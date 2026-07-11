"""agent_bus.py — Forge REI OS inter-agent comms bus (handoffs + notes + alerts).

Lightweight message bus so the AI agents (Marcus, Scout, and future agents) can
talk to each other and hand off work. Backs the Command Center inbox/feed.

Server-side JSON store mirroring agency_io.py: the 24/7 connector owns the single
source of truth at marcus_state/agent_bus.json, so messages persist across reloads
and survive restarts/redeploys. No DB — just a thread-locked JSON file.

A message = {
    "id": "m{seq}_{ts}", "ts": <int ms>, "from": <agentId>, "to": <agentId|"all">,
    "kind": <"handoff"|"note"|"alert"|"status">, "text": <str>,
    "data": <dict, optional payload e.g. {conversationId, contactId, name}>,
    "read": <bool>,
}
Store = {"messages": [newest..oldest], "seq": <int>}. Capped at 200 (prune oldest).
"""
import forge_atomic
import json
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agent_bus.json"
_LOCK = threading.Lock()

KINDS = ["handoff", "note", "alert", "status"]
MAX_MESSAGES = 200

_NOTIFIERS = []


def register_notifier(fn):
    """Tap the bus: every send() fans out to each registered notifier (best-effort).
    Additive — multiple taps coexist (e.g. Telegram alerts + Marcus auto-screen)."""
    if fn and fn not in _NOTIFIERS:
        _NOTIFIERS.append(fn)


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("messages"), list):
                return d
        except Exception:
            pass
    return {"messages": [], "seq": 0}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _str(v):
    return v.strip() if isinstance(v, str) else ""


def send(frm, to, kind, text, data=None):
    """Create a message from one agent to another (or "all"). Newest first."""
    frm = _str(frm)
    to = _str(to)
    text = _str(text)
    if not frm:
        return {"error": "from required"}
    if not to:
        return {"error": "to required"}
    if not text:
        return {"error": "text required"}
    kind = _str(kind) or "note"
    if kind not in KINDS:
        kind = "note"
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        d["seq"] = d.get("seq", 0) + 1
        msg = {
            "id": f"m{d['seq']}_{now}",
            "ts": now,
            "from": frm,
            "to": to,
            "kind": kind,
            "text": text,
            "data": data if isinstance(data, dict) else {},
            "read": False,
        }
        msgs = d.get("messages", [])
        msgs.insert(0, msg)
        d["messages"] = msgs[:MAX_MESSAGES]
        _save(d)
    for _fn in list(_NOTIFIERS):
        try:
            _fn(msg)
        except Exception:
            pass
    return {"ok": True, "message": msg}


def recent(limit=50):
    """Return the newest messages across all agents."""
    try:
        limit = max(0, int(limit))
    except (ValueError, TypeError):
        limit = 50
    with _LOCK:
        d = _load()
        msgs = d.get("messages", [])[:limit]
        return {"messages": msgs, "count": len(msgs)}


def inbox(agent, unread_only=False):
    """Messages addressed to an agent (or broadcast to "all")."""
    agent = _str(agent)
    if not agent:
        return {"error": "agent required"}
    with _LOCK:
        d = _load()
        mine = [m for m in d.get("messages", [])
                if m.get("to") == agent or m.get("to") == "all"]
        unread = sum(1 for m in mine if not m.get("read"))
        if unread_only:
            mine = [m for m in mine if not m.get("read")]
        return {"messages": mine, "count": len(mine), "unread": unread}


def mark_read(msg_id):
    """Mark a single message read by id."""
    msg_id = _str(msg_id)
    if not msg_id:
        return {"error": "msg_id required"}
    with _LOCK:
        d = _load()
        m = next((x for x in d.get("messages", []) if x.get("id") == msg_id), None)
        if not m:
            return {"error": "not found"}
        m["read"] = True
        _save(d)
        return {"ok": True}


def mark_all_read(agent):
    """Mark every message addressed to an agent (or "all") read."""
    agent = _str(agent)
    if not agent:
        return {"error": "agent required"}
    with _LOCK:
        d = _load()
        marked = 0
        for m in d.get("messages", []):
            if (m.get("to") == agent or m.get("to") == "all") and not m.get("read"):
                m["read"] = True
                marked += 1
        if marked:
            _save(d)
        return {"ok": True, "marked": marked}


def clear():
    """Wipe all messages — for admin/testing."""
    with _LOCK:
        d = _load()
        d["messages"] = []
        _save(d)
        return {"ok": True}
