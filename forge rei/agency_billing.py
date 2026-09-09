#!/usr/bin/env python3
"""agency_billing.py — the ClientForge care-plan payment link.

**What this does:** turns "they said yes" into a link the operator can text
them, and records on the client that it was sent. That is the whole job.

**Why a Payment Link and not a Checkout Session.** Our offer is one recurring
price — $129/mo, free build (`agency-offer-sheet.md`). One Stripe Payment Link
covers every client forever: it does not expire, it can be texted, and Stripe
appends per-client attribution through the URL. A Checkout Session would have to
be minted per client and dies in 24 hours, which is wrong for a link you send to
a daycare director who opens it after pickup.

**Per-client attribution without per-client objects.** Stripe accepts
``?client_reference_id=<id>`` on a payment-link URL and copies it onto the
resulting Checkout Session. So one link + a query string = we know which client
paid, with zero extra Stripe objects to manage.

**What this deliberately does NOT do:** it does not mark anyone paid. There is
no webhook listener reachable from the internet yet (same public-URL blocker as
the client portal — see AGENCY_WORKFLOW_AUDIT_2026-09-08.md), so activation is
the operator's tap in the dashboard after Stripe emails them. A stub that
guessed at payment state would be worse than an honest manual step.

**Key:** ``STRIPE_SECRET_KEY`` in ``forge-agency/config/agency.env`` — the
AGENCY Stripe account, kept separate from the daycare's on purpose. Falls back
to ``AGENCY_STRIPE_SECRET_KEY`` in the environment. When it is blank,
``configured()`` is False and every call returns a clean "not configured"
result. Nothing is ever charged from here and no secret reaches the browser.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from urllib.parse import quote, urlencode

import stripe_io

HERE = Path(__file__).resolve().parent

AGENCY_ENV_CANDIDATES = [
    HERE.parent / "forge-agency" / "config" / "agency.env",
    Path.home() / "Desktop" / "forge-agency" / "config" / "agency.env",
]

# Stripe objects we look for by name before creating anything, so running this
# twice does not litter the account with duplicate products.
PRODUCT_NAME = "ClientForge Care Plan"
_LOOKUP_KEY = "clientforge_care_plan_monthly"

_LOCK = threading.Lock()
_CACHE: dict = {}


# --- key ---------------------------------------------------------------------
def _secret_key() -> str:
    k = os.environ.get("AGENCY_STRIPE_SECRET_KEY", "").strip()
    if k:
        return k
    for p in AGENCY_ENV_CANDIDATES:
        try:
            if not p.exists():
                continue
            for raw in p.read_text().splitlines():
                s = raw.strip()
                if s.startswith("STRIPE_SECRET_KEY=") and not s.startswith("#"):
                    return s.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def configured() -> bool:
    return bool(_secret_key())


def _req(method: str, path: str, params: dict | None = None) -> dict:
    return stripe_io._req(method, path, params, key=_secret_key())


# --- the care-plan price -----------------------------------------------------
def _plan():
    """The offer, read from the one place that defines it."""
    import agency_offers
    o = agency_offers.get(agency_offers.PRIMARY_ID)
    if not o or not o.get("monthly"):
        raise stripe_io.StripeError(500, "The primary offer is not a monthly plan", "bad_offer")
    return o


def ensure_price() -> str:
    """Find (or create once) the recurring price for the care plan.

    Matched on `lookup_key`, not on name, so renaming the product later doesn't
    silently create a second price and start billing two different amounts.
    Raises if a price exists at a DIFFERENT amount than the offer sheet says —
    quietly billing an amount nobody chose is the worst outcome here.
    """
    plan = _plan()
    cents = int(round(float(plan["price"]) * 100))

    with _LOCK:
        if _CACHE.get("price_id") and _CACHE.get("cents") == cents:
            return _CACHE["price_id"]

    found = _req("GET", "/prices", {"lookup_keys[]": _LOOKUP_KEY, "limit": 1})
    for price in found.get("data") or []:
        if price.get("unit_amount") != cents:
            raise stripe_io.StripeError(
                409,
                f"Stripe already has a '{_LOOKUP_KEY}' price at "
                f"${price.get('unit_amount', 0) / 100:,.2f}/mo but the offer sheet says "
                f"${cents / 100:,.2f}/mo. Fix one of them before sending a link.",
                "price_mismatch")
        with _LOCK:
            _CACHE.update(price_id=price["id"], cents=cents)
        return price["id"]

    product = _req("POST", "/products", {
        "name": PRODUCT_NAME,
        "description": plan["blurb"],
    })
    price = _req("POST", "/prices", {
        "product": product["id"],
        "unit_amount": cents,
        "currency": "usd",
        "recurring": {"interval": "month"},
        "lookup_key": _LOOKUP_KEY,
    })
    with _LOCK:
        _CACHE.update(price_id=price["id"], cents=cents)
    return price["id"]


def ensure_link() -> str:
    """Find (or create once) the reusable payment link. Returns its base URL."""
    with _LOCK:
        if _CACHE.get("link_url"):
            return _CACHE["link_url"]

    price_id = ensure_price()
    existing = _req("GET", "/payment_links", {"active": "true", "limit": 100})
    for link in existing.get("data") or []:
        if (link.get("metadata") or {}).get("forge") == _LOOKUP_KEY:
            with _LOCK:
                _CACHE["link_url"] = link["url"]
            return link["url"]

    link = _req("POST", "/payment_links", {
        "line_items": [{"price": price_id, "quantity": 1}],
        "metadata": {"forge": _LOOKUP_KEY},
        "allow_promotion_codes": "false",
    })
    with _LOCK:
        _CACHE["link_url"] = link["url"]
    return link["url"]


# --- what the dashboard calls ------------------------------------------------
def link_for_client(client_id: str, email: str = "") -> dict:
    """The care-plan link for one client, tagged so we know who paid.

    Safe to call repeatedly — it reuses the same Stripe objects every time and
    only ever appends a query string.
    """
    cid = str(client_id or "").strip()
    if not cid:
        return {"ok": False, "detail": "client id required"}
    if not configured():
        return {"ok": False, "detail":
                "Stripe isn't configured. Add STRIPE_SECRET_KEY to "
                "forge-agency/config/agency.env (the AGENCY account, not the "
                "daycare's), then reload."}

    plan = _plan()
    try:
        base = ensure_link()
    except stripe_io.StripeError as e:
        return {"ok": False, "detail": e.message, "code": e.code}

    query = {"client_reference_id": cid}
    email = str(email or "").strip()
    if "@" in email:
        query["prefilled_email"] = email
    sep = "&" if "?" in base else "?"
    return {
        "ok": True,
        "url": f"{base}{sep}{urlencode(query, quote_via=quote)}",
        "amount": float(plan["price"]),
        "display": plan["display"],
        "minMonths": plan.get("min_months"),
        "buildPrice": float(plan.get("build_price", 0) or 0),
        # Said plainly so no UI can imply a payment was taken.
        "note": "Sending this link does not charge anyone. Stripe emails you "
                "when they actually subscribe — mark the client active then.",
    }


def status() -> dict:
    """Cheap health check for the UI, with no Stripe call when unconfigured."""
    if not configured():
        return {"ok": True, "configured": False,
                "detail": "No STRIPE_SECRET_KEY in forge-agency/config/agency.env"}
    plan = _plan()
    return {"ok": True, "configured": True, "plan": plan["name"],
            "display": plan["display"],
            "webhook": False,
            "detail": "Link generation is live. Payment confirmation is manual — "
                      "there is no public webhook listener yet."}


if __name__ == "__main__":
    # Runs with no network and no key: proves the unconfigured path is clean and
    # that the URL is built correctly, which is the only logic worth a check.
    os.environ.pop("AGENCY_STRIPE_SECRET_KEY", None)
    globals()["_secret_key"] = lambda: ""
    assert configured() is False
    r = link_for_client("c7_123")
    assert r["ok"] is False and "agency.env" in r["detail"], r
    assert status()["configured"] is False
    assert link_for_client("")["detail"] == "client id required"

    globals()["_secret_key"] = lambda: "sk_test_fake"
    globals()["ensure_link"] = lambda: "https://buy.stripe.com/test_abc"
    r = link_for_client("c7_123", "director@example.com")
    assert r["ok"] and r["amount"] == 129.0 and r["buildPrice"] == 0.0, r
    assert "client_reference_id=c7_123" in r["url"], r["url"]
    assert "prefilled_email=director%40example.com" in r["url"], r["url"]
    assert link_for_client("c8", "not-an-email")["url"].count("prefilled_email") == 0

    globals()["ensure_link"] = lambda: "https://buy.stripe.com/x?utm=1"
    assert "?utm=1&client_reference_id=c9" in link_for_client("c9")["url"]
    print("agency_billing: ok")
