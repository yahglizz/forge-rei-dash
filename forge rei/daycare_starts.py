"""daycare_starts.py — Solomon · Starts: agreed start date → owner confirm → start-day app login.

A lane of Solomon (like Replies / Leads): its heartbeat is labeled "Solomon · Starts", its
thread (`daycare_starts`) bills to Solomon, and it makes ZERO Claude calls.

Flow (spec: docs/superpowers/specs/2026-09-29-daycare-start-date-design.md):
  1. sweep()  — every 15 min on the box, reads recently-active daycare GHL threads of
     new-signup contacts and pulls the agreed start date out of the messages with the pure
     extract() below (no guessing: vague = nothing). Fallback: the form's Desired Start Date.
  2. propose  — state `proposed`; the GHL contact gets the "Agreed Start Date" field + tag
     `start-date-proposed` (internal + reversible — CLAUDE.md rule 2 auto-tag class).
  3. confirm() — the OWNER's tap (prompted from 2 days before the date). Enrolls/updates the
     child in Supabase with enrollment_date = start date and makes sure a parent login exists
     (via the connector's enroll path, NO text). State `confirmed`.
  4. send_due() — on the start day (first tick inside 8am–9pm ET) mints a fresh PIN (never
     stored) and texts the login + the get-app guide. The owner's confirm tap IS the approval
     for that one text; opt-out / DND / window are re-checked by daycare_replies.send_manual.

Disk: marcus_state/daycare_starts.json holds dates, names and a ≤160-char evidence quote
from the thread (so the owner can check it before confirming). Never a PIN, phone or email.
Stdlib only.
"""
from __future__ import annotations

import calendar
import html
import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import daycare_ghl
import daycare_leads
import forge_atomic
import forge_heartbeat
import forge_ops

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_starts.json"
_LOCK = threading.Lock()

INTERVAL = int(os.environ.get("FORGE_DAYCARE_STARTS_INTERVAL", "900"))   # 15 min
ET = daycare_leads.ET
CONFIRM_DAYS = 2            # the confirm prompt opens this many days before the start date
HORIZON_DAYS = 120          # a "start date" further out than this is not a start date
LOOKBACK_DAYS = 21          # threads quiet longer than this are not re-read
MAX_READS = 30              # contacts read per sweep (2 GETs each)
MAX_TRIES = 3               # start-day send attempts before it becomes an owner FIX row
SENDING_STALE_SEC = 600     # a send that never recorded its result → failed, never re-sent

CF_AGREED = "KDzh39WHQIlZIIUb7xLR"     # GHL "Agreed Start Date" (DATE) — created 2026-09-29
CF_DESIRED = "R6lY0PLyZgCVWchlplzE"    # GHL "Desired Start Date" — the parent's form answer
TAG_PROPOSED, TAG_CONFIRMED, TAG_SENT = "start-date-proposed", "start-date-confirmed", "app-login-sent"
SIGNUP_TAGS = {"website-lead", "form-type-new-inquiry", "family-contact-form"}

# --------------------------------------------------------------------------- extractor
_MONTHS = {}
for _i in range(1, 13):
    _MONTHS[calendar.month_name[_i].lower()] = _i
    _MONTHS[calendar.month_abbr[_i].lower()] = _i
_MONTHS["sept"] = 9
_WEEKDAYS = {"monday": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2,
             "wed": 2, "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4,
             "fri": 4, "saturday": 5, "sunday": 6}
