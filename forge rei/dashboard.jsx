// dashboard.jsx
const { useState: useStateD, useEffect: useEffectD, useRef: useRefD } = React;

function MarcusChat() {
  const Icons = window.Icons;
  const [msgs, setMsgs] = useStateD([]);
  const [val, setVal] = useStateD("");
  const [typing, setTyping] = useStateD(false);
  const feedRef = useRefD(null);

  useEffectD(() => { if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight; }, [msgs, typing]);

  const now = () => new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  async function send() {
    const q = val.trim();
    if (!q || typing) return;
    setMsgs((m) => [...m, { role: "user", text: q, time: now() }]);
    setVal("");
    setTyping(true);
    let reply;
    try {
      // Routes through the connector: Marcus searches the real GHL SMS threads,
      // then answers via Claude (key lives server-side in ghl.env).
      const res = await fetch("/api/marcus/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: q }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.error || ("HTTP " + res.status));
      reply = j.reply;
    } catch (e) {
      reply = "Couldn't reach my brain just now (" + (e.message || "connection error") + "). Make sure the connector is running.";
    }
    setTyping(false);
    setMsgs((m) => [...m, { role: "ai", text: (reply || "").trim() || "On it.", time: now() }]);
  }

  return (
    <div className="chat-wrap" style={{ height: "100%" }}>
      <div style={{ padding: "12px 14px 0", fontSize: 13, fontWeight: 600 }} className="muted">Chat with Marcus</div>
      <div className="chat-feed" ref={feedRef}>
        {msgs.length === 0 && !typing && (
          <div className="faint" style={{ fontSize: 12.5, padding: "8px 2px", lineHeight: 1.5 }}>
            Say hi to Marcus. He'll help you work your leads once they start coming in.
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={"bubble " + m.role}>
            {m.text}
            <div className="bubble-time">{m.time}</div>
          </div>
        ))}
        {typing && (
          <div className="bubble ai"><span className="typing"><span></span><span></span><span></span></span></div>
        )}
      </div>
      <div className="chat-input">
        <input value={val} onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Ask Marcus anything..." />
        <button className="send-btn" onClick={send} disabled={typing || !val.trim()}><Icons.Send size={17} /></button>
      </div>
    </div>
  );
}

function MarcusPanel() {
  const Icons = window.Icons;
  const { data: status } = window.useApi("/api/marcus/status", { interval: 10000 });
  const s = status || {};
  const c = s.counts || {};
  const live = s.enabled;
  const stats = [
    { ico: "Conversations", label: "Pending", val: s.pending || 0 },
    { ico: "Send", label: "Sent", val: c.sent || 0 },
    { ico: "Check", label: "Suppressed", val: c.suppressed || 0 },
    { ico: "Spark", label: "Proposed", val: c.proposed || 0 },
  ];
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <div className="card-title" style={{ fontSize: 20 }}>Marcus AI</div>
          <div className="faint" style={{ fontSize: 13, marginTop: 2 }}>AI Acquisitions Manager · {s.draftMode || "—"} drafts</div>
        </div>
        <span className="pill" style={{ background: live ? "rgba(34,197,94,0.12)" : "rgba(100,116,139,0.15)", color: live ? "var(--green)" : "var(--text-3)", border: "1px solid " + (live ? "rgba(34,197,94,0.3)" : "var(--border)") }}>
          <span className={"dot " + (live ? "online pulse" : "")} /> {live ? "ON DUTY" : "PAUSED"}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "172px minmax(0,1fr) 286px", gap: 16, height: 358, alignItems: "stretch" }}>
        {/* Orb */}
        <div className="marcus-orb" style={{ aspectRatio: "auto", height: "100%" }}>
          <div className="orb-ring" style={{ width: 152, height: 152, animation: "spin 18s linear infinite" }} />
          <div className="orb-ring" style={{ width: 110, height: 110, borderStyle: "dashed", animation: "spin 12s linear infinite reverse" }} />
          <div className="orb-core" />
          <div style={{ position: "absolute", bottom: 12, display: "flex", alignItems: "center", gap: 6, fontSize: 11, letterSpacing: 1, color: "var(--blue-soft)", fontWeight: 600 }}>
            <Icons.Spark size={12} /> FORGE
          </div>
        </div>

        {/* Center: task + stats + NBA */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0, overflow: "hidden" }}>
          <div>
            <div className="faint" style={{ fontSize: 12 }}>Current Task</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginTop: 4, lineHeight: 1.35 }}>{s.task || "Idle — watching GoHighLevel"}</div>
            <div className="faint" style={{ fontSize: 11, marginTop: 3 }}>last check {window.timeAgo(s.lastPoll)}</div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9 }}>
            {stats.map((st) => {
              const Ico = Icons[st.ico];
              return (
                <div key={st.label} className="stat-cell">
                  <span className="faint"><Ico size={15} /></span>
                  <div className="stat-num tabnum">{st.val}</div>
                  <div className="faint" style={{ fontSize: 9.5, marginTop: 1, lineHeight: 1.2 }}>{st.label}</div>
                </div>
              );
            })}
          </div>
          <button className="nba" style={{ marginTop: "auto" }} onClick={() => window.GoTo && window.GoTo("Command")}>
            <div>
              <div className="faint" style={{ fontSize: 11 }}>Next Best Action</div>
              <div style={{ fontSize: 13.5, fontWeight: 500, marginTop: 3 }}>
                {s.pending ? `Review ${s.pending} ${s.pending > 1 ? "replies" : "reply"} waiting` : "Open Marcus command center"}
              </div>
            </div>
            <span style={{ color: "var(--blue-soft)" }}><Icons.ChevronR size={18} /></span>
          </button>
        </div>

        {/* Right: chat — minHeight:0 lets the feed scroll inside the fixed-height row
            instead of stretching the row taller than 358px. */}
        <div style={{ minWidth: 0, minHeight: 0, height: "100%" }}><MarcusChat /></div>
      </div>
    </div>
  );
}

