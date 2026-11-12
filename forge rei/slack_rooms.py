"""slack_rooms.py — the daycare channels in Slack, organized by site.

  Per site (the specifics), A Touch of Blessings only:
    #daycare-921  / #daycare-2318              new leads + parent replies (stage "New Lead")
    #921-tours    / #2318-tours                tours booked, tour reminders (stage "Tour Scheduled")
    #921-quotes   / #2318-quotes               application / tuition quote sent (stage "Application Sent")
    #921-enrolled / #2318-enrolled             new enrollments + start dates to confirm
  #amt-1923  A Mother's Touch alerts only (separate legal entity; not a room).
  All sites (the overview): #daycare-alerts / -tours / -quotes / -starting / -enrolled get the 8 AM and
  6 PM briefs only (slack_briefs), never single events. #forge-daycare = per-site brief + anything urgent
  or not provably tied to a site.

Zero Claude calls, zero GHL calls, zero n8n runs: it only reads what the box lanes already
hold (daycare_pipeline state, daycare_calendar.view, /starts) and posts to Slack.
  on_refresh()  daycare_pipeline.refresh calls it after each read: a family that changed stage
                gets one line in its site's channel for the new stage, with buttons. A family with no
                provable site gets no line (the brief counts it). The first read after a site channel
                is created posts that channel's roster once (seed). Then the briefs tick.
  roster()      the current list for a room or site channel: `/forge roster`, or the Roster button.
  draft()       the "Draft reply" button: asks Solomon; his text comes back as a ✅ card.
Site is proven from the boards (site_of / _card_site), never from alert text. A Mother's Touch is a
separate legal entity: never posted in an ATOB room or site channel.
Slack-only (rooms don't exist in Telegram); inert while FORGE_CHAT_TRANSPORT=telegram.
"""
from __future__ import annotations

import html
import re
import threading

import slack_io

BOARD = "enrollment"                       # ATOB. Never "amt".
STAGE_TOPIC = {"new lead": "alerts", "tour scheduled": "tours", "application sent": "quotes",
               "enrolled": "enrolled"}
TOPIC_STAGE = {v: k for k, v in STAGE_TOPIC.items()}
TITLE = {"alerts": "🆕 New leads", "tours": "🗓 Tours", "quotes": "📄 Application / quote sent",
         "starting": "🚀 Starting soon", "enrolled": "✅ Enrolled"}
MAX_EVENTS = 8                             # per refresh: a bulk GHL edit must not flood a room
MAX_ROWS = 25
_STATE = "slack_rooms.json"
_LOCK = threading.Lock()


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def _test(name) -> bool:
    return str(name or "").strip().lower().startswith("zz")


def _room(topic):
    return slack_io.topic_channel(f"daycare-{topic}")


def _ghl_url(location_id, contact_id):
    if location_id and contact_id:
        return f"https://app.gohighlevel.com/v2/location/{location_id}/contacts/detail/{contact_id}"
    return None


def _buttons(topic, contact_id=None, location_id=None):
    row = []
    if contact_id:
        row.append({"text": "✍️ Draft reply", "callback_data": f"draft:{contact_id}"})
        url = _ghl_url(location_id, contact_id)
        if url:
            row.append({"text": "Open in GHL", "url": url})
    row.append({"text": "📋 Roster", "callback_data": f"cmd:roster {topic}"})
    return [row]


# ── rosters ───────────────────────────────────────────────────────────────────
def _stage_cards(stage_name):
    import daycare_pipeline
    v = daycare_pipeline.view(board=BOARD)
    col = next((c for c in v.get("stages") or [] if c["name"].strip().lower() == stage_name), None)
    cards = [c for c in (col or {}).get("cards") or [] if not _test(c.get("name"))]
    return cards, v.get("error") if col is None or v.get("stale") else None


def _days(ms, now_ms):
    return f"{max(0, int((now_ms - ms) / 86400000))}d" if ms else "?"


