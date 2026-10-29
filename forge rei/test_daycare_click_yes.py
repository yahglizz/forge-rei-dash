"""Parent login = owner Create login click + family YES (2026-10-29). No network."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import connector
import daycare_supabase as ds

PID = "11111111-1111-1111-1111-111111111111"
LOC = "44444444-4444-4444-4444-444444444444"
FAMILY = {"contact_id": "ghl1", "card_id": "ghl1", "parent_first": "Ana", "parent_last": "Lopez",
          "child_first": "Maria", "email": "ana@example.com", "location_id": LOC}


class ClickGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = mock.patch.object(connector.daycare_auto_enroll, "STATE", Path(self.tmp.name) / "s.json")
        self.state.start()
        self.h = object.__new__(connector.Handler)
        self.h._daycare_enroll_family = mock.Mock(return_value={"ok": True, "child": {"id": "c1"}})

    def tearDown(self):
        self.state.stop()
        self.tmp.cleanup()

    def click(self, confirmed):
        with mock.patch.object(connector.daycare_auto_enroll, "is_confirmed", return_value=confirmed) as read:
            out = self.h._daycare_ghl_enroll("S", {"family": dict(FAMILY, confirm_state="confirmed")})
        read.assert_called_once_with(connector.DAYCARE_GHL, "ghl1")   # YES re-read from GHL, not the card
        return out

    def test_click_before_yes_only_records_approval(self):
        out = self.click(False)
        self.h._daycare_enroll_family.assert_not_called()
        self.assertTrue(out["waiting_for_yes"])
        self.assertEqual(connector.daycare_auto_enroll.approved_ids(), {"ghl1"})

    def test_click_after_yes_enrolls_now_and_clears_approval(self):
        connector.daycare_auto_enroll.approve("ghl1", "ghl1")
        out = self.click(True)
        self.h._daycare_enroll_family.assert_called_once()
        self.assertEqual(out["child"], {"id": "c1"})
        self.assertEqual(connector.daycare_auto_enroll.approved_ids(), set())


class CheckBlocksText(unittest.TestCase):
    def test_failed_check_means_no_text(self):
        h = object.__new__(connector.Handler)
        h._daycare_family_child_body = lambda _s, fam: {"first_name": "Maria", "last_name": "Lopez", "location_id": LOC}
        h._daycare_child_save = mock.Mock(return_value={"ok": True, "child": {"id": "c1"}, "provision": {
            "profile_id": PID, "login_id": "Ana Lopez", "pin": "48291355"}})
        with mock.patch.object(connector.daycare_ghl, "form_child_id", return_value="c1"), \
             mock.patch.object(connector.daycare_ghl, "record_form_child"), \
             mock.patch.object(connector.daycare_ghl, "dismiss", return_value={"ok": True}), \
             mock.patch.object(connector.daycare_leads, "in_hours", return_value=True), \
             mock.patch.object(connector, "_daycare_login_problem", return_value="parent login is not linked to a child here"), \
             mock.patch.object(connector.daycare_replies, "send_manual") as send:
            out = h._daycare_enroll_family("S", dict(FAMILY))
        send.assert_not_called()
        self.assertIn("login check failed", out["provision"]["texted"]["error"])

    def test_queue_mint_refuses_a_broken_login(self):
        reset = mock.Mock(return_value={"provision": {"pin": "1", "login_id": "Ana Lopez"}})
        with mock.patch.object(connector.daycare_supabase, "reset_credentials", reset), \
             mock.patch.object(connector.daycare_supabase, "at_location", mock.MagicMock()), \
             mock.patch.object(connector.daycare_supabase, "login_check", return_value="parent login is turned off"):
            out = connector._daycare_queue_mint("S", {"profile_id": PID, "location_id": LOC})
        self.assertEqual(out, {"error": "login check failed: parent login is turned off"})


class LoginCheck(unittest.TestCase):
    def check(self, profiles, kids, login_id="Ana Lopez", pid=PID):
        rows = {"profiles": profiles, "children": kids}
        with mock.patch.object(ds, "active_location", return_value=LOC), \
             mock.patch.object(ds.BRIDGE, "rest", side_effect=lambda _s, _m, table, **_k: rows[table]):
            return ds.login_check("S", pid, login_id)

    def test_whole_login_passes(self):
        self.assertIsNone(self.check([{"id": PID, "role": "parent", "active": True}], [{"id": "c1"}]))

    def test_each_gap_has_a_reason(self):
        parent = {"id": PID, "role": "parent", "active": True}
        self.assertIn("not at this center", self.check([], [{"id": "c1"}]))
        self.assertIn("not a parent", self.check([{**parent, "role": "staff"}], [{"id": "c1"}]))
        self.assertIn("turned off", self.check([{**parent, "active": False}], [{"id": "c1"}]))
        self.assertIn("not linked to a child", self.check([parent], []))
        self.assertIn("can't be typed", self.check([parent], [{"id": "c1"}], login_id="  "))
        self.assertIn("no parent login id", self.check([parent], [{"id": "c1"}], pid="x"))

    def test_slug_matches_the_app(self):
        self.assertEqual(ds.login_slug("José  Núñez 2"), "jose-nunez-2")   # lib/login.ts loginSlug


if __name__ == "__main__":
    unittest.main()
