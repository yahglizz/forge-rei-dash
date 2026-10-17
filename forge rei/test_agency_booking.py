"""Self-check for ClientForge "Book a call" (agency_booking + its routes on PortalHandler).

Slot math (DST, notice, buffer, closed dates, window), double-book refusal, one future call
per email, honeypot, rate limit, validation, ref/phone -> Call Sheet demo_booked, cancel frees
the slot, Google on (fake) inserts with sendUpdates=none and Google failure falls back to local,
Owner Actions row, and the public portal listener 404s on every non-booking path.
Temp state only, fake Google, Telegram stubbed — no network, no Claude.
Run: python3 test_agency_booking.py
"""
import json
import os
import tempfile
import threading
import types
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TMP = Path(tempfile.mkdtemp())
os.environ["FORGE_AGENCY_BOOKINGS_STATE"] = str(TMP / "bookings.json")
os.environ.setdefault("FORGE_ACTION_LOG", str(TMP / "actions.jsonl"))

import agency_booking as ab  # noqa: E402
import agency_callsheet as cs  # noqa: E402
import google_io as g  # noqa: E402
import owner_actions as oa  # noqa: E402
import telegram_io  # noqa: E402
import test_google_io as tg  # noqa: E402 — FakeGoogle + setup()

ET = ZoneInfo("America/New_York")
CFG = dict(ab.DEFAULTS, closedDates=["2026-10-21"])
ab.CONFIG_FILE = TMP / "booking.json"
ab.CONFIG_FILE.write_text(json.dumps(CFG))
cs.STATE = TMP / "callsheet.json"
PINGS = []
telegram_io.send_biz = lambda biz, text, **kw: PINGS.append((biz, text)) or {"ok": True}


def et(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=ET).timestamp())


def google_off():
    g.CLIENT_FILE = TMP / "no-client.json"
    g.TOKEN_FILE = TMP / "no-token.json"
    g._ACCESS.update(token=None, exp=0)
    g._CAL.clear()
    g._RECENT.clear()

    def boom(*a, **k):
        raise AssertionError("network used while Google is off")
    g._http = boom


def reset():
    ab.STATE.write_text(json.dumps({"bookings": []}))
    ab._HITS.clear()
    ab._BUSY_CACHE.update(at=0.0, key=None, busy=[])
    PINGS.clear()
    google_off()


NOW = et(2026, 10, 19, 8, 0)          # Mon 08:00 ET


def ids(now=NOW):
    r = ab.slots(now=now)
    assert r["ok"], r
    return [s["id"] for s in r["slots"]]


def person(i, start, **kw):
    p = {"name": f"Pat {i}", "business": f"Shop {i}", "email": f"pat{i}@example.com",
         "start": start, "need": ["website"], "notes": "", "phone": "", "website": ""}
    p.update(kw)
    return p


def test_slot_math():
    reset()
    s = ids()
    mon = [x for x in s if x.startswith("2026-10-19")]
    assert mon[0] == "2026-10-19T12:00" and mon[-1] == "2026-10-19T16:30" and len(mon) == 10, mon  # 4 h notice
    tue = [x for x in s if x.startswith("2026-10-20")]
    assert tue[0] == "2026-10-20T10:00" and len(tue) == 14, tue                # 10:00..16:30, ends by 17:00
    assert not any(x.startswith(("2026-10-24", "2026-10-25")) for x in s)       # weekend closed
    assert not any(x.startswith("2026-10-21") for x in s)                       # closedDates
    assert max(s) < "2026-11-09" and any(x.startswith("2026-11-06") for x in s)  # 21-day window
    # DST ends Sun 2026-11-01: 10:00 wall clock is 14:00Z before, 15:00Z after.
    r = {x["id"]: x for x in ab.slots(now=NOW)["slots"]}
    utc = lambda k: datetime.fromtimestamp(r[k]["start"], timezone.utc).hour  # noqa: E731
    assert utc("2026-10-30T10:00") == 14 and utc("2026-11-02T10:00") == 15
    assert all(x["end"] - x["start"] == 1800 for x in r.values())
    info = ab.slots(now=NOW)["event"]
    assert info["title"] == "Free 30-min growth call" and info["durationMin"] == 30
    assert set(info) == {"title", "host", "description", "durationMin", "timezone", "daysAhead"}


