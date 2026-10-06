"""Parent login fixes + App Tracking (spec 2026-10-06). No network: BRIDGE is mocked."""
import time
import unittest
from unittest import mock

import daycare_supabase as daycare

LOC = "11111111-1111-1111-1111-111111111111"
CHILD = {"first_name": "Zztest", "last_name": "Alpha", "birth_date": "2022-04-04",
         "guardian_first_name": "Ana", "guardian_last_name": "Lopez",
         "guardian_email": "ana@example.com", "guardian_phone": "+12155550120"}


class SaveChildLinkOnly(unittest.TestCase):
    def run_save(self, source, existing=None, edge_result=None):
        edge = mock.Mock(return_value=edge_result or {"profile_id": "a0000000-0000-0000-0000-000000000001",
                                                      "login_id": "Ana Lopez", "existing": True, "linked": True})
        rest = mock.Mock(return_value=[{"id": "c0000000-0000-0000-0000-000000000001"}])
        with mock.patch.object(daycare.BRIDGE, "edge_function", edge), \
             mock.patch.object(daycare.BRIDGE, "rest", rest), \
             mock.patch.object(daycare, "active_location", return_value=LOC), \
             mock.patch.object(daycare, "_ensure_location_record", return_value=existing):
            return daycare.save_child(object(), {"child": source}), edge

    def test_link_only_sent_on_create_login_path(self):
        result, edge = self.run_save({**CHILD, "guardian_link_only": True})
        body = edge.call_args.args[2]
        self.assertTrue(body["link_only"])
        self.assertTrue(edge.call_args.kwargs.get("surface_errors"))
        self.assertTrue(result["provision"]["linked"])
        self.assertNotIn("pin", result["provision"])

    def test_link_only_absent_on_manual_add(self):
        _, edge = self.run_save(dict(CHILD))
        self.assertNotIn("link_only", edge.call_args.args[2])

    def test_already_linked_child_says_so(self):
        existing = {"id": "c0000000-0000-0000-0000-000000000001",
                    "guardian_profile_id": "a0000000-0000-0000-0000-000000000009"}
        result, edge = self.run_save({**CHILD, "id": existing["id"], "guardian_link_only": True}, existing=existing)
        edge.assert_not_called()
        self.assertTrue(result["already_linked"])


class ResetFlag(unittest.TestCase):
    def test_only_if_never_signed_in_is_forwarded(self):
        edge = mock.Mock(return_value={"profile_id": "p", "login_id": "Ana Lopez", "pin": "12345678", "reset": True})
        with mock.patch.object(daycare.BRIDGE, "edge_function", edge):
            daycare.reset_credentials(object(), {"profile_id": "a0000000-0000-0000-0000-000000000001",
                                                 "only_if_never_signed_in": True})
        self.assertTrue(edge.call_args.args[2]["only_if_never_signed_in"])
        self.assertTrue(edge.call_args.kwargs.get("surface_errors"))


class AppTrackingReader(unittest.TestCase):
    def test_reads_without_write_gate(self):
        rpc = mock.Mock(return_value={"totals": {"families": 3}})
        with mock.patch.object(daycare.BRIDGE, "rpc", rpc):
            out = daycare.app_tracking(object(), LOC)
        self.assertEqual(out, {"ok": True, "tracking": {"totals": {"families": 3}}})
        self.assertEqual(rpc.call_args.args[1:3], ("app_tracking", {"p_location": LOC}))
        self.assertIs(rpc.call_args.kwargs["write"], False)

    def test_rejects_non_uuid(self):
        with self.assertRaises(daycare.DaycareError):
            daycare.app_tracking(object(), "921")



import daycare_ghl as g


