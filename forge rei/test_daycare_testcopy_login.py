"""Local test-copy auto sign-in (FORGE_DAYCARE_TEST_AUTOLOGIN): every guard, mocked.
Run: python3 -m unittest test_daycare_testcopy_login  (from `forge rei/`)."""
import dataclasses
import io
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

import daycare_supabase as ds

QA = ds.QA_SANDBOX_LOCATION_ID
REAL = "11111111-1111-1111-1111-111111111111"
ENV_OK = {"FORGE_DAYCARE_TEST_AUTOLOGIN": "1", "FORGE_HOST": "127.0.0.1"}
SECRET_PIN = "654321"


def make_session(role="admin", home=QA, active=QA, sid="s1"):
    now = time.time()
    return ds.Session(sid=sid, access_token="tok", refresh_token="ref", token_expires_at=now + 3600,
                      created_at=now, absolute_expires_at=now + 3600, idle_expires_at=now + 3600,
                      profile_checked_at=now,
                      profile={"id": "p1", "role": role, "location_id": home, "active_location_id": active})


class Base(unittest.TestCase):
    def setUp(self):
        ds.clear_sessions()
        ds._TESTCOPY_WARNED.clear()
        cfg = dataclasses.replace(ds.CONFIG, location_id=QA, autoadmin=True,
                                  test_profiles=(("admin", "BL-REAL-1", "111111"),))
        self.bridge = ds.SupabaseBridge(cfg)
        self.addCleanup(ds.clear_sessions)
        env = mock.patch.dict("os.environ", ENV_OK, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for k in ("FORGE_MARCUS",):
            p = mock.patch.dict("os.environ", {}, clear=False)
            p.start()
            self.addCleanup(p.stop)
            __import__("os").environ.pop(k, None)
        creds = mock.patch.object(ds, "_testcopy_credentials", return_value=("BL-ADM-100001", SECRET_PIN))
        creds.start()
        self.addCleanup(creds.stop)

    def sign_in(self, session=None, locations=None, **kw):
        session = session or make_session()
        locs = [{"id": QA}] if locations is None else locations

        def login(login_id, pin):
            ds._SESSIONS[session.sid] = session
            return session, {}
        self.login = mock.Mock(side_effect=login)
        with mock.patch.object(self.bridge, "login", self.login), \
                mock.patch.object(self.bridge, "rest", return_value=locs, **kw), \
                mock.patch.object(self.bridge, "logout", wraps=self.bridge.logout) as self.logout:
            return self.bridge.testcopy_session()


class Refusal(unittest.TestCase):
    def test_all_guards(self):
        self.assertIsNone(ds.testcopy_refusal(dict(ENV_OK), QA))
        self.assertIsNone(ds.testcopy_refusal({"FORGE_DAYCARE_TEST_AUTOLOGIN": "1"}, QA))      # FORGE_HOST default = 127.0.0.1
        self.assertTrue(ds.testcopy_refusal({}, QA))                                            # flag absent
        self.assertTrue(ds.testcopy_refusal({"FORGE_DAYCARE_TEST_AUTOLOGIN": "0"}, QA))
        self.assertTrue(ds.testcopy_refusal({**ENV_OK, "FORGE_HOST": "0.0.0.0"}, QA))
        self.assertTrue(ds.testcopy_refusal({**ENV_OK, "FORGE_HOST": "localhost"}, QA))
        self.assertTrue(ds.testcopy_refusal({**ENV_OK, "FORGE_MARCUS": "1"}, QA))
        self.assertTrue(ds.testcopy_refusal(dict(ENV_OK), REAL))                                # config points at a real center

    def test_credentials_parse_like_the_app_card(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / ".env.local"
            f.write_text("NEXT_PUBLIC_TEST_LOGIN_ADMIN=BL-ADM-100001:654321\n")
            self.assertEqual(("BL-ADM-100001", "654321"), ds._testcopy_credentials(f))
            for bad in ("", "BL-ADM-100001", "BL-ADM-100001:123", ":654321", "bad id:654321"):
                f.write_text(f"NEXT_PUBLIC_TEST_LOGIN_ADMIN={bad}\n")
                self.assertIsNone(ds._testcopy_credentials(f), bad)


class Session_(Base):
    def test_signs_in_through_login_and_caches(self):
        got = self.sign_in()
        self.assertEqual("s1", got.sid)
        self.login.assert_called_once_with("BL-ADM-100001", SECRET_PIN)
        with mock.patch.object(self.bridge, "login") as login:
            self.assertEqual("s1", self.bridge.testcopy_session().sid)    # cached
        login.assert_not_called()

    def test_re_signs_after_expiry(self):
        self.sign_in()
        ds._SESSIONS["s1"].idle_expires_at = time.time() - 1
        fresh = make_session(sid="s2")
        with mock.patch.object(self.bridge, "login", side_effect=lambda *a: (ds._SESSIONS.__setitem__("s2", fresh), (fresh, {}))[1]), \
                mock.patch.object(self.bridge, "rest", return_value=[{"id": QA}]):
            self.assertEqual("s2", self.bridge.testcopy_session().sid)

    def test_refuses_non_admin(self):
        self.assertIsNone(self.sign_in(make_session(role="manager")))
        self.logout.assert_called_once()

    def test_refuses_account_that_sees_another_center(self):
        self.assertIsNone(self.sign_in(locations=[{"id": QA}, {"id": REAL}]))
        self.logout.assert_called_once()

    def test_refuses_real_home_or_active_center(self):
        self.assertIsNone(self.sign_in(make_session(home=REAL, active=QA)))
        self.assertIsNone(self.sign_in(make_session(home=QA, active=REAL)))

    def test_refuses_when_locations_cannot_be_listed(self):
        session = make_session()
        with mock.patch.object(self.bridge, "login", return_value=(session, {})), \
                mock.patch.object(self.bridge, "rest", side_effect=ds.DaycareError(403, "x")), \
                mock.patch.object(self.bridge, "logout") as logout:
            self.assertIsNone(self.bridge.testcopy_session())
        logout.assert_called_once()

    def test_guards_fail_before_any_sign_in(self):
        for env in ({"FORGE_HOST": "0.0.0.0"}, {"FORGE_MARCUS": "1"}):
            with mock.patch.dict("os.environ", env), mock.patch.object(self.bridge, "login") as login:
                self.assertIsNone(self.bridge.testcopy_session())
            login.assert_not_called()
        bridge = ds.SupabaseBridge(dataclasses.replace(ds.CONFIG, location_id=REAL))
        with mock.patch.object(bridge, "login") as login:
            self.assertIsNone(bridge.testcopy_session())
        login.assert_not_called()

    def test_sign_in_failure_keeps_login_screen_and_never_prints_the_pin(self):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(self.bridge, "login",
                                                     side_effect=ds.DaycareError(401, "no", "invalid_credentials")):
            self.assertIsNone(self.bridge.testcopy_session())
        self.assertIn("refused", out.getvalue())
        self.assertNotIn(SECRET_PIN, out.getvalue())
        self.assertNotIn("tok", out.getvalue())


class AutoadminHook(Base):
    def test_remote_or_proxied_clients_get_nothing(self):
        with mock.patch.object(self.bridge, "login") as login:
            self.assertIsNone(self.bridge.autoadmin_session("100.64.0.9"))
            self.assertIsNone(self.bridge.autoadmin_session("127.0.0.1", {"X-Forwarded-For": "1.2.3.4"}))
        login.assert_not_called()

    def test_flag_on_never_falls_back_to_the_real_autoadmin(self):
        with mock.patch.dict("os.environ", {"FORGE_MARCUS": "1"}), \
                mock.patch.object(self.bridge, "login") as login:     # test-copy refused (box)
            self.assertIsNone(self.bridge.autoadmin_session("127.0.0.1"))
        login.assert_not_called()                                      # real autoadmin creds untouched

    def test_flag_on_loopback_gets_the_qa_session(self):
        session = make_session()
        with mock.patch.object(self.bridge, "login", return_value=(session, {})), \
                mock.patch.object(self.bridge, "rest", return_value=[{"id": QA}]):
            self.assertEqual("s1", self.bridge.autoadmin_session("127.0.0.1").sid)

    def test_flag_absent_changes_nothing(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            __import__("os").environ.pop("FORGE_DAYCARE_TEST_AUTOLOGIN", None)
            plain = ds.SupabaseBridge(dataclasses.replace(ds.CONFIG, autoadmin=False))
            with mock.patch.object(plain, "login") as login, mock.patch.object(plain, "testcopy_session") as tc:
                self.assertIsNone(plain.autoadmin_session("127.0.0.1"))
            login.assert_not_called()
            tc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
