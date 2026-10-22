"""test_daycare_ads_feed.py — the Meta-exact ads range resolver + the agents' live ad packet.

No network: every Pipeboard read is a fake `pipeboard_io.call`; every Meta WRITE is a mock that
must never be touched. Run: cd "forge rei" && python3 test_daycare_ads_feed.py
"""
import datetime as dt
import json
import os
import unittest
from unittest import mock

import ads_range
import daycare_growth
import pipeboard_io as pb

D = dt.date
WRITE_TOOLS = ("update_", "create_", "upload_", "delete_", "duplicate_", "bulk_")


class ResolverTable(unittest.TestCase):
    def r(self, preset, today, **kw):
        out = ads_range.resolve(preset, today=today, tz_name="America/New_York", **kw)
        return out["since"], out["until"]

    def test_presets_table(self):
        sat = D(2026, 10, 17)       # a Saturday
        sun = D(2026, 10, 18)
        table = [
            ("last_30d", sat, ("2026-09-17", "2026-10-16")),      # verified against Ads Manager
            ("today", sat, ("2026-10-17", "2026-10-17")),
            ("yesterday", sat, ("2026-10-16", "2026-10-16")),
            ("today_and_yesterday", sat, ("2026-10-16", "2026-10-17")),
            ("last_7d", sat, ("2026-10-10", "2026-10-16")),
            ("last_14d", sat, ("2026-10-03", "2026-10-16")),
            ("last_28d", sat, ("2026-09-19", "2026-10-16")),
            ("last_90d", sat, ("2026-07-19", "2026-10-16")),
            ("this_week", sat, ("2026-10-11", "2026-10-17")),      # Saturday edge: Sun..Sat so far
            ("last_week", sat, ("2026-10-04", "2026-10-10")),
            ("this_week", sun, ("2026-10-18", "2026-10-18")),      # Sunday edge: week just started
            ("last_week", sun, ("2026-10-11", "2026-10-17")),
            ("this_month", sat, ("2026-10-01", "2026-10-17")),
            ("last_month", sat, ("2026-09-01", "2026-09-30")),
            ("last_month", D(2026, 1, 1), ("2025-12-01", "2025-12-31")),   # year boundary
            ("yesterday", D(2026, 1, 1), ("2025-12-31", "2025-12-31")),
            ("last_7d", D(2026, 1, 1), ("2025-12-25", "2025-12-31")),
            ("this_week", D(2026, 1, 1), ("2025-12-28", "2026-01-01")),    # Thu → previous Sunday
            ("last_month", D(2026, 3, 1), ("2026-02-01", "2026-02-28")),   # month boundary
            ("last_30d", D(2026, 3, 1), ("2026-01-30", "2026-02-28")),
            ("last_month", D(2028, 3, 1), ("2028-02-01", "2028-02-29")),   # leap year
            ("this_month", D(2026, 10, 1), ("2026-10-01", "2026-10-01")),
        ]
        for preset, today, want in table:
            with self.subTest(preset=preset, today=today):
                self.assertEqual(self.r(preset, today), want)

    def test_partial_today_flag(self):
        t = D(2026, 10, 17)
        self.assertTrue(ads_range.resolve("today", today=t)["partialToday"])
        self.assertFalse(ads_range.resolve("last_30d", today=t)["partialToday"])
        self.assertEqual(ads_range.resolve("last_30d", today=t)["days"], 30)

    def test_maximum(self):
        t = D(2026, 10, 17)
        self.assertEqual(self.r("maximum", t, earliest="2025-02-03"), ("2025-02-03", "2026-10-17"))
        self.assertEqual(self.r("maximum", t), ("2023-09-17", "2026-10-17"))           # 37-month floor
        self.assertEqual(self.r("maximum", t, earliest="2019-01-01"), ("2023-09-17", "2026-10-17"))

    def test_custom_validation(self):
        t = D(2026, 10, 17)
        self.assertEqual(self.r(None, t, since="2026-08-21", until="2026-08-31"), ("2026-08-21", "2026-08-31"))
        with self.assertRaises(ValueError):
            self.r(None, t, since="2026-09-10", until="2026-09-01")
        with self.assertRaises(ValueError):
            self.r(None, t, since="2026-10-20", until="2026-10-21")
        out = ads_range.resolve(None, "2026-10-01", "2026-12-01", today=t)
        self.assertEqual((out["until"], out["clamped"]), ("2026-10-17", True))
        out = ads_range.resolve(None, "2020-01-01", "2026-01-01", today=t)
        self.assertEqual((out["since"], out["clamped"]), ("2023-09-17", True))
        with self.assertRaises(ValueError):
            ads_range.resolve("nonsense", today=t)

    def test_legacy_days(self):
        t = D(2026, 10, 17)
        self.assertEqual(ads_range.resolve(days=30, today=t)["preset"], "last_30d")
        out = ads_range.resolve(days="45", today=t)
        self.assertEqual((out["since"], out["until"], out["days"]), ("2026-09-02", "2026-10-16", 45))

    def test_utc_evening_vs_new_york(self):
        # 21:30 EDT on Oct 17 is already Oct 18 in UTC (the box). Meta's day is the account's.
        now = dt.datetime(2026, 10, 18, 1, 30, tzinfo=dt.timezone.utc)
        today, tz, fell = ads_range.account_today("America/New_York", now)
        self.assertEqual((today, tz, fell), (D(2026, 10, 17), "America/New_York", False))
        r = ads_range.resolve("last_30d", today=today)
        self.assertEqual((r["since"], r["until"]), ("2026-09-17", "2026-10-16"))
        self.assertNotEqual(now.date(), today)            # the old server-date bug, pinned
        with mock.patch.dict(os.environ, {"FORGE_TZ_OFFSET": "-4"}):
            today2, tz2, fell2 = ads_range.account_today("Not/AZone", now)
        self.assertEqual((today2, fell2), (D(2026, 10, 17), True))
        self.assertIn("fallback", tz2)

    def test_compare_math(self):
        p = ads_range.previous({"since": "2026-09-17", "until": "2026-10-16"})
        self.assertEqual((p["since"], p["until"], p["days"]), ("2026-08-18", "2026-09-16", 30))
        p = ads_range.previous({"since": "2026-10-17", "until": "2026-10-17"})
        self.assertEqual((p["since"], p["until"]), ("2026-10-16", "2026-10-16"))
        self.assertEqual(ads_range.delta_pct(0, 361.01), -100.0)
        self.assertEqual(ads_range.delta_pct(15, 10), 50.0)
        self.assertIsNone(ads_range.delta_pct(5, 0))        # undefined, not a fake 0 or ∞
        self.assertIsNone(ads_range.delta_pct(None, 3))


