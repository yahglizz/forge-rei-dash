"""agent_office.py — the 3D Agent Office backend: every FORGE agent live at a desk.

The 3D floor (office_scene.js) is driven entirely by this module. Orion, the kid CEO,
oversees the real business agents. Four jobs, and nothing more:

  state()    What is every agent doing RIGHT NOW — derived only from real signals:
             a live job in this module, an open task in agents_hub, recent agent_bus
             traffic, and the engine's own status(). Never invented; an agent we can't
             reach reads "unknown", not "idle".

  dispatch() The operator (or Orion's owner-approved plan) gives an agent a task. This
             files it as a normal agents_hub task AND actually runs that agent's real
             brain in a background thread, appending a step log the floor animates
             against. So "you can see them doing it" and "they actually do it" are the
             same code path.

  checkin()  Orion checks in on the team: reads each agent's live job, last result,
             errors and open tasks and gives a verdict (working / on_track / waiting /
             idle / attention / blocked) plus owner-approvable follow-up suggestions.
             Zero Claude calls — every line is a fact from a real signal, so it works
             even when the AI account is out of credits. Read-only; never acts.

  chat()     Office chat with an agent. Goes to the agent's real brain; if the AI
             provider is unreachable, answers from the live floor instead and SAYS so
             (offline=True) — never pretends to reason.

Autonomy (CLAUDE.md rule 2) is unchanged. A dispatched task runs the agent's THINKING —
the same chat/analyze brain the Agents tab already calls, creed-loaded and grounded.
It never sends an SMS, launches an ad, moves a pipeline, or writes a system of record.
The output is a proposal the operator still taps to execute.

State lives in memory only (marcus_state/ holds the durable half via agents_hub +
agent_bus). A restart clears the job log and check-ins; the tasks and bus notes survive.
"""
import json
import threading
import time

# Departments = the dashboard's four workspaces. Each agent id here must match the id
# agents_hub/dropship uses, because that's what we route a dispatched task to.
# One main agent per business (2026-09-30). Scout/Atlas/Follow-up are Marcus's lanes and Eco is
# Dyson's: they keep their engines but have no character of their own (agents_hub.LANE_OF).
DEPARTMENTS = [
    {"id": "rei", "label": "Wholesale · REI", "accent": "#4F7CFF",
     "agents": ["marcus"]},
    {"id": "agency", "label": "Agency · ClientForge", "accent": "#8B5CF6",
     "agents": ["dyson"]},
    {"id": "daycare", "label": "Daycare · A Touch of Blessings", "accent": "#2DD4BF",
     "agents": ["solomon"]},
    {"id": "dropship", "label": "Dropship · FORGE Store", "accent": "#F97316",
     "agents": ["midas"]},
]

# Midas lives in dropship_director, not agents_hub's roster, so his card is defined
# here. Everyone else is read from agents_hub so there is exactly one source of truth
# for a name/role/blurb. (Hawk/Blaze/Otto were merged into Midas 2026-07-25.)
DROPSHIP_AGENTS = {
    "midas": {"id": "midas", "name": "Midas", "business": "dropship", "emoji": "👑",
              "role": "E-com Director — the whole store",
              "blurb": "Product research, ads, fulfillment, and the ranked brief over "
                       "all three. Proposes only — never spends or ships."},
}

DEPT_OF = {a: d["id"] for d in DEPARTMENTS for a in d["agents"]}
DEPT_OF["orion"] = "cross"
# Lane ids still resolve (an old bus message / task / Telegram "scout:" names one): they map to
# the main agent's department and dispatch() files the job under the main agent.
LANE_OF = {"scout": "marcus", "atlas": "marcus", "eco": "dyson"}
for _lane, _main in LANE_OF.items():
    DEPT_OF[_lane] = DEPT_OF[_main]

# How long after a bus message an agent still reads as "reporting" on the floor.
REPORTING_WINDOW_MS = 90_000
MAX_JOBS = 60
STALL_MS = 180_000          # a running job older than this is flagged by Orion's check-in
MAX_CHECKINS = 20
AUTO_CHECKIN = True         # Orion reviews each job the moment it finishes (selfcheck turns it off)

_LOCK = threading.Lock()
_JOBS = []          # newest first, capped at MAX_JOBS
_SEQ = 0
_CHECKINS = []      # Orion's reviews, newest first, capped at MAX_CHECKINS
_CSEQ = 0


# ── roster ────────────────────────────────────────────────────────────────────
def _hub_agents():
    """The agents_hub agents keyed by id. {} if the hub can't be imported."""
    try:
        import agents_hub
        return {a["id"]: a for a in agents_hub.AGENTS}
    except Exception:
        return {}


