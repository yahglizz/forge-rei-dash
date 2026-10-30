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
REAL_FAMILY_BUSY = daycare_supabase.billing_reminder_family_busy      # Base patches the module attribute per test
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
        self.recent_link = False         # a link row created/sent/delivered < 120 s ago
        self.link_sent_today = False     # the owner's pay-link text for this family went out today (ET)
        self.hosted_calls = []
        self.hosted_error = None

    def rpc(self, session, name, body, write=True):
        self.calls.append((name, body))
        if name == "billing_mark_overdue":
            return 0
        if name == "billing_reminders_owed":
            return [] if self.mode == "off" else list(self.owed)         # the database returns nothing for an off center
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
        bl._INFLIGHT.clear()
        bl._RECENT.clear()

        self.depth = 0                 # how many center switches are open right now
        self.max_depth = 0

        @contextmanager
        def at_location(session, loc):
            self.depth += 1
            self.max_depth = max(self.max_depth, self.depth)
            try:
                yield
            finally:
                self.depth -= 1
        patches = [
            mock.patch.object(daycare_supabase, "billing_rpc", side_effect=self.db.rpc),
            mock.patch.object(daycare_supabase, "billing_reminder_mode", side_effect=lambda s, loc: self.db.mode),
            mock.patch.object(daycare_supabase, "billing_invoice_facts",
                              side_effect=lambda s, inv: self.db.facts.get(inv) or facts(inv)),
            mock.patch.object(daycare_supabase, "billing_reminder_unchecked",
                              side_effect=lambda s, loc: self.db.unchecked),
            mock.patch.object(daycare_supabase, "at_location", at_location),
            mock.patch.object(daycare_supabase, "billing_link_amount", side_effect=lambda s, lid: self.db.link_amount),
            mock.patch.object(daycare_supabase, "billing_recent_send",
                              side_effect=lambda s, inv, secs=120: self.db.recent_link),
            mock.patch.object(daycare_supabase, "billing_reminder_family_busy",
                              side_effect=lambda s, gid, today: self.db.link_sent_today or any(
                                  r["guardian"] == gid and r["date"] == today and r["status"] in ("sending", "sent")
                                  for r in self.db.rows.values())),
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
        self.assertNotIn("billing_reminder_claim", self.db.names())
        self.assertEqual([], ghl.posts)


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

    def test_off_center_never_enters_the_center_or_sends(self):
        self.db.mode = "off"
        self.db.owed = [owed_row()]
        self.tick()
        self.assertEqual(0, self.max_depth)                  # the shared profile's active center is never touched
        self.assertNotIn("billing_reminder_claim", self.db.names())
        self.assertEqual([], self.ghl.posts)

    def test_unreadable_switch_with_rows_owed_does_nothing(self):
        self.db.owed = [owed_row()]
        for mode in ("", "weird"):
            self.db.mode = mode
            self.db.calls.clear()
            self.tick()
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
        self.assertEqual({"p_today": "2026-11-03", "p_location": QA}, self.db.calls[0][1])

    def test_run_now_with_a_future_as_of_flips_for_that_date(self):
        out = self.tick(as_of=date(2026, 11, 10))
        self.assertEqual({"p_today": "2026-11-10", "p_location": QA}, self.db.calls[0][1])
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

    def test_family_cap_is_checked_before_stripe(self):
        self.stale()
        self.db.rows[("zz", "upcoming", "d")] = {"id": "r0", "status": "sent", "guardian": "g1", "date": "2026-11-03"}
        out = self.tick()
        self.assertEqual([], self.ghl.posts)
        self.assertEqual([], self.db.hosted_calls)                         # Stripe never touched
        self.assertNotIn("billing_create_link_send", self.db.names())
        self.assertEqual(1, out["skipped"]["already_sent_or_family_cap"])

    def test_claim_refusal_after_a_refresh_leaves_no_sent_link_row(self):
        # the race the pre-check cannot see: another tick claimed the family between the read and the claim
        self.stale()
        self.db.rows[("zz", "upcoming", "d")] = {"id": "r0", "status": "sent", "guardian": "g1", "date": "2026-11-03"}
        with mock.patch.object(daycare_supabase, "billing_reminder_family_busy", return_value=False):
            out = self.tick()
        self.assertEqual([], self.ghl.posts)
        self.assertEqual(1, out["skipped"]["already_sent_or_family_cap"])
        marks = [b for n, b in self.db.calls if n == "billing_mark_link_sent"]
        self.assertEqual("failed", marks[0]["p_status"])

    def test_no_phone_is_caught_before_stripe(self):
        self.stale()
        self.db.facts["i1"]["guardian"]["phone"] = ""
        out = self.tick()
        self.assertEqual([], self.db.hosted_calls)
        self.assertEqual(["i1"], out["flagged"])
        self.assertEqual(1, out["skipped"]["no_phone"])
        self.assertEqual("No phone number on file.", self.db.rows[("i1", "overdue_3", "2026-10-31")]["error"])

    def test_a_link_built_in_the_last_two_minutes_vetoes_the_refresh(self):
        self.stale()
        self.db.recent_link = True                        # e.g. the owner just tapped Send
        out = self.tick()
        self.assertEqual([], self.db.hosted_calls)
        self.assertEqual([], self.ghl.posts)
        self.assertEqual(1, out["skipped"]["link_busy"])
        self.assertEqual([], out["flagged"])              # not an error: the next tick decides
        self.assertNotIn("billing_reminder_claim", self.db.names())

    def test_a_link_build_in_flight_in_this_process_vetoes_the_refresh(self):
        self.stale()
        bl._INFLIGHT.add("i1")
        out = self.tick()
        self.assertEqual([], self.db.hosted_calls)
        self.assertEqual(1, out["skipped"]["link_busy"])

    def test_the_slot_is_released_after_success_and_after_failure(self):
        self.stale()
        self.tick()
        self.assertNotIn("i1", bl._INFLIGHT)
        self.assertIn("i1", bl._RECENT)                    # a text just went out: owner Send waits 120 s
        bl._RECENT.clear()
        self.db.rows.clear()
        self.db.hosted_error = stripe_io.StripeError(502, "down", "upstream_unavailable")
        self.tick()
        self.assertNotIn("i1", bl._INFLIGHT)
        self.assertNotIn("i1", bl._RECENT)

    def test_an_owner_send_right_after_a_reminder_refresh_is_refused(self):
        self.stale()
        self.tick()
        with self.assertRaises(bl.BillingLinkError) as cm:
            bl.reserve_link(None, "i1", recent=False)
        self.assertEqual(409, cm.exception.status)

    def test_owner_send_and_reminder_share_one_guard(self):
        self.assertIn("reserve_link", inspect.getsource(bl.send))
        self.assertIn("reserve_link", inspect.getsource(rem._process_row))

    def test_dry_run_does_not_reserve_or_read_the_veto_checks(self):
        self.db.mode = "dry_run"
        self.stale()
        self.db.recent_link = True
        out = self.tick()
        self.assertEqual(1, out["dry_run"])                # dry_run ignores the live-only vetoes
        self.assertEqual(set(), bl._INFLIGHT)

    def test_the_refresh_path_is_the_existing_one_not_a_copy(self):
        source = inspect.getsource(rem)
        self.assertIn("bl.create_link", source)
        self.assertNotIn("ensure_hosted_invoice", source)
        self.assertNotIn("billing_create_link_send", source)
        self.assertIn("ensure_hosted_invoice", inspect.getsource(bl.create_link))
        self.assertIn("billing_create_link_send", inspect.getsource(bl.create_link))


class CenterSwitch(Base):
    """The center switch (a process-wide lock on a profile shared with the dashboard) is held for the
    phase-1 reads only; Stripe, GHL and the claim/result writes happen after it is released."""

    def test_network_and_writes_run_outside_the_switch_reads_run_inside(self):
        log = []
        real_rpc, real_hosted = self.db.rpc, self.db.hosted
        self.db.link_amount = 2000                       # stale -> exercises the Stripe refresh too
        self.db.owed = [owed_row(kind="overdue_3", due="2026-10-31")]
        self.db.facts["i1"] = facts(status="overdue", balance=3000, due_on="2026-10-31")

        def rpc(session, name, body, write=True):
            log.append((name, self.depth))
            return real_rpc(session, name, body, write)

        def hosted(ctx, loc):
            log.append(("stripe", self.depth))
            return real_hosted(ctx, loc)
        real_post = self.ghl.post

        def post(path, body, retries=2):
            log.append(("ghl " + path, self.depth))
            return real_post(path, body, retries)
        self.ghl.post = post
        with mock.patch.object(daycare_supabase, "billing_rpc", side_effect=rpc), \
                mock.patch.object(stripe_io, "ensure_hosted_invoice", side_effect=hosted), \
                mock.patch.object(daycare_supabase, "billing_invoice_facts",
                                  side_effect=lambda s, inv: log.append(("facts", self.depth)) or self.db.facts[inv]), \
                mock.patch.object(daycare_supabase, "billing_link_amount",
                                  side_effect=lambda s, lid: log.append(("link_amount", self.depth)) or 2000):
            out = self.tick()
        self.assertEqual(1, out["sent"])
        inside = {n for n, d in log if d > 0}
        outside = {n for n, d in log if d == 0}
        self.assertEqual({"facts", "link_amount"}, inside, log)               # the only reads that need the switch
        for name in ("billing_mark_overdue", "billing_reminders_owed", "stripe", "billing_create_link_send",
                     "billing_reminder_claim", "billing_reminder_result",
                     "ghl /conversations/messages", "ghl /contacts/c9/tags", "billing_mark_link_sent"):
            self.assertIn(name, outside, (name, log))
            self.assertNotIn(name, inside, (name, log))
        self.assertEqual(0, self.depth)

    def test_veto_reads_happen_inside_the_switch_before_any_stripe_call(self):
        log = []
        self.db.link_amount = 2000
        self.db.owed = [owed_row(kind="overdue_3", due="2026-10-31")]
        self.db.facts["i1"] = facts(status="overdue", balance=3000, due_on="2026-10-31")
        real_hosted = self.db.hosted
        with mock.patch.object(daycare_supabase, "billing_recent_send",
                               side_effect=lambda s, inv, secs=120: log.append(("recent", self.depth)) or False), \
                mock.patch.object(daycare_supabase, "billing_reminder_family_busy",
                                  side_effect=lambda s, g, d: log.append(("family", self.depth)) or False), \
                mock.patch.object(stripe_io, "ensure_hosted_invoice",
                                  side_effect=lambda c, l: log.append(("stripe", self.depth)) or real_hosted(c, l)):
            self.tick()
        self.assertEqual([("recent", 1), ("family", 1), ("stripe", 0)], log)

    def test_run_now_and_run_all_open_exactly_one_switch(self):
        self.db.owed = [owed_row(kind="due_today", due="2026-11-03")]
        rem.run_now(None, {"location_id": QA, "as_of": "2026-11-03"}, self.ghl, now=AT_10AM)
        self.assertEqual(1, self.max_depth)
        self.max_depth = 0
        with mock.patch.object(daycare_supabase, "list_locations", return_value={"locations": [{"id": ATOB}]}):
            rem.run_all(lambda: object(), self.ghl, now=AT_10AM)
        self.assertEqual(1, self.max_depth)

    def test_switch_is_released_even_when_a_read_fails(self):
        self.db.owed = [owed_row()]
        with mock.patch.object(daycare_supabase, "billing_reminder_mode", side_effect=RuntimeError("db")):
            with self.assertRaises(RuntimeError):
                self.tick()
        self.assertEqual(0, self.depth)
        self.assertTrue(rem._TICK_LOCK.acquire(blocking=False))     # and the tick lock too
        rem._TICK_LOCK.release()

    def flips(self):
        return [b for n, b in self.db.calls if n == "billing_mark_overdue"]

    def test_location_is_always_passed_to_the_flip(self):
        self.tick(loc=ATOB)
        self.assertEqual([{"p_today": "2026-11-03", "p_location": ATOB}], self.flips())

    def test_run_now_passes_the_qa_location_even_for_a_simulated_date(self):
        rem.run_now(None, {"location_id": QA, "as_of": "2026-11-10"}, self.ghl, now=AT_10AM)
        self.assertEqual([{"p_today": "2026-11-10", "p_location": QA}], self.flips())

    def test_box_loop_passes_each_centers_own_location(self):
        locs = {"locations": [{"id": ATOB}, {"id": ATOB2}, {"id": AMT}]}
        with mock.patch.object(daycare_supabase, "list_locations", return_value=locs):
            rem.run_all(lambda: object(), self.ghl, now=AT_10AM)
        self.assertEqual([ATOB, ATOB2, QA], [b["p_location"] for b in self.flips()])    # AMT never; QA added
        for b in self.flips():
            self.assertEqual("2026-11-03", b["p_today"])

    def test_no_call_left_with_the_one_argument_signature(self):
        source = inspect.getsource(rem)
        calls = [m.start() for m in re.finditer(r'_rpc\(session, "billing_mark_overdue"', source)]
        self.assertEqual(1, len(calls))
        self.assertIn('"p_location"', source[calls[0]:calls[0] + 160])


class OverdueFlipScope(Base):
    def test_flip_and_owed_run_outside_the_switch_and_nothing_owed_means_no_switch(self):
        for mode in ("off", "dry_run", "live"):
            self.db.mode = mode
            self.db.calls.clear()
            self.db.owed = []
            self.tick()
            self.assertEqual(["billing_mark_overdue", "billing_reminders_owed"], self.db.names(), mode)
            self.assertEqual(0, self.max_depth, mode)

    def test_flip_runs_for_dry_run_and_live_before_the_owed_query(self):
        for mode in ("dry_run", "live"):
            self.db.mode = mode
            self.db.calls.clear()
            self.db.owed = [owed_row()]
            self.tick()
            self.assertEqual(["billing_mark_overdue", "billing_reminders_owed"], self.db.names()[:2], mode)


class SameFamilyTwoStaleInvoices(Base):
    """Fix 1: a family's second stale invoice must not reach Stripe (it voids a live link) when the
    first one already claimed the family's text for the day."""

    def setUp(self):
        super().setUp()
        self.db.owed = [owed_row("A", kind="overdue_1", due="2026-11-02"),
                        owed_row("B", kind="overdue_1", due="2026-11-02")]
        for inv in ("A", "B"):
            self.db.facts[inv] = facts(inv, status="overdue", balance=2000, due_on="2026-11-02")
        self.db.link_amount = 3000                       # both saved links are stale

    def test_only_the_first_invoice_goes_to_stripe(self):
        out = self.tick()
        self.assertEqual(["A"], [c[0]["invoice_id"] for c in self.db.hosted_calls])
        self.assertEqual(1, len(self.ghl.texts()))
        self.assertEqual(1, out["skipped"]["already_sent_or_family_cap"])
        marks = [b for n, b in self.db.calls if n == "billing_mark_link_sent"]
        self.assertEqual(1, len(marks))                  # B never got a link row either

    def test_different_families_each_refresh(self):
        self.db.owed[1]["guardian_id"] = "g2"
        self.db.facts["B"] = facts("B", status="overdue", balance=2000, due_on="2026-11-02",
                                   guardian={"id": "g2", "name": "Lee Park", "first_name": "Lee",
                                             "phone": "+15555550111"})
        out = self.tick()
        self.assertEqual(2, out["sent"])
        self.assertEqual(["A", "B"], sorted(c[0]["invoice_id"] for c in self.db.hosted_calls))

    def test_a_flagged_invoice_does_not_use_up_the_familys_slot(self):
        self.db.owed[0] = owed_row("A", kind="overdue_1", due="2026-11-02", has_link=False, token=None, link_send_id=None)
        out = self.tick()
        self.assertEqual(["A"], out["flagged"])
        self.assertEqual(["B"], [c[0]["invoice_id"] for c in self.db.hosted_calls])
        self.assertEqual(1, out["sent"])


class Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


class Unknown2xx(Base):
    """Fix 3: only a plain HTTP 4xx is a definite refusal. Everything else may have been accepted."""

    def real_client(self, send_body=b"<html>gateway ok</html>", sends=None):
        import connector

        def urlopen(req, timeout=30):
            if req.full_url.endswith("/conversations/messages"):
                if sends is not None:
                    sends.append(req.full_url)
                return Resp(send_body)
            return Resp(b'{"conversations": [{"id": "c1"}], "contact": {"id": "c9"}, "id": "x"}')
        patcher = mock.patch("urllib.request.urlopen", urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)
        return connector.GHLClient({"GHL_API_KEY": "k", "GHL_LOCATION_ID": "L"})

    def test_accepted_but_unreadable_body_is_unknown_and_never_sent_twice(self):
        sends = []
        client = self.real_client(sends=sends)
        self.db.owed = [owed_row()]
        with mock.patch.object(daycare_ghl, "find_contact_by_phone", return_value="c9"):
            self.tick(ghl=client)
            row = dict(self.db.rows[("i1", "upcoming", "2026-11-06")])
            self.tick(ghl=client)
        self.assertEqual("sent", row["status"])                  # held, with a note
        self.assertIn("Unknown whether", row["error"])
        self.assertEqual(1, len(sends))                          # the second tick did NOT text again

    def test_classification_table(self):
        def classify(error):
            ghl = FakeGHL(fail_send=error)
            with self.assertRaises(bl.BillingLinkError) as cm:
                bl.deliver_text(ghl, facts(), "hi", QA)
            return cm.exception.code
        http = lambda code: urllib.error.HTTPError("u", code, "x", {}, None)
        self.assertEqual("ghl_send", classify(http(400)))
        self.assertEqual("ghl_send", classify(http(429)))
        self.assertEqual("ghl_send_unknown", classify(http(500)))
        self.assertEqual("ghl_send_unknown", classify(http(302)))
        self.assertEqual("ghl_send_unknown", classify(ValueError("bad json")))
        self.assertEqual("ghl_send_unknown", classify(urllib.error.URLError("reset")))
        self.assertEqual("ghl_send_unknown", classify(TimeoutError()))
        self.assertEqual("ghl_send_unknown", classify(RuntimeError("HTTP 400 DND")))     # not an HTTPError

    def test_a_non_dict_send_result_is_unknown(self):
        with mock.patch.object(daycare_ghl, "send_sms", return_value=["weird"]), \
                self.assertRaises(bl.BillingLinkError) as cm:
            bl.deliver_text(FakeGHL(), facts(), "hi", QA)
        self.assertEqual("ghl_send_unknown", cm.exception.code)

    def test_failing_before_the_text_is_always_definite(self):
        for error in (RuntimeError("down"), urllib.error.URLError("dns")):
            with mock.patch.object(daycare_ghl, "ensure_family_contact", side_effect=error), \
                    self.assertRaises(bl.BillingLinkError) as cm:
                bl.deliver_text(FakeGHL(), facts(), "hi", QA)
            self.assertEqual("ghl_contact", cm.exception.code)

    def test_owner_send_with_an_unreadable_2xx_is_unknown_blocks_retry_and_marks_failed(self):
        bl._RECENT.clear()
        bl._INFLIGHT.clear()
        rpcs = []

        def rpc(session, name, body, write=True):
            rpcs.append((name, body))
            if name == "billing_create_link_send":
                return [{"id": "s1", "token": "T", "pay_url": "https://p/T", "message": "Hi https://p/T"}]
        client = self.real_client()
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", return_value=facts("i1")), \
                mock.patch.object(daycare_supabase, "billing_recent_send", return_value=False), \
                mock.patch.object(daycare_supabase, "billing_rpc", side_effect=rpc), \
                mock.patch.object(stripe_io, "ensure_hosted_invoice", side_effect=self.db.hosted), \
                mock.patch.object(daycare_ghl, "find_contact_by_phone", return_value="c9"):
            with self.assertRaises(bl.BillingLinkError) as cm:
                bl.send(None, "i1", "Hi {{PAY_URL}}", client)
            self.assertEqual("ghl_send_unknown", cm.exception.code)
            self.assertEqual("failed", [b for n, b in rpcs if n == "billing_mark_link_sent"][0]["p_status"])
            with self.assertRaises(bl.BillingLinkError) as again:      # an immediate retry is refused
                bl.send(None, "i1", "Hi {{PAY_URL}}", client)
            self.assertEqual(409, again.exception.status)

    def test_owner_send_definite_400_can_retry_at_once(self):
        bl._RECENT.clear()
        bl._INFLIGHT.clear()

        def rpc(session, name, body, write=True):
            if name == "billing_create_link_send":
                return [{"id": "s1", "token": "T", "pay_url": "https://p/T", "message": "Hi https://p/T"}]
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", return_value=facts("i1")), \
                mock.patch.object(daycare_supabase, "billing_recent_send", return_value=False), \
                mock.patch.object(daycare_supabase, "billing_rpc", side_effect=rpc), \
                mock.patch.object(stripe_io, "ensure_hosted_invoice", side_effect=self.db.hosted):
            with self.assertRaises(bl.BillingLinkError) as cm:
                bl.send(None, "i1", "Hi {{PAY_URL}}",
                        FakeGHL(fail_send=urllib.error.HTTPError("u", 400, "x", {}, None)))
            self.assertEqual("ghl_send", cm.exception.code)
            self.assertEqual("sent", bl.send(None, "i1", "Hi {{PAY_URL}}", FakeGHL())["status"])


class FlagsUnderTheCap(Base):
    """Fix 4: no-link / no-phone flags are written even when a sibling invoice texts the same family."""

    def test_no_link_flag_row_is_written_even_though_a_sibling_texts_first_in_the_list(self):
        self.db.owed = [owed_row("A"), owed_row("B", has_link=False, token=None, link_send_id=None)]
        self.db.facts["A"] = facts("A")
        self.db.facts["B"] = facts("B")
        out = self.tick()
        self.assertEqual(["B"], out["flagged"])
        self.assertEqual({"A": "sent", "B": "failed"}, {k[0]: v["status"] for k, v in self.db.rows.items()})
        self.assertIn("No pay link", self.db.rows[("B", "upcoming", "2026-11-06")]["error"])
        self.assertEqual(1, len(self.ghl.texts()))

    def test_no_phone_flag_row_is_written_and_nothing_is_texted(self):
        self.db.owed = [owed_row("A"), owed_row("B")]
        self.db.facts["A"] = facts("A")
        self.db.facts["B"] = facts("B", guardian={"id": "g1", "name": "Dana Smith", "first_name": "Dana", "phone": ""})
        out = self.tick()
        self.assertIn("B", out["flagged"])
        self.assertEqual("failed", self.db.rows[("B", "upcoming", "2026-11-06")]["status"])

    def test_flag_rows_go_first_in_the_order_of_work(self):
        self.db.owed = [owed_row("A"), owed_row("B", has_link=False, token=None, link_send_id=None)]
        self.db.facts["A"] = facts("A")
        self.db.facts["B"] = facts("B")
        self.tick()
        claims = [b["p_invoice"] for n, b in self.db.calls if n == "billing_reminder_claim"]
        self.assertEqual(["B", "A"], claims)

    def test_refresh_failure_row_is_written(self):
        self.db.owed = [owed_row("A", kind="overdue_1", due="2026-11-02")]
        self.db.facts["A"] = facts("A", status="overdue", balance=2000, due_on="2026-11-02")
        self.db.link_amount = 3000
        self.db.hosted_error = stripe_io.StripeError(502, "Stripe is temporarily unavailable", "x")
        self.tick()
        self.assertEqual("failed", self.db.rows[("A", "overdue_1", "2026-11-02")]["status"])


class TickLog(unittest.TestCase):
    def test_line_reports_counts_flags_and_failures(self):
        line = rem.tick_line({"ok": True, "errors": 1, "results": [
            {"location_id": QA, "mode": "live", "sent": 2, "failed": 1, "flagged": ["i1"], "warnings": []},
            {"location_id": ATOB, "mode": "off"}]})
        self.assertIn("[billing_reminders] tick:", line)
        self.assertIn("99999999 mode=live", line)
        self.assertIn("'sent': 2", line)
        self.assertIn("flagged=1", line)
        self.assertIn("1 center(s) skipped", line)
        self.assertNotIn("11111111", line)                  # an idle center adds nothing

    def test_quiet_when_nothing_happened_or_window_closed(self):
        self.assertEqual("", rem.tick_line({"ok": True, "skipped_window": True}))
        self.assertEqual("", rem.tick_line({"ok": True, "results": [{"location_id": QA, "mode": "off"}], "errors": 0}))

    def test_failed_tick_is_reported(self):
        self.assertIn("tick failed: no daycare session", rem.tick_line({"ok": False, "error": "no daycare session"}))

    def test_loop_prints_the_line(self):
        class Stop(Exception):
            pass
        printed = []
        import forge_heartbeat
        import forge_ops
        with mock.patch.object(rem, "run_all", return_value={"ok": True, "errors": 0, "results": [
                    {"location_id": QA, "mode": "live", "sent": 1}]}), \
                mock.patch.object(rem.time, "sleep", side_effect=Stop()), \
                mock.patch.object(forge_ops, "paused", return_value=False), \
                mock.patch.object(forge_heartbeat, "beat"), \
                mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(a[0])):
            with self.assertRaises(Stop):
                rem.run_forever(lambda: None, FakeGHL(), interval=1)
        self.assertTrue(any("[billing_reminders] tick:" in str(p) for p in printed))


