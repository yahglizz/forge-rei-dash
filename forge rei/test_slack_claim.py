"""C4 one live button per card across transports + security fixes from refs/08 (M2 env loader,
M3 failed-send signal). Run: FORGE_MARCUS=0 python3 -m unittest test_slack_claim
(no network: telegram_io._api and slack_io._api are faked; actions stubbed; state in temp dirs)."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

# Import slack_io against an EMPTY config dir so a real slack.env (if present) never loads.
if "slack_io" not in sys.modules:
    os.environ["FORGE_SLACK_CONFIG_DIR"] = tempfile.mkdtemp(prefix="slack_cfg_")

import slack_io  # noqa: E402
import telegram_io as tg  # noqa: E402

HERE = Path(__file__).resolve().parent
OPERATOR = "7001"                      # Telegram HQ = the operator's DM (chat id == user id)
SLACK_OWNER = "UOWNER1"
HQ, DAYCARE = "CHQ001", "CDAY01"


def slack_tap(value, card, channel=DAYCARE, user=SLACK_OWNER):
    return {"type": "block_actions", "user": {"id": user}, "channel": {"id": channel},
            "container": {"type": "message", "channel_id": channel, "message_ts": "1.1"},
            "trigger_id": uuid.uuid4().hex,
            "message": {"ts": "1.1", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "card"}}]},
            "actions": [{"type": "button", "block_id": f"{card}#0", "action_id": value, "value": value}]}


def tg_tap(data, message_id, chat=OPERATOR, user=OPERATOR):
    return {"id": uuid.uuid4().hex, "from": {"id": user}, "data": data,
            "message": {"message_id": message_id, "chat": {"id": chat}, "text": "card"}}


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ran, self.tg_calls, self.slack_calls = [], [], []
        self.lock = threading.Lock()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("SLACK_", "TELEGRAM_")) and k != "FORGE_CHAT_TRANSPORT"}
        env.update({"TELEGRAM_BOT_TOKEN": "tgtok", "TELEGRAM_CHAT_ID": OPERATOR, "TELEGRAM_ALLOWED_IDS": "",
                    "SLACK_BOT_TOKEN": "xoxb-test", "SLACK_ALLOWED_USER_IDS": SLACK_OWNER,
                    "FORGE_CHAT_TRANSPORT": "both"})

        def act(name):
            def fn(arg=None, *_):
                time.sleep(0.005)                 # widen the race window for the thread test
                with self.lock:
                    self.ran.append((name, arg))
                return {"ok": True}
            return fn
        self.actions = {"approve": act("approve"), "opspause": act("opspause")}
        self.patches = [
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
            mock.patch.object(tg, "STATE", Path(self.tmp.name) / "telegram.json"),
            mock.patch.object(slack_io, "_api", self._slack_api),
            mock.patch.object(tg, "_api", self._tg_api),
            mock.patch.object(tg, "_ACTIONS", self.actions),
        ]
        for p in self.patches:
            p.start()
        slack_io._SEEN.clear()
        slack_io.bind("hq", HQ)
        slack_io.bind("daycare", DAYCARE)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _slack_api(self, method, token, **params):
        with self.lock:
            self.slack_calls.append((method, params))
        return {"ok": True, "channel": DAYCARE, "ts": "9.9"}

    def _tg_api(self, method, payload, timeout=15, token=None):
        with self.lock:
            self.tg_calls.append((method, payload, token))
        return {"ok": True}

    def twin(self, card="card1", mid=42, actions=("approve:p1",), **kw):
        slack_io.register_card(card, DAYCARE, "1.1", list(actions), origin_chat=OPERATOR,
                               tg_message_id=mid, tg_chat_id=OPERATOR, **kw)

    def tg_methods(self):
        return [m for m, _, _ in self.tg_calls]

    # ── cross-transport single use ─────────────────────────────────────────────
    def test_telegram_tap_refused_after_slack_tap_same_card(self):
        self.twin()
        self.assertTrue(slack_io.handle_interaction(slack_tap("approve:p1", "card1"))["ok"])
        self.assertEqual(self.ran, [("approve", "p1")])
        self.tg_calls.clear()
        tg._handle_callback(tg_tap("approve:p1", 42))
        self.assertEqual(self.ran, [("approve", "p1")])                       # nothing ran again
        self.assertEqual(self.tg_calls[0][0], "answerCallbackQuery")
        self.assertEqual(self.tg_calls[0][1]["text"], "Already handled in Slack")
        self.assertEqual(self.tg_methods(), ["answerCallbackQuery", "editMessageReplyMarkup"])
        self.assertEqual(slack_io.claim_for_telegram(OPERATOR, 42), "taken")

    def test_slack_tap_refused_after_telegram_tap_same_card(self):
        self.twin()
        tg._handle_callback(tg_tap("approve:p1", 42))
        self.assertEqual(self.ran, [("approve", "p1")])
        self.assertEqual(self.tg_methods(), ["answerCallbackQuery", "editMessageText"])   # today's flow
        card = slack_io.get_card("card1")
        self.assertEqual((card["consumed"], card["consumedBy"]), (True, "telegram"))
        out = slack_io.handle_interaction(slack_tap("approve:p1", "card1"))
        self.assertEqual(out, {"ok": False, "result": "already handled"})
        self.assertEqual(len(self.ran), 1)

    def test_other_card_same_callback_value_not_blocked(self):
        self.twin("cardA", 42, ("opspause",))
        self.twin("cardB", 43, ("opspause",))
        self.assertTrue(slack_io.handle_interaction(slack_tap("opspause", "cardA"))["ok"])
        tg._handle_callback(tg_tap("opspause", 43))                           # same value, other card
        self.assertEqual(self.ran, [("opspause", ""), ("opspause", "")])
        tg._handle_callback(tg_tap("opspause", 42))                           # cardA's twin: refused
        self.assertEqual(len(self.ran), 2)
        self.assertEqual(slack_io.handle_interaction(slack_tap("opspause", "cardB"))["result"],
                         "already handled")                                   # cardB used in Telegram
        # A later card with the same value still works on both sides.
        self.twin("cardC", 44, ("opspause",))
        self.assertTrue(slack_io.handle_interaction(slack_tap("opspause", "cardC"))["ok"])
        self.assertEqual(len(self.ran), 3)

    def test_unmirrored_telegram_tap_unchanged_free(self):
        expected = [("answerCallbackQuery", {"callback_query_id": "q1", "text": "✅ Approved & sent"}, None),
                    ("editMessageText", {"chat_id": OPERATOR, "message_id": 77,
                                         "text": "card\n\n✅ Approved &amp; sent", "parse_mode": "HTML",
                                         "reply_markup": {"inline_keyboard": []}}, None)]
        cq = tg_tap("approve:p1", 77)
        cq["id"] = "q1"
        # Transport unset: the claim is never consulted, Telegram calls are exactly today's.
        os.environ.pop("FORGE_CHAT_TRANSPORT")
        with mock.patch.object(slack_io, "claim_for_telegram", side_effect=AssertionError("consulted")):
            tg._handle_callback(cq)
        self.assertEqual(self.tg_calls, expected)
        # Transport on, no Slack twin: "free", same calls; a second tap runs too (as today).
        os.environ["FORGE_CHAT_TRANSPORT"] = "both"
        for _ in range(2):
            self.tg_calls.clear()
            self.assertEqual(slack_io.claim_for_telegram(OPERATOR, 77), "free")
            tg._handle_callback(cq)
            self.assertEqual(self.tg_calls, expected)
        self.assertEqual(self.ran, [("approve", "p1")] * 3)
        self.assertEqual(self.slack_calls, [])                                # no Slack network
        self.assertEqual(slack_io.claim_for_telegram(OPERATOR, None), "free")  # no message id

    def test_telegram_tap_before_slack_copy_registers_tombstones(self):
        tg._handle_callback(tg_tap("approve:p1", 50))                         # Slack copy still in flight
        self.assertEqual(len(self.ran), 1)
        self.assertTrue(slack_io.register_card("late", DAYCARE, "2.2", ["approve:p1"], origin_chat=OPERATOR,
                                               tg_message_id=50, tg_chat_id=OPERATOR))
        self.assertTrue(slack_io.get_card("late")["consumed"])
        self.assertIsNone(slack_io.get_card(f"tg:{OPERATOR}:50"))             # tombstone consumed, not a card
        self.assertEqual(slack_io.handle_interaction(slack_tap("approve:p1", "late"))["result"],
                         "already handled")
        self.assertEqual(len(self.ran), 1)
        # Through _deliver: the late copy's Slack buttons are dropped right after posting.
        tg._handle_callback(tg_tap("approve:p1", 51))
        self.slack_calls.clear()
        self.assertTrue(slack_io.send("card", business="daycare", buttons=[[{"text": "Go", "callback_data": "approve:p1"}]],
                                      origin_chat=OPERATOR, tg_message_id=51, tg_chat_id=OPERATOR))
        self.assertEqual([m for m, _ in self.slack_calls], ["chat.postMessage", "chat.update"])
        self.assertFalse(any(b["type"] == "actions" for b in self.slack_calls[1][1]["blocks"]))

    def test_corrupt_registry_fails_closed(self):
        self.assertFalse((Path(self.tmp.name) / "slack_cards.json").exists())
        self.assertEqual(slack_io.claim_for_telegram(OPERATOR, 42), "free")  # missing file = no twin
        for junk in ("{not json", "[1, 2]"):
            (Path(self.tmp.name) / "slack_cards.json").write_text(junk)
            self.assertEqual(slack_io.claim_for_telegram(OPERATOR, 42), "unreadable")   # L2
            self.tg_calls.clear()
            tg._handle_callback(tg_tap("approve:p1", 42))
            self.assertEqual(self.ran, [])
            self.assertEqual(self.tg_methods(), ["answerCallbackQuery"])               # buttons kept
            self.assertIn("Try again in a moment", self.tg_calls[0][1]["text"])
        with mock.patch.object(slack_io, "claim_for_telegram", side_effect=RuntimeError("x")):
            tg._handle_callback(tg_tap("approve:p1", 42))                     # claim raising = refuse
        self.assertEqual(self.ran, [])
        # A twin whose claim cannot be written: refused, nothing runs.
        (Path(self.tmp.name) / "slack_cards.json").unlink()
        self.twin()
        with mock.patch.object(slack_io, "_write", lambda *a: False):
            self.assertEqual(slack_io.claim_for_telegram(OPERATOR, 42), "unreadable")

    # ── Slack side edits the Telegram twin ─────────────────────────────────────
    def test_slack_tap_edits_telegram_twin_best_effort(self):
        self.twin()
        slack_io.handle_interaction(slack_tap("approve:p1", "card1"))
        self.assertIn(("editMessageReplyMarkup", {"chat_id": OPERATOR, "message_id": 42,
                                                  "reply_markup": {"inline_keyboard": []}}, None), self.tg_calls)
        # An agent-bot card is edited with the agent bot's token.
        os.environ["TELEGRAM_AGENT_BOT_TOKEN"] = "agtok"
        self.twin("card2", 60, tg_bot="agent")
        slack_io.handle_interaction(slack_tap("approve:p1", "card2"))
        self.assertEqual(self.tg_calls[-1], ("editMessageReplyMarkup", {
            "chat_id": OPERATOR, "message_id": 60, "reply_markup": {"inline_keyboard": []}}, "agtok"))
        # A Slack-only card: no Telegram call at all.
        self.tg_calls.clear()
        slack_io.register_card("solo", DAYCARE, "3.3", ["approve:p1"])
        self.assertTrue(slack_io.handle_interaction(slack_tap("approve:p1", "solo"))["ok"])
        self.assertEqual(self.tg_calls, [])

    def test_telegram_twin_edit_failure_does_not_raise(self):
        self.twin()

        def boom(*a, **k):
            raise RuntimeError("HTTP 400 https://api.telegram.org/bottgtok/editMessageReplyMarkup")
        out = io.StringIO()
        with mock.patch.object(tg, "_api", boom), contextlib.redirect_stdout(out):
            res = slack_io.handle_interaction(slack_tap("approve:p1", "card1"))
        self.assertTrue(res["ok"])
        self.assertEqual(self.ran, [("approve", "p1")])
        self.assertIn("telegram twin edit failed: RuntimeError", out.getvalue())
        self.assertNotIn("tgtok", out.getvalue())

    def test_two_threads_same_card_exactly_one_wins(self):
        for i in range(25):
            self.twin(f"race{i}", 100 + i, (f"approve:r{i}",))
            gate = threading.Barrier(2)

            def slack_side(i=i):
                gate.wait()
                slack_io.handle_interaction(slack_tap(f"approve:r{i}", f"race{i}"))

            def tg_side(i=i):
                gate.wait()
                tg._handle_callback(tg_tap(f"approve:r{i}", 100 + i))
            threads = [threading.Thread(target=slack_side), threading.Thread(target=tg_side)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
            self.assertEqual(self.ran.count(("approve", f"r{i}")), 1, f"card {i}")
        self.assertEqual(len(self.ran), 25)


class EnvLoaderTests(unittest.TestCase):
    def test_env_loader_ignores_forbidden_keys(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "cfg"
            cfg.mkdir()
            (cfg / "slack.env").write_text(
                "FORGE_CHAT_TRANSPORT=both\nSLACK_ONLY_TEST=1\nFORGE_SLACK=1\nSLACK_TEST_CHANNEL_ID=CTEST01\n"
                "SLACK_BOT_TOKEN=xoxb-cfg\nSLACK_CHANNEL_HQ=CHQENV\nSLACK_CHANNEL_hq2=CBAD\nPATH_EVIL=1\n")
            # In process: only allowlisted keys land; routing is untouched.
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith("SLACK_") and k not in ("FORGE_CHAT_TRANSPORT", "FORGE_SLACK")}
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(slack_io, "STATE", Path(d)):
                slack_io._load_env_file(cfg / "slack.env")
                for k in ("FORGE_CHAT_TRANSPORT", "SLACK_ONLY_TEST", "FORGE_SLACK", "SLACK_CHANNEL_hq2", "PATH_EVIL"):
                    self.assertNotIn(k, os.environ)
                self.assertEqual((os.environ["SLACK_BOT_TOKEN"], os.environ["SLACK_TEST_CHANNEL_ID"]),
                                 ("xoxb-cfg", "CTEST01"))
                self.assertEqual(slack_io.mode(), "telegram")
                self.assertEqual(slack_io.chat_for("daycare"), "CHQENV")      # not the test channel
                self.assertNotIn("CTEST01", slack_io._channels())
                self.assertFalse(slack_io.send("x"))                          # still inert
                os.environ["SLACK_ONLY_TEST"] = "1"                           # real env still works
                self.assertEqual(slack_io.chat_for("daycare"), "CTEST01")
            # The real import-time path, in a clean child process.
            child = {k: v for k, v in env.items() if k != "SLACK_ONLY_TEST"}
            child.update(FORGE_SLACK_CONFIG_DIR=str(cfg), FORGE_MARCUS="0", FORGE_UNDER_TEST="1")
            out = subprocess.run(
                [sys.executable, "-c", "import os, slack_io; print(slack_io.mode(), "
                 "os.environ.get('SLACK_ONLY_TEST'), os.environ.get('FORGE_SLACK'), "
                 "bool(os.environ.get('SLACK_BOT_TOKEN')))"],
                cwd=str(HERE), env=child, capture_output=True, text=True, timeout=60)
            self.assertEqual(out.stdout.split(), ["telegram", "None", "None", "True"], out.stderr)


class FailedSendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("SLACK_", "TELEGRAM_")) and k != "FORGE_CHAT_TRANSPORT"}
        env.update({"FORGE_CHAT_TRANSPORT": "slack", "SLACK_BOT_TOKEN": "xoxb-secret-777"})
        self.patches = [mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
                        mock.patch.object(tg, "STATE", Path(self.tmp.name) / "telegram.json"),
                        mock.patch.object(tg, "_api", side_effect=AssertionError("telegram network"))]
        for p in self.patches:
            p.start()
        slack_io.bind("daycare", DAYCARE)
        slack_io._STATUS["last_error"] = None

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_failed_send_logs_no_body_no_token(self):
        body = "SECRET BODY Jane 215-555-0100"
        out = io.StringIO()
        with mock.patch.object(slack_io, "_api", lambda m, t, **p: {"ok": False, "error": "channel_not_found"}), \
                contextlib.redirect_stdout(out):
            res = tg.send(body, business="daycare")
        self.assertEqual(res, {"error": "slack send failed"})                 # propagated, not dropped
        self.assertIn("[slack] send failed: channel_not_found channel=CDAY01", out.getvalue())
        self.assertEqual(slack_io.status()["last_error"], "channel_not_found")
        self.assertEqual(tg._load().get("lastError"), "slack send failed")
        # No token configured, and an exception carrying the body: reason only, never the body.
        os.environ["SLACK_BOT_TOKEN"] = ""
        with contextlib.redirect_stdout(out):
            self.assertEqual(tg._send_to(OPERATOR, body), {"error": "slack send failed"})
        self.assertIn("not configured", slack_io.status()["last_error"])
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-secret-777"
        with mock.patch.object(slack_io, "to_mrkdwn", side_effect=RuntimeError(body)), \
                contextlib.redirect_stdout(out):
            self.assertEqual(tg.send_photo("daycare", "https://i/x.png", body), {"error": "slack send failed"})
        self.assertIn("send failed: error RuntimeError", out.getvalue())
        log = out.getvalue()
        for secret in ("SECRET BODY", "215-555", "xoxb-secret-777", "xoxb"):
            self.assertNotIn(secret, log)


if __name__ == "__main__":
    unittest.main()
