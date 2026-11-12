"""slack_briefs.py — the daycare briefs in Slack, 8 AM and 6 PM Eastern.

  #forge-daycare        one line per site (921, 2318, A Mother's Touch): counts only, plus how many
                        families have no site tag. The main chat = the overview.
  #daycare-alerts       all sites: new leads (New Lead stage), new since the last brief
  #daycare-tours        all sites: tours today + tomorrow, and how many are in Tour Scheduled
  #daycare-quotes       all sites: Application Sent, oldest first
  #daycare-starting     all sites: start dates in the next 7 days, past ones still unconfirmed
  #daycare-enrolled     all sites: enrolled count, new since the last brief
The shared rooms get ONLY these briefs; single events go to the site channels (slack_rooms).
A room with nothing to say is skipped. The evening brief counts what changed since the morning one.

Zero Claude calls, zero GHL calls, zero n8n runs: it reads the box lanes' own state (daycare_pipeline,
daycare_calendar, daycare_starts) — this is code, not the scheduled Claude briefs that are OFF.
Ticked from slack_rooms.on_refresh (every pipeline read, ~5 min on the box): a slot posts once, any
time in the 4 hours after it starts (box restarts don't lose it, a late box doesn't post a stale one).
A Touch of Blessings rows use slack_rooms.site_cards (board-proven site, AMT guard, fails closed when a
board was never read). A Mother's Touch shows as counts from its own board, in #forge-daycare only.
Slack-only; inert while FORGE_CHAT_TRANSPORT=telegram.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import slack_io

SLOTS = (("am", 8, "☀️ Morning brief"), ("pm", 18, "🌙 Evening brief"))
WINDOW_H = 4
MAX_NAMES = 6
_STATE = "slack_briefs.json"               # {"done": {"2026-11-12-am": ts}, "snap": {opportunityId: stage}}
_LOCK = threading.Lock()
ROOMS = ("alerts", "tours", "quotes", "starting", "enrolled")


def _et(now):
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(now, ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001 — no tz database: EST, off by an hour in summer at worst
        from datetime import timezone
        return datetime.fromtimestamp(now, timezone(timedelta(hours=-5)))


def due(now=None):
    """-> (slot id, title) for the slot whose window is open now, else None. Says nothing about done."""
    et = _et(now or time.time())
    for name, hour, title in SLOTS:
        if hour <= et.hour < hour + WINDOW_H:
            return f"{et.date().isoformat()}-{name}", title
    return None


def tick(now=None) -> int:
    """Post the open slot's briefs once. -> messages posted. Never raises."""
    try:
        now = now or time.time()
        if slack_io.mode() == "telegram":
            return 0
        slot = due(now)
        if not slot:
            return 0
        with _LOCK:
            st = slack_io._read(_STATE)
            if slot[0] in (st.get("done") or {}):
                return 0
            built = build(now, st.get("snap"), slot[1])
            if built is None:                  # a board was never read: try again on the next read
                return 0
            posts, snap = built
            sent, failed = 0, False
            for channel, text in posts:
                if slack_io.send(text, channel=channel):
                    sent += 1
                else:
                    failed = True
            if failed and not sent:            # Slack down: the next read retries the whole slot
                return 0
            done = {k: v for k, v in (st.get("done") or {}).items() if v > now - 7 * 86400}
            done[slot[0]] = int(now)
            st.update(done=done, snap=snap)
            slack_io._write(_STATE, st)
            return sent
    except Exception as e:  # noqa: BLE001 — a brief never blocks the pipeline lane
        print(f"[slack_briefs] tick failed: {type(e).__name__}", flush=True)
        return 0


# ── building the briefs ───────────────────────────────────────────────────────
def _esc(s):
    import html
    return html.escape(str(s or ""), quote=False)


def _names(cards):
    names = [_esc(c.get("name")) for c in cards[:MAX_NAMES]]
    return ", ".join(names) + (f" +{len(cards) - MAX_NAMES}" if len(cards) > MAX_NAMES else "")


