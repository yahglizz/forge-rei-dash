// agent_office.jsx — the Agent Office page: the 3D floor, the roster, Orion's check-ins
// and a chat + task panel for every agent. (The old 2D canvas view was removed 2026-09-30.)
//
// All motion on the floor comes from office_scene.js reading /api/office/state: real job
// steps, real agent-bus assignments, real check-ins. Nothing here invents activity.
//
// Collision discipline (CLAUDE.md §7): unique hook aliases, every top-level name prefixed
// AO / AgentOffice, no computed JSX tags.
const { useState: useStateAO, useEffect: useEffectAO, useRef: useRefAO } = React;

// activity -> how the operator reads it. One table so the roster, the legend and the
// task panel never disagree with the 3D floor's colours.
const AO_ACTIVITY = {
  walk:      { label: "Heading to desk", color: "#9FB0C7" },
  read:      { label: "Reading brief",   color: "#2DD4BF" },
  think:     { label: "Working",         color: "#4F7CFF" },
  report:    { label: "Writing up",      color: "#8B5CF6" },
  done:      { label: "Done",            color: "#22C55E" },
  reporting: { label: "Just reported",   color: "#22C55E" },
  queued:    { label: "Task waiting",    color: "#F59E0B" },
  idle:      { label: "Idle",            color: "#64748B" },
  error:     { label: "Needs you",       color: "#EF4444" },
  unknown:   { label: "Not reachable",   color: "#475569" },
};
// Orion's check-in verdicts (agent_office._review_agent).
const AO_VERDICT = {
  working:   { label: "Working",         color: "#60A5FA" },
  on_track:  { label: "On track",        color: "#22C55E" },
  waiting:   { label: "Waiting",         color: "#F59E0B" },
  idle:      { label: "Idle",            color: "#64748B" },
  attention: { label: "Needs attention", color: "#EF4444" },
  blocked:   { label: "Blocked",         color: "#F97316" },
};

function aoMeta(a) { return AO_ACTIVITY[a] || AO_ACTIVITY.unknown; }
function aoBusy(a) { return ["walk", "read", "think", "report"].indexOf(a) >= 0; }
function aoAgo(ts, now) {
  const s = Math.max(0, Math.round(((now || Date.now()) - ts) / 1000));
  return s < 60 ? s + "s ago" : s < 3600 ? Math.round(s / 60) + " min ago" : Math.round(s / 3600) + " h ago";
}

