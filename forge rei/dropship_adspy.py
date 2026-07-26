#!/usr/bin/env python3
"""dropship_adspy.py — competitor-ad watcher for FORGE Dropship (stdlib).

The missing half of Product Watch. ``dropship_pipiads`` answers "what product is
trending"; THIS answers "what ad is actually running, and for how long". Longevity is
the proxy for profitability — a store does not pay to keep an ad live for 60 days
unless it converts. So ``daysRunning`` is the signal, and ``winners()`` is the filter.

Source: the Meta (Facebook/Instagram) Ad Library, pulled through the Apify platform
REST API — the library has no usable public API, and Apify's actor is the maintained
scraper in front of it.

Config in ``forge-dropship/config/dropship.env``:
  APIFY_TOKEN             — required. Blank → ``configured() == False``, every call
                            returns a clean "add key" mock, ZERO spend.
  DROPSHIP_ADSPY_ACTOR    — actor id, default ``curious_coder~facebook-ads-library-scraper``
                            (Apify writes ``/`` as ``~`` inside a URL path).
  DROPSHIP_ADSPY_MAX_ADS  — HARD cap on ads pulled per call, default 50.
  DROPSHIP_ADSPY_COUNTRY  — default ``US``.

COST — read this before touching the knobs. The actor bills PER AD SCRAPED
(~$0.00075/ad at time of writing) on top of Apify compute. Every call is clamped to
``DROPSHIP_ADSPY_MAX_ADS`` in ``_clamp`` — the clamp is the spend ceiling, not a
suggestion — and the requested count is echoed back in the response so an oversized
pull is visible. Only idempotent GET requests retry once. Paid POST actor runs never
retry: an actor run that got far enough to bill and then timed out would be billed
AGAIN on retry. The read timeout is correspondingly long (a run takes 30-120s).

Read-only. This module never launches, edits, orders, or spends ad budget (rule 2).
Shape mirrors ``dropship_pipiads`` / ``dropship_autods``: urllib only, honest errors,
never a fabricated row.
"""
from __future__ import annotations

import datetime
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import dropship_env

# Long read timeout: an Apify actor run is 30-120s, not a normal API call.
_TIMEOUT = 180
# One GET retry; paid POST actor runs must not be paid twice.
_RETRIES = 1
_API = "https://api.apify.com/v2"


class ApifyError(Exception):
    def __init__(self, status: int, message: str, code: str = "apify_error"):
        super().__init__(message)
        self.status = int(status)
        self.message = message
        self.code = code


def _token() -> str:
    return dropship_env.get("APIFY_TOKEN", "").strip()


def _actor() -> str:
    return (dropship_env.get("DROPSHIP_ADSPY_ACTOR", "").strip()
            or "curious_coder~facebook-ads-library-scraper")


def _country() -> str:
    return (dropship_env.get("DROPSHIP_ADSPY_COUNTRY", "").strip() or "US").upper()


def _max_ads() -> int:
    try:
        return max(1, int(dropship_env.get("DROPSHIP_ADSPY_MAX_ADS", "50") or 50))
    except Exception:
        return 50


def _clamp(limit) -> int:
    """The spend ceiling. Every path into a paid run goes through here."""
    cap = _max_ads()
    try:
        n = int(limit)
    except Exception:
        n = cap
    return 0 if n == 0 else max(1, min(n if n > 0 else cap, cap))


def configured() -> bool:
    return bool(_token())


def _req(method: str, url: str, payload: dict | None = None):
    token = _token()
    if not token:
        raise ApifyError(503, "Apify is not configured", "not_configured")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}",  # header, not ?token= — never in a URL
               "Content-Type": "application/json", "Accept": "application/json"}
    last_error: Exception | None = None
    retries = _RETRIES if method.upper() == "GET" else 0
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw.strip() else []
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5)
                last_error = error
                continue
            detail = "Apify request failed"
            try:
                payload_err = json.loads(error.read().decode("utf-8"))
                err = payload_err.get("error") or {}
                detail = (err.get("message") if isinstance(err, dict) else None) \
                    or payload_err.get("message") or detail
            except Exception:
                pass
            raise ApifyError(error.code, str(detail), "apify_http_error") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(1.5)
                continue
            raise ApifyError(502, "Apify is temporarily unavailable", "upstream_unavailable") from None
    raise ApifyError(502, "Apify is temporarily unavailable", "upstream_unavailable") from last_error