def _archived():
    """Archived business ids (business_scope). Fails OPEN: nothing archived."""
    try:
        import business_scope
        return business_scope.archived()
    except Exception:
        return set()


def _card(agent_id):
    """Name/role/blurb for one agent — hub first, dropship table second."""
    return _hub_agents().get(agent_id) or DROPSHIP_AGENTS.get(agent_id) or {
        "id": agent_id, "name": agent_id.title(), "business": DEPT_OF.get(agent_id, ""),
        "emoji": "🤖", "role": "", "blurb": ""}


# agent id -> the attribute the connector holds that engine under. Agents with no
# background engine (Marcus's screener, Dyson, Eco) are simply absent.
_ENGINE_ATTR = {
    "scout": "SCOUT", "marcus": "MARCUS", "atlas": "DEAL_PREP",
    "solomon": "SOLOMON", "midas": "MIDAS", "orion": "ORION",
}


def _engine(agent_id):
    """The live engine instance for an agent, or None. Read-only, same lookup shape as
    agents_hub._engine — extended with the dropship director. The id is checked
    BEFORE importing the connector so an unknown agent costs nothing."""
    attr = _ENGINE_ATTR.get(agent_id)
    if not attr:
        return None
    try:
        import connector
    except Exception:
        return None
    return getattr(connector, attr, None)


# ── activity derivation (every branch is a real signal) ───────────────────────
def _live_job(agent_id):
    """The newest still-running job for this agent, or None."""
    with _LOCK:
        for j in _JOBS:
            if j["agentId"] == agent_id and j["status"] == "running":
                return dict(j)
    return None


def _last_job(agent_id):
    with _LOCK:
        for j in _JOBS:
            if j["agentId"] == agent_id:
                return dict(j)
    return None


def _bus_index(limit=120):
    """agent_id -> (newest ts it sent, that message's text). {} when the bus is down."""
    try:
        import agent_bus
        msgs = (agent_bus.recent(limit=limit) or {}).get("messages", []) or []
    except Exception:
        return {}
    out = {}
    for m in msgs:                      # newest first — first hit per sender wins
        frm = m.get("from")
        if frm and frm not in out:
            out[frm] = (m.get("ts") or 0, (m.get("text") or "")[:160])
    return out


def _open_tasks():
    """agent_id -> count of open tasks in the agents_hub store."""
    try:
        import agents_hub
        rows = (agents_hub.tasks() or {}).get("tasks", []) or []
    except Exception:
        return {}
    out = {}
    for t in rows:
        if t.get("status") == "open":
            out[t.get("agentId")] = out.get(t.get("agentId"), 0) + 1
    return out


def _engine_health(agent_id):
    """(reachable, healthy, detail). reachable=False means we genuinely can't see it —
    the floor renders that as "unknown", never as idle.

    Dyson and Eco have no background engine at all: their brain is agency_agents.chat,
    which is always reachable. Only an agent that SHOULD have an engine and doesn't
    counts as unreachable — otherwise a chat-only agent reads as broken forever."""
    if agent_id not in _ENGINE_ATTR:
        return True, True, ""
    lanes = [l for l, m in LANE_OF.items() if m == agent_id and l in _ENGINE_ATTR]
    if lanes:   # Marcus: his own screening engine AND the Scout / Atlas lanes
        worst = (True, True, "")
        for aid in [agent_id] + lanes:
            r = _engine_health_one(aid)
            if not r[0] and not worst[0] is False:
                worst = r if worst[1] else worst
            if r[0] and not r[1]:
                return r
        return worst
    return _engine_health_one(agent_id)


def _engine_health_one(agent_id):
    eng = _engine(agent_id)
    if eng is None:
        return False, False, ""
    try:
        st = eng.status() if hasattr(eng, "status") else {}
    except Exception as e:  # noqa: BLE001
        return True, False, str(e)[:120]
    if not isinstance(st, dict):
        return True, True, ""
    err = st.get("lastError")
    if err:
        return True, False, str(err)[:120]
    if st.get("aiReady") is False:
        return True, False, "no AI key"
    return True, True, ""


def _activity(agent_id, bus_idx, task_counts, now_ms):
    """One agent's floor state. Order matters: doing-it-now beats just-finished beats
    has-work-waiting beats resting."""
    job = _live_job(agent_id)
    if job:
        steps = job.get("steps") or []
        phase = steps[-1]["phase"] if steps else "walk"
        return {"activity": phase, "detail": steps[-1]["text"] if steps else "starting",
                "jobId": job["id"], "since": job["startedAt"]}

    reachable, healthy, detail = _engine_health(agent_id)
    if reachable and not healthy:
        return {"activity": "error", "detail": detail or "engine unhealthy"}

    ts, text = bus_idx.get(agent_id, (0, ""))
    if ts and (now_ms - ts) < REPORTING_WINDOW_MS:
        return {"activity": "reporting", "detail": text, "since": ts}

    n = task_counts.get(agent_id, 0)
    if n:
        return {"activity": "queued",
                "detail": f"{n} open task{'s' if n != 1 else ''}"}

    if not reachable:
        # No engine instance (UI-only Mac, or an agent whose brain is chat-only).
        return {"activity": "unknown", "detail": "no live engine on this host"}
    return {"activity": "idle", "detail": text or "waiting for work"}


