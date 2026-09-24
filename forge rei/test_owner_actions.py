#!/usr/bin/env python3
"""owner_actions.py — sort order, dedupe, fail-soft, archive skip, mock approvals ignored.

No network, no Claude, no connector import. Fake engines stand in for Scout/Marcus/Screener.
Run: cd "forge rei" && FORGE_MARCUS=0 FORGE_VAULT=$(mktemp -d) python3 test_owner_actions.py
"""
import sys
import time
from pathlib import Path

import owner_actions as oa

NOW = int(time.time() * 1000)
H = 3600 * 1000


def it(iid, prio, age=None, kind="CALL"):
    return {"id": iid, "kind": kind, "priority": prio, "ageSec": age}


# 1. sort: urgent → revenue → customer → normal; oldest first inside a tier; unknown age last
got = oa.merge_and_sort([it("n", "normal"), it("r-young", "revenue", 10), it("c", "customer", 5),
                         it("u", "urgent", 1), it("r-old", "revenue", 999), it("r-none", "revenue")])
assert [i["id"] for i in got] == ["u", "r-old", "r-young", "r-none", "c", "n"], [i["id"] for i in got]

# 2. dedupe by id — first wins
got = oa.merge_and_sort([it("x", "normal", 1), it("x", "urgent", 2), it("y", "normal")])
assert [i["id"] for i in got] == ["x", "y"] and got[0]["priority"] == "normal"


# 3. one broken source → exactly one FIX item, everything else still returned
class FakeMarcus:
    def proposals_list(self):
        return [{"id": "p1", "status": "pending", "name": "Ann", "inbound": "how much?", "ts": NOW - H,
                 "classification": "PRICE"},
                {"id": "p2", "status": "pending", "name": "Bob", "inbound": "call me", "ts": NOW - 2 * H,
                 "classification": "READY", "newLead": True},
                {"id": "p3", "status": "sent", "name": "Old", "ts": NOW}]


class FakeScout:
    def leads(self, bucket=None):
        if bucket == "asap":
            return {"leads": [{"id": "c1", "contactId": "k1", "name": "Hot Harry", "reason": "wants out",
                               "lastMessageDate": NOW - 3 * H}]}
        if bucket == "warm":
            return {"leads": [{"id": "c2", "contactId": "k2", "name": "Warm Wendy", "proposedTags": ["triage: warm"],
                               "tagsAppliedAt": None, "lastMessageDate": NOW - H},
                              {"id": "c3", "contactId": "k3", "name": "Tagged Tom", "proposedTags": ["triage: warm"],
                               "tagsAppliedAt": NOW}]}
        return {"leads": []}


def boom(ctx):
    raise RuntimeError("ghl 502")


ctx = {"marcus": FakeMarcus(), "scout": FakeScout(), "screener": None, "deal_prep": None,
       "daycare_client": None, "system": {"active": True, "loops": [
           {"loop": "scout", "label": "Scout", "status": "red", "lastError": "dead", "lastRun": NOW - 9 * H},
           {"loop": "atlas", "status": "green"}], "ai": {"ok": False, "error": "credit balance too low"}}}
srcs = [("marcus_proposals", "wholesale", oa._src_marcus_proposals),
        ("scout_asap", "wholesale", oa._src_scout_asap),
        ("scout_pending_tags", "wholesale", oa._src_scout_pending_tags),
        ("broken", "agency", boom),
        ("system", "system", oa._src_system)]
