"""Billing P0 (Stream D): per-center Stripe key, hosted invoice without Stripe email,
pay-link text for the REMAINING balance, GHL child-named contact, send/timeline guards.
All HTTP mocked; run: python3 -m unittest test_billing_link  (from `forge rei/`)."""
import importlib
import os
import unittest
import urllib.error
from datetime import date
from unittest import mock

import daycare_billing_link as bl
import daycare_ghl
import daycare_supabase
import stripe_io



def setUpModule():
    # Script-style tests (test_stripe_invoice, test_stripe_links) overwrite stripe_io functions at
    # import time. Restore the real module so these tests never depend on import order.
    importlib.reload(stripe_io)


QA = "99999999-9999-9999-9999-999999999999"
ATOB = "11111111-1111-1111-1111-111111111111"
AMT = "44444444-4444-4444-4444-444444444444"
INV = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TODAY = date(2026, 10, 30)


def facts(**over):
    base = {
        "invoice_id": INV, "invoice_number": "INV-1042", "description": "Tuition", "due_on": "2026-11-03",
        "status": "due", "location_id": ATOB, "amount_cents": 10000, "paid_cents": 7500, "balance_cents": 2500,
        "guardian": {"id": "g1", "name": "Dana Smith", "first_name": "Dana", "email": "d@example.com",
                     "phone": "+15555550100"},
        "child": {"id": "c1", "first_name": "Maya", "last_name": "Smith"}, "child_ambiguous": False,
        "known_stripe_invoice_ids": [],
    }
    base.update(over)
    return base


class FakeStripe:
    """Records calls; invoices dict keyed by id (the mocked Stripe account)."""

    def __init__(self, invoices=None):
        self.calls, self.invoices, self.n = [], dict(invoices or {}), 0

    def __call__(self, method, path, params=None, key=None):
        self.calls.append((method, path, params, key))
        if method == "GET" and path.startswith("/invoices/search"):
            return {"data": []}
        if method == "GET" and path.startswith("/customers/search"):
            return {"data": []}
        if method == "GET" and path.startswith("/invoices/"):
            inv = self.invoices.get(path.rsplit("/", 1)[1])
            if not inv:
                raise stripe_io.StripeError(404, "no such invoice")
            return inv
        if method == "POST" and path == "/customers":
            return {"id": "cus_1"}
        if method == "POST" and path == "/invoices":
            self.n += 1
            inv = {"id": f"in_new{self.n}", "status": "draft", "metadata": params["metadata"],
                   "customer": params["customer"], "livemode": not stripe_io.is_test_key(key)}
            self.invoices[inv["id"]] = inv
            return inv
        if method == "POST" and path == "/invoiceitems":
            if "invoice" in params:
                self.invoices[params["invoice"]]["amount_due"] = params["amount"]
            return {"id": "ii_1"}
        if method == "POST" and path.endswith("/finalize"):
            inv = self.invoices[path.split("/")[2]]
            inv.update(status="open", hosted_invoice_url="https://invoice.stripe.com/i/x/" + inv["id"])
            return inv
        if method == "POST" and path.endswith("/send"):
            return self.invoices.get(path.split("/")[2], {})
        if method == "POST" and path.endswith("/void"):
            self.invoices[path.split("/")[2]]["status"] = "void"
            return {}
        if method == "DELETE":
            self.invoices.pop(path.rsplit("/", 1)[1], None)
            return {}
        raise AssertionError(f"unexpected stripe call {method} {path}")

    def paths(self):
        return [(m, p) for m, p, _, _ in self.calls]


def open_inv(iid, amount, **extra):
    return {"id": iid, "status": "open", "amount_due": amount, "customer": "cus_1", "livemode": True,
            "hosted_invoice_url": "https://invoice.stripe.com/i/old/" + iid,
            "metadata": {"daycare_invoice_id": INV}, **extra}


class KeySelection(unittest.TestCase):
    def env(self, **kw):
        base = {"STRIPE_SECRET_KEY": "", "STRIPE_SECRET_KEY__DAYCARE_TEST": ""}
        base.update(kw)
        return mock.patch.dict(os.environ, base), mock.patch.object(daycare_supabase, "_read_env", return_value={})

    def test_qa_uses_test_key_everyone_else_live(self):
        a, b = self.env(STRIPE_SECRET_KEY="rk_live_abc", STRIPE_SECRET_KEY__DAYCARE_TEST="sk_test_abc")
        with a, b:
            self.assertEqual("sk_test_abc", stripe_io.key_for_location(QA))
            self.assertEqual("rk_live_abc", stripe_io.key_for_location(ATOB))
            self.assertEqual("rk_live_abc", stripe_io.key_for_location(AMT))

    def test_fail_closed_missing_keys(self):
        a, b = self.env(STRIPE_SECRET_KEY="rk_live_abc")
        with a, b, self.assertRaises(stripe_io.StripeError) as cm:
            stripe_io.key_for_location(QA)
        self.assertEqual("not_configured", cm.exception.code)
        a, b = self.env(STRIPE_SECRET_KEY__DAYCARE_TEST="sk_test_abc")
        with a, b, self.assertRaises(stripe_io.StripeError) as cm:
            stripe_io.key_for_location(ATOB)
        self.assertEqual("not_configured", cm.exception.code)

    def test_never_crosses_modes(self):
        a, b = self.env(STRIPE_SECRET_KEY="rk_live_abc", STRIPE_SECRET_KEY__DAYCARE_TEST="rk_live_abc")
        with a, b, self.assertRaises(stripe_io.StripeError) as cm:     # live key in the test slot
            stripe_io.key_for_location(QA)
        self.assertEqual("key_mismatch", cm.exception.code)
        a, b = self.env(STRIPE_SECRET_KEY="sk_test_abc")
        with a, b, self.assertRaises(stripe_io.StripeError) as cm:     # test key in the live slot
            stripe_io.key_for_location(ATOB)
        self.assertEqual("key_mismatch", cm.exception.code)

    def test_real_center_never_falls_back_to_test_key(self):
        a, b = self.env(STRIPE_SECRET_KEY="", STRIPE_SECRET_KEY__DAYCARE_TEST="sk_test_abc")
        with a, b, self.assertRaises(stripe_io.StripeError):
            stripe_io.key_for_location(AMT)


