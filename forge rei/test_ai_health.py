"""test_ai_health.py — WP-A: heartbeat truth, AI dependency health, Solomon backoff,
Meta auth cache, phantom-connector alias.

Why: since 2026-08-01 every Anthropic call 400'd ("credit balance is too low") and every
heartbeat stayed GREEN for 51 days, because forge_heartbeat.beat() wraps loops, not Claude
calls. Nobody was alerted. Solomon retried the failed brief every 15 min (errStreak ~4,900)
and hit Meta with an invalid token each time.

No network. Every state file is redirected to a temp dir. Never reads *.env values.
Run: cd "forge rei" && FORGE_MARCUS=0 FORGE_VAULT=$(mktemp -d) python3 test_ai_health.py
"""
import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import forge_heartbeat as fh

HERE = Path(__file__).resolve().parent


class _TempState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = (fh.STATE, fh.AI_STATE)
        fh.STATE = Path(self._tmp.name) / "heartbeats.json"
        fh.AI_STATE = Path(self._tmp.name) / "ai_health.json"

    def tearDown(self):
        fh.STATE, fh.AI_STATE = self._orig
        self._tmp.cleanup()


class HeartbeatTruthTest(_TempState):
    def test_beat_records_last_success_and_errors_total(self):
        fh.beat("scout", 180, "Scout", error=None)
        rec = fh.snapshot()[0]
        first_ok = rec["lastSuccessAt"]
        self.assertIsNotNone(first_ok)
        self.assertEqual(rec["errorsTotal"], 0)

        fh.beat("scout", 180, error="boom 1")
        fh.beat("scout", 180, error="boom 2")
        rec = fh.snapshot()[0]
        self.assertEqual(rec["errStreak"], 2)
        self.assertEqual(rec["errorsTotal"], 2)
        self.assertEqual(rec["lastSuccessAt"], first_ok, "errors must not move lastSuccessAt")
        self.assertEqual(rec["lastError"], "boom 2")

        fh.beat("scout", 180)
        rec = fh.snapshot()[0]
        self.assertEqual(rec["errStreak"], 0, "ok beat resets the streak")
        self.assertEqual(rec["errorsTotal"], 2, "errorsTotal is cumulative")
        self.assertGreaterEqual(rec["lastSuccessAt"], first_ok)

    def test_last_error_never_carries_a_secret(self):
        fh.beat("x", 60, error="auth failed x-api-key: sk-ant-api03-SECRETSECRET rest")
        err = fh.snapshot()[0]["lastError"]
        self.assertNotIn("SECRETSECRET", err)
        self.assertIn("[redacted]", err)
        # the lastError is on disk too — the file must be clean as well
        self.assertNotIn("SECRETSECRET", fh.STATE.read_text())