def state(business=None):
    """The whole floor. `business` scopes to one department; None returns every
    non-archived one."""
    now_ms = int(time.time() * 1000)
    bus_idx = _bus_index()
    task_counts = _open_tasks()
    # No scope -> every ACTIVE department (archived ones drop off the floor; asking
    # for one by name still works, so an archived workspace can be viewed read-only).
    arch = _archived()
    depts = [d for d in DEPARTMENTS
             if (d["id"] == business if business else d["id"] not in arch)]

    out = []
    for d in depts:
        agents = []
        for aid in d["agents"]:
            row = dict(_card(aid))
            row["dept"] = d["id"]
            row.update(_activity(aid, bus_idx, task_counts, now_ms))
            row["openTasks"] = task_counts.get(aid, 0)
            last = _last_job(aid)
            if last:
                row["lastJob"] = {"id": last["id"], "title": last["title"],
                                  "status": last["status"],
                                  "finishedAt": last.get("finishedAt")}
            agents.append(row)
        out.append({"id": d["id"], "label": d["label"], "accent": d["accent"],
                    "agents": agents})

    director = dict(_card("orion"))
    director.update(_activity("orion", bus_idx, task_counts, now_ms))
    director["openTasks"] = task_counts.get("orion", 0)
    try:
        import agent_bus
        messages = agent_bus.recent(limit=30).get("messages", [])
    except Exception:
        messages = []
    active_ids = {a["id"] for d in out for a in d["agents"]} | {"orion", "operator", "all"}
    messages = [m for m in messages if m.get("from") in active_ids
                and m.get("to") in active_ids][:12]
    with _LOCK:
        running = sum(1 for j in _JOBS if j["status"] == "running")
    return {"ok": True, "now": now_ms, "departments": out, "running": running,
            "business": business, "director": director, "messages": messages,
            "checkin": latest_checkin(), "ai": _ai_state()}


def plan(message, chat_fn):
    """Orion proposes assignments; this never dispatches them. The owner reviews first."""
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        return {"error": "Enter a request of 1–4000 characters"}
    floor = state()
    active = {a["id"] for d in floor["departments"] for a in d["agents"]}
    prompt = ("Plan internal analytical tasks for this OWNER request. Do not execute anything. "
              "Return ONLY valid JSON: {\"summary\":\"short explanation\",\"assignments\":"
              "[{\"agentId\":\"an active id\",\"title\":\"specific task\",\"note\":\"context\"}]}. "
              "At most one assignment per agent, at most 6 total. Only use active ids: "
              + ", ".join(sorted(active)) + ". No seller/customer messages, ad spending, "
              "invoices, deployments or system-of-record writes. If no internal task is "
              "appropriate, use an empty assignments array. CURRENT OFFICE: "
              + json.dumps(floor, default=str)[:9000] + "\nOWNER REQUEST: " + message.strip())
    out = chat_fn("orion", prompt)
    if not isinstance(out, dict):
        return {"error": "Orion unavailable"}
    if out.get("error") or out.get("needsKey"):
        return {"error": out.get("error") or out.get("reply") or "Orion unavailable"}
    if not isinstance(out.get("reply"), str):
        return {"error": "Orion returned an invalid plan. No tasks were assigned."}
    raw = out["reply"].strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        proposal = json.loads(raw)
    except (ValueError, TypeError):
        return {"error": "Orion returned an unreadable plan. No tasks were assigned."}
    if not isinstance(proposal, dict) or not isinstance(proposal.get("assignments"), list):
        return {"error": "Orion returned an invalid plan. No tasks were assigned."}
    assignments, seen = [], set()
    for row in proposal["assignments"]:
        if not isinstance(row, dict):
            return {"error": "Invalid assignment. No tasks were assigned."}
        aid, title, note = row.get("agentId"), row.get("title"), row.get("note", "")
        if (not isinstance(aid, str) or aid not in active or aid in seen or not isinstance(title, str) or not title.strip()
                or len(title) > 600 or not isinstance(note, str) or len(note) > 4000):
            return {"error": "Invalid assignment. No tasks were assigned."}
        seen.add(aid)
        assignments.append({"agentId": aid, "title": title.strip(), "note": note.strip()})
    summary = proposal.get("summary", "Review these assignments.")
    if len(assignments) > 6 or not isinstance(summary, str) or len(summary) > 2000:
        return {"error": "Invalid plan. No tasks were assigned."}
    return {"ok": True, "summary": summary, "assignments": assignments}


