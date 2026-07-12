import tempfile
import unittest
from pathlib import Path

import ace
import conversation_engine


class FakeMarcus:
    def __init__(self):
        self.calls = []

    def make_proposal_for(self, conv_id, contact_id=None, hint=None, seller_said=None):
        self.calls.append({"conv": conv_id, "contact": contact_id, "hint": hint})
        return {"ok": True, "conversationId": conv_id}


class FakeSendingMarcus(FakeMarcus):
    """P3 fake: drafting creates a pending proposal; approve records what was sent."""

    def __init__(self, approve_ok=True):
        super().__init__()
        self.proposals = {}
        self.approved = []
        self.approve_ok = approve_ok
        self._n = 0

    def make_proposal_for(self, conv_id, contact_id=None, hint=None, seller_said=None):
        super().make_proposal_for(conv_id, contact_id=contact_id, hint=hint,
                                  seller_said=seller_said)
        self._n += 1
        pid = f"p_{conv_id}_{self._n}"
        self.proposals[pid] = {"id": pid, "conversationId": conv_id,
                               "contactId": contact_id, "status": "pending",
                               "suggestedReply": "how soon are you looking to sell",
                               "ts": self._n}
        return {"ok": True, "conversationId": conv_id}

    def approve(self, pid, edited=None):
        p = self.proposals.get(pid)
        if not p:
            return {"error": "not found"}
        self.approved.append({"pid": pid, "autonomous": p.get("autonomous")})
        if not self.approve_ok:
            return {"error": "gate says no", "gate": "send_hours"}
        p["status"] = "sent"
        p["sentReply"] = p["suggestedReply"]
        return {"ok": True}


def rec(state="QUALIFYING", facts=None, replies=0, held=False, name="Lead", contact="c1",
        phone="2675550100"):
    return {"convId": "v1", "contactId": contact, "name": name, "state": state,
            "phone": phone, "replies": replies, "held": held,
            "facts": facts if facts is not None else {
                "condition": True, "timeline": False, "price": False,
                "motivation": True, "occupancy": True}}


REPORT = {"interest": "interested",
          "callPrep": {"questions": ["How soon are you hoping to close?",
                                     "What's the condition like?"]}}


class ConvEngineQuestionTest(unittest.TestCase):
    def setUp(self):
        self.ce = conversation_engine.ConversationEngine()

    def test_picks_top_missing_fact_in_order(self):
        # condition known, timeline missing → timeline is next (before price)
        nq = self.ce.next_question(rec(), REPORT)
        self.assertEqual("timeline", nq["fact"])

    def test_reuses_callprep_question_when_matches(self):
        nq = self.ce.next_question(rec(), REPORT)
        self.assertEqual("callprep", nq["source"])
        self.assertIn("close", nq["question"].lower())

    def test_canned_fallback_is_price_free(self):
        # only price missing → canned price question, no '$'
        facts = {"condition": True, "timeline": True, "occupancy": True,
                 "motivation": True, "price": False}
        nq = self.ce.next_question(rec(facts=facts), {"callPrep": {"questions": []}})
        self.assertEqual("price", nq["fact"])
        self.assertNotIn("$", nq["question"])

    def test_none_when_all_facts_known(self):
        facts = {k: True for k in conversation_engine.TARGET_FACTS}
        self.assertIsNone(self.ce.next_question(rec(facts=facts), REPORT))

    def test_never_returns_dollar_quoting_callprep_line(self):
        rep = {"callPrep": {"questions": ["Could you take $80,000 for it?"]}}
        facts = {"condition": True, "timeline": True, "occupancy": True,
                 "motivation": True, "price": False}
        nq = self.ce.next_question(rec(facts=facts), rep)
        self.assertNotIn("$", nq["question"])          # falls back to canned, not the $ line

    def test_never_returns_numeric_offer_callprep_line(self):
        rep = {"callPrep": {"questions": ["Would you take 80k for it?"]}}
        facts = {"condition": True, "timeline": True, "occupancy": True,
                 "motivation": True, "price": False}
        nq = self.ce.next_question(rec(facts=facts), rep)
        self.assertEqual("canned", nq["source"])
        self.assertNotIn("80k", nq["question"].lower())


