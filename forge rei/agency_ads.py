"""agency_ads.py — Meta Ads analytics (Forge AI Agency).

Credential-guard pattern: if META_ACCESS_TOKEN is present in env, live Meta
Graph API calls are made. If absent or if live fetch fails, deterministic mock
data is returned (identical output shape — the UI never errors).

M3: create_ad(spec, paused=True) creates a Meta campaign/adset/ad in PAUSED
state when token is present; returns {ok, detail, url?} without throwing.

Keys read from os.environ (injected from agency.env by connector.py M0):
  META_ACCESS_TOKEN    — long-lived system-user token (ads_read + ads_management)
  META_AD_ACCOUNT_MAP  — JSON {"clientId": "act_123", ...}

No persistence — pure read model.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# --- MOCK ad accounts, one per demo client ----------------------------------
_ACCOUNTS = [
    {"id": "act_1001", "name": "Bloom Dental — Meta", "clientId": "demo-bloom",
     "clientName": "Bloom Dental"},
    {"id": "act_1002", "name": "Peak Fitness — Meta", "clientId": "demo-peak",
     "clientName": "Peak Fitness"},
]

# Per-account mock campaign + ad sets. Numbers are hand-tuned, not random, so
# CTR/CPC/CPL/ROAS are internally consistent and stable.
_DATA = {
    "act_1001": {
        "campaigns": [
            {"id": "c_b1", "name": "New Patient — Search Intent", "objective": "Leads",
             "status": "active", "spend": 1840, "impressions": 96000, "reach": 41000,
             "clicks": 1730, "leads": 88, "conversions": 41, "revenue": 12300},
            {"id": "c_b2", "name": "Whitening Promo — Retarget", "objective": "Conversions",
             "status": "active", "spend": 920, "impressions": 52000, "reach": 18000,
             "clicks": 640, "leads": 23, "conversions": 14, "revenue": 4200},
            {"id": "c_b3", "name": "Brand Awareness — Broad", "objective": "Awareness",
             "status": "active", "spend": 610, "impressions": 140000, "reach": 88000,
             "clicks": 410, "leads": 6, "conversions": 1, "revenue": 300},
        ],
        "ads": [
            {"id": "ad_b1", "name": "Family smiling — 'Gentle care'", "campaign": "New Patient",
             "spend": 760, "impressions": 38000, "clicks": 910, "leads": 51,
             "conversions": 26, "revenue": 7800, "hook": "Gentle dentistry for the whole family"},
            {"id": "ad_b2", "name": "Before/After whitening", "campaign": "Whitening Promo",
             "spend": 520, "impressions": 24000, "clicks": 430, "leads": 19,
             "conversions": 12, "revenue": 3600, "hook": "Brighter smile in one visit"},
            {"id": "ad_b3", "name": "Stock office photo", "campaign": "Brand Awareness",
             "spend": 610, "impressions": 140000, "clicks": 410, "leads": 6,
             "conversions": 1, "revenue": 300, "hook": "Your local dentist"},
            {"id": "ad_b4", "name": "Long text testimonial", "campaign": "New Patient",
             "spend": 290, "impressions": 19000, "clicks": 120, "leads": 4,
             "conversions": 1, "revenue": 300, "hook": "Read what our patients say"},
        ],
    },
    "act_1002": {
        "campaigns": [
            {"id": "c_p1", "name": "Free Trial — UGC", "objective": "Leads",
             "status": "active", "spend": 2200, "impressions": 110000, "reach": 60000,
             "clicks": 2480, "leads": 140, "conversions": 62, "revenue": 9300},
            {"id": "c_p2", "name": "Transformation Stories", "objective": "Conversions",
             "status": "active", "spend": 1300, "impressions": 70000, "reach": 33000,
             "clicks": 990, "leads": 51, "conversions": 28, "revenue": 5600},
            {"id": "c_p3", "name": "Generic Gym Promo", "objective": "Traffic",
             "status": "active", "spend": 740, "impressions": 60000, "reach": 40000,
             "clicks": 300, "leads": 5, "conversions": 1, "revenue": 150},
        ],
        "ads": [
            {"id": "ad_p1", "name": "Member transformation reel", "campaign": "Transformation",
             "spend": 880, "impressions": 41000, "clicks": 1200, "leads": 78,
             "conversions": 34, "revenue": 5100, "hook": "She lost 30lbs in 12 weeks"},
            {"id": "ad_p2", "name": "Trainer talking-head UGC", "campaign": "Free Trial",
             "spend": 760, "impressions": 36000, "clicks": 940, "leads": 49,
             "conversions": 21, "revenue": 3150, "hook": "Your first week is on us"},
            {"id": "ad_p3", "name": "Generic dumbbell stock", "campaign": "Generic Gym Promo",
             "spend": 740, "impressions": 60000, "clicks": 300, "leads": 5,
             "conversions": 1, "revenue": 150, "hook": "Join our gym today"},
            {"id": "ad_p4", "name": "Price-only graphic", "campaign": "Free Trial",
             "spend": 420, "impressions": 28000, "clicks": 210, "leads": 7,
             "conversions": 2, "revenue": 300, "hook": "$19/mo membership"},
        ],
    },
}


_UA = "ForgeREI/1.0 (+https://github.com/forgelabs)"
_META_BASE = "https://graph.facebook.com/v19.0"
_RETRIES = 3


def _http_error_detail(e, limit=500):
    try:
        raw = e.read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        raw = ""
    detail = raw.strip()
    try:
        parsed = json.loads(detail)
        if isinstance(parsed, dict):
            err = parsed.get("error")
            if isinstance(err, dict):
                detail = err.get("message") or err.get("error_user_msg") or detail
            else:
                detail = parsed.get("message") or parsed.get("error_description") or detail
    except Exception:  # noqa: BLE001
        pass
    return str(detail or getattr(e, "reason", "") or "")[:limit]


def _meta_error(e):
    return f"Meta {e.code}: {_http_error_detail(e) or e.reason}"


def _meta_open_json(req, label):
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{label} failed: {_meta_error(e)}")


def _meta_req(token, endpoint, params=None):
    """urllib GET to Meta Graph API — mirrors GHLClient._req style."""
    p = dict(params or {})
    p["access_token"] = token
    url = f"{_META_BASE}{endpoint}?{urllib.parse.urlencode(p)}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA}, method="GET")
    for attempt in range(_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < _RETRIES:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise RuntimeError(_meta_error(e))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < _RETRIES:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise


def _round(v, n=2):
    return round(v, n)


def _metrics(row):
    """Derive CTR / CPC / CPL / ROAS from raw counters."""
    imp = max(1, row.get("impressions", 0))
    clk = max(0, row.get("clicks", 0))
    spend = row.get("spend", 0)
    leads = row.get("leads", 0)
    conv = row.get("conversions", 0)
    rev = row.get("revenue", 0)
    return {
        "spend": spend,
        "impressions": row.get("impressions", 0),
        "reach": row.get("reach", row.get("impressions", 0)),
        "clicks": clk,
        "leads": leads,
        "conversions": conv,
        "ctr": _round(clk / imp * 100, 2),
        "cpc": _round(spend / clk, 2) if clk else 0,
        "cpl": _round(spend / leads, 2) if leads else 0,
        "roas": _round(rev / spend, 2) if spend else 0,
        "revenue": rev,
    }


def _live_analytics(token, account_id, days):
    """Fetch real Meta Ads insights via Graph API GET /{ad_account}/insights."""
    fields = ("spend,impressions,reach,clicks,ctr,cpc,actions,"
              "action_values,campaign_name,objective")
    params = {
        "fields": fields,
        "date_preset": f"last_{days}_d",
        "level": "ad",
        "limit": 100,
    }
    data = _meta_req(token, f"/{account_id}/insights", params)
    rows = data.get("data", [])

    def _actions_val(row, action_type):
        for a in row.get("actions", []):
            if a.get("action_type") == action_type:
                return float(a.get("value", 0))
        return 0.0

    def _action_values_val(row, action_type):
        for a in row.get("action_values", []):
            if a.get("action_type") == action_type:
                return float(a.get("value", 0))
        return 0.0

    campaigns_map = {}
    ads_list = []
    tot = {"spend": 0.0, "impressions": 0, "reach": 0,
           "clicks": 0, "leads": 0, "conversions": 0, "revenue": 0.0}

    for row in rows:
        spend = float(row.get("spend", 0) or 0)
        impressions = int(row.get("impressions", 0) or 0)
        reach = int(row.get("reach", 0) or 0)
        clicks = int(row.get("clicks", 0) or 0)
        leads = int(_actions_val(row, "lead"))
        conversions = int(_actions_val(row, "purchase"))
        revenue = _action_values_val(row, "purchase")
        cname = row.get("campaign_name", "Unknown")
        cid = row.get("campaign_id", cname)

        if cid not in campaigns_map:
            campaigns_map[cid] = {"id": cid, "name": cname,
                                  "objective": row.get("objective", ""),
                                  "status": "active", "spend": 0.0,
                                  "impressions": 0, "reach": 0, "clicks": 0,
                                  "leads": 0, "conversions": 0, "revenue": 0.0}
        cm = campaigns_map[cid]
        cm["spend"] += spend
        cm["impressions"] += impressions
        cm["reach"] += reach
        cm["clicks"] += clicks
        cm["leads"] += leads
        cm["conversions"] += conversions
        cm["revenue"] += revenue

        ads_list.append({
            "id": row.get("ad_id", f"ad_{len(ads_list)}"),
            "name": row.get("ad_name", "(ad)"),
            "campaign": cname,
            "hook": "",
            "spend": spend, "impressions": impressions, "reach": reach,
            "clicks": clicks, "leads": leads, "conversions": conversions,
            "revenue": revenue,
        })
        for k in tot:
            if k == "spend" or k == "revenue":
                tot[k] += float(row.get(k, 0) or 0) if k == "spend" else revenue
            else:
                tot[k] += int(row.get(k if k != "leads" else "_", 0) or 0)

    # Rebuild totals cleanly from per-row accumulators
    tot = {"spend": 0.0, "impressions": 0, "reach": 0,
           "clicks": 0, "leads": 0, "conversions": 0, "revenue": 0.0}
    for a in ads_list:
        for k in tot:
            tot[k] += a[k]

    campaigns = [_metrics(c) | {"id": c["id"], "name": c["name"],
                                 "objective": c["objective"], "status": c["status"]}
                 for c in campaigns_map.values()]
    ads_out = [{"id": a["id"], "name": a["name"], "campaign": a["campaign"],
                "hook": a.get("hook", ""), **_metrics(a)} for a in ads_list]
    ranked = sorted(ads_out, key=lambda x: (x["roas"], x["leads"]), reverse=True)
    return {
        "account": {"id": account_id, "name": account_id, "clientName": ""},
        "days": days,
        "totals": _metrics(tot),
        "campaigns": campaigns,
        "topAds": ranked[:3],
        "weakAds": sorted(ads_out, key=lambda x: (x["roas"], x["leads"]))[:3],
        "connection": connection(),
        "source": "live",
    }


def _mock_analytics(account=None, client=None, days=7):
    """Deterministic mock analytics — existing body, renamed."""
    acct_id = account
    if not acct_id and client:
        match = next((a for a in _ACCOUNTS if a["clientId"] == client), None)
        acct_id = match["id"] if match else None
    if not acct_id:
        acct_id = _ACCOUNTS[0]["id"]

    acct = next((a for a in _ACCOUNTS if a["id"] == acct_id), _ACCOUNTS[0])
    raw = _DATA.get(acct_id, _DATA["act_1001"])

    campaigns = []
    tot = {"spend": 0, "impressions": 0, "reach": 0, "clicks": 0,
           "leads": 0, "conversions": 0, "revenue": 0}
    for c in raw["campaigns"]:
        m = _metrics(c)
        campaigns.append({"id": c["id"], "name": c["name"],
                          "objective": c["objective"], "status": c["status"], **m})
        for k in tot:
            tot[k] += c.get(k, 0)

    ads = [{"id": a["id"], "name": a["name"], "campaign": a["campaign"],
            "hook": a.get("hook", ""), **_metrics(a)} for a in raw["ads"]]
    ranked = sorted(ads, key=lambda a: (a["roas"], a["leads"]), reverse=True)
    top_ads = ranked[:3]
    weak_ads = sorted(ads, key=lambda a: (a["roas"], a["leads"]))[:3]

    totals = _metrics(tot)
    return {
        "account": {"id": acct["id"], "name": acct["name"],
                    "clientName": acct["clientName"]},
        "days": days,
        "totals": totals,
        "campaigns": campaigns,
        "topAds": top_ads,
        "weakAds": weak_ads,
        "connection": connection(),
        "source": "mock",
    }


def connection():
    """Connection state — connected=True when token present, source flag included."""
    token = os.environ.get("META_ACCESS_TOKEN", "")
    has_token = bool(token)
    return {
        "connected": has_token,
        "hasToken": has_token,
        "source": "live" if has_token else "mock",
        "todo": (None if has_token else
                 "Set META_ACCESS_TOKEN (env) + META_AD_ACCOUNT_MAP to go live."),
    }


def accounts():
    """Return ad accounts. Live: reads META_AD_ACCOUNT_MAP. Else: mock _ACCOUNTS."""
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if token:
        raw_map = os.environ.get("META_AD_ACCOUNT_MAP", "")
        if raw_map:
            try:
                acct_map = json.loads(raw_map)
                live_accounts = [
                    {"id": act_id, "name": f"{cid} — Meta",
                     "clientId": cid, "clientName": cid}
                    for cid, act_id in acct_map.items()
                ]
                return {"accounts": live_accounts, "connection": connection()}
            except (json.JSONDecodeError, AttributeError):
                pass
    return {"accounts": _ACCOUNTS, "connection": connection()}


def analytics(account=None, client=None, days=7):
    """Aggregate analytics. Live when META_ACCESS_TOKEN present; mock fallback."""
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if token:
        acct_id = account
        if not acct_id and client:
            raw_map = os.environ.get("META_AD_ACCOUNT_MAP", "")
            if raw_map:
                try:
                    acct_map = json.loads(raw_map)
                    acct_id = acct_map.get(client)
                except (json.JSONDecodeError, AttributeError):
                    pass
        if not acct_id:
            acct_id = account or _ACCOUNTS[0]["id"]
        try:
            return _live_analytics(token, acct_id, days)
        except Exception as e:
            import sys
            print(f"[ads] live fetch failed, falling back to mock: {e}", file=sys.stderr)
    return _mock_analytics(account=account, client=client, days=days)


def create_ad(spec, paused=True):
    """M3: Create a Meta campaign/adset/ad in PAUSED state. Never throws.

    spec: {name, objective, adset_name, targeting, creative, budget_daily,
           ad_account_id, page_id, instagram_actor_id?}
    Returns: {ok, detail, url?}
    """
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        return {"ok": False, "detail": "needs META_ACCESS_TOKEN"}
    try:
        return _live_create_ad(token, spec, paused)
    except Exception as e:
        import sys
        print(f"[ads] create_ad failed: {e}", file=sys.stderr)
        return {"ok": False, "detail": f"Meta API error: {e}"}


def _live_create_ad(token, spec, paused):
    """Create campaign → adset → ad via Meta Graph API POST calls."""
    acct = spec.get("ad_account_id", "")
    if not acct:
        return {"ok": False, "detail": "spec.ad_account_id required"}

    camp_status = "PAUSED" if paused else "ACTIVE"

    # 1. Create campaign
    camp_data = urllib.parse.urlencode({
        "name": spec.get("name", "New Campaign"),
        "objective": spec.get("objective", "OUTCOME_LEADS"),
        "status": camp_status,
        "special_ad_categories": "[]",
        "access_token": token,
    }).encode()
    camp_req = urllib.request.Request(
        f"{_META_BASE}/{acct}/campaigns",
        data=camp_data,
        headers={"User-Agent": _UA, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    camp_resp = _meta_open_json(camp_req, "Campaign creation")
    camp_id = camp_resp.get("id")
    if not camp_id:
        return {"ok": False, "detail": f"Campaign creation failed: {camp_resp}"}

    # 2. Create adset
    targeting = spec.get("targeting", {"age_min": 25, "age_max": 65})
    adset_data = urllib.parse.urlencode({
        "name": spec.get("adset_name", f"{spec.get('name', 'AdSet')} — Set 1"),
        "campaign_id": camp_id,
        "daily_budget": int(spec.get("budget_daily", 1000)),
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "LEAD_GENERATION",
        "targeting": json.dumps(targeting),
        "status": camp_status,
        "access_token": token,
    }).encode()
    adset_req = urllib.request.Request(
        f"{_META_BASE}/{acct}/adsets",
        data=adset_data,
        headers={"User-Agent": _UA, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    adset_resp = _meta_open_json(adset_req, "Adset creation")
    adset_id = adset_resp.get("id")
    if not adset_id:
        return {"ok": False, "detail": f"Adset creation failed: {adset_resp}"}

    # 3. Create ad creative + ad
    creative = spec.get("creative", {})
    creative_data = urllib.parse.urlencode({
        "name": f"{spec.get('name', 'Ad')} — Creative",
        "object_story_spec": json.dumps({
            "page_id": spec.get("page_id", ""),
            "link_data": {
                "message": creative.get("message", ""),
                "link": creative.get("link", ""),
                "name": creative.get("headline", ""),
                "description": creative.get("description", ""),
            },
        }),
        "access_token": token,
    }).encode()
    creative_req = urllib.request.Request(
        f"{_META_BASE}/{acct}/adcreatives",
        data=creative_data,
        headers={"User-Agent": _UA, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    creative_resp = _meta_open_json(creative_req, "Creative creation")
    creative_id = creative_resp.get("id")
    if not creative_id:
        return {"ok": False, "detail": f"Creative creation failed: {creative_resp}"}

    ad_data = urllib.parse.urlencode({
        "name": spec.get("name", "New Ad"),
        "adset_id": adset_id,
        "creative": json.dumps({"creative_id": creative_id}),
        "status": camp_status,
        "access_token": token,
    }).encode()
    ad_req = urllib.request.Request(
        f"{_META_BASE}/{acct}/ads",
        data=ad_data,
        headers={"User-Agent": _UA, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    ad_resp = _meta_open_json(ad_req, "Ad creation")
    ad_id = ad_resp.get("id")
    if not ad_id:
        return {"ok": False, "detail": f"Ad creation failed: {ad_resp}"}

    url = f"https://www.facebook.com/adsmanager/manage/campaigns?act={acct.replace('act_', '')}"
    return {
        "ok": True,
        "detail": f"Campaign '{spec.get('name')}' created PAUSED — un-pause in Meta Ads Manager.",
        "url": url,
        "campaignId": camp_id,
        "adsetId": adset_id,
        "adId": ad_id,
    }
