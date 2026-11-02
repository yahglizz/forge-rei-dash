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
//   POST /api/hub/chat              (daycare, Orion in Everything) · /api/office/chat (Orion inside a portal)
//   GET  /api/bus?limit=30           → comms bus feed
//   GET  /api/chat/cards[?business=] → still-open tap cards (survive a reload); tap = ChatActions
//   GET  /api/mac/status             → Mac online / last seen (refreshed with each registry poll)
// Tasks view: m_tasks.jsx. Chat turns abort after 330 s; "still working" at 20 s; Cancel any time.
const { useState: useStateMA, useEffect: useEffectMA, useRef: useRefMA } = React;

// Static roster for when the registry call fails: the same main agents as agents_hub.AGENTS (no lanes,
// no archived Midas). Checked by test_mobile_workshop.py. Lane ids (Scout/Atlas/Eco) still chat server-side
// as their main agent.
const MA_AGENTS = [
  { id: "marcus", name: "Marcus", color: "#4F7CFF", business: "wholesale",
    role: "Wholesale lead · triage, screening, underwriting, follow-up" },
  { id: "dyson", name: "Dyson", color: "#8B5CF6", business: "agency",
    role: "Agency lead · client sites + ads" },
  { id: "solomon", name: "Solomon", color: "#2DD4BF", business: "daycare",
    role: "Daycare growth director · enrollment" },
  { id: "orion", name: "Orion", color: "#EC4899", business: "cross",
    role: "CEO · oversees all the businesses" },
];
const MA_KNOWN_BIZ = ["wholesale", "agency", "daycare", "dropship", "cross"];
const MA_TIMEOUT_MS = 330000;   // chat turns can run 315 s on the gateway
const MA_SLOW_S = 20;           // after this long, say it is still working
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

// Registry business → mobile business id ("rei" kept for older registries).
// Orion is "cross": he shows in every business's crew, not only in "Everything".
function MABizOf(a, fixed) {
  const b = a.business || fixed.business || "";
  return b === "rei" ? "wholesale" : b;
}

// Where a message to this agent goes. null = unknown business: the agent is not offered at all,
// so nothing is ever sent to the wrong business's chat route by default.
// Orion inside a portal goes through the office chat, which scopes him to that business's floor;
// the hub chat would refuse him there (he is not that workspace's agent).
function MAChatTarget(id, biz, portal) {
  if (biz === "agency") return { ep: "/api/agency/agents/chat", business: portal };
  if (id === "marcus" && biz === "wholesale") return { ep: "/api/agents/chat", business: portal };
  if (biz === "cross") return portal ? { ep: "/api/office/chat", business: portal } : { ep: "/api/hub/chat" };
  if (MA_KNOWN_BIZ.includes(biz)) return { ep: "/api/hub/chat", business: portal };
  return null;
}

// One compact line per agent: working / idle / waiting on you, plus open task and approval counts.
// Registry fields only (status, openTasks, pendingApprovals) plus the open tap cards for that agent.
function MAState(a, cards) {
  const st = String(a.status || "").toUpperCase();
  const approvals = (Number(a.pendingApprovals) || 0) + cards;
  const tasks = Number(a.openTasks) || 0;
  let label = "";
  if (st === "RUNNING") label = "Working";
  else if (approvals > 0 || st === "WAITING FOR APPROVAL") label = "Waiting on you";
  else if (st === "IDLE") label = "Idle";
  else if (st) label = st.charAt(0) + st.slice(1).toLowerCase();
  const parts = [];
  if (label) parts.push(label);
  if (tasks) parts.push(tasks + (tasks === 1 ? " open task" : " open tasks"));
  if (approvals) parts.push(approvals + " to approve");
  return { label, text: parts.join(" · ") };
}