class AceDecideTest(unittest.TestCase):
    def setUp(self):
        self._orig_state = ace.STATE
        self._orig_paused = ace.forge_ops.paused
        self._tmp = tempfile.TemporaryDirectory()
        ace.STATE = Path(self._tmp.name) / "ace.json"
        ace.forge_ops.paused = lambda: False
        self.ce = conversation_engine.ConversationEngine()

    def tearDown(self):
        ace.STATE = self._orig_state
        ace.forge_ops.paused = self._orig_paused
        self._tmp.cleanup()

    def test_off_stops(self):
        ace.set_mode("off")
        self.assertEqual("stop", ace.decide(rec(), REPORT, self.ce)["action"])

    def test_clocked_out_stops(self):
        ace.set_mode("shadow")
        ace.forge_ops.paused = lambda: True
        d = ace.decide(rec(), REPORT, self.ce)
        self.assertEqual("stop", d["action"])
        self.assertEqual("clocked out", d["reason"])

    def test_reply_with_next_question(self):
        ace.set_mode("shadow")
        d = ace.decide(rec(), REPORT, self.ce)
        self.assertEqual("reply", d["action"])
        self.assertEqual("timeline", d["fact"])

    def test_escalate_when_all_facts(self):
        ace.set_mode("shadow")
        facts = {k: True for k in conversation_engine.TARGET_FACTS}
        d = ace.decide(rec(facts=facts), REPORT, self.ce)
        self.assertEqual("escalate", d["action"])

    def test_escalate_call_ready(self):
        ace.set_mode("shadow")
        d = ace.decide(rec(state="CALL_READY"), REPORT, self.ce)
        self.assertEqual("escalate", d["action"])

    def test_escalate_max_replies(self):
        ace.set_mode("shadow")
        d = ace.decide(rec(replies=5), REPORT, self.ce)
        self.assertEqual("escalate", d["action"])

    def test_held_stops(self):
        ace.set_mode("shadow")
        d = ace.decide(rec(held=True), REPORT, self.ce)
        self.assertEqual("stop", d["action"])

    def test_terminal_stops(self):
        ace.set_mode("full")
        self.assertEqual("stop", ace.decide(rec(state="HANDED_OFF"), REPORT, self.ce)["action"])
        self.assertEqual("stop", ace.decide(rec(state="DEAD"), REPORT, self.ce)["action"])


class AcePhoneScopedFullTest(unittest.TestCase):
    def setUp(self):
        self.orig_state = ace.STATE
        self.orig_paused = ace.forge_ops.paused
        self.orig_status = ace.test_mode.status
        self.orig_is_test = ace.test_mode.is_test
        self.tmp = tempfile.TemporaryDirectory()
        ace.STATE = Path(self.tmp.name) / "ace.json"
        ace.forge_ops.paused = lambda: False
        ace.test_mode.status = lambda: {"enabled": True, "phones": ["2675550100"]}
        ace.test_mode.is_test = lambda phone: phone == "2675550100"
        self.ce = conversation_engine.ConversationEngine()
        ace.set_mode("full")

    def tearDown(self):
        ace.STATE = self.orig_state
        ace.forge_ops.paused = self.orig_paused
        ace.test_mode.status = self.orig_status
        ace.test_mode.is_test = self.orig_is_test
        self.tmp.cleanup()

    def test_full_allows_whitelisted_phone(self):
        decision = ace.decide(rec(phone="2675550100"), REPORT, self.ce)
        self.assertEqual("reply", decision["action"])

    def test_full_blocks_every_non_whitelisted_contact(self):
        for phone in ("2155550100", "", None):
            decision = ace.decide(rec(phone=phone), REPORT, self.ce)
            self.assertEqual("stop", decision["action"])
            self.assertEqual("test mode: contact is not whitelisted", decision["reason"])

    def test_status_exposes_hard_test_scope(self):
        status = ace.status()
        self.assertTrue(status["testScoped"])
        self.assertEqual(1, status["testPhoneCount"])


