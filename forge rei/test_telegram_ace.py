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

    def test_production_connector_registers_ace_hold_handlers(self):
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
        actions = {
            key.value: value
            for key, value in zip(registries[0].keys, registries[0].values)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }

        for action, reason in (
            ("acestop", "operator stop tap"),
            ("aceundo", "operator undo tap"),
        ):
            with self.subTest(action=action):
                handler = actions.get(action)
                self.assertIsInstance(handler, ast.Lambda, f"{action} must be a lambda")
                self.assertEqual(1, len(handler.args.args), f"{action} must accept conv_id")
                callback_arg = handler.args.args[0].arg
                call = handler.body
                self.assertIsInstance(call, ast.Call, f"{action} must call ace.hold")
                self.assertIsInstance(call.func, ast.Attribute)
                self.assertIsInstance(call.func.value, ast.Name)
                self.assertEqual(("ace", "hold"), (call.func.value.id, call.func.attr))
                self.assertEqual(2, len(call.args))
                self.assertIsInstance(call.args[0], ast.Name)
                self.assertEqual(callback_arg, call.args[0].id)
                self.assertIsInstance(call.args[1], ast.Name)
                self.assertEqual("CONVO", call.args[1].id)
                self.assertEqual(["reason"], [keyword.arg for keyword in call.keywords])
                keywords = {keyword.arg: keyword.value for keyword in call.keywords}
                reason_node = keywords.get("reason")
                self.assertIsInstance(reason_node, ast.Constant)
                self.assertEqual(reason, reason_node.value)


if __name__ == "__main__":
    unittest.main()
