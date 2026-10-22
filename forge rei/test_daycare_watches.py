"""The board's zero-Claude watches (daycare_watches) on fixtures. Run: python3 test_daycare_watches.py
No network: every read is a fixture `get`; the board file is a temp file; Claude is booby-trapped."""
import copy
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="watches-test-"))
os.environ["FORGE_DAYCARE_BOARD"] = str(TMP / "board.json")

import daycare_board  # noqa: E402
import daycare_watches as w  # noqa: E402
import review_agent  # noqa: E402

NOW = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc).timestamp()     # Mon 10:00 ET
MS = int(NOW * 1000)
AMT, N921, N2318 = "1923 Cecil B Moore (AMT)", "921 N 18th St", "2318 Cecil B Moore"


def iso(h_ago):
    return datetime.fromtimestamp(NOW - h_ago * 3600, timezone.utc).isoformat(timespec="seconds")


def day(d):
    return (datetime.fromtimestamp(NOW, timezone.utc) + timedelta(days=d)).date().isoformat()


def row(mid, tid, frm, subject, h_ago, bucket, unread=False, snippet=""):
    return {"id": mid, "threadId": tid, "date": iso(h_ago), "from": frm, "subject": subject, "snippet": snippet,
            "unread": unread, "bucket": bucket, "labels": []}


ME = "Yahjair <yahjair@atouchofblessing.com>"
FORM = "noreply@atouchofblessing.com"
MAIL = {"ok": True, "via": "gmail", "configured": True, "filteredOut": 12, "fetchedAt": MS,
        "dateRange": {"label": "last 7 days (Gmail newer_than:7d)"},
        "rows": [row("m1", "t1", "Seara P <seara@x.com>", "Mia's tuition this week", 6, "parent", unread=True),
                 row("m2", "t2", "Ann <ann@x.com>", "Pickup Friday", 8, "parent"),
                 row("m3", "t3", "Bo <bo@x.com>", "Invoice question", 10, "billing"),
                 row("m4", "t4", "OCDEL <notice@pa.gov>", "A Mother's Touch inspection notice", 30, "licensing"),
                 row("m5", "t5", "ZZTest Parent <zz@x.com>", "zztest tour", 9, "parent", unread=True),
                 row("m6", "t6", "Cy <cy@x.com>", "Quick question", 1, "parent", unread=True),
                 row("m7", "t7", FORM, "New Inquiry", 2, "lead"),
                 row("m8", "t8", FORM, "New Inquiry", 3, "lead"),
                 row("m9", "t9", FORM, "Family Contact Form", 5, "lead"),
                 row("m10", "t10", "Vendor <v@x.com>", "Daycare supplies", 40, "vendor", unread=True)]}
THREADS = {"t1": [MAIL["rows"][0]],
           "t2": [MAIL["rows"][1], {"id": "r2", "date": iso(7), "from": ME}],          # answered after
           "t3": [MAIL["rows"][2], {"id": "r3", "date": iso(12), "from": ME}],         # our reply was BEFORE theirs
           "t4": [MAIL["rows"][3]]}
LEADS = {"ok": True, "lastOkAt": MS - 600_000, "kpis": {"medianHumanResponseSec": 3 * 3600, "humanSample": 9},
         "leads": [{"contactId": "c1", "parentName": "Seara P", "createdAt": int((NOW - 2 * 3600 + 600) * 1000)},
                   {"contactId": "c2", "parentName": "ZZTest Mom"},
                   {"contactId": "c3", "parentName": "Ivy R"}],
         "needsHuman": [{"contactId": "c1", "title": f"Reply to Seara P — {N921}", "why": "Parent message unanswered",
                         "ageSec": 1800, "priority": "URGENT", "center": N921},
                        {"contactId": "c2", "title": f"Reply to ZZTest Mom — {N921}", "why": "x", "ageSec": 9,
                         "priority": "URGENT", "center": N921},
                        {"contactId": "c3", "title": f"Call Ivy R — {AMT}", "why": "GHL call task is overdue",
                         "ageSec": 7200, "priority": "REVENUE", "center": AMT}]}