class AiHealthTest(_TempState):
    CREDIT = "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing"

    def test_fresh_state_is_ok(self):
        ai = fh.ai_health()
        self.assertTrue(ai["ok"])
        self.assertFalse(ai["hard"])
        for k in ("ok", "lastOkAt", "lastError", "downSince", "reason"):
            self.assertIn(k, ai, "health JSON shape: " + k)

    def test_credit_400_is_hard_down_until_a_success(self):
        fh.ai_fail(400, self.CREDIT)
        ai = fh.ai_health()
        self.assertFalse(ai["ok"])
        self.assertTrue(ai["hard"])
        self.assertEqual(ai["kind"], "billing")
        self.assertIn("credit", ai["reason"].lower())
        self.assertIsNotNone(ai["downSince"])
        down_since = ai["downSince"]

        fh.ai_fail(429, "rate limited")          # transient DURING the outage: still down
        ai = fh.ai_health()
        self.assertFalse(ai["ok"])
        self.assertEqual(ai["downSince"], down_since, "downSince is the FIRST failure")
        self.assertEqual(ai["failStreak"], 2)
        self.assertEqual(ai["errorsTotal"], 2)

        fh.ai_ok()                               # recovery clears it
        ai = fh.ai_health()
        self.assertTrue(ai["ok"])
        self.assertFalse(ai["hard"])
        self.assertIsNone(ai["downSince"])
        self.assertIsNone(ai["reason"])
        self.assertEqual(ai["failStreak"], 0)
        self.assertIsNotNone(ai["lastOkAt"])
        self.assertEqual(ai["errorsTotal"], 2, "history survives recovery")

    def test_auth_401_403_hard_transient_not(self):
        self.assertEqual(fh.ai_classify(401, "invalid x-api-key"), ("auth", True))
        self.assertEqual(fh.ai_classify(403, "permission_error"), ("auth", True))
        self.assertEqual(fh.ai_classify(400, "max_tokens too large"), ("transient", False))
        self.assertEqual(fh.ai_classify(429, "rate"), ("transient", False))
        self.assertEqual(fh.ai_classify(529, "overloaded"), ("transient", False))
        self.assertEqual(fh.ai_classify(None, "timed out"), ("transient", False))

        fh.ai_fail(None, "<urlopen error timed out>")
        ai = fh.ai_health()
        self.assertTrue(ai["ok"], "a timeout is not an outage")
        self.assertEqual(ai["failStreak"], 1)
        self.assertIn("timed out", ai["lastError"])

    def test_alerted_flag_persists_and_survives_recovery_until_cleared(self):
        fh.ai_fail(401, "bad key")
        fh.ai_alerted(True)
        self.assertTrue(fh.ai_health()["alerted"])
        fh.ai_ok()
        self.assertTrue(fh.ai_health()["alerted"], "watchdog clears it, not ai_ok()")
        fh.ai_alerted(False)
        self.assertFalse(fh.ai_health()["alerted"])
        self.assertTrue(json.loads(fh.AI_STATE.read_text())["ok"])

    def test_hard_down_is_tracked_per_credential(self):
        """Fable review: one revoked key among healthy ones must not be masked, and a
        healthy key's success must not clear ANOTHER key's outage (no flip-flop)."""
        fh.ai_fail(400, self.CREDIT, key="unit-key-A")
        fh.ai_ok("unit-key-B")                          # B fine → fleet still hard (A)
        ai = fh.ai_health()
        self.assertTrue(ai["hard"])
        self.assertFalse(ai["ok"])
        self.assertEqual(len(ai["hardBy"]), 1)
        self.assertIn("1 key down", ai["reason"])
        self.assertNotIn("unit-key", json.dumps(ai), "fingerprints only — never the key")
        first_since = ai["downSince"]

        fh.ai_fail(401, "invalid x-api-key", key="unit-key-B")
        ai = fh.ai_health()
        self.assertEqual(len(ai["hardBy"]), 2)
        self.assertIn("2 keys down", ai["reason"])
        self.assertEqual(ai["kind"], "billing", "billing (account-wide) outranks auth")
        self.assertEqual(ai["downSince"], first_since, "downSince = the EARLIEST key")

        fh.ai_ok("unit-key-B")                          # B recovers — A is still dead
        fh.ai_ok("unit-key-B")
        ai = fh.ai_health()
        self.assertTrue(ai["hard"], "no flip-flop: A never succeeded")
        self.assertEqual(len(ai["hardBy"]), 1)
        self.assertIn("1 key down", ai["reason"])

        fh.ai_ok("unit-key-A")                          # A recovers → fleet ok
        ai = fh.ai_health()
        self.assertTrue(ai["ok"])
        self.assertEqual(ai["hardBy"], {})
        self.assertIsNone(ai["downSince"])

    def test_keyless_calls_share_the_default_fingerprint(self):
        fh.ai_fail(401, "bad key")                      # no key → "default"
        self.assertIn("default", fh.ai_health()["hardBy"])
        fh.ai_ok()
        self.assertTrue(fh.ai_health()["ok"])

    def test_pre_hardby_state_file_migrates(self):
        """A box mid-outage on the old single-flag file must not read green after upgrade."""
        fh.AI_STATE.write_text(json.dumps({"ok": False, "hard": True, "kind": "billing",
                                           "downSince": 123, "reason": "old"}))
        fh.ai_fail(429, "rate limited")                 # any write migrates it
        ai = fh.ai_health()
        self.assertTrue(ai["hard"])
        self.assertEqual(ai["downSince"], 123)
        self.assertIn("default", ai["hardBy"])
        fh.ai_ok()
        self.assertTrue(fh.ai_health()["ok"])

    def test_ai_calls_never_raise(self):
        fh.AI_STATE = Path(self._tmp.name) / "no-such-dir" / "x" / "ai.json"
        fh.ai_fail(400, self.CREDIT)             # write fails → swallowed
        fh.ai_ok()
        fh.ai_alerted(True)
        self.assertTrue(fh.ai_health()["ok"])   # degrades to the safe default