function MAgentsPage(props) {
  const business = props && props.business; // optional: "wholesale" | "agency" | "daycare"
  const [agentId, setAgentId] = useStateMA("marcus");
  const [view, setView] = useStateMA("chat");     // "chat" | "tasks" | "bus"
  const [drafts, setDrafts] = useStateMA({});     // agentId -> draft text
  const [busyId, setBusyId] = useStateMA(null);   // agentId currently "thinking"
  const [waited, setWaited] = useStateMA(0);      // seconds the current turn has been running
  const [pending, setPending] = useStateMA(null); // optimistic {agentId, text, ts}
  const [sendErr, setSendErr] = useStateMA(null); // {agentId, text, msg} — text = what to retry
  const [local, setLocal] = useStateMA(null);     // {agentId, text} a reply the server does not store (offline / refused)
  const [acts, setActs] = useStateMA(null);       // {agentId, done, consults} from the latest reply
  const feedRefMA = useRefMA(null);
  const ctlRefMA = useRefMA(null);                // AbortController of the running turn
  const seenRefMA = useRefMA({});                 // tok -> card: a tapped card keeps its result on screen until expiry
  const lastRegRefMA = useRefMA(null);
  const rosterM = window.useApiM("/api/agents/registry", { interval: 30000 });
  const cardsM = window.useApiM("/api/chat/cards" + (business ? "?business=" + encodeURIComponent(business) : ""));
  const macM = window.useApiM("/api/mac/status");
  const hasRegistry = !!(rosterM.data && Array.isArray(rosterM.data.agents));
  const registered = hasRegistry ? rosterM.data.agents.filter((a) => a && a.id && !a.archived) : [];
  const inBiz = (a) => {
    if (!business) return true;
    const b = MABizOf(a, MA_AGENTS.find((f) => f.id === a.id) || {});
    return b === business || b === "cross";   // each workspace: its own agent + Orion
  };
  const agents = (hasRegistry ? registered : MA_AGENTS).filter(inBiz).map((a) => {
    const fixed = MA_AGENTS.find((f) => f.id === a.id) || {};
    const biz = MABizOf(a, fixed);
    const tgt = MAChatTarget(a.id, biz, business);
    return Object.assign({}, fixed, a, {
      business: biz,
      name: a.name || fixed.name || "Agent",
      role: a.role || a.purpose || fixed.role || "FORGE agent",
      crew: biz === "agency" ? "agency" : "rei",
      ep: tgt && tgt.ep,
      sendBiz: tgt && tgt.business,
    });
  }).filter((a) => a.ep).map((a, i) => Object.assign(a, {
    color: a.color || MA_DYNAMIC_COLORS[i % MA_DYNAMIC_COLORS.length],
  }));

  // Filtered + registry down: the fallback list may have nobody for this business.
  const noAgents = !agents.length && (hasRegistry || (!!business && !rosterM.loading));
  const active = agents.find((a) => a.id === agentId) || agents[0] || { id: "none", name: "No active agent", color: "#64748B", crew: "rei", ep: "", role: "Archived agents are hidden on mobile" };
  const draft = drafts[active.id] || "";
  const thinking = busyId === active.id;

  // Open tap cards. The server list is the truth after a reload; cards already on screen stay (with their
  // result) until they expire, so a tap does not make its own card vanish on the next refresh.
  const nowS = Date.now() / 1000;
  ((cardsM.data && cardsM.data.cards) || []).forEach((c) => { if (c && c.tok) seenRefMA.current[c.tok] = c; });
  Object.keys(seenRefMA.current).forEach((k) => { if (!(seenRefMA.current[k].expiresAt > nowS)) delete seenRefMA.current[k]; });
  const ids = agents.map((a) => a.id);
  const cardOwner = (c) => (ids.includes(c.agent) ? c.agent : ids[0]);   // never an invisible card
  const allCards = Object.keys(seenRefMA.current).map((k) => seenRefMA.current[k]);
  const cardsOf = (id) => allCards.filter((c) => cardOwner(c) === id);
  const myCards = cardsOf(active.id);

  // Mac state refreshes on the registry's own poll, so no extra timer.
  const regStamp = rosterM.data && rosterM.data.generatedAt;
  useEffectMA(() => {
    if (regStamp && lastRegRefMA.current && lastRegRefMA.current !== regStamp) macM.refresh();
    lastRegRefMA.current = regStamp || lastRegRefMA.current;
  }, [regStamp]);

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

  // Seconds counter while a turn runs (drives the "still working" line).
  useEffectMA(() => {
    if (!busyId) return undefined;
    setWaited(0);
    const t0 = Date.now();
    const iv = setInterval(() => setWaited(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(iv);
  }, [busyId]);
  useEffectMA(() => () => { if (ctlRefMA.current) ctlRefMA.current.abort(); }, []);

  // Auto-scroll the feed to the newest bubble.
  useEffectMA(() => {
    if (feedRefMA.current) feedRefMA.current.scrollTop = feedRefMA.current.scrollHeight;
  }, [thread.length, busyId, agentId, view, hist.data, waited >= MA_SLOW_S, myCards.length, sendErr]);

  async function maSend(retryText) {
    const a = active;
    const q = (typeof retryText === "string" ? retryText : (drafts[a.id] || "")).trim();
    if (!q || busyId || !a.ep) return;
    // Last 8 server turns as context (server also falls back to its own store).
    const history = serverThread.slice(-8).map((m) => ({ role: m.role, text: m.text }));
    const ctl = new AbortController();
    ctlRefMA.current = ctl;
    setPending({ agentId: a.id, role: "user", text: q, ts: Date.now(), optimistic: true });
    setDrafts((d) => Object.assign({}, d, { [a.id]: "" }));
    setBusyId(a.id);
    setSendErr(null);
    setLocal(null);
    setActs(null);
    try {
      // business = the portal we're in; the hub refuses an agent outside its home workspace.
      // Hub chat replays the server's own thread: the Mac gate needs its clean flags, which this copy
      // lacks. The agency's old path has no store to fall back on, so it still takes this context.
      const body = { agentId: a.id, message: q };
      if (a.ep !== "/api/hub/chat") body.history = history;
      if (a.sendBiz) body.business = a.sendBiz;
      const d = await window.apiPostM(a.ep, body, { timeoutMs: MA_TIMEOUT_MS, signal: ctl.signal });
      // The reply's own cards show at once; the server queue (cardsM) confirms them and keeps them across a reload.
      (d && d.actions || []).forEach((c) => { if (c && c.tok) seenRefMA.current[c.tok] = Object.assign({ expiresAt: Date.now() / 1000 + 1800 }, c); });
      if (d && (d.done || d.consults)) setActs({ agentId: a.id, done: d.done, consults: d.consults });
      if (d && d.reply && (d.offline || d.refused)) setLocal({ agentId: a.id, text: d.reply });   // the server does not store these
      cardsM.refresh();             // new tap cards are in the server queue now
      hist.refresh();               // server recorded both turns — pull them in
    } catch (e) {
      // The server writes history only on a real reply, so on any error there is nothing to refresh
      // into view — put the message back in the box (unless something new was typed) and keep it for Retry.
      setDrafts((d) => (d[a.id] ? d : Object.assign({}, d, { [a.id]: q })));
      const code = e && e.code;
      setSendErr({ agentId: a.id, text: q, msg: code === "cancelled"
        ? "Cancelled. " + a.name + " may still finish, so check the thread before you send it again."
        : code === "timeout"
          ? a.name + " didn't answer in 5 minutes. A late reply still lands in the thread."
          : "Couldn't reach " + a.name + " (" + ((e && e.message) || "connection error") + ")." });
    }
    ctlRefMA.current = null;
    setPending(null);
    setBusyId(null);
  }

  function maCancel() { if (ctlRefMA.current) ctlRefMA.current.abort(); }

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

  if (noAgents) return <React.Fragment><window.MHeader title="Agents" sub="Live agent roster" /><div className="m-content"><window.MEmpty title="No active agents" sub="Archived agents are hidden from mobile." /></div></React.Fragment>;

  const mac = macM.data;
  const macLine = !mac ? (macM.error ? "Mac status unavailable" : "")
    : !mac.enabled ? "Mac link is off"
    : mac.online ? "Mac online" + (mac.busy ? ", running a command" : "")
    : "Mac offline, last seen " + (mac.lastSeen || "Unknown");
  const st = MAState(active, myCards.length);
  return (
    <React.Fragment>
      <window.MHeader title="Agents" sub="Your AI employees — synced with Telegram" />
      <div className="m-content" style={{ gap: 10 }}>

        {macLine && (
          <div className="m-row" style={{ gap: 7, fontSize: 12, padding: "0 2px" }}>
            <span style={{ width: 9, height: 9, borderRadius: "50%", flex: "none",
              background: mac && mac.enabled && mac.online ? "#22C55E" : "#94A3B8" }} />
            <span className="m-fade">{macLine}</span>
          </div>
        )}
        {rosterM.error && <div className="mw-warn">Agent registry unavailable — showing the saved chat list.</div>}
        {hasRegistry && !agents.length && <window.MEmpty title="No active agents" sub="Archived agents are hidden from mobile." />}
        {hasRegistry && rosterM.data.ai && rosterM.data.ai.ok === false && <div className="mw-warn">AI connection needs attention{rosterM.data.ai.reason ? " — " + rosterM.data.ai.reason : ""}.</div>}

        {/* Agent picker + Tasks + Bus toggles */}
        <div className="m-seg">
          {agents.map((a) => {
            const s = MAState(a, cardsOf(a.id).length);
            return (
              <button key={a.id}
                className={"m-chip" + (view === "chat" && agentId === a.id ? " active" : "")}
                style={{ minHeight: 44 }}
                onClick={() => { setView("chat"); setAgentId(a.id); }}>
                {a.name}{s.label ? " · " + s.label.toLowerCase() : ""}{busyId === a.id ? " …" : ""}
              </button>
            );
          })}
          <button className={"m-chip" + (view === "tasks" ? " active" : "")}
            style={{ minHeight: 44 }}
            onClick={() => setView("tasks")}>
            Tasks
          </button>
          <button className={"m-chip" + (view === "bus" ? " active" : "")}
            style={{ minHeight: 44 }}
            onClick={() => setView("bus")}>
            Bus
          </button>
        </div>

        {view === "bus" ? (
          <MABusCard />
        ) : view === "tasks" ? (
          window.MATasksCard
            ? <window.MATasksCard agents={agents} business={business} />
            : <window.MEmpty title="Tasks unavailable" />
        ) : (
          <React.Fragment>
            {/* Telegram-style chat header */}
            <div className="m-row" style={{ gap: 10, padding: "2px 2px 0" }}>
              <MAAvatar agent={active} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 800 }}>{active.name}</div>
                <div className="m-fade" style={{ fontSize: 11.5, overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {thinking ? "working…" : active.role}
                </div>
                {st.text && <div className="m-fade" style={{ fontSize: 11.5 }}>{st.text}</div>}
              </div>
              <button className="m-tab" style={{ flex: "none", minWidth: 44, minHeight: 44, padding: 4 }}
                aria-label="Refresh" onClick={() => { hist.refresh(); cardsM.refresh(); }}>
                <window.MIcons.Refresh size={18} />
              </button>
            </div>

            {/* Thread */}
            <div ref={feedRefMA} className="m-tg-feed m-cards">
              {hist.loading && !hist.data && <window.MSpin />}
              {hist.error && !serverThread.length && (
                <div className="m-fade" style={{ textAlign: "center", padding: 10 }}>
                  Couldn't load the thread: {String(hist.error)}
                </div>
              )}
              {!hist.loading && !thread.length && !thinking && !myCards.length && (
                <div style={{ margin: "auto 0" }}>
                  <window.MEmpty title={"Chat with " + active.name}
                    sub={active.role + " — messages sync with the Telegram bot"} />
                </div>
              )}
              {rows}
              {local && local.agentId === active.id && (
                <div className="m-tg-bubble in" style={{ marginTop: 9 }}>{local.text}</div>
              )}
              {window.ChatActions && (myCards.length > 0 || (acts && acts.agentId === active.id)) && (
                <div style={{ alignSelf: "stretch", marginTop: 6 }}>
                  <window.ChatActions actions={myCards} done={acts && acts.agentId === active.id ? acts.done : null}
                    consults={acts && acts.agentId === active.id ? acts.consults : null} />
                </div>
              )}
              {thinking && (
                <div className="m-tg-bubble in" style={{ marginTop: 9, color: "var(--text-2, #9FB0C7)" }}>
                  <span style={{ fontStyle: "italic" }}>
                    {waited >= MA_SLOW_S
                      ? active.name + " is still working (" + waited + "s). Long answers can take a few minutes."
                      : active.name + " is working…"}
                  </span>
                  <div style={{ marginTop: 8 }}>
                    <button type="button" className="m-btn ghost" style={{ minHeight: 44, padding: "0 16px" }}
                      onClick={maCancel}>Cancel</button>
                  </div>
                </div>
              )}
              {sendErr && sendErr.agentId === active.id && !thinking && (
                <div role="alert" style={{ alignSelf: "stretch", marginTop: 8, fontSize: 12.5,
                  color: "var(--red, #EF4444)", textAlign: "center" }}>
                  <div>{sendErr.msg}</div>
                  <button type="button" className="m-btn ghost" style={{ minHeight: 44, padding: "0 20px", marginTop: 6 }}
                    onClick={() => maSend(sendErr.text)}>Retry</button>
                </div>
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
              <button className="m-btn m-tg-sendbtn" onClick={() => maSend()} aria-label="Send"
                disabled={!!busyId || !draft.trim()}>
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