out = oa.build(ctx, sources=srcs)
ids = [i["id"] for i in out["items"]]
fixes = [i for i in out["items"] if i["kind"] == "FIX"]
assert "fix:broken" in ids and sum(1 for i in ids if i == "fix:broken") == 1, ids
assert {"marcus:p1", "marcus:p2", "scout:asap:k1", "scout:tags:c2", "heartbeat:scout", "ai:down"} <= set(ids), ids
assert "marcus:p3" not in ids and "scout:tags:c3" not in ids, ids
assert "error" not in out and out["ok"] and out["counts"]["total"] == len(ids)
assert out["counts"]["FIX"] == 3 and out["counts"]["APPROVE"] == 3 and out["counts"]["CALL"] == 1, out["counts"]
by = {i["id"]: i for i in out["items"]}
assert by["marcus:p2"]["priority"] == "urgent" and by["marcus:p1"]["priority"] == "revenue"
assert by["scout:asap:k1"]["kind"] == "CALL" and by["scout:asap:k1"]["priority"] == "urgent"
assert by["scout:tags:c2"]["priority"] == "normal" and by["marcus:p2"]["link"] == {"ws": "rei", "page": "Agents"}
assert by["ai:down"]["title"] == "Anthropic credits/auth" and by["ai:down"]["link"] == {"view": "health"}
# urgent block first, then revenue, then normal
prios = [i["priority"] for i in out["items"]]
assert prios == sorted(prios, key=lambda p: oa.PRIORITY_RANK[p]), prios
# oldest first inside the urgent tier: heartbeat (9h) before scout asap (3h) before marcus p2 (2h)
urg = [i["id"] for i in out["items"] if i["priority"] == "urgent" and i["ageSec"] is not None]
assert urg.index("heartbeat:scout") < urg.index("scout:asap:k1") < urg.index("marcus:p2"), urg

# 4. archived business skipped (business_scope may not exist yet — patch the resolver)
orig = oa._is_archived
oa._is_archived = lambda b: b == "wholesale"
try:
    out2 = oa.build(ctx, sources=srcs)
    ids2 = [i["id"] for i in out2["items"]]
    assert not any(i.startswith(("marcus:", "scout:")) for i in ids2), ids2
    assert "fix:broken" in ids2 and "ai:down" in ids2, ids2   # agency + system untouched
finally:
    oa._is_archived = orig
# a missing business_scope module means nothing is archived
assert oa._is_archived("agency") in (False, True)  # never raises

# 5. agency approvals: the in-memory MOCK seed (no state file) is not an owner action
import agency_approvals_io
orig_state = agency_approvals_io.STATE
agency_approvals_io.STATE = Path(sys.argv[1] if len(sys.argv) > 1 else "/nonexistent-dir") / "nope.json"
try:
    assert oa._src_agency_approvals({}) == []   # no state file → no rows (seed removed in WP-G)
finally:
    agency_approvals_io.STATE = orig_state

# 6. system source stays quiet when the fleet isn't active (UI-only Mac) — no false FIX rows
assert oa._src_system({"system": {"active": False, "loops": [{"loop": "x", "status": "red"}]}}) == []
assert oa._src_system({"system": {"ai": {"ok": True}}}) == []
# AI FIX row ages from forge_heartbeat.ai_health's downSince (there is no "since" key)
_down = oa._src_system({"system": {"ai": {"ok": False, "downSince": int(time.time() * 1000) - 7_200_000}}})
assert _down and 7100 <= _down[0]["ageSec"] <= 7300, _down

# 7. build() on an empty ctx never raises and returns the contract shape
empty = oa.build({}, sources=[])
assert empty["ok"] and empty["items"] == [] and empty["counts"]["total"] == 0 and "generatedAt" in empty

# 8. stale rows collapse to one summary row per source; FIX + fresh rows untouched
_d = 86400
_rows = [dict(oa._item(f"marcus:{i}", "APPROVE", "wholesale", "urgent", f"r{i}", source="marcus"), ageSec=40 * _d)
         for i in range(3)]
_rows += [dict(oa._item("marcus:new", "APPROVE", "wholesale", "revenue", "fresh", source="marcus"), ageSec=_d),
          dict(oa._item("ai:down", "FIX", "system", "urgent", "ai"), ageSec=90 * _d)]
_c = oa.collapse_stale(_rows, 30)
_ids = sorted(r["id"] for r in _c)
assert _ids == ["ai:down", "marcus:new", "stale:marcus"], _ids
_s = [r for r in _c if r["id"] == "stale:marcus"][0]
assert _s["stale"] == 3 and _s["priority"] == "normal" and _s["kind"] == "REVIEW", _s

