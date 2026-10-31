"""daycare_calendar.py — Solomon · Calendar: booked tours + first days → one Google calendar.

A lane of Solomon, like Starts: its heartbeat is labeled "Solomon · Calendar" and it makes ZERO
Claude calls. Spec: Brand Kit docs/google-calendar/2026-10-30-tour-first-day-calendar-design.md

Computed, not scheduled. Every tick works out which events should exist, compares that to the
ledger (marcus_state/daycare_calendar.json) and creates, moves or removes events. One way only:
an edit made inside Google does not flow back.

  Tours       the GHL contact: tag tour-scheduled + Tour Date, Tour Time, Tour Location.
              confirm_tour() is the owner's tap. It arms the published Tour Check-in SMS.
  First days  the Starts state: confirmed, or proposed with the Add to calendar tap.

Rules that keep a family safe:
  - A failed read never removes an event. A missing tour is re-read before it is removed.
  - Center is never guessed: unclear = held, flagged, no event.
  - Past events are never created or moved. 7 days after the event the names are stripped.
  - No guests, no phone, email, last name, notes or payment type in any event.
  - QA mode is the default: only zz-calendar-qa contacts, only the QA calendar.
    FORGE_DAYCARE_CAL_QA=0 is the owner's switch to real mode.

Disk: event ids, hashes and dates, plus a first name in `held`. Never a phone, email or token.
Stdlib only. Tests: python3 test_daycare_calendar.py
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import daycare_ghl
import forge_atomic
import forge_heartbeat
import forge_ops
import google_cal_io as gcal
from google_cal_io import CalAuthError, CalError, _pick, event_id

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_calendar.json"
ET = ZoneInfo("America/New_York")
UTC = timezone.utc
TZ_NAME = "America/New_York"

INTERVAL = int(os.environ.get("FORGE_DAYCARE_CAL_INTERVAL", "900"))   # 15 min
TOUR_MINUTES = 30           # website/tour-config.json slotMinutes
SCRUB_AFTER_DAYS = 7        # same rule as the staff calendar design
FORGET_AFTER_DAYS = 90      # a stripped row leaves the ledger
FAIL_TRIES = 3              # failed ticks before the owner is told
MAX_WRITES = 20             # Google writes per tick
MAX_PAGES = 5               # contact search pages per tick
HOURS = (6, 18)             # Mon-Fri 6:00 AM - 6:00 PM (ATOB-MASTER-INFO)
TOUR_DAYS_AHEAD = 120

CF_TOUR_DATE = "eQhnJzIYVbwGFh8z81jl"
CF_TOUR_TIME = "FPuBFbQzWCzFq5V8qFap"
CF_TOUR_LOCATION = "Ya3O863Fh9koyqCejf8k"
CF_CHILD_AGE = "KW7sDqefOml0Iym7MH5c"
TAG_SCHEDULED, TAG_CANCELED, QA_TAG = "tour-scheduled", "tour-canceled", "zz-calendar-qa"
START_STATUSES = {"confirmed", "sending", "sent", "failed"}

# tourLabel = the GHL Tour Location text. None = no tours there yet: the check-in text must
# have an A Mother's Touch version first, because rule 11 forbids the other brand at 1923.
CENTERS = {
    "loc-921-n-18th": {"tag": "[921]", "color": "3", "tourLabel": "A Touch of Blessings",
                       "address": "921 N 18th St, Philadelphia, PA 19130", "entity": "entity-atob"},
    "loc-2318-cecil-b-moore": {"tag": "[2318]", "color": "7", "tourLabel": "A Touch of Blessings 2 & 3",
                               "address": "2318 Cecil B. Moore Ave, Philadelphia, PA 19121",
                               "entity": "entity-atob"},
    "loc-1923-cecil-b-moore": {"tag": "[1923 AMT]", "color": "4", "tourLabel": None,
                               "address": "1923 Cecil B. Moore Ave, Philadelphia, PA 19121",
                               "entity": "entity-amt"},
}
TAG_BY_LOCATION_ID = {v: k for k, v in daycare_ghl.LOCATION_ID_BY_TAG.items()}

_RUN = threading.Lock()
_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AP])\.?M\b", re.I)
_DIGITS = re.compile(r"^\d{10,14}$")
_AGE_TEXT = re.compile(r"^[0-9A-Za-z ./-]{1,20}$")


# --------------------------------------------------------------------------- reading values
def _today(now=None):
    return datetime.fromtimestamp(now or time.time(), ET).date()


def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 — missing/corrupt = fresh ledger; ids are stable, so no duplicates
        return {}


def _save(st):
    forge_atomic.atomic_write_json(STATE, st)


def qa_mode():
    """On unless the owner set FORGE_DAYCARE_CAL_QA=0: a missing switch never reaches real families."""
    return _pick("FORGE_DAYCARE_CAL_QA") != "0"


def _gcal_ready():
    return gcal.configured()


def _clean(value, limit):
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))).strip()[:limit]


def _date(value):
    """GHL date → date. It may come back ISO, m/d/Y or epoch ms (midnight UTC)."""
    raw = str(value or "").strip()
    if _DIGITS.match(raw):
        return datetime.fromtimestamp(int(raw) / (1000 if len(raw) > 10 else 1), UTC).date()
    for fmt, size in (("%Y-%m-%d", 10), ("%m/%d/%Y", 10), ("%m-%d-%Y", 10)):
        try:
            return datetime.strptime(raw[:size], fmt).date()
        except ValueError:
            continue
    return None


def parse_clock(text):
    """(hour24, minute) from Tour Time text, only when it names exactly one clock time."""
    hits = _CLOCK.findall(str(text or ""))
    if len(hits) != 1:
        return None
    hour, minute, half = int(hits[0][0]), int(hits[0][1]), hits[0][2].upper()
    if not 1 <= hour <= 12 or minute > 59:
        return None
    return (hour % 12) + (12 if half == "P" else 0), minute


def _age(cf, on_day):
    """The child's age on the event day: birth date first, then the family's Child Age text."""
    dob = _date(cf.get(daycare_ghl.CF_CHILD_DOB))
    if dob and dob <= on_day:
        months = (on_day.year - dob.year) * 12 + on_day.month - dob.month - (on_day.day < dob.day)
        if months >= 12:
            years = months // 12
            return f"{years} Year{'' if years == 1 else 's'}"
        return f"{months} Month{'' if months == 1 else 's'}"
    # enroll.js writes "2 Years (+1 sibling)" for a multi-child form: the note is not the age.
    text = _clean(str(cf.get(CF_CHILD_AGE) or "").split("(")[0], 20)
    if text.isdigit():
        return f"Age {text}"      # no unit on file: never guess years or months
    return text if _AGE_TEXT.match(text) else ""


def _tags(contact):
    return {str(t).strip().lower() for t in contact.get("tags") or []}


def _one_center(tags):
    locs = [t for t in tags if t.startswith("loc-")]
    return locs[0] if len(locs) == 1 and locs[0] in CENTERS else ""


def _is_test(fam):
    # ponytail: first name starting ZZ = our test contacts; a real child named Zz... would be skipped.
    return str(fam.get("child_first") or "").lower().startswith("zz")


def _short_name(fam):
    first = _clean(fam.get("child_first"), 40)
    last = _clean(fam.get("child_last"), 40)
    return f"{first} {last[0].upper()}." if first and last else first or "Child"


# --------------------------------------------------------------------------- event bodies
def _title(center, word, fam, age):
    name = _short_name(fam)
    return f"{center['tag']} {word}: {name}" + (f" ({age})" if age else "")


def _describe(location, contact_id, fam):
    lines = []
    parent = _clean(fam.get("parent_name"), 60)
    if parent:
        lines.append(f"Parent: {parent}")
    lines.append(f"GHL: https://app.gohighlevel.com/v2/location/{location}/contacts/detail/{contact_id}")
    lines.append("Auto-filled. Change it in the dashboard, not here.")
    return "\n".join(lines)


def _timed(day, hour, minute):
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET)
    end = start + timedelta(minutes=TOUR_MINUTES)
    return ({"dateTime": start.isoformat(), "timeZone": TZ_NAME},
            {"dateTime": end.isoformat(), "timeZone": TZ_NAME})


def _all_day(day):
    return {"date": day.isoformat()}, {"date": (day + timedelta(days=1)).isoformat()}


def _tour_event(location, contact_id, fam, cf, loc, day):
    center = CENTERS[loc]
    age = _age(cf, day)
    clock = parse_clock(cf.get(CF_TOUR_TIME))
    start, end = _timed(day, *clock) if clock else _all_day(day)
    return {"summary": _title(center, "Tour" if clock else "Tour: time not set", fam, age), "description": _describe(location, contact_id, fam), "location": center["address"],
            "colorId": center["color"], "start": start, "end": end}, bool(clock)


def _first_day_event(location, contact_id, fam, cf, loc, day):
    center = CENTERS[loc]
    start, end = _all_day(day)
    return {"summary": _title(center, "First day", fam, _age(cf, day)),
            "description": _describe(location, contact_id, fam), "location": center["address"],
            "colorId": center["color"], "start": start, "end": end, "transparency": "transparent"}


def _hash(cal, body):
    return hashlib.sha256(json.dumps([cal, body], sort_keys=True).encode()).hexdigest()


# --------------------------------------------------------------------------- GHL reads
def _tagged(client, tag):
    """Contact ids carrying a tag. Raises on a failed read: the caller must not treat it as none."""
    ids, page = [], 1
    while page <= MAX_PAGES:
        body = {"locationId": client.location_id, "page": page, "pageLimit": 100,
                "filters": [{"field": "tags", "operator": "contains", "value": tag}]}
        data = client.post("/contacts/search", body)
        rows = data.get("contacts") or []
        ids += [str(c.get("id")) for c in rows if c.get("id")]
        if len(rows) < 100:
            break
        page += 1
    return ids


def _contact(client, contact_id):
    # One GET per contact: the search response hides DATE fields and lowercases names.
    data = client.get(f"/contacts/{contact_id}")
    contact = data.get("contact") if isinstance(data, dict) else None
    if not isinstance(contact, dict):
        raise ValueError("no contact in the GHL reply")
    return contact


def _starts_entries():
    """Strict read: unlike daycare_starts._load, a bad file raises, so nothing gets removed."""
    import daycare_starts
    entries = json.loads(daycare_starts.STATE.read_text()).get("entries")
    if not isinstance(entries, dict):
        raise ValueError("no entries in the Starts state")
    return entries


def _hold(held, kind, contact_id, fam, reason):
    held.append({"kind": kind, "contactId": contact_id, "who": _short_name(fam), "reason": reason})


def _tours(client, qa, qa_ids, cal):
    """(wanted, keep, held) for tours. Raises on any failed read."""
    wanted, keep, held = {}, set(), []
    # ponytail: one GET per tagged contact each tick, past tours too; prune tags if this ever hits MAX_PAGES.
    for contact_id in (qa_ids if qa else _tagged(client, TAG_SCHEDULED)):
        contact = _contact(client, contact_id)
        tags = _tags(contact)
        fam = daycare_ghl._family_from_contact(contact)
        if TAG_SCHEDULED not in tags or TAG_CANCELED in tags:
            continue
        if not qa and (QA_TAG in tags or _is_test(fam)):
            continue
        key = f"tour|{contact_id}"
        cf = daycare_ghl._cf_map(contact)
        day = _date(cf.get(CF_TOUR_DATE))
        loc = _one_center(tags)
        label = _clean(cf.get(CF_TOUR_LOCATION), 60)
        if not day:
            reason = "no Tour Date on the contact"
        elif not loc:
            reason = "needs exactly one center tag"
        elif CENTERS[loc]["tourLabel"] != label:
            reason = "center tag and Tour Location disagree"
        else:
            reason = ""
        if reason:
            _hold(held, "tour", contact_id, fam, reason)
            keep.add(key)
            continue
        body, timed = _tour_event(client.location_id, contact_id, fam, cf, loc, day)
        if not timed:
            _hold(held, "tour", contact_id, fam, "Tour Time could not be read: event is all-day")
        wanted[key] = {"kind": "tour", "cal": cal, "body": body, "when": day.isoformat(), "center": loc}
    return wanted, keep, held


def _first_days(client, entries, ledger, qa, qa_ids, today, cal):
    """(wanted, keep, held) for first days. An unchanged entry needs no GHL read."""
    wanted, keep, held = {}, set(), []
    for contact_id, entry in entries.items():
        status = entry.get("status")
        if status not in START_STATUSES and not (status == "proposed" and entry.get("calendarAt")):
            continue
        if qa and contact_id not in qa_ids:
            continue
        key = f"first|{contact_id}"
        day = _date(entry.get("startDate"))
        row = ledger.get(key) or {}
        if not day:
            continue
        if day < today:
            if key in ledger:
                keep.add(key)
            continue
        source = f"{day}|{status in START_STATUSES}|{entry.get('locationId')}"
        if row.get("hash") and row.get("source") == source:
            keep.add(key)
            continue
        contact = _contact(client, contact_id)
        fam = daycare_ghl._family_from_contact(contact)
        if not qa and (QA_TAG in _tags(contact) or _is_test(fam)):
            continue
        # A confirm set the real center. A tap only has tags, and Starts picks the first of several.
        loc = TAG_BY_LOCATION_ID.get(entry.get("locationId")) if status in START_STATUSES else ""
        loc = loc or _one_center(_tags(contact))
        if not loc:
            _hold(held, "first", contact_id, fam, "needs exactly one center tag")
            keep.add(key)
            continue
        wanted[key] = {"kind": "first", "cal": cal, "when": day.isoformat(), "center": loc, "source": source,
                       "body": _first_day_event(client.location_id, contact_id, fam, daycare_ghl._cf_map(contact), loc, day)}
    return wanted, keep, held


def _still_booked(client, contact_id):
    """A tour missing from the search is re-read first: only a clean read removes an event."""
    tags = _tags(_contact(client, contact_id))
    return TAG_SCHEDULED in tags and TAG_CANCELED not in tags


# --------------------------------------------------------------------------- the tick
def _record(ledger, key, want, error):
    """Ledger row after a write. Failed writes keep the old hash, so the next tick retries."""
    row = ledger.setdefault(key, {"kind": want["kind"], "eventId": event_id(key), "tries": 0})
    if error:
        row.update(tries=row.get("tries", 0) + 1, error=error, cal=want["cal"], when=want["when"])
        return
    shell = {k: v for k, v in want["body"].items() if k not in ("summary", "description")}
    row.update(cal=want["cal"], when=want["when"], center=want["center"], shell=shell, tries=0, error=None,
               hash=_hash(want["cal"], want["body"]), source=want.get("source"), scrubbed=False)


def _scrub_body(row):
    word = "Tour" if row.get("kind") == "tour" else "First day"
    tag = CENTERS.get(row.get("center"), {}).get("tag", "")
    return {**(row.get("shell") or {}), "summary": f"{tag} {word} (past)".strip(), "description": ""}


def _notify(text, key):
    """One Telegram note to the daycare chat. Counts only, never a name. Best effort."""
    try:
        import telegram_io
        telegram_io.send_biz("daycare", html.escape(text), dedupe_key=key)
    except Exception:  # noqa: BLE001 — a ping never blocks the lane
        pass


def _apply(client, st, wanted, keep, clean, today):
    """Run the writes. Returns (writes used, auth error or None, read error or None)."""
    ledger, writes, read_err = st["events"], 0, None
    for key, want in wanted.items():
        row = ledger.get(key)
        if writes >= MAX_WRITES:
            break
        if want["when"] < today.isoformat():
            continue                              # past: never created, never moved
        if row and row.get("hash") == _hash(want["cal"], want["body"]):
            continue
        writes += 1
        try:
            gcal.put_event(want["cal"], event_id(key), want["body"])
            _record(ledger, key, want, None)
        except CalAuthError:
            _save(st)
            return writes, "Google calendar login rejected: re-consent needed", read_err
        except CalError as e:
            _record(ledger, key, want, str(e))
        _save(st)
    for key, row in list(ledger.items()):
        if writes >= MAX_WRITES:
            break
        kind = key.split("|")[0]
        if key in wanted or key in keep or kind not in clean or row.get("when", "") < today.isoformat():
            continue
        contact_id = key.split("|", 1)[1]
        writes += 1
        try:
            if kind == "tour" and _still_booked(client, contact_id):
                continue
            if row.get("hash"):
                gcal.remove(row.get("cal"), event_id(key))
            ledger.pop(key)
        except CalAuthError:
            _save(st)
            return writes, "Google calendar login rejected: re-consent needed", read_err
        except CalError as e:
            row.update(tries=row.get("tries", 0) + 1, error=str(e))
        except Exception as e:  # noqa: BLE001 — a failed re-read keeps the event
            read_err = f"GHL read failed: {type(e).__name__}"
        _save(st)
    scrub_before = (today - timedelta(days=SCRUB_AFTER_DAYS)).isoformat()
    forget_before = (today - timedelta(days=FORGET_AFTER_DAYS)).isoformat()
    for key, row in list(ledger.items()):
        if writes >= MAX_WRITES:
            break
        when = row.get("when", "")
        if row.get("scrubbed"):
            if when < forget_before:
                ledger.pop(key)
            continue
        if not row.get("hash") or when > scrub_before:
            continue
        writes += 1
        try:
            gcal.put_event(row.get("cal"), event_id(key), _scrub_body(row))
            row.update(scrubbed=True, tries=0, error=None)
        except CalAuthError:
            _save(st)
            return writes, "Google calendar login rejected: re-consent needed", read_err
        except CalError as e:
            row.update(tries=row.get("tries", 0) + 1, error=str(e))
        _save(st)
    return writes, None, read_err


def _tick(client, now):
    st = _load()
    st.setdefault("events", {})
    today, qa = _today(now), qa_mode()
    if not _gcal_ready():
        st.update(lastRunAt=int(now * 1000), error="Google calendar is not connected")
        _save(st)
        return st["error"]
    cal = _pick("GOOGLE_CAL_ID_QA" if qa else "GOOGLE_CAL_ID")
    wanted, keep, held, clean, errors = {}, set(), [], set(), []
    qa_ids = set()
    try:
        qa_ids = set(_tagged(client, QA_TAG)) if qa else qa_ids
    except Exception as e:  # noqa: BLE001 — type + code only, never a body
        errors.append(f"GHL read failed: {type(e).__name__}")
    if not errors:
        for kind, read in (
                ("tour", lambda: _tours(client, qa, sorted(qa_ids), cal)),
                ("first", lambda: _first_days(client, _starts_entries(), st["events"], qa, qa_ids, today, cal))):
            try:
                w, k, h = read()
                wanted.update(w)
                keep |= k
                held += h
                clean.add(kind)
            except Exception as e:  # noqa: BLE001 — a failed half writes and removes nothing
                errors.append(f"{kind} read failed: {type(e).__name__}")
    st["held"] = held + [h for h in st.get("held") or [] if h.get("kind") not in clean]
    _, auth_err, read_err = _apply(client, st, wanted, keep, clean, today)
    errors += [e for e in (auth_err, read_err) if e]
    failed = [r for r in st["events"].values() if r.get("tries", 0) >= FAIL_TRIES]
    if failed:
        errors.append(f"{len(failed)} calendar event(s) could not be updated")
    if (failed or auth_err) and st.get("notifiedOn") != today.isoformat():
        st["notifiedOn"] = today.isoformat()
        _notify(auth_err or f"Calendar: {len(failed)} event(s) could not be updated after {FAIL_TRIES} tries.",
                f"daycare-calendar:{today}")
    st.update(lastRunAt=int(now * 1000), error="; ".join(errors) or None)
    _save(st)
    return st["error"]


def tick(client, now=None):
    if not _RUN.acquire(blocking=False):
        return "a calendar tick is already running"
    try:
        return _tick(client, now or time.time())
    finally:
        _RUN.release()


def run_now(client):
    """POST /api/daycare/calendar/run: one tick on demand, in whichever mode is set."""
    return {"ok": True, "error": tick(client), **view()}


def view(now=None):
    """GET /api/daycare/calendar: state only, no network on the request path."""
    st = _load()
    rows = (st.get("events") or {}).values()
    err = st.get("error")
    if not st.get("lastRunAt"):
        err = err or ("The calendar lane has not run yet: it runs every 15 min on the box "
                      "(loops are off on a UI-only machine).")
    return {"ok": True, "mode": "qa" if qa_mode() else "live", "lastRunAt": st.get("lastRunAt"), "error": err,
            "events": sum(1 for r in rows if r.get("hash") and not r.get("scrubbed")),
            "failed": sum(1 for r in rows if r.get("tries", 0) >= FAIL_TRIES), "held": st.get("held") or []}


# --------------------------------------------------------------------------- owner taps
def _tap_contact(client, contact_id):
    """The contact for a tap, or (None, error). QA mode only touches QA contacts: a tap on a real
    family would arm a real text while the lane is still ignoring them."""
    contact_id = str(contact_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]+", contact_id):
        return None, "no contact to update"
    try:
        contact = _contact(client, contact_id)
    except Exception as e:  # noqa: BLE001 — type only, never a token
        return None, f"GHL read failed: {type(e).__name__}"
    if qa_mode() and QA_TAG not in _tags(contact):
        return None, "calendar is in QA mode: only test contacts can be changed"
    return contact, None


def confirm_tour(client, contact_id, day, clock, center_tag, now=None):
    """The owner's Confirm tour tap: fields first, then the tag. Writing Tour Date arms the
    published Tour Check-in SMS, so this tap is that text's approval."""
    now = now or time.time()
    center = CENTERS.get(str(center_tag or ""))
    if not center or not center["tourLabel"]:
        return {"ok": False, "error": "pick 921 or 2318: 1923 tours are off for now"}
    tour_day = _date(day)
    today = _today(now)
    if not tour_day or not today <= tour_day <= today + timedelta(days=TOUR_DAYS_AHEAD):
        return {"ok": False, "error": "pick a date from today to four months out"}
    if tour_day.weekday() > 4:
        return {"ok": False, "error": "the centers are open Monday to Friday"}
    match = re.fullmatch(r"(\d{2}):(\d{2})", str(clock or ""))
    if not match or int(match[2]) > 59 or not HOURS[0] <= int(match[1]) < HOURS[1]:
        return {"ok": False, "error": "pick a time from 6:00 AM to 6:00 PM"}
    hour, minute = int(match[1]), int(match[2])
    contact, err = _tap_contact(client, contact_id)
    if err:
        return {"ok": False, "error": err}
    tags = _tags(contact)
    locs = [t for t in tags if t.startswith("loc-")]
    if locs and locs != [center_tag]:
        return {"ok": False, "error": "this family is tagged for another center: fix it in GHL first"}
    text = (f"{tour_day:%A}, {tour_day:%B} {tour_day.day} at "
            f"{hour % 12 or 12}:{minute:02d} {'PM' if hour >= 12 else 'AM'} ET")
    cid = contact["id"]
    try:
        client.put(f"/contacts/{cid}", {"customFields": [
            {"id": CF_TOUR_DATE, "field_value": tour_day.isoformat()},
            {"id": CF_TOUR_TIME, "field_value": text},
            {"id": CF_TOUR_LOCATION, "field_value": center["tourLabel"]}]})
        if not locs:
            client.post(f"/contacts/{cid}/tags", {"tags": [center_tag, center["entity"]]})
        if TAG_CANCELED in tags:
            client.delete(f"/contacts/{cid}/tags", {"tags": [TAG_CANCELED]})
        client.post(f"/contacts/{cid}/tags", {"tags": [TAG_SCHEDULED]})   # additive, never an upsert
    except Exception as e:  # noqa: BLE001 — type + code only, never a body
        code = getattr(e, "code", None)
        return {"ok": False, "error": f"GHL update failed: {type(e).__name__}{f' {code}' if code else ''}"}
    return {"ok": True, "tourDate": tour_day.isoformat(), "tourTime": text}


def cancel_tour(client, contact_id):
    """The owner's Cancel tour tap. The next tick removes the event; the tag stops the check-in text."""
    contact, err = _tap_contact(client, contact_id)
    if err:
        return {"ok": False, "error": err}
    cid = contact["id"]
    try:
        client.delete(f"/contacts/{cid}/tags", {"tags": [TAG_SCHEDULED]})
        client.post(f"/contacts/{cid}/tags", {"tags": [TAG_CANCELED]})
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        return {"ok": False, "error": f"GHL update failed: {type(e).__name__}{f' {code}' if code else ''}"}
    return {"ok": True}


def run_forever(client):
    """Background loop (thread `daycare_calendar`, box only)."""
    while True:
        err = None
        try:
            if client is None or not getattr(client, "configured", False):
                err = "Daycare GHL not configured"
            elif not forge_ops.paused():
                err = tick(client)
        except Exception as e:  # noqa: BLE001 — one failure never kills the loop
            err = type(e).__name__
        forge_heartbeat.beat("daycare_calendar", INTERVAL, "Solomon · Calendar", error=err)
        time.sleep(INTERVAL)