class HostedInvoice(unittest.TestCase):
    def run_ensure(self, fake, balance=2500, paid=7500, known=()):
        ctx = {"invoice_id": INV, "invoice_number": "INV-1042", "balance_cents": balance, "paid_cents": paid,
               "due_on": "2026-11-03", "description": "Tuition", "guardian": {"id": "g1", "name": "Dana"},
               "known_stripe_invoice_ids": list(known)}
        with mock.patch.object(stripe_io, "_req", fake), \
                mock.patch.object(stripe_io, "key_for_location", return_value="sk_test_abc"):
            return stripe_io.ensure_hosted_invoice(ctx, QA)

    def test_creates_for_balance_finalizes_never_sends(self):
        fake = FakeStripe()
        out = self.run_ensure(fake)
        self.assertEqual(2500, out["amount_cents"])
        self.assertFalse(out["livemode"])
        self.assertTrue(out["hosted_url"].startswith("https://invoice.stripe.com/"))
        self.assertFalse([p for m, p in fake.paths() if p.endswith("/send")])
        item = [c for c in fake.calls if c[1] == "/invoiceitems"][0][2]
        self.assertEqual(2500, item["amount"])
        self.assertIn("invoice", item)                 # attached to THIS invoice, no dangling pending item
        create = [c for c in fake.calls if c[1] == "/invoices" and c[0] == "POST"][0][2]
        self.assertEqual("exclude", create["pending_invoice_items_behavior"])
        self.assertEqual(INV, create["metadata"]["daycare_invoice_id"])

    def test_reuses_open_invoice_with_same_amount(self):
        fake = FakeStripe({"in_old": open_inv("in_old", 2500)})
        out = self.run_ensure(fake, known=["in_old"])
        self.assertTrue(out["reused"])
        self.assertEqual("in_old", out["stripe_invoice_id"])
        self.assertFalse([p for m, p in fake.paths() if m == "POST" and p == "/invoices"])

    def test_voids_open_invoice_when_balance_changed(self):
        fake = FakeStripe({"in_old": open_inv("in_old", 10000)})
        out = self.run_ensure(fake, known=["in_old"])
        self.assertEqual(["in_old"], out["voided"])
        self.assertEqual("void", fake.invoices["in_old"]["status"])
        self.assertEqual(2500, out["amount_cents"])
        self.assertNotEqual("in_old", out["stripe_invoice_id"])

    def test_refuses_when_stripe_paid_more_than_recorded(self):
        paid = open_inv("in_paid", 4000, status="paid", amount_paid=4000)
        fake = FakeStripe({"in_paid": paid})
        with self.assertRaises(stripe_io.StripeError) as cm:
            self.run_ensure(fake, paid=0, known=["in_paid"])
        self.assertEqual("payment_not_synced", cm.exception.code)

    def test_paid_stripe_invoice_already_recorded_does_not_block_new_balance(self):
        paid = open_inv("in_paid", 4000, status="paid", amount_paid=4000)
        fake = FakeStripe({"in_paid": paid})
        out = self.run_ensure(fake, paid=4000, balance=6000, known=["in_paid"])
        self.assertEqual(6000, out["amount_cents"])

    def test_zero_balance_refused(self):
        with self.assertRaises(stripe_io.StripeError):
            self.run_ensure(FakeStripe(), balance=0)

    def test_send_invoice_old_path_still_pins_key_per_location(self):
        fake = FakeStripe()
        with mock.patch.object(stripe_io, "_req", fake), \
                mock.patch.object(stripe_io, "key_for_location", return_value="sk_test_abc"), \
                mock.patch.object(stripe_io, "find_invoice", return_value=None):
            stripe_io.send_invoice({"invoice_id": INV, "amount": 25, "location_id": QA,
                                    "guardian": {"id": "g1", "name": "D"}})
        self.assertTrue(fake.calls and all(c[3] == "sk_test_abc" for c in fake.calls))

