import tempfile
import unittest
from pathlib import Path

import ace
import conversation_engine
import cost_tracker
import send_ledger
import sms_guard
import telegram_io


class FakeMarcus:
    def __init__(self):
        self.calls = []

    def make_proposal_for(self, conv_id, contact_id=None, hint=None, seller_said=None,
                          pivot=False):
        self.calls.append({"conv": conv_id, "contact": contact_id, "hint": hint,
                           "pivot": pivot})
        return {"ok": True, "conversationId": conv_id}


class FakeSendingMarcus(FakeMarcus):
    """P3 fake: drafting creates a pending proposal; approve records what was sent."""

    def __init__(self, approve_ok=True, draft=None, drafts=None):
        super().__init__()
        self.proposals = {}
        self.approved = []
        self.dismissed = []
        self.approve_ok = approve_ok
        self.drafts = list(drafts or [draft or "how soon are you looking to sell"])
        self._n = 0

    def make_proposal_for(self, conv_id, contact_id=None, hint=None, seller_said=None,
                          pivot=False):
        super().make_proposal_for(conv_id, contact_id=contact_id, hint=hint,
                                  seller_said=seller_said, pivot=pivot)
        self._n += 1
        pid = f"p_{conv_id}_{self._n}"
        draft = self.drafts[min(self._n - 1, len(self.drafts) - 1)]
        self.proposals[pid] = {"id": pid, "conversationId": conv_id,
                               "contactId": contact_id, "status": "pending",
                               "suggestedReply": draft,
                               "pivot": bool(pivot),
                               "ts": self._n}
        return {"ok": True, "conversationId": conv_id, "proposalId": pid}

    def approve(self, pid, edited=None):
        p = self.proposals.get(pid)
        if not p:
            return {"error": "not found"}
        self.approved.append({"pid": pid, "autonomous": p.get("autonomous"),
                              "edited": edited, "acePivot": p.get("acePivot")})
        if not self.approve_ok:
            return {"error": "gate says no", "gate": "send_hours"}
        p["status"] = "sent"
        p["sentReply"] = edited or p["suggestedReply"]
        return {"ok": True}

    def dismiss(self, pid):
        p = self.proposals.pop(pid, None)
        if not p:
            return {"error": "not found"}
        p["status"] = "dismissed"
        self.dismissed.append(pid)
        return {"ok": True}


class GuardedFakeMarcus(FakeSendingMarcus):
    """Marcus-shaped test hook: only the external GHL POST is simulated."""

    def __init__(self):
        super().__init__()
        self.outbound = []

    def approve(self, pid, edited=None):
        p = self.proposals.get(pid)
        if not p:
            return {"error": "proposal not found or already handled"}
        message = edited or p["suggestedReply"]
        gate = sms_guard.guard(
            p.get("contactId"),
            message,
            conv_id=p.get("conversationId"),
            name="Ledger Lead",
            last_seller_message="the kitchen needs some work",
            kind="marcus_approve",
            autonomous=bool(p.get("autonomous")),
        )
        self.approved.append({
            "pid": pid,
            "autonomous": p.get("autonomous"),
            "edited": edited,
            "gate": gate.get("gate"),
        })
        if not gate.get("ok"):
            return gate

        self.outbound.append({
            "conversationId": p["conversationId"],
            "contactId": p["contactId"],
            "message": message,
        })
        p["status"] = "sent"
        p["sentReply"] = message
        sms_guard.record_success(
            reservation=gate.get("reservation"),
            conv_id=p["conversationId"],
            contact_id=p["contactId"],
            message=message,
            kind="marcus_approve",
        )
        return {"ok": True}


def rec(state="QUALIFYING", facts=None, replies=0, held=False, name="Lead", contact="c1",
        phone="2675550100", pivot_at=None, conv="v1"):
    r = {"convId": conv, "contactId": contact, "name": name, "state": state,
         "phone": phone, "replies": replies, "held": held,
         "facts": facts if facts is not None else {
             "condition": True, "timeline": False, "price": False,
             "motivation": True, "occupancy": True}}
    if pivot_at:
        r["callPivotAt"] = pivot_at
    return r


ALL_FACTS = {"condition": True, "timeline": True, "price": True,
             "motivation": True, "occupancy": True}


