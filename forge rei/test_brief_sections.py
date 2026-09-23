#!/usr/bin/env python3
"""Cross-business morning brief + nightly recap (Wave-2 #1, spec §16/§17).

Pure fixture test — no network, no Claude, no connector import (connector.py is only read
as source to pin the dedupe keys and the zero-Claude gather).
Run: cd "forge rei" && python3 test_brief_sections.py   (exit 1 on failure)
"""
import ast
from pathlib import Path

import daily_brief
import daily_recap

HERE = Path(__file__).resolve().parent

FULL = {
    "date": "Tue Sep 22",
    "hot": 3, "warm": 5, "replies": 12, "approvals": 2,
    "openOpps": 9, "pipelineValue": 412000, "appointments": 1,
    "topLeads": [{"name": "Seller A", "last": "call me tomorrow"}],
    "spendLine": "$4.10 AI · $1.20 SMS",
    "staleAgents": ["Atlas"],
    "archived": [],
    "agency": {"callsReady": 47, "callbacks": 8, "interested": 3, "clients": 2, "mrr": 1500},
    "daycare": {"newLeads7d": 9, "needsHuman": 2, "medianResponseSec": 540, "stale": False},
    "agents": {"healthy": 10, "running": 2, "waiting approval": 1, "degraded": 1, "failed": 1},
    "ownerCalls": 3,
    "ownerCounts": {"total": 7},
    "ownerItems": [
        {"kind": "FIX", "title": "Loop down: Atlas", "business": "system"},
        {"kind": "CALL", "title": "Call Seller A", "business": "wholesale"},
        {"kind": "CALL", "title": "Call Seller B", "business": "wholesale"},
        {"kind": "CALLBACK", "title": "Call back ABC Plumbing", "business": "agency"},
        {"kind": "APPROVE", "title": "Approve daycare Meta rec", "business": "daycare"},
        {"kind": "REVIEW", "title": "Review client website", "business": "agency"},
        {"kind": "CALL", "title": "47 prospects ready to dial", "business": "agency"},
    ],
    "fixes": ["Loop down: Atlas", "Anthropic credits/auth"],
}

SECTIONS = ("<b>AGENCY</b>", "<b>WHOLESALE</b>", "<b>DAYCARE</b>", "<b>AGENTS</b>")

# 1. morning brief: every section + spec lines
b = daily_brief.build_text(FULL)
for s in SECTIONS + ("<b>OWNER TASKS</b>",):
    assert s in b, s
for frag in ("Ready to dial: <b>47</b>", "Callbacks: <b>8</b>", "Interested: <b>3</b>",
             "Clients: <b>2</b>", "MRR: <b>$1,500</b>", "3 hot · 5 warm",
             "Owner calls required: <b>3</b>", "9 open · $412k", "New leads (7d): <b>9</b>",
             "Need a human: <b>2</b>", "Median response: <b>9m</b>",
             "10 healthy · 2 running · 1 waiting approval · 1 degraded · 1 failed",
             "1. [FIX] Loop down: Atlas", "5. [APPROVE] Approve daycare Meta rec",
             "OWNER TASKS</b> — 7 total", "Stale agents: Atlas"):
    assert frag in b, (frag, b)
assert "6. [" not in b, "owner tasks capped at 5"

# 2. nightly recap: sections + failed today + tomorrow's first 5 (FIX rows not repeated)
r = daily_recap.build_text(FULL)
for s in SECTIONS + ("FAILED TODAY", "TOMORROW — FIRST 5", "Still open"):
    assert s in r, (s, r)
assert r.count("Loop down: Atlas") == 1, "red loop + FIX row dedupe"
assert "• Anthropic credits/auth" in r
assert "1. [CALL] Call Seller A" in r and "5. [REVIEW] Review client website" in r
assert "[FIX]" not in r, "tomorrow's list skips FIX rows (they're under FAILED TODAY)"
assert "Hot leads to text back: <b>3</b>" in r
assert r.count("Replies waiting") == 0, "recap WHOLESALE block leaves open loops to 'Still open'"

# 3. missing source → its line is omitted, never a fake 0
bare = {"date": "Tue Sep 22", "hot": 1}
for txt in (daily_brief.build_text(bare), daily_recap.build_text(bare)):
    for s in ("AGENCY", "DAYCARE", "AGENTS", "OWNER TASKS", "TOMORROW", "FAILED TODAY",
              "Ready to dial", "MRR", "Need a human", "Owner calls required"):
        assert s not in txt, (s, txt)
part = dict(FULL, agency={"clients": 2, "mrr": 0})        # callsheet read failed
t = daily_brief.build_text(part)
assert "Ready to dial" not in t and "Callbacks" not in t and "Clients: <b>2</b>" in t
assert "MRR: <b>$0</b>" in t, "a real 0 from a good read still shows"
t = daily_brief.build_text(dict(FULL, daycare={"newLeads7d": 4, "needsHuman": 0,
                                               "medianResponseSec": None, "stale": True}))
assert "Median response" not in t and "Need a human: <b>0</b>" in t and "sweep failed" in t

# 4. archived businesses are skipped (sections, open loops, top leads)
arch = dict(FULL, archived=["agency", "wholesale"])
for txt in (daily_brief.build_text(arch), daily_recap.build_text(arch)):
    assert "AGENCY" not in txt and "WHOLESALE" not in txt and "DAYCARE" in txt, txt
    assert "Seller A —" not in txt and "Hot leads to text back" not in txt and "3 hot" not in txt

# 5. old-shape stats (pre-wave-2) still render the brief exactly like before, no crash
old = {k: FULL[k] for k in ("date", "hot", "warm", "replies", "approvals", "openOpps",
                            "pipelineValue", "appointments", "topLeads", "spendLine")}
t = daily_brief.build_text(old)
assert "<b>WHOLESALE</b>" in t and "Top hot leads" in t and "OWNER TASKS" not in t
assert daily_brief.build_text(None) and daily_recap.build_text(None)

# 6. dedupe keys + send-once-per-day wiring unchanged
src = (HERE / "connector.py").read_text()
assert 'dedupe_key="daily_brief:" + daily_brief.today_key()' in src
assert 'dedupe_key="daily_recap:" + daily_recap.today_key()' in src

# 7. zero Claude: the gather touches no model path; the formatters import no AI module
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_gather_brief_stats")
names = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)} | \
        {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
for bad in ("_claude", "ORION", "SOLOMON", "MIDAS", "learn", "chat", "analyze", "build_brief",
            "maybe_daily", "review_agent"):
    assert bad not in names, bad
for mod in ("daily_brief.py", "daily_recap.py"):
    body = (HERE / mod).read_text()
    assert "review_agent" not in body and "_claude" not in body, mod

print("test_brief_sections: all OK")
print("\n----- morning brief (fixture) -----\n" + b)
print("\n----- nightly recap (fixture) -----\n" + r)
