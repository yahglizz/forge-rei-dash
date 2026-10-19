"""Per-agent daily $ ceiling (cost_tracker.spent_today / over_ceiling — for the later unattended
orchestrator round; nothing loops on it yet). Run: python3 test_cost_ceiling.py (temp state; exit 1 on failure)."""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("FORGE_ACTION_LOG", str(Path(tempfile.mkdtemp()) / "actions.jsonl"))
import cost_tracker as ct  # noqa: E402

ct.STATE = Path(tempfile.mkdtemp()) / "cost_tracker.json"
MODEL = "claude-sonnet-5-5"          # $2 in / $10 out per M tokens


def on_thread(name, fn):
    t = threading.Thread(target=fn, name=name)
    t.start()
    t.join()


def main():
    os.environ.pop("FORGE_AGENT_MAX_USD", None)
    assert ct.spent_today("solomon") == 0.0 and not ct.over_ceiling("solomon"), "empty state = $0"
    on_thread("daycare_replies", lambda: ct.record_anthropic(MODEL, 1_000_000, 0))     # lane bills to solomon
    on_thread("solomon", lambda: ct.record_anthropic(MODEL, 0, 50_000))               # +$0.50
    on_thread("scout", lambda: ct.record_anthropic(MODEL, 500_000, 0))                # someone else's $1
    assert ct.spent_today("solomon") == 2.5, ct.spent_today("solomon")
    assert ct.spent_today("daycare_replies") == 2.5, "a lane name resolves through THREAD_ALIAS"
    assert ct.spent_today("scout") == 1.0 and ct.spent_today("marcus") == 0.0
    assert ct.spent_today("orion") == 0.0, "orion → the brief bucket (alias), nothing there yet"
    assert not ct.over_ceiling("solomon"), "$2.50 < $3 default"
    on_thread("solomon", lambda: ct.record_anthropic(MODEL, 0, 50_000))               # → $3.00
    assert ct.spent_today("solomon") == 3.0 and ct.over_ceiling("solomon"), "at the ceiling = over"
    d = json.loads(ct.STATE.read_text())                                            # yesterday never counts
    d["days"]["2000-01-01"] = {"byAgent": {"marcus": {"usd": 99.0, "calls": 1}}}
    ct.STATE.write_text(json.dumps(d))
    assert ct.spent_today("marcus") == 0.0 and not ct.over_ceiling("marcus")
    for raw, want in (("10", 10.0), ("0.5", 0.5), ("", 3.0), ("abc", 3.0), ("-4", 0.0)):
        os.environ["FORGE_AGENT_MAX_USD"] = raw
        assert ct.max_usd() == want, (raw, ct.max_usd())
    os.environ["FORGE_AGENT_MAX_USD"] = "10"
    assert not ct.over_ceiling("solomon")
    os.environ.pop("FORGE_AGENT_MAX_USD")
    ct.STATE.write_text("{not json")
    assert ct.spent_today("solomon") == 0.0 and not ct.over_ceiling("solomon"), "corrupt state never raises"
    print("cost_ceiling: all OK")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print("FAIL", repr(e))
        sys.exit(1)