# ── fake Pipeboard ────────────────────────────────────────────────────────────
LEAD_RESULT = [{"indicator": "actions:offsite_conversion.fb_pixel_lead",
                "values": [{"value": "2", "attribution_windows": ["default"]}]}]
ACCT_ROW = {"spend": "30.00", "impressions": "1000", "clicks": "20", "reach": "800",
            "actions": [{"action_type": "lead", "value": "2"}]}
AD1 = {"campaign_id": "c1", "campaign_name": "daycare ads pt1", "ad_id": "a1", "ad_name": "Flyer A",
       "spend": "20.00", "impressions": "600", "clicks": "12", "reach": "500",
       "actions": [{"action_type": "lead", "value": "2"},
                   {"action_type": "offsite_conversion.fb_pixel_lead", "value": "2"}],
       "results": LEAD_RESULT}
AD2 = {"campaign_id": "c1", "campaign_name": "daycare ads pt1", "ad_id": "a2", "ad_name": "Flyer B",
       "spend": "10.00", "impressions": "400", "clicks": "8", "reach": "350", "actions": []}


class FakePB:
    def __init__(self, fail=False, acct_spend="30.00"):
        self.calls, self.fail, self.acct_spend = [], fail, acct_spend

    def __call__(self, tool, args=None, timeout=60):
        args = dict(args or {})
        self.calls.append((tool, args))
        if tool.startswith(WRITE_TOOLS):
            raise AssertionError("Meta WRITE attempted: " + tool)
        if self.fail:
            raise pb.PipeboardError("Pipeboard HTTP 500")
        if tool == "get_account_info":
            return {"timezone_name": "America/New_York", "created_time": "2025-02-03T23:46:43-0500"}
        if tool == "get_campaigns":
            return {"data": [{"id": "c1", "name": "daycare ads pt1", "status": "PAUSED",
                              "objective": "OUTCOME_LEADS"}]}
        if tool == "get_insights":
            tr = args["time_range"]
            if args.get("time_breakdown"):
                return {"segmented_metrics": [{"period_start": tr["since"], "metrics": dict(ACCT_ROW)}]}
            if args["level"] == "account":
                return {"data": [dict(ACCT_ROW, spend=self.acct_spend)], "paging": {"cursors": {"after": "x"}}}
            return {"data": [AD1, AD2], "paging": {"cursors": {"after": "y"}}}
        raise AssertionError("unexpected tool " + tool)


