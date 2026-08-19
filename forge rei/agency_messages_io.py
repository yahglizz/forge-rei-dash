"""agency_messages_io.py — two-way operator ↔ client message thread (ClientForge).

Server-side JSON store mirroring agency_requests_io.py / agents_history.py. One
persistent thread per agency client, shared by BOTH surfaces: the operator's
Clients tab and the client's own portal page (agency_portal_io) read and append
the same thread — exactly like a text conversation.

Store: marcus_state/agency_messages.json
  {"threads": {"<clientId>": [{id, clientId, from, text, ts,
                              readByOperator, readByClient}, ...]}, "seq": <int>}
"from" is "client" (sent from the portal) or "operator" (sent from the dashboard).

Text only — no attachments, no upload path. A message from a client is announced
on the agent bus so the existing Telegram notifier pings for free.
"""
import json
import threading
import time
from pathlib import Path

import forge_atomic

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_messages.json"
_LOCK = threading.Lock()

SENDERS = ("client", "operator")
MAX_PER_THREAD = 300
MAX_TEXT = 2000


def _now():
    return int(time.time() * 1000)


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("threads"), dict):
                return {"threads": d["threads"], "seq": d.get("seq", 0)}
        except Exception:
            pass
    return {"threads": {}, "seq": 0}


def _save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    forge_atomic.atomic_write_json(STATE, d)


def _slim(m):
    return {
        "id": m.get("id"),
        "clientId": m.get("clientId") or "",
        "from": m.get("from") if m.get("from") in SENDERS else "client",
        "text": m.get("text") or "",
        "ts": m.get("ts"),
        "readByOperator": bool(m.get("readByOperator")),
        "readByClient": bool(m.get("readByClient")),
    }


def _broadcast_client_msg(client_id, name, text):
    """Best-effort: announce an inbound client message on the agent bus so the
    Telegram notifier (and any other tap) can fire. NEVER raises."""
    try:
        import agent_bus
        agent_bus.send(
            "portal", "all", "note",
            f"💬 {name or 'Client'}: {text[:120]}",
            {"type": "client_message", "clientId": client_id},
        )
    except Exception:
        pass


def list_for_client(client_id):
    """One client's whole thread, oldest first, plus the operator's unread count.

    An unknown/empty client id is NOT an error — an empty thread is normal."""
    cid = str(client_id or "").strip()
    if not cid:
        return {"messages": [], "unread": 0}
    with _LOCK:
        d = _load()
        thread = [_slim(m) for m in (d["threads"].get(cid) or [])]
    unread = sum(1 for m in thread if not m["readByOperator"])
    return {"ok": True, "messages": thread, "unread": unread}


def send(client_id, sender, text, client_name=""):
    """Append one message to a client's thread. Returns {ok, message} or {error}."""
    cid = str(client_id or "").strip()
    if not cid:
        return {"error": "clientId required"}
    if sender not in SENDERS:
        return {"error": "invalid sender"}
    body = str(text or "").strip()[:MAX_TEXT]
    if not body:
        return {"error": "message is empty"}
    with _LOCK:
        d = _load()
        now = _now()
        d["seq"] = d.get("seq", 0) + 1
        msg = {
            "id": f"m{d['seq']}_{now}",
            "clientId": cid,
            "from": sender,
            "text": body,
            "ts": now,
            "readByOperator": sender == "operator",
            "readByClient": sender == "client",
        }
        thread = list(d["threads"].get(cid) or [])
        thread.append(msg)
        d["threads"][cid] = thread[-MAX_PER_THREAD:]
        _save(d)
    out = _slim(msg)
    if sender == "client":
        _broadcast_client_msg(cid, client_name, body)
    return {"ok": True, "message": out}


def mark_read(client_id, by):
    """Mark a thread read by "operator" or "client". Returns {ok, marked}."""
    cid = str(client_id or "").strip()
    if not cid:
        return {"error": "clientId required"}
    if by not in SENDERS:
        return {"error": "invalid reader"}
    key = "readByOperator" if by == "operator" else "readByClient"
    with _LOCK:
        d = _load()
        thread = d["threads"].get(cid) or []
        n = 0
        for m in thread:
            if not m.get(key):
                m[key] = True
                n += 1
        if n:
            d["threads"][cid] = thread
            _save(d)
    return {"ok": True, "marked": n}


def unread_counts():
    """Messages the OPERATOR has not read yet, per client. Clients with 0 omitted."""
    with _LOCK:
        d = _load()
        threads = d["threads"]
        by = {}
        total = 0
        for cid, thread in threads.items():
            n = sum(1 for m in (thread or []) if not m.get("readByOperator"))
            if n:
                by[cid] = n
                total += n
    return {"ok": True, "byClient": by, "total": total}


def purge_client(client_id):
    """Delete a client's whole conversation. Called when the client is deleted.

    Without this an orphaned thread outlives the client record: it keeps reporting an
    unread count for a client that no longer appears in any list, so the operator can
    never open it to clear the badge — and a deleted client's messages would linger on
    disk forever, which is not what "delete this client" means to the person clicking it.
    """
    cid = str(client_id or "").strip()
    if not cid:
        return {"error": "id required"}
    with _LOCK:
        d = _load()
        removed = len(d["threads"].pop(cid, []) or [])
        if removed:
            _save(d)
    return {"ok": True, "removed": removed}


def reset():
    """Admin clean-slate: remove ALL message threads."""
    with _LOCK:
        d = _load()
        n = sum(len(t or []) for t in d["threads"].values())
        d["threads"] = {}
        _save(d)
    return {"ok": True, "cleared": n}