def _mock(extra: dict | None = None) -> dict:
    out = {"ok": True, "configured": False, "source": "apify:meta-ad-library", "ads": [],
           "detail": "Add APIFY_TOKEN to dropship.env (apify.com → Settings → Integrations). "
                     "$0 until then."}
    if extra:
        out.update(extra)
    return out


def _run(urls: list, limit: int, active_only: bool, country: str) -> list:
    """One paid actor run. run-sync-get-dataset-items returns the items directly, so
    there is no run-polling loop to babysit. ``maxItems`` + ``limit`` on the query and
    ``count``/``limitPerSource`` in the input are the same ceiling stated three ways —
    whichever one the actor honours, the pull stays capped."""
    path = urllib.parse.quote(_actor(), safe="~")
    url = f"{_API}/acts/{path}/run-sync-get-dataset-items?" + urllib.parse.urlencode(
        {"maxItems": limit, "limit": limit})
    body = {
        "urls": [{"url": u, "method": "GET"} for u in urls],
        "scrapeAdDetails": True,
        "limitPerSource": limit,
        "count": limit,
        "scrapePageAds.activeStatus": "active" if active_only else "all",
        "scrapePageAds.countryCode": country,
        "proxy": {"useApifyProxy": True},
    }
    rows = _req("POST", url, body)
    if isinstance(rows, dict):  # some actors wrap; unwrap defensively
        rows = rows.get("items") or rows.get("data") or []
    return rows if isinstance(rows, list) else []


def _pick(row: dict, *paths):
    """First non-empty value across several plausible keys. Dotted paths walk nested
    dicts (the actor buries most creative fields under ``snapshot``). Missing → None,
    never a guess."""
    for p in paths:
        cur = row
        for part in p.split("."):
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(part)
        if cur not in (None, "", [], {}):
            return cur
    return None


def _days_running(start) -> int | None:
    """Days since the ad first ran. THE signal — a 60-day-old ad is a proven ad.
    Accepts a unix epoch (int/float/numeric string) or an ISO-ish date string."""
    if start in (None, "", 0):
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    dt = None
    try:
        if isinstance(start, (int, float)) or (isinstance(start, str) and start.strip().isdigit()):
            dt = datetime.datetime.fromtimestamp(float(start), datetime.timezone.utc)
        elif isinstance(start, str):
            s = start.strip().replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None
    if dt is None:
        return None
    return max(0, (now - dt).days)


def _media(row: dict):
    """(mediaType, mediaUrl) from whichever creative array the actor filled in."""
    videos = _pick(row, "snapshot.videos", "videos")
    if isinstance(videos, list) and videos and isinstance(videos[0], dict):
        return "video", _pick(videos[0], "video_hd_url", "video_sd_url",
                              "video_preview_image_url")
    images = _pick(row, "snapshot.images", "images")
    if isinstance(images, list) and images and isinstance(images[0], dict):
        return "image", _pick(images[0], "original_image_url", "resized_image_url")
    return None, None