class FeedBase(unittest.TestCase):
    def setUp(self):
        pb.clear_cache()
        daycare_growth._acct_meta_cache.clear()
        self.fake = FakePB()
        self.writes = {n: mock.MagicMock(name=n) for n in
                       ("set_status", "set_budget", "create_ad", "create_creative", "upload_image")}
        import daycare_ads_autopilot as ap
        self.ap_writes = {n: mock.MagicMock(name=n) for n in ("run_once", "approve", "_execute", "set_mode")}
        status = {"mode": "shadow", "config": {"tcpl": 40.0, "maxDaily": 100.0, "hour": 8},
                  "lastRun": {"day": "2026-10-17", "ts": 1, "mode": "shadow", "judge": "rules-only",
                              "note": "Nothing is delivering right now.", "counts": {}, "totalBudget": 0},
                  "lastRunDay": "2026-10-17", "lastError": None, "dueNow": False, "held": [],
                  "pending": [{"aid": "a1", "kind": "status", "level": "ad", "id": "9", "name": "Flyer B",
                               "from": "ACTIVE", "to": "PAUSED", "reason": "zero leads at 3xTCPL"}],
                  "recent": []}
        patches = [mock.patch.object(pb, "call", self.fake),
                   mock.patch.object(daycare_growth, "_daycare_creds",
                                     return_value={"PIPEBOARD_API_TOKEN": "unit-test-not-real",
                                                   "PIPEBOARD_AD_ACCOUNT_ID": "act_1175564690150627"}),
                   mock.patch.object(ap, "status", return_value=status)]
        patches += [mock.patch.object(pb, n, m) for n, m in self.writes.items()]
        patches += [mock.patch.object(ap, n, m) for n, m in self.ap_writes.items()]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.assert_no_meta_write)

    def assert_no_meta_write(self):
        for n, m in {**self.writes, **self.ap_writes}.items():
            self.assertFalse(m.called, f"{n} was called — a Meta write path ran")
        self.assertFalse([t for t, _ in self.fake.calls if t.startswith(WRITE_TOOLS)])

    def insight_calls(self):
        return [a for t, a in self.fake.calls if t == "get_insights"]


class FeedShape(FeedBase):
    def test_feed_shape_windows_and_autopilot(self):
        f = daycare_growth.ads_feed()
        self.assertTrue(f["configured"])
        self.assertFalse(f["unknown"])
        self.assertEqual([w["preset"] for w in f["windows"]], ["last_7d", "last_30d", "last_90d", "maximum"])
        w30 = f["windows"][1]
        self.assertIn("..", w30["window"])
        self.assertEqual(w30["totals"]["spend"], 30.0)                      # Meta account-level total
        self.assertEqual(w30["totals"]["leads"], 2)
        self.assertEqual(w30["totals"]["cpl"], 15.0)
        self.assertEqual(w30["totals"]["tcpl"], 30.0)                       # code default (2026-10-22: was 40)
        self.assertEqual(w30["reconciled"]["spend"], True)
        self.assertTrue(w30["reconciled"]["leadsMatchMetaResults"])
        self.assertIn("series", w30)                                         # selected window (default 30d)
        self.assertEqual(f["selected"], {"sameAs": "last_30d"})
        self.assertTrue(f["fetchedAt"].endswith(("-04:00", "-05:00")))
        self.assertEqual(f["tz"], "America/New_York")
        self.assertEqual(f["autopilot"]["mode"], "shadow")
        self.assertEqual(f["autopilot"]["pending"][0]["reason"], "zero leads at 3xTCPL")
        self.assertIn("not enrollments", f["evidence"].lower().replace("—", ""))
        blob = json.dumps(f)
        self.assertNotIn('"actions"', blob)                                  # no raw rows to the agents
        self.assertLess(len(blob), 9000)
        # maximum starts at the account's first day (created_time, account tz)
        self.assertTrue(f["windows"][3]["window"].startswith("Maximum 2025-02-03.."))

    def test_custom_selected_window_and_compare(self):
        f = daycare_growth.ads_feed(since="2026-08-21", until="2026-08-31", compare=True)
        self.assertEqual(f["selected"]["preset"], "custom")
        self.assertIn("compare", f["selected"])
        self.assertIn("deltaPct", f["selected"]["compare"])

    def test_report_for_the_card(self):
        out = daycare_growth.ads_overview(preset="last_30d", compare=True)
        a = out["analytics"]
        self.assertEqual(a["dataSource"], "live")
        self.assertEqual(a["via"], "pipeboard")
        for k in ("since", "until", "label", "tz", "preset"):
            self.assertIn(k, a["dateRange"])
        self.assertEqual(a["compare"]["delta"]["spend"], 0.0)                # same fake both periods
        self.assertEqual(len(a["series"]["points"]), 30)                     # zero-filled
        self.assertEqual(a["campaigns"][0]["status"], "paused")
        self.assertIn("evidence", a)
        bad = daycare_growth.ads_overview(since="2026-09-10", until="2026-09-01")
        self.assertFalse(bad["ok"])

    def test_reconciliation_flags_a_mismatch(self):
        self.fake.acct_spend = "45.00"                                      # ads only add up to 30
        a = daycare_growth.ads_overview(preset="last_7d")["analytics"]
        self.assertFalse(a["reconciled"]["spend"])
        self.assertEqual(a["totals"]["spend"], 45.0)                         # Meta's own total wins


