"""Self-check for google_io (tour booking): slot math (hours, buffer, busy, past, DST),
no double-booking under concurrent approvals, OAuth state + token handling with no token
ever in a return value or a log line, missing config = feature off, and no email surface.
Fake transport only — no network, no Google. Run: python3 test_google_io.py"""
import base64
import contextlib
import inspect
import io
import json
import os
import stat
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import google_io as g

ET = ZoneInfo("America/New_York")
TMP = Path(tempfile.mkdtemp())
CLIENT = {"web": {"client_id": "cid-123.apps.googleusercontent.com", "client_secret": "SECRET-CLIENT-xyz",
                  "redirect_uris": ["https://forge-reios.tail0a2dda.ts.net/api/google/oauth/callback",
                                    "http://localhost:7799/api/google/oauth/callback"]}}
REFRESH, ACCESS = "fake-refresh-token-abc", "fake-access-token-def"   # not Google-shaped: no secret-scanner noise
CFG = {"_note": "real policy", "calendarName": "ATOB Tours", "timezone": "America/New_York",
       "days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "start": "10:00", "end": "16:00",
       "slotMinutes": 30, "bufferMinutes": 15, "minNoticeHours": 2, "closedDates": [],
       "locations": {"loc-921-n-18th": {"label": "921 N 18th St",
                                        "address": "921 N 18th St, Philadelphia, PA 19130"}}}
LOC = "loc-921-n-18th"


def et(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ET).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeGoogle:
    """Stands in for google_io._http: token endpoint, calendarList, freeBusy, events."""

    def __init__(self, busy=(), delay=0.0):
        self.busy, self.delay, self.events, self.calls, self.bodies = list(busy), delay, {}, [], []
        self.refresh_ok, self.n, self.lock = True, 0, threading.Lock()

    def __call__(self, method, url, headers=None, body=None, timeout=20):
        self.calls.append((method, url))
        path = urllib.parse.urlparse(url).path
        if url.startswith(g.TOKEN_URI):
            f = dict(urllib.parse.parse_qsl(body.decode()))
            assert f["client_secret"] == CLIENT["web"]["client_secret"]
            if f["grant_type"] == "authorization_code":
                claims = base64.urlsafe_b64encode(json.dumps({"email": "owner@example.com"}).encode()).decode()
                return 200, {"access_token": ACCESS, "expires_in": 3600, "refresh_token": REFRESH,
                             "scope": g.SCOPES, "id_token": f"h.{claims.rstrip('=')}.s"}
            if self.refresh_ok:
                return 200, {"access_token": ACCESS, "expires_in": 3600}
            return 400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
        assert headers["Authorization"] == "Bearer " + ACCESS
        if path.endswith("/users/me/calendarList"):
            return 200, {"items": [{"id": "primary@x", "summary": "Owner"},
                                   {"id": "tours@group.calendar.google.com", "summary": "ATOB Tours"}]}
        if path.endswith("/freeBusy"):
            b = json.loads(body)
            t0, t1 = g._ts(b["timeMin"]), g._ts(b["timeMax"])
            with self.lock:
                spans = self.busy + list(self.events.values())
            time.sleep(self.delay)                       # answer is in flight: widen any race window
            return 200, {"calendars": {b["items"][0]["id"]: {
                "busy": [{"start": iso(s), "end": iso(e)} for s, e in spans if s < t1 and e > t0]}}}
        if method == "POST" and path.endswith("/events"):
            b = json.loads(body)
            time.sleep(self.delay)                       # insert in flight, not yet visible
            self.bodies.append((url, b))
            with self.lock:
                self.n += 1
                eid = f"ev{self.n}"
                self.events[eid] = (g._ts(b["start"]["dateTime"]), g._ts(b["end"]["dateTime"]))
            return 200, {"id": eid}
        if method == "DELETE":
            eid = urllib.parse.unquote(path.rsplit("/", 1)[1])
            with self.lock:
                gone = self.events.pop(eid, None)
            return (204 if gone else 410), {}
        return 404, {"error": {"message": "unexpected " + path}}


