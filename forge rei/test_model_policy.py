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

    # Automatic re-engage bumps are cheap; the money moment is not.
    assert "model=review_agent.FAST_MODEL" in (HERE / "reengage_draft.py").read_text()
    assert "model=review_agent.FAST_MODEL" in (HERE / "reengage_copy.py").read_text()
    assert "import review_agent" in (HERE / "daycare_replies.py").read_text()
    import daycare_replies
    assert daycare_replies.MODEL == ra.SMART_MODEL

    # One main agent per business + the CEO.
    import agents_hub
    assert [a["id"] for a in agents_hub.roster()["agents"]] == ["marcus", "dyson", "solomon", "midas", "orion"]
    print("model policy OK")


if __name__ == "__main__":
    check()
