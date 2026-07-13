import inspect
import unittest

import connector


PLANNED_GETS = {
    "/api/daycare/auth/status", "/api/daycare/status", "/api/daycare/overview",
    "/api/daycare/children", "/api/daycare/attendance", "/api/daycare/classrooms",
    "/api/daycare/staff", "/api/daycare/logs", "/api/daycare/incidents",
    "/api/daycare/announcements", "/api/daycare/threads", "/api/daycare/thread",
    "/api/daycare/notifications", "/api/daycare/billing", "/api/daycare/payroll",
    "/api/daycare/reports", "/api/daycare/media/signed-read",
}

PLANNED_POSTS = {
    "/api/daycare/auth/login", "/api/daycare/auth/logout",
    "/api/daycare/child/save", "/api/daycare/child/deactivate",
    "/api/daycare/classroom/save", "/api/daycare/classroom/archive",
    "/api/daycare/staff/save", "/api/daycare/staff/deactivate",
    "/api/daycare/schedule/save", "/api/daycare/attendance/set",
    "/api/daycare/attendance/sign-out-all", "/api/daycare/log/save",
    "/api/daycare/incident/save", "/api/daycare/announcement/save",
    "/api/daycare/announcement/delete", "/api/daycare/thread/save",
    "/api/daycare/thread/rename", "/api/daycare/thread/leave",
    "/api/daycare/message/send", "/api/daycare/message/react",
    "/api/daycare/notifications/read", "/api/daycare/invoice/save",
    "/api/daycare/invoice/record-payment", "/api/daycare/payroll/save",
    "/api/daycare/payroll/record-paid", "/api/daycare/media/sign-upload",
}


class DaycareConnectorContractTests(unittest.TestCase):
    def test_all_approved_routes_are_explicitly_registered(self):
        get_source = inspect.getsource(connector.Handler._handle_daycare_get)
        post_source = inspect.getsource(connector.Handler._handle_daycare_post)
        self.assertEqual(set(), {path for path in PLANNED_GETS if path not in get_source})
        self.assertEqual(set(), {path for path in PLANNED_POSTS if path not in post_source})

    def test_auth_status_is_handled_before_secure_session_requirement(self):
        source = inspect.getsource(connector.Handler._handle_daycare_get)
        self.assertLess(
            source.index('path == "/api/daycare/auth/status"'),
            source.index("self._daycare_require_secure()"),
        )
        self.assertIn("sid if secure else None", source)
        self.assertIn('result["secureRequired"] = True', source)

    def test_expected_error_statuses_are_supported(self):
        source = inspect.getsource(connector.Handler._handle_daycare_post)
        self.assertIn("DaycareError", source)
        for status in (400, 401, 403, 409, 502):
            error = connector.daycare_supabase.DaycareError(status, "safe", "test")
            self.assertEqual(error.payload()["error"], "safe")
            self.assertEqual(error.status, status)


if __name__ == "__main__":
    unittest.main()
