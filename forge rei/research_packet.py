#!/usr/bin/env python3
"""research_packet.py — the decision packet's arithmetic and kill flags.

Pure functions, stdlib only, no I/O and no Claude call. ``MidasEngine.
research_packet`` wraps this: this module assembles the evidence + the maths +
the flags, Midas adds the "why it's winning" read on top using the skills he
already carries (``dropship-four-triggers-ad-writer``,
``dropship-meta-ads-diagnostician``).

Kept separate from the engine on purpose — the money path needs a test that runs
without a Claude key, an engine instance, or a network.

**The one number that earns this module's keep** is ``breakeven_cvr``. Most
candidates die on it before a dollar moves: at a median ecom CPM of ~$17 and a
median CVR of ~1.57%, acquiring one order costs roughly $70, so anything whose
gross margin per sale is under ~$70 needs above-median conversion just to break
even. That is one line of arithmetic and it is the entire reason this engine
exists.
"""
from __future__ import annotations

import re

import research_guard as guard

# --- benchmarks -------------------------------------------------------------
# Median ecommerce figures, 2026. Overridable per-call because a niche's real
# numbers beat a median every time — these are the default when nothing better
# is known, not a claim about your account.
DEFAULT_CPM = 17.0          # median ecommerce Meta CPM, USD per 1000 impressions
DEFAULT_CTR = 0.0153        # implied by the commonly-cited ~$1.11 median CPC
MEDIAN_CVR = 0.0157         # median ecommerce conversion rate

# Etsy fees, US seller, 2026. Verified against Etsy's fee schedule.
ETSY_LISTING_FEE = 0.20
ETSY_TRANSACTION_PCT = 0.065      # of item price + shipping
ETSY_PROCESSING_PCT = 0.03
ETSY_PROCESSING_FLAT = 0.25
ETSY_OFFSITE_ADS_PCT_UNDER_10K = 0.15   # opt-out available under $10k/yr
ETSY_OFFSITE_ADS_PCT_OVER_10K = 0.12    # MANDATORY above $10k/yr, no opt-out


def cpc(cpm: float = DEFAULT_CPM, ctr: float = DEFAULT_CTR) -> float | None:
    """Cost per click implied by a CPM and a click-through rate."""
    try:
        cpm, ctr = float(cpm), float(ctr)
    except (TypeError, ValueError):
        return None
    if ctr <= 0 or cpm < 0:
        return None
    return cpm / (1000.0 * ctr)


def margin(price, landed_cost) -> float | None:
    """Gross margin per sale. None when either side is unknown — the creed's
    point is that a missing input yields Unknown, not a guess."""
    try:
        p, c = float(price), float(landed_cost)
    except (TypeError, ValueError):
        return None
    return p - c


def breakeven_cvr(price, landed_cost, cpm: float = DEFAULT_CPM,
                  ctr: float = DEFAULT_CTR) -> dict:
    """The conversion rate a paid-traffic product must hit to break even.

    ``breakeven = CPC / gross_margin_per_sale``. Returns a stamped result with the
    verdict, plus the two figures that make it actionable: what one order costs at
    median conversion, and the margin you would need to survive at median.
    """
    m = margin(price, landed_cost)
    c = cpc(cpm, ctr)
    if m is None or c is None:
        return {"breakevenCvr": guard.unknown("computed", "price or landed cost missing"),
                "margin": guard.unknown("computed", "price or landed cost missing"),
                "verdict": guard.UNKNOWN,
                "note": "Cannot judge viability without both price and landed cost."}
    if m <= 0:
        return {"breakevenCvr": guard.stamp(None, "computed"),
                "margin": guard.stamp(round(m, 2), "computed", window="per sale"),
                "verdict": "DEAD",
                "note": f"Gross margin is ${m:.2f} — you lose money on every sale before ad spend."}
    be = c / m
    cac_at_median = c / MEDIAN_CVR
    margin_needed = cac_at_median
    if be <= MEDIAN_CVR * 0.5:
        verdict = "STRONG"
        note = (f"Breaks even at {be * 100:.2f}% conversion — comfortably under the "
                f"{MEDIAN_CVR * 100:.2f}% median. Room for error.")
    elif be <= MEDIAN_CVR:
        verdict = "WORKABLE"
        note = (f"Breaks even at {be * 100:.2f}% conversion, just under the "
                f"{MEDIAN_CVR * 100:.2f}% median. Thin — the creative has to carry it.")
    elif be <= MEDIAN_CVR * 2:
        verdict = "HARD"
        note = (f"Needs {be * 100:.2f}% conversion to break even vs a "
                f"{MEDIAN_CVR * 100:.2f}% median. Requires an above-average funnel "
                f"before profit, not after.")
    else:
        verdict = "DEAD"
        note = (f"Needs {be * 100:.2f}% conversion to break even — more than double the "
                f"{MEDIAN_CVR * 100:.2f}% median. This does not work on paid traffic.")
    return {
        "breakevenCvr": guard.stamp(round(be, 5), "computed",
                                    window=f"CPM ${cpm:.2f}, CTR {ctr * 100:.2f}%",
                                    confidence="arithmetic on median benchmarks"),
        "breakevenCvrPct": round(be * 100, 2),
        "margin": guard.stamp(round(m, 2), "computed", window="per sale"),
        "cpc": guard.stamp(round(c, 2), "computed",
                           window=f"CPM ${cpm:.2f}, CTR {ctr * 100:.2f}%"),
        "cacAtMedianCvr": guard.stamp(round(cac_at_median, 2), "computed",
                                      window=f"at {MEDIAN_CVR * 100:.2f}% median CVR"),
        "marginNeededAtMedian": guard.stamp(round(margin_needed, 2), "computed",
                                            window=f"at {MEDIAN_CVR * 100:.2f}% median CVR"),
        "salesToRecover100": (round(100.0 / m, 1) if m > 0 else None),
        "verdict": verdict,
        "note": note,
    }


