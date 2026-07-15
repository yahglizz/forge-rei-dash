// agents_hub.jsx — THE Agents tab. One place to operate every agent in the business.
//
// Left rail: all 8 agents grouped by business (Wholesale / Agency / Daycare) + any live
// Retell voice agents. Right: the selected agent — Chat (talk + assign), Tasks (what
// you've given them), Console (their full deep page, relocated here from the sidebar).
//
// Nothing was deleted to build this: the old per-agent pages (Dyson, Eco, Solomon, Nora,
// Nova, Command Center) are the SAME components, now rendered inside the Console tab.
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
  nora: "DaycareFamilyAgent",
  nova: "DaycareAdOpsAgent",
};

const HUB_BIZ_COLOR = {
  wholesale: "#4F7CFF",
  agency: "#8B5CF6",
  daycare: "#2DD4BF",
  voice: "#F4B860",
};

// agent id -> business, so the coaching feed can color an entry by who sent it even
// when that agent isn't in the current workspace's roster (cross-business view).
const HUB_BUSINESS_OF = {
  scout: "wholesale", marcus: "wholesale", atlas: "wholesale",
  dyson: "agency", eco: "agency",
  solomon: "daycare", nora: "daycare", nova: "daycare",
};

function HubDot({ ok, title }) {
  return <span title={title || (ok ? "ready" : "not ready")} style={{
    display: "inline-block", width: 7, height: 7, borderRadius: 9,
    background: ok ? "#22C55E" : "#6B7280", flex: "0 0 auto",
  }} />;
}

