#!/usr/bin/env python3
"""Agent Control Center registry (agents_hub.registry, spec §9).

    FORGE_MARCUS=0 FORGE_VAULT=$(mktemp -d) python3 test_agent_registry.py

Never imports connector: agents_hub._engine is stubbed to None, and every state file
the registry reads or writes is redirected into a temp dir.
"""
import os
import sys
import tempfile
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="agent_registry_test_"))

import agent_bus          # noqa: E402
import agents_hub         # noqa: E402
import daycare_ghl        # noqa: E402
import daycare_leads      # noqa: E402
import daycare_replies    # noqa: E402
import forge_heartbeat    # noqa: E402

agents_hub.TASKS = TMP / "hub_tasks.json"
agent_bus.STATE = TMP / "agent_bus.json"
forge_heartbeat.STATE = TMP / "heartbeats.json"
agents_hub._engine = lambda _aid: None          # no connector, no live engines
for _mod in ("ace", "autopilot", "daily_brief", "daily_recap", "test_mode"):
    __import__(_mod).STATE = TMP / f"{_mod}.json"
# Solomon's lanes (Replies + Leads) are read on his row — never the real marcus_state.
daycare_replies.STATE = TMP / "daycare_replies.json"
daycare_leads.STATE = TMP / "daycare_leads.json"
daycare_leads.STAGES_STATE = TMP / "daycare_lead_stages.json"
daycare_ghl._FORM_CHILD_STATE = TMP / "daycare_form_children.json"

NOW = int(time.time() * 1000)
REQUIRED = ("id", "name", "business", "purpose", "status", "lastRun", "lastSuccessAt",
            "nextRun", "tasksCompleted", "tasksFailed", "errorCount", "currentTask",
            "dependencyHealth", "chatTarget", "taskCapable", "lastError", "archived")


def _rec(**kw):
    r = {"lastRun": NOW - 10_000, "interval": 180, "staleMult": 2.0, "errStreak": 0,
         "lastError": None}
    r.update(kw)
    return r


def test_status_mapping():
    s = agents_hub.status_of
    assert s([_rec()], NOW) == "IDLE"
    assert s([_rec(lastRun=NOW - 3600_000)], NOW) == "FAILED"            # stale
    assert s([_rec(errStreak=3, lastError="boom")], NOW) == "FAILED"      # red streak
    assert s([_rec(errStreak=1, lastError="boom")], NOW) == "DEGRADED"    # errStreak
    assert s([_rec()], NOW, ai_ok=False) == "DEGRADED"                     # AI down
    assert s([_rec()], NOW, ai_ok=None) == "IDLE"                          # AI unknown
    assert s([_rec(retired=True)], NOW) == "DISABLED"                      # retired loop
    assert s([_rec()], NOW, enabled=False) == "DISABLED"                   # knob / mode off
    assert s([_rec(errStreak=9, lastError="x")], NOW, archived=True) == "DISABLED"
    assert s([_rec()], NOW, pending=2) == "WAITING FOR APPROVAL"
    assert s([_rec()], NOW, pending=2, running=True) == "RUNNING"
    assert s([], NOW) == "IDLE"                                            # no loop (chat-only)
    assert s([_rec(errStreak=1, lastError="x")], NOW, pending=4) == "DEGRADED"  # health first


def test_roster_complete():
    ids = [a["id"] for a in agents_hub.AGENTS]
    assert len(ids) == len(set(ids)), ids
    for want in ("marcus", "scout", "atlas", "followup", "ace", "autopilot", "dyson", "eco",
                 "solomon", "midas", "orion", "briefs"):
        assert want in ids, want
    for a in agents_hub.AGENTS:
        assert a["business"] in agents_hub.BUSINESS, a
        via = a.get("chatVia")
        assert via is None or via in ids, a       # every delegate lands on a real brain

    rows = agents_hub.registry(now=NOW)
    assert {r["id"] for r in rows} == set(ids)
    for r in rows:
        missing = [k for k in REQUIRED if k not in r]
        assert not missing, (r["id"], missing)
        assert r["status"] in agents_hub.STATUSES, r
        assert set(r["dependencyHealth"]) >= {"ai", "keys", "heartbeat"}, r


