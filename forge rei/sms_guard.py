"""Central outbound-SMS safety gate.

Every code path that can create a GoHighLevel SMS should call guard() immediately
before the API write, then record_success() or release() after the write returns.
This keeps operator clicks, Marcus approvals, screening nurtures, Telegram actions,
and autopilot on the same load-bearing checks.
"""
import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

import forge_atomic
import forge_ops
import legit_check
import marcus_engine
import send_ledger

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "sms_guard.json"
_LOCK = threading.Lock()

SEND_START = int(os.environ.get("FORGE_SMS_SEND_START", "9"))
SEND_END = int(os.environ.get("FORGE_SMS_SEND_END", "20"))
DAILY_CAP = int(os.environ.get("FORGE_SMS_DAILY_CAP", "80"))
DEDUP_MINUTES = float(os.environ.get("FORGE_SMS_DEDUPE_MINUTES", "3"))
MAX_LOG = 500

_PRICE_RE = re.compile(r"(?i)(\$\s*\d|(?:^|\s)\d{2,3}[,.]?\d{3}\b|\b\d+\s*k\b)")
_OFFER_RE = re.compile(
    r"(?i)\b(offer|offering|cash offer|pay|paying|give you|can do|"
    r"come in at|bring you|net you|purchase price|buy it for)\b"
)


def _now_ms():
    return int(time.time() * 1000)


def _today_key():
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        return time.strftime("%Y-%m-%d")


def _hour_et():
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).hour
    except Exception:
        return time.localtime().tm_hour


def _within_hours():
    return SEND_START <= _hour_et() < SEND_END


def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _roll(d):
    today = _today_key()
    if d.get("day") != today:
        d = {"day": today, "sent": 0, "pending": {}, "log": []}
    d.setdefault("pending", {})
    d.setdefault("log", [])
    d.setdefault("sent", 0)
    return d


def _msg_hash(message):
    return hashlib.sha256((message or "").strip().lower().encode()).hexdigest()[:16]


def _reserve(contact_id, conv_id, message, kind):
    if DAILY_CAP <= 0:
        return None
    token = uuid.uuid4().hex
    now = _now_ms()
    with _LOCK:
        d = _roll(_load())
        pending = d.setdefault("pending", {})
        # Drop abandoned reservations after 10 minutes so a crashed worker does not
        # hold the daily cap forever.
        for k, v in list(pending.items()):
            if now - int(v.get("ts") or 0) > 10 * 60 * 1000:
                pending.pop(k, None)
        if int(d.get("sent") or 0) + len(pending) >= DAILY_CAP:
            return {"error": f"daily cap {DAILY_CAP} reached", "gate": "daily_cap"}
        h = _msg_hash(message)
        dedupe_ms = int(max(0, DEDUP_MINUTES) * 60 * 1000)
        for v in pending.values():
            if conv_id and v.get("convId") == conv_id and now - int(v.get("ts") or 0) <= dedupe_ms:
                return {"error": "thread already has a pending SMS send", "gate": "pending_dedupe"}
            if conv_id and v.get("convId") == conv_id and v.get("hash") == h:
                return {"error": "duplicate SMS send already pending", "gate": "pending_dedupe"}
        pending[token] = {
            "ts": now,
            "kind": kind,
            "contactId": contact_id,
            "convId": conv_id,
            "hash": h,
        }
        _save(d)
    return {"reservation": token}


def release(reservation):
    if not reservation:
        return {"ok": True}
    with _LOCK:
        d = _roll(_load())
        d.setdefault("pending", {}).pop(reservation, None)
        _save(d)
    return {"ok": True}


def _last_inbound_from_thread(scout, conv_id):
    if not (scout and conv_id):
        return "", []
    msgs = scout._thread_transcript(conv_id) or []
    inbound = [(m.get("body") or "").strip() for m in msgs
               if m.get("direction") == "inbound" and (m.get("body") or "").strip()]
    return (inbound[-1] if inbound else ""), msgs


def _quotes_price_or_offer(message):
    text = (message or "").strip()
    return bool(_PRICE_RE.search(text) or _OFFER_RE.search(text))


