"""solomon_orchestrator.py — Solomon's wake-up timer (spec 2026-10-18, Phase 3). OPERATOR OPT-IN, DEFAULT OFF.

WHAT A ROUND IS IN THIS PHASE: ZERO-CLAUDE DETECTION ONLY.
  daycare_watches.run_round() reads the daycare's own routes, updates the Command Board
  (marcus_state/daycare_board.json) and — only when something is NEW or NEWLY URGENT — this module
  sends ONE short digest to the DAYCARE Telegram chat. A round runs NO LLM tool loop, makes NO Claude
  call, and writes NOTHING outward: no text, email, invoice, tag, ad change, login or pipeline move.
  The safe self-fixes (AUTO tier: tags, notes, tasks, desk re-runs) happen ONLY through the existing
  dashboard-chat tier when the owner talks to Solomon (CLAUDE.md §2 "Dashboard chat AUTO tier").
  A Claude-driven round (the "worker" in the spec) is a later phase with its own spec.

Thread `solomon_orchestrator` — the connector starts it only when LOOPS_ENABLED (FORGE_MARCUS=1, the
box) AND FORGE_SOLOMON_ORCH=1; otherwise it calls forge_heartbeat.retire("solomon_orchestrator").
Wakes every POLL_SEC (heartbeat each wake). A round is due every FORGE_SOLOMON_ORCH_EVERY_MIN (120)
from 07:00 to 18:59 ET, plus one round at 20:00 ET. Skipped (nothing read, nothing sent) when:
forge_ops clock-out · cost_tracker.over_ceiling("solomon") (one HQ Telegram note per ET day) · the AI
circuit is open (review_agent.ai_blocked — kept so the later Claude round inherits it) · a round is
already running (manual "Run round" included). Bills to `solomon` (cost_tracker.THREAD_ALIAS).
Heartbeat `solomon_orchestrator` "Solomon · Orchestrator" (on his Agent Control Center row).
Kill: FORGE_SOLOMON_ORCH=0 + restart · forge_ops clock-out · snooze an item · the daily cost ceiling.
State: marcus_state/solomon_orchestrator.json. Test: python3 test_solomon_orchestrator.py
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import forge_atomic
import forge_heartbeat
import forge_ops

HERE = Path(__file__).resolve().parent
STATE = forge_atomic.guard_state_path(HERE / "marcus_state" / "solomon_orchestrator.json")
LOOP, LABEL = "solomon_orchestrator", "Solomon · Orchestrator"
ET = ZoneInfo("America/New_York")
POLL_SEC = 300
DAY_START, DAY_END, EVENING = 7, 19, 20          # rounds 07:00–18:59 ET + one at 20:00 ET


def enabled():
    return os.environ.get("FORGE_SOLOMON_ORCH", "0") == "1"


def every_min():
    try:
        return max(15, int(os.environ.get("FORGE_SOLOMON_ORCH_EVERY_MIN") or 120))
    except ValueError:
        return 120


def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def due(now, last):
    """Business hours: every every_min(); evening: once after 20:00 ET; never overnight."""
    t = datetime.fromtimestamp(now, ET)
    if DAY_START <= t.hour < DAY_END:
        return last is None or now - last >= every_min() * 60
    if t.hour == EVENING:
        return last is None or last < t.replace(minute=0, second=0, microsecond=0).timestamp()
    return False


def _skip_reason():
    if forge_ops.paused():
        return "clocked out"
    try:
        import cost_tracker
        if cost_tracker.over_ceiling("solomon"):
            return "cost ceiling"
    except Exception:  # noqa: BLE001
        pass
    try:
        import review_agent
        if review_agent.ai_blocked():
            return "AI circuit open"
    except Exception:  # noqa: BLE001
        pass
    return None


def digest_due(res, st):
    """Ping only when something is new, or an urgent item the last digest did not show."""
    shown = set((st.get("digest") or {}).get("urgent") or [])
    return bool(res.get("new")) or bool({u.get("id") for u in res.get("urgent") or []} - shown)


def _send_daycare(text):
    import telegram_io
    return telegram_io.send_biz("daycare", text)


def _send_hq(text):
    import telegram_io
    return telegram_io.send(text)


def tick(now=None, round_fn=None, send=None, hq=None):
    """One wake-up. -> the round result, or {skipped: why}. Never raises past the loop."""
    now = now or time.time()
    st = _load()
    if not due(now, st.get("lastRoundAt")):
        return {"skipped": "not due"}
    why = _skip_reason()
    if why:
        st["lastSkip"] = {"at": int(now * 1000), "why": why}
        day = datetime.fromtimestamp(now, ET).date().isoformat()
        if why == "cost ceiling" and st.get("ceilingNoteDay") != day:
            try:
                (hq or _send_hq)("🏛️ Solomon · Orchestrator skipped his board rounds today — Solomon's Claude spend "
                                 "is at the daily ceiling (FORGE_AGENT_MAX_USD). Rounds resume tomorrow.")
            except Exception:  # noqa: BLE001
                pass
            st["ceilingNoteDay"] = day
        _save(st)
        return {"skipped": why}
    if round_fn is None:
        import daycare_watches
        round_fn = daycare_watches.run_round
    res = round_fn() or {}
    if res.get("skipped"):
        return res
    st.update(lastRoundAt=now, lastLine=res.get("line"), lastSkip=None)
    if digest_due(res, st):
        import daycare_board
        try:
            out = (send or _send_daycare)(daycare_board.board_digest_text(res))
        except Exception as e:  # noqa: BLE001
            out = {"error": type(e).__name__}
        if isinstance(out, dict) and out.get("ok"):
            st["digest"] = {"at": int(now * 1000), "urgent": [u.get("id") for u in res.get("urgent") or []]}
    _save(st)
    return res


def status():
    st = _load()
    return {"enabled": enabled(), "everyMin": every_min(), "lastRoundAt": st.get("lastRoundAt"),
            "lastLine": st.get("lastLine"), "lastSkip": st.get("lastSkip"), "lastDigestAt": (st.get("digest") or {}).get("at")}


def run_forever():
    """Thread `solomon_orchestrator` (box only, FORGE_SOLOMON_ORCH=1). Beats every wake."""
    while True:
        err = None
        try:
            tick()
        except Exception as e:  # noqa: BLE001
            err = f"tick: {type(e).__name__}"
        # stale after 4 wakes (20 min): a slow round (GHL scan, Gmail paging) must not read as a dead loop
        forge_heartbeat.beat(LOOP, POLL_SEC, LABEL, error=err, stale_mult=4.0)
        time.sleep(POLL_SEC)
