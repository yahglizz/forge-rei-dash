"""google_io.py — Google Calendar bridge for Solomon's tour booking. Stdlib only.

What it does:
  • OAuth2 — one consent click (`/api/google/oauth/start` → `/callback`) leaves a refresh
    token in FORGE_GOOGLE_TOKEN_FILE (default marcus_state/google_token.json, chmod 600,
    git-ignored). Access tokens live in memory only.
  • free_slots() — open tour times = the tour policy (forge-daycare/config/tours.json)
    minus busy time on the "ATOB Tours" calendar (Calendar freeBusy).
  • create_tour_event() / cancel_event() — one tour event. Create re-checks free/busy
    under a lock right before the insert and refuses a taken slot.

What it deliberately does NOT do: send email, invite attendees, or touch Gmail — there is
no such function here (test_google_io asserts it). Events carry no attendees and every
write passes sendUpdates=none, so Google mails nobody.

Contract: every public call returns {"ok": True, "data": …} or {"ok": False, "error": "…"};
nothing raises into callers; no token ever appears in a return value or a log line.
All HTTP goes through `_http` — the one injectable transport (tests swap it for a fake).
Env (names only): FORGE_GOOGLE_CLIENT_FILE (OAuth client JSON), FORGE_GOOGLE_TOKEN_FILE.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import forge_atomic

HERE = Path(__file__).resolve().parent
CLIENT_FILE = Path(os.environ.get("FORGE_GOOGLE_CLIENT_FILE")
                   or Path.home() / ".forge-secrets" / "forge-rei" / "keys" / "google-oauth-client.json")
TOKEN_FILE = Path(os.environ.get("FORGE_GOOGLE_TOKEN_FILE") or HERE / "marcus_state" / "google_token.json")
# Box-local like daycare.env: deploys rsync forge-daycare/ with --exclude config, so the
# owner's real policy on the box is never overwritten by (or shipped from) git.
TOURS_FILE = HERE.parent / "forge-daycare" / "config" / "tours.json"

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
CALLBACK_PATH = "/api/google/oauth/callback"
# calendar.events = create/cancel events; calendar.readonly = freeBusy + find "ATOB Tours" by
# name (calendar.events alone covers neither); openid email = show which account is connected.
SCOPES = ("openid email https://www.googleapis.com/auth/calendar.events "
          "https://www.googleapis.com/auth/calendar.readonly")
DEFAULT_CALENDAR = "ATOB Tours"
STATE_TTL = 600
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_LOCK = threading.Lock()
_BOOK_LOCK = threading.Lock()
_STATES = {}                      # oauth state -> (expires_at, redirect_uri); single-use
_ACCESS = {"token": None, "exp": 0.0}
_CAL = {}                         # calendar name -> (id, fetched_at)
_RECENT = []                      # our fresh bookings (start, end, event_id, expires_at)


class GoogleError(Exception):
    """A Google failure whose message is already safe to show (no token in it)."""


# ── transport (the ONE network path) ──────────────────────────────────────────
def _http(method, url, headers=None, body=None, timeout=10):
    """-> (status, json dict). HTTP errors come back as their status; network errors raise."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            st, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        st, raw = e.code, e.read()
    try:
        d = json.loads(raw) if raw and raw.strip() else {}
    except ValueError:
        d = {}
    return st, d if isinstance(d, dict) else {}


# ── safe errors ───────────────────────────────────────────────────────────────
def _scrub(text):
    for t in (_ACCESS.get("token"), (_token() or {}).get("refresh_token")):
        if t:
            text = text.replace(t, "[redacted]")
    return text


def _fail(e):
    msg = str(e) if isinstance(e, GoogleError) else f"{type(e).__name__}: {e}"
    return {"ok": False, "error": _scrub(msg)[:240]}


def _gerr(d):
    e = d.get("error")
    if isinstance(e, dict):
        return str(e.get("message") or e.get("status") or "")[:160]
    return f"{e or ''} {d.get('error_description') or ''}".strip()[:160]


# ── OAuth ─────────────────────────────────────────────────────────────────────
def _client():
    """The OAuth client ({client_id, client_secret, redirect_uris}) or None. Never logged."""
    try:
        d = json.loads(CLIENT_FILE.expanduser().read_text())
        c = d.get("web") or d.get("installed") or {}
        return c if c.get("client_id") and c.get("client_secret") else None
    except Exception:  # noqa: BLE001 — missing/unreadable = not configured
        return None


def configured():
    return _client() is not None


def _token():
    try:
        d = json.loads(TOKEN_FILE.expanduser().read_text())
        return d if isinstance(d, dict) and d.get("refresh_token") else None
    except Exception:  # noqa: BLE001
        return None


