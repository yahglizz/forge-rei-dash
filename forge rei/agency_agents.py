"""agency_agents.py — operable AI agents for the Forge AI Agency.

Turns Dyson (edit agent) and Eco (ads strategist) into agents you can open,
chat with, and send tasks to — each backed by Claude through the AGENCY's own
Anthropic key (forge-agency/config/agency.env), falling back to the wholesale
key only if the agency key is missing.

"Login + sync":
  - LOGIN  = the Anthropic key (status() reports connected + which key it used).
  - SYNC   = chat history + tasks persist to marcus_state/agency_agents.json, so
             they survive reloads/restarts and show up the same on the box.

Reuses review_agent._claude (the stdlib Anthropic HTTP call) + review_agent.MODEL.
"""
import forge_atomic
import json
import os
import threading
import time
from pathlib import Path

import review_agent  # _claude(key, system, user, max_tokens), MODEL, _api_key()

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_agents.json"
_LOCK = threading.Lock()

AGENCY_ENV_CANDIDATES = [
    HERE.parent / "forge-agency" / "config" / "agency.env",
    Path.home() / "Desktop" / "forge-agency" / "config" / "agency.env",
]

# --- self-improvement (mirror of scout_triage's adaptive loop) ---------------
# Seed playbooks ship in forge-agency/skills/<agent_id>-playbook.md; the learned
# version is written into the Obsidian brain at Skills/<agent_id>-playbook.md and
# git-committed, so the next prompt reloads the freshly-improved rubric.
SEED_SKILLS_DIRS = [
    HERE.parent / "forge-agency" / "skills",
    Path.home() / "Desktop" / "forge-agency" / "skills",
]
AGENCY_LEARN_EVERY = int(os.environ.get("AGENCY_LEARN_EVERY", "12"))
LEARN_MIN_INTERVAL_MS = 45 * 60 * 1000
PLAYBOOK_REL = {
    "dyson": "Skills/dyson-playbook.md",
    "eco": "Skills/eco-playbook.md",
}
# mtime-cached brain+seed skills text, keyed by agent_id -> (mtime_sig, text)
_SK_CACHE = {}

# --- agent registry ----------------------------------------------------------
_AGENTS = {
    "dyson": {
        "id": "dyson", "name": "Dyson", "kind": "edit",
        "role": "Edit Agent · drafts & ships website/code changes",
        "blurb": "Handles client website edits, new pages, bug fixes, and "
                 "integrations. Drafts a plan for every change — nothing goes "
                 "live until you approve.",
        "page": "AgencyDyson",
        "system": (
            "You are Dyson, the edit/build agent for Forge AI Agency — Yahjair's "
            "AI website + automation agency. You handle client website and code "
            "work: edits, new pages, bug fixes, design changes, and integrations. "
            "For any change you produce a PLAN — the affected files/pages/workflows, "
            "a risk level (low/medium/high) with a one-line reason, and numbered "
            "implementation steps. Nothing you plan goes live until Yahjair approves "
            "it in the Approval Center; never claim something is already done/live. "
            "You are talking by text with Yahjair, the operator who runs the agency "
            "(not a client). Be concise, concrete, and technical. Use plain text, no "
            "markdown headings."
        ),
    },
    "eco": {
        "id": "eco", "name": "Eco", "kind": "ads",
        "role": "Ads Strategist · plans & optimizes ad campaigns",
        "blurb": "Reviews Meta ad performance, finds winners and losers, and "
                 "proposes new ad concepts. Campaigns launch only after you approve.",
        "page": "AgencyEco",
        "system": (
            "You are Eco, the ads strategist agent for Forge AI Agency. You analyze "
            "Meta ad performance for the agency's clients, identify winning and weak "
            "ads, and propose new ad concepts — each with a hook, headline, primary "
            "text, CTA, and creative direction. You RECOMMEND; campaigns only launch "
            "after Yahjair approves them in the Approval Center. You are talking by "
            "text with Yahjair, the operator. Be concise, specific, and numeric. "
            "Ground advice in the client's real ad metrics when available. Plain text, "
            "no markdown headings."
        ),
    },
}
AGENT_ORDER = ["dyson", "eco"]