def roster(topic, now=None) -> tuple[str, list]:
    """-> (Telegram-HTML text, buttons) for one room. Never raises."""
    import time
    topic = str(topic or "").strip().lower()
    site, sub = split_site(topic)
    if site and (not sub or sub in SUB_STAGE):
        return site_roster(site, sub)
    if topic not in TITLE:
        return ("Which list? <code>/forge roster tours</code> (all sites: alerts · tours · quotes · starting · "
                "enrolled) or <code>/forge roster atob-one-tours</code> (921: atob-one, 2318: atob-two; "
                "add -tours · -quotes · -enrolled)", [])
    now_ms = int((now or time.time()) * 1000)
    lines, note = [], None
    try:
        if topic in ("starting", "tours"):        # the board proves the family's site, never a center label
            sites, why = site_cards(None)
            if sites is None:
                return (f"<b>{TITLE[topic]}</b>\n⚠️ {why} Tap Refresh on the dashboard board, then try again.", [])
            proven = {c.get("contactId") for by in sites.values() for cs in by.values() for c in cs}
        if topic == "starting":
            import daycare_starts
            v = daycare_starts.view()
            rows = [r for r in (v.get("starts") if isinstance(v, dict) else v) or []
                    if r.get("status") != "sent" and r.get("contactId") in proven
                    and not _test(r.get("childName") or r.get("parentName"))]
            from datetime import datetime, timezone, timedelta
            today = (datetime.fromtimestamp(now_ms / 1000, timezone.utc) - timedelta(hours=5)).date().isoformat()  # ET, ±1 h
            soon = [r for r in rows if (r.get("startDate") or "") >= today]
            past = len(rows) - len(soon)
            lines = [f"• {_esc(r.get('childName') or r.get('parentName') or '?')} — {_esc(r.get('startDate') or '?')} "
                     f"({_esc(r.get('status') or '?')})" for r in soon[:MAX_ROWS]]
            if past:
                lines.append(f"\n{past} more have a start date already past and unconfirmed — fix them on the dashboard.")
            return ("\n".join([f"<b>{TITLE[topic]}</b> — {len(soon)}"] + (lines or ["Nobody has a start date set."])),
                    _buttons(topic))
        if topic == "tours":
            import daycare_calendar
            v = daycare_calendar.view()
            for u in [u for u in v.get("upcoming") or [] if u.get("kind") == "tour"
                      and u.get("contactId") in proven][:MAX_ROWS]:
                at = (u.get("time") or "")[11:16]
                lines.append(f"• {_esc(u['date'])}{' ' + at if at else ''} {_esc(u.get('tag') or '')} "
                             f"{_esc(u.get('who') or 'name not loaded yet')}".rstrip())
            note = v.get("error")
            head = f"<b>{TITLE[topic]}</b> — next 14 days: {len(lines)}"
        cards, err = _stage_cards(TOPIC_STAGE[topic]) if topic in TOPIC_STAGE else ([], None)
        if topic == "tours":
            lines.append(f"\nIn stage Tour Scheduled: {len(cards)}")
        else:
            head = f"<b>{TITLE[topic]}</b> — {len(cards)}"
            lines += [f"• {_esc(c['name'])} · {_days(c.get('updatedAt') or c.get('createdAt'), now_ms)}"
                      for c in cards[:MAX_ROWS]]
            if len(cards) > MAX_ROWS:
                lines.append(f"…and {len(cards) - MAX_ROWS} more on the dashboard board.")
        note = note or err
    except Exception as e:  # noqa: BLE001
        return (f"<b>{TITLE[topic]}</b>\n⚠️ Couldn't read it ({type(e).__name__}).", [])
    if note:
        lines.append(f"⚠️ {_esc(str(note)[:160])}")
    return ("\n".join([head] + (lines or ["Nobody here right now."])), _buttons(topic))


SITE_TITLE = {"atob-one": "🏠 ATOB · 921 N 18th", "atob-two": "🏠 ATOB · 2318 Cecil B. Moore"}
SITE_SHORT = {"atob-one": "921", "atob-two": "2318"}
SUB_STAGE = {"tours": "tour scheduled", "quotes": "application sent", "enrolled": "enrolled"}
STAGE_SUB = {v: k for k, v in SUB_STAGE.items()}
_SITE_SKIP = ("lost", "not interested")           # closed-out stages are not a site's working list


