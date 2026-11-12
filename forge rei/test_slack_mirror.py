"""telegram_io -> Slack mirror hook (FORGE_CHAT_TRANSPORT = telegram | both | slack).
Run: FORGE_MARCUS=0 python3 -m unittest test_slack_mirror  (no network: telegram_io._api and
slack_io._api / send / send_photo are always faked; state lives in temp dirs)."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

# Import slack_io against an EMPTY config dir so a real slack.env (if present) never loads.
if "slack_io" not in sys.modules:
    os.environ["FORGE_SLACK_CONFIG_DIR"] = tempfile.mkdtemp(prefix="slack_cfg_")

import slack_io  # noqa: E402
import telegram_io as tg  # noqa: E402

REAL_SEND = slack_io.send
REAL_THREAD = threading.Thread
OPERATOR = "7001"
DAYCARE_GROUP = "-100555"
BTN = [[{"text": "✅ Do it", "callback_data": "pgo:tok1"}, {"text": "❌", "callback_data": "pno:tok1"}]]


class _SyncThread:
    """Run mirror threads inline so assertions see the Slack call (test_telegram_biz_chats pattern)."""
    started = []

    def __init__(self, target=None, args=(), kwargs=None, name=None, **_):
        self.t, self.a, self.k, self.name = target, args, kwargs or {}, name

    def start(self):
        _SyncThread.started.append(self.name)
        self.t(*self.a, **self.k)


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("SLACK_", "TELEGRAM_")) and k != "FORGE_CHAT_TRANSPORT"}
        env.update({"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": OPERATOR, "TELEGRAM_ALLOWED_IDS": ""})
        self.api, self.slack = [], []
        self.tg_reply = {"ok": True, "result": {"message_id": 42}}
        _SyncThread.started = []
        self.patches = [
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(tg, "STATE", Path(self.tmp.name) / "telegram.json"),
            mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
            mock.patch.object(tg, "_api", self._tg_api),
            mock.patch.object(tg.threading, "Thread", _SyncThread),
            mock.patch.object(slack_io, "send", self._rec("send")),
            mock.patch.object(slack_io, "send_photo", self._rec("send_photo")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _tg_api(self, method, payload, **kw):
        self.api.append((method, payload, kw))
        reply = self.tg_reply(method) if callable(self.tg_reply) else self.tg_reply
        return dict(reply)

    def _rec(self, kind):
        def fn(*a, **kw):
            self.slack.append((kind, a, kw))
            return True
        return fn

    def _all_sends(self, run=""):
        tg.send("<b>alert</b>", dedupe_key="k1" + run)
        tg.send_biz("daycare", "biz", buttons=BTN, dedupe_key="k2" + run)
        tg.send_photo("daycare", "https://img.test/a.png", "<b>Ad</b>", buttons=BTN, dedupe_key="k3" + run)
        tg._send_to(OPERATOR, "agent reply", buttons=BTN)

    # ── telegram (default) ─────────────────────────────────────────────────────
    def test_mode_telegram_never_calls_slack(self):
        for mode in (None, "telegram", "nonsense"):
            if mode:
                os.environ["FORGE_CHAT_TRANSPORT"] = mode
            with mock.patch.object(slack_io, "_api", side_effect=AssertionError("slack network")):
                self._all_sends(str(mode))
        self.assertEqual(self.slack, [])
        self.assertEqual(_SyncThread.started, [])            # not even a mirror thread
        self.assertEqual(len(self.api), 12)                  # 4 Telegram sends x 3 modes

    def test_default_telegram_payloads_byte_for_byte_unchanged(self):
        self._all_sends()
        mk = {"inline_keyboard": BTN}
        expected = [
            ("sendMessage", {"chat_id": OPERATOR, "text": "<b>alert</b>", "parse_mode": "HTML",
                             "disable_web_page_preview": True}, {"timeout": 10}),
            ("sendMessage", {"chat_id": OPERATOR, "text": "biz", "parse_mode": "HTML",
                             "disable_web_page_preview": True, "reply_markup": mk}, {"timeout": 10}),
            ("sendPhoto", {"chat_id": OPERATOR, "photo": "https://img.test/a.png", "caption": "<b>Ad</b>",
                           "parse_mode": "HTML", "reply_markup": mk}, {"timeout": 20}),
            ("sendMessage", {"chat_id": OPERATOR, "text": "agent reply", "parse_mode": "HTML",
                             "disable_web_page_preview": True, "reply_markup": mk},
             {"timeout": 12, "token": None}),
        ]
        self.assertEqual([(m, json.dumps(p), kw) for m, p, kw in self.api],
                         [(m, json.dumps(p), kw) for m, p, kw in expected])   # key order too
        self.assertEqual(tg.send("again"), {"ok": True, "messageId": 42})
        self.assertEqual(tg._send_to(OPERATOR, "x"), {"ok": True})
        self.assertEqual(self.slack, [])

    # ── both ───────────────────────────────────────────────────────────────────
    def test_mode_both_calls_slack_once_per_send(self):
        os.environ["FORGE_CHAT_TRANSPORT"] = "both"
        self._all_sends()
        self.assertEqual(len(self.api), 4)                     # Telegram still sends every one
        self.assertEqual([k for k, _, _ in self.slack], ["send", "send", "send_photo", "send"])
        _, a, kw = self.slack[1]
        self.assertEqual((a, kw["business"], kw["buttons"], kw["dedupe_key"]), (("biz",), "daycare", BTN, "k2"))
        self.assertEqual((kw["origin_chat"], kw["tg_message_id"]), (OPERATOR, 42))
        _, a, kw = self.slack[2]
        self.assertEqual(a, ("https://img.test/a.png", "<b>Ad</b>"))
        self.assertEqual((kw["business"], kw["buttons"], kw["origin_chat"]), ("daycare", BTN, OPERATOR))
        # Telegram dedupe hit -> nothing new on either side.
        tg.send("<b>alert</b>", dedupe_key="k1")
        self.assertEqual((len(self.api), len(self.slack)), (4, 4))
        # Telegram failure -> no mirror (Slack copies delivered messages only).
        self.tg_reply = {"ok": False, "description": "chat not found"}
        self.assertIn("error", tg.send("lost"))
        self.assertEqual(len(self.slack), 4)

    def test_send_photo_failure_fallback_mirrors_once(self):
        os.environ["FORGE_CHAT_TRANSPORT"] = "both"
        self.tg_reply = lambda m: ({"ok": False, "description": "bad photo"} if m == "sendPhoto"
                                   else {"ok": True, "result": {"message_id": 7}})
        out = tg.send_photo("daycare", "https://img.test/x.png", "cap", buttons=BTN, dedupe_key="ph")
        self.assertEqual((out["ok"], out["photo"]), (True, False))
        self.assertEqual([m for m, _, _ in self.api], ["sendPhoto", "sendMessage"])
        self.assertEqual(len(self.slack), 1)                   # once, via send()'s own mirror
        kind, a, kw = self.slack[0]
        self.assertEqual(kind, "send")
        self.assertIn("Image</a>", a[0])
        self.assertEqual((kw["buttons"], kw["dedupe_key"]), (BTN, "ph"))

    def test_slack_exception_never_breaks_telegram_send(self):
        os.environ["FORGE_CHAT_TRANSPORT"] = "both"

        def boom(*a, **k):
            raise RuntimeError("slack down xoxb-secret-1")
        with mock.patch.object(slack_io, "send", boom), mock.patch.object(slack_io, "send_photo", boom):
            self.assertEqual(tg.send("a"), {"ok": True, "messageId": 42})
            self.assertTrue(tg.send_photo("daycare", "https://i/x.png", "c")["ok"])
            self.assertEqual(tg._send_to(OPERATOR, "x"), {"ok": True})
        with mock.patch.object(slack_io, "mode", boom):     # even mode() blowing up is contained
            self.assertEqual(tg.send("b"), {"ok": True, "messageId": 42})
        # A hung Slack never delays Telegram: real thread, Slack blocks until released.
        gate, done = threading.Event(), threading.Event()

        def slow(*a, **k):
            gate.wait(5)
            done.set()
            return True
        with mock.patch.object(tg.threading, "Thread", REAL_THREAD), \
                mock.patch.object(slack_io, "send", slow):
            t0 = time.monotonic()
            self.assertEqual(tg.send("c"), {"ok": True, "messageId": 42})
            self.assertLess(time.monotonic() - t0, 1.0)
            self.assertFalse(done.is_set())
            gate.set()
            self.assertTrue(done.wait(5))

    # ── slack only ─────────────────────────────────────────────────────────────
    def test_mode_slack_skips_telegram_api(self):
        os.environ["FORGE_CHAT_TRANSPORT"] = "slack"
        os.environ["TELEGRAM_BOT_TOKEN"] = ""                 # Telegram may be gone entirely
        self.assertEqual(tg.send("a", business="daycare"), {"ok": True, "slack": True})
        self.assertEqual(tg.send_photo("daycare", "https://i/x.png", "c"), {"ok": True, "slack": True})
        self.assertEqual(tg._send_to(OPERATOR, "x", buttons=BTN), {"ok": True, "slack": True})
        self.assertEqual(self.api, [])
        self.assertEqual([k for k, _, _ in self.slack], ["send", "send_photo", "send"])
        self.assertEqual(self.slack[2][2]["origin_chat"], OPERATOR)   # pgo token's chat travels along
        with mock.patch.object(slack_io, "send", lambda *a, **k: False):
            self.assertEqual(tg.send("a"), {"error": "slack send failed"})
        self.assertEqual(self.api, [])

    # ── _send_to (agent replies, gateway + Mac cards) ──────────────────────────
    def test_send_to_agent_reply_is_mirrored(self):
        os.environ["FORGE_CHAT_TRANSPORT"] = "both"
        os.environ["TELEGRAM_CHAT_DAYCARE"] = DAYCARE_GROUP
        import agent_gateway
        import telegram_agent
        with mock.patch.object(telegram_agent, "chat",
                               lambda aid, text, hist, chat_id: {"reply": "3 tours today", "cards": []}), \
                mock.patch.object(agent_gateway, "is_owner", lambda _id: False), \
                mock.patch.dict("sys.modules", {"agents_history": mock.MagicMock()}):
            tg._partner_turn(DAYCARE_GROUP, "solomon", "how many tours?")
        sends = [(a, kw) for k, a, kw in self.slack if k == "send"]
        self.assertEqual(len(sends), 1)
        self.assertIn("3 tours today", sends[0][0][0])
        self.assertEqual((sends[0][1]["business"], sends[0][1]["origin_chat"]), ("daycare", DAYCARE_GROUP))
        # A gateway card through _send_to lands in the business channel as a Slack card that
        # remembers the Telegram chat its pgo token is bound to.
        slack_io.bind("daycare", "CDAY01")
        posted = []
        with mock.patch.object(slack_io, "send", REAL_SEND), \
                mock.patch.object(slack_io, "_api", lambda m, t, **p: posted.append(p) or
                                  {"ok": True, "channel": "CDAY01", "ts": "5.6"}), \
                mock.patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb-test"}):
            self.assertEqual(tg._send_to(DAYCARE_GROUP, "🟡 card", buttons=BTN), {"ok": True})
        card_id = posted[0]["blocks"][-1]["block_id"].split("#")[0]
        card = slack_io.get_card(card_id)
        self.assertEqual((card["channel"], card["origin_chat"], card["tg_message_id"]),
                         ("CDAY01", DAYCARE_GROUP, 42))
        self.assertEqual(card["actions"], ["pgo:tok1", "pno:tok1"])


class ChannelEnvTests(unittest.TestCase):
    """chat_for order: bound business -> SLACK_CHANNEL_<BIZ> -> HQ (bound, then env) -> None."""

    def test_chat_for_env_channels(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_")}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(slack_io, "STATE", Path(d)), \
                mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(slack_io.chat_for("daycare"))
            os.environ["SLACK_CHANNEL_HQ"] = "CENVHQ"
            self.assertEqual(slack_io.chat_for("daycare"), "CENVHQ")
            os.environ["SLACK_CHANNEL_DAYCARE"] = "CENVDAY"
            self.assertEqual(slack_io.chat_for("daycare"), "CENVDAY")
            self.assertEqual(slack_io.chat_for("agency"), "CENVHQ")
            slack_io.bind("daycare", "CBOUND1")                # a binding beats the env
            slack_io.bind("hq", "CBOUNDHQ")
            self.assertEqual(slack_io.chat_for("daycare"), "CBOUND1")
            self.assertEqual(slack_io.chat_for(None), "CBOUNDHQ")
            self.assertEqual(slack_io._channels(), {"CBOUND1", "CBOUNDHQ"})
            os.environ["SLACK_CHANNEL_AGENCY"] = "CENVAG"
            self.assertEqual(slack_io._channels(), {"CBOUND1", "CBOUNDHQ", "CENVAG"})


if __name__ == "__main__":
    unittest.main()
