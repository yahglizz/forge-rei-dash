// agents_hub.jsx — THE Agents tab. One place to operate every agent in the business.
//
// Left rail: all 7 agents grouped by business (Wholesale / Agency / Daycare / Dropship) + any live
// Retell voice agents. Right: the selected agent — Chat (talk + assign), Tasks (what
// you've given them), Console (their full deep page, relocated here from the sidebar).
//
// Nothing was deleted to build this: the old per-agent pages (Dyson, Eco, Solomon,
// Command Center) are the SAME components, now rendered inside the Console tab.
//
// Collision rules (CLAUDE.md §7): unique hook aliases, Hub-prefixed globals, and no
// computed JSX tags — every dynamic component is resolved to a capitalized const first.
const { useState: useStateHub, useEffect: useEffectHub, useRef: useRefHub } = React;

// Each agent's deep page, relocated from the sidebar into the Console tab. Stored as a
// NAME here and resolved to a capitalized const before render — a computed JSX tag
// white-screens the app (CLAUDE.md §7), so the component is never indexed inline.
const HUB_CONSOLE = {
  marcus: "MarcusCommand",
  scout: "ScreeningPage",
  dyson: "AgencyDyson",
  eco: "AgencyEco",
  solomon: "DaycareDirector",
  midas: "DropshipAgents",
};

const HUB_BIZ_COLOR = {
  wholesale: "#4F7CFF",
  agency: "#8B5CF6",
  daycare: "#2DD4BF",
  dropship: "#F59E0B",
  voice: "#F4B860",
  cross: "#EC4899",
  system: "#94A3B8",
};

// agent id -> business, so the coaching feed can color an entry by who sent it even
// when that agent isn't in the current workspace's roster (cross-business view).
const HUB_BUSINESS_OF = {
  scout: "wholesale", marcus: "wholesale", atlas: "wholesale",
  followup: "wholesale", ace: "wholesale", autopilot: "wholesale",
  dyson: "agency", eco: "agency",
  solomon: "daycare",
  midas: "dropship",
  orion: "cross", briefs: "system",
};

// The Agent Control Center fields for one agent (roster().control = agents_hub.registry
// row): status pill, last run / success, errors, tasks, current task, and the error text.
// Pill + time formatter come from agent_center.jsx; both are optional at render time.
function HubControlLine({ c }) {
  if (!c) return null;
  const HubPill = window.AccStatusPill || null;
  const ago = window.accAgo || ((ms) => (ms ? new Date(ms).toLocaleString() : "—"));
  const err = c.lastError || (c.dependencyHealth || {}).aiReason;
  return <div className="hub-control">
    <div className="hub-control-stats">
      {HubPill && <HubPill status={c.status} />}
      <span>Last run <b>{ago(c.lastRun)}</b></span>
      <span>Last success <b>{ago(c.lastSuccessAt)}</b></span>
      <span>Errors <b>{c.errorCount == null ? "—" : c.errorCount}</b></span>
      <span>Tasks <b>{c.tasksCompleted} done / {c.tasksFailed} failed</b></span>
      {c.pendingApprovals > 0 && <span>{c.pendingApprovals} awaiting approval</span>}
    </div>
    {c.currentTask && <div className="hub-now">Working on: {c.currentTask}</div>}
    {err && <div className="hub-error" role="status">⚠ {err}</div>}
  </div>;
}

function HubDot({ ok, status, title }) {
  const tone = status === "FAILED" ? "#EF4444" : status === "DEGRADED" || status === "WAITING FOR APPROVAL" ? "#F59E0B" : ok ? "#22C55E" : "#6B7280";
  return <span title={title || status || (ok ? "ready" : "not ready")} style={{
    display: "inline-block", width: 7, height: 7, borderRadius: 9,
    background: tone, flex: "0 0 auto",
  }} />;
}

