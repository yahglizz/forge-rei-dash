"""Solomon · Orchestrator — the board's wake-up timer (solomon_orchestrator). Run: python3 test_solomon_orchestrator.py
No network: rounds use fixture reads, Telegram is a fake, Claude is booby-trapped; state in temp files."""
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TMP = Path(tempfile.mkdtemp(prefix="orch-test-"))
os.environ["FORGE_DAYCARE_BOARD"] = str(TMP / "board.json")
os.environ.pop("FORGE_SOLOMON_ORCH", None)
os.environ.pop("FORGE_SOLOMON_ORCH_EVERY_MIN", None)

import cost_tracker  # noqa: E402
import daycare_watches  # noqa: E402
import forge_heartbeat  # noqa: E402
import forge_ops  # noqa: E402
import review_agent  # noqa: E402
import solomon_orchestrator as so  # noqa: E402
import telegram_io  # noqa: E402
import test_daycare_watches as fx  # noqa: E402  (the watches' fixtures)

so.STATE = TMP / "orch.json"
forge_heartbeat.STATE = TMP / "heartbeats.json"
ET = ZoneInfo("America/New_York")
HERE = Path(__file__).resolve().parent


def at(h, m=0, d=19):
    return datetime(2026, 10, d, h, m, tzinfo=ET).timestamp()


class Env:
    """Patch the skip switches + capture sends for one test."""
    def __init__(self, paused=False, ceiling=False, blocked=False):
        self.sent, self.hq, self.rounds = [], [], 0
        self.saved = (forge_ops.paused, cost_tracker.over_ceiling, review_agent.ai_blocked)
        forge_ops.paused = lambda: paused
        cost_tracker.over_ceiling = lambda agent: ceiling and agent == "solomon"
        review_agent.ai_blocked = lambda *a, **k: blocked
        so.STATE.unlink(missing_ok=True)

    def round(self, res):
        def fn():
            self.rounds += 1
            return res
        return fn

    def send(self, text):
        self.sent.append(text)
        return {"ok": True}

    def note(self, text):
        self.hq.append(text)
        return {"ok": True}

    def close(self):
        forge_ops.paused, cost_tracker.over_ceiling, review_agent.ai_blocked = self.saved


R_NEW = {"ok": True, "new": ["a"], "closed": [], "open": 1, "urgent": [], "newItems": [
    {"id": "a", "domain": "billing", "title": "Overdue: INV-1", "severity": "high", "center": "921 N 18th St"}],
    "domains": [], "line": "1 open"}
R_QUIET = {"ok": True, "new": [], "closed": [], "open": 1, "urgent": [], "domains": [], "line": "1 open"}
R_URG = {"ok": True, "new": [], "closed": [], "open": 1, "domains": [], "line": "1 open",
         "urgent": [{"id": "u1", "domain": "roster", "title": "Toddlers over capacity", "severity": "urgent", "center": "x"}]}


def test_off_by_default_and_wired_box_only():
    assert so.enabled() is False, "FORGE_SOLOMON_ORCH defaults OFF"
    os.environ["FORGE_SOLOMON_ORCH"] = "1"
    try:
        assert so.enabled() is True
    finally:
        os.environ.pop("FORGE_SOLOMON_ORCH")
    src = (HERE / "connector.py").read_text()
    loops = src.index("    if LOOPS_ENABLED:\n        # Scout")
    on = src.index("if solomon_orchestrator.enabled():")
    assert loops < on, "the thread starts only inside the box-only LOOPS_ENABLED block"
    block = src[on:on + 700]
    assert 'name="solomon_orchestrator"' in block and 'forge_heartbeat.retire("solomon_orchestrator")' in block, block
    assert cost_tracker.THREAD_ALIAS["solomon_orchestrator"] == "solomon"
    who = []
    t = threading.Thread(target=lambda: who.append(cost_tracker._who()), name="solomon_orchestrator")
    t.start(), t.join()
    assert who == ["solomon"], "a round on the timer thread bills to Solomon"


def test_registry_lists_the_heartbeat_only_when_on():
    code = "import agents_hub; print(agents_hub._BY_ID['solomon']['hb'])"
    env = {**os.environ, "FORGE_UNDER_TEST": "1"}
    off = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=env, capture_output=True, text=True)
    on = subprocess.run([sys.executable, "-c", code], cwd=HERE, env={**env, "FORGE_SOLOMON_ORCH": "1"},
                        capture_output=True, text=True)
    assert "solomon_orchestrator" not in off.stdout and "daycare_replies" in off.stdout, off.stdout + off.stderr
    assert "solomon_orchestrator" in on.stdout, on.stdout + on.stderr


