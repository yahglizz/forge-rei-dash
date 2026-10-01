"""test_ai_breaker.py — AI circuit breaker (review_agent.claude_urlopen / ai_blocked).

No network (urlopen faked), temp health state, never reads *.env.
Run: cd "forge rei" && FORGE_MARCUS=0 python3 test_ai_breaker.py
"""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import cost_tracker
import forge_heartbeat as fh
import review_agent

KEY, KEY2 = "test-key-one", "test-key-two"


def _credit_400():
    body = io.BytesIO(json.dumps({"error": {"message": "Your credit balance is too low"}}).encode())
    return urllib.error.HTTPError("https://api.anthropic.com/v1/messages", 400, "x", {}, body)


class _Resp:
    def read(self):
        return json.dumps({"content": [{"type": "text", "text": "ok"}],
                           "stop_reason": "end_turn", "usage": {}}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class BreakerTest(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._o = (fh.STATE, fh.AI_STATE, fh._ai_configured_fps, cost_tracker.STATE,
                   review_agent._RETRY_BACKOFF)
        fh.STATE, fh.AI_STATE = Path(self.t.name) / "hb.json", Path(self.t.name) / "ai.json"
        cost_tracker.STATE = Path(self.t.name) / "cost.json"
        fh._ai_configured_fps = lambda: None
        review_agent._RETRY_BACKOFF = (0, 0)
        review_agent._PROBE_AT.clear()
        self.calls = []

    def tearDown(self):
        (fh.STATE, fh.AI_STATE, fh._ai_configured_fps, cost_tracker.STATE,
         review_agent._RETRY_BACKOFF) = self._o
        review_agent._PROBE_AT.clear()
        self.t.cleanup()

    def _urlopen(self, script):
        def f(req, timeout=None):
            self.calls.append(1)
            step = script.pop(0)
            if isinstance(step, Exception):
                raise step
            return step
        return f

    def _ask(self, script, key=KEY):
        with mock.patch("urllib.request.urlopen", self._urlopen(script)):
            try:
                return review_agent._claude(key, "s", "u")
            except Exception as e:  # noqa: BLE001
                return e

    def test_open_after_credit_failure_fails_fast_without_network(self):
        self._ask([_credit_400()])                      # first call hits Anthropic, marks hard-down
        self.assertEqual(len(self.calls), 1)
        before = fh.ai_health()["failStreak"]
        for _ in range(5):
            out = self._ask([_Resp()])                  # would succeed — must never be reached
            self.assertIsInstance(out, RuntimeError)
            self.assertIn("circuit open", str(out))
            self.assertIn("credit balance", str(out))
        self.assertEqual(len(self.calls), 1, "no network while the breaker is open")
        self.assertEqual(fh.ai_health()["failStreak"], before, "fast-fails are not new failures")
        self.assertTrue(review_agent.ai_blocked(KEY))

    def test_probe_reopens_and_success_closes_breaker(self):
        self._ask([_credit_400()])
        review_agent._PROBE_AT.clear()                  # probe window elapsed
        self.assertFalse(review_agent.ai_blocked(KEY), "loops may wake up to be the probe")
        self.assertEqual(self._ask([_Resp()]), "ok")    # credits are back: probe succeeds
        self.assertFalse(fh.ai_health()["hard"])
        self.assertEqual(self._ask([_Resp()]), "ok")    # closed: normal calls flow
        self.assertFalse(review_agent.ai_blocked(KEY))

    def test_failed_probe_keeps_it_open(self):
        self._ask([_credit_400()])
        review_agent._PROBE_AT.clear()
        self._ask([_credit_400()])                      # probe fails again
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(review_agent.ai_blocked(KEY))
        self.assertIsInstance(self._ask([_Resp()]), RuntimeError)
        self.assertEqual(len(self.calls), 2)

    def test_replacement_key_is_never_blocked(self):
        self._ask([_credit_400()], key=KEY)
        self.assertEqual(self._ask([_Resp()], key=KEY2), "ok")

    def test_transient_errors_do_not_open_it(self):
        e = urllib.error.HTTPError("u", 529, "Overloaded", {}, io.BytesIO(b'{"error":{"message":"Overloaded"}}'))
        self._ask([e, e, e])
        self.assertFalse(review_agent.ai_blocked(KEY))

    def test_zero_probe_sec_disables(self):
        self._ask([_credit_400()])
        with mock.patch.dict("os.environ", {"FORGE_AI_PROBE_SEC": "0"}):
            self.assertEqual(self._ask([_Resp()]), "ok")


if __name__ == "__main__":
    unittest.main()
