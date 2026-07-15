"""agency_io.py — Forge AI Agency client book (ClientForge ops).

Server-side JSON store mirroring daily_goals.py: the 24/7 connector owns the single
source of truth at marcus_state/agency.json, so the AI Agency workspace persists
across reloads and survives restarts/redeploys.
"""
import forge_atomic
import json
import secrets
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency.json"
_LOCK = threading.Lock()

STATUSES = ["lead", "building", "active", "paused", "churned"]

# What a client signed up for. Used as dashboard tags + mirrored to GHL as
# "signed: <service>" tags (see agency_ghl.service_tag).
SERVICES = ["Website", "Automations", "AI Receptionist", "AI Chatbot",
            "Ads Management", "SEO", "Lead Gen", "Social Media", "CRM Setup",
            "Hosting"]


def _services(v):
    if not isinstance(v, list):
        return []
    return [s for s in v if isinstance(s, str) and s in SERVICES]


# What a client's site/build actually IS — so the agents (Dyson) have the context
# + access to make real changes. This is the client "workspace." repo is the key
# that unlocks autonomous edits (agent reads the repo, writes the change, opens a
# PR → Vercel deploys on merge). NO raw passwords here — accessNotes points at
# where logins live (a password manager), never the secret itself.
_WORKSPACE_KEYS = ("repo", "branch", "liveUrl", "stack", "brand", "assets", "accessNotes")


def _workspace(v):
    if not isinstance(v, dict):
        return {k: "" for k in _WORKSPACE_KEYS}
    out = {}
    for k in _WORKSPACE_KEYS:
        val = v.get(k, "")
        out[k] = str(val) if val is not None else ""
    # repo normalize: strip a pasted full URL down to owner/repo
    repo = out.get("repo", "").strip()
    if repo:
        repo = repo.replace("https://github.com/", "").replace("http://github.com/", "")
        repo = repo.replace(".git", "").strip("/ ")
        out["repo"] = repo
    return out


def _num(v):
    try:
        return max(0.0, float(v))
    except (ValueError, TypeError):
        return 0.0


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("clients"), list):
                return d
        except Exception:
            pass
    return {"clients": [], "seq": 0}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _slim(c):
    return {
        "id": c.get("id"),
        "name": c.get("name") or "(unnamed)",
        "business": c.get("business") or "",
        "plan": c.get("plan") or "",
        "mrr": _num(c.get("mrr")),
        "status": c.get("status") if c.get("status") in STATUSES else "lead",
        "site": c.get("site") or "",
        "agents": c.get("agents") or [],
        "services": _services(c.get("services")),
        "ghlContactId": c.get("ghlContactId") or "",
        "ghlSyncedAt": c.get("ghlSyncedAt"),
        "notes": c.get("notes") or "",
        "portalToken": c.get("portalToken") or "",
        "workspace": _workspace(c.get("workspace")),
        "dateAdded": c.get("dateAdded"),
        "dateUpdated": c.get("dateUpdated"),
    }


def list_clients():
    with _LOCK:
        d = _load()
        clients = [_slim(c) for c in d.get("clients", [])]
        clients.sort(key=lambda c: c.get("dateUpdated") or c.get("dateAdded") or 0,
                     reverse=True)
        return {"clients": clients, "count": len(clients), "statuses": STATUSES}