# ── jobs (an agent visibly doing the work, and actually doing it) ─────────────
def _step(job_id, phase, text):
    with _LOCK:
        for j in _JOBS:
            if j["id"] == job_id:
                j["steps"].append({"phase": phase, "text": text,
                                   "ts": int(time.time() * 1000)})
                return


def _finish(job_id, status, result="", error=""):
    with _LOCK:
        for j in _JOBS:
            if j["id"] == job_id:
                j["status"] = status
                j["result"] = result
                j["error"] = error
                j["finishedAt"] = int(time.time() * 1000)
                return


def _run(job, chat_fn):
    """Run the job, then Orion reviews the result (auto check-in on that one agent)."""
    try:
        _run_job(job, chat_fn)
    finally:
        if AUTO_CHECKIN:
            try:
                checkin("auto", only=job["agentId"])
            except Exception:  # noqa: BLE001 — a review must never kill the worker
                pass


def _run_job(job, chat_fn):
    """The worker. Every step is announced BEFORE the work so the floor animates the
    thing that is actually happening, not a canned sequence."""
    jid, aid, title = job["id"], job["agentId"], job["title"]
    note = job.get("note") or ""
    try:
        _step(jid, "walk", "heading to the desk")
        _step(jid, "read", "loading creed, playbook and live data")

        # Every agent — all four businesses — answers the ACTUAL task through its own
        # brain (agents_hub.chat → the creed + playbook + live data for its business).
        # Dropship used to be special-cased into "rebuild the brief", which meant Midas
        # replied with a canned line no matter what you asked him. Now that he's in the
        # hub roster he goes through the same path as everyone else.
        prompt = title if not note else f"{title}\n\nContext from the operator: {note}"
        if chat_fn is None:
            reply, err = "", "no brain wired for this agent on this host"
        else:
            _step(jid, "think", "working the task")
            try:
                out = chat_fn(aid, prompt)
            except Exception as e:  # noqa: BLE001
                out, err = None, str(e)[:300]
            else:
                err = ""
            if err:
                reply = ""
            elif isinstance(out, dict):
                reply = out.get("reply") or out.get("answer") or ""
                if out.get("needsKey"):
                    err = reply or "no Anthropic key"
                    reply = ""
                elif out.get("error"):     # the brain failed (e.g. out of credits)
                    err = str(out["error"])[:300]
                    reply = ""
            else:
                reply = str(out or "")

        if err or not reply:
            _step(jid, "error", err or "no answer came back")
            _fail_task(job, err or "no answer came back")   # before _finish: pollers
            _finish(jid, "error", error=err or "no answer came back")   # see both at once
            return

        _step(jid, "report", "writing up the answer")
        head = reply.strip().split("\n")[0][:180]
        try:
            import agent_bus
            agent_bus.send(aid, job.get("directedBy") or "operator", "note", f"Task done — {head}",
                           {"taskId": job.get("taskId"), "jobId": jid})
        except Exception:
            pass
        try:
            import agents_hub
            if job.get("taskId"):
                agents_hub.update_task(job["taskId"], "done")
        except Exception:
            pass
        _step(jid, "done", head)
        _finish(jid, "done", result=reply)
    except Exception as e:  # noqa: BLE001 — a worker thread must never take the box down
        _step(jid, "error", str(e)[:200])
        _fail_task(job, str(e))
        _finish(jid, "error", error=str(e)[:300])


def _fail_task(job, err):
    """The hub task behind an errored run → failed (with the reason), never left open."""
    try:
        import agents_hub
        if job.get("taskId"):
            agents_hub.update_task(job["taskId"], "failed", error=err)
    except Exception:
        pass


