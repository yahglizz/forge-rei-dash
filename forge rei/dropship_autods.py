#!/usr/bin/env python3
"""dropship_autods.py — AutoDS bridge for FORGE Dropship (stdlib only).

Reads AutoDS sourcing data — products (supplier cost, stock, price-monitor state)
and orders — so Midas/Hawk/Otto can ground margin math and fulfillment health in
real supplier numbers. **Read-only today**; placing/approving an auto-order stays a
gated stub (rule 2).

Config in ``forge-dropship/config/dropship.env``: ``AUTODS_API_KEY`` (AutoDS API
token) + ``AUTODS_STORE_ID``. Blank → ``configured() == False`` and every call
returns a clean "add key" result.

NOTE ON ENDPOINTS: AutoDS's API base + paths are env-overridable
(``AUTODS_API_BASE``, ``AUTODS_PRODUCTS_PATH``, ``AUTODS_ORDERS_PATH``) because the
exact routes should be confirmed against the AutoDS API docs for the account tier
when the key is added. Defaults follow the AutoDS Platform API v2 shape. Until a key
is present nothing calls out, so a wrong default can never fabricate data — an
unconfigured read returns mock, and a configured-but-failing read returns an honest
error, never invented numbers (per the dropship creed).

Design mirrors ``stripe_io`` / ``dropship_shopify``: urllib + retry, Bearer auth.
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


class AutoDSError(Exception):
    def __init__(self, status: int, message: str, code: str = "autods_error"):
        super().__init__(message)
        self.status = int(status)
        self.message = message
        self.code = code


def _key() -> str:
    return dropship_env.get("AUTODS_API_KEY", "").strip()


def _store_id() -> str:
    return dropship_env.get("AUTODS_STORE_ID", "").strip()


def _base() -> str:
    return dropship_env.get("AUTODS_API_BASE", "https://v2-api.autods.com").strip().rstrip("/")


def configured() -> bool:
    return bool(_key())


def _req(method: str, path: str, params: dict | None = None) -> dict:
    key = _key()
    if not key:
        raise AutoDSError(503, "AutoDS is not configured", "not_configured")
    url = f"{_base()}{path}"
    data = None
    if method == "GET" and params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    elif method in ("POST", "PUT") and params is not None:
        data = json.dumps(params).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {key}",
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
            detail = "AutoDS request failed"
            try:
                payload = json.loads(error.read().decode("utf-8"))
                detail = payload.get("message") or payload.get("error") or detail
            except Exception:
                pass
            raise AutoDSError(error.code, str(detail), "autods_http_error") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
            if attempt < _RETRIES:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise AutoDSError(502, "AutoDS is temporarily unavailable", "upstream_unavailable") from None
    raise AutoDSError(502, "AutoDS is temporarily unavailable", "upstream_unavailable") from last_error


def _mock(extra: dict | None = None) -> dict:
    out = {"ok": True, "configured": False,
           "detail": "Add AUTODS_API_KEY (+ AUTODS_STORE_ID) to dropship.env."}
    if extra:
        out.update(extra)
    return out


def health() -> dict:
    """Presence only until a key is set; a live ping once it is. Never leaks the key."""
    if not configured():
        return _mock({"connected": False})
    # A lightweight probe: list one product. Any 2xx means the token works.
    try:
        path = dropship_env.get("AUTODS_PRODUCTS_PATH", "/products/")
        params = {"limit": 1}
        sid = _store_id()
        if sid:
            params["store_id"] = sid
        _req("GET", path, params)
        return {"ok": True, "configured": True, "connected": True}
    except AutoDSError as e:
        return {"ok": False, "configured": True, "connected": False, "error": e.message}


def products(limit: int = 50) -> dict:
    """Supplier-side product list (cost, stock, monitor state). Honest error on
    failure — never fabricated rows."""
    if not configured():
        return _mock({"products": []})
    try:
        path = dropship_env.get("AUTODS_PRODUCTS_PATH", "/products/")
        params = {"limit": max(1, min(int(limit), 200))}
        sid = _store_id()
        if sid:
            params["store_id"] = sid
        data = _req("GET", path, params)
        rows = data.get("results") if isinstance(data, dict) else data
        rows = rows if isinstance(rows, list) else []
        return {"ok": True, "configured": True, "products": rows, "count": len(rows)}
    except AutoDSError as e:
        return {"ok": False, "configured": True, "error": e.message, "products": []}


def marketplace(limit: int = 25, query: str = "") -> dict:
    """AutoDS Marketplace / Product Finding Hub — winning + trending products (the
    'product watcher' the operator asked for). This is a PAID add-on on AutoDS and may
    not be exposed on every account tier's API, so the path is env-overridable
    (``AUTODS_MARKETPLACE_PATH``) and confirmed against the docs when the key is added.
    Read-only; mock until keyed; honest error, never fabricated rows."""
    if not configured():
        return _mock({"products": []})
    try:
        path = dropship_env.get("AUTODS_MARKETPLACE_PATH", "/marketplace/products/")
        params = {"limit": max(1, min(int(limit), 100))}
        q = (query or "").strip()
        if q:
            params["search"] = q
        sid = _store_id()
        if sid:
            params["store_id"] = sid
        data = _req("GET", path, params)
        rows = data.get("results") if isinstance(data, dict) else data
        rows = rows if isinstance(rows, list) else []
        out = []
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            out.append({
                "name": (r.get("title") or r.get("name") or r.get("product_name")
                         or "(untitled)"),
                "sourceUrl": r.get("url") or r.get("product_url") or "",
                "supplier": "AutoDS marketplace",
                "cost": r.get("buy_price") or r.get("cost") or r.get("price"),
                "signal": {
                    "sellPrice": r.get("sell_price") or r.get("recommended_price"),
                    "sold": r.get("sold_count") or r.get("orders") or r.get("sold"),
                    "category": r.get("category") or r.get("category_name"),
                    "supplierName": r.get("supplier") or r.get("source"),
                },
                "raw": r,
            })
        return {"ok": True, "configured": True, "source": "autods",
                "products": out, "count": len(out)}
    except AutoDSError as e:
        return {"ok": False, "configured": True, "source": "autods",
                "error": e.message, "products": []}


def orders(limit: int = 50) -> dict:
    if not configured():
        return _mock({"orders": []})
    try:
        path = dropship_env.get("AUTODS_ORDERS_PATH", "/orders/")
        params = {"limit": max(1, min(int(limit), 200))}
        sid = _store_id()
        if sid:
            params["store_id"] = sid
        data = _req("GET", path, params)
        rows = data.get("results") if isinstance(data, dict) else data
        rows = rows if isinstance(rows, list) else []
        return {"ok": True, "configured": True, "orders": rows, "count": len(rows)}
    except AutoDSError as e:
        return {"ok": False, "configured": True, "error": e.message, "orders": []}
