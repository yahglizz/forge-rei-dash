"""daily_goals.py — the daily non-negotiables scoreboard for FORGE REI OS.

Yahjair's grind tracker: fixed daily activity targets (messages, conversations,
calls, offers) that he checks off through the day. Auto-resets at midnight,
archives each day, tracks the streak of complete days and the day-count chasing
the first deal. Stops the clock when the first deal is marked closed.

State persists in marcus_state/daily_goals.json so it survives restarts and the
24/7 server owns the single source of truth.
"""
import forge_atomic
import json
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daily_goals.json"
_LOCK = threading.Lock()

# The non-negotiables to land the first deal. Editable from the dashboard.
DEFAULT_TARGETS = {"messages": 100, "conversations": 10, "calls": 50, "offers": 2}
METRICS = ["messages", "conversations", "calls", "offers"]


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _load():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {
        "date": None,
        "startDate": None,
        "dayNumber": 0,
        "targets": dict(DEFAULT_TARGETS),
        "progress": {k: 0 for k in METRICS},
        "history": [],
        "dealClosed": False,
        "dealClosedDate": None,
    }


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _day_complete(targets, progress):
    return all(progress.get(k, 0) >= targets.get(k, 0) for k in targets)


def _ensure_today(d):
    today = _today()
    if d.get("date") == today:
        return d
    # New day: archive yesterday, reset progress, bump the day counter.
    if d.get("date"):
        d.setdefault("history", []).append({
            "date": d["date"],
            "targets": dict(d.get("targets", {})),
            "progress": dict(d.get("progress", {})),
            "complete": _day_complete(d.get("targets", {}), d.get("progress", {})),
        })
        d["history"] = d["history"][-120:]
    if not d.get("startDate"):
        d["startDate"] = today
    d["dayNumber"] = (d.get("dayNumber") or 0) + 1
    d["date"] = today
    d["progress"] = {k: 0 for k in d.get("targets", DEFAULT_TARGETS)}
    return d


def _streak(d):
    """Consecutive complete days, counting today if already complete."""
    n = 0
    if _day_complete(d.get("targets", {}), d.get("progress", {})):
        n = 1
    for h in reversed(d.get("history", [])):
        if h.get("complete"):
            n += 1
        else:
            break
    return n


def _view(d):
    targets = d.get("targets", DEFAULT_TARGETS)
    progress = d.get("progress", {})
    per = {}
    done_count = 0
    for k in METRICS:
        t = targets.get(k, 0)
        p = progress.get(k, 0)
        complete = p >= t and t > 0
        if complete:
            done_count += 1
        per[k] = {"target": t, "progress": p, "complete": complete,
                  "pct": min(100, int(p * 100 / t)) if t else 0}
    completed_days = sum(1 for h in d.get("history", []) if h.get("complete"))
    if _day_complete(targets, progress):
        completed_days += 1
    return {
        "date": d.get("date"),
        "startDate": d.get("startDate"),
        "dayNumber": d.get("dayNumber", 1),
        "metrics": METRICS,
        "targets": targets,
        "perMetric": per,
        "metricsDone": done_count,
        "metricsTotal": len(METRICS),
        "dayComplete": _day_complete(targets, progress),
        "streak": _streak(d),
        "completedDays": completed_days,
        "dealClosed": d.get("dealClosed", False),
        "dealClosedDate": d.get("dealClosedDate"),
    }


def get():
    with _LOCK:
        d = _ensure_today(_load())
        _save(d)
        return _view(d)


def apply_auto(counts):
    """Merge GHL-derived activity counts into today's progress as a FLOOR: auto
    fills the numbers, a manual bump can still exceed them, and auto never drops a
    number back down (counts only grow through the day). counts: {metric: int}."""
    with _LOCK:
        d = _ensure_today(_load())
        d.setdefault("auto", {})
        for k, v in (counts or {}).items():
            if k not in METRICS:
                continue
            try:
                v = max(0, int(v))
            except (ValueError, TypeError):
                continue
            d["auto"][k] = v
            d["progress"][k] = max(d["progress"].get(k, 0), v)
        d["autoSyncedAt"] = int(time.time() * 1000)
        _save(d)
        return _view(d)


def update(metric=None, delta=None, value=None, targets=None, deal_closed=None):
    with _LOCK:
        d = _ensure_today(_load())
        if targets:
            for k, v in targets.items():
                if k in METRICS:
                    try:
                        d["targets"][k] = max(0, int(v))
                    except (ValueError, TypeError):
                        pass
            for k in d["targets"]:
                d["progress"].setdefault(k, 0)
        if metric and metric in d.get("targets", {}):
            cur = d["progress"].get(metric, 0)
            if value is not None:
                try:
                    cur = max(0, int(value))
                except (ValueError, TypeError):
                    pass
            elif delta is not None:
                try:
                    cur = max(0, cur + int(delta))
                except (ValueError, TypeError):
                    pass
            d["progress"][metric] = cur
        if deal_closed is not None:
            d["dealClosed"] = bool(deal_closed)
            d["dealClosedDate"] = _today() if deal_closed else None
        _save(d)
        return _view(d)
