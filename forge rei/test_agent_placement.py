"""Every agent only where it works. Run: python3 test_agent_placement.py (exit 1 on failure).

Marcus (+Scout/Atlas/Follow-up/ACE/Autopilot) = Wholesale · Dyson (+Eco) = Agency ·
Solomon = Daycare · Midas = Dropship · Orion = cross-business surfaces only."""
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("FORGE_ACTION_LOG", str(Path(tempfile.mkdtemp()) / "actions.jsonl"))
HERE = Path(__file__).parent

import agents_hub
import review_agent


def _no_claude(*a, **k):
    raise AssertionError("a refused chat must never reach Claude")


def test_workspace_rosters():
    want = {"wholesale": ["marcus"], "agency": ["dyson"], "daycare": ["solomon"],
            "dropship": ["midas"], "cross": ["orion"]}
    for biz, ids in want.items():
        got = [a["id"] for a in agents_hub.roster(biz)["agents"]]
        assert got == ids, (biz, got)
    assert [a["id"] for a in agents_hub.roster()["agents"]] == ["marcus", "dyson", "solomon", "midas", "orion"]
    for lane, main in (("scout", "marcus"), ("atlas", "marcus"), ("followup", "marcus"),
                       ("ace", "marcus"), ("autopilot", "marcus"), ("eco", "dyson")):
        assert agents_hub.main_agent(lane) == main
        assert agents_hub._BY_ID[lane]["business"] == agents_hub._BY_ID[main]["business"]


def test_wrong_workspace_pointer():
    ww = agents_hub.wrong_workspace
    for aid, ws in (("marcus", "wholesale"), ("marcus", "rei"), ("scout", "wholesale"),
                    ("dyson", "agency"), ("eco", "agency"), ("solomon", "daycare"),
                    ("midas", "dropship"), ("orion", "cross"), ("solomon", None), ("dyson", ""),
                    ("retell-agent-1", "wholesale"), ("", "wholesale")):
        assert ww(aid, ws) is None, (aid, ws, ww(aid, ws))
    msg = ww("dyson", "daycare")
    assert "Agency workspace" in msg and "Ask Solomon here" in msg, msg
    assert "Daycare workspace" in ww("solomon", "agency") and "Ask Dyson" in ww("solomon", "agency")
    assert "Wholesale (REI)" in ww("scout", "daycare")
    assert "Agency workspace" in ww("eco", "wholesale")
    assert "Mission Control" in ww("orion", "agency")
    assert "Outbound" in ww("retell-agent-1", "daycare")


def test_cross_workspace_chat_and_task_refused():
    saved = (review_agent._claude, review_agent.post_messages, agents_hub.TASKS)
    review_agent._claude = review_agent.post_messages = _no_claude
    agents_hub.TASKS = Path(tempfile.mkdtemp()) / "hub_tasks.json"
    try:
        out = agents_hub.chat(None, None, "dyson", "what is the best daycare ad", business="daycare")
        assert out["refused"] and out["wrongWorkspace"] and "Solomon" in out["reply"], out
        out = agents_hub.chat(None, None, "eco", "ads?", business="wholesale")
        assert out["refused"] and out["agent"] == "Dyson", out
        res = agents_hub.send_task("solomon", "do agency work", business="agency")
        assert res.get("wrongWorkspace") and "Daycare workspace" in res["error"], res
        assert not agents_hub.TASKS.exists(), "a refused task is never filed"
    finally:
        review_agent._claude, review_agent.post_messages, agents_hub.TASKS = saved


def test_agent_to_agent_tasks_cross_businesses():
    """Owner 2026-10-18: any agent files a task on any other agent. Only the UI chat placement
    (`business` = the workspace a human typed in) refuses; a chat-filed task never carries it."""
    import telegram_agent as ta
    saved = agents_hub.TASKS
    agents_hub.TASKS = Path(tempfile.mkdtemp()) / "hub_tasks.json"
    try:
        for frm, to in (("solomon", "marcus"), ("marcus", "solomon"), ("dyson", "midas"),
                        ("midas", "orion"), ("orion", "scout")):
            body = ta.task_body({"agentId": to, "title": "x", "business": "daycare"}, frm)
            assert "business" not in body and frm.title() in body["note"], body
            res = agents_hub.send_task(body["agentId"], body["title"], body["note"], business=body.get("business"))
            assert res.get("ok") and res["task"]["agentId"] == agents_hub.main_agent(to), (frm, to, res)
        assert agents_hub.send_task("dyson", "x", business="daycare").get("wrongWorkspace"), "UI placement unchanged"
    finally:
        agents_hub.TASKS = saved