class FeedFailures(FeedBase):
    def test_unknown_never_zero(self):
        self.fake.fail = True
        f = daycare_growth.ads_feed()
        self.assertTrue(f["unknown"])
        for w in f["windows"]:
            self.assertTrue(w["unknown"])
            self.assertNotIn("totals", w)
        out = daycare_growth.ads_overview(preset="last_30d")
        self.assertTrue(out["analytics"]["unknown"])
        self.assertNotIn("totals", out["analytics"])
        self.assertEqual(out["connection"]["source"], "read_failed")

    def test_auth_rejection_is_reported(self):
        def dead(tool, args=None, timeout=60):
            raise pb.PipeboardAuthError("Pipeboard rejected the token (HTTP 401)")
        with mock.patch.object(pb, "call", dead):
            f = daycare_growth.ads_feed()
        self.assertTrue(f["unknown"] and f["authError"])

    def test_unconfigured_says_unknown(self):
        with mock.patch.object(daycare_growth, "_daycare_creds", return_value={}):
            f = daycare_growth.ads_feed()
        self.assertFalse(f["configured"])
        self.assertTrue(f["unknown"])
        self.assertNotIn("windows", f)


class FreshAndPaging(FeedBase):
    def test_feed_is_always_fresh_but_card_is_cached(self):
        daycare_growth.ads_feed()
        n1 = len(self.insight_calls())
        daycare_growth.ads_feed()
        self.assertEqual(len(self.insight_calls()), 2 * n1, "agent packet served from cache")
        daycare_growth.ads_overview(preset="last_7d")
        n2 = len(self.insight_calls())
        daycare_growth.ads_overview(preset="last_7d")
        self.assertEqual(len(self.insight_calls()), n2, "card should reuse the 60 s cache")
        daycare_growth.ads_overview(preset="last_7d", fresh=True)
        self.assertGreater(len(self.insight_calls()), n2, "fresh=1 must bypass the cache")

    def test_paging_follows_cursor(self):
        pages = [{"data": [AD1], "paging": {"next": "https://graph/…", "cursors": {"after": "p2"}}},
                 {"data": [AD2], "paging": {"cursors": {"after": "p3"}}}]
        seen = []

        def paged(tool, args=None, timeout=60):
            seen.append(args.get("after"))
            return pages[len(seen) - 1]
        with mock.patch.object(pb, "call", paged):
            rows, trunc = pb.insights_paged("act_1", "2026-01-01", "2026-01-31", fresh=True)
        self.assertEqual(([r["ad_id"] for r in rows], trunc, seen), (["a1", "a2"], False, [None, "p2"]))

    def test_truncation_is_surfaced(self):
        endless = lambda tool, args=None, timeout=60: {  # noqa: E731
            "data": [AD1], "paging": {"next": "n", "cursors": {"after": "more"}}}
        with mock.patch.object(pb, "call", endless):
            rows, trunc = pb.insights_paged("act_1", "2026-01-01", "2026-01-31", fresh=True)
        self.assertTrue(trunc)
        self.assertEqual(len(rows), pb.MAX_PAGES)
        warned = lambda tool, args=None, timeout=60: {"data": [AD1], "warnings": ["full page"]}  # noqa: E731
        with mock.patch.object(pb, "call", warned):
            self.assertTrue(pb.insights_paged("act_1", "2026-01-01", "2026-01-31", fresh=True)[1])

    def test_result_leads(self):
        self.assertEqual(pb.result_leads(AD1), 2)
        self.assertIsNone(pb.result_leads(AD2))
        self.assertEqual(pb.result_leads({"results": [{"indicator": "actions:lead"}]}), 0)