class _FakeResp:
    def __init__(self, body):
        self._b = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


class ReviewAgentHookTest(_TempState):
    """review_agent._claude is THE shared choke point (47 call sites). No network."""

    def _http_error(self, code, message):
        body = json.dumps({"type": "error", "error": {"type": "x", "message": message}}).encode()
        return urllib.error.HTTPError("https://api.anthropic.com/v1/messages", code,
                                      "Bad Request", {}, io.BytesIO(body))

    def test_credit_400_marks_hard_down_and_still_raises(self):
        import review_agent
        err = self._http_error(400, AiHealthTest.CREDIT)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as cm:
                review_agent._claude("k", "sys", "user")
        self.assertIn("credit balance", str(cm.exception))
        ai = fh.ai_health()
        self.assertFalse(ai["ok"])
        self.assertEqual(ai["kind"], "billing")

    def test_network_error_is_transient_and_reraised(self):
        import review_agent
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("timed out")):
            with self.assertRaises(urllib.error.URLError):
                review_agent._claude("k", "sys", "user")
        ai = fh.ai_health()
        self.assertTrue(ai["ok"])
        self.assertEqual(ai["failStreak"], 1)

    def test_success_records_ok_and_clears_outage(self):
        import review_agent
        fh.ai_fail(400, AiHealthTest.CREDIT, key="k")   # same credential _claude uses below
        resp = _FakeResp({"content": [{"type": "text", "text": "hello"}],
                          "stop_reason": "end_turn", "usage": {}})
        with mock.patch("urllib.request.urlopen", return_value=resp), \
             mock.patch("cost_tracker.record_anthropic"):
            out = review_agent._claude("k", "sys", "user")
        self.assertEqual(out, "hello")
        self.assertTrue(fh.ai_health()["ok"])

    def test_marcus_direct_call_is_hooked(self):
        """marcus_engine._ai_draft bypasses review_agent — it must stamp the same signal
        on the HTTPError + network branches and ai_ok() on success."""
        src = (HERE / "marcus_engine.py").read_text()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_ai_draft")
        seg = ast.get_source_segment(src, fn)
        self.assertIn("forge_heartbeat.ai_fail(e.code, msg, self.anthropic_key)", seg)
        self.assertIn("forge_heartbeat.ai_fail(None, e, self.anthropic_key)", seg)
        self.assertIn("forge_heartbeat.ai_ok(self.anthropic_key)", seg)

    def test_review_agent_passes_its_key(self):
        """Per-credential hardBy: a 400 through review_agent must land on THAT key's
        fingerprint, not "default"."""
        import review_agent
        err = self._http_error(400, AiHealthTest.CREDIT)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError):
                review_agent._claude("unit-key-A", "sys", "user")
        hb = fh.ai_health()["hardBy"]
        self.assertEqual(list(hb), [fh._ai_fp("unit-key-A")])
        self.assertNotIn("default", hb)


