// agent_center.jsx — the Agent Control Center (spec §9). Every agent in every business
// on one page: status, last run / success / next run, tasks, errors, current task,
// dependency health — and Chat + Give task on each card.
//
// Data: GET /api/agents/registry (agents_hub.registry — one roster, real signals only;
// a null field means unknown, shown as "—"). Chat reuses the hub's chat component
// (window.HubChat → POST /api/hub/chat); tasks POST /api/hub/task. Nothing here takes
// an outward action, and ACE / Autopilot modes are shown read-only, never toggled.
//
// Collision rules (CLAUDE.md §7): hook aliases *Acc, every top-level name Acc/acc-
// prefixed, no computed JSX tags (HubChat is resolved to a const before render).
const { useState: useStateAcc, useEffect: useEffectAcc } = React;

const ACC_STATUS_COLOR = {
  "RUNNING": "#4F7CFF",
  "IDLE": "#22C55E",
  "WAITING FOR APPROVAL": "#F59E0B",
  "DEGRADED": "#F97316",
  "FAILED": "#EF4444",
  "DISABLED": "#6B7280",
};

const ACC_BIZ_COLOR = {
  wholesale: "#4F7CFF", agency: "#8B5CF6", daycare: "#2DD4BF",
  dropship: "#F59E0B", cross: "#EC4899", system: "#94A3B8",
};

const ACC_BTN = {
  padding: "7px 13px", borderRadius: 9, fontSize: 12.5, fontWeight: 600, cursor: "pointer",
  border: "1px solid var(--border-strong)", background: "rgba(255,255,255,.04)",
  color: "var(--text)", fontFamily: "inherit",
};

const ACC_INPUT = {
  flex: 1, minWidth: 0, padding: "9px 11px", borderRadius: 9, fontSize: 13,
  border: "1px solid var(--border-strong)", background: "rgba(255,255,255,.03)",
  color: "var(--text)", fontFamily: "inherit",
};

// "3m ago" / "in 12m" / "—". ms timestamps; null/0 = unknown.
function accAgo(ms) {
  if (!ms) return "—";
  const d = ms - Date.now();
  const s = Math.abs(d) / 1000;
  const u = s < 60 ? Math.round(s) + "s" : s < 3600 ? Math.round(s / 60) + "m"
    : s < 86400 ? Math.round(s / 3600) + "h" : Math.round(s / 86400) + "d";
  return d > 0 ? "in " + u : u + " ago";
}

function accStamp(ms) {
  return ms ? new Date(ms).toLocaleString() : "unknown";
}

function AccStatusPill({ status }) {
  const c = ACC_STATUS_COLOR[status] || "#6B7280";
  return <span className="pill" style={{ background: c + "22", color: c, whiteSpace: "nowrap" }}>
    <span style={{ width: 6, height: 6, borderRadius: 6, background: c }} />
    {status || "UNKNOWN"}
  </span>;
}

function AccField({ label, value, title, wide }) {
  return <div style={{ minWidth: 0, gridColumn: wide ? "1 / -1" : undefined }} title={title || ""}>
    <div className="faint" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".06em" }}>{label}</div>
    <div style={{
      fontSize: 12.5, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis",
      whiteSpace: wide ? "normal" : "nowrap", wordBreak: "break-word",
    }}>{value === null || value === undefined || value === "" ? "—" : value}</div>
  </div>;
}

function accDeps(dep) {
  if (!dep) return "—";
  const parts = [];
  if (dep.ai && dep.ai !== "n/a") parts.push("AI " + dep.ai);
  if (dep.keys === true) parts.push("key ✓");
  if (dep.keys === false) parts.push("no key");
  if (dep.heartbeat && dep.heartbeat !== "none") parts.push("loop " + dep.heartbeat);
  return parts.join(" · ") || "no external deps";
}

