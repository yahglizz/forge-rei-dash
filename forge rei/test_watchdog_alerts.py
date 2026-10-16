"""test_watchdog_alerts.py — repeating AI-down alert + daily approval-backlog nudge.

Why: B1 sat dead 3+ weeks after ONE "FIX REQUIRED" alert; approvals waited days with no
reminder. connector.py can't be imported here (it boots engines against real state), so the
two tick functions are lifted out of its source with ast and run against the REAL
forge_heartbeat / forge_atomic / owner_actions.merge_and_sort, with Telegram, agent_bus and
forge_ops faked. Clock passed in. State in a temp dir. No network; nothing is sent.
Run: cd "forge rei" && python3 test_watchdog_alerts.py
"""
import ast
import json
import tempfile
import time
import types
import unittest
from pathlib import Path

import forge_atomic
import forge_heartbeat as fh
import owner_actions

HERE = Path(__file__).resolve().parent
_NAMES = {"_AI_REALERT_MS", "_watchdog_ai_tick", "_NUDGE_SOURCES", "_NUDGE_STATE",
          "_NUDGE_HOUR", "_backlog_nudge_tick"}
H = 3600 * 1000            # one hour, ms
T0 = 1_800_000_000_000     # outage start, epoch ms


class FakeTelegram:
    def __init__(self):
        self.sent, self.ok = [], True

    def send(self, text, buttons=None, dedupe_key=None, business=None):
        self.sent.append({"text": text, "key": dedupe_key, "business": business})
        return {"ok": self.ok}

    def configured(self):
        return True

    @staticmethod
    def _esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _load(tmp, tg, loops=True, paused=False, sources=(), archived=()):
    src = (HERE / "connector.py").read_text()
    body = [n for n in ast.parse(src).body
            if (isinstance(n, ast.FunctionDef) and n.name in _NAMES)
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in _NAMES for t in n.targets))]
    got = {n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id for n in body}
    assert got == _NAMES, f"connector.py is missing {_NAMES - got}"
    bus = []
    ns = {
        "time": time, "json": json, "HERE": Path(tmp), "LOOPS_ENABLED": loops,
        "forge_heartbeat": fh, "forge_atomic": forge_atomic, "telegram_io": tg,
        "agent_bus": types.SimpleNamespace(send=lambda *a, **k: bus.append(a)),
        "forge_ops": types.SimpleNamespace(paused=lambda: paused),
        "owner_actions": types.SimpleNamespace(
            SOURCES=list(sources), merge_and_sort=owner_actions.merge_and_sort,
            _is_archived=lambda b: b in archived),
        "MARCUS": None, "SCREENER": None, "DEAL_PREP": None, "DAYCARE_GHL": None,
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), "connector.py", "exec"), ns)
    ns["_bus"] = bus
    return ns


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self._orig = (fh.STATE, fh.AI_STATE, fh._ai_configured_fps)
        fh.STATE = Path(self.tmp) / "heartbeats.json"
        fh.AI_STATE = Path(self.tmp) / "ai_health.json"
        fh._ai_configured_fps = lambda: None   # never read this machine's env files
        self.tg = FakeTelegram()

    def tearDown(self):
        fh.STATE, fh.AI_STATE, fh._ai_configured_fps = self._orig
        self._tmp.cleanup()


class AiWatchdogTest(_Tmp):
    def setUp(self):
        super().setUp()
        fh._ai_save({"hardBy": {"default": {"kind": "billing", "code": 400, "since": T0}},
                     "hard": True, "ok": False, "kind": "billing", "downSince": T0,
                     "reason": "Anthropic credit balance exhausted",
                     "lastError": "HTTP 400: credit balance <too low>"})
        self.ns = _load(self.tmp, self.tg)
        self.tick = self.ns["_watchdog_ai_tick"]

    def test_first_alert_then_quiet_then_still_down_every_24h(self):
        self.tick(T0 + 60_000)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertIn("FIX REQUIRED", self.tg.sent[0]["text"])
        self.assertIn("&lt;too low&gt;", self.tg.sent[0]["text"], "raw error must be HTML-escaped")
        ai = fh.ai_health()
        self.assertTrue(ai["alerted"])
        self.assertEqual(ai["alertedAt"], T0 + 60_000)
        self.assertEqual(len(self.ns["_bus"]), 1)

        for t in (T0 + H, T0 + 60_000 + 24 * H - 1):        # inside 24 h: silent
            self.tick(t)
        self.assertEqual(len(self.tg.sent), 1)

        self.tick(T0 + 60_000 + 24 * H)                      # exactly 24 h after the alert
        self.assertEqual(len(self.tg.sent), 2)
        self.assertIn("STILL DOWN (24 h)", self.tg.sent[1]["text"])
        self.assertNotEqual(self.tg.sent[0]["key"], self.tg.sent[1]["key"],
                            "each reminder needs its own dedupe key")
        self.assertEqual(fh.ai_health()["alertedAt"], T0 + 60_000 + 24 * H)

        self.tick(T0 + 60_000 + 25 * H)
        self.assertEqual(len(self.tg.sent), 2)
        self.tick(T0 + 60_000 + 48 * H)
        self.assertIn("STILL DOWN (48 h)", self.tg.sent[2]["text"])

    def test_telegram_failure_is_retried_next_tick(self):
        self.tg.ok = False
        self.tick(T0 + 60_000)
        self.assertFalse(fh.ai_health()["alerted"])
        self.tg.ok = True
        self.tick(T0 + 120_000)
        self.assertEqual(len(self.tg.sent), 2)
        self.assertTrue(fh.ai_health()["alerted"])

    def test_restart_with_pre_alertedAt_state_starts_clock_without_resend(self):
        d = fh._ai_load()
        d["alerted"] = True                                  # written by the old watchdog
        fh._ai_save(d)
        self.tick(T0 + 5 * H)
        self.assertEqual(self.tg.sent, [])
        self.assertEqual(fh.ai_health()["alertedAt"], T0 + 5 * H)
        self.tick(T0 + 29 * H)
        self.assertIn("STILL DOWN (29 h)", self.tg.sent[0]["text"])

    def test_recovery_message_once_then_clears(self):
        self.tick(T0 + 60_000)
        fh.ai_ok()
        self.tick(T0 + 2 * H)
        self.assertEqual(len(self.tg.sent), 2)
        self.assertIn("recovered", self.tg.sent[1]["text"])
        ai = fh.ai_health()
        self.assertFalse(ai["alerted"])
        self.assertIsNone(ai["alertedAt"])
        self.tick(T0 + 30 * H)
        self.assertEqual(len(self.tg.sent), 2, "healthy + not alerted = silent")


