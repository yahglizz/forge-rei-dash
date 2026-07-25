"""pixel_office.py — the visual floor: every FORGE agent as a live character at a desk.

Inspired by pixel-agents (github.com/pixel-agents-hq/pixel-agents), which draws Claude
Code sessions as pixel characters in an office. That project is a Vite/React-19 +
Fastify + VS Code extension wired to Claude Code's hook stream — none of which this
dashboard has (buildless React 18 UMD + a stdlib connector). So this is the same IDEA
rebuilt on what's already here: the departments are the four workspaces, the characters
are the twelve real agents, and the animation is driven by REAL agent activity, not a
demo loop.

Two jobs, and nothing more:

  state()   What is every agent doing RIGHT NOW — derived only from real signals:
            a live job in this module, an open task in agents_hub, recent agent_bus
            traffic, and the engine's own status(). Never invented; an agent we can't
            reach reads "unknown", not "idle".

  dispatch() The operator gives an agent a task from the floor. This does two things:
            files it as a normal agents_hub task (so it shows up everywhere tasks
            already show up) AND actually runs that agent's real brain in a background
            thread, appending a step log the floor animates against. So "you can see
            them doing it" and "they actually do it" are the same code path.

Autonomy (CLAUDE.md rule 2) is unchanged. A dispatched task runs the agent's THINKING —
the same chat/analyze brain the Agents tab already calls, creed-loaded and grounded.
It never sends an SMS, launches an ad, moves a pipeline, or writes a system of record.
The output is a proposal the operator still taps to execute.

State lives in memory only (marcus_state/ holds the durable half via agents_hub +
agent_bus). A restart clears the job log; the tasks and bus notes survive.
"""
import threading
import time

# Departments = the dashboard's four workspaces. Each agent id here must match the id
# agents_hub/dropship uses, because that's what we route a dispatched task to.
DEPARTMENTS = [
    {"id": "rei", "label": "Wholesale · REI", "accent": "#4F7CFF",
     "agents": ["marcus", "scout", "atlas"]},
    {"id": "agency", "label": "Agency · ClientForge", "accent": "#8B5CF6",
     "agents": ["dyson", "eco"]},
    {"id": "daycare", "label": "Daycare · A Touch of Blessings", "accent": "#2DD4BF",
     "agents": ["solomon", "nora", "nova"]},
    {"id": "dropship", "label": "Dropship · FORGE Store", "accent": "#F97316",
     "agents": ["midas", "hawk", "blaze", "otto"]},
]

# The four dropship agents live in dropship_director/dropship_agents, not agents_hub's
# roster, so their cards are defined here. The other eight are read from agents_hub so
# there is exactly one source of truth for a name/role/blurb.
DROPSHIP_AGENTS = {
    "midas": {"id": "midas", "name": "Midas", "business": "dropship", "emoji": "👑",
              "role": "E-com Director — head of the store",
              "blurb": "Reads the whole store, ranks what matters, delegates to the crew."},
    "hawk": {"id": "hawk", "name": "Hawk", "business": "dropship", "emoji": "🦅",
             "role": "Product Research — hunts winners",
             "blurb": "Scores product ideas on margin + real demand signal. Proposes only."},
    "blaze": {"id": "blaze", "name": "Blaze", "business": "dropship", "emoji": "🔥",
              "role": "Creative & Ads — Meta performance",
              "blurb": "Reads campaign performance, drafts ad concepts. Never spends."},
    "otto": {"id": "otto", "name": "Otto", "business": "dropship", "emoji": "📦",
             "role": "Fulfillment & Support",
             "blurb": "Order/inventory/tracking health, drafts customer replies."},
}

DEPT_OF = {a: d["id"] for d in DEPARTMENTS for a in d["agents"]}

# How long after a bus message an agent still reads as "reporting" on the floor.
REPORTING_WINDOW_MS = 90_000
MAX_JOBS = 60

_LOCK = threading.Lock()
_JOBS = []          # newest first, capped at MAX_JOBS
_SEQ = 0


# ── roster ────────────────────────────────────────────────────────────────────
def _hub_agents():
    """The eight agents_hub agents keyed by id. {} if the hub can't be imported."""
    try:
        import agents_hub
        return {a["id"]: a for a in agents_hub.AGENTS}
    except Exception:
        return {}


def _card(agent_id):
    """Name/role/blurb for one agent — hub first, dropship table second."""
    return _hub_agents().get(agent_id) or DROPSHIP_AGENTS.get(agent_id) or {
        "id": agent_id, "name": agent_id.title(), "business": DEPT_OF.get(agent_id, ""),
        "emoji": "🤖", "role": "", "blurb": ""}


# agent id -> the attribute the connector holds that engine under. Agents with no
# background engine (Marcus's screener, Dyson, Eco) are simply absent.
_ENGINE_ATTR = {
    "scout": "SCOUT", "marcus": "MARCUS", "atlas": "DEAL_PREP",
    "solomon": "SOLOMON", "nora": "NORA", "nova": "NOVA",
    "midas": "MIDAS", "hawk": "HAWK", "blaze": "BLAZE", "otto": "OTTO",
}


