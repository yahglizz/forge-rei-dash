"""test_agent_comms.py — agency <-> daycare agent communication (2026-09-30).

Temp state only; the vault feed writer and every Claude/Meta call are stubbed.
Run: cd "forge rei" && python3 test_agent_comms.py
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_bus
import agent_coach
import daycare_director
import daycare_growth


class CommsTest(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self._bus = agent_bus.STATE
        agent_bus.STATE = Path(self.t.name) / "bus.json"
        self._share = daycare_growth._SHARE_FILE
        daycare_growth._SHARE_FILE = Path(self.t.name) / "share.json"
        self.feed = mock.patch.object(agent_coach, "_append_feed")   # never write the real vault
        self.feed.start()
        self.arch = mock.patch.object(agent_coach, "_archived_businesses", return_value=set())
        self.arch.start()

    def tearDown(self):
        self.feed.stop()
        self.arch.stop()
        agent_bus.STATE = self._bus
        daycare_growth._SHARE_FILE = self._share
        self.t.cleanup()

    def test_alert_flood_cannot_evict_coaching_or_tasks(self):
        agent_coach.broadcast("eco", "carousels beat single image when the angle is a sequence", to="all")
        agent_bus.send("hub", "eco", "task", "do the thing")
        for i in range(agent_bus.MAX_MESSAGES + 60):
            agent_bus.send("watchdog", "all", "alert", f"loop red {i}")
        kinds = [m["kind"] for m in agent_bus.recent(500)["messages"]]
        self.assertEqual(len(kinds), agent_bus.MAX_MESSAGES)
        self.assertIn("coach", kinds)
        self.assertIn("task", kinds)
        self.assertTrue(agent_coach.feed(), "the coaching feed must survive an alert flood")

    def test_solomon_inbox_ignores_coach_and_status_and_leaves_them_unread(self):
        agent_coach.broadcast("eco", "peer lesson", to="all")
        agent_bus.send("eco", "all", "status", "Eco ran")
        agent_bus.send("hub", "solomon", "handoff", "[Ads] refresh the Trust creative")
        got = daycare_director.SolomonEngine.__new__(daycare_director.SolomonEngine)._read_bus_inbox()
        self.assertEqual([m["kind"] for m in got], ["handoff"])
        unread = {m["kind"] for m in agent_bus.inbox("eco", unread_only=True)["messages"]}
        self.assertTrue({"coach", "status"} <= unread, "other agents must still see their own mail")

    def test_peer_lessons_reach_solomon_prompt_and_both_ids_resolve(self):
        agent_coach.broadcast("eco", "lead with the avatar, not the offer", to="daycare")
        self.assertIn("lead with the avatar", daycare_director._peer_coaching())
        for lane in ("daycare_leads", "daycare_replies", "followup"):
            self.assertIn(lane, agent_coach.BUSINESS_OF)

    def test_owner_ad_method_in_constitution_but_never_in_learn(self):
        eng = daycare_director.SolomonEngine.__new__(daycare_director.SolomonEngine)
        eng._sk_mtime, eng._sk_text = None, ""
        skills = eng._load_skills()
        self.assertIn("THE OWNER'S AD METHOD", skills)
        self.assertIn("Four Triggers", skills)
        self.assertNotIn("THE OWNER'S AD METHOD", eng._playbook_only())

    def _live(self, spend=100.0, leads=5):
        return {"ok": True, "configured": True, "analytics": {
            "dataSource": "live", "dateRange": {"since": "2026-09-01", "until": "2026-09-29"},
            "totals": {"spend": spend, "leads": leads, "cpl": spend / max(leads, 1), "ctr": 2.1, "clicks": 90},
            "topAds": [{"name": "Flyer A", "leads": 4, "spend": 60.0, "ctr": 2.5}],
            "weakAds": [{"name": "Flyer B", "leads": 1, "spend": 40.0, "ctr": 1.2}]}}

    def test_ad_results_flow_solomon_to_eco_once_and_only_when_real(self):
        with mock.patch.object(daycare_growth, "ads_overview", return_value=self._live()):
            first = daycare_growth.share_ad_results()
            again = daycare_growth.share_ad_results()
        self.assertTrue(first["ok"] and first["shared"])
        self.assertIn("2026-09-01→2026-09-29", first["shared"])       # window travels with the number
        self.assertIn("hypothesis", first["shared"])
        self.assertEqual(again.get("skipped"), "already shared")
        mine = agent_coach.insights_for("eco", "agency")
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["from"], "solomon")
        mock_off = {"ok": True, "configured": True, "analytics": {"dataSource": "mock", "totals": {"spend": 9}}}
        with mock.patch.object(daycare_growth, "ads_overview", return_value=mock_off):
            self.assertIn("skipped", daycare_growth.share_ad_results())   # never broadcast mock numbers

    def test_ads_delegation_becomes_one_open_eco_task(self):
        import agents_hub
        rows, saved = [], []
        with mock.patch.object(agents_hub, "_load", lambda: rows), \
             mock.patch.object(agents_hub, "send_task",
                               side_effect=lambda a, t, note="": rows.append(
                                   {"agentId": a, "title": t, "status": "open"}) or {"ok": True}):
            eng = daycare_director.SolomonEngine.__new__(daycare_director.SolomonEngine)
            eng._task_eco("refresh the Trust angle")
            eng._task_eco("refresh the Trust angle")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["title"].startswith("Daycare ads (from Solomon)"))


if __name__ == "__main__":
    unittest.main()