def _at(day, hour, minute=0):
    """Epoch seconds for a LOCAL wall-clock time (mktime is localtime's inverse)."""
    return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))


def _row(iid, biz, age_h, kind="APPROVE"):
    return {"id": iid, "kind": kind, "business": biz, "priority": "normal",
            "ageSec": age_h * 3600 + 100}


class BacklogNudgeTest(_Tmp):
    def setUp(self):
        super().setUp()
        self.calls = []

        def src(name, rows):
            def fn(ctx):
                self.calls.append(name)
                return list(rows)
            return fn
        self.sources = [
            ("marcus_proposals", "wholesale", src("mp", [_row("m1", "wholesale", 2)])),
            ("screenings", "wholesale", src("sc", [_row("s1", "wholesale", 5),
                                                   _row("fix:x", "wholesale", 9, kind="FIX")])),
            ("scout_asap", "wholesale", src("asap", [_row("a1", "wholesale", 50)])),  # not a nudge queue
            ("daycare_replies", "daycare", src("dr", [_row("daycare:c1", "daycare", 3)])),
            ("daycare_inquiries", "daycare", src("di", [_row("daycare:c1", "daycare", 1)])),
            ("agency_approvals", "agency", src("aa", [])),
        ]

    def _tick(self, now, **kw):
        ns = _load(self.tmp, self.tg, sources=self.sources, **kw)
        ns["_backlog_nudge_tick"](now, ctx={})
        return ns

    def _state(self):
        p = Path(self.tmp) / "marcus_state" / "backlog_nudge.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def test_nothing_before_9am(self):
        self._tick(_at(16, 8, 59))
        self.assertEqual(self.tg.sent, [])
        self.assertEqual(self._state(), {})

    def test_after_9am_one_per_business_with_count_and_oldest(self):
        self._tick(_at(16, 9, 5))
        by = {s["business"]: s["text"] for s in self.tg.sent}
        self.assertEqual(set(by), {"wholesale", "daycare"}, "agency has 0 waiting -> silent")
        self.assertIn("2 waiting on you, oldest 5 h", by["wholesale"])   # FIX + scout_asap excluded
        self.assertIn("1 waiting on you, oldest 3 h", by["daycare"])     # one family = one row
        self.assertEqual(self._state(), {"wholesale": "2026-10-16", "daycare": "2026-10-16"})

    def test_once_per_business_per_local_day(self):
        self._tick(_at(16, 9, 5))
        self.calls.clear()
        self._tick(_at(16, 17, 0))
        self.assertEqual(len(self.tg.sent), 2)
        self.assertNotIn("mp", self.calls, "already nudged today -> queue not even read")
        self._tick(_at(17, 9, 30))
        self.assertEqual(len(self.tg.sent), 4)

    def test_telegram_failure_not_marked_and_retried(self):
        self.tg.ok = False
        self._tick(_at(16, 10))
        self.assertEqual(self._state(), {})
        self.tg.ok = True
        self._tick(_at(16, 10, 5))
        self.assertEqual(set(self._state()), {"wholesale", "daycare"})

    def test_skipped_when_clocked_out(self):
        self._tick(_at(16, 10), paused=True)
        self.assertEqual((self.tg.sent, self.calls), ([], []))

    def test_skipped_when_loops_disabled(self):
        self._tick(_at(16, 10), loops=False)
        self.assertEqual((self.tg.sent, self.calls), ([], []))

    def test_archived_business_skipped(self):
        self._tick(_at(16, 10), archived=("wholesale",))
        self.assertEqual([s["business"] for s in self.tg.sent], ["daycare"])


if __name__ == "__main__":
    unittest.main()