// ── left rail ─────────────────────────────────────────────────────────────────
function HubRail({ agents, businesses, sel, onSel }) {
  const groups = businesses
    .map((b) => ({ ...b, rows: agents.filter((a) => a.business === b.id) }))
    .filter((g) => g.rows.length);

  return <div className="card" style={{ padding: 10, overflowY: "auto", minHeight: 0 }}>
    {groups.map((g) => <div key={g.id} style={{ marginBottom: 14 }}>
      <div style={{
        fontSize: 10, textTransform: "uppercase", letterSpacing: ".08em",
        opacity: .55, padding: "4px 8px", fontWeight: 600,
      }}>{g.label}</div>
      {g.rows.map((a) => {
        const on = a.id === sel;
        const color = HUB_BIZ_COLOR[a.business] || "#4F7CFF";
        const ready = a.status && a.status.aiReady !== undefined
          ? !!a.status.aiReady : true;
        return <button key={a.id} onClick={() => onSel(a.id)} style={{
          display: "flex", gap: 10, alignItems: "center", width: "100%",
          padding: "9px 8px", marginBottom: 2, borderRadius: 9, cursor: "pointer",
          textAlign: "left", border: "1px solid " + (on ? color : "transparent"),
          background: on ? color + "1A" : "transparent", color: "inherit",
        }}>
          <span style={{ fontSize: 18, lineHeight: 1 }}>{a.emoji}</span>
          <span style={{ minWidth: 0, flex: 1 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <b style={{ fontSize: 13 }}>{a.name}</b>
              <HubDot ok={ready} title={ready ? "brain ready" : "no API key"} />
            </span>
            <span style={{
              display: "block", fontSize: 11, opacity: .6, whiteSpace: "nowrap",
              overflow: "hidden", textOverflow: "ellipsis",
            }}>{a.role}</span>
          </span>
        </button>;
      })}
    </div>)}
  </div>;
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
  return <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
    {models && Array.isArray(models.providers) && <div style={{
      display: "flex", alignItems: "center", gap: 8, padding: "0 2px 8px", fontSize: 12,
    }}>
      <span style={{ opacity: .55, whiteSpace: "nowrap" }}>Model</span>
      <select className="input" value={curModel} onChange={(e) => pickModel(e.target.value)}
        title="Who answers — Claude, or your ChatGPT via the Codex CLI"
        style={{ flex: 1, maxWidth: 300, padding: "4px 8px", fontSize: 12 }}>
        {models.providers.map((p) => <optgroup key={p.id}
          label={p.label + (p.ready ? "" : " — " + (p.note || "unavailable"))}>
          {(p.models || []).map((m) => <option key={m.id} value={m.id} disabled={!p.ready}>
            {m.label}{p.ready ? "" : " · unavailable"}
          </option>)}
        </optgroup>)}
      </select>
    </div>}
    <div style={{ flex: 1, overflowY: "auto", padding: "4px 2px", minHeight: 0 }}>
      {!msgs.length && !busy && <div style={{ opacity: .55, fontSize: 13, padding: 18, textAlign: "center" }}>
        Talk to {agent.name} — ask what they're seeing, or give them work.
        <div style={{ fontSize: 12, opacity: .8, marginTop: 6 }}>{agent.blurb}</div>
      </div>}
      {msgs.map((m, i) => {
        const mine = m.role === "user";
        return <div key={i} style={{
          display: "flex", justifyContent: mine ? "flex-end" : "flex-start", marginBottom: 8,
        }}>
          <div style={{
            maxWidth: "78%", padding: "9px 12px", borderRadius: 12, fontSize: 13,
            lineHeight: 1.5, whiteSpace: "pre-wrap", wordBreak: "break-word",
            background: mine ? color : "rgba(255,255,255,.06)",
            color: mine ? "#fff" : "inherit",
          }}>{m.text}</div>
        </div>;
      })}
      {busy && <div style={{ opacity: .6, fontSize: 12, padding: "4px 6px" }}>
        {agent.name} is thinking…
      </div>}
      <div ref={endRef} />
    </div>
    {err && <div style={{ color: "#EF4444", fontSize: 12, padding: "4px 6px" }}>{err}</div>}
    <div style={{ display: "flex", gap: 8, paddingTop: 8 }}>
      <input
        className="input"
        value={text}
        placeholder={"Message " + agent.name + "… (or assign work: \"pull the 5 hottest leads\")"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
        style={{ flex: 1 }}
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
      {closed.slice(0, 12).map((t) => <div key={t.id} style={{
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

  // The hub is SCOPED to the workspace you're in: the Daycare tab shows Solomon, Nora and
  // Nova — not the wholesale team, and not the Retell voice agents (those live in the REI
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

  return <div style={{
    display: "grid", gridTemplateColumns: "260px 1fr", gap: 14,
    height: "calc(100vh - 150px)", minHeight: 480,
  }}>
    <HubRail agents={agents} businesses={businesses} sel={agent.id} onSel={(id) => { setSel(id); setTab("chat"); }} />

    <div className="card" style={{ display: "flex", flexDirection: "column", padding: 14, minHeight: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, paddingBottom: 10 }}>
        <span style={{ fontSize: 26 }}>{agent.emoji}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <b style={{ fontSize: 16 }}>{agent.name}</b>
            <span style={{
              fontSize: 10, padding: "2px 7px", borderRadius: 20, fontWeight: 600,
              background: color + "26", color: color,
            }}>{agent.businessLabel}</span>
          </div>
          <div style={{ fontSize: 12, opacity: .6 }}>{agent.role}</div>
        </div>
        <div style={{ display: "flex", gap: 5 }}>
          {TABS.map(([id, label]) => <button key={id} onClick={() => setTab(id)} style={{
            padding: "6px 13px", borderRadius: 8, fontSize: 12, cursor: "pointer",
            fontWeight: tab === id ? 600 : 400,
            border: "1px solid " + (tab === id ? color : "rgba(255,255,255,.12)"),
            background: tab === id ? color + "1A" : "transparent", color: "inherit",
          }}>{label}</button>)}
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, borderTop: "1px solid rgba(255,255,255,.07)", paddingTop: 12 }}>
        {panel}
      </div>
    </div>
  </div>;
}

Object.assign(window, { HubAgentsPage, HubRail, HubChat, HubTasks, HubConsole, HubCoachFeed, HubAskPeer });
