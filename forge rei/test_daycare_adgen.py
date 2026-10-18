"""test_daycare_adgen.py — the daycare Ad Generator (2026-10-17).

Engine selection (REST pool vs the Higgsfield CLI on app credits), REST-403 caching + CLI
fallback, CLI output parsing against a FAKE `hf` shim, the daily credit cap + Unknown-cost
gate, ledger atomicity, concept-prompt order, concept JSON robustness, route wiring.
No network, no real Higgsfield binary, no Meta write.

Run: cd "forge rei" && python3 test_daycare_adgen.py
"""
import ast
import io
import json
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import higgsfield_io as hf  # noqa: E402
import daycare_ads_studio as studio  # noqa: E402

_SHIM = r'''#!{py}
import json, os, sys
from pathlib import Path
mode = os.environ.get("FAKE_HF_MODE", "ok")
state = Path(os.environ["FAKE_HF_STATE"])
args = sys.argv[1:]
with open(str(state) + ".log", "a") as f:
    f.write(json.dumps(args) + "\n")
bal = float(state.read_text()) if state.exists() else 100.0
if args[:1] == ["version"]:
    print("higgsfield 1.2.2 (fake)"); sys.exit(0)
if mode == "noworkspace" and args[:1] != ["workspace"]:
    print("Error: No workspace selected.\nHint: Run: hf workspace set <workspace_id>", file=sys.stderr); sys.exit(4)
if mode == "nologin":
    print("Error: request failed (no response received)\nHint: Run: hf auth login", file=sys.stderr); sys.exit(4)
if args[:2] == ["account", "status"]:
    print(json.dumps({{"credits": bal, "email": "owner@example.test", "subscription_plan_type": "plus"}})); sys.exit(0)
if args[:2] == ["workspace", "status"]:
    print(json.dumps({{"id": "ws_fake", "name": None, "plan_type": "plus", "credits": bal, "is_selected": True}})); sys.exit(0)
if args[:2] == ["generate", "cost"]:
    print("cost: ???" if mode == "badcost" else json.dumps({{"credits": 0.5}}, indent=2)); sys.exit(0)
if args[:2] == ["generate", "create"]:
    state.write_text(str(bal - 0.5))
    if mode == "badcreate":
        print("done!"); sys.exit(0)
    # the verified real shape: a JSON array of jobs, thumbnail key BEFORE result_url
    print(json.dumps([{{"created_at": "2026-10-18T01:40:21Z", "display_name": "GPT Image 2.5", "id": "job1",
                       "job_type": args[2], "min_result_url": "https://cdn.example.test/img1_min.webp",
                       "params": {{"prompt": "x", "quality": "medium"}}, "result_url": "https://cdn.example.test/img1.png",
                       "status": "completed"}}], indent=2))
    sys.exit(0)
print("unknown", file=sys.stderr); sys.exit(2)
'''


def _no_net(*a, **k):
    raise AssertionError("real network call attempted in a test")


class Base(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="adgen-test-"))
        shim = self.td / "hf"
        shim.write_text(_SHIM.format(py=sys.executable))
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        self.shim, self.state = shim, self.td / "hfstate"
        env = {k: "" for k in ("HIGGSFIELD_API_KEY", "HIGGSFIELD_API_SECRET", "HIGGSFIELD_CLI_BIN",
                               "HIGGSFIELD_REST_CREDITS_PER_IMAGE", "HIGGSFIELD_DAILY_CREDITS")}
        env.update(FAKE_HF_STATE=str(self.state), FAKE_HF_MODE="ok", PATH="/usr/bin:/bin")
        for p in (mock.patch.dict(os.environ, env),
                  mock.patch.object(hf, "LEDGER", self.td / "ledger.json"),
                  mock.patch.object(hf, "_scan_env_files", return_value=""),
                  mock.patch.object(studio, "STORE", self.td / "ideas.json"),
                  mock.patch.object(studio, "_daycare_env", return_value={}),
                  mock.patch.object(urllib.request, "urlopen", _no_net),
                  mock.patch.object(socket.socket, "connect", _no_net)):
            p.start()
            self.addCleanup(p.stop)
        hf._CLI_CACHE.update(at=0.0, val=None)

    def cli_on(self, mode="ok"):
        os.environ["HIGGSFIELD_CLI_BIN"] = str(self.shim)
        os.environ["FAKE_HF_MODE"] = mode
        hf._CLI_CACHE.update(at=0.0, val=None)

    def rest_on(self):
        os.environ["HIGGSFIELD_API_KEY"] = "kid"
        os.environ["HIGGSFIELD_API_SECRET"] = "ksecret"

    def calls(self):
        p = Path(str(self.state) + ".log")
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def creates(self):
        return [c for c in self.calls() if c[:2] == ["generate", "create"]]


