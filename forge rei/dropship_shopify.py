#!/usr/bin/env python3
"""dropship_shopify.py — Shopify Admin REST bridge for FORGE Dropship (stdlib only).

Reads the store's orders, products, and inventory so Midas / Otto can ground the
operating brief in real data. **Read-only today** — every write (publish/edit a
listing, fulfill an order) is a gated stub, so nothing outward happens without the
operator's approval per root CLAUDE.md rule 2.

Config lives in ``forge-dropship/config/dropship.env`` (git-ignored, 404 over HTTP):
``SHOPIFY_STORE_DOMAIN`` (your-store.myshopify.com), ``SHOPIFY_ADMIN_TOKEN`` (a custom
app's Admin API access token, ``shpat_...``), ``SHOPIFY_API_VERSION`` (default 2024-10).
When any is blank ``configured() == False`` and every call returns a clean "add key"
result — nothing errors, no rebuild needed to go live.

Design mirrors ``stripe_io`` / ``GHLClient``: urllib + retry. No secret is ever
returned to the browser — callers surface presence only.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import dropship_env

_TIMEOUT = 20
_RETRIES = 2


class ShopifyError(Exception):
    def __init__(self, status: int, message: str, code: str = "shopify_error"):
        super().__init__(message)
        self.status = int(status)
        self.message = message
        self.code = code


def _domain() -> str:
    return dropship_env.get("SHOPIFY_STORE_DOMAIN", "").strip()


def _token() -> str:
    return dropship_env.get("SHOPIFY_ADMIN_TOKEN", "").strip()


def _version() -> str:
    return dropship_env.get("SHOPIFY_API_VERSION", "2024-10").strip() or "2024-10"


def configured() -> bool:
    dom, tok = _domain(), _token()
    return bool(dom and tok and not tok.startswith("shpat_...") and "your-store" not in dom)


def _req(method: str, path: str, params: dict | None = None) -> dict:
    dom, tok = _domain(), _token()
    if not (dom and tok):
        raise ShopifyError(503, "Shopify is not configured", "not_configured")
    url = f"https://{dom}/admin/api/{_version()}{path}"
    data = None
    if method == "GET" and params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    elif method in ("POST", "PUT") and params is not None:
        data = json.dumps(params).encode("utf-8")
    headers = {
        "X-Shopify-Access-Token": tok,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    last_error: Exception | None = None
    for attempt in range(_RETRIES + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < _RETRIES:
                time.sleep(0.6 * (attempt + 1))
                last_error = error
                continue
            detail = "Shopify request failed"
            try:
                payload = json.loads(error.read().decode("utf-8"))
                detail = payload.get("errors") or detail
                if isinstance(detail, dict):
                    detail = "; ".join(f"{k}: {v}" for k, v in detail.items())
            except Exception:
                pass
            raise ShopifyError(error.code, str(detail), "shopify_http_error") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
            if attempt < _RETRIES:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise ShopifyError(502, "Shopify is temporarily unavailable", "upstream_unavailable") from None
    raise ShopifyError(502, "Shopify is temporarily unavailable", "upstream_unavailable") from last_error


def _mock(extra: dict | None = None) -> dict:
    out = {"ok": True, "configured": False,
           "detail": "Add SHOPIFY_STORE_DOMAIN + SHOPIFY_ADMIN_TOKEN to dropship.env."}
    if extra:
        out.update(extra)
    return out


# --- reads -----------------------------------------------------------------

def health() -> dict:
    """Presence + a live ping. Never leaks the token."""
    if not configured():
        return _mock({"connected": False})
    try:
        shop = _req("GET", "/shop.json").get("shop", {}) or {}
        return {"ok": True, "configured": True, "connected": True,
                "shop": {"name": shop.get("name"), "domain": shop.get("domain"),
                         "currency": shop.get("currency"),
                         "plan": shop.get("plan_display_name")}}
    except ShopifyError as e:
        return {"ok": False, "configured": True, "connected": False, "error": e.message}


def _slim_order(o: dict) -> dict:
    return {
        "id": o.get("id"),
        "name": o.get("name"),
        "createdAt": o.get("created_at"),
        "total": o.get("total_price"),
        "currency": o.get("currency"),
        "financialStatus": o.get("financial_status"),
        "fulfillmentStatus": o.get("fulfillment_status") or "unfulfilled",
        "customer": ((o.get("customer") or {}).get("first_name") or "") + " "
                    + ((o.get("customer") or {}).get("last_name") or ""),
        "items": len(o.get("line_items") or []),
    }


def orders(limit: int = 25, status: str = "any") -> dict:
    if not configured():
        return _mock({"orders": []})
    try:
        data = _req("GET", "/orders.json",
                    {"status": status, "limit": max(1, min(int(limit), 250))})
        rows = [_slim_order(o) for o in (data.get("orders") or [])]
        unfulfilled = sum(1 for r in rows if r["fulfillmentStatus"] in (None, "unfulfilled", "partial"))
        return {"ok": True, "configured": True, "orders": rows,
                "count": len(rows), "unfulfilled": unfulfilled}
    except ShopifyError as e:
        return {"ok": False, "configured": True, "error": e.message, "orders": []}


def _slim_product(p: dict) -> dict:
    variants = p.get("variants") or []
    stock = sum((v.get("inventory_quantity") or 0) for v in variants)
    prices = [float(v.get("price") or 0) for v in variants if v.get("price")]
    return {
        "id": p.get("id"),
        "title": p.get("title"),
        "status": p.get("status"),
        "vendor": p.get("vendor"),
        "variants": len(variants),
        "stock": stock,
        "price": min(prices) if prices else None,
    }


def products(limit: int = 50) -> dict:
    if not configured():
        return _mock({"products": []})
    try:
        data = _req("GET", "/products.json", {"limit": max(1, min(int(limit), 250))})
        rows = [_slim_product(p) for p in (data.get("products") or [])]
        return {"ok": True, "configured": True, "products": rows, "count": len(rows)}
    except ShopifyError as e:
        return {"ok": False, "configured": True, "error": e.message, "products": []}


def inventory(low_threshold: int = 5) -> dict:
    """Low-stock read derived from product variants — the fastest signal for a
    stockout on a winner (an account-health item per Otto's creed)."""
    if not configured():
        return _mock({"low": [], "lowThreshold": low_threshold})
    try:
        data = _req("GET", "/products.json", {"limit": 250})
        low = []
        for p in (data.get("products") or []):
            for v in (p.get("variants") or []):
                qty = v.get("inventory_quantity")
                if qty is not None and qty <= low_threshold:
                    low.append({"product": p.get("title"), "variant": v.get("title"),
                                "sku": v.get("sku"), "stock": qty,
                                "status": p.get("status")})
        low.sort(key=lambda r: r["stock"])
        return {"ok": True, "configured": True, "low": low,
                "count": len(low), "lowThreshold": low_threshold}
    except ShopifyError as e:
        return {"ok": False, "configured": True, "error": e.message, "low": []}


def snapshot() -> dict:
    """One call the brief can lean on: health + counts. Read-only."""
    h = health()
    if not h.get("connected"):
        return {"ok": True, "configured": configured(), "connected": False, **h}
    o = orders(limit=50)
    inv = inventory()
    return {
        "ok": True, "configured": True, "connected": True,
        "shop": h.get("shop"),
        "orders": o.get("count", 0),
        "unfulfilled": o.get("unfulfilled", 0),
        "lowStock": inv.get("count", 0),
    }