def quiet_convo(ce):
    """Stop a ConversationEngine from touching the real marcus_state store in tests."""
    ce.note_reply = lambda conv_id: None
    ce.note_call_pivot = lambda conv_id, reason="": 1
    ce.set_state = lambda conv_id, state: None
    return ce


REPORT = {"interest": "interested",
          "callPrep": {"questions": ["How soon are you hoping to close?",
                                     "What's the condition like?"]}}


class AceSendLedgerIntegrationTest(unittest.TestCase):
    """Two real ACE attempts share the real temporary send-ledger window."""

    def setUp(self):
        self._orig = {
            "ace_state": ace.STATE,
            "call_ready": ace.CALL_READY,
            "conversation_state": conversation_engine.STATE,
            "guard_state": sms_guard.STATE,
            "ledger_state": send_ledger.STATE,
            "cost_state": cost_tracker.STATE,
            "paused": ace.forge_ops.paused,
            "test_status": ace.test_mode.status,
            "within_hours": sms_guard._within_hours,
            "verdict": sms_guard.legit_check.verdict,
            "telegram_send": telegram_io.send,
        }
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        ace.STATE = root / "ace.json"
        ace.CALL_READY = root / "call_ready.json"
        conversation_engine.STATE = root / "conversations.json"
        sms_guard.STATE = root / "sms_guard.json"
        send_ledger.STATE = root / "send_ledger.json"
        cost_tracker.STATE = root / "cost_tracker.json"
        ace.forge_ops.paused = lambda: False
        ace.test_mode.status = lambda: {"enabled": False}
        sms_guard._within_hours = lambda: True
        sms_guard.legit_check.verdict = lambda scout, conv_id, name="": {
            "legit": True,
            "urgency": "high",
            "reason": "integration fixture",
        }
        telegram_io.send = lambda text, buttons=None, dedupe_key=None: {"ok": True}
        ace._save({
            "mode": "full",
            "day": ace._today_key(),
            "sentToday": 0,
            "log": [],
        })
        self.convo = conversation_engine.ConversationEngine()
        self.conv_id = "conv-ledger-integration"
        self.thread = rec(conv=self.conv_id, contact="contact-ledger")
        self.convo.update(
            self.conv_id,
            contact_id=self.thread["contactId"],
            name=self.thread["name"],
            phone=self.thread["phone"],
            report=REPORT,
        )

    def tearDown(self):
        ace.STATE = self._orig["ace_state"]
        ace.CALL_READY = self._orig["call_ready"]
        conversation_engine.STATE = self._orig["conversation_state"]
        sms_guard.STATE = self._orig["guard_state"]
        send_ledger.STATE = self._orig["ledger_state"]
        cost_tracker.STATE = self._orig["cost_state"]
        ace.forge_ops.paused = self._orig["paused"]
        ace.test_mode.status = self._orig["test_status"]
        sms_guard._within_hours = self._orig["within_hours"]
        sms_guard.legit_check.verdict = self._orig["verdict"]
        telegram_io.send = self._orig["telegram_send"]
        self._tmp.cleanup()

    def test_second_ace_attempt_is_blocked_by_real_send_ledger_and_refunds_cap(self):
        marcus = GuardedFakeMarcus()

        first = ace.apply(
            self.conv_id, self.thread, REPORT, self.convo, marcus,
            last_seller_msg="the kitchen needs some work",
        )
        second = ace.apply(
            self.conv_id, self.thread, REPORT, self.convo, marcus,
            last_seller_msg="the kitchen needs some work",
        )

        self.assertTrue(first.get("sent"), first)
        self.assertEqual("send_ledger", second.get("gate"), second)
        self.assertNotIn("sent", second)
        self.assertEqual(1, len(marcus.outbound))
        self.assertEqual(2, len(marcus.approved))
        self.assertGreater(send_ledger.last_touch_at(self.conv_id), 0)
        self.assertEqual(1, ace.status()["sentToday"])
        self.assertEqual(1, self.convo.get(self.conv_id)["replies"])
        self.assertEqual(1, sms_guard.status()["sent"])


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

    # The three escalation triggers below now return action "pivot" — the thread still gets
    # handed to the operator (d["escalate"] is True and apply() builds the call card), but
    # the FIRST one on a thread also earns a single call-pivot text instead of silence.
    # Once pivoted they escalate silently again; see AcePivotDecideTest.
    def test_escalate_when_all_facts(self):
        ace.set_mode("shadow")
        facts = {k: True for k in conversation_engine.TARGET_FACTS}
        d = ace.decide(rec(facts=facts), REPORT, self.ce)
        self.assertEqual("pivot", d["action"])
        self.assertTrue(d["escalate"])
        self.assertEqual("escalate", ace.decide(rec(facts=facts, pivot_at=1), REPORT,
                                                self.ce)["action"])

    def test_escalate_call_ready(self):
        ace.set_mode("shadow")
        d = ace.decide(rec(state="CALL_READY"), REPORT, self.ce)
        self.assertEqual("pivot", d["action"])
        self.assertTrue(d["escalate"])
        self.assertEqual("escalate", ace.decide(rec(state="CALL_READY", pivot_at=1), REPORT,
                                                self.ce)["action"])

    def test_escalate_max_replies(self):
        ace.set_mode("shadow")
        d = ace.decide(rec(replies=5), REPORT, self.ce)
        self.assertEqual("pivot", d["action"])
        self.assertTrue(d["escalate"])
        self.assertEqual("escalate", ace.decide(rec(replies=5, pivot_at=1), REPORT,
                                                self.ce)["action"])

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
        m = FakeSendingMarcus()
        d = ace.consider("v1", rec(), REPORT, self.ce, m, last_seller_msg="yeah still thinking")
        self.assertEqual("reply", d["action"])
        self.assertEqual(1, len(m.calls))
        self.assertIn("timeline", m.calls[0]["hint"])
        self.assertNotIn("$", m.calls[0]["hint"])

    def test_shadow_hint_names_assigned_fact_and_known_values(self):
        ace.set_mode("shadow")
        facts = {"condition": True, "timeline": False, "price": True,
                 "motivation": True, "occupancy": True}
        report = {
            "conditionNotes": "new roof, kitchen needs work",
            "timeline": "unknown",
            "askingPrice": "$92,000",
            "motivationLevel": "high",
            "propertyStatus": "tenant occupied",
            "callPrep": {"questions": []},
        }
        m = FakeSendingMarcus()

        d = ace.consider("v1", rec(facts=facts), report, self.ce, m)

        self.assertEqual("timeline", d["fact"])
        hint = m.calls[0]["hint"]
        self.assertIn("Assigned fact: timeline", hint)
        self.assertIn("condition: new roof, kitchen needs work", hint)
        self.assertIn("price: $92,000", hint)
        self.assertIn("motivation: high", hint)
        self.assertIn("occupancy: tenant occupied", hint)
        self.assertIn("Do not re-ask", hint)

    def test_shadow_escalate_makes_no_proposal(self):
        # An ALREADY-pivoted thread escalates silently — this is the case that still
        # produces no draft now that a first CALL_READY earns one pivot text.
        ace.set_mode("shadow")
        m = FakeMarcus()
        ace.consider("v1", rec(state="CALL_READY", pivot_at=1), REPORT, self.ce, m)
        self.assertEqual([], m.calls)

    def test_shadow_pivot_drafts_but_never_sends(self):
        ace.set_mode("shadow")
        m = FakeSendingMarcus()
        d = ace.consider("v1", rec(state="CALL_READY"), REPORT, self.ce, m,
                         last_seller_msg="how much will you give me")
        self.assertEqual("pivot", d["action"])
        self.assertEqual(1, len(m.calls))
        self.assertTrue(m.calls[0]["pivot"])
        self.assertEqual([], m.approved)          # shadow never sends

    def test_shadow_pivot_does_not_burn_the_ledger(self):
        # Nothing was sent, so the thread must stay eligible for a real pivot once the
        # operator arms supervised/full. A shadow run that wrote callPivotAt would
        # permanently silence the highest-intent moment in the funnel.
        ace.set_mode("shadow")
        marked = []
        self.ce.note_call_pivot = lambda conv_id, reason="": marked.append(conv_id)
        ace.consider("v1", rec(state="CALL_READY"), REPORT, self.ce, FakeSendingMarcus())
        self.assertEqual([], marked)


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
        self.ce = quiet_convo(conversation_engine.ConversationEngine())

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
        # Qualifying questions may only spend cap - PIVOT_RESERVE; the remaining slot is
        # held for the call-pivot (see test_pivot_reserve_survives_question_exhaustion).
        ace.set_mode("supervised")
        qcap = ace.reply_cap_for("supervised")
        m = FakeSendingMarcus()
        for i in range(qcap):
            d = ace.apply(f"v{i}", rec(), REPORT, self.ce, m)
            self.assertTrue(d.get("sent"))
        d = ace.apply("vover", rec(), REPORT, self.ce, m)
        self.assertNotIn("sent", d)
        self.assertIn("cap", d.get("reason", ""))
        self.assertEqual(qcap, len(m.approved))
        self.assertEqual(qcap, len(m.calls))   # cap blocks before drafting

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
        # Already pivoted → escalation only, still no send. The call card is built either way.
        ace.set_mode("supervised")
        m = FakeSendingMarcus()
        d = ace.apply("v1", rec(state="CALL_READY", pivot_at=1), REPORT, self.ce, m)
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

    def test_wrong_fact_draft_retries_once_then_sends_adherent_question(self):
        ace.set_mode("supervised")
        noted = []
        self.ce.note_reply = lambda conv_id: noted.append(conv_id)
        m = FakeSendingMarcus(drafts=[
            "what kind of shape is the property in",
            "how soon are you looking to sell",
        ])

        d = ace.apply("v1", rec(), REPORT, self.ce, m)

        self.assertTrue(d.get("sent"))
        self.assertEqual(2, len(m.calls))
        self.assertEqual(1, len(m.approved))
        self.assertEqual(1, len(m.dismissed))
        self.assertEqual(["v1"], noted)
        self.assertEqual(1, ace.status()["sentToday"])

    def test_assigned_fact_plus_known_fact_is_rejected_before_retry(self):
        ace.set_mode("supervised")
        noted = []
        self.ce.note_reply = lambda conv_id: noted.append(conv_id)
        m = FakeSendingMarcus(drafts=[
            "how soon are you looking to sell and what shape is it in?",
            "do you need this wrapped up this month?",
        ])

        d = ace.apply("v1", rec(), REPORT, self.ce, m)

        self.assertTrue(d.get("sent"))
        self.assertEqual(2, len(m.calls))
        self.assertEqual(1, len(m.dismissed))
        self.assertEqual(1, len(m.approved))
        self.assertEqual(["v1"], noted)
        self.assertEqual(1, ace.status()["sentToday"])

    def test_two_wrong_fact_drafts_fail_without_send_or_reply_accounting(self):
        ace.set_mode("supervised")
        noted = []
        self.ce.note_reply = lambda conv_id: noted.append(conv_id)
        m = FakeSendingMarcus(drafts=[
            "what kind of shape is the property in",
            "is the property vacant right now",
        ])

        d = ace.apply("v1", rec(), REPORT, self.ce, m)

        self.assertFalse(d.get("sent"))
        self.assertEqual("fact_adherence", d.get("gate"))
        self.assertEqual(2, len(m.calls))
        self.assertEqual([], m.approved)
        self.assertEqual(2, len(m.dismissed))
        self.assertEqual([], noted)
        self.assertEqual(0, ace.status()["sentToday"])

    def test_buyer_directed_timeline_share_retries_then_fails_closed(self):
        ace.set_mode("supervised")
        drafts = (
            "We can describe our timeline on a call. Are you free today?",
            "Can you share your availability? We can share our timeline on a call",
            "Can you share your availability, and we can share our timeline on a call?",
            "Can you share your availability or we can share our timeline on a call?",
        )
        for draft in drafts:
            with self.subTest(draft=draft):
                noted = []
                self.ce.note_reply = lambda conv_id: noted.append(conv_id)
                m = FakeSendingMarcus(drafts=[draft, draft])

                d = ace.apply("v1", rec(), REPORT, self.ce, m)

                self.assertFalse(d.get("sent"))
                self.assertEqual("fact_adherence", d.get("gate"))
                self.assertEqual(2, len(m.calls))
                self.assertEqual([], m.approved)
                self.assertEqual(2, len(m.dismissed))
                self.assertEqual([], noted)
                self.assertEqual(0, ace.status()["sentToday"])


