"""daycare_leads.py — the Daycare Lead Desk (read-only enrollment-lead visibility).

Why: the 2026-09-12 re-engagement audit found the enrollment leak is human follow-through,
not capture — website leads land in GHL and get one templated text, then tours, call-backs
and replies get dropped. Nothing on the box watched them. This loop does.

What it does, every 15 min on the box (FORGE_MARCUS gate lives in connector.main):
  1. Pages the daycare GHL location's contacts (daycare_ghl.iter_contacts) and keeps the
     new-inquiry leads (`form-type-new-inquiry` / `website-lead`, written by the brand-kit
     website/api/enroll.js), plus untagged webchat/phone contacts nobody has answered yet.
  2. Reads each lead's conversation messages + GHL tasks and derives, with the pure
     `derive()` below: stage NEW → CONTACTED → RESPONDED, or NEEDS_HUMAN with reasons;
     source (`source-*`), center (`loc-*`), first-response time (auto) and first human
     reply, open/overdue call task.
  3. Saves marcus_state/daycare_leads.json; `view()` serves /api/daycare/leads, `kpis()`
     the dashboard numbers, `needs_human()` the Owner Actions list.
  4. When a lead NEWLY needs a human, posts ONE owner alert (agent_bus + Telegram), deduped
     per lead+reason episode, only 8am–9pm ET.

Hard limits (CLAUDE.md rule 2 + the daycare creed): ZERO Claude calls, sends NOTHING to
families, writes NOTHING to GHL (GET only), claims NO facts (no availability, price or
licensing text). The only writes are its own state file and the owner alert. Logs carry
ids + counts only — never a family's name, phone or message text. Message bodies are read
only to spot an opt-out ("STOP") and are never stored.

Stdlib only.
"""
from __future__ import annotations

import html
import json
import os
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import daycare_ghl
import forge_atomic
import forge_heartbeat
import forge_ops
import seller_classify

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_leads.json"
_LOCK = threading.Lock()

INTERVAL = int(os.environ.get("FORGE_DAYCARE_LEADS_INTERVAL", "900"))   # 15 min
ET = ZoneInfo("America/New_York")
OPEN_HOUR, CLOSE_HOUR = 8, 21          # 8am–9pm ET — same window enroll.js texts in
UNANSWERED_SEC = 15 * 60               # business-hours seconds before a reply is overdue
LOOKBACK_DAYS = 90                     # form leads quiet longer than this leave the desk
CHAT_DAYS = 30                         # untagged chat/phone contacts: recent only
ALERT_KEEP_DAYS = 120                  # prune old alert-dedupe keys
CONV_LOOKUPS = 50                      # per-sweep GETs for leads outside the 100-thread window

LEAD_TAGS = {"form-type-new-inquiry", "website-lead"}
# Existing families (Family Contact Form, one-tap enroll, dashboard sync) — never leads.
FAMILY_TAGS = {"daycare family", "family-contact-form", "form-type-existing-family",
               "enrolled", "existing-student"}
QUEUED_TAG = "speed-to-lead-queued"    # enroll.js: overnight text held for the 8am flush
PREF_CALL_TAG = "pref-call-30"         # enroll.js: "call me in the next 30 minutes"
# Custom-field ids from enroll.js GHL_FIELD (plain identifiers, not secrets).
CF_PARENT_FIRST = "N3T1MeOASolGi2rJbqb6"   # smsParentFirst — parent_first_name merge field
CF_STL_SENT = "jIvSMjidWtTzVwD6kbw3"       # speedToLeadSent — contact.speed_to_lead_sent
# ASSUMPTION (GHL message `source`): these mark automated sends (the speed-to-lead
# workflow, campaigns, bulk sends). Any other outbound — including one with no source —
# counts as a human reply, which errs toward FEWER false "needs human" alarms.
AUTO_SOURCES = {"workflow", "campaign", "bulk_actions", "automation"}