def setup(cfg=CFG, connected=True, fake=None):
    g._STATES.clear()
    g._CAL.clear()
    g._RECENT.clear()
    g._ACCESS.update(token=None, exp=0)
    g.CLIENT_FILE = TMP / "client.json"
    g.CLIENT_FILE.write_text(json.dumps(CLIENT))
    g.TOKEN_FILE = TMP / f"token-{time.time_ns()}.json"
    if connected:
        g.TOKEN_FILE.write_text(json.dumps({"refresh_token": REFRESH, "email": "owner@example.com"}))
    g.TOURS_FILE = TMP / f"tours-{time.time_ns()}.json"
    if cfg is not None:
        g.TOURS_FILE.write_text(json.dumps(cfg))
    g._http = fake or FakeGoogle()
    return g._http


def test_slot_math():
    now = et(2026, 10, 21, 10, 30)                                  # Wed 10:30 ET
    s = g.slots(CFG, LOC, [], now, days=7)                          # Wed..Tue
    days = {x["id"][:10] for x in s}
    assert s[0]["id"] == "2026-10-21T12:30", s[0]                   # 2 h notice: nothing before 12:30
    assert all(x["start"] >= now + 7200 for x in s)                 # never a past / too-soon slot
    assert "2026-10-24" not in days and "2026-10-25" not in days    # Sat/Sun closed
    assert sum(1 for x in s if x["id"].startswith("2026-10-22")) == 12      # 10:00..15:30
    assert max(datetime.fromtimestamp(x["end"], ET).hour * 60 + datetime.fromtimestamp(x["end"], ET).minute
               for x in s) == 16 * 60                               # last tour ends at close
    assert s[0]["label"] == "Wed Oct 21, 12:30 PM" and s[0]["end"] - s[0]["start"] == 1800
    # a busy 11:00-11:30 on Thu blocks 10:30, 11:00, 11:30 (15-min buffer) but not 10:00 or 12:00
    busy = [(et(2026, 10, 22, 11), et(2026, 10, 22, 11, 30))]
    thu = [x["id"][11:] for x in g.slots(CFG, LOC, busy, now) if x["id"].startswith("2026-10-22")]
    assert thu[:3] == ["10:00", "12:00", "12:30"], thu
    # closed date + unknown center
    closed = dict(CFG, closedDates=["2026-10-23"])
    assert not any(x["id"].startswith("2026-10-23") for x in g.slots(closed, LOC, [], now))
    assert g.slots(CFG, "loc-nowhere", [], now) == []
    # per-location override wins over the top-level default
    sat = dict(CFG, locations={LOC: dict(CFG["locations"][LOC], days=["Sat"])})
    assert {x["id"][:10] for x in g.slots(sat, LOC, [], now)} == {"2026-10-24"}


def test_dst():
    # DST ends Sun 2026-11-01: Fri 10:00 EDT = 14:00 UTC, Mon 10:00 EST = 15:00 UTC
    s = g.slots(CFG, LOC, [], et(2026, 10, 30, 7), days=4)
    fri = next(x for x in s if x["id"] == "2026-10-30T10:00")
    mon = next(x for x in s if x["id"] == "2026-11-02T10:00")
    assert datetime.fromtimestamp(fri["start"], timezone.utc).hour == 14
    assert datetime.fromtimestamp(mon["start"], timezone.utc).hour == 15
    # DST starts Sun 2027-03-14: Fri 10:00 EST = 15:00 UTC, Mon 10:00 EDT = 14:00 UTC
    s = g.slots(CFG, LOC, [], et(2027, 3, 12, 7), days=4)
    assert datetime.fromtimestamp(next(x for x in s if x["id"] == "2027-03-12T10:00")["start"], timezone.utc).hour == 15
    assert datetime.fromtimestamp(next(x for x in s if x["id"] == "2027-03-15T10:00")["start"], timezone.utc).hour == 14
    for x in s:                                                     # every slot on the wall-clock grid
        lt = datetime.fromtimestamp(x["start"], ET)
        assert 10 <= lt.hour < 16 and lt.minute in (0, 30), x


