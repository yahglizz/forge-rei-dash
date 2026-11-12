"""slack_io core: mrkdwn conversion, splitting, channel map, Block Kit, send, dedupe, redaction.
Run: FORGE_MARCUS=0 python3 -m unittest test_slack_io  (no network: _api is always faked;
STATE points at a temp dir, never the real marcus_state)."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

# Import slack_io against an EMPTY config dir so a real slack.env (if present) never loads.
if "slack_io" not in sys.modules:
    os.environ["FORGE_SLACK_CONFIG_DIR"] = tempfile.mkdtemp(prefix="slack_cfg_")

import slack_io  # noqa: E402
import telegram_io  # noqa: E402

DEFAULT_STATE = slack_io.STATE      # captured before any test patches it
REAL_API = slack_io._api


class SlackIoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []
        self.reply = {"ok": True, "channel": "CHQ001", "ts": "111.222"}
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_")}
        env.update({"SLACK_BOT_TOKEN": "xoxb-test-token", "FORGE_CHAT_TRANSPORT": "both"})
        self.patches = [
            mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(slack_io, "_api", self._fake_api),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _fake_api(self, method, token, **params):
        self.calls.append((method, token, params))
        return dict(self.reply)

    # ── formatting ────────────────────────────────────────────────────────────
    def test_to_mrkdwn_escapes_amp_lt_gt_and_converts_b_i_code_a(self):
        html = ('<b>Hot lead</b> · <i>Jane &amp; Co</i> <code>x &lt; 5 &gt; 2</code> '
                '<a href="https://ex.com/a?x=1&amp;y=2">open</a> raw < & >')
        md = slack_io.to_mrkdwn(html)
        self.assertIn("*Hot lead*", md)
        self.assertIn("_Jane &amp; Co_", md)
        self.assertIn("`x &lt; 5 &gt; 2`", md)
        self.assertIn("<https://ex.com/a?x=1&y=2|open>", md)
        self.assertTrue(md.endswith("raw &lt; &amp; &gt;"))
        self.assertNotIn("<b>", md)
        # Unknown tag-looking text is kept as escaped text, not dropped.
        self.assertEqual(slack_io.to_mrkdwn("a <foo> b"), "a &lt;foo&gt; b")
        self.assertEqual(slack_io.to_mrkdwn("line1<br>line2"), "line1\nline2")
        self.assertEqual(slack_io.to_mrkdwn(None), "")

    def test_split_text_never_exceeds_limit_and_preserves_content(self):
        para = ("word " * 300 + "\n") * 12                 # ~18k chars, newlines + spaces
        nospace = "x" * 7000                                # no break points at all
        for text, limit in ((para, 2900), (nospace, 2900), (para, 100), ("short", 2900)):
            chunks = slack_io.split_text(text, limit)
            self.assertEqual("".join(chunks), text)
            self.assertTrue(all(0 < len(c) <= limit for c in chunks))
        self.assertEqual(slack_io.split_text(""), [])
        # Prefers a newline break over a mid-word cut.
        self.assertTrue(slack_io.split_text(para, 2900)[0].endswith("\n"))

    # ── channels ──────────────────────────────────────────────────────────────
    def test_chat_for_falls_back_to_hq_then_none(self):
        self.assertIsNone(slack_io.chat_for("daycare"))
        self.assertIsNone(slack_io.chat_for(None))
        slack_io.bind("hq", "CHQ001")
        self.assertEqual(slack_io.chat_for("daycare"), "CHQ001")
        self.assertEqual(slack_io.chat_for(None), "CHQ001")
        slack_io.bind("Daycare", "CDAY01")
        self.assertEqual(slack_io.chat_for("daycare"), "CDAY01")
        self.assertEqual(slack_io.chat_for("agency"), "CHQ001")
        with self.assertRaises(ValueError):
            slack_io.bind("dedupe", "CX0001")
        with self.assertRaises(ValueError):
            slack_io.bind("daycare", "")
        # Test-only routing sends everything to the test channel.
        with mock.patch.dict(os.environ, {"SLACK_ONLY_TEST": "1", "SLACK_TEST_CHANNEL_ID": "CTEST1"}):
            self.assertEqual(slack_io.chat_for("daycare"), "CTEST1")
            self.assertEqual(slack_io.chat_for(None), "CTEST1")

    # ── Block Kit ─────────────────────────────────────────────────────────────
    def test_render_blocks_one_button_per_callback_value_len_le_64(self):
        buttons = [[{"text": "✅ Approve & send", "callback_data": "approve:p1"},
                    {"text": "Dismiss", "callback_data": "mdismiss:p1"}],
                   [{"text": "too long", "callback_data": "x:" + "y" * 80}],
                   [{"text": "Hand to Marcus", "callback_data": "handoff:c9"}]]
        blocks = slack_io.render_blocks("hello *there*", buttons, "card1")
        self.assertEqual(blocks[0], {"type": "section", "text": {"type": "mrkdwn", "text": "hello *there*"}})
        actions = [b for b in blocks if b["type"] == "actions"]
        elems = [e for b in actions for e in b["elements"]]
        self.assertEqual([e["value"] for e in elems], ["approve:p1", "mdismiss:p1", "handoff:c9"])
        for e in elems:
            self.assertEqual(e["type"], "button")
            self.assertEqual(e["action_id"], e["value"])
            self.assertLessEqual(len(e["value"].encode()), 64)
        self.assertEqual(len({b["block_id"] for b in actions}), len(actions))
        self.assertTrue(all(b["block_id"].startswith("card1") for b in actions))
        # Long text becomes several sections, each within Slack's 3000-char limit.
        many = slack_io.render_blocks("a" * 7000, None, None)
        self.assertGreaterEqual(len(many), 3)
        self.assertTrue(all(len(b["text"]["text"]) <= 3000 for b in many))

    # ── send ──────────────────────────────────────────────────────────────────
    def test_send_uses_stubbed_api_and_returns_false_on_slack_error_without_raising(self):
        slack_io.bind("hq", "CHQ001")
        self.assertTrue(slack_io.send("<b>hi</b> & bye", business="daycare"))
        method, token, params = self.calls[-1]
        self.assertEqual((method, token, params["channel"]), ("chat.postMessage", "xoxb-test-token", "CHQ001"))
        self.assertEqual(params["text"], "*hi* &amp; bye")              # text fallback always present
        self.assertIsInstance(params["blocks"], list)
        self.reply = {"ok": False, "error": "channel_not_found"}
        self.assertFalse(slack_io.send("x"))

        def boom(*a, **k):
            raise RuntimeError("socket died")
        with mock.patch.object(slack_io, "_api", boom):
            self.assertFalse(slack_io.send("x"))

    def test_send_inert_in_telegram_mode_and_without_channel(self):
        slack_io.bind("hq", "CHQ001")
        with mock.patch.dict(os.environ, {"FORGE_CHAT_TRANSPORT": "telegram"}):
            self.assertFalse(slack_io.send("x"))
        os.environ.pop("FORGE_CHAT_TRANSPORT")
        self.assertEqual(slack_io.mode(), "telegram")
        self.assertFalse(slack_io.send("x"))
        os.environ["FORGE_CHAT_TRANSPORT"] = "nonsense"
        self.assertEqual(slack_io.mode(), "telegram")
        self.assertEqual(self.calls, [])
        os.environ["FORGE_CHAT_TRANSPORT"] = "slack"
        with mock.patch.dict(os.environ, {"SLACK_BOT_TOKEN": ""}):
            self.assertFalse(slack_io.send("x"))
        self.assertEqual(self.calls, [])

    def test_send_dedupes_same_key_within_900s(self):
        slack_io.bind("hq", "CHQ001")
        self.reply = {"ok": False, "error": "ratelimited"}
        self.assertFalse(slack_io.send("a", dedupe_key="k1"))          # failure does not commit
        self.reply = {"ok": True, "channel": "CHQ001", "ts": "1.2"}
        self.assertTrue(slack_io.send("a", dedupe_key="k1"))
        self.assertTrue(slack_io.send("a", dedupe_key="k1"))           # skipped, still "delivered"
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(slack_io.send("a", dedupe_key="k2"))
        self.assertEqual(len(self.calls), 3)
        later = time.time() + 901
        with mock.patch.object(slack_io.time, "time", lambda: later):
            self.assertTrue(slack_io.send("a", dedupe_key="k1"))
        self.assertEqual(len(self.calls), 4)

    def test_long_text_and_buttons_register_one_card(self):
        slack_io.bind("daycare", "CDAY01")
        self.reply = {"ok": True, "channel": "CDAY01", "ts": "9.9"}
        btn = [[{"text": "Do it", "callback_data": "opsgo:t1"}]]
        self.assertTrue(slack_io.send("z" * 9000, business="daycare", buttons=btn))
        self.assertEqual(len(self.calls), 1)                            # one message, many sections
        blocks = self.calls[0][2]["blocks"]
        card_id = blocks[-1]["block_id"].split("#")[0]
        card = slack_io.get_card(card_id)
        self.assertEqual((card["channel"], card["ts"], card["actions"]), ("CDAY01", "9.9", ["opsgo:t1"]))
        self.assertIsNone(slack_io.get_card("nope"))

    def test_send_photo_url_image_block_then_text_fallback(self):
        slack_io.bind("hq", "CHQ001")
        self.assertTrue(slack_io.send_photo("https://img.example/a.png", "<b>Ad 1</b>"))
        blocks = self.calls[-1][2]["blocks"]
        self.assertEqual(blocks[0]["type"], "image")
        self.assertEqual(blocks[0]["image_url"], "https://img.example/a.png")
        replies = iter([{"ok": False, "error": "invalid_blocks"}, {"ok": True, "channel": "CHQ001", "ts": "3.4"}])
        with mock.patch.object(slack_io, "_api", lambda m, t, **p: self.calls.append((m, t, p)) or next(replies)):
            self.assertTrue(slack_io.send_photo("https://img.example/b.png", "cap", dedupe_key="ph"))
        self.assertIn("<https://img.example/b.png|Image>", self.calls[-1][2]["text"])
        self.assertFalse(any(b["type"] == "image" for b in self.calls[-1][2]["blocks"]))

    # ── secrets + state ───────────────────────────────────────────────────────
    def test_redact_covers_xoxb_xoxp_xapp(self):
        s = "err xoxb-123-456-abcDEF and xoxp-9-8-7-zz and xapp-1-A0-123-ff00 end"
        for red in (telegram_io._redact, slack_io._redact):
            out = red(s)
            for tok in ("xoxb-123", "xoxp-9", "xapp-1"):
                self.assertNotIn(tok, out)
            self.assertTrue(out.startswith("err ") and out.endswith(" end"))
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:TGSECRET"}):
            self.assertEqual(telegram_io._redact("bot123:TGSECRET/x"), "bot***/x")
        # _api never raises and redacts the token from transport errors.
        with mock.patch.object(slack_io.requests, "post", side_effect=OSError("boom Bearer xoxb-test-token")):
            res = REAL_API("auth.test", "xoxb-test-token")
        self.assertFalse(res["ok"])
        self.assertNotIn("xoxb-test-token", res["error"])

    def test_state_file_is_slack_json_not_telegram_json(self):
        self.assertEqual(DEFAULT_STATE, telegram_io.STATE.parent)       # same marcus_state dir
        slack_io.bind("hq", "CHQ001")
        slack_io.send("x", dedupe_key="k", buttons=[[{"text": "ok", "callback_data": "a:b"}]])
        names = sorted(p.name for p in Path(self.tmp.name).iterdir())
        self.assertEqual(names, ["slack.json", "slack_cards.json"])
        data = json.loads((Path(self.tmp.name) / "slack.json").read_text())
        self.assertEqual(data["hq"], "CHQ001")
        self.assertIn("k", data["dedupe"])


if __name__ == "__main__":
    unittest.main()
