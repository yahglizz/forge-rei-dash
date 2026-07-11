# Phase 1 — Deal Calculator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Deal Calc tab with a condition-tier repair estimator, creative-finance math (subject-to / seller finance / novation), and a dual-view ROI (internal vs buyer-facing), with Python as the single source of truth for all money math.

**Architecture:** `toolkit_calc.py` owns every formula and a tiny JSON store for editable $/sqft repair rates; the UI (`toolkit_calc.jsx`, mounted inside the existing `DealCalcPage`) posts inputs to `/api/toolkit/calc/eval` (debounced) and renders whatever sections come back. Per-deal snapshots ride the existing `deals.py` record via `deals.upsert` — no second deal store. Buyer Blast (Phase 2) will reuse `toolkit_calc.buyer_view()` server-side, which is why math lives in Python, not JSX.

**Tech Stack:** Python 3 stdlib only (no pip installs), `unittest`, static React UMD + in-browser Babel (no build), window-globals JSX pattern.

## Global Constraints

- **NO new pip dependencies. NO new npm dependencies.** Stdlib + existing patterns only.
- **This directory is NOT a git repository.** Skip all commit steps; the deploy gate + PLAN.md session log are the record. Do not `git init`.
- Additive only — never remove or break an existing feature (root `CLAUDE.md` rule 5).
- JSX conventions or white-screen: hook aliases for toolkit_calc.jsx are `useStateTk/useMemoTk/useEffectTk/useRefTk`; all top-level names prefixed `Tk`; export via `Object.assign(window, {...})`; NO computed JSX tags (resolve `const Ico = Icons.X` first); script tag goes BEFORE `app.jsx`.
- Validate every touched file: `python3 -c "import ast; ast.parse(open('FILE').read())"` for .py, `node deploy/valjsx.js FILE.jsx` for .jsx.
- Working dir for all commands: `/Users/yg4st/forge rei dash/forge rei` (path has spaces — always quote).
- Tests: `unittest`, monkeypatch `STATE` to a tempdir in `setUp` (copy `test_cost_tracker.py` style). Run: `python3 -m unittest test_toolkit_calc -v`.
- Buyer view must NEVER expose the assignment fee — it shows `purchase price` (= contract price + fee) as one number.
- All `/api/toolkit/calc/*` endpoints are operator-only dashboard tools — no outbound actions, no GHL writes, so no approval gating needed. `save` writes only to the local deals store.

---

### Task 1: Store + editable repair rates

**Files:**
- Modify: `toolkit_calc.py` (replace stub body, keep a docstring)
- Create: `test_toolkit_calc.py`

**Interfaces:**
- Produces: `STATE` (Path, monkeypatchable), `DEFAULT_RATES` dict, `_num(v, dflt=0.0) -> float`, `get_rates() -> dict`, `set_rates(rates: dict) -> dict`, `config() -> dict`
- Consumes: `forge_atomic.atomic_write_json` (existing)

- [ ] **Step 1: Write the failing tests**

Create `test_toolkit_calc.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && python3 -m unittest test_toolkit_calc -v`
Expected: ERRORS — `AttributeError: module 'toolkit_calc' has no attribute 'STATE'` (stub has no code).

- [ ] **Step 3: Write the implementation**

Replace `toolkit_calc.py` entirely with:

```python
"""Wholesaler Toolkit — Deal Calculator engine (Phase 1).

Single source of truth for the toolkit money math: repair estimator
(condition tier x $/sqft), creative finance (subject-to / seller finance /
novation) and the dual-view ROI payload (internal vs buyer-facing). The UI
posts inputs to /api/toolkit/calc/eval and renders whatever comes back.
Buyer Blast (Phase 2) reuses buyer_view() server-side for deal sheets.

Store: marcus_state/toolkit_calc.json — editable $/sqft repair rates only.
Per-deal snapshots ride the existing deals.py record (deals.upsert), so
there is no second deal store.
"""
import json
import threading
from pathlib import Path

import deals
import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "toolkit_calc.json"
_LOCK = threading.RLock()

# $/sqft by condition tier — editable via set_rates; seeded market-typical.
DEFAULT_RATES = {"light": 20.0, "moderate": 40.0, "heavy": 65.0, "full_gut": 100.0}
TIER_HINTS = {
    "light": "paint, carpet, fixtures",
    "moderate": "kitchen/bath, flooring",
    "heavy": "roof, HVAC, systems",
    "full_gut": "down to studs",
}


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _num(v, dflt=0.0):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return dflt


def get_rates():
    rates = dict(DEFAULT_RATES)
    for k, v in (_load().get("rates") or {}).items():
        if k in rates and _num(v) > 0:
            rates[k] = _num(v)
    return rates


def set_rates(rates):
    with _LOCK:
        d = _load()
        cur = d.get("rates") or {}
        for k, v in (rates or {}).items():
            if k in DEFAULT_RATES and _num(v) > 0:
                cur[k] = _num(v)
        d["rates"] = cur
        _save(d)
    return {"ok": True, "rates": get_rates()}


def config():
    return {"rates": get_rates(), "tiers": list(DEFAULT_RATES.keys()),
            "hints": TIER_HINTS}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && python3 -m unittest test_toolkit_calc -v`