class AceConsiderShadowTest(unittest.TestCase):
    def setUp(self):
        self._orig_state = ace.STATE
        self._orig_paused = ace.forge_ops.paused
        self._tmp = tempfile.TemporaryDirectory()
        ace.STATE = Path(self._tmp.name) / "ace.json"
        ace.forge_ops.paused = lambda: False
        self.ce = conversation_engine.ConversationEngine()

    def tearDown(self):
        ace.STATE = self._orig_state
        ace.forge_ops.paused = self._orig_paused
        self._tmp.cleanup()

    def test_off_is_noop_no_proposal(self):
        ace.set_mode("off")
        m = FakeMarcus()
        ace.consider("v1", rec(), REPORT, self.ce, m)
        self.assertEqual([], m.calls)

    def test_shadow_drafts_one_proposal(self):
        ace.set_mode("shadow")
        m = FakeMarcus()
        d = ace.consider("v1", rec(), REPORT, self.ce, m, last_seller_msg="yeah still thinking")
        self.assertEqual("reply", d["action"])
        self.assertEqual(1, len(m.calls))
        self.assertIn("timeline", m.calls[0]["hint"])
        self.assertNotIn("$", m.calls[0]["hint"])

    def test_shadow_escalate_makes_no_proposal(self):
        ace.set_mode("shadow")
        m = FakeMarcus()
        ace.consider("v1", rec(state="CALL_READY"), REPORT, self.ce, m)
        self.assertEqual([], m.calls)


