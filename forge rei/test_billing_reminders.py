"""Overdue reminders: texts, window, switch, dedupe, caps, QA-only run-now, loop. All fakes, no network.
Run: python3 -m unittest test_billing_reminders  (from `forge rei/`)."""
import inspect
import re
import urllib.error
from contextlib import contextmanager
from datetime import date, datetime
from unittest import mock
import unittest
from zoneinfo import ZoneInfo

import daycare_billing_link as bl
import daycare_billing_reminders as rem
import daycare_ghl
import daycare_supabase
import stripe_io

ET = ZoneInfo("America/New_York")
QA = "99999999-9999-9999-9999-999999999999"
ATOB = "11111111-1111-1111-1111-111111111111"
ATOB2 = "22222222-2222-2222-2222-222222222222"
AMT = "44444444-4444-4444-4444-444444444444"
TODAY = date(2026, 11, 3)
AT_10AM = datetime(2026, 11, 3, 10, 0, tzinfo=ET)
AT_9PM = datetime(2026, 11, 3, 21, 0, tzinfo=ET)


def facts(inv="i1", loc=QA, balance=3000, **over):
    base = {"invoice_id": inv, "invoice_number": "INV-" + inv, "status": "due", "location_id": loc,
            "due_on": "2026-11-06", "balance_cents": balance, "paid_cents": 0, "amount_cents": balance,
            "has_pending_payment": False, "child_ambiguous": False,
            "guardian": {"id": "g1", "name": "Dana Smith", "first_name": "Dana", "phone": "+15555550100",
                         "email": "d@example.com"},
            "child": {"id": "c1", "first_name": "Maya", "last_name": "Smith"}}
    base.update(over)
    return base


def owed_row(inv="i1", kind="upcoming", loc=QA, due="2026-11-06", **over):
    row = {"invoice_id": inv, "guardian_id": "g1", "location_id": loc, "kind": kind, "due_on": due,
           "balance_cents": 3000, "link_send_id": "ls1", "token": "TOK123", "has_pending_payment": False,
           "has_link": True}
    row.update(over)
    return row


class FakeGHL:
    configured = True
    location_id = "LOC"

    def __init__(self, fail_send=None, fail_tags=False, message_status="delivered"):
        self.fail_send, self.fail_tags, self.message_status = fail_send, fail_tags, message_status
        self.posts = []

    def get(self, path, params=None, retries=3):
        if path == "/contacts/search/duplicate":
            return {"contact": {"id": "c9"}}
        if path == "/conversations/search":
            return {"conversations": [{"id": "conv1"}]}
        if path.startswith("/conversations/messages/"):
            return {"status": self.message_status}
        return {}

    def post(self, path, body, retries=2):
        self.posts.append((path, body))
        if path.endswith("/tags") and self.fail_tags:
            raise urllib.error.HTTPError("u", 500, "x", {}, None)
        if path == "/conversations/messages":
            if self.fail_send:
                raise self.fail_send
            return {"messageId": "m%d" % len(self.posts)}
        return {}

    def texts(self):
        return [b["message"] for p, b in self.posts if p == "/conversations/messages"]

    def paths(self):
        return [p for p, _ in self.posts]


class FakeDB:
    """Stands in for the billing_* RPCs with the contract's semantics (dedupe, family/day cap, upsert over failed)."""

    def __init__(self):
        self.mode = "live"
        self.owed = []
        self.facts = {}
        self.calls = []
        self.rows = {}                 # (invoice, kind, due) -> {"id","status","guardian","date","message","error"}
        self.unchecked = []
        self.link_amount = 3000          # what the saved pay link's Stripe page charges
        self.hosted_calls = []
        self.hosted_error = None

    def rpc(self, session, name, body, write=True):
        self.calls.append((name, body))
        if name == "billing_mark_overdue":
            return 0
        if name == "billing_reminders_owed":
            return list(self.owed)
        if name == "billing_reminder_claim":
            key = (body["p_invoice"], body["p_kind"], body["p_due_on"])
            row = self.rows.get(key)
            if row and row["status"] != "failed":
                return None
            guardian = next((o["guardian_id"] for o in self.owed if o["invoice_id"] == body["p_invoice"]), "g1")
            if any(r["guardian"] == guardian and r["date"] == body["p_today"] and r["status"] in ("sending", "sent")
                   and k != key for k, r in self.rows.items()):
                return None
            rid = row["id"] if row else "r%d" % (len(self.rows) + 1)
            self.rows[key] = {"id": rid, "status": "sending", "guardian": guardian, "date": body["p_today"],
                              "message": body["p_message"], "error": None, "amount": body["p_amount_cents"]}
            return rid
        if name == "billing_reminder_result":
            for r in self.rows.values():
                if r["id"] == body["p_id"]:
                    r.update(status=body["p_status"], error=body["p_error"], ghl=body["p_ghl_message_id"])
            return None
        if name == "billing_reminder_staff_review":
            return None
        if name == "billing_create_link_send":
            url = "https://www.atouchofblessing.com/pay/NEWTOK"
            return [{"id": "ls2", "token": "NEWTOK", "pay_url": url,
                     "message": body["p_message"].replace("{{PAY_URL}}", url)}]
        if name == "billing_mark_link_sent":
            return None
        raise AssertionError(name)

    def hosted(self, ctx, location_id):
        self.hosted_calls.append((ctx, location_id))
        if self.hosted_error:
            raise self.hosted_error
        return {"ok": True, "stripe_invoice_id": "in_new", "hosted_url": "https://invoice.stripe.com/i/new",
                "livemode": False, "amount_cents": ctx["balance_cents"], "reused": False, "voided": ["in_old"]}

    def names(self):
        return [n for n, _ in self.calls]

    def statuses(self):
        return sorted(r["status"] for r in self.rows.values())


