"""Run with python3 test_model_policy.py — the cost policy (2026-09-30): two model tiers,
scheduled briefs + self-improvement OFF by default, one main agent per business."""
import os
import re
from pathlib import Path

os.environ.pop("FORGE_SELF_IMPROVE", None)
HERE = Path(__file__).parent


def check():
    import review_agent as ra
    assert "haiku" in ra.FAST_MODEL and "sonnet" in ra.SMART_MODEL
    assert ra.MODEL == ra.FAST_MODEL, "an unnamed call site must default to the cheap tier"
    assert ra.DRAFT_MODEL == ra.SMART_MODEL, "inbound seller replies run on the smart tier"
    assert "thinking" not in ra.thinking_params(ra.FAST_MODEL, 500, "low")   # Haiku: no thinking bill
    assert ra.thinking_params(ra.SMART_MODEL, 500, "low")["output_config"] == {"effort": "low"}
    assert ra.self_improve_on() is False
    os.environ["FORGE_SELF_IMPROVE"] = "1"
    assert ra.self_improve_on() is True
    del os.environ["FORGE_SELF_IMPROVE"]

    # Opus / Fable are never a default anywhere in the app.
    for p in HERE.glob("*.py"):
        if p.name.startswith("test_") or p.name == "cost_tracker.py":
            continue
        assert not re.search(r'claude-(opus|fable|mythos)', p.read_text()), p.name

    # Switches are OFF unless the env says otherwise.
    conn = (HERE / "connector.py").read_text()
    assert 'BRIEFS_ON = os.environ.get("FORGE_BRIEFS", "0") != "0"' in conn
    import daycare_director
    assert daycare_director.SCHEDULED_BRIEF is False
    assert 'os.environ.get("FORGE_SKILL_FORGE", "0") == "0"' in (HERE / "skill_forge.py").read_text()
    for f in ("scout_triage", "deal_prep", "marcus_screening", "daycare_director",
              "mission_control_agent", "dropship_director", "agency_agents"):
        assert "self_improve_on()" in (HERE / (f + ".py")).read_text(), f

    # Re-engage bumps run on the smart tier since 2026-10-17 (owner: every agent brain on SMART).
    assert "model=review_agent.SMART_MODEL" in (HERE / "reengage_draft.py").read_text()
    assert "model=review_agent.SMART_MODEL" in (HERE / "reengage_copy.py").read_text()
    assert "import review_agent" in (HERE / "daycare_replies.py").read_text()
    import daycare_replies
    assert daycare_replies.MODEL == ra.SMART_MODEL

    # One main agent per business + the CEO.
    import agents_hub
    assert [a["id"] for a in agents_hub.roster()["agents"]] == ["marcus", "dyson", "solomon", "midas", "orion"]
    print("model policy OK")


# Agent brains moved to SMART 2026-10-17. Every _claude() call in these files must name
# both a model and an effort, so nothing silently falls back to FAST or to Sonnet "high".
AGENT_BRAIN_FILES = (
    "review_agent", "legit_check", "marcus_lead", "daycare_ads_autopilot", "mission_control_agent",
    "daycare_director", "dropship_director", "style_agent", "skill_forge", "scout_triage",
    "deal_prep", "marcus_screening", "agency_agents", "agents_chat", "agent_collab",
)


def check_agent_calls_named():
    import ast
    bad = []
    for f in AGENT_BRAIN_FILES:
        for n in ast.walk(ast.parse((HERE / (f + ".py")).read_text())):
            fn = getattr(n, "func", None)
            if isinstance(n, ast.Call) and getattr(fn, "attr", getattr(fn, "id", None)) == "_claude":
                kw = {k.arg for k in n.keywords}
                if not {"model", "effort"} <= kw:
                    bad.append(f"{f}.py:{n.lineno}")
    assert not bad, "_claude() without model= and effort=: " + ", ".join(bad)
    print("agent calls named OK")


if __name__ == "__main__":
    check()
    check_agent_calls_named()