class SolomonBackoffTest(unittest.TestCase):
    def setUp(self):
        import daycare_director
        self.dd = daycare_director
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = (daycare_director.STATE, fh.STATE)
        daycare_director.STATE = Path(self._tmp.name) / "solomon.json"
        fh.STATE = Path(self._tmp.name) / "heartbeats.json"   # the loop's real beats land here

    def tearDown(self):
        self.dd.STATE, fh.STATE = self._orig
        self._tmp.cleanup()

    def test_schedule_15m_doubling_capped_6h(self):
        d = self.dd.SolomonEngine.backoff_delay_s
        self.assertEqual([d(n) for n in range(0, 8)],
                         [0, 900, 1800, 3600, 7200, 14400, 21600, 21600])

    def test_failed_brief_backs_off_and_success_resets(self):
        eng = self.dd.SolomonEngine()
        now = 1_700_000_000_000
        self.assertTrue(eng._brief_due(now), "never briefed → due")

        eng._note_brief_result(False, now)
        self.assertEqual(eng.fail_streak, 1)
        self.assertFalse(eng._brief_due(now + 14 * 60 * 1000), "15 min backoff")
        self.assertTrue(eng._brief_due(now + 15 * 60 * 1000))

        eng._note_brief_result(False, now + 15 * 60 * 1000)
        self.assertEqual(eng.fail_streak, 2)
        t2 = now + 15 * 60 * 1000
        self.assertFalse(eng._brief_due(t2 + 29 * 60 * 1000), "30 min backoff")
        self.assertTrue(eng._brief_due(t2 + 30 * 60 * 1000))

        for _ in range(10):                      # runaway streak stays capped at 6 h
            eng._note_brief_result(False, t2)
        self.assertFalse(eng._brief_due(t2 + 5 * 3600 * 1000))
        self.assertTrue(eng._brief_due(t2 + 6 * 3600 * 1000))

        # persisted → a restart keeps the schedule instead of hammering again
        again = self.dd.SolomonEngine()
        self.assertEqual(again.fail_streak, eng.fail_streak)
        self.assertEqual(again.last_attempt_at, t2)

        eng._note_brief_result(True, t2)
        self.assertEqual(eng.fail_streak, 0)
        eng.last_brief_at = t2
        self.assertFalse(eng._brief_due(t2 + 1000), "fresh brief → not due (24h cadence)")
        self.assertTrue(eng._brief_due(t2 + self.dd.BRIEF_EVERY_MS))

    class _Stop(BaseException):          # not Exception → escapes the loop's except
        pass

    def _run_loop(self, eng, ticks, build_brief):
        """Drive run_forever for `ticks` iterations offline: no key file, no Supabase
        login (autoadmin_session → None even with FORGE_DAYCARE_AUTOADMIN=1 in the
        shell), no learn, real forge_heartbeat beats into the temp store."""
        import daycare_supabase
        with mock.patch.object(self.dd, "_solomon_key", return_value="k"), \
             mock.patch.object(self.dd.forge_ops, "paused", return_value=False), \
             mock.patch.object(daycare_supabase.BRIDGE, "autoadmin_session", return_value=None), \
             mock.patch.object(eng, "build_brief", side_effect=build_brief) as bb, \
             mock.patch.object(eng, "_maybe_learn"), \
             mock.patch.object(self.dd.time, "sleep",
                               side_effect=[None] * (ticks - 1) + [self._Stop()]):
            with self.assertRaises(self._Stop):
                eng.run_forever()
        return bb

    def test_loop_counts_an_exception_as_a_fail(self):
        """run_forever: build_brief raising must still advance the backoff state."""
        eng = self.dd.SolomonEngine()
        self._run_loop(eng, 1, RuntimeError("no credits"))
        self.assertEqual(eng.fail_streak, 1)
        self.assertIsNotNone(eng.last_attempt_at)
        self.assertIn("no credits", eng.last_error)
        self.assertEqual(fh.snapshot()[0]["errorsTotal"], 1, "the attempt itself counts")

    def test_backoff_ticks_do_not_inflate_heartbeat_errors(self):
        """Codex review: inside a backoff window no brief is attempted, yet the loop kept
        beating with the STALE last_error → errStreak/errorsTotal grew ~96/day."""
        eng = self.dd.SolomonEngine()
        eng._note_brief_result(False, int(self.dd.time.time() * 1000))   # 15 min window opens
        eng.last_error = "brief: no credits"
        bb = self._run_loop(eng, 2, RuntimeError("must not be called"))
        bb.assert_not_called()
        rec = fh.snapshot()[0]
        self.assertEqual(rec["loop"], "solomon")
        self.assertEqual(rec["beats"], 2, "the loop still beats (not stale)")
        self.assertEqual(rec["errorsTotal"], 0, "no attempt → no error counted")
        self.assertEqual(rec["errStreak"], 0)
        self.assertEqual(eng.fail_streak, 1, "backoff state untouched")

    def test_status_exposes_backoff_and_next_brief(self):
        eng = self.dd.SolomonEngine()
        self.assertIsNone(eng.next_brief_at(), "never briefed/attempted → due now")
        t = 1_700_000_000_000
        eng._note_brief_result(False, t)
        eng._note_brief_result(False, t)                 # streak 2 → 30 min backoff
        self.assertEqual(eng.next_brief_at(), t + 30 * 60 * 1000)
        eng._note_brief_result(True, t)
        eng.last_brief_at = t
        self.assertEqual(eng.next_brief_at(), t + self.dd.BRIEF_EVERY_MS, "cadence wins")
        st = eng.status()
        self.assertEqual(st["failStreak"], 0)
        self.assertEqual(st["lastAttemptAt"], t)
        self.assertEqual(st["nextBriefAt"], t + self.dd.BRIEF_EVERY_MS)