# --- Anthropic key (agency first) -------------------------------------------
def _agency_key():
    """Return (key, source). Agency key wins; falls back to wholesale."""
    k = os.environ.get("AGENCY_ANTHROPIC_API_KEY")
    if k:
        return k, "agency-env"
    for p in AGENCY_ENV_CANDIDATES:
        if p.exists():
            for line in p.read_text().splitlines():
                s = line.strip()
                if s.startswith("ANTHROPIC_API_KEY=") and not s.startswith("#"):
                    v = s.split("=", 1)[1].strip()
                    if v and not v.startswith("sk-ant-..."):
                        return v, "agency"
    wholesale = review_agent._api_key()
    if wholesale:
        return wholesale, "wholesale"
    return None, None


# --- persistence -------------------------------------------------------------
def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict):
                d.setdefault("history", {})
                d.setdefault("tasks", [])
                d.setdefault("seq", 0)
                d.setdefault("learn", {})  # agent_id -> {lastLearnedAt, learnCount, sinceLearn}
                return d
        except Exception:
            pass
    return {"history": {}, "tasks": [], "seq": 0, "learn": {}}


def _save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    forge_atomic.atomic_write_json(STATE, d)


# --- grounding context (kept small) -----------------------------------------
def _dyson_context():
    try:
        import agency_requests_io
        import agency_dyson
        reqs = agency_requests_io.list_requests().get("requests", [])
        open_reqs = [r for r in reqs if r["status"] not in ("completed", "rejected")]
        drafts = agency_dyson.list_drafts().get("drafts", [])
        lines = [f"- [{r['priority']}] {r['clientName']}: {r['title']} ({r['type']}, {r['status']})"
                 for r in open_reqs[:8]]
        return ("CURRENT OPEN EDIT REQUESTS:\n" + ("\n".join(lines) if lines else "(none)")
                + f"\nDraft plans you've made: {len(drafts)}.")
    except Exception:
        return ""


def _eco_context():
    try:
        import agency_ads
        accts = agency_ads.accounts().get("accounts", [])
        out = []
        for a in accts[:3]:
            an = agency_ads.analytics(account=a["id"])
            t = an["totals"]
            out.append(f"- {a['clientName']}: spend ${t['spend']}, {t['leads']} leads, "
                       f"CPL ${t['cpl']}, ROAS {t['roas']}x")
        return "CLIENT AD ACCOUNTS (last 7d):\n" + ("\n".join(out) if out else "(none)")
    except Exception:
        return ""


def _context(agent_id):
    return _dyson_context() if agent_id == "dyson" else _eco_context()


# --- brain skills (actively learned playbook, mtime-cached) ------------------
def _load_skills(agent_id):
    """The agent's playbook = the forge-agency seed + the brain-learned vault
    version. mtime-cached per agent (keyed in _SK_CACHE), so a self-improve write
    or a manual vault edit is picked up on the next prompt. Returns "" if none."""
    try:
        import brain_io
        parts, sig = [], []
        srcs = []
        for d in SEED_SKILLS_DIRS:
            p = d / f"{agent_id}-playbook.md"
            if p.is_file():
                srcs.append(p)
                break  # first existing seed wins
        srcs.append(brain_io.VAULT / "Skills" / f"{agent_id}-playbook.md")
        for p in srcs:
            if p.is_file():
                parts.append(p.read_text(errors="ignore"))
                sig.append(p.stat().st_mtime)
        sig = tuple(sig)
        cached = _SK_CACHE.get(agent_id)
        if not cached or cached[0] != sig:
            text = "\n\n".join(parts)
            _SK_CACHE[agent_id] = (sig, text)
            return text
        return cached[1]
    except Exception:
        cached = _SK_CACHE.get(agent_id)
        return cached[1] if cached else ""


def _skills_block(agent_id):
    """The system-prompt fragment that injects the learned playbook (or "")."""
    skills = _load_skills(agent_id)
    if skills:
        return ("\n\n=== YOUR PLAYBOOK (learned from the brain — apply it) ===\n"
                + skills[:3000])
    return ""


