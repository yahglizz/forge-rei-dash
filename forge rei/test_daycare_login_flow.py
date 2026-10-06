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


if __name__ == "__main__":
    unittest.main()