_MON_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_START_RE = re.compile(r"\b(?:start(?:s|ing)?|begin(?:s|ning)?|first\s+day|1st\s+day)\b", re.I)
_PAST_RE = re.compile(r"\b(?:started|began|begun)\b", re.I)
_TOUR_RE = re.compile(r"\btours?\b", re.I)
_NUM_RE = re.compile(r"(?<![\d/$])(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?(?![\d/])")
_MONTH_DAY_RE = re.compile(rf"\b({_MON_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s*(\d{{4}}))?", re.I)
_DAY_OF_MONTH_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+of\s+({_MON_ALT})\b(?:,?\s*(\d{{4}}))?", re.I)
_THE_NTH_RE = re.compile(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*(?:months?|years?|kids|children|of us|:|am|pm))", re.I)
_RATIO_RE = re.compile(r"ratio\W+(?:\w+\W+){0,3}$", re.I)
_WD_ALT = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))
_WEEKDAY_RE = re.compile(rf"\b({_WD_ALT})\b", re.I)
_WD_RANGE_RE = re.compile(rf"\b(?:{_WD_ALT})\s*(?:-|–|to|thru|through)\s*(?:{_WD_ALT})\b", re.I)
_REL_RE = re.compile(r"\b(tomorrow)\b", re.I)
# Not a family's start: hours ("start at 6:30"), Head Start, keyword replies, a sibling's school.
_NOT_START_RE = re.compile(r"\bstart(?:s|ing)?\s+(?:at\s+\d|serving\b)|\bhead\s+start\b|\b(?:reply|text)\s+start\b|\bschool\s+starts?\b", re.I)
_SENT_SPLIT = re.compile(r"(?<=[.!?\n;])\s+(?=\D)")   # "Oct. 13th" stays whole
_DAYS_AFTER_RE = re.compile(r"\s*(?:(?:full\s+|half\s+)?days?\b|off\b|%|[ap]\.?m\b)", re.I)
_BLAST_SOURCES = {"campaign", "bulk_actions"}     # blasts never agree a family's date
_SCRUB = ((re.compile(r"\S+@\S+"), "[email]"),
          (re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"), "[phone]"),
          (re.compile(r"\bpin\b\W*\w+", re.I), "[pin]"),
          (re.compile(r"\d{5,}"), "[#]"))


def _mk(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except (TypeError, ValueError):
        return None


def _roll(m, d, ref, year=None):
    """Month/day → the first date on/after ref (next year if it already passed)."""
    if year:
        y = int(year)
        return _mk(y + 2000 if y < 100 else y, m, d)
    got = _mk(ref.year, m, d)
    if got and got < ref:
        got = _mk(ref.year + 1, m, d)
    return got


def parse_date(text, ref, horizon=HORIZON_DAYS):
    """Pure: the date `text` names, resolved against `ref` (a date) — the first match that
    lands inside [ref, ref+horizon] (a DOB or a past date earlier in the line is skipped).
    Explicit dates win over "the 13th", which wins over a weekday / tomorrow. None if none."""
    s = str(text or "")
    last = ref + timedelta(days=horizon)
    for rx, order in ((_MONTH_DAY_RE, "md"), (_DAY_OF_MONTH_RE, "dm"), (_NUM_RE, "num")):
        for m in rx.finditer(s):
            if order == "num":
                if _DAYS_AFTER_RE.match(s, m.end()) or _RATIO_RE.search(s[:m.start()]):
                    continue                  # "1/2 days", "2/3 days a week" — a schedule
                got = _roll(m.group(1), m.group(2), ref, m.group(3))
            else:
                mon, day = (m.group(1), m.group(2)) if order == "md" else (m.group(2), m.group(1))
                got = _roll(_MONTHS[mon.lower().rstrip(".")], day, ref, m.group(3))
            if got and ref <= got <= last:
                return got
    m = _THE_NTH_RE.search(s)
    if m:
        d = int(m.group(1))
        y, mo = ref.year, ref.month
        for _ in range(3):          # this month, else the next month that has that day
            got = _mk(y, mo, d)
            if got and got >= ref:
                return got
            y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    s = _WD_RANGE_RE.sub(" ", s)                      # "Monday-Friday" = hours, not a day
    m = _WEEKDAY_RE.search(s)
    if m:
        ahead = (_WEEKDAYS[m.group(1).lower()] - ref.weekday()) % 7
        if not ahead and not re.search(r"\b(?:this|today)\W+$", s[:m.start()], re.I):
            ahead = 7                                  # "Monday" said on a Monday = next week
        return ref + timedelta(days=ahead)
    m = _REL_RE.search(s)
    if m:
        return ref + timedelta(days=1 if m.group(1).lower() == "tomorrow" else 0)
    return None


def _candidate(body, ref):
    """(date, evidence sentence) for one message, or None. A sentence must pair a start
    word with a date; tour talk and past tense ("started") never count."""
    if not _START_RE.search(body):
        return None
    for sent in _SENT_SPLIT.split(body):
        if (_START_RE.search(sent) and not _TOUR_RE.search(sent) and not _PAST_RE.search(sent)
                and not _NOT_START_RE.search(sent)):
            got = parse_date(sent, ref)
            if got:
                return got, sent
    return None


def extract(messages):
    """Pure: newest agreed start date in a GHL thread → {date, evidence, at, dir} or None.
    Both directions count (our "see you Monday 10/13 for her first day" is the agreement as
    much as the parent's). Resolved against each message's own ET date; future only."""
    blasts = {m.get("body") for m in messages or []
              if str(m.get("source") or "").lower() in _BLAST_SOURCES}
    for t, direction, _human, _type, body in reversed(daycare_leads._events(messages)):
        if not body or body in blasts:
            continue
        ref = datetime.fromtimestamp(t, ET).date()
        got = _candidate(str(body), ref)
        if got and ref <= got[0] <= ref + timedelta(days=HORIZON_DAYS):
            evidence = re.sub(r"\s+", " ", got[1]).strip()
            for rx, sub in _SCRUB:
                evidence = rx.sub(sub, evidence)
            evidence = evidence[:160]
            return {"date": got[0].isoformat(), "evidence": evidence,
                    "at": int(t * 1000), "dir": direction, "source": "messages"}
    return None


def form_date(contact, now):
    """The parent's Desired Start Date from the enrollment form, when it is still ahead."""
    raw = str(daycare_ghl._cf_map(contact).get(CF_DESIRED) or "").strip()
    got = None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            got = datetime.strptime(raw[:10], fmt).date()
            break
        except ValueError:
            continue
    today = _today(now)
    if got and today <= got <= today + timedelta(days=HORIZON_DAYS):
        return {"date": got.isoformat(), "evidence": "Desired Start Date on the enrollment form",
                "at": None, "dir": None, "source": "form"}
    return None


# --------------------------------------------------------------------------- state
def _today(now=None):
    return datetime.fromtimestamp(now or time.time(), ET).date()


def _ms(sec):
    return int(sec * 1000)


def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 — missing/corrupt = fresh lane
        return {}


def _save(st):
    forge_atomic.atomic_write_json(STATE, st)


def _days_until(entry, now):
    try:
        return (date.fromisoformat(entry["startDate"]) - _today(now)).days
    except (KeyError, TypeError, ValueError):
        return None


def _row(e, now):
    left = _days_until(e, now)
    return dict(e, daysUntil=left,
                confirmOpen=e.get("status") == "proposed" and left is not None and left <= CONFIRM_DAYS)


def view(now=None):
    """GET /api/daycare/starts — state only, no network on the request path."""
    now = now or time.time()
    st = _load()
    rows = [_row(e, now) for e in (st.get("entries") or {}).values()
            if e.get("status") != "dismissed"]
    rows.sort(key=lambda r: (r.get("status") in ("sent",), r.get("startDate") or "9999"))
    err = st.get("error")
    if not st.get("lastRunAt"):
        err = err or ("The start-date sweep has not run yet — it reads GHL every 15 min on "
                      "the box (loops are off on a UI-only machine).")
    return {"ok": True, "starts": rows, "lastRunAt": st.get("lastRunAt"), "error": err}


def confirm_due(now=None):
    """Owner Actions: proposals inside the confirm window (incl. overdue) + failed sends."""
    now = now or time.time()
    return [_row(e, now) for e in (_load().get("entries") or {}).values()
            if (e.get("status") == "proposed" and -3 <= (_days_until(e, now) or 0) <= CONFIRM_DAYS)
            or e.get("status") == "failed"]


def display_name(e):
    child = str(e.get("childFirst") or "").strip()
    if len(child) >= 2:
        return child
    parent = str(e.get("parentName") or "").strip()
    return f"{parent}'s child" if len(parent) >= 2 else "New family"


def _apply(entries, contact, found, now):
    """Fold one finding into state. Returns True when the proposal is new or changed (→ GHL
    write). Owner decisions win over OLDER evidence; newer evidence of a different date
    reopens (a date moved in the thread after confirm must not send on the stale date)."""
    cid = str(contact.get("id") or "")
    fam = daycare_ghl._family_from_contact(contact)
    tags = {str(t).strip().lower() for t in contact.get("tags") or []}
    loc_tag = next((t for t in sorted(tags) if t.startswith("loc-")), "")
    e = entries.get(cid)
    if date.fromisoformat(found["date"]) < _today(now):
        return False              # a start that already passed is history, not a proposal
    base = {"contactId": cid, "parentName": fam.get("parent_name") or "",
            "parentFirst": fam.get("parent_first") or "", "childFirst": fam.get("child_first") or "",
            "childName": fam.get("child_name") or "", "centerTag": loc_tag,
            "center": daycare_leads.CENTER_LABEL.get(loc_tag) or loc_tag or "Center unknown",
            "locationId": daycare_ghl.LOCATION_ID_BY_TAG.get(loc_tag) or ""}
    fresh = {"startDate": found["date"], "evidence": found["evidence"], "evidenceAt": found["at"],
             "evidenceDir": found["dir"], "source": found["source"]}
    if e is None:
        entries[cid] = dict(base, **fresh, status="proposed", proposedAt=_ms(now), tries=0)
        return True
    status = e.get("status")
    if status == "proposed":
        e.update(base)
    else:                         # confirmed data (e.g. the owner's center pick) stays put
        e.update({k: v for k, v in base.items() if v and not e.get(k)})
    if status in ("sent", "sending", "failed") or found["date"] == e.get("startDate"):
        return False
    # The owner decided on the evidence they SAW (ownerSawAt = that evidence's time). Anything
    # sent after it with a different date reopens — even if it was swept after their tap.
    if found["at"] is None or found["at"] <= (e.get("ownerSawAt") or 0):
        return False              # older (or form) evidence never overrides the owner
    e.update(fresh, status="proposed", proposedAt=_ms(now), tries=0,
             reopened=status in ("confirmed", "dismissed"))
    return True


def _ghl_mark(client, cid, start_date, add, drop=()):
    """Agreed Start Date field + status tag on the GHL contact. Best-effort; returns an
    error string or None (internal + reversible: a field and a tag, no message)."""
    try:
        if start_date is not None:
            client.put(f"/contacts/{cid}", {"customFields": [{"id": CF_AGREED, "field_value": start_date}]})
        if drop:
            client.delete(f"/contacts/{cid}/tags", {"tags": list(drop)})
        client.post(f"/contacts/{cid}/tags", {"tags": [add]})
        return None
    except Exception as e:  # noqa: BLE001 — type + code only, never a body/token
        code = getattr(e, "code", None)
        return f"GHL update failed: {type(e).__name__}{f' {code}' if code else ''}"


def sweep(client, now=None):
    """Read changed signup threads → findings, then fold them in under the lock (owner taps
    made during the network reads are never overwritten). Returns an error string or None."""
    now = now or time.time()
    data = client.get("/conversations/search", {"locationId": client.location_id, "limit": 100,
                                                 "sortBy": "last_message_date"})
    st = _load()
    entries, seen = st.get("entries") or {}, st.get("seen") or {}
    findings, marks, reads, failed = [], {}, 0, 0
    for conv in (data.get("conversations") if isinstance(data, dict) else None) or []:
        cid = conv.get("contactId")
        last = daycare_leads._sec(conv.get("lastMessageDate")) or 0
        if not cid or last < now - LOOKBACK_DAYS * 86400:
            continue
        if (entries.get(cid) or {}).get("status") in ("sent", "sending"):
            continue
        if seen.get(cid) == _ms(last):
            continue                              # thread unchanged since the last read
        if reads >= MAX_READS:
            break
        reads += 1
        try:
            contact = client.get(f"/contacts/{cid}")
            contact = contact.get("contact") if isinstance(contact, dict) else None
            if not isinstance(contact, dict):
                continue
            tags = {str(t).strip().lower() for t in contact.get("tags") or []}
            if tags & SIGNUP_TAGS and TAG_SENT not in tags:
                found = extract(daycare_leads._messages(client, conv))
                if not found or date.fromisoformat(found["date"]) < _today(now):
                    found = form_date(contact, now) or found
                if found:
                    findings.append((contact, found))
            marks[cid] = _ms(last)        # only after a clean read — a failure re-reads next tick
        except Exception as e:  # noqa: BLE001 — one bad thread never kills the sweep...
            if getattr(e, "code", None) == 429:
                raise                             # ...a rate limit does
            failed += 1
    with _LOCK:
        st = _load()
        entries = st.setdefault("entries", {})
        st.setdefault("seen", {}).update(marks)
        changed = [c.get("id") for c, f in findings if _apply(entries, c, f, now)]
        _save(st)
    retry = [cid for cid, e in entries.items() if e.get("ghlError") and e.get("status") == "proposed"]
    for cid in dict.fromkeys(changed + retry):    # GHL writes outside the lock (+ retries)
        e = entries[cid]
        err = _ghl_mark(client, cid, e["startDate"], TAG_PROPOSED, drop=(TAG_CONFIRMED,) if e.get("reopened") else ())
        _patch(cid, ghlError=err)
    return f"{failed} thread(s) could not be read" if failed else None


def _patch(cid, **fields):
    with _LOCK:
        st = _load()
        e = (st.get("entries") or {}).get(cid)
        if e is not None:
            e.update(fields)
            _save(st)
        return e


def _patch_if(cid, ok, **fields):
    """Patch only if ok(entry) still holds under the lock — the loop and the owner's taps
    never overwrite each other's newer decision. Returns the entry, or None if refused."""
    with _LOCK:
        st = _load()
        e = (st.get("entries") or {}).get(cid)
        if e is None or not ok(e):
            return None
        e.update(fields)
        _save(st)
        return e


def _valid_date(value, now):
    try:
        got = date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None
    today = _today(now)
    return got if today <= got <= today + timedelta(days=HORIZON_DAYS) else None


# --------------------------------------------------------------------------- owner taps
def set_date(contact_id, value, now=None, client=None):
    """Owner edits the date (internal: state + the GHL field). Stays unconfirmed."""
    now = now or time.time()
    got = _valid_date(value, now)
    if not got:
        return {"ok": False, "error": "pick a date from today to four months out"}
    cid = str(contact_id or "")
    cur = (_load().get("entries") or {}).get(cid)
    if cur is None:
        return {"ok": False, "error": "no start date on file for that family"}
    e = _patch_if(cid, lambda x: x.get("status") in ("proposed", "confirmed", "dismissed", "failed"),
                  startDate=got.isoformat(), dateSetAt=_ms(now), status="proposed",
                  ownerSawAt=max(cur.get("evidenceAt") or 0, cur.get("ownerSawAt") or 0),
                  source="owner", evidence="Date set by you on the dashboard", tries=0, lastError=None)
    if e is None:
        return {"ok": False, "error": "the start-day text is going out right now — try again in a minute"}
    if client is not None and getattr(client, "configured", False):
        _patch(cid, ghlError=_ghl_mark(client, cid, got.isoformat(), TAG_PROPOSED, drop=(TAG_CONFIRMED,)))
    return {"ok": True, "start": e}


def dismiss(contact_id, now=None, client=None):
    now = now or time.time()
    cid = str(contact_id or "")
    cur = (_load().get("entries") or {}).get(cid)
    if cur is None:
        return {"ok": False, "error": "no start date on file for that family"}
    e = _patch_if(cid, lambda x: x.get("status") not in ("sending", "sent"), status="dismissed",
                  dismissedAt=_ms(now), ownerSawAt=max(cur.get("evidenceAt") or 0, cur.get("ownerSawAt") or 0))
    if e is None:
        return {"ok": False, "error": "the app login already went out to this family"}
    if client is not None and getattr(client, "configured", False):
        try:     # internal + reversible: drop our status tags; the Agreed field stays as history
            client.delete(f"/contacts/{cid}/tags", {"tags": [TAG_PROPOSED, TAG_CONFIRMED]})
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}


def confirm(contact_id, value, enroll_fn, client=None, extras=None, now=None):
    """The owner's Confirm tap. enroll_fn(entry, start_date, extras) → {ok, childId,
    needs?, error?} enrolls/updates the child + makes sure a parent login exists WITHOUT
    texting. The start-day text then goes out automatically (this tap is its approval)."""
    now = now or time.time()
    cid = str(contact_id or "")
    e = (_load().get("entries") or {}).get(cid)
    if not e:
        return {"ok": False, "error": "no start date on file for that family"}
    if e.get("status") in ("sent", "sending", "failed"):
        return {"ok": False, "error": "the app login already went out (or failed) — see the Logins tab"}
    got = _valid_date(value or e.get("startDate"), now)
    if not got:
        return {"ok": False, "error": "pick a date from today to four months out"}
    res = enroll_fn(e, got.isoformat(), extras or {}) or {}
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "could not enroll", "needs": res.get("needs") or []}
    snap = (e.get("status"), e.get("startDate"), e.get("evidenceAt"))
    # Sticky: once a confirm CREATED the login (PIN withheld), later confirms see an existing
    # guardian — but the parent still has no PIN, so the start day must mint one.
    existed = False if e.get("loginExisted") is False else bool(res.get("loginExisted"))
    e = _patch_if(cid, lambda x: (x.get("status"), x.get("startDate"), x.get("evidenceAt")) == snap,
                  status="confirmed", startDate=got.isoformat(), confirmedAt=_ms(now),
                  ownerSawAt=max(e.get("evidenceAt") or 0, e.get("ownerSawAt") or 0),
                  childId=res.get("childId"), locationId=res.get("locationId") or e.get("locationId"),
                  loginExisted=existed, tries=0, lastError=None, reopened=False)
    if e is None:
        return {"ok": False, "error": "this family's start date just changed — check it and confirm again"}
    if client is not None and getattr(client, "configured", False):
        _patch(cid, ghlError=_ghl_mark(client, cid, got.isoformat(), TAG_CONFIRMED, drop=(TAG_PROPOSED,)))
    return {"ok": True, "start": _row(e, now),
            "sendsOn": got.isoformat(), "sendsToday": got <= _today(now)}