class Compose(unittest.TestCase):
    def text(self, **over):
        return bl.compose_text(facts(**over), TODAY)

    def test_example_shape_and_partial_balance(self):
        msg, warn = self.text()
        self.assertEqual("Hi Dana, this is A Touch of Blessings. Maya's invoice INV-1042 has $25.00 left, "
                         "due Nov 3. Pay securely here: {{PAY_URL}}", msg)
        self.assertEqual([], warn)

    def test_brand_per_center(self):
        self.assertIn("this is A Mother's Touch.", self.text(location_id=AMT)[0])
        self.assertNotIn("A Touch of Blessings", self.text(location_id=AMT)[0])
        self.assertIn("this is A Touch of Blessings.", self.text(location_id="22222222-2222-2222-2222-222222222222")[0])
        self.assertIn("this is A Touch of Blessings.", self.text(location_id=QA)[0])

    def test_one_placeholder_no_stop_line(self):
        msg, _ = self.text()
        self.assertEqual(1, msg.count("{{PAY_URL}}"))
        self.assertNotIn("stop", msg.lower())

    def test_balance_formatting_and_past_due(self):
        msg, _ = self.text(balance_cents=123456, due_on="2026-10-01")
        self.assertIn("$1,234.56 left, past due since Oct 1.", msg)

    def test_ambiguous_child_names_no_child(self):
        msg, warn = self.text(child_ambiguous=True)
        self.assertIn("Invoice INV-1042 has", msg)
        self.assertNotIn("Maya", msg)
        self.assertTrue(warn)

    def test_missing_parent_name(self):
        msg, warn = self.text(guardian={"id": "g", "name": "", "first_name": "", "phone": "+1555"})
        self.assertTrue(msg.startswith("Hi there, this is"))
        self.assertTrue(warn)


class Validate(unittest.TestCase):
    def test_placeholder_rules(self):
        with self.assertRaises(bl.BillingLinkError):
            bl.validate_message("Pay now please")
        with self.assertRaises(bl.BillingLinkError):
            bl.validate_message("{{PAY_URL}} and again {{PAY_URL}}")
        self.assertEqual("ok {{PAY_URL}}", bl.validate_message("  ok {{PAY_URL}}  "))

    def test_length_limit(self):
        bl.validate_message("x" * (640 - 11) + "{{PAY_URL}}")
        with self.assertRaises(bl.BillingLinkError) as cm:
            bl.validate_message("x" * 640 + "{{PAY_URL}}")
        self.assertEqual(400, cm.exception.status)

    def test_no_stop_line(self):
        with self.assertRaises(bl.BillingLinkError):
            bl.validate_message("Pay {{PAY_URL}} Reply STOP to opt out")


class FakeGHL:
    configured = True
    location_id = "LOC"

    def __init__(self, existing=None, fail_send=None, fail_tags=False):
        self.existing, self.fail_send, self.fail_tags, self.posts, self.gets = existing, fail_send, fail_tags, [], []

    def get(self, path, params=None, retries=3):
        self.gets.append((path, params))
        if path == "/contacts/search/duplicate":
            return {"contact": {"id": self.existing}} if self.existing else {}
        if path == "/conversations/search":
            return {"conversations": [{"id": "conv1"}]}
        if path.startswith("/conversations/messages/"):
            return {"status": "delivered"}
        return {}

    def post(self, path, body, retries=2):
        self.posts.append((path, body))
        if path.endswith("/tags") and self.fail_tags:
            raise urllib.error.HTTPError("u", 500, "boom", {}, None)
        if path == "/contacts/":
            return {"contact": {"id": "newc"}}
        if path == "/conversations/messages":
            if self.fail_send:
                raise self.fail_send
            return {"messageId": "msg1"}
        return {}


class GhlContact(unittest.TestCase):
    def test_existing_contact_found_by_phone_is_untouched(self):
        ghl = FakeGHL(existing="c9")
        self.assertEqual("c9", daycare_ghl.ensure_family_contact(ghl, phone="+15555550100", child_first="Maya"))
        self.assertFalse([p for p, _ in ghl.posts if p == "/contacts/"])

    def test_created_contact_is_the_child_with_parent_name_field(self):
        ghl = FakeGHL()
        cid = daycare_ghl.ensure_family_contact(ghl, phone="(555) 555-0100", child_first="Maya",
                                                child_last="Smith", parent_name="Dana Smith")
        self.assertEqual("newc", cid)
        body = [b for p, b in ghl.posts if p == "/contacts/"][0]
        self.assertEqual("Maya", body["firstName"])
        self.assertEqual("Smith", body["lastName"])
        self.assertEqual([{"id": daycare_ghl.CF_PARENT_NAME, "field_value": "Dana Smith"}], body["customFields"])