def dispatch(agent_id, title, note="", chat_fn=None, directed_by=""):
    """Give an agent a task from the floor: file it, then actually run it.

    chat_fn(agent_id, message) -> the agents_hub chat bound to this GHL sub-account.
    The connector supplies it (same pattern as agents_hub.coach_ask) so this module
    stays connector-free and importable on its own.
    """
    global _SEQ
    if (not isinstance(agent_id, str) or not isinstance(title, str)
            or not isinstance(note, str) or directed_by not in ("", "orion")):
        return {"error": "invalid task"}
    agent_id = agent_id.strip()
    title = title.strip()
    if agent_id not in DEPT_OF:
        return {"error": "unknown agent"}
    if not title:
        return {"error": "a task needs a title"}
    if len(title) > 600 or len(note) > 4000:
        return {"error": "task is too long"}
    if directed_by and (agent_id == "orion" or DEPT_OF[agent_id] in _archived()):
        return {"error": "Orion can direct active team agents only"}
    if _live_job(agent_id):
        return {"error": f"{_card(agent_id)['name']} is already on a task"}

    task_id = ""
    try:
        import agents_hub
        # Every agent on the floor is a hub agent now, so every task gets a store row.
        if agent_id in _hub_agents():
            out = agents_hub.send_task(agent_id, title, note)
            task_id = ((out or {}).get("task") or {}).get("id", "")
    except Exception:
        pass

    now = int(time.time() * 1000)
    with _LOCK:
        _SEQ += 1
        job = {"id": f"j{_SEQ}_{now}", "agentId": agent_id,
               "agentName": _card(agent_id)["name"], "dept": DEPT_OF[agent_id],
               "title": title, "note": note.strip(), "taskId": task_id,
               "directedBy": directed_by,
               "status": "running", "startedAt": now, "steps": [],
               "result": "", "error": ""}
        _JOBS.insert(0, job)
        del _JOBS[MAX_JOBS:]

    if directed_by:
        try:
            import agent_bus
            agent_bus.send("orion", agent_id, "task", f"Owner-approved assignment: {title}",
                           {"taskId": task_id, "jobId": job["id"], "approvedBy": "operator"})
        except Exception:
            pass
    threading.Thread(target=_run, args=(dict(job), chat_fn), daemon=True).start()
    return {"ok": True, "job": {k: v for k, v in job.items() if k != "steps"},
            "jobId": job["id"], "taskId": task_id}


def job(job_id):
    """One job with its full step log — what the floor polls while an agent works."""
    with _LOCK:
        for j in _JOBS:
            if j["id"] == job_id:
                return {"ok": True, "job": dict(j)}
    return {"ok": False, "error": "unknown job"}


def jobs(business=None, limit=20):
    """Recent jobs (newest first) — the floor's activity ticker."""
    try:
        limit = max(1, min(int(limit), MAX_JOBS))
    except (TypeError, ValueError):
        limit = 20
    with _LOCK:
        rows = [dict(j) for j in _JOBS if not business or j["dept"] == business]
    for r in rows:
        r["steps"] = r["steps"][-6:]
    return {"ok": True, "jobs": rows[:limit]}


# ── Orion's check-ins (real signals only, zero Claude) ────────────────────────
_AI_DOWN_WORDS = ("credit balance", "billing", "anthropic", "api key", "ai key", "needs an ai",
                  "overloaded", "rate limit", "timed out", "couldn't reach", "no brain")


def _ai_state():
    """{ok, reason} for the AI provider — the floor shows it so a stuck agent is explained."""
    try:
        import forge_heartbeat
        h = forge_heartbeat.ai_health()
        return {"ok": bool(h.get("ok")), "reason": h.get("reason") if not h.get("ok") else None}
    except Exception:
        return {"ok": True, "reason": None}


def _ai_problem(err):
    e = (err or "").lower()
    return any(w in e for w in _AI_DOWN_WORDS)


def _open_task_titles():
    """agent_id -> [titles of open hub tasks], oldest first."""
    try:
        import agents_hub
        rows = (agents_hub.tasks() or {}).get("tasks", []) or []
    except Exception:
        return {}
    out = {}
    for t in reversed(rows):
        if t.get("status") == "open" and t.get("title"):
            out.setdefault(t.get("agentId"), []).append(t["title"])
    return out


