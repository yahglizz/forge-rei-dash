"""agency_requests_io.py — Client Edit Requests store (Forge AI Agency).

Server-side JSON store mirroring agency_io.py. Single source of truth at
marcus_state/agency_requests.json. Clients (or you on their behalf) submit edit
requests; admin moves them through a status flow; every change is logged in the
request's history.

MOCK/SEED: ships with a few example requests so the UI is explorable on first
load. Replace the seed + swap _load/_save for a real DB later (see
AGENCY_DASHBOARD_FEATURES.md → "Future database notes").
"""
import forge_atomic
import json
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_requests.json"
_LOCK = threading.Lock()

TYPES = ["Website Edit", "New Page", "Bug Fix", "Content Update",
         "SEO", "Integration", "Design Change", "AI Agent", "Other"]
PRIORITIES = ["low", "medium", "high", "urgent"]
STATUSES = ["submitted", "in_review", "approved", "in_progress",
            "completed", "rejected"]

_NOW = int(time.time() * 1000)
_DAY = 86400 * 1000

# --- MOCK SEED (remove when wiring a real client portal) --------------------
_SEED = {
    "seq": 3,
    "requests": [
        {
            "id": "r1", "clientId": "demo-bloom", "clientName": "Bloom Dental",
            "title": "Swap homepage hero image + headline",
            "type": "Website Edit", "priority": "high", "status": "in_review",
            "detail": "New hero shot from the photoshoot, headline to "
                      "'Gentle dentistry for the whole family'.",
            "createdAt": _NOW - 2 * _DAY, "updatedAt": _NOW - _DAY,
            "history": [
                {"ts": _NOW - 2 * _DAY, "action": "submitted", "note": "Client submitted"},
                {"ts": _NOW - _DAY, "action": "in_review", "note": "Moved to review"},
            ],
        },
        {
            "id": "r2", "clientId": "demo-peak", "clientName": "Peak Fitness",
            "title": "Add online class booking page",
            "type": "New Page", "priority": "urgent", "status": "submitted",
            "detail": "Need a /book page wired to their Calendly + a CTA in the nav.",
            "createdAt": _NOW - 6 * 3600 * 1000, "updatedAt": _NOW - 6 * 3600 * 1000,
            "history": [
                {"ts": _NOW - 6 * 3600 * 1000, "action": "submitted", "note": "Client submitted"},
            ],
        },
        {
            "id": "r3", "clientId": "demo-bloom", "clientName": "Bloom Dental",
            "title": "Fix contact form not sending",
            "type": "Bug Fix", "priority": "high", "status": "completed",
            "detail": "Form submits but no email arrives. Check SMTP / webhook.",
            "createdAt": _NOW - 5 * _DAY, "updatedAt": _NOW - 3 * _DAY,
            "history": [
                {"ts": _NOW - 5 * _DAY, "action": "submitted", "note": "Client submitted"},
                {"ts": _NOW - 4 * _DAY, "action": "in_progress", "note": "Dyson assigned"},
                {"ts": _NOW - 3 * _DAY, "action": "completed", "note": "Webhook re-pointed, verified"},
            ],
        },
    ],
}


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("requests"), list):
                return d
        except Exception:
            pass
    return json.loads(json.dumps(_SEED))  # deep copy of seed on first run


def _save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    forge_atomic.atomic_write_json(STATE, d)


def _slim(r):
    return {
        "id": r.get("id"),
        "clientId": r.get("clientId") or "",
        "clientName": r.get("clientName") or "(client)",
        "title": r.get("title") or "(untitled)",
        "type": r.get("type") if r.get("type") in TYPES else "Other",
        "priority": r.get("priority") if r.get("priority") in PRIORITIES else "medium",
        "status": r.get("status") if r.get("status") in STATUSES else "submitted",
        "detail": r.get("detail") or "",
        "pageUrl": r.get("pageUrl") or "",
        "outcome": r.get("outcome") or "",
        "references": r.get("references") or "",
        "source": r.get("source") or "admin",
        "createdAt": r.get("createdAt"),
        "updatedAt": r.get("updatedAt"),
        "history": r.get("history") or [],
    }


def _broadcast_new(saved):
    """Best-effort: announce a brand-new request on the agent bus so the
    Telegram tap-to-approve flow (and any other notifier) can fire. NEVER raises."""
    try:
        import agent_bus
        who = saved.get("clientName") or "A client"
        agent_bus.send(
            "portal", "all", "note",
            f"📝 New edit request from {who}: {saved.get('title')}",
            {"type": "edit_request", "requestId": saved.get("id"),
             "client": saved.get("clientName") or "", "title": saved.get("title") or "",
             "reqType": saved.get("type") or "", "priority": saved.get("priority") or "",
             "detail": (saved.get("detail") or "")[:400],
             "source": saved.get("source") or "admin"},
        )
    except Exception:
        pass


