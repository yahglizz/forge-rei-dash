"""Slack inbound: /forge (help, bind, ops route), plain text to the business partner, owner-only,
bot-loop guard, business scope, and the ✅ card chat string == the tap chat string.
Run: FORGE_MARCUS=0 python3 -m unittest test_slack_inbound  (no network: slack_io._api faked;
telegram_ops.route / telegram_agent.chat / tap actions stubbed; state in temp dirs)."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if "slack_io" not in sys.modules:
    os.environ["FORGE_SLACK_CONFIG_DIR"] = tempfile.mkdtemp(prefix="slack_cfg_")

import slack_io  # noqa: E402
import slack_inbound  # noqa: E402
import telegram_agent  # noqa: E402
import telegram_io as tg  # noqa: E402
import telegram_ops  # noqa: E402

OWNER, STRANGER = "UOWNER1", "USTRANGE"
HQ, DAYCARE, WHOLESALE, DM = "CHQ001", "CDAY01", "CWHO01", "DOWNER1"


def msg(text, channel=DAYCARE, user=OWNER, **kw):
    ev = {"type": "message", "user": user, "channel": channel, "text": text, "ts": "5.5",
          "channel_type": "im" if channel.startswith("D") else "group"}
    ev.update(kw)
    return ev


def slash(text, channel=WHOLESALE, user=OWNER):
    return {"command": "/forge", "text": text, "user_id": user, "channel_id": channel,
            "trigger_id": "T1", "response_url": "https://hooks.slack.com/commands/x"}


class InboundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api, self.chats, self.ran = [], [], []
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("SLACK_") and k != "FORGE_CHAT_TRANSPORT"}
        env.update({"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_ALLOWED_USER_IDS": OWNER})
        self.reply = {"reply": "Two tours today.", "cards": []}
        self.patches = [
            mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(slack_io, "_api", self._fake_api),
            mock.patch.object(telegram_agent, "chat", self._fake_chat),
            mock.patch.object(telegram_ops, "route", side_effect=AssertionError("route not expected")),
            mock.patch.dict(sys.modules, {"agents_history": mock.MagicMock(
                recent_for_context=lambda a: [])}),
            mock.patch.object(tg, "_ACTIONS", {
                "pgo": lambda tok, chat=None: self.ran.append(("pgo", tok, chat)) or {"ok": True, "message": "done"},
                "pno": lambda tok, chat=None: self.ran.append(("pno", tok, chat)) or {"ok": True}}),
            mock.patch.object(tg, "_foreign_mac_tap", lambda tok, uid: False),
        ]
        for p in self.patches:
            p.start()
        tg._AGENT_SESS.clear()
        slack_io._SEEN.clear()
        slack_io.bind("hq", HQ)
        slack_io.bind("daycare", DAYCARE)
        slack_io.bind("wholesale", WHOLESALE)
        self.api.clear()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        tg._AGENT_SESS.clear()
        self.tmp.cleanup()

    def _fake_api(self, method, token, **params):
        self.api.append((method, params))
        if method == "conversations.info":           # /forge bind checks (M2): private, unshared
            return {"ok": True, "channel": {"id": params["channel"], "is_private": True}}
        if method == "auth.test":
            return {"ok": True, "user_id": "UBOT"}
        if method == "conversations.members":
            return {"ok": True, "members": [OWNER, "UBOT"], "response_metadata": {"next_cursor": ""}}
        return {"ok": True, "channel": params.get("channel"), "ts": f"1.{len(self.api)}"}

    def _fake_chat(self, agent_id, text, history, chat_id, key=None, call=None):
        self.chats.append((agent_id, text, chat_id))
        return dict(self.reply)

    def posts(self):
        return [(p["channel"], p.get("thread_ts"), p.get("text") or "", p.get("blocks"))
                for m, p in self.api if m == "chat.postMessage"]

    # /forge ------------------------------------------------------------------
    def test_forge_today_routes_to_ops_route(self):
        seen = []

        def route(text, chat_id, send):
            seen.append((text, chat_id))
            send("📋 <b>Today</b> 3 calls", [[{"text": "✅ Send", "callback_data": "opsgo:tok1"}]])
            return True
        with mock.patch.object(telegram_ops, "route", route):
            out = slack_inbound.handle_slash(slash("today"))
        self.assertEqual(out, {})
        self.assertEqual(seen, [("/today", f"slack:{WHOLESALE}")])
        (channel, _, text, blocks), = self.posts()
        self.assertEqual(channel, WHOLESALE)
        self.assertIn("*Today*", text)
        self.assertEqual(blocks[-1]["elements"][0]["value"], "opsgo:tok1")
        card = slack_io.get_card(blocks[-1]["block_id"].split("#")[0])
        self.assertEqual((card["channel"], card["actions"]), (WHOLESALE, ["opsgo:tok1"]))
        self.assertEqual(self.chats, [])

    def test_forge_ops_command_refused_outside_wholesale(self):
        out = slack_inbound.handle_slash(slash("today", channel=DAYCARE))
        self.assertEqual(out, {})
        self.assertIn("wholesale command", self.posts()[0][2])
        self.assertEqual(self.chats, [])

    def test_forge_bind_sets_channel_for_business(self):
        out = slack_inbound.handle_slash(slash("bind agency", channel="GAGENCY1"))
        self.assertIn("agency", out["text"])
        self.assertEqual(slack_io.business_of("GAGENCY1"), "agency")
        self.assertEqual(slack_io.chat_for("agency"), "GAGENCY1")
        state = json.loads((Path(self.tmp.name) / "slack.json").read_text())
        self.assertEqual(state["agency"], "GAGENCY1")
        self.assertIn("not a DM", slack_inbound.handle_slash(slash("bind agency", channel=DM))["text"])
        self.assertIn("Which business", slack_inbound.handle_slash(slash("bind nope"))["text"])

    def test_forge_bind_rejected_for_non_owner(self):
        out = slack_inbound.handle_slash(slash("bind agency", channel="GAGENCY1", user=STRANGER))
        self.assertEqual(out, {"response_type": "ephemeral", "text": "Not authorized"})
        self.assertIsNone(slack_io.business_of("GAGENCY1"))
        out = slack_inbound.handle_slash(slash("today", user=STRANGER))
        self.assertEqual(out["text"], "Not authorized")
        self.assertEqual(self.api, [])

    def test_forge_in_unbound_channel_refused(self):
        out = slack_inbound.handle_slash(slash("solomon, hi", channel="CRANDOM1"))
        self.assertIn("FORGE channel", out["text"])
        self.assertEqual((self.api, self.chats), ([], []))

    def test_help_lists_every_ops_command(self):
        names = re.search(r"\(([a-z|]+)\)", telegram_ops._CMD_RE.pattern).group(1).split("|")
        self.assertGreaterEqual(len(names), 20)
        for n in names:
            self.assertTrue(telegram_ops._CMD_RE.match("/" + n), n)
        text = slack_inbound.handle_slash(slash("help"))["text"]
        self.assertEqual(text, slack_inbound.handle_slash(slash(""))["text"])
        for n in names + ["status", "starts", "logins", "pin", "board"]:
            self.assertIn(f"`{n}`", text, n)
        self.assertIn("`/forge bind daycare`", text)

    # plain messages -------------------------------------------------------------
    def test_non_owner_message_ignored(self):
        slack_inbound.handle_message_event(msg("create a login for Jane", user=STRANGER))
        slack_inbound.handle_message_event(msg("hi", channel=DM, user=STRANGER))
        self.assertEqual((self.chats, self.api), ([], []))

    def test_bot_message_ignored_no_loop(self):
        for ev in (msg("<b>Solomon</b> Two tours", bot_id="B1"),
                   msg("Two tours", subtype="bot_message"),
                   msg("edited", subtype="message_changed"),
                   msg("joined", subtype="channel_join"),
                   dict(msg("<@UBOT> hi"), type="app_mention"),
                   msg("hi", channel="CRANDOM1")):
            slack_inbound.handle_message_event(ev)
        self.assertEqual((self.chats, self.api), ([], []))

    def test_business_channel_text_goes_to_partner_chat_for_that_business(self):
        slack_inbound.handle_message_event(msg("<@UBOT> how many tours &amp; calls?", thread_ts="4.4"))
        self.assertEqual(self.chats, [("solomon", "how many tours & calls?", f"slack:{DAYCARE}")])
        self.assertEqual(telegram_agent.AGENT_BUSINESS["solomon"], "daycare")
        (channel, thread, text, _), = self.posts()
        self.assertEqual((channel, thread), (DAYCARE, "4.4"))      # reply in the thread
        self.assertIn("*Solomon*", text)
        self.assertIn("Two tours today.", text)
        sys.modules["agents_history"].record.assert_called_once_with(
            "solomon", "how many tours & calls?", "Two tours today.", via="slack")

    def test_hq_alias_prefix_solomon_routes_to_daycare_agent(self):
        slack_inbound.handle_message_event(msg("solomon, how many tours?", channel=HQ))
        slack_inbound.handle_message_event(msg("what's down?", channel=DM))
        self.assertEqual(self.chats, [("solomon", "how many tours?", f"slack:{HQ}"),
                                      ("orion", "what's down?", f"slack:{DM}")])
        self.assertEqual([p[0] for p in self.posts()], [HQ, DM])

    def test_wrong_business_alias_in_business_channel_refused(self):
        slack_inbound.handle_message_event(msg("solomon, ratios?", channel=WHOLESALE))
        slack_inbound.handle_message_event(msg("orion: what's down?", channel=DAYCARE))
        self.assertEqual(self.chats, [])
        texts = [p[2] for p in self.posts()]
        self.assertIn("own channel", texts[0])
        self.assertIn("HQ channel", texts[1])
        slack_inbound.handle_message_event(msg("any hot sellers?", channel=WHOLESALE))
        self.assertEqual(self.chats, [("marcus", "any hot sellers?", f"slack:{WHOLESALE}")])

    def test_confirm_card_chat_string_matches_tap_chat_string(self):
        import action_log
        self.reply = {"reply": "Queued it.", "cards": [
            {"tok": "tokDAY", "agent": "solomon", "path": "/api/daycare/pin", "body": {}, "summary": "reset pin"}]}
        slack_inbound.handle_message_event(msg("reset Jane's pin"))                 # business channel
        self.reply["cards"] = [dict(self.reply["cards"][0], tok="tokDM")]
        slack_inbound.handle_message_event(msg("solomon, reset Jane's pin", channel=DM))   # DM: card -> HQ
        cards = json.loads((Path(self.tmp.name) / "slack_cards.json").read_text())
        by_tok = {c["actions"][0].split(":")[1]: (cid, c) for cid, c in cards.items()}
        self.assertEqual(by_tok["tokDAY"][1]["channel"], DAYCARE)
        self.assertEqual(by_tok["tokDM"][1]["channel"], HQ)
        with mock.patch.object(action_log, "record_result"), \
                mock.patch.dict(os.environ, {"FORGE_CHAT_TRANSPORT": "both"}):   # taps need a live transport
            for tok, channel in (("tokDAY", DAYCARE), ("tokDM", HQ)):
                cid = by_tok[tok][0]
                out = slack_io.handle_interaction({
                    "type": "block_actions", "user": {"id": OWNER}, "channel": {"id": channel},
                    "trigger_id": f"trig-{tok}", "message": {"blocks": []},
                    "actions": [{"block_id": f"{cid}#0", "value": f"pgo:{tok}"}]})
                self.assertTrue(out["ok"], out)
        issued = {c[2] for c in self.chats}
        tapped = {r[2] for r in self.ran}
        self.assertEqual(issued, {f"slack:{DAYCARE}", f"slack:{DM}"})
        self.assertEqual(tapped, issued)            # telegram_agent.confirm gets the chat it queued for
        self.assertTrue(any("posted in HQ" in p[2] for p in self.posts() if p[0] == DM))


if __name__ == "__main__":
    unittest.main()