CENTER_LABEL = {
    "loc-921-n-18th": "921 N 18th St",
    "loc-2318-cecil-b-moore": "2318 Cecil B Moore",
    "loc-1923-cecil-b-moore": "1923 Cecil B Moore (AMT)",
}
# code -> (owner-facing reason, title verb, Owner Actions priority). Order = priority.
REASONS = {
    "pref_call": ("Asked for a call within 30 min — no reply logged yet", "Call", "URGENT"),
    "unanswered": ("Parent message unanswered 15+ min (business hours)", "Reply to", "URGENT"),
    "overdue_task": ("GHL call task is overdue", "Call", "REVENUE"),
    "sms_queued": ("Auto-text queued overnight — not sent yet", "Check on", "NORMAL"),
}
_PRIORITY_RANK = {"URGENT": 0, "REVENUE": 1, "CUSTOMER": 2, "NORMAL": 3}


# ── pure helpers ──────────────────────────────────────────────────────────────
def _sec(v):
    """GHL timestamp (epoch s/ms number or digit string, or ISO-8601) -> epoch seconds."""
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)) or str(v).strip().isdigit():
            n = float(v)
            return n / 1000 if n > 1e11 else n
        dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return None


def _ms(s):
    return int(s * 1000) if s is not None else None


def _tags(contact):
    return {str(t).strip().lower() for t in (contact.get("tags") or [])}


def in_hours(now):
    """True inside 8am–9pm America/New_York."""
    return OPEN_HOUR <= datetime.fromtimestamp(now, ET).hour < CLOSE_HOUR


def business_secs(start, end):
    """Seconds of [start, end) that fall inside 8am–9pm ET (DST-correct: zoneinfo
    recomputes the offset for each day's wall-clock open/close)."""
    total = 0.0
    day = datetime.fromtimestamp(start, ET).replace(hour=0, minute=0, second=0, microsecond=0)
    while day.timestamp() < end:
        lo = max(start, day.replace(hour=OPEN_HOUR).timestamp())
        hi = min(end, day.replace(hour=CLOSE_HOUR).timestamp())
        total += max(0.0, hi - lo)
        day += timedelta(days=1)
    return total


def _events(messages):
    """Normalize GHL messages -> sorted [(t, direction, human, TYPE, body)].

    Activity rows are skipped. A picked-up inbound call (ASSUMPTION: meta.call.status or
    status == "completed") is itself the human reply, so it also yields a human outbound.
    """
    ev = []
    for m in messages or []:
        t = _sec(m.get("dateAdded") or m.get("date"))
        d = m.get("direction")
        mtype = str(m.get("messageType") or m.get("type") or "").upper()
        if t is None or d not in ("inbound", "outbound") or "ACTIVITY" in mtype:
            continue
        auto = str(m.get("source") or "").lower() in AUTO_SOURCES
        ev.append((t, d, d == "outbound" and not auto, mtype, m.get("body") or ""))
        call = (m.get("meta") or {}).get("call") or {}
        if d == "inbound" and "CALL" in mtype and (call.get("status") or m.get("status")) == "completed":
            ev.append((t, "outbound", True, mtype, ""))
    ev.sort(key=lambda e: e[0])   # stable: an inbound stays before its synthetic reply
    return ev


def _reason(code, since, anchor=""):
    return {"code": code, "text": REASONS[code][0], "since": _ms(since), "anchor": str(anchor)}