class Base(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.ghl = FakeGHL()

        @contextmanager
        def at_location(session, loc):
            yield
        patches = [
            mock.patch.object(daycare_supabase, "billing_rpc", side_effect=self.db.rpc),
            mock.patch.object(daycare_supabase, "billing_reminder_mode", side_effect=lambda s, loc: self.db.mode),
            mock.patch.object(daycare_supabase, "billing_invoice_facts",
                              side_effect=lambda s, inv: self.db.facts.get(inv) or facts(inv)),
            mock.patch.object(daycare_supabase, "billing_reminder_unchecked",
                              side_effect=lambda s, loc: self.db.unchecked),
            mock.patch.object(daycare_supabase, "at_location", at_location),
            mock.patch.object(daycare_supabase, "billing_link_amount", side_effect=lambda s, lid: self.db.link_amount),
            mock.patch.object(stripe_io, "ensure_hosted_invoice", side_effect=self.db.hosted),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tick(self, loc=QA, as_of=TODAY, now=AT_10AM, ghl=None):
        return rem.run_location(None, loc, as_of, ghl or self.ghl, now=now)


class Texts(unittest.TestCase):
    def c(self, kind, **kw):
        base = dict(parent="Dana", child="Maya", brand="A Touch of Blessings", amount_cents=3000,
                    due_on="2026-11-06", link="https://www.atouchofblessing.com/pay/TOK")
        base.update(kw)
        return rem.compose(kind, **base)

    def test_the_four_templates_word_for_word(self):
        link = "https://www.atouchofblessing.com/pay/TOK"
        self.assertEqual("Hi Dana, this is A Touch of Blessings. Maya's balance of $30.00 is due Nov 6. "
                         f"You can pay here: {link} Thank you!", self.c("upcoming"))
        self.assertEqual("Hi Dana, this is A Touch of Blessings. Maya's balance of $30.00 is due today. "
                         f"You can pay here: {link} Thank you!", self.c("due_today"))
        self.assertEqual("Hi Dana, this is A Touch of Blessings. We don't show Maya's balance of $30.00 as paid yet. "
                         f"It was due Nov 6. You can pay here: {link} "
                         "If you already paid, thank you, and you can ignore this.", self.c("overdue_1"))
        self.assertEqual("Hi Dana, this is A Touch of Blessings. Maya's balance of $30.00 from Nov 6 is still open. "
                         f"You can pay here: {link} If you have any questions, please call us at (215) 236-5439. "
                         "Thank you.", self.c("overdue_3"))

    def test_no_forbidden_wording_in_any_text(self):
        for kind in rem.TEMPLATES:
            text = self.c(kind).lower()
            for bad in ("stop", "late fee", "fee", "suspend", "terminate", "consequence", "collections"):
                self.assertNotIn(bad, text, (kind, bad))

    def test_no_child_reads_naturally(self):
        self.assertIn("Your balance of $30.00 is due Nov 6.", self.c("upcoming", child=""))
        self.assertIn("We don't show your balance of", self.c("overdue_1", child=""))
        self.assertIn("Your balance of $30.00 from Nov 6", self.c("overdue_3", child=""))

    def test_missing_parent_and_money_format(self):
        self.assertTrue(self.c("upcoming", parent="").startswith("Hi there, this is"))
        self.assertIn("$1,234.56", self.c("upcoming", amount_cents=123456))


class Window(Base):
    def test_hours(self):
        at = lambda h, m=0: datetime(2026, 11, 3, h, m, tzinfo=ET)
        self.assertFalse(rem.in_send_window(at(8, 59)))
        self.assertTrue(rem.in_send_window(at(9)))
        self.assertTrue(rem.in_send_window(at(19, 59)))
        self.assertFalse(rem.in_send_window(at(20)))
        self.assertFalse(rem.in_send_window(at(23)))

    def test_nine_pm_tick_does_nothing_at_all(self):
        self.db.owed = [owed_row()]
        out = self.tick(now=AT_9PM)
        self.assertTrue(out["skipped_window"])
        self.assertEqual([], self.db.calls)
        self.assertEqual([], self.ghl.posts)

    def test_window_uses_eastern_not_utc(self):
        utc_9pm_et = datetime(2026, 11, 4, 2, 0, tzinfo=ZoneInfo("UTC"))      # 9 PM ET (EST)
        self.assertFalse(rem.in_send_window(utc_9pm_et))
        self.assertTrue(rem.in_send_window(datetime(2026, 11, 3, 15, 0, tzinfo=ZoneInfo("UTC"))))   # 10 AM ET


class Sending(Base):
    def test_live_text_uses_the_shared_path_in_order(self):
        self.db.owed = [owed_row()]
        out = self.tick()
        self.assertEqual((1, 0, 0), (out["sent"], out["failed"], out["dry_run"]))
        text = self.ghl.texts()[0]
        self.assertEqual("Hi Dana, this is A Touch of Blessings. Maya's balance of $30.00 is due Nov 6. You can pay "
                         "here: https://www.atouchofblessing.com/pay/TOK123 Thank you!", text)
        self.assertNotIn("{{", text)
        # tag (additive endpoint) BEFORE the text, never an upsert
        self.assertLess(self.ghl.paths().index("/contacts/c9/tags"), self.ghl.paths().index("/conversations/messages"))
        self.assertEqual([{"tags": ["daycare family"]}],
                         [b for p, b in self.ghl.posts if p.endswith("/tags")])
        self.assertNotIn("/contacts/", self.ghl.paths())
        # claim -> text -> result, and the overdue flip happened BEFORE the owed query
        names = self.db.names()
        self.assertLess(names.index("billing_mark_overdue"), names.index("billing_reminders_owed"))
        self.assertLess(names.index("billing_reminders_owed"), names.index("billing_reminder_claim"))
        self.assertEqual(["sent"], self.db.statuses())

    def test_parent_name_comes_from_the_app_not_the_ghl_contact(self):
        self.db.owed = [owed_row()]
        self.db.facts["i1"] = facts(guardian={"id": "g1", "name": "Dana Smith", "first_name": "Dana",
                                              "phone": "+15555550100"})
        self.tick()
        self.assertTrue(self.ghl.texts()[0].startswith("Hi Dana,"))
        self.assertFalse([p for p in self.ghl.paths() if p.startswith("/contacts/c9") and not p.endswith("/tags")])

    def test_amt_text_never_sent_and_brand_for_other_centers(self):
        self.db.owed = [owed_row(loc=AMT)]
        out = self.tick(loc=AMT)
        self.assertEqual([], self.ghl.posts)
        self.assertEqual("off", out["mode"])
        self.db.owed = [owed_row(loc=ATOB)]
        self.db.facts["i1"] = facts(loc=ATOB)
        self.tick(loc=ATOB)
        self.assertIn("this is A Touch of Blessings.", self.ghl.texts()[0])

    def test_double_run_sends_once(self):
        self.db.owed = [owed_row()]
        self.tick()
        self.tick()
        self.assertEqual(1, len(self.ghl.texts()))

    def test_family_cap_one_text_per_family_per_day(self):
        self.db.owed = [owed_row("i1"), owed_row("i2", kind="due_today", due="2026-11-03")]
        out = self.tick()
        self.assertEqual(1, out["sent"])
        self.assertEqual(1, len(self.ghl.texts()))
        self.assertEqual(1, out["skipped"]["already_sent_or_family_cap"])

    def test_paid_mid_sequence_sends_nothing(self):
        self.db.owed = [owed_row(kind="overdue_1")]
        self.db.facts["i1"] = facts(status="paid", balance=0)
        out = self.tick()
        self.assertEqual([], self.ghl.posts)
        self.assertNotIn("billing_reminder_claim", self.db.names())
        self.assertEqual(1, out["skipped"]["closed"])
        # and a tick where the database no longer lists it at all
        self.db.owed = []
        self.assertEqual(0, self.tick()["sent"])

    def test_balance_zero_even_if_status_still_overdue(self):
        self.db.owed = [owed_row(kind="overdue_3")]
        self.db.facts["i1"] = facts(status="overdue", balance=0)
        self.tick()
        self.assertEqual([], self.ghl.posts)

    def test_partial_payment_quotes_the_remaining_balance(self):
        self.db.owed = [owed_row(kind="overdue_3", due="2026-10-31")]
        self.db.facts["i1"] = facts(status="overdue", balance=2000, paid_cents=1000, amount_cents=3000,
                                    due_on="2026-10-31")
        self.db.link_amount = 2000                      # the link was already refreshed to the balance
        self.tick(as_of=date(2026, 11, 3))
        self.assertIn("Maya's balance of $20.00 from Oct 31 is still open", self.ghl.texts()[0])
        claim = [b for n, b in self.db.calls if n == "billing_reminder_claim"][0]
        self.assertEqual(2000, claim["p_amount_cents"])

    def test_void_invoice_no_text(self):
        self.db.owed = [owed_row()]
        self.db.facts["i1"] = facts(status="void")
        self.tick()
        self.assertEqual([], self.ghl.posts)

    def test_pending_payment_skips_the_day(self):
        self.db.owed = [owed_row(has_pending_payment=True)]
        out = self.tick()
        self.assertEqual([], self.ghl.posts)
        self.assertEqual(1, out["skipped"]["payment_processing"])
        self.db.owed = [owed_row()]
        self.db.facts["i1"] = facts(has_pending_payment=True)
        self.tick()
        self.assertEqual([], self.ghl.posts)
        self.assertNotIn("billing_reminder_claim", self.db.names())

    def test_no_link_no_text_and_flagged(self):
        self.db.owed = [owed_row(has_link=False, token=None, link_send_id=None)]
        out = self.tick()
        self.assertEqual([], self.ghl.posts)
        self.assertEqual(["i1"], out["flagged"])
        self.assertEqual(["failed"], self.db.statuses())
        self.assertIn("No pay link", list(self.db.rows.values())[0]["error"])

    def test_link_present_flag_but_blank_token_is_still_no_link(self):
        self.db.owed = [owed_row(token="")]
        self.tick()
        self.assertEqual([], self.ghl.posts)

    def test_tag_failure_warns_and_still_texts(self):
        self.db.owed = [owed_row()]
        ghl = FakeGHL(fail_tags=True)
        out = self.tick(ghl=ghl)
        self.assertEqual(1, out["sent"])
        self.assertEqual(1, len(ghl.texts()))
        self.assertTrue(out["warnings"])

    def test_definite_rejection_is_retried_next_tick(self):
        self.db.owed = [owed_row()]
        bad = FakeGHL(fail_send=urllib.error.HTTPError("u", 400, "bad", {}, None))
        out = self.tick(ghl=bad)
        self.assertEqual((0, 1), (out["sent"], out["failed"]))
        self.assertEqual(["failed"], self.db.statuses())
        good = FakeGHL()
        self.assertEqual(1, self.tick(ghl=good)["sent"])           # claim upserts over the failed row

    def test_unknown_outcome_is_never_retried(self):
        class GHLSendUnknown(RuntimeError):
            pass
        self.db.owed = [owed_row()]
        out = self.tick(ghl=FakeGHL(fail_send=GHLSendUnknown("timeout")))
        self.assertEqual(1, out["failed"])
        self.assertEqual(["sent"], self.db.statuses())              # held as 'sent' with a note
        self.assertIn("Unknown whether", list(self.db.rows.values())[0]["error"])
        good = FakeGHL()
        self.tick(ghl=good)
        self.assertEqual([], good.texts())

    def test_one_bad_invoice_does_not_stop_the_rest(self):
        self.db.owed = [owed_row("bad"), owed_row("i2", kind="due_today", due="2026-11-03")]
        self.db.owed[1]["guardian_id"] = "g2"
        real = self.db.facts

        def boom(session, inv):
            if inv == "bad":
                raise daycare_supabase.DaycareError(404, "gone")
            return facts(inv, **({} if inv != "i2" else {"guardian": {"id": "g2", "name": "Lee Park",
                                                                      "first_name": "Lee", "phone": "+15555550111"}}))
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", side_effect=boom):
            out = self.tick()
        self.assertEqual(1, out["sent"])
        self.assertEqual(1, out["skipped"]["row_error"])

    def test_glitch_with_ghl_not_configured_sends_nothing(self):
        self.db.owed = [owed_row()]
        ghl = FakeGHL()
        ghl.configured = False
        out = self.tick(ghl=ghl)
        self.assertFalse(out["ok"])
        self.assertNotIn("billing_reminders_owed", self.db.names())


class Modes(Base):
    def test_dry_run_stores_the_message_and_sends_nothing(self):
        self.db.mode = "dry_run"
        self.db.owed = [owed_row()]
        out = self.tick()
        self.assertEqual((1, 0), (out["dry_run"], out["sent"]))
        self.assertEqual([], self.ghl.posts)
        self.assertEqual(["dry_run"], self.db.statuses())
        self.assertIn("pay/TOK123", list(self.db.rows.values())[0]["message"])

    def test_dry_run_does_not_queue_the_owner_email(self):
        self.db.mode = "dry_run"
        self.db.owed = [owed_row(kind="staff_review", due="2026-10-27")]
        self.tick()
        self.assertNotIn("billing_reminder_staff_review", self.db.names())

    def test_off_or_unreadable_switch_does_nothing(self):
        for mode in ("off", "weird", ""):
            self.db.mode = mode
            self.db.calls.clear()
            self.db.owed = [owed_row()]
            self.tick()
            self.assertNotIn("billing_reminders_owed", self.db.names())
            self.assertNotIn("billing_reminder_claim", self.db.names())
        self.assertEqual([], self.ghl.posts)

    def test_staff_review_live_queues_owner_email_not_a_parent_text(self):
        self.db.owed = [owed_row(kind="staff_review", due="2026-10-27")]
        out = self.tick()
        self.assertEqual(1, out["reviews"])
        self.assertEqual([], self.ghl.posts)
        self.assertEqual({"p_invoice": "i1", "p_due_on": "2026-10-27"},
                         [b for n, b in self.db.calls if n == "billing_reminder_staff_review"][0])


class OverdueFlip(Base):
    def test_flips_before_owed_for_as_of(self):
        self.db.owed = []
        self.tick()
        self.assertEqual(["billing_mark_overdue", "billing_reminders_owed"], self.db.names())
        self.assertEqual({"p_today": "2026-11-03"}, self.db.calls[0][1])

    def test_run_now_with_a_future_as_of_flips_for_that_date(self):
        out = self.tick(as_of=date(2026, 11, 10))
        self.assertEqual({"p_today": "2026-11-10"}, self.db.calls[0][1])
        self.assertEqual("billing_mark_overdue", self.db.names()[0])
        self.assertEqual(0, out["marked_overdue"])


class StaleLink(Base):
    """The text and the Stripe page must show the same amount."""

    def stale(self, balance=2000, link=3000, kind="overdue_3", due="2026-10-31"):
        self.db.owed = [owed_row(kind=kind, due=due)]
        self.db.facts["i1"] = facts(status="overdue", balance=balance, paid_cents=3000 - balance,
                                    amount_cents=3000, due_on=due)
        self.db.link_amount = link

    def test_matching_amount_reuses_the_link_and_never_calls_stripe(self):
        self.stale(balance=3000, link=3000)
        self.tick()
        self.assertEqual([], self.db.hosted_calls)
        self.assertNotIn("billing_create_link_send", self.db.names())
        self.assertIn("/pay/TOK123", self.ghl.texts()[0])

    def test_mismatch_refreshes_through_the_existing_path_and_uses_the_new_token(self):
        self.stale()
        out = self.tick()
        # Stripe invoice built for the CURRENT balance, then the link row for exactly that amount
        ctx, loc = self.db.hosted_calls[0]
        self.assertEqual((2000, QA), (ctx["balance_cents"], loc))
        create = [b for n, b in self.db.calls if n == "billing_create_link_send"][0]
        self.assertEqual(2000, create["p_amount_cents"])
        self.assertIn("{{PAY_URL}}", create["p_message"])
        # the text carries the NEW token and the new amount; the old token is gone
        text = self.ghl.texts()[0]
        self.assertIn("https://www.atouchofblessing.com/pay/NEWTOK", text)
        self.assertNotIn("TOK123", text)
        self.assertIn("$20.00", text)
        claim = [b for n, b in self.db.calls if n == "billing_reminder_claim"][0]
        self.assertEqual((2000, "ls2", text), (claim["p_amount_cents"], claim["p_link_send_id"], claim["p_message"]))
        # quoted amount == link row amount == claim amount, and the link row is marked sent with the GHL id
        self.assertEqual(create["p_amount_cents"], claim["p_amount_cents"])
        marks = [b for n, b in self.db.calls if n == "billing_mark_link_sent"]
        self.assertEqual([("ls2", "sent")], [(m["p_id"], m["p_status"]) for m in marks])
        self.assertTrue(marks[0]["p_ghl_message_id"])
        self.assertEqual((1, 0), (out["sent"], out["failed"]))
        # refresh happens BEFORE the claim
        names = self.db.names()
        self.assertLess(names.index("billing_create_link_send"), names.index("billing_reminder_claim"))

    def test_unknown_link_amount_counts_as_stale(self):
        self.stale(balance=3000, link=None)
        self.tick()
        self.assertEqual(1, len(self.db.hosted_calls))

    def test_refresh_failure_sends_nothing_stores_the_error_flags_and_the_tick_continues(self):
        self.stale()
        self.db.owed.append(owed_row("i2", kind="due_today", due="2026-11-03", guardian_id="g2", token="T2"))
        self.db.facts["i2"] = facts("i2", guardian={"id": "g2", "name": "Lee Park", "first_name": "Lee",
                                                      "phone": "+15555550111"})
        calls = {"n": 0}

        def hosted(ctx, loc):
            calls["n"] += 1
            if ctx["invoice_id"] == "i1":
                raise stripe_io.StripeError(502, "Stripe is temporarily unavailable", "upstream_unavailable")
            return {"stripe_invoice_id": "x", "hosted_url": "u", "livemode": False}
        self.db.link_amount = 3000
        with mock.patch.object(stripe_io, "ensure_hosted_invoice", side_effect=hosted):
            # i2's balance (3000) equals the link amount, so only i1 needs Stripe and it fails
            out = self.tick()
        self.assertEqual(["i1"], out["flagged"])
        self.assertEqual(1, out["skipped"]["link_refresh_failed"])
        row = self.db.rows[("i1", "overdue_3", "2026-10-31")]
        self.assertEqual("failed", row["status"])
        self.assertIn("Could not refresh the pay link", row["error"])
        self.assertIn("Stripe is temporarily unavailable", row["error"])
        self.assertNotIn("billing_create_link_send", self.db.names())       # no link row for a failed refresh
        self.assertEqual(1, out["sent"])                                     # the other family still got its text
        self.assertEqual(1, len(self.ghl.texts()))
        self.assertIn("Hi Lee,", self.ghl.texts()[0])

    def test_database_failure_during_refresh_is_handled_the_same_way(self):
        self.stale()
        real = self.db.rpc

        def rpc(session, name, body, write=True):
            if name == "billing_create_link_send":
                raise daycare_supabase.DaycareError(409, "x", "conflict")
            return real(session, name, body, write)
        with mock.patch.object(daycare_supabase, "billing_rpc", side_effect=rpc):
            out = self.tick()
        self.assertEqual([], self.ghl.posts)
        self.assertEqual(["i1"], out["flagged"])

    def test_dry_run_never_touches_stripe_or_makes_a_link(self):
        self.db.mode = "dry_run"
        self.stale()
        out = self.tick()
        self.assertEqual([], self.db.hosted_calls)
        self.assertNotIn("billing_create_link_send", self.db.names())
        self.assertNotIn("billing_mark_link_sent", self.db.names())
        self.assertEqual([], self.ghl.posts)
        self.assertEqual(1, out["dry_run"])
        row = self.db.rows[("i1", "overdue_3", "2026-10-31")]
        self.assertEqual("dry_run", row["status"])
        self.assertIn("stale", row["error"])
        self.assertIn("$20.00", row["message"])

    def test_dry_run_with_a_matching_link_has_no_note(self):
        self.db.mode = "dry_run"
        self.stale(balance=3000, link=3000)
        self.tick()
        self.assertIsNone(list(self.db.rows.values())[0]["error"])

    def test_failed_text_after_a_refresh_marks_the_new_link_failed(self):
        self.stale()
        out = self.tick(ghl=FakeGHL(fail_send=urllib.error.HTTPError("u", 400, "bad", {}, None)))
        self.assertEqual(1, out["failed"])
        marks = [b for n, b in self.db.calls if n == "billing_mark_link_sent"]
        self.assertEqual("failed", marks[0]["p_status"])

    def test_family_cap_after_a_refresh_does_not_leave_a_sent_link_row(self):
        self.stale()
        self.db.rows[("zz", "upcoming", "d")] = {"id": "r0", "status": "sent", "guardian": "g1", "date": "2026-11-03"}
        out = self.tick()
        self.assertEqual([], self.ghl.posts)
        self.assertEqual(1, out["skipped"]["already_sent_or_family_cap"])
        marks = [b for n, b in self.db.calls if n == "billing_mark_link_sent"]
        self.assertEqual("failed", marks[0]["p_status"])

    def test_the_refresh_path_is_the_existing_one_not_a_copy(self):
        source = inspect.getsource(rem)
        self.assertIn("bl.create_link", source)
        self.assertNotIn("ensure_hosted_invoice", source)
        self.assertNotIn("billing_create_link_send", source)
        self.assertIn("ensure_hosted_invoice", inspect.getsource(bl.create_link))
        self.assertIn("billing_create_link_send", inspect.getsource(bl.create_link))


class RunNow(Base):
    def go(self, body, now=AT_10AM):
        return rem.run_now(None, body, self.ghl, now=now)

    def test_real_centers_refused_whatever_as_of_says(self):
        for body in ({"location_id": ATOB, "as_of": "2026-11-03"}, {"location_id": ATOB2},
                     {"location_id": AMT, "as_of": "garbage"}, {"location_id": ATOB, "as_of": ""},
                     {"location_id": "", "as_of": "2026-11-03"}, {}, {"as_of": "2026-11-03"},
                     {"location_id": "../etc", "as_of": None}):
            with self.assertRaises(bl.BillingLinkError) as cm:
                self.go(body)
            self.assertEqual((403, "qa_only"), (cm.exception.status, cm.exception.code), body)
        self.assertEqual([], self.db.calls)
        self.assertEqual([], self.ghl.posts)

    def test_qa_malformed_as_of_is_a_400(self):
        for bad in ("11/03/2026", "tomorrow", "2026-13-40", "9999-01-01"):
            with self.assertRaises(bl.BillingLinkError) as cm:
                self.go({"location_id": QA, "as_of": bad})
            self.assertEqual(400, cm.exception.status, bad)
        self.assertEqual([], self.db.calls)

    def test_qa_missing_as_of_means_today(self):
        self.db.owed = [owed_row(kind="due_today", due="2026-11-03")]
        out = self.go({"location_id": QA})
        self.assertEqual("2026-11-03", out["as_of"])
        self.assertEqual(1, out["sent"])

    def test_qa_with_as_of_runs_and_uppercase_id_is_fine(self):
        self.db.owed = [owed_row(kind="overdue_1", due="2026-11-02")]
        out = self.go({"location_id": QA.upper(), "as_of": "2026-11-03"})
        self.assertEqual(1, out["sent"])

    def test_nine_pm_run_now_sends_nothing(self):
        self.db.owed = [owed_row()]
        out = self.go({"location_id": QA, "as_of": "2026-11-03"}, now=AT_9PM)
        self.assertTrue(out["skipped_window"])
        self.assertEqual([], self.ghl.posts)

    def test_route_is_registered_with_the_same_gates_as_link_send(self):
        import connector
        post = inspect.getsource(connector.Handler._handle_daycare_post)
        self.assertGreaterEqual(post.count("/api/daycare/billing/reminders/run"), 2)   # allowlist + dispatch
        i = post.index('path == "/api/daycare/billing/reminders/run"')
        self.assertLess(post.index("validate_write_request"), i)                        # origin/HTTPS check first
        self.assertLess(post.index("_daycare_resolve_session"), i)                      # signed-in session first
        self.assertIn("daycare_billing_reminders.run_now", post[i:i + 300])


class Delivery(Base):
    def test_undelivered_reminder_gets_a_carrier_note_but_stays_sent(self):
        self.db.unchecked = [{"id": "r9", "ghl_message_id": "m9"}]
        self.db.rows[("x", "upcoming", "d")] = {"id": "r9", "status": "sent", "guardian": "g1", "date": "d"}
        self.tick(ghl=FakeGHL(message_status="undelivered"))
        res = [b for n, b in self.db.calls if n == "billing_reminder_result" and b["p_id"] == "r9"][0]
        self.assertEqual(("sent", "m9"), (res["p_status"], res["p_ghl_message_id"]))
        self.assertIn("undelivered", res["p_error"])

    def test_delivered_reminder_writes_nothing(self):
        self.db.unchecked = [{"id": "r9", "ghl_message_id": "m9"}]
        self.tick(ghl=FakeGHL(message_status="delivered"))
        self.assertNotIn("billing_reminder_result", self.db.names())


class Loop(Base):
    def test_run_all_visits_memberships_plus_qa_skips_amt_and_survives_a_bad_center(self):
        seen = []

        def run_location(session, loc, today, ghl, now=None):
            if loc == ATOB2:
                raise RuntimeError("cannot stand there")
            seen.append(loc)
            return {"location_id": loc}
        locs = {"locations": [{"id": ATOB}, {"id": ATOB2}, {"id": AMT}]}
        with mock.patch.object(daycare_supabase, "list_locations", return_value=locs), \
                mock.patch.object(rem, "run_location", side_effect=run_location):
            out = rem.run_all(lambda: object(), self.ghl, now=AT_10AM)
        self.assertEqual([ATOB, QA], seen)                      # AMT never; QA added; bad center skipped
        self.assertEqual(1, out["errors"])

    def test_run_all_outside_window_does_not_even_sign_in(self):
        called = []
        out = rem.run_all(lambda: called.append(1), self.ghl, now=AT_9PM)
        self.assertTrue(out["skipped_window"])
        self.assertEqual([], called)

    def test_run_all_without_a_session_reports_it(self):
        self.assertFalse(rem.run_all(lambda: None, self.ghl, now=AT_10AM)["ok"])

    def test_loop_survives_a_failing_tick_and_beats_each_time(self):
        class Stop(Exception):
            pass
        beats, sleeps = [], []

        def sleep(sec):
            sleeps.append(sec)
            if len(sleeps) >= 3:
                raise Stop()
        results = iter([RuntimeError("boom"), {"ok": True}, {"ok": True, "errors": 1}])

        def run_all(*a, **k):
            r = next(results)
            if isinstance(r, Exception):
                raise r
            return r
        import forge_heartbeat
        import forge_ops
        with mock.patch.object(rem, "run_all", side_effect=run_all), \
                mock.patch.object(rem.time, "sleep", side_effect=sleep), \
                mock.patch.object(forge_ops, "paused", return_value=False), \
                mock.patch.object(forge_heartbeat, "beat", side_effect=lambda *a, **k: beats.append(k.get("error"))):
            with self.assertRaises(Stop):
                rem.run_forever(lambda: None, self.ghl, interval=3600)
        self.assertEqual(["RuntimeError", None, "1 center(s) skipped"], beats)
        self.assertEqual([3600, 3600, 3600], sleeps)

    def test_loop_is_only_started_on_the_box(self):
        import connector
        source = inspect.getsource(connector).split("def main():", 1)[1]
        i = source.index("daycare_billing_reminders.run_forever")
        before = source[:i]
        self.assertGreater(before.rfind("if LOOPS_ENABLED:"), before.rfind("\n    else:"))   # inside the box-only block


class Reads(unittest.TestCase):
    def test_timeline_adds_reminders_when_the_rpc_has_none(self):
        rows = [{"kind": "upcoming", "status": "sent", "sent_at": "t", "amount_cents": 3000, "error": None}]
        with mock.patch.object(daycare_supabase, "billing_send_rows", return_value=[]), \
                mock.patch.object(daycare_supabase, "billing_rpc",
                                  return_value={"invoice": {}, "sends": [], "payments": [], "alerts": []}), \
                mock.patch.object(daycare_supabase, "billing_reminder_rows", return_value=rows):
            out = bl.timeline(None, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", None)
        self.assertEqual(rows, out["reminders"])

    def test_timeline_keeps_the_rpcs_own_reminders(self):
        with mock.patch.object(daycare_supabase, "billing_send_rows", return_value=[]), \
                mock.patch.object(daycare_supabase, "billing_rpc", return_value={"reminders": [{"kind": "x"}]}), \
                mock.patch.object(daycare_supabase, "billing_reminder_rows") as reader:
            out = bl.timeline(None, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", None)
        self.assertEqual([{"kind": "x"}], out["reminders"])
        reader.assert_not_called()

    def test_billing_list_marks_needs_review(self):
        def rest(session, method, resource, **kw):
            if resource == "invoices":
                return [{"id": "i1"}, {"id": "i2"}]
            if resource == "billing_reminders":
                return [{"invoice_id": "i2"}]
            return []
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest), \
                mock.patch.object(daycare_supabase, "active_location", return_value=ATOB):
            out = daycare_supabase.get_billing(None)
        self.assertEqual({"i1": False, "i2": True}, {i["id"]: i["needs_review"] for i in out["invoices"]})

    def test_reminder_mode_fails_closed(self):
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=daycare_supabase.DaycareError(403, "x")):
            self.assertEqual("off", daycare_supabase.billing_reminder_mode(None, ATOB))
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", return_value=[]):
            self.assertEqual("off", daycare_supabase.billing_reminder_mode(None, ATOB))
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", return_value=[{"reminder_mode": "LIVE"}]):
            self.assertEqual("live", daycare_supabase.billing_reminder_mode(None, QA))
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", return_value=[{"reminder_mode": "yes please"}]):
            self.assertEqual("off", daycare_supabase.billing_reminder_mode(None, QA))

    def test_new_rpcs_are_whitelisted_and_others_are_not(self):
        for name in ("billing_reminders_owed", "billing_reminder_claim", "billing_reminder_result",
                     "billing_reminder_staff_review", "billing_mark_overdue"):
            self.assertIn(name, daycare_supabase._BILLING_RPCS)
        with self.assertRaises(daycare_supabase.DaycareError):
            daycare_supabase.billing_rpc(None, "billing_drop_everything", {})


class ShareSendPath(unittest.TestCase):
    def test_reminders_have_no_second_ghl_send_path(self):
        source = inspect.getsource(rem)
        self.assertIn("deliver_text", source)
        for forbidden in ("send_sms", "ensure_family_contact", "add_family_tags", "/conversations/messages\""):
            self.assertNotIn(forbidden + "(", source.replace("daycare_ghl._brand_link", ""), forbidden)
        self.assertNotRegex(source, r"client\.post\(|ghl\.post\(")


if __name__ == "__main__":
    unittest.main()