class SendFlow(unittest.TestCase):
    def setUp(self):
        bl._RECENT.clear()
        bl._INFLIGHT.clear()
        self.rpcs = []
        self.recent = False
        self.stripe = FakeStripe()

    def rpc(self, session, name, body, write=True):
        self.rpcs.append((name, body))
        if name == "billing_create_link_send":
            url = "https://pay.example/p/TOKEN123"
            return [{"id": "send1", "token": "TOKEN123", "pay_url": url,
                     "message": body["p_message"].replace("{{PAY_URL}}", url)}]
        return None

    def run_send(self, f=None, ghl=None, message=None):
        ghl = ghl or FakeGHL(existing="c9")
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", return_value=f or facts()), \
                mock.patch.object(daycare_supabase, "billing_rpc", side_effect=self.rpc), \
                mock.patch.object(daycare_supabase, "billing_recent_send", return_value=self.recent), \
                mock.patch.object(stripe_io, "_req", self.stripe), \
                mock.patch.object(stripe_io, "key_for_location", return_value="sk_test_abc"):
            return bl.send(None, INV, message or "Hi Dana. Pay: {{PAY_URL}}", ghl), ghl

    def test_happy_path_order_and_final_text(self):
        out, ghl = self.run_send()
        self.assertEqual(["billing_create_link_send", "billing_mark_link_sent"], [n for n, _ in self.rpcs])
        create = self.rpcs[0][1]
        self.assertEqual(2500, create["p_amount_cents"])
        self.assertEqual("Hi Dana. Pay: {{PAY_URL}}", create["p_message"])
        sms = [b for p, b in ghl.posts if p == "/conversations/messages"][0]
        self.assertEqual("Hi Dana. Pay: https://pay.example/p/TOKEN123", sms["message"])
        self.assertNotIn("{{PAY_URL}}", sms["message"])
        self.assertEqual(("sent", "msg1"), (self.rpcs[1][1]["p_status"], self.rpcs[1][1]["p_ghl_message_id"]))
        self.assertEqual({"ok": True, "send_id": "send1", "status": "sent",
                          "pay_url": "https://pay.example/p/TOKEN123", "sent_message": sms["message"]}, out)
        self.assertFalse([p for m, p in self.stripe.paths() if p.endswith("/send")])    # Stripe never emails

    def test_rejects_zero_balance_before_stripe(self):
        for bad in (facts(balance_cents=0, paid_cents=10000), facts(status="paid"), facts(status="void")):
            with self.assertRaises(bl.BillingLinkError):
                self.run_send(bad)
        self.assertEqual([], self.stripe.calls)
        self.assertEqual([], self.rpcs)

    def test_rejects_bad_message_before_anything(self):
        for bad in ("no placeholder", "x" * 700 + "{{PAY_URL}}", "{{PAY_URL}}{{PAY_URL}}"):
            with self.assertRaises(bl.BillingLinkError):
                self.run_send(message=bad)
        self.assertEqual([], self.stripe.calls)

    def test_no_phone_refused(self):
        f = facts()
        f["guardian"]["phone"] = ""
        with self.assertRaises(bl.BillingLinkError) as cm:
            self.run_send(f)
        self.assertEqual("no_phone", cm.exception.code)
        self.assertEqual([], self.stripe.calls)

    def test_ghl_failure_marks_failed_and_raises(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, None)
        with self.assertRaises(bl.BillingLinkError) as cm:
            self.run_send(ghl=FakeGHL(existing="c9", fail_send=err))
        self.assertEqual("ghl_send", cm.exception.code)
        self.assertEqual("failed", self.rpcs[-1][1]["p_status"])

    def test_unknown_send_outcome_is_flagged(self):
        class GHLSendUnknown(RuntimeError):
            pass
        with self.assertRaises(bl.BillingLinkError) as cm:
            self.run_send(ghl=FakeGHL(existing="c9", fail_send=GHLSendUnknown("timeout")))
        self.assertEqual("ghl_send_unknown", cm.exception.code)
        self.assertIn("Unknown whether", cm.exception.message)

    def test_double_tap_blocked(self):
        self.run_send()
        with self.assertRaises(bl.BillingLinkError) as cm:
            self.run_send()
        self.assertEqual((409, bl.TOO_SOON), (cm.exception.status, cm.exception.message))

    def test_qa_message_names_atob_and_amt_message_names_amt(self):
        msg, _ = bl.compose_text(facts(location_id=AMT), TODAY)
        self.assertIn("A Mother's Touch", msg)


class Facts(unittest.TestCase):
    def facts_from(self, invoice, linked=None):
        def rest(session, method, resource, **kw):
            if resource == "invoices":
                return [invoice]
            if resource == "children":
                return linked or []
            if resource == "billing_link_sends":
                return [{"stripe_invoice_id": "in_1"}]
            if resource == "locations":
                return [{"name": "921 N 18th"}]
            raise AssertionError(resource)
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest), \
                mock.patch.object(daycare_supabase, "_merge_contacts", lambda s, p: p[0].update(phone="+1555")), \
                mock.patch.object(daycare_supabase, "active_location", return_value=ATOB):
            return daycare_supabase.billing_invoice_facts(None, INV)

    def inv(self, **over):
        base = {"id": INV, "invoice_number": "INV-1", "amount": "100.00", "due_on": "2026-11-03",
                "status": "due", "guardian_id": "g1", "child_id": "c1", "location_id": ATOB,
                "children": {"id": "c1", "first_name": "Maya", "last_name": "Smith"},
                "profiles": {"id": "g1", "first_name": "Dana", "last_name": "Smith", "display_name": "Dana Smith"},
                "payments": [{"amount": "50.00", "status": "succeeded"}, {"amount": "10.00", "status": "pending"},
                             {"amount": "5.00", "status": "failed"}, {"amount": "25.00"}]}
        base.update(over)
        return base

    def test_balance_counts_only_succeeded_payments(self):
        f = self.facts_from(self.inv())
        self.assertEqual((10000, 7500, 2500), (f["amount_cents"], f["paid_cents"], f["balance_cents"]))
        self.assertEqual(["in_1"], f["known_stripe_invoice_ids"])
        self.assertEqual("Dana", f["guardian"]["first_name"])
        self.assertEqual("Maya", f["child"]["first_name"])
        self.assertEqual("921 N 18th", f["center_name"])

    def test_child_from_single_linked_child(self):
        f = self.facts_from(self.inv(children=None, child_id=None),
                            linked=[{"id": "c2", "first_name": "Leo", "last_name": "S"}])
        self.assertEqual(("Leo", False), (f["child"]["first_name"], f["child_ambiguous"]))

    def test_several_linked_children_is_ambiguous(self):
        f = self.facts_from(self.inv(children=None, child_id=None),
                            linked=[{"id": "c2", "first_name": "Leo", "last_name": "S"},
                                    {"id": "c3", "first_name": "Zoe", "last_name": "S"}])
        self.assertTrue(f["child_ambiguous"])

    def test_cents_no_float_drift(self):
        self.assertEqual(1999, daycare_supabase._cents(19.99))
        self.assertEqual(110, daycare_supabase._cents("1.10"))


