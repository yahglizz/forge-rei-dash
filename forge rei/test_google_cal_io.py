"""google_cal_io — calendar-only Google client for the daycare calendar lane.
Run: python3 test_google_cal_io.py (no network: fake transport)."""
import io
import json
import os
import re
import unittest
import urllib.error
from unittest import mock

import google_cal_io as g

LIVE = "live@group.calendar.google.com"
QA = "qa@group.calendar.google.com"
ENV = {"GMAIL_CLIENT_ID": "cid", "GMAIL_CLIENT_SECRET": "sec", "GOOGLE_CAL_REFRESH_YAHJAIR": "1//fake",
       "GOOGLE_CAL_ID": LIVE, "GOOGLE_CAL_ID_QA": QA}


class Reply(io.BytesIO):
    def __init__(self, status, body=b""):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, body=b"{}"):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(body))


class Fake:
    """Answers by (method, url piece) in order; records every call."""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, req, timeout):
        url, method = req.full_url, req.get_method()
        if "oauth2.googleapis.com" in url:
            return Reply(200, json.dumps({"access_token": "at", "expires_in": 3600}).encode())
        self.calls.append((method, url, json.loads(req.data) if req.data else None))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Base(unittest.TestCase):
    def setUp(self):
        g._TOK.update(access="", exp=0.0)
        g._DEAD[0] = 0.0
        p = mock.patch.dict(os.environ, ENV)
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(g, "_env", lambda: {})
        q.start()
        self.addCleanup(q.stop)

    def use(self, *answers):
        fake = Fake(*answers)
        p = mock.patch.object(g, "_urlopen", fake)
        p.start()
        self.addCleanup(p.stop)
        return fake


class Reminders(Base):
    def test_popups_ride_through_and_the_guard_still_holds(self):
        fake = self.use(Reply(200, b'{"htmlLink": "x"}'))
        body = {"summary": "s", "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 60}]}}
        g.put_event(QA, "abc", body)
        self.assertEqual(fake.calls[0][2]["reminders"], body["reminders"])
        with self.assertRaises(g.CalError):
            g.put_event("personal@gmail.com", "abc", body)


class EventId(Base):
    def test_id_uses_only_googles_alphabet(self):
        for key in ("tour|abc", "first|XYZ", "z" * 200):
            self.assertRegex(g.event_id(key), r"^[a-v0-9]{5,1024}$")

    def test_same_key_same_id_and_different_key_different_id(self):
        self.assertEqual(g.event_id("tour|a"), g.event_id("tour|a"))
        self.assertNotEqual(g.event_id("tour|a"), g.event_id("first|a"))


class Guard(Base):
    def test_refuses_any_calendar_but_the_two_daycare_ones(self):
        fake = self.use()
        for cal in ("yahjair@atouchofblessing.com", "primary", "", None):
            with self.assertRaises(g.CalError):
                g.put_event(cal, "abcde1", {"summary": "x"})
            with self.assertRaises(g.CalError):
                g.remove(cal, "abcde1")
        self.assertEqual(fake.calls, [])

    def test_refuses_an_event_with_attendees(self):
        fake = self.use()
        with self.assertRaises(g.CalError):
            g.put_event(QA, "abcde1", {"summary": "x", "attendees": [{"email": "a@b.co"}]})
        self.assertEqual(fake.calls, [])

    def test_not_configured_is_a_plain_error(self):
        with mock.patch.dict(os.environ, {"GOOGLE_CAL_REFRESH_YAHJAIR": ""}):
            self.assertFalse(g.configured())


class Put(Base):
    def test_new_event_is_one_insert_with_no_updates_sent(self):
        fake = self.use(Reply(200, b'{"id":"abcde1","htmlLink":"https://cal/new"}'))
        self.assertEqual(g.put_event(QA, "abcde1", {"summary": "x"}), "https://cal/new")
        method, url, body = fake.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("sendUpdates=none", url)
        self.assertEqual(body["id"], "abcde1")

    def test_existing_id_replaces_the_event_and_restores_a_deleted_one(self):
        fake = self.use(http_error(409), Reply(200, b'{"id":"abcde1","htmlLink":"https://cal/put"}'))
        self.assertEqual(g.put_event(QA, "abcde1", {"summary": "x"}), "https://cal/put")
        method, url, body = fake.calls[1]
        self.assertEqual(method, "PUT")
        self.assertIn("/events/abcde1", url)
        self.assertIn("sendUpdates=none", url)
        self.assertEqual(body["status"], "confirmed")

    def test_server_error_raises_with_the_code_only(self):
        self.use(http_error(503, b'{"secret":"never shown"}'))
        with self.assertRaises(g.CalError) as ctx:
            g.put_event(QA, "abcde1", {"summary": "x"})
        self.assertEqual(ctx.exception.code, 503)
        self.assertNotIn("never shown", str(ctx.exception))

    def test_a_401_refreshes_once_then_counts_as_auth_failure(self):
        self.use(http_error(401), http_error(401))
        with self.assertRaises(g.CalAuthError):
            g.put_event(QA, "abcde1", {"summary": "x"})


class Remove(Base):
    def test_delete_sends_no_updates(self):
        fake = self.use(Reply(204))
        g.remove(QA, "abcde1")
        self.assertEqual(fake.calls[0][0], "DELETE")
        self.assertIn("sendUpdates=none", fake.calls[0][1])

    def test_already_gone_counts_as_done(self):
        for code in (404, 410):
            self.use(http_error(code))
            g.remove(QA, "abcde1")


if __name__ == "__main__":
    unittest.main()