def derive(contact, messages, tasks, now, kind="form"):
    """Pure: one lead's desk row from its raw GHL contact + messages + tasks at `now`
    (epoch seconds). No I/O. Timestamps out are epoch ms; durations are seconds.
    messages=None means the thread could not be read (history unknown): reasons that
    hinge on "no reply seen" are withheld — missing data never pages the owner."""
    known = messages is not None
    tags = _tags(contact)
    cf = daycare_ghl._cf_map(contact)
    cid = str(contact.get("id") or "")
    ev = _events(messages)
    created = _sec(contact.get("dateAdded") or contact.get("createdAt")) or (ev[0][0] if ev else now)
    outs = [e[0] for e in ev if e[1] == "outbound"]
    ins = [e for e in ev if e[1] == "inbound"]
    humans = [e[0] for e in ev if e[2]]
    marker = _sec(cf.get(CF_STL_SENT))
    queued = QUEUED_TAG in tags
    # First response: the first outbound we can see; else the speed-to-lead marker (the
    # workflow sends ~3 min after it) — unless the text is still queued overnight.
    first_resp = outs[0] if outs else (marker if marker and not queued else None)
    tasks = [t for t in (tasks or []) if isinstance(t, dict)]
    open_tasks = sorted(((_sec(t.get("dueDate")), t) for t in tasks if not t.get("completed")
                         and _sec(t.get("dueDate")) is not None), key=lambda x: x[0])
    done_task = any(t.get("completed") for t in tasks)
    last_in = ins[-1] if ins else None
    opted_out = bool(last_in and seller_classify.is_opt_out(last_in[4]))

    reasons = []
    if known and PREF_CALL_TAG in tags and not humans and not done_task:
        reasons.append(_reason("pref_call", created))
    if (last_in and not opted_out and not any(h >= last_in[0] for h in humans)
            and business_secs(last_in[0], now) >= UNANSWERED_SEC):
        reasons.append(_reason("unanswered", last_in[0], anchor=_ms(last_in[0])))
    overdue = [(d, t) for d, t in open_tasks if d < now]
    if overdue:
        reasons.append(_reason("overdue_task", overdue[0][0], anchor=overdue[0][1].get("id") or ""))
    if known and queued and not outs:
        reasons.append(_reason("sms_queued", created))

    responded = bool(outs) and any(e[0] > outs[0] for e in ins)
    stage = ("NEEDS_HUMAN" if reasons else "RESPONDED" if responded
             else "CONTACTED" if (outs or marker) else "NEW")

    # GHL first_name is the CHILD (enroll.js); daycare_ghl resolves the parent from the
    # parent-name custom field, handling pre-2026-07-21 contacts too.
    parent = (daycare_ghl._family_from_contact(contact).get("parent_name")
              or str(cf.get(CF_PARENT_FIRST) or "").strip())
    loc = next((t for t in sorted(tags) if t.startswith("loc-")), "")
    src = next((t[len("source-"):] for t in sorted(tags) if t.startswith("source-")), "")
    location_id = contact.get("locationId") or ""
    return {
        "contactId": cid,
        "kind": kind,
        "parentName": parent,
        "center": CENTER_LABEL.get(loc) or loc or "Center unknown",
        "centerTag": loc,
        "source": src or (kind if kind != "form" else "unknown"),
        "createdAt": _ms(created),
        "stage": stage,
        "reasons": reasons,
        "firstResponseSec": max(0, int(first_resp - created)) if first_resp is not None else None,
        "firstHumanSec": max(0, int(humans[0] - created)) if humans else None,
        "lastInboundAt": _ms(last_in[0]) if last_in else None,
        "lastOutboundAt": _ms(outs[-1]) if outs else None,
        "openTask": ({"dueAt": _ms(open_tasks[0][0]), "overdue": open_tasks[0][0] < now}
                     if open_tasks else None),
        "optedOut": opted_out,
        "historyKnown": known,
        "ghlUrl": (f"https://app.gohighlevel.com/v2/location/{location_id}/contacts/detail/{cid}"
                   if location_id and cid else ""),
    }


def _chat_kind(messages):
    """'chat' / 'phone' for an untagged contact that reached us by webchat or call and
    that no human has answered yet; None otherwise (answered, or not a chat/call)."""
    ev = _events(messages)
    if any(e[2] for e in ev):
        return None
    types = [e[3] for e in ev if e[1] == "inbound"]
    if any("CHAT" in t for t in types):
        return "chat"
    if any("CALL" in t or "VOICEMAIL" in t for t in types):
        return "phone"
    return None