class OffCenterNeverSwitches(Base):
    """Fix 2: the hourly tick must not move the shared admin profile's active center for a center
    that is off or has nothing owed."""

    def test_run_all_over_off_centers_never_opens_a_switch(self):
        self.db.mode = "off"
        locs = {"locations": [{"id": ATOB}, {"id": ATOB2}, {"id": AMT}]}
        with mock.patch.object(daycare_supabase, "list_locations", return_value=locs):
            out = rem.run_all(lambda: object(), self.ghl, now=AT_10AM)
        self.assertEqual(0, self.max_depth)
        self.assertEqual(0, out["errors"])
        self.assertEqual(3, len([n for n in self.db.names() if n == "billing_reminders_owed"]))   # ATOB, ATOB2, QA
        self.assertEqual([], self.ghl.posts)

    def test_only_the_center_with_rows_is_entered(self):
        entered = []

        @contextmanager
        def at_location(session, loc):
            entered.append(loc)
            yield
        real = self.db.rpc

        def rpc(session, name, body, write=True):
            if name == "billing_reminders_owed":
                self.db.calls.append((name, body))
                return [owed_row(loc=body["p_location"])] if body["p_location"] == QA else []
            return real(session, name, body, write)
        locs = {"locations": [{"id": ATOB}, {"id": ATOB2}]}
        with mock.patch.object(daycare_supabase, "list_locations", return_value=locs), \
                mock.patch.object(daycare_supabase, "at_location", at_location), \
                mock.patch.object(daycare_supabase, "billing_rpc", side_effect=rpc):
            rem.run_all(lambda: object(), self.ghl, now=AT_10AM)
        self.assertEqual([QA], entered)