class EngineSelection(Base):
    def test_rest_funded_wins(self):
        self.rest_on()
        hf.mark_rest("ok")
        self.assertEqual(hf.engine(), "rest")
        self.assertTrue(hf.status()["ready"])

    def test_rest_empty_falls_to_cli(self):
        self.rest_on()
        hf.mark_rest("empty", "HTTP 403: Not enough credits")
        self.cli_on()
        st = hf.status()
        self.assertEqual(st["engine"], "cli")
        self.assertIs(st["rest"]["funded"], False)
        self.assertEqual(st["cli"]["credits"], 100.0)
        self.assertEqual(st["cli"]["model"], "gpt_image_2_5")
        self.assertEqual(st["cli"]["workspace"], "ws_fake")

    def test_neither(self):
        st = hf.status()
        self.assertEqual(st["engine"], "none")
        self.assertFalse(st["ready"])
        self.assertIn("Install the Higgsfield CLI", st["nextStep"])

    def test_rest_empty_and_cli_needs_login(self):
        self.rest_on()
        hf.mark_rest("empty", "403")
        self.cli_on("noworkspace")
        st = hf.status()
        self.assertEqual(st["engine"], "none")
        self.assertTrue(st["cli"]["needsWorkspace"])
        self.assertIsNone(st["cli"]["loggedIn"])          # Unknown, never assumed
        self.assertIn("higgsfield auth login", st["nextStep"])
        self.assertIn("workspace set", st["nextStep"])
        self.assertIn("top up the Higgsfield API credits", st["nextStep"])

    def test_cli_not_logged_in(self):
        self.cli_on("nologin")
        st = hf.status()
        self.assertIs(st["cli"]["loggedIn"], False)
        self.assertIn("higgsfield auth login", st["nextStep"])

    def test_wrong_hf_binary_is_not_trusted(self):
        bad = self.td / "otherhf"
        bad.write_text("#!/bin/sh\necho huggingface-cli 0.1\n")
        bad.chmod(0o755)
        os.environ["HIGGSFIELD_CLI_BIN"] = str(bad)
        st = hf.cli_status(fresh=True)
        self.assertFalse(st["installed"])
        self.assertFalse(st["ready"])


class RestFallback(Base):
    def _403(self, *a, **k):
        self.rest_calls += 1
        raise urllib.error.HTTPError("https://x", 403, "Forbidden", {},
                                     io.BytesIO(b'{"detail":"Not enough credits"}'))

    def test_403_is_cached_and_falls_back_to_cli(self):
        self.rest_on()
        self.cli_on()
        os.environ["HIGGSFIELD_REST_CREDITS_PER_IMAGE"] = "2"      # REST cost known → REST tried first
        self.rest_calls = 0
        with mock.patch.object(hf, "_http_json", self._403):
            out = hf.generate("warm classroom", "1:1")
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["engine"], "cli")
            self.assertEqual(self.rest_calls, 1)
            self.assertIs(hf.rest_status()["funded"], False)
            out2 = hf.generate("warm classroom", "1:1")
            self.assertTrue(out2["ok"])
            self.assertEqual(self.rest_calls, 1, "an empty pool must not be hammered inside the TTL")
            d = json.loads(hf.LEDGER.read_text())
            d["rest"]["at"] = time.time() - hf.REST_EMPTY_TTL - 5
            hf.LEDGER.write_text(json.dumps(d))
            self.assertTrue(hf.rest_status()["retryDue"])
            hf.generate("warm classroom", "1:1")
            self.assertEqual(self.rest_calls, 2, "after the TTL the pool is re-checked once")

    def test_eco_api_unchanged_and_marks_pool(self):
        self.rest_calls = 0
        with mock.patch.object(hf, "_http_json", self._403):
            out = hf.generate_image("x", key="k", secret="s")
        self.assertFalse(out["ok"])
        self.assertTrue(out["outOfCredits"])
        self.assertIn("KEY IS FINE", out["error"])
        self.assertIs(hf.rest_status()["funded"], False)
        self.assertTrue(callable(hf.resolve_key) and callable(hf.resolve_secret) and callable(hf.ready))