class Readiness(unittest.TestCase):
    def card(self, **kw):
        base = {"enrolled": True, "child_first": "Maria", "child_last": "Lopez", "child_dob": "2022-04-04",
                "parent_first": "Ana", "parent_last": "Lopez", "location_tag": "loc-921-n-18th",
                "email": "ana@example.com", "phone": "+12155550120"}
        base.update(kw)
        return base

    def test_complete_card_is_ready(self):
        self.assertEqual(g._readiness(self.card()), [])

    def test_missing_dob_and_parent_names_listed(self):
        missing = g._readiness(self.card(child_dob="", parent_first="", parent_last=""))
        for item in ("child birth date", "parent first name", "parent last name"):
            self.assertIn(item, missing)

    def test_us_dob_is_fine_future_dob_is_not(self):
        self.assertEqual(g._readiness(self.card(child_dob="03/14/2023")), [])
        self.assertIn("child birth date", g._readiness(self.card(child_dob="2099-01-01")))

    def test_iso_date(self):
        self.assertEqual(g.iso_date("03/14/2023"), "2023-03-14")
        self.assertEqual(g.iso_date("2023-03-14"), "2023-03-14")
        self.assertEqual(g.iso_date("next spring"), "")

    def test_app_tracking_centers_never_list_qa(self):
        self.assertEqual(set(g.APP_TRACKING_CENTERS), {"921", "2318", "1923"})
        self.assertNotIn("99999999-9999-9999-9999-999999999999", g.APP_TRACKING_CENTERS.values())


import json
import tempfile
from pathlib import Path

import daycare_login_queue as lq

# 2026-10-07 08:05 and 22:30 America/New_York (EDT, UTC-4)
AT_0805 = 1791374700.0
AT_2230 = 1791426600.0
ENTRY = {"profile_id": "a0000000-0000-0000-0000-000000000001", "contact_id": "ghl1",
         "location_id": LOC, "parent_first": "Ana", "child_first": "Maria"}


class LoginQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(lq, "STATE", Path(self.tmp.name) / "q.json")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def tick(self, mint, send=None, now=AT_0805):
        return lq.run_once(lambda: "S", mint, send or (lambda e, p: {"ok": True}), now=now)

    def test_enqueue_dedupes_by_profile(self):
        lq.enqueue(ENTRY); lq.enqueue({**ENTRY, "child_first": "Juan"})
        self.assertEqual(len(lq.view()["queued"]), 1)

    def test_nothing_sent_outside_window(self):
        lq.enqueue(ENTRY)
        mint = mock.Mock()
        self.assertEqual(self.tick(mint, now=AT_2230)["sent"], 0)
        mint.assert_not_called()

    def test_8am_tick_mints_and_sends_then_clears(self):
        lq.enqueue(ENTRY)
        send = mock.Mock(return_value={"ok": True})
        out = self.tick(lambda s, e: {"pin": "12345678", "login_id": "Ana Lopez"}, send)
        self.assertEqual(out["sent"], 1)
        self.assertEqual(send.call_args.args[1]["pin"], "12345678")
        self.assertEqual(lq.view()["queued"], [])

    def test_already_signed_in_is_dropped_not_retried(self):
        lq.enqueue(ENTRY)
        send = mock.Mock()
        out = self.tick(lambda s, e: {"error": "already_signed_in"}, send)
        send.assert_not_called()
        self.assertEqual((out["dropped"], lq.view()["queued"]), (1, []))
        self.assertIn("already signed in", lq.view()["done"][-1]["outcome"])

    def test_force_entry_mints_without_signed_in_guard(self):
        lq.enqueue({**ENTRY, "force": True})
        seen = {}
        self.tick(lambda s, e: seen.update(e) or {"pin": "1", "login_id": "x"})
        self.assertTrue(seen["force"])

    def test_send_failure_after_mint_is_never_retried(self):
        # A retry would mint ANOTHER PIN nobody sees. One reset, then a staff-visible problem.
        lq.enqueue(ENTRY)
        mint = mock.Mock(return_value={"pin": "1", "login_id": "x"})
        for _ in range(3):
            self.tick(mint, lambda e, p: {"ok": False, "error": "GHL 500"})
        self.assertEqual(mint.call_count, 1)
        self.assertEqual(lq.view()["queued"], [])
        problem = lq.view()["problems"][-1]
        self.assertIn("GHL 500", problem["outcome"])
        self.assertEqual((problem["parent"], problem["child"]), ("Ana", "Maria"))

    def test_blocked_contact_is_never_minted(self):
        lq.enqueue(ENTRY)
        mint = mock.Mock()
        out = lq.run_once(lambda: "S", mint, mock.Mock(), now=AT_0805,
                          can_send_fn=lambda e: "parent opted out — not sent")
        mint.assert_not_called()
        self.assertEqual(out["dropped"], 1)
        self.assertIn("opted out", lq.view()["problems"][-1]["outcome"])
        self.assertIn("PIN unchanged", lq.view()["problems"][-1]["outcome"])

    def test_mint_outage_keeps_retrying_well_past_three_ticks(self):
        lq.enqueue(ENTRY)
        for _ in range(5):
            self.tick(lambda s, e: {"error": "Daycare database request failed"})
        self.assertEqual(len(lq.view()["queued"]), 1)
        self.assertEqual(lq.view()["problems"], [])

    def test_mint_outage_gives_up_after_max_tries(self):
        lq.enqueue(ENTRY)
        for _ in range(lq.MAX_TRIES):
            self.tick(lambda s, e: {"error": "Daycare database request failed"})
        self.assertEqual(lq.view()["queued"], [])
        self.assertIn("gave up", lq.view()["problems"][-1]["outcome"])

    def test_concurrent_run_is_skipped(self):
        lq.enqueue(ENTRY)
        mint = mock.Mock()
        self.assertTrue(lq._RUN.acquire(blocking=False))
        try:
            out = self.tick(mint)
        finally:
            lq._RUN.release()
        mint.assert_not_called()
        self.assertEqual(out.get("skipped"), "already running")

    def test_resend_queued_during_a_run_is_not_lost(self):
        lq.enqueue(ENTRY)
        def mint(_s, e):
            lq.enqueue({**ENTRY, "force": True})   # owner taps Resend while the 8am tick runs
            return {"error": "already_signed_in"}
        self.tick(mint)
        queued = lq.view()["queued"]
        self.assertEqual(len(queued), 1)
        self.assertTrue(queued[0]["force"])

    def test_interrupted_send_becomes_a_problem_not_a_resend(self):
        lq.STATE.write_text(json.dumps({"queue": {}, "inflight": {ENTRY["profile_id"]: {
            **ENTRY, "force": False, "queued_at": AT_0805 - 4000, "tries": 0, "started": AT_0805 - 1000}}}))
        mint = mock.Mock()
        self.tick(mint)
        mint.assert_not_called()
        self.assertIn("interrupted", lq.view()["problems"][-1]["outcome"])
        self.assertEqual(lq.view()["queued"], [])

    def test_no_session_reports_error_and_keeps_queue(self):
        lq.enqueue(ENTRY)
        out = lq.run_once(lambda: None, mock.Mock(), mock.Mock(), now=AT_0805)
        self.assertFalse(out["ok"])
        self.assertEqual(len(lq.view()["queued"]), 1)

    def test_pin_never_written_to_state(self):
        lq.enqueue(ENTRY)
        self.tick(lambda s, e: {"pin": "87654321", "login_id": "x"}, lambda e, p: {"ok": False, "error": "x"})
        self.assertNotIn("87654321", lq.STATE.read_text())


import connector