def _short(text, n=140):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _review_agent(a, now_ms, open_titles, live=None, last=None):
    """One agent's verdict, from one row of state() plus its job history. Precedence:
    doing-it-now, then a sick engine, then the last run's outcome, then waiting work."""
    aid, name = a["id"], a.get("name") or a["id"]
    live = live if live is not None else _live_job(aid)
    last = last if last is not None else _last_job(aid)
    r = {"agentId": aid, "name": name, "verdict": "idle", "text": "nothing assigned",
         "jobId": None, "title": ""}
    titles = open_titles.get(aid) or []
    if live:
        age = now_ms - live["startedAt"]
        steps = live.get("steps") or []
        step = steps[-1]["text"] if steps else "starting"
        r.update(jobId=live["id"], title=live["title"])
        if age > STALL_MS:
            r.update(verdict="attention", text=f"stalled — on \"{_short(live['title'], 60)}\" for "
                     f"{age // 60000} min, last step: {step}")
        else:
            r.update(verdict="working", text=f"working on \"{_short(live['title'], 60)}\" — {step}")
    elif a.get("activity") == "error":
        detail = a.get("detail") or "engine unhealthy"
        r.update(verdict="blocked" if _ai_problem(detail) else "attention",
                 text=f"engine problem — {_short(detail)}")
    elif a.get("activity") == "unknown":
        r.update(verdict="attention", text="not reachable — no live engine on this host")
    elif last and last["status"] == "error":
        err = last.get("error") or "no answer came back"
        r.update(jobId=last["id"], title=last["title"])
        if _ai_problem(err):
            r.update(verdict="blocked", text=f"could not run \"{_short(last['title'], 60)}\" — "
                     f"the AI is unavailable ({_short(err, 90)})")
        else:
            r.update(verdict="attention", text=f"\"{_short(last['title'], 60)}\" failed — {_short(err, 110)}")
    elif last and last["status"] == "done":
        res = (last.get("result") or "").strip()
        r.update(jobId=last["id"], title=last["title"])
        if res:
            r.update(verdict="on_track", text=f"delivered \"{_short(last['title'], 60)}\" — {_short(res.split(chr(10))[0], 110)}")
        else:
            r.update(verdict="attention", text=f"finished \"{_short(last['title'], 60)}\" but returned nothing")
    elif titles:
        r.update(verdict="waiting", title=titles[0],
                 text=f"{len(titles)} open task{'s' if len(titles) != 1 else ''} not started — \"{_short(titles[0], 70)}\"")
    if r["verdict"] in ("idle", "on_track") and titles and not live:
        r["text"] += f" · {len(titles)} open task{'s' if len(titles) != 1 else ''} waiting"
    return r


def _suggest(reviews, open_titles, last_by):
    """Follow-ups Orion would assign. PROPOSALS ONLY — the owner taps Approve & assign.
    Waiting agents start their oldest open task; a non-AI failure is retried once."""
    out = []
    for r in reviews:
        aid = r["agentId"]
        if r["verdict"] == "waiting" and open_titles.get(aid):
            out.append({"agentId": aid, "title": open_titles[aid][0],
                        "note": "Open task from the task list that nobody has started."})
        elif r["verdict"] == "attention" and r.get("jobId") and (last_by.get(aid) or {}).get("status") == "error":
            last = last_by[aid]
            out.append({"agentId": aid, "title": "Retry: " + last["title"],
                        "note": "The previous run failed: " + _short(last.get("error"), 200)})
    return out[:6]


_SEVERITY = {"attention": 0, "blocked": 1, "working": 2, "waiting": 3, "on_track": 4, "idle": 5}


def _build_checkin(by, only, floor):
    now = floor["now"]
    agents = [a for d in floor["departments"] for a in d["agents"]]
    if only:
        agents = [a for a in agents if a["id"] == only]
    titles = _open_task_titles()
    last_by = {a["id"]: (_last_job(a["id"]) or {}) for a in agents}
    reviews = [_review_agent(a, now, titles) for a in agents]
    reviews.sort(key=lambda r: _SEVERITY.get(r["verdict"], 9))
    tally = {}
    for r in reviews:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    names = {"attention": "need attention", "blocked": "blocked", "working": "working",
             "waiting": "waiting", "on_track": "on track", "idle": "idle"}
    parts = [f"{n} {names[k]}" for k, n in sorted(tally.items(), key=lambda kv: _SEVERITY.get(kv[0], 9))]
    ai = floor.get("ai") or {}
    summary = (f"Checked {len(reviews)} agent{'s' if len(reviews) != 1 else ''}: " + ", ".join(parts) + "."
               if reviews else "No active agents to check.")
    if ai.get("ok") is False:
        summary += " AI is down — " + _short(ai.get("reason"), 120)
    return {"ok": True, "by": by, "scope": only or "team", "ts": now, "reviews": reviews,
            "summary": summary, "tally": tally,
            "suggestions": _suggest(reviews, titles, last_by)}


def checkin(by="operator", only=None, floor=None):
    """Orion walks the floor and reviews the team. Read-only, zero Claude, recorded so the
    3D office can play the round. `only` = one agent's review (the auto check-in after a job)."""
    global _CSEQ
    if by not in ("operator", "auto") or (only is not None and only not in DEPT_OF):
        return {"error": "invalid check-in"}
    rec = _build_checkin(by, only, floor or state())
    with _LOCK:
        _CSEQ += 1
        rec["id"] = f"c{_CSEQ}_{rec['ts']}"
        _CHECKINS.insert(0, rec)
        del _CHECKINS[MAX_CHECKINS:]
    return dict(rec)


def latest_checkin():
    with _LOCK:
        return dict(_CHECKINS[0]) if _CHECKINS else None


def checkins(limit=10):
    with _LOCK:
        return {"ok": True, "checkins": [dict(c) for c in _CHECKINS[:max(1, min(int(limit), MAX_CHECKINS))]]}


