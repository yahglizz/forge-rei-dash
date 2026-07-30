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


class TelegramAceCallbackTest(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "ace_state": ace.STATE,
            "conversation_state": conversation_engine.STATE,
            "paused": ace.forge_ops.paused,
            "test_status": ace.test_mode.status,
            "actions": telegram_io._ACTIONS,
            "authorized": telegram_io._authorized,
            "api": telegram_io._api,
        }
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        ace.STATE = root / "ace.json"
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
        telegram_io._authorized = lambda from_id, chat_id: True
        telegram_io._api = self._capture_api
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
        conversation_engine.STATE = self._orig["conversation_state"]
        ace.forge_ops.paused = self._orig["paused"]
        ace.test_mode.status = self._orig["test_status"]
        telegram_io._ACTIONS = self._orig["actions"]
        telegram_io._authorized = self._orig["authorized"]
        telegram_io._api = self._orig["api"]
        self._tmp.cleanup()

    def _capture_api(self, method, payload=None, **kwargs):
        self.api_calls.append((method, payload, kwargs))
        return {"ok": True, "result": {}}

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


if __name__ == "__main__":
    unittest.main()