class LinkSendCountsAsTodaysText(Base):
    """The claim refuses when the family has a billing_link_sends row with sent_at on p_today (ET). The
    pre-Stripe check must see the same thing, or a stale link is refreshed (old one voided) for nothing."""

    def stale(self):
        self.db.owed = [owed_row(kind="overdue_3", due="2026-10-31")]
        self.db.facts["i1"] = facts(status="overdue", balance=2000, paid_cents=1000, due_on="2026-10-31")
        self.db.link_amount = 3000

    def test_an_owner_link_text_today_vetoes_the_refresh_before_stripe(self):
        self.stale()
        self.db.link_sent_today = True
        out = self.tick()
        self.assertEqual([], self.db.hosted_calls)
        self.assertNotIn("billing_create_link_send", self.db.names())
        self.assertNotIn("billing_reminder_claim", self.db.names())
        self.assertEqual([], self.ghl.posts)
        self.assertEqual(1, out["skipped"]["already_sent_or_family_cap"])

    def test_no_link_text_today_refreshes_as_before(self):
        self.stale()
        out = self.tick()
        self.assertEqual(1, out["sent"])

    def test_the_check_is_asked_for_the_simulated_date(self):
        asked = []
        self.stale()
        with mock.patch.object(daycare_supabase, "billing_reminder_family_busy",
                               side_effect=lambda s, g, today: asked.append((g, today)) or False):
            self.tick(as_of=date(2026, 11, 10))
        self.assertEqual([("g1", "2026-11-10")], asked)

    def test_reader_checks_both_rules_with_eastern_day_bounds(self):
        queries = []

        def rest(session, method, resource, query=None, **kw):
            queries.append((resource, query))
            return []
        guardian = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest):
            self.assertFalse(REAL_FAMILY_BUSY(None, guardian, "2026-11-03"))
        self.assertEqual(["billing_reminders", "billing_link_sends"], [r for r, _ in queries])
        link_query = queries[1][1]
        self.assertEqual(guardian and f"eq.{guardian}", link_query["guardian_id"])
        self.assertEqual(["gte.2026-11-03T05:00:00Z", "lt.2026-11-04T05:00:00Z"], link_query["sent_at"])   # EST day

    def test_day_bounds_follow_daylight_saving(self):
        seen = []

        def rest(session, method, resource, query=None, **kw):
            if resource == "billing_link_sends":
                seen.append(query["sent_at"])
            return []
        guardian = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest):
            REAL_FAMILY_BUSY(None, guardian, "2026-10-31")    # EDT (UTC-4)
            REAL_FAMILY_BUSY(None, guardian, "2026-11-01")    # the 25-hour fall-back day
        self.assertEqual(["gte.2026-10-31T04:00:00Z", "lt.2026-11-01T04:00:00Z"], seen[0])
        self.assertEqual(["gte.2026-11-01T04:00:00Z", "lt.2026-11-02T05:00:00Z"], seen[1])

    def test_either_rule_alone_is_enough(self):
        guardian = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        for hit in ("billing_reminders", "billing_link_sends"):
            def rest(session, method, resource, query=None, hit=hit, **kw):
                return [{"id": "x"}] if resource == hit else []
            with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest):
                self.assertTrue(REAL_FAMILY_BUSY(None, guardian, "2026-11-03"), hit)

    def test_unreadable_halves_and_bad_inputs_are_not_busy(self):
        guardian = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=daycare_supabase.DaycareError(403, "x")):
            self.assertFalse(REAL_FAMILY_BUSY(None, guardian, "2026-11-03"))
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", return_value=[]):
            self.assertFalse(REAL_FAMILY_BUSY(None, "not-a-uuid", "2026-11-03"))
            self.assertFalse(REAL_FAMILY_BUSY(None, guardian, "garbage"))