class MetaAuthCacheTest(unittest.TestCase):
    """agency_ads.analytics: a rejected token is remembered for 6h — no Meta call per tick."""

    def setUp(self):
        import agency_ads
        self.ads = agency_ads
        agency_ads._AUTH_DEAD.clear()
        self._env = mock.patch.dict(os.environ, {"META_ACCESS_TOKEN": "unit-test-token-not-real",
                                                 "META_AD_ACCOUNT_MAP": ""})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.ads._AUTH_DEAD.clear()

    def test_invalid_token_is_cached_and_connection_reports_it(self):
        calls = []

        def dead(token, acct, days):
            calls.append(acct)
            raise RuntimeError("Meta 400: Invalid OAuth access token - Cannot parse access token")

        with mock.patch.object(self.ads, "_live_analytics", side_effect=dead), \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(self.ads.connection()["source"], "live")
            out1 = self.ads.analytics(client="daycare")
            out2 = self.ads.analytics(client="daycare")
            out3 = self.ads.analytics(client="daycare")
        self.assertEqual(len(calls), 1, "Meta must be hit ONCE, then cached for 6h")
        self.assertEqual(out1["source"], "mock")
        self.assertEqual(out3["source"], "mock")
        conn = self.ads.connection()
        self.assertFalse(conn["connected"])
        self.assertEqual(conn["source"], "auth_error")
        self.assertTrue(conn["hasToken"])
        # Solomon's gather reads exactly this and must get the "not connected" err
        import daycare_director
        eng = daycare_director.SolomonEngine.__new__(daycare_director.SolomonEngine)
        with mock.patch.object(self.ads, "_live_analytics", side_effect=dead), \
             mock.patch("daycare_growth._daycare_creds",
                        return_value={"META_ACCESS_TOKEN": "unit-test-token-not-real"}):
            data, err = eng._gather_campaign()
        self.assertFalse(data["connected"])
        self.assertEqual(data["source"], "auth_error")
        # Fable review: the err must name the REJECTION — not "add META_AD_ACCOUNT_MAP".
        self.assertIn("rejected", err.lower())
        self.assertNotIn("META_AD_ACCOUNT_MAP", err)
        self.assertEqual(len(calls), 1, "the gather must not re-hit Meta either")

    def test_transient_error_is_not_cached(self):
        calls = []

        def flaky(token, acct, days):
            calls.append(acct)
            raise RuntimeError("Meta 500: internal")

        with mock.patch.object(self.ads, "_live_analytics", side_effect=flaky), \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            self.ads.analytics(client="daycare")
            self.ads.analytics(client="daycare")
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.ads.connection()["source"], "live")

    def test_replaced_token_is_retried_immediately(self):
        self.ads._AUTH_DEAD[(hash("unit-test-token-not-real"), None)] = 9e12
        self.assertTrue(self.ads._auth_dead("unit-test-token-not-real"))
        self.assertTrue(self.ads._auth_dead("unit-test-token-not-real", "act_other"))
        self.assertFalse(self.ads._auth_dead("a-new-token"))

    def test_account_403_does_not_kill_the_whole_token(self):
        # Codex review: a 403 on ONE ad account must not black out every account.
        self.assertEqual(self.ads._auth_scope("Meta 403: no permission", "act_1"), "act_1")
        self.assertEqual(self.ads._auth_scope("Meta 400: Cannot parse access token", "act_1"), "token")
        self.assertIsNone(self.ads._auth_scope("Meta 500: internal", "act_1"))
        self.ads._AUTH_DEAD[(hash("unit-test-token-not-real"), "act_1001")] = 9e12
        self.assertFalse(self.ads._auth_dead("unit-test-token-not-real"))
        self.assertTrue(self.ads._auth_dead("unit-test-token-not-real", "act_1001"))
        self.assertFalse(self.ads._auth_dead("unit-test-token-not-real", "act_other"))
        self.assertEqual(self.ads.connection()["source"], "live")


