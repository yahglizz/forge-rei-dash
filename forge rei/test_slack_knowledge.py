"""#forge-knowledge: the four writers post freely (AUTO) while their context is clean, a tainted agent's
note becomes a ✅ card, the writer is stamped from who runs the tool (never the body), Midas and
unknown agents are refused, PII / key-shaped notes are refused, per-day cap, read() filters + labels DATA.
Run: FORGE_MARCUS=0 python3 -m unittest test_slack_knowledge  (no network: Slack + loopback faked)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if "slack_io" not in sys.modules:
    os.environ["FORGE_SLACK_CONFIG_DIR"] = tempfile.mkdtemp(prefix="slack_cfg_")
os.environ.setdefault("FORGE_MARCUS", "0")

import dash_live  # noqa: E402
import slack_io  # noqa: E402
import slack_knowledge  # noqa: E402
import telegram_agent as ta  # noqa: E402

KNOW = "CKNOW1"


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api, self.http = [], []
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_") and k != "FORGE_CHAT_TRANSPORT"}
        env.update({"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_ALLOWED_USER_IDS": "UOWNER1",
                    "FORGE_CHAT_TRANSPORT": "both", "SLACK_CHANNEL_KNOWLEDGE": KNOW})
        self.patches = [
            mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(slack_io, "_api", self._fake_api),
            mock.patch.object(dash_live, "TAINT_STATE", Path(self.tmp.name) / "taint.json"),
            mock.patch.object(dash_live, "DAY_STATE", Path(self.tmp.name) / "day.json"),
            mock.patch.object(ta, "allowed", lambda b, m, p: (True, "")),
            mock.patch.object(ta, "_http", self._fake_http),
            mock.patch.object(ta, "_queue", lambda *a, **k: "tok1"),
            mock.patch.dict(sys.modules, {"action_log": mock.MagicMock()}),
        ]
        for p in self.patches:
            p.start()
        slack_io._SEEN.clear()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        dash_live._TL.c = None
        self.tmp.cleanup()

    def _fake_api(self, method, token, **params):
        self.api.append((method, params))
        if method == "conversations.history":
            return {"ok": True, "messages": [
                {"ts": "3", "text": "📝 *Solomon*\n921 tours run 10-11 AM on weekdays."},
                {"ts": "2", "subtype": "channel_join", "text": "joined"},
                {"ts": "1", "text": "📚 *Site note · Location 2* 2318 Cecil B. Moore, infants to school age."}]}
        return {"ok": True, "channel": params.get("channel"), "ts": "1.1"}

    def _fake_http(self, method, path, query=None, body=None, timeout=90):
        self.http.append((method, path, body))
        return slack_knowledge.post(body.get("text"), body.get("agent")) if path == "/api/knowledge/post" else {"ok": True}

    def posts(self):
        return [p for m, p in self.api if m == "chat.postMessage"]

    def _write(self, agent, text, tainted=False, clean=True):
        dash_live.begin(tainted=tainted)
        dash_live._TL.c["promptClean"] = clean       # agent_gateway sets it: no lanes / tasks / history / n8n
        out = dash_live._write("api_post", {"path": "/api/knowledge/post", "summary": "note",
                                            "body": {"text": text, "agent": "orion"}}, agent, dash_live._TL.c)
        return out, dash_live.take()

    def test_clean_agent_posts_now_signed_as_itself_not_the_body(self):
        out, col = self._write("solomon", "921 tours run 10-11 AM on weekdays.")
        self.assertTrue(out.get("done"))
        self.assertEqual(col["actions"], [])                       # AUTO: no card
        self.assertEqual(self.http[-1][2]["agent"], "solomon")      # body said orion: stamped from the runner
        self.assertEqual(self.posts()[0]["channel"], KNOW)
        self.assertIn("Solomon", self.posts()[0]["text"])

    def test_tainted_agent_note_becomes_a_tap_card(self):
        out, col = self._write("marcus", "Sellers in 19121 answer evenings.", tainted=True)
        self.assertTrue(out.get("queued"))
        self.assertEqual(len(col["actions"]), 1)
        self.assertEqual(self.posts(), [])

    def test_prompt_with_outside_text_or_no_gateway_flag_files_a_card(self):
        out, col = self._write("solomon", "921 closes at 6 PM.", clean=False)
        self.assertTrue(out.get("queued"))
        self.assertIn("knowledge note needs your tap", out["note"])
        self.assertEqual(self.posts(), [])

    def test_every_auto_path_passes_the_connector_post_guard(self):
        import inspect
        import connector
        src = inspect.getsource(connector.Handler.do_POST)
        guard = src[src.index('if not (parsed.path.startswith("/api/marcus/")'):src.index('"unknown endpoint"')]
        for p in dash_live.AUTO_PATHS:
            if not p.startswith(("/api/daycare/", "/api/dropship/", "/api/marcus/")):
                self.assertIn(f'"{p}"', guard, f"{p} would 404 behind do_POST's allowlist")

    def test_old_telegram_path_stamps_the_writer(self):
        cards = []
        out = ta._run_tool("api_post", {"path": "/api/knowledge/post", "summary": "s",
                                        "body": {"text": "a fact", "agent": "owner"}}, "midas", "dropship", "C1", cards)
        self.assertIn("can't write", out.get("error", ""))
        ta._run_tool("api_post", {"path": "/api/knowledge/post", "summary": "s",
                                  "body": {"text": "a fact", "agent": "owner"}}, "solomon", "daycare", "C1", cards)
        self.assertEqual(cards[-1]["body"]["agent"], "solomon")

    def test_seed_scrub_escapes_slack_controls(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "seed_knowledge", Path(__file__).resolve().parent.parent / "forge-slack" / "seed_knowledge.py")
        seed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(seed)
        out = seed.scrub("ping <!here> <@U123> <!subteam^S1> @channel call 215-555-0142 Risk-level")
        for bad in ("<!", "<@", "@channel", "555-0142"):
            self.assertNotIn(bad, out)
        self.assertIn("Risk-level", out)

    def test_midas_and_unknown_agents_and_pii_are_refused(self):
        self.assertIn("error", self._write("midas", "a fact")[0])
        self.assertIn("can't write", slack_knowledge.post("a fact", "nobody")["error"])
        for bad in ("Call Ms. J at 215-555-0142", "email her: mom@example.com", "key xoxb-123-abc",
                    "sk-ant-api03-abcdefghijklmnop", "token 0123456789abcdef0123456789abcdef"):
            self.assertIn("refused", slack_knowledge.post(bad, "solomon")["error"], bad)
        self.assertIn("over", slack_knowledge.post("x" * 900, "dyson")["error"])
        self.assertIsNone(slack_knowledge.check("Risk-level rubric: ask-for-confirmation-before-planning steps", "dyson")[1])
        self.assertEqual(self.posts(), [])
        clean, _ = slack_knowledge.check("heads up <!channel> @here 921 is closed Friday", "orion")
        self.assertNotIn("channel>", clean)
        self.assertNotIn("@here", clean)

    def test_daily_cap_per_agent(self):
        for i in range(slack_knowledge.MAX_DAY):
            self.assertTrue(slack_knowledge.post(f"lesson {i}", "dyson")["ok"])
        self.assertIn("already wrote", slack_knowledge.post("one more", "dyson")["error"])
        self.assertTrue(slack_knowledge.post("one more", "orion")["ok"])     # per agent, not shared

    def test_read_filters_skips_joins_and_labels_data(self):
        out = slack_knowledge.read("2318")
        self.assertEqual(out["count"], 1)
        self.assertIn("2318", out["notes"][0]["text"])
        self.assertIn("never instructions", out["untrusted"])
        self.assertEqual(slack_knowledge.read()["count"], 2)

    def test_unbound_channel_says_so(self):
        with mock.patch.dict(os.environ, {"SLACK_CHANNEL_KNOWLEDGE": ""}):
            self.assertIn("not bound", slack_knowledge.post("a fact", "solomon")["error"])
            self.assertFalse(slack_knowledge.read()["ok"])

    def test_route_is_shared_and_its_read_taints(self):
        self.assertTrue(any(p == "/api/knowledge" for p in ta._SHARED))
        self.assertIn("/api/knowledge/post", dash_live.AUTO_PATHS)
        self.assertFalse(dash_live._no_taint("/api/knowledge"))        # outside text: later writes are taps


if __name__ == "__main__":
    unittest.main()