def test_registry_from_real_signals():
    forge_heartbeat.beat("scout", 180, "Scout")                   # fresh + clean
    for _ in range(3):
        forge_heartbeat.beat("atlas", 900, "Atlas", error="Anthropic API error (400)")
    forge_heartbeat.beat("followup", 1800, "Follow-up", error="checkback: timeout")

    real_pending = agents_hub._pending
    agents_hub._pending = lambda aid, q: 3 if aid == "scout" else 0
    try:
        by = {r["id"]: r for r in agents_hub.registry()}
    finally:
        agents_hub._pending = real_pending

    assert by["scout"]["status"] == "WAITING FOR APPROVAL", by["scout"]
    assert by["scout"]["pendingApprovals"] == 3
    assert by["scout"]["lastSuccessAt"] == by["scout"]["lastRun"]     # clean beat = success
    assert by["scout"]["nextRun"] == by["scout"]["lastRun"] + 180_000
    assert by["atlas"]["status"] == "FAILED", by["atlas"]
    assert by["atlas"]["lastError"].startswith("Anthropic"), by["atlas"]
    assert by["atlas"]["errorCount"] >= 3
    assert by["followup"]["status"] == "DEGRADED", by["followup"]
    # ACE + autopilot default OFF → DISABLED, read without flipping anything
    assert by["ace"]["status"] == "DISABLED", by["ace"]
    assert by["autopilot"]["status"] == "DISABLED", by["autopilot"]
    import ace
    import autopilot
    assert ace.mode() == "off" and autopilot.enabled() is False
    # Midas's scheduled brief is off unless FORGE_DROPSHIP_BRIEF says otherwise
    if os.environ.get("FORGE_DROPSHIP_BRIEF", "0") == "0":
        assert by["midas"]["status"] == "DISABLED", by["midas"]
    # delegates route chat to a real brain
    assert by["ace"]["chatTarget"] == "marcus" and by["briefs"]["chatTarget"] == "orion"
    assert by["briefs"]["dependencyHealth"]["ai"] == "n/a"
    # no loop key → honest unknown, not zero
    assert by["dyson"]["errorCount"] is None and by["dyson"]["lastRun"] is None


def test_ai_down_degrades_ai_agents_only():
    real = agents_hub._ai_health
    agents_hub._ai_health = lambda: {"ok": False, "reason": "credit balance exhausted"}
    try:
        by = {r["id"]: r for r in agents_hub.registry()}
    finally:
        agents_hub._ai_health = real
    assert by["eco"]["status"] == "DEGRADED", by["eco"]
    assert by["eco"]["dependencyHealth"]["ai"] == "down"
    assert "credit" in by["eco"]["dependencyHealth"]["aiReason"]
    assert by["briefs"]["dependencyHealth"]["ai"] == "n/a"    # never calls Claude


def test_archived_business_disabled_and_last():
    sys.modules["business_scope"] = types.SimpleNamespace(
        is_archived=lambda b: b == "agency")
    try:
        rows = agents_hub.registry()
    finally:
        sys.modules.pop("business_scope", None)
    agency = [r for r in rows if r["business"] == "agency"]
    assert agency and all(r["status"] == "DISABLED" and r["archived"] for r in agency)
    first_archived = min(i for i, r in enumerate(rows) if r["archived"])
    assert all(r["archived"] for r in rows[first_archived:]), [r["id"] for r in rows]


def test_archived_rei_disables_wholesale():
    # business_scope calls the wholesale workspace "rei" — the registry must map it
    sys.modules["business_scope"] = types.SimpleNamespace(is_archived=lambda b: b == "rei")
    try:
        rows = agents_hub.registry()
    finally:
        sys.modules.pop("business_scope", None)
    whs = [r for r in rows if r["business"] == "wholesale"]
    assert whs and all(r["status"] == "DISABLED" and r["archived"] for r in whs), whs
    assert not any(r["archived"] for r in rows if r["business"] != "wholesale")


def test_marcus_event_driven_not_failed():
    # marcus_sms (legacy SMS loop, off by default) must not drive Marcus's card
    forge_heartbeat.beat("marcus_sms", 60, "Marcus SMS responder", error="x")
    ts = NOW - 5_000
    scr = types.SimpleNamespace(screenings={"c1": {"updatedAt": ts - 9_000},
                                            "c2": {"updatedAt": ts}})
    real_eng, real_ai, real_pending = agents_hub._engine, agents_hub._ai_health, \
        agents_hub._pending
    agents_hub._engine = lambda aid: scr if aid == "screener" else None
    agents_hub._ai_health = lambda: {"ok": True}
    try:
        m = {r["id"]: r for r in agents_hub.registry()}["marcus"]
        agents_hub._pending = lambda aid, q: 2 if aid == "marcus" else 0
        m2 = {r["id"]: r for r in agents_hub.registry()}["marcus"]
        agents_hub._engine = lambda aid: None                  # screener unreachable
        m3 = {r["id"]: r for r in agents_hub.registry()}["marcus"]
    finally:
        agents_hub._engine, agents_hub._ai_health, agents_hub._pending = \
            real_eng, real_ai, real_pending
    assert m["status"] == "IDLE", m
    assert m["dependencyHealth"]["heartbeat"] == "none", m
    assert m["lastRun"] == ts and m["lastSuccessAt"] == ts, m
    assert m2["status"] == "WAITING FOR APPROVAL", m2
    assert m3["status"] == "WAITING FOR APPROVAL" and m3["lastRun"] is None \
        and m3["lastError"] is None, m3                          # fails soft, not FAILED


def test_daily_agents_no_poll_based_next_run():
    forge_heartbeat.beat("daily_brief", 300, "Daily brief")
    by = {r["id"]: r for r in agents_hub.registry()}
    assert by["orion"]["nextRun"] is None and by["briefs"]["nextRun"] is None, \
        (by["orion"]["nextRun"], by["briefs"]["nextRun"])


