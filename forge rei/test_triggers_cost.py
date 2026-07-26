"""test_triggers_cost.py — the two bits of new non-trivial logic, checked.

1. The Telegram trigger-word regex: "solomon, ..." must switch agents; "I told marcus
   to call" must NOT (it's plain chat for whoever is already active).
2. Per-agent cost attribution: record_anthropic buckets by thread name, and an
   unnamed/HTTP thread buckets under "operator".

Run directly: python3 test_triggers_cost.py
"""
import threading

import telegram_io
import cost_tracker


def _trigger(text):
    m = telegram_io._AGENT_TRIGGER.match(text)
    if not m:
        return None, text
    return (m.group(1) or m.group(3)).lower(), (m.group(2) or "").strip()


def test_triggers():
    fires = [
        ("solomon, what's the ratio situation", "solomon", "what's the ratio situation"),
        ("midas: which product is winning", "midas", "which product is winning"),
        ("Scout — audit last week", "scout", "audit last week"),
        ("atlas", "atlas", ""),
        ("MARCUS, draft arthur a reply", "marcus", "draft arthur a reply"),
    ]
    for text, agent, rest in fires:
        got_a, got_r = _trigger(text)
        assert got_a == agent, f"{text!r} → {got_a!r}, want {agent!r}"
        assert got_r == rest, f"{text!r} rest → {got_r!r}, want {rest!r}"

    # Must NOT fire: the name is not the first word, or is mid-sentence with no separator.
    for text in ("I told marcus to call her back",
                 "ask solomon about it",
                 "marcus should probably wait",     # first word but no , : — separator
                 "what did eco say"):
        got_a, _ = _trigger(text)
        assert got_a is None, f"{text!r} wrongly switched to {got_a!r}"


def test_cost_attribution():
    seen = {}

    def grab(name):
        seen[name] = cost_tracker._who()

    for name, want in (("scout", "scout"), ("midas", "midas"),
                       ("Thread-7 (process_request)", "operator"),
                       ("MainThread", "operator")):
        th = threading.Thread(target=grab, args=(name,), name=name)
        th.start()
        th.join()
        assert seen[name] == want, f"thread {name!r} → {seen[name]!r}, want {want!r}"

    # Every agent the connector names must be attributable, or its spend silently
    # lands in "operator" and the per-agent breakdown lies.
    for a in ("scout", "marcus", "atlas", "followup", "solomon", "midas", "do_today"):
        assert a in cost_tracker.AGENT_THREADS, f"{a} missing from AGENT_THREADS"


def test_retire_paused_loop():
    """A deliberately-disabled loop must be REMOVED from heartbeats, not left to rot
    red — a red loop trips the health card and the watchdog."""
    import json
    import tempfile
    from pathlib import Path

    import forge_heartbeat as fh
    orig = fh.STATE
    with tempfile.TemporaryDirectory() as td:
        fh.STATE = Path(td) / "heartbeats.json"
        try:
            fh.beat("midas", 900, "Midas director")
            fh.beat("scout", 180, "Scout triage")
            assert {r["loop"] for r in fh.snapshot()} == {"midas", "scout"}

            fh.retire("midas")
            assert {r["loop"] for r in fh.snapshot()} == {"scout"}, "midas still beating"
            assert "midas" not in json.loads(fh.STATE.read_text()), "midas still on disk"

            fh.retire("midas")          # idempotent
            fh.retire("never-existed")  # unknown loop must not raise
            assert {r["loop"] for r in fh.snapshot()} == {"scout"}
        finally:
            fh.STATE = orig


if __name__ == "__main__":
    test_triggers()
    test_cost_attribution()
    test_retire_paused_loop()
    print("triggers + cost attribution + loop retire: OK")