STARTS = {"ok": True, "lastRunAt": MS - 60_000, "starts": [
    {"contactId": "s1", "status": "proposed", "confirmOpen": True, "childFirst": "Ava", "startDate": day(2),
     "daysUntil": 2, "center": N2318, "evidence": "she can start monday"},
    {"contactId": "s2", "status": "failed", "childFirst": "Leo", "startDate": day(0), "center": N921, "lastError": "GHL 500"},
    {"contactId": "s3", "status": "proposed", "confirmOpen": False, "childFirst": "Max", "startDate": day(20), "center": N921},
    {"contactId": "s4", "status": "failed", "childFirst": "ZZTest", "startDate": day(0), "center": N921}]}
HELD = {"ok": True, "last_run": NOW - 300, "held": [
    {"child": "Mia Q", "card_id": "k1", "reasons": ["child birth date"], "location": "loc-1923-cecil-b-moore"},
    {"child": "Zed Z", "card_id": "k2", "reasons": ["test or junk record"]}]}
AUDIT = {"ok": True, "centers": [{"center": "A Touch of Blessings", "missingTag": 2},
                                 {"center": "A Mother's Touch", "missingTag": 1},
                                 {"center": "A Touch of Blessings 2", "missingTag": 0}],
         "missing": [{"parent": "ZZTest Mom", "child": "ZZTest Kid", "center": "A Touch of Blessings"},
                     {"parent": "Real Mom", "child": "Kid", "center": "A Touch of Blessings"},
                     {"parent": "Ivy R", "child": "Ivy jr", "center": "A Mother's Touch"}]}
LOCS = {"ok": True, "locations": [{"id": "L1", "name": "A Touch of Blessings"}, {"id": "L3", "name": "A Mother's Touch"}]}


def kid(cid, first, gp="g1", phone="+12155550101", **kw):
    return {"id": cid, "first_name": first, "last_name": "Smith", "active": True, "guardian_profile_id": gp,
            "guardian": {"id": gp, "phone": phone} if gp else None, "enrollment_date": day(-90), **kw}


BILL = {"L1": {"ok": True, "invoices": [
            {"id": "i1", "invoice_number": "INV-1", "status": "due", "due_on": day(-10), "issued_on": day(-20),
             "amount": "450.00", "guardian_name": "Seara P", "guardian_id": "g1", "child_id": "k1", "payments": []},
            {"id": "i2", "invoice_number": "INV-2", "status": "due", "due_on": day(2), "issued_on": day(-5),
             "amount": "300", "guardian_name": "Ann", "guardian_id": "g9", "child_id": None, "payments": []},
            {"id": "i3", "invoice_number": "INV-3", "status": "paid", "due_on": day(-30), "issued_on": day(-40),
             "amount": "99", "guardian_name": "Paid Pa", "payments": [{"amount": 99}]},
            {"id": "i4", "invoice_number": "INV-4", "status": "overdue", "due_on": day(-3), "issued_on": day(-30),
             "amount": "120", "guardian_name": "ZZTest Guardian", "payments": []}]},
        "L3": {"ok": True, "invoices": []}}
KIDS = {"L1": {"ok": True, "children": [kid("k1", "Mia"), kid("k2", "Noah", gp="g2", phone="+12155550102"),
                                        kid("k3", "Old", gp="g3", withdrawn_on=day(-1)),
                                        kid("k4", "Nolo", gp=None), kid("k5", "Pip", gp="g5", phone=None),
                                        kid("k6", "ZZTest", gp=None)]},
        "L3": {"ok": True, "children": [kid("a1", "Ivy", gp="h1", phone=None), kid("a2", "Jo", gp="h2", phone=None),
                                        kid("a3", "Kai", gp="h3", phone=None)]}}