// ── the agent panel: status, live step log, and the task box ─────────────────
function AgentOfficeTaskPanel({ agent, job, onDispatch, sending, err }) {
  const [title, setTitle] = useStateAO("");
  const Icons = window.Icons;
  if (!agent) {
    return (
      <div className="card" style={{ padding: 18, height: "100%" }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Pick an agent</div>
        <div className="faint" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
          Select an agent on the floor or in the list. You'll get their status, a live log of what
          they're doing, and a box to hand them a task — the same brain the Agents tab
          uses, so the work is real. Outward actions stay approval-gated.
        </div>
      </div>
    );
  }
  const meta = aoMeta(agent.activity);
  const steps = (job && job.steps) || [];
  const running = job && job.status === "running";

  return (
    <div className="card office-panel" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, height: "100%", minHeight: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <div style={{ width: 40, height: 40, borderRadius: 11, background: "var(--card-2)", display: "grid", placeItems: "center", fontSize: 20 }}>{agent.emoji}</div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{agent.name}</div>
          <div className="faint" style={{ fontSize: 11.5 }}>{agent.role}</div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12 }}>
        <span style={{ width: 8, height: 8, borderRadius: 9, background: meta.color }} />
        <span style={{ color: meta.color, fontWeight: 600 }}>{meta.label}</span>
        {agent.openTasks > 0 && <span className="faint">· {agent.openTasks} open</span>}
      </div>
      {agent.detail && (
        <div className="faint" style={{ fontSize: 11.5, lineHeight: 1.5, maxHeight: 54, overflow: "hidden" }}>{agent.detail}</div>
      )}

      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 11 }}>
        <div className="faint" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 7 }}>
          {running ? "Working now" : "Last run"}
        </div>
        {steps.length === 0 && <div className="faint" style={{ fontSize: 12 }}>No run yet this session.</div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {steps.map((s, i) => (
            <div key={i} style={{ display: "flex", gap: 8, fontSize: 11.5, alignItems: "flex-start" }}>
              <span style={{ width: 7, height: 7, borderRadius: 9, marginTop: 4, flexShrink: 0, background: aoMeta(s.phase).color }} />
              <span style={{ color: s.phase === "error" ? "var(--red)" : "var(--text-2)", lineHeight: 1.45 }}>{s.text}</span>
            </div>
          ))}
        </div>
      </div>

      {job && job.status === "done" && job.result && (
        <div style={{ background: "var(--card-2)", borderRadius: 10, padding: 11, fontSize: 12, lineHeight: 1.55, whiteSpace: "pre-wrap", overflowY: "auto", maxHeight: 240, flex: "1 1 auto", minHeight: 0 }}>
          {job.result}
        </div>
      )}
      {job && job.status === "error" && (
        <div style={{ color: "var(--red)", fontSize: 12 }}>{job.error}</div>
      )}

      <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 7 }}>
        {err && <div style={{ color: "var(--red)", fontSize: 11.5 }}>{err}</div>}
        <textarea value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder={"Give " + agent.name + " a task…"} rows={2}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && title.trim()) {
              onDispatch(title.trim()); setTitle("");
            }
          }}
          style={{ width: "100%", background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 10, padding: "9px 11px", color: "var(--text)", fontSize: 12.5, fontFamily: "var(--font)", resize: "vertical" }} />
        <button className="btn"
          disabled={sending || running || !title.trim()}
          onClick={() => { onDispatch(title.trim()); setTitle(""); }}
          style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, padding: "9px 12px", borderRadius: 10, fontSize: 12.5, fontWeight: 600, background: running ? "var(--card-2)" : "var(--workspace-accent)", color: running ? "var(--text-3)" : "#fff", opacity: (sending || running || !title.trim()) ? 0.55 : 1 }}>
          <Icons.Send size={14} /> {running ? "Working…" : sending ? "Sending…" : "Send task"}
        </button>
        <div className="faint" style={{ fontSize: 10.5, lineHeight: 1.45 }}>
          Runs the agent's real brain and reports back. Never texts, spends, or posts —
          outward actions stay one-tap gated.
        </div>
      </div>
    </div>
  );
}