class ConnectorLoginPieces(unittest.TestCase):
    def test_queue_mint_uses_signed_in_guard_unless_forced(self):
        reset = mock.Mock(return_value={"provision": {"pin": "1", "login_id": "x"}})
        with mock.patch.object(connector.daycare_supabase, "reset_credentials", reset), \
             mock.patch.object(connector.daycare_supabase, "at_location", mock.MagicMock()):
            connector._daycare_queue_mint("S", {**ENTRY, "force": False})
            self.assertTrue(reset.call_args.args[1]["only_if_never_signed_in"])
            connector._daycare_queue_mint("S", {**ENTRY, "force": True})
            self.assertNotIn("only_if_never_signed_in", reset.call_args.args[1])

    def test_queue_mint_maps_409_to_already_signed_in(self):
        err = connector.daycare_supabase.DaycareError(409, "already_signed_in", "function_error")
        with mock.patch.object(connector.daycare_supabase, "reset_credentials", side_effect=err), \
             mock.patch.object(connector.daycare_supabase, "at_location", mock.MagicMock()):
            self.assertEqual(connector._daycare_queue_mint("S", ENTRY), {"error": "already_signed_in"})

    def test_resend_without_contact_shows_pin_only(self):
        h = object.__new__(connector.Handler)
        with mock.patch.object(connector.daycare_supabase, "at_location", mock.MagicMock()), \
             mock.patch.object(connector.daycare_supabase, "guardian_contact",
                               return_value={"id": ENTRY["profile_id"], "name": "Ana Lopez", "phone": "", "role": "parent"}), \
             mock.patch.object(connector.daycare_ghl, "find_contact_by_phone", return_value=None), \
             mock.patch.object(connector.daycare_supabase, "reset_credentials",
                               return_value={"provision": {"login_id": "Ana Lopez", "pin": "12345678"}}), \
             mock.patch.dict("sys.modules", {"action_log": mock.Mock()}), \
             mock.patch.object(connector.daycare_replies, "send_manual") as send:
            out = h._daycare_resend_login("S", {"profile_id": ENTRY["profile_id"], "location_id": LOC})
        send.assert_not_called()
        self.assertEqual(out["provision"]["pin"], "12345678")
        self.assertIn("No GHL contact", out["provision"]["texted"]["error"])

    def test_app_tracking_rejects_unknown_center(self):
        h = object.__new__(connector.Handler)
        for bad in ("9999", "", "4444"):
            with self.assertRaises(connector.daycare_supabase.DaycareError):
                h._daycare_app_tracking("S", bad)


class EnrollAfterHours(unittest.TestCase):
    """Create login at night: no text now, the login is queued (never the PIN itself)."""
    def test_after_9pm_queues_instead_of_texting(self):
        handler = object.__new__(connector.Handler)
        handler._daycare_family_child_body = lambda _s, fam: {
            "first_name": "Maria", "last_name": "Lopez", "location_id": LOC}
        handler._daycare_child_save = mock.Mock(return_value={"ok": True, "child": {"id": "c1"}, "provision": {
            "profile_id": ENTRY["profile_id"], "login_id": "Ana Lopez", "pin": "482913"}})
        family = {"contact_id": "ghl1", "parent_first": "Ana", "parent_last": "Lopez", "child_first": "Maria",
                  "email": "ana@example.com", "location_id": LOC}
        with mock.patch.object(connector.daycare_ghl, "form_child_id", return_value="c1"), \
             mock.patch.object(connector.daycare_ghl, "record_form_child"), \
             mock.patch.object(connector.daycare_ghl, "dismiss", return_value={"ok": True}), \
             mock.patch.object(connector.daycare_leads, "in_hours", return_value=False), \
             mock.patch.object(connector.daycare_login_queue, "enqueue", return_value={"ok": True}) as enq, \
             mock.patch.object(connector.daycare_replies, "send_manual") as send:
            result = connector.Handler._daycare_ghl_enroll(handler, None, {"family": family})
        send.assert_not_called()
        entry = enq.call_args.args[0]
        self.assertEqual((entry["profile_id"], entry["contact_id"]), (ENTRY["profile_id"], "ghl1"))
        self.assertNotIn("pin", entry)
        self.assertTrue(result["provision"]["texted"]["queued"])
        self.assertTrue(handler._daycare_child_save.call_args.args[1]["child"]["guardian_link_only"])


class AppTrackingNoCrossSessionCache(unittest.TestCase):
    """Security: a result read by an authorized admin must never be served to another session."""
    def test_second_session_is_checked_by_the_database(self):
        h = object.__new__(connector.Handler)
        denied = connector.daycare_supabase.DaycareError(403, "Only an admin of this center can read app tracking", "rejected")
        reader = mock.Mock(side_effect=[{"ok": True, "tracking": {"totals": {"families": 2}}}, denied])
        with mock.patch.object(connector.daycare_supabase, "app_tracking", reader):
            self.assertEqual(h._daycare_app_tracking("ADMIN", "921")["tracking"]["totals"]["families"], 2)
            with self.assertRaises(connector.daycare_supabase.DaycareError):
                h._daycare_app_tracking("MANAGER", "921")
        self.assertEqual(reader.call_count, 2)