def _stage(by_stage, stage):
    return next((v for k, v in by_stage.items() if k.strip().lower() == stage), [])


def _upcoming_tours(et_now, proven):
    """{site: [rows]} of tours today + tomorrow (Eastern) for families whose site the board proves
    (proven = {contactId: site} from slack_rooms.site_cards: one ATOB loc- tag, no AMT mark, not on the
    AMT board). The center label alone never decides: a row without a proven contact is dropped."""
    import daycare_calendar
    days = {et_now.date().isoformat(), (et_now.date() + timedelta(days=1)).isoformat()}
    out = {}
    for u in daycare_calendar.view().get("upcoming") or []:
        site = proven.get(u.get("contactId"))
        if u.get("kind") == "tour" and u.get("date") in days and site:
            out.setdefault(site, []).append(u)
    return out


def _starts(et_now, proven):
    """({site: [rows in the next 7 days]}, {site: past-and-unconfirmed count}), proven families only."""
    import daycare_starts
    v = daycare_starts.view()
    today = et_now.date().isoformat()
    week = (et_now.date() + timedelta(days=7)).isoformat()
    soon, past = {}, {}
    for r in (v.get("starts") if isinstance(v, dict) else v) or []:
        site = proven.get(r.get("contactId"))
        if r.get("status") == "sent" or not site:
            continue
        day = r.get("startDate") or ""
        if today <= day <= week:
            soon.setdefault(site, []).append(r)
        elif day and day < today:
            past[site] = past.get(site, 0) + 1
    return soon, past


def _amt_counts():
    """{stage lower: count} from A Mother's Touch's own board, or None when never read."""
    import daycare_pipeline
    v = daycare_pipeline.view(board="amt")
    if not v.get("fetchedAt"):
        return None
    return {c["name"].strip().lower(): len([x for x in c.get("cards") or []
                                             if not str(x.get("name") or "").lower().startswith("zz")])
            for c in v.get("stages") or []}


def _no_site_count():
    """ATOB families (not test, not AMT-marked) with no provable site, open stages only."""
    import daycare_pipeline
    import slack_rooms
    amt = slack_rooms._board_contacts("amt") or set()
    n = 0
    for col in daycare_pipeline.view(board=slack_rooms.BOARD).get("stages") or []:
        if col["name"].strip().lower() in slack_rooms._SITE_SKIP:
            continue
        n += sum(1 for c in col.get("cards") or [] if not slack_rooms._test(c.get("name"))
                 and not slack_rooms._amt_card(c) and c.get("contactId") not in amt
                 and slack_rooms._card_site(c) is None)
    return n


