#!/usr/bin/env python3
"""google_cal_io.py — Google Calendar writes for the daycare calendar lane (stdlib urllib, no deps).

Auth: an OAuth refresh token for yahjair@ with scope `calendar.events` only, in the box's
forge-daycare/config/daycare.env as GOOGLE_CAL_REFRESH_YAHJAIR, with the same Desktop client as
gmail_io.py (GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET). A service account cannot write here: Workspace
limits outside accounts to read access (spec: Brand Kit docs/google-calendar/).

That token can edit every calendar on yahjair@, so _guard() refuses any calendar but GOOGLE_CAL_ID
and GOOGLE_CAL_ID_QA, and refuses any event with attendees (a guest would email a family).
Errors are typed and never carry a token or an upstream body. Nothing here logs event contents.
Tests: python3 test_google_cal_io.py
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3/calendars"
_UA = "forge-reios/1.0 (+google_cal_io)"
_SKEW = 60                    # refresh ~60 s before Google's expiry
_AUTH_DEAD_TTL = 15 * 60      # a rejected token: stop calling for 15 min (gmail_io pattern)

_LOCK = threading.Lock()
_TOK = {"access": "", "exp": 0.0}
_DEAD = [0.0]


class CalError(RuntimeError):
    """Any Calendar failure. The message is safe to show: no token, no upstream body."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class CalAuthError(CalError):
    """Google refused the login: the owner must re-consent."""


def _urlopen(req, timeout):       # the one network seam (tests swap it)
    return urllib.request.urlopen(req, timeout=timeout)


def _env():
    import daycare_supabase
    return daycare_supabase._read_env()


def _pick(name):
    """Same picker as the daycare modules: process env first, then daycare.env."""
    try:
        values = _env()
    except Exception:  # noqa: BLE001 — config IO never breaks a read
        values = {}
    return (os.environ.get(name) or values.get(name) or "").strip()


def _cfg():
    return {"client_id": _pick("GMAIL_CLIENT_ID"), "client_secret": _pick("GMAIL_CLIENT_SECRET"),
            "refresh_token": _pick("GOOGLE_CAL_REFRESH_YAHJAIR")}


def configured():
    return all(_cfg().values())


def calendars():
    """{'live': id, 'qa': id}: the only two calendars this module will touch."""
    return {"live": _pick("GOOGLE_CAL_ID"), "qa": _pick("GOOGLE_CAL_ID_QA")}


def event_id(key):
    """Stable event id for a lane key: hex is inside Google's id alphabet (a-v, 0-9)."""
    return hashlib.sha256(str(key).encode()).hexdigest()


def _guard(calendar_id):
    if not calendar_id or calendar_id not in calendars().values():
        raise CalError("refused: not one of the two daycare calendars")


def _access_token():
    with _LOCK:
        if time.time() < _DEAD[0]:
            raise CalAuthError("Google rejected the calendar login recently: re-consent needed")
        if _TOK["access"] and time.time() < _TOK["exp"] - _SKEW:
            return _TOK["access"]
        c = _cfg()
        if not all(c.values()):
            raise CalError("Calendar is not connected (GOOGLE_CAL_REFRESH_YAHJAIR missing)")
        req = urllib.request.Request(
            TOKEN_URL, data=urllib.parse.urlencode({**c, "grant_type": "refresh_token"}).encode(),
            method="POST", headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": _UA})
        try:
            with _urlopen(req, 30) as r:
                d = json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403):        # invalid_grant / revoked consent
                _DEAD[0] = time.time() + _AUTH_DEAD_TTL
                raise CalAuthError(f"Google rejected the calendar token (HTTP {e.code})", e.code) from None
            raise CalError(f"Google token endpoint HTTP {e.code}", e.code) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise CalError(f"Google token endpoint unreachable: {type(e).__name__}") from None
        tok = str(d.get("access_token") or "")
        if not tok:
            raise CalError("Google returned no access token")
        _TOK.update(access=tok, exp=time.time() + float(d.get("expires_in") or 3600))
        return tok


def _call(method, calendar_id, event=None, body=None, retry=True):
    path = f"{API}/{urllib.parse.quote(calendar_id, safe='')}/events"
    if event:
        path += "/" + urllib.parse.quote(event, safe="")
    req = urllib.request.Request(
        path + "?sendUpdates=none", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json",
                 "User-Agent": _UA})
    try:
        with _urlopen(req, 30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        if e.code == 401 and retry:             # access token died early: one fresh refresh
            with _LOCK:
                _TOK.update(access="", exp=0.0)
            return _call(method, calendar_id, event, body, retry=False)
        if e.code == 401:
            raise CalAuthError("Calendar refused the access token (HTTP 401)", 401) from None
        raise CalError(f"Calendar HTTP {e.code}", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise CalError(f"Calendar unreachable: {type(e).__name__}") from None


def put_event(calendar_id, eid, body):
    """Create the event, or replace it when the id exists (a move, a lost ledger, or a rebook
    after a cancel: a deleted id still answers 409, and the replace brings it back).
    Returns Google's link to the event."""
    _guard(calendar_id)
    if body.get("attendees"):
        raise CalError("refused: daycare events never have guests")
    try:
        return _call("POST", calendar_id, body={**body, "id": eid}).get("htmlLink") or ""
    except CalError as e:
        if e.code != 409:
            raise
    return _call("PUT", calendar_id, eid, {**body, "status": "confirmed"}).get("htmlLink") or ""


def remove(calendar_id, eid):
    """Delete the event. Already gone counts as done."""
    _guard(calendar_id)
    try:
        _call("DELETE", calendar_id, eid)
    except CalError as e:
        if e.code not in (404, 410):
            raise
