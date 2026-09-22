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

State: marcus_state/heartbeats.json  {loop: {lastRun, lastSuccessAt, interval, label,
staleMult, lastError, errStreak, errorsTotal, beats}}. Lives in marcus_state/ which is
rsync-excluded, so it is box-local and survives every deploy (mirrors ops_clock.json /
agent_bus.json).

AI dependency health (marcus_state/ai_health.json): heartbeats wrap LOOPS, not Claude
calls — a loop whose every Claude call 400s still beats green (that hid a 51-day
credit outage). `ai_ok()` / `ai_fail()` are stamped at the two shared call sites
(review_agent._claude, marcus_engine._ai_draft); `ai_health()` is what /api/system/health
and the watchdog read. Billing (400 "credit balance") and auth (401/403) = HARD DOWN
until the next successful call; 429/5xx/network = transient. Never raises.
"""
import json
import re
import shutil
import threading
import time
from pathlib import Path

import forge_atomic

_DIR = Path(__file__).resolve().parent / "marcus_state"
STATE = _DIR / "heartbeats.json"
AI_STATE = _DIR / "ai_health.json"
_LOCK = threading.Lock()

# Error strings land in a state file + the health API + Telegram. Never a secret.
_SECRET_RE = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]+|pit-[A-Za-z0-9_\-]+|eyJ[A-Za-z0-9_\-]{20,}"
    r"|(?i:(?:token|key|secret|bearer|password)\s*[=:]\s*)\S+")


def _scrub(s, limit=400):
    try:
        return _SECRET_RE.sub("[redacted]", str(s))[:limit]
    except Exception:
        return "?"

# Logs the watchdog / health card report on. Written by systemd (StandardOutput=append:)
# and daily_learn.sh — see setup_droplet.sh.
_LOG_FILES = {
    "connector.out.log": Path(__file__).resolve().parent.parent / "connector.out.log",
    "connector.err.log": Path(__file__).resolve().parent.parent / "connector.err.log",
    "daily-learn.log": _DIR / "daily-learn.log",
}


# Loops that no longer exist. Their last heartbeat is still in the state file on any
# box that ran them, and a loop that never beats again goes red forever — so the health
# card and the watchdog would alarm on an agent we deliberately retired. Dropped on read.
RETIRED_LOOPS = {"nora", "nova", "hawk", "blaze", "otto"}


def _load():
    try:
        d = json.loads(STATE.read_text())
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    if d.keys() & RETIRED_LOOPS:
        d = {k: v for k, v in d.items() if k not in RETIRED_LOOPS}
        try:
            _save(d)          # prune once, so the file stops carrying dead loops
        except Exception:
            pass
    return d


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def retire(loop):
    """Drop one loop's heartbeat. Call when a loop is deliberately switched OFF.

    A loop that stops beating goes red forever and trips the health card + watchdog —
    which is exactly right for a crashed loop and exactly wrong for one the operator
    disabled on purpose (FORGE_DROPSHIP_BRIEF=0, FORGE_TODAY_LOOP=0). Idempotent, and
    never raises: telemetry must not be able to break boot.
    """
    try:
        with _LOCK:
            d = _load()
            if loop in d:
                d.pop(loop, None)
                _save(d)
    except Exception:
        pass


def beat(loop, interval=None, label=None, error=None, stale_mult=2.0):
    """Record one heartbeat for `loop`. Call at the end of every loop iteration.

    interval  — expected seconds between beats (for staleness math). Persisted once.
    label     — human name for the UI. Persisted once.
    error     — the caught exception (or its str) from THIS iteration, or None/"" if clean.
                Truthy → set lastError + increment errStreak + errorsTotal; falsy → clear
                the streak and stamp lastSuccessAt. errorsTotal is cumulative (never reset).
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
                rec["lastError"] = _scrub(error)
                rec["lastErrorAt"] = now
                rec["errStreak"] = int(rec.get("errStreak") or 0) + 1
                rec["errorsTotal"] = int(rec.get("errorsTotal") or 0) + 1
            else:
                rec["lastError"] = None
                rec["errStreak"] = 0
                rec["lastSuccessAt"] = now
            d[loop] = rec
            _save(d)
    except Exception:
        pass