class Timeline(unittest.TestCase):
    def test_refreshes_sent_rows_then_returns_db_timeline(self):
        calls = []

        def rpc(session, name, body, write=True):
            calls.append((name, body))
            return {"invoice": {"id": INV}, "sends": [], "payments": [], "alerts": []} \
                if name == "billing_invoice_timeline" else None
        bl._REFRESHED.clear()
        with mock.patch.object(daycare_supabase, "billing_send_rows",
                               return_value=[{"id": "s1", "ghl_message_id": "m1"}]), \
                mock.patch.object(daycare_supabase, "billing_rpc", side_effect=rpc):
            out = bl.timeline(None, INV, FakeGHL())
        self.assertEqual(["billing_set_link_delivery", "billing_invoice_timeline"], [n for n, _ in calls])
        self.assertEqual({"p_id": "s1", "p_status": "delivered"}, calls[0][1])
        self.assertTrue(out["ok"] and out["sends"] == [])

    def test_ghl_lookup_failure_never_breaks_timeline(self):
        class Boom(FakeGHL):
            def get(self, *a, **k):
                raise RuntimeError("down")
        bl._REFRESHED.clear()
        with mock.patch.object(daycare_supabase, "billing_send_rows",
                               return_value=[{"id": "s1", "ghl_message_id": "m1"}]), \
                mock.patch.object(daycare_supabase, "billing_rpc",
                                  return_value={"invoice": {}, "sends": [], "payments": [], "alerts": []}):
            self.assertTrue(bl.timeline(None, INV, Boom())["ok"])


class ChangeOne(unittest.TestCase):
    """Contract change 1: link status on the billing list, center_name, 120 s resend guard."""

    def setUp(self):
        bl._RECENT.clear()
        bl._INFLIGHT.clear()

    def test_billing_list_gets_newest_link_per_invoice_in_one_query(self):
        calls = []
        link_rows = [  # newest first, as asked
            {"invoice_id": "i1", "status": "delivered", "sent_at": "t3", "opened_at": "t4", "open_count": 2,
             "paid_at": None, "created_at": "t3"},
            {"invoice_id": "i1", "status": "failed", "sent_at": None, "opened_at": None, "open_count": 0,
             "paid_at": None, "created_at": "t1"},
        ]

        def rest(session, method, resource, **kw):
            calls.append(resource)
            if resource == "invoices":
                return [{"id": "i1"}, {"id": "i2"}]
            if resource == "billing_link_sends":
                return link_rows
            return []
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest), \
                mock.patch.object(daycare_supabase, "active_location", return_value=ATOB):
            out = daycare_supabase.get_billing(None)
        by = {i["id"]: i for i in out["invoices"]}
        self.assertEqual({"status": "delivered", "sent_at": "t3", "opened_at": "t4", "open_count": 2,
                          "paid_at": None}, by["i1"]["link"])
        self.assertIsNone(by["i2"]["link"])
        self.assertEqual(1, calls.count("billing_link_sends"))        # no N+1

    def test_billing_list_survives_missing_link_table(self):
        def rest(session, method, resource, **kw):
            if resource == "billing_link_sends":
                raise daycare_supabase.DaycareError(404, "x", "not_found")
            return [{"id": "i1"}] if resource == "invoices" else []
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest), \
                mock.patch.object(daycare_supabase, "active_location", return_value=ATOB):
            out = daycare_supabase.get_billing(None)
        self.assertIsNone(out["invoices"][0]["link"])

    def test_compose_facts_have_center_name(self):
        with mock.patch.object(daycare_supabase, "billing_invoice_facts",
                               return_value=facts(center_name="921 N 18th")):
            out = bl.compose(None, INV)
        self.assertEqual(("A Touch of Blessings", "921 N 18th"),
                         (out["facts"]["brand"], out["facts"]["center_name"]))

    def test_recent_send_query_asks_created_or_sent_since_cutoff(self):
        seen = {}

        def rest(session, method, resource, query=None, **kw):
            seen.update(resource=resource, query=query)
            return [{"id": "x"}]
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest):
            self.assertTrue(daycare_supabase.billing_recent_send(None, INV, 120))
        self.assertEqual("billing_link_sends", seen["resource"])
        self.assertEqual("in.(created,sent,delivered)", seen["query"]["status"])
        self.assertTrue(seen["query"]["created_at"].startswith("gte.20"))
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", return_value=[]):
            self.assertFalse(daycare_supabase.billing_recent_send(None, INV, 120))

    def run_send(self, ghl, recent=False, rpc=None):
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", return_value=facts()), \
                mock.patch.object(daycare_supabase, "billing_recent_send", return_value=recent), \
                mock.patch.object(daycare_supabase, "billing_rpc", side_effect=rpc or self.rpc), \
                mock.patch.object(stripe_io, "_req", FakeStripe()), \
                mock.patch.object(stripe_io, "key_for_location", return_value="sk_test_abc"):
            return bl.send(None, INV, "Hi {{PAY_URL}}", ghl)

    def rpc(self, session, name, body, write=True):
        if name == "billing_create_link_send":
            return [{"id": "s1", "token": "T", "pay_url": "https://p/T", "message": "Hi https://p/T"}]

    def test_recent_row_blocks_with_409_before_stripe_or_ghl(self):
        ghl = FakeGHL(existing="c9")
        stripe = FakeStripe()
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", return_value=facts()), \
                mock.patch.object(daycare_supabase, "billing_recent_send", return_value=True), \
                mock.patch.object(daycare_supabase, "billing_rpc") as rpc, \
                mock.patch.object(stripe_io, "_req", stripe):
            with self.assertRaises(bl.BillingLinkError) as cm:
                bl.send(None, INV, "Hi {{PAY_URL}}", ghl)
        self.assertEqual((409, bl.TOO_SOON), (cm.exception.status, cm.exception.message))
        self.assertEqual(({"ok": False, "detail": bl.TOO_SOON}),
                         {k: cm.exception.payload()[k] for k in ("ok", "detail")})
        self.assertEqual(([], [], []), (stripe.calls, ghl.posts, rpc.mock_calls))

    def test_unknown_ghl_outcome_cannot_be_blindly_retried(self):
        class GHLSendUnknown(RuntimeError):
            pass
        with self.assertRaises(bl.BillingLinkError) as cm:
            self.run_send(FakeGHL(existing="c9", fail_send=GHLSendUnknown("timeout")))
        self.assertEqual(502, cm.exception.status)
        ghl2 = FakeGHL(existing="c9")
        with self.assertRaises(bl.BillingLinkError) as cm:      # retry right away: DB says 'failed', memory says wait
            self.run_send(ghl2)
        self.assertEqual(409, cm.exception.status)
        self.assertEqual([], ghl2.posts)

    def test_definite_ghl_rejection_can_be_retried_at_once(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, None)
        with self.assertRaises(bl.BillingLinkError) as cm:
            self.run_send(FakeGHL(existing="c9", fail_send=err))
        self.assertEqual("ghl_send", cm.exception.code)
        out = self.run_send(FakeGHL(existing="c9"))              # nothing went out the first time
        self.assertEqual("sent", out["status"])


