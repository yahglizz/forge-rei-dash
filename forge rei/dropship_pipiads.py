#!/usr/bin/env python3
"""dropship_pipiads.py — PiPiAds trending-products bridge for FORGE Dropship (stdlib).

This is the "watch new trending things" data source the operator asked for: instead of
Hawk reasoning over a product the operator typed in by hand, this pulls REAL winning /
trending products (TikTok + Facebook ad-spy signal, TikTok Shop revenue trend) from
PiPiAds so the crew scores products that are actually moving. THIS is where a paid API
call earns its money — real market signal, not a "little thing that doesn't matter".

Config in ``forge-dropship/config/dropship.env``:
  PIPIADS_API_KEY      — your PiPiAds API key (get it + billing at pipispy.com).
Blank → ``configured() == False`` and every call returns a clean "add key" mock. Nothing
calls out until a key is present, so a wrong default route can NEVER fabricate data.

NOTE ON ENDPOINTS: the base URL + paths are env-overridable
(``PIPIADS_API_BASE``, ``PIPIADS_TRENDING_PATH``, ``PIPIADS_SEARCH_PATH``) because the
exact routes should be confirmed against the PiPiAds API docs for your plan when the key
is added — same discipline as ``dropship_autods.py``. Until then the read is mock; a
configured-but-failing read returns an HONEST error, never invented rows (dropship creed).

Design mirrors ``dropship_autods`` / ``dropship_shopify``: urllib + retry, Bearer auth,
never leaks the key, read-only (this module NEVER spends ad budget or places an order).
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


class PiPiAdsError(Exception):
    def __init__(self, status: int, message: str, code: str = "pipiads_error"):
        super().__init__(message)
        self.status = int(status)
        self.message = message
        self.code = code


def _key() -> str:
    return dropship_env.get("PIPIADS_API_KEY", "").strip()


def _base() -> str:
    return dropship_env.get("PIPIADS_API_BASE", "https://open.pipiads.com").strip().rstrip("/")


def configured() -> bool:
    return bool(_key())


def _auth_headers(key: str) -> dict:
    """PiPiAds accepts the key as a Bearer token by default; override the header name via
    PIPIADS_AUTH_HEADER if your plan expects e.g. 'X-API-KEY' instead."""
    header = dropship_env.get("PIPIADS_AUTH_HEADER", "Authorization").strip() or "Authorization"
    value = key if header.lower() != "authorization" else f"Bearer {key}"
    return {header: value, "Content-Type": "application/json", "Accept": "application/json"}


def _req(method: str, path: str, params: dict | None = None) -> dict:
    key = _key()
    if not key:
        raise PiPiAdsError(503, "PiPiAds is not configured", "not_configured")
    url = f"{_base()}{path}"
    data = None
    if method == "GET" and params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    elif method in ("POST", "PUT") and params is not None:
        data = json.dumps(params).encode("utf-8")
    headers = _auth_headers(key)
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
            detail = "PiPiAds request failed"
            try:
                payload = json.loads(error.read().decode("utf-8"))
                detail = payload.get("message") or payload.get("msg") or payload.get("error") or detail
            except Exception:
                pass
            raise PiPiAdsError(error.code, str(detail), "pipiads_http_error") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
            if attempt < _RETRIES:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise PiPiAdsError(502, "PiPiAds is temporarily unavailable", "upstream_unavailable") from None
    raise PiPiAdsError(502, "PiPiAds is temporarily unavailable", "upstream_unavailable") from last_error


def _mock(extra: dict | None = None) -> dict:
    out = {"ok": True, "configured": False, "source": "pipiads",
           "detail": "Add PIPIADS_API_KEY to dropship.env (key + billing at pipispy.com)."}
    if extra:
        out.update(extra)
    return out


def _normalize(rows) -> list:
    """Best-effort map PiPiAds product rows into the shape Product Watch understands.
    We keep the raw row too so nothing real is ever dropped. Only fields that ARE present
    get filled — no field is ever invented."""
    rows = rows if isinstance(rows, list) else []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = (r.get("product_title") or r.get("title") or r.get("name")
                or r.get("product_name") or "").strip()
        out.append({
            "name": name or "(untitled)",
            "sourceUrl": r.get("product_url") or r.get("url") or r.get("landing_url") or "",
            "supplier": "PiPiAds trend",
            "signal": {  # real market signal for Hawk to ground on (present-only)
                "adCount": r.get("ad_count") or r.get("ads") or r.get("total_ads"),
                "revenueTrend": r.get("revenue") or r.get("revenue_trend") or r.get("gmv"),
                "category": r.get("category") or r.get("category_name"),
                "impressions": r.get("impression") or r.get("impressions"),
                "firstSeen": r.get("first_seen") or r.get("start_date"),
                "country": r.get("country") or r.get("region"),
            },
            "raw": r,
        })
    return out


def health() -> dict:
    """Presence only until a key is set; a live probe once it is. Never leaks the key."""
    if not configured():
        return _mock({"connected": False})
    try:
        path = dropship_env.get("PIPIADS_TRENDING_PATH", "/api/v1/products/trending")
        _req("GET", path, {"limit": 1})
        return {"ok": True, "configured": True, "connected": True, "source": "pipiads"}
    except PiPiAdsError as e:
        return {"ok": False, "configured": True, "connected": False,
                "source": "pipiads", "error": e.message}


def trending(query: str = "", limit: int = 20) -> dict:
    """Pull real trending / winning products. Optional ``query`` filters by keyword or
    category. Honest error on failure — never fabricated rows."""
    if not configured():
        return _mock({"products": []})
    try:
        q = (query or "").strip()
        limit = max(1, min(int(limit or 20), 100))
        if q:
            path = dropship_env.get("PIPIADS_SEARCH_PATH", "/api/v1/products/search")
            params = {"keyword": q, "limit": limit}
        else:
            path = dropship_env.get("PIPIADS_TRENDING_PATH", "/api/v1/products/trending")
            params = {"limit": limit}
        data = _req("GET", path, params)
        rows = (data.get("data") if isinstance(data, dict) else None)
        if isinstance(rows, dict):
            rows = rows.get("list") or rows.get("results") or rows.get("products")
        if rows is None and isinstance(data, dict):
            rows = data.get("results") or data.get("products") or data.get("list")
        products = _normalize(rows)
        return {"ok": True, "configured": True, "source": "pipiads",
                "query": q, "products": products, "count": len(products)}
    except PiPiAdsError as e:
        return {"ok": False, "configured": True, "source": "pipiads",
                "error": e.message, "products": []}
