"""slack_rooms.py — the daycare rooms in Slack: one channel per kind of enrollment news.

  #daycare-alerts    new leads + parent replies that need the owner   (stage "New Lead")
  #daycare-tours     tours booked, tour reminders                     (stage "Tour Scheduled")
  #daycare-quotes    application / tuition quote sent                 (stage "Application Sent")
  #daycare-starting  start dates to confirm                           (daycare_starts)
  #daycare-enrolled  new enrollments                                  (stage "Enrolled")

Zero Claude calls, zero GHL calls, zero n8n runs: it only reads what the box lanes already
hold (daycare_pipeline state, daycare_calendar.view, /starts) and posts to Slack.
  on_refresh()  daycare_pipeline.refresh calls it after each read: a family that changed stage
                gets one line in the new stage's room, with buttons. The first read after a
                room is created posts that room's roster once (seed).
  roster()      the current list for a room: `/forge roster` in the room, or the Roster button.
  draft()       the "Draft reply" button: asks Solomon; his text comes back as a ✅ card.
A Touch of Blessings board only. A Mother's Touch is a separate legal entity: never posted here.
Slack-only (rooms don't exist in Telegram); inert while FORGE_CHAT_TRANSPORT=telegram.
"""
from __future__ import annotations

import html
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
    if topic not in TITLE:
        return ("Which room? <code>/forge roster tours</code> (alerts · tours · quotes · starting · enrolled)", [])
    now_ms = int((now or time.time()) * 1000)
    lines, note = [], None
    try:
        if topic == "starting":
            import telegram_agent
            out = telegram_agent.quick("/starts", "", "slack", "daycare")
            body = "\n".join(ln for ln in (out[0] if out else "").split("\n")[1:] if "ZZChild" not in ln)
            return (f"<b>{TITLE[topic]}</b>\n{body or 'Nobody has a start date set.'}", _buttons(topic))
        if topic == "tours":
            import daycare_calendar
            v = daycare_calendar.view()
            for u in [u for u in v.get("upcoming") or [] if u.get("kind") == "tour"][:MAX_ROWS]:
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


# ── stage moves + first-run seed ──────────────────────────────────────────────
def on_refresh(before, after, location_id=None, board=BOARD) -> int:
    """before/after = the board's cards before and after one GHL read (before=None on the very
    first read: nothing to compare, so no events). -> messages posted. Never raises."""
    try:
        if board != BOARD or slack_io.mode() == "telegram":
            return 0
        sent = _seed()
        old = {c.get("opportunityId"): (c.get("stageName") or "") for c in before or []}
        if not old:                        # first read (or an empty board): nothing to compare
            return sent
        moved = [c for c in after
                 if c.get("opportunityId") and not _test(c.get("name"))
                 and (c.get("stageName") or "") != old.get(c["opportunityId"])
                 and STAGE_TOPIC.get((c.get("stageName") or "").strip().lower())]
        for c in moved[:MAX_EVENTS]:
            topic = STAGE_TOPIC[c["stageName"].strip().lower()]
            room = _room(topic)
            if not room:
                continue
            was = old.get(c["opportunityId"])
            text = (f"<b>{_esc(c['name'])}</b> → {_esc(c['stageName'])}"
                    + (f" (was {_esc(was)})" if was else " (new)"))
            if slack_io.send(text, channel=room, buttons=_buttons(topic, c.get("contactId"), location_id),
                             dedupe_key=f"room:{c['opportunityId']}:{c.get('stageId')}"):
                sent += 1
        if len(moved) > MAX_EVENTS:
            hq = slack_io.chat_for("daycare")
            slack_io.send(f"…and {len(moved) - MAX_EVENTS} more stage changes this round — see the dashboard board.",
                          channel=hq)
        return sent
    except Exception as e:  # noqa: BLE001 — a room post never blocks the pipeline lane
        print(f"[slack_rooms] on_refresh failed: {type(e).__name__}", flush=True)
        return 0


def _seed() -> int:
    """Post each room's roster once, the first time that room has a channel."""
    sent = 0
    with _LOCK:
        st = slack_io._read(_STATE)
        seeded = st.setdefault("seeded", {})
        for topic in TITLE:
            room = _room(topic)
            if not room or seeded.get(topic) == room:
                continue
            text, buttons = roster(topic)
            if slack_io.send(text, channel=room, buttons=buttons):
                seeded[topic] = room
                sent += 1
        if sent:
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
    if not card:
        post("That family is no longer on the board. Tap 📋 Roster for the current list.")
        return
    slack_inbound._turn(f"slack:{channel}", "solomon",
                        f"Draft a reply text to the family of {card['name']} (GHL contact {contact_id}, "
                        f"stage {card.get('stageName') or 'unknown'}). Read their thread first. "
                        "Queue it as a card for my tap. Do not send.", post, user)
