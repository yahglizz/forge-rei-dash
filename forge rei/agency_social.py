"""agency_social.py — Instagram + TikTok control for the Forge AI Agency,
backed by Metricool (brand 'forgelabsx').

Credential-guard pattern: if METRICOOL_USER_TOKEN is present, _live_analytics()
calls Metricool REST for follower/engagement data. Else _ANALYTICS (zeros with
a helpful note) is returned. Output shape is identical either way.

M3: publish(post) — when METRICOOL_USER_TOKEN is set, POST to Metricool REST to
schedule/publish the post. Else, flags post for operator MCP publish and returns
a clear receipt. Never throws.

TWO LAYERS:
  - COCKPIT + QUEUE (this module, runs 24/7 on the box): connected accounts,
    real best-time-to-post heatmaps (baked in), post queue, analytics.
  - EXECUTOR: REST (autonomous) when METRICOOL_USER_TOKEN is set; else operator
    via the Metricool MCP (works today via the Claude session).

Account: brand 'forgelabsx', blogId 6354174, userId 4895528, tz America/New_York.
"""
import forge_atomic
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import agency_approvals_io

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_social.json"
_LOCK = threading.Lock()

BRAND = "forgelabsx"
BLOG_ID = 6354174
USER_ID = 4895528
TIMEZONE = "America/New_York"
NETWORKS = ["instagram", "tiktok"]
POST_STATUSES = ["draft", "ready", "posted", "failed"]
DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}

# --- REAL best-time-to-post grids (Metricool, pulled 2026-06-07) -------------
# {network: {dayOfWeek(1=Mon..7=Sun): [24 hourly values, hour 0..23]}}
# Higher = better. Refresh via the MCP (operator) or REST (token) anytime.
_BEST_TIME = {
    "instagram": {
        1: [508, 283, 221, 203, 255, 427, 878, 1874, 3127, 4646, 5528, 5117, 4994, 3663, 3537, 3825, 3792, 3988, 4206, 3533, 2455, 1463, 901, 555],
        2: [466, 283, 165, 131, 177, 369, 773, 1591, 2765, 3835, 4942, 4642, 4656, 3326, 3324, 3589, 3532, 4140, 4788, 3984, 2916, 1704, 1018, 866],
        3: [1121, 474, 258, 177, 230, 433, 1142, 2125, 3781, 5201, 6506, 6063, 5774, 4327, 4263, 4104, 4357, 4541, 4869, 3992, 3024, 1799, 963, 706],
        4: [556, 384, 221, 174, 182, 412, 1082, 1996, 3269, 4737, 6275, 5713, 5730, 4438, 4261, 4563, 4515, 4697, 5078, 4124, 3156, 1834, 1034, 688],
        5: [576, 401, 226, 176, 247, 470, 1120, 1908, 3573, 5039, 6734, 5952, 5909, 4641, 4336, 4517, 4490, 4570, 4418, 3360, 2339, 1440, 864, 546],
        6: [525, 289, 174, 143, 144, 282, 511, 957, 1656, 2430, 3409, 2816, 2822, 2010, 1910, 2009, 2091, 1938, 2393, 2028, 1376, 1031, 617, 487],
        7: [385, 271, 161, 92, 175, 228, 403, 822, 1330, 1968, 2582, 2218, 2410, 1777, 1634, 1759, 1696, 1890, 2253, 2232, 1523, 1021, 597, 488],
    },
    "tiktok": {
        1: [125, 68, 67, 60, 66, 91, 193, 318, 508, 653, 1089, 741, 1050, 730, 689, 795, 906, 890, 1096, 804, 702, 503, 346, 255],
        2: [136, 91, 66, 53, 48, 73, 177, 327, 452, 646, 1136, 736, 1082, 707, 681, 771, 812, 883, 1119, 859, 767, 588, 379, 290],
        3: [158, 119, 85, 116, 106, 99, 237, 420, 772, 856, 1432, 985, 1359, 947, 940, 947, 1122, 1095, 1386, 1039, 907, 580, 370, 279],
        4: [188, 126, 88, 85, 78, 118, 239, 425, 630, 803, 1471, 978, 1299, 941, 887, 947, 1118, 1097, 1378, 999, 838, 643, 439, 280],
        5: [175, 113, 101, 85, 79, 81, 226, 444, 684, 890, 1379, 899, 1251, 876, 854, 978, 1079, 1044, 1222, 891, 689, 474, 328, 294],
        6: [170, 105, 76, 51, 49, 69, 145, 257, 396, 517, 852, 566, 815, 564, 560, 552, 620, 531, 709, 573, 523, 347, 275, 185],
        7: [130, 87, 69, 61, 35, 53, 129, 228, 337, 506, 816, 493, 720, 487, 493, 492, 595, 524, 677, 632, 579, 402, 283, 161],
    },
}

