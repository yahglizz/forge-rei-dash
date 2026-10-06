"""daycare_login_queue.py — parent login texts that quiet hours held back.

Create login / Resend login after 9pm ET can't text (daycare_leads.in_hours). The owner's
click still created the login; this queue sends the login text from 8am. No PIN is ever
stored: at send time a FRESH PIN is minted. A normal entry is minted with
only_if_never_signed_in — a parent who already signed in (with the PIN staff handed over
at night) keeps their login and gets no text. A Resend entry (force=True) always mints.

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
MAX_TRIES = 3
DONE_KEEP = 50
_LOCK = threading.Lock()
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


def view() -> dict:
    with _LOCK:
        st = _load()
    return {"ok": True, "queued": list((st.get("queue") or {}).values()),
            "done": (st.get("done") or [])[-20:]}


def run_once(session_fn, mint_fn, send_fn, now: float | None = None) -> dict:
    now = now or time.time()
    summary = {"ok": True, "sent": 0, "dropped": 0, "retry": 0}
    if not sending_window(now):
        return {**summary, "skipped": "outside 8:00–20:30 ET"}
    with _LOCK:
        pending = dict((_load().get("queue") or {}))
    if not pending:
        return summary
    session = session_fn()
    if session is None:
        return {**summary, "ok": False, "error": "no daycare session — auto-admin is off"}
    results = {}
    for pid, entry in pending.items():
        try:
            minted = mint_fn(session, entry) or {}
            if minted.get("error") == "already_signed_in":
                results[pid] = ("drop", "parent already signed in, no text needed")
            elif minted.get("pin"):
                sent = send_fn(entry, minted) or {}
                results[pid] = ("sent", "sent") if sent.get("ok") else (
                    "fail", f"send failed: {sent.get('error') or 'unknown'}")
            else:
                results[pid] = ("fail", f"PIN reset failed: {minted.get('error') or 'unknown'}")
        except Exception as e:  # noqa: BLE001 — one family never blocks the rest
            results[pid] = ("fail", f"{type(e).__name__}")
    with _LOCK:
        st = _load()
        queue = st.setdefault("queue", {})
        done = st.setdefault("done", [])
        for pid, (kind, outcome) in results.items():
            if pid not in queue:
                continue
            if kind == "fail":
                queue[pid]["tries"] = int(queue[pid].get("tries") or 0) + 1
                if queue[pid]["tries"] < MAX_TRIES:
                    summary["retry"] += 1
                    continue
                outcome = f"gave up after {MAX_TRIES} tries — {outcome}"
            queue.pop(pid)
            summary["sent" if kind == "sent" else "dropped"] += 1
            done.append({"profile_id": pid, "outcome": outcome, "at": now})
        st["done"] = done[-DONE_KEEP:]
        st["last"] = {**summary, "at": now}
        _save(st)
    return summary


def run_forever(session_fn, mint_fn, send_fn):
    """Background loop (thread `daycare_login_queue`)."""
    while True:
        err = None
        try:
            if not forge_ops.paused():
                err = run_once(session_fn, mint_fn, send_fn).get("error")
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        forge_heartbeat.beat("daycare_login_queue", INTERVAL, "Solomon · Login texts", error=err)
        time.sleep(INTERVAL)
