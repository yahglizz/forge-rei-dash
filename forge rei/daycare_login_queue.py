"""daycare_login_queue.py — parent login texts that quiet hours held back.

Create login / Resend login after 9pm ET can't text (daycare_leads.in_hours). The owner's
click still created the login; this queue sends the login text from 8am. No PIN is ever
stored: at send time a FRESH PIN is minted. A normal entry is minted with
only_if_never_signed_in — a parent who already signed in (with the PIN staff handed over
at night) keeps their login and gets no text. A Resend entry (force=True) always mints.

Never two PINs for one family: the texting gates (opt-out / DND / GHL) are checked BEFORE
a PIN is minted, a send that fails after the mint is never retried (it becomes a staff-
visible problem), only one run at a time, and an entry is moved to `inflight` before its
mint so a restart mid-send surfaces as a problem instead of a second text.

Spec: A Touch of Blessings — Brand Kit/docs/superpowers/specs/2026-10-06-app-tracking-and-login-fixes-design.md
Knob: FORGE_DAYCARE_LOGIN_QUEUE=0 (connector) keeps the thread off. Stdlib only.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import daycare_leads
import forge_atomic
import forge_heartbeat
import forge_ops

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_login_queue.json"
INTERVAL = 300
MAX_TRIES = 36            # mint retries (~3h of ticks): an outage must not drop the family
STALE_INFLIGHT = 600      # a send still "in flight" after 10 min = the process died mid-send
PROBLEM_WINDOW = 48 * 3600
DONE_KEEP = 50
_LOCK = threading.Lock()  # guards the state file
_RUN = threading.Lock()   # one run at a time (background thread vs the manual "run now")
FIELDS = ("profile_id", "contact_id", "location_id", "parent_first", "child_first")


def _load() -> dict:
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 — missing/corrupt = empty queue
        return {}


def _save(st: dict) -> None:
    forge_atomic.atomic_write_json(STATE, st)


def enqueue(entry: dict, reason: str = "quiet hours", now: float | None = None) -> dict:
    pid = str((entry or {}).get("profile_id") or "")
    if not pid or not str(entry.get("contact_id") or ""):
        return {"ok": False, "error": "profile_id and contact_id are required"}
    with _LOCK:
        st = _load()
        st.setdefault("queue", {})[pid] = {
            **{k: str(entry.get(k) or "") for k in FIELDS},
            "force": bool(entry.get("force")), "reason": str(reason)[:80],
            "queued_at": now or time.time(), "tries": 0}
        _save(st)
    return {"ok": True, "queued": True}


def sending_window(now: float) -> bool:
    """8:00–20:30 ET: inside the texting window with time left for GHL to deliver."""
    t = datetime.fromtimestamp(now, daycare_leads.ET)
    return daycare_leads.in_hours(now) and (t.hour, t.minute) < (20, 30)


def view(now: float | None = None) -> dict:
    now = now or time.time()
    with _LOCK:
        st = _load()
    done = st.get("done") or []
    return {"ok": True, "queued": list((st.get("queue") or {}).values()), "done": done[-20:],
            "problems": [d for d in done if d.get("problem") and now - float(d.get("at") or 0) < PROBLEM_WINDOW]}


def _finish(st: dict, pid: str, entry: dict, outcome: str, now: float, problem: bool) -> None:
    (st.get("inflight") or {}).pop(pid, None)
    done = st.setdefault("done", [])
    done.append({"profile_id": pid, "parent": entry.get("parent_first") or "",
                 "child": entry.get("child_first") or "", "outcome": outcome, "at": now, "problem": problem})
    st["done"] = done[-DONE_KEEP:]


def _recover_inflight(now: float) -> int:
    """Entries left in flight by a crash/restart: never re-sent (that could be a second PIN)."""
    with _LOCK:
        st = _load()
        stale = [(pid, e) for pid, e in (st.get("inflight") or {}).items()
                 if now - float(e.get("started") or 0) > STALE_INFLIGHT]
        for pid, e in stale:
            _finish(st, pid, e, "interrupted mid-send (restart) — check the parent got a text; "
                                "use Resend login if not", now, True)
        if stale:
            _save(st)
    return len(stale)


def _claim(pid: str, entry: dict, now: float) -> bool:
    """Move the entry to inflight. False when it was replaced or removed meanwhile."""
    with _LOCK:
        st = _load()
        current = (st.get("queue") or {}).get(pid)
        if not current or current.get("queued_at") != entry.get("queued_at"):
            return False
        st["queue"].pop(pid)
        st.setdefault("inflight", {})[pid] = {**current, "started": now}
        _save(st)
    return True


def _settle(pid: str, entry: dict, kind: str, outcome: str, now: float) -> None:
    with _LOCK:
        st = _load()
        if kind == "retry":
            (st.get("inflight") or {}).pop(pid, None)
            queue = st.setdefault("queue", {})
            if pid not in queue:      # a newer entry (e.g. a Resend) wins over the retry
                queue[pid] = {k: v for k, v in entry.items() if k != "started"}
        else:
            queue = st.get("queue") or {}
            if queue.get(pid, {}).get("queued_at") == entry.get("queued_at"):
                queue.pop(pid)        # blocked before the claim: still queued, now settled
            _finish(st, pid, entry, outcome, now, problem=kind == "problem")
        _save(st)


def _process(session, pid, entry, mint_fn, send_fn, can_send_fn, now):
    """One entry → (kind, outcome). kind: sent | drop | problem | retry."""
    block = can_send_fn(entry) if can_send_fn else None
    if block:
        return "problem", f"not texted: {block} — PIN unchanged; share it in person or fix and Resend login"
    if not _claim(pid, entry, now):
        return None, None
    minted = mint_fn(session, entry) or {}
    if minted.get("error") == "already_signed_in":
        return "drop", "parent already signed in, no text needed"
    if not minted.get("pin"):
        tries = int(entry.get("tries") or 0) + 1
        if tries < MAX_TRIES:
            entry["tries"] = tries
            return "retry", minted.get("error") or "unknown"
        return "problem", f"gave up after {MAX_TRIES} tries — PIN reset failed: {minted.get('error') or 'unknown'}"
    sent = send_fn(entry, minted) or {}
    if sent.get("ok"):
        return "sent", "sent"
    return "problem", (f"PIN was reset but the text failed: {sent.get('error') or 'unknown'} — "
                       "use Resend login or Reset PIN")


def run_once(session_fn, mint_fn, send_fn, now: float | None = None, can_send_fn=None) -> dict:
    now = now or time.time()
    summary = {"ok": True, "sent": 0, "dropped": 0, "retry": 0, "problems": 0}
    if not sending_window(now):
        return {**summary, "skipped": "outside 8:00–20:30 ET"}
    if not _RUN.acquire(blocking=False):
        return {**summary, "skipped": "already running"}
    try:
        summary["problems"] += _recover_inflight(now)
        with _LOCK:
            pending = dict((_load().get("queue") or {}))
        if not pending:
            return summary
        session = session_fn()
        if session is None:
            return {**summary, "ok": False, "error": "no daycare session — auto-admin is off"}
        for pid, entry in pending.items():
            try:
                kind, outcome = _process(session, pid, dict(entry), mint_fn, send_fn, can_send_fn, now)
            except Exception as e:  # noqa: BLE001 — one family never blocks the rest
                kind, outcome = "problem", f"error before the text: {type(e).__name__} — use Resend login"
            if kind is None:
                continue
            _settle(pid, entry if kind != "retry" else {**entry, "tries": int(entry.get("tries") or 0) + 1},
                    kind, outcome, now)
            summary[{"sent": "sent", "drop": "dropped", "retry": "retry", "problem": "dropped"}[kind]] += 1
            summary["problems"] += kind == "problem"
        with _LOCK:
            st = _load()
            st["last"] = {**summary, "at": now}
            _save(st)
        return summary
    finally:
        _RUN.release()


def run_forever(session_fn, mint_fn, send_fn, can_send_fn=None):
    """Background loop (thread `daycare_login_queue`)."""
    while True:
        err = None
        try:
            if not forge_ops.paused():
                s = run_once(session_fn, mint_fn, send_fn, can_send_fn=can_send_fn)
                err = s.get("error") or (f"{s['problems']} login text(s) need staff" if s.get("problems") else None)
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        forge_heartbeat.beat("daycare_login_queue", INTERVAL, "Solomon · Login texts", error=err)
        time.sleep(INTERVAL)
