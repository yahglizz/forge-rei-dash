"""test_daycare_leads.py — the Daycare Lead Desk's logic, checked offline (no network).

Covers: stage derivation (NEW / CONTACTED / RESPONDED / NEEDS_HUMAN, incl. the 8am–9pm ET
quiet-hours boundary), parent-vs-child name, source/center parsing, KPI math, alert dedupe,
the Owner Actions item shape, and one full sweep against a fake GET-only GHL client.

Run from `forge rei/`:  FORGE_MARCUS=0 FORGE_VAULT=$(mktemp -d) python3 test_daycare_leads.py
"""
import tempfile
from datetime import datetime
from pathlib import Path

import daycare_leads as dl

ET = dl.ET
CF_PARENT = "68zgbWrCHH0e9OIyuRJx"          # enroll.js GHL_FIELD.parentName


def et(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ET).timestamp()


def iso(ts):
    return datetime.fromtimestamp(ts, ET).isoformat()


CREATED = et(2026, 9, 21, 10, 0)            # a Monday, 10:00 ET


def lead(tags=(), cf=None, created=CREATED, cid="c1"):
    c = {"id": cid, "locationId": "LOC", "firstName": "Ava", "lastName": "Smith",
         "dateAdded": iso(created), "tags": ["website-lead", "form-type-new-inquiry", *tags],
         "customFields": [{"id": k, "value": v} for k, v in (cf or {}).items()]}
    return c


def msg(direction, ts, source=None, mtype="TYPE_SMS", body="hi", **extra):
    m = {"direction": direction, "dateAdded": iso(ts), "messageType": mtype, "body": body}
    if source:
        m["source"] = source
    m.update(extra)
    return m


def stage(contact, messages=(), tasks=(), now=None):
    return dl.derive(contact, list(messages), list(tasks), now or CREATED + 3600)


def codes(row):
    return [r["code"] for r in row["reasons"]]


def test_stages():
    # NEW — the opportunity exists, nothing else happened.
    assert stage(lead())["stage"] == "NEW"
    # CONTACTED — speed_to_lead_sent marker only; response time from the marker.
    row = stage(lead(cf={dl.CF_STL_SENT: "2026-09-21T14:02:00.000Z"}))   # 10:02 ET
    assert row["stage"] == "CONTACTED" and row["firstResponseSec"] == 120, row
    # CONTACTED — the workflow text is automated: no human reply yet.
    row = stage(lead(), [msg("outbound", CREATED + 180, source="workflow")])
    assert row["stage"] == "CONTACTED" and row["firstResponseSec"] == 180
    assert row["firstHumanSec"] is None
    # RESPONDED — parent replied 10 min ago (under the 15-min bar).
    now = CREATED + 7200
    row = stage(lead(), [msg("outbound", CREATED + 180, source="workflow"),
                         msg("inbound", now - 600)], now=now)
    assert row["stage"] == "RESPONDED", row
    # NEEDS_HUMAN — parent reply unanswered 20 min in business hours.
    row = stage(lead(), [msg("outbound", CREATED + 180, source="workflow"),
                         msg("inbound", now - 1200)], now=now)
    assert row["stage"] == "NEEDS_HUMAN" and codes(row) == ["unanswered"], row
    # ...answered by a human (GHL app) -> back to RESPONDED; first human reply timed.
    row = stage(lead(), [msg("outbound", CREATED + 180, source="workflow"),
                         msg("inbound", now - 1200),
                         msg("outbound", now - 900, source="app", userId="u1")], now=now)
    assert row["stage"] == "RESPONDED" and row["firstHumanSec"] == 7200 - 900, row
    # A picked-up inbound call IS the reply.
    row = stage(lead(), [msg("inbound", now - 3000, mtype="TYPE_CALL",
                             meta={"call": {"status": "completed"}})], now=now)
    assert "unanswered" not in codes(row), row
    # An opt-out is never "unanswered" — don't nag the owner to text a STOP.
    row = stage(lead(), [msg("outbound", CREATED + 180, source="workflow"),
                         msg("inbound", now - 3000, body="STOP")], now=now)
    assert row["stage"] == "RESPONDED" and row["optedOut"] is True, row


