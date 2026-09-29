"""Per-business Telegram chats: /bind, routing, fallback to HQ, tap security.
Run: python3 test_telegram_biz_chats.py (no network: _api/_send_to faked)."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import telegram_io as tg


class _SyncThread:
    """Run Telegram partner turns inline so assertions see the reply."""
    def __init__(self, target=None, args=(), kwargs=None, **_):
        self.t, self.a, self.k = target, args, kwargs or {}

    def start(self):
        self.t(*self.a, **self.k)

OPERATOR = "7001"          # HQ chat = the operator's DM, so its id IS their user id
DAYCARE_GROUP = "-100555"


class BizChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(tg, "STATE", Path(self.tmp.name) / "telegram.json"),
            mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": OPERATOR,
                                         "TELEGRAM_ALLOWED_IDS": ""}),
            mock.patch.object(tg.threading, "Thread", _SyncThread),
        ]
        for p in self.patches:
            p.start()
        for b in tg.BUSINESSES:
            os.environ.pop(f"TELEGRAM_CHAT_{b.upper()}", None)
        self.replies, self.api = [], []
        self.p_send_to = mock.patch.object(tg, "_send_to", lambda chat, text, **kw: self.replies.append((chat, text)) or {"ok": True})
        self.p_api = mock.patch.object(tg, "_api", lambda method, payload, **kw: self.api.append((method, payload)) or {"ok": True, "result": {"message_id": 1}})
        self.p_send_to.start()
        self.p_api.start()
        tg._AGENT_SESS.clear()

    def tearDown(self):
        self.p_api.stop()
        self.p_send_to.stop()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def msg(self, text, chat=DAYCARE_GROUP, sender=OPERATOR, kind="supergroup"):
        tg._handle_message({"chat": {"id": int(chat), "type": kind, "title": "FORGE Daycare"},
                            "from": {"id": int(sender)}, "text": text})

    def test_unbound_business_falls_back_to_hq(self):
        self.assertEqual(tg.chat_for("daycare"), OPERATOR)
        self.assertEqual(tg.chat_for(None), OPERATOR)
        tg.send_biz("daycare", "hi")
        self.assertEqual(self.api[-1][1]["chat_id"], OPERATOR)

    def test_bind_routes_that_business_only(self):
        self.msg("/bind@Forgelabsxbot daycare")
        self.assertIn("Daycare", self.replies[-1][1])
        self.assertEqual(tg.chat_for("daycare"), DAYCARE_GROUP)
        self.assertEqual(tg.chat_for("wholesale"), OPERATOR)
        tg.send_biz("daycare", "start date")
        tg.send("system alert")
        self.assertEqual([p["chat_id"] for _, p in self.api[-2:]], [DAYCARE_GROUP, OPERATOR])
        self.assertEqual(tg.settings()["bizChats"]["daycare"], True)
        self.msg("/unbind daycare")
        self.assertEqual(tg.chat_for("daycare"), OPERATOR)

    def test_only_operator_can_bind(self):
        self.msg("/bind daycare", sender="999")
        self.assertEqual(tg.chat_for("daycare"), OPERATOR)
        self.assertEqual(self.replies, [])

    def test_env_overrides_binding(self):
        self.msg("/bind agency")
        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_AGENCY": "-100777"}):
            self.assertEqual(tg.chat_for("agency"), "-100777")

    def test_taps_in_business_chat_operator_only(self):
        self.assertFalse(tg._authorized(OPERATOR, DAYCARE_GROUP))    # unbound group: refused
        self.msg("/bind daycare")
        self.assertTrue(tg._authorized(OPERATOR, DAYCARE_GROUP))
        self.assertFalse(tg._authorized("999", DAYCARE_GROUP))        # another group member
        self.assertTrue(tg._authorized(OPERATOR, OPERATOR))           # HQ DM unchanged
        self.assertFalse(tg._authorized("999", "-100123"))
        with mock.patch.dict(os.environ, {"TELEGRAM_ALLOWED_IDS": "999"}):
            self.assertTrue(tg._authorized("999", DAYCARE_GROUP))     # explicit allowlist wins

    def test_bus_events_route_by_business(self):
        self.msg("/bind wholesale", chat="-100888")
        sent = []
        with mock.patch.object(tg, "send", lambda text, buttons=None, dedupe_key=None, business=None: sent.append(business)):
            tg.on_bus_message({"kind": "alert", "from": "marcus", "text": "reply ready",
                               "data": {"type": "proposal", "pid": "p1", "cls": "READY"}})
            tg.on_bus_message({"kind": "alert", "from": "dyson", "text": "plan", "data": {}})
            tg.on_bus_message({"kind": "alert", "from": "x", "text": "skill",
                               "data": {"type": "skill_proposal", "pid": "s1"}})
            time.sleep(0.2)                                         # sends run on threads
        self.assertEqual(sorted(sent, key=str), sorted(["wholesale", "agency", None], key=str))

    def test_business_chat_defaults_to_its_agent(self):
        self.msg("/bind daycare")
        self.assertEqual(tg._AGENT_SESS[DAYCARE_GROUP]["agent"], "solomon")
        tg._AGENT_SESS.clear()                                      # e.g. after a restart
        import telegram_agent
        with mock.patch.object(telegram_agent, "chat",
                               lambda aid, text, hist, chat_id: {"reply": f"{aid} here", "cards": []}), \
                mock.patch.dict("sys.modules", {"agents_history": mock.MagicMock()}):
            self.msg("how many kids today?")
        self.assertIn("solomon here", self.replies[-1][1])
        self.assertIn("Solomon", self.replies[-1][1])


if __name__ == "__main__":
    unittest.main()