def _engine(agent_id):
    """The live engine instance for an agent, or None. Read-only, same lookup shape as
    agents_hub._engine — extended with the four dropship engines. The id is checked
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
    """The whole floor. `business` scopes to one department; None returns all four."""
    now_ms = int(time.time() * 1000)
    bus_idx = _bus_index()
    task_counts = _open_tasks()
    depts = [d for d in DEPARTMENTS if not business or d["id"] == business]

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

    with _LOCK:
        running = sum(1 for j in _JOBS if j["status"] == "running")
    return {"ok": True, "now": now_ms, "departments": out, "running": running,
            "business": business}


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


def _run_dropship(agent_id, title):
    """Run one of the four dropship agents for real. Hawk/Blaze/Otto take a free-form
    task through analyze(); Midas's real run is his operating brief."""
    eng = _engine(agent_id)
    if eng is None:
        return "", f"{agent_id} has no live engine on this host"
    try:
        if agent_id == "midas":
            brief = eng.build_brief()
            if isinstance(brief, dict) and brief.get("error"):
                return "", str(brief["error"])[:300]
            headline = ""
            if isinstance(brief, dict):
                headline = brief.get("headline") or brief.get("summary") or ""
            return (headline or "Operating brief rebuilt — see the Midas console."), ""
        out = eng.analyze(title)
        if isinstance(out, dict) and not out.get("ok"):
            return "", str(out.get("error") or "analysis failed")[:300]
        res = (out or {}).get("result") if isinstance(out, dict) else out
        if isinstance(res, dict):
            return (res.get("headline") or res.get("raw")
                    or "Analysis complete — see the agent console."), ""
        return str(res or "Analysis complete."), ""
    except Exception as e:  # noqa: BLE001
        return "", str(e)[:300]


def _run(job, chat_fn):
    """The worker. Every step is announced BEFORE the work so the floor animates the
    thing that is actually happening, not a canned sequence."""
    jid, aid, title = job["id"], job["agentId"], job["title"]
    note = job.get("note") or ""
    try:
        _step(jid, "walk", "heading to the desk")
        _step(jid, "read", "loading creed, playbook and live data")

        prompt = title if not note else f"{title}\n\nContext from the operator: {note}"
        if DEPT_OF.get(aid) == "dropship":
            _step(jid, "think", "working the task")
            reply, err = _run_dropship(aid, prompt)
        elif chat_fn is None:
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
            else:
                reply = str(out or "")

        if err or not reply:
            _step(jid, "error", err or "no answer came back")
            _finish(jid, "error", error=err or "no answer came back")
            return

        _step(jid, "report", "writing up the answer")
        head = reply.strip().split("\n")[0][:180]
        try:
            import agent_bus
            agent_bus.send(aid, "operator", "note", f"Task done — {head}",
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
        _finish(jid, "error", error=str(e)[:300])


def dispatch(agent_id, title, note="", chat_fn=None):
    """Give an agent a task from the floor: file it, then actually run it.

    chat_fn(agent_id, message) -> the agents_hub chat bound to this GHL sub-account.
    The connector supplies it (same pattern as agents_hub.coach_ask) so this module
    stays connector-free and importable on its own.
    """
    global _SEQ
    agent_id = (agent_id or "").strip()
    title = (title or "").strip()
    if agent_id not in DEPT_OF:
        return {"error": "unknown agent"}
    if not title:
        return {"error": "a task needs a title"}
    if _live_job(agent_id):
        return {"error": f"{_card(agent_id)['name']} is already on a task"}

    task_id = ""
    try:
        import agents_hub
        # Only the eight hub agents have a task store; dropship tasks live in the job log.
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
               "title": title, "note": (note or "").strip(), "taskId": task_id,
               "status": "running", "startedAt": now, "steps": [],
               "result": "", "error": ""}
        _JOBS.insert(0, job)
        del _JOBS[MAX_JOBS:]

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


def _selfcheck():
    """Runnable check of the only non-trivial logic here: activity precedence and the
    job lifecycle. No network, no Claude — a fake chat_fn stands in for the brain, and
    the task/bus stores are redirected to a temp dir so a test run never writes into
    the operator's live marcus_state."""
    import tempfile
    from pathlib import Path as _P

    assert set(DEPT_OF) == {a for d in DEPARTMENTS for a in d["agents"]}
    assert len(DEPT_OF) == 12, DEPT_OF

    now = 1_000_000
    # "zzz" is chat-only (no engine attr) -> idle, not unknown.
    assert _activity("zzz", {}, {}, now)["activity"] == "idle"
    # queued beats idle; reporting beats queued; a live job beats everything.
    assert _activity("zzz", {}, {"zzz": 2}, now)["activity"] == "queued"
    assert _activity("zzz", {"zzz": (now - 1000, "hi")}, {"zzz": 2}, now)["activity"] == "reporting"
    # outside the window a stale bus note must NOT read as reporting
    stale = _activity("zzz", {"zzz": (now - REPORTING_WINDOW_MS - 1, "old")}, {}, now)
    assert stale["activity"] == "idle", stale

    tmp = _P(tempfile.mkdtemp(prefix="pixel_office_test_"))
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

    assert dispatch("nobody", "x").get("error") == "unknown agent"
    assert dispatch("scout", "").get("error")
    print("pixel_office selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
