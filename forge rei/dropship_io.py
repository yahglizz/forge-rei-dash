"""dropship_io.py — FORGE Dropship local store (workspace state).

Server-side JSON store mirroring agency_io.py: the 24/7 connector owns the single
source of truth at marcus_state/dropship.json, so the Dropship workspace persists
across reloads and survives restarts/redeploys.

Holds the things that are genuinely LOCAL — not already in Shopify/AutoDS:
  • settings  — store facts the agents ground on (niche, target margin, price band).
  • watchlist — product ideas Hawk / the operator are tracking through the research
                pipeline (idea → testing → winner → killed). Shopify owns live
                products; this owns the funnel BEFORE a product is live.
  • mcp       — the MCP server registry (which servers this store talks to, their
                URLs, and the NAME of the env var holding each one's token — never
                the token itself). Powers the Connections & MCP tab.
"""
import dropship_env
import forge_atomic
import json
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "dropship.json"
_LOCK = threading.Lock()

# Where a product idea sits in Hawk's research → launch funnel.
STAGES = ["idea", "researching", "testing", "winner", "killed"]


def _stage(v):
    return v if v in STAGES else "idea"


def _num(v):
    try:
        return max(0.0, float(v))
    except (ValueError, TypeError):
        return 0.0


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("watchlist"), list):
                return d
        except Exception:
            pass
    return {"watchlist": [], "seq": 0}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _slim(it):
    return {
        "id": it.get("id"),
        "name": it.get("name") or "(unnamed)",
        "stage": _stage(it.get("stage")),
        "supplier": it.get("supplier") or "",
        "cost": _num(it.get("cost")),          # landed cost estimate
        "price": _num(it.get("price")),        # intended sell price
        "sourceUrl": it.get("sourceUrl") or "",
        "angle": it.get("angle") or "",        # the creative/marketing angle
        "notes": it.get("notes") or "",
        "verdict": it.get("verdict") or "",    # Hawk's test/pass/watch
        "score": it.get("score"),              # Hawk's 1–10 upside rating
        "analysis": it.get("analysis") or None,  # Hawk's full watch analysis
        "analyzedAt": it.get("analyzedAt"),
        "dateAdded": it.get("dateAdded"),
        "dateUpdated": it.get("dateUpdated"),
    }


def list_watchlist():
    with _LOCK:
        d = _load()
        items = [_slim(x) for x in d.get("watchlist", [])]
        items.sort(key=lambda x: x.get("dateUpdated") or x.get("dateAdded") or 0,
                   reverse=True)
        return {"items": items, "count": len(items), "stages": STAGES}


def save_item(it):
    """Add a new product idea or update an existing one (matched by id)."""
    if not isinstance(it, dict):
        return {"error": "item object required"}
    name = (it.get("name") or "").strip()
    if not name:
        return {"error": "name required"}
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        iid = it.get("id")
        items = d.get("watchlist", [])
        existing = next((x for x in items if x.get("id") == iid), None) if iid else None
        if existing:
            existing.update({
                "name": name,
                "stage": _stage(it.get("stage", existing.get("stage"))),
                "supplier": it.get("supplier", existing.get("supplier", "")),
                "cost": _num(it.get("cost", existing.get("cost", 0))),
                "price": _num(it.get("price", existing.get("price", 0))),
                "sourceUrl": it.get("sourceUrl", existing.get("sourceUrl", "")),
                "angle": it.get("angle", existing.get("angle", "")),
                "notes": it.get("notes", existing.get("notes", "")),
                "verdict": it.get("verdict", existing.get("verdict", "")),
                "dateUpdated": now,
            })
            saved = existing
        else:
            d["seq"] = d.get("seq", 0) + 1
            saved = {
                "id": iid or f"p{d['seq']}_{now}",
                "name": name,
                "stage": _stage(it.get("stage")),
                "supplier": it.get("supplier", ""),
                "cost": _num(it.get("cost", 0)),
                "price": _num(it.get("price", 0)),
                "sourceUrl": it.get("sourceUrl", ""),
                "angle": it.get("angle", ""),
                "notes": it.get("notes", ""),
                "verdict": it.get("verdict", ""),
                "dateAdded": now,
                "dateUpdated": now,
            }
            items.append(saved)
        d["watchlist"] = items
        _save(d)
        return {"ok": True, "item": _slim(saved)}


def get_item(iid):
    """Return the FULL stored item (not slimmed) for an agent to analyze, or None."""
    if not iid:
        return None
    with _LOCK:
        d = _load()
        return next((x for x in d.get("watchlist", []) if x.get("id") == iid), None)