def _history_block(history, limit=10):
    lines = []
    for h in (history or [])[-limit:]:
        who = "OPERATOR" if h.get("role") == "user" else "YOU"
        txt = (h.get("text") or "").strip()
        if txt:
            lines.append(f"{who}: {txt}")
    return ("\n".join(lines) + "\n") if lines else ""


# --- public API --------------------------------------------------------------
def status():
    key, src = _agency_key()
    with _LOCK:
        d = _load()
        tasks = d.get("tasks", [])
        hist = d.get("history", {})
        learn = d.get("learn", {})
    agents = []
    for aid in AGENT_ORDER:
        a = _AGENTS[aid]
        at = [t for t in tasks if t.get("agentId") == aid]
        last = max([t.get("createdAt", 0) for t in at]
                   + [h.get("ts", 0) for h in hist.get(aid, [])] + [0])
        ls = learn.get(aid, {}) or {}
        agents.append({
            "id": a["id"], "name": a["name"], "role": a["role"],
            "kind": a["kind"], "blurb": a["blurb"], "page": a["page"],
            "online": bool(key),
            "openTasks": len([t for t in at if t.get("status") in ("queued", "planned", "working")]),
            "totalTasks": len(at),
            "messages": len(hist.get(aid, [])),
            "lastActive": last or None,
            "skillsLoaded": bool(_load_skills(aid)),
            "learnCount": ls.get("learnCount", 0),
            "lastLearnedAt": ls.get("lastLearnedAt"),
        })
    brain_ok = False
    try:
        import brain_io
        brain_ok = bool(brain_io.available())
    except Exception:
        brain_ok = False
    return {"agents": agents, "connected": bool(key), "keySource": src,
            "model": review_agent.MODEL, "brain": brain_ok}


def history(agent_id):
    with _LOCK:
        d = _load()
        return {"history": d.get("history", {}).get(agent_id, [])}


def list_tasks(agent_id=None):
    with _LOCK:
        d = _load()
        tasks = d.get("tasks", [])
    if agent_id:
        tasks = [t for t in tasks if t.get("agentId") == agent_id]
    tasks = sorted(tasks, key=lambda t: t.get("createdAt") or 0, reverse=True)
    return {"tasks": tasks, "count": len(tasks)}


def chat(agent_id, message, history_in=None):
    agent = _AGENTS.get(agent_id)
    if not agent:
        return {"error": "unknown agent"}
    message = (message or "").strip()
    if not message:
        return {"reply": "Tell me what you need and I'll get on it."}
    key, src = _agency_key()
    if not key:
        return {"needsKey": True, "connected": False,
                "reply": "I'm not connected yet — add ANTHROPIC_API_KEY to "
                         "forge-agency/config/agency.env, then reload."}

    system = (agent["system"] + "\n\n=== LIVE CONTEXT ===\n" + _context(agent_id)
              + _skills_block(agent_id))
    if agent_id == "dyson":                 # code/website agent → pull the graphify code-graph
        try:
            import agent_context
            g = agent_context.graphify_context(message)
            if g:
                system += ("\n\n=== CODEBASE GRAPH (graphify — relevant repos/files/modules for this ask) ===\n" + g)
        except Exception:  # noqa: BLE001
            pass
    user = _history_block(history_in) + f"OPERATOR: {message}\nYOU:"
    try:
        reply = review_agent._claude(key, system, user, max_tokens=700)
    except Exception as e:  # noqa: BLE001
        return {"connected": True, "reply": f"Hit an error reaching my brain: {e}"}

    now = int(time.time() * 1000)
    with _LOCK:
        d = _load()
        h = d.setdefault("history", {}).setdefault(agent_id, [])
        h.append({"role": "user", "text": message, "ts": now})
        h.append({"role": "agent", "text": reply or "On it.", "ts": now + 1})
        d["history"][agent_id] = h[-60:]  # keep last 60 turns synced
        ls = d.setdefault("learn", {}).setdefault(agent_id, {})
        ls["sinceLearn"] = ls.get("sinceLearn", 0) + 1
        _save(d)
    _maybe_learn(agent_id, key)
    return {"reply": reply or "On it.", "agent": agent["name"],
            "connected": True, "keySource": src}


