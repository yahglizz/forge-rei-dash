#!/usr/bin/env python3
"""Fee links — one-off Stripe payment links (registration fee, deposit...) tracked paid / unpaid.

Why (2026-11-02 audit of one family's thread): a $49 registration link was texted by hand, the parent
paid, and the dashboard never knew — payment links live in Stripe + GHL, the invoice list lives in the
daycare database. This module closes that gap without a webhook:

  list_fees(session, q)    -> every purpose-tagged link/checkout for one center, paid or not (read-only)
  create(session, body)    -> mint a per-family payment link + a DRAFT text. Charges nobody, sends nothing.

Sending is the owner's tap on the existing `POST /api/daycare/ghl/reply` (owner-typed, tap-gated).
Per-center Stripe key via stripe_io.key_for_location: the QA Sandbox uses the test key, fail closed.
A Mother's Touch (4444) is a separate legal entity — a fee only ever shows at the center it was made for.
"""
from __future__ import annotations

import math
import re
import threading
import time
from datetime import datetime, timezone

import daycare_ghl
import daycare_supabase
import stripe_io

ATOB = "11111111-1111-1111-1111-111111111111"          # A Touch of Blessings (921 N 18th) — the default
AMT = "44444444-4444-4444-4444-444444444444"           # A Mother's Touch — separate legal entity
NO_AMT_STRIPE = ("A Mother's Touch has no Stripe account of its own yet, so fee links are blocked for it "
                 "(stripe_io would put the money in A Touch of Blessings' account).")
PURPOSES = {"registration-fee": "registration fee", "deposit": "deposit", "supply-fee": "supply fee",
            "late-fee": "late fee", "other": "fee"}
MAX_USD = 2000.0
MAX_PAGES = 5               # x100 rows; past that the result says so (never silently 'unpaid')
CACHE_SECONDS = 30
_TAG_BY_ID = {v: k for k, v in daycare_ghl.LOCATION_ID_BY_TAG.items()}
_CACHE: dict = {}          # center id -> (at, result)
_RECENT: dict = {}         # (contact|family, purpose, cents, center) -> (at, result)  double-tap guard
_LOCK = threading.Lock()
_GHL_ID = re.compile(r"^[A-Za-z0-9]{10,40}$")


class FeeError(Exception):
    def __init__(self, status: int, detail: str, code: str = "fee_error"):
        super().__init__(detail)
        self.status, self.message, self.code = int(status), detail, code

    def payload(self) -> dict:
        return {"ok": False, "detail": self.message, "error": self.message, "code": self.code}


def _center(session, value) -> str:
    """The center this call is about — and proof the caller may act there. RLS hands list_locations
    only the centers the profile belongs to, so a center id outside it never reaches Stripe.
    No id given -> A Touch of Blessings (owner rule), else the caller's own active center."""
    profile = getattr(session, "profile", None) or {}
    if profile.get("role") not in daycare_supabase.MANAGEMENT_ROLES:
        raise FeeError(403, "Management or admin access is required", "management_required")
    mine = {str(r.get("id")).lower() for r in daycare_supabase.list_locations(session).get("locations") or []}
    if value:
        center = daycare_supabase.require_uuid(value, "location_id").lower()
    else:
        center = ATOB if ATOB in mine else str(daycare_supabase.active_location(session)).lower()
    if center not in mine:
        raise FeeError(403, "You don't have access to that center", "location_mismatch")
    return center