def etsy_net(price, landed_cost=0.0, over_10k: bool = False,
             offsite_ads: bool = False, shipping: float = 0.0) -> dict:
    """Net per sale on Etsy after every fee.

    The flat $0.25 processing fee is what makes cheap digital items ugly — at $3
    it is ~24% of the sale. Offsite Ads is 15% and opt-out-able under $10k/yr
    trailing, then **12% mandatory with no opt-out** above it, charged only on
    ad-attributed orders.
    """
    try:
        p = float(price)
        c = float(landed_cost or 0.0)
        ship = float(shipping or 0.0)
    except (TypeError, ValueError):
        return {"net": guard.unknown("computed", "price missing"),
                "verdict": guard.UNKNOWN}
    fees = ETSY_LISTING_FEE
    fees += (p + ship) * ETSY_TRANSACTION_PCT
    fees += p * ETSY_PROCESSING_PCT + ETSY_PROCESSING_FLAT
    if offsite_ads:
        fees += p * (ETSY_OFFSITE_ADS_PCT_OVER_10K if over_10k
                     else ETSY_OFFSITE_ADS_PCT_UNDER_10K)
    net = p - c - fees
    pct = (fees / p * 100.0) if p > 0 else None
    return {
        "net": guard.stamp(round(net, 2), "computed", window="per sale",
                           confidence="Etsy published fee schedule"),
        "fees": guard.stamp(round(fees, 2), "computed", window="per sale"),
        "feePct": (round(pct, 1) if pct is not None else None),
        "offsiteAds": offsite_ads,
        "verdict": ("DEAD" if net <= 0 else "THIN" if p > 0 and net < p * 0.35 else "OK"),
        "note": (f"Etsy takes ${fees:.2f} of a ${p:.2f} sale"
                 + (f" ({pct:.1f}%)" if pct is not None else "")
                 + (" — Offsite Ads included." if offsite_ads else
                    " — excludes Offsite Ads (15% under $10k/yr, 12% mandatory above).")),
    }


# --- kill flags -------------------------------------------------------------
# Any one of these stops the packet. Each returns (fired, reason).

_BRAND_RE = re.compile(
    r"\b(nike|adidas|apple|disney|marvel|pokemon|louis vuitton|gucci|chanel|"
    r"rolex|supreme|lego|nintendo|sanrio|hello kitty|stanley|dyson|yeti|"
    r"harry potter|star wars|nfl|nba|fifa)\b", re.IGNORECASE)

_RESTRICTED_RE = re.compile(
    r"\b(vape|e-?cig|nicotine|cbd|thc|kratom|weapon|firearm|ammo|ammunition|"
    r"taser|pepper spray|prescription|pharmaceutical|supplement|weight ?loss|"
    r"diet pill|counterfeit|replica|knock-?off)\b", re.IGNORECASE)

# Shopify Payments' documented high-risk bucket + practical chargeback magnets.
_HIGH_RISK_RE = re.compile(
    r"\b(electronic|battery|lithium|charger|drone|phone|laptop|tablet|"
    r"smart ?watch|glass|ceramic|mirror|aquarium|furniture|mattress|sofa)\b",
    re.IGNORECASE)

FTC_SHIP_DAYS = 30   # 16 CFR 435.2 — no stated timeframe means a 30-day default