class FollowUps(unittest.TestCase):
    """Verifier follow-ups: pending payment block, mark() never crashes, created-row refresh, per-center sync key."""

    def setUp(self):
        bl._RECENT.clear()
        bl._INFLIGHT.clear()
        bl._REFRESHED.clear()

    def test_pending_payment_warns_in_compose_and_refuses_send(self):
        f = facts(has_pending_payment=True)
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", return_value=f):
            out = bl.compose(None, INV)
            self.assertIn("A payment is processing for this invoice.", out["warnings"])
            self.assertEqual(2500, out["facts"]["balance_cents"])        # balance math untouched
            stripe = FakeStripe()
            with mock.patch.object(stripe_io, "_req", stripe), \
                    mock.patch.object(daycare_supabase, "billing_recent_send", return_value=False):
                with self.assertRaises(bl.BillingLinkError) as cm:
                    bl.send(None, INV, "Hi {{PAY_URL}}", FakeGHL(existing="c9"))
        self.assertEqual((409, "A payment is processing for this invoice. Wait for it to clear before sending a link."),
                         (cm.exception.status, cm.exception.message))
        self.assertEqual([], stripe.calls)

    def test_pending_flag_from_payments_but_balance_ignores_pending(self):
        inv = {"id": INV, "invoice_number": "I", "amount": "100.00", "status": "due", "guardian_id": "g1",
               "location_id": ATOB, "children": {"id": "c", "first_name": "Maya", "last_name": "S"},
               "profiles": {"id": "g1", "first_name": "Dana", "display_name": "Dana"},
               "payments": [{"amount": "40.00", "status": "pending"}]}

        def rest(session, method, resource, **kw):
            return [inv] if resource == "invoices" else []
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest), \
                mock.patch.object(daycare_supabase, "_merge_contacts", lambda s, p: None), \
                mock.patch.object(daycare_supabase, "active_location", return_value=ATOB):
            f = daycare_supabase.billing_invoice_facts(None, INV)
        self.assertEqual((True, 10000), (f["has_pending_payment"], f["balance_cents"]))

    def test_mark_failure_of_any_kind_does_not_crash_the_response(self):
        def rpc(session, name, body, write=True):
            if name == "billing_create_link_send":
                return [{"id": "s1", "token": "T", "pay_url": "https://p/T", "message": "Hi https://p/T"}]
            raise RuntimeError("db down")                                  # not a DaycareError
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", return_value=facts()), \
                mock.patch.object(daycare_supabase, "billing_recent_send", return_value=False), \
                mock.patch.object(daycare_supabase, "billing_rpc", side_effect=rpc), \
                mock.patch.object(stripe_io, "_req", FakeStripe()), \
                mock.patch.object(stripe_io, "key_for_location", return_value="sk_test_abc"):
            out = bl.send(None, INV, "Hi {{PAY_URL}}", FakeGHL(existing="c9"))
        self.assertTrue(out["ok"])
        self.assertIn("warning", out)

    def test_timeline_refresh_asks_for_created_and_sent_rows(self):
        seen = {}

        def rows(session, invoice_id, statuses=("sent",)):
            seen["statuses"] = tuple(statuses)
            return [{"id": "s1", "ghl_message_id": "m1"}, {"id": "s2", "ghl_message_id": None}]
        calls = []

        def rpc(session, name, body, write=True):
            calls.append((name, body))
            return {"invoice": {}, "sends": [], "payments": [], "alerts": []}
        with mock.patch.object(daycare_supabase, "billing_send_rows", side_effect=rows), \
                mock.patch.object(daycare_supabase, "billing_rpc", side_effect=rpc):
            bl.timeline(None, INV, FakeGHL())
        self.assertEqual(("created", "sent"), seen["statuses"])
        self.assertEqual([("billing_set_link_delivery", {"p_id": "s1", "p_status": "delivered"})], calls[:1])
        self.assertEqual(1, len([c for c in calls if c[0] == "billing_set_link_delivery"]))   # no message id -> skipped

    def test_send_rows_query_uses_status_list(self):
        seen = {}

        def rest(session, method, resource, query=None, **kw):
            seen.update(query)
            return []
        with mock.patch.object(daycare_supabase.BRIDGE, "rest", side_effect=rest):
            daycare_supabase.billing_send_rows(None, INV, ("created", "sent"))
        self.assertEqual("in.(created,sent)", seen["status"])

    def test_invoice_status_uses_the_invoices_own_center_key(self):
        keys = []

        def fake(method, path, params=None, key=None):
            keys.append(key)
            return {"data": []}
        with mock.patch.object(stripe_io, "_req", fake), \
                mock.patch.object(stripe_io, "key_for_location", return_value="sk_test_abc") as kfl:
            out = stripe_io.invoice_status(INV, QA)
        kfl.assert_called_once_with(QA)
        self.assertEqual(["sk_test_abc"], keys)
        self.assertEqual((True, False), (out["configured"], out["sent"]))

    def test_invoice_status_test_key_missing_reports_unconfigured(self):
        with mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY__DAYCARE_TEST": ""}), \
                mock.patch.object(daycare_supabase, "_read_env", return_value={}):
            self.assertEqual({"ok": True, "configured": False}, stripe_io.invoice_status(INV, QA))

    def test_sync_payment_looks_up_with_the_center_key(self):
        import connector
        seen = {}
        ctx = {"invoice_id": INV, "location_id": QA}
        with mock.patch.object(daycare_supabase, "stripe_invoice_context", return_value=ctx), \
                mock.patch.object(stripe_io, "key_for_location", return_value="sk_test_abc"), \
                mock.patch.object(stripe_io, "find_invoice",
                                  side_effect=lambda i, key=None: seen.update(key=key)):
            out = connector.Handler._daycare_stripe_sync_payment(object.__new__(connector.Handler), None, {"invoice_id": INV})
        self.assertEqual("sk_test_abc", seen["key"])
        self.assertFalse(out["synced"])


