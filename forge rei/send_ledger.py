"""Shared send-gate — stops the Tier-2 cadence loops from double-texting a seller.

Every outward SMS path (Marcus reply approval, nurture check-back) RECORDS its touch here.
The follow-up + check-back loops check recency before proposing a NEW automated touch, so a
bump can't fire right after a real reply and two automated touches can't stack on one thread.

Operator-approved replies to a live conversation are recorded but never blocked — that's the
operator's call. The gate only suppresses automated cadence touches.
"""
import json
import threading
import time
from pathlib import Path

import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "send_ledger.json"
_LOCK = threading.Lock()
_DAY_MS = 24 * 60 * 60 * 1000


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def record(conv_id, kind="reply", last_message_date=0):
    """Stamp an outbound touch for a conversation. Call AFTER a successful GHL send.

    `last_message_date` = the thread's latest-message timestamp (epoch ms) AT SEND TIME. Do
    Today uses it to suppress a re-surfaced "text back" task until the seller replies again
    (a newer lastMessageDate). 0 = unknown (no suppression)."""
    if not conv_id:
        return
    now = int(time.time() * 1000)
    with _LOCK:
        d = _load()
        rec = {"at": now, "kind": kind}
        try:
            lmd = int(last_message_date or 0)
        except (TypeError, ValueError):
            lmd = 0
        if lmd:
            rec["lastMessageDate"] = lmd
        d[str(conv_id)] = rec
        cutoff = now - 60 * _DAY_MS          # prune touches older than 60d
        d = {k: v for k, v in d.items() if (v.get("at") or 0) >= cutoff}
        forge_atomic.atomic_write_json(STATE, d)


def last_touch_at(conv_id):
    if not conv_id:
        return 0
    return (_load().get(str(conv_id)) or {}).get("at") or 0


def last_reply_msg_date(conv_id):
    """The thread's lastMessageDate captured the last time WE texted this conversation back
    (0 if never / unknown). Do Today suppresses the reply task while the thread hasn't moved
    past this — i.e. the seller hasn't said anything new since we replied."""
    if not conv_id:
        return 0
    return (_load().get(str(conv_id)) or {}).get("lastMessageDate") or 0


def touched_within(conv_id, hours):
    """True if this conversation got any outbound touch within the last `hours`."""
    last = last_touch_at(conv_id)
    return bool(last) and (int(time.time() * 1000) - last) < hours * 60 * 60 * 1000