def test_quiet_hours_boundary():
    out = msg("outbound", et(2026, 9, 21, 20, 0), source="workflow")
    inbound = msg("inbound", et(2026, 9, 21, 20, 50))          # 8:50pm ET
    c = lead()
    # 9:30pm: only 10 business minutes have passed -> not yet.
    assert stage(c, [out, inbound], now=et(2026, 9, 21, 21, 30))["stage"] == "RESPONDED"
    # 8:04am next day: 10 + 4 = 14 business minutes -> not yet.
    assert stage(c, [out, inbound], now=et(2026, 9, 22, 8, 4))["stage"] == "RESPONDED"
    # 8:06am: 16 business minutes -> needs a human.
    row = stage(c, [out, inbound], now=et(2026, 9, 22, 8, 6))
    assert row["stage"] == "NEEDS_HUMAN" and codes(row) == ["unanswered"]
    # 11pm text: overnight hours never count.
    late = msg("inbound", et(2026, 9, 21, 23, 0))
    assert stage(c, [out, late], now=et(2026, 9, 22, 8, 14))["stage"] == "RESPONDED"
    assert stage(c, [out, late], now=et(2026, 9, 22, 8, 16))["stage"] == "NEEDS_HUMAN"
    # DST (spring forward 2026-03-08): 8–9pm on the 7th + 8–9am on the 8th = 2h exactly.
    assert dl.business_secs(et(2026, 3, 7, 20), et(2026, 3, 8, 9)) == 7200
    assert dl.in_hours(et(2026, 9, 21, 8, 0)) and not dl.in_hours(et(2026, 9, 21, 21, 0))


def test_tasks_tags():
    due_past = {"id": "t1", "dueDate": iso(CREATED + 1200), "completed": False}
    row = stage(lead(), tasks=[due_past], now=CREATED + 3600)
    assert codes(row) == ["overdue_task"] and row["openTask"]["overdue"] is True
    done = dict(due_past, completed=True)
    assert stage(lead(), tasks=[done])["stage"] == "NEW"
    # pref-call-30: needs a human until someone replies or completes the call task.
    assert codes(stage(lead(["pref-call-30"]))) == ["pref_call"]
    assert codes(stage(lead(["pref-call-30"]), tasks=[done])) == []
    human = msg("outbound", CREATED + 300, source="app", userId="u1")
    assert codes(stage(lead(["pref-call-30"]), [human])) == []
    # speed-to-lead-queued: needs a human until the text actually goes out.
    q = lead(["speed-to-lead-queued"], cf={dl.CF_STL_SENT: iso(CREATED)})
    row = stage(q)
    assert codes(row) == ["sms_queued"] and row["firstResponseSec"] is None
    assert stage(q, [msg("outbound", CREATED + 600, source="workflow")])["stage"] == "CONTACTED"
    # Several reasons: ordered by priority, stage NEEDS_HUMAN.
    assert codes(stage(lead(["pref-call-30"]), tasks=[due_past])) == ["pref_call", "overdue_task"]


def test_names_source_center():
    # GHL first/last = the CHILD; the parent comes from the parent-name custom field.
    row = stage(lead(cf={CF_PARENT: "Jordan Smith"}))
    assert row["parentName"] == "Jordan Smith" and "Ava" not in row["parentName"]
    # Pre-2026-07-21 contacts: no parent field, first/last WAS the parent.
    old = stage(lead())
    assert old["parentName"] == "Ava Smith"
    row = stage(lead(["source-meta-ad", "loc-1923-cecil-b-moore"]))
    assert row["source"] == "meta-ad" and row["center"] == "1923 Cecil B Moore (AMT)"
    assert row["centerTag"] == "loc-1923-cecil-b-moore"
    row = stage(lead(["loc-somewhere-new"]))
    assert row["source"] == "unknown" and row["center"] == "loc-somewhere-new"
    assert stage(lead())["center"] == "Center unknown"
    assert stage(lead())["ghlUrl"].endswith("/v2/location/LOC/contacts/detail/c1")


