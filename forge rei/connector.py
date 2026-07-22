#!/usr/bin/env python3
"""FORGE REI OS — GoHighLevel live connector.

Read-only bridge between the static dashboard (browser) and GoHighLevel.
- Serves the dashboard files (same origin -> no CORS, token never leaves server).
- Exposes /api/* endpoints that proxy + aggregate the GHL v2 API.

Stdlib only. No new dependencies, no database. Reuses the existing
credentials in marcus-wholesale-agent/config/ghl.env.

Run:  python3 connector.py   ->   http://localhost:7799
"""

import io
import json
import os
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("FORGE_PORT", "7799"))
# Bind host. Localhost-only by default (safe on a laptop). On the 24/7 box set
# FORGE_HOST=0.0.0.0 so Tailscale peers can reach it; the firewall keeps :7799
# private to the tailnet (never exposed to the public internet).
HOST = os.environ.get("FORGE_HOST", "127.0.0.1")
LOOPS_ENABLED = os.environ.get("FORGE_MARCUS", "1") != "0"
BUSINESS_TZ = os.environ.get("TZ") or os.environ.get("FORGE_TZ", "America/New_York")
os.environ.setdefault("TZ", BUSINESS_TZ)
if hasattr(time, "tzset"):
    time.tzset()

# ---------------------------------------------------------------------------
# Credentials — reuse the Marcus wholesale GHL config (do not duplicate keys).
# ---------------------------------------------------------------------------
ENV_CANDIDATES = [
    HERE.parent / "marcus-wholesale-agent" / "config" / "ghl.env",
    Path.home() / "Desktop" / "marcus-wholesale-agent" / "config" / "ghl.env",
]
# Forge AI Agency — its OWN GoHighLevel sub-account, kept fully separate from
# wholesale (different file, different keys, different code path).
AGENCY_ENV_CANDIDATES = [
    HERE.parent / "forge-agency" / "config" / "agency.env",
    Path.home() / "Desktop" / "forge-agency" / "config" / "agency.env",
]
# Daycare — its OWN GoHighLevel sub-account for family messaging, kept separate
# from wholesale + agency (keys live in forge-daycare/config/daycare.env).
DAYCARE_ENV_CANDIDATES = [
    HERE.parent / "forge-daycare" / "config" / "daycare.env",
    Path.home() / "Desktop" / "forge-daycare" / "config" / "daycare.env",
    Path("/opt/forge/forge-daycare/config/daycare.env"),
]


def _load_env(paths):
    cfg = {}
    for p in paths:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip()
            break
    return cfg


_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _http_error_detail(e, limit=500):
    """Read/cache an HTTPError body while preserving the exception type contract."""
    body = getattr(e, "_body", None)
    if body is None:
        try:
            body = e.read()
        except Exception:  # noqa: BLE001
            body = b""
        e._body = body
        try:
            e.fp = io.BytesIO(body if isinstance(body, bytes) else str(body).encode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
    text = body.decode("utf-8", "ignore") if isinstance(body, bytes) else str(body or "")
    detail = text.strip()
    try:
        parsed = json.loads(detail)
        if isinstance(parsed, dict):
            detail = (parsed.get("message") or parsed.get("error_description")
                      or parsed.get("error") or parsed.get("detail") or detail)
            if isinstance(detail, (dict, list)):
                detail = json.dumps(detail)
    except Exception:  # noqa: BLE001
        pass
    detail = str(detail or getattr(e, "reason", "") or "")[:limit]
    e._detail = detail
    if detail:
        msg = str(getattr(e, "msg", "") or getattr(e, "reason", "") or "")
        if detail not in msg:
            e.msg = f"{msg}: {detail[:250]}" if msg else detail[:250]
    return detail


class GHLClient:
    """One GoHighLevel account (sub-account). Wholesale and agency each get their
    own instance, so their tokens + location IDs never mix."""

    def __init__(self, cfg, label=""):
        self.label = label
        self.api_key = cfg.get("GHL_API_KEY", "")
        self.location_id = cfg.get("GHL_LOCATION_ID", "")
        self.base = cfg.get("GHL_BASE_URL",
                            "https://services.leadconnectorhq.com").rstrip("/")
        self.version = cfg.get("GHL_API_VERSION", "2021-07-28")

    @property
    def configured(self):
        return bool(self.api_key and self.location_id)

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Version": self.version,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": _UA,  # Cloudflare (1010) blocks default urllib UA.
        }

    def _req(self, method, endpoint, params=None, body=None, retries=3):
        url = f"{self.base}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw.strip() else {}
            except urllib.error.HTTPError as e:
                # GHL rate-limits bursts (429) — back off and retry.
                if e.code in (429, 500, 502, 503) and attempt < retries:
                    time.sleep(0.6 * (attempt + 1))
                    continue
                _http_error_detail(e)
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                # Transient network: read-timeout, DNS flap, connection reset/refused —
                # the most common real-world failure. Back off and retry instead of
                # aborting the whole poll sweep. (HTTPError is a URLError subclass but is
                # caught above, so this only sees true network errors.)
                if attempt < retries:
                    time.sleep(0.6 * (attempt + 1))
                    continue
                raise

    def get(self, endpoint, params=None, retries=3):
        return self._req("GET", endpoint, params=params, retries=retries)

    def post(self, endpoint, body, retries=2):
        return self._req("POST", endpoint, body=body, retries=retries)

    def put(self, endpoint, body, retries=2):
        return self._req("PUT", endpoint, body=body, retries=retries)

    def delete(self, endpoint, body=None, retries=2):
        return self._req("DELETE", endpoint, body=body, retries=retries)


WHOLESALE = GHLClient(_load_env(ENV_CANDIDATES), "wholesale")
AGENCY = GHLClient(_load_env(AGENCY_ENV_CANDIDATES), "agency")
DAYCARE_GHL = GHLClient(_load_env(DAYCARE_ENV_CANDIDATES), "daycare")

# Family Contact Form GHL location tag -> Supabase center id. The public form tags
# each submission with its center (submit.js); this maps that tag to the Supabase
# `locations` row so the dashboard inbox can organize families by center and provision
# each into the right one. IDs are stable business identifiers (not secrets).
DAYCARE_FORM_LOCATION_BY_TAG = {
    "loc-921-n-18th": "11111111-1111-1111-1111-111111111111",       # A Touch of Blessings
    "loc-2318-cecil-b-moore": "22222222-2222-2222-2222-222222222222",  # A Touch of Blessings 2
    "loc-1923-cecil-b-moore": "44444444-4444-4444-4444-444444444444",  # A Mother's Touch
}


# Key families that are PER-BUSINESS / per-sub-account and must stay isolated —
# never merged into the shared process env (CLAUDE.md §11). The three GHL
# sub-accounts, each business's own Meta ad account + social token, the
# daycare-internal Supabase/app vars, and Anthropic (unified deliberately via the
# systemd env, so it must not be re-injected from any file's stale copy).
_SHARED_ISOLATED = ("GHL_", "ANTHROPIC", "AGENCY_ANTHROPIC",
                    "META_", "METRICOOL_", "DAYCARE_", "NEXT_PUBLIC_", "SUPABASE")


def _inject_env(paths, exclude_prefixes=()):
    """Inject env-file keys into os.environ without clobbering real shell/systemd
    vars (first-writer-wins). exclude_prefixes skips per-business/isolated families.

    So META_ACCESS_TOKEN / N8N_* / METRICOOL_* / GITHUB_TOKEN (+ every shared app
    key) are visible to all modules via os.environ.get() — the credential-guard
    pattern every M2/M3 module uses.
    """
    for k, v in _load_env(paths).items():
        if v and k not in os.environ and not (exclude_prefixes and k.startswith(exclude_prefixes)):
            os.environ[k] = v


_inject_env(AGENCY_ENV_CANDIDATES)  # agency's own keys (incl its META/GHL) — unchanged
# Also expose the OTHER businesses' shared APP keys (RETELL, APIFY, TWILIO,
# HIGGSFIELD, STRIPE, GOOGLE, N8N, RESEND, OPENAI…) process-wide so ANY agent can
# call an app whose key lives in another folder. Per-business families
# (GHL_/META_/METRICOOL_/ANTHROPIC/daycare-internal) stay isolated; first-writer-
# wins keeps agency's values authoritative for anything genuinely shared.
_inject_env(DAYCARE_ENV_CANDIDATES, exclude_prefixes=_SHARED_ISOLATED)
_inject_env(ENV_CANDIDATES, exclude_prefixes=_SHARED_ISOLATED)

# Back-compat: the rest of the app (marcus_engine, analytics, brain, etc.) uses
# these module-level WHOLESALE handles. Behavior unchanged.
API_KEY = WHOLESALE.api_key
LOCATION_ID = WHOLESALE.location_id
BASE_URL = WHOLESALE.base
API_VERSION = WHOLESALE.version


def ghl_get(endpoint, params=None, retries=3):
    return WHOLESALE.get(endpoint, params, retries)


def ghl_post(endpoint, body, retries=2):
    return WHOLESALE.post(endpoint, body, retries)


def ghl_put(endpoint, body, retries=2):
    return WHOLESALE.put(endpoint, body, retries)


def ghl_delete(endpoint, body=None, retries=2):
    return WHOLESALE.delete(endpoint, body, retries)

# Small in-process cache so the dashboard's auto-refresh doesn't hammer GHL.
_CACHE = {}
_CACHE_TTL = 45  # seconds — softens GHL rate limits under auto-refresh
_CACHE_MAX = 200  # cap entries so a long-running 24/7 process can't leak memory

# Shared revision for the separate desktop dashboard and mobile app. Both clients
# read the same connector, so a successful write can invalidate every open view
# without merging the frontends or exposing state files over HTTP.
_SYNC_LOCK = threading.Lock()
_SYNC_STARTED_MS = int(time.time() * 1000)
_SYNC_REVISION = 0


def _touch_sync():
    global _SYNC_REVISION
    with _SYNC_LOCK:
        _SYNC_REVISION += 1


def api_sync(_q):
    with _SYNC_LOCK:
        revision = _SYNC_REVISION
    return {
        "ok": True,
        "version": f"{_SYNC_STARTED_MS}:{revision}",
        "serverTime": int(time.time() * 1000),
        "pollMs": 2000,
    }

# Static serving is allow-listed: only these asset types are ever sent to the
# browser. Anything else (.py source, .env*, .jsonl state, SSH keys, .db) 404s.
SERVE_TYPES = {
    ".html": "text/html", ".css": "text/css", ".jsx": "text/babel",
    ".js": "application/javascript", ".json": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2",
}
# Directories that must never be reachable over HTTP even with an allowed suffix.
DENY_DIRS = {"deploy", "marcus_state", "__pycache__", ".git", "uploads"}


# GHL HTTP now lives on GHLClient (WHOLESALE / AGENCY). ghl_get/post/put above are
# thin wholesale wrappers kept for existing callers.

# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------
def contacts_page(limit=100, start_after=None, start_after_id=None, query=None):
    params = {"locationId": LOCATION_ID, "limit": limit}
    if start_after:
        params["startAfter"] = start_after
    if start_after_id:
        params["startAfterId"] = start_after_id
    if query:
        params["query"] = query
    return ghl_get("/contacts/", params)


def _slim_contact(c):
    name = f"{c.get('firstName') or ''} {c.get('lastName') or ''}".strip() or "(no name)"
    addr = ", ".join(
        [x for x in [c.get("address1"), c.get("city"), c.get("state")] if x]
    )
    return {
        "id": c.get("id"),
        "name": name,
        "phone": c.get("phone") or "",
        "email": c.get("email") or "",
        "tags": c.get("tags") or [],
        "addr": addr,
        "source": c.get("source") or "GoHighLevel",
        "dateAdded": c.get("dateAdded"),
        "dateUpdated": c.get("dateUpdated"),
    }


def all_opportunities():
    """Page through every opportunity (usually a small set)."""
    opps, start_after, start_after_id = [], None, None
    for _ in range(50):  # hard cap
        params = {"location_id": LOCATION_ID, "limit": 100}
        if start_after:
            params["startAfter"] = start_after
            params["startAfterId"] = start_after_id
        data = ghl_get("/opportunities/search", params)
        batch = data.get("opportunities", []) or []
        opps.extend(batch)
        meta = data.get("meta", {}) or {}
        if not batch or not meta.get("nextPage"):
            break
        start_after = meta.get("startAfter")
        start_after_id = meta.get("startAfterId")
    return opps


def pipelines():
    data = ghl_get("/opportunities/pipelines", {"locationId": LOCATION_ID})
    return data.get("pipelines", []) or []


def contact_tasks(contact_id):
    try:
        data = ghl_get(f"/contacts/{contact_id}/tasks")
        return data.get("tasks", []) or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# API endpoint handlers (return python objects)
# ---------------------------------------------------------------------------
def api_ops_status(_q):
    """The agent time-clock state (clocked out/in) for the Command Center pill."""
    return forge_ops.status()


def api_health(_q):
    ok = bool(API_KEY and LOCATION_ID)
    out = {
        "ok": ok,
        "locationId": LOCATION_ID if ok else None,
        "base": BASE_URL,
        "version": API_VERSION,
        "loopsEnabled": LOOPS_ENABLED,
        "businessTimezone": BUSINESS_TZ,
        "ops": forge_ops.status(),
    }
    # Real liveness probe: the Scout poll loop bumps last_run every sweep (even when there
    # are no new leads). If it's older than 3 sweeps the loop is wedged or can't reach GHL
    # — surface it so an external uptime check (or the operator) can catch a silent death.
    try:
        last_run = getattr(SCOUT, "last_run", 0) or 0
        age_s = (int(time.time() * 1000) - last_run) / 1000 if last_run else None
        stale = (LOOPS_ENABLED and age_s is not None
                 and age_s > 3 * scout_triage.POLL_INTERVAL)
        out["scout"] = {
            "lastRunAgeSec": int(age_s) if age_s is not None else None,
            "lastError": getattr(SCOUT, "last_error", None),
            "stale": bool(stale),
        }
        if stale:
            out["ok"] = False
    except Exception:
        pass  # SCOUT not up yet (startup) or UI-only mode — health still returns base info
    # Follow-up loop liveness (slow cadence; stale if older than ~2 intervals).
    try:
        fr = getattr(FOLLOWUP, "last_run", 0) or 0
        fage = (int(time.time() * 1000) - fr) / 1000 if fr else None
        fstale = (LOOPS_ENABLED and fage is not None
                  and fage > 2.2 * followup.INTERVAL)
        out["followup"] = {"lastRunAgeSec": int(fage) if fage is not None else None,
                           "lastError": getattr(FOLLOWUP, "last_error", None),
                           "stale": bool(fstale)}
        if fstale:
            out["ok"] = False
    except Exception:
        pass
    try:
        rows = deals.list_deals()
        pending = sum(
            1 for d in rows
            if (not d.get("pipelineSyncSkippedAt")
                and ((d.get("contractStatus") in ("sent", "delivered")
                      and not d.get("contractPipelineSyncedAt"))
                     or (d.get("contractStatus") == "completed"
                         and not d.get("closedPipelineSyncedAt"))))
        )
        skipped = sum(1 for d in rows if d.get("pipelineSyncSkippedAt"))
        last_contract = _CONTRACT_MONITOR.get("lastRun") or 0
        cage = ((int(time.time() * 1000) - last_contract) / 1000
                if last_contract else None)
        contract_configured = docusign_io.configured()
        poll_interval = int(os.environ.get("FORGE_CONTRACT_POLL", "600"))
        cstale = (LOOPS_ENABLED and contract_configured and cage is not None
                  and cage > max(1200, 2.2 * poll_interval))
        contract_error = _CONTRACT_MONITOR.get("lastError")
        out["contract"] = {
            "configured": contract_configured,
            "lastRunAgeSec": int(cage) if cage is not None else None,
            "lastError": contract_error,
            "stale": bool(cstale),
            "pendingPipelineSync": pending,
            "skippedPipelineSync": skipped,
        }
        if cstale or contract_error:
            out["ok"] = False
    except Exception:
        pass
    out["telegram"] = {"configured": bool(getattr(telegram_io, "configured", lambda: False)())}
    return out


def api_system_health(_q):
    """Aggregate liveness for EVERY background loop + disk/log pressure — one screen that
    answers 'is the whole fleet running?'. Reads the forge_heartbeat store that each loop
    stamps every iteration, so a silently-dead thread shows up here (and drives the
    watchdog + the System Health UI tab). Never 500s."""
    loops = forge_heartbeat.snapshot()
    disk = forge_heartbeat.disk_log_stats()
    # A loop only counts as 'red' when the fleet is supposed to be running: skip staleness on
    # a UI-only Mac (FORGE_MARCUS=0) or when the crew is clocked out.
    paused = False
    try:
        paused = bool(forge_ops.paused())
    except Exception:
        pass
    active = LOOPS_ENABLED and not paused
    red = [l["loop"] for l in loops if l.get("status") == "red"] if active else []
    disk_ok = True
    try:
        pct = (disk.get("disk") or {}).get("pctUsed")
        disk_ok = pct is None or pct < 92
    except Exception:
        pass
    return {
        "ok": (not red) and disk_ok,
        "loopsEnabled": LOOPS_ENABLED,
        "paused": paused,
        "active": active,
        "redLoops": red,
        "diskOk": disk_ok,
        "loops": loops,
        "disk": disk.get("disk"),
        "logs": disk.get("logs"),
        "stateBytes": disk.get("stateBytes"),
        "telegramConfigured": bool(getattr(telegram_io, "configured", lambda: False)()),
        # Marcus screening is event-driven (fires off Scout's scores) — no loop to heartbeat.
        "note": "Marcus screening is event-driven (no heartbeat).",
        "now": int(time.time() * 1000),
    }


def api_mission_control(_q):
    """The front-door snapshot: one light health + attention read across every
    business + the loop fleet, each item carrying a jump target. Never 500s."""
    try:
        return mission_control.snapshot(
            scout=SCOUT, solomon=SOLOMON, midas=MIDAS, screener=SCREENER,
            system=api_system_health(None))
    except Exception as e:  # last-resort guard — the landing screen must always render
        return {"ok": False, "verdict": "SNAPSHOT ERROR", "verdictStatus": "down",
                "attentionCount": 0, "businesses": [], "system": {},
                "error": str(e)[:200], "generatedAt": int(time.time() * 1000)}


def api_ace_state(_q):
    """ACE Phase 1 (read-only): the per-thread conversation state machine — where each seller
    conversation is + which qualifying facts we have. No sends; just observability for the
    autonomy rollout. CONVO is defined at boot; guard in case of UI-only startup."""
    try:
        return {"ok": True, "summary": CONVO.summary(), "threads": CONVO.all()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "summary": {"total": 0, "byState": {}}, "threads": []}


def api_ace_status(_q):
    """ACE controller status: mode (off/shadow/supervised/full), today's send count, recent log."""
    try:
        return {"ok": True, **ace.status()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "mode": "off"}


def api_cost_status(_q):
    """Running cost of the OS: Claude tokens, SMS count, fixed monthly, cap alert."""
    try:
        import cost_tracker
        return cost_tracker.status()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "today": {}, "mtd": {}, "trend": []}


def api_spend_status(_q):
    """The operator's own monthly subscriptions/bills, grouped by business (spend_tracker)."""
    try:
        import spend_tracker
        return spend_tracker.status()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "groups": [], "monthlyUSD": 0.0}


def api_ace_callready(_q):
    """ACE Phase 4: the call queue — call-ready leads with the full card (anchors, prep)."""
    try:
        return ace.call_ready_list()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "callReady": [], "waiting": 0}


def api_ace_digest(_q):
    """ACE Phase 5: autonomy digest — sends, escalations, blocks-by-reason, call queue."""
    try:
        return ace.digest(days=1)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "summary": {}, "events": []}


def api_skillforge_pending(_q):
    """skill_forge proposal queue: pending skill drafts awaiting a tap + recent decisions."""
    try:
        import skill_forge as _sf
        return _sf.pending()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "pending": [], "recent": []}


def _qint(q, key, default):
    """Safe int from a query-string dict — bad input (?limit=abc) falls back to
    the default instead of throwing ValueError and 500ing the endpoint."""
    try:
        return int(q.get(key, [str(default)])[0])
    except (ValueError, TypeError):
        return default


def api_contacts(q):
    limit = _qint(q, "limit", 100)
    query = q.get("query", [None])[0]
    data = contacts_page(limit=limit, query=query)
    contacts = [_slim_contact(c) for c in data.get("contacts", []) or []]
    meta = data.get("meta", {}) or {}
    return {
        "total": meta.get("total", len(contacts)),
        "count": len(contacts),
        "contacts": contacts,
    }


def api_conversations(q):
    limit = _qint(q, "limit", 50)
    data = ghl_get(
        "/conversations/search",
        {"locationId": LOCATION_ID, "limit": limit, "sortBy": "last_message_date"},
    )
    convos = []
    for c in data.get("conversations", []) or []:
        convos.append(
            {
                "id": c.get("id"),
                "contactId": c.get("contactId"),
                "name": c.get("fullName") or c.get("contactName") or "(unknown)",
                "phone": c.get("phone") or "",
                "lastMessage": c.get("lastMessageBody") or "",
                "lastMessageType": c.get("lastMessageType") or "",
                "lastMessageDate": c.get("lastMessageDate"),
                "unread": c.get("unreadCount", 0) or 0,
                "type": c.get("type") or "",
            }
        )
    return {
        "total": data.get("total", len(convos)),
        "count": len(convos),
        "locationId": LOCATION_ID,
        "conversations": convos,
    }


def _opp_view():
    pls = pipelines()
    opps = all_opportunities()
    stage_names, stage_order = {}, {}
    for p in pls:
        for idx, s in enumerate(p.get("stages", []) or []):
            stage_names[s.get("id")] = s.get("name", "Unknown")
            stage_order[s.get("id")] = (p.get("id"), idx)
    enriched = []
    for o in opps:
        sid = o.get("pipelineStageId")
        contact = o.get("contact", {}) or {}
        enriched.append(
            {
                "id": o.get("id"),
                "name": o.get("name") or contact.get("name") or "(no name)",
                "value": float(o.get("monetaryValue", 0) or 0),
                "status": o.get("status") or "open",
                "pipelineId": o.get("pipelineId"),
                "stageId": sid,
                "stage": stage_names.get(sid, "Unknown"),
                "contactId": contact.get("id"),
                "phone": contact.get("phone") or "",
                "tags": contact.get("tags") or [],
                "updated": o.get("updatedAt") or o.get("dateUpdated"),
            }
        )
    return pls, enriched


def api_messages(q):
    """Full SMS thread for one contact (oldest -> newest), for the lead drawer."""
    contact_id = q.get("contactId", [None])[0]
    if not contact_id:
        return {"error": "contactId required", "messages": []}
    limit = _qint(q, "limit", 50)
    conv = ghl_get("/conversations/search",
                   {"locationId": LOCATION_ID, "contactId": contact_id})
    convos = conv.get("conversations", []) or []
    if not convos:
        return {"conversationId": None, "count": 0, "messages": []}
    conv_id = convos[0].get("id")
    data = ghl_get(f"/conversations/{conv_id}/messages", {"limit": limit})
    raw = data.get("messages", data)
    if isinstance(raw, dict):
        raw = raw.get("messages", [])
    msgs = [
        {
            "direction": m.get("direction"),
            "body": m.get("body") or "",
            "type": m.get("messageType") or m.get("type"),
            "date": m.get("dateAdded"),
        }
        for m in (raw or [])
    ]
    msgs.reverse()  # GHL returns newest-first; show oldest-first like a chat
    return {"conversationId": conv_id, "count": len(msgs), "messages": msgs}


