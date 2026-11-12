"""agents_history.py — server-side chat history for the REI agents.

One persistent thread per agent (marcus/scout/atlas + retell personas) shared
across EVERY surface: desktop Agents tab, FORGE Mobile, and the Telegram agent
bot all read and append the same thread — exactly like a Telegram chat. The
agency crew (dyson/eco) is NOT tracked here; agency_agents.py already keeps its
own persistent per-agent history (don't double-track).

Store: marcus_state/agents_chat_history.json
  {"threads": {"marcus": [{role, text, ts, via}], ...}}
role: "user" (operator) | "ai"; via: "dash" | "telegram".
"""
import json
import threading
import time
from pathlib import Path

import forge_atomic

STATE = forge_atomic.guard_state_path(Path(__file__).resolve().parent / "marcus_state" / "agents_chat_history.json")  # temp dir under tests
_LOCK = threading.RLock()
MAX_PER_AGENT = 200


def _now():
    return int(time.time() * 1000)


def _load():
    try:
        raw = json.loads(STATE.read_text())
    except Exception:
        raw = {}
    threads = raw.get("threads") if isinstance(raw, dict) else {}
    return {"threads": threads if isinstance(threads, dict) else {}}


def _save(data):
    forge_atomic.atomic_write_json(STATE, data)


def record(agent_id, user_text, reply_text, via="dash", clean=False, reads=None):
    """Append one operator turn + one agent turn. Best-effort, never raises. clean=True only from
    agent_gateway._after, on a turn that stayed free of outside text: the Mac gate reads it, and a row
    without it (every other writer, every old row) counts as outside text."""
    try:
        aid = str(agent_id or "marcus").strip().lower()
        now = _now()
        with _LOCK:
            data = _load()
            thread = list(data["threads"].get(aid) or [])
            flag = {"clean": True} if clean else {}
            if str(user_text or "").strip():
                thread.append({"role": "user", "text": str(user_text).strip(),
                               "ts": now, "via": via, **flag})
            if str(reply_text or "").strip():
                # reads = the tools this answer actually ran (agent_gateway). Replayed with the row so
                # the next turn knows what was verified and neither re-claims nor retracts it blindly.
                extra = {"reads": [str(x)[:80] for x in reads][:8]} if reads is not None else {}
                thread.append({"role": "ai", "text": str(reply_text).strip(),
                               "ts": now, "via": via, **flag, **extra})
            data["threads"][aid] = thread[-MAX_PER_AGENT:]
            _save(data)
    except Exception:  # noqa: BLE001 — history must never break a chat reply
        pass


def history(agent_id, limit=60):
    aid = str(agent_id or "marcus").strip().lower()
    try:
        lim = max(1, min(int(limit or 60), MAX_PER_AGENT))
    except (TypeError, ValueError):
        lim = 60
    with _LOCK:
        thread = list(_load()["threads"].get(aid) or [])
    return {"agentId": aid, "history": thread[-lim:], "count": len(thread)}


REPLAY = 8                             # rows a chat replays into its prompt


def recent_for_context(agent_id, limit=REPLAY):
    """Last N turns shaped for agents_chat's history= param ({role, text})."""
    rows = history(agent_id, limit).get("history") or []
    return [{"role": r.get("role"), "text": r.get("text")} for r in rows]


def clear(agent_id):
    aid = str(agent_id or "").strip().lower()
    if not aid:
        return {"error": "agentId required"}
    with _LOCK:
        data = _load()
        data["threads"][aid] = []
        _save(data)
    return {"ok": True, "agentId": aid}