def split_site(topic):
    """"atob-one-tours" -> ("atob-one", "tours"); "atob-two" -> ("atob-two", None); else (None, None)."""
    t = str(topic or "").strip().lower()
    site = next((x for x in SITE_TITLE if t == x or t.startswith(x + "-")), None)
    return (site, t[len(site) + 1:] or None) if site else (None, None)


def site_target(site, stage_name):
    """-> (channel, roster topic) for a family of this site that just entered this stage. The site's
    sub-channel (tours / quotes / enrolled) when bound, else the site channel; (None, None) when the
    site has no channel at all. New Lead goes to the site channel itself."""
    sub = STAGE_SUB.get(str(stage_name or "").strip().lower())
    if sub:
        ch = slack_io.topic_channel(f"daycare-{site}-{sub}")
        if ch:
            return ch, f"{site}-{sub}"
    ch = slack_io.topic_channel(f"daycare-{site}")
    return (ch, site) if ch else (None, None)


def _card_site(c):
    """The ATOB site a board card proves (exactly one ATOB loc- tag, no AMT mark), else None."""
    tags = {x for x in (c.get("centers") or [c.get("center")]) if x}
    return SITE_BY_CENTER.get(next(iter(tags))) if len(tags) == 1 and not _amt_card(c) else None


def site_cards(site=None):
    """-> ({stage name: [cards]}, error) of ATOB families at one site (or keyed by site when site is None:
    {site: {stage: [cards]}}), test families hidden. Same proof as site_of; None cards when either board
    has never been read (fail closed: an unread AMT board proves nothing)."""
    import daycare_pipeline
    v = daycare_pipeline.view(board=BOARD)
    amt, atob = _board_contacts("amt"), _board_contacts(BOARD)
    if amt is None or atob is None:
        return None, "Can't prove which families are ATOB yet (a board hasn't been read)."
    out = {}
    for col in v.get("stages") or []:
        for c in col.get("cards") or []:
            where = _card_site(c)
            if where and not _test(c.get("name")) and c.get("contactId") not in amt and (site is None or where == site):
                out.setdefault(where, {}).setdefault(col["name"], []).append(c)
    return (out if site is None else out.get(site, {})), (v.get("error") if v.get("stale") or v.get("error") else None)


def site_roster(site, sub=None) -> tuple[str, list]:
    """-> (text, buttons): the ATOB families at ONE site, by stage (or one stage for a sub-channel).
    A card counts only when its single ATOB loc- tag is this site's, it has no AMT mark, and the AMT
    board does not hold the contact. Never raises."""
    title = SITE_TITLE[site] + (f" · {sub}" if sub else "")
    topic = f"{site}-{sub}" if sub else site
    try:
        by_stage, note = site_cards(site)
        if by_stage is None:
            return (f"<b>{title}</b>\n⚠️ {note} Tap Refresh on the dashboard board, then try again.", [])
        lines, total = [], 0
        for name, mine in by_stage.items():
            low = name.strip().lower()
            if low in _SITE_SKIP or (sub and low != SUB_STAGE[sub]):
                continue
            total += len(mine)
            names = ", ".join(_esc(c["name"]) for c in mine[:6]) + (f" +{len(mine) - 6}" if len(mine) > 6 else "")
            lines.append(f"• <b>{_esc(name)}</b> {len(mine)} — {names}")
        if note:
            lines.append(f"⚠️ {_esc(str(note)[:160])}")
        return ("\n".join([f"<b>{title}</b> — {total} families"] + (lines or ["Nobody here right now."])),
                [[{"text": "📋 Roster", "callback_data": f"cmd:roster {topic}"}]])
    except Exception as e:  # noqa: BLE001
        return (f"<b>{title}</b>\n⚠️ Couldn't read it ({type(e).__name__}).", [])


# ── A Mother's Touch never enters a room ──────────────────────────────────────
_AMT_TEXT = re.compile(r"\bAMT\b|\b1923\b|Mother.{0,3}s Touch", re.I)