ROOMS = {"L1": {"ok": True, "classrooms": [{"id": "r1", "name": "Toddlers", "capacity": 8, "enrolled": 9, "active": True},
                                           {"id": "r2", "name": "Pre-K", "capacity": 10, "enrolled": 10, "active": True}]},
         "L3": {"ok": True, "classrooms": [{"id": "r9", "name": "Infants", "capacity": 4, "enrolled": 5, "active": True}]}}
FEED = {"ok": True, "kind": "daycare_ads_feed", "configured": True, "fetchedAt": "2026-10-19T10:00:00-04:00",
        "autopilot": {"pending": [{"id": "a1", "action": "pause ad Trust v2", "reason": "CPL 3x target."}]},
        "windows": [{"preset": "last_7d", "window": "last 7 days 2026-10-12..2026-10-18",
                     "totals": {"spend": 140.0, "leads": 2, "cpl": 70.0, "tcpl": 40},
                     "campaigns": [{"id": "c1", "name": "Trust", "status": "active", "spend": 0},
                                   {"id": "c2", "name": "Offer", "status": "paused", "spend": 0}]}]}
HEALTH = {"loops": [{"loop": "daycare_leads", "label": "Solomon · Leads", "status": "red", "ageSec": 4000,
                     "lastError": "GHL 500"}, {"loop": "scout", "label": "Scout", "status": "red"}],
          "redLoops": ["daycare_leads", "scout"], "ai": {"ok": False, "reason": "credit balance too low"}}
FIX = {"/api/daycare/mail": MAIL, "/api/daycare/leads": LEADS, "/api/daycare/starts": STARTS,
       "/api/daycare/auto-enroll": HELD, "/api/daycare/ghl/enrolled-audit": AUDIT, "/api/daycare/locations": LOCS,
       "/api/daycare/ads/feed": FEED, "/api/daycare/social": {"ok": True, "configured": False},
       "/api/system/health": HEALTH, "/api/stripe/status": {"configured": True, "ok": False, "detail": "Invalid API key"},
       "/api/daycare/ghl/health": {"ok": True, "connected": True, "hasKeys": True}}
PER_LOC = {"/api/daycare/billing": BILL, "/api/daycare/children": KIDS, "/api/daycare/classrooms": ROOMS}
CALLS = []


def make_get(over=None):
    over = over or {}

    def get(path, query=None):
        CALLS.append((path, dict(query or {})))
        if path in over:
            v = over[path]
            return v(query) if callable(v) else copy.deepcopy(v)
        if path == "/api/daycare/mail/thread":
            msgs = THREADS.get((query or {}).get("id"))
            return {"ok": True, "via": "gmail", "messages": msgs} if msgs else {"ok": False, "error": "not found"}
        if path in PER_LOC:
            return copy.deepcopy(PER_LOC[path].get((query or {}).get("location_id"), {"ok": False, "error": "no loc"}))
        return copy.deepcopy(FIX.get(path, {"ok": False, "error": "HTTP 404"}))
    return get


def keys(items):
    return {i["key"]: i for i in items}


def test_inbox():
    items, st = w.watch_inbox(make_get(), NOW)
    k = keys(items)
    assert set(k) == {"mail:t1", "mail:t3", "mail:t4", "form:m8"}, sorted(k)
    assert "unread" in k["mail:t1"]["why"] and k["mail:t1"]["severity"] == "normal", k["mail:t1"]
    assert "no reply from @atouchofblessing.com" in k["mail:t3"]["why"], "a reply BEFORE their message is not an answer"
    assert k["mail:t4"]["severity"] == "high" and k["mail:t4"]["center"] == AMT, "licensing = high; AMT kept apart"
    assert k["form:m8"]["severity"] == "high" and "GHL" in k["form:m8"]["why"]
    for i in items:
        assert i["evidence"]["source"].startswith("Gmail") and i["evidence"]["window"].startswith("last 7 days"), i
        assert i["link"]["kind"] == "mail" and "zz" not in str(i).lower()
    desk = st["mailDesk"]
    assert st["ok"] and desk["needsAnswer"] == 4 and desk["filteredOut"] == 12, desk
    assert desk["unread"] == 3 and all("zztest" not in str(t).lower() for t in desk["top"]), desk
    assert [u["bucket"] for u in desk["urgent"]] == ["licensing"], desk["urgent"]