def save_analysis(iid, analysis):
    """Persist Hawk's watch analysis onto a watchlist item. Pulls the 1–10 score and
    verdict out of the analysis so the card can show them at a glance. Internal +
    reversible (re-score any time) — no outward action."""
    if not iid:
        return {"error": "id required"}
    with _LOCK:
        d = _load()
        item = next((x for x in d.get("watchlist", []) if x.get("id") == iid), None)
        if not item:
            return {"error": "item not found"}
        item["analysis"] = analysis if isinstance(analysis, dict) else {"raw": str(analysis)}
        try:
            score = int(item["analysis"].get("score"))
            item["score"] = min(10, max(1, score))
        except (TypeError, ValueError):
            item["score"] = None
        verdict = str(item["analysis"].get("verdict") or "").strip().lower()
        if verdict in ("test", "pass", "watch"):
            item["verdict"] = verdict
        now = int(time.time() * 1000)
        item["analyzedAt"] = now
        item["dateUpdated"] = now
        _save(d)
        return {"ok": True, "item": _slim(item)}


def delete_item(iid):
    if not iid:
        return {"error": "id required"}
    with _LOCK:
        d = _load()
        before = len(d.get("watchlist", []))
        d["watchlist"] = [x for x in d.get("watchlist", []) if x.get("id") != iid]
        _save(d)
        return {"ok": True, "removed": before - len(d["watchlist"])}


def stats():
    with _LOCK:
        d = _load()
        items = d.get("watchlist", [])
        by = {s: 0 for s in STAGES}
        for x in items:
            by[_stage(x.get("stage"))] += 1
        return {
            "totalIdeas": len(items),
            "testing": by["testing"],
            "winners": by["winner"],
            "byStage": by,
            "stages": STAGES,
        }


# ---------------------------------------------------------------------------
# Workspace settings — stored under "settings" in the same dropship.json so
# there is one atomic store. These are the store facts the agents ground on
# (a fast-access mirror of what the owner keeps in dropship-context.md).
# ---------------------------------------------------------------------------

_SETTINGS_DEFAULTS = {
    "storeName": "",
    "niche": "",
    "targetMargin": "",      # e.g. "3x landed cost" or "30%"
    "priceBand": "",         # e.g. "$29–$59"
    "currency": "USD",
}


def get_settings():
    """Return dropship settings, FLAT (frontend reads data.storeName etc.)."""
    with _LOCK:
        d = _load()
        stored = d.get("settings") or {}
        return {"ok": True, **{**_SETTINGS_DEFAULTS, **stored}}


def save_settings(data):
    """Merge provided fields into dropship settings and persist atomically."""
    if not isinstance(data, dict):
        return {"error": "settings object required"}
    with _LOCK:
        d = _load()
        stored = d.get("settings") or {}
        updated = {**_SETTINGS_DEFAULTS, **stored}
        for k in _SETTINGS_DEFAULTS:
            if k in data:
                updated[k] = str(data[k])
        d["settings"] = updated
        _save(d)
        return {"ok": True, **updated}


# ---------------------------------------------------------------------------
# MCP server registry — which MCP servers this store talks to.
#
# A record NEVER holds a token. ``authEnv`` is the NAME of the env var in
# dropship.env that holds it (rule 4); dropship_mcp reads the value at call time
# and the browser only ever sees presence. URLs are operator-editable because MCP
# endpoint shapes should be confirmed against each vendor's live docs — the same
# posture as the AUTODS_*_PATH env overrides in dropship_autods.
# ---------------------------------------------------------------------------

_MCP_FIELDS = {
    "id": "", "name": "", "transport": "http", "url": "", "command": "",
    "authEnv": "", "authScheme": "Bearer", "authHeader": "Authorization",
    "note": "", "enabled": True,
}


def _mcp_seed():
    """Built-in rows. Regenerated on every read, so a row the operator has never
    saved tracks dropship.env (e.g. the Shopify URL follows SHOPIFY_STORE_DOMAIN).
    The moment a row is saved, the saved copy wins."""
    domain = dropship_env.get("SHOPIFY_STORE_DOMAIN", "").strip()
    storefront = dropship_env.get("SHOPIFY_STOREFRONT_MCP_URL", "").strip()
    if not storefront and domain and "your-store" not in domain:
        storefront = f"https://{domain}/api/mcp"
    return [
        {**_MCP_FIELDS, "id": "shopify-storefront", "name": "Shopify Storefront MCP",
         "transport": "http", "url": storefront, "seeded": True,
         "note": "Your store's own MCP endpoint — catalog, cart, policies. "
                 "Public (no token). URL follows SHOPIFY_STORE_DOMAIN until you edit it."},
        {**_MCP_FIELDS, "id": "shopify-dev", "name": "Shopify Dev MCP",
         "transport": "stdio", "command": "npx -y @shopify/dev-mcp@latest",
         "seeded": True,
         "note": "Docs/schema search. Runs in your Claude session — the box cannot "
                 "reach a stdio server, so it never shows as 'connected' here."},
        {**_MCP_FIELDS, "id": "autods", "name": "AutoDS MCP",
         "transport": "http", "url": dropship_env.get("AUTODS_MCP_URL", "").strip(),
         "authEnv": "AUTODS_MCP_TOKEN", "seeded": True,
         "note": "Paste the AutoDS MCP URL when you have it, then Probe — the real "
                 "tool list loads from the server. Sourcing reads work over REST "
                 "(Suppliers tab) meanwhile."},
    ]