def guard(contact_id, message, conv_id=None, name="", scout=None,
          last_seller_message=None, kind="sms", autonomous=False,
          check_legit=True, reserve=True):
    """Return {"ok": True, "reservation": "..."} or {"error": "...", "gate": "..."}.

    kind="screening_nurture" is the only soft-no exception: it may send a
    no-pressure check-back request, but it still cannot contain a price/offer.
    """
    contact_id = (contact_id or "").strip()
    message = (message or "").strip()
    if not contact_id or not message:
        return {"error": "contactId and message required", "gate": "required"}
    # `autonomous` = an agent (ACE / autopilot) initiated this send → every gate applies.
    # Otherwise the OPERATOR initiated it (a manual tap, a speed-to-lead reply, or a
    # human-approved Marcus draft). "The operator's own actions always work" (forge_ops
    # philosophy): operator sends still honor TCPA quiet-hours + the seller's DNC/STOP
    # opt-out (both legal), but are NOT hard-gated by clock-out, the legit-check verdict, or
    # a legit-check outage (a missing Anthropic key must never lock the operator out of
    # texting), soft-no, or the our-message filter.
    operator = not autonomous
    if forge_ops.paused() and not operator:
        return {"error": "crew is clocked out", "gate": "clock_out"}
    if not _within_hours():
        return {"error": "outside 9am-8pm ET send window", "gate": "send_hours"}
    if conv_id and DEDUP_MINUTES > 0 and not operator:
        if send_ledger.touched_within(conv_id, DEDUP_MINUTES / 60.0):
            return {"error": f"thread touched within {DEDUP_MINUTES:g} minutes",
                    "gate": "send_ledger"}

    last_in = (last_seller_message or "").strip()
    protected_draft = autonomous or kind in ("screening_nurture", "marcus_nrn")
    thread_msgs = []
    # Agent-authored copy needs the recent seller context, not just the newest inbound.
    # A price stated one message earlier still makes "in the ballpark" an offer leak.
    if scout and conv_id and (not last_in or protected_draft):
        try:
            thread_last, thread_msgs = _last_inbound_from_thread(scout, conv_id)
            if thread_last:
                last_in = thread_last
        except Exception as e:  # noqa: BLE001
            if not operator or protected_draft:
                return {"error": f"could not read thread before SMS: {e}",
                        "gate": "thread_read"}
            last_in = ""     # operator send never blocked by a thread-read hiccup
    if last_in:
        # DNC / hard opt-out blocks EVERY send, operator included — legal compliance.
        cls = marcus_engine.classify(last_in)
        if cls == "DNC" or marcus_engine._is_hard_no(last_in):
            return {"error": "seller opted out or hard-declined", "gate": "hard_no"}
        if not operator:
            if not marcus_engine._is_seller_message(last_in):
                return {"error": "last inbound looks like our own outreach",
                        "gate": "our_message"}
            if (marcus_engine._is_soft_no(last_in)
                    and kind not in ("screening_nurture", "marcus_nrn")):
                return {"error": "seller gave a soft no; only nurture/check-back is allowed",
                        "gate": "soft_no"}

    # Final content firewall. This duplicates Marcus's queue-admission check on purpose:
    # persisted legacy proposals, operator edits later marked autonomous, and future agent
    # paths must still fail closed at the last instant before the GHL POST.
    seller_context = last_in
    if thread_msgs:
        recent_inbound = [(m.get("body") or "").strip() for m in thread_msgs
                          if m.get("direction") == "inbound" and (m.get("body") or "").strip()]
        seller_context = "\n".join(recent_inbound[-8:]) or last_in
    if protected_draft:
        unsafe = marcus_engine._draft_safety_reason(message, seller_context)
        if unsafe:
            return {"error": f"unsafe AI draft: {unsafe}", "gate": "draft_safety"}

    if protected_draft and _quotes_price_or_offer(message):
        return {"error": "autonomous/nurture SMS cannot quote a price or offer",
                "gate": "price_offer"}

    if check_legit and not operator:
        v = legit_check.verdict(scout, conv_id, name)
        if not isinstance(v, dict):
            return {"error": "legit_check unavailable: invalid verdict",
                    "gate": "legit_check_unavailable", "verdict": v}
        reason = str(v.get("reason") or "")
        unavailable = (
            "no key" in reason.lower()
            or "thread unreadable" in reason.lower()
            or "no thread to judge" in reason.lower()
            or "judge error" in reason.lower()
        )
        if unavailable:
            return {"error": f"legit_check unavailable: {reason}",
                    "gate": "legit_check_unavailable", "verdict": v}
        if isinstance(v, dict) and not v.get("legit"):
            return {"error": f"legit_check: {reason or 'not legit'}",
                    "gate": "legit_check", "verdict": v}

    out = {"ok": True}
    if reserve:
        held = _reserve(contact_id, conv_id, message, kind)
        if isinstance(held, dict) and held.get("error"):
            return held
        if isinstance(held, dict):
            out.update(held)
    return out


def record_success(reservation=None, conv_id=None, contact_id=None, message=None,
                   kind="sms", last_message_date=0):
    """Commit a successful SMS send to the guard counter and send ledger."""
    try:
        if conv_id:
            send_ledger.record(conv_id, kind=kind, last_message_date=last_message_date or 0)
    except Exception:
        pass
    try:  # cost telemetry — every outbound SMS is a metered send
        import cost_tracker
        cost_tracker.record_sms(1)
    except Exception:
        pass
    if DAILY_CAP <= 0:
        return {"ok": True}
    now = _now_ms()
    with _LOCK:
        d = _roll(_load())
        pending = d.setdefault("pending", {})
        rec = pending.pop(reservation, None) if reservation else None
        d["sent"] = int(d.get("sent") or 0) + 1
        d.setdefault("log", []).insert(0, {
            "ts": now,
            "kind": kind or (rec or {}).get("kind"),
            "contactId": contact_id or (rec or {}).get("contactId"),
            "convId": conv_id or (rec or {}).get("convId"),
            "hash": _msg_hash(message) if message else (rec or {}).get("hash"),
        })
        d["log"] = d["log"][:MAX_LOG]
        _save(d)
    return {"ok": True}


def status():
    with _LOCK:
        d = _roll(_load())
        return {
            "day": d.get("day"),
            "sent": int(d.get("sent") or 0),
            "pending": len(d.get("pending") or {}),
            "dailyCap": DAILY_CAP,
            "sendStart": SEND_START,
            "sendEnd": SEND_END,
            "dedupeMinutes": DEDUP_MINUTES,
        }
