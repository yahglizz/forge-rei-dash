import tempfile
import unittest
from pathlib import Path

import cost_tracker


class CostTrackerTest(unittest.TestCase):
    def setUp(self):
        self._orig_state = cost_tracker.STATE
        self._tmp = tempfile.TemporaryDirectory()
        cost_tracker.STATE = Path(self._tmp.name) / "cost_tracker.json"

    def tearDown(self):
        cost_tracker.STATE = self._orig_state
        self._tmp.cleanup()

    def test_anthropic_token_math(self):
        # 1M in + 1M out on sonnet = $3 + $15 = $18
        cost_tracker.record_anthropic("claude-sonnet-4-5", 1_000_000, 1_000_000)
        s = cost_tracker.status()
        self.assertAlmostEqual(18.0, s["today"]["claudeUSD"], places=2)
        self.assertEqual(1_000_000, s["today"]["claudeIn"])

    def test_by_model_counts_and_old_rows_still_load(self):
        # an old day row (no byModel) must load and keep accumulating
        cost_tracker._save({"days": {cost_tracker._today_key(): {"claudeUSD": 1.0, "claudeIn": 5}}})
        cost_tracker.record_anthropic("claude-haiku-5-5", 1000, 100)
        cost_tracker.record_anthropic("claude-haiku-5-5", 1000, 100)
        cost_tracker.record_anthropic("claude-sonnet-5-5", 1000, 100)
        s = cost_tracker.status()
        bm = s["today"]["byModel"]
        self.assertEqual(2, bm["claude-haiku-5-5"]["calls"])
        self.assertEqual(1, bm["claude-sonnet-5-5"]["calls"])
        self.assertGreater(bm["claude-sonnet-5-5"]["usd"], 0)
        self.assertEqual(2, s["mtd"]["byModel"]["claude-haiku-5-5"]["calls"])
        # a day row without byModel reads as {}
        cost_tracker._save({"days": {cost_tracker._today_key(): {"claudeUSD": 1.0}}})
        self.assertEqual({}, cost_tracker.status()["today"]["byModel"])

    def test_haiku_5_5_has_two_rate_cards_split_at_a_100k_prompt(self):
        day = lambda: cost_tracker.status()["today"]["claudeUSD"]
        self.assertEqual((0.10, 0.50), cost_tracker._price_for("claude-haiku-5-5"))
        self.assertEqual((0.10, 0.50), cost_tracker._price_for("claude-haiku-5-5", 100_000))
        self.assertEqual((0.50, 2.50), cost_tracker._price_for("claude-haiku-5-5", 100_001))
        self.assertEqual((1.0, 5.0), cost_tracker._price_for("claude-haiku-4-5-20251001", 900_000))
        self.assertEqual((2.0, 10.0), cost_tracker._price_for("claude-sonnet-5-5", 900_000))
        cost_tracker.record_anthropic("claude-haiku-5-5", 100_000, 1_000_000)      # $0.01 + $0.50
        self.assertAlmostEqual(0.51, day(), places=4)
        before = day()                                                             # cached tokens count
        cost_tracker.record_anthropic("claude-haiku-5-5", 1, 0, cache_read_tokens=100_000)
        self.assertAlmostEqual(0.005, day() - before, places=4)                    # 0.1 x $0.50 card
        before = day()
        cost_tracker.record_anthropic("claude-haiku-5-5", 0, 0, cache_write_tokens=1_000_000)
        self.assertAlmostEqual(0.625, day() - before, places=4)                    # 1.25 x $0.50 card

    def test_haiku_priced_cheaper_than_sonnet(self):
        cost_tracker.record_anthropic("claude-haiku-4-5-20251001", 1_000_000, 0)
        s = cost_tracker.status()
        self.assertAlmostEqual(1.0, s["today"]["claudeUSD"], places=2)

    def test_current_anthropic_model_prices(self):
        self.assertEqual((5.0, 25.0), cost_tracker._price_for("claude-opus-4-8"))
        self.assertEqual((10.0, 50.0), cost_tracker._price_for("claude-fable-5"))
        self.assertEqual((2.0, 10.0), cost_tracker._price_for("claude-sonnet-5"))
        self.assertEqual((3.0, 15.0), cost_tracker._price_for("claude-sonnet-4-5"))

    def test_sms_counter_and_rate(self):
        cost_tracker.set_settings(sms_rate=0.01)
        for _ in range(5):
            cost_tracker.record_sms(1)
        s = cost_tracker.status()
        self.assertEqual(5, s["today"]["sms"])
        self.assertAlmostEqual(0.05, s["today"]["usd"], places=4)

    def test_manual_fixed_persists_and_removes(self):
        cost_tracker.set_fixed("digitalocean", 24, "droplet")
        s = cost_tracker.status()
        self.assertAlmostEqual(24.0, s["fixedMonthlyUSD"], places=2)
        self.assertIn("digitalocean", s["fixed"])
        cost_tracker.set_fixed("digitalocean", 0)          # <=0 removes
        s = cost_tracker.status()
        self.assertEqual(0.0, s["fixedMonthlyUSD"])

    def test_bad_manual_input_rejected(self):
        self.assertIn("error", cost_tracker.set_fixed("", 5))
        self.assertIn("error", cost_tracker.set_fixed("x", "abc"))

    def test_cap_alert_thresholds(self):
        cost_tracker.set_settings(monthly_cap_usd=10)
        cost_tracker.record_anthropic("claude-sonnet-4-5", 0, 600_000)  # $9 = 90% > 80%
        s = cost_tracker.status()
        self.assertTrue(s["capWarn"])
        self.assertFalse(s["capAlert"])
        cost_tracker.record_anthropic("claude-sonnet-4-5", 0, 100_000)  # +$1.5 → over cap
        s = cost_tracker.status()
        self.assertTrue(s["capAlert"])

    def test_zero_usage_noop(self):
        cost_tracker.record_anthropic("claude-sonnet-4-5", 0, 0)
        s = cost_tracker.status()
        self.assertEqual(0, s["today"]["claudeIn"])

    def test_never_raises_on_garbage(self):
        cost_tracker.record_anthropic(None, "x", None)     # swallowed
        cost_tracker.record_sms("y")                        # swallowed
        s = cost_tracker.status()
        self.assertTrue(s["ok"])

    def test_digest_line(self):
        cost_tracker.record_sms(2)
        line = cost_tracker.digest_line()
        self.assertIn("Spend today", line)


if __name__ == "__main__":
    unittest.main()
