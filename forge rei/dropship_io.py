"""dropship_io.py — FORGE Dropship local store (workspace state).

Server-side JSON store mirroring agency_io.py: the 24/7 connector owns the single
source of truth at marcus_state/dropship.json, so the Dropship workspace persists
across reloads and survives restarts/redeploys.

Holds the two things that are genuinely LOCAL — not already in Shopify/AutoDS:
  • settings  — store facts the agents ground on (niche, target margin, price band).
  • watchlist — product ideas Hawk / the operator are tracking through the research
                pipeline (idea → testing → winner → killed). Shopify owns live
                products; this owns the funnel BEFORE a product is live.
"""
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
