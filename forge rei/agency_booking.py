"""agency_booking.py — ClientForge "Book a call" (Calendly-style) backend. Stdlib only.

A prospect opens /book (book.html, served by the public-safe PortalHandler), picks a slot
and leaves their details. We store the booking, block the slot, and — only when Google is
connected — insert an event on the "ClientForge Calls" calendar (sendUpdates=none, no
attendees: Google emails nobody). WE SEND NOTHING to the prospect (Rule 2): the confirm
page + its .ics is the confirmation. The owner gets a guarded Telegram ping.

Policy: forge-agency/config/booking.json (same shape as forge-daycare/config/tours.json,
one location "agency"), falling back to DEFAULTS. Slot math is google_io's pure `slots()`.
State: marcus_state/agency_bookings.json (FORGE_AGENCY_BOOKINGS_STATE overrides, for tests).

Contract: every public call returns {"ok": True, …} or {"ok": False, "error": code,
"message": text}; nothing raises into the HTTP handlers. No AI calls anywhere.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import forge_atomic
import google_io

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE.parent / "forge-agency" / "config" / "booking.json"
STATE = Path(os.environ.get("FORGE_AGENCY_BOOKINGS_STATE") or HERE / "marcus_state" / "agency_bookings.json")
LOC = "agency"

DEFAULTS = {
    "title": "Free 30-min growth call",
    "host": "Yahjair · ClientForge",
    "description": "A quick call about your business: what is working, what is not, and whether "
                   "a new website, ads, or a booking system would help. No pitch deck, no obligation.",
    "calendarName": "ClientForge Calls",
    "timezone": "America/New_York",
    "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "start": "10:00", "end": "17:00",
    "slotMinutes": 30, "bufferMinutes": 15, "minNoticeHours": 4, "daysAhead": 21,
    "closedDates": [],
}
NEEDS = ("website", "ads", "booking", "other")
RATE_MAX, RATE_WINDOW = 5, 3600          # create attempts per IP per hour
# Global ceiling across ALL visitors — even a rate-limit bypass can't flood the calendar.
GLOBAL_HOUR, GLOBAL_DAY = 20, 40         # successful bookings per rolling hour / 24 h
CAPS = {"name": 80, "business": 120, "email": 254, "phone": 32, "website": 200,
        "notes": 1000, "ref": 40, "tz": 64}
# Call Sheet rows a booking may move to demo_booked — never regress proposal/won/lost/dnc.
PRE_DEMO = ("new", "answered", "interested", "no_answer", "callback", "ready")
BUSY_TTL = 60                            # seconds a Google free/busy read is reused for /slots

_EMAIL_RE = re.compile(r"^[^@\s<>\"]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_SITE_RE = re.compile(r"^(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?$", re.I)
_REF_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_LOCK = threading.Lock()                 # state file + the check-then-book critical section
_HITS = {}                               # ip -> [attempt ts]  (in memory; resets on restart)
_BUSY_CACHE = {"at": 0.0, "key": None, "busy": []}


def _log(msg):
    print(f"   [booking] {msg}", flush=True)


# ── policy ────────────────────────────────────────────────────────────────────
def config():
    """DEFAULTS overlaid with booking.json (bad/missing file = defaults), in tours.json shape."""
    cfg = dict(DEFAULTS)
    try:
        d = json.loads(CONFIG_FILE.read_text())
        if isinstance(d, dict):
            cfg.update({k: v for k, v in d.items() if k in DEFAULTS})
    except Exception:  # noqa: BLE001 — missing/unreadable = built-in defaults
        pass
    cfg["locations"] = {LOC: {}}
    return cfg


def public_info(cfg=None):
    """The event-card fields only — nothing about calendars, state or Google."""
    cfg = cfg or config()
    return {"title": str(cfg["title"]), "host": str(cfg["host"]),
            "description": str(cfg["description"]), "durationMin": int(cfg["slotMinutes"]),
            "timezone": str(cfg["timezone"]), "daysAhead": int(cfg["daysAhead"])}


# ── state ─────────────────────────────────────────────────────────────────────
def _load():
    try:
        d = json.loads(STATE.read_text())
        if isinstance(d, dict) and isinstance(d.get("bookings"), list):
            return d
    except Exception:  # noqa: BLE001
        pass
    return {"bookings": []}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _live(d, now):
    return [b for b in d["bookings"] if b.get("status") == "booked" and b.get("end", 0) > now]


# ── Google (only when connected; any failure = local-only, logged) ───────────
def _google_on():
    return google_io.configured() and google_io._token() is not None


def _google_busy(cfg, t0, t1, cache=False):
    """Busy spans from the agency calendar, or [] when Google is off / failing."""
    if not _google_on():
        return []
    key = (int(t0) // 3600, int(t1) // 3600)
    if cache and _BUSY_CACHE["key"] == key and time.time() - _BUSY_CACHE["at"] < BUSY_TTL:
        return list(_BUSY_CACHE["busy"])
    try:
        busy = google_io._busy(google_io._calendar_id(cfg["calendarName"]), t0, t1)
    except Exception as e:  # noqa: BLE001
        _log(f"google free/busy failed, local bookings only: {google_io._fail(e)['error']}")
        return []
    _BUSY_CACHE.update(at=time.time(), key=key, busy=list(busy))
    return busy


def _google_insert(cfg, b):
    """-> (event_id, None) or (None, error text). sendUpdates=none, no attendees."""
    try:
        tz = google_io._tz(cfg)
        cal = google_io._calendar_id(cfg["calendarName"])
        lines = [f"Email: {b['email']}", f"Phone: {b['phone'] or '-'}", f"Website: {b['website'] or '-'}",
                 f"Wants help with: {', '.join(b['need']) or '-'}", f"Notes: {b['notes'] or '-'}",
                 f"Call Sheet: {b['leadId'] or '-'}", "Booked by the prospect on the ClientForge page."]
        body = {"summary": f"ClientForge call — {b['name']} ({b['business']})",
                "description": "\n".join(lines),
                "start": {"dateTime": datetime.fromtimestamp(b["start"], tz).isoformat(), "timeZone": tz.key},
                "end": {"dateTime": datetime.fromtimestamp(b["end"], tz).isoformat(), "timeZone": tz.key},
                "extendedProperties": {"private": {"forgeBookingId": b["id"]}}}
        st, d = google_io._api("POST", f"/calendars/{urllib.parse.quote(cal, safe='')}/events",
                               {"sendUpdates": "none"}, body)
        if st not in (200, 201) or not d.get("id"):
            return None, f"event insert failed ({st}): {google_io._gerr(d)}"
        return d["id"], None
    except Exception as e:  # noqa: BLE001
        return None, google_io._fail(e)["error"]


def _google_delete(cfg, event_id):
    try:
        cal = google_io._calendar_id(cfg["calendarName"])
        q = urllib.parse.quote
        st, d = google_io._api("DELETE", f"/calendars/{q(cal, safe='')}/events/{q(str(event_id), safe='')}",
                               {"sendUpdates": "none"})
        return None if st in (200, 204, 404, 410) else f"cancel failed ({st}): {google_io._gerr(d)}"
    except Exception as e:  # noqa: BLE001
        return google_io._fail(e)["error"]


# ── slots ─────────────────────────────────────────────────────────────────────
def _busy_local(d, now):
    return [(b["start"], b["end"]) for b in _live(d, now)]


def slots(days=None, now=None):
    """Open slots = policy − our bookings − Google busy (when connected). Never raises.
    -> {ok, event:{…public_info}, slots:[{id, start, end}]}"""
    try:
        now = now or time.time()
        cfg = config()
        days = max(1, min(int(days or cfg["daysAhead"]), 60))
        with _LOCK:
            busy = _busy_local(_load(), now)
        cands = google_io.slots(cfg, LOC, busy, now, days)
        if cands:
            buf = int(cfg["bufferMinutes"]) * 60
            gb = _google_busy(cfg, cands[0]["start"] - buf, cands[-1]["end"] + buf, cache=True)
            if gb:
                cands = google_io.slots(cfg, LOC, busy + gb, now, days)
        return {"ok": True, "event": public_info(cfg),
                "slots": [{"id": s["id"], "start": s["start"], "end": s["end"]} for s in cands]}
    except Exception as e:  # noqa: BLE001
        _log(f"slots failed: {type(e).__name__}: {e}")
        return {"ok": False, "error": "unavailable", "message": "Booking is unavailable right now."}


# ── create ────────────────────────────────────────────────────────────────────
def _err(code, message):
    return {"ok": False, "error": code, "message": message}


def _text(v, cap, multiline=False):
    """-> cleaned str, or None if over the cap. Control chars dropped (newlines kept if multiline)."""
    s = str(v if v is not None else "")
    if not multiline:
        s = s.replace("\n", " ").replace("\r", " ")
    s = _CTRL_RE.sub("", s).strip()
    return None if len(s) > cap else s


def _rate_ok(ip, now):
    with _LOCK:
        hits = [t for t in _HITS.get(ip, []) if t > now - RATE_WINDOW]
        ok = len(hits) < RATE_MAX
        if ok:
            hits.append(now)
        _HITS[ip] = hits
        for k in [k for k, v in _HITS.items() if not v or v[-1] <= now - RATE_WINDOW]:
            _HITS.pop(k, None)               # ponytail: prune on write; fine at prospect volume
    return ok


def _validate(p):
    """-> (fields dict, None) or (None, error dict)."""
    f = {}
    for k in ("name", "business", "email", "phone", "website", "ref", "tz"):
        f[k] = _text(p.get(k), CAPS[k])
        if f[k] is None:
            return None, _err("invalid", f"{k} is too long")
    f["notes"] = _text(p.get("notes"), CAPS["notes"], multiline=True)
    if f["notes"] is None:
        return None, _err("invalid", "notes is too long")
    if not f["name"]:
        return None, _err("invalid", "Your name is required.")
    if not f["business"]:
        return None, _err("invalid", "Your business name is required.")
    f["email"] = f["email"].lower()
    if not _EMAIL_RE.match(f["email"]):
        return None, _err("invalid", "Enter a valid email address.")
    if f["phone"]:
        digits = re.sub(r"\D", "", f["phone"])
        if not (10 <= len(digits) <= 15) or re.search(r"[^\d\s()+.-]", f["phone"]):
            return None, _err("invalid", "Enter a valid phone number (or leave it blank).")
    if f["website"] and not _SITE_RE.match(f["website"]):
        return None, _err("invalid", "Enter a valid website (or leave it blank).")
    if f["ref"] and not _REF_RE.match(f["ref"]):
        f["ref"] = ""                        # a mangled link still books; it just isn't matched
    need = p.get("need") or []
    if not isinstance(need, list) or any(n not in NEEDS for n in need):
        return None, _err("invalid", "Pick what you want help with from the list.")
    f["need"] = [n for n in NEEDS if n in need]
    try:
        f["start"] = int(p.get("start"))
    except (TypeError, ValueError):
        return None, _err("invalid", "Pick a time first.")
    return f, None


def _on_policy(cfg, start, now):
    """-> slot end if `start` is a real, future, in-window policy slot, else None."""
    tz = google_io._tz(cfg)
    day = datetime.fromtimestamp(start, tz).date()
    today = datetime.fromtimestamp(now, tz).date()
    if not (0 <= (day - today).days < int(cfg["daysAhead"])):
        return None
    if start < now + float(cfg["minNoticeHours"]) * 3600:
        return None
    return next((e for s, e in google_io._day_slots(cfg, day) if s == start), None)


def _leads():
    import agency_callsheet as cs
    return (cs.list_leads() or {}).get("leads") or []


def ref_link(lead_id, base=""):
    """Private (owner, Bookings tab): the per-prospect link token for one Call Sheet lead.
    Unguessable (token_urlsafe), minted once and reused; the public page only ever matches
    this token — a raw lead id in ?ref= is ignored, so nobody can write the CRM by guessing."""
    lead = next((l for l in _leads() if l.get("id") == lead_id), None) if lead_id else None
    if not lead:
        return _err("not_found", "Call Sheet lead not found.")
    with _LOCK:
        d = _load()
        refs = d.setdefault("refs", {})
        tok = next((t for t, lid in refs.items() if lid == lead_id), None)
        if not tok:
            tok = secrets.token_urlsafe(12)
            refs[tok] = lead_id
            _save(d)
    sep = "&" if "?" in base else "?"
    return {"ok": True, "leadId": lead_id, "token": tok,
            "url": f"{base}{sep}ref={tok}" if base else f"?ref={tok}",
            "lead": lead.get("company") or lead.get("name") or lead_id}


def _suggest_lead(phone):
    """-> (lead id, label) of a Call Sheet row with the same phone, or ('', ''). Read-only:
    a phone typed on a public form is not proof of identity, so it only SUGGESTS."""
    try:
        import agency_callsheet as cs
        want = cs._norm_phone(phone)[-10:]
        if len(want) == 10:
            for l in _leads():
                if cs._norm_phone(l.get("phone"))[-10:] == want:
                    return l["id"], l.get("company") or l.get("name") or l["id"]
    except Exception as e:  # noqa: BLE001
        _log(f"call sheet match skipped: {e}")
    return "", ""


def _global_ok(d, now):
    made = [b.get("createdAt", 0) for b in d["bookings"]]
    return (sum(1 for t in made if t > now - 3600) < GLOBAL_HOUR
            and sum(1 for t in made if t > now - 86400) < GLOBAL_DAY)


def _mark_demo_booked(lead_id):
    try:
        import agency_callsheet as cs
        lead = next((l for l in (cs.list_leads() or {}).get("leads") or [] if l.get("id") == lead_id), None)
        if lead and (lead.get("status") or "new") in PRE_DEMO:
            cs.set_status(lead_id, "demo_booked")
            return True
    except Exception as e:  # noqa: BLE001
        _log(f"call sheet update skipped: {e}")
    return False


def when_label(cfg, start, end):
    return google_io._slot(google_io._tz(cfg), start, end)["label"] + " ET"


def _ping(cfg, b):
    try:
        import telegram_io
        e = html.escape
        need = ", ".join(b["need"]) or "-"
        telegram_io.send_biz("agency",
                             f"📅 <b>Call booked</b> — {e(b['name'])} · {e(b['business'])}\n"
                             f"{e(when_label(cfg, b['start'], b['end']))}\nWants: {e(need)}"
                             + (f"\nCall Sheet: {e(b['leadId'])}" if b["leadId"] else "")
                             + (f"\nPossible Call Sheet match: {e(b['suggestedName'])} (confirm in Bookings)"
                                if b.get("suggestedLead") else ""),
                             dedupe_key=f"booking:{b['id']}")
    except Exception as e:  # noqa: BLE001 — unconfigured/failed Telegram never blocks a booking
        _log(f"telegram ping skipped: {e}")


def create(payload, ip, now=None):
    """Book one call from the public page. -> {ok, booking:{start,end,title,host,durationMin}}"""
    try:
        now = now or time.time()
        p = payload if isinstance(payload, dict) else {}
        if str(p.get("fax") or "").strip():          # honeypot: hidden from humans
            return _err("invalid", "Could not book that time.")
        if not _rate_ok(str(ip or "?"), now):
            return _err("rate_limited", "Too many attempts. Please try again in an hour.")
        f, bad = _validate(p)
        if bad:
            return bad
        cfg = config()
        end = _on_policy(cfg, f["start"], now)
        if end is None:
            return _err("not_bookable", "That time is not available. Please pick another.")
        buf = int(cfg["bufferMinutes"]) * 60
        sug_id, sug_name = _suggest_lead(f["phone"])
        # ponytail: one process-wide lock held across the Google calls (one connector runs);
        # a second writer process would need a calendar-side guard.
        with _LOCK:
            d = _load()
            if not _global_ok(d, now):
                _log("global booking cap hit — refusing")
                return _err("rate_limited", "Booking is busy right now. Please try again later.")
            lead_id = (d.get("refs") or {}).get(f["ref"], "") if f["ref"] else ""
            if any(b.get("email") == f["email"] for b in _live(d, now)):
                return _err("already_booked", "You already have a call booked. Reply to the "
                                              "calendar invite or email us to change it.")
            busy = _busy_local(d, now) + _google_busy(cfg, f["start"] - buf, end + buf)
            if not google_io._clear(f["start"], end, busy, buf):
                return _err("slot_taken", "Someone just took that time. Please pick another.")
            b = {"id": "bk_" + secrets.token_hex(6), "status": "booked", "start": f["start"], "end": end,
                 "slotId": google_io._slot(google_io._tz(cfg), f["start"], end)["id"],
                 **{k: f[k] for k in ("name", "business", "email", "phone", "website", "need", "notes",
                                      "ref", "tz")},
                 "leadId": lead_id, "leadMatch": "ref" if lead_id else "",
                 "suggestedLead": "" if lead_id else sug_id, "suggestedName": "" if lead_id else sug_name,
                 "createdAt": int(now),
                 "eventId": None, "googleError": None}
            if _google_on():
                b["eventId"], b["googleError"] = _google_insert(cfg, b)
                if b["googleError"]:
                    _log(f"booking {b['id']} kept locally; {b['googleError']}")
                else:
                    with google_io._LOCK:      # freeBusy can lag a fresh insert
                        google_io._RECENT.append((b["start"], end, b["eventId"], time.time() + 900))
            d["bookings"].append(b)
            _save(d)
            _BUSY_CACHE["key"] = None
        demo = _mark_demo_booked(lead_id) if lead_id else False
        _ping(cfg, b)
        _log(f"booked {b['id']} {b['slotId']} lead={lead_id or '-'}{' -> demo_booked' if demo else ''}")
        info = public_info(cfg)
        return {"ok": True, "booking": {"start": b["start"], "end": end, "title": info["title"],
                                        "host": info["host"], "durationMin": info["durationMin"]}}
    except Exception as e:  # noqa: BLE001
        _log(f"create failed: {type(e).__name__}: {e}")
        return _err("unavailable", "Booking failed. Please try again.")


# ── dashboard (private Handler only) ─────────────────────────────────────────
def _view(cfg, b):
    keys = ("id", "start", "end", "slotId", "name", "business", "email", "phone", "website", "need",
            "notes", "ref", "leadId", "leadMatch", "suggestedLead", "suggestedName", "tz", "createdAt",
            "eventId", "googleError")
    return {**{k: b.get(k) for k in keys}, "when": when_label(cfg, b["start"], b["end"])}


def upcoming(now=None, link=""):
    """GET /api/agency/bookings — booked calls that have not ended, soonest first."""
    now = now or time.time()
    cfg = config()
    with _LOCK:
        rows = sorted(_live(_load(), now), key=lambda b: b["start"])
    return {"ok": True, "bookings": [_view(cfg, b) for b in rows], "count": len(rows),
            "link": link, "event": public_info(cfg), "google": _google_on()}


def cancel(booking_id, now=None, link=""):
    """POST /api/agency/bookings/cancel — frees the slot; deletes the Google event if any."""
    cfg = config()
    with _LOCK:
        d = _load()
        b = next((x for x in d["bookings"] if x.get("id") == booking_id and x.get("status") == "booked"), None)
        if not b:
            return _err("not_found", "Booking not found (or already cancelled).")
        b["status"], b["cancelledAt"] = "cancelled", int(time.time())
        if b.get("eventId"):
            b["googleError"] = _google_delete(cfg, b["eventId"])
            with google_io._LOCK:
                google_io._RECENT[:] = [r for r in google_io._RECENT if r[2] != b["eventId"]]
        _save(d)
        _BUSY_CACHE["key"] = None
    _log(f"cancelled {booking_id}")
    out = upcoming(now, link)
    out["cancelled"] = booking_id
    return out


def confirm_lead(booking_id, now=None, link=""):
    """POST /api/agency/bookings/confirm-lead — the owner's tap on a phone-match suggestion:
    links the booking to that Call Sheet row and marks it demo_booked (never regresses)."""
    with _LOCK:
        d = _load()
        b = next((x for x in d["bookings"] if x.get("id") == booking_id), None)
        if not b or not b.get("suggestedLead"):
            return _err("not_found", "No suggested Call Sheet match on that booking.")
        b["leadId"], b["leadMatch"] = b["suggestedLead"], "phone_confirmed"
        b["suggestedLead"], b["suggestedName"] = "", ""
        _save(d)
    demo = _mark_demo_booked(b["leadId"])
    out = upcoming(now, link)
    out["confirmed"], out["demoBooked"] = b["leadId"], demo
    return out


def purge(booking_id):
    """Remove one booking record entirely (test cleanup). Private only, never routed."""
    with _LOCK:
        d = _load()
        n = len(d["bookings"])
        d["bookings"] = [b for b in d["bookings"] if b.get("id") != booking_id]
        _save(d)
    return n != len(d["bookings"])

