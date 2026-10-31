"""test_agency_instagram.py — the agency Instagram toolkit (@forgelabsphiladelphia).

Runnable spec for agency_instagram: the vendored ig tools run, drafts never leave `draft`,
the daycare's ids never leak in, state paths stay agency-only, and Dyson/Eco are told the tools.

Run: python3 test_agency_instagram.py
"""
import json
import tempfile
import unittest
from pathlib import Path

import agency_agents
import agency_instagram as ai
import agency_social

DAYCARE_AD = "act_1175564690150627"
DAYCARE_PAGE = "939494549239823"
DAYCARE_IG = {"17841436257715501", "17841439350588476"}
TSV = "account\tfollowers\tmedian\tviews\thook\n@a\t4000\t1000\t90000\tI lost $5,000 on one contract\n@b\t900000\t400000\t410000\tHello everyone\n"


class ToolsTest(unittest.TestCase):
    def test_every_tool_runs_on_good_input(self):
        cases = {
            "hook": "I lost $18,000 because of one missing contract.\nHey guys, today I wanted to talk",
            "beats": "I lost $18,000 on one contract.\nHere is the clause I add now.\nDelivery is a date.",
            "caption": "Most Philly daycares lose parents on the website, not the phone.",
            "humanize": "Let’s delve in — it’s seamless.",
            "detect": "Let's delve into a robust, seamless approach.",
            "swipe": TSV,
        }
        self.assertEqual(set(cases), set(ai.TOOLS))
        for tool, text in cases.items():
            r = ai.run_tool(tool, text)
            self.assertTrue(r.get("ok"), (tool, r))
            self.assertEqual(tool, r["tool"])

    def test_humanize_strips_em_dash(self):
        out = ai.run_tool("humanize", "It works — really.")["result"]["text"]
        self.assertNotIn("—", out)

    def test_bad_input_is_an_error_not_a_crash(self):
        self.assertIn("error", ai.run_tool("nope", "x"))
        self.assertIn("error", ai.run_tool("hook", ""))
        self.assertIn("error", ai.run_tool("hook", None))
        self.assertIn("error", ai.run_tool("hook", "x" * (ai.MAX_CHARS + 1)))
        self.assertIn("error", ai.run_tool("swipe", "not a table"))

    def test_beats_options_are_clamped(self):
        r = ai.run_tool("beats", "One line here.\nAnother line.", {"target": 20, "wpm": 99999})
        self.assertTrue(r["ok"])
        self.assertEqual(165, r["result"]["wpm"])      # out-of-range wpm ignored -> default
        self.assertEqual(20.0, r["result"]["target"])


class DraftTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = agency_social.STATE
        agency_social.STATE = Path(self._tmp.name) / "agency_social.json"

    def tearDown(self):
        agency_social.STATE = self._orig
        self._tmp.cleanup()

    def test_save_draft_is_an_instagram_draft_only(self):
        r = ai.save_draft("Websites for Philly small businesses — free to build.")
        self.assertTrue(r["ok"], r)
        self.assertEqual("draft", r["post"]["status"])
        self.assertEqual("instagram", r["post"]["network"])
        self.assertNotIn("—", r["post"]["text"])          # humanized before it was stored
        self.assertEqual(["draft"], [p["status"] for p in agency_social.list_posts()["posts"]])

    def test_daycare_is_refused(self):
        for text in ("Follow @atouchofblessing2.3 for more", "A Touch of Blessings is hiring",
                     "ad account " + DAYCARE_AD, "page " + DAYCARE_PAGE, "ig 17841436257715501"):
            r = ai.save_draft(text)
            self.assertIn("error", r, text)
        self.assertEqual([], agency_social.list_posts()["posts"])

    def test_empty_text_refused(self):
        self.assertIn("error", ai.save_draft("   "))


class IsolationTest(unittest.TestCase):
    def test_pinned_ids_are_the_agencys_not_the_daycares(self):
        self.assertEqual("act_2344043939684594", ai.AGENCY_AD_ACCOUNT)
        self.assertNotEqual(DAYCARE_AD, ai.AGENCY_AD_ACCOUNT)
        self.assertNotIn(ai.IG_ID, DAYCARE_IG)
        st = ai.status()
        self.assertEqual("agency", st["account"]["business"])
        self.assertIsNone(st["account"]["facebookPage"])        # no agency Page yet: Unknown, never the daycare's
        self.assertFalse(st["publishes"])
        self.assertTrue(st["toolsOnDisk"])
        blob = json.dumps(st)
        for bad in (DAYCARE_AD, DAYCARE_PAGE, *DAYCARE_IG):
            self.assertNotIn(bad, blob)

    def test_vendored_skills_use_agency_state_not_the_global_folder(self):
        for p in ai.SKILLS.rglob("*"):
            if p.is_file() and p.suffix in (".md", ".py", ".json"):
                self.assertNotIn("~/.claude/instagram", p.read_text(errors="ignore"), p)
        self.assertTrue(ai.VOICE.is_file())

    def test_vendored_tools_do_no_network_or_subprocess(self):
        for p in ai.SKILLS.rglob("*.py"):
            src = p.read_text()
            for bad in ("import socket", "import requests", "urllib.request", "import subprocess", "os.system"):
                self.assertNotIn(bad, src, (p.name, bad))


class AgentKnowledgeTest(unittest.TestCase):
    def test_dyson_and_eco_are_told_the_tools_and_the_right_account(self):
        for agent in ("dyson", "eco"):
            block = agency_agents._skills_block(agent)
            self.assertIn("AGENCY INSTAGRAM TOOLS", block, agent)
            self.assertIn("forgelabsphiladelphia", block, agent)
            self.assertIn("act_2344043939684594", block, agent)
            self.assertIn("/api/agency/instagram/tool", block, agent)


if __name__ == "__main__":
    unittest.main()
