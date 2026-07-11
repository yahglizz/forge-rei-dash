"""agency_workflows_io.py — n8n workflow control (Forge AI Agency).

Credential-guard pattern: if N8N_BASE_URL + N8N_API_KEY are both present,
_live_workflows() hits the n8n REST API. Otherwise _MOCK_WORKFLOWS is used.
Output shape is identical either way — the UI never errors.

M3: push(draft) creates/updates + publishes a workflow via n8n REST when
connected; returns {ok, detail, url?} without throwing.

Keys injected by connector.py M0:
  N8N_BASE_URL   — e.g. https://n8n.yourdomain.com
  N8N_API_KEY    — n8n instance API key (Settings → API)

Store: marcus_state/agency_workflows.json (drafts only).
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
STATE = HERE / "marcus_state" / "agency_workflows.json"
_LOCK = threading.Lock()

_NOW = int(time.time() * 1000)
_DAY = 86400 * 1000

# --- MOCK workflow catalog (stand-in for the n8n MCP list) ------------------
_MOCK_WORKFLOWS = [
    {
        "id": "wf_lead_intake", "name": "Lead Intake → GHL",
        "status": "active", "nodes": 7, "lastRun": _NOW - 2 * 3600 * 1000,
        "trigger": "Webhook (website form)",
        "description": "New website lead → dedupe → create GHL contact → Slack ping.",
        "client": "Bloom Dental",
        "steps": ["Webhook", "Dedupe (lookup contact)", "Create/Update GHL contact",
                  "Tag 'web-lead'", "Slack notify", "Respond 200"],
    },
    {
        "id": "wf_review_request", "name": "Post-Visit Review Request",
        "status": "active", "nodes": 5, "lastRun": _NOW - 26 * 3600 * 1000,
        "trigger": "Schedule (daily 6pm)",
        "description": "Pull yesterday's completed appts → SMS review link via GHL.",
        "client": "Bloom Dental",
        "steps": ["Cron 6pm", "Query completed appts", "Filter no-review",
                  "Send GHL SMS", "Log sent"],
    },
    {
        "id": "wf_class_booking", "name": "Class Booking Confirmations",
        "status": "inactive", "nodes": 6, "lastRun": _NOW - 9 * _DAY,
        "trigger": "Calendly webhook",
        "description": "Calendly booking → confirm email + add to GHL calendar.",
        "client": "Peak Fitness",
        "steps": ["Calendly webhook", "Parse booking", "Create GHL appt",
                  "Send confirm email", "Add to roster sheet", "Respond 200"],
    },
    {
        "id": "wf_invoice_followup", "name": "Invoice Follow-up",
        "status": "active", "nodes": 4, "lastRun": _NOW - 5 * 3600 * 1000,
        "trigger": "Schedule (weekly Mon 9am)",
        "description": "Find overdue invoices → polite reminder email sequence.",
        "client": "Peak Fitness",
        "steps": ["Cron Mon 9am", "Query overdue", "Send reminder", "Log"],
    },
]


_UA = "ForgeREI/1.0 (+https://github.com/forgelabs)"


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


def _n8n_req(method, endpoint, body=None):
    """urllib request to n8n REST API — mirrors GHLClient._req style."""
    base = os.environ.get("N8N_BASE_URL", "").rstrip("/")
    key = os.environ.get("N8N_API_KEY", "")
    url = f"{base}{endpoint}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "X-N8N-API-KEY": key,
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
            raise RuntimeError(f"n8n {e.code}: {_http_error_detail(e)}")
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise


def _map_n8n_workflow(wf):
    """Map an n8n REST workflow object → existing workflow card shape."""
    nodes = wf.get("nodes") or []
    triggered_at = None
    if wf.get("updatedAt"):
        try:
            import calendar
            from datetime import datetime
            dt = datetime.fromisoformat(wf["updatedAt"].replace("Z", "+00:00"))
            triggered_at = int(calendar.timegm(dt.timetuple()) * 1000)
        except Exception:
            pass
    trigger_node = next(
        (n for n in nodes if "trigger" in n.get("type", "").lower()), None
    )
    trigger_label = trigger_node["type"].split(".")[-1] if trigger_node else "—"
    return {
        "id": str(wf.get("id", "")),
        "name": wf.get("name", "(unnamed)"),
        "status": "active" if wf.get("active") else "inactive",
        "nodes": len(nodes),
        "lastRun": triggered_at,
        "trigger": trigger_label,
        "description": wf.get("description") or wf.get("notes") or "",
        "client": wf.get("tags", [{}])[0].get("name", "") if wf.get("tags") else "",
        "steps": [n.get("name", n.get("type", "")) for n in nodes],
    }


def _live_workflows():
    """Fetch real workflows from n8n REST GET /api/v1/workflows."""
    data = _n8n_req("GET", "/api/v1/workflows")
    items = data.get("data") or (data if isinstance(data, list) else [])
    return [_map_n8n_workflow(wf) for wf in items]


def _connection():
    """Connection state — connected=True when N8N_BASE_URL + N8N_API_KEY present."""
    base = os.environ.get("N8N_BASE_URL", "")
    has_key = bool(os.environ.get("N8N_API_KEY"))
    connected = bool(base and has_key)
    return {
        "connected": connected,
        "baseUrl": base,
        "hasKey": has_key,
        "source": "live" if connected else "mock",
        "todo": (None if connected else
                 "Set N8N_BASE_URL + N8N_API_KEY (env) to go live."),
    }


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("drafts"), list):
                return d
        except Exception:
            pass
    return {"drafts": [], "seq": 0}


def _save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    forge_atomic.atomic_write_json(STATE, d)


def list_workflows():
    """Live workflows from n8n if connected; else mock. Merges local drafts."""
    conn = _connection()
    base_workflows = _MOCK_WORKFLOWS
    if conn["connected"]:
        try:
            base_workflows = _live_workflows()
        except Exception as e:
            import sys
            print(f"[workflows] live fetch failed, falling back to mock: {e}",
                  file=sys.stderr)
            base_workflows = _MOCK_WORKFLOWS

    with _LOCK:
        d = _load()
        drafts = d.get("drafts", [])
    draft_by_id = {x.get("workflowId"): x for x in drafts}
    out = []
    live_ids = set()
    for wf in base_workflows:
        item = dict(wf)
        live_ids.add(wf["id"])
        if wf["id"] in draft_by_id:
            item["draft"] = draft_by_id[wf["id"]]
        out.append(item)
    # Brand-new draft workflows (no live counterpart) also surface in the list.
    for x in drafts:
        if x.get("workflowId") not in live_ids:
            out.append({
                "id": x.get("workflowId") or x.get("id"),
                "name": x.get("name", "(draft workflow)"),
                "status": "draft", "nodes": len(x.get("steps", [])),
                "lastRun": None, "trigger": x.get("trigger", "—"),
                "description": x.get("description", ""),
                "client": x.get("client", ""),
                "steps": x.get("steps", []), "draft": x,
            })
    return {"workflows": out, "count": len(out), "connection": conn}


def save_draft(wf):
    """Save a draft edit of a workflow and queue it for approval-before-push."""
    if not isinstance(wf, dict):
        return {"error": "workflow object required"}
    name = (wf.get("name") or "").strip()
    if not name:
        return {"error": "name required"}
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        wid = wf.get("workflowId") or wf.get("id")
        drafts = d.get("drafts", [])
        existing = next((x for x in drafts if x.get("workflowId") == wid), None) if wid else None
        if existing:
            existing.update({
                "name": name,
                "description": wf.get("description", existing.get("description", "")),
                "trigger": wf.get("trigger", existing.get("trigger", "")),
                "client": wf.get("client", existing.get("client", "")),
                "steps": wf.get("steps", existing.get("steps", [])),
                "status": "draft", "updatedAt": now,
            })
            draft = existing
        else:
            d["seq"] = d.get("seq", 0) + 1
            draft = {
                "id": f"wdraft{d['seq']}_{now}",
                "workflowId": wid or f"wf_new_{now}",
                "name": name,
                "description": wf.get("description", ""),
                "trigger": wf.get("trigger", ""),
                "client": wf.get("client", ""),
                "steps": wf.get("steps", []),
                "status": "draft", "createdAt": now, "updatedAt": now,
            }
            drafts.append(draft)
        d["drafts"] = drafts
        _save(d)

    agency_approvals_io.add(
        "workflow", draft["workflowId"], f"Workflow edit: {name}",
        f"Draft change to '{name}' ({len(draft.get('steps', []))} steps) "
        f"— awaiting push to n8n.",
        client=draft.get("client", ""), risk="medium",
        payload={"steps": draft.get("steps", []), "trigger": draft.get("trigger", "")})
    return {"ok": True, "draft": draft}


def push(draft):
    """M3: Create or update + publish a workflow via n8n REST. Never throws.

    draft: a workflow draft dict (workflowId, name, steps, trigger, etc.)
    Returns: {ok, detail, url?}
    """
    conn = _connection()
    if not conn["connected"]:
        return {"ok": False, "detail": "needs N8N_BASE_URL and N8N_API_KEY"}
    try:
        return _live_push(draft, conn["baseUrl"])
    except Exception as e:
        import sys
        print(f"[workflows] push failed: {e}", file=sys.stderr)
        return {"ok": False, "detail": f"n8n API error: {e}"}


def _live_push(draft, base_url):
    """Create/update + publish a workflow via n8n REST API."""
    wid = draft.get("workflowId", "")
    name = draft.get("name", "New Workflow")
    steps = draft.get("steps", [])

    # Build a minimal n8n workflow JSON structure from draft steps
    nodes = []
    for i, step in enumerate(steps):
        nodes.append({
            "id": f"node_{i}",
            "name": str(step),
            "type": "n8n-nodes-base.set",
            "typeVersion": 3,
            "position": [240 + i * 200, 300],
            "parameters": {},
        })
    wf_body = {
        "name": name,
        "nodes": nodes,
        "connections": {},
        "settings": {"executionOrder": "v1"},
        "staticData": None,
    }

    # Determine create vs update (n8n numeric IDs only, string IDs = new)
    is_existing = wid and not wid.startswith("wf_new_") and not wid.startswith("wdraft")
    if is_existing:
        resp = _n8n_req("PUT", f"/api/v1/workflows/{wid}", wf_body)
        n8n_id = resp.get("id") or wid
    else:
        resp = _n8n_req("POST", "/api/v1/workflows", wf_body)
        n8n_id = resp.get("id")
        if not n8n_id:
            return {"ok": False, "detail": f"n8n create failed: {resp}"}

    # Activate (publish)
    try:
        _n8n_req("POST", f"/api/v1/workflows/{n8n_id}/activate")
    except Exception:
        pass  # best-effort; workflow still created

    url = f"{os.environ.get('N8N_BASE_URL', '').rstrip('/')}/workflow/{n8n_id}"
    return {
        "ok": True,
        "detail": f"Workflow '{name}' pushed to n8n (id={n8n_id}).",
        "url": url,
        "n8nId": n8n_id,
    }


def decision(workflow_id, action):
    """Route inline workflow decisions through the central approval executor."""
    if action not in {"approve", "revise", "reject"}:
        return {"error": "action must be one of ['approve', 'revise', 'reject']"}
    with _LOCK:
        d = _load()
        draft = next((x for x in d.get("drafts", [])
                      if x.get("workflowId") == workflow_id or x.get("id") == workflow_id), None)
        if not draft:
            return {"error": "draft not found"}
    queue = agency_approvals_io.list_queue().get("queue", [])
    item = next((x for x in queue
                 if x.get("kind") == "workflow"
                 and x.get("refId") == (draft.get("workflowId") or workflow_id)
                 and x.get("status") in ("pending", "failed")), None)
    if not item:
        return {"error": "workflow is not awaiting approval"}
    return agency_approvals_io.decide(item["id"], action)