class StaffReviewForAnyFamily(Base):
    """A +7 day staff_review row has no parent text, so it works for a family with no link, no phone,
    no usable facts - e.g. an autopay family whose charge was declined."""

    def test_staff_review_needs_no_link_no_phone_and_reads_no_facts(self):
        self.db.owed = [owed_row(kind="staff_review", due="2026-10-27", has_link=False, token=None, link_send_id=None)]
        with mock.patch.object(daycare_supabase, "billing_invoice_facts") as read:
            out = self.tick()
        read.assert_not_called()
        self.assertEqual((1, 0, []), (out["reviews"], out["sent"], out["flagged"]))
        self.assertEqual([], self.ghl.posts)
        self.assertNotIn("billing_reminder_claim", self.db.names())
        self.assertEqual(1, self.db.names().count("billing_reminder_staff_review"))

    def test_staff_review_with_a_pending_payment_still_goes_to_the_owner(self):
        self.db.owed = [owed_row(kind="staff_review", due="2026-10-27", has_pending_payment=True)]
        out = self.tick()
        self.assertEqual(1, out["reviews"])
        self.assertEqual([], self.ghl.posts)

    def test_flag_rows_carry_no_pay_link_text_so_they_never_count_as_send_attempts(self):
        self.db.owed = [owed_row(has_link=False, token=None, link_send_id=None)]
        self.tick()
        claim = [b for n, b in self.db.calls if n == "billing_reminder_claim"][0]
        self.assertNotIn("/pay/", claim["p_message"])


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
        self.db.owed = [owed_row()]
        self.db.unchecked = [{"id": "r9", "ghl_message_id": "m9"}]
        self.db.rows[("x", "upcoming", "d")] = {"id": "r9", "status": "sent", "guardian": "g1", "date": "d"}
        self.tick(ghl=FakeGHL(message_status="undelivered"))
        res = [b for n, b in self.db.calls if n == "billing_reminder_result" and b["p_id"] == "r9"][0]
        self.assertEqual(("sent", "m9"), (res["p_status"], res["p_ghl_message_id"]))
        self.assertIn("undelivered", res["p_error"])

    def test_delivered_reminder_writes_nothing(self):
        self.db.owed = [owed_row()]
        self.db.unchecked = [{"id": "r9", "ghl_message_id": "m9"}]
        self.tick(ghl=FakeGHL(message_status="delivered"))
        self.assertEqual([], [b for n, b in self.db.calls if n == "billing_reminder_result" and b["p_id"] == "r9"])


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

    def test_billing_list_marks_needs_review_and_reminder_failed(self):
        queries = []

        def rest(session, method, resource, query=None, **kw):
            if resource == "invoices":
                return [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}]
            if resource == "billing_reminders":
                queries.append(query)
                return [{"invoice_id": "i2", "kind": "staff_review", "status": "sent"},
                        {"invoice_id": "i3", "kind": "overdue_1", "status": "failed"}]
            return []
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest), \
                mock.patch.object(daycare_supabase, "active_location", return_value=ATOB):
            out = daycare_supabase.get_billing(None)
        by = {i["id"]: (i["needs_review"], i["reminder_failed"]) for i in out["invoices"]}
        self.assertEqual({"i1": (False, False), "i2": (True, False), "i3": (False, True)}, by)
        self.assertEqual(1, len(queries))                    # one select for both flags
        self.assertEqual("(kind.eq.staff_review,status.eq.failed)", queries[0]["or"])

    def test_billing_list_flags_default_false_when_unreadable(self):
        def rest(session, method, resource, **kw):
            if resource == "billing_reminders":
                raise daycare_supabase.DaycareError(403, "x")
            return [{"id": "i1"}] if resource == "invoices" else []
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest), \
                mock.patch.object(daycare_supabase, "active_location", return_value=ATOB):
            inv = daycare_supabase.get_billing(None)["invoices"][0]
        self.assertEqual((False, False), (inv["needs_review"], inv["reminder_failed"]))

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