# --------------------------------------------------------------------------- start day
def send_due(client, session_fn, mint_fn, now=None, send_fn=None):
    """Text every confirmed family whose start day is TODAY. Marked `sending` under the lock
    BEFORE anything outward, and every result write is conditional on still being `sending`,
    so an owner's dismiss / date change is never overwritten. Once send_fn has been called,
    an exception means the result is unknown → `failed` (never re-sent, never a 2nd PIN)."""
    now = now or time.time()
    if send_fn is None:
        import daycare_replies
        send_fn = lambda cid, text: daycare_replies.send_manual(client, cid, text, now=now, close_draft=False)  # noqa: E731
    in_hours = daycare_leads.in_hours(now)
    with _LOCK:
        st = _load()
        due = []
        for e in (st.get("entries") or {}).values():
            left = _days_until(e, now)
            if e.get("status") == "sending" and _ms(now) - (e.get("sendingAt") or 0) > SENDING_STALE_SEC * 1000:
                e.update(status="failed", lastError="send result unknown — check the thread before resending")
            elif e.get("status") == "confirmed" and left is not None and left < 0:
                e.update(status="failed", lastError="the start day passed before the login text went out")
            elif e.get("status") == "confirmed" and left == 0 and in_hours:
                e.update(status="sending", sendingAt=_ms(now))
                due.append(dict(e))
        _save(st)
    if not due:
        return []
    still_sending = lambda x: x.get("status") == "sending"   # noqa: E731
    session, session_err = None, None
    if any(not e.get("loginExisted") for e in due):
        try:
            session = session_fn()
        except Exception as ex:  # noqa: BLE001 — nothing sent yet: retryable
            session_err = f"no daycare session ({type(ex).__name__})"
        if session is None and session_err is None:
            session_err = "no daycare session — auto-admin is off"
    results = []
    for e in due:
        cid = e["contactId"]
        err, final = None, False
        try:
            # A parent who already had a login keeps their PIN (a reset would lock them out of
            # an app they use): they get the welcome + guide only. A new login gets a fresh PIN.
            if not e.get("loginExisted") and session_err:
                raise RuntimeError(session_err)
            login = {"pin": None} if e.get("loginExisted") else (mint_fn(session, e) or {})
            if not e.get("loginExisted") and not login.get("pin"):
                err = login.get("error") or "could not create a fresh PIN"
        except Exception as ex:  # noqa: BLE001 — type only; never a PIN or token
            err = session_err if isinstance(ex, RuntimeError) and session_err else f"PIN: {type(ex).__name__}"
        if err is None:
            text = daycare_ghl.start_day_text(e.get("parentFirst"), e.get("childFirst"),
                                              login.get("login_id"), login.get("pin"), e.get("locationId"))
            try:
                res = send_fn(cid, text) or {}
                if not res.get("ok"):          # a pre-send gate said no (window/opt-out/DND)
                    err = res.get("error") or res.get("detail") or "send failed"
            except Exception as ex:  # noqa: BLE001 — GHL may have accepted it: never resend
                err, final = f"send result unknown ({type(ex).__name__}) — check the thread", True
        if err is None:
            _patch_if(cid, still_sending, status="sent", sentAt=_ms(now), lastError=None)
            if client is not None:
                _patch(cid, ghlError=_ghl_mark(client, cid, None, TAG_SENT, drop=(TAG_CONFIRMED,)))
        else:
            tries = (e.get("tries") or 0) + 1
            _patch_if(cid, still_sending, status="failed" if final or tries >= MAX_TRIES else "confirmed",
                      tries=tries, lastError=err)
        results.append({"contactId": cid, "ok": err is None, "error": err})
    return results