def _mcp_slim(r):
    out = {**_MCP_FIELDS, **{k: v for k, v in r.items() if k in _MCP_FIELDS}}
    out["id"] = str(out["id"] or "").strip()
    out["name"] = str(out["name"] or "").strip() or out["id"]
    out["transport"] = out["transport"] if out["transport"] in ("http", "stdio") else "http"
    out["enabled"] = bool(out["enabled"])
    out["seeded"] = bool(r.get("seeded"))
    out["note"] = str(r.get("note") or "")
    if isinstance(r.get("lastProbe"), dict):
        out["lastProbe"] = r["lastProbe"]
    return out


def get_mcp():
    """The registry: seeded rows (overridden by anything saved) + custom rows."""
    with _LOCK:
        stored = (_load().get("mcp") or [])
    by_id = {}
    for r in stored:
        if isinstance(r, dict) and str(r.get("id") or "").strip():
            by_id[str(r["id"]).strip()] = r
    servers = []
    for seed in _mcp_seed():
        saved = by_id.pop(seed["id"], None)
        servers.append(_mcp_slim({**seed, **saved} if saved else seed))
    for leftover in by_id.values():
        servers.append(_mcp_slim(leftover))
    return {"ok": True, "servers": servers, "count": len(servers)}


def get_mcp_server(sid):
    """One record by id, or None. What dropship_mcp.probe/call is handed."""
    sid = str(sid or "").strip()
    if not sid:
        return None
    return next((s for s in get_mcp()["servers"] if s["id"] == sid), None)


def save_mcp_server(rec):
    """Add or update a server. Rejects a token pasted into a field — tokens live in
    dropship.env and are referenced by env-var NAME only (rule 4)."""
    if not isinstance(rec, dict):
        return {"error": "server object required"}
    name = str(rec.get("name") or "").strip()
    sid = str(rec.get("id") or "").strip()
    if not sid:
        sid = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
        sid = sid or f"mcp{int(time.time())}"
    if not name:
        return {"error": "name required"}
    for field in ("url", "command", "authEnv"):
        val = str(rec.get(field) or "")
        if any(val.startswith(p) for p in ("shpat_", "sk-", "sk_live", "Bearer ")):
            return {"error": "Put the token in dropship.env and reference its variable "
                             "NAME here — never paste the token itself."}
    # A seeded row keeps its built-in note/flag when the operator edits its URL.
    base = next((s for s in _mcp_seed() if s["id"] == sid), _MCP_FIELDS)
    incoming = _mcp_slim({**base, **rec, "id": sid, "name": name})
    incoming["seeded"] = bool(base.get("seeded"))
    incoming["note"] = str(rec.get("note") or base.get("note") or "")
    with _LOCK:
        d = _load()
        rows = [r for r in (d.get("mcp") or []) if isinstance(r, dict)]
        existing = next((r for r in rows if str(r.get("id") or "").strip() == sid), None)
        if existing:
            if isinstance(existing.get("lastProbe"), dict):
                incoming["lastProbe"] = existing["lastProbe"]
            rows[rows.index(existing)] = incoming
        else:
            rows.append(incoming)
        d["mcp"] = rows
        _save(d)
    return {"ok": True, "server": incoming}


def delete_mcp_server(sid):
    """Remove a saved record. A seeded row reverts to its built-in default rather
    than disappearing — additive, nothing is ever lost (rule 5)."""
    sid = str(sid or "").strip()
    if not sid:
        return {"error": "id required"}
    with _LOCK:
        d = _load()
        rows = [r for r in (d.get("mcp") or []) if isinstance(r, dict)]
        d["mcp"] = [r for r in rows if str(r.get("id") or "").strip() != sid]
        removed = len(rows) - len(d["mcp"])
        _save(d)
    seeded = any(s["id"] == sid for s in _mcp_seed())
    return {"ok": True, "removed": removed, "revertedToDefault": seeded}


def record_mcp_probe(sid, result):
    """Cache a probe so the tab shows the tool list without re-handshaking on load."""
    sid = str(sid or "").strip()
    if not sid or not isinstance(result, dict):
        return {"error": "id and result required"}
    tools = result.get("tools") if isinstance(result.get("tools"), list) else []
    snap = {
        "ts": result.get("ts") or int(time.time() * 1000),
        "connected": bool(result.get("connected")),
        "serverInfo": result.get("serverInfo") or {},
        "protocolVersion": result.get("protocolVersion") or "",
        "instructions": result.get("instructions") or "",
        "toolCount": len(tools),
        "tools": tools[:100],
        "error": result.get("error") or "",
        "code": result.get("code") or "",
    }
    with _LOCK:
        d = _load()
        rows = [r for r in (d.get("mcp") or []) if isinstance(r, dict)]
        existing = next((r for r in rows if str(r.get("id") or "").strip() == sid), None)
        if existing:
            existing["lastProbe"] = snap
        else:
            seed = next((s for s in _mcp_seed() if s["id"] == sid), None)
            if seed:
                rows.append({**seed, "lastProbe": snap})
            else:
                return {"error": "unknown server"}
        d["mcp"] = rows
        _save(d)
    return {"ok": True, "lastProbe": snap}
