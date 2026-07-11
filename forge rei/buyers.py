"""Tier 3 — the cash-buyer list + buy-box match (the dispo half of the deal loop).

A locked contract is worthless without somewhere to assign it. This is the missing half:
a persistent roster of cash buyers (their areas / max price / property type / proof-of-funds)
plus a buy-box matcher that, given a deal record, ranks who to call first.

Keyed by buyer id. Pure JSON store mirroring deals.py — atomic writes so a restart
mid-write can't corrupt it. Stays decoupled: the connector hands match() a deal dict
(assembled from deals.get + screening), buyers.py never imports deals.
"""
import json
import re
import threading
import time
from pathlib import Path

import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "buyers.json"
_LOCK = threading.RLock()
MAX = 2000

# Property types a buyer may want. Empty list on a buyer = "any type".
PROPERTY_TYPES = ("sfr", "multi", "land", "mobile", "condo", "commercial")
# How distressed a condition a buyer tolerates (informational + light scoring).
CONDITIONS = ("any", "light", "heavy")
# Exit strategy (informational).
STRATEGIES = ("", "flip", "buyhold", "wholetail", "brrrr")


def _now():
    return int(time.time() * 1000)


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or "buyer"


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _as_list(v):
    """Accept a list or a comma/newline-separated string -> clean lowercase tokens."""
    if v is None:
        return None
    if isinstance(v, list):
        items = v
    else:
        items = re.split(r"[,\n;]+", str(v))
    return [x.strip().lower() for x in items if x and x.strip()]


def get(buyer_id):
    return _load().get(buyer_id)


def list_buyers():
    rows = list(_load().values())
    rows.sort(key=lambda r: (0 if r.get("active", True) else 1, -(r.get("updatedAt") or 0)))
    return rows


def upsert(buyer_id=None, **fields):
    """Create or update a buyer. List fields (areas/types) accept a string or list.
    Only provided fields overwrite; everything else is preserved."""
    with _LOCK:
        d = _load()
        if not buyer_id:
            base = _slug(fields.get("name") or fields.get("company"))
            buyer_id = base
            n = 2
            while buyer_id in d:
                buyer_id = f"{base}-{n}"
                n += 1
        r = d.get(buyer_id) or {"id": buyer_id, "createdAt": _now(), "active": True,
                                "dealsBought": 0}
        for k, v in fields.items():
            if v is None:
                continue
            if k in ("areas", "propertyTypes"):
                r[k] = _as_list(v) or []
            elif k in ("maxPrice", "minPrice", "minBeds", "maxBeds"):
                r[k] = _num(v)
            elif k in ("pof", "active"):
                r[k] = bool(v)
            elif k == "dealsBought":
                r[k] = int(v)
            else:
                r[k] = v
        r["id"] = buyer_id
        r["updatedAt"] = _now()
        d[buyer_id] = r
        if len(d) > MAX:
            keep = sorted(d.values(), key=lambda x: -(x.get("updatedAt") or 0))[:MAX]
            d = {x["id"]: x for x in keep}
        _save(d)
        return r


def remove(buyer_id):
    with _LOCK:
        d = _load()
        if buyer_id in d:
            r = d.pop(buyer_id)
            _save(d)
            return {"ok": True, "removed": r}
        return {"ok": False, "error": "not found"}


# ---- buy-box match -------------------------------------------------------------

def _deal_price(deal):
    """What the property costs us — the number a buyer's maxPrice is judged against."""
    for k in ("offer", "mao", "purchasePrice", "asking"):
        v = _num(deal.get(k))
        if v:
            return v
    return None


def _deal_text(deal):
    return " ".join(str(deal.get(k) or "") for k in (
        "address", "city", "state", "zip", "county", "propertyStatus", "condition")).lower()


def _condition_rank(deal):
    """Rough distress read of the deal from its condition/status prose."""
    t = _deal_text(deal)
    if any(w in t for w in ("teardown", "fire", "gut", "severe", "uninhab", "condemn",
                            "major", "foundation")):
        return "heavy"
    if any(w in t for w in ("cosmetic", "light", "turnkey", "rent ready", "move-in",
                            "good", "updated")):
        return "light"
    return "any"


def score_buyer(buyer, deal):
    """Score one buyer against a deal (0-100) + human reasons + a hard `fits` flag.
    Area + price are the hard filters; type/beds/condition refine the ranking."""
    reasons = []
    fits = True
    score = 0.0
    text = _deal_text(deal)

    # Area (45) — the hard dispo filter. No areas set = open buyer (neutral).
    areas = buyer.get("areas") or []
    if not areas:
        score += 45 * 0.6
        reasons.append("buys anywhere (no area set)")
    else:
        hit = next((a for a in areas if a and a in text), None)
        if hit:
            score += 45
            reasons.append(f"area match: {hit}")
        else:
            fits = False
            reasons.append("outside buy-area")

    # Price (35) — buyer's ceiling vs the deal price.
    price = _deal_price(deal)
    cap = _num(buyer.get("maxPrice"))
    if cap and price:
        if price <= cap:
            score += 35
            reasons.append(f"under budget (${int(price):,} ≤ ${int(cap):,})")
        else:
            fits = False
            reasons.append(f"over budget (${int(price):,} > ${int(cap):,})")
    elif not cap:
        score += 35 * 0.6
        reasons.append("no price cap")
    else:  # cap set but deal has no price yet
        score += 35 * 0.5
        reasons.append("deal price TBD")

    # Type (12) — informational; deal type rarely typed, so neutral when unknown.
    types = buyer.get("propertyTypes") or []
    dtype = (deal.get("propertyType") or "").lower()
    if types and dtype:
        if dtype in types:
            score += 12
            reasons.append(f"{dtype} matches")
        else:
            reasons.append(f"wants {'/'.join(types)}, deal is {dtype}")
    else:
        score += 12 * 0.6

    # Beds (4)
    mb = _num(buyer.get("minBeds"))
    db = _num(deal.get("beds"))
    if mb and db:
        if db >= mb:
            score += 4
        else:
            reasons.append(f"under {int(mb)} beds")
    else:
        score += 4 * 0.6

    # Condition tolerance (4) — a "light only" buyer on a heavy deal is a soft mismatch.
    tol = (buyer.get("condition") or "any").lower()
    need = _condition_rank(deal)
    if tol == "light" and need == "heavy":
        reasons.append("wants light rehab, deal is heavy")
    else:
        score += 4

    if buyer.get("pof"):
        reasons.append("POF on file")

    return {"buyer": buyer, "buyerId": buyer.get("id"), "name": buyer.get("name"),
            "score": round(min(100.0, score)), "fits": fits, "reasons": reasons}


def match(deal, limit=20):
    """Rank active buyers for a deal. `fits` buyers (area+price ok) sort to the top."""
    deal = deal or {}
    out = [score_buyer(b, deal) for b in _load().values() if b.get("active", True)]
    out.sort(key=lambda m: (0 if m["fits"] else 1, -m["score"]))
    return out[:limit]