def build(now, snap, title):
    """-> ([(channel, text)], new snapshot), or None when the boards can't prove a site yet."""
    import slack_rooms
    sites, _note = slack_rooms.site_cards(None)
    if sites is None:
        return None
    et_now = _et(now)
    snap = snap or {}
    fresh = {}                                 # site -> [cards whose stage changed since the last brief]
    new_snap = {}
    for site, by_stage in sites.items():
        for stage, cards in by_stage.items():
            for c in cards:
                oid = c.get("opportunityId")
                if not oid:
                    continue
                new_snap[oid] = stage
                if snap and snap.get(oid) != stage:
                    fresh.setdefault(site, []).append(c)
    proven = {c.get("contactId"): site for site, by in sites.items() for cards in by.values()
              for c in cards if c.get("contactId")}
    tours, (starts, past) = _upcoming_tours(et_now, proven), _starts(et_now, proven)
    head = f"<b>{title}</b> · {et_now.strftime('%a %b %-d')}"
    order = list(slack_rooms.SITE_TITLE)
    short = slack_rooms.SITE_SHORT

    def fresh_in(site, stage):
        return [c for c in fresh.get(site, []) if new_snap.get(c.get("opportunityId"), "").strip().lower() == stage]

    rooms = {r: [] for r in ROOMS}
    for site in order:
        by = sites.get(site, {})
        lead, tour_st = _stage(by, "new lead"), _stage(by, "tour scheduled")
        quote, enr = _stage(by, "application sent"), _stage(by, "enrolled")
        n_new = fresh_in(site, "new lead")
        if lead:
            rooms["alerts"].append(f"• <b>{short[site]}</b> {len(lead)} new lead(s): {_names(lead)}"
                                   + (f" ({len(n_new)} since last brief)" if n_new else ""))
        t = tours.get(site, [])
        if t or tour_st:
            rows = ", ".join(f"{_esc(u.get('date', '')[5:])}{' ' + (u.get('time') or '')[11:16] if u.get('time') else ''} "
                             f"{_esc(u.get('who') or '?')}" for u in t[:MAX_NAMES])
            rooms["tours"].append(f"• <b>{short[site]}</b> {len(t)} tour(s) today/tomorrow"
                                  + (f": {rows}" if rows else "") + f" · {len(tour_st)} in Tour Scheduled")
        if quote:
            oldest = sorted(quote, key=lambda c: c.get("updatedAt") or c.get("createdAt") or 0)
            rooms["quotes"].append(f"• <b>{short[site]}</b> {len(quote)} sent: {_names(oldest)}")
        s, p = starts.get(site, []), past.get(site, 0)
        if s or p:
            rows = ", ".join(f"{_esc(r.get('childName') or r.get('parentName') or '?')} {_esc((r.get('startDate') or '')[5:])}"
                             for r in s[:MAX_NAMES])
            rooms["starting"].append(f"• <b>{short[site]}</b> {len(s)} starting this week" + (f": {rows}" if rows else "")
                                     + (f" · ⚠️ {p} past date unconfirmed" if p else ""))
        n_enr = fresh_in(site, "enrolled")
        if enr or n_enr:
            rooms["enrolled"].append(f"• <b>{short[site]}</b> {len(enr)} enrolled"
                                     + (f", {len(n_enr)} new: {_names(n_enr)}" if n_enr else ""))
    titles = {"alerts": "🆕 New leads", "tours": "🗓 Tours", "quotes": "📄 Quotes sent",
              "starting": "🚀 Starting soon", "enrolled": "✅ Enrolled"}
    posts = []
    for r in ROOMS:
        ch = slack_io.topic_channel(f"daycare-{r}")
        if ch and rooms[r]:
            posts.append((ch, "\n".join([f"{head} — {titles[r]}, all sites"] + rooms[r])))
    # the main chat: one line per site, counts only
    lines = [f"{head} — all sites"]
    for site in order:
        by = sites.get(site, {})
        bits = [f"{len(_stage(by, 'new lead'))} new", f"{len(_stage(by, 'tour scheduled'))} touring",
                f"{len(_stage(by, 'application sent'))} quoted", f"{len(_stage(by, 'enrolled'))} enrolled",
                f"{len(starts.get(site, []))} starting this week"]
        moved = len(fresh.get(site, []))
        lines.append(f"• <b>{short[site]}</b> " + " · ".join(bits) + (f" ({moved} moved since last brief)" if moved else ""))
    amt = _amt_counts()
    if amt is None:
        lines.append("• <b>AMT 1923</b> board not read yet")
    else:
        lines.append("• <b>AMT 1923</b> " + " · ".join(f"{amt.get(k, 0)} {w}" for k, w in (
            ("new lead", "new"), ("tour scheduled", "touring"), ("application sent", "quoted"), ("enrolled", "enrolled"))))
    gap = _no_site_count()
    if gap:
        lines.append(f"⚠️ {gap} ATOB famil{'y has' if gap == 1 else 'ies have'} no site tag — add loc-921-n-18th or "
                     "loc-2318-cecil-b-moore in GHL so they land in a site channel.")
    main = slack_io.chat_for("daycare")
    if main:
        posts.insert(0, (main, "\n".join(lines)))
    return posts, new_snap