def test_inbox_reply_already_in_the_list():
    mail = copy.deepcopy(MAIL)
    mail["rows"].append(row("m11", "t1", ME, "Re: Mia's tuition this week", 5, "parent"))
    CALLS.clear()
    items, _ = w.watch_inbox(make_get({"/api/daycare/mail": mail}), NOW)
    assert "mail:t1" not in keys(items), "our later reply in the list = answered"
    assert ("/api/daycare/mail/thread", {"id": "t1", "meta": 1}) not in CALLS, "no thread read needed"


def test_inbox_failed_and_not_wired():
    items, st = w.watch_inbox(make_get({"/api/daycare/mail": {"ok": False, "configured": False, "error": "x"}}), NOW)
    assert items == [] and st["ok"] is False and st["notWired"] is True and "Unknown, not zero" in st["error"], st
    items, st = w.watch_inbox(make_get({"/api/daycare/mail": {"ok": False, "error": "Session expired", "code": "x"}}), NOW)
    assert st["ok"] is False and not st["notWired"] and "read failed" in st["error"], st
    items, st = w.watch_inbox(make_get({"/api/daycare/mail/thread": {"ok": False, "error": "down"}}), NOW)
    k = keys(items)
    assert "mail:t1" in k and "not checked" in k["mail:t1"]["why"], "unread + unknown reply status = still an item"
    assert "mail:t3" not in k and "not checked" in st["note"], "read + unknown reply status = Unknown, not an item"


def test_enrollment():
    items, st = w.watch_enrollment(make_get(), NOW)
    k = keys(items)
    assert set(k) == {"lead:c1", "lead:c3", "leads:response-time", "start:s1", "start:s2", "held:k1",
                      f"tagdrift:{N921}", f"tagdrift:{AMT}"}, sorted(k)
    assert k["lead:c1"]["severity"] == "urgent" and k["lead:c3"]["severity"] == "high"
    assert k["lead:c3"]["center"] == AMT and k["held:k1"]["center"] == AMT, "1923 keeps its own label"
    assert k["start:s2"]["severity"] == "urgent" and k["start:s1"]["severity"] == "high"
    assert "1 enrolled family" in k[f"tagdrift:{N921}"]["title"], "the ZZTest family is not counted"
    assert k[f"tagdrift:{N921}"]["owner"] == "solomon" and k[f"tagdrift:{AMT}"]["center"] == AMT
    assert k["leads:response-time"]["center"] == "all" and "3.0 h" in k["leads:response-time"]["title"]
    assert st["ok"] and all(st["sources"].values()), st


def test_enrollment_stale_desk_is_unknown():
    stale = dict(LEADS, lastOkAt=MS - 5 * 3600 * 1000)
    items, st = w.watch_enrollment(make_get({"/api/daycare/leads": stale,
                                             "/api/daycare/ghl/enrolled-audit": {"ok": False, "error": "GHL 500"}}), NOW)
    assert not any(i["key"].startswith(("lead:", "leads:", "tagdrift:")) for i in items), items
    assert st["ok"] is False and st["sources"]["lead:"] is False and st["sources"]["tagdrift:"] is False
    assert st["sources"]["start:"] is True and "Lead Desk" in st["error"] and "GHL 500" in st["error"], st