# 9. a Marcus draft whose "inbound" is our own outreach never becomes an APPROVE row (rule 4)
class _M:
    def proposals_list(self):
        return [{"id": "a", "status": "pending", "inbound": "just checking in, i dont want to be a bug", "ts": 1},
                {"id": "b", "status": "pending", "inbound": "yes I want to sell", "ts": 1}]
assert [r["id"] for r in oa._src_marcus_proposals({"marcus": _M()})] == ["marcus:b"]

print("test_owner_actions: OK")


def test_daycare_lead_desk_contract():
    # WP-E needs_human() shape → one row per family, real priority + age, no double prefix.
    import sys, types
    fake = types.ModuleType("daycare_leads")
    fake.needs_human = lambda: [{"id": "daycare-lead:c1", "contactId": "c1", "title": "Call Jo",
                                 "why": "unanswered 40m", "ageSec": 2400, "priority": "REVENUE"}]
    sys.modules["daycare_leads"] = fake
    try:
        rows = oa._src_daycare_leads({})
    finally:
        del sys.modules["daycare_leads"]
    assert len(rows) == 1 and rows[0]["id"] == "daycare:c1", rows
    assert rows[0]["priority"] == "revenue" and 2390 <= rows[0]["ageSec"] <= 2410, rows
    assert rows[0]["why"] == "Solomon · Leads: unanswered 40m", rows      # Solomon's lane
    dup = oa._item("daycare:c1", "CALL", "daycare", "revenue", "Call Jo — new enrollment inquiry")
    assert len(oa.merge_and_sort(rows + [dup])) == 1


def test_daycare_reply_drafts():
    # Solomon · Replies: one APPROVE row per pending draft, keyed like the lead desk so a
    # family with a ready draft is ONE row — and it inherits the lead's URGENT priority.
    import sys, types
    now = int(time.time() * 1000)
    fake_r = types.ModuleType("daycare_replies")
    fake_r.view = lambda: {"pending": [
        {"contactId": "c1", "parentName": "Jo", "center": "921 N 18th St", "action": "draft",
         "category": "tour", "flags": ["money"], "inboundAt": now - 600_000,
         "inboundText": "PRIVATE parent text"},
        {"contactId": "c2", "parentName": "I", "action": "escalate", "category": "medical",
         "inboundAt": now - 60_000}]}
    fake_l = types.ModuleType("daycare_leads")
    fake_l.needs_human = lambda: [{"contactId": "c1", "title": "Reply to Jo", "ageSec": 900,
                                   "why": "Parent message unanswered 15+ min",
                                   "priority": "URGENT"}]
    saved = {m: sys.modules.get(m) for m in ("daycare_replies", "daycare_leads")}
    sys.modules.update(daycare_replies=fake_r, daycare_leads=fake_l)
    try:
        rows = oa._src_daycare_replies({}) + oa._src_daycare_leads({})
    finally:
        for m, mod in saved.items():
            if mod is None:
                sys.modules.pop(m, None)
            else:
                sys.modules[m] = mod
    got = {r["id"]: r for r in oa.merge_and_sort(rows)}
    assert set(got) == {"daycare:c1", "daycare:c2"}, got                  # one row per family
    c1, c2 = got["daycare:c1"], got["daycare:c2"]
    assert c1["kind"] == "APPROVE" and c1["source"] == "daycare_replies", c1
    assert c1["priority"] == "urgent" and 590 <= c1["ageSec"] <= 700, c1   # never demoted
    assert c1["title"] == "Approve Solomon's reply to Jo — 921 N 18th St", c1
    assert c1["why"].startswith("Solomon · Replies: tour") and "money" in c1["why"], c1
    assert "unanswered" in c1["why"] and "PRIVATE" not in c1["why"], c1   # no message text
    assert c2["priority"] == "customer" and "a parent" in c2["title"], c2  # "I" is no name
    assert "escalated (medical)" in c2["title"], c2


if __name__ == "__main__":
    test_daycare_lead_desk_contract()
    print("test_daycare_lead_desk_contract: OK")
    test_daycare_reply_drafts()
    print("test_daycare_reply_drafts: OK")