def redirect_uri_for(host):
    """The registered callback whose host is the browser's, or None. Google requires the
    same redirect_uri at consent and at code exchange, so it is stored with the state."""
    host = (host or "").split(",")[0].strip().lower()
    for u in (_client() or {}).get("redirect_uris") or []:
        p = urllib.parse.urlparse(u)
        if p.path == CALLBACK_PATH and p.netloc.lower() == host:
            return u
    return None


def new_state(redirect_uri, now=None):
    now = now or time.time()
    s = secrets.token_urlsafe(24)
    with _LOCK:
        for k in [k for k, v in _STATES.items() if v[0] < now]:
            _STATES.pop(k)
        _STATES[s] = (now + STATE_TTL, redirect_uri)
    return s


def take_state(state, now=None):
    """Single-use: removes it. -> the redirect_uri it was minted for, or None."""
    now = now or time.time()
    with _LOCK:
        hit = _STATES.pop(str(state or ""), None)
    return hit[1] if hit and hit[0] >= now else None


def auth_url(state, redirect_uri):
    c = _client()
    if not c:
        return {"ok": False, "error": "Google OAuth client JSON missing (FORGE_GOOGLE_CLIENT_FILE)"}
    q = {"client_id": c["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
         "scope": SCOPES, "access_type": "offline", "prompt": "consent",
         "include_granted_scopes": "true", "state": state}
    return {"ok": True, "data": AUTH_URI + "?" + urllib.parse.urlencode(q)}


def _id_account(id_token):
    # Not signature-checked: it came straight from Google's token endpoint over TLS
    # (OIDC Core 3.1.3.7), and it only labels which account is connected.
    try:
        part = str(id_token).split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("email")
    except Exception:  # noqa: BLE001
        return None


def _token_post(fields):
    c = _client()
    if not c:
        raise GoogleError("Google OAuth client JSON missing (FORGE_GOOGLE_CLIENT_FILE)")
    body = urllib.parse.urlencode({"client_id": c["client_id"],
                                   "client_secret": c["client_secret"], **fields}).encode()
    return _http("POST", TOKEN_URI, {"Content-Type": "application/x-www-form-urlencoded"}, body)


def _keep_access(d):
    with _LOCK:
        _ACCESS.update(token=d["access_token"],
                       exp=time.time() + int(d.get("expires_in") or 3600) - 60)


def exchange_code(code, redirect_uri):
    """The consent callback: code -> refresh token on disk (0600). -> {ok, data:{account}}"""
    try:
        st, d = _token_post({"code": code, "redirect_uri": redirect_uri,
                             "grant_type": "authorization_code"})
        if st != 200 or not d.get("access_token"):
            return {"ok": False, "error": f"token exchange failed ({st}): {_gerr(d)}"}
        old = _token() or {}
        refresh = d.get("refresh_token") or old.get("refresh_token")
        if not refresh:
            return {"ok": False, "error": "Google sent no refresh token — remove the app's access "
                                          "in the Google account's security settings, then connect again"}
        email = _id_account(d.get("id_token")) or old.get("email")
        forge_atomic.atomic_write_json(TOKEN_FILE.expanduser(), {
            "refresh_token": refresh, "email": email, "scope": d.get("scope") or "",
            "connectedAt": int(time.time())}, mode=0o600)
        _keep_access(d)
        with _LOCK:
            _CAL.clear()
        return {"ok": True, "data": {"account": email, "scope": d.get("scope") or ""}}
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _access_token(force=False):
    with _LOCK:
        if not force and _ACCESS["token"] and time.time() < _ACCESS["exp"]:
            return _ACCESS["token"]
    t = _token()
    if not t:
        raise GoogleError("Google not connected — open /api/google/oauth/start once")
    st, d = _token_post({"refresh_token": t["refresh_token"], "grant_type": "refresh_token"})
    if st != 200 or not d.get("access_token"):
        hint = " — reconnect Google (/api/google/oauth/start)" if d.get("error") == "invalid_grant" else ""
        raise GoogleError(f"token refresh failed ({st}): {_gerr(d)}{hint}")
    _keep_access(d)
    return d["access_token"]


def _api(method, path, params=None, body=None):
    """Calendar API call; one retry with a fresh access token on 401."""
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    for force in (False, True):
        hdr = {"Authorization": "Bearer " + _access_token(force), "Accept": "application/json"}
        if data is not None:
            hdr["Content-Type"] = "application/json"
        st, d = _http(method, url, hdr, data)
        if st != 401:
            break
    return st, d


# ── tour policy (forge-daycare/config/tours.json) ─────────────────────────────
def tours_config():
    """The tour policy dict, or None when missing/unreadable (the feature is simply off)."""
    try:
        d = json.loads(TOURS_FILE.read_text())
        return d if isinstance(d, dict) and isinstance(d.get("locations"), dict) else None
    except Exception:  # noqa: BLE001
        return None


def is_placeholder(cfg):
    return "PLACEHOLDER" in str((cfg or {}).get("_note") or "").upper()


def _policy(cfg, loc):
    """Top-level defaults overlaid with the location's own keys (days/hours/calendarName…)."""
    p = ((cfg or {}).get("locations") or {}).get(loc)
    return {**cfg, **p} if isinstance(p, dict) else None


def _tz(pol):
    return ZoneInfo(pol.get("timezone") or "America/New_York")


def _day_slots(pol, day):
    """Candidate (start, end) epoch pairs for one local date — the policy only, no busy check.
    Wall-clock times go through zoneinfo, so DST days are right."""
    if DAYS[day.weekday()] not in (pol.get("days") or []) or day.isoformat() in (pol.get("closedDates") or []):
        return []
    tz, step = _tz(pol), int(pol.get("slotMinutes") or 30) * 60
    h1, m1 = map(int, str(pol["start"]).split(":"))
    h2, m2 = map(int, str(pol["end"]).split(":"))
    t = int(datetime(day.year, day.month, day.day, h1, m1, tzinfo=tz).timestamp())
    close = int(datetime(day.year, day.month, day.day, h2, m2, tzinfo=tz).timestamp())
    out = []
    while t + step <= close:
        out.append((t, t + step))
        t += step
    return out


def _clear(s, e, busy, buf):
    return all(be <= s - buf or bs >= e + buf for bs, be in busy)


def _slot(tz, s, e):
    dt = datetime.fromtimestamp(s, tz)
    return {"id": dt.strftime("%Y-%m-%dT%H:%M"), "start": s, "end": e,
            "label": f"{DAYS[dt.weekday()]} {MONTHS[dt.month - 1]} {dt.day}, "
                     f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"}


def slots(cfg, loc, busy, now, days=7):
    """Pure: open slots for `loc` over the next `days` local dates — inside the day's hours,
    at least minNoticeHours out, and no busy interval within bufferMinutes.
    -> [{id, start, end, label}] oldest first ([] for an unknown location)."""
    pol = _policy(cfg, loc)
    if not pol:
        return []
    tz, buf = _tz(pol), int(pol.get("bufferMinutes") or 0) * 60
    earliest = now + float(pol.get("minNoticeHours", 2)) * 3600
    today = datetime.fromtimestamp(now, tz).date()
    return [_slot(tz, s, e) for i in range(days)
            for s, e in _day_slots(pol, today + timedelta(days=i))
            if s >= earliest and _clear(s, e, busy, buf)]


def spread(free, n=3):
    """Up to n slots, one per day first (a real choice for the parent), then the earliest rest."""
    firsts, seen = [], set()
    for s in free:
        if s["id"][:10] not in seen:
            seen.add(s["id"][:10])
            firsts.append(s)
    pick = firsts[:n]
    pick += [s for s in free if s not in pick][:n - len(pick)]
    return sorted(pick, key=lambda s: s["start"])


# ── Calendar reads ────────────────────────────────────────────────────────────
def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def _calendar_id(name):
    with _LOCK:
        hit = _CAL.get(name)
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    # ponytail: one page of 250 writable calendars; paginate if an account ever has more
    st, d = _api("GET", "/users/me/calendarList", {"maxResults": 250, "minAccessRole": "writer"})
    if st != 200:
        raise GoogleError(f"calendar list failed ({st}): {_gerr(d)}")
    for c in d.get("items") or []:
        if str(c.get("summary") or "").strip().lower() == name.strip().lower():
            with _LOCK:
                _CAL[name] = (c["id"], time.time())
            return c["id"]
    raise GoogleError(f"calendar '{name}' not found (or not writable) on the connected Google account")


def _busy(cal_id, t0, t1):
    st, d = _api("POST", "/freeBusy", body={"timeMin": _iso(t0), "timeMax": _iso(t1),
                                            "items": [{"id": cal_id}]})
    cal = (d.get("calendars") or {}).get(cal_id) or {}
    if st != 200 or cal.get("errors"):
        raise GoogleError(f"free/busy failed ({st}): {_gerr(d) if st != 200 else cal.get('errors')}")
    out = [(_ts(b["start"]), _ts(b["end"])) for b in cal.get("busy") or []]
    now = time.time()
    with _LOCK:   # our own just-made bookings count even if freeBusy lags a moment
        _RECENT[:] = [r for r in _RECENT if r[3] > now]
        out += [(r[0], r[1]) for r in _RECENT]
    return out


def free_slots(location_id, days=7, now=None):
    """Open tour slots for one center (a `loc-*` tag) over the next `days` days.
    -> {ok, data:[{id, start, end, label}]}"""
    try:
        now = now or time.time()
        cfg = tours_config()
        pol = _policy(cfg, location_id) if cfg else None
        if not pol:
            return {"ok": False, "error": f"no tour policy for {location_id or 'that center'}"}
        cands = slots(cfg, location_id, [], now, days)
        if not cands:
            return {"ok": True, "data": []}
        buf = int(pol.get("bufferMinutes") or 0) * 60
        busy = _busy(_calendar_id(pol.get("calendarName") or DEFAULT_CALENDAR),
                     cands[0]["start"] - buf, cands[-1]["end"] + buf)
        return {"ok": True, "data": slots(cfg, location_id, busy, now, days)}
    except Exception as e:  # noqa: BLE001
        return _fail(e)


# ── Calendar writes (only ever on the owner's tap — see daycare_tours.book) ──
def create_tour_event(location_id, start, contact_id="", child_first="", parent_first="", now=None):
    """Book one tour. Re-checks free/busy under a lock right before the insert, so two
    approvals can never book one slot (the second gets error "slot_taken"). No attendees,
    sendUpdates=none — Google emails nobody. -> {ok, data:{eventId, id, start, end, label,
    location, center}}"""
    try:
        now = now or time.time()
        cfg = tours_config()
        pol = _policy(cfg, location_id) if cfg else None
        if not pol:
            return {"ok": False, "error": f"no tour policy for {location_id or 'that center'}"}
        tz, s = _tz(pol), int(start)
        end = next((b for a, b in _day_slots(pol, datetime.fromtimestamp(s, tz).date()) if a == s), None)
        if end is None or s <= now:
            return {"ok": False, "error": "not a bookable tour time under the tour policy"}
        buf = int(pol.get("bufferMinutes") or 0) * 60
        # ponytail: one process-wide lock (the box runs one connector); a second writer
        # process would need a calendar-side guard.
        with _BOOK_LOCK:
            cal = _calendar_id(pol.get("calendarName") or DEFAULT_CALENDAR)
            if not _clear(s, end, _busy(cal, s - buf, end + buf), buf):
                return {"ok": False, "error": "slot_taken"}
            who = child_first or (f"{parent_first}'s family" if parent_first else "New family")
            center = pol.get("label") or location_id
            body = {"summary": f"Tour — {who} — {center}",
                    "location": pol.get("address") or center,
                    "description": "Tour booked by Solomon (owner-approved text)."
                                   + (f"\nGHL contact: {contact_id}" if contact_id else ""),
                    "start": {"dateTime": datetime.fromtimestamp(s, tz).isoformat(), "timeZone": tz.key},
                    "end": {"dateTime": datetime.fromtimestamp(end, tz).isoformat(), "timeZone": tz.key},
                    "extendedProperties": {"private": {"forgeContactId": str(contact_id or ""),
                                                       "forgeLocation": location_id}}}
            st, d = _api("POST", f"/calendars/{urllib.parse.quote(cal, safe='')}/events",
                         {"sendUpdates": "none"}, body)
            if st not in (200, 201) or not d.get("id"):
                return {"ok": False, "error": f"event insert failed ({st}): {_gerr(d)}"}
            with _LOCK:
                _RECENT.append((s, end, d["id"], time.time() + 900))
        return {"ok": True, "data": {"eventId": d["id"], **_slot(tz, s, end),
                                     "location": location_id, "center": center}}
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def cancel_event(event_id, location_id=None):
    """Delete one tour event (already gone = ok). sendUpdates=none."""
    try:
        cfg = tours_config() or {}
        pol = _policy(cfg, location_id) or cfg
        cal = _calendar_id(pol.get("calendarName") or DEFAULT_CALENDAR)
        q = urllib.parse.quote
        st, d = _api("DELETE", f"/calendars/{q(cal, safe='')}/events/{q(str(event_id), safe='')}",
                     {"sendUpdates": "none"})
        with _LOCK:
            _RECENT[:] = [r for r in _RECENT if r[2] != event_id]
        if st in (200, 204, 404, 410):
            return {"ok": True, "data": {"eventId": event_id, "gone": st in (404, 410)}}
        return {"ok": False, "error": f"cancel failed ({st}): {_gerr(d)}"}
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def status():
    """GET /api/google/status — {configured, connected, account, calendarFound, …}. No secrets."""
    cfg, t = tours_config(), _token()
    name = (cfg or {}).get("calendarName") or DEFAULT_CALENDAR
    out = {"ok": True, "flag": os.environ.get("FORGE_GOOGLE_CALENDAR", "0") == "1",
           "configured": configured(), "connected": bool(t), "account": (t or {}).get("email"),
           "toursConfig": bool(cfg), "placeholderPolicy": is_placeholder(cfg) if cfg else None,
           "calendarName": name, "calendarFound": None, "error": None}
    if t and out["configured"]:
        try:
            _calendar_id(name)
            out["calendarFound"] = True
        except Exception as e:  # noqa: BLE001
            out["calendarFound"], out["error"] = False, _fail(e)["error"]
    return out