// ── left rail ─────────────────────────────────────────────────────────────────
function HubRail({ agents, businesses, sel, onSel }) {
  const groups = businesses
    .map((b) => ({ ...b, rows: agents.filter((a) => a.business === b.id) }))
    .filter((g) => g.rows.length);

  return <aside className="card hub-rail">
    <div className="hub-rail-heading">
      <span className="hub-eyebrow">Agent directory</span>
      <strong>Your team</strong>
      <small>Select an agent to see their work and messages.</small>
    </div>
    {groups.map((g) => <div key={g.id} className="hub-rail-group">
      <div className="hub-group-label">{g.label}</div>
      {g.rows.map((a) => {
        const on = a.id === sel;
        const color = HUB_BIZ_COLOR[a.business] || "#4F7CFF";
        const ready = a.status && a.status.aiReady !== undefined
          ? !!a.status.aiReady : true;
        return <button key={a.id} onClick={() => onSel(a.id)}
          className={"hub-agent" + (on ? " selected" : "")}
          style={{ "--agent-accent": color }} aria-current={on ? "true" : undefined}>
          <span className="hub-agent-avatar">{a.emoji}</span>
          <span className="hub-agent-copy">
            <span className="hub-agent-name">
              <b>{a.name}</b>
              <HubDot ok={ready} status={a.control && a.control.status}
                title={a.control && a.control.status ? a.control.status : ready ? "brain ready" : "no API key"} />
            </span>
            <span className="hub-agent-role">{a.role}</span>
          </span>
          <span className="hub-agent-arrow" aria-hidden="true">›</span>
        </button>;
      })}
    </div>)}
  </aside>;
}