// ── Orion's latest check-in: who is on track, who needs you, what he would assign ──
function AgentOfficeCheckin({ checkin, now, onSelect, onAssign, assigning }) {
  if (!checkin) {
    return (
      <div className="orion-feed"><strong>Orion's check-ins</strong>
        <div className="faint">None yet. Press "Check in on team" and Orion walks the floor, reading each agent's live job, last result and errors. Needs no AI credits.</div>
      </div>
    );
  }
  const names = {};
  (checkin.reviews || []).forEach((r) => { names[r.agentId] = r.name; });
  return (
    <div className="orion-feed" aria-live="polite"><strong>Orion's check-in · {aoAgo(checkin.ts, now)}</strong>
      <div>{checkin.summary}</div>
      {(checkin.reviews || []).map((r) => {
        const v = AO_VERDICT[r.verdict] || AO_VERDICT.idle;
        return (
          <div key={r.agentId}>
            <button className="btn" onClick={() => onSelect(r.agentId)} style={{ display: "flex", gap: 8, alignItems: "flex-start", textAlign: "left", padding: "7px 9px" }}>
              <span style={{ width: 9, height: 9, borderRadius: 9, marginTop: 4, flexShrink: 0, background: v.color }} />
              <span style={{ minWidth: 0 }}><b>{r.name}</b> <span style={{ color: v.color, fontWeight: 700 }}>{v.label}</span><br /><span className="faint">{r.text}</span></span>
            </button>
          </div>
        );
      })}
      {(checkin.suggestions || []).length > 0 && (
        <div className="orion-plan"><strong>Orion suggests</strong>
          {checkin.suggestions.map((s) => (
            <div key={s.agentId}>
              <b>{names[s.agentId] || s.agentId}</b><p>{s.title}</p>{s.note && <small>{s.note}</small>}
              <div className="orion-controls"><button className="btn btn-primary" disabled={assigning === s.agentId} onClick={() => onAssign(s)}>{assigning === s.agentId ? "Assigning…" : "Approve & assign"}</button></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── the page ─────────────────────────────────────────────────────────────────
function AgentOfficePage() {
  const [state, setState] = useStateAO(null);
  const [err, setErr] = useStateAO(null);
  const [selected, setSelected] = useStateAO("orion");
  const [orionMode, setOrionMode] = useStateAO("idle");
  const [dogModes, setDogModes] = useStateAO({});
  const [job, setJob] = useStateAO(null);
  const [sending, setSending] = useStateAO(false);
  const [sendErr, setSendErr] = useStateAO(null);
  const [checking, setChecking] = useStateAO(false);
  const [assigning, setAssigning] = useStateAO("");
  const jobIdRef = useRefAO(null);

  // Floor state — 2.5s poll. Everything here is derived server-side from real signals.
  useEffectAO(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await window.apiGet("/api/office/state");
        if (alive) { setState(d); setErr(null); }
      } catch (e) { if (alive) setErr(e.message || String(e)); }
    };
    load();
    const timer = setInterval(load, 2500);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const agents = [];
  ((state && state.departments) || []).forEach((d) => (d.agents || []).forEach((a) => agents.push(a)));
  if (state && state.director) agents.unshift(state.director);
  const agent = agents.find((a) => a.id === selected) || null;
  async function refreshOffice() {
    try { setState(await window.apiGet("/api/office/state")); }
    catch (e) { setErr(e.message || String(e)); }
  }

  // Follow whichever job belongs to the selected agent — live while running, then the
  // finished result stays on screen.
  const followId = (agent && (agent.jobId || (agent.lastJob && agent.lastJob.id))) || null;
  useEffectAO(() => {
    jobIdRef.current = followId;
    if (!followId) { setJob(null); return; }
    let alive = true;
    const load = async () => {
      try {
        const d = await window.apiGet("/api/office/job?id=" + encodeURIComponent(followId));
        if (alive && d.job && jobIdRef.current === followId) setJob(d.job);
      } catch (_) { /* a job that aged out of the log is not an error */ }
    };
    load();
    const timer = setInterval(load, 1200);
    return () => { alive = false; clearInterval(timer); };
  }, [followId]);

  async function dispatch(title) {
    if (!agent || !title) return;
    setSending(true); setSendErr(null);
    try {
      const d = await window.apiPost("/api/office/task", { agentId: agent.id, title });
      if (d.error) throw new Error(d.error);
      if (d.jobId) {
        jobIdRef.current = d.jobId;
        setJob({ id: d.jobId, status: "running", steps: [] });
      }
      await refreshOffice();
    } catch (e) { setSendErr(e.message || String(e)); }
    setSending(false);
  }

  // Orion's round: read-only, no AI call, so it works whatever state the AI account is in.
  async function checkIn() {
    if (checking) return;
    setChecking(true); setErr(null);
    try {
      const d = await window.apiPost("/api/office/checkin", {});
      if (d.error) throw new Error(d.error);
      await refreshOffice();
    } catch (e) { setErr("Check-in: " + (e.message || String(e))); }
    setChecking(false);
  }

  // The owner's tap on "Approve & assign" is the approval (rule 2); Orion then walks over.
  async function assignSuggestion(s) {
    setAssigning(s.agentId); setErr(null);
    try {
      const d = await window.apiPost("/api/office/task", { agentId: s.agentId, title: s.title, note: s.note || "", directedBy: "orion" });
      if (d.error || !d.jobId) throw new Error(d.error || "No job was created");
      await refreshOffice();
    } catch (e) { setErr("Assign: " + (e.message || String(e))); }
    setAssigning("");
  }

  const busy = agents.filter((a) => aoBusy(a.activity)).length;
  const legend = ["think", "read", "report", "queued", "idle", "error"];
  const ai = (state && state.ai) || { ok: true };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="card office-head">
        <div>
          <div className="office-head-title" style={{ fontWeight: 700 }}>Agent Office <span className="office-live">Live</span></div>
          <div className="faint" style={{ fontSize: 11.5 }}>
            {((state && state.departments) || []).length} departments, live. {agents.length} agents · {busy} working right now.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <button className="btn btn-primary" disabled={checking || !state} onClick={checkIn} title="Orion reads every agent's live job, result and errors">{checking ? "Checking in…" : "Check in on team"}</button>
        <div className="office-legend">
          {legend.map((k) => (
            <span key={k} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11 }}>
              <span style={{ width: 8, height: 8, borderRadius: 9, background: aoMeta(k).color }} />
              <span className="faint">{aoMeta(k).label}</span>
            </span>
          ))}
        </div>
      </div>

      {err && <div className="card" style={{ padding: 14, color: "var(--red)", fontSize: 12.5 }}>Office feed: {err}</div>}
      {!ai.ok && <div className="card" role="alert" style={{ padding: 14, color: "#fdba74", fontSize: 12.5, lineHeight: 1.5 }}>
        AI is offline — {ai.reason || "the provider is unreachable"}. Agents can't reason or finish tasks until it is back; chats answer from the live floor and say so, and Orion's check-ins still work.
      </div>}

      <div className="office-grid">
        <div className="card office-floor-card">
          <OrionOfficeFloor state={state} selected={selected} onSelect={setSelected} mode={orionMode} dogModes={dogModes} />
          <div className="office-roster">
            {agents.map((a) => {
              const m = aoMeta(a.activity);
              return (
                <button key={a.id} onClick={() => setSelected(a.id)}
                  className="card"
                  style={{ padding: "9px 11px", display: "flex", alignItems: "center", gap: 9, textAlign: "left", borderRadius: 12, border: selected === a.id ? "1px solid var(--workspace-accent)" : "1px solid var(--border)" }}>
                  <span style={{ fontSize: 16 }}>{a.emoji}</span>
                  <span style={{ minWidth: 0, flex: 1 }}>
                    <span style={{ display: "block", fontSize: 12.5, fontWeight: 600 }}>{a.name}</span>
                    <span style={{ display: "block", fontSize: 10.5, color: m.color }}>{m.label}</span>
                  </span>
                  {a.openTasks > 0 && (
                    <span className="tabnum" style={{ fontSize: 10.5, color: "var(--orange)", fontWeight: 700 }}>{a.openTasks}</span>
                  )}
                </button>
              );
            })}
          </div>
          <AgentOfficeCheckin checkin={state && state.checkin} now={state && state.now} onSelect={setSelected} onAssign={assignSuggestion} assigning={assigning} />
          <div className="orion-feed" aria-live="polite"><strong>Office handoffs</strong>
            {((state && state.messages) || []).slice(0, 6).map(m => <div key={m.id}><small>{(agents.find(a => a.id === m.from) || {}).name || m.from} → {(agents.find(a => a.id === m.to) || {}).name || m.to}</small><span>{m.text}</span></div>)}
            {!(state && state.messages && state.messages.length) && <div className="faint">No recent handoffs.</div>}
          </div>
        </div>

        <div className="orion-panel-wrap">
          {selected === "orion" ? <OrionOfficePanel key="orion" state={state} onMode={setOrionMode} onRefresh={refreshOffice} onCheckin={checkIn} checking={checking} />
            : <React.Fragment>{agent && <OrionOfficePanel key={agent.id} agent={agent} state={state} onMode={mode => setDogModes(current => ({ ...current, [agent.id]: mode }))} onRefresh={refreshOffice} />}<AgentOfficeTaskPanel agent={agent} job={job} onDispatch={dispatch} sending={sending} err={sendErr} /></React.Fragment>}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { AgentOfficePage, AgentOfficeTaskPanel });
