"""test_agency_ads_range.py — the agency Ads timeline = Meta's date picker, in the ad account's day.

Runnable spec for agency_ads._date_range / analytics(preset, since, until) / pipeboard_io.account_meta
and the /api/agency/ads route. The bug this guards: the box runs UTC, so "today" taken from the server
clock is already tomorrow after ~8pm Eastern and every window shifted by a day.

Run: python3 test_agency_ads_range.py
"""
import datetime as dt
import unittest
from unittest import mock

import ads_range
import agency_ads
import pipeboard_io

TODAY = dt.date(2026, 10, 31)
ACCT = "act_2344043939684594"


def _fake_pb_analytics(acct, days, rng=None):
    rng = rng or agency_ads._date_range(days)
    return {"account": {"id": acct}, "days": rng.get("days", days), "dateRange": rng, "totals": {},
            "dataSource": "live", "via": "pipeboard"}


class DateRangeTest(unittest.TestCase):
    def test_default_window_uses_the_account_day_not_the_server_day(self):
        with mock.patch.object(ads_range, "account_today", lambda tz=None, now=None: (TODAY, "America/New_York", False)):
            r = agency_ads._date_range(7)
        self.assertEqual({"days": 7, "since": "2026-10-24", "until": "2026-10-30"}, r)

    def test_bad_days_keeps_the_old_window_instead_of_raising(self):
        self.assertIn("since", agency_ads._date_range(0))


class AnalyticsRangeTest(unittest.TestCase):
    def setUp(self):
        self.p = [
            mock.patch.object(pipeboard_io, "configured", lambda: True),
            mock.patch.object(pipeboard_io, "auth_dead", lambda: False),
            mock.patch.object(pipeboard_io, "account_meta", lambda a: {"tz": "America/New_York", "created": "2026-08-01"}),
            mock.patch.object(pipeboard_io, "analytics", _fake_pb_analytics),
            mock.patch.object(agency_ads, "owner_of", lambda a: None),
            mock.patch.object(agency_ads, "connection", lambda: {}),
            mock.patch.object(ads_range, "account_today", lambda tz=None, now=None: (TODAY, tz or "x", False)),
        ]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_presets_match_ads_manager(self):
        for preset, since, until in (("yesterday", "2026-10-30", "2026-10-30"),
                                     ("last_30d", "2026-10-01", "2026-10-30"),      # 30 COMPLETE days, today excluded
                                     ("this_month", "2026-10-01", "2026-10-31"),
                                     ("last_month", "2026-09-01", "2026-09-30")):
            out = agency_ads.analytics(account=ACCT, preset=preset)
            self.assertEqual((since, until), (out["dateRange"]["since"], out["dateRange"]["until"]), preset)
            self.assertEqual("2026-10-31", out["accountToday"])
            self.assertEqual("America/New_York", out["accountTz"])

    def test_custom_range_and_label(self):
        out = agency_ads.analytics(account=ACCT, since="2026-10-01", until="2026-10-15")
        self.assertEqual("custom", out["dateRange"]["preset"])
        self.assertEqual(15, out["days"])

    def test_no_picker_args_is_the_legacy_last_n_days(self):
        out = agency_ads.analytics(account=ACCT, days=7)
        self.assertEqual(("2026-10-24", "2026-10-30"), (out["dateRange"]["since"], out["dateRange"]["until"]))

    def test_bad_range_raises_value_error_not_a_silent_mock(self):
        for kw in ({"preset": "nope"}, {"since": "2026-10-20", "until": "2026-10-01"}, {"since": "2027-01-01", "until": "2027-01-02"}):
            with self.assertRaises(ValueError):
                agency_ads.analytics(account=ACCT, **kw)

    def test_route_turns_a_bad_range_into_a_message(self):
        import connector
        with mock.patch.object(agency_ads, "agency_account", lambda a, c: ("ok", ACCT)):
            out = connector.api_agency_ads({"account": [ACCT], "preset": ["nope"]})
            self.assertEqual("range_error", out["dataSource"])
            self.assertIn("nope", out["rangeError"])
            ok = connector.api_agency_ads({"account": [ACCT], "preset": ["last_14d"]})
            self.assertEqual("live", ok["dataSource"])
            self.assertEqual(14, ok["days"])


class AccountMetaTest(unittest.TestCase):
    def setUp(self):
        pipeboard_io._META.clear()

    def test_reads_timezone_and_created_and_caches(self):
        calls = []

        def fake(tool, args=None, timeout=60):
            calls.append(tool)
            return {"timezone_name": "America/New_York", "created_time": "2026-04-01T10:00:00+0000"}

        with mock.patch.object(pipeboard_io, "call", fake):
            m1 = pipeboard_io.account_meta("act_1")
            m2 = pipeboard_io.account_meta("act_1")
        self.assertEqual({"tz": "America/New_York", "created": "2026-04-01"}, m1)
        self.assertEqual(m1, m2)
        self.assertEqual(1, len(calls))

    def test_failure_returns_unknown_and_is_not_cached(self):
        def boom(tool, args=None, timeout=60):
            raise RuntimeError("down")

        with mock.patch.object(pipeboard_io, "call", boom):
            self.assertEqual({"tz": None, "created": None}, pipeboard_io.account_meta("act_2"))
        self.assertNotIn("act_2", pipeboard_io._META)


if __name__ == "__main__":
    unittest.main()