class AceDraftAdherenceTest(unittest.TestCase):
    def test_fact_statements_do_not_satisfy_assigned_fact(self):
        cases = [
            ("condition", "The condition of the property matters."),
            ("timeline", "Your timeline matters."),
            ("price", "I noted the asking price."),
            ("motivation", "Your motivation for selling matters."),
            ("occupancy", "I understand the property is vacant."),
        ]
        for fact, draft in cases:
            with self.subTest(fact=fact, draft=draft):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, fact
                )
                self.assertIsNotNone(reason)

    def test_fact_vocabulary_with_call_question_does_not_satisfy_assigned_fact(self):
        cases = [
            ("condition", "the condition matters, are you free for a quick call today?"),
            ("timeline", "your timeline matters, are you free for a quick call today?"),
            ("price", "your asking price matters, are you free for a quick call today?"),
            ("motivation", "your motivation for selling matters, are you free for a quick call today?"),
            ("occupancy", "occupancy matters, are you free for a quick call today?"),
        ]
        for fact, draft in cases:
            with self.subTest(fact=fact, draft=draft):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, fact
                )
                self.assertIsNotNone(reason)

    def test_buyer_or_owner_directed_share_statements_do_not_satisfy_assigned_fact(self):
        cases = [
            ("condition", "We can share our property condition on a call. Are you free today?"),
            ("timeline", "We can share our timeline on a call. Are you free today?"),
            ("timeline", "We can describe our timeline on a call. Are you free today?"),
            ("price", "We can share our asking price on a call. Are you free today?"),
            ("motivation", "We can share our reason for buying on a call. Are you free today?"),
            ("occupancy", "We can share our occupancy plan on a call. Are you free today?"),
        ]
        for fact, draft in cases:
            with self.subTest(fact=fact, draft=draft):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, fact
                )
                self.assertIsNotNone(reason)

    def test_request_lead_cannot_license_fact_topic_in_next_sentence(self):
        drafts = (
            "Can you share your availability? We can share our timeline on a call",
            "Can you share your availability, and we can share our timeline on a call?",
            "Can you share your availability or we can share our timeline on a call?",
        )
        for draft in drafts:
            with self.subTest(draft=draft):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, "timeline"
                )
                self.assertIsNotNone(reason)

    def test_generic_substring_collisions_do_not_satisfy_assigned_fact(self):
        cases = [
            ("condition", "would next month work for you?"),
            ("timeline", "is the property close by?"),
            ("motivation", "why is the roof damaged?"),
        ]
        for fact, draft in cases:
            with self.subTest(fact=fact, draft=draft):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, fact
                )
                self.assertIsNotNone(reason)

    def test_valid_question_paraphrases_are_admitted_for_every_fact(self):
        cases = [
            ("condition", "what kind of work does the house need?"),
            ("price", "what number did you have in mind?"),
            ("motivation", "why are you considering selling?"),
            ("occupancy", "who currently calls the property home?"),
            ("timeline", "do you need this wrapped up this month?"),
        ]
        for fact, draft in cases:
            with self.subTest(fact=fact, draft=draft):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, fact
                )
                self.assertIsNone(reason)

    def test_valid_request_paraphrases_are_admitted_for_every_fact(self):
        cases = [
            ("condition", "tell me what shape the property is in."),
            ("timeline", "tell me when you would like to close."),
            ("price", "tell me what number you have in mind."),
            ("motivation", "tell me what has you thinking about selling."),
            ("occupancy", "tell me who is living there now."),
        ]
        for fact, draft in cases:
            with self.subTest(fact=fact, draft=draft):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, fact
                )
                self.assertIsNone(reason)

    def test_seller_directed_share_request_is_admitted(self):
        drafts = (
            "can you share your timeline",
            "John, please share your timeline",
            "got it, can you share your timeline",
            "Can you describe your situation and your timeline?",
        )
        for draft in drafts:
            with self.subTest(draft=draft):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, "timeline"
                )
                self.assertIsNone(reason)

    def test_known_fact_acknowledgments_are_not_treated_as_reasks(self):
        cases = [
            (
                {"occupancy"},
                "Since it's vacant, how soon are you looking to sell?",
            ),
            (
                {"condition"},
                "Since the roof is new, do you need this wrapped up this month?",
            ),
        ]
        for known_facts, draft in cases:
            with self.subTest(draft=draft):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, "timeline", known_facts=known_facts
                )
                self.assertIsNone(reason)

    def test_known_fact_questions_are_rejected(self):
        cases = [
            (
                "timeline",
                {"condition"},
                "how soon are you looking to sell and what shape is it in?",
            ),
            (
                "condition",
                {"timeline"},
                "what shape is it in and how soon are you looking to sell?",
            ),
            (
                "timeline",
                {"occupancy"},
                "how soon are you looking to sell and is it vacant?",
            ),
            (
                "condition",
                {"motivation"},
                "what shape is it in and why are you selling?",
            ),
            (
                "timeline",
                {"price"},
                "how soon are you looking to sell and what number do you have in mind?",
            ),
        ]
        for fact, known_facts, draft in cases:
            with self.subTest(fact=fact, known_facts=known_facts):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, fact, known_facts=known_facts
                )
                self.assertIn("already-known", reason or "")

    def test_declarative_known_fact_acknowledgments_are_admitted(self):
        cases = [
            (
                "timeline",
                {"condition"},
                "Since it does need repairs, how soon are you looking to sell?",
            ),
            (
                "condition",
                {"timeline"},
                "Since there is a deadline, what shape is it in?",
            ),
            (
                "condition",
                {"motivation"},
                "Since the sale is motivated by relocation, what shape is it in?",
            ),
            (
                "timeline",
                {"occupancy"},
                "Since the owner occupies it, how soon are you looking to sell?",
            ),
            (
                "timeline",
                {"price"},
                "Since the asking price is set, how soon are you looking to sell?",
            ),
        ]
        for fact, known_facts, draft in cases:
            with self.subTest(fact=fact, known_facts=known_facts):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, fact, known_facts=known_facts
                )
                self.assertIsNone(reason)

    def test_alternate_known_fact_interrogatives_are_rejected(self):
        cases = [
            (
                "timeline",
                {"condition"},
                "how soon are you looking to sell and is it in good shape?",
            ),
            (
                "condition",
                {"timeline"},
                "what shape is it in and is there a deadline?",
            ),
            (
                "condition",
                {"motivation"},
                "what shape is it in and what's motivating the sale?",
            ),
            (
                "timeline",
                {"occupancy"},
                "how soon are you looking to sell and who occupies it?",
            ),
            (
                "timeline",
                {"price"},
                "how soon are you looking to sell and what is the asking price?",
            ),
        ]
        for fact, known_facts, draft in cases:
            with self.subTest(fact=fact, known_facts=known_facts):
                reason = ace._draft_adherence_reason(
                    {"suggestedReply": draft}, fact, known_facts=known_facts
                )
                self.assertIn("already-known", reason or "")


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


