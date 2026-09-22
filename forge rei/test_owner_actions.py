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
    assert agency_approvals_io.list_queue("pending")["queue"], "seed should be present in memory"
    assert oa._src_agency_approvals({}) == []
finally:
    agency_approvals_io.STATE = orig_state

# 6. system source stays quiet when the fleet isn't active (UI-only Mac) — no false FIX rows
assert oa._src_system({"system": {"active": False, "loops": [{"loop": "x", "status": "red"}]}}) == []
assert oa._src_system({"system": {"ai": {"ok": True}}}) == []

# 7. build() on an empty ctx never raises and returns the contract shape
empty = oa.build({}, sources=[])
assert empty["ok"] and empty["items"] == [] and empty["counts"]["total"] == 0 and "generatedAt" in empty

print("test_owner_actions: OK")
