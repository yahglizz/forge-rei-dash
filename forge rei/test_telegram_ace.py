import ast
import tempfile
import unittest
from pathlib import Path

import ace
import conversation_engine
import telegram_io


REPORT = {
    "interest": "interested",
    "conditionNotes": "needs work",
    "callPrep": {"questions": ["How soon are you hoping to close?"]},
}


class ReceiptMarcus:
    def __init__(self):
        self.proposals = {}

    def make_proposal_for(self, conv_id, contact_id=None, hint=None, seller_said=None,
                          pivot=False):
        pid = f"proposal-{conv_id}"
        self.proposals[pid] = {
            "id": pid,
            "conversationId": conv_id,
            "contactId": contact_id,
            "status": "pending",
            "suggestedReply": "when is a good time for a quick call today?",
            "pivot": bool(pivot),
            "ts": 1,
        }
        return {"ok": True, "conversationId": conv_id, "proposalId": pid}

    def approve(self, pid, edited=None):
        proposal = self.proposals[pid]
        proposal["status"] = "sent"
        proposal["sentReply"] = edited or proposal["suggestedReply"]
        return {"ok": True}


class TelegramAceCallbackTest(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "ace_state": ace.STATE,
            "call_ready": ace.CALL_READY,
            "conversation_state": conversation_engine.STATE,
            "paused": ace.forge_ops.paused,
            "test_status": ace.test_mode.status,
            "actions": telegram_io._ACTIONS,
            "authorized": telegram_io._authorized,
            "api": telegram_io._api,
            "send": telegram_io.send,
        }
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        ace.STATE = root / "ace.json"
        ace.CALL_READY = root / "call_ready.json"
        conversation_engine.STATE = root / "conversations.json"
        ace._save({
            "mode": "full",
            "day": ace._today_key(),
            "sentToday": 0,
            "log": [],
        })
        ace.forge_ops.paused = lambda: False
        ace.test_mode.status = lambda: {"enabled": False}
        self.api_calls = []
        self.receipts = []
        telegram_io._authorized = lambda from_id, chat_id: True
        telegram_io._api = self._capture_api
        telegram_io.send = self._capture_send
        self.convo = conversation_engine.ConversationEngine()
        telegram_io.set_actions({
            "acestop": lambda conv_id: ace.hold(
                conv_id, self.convo, reason="operator stop tap"
            ),
            "aceundo": lambda conv_id: ace.hold(
                conv_id, self.convo, reason="operator undo tap"
            ),
        })

    def tearDown(self):
        ace.STATE = self._orig["ace_state"]
        ace.CALL_READY = self._orig["call_ready"]
        conversation_engine.STATE = self._orig["conversation_state"]
        ace.forge_ops.paused = self._orig["paused"]
        ace.test_mode.status = self._orig["test_status"]
        telegram_io._ACTIONS = self._orig["actions"]
        telegram_io._authorized = self._orig["authorized"]
        telegram_io._api = self._orig["api"]
        telegram_io.send = self._orig["send"]
        self._tmp.cleanup()

    def _capture_api(self, method, payload=None, **kwargs):
        self.api_calls.append((method, payload, kwargs))
        return {"ok": True, "result": {}}

    def _capture_send(self, text, buttons=None, dedupe_key=None):
        self.receipts.append({
            "text": text,
            "buttons": buttons or [],
            "dedupe_key": dedupe_key,
        })
        return {"ok": True}

    def _dispatch(self, payload, conv_id):
        self.convo.update(
            conv_id,
            contact_id=f"contact-{conv_id}",
            name="Test Lead",
            report=REPORT,
        )
        before = self.convo.get(conv_id)
        self.assertFalse(before.get("held"), before)
        telegram_io._handle_callback({
            "id": f"callback-{payload}",
            "from": {"id": "operator"},
            "data": f"{payload}:{conv_id}",
            "message": {
                "message_id": 42,
                "text": "ACE sent a message",
                "chat": {"id": "operator"},
            },
        }, token="test-token")
        return self.convo.get(conv_id)

    def _assert_callback_holds_and_stops(self, payload):
        conv_id = f"conv-{payload}"
        stored = self._dispatch(payload, conv_id)
        self.assertTrue(stored.get("held"), stored)
        decision = ace.decide(stored, REPORT, self.convo)
        self.assertEqual("stop", decision.get("action"), decision)
        self.assertEqual("operator-held", decision.get("reason"), decision)
        self.assertEqual(
            ["answerCallbackQuery", "editMessageText"],
            [method for method, _payload, _kwargs in self.api_calls],
        )

    def test_acestop_callback_holds_thread_and_decide_stops(self):
        self._assert_callback_holds_and_stops("acestop")

    def test_aceundo_callback_holds_thread_and_decide_stops(self):
        self._assert_callback_holds_and_stops("aceundo")

    def test_pivot_receipt_callback_dispatch_holds_thread_and_stops_next_decision(self):
        conv_id = "conv-receipt-integration"
        stored = self.convo.update(
            conv_id,
            contact_id="contact-receipt",
            name="Receipt Lead",
            phone="2675550111",
            report=REPORT,
        )
        pivot_record = dict(stored, state="CALL_READY")

        result = ace.apply(
            conv_id,
            pivot_record,
            REPORT,
            self.convo,
            ReceiptMarcus(),
            last_seller_msg="how much can you pay?",
        )

        self.assertTrue(result.get("pivoted"), result)
        production_actions = getattr(ace, "telegram_action_handlers", None)
        self.assertTrue(
            callable(production_actions),
            "ACE must expose the production action mapping used by connector",
        )
        telegram_io.set_actions(production_actions(self.convo))
        pivot_receipts = [
            receipt for receipt in self.receipts
            if receipt["dedupe_key"] == f"acepivot:{conv_id}"
        ]
        self.assertEqual(1, len(pivot_receipts), self.receipts)
        pivot_receipt = pivot_receipts[0]
        self.assertIn("ACE call-pivot", pivot_receipt["text"])
        payloads = [
            button.get("callback_data")
            for row in pivot_receipt["buttons"]
            for button in row
            if button.get("callback_data")
        ]
        self.assertIn(f"acestop:{conv_id}", payloads)
        self.assertIn(f"aceundo:{conv_id}", payloads)
        captured_payload = next(
            payload for payload in payloads if payload.startswith("acestop:")
        )

        telegram_io._handle_callback({
            "id": "callback-from-captured-receipt",
            "from": {"id": "operator"},
            "data": captured_payload,
            "message": {
                "message_id": 43,
                "text": "ACE call-pivot receipt",
                "chat": {"id": "operator"},
            },
        }, token="test-token")

        held = self.convo.get(conv_id)
        self.assertTrue(held.get("held"), held)
        decision = ace.decide(held, REPORT, self.convo)
        self.assertEqual("stop", decision.get("action"), decision)
        self.assertEqual("operator-held", decision.get("reason"), decision)

    def test_production_connector_registers_shared_ace_action_handlers(self):
        source = Path(__file__).with_name("connector.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        registries = [
            node.args[0]
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "telegram_io"
                and node.func.attr == "set_actions"
                and node.args
                and isinstance(node.args[0], ast.Dict)
            )
        ]
        self.assertEqual(1, len(registries), "expected one production action registry")
        shared_factories = [
            value
            for key, value in zip(registries[0].keys, registries[0].values)
            if key is None
        }
        matches = []
        for call in shared_factories:
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "ace"
                and call.func.attr == "telegram_action_handlers"
            ):
                continue
            self.assertEqual(1, len(call.args))
            self.assertIsInstance(call.args[0], ast.Name)
            self.assertEqual("CONVO", call.args[0].id)
            matches.append(call)
        self.assertEqual(
            1,
            len(matches),
            "connector must register ace.telegram_action_handlers(CONVO)",
        )


if __name__ == "__main__":
    unittest.main()
