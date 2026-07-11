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


# -- AI ARV finder (operator-requested 2026-07-11; supersedes Open Decision #2's
#    "manual comps only" for the lookup — the manual comps list stays available).
#    Claude + the Anthropic web_search server tool pulls live listing/sale data
#    for the address and returns a structured estimate. INTERNAL prep numbers
#    only — never quoted to a seller (same rule as Atlas).
_ARV_TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}]

_ARV_SYSTEM = (
    "You are an ARV (after-repair value) analyst for a real-estate wholesaler. "
    "Given a property address, use web search to find the property's details "
    "(sqft, beds/baths, last sale) and RECENT comparable sales or estimates "
    "(Zillow/Redfin/Realtor estimates, nearby solds) and produce a conservative "
    "after-repair value. Wholesalers get burned by high ARVs — bias LOW. "
    "Respond with ONLY a JSON object, no prose before or after, shaped exactly:\n"
    '{"arv": <number>, "low": <number>, "high": <number>, '
    '"confidence": "low"|"medium"|"high", "sqft": <number or null>, '
    '"beds": <number or null>, "baths": <number or null>, '
    '"comps": [{"address": "...", "price": <number>, "note": "sold 03/2026, 3/2, 1,200 sqft"}], '
    '"summary": "<2-3 sentences: what drove the number + what to verify>"}\n'
    "Max 5 comps. If you cannot find enough data, still return the JSON with "
    'your best conservative estimate and "confidence": "low".'
)


def _parse_arv_json(text):
    """Pull the first JSON object out of a Claude reply (tolerates stray prose)."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(raw[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:
                    return None
    return None


def find_arv(address, sqft=None, beds=None, baths=None):
    """Web-search-backed ARV estimate for an address. Returns the parsed JSON
    plus an `ok` flag, or {"error": ...}. Never raises."""
    addr = str(address or "").strip()
    if len(addr) < 8:
        return {"error": "Enter the full property address (street, city, state)."}
    import review_agent
    key = review_agent._api_key()
    if not key:
        return {"error": "ANTHROPIC_API_KEY missing — add it to ghl.env."}
    facts = [f"Address: {addr}"]
    if _num(sqft) > 0:
        facts.append(f"Operator says sqft: {int(_num(sqft))}")
    if _num(beds) > 0:
        facts.append(f"Beds: {int(_num(beds))}")
    if _num(baths) > 0:
        facts.append(f"Baths: {_num(baths)}")
    user = ("\n".join(facts)
            + "\n\nSearch the web for this property and recent nearby sales, "
              "then return the JSON object.")
    try:
        reply = review_agent._claude(key, _ARV_SYSTEM, user,
                                     max_tokens=1500, tools=_ARV_TOOLS)
    except Exception as e:  # noqa: BLE001
        return {"error": f"ARV lookup failed: {e}"}
    parsed = _parse_arv_json(reply)
    if not parsed or _num(parsed.get("arv")) <= 0:
        return {"error": "Couldn't get a solid number back — try adding city/state "
                         "or run it again.", "raw": (reply or "")[:800]}
    out = {
        "ok": True,
        "address": addr,
        "arv": round(_num(parsed.get("arv"))),
        "low": round(_num(parsed.get("low"))) or None,
        "high": round(_num(parsed.get("high"))) or None,
        "confidence": str(parsed.get("confidence") or "low").lower(),
        "sqft": int(_num(parsed.get("sqft"))) or None,
        "beds": int(_num(parsed.get("beds"))) or None,
        "baths": _num(parsed.get("baths")) or None,
        "comps": [c for c in (parsed.get("comps") or []) if isinstance(c, dict)][:5],
        "summary": str(parsed.get("summary") or "")[:600],
    }
    return out
