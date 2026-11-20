#!/usr/bin/env python3
"""On-time payment streaks -> one line per confirmed payment in #daycare-payments.

The database does the streak math (`payment_streak_events`, one row per invoice). This lane only
reads the rows not posted yet (`streak_events_unposted`), posts each through `slack_io.send`, and
stamps it (`streak_mark_posted`) after Slack took it. Nothing else: no texts, no CRM, no money.

Inert unless ALL of these hold:
- the box loop runs (FORGE_MARCUS=1, FORGE_DAYCARE_STREAK_SLACK != 0),
- Slack is on (FORGE_CHAT_TRANSPORT both|slack),
- #daycare-payments is bound (env SLACK_CHANNEL_DAYCARE_PAYMENTS or `/forge bind daycare-payments`).
  No fallback to #forge-daycare: an unbound room means no post and no database call.
- the database has an eligible event (a center with streak_mode off writes none).

A Touch of Blessings only. A Mother's Touch (1923) rows are never posted (the database excludes
them too). Parent name only, never a child's name.
"""

from __future__ import annotations

import html
import logging
import time
from datetime import date
from decimal import Decimal

import daycare_ghl
import daycare_supabase
import slack_io

_log = logging.getLogger("daycare_streak_slack")

ROOM = "daycare-payments"          # slack_io.TOPICS key
KEY = "daycare-pay:"               # dedupe prefix; slack_io routes it to ROOM
# ponytail: slack_io forgets a dedupe key after 15 min, so a tick must come back sooner than that
# for a failed stamp to be retried without a second post. If the stamp keeps failing for longer,
# the line can post twice; move to a local posted-ids file if that ever shows up.
INTERVAL = 300
LIMIT = 20

_SESSION = None                    # the lane's own login, kept between ticks (dropped on any error)


def _money(value) -> str:
    return f"${Decimal(str(value)):,.2f}"


def _pct(value) -> str:
    """10.00 -> '10', 12.50 -> '12.5'."""
    return f"{Decimal(str(value)).normalize():f}"


def _day(value) -> str:
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        return "unknown"
    return f"{day:%b} {day.day}"


def next_tier(streak: int, tiers):
    """The first (min_streak, pct) above `streak`, or None at the top tier."""
    return next(((k, pct) for k, pct in sorted(tiers) if k > streak), None)


def compose(event: dict, tiers=daycare_supabase.DEFAULT_STREAK_TIERS) -> str:
    """One feed line for one streak event. Pure. Telegram-HTML (slack_io converts it)."""
    name = html.escape(str(event.get("parent_name") or "").strip()[:60] or "A family")
    week = _day(event.get("week_of") or event.get("due_on"))
    paid = event.get("paid_amount")
    has_amount = paid is not None and Decimal(str(paid)) > 0
    if not event.get("on_time"):
        if not has_amount:         # the nightly miss job: nothing was paid
            return f"Missed payment — {name} — week of {week} — streak reset to 0"
        return f"Late payment — {name} — {_money(paid)} — week of {week} — streak reset to 0"
    streak = int(event.get("streak_after") or 0)
    nxt = next_tier(streak, tiers)
    if nxt:
        tail = f" (next: {_pct(nxt[1])}% at {nxt[0]})"
    else:
        tier = Decimal(str(event.get("tier_pct_after") or 0))
        tail = f" (top tier: {_pct(tier)}%)" if tier > 0 else ""
    amount = _money(paid) if has_amount else "$0.00"
    return f"Payment confirmed — {name} — {amount} — week of {week} — streak {streak}{tail}"


def ready() -> bool:
    """Slack is on and the payments room has its own channel. Never raises."""
    try:
        return slack_io.mode() != "telegram" and bool(slack_io.topic_channel(ROOM))
    except Exception:  # noqa: BLE001
        return False


def _postable(event) -> bool:
    """Fail closed: a row we cannot place at an ATOB center is not posted."""
    loc = str(event.get("location_id") or "")
    return bool(event.get("id")) and bool(loc) and not loc.startswith(daycare_ghl.AMT_LOCATION_PREFIX) \
        and event.get("slack_eligible", True) is not False


def run_once(session_fn) -> dict:
    """One tick: post every unposted event, stamp each one only after Slack returned True."""
    global _SESSION
    out = {"ok": True, "posted": 0, "skipped": 0, "failed": 0}
    if not ready():
        return {**out, "inert": True}
    try:
        if _SESSION is None:
            _SESSION = session_fn()
        session = _SESSION
        if session is None:
            return {**out, "ok": False, "error": "no daycare session"}
        rows = daycare_supabase.billing_rpc(session, "streak_events_unposted", {"p_limit": LIMIT}, write=False)
        tiers = {}
        for event in rows if isinstance(rows, list) else []:
            if not isinstance(event, dict) or not _postable(event):
                out["skipped"] += 1
                continue
            loc = str(event["location_id"])
            if loc not in tiers:
                tiers[loc] = daycare_supabase.streak_tiers(session, loc)
            if not slack_io.send(compose(event, tiers[loc]), business="daycare", dedupe_key=KEY + str(event["id"])):
                out["failed"] += 1                    # not stamped: the next tick tries again
                continue
            daycare_supabase.billing_rpc(session, "streak_mark_posted", {"p_event": event["id"]})
            out["posted"] += 1
    except Exception as error:  # noqa: BLE001 — a failed tick posts nothing more and starts clean next time
        _SESSION = None
        _log.warning("streak feed tick failed: %s", type(error).__name__)
        return {**out, "ok": False, "error": type(error).__name__}
    return out


def run_forever(session_fn, interval: int = INTERVAL):
    """Box loop (thread `daycare_streak_slack`, FORGE_MARCUS=1 only)."""
    import forge_heartbeat
    import forge_ops
    while True:
        err = None
        try:
            if not forge_ops.paused():
                summary = run_once(session_fn)
                err = summary.get("error")
                if summary.get("posted") or summary.get("failed"):
                    print(f"[streak_slack] posted={summary['posted']} failed={summary['failed']} "
                          f"skipped={summary['skipped']}", flush=True)
        except Exception as error:  # noqa: BLE001 — one failure never kills the loop
            err = type(error).__name__
        forge_heartbeat.beat("daycare_streak_slack", interval, "Billing · Payment streak feed", error=err)
        time.sleep(interval)