class AcePivotDecideTest(unittest.TestCase):
    """Phase 6: the four escalation triggers that used to send NOTHING now earn one
    call-pivot text — and only ever one per thread."""

    def setUp(self):
        self._orig_state = ace.STATE
        self._orig_paused = ace.forge_ops.paused
        self._tmp = tempfile.TemporaryDirectory()
        ace.STATE = Path(self._tmp.name) / "ace.json"
        ace.forge_ops.paused = lambda: False
        ace.set_mode("full")
        self.ce = conversation_engine.ConversationEngine()

    def tearDown(self):
        ace.STATE = self._orig_state
        ace.forge_ops.paused = self._orig_paused
        self._tmp.cleanup()

    def test_price_ask_pivots_instead_of_going_silent(self):
        no_facts = {fact: False for fact in conversation_engine.TARGET_FACTS}
        d = ace.decide(rec(facts=no_facts), REPORT, self.ce,
                       last_seller_msg="how much will you give me")
        self.assertEqual("pivot", d["action"])
        self.assertEqual("classify:PRICE", d["reason"])

    def test_ready_with_fewer_than_three_facts_keeps_qualifying(self):
        two_facts = {"condition": True, "timeline": True, "price": False,
                     "motivation": False, "occupancy": False}
        d = ace.decide(rec(facts=two_facts), REPORT, self.ce,
                       last_seller_msg="yes im interested lets do it")
        self.assertEqual("reply", d["action"])

    def test_ready_at_three_facts_pivots(self):
        three_facts = {"condition": True, "timeline": True, "price": False,
                       "motivation": True, "occupancy": False}
        d = ace.decide(rec(facts=three_facts), REPORT, self.ce,
                       last_seller_msg="yes im interested lets do it")
        self.assertEqual("pivot", d["action"])
        self.assertEqual("classify:READY", d["reason"])

    def test_call_ready_state_pivots(self):
        d = ace.decide(rec(state="CALL_READY"), REPORT, self.ce)
        self.assertEqual("pivot", d["action"])
        self.assertEqual("call-ready", d["reason"])

    def test_max_replies_pivots(self):
        d = ace.decide(rec(replies=ace.MAX_REPLIES), REPORT, self.ce)
        self.assertEqual("pivot", d["action"])
        self.assertEqual("max replies reached", d["reason"])

    def test_all_facts_gathered_pivots(self):
        d = ace.decide(rec(facts=ALL_FACTS), REPORT, self.ce)
        self.assertEqual("pivot", d["action"])

    def test_never_pivots_twice(self):
        d = ace.decide(rec(pivot_at=1), REPORT, self.ce,
                       last_seller_msg="seriously whats your number")
        self.assertEqual("escalate", d["action"])
        self.assertIn("operator", d["reason"])

    def test_pivoted_thread_stops_the_question_lane_too(self):
        # _next_state can regress a thread out of CALL_READY, so the ledger — not the
        # state — is what makes the handoff permanent. Facts are missing here, which would
        # normally produce a qualifying question.
        d = ace.decide(rec(pivot_at=1, facts={"condition": False, "timeline": False,
                                              "price": False, "motivation": False,
                                              "occupancy": False}),
                       REPORT, self.ce)
        self.assertEqual("escalate", d["action"])

    def test_held_beats_pivot(self):
        d = ace.decide(rec(held=True), REPORT, self.ce, last_seller_msg="whats your offer")
        self.assertEqual("stop", d["action"])
        self.assertEqual("operator-held", d["reason"])

    def test_terminal_beats_pivot(self):
        for state in ("HANDED_OFF", "DEAD"):
            d = ace.decide(rec(state=state), REPORT, self.ce,
                           last_seller_msg="whats your offer")
            self.assertEqual("stop", d["action"])

    def test_decide_stays_pure(self):
        r = rec()
        before = dict(r)
        ace.decide(r, REPORT, self.ce, last_seller_msg="how much")
        self.assertEqual(before, r)          # no side effects, no ledger write