def test_schedule():
    assert not so.due(at(6, 59), None) and so.due(at(7, 0), None)
    assert not so.due(at(8, 30), at(7, 0)) and so.due(at(9, 0), at(7, 0))
    assert so.due(at(18, 59), at(16, 0)) and not so.due(at(19, 30), at(16, 0)), "business hours end at 19:00"
    assert so.due(at(20, 5), at(17, 0)) and not so.due(at(20, 40), at(20, 5)), "one 20:00 round"
    assert not so.due(at(23, 0), None) and not so.due(at(3, 0), None), "never overnight"
    os.environ["FORGE_SOLOMON_ORCH_EVERY_MIN"] = "60"
    try:
        assert so.due(at(8, 0), at(7, 0)) and so.every_min() == 60
    finally:
        os.environ.pop("FORGE_SOLOMON_ORCH_EVERY_MIN")


def test_skips():
    for kw, why in (({"paused": True}, "clocked out"), ({"ceiling": True}, "cost ceiling"),
                    ({"blocked": True}, "AI circuit open")):
        e = Env(**kw)
        try:
            out = so.tick(at(9), round_fn=e.round(R_NEW), send=e.send, hq=e.note)
            assert out == {"skipped": why} and e.rounds == 0 and e.sent == [], (kw, out)
            assert so._load()["lastSkip"]["why"] == why and "lastRoundAt" not in so._load()
        finally:
            e.close()
    e = Env(ceiling=True)
    try:
        so.tick(at(9), round_fn=e.round(R_NEW), hq=e.note)
        so.tick(at(9, 5), round_fn=e.round(R_NEW), hq=e.note)
        assert len(e.hq) == 1 and "ceiling" in e.hq[0], "one HQ note per ET day"
        so.tick(at(9, 0, d=20), round_fn=e.round(R_NEW), hq=e.note)
        assert len(e.hq) == 2, "a new ET day gets a new note"
    finally:
        e.close()
    e = Env()
    try:
        assert so.tick(at(23), round_fn=e.round(R_NEW), send=e.send) == {"skipped": "not due"} and e.rounds == 0
    finally:
        e.close()


def test_no_overlap():
    e = Env()
    try:
        assert daycare_watches._RUN.acquire(blocking=False)
        try:
            out = so.tick(at(9), round_fn=lambda: daycare_watches.run_round(get=fx.make_get(), now=fx.NOW), send=e.send)
        finally:
            daycare_watches._RUN.release()
        assert out == {"ok": True, "skipped": "a round is already running"} and e.sent == [], out
        assert "lastRoundAt" not in so._load(), "a skipped round is not a round"
    finally:
        e.close()


def test_digest_only_when_new_or_newly_urgent():
    e = Env()
    try:
        so.tick(at(9), round_fn=e.round(R_QUIET), send=e.send)
        assert e.sent == [] and so._load()["lastRoundAt"] == at(9), "no empty pings"
        so.tick(at(11), round_fn=e.round(R_NEW), send=e.send)
        assert len(e.sent) == 1 and "Overdue: INV-1" in e.sent[0] and len(e.sent[0].splitlines()) <= 12
        so.tick(at(13), round_fn=e.round(R_URG), send=e.send)
        assert len(e.sent) == 2 and "Toddlers over capacity" in e.sent[1]
        so.tick(at(15), round_fn=e.round(R_URG), send=e.send)
        assert len(e.sent) == 2, "the same urgent item is not re-pinged every round"
        assert so.status()["lastDigestAt"] == int(at(13) * 1000) and so.status()["enabled"] is False
    finally:
        e.close()
    e = Env()
    saved = telegram_io.send_biz
    to = []
    telegram_io.send_biz = lambda biz, text, **k: to.append(biz) or {"ok": True}
    try:
        so.tick(at(9), round_fn=e.round(R_NEW))
    finally:
        telegram_io.send_biz = saved
        e.close()
    assert to == ["daycare"], "the digest goes to the DAYCARE chat"


def test_zero_claude_real_round():
    e = Env()
    trap = []
    saved = (review_agent._claude, review_agent.post_messages)
    review_agent._claude = review_agent.post_messages = lambda *a, **k: trap.append(a) or 1 / 0
    try:
        fx.daycare_board.STATE.unlink(missing_ok=True)
        out = so.tick(at(9), round_fn=lambda: daycare_watches.run_round(get=fx.make_get(), now=fx.NOW), send=e.send)
    finally:
        review_agent._claude, review_agent.post_messages = saved
        e.close()
    assert trap == [] and out["ok"] and out["open"] > 0 and len(e.sent) == 1, (trap, out.get("line"))


def test_heartbeat_retire():
    forge_heartbeat.beat(so.LOOP, so.POLL_SEC, so.LABEL)
    assert any(l["loop"] == so.LOOP and l["label"] == "Solomon · Orchestrator" for l in forge_heartbeat.snapshot())
    forge_heartbeat.retire(so.LOOP)
    assert not any(l["loop"] == so.LOOP for l in forge_heartbeat.snapshot())
    doc = so.__doc__
    assert "ZERO-CLAUDE DETECTION ONLY" in doc and "NO LLM" in doc and "NOTHING outward" in doc


def main():
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                import traceback
                print("FAIL", name, "->", repr(e))
                traceback.print_exc()
    print("solomon_orchestrator:", "FAILED" if failed else "all OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
