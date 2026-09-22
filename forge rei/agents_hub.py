"""agents_hub.py — ONE place to operate every agent in the business.

The dashboard used to scatter agents across eight sidebar tabs (REI Agents, Command,
Screening; Agency Agents/Dyson/Eco; Daycare Director/Family/AdOps). This module is the
single backend behind the unified **Agents** tab: one roster, one chat, one task queue —
across all three businesses.

    wholesale  Marcus (lead agent) · Scout (triage) · Atlas (underwriter)
               + Follow-up · ACE · Autopilot (no brain of their own — Marcus answers)
    agency     Dyson (build) · Eco (ads)
    daycare    Solomon (director — ops, enrollment, roster/family-comms, ad ops)
    dropship   Midas (director)
    cross      Orion (CEO brief)   ·   system  Daily brief / recap (Orion answers)
    voice      any Retell outbound agent (personas, testable in text)

  • registry()  — the Agent Control Center (spec §9): status + last run / success /
                  next run / tasks / errors / current task / dependency health per agent.

What it adds vs. what it reuses — additive, nothing rewritten:
  • roster()    — every agent + live status, grouped by business.
  • chat()      — routes to each agent's REAL brain:
                    wholesale -> agents_chat (GHL threads, commands, agent_collab)
                    agency    -> agency_agents.chat
                    daycare   -> NEW here (Solomon had a brief but no chat)
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
import caveman
import agent_coach

HERE = Path(__file__).resolve().parent
TASKS = HERE / "marcus_state" / "hub_tasks.json"
_LOCK = threading.Lock()

# business -> creed key (agent_creed.CREED_FILE)
BUSINESS = {
    "wholesale": {"label": "Wholesale (REI)", "creed": "wholesale"},
    "agency": {"label": "Agency (ClientForge)", "creed": "agency"},
    "daycare": {"label": "Daycare", "creed": "daycare"},
    "dropship": {"label": "Dropship (FORGE)", "creed": "dropship"},
    "voice": {"label": "Voice (Outbound)", "creed": "wholesale"},
    # No creed file for these (agent_creed.block("") == ""): Orion carries his own hard
    # rules + NORTH_STAR; the briefs make no Claude call.
    "cross": {"label": "Cross-business", "creed": ""},
    "system": {"label": "System", "creed": ""},
}

# THE roster — the one source for the hub, the Agent Control Center (registry()), the
# Agent Office floor (pixel_office reads it) and the task store.
#
# Agent Control Center fields (spec §9), all optional:
#   hb       forge_heartbeat loop key(s): liveness, last run, errors
#   queue    approval queue that puts it in WAITING FOR APPROVAL (see _pending)
#   chatVia  agent whose brain answers for this one (it has no brain of its own). Chat
#            and tasks keep THIS id; that brain gets this agent's live state as context
#            and sees its open tasks (_open_tasks_block).
#   ai       False = never calls Claude, so an AI outage can't degrade it
AGENTS = [
    {"id": "marcus", "name": "Marcus", "business": "wholesale", "emoji": "🎯",
     "role": "Lead Agent — head of the operation",
     "blurb": "Screens sellers, drafts the text-back, directs the team. Never quotes a price.",
     "hb": ["marcus_sms"], "queue": "marcus"},
    {"id": "scout", "name": "Scout", "business": "wholesale", "emoji": "🔍",
     "role": "Lead Triage — finds, ranks, organizes",
     "blurb": "Scores every seller reply, tags + buckets them, hands the hot ones to Marcus.",
     "hb": ["scout"], "queue": "scout"},
    {"id": "atlas", "name": "Atlas", "business": "wholesale", "emoji": "📐",
     "role": "Deal Underwriter — the numbers",
     "blurb": "Offer anchors, MAO math, the negotiation call card. Numbers stay internal.",
     "hb": ["atlas"]},
    {"id": "followup", "name": "Follow-up", "business": "wholesale", "emoji": "🔁",
     "role": "Follow-up Cadence — bumps + check-backs",
     "blurb": "Every 30 min drafts no-response re-engage bumps and due check-backs as "
              "Marcus proposals you approve. Marcus answers for it in chat.",
     "hb": ["followup"], "queue": "followup", "chatVia": "marcus"},
    {"id": "ace", "name": "ACE", "business": "wholesale", "emoji": "♠️",
     "role": "Conversation Engine — per-thread state machine",
     "blurb": "Tracks where every seller thread is, decides reply-vs-escalate, builds the "
              "call-ready queue. Mode is read-only here. Marcus answers for it in chat.",
     "chatVia": "marcus"},
    {"id": "autopilot", "name": "Autopilot", "business": "wholesale", "emoji": "🛩️",
     "role": "Re-engage Autopilot — opt-in auto-send",
     "blurb": "When you switch it on, auto-sends routine re-engage bumps behind 7 gates "
              "(cap, hours, legit check, dedupe). Off by default. Marcus answers for it.",
     "chatVia": "marcus"},
    {"id": "dyson", "name": "Dyson", "business": "agency", "emoji": "🛠️",
     "role": "Build Agent — sites + code edits",
     "blurb": "Plans and ships client website work. Plan-only until you approve.",
     "queue": "agency"},
    {"id": "eco", "name": "Eco", "business": "agency", "emoji": "📈",
     "role": "Ads Agent — strategy + Meta",
     "blurb": "Ad strategy, performance reads, creative concepts. Launches on approval.",
     "queue": "agency"},
    {"id": "solomon", "name": "Solomon", "business": "daycare", "emoji": "🏛️",
     "role": "Executive Director — the whole center",
     "blurb": "Ops, enrollment, money, people, roster + family follow-ups, and the "
              "enrollment ads. Ranks it all, owns enrollment, never acts outward.",
     "hb": ["solomon"]},
    {"id": "midas", "name": "Midas", "business": "dropship", "emoji": "🛒",
     "role": "E-com Director — the whole store",
     "blurb": "Product research, creative + ads, fulfillment and support. Ranks the "
              "store into one brief. Never launches, orders, or messages a customer.",
     "hb": ["midas"]},
    {"id": "orion", "name": "Orion", "business": "cross", "emoji": "🧭",
     "role": "Chief of Staff — the cross-business CEO brief",
     "blurb": "Reads what every agent produced and writes the daily 'attack today' "
              "brief: one focus, one idea, ranked priorities. Proposes only.",
     "hb": ["daily_brief"]},
    {"id": "briefs", "name": "Daily brief / recap", "business": "system", "emoji": "🗞️",
     "role": "Morning brief + end-of-day recap (Telegram)",
     "blurb": "Stats-only Telegram pulses, morning and evening. No Claude call. Orion "
              "answers for it in chat.",
     "hb": ["daily_brief"], "chatVia": "orion", "ai": False},
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
        "midas": getattr(connector, "MIDAS", None),
        "orion": getattr(connector, "ORION", None),
        "followup": getattr(connector, "FOLLOWUP", None),
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


def roster(business=None):
    """The agents for ONE business, with live status. Powers the hub's left rail.

    Scoped by workspace on purpose: in the Daycare workspace you want Solomon — not the
    wholesale team. Passing business=None returns everyone (the bus /
    cross-business view still uses that).

    Retell voice agents are deliberately NOT here. They're outbound-call personas, not
    operating agents, and they belong to the REI **Outbound** tab where they're actually
    configured — listing a dozen of them rebuilt the clutter this hub exists to remove.
    """
    rows = [a for a in AGENTS if not business or a["business"] == business]
    try:  # spec §9 fields (status pill, last run, errors…) for the hub header
        control = {r["id"]: r for r in registry(business)}
    except Exception:
        control = {}
    out = []
    for a in rows:
        row = dict(a)
        row["status"] = _live_status(a["id"])
        row["businessLabel"] = BUSINESS[a["business"]]["label"]
        row["control"] = control.get(a["id"])
        out.append(row)

    creeds = {}
    try:
        import agent_creed
        creeds = agent_creed.status()
    except Exception:
        pass

    shown = [b for b in BUSINESS if not business or b == business]
    return {"agents": out,
            "business": business,
            "businesses": [{"id": b, "label": BUSINESS[b]["label"]} for b in shown],
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
    # Plus tasks for the agents this brain answers for (ACE/Follow-up/Autopilot → Marcus).
    ids = {agent_id} | {a["id"] for a in AGENTS if a.get("chatVia") == agent_id}
    rows = [t for t in _load()
            if t.get("agentId") in ids and t.get("status") == "open"]
    if not rows:
        return ""
    lines = "\n".join(
        f"- [{t.get('id')}] {t.get('title')}"
        + (f" (for {t.get('agentName')})" if t.get("agentId") != agent_id else "")
        for t in rows[-8:])
    return ("\n\n=== TASKS THE OPERATOR ASSIGNED YOU (open — address these) ===\n"
            + lines)


def open_tasks_block(agent_id):
    """Public, never-raises version — for the chat prompts that live outside this
    module (agents_chat, marcus_chat, agency_agents). "" when there's nothing open,
    so callers concatenate unconditionally."""
    try:
        return _open_tasks_block(agent_id)
    except Exception:
        return ""


# Per-business wiring for the director chat below: (env file named in the "add a key"
# hint, the business-brief module, the playbook module, who they're talking about).
_DIRECTOR = {
    "daycare": ("daycare.env", "daycare_context", "daycare_director",
                "A Touch of Blessings Learning Academy"),
    "dropship": ("dropship.env", "dropship_context", "dropship_director",
                 "the FORGE Dropship store"),
    # Orion: NORTH_STAR is his brief; his playbook comes off the engine (_playbook).
    "cross": ("ghl.env", "north_star", "mission_control_agent",
              "the owner's whole portfolio (wholesale, agency, daycare, dropship)"),
}


def _director_chat(agent_id, message, history):
    """Chat for a business's director agent (Solomon · daycare, Midas · dropship).
    They produced briefs but had no chat surface — this is it. Grounded in the creed +
    the business brief + their OWN live brief and playbook, so the agent you talk to is
    the same one that runs the loops, not a generic assistant wearing its name."""
    meta = _BY_ID[agent_id]
    business = meta["business"]
    env_name, ctx_mod, pb_mod, org = _DIRECTOR[business]

    key = review_agent._api_key()
    if not key:
        return {"needsKey": True,
                "reply": f"Add an Anthropic key to {env_name} so I can answer."}
    eng = _engine(agent_id)

    ctx = ""
    try:
        ctx = __import__(ctx_mod).context_block()   # the business brief — read FIRST
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

    # Same constitution the brief runs on: TOP SKILLS above the learned playbook. Chat
    # used to ship the playbook alone, so the agent you talked to was weaker than the one
    # that wrote the brief. getattr, so a director without top skills (Solomon) is
    # unchanged. Playbook slice matches the brief's 4000 — 1500 cut it off mid-rubric.
    skills = playbook = ""
    try:
        mod = __import__(pb_mod)
        top = getattr(mod, "top_skills_text", None)
        if top:
            skills = top()
        pb = getattr(mod, "playbook_text", None)
        playbook = pb(4000) if pb else (getattr(eng, "_playbook", lambda: "")() or "")[:4000]
    except Exception:
        pass

    system = (
        f"You are {meta['name']}, {meta['role']} for {org}. "
        f"{meta['blurb']} You are talking directly with the OWNER in the "
        "dashboard — answer like the seasoned operator you are: warm, direct, decisive, "
        "no preamble. Ground every number in the data below; if you cannot reach a fact, "
        "say it is unknown and say how you'd find out. You never take an outward action "
        "(no SMS to a family, no invoice, no ad launch, no database write) — you surface, "
        "recommend, and delegate; the owner taps to execute. If he assigns you work, "
        "confirm what you'll do and what you need from him."
        + _creed(business)
        + (ctx or "")
        + live
        + (("\n\n=== YOUR TOP SKILLS (these OUTRANK the playbook below; when they "
            "conflict, these win) ===\n" + skills) if skills else "")
        + (("\n\n=== YOUR PLAYBOOK ===\n" + playbook) if playbook else "")
        + _open_tasks_block(agent_id)
    )
    user = _history_block(history) + f"OPERATOR: {message}\nYOU:"
    try:
        reply = review_agent._claude(key, system + caveman.block(), user, max_tokens=700)
    except Exception as e:  # noqa: BLE001
        return {"reply": f"Hit an error reaching my brain: {e}", "error": str(e),
                "agent": meta["name"]}
    return {"reply": reply or "On it.", "agent": meta["name"]}


def _delegate_context(agent_id):
    """Live state of an agent with no brain of its own (ACE, Follow-up, Autopilot, the
    briefs) — handed to the brain that answers for it. Read-only; {} when unreachable."""
    try:
        if agent_id == "ace":
            import ace
            st = ace.status()
            return {k: st.get(k) for k in ("mode", "sentToday", "maxReplies", "warning",
                                           "testScoped", "log")}
        if agent_id == "autopilot":
            import autopilot
            return autopilot.status()
        if agent_id == "followup":
            eng = _engine("followup")
            st = eng.status() if eng is not None else {}
            return {k: st.get(k) for k in ("lastRun", "lastError", "tracked", "tiersHours",
                                           "activity")}
        if agent_id == "briefs":
            import daily_brief
            import daily_recap
            return {"brief": daily_brief.config(), "recap": daily_recap.config()}
    except Exception as e:  # noqa: BLE001
        return {"unreachable": str(e)[:200]}
    return {}


# Reply prefixes the agent brains use when the Claude call itself failed. The reply
# carries the real API text ("credit balance is too low"); chat() lifts it into "error"
# so the UI shows it as an error and the office marks the task failed, not done.
_ERR_PREFIXES = ("Hit an error reaching my brain:", "Couldn't reach ")


def _flag_error(out):
    if isinstance(out, dict) and not out.get("error"):
        reply = str(out.get("reply") or "")
        for p in _ERR_PREFIXES:
            if reply.startswith(p):
                out["error"] = reply[len(p):].strip() or reply
                break
    return out


def chat(ghl_get, location_id, agent_id, message, history=None, scout=None):
    """Route the operator's message to the agent's REAL brain."""
    return _flag_error(_chat(ghl_get, location_id, agent_id, message, history, scout))


def _chat(ghl_get, location_id, agent_id, message, history=None, scout=None):
    agent_id = (agent_id or "marcus").strip()
    message = (message or "").strip()
    if not message:
        return {"reply": "Say something and I'll answer."}

    meta = _BY_ID.get(agent_id)
    business = meta["business"] if meta else "voice"

    # No brain of its own → the brain that answers for it, with its live state.
    via = (meta or {}).get("chatVia")
    if via:
        message = (f"[The operator is asking about {meta['name']} ({meta['role']}), "
                   f"which you answer for. Its live state, read-only: "
                   f"{json.dumps(_delegate_context(agent_id), default=str)[:2500]}]"
                   f"\n\n{message}")
        if via in _BY_ID and _BY_ID[via]["business"] in _DIRECTOR:
            return _director_chat(via, message, history)
        import agents_chat
        # Commands off: this message carries a context blob, and a delegate chat must
        # never become a write path.
        return agents_chat.chat(ghl_get, location_id, via, message, history=history,
                                scout=scout, enable_commands=False)

    # Agency — Dyson / Eco (their own engine, already creed-injected via _skills_block).
    if business == "agency":
        try:
            import agency_agents
            out = agency_agents.chat(agent_id, message, history)
            if isinstance(out, dict) and not out.get("error"):
                return out
            err = (out or {}).get("error") or "Couldn't reach that agent."
            return {"reply": (out or {}).get("reply") or err, "error": err,
                    "agent": meta["name"]}
        except Exception as e:  # noqa: BLE001
            return {"reply": f"Couldn't reach {meta['name']}: {e}", "error": str(e),
                    "agent": meta["name"]}

    # The directors — Solomon (daycare), Midas (dropship), Orion (cross-business).
    if business in _DIRECTOR:
        return _director_chat(agent_id, message, history)

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


TASK_STATUSES = ("open", "done", "dismissed", "failed")


def update_task(task_id, status, error=None):
    """failed = the agent's run errored; `error` keeps the real reason on the task."""
    if status not in TASK_STATUSES:
        return {"error": "bad status"}
    with _LOCK:
        rows = _load()
        hit = None
        for t in rows:
            if t.get("id") == task_id:
                t["status"] = status
                t["updatedAt"] = int(time.time() * 1000)
                if status == "failed":
                    t["error"] = str(error or "the agent's run failed")[:400]
                else:
                    t.pop("error", None)
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

    agent_bus.recent() returns a DICT — {"messages": [...], "count": n} — newest first,
    and the sender field is "from" (not "frm"). Unwrap it, filter on both directions
    (what the agent sent AND what was sent to it), and slice from the head.
    """
    try:
        import agent_bus
        msgs = (agent_bus.recent(limit=200) or {}).get("messages", []) or []
    except Exception:
        return {"messages": []}
    if agent_id:
        msgs = [m for m in msgs
                if m.get("from") == agent_id or m.get("to") in (agent_id, "all")]
    return {"messages": msgs[:limit]}


# ── Agent Control Center registry (spec §9) ───────────────────────────────────
# Every field comes from a real signal (heartbeat, engine status, task store, approval
# queue, AI health) or is None = unknown. Status mapping: docs/FORGE_AGENTS.md §4.
STATUSES = ("RUNNING", "IDLE", "WAITING FOR APPROVAL", "DEGRADED", "FAILED", "DISABLED")


def status_of(recs, now, enabled=True, archived=False, running=False, pending=0,
              ai_ok=None):
    """Spec status. Most urgent wins: DISABLED > FAILED > DEGRADED > RUNNING >
    WAITING FOR APPROVAL > IDLE.

    recs   raw forge_heartbeat records for the agent's loop(s)
    ai_ok  False = AI dependency hard-down (billing/auth); None = unknown / not used
    """
    import forge_heartbeat
    if archived or not enabled or any(r.get("retired") for r in recs):
        return "DISABLED"
    health = [forge_heartbeat._status_for(r, now)[0] for r in recs]
    if "red" in health:                      # stale, or errStreak >= 3
        return "FAILED"
    if "amber" in health or ai_ok is False:  # errStreak >= 1, or AI down
        return "DEGRADED"
    if running:
        return "RUNNING"
    if pending:
        return "WAITING FOR APPROVAL"
    return "IDLE"


def _ai_health():
    """The global AI dependency record (forge_heartbeat.ai_health) when this build has it.
    ok: True / False (hard-down) / None (not tracked here)."""
    try:
        import forge_heartbeat
        fn = getattr(forge_heartbeat, "ai_health", None)
        if callable(fn):
            h = fn() or {}
            return {"ok": h.get("ok"), "reason": h.get("reason"),
                    "lastError": h.get("lastError"), "lastOkAt": h.get("lastOkAt"),
                    "downSince": h.get("downSince")}
    except Exception:
        pass
    return {"ok": None, "reason": None, "lastError": None}


def _archived(business):
    try:
        import business_scope          # archive switch; absent on older builds
        return bool(business_scope.is_archived(business))
    except Exception:
        return False


def _running_jobs():
    """agent_id -> title of its running Agent Office job (in-memory, this process)."""
    try:
        import pixel_office
        return {j["agentId"]: j["title"] for j in pixel_office.jobs(limit=60)["jobs"]
                if j.get("status") == "running"}
    except Exception:
        return {}


def _pending(agent_id, queue):
    """Items waiting on the owner in this agent's approval queue (0 when unreadable)."""
    try:
        if queue in ("marcus", "followup"):
            eng = _engine("marcus")
            rows = eng.proposals_list() if eng is not None else []   # pending only
            return sum(1 for p in rows if queue == "marcus" or p.get("reengage"))
        if queue == "scout":
            eng = _engine("scout")
            return len((eng.overview() or {}).get("pendingTags") or []) if eng else 0
        if queue == "agency":
            import agency_approvals_io
            rows = agency_approvals_io.list_queue("pending").get("queue") or []
            return sum(1 for x in rows if x.get("kind") == agent_id)
    except Exception:
        pass
    return 0


