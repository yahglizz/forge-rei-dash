"""forge_ops.py — the master time clock for the agent fleet (clock-out / clock-in).

One flag the operator flips when HE is working the leads himself, so the AI agents stand
down ("clock out") instead of acting in parallel — then "clock in" again when he steps
away, and they get back to work.

Paused == clocked out. While clocked out:
  - Scout stops sweeping / scoring / tagging / pipeline (poll_once returns early).
  - Marcus auto-screening + Atlas auto-prep stop (they fire off Scout's new scores, which
    no longer happen; Atlas's own sweep also returns early).
  - The follow-up engine + Autopilot stop drafting/sending.
  - The contract (DocuSign) poll pauses.
The operator's OWN actions always work — taps, /text, /screen, single /prep, dashboard
buttons. Clock-out freezes AUTONOMOUS work only, never the operator.

State: marcus_state/ops_clock.json {paused, since, shifts[:50]}.
"""
import json
import threading
import time
from pathlib import Path

import agent_bus
import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "ops_clock.json"
_LOCK = threading.Lock()

# The crew that clocks out together (display only).
CREW = ("Scout", "Marcus", "Atlas")


def _load():
    try:
        d = json.loads(STATE.read_text())
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("paused", False)
    d.setdefault("since", None)
    d.setdefault("shifts", [])
    return d


def _save(d):
    d["shifts"] = (d.get("shifts") or [])[:50]
    forge_atomic.atomic_write_json(STATE, d)


def paused():
    """The hot path every autonomous loop checks. Never raises (defaults to running)."""
    try:
        with _LOCK:
            return bool(_load().get("paused"))
    except Exception:
        return False


def status():
    with _LOCK:
        d = _load()
        return {
            "paused": bool(d.get("paused")),
            "since": d.get("since"),
            "crew": list(CREW),
            "shifts": (d.get("shifts") or [])[:10],
        }


def set_paused(on):
    """Clock the crew out (on=True) or in (on=False). Idempotent; logs each shift change
    and broadcasts to the bus so the Command Center + Telegram see it."""
    on = bool(on)
    with _LOCK:
        d = _load()
        was = bool(d.get("paused"))
        d["paused"] = on
        d["since"] = int(time.time() * 1000)
        if was != on:
            d.setdefault("shifts", []).insert(0, {
                "ts": d["since"],
                "event": "clock_out" if on else "clock_in",
            })
        _save(d)
    try:        # best-effort broadcast (Command Center bus feed + any notifier)
        if on:
            msg = ("🕐 Agents CLOCKED OUT — " + ", ".join(CREW) + " stood down. "
                   "You've got the wheel; nothing autonomous runs until you clock them "
                   "back in. Your own taps still work.")
        else:
            msg = ("🟢 Agents CLOCKED IN — " + ", ".join(CREW) + " back to work: "
                   "sweeping, scoring, tagging, screening, prepping.")
        agent_bus.send("ops", "all", "alert", msg, {"type": "ops_clock", "paused": on})
    except Exception:
        pass
    return status()
