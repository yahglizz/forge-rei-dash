"""Live read-only dashboard data in operator agent chat (dash_live).
Run: python3 test_dash_live.py   (no network: Claude + loopback HTTP are faked; exit 1 on failure)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("FORGE_ACTION_LOG", str(Path(tempfile.mkdtemp()) / "actions.jsonl"))
os.environ.pop("FORGE_CHAT_LIVE", None)

import caveman
import dash_live
import review_agent
import telegram_agent as ta

CAT = {"GET": {"/api/daycare/ads/feed", "/api/daycare/children", "/api/daycare/staff",
               "/api/daycare/locations", "/api/agency/clients", "/api/agency/ads",
               "/api/scout/leads", "/api/scout/summary", "/api/system/health",
               "/api/owner-actions", "/api/dropship/overview", "/api/notify/settings"},
       "POST": {"/api/daycare/adgen/cards", "/api/marcus/approve"}}
HTTP, CALLS, PLAIN = [], [], []
SCRIPT = []


def fake_http(method, path, query=None, body=None, timeout=90):
    HTTP.append((method, path, query))
    return {"ok": True, "path": path, "spend7d": 41.5, "api_key": "sk-live-SECRET", "pin": "482913"}


def fake_post(key, payload):
    CALLS.append(payload)
    nxt = SCRIPT.pop(0) if SCRIPT else {"content": [{"type": "text", "text": "done"}]}
    return nxt(payload) if callable(nxt) else nxt


def fake_claude(key, system, user, max_tokens=1200, tools=None, model=None, effort="low"):
    PLAIN.append((system, user, model, effort))
    return "plain reply"


def use(path, tid="t1", name="api_get"):
    return {"content": [{"type": "tool_use", "id": tid, "name": name, "input": {"path": path}}],
            "stop_reason": "tool_use"}


def text(t):
    return {"content": [{"type": "text", "text": t}], "stop_reason": "end_turn"}


def reset():
    HTTP.clear(), CALLS.clear(), PLAIN.clear(), SCRIPT.clear()


def tool_results(payload):
    last = payload["messages"][-1]["content"]
    return " ".join(b["content"] for b in last if b.get("type") == "tool_result")


def test_tool_loop_reads_and_redacts():
    reset()
    SCRIPT.extend([use("/api/daycare/ads/feed"), text("1. Best: Trust ad — $41.50 / 7d, Meta via Pipeboard")])
    out = dash_live.ask("k", "SYS" + caveman.block(), "OPERATOR: best ad?\nYOU:", "solomon")
    assert out.startswith("1. Best"), out
    assert HTTP == [("GET", "/api/daycare/ads/feed", None)], HTTP
    res = tool_results(CALLS[1])
    assert res.startswith("<data>") and "41.5" in res, res
    assert "sk-live-SECRET" not in res and "482913" not in res and "[redacted]" in res, res
    sys_text = CALLS[0]["system"][0]["text"]
    assert CALLS[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sys_text.endswith(caveman.block()), "caveman/ADHD style block must stay LAST"
    assert "LIVE DASHBOARD DATA" in sys_text and "/api/daycare/ads/feed" in sys_text
    assert "Meta via Pipeboard" in sys_text
    assert CALLS[0]["model"] == review_agent.SMART_MODEL
    assert CALLS[0]["output_config"] == {"effort": "low"}


def test_off_scope_points_to_owner():
    reset()
    SCRIPT.extend([use("/api/daycare/ads/feed"), text("That's Solomon's lane — Daycare workspace.")])
    out = dash_live.ask("k", "SYS", "OPERATOR: best daycare ad?\nYOU:", "dyson")
    assert HTTP == [], "an off-scope read must never hit the API"
    res = tool_results(CALLS[1])
    assert "outside agency scope" in res and "Solomon's lane (Daycare workspace)" in res, res
    assert "Solomon" in out
    ok, why = dash_live.read_ok(("wholesale",), "/api/agency/clients")
    assert not ok and "Dyson's lane (Agency workspace)" in why, why
    ok, why = dash_live.read_ok(("daycare",), "/api/scout/leads")
    assert not ok and "Marcus's lane" in why, why
    ok, why = dash_live.read_ok(("daycare",), "/api/system/health")
    assert not ok and "Orion's lane" in why, why
    ok, why = dash_live.read_ok(("hq",) + dash_live.ALL[1:], "/api/notify/settings")
    assert not ok and "off-limits" in why, "deny list holds even for Orion: " + why


def test_no_write_tool():
    for aid in ("marcus", "scout", "atlas", "dyson", "eco", "solomon", "midas", "orion"):
        names = {t["name"] for t in dash_live.tools(aid)}
        assert names <= {"api_get", "route_help", "find_people"}, (aid, names)
        assert "api_post" not in names and "file_task" not in names
    assert {t["name"] for t in dash_live.tools("solomon")} == {"api_get", "route_help", "find_people"}
    assert "find_people" not in {t["name"] for t in dash_live.tools("orion")}
    reset()
    for name in ("api_post", "file_task"):
        r = dash_live.run_tool(name, {"path": "/api/daycare/adgen/cards", "body": {"n": 3}}, "solomon")
        assert "read-only" in r["error"], r
    assert dash_live.run_tool("find_people", {"q": "mia"}, "dyson")["error"].startswith("find_people")
    assert HTTP == [], "no write and no off-business people lookup may reach the API"
    reset()
    SCRIPT.extend([use("/api/daycare/adgen/cards", name="api_post"), text("ok")])
    dash_live.ask("k", "SYS", "make ads", "solomon")
    assert HTTP == [] and "read-only" in tool_results(CALLS[1])
    assert all(t["name"] != "api_post" for t in CALLS[0]["tools"])


def test_orion_reads_every_business():
    reset()
    for p in ("/api/daycare/ads/feed", "/api/agency/clients", "/api/scout/leads",
              "/api/dropship/overview", "/api/system/health", "/api/owner-actions"):
        r = dash_live.run_tool("api_get", {"path": p}, "orion")
        assert "error" not in r, (p, r)
    assert len(HTTP) == 6
    assert dash_live.run_tool("api_get", {"path": "/api/system/health"}, "marcus").get("error")


def test_lanes_resolve_to_owner_scope():
    assert dash_live.businesses("eco") == ("agency",)
    assert dash_live.businesses("scout") == ("wholesale",)
    assert dash_live.businesses("atlas") == ("wholesale",)
    assert dash_live.businesses("orion") == dash_live.ALL
    assert dash_live.businesses("some-retell-agent-id") == ()
    assert dash_live.businesses(None) == ()


def test_tool_turn_cap():
    reset()

    def always_tool(payload):
        if payload.get("tool_choice") == {"type": "none"}:
            return text("answer from what I read")
        return use("/api/scout/leads", tid=f"t{len(CALLS)}")
    SCRIPT.extend([always_tool] * 10)
    out = dash_live.ask("k", "SYS", "q", "marcus")
    assert len(CALLS) == dash_live.MAX_TOOL_TURNS + 1 == 5, len(CALLS)
    assert len(HTTP) == dash_live.MAX_TOOL_TURNS, len(HTTP)
    assert CALLS[-1]["tool_choice"] == {"type": "none"}
    assert all("tool_choice" not in c for c in CALLS[:-1])
    assert out == "answer from what I read", out


def test_fallbacks_are_plain():
    reset()
    os.environ["FORGE_CHAT_LIVE"] = "0"
    try:
        assert dash_live.ask("k", "SYS", "q", "solomon", max_tokens=700) == "plain reply"
    finally:
        del os.environ["FORGE_CHAT_LIVE"]
    assert CALLS == [] and PLAIN[0][2] == review_agent.SMART_MODEL and PLAIN[0][3] == "low"
    reset()
    h = ta._H.pop("handler")
    try:
        assert dash_live.ask("k", "SYS", "q", "solomon") == "plain reply", "unregistered -> plain"
    finally:
        ta._H["handler"] = h
    assert dash_live.ask("k", "SYS", "q", "retell-123") == "plain reply", "no business -> plain"
    assert dash_live.ask("k", "SYS", "q", None) == "plain reply", "teammate consult -> plain"
    assert CALLS == [] and len(PLAIN) == 3


def test_seams_wired():
    here = Path(__file__).parent
    for f in ("agents_hub.py", "agency_agents.py", "agents_chat.py", "marcus_chat.py"):
        assert "dash_live.ask(" in (here / f).read_text(), f
    draft = (here / "marcus_engine.py").read_text()
    assert "dash_live" not in draft and "caveman" not in draft, "seller SMS drafts stay tool- and style-free"


def test_caveman_adhd_switches():
    b = caveman.block()
    assert "ANSWER STYLE" in b and "ADHD" in b and "ONE concrete next action" in b
    assert "Max 5 items" in b and "Unknowns" in b and "explain" in b
    os.environ["FORGE_ADHD"] = "0"
    try:
        b2 = caveman.block()
        assert "ANSWER STYLE" in b2 and "ADHD" not in b2
    finally:
        del os.environ["FORGE_ADHD"]
    os.environ["FORGE_CAVEMAN"] = "0"
    try:
        assert caveman.block() == ""
    finally:
        del os.environ["FORGE_CAVEMAN"]
    here = Path(__file__).parent
    assert (here / "vendor" / "i-have-adhd" / "LICENSE").read_text().startswith("MIT License")
    assert "i-have-adhd" in (here / "vendor" / "i-have-adhd" / "SKILL.md").read_text()


def main():
    saved = (ta.catalog, ta._http, ta._H.get("handler"), review_agent.post_messages, review_agent._claude)
    ta.catalog = lambda: CAT
    ta._http = fake_http
    ta._H["handler"] = object()
    review_agent.post_messages = fake_post
    review_agent._claude = fake_claude
    failed = 0
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and callable(fn):
                try:
                    fn()
                    print("ok  ", name)
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print("FAIL", name, "->", repr(e))
    finally:
        ta.catalog, ta._http = saved[0], saved[1]
        if saved[2] is None:
            ta._H.pop("handler", None)
        else:
            ta._H["handler"] = saved[2]
        review_agent.post_messages, review_agent._claude = saved[3], saved[4]
    print("dash_live:", "FAILED" if failed else "all OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
