"""Read-only GetHookd ad intelligence for Midas product research.

GetHookd supplies the market signal: active Shopify ads with their age, use count,
and performance score.  It never supplies a supplier cost, so this module never
calls a product profitable.  AutoDS must ground that later decision.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import dropship_env
import research_guard as guard

SOURCE = "GetHookd"
_BASE = "https://app.gethookd.ai/api/v1"
_TIMEOUT = 20


class GetHookdError(Exception):
    def __init__(self, status: int, message: str, code: str = "gethookd_error"):
        super().__init__(message)
        self.status, self.message, self.code = int(status), message, code


def _key() -> str:
    return dropship_env.get("GETHOOKED_API_KEY", "").strip()


def configured() -> bool:
    return bool(_key())


def _mock(extra: dict | None = None) -> dict:
    out = {"ok": True, "configured": False, "connected": False, "source": SOURCE,
           "detail": "Add GETHOOKED_API_KEY to dropship.env."}
    if extra:
        out.update(extra)
    return out


def _request(path: str, params: dict | None = None) -> dict:
    key = _key()
    if not key:
        raise GetHookdError(503, "GetHookd is not configured", "not_configured")
    url = _BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items()
                                                if v not in (None, "")})
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}", "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            raw = response.read()
            payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except urllib.error.HTTPError as error:
        message = "GetHookd request failed"
        try:
            payload = json.loads(error.read().decode("utf-8", "replace"))
            message = str(payload.get("message") or message)
        except Exception:
            pass
        code = "credits_exhausted" if error.code == 402 else (
            "rate_limited" if error.code == 429 else "gethookd_http_error")
        raise GetHookdError(error.code, message, code) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        raise GetHookdError(502, "GetHookd is temporarily unavailable", "unavailable") from error
    if isinstance(payload, dict) and payload.get("errors"):
        raise GetHookdError(502, str(payload.get("message") or "GetHookd request failed"),
                             "gethookd_error")
    return payload if isinstance(payload, dict) else {}


def health() -> dict:
    """Free authentication probe.  It returns scopes, never the token or workspace."""
    if not configured():
        return _mock()
    try:
        data = _request("/authcheck").get("data") or {}
        scopes = data.get("scopes") or []
        return {"ok": bool(data.get("authenticated")), "configured": True,
                "connected": bool(data.get("authenticated")), "source": SOURCE,
                "scopes": [str(scope) for scope in scopes]}
    except GetHookdError as error:
        return {"ok": False, "configured": True, "connected": False, "source": SOURCE,
                "error": error.message, "code": error.code}


def _ad(row: dict) -> dict:
    brand = row.get("brand") if isinstance(row.get("brand"), dict) else {}
    return {
        "id": row.get("id"),
        "advertiser": guard.inert(brand.get("name") or "", "brand_name"),
        "headline": guard.inert(row.get("title") or "", "ad_title"),
        "copy": guard.inert(row.get("body") or "", "ad_copy"),
        "format": row.get("display_format") or "",
        "platform": row.get("platform") or "",
        "landingPage": row.get("landing_page") or "",
        "shareUrl": row.get("share_url") or "",
        "startDate": row.get("start_date"),
        "daysRunning": guard.stamp(row.get("days_active"), SOURCE,
                                    window="GetHookd active-ad history",
                                    confidence="vendor-reported ad age"),
        "usedCount": guard.stamp(row.get("used_count"), SOURCE,
                                  window="GetHookd creative reuse count",
                                  confidence="vendor-reported"),
        "performanceScore": guard.stamp(row.get("performance_score"), SOURCE,
                                          window="GetHookd score",
                                          confidence="vendor-proprietary score"),
        "performanceTier": row.get("performance_score_title") or "",
        "activeAds": brand.get("active_ads"),
    }


def search_ads(query: str = "", per_page: int = 30, **filters) -> dict:
    """Search active, long-running Shopify ads; credit use is returned transparently."""
    if not configured():
        return _mock({"ads": [], "query": query})
    params = {
        "query": (query or "").strip(), "page": 1,
        "per_page": max(1, min(int(per_page), 100)),
        "status": "active", "platform": "facebook,instagram", "technologies": "shopify",
        "performance_scores": "winning,optimized", "run-time": 21,
        "sort_column": "days_active", "sort_direction": "desc", "ads_per_brand_limit": 1,
        **filters,
    }
    try:
        payload = _request("/explore", params)
        rows = [_ad(row) for row in (payload.get("data") or []) if isinstance(row, dict)]
        return {"ok": True, "configured": True, "connected": True, "source": SOURCE,
                "query": query, "ads": rows, "count": len(rows),
                "usedCredits": payload.get("used_credits"),
                "remainingCredits": payload.get("remaining_credits"),
                "flagged": guard.flagged_fields(rows)}
    except GetHookdError as error:
        return {"ok": False, "configured": True, "connected": False, "source": SOURCE,
                "query": query, "ads": [], "error": error.message, "code": error.code}


def evidence(query: str, per_page: int = 30) -> dict:
    """Packet-ready GetHookd evidence.  Ads are the demand proof, not cost proof."""
    result = search_ads(query, per_page=per_page)
    rows = result.get("ads") or []
    running = [row["daysRunning"]["value"] for row in rows
               if row.get("daysRunning", {}).get("value") is not None]
    advertisers = {row.get("advertiser", {}).get("text") for row in rows
                   if row.get("advertiser", {}).get("text")}
    return {**result,
            "longestRunningDays": guard.stamp(max(running) if running else None, SOURCE,
                                               window="matched active Shopify ads",
                                               confidence="derived from GetHookd ad age"),
            "advertiserCount": guard.stamp(len(advertisers) if rows else None, SOURCE,
                                             window="matched active Shopify ads",
                                             confidence="derived"),
            "fetchedAt": int(time.time() * 1000)}