def api_pipeline(_q):
    pls, opps = _opp_view()
    pipelines_out = []
    for p in pls:
        stages = []
        for s in p.get("stages", []) or []:
            sid = s.get("id")
            cards = [o for o in opps if o["stageId"] == sid]
            stages.append(
                {
                    "id": sid,
                    "name": s.get("name"),
                    "count": len(cards),
                    "value": sum(c["value"] for c in cards),
                    "cards": cards,
                }
            )
        pipelines_out.append(
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "stages": stages,
                "totalDeals": sum(s["count"] for s in stages),
                "totalValue": sum(s["value"] for s in stages),
            }
        )
    return {"pipelines": pipelines_out, "opportunities": opps}


def api_tasks(q):
    """No global GHL task list -> aggregate across the most-recent contacts."""
    scan = _qint(q, "scan", 150)
    data = contacts_page(limit=min(scan, 100))
    contacts = data.get("contacts", []) or []
    by_id = {c.get("id"): _slim_contact(c) for c in contacts}
    tasks = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = ex.map(contact_tasks, list(by_id.keys()))
        for cid, tlist in zip(by_id.keys(), results):
            for t in tlist:
                tasks.append(
                    {
                        "id": t.get("id"),
                        "title": t.get("title") or "(untitled task)",
                        "body": t.get("body") or "",
                        "dueDate": t.get("dueDate"),
                        "completed": bool(t.get("completed")),
                        "contactId": cid,
                        "contactName": by_id[cid]["name"],
                        "assignedTo": t.get("assignedTo") or "",
                    }
                )
    tasks.sort(key=lambda t: t.get("dueDate") or "")
    return {"count": len(tasks), "scanned": len(by_id), "tasks": tasks}


def api_dashboard(_q):
    out = {}

    def safe(fn, key, default=0):
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001
            out[key] = default
            out.setdefault("_errors", {})[key] = str(e)

    # Run the independent counts concurrently.
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_contacts = ex.submit(
            lambda: ghl_get("/contacts/", {"locationId": LOCATION_ID, "limit": 1})
        )
        f_convos = ex.submit(
            lambda: ghl_get(
                "/conversations/search", {"locationId": LOCATION_ID, "limit": 100}
            )
        )
        f_opps = ex.submit(_opp_view)
        f_contacts_r = f_contacts.result()
        f_convos_r = f_convos.result()
        pls, opps = f_opps.result()

    out["totalLeads"] = (f_contacts_r.get("meta", {}) or {}).get("total", 0)

    convos = f_convos_r.get("conversations", []) or []
    out["totalConversations"] = f_convos_r.get("total", len(convos))
    out["activeConversations"] = sum(1 for c in convos if (c.get("unreadCount") or 0) > 0)

    open_opps = [o for o in opps if o["status"] == "open"]
    out["openOpportunities"] = len(open_opps)
    out["pipelineValue"] = sum(o["value"] for o in open_opps)
    out["appointments"] = sum(
        1 for o in opps if "appointment" in (o["stage"] or "").lower()
    )

    # Tasks due today (best-effort scan of recent contacts).
    try:
        today = time.strftime("%Y-%m-%d")
        tdata = api_tasks({"scan": ["30"]})
        out["tasksDueToday"] = sum(
            1
            for t in tdata["tasks"]
            if not t["completed"] and (t.get("dueDate") or "").startswith(today)
        )
        out["openTasks"] = sum(1 for t in tdata["tasks"] if not t["completed"])
    except Exception as e:  # noqa: BLE001
        out["tasksDueToday"] = 0
        out["openTasks"] = 0
        out.setdefault("_errors", {})["tasks"] = str(e)

    out["pipelineNames"] = [p.get("name") for p in pls]
    return out


# ---------------------------------------------------------------------------
# Marcus — autonomous responder engine (trigger-on-need)
# ---------------------------------------------------------------------------
import marcus_engine  # noqa: E402

MARCUS = marcus_engine.MarcusEngine(ghl_get, ghl_post, LOCATION_ID)


def api_marcus_status(_q):
    return MARCUS.status()


def api_marcus_proposals(_q):
    return {"proposals": MARCUS.proposals_list(), "activity": MARCUS.activity[:40]}


# ---------------------------------------------------------------------------
# Analytics — deterministic message metrics
# ---------------------------------------------------------------------------
import analytics_engine  # noqa: E402


def api_analytics(q):
    days = _qint(q, "days", 30)
    return analytics_engine.build(ghl_get, _opp_view, LOCATION_ID, days=days)


# ---------------------------------------------------------------------------
# Brain — read/write the Agentic-OS Obsidian vault (path-jailed)
# ---------------------------------------------------------------------------
import brain_io  # noqa: E402


def api_brain_tree(_q):
    return brain_io.tree()


def api_brain_note(q):
    return brain_io.read_note(q.get("path", [""])[0])


def api_brain_search(q):
    return brain_io.search(q.get("q", [""])[0])


def api_brain_recent(q):
    return brain_io.recent(_qint(q, "n", 20))


def api_brain_graph(q):
    return brain_io.graph(_qint(q, "limit", 90))


def api_brain_activity(q):
    return brain_io.activity(_qint(q, "n", 30))


def api_brain_status(_q):
    """Brain connection/sync health — surfaced across both workspaces."""
    t = brain_io.tree()
    notes = sum(f.get("count", 0) for f in t.get("folders", [])) if t.get("available") else 0
    skills = brain_io.skill_status()
    return {"available": t.get("available", False), "live": skills.get("live", False),
            "vault": t.get("vault"), "notes": notes,
            "agentsReady": skills.get("ready", 0), "agentsTotal": skills.get("total", 0),
            "newestSkillMtime": skills.get("newestSkillMtime"),
            "consumers": skills.get("consumers", {}),
            "url": getattr(brain_io, "BRAIN_URL", None)}


# ---------------------------------------------------------------------------
# Graphify — global knowledge graph (~/.graphify/global-graph.json)
# Agents and the Brain tab UI can query across all projects.
# ---------------------------------------------------------------------------
import graphify_io  # noqa: E402


def api_graphify_graph(_q):
    return graphify_io.graph()


def api_graphify_search(q):
    query = q.get("q", [""])[0].strip()
    repo  = q.get("repo", [""])[0].strip() or None
    if not query:
        return {"ok": False, "error": "missing q"}
    return graphify_io.search(query, repo=repo)


def api_graphify_stats(_q):
    return graphify_io.stats()


def api_graphify_build_status(_q):
    """Last box-native rebuild result (builtAt/nodes/links/byRepo). Presence of
    graphify_build means the live builder is wired; builtAt=None until first run."""
    try:
        import graphify_build
        return {"ok": True, **graphify_build.status(),
                "everyMin": graphify_build.REBUILD_EVERY // 60}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Weekly review agent (LLM, parallel)
# ---------------------------------------------------------------------------
import review_agent  # noqa: E402


def api_review_latest(_q):
    return review_agent.latest()


import retell_io  # noqa: E402


def api_outbound_status(_q):
    return retell_io.status()


def api_outbound_calls(q):
    try:
        limit = int((q.get("limit", ["20"]) or ["20"])[0])
    except (ValueError, TypeError):
        limit = 20
    return retell_io.calls(limit=limit)


def api_outbound_agent(q):
    return retell_io.get_agent((q.get("id", [""]) or [""])[0] or None)


def api_outbound_voices(_q):
    return retell_io.list_voices()


import style_agent  # noqa: E402
import marcus_chat  # noqa: E402
import agents_chat  # noqa: E402
import agents_hub  # noqa: E402
import daily_goals  # noqa: E402
import deal_stats  # noqa: E402
import monthly_goals  # noqa: E402
import agency_io  # noqa: E402
import agency_ghl  # noqa: E402
import agency_requests_io  # noqa: E402
import agency_portal_io  # noqa: E402
import agency_dyson  # noqa: E402
import agency_workflows_io  # noqa: E402
import agency_ads  # noqa: E402
import agency_eco  # noqa: E402
import agency_approvals_io  # noqa: E402
import agency_agents  # noqa: E402
import agency_social  # noqa: E402
import agency_deploy  # noqa: E402
import agency_build_studio  # noqa: E402 — Blueprint Studio: idea -> build-ready plan (propose-only)
import agency_calls  # noqa: E402
import daycare_supabase  # noqa: E402 — secure Supabase-backed Daycare management API
import daycare_growth  # noqa: E402 — daycare Ads + Social monitoring (reuses agency engines)
import daycare_ads_studio  # noqa: E402 — Nova's idea → image → PAUSED ad pipeline
import stripe_io  # noqa: E402 — stdlib Stripe REST bridge for daycare invoicing
import daycare_ghl  # noqa: E402 — daycare GoHighLevel family messaging (owner-initiated)
import daycare_blast  # noqa: E402 — daycare family SMS blast (operator-gated, never autonomous)
import daycare_director  # noqa: E402 — Solomon, the daycare's head agent (executive director)
import daycare_family  # noqa: E402 — Nora, roster organizer & family follow-up (reports to Solomon)
import daycare_adops  # noqa: E402 — Nova, ad ops: campaign health, competitor intel, creative direction
SOLOMON = daycare_director.SolomonEngine()
NORA = daycare_family.NoraEngine()
NOVA = daycare_adops.NovaEngine()

# --- FORGE Dropship (4th business) — Shopify/AutoDS/Meta store + the Midas crew ------
import dropship_shopify  # noqa: E402 — Shopify Admin REST bridge (read-only; writes gated)
import dropship_autods  # noqa: E402 — AutoDS sourcing/orders bridge (read-only; orders gated)
import dropship_pipiads  # noqa: E402 — PiPiAds trending-products bridge (read-only, add-key)
import dropship_io  # noqa: E402 — dropship local store (watchlist + settings)
import dropship_context  # noqa: E402 — dropship business brief (read FIRST by every dropship agent)
import dropship_director  # noqa: E402 — Midas, the dropship head agent (e-com director)
import dropship_agents  # noqa: E402 — Hawk / Blaze / Otto specialist crew
MIDAS = dropship_director.MidasEngine()
HAWK = dropship_agents.HawkEngine()
BLAZE = dropship_agents.BlazeEngine()
OTTO = dropship_agents.OttoEngine()

import mission_control  # noqa: E402 — cross-business front-door snapshot (read-only)
import mission_control_agent  # noqa: E402 — Orion, the cross-business Chief-of-Staff agent
ORION = mission_control_agent.OrionEngine()


def _daycare_blast_transport(recipient, text):
    """Wire-send ONE family blast SMS through the daycare's own GHL sub-account.

    Registered here (not inside daycare_blast) so the engine stays decoupled from
    the GHL client, exactly like toolkit_blast. Only ever called from send_blast,
    which the console's confirm button gates.
    """
    if not DAYCARE_GHL.configured:
        return {"ok": False, "skipped": True,
                "note": "GHL not connected — add GHL_API_KEY + GHL_LOCATION_ID to daycare.env"}
    contact_id = daycare_ghl.ensure_contact(
        DAYCARE_GHL, name=recipient.get("name") or "Family",
        phone=recipient.get("phone"), email=recipient.get("email"))
    if not contact_id:
        return {"ok": False, "note": "could not resolve a GHL contact"}
    result = daycare_ghl.send_sms(DAYCARE_GHL, contact_id=contact_id, message=text)
    if not result.get("ok"):
        return {"ok": False, "note": result.get("detail") or "send failed"}
    return {"ok": True, "note": ""}


daycare_blast.register_transport(_daycare_blast_transport)
import scout_triage  # noqa: E402
import marcus_screening  # noqa: E402
import agent_bus  # noqa: E402
import forge_ops  # noqa: E402
import forge_heartbeat  # noqa: E402
import sms_guard  # noqa: E402
import telegram_io  # noqa: E402
import test_mode  # noqa: E402


def api_style_latest(_q):
    return style_agent.latest()


def api_agents_list(_q):
    return agents_chat.roster()


# ── Agents HUB — one tab to operate every agent across all three businesses ────
def api_hub_roster(q):
    # ?business=daycare|wholesale|agency — the hub is scoped to the workspace you're in.
    return agents_hub.roster((q.get("business", [None]) or [None])[0])


def api_hub_tasks(q):
    return agents_hub.tasks((q.get("agent", [None]) or [None])[0])


def api_hub_bus(q):
    return agents_hub.bus((q.get("agent", [None]) or [None])[0])


def api_hub_history(q):
    # agents_history.history() returns {"agentId", "history": [...], "count"} — the turns
    # live under "history", NOT the dict itself. Unwrap it: the hub's chat maps over this
    # list, and handing it an object is a render crash, not a graceful empty state.
    agent = (q.get("agent", ["marcus"]) or ["marcus"])[0]
    return {"messages": agents_history.history(agent).get("history") or []}


# Cross-agent coaching — the live feed powering the Agent Network's Coaching panel.
# INSIGHTS ONLY (text): broadcasts/asks/answers, never a credential or outward action.
def api_coach_feed(q):
    try:
        limit = int((q.get("limit", ["40"]) or ["40"])[0])
    except Exception:
        limit = 40
    return agents_hub.coach_feed(limit)


# Scout — wholesale lead-triage agent (ranks who to text back ASAP; read-only loop).
SCOUT = scout_triage.ScoutEngine(ghl_get, ghl_post, LOCATION_ID, ghl_put=ghl_put, ghl_delete=ghl_delete)

# Marcus (screening) — reads each seller thread + Scout's triage and writes a Seller
# Screening Report so the operator knows who to CALL. Never texts/offers; reuses Scout's
# gated writes for stage actions. The SMS engine (MARCUS) stays dormant alongside.
SCREENER = marcus_screening.Screener(ghl_get, LOCATION_ID, scout=SCOUT, ghl_post=ghl_post)


def _sms_safety_check(contact_id, message, conv_id=None, name="", last_seller_message=None,
                      kind="sms", autonomous=False, check_legit=True):
    return sms_guard.guard(contact_id, message, conv_id=conv_id, name=name, scout=SCOUT,
                           last_seller_message=last_seller_message, kind=kind,
                           autonomous=autonomous, check_legit=check_legit)


def _sms_safety_record(reservation=None, conv_id=None, contact_id=None, message=None,
                       kind="sms", last_message_date=0):
    return sms_guard.record_success(reservation=reservation, conv_id=conv_id,
                                    contact_id=contact_id, message=message, kind=kind,
                                    last_message_date=last_message_date)


MARCUS.safety_check = _sms_safety_check
MARCUS.safety_record = _sms_safety_record
MARCUS.safety_release = sms_guard.release
SCREENER.safety_check = _sms_safety_check
SCREENER.safety_record = _sms_safety_record
SCREENER.safety_release = sms_guard.release

# ACE — Autonomous Conversation Engine, Phase 1: read-only per-thread state machine. It rides
# the existing screening (no new loop, no sends) and just tracks where each seller conversation
# is + which qualifying facts we have. Later phases (ace.py) read it to decide reply-vs-escalate.
import conversation_engine  # noqa: E402
import ace  # noqa: E402
CONVO = conversation_engine.ConversationEngine()


def _ace_update_from_screening(contact_id):
    """After a screening lands, refresh the conversation state (best-effort, never raises).
    Mode routing: shadow → consider() drafts into the approval inbox (no send);
    supervised/full → apply() auto-sends ONE gated qualifying question (autonomous=True,
    full sms_guard stack, per-mode daily cap, Telegram receipt + stop button).
    Any non-off mode also builds/pings the call-ready queue when a thread goes CALL_READY."""
    try:
        rec = SCREENER.screenings.get(contact_id) or {}
        conv_id = rec.get("convId")
        if not conv_id:
            return
        crec = CONVO.update(conv_id, contact_id=contact_id, name=rec.get("name"),
                            phone=rec.get("phone"),
                            report=rec.get("report"),
                            last_inbound_ms=rec.get("updatedAt"))
        m = ace.mode()
        if crec and m != "off":
            last_in = None
            try:
                msgs = SCOUT._thread_transcript(conv_id) or []
                inb = [(m2.get("body") or "").strip() for m2 in msgs
                       if m2.get("direction") == "inbound" and (m2.get("body") or "").strip()]
                last_in = inb[-1] if inb else None
            except Exception:
                pass
            if m in ("supervised", "full"):
                ace.apply(conv_id, crec, rec.get("report"), CONVO, MARCUS,
                          last_seller_msg=last_in, deal_prep=DEAL_PREP)
            else:
                ace.consider(conv_id, crec, rec.get("report"), CONVO, MARCUS,
                             last_seller_msg=last_in)
                if (crec or {}).get("state") == "CALL_READY":
                    ace.call_ready_upsert(crec, rec.get("report"), DEAL_PREP)
    except Exception:
        pass


# Telegram — push alerts + tap-to-approve. Tap the bus so every agent_bus.send fans
# out to Telegram, and wire the inline-button callbacks to Marcus/Scout actions.
agent_bus.register_notifier(telegram_io.on_bus_message)


# Auto-screen: Scout calls this for every call-worthy lead it just scored (asap + warm),
# so a Marcus screening report is waiting with zero clicks (gated by FORGE_SCREEN_AUTO).
# This is the automation bridge — Scout finds + ranks, Marcus screens, hands-free.
def _auto_screen(rec):
    if not marcus_screening.AUTO_SCREEN:
        return
    def _run(cid=rec.get("contactId"), conv=rec.get("convId")):
        SCREENER.auto_screen(contact_id=cid, conv_id=conv)
        _ace_update_from_screening(cid)   # ACE P1: refresh conversation state off the screening
    threading.Thread(target=_run, daemon=True).start()
    agent_bus.send("scout", "marcus", "handoff",
                   f"🤝 Handed {rec.get('name') or 'a lead'} to Marcus for screening.",
                   {"contactId": rec.get("contactId"), "bucket": rec.get("bucket")})


SCOUT.on_scored = _auto_screen


# Tier 2 — work leads 24/7. Slow cadence loop: no-response bumps + due check-backs, both
# land as GATED proposals/flags (nothing auto-texts). Shares Scout/Screener/Marcus.
import followup  # noqa: E402
FOLLOWUP = followup.FollowupEngine(SCOUT, SCREENER, MARCUS, ghl_get, LOCATION_ID)


def api_followup_status(_q):
    return FOLLOWUP.status()


# Do Today — the operator's morning battle plan. Rebuilds + emails at 9 AM Eastern
# (do_today.RUN_HOUR / FORGE_TODAY_TZ); the dashboard checks items off. The digest
# email rides GHL (LeadConnector) to GHL_USER_EMAIL — no SMTP secrets on the box.
import do_today  # noqa: E402
DO_TODAY = do_today.DoTodayEngine(
    SCOUT, SCREENER, MARCUS, ghl_get, ghl_post, LOCATION_ID,
    _load_env(ENV_CANDIDATES).get("GHL_USER_EMAIL", ""),
    ghl_tasks_fn=lambda: api_tasks({"scan": ["60"]}))


def api_today(_q):
    return DO_TODAY.view()


# Legit-interest audit — agents read every tagged thread and demote the sellers who
# aren't actually interested (Scout bucket → dead, check-backs cleared). Runs in a
# thread (one Claude verdict per thread); GET returns the last report + running flag.
import legit_check  # noqa: E402
_LEGIT_RUNNING = {"on": False}


def api_audit_legit(_q):
    return {"running": _LEGIT_RUNNING["on"], "lastAudit": legit_check.last_audit()}


# Marcus as LEAD AGENT — surveys the whole operation, directs Scout + the operator.
import marcus_lead  # noqa: E402


def api_marcus_directives(_q):
    return marcus_lead.last()


def handle_marcus_directives_run(body):
    return marcus_lead.directives(SCOUT, SCREENER, MARCUS, DO_TODAY,
                                  trigger=body.get("trigger") or "manual")


# Atlas — the deal underwriter. Auto-preps every screened-interested seller (15-min
# sweep on the box): facts, offer anchors off the SELLER'S ask, MAO math, call card.
# Internal decision support only — Atlas never contacts anyone. Reports to Marcus.
import deal_prep  # noqa: E402
DEAL_PREP = deal_prep.DealPrep(SCOUT, SCREENER, ghl_get, LOCATION_ID)
deal_prep.INSTANCE = DEAL_PREP          # agents_chat's Atlas persona reads this
DO_TODAY.deal_prep = DEAL_PREP          # call tasks pick up the anchors as detail


def api_prep_list(_q):
    return DEAL_PREP.list_all()


def api_prep_get(q):
    cid = (q.get("contactId", [None]) or [None])[0]
    return DEAL_PREP.get(cid)


def api_prep_status(_q):
    return DEAL_PREP.status()


def handle_prep_run(body):
    cid = body.get("contactId")
    if cid:
        return DEAL_PREP.prep(cid, force=bool(body.get("force")))
    return DEAL_PREP.auto_prep_interested()


def handle_audit_legit_run(_body):
    if _LEGIT_RUNNING["on"]:
        return {"error": "audit already running"}

    def run():
        try:
            legit_check.audit_tagged(SCOUT, SCREENER)
        finally:
            _LEGIT_RUNNING["on"] = False
    _LEGIT_RUNNING["on"] = True
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "started": True}


# Tier 3 — deal record + DocuSign contracts. The deal record persists the Deal Calc (MAO
# stops evaporating) and feeds the contract; DocuSign sends it for e-signature (gated).
import deals          # noqa: E402
import docusign_io    # noqa: E402
import buyers         # noqa: E402  — cash-buyer list + buy-box match (dispo half)
import toolkit_calc   # noqa: E402  — Wholesaler Toolkit: calculator math + rates store
import toolkit_blast   # noqa: E402  — Wholesaler Toolkit: buyer blast (deal sheets + queue)
import toolkit_pipeline  # noqa: E402  — Wholesaler Toolkit: local reminder overlay
import toolkit_contracts  # noqa: E402  — Wholesaler Toolkit: sandbox contract approvals
import agents_history  # noqa: E402  — shared agent chat threads (dash + mobile + Telegram)
import daily_brief  # noqa: E402  — daily ops brief pushed to Telegram (run-from-anywhere)
import daily_recap  # noqa: E402  — evening end-of-day recap pushed to Telegram (close the loops)
import sync_monitor  # noqa: E402  — alert when a workstation falls behind on git auto-sync


def _deal_prefill(contact_id):
    """Assemble a deal sheet from the GHL contact + Marcus screening (best-effort)."""
    out = {}
    try:
        c = (ghl_get(f"/contacts/{contact_id}") or {}).get("contact", {}) or {}
        nm = (f"{c.get('firstName','')} {c.get('lastName','')}").strip() or c.get("name") or ""
        out["name"] = nm
        out["email"] = c.get("email") or ""
        out["phone"] = c.get("phone") or ""
        out["address"] = ", ".join([x for x in [c.get("address1"), c.get("city"),
                                                 c.get("state"), c.get("postalCode")] if x])
    except Exception:
        pass
    try:
        s = SCREENER.screenings.get(contact_id) or {}
        rep = s.get("report") or {}
        if s.get("convId"):
            out["convId"] = s.get("convId")
        if rep.get("askingPrice"):
            out["asking"] = rep["askingPrice"]
        if rep.get("propertyStatus"):
            out["propertyStatus"] = rep["propertyStatus"]
        if rep.get("conditionNotes"):
            out["condition"] = rep["conditionNotes"]
    except Exception:
        pass
    return out


def api_deals_list(_q):
    return {"deals": deals.list_deals()}


def api_deals_get(q):
    cid = (q.get("contactId", [None]) or [None])[0]
    if not cid:
        return {"error": "contactId required"}
    d = deals.get(cid)
    if not d:                       # no saved deal yet — return a prefilled draft
        d = dict(_deal_prefill(cid), contactId=cid, contractStatus="none")
    return {"deal": d}