class LocationLock(unittest.TestCase):
    """Center switches (at_location / save_child / the switch route) are serialized per process."""
    def test_at_location_holds_the_lock_for_the_block(self):
        session = mock.Mock(profile={"active_location_id": LOC})
        with mock.patch.object(daycare, "switch_location"):
            with daycare.at_location(session, "44444444-4444-4444-4444-444444444444"):
                self.assertTrue(daycare.LOCATION_LOCK._is_owned())
        self.assertFalse(daycare.LOCATION_LOCK._is_owned())


class ResendContactChecks(unittest.TestCase):
    def resend(self, guardian, contact):
        h = object.__new__(connector.Handler)
        with mock.patch.object(connector.daycare_supabase, "at_location", mock.MagicMock()), \
             mock.patch.object(connector.daycare_supabase, "guardian_contact", return_value=guardian), \
             mock.patch.object(connector.daycare_ghl, "find_contact_by_phone", return_value="ghl9"), \
             mock.patch.object(connector.daycare_replies, "_contact", return_value=contact), \
             mock.patch.object(connector.daycare_leads, "in_hours", return_value=True), \
             mock.patch.object(connector.daycare_supabase, "reset_credentials",
                               return_value={"provision": {"login_id": "Ana Lopez", "pin": "12345678"}}) as reset, \
             mock.patch.dict("sys.modules", {"action_log": mock.Mock()}), \
             mock.patch.object(connector.daycare_replies, "send_manual", return_value={"ok": True}) as send:
            try:
                return h._daycare_resend_login("S", {"profile_id": ENTRY["profile_id"], "location_id": LOC}), send, reset
            except connector.daycare_supabase.DaycareError as error:
                return error, send, reset

    def test_pin_never_texted_to_a_contact_whose_phone_differs(self):
        out, send, _ = self.resend({"id": ENTRY["profile_id"], "name": "Ana Lopez", "phone": "+12155550120", "role": "parent"},
                                   {"id": "ghl9", "phone": "+12675550999"})
        send.assert_not_called()
        self.assertIn("share the PIN in person", out["provision"]["texted"]["error"])

    def test_matching_contact_is_texted(self):
        out, send, _ = self.resend({"id": ENTRY["profile_id"], "name": "Ana Lopez", "phone": "(215) 555-0120", "role": "parent"},
                                   {"id": "ghl9", "phone": "+12155550120"})
        send.assert_called_once()
        self.assertTrue(out["provision"]["texted"]["ok"])

    def test_resend_refuses_non_parent_accounts(self):
        out, send, reset = self.resend({"id": ENTRY["profile_id"], "name": "Staff Person", "phone": "+12155550120", "role": "staff"},
                                       {"id": "ghl9", "phone": "+12155550120"})
        self.assertIsInstance(out, connector.daycare_supabase.DaycareError)
        reset.assert_not_called()
        send.assert_not_called()


class FindContactByPhone(unittest.TestCase):
    """GHL's list search lags new contacts and matches fuzzily; the duplicate lookup is exact
    and consistent right after a write (found live: a 30s-old contact was missed)."""
    def client(self, payload):
        c = mock.Mock(location_id="LOC1")
        c.get.return_value = payload
        return c

    def test_uses_exact_duplicate_lookup_in_e164(self):
        c = self.client({"contact": {"id": "ghl7"}})
        self.assertEqual(g.find_contact_by_phone(c, "(215) 555-0142"), "ghl7")
        path, params = c.get.call_args.args
        self.assertEqual(path, "/contacts/search/duplicate")
        self.assertEqual(params, {"locationId": "LOC1", "number": "+12155550142"})

    def test_no_match_is_none(self):
        self.assertIsNone(g.find_contact_by_phone(self.client({"contact": None}), "+12155550142"))
        self.assertIsNone(g.find_contact_by_phone(self.client({}), ""))


if __name__ == "__main__":
    unittest.main()