def kpis(leads=None, now=None):
    """New Leads 7d/30d (meta vs organic), median response times, needs-human count.
    With no args, reads the saved desk."""
    if leads is None:
        leads = _load().get("leads") or []
    now = now or time.time()

    def recent(days):
        return [l for l in leads if l.get("createdAt") and now - l["createdAt"] / 1000 <= days * 86400]

    def window(days):
        rows = recent(days)
        meta = sum(1 for l in rows if l.get("source") == "meta-ad")
        organic = sum(1 for l in rows if l.get("source") == "organic")
        return {"total": len(rows), "meta": meta, "organic": organic,
                "other": len(rows) - meta - organic}

    last30 = recent(30)
    auto = [l["firstResponseSec"] for l in last30 if l.get("firstResponseSec") is not None]
    human = [l["firstHumanSec"] for l in last30 if l.get("firstHumanSec") is not None]
    stages = {}
    for l in leads:
        stages[l.get("stage")] = stages.get(l.get("stage"), 0) + 1
    return {
        "newLeads7d": window(7),
        "newLeads30d": window(30),
        "medianResponseSec": int(statistics.median(auto)) if auto else None,
        "medianHumanResponseSec": int(statistics.median(human)) if human else None,
        "responseSample": len(auto),
        "humanSample": len(human),
        "needsHuman": stages.get("NEEDS_HUMAN", 0),
        "stages": stages,
    }


def needs_human(state=None, now=None):
    """Owner Actions feed: [{id, title, why, ageSec, priority, contactId, ...}], most
    urgent first. ageSec = seconds since the top reason began (recomputed per call)."""
    st = state if state is not None else _load()
    now = now or time.time()
    items = []
    for lead in st.get("leads") or []:
        if lead.get("stage") != "NEEDS_HUMAN" or not lead.get("reasons"):
            continue
        top = lead["reasons"][0]
        _text, verb, priority = REASONS[top["code"]]
        who = lead.get("parentName") or "new family"
        items.append({
            "id": "daycare-lead:" + lead["contactId"],
            "title": f"{verb} {who} — {lead.get('center')}",
            "why": "; ".join(r["text"] for r in lead["reasons"]),
            "ageSec": max(0, int(now - (top.get("since") or lead.get("createdAt") or now * 1000) / 1000)),
            "priority": priority,
            "contactId": lead["contactId"],
            "business": "daycare",
            "center": lead.get("center"),
            "reasons": [r["code"] for r in lead["reasons"]],
            "ghlUrl": lead.get("ghlUrl") or "",
        })
    items.sort(key=lambda i: (_PRIORITY_RANK.get(i["priority"], 9), -i["ageSec"]))
    return items


# ── owner alerts (internal notification — never family contact) ──────────────
def _alert_key(lead, reason):
    return f"{lead['contactId']}:{reason['code']}:{reason.get('anchor') or ''}"


def _notify(text, data, key):
    """One bus alert to the operator + the same line on Telegram. agent_bus alone does not
    reach Telegram (its notifier only forwards known event types), so this mirrors the
    watchdog: bus for the dashboard record, telegram_io.send for the phone."""
    import agent_bus
    agent_bus.send("daycare_leads", "operator", "alert", text, data)
    try:
        import telegram_io
        telegram_io.send(html.escape(text), dedupe_key="daycare-lead:" + key)
    except Exception:  # noqa: BLE001 — Telegram is best-effort; the bus record stands
        pass


