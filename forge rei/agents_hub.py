"""agents_hub.py — ONE place to operate every agent in the business.

The dashboard used to scatter agents across eight sidebar tabs (REI Agents, Command,
Screening; Agency Agents/Dyson/Eco; Daycare Director/Family/AdOps). This module is the
single backend behind the unified **Agents** tab: one roster, one chat, one task queue —
across all three businesses.

    wholesale  Marcus (lead agent) · Scout (triage) · Atlas (underwriter)
    agency     Dyson (build) · Eco (ads)
    daycare    Solomon (director) · Nora (family) · Nova (ad ops)
    voice      any Retell outbound agent (personas, testable in text)

What it adds vs. what it reuses — additive, nothing rewritten:
  • roster()    — every agent + live status, grouped by business.
  • chat()      — routes to each agent's REAL brain:
                    wholesale -> agents_chat (GHL threads, commands, agent_collab)
                    agency    -> agency_agents.chat
                    daycare   -> NEW here (Solomon/Nora/Nova had briefs but no chat)
  • send_task() — dispatch work to any agent: persisted + broadcast on the agent bus,
                  so the agent (and the operator) both see it. Agency tasks also flow
                  into agency_agents' existing task store so that UI keeps working.

Autonomy is unchanged (CLAUDE.md rule 2). A task is a PROPOSAL/assignment — dispatching
one never sends an SMS, launches an ad, or writes a system of record. The agents still
surface and recommend; the operator still taps to execute.

Every daycare/agency prompt here carries the business CREED first (agent_creed) — the
same evidence discipline the background loops run on, so an agent doesn't get looser just
because you're talking to it in a chat box.
"""
import json
import os
import threading
import time
from pathlib import Path

import review_agent

HERE = Path(__file__).resolve().parent
TASKS = HERE / "marcus_state" / "hub_tasks.json"
_LOCK = threading.Lock()

# business -> creed key (agent_creed.CREED_FILE)
BUSINESS = {
    "wholesale": {"label": "Wholesale (REI)", "creed": "wholesale"},
    "agency": {"label": "Agency (ClientForge)", "creed": "agency"},
    "daycare": {"label": "Daycare", "creed": "daycare"},
    "voice": {"label": "Voice (Outbound)", "creed": "wholesale"},
}

# The permanent roster. Retell voice agents are appended live in roster().
AGENTS = [
    {"id": "marcus", "name": "Marcus", "business": "wholesale", "emoji": "🎯",
     "role": "Lead Agent — head of the operation",
     "blurb": "Screens sellers, drafts the text-back, directs the team. Never quotes a price."},
    {"id": "scout", "name": "Scout", "business": "wholesale", "emoji": "🔍",
     "role": "Lead Triage — finds, ranks, organizes",
     "blurb": "Scores every seller reply, tags + buckets them, hands the hot ones to Marcus."},
    {"id": "atlas", "name": "Atlas", "business": "wholesale", "emoji": "📐",
     "role": "Deal Underwriter — the numbers",
     "blurb": "Offer anchors, MAO math, the negotiation call card. Numbers stay internal."},
    {"id": "dyson", "name": "Dyson", "business": "agency", "emoji": "🛠️",
     "role": "Build Agent — sites + code edits",
     "blurb": "Plans and ships client website work. Plan-only until you approve."},
    {"id": "eco", "name": "Eco", "business": "agency", "emoji": "📈",
     "role": "Ads Agent — strategy + Meta",
     "blurb": "Ad strategy, performance reads, creative concepts. Launches on approval."},
    {"id": "solomon", "name": "Solomon", "business": "daycare", "emoji": "🏛️",
     "role": "Executive Director — head of the daycare agents",
     "blurb": "Reads the whole center, ranks what matters today, owns enrollment, delegates."},
    {"id": "nora", "name": "Nora", "business": "daycare", "emoji": "💬",
     "role": "Family Agent — comms + retention",
     "blurb": "Watches family engagement, flags who's drifting, drafts the outreach."},
    {"id": "nova", "name": "Nova", "business": "daycare", "emoji": "🎨",
     "role": "Ad Ops — enrollment campaigns",
     "blurb": "Runs the enrollment ad angles + creative. Spend stays approval-gated."},
]

_BY_ID = {a["id"]: a for a in AGENTS}


# ── task store (mirrors the agency_io pattern: lock + _load/_save) ─────────────
def _load():
    try:
        if TASKS.exists():
            return json.loads(TASKS.read_text()) or []
    except Exception:
        pass
    return []


def _save(rows):
    try:
        TASKS.parent.mkdir(parents=True, exist_ok=True)
        import forge_atomic
        forge_atomic.atomic_write_json(TASKS, rows[-400:])
    except Exception:
        pass