def _probe(agent_id):
    """Agent-specific live reads — what a heartbeat can't say. A key is set only when a
    real source has it. Read-only: never flips ACE/autopilot, never calls Claude."""
    p = {}
    eng = _engine(agent_id)
    try:
        if agent_id == "scout" and eng is not None:
            st = eng.summary()
            p.update(lastRun=st.get("lastRun") or None, lastError=st.get("lastError"),
                     keys=st.get("aiScoring"), work=f"{st.get('total', 0)} leads tracked")
        elif agent_id == "marcus" and eng is not None:
            st = eng.status()
            p.update(lastRun=st.get("lastPoll") or None, lastError=st.get("lastError"),
                     keys=st.get("hasAI"), task=st.get("task") if st.get("pending") else None)
        elif agent_id == "atlas" and eng is not None:
            st = eng.status()
            p.update(lastError=st.get("lastError"), keys=st.get("aiPrep"),
                     work=f"{st.get('total', 0)} deals prepped")
        elif agent_id in ("solomon", "midas", "orion") and eng is not None:
            st = eng.status()
            p.update(lastSuccessAt=st.get("lastBriefAt"), lastError=st.get("lastError"),
                     keys=st.get("aiReady"), work=f"{st.get('briefCount', 0)} briefs")
        elif agent_id == "followup" and eng is not None:
            st = eng.status()
            p.update(lastRun=st.get("lastRun") or None, lastError=st.get("lastError"),
                     work=f"{st.get('tracked', 0)} threads tracked")
        elif agent_id == "ace":
            import ace
            st = ace.status()
            log = st.get("log") or []
            p.update(enabled=st.get("mode", "off") != "off",
                     lastRun=log[0].get("ts") if log else None, detail=st.get("warning"),
                     work=f"mode {st.get('mode', 'off')} · {st.get('sentToday', 0)} sent today")
        elif agent_id == "autopilot":
            import autopilot
            st = autopilot.status()
            log = st.get("log") or []
            p.update(enabled=bool(st.get("enabled")),
                     lastRun=log[0].get("ts") if log else None,
                     work=f"{st.get('sentToday', 0)}/{st.get('cap')} sent today")
        elif agent_id == "briefs":
            import daily_brief
            import daily_recap
            b, r = daily_brief.config(), daily_recap.config()
            p.update(enabled=bool(b.get("enabled") or r.get("enabled")),
                     lastSuccessAt=max(b.get("lastSentAt") or 0, r.get("lastSentAt") or 0)
                     or None,
                     work=f"brief {b.get('hour')}:00 · recap {r.get('hour')}:00")
    except Exception as e:  # noqa: BLE001
        p["lastError"] = f"status read failed: {e}"[:300]
    if agent_id == "midas":   # scheduled brief off by default (CLAUDE.md loop switchboard)
        p["enabled"] = os.environ.get("FORGE_DROPSHIP_BRIEF", "0") != "0"
    return p


