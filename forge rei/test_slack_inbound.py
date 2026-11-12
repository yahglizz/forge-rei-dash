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
        with mock.patch.object(telegram_ops, "route", return_value=False):
            slack_inbound.handle_message_event(msg("solomon, ratios?", channel=WHOLESALE))
        slack_inbound.handle_message_event(msg("orion: what's down?", channel=DAYCARE))
        self.assertEqual(self.chats, [])
        texts = [p[2] for p in self.posts()]
        self.assertIn("own channel", texts[0])
        self.assertIn("HQ channel", texts[1])
        with mock.patch.object(telegram_ops, "route", return_value=False) as route:
            slack_inbound.handle_message_event(msg("any hot sellers?", channel=WHOLESALE))
        route.assert_called_once()                  # Telegram parity: plain English tries ops first
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

    # Telegram parity (2026-11-11) ---------------------------------------------------
    def test_registered_slash_command_equals_forge_prefix(self):
        seen = []
        with mock.patch.object(telegram_ops, "route", lambda t, c, send: seen.append(t) or True):
            out = slack_inbound.handle_slash(dict(slash(""), command="/today"))
            slack_inbound.handle_slash(dict(slash("arthur: I can call at 3"), command="/text"))
        self.assertEqual(out, {})
        self.assertEqual(seen, ["/today", "/text arthur: I can call at 3"])
        slack_inbound.handle_slash(dict(slash("how many tours?", channel=HQ), command="/solomon"))
        self.assertEqual(self.chats, [("solomon", "how many tours?", f"slack:{HQ}")])
        self.assertEqual(slack_inbound.handle_slash(dict(slash("", user=STRANGER), command="/today"))["text"],
                         "Not authorized")

    def test_plain_english_ops_in_wholesale_channel(self):
        seen = []
        with mock.patch.object(telegram_ops, "route", lambda t, c, send: seen.append((t, c)) or True):
            slack_inbound.handle_message_event(msg("text arthur I can call at 3", channel=WHOLESALE))
            slack_inbound.handle_message_event(msg("text arthur hi", channel=HQ))   # wholesale has its own
        self.assertEqual(seen, [("text arthur I can call at 3", f"slack:{WHOLESALE}")])
        self.assertEqual(self.chats, [("orion", "text arthur hi", f"slack:{HQ}")])

    def test_agents_roster_scoped_to_channel(self):
        slack_inbound.handle_slash(slash("agents", channel=DAYCARE))
        slack_inbound.handle_slash(slash("agents", channel=HQ))
        day, hq = self.posts()[0][2], self.posts()[1][2]
        self.assertIn("solomon", day)
        self.assertNotIn("marcus", day)
        for a in ("marcus", "solomon", "dyson", "orion"):
            self.assertIn(a, hq)
        self.assertIn("active", day)

    def test_ace_status_and_set(self):
        fake = mock.MagicMock(status=lambda: {"mode": "off", "sentToday": 2},
                              set_mode=lambda m: {"mode": m} if m == "shadow" else {"error": "bad mode"})
        with mock.patch.dict(sys.modules, {"ace": fake}):
            slack_inbound.handle_slash(slash("ace"))
            slack_inbound.handle_slash(slash("ace shadow"))
            slack_inbound.handle_slash(slash("ace nope"))
        texts = [p[2] for p in self.posts()]
        self.assertIn("*OFF*", texts[0])
        self.assertIn("*SHADOW*", texts[1])
        self.assertIn("bad mode", texts[2])
        self.assertEqual(self.chats, [])

    def test_task_files_for_active_agent_then_answers(self):
        hub = mock.MagicMock(send_task=mock.MagicMock(return_value={"ok": True}))
        with mock.patch.dict(sys.modules, {"agents_hub": hub}):
            slack_inbound.handle_slash(slash("task call the Smith family", channel=DAYCARE))
        hub.send_task.assert_called_once_with("solomon", "call the Smith family")
        self.assertIn("Filed for Solomon", self.posts()[0][2])
        self.assertEqual(self.chats, [("solomon", "call the Smith family", f"slack:{DAYCARE}")])

    def test_task_for_agency_agent_queues_on_agency_board(self):
        tfn = mock.MagicMock(return_value={"plan": "1. edit hero"})
        tg._AGENT_SESS[f"slack:{HQ}"] = {"agent": "dyson", "history": []}
        with mock.patch.dict(tg._AGENCY_TASK, {"fn": tfn}):
            slack_inbound.handle_slash(slash("task fix the hero copy", channel=HQ))
        tfn.assert_called_once_with("dyson", "fix the hero copy")
        self.assertIn("Queued for Dyson", self.posts()[0][2])
        self.assertEqual(self.chats, [])

    def test_owner_turn_goes_through_gateway(self):
        import agent_gateway
        calls = []

        def local(agent, text, origin, history=None):
            calls.append((agent, text, origin))
            return {"reply": "Pong.", "agent": "Orion", "job": "j1"}
        with mock.patch.object(agent_gateway, "chat_local", local):
            slack_inbound.handle_message_event(msg("ping", channel=HQ))
            slack_inbound.handle_message_event(msg("ping", channel=HQ, user=STRANGER))
        self.assertEqual(calls, [("orion", "ping", "slack")])
        self.assertEqual(self.chats, [])                       # gateway answered: no old path
        self.assertIn("Pong.", self.posts()[0][2])
        sys.modules["agents_history"].record.assert_not_called()   # the gateway job records itself
        with mock.patch.object(agent_gateway, "chat_local", return_value=None):
            slack_inbound.handle_message_event(msg("ping", channel=HQ))
        self.assertEqual(self.chats, [("orion", "ping", f"slack:{HQ}")])   # fallback

    def test_is_owner_accepts_slack_owner_only(self):
        import agent_gateway
        with mock.patch.dict(os.environ, {"FORGE_GATEWAY_OWNER_IDS": "12345"}):
            self.assertTrue(agent_gateway.is_owner("12345"))
            self.assertTrue(agent_gateway.is_owner(OWNER))
            self.assertFalse(agent_gateway.is_owner(STRANGER))
            self.assertFalse(agent_gateway.is_owner(""))
            self.assertEqual(agent_gateway._owner_ids(), {"12345"})   # Mac output DMs stay Telegram-only
        with mock.patch.dict(os.environ, {"SLACK_ALLOWED_USER_IDS": ""}):
            self.assertFalse(agent_gateway.is_owner(OWNER))
        with mock.patch.dict(os.environ, {"SLACK_ALLOWED_USER_IDS": f"{OWNER},UMATE1", "SLACK_OWNER_IDS": OWNER}):
            self.assertTrue(agent_gateway.is_owner(OWNER))
            self.assertFalse(agent_gateway.is_owner("UMATE1"))       # teammate: allowlisted, not owner

    def test_literal_slash_message_runs_as_the_command(self):
        """Threads / phones / a swallowed popup deliver "/task x" as a plain message."""
        hub = mock.MagicMock(send_task=mock.MagicMock(return_value={"ok": True}))
        with mock.patch.dict(sys.modules, {"agents_hub": hub}):
            slack_inbound.handle_message_event(msg("/task call the Smith family", channel=DAYCARE, thread_ts="7.7"))
        hub.send_task.assert_called_once_with("solomon", "call the Smith family")
        self.assertEqual(self.posts()[0][1], "7.7")                    # answered in the thread
        slack_inbound.handle_message_event(msg("/forge agents", channel=DAYCARE))
        slack_inbound.handle_message_event(msg("/solomon how many tours?", channel=HQ))
        self.assertIn(("solomon", "how many tours?", f"slack:{HQ}"), self.chats)
        n = len(self.chats)
        slack_inbound.handle_message_event(msg("/home/user/file.txt is odd", channel=DAYCARE))
        self.assertEqual(len(self.chats), n + 1)                       # not a command: plain chat
        slack_inbound.handle_message_event(msg("/forge bind agency", channel="GNEWAG1"))   # unbound channel
        self.assertEqual(slack_io.business_of("GNEWAG1"), "agency")
        slack_inbound.handle_message_event(msg("/task x", channel=DAYCARE, user=STRANGER))
        self.assertEqual(len(self.chats), n + 1)                       # strangers still ignored

    def test_reply_clamp(self):
        c = slack_inbound.clamp
        two = "Call Ija Henry first at 2318 Cecil B. Moore on Nov. 13 at 10 a.m. sharp. I did not check the rest."
        self.assertEqual(c(two), two)                                  # initials + abbreviations do not split
        self.assertEqual(c("One. Two. Three. Four."), "One. Two. (more: just ask)")
        self.assertEqual(c("Yes."), "Yes.")
        self.assertEqual(c("It is 2.5 hours. Fine."), "It is 2.5 hours. Fine.")
        bl = "Top three:\n1. A thing\n2. B thing\n3. C thing"
        self.assertEqual(c(bl), bl)
        self.assertEqual(c(bl + "\nI only read the top of the board."), bl + " (more: just ask)")
        many = "\n".join(f"• item {i}" for i in range(8))
        self.assertEqual(c(many).count("•"), 5)
        self.assertTrue(c(many).endswith("(more: just ask)"))
        self.reply = {"reply": "A. B is next. C too. D also.", "cards": []}
        slack_inbound.handle_message_event(msg("anything?"))
        self.assertIn("(more: just ask)", self.posts()[0][2])


if __name__ == "__main__":
    unittest.main()