def test_book_buffer_double_book_and_email():
    reset()
    t = et(2026, 10, 20, 12, 0)
    r = ab.create(person(1, t), "1.1.1.1", now=NOW)
    assert r["ok"] and r["booking"]["start"] == t and r["booking"]["end"] == t + 1800, r
    assert "email" not in r["booking"] and "id" not in r["booking"]                 # public echo only
    s = ids()
    for gone in ("2026-10-20T11:30", "2026-10-20T12:00", "2026-10-20T12:30"):     # 15-min buffer
        assert gone not in s, gone
    assert "2026-10-20T11:00" in s and "2026-10-20T13:00" in s
    assert ab.create(person(2, t), "1.1.1.2", now=NOW)["error"] == "slot_taken"
    assert ab.create(person(3, t + 1800), "1.1.1.3", now=NOW)["error"] == "slot_taken"  # buffer
    again = ab.create(person(1, et(2026, 10, 22, 10)), "1.1.1.4", now=NOW)
    assert again["error"] == "already_booked", again                                   # 1 future / email
    up = ab.upcoming(now=NOW)
    assert up["count"] == 1 and up["bookings"][0]["email"] == "pat1@example.com"
    assert up["bookings"][0]["when"].endswith("ET")
    assert PINGS and PINGS[0][0] == "agency" and "Call booked" in PINGS[0][1]


def test_concurrent_double_book():
    reset()
    t = et(2026, 10, 23, 14, 0)
    out = []
    ths = [threading.Thread(target=lambda i=i: out.append(ab.create(person(i, t), f"9.9.9.{i}", now=NOW)))
           for i in range(8)]
    [x.start() for x in ths]
    [x.join() for x in ths]
    assert sum(1 for r in out if r.get("ok")) == 1, out
    assert all(r["error"] == "slot_taken" for r in out if not r.get("ok"))


def test_validation_honeypot_rate_limit():
    reset()
    t = et(2026, 10, 20, 15, 0)
    bad = [person(1, t, name=""), person(1, t, business=" "), person(1, t, email="nope"),
           person(1, t, email="a@b"), person(1, t, phone="12345"), person(1, t, phone="215-555-12x4"),
           person(1, t, notes="x" * 1001), person(1, t, name="n" * 81), person(1, t, need=["seo"]),
           person(1, t, need="website"), person(1, t, website="javascript:alert(1)"),
           person(1, "soon")]
    for i, p in enumerate(bad):
        r = ab.create(p, f"2.2.2.{i}", now=NOW)
        assert r["error"] == "invalid", (p, r)
    off = [et(2026, 10, 24, 12), et(2026, 10, 20, 9, 30), et(2026, 10, 20, 16, 45),
           et(2026, 10, 19, 11, 30), NOW - 3600, et(2026, 11, 9, 12), et(2026, 10, 21, 12),
           et(2026, 10, 20, 12, 10)]
    for i, start in enumerate(off):                     # weekend, before/after hours, notice, past,
        r = ab.create(person(1, start), f"3.3.3.{i}", now=NOW)   # past window, closed, off-grid
        assert r["error"] == "not_bookable", (start, r)
    hp = ab.create(person(1, t, fax="http://spam"), "4.4.4.4", now=NOW)
    assert hp["error"] == "invalid" and ab.upcoming(now=NOW)["count"] == 0
    for _ in range(ab.RATE_MAX):
        assert ab.create(person(1, t, email="x"), "5.5.5.5", now=NOW)["error"] == "invalid"
    assert ab.create(person(1, t), "5.5.5.5", now=NOW)["error"] == "rate_limited"
    assert ab.create(person(1, t), "5.5.5.5", now=NOW + 3601)["ok"]                # window rolls
    ok = ab.create(person(2, et(2026, 10, 22, 10), phone="(215) 555-0100", website="shop2.com",
                          need=["ads", "website", "booking"], notes="line1\nline2"), "6.6.6.6", now=NOW)
    assert ok["ok"], ok
    row = [b for b in ab.upcoming(now=NOW)["bookings"] if b["email"] == "pat2@example.com"][0]
    assert row["need"] == ["website", "ads", "booking"] and row["notes"] == "line1\nline2"
    assert not PINGS[0][1].count("<script")