def _confirm_pings(st, now):
    """Pick (under the lock) the families whose confirm window just opened; mark them so each
    family+date is pinged once. The network sends happen after the lock is released."""
    if not daycare_leads.in_hours(now):
        return []
    pinged, out = st.setdefault("pinged", {}), []
    for e in (st.get("entries") or {}).values():
        left = _days_until(e, now)
        key = f"{e.get('contactId')}:{e.get('startDate')}"
        if e.get("status") != "proposed" or left is None or not 0 <= left <= CONFIRM_DAYS or key in pinged:
            continue
        pinged[key] = _ms(now)
        out.append((key, dict(e)))
    return out


def _ping_confirm_window(pings):
    """One Telegram + bus ping per family+date (best-effort, outside the lock)."""
    for key, e in pings:
        when = date.fromisoformat(e["startDate"]).strftime("%a %b %-d")
        try:
            import agent_bus
            agent_bus.send("solomon", "operator", "alert",
                           f"Solomon · Starts — confirm a start date (contact {e['contactId']}) for {e['startDate']}",
                           {"contactId": e["contactId"], "startDate": e["startDate"]})
            import telegram_io
            telegram_io.send(html.escape(f"📅 Confirm {display_name(e)}'s start date — {when}. "
                                         "Tap Confirm on the daycare dashboard; the app login goes out that morning."),
                             dedupe_key="daycare-start:" + key)
        except Exception:  # noqa: BLE001 — a ping never blocks the lane
            pass


