// agency_agents.jsx — the Agents hub. Dyson + Eco live here as operable agents:
// open one, chat with it, send it tasks, or jump to its operate panel. Each is
// backed by Claude through the agency Anthropic key (see agency_agents.py).
// Static-React: hooks aliased (…Agt), top-level names prefixed Agt, shipped on window.
const { useState: useStateAgt, useEffect: useEffectAgt, useRef: useRefAgt } = React;

const AGT_AVATAR = { dyson: "Dyson", eco: "Eco" };
const AGT_ACCENT = { dyson: "#2DD4BF", eco: "#22C55E" };
const AGT_TASK_STATUS = {
  queued:    { label: "Queued",    color: "#4F7CFF" },
  planned:   { label: "Planned",   color: "#8B5CF6" },
  working:   { label: "Working",   color: "#F59E0B" },
  done:      { label: "Done",      color: "#22C55E" },
  cancelled: { label: "Cancelled", color: "#64748B" },
};

function AgtConnBanner({ st }) {
  const Icons = window.Icons;
  if (!st) return null;
  if (st.connected) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="dot online pulse" />
        <span className="faint" style={{ fontSize: 12 }}>
          Agents connected · Anthropic ({st.keySource} key) · <span className="mono">{st.model}</span>
        </span>
      </div>
    );
  }
  return (
    <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 12, borderColor: "var(--orange)" }}>
      <span style={{ color: "var(--orange)" }}><Icons.Bot size={18} /></span>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: 13.5 }}>Agents not connected</div>
        <div className="faint" style={{ fontSize: 12 }}>
          Add <span className="mono">ANTHROPIC_API_KEY</span> to <span className="mono">forge-agency/config/agency.env</span>, then reload.
        </div>
      </div>
    </div>
  );
}

function AgtCard({ a, onOpen }) {
  const Icons = window.Icons;
  const Av = Icons[AGT_AVATAR[a.id]] || Icons.Bot;
  const accent = AGT_ACCENT[a.id] || "#8B5CF6";
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 46, height: 46, borderRadius: 12, flexShrink: 0, display: "grid", placeItems: "center",
          background: accent + "1f", color: accent }}><Av size={24} /></div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 16 }}>{a.name}</div>
          <div className="faint" style={{ fontSize: 12 }}>{a.role}</div>
        </div>
        <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10.5, fontWeight: 600,
          color: a.online ? "var(--green)" : "var(--muted)" }}>
          <span className={"dot" + (a.online ? " online pulse" : "")} /> {a.online ? "ONLINE" : "OFFLINE"}
        </span>
      </div>
      <div className="faint" style={{ fontSize: 12.5, lineHeight: 1.5 }}>{a.blurb}</div>
      <div style={{ display: "flex", gap: 16, fontSize: 12 }}>
        <span><b>{a.openTasks}</b> <span className="faint">open tasks</span></span>
        <span><b>{a.messages}</b> <span className="faint">messages</span></span>
      </div>
      <button className="tab" onClick={() => onOpen(a)}
        style={{ background: accent + "22", color: accent, borderColor: accent + "55", fontWeight: 600,
          display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
        <Icons.Command size={14} /> Open {a.name}
      </button>
    </div>
  );
}