def test_callsheet_hook():
    reset()
    cs.STATE.unlink(missing_ok=True)
    cs.import_text("Joe's Pizza (215) 555-1234 joe@pizza.com\nAcme Plumbing 215-555-9999 www.acme.com\n"
                   "Won Co 267-555-0000", use_ai=False)
    leads = {l["company"] or l["name"]: l for l in cs.list_leads()["leads"]}
    ids_ = {k: v["id"] for k, v in leads.items()}
    joe = next(v for k, v in ids_.items() if "Joe" in k)
    acme = next(v for k, v in ids_.items() if "Acme" in k)
    won = next(v for k, v in ids_.items() if "Won" in k)
    cs.set_status(won, "won")
    r = ab.create(person(1, et(2026, 10, 20, 10), ref=joe), "7.7.7.1", now=NOW)
    assert r["ok"], r
    r = ab.create(person(2, et(2026, 10, 20, 14), phone="+1 215.555.9999"), "7.7.7.2", now=NOW)
    assert r["ok"], r
    r = ab.create(person(3, et(2026, 10, 20, 16), ref=won), "7.7.7.3", now=NOW)
    assert r["ok"], r
    r = ab.create(person(4, et(2026, 10, 22, 16), ref="L999<script>"), "7.7.7.4", now=NOW)
    assert r["ok"], r                                                        # bad ref still books
    st = {l["id"]: l["status"] for l in cs.list_leads()["leads"]}
    assert st[joe] == "demo_booked" and st[acme] == "demo_booked", st
    assert st[won] == "won", st                                              # never regressed
    rows = {b["email"]: b for b in ab.upcoming(now=NOW)["bookings"]}
    assert rows["pat1@example.com"]["leadMatch"] == "ref" and rows["pat2@example.com"]["leadMatch"] == "phone"
    assert rows["pat4@example.com"]["ref"] == "" and rows["pat4@example.com"]["leadId"] == ""
    assert f"Call Sheet: {joe}" in PINGS[0][1]


def test_cancel_frees_slot_and_owner_actions():
    reset()
    t = et(2026, 10, 27, 11, 0)
    assert ab.create(person(1, t), "8.8.8.8", now=NOW)["ok"]
    assert "2026-10-27T11:00" not in ids()
    real_time = ab.time
    ab.time = types.SimpleNamespace(time=lambda: NOW)        # owner_actions reads "now"
    try:
        rows = oa._src_agency_bookings({})
    finally:
        ab.time = real_time
    assert len(rows) == 1 and rows[0]["kind"] == "CALL" and rows[0]["business"] == "agency", rows
    assert rows[0]["link"] == {"ws": "agency", "page": "Bookings"} and "Pat 1" in rows[0]["title"]
    bid = ab.upcoming(now=NOW)["bookings"][0]["id"]
    out = ab.cancel(bid, now=NOW)
    assert out["ok"] and out["cancelled"] == bid and out["count"] == 0, out
    assert "2026-10-27T11:00" in ids()
    assert ab.cancel(bid, now=NOW)["error"] == "not_found"
    assert ab.create(person(1, t), "8.8.8.9", now=NOW)["ok"]                    # email free again
    assert ab.purge(ab.upcoming(now=NOW)["bookings"][0]["id"])