class CliParsing(Base):
    def test_parse_cli_shapes(self):
        self.assertEqual(hf.parse_cli("cost", '{\n  "credits": 0.5\n}'), 0.5)
        self.assertEqual(hf.parse_cli("cost", '{"data": {"cost": "4.5"}}'), 4.5)
        self.assertEqual(hf.parse_cli("cost", "Estimated: 4 credits"), 4.0)
        self.assertIsNone(hf.parse_cli("cost", "cost: ???"))
        self.assertIsNone(hf.parse_cli("cost", '{"credits": true}'))
        self.assertIsNone(hf.parse_cli("cost", '{"price_usd": 1.2}'))     # dollars are not credits
        self.assertEqual(hf.parse_cli("account", '{"data": {"credits": {"available": 910}}}'), 910.0)
        self.assertIsNone(hf.parse_cli("workspace", "No workspace selected."))
        r = hf.parse_cli("result", "progress...\n" + json.dumps({"status": "completed",
                                                                 "images": [{"url": "https://c.test/a.png"}]}))
        self.assertEqual(r["url"], "https://c.test/a.png")
        self.assertIsNone(hf.parse_cli("result", "done!")["url"])
        real = json.dumps([{"id": "j", "status": "completed", "min_result_url": "https://c.test/a_min.webp",
                            "result_url": "https://c.test/a.png"}])
        self.assertEqual(hf.parse_cli("result", real)["url"], "https://c.test/a.png")   # never the thumbnail
        failed = hf.parse_cli("result", json.dumps([{"id": "j", "status": "failed"}]))
        self.assertEqual((failed["url"], failed["status"]), (None, "failed"))

    def test_quote_via_shim(self):
        self.cli_on()
        q = hf.quote("reading corner", fmt="9:16")
        self.assertEqual((q["engine"], q["credits"], q["unknown"]), ("cli", 0.5, False))
        cost = [c for c in self.calls() if c[:2] == ["generate", "cost"]][-1]
        self.assertIn("--aspect_ratio=9:16", cost)
        self.assertIn("--quality=medium", cost)
        self.assertEqual(cost[2], "gpt_image_2_5")
        self.assertIn("--prompt=reading corner", cost)
        self.assertEqual(self.creates(), [], "a quote must never create a job")

    def test_quote_malformed_is_unknown(self):
        self.cli_on("badcost")
        q = hf.quote("x")
        self.assertIsNone(q["credits"])
        self.assertTrue(q["unknown"])

    def test_generate_via_shim(self):
        self.cli_on()
        out = hf.generate("-dash first prompt", "9:16", ref="idea1")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["imageUrl"], "https://cdn.example.test/img1.png")
        self.assertEqual(out["credits"], 0.5)
        c = self.creates()[0]
        self.assertIn("--prompt=-dash first prompt", c)            # one token: a leading '-' can't become a flag
        self.assertIn("--wait", c)
        self.assertEqual(hf.spent_today(), (0.5, 0))

    def test_generate_malformed_create_fails_closed(self):
        self.cli_on("badcreate")
        out = hf.generate("x", "1:1")
        self.assertFalse(out["ok"])
        self.assertIn("--probe", out["error"])
        self.assertEqual(hf.spent_today(), (0.0, 0))