class PhantomConnectorTest(unittest.TestCase):
    ALIAS = 'sys.modules.setdefault("connector", sys.modules[__name__])'

    def test_alias_sits_before_every_project_import(self):
        src = (HERE / "connector.py").read_text()
        tree = ast.parse(src)
        local = {p.stem for p in HERE.glob("*.py")} - {"connector"}
        alias_line = next(n.lineno for n in tree.body if isinstance(n, ast.If)
                          and self.ALIAS in ast.get_source_segment(src, n))
        first_local = min(n.lineno for n in ast.walk(tree)
                          if isinstance(n, ast.Import)
                          and any(a.name.split(".")[0] in local for a in n.names))
        self.assertLess(alias_line, first_local,
                        "alias must run before any module that could `import connector`")
        # main() is still guarded — the alias did not replace the entry point
        self.assertIn('if __name__ == "__main__":\n    main()', src)

    def test_pattern_makes_import_return_the_running_main(self):
        """Behavioral: with the alias, `import <main module>` from a helper yields the very
        object running as __main__; without it, a phantom second copy loads."""
        helper = ("def probe():\n"
                  "    import sys, phantom_main\n"
                  "    return 'same' if phantom_main is sys.modules['__main__'] else 'phantom'\n")
        main_tpl = ("import sys\n"
                    "{alias}"
                    "import helper\n"
                    "if __name__ == '__main__':\n"
                    "    print(helper.probe())\n")
        for alias, want in (("if __name__ == '__main__':\n"
                             "    sys.modules.setdefault('phantom_main', sys.modules[__name__])\n",
                             "same"), ("", "phantom")):
            with tempfile.TemporaryDirectory() as td:
                (Path(td) / "helper.py").write_text(helper)
                (Path(td) / "phantom_main.py").write_text(main_tpl.format(alias=alias))
                out = subprocess.run([sys.executable, "phantom_main.py"], cwd=td,
                                     capture_output=True, text=True, timeout=30)
                self.assertEqual(out.stdout.strip(), want, out.stderr)

    def test_no_other_module_imports_connector(self):
        """Only the two known lazy lookups (plus tests) import connector — anything new
        needs the same alias guarantee."""
        # Per-LINE statement match — a substring check also trips on comments/docstrings
        # that merely mention "import connector" (Codex review).
        stmt = re.compile(r"^\s*import connector\b", re.M)
        offenders = []
        for p in HERE.glob("*.py"):
            if p.name.startswith("test_") or p.name == "connector.py":
                continue
            if stmt.search(p.read_text()):
                offenders.append(p.name)
        self.assertEqual(sorted(offenders), ["agents_hub.py", "pixel_office.py"])


class SystemHealthRouteTest(unittest.TestCase):
    """connector can't be imported here (it boots engines against real state) — assert the
    route's contract at the source level."""

    def test_health_route_exposes_ai_and_gates_ok(self):
        src = (HERE / "connector.py").read_text()
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "api_system_health")
        seg = ast.get_source_segment(src, fn)
        self.assertIn("forge_heartbeat.ai_health()", seg)
        self.assertIn('"ai": ai', seg)
        self.assertIn('"reason":', seg)
        self.assertIn('bool(ai.get("ok"))', seg)
        wd = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_watchdog_forever")
        wseg = ast.get_source_segment(src, wd)
        self.assertIn("FIX REQUIRED: Anthropic credits/auth", wseg)
        self.assertIn("forge_heartbeat.ai_alerted(True)", wseg)
        self.assertIn("forge_heartbeat.ai_alerted(False)", wseg)
        # The AI alert runs ABOVE the clocked-out `continue`: a dead key is fix-required
        # whether or not the crew is paused (transition-based, so it can't spam).
        self.assertLess(wseg.index("FIX REQUIRED: Anthropic"), wseg.index("forge_ops.paused()"))


if __name__ == "__main__":
    unittest.main()