def registry(business=None, now=None):
    """One row per roster agent with the spec §9 fields. Archived businesses → DISABLED,
    sorted last. Never raises per agent: an unreadable source reads as None/unknown."""
    import forge_heartbeat
    now = now or int(time.time() * 1000)
    try:
        hb_all = forge_heartbeat._load()
    except Exception:
        hb_all = {}
    ai = _ai_health()
    task_rows = _load()
    jobs = _running_jobs()
    has_key = bool(review_agent._api_key())

    out = []
    for a in AGENTS:
        if business and a["business"] != business:
            continue
        aid = a["id"]
        recs = [hb_all[k] for k in a.get("hb", []) if isinstance(hb_all.get(k), dict)]
        rec = recs[0] if recs else {}
        p = _probe(aid)
        mine = [t for t in task_rows if t.get("agentId") == aid]
        open_t = [t for t in mine if t.get("status") == "open"]
        pending = _pending(aid, a.get("queue"))
        archived = _archived(a["business"])
        uses_ai = a.get("ai", True)
        ai_ok = ai.get("ok") if uses_ai else None
        status = status_of(recs, now, enabled=p.get("enabled", True), archived=archived,
                           running=aid in jobs, pending=pending, ai_ok=ai_ok)
        last_run = rec.get("lastRun") or p.get("lastRun")
        interval = rec.get("interval")
        out.append({
            "id": aid, "name": a["name"], "emoji": a["emoji"], "role": a["role"],
            "blurb": a["blurb"], "purpose": a["blurb"],
            "business": a["business"], "businessLabel": BUSINESS[a["business"]]["label"],
            "archived": archived,
            "status": status,
            "lastRun": last_run,
            # WP-A's heartbeat stamps lastSuccessAt; before that, a clean beat IS a success.
            "lastSuccessAt": (p.get("lastSuccessAt") or rec.get("lastSuccessAt")
                              or (rec.get("lastRun") if rec and not rec.get("errStreak")
                                  else None)),
            "nextRun": (rec["lastRun"] + int(interval * 1000)
                        if rec.get("lastRun") and interval and status != "DISABLED"
                        else None),
            "tasksCompleted": sum(1 for t in mine if t.get("status") == "done"),
            "tasksFailed": sum(1 for t in mine if t.get("status") == "failed"),
            "openTasks": len(open_t),
            # errorsTotal = cumulative (WP-A); errStreak = consecutive; None = no loop.
            "errorCount": (rec.get("errorsTotal", rec.get("errStreak", 0)) if rec else None),
            "lastError": rec.get("lastError") or p.get("lastError"),
            "currentTask": jobs.get(aid) or (open_t[-1].get("title") if open_t else None)
                           or p.get("task"),
            "pendingApprovals": pending,
            "approvalQueue": a.get("queue"),
            "dependencyHealth": {
                "ai": ("n/a" if not uses_ai else "unknown" if ai_ok is None
                       else "ok" if ai_ok else "down"),
                "aiReason": (ai.get("reason") or ai.get("lastError")) if ai_ok is False else None,
                "keys": p.get("keys", has_key) if uses_ai else None,   # presence only
                "heartbeat": ("none" if not a.get("hb") else "missing" if not recs
                              else forge_heartbeat._status_for(rec, now)[0]),
            },
            "work": p.get("work"),
            "detail": p.get("detail"),
            "heartbeat": a.get("hb", []),
            "chatTarget": a.get("chatVia") or aid,
            "taskCapable": True,   # delegates' tasks surface in the chatTarget's prompt
        })
    out.sort(key=lambda r: r["archived"])   # stable: roster order, archived last
    return out