def save_client(c):
    """Add a new client or update an existing one (matched by id)."""
    if not isinstance(c, dict):
        return {"error": "client object required"}
    name = (c.get("name") or "").strip()
    if not name:
        return {"error": "name required"}
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        cid = c.get("id")
        clients = d.get("clients", [])
        existing = next((x for x in clients if x.get("id") == cid), None) if cid else None
        if existing:
            existing.update({
                "name": name,
                "business": c.get("business", existing.get("business", "")),
                "plan": c.get("plan", existing.get("plan", "")),
                "mrr": _num(c.get("mrr", existing.get("mrr", 0))),
                "status": (c.get("status") if c.get("status") in STATUSES
                           else existing.get("status", "lead")),
                "site": c.get("site", existing.get("site", "")),
                "agents": c.get("agents", existing.get("agents", [])),
                "services": (_services(c.get("services")) if "services" in c
                             else existing.get("services", [])),
                "ghlContactId": c.get("ghlContactId", existing.get("ghlContactId", "")),
                "notes": c.get("notes", existing.get("notes", "")),
                "workspace": (_workspace(c.get("workspace")) if "workspace" in c
                              else existing.get("workspace") or _workspace(None)),
                "dateUpdated": now,
            })
            saved = existing
        else:
            d["seq"] = d.get("seq", 0) + 1
            saved = {
                "id": cid or f"c{d['seq']}_{now}",
                "name": name,
                "business": c.get("business", ""),
                "plan": c.get("plan", ""),
                "mrr": _num(c.get("mrr", 0)),
                "status": c.get("status") if c.get("status") in STATUSES else "lead",
                "site": c.get("site", ""),
                "agents": c.get("agents", []),
                "services": _services(c.get("services")),
                "ghlContactId": c.get("ghlContactId", ""),
                "ghlSyncedAt": None,
                "notes": c.get("notes", ""),
                "workspace": _workspace(c.get("workspace")),
                "dateAdded": now,
                "dateUpdated": now,
            }
            clients.append(saved)
        d["clients"] = clients
        _save(d)
        return {"ok": True, "client": _slim(saved)}


def delete_client(cid):
    if not cid:
        return {"error": "id required"}
    with _LOCK:
        d = _load()
        before = len(d.get("clients", []))
        d["clients"] = [x for x in d.get("clients", []) if x.get("id") != cid]
        _save(d)
        return {"ok": True, "removed": before - len(d["clients"])}


def stats():
    with _LOCK:
        d = _load()
        clients = d.get("clients", [])
        by = {s: 0 for s in STATUSES}
        by_service = {s: 0 for s in SERVICES}
        mrr = 0.0
        for c in clients:
            s = c.get("status") if c.get("status") in STATUSES else "lead"
            by[s] += 1
            if s in ("active", "paused"):
                mrr += _num(c.get("mrr"))
            for sv in _services(c.get("services")):
                by_service[sv] += 1
        return {
            "totalClients": len(clients),
            "activeClients": by["active"],
            "leads": by["lead"],
            "building": by["building"],
            "paused": by["paused"],
            "churned": by["churned"],
            "mrr": mrr,
            "arr": mrr * 12,
            "byStatus": by,
            "byService": by_service,
            "services": SERVICES,
        }


def get_client(cid):
    with _LOCK:
        d = _load()
        c = next((x for x in d.get("clients", []) if x.get("id") == cid), None)
        return _slim(c) if c else None


def get_workspace(cid):
    """Return a client's workspace dict (repo/site/brand/access), or None."""
    c = get_client(cid)
    return c.get("workspace") if c else None


# ---------------------------------------------------------------------------
# Client portal access — each client gets a random, revocable token. The
# operator shares a link (…/portal?c=<clientId>&k=<token>); the client can then
# submit + track edit requests WITHOUT logging in or contacting the operator.
# The token is a bearer secret scoped to ONE client: it unlocks only that
# client's own name + own requests (see agency_portal_io.verify_client). It is
# NOT an API key and grants zero dashboard access — the portal server (a
# separate, portal-only listener) is the only surface that ever accepts it.
# ---------------------------------------------------------------------------


def ensure_portal_token(cid):
    """Return the client's portal token, minting one on first use. Idempotent."""
    if not cid:
        return {"error": "id required"}
    with _LOCK:
        d = _load()
        c = next((x for x in d.get("clients", []) if x.get("id") == cid), None)
        if not c:
            return {"error": "client not found"}
        if not c.get("portalToken"):
            c["portalToken"] = secrets.token_urlsafe(18)
            c["dateUpdated"] = int(time.time() * 1000)
            _save(d)
        return {"ok": True, "clientId": cid, "name": c.get("name") or "",
                "portalToken": c["portalToken"]}