def test_spread():
    s = g.slots(CFG, LOC, [], et(2026, 10, 21, 7), days=7)
    pick = g.spread(s, 3)
    assert [x["id"] for x in pick] == ["2026-10-21T10:00", "2026-10-22T10:00", "2026-10-23T10:00"]
    assert g.spread(s[:2], 3) == s[:2] and g.spread([], 3) == []


def test_free_slots_reads_calendar():
    fake = setup(fake=FakeGoogle(busy=[(et(2026, 10, 22, 10), et(2026, 10, 22, 12))]))
    r = g.free_slots(LOC, now=et(2026, 10, 21, 7))
    assert r["ok"], r
    assert not any(x["id"].startswith("2026-10-22T1") and x["id"] < "2026-10-22T12:15" for x in r["data"])
    assert any(x["id"] == "2026-10-22T12:30" for x in r["data"])
    fb = [u for m, u in fake.calls if u.endswith("/freeBusy")]
    assert len(fb) == 1                                             # one freeBusy for the whole week
    assert g.free_slots(LOC, now=et(2026, 10, 21, 7))["ok"]
    assert sum(1 for m, u in fake.calls if "calendarList" in u) == 1    # calendar id cached


def test_no_double_book():
    fake = setup(fake=FakeGoogle(delay=0.05))
    now = et(2026, 10, 21, 7)
    slot = et(2026, 10, 22, 10)
    out = []
    ts = [threading.Thread(target=lambda c=c: out.append(g.create_tour_event(LOC, slot, contact_id=c, now=now)))
          for c in ("cA", "cB")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    oks = [r for r in out if r["ok"]]
    assert len(oks) == 1 and len(fake.events) == 1, out             # two simultaneous approvals -> one event
    assert [r["error"] for r in out if not r["ok"]] == ["slot_taken"]
    assert g.create_tour_event(LOC, slot, contact_id="cC", now=now)["error"] == "slot_taken"
    # 10:30 is inside the 15-min buffer of the 10:00 tour; 11:00 is fine
    assert g.create_tour_event(LOC, et(2026, 10, 22, 10, 30), now=now)["error"] == "slot_taken"
    assert g.create_tour_event(LOC, et(2026, 10, 22, 11), child_first="Ava", now=now)["ok"]
    # never outside policy or in the past
    assert not g.create_tour_event(LOC, et(2026, 10, 24, 10), now=now)["ok"]          # Saturday
    assert not g.create_tour_event(LOC, et(2026, 10, 22, 10, 10), now=now)["ok"]      # off-grid
    assert not g.create_tour_event(LOC, et(2026, 10, 20, 10), now=now)["ok"]          # past
    # the event: no attendees, Google told to email nobody, right title/place/time zone
    url, body = fake.bodies[-1]
    assert "sendUpdates=none" in url and "attendees" not in body
    assert body["summary"] == "Tour — Ava — 921 N 18th St" and body["location"].startswith("921 N 18th")
    assert body["start"]["timeZone"] == "America/New_York" and body["start"]["dateTime"].endswith("-04:00")
    # cancel frees the slot (and an unknown id is already gone = ok)
    eid = oks[0]["data"]["eventId"]
    assert g.cancel_event(eid, LOC)["ok"] and eid not in fake.events
    assert g.create_tour_event(LOC, slot, contact_id="cC", now=now)["ok"]
    assert g.cancel_event("nope", LOC)["data"]["gone"] is True


def test_oauth_and_no_token_leak():
    fake = setup(connected=False)
    logs, results = io.StringIO(), []
    with contextlib.redirect_stdout(logs):
        assert g.redirect_uri_for("localhost:7799") == CLIENT["web"]["redirect_uris"][1]
        assert g.redirect_uri_for("forge-reios.tail0a2dda.ts.net") == CLIENT["web"]["redirect_uris"][0]
        assert g.redirect_uri_for("evil.example") is None and g.redirect_uri_for("") is None
        uri = CLIENT["web"]["redirect_uris"][1]
        st = g.new_state(uri)
        url = g.auth_url(st, uri)["data"]
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        assert q["state"] == st and q["access_type"] == "offline" and q["redirect_uri"] == uri
        assert "client_secret" not in url and "SECRET" not in url and "gmail" not in q["scope"]
        assert g.take_state(st) == uri and g.take_state(st) is None            # single-use
        old = g.new_state(uri, now=time.time() - 3600)
        assert g.take_state(old) is None                                       # expired
        assert g.status()["connected"] is False and g.status()["calendarFound"] is None
        results.append(g.exchange_code("4/the-code", uri))
        assert results[-1]["ok"] and results[-1]["data"]["account"] == "owner@example.com"
        assert stat.S_IMODE(os.stat(g.TOKEN_FILE).st_mode) == 0o600            # token file 0600
        assert json.loads(g.TOKEN_FILE.read_text())["refresh_token"] == REFRESH
        results.append(g.status())
        assert results[-1]["connected"] and results[-1]["calendarFound"] is True
        results.append(g.free_slots(LOC, now=et(2026, 10, 21, 7)))
        results.append(g.create_tour_event(LOC, et(2026, 10, 22, 10), now=et(2026, 10, 21, 7)))
        # refresh token revoked -> clear error, still no token anywhere
        g._ACCESS.update(token=None, exp=0)
        fake.refresh_ok = False
        results.append(g.free_slots(LOC, now=et(2026, 10, 21, 7)))
        assert not results[-1]["ok"] and "reconnect" in results[-1]["error"]
        # a transport error that carries a token in its text is redacted
        g._ACCESS.update(token=ACCESS, exp=time.time() + 600)

        def boom(*a, **k):
            raise RuntimeError(f"socket died while sending {ACCESS} / {REFRESH}")
        g._http = boom
        results.append(g.free_slots(LOC, now=et(2026, 10, 21, 7)))
        assert "[redacted]" in results[-1]["error"]
    blob = logs.getvalue() + repr(results)
    for secret in (REFRESH, ACCESS, CLIENT["web"]["client_secret"]):
        assert secret not in blob, secret


def test_missing_config_is_off():
    fake = setup(cfg=None)
    assert g.tours_config() is None
    r = g.free_slots(LOC, now=et(2026, 10, 21, 7))
    assert not r["ok"] and fake.calls == []                         # no policy -> no Google call at all
    assert not g.create_tour_event(LOC, et(2026, 10, 22, 10))["ok"] and fake.calls == []
    assert g.status()["toursConfig"] is False
    g.TOURS_FILE.write_text("{not json")
    assert g.tours_config() is None
    setup(cfg={"_note": "PLACEHOLDER tour policy - owner must replace", "locations": {}})
    assert g.is_placeholder(g.tours_config()) and g.status()["placeholderPolicy"] is True
    # the committed template is valid, loud, and covers the three centers
    tpl = json.loads((Path(__file__).resolve().parent.parent / "forge-daycare" / "config" / "tours.json").read_text())
    assert g.is_placeholder(tpl) and set(tpl["locations"]) == {
        "loc-921-n-18th", "loc-2318-cecil-b-moore", "loc-1923-cecil-b-moore"}
    assert tpl["calendarName"] == "ATOB Tours" and tpl["slotMinutes"] == 30 and tpl["bufferMinutes"] == 15


def test_no_email_surface():
    names = [n for n, v in vars(g).items() if callable(v) and not n.startswith("__")]
    assert not [n for n in names if any(w in n.lower() for w in ("mail", "send", "invite"))], names
    src = inspect.getsource(g).lower()
    assert "gmail.googleapis" not in src and "/gmail/" not in src and "auth/gmail" not in src


if __name__ == "__main__":
    test_slot_math()
    test_dst()
    test_spread()
    test_free_slots_reads_calendar()
    test_no_double_book()
    test_oauth_and_no_token_leak()
    test_missing_config_is_off()
    test_no_email_surface()
    print("test_google_io: all passed")
