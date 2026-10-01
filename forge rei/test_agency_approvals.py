"""test_agency_approvals.py — regression guards from the 2026-09-30 audit.

1. Approving a queued social post with no Metricool token used to DEADLOCK (decide() held a
   plain Lock while publish() -> set_status('ready') -> add() re-took it). Must return.
2. Eco approve built a spec create_ad never read (account_id vs ad_account_id). The spec must
   carry ad_account_id/page_id/creative, and create_ad must refuse an incomplete spec BEFORE the
   first Meta POST (no orphaned campaigns).
No network, temp state only. Run: cd "forge rei" && python3 test_agency_approvals.py
"""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import agency_ads
import agency_approvals_io as ap
import agency_eco
import agency_social


class ApprovalsTest(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        base = Path(self.t.name)
        self._o = (ap.STATE, agency_social.STATE, agency_eco.STATE)
        ap.STATE, agency_social.STATE, agency_eco.STATE = (
            base / "ap.json", base / "social.json", base / "eco.json")
        self.env = mock.patch.dict(os.environ, {"METRICOOL_USER_TOKEN": "", "META_ACCESS_TOKEN": "",
                                                "PIPEBOARD_API_TOKEN": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        ap.STATE, agency_social.STATE, agency_eco.STATE = self._o
        self.t.cleanup()

    def test_social_approve_without_token_returns_instead_of_deadlocking(self):
        post = agency_social.save_post({"network": "instagram", "text": "hello"})["post"]
        agency_social.set_status(post["id"], "ready")          # queues the approval item
        item = ap.list_queue()["queue"][0]
        out = {}
        th = threading.Thread(target=lambda: out.update(ap.decide(item["id"], "approve")), daemon=True)
        th.start()
        th.join(5)
        self.assertFalse(th.is_alive(), "decide() deadlocked on its own lock")
        self.assertEqual(out["item"]["status"], "failed")       # honest: nothing was published
        self.assertTrue(ap.add("social", "x", "t", "s")["ok"], "lock must be free afterwards")

    def test_eco_spec_has_the_keys_create_ad_reads(self):
        built = {"id": "eco1", "status": "draft", "account": {"id": "act_9", "clientName": "C"},
                 "next": [{"title": "T", "headline": "H", "primaryText": "P", "link": "https://x.test"}],
                 "best": [], "weak": []}
        agency_eco._save({"sets": [built], "seq": 1})
        seen = {}
        with mock.patch.object(agency_ads, "create_ad",
                               side_effect=lambda spec, paused=True: seen.update(spec) or {"ok": True, "detail": "d"}), \
             mock.patch.dict(os.environ, {"META_PAGE_ID": "123", "META_ACCESS_TOKEN": "x"}):
            agency_eco._approve_ad("eco1", 0)
        self.assertEqual(seen["ad_account_id"], "act_9")
        self.assertEqual(seen["page_id"], "123")
        self.assertEqual(seen["creative"]["link"], "https://x.test")
        self.assertEqual(seen["creative"]["message"], "P")

    def test_create_ad_refuses_incomplete_spec_before_any_meta_post(self):
        with mock.patch.object(agency_ads, "_meta_open_json") as post:
            out = agency_ads._live_create_ad("tok", {"ad_account_id": "act_9", "name": "n"}, True)
        self.assertFalse(out["ok"])
        self.assertIn("page_id", out["detail"])
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