def list_requests():
    with _LOCK:
        d = _load()
        reqs = [_slim(r) for r in d.get("requests", [])]
        reqs.sort(key=lambda r: r.get("updatedAt") or r.get("createdAt") or 0,
                  reverse=True)
        return {"requests": reqs, "count": len(reqs),
                "types": TYPES, "priorities": PRIORITIES, "statuses": STATUSES}


def save_request(r):
    """Create a new request or update an existing one (matched by id)."""
    if not isinstance(r, dict):
        return {"error": "request object required"}
    title = (r.get("title") or "").strip()
    if not title:
        return {"error": "title required"}
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        rid = r.get("id")
        reqs = d.get("requests", [])
        existing = next((x for x in reqs if x.get("id") == rid), None) if rid else None
        if existing:
            existing.update({
                "clientId": r.get("clientId", existing.get("clientId", "")),
                "clientName": r.get("clientName", existing.get("clientName", "")),
                "title": title,
                "type": r.get("type", existing.get("type")),
                "priority": r.get("priority", existing.get("priority")),
                "detail": r.get("detail", existing.get("detail", "")),
                "pageUrl": r.get("pageUrl", existing.get("pageUrl", "")),
                "outcome": r.get("outcome", existing.get("outcome", "")),
                "references": r.get("references", existing.get("references", "")),
                "updatedAt": now,
            })
            existing.setdefault("history", []).append(
                {"ts": now, "action": "edited", "note": "Request edited"})
            saved = existing
        else:
            d["seq"] = d.get("seq", 0) + 1
            src = r.get("source") if r.get("source") in ("admin", "portal") else "admin"
            saved = {
                "id": rid or f"r{d['seq']}_{now}",
                "clientId": r.get("clientId", ""),
                "clientName": r.get("clientName", "(client)"),
                "title": title,
                "type": r.get("type") if r.get("type") in TYPES else "Other",
                "priority": r.get("priority") if r.get("priority") in PRIORITIES else "medium",
                "status": "submitted",
                "detail": r.get("detail", ""),
                "pageUrl": r.get("pageUrl", ""),
                "outcome": r.get("outcome", ""),
                "references": r.get("references", ""),
                "source": src,
                "createdAt": now,
                "updatedAt": now,
                "history": [{"ts": now, "action": "submitted",
                             "note": ("Submitted via client portal" if src == "portal"
                                      else "Request submitted")}],
            }
            reqs.append(saved)
        d["requests"] = reqs
        _save(d)
        out = _slim(saved)
        # Announce brand-new requests only (edits update in place, no re-ping).
        if not existing:
            _broadcast_new(out)
        return {"ok": True, "request": out}


def list_for_client(cid):
    """Return one client's own requests (newest first). Used by the client portal —
    scoped so a client only ever sees their own edit requests."""
    if not cid:
        return {"requests": [], "count": 0}
    with _LOCK:
        d = _load()
        reqs = [_slim(r) for r in d.get("requests", []) if r.get("clientId") == cid]
        reqs.sort(key=lambda r: r.get("updatedAt") or r.get("createdAt") or 0,
                  reverse=True)
        return {"requests": reqs, "count": len(reqs)}


def set_status(rid, status, note=None):
    """Admin moves a request through the status flow; logs to history."""
    if status not in STATUSES:
        return {"error": f"status must be one of {STATUSES}"}
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        r = next((x for x in d.get("requests", []) if x.get("id") == rid), None)
        if not r:
            return {"error": "request not found"}
        r["status"] = status
        r["updatedAt"] = now
        r.setdefault("history", []).append(
            {"ts": now, "action": status, "note": note or f"Status → {status}"})
        _save(d)
        return {"ok": True, "request": _slim(r)}


def delete_request(rid):
    if not rid:
        return {"error": "id required"}
    with _LOCK:
        d = _load()
        before = len(d.get("requests", []))
        d["requests"] = [x for x in d.get("requests", []) if x.get("id") != rid]
        _save(d)
        return {"ok": True, "removed": before - len(d["requests"])}


def reset():
    """Admin clean-slate: remove ALL edit requests."""
    with _LOCK:
        d = _load()
        n = len(d.get("requests", []))
        d["requests"] = []
        _save(d)
    return {"ok": True, "cleared": n}


def get_request(rid):
    with _LOCK:
        d = _load()
        r = next((x for x in d.get("requests", []) if x.get("id") == rid), None)
        return _slim(r) if r else None
