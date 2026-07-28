#!/usr/bin/env python3
"""etsy_everbee.py — EverBee Research Open API bridge (stdlib only).

Supplies the Etsy half of the product decision packet: keyword volume and
competition, plus listing- and shop-level demand estimates. Read-only; nothing
here lists, edits, or messages.

**Why EverBee and not Etsy directly.** Etsy's own Open API v3 exposes NO
analytics, NO search-volume and NO messages endpoints — lifetime listing views
and nothing else. Every Etsy keyword tool in existence is therefore scrape-derived,
and EverBee is the only vendor of them with a real documented API (verified
against their OpenAPI 3.0.3 spec). eRank, Alura, Sale Samurai, Marmalead,
Koalanda and Roketfy have no API of any kind; none of them ship an MCP server.

**We deliberately do not touch Etsy's own API here.** Etsy's API Terms of Use
(2025-06-16) prohibit using it "for purposes of analytics, machine learning,
training artificial intelligence models", and the general Terms §C (2025-08-26)
prohibit members from crawling or scraping. Routing research through EverBee
leaves that exposure with EverBee. Direct Etsy API use becomes a live question
only if programmatic listing is ever built — a separate spec, separate decision.

**Accuracy, stated up front and stamped on every figure.** Etsy never exposes
per-listing sales, so ``est_mo_sales`` is necessarily modelled — the inputs
(views, favourites, category, listing age, shop lifetime sale counter) are real,
the transfer function is invented and unpublished. Sellers report 20 estimated
against 8 actual on low-volume listings. Keyword volume is likewise an estimate;
eRank, the category leader, publicly concedes its numbers diverge from Etsy's own.
Ground truth lives in **Etsy Marketplace Insights** (Etsy Plus, $10/mo,
dashboard-only, no API) — its job is to calibrate this feed, not to replace it.

Config in ``forge-dropship/config/dropship.env`` (git-ignored, 404 over HTTP):
``EVERBEE_CLIENT_ID`` + ``EVERBEE_CLIENT_SECRET``. Unkeyed, ``configured() ==
False`` and every call returns a clean "add key" mock.

⚠️  Two things unverifiable without an account, both flagged by ``health()``:
whether the API is a separate paid add-on (their pricing is published nowhere),
and whether the subscribed tier actually returns the sales/revenue fields — their
guide says data is "filtered to match that user's subscription", so a lower tier
may return keywords while nulling ``est_mo_sales``. A null lands as Unknown,
which is the correct behaviour either way.
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

SOURCE = "EverBee"

# Published limits: 10 requests/second, 50,000 per rolling 24h window.
_MIN_INTERVAL = 0.12
_last_call = [0.0]


class EverBeeError(Exception):
    def __init__(self, status: int, message: str, code: str = "everbee_error"):
        super().__init__(message)
        self.status = int(status)
        self.message = message
        self.code = code


def _client_id() -> str:
    return dropship_env.get("EVERBEE_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return dropship_env.get("EVERBEE_CLIENT_SECRET", "").strip()


def _base() -> str:
    return dropship_env.get(
        "EVERBEE_API_BASE", "https://research-open-api.everbee.com").strip().rstrip("/")


def configured() -> bool:
    cid, sec = _client_id(), _client_secret()
    return bool(cid and sec) and not cid.startswith("your-")


def _mock(extra: dict | None = None) -> dict:
    out = {"ok": True, "configured": False,
           "detail": "Add EVERBEE_CLIENT_ID + EVERBEE_CLIENT_SECRET to dropship.env.",
           "source": SOURCE}
    if extra:
        out.update(extra)
    return out


def _req(path: str, params: dict | None = None) -> dict:
    cid, sec = _client_id(), _client_secret()
    if not (cid and sec):
        raise EverBeeError(503, "EverBee is not configured", "not_configured")
    # Cheap client-side throttle so a wide sweep cannot trip the documented 10 QPS.
    gap = time.time() - _last_call[0]
    if gap < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - gap)
    url = f"{_base()}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, '')})}"
    headers = {"client_id": cid, "client_secret": sec, "Accept": "application/json"}
    last_error: Exception | None = None
    for attempt in range(_RETRIES + 1):
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                _last_call[0] = time.time()
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except urllib.error.HTTPError as error:
            _last_call[0] = time.time()
            if error.code == 429 and attempt < _RETRIES:
                # They send Retry-After; honour it rather than guessing.
                wait = 2.0 * (attempt + 1)
                try:
                    wait = max(wait, float(error.headers.get("Retry-After") or 0))
                except Exception:
                    pass
                time.sleep(min(wait, 10.0))
                last_error = error
                continue
            if error.code in (500, 502, 503, 504) and attempt < _RETRIES:
                time.sleep(0.8 * (attempt + 1))
                last_error = error
                continue
            if error.code in (401, 403):
                raise EverBeeError(
                    error.code,
                    "EverBee rejected the credentials. Confirm the API is included in "
                    "your plan (it may be a paid add-on) and that the app install is approved.",
                    "no_api_access") from None
            detail = "EverBee request failed"
            try:
                payload = json.loads(error.read().decode("utf-8"))
                detail = payload.get("message") or payload.get("error") or detail
            except Exception:
                pass
            raise EverBeeError(error.code, str(detail), "everbee_http_error") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
            if attempt < _RETRIES:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise EverBeeError(502, "EverBee is temporarily unavailable",
                               "upstream_unavailable") from None
    raise EverBeeError(502, "EverBee is temporarily unavailable",
                       "upstream_unavailable") from last_error


def _rows(data: dict, *names) -> list:
    for n in names:
        v = data.get(n)
        if isinstance(v, list):
            return v
    return data.get("data") if isinstance(data.get("data"), list) else []


# --- reads ------------------------------------------------------------------

def health() -> dict:
    if not configured():
        return _mock({"connected": False})
    try:
        _req("/api/v1/keywords", {"keyword": "test", "limit": 1})
        return {"ok": True, "configured": True, "connected": True, "source": SOURCE}
    except EverBeeError as e:
        return {"ok": False, "configured": True, "connected": False,
                "error": e.message, "code": e.code, "source": SOURCE}


def keywords(term: str, limit: int = 25) -> dict:
    """Volume, competition and score for a search term.

    Volume is MODELLED, not measured — the schema carries ``cpc`` alongside
    ``vol``, which is the Google Keyword Planner field set, so it is at least
    partly derived from paid-search data rather than Etsy search logs. Calibrate
    against Etsy Marketplace Insights before trusting a number.
    """
    if not configured():
        return _mock({"keywords": [], "term": term})
    try:
        data = _req("/api/v1/keywords", {"keyword": term, "limit": max(1, min(int(limit), 100))})
        out = []
        for r in _rows(data, "keywords", "results"):
            if not isinstance(r, dict):
                continue
            out.append({
                "keyword": guard.inert(r.get("keyword") or "", "keyword"),
                "volume": guard.stamp(r.get("vol"), SOURCE, window="last 30d",
                                      confidence="modelled estimate — calibrate vs Etsy Marketplace Insights"),
                "newVolume": guard.stamp(r.get("new_volume"), SOURCE, window="last 30d",
                                         confidence="modelled estimate"),
                "competition": guard.stamp(r.get("competition"), SOURCE, window="current",
                                           confidence="vendor score"),
                "score": r.get("score"),
                "cpc": r.get("cpc"),
            })
        return {"ok": True, "configured": True, "source": SOURCE, "term": term,
                "keywords": out, "count": len(out), "flagged": guard.flagged_fields(out)}
    except EverBeeError as e:
        return {"ok": False, "configured": True, "source": SOURCE,
                "error": e.message, "code": e.code, "keywords": []}


def listings(term: str, limit: int = 25) -> dict:
    """Listings matching a term, with the demand estimates.

    ``est_mo_sales`` may come back null on a lower plan tier — EverBee filters
    fields by subscription. Null lands as Unknown, which is correct either way.
    """
    if not configured():
        return _mock({"listings": [], "term": term})
    try:
        data = _req("/api/v1/listings", {"search": term, "limit": max(1, min(int(limit), 100)),
                                         "time_range": "last_30_days"})
        out = []
        for r in _rows(data, "listings", "results"):
            if not isinstance(r, dict):
                continue
            out.append({
                "id": r.get("listing_id") or r.get("id"),
                "title": guard.inert(r.get("title") or "", "listing_title"),
                "shop": guard.inert(r.get("shop_name") or r.get("shop") or "", "shop_name"),
                "price": r.get("price"),
                "monthlySales": guard.stamp(
                    r.get("est_mo_sales"), SOURCE, window="last 30d",
                    confidence="MODELLED — Etsy never exposes per-listing sales; ±wide on low-volume listings"),
                "monthlyRevenue": guard.stamp(
                    r.get("est_mo_revenue"), SOURCE, window="last 30d",
                    confidence="MODELLED — derived from est_mo_sales × price"),
                "totalSales": guard.stamp(
                    r.get("est_total_sales"), SOURCE, window="lifetime",
                    confidence="modelled; shop lifetime counter is real, per-listing split is not"),
                "views": r.get("views"),
                "favorites": r.get("num_favorers"),
                "conversionRate": r.get("conversion_rate"),
                "ageMonths": r.get("listing_age_in_months"),
                "tags": guard.inert_deep(r.get("tags") or [], "tags"),
            })
        return {"ok": True, "configured": True, "source": SOURCE, "term": term,
                "listings": out, "count": len(out), "flagged": guard.flagged_fields(out)}
    except EverBeeError as e:
        return {"ok": False, "configured": True, "source": SOURCE,
                "error": e.message, "code": e.code, "listings": []}


def shop(name: str) -> dict:
    if not configured():
        return _mock({"shop": None, "name": name})
    try:
        data = _req(f"/api/v1/shops/{urllib.parse.quote(str(name))}")
        row = data.get("data") or data.get("shop") or data
        if not isinstance(row, dict):
            row = {}
        return {"ok": True, "configured": True, "source": SOURCE, "name": name,
                "monthlySales": guard.stamp(row.get("est_mo_sales"), SOURCE,
                                            window="last 30d", confidence="modelled estimate"),
                "monthlyRevenue": guard.stamp(row.get("est_mo_revenue"), SOURCE,
                                              window="last 30d", confidence="modelled estimate"),
                "totalSales": guard.stamp(row.get("total_sales"), SOURCE, window="lifetime",
                                          confidence="Etsy's public shop counter — real"),
                "listings": row.get("listing_count") or row.get("listings")}
    except EverBeeError as e:
        return {"ok": False, "configured": True, "source": SOURCE,
                "error": e.message, "code": e.code, "shop": None}


def evidence(term: str) -> dict:
    """One call the Etsy packet leans on: keywords + listings + a demand read."""
    if not configured():
        return _mock({"keywords": [], "listings": []})
    kw = keywords(term, limit=25)
    li = listings(term, limit=25)
    vols = [k["volume"]["value"] for k in (kw.get("keywords") or [])
            if k["volume"]["value"] is not None]
    sellers = [l for l in (li.get("listings") or [])
               if (l["monthlySales"]["value"] or 0) > 0]
    return {
        "ok": True, "configured": True, "source": SOURCE, "term": term,
        "keywords": kw.get("keywords") or [],
        "listings": li.get("listings") or [],
        "topVolume": guard.stamp(max(vols) if vols else None, SOURCE, window="last 30d",
                                 confidence="modelled estimate"),
        "sellingListings": guard.stamp(len(sellers) if li.get("listings") else None,
                                       SOURCE, window="last 30d", confidence="derived from modelled sales"),
        "competingListings": guard.stamp(li.get("count") if li.get("ok") else None,
                                         SOURCE, window="current", confidence="matched result count"),
        "flagged": (kw.get("flagged") or []) + (li.get("flagged") or []),
    }