# ── roster ────────────────────────────────────────────────────────────────────
def _engine(agent_id):
    """The live engine instance for an agent, or None. Read-only."""
    try:
        import connector  # instances live there (SCOUT, SOLOMON, ...)
    except Exception:
        return None
    return {
        "scout": getattr(connector, "SCOUT", None),
        "marcus": getattr(connector, "MARCUS", None),
        "atlas": getattr(connector, "DEAL_PREP", None),
        "solomon": getattr(connector, "SOLOMON", None),
        "nora": getattr(connector, "NORA", None),
        "nova": getattr(connector, "NOVA", None),
    }.get(agent_id)


def _live_status(agent_id):
    """A one-line health read per agent — never invented. "" when we can't reach it."""
    eng = _engine(agent_id)
    if eng is None:
        return {}
    try:
        st = eng.status() if hasattr(eng, "status") else {}
        return {k: st.get(k) for k in
                ("aiReady", "skillsLoaded", "creedLoaded", "lastError", "learn",
                 "briefCount", "lastBriefAt") if k in st}
    except Exception:
        return {}


def roster():
    """Every agent, grouped by business, with live status. Powers the hub's left rail."""
    out = []
    for a in AGENTS:
        row = dict(a)
        row["status"] = _live_status(a["id"])
        row["businessLabel"] = BUSINESS[a["business"]]["label"]
        out.append(row)

    # Live Retell voice agents (personas you can test in text before they dial).
    try:
        import retell_io
        if retell_io.has_key():
            for v in (retell_io.status().get("agents") or []):
                vid = v.get("id")
                if not vid or vid in _BY_ID:
                    continue
                out.append({
                    "id": vid, "name": v.get("name") or "Voice Agent",
                    "business": "voice", "businessLabel": BUSINESS["voice"]["label"],
                    "emoji": "📞", "role": "Outbound voice agent — Retell",
                    "blurb": "Chat runs this agent's real persona so you can test it in text.",
                    "status": {}, "voice": v.get("voice") or "",
                })
    except Exception:
        pass

    creeds = {}
    try:
        import agent_creed
        creeds = agent_creed.status()
    except Exception:
        pass

    return {"agents": out,
            "businesses": [{"id": b, "label": v["label"]} for b, v in BUSINESS.items()],
            "creeds": creeds,
            "hasKey": bool(review_agent._api_key())}


# ── chat ──────────────────────────────────────────────────────────────────────
def _creed(business):
    try:
        import agent_creed
        return agent_creed.block(BUSINESS[business]["creed"])
    except Exception:
        return ""


def _history_block(history, limit=8):
    if not history:
        return ""
    lines = []
    for h in history[-limit:]:
        who = "OPERATOR" if h.get("role") == "user" else "YOU"
        txt = (h.get("text") or "").strip()
        if txt:
            lines.append(f"{who}: {txt}")
    return ("\n".join(lines) + "\n") if lines else ""


def _open_tasks_block(agent_id):
    rows = [t for t in _load()
            if t.get("agentId") == agent_id and t.get("status") == "open"]
    if not rows:
        return ""
    lines = "\n".join(f"- [{t.get('id')}] {t.get('title')}" for t in rows[-8:])
    return ("\n\n=== TASKS THE OPERATOR ASSIGNED YOU (open — address these) ===\n"
            + lines)


def _daycare_chat(agent_id, message, history):
    """Chat for Solomon / Nora / Nova. These agents produced briefs but had no chat
    surface — this is it. Grounded in the creed + the business brief + their OWN live
    brief and playbook, so the agent you talk to is the same one that runs the loops,
    not a generic assistant wearing its name."""
    key = review_agent._api_key()
    if not key:
        return {"needsKey": True,
                "reply": "Add an Anthropic key to daycare.env so I can answer."}
    meta = _BY_ID[agent_id]
    eng = _engine(agent_id)

    ctx = ""
    try:
        import daycare_context
        ctx = daycare_context.context_block()   # the business brief — read FIRST
    except Exception:
        pass

    live = ""
    try:
        if eng is not None and hasattr(eng, "overview"):
            ov = eng.overview() or {}
            brief = ov.get("brief") or ov.get("lastBrief")
            if brief:
                live = ("\n\n=== YOUR LATEST BRIEF (what you most recently concluded — "
                        "build on it, say what changed) ===\n"
                        + json.dumps(brief, default=str)[:3500])
    except Exception:
        pass

    playbook = ""
    try:
        if agent_id == "solomon":
            import daycare_director
            playbook = daycare_director.playbook_text(1500)
    except Exception:
        pass

    system = (
        f"You are {meta['name']}, {meta['role']} for A Touch of Blessings Learning "
        f"Academy. {meta['blurb']} You are talking directly with the OWNER in the "
        "dashboard — answer like the seasoned operator you are: warm, direct, decisive, "
        "no preamble. Ground every number in the data below; if you cannot reach a fact, "
        "say it is unknown and say how you'd find out. You never take an outward action "
        "(no SMS to a family, no invoice, no ad launch, no database write) — you surface, "
        "recommend, and delegate; the owner taps to execute. If he assigns you work, "
        "confirm what you'll do and what you need from him."
        + _creed("daycare")
        + (ctx or "")
        + live
        + (("\n\n=== YOUR PLAYBOOK ===\n" + playbook) if playbook else "")
        + _open_tasks_block(agent_id)
    )
    user = _history_block(history) + f"OPERATOR: {message}\nYOU:"
    try:
        reply = review_agent._claude(key, system, user, max_tokens=700)
    except Exception as e:  # noqa: BLE001
        return {"reply": f"Hit an error reaching my brain: {e}", "agent": meta["name"]}
    return {"reply": reply or "On it.", "agent": meta["name"]}