def api_toolkit_blast_list(_q):
    return {"blasts": toolkit_blast.list_blasts(), "live": toolkit_blast.live_enabled()}


def api_toolkit_blast_get(q):
    bid = (q.get("id", [None]) or [None])[0]
    b = toolkit_blast.get_blast(bid) if bid else None
    return {"blast": b} if b else {"error": "blast not found"}


def _blast_deal(contact_id):
    """Assemble the deal dict the blast engine + matcher consume (saved record
    over prefill draft)."""
    d = deals.get(contact_id) or dict(_deal_prefill(contact_id), contactId=contact_id)
    d.setdefault("contactId", contact_id)
    return d


def api_toolkit_blast_matches(q):
    cid = (q.get("contactId", [None]) or [None])[0]
    if not cid:
        return {"error": "contactId required"}
    d = _blast_deal(cid)
    matches = buyers.match(d, limit=25)
    return {"deal": d, "sheet": toolkit_blast.build_sheet(d, toolkit_blast.list_photos(cid)),
            "matches": matches, "buyerCount": len(buyers.list_buyers())}


def _pipeline_deal(deal_id):
    """Read the current GHL card or saved deal for the reminder overlay only.

    This intentionally has no GHL write path: Phase 3 reminders are local operator
    state, while the pipeline endpoint remains the source of truth for cards/stages.
    """
    key = str(deal_id or "").strip()
    if not key:
        return {}
    saved = deals.get(key)
    if saved:
        return saved
    try:
        _pls, opportunities = _opp_view()
        for opp in opportunities:
            if key in (str(opp.get("id") or ""), str(opp.get("contactId") or "")):
                out = dict(opp)
                out["updatedAt"] = opp.get("updated")
                return out
    except Exception:
        pass
    return {"contactId": key}


def api_toolkit_pipeline_reminders(q):
    status = (q.get("status", [None]) or [None])[0]
    return {"reminders": toolkit_pipeline.list_reminders(status=status)}


def api_toolkit_pipeline_reminder(q):
    deal_id = (q.get("dealId", [None]) or [None])[0]
    return {"reminder": toolkit_pipeline.get_reminder(deal_id) if deal_id else None}


def api_toolkit_pipeline_days_in_stage(q):
    deal_id = (q.get("dealId", [None]) or [None])[0]
    if not deal_id:
        return {"error": "dealId required"}
    return {"dealId": deal_id,
            "days": toolkit_pipeline.days_in_stage(_pipeline_deal(deal_id))}


def api_toolkit_contracts_list(q):
    status = (q.get("status", [None]) or [None])[0]
    return {"contracts": toolkit_contracts.list_contracts(status=status)}


def api_toolkit_contracts_templates(_q):
    return {"templates": toolkit_contracts.template_list()}


def api_toolkit_contracts_status(q):
    deal_id = (q.get("dealId", [None]) or [None])[0]
    if not deal_id:
        return {"error": "dealId required"}
    return toolkit_contracts.refresh_contract_status(deal_id)


def api_toolkit_contracts_mytemplates(_q):
    return toolkit_contracts.list_uploaded_templates()


def api_agents_history(q):
    agent_id = (q.get("agentId", ["marcus"]) or ["marcus"])[0]
    limit = (q.get("limit", ["60"]) or ["60"])[0]
    return agents_history.history(agent_id, limit)


def api_toolkit_calc_config(_q):
    return toolkit_calc.config()


def api_buyers_list(_q):
    return {"buyers": buyers.list_buyers()}


def api_buyers_match(q):
    """Rank cash buyers for a deal. contactId -> the deal (saved or prefilled draft)."""
    cid = (q.get("contactId", [None]) or [None])[0]
    deal = (deals.get(cid) if cid else None) or (
        dict(_deal_prefill(cid), contactId=cid) if cid else {})
    return {"matches": buyers.match(deal), "deal": deal}


def api_buyers_dispo(_q):
    """Deals that have a buyer-shaped need (under contract / closing / has an offer),
    each with its top buyer matches — the dispo worklist."""
    out = []
    for d in deals.list_deals():
        stage = (d.get("stage") or "").lower()
        cs = (d.get("contractStatus") or "none").lower()
        needs = ("contract" in stage or "closing" in stage or "won" in stage
                 or cs in ("sent", "delivered", "completed") or d.get("offer"))
        if not needs:
            continue
        m = buyers.match(d, limit=5)
        out.append({"deal": d, "matches": m,
                    "assignedBuyerId": d.get("assignedBuyerId"),
                    "topFit": next((x for x in m if x["fits"]), None)})
    return {"dispo": out, "buyerCount": len(buyers.list_buyers())}


def handle_buyers_upsert(body):
    bid = body.get("id")
    fields = {k: v for k, v in body.items() if k != "id"}
    return {"ok": True, "buyer": buyers.upsert(bid, **fields)}


def handle_buyers_remove(body):
    bid = body.get("id")
    if not bid:
        return {"error": "id required"}
    return buyers.remove(bid)


def handle_buyers_assign(body):
    """Operator picks the buyer for a deal (dispo). Reversible — just writes the link
    onto the deal record; no outward action. Pass buyerId='' to unassign."""
    cid = body.get("contactId")
    if not cid:
        return {"error": "contactId required"}
    bid = body.get("buyerId") or ""
    b = buyers.get(bid) if bid else None
    if bid and not b:
        return {"error": "buyer not found"}
    if b:
        deals.upsert(cid, assignedBuyerId=bid, assignedBuyerName=b.get("name"))
    else:
        deals.unset(cid, "assignedBuyerId", "assignedBuyerName")
    if b:
        try:
            agent_bus.send("scout", "all", "note",
                           f"🤝 Deal {body.get('name') or cid} assigned to buyer {b.get('name')}.",
                           {"type": "deal_assigned", "contactId": cid, "buyerId": bid})
        except Exception:
            pass
    return {"ok": True, "deal": deals.get(cid)}


def api_contract_config(_q):
    return docusign_io.config_status()


def api_contract_status(q):
    return docusign_io.envelope_status((q.get("envelopeId", [None]) or [None])[0])


def handle_deals_save(body):
    cid = body.get("contactId")
    if not cid:
        return {"error": "contactId required"}
    deals.save_calc(cid, arv=body.get("arv"), repairs=body.get("repairs"),
                    fee=body.get("fee"), pct=body.get("pct"), asking=body.get("asking"),
                    mao=body.get("mao"), offer=body.get("offer"))
    addr = body.get("address") or ", ".join(
        [x for x in [body.get("property_street"), body.get("property_city"),
                     body.get("property_zip")] if x]) or None
    extra = {k: body.get(k) for k in ("name", "email", "phone", "convId", "stage",
                                      "propertyStatus", "condition", "beds", "baths", "sqft")
             if body.get(k)}
    if addr:
        extra["address"] = addr
    r = deals.upsert(cid, **extra) if extra else deals.get(cid)
    return {"ok": True, "deal": r}


def handle_deals_upsert(body):
    cid = body.get("contactId")
    if not cid:
        return {"error": "contactId required"}
    fields = {k: v for k, v in body.items() if k not in ("contactId", "prefill")}
    if body.get("prefill"):
        pf = _deal_prefill(cid)
        pf.update({k: v for k, v in fields.items() if v not in (None, "")})
        fields = pf
    return {"ok": True, "deal": deals.upsert(cid, **fields)}


def handle_contract_send(body):
    """Gated: operator clicks 'Send Contract' → DocuSign envelope to the seller's email.
    The one-click IS the approval (propose→review→execute). Inert until DocuSign is set up."""
    cid = body.get("contactId")
    if not cid:
        return {"error": "contactId required"}
    if not docusign_io.configured():
        return {"error": "DocuSign not connected", "config": docusign_io.config_status()}
    # Idempotency: don't fire a SECOND legally-binding envelope on a re-click/retry.
    existing = deals.get(cid)
    if (existing and existing.get("contractStatus") in ("sent", "delivered", "completed")
            and not body.get("force")):
        return {"error": "a contract was already sent for this lead",
                "envelopeId": existing.get("contractEnvelopeId"),
                "hint": "pass force:true to send another"}
    d = deals.get(cid) or dict(_deal_prefill(cid), contactId=cid)
    email = (body.get("email") or d.get("email") or "").strip()
    name = body.get("seller_name") or body.get("name") or d.get("name")
    if not email:
        return {"error": "no seller email on file — DocuSign signs via email"}
    # Map each dashboard form field -> the template's anchor tabLabel(s). One field can
    # fill several spots (seller name also fills the print-name line, etc.).
    MAP = {
        "seller_name": ["seller", "sprint"], "seller_phone": ["sphone"], "email": ["semail"],
        "buyer_name": ["buyer", "buyerco"], "buyer_signer": ["buyerby", "buyerprint"],
        "buyer_title": ["buyertitle"], "property_street": ["street"], "property_city": ["city"],
        "property_zip": ["zip"], "county": ["county"], "parcel": ["ppn"],
        "purchase_price": ["price"], "earnest_money": ["emd"], "closing_date": ["closedate"],
        "closing_year": ["closeyear"], "title_company": ["tco"], "title_address": ["taddr"],
        "title_officer": ["tofficer"], "title_email": ["temail"],
    }
    src = dict(body)
    src["email"] = email
    src["seller_name"] = body.get("seller_name") or name or ""
    src["buyer_name"] = body.get("buyer_name") or os.environ.get(
        "FORGE_BUYER_ENTITY", "A Touch of Blessings Home Buyers LLC")
    if not src.get("property_street") and not body.get("property_address") and d.get("address"):
        src["property_street"] = d.get("address")
    tabs = {}
    for ui, labels in MAP.items():
        v = src.get(ui)
        if v in (None, ""):
            continue
        for lab in labels:
            tabs[lab] = str(v)
    tabs.update(body.get("tabs") or {})
    # Persist the contract terms onto the deal record so the pipeline/stats see them.
    addr = ", ".join([x for x in [src.get("property_street"), src.get("property_city"),
                                  src.get("property_zip")] if x]) or d.get("address")
    deals.upsert(cid, email=email, name=src["seller_name"], address=addr,
                 county=body.get("county"), parcel=body.get("parcel"),
                 purchasePrice=body.get("purchase_price"), earnestMoney=body.get("earnest_money"),
                 closingDate=body.get("closing_date"), titleCompany=body.get("title_company"),
                 titleOfficer=body.get("title_officer"), titleEmail=body.get("title_email"))
    res = docusign_io.send_contract(email, src["seller_name"], tabs=tabs, email_subject=body.get("subject"))
    if not isinstance(res, dict):
        return {"error": "DocuSign send failed: empty response"}
    if res.get("ok"):
        deals.unset(cid, "pipelineSyncSkippedAt", "pipelineSyncSkipReason")
        deals.set_contract(cid, "sent", envelope_id=res.get("envelopeId"),
                           sent_at=int(time.time() * 1000))
        deals.upsert(cid, stage="Under Contract")
        sync = _sync_deal_pipeline(cid, "contract", name=src["seller_name"])
        res["pipelineSync"] = sync
        if not sync.get("ok"):
            res["warning"] = "Contract sent; GHL pipeline sync is pending retry."
        try:
            agent_bus.send("marcus", "all", "note",
                           f"📄 Contract sent to {name or email} for e-signature.",
                           {"type": "contract_sent", "contactId": cid,
                            "envelopeId": res.get("envelopeId")})
        except Exception:
            pass
    return res


def handle_contract_retry(body):
    """Clear a terminal DocuSign poll pause after an operator repairs a deal."""
    cid = body.get("contactId")
    if not cid:
        return {"error": "contactId required"}
    deals.unset(cid, "contractPollPausedAt", "contractPollPausedReason", "contractPollError")
    if body.get("envelopeId"):
        deals.upsert(cid, contractEnvelopeId=str(body.get("envelopeId")).strip())
    return {"ok": True, "deal": deals.get(cid)}


_CONTRACT_MONITOR = {"lastRun": None, "lastError": None}


def _sync_deal_pipeline(contact_id, kind, value=None, name=None):
    """Persist a retryable record of a GHL deal-stage synchronization attempt."""
    now = int(time.time() * 1000)
    prefix = {"offer": "offer", "contract": "contract", "closed": "closed"}.get(kind)
    if not prefix:
        return {"error": f"unknown lifecycle kind '{kind}'"}
    try:
        result = SCOUT.advance_opp(contact_id, kind, value=value, name=name)
    except Exception as e:  # noqa: BLE001
        result = {"error": str(e)}
    if result.get("ok"):
        deals.upsert(contact_id, **{
            f"{prefix}PipelineSyncedAt": now,
            f"{prefix}PipelineStage": result.get("stage"),
        })
        deals.unset(contact_id, f"{prefix}PipelineSyncError",
                    f"{prefix}PipelineSyncFailedAt")
    else:
        deals.upsert(contact_id, **{
            f"{prefix}PipelineSyncError": result.get("error") or "unknown GHL sync error",
            f"{prefix}PipelineSyncFailedAt": now,
        })
    return result


def _terminal_contract_error(error):
    """Whether DocuSign says the envelope cannot be polled again as-is."""
    text = str(error or "").lower()
    return ("404" in text or "not found" in text or "does not exist" in text
            or "no rights" in text or "no access" in text)


def _contract_poll_once():
    """Close the loop: check open DocuSign envelopes; when a seller actually signs
    (status 'completed') mark the deal + advance the GHL opp to Closed/Won (value =
    assignment fee) so deal_stats counts it. Signature-driven + reversible — a factual
    sync of a real external event, not an autonomous outward action."""
    if forge_ops.paused():               # clocked out — pause the signature poll too
        return {"ok": False, "paused": True, "checked": 0}
    if not docusign_io.configured():
        return {"ok": False, "configured": False, "checked": 0}
    checked = 0
    synced = 0
    errors = []
    for dd in deals.list_deals():
        local_status = (dd.get("contractStatus") or "none").lower()
        if local_status not in ("sent", "delivered", "completed"):
            continue
        env = dd.get("contractEnvelopeId")
        cid = dd.get("contactId")
        if not cid:
            continue
        # Hold terminal lookup failures until an operator repairs/replaces the
        # envelope through /api/contract/retry.
        if dd.get("contractPollPausedAt"):
            continue
        checked += 1
        if local_status == "completed":
            status = "completed"
        else:
            if not env:
                deals.upsert(cid, contractPollError="missing DocuSign envelope id")
                errors.append("missing DocuSign envelope id")
                continue
            st = docusign_io.envelope_status(env)
            if st.get("error"):
                err = str(st.get("error"))[:300]
                if _terminal_contract_error(err):
                    deals.upsert(cid, contractPollError=err,
                                 contractPollPausedAt=int(time.time() * 1000),
                                 contractPollPausedReason=err)
                else:
                    deals.upsert(cid, contractPollError=err)
                    errors.append(f"DocuSign status: {err}")
                continue
            deals.unset(cid, "contractPollError")
            status = (st.get("status") or "").lower()
            if not status:
                continue

        sync_skipped = bool(dd.get("pipelineSyncSkippedAt"))
        if (status in ("sent", "delivered") and not sync_skipped
                and not dd.get("contractPipelineSyncedAt")):
            sync = _sync_deal_pipeline(cid, "contract", name=dd.get("name"))
            synced += int(bool(sync.get("ok")))
            if not sync.get("ok"):
                errors.append(f"contract pipeline sync: {sync.get('error')}")

        if status == "completed":
            first_completion = local_status != "completed"
            if first_completion:
                deals.set_contract(cid, "completed")
            deals.upsert(cid, stage="Closed / Won")
            current = deals.get(cid) or dd
            if (not current.get("pipelineSyncSkippedAt")
                    and not current.get("closedPipelineSyncedAt")):
                sync = _sync_deal_pipeline(
                    cid, "closed", value=dd.get("assignmentFee"), name=dd.get("name"))
                synced += int(bool(sync.get("ok")))
                if not sync.get("ok"):
                    errors.append(f"closed pipeline sync: {sync.get('error')}")
            current = deals.get(cid) or current
            if first_completion and not current.get("closedAlertedAt"):
                try:
                    agent_bus.send("scout", "all", "alert",
                                   f"✅ Deal closed — {dd.get('name') or cid} signed the contract.",
                                   {"type": "deal_closed", "contactId": cid,
                                    "envelopeId": env})
                    deals.upsert(cid, closedAlertedAt=int(time.time() * 1000))
                except Exception:
                    pass
        elif status in ("delivered", "declined", "voided") and status != local_status:
            deals.set_contract(cid, status)
    _CONTRACT_MONITOR["lastRun"] = int(time.time() * 1000)
    _CONTRACT_MONITOR["lastError"] = "; ".join(errors[:3]) or None
    return {"ok": not errors, "configured": True, "checked": checked,
            "synced": synced, "errors": len(errors)}


def _contract_poll_forever():
    time.sleep(90)
    while True:
        try:
            _contract_poll_once()
        except Exception as e:  # noqa: BLE001
            _CONTRACT_MONITOR["lastRun"] = int(time.time() * 1000)
            _CONTRACT_MONITOR["lastError"] = str(e)
        _poll = int(os.environ.get("FORGE_CONTRACT_POLL", "600"))
        forge_heartbeat.beat("contract", _poll, "Contract poller",
                             error=_CONTRACT_MONITOR.get("lastError"))
        time.sleep(_poll)


_WATCHDOG_STATE = {}   # loop -> last status we alerted on (transition-based dedupe)


def _watchdog_forever():
    """The thing that watches the watchers. Every FORGE_WATCHDOG_SEC it reads the heartbeat
    snapshot and fires a SINGLE Telegram + bus alert the moment a loop transitions INTO red
    (stale or error-streak), plus one 🟢 recovery when it climbs back out. Transition-based
    so it alerts once per outage, not every tick. Quiet on a UI-only Mac and while the crew
    is clocked out. Never raises out."""
    if not LOOPS_ENABLED:
        return
    time.sleep(120)   # let the loops take their first beats before judging them
    every = max(60, int(os.environ.get("FORGE_WATCHDOG_SEC", "300")))
    while True:
        try:
            if forge_ops.paused():          # clocked out — everything is intentionally idle
                time.sleep(every)
                continue
            for l in forge_heartbeat.snapshot():
                loop = l.get("loop")
                status = l.get("status")
                prev = _WATCHDOG_STATE.get(loop)
                if status == "red" and prev != "red":
                    why = ("stale — no heartbeat in "
                           f"{int(l.get('ageSec') or 0)}s" if l.get("stale")
                           else f"errors x{l.get('errStreak')}")
                    err = l.get("lastError")
                    txt = (f"🔴 {l.get('label') or loop} is DOWN ({why})."
                           + (f" Last error: {err}" if err else ""))
                    try:
                        telegram_io.send(txt, dedupe_key=f"watchdog:{loop}")
                    except Exception:
                        pass
                    try:
                        agent_bus.send("watchdog", "all", "alert", txt,
                                       {"type": "loop_down", "loop": loop,
                                        "status": status})
                    except Exception:
                        pass
                elif status != "red" and prev == "red":
                    txt = f"🟢 {l.get('label') or loop} recovered — heartbeat is fresh again."
                    try:
                        telegram_io.send(txt, dedupe_key=f"watchdog-ok:{loop}")
                    except Exception:
                        pass
                    try:
                        agent_bus.send("watchdog", "all", "note", txt,
                                       {"type": "loop_up", "loop": loop})
                    except Exception:
                        pass
                _WATCHDOG_STATE[loop] = status
        except Exception:
            pass
        try:
            forge_heartbeat.beat("watchdog", every, "Watchdog")
        except Exception:
            pass
        time.sleep(every)


def _gather_brief_stats():
    """Assemble the daily-brief numbers from the live engines. Best-effort — any
    piece that errors is simply omitted, never blocks the brief."""
    stats = {"date": daily_brief.date_label()}
    try:
        d = api_dashboard(None) or {}
        stats["replies"] = d.get("activeConversations")
        stats["openOpps"] = d.get("openOpportunities")
        stats["pipelineValue"] = d.get("pipelineValue")
        stats["appointments"] = d.get("appointments")
    except Exception:
        pass
    try:
        counts = (SCOUT.summary() or {}).get("counts") or {}
        stats["hot"] = counts.get("asap")
        stats["warm"] = counts.get("warm")
    except Exception:
        pass
    try:
        stats["approvals"] = len(MARCUS.proposals_list())
    except Exception:
        pass
    try:
        leads = (SCOUT.leads("asap") or {}).get("leads") or []
        stats["topLeads"] = [{"name": l.get("name"), "last": l.get("lastMessage")}
                             for l in leads[:3]]
    except Exception:
        pass
    try:
        import cost_tracker
        stats["spendLine"] = cost_tracker.digest_line()
    except Exception:
        pass
    try:
        stats["staleAgents"] = [l.get("label") or l.get("loop")
                                for l in forge_heartbeat.snapshot()
                                if l.get("status") == "red"]
    except Exception:
        pass
    return stats


def _maybe_daily_brief(force=False):
    """Send the brief if due (or forced). Only marks-sent on a real send or when
    Telegram is simply not configured, so a transient failure retries next cycle."""
    if not force and not daily_brief.due():
        return {"sent": False, "reason": "not due"}
    stats = _gather_brief_stats()
    text = daily_brief.build_text(stats)
    sent, note = False, ""
    try:
        res = telegram_io.send(text, dedupe_key="daily_brief:" + daily_brief.today_key())
        if isinstance(res, dict) and (res.get("ok") or res.get("skipped")):
            sent = True
        else:
            note = (res or {}).get("error") if isinstance(res, dict) else "send failed"
    except Exception as e:  # noqa: BLE001
        note = str(e)
    # Mark the day done on a real send, or when there's no bot to send through
    # (don't hammer a missing config every cycle). Transient errors stay unmarked.
    if sent or (note and "not configured" in note):
        daily_brief.mark_sent()
    return {"sent": sent, "text": text, "note": note, "stats": stats}


def _maybe_daily_recap(force=False):
    """Evening companion to _maybe_daily_brief — send the end-of-day recap if due (or
    forced). Reuses the same brief stats (open loops + spend), same mark-sent discipline."""
    if not force and not daily_recap.due():
        return {"sent": False, "reason": "not due"}
    stats = _gather_brief_stats()
    text = daily_recap.build_text(stats)
    sent, note = False, ""
    try:
        res = telegram_io.send(text, dedupe_key="daily_recap:" + daily_recap.today_key())
        if isinstance(res, dict) and (res.get("ok") or res.get("skipped")):
            sent = True
        else:
            note = (res or {}).get("error") if isinstance(res, dict) else "send failed"
    except Exception as e:  # noqa: BLE001
        note = str(e)
    if sent or (note and "not configured" in note):
        daily_recap.mark_sent()
    return {"sent": sent, "text": text, "note": note, "stats": stats}


def _maybe_ceo_brief():
    """Once a day (after FORGE_MISSION_BRIEF_HOUR), Orion synthesizes the cross-business
    'attack today' brief so the dashboard greets the owner with it. One paid Claude call
    per day; opening the dashboard reads the cached brief for free. Optional Telegram push
    via FORGE_MISSION_BRIEF_TELEGRAM=1. Never raises."""
    try:
        res = ORION.maybe_daily(scout=SCOUT, solomon=SOLOMON, midas=MIDAS, screener=SCREENER)
        if (res.get("ok") and not res.get("skipped") and res.get("brief")
                and os.environ.get("FORGE_MISSION_BRIEF_TELEGRAM", "0") == "1"):
            b = res["brief"]
            lines = ["🧭 <b>Orion — today's focus</b>", "", "<b>" + str(b.get("headline", "")) + "</b>"]
            if b.get("idea"):
                lines += ["", "💡 " + str(b["idea"])]
            for p in (b.get("priorities") or [])[:3]:
                lines.append(f"• [{p.get('business','?')}] {p.get('title','')}")
            try:
                telegram_io.send("\n".join(lines), dedupe_key="ceo_brief:" + time.strftime("%Y-%m-%d"))
            except Exception:
                pass
        return res
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:160]}


