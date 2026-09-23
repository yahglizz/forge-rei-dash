"""test_claude_retry.py — wave-2 item 7: Claude transient retry + crm/meta dependency health.

No network (urlopen is faked), no sleeps (backoff zeroed), every forge_heartbeat state file
redirected to a temp dir — the real marcus_state is never written. Never reads *.env.
Run: cd "forge rei" && FORGE_MARCUS=0 python3 test_claude_retry.py
"""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import cost_tracker
import forge_heartbeat as fh
import review_agent

KEY = "test-key-not-real"


def _http(code, msg):
    body = io.BytesIO(json.dumps({"error": {"message": msg}}).encode())
    return urllib.error.HTTPError("https://api.anthropic.com/v1/messages", code, msg, {}, body)


class _Resp:
    def __init__(self, text):
        self._b = json.dumps({"content": [{"type": "text", "text": text}],
                              "stop_reason": "end_turn", "usage": {}}).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake(script):
    """urlopen that plays `script` in order: an Exception is raised, a str is returned."""
    calls = []

    def urlopen(req, timeout=None):
        step = script[len(calls)]
        calls.append(timeout)
        if isinstance(step, Exception):
            raise step
        return _Resp(step)
    return urlopen, calls


class ClaudeRetryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = (fh.STATE, fh.AI_STATE, fh._ai_configured_fps, review_agent._RETRY_BACKOFF)
        self._orig_cost = cost_tracker.STATE
        cost_tracker.STATE = Path(self._tmp.name) / "cost_tracker.json"
        fh.STATE = Path(self._tmp.name) / "heartbeats.json"
        fh.AI_STATE = Path(self._tmp.name) / "ai_health.json"
        fh._ai_configured_fps = lambda: None     # hermetic: never scan real env files
        review_agent._RETRY_BACKOFF = (0, 0)
        self._ok = mock.patch.object(fh, "ai_ok", wraps=fh.ai_ok)
        self._fail = mock.patch.object(fh, "ai_fail", wraps=fh.ai_fail)
        self.ai_ok = self._ok.start()
        self.ai_fail = self._fail.start()

    def tearDown(self):
        self._ok.stop()
        self._fail.stop()
        (fh.STATE, fh.AI_STATE, fh._ai_configured_fps, review_agent._RETRY_BACKOFF) = self._orig
        cost_tracker.STATE = self._orig_cost
        self._tmp.cleanup()

    def _run(self, script):
        urlopen, calls = _fake(script)
        with mock.patch("urllib.request.urlopen", urlopen):
            try:
                return review_agent._claude(KEY, "sys", "hi"), calls
            except Exception as e:  # noqa: BLE001
                return e, calls

    def test_529_529_then_200_returns_text_one_ai_ok(self):
        out, calls = self._run([_http(529, "Overloaded"), _http(529, "Overloaded"), "hello"])
        self.assertEqual(out, "hello")
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.ai_ok.call_count, 1)
        self.assertEqual(self.ai_fail.call_count, 0, "swallowed transients must not count")
        h = fh.ai_health()
        self.assertTrue(h["ok"])
        self.assertEqual(h["failStreak"], 0)
        self.assertEqual(h["callsTotal"], 1)

    def test_credit_400_raises_at_once_and_marks_hard_down(self):
        out, calls = self._run([_http(400, "Your credit balance is too low"), "never"])
        self.assertIsInstance(out, RuntimeError)
        self.assertIn("credit balance", str(out))
        self.assertEqual(len(calls), 1, "a credit 400 must never retry")
        self.assertEqual(self.ai_fail.call_count, 1)
        self.assertEqual(self.ai_ok.call_count, 0)
        h = fh.ai_health()
        self.assertFalse(h["ok"])
        self.assertTrue(h["hard"])
        self.assertEqual(h["kind"], "billing")

    def test_401_never_retries(self):
        out, calls = self._run([_http(401, "invalid x-api-key"), "never"])
        self.assertIsInstance(out, RuntimeError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(fh.ai_health()["kind"], "auth")

    def test_three_529_raises_after_three_calls(self):
        out, calls = self._run([_http(529, "Overloaded")] * 3)
        self.assertIsInstance(out, RuntimeError)
        self.assertIn("529", str(out))
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.ai_fail.call_count, 1, "one logical call = one ai_fail")
        h = fh.ai_health()
        self.assertTrue(h["ok"], "transient exhaustion is not hard-down")
        self.assertEqual(h["failStreak"], 1)

    def test_connection_error_retries_then_succeeds(self):
        out, calls = self._run([urllib.error.URLError(ConnectionResetError("reset")),
                                ConnectionResetError("reset"), "yo"])
        self.assertEqual(out, "yo")
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.ai_ok.call_count, 1)

    def test_timeout_is_not_retried(self):
        # A timeout already cost the full timeout; retrying would triple handler-thread blocking.
        for exc in (TimeoutError("t"), urllib.error.URLError(TimeoutError("t"))):
            out, calls = self._run([exc, "yo"])
            self.assertIsInstance(out, Exception, exc)
            self.assertEqual(len(calls), 1, exc)

    def test_marcus_engine_uses_shared_retry(self):
        src = (Path(__file__).resolve().parent / "marcus_engine.py").read_text()
        self.assertIn("review_agent.claude_urlopen(req, 30)", src)


class DependencyHealthTest(unittest.TestCase):
    def test_crm_from_scout_heartbeat(self):
        import agents_hub
        now = 10_000_000
        fresh = {"lastRun": now - 1000, "interval": 180, "staleMult": 2.0}
        self.assertEqual(agents_hub._crm_health({}, now), (None, None))
        self.assertEqual(agents_hub._crm_health({"scout": dict(fresh)}, now), ("ok", None))
        self.assertEqual(agents_hub._crm_health(
            {"scout": dict(fresh, lastError="claude: overloaded", errStreak=5)}, now)[0], "ok")
        self.assertEqual(agents_hub._crm_health(
            {"scout": dict(fresh, lastError="GHL 503", errStreak=1)}, now), ("degraded", "GHL 503"))
        self.assertEqual(agents_hub._crm_health(
            {"scout": dict(fresh, lastError="GHL 503", errStreak=3)}, now)[0], "down")
        stale = dict(fresh, lastRun=now - 3_600_000)
        self.assertEqual(agents_hub._crm_health({"scout": stale}, now), (None, None))

    def test_meta_from_auth_cache_no_network(self):
        import agents_hub
        import agency_ads
        with mock.patch.dict(os.environ, {"META_ACCESS_TOKEN": ""}):
            self.assertIsNone(agents_hub._meta_health())
        tok = "fake-meta-token"
        with mock.patch.dict(os.environ, {"META_ACCESS_TOKEN": tok}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            self.assertEqual(agents_hub._meta_health(), "ok")
            with mock.patch.dict(agency_ads._AUTH_DEAD, {(hash(tok), None): 9e18}):
                self.assertEqual(agents_hub._meta_health(), "down")


if __name__ == "__main__":
    unittest.main(verbosity=2)