def test_kpis():
    now = et(2026, 9, 22, 12)
    day = 86400 * 1000
    nms = int(now * 1000)
    leads = [
        {"createdAt": nms - 1 * day, "source": "meta-ad", "stage": "NEEDS_HUMAN", "firstResponseSec": 180, "firstHumanSec": 600},
        {"createdAt": nms - 3 * day, "source": "organic", "stage": "RESPONDED", "firstResponseSec": 240, "firstHumanSec": None},
        {"createdAt": nms - 10 * day, "source": "meta-ad", "stage": "CONTACTED", "firstResponseSec": 60, "firstHumanSec": 1200},
        {"createdAt": nms - 20 * day, "source": "chat", "stage": "NEW", "firstResponseSec": None, "firstHumanSec": None},
        {"createdAt": nms - 40 * day, "source": "meta-ad", "stage": "NEW", "firstResponseSec": 1, "firstHumanSec": 1},
    ]
    k = dl.kpis(leads, now)
    assert k["newLeads7d"] == {"total": 2, "meta": 1, "organic": 1, "other": 0}, k
    assert k["newLeads30d"] == {"total": 4, "meta": 2, "organic": 1, "other": 1}, k
    assert k["medianResponseSec"] == 180 and k["responseSample"] == 3        # 60,180,240
    assert k["medianHumanResponseSec"] == 900 and k["humanSample"] == 2      # 600,1200
    assert k["needsHuman"] == 1 and k["stages"]["NEW"] == 2


def test_alert_dedupe_and_owner_items():
    sent = []
    send = lambda text, data, key: sent.append((text, data, key))  # noqa: E731
    base = lead(["pref-call-30", "loc-921-n-18th"], cf={CF_PARENT: "Jordan Smith"})
    other = lead(cid="c2")
    in_hours, night = et(2026, 9, 21, 10, 30), et(2026, 9, 21, 23, 0)
    row = dl.derive(base, [], [], in_hours)
    st = {}
    # First-ever run seeds the backlog: one summary line, no per-lead spam.
    dl.process_alerts(st, [row, dl.derive(other, [], [], in_hours)], in_hours, send)
    assert len(sent) == 1 and sent[0][1]["type"] == "daycare_lead_summary" and st["seeded"]
    # Same needs, next sweep: nothing.
    dl.process_alerts(st, [row], in_hours + 900, send)
    assert len(sent) == 1
    # A NEW reason on the same lead at night: deferred, not recorded.
    task = {"id": "t9", "dueDate": iso(night - 600), "completed": False}
    row2 = dl.derive(base, [], [task], night)
    dl.process_alerts(st, [row2], night, send)
    assert len(sent) == 1 and not any("overdue_task" in k for k in st["alerted"])
    # ...and it fires ONCE at 8am, first name only.
    morning = et(2026, 9, 22, 8, 1)
    row3 = dl.derive(base, [], [task], morning)
    dl.process_alerts(st, [row3], morning, send)
    dl.process_alerts(st, [row3], morning + 900, send)
    assert len(sent) == 2, sent
    text, data, _key = sent[1]
    assert text.startswith("Daycare lead needs you: Jordan (921 N 18th St)") and "Smith" not in text
    assert data == {"type": "daycare_lead", "contactId": "c1", "reasons": ["overdue_task"]}

    # Owner Actions shape (WP-C imports needs_human()).
    items = dl.needs_human({"leads": [row3]}, now=morning)
    assert len(items) == 1
    item = items[0]
    assert {"id", "title", "why", "ageSec", "priority", "contactId"} <= set(item)
    assert item["id"] == "daycare-lead:c1" and item["priority"] == "URGENT"
    assert item["title"] == "Call Jordan Smith — 921 N 18th St"
    assert item["ageSec"] == int(morning - CREATED)
    assert dl.needs_human({"leads": [dl.derive(other, [], [], in_hours)]}) == []


class FakeGHL:
    """GET-only stand-in. No post/put/delete: any write would raise AttributeError."""
    configured = True
    location_id = "LOC"

    def __init__(self, now):
        self.now = now
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(path)
        n = self.now
        if path == "/contacts/":
            return {"contacts": [
                lead(["loc-921-n-18th", "source-organic"], cf={CF_PARENT: "Jordan Smith"}, created=n - 7200, cid="lead1"),
                lead(["enrolled"], created=n - 7200, cid="fam1"),                     # enrolled family
                {"id": "chat1", "tags": [], "dateAdded": iso(n - 3600), "firstName": "Pat"},
                {"id": "vendor1", "tags": [], "dateAdded": iso(n - 3600)},             # SMS only
                lead(created=n - 200 * 86400, cid="old1"),                             # dormant
            ], "meta": {}}
        if path == "/conversations/search":
            convs = [
                {"id": "cv1", "contactId": "lead1", "lastMessageDate": int((n - 1800) * 1000)},
                {"id": "cvc", "contactId": "chat1", "lastMessageDate": int((n - 1800) * 1000)},
                {"id": "cvv", "contactId": "vendor1", "lastMessageDate": int((n - 1800) * 1000)},
                {"id": "cvf", "contactId": "fam1", "lastMessageDate": int((n - 1800) * 1000)},
            ]
            only = (params or {}).get("contactId")
            return {"conversations": [c for c in convs if not only or c["contactId"] == only]}
        if path == "/conversations/cv1/messages":
            return {"messages": {"messages": [msg("inbound", n - 1800),
                                              msg("outbound", n - 7000, source="workflow")]}}
        if path == "/conversations/cvc/messages":
            return {"messages": {"messages": [msg("inbound", n - 1800, mtype="TYPE_WEBCHAT")]}}
        if path == "/conversations/cvv/messages":
            return {"messages": {"messages": [msg("inbound", n - 1800)]}}
        if path.endswith("/tasks"):
            return {"tasks": []}
        raise AssertionError("unexpected GET " + path)