# ── chat that survives an AI outage ───────────────────────────────────────────
def status_reply(agent_id):
    """What an agent can truthfully say from the live floor alone — no reasoning, no invention."""
    floor = state()
    if agent_id == "orion":
        rec = _build_checkin("auto", None, floor)
        lines = [rec["summary"]] + [f"• {r['name']}: {r['text']}" for r in rec["reviews"]]
        return "\n".join(lines)
    rows = {a["id"]: a for d in floor["departments"] for a in d["agents"]}
    a = rows.get(agent_id)
    if not a:
        return "I'm not on the active floor right now."
    r = _review_agent(a, floor["now"], _open_task_titles())
    return f"{a['name']} — {r['verdict'].replace('_', ' ')}: {r['text']}."


def chat(agent_id, message, chat_fn):
    """The agent's real brain when it answers; otherwise a clearly-labelled status reply."""
    out = chat_fn(agent_id, message)
    ok = isinstance(out, dict) and out.get("reply") and not out.get("error") and not out.get("needsKey")
    if ok:
        return out
    err = ""
    if isinstance(out, dict):
        err = str(out.get("error") or out.get("reply") or "")
    if agent_id not in DEPT_OF:
        return out if isinstance(out, dict) else {"error": "unknown agent"}
    note = ("My AI brain is unreachable right now" + (f" ({_short(err, 110)})" if err else "") +
            ", so I can't reason about your message. Here is what I can see live on the floor:\n")
    return {"reply": note + status_reply(agent_id), "offline": True, "aiError": _short(err, 200)}