def _brief_scheduler_forever():
    """Box-only daily clock for BOTH the morning brief and the evening recap. Checks every
    few minutes; each send is guarded by its own due() (past the set hour, once per day).
    Quiet while clocked out."""
    if not LOOPS_ENABLED:
        return
    time.sleep(90)
    every = max(60, int(os.environ.get("FORGE_BRIEF_CHECK_SEC", "300")))
    while True:
        try:
            if not forge_ops.paused():
                _maybe_daily_brief()
                _maybe_daily_recap()
                _maybe_ceo_brief()
                # Watch for a workstation whose git auto-sync stalled (self-rate-limited
                # to FORGE_SYNC_CHECK_MIN; pings Telegram once per fresh<->stale flip).
                sync_monitor.check_and_alert()
        except Exception:
            pass
        try:
            forge_heartbeat.beat("daily_brief", every, "Daily brief")
        except Exception:
            pass
        time.sleep(every)


def _tg_handoff(conv_id):
    """Telegram '🤝 Hand to Marcus' → Marcus screens the lead AND drafts a reply, then
    the draft comes straight back to Telegram as an ✅ Approve / 🗑 Dismiss proposal —
    the operator's tap stays the gate. Runs on a worker thread (two Claude calls take
    ~30s and must never stall the Telegram poll loop)."""
    SCOUT.note_handoff(conv_id, "marcus")

    def run():
        scr_line = ""
        try:
            scr = SCREENER.screen(conv_id=conv_id)
            rep = ((scr or {}).get("screening") or {}).get("report") or {}
            if rep:
                scr_line = (f"🩺 Screened {rep.get('score', '?')}/10 · "
                            f"{rep.get('interest', '?')} · {rep.get('stage', '')}")
            elif isinstance(scr, dict) and scr.get("error"):
                scr_line = f"⚠ screening: {scr['error']}"
        except Exception as e:  # noqa: BLE001
            scr_line = f"⚠ screening failed: {e}"
        try:
            res = MARCUS.make_proposal_for(conv_id)
            if isinstance(res, dict) and res.get("error"):
                # Cold thread (our message is last) → deliberate re-engage draft.
                res = MARCUS.make_proposal_for(conv_id, hint=(
                    "Scout handed this lead to you. Draft a short re-engage in the "
                    "operator's voice that picks the conversation back up — reference "
                    "what the seller actually said, no generic follow-up."))
            prop = None
            if isinstance(res, dict) and res.get("ok"):
                prop = next((p for p in MARCUS.proposals_list()
                             if p.get("conversationId") == conv_id
                             and p.get("status") == "pending"), None)
            if prop:
                # Push the draft straight back with the approve gate — don't rely on
                # the bus alert (it tier-filters + dedupes and could swallow this one).
                telegram_io.send(
                    f"🤝 <b>{prop.get('name') or 'Lead'}</b> — Marcus took the handoff.\n"
                    f"{scr_line}\n\n"
                    f"Seller said: “{(prop.get('inbound') or '')[:200]}”\n"
                    f"✍️ Draft: “{(prop.get('suggestedReply') or '')[:400]}”",
                    buttons=[
                        [{"text": "✅ Approve & send", "callback_data": f"approve:{prop['id']}"}],
                        [{"text": "\U0001f5d1 Dismiss", "callback_data": f"mdismiss:{prop['id']}"}],
                    ],
                    dedupe_key=f"handoff_draft:{prop['id']}")
            else:
                err = (res or {}).get("error") if isinstance(res, dict) else res
                telegram_io.send(f"🤝 Marcus took the handoff.\n{scr_line}\n"
                                 f"⚠ couldn't draft a reply: {err}")
        except Exception as e:  # noqa: BLE001
            telegram_io.send(f"🤝 Handoff hit an error: {e}")
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "message": "Marcus is on it — screening + drafting now"}


import telegram_ops  # noqa: E402
import autopilot      # noqa: E402
import skill_forge    # noqa: E402

# skill_forge listens to every bus broadcast (cross-agent pattern detection).
agent_bus.register_notifier(skill_forge.on_bus_message)

telegram_io.set_actions({
    "approve": lambda pid: MARCUS.approve(pid),
    "mdismiss": lambda pid: MARCUS.dismiss(pid),
    "handoff": _tg_handoff,
    "scoutdismiss": lambda cid: SCOUT.dismiss(cid),
    # skill_forge proposal taps: adopt into the vault / dismiss.
    "skillgo": skill_forge.approve,
    "skillno": skill_forge.dismiss,
    # ACE thread controls: stop/undo hold the thread (decide() checks held first);
    # ack marks a call-ready lead HANDED_OFF — the operator owns it from here.
    "acestop": lambda cid: ace.hold(cid, CONVO, reason="operator stop tap"),
    "aceundo": lambda cid: ace.hold(cid, CONVO, reason="operator undo tap"),
    "aceack": lambda cid: ace.ack(cid, CONVO),
    # Remote-control confirm gates: ✅ fires the queued outward send, ❌ drops it.
    "opsgo": telegram_ops.confirm,
    "opsno": telegram_ops.cancel,
    # Clock the agent crew out / in from a Telegram button tap.
    "opspause": lambda _a=None: forge_ops.set_paused(True),
    "opsresume": lambda _a=None: forge_ops.set_paused(False),
    # Agency edit requests: a new client request → tap to have Dyson draft a plan,
    # or dismiss it. Dyson's plan → tap to approve+ship (runs agency_deploy) or reject.
    "dysonplan": lambda rid: agency_dyson.generate_draft(rid),
    "reqdismiss": lambda rid: agency_requests_io.set_status(
        rid, "rejected", "Dismissed from Telegram"),
    "dysongo": lambda did: agency_dyson.decision(did, "approve"),
    "dysonno": lambda did: agency_dyson.decision(did, "reject"),
})


def _stage_key(v):
    return "".join(ch for ch in str(v or "").lower() if ch.isalnum())


def _tg_resolve_stage(stage):
    raw = (stage or "").strip()
    aliases = {
        "contract": scout_triage.DEAL_STAGE.get("contract"),
        "under contract": scout_triage.DEAL_STAGE.get("contract"),
        "undercontract": scout_triage.DEAL_STAGE.get("contract"),
        "offer": scout_triage.DEAL_STAGE.get("offer"),
        "offer made": scout_triage.DEAL_STAGE.get("offer"),
        "closed": scout_triage.DEAL_STAGE.get("closed"),
        "won": scout_triage.DEAL_STAGE.get("closed"),
    }
    target = scout_triage.STAGE_ALIASES.get(raw.lower()) or aliases.get(raw.lower()) or raw
    try:
        pid, stages, pname = SCOUT._resolve_pipeline()
    except Exception as e:  # noqa: BLE001
        return {"error": f"pipeline lookup failed: {e}"}
    stage_id = stages.get((target or "").lower())
    if not stage_id:
        keyed = {_stage_key(name): (name, sid) for name, sid in stages.items()}
        hit = keyed.get(_stage_key(target))
        if hit:
            target, stage_id = hit
    if not stage_id:
        partial = [(name, sid) for name, sid in stages.items()
                   if _stage_key(target) and _stage_key(target) in _stage_key(name)]
        if len(partial) == 1:
            target, stage_id = partial[0]
    if not stage_id:
        return {"error": f"stage '{raw}' not in {pname}", "stages": list(stages.keys())}
    return {"ok": True, "pipelineId": pid, "pipeline": pname,
            "stageId": stage_id, "stage": target, "input": raw}


def _tg_find_opportunities(contact_id):
    found = ghl_get("/opportunities/search",
                    {"location_id": LOCATION_ID, "contact_id": contact_id})
    return found.get("opportunities", []) or []


def _tg_move_stage(payload):
    if payload.get("opportunityId") and payload.get("stageId"):
        return handle_move_opportunity({
            "id": payload.get("opportunityId"),
            "stageId": payload.get("stageId"),
            "pipelineId": payload.get("pipelineId"),
        })
    if payload.get("convId"):
        return SCOUT.add_to_pipeline(payload.get("convId"), payload.get("stage"))
    return {"error": "no opportunity or Scout lead record to move"}


def _tg_tag_contact(payload):
    op = (payload.get("op") or "add").lower()
    if op == "remove":
        return SCOUT.remove_contact_tags(payload.get("contactId"), payload.get("tags") or [],
                                         name=payload.get("name"), conv_id=payload.get("convId"))
    return SCOUT.apply_contact_tags(payload.get("contactId"), payload.get("tags") or [],
                                    name=payload.get("name"), conv_id=payload.get("convId"))


# Remote control over Telegram — agents as employees. handle_send_post / SCREENER
# .send_nurture are the SAME gated send paths the dashboard buttons use; the
# operator's ✅ tap in Telegram is the review step (propose → review → execute).
telegram_ops.register({
    "scout": SCOUT, "screener": SCREENER, "marcus": MARCUS,
    "ghl_get": ghl_get, "location_id": LOCATION_ID,
    "do_today": DO_TODAY,
    "send_sms": lambda cid, msg, name=None: handle_send_post(
        {"contactId": cid, "message": msg, "name": name}),
    "send_nurture": lambda cid, msg: SCREENER.send_nurture(cid, msg),
    "claude_key": review_agent._api_key,
    "directives": lambda: marcus_lead.directives(SCOUT, SCREENER, MARCUS, DO_TODAY,
                                                 trigger="telegram"),
    # Autopilot — operator's kill switch + status for the auto-sent follow-up bumps.
    "autopilot_status": autopilot.status,
    "autopilot_set": autopilot.set_enabled,
    # Ops clock — the operator's clock-out/clock-in master switch for the whole crew.
    "ops_status": forge_ops.status,
    "ops_set": forge_ops.set_paused,
    "deal_prep": DEAL_PREP,                       # /prep — Atlas's deal cards
    "opportunities": lambda: _opp_view()[1],
    "find_opportunities": _tg_find_opportunities,
    "resolve_stage": _tg_resolve_stage,
    "move_stage": _tg_move_stage,
    "tag_contact": _tg_tag_contact,
    "telegram_send": telegram_io.send,
    "bus_send": agent_bus.send,
})


# Talk-to-your-agents over Telegram: route an inbound message to the agent chat brain.
# The turn lands in agents_history, so the dashboard/mobile Agents tab shows the SAME
# thread you see in Telegram (and vice versa).
def _tg_agent_chat(agent_id, message, history):
    try:
        # Always read the SHARED thread (dash + mobile + Telegram all record into
        # agents_history). Telegram's own in-memory session history would fork the
        # thread after its first exchange — ignore it unless the store is empty.
        # (Audit F3, 2026-07-11.)
        hist = agents_history.recent_for_context(agent_id) or history
        out = agents_chat.chat(ghl_get, LOCATION_ID, agent_id, message,
                               history=hist, scout=SCOUT, enable_commands=False)
        reply = (out or {}).get("reply", "") if isinstance(out, dict) else str(out or "")
        agents_history.record(agent_id, message, reply, via="telegram")
        return reply
    except Exception as e:  # noqa: BLE001
        return f"({(agent_id or 'agent').title()} couldn't answer: {e})"


telegram_io.register_agent_chat(_tg_agent_chat)


# Agency crew (Dyson/Eco) over Telegram: chat + /task queue (plan-only — the agency
# task board is approval-gated downstream, same as the dashboard; nothing goes live).
def _tg_agency_chat(agent_id, message, history):
    try:
        import agency_agents
        # agency_agents keeps its own persistent per-agent history — don't double-track
        # the telegram-local session history on this side.
        out = agency_agents.chat(agent_id, message)
        return (out or {}).get("reply", "") if isinstance(out, dict) else str(out or "")
    except Exception as e:  # noqa: BLE001
        return f"({(agent_id or 'agent').title()} couldn't answer: {e})"


def _tg_agency_task(agent_id, title):
    try:
        import agency_agents
        return agency_agents.send_task(agent_id, title) or {}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


telegram_io.register_agency_chat(_tg_agency_chat, _tg_agency_task)


def api_scout_summary(_q):
    return SCOUT.summary()


def api_scout_leads(q):
    bucket = (q.get("bucket", [None]) or [None])[0]
    return SCOUT.leads(bucket)


def api_scout_pipeline(_q):
    return SCOUT.pipeline_info()


def api_scout_overview(_q):
    return SCOUT.overview()


def api_scout_audit(_q):
    return SCOUT.audit_report()


def api_screening_queue(_q):
    return SCREENER.queue()


def api_screening_report(q):
    cid = (q.get("contactId", [None]) or [None])[0]
    return SCREENER.report(cid)


def api_screening_status(_q):
    return SCREENER.status()


def api_bus(q):
    limit = int((q.get("limit", ["50"]) or ["50"])[0])
    return agent_bus.recent(limit)


def api_notify_settings(_q):
    return telegram_io.settings()


def api_test_mode(_q):
    return test_mode.status()


def api_brief(_q):
    """Pull today's ops brief on demand (mobile/desktop): the config + a live
    preview of the exact text the scheduled Telegram push would send."""
    return {"ok": True, "config": daily_brief.config(),
            "text": daily_brief.build_text(_gather_brief_stats())}


def api_recap(_q):
    """Pull tonight's end-of-day recap on demand: config + live preview of the exact
    Telegram push. Reuses the brief stats (open loops + spend), evening framing."""
    return {"ok": True, "config": daily_recap.config(),
            "text": daily_recap.build_text(_gather_brief_stats())}


def api_sync_status(_q):
    """Read-only sync health: every workstation, how long since it last auto-synced,
    and whether it's stale. Powers a dashboard chip + confirms the box/PC are current."""
    return sync_monitor.status()


def api_sync_check(_q):
    """Force a sync check now (bypasses the rate-limit) and fire any pending Telegram
    stale/recovery alerts. Manual 'check now' from the dashboard."""
    return sync_monitor.check_and_alert(force=True)


# Daily grind auto-sync — count today's GHL activity (messages out, conversations,
# calls) and let Scout auto-tag any offers made today. Memoized 60s (heavy scan).
_ACT_FETCH_CAP = 80          # today-active threads we open for per-message detail
_ACT_CACHE = {"at": 0.0, "data": None}