def test_task_failed_round_trip():
    out = agents_hub.send_task("scout", "rank the 5 hottest leads")
    tid = out["task"]["id"]
    res = agents_hub.update_task(tid, "failed", error="Anthropic API error (400): "
                                 "Your credit balance is too low")
    assert res["ok"] and res["task"]["status"] == "failed"
    t = next(t for t in agents_hub.tasks("scout")["tasks"] if t["id"] == tid)
    assert t["status"] == "failed" and "credit balance" in t["error"], t
    by = {r["id"]: r for r in agents_hub.registry()}
    assert by["scout"]["tasksFailed"] >= 1
    # reopening clears the stale error; a bogus status is refused
    assert "error" not in agents_hub.update_task(tid, "open")["task"]
    assert agents_hub.update_task(tid, "exploded").get("error") == "bad status"


def test_delegate_tasks_reach_their_brain():
    agents_hub.send_task("ace", "hold thread 123 until Monday")
    block = agents_hub.open_tasks_block("marcus")
    assert "hold thread 123" in block and "(for ACE)" in block, block
    assert agents_hub.open_tasks_block("atlas") == "" or "hold thread" not in \
        agents_hub.open_tasks_block("atlas")


def test_solomon_owns_reply_and_lead_lanes():
    """The Reply Desk + Lead Desk are Solomon's lanes, not rows: their drafts are his
    approval queue, their loop health folds into his status, his chat sees their state."""
    import json
    assert "daycare_replies" not in agents_hub._BY_ID                 # a lane, not a row
    assert agents_hub._BY_ID["solomon"]["hb"] == ["solomon", "daycare_replies", "daycare_leads"]
    daycare_replies.STATE.write_text(json.dumps({"lastRunAt": NOW, "drafts": {
        "c1": {"contactId": "c1", "status": "pending", "action": "draft",
               "inboundAt": NOW - 600_000},
        "c2": {"contactId": "c2", "status": "pending", "action": "escalate",
               "inboundAt": NOW - 60_000},
        "c3": {"contactId": "c3", "status": "sent", "inboundAt": NOW}}}))
    forge_heartbeat.beat("solomon", 900, "Solomon director")
    forge_heartbeat.beat("daycare_replies", 300, "Solomon · Replies")
    forge_heartbeat.beat("daycare_leads", 900, "Solomon · Leads", error="GHL read failed: 500")
    real_ai = agents_hub._ai_health
    agents_hub._ai_health = lambda: {"ok": True}
    try:
        s = {r["id"]: r for r in agents_hub.registry()}["solomon"]
        forge_heartbeat.beat("daycare_leads", 900, "Solomon · Leads")    # lane recovers
        s2 = {r["id"]: r for r in agents_hub.registry()}["solomon"]
        # a task filed under the retired Reply Desk id still reaches Solomon's prompt
        agents_hub._save(agents_hub._load() + [{"id": "tfold", "agentId": "daycare_replies",
                                                "agentName": "Reply Desk", "status": "open",
                                                "title": "check the Jones draft"}])
        tasks_block = agents_hub.open_tasks_block("solomon")
        ctx = agents_hub._delegate_context("solomon")
        lanes = agents_hub._lanes_block("solomon")
    finally:
        agents_hub._ai_health = real_ai
        for loop in ("solomon", "daycare_replies", "daycare_leads"):
            forge_heartbeat.retire(loop)
        daycare_replies.STATE.unlink()
    assert s["pendingApprovals"] == 2 and s["approvalQueue"] == "daycare_replies", s
    assert s["status"] == "DEGRADED", s                     # a sick lane shows on his row
    assert s["lastError"].startswith("Solomon · Leads: GHL read failed"), s["lastError"]
    assert s["dependencyHealth"]["heartbeat"] == "amber", s["dependencyHealth"]
    assert "Replies: 2 draft(s) waiting on you" in s["work"], s["work"]
    assert s2["status"] == "WAITING FOR APPROVAL" and s2["lastError"] is None, s2
    assert "check the Jones draft" in tasks_block, tasks_block
    r = ctx["replies"]
    assert (r["pending"], r["escalations"]) == (2, 1) and 590 <= r["oldestPendingAgeSec"] <= 700, r
    assert "leads" in ctx and "YOUR LIVE LANES" in lanes
    assert agents_hub._lanes_block("midas") == ""           # only directors with lanes


def test_chat_error_text_is_surfaced():
    out = agents_hub._flag_error({"reply": "Hit an error reaching my brain: Anthropic API "
                                           "error (400): Your credit balance is too low"})
    assert out["error"].startswith("Anthropic API error (400)"), out
    assert "credit balance" in out["reply"]                     # reply keeps the text too
    ok = agents_hub._flag_error({"reply": "Here are your 5 hottest leads"})
    assert "error" not in ok


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("test_agent_registry: all passed")