def _iso(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _center_of(meta: dict) -> str | None:
    """Which center a link belongs to: its own center_id, else the GHL location tag the older links carry."""
    if meta.get("center_id"):
        return str(meta["center_id"]).lower()
    return daycare_ghl.LOCATION_ID_BY_TAG.get(str(meta.get("location") or ""))


def _pages(path: str, params: dict, key: str, cap: int = MAX_PAGES):
    """(rows, truncated). truncated = Stripe had more than `cap` pages we did not read."""
    out, after, more = [], None, False
    for _ in range(cap):
        q = dict(params, limit=100)
        if after:
            q["starting_after"] = after
        page = stripe_io._req("GET", path, q, key=key)
        data = page.get("data") or []
        out += data
        more = bool(page.get("has_more")) and bool(data)
        if not more:
            break
        after = data[-1]["id"]
    return out, more


def list_fees(session, q=None) -> dict:
    """Paid / unpaid fee links for one center. Stripe is the source of truth; cached 30 s."""
    center = _center(session, ((q or {}).get("location_id") or [""])[0])
    hit = _CACHE.get(center)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        key = stripe_io.key_for_location(center)
        # No date window: a window shorter than the links' life turns a paid fee back into "Unpaid".
        sessions, cut_s = _pages("/checkout/sessions", {}, key)
        links, cut_l = _pages("/payment_links", {"active": "true"}, key)
    except stripe_io.StripeError as e:
        raise FeeError(e.status if e.status < 600 else 502, e.message, e.code) from None
    rows: dict = {}
    for link in links:                                   # a link nobody opened yet has no sessions
        meta = link.get("metadata") or {}
        if meta.get("purpose") and _center_of(meta) == center:
            rows[link["id"]] = _row(link["id"], meta, link.get("url"))
    for s in sessions:
        meta = s.get("metadata") or {}
        if not meta.get("purpose") or _center_of(meta) != center:
            continue
        row = rows.setdefault(s.get("payment_link") or s["id"], _row(s.get("payment_link") or s["id"], meta))
        row["opens"] += 1
        row["amountCents"] = row["amountCents"] or s.get("amount_total")
        row["lastActivity"] = max(row["lastActivity"] or "", _iso(s.get("created")) or "") or None
        if s.get("payment_status") == "paid":
            row["status"], row["paidAt"] = "paid", row["paidAt"] or _iso(s.get("created"))
    out = sorted(rows.values(), key=lambda r: (r["status"] == "paid", _neg(r["lastActivity"])))
    paid = [r for r in out if r["status"] == "paid"]
    unpaid = [r for r in out if r["status"] != "paid"]
    result = {"ok": True, "centerId": center, "fees": out,
              "totals": {"paidCents": sum(r["amountCents"] or 0 for r in paid), "paidCount": len(paid),
                         "unpaidCents": sum(r["amountCents"] or 0 for r in unpaid), "unpaidCount": len(unpaid)},
              "testMode": stripe_io.is_test_key(key), "truncated": bool(cut_s or cut_l)}
    _CACHE[center] = (time.time(), result)
    return result


def _neg(iso):
    return -(datetime.fromisoformat(iso).timestamp()) if iso else 0


def _row(rid, meta, url=None) -> dict:
    purpose = str(meta.get("purpose") or "other")
    try:
        cents = int(meta.get("amount_cents") or 0) or None
    except ValueError:
        cents = None
    return {"id": rid, "family": meta.get("family") or "", "contactId": meta.get("ghl_contact_id") or "",
            "purpose": purpose, "label": PURPOSES.get(purpose, purpose.replace("-", " ")),
            "amountCents": cents, "status": "unpaid", "paidAt": None, "lastActivity": None, "opens": 0,
            "url": url}


def _money(cents: int) -> str:
    d = f"{cents // 100:,}" + ("" if cents % 100 == 0 else f".{cents % 100:02d}")
    return "$" + d


def create(session, body) -> dict:
    """Mint a per-family payment link and a draft text. Never sends, never charges."""
    body = body or {}
    family = re.sub(r"\s+", " ", str(body.get("family") or "")).strip()[:80]
    if len(family) < 2:
        raise FeeError(400, "Family name is required", "validation_error")
    purpose = str(body.get("purpose") or "registration-fee")
    if purpose not in PURPOSES:
        raise FeeError(400, "Pick a fee type from the list", "validation_error")
    try:
        usd = float(body.get("amount"))
    except (TypeError, ValueError):
        raise FeeError(400, "Amount must be a number", "validation_error") from None
    if not math.isfinite(usd) or usd < 1 or usd > MAX_USD:
        raise FeeError(400, f"Amount must be between $1 and ${MAX_USD:,.0f}", "validation_error")
    cents = int(round(usd * 100))
    contact = str(body.get("contact_id") or "").strip()
    if contact and not _GHL_ID.match(contact):
        raise FeeError(400, "Contact id looks wrong", "validation_error")
    center = _center(session, body.get("location_id"))
    if center == AMT:
        raise FeeError(409, NO_AMT_STRIPE, "no_center_stripe")
    guard = (contact or family.lower(), purpose, cents, center)
    with _LOCK:
        hit = _RECENT.get(guard)
        if hit and time.time() - hit[0] < 120:            # double tap -> the same link, never two
            return dict(hit[1], reused=True)
        try:
            key = stripe_io.key_for_location(center)
            brand = daycare_ghl._brand_link(center)[0]
            label = PURPOSES[purpose]
            meta = {"family": family, "ghl_contact_id": contact, "purpose": purpose,
                    "center_id": center, "location": _TAG_BY_ID.get(center, "loc-" + center[:8]),
                    "amount_cents": str(cents), "made_by": "forge-mobile"}
            link = stripe_io._req("POST", "/payment_links", {
                "line_items": [{"price_data": {"currency": "usd", "unit_amount": cents,
                                               "product_data": {"name": f"{label.capitalize()} - {brand}"}},
                                "quantity": 1}],
                "metadata": meta, "allow_promotion_codes": "false",
                "invoice_creation": {"enabled": "true"},        # a real receipt for the books
                "restrictions": {"completed_sessions": {"limit": "1"}},   # pay once: a paid link closes itself
            }, key=key)
        except stripe_io.StripeError as e:
            hint = " The Stripe key needs write access to Payment Links." if e.status == 403 else ""
            raise FeeError(e.status if e.status < 600 else 502, e.message + hint, e.code) from None
        result = {"ok": True, "url": link["url"], "linkId": link["id"], "centerId": center, "family": family,
                  "purpose": purpose, "amountCents": cents, "testMode": stripe_io.is_test_key(key),
                  "draft": f"Here is the link for the {_money(cents)} {label}: {link['url']} Thank you!",
                  "note": "Link made. Nothing was sent and nobody was charged."}
        _RECENT[guard] = (time.time(), result)
        _CACHE.pop(center, None)
    return result
