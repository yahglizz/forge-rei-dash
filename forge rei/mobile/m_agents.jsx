// FORGE Mobile — Agents tab: Telegram-style chat with the AI employees + the
// inter-agent comms bus. Threads are SERVER-SIDE and shared with the Telegram
// agent bot — what you say here shows up there and vice versa (same store).
// Hook aliases for this file: MA. Exports: MAgentsPage.
//
// Endpoints:
//   POST /api/agents/chat            (REI crew — server records the turn)
//   POST /api/agency/agents/chat     (agency crew — agency_agents records)
//   GET  /api/agents/history?agentId=X&limit=60   → {history:[{role:"user"|"ai",text,ts,via}]}
//   GET  /api/agency/agents/history?agent=X       → {history:[{role:"user"|"agent",text,ts}]}
//   GET  /api/bus?limit=30           → comms bus feed
const { useState: useStateMA, useEffect: useEffectMA, useRef: useRefMA } = React;

const MA_AGENTS = [
  { id: "marcus", name: "Marcus", color: "#4F7CFF", ep: "/api/agents/chat", crew: "rei",
    role: "Lead Agent · screens sellers + directs the team" },
  { id: "scout", name: "Scout", color: "#F59E0B", ep: "/api/agents/chat", crew: "rei",
    role: "Lead Triage · ranks seller threads by motivation" },
  { id: "atlas", name: "Atlas", color: "#22C55E", ep: "/api/agents/chat", crew: "rei",
    role: "Deal Underwriter · offer anchors + MAO math" },
  { id: "dyson", name: "Dyson", color: "#8B5CF6", ep: "/api/agency/agents/chat", crew: "agency",
    role: "Agency Builder · plans + ships client site edits" },
  { id: "eco", name: "Eco", color: "#2DD4BF", ep: "/api/agency/agents/chat", crew: "agency",
    role: "Agency Ads · Meta strategy, analysis + concepts" },
];
const MA_DYNAMIC_COLORS = ["#EC4899", "#0EA5E9", "#F97316", "#A78BFA"];

function MAKindColor(kind) {
  if (kind === "handoff") return "var(--violet, #8B5CF6)";
  if (kind === "alert") return "var(--red, #EF4444)";
  if (kind === "status") return "var(--blue, #4F7CFF)";
  return "var(--text-3, #64748B)"; // note + anything else
}

// Telegram-style clock: "3:42 PM", not "2h ago".
function MATime(ts) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch (e) { return ""; }
}

// Date-chip label between day groups: Today / Yesterday / Jul 9.
function MADateLabel(ts) {
  const d = new Date(ts);
  const today = new Date();
  const yest = new Date(today.getTime() - 86400000);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yest.toDateString()) return "Yesterday";
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function MAAvatar(props) {
  const a = props.agent;
  return (
    <div style={{ position: "relative", flex: "none" }}>
      <div style={{ width: props.size || 38, height: props.size || 38, borderRadius: "50%",
        display: "grid", placeItems: "center", fontSize: (props.size || 38) * 0.42,
        fontWeight: 800, color: "#fff",
        background: "linear-gradient(135deg, " + a.color + ", " + a.color + "99)" }}>
        {a.name[0]}
      </div>
      <span style={{ position: "absolute", right: -1, bottom: -1, width: 11, height: 11,
        borderRadius: "50%", background: "#22C55E",
        border: "2.5px solid var(--bg, #050B18)" }} />
    </div>
  );
}

