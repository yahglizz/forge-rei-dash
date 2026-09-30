#!/usr/bin/env python3
"""stripe_links.py — the ONE Stripe payment-link maker for every side of the dashboard.

Owner decision 2026-09-30: one Stripe key (daycare.env STRIPE_SECRET_KEY, shared by every
business), and a link on demand — recurring revenue OR pay-in-full — for any business.

  mode "recurring"  monthly/yearly subscription (optionally + a one-time upfront fee on the first invoice)
  mode "one_time"   pay in full, one charge

Creating a link charges nobody and sends nothing; the customer pays only when THEY open it.
Links are reused (same business + name + amount + mode -> same Stripe link, tagged per client with
?client_reference_id), so asking twice never litters the account. Stdlib only, zero Claude.
"""
from __future__ import annotations

import hashlib
import threading
from urllib.parse import quote, urlencode

import stripe_io

BUSINESSES = ("agency", "daycare", "wholesale", "dropship", "other")
MAX_USD = 25000.0
_LOCK = threading.Lock()


def _cents(v, label):
    try:
        usd = float(v)
    except (TypeError, ValueError):
        raise stripe_io.StripeError(400, f"{label} must be a number", "validation_error") from None
    if usd < 1 or usd > MAX_USD:
        raise stripe_io.StripeError(400, f"{label} must be between $1 and ${MAX_USD:,.0f}", "validation_error")
    return int(round(usd * 100))


def _resolve(spec: dict) -> dict:
    """Turn a request (an agency offer id, or a custom name+amount) into one normalized spec."""
    spec = dict(spec or {})
    offer = None
    if spec.get("offerId"):
        import agency_offers
        offer = agency_offers.get(str(spec["offerId"]))
        if not offer:
            raise stripe_io.StripeError(404, f"unknown offer: {spec['offerId']}", "unknown_offer")
    business = str(spec.get("business") or ("agency" if offer else "other")).lower()
    if business not in BUSINESSES:
        raise stripe_io.StripeError(400, f"business must be one of {', '.join(BUSINESSES)}", "validation_error")
    mode = str(spec.get("mode") or ("recurring" if offer and offer.get("monthly") else "one_time")).lower()
    if mode not in ("recurring", "one_time"):
        raise stripe_io.StripeError(400, "mode must be recurring or one_time", "validation_error")
    interval = str(spec.get("interval") or "month").lower()
    if interval not in ("week", "month", "year"):
        raise stripe_io.StripeError(400, "interval must be week, month or year", "validation_error")
    name = str(spec.get("name") or (offer or {}).get("name") or "").strip()[:120]
    if not name:
        raise stripe_io.StripeError(400, "name required", "validation_error")
    amount = spec.get("amountUSD", spec.get("amount", (offer or {}).get("price")))
    upfront = spec.get("upfrontUSD")
    if upfront in (None, "", 0, "0") and offer and mode == "recurring" and offer.get("build_price"):
        upfront = offer["build_price"]
    return {
        "business": business, "mode": mode, "interval": interval, "name": name,
        "cents": _cents(amount, "amount"),
        "upfront": _cents(upfront, "upfront fee") if upfront not in (None, "", 0, "0") else 0,
        "reference": str(spec.get("reference") or spec.get("clientId") or "").strip()[:80],
        "email": str(spec.get("email") or "").strip(),
        "description": str(spec.get("description") or "").strip()[:300],
    }


def _key(s: dict) -> str:
    raw = "|".join(str(s[k]) for k in ("business", "mode", "interval", "name", "cents", "upfront"))
    return "forge_" + hashlib.sha1(raw.encode()).hexdigest()[:20]


def _product(name: str, business: str) -> str:
    found = stripe_io._req("GET", "/products", {"active": "true", "limit": 100})
    for p in found.get("data") or []:
        if p.get("name") == name and (p.get("metadata") or {}).get("forge_business") == business:
            return p["id"]
    return stripe_io._req("POST", "/products", {"name": name, "metadata": {"forge_business": business}})["id"]


def _link_items(s: dict, product: str) -> list:
    main = {"currency": "usd", "product": product, "unit_amount": s["cents"]}
    if s["mode"] == "recurring":
        main["recurring"] = {"interval": s["interval"]}
    items = [{"price_data": main, "quantity": 1}]
    if s["mode"] == "recurring" and s["upfront"]:
        up = {"currency": "usd", "product": _product(s["name"] + " — setup", s["business"]), "unit_amount": s["upfront"]}
        items.append({"price_data": up, "quantity": 1})
    return items


def create(spec: dict) -> dict:
    """Return {ok, url, ...}. Never charges, never sends. Reuses an existing link when possible."""
    if not stripe_io.configured():
        return {"ok": False, "detail": "No STRIPE_SECRET_KEY configured (forge-daycare/config/daycare.env)."}
    try:
        s = _resolve(spec)
        key = _key(s)
        with _LOCK:
            base = None
            for link in stripe_io._req("GET", "/payment_links", {"active": "true", "limit": 100}).get("data") or []:
                if (link.get("metadata") or {}).get("forge_key") == key:
                    base, link_id = link["url"], link["id"]
                    break
            reused = base is not None
            if not reused:
                params = {
                    "line_items": _link_items(s, _product(s["name"], s["business"])),
                    "metadata": {"forge_key": key, "forge_business": s["business"], "forge_mode": s["mode"]},
                    "allow_promotion_codes": "false",
                }
                if s["mode"] == "one_time":
                    params["invoice_creation"] = {"enabled": "true"}     # a real invoice/receipt for the books
                link = stripe_io._req("POST", "/payment_links", params)
                base, link_id = link["url"], link["id"]
    except stripe_io.StripeError as e:
        hint = " The Stripe key needs write access to Products and Payment Links." if e.status == 403 else ""
        return {"ok": False, "detail": e.message + hint, "code": e.code, "status": e.status}
    q = {}
    if s["reference"]:
        q["client_reference_id"] = s["reference"]
    if "@" in s["email"]:
        q["prefilled_email"] = s["email"]
    url = base + (("&" if "?" in base else "?") + urlencode(q, quote_via=quote) if q else "")
    per = {"week": "wk", "month": "mo", "year": "yr"}[s["interval"]]
    shown = f"${s['cents'] / 100:,.2f}" + (f"/{per}" if s["mode"] == "recurring" else " pay in full")
    if s["upfront"]:
        shown += f" + ${s['upfront'] / 100:,.2f} upfront"
    return {"ok": True, "url": url, "linkId": link_id, "reused": reused, "business": s["business"], "mode": s["mode"],
            "name": s["name"], "display": shown,
            "note": "Creating this link charges nobody. Stripe emails you when someone pays."}


def offers() -> dict:
    """What the UI can offer: agency offers (recurring + one-time tiers) and the knobs for a custom link."""
    import agency_offers
    return {"ok": True, "businesses": list(BUSINESSES), "maxUSD": MAX_USD,
            "offers": [{"id": o["id"], "name": o["name"], "display": o["display"], "price": o["price"],
                        "monthly": bool(o.get("monthly")), "service": o.get("service")} for o in agency_offers.OFFERS]}