def test_connector_passes_workspace_and_keeps_refusals_out_of_history():
    src = (HERE / "connector.py").read_text()
    assert 'scout=SCOUT, business=body.get("business"))' in src
    assert 'not result.get("refused")' in src
    assert 'body.get("note", ""), business=body.get("business"))' in src, "hub task passes the workspace"


def test_ui_surfaces_scoped():
    hub = (HERE / "agents_hub.jsx").read_text()
    assert "business: biz }" in hub, "hub chat/tasks must send the workspace"
    assert 'wsId === "dropship" ? "dropship"' in hub, "dropship must not fall back to the wholesale roster"
    mob = (HERE / "mobile" / "m_agents.jsx").read_text()
    assert re.search(r"return b === business;", mob), "business portal crews: own agents only (no Orion)"
    assert '"cross" || b === "system"' not in mob
    app = (HERE / "app.jsx").read_text()
    for ws in ("rei", "agency", "daycare", "dropship"):
        assert f'<window.BrainPage ws="{ws}" />' in app, ws
    brain = (HERE / "brain.jsx").read_text()
    assert 'brainWs === "rei" && <LearnPanel' in brain, "Marcus's voice learning card is REI-only"
    assert 'daycare: "Skills/solomon-playbook.md"' in brain


def test_office_floor_per_workspace():
    import agent_office as ao
    ao.AUTO_CHECKIN = False
    want = {"rei": ["marcus"], "wholesale": ["marcus"], "agency": ["dyson"],
            "daycare": ["solomon"], "dropship": ["midas"]}
    for ws, ids in want.items():
        st = ao.state(ws)
        got = [a["id"] for d in st["departments"] for a in d["agents"]]
        assert got == ids, (ws, got)
        assert st["director"]["id"] == "orion", ws          # Orion on every floor
        assert all(m.get("from") in set(ids) | {"orion", "operator", "all"} for m in st["messages"])
    every = [a["id"] for d in ao.state()["departments"] for a in d["agents"]]
    assert "marcus" in every and "dyson" in every and "solomon" in every, every   # no param = all active


def test_office_refuses_other_business_and_scopes_orion():
    import agent_office as ao
    ao.AUTO_CHECKIN = False
    called = []
    fn = lambda a, m: called.append((a, m)) or {"reply": "ok"}   # noqa: E731
    r = ao.chat("dyson", "best daycare ad?", fn, business="daycare")
    assert r["refused"] and "Agency floor" in r["reply"] and not called, r
    assert ao.chat("eco", "hi", fn, business="rei")["refused"]                   # lane -> Dyson
    assert ao.chat("solomon", "hi", fn, business="daycare") == {"reply": "ok"}
    assert ao.chat("orion", "hi", fn, business="agency") == {"reply": "ok"}       # Orion on every floor
    jobs_before = len(ao._JOBS)
    d = ao.dispatch("marcus", "x", chat_fn=fn, business="daycare")
    assert d.get("wrongWorkspace") and len(ao._JOBS) == jobs_before, d
    assert ao.dispatch("solomon", "y", chat_fn=fn, directed_by="orion",
                       business="agency").get("wrongWorkspace")
    assert ao.checkin("operator", only="dyson", business="daycare").get("wrongWorkspace")
    rec = ao.checkin("operator", business="daycare")
    assert [x["agentId"] for x in rec["reviews"]] == ["solomon"] and rec["dept"] == "daycare", rec
    assert ao.latest_checkin("daycare")["id"] == rec["id"]
    assert (ao.latest_checkin("agency") or {}).get("id") != rec["id"], "a daycare round never shows on the agency floor"
    assert all(c["dept"] == "daycare" for c in ao.checkins(business="daycare")["checkins"])
    seen = {}

    def planner(agent, prompt):
        seen["prompt"] = prompt
        return {"reply": json.dumps({"summary": "s", "assignments": [{"agentId": "marcus", "title": "t"}]})}
    import json
    assert ao.plan("rank leads", planner, business="daycare").get("error"), "Orion can't assign off-floor"
    assert "Only use active ids: solomon." in seen["prompt"], seen["prompt"][:400]


def test_office_ui_passes_workspace():
    app = (HERE / "app.jsx").read_text()
    for ws in ("rei", "agency", "daycare", "dropship"):
        assert f'<window.AgentOfficePage ws="{ws}" />' in app, ws
    office = (HERE / "agent_office.jsx").read_text()
    assert '"/api/office/state" + aoQs' in office and "business: ws" in office
    orion = (HERE / "orion_office.jsx").read_text()
    assert "business: floorBiz" in orion
    src = (HERE / "connector.py").read_text()
    assert "floor=_floor" in src and "business=_floor" in src


def main():
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print("FAIL", name, "->", repr(e))
    print("placement:", "FAILED" if failed else "all OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