def send_task(agent_id, title):
    """Queue a task and have the agent draft how it will handle it (Claude)."""
    agent = _AGENTS.get(agent_id)
    if not agent:
        return {"error": "unknown agent"}
    title = (title or "").strip()
    if not title:
        return {"error": "task title required"}
    key, src = _agency_key()

    plan = ""
    status_ = "queued"
    if key:
        system = (agent["system"] + "\n\n=== LIVE CONTEXT ===\n" + _context(agent_id)
                  + _skills_block(agent_id)
                  + "\n\nThe operator just assigned you a TASK. Reply with a short, "
                  "concrete plan for how you'll handle it (3-6 lines). Remember: you "
                  "plan and queue for approval, you do not execute live yet.")
        if agent_id == "dyson":
            try:
                import agent_context
                g = agent_context.graphify_context(title)
                if g:
                    system += ("\n\n=== CODEBASE GRAPH (graphify — relevant repos/files/modules) ===\n" + g)
            except Exception:  # noqa: BLE001
                pass
        try:
            plan = review_agent._claude(key, system, f"TASK: {title}\n\nYour plan:", max_tokens=500)
            status_ = "planned"
        except Exception as e:  # noqa: BLE001
            plan = f"(couldn't draft a plan: {e})"

    now = int(time.time() * 1000)
    with _LOCK:
        d = _load()
        d["seq"] = d.get("seq", 0) + 1
        task = {
            "id": f"t{d['seq']}_{now}", "agentId": agent_id,
            "agentName": agent["name"], "title": title,
            "plan": plan, "status": status_,
            "createdAt": now, "updatedAt": now,
        }
        d.setdefault("tasks", []).append(task)
        ls = d.setdefault("learn", {}).setdefault(agent_id, {})
        ls["sinceLearn"] = ls.get("sinceLearn", 0) + 1
        _save(d)
    try:
        import agent_bus
        agent_bus.send(agent_id, "all", "status",
                       f"{agent['name']} queued: {title}",
                       {"taskId": task["id"], "status": status_})
    except Exception:
        pass
    _maybe_learn(agent_id, key)
    return {"ok": True, "task": task}


def update_task(task_id, status_new):
    allowed = ["queued", "planned", "working", "done", "cancelled"]
    if status_new not in allowed:
        return {"error": f"status must be one of {allowed}"}
    with _LOCK:
        d = _load()
        t = next((x for x in d.get("tasks", []) if x.get("id") == task_id), None)
        if not t:
            return {"error": "task not found"}
        t["status"] = status_new
        t["updatedAt"] = int(time.time() * 1000)
        _save(d)
        return {"ok": True, "task": t}