function AccCard({ a, byId, onOpen }) {
  const biz = ACC_BIZ_COLOR[a.business] || "#94A3B8";
  const via = a.chatTarget && a.chatTarget !== a.id ? byId[a.chatTarget] : null;
  const dep = a.dependencyHealth || {};
  const err = a.lastError || dep.aiReason;
  return <div className="card card-pad" style={{
    display: "flex", flexDirection: "column", gap: 10, minWidth: 0,
    borderLeft: "3px solid " + (ACC_STATUS_COLOR[a.status] || biz),
    opacity: a.archived ? 0.6 : 1,
  }}>
    <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
      <span style={{ fontSize: 24, lineHeight: 1 }}>{a.emoji}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
          <b style={{ fontSize: 15 }}>{a.name}</b>
          <span className="pill" style={{ background: biz + "22", color: biz }}>
            {a.businessLabel}{a.archived ? " · archived" : ""}
          </span>
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{a.role}</div>
      </div>
      <AccStatusPill status={a.status} />
    </div>

    <div className="faint" style={{ fontSize: 12, lineHeight: 1.45 }}>{a.purpose}</div>

    {err && <div style={{
      fontSize: 12, lineHeight: 1.45, color: "#FCA5A5", background: "rgba(239,68,68,.08)",
      border: "1px solid rgba(239,68,68,.25)", borderRadius: 9, padding: "7px 9px",
      wordBreak: "break-word",
    }}>⚠ {err}</div>}
    {a.detail && <div style={{
      fontSize: 12, lineHeight: 1.45, color: "#FCD34D", background: "rgba(245,158,11,.08)",
      borderRadius: 9, padding: "7px 9px",
    }}>{a.detail}</div>}

    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "9px 12px" }}>
      <AccField label="Last run" value={accAgo(a.lastRun)} title={accStamp(a.lastRun)} />
      <AccField label="Last success" value={accAgo(a.lastSuccessAt)} title={accStamp(a.lastSuccessAt)} />
      <AccField label="Next run" value={accAgo(a.nextRun)} title={accStamp(a.nextRun)} />
      <AccField label="Tasks done" value={a.tasksCompleted} />
      <AccField label="Tasks failed" value={a.tasksFailed} />
      <AccField label="Errors" value={a.errorCount} title="Loop errors (cumulative when tracked, else current streak). — = no loop." />
      <AccField label="Approvals" value={a.approvalQueue ? a.pendingApprovals + " waiting" : "n/a"} />
      <AccField label="Open tasks" value={a.openTasks} />
      <AccField label="Output" value={a.work} wide />
      <AccField label="Current task" value={a.currentTask || "none"} wide />
      <AccField label="Dependency health" value={accDeps(dep)} wide />
    </div>

    <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: "auto", flexWrap: "wrap" }}>
      <button style={ACC_BTN} onClick={() => onOpen(a.id, "chat")}>💬 Chat</button>
      <button style={ACC_BTN} onClick={() => onOpen(a.id, "task")}>📋 Give task</button>
      {via && <span className="faint" style={{ fontSize: 11 }}>answered by {via.name}</span>}
    </div>
  </div>;
}