def test_billing():
    items, st = w.watch_billing(make_get(), NOW)
    k = keys(items)
    assert set(k) == {"inv:L1:i1", "inv:L1:i2", "noinv:L1", "noinv:L3"}, sorted(k)
    i1 = k["inv:L1:i1"]
    assert i1["severity"] == "high" and "$450.00" in i1["title"] and "10d" in i1["title"], i1
    assert "invoice amount" in i1["why"] and "Supabase" in i1["evidence"]["source"], i1
    assert k["inv:L1:i2"]["severity"] == "low" and k["inv:L1:i2"]["center"] == N921
    assert "Noah" in k["noinv:L1"]["why"] and "Mia" not in k["noinv:L1"]["why"], k["noinv:L1"]
    assert "Old" not in k["noinv:L1"]["why"] and "ZZTest" not in str(items), "withdrawn + test kids excluded"
    assert k["noinv:L3"]["center"] == AMT and k["noinv:L3"]["severity"] == "low" and "Unknown" in k["noinv:L3"]["why"]
    assert st["ok"] and "failed payments: Unknown" in st["note"], st


def test_billing_center_failure_is_isolated():
    bad = dict(BILL, L3={"ok": False, "error": "Daycare request failed"})
    items, st = w.watch_billing(make_get({"/api/daycare/billing": lambda q: copy.deepcopy(bad[q["location_id"]])}), NOW)
    assert st["ok"] is False and st["sources"]["inv:L1:"] is True and st["sources"]["inv:L3:"] is False, st
    assert st["sources"]["noinv:L3"] is False and not any(i["center"] == AMT for i in items)
    items, st = w.watch_billing(make_get({"/api/daycare/locations": {"ok": True, "locations": []}}), NOW)
    assert items == [] and st["ok"] is False, "zero centers readable is a failed read, never 0 problems"


def test_roster():
    items, st = w.watch_roster(make_get(), NOW)
    k = keys(items)
    assert set(k) == {"room:L1:r1", "room:L3:r9", "withdrawn:L1:k3", "nologin:L1", "nophone:L1"}, sorted(k)
    assert k["room:L1:r1"]["severity"] == "urgent" and "9/8" in k["room:L1:r1"]["title"]
    assert k["room:L3:r9"]["center"] == AMT and k["room:L1:r1"]["center"] == N921
    assert "1 active children" in k["nologin:L1"]["title"] and "ZZTest" not in str(items)
    assert "1 parent logins" in k["nophone:L1"]["title"]
    assert st["sources"]["nophone:L3"] is False and "Unknown" in st["error"], "every phone missing = the read failed"
    assert "ratio" in st["note"]


def test_ads():
    items, st = w.watch_ads(make_get(), NOW)
    k = keys(items)
    assert set(k) == {"ap:a1", "cpl:7d", "nodeliv:c1"}, sorted(k)
    assert k["cpl:7d"]["severity"] == "high" and "$70.00" in k["cpl:7d"]["title"], k["cpl:7d"]
    assert k["cpl:7d"]["evidence"] == {"source": "Meta via Pipeboard", "window": "last 7 days 2026-10-12..2026-10-18",
                                       "fetchedAt": FEED["fetchedAt"]}
    assert st["ok"]
    zero = copy.deepcopy(FEED)
    zero["windows"][0]["totals"] = {"spend": 45.0, "leads": 0, "cpl": None, "tcpl": 40}
    assert "0 leads" in keys(w.watch_ads(make_get({"/api/daycare/ads/feed": zero}), NOW)[0])["cpl:7d"]["title"]
    items, st = w.watch_ads(make_get({"/api/daycare/ads/feed": {"ok": True, "kind": "daycare_ads_feed",
                                                                "configured": False}}), NOW)
    assert items == [] and st["notWired"] and not st["ok"]
    unk = dict(FEED, unknown=True, error="Pipeboard 503")
    items, st = w.watch_ads(make_get({"/api/daycare/ads/feed": unk}), NOW)
    assert keys(items).keys() == {"ap:a1"} and st["sources"] == {"ap:": True, "cpl:": False, "nodeliv:": False}, st