// Comms bus — its own component so the 30s poll only runs while the Bus view is open.
function MABusCard() {
  const bus = window.useApiM("/api/bus?limit=30", { interval: 30000 });
  const msgs = (bus.data && bus.data.messages) || [];
  return (
    <window.MCard
      title="Comms Bus"
      right={
        <button className="m-chip" style={{ minHeight: 44, display: "flex", alignItems: "center", gap: 5 }}
          onClick={bus.refresh}>
          <window.MIcons.Refresh size={14} /> Refresh
        </button>
      }>
      <div className="m-fade" style={{ marginBottom: 10 }}>
        What the agents are saying to each other — handoffs, alerts, notes.
      </div>
      {bus.error && (
        <div style={{ padding: "10px 12px", borderRadius: 12, marginBottom: 10,
          background: "rgba(239,68,68,0.10)", border: "1px solid rgba(239,68,68,0.3)",
          color: "var(--red, #EF4444)", fontSize: 12.5 }}>
          Couldn't load the bus: {String(bus.error)}
        </div>
      )}
      {bus.loading && !bus.data && <window.MSpin />}
      {!bus.loading && !bus.error && msgs.length === 0 && (
        <window.MEmpty title="Bus is quiet" sub="Agent handoffs and notes will show up here." />
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {msgs.map((m) => (
          <div key={m.id} style={{ padding: "10px 12px", borderRadius: 12,
            background: "var(--card-2, #17203a)", border: "1px solid rgba(255,255,255,0.05)" }}>
            <div className="m-row" style={{ gap: 6, marginBottom: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 800, textTransform: "capitalize" }}>
                {(m.from || "?")}
              </span>
              <span className="m-fade" style={{ fontSize: 11 }}>→</span>
              <span style={{ fontSize: 12, fontWeight: 700, textTransform: "capitalize",
                color: "var(--text-2, #9FB0C7)" }}>
                {(m.to || "all")}
              </span>
              <span style={{ fontSize: 9.5, fontWeight: 800, letterSpacing: 0.5, textTransform: "uppercase",
                padding: "2px 7px", borderRadius: 999, color: MAKindColor(m.kind),
                border: "1px solid " + MAKindColor(m.kind), opacity: 0.9 }}>
                {m.kind || "note"}
              </span>
              <span className="m-fade" style={{ marginLeft: "auto", fontSize: 11, flexShrink: 0 }}>
                {window.timeAgoM(m.ts)}
              </span>
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.4, whiteSpace: "pre-wrap",
              wordBreak: "break-word", color: "var(--text, #F1F5FB)" }}>
              {m.text}
            </div>
          </div>
        ))}
      </div>
    </window.MCard>
  );
}