# ── AI dependency health ──────────────────────────────────────────────────────
def _ai_load():
    try:
        d = json.loads(AI_STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _ai_save(d):
    forge_atomic.atomic_write_json(AI_STATE, d)


def ai_classify(code, msg):
    """(kind, hard) for one failed Claude call. billing/auth = hard down; else transient."""
    m = str(msg or "").lower()
    if code == 400 and "credit balance" in m:
        return "billing", True
    if code in (401, 403) or "authentication_error" in m or "permission_error" in m:
        return "auth", True
    return "transient", False


def ai_ok():
    """A Claude call succeeded. Clears any hard-down state. Never raises."""
    try:
        now = int(time.time() * 1000)
        with _LOCK:
            d = _ai_load()
            d.update({"ok": True, "lastOkAt": now, "downSince": None, "reason": None,
                      "kind": None, "hard": False, "failStreak": 0,
                      "callsTotal": int(d.get("callsTotal") or 0) + 1})
            _ai_save(d)
    except Exception:
        pass


def ai_fail(code, msg):
    """A Claude call failed. code = HTTP status (None for network/timeouts). Never raises."""
    try:
        now = int(time.time() * 1000)
        kind, hard = ai_classify(code, msg)
        with _LOCK:
            d = _ai_load()
            d["callsTotal"] = int(d.get("callsTotal") or 0) + 1
            d["errorsTotal"] = int(d.get("errorsTotal") or 0) + 1
            d["failStreak"] = int(d.get("failStreak") or 0) + 1
            d["lastError"] = f"HTTP {code}: {_scrub(msg, 300)}" if code else _scrub(msg, 300)
            d["lastErrorAt"] = now
            d["lastKind"] = kind
            if hard:
                # A 429 during a billing outage does not end the outage — only ai_ok() does.
                d["ok"] = False
                d["hard"] = True
                d["kind"] = kind
                d["downSince"] = d.get("downSince") or now
                d["reason"] = ("Anthropic credit balance exhausted — top up the account"
                               if kind == "billing" else
                               f"Anthropic rejected the API key (HTTP {code}) — check/rotate it")
            _ai_save(d)
    except Exception:
        pass


def ai_alerted(flag):
    """Persist whether the watchdog has already alerted on the current outage (survives
    restarts so one outage = one alert). Never raises."""
    try:
        with _LOCK:
            d = _ai_load()
            d["alerted"] = bool(flag)
            _ai_save(d)
    except Exception:
        pass


def ai_health():
    """UI/health-route-ready read of the AI dependency. ok=False only while hard-down
    (billing/auth); transient errors show in lastError/failStreak. Never raises."""
    base = {"ok": True, "hard": False, "kind": None, "reason": None, "lastOkAt": None,
            "lastErrorAt": None, "lastError": None, "lastKind": None, "downSince": None,
            "failStreak": 0, "callsTotal": 0, "errorsTotal": 0, "alerted": False}
    try:
        with _LOCK:
            d = _ai_load()
        base.update({k: d.get(k, v) for k, v in base.items()})
        base["ok"] = not bool(base["hard"])
        return base
    except Exception:
        return base


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
                "lastSuccessAt": rec.get("lastSuccessAt"),
                "ageSec": None if age_sec is None else round(age_sec, 1),
                "interval": rec.get("interval"),
                "stale": stale,
                "status": status,
                "lastError": rec.get("lastError"),
                "lastErrorAt": rec.get("lastErrorAt"),
                "errStreak": int(rec.get("errStreak") or 0),
                "errorsTotal": int(rec.get("errorsTotal") or 0),
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