def test_ads_learning():
    """The new campaign's board item: 'learning day N, X/50' while ACTIVE + learning, then 'optimizer
    ready' for LEARN_READY_DAYS after the gate opens; the learning item closes when it flips."""
    name = "ATOB — Enrollment 2026 — Leads — Oct"
    g = {"id": "C9", "name": name, "status": "ACTIVE", "open": False, "day": 3, "results": 4, "need": 50,
         "days": 7, "maxDays": 14, "asOf": day(0), "firstDay": day(-3), "note": "learning: day 3, 4/50 results"}

    def feed(*rows):
        f = copy.deepcopy(FEED)
        f["autopilot"]["learning"] = list(rows)
        return {"/api/daycare/ads/feed": f}
    items, st = w.watch_ads(make_get(feed(g)), NOW)
    k = keys(items)
    assert k["learn:C9"]["title"] == f"Learning day 3, 4/50 — {name}", k["learn:C9"]
    assert k["learn:C9"]["severity"] == "low" and k["learn:C9"]["evidence"]["window"].startswith("daily run")
    assert st["sources"]["learn:"] is True and st["ok"], st
    assert "learn:C9" not in keys(w.watch_ads(make_get(feed(dict(g, status="PAUSED"))), NOW)[0]), "paused = not learning"
    ready = dict(g, open=True, day=14, results=15, openedOn=day(0))
    k = keys(w.watch_ads(make_get(feed(ready)), NOW)[0])
    assert "learn:C9" not in k and "Optimizer ready" in k["learn:C9:ready"]["title"], sorted(k)
    k = keys(w.watch_ads(make_get(feed(dict(ready, openedOn=day(-5)))), NOW)[0])
    assert not any(x.startswith("learn:") for x in k), "ready item ages off after LEARN_READY_DAYS"
    assert "learn:" not in w.watch_ads(make_get(), NOW)[1]["sources"], "no learning block = nothing to close"
    # on the board: learning → ready closes the learning item and opens the ready one (one ping-worthy NEW)
    daycare_board.STATE.unlink(missing_ok=True)
    a = daycare_board.apply_round([{"domain": "ads", "items": [i for i in w.watch_ads(make_get(feed(g)), NOW)[0]
                                                               if i["key"].startswith("learn:")],
                                    "status": {"ok": True, "sources": {"learn:": True}}}], now=NOW)
    b = daycare_board.apply_round([{"domain": "ads", "items": [i for i in w.watch_ads(make_get(feed(ready)), NOW)[0]
                                                               if i["key"].startswith("learn:")],
                                    "status": {"ok": True, "sources": {"learn:": True}}}], now=NOW + 86400)
    assert len(a["new"]) == 1 and len(b["new"]) == 1 and b["closed"] == a["new"], (a["new"], b)
    daycare_board.STATE.unlink(missing_ok=True)


def test_social_is_not_wired():
    for payload in ({"ok": True, "configured": False}, {"ok": True, "connection": {"connected": True}}):
        items, st = w.watch_social(make_get({"/api/daycare/social": payload}), NOW)
        assert items == [] and st["ok"] is False and st["notWired"] is True and "Unknown" in st["error"], st


def test_systems():
    items, st = w.watch_systems(make_get(), NOW)
    k = keys(items)
    assert set(k) == {"loop:daycare_leads", "ai", "dep:stripe"}, sorted(k)
    assert "Invalid API key" in k["dep:stripe"]["why"] and k["ai"]["center"] == "all"
    assert st["ok"], st
    items, st = w.watch_systems(make_get({"/api/daycare/ghl/health": {"ok": False, "error": "Session expired"},
                                          "/api/daycare/mail": {"ok": False, "via": "gmail", "authDead": True}}), NOW)
    k = keys(items)
    assert "dep:gmail" in k and "dep:ghl" not in k and st["sources"]["dep:ghl"] is False, (sorted(k), st)


