import tempfile
import unittest
from pathlib import Path

import marcus_engine
import marcus_screening
import sms_guard


class SmsGuardTest(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "STATE": sms_guard.STATE,
            "paused": sms_guard.forge_ops.paused,
            "within": sms_guard._within_hours,
            "touched": sms_guard.send_ledger.touched_within,
            "verdict": sms_guard.legit_check.verdict,
            "cap": sms_guard.DAILY_CAP,
        }
        self._tmp = tempfile.TemporaryDirectory()
        sms_guard.STATE = Path(self._tmp.name) / "sms_guard.json"
        self.reset()

    def tearDown(self):
        sms_guard.STATE = self._orig["STATE"]
        sms_guard.forge_ops.paused = self._orig["paused"]
        sms_guard._within_hours = self._orig["within"]
        sms_guard.send_ledger.touched_within = self._orig["touched"]
        sms_guard.legit_check.verdict = self._orig["verdict"]
        sms_guard.DAILY_CAP = self._orig["cap"]
        self._tmp.cleanup()

    def reset(self):
        sms_guard.forge_ops.paused = lambda: False
        sms_guard._within_hours = lambda: True
        sms_guard.send_ledger.touched_within = lambda conv_id, hours: False
        sms_guard.legit_check.verdict = lambda scout, conv_id, name="": {
            "legit": True,
            "urgency": "high",
            "reason": "test",
        }
        sms_guard.DAILY_CAP = 80

    def gate(self, **kw):
        return sms_guard.guard(
            kw.pop("contact_id", "c1"),
            kw.pop("message", "sounds good, when can we talk?"),
            conv_id=kw.pop("conv_id", "v1"),
            name="Test Lead",
            last_seller_message=kw.pop("last", "yes I am interested"),
            kind=kw.pop("kind", "reply"),
            autonomous=kw.pop("autonomous", False),
            reserve=kw.pop("reserve", False),
        )

    def assertGate(self, expected, **kw):
        res = self.gate(**kw)
        got = "ok" if res.get("ok") else res.get("gate")
        self.assertEqual(expected, got, res)

    # ---- gates that apply to EVERY send, operator or autonomous ----
    def test_hours_block_applies_to_all(self):
        sms_guard._within_hours = lambda: False
        self.assertGate("send_hours")                          # operator (default)
        self.assertGate("send_hours", autonomous=True)         # autonomous

    def test_dnc_and_hard_no_block_all(self):
        # Seller opt-out / hard-no is a legal stop — it blocks the operator too.
        self.assertGate("hard_no", last="stop texting me")
        self.assertGate("hard_no", last="no thanks")
        self.assertGate("hard_no", last="stop texting me", autonomous=True)

    def test_autonomous_price_offer_block(self):
        self.assertGate("price_offer", autonomous=True, message="i can do $100k cash")
        # nurture (even operator-tapped) can never quote a price/offer
        self.assertGate(
            "price_offer",
            last="not right now",
            kind="screening_nurture",
            message="i can offer $100,000 whenever you are ready",
        )
        self.assertGate(
            "ok",
            last="not right now",
            kind="screening_nurture",
            message="no worries, is it ok if i check back in a few months?",
        )

    # ---- gates that apply ONLY to autonomous (agent) sends ----
    def test_clock_out_blocks_autonomous_only(self):
        sms_guard.forge_ops.paused = lambda: True
        self.assertGate("clock_out", autonomous=True)
        self.assertGate("ok")           # operator's own action works even clocked out

    def test_send_ledger_blocks_autonomous_only(self):
        sms_guard.send_ledger.touched_within = lambda conv_id, hours: True
        self.assertGate("send_ledger", autonomous=True)
        self.assertGate("ok")           # operator may re-text a live thread

    def test_our_message_blocks_autonomous_only(self):
        self.assertGate("our_message", autonomous=True,
                        last="we buy houses cash offer close fast")
        self.assertGate("ok", last="we buy houses cash offer close fast")

    def test_soft_no_blocks_autonomous_only(self):
        self.assertGate("soft_no", autonomous=True, last="not right now")
        self.assertGate("ok", last="not right now")   # operator can still text a soft-no

    def test_legit_check_gates_autonomous_only(self):
        sms_guard.legit_check.verdict = lambda scout, conv_id, name="": {
            "legit": False, "reason": "not a seller",
        }
        self.assertGate("legit_check", autonomous=True)
        self.assertGate("ok")           # operator judges legitimacy themselves

    def test_legit_unavailable_never_locks_out_operator(self):
        # A missing Anthropic key / unreadable thread must not stop the operator texting.
        sms_guard.legit_check.verdict = lambda scout, conv_id, name="": {
            "legit": True, "reason": "no key — gate off",
        }
        self.assertGate("legit_check_unavailable", autonomous=True)
        self.assertGate("ok")           # operator send still goes through

    def test_daily_cap_counts_pending_reservations(self):
        sms_guard.DAILY_CAP = 1
        first = self.gate(message="first safe text", reserve=True)
        second = self.gate(contact_id="c2", conv_id="v2",
                           message="second safe text", reserve=True)
        self.assertTrue(first.get("ok"), first)
        self.assertEqual("daily_cap", second.get("gate"), second)
        sms_guard.release(first.get("reservation"))

    def test_marcus_send_fails_closed_without_guard_hook(self):
        posts = []
        m = marcus_engine.MarcusEngine(
            ghl_get=lambda *a, **k: {},
            ghl_post=lambda *a, **k: posts.append((a, k)) or {},
            location_id="loc",
        )
        m.proposals = {
            "p1": {
                "id": "p1", "conversationId": "v1", "contactId": "c1",
                "name": "Lead", "classification": "CONTINUE", "inbound": "yes",
                "suggestedReply": "sounds good when can we talk",
            }
        }
        res = m.approve("p1")
        self.assertEqual("sms_guard_missing", res.get("gate"), res)
        self.assertEqual([], posts)

    def test_screening_nurture_fails_closed_without_guard_hook(self):
        posts = []
        s = marcus_screening.Screener(
            ghl_get=lambda *a, **k: {},
            location_id="loc",
            scout=None,
            ghl_post=lambda *a, **k: posts.append((a, k)) or {},
        )
        s.screenings = {
            "c1": {
                "contactId": "c1", "convId": "v1", "name": "Lead",
                "report": {"nurtureDraft": "no worries can i check back later"},
            }
        }
        res = s.send_nurture("c1")
        self.assertEqual("sms_guard_missing", res.get("gate"), res)
        self.assertEqual([], posts)

    def test_marcus_template_fallback_is_voice_scrubbed(self):
        orig_draft = marcus_engine.draft_reply
        try:
            marcus_engine.draft_reply = lambda first, cls: "hey there — sure; let's talk!"
            m = marcus_engine.MarcusEngine(
                ghl_get=lambda *a, **k: {},
                ghl_post=lambda *a, **k: {},
                location_id="loc",
            )
            m.anthropic_key = ""
            text, source = m._ai_draft("there", "CONTINUE", "sounds good", [], None)
            self.assertEqual("template", source)
            self.assertNotIn("—", text)
            self.assertNotIn(";", text)
            self.assertNotIn("!", text)
        finally:
            marcus_engine.draft_reply = orig_draft


if __name__ == "__main__":
    unittest.main()