def kill_flags(candidate: dict, evidence: dict | None = None) -> list:
    """Every flag that fired, worst first. Empty list means nothing blocking."""
    candidate = candidate or {}
    flags: list = []
    text = " ".join(str(candidate.get(k) or "") for k in
                    ("name", "title", "description", "niche", "notes"))

    hit = _BRAND_RE.search(text)
    if hit:
        flags.append({"flag": "trademark", "severity": "stop",
                      "detail": f"'{hit.group(0)}' is a protected brand. IP takedown is the "
                                f"single largest killer of stores in this category, and Meta "
                                f"rejects the creative regardless of disclosure."})

    hit = _RESTRICTED_RE.search(text)
    if hit:
        flags.append({"flag": "restricted_category", "severity": "stop",
                      "detail": f"'{hit.group(0)}' falls in a restricted or prohibited "
                                f"category for Meta ads, Shopify Payments, or both."})

    hit = _HIGH_RISK_RE.search(text)
    if hit:
        flags.append({"flag": "high_risk_bucket", "severity": "warn",
                      "detail": f"'{hit.group(0)}' sits in Shopify Payments' high-risk bucket "
                                f"(fragile / oversized / electronics). Expect reserve exposure: "
                                f"reserves are fully discretionary with no published cap."})

    ship = candidate.get("shipDays") or candidate.get("transitDays")
    try:
        ship = int(ship) if ship not in (None, "") else None
    except (TypeError, ValueError):
        ship = None
    if ship is not None and ship > FTC_SHIP_DAYS:
        flags.append({"flag": "ftc_shipping", "severity": "stop",
                      "detail": f"{ship}-day transit exceeds the FTC Mail Order Rule's "
                                f"{FTC_SHIP_DAYS}-day default (16 CFR 435.2). Undisclosed, that "
                                f"is a federal violation on every order — and 'item not received' "
                                f"is the #1 chargeback, which Shopify Protect does NOT cover."})
    elif ship is None:
        flags.append({"flag": "ftc_shipping", "severity": "unknown",
                      "detail": "Transit time unknown. Under 16 CFR 435.2, stating no timeframe "
                                "defaults you to 30 days. Establish it before advertising."})

    if evidence:
        adv = ((evidence.get("advertiserCount") or {}).get("value"))
        longest = ((evidence.get("longestRunningDays") or {}).get("value"))
        if adv is not None and longest is not None:
            if adv >= 15 and longest >= 90:
                flags.append({"flag": "saturated", "severity": "warn",
                              "detail": f"{adv} advertisers on a creative running {longest}+ days. "
                                        f"Validated demand, but you are late and bidding against "
                                        f"established pixels."})
        for path in (evidence.get("flagged") or []):
            flags.append({"flag": "injected_text", "severity": "warn",
                          "detail": f"Vendor field '{path}' contains text addressed at a reading "
                                    f"model. Treated as inert data, never followed. Shown so you "
                                    f"can see a vendor attempted it."})

    order = {"stop": 0, "warn": 1, "unknown": 2}
    flags.sort(key=lambda f: order.get(f["severity"], 3))
    return flags


def blocking(flags: list) -> bool:
    return any(f.get("severity") == "stop" for f in (flags or []))


# --- assembly ---------------------------------------------------------------

def build(candidate: dict, ads_evidence: dict | None = None,
          etsy_evidence: dict | None = None, **benchmarks) -> dict:
    """Evidence + maths + flags. No Claude call — Midas adds the read on top."""
    candidate = candidate or {}
    channel = (candidate.get("channel") or "dropship").strip().lower()
    flags = kill_flags(candidate, ads_evidence or etsy_evidence)

    money: dict
    if channel == "etsy":
        money = etsy_net(candidate.get("price"), candidate.get("landedCost"),
                         over_10k=bool(candidate.get("over10k")),
                         offsite_ads=bool(candidate.get("offsiteAds")),
                         shipping=candidate.get("shipping") or 0.0)
    else:
        money = breakeven_cvr(
            candidate.get("price"), candidate.get("landedCost"),
            cpm=benchmarks.get("cpm", DEFAULT_CPM),
            ctr=benchmarks.get("ctr", DEFAULT_CTR))

    unknowns = []
    if candidate.get("price") in (None, ""):
        unknowns.append("price")
    if candidate.get("landedCost") in (None, ""):
        unknowns.append("landed cost")
    if not (ads_evidence or {}).get("ads") and channel != "etsy":
        unknowns.append("competitor ad data")
    if channel == "etsy" and not (etsy_evidence or {}).get("keywords"):
        unknowns.append("keyword volume")

    return {
        "ok": True,
        "candidate": {"name": guard.inert(candidate.get("name") or "", "candidate_name"),
                      "channel": channel,
                      "price": candidate.get("price"),
                      "landedCost": candidate.get("landedCost"),
                      "shipDays": candidate.get("shipDays")},
        "evidence": {"ads": ads_evidence or {}, "etsy": etsy_evidence or {}},
        "money": money,
        "killFlags": flags,
        "blocked": blocking(flags),
        "unknowns": unknowns,
        # Copying the ANGLE is legitimate competitive practice. Copying the ASSET
        # is IP infringement plus a Meta rejection. The packet emits a prompt.
        "copyRule": ("Copy the angle, trigger, structure and offer shape. Never their "
                     "images or video — that is IP infringement and a Meta rejection "
                     "trigger. Output a Higgsfield prompt, never a downloaded asset. "
                     "Meta requires AI-imagery disclosure."),
    }