class AcePivotApplyTest(unittest.TestCase):
    def setUp(self):
        self._orig_state = ace.STATE
        self._orig_cr = ace.CALL_READY
        self._orig_paused = ace.forge_ops.paused
        self._tmp = tempfile.TemporaryDirectory()
        ace.STATE = Path(self._tmp.name) / "ace.json"
        ace.CALL_READY = Path(self._tmp.name) / "call_ready.json"
        ace.forge_ops.paused = lambda: False
        self.marked = []
        self.ce = quiet_convo(conversation_engine.ConversationEngine())
        self.ce.note_call_pivot = lambda conv_id, reason="": self.marked.append(conv_id) or 1

    def tearDown(self):
        ace.STATE = self._orig_state
        ace.CALL_READY = self._orig_cr
        ace.forge_ops.paused = self._orig_paused
        self._tmp.cleanup()

    def test_pivot_sends_autonomous_and_marks_ledger(self):
        ace.set_mode("full")
        m = FakeSendingMarcus(draft="whats a good time for a quick call today")
        d = ace.apply("v1", rec(state="CALL_READY"), REPORT, self.ce, m)
        self.assertTrue(d.get("pivoted"))
        self.assertTrue(m.calls[0]["pivot"])
        self.assertTrue(m.approved[0]["autonomous"])   # LOCKED: full sms_guard stack
        self.assertEqual(["v1"], self.marked)

    def test_pivot_still_builds_the_call_card(self):
        ace.set_mode("full")
        ace.apply("v1", rec(state="CALL_READY"), REPORT, self.ce, FakeSendingMarcus())
        self.assertEqual(1, ace.call_ready_list()["waiting"])

    def test_leaked_price_is_replaced_by_the_gate_safe_twin(self):
        import marcus_engine
        ace.set_mode("full")
        m = FakeSendingMarcus(draft="i can do 40k for it")
        ace.apply("v1", rec(state="CALL_READY"), REPORT, self.ce, m)
        self.assertEqual(marcus_engine.CALL_PIVOT_FALLBACK, m.approved[0]["edited"])

    def test_offer_word_is_replaced_even_without_digits(self):
        # "offer" alone trips sms_guard._OFFER_RE — the message would never reach the
        # seller, so substitute rather than gamble the highest-intent text in the funnel.
        import marcus_engine
        ace.set_mode("full")
        m = FakeSendingMarcus(draft="let me put together a fair offer for you")
        ace.apply("v1", rec(state="CALL_READY"), REPORT, self.ce, m)
        self.assertEqual(marcus_engine.CALL_PIVOT_FALLBACK, m.approved[0]["edited"])

    def test_gate_block_leaves_thread_eligible_and_refunds_cap(self):
        # A block at 8:59pm must not become silence forever — no ledger write, no cap spend,
        # and the operator still gets the call card.
        ace.set_mode("full")
        m = FakeSendingMarcus(approve_ok=False)
        ace.apply("v1", rec(state="CALL_READY"), REPORT, self.ce, m)
        self.assertEqual([], self.marked)
        self.assertEqual(0, ace.status()["sentToday"])
        self.assertEqual(1, ace.call_ready_list()["waiting"])

    def test_pivot_reserve_survives_question_exhaustion(self):
        # Burn every slot the question lane is allowed, then prove a pivot still sends.
        ace.set_mode("supervised")
        m = FakeSendingMarcus()
        for i in range(ace.reply_cap_for("supervised")):
            ace.apply(f"q{i}", rec(conv=f"q{i}"), REPORT, self.ce, m)
        blocked = ace.apply("qmore", rec(conv="qmore"), REPORT, self.ce, m)
        self.assertNotIn("sent", blocked)
        d = ace.apply("v9", rec(conv="v9", state="CALL_READY"), REPORT, self.ce, m)
        self.assertTrue(d.get("pivoted"))

    def test_pivot_inert_when_off_and_clocked_out(self):
        m = FakeSendingMarcus()
        ace.set_mode("off")
        ace.apply("v1", rec(state="CALL_READY"), REPORT, self.ce, m)
        ace.set_mode("full")
        ace.forge_ops.paused = lambda: True
        ace.apply("v1", rec(state="CALL_READY"), REPORT, self.ce, m)
        self.assertEqual([], m.approved)
        self.assertEqual([], self.marked)