def test_run_round_end_to_end():
    daycare_board.STATE.unlink(missing_ok=True)
    trap = []
    saved = (review_agent._claude, review_agent.post_messages)
    review_agent._claude = review_agent.post_messages = lambda *a, **k: trap.append(a) or 1 / 0
    try:
        CALLS.clear()
        res = w.run_round(get=make_get(), now=NOW)
    finally:
        review_agent._claude, review_agent.post_messages = saved
    assert trap == [], "a round makes zero Claude calls"
    assert res["ok"] and res["open"] == len(res["new"]) > 15, res["open"]
    dom = {d["domain"]: d for d in res["domains"]}
    assert set(dom) == {"inbox", "enrollment", "billing", "ads", "social", "roster", "systems"}
    assert dom["social"]["ok"] is False and dom["social"]["notWired"] is True and dom["roster"]["ok"] is False
    assert res["urgent"] and res["urgent"][0]["severity"] == "urgent"
    mail_calls = [c for c in CALLS if c[0] == "/api/daycare/mail"]
    assert len(mail_calls) == 1, "inbox + systems share ONE mail read per round"
    assert not any(p.startswith("/api/daycare/board") for p, _ in CALLS), "watches never call board routes"
    v = daycare_board.view(limit=200, now=NOW)
    assert v["mailDesk"]["needsAnswer"] == 4 and v["lastRound"]["line"] == res["line"]
    for it in v["items"]:
        assert it["evidence"]["source"] and it["evidence"]["window"] and it["center"], it
    # round 2: Gmail fails, Seara's lead got answered → inbox items stay, lead:c1 closes
    leads2 = copy.deepcopy(LEADS)
    leads2["needsHuman"] = leads2["needsHuman"][1:]
    res2 = w.run_round(get=make_get({"/api/daycare/mail": {"ok": False, "error": "Gmail HTTP 503"},
                                     "/api/daycare/leads": leads2}), now=NOW + 3600)
    v2 = {i["key"] for i in daycare_board.view(limit=200, now=NOW + 3600)["items"]}
    assert {"mail:t1", "mail:t3", "mail:t4", "form:m8"} <= v2, "a failed Gmail read never closes mail items"
    assert "lead:c1" not in v2 and daycare_board.item_id("enrollment", "lead:c1") in res2["closed"]
    assert res2["new"] == [] and "inbox" in res2["line"]
    assert daycare_board.view(now=NOW + 3600)["mailDesk"]["ok"] is False, "old subjects are not shown as current"


def test_crash_isolated_and_no_overlap():
    saved = w.WATCHES
    w.WATCHES = saved[:4] + (("social", lambda g, n: 1 / 0),) + saved[5:]
    try:
        res = w.run_round(get=make_get(), now=NOW + 7200)
    finally:
        w.WATCHES = saved
    dom = {d["domain"]: d for d in res["domains"]}
    assert dom["social"]["ok"] is False and "crashed" in dom["social"]["error"] and dom["ads"]["ok"], dom
    again = w.run_round(get=make_get(), now=NOW + 7200 + 30)
    assert again["skipped"].startswith("a round ran 30 s ago") and again["line"] == res["line"], "cooldown"
    assert w._RUN.acquire(blocking=False)
    try:
        assert w.run_round(get=make_get(), now=NOW)["skipped"] == "a round is already running"
    finally:
        w._RUN.release()
    boom = make_get({"/api/daycare/locations": lambda q: 1 / 0})
    out = w._memo(boom)("/api/daycare/locations")
    assert out["ok"] is False and "read failed" in out["error"], "a raising fetch is a failed read"


def main():
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                import traceback
                print("FAIL", name, "->", repr(e))
                traceback.print_exc()
    print("daycare_watches:", "FAILED" if failed else "all OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