class FamilyTags(unittest.TestCase):
    """The GHL chat bot skips `daycare family` / `entity-amt`: tag (additively) BEFORE texting."""

    def setUp(self):
        bl._RECENT.clear()
        bl._INFLIGHT.clear()

    def rpc(self, session, name, body, write=True):
        if name == "billing_create_link_send":
            return [{"id": "s1", "token": "T", "pay_url": "https://p/T", "message": "Hi https://p/T"}]

    def send(self, ghl, f=None):
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", return_value=f or facts()), \
                mock.patch.object(daycare_supabase, "billing_recent_send", return_value=False), \
                mock.patch.object(daycare_supabase, "billing_rpc", side_effect=self.rpc), \
                mock.patch.object(stripe_io, "_req", FakeStripe()), \
                mock.patch.object(stripe_io, "key_for_location", return_value="sk_test_abc"):
            return bl.send(None, INV, "Hi {{PAY_URL}}", ghl)

    def paths(self, ghl):
        return [p for p, _ in ghl.posts]

    def test_atob_family_tagged_once_additively_before_the_text(self):
        ghl = FakeGHL(existing="c9")
        out = self.send(ghl)
        tag_posts = [(p, b) for p, b in ghl.posts if p.endswith("/tags")]
        self.assertEqual([("/contacts/c9/tags", {"tags": ["daycare family"]})], tag_posts)
        self.assertLess(self.paths(ghl).index("/contacts/c9/tags"), self.paths(ghl).index("/conversations/messages"))
        self.assertNotIn("/contacts/", self.paths(ghl))            # no upsert that could replace tags
        self.assertNotIn("warning", out)

    def test_amt_adds_entity_amt(self):
        ghl = FakeGHL(existing="c9")
        self.send(ghl, facts(location_id=AMT))
        self.assertEqual([{"tags": ["daycare family", "entity-amt"]}],
                         [b for p, b in ghl.posts if p.endswith("/tags")])

    def test_qa_and_921_get_no_entity_tag(self):
        for loc in (QA, ATOB):
            ghl = FakeGHL(existing="c9")
            bl._RECENT.clear()
            self.send(ghl, facts(location_id=loc))
            self.assertEqual([{"tags": ["daycare family"]}], [b for p, b in ghl.posts if p.endswith("/tags")])

    def test_tag_failure_does_not_block_the_text_and_warns(self):
        ghl = FakeGHL(existing="c9", fail_tags=True)
        out = self.send(ghl)
        self.assertIn("/conversations/messages", self.paths(ghl))
        self.assertEqual("sent", out["status"])
        self.assertIn("daycare family", out["warning"])

    def test_new_contact_is_created_untagged_then_tagged_additively(self):
        ghl = FakeGHL()                                           # phone not found -> contact created as 'newc'
        self.send(ghl)
        create = [b for p, b in ghl.posts if p == "/contacts/"][0]
        self.assertNotIn("tags", create)                          # creation never carries a tags list
        self.assertIn("/contacts/newc/tags", self.paths(ghl))

    def test_legacy_text_invoice_tags_too(self):
        ghl = FakeGHL(existing="c9")
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", return_value=facts(location_id=AMT)), \
                mock.patch.object(stripe_io, "find_invoice", return_value=None), \
                mock.patch.object(stripe_io, "key_for_location", return_value="sk_test_abc"):
            out = bl.legacy_text(None, {"invoice_id": INV}, ghl)
        self.assertTrue(out["ok"])
        self.assertEqual([{"tags": ["daycare family", "entity-amt"]}],
                         [b for p, b in ghl.posts if p.endswith("/tags")])

    def test_legacy_text_tag_failure_still_sends(self):
        ghl = FakeGHL(existing="c9", fail_tags=True)
        with mock.patch.object(daycare_supabase, "billing_invoice_facts", return_value=facts()), \
                mock.patch.object(stripe_io, "find_invoice", return_value=None), \
                mock.patch.object(stripe_io, "key_for_location", return_value="sk_test_abc"):
            out = bl.legacy_text(None, {"invoice_id": INV}, ghl)
        self.assertTrue(out["ok"])
        self.assertIn("warning", out)

    def test_blast_transport_tags_by_the_blasts_center(self):
        import connector
        import daycare_blast
        seen = []
        ghl = FakeGHL(existing="c9")
        old = daycare_blast._TRANSPORT
        self.addCleanup(setattr, daycare_blast, "_TRANSPORT", old)
        daycare_blast.register_transport(lambda rec, text: seen.append(rec) or {"ok": True})
        daycare_blast._send_one({"phone": "+15555550100", "text": "hi"}, AMT)
        self.assertEqual(AMT, seen[0]["locationId"])                # the blast's center reaches the transport
        with mock.patch.object(connector, "DAYCARE_GHL", ghl), \
                mock.patch.object(daycare_ghl, "ensure_contact", return_value="c9"):
            out = connector._daycare_blast_transport({"name": "Dana", "phone": "+15555550100", "locationId": AMT}, "hi")
        self.assertTrue(out["ok"])
        self.assertEqual([{"tags": ["daycare family", "entity-amt"]}],
                         [b for p, b in ghl.posts if p.endswith("/tags")])
        self.assertLess(self.paths(ghl).index("/contacts/c9/tags"), self.paths(ghl).index("/conversations/messages"))

    def test_blast_tag_failure_still_texts(self):
        import connector
        ghl = FakeGHL(existing="c9", fail_tags=True)
        with mock.patch.object(connector, "DAYCARE_GHL", ghl), \
                mock.patch.object(daycare_ghl, "ensure_contact", return_value="c9"):
            out = connector._daycare_blast_transport({"name": "Dana", "phone": "+15555550100"}, "hi")
        self.assertTrue(out["ok"])
        self.assertIn("/conversations/messages", self.paths(ghl))

    def test_blast_tag_failure_shows_in_the_report_note(self):
        import connector
        ghl = FakeGHL(existing="c9", fail_tags=True)
        with mock.patch.object(connector, "DAYCARE_GHL", ghl), \
                mock.patch.object(daycare_ghl, "ensure_contact", return_value="c9"):
            out = connector._daycare_blast_transport({"name": "Dana", "phone": "+15555550100"}, "hi")
        self.assertTrue(out["ok"])
        self.assertIn("daycare family", out["note"])
        ghl_ok = FakeGHL(existing="c9")
        with mock.patch.object(connector, "DAYCARE_GHL", ghl_ok), \
                mock.patch.object(daycare_ghl, "ensure_contact", return_value="c9"):
            self.assertEqual({"ok": True, "note": ""},
                             connector._daycare_blast_transport({"name": "Dana", "phone": "+15555550100"}, "hi"))

    def test_no_contact_id_means_no_tag_call(self):
        for empty in (None, "", "None"):
            ghl = FakeGHL()
            self.assertTrue(daycare_ghl.add_family_tags(ghl, empty, AMT))      # returns a warning
            self.assertEqual([], ghl.posts)


class Routes(unittest.TestCase):
    def test_routes_registered(self):
        import inspect
        import connector
        post = inspect.getsource(connector.Handler._handle_daycare_post)
        get = inspect.getsource(connector.Handler._handle_daycare_get)
        for path in ("/api/daycare/billing/link/compose", "/api/daycare/billing/link/send"):
            self.assertGreaterEqual(post.count(path), 2)       # allowlist + dispatch
        self.assertIn("/api/daycare/billing/timeline", get)


if __name__ == "__main__":
    unittest.main()