// Task box + this agent's task history (failed ones show their error).
function AccTaskPanel({ agent, byId }) {
  const [title, setTitle] = useStateAcc("");
  const [busy, setBusy] = useStateAcc(false);
  const [note, setNote] = useStateAcc(null);
  const [rows, setRows] = useStateAcc([]);

  function load() {
    window.apiGet("/api/hub/tasks?agent=" + encodeURIComponent(agent.id))
      .then((d) => setRows(Array.isArray(d && d.tasks) ? d.tasks : []))
      .catch((e) => setNote({ err: true, text: String(e.message || e) }));
  }
  useEffectAcc(() => { setRows([]); setNote(null); load(); }, [agent.id]);

  function assign() {
    const t = title.trim();
    if (!t || busy) return;
    setBusy(true); setNote(null);
    window.apiPost("/api/hub/task", { agentId: agent.id, title: t })
      .then(() => { setTitle(""); setNote({ err: false, text: "Filed. " + agent.name + " sees it on the next run." }); load(); })
      .catch((e) => setNote({ err: true, text: String(e.message || e) }))
      .then(() => setBusy(false));
  }

  const via = agent.chatTarget && agent.chatTarget !== agent.id ? byId[agent.chatTarget] : null;
  const tone = { open: "#4F7CFF", done: "#22C55E", failed: "#EF4444", dismissed: "#6B7280" };
  return <div style={{ display: "flex", flexDirection: "column", gap: 10, minHeight: 0, height: "100%" }}>
    <div style={{ display: "flex", gap: 8 }}>
      <input style={ACC_INPUT} value={title} placeholder={"Give " + agent.name + " a task…"}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") assign(); }} />
      <button style={ACC_BTN} onClick={assign} disabled={busy || !title.trim()}>{busy ? "…" : "Assign"}</button>
    </div>
    <div className="faint" style={{ fontSize: 11.5, lineHeight: 1.45 }}>
      A task is an assignment, not an action — the agent comes back with a recommendation;
      anything outward still needs your approval.
      {via ? " " + agent.name + " has no brain of its own: " + via.name + " picks this up." : ""}
    </div>
    {note && <div style={{ fontSize: 12, color: note.err ? "#EF4444" : "#22C55E", wordBreak: "break-word" }}>{note.text}</div>}
    <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
      {!rows.length && <div className="faint" style={{ fontSize: 12.5, padding: 8 }}>No tasks yet.</div>}
      {rows.map((t) => <div key={t.id} style={{ padding: "8px 2px", borderBottom: "1px solid var(--border)" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="pill" style={{ background: (tone[t.status] || "#6B7280") + "22", color: tone[t.status] || "#6B7280" }}>{t.status}</span>
          <span style={{ fontSize: 12.5, flex: 1, minWidth: 0, wordBreak: "break-word" }}>{t.title}</span>
          <span className="faint" style={{ fontSize: 11 }}>{accAgo(t.updatedAt || t.createdAt)}</span>
        </div>
        {t.error && <div style={{ fontSize: 11.5, color: "#FCA5A5", marginTop: 4, wordBreak: "break-word" }}>⚠ {t.error}</div>}
      </div>)}
    </div>
  </div>;
}

function AccDrawer({ agent, agents, byId, mode, setMode, onClose }) {
  const AccHubChat = window.HubChat || null;   // resolved before render — never computed
  const via = agent.chatTarget && agent.chatTarget !== agent.id ? byId[agent.chatTarget] : null;
  useEffectAcc(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const tabStyle = (on) => ({ ...ACC_BTN, padding: "5px 11px", background: on ? "rgba(79,124,255,.18)" : "transparent" });
  return <div onClick={onClose} style={{
    position: "fixed", inset: 0, background: "rgba(0,0,0,.45)", zIndex: 60,
    display: "flex", justifyContent: "flex-end",
  }}>
    <div onClick={(e) => e.stopPropagation()} className="card" style={{
      width: "min(540px, 100vw)", height: "100%", borderRadius: 0, padding: 16,
      display: "flex", flexDirection: "column", gap: 12, background: "var(--card)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 24 }}>{agent.emoji}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <b style={{ fontSize: 15 }}>{agent.name}</b>
          <div className="faint" style={{ fontSize: 11.5 }}>
            {agent.businessLabel}{via ? " · replies come from " + via.name + ", with " + agent.name + "'s live state" : ""}
          </div>
        </div>
        <AccStatusPill status={agent.status} />
        <button style={{ ...ACC_BTN, padding: "5px 10px" }} onClick={onClose} aria-label="Close">✕</button>
      </div>
      <div style={{ display: "flex", gap: 6 }}>
        <button style={tabStyle(mode === "chat")} onClick={() => setMode("chat")}>Chat</button>
        <button style={tabStyle(mode === "task")} onClick={() => setMode("task")}>Tasks</button>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        {mode === "chat"
          ? (AccHubChat ? <AccHubChat agent={agent} agents={agents} />
            : <div className="faint" style={{ fontSize: 13 }}>Chat component didn't load (agents_hub.jsx).</div>)
          : <AccTaskPanel agent={agent} byId={byId} />}
      </div>
    </div>
  </div>;
}

function AgentControlCenter() {
  const reg = window.useApi("/api/agents/registry", { interval: 20000 });
  const [biz, setBiz] = useStateAcc("all");
  const [open, setOpen] = useStateAcc(null);   // { id, mode }

  const data = reg.data || {};
  const agents = Array.isArray(data.agents) ? data.agents : [];
  const byId = {};
  agents.forEach((a) => { byId[a.id] = a; });

  if (reg.loading && !agents.length) {
    return <div className="card card-pad faint">Loading agents…</div>;
  }
  if (reg.error && !agents.length) {
    return <div className="card card-pad" style={{ color: "#EF4444" }}>
      Couldn't load the agent registry: {String(reg.error.message || reg.error)}
    </div>;
  }

  const seen = [];
  agents.forEach((a) => { if (!seen.find((b) => b.id === a.business)) seen.push({ id: a.business, label: a.businessLabel }); });
  const shown = biz === "all" ? agents : agents.filter((a) => a.business === biz);
  const counts = {};
  shown.forEach((a) => { counts[a.status] = (counts[a.status] || 0) + 1; });
  const ai = data.ai || {};
  const cur = open && byId[open.id];

  return <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
    <div style={{ display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.3px" }}>Agent Control Center</div>
        <div className="muted" style={{ fontSize: 13 }}>
          Every agent, every business — live status from heartbeats, task store, approval queues and AI health.
        </div>
      </div>
      <div className="faint" style={{ fontSize: 11.5 }}>
        {reg.error ? <span style={{ color: "#EF4444" }}>refresh failed: {String(reg.error)} · </span> : null}
        updated {accAgo(data.generatedAt)}
      </div>
      <button style={ACC_BTN} onClick={() => reg.refresh && reg.refresh()}>↻ Refresh</button>
    </div>

    {ai.ok === false && <div className="card card-pad" style={{
      borderLeft: "3px solid #EF4444", color: "#FCA5A5", fontSize: 13, lineHeight: 1.5,
    }}>
      <b>AI is down</b> — every agent that calls Claude is degraded.
      {ai.reason ? " " + ai.reason + "." : ""}
      {ai.lastError ? <div className="faint" style={{ fontSize: 12, marginTop: 4, wordBreak: "break-word" }}>{ai.lastError}</div> : null}
    </div>}

    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
      <button className={"tab" + (biz === "all" ? " active" : "")} style={{ border: "none", cursor: "pointer", fontFamily: "inherit", background: biz === "all" ? undefined : "transparent" }}
        onClick={() => setBiz("all")}>All · {agents.length}</button>
      {seen.map((b) => <button key={b.id} className={"tab" + (biz === b.id ? " active" : "")}
        style={{ border: "none", cursor: "pointer", fontFamily: "inherit", background: biz === b.id ? undefined : "transparent" }}
        onClick={() => setBiz(b.id)}>{b.label}</button>)}
      <span style={{ flex: 1 }} />
      {Object.keys(ACC_STATUS_COLOR).filter((s) => counts[s]).map((s) =>
        <span key={s} className="pill" style={{ background: ACC_STATUS_COLOR[s] + "1F", color: ACC_STATUS_COLOR[s] }}>
          {counts[s]} {s.toLowerCase()}
        </span>)}
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 330px), 1fr))", gap: 14 }}>
      {shown.map((a) => <AccCard key={a.id} a={a} byId={byId} onOpen={(id, mode) => setOpen({ id, mode })} />)}
    </div>
    {!shown.length && <div className="card card-pad faint">No agents in this business.</div>}

    {cur && <AccDrawer agent={cur} agents={agents} byId={byId} mode={open.mode}
      setMode={(m) => setOpen({ id: open.id, mode: m })} onClose={() => setOpen(null)} />}
  </div>;
}

Object.assign(window, { AgentControlCenter, AccStatusPill, AccCard, AccDrawer, AccTaskPanel, accAgo });