def registry_payload(business=None):
    """GET /api/agents/registry body."""
    return {"ok": True, "agents": registry(business), "ai": _ai_health(),
            "statuses": list(STATUSES),
            "businesses": [{"id": b, "label": v["label"]} for b, v in BUSINESS.items()
                           if b != "voice"],
            "generatedAt": int(time.time() * 1000)}


# ── cross-agent coaching (agent_coach) ─────────────────────────────────────────
# Thin wrappers so the connector calls the hub, not agent_coach directly. Coaching
# moves INSIGHTS — plain text lessons, questions, answers — never a credential, GHL
# client, token, or location id, and never an outward action (CLAUDE.md rule 2; see
# docs/superpowers/specs/2026-07-14-cross-agent-coaching-network.md).
def coach_feed(limit=40):
    """The whole coaching feed, newest first — powers the Live Coaching Feed panel."""
    return {"feed": agent_coach.feed(limit)}


def coach_broadcast(frm, insight, to="all"):
    """An agent shares a transferable lesson with a peer / business / everyone."""
    return agent_coach.broadcast(frm, insight, to)


def coach_ask(ghl_get, location_id, frm, to, question):
    """Agent-to-agent Q&A. Route `question` to the target agent through the EXISTING
    hub chat (bound to ghl_get + location_id) so agent_coach stays connector-free."""
    def _chat_fn(agent_id, message):
        out = chat(ghl_get, location_id, agent_id, message)
        if isinstance(out, dict):
            return out.get("reply") or out.get("answer") or ""
        return str(out or "")
    return agent_coach.ask(frm, to, question, chat_fn=_chat_fn)