// ── chat ──────────────────────────────────────────────────────────────────────
function HubChat({ agent, agents }) {
  const [msgs, setMsgs] = useStateHub([]);
  const [text, setText] = useStateHub("");
  const [busy, setBusy] = useStateHub(false);
  const [err, setErr] = useStateHub(null);
  const endRef = useRefHub(null);

  // Always coerce to an array. There is no error boundary in this app (in-browser Babel),
  // so a payload shaped differently than expected doesn't degrade — it blanks the tab.
  useEffectHub(() => {
    let dead = false;
    setMsgs([]); setErr(null);
    window.apiGet("/api/hub/history?agent=" + encodeURIComponent(agent.id))
      .then((d) => {
        if (dead) return;
        const rows = d && d.messages;
        setMsgs(Array.isArray(rows) ? rows : []);
      })
      .catch(() => { if (!dead) setMsgs([]); });
    return () => { dead = true; };
  }, [agent.id]);

  useEffectHub(() => {
    if (endRef.current) endRef.current.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy]);

  function send() {
    const t = text.trim();
    if (!t || busy) return;
    setText(""); setErr(null); setBusy(true);
    setMsgs((m) => m.concat([{ role: "user", text: t }]));
    window.apiPost("/api/hub/chat", { agentId: agent.id, message: t })
      .then((d) => {
        if (d.needsKey) setErr("No Anthropic key wired for this agent yet.");
        setMsgs((m) => m.concat([{ role: "agent", text: d.reply || "…" }]));
      })
      .catch((e) => setErr(String(e.message || e)))
      .then(() => setBusy(false));
  }

  const color = HUB_BIZ_COLOR[agent.business] || "#4F7CFF";
  return <div className="hub-chat" style={{ "--agent-accent": color }}>
    <div className="hub-chat-feed">
      {!msgs.length && !busy && <div className="hub-chat-empty">
        <span className="hub-chat-empty-icon">{agent.emoji}</span>
        <strong>Start a conversation with {agent.name}</strong>
        <p>Ask what they're seeing, or give them work.</p>
        <small>{agent.blurb}</small>
      </div>}
      {msgs.map((m, i) => {
        const mine = m.role === "user";
        return <div key={i} className={"hub-message" + (mine ? " mine" : "")}>
          {!mine && <span className="hub-message-avatar">{agent.emoji}</span>}
          <div className="hub-message-body">
            {!mine && <span className="hub-message-author">{agent.name}</span>}
            <div className="hub-message-bubble">{m.text}</div>
          </div>
        </div>;
      })}
      {busy && <div className="hub-thinking"><span className="typing"><span/><span/><span/></span>{agent.name} is thinking…</div>}
      <div ref={endRef} />
    </div>
    {err && <div className="hub-error" role="alert">{err}</div>}
    <div className="hub-composer">
      <input
        className="input"
        value={text}
        placeholder={"Message " + agent.name + "… (or assign work: \"pull the 5 hottest leads\")"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
        aria-label={"Message " + agent.name}
      />
      <button className="btn btn-primary" onClick={send} disabled={busy || !text.trim()}>Send</button>
    </div>
    <HubAskPeer agent={agent} agents={agents} />
  </div>;
}

// ── tasks ─────────────────────────────────────────────────────────────────────
function HubTasks({ agent }) {
  const [rows, setRows] = useStateHub([]);
  const [title, setTitle] = useStateHub("");
  const [busy, setBusy] = useStateHub(false);
  const [err, setErr] = useStateHub(null);

  function load() {
    window.apiGet("/api/hub/tasks?agent=" + encodeURIComponent(agent.id))
      .then((d) => setRows(Array.isArray(d && d.tasks) ? d.tasks : []))
      .catch(() => setRows([]));
  }
  useEffectHub(() => { load(); }, [agent.id]);

  function add() {
    const t = title.trim();
    if (!t || busy) return;
    setBusy(true); setErr(null);
    window.apiPost("/api/hub/task", { agentId: agent.id, title: t })
      .then(() => { setTitle(""); load(); })
      .catch((e) => setErr(String(e.message || e)))
      .then(() => setBusy(false));
  }
  function mark(id, status) {
    window.apiPost("/api/hub/task/update", { id, status }).then(load).catch(() => {});
  }

  const open = rows.filter((r) => r.status === "open");
  const closed = rows.filter((r) => r.status !== "open");
  return <div style={{ overflowY: "auto", height: "100%", minHeight: 0 }}>
    <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
      <input className="input" value={title} placeholder={"Assign " + agent.name + " a task…"}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") add(); }}
        style={{ flex: 1 }} />
      <button className="btn btn-primary" onClick={add} disabled={busy || !title.trim()}>Assign</button>
    </div>
    {err && <div style={{ color: "#EF4444", fontSize: 12, marginBottom: 8 }}>{err}</div>}
    <div style={{ fontSize: 11, opacity: .55, marginBottom: 8 }}>
      Assigning is not acting — {agent.name} picks this up and comes back with a
      recommendation. Outward actions still need your approval.
    </div>

    {!open.length && <div style={{ opacity: .5, fontSize: 13, padding: 10 }}>No open tasks.</div>}
    {open.map((t) => <div key={t.id} className="card card-pad" style={{
      display: "flex", alignItems: "center", gap: 10, marginBottom: 6, padding: "10px 12px",
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <b style={{ fontSize: 13, fontWeight: 500 }}>{t.title}</b>
        <div style={{ fontSize: 11, opacity: .5 }}>{window.timeAgo ? window.timeAgo(t.createdAt) : ""}</div>
      </div>
      <button className="btn" onClick={() => mark(t.id, "done")}>Done</button>
      <button className="btn" onClick={() => mark(t.id, "dismissed")}>✕</button>
    </div>)}

    {closed.length > 0 && <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".08em", opacity: .45, marginBottom: 6 }}>
        Closed
      </div>
      {closed.slice(0, 12).map((t) => t.status === "failed"
        ? <div key={t.id} style={{ fontSize: 12, padding: "5px 2px" }}>
          <span style={{ opacity: .7 }}>{t.title}</span>
          <div style={{ color: "#EF4444", fontSize: 11, wordBreak: "break-word" }}>⚠ failed: {t.error}</div>
        </div>
        : <div key={t.id} style={{
          fontSize: 12, opacity: .5, padding: "5px 2px", textDecoration: "line-through",
        }}>{t.title}</div>)}
    </div>}
  </div>;
}

// ── ask a peer (cross-agent coaching, in the compose area) ────────────────────
// One agent asks another a direct question. The answer is logged to the shared
// coaching feed (INSIGHTS ONLY — text, never a credential or an outward action).
function HubAskPeer({ agent, agents }) {
  const [openAsk, setOpenAsk] = useStateHub(false);
  const [peer, setPeer] = useStateHub("");
  const [q, setQ] = useStateHub("");
  const [busy, setBusy] = useStateHub(false);
  const [note, setNote] = useStateHub(null);

  const peers = (agents || []).filter((a) => a.id !== agent.id);
  useEffectHub(() => {
    setPeer(peers.length ? peers[0].id : "");
    setNote(null); setQ("");
  }, [agent.id, agents.length]);

  function askPeer() {
    const question = q.trim();
    if (!question || !peer || busy) return;
    setBusy(true); setNote(null);
    window.apiPost("/api/coach/ask", { from: agent.id, to: peer, question })
      .then((d) => {
        if (d && d.error) { setNote("⚠ " + d.error); return; }
        setNote("✓ " + agent.name + " asked " + peer + " — answer added to the Coach feed.");
        setQ("");
        window.dispatchEvent(new Event("hubCoachRefresh"));  // nudge the feed to reload
      })
      .catch((e) => setNote("⚠ " + String(e.message || e)))
      .then(() => setBusy(false));
  }

  if (!peers.length) return null;
  return <div style={{ marginTop: 8 }}>
    <button onClick={() => setOpenAsk((v) => !v)} style={{
      fontSize: 11, opacity: .7, cursor: "pointer", background: "transparent",
      border: "none", color: "inherit", padding: "2px 0",
    }}>{openAsk ? "▾" : "▸"} 🤝 ask a peer</button>
    {openAsk && <div style={{ display: "flex", gap: 8, marginTop: 6, alignItems: "center" }}>
      <select className="input" value={peer} onChange={(e) => setPeer(e.target.value)}
        style={{ flex: "0 0 130px" }}>
        {peers.map((p) => <option key={p.id} value={p.id}>{p.emoji + " " + p.name}</option>)}
      </select>
      <input className="input" value={q} placeholder={"Ask " + (peer || "a peer") + "…"}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") askPeer(); }}
        style={{ flex: 1 }} />
      <button className="btn" onClick={askPeer} disabled={busy || !q.trim() || !peer}>Ask</button>
    </div>}
    {note && <div style={{ fontSize: 11, opacity: .75, marginTop: 5 }}>{note}</div>}
  </div>;
}

// ── coaching feed (the live cross-agent network view) ─────────────────────────
// Polls /api/coach/feed every ~10s and shows what the agents are teaching each other,
// newest first. 💡 = a broadcast insight, ❓ = a peer Q&A exchange.
function HubCoachFeed({ agent, agents }) {
  const [rows, setRows] = useStateHub([]);
  const [err, setErr] = useStateHub(null);

  function loadCoach() {
    window.apiGet("/api/coach/feed?limit=40")
      .then((d) => setRows(Array.isArray(d && d.feed) ? d.feed : []))
      .catch((e) => setErr(String(e.message || e)));
  }
  useEffectHub(() => {
    loadCoach();
    const iv = setInterval(loadCoach, 10000);
    const onBump = () => loadCoach();
    window.addEventListener("hubCoachRefresh", onBump);
    return () => { clearInterval(iv); window.removeEventListener("hubCoachRefresh", onBump); };
  }, []);

  return <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
    <div style={{ fontSize: 11, opacity: .55, marginBottom: 8 }}>
      Live cross-agent coaching — insights + Q&A the agents share across all three
      businesses. Knowledge only; every outward action still needs your approval.
    </div>
    <div style={{ marginBottom: 10 }}>
      <HubAskPeer agent={agent} agents={agents} />
    </div>
    {err && <div style={{ color: "#EF4444", fontSize: 12, marginBottom: 8 }}>{err}</div>}
    <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
      {!rows.length && <div style={{ opacity: .5, fontSize: 13, padding: 12 }}>
        No coaching yet. When an agent learns something transferable it shows up here.
      </div>}
      {rows.map((c, i) => {
        const isQa = c.kindTag === "qa";
        const color = HUB_BIZ_COLOR[HUB_BUSINESS_OF[c.from] || ""] || "#4F7CFF";
        return <div key={c.id || i} className="card" style={{
          padding: "9px 11px", marginBottom: 6,
          borderLeft: "3px solid " + color,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
            <span style={{ fontSize: 13 }}>{isQa ? "❓" : "💡"}</span>
            <b style={{ fontSize: 12 }}>{c.from} → {c.to}</b>
            <span style={{ marginLeft: "auto", fontSize: 10, opacity: .45 }}>
              {window.timeAgo ? window.timeAgo(c.ts) : ""}
            </span>
          </div>
          <div style={{ fontSize: 12, opacity: .85, lineHeight: 1.5, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {c.insight}
          </div>
        </div>;
      })}
    </div>
  </div>;
}

// ── console (the agent's full page, relocated from the sidebar) ───────────────
function HubConsole({ agent }) {
  const name = HUB_CONSOLE[agent.id];
  const Cmp = name && window[name] ? window[name] : null;   // resolve BEFORE render
  if (!Cmp) {
    return <div style={{ opacity: .55, fontSize: 13, padding: 20 }}>
      {agent.name} has no separate console — everything they do runs through Chat and
      Tasks, plus the background loops on the box.
    </div>;
  }
  return <div style={{ overflowY: "auto", height: "100%", minHeight: 0 }}><Cmp /></div>;
}

// ── the page ──────────────────────────────────────────────────────────────────
function HubAgentsPage({ ws }) {
  const [sel, setSel] = useStateHub(null);
  const [tab, setTab] = useStateHub("chat");

  // The hub is SCOPED to the workspace you're in: the Daycare tab shows Solomon —
  // not the wholesale team, and not the Retell voice agents (those live in the REI
  // Outbound tab, where they're actually configured).
  const wsId = ws || localStorage.getItem("forge_ws") || "rei";
  const biz = wsId === "agency" ? "agency" : wsId === "daycare" ? "daycare" : "wholesale";
  const roster = window.useApi("/api/hub/roster?business=" + biz, { interval: 30000 });

  const data = roster.data || {};
  const agents = Array.isArray(data.agents) ? data.agents : [];
  const businesses = Array.isArray(data.businesses) ? data.businesses : [];

  // Land on the first agent of this business.
  useEffectHub(() => {
    if (sel || !agents.length) return;
    setSel(agents[0].id);
  }, [agents.length, biz]);

  // Switching workspace swaps the roster — drop a stale selection from the old business.
  useEffectHub(() => { setSel(null); setTab("chat"); }, [biz]);

  if (roster.loading && !agents.length) {
    return <div className="card card-pad" style={{ opacity: .6 }}>Loading agents…</div>;
  }
  if (roster.error) {
    return <div className="card card-pad" style={{ color: "#EF4444" }}>
      Couldn't load the agents: {String(roster.error.message || roster.error)}
    </div>;
  }

  const agent = agents.find((a) => a.id === sel) || agents[0];
  if (!agent) return <div className="card card-pad">No agents wired yet.</div>;

  const color = HUB_BIZ_COLOR[agent.business] || "#4F7CFF";
  const TABS = [["chat", "Chat"], ["tasks", "Tasks"], ["coach", "Coach"], ["console", "Console"]];
  const panel = tab === "chat" ? <HubChat agent={agent} agents={agents} />
    : tab === "tasks" ? <HubTasks agent={agent} />
      : tab === "coach" ? <HubCoachFeed agent={agent} agents={agents} />
        : <HubConsole agent={agent} />;

  return <div className="hub-layout">
    <HubRail agents={agents} businesses={businesses} sel={agent.id} onSel={(id) => { setSel(id); setTab("chat"); }} />

    <section className="card hub-panel" style={{ "--agent-accent": color }}>
      <div className="hub-panel-head">
        <span className="hub-panel-avatar">{agent.emoji}</span>
        <div className="hub-panel-identity">
          <div className="hub-panel-name">
            <b>{agent.name}</b>
            <span className="hub-business-pill">{agent.businessLabel}</span>
          </div>
          <div className="hub-panel-role">{agent.role}</div>
        </div>
        <div className="hub-tabs" role="tablist" aria-label={agent.name + " views"}>
          {TABS.map(([id, label]) => <button key={id} onClick={() => setTab(id)}
            className={tab === id ? "active" : ""} role="tab" aria-selected={tab === id}>{label}</button>)}
        </div>
      </div>
      <HubControlLine c={agent.control} />
      <div className="hub-panel-body" role="tabpanel">
        {panel}
      </div>
    </section>
  </div>;
}

Object.assign(window, { HubAgentsPage, HubRail, HubChat, HubTasks, HubConsole, HubCoachFeed, HubAskPeer, HubControlLine });
