"""monthly_goals.py — the monthly goals board for FORGE REI OS.

Dashboard-owned, editable monthly goals (seeded with "Close my first deal").
Recurring: when the month rolls over, the goal texts carry forward but every
goal is reset to un-done so the board is a fresh checklist each month.

State persists in marcus_state/monthly_goals.json so it survives restarts and
the 24/7 server owns the single source of truth.
"""
import forge_atomic
import json
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "monthly_goals.json"
_LOCK = threading.Lock()


def _month():
    return datetime.now().strftime("%Y-%m")


def _now_ms():
    return int(time.time() * 1000)


def _new_id(d):
    # Millis-based string; append the goal count to stay unique if two adds
    # land in the same millisecond.
    base = str(_now_ms())
    n = len(d.get("goals", []))
    return f"{base}{n}"


def _seed():
    return {
        "month": _month(),
        "goals": [{"id": str(_now_ms()), "text": "Close my first deal", "done": False}],
        "updatedAt": _now_ms(),
    }


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            d.setdefault("month", _month())
            d.setdefault("goals", [])
            d.setdefault("updatedAt", _now_ms())
            return d
        except Exception:
            pass
    return _seed()


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _ensure_month(d):
    month = _month()
    if d.get("month") == month:
        return d
    # New month: carry goal texts over, reset every goal to un-done.
    d["month"] = month
    for g in d.get("goals", []):
        g["done"] = False
    return d


def get():
    with _LOCK:
        d = _load()
        before = json.dumps(d, sort_keys=True)
        d = _ensure_month(d)
        if json.dumps(d, sort_keys=True) != before:
            _save(d)
        return d


def update(op, gid=None, text=None):
    with _LOCK:
        d = _ensure_month(_load())
        goals = d.setdefault("goals", [])
        if op == "add":
            if text:
                goals.append({"id": _new_id(d), "text": text, "done": False})
        elif op == "toggle":
            for g in goals:
                if g.get("id") == gid:
                    g["done"] = not g.get("done", False)
                    break
        elif op == "edit":
            if text:
                for g in goals:
                    if g.get("id") == gid:
                        g["text"] = text
                        break
        elif op == "remove":
            d["goals"] = [g for g in goals if g.get("id") != gid]
        # unknown op → no-op
        d["updatedAt"] = _now_ms()
        _save(d)
        return d