class CallPivotFallbackGateTest(unittest.TestCase):
    """The load-bearing pair. If these ever disagree, autonomous sends go silent."""

    def test_twin_passes_the_central_gate(self):
        import marcus_engine
        import sms_guard
        self.assertFalse(sms_guard._quotes_price_or_offer(marcus_engine.CALL_PIVOT_FALLBACK))

    def test_original_fallback_is_gate_blocked_which_is_why_the_twin_exists(self):
        # _PRICE_FALLBACK says "an accurate offer not a lowball"; sms_guard._OFFER_RE
        # matches the bare word "offer". Documented here so nobody "simplifies" the twin
        # away and silently reintroduces the bug.
        import marcus_engine
        import sms_guard
        self.assertTrue(
            sms_guard._quotes_price_or_offer(marcus_engine.MarcusEngine._PRICE_FALLBACK))

    def test_twin_has_no_digits_or_dollar_sign(self):
        import marcus_engine
        t = marcus_engine.CALL_PIVOT_FALLBACK
        self.assertNotIn("$", t)
        self.assertFalse(any(ch.isdigit() for ch in t))


class ConvoPivotLedgerTest(unittest.TestCase):
    def setUp(self):
        self._orig = conversation_engine.STATE
        self._tmp = tempfile.TemporaryDirectory()
        conversation_engine.STATE = Path(self._tmp.name) / "conversations.json"

    def tearDown(self):
        conversation_engine.STATE = self._orig
        self._tmp.cleanup()

    def test_note_call_pivot_persists_and_survives_update(self):
        ce = conversation_engine.ConversationEngine()
        ce.update("v1", contact_id="c1", report=REPORT)
        ts = ce.note_call_pivot("v1", reason="classify:PRICE")
        self.assertTrue(ts)
        self.assertTrue(ce.get("v1")["callPivotAt"])
        # A later screening refresh must not wipe the ledger — update() mutates the record.
        ce.update("v1", contact_id="c1", report=REPORT)
        self.assertTrue(ce.get("v1")["callPivotAt"])


if __name__ == "__main__":
    unittest.main()