def _act_ms(v):
    """Coerce GHL date (epoch-ms int/str or ISO-8601) to int ms; 0 on failure."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v)
    if s.isdigit():
        return int(s)
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:  # noqa: BLE001
        return 0


def _today_activity():
    now = time.time()
    if _ACT_CACHE["data"] is not None and now - _ACT_CACHE["at"] < 60:
        return _ACT_CACHE["data"]
    today = time.strftime("%Y-%m-%d")
    try:
        day_start = int(time.mktime(time.strptime(today, "%Y-%m-%d")) * 1000)
    except Exception:  # noqa: BLE001
        day_start = int(now * 1000) - 86_400_000
    try:
        data = ghl_get("/conversations/search",
                       {"locationId": LOCATION_ID, "limit": 100,
                        "sortBy": "last_message_date", "sort": "desc"})
    except Exception:  # noqa: BLE001
        return {"messages": 0, "conversations": 0, "calls": 0}
    convos = data.get("conversations", []) or []
    todays = [c for c in convos if _act_ms(c.get("lastMessageDate")) >= day_start]
    conv_count = len(todays)

    def work(c):
        cid = c.get("id")
        contact = c.get("contact") or {}
        contact_id = c.get("contactId") or contact.get("id")
        name = c.get("fullName") or c.get("contactName") or contact.get("name") or ""
        mo = ca = 0
        offer_msgs = []
        try:
            raw = ghl_get(f"/conversations/{cid}/messages", {"limit": 100})
        except Exception:  # noqa: BLE001
            return (0, 0)
        rawm = raw.get("messages", raw) if isinstance(raw, dict) else raw
        if isinstance(rawm, dict):
            rawm = rawm.get("messages", [])
        for m in (rawm or []):
            dms = _act_ms(m.get("dateAdded") or m.get("date"))
            if dms < day_start:
                continue
            direction = m.get("direction")
            mtype = (m.get("messageType") or m.get("type") or "").upper()
            if "CALL" in mtype:
                if direction == "outbound":
                    ca += 1
            elif direction == "outbound":
                mo += 1
            offer_msgs.append({"direction": direction, "body": m.get("body") or "", "date": dms})
        try:
            SCOUT.scan_thread_offer(contact_id, name, offer_msgs, day_start)
        except Exception:  # noqa: BLE001
            pass   # offer auto-tag is best-effort; never break the count
        return (mo, ca)

    msgs_out = calls = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for mo, ca in ex.map(work, todays[:_ACT_FETCH_CAP]):
            msgs_out += mo
            calls += ca
    out = {"messages": msgs_out, "conversations": conv_count, "calls": calls}
    _ACT_CACHE["at"], _ACT_CACHE["data"] = now, out
    return out


def api_goals_today(_q):
    """Daily non-negotiables — auto-filled from live GHL activity (manual bump still
    wins as a floor). Offers are auto-tagged + counted by Scout."""
    try:
        counts = _today_activity()
        counts["offers"] = SCOUT.offers_today()
        return daily_goals.apply_auto(counts)
    except Exception:  # noqa: BLE001
        return daily_goals.get()


# JV deal = won opp whose name/stage/pipeline/contact-tags contain this keyword.
JV_KW = os.environ.get("FORGE_JV_KEYWORD", "jv").lower()


def api_deal_stats(_q):
    """Lifetime + month deal stats, derived live from GHL opportunities."""
    pls, opps = _opp_view()
    return deal_stats.compute(opps, pls, JV_KW, time.strftime("%Y-%m"))


def api_goals_monthly(_q):
    return monthly_goals.get()


def api_agency_clients(_q):
    return agency_io.list_clients()


def api_agency_stats(_q):
    return agency_io.stats()


# Agency's OWN GoHighLevel sub-account (separate creds, separate module).
def api_agency_health(_q):
    return agency_ghl.health(AGENCY)


def api_agency_ghl_dashboard(_q):
    return agency_ghl.dashboard(AGENCY)


def api_agency_ghl_contacts(q):
    limit = int((q.get("limit", ["50"]) or ["50"])[0])
    query = (q.get("query", [None]) or [None])[0]
    return agency_ghl.contacts(AGENCY, limit=limit, query=query)


def api_agency_ghl_pipeline(_q):
    return agency_ghl.pipeline(AGENCY)


def api_agency_ghl_tags(_q):
    return agency_ghl.list_tags(AGENCY)


# --- Agency feature modules (edit requests, Dyson, n8n, ads, Eco, approvals) -
def api_agency_requests(_q):
    return agency_requests_io.list_requests()


# The public origin the operator shares with clients. Defaults to the Tailscale
# HTTPS name; override with FORGE_PORTAL_BASE once a public funnel host is set.
PORTAL_BASE = os.environ.get(
    "FORGE_PORTAL_BASE", "https://forge-reios.tail0a2dda.ts.net").rstrip("/")


def api_agency_portal_links(_q):
    """Admin: a shareable client-portal link for every client (mints tokens lazily)."""
    return agency_portal_io.links_for_all(base=PORTAL_BASE)


# --- Client portal (public-safe: only ever touches ONE token-scoped client) ---
def api_portal_bootstrap(q):
    cid = (q.get("c", [None]) or [None])[0]
    token = (q.get("k", [None]) or [None])[0]
    return agency_portal_io.bootstrap(cid, token)


def api_agency_dyson_drafts(_q):
    return agency_dyson.list_drafts()


def api_agency_workflows(_q):
    return agency_workflows_io.list_workflows()


def api_agency_build_list(_q):
    """Blueprint Studio: every idea turned into a build-ready plan (newest first)."""
    return agency_build_studio.list_blueprints()


def api_agency_ads(q):
    account = (q.get("account", [None]) or [None])[0]
    client = (q.get("client", [None]) or [None])[0]
    days = int((q.get("days", ["7"]) or ["7"])[0])
    return agency_ads.analytics(account=account, client=client, days=days)


def api_agency_ads_accounts(_q):
    return agency_ads.accounts()


def api_agency_eco(q):
    account = (q.get("account", [None]) or [None])[0]
    client = (q.get("client", [None]) or [None])[0]
    return agency_eco.recommendations(account=account, client=client)


def api_agency_approvals(q):
    status = (q.get("status", [None]) or [None])[0]
    return agency_approvals_io.list_queue(status=status)


def api_agency_calls(_q):
    return agency_calls.summary()


# Operable AI agents (Dyson, Eco) — Anthropic-backed, chat + tasks.
def api_agency_agents(_q):
    return agency_agents.status()


def api_agency_agents_history(q):
    agent = (q.get("agent", [None]) or [None])[0]
    return agency_agents.history(agent)


def api_agency_agents_tasks(q):
    agent = (q.get("agent", [None]) or [None])[0]
    return agency_agents.list_tasks(agent)


# Social (Instagram + TikTok via Metricool — brand forgelabsx).
def api_agency_social(_q):
    return agency_social.connection()


def api_agency_social_besttime(q):
    return agency_social.best_time((q.get("network", [None]) or [None])[0])


def api_agency_social_posts(q):
    return agency_social.list_posts((q.get("network", [None]) or [None])[0])


def api_agency_social_analytics(q):
    return agency_social.analytics((q.get("network", [None]) or [None])[0])


# --- Deploy status (M4 — agency_deploy owned by Lane E) ----------------------
def api_agency_deploy_status(q):
    client_id = (q.get("clientId", [None]) or [None])[0]
    return agency_deploy.status(client_id)


# --- Agency settings (M5 — get only; save is POST below) --------------------
def api_agency_settings(_q):
    return agency_io.get_settings()


ROUTES = {
    "/api/sync": api_sync,
    "/api/health": api_health,
    "/api/system/health": api_system_health,
    "/api/mission-control": api_mission_control,
    "/api/mission-control/brief": lambda q: ORION.cached_brief(),
    "/api/mission-control/brief/overview": lambda q: ORION.overview(),
    "/api/ace/state": api_ace_state,
    "/api/ace/status": api_ace_status,
    "/api/cost/status": api_cost_status,
    "/api/spend/status": api_spend_status,
    "/api/skillforge/pending": api_skillforge_pending,
    "/api/ace/callready": api_ace_callready,
    "/api/ace/digest": api_ace_digest,
    "/api/contacts": api_contacts,
    "/api/conversations": api_conversations,
    "/api/messages": api_messages,
    "/api/pipeline": api_pipeline,
    "/api/tasks": api_tasks,
    "/api/dashboard": api_dashboard,
    "/api/marcus/status": api_marcus_status,
    "/api/marcus/proposals": api_marcus_proposals,
    "/api/analytics": api_analytics,
    "/api/brain/tree": api_brain_tree,
    "/api/brain/note": api_brain_note,
    "/api/brain/search": api_brain_search,
    "/api/brain/recent": api_brain_recent,
    "/api/brain/status": api_brain_status,
    "/api/brain/graph": api_brain_graph,
    "/api/brain/activity": api_brain_activity,
    "/api/graphify/graph": api_graphify_graph,
    "/api/graphify/search": api_graphify_search,
    "/api/graphify/stats": api_graphify_stats,
    "/api/graphify/build": api_graphify_build_status,
    "/api/review/latest": api_review_latest,
    "/api/style/latest": api_style_latest,
    "/api/outbound/status": api_outbound_status,
    "/api/outbound/calls": api_outbound_calls,
    "/api/outbound/agent": api_outbound_agent,
    "/api/outbound/voices": api_outbound_voices,
    "/api/agents/list": api_agents_list,
    "/api/hub/roster": api_hub_roster,
    "/api/hub/tasks": api_hub_tasks,
    "/api/hub/bus": api_hub_bus,
    "/api/hub/history": api_hub_history,
    "/api/coach/feed": api_coach_feed,
    "/api/scout/summary": api_scout_summary,
    "/api/scout/leads": api_scout_leads,
    "/api/scout/pipeline": api_scout_pipeline,
    "/api/scout/overview": api_scout_overview,
    "/api/scout/audit": api_scout_audit,
    "/api/screening/queue": api_screening_queue,
    "/api/screening/report": api_screening_report,
    "/api/screening/status": api_screening_status,
    "/api/followup/status": api_followup_status,
    "/api/today": api_today,
    "/api/audit/legit": api_audit_legit,
    "/api/marcus/directives": api_marcus_directives,
    "/api/prep/list": api_prep_list,
    "/api/prep/get": api_prep_get,
    "/api/prep/status": api_prep_status,
    "/api/deals/list": api_deals_list,
    "/api/deals/get": api_deals_get,
    "/api/toolkit/blast/list": api_toolkit_blast_list,
    "/api/toolkit/blast/get": api_toolkit_blast_get,
    "/api/toolkit/blast/matches": api_toolkit_blast_matches,
    "/api/toolkit/pipeline/reminders": api_toolkit_pipeline_reminders,
    "/api/toolkit/pipeline/reminder": api_toolkit_pipeline_reminder,
    "/api/toolkit/pipeline/days-in-stage": api_toolkit_pipeline_days_in_stage,
    "/api/toolkit/contracts/list": api_toolkit_contracts_list,
    "/api/toolkit/contracts/templates": api_toolkit_contracts_templates,
    "/api/toolkit/contracts/status": api_toolkit_contracts_status,
    "/api/toolkit/contracts/mytemplates": api_toolkit_contracts_mytemplates,
    "/api/agents/history": api_agents_history,
    "/api/brief": api_brief,
    "/api/recap": api_recap,
    "/api/sync/status": api_sync_status,
    "/api/sync/check": api_sync_check,
    "/api/toolkit/calc/config": api_toolkit_calc_config,
    "/api/buyers/list": api_buyers_list,
    "/api/buyers/match": api_buyers_match,
    "/api/buyers/dispo": api_buyers_dispo,
    "/api/contract/config": api_contract_config,
    "/api/contract/status": api_contract_status,
    "/api/bus": api_bus,
    "/api/notify/settings": api_notify_settings,
    "/api/ops/status": api_ops_status,
    "/api/test-mode": api_test_mode,
    "/api/goals/today": api_goals_today,
    "/api/goals/monthly": api_goals_monthly,
    "/api/deals/stats": api_deal_stats,
    "/api/agency/clients": api_agency_clients,
    "/api/agency/stats": api_agency_stats,
    "/api/agency/health": api_agency_health,
    "/api/agency/ghl/dashboard": api_agency_ghl_dashboard,
    "/api/agency/ghl/contacts": api_agency_ghl_contacts,
    "/api/agency/ghl/pipeline": api_agency_ghl_pipeline,
    "/api/agency/ghl/tags": api_agency_ghl_tags,
    "/api/agency/requests": api_agency_requests,
    "/api/agency/portal/links": api_agency_portal_links,
    "/api/portal/bootstrap": api_portal_bootstrap,
    "/api/agency/dyson/drafts": api_agency_dyson_drafts,
    "/api/agency/workflows": api_agency_workflows,
    "/api/agency/build/list": api_agency_build_list,
    "/api/agency/ads": api_agency_ads,
    "/api/agency/ads/accounts": api_agency_ads_accounts,
    "/api/agency/eco": api_agency_eco,
    "/api/agency/approvals": api_agency_approvals,
    "/api/agency/calls": api_agency_calls,
    "/api/agency/agents": api_agency_agents,
    "/api/agency/agents/history": api_agency_agents_history,
    "/api/agency/agents/tasks": api_agency_agents_tasks,
    "/api/agency/social": api_agency_social,
    "/api/agency/social/besttime": api_agency_social_besttime,
    "/api/agency/social/posts": api_agency_social_posts,
    "/api/agency/social/analytics": api_agency_social_analytics,
    "/api/agency/deploy/status": api_agency_deploy_status,
    "/api/agency/settings": api_agency_settings,
}

# Marcus endpoints are real-time — never serve them from the 45s cache.
# (retell_io keeps its own 30s cache, so /api/outbound/* skip the connector cache.)
NO_CACHE = {"/api/sync", "/api/health", "/api/system/health", "/api/mission-control", "/api/mission-control/brief", "/api/ace/state", "/api/ace/status",
            "/api/cost/status", "/api/spend/status", "/api/skillforge/pending",
            "/api/hub/roster", "/api/hub/tasks", "/api/hub/bus", "/api/hub/history",
            "/api/coach/feed", "/api/sync/status", "/api/sync/check",
            "/api/ace/callready", "/api/ace/digest",
            "/api/contacts", "/api/conversations", "/api/messages",
            "/api/pipeline", "/api/tasks", "/api/dashboard", "/api/analytics",
            "/api/marcus/status", "/api/marcus/proposals", "/api/review/latest",
            "/api/brain/tree", "/api/brain/note", "/api/brain/search",
            "/api/brain/recent", "/api/brain/status", "/api/brain/graph",
            "/api/graphify/graph", "/api/graphify/search", "/api/graphify/stats",
            "/api/graphify/build",
            "/api/outbound/agent", "/api/outbound/voices", "/api/agents/list",
            "/api/followup/status", "/api/today", "/api/audit/legit",
            "/api/marcus/directives",
            "/api/prep/list", "/api/prep/get", "/api/prep/status",
            "/api/deals/list", "/api/deals/get", "/api/contract/config", "/api/contract/status",
            "/api/toolkit/calc/config",
            "/api/toolkit/blast/list", "/api/toolkit/blast/get", "/api/toolkit/blast/matches",
            "/api/toolkit/pipeline/reminders", "/api/toolkit/pipeline/reminder",
            "/api/toolkit/pipeline/days-in-stage",
            "/api/toolkit/contracts/list", "/api/toolkit/contracts/templates",
            "/api/toolkit/contracts/status", "/api/toolkit/contracts/mytemplates",
            "/api/agents/history", "/api/brief", "/api/recap",
            "/api/buyers/list", "/api/buyers/match", "/api/buyers/dispo",
            "/api/outbound/status", "/api/outbound/calls",
            "/api/brain/activity", "/api/style/latest", "/api/goals/today",
            "/api/goals/monthly", "/api/deals/stats",
            "/api/agency/clients", "/api/agency/stats", "/api/agency/health",
            "/api/agency/ghl/dashboard", "/api/agency/ghl/contacts",
            "/api/agency/ghl/pipeline",
            "/api/agency/requests", "/api/agency/portal/links",
            "/api/portal/bootstrap", "/api/agency/dyson/drafts",
            "/api/agency/build/list",
            "/api/agency/workflows", "/api/agency/ads", "/api/agency/ads/accounts",
            "/api/agency/eco", "/api/agency/approvals", "/api/agency/calls",
            "/api/agency/agents", "/api/agency/agents/history",
            "/api/agency/agents/tasks", "/api/agency/social",
            "/api/agency/social/besttime", "/api/agency/social/posts",
            "/api/agency/social/analytics", "/api/agency/ghl/tags",
            "/api/agency/deploy/status", "/api/agency/settings",
            "/api/scout/summary", "/api/scout/leads", "/api/scout/pipeline",
            "/api/scout/overview", "/api/scout/audit", "/api/bus",
            "/api/screening/queue", "/api/screening/report", "/api/screening/status",
            "/api/notify/settings", "/api/ops/status", "/api/test-mode"}


def _get_or_create_conversation(contact_id):
    data = ghl_get("/conversations/search",
                   {"locationId": LOCATION_ID, "contactId": contact_id})
    convos = data.get("conversations", []) or []
    if convos:
        return convos[0]["id"]
    new = ghl_post("/conversations/",
                   {"locationId": LOCATION_ID, "contactId": contact_id})
    return (new.get("conversation", {}) or {}).get("id") or new.get("id")


def _blast_transport(recipient, sheet):
    """GHL-native buyer send (PLAN.md Open Decision #1 resolved: GHL).

    Fires only from an operator-approved blast AND only when FORGE_BLAST_LIVE=1
    (toolkit_blast gates both). SMS only for v1 — GHL email needs a configured
    location mailbox, so email recipients are skipped, not failed. Buyers are
    upserted into GHL tagged `buyer` so replies land in the mirrored convos.
    TCPA quiet hours block buyer texts the same as seller texts.
    """
    if recipient.get("channel") != "sms":
        return {"ok": False, "skipped": True,
                "note": "email transport not wired (GHL SMS only)"}
    phone = (recipient.get("phone") or "").strip()
    message = (recipient.get("smsDraft") or "").strip()
    if not phone:
        return {"ok": False, "skipped": True, "note": "no phone on file"}
    if not message:
        return {"ok": False, "skipped": True, "note": "empty draft"}
    if not sms_guard._within_hours():
        return {"ok": False, "note": "outside 9am-8pm ET send window"}
    up = ghl_post("/contacts/upsert", {
        "locationId": LOCATION_ID, "phone": phone,
        "name": recipient.get("name") or "Cash Buyer", "tags": ["buyer"],
    })
    contact_id = (up.get("contact") or {}).get("id") or up.get("id")
    if not contact_id:
        return {"ok": False, "note": "GHL contact upsert failed"}
    conv_id = _get_or_create_conversation(contact_id)
    if not conv_id:
        return {"ok": False, "note": "could not open GHL conversation"}
    ghl_post("/conversations/messages", {
        "type": "SMS", "conversationId": conv_id,
        "contactId": contact_id, "message": message,
    })
    return {"ok": True, "note": "sent via GHL SMS"}


toolkit_blast.register_transport(_blast_transport)


def handle_send_post(body):
    """Send an SMS to a contact from the lead drawer. Human-initiated."""
    contact_id = body.get("contactId")
    message = (body.get("message") or "").strip()
    if not contact_id or not message:
        return {"error": "contactId and message required"}
    conv_id = body.get("convId") or body.get("conversationId") or _get_or_create_conversation(contact_id)
    if not conv_id:
        return {"error": "could not open conversation"}
    kind = body.get("kind") or "manual"
    gate = sms_guard.guard(contact_id, message, conv_id=conv_id, name=body.get("name"),
                           scout=SCOUT, kind=kind,
                           autonomous=bool(body.get("autonomous")))
    if not gate.get("ok"):
        return gate
    reservation = gate.get("reservation")
    try:
        res = ghl_post("/conversations/messages", {
            "type": "SMS",
            "conversationId": conv_id,
            "contactId": contact_id,
            "message": message,
        })
    except Exception as e:  # noqa: BLE001
        sms_guard.release(reservation)
        return {"error": str(e), "gate": "ghl_send"}
    try:
        sms_guard.record_success(reservation=reservation, conv_id=conv_id,
                                 contact_id=contact_id, message=message, kind=kind,
                                 last_message_date=body.get("lastMessageDate") or 0)
    except Exception:
        pass
    # If this send was a cash offer, tag it + advance the opp to the offer stage. The
    # operator clicking send IS the approval. detect_offer is conservative ($ amount + an
    # offer phrase), so an ordinary drawer text won't trigger a move.
    lifecycle = None
    now = int(time.time() * 1000)
    offer_msgs = [{"direction": "outbound", "body": message, "date": now}]
    if SCOUT.detect_offer(offer_msgs):
        try:
            SCOUT.scan_thread_offer(contact_id, body.get("name"), offer_msgs)
        except Exception as e:  # noqa: BLE001
            lifecycle = {"error": f"offer tag sync failed: {e}"}
        deals.upsert(contact_id, name=body.get("name"), stage="Offer Made")
        lifecycle = _sync_deal_pipeline(
            contact_id, "offer", name=body.get("name"))
    out = {"ok": True, "conversationId": conv_id, "result": res}
    if lifecycle is not None:
        out["pipelineSync"] = lifecycle
        if not lifecycle.get("ok"):
            out["warning"] = "Message sent; GHL offer-stage sync needs review."
    return out


def handle_reply_draft(body):
    """Speed-to-Lead: draft a text-back reply to a hot seller in the operator's voice.
    Read-only (no send) — reuses Marcus's voice-drafting (_ai_draft → wholesale-seller-texter
    + yahjair-voice, the 'response skill'). Returns the suggested SMS; operator edits + sends."""
    conv = body.get("convId") or body.get("conversationId") or body.get("id")
    name = body.get("name") or ""
    if not conv:
        return {"error": "no conversation for this lead yet"}
    try:
        msgs = SCOUT._thread_transcript(conv) or []
    except Exception as e:  # noqa: BLE001
        return {"error": f"couldn't read the thread: {e}"}
    inbound = [(m.get("body") or "").strip() for m in msgs
               if m.get("direction") == "inbound" and (m.get("body") or "").strip()]
    if not inbound:
        return {"error": "no seller message to reply to yet"}
    last_in = inbound[-1]
    # Never draft a reply to OUR own outreach mis-flagged as inbound (Rule #4).
    try:
        if marcus_engine._is_our_message(last_in):
            return {"error": "last inbound looks like our own outreach — nothing to reply to"}
    except Exception:  # noqa: BLE001
        pass
    try:
        cls = marcus_engine.classify(last_in)
    except Exception:  # noqa: BLE001
        cls = "CONTINUE"
    history = [("Seller: " if m.get("direction") == "inbound" else "Us: ")
               + (m.get("body") or "").strip()
               for m in msgs if (m.get("body") or "").strip()]
    first = (name or "").split(" ")[0] if name else ""
    try:
        text, source = MARCUS._ai_draft(first, cls, last_in, history, hint=body.get("hint"))
    except Exception as e:  # noqa: BLE001
        return {"error": f"draft failed: {e}"}
    return {"ok": True, "draft": text, "source": source, "classification": cls,
            "lastMessage": last_in}


def handle_reply_send(body):
    """Speed-to-Lead: send the (edited) text-back reply, record the touch WITH the thread's
    current lastMessageDate so Do Today suppresses this lead until the seller replies again,
    and check it off today's list. Operator clicking Send IS the approval (Rule #2)."""
    send_body = dict(body)
    send_body.setdefault("kind", "reply")
    res = handle_send_post(send_body)     # sends the SMS (+ offer detection) via the gated path
    if not res.get("ok"):
        return res
    conv = res.get("conversationId") or body.get("convId") or body.get("conversationId")
    try:
        import send_ledger
        send_ledger.record(conv, kind="reply",
                           last_message_date=body.get("lastMessageDate") or 0)
    except Exception:  # noqa: BLE001
        pass
    marked = False
    try:
        marked = DO_TODAY.mark_texted(body.get("contactId"))
    except Exception:  # noqa: BLE001
        pass
    res["texted"] = True
    res["markedDone"] = bool(marked)
    return res


def handle_move_opportunity(body):
    """Drag-and-drop: move an opportunity to a different pipeline stage in GHL.
    Dashboard -> GHL write. GHL -> dashboard is covered by the 30s poll + cache TTL."""
    opp_id = body.get("id")
    stage_id = body.get("stageId")
    pipeline_id = body.get("pipelineId")
    if not opp_id or not stage_id:
        return {"error": "id and stageId required"}
    payload = {"pipelineStageId": stage_id}
    if pipeline_id:
        payload["pipelineId"] = pipeline_id
    res = ghl_put(f"/opportunities/{opp_id}", payload)
    # Bust caches so the next read reflects the move immediately.
    for k in list(_CACHE.keys()):
        if k.startswith("/api/pipeline") or k.startswith("/api/dashboard"):
            _CACHE.pop(k, None)
    return {"ok": True, "id": opp_id, "stageId": stage_id, "result": res}