// ---- chat ----
function AgtChat({ agent }) {
  const Icons = window.Icons;
  const { data } = window.useApi("/api/agency/agents/history?agent=" + agent.id);
  const [msgs, setMsgs] = useStateAgt([]);
  const [text, setText] = useStateAgt("");
  const [busy, setBusy] = useStateAgt(false);
  const feedRef = useRefAgt(null);
  const accent = AGT_ACCENT[agent.id] || "#8B5CF6";

  useEffectAgt(() => { if (data && data.history) setMsgs(data.history); }, [data]);
  useEffectAgt(() => { if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight; }, [msgs, busy]);

  async function send() {
    const m = text.trim();
    if (!m || busy) return;
    setText("");
    const hist = msgs.slice();
    setMsgs([...hist, { role: "user", text: m, ts: Date.now() }]);
    setBusy(true);
    try {
      const r = await window.apiPost("/api/agency/agents/chat", { agentId: agent.id, message: m, history: hist });
      setMsgs((cur) => [...cur, { role: "agent", text: r.reply || "On it.", ts: Date.now() }]);
    } catch (e) {
      setMsgs((cur) => [...cur, { role: "agent", text: "Error: " + (e.message || e), ts: Date.now() }]);
    }
    setBusy(false);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div ref={feedRef} className="card card-pad" style={{ height: "46vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
        {msgs.length === 0 && <div className="faint" style={{ fontSize: 13, margin: "auto", textAlign: "center" }}>
          Say hi to {agent.name} or ask for a plan. Conversations sync + persist.</div>}
        {msgs.map((m, i) => {
          const mine = m.role === "user";
          return (
            <div key={i} style={{ display: "flex", justifyContent: mine ? "flex-end" : "flex-start" }}>
              <div style={{ maxWidth: "78%", padding: "9px 12px", borderRadius: 13, fontSize: 13, whiteSpace: "pre-wrap", lineHeight: 1.5,
                background: mine ? "var(--accent, #4F7CFF)" : "var(--card-2)",
                color: mine ? "#fff" : "var(--text)" }}>{m.text}</div>
            </div>
          );
        })}
        {busy && <div style={{ display: "flex", justifyContent: "flex-start" }}>
          <div style={{ padding: "9px 12px", borderRadius: 13, background: "var(--card-2)", color: accent, fontSize: 13 }}>
            {agent.name} is thinking…</div></div>}
      </div>
      <div style={{ display: "flex", gap: 9 }}>
        <input style={{ ...window.AgUI.inp, flex: 1 }} value={text} placeholder={"Message " + agent.name + "…"}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
        <button className="tab" onClick={send} disabled={busy}
          style={{ background: accent, color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
          <Icons.Send size={14} /> Send</button>
      </div>
    </div>
  );
}

// ---- tasks ----
function AgtTasks({ agent }) {
  const Icons = window.Icons;
  const { data, refresh } = window.useApi("/api/agency/agents/tasks?agent=" + agent.id, { interval: 15000 });
  const [title, setTitle] = useStateAgt("");
  const [busy, setBusy] = useStateAgt(false);
  const tasks = (data && data.tasks) || [];

  async function add() {
    const t = title.trim();
    if (!t || busy) return;
    setBusy(true); setTitle("");
    try { await window.apiPost("/api/agency/agents/task", { agentId: agent.id, title: t }); refresh(); }
    catch (e) { window.alert("Task failed: " + (e.message || e)); }
    setBusy(false);
  }
  async function setStatus(id, status) {
    try { await window.apiPost("/api/agency/agents/task/update", { id, status }); refresh(); }
    catch (e) { window.alert("Update failed: " + (e.message || e)); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 9 }}>
        <input style={{ ...window.AgUI.inp, flex: 1 }} value={title} placeholder={"Send " + agent.name + " a task…"}
          onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
        <button className="tab" onClick={add} disabled={busy}
          style={{ background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
          <Icons.Plus size={14} /> {busy ? "Sending…" : "Assign"}</button>
      </div>
      {tasks.length === 0 && <div className="faint" style={{ fontSize: 13 }}>No tasks yet. Assign one — {agent.name} drafts a plan and queues it.</div>}
      {tasks.map((t) => (
        <div key={t.id} className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ minWidth: 0, flex: 1, fontWeight: 600, fontSize: 13.5 }}>{t.title}</div>
            <window.AgUI.Badge status={t.status} map={AGT_TASK_STATUS} />
            <span className="faint" style={{ fontSize: 11 }}>{window.timeAgo(t.createdAt)}</span>
          </div>
          {t.plan && <div className="faint" style={{ fontSize: 12.5, whiteSpace: "pre-wrap", lineHeight: 1.5,
            borderLeft: "2px solid var(--border)", paddingLeft: 10 }}>{t.plan}</div>}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            {t.status !== "working" && t.status !== "done" && <button className="tab" onClick={() => setStatus(t.id, "working")}>Start</button>}
            {t.status !== "done" && <button className="tab" onClick={() => setStatus(t.id, "done")}
              style={{ color: "var(--green)" }}>Mark Done</button>}
            {t.status !== "cancelled" && t.status !== "done" && <button className="tab" onClick={() => setStatus(t.id, "cancelled")}
              style={{ color: "var(--red)" }}>Cancel</button>}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---- console (chat | tasks | operate) ----
function AgtComms() {
  const Icons = window.Icons;
  const { data } = window.useApi("/api/bus?limit=30", { interval: 8000 });
  const msgs = (data && data.messages) || [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="faint" style={{ fontSize: 12.5 }}>Live messages between your agents — handoffs, alerts, and self-improvement broadcasts (shared with the wholesale side).</div>
      {msgs.length === 0 && <div className="faint" style={{ fontSize: 12.5 }}>No agent messages yet.</div>}
      {msgs.map((m, i) => {
        const c = { handoff: "#EC4899", alert: "#EF4444", status: "#8B5CF6", note: "#4F7CFF" }[m.kind] || "#4F7CFF";
        return (
          <div key={m.id || i} className="card card-pad" style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "10px 12px" }}>
            <div style={{ width: 28, height: 28, borderRadius: 8, flexShrink: 0, display: "grid", placeItems: "center", background: c + "1f", color: c }}><Icons.Send size={13} /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="faint" style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.3 }}>{(m.from || "?").toUpperCase()} → {(m.to || "?").toUpperCase()} · {m.kind}</div>
              <div style={{ fontSize: 12.5 }}>{m.text}</div>
              <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>{window.timeAgo(m.ts)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function AgtConsole({ agent, st, onBack }) {
  const Icons = window.Icons;
  const [tab, setTab] = useStateAgt("chat");
  const [busy, setBusy] = useStateAgt(null);
  const Av = Icons[AGT_AVATAR[agent.id]] || Icons.Bot;
  const accent = AGT_ACCENT[agent.id] || "#8B5CF6";
  const OperateComp = window[agent.page];

  async function learnNow() {
    setBusy("learn");
    try {
      const r = await window.apiPost("/api/agency/agents/learn", { agentId: agent.id });
      if (r && r.error) alert(agent.name + ": " + r.error);
    } catch (e) { alert("Learn: " + e.message); }
    setBusy(null);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button className="tab" onClick={onBack} style={{ padding: "7px 10px" }}><Icons.Chevron size={14} style={{ transform: "rotate(90deg)" }} /> All agents</button>
        <div style={{ width: 40, height: 40, borderRadius: 11, display: "grid", placeItems: "center", background: accent + "1f", color: accent }}><Av size={22} /></div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 19, fontWeight: 700 }}>{agent.name}</div>
          <div className="faint" style={{ fontSize: 12 }}>{agent.role}</div>
          <div className="faint" style={{ fontSize: 11, marginTop: 2 }}>
            playbook <b style={{ color: agent.skillsLoaded ? "var(--green)" : "var(--orange)" }}>{agent.skillsLoaded ? "loaded from brain" : "seed only"}</b>
            {" · "}self-improved <b>{agent.learnCount || 0}×</b>{agent.lastLearnedAt ? ` (last ${window.timeAgo(agent.lastLearnedAt)})` : ""}
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 600, color: agent.online ? "var(--green)" : "var(--muted)" }}>
            <span className={"dot" + (agent.online ? " online pulse" : "")} /> {agent.online ? "ONLINE" : "OFFLINE"}
          </span>
          <button className="tab" onClick={learnNow} disabled={busy === "learn"} style={{ fontSize: 11, borderColor: "var(--violet)", color: "var(--violet)" }} title="Reflect on recent work + rewrite this agent's playbook in the brain">{busy === "learn" ? "Learning…" : "Learn from brain"}</button>
        </div>
      </div>

      {!st.connected && <AgtConnBanner st={st} />}

      <div className="tabs" style={{ display: "flex", gap: 8 }}>
        {[["chat", "Chat"], ["tasks", "Tasks"], ["operate", "Operate"], ["comms", "Comms"]].map(([k, l]) => (
          <button key={k} className={"tab" + (tab === k ? " active" : "")} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {tab === "chat" && <AgtChat agent={agent} />}
      {tab === "tasks" && <AgtTasks agent={agent} />}
      {tab === "comms" && <AgtComms />}
      {tab === "operate" && (
        <div>
          <div className="faint" style={{ fontSize: 12.5, marginBottom: 10 }}>
            {agent.name}'s full operating panel — same tools, embedded here.
          </div>
          {OperateComp ? <OperateComp /> : <div className="faint">Operate panel unavailable.</div>}
        </div>
      )}
    </div>
  );
}

function AgencyAgents() {
  const Icons = window.Icons;
  const { data: st, error, loading, refresh } = window.useApi("/api/agency/agents", { interval: 20000 });
  const [openId, setOpenId] = useStateAgt(null);
  const agents = (st && st.agents) || [];
  const current = agents.find((a) => a.id === openId);

  if (current) return <AgtConsole agent={current} st={st} onBack={() => { setOpenId(null); refresh(); }} />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Agents</h1>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>Your AI team — open one to chat, assign tasks, or operate it.</div>
      </div>
      <AgtConnBanner st={st} />
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {loading && !st && <window.LoadingRow label="Waking the agents…" />}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16 }}>
        {agents.map((a) => <AgtCard key={a.id} a={a} onOpen={(x) => setOpenId(x.id)} />)}
      </div>
    </div>
  );
}

Object.assign(window, { AgencyAgents });