def _normalize(raw_ad) -> dict:
    """Map one raw actor row onto the small stable shape the rest of the system uses.
    The actor's raw keys drift between runs/versions, so every field probes several
    plausible names and falls back to None — a missing field is NEVER invented."""
    row = raw_ad if isinstance(raw_ad, dict) else {}
    ad_id = _pick(row, "adArchiveID", "ad_archive_id", "adid", "archiveID", "id")
    start = _pick(row, "startDate", "start_date", "ad_delivery_start_time",
                  "snapshot.creation_time")
    media_type, media_url = _media(row)
    snapshot_url = _pick(row, "url", "adSnapshotUrl", "ad_snapshot_url",
                         "snapshot.ad_snapshot_url")
    if not snapshot_url and ad_id:
        # Derived from a real id, not invented — this is the canonical permalink shape.
        snapshot_url = f"https://www.facebook.com/ads/library/?id={ad_id}"
    platforms = _pick(row, "publisherPlatform", "publisher_platform", "platforms")
    if isinstance(platforms, str):
        platforms = [platforms]
    return {
        "id": str(ad_id) if ad_id is not None else None,
        "pageName": _pick(row, "pageName", "page_name", "snapshot.page_name"),
        "pageId": (lambda v: str(v) if v is not None else None)(
            _pick(row, "pageID", "page_id", "snapshot.page_id")),
        "startDate": start,
        "daysRunning": _days_running(start),
        "body": _pick(row, "snapshot.body.text", "snapshot.body.markup.__html",
                      "body", "adText", "snapshot.caption"),
        "title": _pick(row, "snapshot.title", "title", "headline",
                       "snapshot.link_description"),
        "cta": _pick(row, "snapshot.cta_text", "cta_text", "ctaText", "snapshot.cta_type"),
        "linkUrl": _pick(row, "snapshot.link_url", "link_url", "linkUrl"),
        "mediaType": media_type,
        "mediaUrl": media_url,
        "platforms": platforms if isinstance(platforms, list) else None,
        "snapshotUrl": snapshot_url,
    }


def winners(ads, *, min_days: int = 21) -> list:
    """The "find winning ads" primitive: only ads still running after ``min_days``,
    longest-running first. A store does not keep paying for an ad that loses money.
    Pure — no I/O, no spend."""
    rows = [a for a in (ads or []) if isinstance(a, dict)
            and isinstance(a.get("daysRunning"), int) and a["daysRunning"] >= min_days]
    return sorted(rows, key=lambda a: a["daysRunning"], reverse=True)


def health() -> dict:
    """Presence, then a FREE token probe (/users/me). Deliberately never fires the
    actor — a health check must not bill an ad-scrape run. Never leaks the token."""
    if not configured():
        return _mock({"connected": False})
    try:
        _req("GET", f"{_API}/users/me")
        return {"ok": True, "configured": True, "connected": True,
                "source": "apify:meta-ad-library", "actor": _actor(),
                "maxAds": _max_ads(), "country": _country()}
    except ApifyError as e:
        return {"ok": False, "configured": True, "connected": False,
                "source": "apify:meta-ad-library", "error": e.message}


def _result(keyword: str, rows: list, limit: int) -> dict:
    ads = [_normalize(r) for r in rows]
    return {"ok": True, "configured": True, "source": "apify:meta-ad-library",
            "keyword": keyword, "ads": ads, "count": len(ads), "requested": limit}


def search(keyword, *, country=None, limit=None, active_only: bool = True) -> dict:
    """Keyword search of the Meta Ad Library — what ads are running for this product."""
    kw = (keyword or "").strip()
    if not kw:
        return {"ok": False, "configured": configured(), "source": "apify:meta-ad-library",
                "error": "keyword required", "ads": [], "count": 0}
    n = _clamp(limit)
    if not n:
        return {"ok": False, "configured": configured(), "source": "apify:meta-ad-library",
                "keyword": kw, "error": "limit must be at least 1", "code": "bad_request",
                "ads": [], "count": 0, "requested": 0}
    if not configured():
        return _mock({"keyword": kw, "count": 0})
    cc = (country or "").strip().upper() or _country()
    url = "https://www.facebook.com/ads/library/?" + urllib.parse.urlencode({
        "active_status": "active" if active_only else "all", "ad_type": "all",
        "country": cc, "q": kw, "search_type": "keyword_unordered"})
    try:
        return _result(kw, _run([url], n, active_only, cc), n)
    except ApifyError as e:
        return {"ok": False, "configured": True, "source": "apify:meta-ad-library",
                "keyword": kw, "error": e.message, "ads": [], "count": 0}


