"""business_scope.py — which businesses are ACTIVE vs ARCHIVED (P1-1).

Archive = HIDE, never delete. An archived business drops out of the workspace
switcher, Mission Control, Orion's daily brief, the Agent Office floor and the
coaching feed — but every file, route, JSON store and agent stays in place, so
reactivating brings it straight back with its data.

Server-side (not localStorage) because the Mac, the PC, the phone and the box's
background loops all have to agree on one answer.

Store: marcus_state/businesses.json = {"archived": [ids]}. Missing file -> the
default seed (Dropship + the Agency "Personal" lens archived), written on the
first change. Same store idiom as agency_io (forge_atomic + _LOCK + _load/_save).

Consumers read `is_archived()` / `archived()` and must FAIL OPEN (treat as
active) if this module can't be imported.
"""
import json
import threading
from pathlib import Path

import forge_atomic

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "businesses.json"
_LOCK = threading.Lock()

# Every id the UI knows. Workspace ids match data.jsx WORKSPACES; "agency:p" is the
# Agency workspace's Personal lens. Order = display order.
KNOWN = {
    "rei": "Wholesale (REI)",
    "agency": "Agency (ClientForge)",
    "daycare": "Daycare",
    "dropship": "Dropship",
    "agency:p": "Agency · Personal lens",
}
DEFAULT_ARCHIVED = ("dropship", "agency:p")


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("archived"), list):
                return d
        except Exception:
            pass
    return {"archived": list(DEFAULT_ARCHIVED)}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def archived() -> set:
    """Ids currently archived (unknown ids in the file are ignored)."""
    return {b for b in _load()["archived"] if b in KNOWN}


def is_archived(biz_id: str) -> bool:
    return str(biz_id or "") in archived()


def set_archived(biz_id: str, archived: bool) -> dict:
    """Archive (True) or reactivate (False) one known id. Data is never touched."""
    if not isinstance(biz_id, str) or biz_id not in KNOWN:
        return {"error": f"unknown business: {biz_id!r}"}
    if not isinstance(archived, bool):
        return {"error": "archived must be true or false"}
    with _LOCK:
        cur = {b for b in _load()["archived"] if b in KNOWN}
        (cur.add if archived else cur.discard)(biz_id)
        _save({"archived": [b for b in KNOWN if b in cur]})
    return {"ok": True, "id": biz_id, "archived": archived, "businesses": listing()}


def listing() -> list:
    arch = archived()
    return [{"id": b, "label": label, "archived": b in arch} for b, label in KNOWN.items()]
