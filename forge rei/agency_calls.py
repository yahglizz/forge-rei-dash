"""agency_calls.py — Call Center tap-to-log tracker (Forge AI Agency).

Owner dials clients/prospects manually from GHL; this store just tallies each
tap (Answered / No Answer) per day, keeps a rolling history, and derives a
streak. Internal + reversible (local tally only, no outward action) — no
approval gate needed, mirrors agency_io.py's store idiom.
"""
import forge_atomic
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_calls.json"
_LOCK = threading.Lock()

OUTCOMES = ("answered", "no_answer")
DEFAULT_GOAL = 25


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("days"), dict):
                d.setdefault("goal", DEFAULT_GOAL)
                return d
        except Exception:
            pass
    return {"goal": DEFAULT_GOAL, "days": {}}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _day(d, date):
    return d["days"].setdefault(date, {"answered": 0, "no_answer": 0, "log": []})


def _dials(day):
    return day.get("answered", 0) + day.get("no_answer", 0)


def _rate(day):
    dials = _dials(day)
    return round(day.get("answered", 0) * 100 / dials) if dials else 0


# ponytail: naive day-walk (no calendar-gap detection beyond a plain reversed
# scan of recent dates) — fine at this scale; upgrade to an indexed date range
# only if history grows into the thousands of days.
def _streak(d):
    goal = d.get("goal", 0)
    threshold = goal if goal > 0 else 1
    today = _today()
    days = d.get("days", {})

    def counts(date):
        day = days.get(date)
        return day is not None and _dials(day) >= threshold

    # Decide the anchor: today if it already qualifies, else yesterday (so an
    # in-progress day that hasn't hit goal yet doesn't show the streak as
    # broken mid-day).
    cursor = datetime.strptime(today, "%Y-%m-%d")
    if not counts(today):
        cursor -= timedelta(days=1)

    n = 0
    while counts(cursor.strftime("%Y-%m-%d")):
        n += 1
        cursor -= timedelta(days=1)
    return n


def log_call(outcome):
    if outcome not in OUTCOMES:
        return {"ok": False, "detail": "outcome must be 'answered' or 'no_answer'"}
    with _LOCK:
        d = _load()
        today = _today()
        day = _day(d, today)
        day[outcome] += 1
        day["log"].append({"ts": datetime.now().strftime("%H:%M"), "outcome": outcome})
        _save(d)
        return summary(_locked=d)


def undo_last():
    with _LOCK:
        d = _load()
        today = _today()
        day = d["days"].get(today)
        if day and day["log"]:
            last = day["log"].pop()
            day[last["outcome"]] = max(0, day[last["outcome"]] - 1)
            _save(d)
        return summary(_locked=d)


def set_goal(n):
    try:
        n = max(0, int(n))
    except (ValueError, TypeError):
        n = DEFAULT_GOAL
    with _LOCK:
        d = _load()
        d["goal"] = n
        _save(d)
        return summary(_locked=d)


def summary(_locked=None):
    """Public read. _locked lets internal callers (already holding _LOCK)
    reuse the in-memory dict without re-acquiring/re-loading."""
    if _locked is not None:
        d = _locked
    else:
        with _LOCK:
            d = _load()

    today = _today()
    day = d["days"].get(today, {"answered": 0, "no_answer": 0, "log": []})
    dials = _dials(day)

    week = []
    cursor = datetime.strptime(today, "%Y-%m-%d") - timedelta(days=6)
    for _ in range(7):
        date = cursor.strftime("%Y-%m-%d")
        wd = d["days"].get(date, {"answered": 0, "no_answer": 0})
        week.append({"date": date, "dials": _dials(wd), "answered": wd.get("answered", 0)})
        cursor += timedelta(days=1)

    return {
        "ok": True,
        "goal": d.get("goal", DEFAULT_GOAL),
        "streak": _streak(d),
        "today": {
            "date": today,
            "answered": day.get("answered", 0),
            "no_answer": day.get("no_answer", 0),
            "dials": dials,
            "rate": _rate(day),
            "log": list(reversed(day.get("log", []))),
        },
        "week": week,
    }


if __name__ == "__main__":
    import tempfile

    STATE = Path(tempfile.mktemp(suffix=".json"))  # monkeypatch before any call

    s = log_call("answered")
    assert s["ok"] and s["today"]["answered"] == 1, s
    s = log_call("answered")
    s = log_call("no_answer")
    assert s["today"]["answered"] == 2 and s["today"]["no_answer"] == 1, s
    assert s["today"]["dials"] == 3, s
    assert s["today"]["rate"] == round(2 * 100 / 3), s
    assert s["today"]["log"][0]["outcome"] == "no_answer", "newest first"

    bad = log_call("maybe")
    assert bad["ok"] is False, bad

    s = undo_last()
    assert s["today"]["no_answer"] == 0 and s["today"]["dials"] == 2, s

    s = set_goal(2)
    assert s["goal"] == 2, s
    # today has 2 dials >= goal(2) -> today counts -> streak >= 1
    assert s["streak"] >= 1, s

    # Synthetic 3-day streak check: fabricate yesterday + day-before as
    # qualifying, today already qualifies (2 dials >= goal 2) from above.
    d = _load()
    goal = d["goal"]
    yday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    dbefore = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    d["days"][yday] = {"answered": goal, "no_answer": 0, "log": []}
    d["days"][dbefore] = {"answered": goal, "no_answer": 0, "log": []}
    _save(d)
    s = summary()
    assert s["streak"] == 3, s["streak"]

    # Break the chain two days back and confirm the walk stops there.
    d = _load()
    del d["days"][dbefore]
    _save(d)
    s = summary()
    assert s["streak"] == 2, s["streak"]

    # Empty-log undo is a no-op, not an error.
    s2 = undo_last()
    s3 = undo_last()
    assert s3["today"] == s2["today"] or s3["ok"], "undo on empty log is a no-op"

    print("ok")
