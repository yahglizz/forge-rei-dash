"""action_log.py — durable, append-only agent action log (wave-2 item 6, spec §10).

One JSON line per thing an agent (or the operator, via a gated tap) actually DID:
marcus_state/agent_actions.jsonl. Fields: ts, agent, business, trigger, ref, action,
result, ok, error, retry, approvalRequired.

Contract — this is an audit trail, never a gate:
  * record() NEVER raises and never blocks for long (lock wait capped; a full disk or an
    unwritable path is swallowed with one stderr line per process).
  * Hooks call it AFTER the action with the result only. Nothing here can change,
    delay, or veto what happened.
  * No message bodies, no full phone numbers (last 4 max), no secrets: every string is
    scrubbed with agent_coach's secret patterns + Bearer / sk- / EAA / Telegram shapes
    before it touches disk.

marcus_state/ is in connector.DENY_DIRS and .jsonl is not in SERVE_TYPES, so the file
itself 404s over HTTP; read it via GET /api/actions/log. Stdlib only.
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# FORGE_ACTION_LOG overrides the path (tests, or /dev/null to silence it).
STATE = Path(os.environ.get("FORGE_ACTION_LOG") or HERE / "marcus_state" / "agent_actions.jsonl")
# ponytail: one rotated file (.1) at 5 MB = ~15k lines of history; add .2 or ship to
# the brain if the audit horizon ever needs to be longer than that.
MAX_BYTES = 5 * 1024 * 1024
TAIL_BYTES = 1024 * 1024        # recent() reads at most the last 1 MB of each file
_LOCK = threading.Lock()
_WARNED = [False]

try:  # reuse the coaching secret-guard patterns — one list of vendor key shapes
    from agent_coach import _SECRET_PATTERNS as _COACH_PATTERNS
except Exception:  # noqa: BLE001 — a broken import must never break the log
    _COACH_PATTERNS = []
_EXTRA_PATTERNS = [
    re.compile(r"\bBearer\s+\S{8,}", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),             # generic sk- keys
    re.compile(r"\bEAA[A-Za-z0-9]{16,}"),                # Meta access token
    re.compile(r"\b\d{6,}:AA[A-Za-z0-9_\-]{20,}"),        # Telegram bot token
    re.compile(r"-----BEGIN[^-]*-----.*?(-----END[^-]*-----|$)", re.S),
]
_PATTERNS = list(_COACH_PATTERNS) + _EXTRA_PATTERNS
# ONE phone number per match (Codex: a greedy run swallowed neighbours / dates and then
# failed the length check, leaving numbers whole). NANP 3-3-4 with optional +1 / separators,
# or a bare 11-15 digit international run. A date like 2026-09-22 (4-2-2) never matches.
_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"
                    r"|(?<!\d)\+?\d{11,15}(?!\d)")
# A prefix-only secret pattern (e.g. coaching's GHL `pit-` shape) must not leave the tail.
_REDACT_TAIL = re.compile(r"\[REDACTED\][\w\-.]+")


def _mask_phone(m):
    digits = re.sub(r"\D", "", m.group(0))
    return "***" + digits[-4:]


def _scrub(v, limit=300):
    if v is None:
        return None
    s = str(v)
    for p in _PATTERNS:
        s = p.sub("[REDACTED]", s)
    s = _REDACT_TAIL.sub("[REDACTED]", s)
    s = _PHONE.sub(_mask_phone, s)
    return s[:limit]


def _who():
    try:  # same attribution as cost_tracker: the named loop thread IS the agent
        import cost_tracker
        return cost_tracker._who()
    except Exception:  # noqa: BLE001
        return "operator"


def _warn(e):
    if not _WARNED[0]:
        _WARNED[0] = True
        try:
            print(f"[action_log] write failed (further errors silenced): {e}",
                  file=sys.stderr, flush=True)
        except Exception:  # noqa: BLE001
            pass


def record(agent=None, action="", *, business=None, trigger=None, ref=None,
           result=None, ok=True, error=None, retry=0, approval_required=False):
    """Append one action line. Returns True if written. Never raises."""
    try:
        line = json.dumps({
            "ts": int(time.time() * 1000),
            "agent": _scrub(agent or _who(), 40),
            "business": _scrub(business, 40),
            "trigger": _scrub(trigger, 60),
            "ref": _scrub(ref, 120),
            "action": _scrub(action, 80),
            "result": _scrub(result),
            "ok": bool(ok),
            "error": _scrub(error),
            "retry": int(retry or 0),
            "approvalRequired": bool(approval_required),
        }, ensure_ascii=False) + "\n"
    except Exception as e:  # noqa: BLE001
        _warn(e)
        return False
    # Codex P1: disk I/O never runs on the caller's thread (an SMS send / Marcus lock /
    # contract send). Enqueue and return; a daemon worker writes. Full queue = dropped line.
    # ponytail: lines still queued at process exit are lost — fine for an audit trail;
    # add an atexit flush if that ever matters.
    try:
        _ensure_worker()
        _Q.put_nowait(line)
        return True
    except Exception as e:  # noqa: BLE001 — queue.Full or a thread-start failure
        _warn(e)
        return False


_Q = queue.Queue(maxsize=2000)
_WORKER = [None]


def _ensure_worker():
    w = _WORKER[0]
    if w is None or not w.is_alive():
        with _LOCK:
            w = _WORKER[0]
            if w is None or not w.is_alive():
                w = threading.Thread(target=_drain, name="action_log", daemon=True)
                w.start()
                _WORKER[0] = w


def _drain():
    while True:
        line = _Q.get()
        try:
            _write(line)
        finally:
            _Q.task_done()


def flush(timeout=5.0):
    """Wait (bounded) until queued lines are on disk. Tests/readers only — never a send path."""
    end = time.time() + timeout
    while _Q.unfinished_tasks and time.time() < end:
        time.sleep(0.01)
    return not _Q.unfinished_tasks


def _write(line):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        try:
            if STATE.stat().st_size > MAX_BYTES:
                os.replace(STATE, STATE.with_name(STATE.name + ".1"))
        except FileNotFoundError:
            pass
        with open(STATE, "a", encoding="utf-8") as f:
            f.write(line)                 # one write of one line: O_APPEND keeps it whole
        return True
    except Exception as e:  # noqa: BLE001
        _warn(e)
        return False


def record_result(res, agent=None, action="", **kw):
    """record() with ok/error/result derived from an engine's {ok|error|detail} dict.
    Never raises."""
    try:
        d = res if isinstance(res, dict) else {}
        ok = bool(res) if not isinstance(res, dict) else (
            not d.get("error") and d.get("ok") is not False)
        err = None if ok else (d.get("error") or d.get("detail") or d.get("note") or "failed")
        summary = (d.get("gate") or d.get("stage") or d.get("status")
                   or (d.get("detail") if ok else None) or ("ok" if ok else "error"))
        return record(agent, action, ok=ok, error=err, result=summary, **kw)
    except Exception as e:  # noqa: BLE001
        _warn(e)
        return False


def _tail(path):
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - TAIL_BYTES))
            raw = f.read().decode("utf-8", "replace").splitlines()
        if size > TAIL_BYTES:
            raw = raw[1:]                 # first line is a partial cut
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ln in raw:
        try:
            out.append(json.loads(ln))
        except Exception:  # noqa: BLE001 — a torn/garbled line is skipped, not fatal
            continue
    return out


def recent(n=50, agent=None):
    """Newest-first list of up to n lines (optionally one agent). Never raises."""
    try:
        n = max(1, min(int(n or 50), 500))
        rows = _tail(STATE)
        if agent:
            rows = [r for r in rows if r.get("agent") == agent]
        if len(rows) < n:                 # dip into the rotated file only when short
            old = _tail(STATE.with_name(STATE.name + ".1"))
            if agent:
                old = [r for r in old if r.get("agent") == agent]
            rows = old + rows
        return rows[-n:][::-1]
    except Exception:  # noqa: BLE001
        return []


def last_by_agent(n=500):
    """{agent: {ts, action, ok}} for each agent's newest line in the tail. Never raises."""
    out = {}
    for r in recent(n):
        a = r.get("agent")
        if a and a not in out:
            out[a] = {"ts": r.get("ts"), "action": r.get("action"), "ok": r.get("ok")}
    return out
