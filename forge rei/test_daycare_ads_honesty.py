"""test_daycare_ads_honesty.py — the daycare must never report another business's ad numbers.

Regression guard for a real defect found 2026-08-19: daycare.env carried a real
META_ACCESS_TOKEN but no META_AD_ACCOUNT_MAP, so agency_ads.connection() reported
source="live" while agency_ads.analytics(client="daycare") matched no account and fell
back to _ACCOUNTS[0] — the AGENCY's demo account. The daycare Growth tab rendered
Bloom Dental's fabricated $3,370 spend / 117 leads / 4.99 ROAS under a green LIVE badge,
and Solomon ingested the same figures under "TODAY'S LIVE CENTER DATA".

The daycare creed: never invent a number; every metric carries its source or is Unknown.

Run: cd "forge rei" && python3 test_daycare_ads_honesty.py
"""
import unittest
from unittest import mock

import agency_ads
import daycare_growth


class DaycareAdsHonestyTest(unittest.TestCase):
    def test_demo_account_is_never_served_as_daycare_data(self):
        """Token present, no account map -> honest not-configured, NOT Bloom Dental."""
        with mock.patch.object(agency_ads, "connection",
                               return_value={"connected": True, "hasToken": True,
                                             "source": "live", "todo": None}):
            out = daycare_growth.ads_overview()

        self.assertIsNone(out["analytics"], "daycare served fabricated ad analytics")
        self.assertFalse(out["configured"])
        self.assertFalse(out["connection"]["connected"],
                         "badge would render LIVE over fake numbers")
        self.assertEqual(out["accounts"], [])

        blob = repr(out)
        for leak in ("Bloom Dental", "Peak Fitness", "demo-bloom", "act_1001", "3370"):
            self.assertNotIn(leak, blob, "another business leaked into daycare ads: " + leak)

    def test_real_account_passes_through(self):
        """A genuinely mapped daycare account must NOT be suppressed by the guard."""
        real = {"id": "act_1175564690150627", "name": "A Touch of Blessings",
                "clientId": "daycare", "clientName": "A Touch of Blessings"}
        with mock.patch.object(agency_ads, "connection",
                               return_value={"connected": True, "source": "live"}), \
             mock.patch.object(agency_ads, "accounts", return_value={"accounts": [real]}), \
             mock.patch.object(agency_ads, "analytics",
                               return_value={"account": real, "totals": {"spend": 42}}):
            out = daycare_growth.ads_overview()

        self.assertTrue(out["configured"])
        self.assertEqual(out["analytics"]["totals"]["spend"], 42)
        self.assertEqual(out["accounts"], [real])

    def test_solomon_is_told_not_to_fabricate_when_unmapped(self):
        """The director must receive an explicit err so its no-fabrication rail fires."""
        import daycare_director
        eng = daycare_director.SolomonEngine.__new__(daycare_director.SolomonEngine)
        with mock.patch.object(agency_ads, "connection",
                               return_value={"connected": True, "source": "live"}):
            data, err = eng._gather_campaign()
        self.assertFalse(data["connected"])
        self.assertTrue(err, "no err -> the do-not-fabricate instruction never fires")
        self.assertNotIn("Bloom", repr(data))


if __name__ == "__main__":
    unittest.main()