def process_alerts(st, leads, now, send=None):
    """Alert ONCE per lead+reason episode when a lead newly needs a human. 8am–9pm ET only;
    outside the window new episodes are NOT recorded, so they alert at 8am if still open.
    First-ever run seeds the backlog silently plus one summary line. Mutates st; returns
    the number of alerts sent."""
    send = send or _notify
    alerted = st.setdefault("alerted", {})
    fresh = []
    for lead in leads:
        new = [r for r in lead.get("reasons") or [] if _alert_key(lead, r) not in alerted]
        if new:                           # reasons exist only on NEEDS_HUMAN leads
            fresh.append((lead, new))
    stamp = _ms(now)
    sent = 0
    if not st.get("seeded"):
        for lead, new in fresh:
            for r in new:
                alerted[_alert_key(lead, r)] = stamp
        st["seeded"] = True
        if fresh and in_hours(now):
            send(f"Daycare Lead Desk is live: {len(fresh)} lead(s) need a human — "
                 "open the Daycare dashboard.", {"type": "daycare_lead_summary",
                                                 "count": len(fresh)}, "seed")
            sent = 1
    elif in_hours(now):
        for lead, new in fresh:
            who = (lead.get("parentName") or "").split(" ")[0] or "A new family"
            send(f"Daycare lead needs you: {who} ({lead.get('center')}) — "
                 + "; ".join(r["text"] for r in new),
                 {"type": "daycare_lead", "contactId": lead["contactId"],
                  "reasons": [r["code"] for r in new]},
                 _alert_key(lead, new[0]))
            for r in new:
                alerted[_alert_key(lead, r)] = stamp
            sent += 1
    cutoff = stamp - ALERT_KEEP_DAYS * 86400 * 1000
    st["alerted"] = {k: v for k, v in alerted.items() if v >= cutoff}
    return sent


# ── I/O: GHL reads (GET only) + state ────────────────────────────────────────
def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 — missing/corrupt state = fresh desk
        return {}


def _messages(client, conv):
    if not conv or not conv.get("id"):
        return []
    data = client.get(f"/conversations/{conv['id']}/messages", {"limit": 100})
    raw = data.get("messages", data) if isinstance(data, dict) else data
    if isinstance(raw, dict):
        raw = raw.get("messages", [])
    return [m for m in (raw or []) if isinstance(m, dict)]


def _tasks(client, contact_id):
    data = client.get(f"/contacts/{contact_id}/tasks")
    return [t for t in ((data.get("tasks") if isinstance(data, dict) else None) or [])
            if isinstance(t, dict)]


def _conversation(client, contact_id):
    """One contact's newest conversation (GET), or {} when it has none."""
    data = client.get("/conversations/search", {
        "locationId": client.location_id, "contactId": contact_id, "limit": 1,
        "sortBy": "last_message_date"})
    convs = (data.get("conversations") if isinstance(data, dict) else None) or []
    return convs[0] if convs and isinstance(convs[0], dict) else {}


def _retry_after(e):
    """Seconds GHL asked us to wait on a 429 (Retry-After, delta-seconds), else one interval."""
    try:
        return min(max(1, int(str(e.headers.get("Retry-After")).strip())), 86400)
    except (AttributeError, TypeError, ValueError):
        return INTERVAL


def collect(client, now):
    """Read the daycare GHL location -> (lead rows, per-lead fetch failures). GET only."""
    contacts = list(daycare_ghl.iter_contacts(client))
    convs = client.get("/conversations/search", {
        "locationId": client.location_id, "limit": 100, "sortBy": "last_message_date"})
    by_contact = {}
    for c in (convs.get("conversations") if isinstance(convs, dict) else None) or []:
        by_contact.setdefault(c.get("contactId"), c)      # newest conversation wins
    leads, failed, lookups = [], 0, 0
    for contact in contacts:
        contact.setdefault("locationId", client.location_id)
        cid = contact.get("id")
        tags = _tags(contact)
        conv = by_contact.get(cid)
        last_at = _sec((conv or {}).get("lastMessageDate")) or 0
        created = _sec(contact.get("dateAdded")) or 0
        try:
            if tags & FAMILY_TAGS:
                continue                  # an enrolled family is not a lead any more
            if tags & LEAD_TAGS:
                if max(created, last_at) < now - LOOKBACK_DAYS * 86400:
                    continue
                if conv is None and lookups < CONV_LOOKUPS:
                    lookups += 1          # thread older than the location-wide window
                    conv = _conversation(client, cid)       # {} = looked: no thread at all
                msgs = _messages(client, conv) if conv is not None else None  # None = unknown
                leads.append(derive(contact, msgs, _tasks(client, cid), now))
            elif (conv and not any(t.startswith(daycare_ghl.LOCATION_PREFIX) for t in tags)
                  and last_at >= now - CHAT_DAYS * 86400):
                msgs = _messages(client, conv)
                kind = _chat_kind(msgs)
                if kind:
                    leads.append(derive(contact, msgs, [], now, kind=kind))
        except Exception as e:  # noqa: BLE001 — one bad lead never kills the sweep...
            if getattr(e, "code", None) == 429:
                raise                     # ...but a rate limit does: stop hammering GHL
            failed += 1
    leads.sort(key=lambda l: (l["stage"] != "NEEDS_HUMAN", -(l.get("createdAt") or 0)))
    return leads, failed