# --- mock analytics (swap for real via MCP/REST) ----------------------------
_ANALYTICS = {
    "instagram": {"followers": 0, "posts": 0, "engagement": 0.0,
                  "reach": 0, "note": "Connect a Metricool API token (or ask the "
                  "operator to pull live IG analytics via MCP) for real numbers."},
    "tiktok": {"followers": 0, "posts": 0, "engagement": 0.0, "views": 0,
               "note": "Connect a Metricool API token (or ask the operator to pull "
               "live TikTok analytics via MCP) for real numbers."},
}


_UA = "ForgeREI/1.0 (+https://github.com/forgelabs)"
_METRICOOL_BASE = "https://app.metricool.com/api"


def _http_error_detail(e, limit=500):
    try:
        raw = e.read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        raw = ""
    detail = raw.strip()
    try:
        parsed = json.loads(detail)
        if isinstance(parsed, dict):
            detail = (parsed.get("message") or parsed.get("error_description")
                      or parsed.get("error") or parsed.get("detail") or detail)
            if isinstance(detail, (dict, list)):
                detail = json.dumps(detail)
    except Exception:  # noqa: BLE001
        pass
    return str(detail or getattr(e, "reason", "") or "")[:limit]


def _metricool_req(token, method, endpoint, body=None, params=None):
    """urllib request to Metricool REST API — mirrors GHLClient._req style."""
    url = f"{_METRICOOL_BASE}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": _UA,
    }
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    retries = 3
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise RuntimeError(f"Metricool {e.code}: {_http_error_detail(e)}")
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise


def _live_analytics(token, network):
    """Fetch real analytics from Metricool REST for one network."""
    # Metricool v1: GET /blog/{blogId}/analytics/{network}
    try:
        data = _metricool_req(token, "GET",
                              f"/blog/{BLOG_ID}/analytics/{network}",
                              params={"user_token": token})
        if not data or not isinstance(data, dict):
            return None
        return {
            "followers": int(data.get("followers") or data.get("totalFollowers") or 0),
            "posts": int(data.get("posts") or data.get("totalPosts") or 0),
            "engagement": float(data.get("engagement") or data.get("engagementRate") or 0.0),
            "reach": int(data.get("reach") or data.get("totalReach") or 0),
            "views": int(data.get("views") or data.get("totalViews") or 0),
        }
    except Exception:
        return None


def _norm_net(n):
    n = (n or "instagram").lower()
    return n if n in NETWORKS else "instagram"


def connection():
    """Connection state — autonomous=True when METRICOOL_USER_TOKEN present."""
    token = bool(os.environ.get("METRICOOL_USER_TOKEN"))
    return {
        "connected": True,                 # accounts ARE linked in Metricool
        "brand": BRAND, "blogId": BLOG_ID, "userId": USER_ID, "timezone": TIMEZONE,
        "networks": NETWORKS,
        "autonomous": token,               # True = box can publish via REST itself
        "executor": "rest" if token else "mcp",
        "source": "live" if token else "mock",
        "note": ("Autonomous posting enabled via Metricool REST API."
                 if token else
                 "Cockpit live. Posting is operator-driven via the Metricool MCP. "
                 "Add METRICOOL_USER_TOKEN to forge-agency/config/agency.env for "
                 "autonomous box posting."),
    }


