"""Slack button taps: auth (user + channel + issuing channel), expiry, single use, retry dedupe,
audit, pgo chat binding, Mac-card owner rule, and the connector's harmless self-test action.
Run: FORGE_MARCUS=0 python3 -m unittest test_slack_taps  (no network: slack_io._api faked;
telegram_io._ACTIONS stubbed, never a real action; state in temp dirs)."""
import ast
import os
import sys
import tempfile
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

OWNER = "UOWNER1"
HQ, DAYCARE = "CHQ001", "CDAY01"
REAL_FOREIGN_MAC = tg._foreign_mac_tap       # setUp stubs it; the Mac test uses the real one


def tap(value, card="card1", user=OWNER, channel=DAYCARE, trigger=None):
    return {"type": "block_actions", "user": {"id": user}, "channel": {"id": channel},
            "container": {"type": "message", "channel_id": channel, "message_ts": "1.1"},
            "trigger_id": trigger or uuid.uuid4().hex,
            "message": {"ts": "1.1", "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "*Reply ready*"}},
                {"type": "actions", "block_id": f"{card}#0", "elements": []}]},
            "actions": [{"type": "button", "block_id": f"{card}#0", "action_id": value,
                         "value": value, "action_ts": "9.9"}]}


class TapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls, self.ran = [], []
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_")}
        env.update({"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_ALLOWED_USER_IDS": f"{OWNER}, UOTHER9",
                    "FORGE_CHAT_TRANSPORT": "both"})          # telegram mode pauses Slack taps (M1)
        self.actions = {
            "approve": lambda pid: self.ran.append(("approve", pid)) or {"ok": True},
            "slackselftest": lambda _a=None: self.ran.append(("slackselftest", _a)) or
            {"ok": True, "result": "slack self-test ok"},
            "pgo": lambda tok, chat=None: self.ran.append(("pgo", tok, chat)) or {"ok": True, "message": "done"},
            "pno": lambda tok, chat=None: self.ran.append(("pno", tok, chat)) or {"ok": True, "message": "Cancelled"},
        }
        self.patches = [
            mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(slack_io, "_api", self._fake_api),
            mock.patch.object(tg, "_ACTIONS", self.actions),
            mock.patch.object(tg, "_foreign_mac_tap", lambda tok, uid: False),
        ]
        for p in self.patches:
            p.start()
        slack_io._SEEN.clear()
        slack_io.bind("hq", HQ)
        slack_io.bind("daycare", DAYCARE)
        slack_io.register_card("card1", DAYCARE, "1.1", ["approve:p1", "slackselftest:x"])

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _fake_api(self, method, token, **params):
        self.calls.append((method, params))
        return {"ok": True}

    def methods(self):
        return [m for m, _ in self.calls]

    # ── auth ───────────────────────────────────────────────────────────────────
    def test_wrong_user_refused_action_not_called(self):
        for user in ("USTRANGER", "", None):
            out = slack_io.handle_interaction(tap("approve:p1", user=user))
            self.assertEqual(out, {"ok": False, "result": "Not authorized"})
        self.assertEqual(self.ran, [])
        self.assertNotIn("chat.update", self.methods())
        self.assertFalse(slack_io.get_card("card1")["consumed"])       # refusal never burns the card
        self.assertEqual(self.calls[0], ("chat.postEphemeral",
                                         {"channel": DAYCARE, "user": "USTRANGER", "text": "Not authorized"}))
        with mock.patch.dict(os.environ, {"SLACK_ALLOWED_USER_IDS": ""}):   # blank allowlist = nobody
            self.assertFalse(slack_io.handle_interaction(tap("approve:p1"))["ok"])
            self.assertFalse(slack_io.authorized(OWNER, DAYCARE, None))
        self.assertEqual(self.ran, [])

    def test_right_user_wrong_channel_refused(self):
        slack_io.register_card("cardx", "CRANDOM", "2.2", ["approve:p1"])   # even its own channel
        for ch in ("CRANDOM", "DOWNERDM", ""):
            out = slack_io.handle_interaction(tap("approve:p1", card="cardx", channel=ch))
            self.assertEqual(out["result"], "Not authorized")
        self.assertEqual(self.ran, [])
        self.assertTrue(slack_io.authorized(OWNER, HQ, None))
        self.assertFalse(slack_io.authorized(OWNER, "CRANDOM", None))

    def test_click_channel_must_equal_card_channel(self):
        out = slack_io.handle_interaction(tap("approve:p1", channel=HQ))     # HQ is allowed, card is daycare's
        self.assertEqual(out["result"], "Not authorized")
        self.assertFalse(slack_io.authorized(OWNER, HQ, slack_io.get_card("card1")))
        # A value the card was never issued with is refused too (no forged buttons).
        out = slack_io.handle_interaction(tap("approve:OTHER"))
        self.assertEqual(out["result"], "Not authorized")
        self.assertEqual(self.ran, [])
        self.assertFalse(slack_io.get_card("card1")["consumed"])

    # ── expiry / single use / retries ──────────────────────────────────────────
    def test_unknown_or_expired_card_says_expired(self):
        self.assertEqual(slack_io.handle_interaction(tap("approve:p1", card="nope"))["result"], "expired")
        later = time.time() + slack_io._CARD_TTL + 1
        with mock.patch.object(slack_io.time, "time", lambda: later):
            self.assertEqual(slack_io.handle_interaction(tap("approve:p1"))["result"], "expired")
        self.assertEqual(self.ran, [])
        self.assertIn("expired", self.calls[-1][1]["text"])
        # Garbage payloads never crash.
        for junk in (None, {}, {"type": "block_actions"}, {"type": "block_actions", "actions": ["x"]},
                     {"type": "view_submission"}):
            self.assertFalse(slack_io.handle_interaction(junk)["ok"])
        # Card registry survives a "restart": it is read from disk every time.
        self.assertTrue(slack_io.handle_interaction(tap("approve:p1"))["ok"])

    def test_second_tap_same_card_refused(self):
        out = slack_io.handle_interaction(tap("slackselftest:x"))
        self.assertTrue(out["ok"])
        self.assertEqual(self.ran, [("slackselftest", "x")])
        method, p = next(c for c in self.calls if c[0] == "chat.update")
        self.assertEqual((p["channel"], p["ts"]), (DAYCARE, "1.1"))
        self.assertFalse(any(b["type"] == "actions" for b in p["blocks"]))   # buttons dropped
        self.assertEqual(p["blocks"][0]["text"]["text"], "*Reply ready*")    # original text kept
        self.assertTrue(slack_io.get_card("card1")["consumed"])
        # Another button on the same card, a fresh delivery: refused, nothing runs.
        out = slack_io.handle_interaction(tap("approve:p1"))
        self.assertEqual(out, {"ok": False, "result": "already handled"})
        self.assertEqual(len(self.ran), 1)
        self.assertEqual(self.methods().count("chat.update"), 1)

    def test_retry_delivery_same_envelope_runs_once(self):
        payload = tap("approve:p1", trigger="trig-1")
        self.assertTrue(slack_io.handle_interaction(payload, envelope_id="env-1")["ok"])
        self.assertEqual(slack_io.handle_interaction(payload, envelope_id="env-1"),
                         {"ok": False, "result": "duplicate"})
        self.assertEqual(slack_io.handle_interaction(payload, envelope_id="env-2")["result"], "duplicate")
        self.assertEqual(self.ran, [("approve", "p1")])
        self.assertEqual(self.methods().count("chat.postEphemeral"), 0)       # a retry is silent

    def test_claim_fails_closed_when_card_write_fails(self):
        with mock.patch.object(slack_io, "_write", lambda *a: False):
            out = slack_io.handle_interaction(tap("approve:p1"))
        self.assertFalse(out["ok"])
        self.assertIn("could not record", out["result"])
        self.assertEqual(self.ran, [])

    # ── dispatch + audit ───────────────────────────────────────────────────────
    def test_result_audited_via_action_log(self):
        import action_log
        with mock.patch.object(action_log, "record_result") as rec:
            slack_io.handle_interaction(tap("approve:p1"))
        rec.assert_called_once_with({"ok": True}, "marcus", "tap:approve", business="wholesale",
                                    trigger="slack_tap", ref="p1", approval_required=True)
        # An action that raises is audited as an error and shown, never crashes.
        slack_io.register_card("card2", DAYCARE, "3.3", ["approve:p2"])
        self.actions["approve"] = lambda pid: 1 / 0
        with mock.patch.object(action_log, "record_result") as rec:
            out = slack_io.handle_interaction(tap("approve:p2", card="card2"))
        self.assertFalse(out["ok"])
        self.assertIn("division by zero", out["result"])
        self.assertIn("error", rec.call_args[0][0])

    def test_pgo_gets_slack_chat_string(self):
        slack_io.register_card("born", DAYCARE, "4.4", ["pgo:tokA", "pno:tokA"])        # Slack-born card
        slack_io.register_card("mirr", DAYCARE, "5.5", ["pgo:tokB"], origin_chat="-100555")  # Telegram twin
        self.assertTrue(slack_io.handle_interaction(tap("pgo:tokA", card="born"))["ok"])
        self.assertTrue(slack_io.handle_interaction(tap("pgo:tokB", card="mirr"))["ok"])
        self.assertEqual(self.ran, [("pgo", "tokA", f"slack:{DAYCARE}"), ("pgo", "tokB", "-100555")])

    def test_mac_card_needs_owner(self):
        slack_io.register_card("mac", DAYCARE, "6.6", ["pgo:tokM"], origin_chat="-100555")
        # The REAL owner check: owner ids are Telegram ids, so a Slack user id is never the owner
        # and a Mac card is always refused from Slack (refs/08 L1, fails closed).
        import json
        import telegram_agent
        pending = Path(self.tmp.name) / "pending.json"
        pending.write_text(json.dumps({"tokM": {"chat": "-100555", "ts": int(time.time()),
                                                "mac": {"command": "echo hi"}}}))
        with mock.patch.object(tg, "_foreign_mac_tap", REAL_FOREIGN_MAC), \
                mock.patch.object(telegram_agent, "STATE", pending), \
                mock.patch.dict(os.environ, {"FORGE_GATEWAY_OWNER_IDS": "7001"}):
            self.assertTrue(telegram_agent.is_mac_card("tokM"))
            out = slack_io.handle_interaction(tap("pgo:tokM", card="mac"))
        self.assertEqual(out["result"], "Only the owner can run a Mac command")
        self.assertFalse(slack_io.get_card("mac")["consumed"])       # stays for the owner

        def boom(tok, uid):
            raise RuntimeError("state unreadable")
        with mock.patch.object(tg, "_foreign_mac_tap", boom):         # can't tell = refuse
            self.assertFalse(slack_io.handle_interaction(tap("pgo:tokM", card="mac"))["ok"])
        self.assertEqual(self.ran, [])


class ConnectorSelfTestAction(unittest.TestCase):
    def test_slackselftest_registered_and_harmless(self):
        tree = ast.parse(Path(__file__).with_name("connector.py").read_text(encoding="utf-8"))
        regs = [n.args[0] for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and getattr(n.func.value, "id", None) == "telegram_io" and n.func.attr == "set_actions"]
        self.assertEqual(len(regs), 1)
        val = next(v for k, v in zip(regs[0].keys, regs[0].values)
                   if isinstance(k, ast.Constant) and k.value == "slackselftest")
        fn = eval(compile(ast.Expression(val), "connector.py", "eval"), {})   # a bare lambda, no names
        self.assertEqual(fn("x"), {"ok": True, "result": "slack self-test ok"})


if __name__ == "__main__":
    unittest.main()