def rotate_portal_token(cid):
    """Mint a fresh token, invalidating any previously shared link for this client."""
    if not cid:
        return {"error": "id required"}
    with _LOCK:
        d = _load()
        c = next((x for x in d.get("clients", []) if x.get("id") == cid), None)
        if not c:
            return {"error": "client not found"}
        c["portalToken"] = secrets.token_urlsafe(18)
        c["dateUpdated"] = int(time.time() * 1000)
        _save(d)
        return {"ok": True, "clientId": cid, "name": c.get("name") or "",
                "portalToken": c["portalToken"]}


def verify_portal(cid, token):
    """Return the slimmed client IFF (cid, token) matches an existing client.

    Constant-ish-time compare via secrets.compare_digest so a bad token can't be
    probed by timing. Returns None on any mismatch (never raises)."""
    if not cid or not token:
        return None
    with _LOCK:
        d = _load()
        c = next((x for x in d.get("clients", []) if x.get("id") == cid), None)
    if not c:
        return None
    stored = c.get("portalToken") or ""
    if not stored:
        return None
    try:
        if secrets.compare_digest(str(stored), str(token)):
            return _slim(c)
    except Exception:
        return None
    return None


def mark_ghl_synced(cid):
    with _LOCK:
        d = _load()
        c = next((x for x in d.get("clients", []) if x.get("id") == cid), None)
        if not c:
            return {"error": "client not found"}
        c["ghlSyncedAt"] = int(time.time() * 1000)
        _save(d)
        return {"ok": True, "client": _slim(c)}


# ---------------------------------------------------------------------------
# Agency-level settings (billing, defaults, team) — stored under key
# "settings" in the same agency.json so there is one atomic store.
# ---------------------------------------------------------------------------

_SETTINGS_DEFAULTS = {
    "billingSource": "",          # e.g. "Stripe", "Wave", "Square"
    "defaultPlan": "",            # e.g. "Starter", "Pro", "Enterprise"
    "defaultServices": [],        # subset of SERVICES offered by default
    "teamMembers": [],            # list of {name, role, email}
}


def get_settings():
    """Return agency settings, FLAT (frontend reads data.billingSource etc.)."""
    with _LOCK:
        d = _load()
        stored = d.get("settings") or {}
        settings = {**_SETTINGS_DEFAULTS, **stored}
        return {"ok": True, **settings}


def client_login(email, token):
    """Stub: validate a client portal login (email + access token).

    Real auth is a later milestone. Returns {ok:False, detail:"client login not enabled"}
    so the route exists and the frontend receives a clean JSON response.
    When AGENCY_CLIENT_LOGIN is enabled and real auth is implemented, this
    function will look up the client by email + compare a hashed token.
    """
    return {"ok": False, "detail": "client login not enabled"}


def save_settings(data):
    """Merge provided fields into agency settings and persist atomically."""
    if not isinstance(data, dict):
        return {"error": "settings object required"}
    with _LOCK:
        d = _load()
        stored = d.get("settings") or {}
        updated = {**_SETTINGS_DEFAULTS, **stored}
        # Accept only known top-level keys; unknown keys are silently ignored.
        if "billingSource" in data:
            updated["billingSource"] = str(data["billingSource"])
        if "defaultPlan" in data:
            updated["defaultPlan"] = str(data["defaultPlan"])
        if "defaultServices" in data:
            svc = data["defaultServices"]
            updated["defaultServices"] = (
                [s for s in svc if isinstance(s, str) and s in SERVICES]
                if isinstance(svc, list) else []
            )
        # Frontend sends "teamMembers"; accept "team" too for back-compat.
        team = data.get("teamMembers", data.get("team"))
        if team is not None:
            updated["teamMembers"] = (
                [m for m in team if isinstance(m, dict)]
                if isinstance(team, list) else []
            )
        d["settings"] = updated
        _save(d)
        return {"ok": True, **updated}