def best_time(network=None):
    net = _norm_net(network)
    grid = _BEST_TIME[net]
    # rows Mon..Sun, each 24 hourly values
    rows = [{"day": DAY_NAMES[d], "dow": d, "hours": grid[d]} for d in range(1, 8)]
    mx = max(max(v) for v in grid.values()) or 1
    # top 3 (day, hour) slots
    slots = []
    for d in range(1, 8):
        for h in range(24):
            slots.append({"day": DAY_NAMES[d], "hour": h, "value": grid[d][h]})
    slots.sort(key=lambda s: s["value"], reverse=True)
    return {"network": net, "rows": rows, "max": mx,
            "top": slots[:3], "timezone": TIMEZONE}


def analytics(network=None):
    """Return social analytics. Live via Metricool REST if token; else zeros."""
    net = _norm_net(network)
    token = os.environ.get("METRICOOL_USER_TOKEN", "")
    if token:
        try:
            live = _live_analytics(token, net)
            if live:
                return {"network": net, "source": "live", **live}
        except Exception as e:
            import sys
            print(f"[social] live analytics failed, falling back to mock: {e}",
                  file=sys.stderr)
    return {"network": net, "source": "mock", **_ANALYTICS[net]}


# --- post / schedule queue (persisted) --------------------------------------
def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("posts"), list):
                return d
        except Exception:
            pass
    return {"posts": [], "seq": 0}


def _save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    forge_atomic.atomic_write_json(STATE, d)


def _slim(p):
    return {
        "id": p.get("id"),
        "network": _norm_net(p.get("network")),
        "text": p.get("text") or "",
        "link": p.get("link") or "",
        "mediaUrl": p.get("mediaUrl") or "",
        "scheduledAt": p.get("scheduledAt") or "",
        "status": p.get("status") if p.get("status") in POST_STATUSES else "draft",
        "createdAt": p.get("createdAt"),
        "updatedAt": p.get("updatedAt"),
        "postedAt": p.get("postedAt"),
    }


def list_posts(network=None):
    with _LOCK:
        d = _load()
        posts = [_slim(p) for p in d.get("posts", [])]
    if network:
        net = _norm_net(network)
        posts = [p for p in posts if p["network"] == net]
    posts.sort(key=lambda p: p.get("updatedAt") or p.get("createdAt") or 0, reverse=True)
    return {"posts": posts, "count": len(posts), "networks": NETWORKS,
            "statuses": POST_STATUSES}


def save_post(p):
    if not isinstance(p, dict):
        return {"error": "post object required"}
    text = (p.get("text") or "").strip()
    if not text and not p.get("mediaUrl"):
        return {"error": "post needs text or media"}
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        pid = p.get("id")
        posts = d.get("posts", [])
        existing = next((x for x in posts if x.get("id") == pid), None) if pid else None
        if existing:
            existing.update({
                "network": _norm_net(p.get("network", existing.get("network"))),
                "text": text or existing.get("text", ""),
                "link": p.get("link", existing.get("link", "")),
                "mediaUrl": p.get("mediaUrl", existing.get("mediaUrl", "")),
                "scheduledAt": p.get("scheduledAt", existing.get("scheduledAt", "")),
                "status": p.get("status", existing.get("status", "draft")),
                "updatedAt": now,
            })
            saved = existing
        else:
            d["seq"] = d.get("seq", 0) + 1
            saved = {
                "id": pid or f"p{d['seq']}_{now}",
                "network": _norm_net(p.get("network")),
                "text": text, "link": p.get("link", ""),
                "mediaUrl": p.get("mediaUrl", ""),
                "scheduledAt": p.get("scheduledAt", ""),
                "status": p.get("status") if p.get("status") in POST_STATUSES else "draft",
                "createdAt": now, "updatedAt": now, "postedAt": None,
            }
            posts.append(saved)
        d["posts"] = posts
        _save(d)
        return {"ok": True, "post": _slim(saved)}