class AgencyFake(tg.FakeGoogle):
    def __init__(self, cals=("ClientForge Calls",), **kw):
        super().__init__(**kw)
        self.cals = cals

    def __call__(self, method, url, headers=None, body=None, timeout=20):
        if urllib.parse.urlparse(url).path.endswith("/users/me/calendarList"):
            self.calls.append((method, url))
            return 200, {"items": [{"id": f"cal{i}@group.calendar.google.com", "summary": n}
                                   for i, n in enumerate(self.cals)]}
        return super().__call__(method, url, headers, body, timeout)


def test_google_connected():
    reset()
    busy_t = et(2026, 10, 28, 13, 0)
    fake = tg.setup(cfg=None, connected=True, fake=AgencyFake(busy=[(busy_t, busy_t + 3600)]))
    s = ids()
    assert "2026-10-28T13:00" not in s and "2026-10-28T13:30" not in s and "2026-10-28T12:00" in s
    t = et(2026, 10, 28, 10, 0)
    r = ab.create(person(1, t, notes="hi"), "1.2.3.4", now=NOW)
    assert r["ok"], r
    url, body = fake.bodies[-1]
    assert "sendUpdates=none" in url and "attendees" not in body, (url, body)
    assert "cal0@group" in urllib.parse.unquote(url) and body["summary"].startswith("ClientForge call")
    row = ab.upcoming(now=NOW)["bookings"][0]
    assert row["eventId"] and row["googleError"] is None and ab.upcoming(now=NOW)["google"] is True
    ab.cancel(row["id"], now=NOW)
    assert any(m == "DELETE" and "sendUpdates=none" in u for m, u in fake.calls)
    assert row["eventId"] not in fake.events
    # Google up but the calendar is missing -> local-only, still books, error kept for the owner.
    reset()
    tg.setup(cfg=None, connected=True, fake=AgencyFake(cals=("Something else",)))
    assert ids()
    r = ab.create(person(2, t), "1.2.3.5", now=NOW)
    assert r["ok"], r
    row = ab.upcoming(now=NOW)["bookings"][0]
    assert row["eventId"] is None and "not found" in row["googleError"], row
    google_off()


def test_public_surface():
    import connector
    from http.server import ThreadingHTTPServer
    reset()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), connector.PortalHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None, headers=None):
        req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     method="GET" if body is None else "POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    try:
        if (Path(connector.HERE) / "book.html").exists():
            st, raw = call("/book")
            assert st == 200 and b"ClientForge" in raw, st
        else:
            print("SKIP /book page — book.html not built yet")
        st, raw = call("/api/book/slots", {})
        assert st == 200 and json.loads(raw)["ok"] and json.loads(raw)["slots"], raw[:200]
        st, raw = call("/api/book/create", {"name": ""})
        assert st == 200 and json.loads(raw)["error"] == "invalid"
        for path in ("/api/agency/bookings", "/api/daycare/x", "/api/agency/callsheet", "/book.html",
                     "/FORGE%20REI%20OS.html", "/agency_booking.py", "/marcus_state/agency_bookings.json",
                     "/api/book/slots", "/api/owner-actions"):
            assert call(path)[0] == 404, path
        for path in ("/api/agency/bookings", "/api/agency/bookings/cancel", "/api/daycare/x",
                     "/api/agency/callsheet/status", "/api/send"):
            assert call(path, {})[0] == 404, path
        st, _ = call("/api/book/create", {}, {"Origin": "https://evil.example"})
        assert st == 403
    finally:
        srv.shutdown()


if __name__ == "__main__":
    tests = [test_slot_math, test_book_buffer_double_book_and_email, test_concurrent_double_book,
             test_validation_honeypot_rate_limit, test_callsheet_hook,
             test_cancel_frees_slot_and_owner_actions, test_google_connected, test_public_surface]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"test_agency_booking: all {len(tests)} passed")
