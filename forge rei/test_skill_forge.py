import json
import tempfile
import time
import unittest
from pathlib import Path

import skill_forge


def bus_msg(frm, text):
    return {"id": "m1", "ts": int(time.time() * 1000), "from": frm, "to": "all",
            "kind": "status", "text": text, "data": {}, "read": False}


class SkillForgeTest(unittest.TestCase):
    def setUp(self):
        self._orig_state = skill_forge.STATE
        self._orig_covered = skill_forge._already_covered
        self._orig_propose = skill_forge._propose
        self._tmp = tempfile.TemporaryDirectory()
        skill_forge.STATE = Path(self._tmp.name) / "skill_forge.json"
        skill_forge._already_covered = lambda topic: False
        # capture instead of threading + Claude + vault write
        self.proposed = []
        skill_forge._propose = lambda cand: self.proposed.append(cand)

    def tearDown(self):
        skill_forge.STATE = self._orig_state
        skill_forge._already_covered = self._orig_covered
        skill_forge._propose = self._orig_propose
        self._tmp.cleanup()

    def _state(self):
        return json.loads(skill_forge.STATE.read_text())

    def test_signals_accumulate_per_agent(self):
        skill_forge.on_bus_message(bus_msg("scout", "seller ghosting after price talk"))
        skill_forge.on_bus_message(bus_msg("marcus", "seller ghosting after price talk"))
        sig = self._state()["signals"]
        row = sig.get("seller ghosting")
        self.assertIsNotNone(row)
        self.assertEqual(2, len(row["agents"]))

    def test_two_agents_triggers_candidate(self):
        # MIN_AGENTS=2 default: same shingles from two agents → exactly one candidate
        skill_forge.on_bus_message(bus_msg("scout", "vacant probate house pattern"))
        self.assertEqual([], self.proposed)
        skill_forge.on_bus_message(bus_msg("marcus", "vacant probate house pattern"))
        self.assertEqual(1, len(self.proposed))
        self.assertIn(self.proposed[0]["topic"],
                      ("vacant probate", "probate house", "house pattern"))

    def test_one_agent_below_encounter_threshold_no_candidate(self):
        for _ in range(3):   # 3 < MIN_ENCOUNTERS(8), one agent < MIN_AGENTS(2)
            skill_forge.on_bus_message(bus_msg("scout", "tired landlord eviction angle"))
        self.assertEqual([], self.proposed)

    def test_rate_limit_one_proposal_per_interval(self):
        skill_forge.on_bus_message(bus_msg("scout", "cash buyer list building"))
        skill_forge.on_bus_message(bus_msg("marcus", "cash buyer list building"))
        n = len(self.proposed)
        self.assertEqual(1, n)
        # second cross-agent topic inside the interval → suppressed
        skill_forge.on_bus_message(bus_msg("scout", "code violation leads angle"))
        skill_forge.on_bus_message(bus_msg("marcus", "code violation leads angle"))
        self.assertEqual(n, len(self.proposed))

    def test_covered_topic_skipped(self):
        skill_forge._already_covered = lambda topic: True
        skill_forge.on_bus_message(bus_msg("scout", "wholesale double close trick"))
        skill_forge.on_bus_message(bus_msg("marcus", "wholesale double close trick"))
        self.assertEqual([], self.proposed)

    def test_own_messages_ignored(self):
        skill_forge.on_bus_message(bus_msg("skill_forge", "meta pattern noise loop"))
        # ignored before any state write — no file, no signals, no proposals
        self.assertFalse(skill_forge.STATE.exists())
        self.assertEqual([], self.proposed)

    def test_never_raises_on_garbage(self):
        skill_forge.on_bus_message(None)
        skill_forge.on_bus_message("nope")
        skill_forge.on_bus_message({"from": "scout"})   # no text


class ApprovalGateTest(unittest.TestCase):
    """The gate: nothing applied without a tap; approve writes exactly once."""

    def setUp(self):
        self._orig_state = skill_forge.STATE
        self._tmp = tempfile.TemporaryDirectory()
        skill_forge.STATE = Path(self._tmp.name) / "skill_forge.json"
        # seed one pending proposal
        d = {"proposals": {"sf_x_1": {
            "id": "sf_x_1", "status": "pending", "topic": "vacant probate",
            "path": "Skills/proposals/sf_x_1.md", "body": "---\nname: vacant-probate\n---\nX",
            "ts": 1}}}
        skill_forge.STATE.parent.mkdir(parents=True, exist_ok=True)
        skill_forge.STATE.write_text(json.dumps(d))
        # capture vault writes
        self.writes = []
        import brain_io
        self._orig_write = brain_io.write_note
        brain_io.write_note = lambda rel, content, reason="": (
            self.writes.append((rel, reason)) or {"ok": True, "path": rel, "committed": True})

    def tearDown(self):
        import brain_io
        brain_io.write_note = self._orig_write
        skill_forge.STATE = self._orig_state
        self._tmp.cleanup()

    def test_pending_lists_without_writing(self):
        p = skill_forge.pending()
        self.assertEqual(1, len(p["pending"]))
        self.assertEqual([], self.writes)          # reading applies nothing

    def test_dismiss_writes_nothing(self):
        r = skill_forge.dismiss("sf_x_1")
        self.assertTrue(r.get("ok"))
        self.assertEqual([], self.writes)          # no adoption write on dismiss
        self.assertEqual(1, skill_forge.pending()["stats"]["rejected"])

    def test_approve_adopts_into_vault(self):
        r = skill_forge.approve("sf_x_1")
        self.assertTrue(r.get("ok"))
        self.assertEqual(1, len(self.writes))
        rel, reason = self.writes[0]
        self.assertEqual("Skills/vacant-probate.md", rel)
        self.assertIn("ADOPTED", reason)           # its own commit → git-reversible
        # second tap is a no-op
        self.assertIn("error", skill_forge.approve("sf_x_1"))

    def test_approve_write_failure_stays_pending_for_retry(self):
        import brain_io

        def fail_write(rel, content, reason=""):
            raise RuntimeError("vault locked")

        brain_io.write_note = fail_write
        r = skill_forge.approve("sf_x_1")
        self.assertIn("error", r)
        p = skill_forge.pending()
        self.assertEqual(1, len(p["pending"]))
        self.assertEqual("pending", p["pending"][0]["status"])
        self.assertEqual({}, p["stats"])

    def test_unknown_pid_errors(self):
        self.assertIn("error", skill_forge.approve("nope"))
        self.assertIn("error", skill_forge.dismiss("nope"))


if __name__ == "__main__":
    unittest.main()
