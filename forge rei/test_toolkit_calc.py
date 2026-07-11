import tempfile
import unittest
from pathlib import Path

import deals
import toolkit_calc


class ToolkitCalcTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_state = toolkit_calc.STATE
        self._orig_deals = deals.STATE
        toolkit_calc.STATE = Path(self._tmp.name) / "toolkit_calc.json"
        deals.STATE = Path(self._tmp.name) / "deals.json"

    def tearDown(self):
        toolkit_calc.STATE = self._orig_state
        deals.STATE = self._orig_deals
        self._tmp.cleanup()

    # ---- rates store ----
    def test_default_rates(self):
        r = toolkit_calc.get_rates()
        self.assertEqual(40.0, r["moderate"])
        self.assertEqual(100.0, r["full_gut"])

    def test_set_rates_persists_and_ignores_junk(self):
        toolkit_calc.set_rates({"moderate": 45, "bogus": 99, "light": -5})
        r = toolkit_calc.get_rates()
        self.assertEqual(45.0, r["moderate"])
        self.assertEqual(20.0, r["light"])           # negative ignored -> default
        self.assertNotIn("bogus", r)

    def test_config_shape(self):
        c = toolkit_calc.config()
        self.assertIn("rates", c)
        self.assertIn("moderate", c["hints"])

    # ---- repair estimator ----
    def test_repair_estimate_rounds_up_to_500(self):
        e = toolkit_calc.estimate_repairs(1234, "light")     # 24,680 -> 25,000
        self.assertEqual(25000, e["total"])

    def test_repair_estimate_exact_multiple(self):
        e = toolkit_calc.estimate_repairs(1200, "moderate")  # 48,000 stays
        self.assertEqual(48000, e["total"])
        self.assertEqual(40.0, e["perSqft"])

    def test_repair_estimate_bad_inputs(self):
        self.assertIn("error", toolkit_calc.estimate_repairs(1000, "luxury"))
        self.assertIn("error", toolkit_calc.estimate_repairs(0, "light"))

    # ---- seller finance ----
    def test_seller_finance_amortization(self):
        # 100k price, 20k down, 6%, 30y -> classic $479.64/mo on the 80k note
        sf = toolkit_calc.seller_finance(100000, 20000, 6, 30)
        self.assertAlmostEqual(479.64, sf["monthly"], places=2)
        self.assertEqual(360, sf["months"])
        self.assertAlmostEqual(80000.0, sf["loan"], places=2)

    def test_seller_finance_zero_rate(self):
        sf = toolkit_calc.seller_finance(60000, 0, 0, 5)     # 60k / 60 months
        self.assertAlmostEqual(1000.0, sf["monthly"], places=2)
        self.assertAlmostEqual(0.0, sf["totalInterest"], places=2)

    def test_seller_finance_balloon(self):
        sf = toolkit_calc.seller_finance(100000, 20000, 6, 30, balloon_years=5)
        self.assertEqual(60, sf["balloonMonths"])
        self.assertAlmostEqual(74443, sf["balloonBalance"], delta=60)

    def test_seller_finance_bad_loan(self):
        self.assertIn("error", toolkit_calc.seller_finance(0, 0, 6, 30))
        self.assertIn("error", toolkit_calc.seller_finance(50000, 50000, 6, 30))

    # ---- subject-to ----
    def test_subto_flow_and_coc(self):
        st = toolkit_calc.subject_to(900, 1400, balance=120000,
                                     entry_fee=5000, arrears=3000, closing_costs=2000)
        self.assertAlmostEqual(500.0, st["monthlyFlow"], places=2)
        self.assertAlmostEqual(10000.0, st["entryCash"], places=2)
        self.assertAlmostEqual(60.0, st["cashOnCash"], places=1)   # 6000/10000

    def test_subto_zero_entry_no_coc(self):
        st = toolkit_calc.subject_to(900, 1400)
        self.assertIsNone(st["cashOnCash"])
        self.assertIn("error", toolkit_calc.subject_to(0, 1400))

    # ---- novation ----
    def test_novation_profit_and_compare(self):
        # ARV 200k, repairs 20k, seller nets 140k, 8% selling costs = 16k -> 24k
        nv = toolkit_calc.novation(200000, 20000, 140000, wholesale_fee=10000)
        self.assertAlmostEqual(24000.0, nv["profit"], places=2)
        self.assertAlmostEqual(14000.0, nv["vsWholesale"], places=2)

    def test_novation_requires_inputs(self):
        self.assertIn("error", toolkit_calc.novation(0, 0, 140000))

    # ---- dual-view ROI ----
    def test_internal_view_matches_ui_mao(self):
        iv = toolkit_calc.internal_view(200000, 30000, 10000, 70, asking=90000)
        self.assertAlmostEqual(100000.0, iv["mao"], places=2)
        self.assertAlmostEqual(10000.0, iv["spread"], places=2)
        self.assertAlmostEqual(110000.0, iv["buyerPrice"], places=2)

    def test_buyer_view_hides_fee_and_computes_roi(self):
        # ARV 200k, buyer pays 120k, repairs 30k:
        # buy close 2,400 · sell close 16,000 · cash in 152,400 · profit 31,600
        bv = toolkit_calc.buyer_view(200000, 120000, 30000)
        self.assertAlmostEqual(31600.0, bv["profit"], places=2)
        self.assertAlmostEqual(20.7, bv["roiPct"], places=1)
        self.assertNotIn("fee", bv)

    def test_buyer_view_bad_inputs(self):
        self.assertIn("error", toolkit_calc.buyer_view(0, 120000, 0))

    # ---- evaluate aggregator ----
    def test_evaluate_returns_only_requested_sections(self):
        out = toolkit_calc.evaluate({"arv": 200000, "repairs": 30000, "fee": 10000,
                                     "pct": 70, "sqft": 1000, "tier": "light"})
        self.assertIn("internal", out)
        self.assertIn("repair", out)
        self.assertIn("buyer", out)          # derived from internal buyerPrice
        self.assertNotIn("subto", out)
        self.assertNotIn("sellerFinance", out)
        self.assertAlmostEqual(110000.0, out["buyer"]["purchase"], places=2)

    def test_evaluate_empty_body(self):
        self.assertEqual({}, toolkit_calc.evaluate({}))
        self.assertEqual({}, toolkit_calc.evaluate(None))

    # ---- snapshot rides the deal record ----
    def test_save_snapshot_rides_deal_record(self):
        r = toolkit_calc.save_snapshot({"contactId": "c1", "arv": 200000,
                                        "repairs": 30000, "fee": 10000, "pct": 70})
        self.assertTrue(r["ok"])
        d = deals.get("c1")
        self.assertAlmostEqual(100000.0,
                               d["toolkitCalc"]["results"]["internal"]["mao"])

    def test_save_snapshot_requires_contact(self):
        self.assertIn("error", toolkit_calc.save_snapshot({"arv": 1}))


class ArvFinderTest(unittest.TestCase):
    """AI ARV finder parse + guards (2026-07-11)."""

    def test_parse_plain_json(self):
        p = toolkit_calc._parse_arv_json('{"arv": 150000, "confidence": "medium"}')
        self.assertEqual(150000, p["arv"])

    def test_parse_json_in_fences_and_prose(self):
        t = ('Sure, here it is:\n```json\n{"arv": 150000, "low": 140000, '
             '"high": 160000, "confidence": "high", "comps": []}\n```')
        p = toolkit_calc._parse_arv_json(t)
        self.assertEqual(160000, p["high"])

    def test_parse_garbage_returns_none(self):
        self.assertIsNone(toolkit_calc._parse_arv_json("no json here"))
        self.assertIsNone(toolkit_calc._parse_arv_json(""))

    def test_find_arv_rejects_short_address(self):
        self.assertIn("error", toolkit_calc.find_arv("short"))
        self.assertIn("error", toolkit_calc.find_arv(""))


if __name__ == "__main__":
    unittest.main()
