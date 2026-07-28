#!/usr/bin/env python3
"""dropship_winninghunter.py — WinningHunter research bridge (stdlib only).

Supplies the EVIDENCE half of the product decision packet: which ads are running,
how long each creative has been live, which stores sell the product, and at what
price. The *why it's winning* read is Midas's job — his existing
``dropship-four-triggers-ad-writer`` and ``dropship-meta-ads-diagnostician``
skills do that analysis; this module just stops them reasoning over nothing.

**Read-only. No write endpoint exists here and none should.** Research is
thinking, not an outward action (root CLAUDE.md rule 2 is untouched by this file).

Why this matters at all: Meta's FREE Ad Library API returns non-EU ads only when
they are about social issues, elections or politics — US commercial dropship ads
are visible in the browser UI but are **not** returned by the free API. That gap
is the entire reason a paid ad-spy subscription is justified.

Config in ``forge-dropship/config/dropship.env`` (git-ignored, 404 over HTTP):
``WINNINGHUNTER_API_KEY``. Unkeyed, ``configured() == False`` and every call
returns a clean "add key" mock — nothing errors, no rebuild needed to go live.

⚠️  **The request shape is env-overridable on purpose.** WinningHunter's docs sit
behind an account, so the exact paths, auth header and response field names are
UNVERIFIED until the operator subscribes. Rather than hardcode a guess — the
mistake already sitting in ``dropship_pipiads.py``, which assumed REST paths and
a header key when the real API is a single POST gateway — every one of those is a
``WINNINGHUNTER_*`` env var. When the account exists, one env edit corrects the
shape with no code change and no redeploy. ``_normalize_ad`` reads through a
candidate-key list for the same reason.

Also unverified and worth confirming before payment: **which plan tier unlocks
API access.** Their docs never say, and a ``403`` from this client means exactly
that — see ``health()``.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import dropship_env
import research_guard as guard

_TIMEOUT = 20
_RETRIES = 2

SOURCE = "WinningHunter"


class WinningHunterError(Exception):
    def __init__(self, status: int, message: str, code: str = "wh_error"):
        super().__init__(message)
        self.status = int(status)
        self.message = message
        self.code = code


# --- config ----------------------------------------------------------------

def _key() -> str:
    return dropship_env.get("WINNINGHUNTER_API_KEY", "").strip()


def _base() -> str:
    return dropship_env.get(
        "WINNINGHUNTER_API_BASE", "https://app.winninghunter.com").strip().rstrip("/")


def _path(name: str, default: str) -> str:
    return dropship_env.get(f"WINNINGHUNTER_{name}_PATH", default).strip() or default


def _auth_header() -> str:
    """Header name carrying the key. Bearer is the common shape; overridable
    because we have not seen their docs."""
    return dropship_env.get("WINNINGHUNTER_AUTH_HEADER", "Authorization").strip() or "Authorization"


def _auth_prefix() -> str:
    """Scheme in front of the key, e.g. ``Bearer ``.

    The trailing space is re-added here on purpose. ``dropship_env.read_env()``
    ``.strip()``s every value, so a space typed at the end of an env line cannot
    survive the file — writing ``WINNINGHUNTER_AUTH_PREFIX=Bearer`` would otherwise
    produce the header ``Bearer<key>`` and a guaranteed 401 that looks exactly like
    a bad key. Set the var to ``none`` for a raw key with no scheme.
    """
    raw = dropship_env.get("WINNINGHUNTER_AUTH_PREFIX", "Bearer ")
    if raw.strip().lower() in ("none", "raw", "-"):
        return ""
    raw = raw.strip()
    return (raw + " ") if raw else ""


def configured() -> bool:
    k = _key()
    return bool(k) and not k.startswith("your-") and not k.startswith("wh_...")


def _mock(extra: dict | None = None) -> dict:
    out = {"ok": True, "configured": False,
           "detail": "Add WINNINGHUNTER_API_KEY to dropship.env.",
           "source": SOURCE}
    if extra:
        out.update(extra)
    return out


# --- transport --------------------------------------------------------------

def _req(method: str, path: str, params: dict | None = None) -> dict:
    key = _key()
    if not key:
        raise WinningHunterError(503, "WinningHunter is not configured", "not_configured")
    url = f"{_base()}{path}"
    data = None
    if method == "GET" and params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    elif method == "POST" and params is not None:
        data = json.dumps(params).encode("utf-8")
    headers = {
        _auth_header(): f"{_auth_prefix()}{key}",
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
            # 60 req/min documented; back off rather than burn the window.
            if error.code in (429, 500, 502, 503, 504) and attempt < _RETRIES:
                time.sleep(1.2 * (attempt + 1))
                last_error = error
                continue
            if error.code == 403:
                raise WinningHunterError(
                    403,
                    "403 from WinningHunter — this usually means the plan tier does not "
                    "include API access. Confirm with their sales which tier unlocks it.",
                    "no_api_access") from None
            detail = "WinningHunter request failed"
            try:
                payload = json.loads(error.read().decode("utf-8"))
                detail = payload.get("message") or payload.get("error") or detail
            except Exception:
                pass
            raise WinningHunterError(error.code, str(detail), "wh_http_error") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
            if attempt < _RETRIES:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise WinningHunterError(502, "WinningHunter is temporarily unavailable",
                                     "upstream_unavailable") from None
    raise WinningHunterError(502, "WinningHunter is temporarily unavailable",
                             "upstream_unavailable") from last_error


# --- normalisation ----------------------------------------------------------

def _first(row: dict, *names, default=None):
    """Read through a candidate-key list — vendor field names are unverified."""
    for n in names:
        if isinstance(row, dict) and row.get(n) not in (None, ""):
            return row[n]
    return default


def _days_between(first_seen, last_seen) -> int | None:
    """Days a creative has been live. THE proof-of-profit proxy — nobody funds a
    losing ad for 90 days. Returns None (→ Unknown) when either end is missing."""
    a, b = _parse_ts(first_seen), _parse_ts(last_seen)
    if a is None:
        return None
    if b is None:
        b = time.time()
    return max(0, int((b - a) // 86400))


def _parse_ts(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        # seconds vs milliseconds
        return float(v) / 1000.0 if float(v) > 1e11 else float(v)
    s = str(v).strip().replace("Z", "+0000")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except Exception:
            continue
    return None


def _normalize_ad(row: dict) -> dict:
    """One ad → the fields the packet actually reads. Text fields go through the
    injection guard; numbers stay numbers so the money math still works."""
    first_seen = _first(row, "first_seen", "firstSeen", "start_date", "startDate", "created_at")
    last_seen = _first(row, "last_seen", "lastSeen", "end_date", "endDate", "updated_at")
    days = _days_between(first_seen, last_seen)
    return {
        "id": _first(row, "id", "ad_id", "adId"),
        "advertiser": guard.inert(_first(row, "advertiser", "page_name", "pageName",
                                         "brand", default=""), "advertiser"),
        "headline": guard.inert(_first(row, "headline", "title", "ad_title", default=""), "headline"),
        "copy": guard.inert(_first(row, "copy", "body", "ad_copy", "text", default=""), "ad_copy"),
        "format": _first(row, "format", "media_type", "mediaType", "type"),
        "platform": _first(row, "platform", "network", "source"),
        "landingPage": _first(row, "landing_page", "landingPage", "link", "url"),
        "store": _first(row, "store", "shop", "domain", "store_domain"),
        "firstSeen": first_seen,
        "lastSeen": last_seen,
        # The one derived number the whole packet leans on.
        "daysRunning": guard.stamp(
            days, SOURCE, window=f"{first_seen or guard.UNKNOWN} → {last_seen or 'now'}",
            confidence="derived from vendor first/last-seen dates"),
        "likes": _first(row, "likes", "reactions"),
        "comments": _first(row, "comments"),
        "shares": _first(row, "shares"),
    }


# --- reads ------------------------------------------------------------------

def health() -> dict:
    """Presence + a live ping. Never leaks the key."""
    if not configured():
        return _mock({"connected": False})
    try:
        _req("GET", _path("HEALTH", "/api/v1/me"))
        return {"ok": True, "configured": True, "connected": True, "source": SOURCE}
    except WinningHunterError as e:
        return {"ok": False, "configured": True, "connected": False,
                "error": e.message, "code": e.code, "source": SOURCE}


def search_ads(query: str, limit: int = 25, **filters) -> dict:
    """Ads matching a product/keyword, richest-signal first (longest-running).

    Sorting by ``daysRunning`` here rather than in the UI is deliberate: longevity
    is the evidence, so it is the default order everywhere downstream.
    """
    if not configured():
        return _mock({"ads": [], "query": query})
    params = {"query": query, "limit": max(1, min(int(limit), 100))}
    params.update({k: v for k, v in filters.items() if v not in (None, "")})
    try:
        data = _req("GET", _path("ADS", "/api/v1/ads"), params)
        raw = data.get("data") or data.get("ads") or data.get("results") or []
        rows = [_normalize_ad(r) for r in raw if isinstance(r, dict)]
        rows.sort(key=lambda r: (r["daysRunning"]["value"] or -1), reverse=True)
        return {"ok": True, "configured": True, "source": SOURCE, "query": query,
                "ads": rows, "count": len(rows),
                "flagged": guard.flagged_fields(rows)}
    except WinningHunterError as e:
        return {"ok": False, "configured": True, "source": SOURCE,
                "error": e.message, "code": e.code, "ads": []}


def store(domain: str) -> dict:
    """One competitor store: revenue estimate, product count, top products."""
    if not configured():
        return _mock({"store": None, "domain": domain})
    try:
        data = _req("GET", _path("STORE", "/api/v1/stores"), {"domain": domain})
        row = data.get("data") or data.get("store") or data
        if not isinstance(row, dict):
            row = {}
        return {
            "ok": True, "configured": True, "source": SOURCE, "domain": domain,
            "name": guard.inert(_first(row, "name", "title", default=""), "store_name"),
            # Revenue is the least trustworthy thing this category sells — stamped,
            # never bare. See research_guard.REVENUE_CONFIDENCE.
            "revenueMonthly": guard.stamp(
                _first(row, "revenue", "monthly_revenue", "monthlyRevenue"),
                SOURCE, window="trailing 30d", confidence=guard.REVENUE_CONFIDENCE),
            "salesMonthly": guard.stamp(
                _first(row, "sales", "monthly_sales", "monthlySales"),
                SOURCE, window="trailing 30d", confidence=guard.COUNT_CONFIDENCE),
            "products": _first(row, "products", "product_count", "productCount"),
            "topProducts": guard.inert_deep(
                _first(row, "top_products", "topProducts", default=[]), "top_products"),
        }
    except WinningHunterError as e:
        return {"ok": False, "configured": True, "source": SOURCE,
                "error": e.message, "code": e.code, "store": None}


def search_products(query: str, limit: int = 25) -> dict:
    """Products matching a term, across tracked stores."""
    if not configured():
        return _mock({"products": [], "query": query})
    try:
        data = _req("GET", _path("PRODUCTS", "/api/v1/products"),
                    {"query": query, "limit": max(1, min(int(limit), 100))})
        raw = data.get("data") or data.get("products") or data.get("results") or []
        rows = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            rows.append({
                "id": _first(r, "id", "product_id"),
                "title": guard.inert(_first(r, "title", "name", default=""), "product_title"),
                "price": _first(r, "price", "sale_price"),
                "store": _first(r, "store", "domain", "shop"),
                "image": _first(r, "image", "image_url", "thumbnail"),
                "salesMonthly": guard.stamp(
                    _first(r, "sales", "monthly_sales", "monthlySales"),
                    SOURCE, window="trailing 30d", confidence=guard.COUNT_CONFIDENCE),
                "revenueMonthly": guard.stamp(
                    _first(r, "revenue", "monthly_revenue", "monthlyRevenue"),
                    SOURCE, window="trailing 30d", confidence=guard.REVENUE_CONFIDENCE),
            })
        return {"ok": True, "configured": True, "source": SOURCE, "query": query,
                "products": rows, "count": len(rows),
                "flagged": guard.flagged_fields(rows)}
    except WinningHunterError as e:
        return {"ok": False, "configured": True, "source": SOURCE,
                "error": e.message, "code": e.code, "products": []}


def evidence(query: str, ad_limit: int = 25) -> dict:
    """One call the packet leans on: ads + products for a candidate, plus the
    derived longevity/saturation read. Read-only."""
    if not configured():
        return _mock({"ads": [], "products": []})
    ads = search_ads(query, limit=ad_limit)
    prods = search_products(query, limit=25)
    rows = ads.get("ads") or []
    running = [r["daysRunning"]["value"] for r in rows if r["daysRunning"]["value"] is not None]
    advertisers = {r.get("store") or (r.get("advertiser") or {}).get("text")
                   for r in rows if r.get("store") or r.get("advertiser")}
    return {
        "ok": True, "configured": True, "source": SOURCE, "query": query,
        "ads": rows,
        "products": prods.get("products") or [],
        "longestRunningDays": guard.stamp(
            max(running) if running else None, SOURCE, window="all matched ads",
            confidence="derived"),
        "advertiserCount": guard.stamp(
            len(advertisers) if rows else None, SOURCE, window="all matched ads",
            confidence="derived"),
        "flagged": (ads.get("flagged") or []) + (prods.get("flagged") or []),
    }
