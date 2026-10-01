"""test_pipeboard_io.py — Pipeboard client shape + failure semantics. No network, no env files.
Run: cd "forge rei" && python3 test_pipeboard_io.py
"""
import unittest
from unittest import mock

import agency_ads
import pipeboard_io as pb

ROWS = [
    {"ad_id": "1", "ad_name": "Flyer A", "campaign_id": "c1", "campaign_name": "Camp",
     "spend": "10.00", "impressions": "1000", "reach": "900", "clicks": "20",
     "actions": [{"action_type": "lead", "value": "3"},
                 {"action_type": "onsite_conversion.lead_grouped", "value": "3"}]},
    {"ad_id": "2", "ad_name": "Flyer B", "campaign_id": "c1", "campaign_name": "Camp",
     "spend": "5.00", "impressions": "500", "reach": "450", "clicks": "5", "actions": []},
]


class PipeboardTest(unittest.TestCase):
    def setUp(self):
        pb.clear_cache()
        self.env = mock.patch.dict("os.environ", {"PIPEBOARD_API_TOKEN": "t", "PIPEBOARD_AD_ACCOUNT_ID": "act_9"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        pb.clear_cache()

    def _call(self, tool, args=None, timeout=60):
        return {"get_insights": {"data": ROWS},
                "get_campaigns": {"data": [{"id": "c1", "status": "PAUSED"}]}}[tool]

    def test_analytics_shape_and_no_double_counted_leads(self):
        with mock.patch.object(pb, "call", self._call):
            a = pb.analytics("act_9", 7)
        self.assertEqual((a["dataSource"], a["via"]), ("live", "pipeboard"))
        self.assertEqual(a["totals"]["leads"], 3, "lead + lead_grouped is ONE lead")
        self.assertEqual(a["totals"]["spend"], 15.0)
        self.assertEqual(a["campaigns"][0]["status"], "paused")
        self.assertEqual(a["topAds"][0]["name"], "Flyer A")
        self.assertIn("since", a["dateRange"])

    def test_agency_ads_uses_pipeboard_when_keyed_and_labels_it(self):
        with mock.patch.object(pb, "call", self._call):
            out = agency_ads.analytics(client="daycare", days=7)
            self.assertEqual(agency_ads.connection()["via"], "pipeboard")
        self.assertEqual(out["account"]["id"], "act_9")
        self.assertEqual(out["dataSource"], "live")

    def test_failure_falls_back_to_labeled_mock_never_silent_zero(self):
        def boom(*a, **k):
            raise pb.PipeboardError("down")
        with mock.patch.object(pb, "call", boom):
            out = agency_ads.analytics(client="daycare", days=7)
        self.assertEqual(out["source"], "mock")
        self.assertNotEqual(out["dataSource"], "live")

    def test_auth_rejection_is_cached_and_reported(self):
        def deny(*a, **k):
            pb._mark_dead()
            raise pb.PipeboardAuthError("nope")
        with mock.patch.object(pb, "call", deny):
            agency_ads.analytics(client="daycare", days=7)
        self.assertEqual(agency_ads.connection()["source"], "auth_error")
        self.assertEqual(agency_ads.analytics(client="daycare")["dataSource"], "token_rejected")

    def test_unconfigured_changes_nothing(self):
        with mock.patch.dict("os.environ", {"PIPEBOARD_API_TOKEN": ""}):
            self.assertFalse(pb.configured())
            self.assertNotEqual(agency_ads.connection().get("via"), "pipeboard")


if __name__ == "__main__":
    unittest.main()