class AgentsGetThePacket(FeedBase):
    MARK = "PACKET-MARKER-7731"

    def test_solomon_chat_prompt_contains_fresh_packet(self):
        import agents_hub
        import daycare_director
        import review_agent
        seen = {}

        def fake_claude(key, system, user, **kw):
            seen["system"] = system
            return "ok"
        with mock.patch.object(daycare_growth, "ads_feed", return_value={"marker": self.MARK}), \
             mock.patch.object(daycare_director, "_solomon_key", return_value="unit-test-key"), \
             mock.patch.object(review_agent, "_claude", fake_claude):
            agents_hub._director_chat("solomon", "how are the ads doing?", [])
        self.assertIn(self.MARK, seen["system"])
        self.assertIn("ONLY source of ad numbers", seen["system"])

    def test_brief_gather_uses_the_feed(self):
        import daycare_director
        eng = daycare_director.SolomonEngine.__new__(daycare_director.SolomonEngine)
        data, err = eng._gather_campaign()
        self.assertIsNone(err)
        self.assertTrue(data["connected"])
        self.assertEqual(data["feed"]["windows"][2]["preset"], "last_90d")
        self.fake.fail = True
        data, err = eng._gather_campaign()
        self.assertFalse(data["connected"])
        self.assertTrue(err)                     # the "do not fabricate" rail fires

    def test_idea_generator_reads_the_packet(self):
        import agency_eco
        got = {}

        def ideas(ctx, key, block=""):
            got["block"] = block
            return {"next": []}
        with mock.patch.object(daycare_growth, "ads_feed", return_value={"marker": self.MARK}), \
             mock.patch.object(agency_eco, "_agency_key", return_value=("unit-test-key", "t")), \
             mock.patch.object(agency_eco, "daycare_enrollment_ideas", ideas):
            out = daycare_growth.eco_ideas()
        self.assertIn(self.MARK, got["block"])
        self.assertEqual(out["dataSource"], "live")

    def test_share_reads_live_and_formats_unknown_ctr(self):
        import agent_coach
        sent = {}
        with mock.patch.object(agent_coach, "broadcast",
                               side_effect=lambda *a, **k: sent.update(text=a[1]) or {"ok": False}):
            daycare_growth.share_ad_results(days=30)
        self.assertIn("Meta via Pipeboard", sent["text"])
        self.assertNotIn("None%", sent["text"])

    def test_telegram_partner_is_pointed_at_the_feed_route(self):
        import telegram_agent
        with mock.patch.object(telegram_agent, "_scoped", return_value=[]), \
             mock.patch.object(telegram_agent, "_charter", return_value=""), \
             mock.patch.object(telegram_agent, "_context", return_value=""), \
             mock.patch.object(telegram_agent, "_playbook", return_value=""):
            sp = telegram_agent.system_prompt("solomon", "daycare")
        self.assertIn("/api/daycare/ads/feed", sp)

    def test_feed_route_is_registered_and_read_only(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "connector.py")) as fh:
            src = fh.read()
        self.assertIn('"/api/daycare/ads/feed": lambda session: daycare_growth.ads_feed(', src)
        self.assertEqual(src.count('"/api/daycare/ads/feed"'), 1, "feed must be a GET route only")

    def test_no_write_functions_referenced_by_the_read_path(self):
        import inspect
        for fn in (daycare_growth.ads_feed, daycare_growth.ads_report, daycare_growth._jobs,
                   daycare_growth._ads_overview_pb, daycare_growth._assemble):
            body = inspect.getsource(fn)
            for w in ("set_status", "set_budget", "create_ad", "create_creative", "upload_image",
                      "run_once", "approve(", "_execute"):
                self.assertNotIn(w, body, f"{fn.__name__} references {w}")


if __name__ == "__main__":
    unittest.main()