class AceApplyTest(unittest.TestCase):
    """Phase 3: supervised/full auto-send through the gated approve path."""

    def setUp(self):
        self._orig_state = ace.STATE
        self._orig_cr = ace.CALL_READY
        self._orig_paused = ace.forge_ops.paused
        self._tmp = tempfile.TemporaryDirectory()
        ace.STATE = Path(self._tmp.name) / "ace.json"
        ace.CALL_READY = Path(self._tmp.name) / "call_ready.json"
        ace.forge_ops.paused = lambda: False
        self.ce = conversation_engine.ConversationEngine()
        self.ce.note_reply = lambda conv_id: None   # don't touch the real conversations store

    def tearDown(self):
        ace.STATE = self._orig_state
        ace.CALL_READY = self._orig_cr
        ace.forge_ops.paused = self._orig_paused
        self._tmp.cleanup()

    def test_supervised_sends_with_autonomous_true(self):
        ace.set_mode("supervised")
        m = FakeSendingMarcus()
        d = ace.apply("v1", rec(), REPORT, self.ce, m)
        self.assertTrue(d.get("sent"))
        self.assertEqual(1, len(m.approved))
        # LOCKED CONTRACT: a bot send is autonomous=True — full sms_guard stack fires
        self.assertTrue(m.approved[0]["autonomous"])

    def test_full_also_autonomous_true(self):
        ace.set_mode("full")
        m = FakeSendingMarcus()
        ace.apply("v1", rec(), REPORT, self.ce, m)
        self.assertTrue(m.approved[0]["autonomous"])

    def test_supervised_cap_enforced(self):
        ace.set_mode("supervised")
        m = FakeSendingMarcus()
        for i in range(ace.CAP_SUPERVISED):
            d = ace.apply(f"v{i}", rec(), REPORT, self.ce, m)
            self.assertTrue(d.get("sent"))
        d = ace.apply("vover", rec(), REPORT, self.ce, m)
        self.assertNotIn("sent", d)
        self.assertIn("cap", d.get("reason", ""))
        self.assertEqual(ace.CAP_SUPERVISED, len(m.approved))
        self.assertEqual(ace.CAP_SUPERVISED, len(m.calls))   # cap blocks before drafting

    def test_gate_block_does_not_consume_cap(self):
        ace.set_mode("supervised")
        m = FakeSendingMarcus(approve_ok=False)
        d = ace.apply("v1", rec(), REPORT, self.ce, m)
        self.assertEqual("send_hours", d.get("gate"))
        self.assertEqual(0, ace.status()["sentToday"])

    def test_pre_filled_cap_does_not_draft(self):
        ace.set_mode("supervised")
        with ace._LOCK:
            d = ace._load()
            d["sentToday"] = ace.CAP_SUPERVISED
            ace._save(d)
        m = FakeSendingMarcus()
        d = ace.apply("vover", rec(), REPORT, self.ce, m)
        self.assertNotIn("sent", d)
        self.assertIn("cap", d.get("reason", ""))
        self.assertEqual([], m.calls)

    def test_held_thread_never_sends(self):
        ace.set_mode("full")
        m = FakeSendingMarcus()
        d = ace.apply("v1", rec(held=True), REPORT, self.ce, m)
        self.assertEqual("stop", d["action"])
        self.assertEqual([], m.approved)

    def test_escalate_call_ready_builds_queue_entry(self):
        ace.set_mode("supervised")
        m = FakeSendingMarcus()
        d = ace.apply("v1", rec(state="CALL_READY"), REPORT, self.ce, m)
        self.assertEqual("escalate", d["action"])
        self.assertEqual([], m.approved)                  # escalation ≠ send
        lst = ace.call_ready_list()
        self.assertEqual(1, lst["waiting"])
        self.assertEqual("v1", lst["callReady"][0]["convId"])

    def test_day_rollover_resets_counter(self):
        ace.set_mode("full")
        m = FakeSendingMarcus()
        ace.apply("v1", rec(), REPORT, self.ce, m)
        self.assertEqual(1, ace.status()["sentToday"])
        with ace._LOCK:                                    # simulate yesterday
            d = ace._load()
            d["day"] = "2000-01-01"
            ace._save(d)
        self.assertEqual(0, ace.status()["sentToday"])     # _roll resets on read


class AceHoldAckTest(unittest.TestCase):
    """Stop-button + call-ready ack plumbing."""

    def setUp(self):
        self._orig_state = ace.STATE
        self._orig_cr = ace.CALL_READY
        self._tmp = tempfile.TemporaryDirectory()
        ace.STATE = Path(self._tmp.name) / "ace.json"
        ace.CALL_READY = Path(self._tmp.name) / "call_ready.json"

    def tearDown(self):
        ace.STATE = self._orig_state
        ace.CALL_READY = self._orig_cr
        self._tmp.cleanup()

    def test_hold_sets_flag_and_decide_stops(self):
        class FakeConvo:
            def __init__(self):
                self.held = {}

            def set_held(self, conv_id, held=True):
                self.held[conv_id] = held
                return {"convId": conv_id, "held": held}
        ace.set_mode("full")
        ace.forge_ops.paused = lambda: False
        fc = FakeConvo()
        r = ace.hold("v1", fc, reason="operator stop tap")
        self.assertTrue(r["ok"])
        self.assertTrue(fc.held["v1"])
        d = ace.decide(rec(held=True), REPORT, conversation_engine.ConversationEngine())
        self.assertEqual("stop", d["action"])
        self.assertEqual("operator-held", d["reason"])

    def test_ack_marks_handed_off(self):
        class FakeConvo:
            def __init__(self):
                self.states = {}

            def set_state(self, conv_id, state):
                self.states[conv_id] = state
                return {"convId": conv_id, "state": state}
        ace.call_ready_upsert(rec(state="CALL_READY"), REPORT, None)
        fc = FakeConvo()
        r = ace.ack("v1", fc)
        self.assertTrue(r["ok"])
        self.assertEqual("HANDED_OFF", fc.states["v1"])
        self.assertEqual(0, ace.call_ready_list()["waiting"])