Expected: `OK` — 3 tests pass.

- [ ] **Step 5: Validate syntax**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && python3 -c "import ast; ast.parse(open('toolkit_calc.py').read())" && python3 -c "import ast; ast.parse(open('test_toolkit_calc.py').read())"`
Expected: silent success.

---

### Task 2: Repair estimator

**Files:**
- Modify: `toolkit_calc.py` (append function)
- Modify: `test_toolkit_calc.py` (append tests inside the class)

**Interfaces:**
- Produces: `estimate_repairs(sqft, tier, rates=None) -> dict` with keys `tier, sqft, perSqft, total` (or `error`). Total rounds UP to nearest $500 (estimate high — house rule).
- Consumes: `get_rates()`, `_num()` from Task 1.

- [ ] **Step 1: Append failing tests** (inside `ToolkitCalcTest`, before `if __name__`)

```python
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
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: ... no attribute 'estimate_repairs'`)

- [ ] **Step 3: Append implementation** to `toolkit_calc.py`:

```python
def estimate_repairs(sqft, tier, rates=None):
    """Condition tier x $/sqft x sqft, rounded UP to the nearest $500
    (always estimate repairs high — buyers verify at the table)."""
    rates = rates or get_rates()
    tier = (tier or "").strip().lower().replace(" ", "_").replace("-", "_")
    if tier not in rates:
        return {"error": "unknown tier '%s'" % tier, "tiers": list(rates.keys())}
    sq = _num(sqft)
    if sq <= 0:
        return {"error": "sqft required"}
    per = rates[tier]
    total = int(-(-(sq * per) // 500) * 500)     # ceil to $500
    return {"tier": tier, "sqft": sq, "perSqft": per, "total": total}
```

- [ ] **Step 4: Run tests — expect OK (6 tests)**

---

### Task 3: Seller-finance amortization

**Files:**
- Modify: `toolkit_calc.py`, `test_toolkit_calc.py`

**Interfaces:**
- Produces: `seller_finance(price, down=0, rate_pct=0, term_years=30, balloon_years=None) -> dict` with keys `loan, monthly, months, totalInterest` (+ `balloonMonths, balloonBalance, totalInterestToBalloon` when balloon set; or `error`).

- [ ] **Step 1: Append failing tests**

```python
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
```

- [ ] **Step 2: Run — expect FAIL** (no attribute `seller_finance`)

- [ ] **Step 3: Append implementation**

```python
def seller_finance(price, down=0, rate_pct=0, term_years=30, balloon_years=None):
    """Amortized seller-carry note: monthly payment, total interest, and the
    balloon payoff if a balloon year is set. Standard amortization formula."""
    loan = _num(price) - _num(down)
    if loan <= 0 or _num(term_years) <= 0:
        return {"error": "price, down and term must make a positive loan"}
    n = int(round(_num(term_years) * 12))
    r = _num(rate_pct) / 100.0 / 12.0
    pmt = loan * r / (1 - (1 + r) ** (-n)) if r > 0 else loan / n
    out = {"loan": round(loan, 2), "monthly": round(pmt, 2), "months": n,
           "totalInterest": round(pmt * n - loan, 2)}
    if balloon_years and _num(balloon_years) > 0:
        k = min(n, int(round(_num(balloon_years) * 12)))
        if r > 0:
            bal = loan * (1 + r) ** k - pmt * (((1 + r) ** k - 1) / r)
        else:
            bal = loan - pmt * k
        out["balloonMonths"] = k
        out["balloonBalance"] = round(max(0.0, bal), 2)
        out["totalInterestToBalloon"] = round(pmt * k + max(0.0, bal) - loan, 2)
    return out
```

- [ ] **Step 4: Run tests — expect OK (10 tests)**

---

### Task 4: Subject-to + novation

**Files:**
- Modify: `toolkit_calc.py`, `test_toolkit_calc.py`

**Interfaces:**
- Produces: `subject_to(piti, rent, balance=0, entry_fee=0, arrears=0, closing_costs=0) -> dict` with keys `entryCash, monthlyFlow, annualFlow, loanBalance, cashOnCash` (cashOnCash is `None` when entry is 0 or flow ≤ 0).
- Produces: `novation(arv, repairs, seller_price, sell_cost_pct=8.0, wholesale_fee=None) -> dict` with keys `arv, sellerPrice, sellingCosts, repairs, profit` (+ `wholesaleFee, vsWholesale` when fee given).

- [ ] **Step 1: Append failing tests**

```python
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
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Append implementation**

```python
def subject_to(piti, rent, balance=0, entry_fee=0, arrears=0, closing_costs=0):
    """Take over the existing payments: cash to get in + monthly spread."""
    piti_n, rent_n = _num(piti), _num(rent)
    if piti_n <= 0:
        return {"error": "monthly PITI required"}
    entry = _num(arrears) + _num(entry_fee) + _num(closing_costs)
    flow = rent_n - piti_n
    out = {"entryCash": round(entry, 2), "monthlyFlow": round(flow, 2),
           "annualFlow": round(flow * 12, 2), "loanBalance": _num(balance)}
    out["cashOnCash"] = round(flow * 12 / entry * 100, 1) if entry > 0 and flow > 0 else None
    return out


def novation(arv, repairs, seller_price, sell_cost_pct=8.0, wholesale_fee=None):
    """Novation net vs a straight wholesale fee. Selling costs default 8%
    of ARV (6% agent + ~2% closing)."""
    arv_n, sp = _num(arv), _num(seller_price)
    if arv_n <= 0 or sp <= 0:
        return {"error": "arv and seller price required"}
    costs = arv_n * _num(sell_cost_pct, 8.0) / 100.0
    profit = arv_n - _num(repairs) - costs - sp
    out = {"arv": arv_n, "sellerPrice": sp, "sellingCosts": round(costs, 2),
           "repairs": _num(repairs), "profit": round(profit, 2)}
    if wholesale_fee is not None and _num(wholesale_fee) > 0:
        out["wholesaleFee"] = _num(wholesale_fee)
        out["vsWholesale"] = round(profit - _num(wholesale_fee), 2)
    return out
```

- [ ] **Step 4: Run tests — expect OK (14 tests)**

---

### Task 5: Dual-view ROI (internal + buyer)

**Files:**
- Modify: `toolkit_calc.py`, `test_toolkit_calc.py`

**Interfaces:**
- Produces: `internal_view(arv, repairs, fee, pct, asking=None) -> dict` with keys `arv, repairs, fee, pct, mao, buyerPrice` (+ `asking, spread`). MAO formula MUST match the UI: `max(0, arv*pct/100 - repairs - fee)`.
- Produces: `buyer_view(arv, purchase_price, repairs, holding=0, buy_close_pct=2.0, sell_close_pct=8.0) -> dict` with keys `arv, purchase, repairs, buyClosing, sellClosing, holding, cashIn, profit, roiPct, marginPct`. NEVER includes a fee key — purchase_price is contract price + fee as ONE number.

- [ ] **Step 1: Append failing tests**

```python
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
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Append implementation**

```python
def internal_view(arv, repairs, fee, pct, asking=None):
    """YOUR side of the deal: MAO (same formula as the Deal Calc UI), spread,
    and what the buyer pays (contract + fee)."""
    arv_n, rep = _num(arv), _num(repairs)
    fee_n, pct_n = _num(fee), _num(pct, 70.0) or 70.0
    mao = max(0.0, arv_n * pct_n / 100.0 - rep - fee_n)
    out = {"arv": arv_n, "repairs": rep, "fee": fee_n, "pct": pct_n,
           "mao": round(mao, 2), "buyerPrice": round(mao + fee_n, 2)}
    ask = _num(asking)
    if ask > 0:
        out["asking"] = ask
        out["spread"] = round(mao - ask, 2)
    return out


def buyer_view(arv, purchase_price, repairs, holding=0,
               buy_close_pct=2.0, sell_close_pct=8.0):
    """The flip math a CASH BUYER sees on a deal sheet. purchase_price is what
    the buyer pays (your contract price + assignment fee, one number — the fee
    itself is never exposed here)."""
    arv_n, pp = _num(arv), _num(purchase_price)
    if arv_n <= 0 or pp <= 0:
        return {"error": "arv and purchase price required"}
    rep, hold = _num(repairs), _num(holding)
    buy_close = pp * _num(buy_close_pct, 2.0) / 100.0
    sell_close = arv_n * _num(sell_close_pct, 8.0) / 100.0
    cash_in = pp + rep + buy_close + hold
    profit = arv_n - pp - rep - buy_close - sell_close - hold
    return {"arv": arv_n, "purchase": pp, "repairs": rep,
            "buyClosing": round(buy_close, 2), "sellClosing": round(sell_close, 2),
            "holding": hold, "cashIn": round(cash_in, 2), "profit": round(profit, 2),
            "roiPct": round(profit / cash_in * 100, 1) if cash_in > 0 else None,
            "marginPct": round(profit / arv_n * 100, 1)}
```

- [ ] **Step 4: Run tests — expect OK (17 tests)**

---

### Task 6: `evaluate()` aggregator + `save_snapshot()`

**Files:**
- Modify: `toolkit_calc.py`, `test_toolkit_calc.py`

**Interfaces:**
- Produces: `evaluate(body: dict) -> dict` — returns only the sections the body has inputs for, keyed `repair, subto, sellerFinance, novation, internal, buyer`. The UI and Task 7's `/api/toolkit/calc/eval` consume this.
  - `repair` when `sqft > 0` and `tier` set
  - `subto` when `body["subto"]["piti"] > 0` (subto keys: `piti, rent, balance, entryFee, arrears, closingCosts`)
  - `sellerFinance` when `body["sellerFinance"]["price"] > 0` (keys: `price, down, ratePct, termYears, balloonYears`)
  - `novation` when `body["novation"]["sellerPrice"] > 0` (keys: `sellerPrice, sellCostPct`; arv/repairs/fee come from the top level)
  - `internal` when `arv > 0`; `buyer` derived using `body["buyerPrice"]` if given, else `internal["buyerPrice"]`
- Produces: `save_snapshot(body: dict) -> dict` — persists `{inputs, results}` as `toolkitCalc` on the deal record via `deals.upsert(contactId, toolkitCalc=...)`.

- [ ] **Step 1: Append failing tests**

```python
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
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Append implementation**

```python
def evaluate(body):
    """One POST from the UI -> every section it has inputs for."""
    body = body or {}
    out = {}
    if _num(body.get("sqft")) > 0 and body.get("tier"):
        out["repair"] = estimate_repairs(body.get("sqft"), body.get("tier"))
    st = body.get("subto") or {}
    if _num(st.get("piti")) > 0:
        out["subto"] = subject_to(st.get("piti"), st.get("rent"), st.get("balance"),
                                  st.get("entryFee"), st.get("arrears"),
                                  st.get("closingCosts"))
    sf = body.get("sellerFinance") or {}
    if _num(sf.get("price")) > 0:
        out["sellerFinance"] = seller_finance(sf.get("price"), sf.get("down"),
                                              sf.get("ratePct"),
                                              sf.get("termYears") or 30,
                                              sf.get("balloonYears"))
    nv = body.get("novation") or {}
    if _num(nv.get("sellerPrice")) > 0:
        out["novation"] = novation(body.get("arv"), body.get("repairs"),
                                   nv.get("sellerPrice"),
                                   nv.get("sellCostPct") or 8.0, body.get("fee"))
    if _num(body.get("arv")) > 0:
        out["internal"] = internal_view(body.get("arv"), body.get("repairs"),
                                        body.get("fee"), body.get("pct"),
                                        body.get("asking"))
        pp = _num(body.get("buyerPrice")) or out["internal"]["buyerPrice"]
        if pp > 0:
            out["buyer"] = buyer_view(body.get("arv"), pp, body.get("repairs"),
                                      body.get("holding"))
    return out


def save_snapshot(body):
    """Persist the whole calc (incl. creative scenarios) onto the deal record."""
    body = body or {}
    cid = body.get("contactId")
    if not cid:
        return {"error": "contactId required"}
    results = evaluate(body)
    keep = ("arv", "repairs", "fee", "pct", "asking", "sqft", "tier",
            "buyerPrice", "holding", "subto", "sellerFinance", "novation")
    r = deals.upsert(cid, toolkitCalc={"inputs": {k: body.get(k) for k in keep},
                                       "results": results})
    if isinstance(r, dict) and r.get("error"):
        return r
    return {"ok": True, "results": results}
```

- [ ] **Step 4: Run full suite — expect OK (21 tests)**

- [ ] **Step 5: Regression check — existing tests still pass**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && python3 -m unittest test_cost_tracker test_sms_guard -v 2>&1 | tail -3`
Expected: `OK` (no interference).

---

### Task 7: Connector wiring (routes)

**Files:**
- Modify: `connector.py` (5 small edits, exact anchors below)

**Interfaces:**
- Consumes: `toolkit_calc.config/evaluate/set_rates/save_snapshot` (Tasks 1–6)
- Produces: `GET /api/toolkit/calc/config`, `POST /api/toolkit/calc/{eval,rates,save}` — consumed by Task 8's JSX.

- [ ] **Step 1: Add import.** Find line 1041 (`import buyers`) and add after it:

```python
import buyers         # noqa: E402  — cash-buyer list + buy-box match (dispo half)
import toolkit_calc   # noqa: E402  — Wholesaler Toolkit: calculator math + rates store
```
(old_string is the existing `import buyers` line; new_string is both lines.)

- [ ] **Step 2: Add the GET handler.** Insert immediately before `def api_buyers_list(_q):` (~line 1087):

```python
def api_toolkit_calc_config(_q):
    return toolkit_calc.config()


```

- [ ] **Step 3: Register GET route.** In the `ROUTES` dict find `"/api/deals/get": api_deals_get,` (line ~2005) and add after it:

```python
    "/api/toolkit/calc/config": api_toolkit_calc_config,
```

- [ ] **Step 4: Add to NO_CACHE** (so rate edits show instantly). Find the NO_CACHE line containing `"/api/deals/list", "/api/deals/get", "/api/contract/config", "/api/contract/status",` (~line 2058) and append to the set:

```python
            "/api/toolkit/calc/config",
```

- [ ] **Step 5: POST allowlist.** In the `do_POST` allowlist tuple find `"/api/deals/save",` (~line 2334) and add after it:

```python
                                   "/api/toolkit/calc/eval",
                                   "/api/toolkit/calc/rates",
                                   "/api/toolkit/calc/save",
```

- [ ] **Step 6: POST dispatch.** Find `elif parsed.path == "/api/deals/save":` (~line 2564) and insert BEFORE it:

```python
            elif parsed.path == "/api/toolkit/calc/eval":
                result = toolkit_calc.evaluate(body)
            elif parsed.path == "/api/toolkit/calc/rates":
                result = toolkit_calc.set_rates(body.get("rates") or {})
            elif parsed.path == "/api/toolkit/calc/save":
                result = toolkit_calc.save_snapshot(body)
```

- [ ] **Step 7: Validate + smoke-test the live routes**

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
python3 -c "import ast; ast.parse(open('connector.py').read())"
FORGE_MARCUS=0 FORGE_PORT=7801 python3 connector.py &   # throwaway port
sleep 2
curl -s localhost:7801/api/toolkit/calc/config
curl -s -X POST localhost:7801/api/toolkit/calc/eval -d '{"arv":200000,"repairs":30000,"fee":10000,"pct":70,"sqft":1000,"tier":"light"}'
kill %1
```
Expected: config returns `{"rates": {"light": 20.0, ...}}`; eval returns `internal` (mao 100000), `repair` (total 20000), `buyer` (purchase 110000).

---

### Task 8: `toolkit_calc.jsx` — the UI panels

**Files:**
- Modify: `toolkit_calc.jsx` (replace stub with the component)

**Interfaces:**
- Consumes: `POST /api/toolkit/calc/eval|rates|save`, `GET /api/toolkit/calc/config` (Task 7); `window.apiPost`, `window.fmtMoney`, `window.Icons` (existing).
- Produces: `window.TkCalcPanels` — props `{arv, repairs, fee, pct, asking, contactId, onApplyRepairs}` (numbers, contactId string|null, onApplyRepairs(total:number)). Task 9 mounts it.

- [ ] **Step 1: Replace the stub** with this complete component:

```jsx
// Wholesaler Toolkit — Deal Calculator panels (Phase 1).
// Mounted inside DealCalcPage (pages.jsx). Math lives in toolkit_calc.py —
// this posts inputs to /api/toolkit/calc/eval (debounced) and renders results.
// Hook aliases: useStateTk/useMemoTk/useEffectTk/useRefTk. Globals prefixed Tk.
const { useState: useStateTk, useEffect: useEffectTk, useRef: useRefTk } = React;

const TK_BOX = { background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 13, padding: 16 };
const TK_TIER_LABEL = { light: "Light", moderate: "Moderate", heavy: "Heavy", full_gut: "Full gut" };

function TkIn(label, value, onChange, opts) {
  opts = opts || {};
  return (
    <div style={{ flex: 1, minWidth: 130 }}>
      <div className="faint" style={{ fontSize: 11.5, marginBottom: 5 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "center", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 10, padding: "0 11px" }}>
        {opts.prefix && <span className="faint" style={{ fontSize: 14 }}>{opts.prefix}</span>}
        <input type="number" value={value} onChange={(e) => onChange(e.target.value)} placeholder={opts.placeholder || "0"}
          style={{ flex: 1, background: "none", border: "none", outline: "none", color: "var(--text)", fontSize: 14, fontWeight: 600, padding: "10px 6px", width: "100%" }} />
        {opts.suffix && <span className="faint" style={{ fontSize: 14 }}>{opts.suffix}</span>}
      </div>
    </div>
  );
}

function TkRow(label, val, opts) {
  opts = opts || {};
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
      <span className="faint">{label}</span>
      <span className="tabnum" style={{ fontWeight: opts.bold ? 700 : 500, color: opts.color || "var(--text)" }}>{val}</span>
    </div>
  );
}

function TkCalcPanels(props) {
  const Icons = window.Icons;
  const M = window.fmtMoney;
  // repair estimator
  const [sqft, setSqft] = useStateTk("");
  const [tier, setTier] = useStateTk("");
  const [rates, setRates] = useStateTk(null);
  const [rateDraft, setRateDraft] = useStateTk({});
  const [showRates, setShowRates] = useStateTk(false);
  // creative finance
  const [mode, setMode] = useStateTk("subto");
  const [st, setSt] = useStateTk({ piti: "", rent: "", balance: "", entryFee: "", arrears: "", closingCosts: "" });
  const [sf, setSf] = useStateTk({ price: "", down: "", ratePct: "6", termYears: "30", balloonYears: "" });
  const [nv, setNv] = useStateTk({ sellerPrice: "", sellCostPct: "8" });
  // dual view
  const [view, setView] = useStateTk("internal");
  const [buyerPrice, setBuyerPrice] = useStateTk("");
  const [holding, setHolding] = useStateTk("");
  // results
  const [res, setRes] = useStateTk({});
  const [saveMsg, setSaveMsg] = useStateTk(null);
  const [saving, setSaving] = useStateTk(false);
  const timerTk = useRefTk(null);

  useEffectTk(() => {
    fetch("/api/toolkit/calc/config").then((r) => r.json())
      .then((c) => { setRates(c.rates || null); setRateDraft(c.rates || {}); })
      .catch(() => {});
  }, []);

  const bodyTk = () => ({
    arv: props.arv, repairs: props.repairs, fee: props.fee, pct: props.pct,
    asking: props.asking, sqft, tier, buyerPrice, holding,
    subto: st, sellerFinance: sf, novation: nv,
  });

  useEffectTk(() => {
    if (timerTk.current) clearTimeout(timerTk.current);
    timerTk.current = setTimeout(async () => {
      try { setRes(await window.apiPost("/api/toolkit/calc/eval", bodyTk())); }
      catch (e) { /* server down — panels just stay empty */ }
    }, 400);
    return () => clearTimeout(timerTk.current);
  }, [props.arv, props.repairs, props.fee, props.pct, props.asking,
      sqft, tier, buyerPrice, holding, st, sf, nv]);

  async function saveRates() {
    try {
      const r = await window.apiPost("/api/toolkit/calc/rates", { rates: rateDraft });
      if (r && r.rates) { setRates(r.rates); setShowRates(false); }
    } catch (e) {}
  }

  async function saveSnapshot() {
    if (!props.contactId || saving) return;
    setSaving(true); setSaveMsg(null);
    try {
      const r = await window.apiPost("/api/toolkit/calc/save", { contactId: props.contactId, ...bodyTk() });
      setSaveMsg(r && r.ok ? { ok: true, t: "Saved to deal record." } : { ok: false, t: (r && r.error) || "save failed" });
    } catch (e) { setSaveMsg({ ok: false, t: "save failed: " + (e.message || "error") }); }
    finally { setSaving(false); }
  }

  const rep = res.repair && !res.repair.error ? res.repair : null;
  const sub = res.subto && !res.subto.error ? res.subto : null;
  const fin = res.sellerFinance && !res.sellerFinance.error ? res.sellerFinance : null;
  const nov = res.novation && !res.novation.error ? res.novation : null;
  const itn = res.internal || null;
  const byr = res.buyer && !res.buyer.error ? res.buyer : null;
  const setK = (setter) => (k) => (v) => setter((p) => ({ ...p, [k]: v }));
  const stK = setK(setSt), sfK = setK(setSf), nvK = setK(setNv);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16, alignItems: "start" }}>

      {/* ---- Repair estimator ---- */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <Icons.Sliders size={15} /> Repair estimator
          <button className="link" onClick={() => setShowRates((s) => !s)} style={{ fontSize: 11, marginLeft: "auto" }}>
            {showRates ? "hide rates" : "edit $/sqft"}
          </button>
        </div>
        {showRates && rates && (
          <div style={TK_BOX}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {Object.keys(rates).map((k) => TkIn(TK_TIER_LABEL[k] || k, rateDraft[k] == null ? rates[k] : rateDraft[k],
                (v) => setRateDraft((p) => ({ ...p, [k]: v })), { prefix: "$", suffix: "/sqft" }))}
            </div>
            <button className="tab" onClick={saveRates} style={{ marginTop: 10, fontWeight: 600 }}>Save rates</button>
          </div>
        )}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {TkIn("Square footage", sqft, setSqft, { suffix: "sqft" })}
        </div>
        <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
          {(rates ? Object.keys(rates) : []).map((k) => (
            <button key={k} className={"tab" + (tier === k ? " active" : "")} onClick={() => setTier(k)} style={{ fontSize: 12 }}>
              {TK_TIER_LABEL[k] || k} · ${rates[k]}/sqft
            </button>
          ))}
        </div>
        {rep ? (
          <div style={TK_BOX}>
            {TkRow(`${TK_TIER_LABEL[rep.tier] || rep.tier} · ${rep.sqft} sqft × $${rep.perSqft}`, M(rep.total), { bold: true, color: "var(--orange)" })}
            {props.onApplyRepairs && (
              <button className="tab" onClick={() => props.onApplyRepairs(rep.total)} style={{ marginTop: 10, fontWeight: 600 }}>
                Apply {M(rep.total)} → repairs
              </button>
            )}
          </div>
        ) : (
          <div className="faint" style={{ fontSize: 12 }}>Enter sqft + pick a condition tier.</div>
        )}
      </div>

      {/* ---- Creative finance ---- */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <Icons.Dollar size={15} /> Creative finance
        </div>
        <div style={{ display: "flex", gap: 7 }}>
          {[["subto", "Sub-To"], ["sellerfi", "Seller finance"], ["novation", "Novation"]].map(([k, lbl]) => (
            <button key={k} className={"tab" + (mode === k ? " active" : "")} onClick={() => setMode(k)} style={{ fontSize: 12 }}>{lbl}</button>
          ))}
        </div>
        {mode === "subto" && (
          <React.Fragment>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Monthly PITI", st.piti, stK("piti"), { prefix: "$" })}
              {TkIn("Market rent", st.rent, stK("rent"), { prefix: "$" })}
              {TkIn("Loan balance", st.balance, stK("balance"), { prefix: "$" })}
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Cash to seller", st.entryFee, stK("entryFee"), { prefix: "$" })}
              {TkIn("Arrears", st.arrears, stK("arrears"), { prefix: "$" })}
              {TkIn("Closing costs", st.closingCosts, stK("closingCosts"), { prefix: "$" })}
            </div>
            {sub && (
              <div style={{ ...TK_BOX, display: "flex", flexDirection: "column", gap: 6 }}>
                {TkRow("Entry cash", M(sub.entryCash))}
                {TkRow("Monthly cash flow", M(sub.monthlyFlow), { bold: true, color: sub.monthlyFlow >= 0 ? "var(--green)" : "var(--red)" })}
                {TkRow("Annual", M(sub.annualFlow))}
                {sub.cashOnCash != null && TkRow("Cash-on-cash", sub.cashOnCash + "%", { bold: true, color: "var(--green)" })}
              </div>
            )}
          </React.Fragment>
        )}
        {mode === "sellerfi" && (
          <React.Fragment>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Price", sf.price, sfK("price"), { prefix: "$" })}
              {TkIn("Down", sf.down, sfK("down"), { prefix: "$" })}
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Rate", sf.ratePct, sfK("ratePct"), { suffix: "%" })}
              {TkIn("Term (years)", sf.termYears, sfK("termYears"), { suffix: "yr" })}
              {TkIn("Balloon (years)", sf.balloonYears, sfK("balloonYears"), { suffix: "yr", placeholder: "none" })}
            </div>
            {fin && (
              <div style={{ ...TK_BOX, display: "flex", flexDirection: "column", gap: 6 }}>
                {TkRow("Note amount", M(fin.loan))}
                {TkRow("Monthly payment", M(fin.monthly), { bold: true, color: "var(--blue)" })}
                {TkRow("Total interest", M(fin.totalInterest))}
                {fin.balloonBalance != null && TkRow(`Balloon @ ${Math.round(fin.balloonMonths / 12)}yr`, M(fin.balloonBalance), { bold: true, color: "var(--orange)" })}
              </div>
            )}
          </React.Fragment>
        )}
        {mode === "novation" && (
          <React.Fragment>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Seller nets", nv.sellerPrice, nvK("sellerPrice"), { prefix: "$" })}
              {TkIn("Selling costs", nv.sellCostPct, nvK("sellCostPct"), { suffix: "%" })}
            </div>
            <div className="faint" style={{ fontSize: 11.5 }}>Uses ARV + repairs from the calculator above.</div>
            {nov && (
              <div style={{ ...TK_BOX, display: "flex", flexDirection: "column", gap: 6 }}>
                {TkRow("ARV − repairs − costs", M(nov.arv - nov.repairs - nov.sellingCosts))}
                {TkRow("Seller nets", "−" + M(nov.sellerPrice), { color: "var(--red)" })}
                {TkRow("Novation profit", M(nov.profit), { bold: true, color: nov.profit >= 0 ? "var(--green)" : "var(--red)" })}
                {nov.vsWholesale != null && TkRow("vs wholesale fee", (nov.vsWholesale >= 0 ? "+" : "") + M(nov.vsWholesale), { color: nov.vsWholesale >= 0 ? "var(--green)" : "var(--red)" })}
              </div>
            )}
          </React.Fragment>
        )}
      </div>

      {/* ---- Dual-view ROI ---- */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <Icons.Target size={15} /> Deal views
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <button className={"tab" + (view === "internal" ? " active" : "")} onClick={() => setView("internal")} style={{ fontSize: 11.5 }}>Internal</button>
            <button className={"tab" + (view === "buyer" ? " active" : "")} onClick={() => setView("buyer")} style={{ fontSize: 11.5 }}>Buyer sees</button>
          </div>
        </div>
        {view === "internal" && (itn ? (
          <div style={{ ...TK_BOX, display: "flex", flexDirection: "column", gap: 6 }}>
            {TkRow("MAO (you pay seller)", M(itn.mao), { bold: true, color: "var(--green)" })}
            {TkRow("Assignment fee", M(itn.fee))}
            {TkRow("Buyer pays", M(itn.buyerPrice), { bold: true })}
            {itn.spread != null && TkRow("Spread vs asking", (itn.spread >= 0 ? "+" : "") + M(itn.spread), { color: itn.spread >= 0 ? "var(--green)" : "var(--red)" })}
          </div>
        ) : <div className="faint" style={{ fontSize: 12 }}>Enter an ARV above.</div>)}
        {view === "buyer" && (
          <React.Fragment>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Buyer price", buyerPrice, setBuyerPrice, { prefix: "$", placeholder: itn ? String(Math.round(itn.buyerPrice)) : "MAO + fee" })}
              {TkIn("Holding costs", holding, setHolding, { prefix: "$" })}
            </div>
            {byr ? (
              <div style={{ ...TK_BOX, display: "flex", flexDirection: "column", gap: 6 }}>
                {TkRow("ARV (resale)", M(byr.arv))}
                {TkRow("Purchase", "−" + M(byr.purchase), { color: "var(--red)" })}
                {TkRow("Repairs", "−" + M(byr.repairs), { color: "var(--red)" })}
                {TkRow("Closing (buy + sell)", "−" + M(byr.buyClosing + byr.sellClosing), { color: "var(--red)" })}
                {byr.holding > 0 && TkRow("Holding", "−" + M(byr.holding), { color: "var(--red)" })}
                {TkRow("Buyer profit", M(byr.profit), { bold: true, color: byr.profit >= 0 ? "var(--green)" : "var(--red)" })}
                {byr.roiPct != null && TkRow("Cash-in ROI", byr.roiPct + "%", { bold: true, color: "var(--green)" })}
              </div>
            ) : <div className="faint" style={{ fontSize: 12 }}>Enter an ARV above.</div>}
            <div className="faint" style={{ fontSize: 11 }}>This is the sheet buyers see — one purchase number, your fee never shown. Feeds Buyer Blast deal sheets (Phase 2).</div>
          </React.Fragment>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <button className="tab" onClick={saveSnapshot} disabled={!props.contactId || saving} style={{ fontWeight: 600, opacity: props.contactId ? 1 : 0.5 }}>
            {saving ? "Saving…" : "Save scenario to deal"}
          </button>
          {!props.contactId && <span className="faint" style={{ fontSize: 11 }}>pick a homeowner above to save</span>}
          {saveMsg && <span style={{ fontSize: 12, fontWeight: 600, color: saveMsg.ok ? "var(--green)" : "var(--red)" }}>{saveMsg.ok ? "✓ " : ""}{saveMsg.t}</span>}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { TkCalcPanels });
```

- [ ] **Step 2: Validate**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && node deploy/valjsx.js toolkit_calc.jsx`
Expected: `OK   toolkit_calc.jsx`

---

### Task 9: Mount in DealCalcPage + HTML script tag

**Files:**
- Modify: `pages.jsx` (one insertion at the end of `DealCalcPage`'s return, ~line 1221)
- Modify: `FORGE REI OS.html` (one script tag, line 24)

**Interfaces:**
- Consumes: `window.TkCalcPanels` (Task 8). Guarded mount — page still renders if the script is missing.

- [ ] **Step 1: Mount the panels.** In `pages.jsx`, find the end of `DealCalcPage` (the contract card close + page close, right before the Pipeline comment block):

```jsx
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pipeline — all opportunities by stage, with deal values.
```

Replace with:

```jsx
        </div>
      )}

      {/* Wholesaler Toolkit — repair estimator, creative finance, dual-view ROI */}
      {window.TkCalcPanels && (
        <window.TkCalcPanels arv={arvN} repairs={repN} fee={feeN} pct={pctN} asking={askN}
          contactId={picked ? picked.id : null}
          onApplyRepairs={(v) => setRepairs(String(v))} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pipeline — all opportunities by stage, with deal values.
```

- [ ] **Step 2: Script tag.** In `FORGE REI OS.html`, find `<script type="text/babel" src="pages.jsx"></script>` (line 23) and add after it:

```html
<script type="text/babel" src="toolkit_calc.jsx"></script>
```

- [ ] **Step 3: Validate both**

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
node deploy/valjsx.js pages.jsx
node deploy/valjsx.js toolkit_calc.jsx
```
Expected: OK for both.

- [ ] **Step 4: End-to-end local check**

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
FORGE_MARCUS=0 FORGE_PORT=7801 python3 connector.py &
sleep 2
curl -s localhost:7801/ | grep -c "toolkit_calc.jsx"     # expect 1
```
Then open `http://localhost:7801/`, go to Deal Calc tab, verify: three new cards render below the existing calculator; entering ARV 200000 / sqft 1200 / tier Moderate shows a $48,000 estimate with an Apply button; Apply fills the repairs input; Buyer view shows profit/ROI; no white screen anywhere (check other tabs too). Kill the server after.

---

### Task 10: PLAN.md update + deploy

**Files:**
- Modify: `/Users/yg4st/forge rei dash/PLAN.md` (phase status + session log)

- [ ] **Step 1: Full test suite one last time**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && python3 -m unittest test_toolkit_calc -v 2>&1 | tail -3`
Expected: OK, 21 tests.

- [ ] **Step 2: Update PLAN.md** — Phase Status row 1 → `✅ SHIPPED (date)`, Phase 2 → `⬜ NEXT`; add Session Log entry (what shipped, any deviations).

- [ ] **Step 3: Deploy + verify**

Run: `cd "/Users/yg4st/forge rei dash/forge rei" && ./deploy/push.sh root@24.199.81.124 2>&1 | tail -5`
Expected: validators pass, `OK: service active · /api/health + /api/system/health 200 · heartbeats.json 404 · ghl.env not served`.

- [ ] **Step 4: Verify the new endpoint on the box**

Run: `ssh -i ~/.ssh/forge_droplet root@24.199.81.124 "curl -s localhost:7799/api/toolkit/calc/config"`
Expected: `{"rates": {"light": 20.0, ...}, "tiers": [...], "hints": {...}}`

---

## Self-review notes

- **Spec coverage:** repair estimator by tier ✅ (Task 2), creative finance subto/seller-finance/novation ✅ (Tasks 3-4), dual-view ROI buyers can see ✅ (Task 5), MAO calc with adjustable % — already exists, untouched ✅, persistence ✅ (Task 6 rides deals.py).
- **Fee-hiding invariant** tested explicitly (`test_buyer_view_hides_fee_and_computes_roi`).
- **MAO formula parity** with the UI locked by `test_internal_view_matches_ui_mao` (same formula as `pages.jsx:871`).
- **No git:** commit steps intentionally absent; deploy gate + PLAN.md log are the record.
