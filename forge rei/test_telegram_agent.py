"""Business partners in Telegram: tool loop, ✅-gated writes, scope, zero-Claude commands.
Run: python3 test_telegram_agent.py  (no network: Claude + loopback HTTP are faked)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import telegram_agent as ta
import telegram_io as tg


SRC = '''
ROUTES = {"/api/system/health": 1, "/api/cost/status": 1, "/api/scout/leads": 1}
def do_POST(self):
    if p in ("/api/agency/reset", "/api/marcus/approve"):
        pass
def _handle_daycare_post(self, path):
    handlers = {"/api/daycare/guardian/reset-pin": daycare_supabase.reset_credentials,
                "/api/daycare/child/save": daycare_supabase.save_child,
                "/api/daycare/auth/login": x}
def _handle_daycare_get(self, path, q):
    if path == "/api/daycare/children": pass
    elif path == "/api/daycare/staff": pass
    elif path == "/api/daycare/starts": pass
'''


TMP = tempfile.TemporaryDirectory()
TMP_SRC = Path(TMP.name) / "connector_fixture.py"
TMP_SRC.write_text("class H:\n" + "\n".join("    " + ln for ln in SRC.split("\n", 2)[2].splitlines()))


class PartnerTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("connector_fixture", TMP_SRC)
        mod = importlib.util.module_from_spec(spec)
        mod.daycare_supabase = mod.x = None
        spec.loader.exec_module(mod)
        routes = {"/api/system/health": 1, "/api/cost/status": 1, "/api/scout/leads": 1}
        self.state = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(ta, "STATE", Path(self.state.name) / "p.json"),
                        mock.patch.object(ta, "_source", lambda: SRC)]
        for p in self.patches:
            p.start()
        ta.register(7799, routes, mod.H, TMP_SRC)
        self.http = []
        self.p_http = mock.patch.object(ta, "_http", self._fake_http)
        self.p_http.start()

    def tearDown(self):
        self.p_http.stop()
        for p in reversed(self.patches):
            p.stop()
        self.state.cleanup()

    def _fake_http(self, method, path, query=None, body=None, timeout=90):
        self.http.append((method, path, body))
        if path == "/api/daycare/children":
            return {"ok": True, "children": [
                {"first_name": "Mia", "last_name": "Peterson", "guardian_profile_id": "g-1",
                 "guardian": {"display_name": "Seara Peterson", "login_id": "SP-1234"}}]}
        if path == "/api/daycare/staff":
            return {"ok": True, "staff": []}
        if path == "/api/daycare/guardian/reset-pin":
            return {"ok": True, "provision": {"login_id": "SP-1234", "pin": "482913"}}
        return {"ok": True}

    def test_catalog_and_scope(self):
        cat = ta.catalog()
        self.assertIn("/api/daycare/guardian/reset-pin", cat["POST"])
        self.assertIn("/api/daycare/children", cat["GET"])
        self.assertTrue(ta.allowed("daycare", "GET", "/api/daycare/children")[0])
        self.assertFalse(ta.allowed("daycare", "GET", "/api/scout/leads")[0])      # other biz
        self.assertFalse(ta.allowed("agency", "POST", "/api/agency/reset")[0])     # denied
        self.assertFalse(ta.allowed("daycare", "POST", "/api/daycare/auth/login")[0])
        self.assertFalse(ta.allowed("daycare", "POST", "/api/daycare/children")[0])  # GET-only
        self.assertTrue(ta.allowed("hq", "GET", "/api/cost/status")[0])
        self.assertFalse(ta.allowed("hq", "GET", "/api/daycare/children")[0])

    def _claude_script(self, steps):
        calls = []

        def call(key, payload):
            calls.append(__import__("copy").deepcopy(payload))
            return steps[len(calls) - 1]
        return call, calls

    def test_get_runs_post_queues_tap_runs_once(self):
        call, calls = self._claude_script([
            {"content": [{"type": "tool_use", "id": "t1", "name": "api_get",
                          "input": {"path": "/api/daycare/children"}}],
             "stop_reason": "tool_use"},
            {"content": [{"type": "tool_use", "id": "t2", "name": "api_post",
                          "input": {"path": "/api/daycare/guardian/reset-pin",
                                    "body": {"profile_id": "g-1"},
                                    "summary": "Reset PIN for Seara Peterson"}}],
             "stop_reason": "tool_use"},
            {"content": [{"type": "text", "text": "Card's up — tap ✅."}],
             "stop_reason": "end_turn"},
        ])
        with mock.patch.object(ta, "system_prompt", lambda a, b: "sys"):
            out = ta.chat("solomon", "reset seara's pin", [], "-100", key="k", call=call)
        self.assertEqual(out["reply"], "Card's up — tap ✅.")
        self.assertEqual(len(out["cards"]), 1)
        self.assertEqual([h[:2] for h in self.http], [("GET", "/api/daycare/children")])
        self.assertEqual(calls[1]["messages"][-1]["content"][0]["type"], "tool_result")
        tok = out["cards"][0]["tok"]
        res = ta.confirm(tok)
        self.assertTrue(res.get("ok"))
        self.assertIn("482913", res["message"])                   # PIN shown once in the tap
        self.assertEqual(self.http[-1][:2], ("POST", "/api/daycare/guardian/reset-pin"))
        self.assertIn("expired", ta.confirm(tok)["error"])         # single use
        text, buttons = ta.card(out["cards"][0])
        self.assertEqual(buttons[0][0]["callback_data"], f"pgo:{tok}")

    def test_out_of_scope_tool_is_refused(self):
        call, _ = self._claude_script([
            {"content": [{"type": "tool_use", "id": "t1", "name": "api_post",
                          "input": {"path": "/api/marcus/approve", "body": {}, "summary": "x"}}],
             "stop_reason": "tool_use"},
            {"content": [{"type": "text", "text": "That's wholesale."}], "stop_reason": "end_turn"},
        ])
        with mock.patch.object(ta, "system_prompt", lambda a, b: "sys"):
            out = ta.chat("solomon", "approve marcus draft", [], "-100", key="k", call=call)
        self.assertEqual(out["cards"], [])
        self.assertEqual(self.http, [])

    def test_claude_down_says_why(self):
        def boom(key, payload):
            raise RuntimeError("Anthropic API error (400): credit balance is too low")
        with mock.patch.object(ta, "system_prompt", lambda a, b: "sys"):
            out = ta.chat("solomon", "hi", [], "-100", key="k", call=boom)
        self.assertIn("credit balance", out["reply"])
        self.assertIn("/logins", out["reply"])

    def test_quick_commands_without_claude(self):
        text, cards = ta.quick("/logins", "seara", "-100", "daycare")
        self.assertIn("SP-1234", text)
        text, cards = ta.quick("/pin", "peterson", "-100", "daycare")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["body"], {"profile_id": "g-1"})
        text, _ = ta.quick("/pin", "seara", "-100", "wholesale")
        self.assertIn("Daycare chat", text)
        self.assertIsNone(ta.quick("/hot", "", "-100", "daycare"))

    def test_history_alternates(self):
        msgs = ta._messages([{"role": "assistant", "text": "hey"},
                             {"role": "user", "text": "a"}, {"role": "user", "text": "b"},
                             {"role": "assistant", "text": "c"}], "d")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])


OPERATOR, DAYCARE = "7001", "-100555"


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(tg, "STATE", Path(self.tmp.name) / "telegram.json"),
            mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": OPERATOR,
                                         "TELEGRAM_ALLOWED_IDS": ""}),
            mock.patch.object(tg, "_api", lambda *a, **k: {"ok": True}),
        ]
        for p in self.patches:
            p.start()
        for b in tg.BUSINESSES:
            os.environ.pop(f"TELEGRAM_CHAT_{b.upper()}", None)
        self.replies = []
        self.p_send = mock.patch.object(tg, "_send_to", lambda c, t, **k: self.replies.append((c, t, k.get("buttons"))) or {"ok": True})
        self.p_send.start()
        tg._AGENT_SESS.clear()
        self.seen = []
        self.p_chat = mock.patch.object(ta, "chat", lambda aid, text, hist, chat_id: self.seen.append((aid, text)) or {"reply": f"{aid} ok", "cards": []})
        self.p_chat.start()
        self.p_hist = mock.patch.dict("sys.modules", {"agents_history": mock.MagicMock()})
        self.p_hist.start()

    def tearDown(self):
        for p in (self.p_hist, self.p_chat, self.p_send):
            p.stop()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def msg(self, text, chat=DAYCARE):
        tg._handle_message({"chat": {"id": int(chat), "type": "supergroup"},
                            "from": {"id": int(OPERATOR)}, "text": text})

    def test_daycare_chat_goes_to_solomon_not_ops(self):
        self.msg("/bind daycare")
        with mock.patch("telegram_ops.route", side_effect=AssertionError("ops ran")):
            self.msg("find Seara and reset her pin")
        self.assertEqual(self.seen[-1][0], "solomon")

    def test_foreign_agent_refused_in_business_chat(self):
        self.msg("/bind daycare")
        self.msg("marcus, how are sellers")
        self.assertIn("own chat", self.replies[-1][1])
        self.assertEqual(self.seen, [])

    def test_hq_defaults_to_orion(self):
        with mock.patch("telegram_ops.route", return_value=False):
            self.msg("what's broken?", chat=OPERATOR)
        self.assertEqual(self.seen[-1][0], "orion")

    def test_cards_sent_with_buttons(self):
        self.msg("/bind daycare")
        tg._AGENT_SESS.clear()
        with mock.patch.object(ta, "chat", lambda *a: {"reply": "tap it", "cards": [
                {"tok": "abc", "agent": "solomon", "path": "/api/daycare/guardian/reset-pin",
                 "body": {"profile_id": "g"}, "summary": "Reset PIN"}]}):
            self.msg("reset pin")
        self.assertEqual(self.replies[-1][2][0][0]["callback_data"], "pgo:abc")


if __name__ == "__main__":
    unittest.main()
