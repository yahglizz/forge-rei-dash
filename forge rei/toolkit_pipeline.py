"""Wholesaler Toolkit — local Pipeline Organizer state (Phase 3).

This module deliberately never writes to GoHighLevel.  Pipeline cards remain a
read-only view of GHL; the only persisted state is the operator's local reminder
overlay.  Every write is atomic so a restart cannot leave malformed JSON behind.
"""
import datetime as _datetime
import json
import math
import threading
import time
from pathlib import Path

import forge_atomic


STATE = Path(__file__).resolve().parent / "marcus_state" / "pipeline_reminders.json"
_LOCK = threading.RLock()
_STATUSES = ("pending", "sent", "dismissed", "snoozed")
MAX_REMINDERS = 1000
_DAY_MS = 24 * 60 * 60 * 1000


def _now():
    return int(time.time() * 1000)


def _load():
    try:
        raw = json.loads(STATE.read_text())
    except Exception:
        raw = {}
    reminders = raw.get("reminders") if isinstance(raw, dict) else {}
    return {"reminders": reminders if isinstance(reminders, dict) else {}}


def _save(data):
    forge_atomic.atomic_write_json(STATE, data)


def _ms(value):
    """Normalize milliseconds or a parseable ISO date to epoch milliseconds."""
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).strip())
        if not math.isfinite(parsed) or parsed <= 0:
            return None
        return int(parsed * 1000) if parsed < 20_000_000_000 else int(parsed)
    except (TypeError, ValueError):
        pass
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = _datetime.datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_datetime.timezone.utc)
        return int(dt.timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _record(data, deal_id):
    return data["reminders"].get(str(deal_id or ""))


def get_reminder(deal_id):
    """Return a reminder by deal/contact id, or ``None`` when it is unset."""
    with _LOCK:
        record = _record(_load(), deal_id)
        return dict(record) if isinstance(record, dict) else None


def create_reminder(deal_id, deal_dict, due_at, draft_msg):
    """Create or replace the one local reminder associated with a deal."""
    key = str(deal_id or "").strip()
    due_ms = _ms(due_at)
    if not key:
        return {"error": "dealId required"}
    if due_ms is None:
        return {"error": "valid dueAt required"}
    deal = deal_dict if isinstance(deal_dict, dict) else {}
    now = _now()
    reminder = {
        "dealId": key,
        "dealName": str(deal.get("name") or deal.get("dealName") or ""),
        "address": str(deal.get("address") or ""),
        "setAt": now,
        "dueAt": due_ms,
        "draftMsg": str(draft_msg or ""),
        "status": "pending",
        "sentAt": None,
        "snoozedUntil": None,
        "note": "",
    }
    with _LOCK:
        data = _load()
        data["reminders"][key] = reminder
        if len(data["reminders"]) > MAX_REMINDERS:
            rows = sorted(data["reminders"].values(),
                          key=lambda row: -(row.get("setAt") or 0))[:MAX_REMINDERS]
            data["reminders"] = {row["dealId"]: row for row in rows}
        _save(data)
    return dict(reminder)


def list_reminders(status=None):
    """Return reminders by next due time, optionally filtered by local state."""
    if status is not None and status not in _STATUSES:
        return []
    with _LOCK:
        rows = [dict(row) for row in _load()["reminders"].values()
                if isinstance(row, dict) and (status is None or row.get("status") == status)]
    rows.sort(key=lambda row: (row.get("dueAt") or 0, row.get("setAt") or 0))
    return rows


def _change(deal_id, updater):
    key = str(deal_id or "").strip()
    if not key:
        return {"error": "dealId required"}
    with _LOCK:
        data = _load()
        record = _record(data, key)
        if not isinstance(record, dict):
            return {"error": "reminder not found"}
        updater(record)
        data["reminders"][key] = record
        _save(data)
        return dict(record)


def snooze_reminder(deal_id, until_ms):
    """Delay a reminder locally.  It does not notify or mutate any CRM record."""
    until = _ms(until_ms)
    if until is None:
        return {"error": "valid untilMs required"}

    def apply(record):
        record.update(status="snoozed", snoozedUntil=until, dueAt=until, snoozedAt=_now())
    return _change(deal_id, apply)


def dismiss_reminder(deal_id):
    """Close a reminder while retaining its history in the local store."""
    return _change(deal_id, lambda record: record.update(status="dismissed", dismissedAt=_now()))


def mark_sent(deal_id):
    """Record an operator handoff only; Phase 3 has no transport side effect."""
    return _change(deal_id, lambda record: record.update(status="sent", sentAt=_now()))


def update_reminder(deal_id, **fields):
    """Edit the reversible local notes.  Lifecycle state is controlled above."""
    allowed = {"draftMsg", "note"}

    def apply(record):
        for name in allowed:
            if name in fields and fields[name] is not None:
                record[name] = str(fields[name])
    return _change(deal_id, apply)


def days_in_stage(deal):
    """Return elapsed days from ``updatedAt`` rounded up, or ``None`` if unknown."""
    if not isinstance(deal, dict):
        return None
    updated = _ms(deal.get("updatedAt") if deal.get("updatedAt") is not None
                  else deal.get("updated"))
    if updated is None:
        return None
    return max(0, int(math.ceil((_now() - updated) / float(_DAY_MS))))
