#!/usr/bin/env python3
"""mission_control.py spec §15 tiles — labels present, and a failing source drops ITS tiles
plus exactly one warn line (never a fake 0). Fake modules only: no network, no connector,
no real marcus_state reads.
Run: cd "forge rei" && python3 test_mission_tiles.py
"""
import sys
import time
import types

NOW = int(time.time() * 1000)


def fake(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


def boom(*_a, **_k):
    raise RuntimeError("boom")


fake("business_scope", archived=lambda: {"dropship"}, is_archived=lambda b: b == "dropship")
fake("send_ledger", last_reply_msg_date=lambda conv: None)
fake("daycare_replies", view=lambda: {"pending": []})   # Owner Actions: Solomon · Replies
fake("agency_agents", status=lambda: {"connected": True, "agents": [{"online": True}]})
fake("agency_approvals_io", list_queue=lambda s: {"counts": {"pending": 0}, "queue": []})
cs = fake("agency_callsheet", list_leads=lambda: {"counts": {
    "new": 7, "answered": 1, "interested": 2, "no_answer": 0, "callback": 3, "dead": 0,
    "bad_number": 0, "total": 13}})
aio = fake("agency_io", stats=lambda: {"activeClients": 4, "mrr": 3200.0})
fake("deals", list_deals=lambda: [{"contractStatus": "sent"}, {"contractStatus": "completed"},
                                   {"contractStatus": "none"}])
dl = fake("daycare_leads")
ace = fake("ace", call_ready_list=lambda: {"callReady": [{"convId": "c9", "name": "Zed",
                                                          "updatedAt": NOW}]})
hub = fake("agents_hub", registry=lambda: [
    {"status": "IDLE"}, {"status": "IDLE"}, {"status": "RUNNING"},
    {"status": "WAITING FOR APPROVAL"}, {"status": "FAILED"}, {"status": "DEGRADED"},
    {"status": "DISABLED"}])

LEAD_OK = {"lastOkAt": NOW, "error": None, "kpis": {
    "newLeads7d": {"total": 5}, "needsHuman": 2, "medianResponseSec": 540}}


class Scout:
    def summary(self):
        return {"counts": {"asap": 2, "warm": 1}, "total": 9, "aiScoring": True}

    def leads(self, bucket=None):
        return {"leads": [{"id": "v1", "contactId": "k1", "name": "Ann", "lastMessageDate": NOW},
                          {"id": "v2", "contactId": "k2", "name": "Bob", "lastMessageDate": NOW}]}


class Screener:
    screenings = {"k3": {"name": "Cy", "updatedAt": NOW, "report": {"interest": "interested"}}}

    def queue(self):
        return {"count": 0}


class Solomon:
    def status(self):
        return {"aiReady": True, "systems": [{"name": "Supabase", "connected": True}]}


import mission_control as mc  # noqa: E402


def card(snap, bid):
    return next(c for c in snap["businesses"] if c["id"] == bid)


def labels(c):
    return {m["label"]: m["value"] for m in c["metrics"]}


def warns(c):
    return [a["text"] for a in c["attention"] if a["sev"] == "warn"]


# 1. happy path — every spec label, real values
dl.view = lambda: dict(LEAD_OK)
s = mc.snapshot(scout=Scout(), screener=Screener(), solomon=Solomon(), system={})
ag, rei, dc = labels(card(s, "agency")), labels(card(s, "rei")), labels(card(s, "daycare"))
assert (ag["Calls ready"], ag["Callbacks"], ag["Interested"], ag["Clients"], ag["MRR"]) == \
    (7, 3, 2, 4, "$3,200"), ag
assert rei["Owner calls required"] == 4, rei           # 2 hot + 1 ACE + 1 screened
assert (rei["Contracts"], rei["Deals"]) == (2, 3), rei
assert (dc["New leads (7d)"], dc["Needs human"], dc["Response time"]) == (5, 2, "9m"), dc
assert list(ag)[:5] == ["Calls ready", "Callbacks", "Interested", "Clients", "MRR"]  # spec first
assert not warns(card(s, "agency")) and not warns(card(s, "daycare")), s
a = s["agents"]
assert (a["ok"], a["healthy"], a["running"], a["failed"], a["waiting"], a["total"]) == \
    (True, 4, 1, 1, 1, 6), a                            # DISABLED left out
assert "dropship" not in [c["id"] for c in s["businesses"]]   # archived stays hidden

# 2. failing sources drop ONLY their tiles + exactly one warn line each
aio.stats = boom
ace.call_ready_list = boom
hub.registry = boom
dl.view = lambda: {"lastOkAt": None, "error": "Has not run yet", "kpis": {
    "newLeads7d": {"total": 0}, "needsHuman": 0, "medianResponseSec": None}}
s = mc.snapshot(scout=Scout(), screener=Screener(), solomon=Solomon(), system={})
agc, reic, dcc = card(s, "agency"), card(s, "rei"), card(s, "daycare")
assert "Clients" not in labels(agc) and "MRR" not in labels(agc), labels(agc)
assert labels(agc)["Calls ready"] == 7                  # other source untouched
assert len([w for w in warns(agc) if w.startswith("Clients unavailable")]) == 1, warns(agc)
assert "Owner calls required" not in labels(reic) and labels(reic)["Deals"] == 3
assert len([w for w in warns(reic) if w.startswith("Owner Actions unavailable")]) == 1
for lab in ("New leads (7d)", "Needs human", "Response time"):
    assert lab not in labels(dcc), labels(dcc)          # never a fake 0
assert len([w for w in warns(dcc) if w.startswith("Solomon · Leads unavailable")]) == 1, warns(dcc)
assert s["agents"]["ok"] is False and "healthy" not in s["agents"]
assert s["agents"]["warn"].startswith("Agent registry unavailable")

# 3. stale sweep: last good tiles stay, one warn says so; no response sample = "—"
dl.view = lambda: dict(LEAD_OK, error="GHL read failed: HTTPError 500",
                       kpis=dict(LEAD_OK["kpis"], medianResponseSec=None))
dcc = card(mc.snapshot(scout=Scout(), screener=Screener(), solomon=Solomon(), system={}), "daycare")
assert labels(dcc)["Response time"] == "—" and labels(dcc)["Needs human"] == 2
assert len([w for w in warns(dcc) if w.startswith("Solomon · Leads:")]) == 1, warns(dcc)

# 4. missing count key = failing source (strict read), not a silent 0
cs.list_leads = lambda: {"counts": {"total": 0}}
agc = card(mc.snapshot(scout=Scout(), screener=Screener(), solomon=Solomon(), system={}), "agency")
assert "Calls ready" not in labels(agc) and any(w.startswith("Call Sheet") for w in warns(agc))

print("test_mission_tiles: all passed")
sys.exit(0)