def test_sweep_and_view():
    with tempfile.TemporaryDirectory() as tmp:
        dl.STATE = Path(tmp) / "daycare_leads.json"
        assert "has not run yet" in dl.view()["error"]
        now = et(2026, 9, 22, 11, 0)
        sent = []
        st = dl.run_once(FakeGHL(now), now=now, send=lambda *a: sent.append(a))
        ids = {l["contactId"]: l for l in st["leads"]}
        assert set(ids) == {"lead1", "chat1"}, ids.keys()            # family, vendor, dormant out
        assert ids["lead1"]["stage"] == "NEEDS_HUMAN" and ids["chat1"]["kind"] == "chat"
        assert ids["chat1"]["source"] == "chat"
        assert st["error"] is None and st["kpis"]["needsHuman"] == 2
        assert len(sent) == 1                                        # first run: one summary
        v = dl.view()
        assert v["ok"] and v["error"] is None and len(v["needsHuman"]) == 2 and v["lastRunAt"]
        # A failed sweep keeps the last good leads and surfaces the error.
        class Broken(FakeGHL):
            def get(self, path, params=None):
                raise OSError("boom")
        st = dl.run_once(Broken(now), now=now + 900, send=lambda *a: None)
        assert st["error"] == "GHL read failed: OSError" and len(st["leads"]) == 2
        # Unconfigured client: honest error, no crash.
        st = dl.run_once(None, now=now + 1800)
        assert "not configured" in st["error"]


def test_rate_limit_aborts_sweep():
    """An exhausted 429 stops the whole sweep at once, keeps the last good snapshot, and
    holds every GET until GHL's Retry-After passes (else one interval)."""
    import urllib.error

    class Limited(FakeGHL):
        def get(self, path, params=None):
            if path.startswith("/conversations/cv"):          # first per-lead read
                self.calls.append(path)
                raise urllib.error.HTTPError(path, 429, "Too Many Requests",
                                             {"Retry-After": "1800"}, None)
            return super().get(path, params)

    with tempfile.TemporaryDirectory() as tmp:
        dl.STATE = Path(tmp) / "daycare_leads.json"
        now = et(2026, 9, 22, 11, 0)
        good = dl.run_once(FakeGHL(now), now=now, send=lambda *a: None)
        lim = Limited(now + 900)
        st = dl.run_once(lim, now=now + 900, send=lambda *a: None)
        assert "429" in st["error"] and "backing off 1800s" in st["error"], st["error"]
        assert st["leads"] == good["leads"] and st["lastOkAt"] == good["lastOkAt"]
        assert st["alerted"] == good["alerted"]
        assert st["backoffUntil"] == dl._ms(now + 900 + 1800)
        assert sum(1 for c in lim.calls if c.startswith("/conversations/cv") or c.endswith("/tasks")) == 1
        # Inside the backoff: zero GETs; the 429 error stands, so the heartbeat beats red.
        quiet = FakeGHL(now + 1800)
        st = dl.run_once(quiet, now=now + 1800)
        assert quiet.calls == [] and "429" in st["error"]
        # Past it: a normal sweep, backoff cleared.
        st = dl.run_once(FakeGHL(now + 2800), now=now + 2800, send=lambda *a: None)
        assert st["error"] is None and st["backoffUntil"] is None and len(st["leads"]) == 2
    assert dl._retry_after(urllib.error.HTTPError("u", 429, "x", {}, None)) == dl.INTERVAL