def _board_contacts(board):
    """-> the board's contact ids, or None when that board has never been read (cannot tell)."""
    import daycare_pipeline
    st = daycare_pipeline._load(board)
    if not st.get("fetchedAt"):
        return None
    return {c.get("contactId") for c in st.get("cards") or [] if c.get("contactId")}


def room_ok(dedupe_key, text) -> bool:
    """May this mirrored daycare alert go to a room? Only when it is PROVABLY A Touch of Blessings:
    a contact id inside its dedupe key (leads, replies, tours carry one) is on the ATOB board, the
    AMT board has been read and does not hold it, and the text names neither AMT nor 1923.
    Anything else (no id, unread board, unknown family) stays in the main daycare channel."""
    if _AMT_TEXT.search(str(text or "")):
        return False
    ids = set(re.findall(r"[A-Za-z0-9]{12,}", str(dedupe_key or "")))
    atob, amt = _board_contacts(BOARD), _board_contacts("amt")
    if not ids or atob is None or amt is None or not ids & atob or ids & amt:
        return False
    import daycare_pipeline                    # ANY AMT tag on an ATOB card still fails closed
    return not any(_amt_card(c) for c in daycare_pipeline._load(BOARD).get("cards") or []
                   if c.get("contactId") in ids)


def _amt_card(c) -> bool:
    """A board card that carries any A Mother's Touch mark (entity-amt or a 1923 loc- tag, even
    next to an ATOB one)."""
    return bool(c.get("amt")) or any("1923" in str(t) for t in (c.get("centers") or []) + [c.get("center") or ""])


SITE_BY_CENTER = {"loc-921-n-18th": "atob-one", "loc-2318-cecil-b-moore": "atob-two"}


def site_of(dedupe_key, text) -> str | None:
    """Which site channel a daycare alert belongs in, proven from the boards, never from its text
    (a parent's quoted words can name any address): "amt" when its contact is on the AMT board and
    not the ATOB one; "atob-one"/"atob-two" when room_ok passes and the family's ATOB card carries
    exactly that site's loc- tag. None = cannot prove it (it stays in its room / #forge-daycare)."""
    ids = set(re.findall(r"[A-Za-z0-9]{12,}", str(dedupe_key or "")))
    atob, amt = _board_contacts(BOARD), _board_contacts("amt")
    if not ids or atob is None or amt is None:
        return None
    if ids & amt and not ids & atob:
        return "amt"
    if not room_ok(dedupe_key, text):
        return None
    import daycare_pipeline
    cards = [c for c in daycare_pipeline._load(BOARD).get("cards") or [] if c.get("contactId") in ids]
    centers = {t for c in cards for t in (c.get("centers") or [c.get("center")])}    # exactly one ATOB tag
    return SITE_BY_CENTER.get(centers.pop()) if len(centers) == 1 and not any(map(_amt_card, cards)) else None


# ── stage moves + first-run seed ──────────────────────────────────────────────
def on_refresh(after, location_id=None, board=BOARD) -> int:
    """after = the ATOB board's cards from one GHL read. A family whose stage differs from the last
    one ANNOUNCED (slack_rooms.json, so the owner's own dashboard moves count too) gets one line in its
    site's channel for the new stage (site_target). A family with no provable site gets no line (the
    brief counts it). First run only records the snapshot. Then the 8 AM / 6 PM briefs tick.
    -> messages posted. Never raises."""
    try:
        if board != BOARD or slack_io.mode() == "telegram":
            return 0
        sent = _seed() + _moves(after, location_id)
    except Exception as e:  # noqa: BLE001 — a room post never blocks the pipeline lane
        print(f"[slack_rooms] on_refresh failed: {type(e).__name__}", flush=True)
        sent = 0
    try:
        import slack_briefs
        sent += slack_briefs.tick()
    except Exception as e:  # noqa: BLE001
        print(f"[slack_rooms] briefs failed: {type(e).__name__}", flush=True)
    return sent