class CapAndUnknown(Base):
    def test_daily_cap(self):
        self.cli_on()
        os.environ["HIGGSFIELD_DAILY_CREDITS"] = "0.8"
        self.assertTrue(hf.generate("a", "1:1")["ok"])            # 0 + 0.5 ≤ 0.8
        out = hf.generate("b", "1:1")                               # 0.5 + 0.5 > 0.8
        self.assertFalse(out["ok"])
        self.assertTrue(out["capped"])
        self.assertIn("daily cap", out["error"])
        self.assertEqual(len(self.creates()), 1)

    def test_unknown_cost_needs_confirm(self):
        self.cli_on("badcost")
        out = hf.generate("a", "1:1")
        self.assertFalse(out["ok"])
        self.assertTrue(out["needsConfirm"])
        self.assertEqual(self.creates(), [])
        ok = hf.generate("a", "1:1", confirm_unknown=True)
        self.assertTrue(ok["ok"])
        self.assertEqual(len(self.creates()), 1)

    def test_rest_unknown_cost_prefers_known_cli(self):
        self.rest_on()
        self.cli_on()
        with mock.patch.object(hf, "_http_json", _no_net):
            out = hf.generate("a", "1:1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["engine"], "cli")

    def test_one_generation_at_a_time(self):
        self.cli_on()
        hf._GEN_LOCK.acquire()
        try:
            out = hf.generate("a", "1:1")
        finally:
            hf._GEN_LOCK.release()
        self.assertTrue(out.get("busy"))
        self.assertEqual(self.creates(), [])

    def test_ledger_atomic_under_threads(self):
        ts = [threading.Thread(target=hf._ledger_add, args=({"credits": 1, "engine": "cli"},))
              for _ in range(25)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(hf.spent_today(), (25.0, 0))
        json.loads(hf.LEDGER.read_text())
        self.assertFalse(Path(str(hf.LEDGER) + ".tmp").exists())


_FEED_OK = {"ok": True, "unknown": False, "windows": [{"preset": "last_90d", "spend": 361.01, "leads": 13}],
            "source": "Meta via Pipeboard (read-only)"}
_FEED_UNKNOWN = {"ok": True, "unknown": True, "error": "PIPEBOARD_API_TOKEN not set"}


class Concepts(Base):
    def test_prompt_order_and_contents(self):
        mkt = {"market": {"at": time.time(), "source": "meta-ad-library via Apify",
                          "ours": [{"name": "Trust", "cpl": 20}], "competitors": [{"page": "X", "days": 40}]}}
        with mock.patch("daycare_ads_autopilot._load", return_value=mkt):
            text, unknown, _err = studio.build_prompt(feed=_FEED_OK)
        self.assertFalse(unknown)
        order = ["YOUR CREED", "LIVE AD PACKET", "DAYCARE CONTEXT", "BRAND RULES", "MARKET INTEL",
                 "IMAGE PROMPT CRAFT (Higgsfield)"]
        idx = [text.find(m) for m in order]
        self.assertTrue(all(i >= 0 for i in idx), dict(zip(order, idx)))
        self.assertEqual(idx, sorted(idx), dict(zip(order, idx)))
        self.assertIn("No children's faces", text)
        self.assertIn("361.01", text)

    def test_unknown_packet_is_said(self):
        with mock.patch("daycare_ads_autopilot._load", return_value={}):
            text, unknown, err = studio.build_prompt(feed=_FEED_UNKNOWN)
        self.assertTrue(unknown)
        self.assertIn("THE LIVE AD PACKET IS UNKNOWN", text)
        self.assertIn("MARKET INTEL === Unknown", text)

    def test_brand_skill_is_not_learnable(self):
        import daycare_director
        self.assertNotIn("Ad Generator brand rules", daycare_director.top_skills_text())
        self.assertTrue(studio.daycare_context.load_skill(studio.BRAND_SKILL))

    def _ideas(self, raw, feed):
        seen = {}

        def fake(key, system, user, **kw):
            seen.update(kw, user=user)
            return raw
        with mock.patch("agency_eco._agency_key", return_value=("k", "test")), \
                mock.patch("review_agent._claude", fake), \
                mock.patch("daycare_ads_autopilot._load", return_value={}), \
                mock.patch("agency_ads.create_ad", side_effect=AssertionError("Meta write")):
            return studio.ideas(feed=feed), seen

    def test_concepts_robust_and_creed_backstop(self):
        good = {"title": "Concept 1: Trust", "angle": "Trust", "headline": "A second home",
                "primaryText": "Warm, licensed care.", "cta": "BOOK_TRAVEL", "format": "4:5",
                "imagePrompt": "Sunlit reading corner, no children, 1:1", "evidence": "last_90d CPL $9"}
        raw = "Here you go:\n```json\n" + json.dumps({"next": [good, {"headline": "no prompt"}, "junk"]}) + "\n```"
        out, seen = self._ideas(raw, _FEED_UNKNOWN)
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(out["next"]), 1)
        c = out["next"][0]
        self.assertEqual(c["cta"], "SIGN_UP")
        self.assertEqual(c["format"], "1:1")
        self.assertTrue(c["evidence"].startswith("Unknown — no live ad data"))   # invented $9 dropped
        self.assertEqual(c["assets"], [])
        self.assertEqual(seen["effort"], "low")
        import review_agent
        self.assertEqual(seen["model"], review_agent.SMART_MODEL)
        self.assertEqual(len(studio.saved()["ideas"]), 1)

    def test_malformed_json(self):
        out, _ = self._ideas("sorry, no json", _FEED_OK)
        self.assertFalse(out["ok"])

    def test_claude_call_names_model_and_effort(self):
        tree = ast.parse((HERE / "daycare_ads_studio.py").read_text())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "_claude":
                self.assertTrue({"model", "effort"} <= {k.arg for k in n.keywords})


class StudioFlow(Base):
    def _seed(self):
        studio._save([{"id": "i1", "title": "T", "imagePrompt": "room, 1:1", "imagePromptAlt": "hands, 9:16",
                       "format": "9:16", "status": "draft", "evidence": "Unknown — no live ad data"}])

    def test_generate_needs_tap_and_records_asset(self):
        self._seed()
        self.cli_on()
        self.assertTrue(studio.generate_asset("i1")["needsConfirm"])
        self.assertEqual(self.creates(), [])
        with mock.patch("agency_ads.create_ad", side_effect=AssertionError("Meta write")):
            out = studio.generate_asset("i1", confirm=True, variant="1")
        self.assertTrue(out["ok"], out)
        idea = studio._find("i1")
        self.assertEqual(idea["status"], "image")
        a = idea["assets"][0]
        self.assertEqual((a["format"], a["engine"], a["credits"], a["variant"]), ("9:16", "cli", 0.5, 1))
        self.assertIn("--prompt=hands, 9:16", self.creates()[0])

    def test_autopilot_path_refuses_unknown_cost(self):
        self._seed()
        self.cli_on("badcost")
        out = studio.attach_image("i1")                     # the autopilot's call: no tap, no confirm
        self.assertFalse(out["ok"])
        self.assertEqual(self.creates(), [])

    def test_no_engine_is_polite(self):
        self._seed()
        out = studio.attach_image("i1", trigger="owner_tap")
        self.assertFalse(out["ok"])
        self.assertTrue(out["needsKey"])
        self.assertIn("No image engine is ready", out["error"])
        q = studio.quote_image("i1")
        self.assertIsNone(q["credits"])
        st = studio.adgen_status()
        self.assertEqual((st["ideas"], st["drafts"], st["assets"]), (1, 1, 0))


class Wiring(unittest.TestCase):
    def test_routes_allowlisted_and_session_gated(self):
        tree = ast.parse((HERE / "connector.py").read_text())
        fns = {n.name: ast.get_source_segment((HERE / "connector.py").read_text(), n)
               for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        post, get = fns["_handle_daycare_post"], fns["_handle_daycare_get"]
        for r in ("/api/daycare/adgen/quote", "/api/daycare/adgen/generate"):
            self.assertEqual(post.count(f'"{r}"'), 2, r)             # allowlist + elif dispatch
        self.assertIn('"/api/daycare/adgen/status"', get)
        self.assertLess(post.index("_daycare_resolve_session(sid)"), post.index('== "/api/daycare/adgen/generate"'))
        self.assertIn('confirm=body.get("confirm") is True', post)
        self.assertIn("sid = self._daycare_session_id()", get)

    def test_telegram_partner_sees_it_and_taps_spend(self):
        import telegram_agent as ta
        self.assertIn(("adgen/generate", "💸 spends image credits"), ta._RISKY)
        self.assertIn("/api/daycare/adgen/status", (HERE / "telegram_agent.py").read_text())
        self.assertFalse(any(d in "/api/daycare/nova/generate" for d in ta.DENY))

    def test_ui_registered(self):
        html = (HERE / "FORGE REI OS.html").read_text()
        self.assertLess(html.index('src="daycare_adgen.jsx"'), html.index('src="app.jsx"'))


if __name__ == "__main__":
    unittest.main()