function HotLeads() {
  const Icons = window.Icons;
  const { data, loading } = window.useApi("/api/contacts?limit=6");
  const leads = (data && data.contacts) || [];
  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "var(--orange)" }}><Icons.Flame size={18} /></span>
          <span className="card-title">Latest Leads</span>
        </div>
        <button className="link" onClick={() => window.GoTo && window.GoTo("Leads")}>View all</button>
      </div>
      {loading && <window.LoadingRow />}
      {!loading && leads.length === 0 && (
        <div className="empty" style={{ padding: "26px 8px" }}>
          <div className="empty-ico"><Icons.Flame size={22} /></div>
          <div style={{ fontSize: 12.5 }}>No leads yet</div>
        </div>
      )}
      {leads.map((l) => (
        <div className="row-item" key={l.id}>
          <div style={{ width: 34, height: 34, borderRadius: 10, background: "var(--card-2)", border: "1px solid var(--border)", display: "grid", placeItems: "center", flexShrink: 0 }} className="faint">
            <Icons.Leads size={15} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.name}</div>
            <div className="faint mono" style={{ fontSize: 11.5 }}>{l.phone || l.addr || "—"}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="faint" style={{ fontSize: 9.5 }}>{window.timeAgo(l.dateAdded)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TodaysTasks() {
  const Icons = window.Icons;
  const { data, loading } = window.useApi("/api/tasks?scan=100");
  const today = new Date().toISOString().slice(0, 10);
  const all = (data && data.tasks) || [];
  const due = all.filter((t) => !t.completed && (t.dueDate || "").startsWith(today));
  const upcoming = all.filter((t) => !t.completed).slice(0, 6);
  const show = due.length ? due.slice(0, 6) : upcoming;
  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "var(--blue-soft)" }}><Icons.Clipboard size={17} /></span>
          <span className="card-title">{due.length ? "Due Today" : "Open Tasks"}</span>
        </div>
        <button className="link" onClick={() => window.GoTo && window.GoTo("Tasks")}>View all</button>
      </div>
      {loading && <window.LoadingRow />}
      {!loading && show.length === 0 && (
        <div className="empty" style={{ padding: "26px 8px" }}>
          <div className="empty-ico"><Icons.Clipboard size={22} /></div>
          <div style={{ fontSize: 12.5 }}>No open tasks</div>
        </div>
      )}
      {show.map((t) => (
        <div className="task" key={t.id}>
          <div className="checkbox" />
          <span className="task-label" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title}</span>
          <span className="task-count">{t.dueDate ? t.dueDate.slice(5, 10) : "—"}</span>
        </div>
      ))}
    </div>
  );
}

function NextActionCard() {
  const Icons = window.Icons;
  return (
    <div className="next-action">
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{ color: "var(--violet)" }}><Icons.Spark size={16} /></span>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Next Action</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>Nothing queued</div>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 5, lineHeight: 1.5 }}>Add your first leads and Marcus will surface your next best move here.</div>
        </div>
        <button className="call-btn" disabled style={{ opacity: 0.45 }}><Icons.Phone size={20} /></button>
      </div>
    </div>
  );
}

