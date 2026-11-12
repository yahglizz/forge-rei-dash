"""Second security pass (refs/09): M1 rollback keeps single use, M2 /forge bind checks the
channel, L1 pruned twins stay refused, L2 an unreadable registry keeps the Telegram buttons,
L3 taps run on their own pool. Plus: transport unset + no registry = Telegram exactly as today.
Run: FORGE_MARCUS=0 python3 -m unittest test_slack_hardening  (no network: telegram_io._api and
slack_io._api are faked; actions stubbed; state in temp dirs)."""
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock

if "slack_io" not in sys.modules:
    os.environ["FORGE_SLACK_CONFIG_DIR"] = tempfile.mkdtemp(prefix="slack_cfg_")

import slack_inbound  # noqa: E402
import slack_io  # noqa: E402
import telegram_io as tg  # noqa: E402
from test_slack_listener import Harness, Req  # noqa: E402  (helpers only, no TestCase)

OPERATOR, OWNER, STRANGER = "7001", "UOWNER1", "USTRANGE"
HQ, DAYCARE = "CHQ001", "CDAY01"
DAY = 86400


def slack_tap(value, card, channel=DAYCARE, user=OWNER):
    return {"type": "block_actions", "user": {"id": user}, "channel": {"id": channel},
            "trigger_id": uuid.uuid4().hex, "message": {"ts": "1.1", "blocks": []},
            "actions": [{"type": "button", "block_id": f"{card}#0", "value": value}]}


def tg_tap(data, message_id, cq_id=None):
    return {"id": cq_id or uuid.uuid4().hex, "from": {"id": OPERATOR}, "data": data,
            "message": {"message_id": message_id, "chat": {"id": OPERATOR}, "text": "card"}}


class ClaimHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = Path(self.tmp.name) / "slack_cards.json"
        self.ran, self.tg_calls, self.slack_calls = [], [], []
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("SLACK_", "TELEGRAM_")) and k != "FORGE_CHAT_TRANSPORT"}
        env.update({"TELEGRAM_BOT_TOKEN": "tgtok", "TELEGRAM_CHAT_ID": OPERATOR, "TELEGRAM_ALLOWED_IDS": "",
                    "SLACK_BOT_TOKEN": "xoxb-test", "SLACK_ALLOWED_USER_IDS": OWNER,
                    "FORGE_CHAT_TRANSPORT": "both"})
        self.patches = [
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
            mock.patch.object(tg, "STATE", Path(self.tmp.name) / "telegram.json"),
            mock.patch.object(slack_io, "_api", lambda m, t, **p: self.slack_calls.append((m, p)) or {"ok": True}),
            mock.patch.object(tg, "_api", lambda m, p, timeout=15, token=None:
                              self.tg_calls.append((m, p, token)) or {"ok": True}),
            mock.patch.object(tg, "_ACTIONS", {"approve": lambda a=None: self.ran.append(a) or {"ok": True}}),
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

    def twin(self, card, mid, at=None):
        if at is None:
            slack_io.register_card(card, DAYCARE, "1.1", [f"approve:{card}"], origin_chat=OPERATOR,
                                   tg_message_id=mid, tg_chat_id=OPERATOR)
            return
        with mock.patch.object(slack_io.time, "time", lambda: at):
            self.twin(card, mid)

    def tg_methods(self):
        return [m for m, _, _ in self.tg_calls]

    # ── transport unset, no registry: Telegram exactly as today ──────────────────
    def test_transport_unset_no_registry_telegram_unchanged(self):
        os.environ.pop("FORGE_CHAT_TRANSPORT")
        self.assertFalse(self.reg.exists())
        expected = [("answerCallbackQuery", {"callback_query_id": "q1", "text": "✅ Approved & sent"}, None),
                    ("editMessageText", {"chat_id": OPERATOR, "message_id": 77,
                                         "text": "card\n\n✅ Approved &amp; sent", "parse_mode": "HTML",
                                         "reply_markup": {"inline_keyboard": []}}, None)]
        with mock.patch.object(slack_io, "claim_for_telegram", side_effect=AssertionError("consulted")):
            for _ in range(2):                                    # a re-tap runs again, as today
                self.tg_calls.clear()
                tg._handle_callback(tg_tap("approve:p1", 77, "q1"))
                self.assertEqual(self.tg_calls, expected)
        self.assertEqual(self.ran, ["p1", "p1"])
        self.assertFalse(self.reg.exists())                      # nothing written
        self.assertEqual(self.slack_calls, [])

    # ── M1 rollback ────────────────────────────────────────────────────────────
    def test_rollback_to_telegram_mode_keeps_single_use(self):
        self.twin("c1", 42)
        self.twin("c2", 43)
        self.assertTrue(slack_io.handle_interaction(slack_tap("approve:c1", "c1"))["ok"])   # used in Slack
        self.assertEqual(self.ran, ["c1"])
        os.environ["FORGE_CHAT_TRANSPORT"] = "telegram"                                     # rollback
        # Telegram twin of the Slack-used card: still refused, buttons dropped.
        self.tg_calls.clear()
        tg._handle_callback(tg_tap("approve:c1", 42))
        self.assertEqual(self.ran, ["c1"])
        self.assertEqual(self.tg_calls[0][1]["text"], "Already handled in Slack")
        # Slack copy of an unused card: paused, nothing runs, nothing claimed.
        self.slack_calls.clear()
        out = slack_io.handle_interaction(slack_tap("approve:c2", "c2"))
        self.assertEqual(out, {"ok": False, "result": "paused"})
        self.assertEqual(self.slack_calls, [("chat.postEphemeral", {
            "channel": DAYCARE, "user": OWNER, "text": "Slack actions are paused. Tap it in Telegram."})])
        self.assertFalse(slack_io.get_card("c2")["consumed"])
        # Its Telegram twin runs (and claims the card)...
        tg._handle_callback(tg_tap("approve:c2", 43))
        self.assertEqual(self.ran, ["c1", "c2"])
        self.assertEqual(slack_io.get_card("c2")["consumedBy"], "telegram")
        # ...so after rolling forward again the Slack copy stays used.
        os.environ["FORGE_CHAT_TRANSPORT"] = "both"
        self.assertEqual(slack_io.handle_interaction(slack_tap("approve:c2", "c2"))["result"], "already handled")
        self.assertEqual(self.ran, ["c1", "c2"])
        # telegram mode, unmirrored card: runs, and no tombstone is written (no copy will come).
        os.environ["FORGE_CHAT_TRANSPORT"] = "telegram"
        tg._handle_callback(tg_tap("approve:x", 99))
        self.assertEqual(self.ran, ["c1", "c2", "x"])
        self.assertNotIn(f"tg:{OPERATOR}:99", slack_io._read("slack_cards.json"))

    def test_rollback_corrupt_registry_fails_closed(self):
        os.environ.pop("FORGE_CHAT_TRANSPORT")
        self.reg.write_text("{not json")
        tg._handle_callback(tg_tap("approve:p1", 42))
        self.assertEqual(self.ran, [])
        self.assertEqual(self.tg_methods(), ["answerCallbackQuery"])

    # ── L1 prune ───────────────────────────────────────────────────────────────
    def test_prune_after_ttl_keeps_consumed_marker(self):
        t0 = time.time()
        self.twin("used", 42, at=t0)
        self.twin("unused", 43, at=t0)
        with mock.patch.object(slack_io.time, "time", lambda: t0):
            slack_io.handle_interaction(slack_tap("approve:used", "used"))
        self.assertEqual(self.ran, ["used"])
        self.twin("fresh", 44, at=t0 + 8 * DAY)                                 # prunes both
        self.assertIsNone(slack_io.get_card("used"))
        self.assertIsNone(slack_io.get_card(f"tg:{OPERATOR}:42"))               # a marker is not a card
        with mock.patch.object(slack_io.time, "time", lambda: t0 + 8 * DAY):
            self.assertEqual(slack_io.claim_for_telegram(OPERATOR, 42), "taken")
            self.tg_calls.clear()
            tg._handle_callback(tg_tap("approve:used", 42))
            self.assertEqual(self.ran, ["used"])                                # not run again
            self.assertEqual(self.tg_methods(), ["answerCallbackQuery", "editMessageReplyMarkup"])
            tg._handle_callback(tg_tap("approve:unused", 43))                   # never used: free, runs
        self.assertEqual(self.ran, ["used", "unused"])
        # The marker lasts 90 days from the prune (day 8), then goes.
        self.twin("still", 46, at=t0 + 97 * DAY)
        with mock.patch.object(slack_io.time, "time", lambda: t0 + 97 * DAY):
            self.assertEqual(slack_io.claim_for_telegram(OPERATOR, 42), "taken")
        self.twin("later", 45, at=t0 + 99 * DAY)
        with mock.patch.object(slack_io.time, "time", lambda: t0 + 99 * DAY):
            self.assertEqual(slack_io.claim_for_telegram(OPERATOR, 42), "free")

    def test_prune_by_cap_keeps_marker_and_markers_are_capped(self):
        t0 = time.time()
        with mock.patch.object(slack_io, "_CARD_MAX", 2), mock.patch.object(slack_io, "_MARK_MAX", 2):
            for i in range(3):
                self.twin(f"u{i}", 50 + i, at=t0 + i)
                with mock.patch.object(slack_io.time, "time", lambda: t0 + i):
                    slack_io.handle_interaction(slack_tap(f"approve:u{i}", f"u{i}"))
            for i in range(3, 6):                                               # push u0..u2 out
                self.twin(f"n{i}", 60 + i, at=t0 + i)
            reg = slack_io._read("slack_cards.json")
            marks = sorted(k for k, v in reg.items() if v.get("tombstone") and v.get("consumed"))
            self.assertEqual(len(marks), 2)                                     # capped at _MARK_MAX
            self.assertLessEqual(sum(1 for v in reg.values() if not v.get("tombstone")), 2)
            self.assertTrue(any(slack_io.claim_for_telegram(OPERATOR, 50 + i) == "taken" for i in range(3)))

    # ── L2 unreadable registry ─────────────────────────────────────────────────
    def test_unreadable_registry_keeps_buttons_then_retry_works(self):
        self.reg.write_text("{not json")
        tg._handle_callback(tg_tap("approve:c1", 42))
        self.assertEqual(self.ran, [])
        self.assertEqual(self.tg_methods(), ["answerCallbackQuery"])           # no editMessageReplyMarkup
        self.assertIn("Try again in a moment", self.tg_calls[0][1]["text"])
        self.reg.unlink()                                                      # registry readable again
        self.twin("c1", 42)
        tg._handle_callback(tg_tap("approve:c1", 42))
        self.assertEqual(self.ran, ["c1"])
        with mock.patch.object(slack_io, "_read_strict", side_effect=OSError("io")):
            self.assertEqual(slack_io.claim_for_telegram(OPERATOR, 42), "unreadable")


class BindTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api = []
        self.info = {"is_private": True}
        self.members, self.fail = [OWNER, "UBOT"], set()
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_")}
        env.update({"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_ALLOWED_USER_IDS": OWNER})
        self.patches = [mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
                        mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(slack_io, "_api", self._fake_api)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _fake_api(self, method, token, **params):
        self.api.append(method)
        if method in self.fail:
            return {"ok": False, "error": "missing_scope"}
        if method == "conversations.info":
            return {"ok": True, "channel": dict(self.info, id=params["channel"])}
        if method == "auth.test":
            return {"ok": True, "user_id": "UBOT"}
        if method == "conversations.members":
            return {"ok": True, "members": list(self.members), "response_metadata": {"next_cursor": ""}}
        return {"ok": True}

    def bind(self, biz, channel="GPRIV01", user=OWNER):
        return slack_inbound.handle_slash({"command": "/forge", "text": f"bind {biz}",
                                           "user_id": user, "channel_id": channel})["text"]

    def refused(self, biz, channel="GPRIV01"):
        text = self.bind(biz, channel)
        self.assertIn("Bind refused", text)
        self.assertIsNone(slack_io.business_of(channel))
        self.assertNotIn("chat.postMessage", self.api)
        return text

    def test_public_channel_refused(self):
        self.info = {"is_private": False, "is_channel": True}
        self.assertIn("public", self.refused("daycare", "CPUB01"))
        self.assertIn("public", self.refused("hq", "CPUB01"))

    def test_shared_channel_refused(self):
        for flag in ("is_ext_shared", "is_shared", "is_org_shared", "is_pending_ext_shared"):
            self.info = {"is_private": True, flag: True}
            self.assertIn("shared", self.refused("daycare"), flag)

    def test_group_dm_refused(self):
        self.info = {"is_private": True, "is_mpim": True}
        self.assertIn("group DMs", self.refused("hq", "GMPIM01"))

    def test_hq_with_stranger_member_refused(self):
        self.members = [OWNER, "UBOT", STRANGER]
        self.assertIn("1 member(s)", self.refused("hq"))
        self.members = [OWNER, "UBOT"]                     # stranger removed: now fine
        self.assertIn("now *hq*", self.bind("hq"))

    def test_private_owner_only_channel_allowed(self):
        self.members = [OWNER]
        self.assertIn("now *hq*", self.bind("hq", "GHQ001"))
        self.assertEqual(slack_io.chat_for(None), "GHQ001")
        self.assertIn("now *daycare*", self.bind("daycare", "GDAY01"))
        self.assertEqual(slack_io.business_of("GDAY01"), "daycare")
        self.assertEqual(self.api, ["conversations.info", "auth.test", "conversations.members",
                                    "conversations.info"])          # members are checked for HQ only

    def test_api_error_fails_closed(self):
        for method in ("conversations.info", "auth.test", "conversations.members"):
            self.fail = {method}
            self.assertIn("missing_scope", self.refused("hq"), method)
        self.fail = set()
        with mock.patch.object(slack_io, "_api", lambda m, t, **p: {"ok": True, "members": [OWNER],
                                                                   "user_id": "UBOT",
                                                                   "channel": {"is_private": True},
                                                                   "response_metadata": {"next_cursor": "x"}}):
            self.refused("hq")                                 # more members than one page: refuse
        self.assertIn("Not authorized", self.bind("hq", user=STRANGER))


class TapPoolTests(unittest.TestCase):
    def setUp(self):
        slack_io._ENVELOPES.clear()
        self.patches = [mock.patch.object(slack_io, "_POLL", 0.01)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_blocked_message_workers_do_not_delay_a_tap(self):
        release, busy, tapped = threading.Event(), [], threading.Event()
        lock = threading.Lock()

        def slow_turn(ev):
            with lock:
                busy.append(threading.current_thread().name)
            release.wait(5)
        names = []

        def tap(payload, envelope_id=None):
            names.append(threading.current_thread().name)
            tapped.set()
        mod = types.SimpleNamespace(handle_message_event=slow_turn, handle_slash=lambda p: {})
        try:
            with mock.patch.dict(sys.modules, {"slack_inbound": mod}), \
                    mock.patch.object(slack_io, "handle_interaction", tap), Harness() as h:
                for i in range(5):                             # 4 workers busy + 1 queued
                    h.clients[0].feed(Req("events_api", f"M{i}", {"event_id": f"Ev{i}",
                                                                  "event": {"type": "message"}}))
                for _ in range(200):
                    if len(busy) == 4:
                        break
                    threading.Event().wait(0.01)
                self.assertEqual(len(busy), 4)
                h.clients[0].feed(Req("interactive", "T1", {"type": "block_actions", "trigger_id": "TR1"}))
                self.assertTrue(tapped.wait(2), "tap queued behind agent turns")
                self.assertEqual(len(busy), 4)                 # message workers still blocked
                self.assertTrue(names[0].startswith("slack-tap"))
                release.set()
        finally:
            release.set()


if __name__ == "__main__":
    unittest.main()
