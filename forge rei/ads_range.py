"""ads_range.py — ONE date-range resolver for every ads surface, matching Meta Ads Manager's picker.

Semantics (verified against Ads Manager 2026-10-17: "Last 30 days" = Sep 17 – Oct 16):
  today                 today only (partial day)
  yesterday             yesterday
  today_and_yesterday   yesterday – today (partial)
  last_Nd               N COMPLETE days ending YESTERDAY (today excluded)
  this_week             Sunday of this week – today (Meta's this_week_sun_today, partial)
  last_week             the previous Sunday – Saturday
  this_month            the 1st – today (partial)
  last_month            the whole previous calendar month
  maximum               the account's first day (created_time, account tz) – today, clamped to
                        Meta's 37-month retention floor. Unknown created date → the floor itself.
  custom                since/until validated: since <= until, since not in the future, until
                        clamped to today, since clamped to the 37-month floor (clamped:true).

"Today" is the AD ACCOUNT's day (the daycare account reports America/New_York), never the
server's: the box runs UTC, so after ~8pm Eastern the server is already "tomorrow".
Stdlib only, pure functions. Self-check: python3 ads_range.py
"""
from __future__ import annotations

import datetime as dt
import os

PRESETS = ("today", "yesterday", "today_and_yesterday", "last_7d", "last_14d", "last_28d",
           "last_30d", "last_90d", "this_week", "last_week", "this_month", "last_month", "maximum")
LABELS = {"today": "Today", "yesterday": "Yesterday", "today_and_yesterday": "Today and yesterday",
          "last_7d": "Last 7 days", "last_14d": "Last 14 days", "last_28d": "Last 28 days",
          "last_30d": "Last 30 days", "last_90d": "Last 90 days", "this_week": "This week",
          "last_week": "Last week", "this_month": "This month", "last_month": "Last month",
          "maximum": "Maximum", "custom": "Custom"}
MAX_MONTHS = 37
_DAYS_PRESET = {7: "last_7d", 14: "last_14d", 28: "last_28d", 30: "last_30d", 90: "last_90d"}


def _months_back(d: dt.date, months: int) -> dt.date:
    y, m = divmod(d.year * 12 + (d.month - 1) - months, 12)
    m += 1
    for day in (d.day, 30, 29, 28):             # clamp Mar 31 → Feb 28/29
        try:
            return dt.date(y, m, day)
        except ValueError:
            continue
    raise ValueError("bad date")


def account_today(tz_name: str | None = None, now: dt.datetime | None = None) -> tuple[dt.date, str, bool]:
    """(today in the account's zone, tz label, fell_back). Falls back to FORGE_TZ_OFFSET hours."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return now.astimezone(ZoneInfo(tz_name)).date(), tz_name, False
        except Exception:  # noqa: BLE001 — bad name / no tzdata → fixed offset, said out loud
            pass
    try:
        off = float(os.environ.get("FORGE_TZ_OFFSET") or -4)
    except ValueError:
        off = -4.0
    return (now + dt.timedelta(hours=off)).date(), f"UTC{off:+g} (FORGE_TZ_OFFSET fallback)", True


def _d(v) -> dt.date:
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])


def resolve(preset: str | None = None, since=None, until=None, tz_name: str | None = None,
            today: dt.date | None = None, earliest=None, days=None) -> dict:
    """→ {since, until, label, preset, tz, days, partialToday, clamped, tzFallback}.
    `days` is the legacy N-day knob (last N complete days). Raises ValueError on bad input."""
    fallback = False
    tz = tz_name or ""
    if today is None:
        today, tz, fallback = account_today(tz_name)
    floor = _months_back(today, MAX_MONTHS)
    clamped = False
    p = (preset or "").strip().lower() or None
    if p is None and (since or until):
        p = "custom"
    if p is None and days not in (None, ""):
        n = int(days)
        if not 1 <= n <= 1200:
            raise ValueError("days must be 1-1200")
        p = _DAYS_PRESET.get(n) or "custom"
        if p == "custom":
            since, until = today - dt.timedelta(days=n), today - dt.timedelta(days=1)
    p = p or "last_30d"
    y = today - dt.timedelta(days=1)
    if p == "today":
        s, u = today, today
    elif p == "yesterday":
        s, u = y, y
    elif p == "today_and_yesterday":
        s, u = y, today
    elif p.startswith("last_") and p.endswith("d") and p[5:-1].isdigit():
        n = int(p[5:-1])
        s, u = today - dt.timedelta(days=n), y
    elif p == "this_week":
        s, u = today - dt.timedelta(days=(today.weekday() + 1) % 7), today
    elif p == "last_week":
        sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)
        s, u = sun - dt.timedelta(days=7), sun - dt.timedelta(days=1)
    elif p == "this_month":
        s, u = today.replace(day=1), today
    elif p == "last_month":
        u = today.replace(day=1) - dt.timedelta(days=1)
        s = u.replace(day=1)
    elif p == "maximum":
        s, u = floor, today
        if earliest:
            e = _d(earliest)
            s = max(e, floor)
    elif p == "custom":
        if not since or not until:
            raise ValueError("custom range needs since and until")
        s, u = _d(since), _d(until)
        if s > today:
            raise ValueError("since is in the future")
        if s > u:
            raise ValueError("since is after until")
        if u > today:
            u, clamped = today, True
    else:
        raise ValueError(f"unknown preset {preset!r}")
    if s < floor:
        s, clamped = floor, True
    label = LABELS.get(p) or (f"Last {p[5:-1]} days" if p.startswith("last_") else p)
    return {"since": s.isoformat(), "until": u.isoformat(), "label": label, "preset": p,
            "tz": tz, "days": (u - s).days + 1, "partialToday": u == today,
            "clamped": clamped, "tzFallback": fallback}


def previous(rng: dict) -> dict:
    """Meta's compare period: the same number of days immediately before `since`."""
    s, u = _d(rng["since"]), _d(rng["until"])
    pu = s - dt.timedelta(days=1)
    ps = pu - (u - s)
    return {"since": ps.isoformat(), "until": pu.isoformat(), "label": "Previous period",
            "preset": "previous", "tz": rng.get("tz"), "days": (pu - ps).days + 1,
            "partialToday": False, "clamped": False, "tzFallback": rng.get("tzFallback", False)}


def delta_pct(cur, prev):
    """% change, or None when it is undefined (prev missing / 0) — never a fake 0 or ∞."""
    try:
        cur, prev = float(cur), float(prev)
    except (TypeError, ValueError):
        return None
    if prev == 0:
        return None
    return round((cur - prev) / prev * 100, 1)


if __name__ == "__main__":
    r = resolve("last_30d", today=dt.date(2026, 10, 17), tz_name="America/New_York")
    assert (r["since"], r["until"]) == ("2026-09-17", "2026-10-16"), r
    print("ok", r)