def advertiser(page_url_or_id, *, limit=None) -> dict:
    """Every ad one competitor page is running. Takes an Ad Library / Facebook page URL
    or a bare numeric page id."""
    ref = str(page_url_or_id or "").strip()
    if not ref:
        return {"ok": False, "configured": configured(), "source": "apify:meta-ad-library",
                "error": "page required", "ads": [], "count": 0}
    n = _clamp(limit)
    if not n:
        return {"ok": False, "configured": configured(), "source": "apify:meta-ad-library",
                "keyword": ref, "error": "limit must be at least 1", "code": "bad_request",
                "ads": [], "count": 0, "requested": 0}
    if not configured():
        return _mock({"keyword": ref, "count": 0})
    cc = _country()
    url = ref if ref.startswith("http") else (
        "https://www.facebook.com/ads/library/?" + urllib.parse.urlencode({
            "active_status": "active", "ad_type": "all", "country": cc,
            "view_all_page_id": ref, "search_type": "page"}))
    try:
        return _result(ref, _run([url], n, True, cc), n)
    except ApifyError as e:
        return {"ok": False, "configured": True, "source": "apify:meta-ad-library",
                "keyword": ref, "error": e.message, "ads": [], "count": 0}


if __name__ == "__main__":  # self-check — no network, no key, no spend
    _orig_get = dropship_env.get
    dropship_env.get = lambda k, d="": ("" if k == "APIFY_TOKEN" else _orig_get(k, d))
    try:
        assert configured() is False, "unkeyed must read as not configured"
        assert search("dog brush")["configured"] is False
        assert search("dog brush")["ads"] == []
        assert advertiser("123")["ads"] == []
        assert search("")["ok"] is False, "empty keyword must not reach a paid run"
        assert _clamp(0) == 0, "zero must not become a paid maximum pull"
        assert search("dog brush", limit=0)["code"] == "bad_request"
        assert advertiser("123", limit=0)["code"] == "bad_request"

        empty = _normalize({})
        keys = {"id", "pageName", "pageId", "startDate", "daysRunning", "body", "title",
                "cta", "linkUrl", "mediaType", "mediaUrl", "platforms", "snapshotUrl"}
        assert set(empty) == keys, set(empty) ^ keys
        assert all(v is None for v in empty.values()), empty
        assert _normalize("not a dict")["id"] is None
        assert _normalize(None)["daysRunning"] is None

        then = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=45)
        assert _normalize({"startDate": then.isoformat()})["daysRunning"] == 45
        assert _normalize({"start_date": int(then.timestamp())})["daysRunning"] == 45
        offset_then = (datetime.datetime.now(datetime.timezone.utc)
                       - datetime.timedelta(days=45, hours=20)).astimezone(
                           datetime.timezone(-datetime.timedelta(hours=7)))
        assert _days_running(offset_then.isoformat()) == 45
        assert _normalize({"startDate": "not-a-date"})["daysRunning"] is None
        n = _normalize({"adArchiveID": 9, "snapshot": {"page_name": "Acme",
                        "body": {"text": "buy"}, "cta_text": "Shop Now",
                        "videos": [{"video_hd_url": "v.mp4"}]}})
        assert (n["id"], n["pageName"], n["body"], n["cta"]) == ("9", "Acme", "buy", "Shop Now")
        assert (n["mediaType"], n["mediaUrl"]) == ("video", "v.mp4")
        assert n["snapshotUrl"].endswith("?id=9")

        w = winners([{"daysRunning": 5}, {"daysRunning": 60}, {"daysRunning": 21},
                     {"daysRunning": None}, "junk"])
        assert [a["daysRunning"] for a in w] == [60, 21], w
        assert winners([], min_days=1) == [] and winners(None) == []

        assert _clamp(9999) == _max_ads(), "oversized pull must clamp to the cap"
        assert _clamp("x") == _max_ads()
        assert _clamp(3) == 3
    finally:
        dropship_env.get = _orig_get
    print("dropship_adspy self-check OK — cap", _max_ads(), "ads/call, actor", _actor())