def tick(client, session_fn, mint_fn, now=None):
    """One lane cycle: sweep (so a moved date reverts BEFORE any send), send, ping."""
    now = now or time.time()
    error = None
    try:
        error = sweep(client, now)
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        error = f"GHL read failed: {type(e).__name__}{f' {code}' if code else ''}"
    try:
        sent = send_due(client, session_fn, mint_fn, now)
        bad = [r for r in sent if not r["ok"]]
        if bad:
            error = f"{len(bad)} start-day text(s) failed"
    except Exception as e:  # noqa: BLE001
        error = f"send failed: {type(e).__name__}"
    with _LOCK:
        st = _load()
        pings = _confirm_pings(st, now)
        st["lastRunAt"], st["error"] = _ms(now), error
        _save(st)
    _ping_confirm_window(pings)
    return error


def run_forever(client, session_fn, mint_fn):
    """Background loop (thread `daycare_starts` — Solomon's Starts lane)."""
    last = (_load().get("lastRunAt") or 0) / 1000
    time.sleep(max(0, min(INTERVAL, last + INTERVAL - time.time())))
    while True:
        err = None
        try:
            if client is None or not getattr(client, "configured", False):
                err = "Daycare GHL not configured"
            elif not forge_ops.paused():
                err = tick(client, session_fn, mint_fn)
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        forge_heartbeat.beat("daycare_starts", INTERVAL, "Solomon · Starts", error=err)
        time.sleep(INTERVAL)