class AceKillSwitchInvariantTest(unittest.TestCase):
    """THE invariant: mode=off / clocked-out beats EVERY other trigger — no state,
    no fact-mix, no classification can make ACE act while it's off or paused."""

    def setUp(self):
        self._orig_state = ace.STATE
        self._orig_paused = ace.forge_ops.paused
        self._tmp = tempfile.TemporaryDirectory()
        ace.STATE = Path(self._tmp.name) / "ace.json"
        self.ce = conversation_engine.ConversationEngine()
        self.hot_recs = [
            rec(),                                            # normal reply case
            rec(state="CALL_READY"),                          # escalation case
            rec(replies=99),                                  # max-replies case
            rec(facts={k: True for k in conversation_engine.TARGET_FACTS}),  # all facts
            rec(held=True),                                   # held
        ]

    def tearDown(self):
        ace.STATE = self._orig_state
        ace.forge_ops.paused = self._orig_paused
        self._tmp.cleanup()

    def test_mode_off_beats_everything(self):
        ace.set_mode("off")
        ace.forge_ops.paused = lambda: False
        for r in self.hot_recs:
            for msg in (None, "yes whats your offer", "READY to sell NOW"):
                d = ace.decide(r, REPORT, self.ce, last_seller_msg=msg)
                self.assertEqual("stop", d["action"])
                self.assertEqual("ace off", d["reason"])

    def test_clock_out_beats_everything_in_every_mode(self):
        ace.forge_ops.paused = lambda: True
        for m in ("shadow", "supervised", "full"):
            ace.set_mode(m)
            for r in self.hot_recs:
                d = ace.decide(r, REPORT, self.ce, last_seller_msg="whats your offer")
                self.assertEqual("stop", d["action"])
                self.assertEqual("clocked out", d["reason"])

    def test_apply_and_consider_inert_when_off(self):
        ace.set_mode("off")
        ace.forge_ops.paused = lambda: False
        m = FakeSendingMarcus()
        for r in self.hot_recs:
            ace.consider("v1", r, REPORT, self.ce, m)
            ace.apply("v1", r, REPORT, self.ce, m)
        self.assertEqual([], m.calls)          # no drafts
        self.assertEqual([], m.approved)       # no sends


class AceDigestTest(unittest.TestCase):
    def setUp(self):
        self._orig_state = ace.STATE
        self._orig_cr = ace.CALL_READY
        self._orig_paused = ace.forge_ops.paused
        self._tmp = tempfile.TemporaryDirectory()
        ace.STATE = Path(self._tmp.name) / "ace.json"
        ace.CALL_READY = Path(self._tmp.name) / "call_ready.json"
        ace.forge_ops.paused = lambda: False

    def tearDown(self):
        ace.STATE = self._orig_state
        ace.CALL_READY = self._orig_cr
        ace.forge_ops.paused = self._orig_paused
        self._tmp.cleanup()

    def test_digest_counts_sends_and_blocks(self):
        ace.set_mode("supervised")
        ce = conversation_engine.ConversationEngine()
        ce.note_reply = lambda conv_id: None
        m = FakeSendingMarcus()
        ace.apply("v1", rec(), REPORT, ce, m)              # auto_send
        ace.log_event("blocked", "v2", "outside hours", {"gate": "send_hours"})
        d = ace.digest(days=1)
        self.assertEqual(1, d["summary"]["autoSends"])
        self.assertEqual(1, d["summary"]["blocked"])
        self.assertIn("send_hours", d["blocksByReason"])
        self.assertEqual("supervised", d["mode"])


if __name__ == "__main__":
    unittest.main()