def run_once(client, now=None, send=None):
    """One sweep: read GHL, derive, save, alert. Returns the saved state."""
    now = now or time.time()
    error = None
    leads = failed = backoff = None
    if client is None or not getattr(client, "configured", False):
        error = "Daycare GHL not configured — add GHL_API_KEY + GHL_LOCATION_ID to daycare.env."
    else:
        held = _load()
        if now < (held.get("backoffUntil") or 0) / 1000:
            return held       # inside GHL's Retry-After: zero GETs; the 429 error stands
        try:
            leads, failed = collect(client, now)
        except Exception as e:  # noqa: BLE001 — type + HTTP code only; never a body/token
            code = getattr(e, "code", None)
            error = f"GHL read failed: {type(e).__name__}{f' {code}' if code else ''}"
            if code == 429:
                backoff = _retry_after(e)
                error += f" — rate-limited, backing off {backoff}s"
    with _LOCK:
        st = _load()
        st["lastRunAt"] = _ms(now)
        st["backoffUntil"] = _ms(now + backoff) if backoff else None
        if leads is not None:
            st["leads"] = leads
            st["kpis"] = kpis(leads, now)
            st["lastOkAt"] = _ms(now)
            error = f"{failed} lead(s) could not be read this sweep" if failed else None
            try:
                process_alerts(st, leads, now, send)
            except Exception as e:  # noqa: BLE001 — an alert failure never loses the sweep
                error = f"alert failed: {type(e).__name__}"
        st["error"] = error          # on failure the previous leads stay, marked stale
        forge_atomic.atomic_write_json(STATE, st)
    print(f"[daycare_leads] sweep: {len(leads) if leads is not None else 'n/a'} leads, "
          f"{(st.get('kpis') or {}).get('needsHuman', 0)} need a human"
          + (f", error: {error}" if error else ""))
    return st


def view():
    """GET /api/daycare/leads payload. Reads state only — no network on the request path."""
    st = _load()
    leads = st.get("leads") or []
    error = st.get("error")
    if not st.get("lastRunAt"):
        error = error or ("Lead Desk has not run yet — it reads GHL every 15 min on the box "
                          "(loops are off on a UI-only machine).")
    return {
        "ok": True,
        "kpis": kpis(leads),
        "leads": leads,
        "needsHuman": needs_human(st),
        "lastRunAt": st.get("lastRunAt"),
        "lastOkAt": st.get("lastOkAt"),
        "error": error,
    }


def run_forever(client):
    """Background loop (thread name `daycare_leads`). Skips work while the crew is
    clocked out; beats the heartbeat every tick either way."""
    last = (_load().get("lastRunAt") or 0) / 1000
    time.sleep(max(0, min(INTERVAL, last + INTERVAL - time.time())))   # deploys restart often
    while True:
        err = None
        try:
            if not forge_ops.paused():
                err = run_once(client).get("error")
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        forge_heartbeat.beat("daycare_leads", INTERVAL, "Daycare Lead Desk", error=err)
        time.sleep(INTERVAL)