def chat(ghl_get, location_id, agent_id, message, history=None, scout=None):
    """Route the operator's message to the agent's REAL brain."""
    agent_id = (agent_id or "marcus").strip()
    message = (message or "").strip()
    if not message:
        return {"reply": "Say something and I'll answer."}

    meta = _BY_ID.get(agent_id)
    business = meta["business"] if meta else "voice"

    # Agency — Dyson / Eco (their own engine, already creed-injected via _skills_block).
    if business == "agency":
        try:
            import agency_agents
            out = agency_agents.chat(agent_id, message, history)
            if isinstance(out, dict) and not out.get("error"):
                return out
            return {"reply": (out or {}).get("error") or "Couldn't reach that agent.",
                    "agent": meta["name"]}
        except Exception as e:  # noqa: BLE001
            return {"reply": f"Couldn't reach {meta['name']}: {e}", "agent": meta["name"]}

    # Daycare — Solomon / Nora / Nova (chat added here).
    if business == "daycare":
        return _daycare_chat(agent_id, message, history)

    # Wholesale + Retell voice — the existing brain (GHL threads, commands, collab).
    import agents_chat
    return agents_chat.chat(ghl_get, location_id, agent_id, message,
                            history=history, scout=scout)


# ── tasks ─────────────────────────────────────────────────────────────────────
def send_task(agent_id, title, note=""):
    """Assign work to any agent. Persisted + broadcast on the bus so the agent sees it
    on its next run and the operator sees it in the hub.

    A task is an ASSIGNMENT, not an action — dispatching one never sends an SMS,
    launches an ad, or writes a system of record (CLAUDE.md rule 2 holds).
    """
    agent_id = (agent_id or "").strip()
    title = (title or "").strip()
    if agent_id not in _BY_ID:
        return {"error": "unknown agent"}
    if not title:
        return {"error": "a task needs a title"}
    meta = _BY_ID[agent_id]

    row = {
        "id": f"t{int(time.time() * 1000)}",
        "agentId": agent_id,
        "agentName": meta["name"],
        "business": meta["business"],
        "title": title,
        "note": (note or "").strip(),
        "status": "open",
        "createdAt": int(time.time() * 1000),
    }
    with _LOCK:
        rows = _load()
        rows.append(row)
        _save(rows)

    # Agency agents keep their existing task store so the Agency Agents tab still works.
    if meta["business"] == "agency":
        try:
            import agency_agents
            agency_agents.send_task(agent_id, title)
        except Exception:
            pass

    try:
        import agent_bus
        agent_bus.send("operator", agent_id, "task",
                       f"New task: {title}", {"taskId": row["id"]})
    except Exception:
        pass
    return {"ok": True, "task": row}


def update_task(task_id, status):
    if status not in ("open", "done", "dismissed"):
        return {"error": "bad status"}
    with _LOCK:
        rows = _load()
        hit = None
        for t in rows:
            if t.get("id") == task_id:
                t["status"] = status
                t["updatedAt"] = int(time.time() * 1000)
                hit = t
                break
        if not hit:
            return {"error": "unknown task"}
        _save(rows)
    return {"ok": True, "task": hit}


def tasks(agent_id=None):
    rows = _load()
    if agent_id:
        rows = [t for t in rows if t.get("agentId") == agent_id]
    return {"tasks": list(reversed(rows))[:200]}


def bus(agent_id=None, limit=40):
    """Recent agent-bus traffic — the hub's 'everything is connected' view.

    agent_bus.recent() returns NEWEST FIRST and the sender field is "from" (not "frm"),
    so slice from the head, not the tail.
    """
    try:
        import agent_bus
        msgs = agent_bus.recent(limit=200) or []
    except Exception:
        return {"messages": []}
    if agent_id:
        msgs = [m for m in msgs
                if m.get("from") == agent_id or m.get("to") in (agent_id, "all")]
    return {"messages": msgs[:limit]}