function MAgentsPage() {
  const [agentId, setAgentId] = useStateMA("marcus");
  const [busMode, setBusMode] = useStateMA(false);
  const [drafts, setDrafts] = useStateMA({});     // agentId -> draft text
  const [busyId, setBusyId] = useStateMA(null);   // agentId currently "thinking"
  const [pending, setPending] = useStateMA(null); // optimistic {agentId, text, ts}
  const [sendErr, setSendErr] = useStateMA(null);
  const feedRefMA = useRefMA(null);
  const rosterM = window.useApiM("/api/agents/list", { interval: 30000 });
  const dynamicAgents = rosterM.error ? [] : ((rosterM.data && rosterM.data.agents) || [])
    .filter((a) => a && a.id && !MA_AGENTS.some((fixed) => fixed.id === a.id))
    .map((a, i) => ({
      id: a.id,
      name: a.name || "Agent",
      color: MA_DYNAMIC_COLORS[i % MA_DYNAMIC_COLORS.length],
      ep: "/api/agents/chat",
      crew: "rei",
      role: a.role || "Outbound voice agent · Retell",
    }));
  const agents = MA_AGENTS.concat(dynamicAgents);

  const active = agents.find((a) => a.id === agentId) || agents[0];
  const draft = drafts[active.id] || "";
  const thinking = busyId === active.id;

  // Server-side shared thread — the SAME store the Telegram bot writes, polled
  // so messages sent from Telegram show up here without a reload.
  const histPath = active.crew === "agency"
    ? "/api/agency/agents/history?agent=" + active.id
    : "/api/agents/history?agentId=" + active.id + "&limit=80";
  const hist = window.useApiM(histPath, { interval: 12000 });
  const serverThread = (hist.data && hist.data.history) || [];

  // Optimistic bubble only until the server thread includes the turn.
  const thread = serverThread.concat(
    (pending && pending.agentId === active.id) ? [pending] : []);

  // Auto-scroll the feed to the newest bubble.
  useEffectMA(() => {
    if (feedRefMA.current) feedRefMA.current.scrollTop = feedRefMA.current.scrollHeight;
  }, [thread.length, busyId, agentId, busMode, hist.data]);

  async function maSend() {
    const a = active;
    const q = (drafts[a.id] || "").trim();
    if (!q || busyId) return;
    // Last 8 server turns as context (server also falls back to its own store).
    const history = serverThread.slice(-8).map((m) => ({ role: m.role, text: m.text }));
    setPending({ agentId: a.id, role: "user", text: q, ts: Date.now(), optimistic: true });
    setDrafts((d) => Object.assign({}, d, { [a.id]: "" }));
    setBusyId(a.id);
    setSendErr(null);
    try {
      const body = a.crew === "agency"
        ? { agentId: a.id, message: q, history }
        : { agentId: a.id, message: q, history };
      await window.apiPostM(a.ep, body);
      hist.refresh();               // server recorded both turns — pull them in
    } catch (e) {
      setSendErr("Couldn't reach " + a.name + " (" + ((e && e.message) || "connection error") + "). Try again.");
    }
    setPending(null);
    setBusyId(null);
  }

  // Bubble list with Telegram date chips + role-change spacing.
  const rows = [];
  let lastDay = "", lastOut = null;
  thread.forEach((m, i) => {
    const out = m.role === "user";
    const day = m.ts ? new Date(m.ts).toDateString() : lastDay;
    if (m.ts && day !== lastDay) {
      rows.push(<div key={"d" + i} className="m-tg-date">{MADateLabel(m.ts)}</div>);
      lastDay = day; lastOut = null;
    }
    rows.push(
      <div key={i} className={"m-tg-bubble " + (out ? "out" : "in")}
        style={{ marginTop: lastOut === null || lastOut === out ? 2 : 9,
          opacity: m.optimistic ? 0.65 : 1 }}>
        {m.text}
        <span className="m-tg-meta">
          {m.via === "telegram" && <window.MIcons.Send size={9} />}
          {MATime(m.ts)}
          {out && !m.optimistic && <window.MIcons.Check size={11} />}
        </span>
      </div>
    );
    lastOut = out;
  });

  return (
    <React.Fragment>
      <window.MHeader title="Agents" sub="Your AI employees — synced with Telegram" />
      <div className="m-content" style={{ gap: 10 }}>

        {/* Agent picker + Bus toggle */}
        <div className="m-seg">
          {agents.map((a) => (
            <button key={a.id}
              className={"m-chip" + (!busMode && agentId === a.id ? " active" : "")}
              style={{ minHeight: 44 }}
              onClick={() => { setBusMode(false); setAgentId(a.id); }}>
              {a.name}{busyId === a.id ? " …" : ""}
            </button>
          ))}
          <button className={"m-chip" + (busMode ? " active" : "")}
            style={{ minHeight: 44 }}
            onClick={() => setBusMode(true)}>
            Bus
          </button>
        </div>

        {busMode ? (
          <MABusCard />
        ) : (
          <React.Fragment>
            {/* Telegram-style chat header */}
            <div className="m-row" style={{ gap: 10, padding: "2px 2px 0" }}>
              <MAAvatar agent={active} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 800 }}>{active.name}</div>
                <div className="m-fade" style={{ fontSize: 11.5, overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {thinking ? "typing…" : "online · " + active.role}
                </div>
              </div>
              <button className="m-tab" style={{ flex: "none", minWidth: 44, minHeight: 44, padding: 4 }}
                onClick={hist.refresh}>
                <window.MIcons.Refresh size={18} />
              </button>
            </div>

            {/* Thread */}
            <div ref={feedRefMA} className="m-tg-feed">
              {hist.loading && !hist.data && <window.MSpin />}
              {hist.error && !serverThread.length && (
                <div className="m-fade" style={{ textAlign: "center", padding: 10 }}>
                  Couldn't load the thread: {String(hist.error)}
                </div>
              )}
              {!hist.loading && !thread.length && !thinking && (
                <div style={{ margin: "auto 0" }}>
                  <window.MEmpty title={"Chat with " + active.name}
                    sub={active.role + " — messages sync with the Telegram bot"} />
                </div>
              )}
              {rows}
              {thinking && (
                <div className="m-tg-bubble in" style={{ marginTop: 9, fontStyle: "italic",
                  color: "var(--text-2, #9FB0C7)" }}>
                  {active.name} is typing…
                </div>
              )}
              {sendErr && (
                <div style={{ alignSelf: "center", marginTop: 8, fontSize: 12,
                  color: "var(--red, #EF4444)" }}>{sendErr}</div>
              )}
            </div>

            {/* Composer — Telegram pill + round send */}
            <div className="m-tg-compose">
              <textarea className="m-input m-tg-input" rows={1} value={draft}
                placeholder={"Message " + active.name + "…"}
                style={{ minHeight: 46, maxHeight: 110, resize: "none" }}
                onChange={(e) => {
                  const v = e.target.value;
                  setDrafts((d) => Object.assign({}, d, { [active.id]: v }));
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); maSend(); }
                }} />
              <button className="m-btn m-tg-sendbtn" onClick={maSend}
                disabled={thinking || !draft.trim()}>
                <window.MIcons.Send size={19} />
              </button>
            </div>
          </React.Fragment>
        )}
      </div>
    </React.Fragment>
  );
}

Object.assign(window, { MAgentsPage });