# --- self-improvement (learn from every encounter, rewrite own playbook) -----
def learn(agent_id, auto=False):
    """Claude reflects on the agent's recent chat + tasks and its current playbook,
    then rewrites the playbook into the Obsidian brain (Skills/<id>-playbook.md,
    git-committed). Next prompt reloads it — closed adaptive loop. Mirrors
    scout_triage.learn. Dyson rewrites an edit/build rubric, Eco an ads rubric."""
    agent = _AGENTS.get(agent_id)
    if not agent:
        return {"error": "unknown agent"}
    key, _src = _agency_key()
    if not key:
        return {"error": "no anthropic key"}

    # Gather the agent's recent real encounters: last ~12 chat turns + last ~8 tasks.
    with _LOCK:
        d = _load()
        hist = (d.get("history", {}).get(agent_id, []) or [])[-12:]
        tasks = sorted([t for t in d.get("tasks", []) if t.get("agentId") == agent_id],
                       key=lambda t: t.get("createdAt") or 0, reverse=True)[:8]
    lines = []
    for h in hist:
        who = "OPERATOR" if h.get("role") == "user" else "YOU"
        txt = (h.get("text") or "").strip().replace("\n", " ")
        if txt:
            lines.append(f"[chat] {who}: {txt[:200]}")
    for t in tasks:
        plan = (t.get("plan") or "").strip().replace("\n", " ")
        lines.append(f"[task:{t.get('status')}] {t.get('title')} :: {plan[:200]}")
    if not lines:
        return {"error": "no encounters to learn from yet"}

    current = _load_skills(agent_id) or "(no playbook yet — create one)"
    name = agent["name"]
    if agent_id == "eco":
        rubric = ("an ADS rubric a strategist follows: how to read Meta ad metrics "
                  "(spend, CPL, ROAS, CTR), how to spot winners vs losers, how to "
                  "structure new ad concepts (hook, headline, primary text, CTA, "
                  "creative direction), budget/scaling rules, and hard rules "
                  "(recommend only — campaigns launch after operator approval).")
    else:
        rubric = ("an EDIT/BUILD rubric an edit agent follows: how to scope a "
                  "website/code change into a PLAN (affected files/pages/workflows, "
                  "risk level with a reason, numbered implementation steps), how to "
                  "judge risk, common patterns/pitfalls, and hard rules (nothing "
                  "goes live until operator approval; never claim work is done).")
    system = (
        f"You are {name}, a SELF-IMPROVING agent for Forge AI Agency, based on this "
        f"role:\n{agent['system']}\n\nBelow is your CURRENT playbook and a sample of "
        "your real recent work (chats + task plans). Improve yourself: sharpen what "
        "worked, drop what didn't, and add new patterns you notice. Output the FULL "
        "UPDATED playbook as clean markdown — " + rubric + " Keep it tight and "
        "actionable. Output ONLY the markdown."
    )
    user = ("CURRENT PLAYBOOK:\n" + current[:4000]
            + "\n\nRECENT REAL WORK (your own — learn from these):\n"
            + "\n".join(lines))
    try:
        new_md = review_agent._claude(key, system, user, max_tokens=2000)
    except Exception as e:  # noqa: BLE001
        return {"error": f"claude: {e}"}
    if not new_md or len(new_md) < 200:
        return {"error": "learning produced nothing usable"}

    stamp = time.strftime("%Y-%m-%d %H:%M")
    header = (f"---\nagent: {agent_id}\nupdated: {stamp}\n"
              f"source: self-improvement (learned from {len(lines)} recent encounters)\n---\n\n")
    rel = PLAYBOOK_REL[agent_id]
    try:
        import brain_io
        res = brain_io.write_note(rel, header + new_md.strip(),
                                  reason=f"{name} self-improve {stamp}")
    except Exception as e:  # noqa: BLE001
        return {"error": f"brain write failed: {e}"}

    now = int(time.time() * 1000)
    with _LOCK:
        d = _load()
        ls = d.setdefault("learn", {}).setdefault(agent_id, {})
        ls["lastLearnedAt"] = now
        ls["learnCount"] = ls.get("learnCount", 0) + 1
        ls["sinceLearn"] = 0
        count = ls["learnCount"]
        h = d.setdefault("history", {}).setdefault(agent_id, [])
        h.append({"role": "agent",
                  "text": f"(self-improved my playbook from {len(lines)} recent "
                          f"encounters — update #{count})",
                  "ts": now, "system": True})
        d["history"][agent_id] = h[-60:]
        _save(d)
    _SK_CACHE.pop(agent_id, None)  # force reload of the freshly-written playbook
    try:
        import agent_bus
        agent_bus.send(agent_id, "all", "status",
                       f"{name} updated its playbook (self-improvement #{count}).",
                       {"learnCount": count})
    except Exception:
        pass
    return {"ok": True, "learnCount": count, "wrote": rel,
            "fromEncounters": len(lines),
            "committed": (res or {}).get("committed"), "auto": auto}


def _maybe_learn(agent_id, key):
    """Auto self-improve once enough fresh encounters accrue, rate-limited so it
    can't run too often. Mirrors scout_triage._maybe_learn."""
    if not key:
        return
    now = int(time.time() * 1000)
    with _LOCK:
        d = _load()
        ls = d.get("learn", {}).get(agent_id, {}) or {}
        since = ls.get("sinceLearn", 0)
        last = ls.get("lastLearnedAt") or 0
    if since >= AGENCY_LEARN_EVERY and (now - last) >= LEARN_MIN_INTERVAL_MS:
        try:
            learn(agent_id, auto=True)
        except Exception:
            pass