const STAGE_ACCENTS = ["#4F7CFF", "#8B5CF6", "#2DD4BF", "#22C55E", "#F59E0B", "#EC4899", "#64748B", "#EF4444"];

function PipelineOverview() {
  const Icons = window.Icons;
  const { data, loading } = window.useApi("/api/pipeline", { interval: 60000 });
  const pls = (data && data.pipelines) || [];
  const [idx, setIdx] = useStateD(0);
  const active = pls[idx];
  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <span className="card-title" style={{ fontSize: 17 }}>Pipeline Overview</span>
        <div className="tabs">
          {pls.map((p, i) => (
            <button key={p.id} className={"tab" + (i === idx ? " active" : "")} onClick={() => setIdx(i)}>
              {p.name} · {window.fmtMoney(p.totalValue)}
            </button>
          ))}
        </div>
      </div>
      {loading && <window.LoadingRow />}
      {active && (
        <div className="kanban">
          {active.stages.map((s, i) => (
            <div className="kcol" key={s.id} style={{ "--col-accent": STAGE_ACCENTS[i % STAGE_ACCENTS.length] }}>
              <div className="kcol-head">
                <span className="kcol-title">{s.name}</span>
                <span className="kcol-count tabnum">{s.count}</span>
              </div>
              {s.count === 0 && <div className="kempty">—</div>}
              {s.cards.slice(0, 8).map((card) => (
                <div className="kcard" key={card.id} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <div style={{ fontWeight: 600, fontSize: 13, lineHeight: 1.25, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{card.name}</div>
                    {card.value > 0 && <span className="tabnum" style={{ fontSize: 12, fontWeight: 700, color: "var(--green)", flexShrink: 0 }}>{window.fmtMoney(card.value)}</span>}
                  </div>
                  {card.phone && <div className="faint mono" style={{ fontSize: 11 }}>{card.phone}</div>}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ConversationsWidget() {
  const Icons = window.Icons;
  const { data, loading } = window.useApi("/api/conversations?limit=8", { interval: 15000 });
  const convos = (data && data.conversations) || [];
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 13 }}>
        <div className="card-title">Conversations</div>
        <button className="link" onClick={() => window.GoTo && window.GoTo("Conversations")}>View all</button>
      </div>
      {loading && <window.LoadingRow />}
      {!loading && convos.length === 0 && (
        <div className="empty" style={{ flex: 1 }}>
          <div className="empty-ico"><Icons.Message size={26} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)" }}>No conversations yet</div>
        </div>
      )}
      {convos.map((c) => (
        <div className="row-item" key={c.id}>
          <div style={{ width: 32, height: 32, borderRadius: 9, background: "var(--card-2)", border: "1px solid var(--border)", display: "grid", placeItems: "center", flexShrink: 0 }} className="faint">
            <Icons.Message size={14} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</span>
              <span className="faint" style={{ fontSize: 10.5, flexShrink: 0 }}>{window.timeAgo(c.lastMessageDate)}</span>
            </div>
            <div className="faint" style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.lastMessage || "—"}</div>
          </div>
          {c.unread > 0 && <span className="pill" style={{ background: "var(--blue)", color: "#fff", flexShrink: 0 }}>{c.unread}</span>}
        </div>
      ))}
    </div>
  );
}

function AIWorkforce() {
  const Icons = window.Icons;
  return (
    <div className="card card-pad">
      <div className="card-title" style={{ marginBottom: 16 }}>AI Workforce</div>
      <div className="workforce-grid">
        {window.WORKFORCE.map((a) => {
          const live = a.status === "online";
          return (
            <div key={a.name} className={"agent-card" + (live ? " active" : "")}>
              <div className={"agent-av " + (live ? "live" : "soon")}><Icons.Bot size={24} /></div>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>{a.name}</div>
              <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>{a.role}</div>
              {live ? (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 5, margin: "8px 0" }}>
                  <span className="dot online pulse" /><span style={{ fontSize: 10, color: "var(--green)", fontWeight: 600 }}>ONLINE</span>
                </div>
              ) : <div className="coming-soon">COMING SOON</div>}
              {live && (
                <div style={{ marginTop: 10, fontSize: 9.5, color: "var(--text-3)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", whiteSpace: "nowrap" }}><span>Tasks Today</span><span className="muted tabnum">0</span></div>
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", whiteSpace: "nowrap" }}><span>Leads Managed</span><span className="muted tabnum">0</span></div>
                  <div style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", whiteSpace: "nowrap" }}><span>Messages Sent</span><span className="muted tabnum">0</span></div>
                  <div style={{ marginTop: 8, fontSize: 10 }} className="faint">Performance <span style={{ float: "right", color: "var(--green)" }}>100%</span></div>
                  <div className="progress" style={{ marginTop: 4 }}><div style={{ width: "100%" }} /></div>
                </div>
              )}
              {!live && <div style={{ marginTop: 10, fontSize: 10 }} className="faint">Performance <span style={{ float: "right" }}>--</span></div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ActivityFeed() {
  const Icons = window.Icons;
  const { data } = window.useApi("/api/marcus/proposals", { interval: 10000 });
  const activity = (data && data.activity) || [];
  const colorFor = (k) => ({ propose: "#4F7CFF", sent: "#22C55E", suppress: "#64748B", dismiss: "#F59E0B", config: "#8B5CF6" }[k] || "#4F7CFF");
  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span className="card-title">Activity Feed</span>
        <button className="link" onClick={() => window.GoTo && window.GoTo("Command")}>View all</button>
      </div>
      {activity.length === 0 && (
        <div className="empty" style={{ padding: "26px 8px" }}>
          <div className="empty-ico"><Icons.Spark size={22} /></div>
          <div style={{ fontSize: 12.5 }}>No activity yet</div>
        </div>
      )}
      {activity.slice(0, 8).map((a, i) => {
        const c = colorFor(a.kind);
        return (
          <div className="feed-item" key={i}>
            <div className="feed-ico" style={{ background: c + "1f", color: c }}><Icons.Spark size={16} /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.text}</div>
            </div>
            <span className="faint" style={{ fontSize: 11, whiteSpace: "nowrap" }}>{window.timeAgo(a.ts)}</span>
          </div>
        );
      })}
    </div>
  );
}

function KpiCard({ kpi, value, loading }) {
  const Icons = window.Icons;
  const Ico = Icons[kpi.icon];
  return (
    <div className="kpi">
      <div className="kpi-ico" style={{ background: kpi.color + "1f", color: kpi.color }}><Ico size={18} /></div>
      <div className="kpi-label">{kpi.label}</div>
      <div className="kpi-val">
        {loading ? <span className="faint" style={{ fontSize: 20 }}>···</span>
                 : <CountUp to={Number(value || 0)} prefix={kpi.prefix} />}
      </div>
      <div className="kpi-delta">{kpi.sub
        ? <span className="faint">{kpi.sub}</span>
        : <span className="faint">live · GoHighLevel</span>}</div>
    </div>
  );
}

// Scout's "text back now" strip — the first thing you see: hottest sellers to reply
// to, click one to jump straight into the thread. Stop/not-interested are filtered out.
function ScoutWidget() {
  const Icons = window.Icons;
  const sc = (s) => (s >= 80 ? "#22C55E" : s >= 60 ? "#F59E0B" : "#EF4444");
  const { data, refresh } = window.useApi("/api/scout/leads?bucket=asap", { interval: 15000 });
  const sum = window.useApi("/api/scout/summary", { interval: 20000 });
  const leads = (data && data.leads) || [];
  const counts = (sum.data && sum.data.counts) || {};

  const [openId, setOpenId] = useStateD(null);     // which lead's draft panel is expanded
  const [drafts, setDrafts] = useStateD({});        // id -> { text, source, loading, error }
  const [sending, setSending] = useStateD(null);    // id being sent
  const [sentIds, setSentIds] = useStateD({});      // id -> true, hide optimistically

  function setDraft(id, patch) {
    setDrafts((m) => ({ ...m, [id]: { ...(m[id] || {}), ...patch } }));
  }

  // Tap a lead → draft a reply in the operator's voice (Marcus's response skill), on demand.
  async function openDraft(l) {
    if (openId === l.id) { setOpenId(null); return; }
    setOpenId(l.id);
    if (drafts[l.id] && (drafts[l.id].text || drafts[l.id].loading)) return;
    setDraft(l.id, { loading: true, error: null });
    try {
      const r = await window.apiPost("/api/reply/draft", { convId: l.id, contactId: l.contactId, name: l.name });
      if (r && r.error) setDraft(l.id, { loading: false, error: r.error });
      else setDraft(l.id, { loading: false, text: r.draft || "", source: r.source });
    } catch (e) { setDraft(l.id, { loading: false, error: e.message }); }
  }

  // Send the (edited) reply → GHL SMS, records the touch (suppresses re-surfacing until the
  // seller replies again) and checks it off Do Today. Operator's click IS the approval.
  async function sendReply(l) {
    const text = ((drafts[l.id] || {}).text || "").trim();
    if (!text || sending) return;
    setSending(l.id);
    try {
      const r = await window.apiPost("/api/reply/send", {
        contactId: l.contactId, convId: l.id, message: text, name: l.name,
        lastMessageDate: l.lastMessageDate,
      });
      if (r && r.error) { alert("Send failed: " + r.error); return; }
      setSentIds((m) => ({ ...m, [l.id]: true }));    // hide it now
      setOpenId(null);
      if (window.refreshDoToday) window.refreshDoToday();  // instant check-off on the Do Today card
      refresh();
    } catch (e) { alert("Send failed: " + e.message); }
    finally { setSending(null); }
  }

  async function removeLead(e, l) {
    e.stopPropagation();
    if (!window.confirm(`Remove ${l.name} as a hot lead?\n\nTakes the hot tags off the GHL contact and marks their opportunity Lost (reopenable in GHL).`)) return;
    try {
      const r = await window.apiPost("/api/scout/remove", { id: l.id });
      if (r && r.errors && r.errors.length) alert("Removed, with warnings:\n" + r.errors.join("\n"));
      refresh();
    } catch (err) { alert("Remove failed: " + err.message); }
  }

  const shown = leads.filter((l) => !sentIds[l.id]).slice(0, 6);
  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "var(--orange)" }}><Icons.Flame size={18} /></span>
          <span className="card-title">Text Back Now · Speed to Lead</span>
          <span className="pill" style={{ background: "rgba(239,68,68,0.12)", color: "#EF4444" }}>{counts.asap || 0} hot</span>
          <span className="faint" style={{ fontSize: 11 }}>tap a lead → AI drafts the reply → send</span>
        </div>
        <button className="link" onClick={() => window.GoTo && window.GoTo("Conversations")}>Open ASAP</button>
      </div>
      {shown.length === 0
        ? <div className="faint" style={{ fontSize: 12.5, padding: "6px 2px", lineHeight: 1.5 }}>No hot sellers waiting right now. Scout auto-filters stop / not-interested and surfaces motivated replies here the moment they come in.</div>
        : <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {shown.map((l) => {
              const dr = drafts[l.id] || {};
              const isOpen = openId === l.id;
              return (
                <div key={l.id} style={{ border: "1px solid " + (isOpen ? "var(--blue-soft)" : "transparent"), borderRadius: 12, background: isOpen ? "var(--card-2)" : "transparent", transition: "background .15s" }}>
                  <div className="row-item" style={{ cursor: "pointer" }} onClick={() => openDraft(l)}>
                    <div style={{ width: 34, height: 34, borderRadius: 10, background: "var(--card-2)", border: "1px solid var(--border)", display: "grid", placeItems: "center", flexShrink: 0, fontWeight: 800, fontSize: 12.5, color: sc(l.motivation) }}>{l.motivation}</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.name}{l.priceBand ? ` · asks ${l.priceBand}` : ""}</div>
                      <div className="faint" style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.lastMessage || l.reason || "—"}</div>
                    </div>
                    <span className="faint" style={{ fontSize: 10, whiteSpace: "nowrap" }}>{window.timeAgo(l.lastMessageDate)}</span>
                    <button className="tab" onClick={(e) => { e.stopPropagation(); openDraft(l); }}
                      style={{ fontSize: 12, lineHeight: 1, padding: "5px 10px", border: "1px solid var(--blue-soft)", color: "var(--blue-soft)", flexShrink: 0 }}>
                      {isOpen ? "Hide" : "Draft"}
                    </button>
                    <button className="tab" onClick={(e) => removeLead(e, l)} title="Not actually hot — remove tags + mark opportunity Lost"
                      style={{ fontSize: 12, lineHeight: 1, padding: "4px 7px", border: "1px solid rgba(239,68,68,0.35)", color: "#EF4444", flexShrink: 0 }}>✕</button>
                  </div>
                  {isOpen && (
                    <div style={{ padding: "2px 12px 12px 12px" }}>
                      {dr.loading && <div className="faint" style={{ fontSize: 12, padding: "6px 2px" }}>Drafting a reply in your voice…</div>}
                      {dr.error && <div style={{ fontSize: 12, color: "#EF4444", padding: "6px 2px" }}>{dr.error}</div>}
                      {!dr.loading && !dr.error && (
                        <div>
                          <textarea value={dr.text || ""} onChange={(e) => setDraft(l.id, { text: e.target.value })}
                            rows={3} placeholder="Your reply…"
                            style={{ width: "100%", background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text)", fontSize: 13, padding: 9, resize: "vertical", fontFamily: "inherit" }} />
                          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
                            <button className="send-btn" onClick={() => sendReply(l)} disabled={sending === l.id || !((dr.text || "").trim())}
                              style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 14px", fontSize: 13 }}>
                              <Icons.Send size={15} /> {sending === l.id ? "Sending…" : "Send text"}
                            </button>
                            <button className="tab" style={{ fontSize: 12 }} onClick={() => openDraft(l)}>Re-draft</button>
                            <button className="link" style={{ fontSize: 12 }} onClick={() => window.openConversation && window.openConversation(l)}>Open full thread</button>
                            {dr.source && <span className="faint" style={{ fontSize: 10, marginLeft: "auto" }}>{dr.source === "claude" ? "AI draft · edit before sending" : "template"}</span>}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>}
    </div>
  );
}

// DO TODAY — the morning battle plan. Rebuilt + emailed by the box every day at
// 9 AM Eastern (do_today.py); check items off here and the flag sticks all day.
const DO_TODAY_META = {
  reply:     { ico: "Message",   color: "#EF4444" },
  call:      { ico: "Phone",     color: "#22C55E" },
  approve:   { ico: "Send",      color: "#4F7CFF" },
  checkback: { ico: "Calendar",  color: "#F59E0B" },
  ghl:       { ico: "Clipboard", color: "#8B5CF6" },
};

function DoTodayCard() {
  const Icons = window.Icons;
  const { data, loading, refresh } = window.useApi("/api/today", { interval: 30000 });
  const [busy, setBusy] = useStateD(null);
  const [emailing, setEmailing] = useStateD(false);
  // Let Speed-to-Lead check a lead off instantly after a send (no 30s poll wait).
  useEffectD(() => {
    window.refreshDoToday = refresh;
    return () => { if (window.refreshDoToday === refresh) delete window.refreshDoToday; };
  }, [refresh]);
  const d = data || {};
  const tasks = d.tasks || [];
  const ghost = d.ghost || [];
  const done = d.doneCount || 0;
  const total = d.total || 0;
  const pct = total ? Math.round((done * 100) / total) : 0;

  async function toggle(t) {
    if (busy) return;
    setBusy(t.id);
    try { await window.apiPost("/api/today/check", { id: t.id, done: !t.done }); refresh(); }
    catch (e) { alert("Couldn't save: " + e.message); }
    finally { setBusy(null); }
  }

  async function emailNow() {
    if (emailing) return;
    setEmailing(true);
    try {
      const r = await window.apiPost("/api/today/run", { email: true });
      if (r && r.lastError) alert("Rebuilt the list, but the email hit a snag:\n" + r.lastError);
      refresh();
    } catch (e) { alert("Failed: " + e.message); }
    finally { setEmailing(false); }
  }

  function openTask(t) {
    // Conversations page expects { id: convId, contactId, name } (same as Scout's leads).
    if (t.convId && window.openConversation) {
      window.openConversation({ id: t.convId, contactId: t.contactId, name: t.title });
    }
  }

  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={{ color: "var(--green)" }}><Icons.Check size={18} /></span>
          <span className="card-title">Do Today</span>
          <span className="pill" style={{ background: "rgba(34,197,94,0.12)", color: "var(--green)" }}>{done}/{total} done</span>
          <span className="faint" style={{ fontSize: 11 }}>
            rebuilds 9:00 AM ET{d.emailedAt ? " · emailed " + window.timeAgo(d.emailedAt) : ""}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="tab" style={{ fontSize: 12 }} onClick={emailNow} disabled={emailing}>
            {emailing ? "Sending…" : "Rebuild + email now"}
          </button>
          <button className="tab" style={{ fontSize: 12 }} onClick={refresh}>↻</button>
        </div>
      </div>
      {total > 0 && (
        <div className="progress" style={{ marginBottom: 12 }}>
          <div style={{ width: pct + "%" }} />
        </div>
      )}
      {loading && !data && <window.LoadingRow label="Building today's battle plan…" />}
      {!loading && tasks.length === 0 && ghost.length === 0 && (
        <div className="empty" style={{ padding: "22px 8px" }}>
          <div className="empty-ico"><Icons.Check size={22} /></div>
          <div style={{ fontSize: 12.5 }}>Board's clear — no urgent moves waiting on you right now.</div>
        </div>
      )}
      {!loading && tasks.length === 0 && ghost.length > 0 && (
        <div className="faint" style={{ fontSize: 12.5, padding: "6px 2px" }}>
          No urgent moves today — but you've got {ghost.length} to re-engage below.
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(330px, 1fr))", gap: "4px 18px" }}>
        {tasks.map((t) => {
          const meta = DO_TODAY_META[t.kind] || DO_TODAY_META.ghl;
          const Ico = Icons[meta.ico] || Icons.Clipboard;
          return (
            <div className="row-item" key={t.id} style={{ opacity: t.done ? 0.45 : 1, cursor: t.convId ? "pointer" : "default" }}
                 onClick={() => openTask(t)}>
              <div className={"checkbox" + (t.done ? " done" : "")}
                   style={{ cursor: "pointer", color: "#fff" }}
                   onClick={(e) => { e.stopPropagation(); toggle(t); }}>
                {t.done && <Icons.Check size={12} />}
              </div>
              <span style={{ color: meta.color, flexShrink: 0 }}><Ico size={15} /></span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                              textDecoration: t.done ? "line-through" : "none" }}>{t.title}</div>
                {t.detail && <div className="faint" style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.detail}</div>}
              </div>
              <span className="pill" style={{ background: meta.color + "1f", color: meta.color, fontSize: 9.5, flexShrink: 0 }}>{t.label.toUpperCase()}</span>
            </div>
          );
        })}
      </div>
      {ghost.length > 0 && (
        <div style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <span style={{ color: "#F59E0B" }}><Icons.Reply size={15} /></span>
            <span className="card-title" style={{ fontSize: 13.5 }}>Went Ghost — Re-engage</span>
            <span className="pill" style={{ background: "rgba(245,158,11,0.14)", color: "#F59E0B", fontSize: 9.5 }}>
              {ghost.length} showed interest, went quiet
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(330px, 1fr))", gap: "4px 18px", opacity: 0.9 }}>
            {ghost.map((t) => {
              const meta = DO_TODAY_META[t.kind] || DO_TODAY_META.ghl;
              const Ico = Icons[meta.ico] || Icons.Clipboard;
              return (
                <div className="row-item" key={t.id} style={{ opacity: t.done ? 0.45 : 1, cursor: t.convId ? "pointer" : "default" }}
                     onClick={() => openTask(t)}>
                  <div className={"checkbox" + (t.done ? " done" : "")}
                       style={{ cursor: "pointer", color: "#fff" }}
                       onClick={(e) => { e.stopPropagation(); toggle(t); }}>
                    {t.done && <Icons.Check size={12} />}
                  </div>
                  <span style={{ color: "#F59E0B", flexShrink: 0 }}><Ico size={15} /></span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                  textDecoration: t.done ? "line-through" : "none" }}>{t.title}</div>
                    {t.detail && <div className="faint" style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.detail}</div>}
                  </div>
                  <span className="pill" style={{ background: "#F59E0B1f", color: "#F59E0B", fontSize: 9.5, flexShrink: 0 }}>RE-ENGAGE</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function DashHealthDot() {
  // Fleet health at a glance: green = all loops beating, amber = warnings, red = a loop
  // is down. Tap → the full System Health tab. Grey while loops are off/UI-only.
  const { data } = window.useApi("/api/system/health", { interval: 30000 });
  const d = data || {};
  const loops = Array.isArray(d.loops) ? d.loops : [];
  const reds = loops.filter((l) => l.status === "red").length;
  const ambers = loops.filter((l) => l.status === "amber").length;
  const c = !d.active ? "#64748B" : reds ? "#EF4444" : ambers ? "#F59E0B" : "#22C55E";
  const label = !d.active ? "idle" : reds ? reds + " loop down" : ambers ? ambers + " warn" : "healthy";
  return (
    <span onClick={() => window.GoTo && window.GoTo("SystemHealth")}
      title="System health — tap for detail"
      style={{ display: "inline-flex", alignItems: "center", gap: 5, cursor: "pointer" }}>
      <span style={{ width: 9, height: 9, borderRadius: "50%", background: c, display: "inline-block",
                     boxShadow: reds ? "0 0 0 3px rgba(239,68,68,.18)" : "none" }} />
      <span className="faint" style={{ fontSize: 11.5 }}>{label}</span>
    </span>
  );
}

function DashCostChip() {
  // Month-to-date burn, always visible. Tap → the Costs tab.
  const { data } = window.useApi("/api/cost/status", { interval: 60000 });
  const d = data || {};
  const mtd = (d.mtd || {}).totalUSD;
  if (mtd === undefined) return null;
  const c = d.capAlert ? "#EF4444" : d.capWarn ? "#F59E0B" : "var(--text)";
  return (
    <span onClick={() => window.GoTo && window.GoTo("Costs")}
      title="Spend this month — tap for the breakdown"
      className="faint" style={{ fontSize: 11.5, cursor: "pointer" }}>
      💸 <span className="tabnum" style={{ fontWeight: 700, color: c }}>${Number(mtd).toFixed(2)}</span> mtd
    </span>
  );
}

function FDDashboardHero() {
  return <div style={{ minHeight: 178, borderRadius: 16, overflow: "hidden", border: "1px solid rgba(79,124,255,0.25)", backgroundImage: "linear-gradient(90deg, rgba(5,11,24,0.97) 0%, rgba(5,11,24,0.72) 45%, rgba(5,11,24,0.08) 100%), url('assets/dashboard-hero.jpg')", backgroundSize: "cover", backgroundPosition: "center", display: "flex", alignItems: "center", padding: "26px clamp(18px,4vw,42px)" }}><div style={{ maxWidth: 480 }}><div className="pill" style={{ width: "fit-content", color: "#8FB0FF", background: "rgba(79,124,255,0.16)", border: "1px solid rgba(79,124,255,0.34)", fontSize: 10.5 }}>FORGE DEAL DESK</div><div style={{ fontSize: "clamp(22px,3vw,34px)", fontWeight: 750, letterSpacing: "-1px", marginTop: 10 }}>See the deal. Move the next action.</div><div className="faint" style={{ fontSize: 13, marginTop: 7, lineHeight: 1.5 }}>Your live pipeline, buyer workflow, contract review, and AI operator controls in one place.</div><button className="tab active" onClick={() => window.GoTo && window.GoTo("Pipeline")} style={{ marginTop: 14, minHeight: 38 }}>Open Deal Pipeline</button></div></div>;
}

function Dashboard() {
  const Icons = window.Icons;
  const { data, error, loading, refreshedAt, refresh } = window.useApi("/api/dashboard", { interval: 30000 });
  const [showMore, setShowMore] = useStateD(false);
  const d = data || {};
  const kpis = [
    { key: "totalLeads",     label: "Total Leads",        icon: "Leads",         color: "#4F7CFF", prefix: "", value: d.totalLeads },
    { key: "activeConvos",   label: "Active Conversations", icon: "Conversations", color: "#8B5CF6", prefix: "", value: d.activeConversations, sub: (d.totalConversations||0).toLocaleString() + " total" },
    { key: "openOpps",       label: "Open Opportunities", icon: "Pipeline",      color: "#2DD4BF", prefix: "", value: d.openOpportunities },
    { key: "pipelineValue",  label: "Pipeline Value",     icon: "Dollar",        color: "#22C55E", prefix: "$", value: d.pipelineValue },
    { key: "appointments",   label: "Appointments",       icon: "Calendar",      color: "#F59E0B", prefix: "", value: d.appointments },
    { key: "tasksToday",     label: "Tasks Due Today",    icon: "Clipboard",     color: "#EC4899", prefix: "", value: d.tasksDueToday, sub: (d.openTasks||0) + " open tasks" },
  ];
  // Main view = the four things you act on: KPIs, Speed-to-Lead, Do Today, Pipeline.
  // Everything else (Marcus panel, conversations, workforce, activity) is preserved but
  // tucked into a collapsible "More" so the dashboard leads with what matters.
  const MoreChevron = showMore ? Icons.Chevron : Icons.ChevronR;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div className="faint" style={{ fontSize: 12.5, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
            <span className="dot online pulse" /> Mirroring GoHighLevel
          </span>
          {d.pipelineNames && <span className="mono"> · {d.pipelineNames.join(" + ")}</span>}
          <DashHealthDot />
          <DashCostChip />
        </div>
        <button className="tab" onClick={refresh} style={{ fontSize: 12 }}>
          {loading ? "Refreshing…" : "Refreshed " + window.timeAgo(refreshedAt)}
        </button>
      </div>

      <div className="kpi-row">
        {kpis.map((k) => <div key={k.key}><KpiCard kpi={k} value={k.value} loading={loading && !data} /></div>)}
      </div>

      <FDDashboardHero />

      <window.AceStrip />

      <ScoutWidget />

      <DoTodayCard />

      <PipelineOverview />

      <button className="tab" onClick={() => setShowMore((v) => !v)}
        style={{ alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
        <MoreChevron size={15} /> {showMore ? "Hide extras" : "More — Marcus, conversations, workforce, activity"}
      </button>

      {showMore && (
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 246px 246px", gap: 18, alignItems: "start" }}>
            <MarcusPanel />
            <HotLeads />
            <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <TodaysTasks />
              <NextActionCard />
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "270px minmax(0,1fr) 270px", gap: 18, alignItems: "start" }}>
            <ConversationsWidget />
            <AIWorkforce />
            <ActivityFeed />
          </div>
        </div>
      )}
    </div>
  );
}

window.Dashboard = Dashboard;
