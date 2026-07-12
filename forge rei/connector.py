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


def _inject_env(paths):
    """Inject non-GHL agency keys into os.environ without clobbering real shell vars.

    Called once at startup so META_ACCESS_TOKEN / N8N_* / METRICOOL_USER_TOKEN /
    GITHUB_TOKEN are visible to all modules via os.environ.get() — the credential
    guard pattern used by every M2/M3 module.
    """
    for k, v in _load_env(paths).items():
        if v and k not in os.environ:
            os.environ[k] = v


_inject_env(AGENCY_ENV_CANDIDATES)  # makes META_ACCESS_TOKEN / N8N_* / METRICOOL_* / GITHUB_TOKEN visible

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
    return {"available": t.get("available", False), "vault": t.get("vault"),
            "notes": notes, "url": getattr(brain_io, "BRAIN_URL", None)}


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
import daily_goals  # noqa: E402
import deal_stats  # noqa: E402
import monthly_goals  # noqa: E402
import agency_io  # noqa: E402
import agency_ghl  # noqa: E402
import agency_requests_io  # noqa: E402
import agency_dyson  # noqa: E402
import agency_workflows_io  # noqa: E402
import agency_ads  # noqa: E402
import agency_eco  # noqa: E402
import agency_approvals_io  # noqa: E402
import agency_agents  # noqa: E402
import agency_social  # noqa: E402
import agency_deploy  # noqa: E402
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


def api_agency_dyson_drafts(_q):
    return agency_dyson.list_drafts()


def api_agency_workflows(_q):
    return agency_workflows_io.list_workflows()


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
    "/api/ace/state": api_ace_state,
    "/api/ace/status": api_ace_status,
    "/api/cost/status": api_cost_status,
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
    "/api/review/latest": api_review_latest,
    "/api/style/latest": api_style_latest,
    "/api/outbound/status": api_outbound_status,
    "/api/outbound/calls": api_outbound_calls,
    "/api/outbound/agent": api_outbound_agent,
    "/api/outbound/voices": api_outbound_voices,
    "/api/agents/list": api_agents_list,
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
    "/api/agency/dyson/drafts": api_agency_dyson_drafts,
    "/api/agency/workflows": api_agency_workflows,
    "/api/agency/ads": api_agency_ads,
    "/api/agency/ads/accounts": api_agency_ads_accounts,
    "/api/agency/eco": api_agency_eco,
    "/api/agency/approvals": api_agency_approvals,
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
NO_CACHE = {"/api/sync", "/api/health", "/api/system/health", "/api/ace/state", "/api/ace/status",
            "/api/cost/status", "/api/skillforge/pending",
            "/api/ace/callready", "/api/ace/digest",
            "/api/contacts", "/api/conversations", "/api/messages",
            "/api/pipeline", "/api/tasks", "/api/dashboard", "/api/analytics",
            "/api/marcus/status", "/api/marcus/proposals", "/api/review/latest",
            "/api/brain/tree", "/api/brain/note", "/api/brain/search",
            "/api/brain/recent", "/api/brain/status", "/api/brain/graph",
            "/api/graphify/graph", "/api/graphify/search", "/api/graphify/stats",
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
            "/api/agency/requests", "/api/agency/dyson/drafts",
            "/api/agency/workflows", "/api/agency/ads", "/api/agency/ads/accounts",
            "/api/agency/eco", "/api/agency/approvals",
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

    def _send_json(self, obj, code=200):
        payload = json.dumps(obj).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:  # noqa: BLE001
            if self._client_disconnected(exc):
                return
            raise

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if not (parsed.path.startswith("/api/marcus/")
                or parsed.path in ("/api/send", "/api/review/run",
                                   "/api/reply/draft", "/api/reply/send",
                                   "/api/ace/mode",
                                   "/api/cost/manual", "/api/cost/settings",
                                   "/api/skillforge/act", "/api/ace/ack", "/api/ace/hold",
                                   "/api/style/run", "/api/brain/undo",
                                   "/api/outbound/agent/update",
                                   "/api/outbound/agent/create",
                                   "/api/pipeline/move",
                                   "/api/marcus/chat",
                                   "/api/agents/chat",
                                   "/api/goals/update",
                                   "/api/goals/monthly/update",
                                   "/api/today/check",
                                   "/api/today/run",
                                   "/api/audit/legit/run",
                                   "/api/marcus/directives/run",
                                   "/api/prep/run",
                                   "/api/prep/learn",
                                   "/api/agency/client/save",
                                   "/api/agency/client/delete",
                                   "/api/agency/request/save",
                                   "/api/agency/request/delete",
                                   "/api/agency/request/status",
                                   "/api/agency/dyson/generate",
                                   "/api/agency/dyson/decision",
                                   "/api/agency/workflow/save",
                                   "/api/agency/workflow/decision",
                                   "/api/agency/eco/generate",
                                   "/api/agency/eco/decision",
                                   "/api/agency/approval/decision",
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
            elif parsed.path == "/api/agency/client/save":
                result = agency_io.save_client(body.get("client") or body)
            elif parsed.path == "/api/agency/client/delete":
                result = agency_io.delete_client(body.get("id"))
            elif parsed.path == "/api/agency/request/save":
                result = agency_requests_io.save_request(body.get("request") or body)
            elif parsed.path == "/api/agency/request/delete":
                result = agency_requests_io.delete_request(body.get("id"))
            elif parsed.path == "/api/agency/request/status":
                result = agency_requests_io.set_status(
                    body.get("id"), body.get("status"), body.get("note"))
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
            elif parsed.path == "/api/agency/eco/generate":
                result = agency_eco.generate(
                    account=body.get("account"), client=body.get("client"))
            elif parsed.path == "/api/agency/eco/decision":
                result = agency_eco.decision(body.get("id"), body.get("action"))
            elif parsed.path == "/api/agency/approval/decision":
                result = agency_approvals_io.decide(
                    body.get("id"), body.get("action"))
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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

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
    else:
        print("   Scout + Marcus: loops DISABLED (FORGE_MARCUS=0) — UI/proxy only")
    print(f"   binding {HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