def test_lead_outside_conversation_window():
    """A lead whose thread fell out of the 100-conversation window is looked up per
    contact (capped); an answered one never pages the owner, and one past the cap is
    'history unknown' — never NEEDS_HUMAN or an alert from missing data."""
    class Window(FakeGHL):
        def get(self, path, params=None):
            n = self.now
            if path == "/contacts/":
                self.calls.append(path)
                return {"contacts": [
                    lead(["pref-call-30"], created=n - 5 * 86400, cid="late1"),
                    lead(["pref-call-30"], created=n - 5 * 86400, cid="late2"),
                ]}
            if path == "/conversations/search" and (params or {}).get("contactId") == "late1":
                self.calls.append("lookup:late1")
                return {"conversations": [{"id": "cvl", "contactId": "late1",
                                           "lastMessageDate": int((n - 4 * 86400) * 1000)}]}
            if path == "/conversations/cvl/messages":
                self.calls.append(path)
                return {"messages": {"messages": [
                    msg("inbound", n - 5 * 86400 + 60),
                    msg("outbound", n - 5 * 86400 + 600, source="app", userId="u1")]}}
            return super().get(path, params)

    cap = dl.CONV_LOOKUPS
    dl.CONV_LOOKUPS = 1
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dl.STATE = Path(tmp) / "daycare_leads.json"
            now = et(2026, 9, 22, 11, 0)
            sent, ghl = [], Window(now)
            st = dl.run_once(ghl, now=now, send=lambda *a: sent.append(a))
            ids = {l["contactId"]: l for l in st["leads"]}
            assert ids["late1"]["stage"] != "NEEDS_HUMAN" and ids["late1"]["historyKnown"], ids["late1"]
            assert ids["late1"]["firstHumanSec"] == 600
            assert ids["late2"]["stage"] != "NEEDS_HUMAN" and ids["late2"]["historyKnown"] is False
            assert "lookup:late1" in ghl.calls and ghl.calls.count("/conversations/search") == 1
            assert sent == [] and dl.needs_human(st) == [] and st["error"] is None
    finally:
        dl.CONV_LOOKUPS = cap


def test_bus_alert_is_name_free():
    """skill_forge samples bus text to disk: the parent's name rides Telegram only."""
    import sys
    import types
    bus, tg = [], []
    saved = {m: sys.modules.get(m) for m in ("agent_bus", "telegram_io")}
    sys.modules["agent_bus"] = types.SimpleNamespace(send=lambda *a: bus.append(a))
    sys.modules["telegram_io"] = types.SimpleNamespace(
        send=lambda text, dedupe_key=None: tg.append(text))
    try:
        dl._notify("Daycare lead needs you: Jordan (921 N 18th St) — GHL call task is overdue",
                   {"type": "daycare_lead", "contactId": "c1", "reasons": ["overdue_task"]}, "k")
    finally:
        for m, mod in saved.items():
            if mod is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = mod
    text, data = bus[0][3], bus[0][4]
    assert "Jordan" not in text and "921" not in text and "c1" in text and "overdue_task" in text, text
    assert "Jordan" not in str(data)
    assert "Jordan" in tg[0]


def test_contact_cap_truncation_note():
    """A full contact page cap is surfaced as a note — the sweep and heartbeat stay clean."""
    cap = (dl.CONTACT_PAGES, dl.PAGE_SIZE)
    dl.CONTACT_PAGES, dl.PAGE_SIZE = 1, 5          # FakeGHL returns exactly 5 contacts
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dl.STATE = Path(tmp) / "daycare_leads.json"
            now = et(2026, 9, 22, 11, 0)
            st = dl.run_once(FakeGHL(now), now=now, send=lambda *a: None)
            assert st["error"] is None and len(st["leads"]) == 2, st["error"]
            assert "5-contact cap" in st["note"], st["note"]
            assert "5-contact cap" in dl.view()["error"]
    finally:
        dl.CONTACT_PAGES, dl.PAGE_SIZE = cap
    with tempfile.TemporaryDirectory() as tmp:
        dl.STATE = Path(tmp) / "daycare_leads.json"
        st = dl.run_once(FakeGHL(now), now=now, send=lambda *a: None)
        assert st["note"] is None and dl.view()["error"] is None


if __name__ == "__main__":
    import sys
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print("FAIL", name, "-", type(e).__name__, e)
    sys.exit(1 if failed else 0)