def handle_marcus_post(path, body):
    if path == "/api/marcus/approve":
        return MARCUS.approve(body.get("id"), body.get("message"))
    if path == "/api/marcus/dismiss":
        return MARCUS.dismiss(body.get("id"))
    if path == "/api/marcus/toggle":
        return MARCUS.toggle(body.get("enabled"), body.get("autoSend"),
                             body.get("autoSendNrn"))
    if path == "/api/marcus/poll":  # manual "check now"
        MARCUS.poll_once()
        return MARCUS.status()
    return None


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quieter logs
        pass

    def _client_disconnected(self, exc):
        return isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError))

    def handle(self):
        try:
            super().handle()
        except Exception as exc:  # noqa: BLE001
            if self._client_disconnected(exc):
                return
            raise

    def _send_json(self, obj, code=200, headers=None):
        payload = json.dumps(obj).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:  # noqa: BLE001
            if self._client_disconnected(exc):
                return
            raise

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/daycare/"):
            return self._handle_daycare_post(parsed.path)
        if parsed.path.startswith("/api/dropship/"):
            return self._handle_dropship_post(parsed.path)
        if not (parsed.path.startswith("/api/marcus/")
                or parsed.path in ("/api/send", "/api/review/run",
                                   "/api/reply/draft", "/api/reply/send",
                                   "/api/ace/mode",
                                   "/api/cost/manual", "/api/cost/settings",
                                   "/api/spend/save", "/api/spend/delete",
                                   "/api/skillforge/act", "/api/ace/ack", "/api/ace/hold",
                                   "/api/style/run", "/api/brain/undo",
                                   "/api/outbound/agent/update",
                                   "/api/outbound/agent/create",
                                   "/api/pipeline/move",
                                   "/api/marcus/chat",
                                   "/api/agents/chat",
                                   "/api/hub/chat",
                                   "/api/hub/task",
                                   "/api/hub/task/update",
                                   "/api/graphify/rebuild",
                                   "/api/coach/broadcast",
                                   "/api/coach/ask",
                                   "/api/goals/update",
                                   "/api/goals/monthly/update",
                                   "/api/today/check",
                                   "/api/today/run",
                                   "/api/audit/legit/run",
                                   "/api/marcus/directives/run",
                                   "/api/prep/run",
                                   "/api/prep/learn",
                                   "/api/mission-control/brief/run",
                                   "/api/mission-control/brief/learn",
                                   "/api/agency/client/save",
                                   "/api/agency/client/delete",
                                   "/api/agency/reset",
                                   "/api/agency/request/save",
                                   "/api/agency/request/delete",
                                   "/api/agency/request/status",
                                   "/api/agency/portal/token",
                                   "/api/portal/submit",
                                   "/api/agency/dyson/generate",
                                   "/api/agency/dyson/decision",
                                   "/api/agency/workflow/save",
                                   "/api/agency/workflow/decision",
                                   "/api/agency/build/generate",
                                   "/api/agency/build/delete",
                                   "/api/agency/build/status",
                                   "/api/agency/build/handoff",
                                   "/api/agency/eco/generate",
                                   "/api/agency/eco/decision",
                                   "/api/agency/eco/image",
                                   "/api/agency/approval/decision",
                                   "/api/agency/calls/log",
                                   "/api/agency/calls/undo",
                                   "/api/agency/calls/goal",
                                   "/api/agency/agents/chat",
                                   "/api/agency/agents/task",
                                   "/api/agency/agents/task/update",
                                   "/api/agency/agents/learn",
                                   "/api/agency/social/post/save",
                                   "/api/agency/social/post/status",
                                   "/api/agency/social/post/delete",
                                   "/api/agency/settings/save",
                                   "/api/agency/eco/competitor",
                                   "/api/agency/client/login",
                                   "/api/agency/ghl/tags/sync",
                                   "/api/agency/client/sync-ghl",
                                   "/api/scout/run",
                                   "/api/scout/apply",
                                   "/api/scout/dismiss",
                                   "/api/scout/remove",
                                   "/api/scout/pipeline",
                                   "/api/scout/learn",
                                   "/api/scout/backfill",
                                   "/api/scout/handoff",
                                   "/api/scout/audit/run",
                                   "/api/screening/run",
                                   "/api/screening/note",
                                   "/api/screening/stage",
                                   "/api/screening/send",
                                   "/api/screening/audit-not-ready",
                                   "/api/screening/learn",
                                   "/api/deals/save",
                                   "/api/deals/upsert",
                                   "/api/toolkit/calc/eval",
                                   "/api/toolkit/calc/rates",
                                   "/api/toolkit/calc/save",
                                   "/api/toolkit/blast/create",
                                   "/api/toolkit/blast/send",
                                   "/api/toolkit/blast/respond",
                                   "/api/toolkit/blast/recipient",
                                   "/api/toolkit/blast/photos",
                                   "/api/toolkit/pipeline/reminder/set",
                                   "/api/toolkit/pipeline/reminder/snooze",
                                   "/api/toolkit/pipeline/reminder/dismiss",
                                   "/api/toolkit/pipeline/reminder/send",
                                   "/api/toolkit/pipeline/reminder/update",
                                   "/api/toolkit/contracts/create",
                                   "/api/toolkit/contracts/send",
                                   "/api/toolkit/contracts/void",
                                   "/api/toolkit/contracts/mark-signed",
                                   "/api/toolkit/contracts/template/upload",
                                   "/api/toolkit/contracts/template/delete",
                                   "/api/toolkit/contracts/quicksend",
                                   "/api/toolkit/calc/arv",
                                   "/api/buyers/upsert",
                                   "/api/buyers/remove",
                                   "/api/buyers/assign",
                                   "/api/contract/send",
                                   "/api/contract/retry",
                                   "/api/notify/settings",
                                   "/api/notify/test",
                                   "/api/ops/set",
                                   "/api/brief/send",
                                   "/api/brief/config",
                                   "/api/recap/send",
                                   "/api/recap/config",
                                   "/api/test-mode")):
            return self._send_json({"error": "unknown endpoint"}, 404)
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except Exception:
            body = {}
        try:
            if parsed.path == "/api/send":
                result = handle_send_post(body)
            elif parsed.path == "/api/reply/draft":
                result = handle_reply_draft(body)
            elif parsed.path == "/api/reply/send":
                result = handle_reply_send(body)
            elif parsed.path == "/api/ace/mode":
                result = ace.set_mode(body.get("mode"))
            elif parsed.path == "/api/cost/manual":
                import cost_tracker
                result = cost_tracker.set_fixed(body.get("service"),
                                                body.get("monthlyUSD"),
                                                body.get("note", ""))
            elif parsed.path == "/api/cost/settings":
                import cost_tracker
                result = cost_tracker.set_settings(
                    sms_rate=body.get("smsRate"),
                    monthly_cap_usd=body.get("monthlyCapUSD"))
            elif parsed.path == "/api/spend/save":
                import spend_tracker
                result = spend_tracker.save_item(
                    item_id=body.get("id"), name=body.get("name"),
                    amount=body.get("amount"), cadence=body.get("cadence"),
                    business=body.get("business"), note=body.get("note"))
            elif parsed.path == "/api/spend/delete":
                import spend_tracker
                result = spend_tracker.delete_item(body.get("id"))
            elif parsed.path == "/api/ace/ack":
                result = ace.ack(body.get("convId"), CONVO)
            elif parsed.path == "/api/ace/hold":
                result = ace.hold(body.get("convId"), CONVO,
                                  reason=body.get("reason") or "dashboard stop")
            elif parsed.path == "/api/skillforge/act":
                _act = (body.get("action") or "").strip().lower()
                if _act == "approve":
                    result = skill_forge.approve(body.get("pid"))
                elif _act == "dismiss":
                    result = skill_forge.dismiss(body.get("pid"))
                else:
                    result = {"error": "action must be approve or dismiss"}
            elif parsed.path == "/api/review/run":
                result = review_agent.run(
                    lambda d=int(body.get("days", 30)): analytics_engine.build(
                        ghl_get, _opp_view, LOCATION_ID, days=d))
            elif parsed.path == "/api/style/run":
                result = style_agent.run(ghl_get, LOCATION_ID,
                                         days=int(body.get("days", 1)))
            elif parsed.path == "/api/brain/undo":
                result = brain_io.undo_note(body.get("path"))
            elif parsed.path == "/api/outbound/agent/update":
                result = retell_io.update_agent(body)
            elif parsed.path == "/api/outbound/agent/create":
                result = retell_io.create_starter_agent()
            elif parsed.path == "/api/pipeline/move":
                result = handle_move_opportunity(body)
            elif parsed.path == "/api/marcus/chat":
                _msg = body.get("message", "")
                _cmd = telegram_ops.handle_agent_command("marcus", _msg, source="dashboard")
                result = _cmd if _cmd else marcus_chat.chat(ghl_get, LOCATION_ID,
                                                            _msg,
                                                            days=int(body.get("days", 7)))
            elif parsed.path == "/api/agents/chat":
                result = agents_chat.chat(ghl_get, LOCATION_ID,
                                          body.get("agentId", "marcus"),
                                          body.get("message", ""),
                                          history=(body.get("history")
                                                   or agents_history.recent_for_context(
                                                       body.get("agentId", "marcus"))),
                                          scout=SCOUT)
                # Shared thread: the same history Telegram reads/writes.
                if isinstance(result, dict) and result.get("reply") and not result.get("needsKey"):
                    agents_history.record(body.get("agentId", "marcus"),
                                          body.get("message", ""),
                                          result.get("reply"), via="dash")
            elif parsed.path == "/api/hub/chat":
                # The Agents hub — same shared thread Telegram reads/writes, so a
                # conversation continues across the dashboard and your phone.
                _aid = body.get("agentId", "marcus")
                result = agents_hub.chat(ghl_get, LOCATION_ID, _aid,
                                         body.get("message", ""),
                                         history=(body.get("history")
                                                  or agents_history.recent_for_context(_aid)),
                                         scout=SCOUT)
                if isinstance(result, dict) and result.get("reply") and not result.get("needsKey"):
                    agents_history.record(_aid, body.get("message", ""),
                                          result.get("reply"), via="dash")
            elif parsed.path == "/api/hub/task":
                result = agents_hub.send_task(body.get("agentId"), body.get("title"),
                                              body.get("note", ""))
            elif parsed.path == "/api/hub/task/update":
                result = agents_hub.update_task(body.get("id"), body.get("status"))
            elif parsed.path == "/api/graphify/rebuild":
                # Rebuild the knowledge graph now (internal + read-only over the repo/
                # vault; writes only the graph file). Handy after a big code change.
                import graphify_build
                result = graphify_build.build_graph()
            elif parsed.path == "/api/coach/broadcast":
                # An agent shares a transferable INSIGHT (text) with a peer/business/all.
                result = agents_hub.coach_broadcast(body.get("from"), body.get("insight"),
                                                    body.get("to", "all"))
            elif parsed.path == "/api/coach/ask":
                # Agent-to-agent Q&A — routed through the hub chat bound to this GHL sub-
                # account (ghl_get + LOCATION_ID), exactly like /api/hub/chat.
                result = agents_hub.coach_ask(ghl_get, LOCATION_ID, body.get("from"),
                                              body.get("to"), body.get("question"))
            elif parsed.path == "/api/goals/update":
                result = daily_goals.update(
                    metric=body.get("metric"), delta=body.get("delta"),
                    value=body.get("value"), targets=body.get("targets"),
                    deal_closed=body.get("dealClosed"))
            elif parsed.path == "/api/goals/monthly/update":
                result = monthly_goals.update(body.get("op"), body.get("gid"), body.get("text"))
            elif parsed.path == "/api/today/check":
                result = DO_TODAY.check(body.get("id"), body.get("done", True))
            elif parsed.path == "/api/today/run":
                result = DO_TODAY.build(email=bool(body.get("email")))
            elif parsed.path == "/api/audit/legit/run":
                result = handle_audit_legit_run(body)
            elif parsed.path == "/api/marcus/directives/run":
                result = handle_marcus_directives_run(body)
            elif parsed.path == "/api/prep/run":
                result = handle_prep_run(body)
            elif parsed.path == "/api/prep/learn":
                result = DEAL_PREP.learn()
            elif parsed.path == "/api/mission-control/brief/run":
                result = ORION.build_brief(scout=SCOUT, solomon=SOLOMON,
                                           midas=MIDAS, screener=SCREENER)
            elif parsed.path == "/api/mission-control/brief/learn":
                result = ORION.learn()
            elif parsed.path == "/api/agency/client/save":
                result = agency_io.save_client(body.get("client") or body)
            elif parsed.path == "/api/agency/client/delete":
                result = agency_io.delete_client(body.get("id"))
            elif parsed.path == "/api/agency/reset":
                # Admin clean-slate: wipe ALL agency clients + edit requests + the
                # approval queue. No executor runs. Requires {"confirm": true}.
                if not (isinstance(body, dict) and body.get("confirm") is True):
                    result = {"ok": False, "error": "reset requires {\"confirm\": true}"}
                else:
                    result = {"ok": True,
                              "clients": agency_io.reset(),
                              "requests": agency_requests_io.reset(),
                              "approvals": agency_approvals_io.reset()}
            elif parsed.path == "/api/agency/request/save":
                result = agency_requests_io.save_request(body.get("request") or body)
            elif parsed.path == "/api/agency/request/delete":
                result = agency_requests_io.delete_request(body.get("id"))
            elif parsed.path == "/api/agency/request/status":
                result = agency_requests_io.set_status(
                    body.get("id"), body.get("status"), body.get("note"))
            elif parsed.path == "/api/agency/portal/token":
                # Admin: mint/return (or rotate) a client's portal link.
                if body.get("rotate"):
                    rot = agency_io.rotate_portal_token(body.get("clientId"))
                    if rot.get("error"):
                        result = rot
                    else:
                        result = agency_portal_io.link(body.get("clientId"), base=PORTAL_BASE)
                else:
                    result = agency_portal_io.link(body.get("clientId"), base=PORTAL_BASE)
            elif parsed.path == "/api/portal/submit":
                # PUBLIC client-portal submit — token-scoped to one client.
                result = agency_portal_io.submit(
                    body.get("c"), body.get("k"), body)
            elif parsed.path == "/api/agency/dyson/generate":
                result = agency_dyson.generate_draft(body.get("requestId"))
            elif parsed.path == "/api/agency/dyson/decision":
                result = agency_dyson.decision(
                    body.get("id"), body.get("action"), body.get("note"))
            elif parsed.path == "/api/agency/workflow/save":
                result = agency_workflows_io.save_draft(body.get("workflow") or body)
            elif parsed.path == "/api/agency/workflow/decision":
                result = agency_workflows_io.decision(
                    body.get("id") or body.get("workflowId"), body.get("action"))
            elif parsed.path == "/api/agency/build/generate":
                result = agency_build_studio.generate(body)
            elif parsed.path == "/api/agency/build/delete":
                result = agency_build_studio.delete_blueprint(body.get("id"))
            elif parsed.path == "/api/agency/build/status":
                result = agency_build_studio.set_status(body.get("id"), body.get("status"))
            elif parsed.path == "/api/agency/build/handoff":
                result = agency_build_studio.hand_off(body.get("id"))
            elif parsed.path == "/api/agency/eco/generate":
                result = agency_eco.generate(
                    account=body.get("account"), client=body.get("client"))
            elif parsed.path == "/api/agency/eco/decision":
                result = agency_eco.decision(body.get("id"), body.get("action"))
            elif parsed.path == "/api/agency/eco/image":
                result = agency_eco.generate_concept_image(
                    body.get("id"), body.get("conceptIndex", 0), body.get("prompt"))
            elif parsed.path == "/api/agency/approval/decision":
                result = agency_approvals_io.decide(
                    body.get("id"), body.get("action"))
            elif parsed.path == "/api/agency/calls/log":
                result = agency_calls.log_call(body.get("outcome"))
            elif parsed.path == "/api/agency/calls/undo":
                result = agency_calls.undo_last()
            elif parsed.path == "/api/agency/calls/goal":
                result = agency_calls.set_goal(body.get("goal"))
            elif parsed.path == "/api/agency/agents/chat":
                result = agency_agents.chat(
                    body.get("agentId"), body.get("message"), body.get("history"))
            elif parsed.path == "/api/agency/agents/task":
                result = agency_agents.send_task(
                    body.get("agentId"), body.get("title"))
            elif parsed.path == "/api/agency/agents/task/update":
                result = agency_agents.update_task(
                    body.get("id"), body.get("status"))
            elif parsed.path == "/api/agency/agents/learn":
                result = agency_agents.learn(body.get("agentId"))
            elif parsed.path == "/api/agency/social/post/save":
                result = agency_social.save_post(body.get("post") or body)
            elif parsed.path == "/api/agency/social/post/status":
                result = agency_social.set_status(body.get("id"), body.get("status"))
            elif parsed.path == "/api/agency/social/post/delete":
                result = agency_social.delete_post(body.get("id"))
            elif parsed.path == "/api/agency/settings/save":
                result = agency_io.save_settings(body.get("settings") or body)
            elif parsed.path == "/api/agency/eco/competitor":
                # M3: run competitor research for a client (triggers Claude analysis
                # or returns a placeholder when no key). Never throws.
                result = agency_eco.competitor_research(body.get("client"))
            elif parsed.path == "/api/agency/client/login":
                # M5 scaffold: client portal login (stub; real auth is a later milestone).
                result = agency_io.client_login(
                    body.get("email"), body.get("token"))
            elif parsed.path == "/api/agency/ghl/tags/sync":
                result = agency_ghl.ensure_service_tags(
                    AGENCY, body.get("services") or agency_io.SERVICES)
            elif parsed.path == "/api/agency/client/sync-ghl":
                _cl = agency_io.get_client(body.get("id"))
                if not _cl:
                    result = {"error": "client not found"}
                else:
                    _services = _cl.get("services") or []
                    _ens = agency_ghl.ensure_service_tags(AGENCY, _services)
                    _app = agency_ghl.apply_contact_tags(
                        AGENCY, _cl.get("ghlContactId"), _services)
                    _client_id = _cl.get("id") or body.get("id")
                    if _client_id:
                        agency_io.mark_ghl_synced(_client_id)
                    result = {"ok": True, "ensured": _ens, "applied": _app,
                              "services": _services}
            elif parsed.path == "/api/scout/run":
                result = SCOUT.run_once()
            elif parsed.path == "/api/scout/apply":
                result = SCOUT.apply_tags(body.get("id"))
            elif parsed.path == "/api/scout/dismiss":
                result = SCOUT.dismiss(body.get("id"))
            elif parsed.path == "/api/scout/remove":
                # "Not actually hot" — pull the Scout hot tags off the GHL contact and
                # mark its opportunity Lost, then drop it from triage. User-gated.
                result = SCOUT.remove_lead(body.get("id"))
            elif parsed.path == "/api/scout/pipeline":
                result = SCOUT.add_to_pipeline(body.get("id"), body.get("stage"))
            elif parsed.path == "/api/scout/learn":
                result = SCOUT.learn()
            elif parsed.path == "/api/scout/backfill":
                # Recovery: rebuild triage records for screened threads the sweep can't see
                # (we replied last → outbound-last → skipped forever). Read-only on GHL.
                result = SCOUT.backfill(SCREENER, limit=int(body.get("limit") or 80))
            elif parsed.path == "/api/scout/handoff":
                # Hand to Marcus = screen the lead (Marcus is the screening agent now).
                _conv = body.get("id")
                _cid = body.get("contactId")
                _info = SCOUT.note_handoff(_conv, "marcus")
                _m = SCREENER.screen(conv_id=_conv, contact_id=_cid or _info.get("contactId"))
                if _m.get("ok"):
                    try:
                        agent_bus.send("scout", "marcus", "handoff",
                                       f"Handed {_info['name']} to Marcus — screened for your review",
                                       {"conversationId": _conv, "contactId": _cid or _info.get("contactId"),
                                        "name": _info["name"]})
                    except Exception:
                        pass   # notification is best-effort; the screening already exists
                # Handoff also drafts a reply (gated) — same as the Telegram button. The
                # proposal lands in the approval inbox + fires its own bus/Telegram alert.
                try:
                    _pr = MARCUS.make_proposal_for(_conv, contact_id=_cid or _info.get("contactId"))
                    if isinstance(_pr, dict) and _pr.get("error"):
                        _pr = MARCUS.make_proposal_for(
                            _conv, contact_id=_cid or _info.get("contactId"),
                            hint=("Scout handed this lead to you. Draft a short re-engage "
                                  "in the operator's voice that picks the conversation "
                                  "back up — reference what the seller actually said."))
                    _m["draft"] = "ok" if (isinstance(_pr, dict) and _pr.get("ok")) else \
                        (_pr or {}).get("error")
                except Exception as _e:  # noqa: BLE001
                    _m["draft"] = str(_e)
                result = {**_m, "name": _info["name"]}
            elif parsed.path == "/api/scout/audit/run":
                try:
                    _ad = int(body.get("days", 7) or 7)
                except (ValueError, TypeError):
                    _ad = 7
                result = SCOUT.retro_audit(days=_ad, query=body.get("query"))
            elif parsed.path == "/api/screening/run":
                result = SCREENER.screen(contact_id=body.get("contactId"),
                                         conv_id=body.get("convId"))
                _ace_update_from_screening(body.get("contactId"))   # ACE P1: refresh state
            elif parsed.path == "/api/screening/note":
                result = SCREENER.note(body.get("contactId"), body.get("note"))
            elif parsed.path == "/api/screening/stage":
                result = SCREENER.set_stage(body.get("contactId"), body.get("stage"))
            elif parsed.path == "/api/screening/send":
                result = SCREENER.send_nurture(body.get("contactId"), body.get("message"))
            elif parsed.path == "/api/screening/audit-not-ready":
                result = SCREENER.audit_not_ready(body.get("days", 7))
            elif parsed.path == "/api/screening/learn":
                result = SCREENER.learn()
            elif parsed.path == "/api/toolkit/blast/create":
                _bd = _blast_deal(body.get("contactId"))
                result = toolkit_blast.create_blast(
                    _bd, buyers.match(_bd, limit=25),
                    channels=body.get("channels"), buyer_ids=body.get("buyerIds"))
            elif parsed.path == "/api/toolkit/blast/send":
                result = toolkit_blast.send_blast(body.get("id"))
            elif parsed.path == "/api/toolkit/blast/respond":
                result = toolkit_blast.record_response(
                    body.get("id"), body.get("buyerId"), body.get("verdict"))
            elif parsed.path == "/api/toolkit/blast/recipient":
                result = toolkit_blast.set_recipient(
                    body.get("id"), body.get("buyerId"),
                    **{k: body.get(k) for k in ("channel", "smsDraft", "emailSubject",
                                                "emailBody", "status", "note")
                       if body.get(k) is not None})
            elif parsed.path == "/api/toolkit/blast/photos":
                result = toolkit_blast.save_photos(body.get("dealId"), body.get("photos") or [])
            elif parsed.path == "/api/toolkit/pipeline/reminder/set":
                deal_id = body.get("dealId")
                deal = _pipeline_deal(deal_id)
                supplied = body.get("deal")
                if isinstance(supplied, dict):
                    deal = {**deal, **supplied}
                result = toolkit_pipeline.create_reminder(
                    deal_id, deal, body.get("dueAt"), body.get("draftMsg"))
            elif parsed.path == "/api/toolkit/pipeline/reminder/snooze":
                result = toolkit_pipeline.snooze_reminder(body.get("dealId"), body.get("untilMs"))
            elif parsed.path == "/api/toolkit/pipeline/reminder/dismiss":
                result = toolkit_pipeline.dismiss_reminder(body.get("dealId"))
            elif parsed.path == "/api/toolkit/pipeline/reminder/send":
                result = toolkit_pipeline.mark_sent(body.get("dealId"))
            elif parsed.path == "/api/toolkit/pipeline/reminder/update":
                result = toolkit_pipeline.update_reminder(
                    body.get("dealId"), draftMsg=body.get("draftMsg"), note=body.get("note"))
            elif parsed.path == "/api/toolkit/contracts/create":
                deal_id = body.get("dealId")
                deal = _blast_deal(deal_id) if deal_id else {}
                supplied = body.get("deal")
                if isinstance(supplied, dict):
                    deal = {**deal, **supplied}
                result = toolkit_contracts.create_contract(
                    deal_id, deal, body.get("templateType"),
                    approval_required=body.get("approvalRequired", True))
            elif parsed.path == "/api/toolkit/contracts/send":
                result = toolkit_contracts.send_contract(
                    body.get("dealId"), body.get("operatorId"), body.get("reason", ""))
            elif parsed.path == "/api/toolkit/contracts/void":
                result = toolkit_contracts.void_contract(body.get("dealId"), body.get("reason", ""))
            elif parsed.path == "/api/toolkit/contracts/mark-signed":
                result = toolkit_contracts.mark_signed(body.get("dealId"))
            elif parsed.path == "/api/toolkit/contracts/template/upload":
                result = toolkit_contracts.save_template(body.get("name"), body.get("file"))
            elif parsed.path == "/api/toolkit/contracts/template/delete":
                result = toolkit_contracts.delete_template(body.get("id"))
            elif parsed.path == "/api/toolkit/contracts/quicksend":
                result = toolkit_contracts.quick_send(body)
            elif parsed.path == "/api/toolkit/calc/eval":
                result = toolkit_calc.evaluate(body)
            elif parsed.path == "/api/toolkit/calc/rates":
                result = toolkit_calc.set_rates(body.get("rates") or {})
            elif parsed.path == "/api/toolkit/calc/save":
                result = toolkit_calc.save_snapshot(body)
            elif parsed.path == "/api/toolkit/calc/arv":
                result = toolkit_calc.find_arv(
                    body.get("address"), sqft=body.get("sqft"),
                    beds=body.get("beds"), baths=body.get("baths"))
            elif parsed.path == "/api/deals/save":
                result = handle_deals_save(body)
            elif parsed.path == "/api/deals/upsert":
                result = handle_deals_upsert(body)
            elif parsed.path == "/api/buyers/upsert":
                result = handle_buyers_upsert(body)
            elif parsed.path == "/api/buyers/remove":
                result = handle_buyers_remove(body)
            elif parsed.path == "/api/buyers/assign":
                result = handle_buyers_assign(body)
            elif parsed.path == "/api/contract/send":
                result = handle_contract_send(body)
            elif parsed.path == "/api/contract/retry":
                result = handle_contract_retry(body)
            elif parsed.path == "/api/notify/settings":
                result = telegram_io.save_settings(body)
            elif parsed.path == "/api/notify/test":
                result = telegram_io.send_test()
            elif parsed.path == "/api/ops/set":
                result = forge_ops.set_paused(bool(body.get("paused")))
            elif parsed.path == "/api/brief/send":
                result = _maybe_daily_brief(force=True)
            elif parsed.path == "/api/brief/config":
                result = daily_brief.set_config(enabled=body.get("enabled"),
                                                hour=body.get("hour"))
            elif parsed.path == "/api/recap/send":
                result = _maybe_daily_recap(force=True)
            elif parsed.path == "/api/recap/config":
                result = daily_recap.set_config(enabled=body.get("enabled"),
                                                hour=body.get("hour"))
            elif parsed.path == "/api/test-mode":
                result = test_mode.update(body)
            else:
                result = handle_marcus_post(parsed.path, body)
            if result is None:
                return self._send_json({"error": "unknown endpoint"}, 404)
            _touch_sync()
            return self._send_json(result)
        except urllib.error.HTTPError as e:
            # Mirror do_GET: read the GHL error body so a failed tag/pipeline/send
            # shows the real reason (e.g. "credit balance too low") instead of an
            # opaque "HTTP Error 400" once it bubbles to the operator.
            detail = getattr(e, "_detail", None) or _http_error_detail(e, limit=300)
            return self._send_json({"error": f"GHL {e.code}", "detail": detail}, 502)
        except Exception as e:  # noqa: BLE001
            return self._send_json({"error": str(e)}, 500)

    def _daycare_session_id(self):
        return daycare_supabase.session_id_from_cookie(self.headers.get("Cookie"))

    def _daycare_client_ip(self):
        return self.client_address[0] if self.client_address else None

    def _daycare_resolve_session(self, sid):
        """Return (session, set_cookie_or_None).

        Prefers a valid cookie session. On any failure (no cookie / expired), falls
        back to a loopback auto-admin session when enabled, emitting a Set-Cookie so
        the browser reuses it. If auto-admin does not apply, the original error is
        re-raised so non-loopback clients still get the normal 401 login flow.
        """
        try:
            return daycare_supabase.BRIDGE.require_session(sid), None
        except daycare_supabase.DaycareError as first_error:
            auto = daycare_supabase.BRIDGE.autoadmin_session(self._daycare_client_ip())
            if auto is None:
                raise first_error
            session = daycare_supabase.BRIDGE.require_session(auto.sid)
            return session, daycare_supabase.session_cookie(session.sid)

    def _daycare_require_secure(self):
        client_ip = self.client_address[0] if self.client_address else None
        if not daycare_supabase.request_is_secure(self.headers, client_ip):
            raise daycare_supabase.DaycareError(
                403, "Daycare access requires HTTPS", "https_required")

    def _read_daycare_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            raise daycare_supabase.DaycareError(
                400, "Invalid request body", "validation_error") from None
        if length < 0 or length > daycare_supabase.MAX_BODY_BYTES:
            raise daycare_supabase.DaycareError(
                400, "Request body is too large", "validation_error")
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise daycare_supabase.DaycareError(
                400, "Request body must be valid JSON", "validation_error") from None
        if not isinstance(body, dict):
            raise daycare_supabase.DaycareError(
                400, "Request body must be a JSON object", "validation_error")
        return body

    def _daycare_stripe_sync_payment(self, session, body):
        """Pull a Stripe invoice's paid status into the Supabase ledger (manual sync).

        Idempotent: the RPC keys on the Stripe invoice id, so repeated syncs of the
        same paid invoice never double-record.
        """
        ctx = daycare_supabase.stripe_invoice_context(session, body.get("invoice_id"))
        invoice = stripe_io.find_invoice(str(ctx["invoice_id"]))
        if not invoice:
            return {"ok": True, "sent": False, "synced": False,
                    "detail": "No Stripe invoice exists yet for this record."}
        if not invoice.get("paid"):
            return {"ok": True, "sent": True, "synced": False,
                    "status": invoice.get("status"),
                    "hostedInvoiceUrl": invoice.get("hosted_invoice_url")}
        amount_paid = (invoice.get("amount_paid") or 0) / 100.0
        stripe_id = invoice.get("id")
        daycare_supabase.record_invoice_payment(session, {
            "invoice_id": ctx["invoice_id"],
            "payment": {
                "amount": amount_paid,
                "method_label": "Stripe",
                "provider": "stripe",
                "provider_reference": stripe_id,
                "idempotency_key": f"stripe:{stripe_id}",
            },
        })
        return {"ok": True, "sent": True, "synced": True, "amountPaid": amount_paid,
                "status": invoice.get("status")}

    def _daycare_pending_families(self, session):
        """Families submitted through the public Family Contact Form (GHL), for the
        dashboard's "From Contact Form" inbox — organized by center.

        Read-only. Each family's GHL location tag is mapped to its Supabase center
        (`location_id` + `location_name`) so the inbox can group them by location. A
        family is flagged `in_roster` when a guardian with the same email already
        exists at the ACTIVE center (RLS scopes the roster to one center at a time, so
        dedup is only meaningful for the family's own center). Provisioning lands in the
        active center — the owner picks it with the location switcher — so switching to a
        center then creating a login keeps every family organized under the right one.
        """
        active = daycare_supabase.active_location(session)
        names = {}
        try:
            for loc in (daycare_supabase.list_locations(session) or {}).get("locations", []):
                names[str(loc.get("id"))] = loc.get("name")
        except daycare_supabase.DaycareError:
            pass
        families = daycare_ghl.pending_families(DAYCARE_GHL)
        emails = set()
        try:
            roster = (daycare_supabase.get_children(session) or {}).get("children") or []
            for child in roster:
                guardian = child.get("guardian") or child.get("guardian_profile") or {}
                mail = (guardian.get("auth_email") or "").strip().lower()
                if mail:
                    emails.add(mail)
        except daycare_supabase.DaycareError:
            pass
        for family in families:
            loc_id = DAYCARE_FORM_LOCATION_BY_TAG.get((family.get("location_tag") or "").lower())
            family["location_id"] = loc_id
            family["location_name"] = names.get(str(loc_id)) if loc_id else None
            mail = (family.get("email") or "").strip().lower()
            # Dedup only holds for the active center (RLS shows one center's roster),
            # and only for a brand-new website LEAD who already enrolled elsewhere —
            # a Family Contact Form submission being in the roster is the *expected*
            # case (that form is existing-student intake), not a reason to hide it.
            family["in_roster"] = bool(
                family.get("is_lead") and loc_id and str(loc_id) == str(active)
                and mail and mail in emails)
            family["dismissed"] = daycare_ghl.is_dismissed(family.get("contact_id"))
            # For families the owner can still provision, read the GHL intake note for the
            # bits the form keeps only there — authorized-pickup people + the freeform note —
            # so "Create login" carries them into the child's pickup_notes / medical_notes.
            # Bounded to actionable (not-yet-provisioned) families; the note fetch is skipped
            # for everything already in the roster.
            if (not family["in_roster"] and not family["dismissed"]
                    and family.get("enrolled") and family.get("contact_id")):
                intake = daycare_ghl.family_intake(DAYCARE_GHL, family["contact_id"])
                people = intake.get("authorized_pickup") or []
                if people:
                    base = family.get("pickup_notes") or ""
                    family["pickup_notes"] = (
                        base + ("\n" if base else "") + "Authorized pickup:\n"
                        + "\n".join("  - " + p for p in people)).strip()
                if intake.get("notes"):
                    family["medical_notes"] = intake["notes"]
                # Auto-enroll: every enrolled Contact-Form kid becomes a roster child
                # the moment it lands — internal + reversible (a deletable row), same
                # rule-2 class as the HOT-lead auto-tag. The parent LOGIN stays behind
                # the owner's Create-login button (no guardian is provisioned here).
                # Idempotent via the contact->child ledger; a failed attempt (e.g. no
                # DOB on the form) is left for the button. FORGE_DAYCARE_AUTOENROLL=0
                # reverts to button-only enrollment.
                child_id = daycare_ghl.form_child_id(family["contact_id"])
                if not child_id and os.environ.get("FORGE_DAYCARE_AUTOENROLL", "1") != "0":
                    try:
                        child_body = self._daycare_family_child_body(session, family)
                        # Adopt an already-enrolled kid (same name at the family's
                        # center) instead of inserting a duplicate row.
                        child_id = daycare_supabase.find_child_id(
                            session, family.get("location_id"),
                            child_body["first_name"], child_body["last_name"])
                        if not child_id:
                            saved = daycare_supabase.save_child(session, {"child": child_body})
                            child_id = ((saved or {}).get("child") or {}).get("id") or ""
                        if child_id:
                            daycare_ghl.record_form_child(family["contact_id"], child_id)
                    except Exception:  # noqa: BLE001 — auto-enroll must never break the inbox
                        child_id = ""
                family["child_id"] = child_id
        return {"ok": True, "families": families,
                "connected": bool(DAYCARE_GHL.configured),
                "active_location_id": active}

    def _daycare_ghl_text_invoice(self, session, body):
        """Text a family their invoice / payment link via the daycare GHL account.

        Owner-initiated (the console button IS the approval gate). Sends the Stripe
        hosted payment link when the invoice was sent through Stripe, otherwise a
        plain balance reminder. Never autonomous.
        """
        ctx = daycare_supabase.stripe_invoice_context(session, body.get("invoice_id"))
        guardian = ctx.get("guardian") or {}
        phone = guardian.get("phone")
        if not phone:
            return {"ok": False, "detail": "This family has no phone number on file."}
        link = ""
        try:
            invoice = stripe_io.find_invoice(str(ctx["invoice_id"])) if stripe_io.configured() else None
            if invoice:
                link = invoice.get("hosted_invoice_url") or ""
        except Exception:  # noqa: BLE001 — a missing link must not block the text
            link = ""
        custom = (body.get("message") or "").strip()
        if custom:
            message = custom + (("\n\nPay here: " + link) if link else "")
        else:
            amount = "$" + format(float(ctx.get("amount") or 0), ".2f")
            number = ctx.get("invoice_number") or "your invoice"
            message = (f"Hi {guardian.get('name','')}, this is A Touch of Blessings. "
                       f"{number} for {amount} is ready.")
            if link:
                message += " Pay securely here: " + link
        contact_id = daycare_ghl.ensure_contact(
            DAYCARE_GHL, name=guardian.get("name") or "Family",
            phone=phone, email=guardian.get("email"))
        if not contact_id:
            return {"ok": False, "detail": "Could not create a GHL contact for this family."}
        return daycare_ghl.send_sms(DAYCARE_GHL, contact_id=contact_id, message=message)

    # ---- Family blast (SMS to parents' phones, outside the app) --------------
    # The connector owns the Supabase session, so it assembles the audience and
    # hands plain dicts to daycare_blast (which stays decoupled). Every send is
    # operator-gated — nothing here runs on a loop.

    def _daycare_center_name(self, session):
        try:
            settings = (daycare_supabase.get_settings(session) or {}).get("settings") or {}
            return settings.get("name") or "A Touch of Blessings"
        except Exception:  # noqa: BLE001 — a naming lookup must never block a blast
            return "A Touch of Blessings"

    def _daycare_blast_audience(self, session, classroom_id=None):
        children = (daycare_supabase.get_children(session) or {}).get("children") or []
        return daycare_blast.build_audience(children, classroom_id=classroom_id)

    def _daycare_blast_overview(self, session, classroom_id=None):
        """Everything the Blast tab needs: audience, per-room counts, history, opt-outs."""
        children = (daycare_supabase.get_children(session) or {}).get("children") or []
        classrooms = (daycare_supabase.get_classrooms(session) or {}).get("classrooms") or []
        audience = daycare_blast.build_audience(children, classroom_id=classroom_id)
        rooms = []
        for room in classrooms:
            reach = daycare_blast.build_audience(children, classroom_id=room.get("id"))
            rooms.append({"id": room.get("id"), "name": room.get("name"),
                          "color": room.get("color"),
                          "families": len(reach["recipients"])})
        everyone = daycare_blast.build_audience(children)
        here = daycare_supabase.active_location(session)
        return {
            "ok": True,
            "centerName": self._daycare_center_name(session),
            "locationId": here,
            "audience": audience["recipients"],
            "missingPhone": audience["missingPhone"],
            "totalFamilies": len(everyone["recipients"]),
            "classrooms": rooms,
            "blasts": daycare_blast.list_blasts(here),
            "optOuts": daycare_blast.list_optouts(here),
            "cap": daycare_blast.cap(),
            "maxChars": daycare_blast.MAX_SMS_CHARS,
            "ghl": daycare_ghl.health(DAYCARE_GHL),
        }

    def _daycare_child_save(self, session, body):
        """Enroll/update a child, then mirror the family into GHL tagged with THIS center.

        Supabase is the source of truth and its write is authoritative: a GHL failure is
        REPORTED, never fatal, and never rolls back an enrolled child. The child's
        location_id comes from save_child (= the active center), so a child can only ever
        be created in the center the owner is currently standing in.
        """
        result = daycare_supabase.save_child(session, body)
        child = (result or {}).get("child") or {}
        result["ghlSync"] = self._daycare_sync_family_to_ghl(session, child)
        return result

    def _daycare_ghl_enroll(self, session, body):
        """One-click enroll straight from the Contact-Form inbox card — the owner's click
        IS the approval gate (CLAUDE.md rule 2: an explicit click on a specific, already-
        consented family), so this does the full write in one shot: no intermediate
        review form. Maps the family object the inbox already has (from
        /ghl/pending-families) into a save_child call — auto-matching the classroom by
        the form's age-band tag, creating the guardian login when parent info is present
        (save_child's own optional-guardian rule, unchanged) — then dismisses the GHL
        card so it drops out of the inbox once it's a real Supabase record.
        """
        family = body.get("family") if isinstance(body.get("family"), dict) else {}
        contact_id = family.get("contact_id")
        if not contact_id:
            raise daycare_supabase.DaycareError(400, "contact_id is required", "validation_error")
        child_body = self._daycare_family_child_body(session, family)
        # If the kid was already auto-enrolled from the inbox, pass its id so
        # save_child UPDATES that row (and provisions the login) instead of
        # inserting a duplicate.
        child_body["id"] = daycare_ghl.form_child_id(contact_id) or None
        # A parent login is created ONLY when the family gave an email — enrollment and
        # login are independent. save_child raises if guardian NAME is passed without an
        # email, so we attach the guardian block only when an email is present; otherwise
        # the child still enrolls (no login), and a login can be added later from here.
        if (family.get("email") or "").strip():
            child_body.update({
                "guardian_first_name": family.get("parent_first") or "",
                "guardian_last_name": family.get("parent_last") or "",
                "guardian_phone": family.get("phone") or "",
                "guardian_email": family.get("email"),
            })
        result = self._daycare_child_save(session, {"child": child_body})
        saved_id = ((result or {}).get("child") or {}).get("id")
        if saved_id:
            daycare_ghl.record_form_child(contact_id, saved_id)
        result["dismissed"] = daycare_ghl.dismiss(contact_id)
        return result

    def _daycare_family_child_body(self, session, family):
        """Map a Contact-Form inbox family object to a save_child body (no guardian
        block — the login is attached separately by the enroll path)."""
        classroom_id = None
        location_id = family.get("location_id")
        if location_id:
            classroom_id = daycare_supabase.find_classroom_id(
                session, location_id, family.get("classroom_label") or "")
        return {
            "first_name": family.get("child_first") or family.get("child_name") or "",
            # Forms often carry a first-name-only child ("Mu'nir") — fall back to the
            # family surname so save_child's required last_name never blocks intake.
            "last_name": family.get("child_last") or family.get("parent_last") or "",
            "birth_date": family.get("child_dob") or "",
            "classroom_id": classroom_id,
            "allergies": family.get("allergies") or "",
            "medical_notes": family.get("medical_notes") or "",
            "pickup_notes": family.get("pickup_notes") or "",
            "location_id": location_id,
            "active": True,
        }

    def _daycare_sync_family_to_ghl(self, session, child):
        guardian = daycare_supabase.guardian_contact(
            session, (child or {}).get("guardian_profile_id"))
        if not guardian:
            return {"ok": True, "synced": False,
                    "detail": "No guardian linked to this child yet — nothing to sync."}
        try:
            return daycare_ghl.sync_family(
                DAYCARE_GHL,
                name=guardian.get("name"), phone=guardian.get("phone"),
                email=guardian.get("email"),
                location_name=self._daycare_center_name(session),
                child_name=(child or {}).get("first_name") or "")
        except Exception as error:  # noqa: BLE001 — never leak a token, never fail the save
            return {"ok": False, "synced": False,
                    "detail": f"GHL sync failed: {type(error).__name__}"}

    def _daycare_blast_preview(self, session, body):
        audience = self._daycare_blast_audience(session, body.get("classroom_id"))
        people = audience["recipients"]
        keep = body.get("guardian_ids")
        if keep:
            wanted = set(keep)
            people = [p for p in people if p.get("guardianId") in wanted]
        return {"ok": True,
                "preview": daycare_blast.preview(body.get("template"), people,
                                                 self._daycare_center_name(session)),
                "count": len(people)}

    def _daycare_blast_create(self, session, body):
        audience = self._daycare_blast_audience(session, body.get("classroom_id"))
        people = audience["recipients"]
        keep = body.get("guardian_ids")
        if keep:
            wanted = set(keep)
            people = [p for p in people if p.get("guardianId") in wanted]
        return daycare_blast.create_blast(
            title=body.get("title"), template=body.get("template"),
            recipients=people, audience_label=body.get("audience_label") or "",
            center_name=self._daycare_center_name(session),
            location_id=daycare_supabase.active_location(session))

    def _handle_daycare_post(self, path):
        """Explicit, domain-only Daycare write router (never a generic table proxy)."""
        handlers = {
            "/api/daycare/child/save": daycare_supabase.save_child,
            "/api/daycare/child/deactivate": daycare_supabase.deactivate_child,
            "/api/daycare/guardian/reset-pin": daycare_supabase.reset_credentials,
            "/api/daycare/classroom/save": daycare_supabase.save_classroom,
            "/api/daycare/classroom/archive": daycare_supabase.archive_classroom,
            "/api/daycare/staff/save": daycare_supabase.save_staff,
            "/api/daycare/staff/deactivate": daycare_supabase.deactivate_staff,
            "/api/daycare/schedule/save": daycare_supabase.save_schedule,
            "/api/daycare/attendance/set": daycare_supabase.set_attendance,
            "/api/daycare/attendance/sign-out-all": daycare_supabase.sign_out_all,
            "/api/daycare/behavior/set": daycare_supabase.set_behavior,
            "/api/daycare/log/save": daycare_supabase.save_log,
            "/api/daycare/incident/save": daycare_supabase.save_incident,
            "/api/daycare/announcement/save": daycare_supabase.save_announcement,
            "/api/daycare/announcement/delete": daycare_supabase.delete_announcement,
            "/api/daycare/thread/save": daycare_supabase.save_thread,
            "/api/daycare/thread/rename": daycare_supabase.rename_thread,
            "/api/daycare/thread/leave": daycare_supabase.leave_thread,
            "/api/daycare/message/send": daycare_supabase.send_message,
            "/api/daycare/message/react": daycare_supabase.react_message,
            "/api/daycare/notifications/read": daycare_supabase.mark_notifications_read,
            "/api/daycare/invoice/save": daycare_supabase.save_invoice,
            "/api/daycare/invoice/record-payment": daycare_supabase.record_invoice_payment,
            "/api/daycare/payroll/save": daycare_supabase.save_payroll,
            "/api/daycare/payroll/record-paid": daycare_supabase.mark_payroll_paid,
            "/api/daycare/settings/save": daycare_supabase.save_settings,
        }
        if path not in handlers and path not in {
                "/api/daycare/auth/login", "/api/daycare/auth/test-login", "/api/daycare/auth/logout",
                "/api/daycare/media/sign-upload", "/api/daycare/location/switch",
                "/api/daycare/stripe/send-invoice", "/api/daycare/stripe/sync-payment",
                "/api/daycare/ghl/text-invoice", "/api/daycare/ghl/dismiss", "/api/daycare/ghl/undismiss",
                "/api/daycare/ghl/enroll",
                "/api/daycare/blast/preview", "/api/daycare/blast/create",
                "/api/daycare/blast/send", "/api/daycare/blast/cancel",
                "/api/daycare/blast/optout",
                "/api/daycare/director/run", "/api/daycare/director/learn",
                "/api/daycare/family/run", "/api/daycare/family/learn",
                "/api/daycare/adops/run", "/api/daycare/adops/learn",
                "/api/daycare/nova/generate", "/api/daycare/nova/image",
                "/api/daycare/nova/create-ad", "/api/daycare/nova/discard"}:
            return self._send_json(
                {"ok": False, "error": "unknown endpoint", "code": "not_found"}, 404)
        try:
            client_ip = self.client_address[0] if self.client_address else None
            daycare_supabase.validate_write_request(self.headers, client_ip)
            body = self._read_daycare_json()
            sid = self._daycare_session_id()
            if path == "/api/daycare/auth/login":
                session, profile = daycare_supabase.BRIDGE.login(
                    body.get("loginId") or body.get("login_id"), body.get("pin"))
                return self._send_json(
                    {"ok": True, "authenticated": True, "profile": profile},
                    headers={"Set-Cookie": daycare_supabase.session_cookie(session.sid)},
                )
            if path == "/api/daycare/auth/test-login":
                session, profile = daycare_supabase.BRIDGE.login_test_profile(
                    body.get("profile"))
                return self._send_json(
                    {"ok": True, "authenticated": True, "profile": profile, "testMode": True},
                    headers={"Set-Cookie": daycare_supabase.session_cookie(session.sid)},
                )
            if path == "/api/daycare/auth/logout":
                daycare_supabase.BRIDGE.logout(sid)
                return self._send_json(
                    {"ok": True, "authenticated": False},
                    headers={"Set-Cookie": daycare_supabase.expired_session_cookie()},
                )
            session, set_cookie = self._daycare_resolve_session(sid)
            if path == "/api/daycare/media/sign-upload":
                result = daycare_supabase.sign_media(session, body, upload=True)
            elif path == "/api/daycare/child/save":
                # Enroll in the ACTIVE center + auto-sync the family into GHL, tagged.
                result = self._daycare_child_save(session, body)
            elif path == "/api/daycare/location/switch":
                # The DB's set_active_location RPC is the gate — it refuses any center
                # this profile has no membership row for. We never trust the browser's id.
                result = daycare_supabase.switch_location(session, body)
            elif path == "/api/daycare/nova/generate":
                result = daycare_ads_studio.ideas(body.get("account"))
            elif path == "/api/daycare/nova/image":
                result = daycare_ads_studio.attach_image(body.get("id"),
                                                         body.get("imageUrl", ""))
            elif path == "/api/daycare/nova/create-ad":
                # Builds the campaign PAUSED. Nothing serves, nothing spends — going
                # ACTIVE / changing budget stays the owner's call (CLAUDE.md rule 2).
                result = daycare_ads_studio.create_ad(body.get("id"))
            elif path == "/api/daycare/nova/discard":
                result = daycare_ads_studio.discard(body.get("id"))
            elif path == "/api/daycare/stripe/send-invoice":
                ctx = daycare_supabase.stripe_invoice_context(session, body.get("invoice_id"))
                result = stripe_io.send_invoice(ctx)
            elif path == "/api/daycare/stripe/sync-payment":
                result = self._daycare_stripe_sync_payment(session, body)
            elif path == "/api/daycare/ghl/text-invoice":
                result = self._daycare_ghl_text_invoice(session, body)
            elif path == "/api/daycare/ghl/dismiss":
                # Owner marks a Contact-Form inbox entry as reviewed — internal +
                # reversible (undo just re-adds it), no approval gate (rule 2).
                result = daycare_ghl.dismiss(body.get("contact_id"))
            elif path == "/api/daycare/ghl/undismiss":
                result = daycare_ghl.undismiss(body.get("contact_id"))
            elif path == "/api/daycare/ghl/enroll":
                result = self._daycare_ghl_enroll(session, body)
            elif path == "/api/daycare/blast/preview":
                result = self._daycare_blast_preview(session, body)
            elif path == "/api/daycare/blast/create":
                result = self._daycare_blast_create(session, body)
            elif path == "/api/daycare/blast/send":
                # Operator-gated: the console's confirm button IS the approval gate.
                # location_id pins the send to the active center — a blast id from
                # another center is refused even if it is guessed.
                result = daycare_blast.send_blast(
                    body.get("blast_id"),
                    location_id=daycare_supabase.active_location(session))
            elif path == "/api/daycare/blast/cancel":
                result = daycare_blast.cancel_blast(
                    body.get("blast_id"),
                    location_id=daycare_supabase.active_location(session))
            elif path == "/api/daycare/blast/optout":
                result = daycare_blast.set_optout(
                    body.get("phone"),
                    location_id=daycare_supabase.active_location(session),
                    opted_out=body.get("opted_out", True),
                    name=body.get("name") or "")
            elif path == "/api/daycare/director/run":
                result = SOLOMON.run_once(session)
            elif path == "/api/daycare/director/learn":
                result = SOLOMON.learn()
            elif path == "/api/daycare/family/run":
                result = NORA.run_once(session)
            elif path == "/api/daycare/family/learn":
                result = NORA.learn()
            elif path == "/api/daycare/adops/run":
                result = NOVA.run_once(session)
            elif path == "/api/daycare/adops/learn":
                result = NOVA.learn()
            else:
                result = handlers[path](session, body)
            _touch_sync()
            return self._send_json(
                result,
                headers=({"Set-Cookie": set_cookie} if set_cookie else None),
            )
        except daycare_supabase.DaycareError as error:
            headers = None
            if error.status == 401:
                headers = {"Set-Cookie": daycare_supabase.expired_session_cookie()}
            return self._send_json(error.payload(), error.status, headers=headers)
        except stripe_io.StripeError as error:
            return self._send_json(
                {"ok": False, "error": error.message, "code": error.code}, error.status)
        except Exception:  # never leak tokens, credentials, PII, or upstream bodies
            return self._send_json(
                {"ok": False, "error": "Daycare request failed", "code": "internal_error"}, 500)

    def _handle_daycare_get(self, path, q):
        """Explicit Daycare read router; all domain data requires a secure session."""
        handlers = {
            "/api/daycare/overview": lambda session: daycare_supabase.get_overview(session),
            "/api/daycare/children": lambda session: daycare_supabase.get_children(session),
            "/api/daycare/attendance": lambda session: daycare_supabase.get_attendance(
                session, q.get("date", [None])[0]),
            "/api/daycare/behavior": lambda session: daycare_supabase.get_behavior(
                session, q.get("date", [None])[0]),
            "/api/daycare/classrooms": lambda session: daycare_supabase.get_classrooms(session),
            "/api/daycare/staff": lambda session: daycare_supabase.get_staff(session),
            "/api/daycare/logs": lambda session: daycare_supabase.get_logs(
                session, q.get("from", [None])[0], q.get("to", [None])[0]),
            "/api/daycare/incidents": lambda session: daycare_supabase.get_incidents(
                session, q.get("from", [None])[0], q.get("to", [None])[0]),
            "/api/daycare/announcements": lambda session: daycare_supabase.get_announcements(session),
            "/api/daycare/threads": lambda session: daycare_supabase.get_threads(session),
            "/api/daycare/thread": lambda session: daycare_supabase.get_thread(
                session, q.get("id", [None])[0]),
            "/api/daycare/notifications": lambda session: daycare_supabase.get_notifications(session),
            "/api/daycare/billing": lambda session: daycare_supabase.get_billing(session),
            "/api/daycare/payroll": lambda session: daycare_supabase.get_payroll(session),
            "/api/daycare/reports": lambda session: daycare_supabase.get_reports(
                session, q.get("from", [None])[0], q.get("to", [None])[0]),
            "/api/daycare/settings": lambda session: daycare_supabase.get_settings(session),
            "/api/daycare/ads": lambda session: daycare_growth.ads_overview(
                q.get("account", [None])[0], q.get("days", ["7"])[0]),
            "/api/daycare/social": lambda session: daycare_growth.social_overview(
                q.get("network", [None])[0]),
            "/api/daycare/eco": lambda session: daycare_growth.eco_overview(
                q.get("account", [None])[0]),
            "/api/daycare/eco/ideas": lambda session: daycare_growth.eco_ideas(
                q.get("account", [None])[0]),
            # Nova's ad studio — saved ad packages + what's actually wired.
            "/api/daycare/nova/ideas": lambda session: daycare_ads_studio.saved(),
            "/api/daycare/nova/status": lambda session: daycare_ads_studio.status(),
            "/api/daycare/director/status": lambda session: SOLOMON.status(),
            "/api/daycare/director/overview": lambda session: SOLOMON.overview(),
            "/api/daycare/director/brief": lambda session: SOLOMON.brief(),
            "/api/daycare/director/bus": lambda session: agent_bus.recent(30),
            "/api/daycare/family/status": lambda session: NORA.status(),
            "/api/daycare/family/overview": lambda session: NORA.overview(),
            "/api/daycare/family/brief": lambda session: NORA.brief(),
            "/api/daycare/family/bus": lambda session: agent_bus.recent(30),
            "/api/daycare/adops/status": lambda session: NOVA.status(),
            "/api/daycare/adops/overview": lambda session: NOVA.overview(),
            "/api/daycare/adops/brief": lambda session: NOVA.brief(),
            "/api/daycare/adops/bus": lambda session: agent_bus.recent(30),
            "/api/daycare/stripe/status": lambda session: stripe_io.invoice_status(
                (daycare_supabase.stripe_invoice_context(session, q.get("invoice_id", [None])[0]) or {}).get("invoice_id")),
            "/api/daycare/locations": lambda session: daycare_supabase.list_locations(session),
            "/api/daycare/ghl/health": lambda session: daycare_ghl.health(DAYCARE_GHL),
            "/api/daycare/ghl/pending-families": lambda session: self._daycare_pending_families(session),
            "/api/daycare/blast": lambda session: self._daycare_blast_overview(
                session, q.get("classroom", [None])[0]),
            "/api/daycare/media/signed-read": lambda session: daycare_supabase.sign_media(
                session,
                {"bucket": q.get("bucket", [None])[0], "path": q.get("path", [None])[0]},
                upload=False),
        }
        if path not in handlers and path not in {
                "/api/daycare/auth/status", "/api/daycare/status"}:
            return self._send_json(
                {"ok": False, "error": "unknown endpoint", "code": "not_found"}, 404)
        sid = self._daycare_session_id()
        try:
            if path == "/api/daycare/auth/status":
                # Always 200, including unconfigured, logged-out, and expired states.
                secure = daycare_supabase.request_is_secure(
                    self.headers, self.client_address[0] if self.client_address else None)
                effective_sid = sid
                set_cookie = None
                if secure and not sid:
                    # Loopback owner with no cookie → hand back an auto-admin session
                    # so the console opens straight in (no login screen).
                    auto = daycare_supabase.BRIDGE.autoadmin_session(self._daycare_client_ip())
                    if auto is not None:
                        effective_sid = auto.sid
                        set_cookie = daycare_supabase.session_cookie(auto.sid)
                result = daycare_supabase.BRIDGE.auth_status(effective_sid if secure else None)
                if not secure:
                    result["secureRequired"] = True
                return self._send_json(
                    result,
                    headers=({"Set-Cookie": set_cookie} if set_cookie else None),
                )
            if path == "/api/daycare/status":
                session = None
                if daycare_supabase.request_is_secure(
                        self.headers, self.client_address[0] if self.client_address else None):
                    try:
                        session, _sc = self._daycare_resolve_session(sid)
                    except daycare_supabase.DaycareError:
                        session = None
                return self._send_json(daycare_supabase.get_status(session))
            self._daycare_require_secure()
            session, set_cookie = self._daycare_resolve_session(sid)
            return self._send_json(
                handlers[path](session),
                headers=({"Set-Cookie": set_cookie} if set_cookie else None),
            )
        except daycare_supabase.DaycareError as error:
            headers = None
            if error.status == 401:
                headers = {"Set-Cookie": daycare_supabase.expired_session_cookie()}
            return self._send_json(error.payload(), error.status, headers=headers)
        except stripe_io.StripeError as error:
            return self._send_json(
                {"ok": False, "error": error.message, "code": error.code}, error.status)
        except Exception:  # never leak tokens, credentials, PII, or upstream bodies
            return self._send_json(
                {"ok": False, "error": "Daycare request failed", "code": "internal_error"}, 500)

    def _handle_dropship_get(self, path, q):
        """FORGE Dropship read router — open on the tailnet/loopback like the agency side
        (no PII, no session). Reads are safe; every write / outward action is gated in
        _handle_dropship_post."""
        def _overview():
            try:
                snap = dropship_shopify.snapshot()
            except Exception as e:  # noqa: BLE001
                snap = {"ok": False, "error": str(e)[:200]}
            return {"ok": True, "store": snap,
                    "watchlist": dropship_io.stats(),
                    "settings": dropship_io.get_settings(),
                    "systems": dropship_director.connected_systems()}

        def _analytics():
            out = {"ok": True}
            try:
                out["shopify"] = dropship_shopify.snapshot()
            except Exception as e:  # noqa: BLE001
                out["shopify"] = {"error": str(e)[:200]}
            try:
                out["ads"] = BLAZE.meta_overview()
            except Exception as e:  # noqa: BLE001
                out["ads"] = {"error": str(e)[:200]}
            return out

        def _trending():
            """Real trending / winning products from whatever ad-spy sources are keyed
            (PiPiAds + AutoDS marketplace). This is the paid signal Hawk scores against —
            mock/'add key' and $0 until a key is present, honest error on failure, never
            fabricated rows. Read-only."""
            query = (q.get("q", [""])[0] or "").strip()
            try:
                limit = max(1, min(int(q.get("limit", ["20"])[0]), 100))
            except Exception:
                limit = 20
            sources, products = [], []
            for name, fn in (
                ("pipiads", lambda: dropship_pipiads.trending(query, limit)),
                ("autods", lambda: dropship_autods.marketplace(limit, query)),
            ):
                try:
                    r = fn()
                except Exception as e:  # noqa: BLE001
                    r = {"ok": False, "source": name, "error": str(e)[:160]}
                sources.append({"source": name, "configured": bool(r.get("configured")),
                                "ok": bool(r.get("ok")), "error": r.get("error"),
                                "count": len(r.get("products") or [])})
                for p in (r.get("products") or []):
                    p = dict(p)
                    p.setdefault("source", name)
                    products.append(p)
            any_keyed = any(s["configured"] for s in sources)
            return {"ok": True, "configured": any_keyed, "query": query,
                    "sources": sources, "products": products, "count": len(products),
                    "detail": None if any_keyed else
                    "Add PIPIADS_API_KEY (pipispy.com) or AUTODS_API_KEY to pull real "
                    "trending products. Until then this reads mock / add-key."}

        handlers = {
            "/api/dropship/overview": _overview,
            "/api/dropship/trending": _trending,
            "/api/dropship/pipiads/health": lambda: dropship_pipiads.health(),
            "/api/dropship/products": lambda: dropship_shopify.products(),
            "/api/dropship/orders": lambda: dropship_shopify.orders(),
            "/api/dropship/inventory": lambda: dropship_shopify.inventory(),
            "/api/dropship/suppliers": lambda: dropship_autods.products(),
            "/api/dropship/watchlist": lambda: dropship_io.list_watchlist(),
            "/api/dropship/settings": lambda: dropship_io.get_settings(),
            "/api/dropship/shopify/health": lambda: dropship_shopify.health(),
            "/api/dropship/autods/health": lambda: dropship_autods.health(),
            "/api/dropship/ads": lambda: BLAZE.meta_overview(),
            "/api/dropship/analytics": _analytics,
            "/api/dropship/agents": lambda: {"ok": True, "agents": [
                MIDAS.status(), HAWK.status(), BLAZE.status(), OTTO.status()]},
            "/api/dropship/director/status": lambda: MIDAS.status(),
            "/api/dropship/director/overview": lambda: MIDAS.overview(),
            "/api/dropship/director/brief": lambda: MIDAS.brief(),
            "/api/dropship/director/bus": lambda: agent_bus.recent(30),
            "/api/dropship/hawk/overview": lambda: HAWK.overview(),
            "/api/dropship/blaze/overview": lambda: BLAZE.overview(),
            "/api/dropship/otto/overview": lambda: OTTO.overview(),
        }
        handler = handlers.get(path)
        if not handler:
            return self._send_json(
                {"ok": False, "error": "unknown endpoint", "code": "not_found"}, 404)
        try:
            return self._send_json(handler())
        except Exception as e:  # noqa: BLE001 — never leak tokens/bodies
            return self._send_json(
                {"ok": False, "error": "Dropship request failed",
                 "code": "internal_error", "detail": str(e)[:200]}, 500)

    def _handle_dropship_post(self, path):
        """FORGE Dropship write/action router. Persistence writes (watchlist/settings) +
        agent runs (Claude, propose-only) are allowed; NO outward action (ad launch,
        supplier order, listing edit, customer message) is exposed here — those stay the
        operator's one-tap approval (rule 2)."""
        allow = {
            "/api/dropship/settings/save",
            "/api/dropship/watchlist/save",
            "/api/dropship/watchlist/delete",
            "/api/dropship/director/run", "/api/dropship/director/learn",
            "/api/dropship/hawk/run", "/api/dropship/hawk/learn",
            "/api/dropship/hawk/watch",
            "/api/dropship/blaze/run", "/api/dropship/blaze/learn",
            "/api/dropship/otto/run", "/api/dropship/otto/learn",
        }
        if path not in allow:
            return self._send_json(
                {"ok": False, "error": "unknown endpoint", "code": "not_found"}, 404)
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except Exception:
            body = {}
        try:
            if path == "/api/dropship/settings/save":
                result = dropship_io.save_settings(body)
            elif path == "/api/dropship/watchlist/save":
                result = dropship_io.save_item(body)
            elif path == "/api/dropship/watchlist/delete":
                result = dropship_io.delete_item(body.get("id"))
            elif path == "/api/dropship/director/run":
                result = MIDAS.run_once()
            elif path == "/api/dropship/director/learn":
                result = MIDAS.learn()
            elif path == "/api/dropship/hawk/run":
                result = HAWK.research(body)
            elif path == "/api/dropship/hawk/learn":
                result = HAWK.learn()
            elif path == "/api/dropship/hawk/watch":
                item = dropship_io.get_item(body.get("id"))
                if not item:
                    result = {"ok": False, "error": "item not found"}
                else:
                    r = HAWK.watch_score(item)
                    if r.get("ok"):
                        saved = dropship_io.save_analysis(item.get("id"), r.get("result"))
                        result = {"ok": True, "item": saved.get("item"),
                                  "analysis": r.get("result")}
                    else:
                        result = r
            elif path == "/api/dropship/blaze/run":
                result = BLAZE.analyze_ads(body)
            elif path == "/api/dropship/blaze/learn":
                result = BLAZE.learn()
            elif path == "/api/dropship/otto/run":
                result = OTTO.check(body)
            elif path == "/api/dropship/otto/learn":
                result = OTTO.learn()
            else:
                result = {"ok": False, "error": "unhandled"}
            _touch_sync()
            return self._send_json(result)
        except Exception as e:  # noqa: BLE001 — never leak tokens/bodies
            return self._send_json(
                {"ok": False, "error": "Dropship request failed",
                 "code": "internal_error", "detail": str(e)[:200]}, 500)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/daycare/"):
            return self._handle_daycare_get(path, urllib.parse.parse_qs(parsed.query))

        if path.startswith("/api/dropship/"):
            return self._handle_dropship_get(path, urllib.parse.parse_qs(parsed.query))

        if path.startswith("/api/"):
            handler = ROUTES.get(path)
            if not handler:
                return self._send_json({"error": "unknown endpoint"}, 404)
            q = urllib.parse.parse_qs(parsed.query)
            cache_key = self.path
            if path not in NO_CACHE:
                hit = _CACHE.get(cache_key)
                if hit and (time.time() - hit[0]) < _CACHE_TTL:
                    return self._send_json(hit[1])
            try:
                result = handler(q)
                if path not in NO_CACHE:
                    if len(_CACHE) >= _CACHE_MAX:
                        oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
                        _CACHE.pop(oldest, None)
                    _CACHE[cache_key] = (time.time(), result)
                return self._send_json(result)
            except urllib.error.HTTPError as e:
                detail = getattr(e, "_detail", None) or _http_error_detail(e, limit=300)
                return self._send_json(
                    {"error": f"GHL {e.code}", "detail": detail}, 502
                )
            except Exception as e:  # noqa: BLE001
                return self._send_json({"error": str(e)}, 500)

        # Static files (default to the dashboard).
        if path in ("/", ""):
            path = "/FORGE REI OS.html"
        elif path in ("/m", "/m/", "/mobile", "/mobile/"):
            path = "/mobile/index.html"
        elif path in ("/portal", "/portal/"):
            path = "/portal.html"
        rel = urllib.parse.unquote(path.lstrip("/"))
        # Deny dotfiles + sensitive dirs (secrets, source, state, SSH keys).
        parts = Path(rel).parts
        # Narrow allow: buyer-sheet photos only — uploads/deals/<id>/<image>.
        _photo_ok = (len(parts) == 4 and parts[0] == "uploads" and parts[1] == "deals"
                     and Path(rel).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
        if any(p.startswith(".") for p in parts) or ((set(parts) & DENY_DIRS) and not _photo_ok):
            self.send_error(404, "Not found")
            return
        target = (HERE / rel).resolve()
        # Path-jail + allow-list: only known asset types are ever served.
        ctype = SERVE_TYPES.get(target.suffix.lower())
        if (not ctype or not str(target).startswith(str(HERE) + os.sep)
                or not target.is_file()):
            self.send_error(404, "Not found")
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception as exc:  # noqa: BLE001
            if not self._client_disconnected(exc):
                raise


# ── Client portal — a SEPARATE, public-safe listener ──────────────────────────
# The main dashboard (Handler above) stays on the private tailnet. This second
# handler is the ONLY surface intended to face the public internet (via Tailscale
# Funnel on FORGE_PORTAL_PORT). It answers exactly three things:
#   GET  /            + /portal        → the client portal page (portal.html)
#   GET  /api/portal/bootstrap         → that client's own name + requests (token)
#   POST /api/portal/submit            → file a new edit request (token)
# EVERYTHING else 404s. There is deliberately NO path from this handler to the
# CRM, the dashboard APIs, secrets, or any other client — a client's token only
# ever unlocks their own record (agency_portal_io + agency_io.verify_portal).
# Off unless FORGE_PORTAL_PORT is set, so the live box is unchanged until the
# operator opts in.
_PORTAL_ALLOWED_ORIGINS = None  # same-origin only; portal.html is served from here


class PortalHandler(BaseHTTPRequestHandler):
    server_version = "ForgePortal/1.0"

    def log_message(self, *a):  # keep the portal quiet in the connector log
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:  # noqa: BLE001
            pass

    def _page(self):
        target = (HERE / "portal.html").resolve()
        if not (str(target).startswith(str(HERE) + os.sep) and target.is_file()):
            return self.send_error(404, "Not found")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:  # noqa: BLE001
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/portal", "/portal/", "/portal.html"):
            return self._page()
        if path == "/api/portal/bootstrap":
            q = urllib.parse.parse_qs(parsed.query)
            cid = (q.get("c", [None]) or [None])[0]
            token = (q.get("k", [None]) or [None])[0]
            try:
                return self._json(agency_portal_io.bootstrap(cid, token))
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)
        return self.send_error(404, "Not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/portal/submit":
            return self.send_error(404, "Not found")
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length > 64 * 1024:  # a client request body is tiny; cap abuse
                return self._json({"error": "payload too large"}, 413)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                return self._json({"error": "bad request"}, 400)
            return self._json(agency_portal_io.submit(
                body.get("c"), body.get("k"), body))
        except Exception as e:  # noqa: BLE001
            return self._json({"error": str(e)}, 500)


def _start_portal_server():
    """Start the public-safe portal listener when FORGE_PORTAL_PORT is set.

    Binds 0.0.0.0 so a Tailscale Funnel target can reach it. Returns the thread
    or None. Never raises — a portal bind failure must not stop the dashboard."""
    raw = (os.environ.get("FORGE_PORTAL_PORT") or "").strip()
    if not raw:
        return None
    try:
        pport = int(raw)
    except ValueError:
        print(f"   Portal: FORGE_PORTAL_PORT={raw!r} is not a number — skipped")
        return None
    phost = os.environ.get("FORGE_PORTAL_HOST", "0.0.0.0")
    try:
        srv = ThreadingHTTPServer((phost, pport), PortalHandler)
    except Exception as e:  # noqa: BLE001
        print(f"   Portal: could not bind {phost}:{pport} ({e}) — skipped")
        return None
    print(f"   Portal: client edit-request portal on {phost}:{pport} "
          f"(public-safe) · share base {PORTAL_BASE}")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return t


def main():
    if not (API_KEY and LOCATION_ID):
        print("!! GHL credentials not found. Checked:")
        for p in ENV_CANDIDATES:
            print("   -", p)
        return
    print(f"FORGE REI OS connector -> http://localhost:{PORT}")
    print(f"   GHL location {LOCATION_ID} ({API_VERSION})")
    # Only ONE machine should poll GHL, or two pollers double-act. Box runs the loops
    # (default); set FORGE_MARCUS=0 on the Mac to run UI-only. Two simple agents:
    #   Scout  — finds + ranks + organizes every seller reply (24/7 sweep).
    #   Marcus — auto-screens what Scout flags into call-ready reports + nurture drafts.
    if LOOPS_ENABLED:
        # Scout — read-only triage sweep; auto-feeds Marcus via SCOUT.on_scored.
        print(f"   Scout: lead triage · {'Claude' if SCOUT and review_agent._api_key() else 'rule'}"
              f"-scored · auto-screens call-worthy leads · sweeping every {scout_triage.POLL_INTERVAL}s")
        ts = threading.Thread(target=SCOUT.run_forever, daemon=True)
        ts.start()
        # Marcus screening runs on-demand + auto (no poll loop needed — Scout drives it).
        print(f"   Marcus: lead screening · {'Claude' if SCREENER and marcus_screening._marcus_key() else 'no key'}"
              f" · auto-screen {'on' if marcus_screening.AUTO_SCREEN else 'off'} · self-learning")
        # Legacy SMS responder loop is OFF by default (Marcus = screening now). Flip
        # FORGE_MARCUS_SMS=1 to bring back the auto-drafting SMS responder.
        if os.environ.get("FORGE_MARCUS_SMS", "0") != "0":
            print(f"   Marcus SMS responder: ON · review-gated · polling every {MARCUS.poll_interval}s")
            t = threading.Thread(target=MARCUS.run_forever, daemon=True)
            t.start()
        # Follow-up — Tier 2 cadence: no-response bumps + due check-backs (gated proposals,
        # nothing auto-texts). Slow loop so it never competes with Scout's 180s sweep.
        print(f"   Follow-up: 24/7 cadence · bumps {followup.TIERS_H}h ·"
              f" check-backs up to {followup.MAX_CHECKBACKS}× · every {followup.INTERVAL}s")
        tf = threading.Thread(target=FOLLOWUP.run_forever, daemon=True)
        tf.start()
        # Atlas — underwrite every screened-interested seller (15-min sweep).
        print("   Atlas: deal underwriter · auto-preps interested sellers every 15 min")
        ta = threading.Thread(target=DEAL_PREP.run_forever, daemon=True)
        ta.start()
        # Solomon — daycare head agent: periodic operating brief + self-improve (box only).
        print(f"   Solomon: daycare director · operating brief every {daycare_director.BRIEF_EVERY_MS // 3600000}h + self-improves")
        tsol = threading.Thread(target=SOLOMON.run_forever, daemon=True)
        tsol.start()
        # Nora — roster organizer & family follow-up (reports to Solomon).
        print(f"   Nora: roster & family follow-up · brief every {daycare_family.BRIEF_EVERY_MS // 3600000}h + self-improves")
        tnora = threading.Thread(target=NORA.run_forever, daemon=True)
        tnora.start()
        # Nova — ad ops: campaign health, competitor intel, creative direction (reports to Solomon).
        print(f"   Nova: ad ops · brief every {daycare_adops.BRIEF_EVERY_MS // 3600000}h + self-improves")
        tnova = threading.Thread(target=NOVA.run_forever, daemon=True)
        tnova.start()
        # Midas — the dropship store's head agent (e-com director). Reads the store
        # (Shopify/AutoDS/Meta) + the brief, writes a ranked operating brief, delegates to
        # Hawk/Blaze/Otto. Propose-only; self-improves. The specialists run on-demand
        # (routes + handoffs), so only the director carries a background loop.
        print(f"   Midas: dropship e-com director · brief every {dropship_director.BRIEF_EVERY_MS // 3600000}h + self-improves")
        tmid = threading.Thread(target=MIDAS.run_forever, daemon=True)
        tmid.start()
        # Do Today — rebuild the morning battle plan + email the digest at 9 AM Eastern.
        print(f"   Do Today: morning battle plan · rebuilds + emails {do_today.RUN_HOUR}:00 {do_today.TZ_NAME}"
              f" → {DO_TODAY.operator_email or 'NO EMAIL (set GHL_USER_EMAIL)'}")
        tdt = threading.Thread(target=DO_TODAY.run_forever, daemon=True)
        tdt.start()
        # Contract poller — close the loop when a seller signs the DocuSign envelope.
        if docusign_io.configured():
            print("   Contract poller: watching DocuSign envelopes → mark Closed/Won on signature")
            tc = threading.Thread(target=_contract_poll_forever, daemon=True)
            tc.start()
        # Telegram — long-poll loop for tap-to-approve (alerts fan out via the bus tap).
        print(f"   Telegram: {'on' if telegram_io.configured() else 'not configured'}"
              f" — alerts + tap-to-approve")
        try:
            telegram_io.register_commands()   # native "/" menu — best-effort, never blocks boot
        except Exception:
            pass
        tt = threading.Thread(target=telegram_io.run_forever, daemon=True)
        tt.start()
        # Optional dedicated agent bot — talk to the agents in its own DM.
        if telegram_io.agent_bot_configured():
            print("   Telegram agent bot: on — DM it to talk to the whole crew")
            at = threading.Thread(target=telegram_io.run_agent_bot_forever, daemon=True)
            at.start()
        # Watchdog — watches every loop's heartbeat; one Telegram+bus alert on silent death.
        print(f"   Watchdog: loop heartbeat monitor · checks every "
              f"{max(60, int(os.environ.get('FORGE_WATCHDOG_SEC', '300')))}s")
        tw = threading.Thread(target=_watchdog_forever, daemon=True)
        tw.start()
        # Daily ops brief — one Telegram digest a day so the operation is legible from
        # anywhere (no app/tunnel needed). Hour is operator-set; default 8am ET.
        _bc = daily_brief.config()
        print(f"   Daily brief: {'on' if _bc.get('enabled') else 'off'} · "
              f"{_bc.get('hour')}:00 (box tz offset {_bc.get('tzOffset')}) → Telegram")
        tb = threading.Thread(target=_brief_scheduler_forever, daemon=True)
        tb.start()
        # Graphify builder — rebuild the code+vault knowledge graph natively on the
        # box so it stays fresh (the old graph came from a Mac-only launchd job and
        # went stale). Same JSON schema graphify_io serves. Box only, low-frequency.
        try:
            import graphify_build
            print(f"   Graphify: rebuilding knowledge graph every "
                  f"{graphify_build.REBUILD_EVERY // 60} min → {graphify_build.GRAPH_PATH}")
            tgf = threading.Thread(target=graphify_build.run_forever, daemon=True)
            tgf.start()
        except Exception as _e:  # noqa: BLE001
            print(f"   Graphify: builder not started ({_e})")
    else:
        print("   Scout + Marcus: loops DISABLED (FORGE_MARCUS=0) — UI/proxy only")
    _start_portal_server()  # public-safe client portal (only if FORGE_PORTAL_PORT set)
    print(f"   binding {HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