def set_status(pid, status):
    if status not in POST_STATUSES:
        return {"error": f"status must be one of {POST_STATUSES}"}
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        p = next((x for x in d.get("posts", []) if x.get("id") == pid), None)
        if not p:
            return {"error": "post not found"}
        p["status"] = status
        p["updatedAt"] = now
        if status == "posted":
            p["postedAt"] = now
        _save(d)
        saved = _slim(p)
        # NOTE: marking 'ready' flags a post for the executor (operator via MCP,
        # or the box via REST once METRICOOL_USER_TOKEN is set) to publish.
    if status == "ready":
        agency_approvals_io.add(
            "social", pid, f"Social post: {saved.get('network', 'social')}",
            "Post is ready for operator approval before Metricool publishing.",
            client=BRAND, risk="medium", payload={"text": saved.get("text", "")})
    return {"ok": True, "post": saved}


def delete_post(pid):
    if not pid:
        return {"error": "id required"}
    with _LOCK:
        d = _load()
        before = len(d.get("posts", []))
        d["posts"] = [x for x in d.get("posts", []) if x.get("id") != pid]
        _save(d)
        return {"ok": True, "removed": before - len(d["posts"])}


def publish(post):
    """M3: Publish a post via Metricool REST if token; else flag for operator. Never throws.

    post: a post dict (id, network, text, link, mediaUrl, scheduledAt, etc.)
    Returns: {ok, detail, url?}
    """
    token = os.environ.get("METRICOOL_USER_TOKEN", "")
    if token:
        try:
            return _live_publish(token, post)
        except Exception as e:
            import sys
            print(f"[social] live publish failed: {e}", file=sys.stderr)
            return {"ok": False, "detail": f"Metricool API error: {e}"}
    # No token — do not claim that anything was published. The approval remains
    # failed/retryable until REST is configured or the operator publishes via MCP.
    pid = post.get("id")
    if pid:
        set_status(pid, "ready")
    return {
        "ok": False,
        "detail": "Metricool REST is not configured; publish via MCP or set METRICOOL_USER_TOKEN.",
        "flagged": True,
    }


def _live_publish(token, post):
    """POST to Metricool REST API to schedule/publish the post."""
    net = _norm_net(post.get("network"))
    scheduled_at = post.get("scheduledAt") or ""

    # Metricool v1 create post endpoint
    body = {
        "blogId": BLOG_ID,
        "networks": [net],
        "text": post.get("text", ""),
        "link": post.get("link", ""),
        "date": scheduled_at,
        "publish": not bool(scheduled_at),  # publish immediately if no schedule
    }
    if post.get("mediaUrl"):
        body["media"] = [{"url": post["mediaUrl"]}]

    resp = _metricool_req(token, "POST", "/post/create", body=body,
                          params={"user_token": token})
    post_id = resp.get("id") or resp.get("postId")
    if resp.get("error") or resp.get("status") == "error":
        return {"ok": False, "detail": f"Metricool error: {resp}"}

    # Mark local post as posted
    pid = post.get("id")
    if pid:
        set_status(pid, "posted")

    url = f"https://app.metricool.com/app/planning?brand={BRAND}"
    return {
        "ok": True,
        "detail": f"Post published to {net} via Metricool REST.",
        "url": url,
        "metricoolId": post_id,
    }


def ready_for_executor():
    """Posts marked 'ready' — what the operator (MCP) or box (REST) should publish."""
    return {"posts": [p for p in list_posts()["posts"] if p["status"] == "ready"]}