def _selfcheck():
    """Runnable check of the only non-trivial logic here: activity precedence and the
    job lifecycle. No network, no Claude — a fake chat_fn stands in for the brain, and
    the task/bus stores are redirected to a temp dir so a test run never writes into
    the operator's live marcus_state."""
    import tempfile
    from pathlib import Path as _P

    global AUTO_CHECKIN
    AUTO_CHECKIN = False   # state() would import the live connector; checks below are explicit

    assert set(DEPT_OF) == {a for d in DEPARTMENTS for a in d["agents"]} | {"orion"}
    # 7 after the 2026-07-25 consolidation (Nora/Nova/Hawk/Blaze/Otto retired).
    assert len(DEPT_OF) == 8, DEPT_OF
    # Every agent on the floor must be reachable through agents_hub.chat — that's the
    # one path _run uses, so an agent missing from the hub roster would silently fall
    # through to "no brain wired" (which is how Midas ended up canned-replying).
    assert not set(DEPT_OF) - set(_hub_agents()), set(DEPT_OF) - set(_hub_agents())

    now = 1_000_000
    # "zzz" is chat-only (no engine attr) -> idle, not unknown.
    assert _activity("zzz", {}, {}, now)["activity"] == "idle"
    # queued beats idle; reporting beats queued; a live job beats everything.
    assert _activity("zzz", {}, {"zzz": 2}, now)["activity"] == "queued"
    assert _activity("zzz", {"zzz": (now - 1000, "hi")}, {"zzz": 2}, now)["activity"] == "reporting"
    # outside the window a stale bus note must NOT read as reporting
    stale = _activity("zzz", {"zzz": (now - REPORTING_WINDOW_MS - 1, "old")}, {}, now)
    assert stale["activity"] == "idle", stale

    tmp = _P(tempfile.mkdtemp(prefix="agent_office_test_"))
    import agents_hub
    import agent_bus
    agents_hub.TASKS = tmp / "hub_tasks.json"
    agent_bus.STATE = tmp / "agent_bus.json"

    # full lifecycle through the real dispatch path
    out = dispatch("scout", "Test task", chat_fn=lambda a, m: {"reply": "line one\nline two"})
    assert out.get("ok"), out
    jid = out["jobId"]
    for _ in range(100):
        if job(jid)["job"]["status"] != "running":
            break
        time.sleep(0.05)
    j = job(jid)["job"]
    assert j["status"] == "done", j
    assert j["result"].startswith("line one"), j
    assert [s["phase"] for s in j["steps"]][-1] == "done", j["steps"]

    # a brain that fails must land in "error", never a half-finished "running"
    bad = dispatch("atlas", "Boom",
                   chat_fn=lambda a, m: {"needsKey": True, "reply": "no key"})
    assert bad.get("ok"), bad
    for _ in range(100):
        if job(bad["jobId"])["job"]["status"] != "running":
            break
        time.sleep(0.05)
    assert job(bad["jobId"])["job"]["status"] == "error"
    # ...and its hub task lands in "failed" with the reason, not stuck "open"
    t = next(t for t in agents_hub.tasks("atlas")["tasks"] if t["id"] == bad["taskId"])
    assert t["status"] == "failed" and t.get("error"), t

    # Planning validates model output and never starts a job; directing creates real receipts.
    from unittest.mock import patch
    before = len(_JOBS)
    floor = {"departments": [{"agents": [{"id": "scout"}]}]}
    good = {"summary": "Rank leads", "assignments": [{"agentId": "scout", "title": "Rank inbound replies"}]}
    with patch(__name__ + ".state", return_value=floor):
        assert plan("Check leads", lambda a, m: {"reply": json.dumps(good)})["ok"]
        for invalid in ("not json", "[]", json.dumps({"assignments": [{"agentId": []}]}),
                        json.dumps({"assignments": [{"agentId": "midas", "title": "Archived"}]})):
            assert plan("Check leads", lambda a, m: {"reply": invalid}).get("error")
        assert plan([], lambda a, m: {}).get("error")
    assert len(_JOBS) == before, "planning dispatched work"
    directed = dispatch("scout", "Rank replies", directed_by="orion", chat_fn=lambda a, m: {"reply": "Ranked"})
    for _ in range(100):
        if job(directed["jobId"])["job"]["status"] != "running":
            break
        time.sleep(.01)
    assert job(directed["jobId"])["job"]["status"] == "done"
    receipts = agent_bus.recent()["messages"]
    assert any(m["from"] == "orion" and m["to"] == "scout" and m["data"].get("approvedBy") == "operator" for m in receipts)
    assert any(m["from"] == "scout" and m["to"] == "orion" for m in receipts)
    assert dispatch("scout", "x", directed_by="untrusted").get("error")

    # Orion's check-in: verdict precedence, stall flag, AI-outage wording, suggestions
    zed = {"id": "zzz", "name": "Zed", "activity": "idle"}
    assert _review_agent(zed, now, {})["verdict"] == "idle"
    assert _review_agent(zed, now, {"zzz": ["t1", "t2"]})["verdict"] == "waiting"
    run = {"id": "j", "title": "T", "startedAt": now - 1000,
           "steps": [{"phase": "think", "text": "working the task"}]}
    assert _review_agent(zed, now, {}, live=run, last={})["verdict"] == "working"
    run["startedAt"] = now - STALL_MS - 1
    assert _review_agent(zed, now, {}, live=run, last={})["verdict"] == "attention"
    failed = {"id": "k", "title": "T", "status": "error", "error": "Your credit balance is too low"}
    assert _review_agent(zed, now, {}, live=False, last=failed)["verdict"] == "blocked"
    failed["error"] = "boom"
    assert _review_agent(zed, now, {}, live=False, last=failed)["verdict"] == "attention"
    done = {"id": "d", "title": "T", "status": "done", "result": "line one\nline two"}
    assert _review_agent(zed, now, {}, live=False, last=done)["verdict"] == "on_track"
    done["result"] = " "
    assert _review_agent(zed, now, {}, live=False, last=done)["verdict"] == "attention"
    sick = dict(zed, activity="error", detail="HTTP 500 from CRM")
    assert _review_agent(sick, now, {}, live=False, last={})["verdict"] == "attention"
    floor = {"now": now, "ai": {"ok": False, "reason": "credits out"},
             "departments": [{"agents": [{"id": "scout", "name": "Scout", "activity": "idle"},
                                         {"id": "atlas", "name": "Atlas", "activity": "idle"}]}]}
    with patch(__name__ + ".state", return_value=floor):
        rec = checkin("operator")
        assert rec["id"] and len(rec["reviews"]) == 2 and "AI is down" in rec["summary"], rec
        assert latest_checkin()["id"] == rec["id"] and checkins(5)["checkins"][0]["id"] == rec["id"]
        assert [r["agentId"] for r in checkin("auto", only="atlas")["reviews"]] == ["atlas"]
        assert checkin("stranger").get("error") and checkin("auto", only="nobody").get("error")
        # chat: a real reply passes through; an outage answers from the floor, labelled offline
        assert chat("scout", "hi", lambda a, m: {"reply": "real"}) == {"reply": "real"}
        off = chat("scout", "hi", lambda a, m: {"error": "credit balance is too low"})
        assert off["offline"] and "Scout" in off["reply"] and "unreachable" in off["reply"], off
        assert "Checked 2 agents" in chat("orion", "hi", lambda a, m: {"needsKey": True, "reply": "no key"})["reply"]
        assert chat("nobody", "hi", lambda a, m: {"error": "x"}).get("error") == "x"

    assert dispatch("nobody", "x").get("error") == "unknown agent"
    assert dispatch("scout", "").get("error")
    print("agent_office selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