def _moves(after, location_id) -> int:
    amt = _board_contacts("amt")
    if amt is None:                            # AMT board never read: cannot prove anyone is ATOB yet. Wait:
        return 0                               # nothing is announced, so the moves post once it has been read.
    sent = 0
    with _LOCK:
        st = slack_io._read(_STATE)
        known = st.get("announced")
        now_map = {c["opportunityId"]: (c.get("stageName") or "") for c in after if c.get("opportunityId")}
        if known is None:                      # first run: nothing to compare against
            st["announced"] = now_map
            slack_io._write(_STATE, st)
            return 0
        posts = []
        for c in after:
            oid = c.get("opportunityId")
            if not oid or now_map[oid] == known.get(oid) or now_map[oid].strip().lower() not in STAGE_TOPIC:
                continue
            site = _card_site(c)               # one ATOB loc- tag, no AMT mark
            if not site or c.get("contactId") in amt:
                continue
            ch, topic = site_target(site, now_map[oid])
            if ch:
                posts.append((c, ch, topic))
        failed = set()
        for c, ch, topic in posts[:MAX_EVENTS]:
            was = known.get(c["opportunityId"])
            # A ZZ test family still posts (marked), so a real GHL move can be checked end to end
            # without touching a real family. Rosters and briefs keep hiding them.
            text = (("🧪 test family · " if _test(c.get("name")) else "")
                    + f"<b>{_esc(c['name'])}</b> → {_esc(c['stageName'])}"
                    + (f" (was {_esc(was)})" if was else " (new)"))
            if slack_io.send(text, channel=ch, buttons=_buttons(topic, c.get("contactId"), location_id),
                             dedupe_key=f"room:{c['opportunityId']}:{c.get('stageId')}"):
                sent += 1
            else:
                failed.add(c["opportunityId"])           # stays un-announced: retried next read
        if len(posts) > MAX_EVENTS:
            slack_io.send(f"…and {len(posts) - MAX_EVENTS} more stage changes this round — see the "
                          "dashboard board.", channel=slack_io.chat_for("daycare"))
        st["announced"] = {k: (known[k] if k in failed and k in known else v)
                           for k, v in now_map.items() if k not in failed or k in known}
        slack_io._write(_STATE, st)
    return sent


def _seed() -> int:
    """Post each site channel's roster once, the first time it has a channel. The shared rooms are
    brief-only and are not seeded. A failed post (bot not in the channel, archived) is retried at most
    once an hour."""
    import time
    sent, now = 0, time.time()
    with _LOCK:
        st = slack_io._read(_STATE)
        seeded, tried = st.setdefault("seeded", {}), st.setdefault("seedTried", {})
        dirty = False
        for topic in [x for site in SITE_TITLE for x in (site, *(f"{site}-{u}" for u in SUB_STAGE))]:
            room = slack_io.topic_channel(f"daycare-{topic}")
            if not room or seeded.get(topic) == room or now - (tried.get(topic) or 0) < 3600:
                continue
            text, buttons = roster(topic)
            if "Can't prove" in text:            # boards not read yet: try again on a later read
                continue
            if slack_io.send(text, channel=room, buttons=buttons):
                seeded[topic] = room
                sent += 1
            else:
                tried[topic] = now
            dirty = True
        if dirty:
            slack_io._write(_STATE, st)
    return sent


# ── the Draft reply button ────────────────────────────────────────────────────
def draft(contact_id, channel, user) -> None:
    """Ask Solomon for a reply to this family. He reads the thread himself; a send is a ✅ card."""
    import daycare_pipeline
    import slack_inbound
    cards = (daycare_pipeline._load(BOARD).get("cards") or [])
    card = next((c for c in cards if c.get("contactId") == str(contact_id)), None)
    post = slack_inbound._poster(channel)
    if not re.fullmatch(r"[A-Za-z0-9]{6,40}", str(contact_id or "")):
        card = None
    if not card:
        post("That family is no longer on the board. Tap 📋 Roster for the current list.")
        return
    # Only the id goes in: this text runs with the owner's authority, and a family name is typed
    # by a parent on a web form. Solomon looks the family up himself through his tools.
    slack_inbound._turn(f"slack:{channel}", "solomon",
                        f"Draft a reply text to the family on GHL contact {contact_id}. Read their thread "
                        "first. Queue it as a card for my tap. Do not send.", post, user)
