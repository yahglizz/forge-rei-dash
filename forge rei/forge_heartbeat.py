"""forge_heartbeat.py — a shared dead-man's switch for every background loop.

The fleet runs a handful of daemon threads (Scout sweep, Follow-up, Atlas underwriter,
DoToday digest, contract poll, Telegram long-poll). If one of those threads dies — an
uncaught exception escapes the loop body, or the loop simply wedges — nothing notices.
Leads pile up uncaught and the operator finds out days later. There was no substrate that
answered "is each loop actually still running?"

This is that substrate. Every loop calls `beat(...)` once per iteration (at the END, inside
its own try/except so a caught error rides along). We record the wall-clock time of that
beat plus the loop's expected interval, so a reader can tell a loop is STALE (hasn't beaten
in > staleMult × interval) without knowing anything about the loop internally.

Contract (hard): `beat()` NEVER raises. A telemetry bug must never be able to kill the very
loop it is measuring. Every public function swallows its own exceptions and degrades to a
safe default.

State: marcus_state/heartbeats.json  {loop: {lastRun, interval, label, staleMult,
lastError, errStreak, beats}}. Lives in marcus_state/ which is rsync-excluded, so it is
box-local and survives every deploy (mirrors ops_clock.json / agent_bus.json).
"""
import json
import shutil
import threading
import time
from pathlib import Path

import forge_atomic

_DIR = Path(__file__).resolve().parent / "marcus_state"
STATE = _DIR / "heartbeats.json"
_LOCK = threading.Lock()

# Logs the watchdog / health card report on. Written by systemd (StandardOutput=append:)
# and daily_learn.sh — see setup_droplet.sh.
_LOG_FILES = {
    "connector.out.log": Path(__file__).resolve().parent.parent / "connector.out.log",
    "connector.err.log": Path(__file__).resolve().parent.parent / "connector.err.log",
    "daily-learn.log": _DIR / "daily-learn.log",
}


def _load():
    try:
        d = json.loads(STATE.read_text())
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    return d


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def beat(loop, interval=None, label=None, error=None, stale_mult=2.0):
    """Record one heartbeat for `loop`. Call at the end of every loop iteration.

    interval  — expected seconds between beats (for staleness math). Persisted once.
    label     — human name for the UI. Persisted once.
    error     — the caught exception (or its str) from THIS iteration, or None/"" if clean.
                Truthy → set lastError + increment errStreak; falsy → clear + reset streak.
    stale_mult — a loop is 'stale' once ageSec > stale_mult * interval. Persisted once.

    Never raises.
    """
    try:
        now = int(time.time() * 1000)
        with _LOCK:
            d = _load()
            rec = d.get(loop) or {}
            rec["lastRun"] = now
            rec["beats"] = int(rec.get("beats") or 0) + 1
            if interval is not None:
                rec["interval"] = interval
            if label is not None:
                rec["label"] = label
            if stale_mult is not None:
                rec["staleMult"] = stale_mult
            if error:
                rec["lastError"] = str(error)[:400]
                rec["lastErrorAt"] = now
                rec["errStreak"] = int(rec.get("errStreak") or 0) + 1
            else:
                rec["lastError"] = None
                rec["errStreak"] = 0
            d[loop] = rec
            _save(d)
    except Exception:
        pass


def _status_for(rec, now):
    """green / amber / red for one loop record."""
    last = rec.get("lastRun") or 0
    interval = rec.get("interval") or 0
    mult = rec.get("staleMult") or 2.0
    age_sec = max(0, (now - last) / 1000.0) if last else None
    stale = bool(interval) and age_sec is not None and age_sec > mult * interval
    err_streak = int(rec.get("errStreak") or 0)
    if stale or err_streak >= 3:
        status = "red"
    elif rec.get("lastError"):
        status = "amber"
    else:
        status = "green"
    return status, age_sec, stale


def snapshot(now=None):
    """All loops as a list of UI-ready dicts. Never raises (returns [] on failure)."""
    try:
        if now is None:
            now = int(time.time() * 1000)
        with _LOCK:
            d = _load()
        out = []
        for loop, rec in d.items():
            status, age_sec, stale = _status_for(rec, now)
            out.append({
                "loop": loop,
                "label": rec.get("label") or loop,
                "lastRun": rec.get("lastRun"),
                "ageSec": None if age_sec is None else round(age_sec, 1),
                "interval": rec.get("interval"),
                "stale": stale,
                "status": status,
                "lastError": rec.get("lastError"),
                "lastErrorAt": rec.get("lastErrorAt"),
                "errStreak": int(rec.get("errStreak") or 0),
                "beats": int(rec.get("beats") or 0),
            })
        out.sort(key=lambda r: r["loop"])
        return out
    except Exception:
        return []


def disk_log_stats():
    """Disk usage of / and the sizes of the connector + learn logs. Never raises."""
    out = {"disk": None, "logs": {}, "stateBytes": None}
    try:
        du = shutil.disk_usage("/")
        out["disk"] = {
            "totalBytes": du.total,
            "usedBytes": du.used,
            "freeBytes": du.free,
            "pctUsed": round(du.used / du.total * 100, 1) if du.total else None,
        }
    except Exception:
        pass
    for name, path in _LOG_FILES.items():
        try:
            out["logs"][name] = path.stat().st_size if path.exists() else 0
        except Exception:
            out["logs"][name] = None
    try:
        total = 0
        for p in _DIR.glob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except Exception:
                pass
        out["stateBytes"] = total
    except Exception:
        pass
    return out
