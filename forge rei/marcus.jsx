// marcus.jsx — Agent Command Center. Live Marcus console: status, controls,
// proposal inbox (Approve / Edit / Dismiss), and activity stream.
const { useState: useStateM } = React;

const CLS_COLOR = {
  READY: "#22C55E", PRICE: "#F59E0B", NRN: "#8B5CF6",
  HELP: "#EF4444", CONTINUE: "#4F7CFF", DNC: "#64748B",
};

function MarcusConsole() {
  const Icons = window.Icons;
  const { data: status, refresh: refreshStatus } = window.useApi("/api/marcus/status", { interval: 8000 });
  const { data: feed, refresh: refreshFeed } = window.useApi("/api/marcus/proposals", { interval: 8000 });
  const [busy, setBusy] = useStateM(null);
  const [edits, setEdits] = useStateM({});

  const s = status || {};
  const proposals = (feed && feed.proposals) || [];
  const activity = (feed && feed.activity) || [];

  const refresh = () => { refreshStatus(); refreshFeed(); };

  async function act(fn, key) {
    setBusy(key);
    try { await fn(); } catch (e) { alert("Marcus: " + e.message); }
    setBusy(null);
    refresh();
  }
  const approve = (p) => act(() => window.apiPost("/api/marcus/approve", { id: p.id, message: edits[p.id] || p.suggestedReply }), p.id);
  const dismiss = (p) => act(() => window.apiPost("/api/marcus/dismiss", { id: p.id }), p.id);
  const toggle = (patch) => act(() => window.apiPost("/api/marcus/toggle", patch), "toggle");
  const pollNow = () => act(() => window.apiPost("/api/marcus/poll", {}), "poll");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {/* Header / status bar */}
      <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
        <div className="marcus-orb" style={{ width: 64, height: 64, flexShrink: 0 }}>
          <div className="orb-core" style={{ width: 40, height: 40 }} />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h1 style={{ fontSize: 22, fontWeight: 700 }}>Marcus</h1>
            <span className="pill" style={{ background: s.enabled ? "rgba(34,197,94,0.12)" : "rgba(100,116,139,0.15)", color: s.enabled ? "var(--green)" : "var(--text-3)", border: "1px solid " + (s.enabled ? "rgba(34,197,94,0.3)" : "var(--border)") }}>
              <span className={"dot " + (s.enabled ? "online pulse" : "")} /> {s.enabled ? "ON DUTY" : "PAUSED"}
            </span>
          </div>
          <div className="faint" style={{ fontSize: 13, marginTop: 4 }}>{s.task || "…"}</div>
          <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>
            Drafts: <b style={{ color: s.hasAI ? "var(--green)" : "var(--orange)" }}>{s.draftMode || "—"}</b>
            {" · "}last check {window.timeAgo(s.lastPoll)}{" · "}polls every {s.pollInterval}s
            {s.lastError && <span style={{ color: "var(--red)" }}> · err: {s.lastError}</span>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="tab" onClick={pollNow} disabled={busy === "poll"}>{busy === "poll" ? "Checking…" : "Check now"}</button>
          <Switch label="Active" on={!!s.enabled} onClick={() => toggle({ enabled: !s.enabled })} />
          <Switch label="Auto-send" on={!!s.autoSend} danger onClick={() => toggle({ autoSend: !s.autoSend })} />
        </div>
      </div>

      {s.autoSend && (
        <div className="card" style={{ padding: 12, borderColor: "var(--orange)", display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ color: "var(--orange)" }}><Icons.Spark size={16} /></span>
          <span style={{ fontSize: 12.5 }}><b>Auto-send ON</b> — Marcus texts sellers without asking. Turn off to review every reply first.</span>
        </div>
      )}

      {/* Counters */}
      <div className="kpi-row">
        <Stat label="Pending" value={s.pending || 0} color="#F59E0B" icon="Conversations" />
        <Stat label="Sent" value={(s.counts || {}).sent || 0} color="#22C55E" icon="Send" />
        <Stat label="Suppressed (DNC)" value={(s.counts || {}).suppressed || 0} color="#64748B" icon="Check" />
        <Stat label="Proposed total" value={(s.counts || {}).proposed || 0} color="#4F7CFF" icon="Spark" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 18, alignItems: "start" }}>
        {/* Proposal inbox */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card-title" style={{ fontSize: 16 }}>Reply Inbox — needs your approval</div>
          {proposals.length === 0 && (
            <div className="card empty" style={{ minHeight: 200 }}>
              <div className="empty-ico"><Icons.Check size={26} /></div>
              <div style={{ fontWeight: 600, color: "var(--text)" }}>All caught up</div>
              <div style={{ fontSize: 12.5 }}>Marcus is watching. New seller replies show up here.</div>
            </div>
          )}
          {proposals.map((p) => (
            <div key={p.id} className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span className="pill" style={{ background: (CLS_COLOR[p.classification] || "#4F7CFF") + "22", color: CLS_COLOR[p.classification] || "#4F7CFF", border: "1px solid " + (CLS_COLOR[p.classification] || "#4F7CFF") + "55" }}>{p.classification}</span>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{p.name}</div>
                    <div className="faint mono" style={{ fontSize: 11 }}>{p.phone}</div>
                  </div>
                </div>
                <span className="faint" style={{ fontSize: 11 }}>→ {p.action}</span>
              </div>

              <div style={{ background: "var(--card-2)", borderRadius: 10, padding: "10px 12px", fontSize: 13, lineHeight: 1.4 }}>
                <span className="faint" style={{ fontSize: 11 }}>Seller said:</span><br />“{p.inbound}”
              </div>

              <div>
                <div className="faint" style={{ fontSize: 11, marginBottom: 5, display: "flex", justifyContent: "space-between" }}>
                  <span>Marcus's reply ({p.draftSource})</span>
                </div>
                <textarea
                  defaultValue={p.suggestedReply}
                  onChange={(e) => setEdits((m) => ({ ...m, [p.id]: e.target.value }))}
                  rows={3}
                  style={{ width: "100%", resize: "vertical", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 12px", fontSize: 13, fontFamily: "inherit", lineHeight: 1.4 }}
                />
              </div>

              <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                <button className="tab" onClick={() => dismiss(p)} disabled={busy === p.id}>Dismiss</button>
                <button onClick={() => approve(p)} disabled={busy === p.id}
                  style={{ display: "flex", alignItems: "center", gap: 7, padding: "9px 16px", borderRadius: 11, background: "linear-gradient(135deg,#22C55E,#16a34a)", fontWeight: 600, fontSize: 13.5, color: "#fff" }}>
                  <Icons.Send size={15} /> {busy === p.id ? "Sending…" : "Approve & Send"}
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Activity stream */}
        <div className="card card-pad">
          <div className="card-title" style={{ marginBottom: 12 }}>Marcus Activity</div>
          {activity.length === 0 && <div className="faint" style={{ fontSize: 12.5 }}>No activity yet.</div>}
          {activity.map((e, i) => {
            const c = { propose: "#4F7CFF", sent: "#22C55E", suppress: "#64748B", dismiss: "#F59E0B", config: "#8B5CF6" }[e.kind] || "#4F7CFF";
            return (
              <div className="feed-item" key={i}>
                <div className="feed-ico" style={{ background: c + "1f", color: c }}><Icons.Spark size={14} /></div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.5 }}>{e.text}</div>
                  <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>{window.timeAgo(e.ts)}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Switch({ label, on, onClick, danger }) {
  return (
    <button onClick={onClick} className="tab" style={{ display: "flex", alignItems: "center", gap: 8, borderColor: on ? (danger ? "var(--orange)" : "var(--green)") : "var(--border)" }}>
      <span style={{ width: 30, height: 17, borderRadius: 999, background: on ? (danger ? "var(--orange)" : "var(--green)") : "var(--border)", position: "relative", transition: "background .2s" }}>
        <span style={{ position: "absolute", top: 2, left: on ? 15 : 2, width: 13, height: 13, borderRadius: 999, background: "#fff", transition: "left .2s" }} />
      </span>
      {label}
    </button>
  );
}

function Stat({ label, value, color, icon }) {
  const Icons = window.Icons;
  const Ico = Icons[icon] || Icons.Spark;
  return (
    <div className="kpi">
      <div className="kpi-ico" style={{ background: color + "1f", color }}><Ico size={18} /></div>
      <div className="kpi-label">{label}</div>
      <div className="kpi-val"><window.CountUp to={Number(value || 0)} /></div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scout console — review what Scout triaged: tags applied / queued + pipeline pushes.
// ---------------------------------------------------------------------------
const SCOUT_SC = (s) => (s >= 80 ? "#22C55E" : s >= 60 ? "#F59E0B" : "#EF4444");

function ScoutRow({ l, busy, onTag, onPipe, onOpen, onHandoff, compact }) {
  const Icons = window.Icons;
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontWeight: 800, color: SCOUT_SC(l.motivation), fontSize: 13, flexShrink: 0 }}>{l.motivation}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.name}{l.priceBand ? ` · asks ${l.priceBand}` : ""}</div>
          <div className="faint mono" style={{ fontSize: 11 }}>{l.phone || "no phone"}</div>
        </div>
        {l.pipelineStage && <span className="pill" style={{ background: "rgba(59,130,246,0.14)", color: "var(--blue)", fontSize: 9.5 }}>● {l.pipelineStage}</span>}
        {l.tagsAppliedAt && <span className="pill" style={{ background: "rgba(34,197,94,0.12)", color: "var(--green)", fontSize: 9.5 }}>tagged ✓</span>}
      </div>
      {l.reason && <div style={{ fontSize: 12.5 }}>{l.reason}</div>}
      {!compact && l.lastMessage && <div className="faint" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>"{l.lastMessage}"</div>}
      {!compact && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
          {(l.proposedTags || []).map((t) => <span key={t} className="pill" style={{ fontSize: 9.5, background: "var(--card-2)" }}>{t}</span>)}
        </div>
      )}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {!l.tagsAppliedAt && <button className="tab" disabled={busy === "tag" + l.id} onClick={() => onTag(l)} style={{ fontSize: 11, border: "1px solid var(--border)" }}>{busy === "tag" + l.id ? "…" : "Apply tags"}</button>}
        {[["hot", "🔥 Hot"], ["warm", "Warm"], ["follow-up", "Follow-up"]].map(([k, lab]) => (
          <button key={k} className="tab" disabled={busy === "pipe" + l.id + k} onClick={() => onPipe(l, k)} style={{ fontSize: 10.5, padding: "3px 9px", border: "1px solid var(--border)" }}>{busy === "pipe" + l.id + k ? "…" : "→ " + lab}</button>
        ))}
        <button className="tab" onClick={() => onOpen(l)} style={{ fontSize: 11, border: "1px solid var(--border)" }}>Open thread</button>
        {onHandoff && <button className="tab" disabled={busy === "ho" + l.id} onClick={() => onHandoff(l)} style={{ fontSize: 11, border: "1px solid var(--violet)", color: "var(--violet)" }}>{busy === "ho" + l.id ? "…" : "→ Hand to Marcus"}</button>}
      </div>
    </div>
  );
}

function ScoutConsole() {
  const Icons = window.Icons;
  const { data, refresh } = window.useApi("/api/scout/overview", { interval: 8000 });
  const bus = window.useApi("/api/bus?limit=30", { interval: 8000 });
  const audit = window.useApi("/api/scout/audit", { interval: 20000 });
  const [busy, setBusy] = useStateM(null);
  const [auditDays, setAuditDays] = useStateM(7);
  const [auditBusy, setAuditBusy] = useStateM(false);
  const [handedMissed, setHandedMissed] = useStateM({});  // convId -> "busy"|"done"|"err:.."
  const a = audit.data || {};
  const found = a.found || [];
  const o = data || {};
  const counts = o.counts || {};
  const pending = o.pendingTags || [];
  const pipeline = o.pipeline || [];
  const tagged = o.tagged || [];
  const activity = o.activity || [];
  const learn = o.learn || {};
  const comms = (bus.data && bus.data.messages) || [];

  async function act(fn, key) { setBusy(key); try { await fn(); } catch (e) { alert("Scout: " + e.message); } setBusy(null); refresh(); }
  const runNow = () => act(() => window.apiPost("/api/scout/run", {}), "run");
  const learnNow = () => act(() => window.apiPost("/api/scout/learn", {}), "learn");
  const onTag = (l) => act(() => window.apiPost("/api/scout/apply", { id: l.id }), "tag" + l.id);
  const onPipe = (l, stage) => act(() => window.apiPost("/api/scout/pipeline", { id: l.id, stage }), "pipe" + l.id + stage);
  const onHandoff = (l) => act(() => window.apiPost("/api/scout/handoff", { id: l.id }), "ho" + l.id);
  const onOpen = (l) => window.openConversation && window.openConversation(l);
  async function runSweep() {
    setAuditBusy(true);
    try { await window.apiPost("/api/scout/audit/run", { days: auditDays }); }
    catch (e) { alert("Scout sweep: " + e.message); }
    setAuditBusy(false);
    audit.refresh();
  }
  // Hand a missed lead to Marcus — he drafts a re-engage reply on Scout's angle into his
  // approval inbox (review-gated). Resolves deep leads via contactId.
  async function handMissed(row) {
    setHandedMissed((h) => ({ ...h, [row.id]: "busy" }));
    try {
      const r = await window.apiPost("/api/scout/handoff",
        { id: row.id, contactId: row.contactId, hint: row.recommendedAction || row.signal, lastSaid: row.lastSellerSaid });
      setHandedMissed((h) => ({ ...h, [row.id]: (r && r.error) ? ("err:" + r.error) : "done" }));
    } catch (e) {
      setHandedMissed((h) => ({ ...h, [row.id]: "err:" + e.message }));
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
        <div className="marcus-orb" style={{ width: 64, height: 64, flexShrink: 0 }}>
          <div className="orb-core" style={{ width: 40, height: 40 }} />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h1 style={{ fontSize: 22, fontWeight: 700 }}>Scout</h1>
            <span className="pill" style={{ background: "rgba(34,197,94,0.12)", color: "var(--green)", border: "1px solid rgba(34,197,94,0.3)" }}>
              <span className="dot online pulse" /> ON DUTY
            </span>
          </div>
          <div className="faint" style={{ fontSize: 13, marginTop: 4 }}>Lead triage · ranks who to text back, queues tags + pipeline pushes for your review. Never texts sellers.</div>
          <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>
            Scoring: <b style={{ color: o.aiScoring ? "var(--green)" : "var(--orange)" }}>{o.aiScoring ? "Claude" : "rules"}</b>
            {" · "}playbook <b style={{ color: o.skillsLoaded ? "var(--green)" : "var(--orange)" }}>{o.skillsLoaded ? "loaded from brain" : "none"}</b>
            {" · "}self-improved <b>{learn.learnCount || 0}×</b>{learn.lastLearnedAt ? ` (last ${window.timeAgo(learn.lastLearnedAt)})` : ""}
            {" · "}last sweep {window.timeAgo(o.lastRun)}
            {o.lastError && <span style={{ color: "var(--red)" }}> · err: {o.lastError}</span>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="tab" onClick={runNow} disabled={busy === "run"}>{busy === "run" ? "Sweeping…" : "Run sweep now"}</button>
          <button className="tab" onClick={learnNow} disabled={busy === "learn"} style={{ borderColor: "var(--violet)", color: "var(--violet)" }} title="Scout reflects on recent leads + rewrites its playbook in the brain">{busy === "learn" ? "Learning…" : "Learn from brain"}</button>
        </div>
      </div>

      <div className="kpi-row">
        <Stat label="Text ASAP" value={counts.asap || 0} color="#EF4444" icon="Spark" />
        <Stat label="Warm" value={counts.warm || 0} color="#F59E0B" icon="Conversations" />
        <Stat label="In pipeline" value={o.pipelineCount || 0} color="#4F7CFF" icon="Pipeline" />
        <Stat label="Tagged" value={o.taggedCount || 0} color="#22C55E" icon="Check" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 18, alignItems: "start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12, border: "1px solid rgba(139,92,246,0.3)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <div className="card-title" style={{ fontSize: 16, flex: 1, minWidth: 160 }}>💎 Missed Leads · Weekly Sweep</div>
              <select className="tab" value={auditDays} disabled={auditBusy} onChange={(e) => setAuditDays(parseInt(e.target.value, 10))} style={{ fontSize: 11.5, border: "1px solid var(--border)", padding: "5px 8px" }}>
                <option value={7}>Last 7 days</option>
                <option value={30}>Last 30 days</option>
                <option value={60}>Last 60 days</option>
              </select>
              <button className="tab" onClick={runSweep} disabled={auditBusy} style={{ fontSize: 11.5, border: "1px solid var(--violet)", color: "var(--violet)" }}>
                {auditBusy ? "Sweeping…" : "Run weekly sweep now"}
              </button>
            </div>
            <div className="faint" style={{ fontSize: 11 }}>Deep-reads the last {auditDays} days of seller threads and surfaces leads we let go cold. Runs automatically every week. Takes 10–20s.</div>
            {a.summary && <div style={{ fontSize: 13, fontWeight: 600 }}>{a.summary}</div>}
            <div className="faint" style={{ fontSize: 11.5 }}>
              Last swept {window.timeAgo(a.ranAt)} · scanned {a.scanned || 0} · {found.length} missed
              {a.running && <span style={{ color: "var(--violet)" }}> · sweeping now…</span>}
            </div>

            {found.length === 0 && (
              <div className="card empty" style={{ minHeight: 120, margin: 0 }}>
                <div className="empty-ico"><Icons.Search size={24} /></div>
                <div style={{ fontWeight: 600, color: "var(--text)" }}>No missed leads found</div>
                <div style={{ fontSize: 12.5 }}>Run a sweep to deep-read recent threads for sellers who showed signal but went cold.</div>
              </div>
            )}

            {found.map((row, i) => (
              <div key={row.id || i} className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 7, background: "var(--card-2)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontWeight: 800, color: SCOUT_SC(row.score), fontSize: 13, flexShrink: 0 }}>{row.score}</span>
                  <div style={{ flex: 1, minWidth: 0, fontWeight: 600, fontSize: 13.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.name || "Unknown"}</div>
                  {row.auto && <span className="pill" style={{ fontSize: 9, background: "rgba(139,92,246,0.14)", color: "var(--violet)" }}>auto</span>}
                  <span className="pill" style={{ fontSize: 9.5, background: "rgba(239,68,68,0.12)", color: "var(--red)" }}>cold {row.daysCold || 0}d</span>
                </div>
                {row.signal && <div style={{ fontSize: 12.5 }}>{row.signal}</div>}
                {row.lastSellerSaid && <div className="faint" style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>"{row.lastSellerSaid}"</div>}
                {row.recommendedAction && <div style={{ fontSize: 12, color: "var(--violet)" }}>→ {row.recommendedAction}</div>}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                  <button className="tab" onClick={() => onOpen(row)} style={{ fontSize: 11, border: "1px solid var(--border)" }}>Open thread</button>
                  {(() => {
                    const st = handedMissed[row.id];
                    if (st === "done") return <span className="pill" style={{ fontSize: 10, background: "rgba(236,72,153,0.14)", color: "#EC4899" }}>✓ Marcus drafted it — approve in Agents</span>;
                    if (st && st.startsWith("err:")) return <span className="pill" style={{ fontSize: 10, background: "rgba(239,68,68,0.12)", color: "var(--red)" }} title={st.slice(4)}>handoff failed</span>;
                    return (
                      <button className="tab" onClick={() => handMissed(row)} disabled={st === "busy"}
                        style={{ fontSize: 11, border: "1px solid #EC4899", color: "#EC4899", fontWeight: 600 }}
                        title="Marcus drafts a re-engage text on Scout's angle (review-gated — nothing sends yet)">
                        {st === "busy" ? "Handing…" : "→ Hand to Marcus"}
                      </button>
                    );
                  })()}
                </div>
              </div>
            ))}
          </div>

          <div className="card-title" style={{ fontSize: 16 }}>Needs your review — apply tags / push to pipeline</div>
          {pending.length === 0 && (
            <div className="card empty" style={{ minHeight: 160 }}>
              <div className="empty-ico"><Icons.Check size={26} /></div>
              <div style={{ fontWeight: 600, color: "var(--text)" }}>Nothing waiting</div>
              <div style={{ fontSize: 12.5 }}>Scout surfaces motivated sellers here as they reply. Stop / not-interested are filtered out.</div>
            </div>
          )}
          {pending.map((l) => <ScoutRow key={l.id} l={l} busy={busy} onTag={onTag} onPipe={onPipe} onOpen={onOpen} onHandoff={onHandoff} />)}

          {pipeline.length > 0 && (
            <React.Fragment>
              <div className="card-title" style={{ fontSize: 16, marginTop: 6 }}>Pushed to pipeline</div>
              {pipeline.map((l) => <ScoutRow key={l.id} l={l} busy={busy} onTag={onTag} onPipe={onPipe} onOpen={onOpen} compact />)}
            </React.Fragment>
          )}

          {tagged.length > 0 && (
            <React.Fragment>
              <div className="card-title" style={{ fontSize: 16, marginTop: 6 }}>Tagged</div>
              {tagged.map((l) => <ScoutRow key={l.id} l={l} busy={busy} onTag={onTag} onPipe={onPipe} onOpen={onOpen} compact />)}
            </React.Fragment>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div className="card card-pad">
            <div className="card-title" style={{ marginBottom: 12 }}>Scout Activity</div>
            {activity.length === 0 && <div className="faint" style={{ fontSize: 12.5 }}>No actions yet. Apply a tag or push a lead to the pipeline and it logs here.</div>}
            {activity.map((e, i) => {
              const c = { tag: "#22C55E", pipeline: "#4F7CFF", dismiss: "#F59E0B", learn: "#8B5CF6", handoff: "#EC4899" }[e.kind] || "#8B5CF6";
              return (
                <div className="feed-item" key={i}>
                  <div className="feed-ico" style={{ background: c + "1f", color: c }}><Icons.Spark size={14} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12.5 }}>{e.text}</div>
                    <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>{window.timeAgo(e.ts)}</div>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="card card-pad">
            <div className="card-title" style={{ marginBottom: 4 }}>Agent Comms</div>
            <div className="faint" style={{ fontSize: 11, marginBottom: 10 }}>Messages between your agents (handoffs, alerts, self-improvement).</div>
            {comms.length === 0 && <div className="faint" style={{ fontSize: 12.5 }}>No agent messages yet.</div>}
            {comms.map((m, i) => {
              const c = { handoff: "#EC4899", alert: "#EF4444", status: "#8B5CF6", note: "#4F7CFF" }[m.kind] || "#4F7CFF";
              return (
                <div className="feed-item" key={m.id || i}>
                  <div className="feed-ico" style={{ background: c + "1f", color: c }}><Icons.Send size={13} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="faint" style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.3 }}>{(m.from || "?").toUpperCase()} → {(m.to || "?").toUpperCase()} · {m.kind}</div>
                    <div style={{ fontSize: 12.5 }}>{m.text}</div>
                    <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>{window.timeAgo(m.ts)}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

const TG_TOGGLES = [
  ["hot_lead", "🔥 Hot lead to text now"],
  ["proposal", "✅ Reply approvals — warm+ only"],
  ["missed_sweep", "💎 Weekly missed-leads sweep"],
  ["handoff", "🤝 Handoffs"],
  ["agency", "Agency (Eco/Dyson) alerts"],
];

function TgAlerts() {
  const Icons = window.Icons;
  const TgBell = Icons.Bell;
  const TgSend = Icons.Send;
  const s = window.useApi("/api/notify/settings", { interval: 20000 });
  const d = s.data || {};
  const tog = d.toggles || {};
  const [tgBusy, setTgBusy] = useStateM(null);
  const [tgResult, setTgResult] = useStateM(null);

  const sendTest = async () => {
    setTgBusy("test");
    setTgResult(null);
    try {
      await window.apiPost("/api/notify/test", {});
      setTgResult({ ok: true, msg: "Test sent — check Telegram." });
    } catch (e) {
      setTgResult({ ok: false, msg: (e && e.message) || "Failed to send." });
    }
    setTgBusy(null);
    s.refresh();
  };

  const flip = async (key) => {
    setTgBusy(key);
    try {
      await window.apiPost("/api/notify/settings", { toggles: { ...tog, [key]: !tog[key] } });
    } catch (e) { /* best-effort; refresh shows truth */ }
    setTgBusy(null);
    s.refresh();
  };

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Header / status */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={{ color: "var(--accent, #4F7CFF)", display: "flex" }}><TgBell size={18} /></span>
        <span className="card-title" style={{ fontSize: 16 }}>🔔 Telegram Alerts</span>
        <span className="pill" style={{
          marginLeft: 8,
          background: d.configured ? "rgba(34,197,94,0.12)" : "rgba(245,158,11,0.12)",
          color: d.configured ? "var(--green)" : "var(--orange)",
          border: "1px solid " + (d.configured ? "rgba(34,197,94,0.3)" : "rgba(245,158,11,0.3)"),
        }}>
          <span className={"dot " + (d.configured ? "online pulse" : "")} />
          {d.configured ? "Telegram connected" : "Telegram — not configured (add token in forge-telegram/config/telegram.env)"}
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginLeft: "auto" }}>
          {tgResult && (
            <span style={{ fontSize: 12, fontWeight: 600, color: tgResult.ok ? "var(--green)" : "var(--red)" }}>
              {tgResult.ok ? "✓ " : "✕ "}{tgResult.msg}
            </span>
          )}
          <button className="tab" onClick={sendTest} disabled={tgBusy === "test"}
            style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <TgSend size={14} /> {tgBusy === "test" ? "Sending…" : "Send test"}
          </button>
        </div>
      </div>

      {/* Toggle rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {TG_TOGGLES.map(([key, label]) => {
          const on = !!tog[key];
          return (
            <div key={key} style={{
              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
              padding: "9px 12px", borderRadius: 10, background: "var(--card-2)",
            }}>
              <span style={{ fontSize: 13 }}>{label}</span>
              <button className="tab" onClick={() => flip(key)} disabled={tgBusy === key}
                style={{
                  minWidth: 64, padding: "5px 12px", fontSize: 12, fontWeight: 700,
                  background: on ? "rgba(34,197,94,0.12)" : "rgba(100,116,139,0.12)",
                  color: on ? "var(--green)" : "var(--text-3)",
                  border: "1px solid " + (on ? "rgba(34,197,94,0.3)" : "var(--border)"),
                }}>
                {tgBusy === key ? "…" : (on ? "ON" : "OFF")}
              </button>
            </div>
          );
        })}
      </div>

      {/* Quiet hours — suppress non-urgent pings while you sleep */}
      <TgQuietHours quiet={d.quietHours} onSaved={s.refresh} />

      <div className="faint" style={{ fontSize: 11.5 }}>
        Setup: forge-telegram/config/telegram.env — BotFather token + your chat id.
      </div>
    </div>
  );
}

function TgQuietHours({ quiet, onSaved }) {
  const q = quiet || {};
  const [tgqBusy, setTgqBusy] = useStateM(false);
  const [tgqStart, setTgqStart] = useStateM(null);   // null = follow server
  const [tgqEnd, setTgqEnd] = useStateM(null);
  const start = tgqStart === null ? (q.start !== undefined ? q.start : 22) : tgqStart;
  const end = tgqEnd === null ? (q.end !== undefined ? q.end : 7) : tgqEnd;
  const save = async (patch) => {
    setTgqBusy(true);
    try {
      await window.apiPost("/api/notify/settings", {
        quietHours: { enabled: !!q.enabled, start: Number(start) || 0,
                      end: Number(end) || 0, ...patch } });
    } catch (e) { /* refresh shows truth */ }
    setTgqBusy(false);
    setTgqStart(null); setTgqEnd(null);
    onSaved && onSaved();
  };
  const numInp = {
    width: 58, background: "var(--card-2)", border: "1px solid var(--border)",
    borderRadius: 8, padding: "6px 8px", color: "var(--text)", fontSize: 13, outline: "none",
  };
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
      padding: "9px 12px", borderRadius: 10, background: "var(--card-2)",
    }}>
      <span style={{ fontSize: 13 }}>😴 Quiet hours</span>
      <input type="number" min="0" max="23" style={numInp} value={start}
        onChange={(e) => setTgqStart(e.target.value)} />
      <span className="faint" style={{ fontSize: 12 }}>to</span>
      <input type="number" min="0" max="23" style={numInp} value={end}
        onChange={(e) => setTgqEnd(e.target.value)} />
      <span className="faint" style={{ fontSize: 11 }}>(24h local, wraps midnight)</span>
      <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
        {(tgqStart !== null || tgqEnd !== null) && (
          <button className="tab" onClick={() => save({})} disabled={tgqBusy}
            style={{ fontSize: 12 }}>
            {tgqBusy ? "…" : "Save hours"}
          </button>
        )}
        <button className="tab" onClick={() => save({ enabled: !q.enabled })} disabled={tgqBusy}
          style={{
            minWidth: 64, padding: "5px 12px", fontSize: 12, fontWeight: 700,
            background: q.enabled ? "rgba(34,197,94,0.12)" : "rgba(100,116,139,0.12)",
            color: q.enabled ? "var(--green)" : "var(--text-3)",
            border: "1px solid " + (q.enabled ? "rgba(34,197,94,0.3)" : "var(--border)"),
          }}>
          {tgqBusy ? "…" : (q.enabled ? "ON" : "OFF")}
        </button>
      </div>
    </div>
  );
}

function TestModeBanner() {
  const TmIcons = window.Icons;
  const TmWarn = TmIcons.Spark;
  const tm = window.useApi("/api/test-mode", { interval: 10000 });
  const t = tm.data || {};
  const [tmBusy, setTmBusy] = useStateM(false);

  const tmTurnOff = async () => {
    setTmBusy(true);
    try {
      await window.apiPost("/api/test-mode", { enabled: false });
    } catch (e) { /* best-effort; refresh shows truth */ }
    setTmBusy(false);
    tm.refresh();
  };

  if (!t.enabled) {
    return (
      <div className="faint" style={{ fontSize: 11.5, opacity: 0.6 }}>
        Test mode: off
      </div>
    );
  }

  const tmPhones = (t.phones || []).join(", ") || "(no numbers whitelisted)";

  return (
    <div className="card card-pad" style={{
      display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
      border: "2px solid var(--red)",
      background: "rgba(239,68,68,0.12)",
    }}>
      <span style={{ color: "var(--orange)", display: "flex" }}><TmWarn size={20} /></span>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1, minWidth: 240 }}>
        <span style={{ fontSize: 15, fontWeight: 800, color: "var(--red)", letterSpacing: 0.2 }}>
          ⚠ TEST MODE — autopilot ON for: {tmPhones}.
        </span>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--orange)" }}>
          Marcus auto-replies + Scout auto-tags/pipelines these numbers only. Real sellers stay review-gated.
        </span>
      </div>
      <button className="tab" onClick={tmTurnOff} disabled={tmBusy}
        style={{
          marginLeft: "auto", fontWeight: 800, fontSize: 13,
          border: "1px solid var(--red)",
          background: "rgba(239,68,68,0.18)",
          color: "var(--red)",
        }}>
        {tmBusy ? "Turning off…" : "Turn OFF"}
      </button>
    </div>
  );
}

const COMMAND_AGENTS = [["marcus", "Marcus"], ["scout", "Scout"]];

function ClockCard() {
  const Icons = window.Icons;
  const ClkIcon = Icons.Clock || Icons.Power || Icons.Bot;
  const cs = window.useApi("/api/ops/status", { interval: 6000 });
  const cd = cs.data || {};
  const clkPaused = !!cd.paused;
  const crew = (cd.crew || []).join(", ");
  const [clkBusy, setClkBusy] = useStateM(false);
  const flipClock = async () => {
    setClkBusy(true);
    try { await window.apiPost("/api/ops/set", { paused: !clkPaused }); }
    catch (e) { /* refresh shows truth */ }
    setClkBusy(false);
    cs.refresh();
  };
  return (
    <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
      <ClkIcon size={18} style={{ color: clkPaused ? "var(--danger, #e5484d)" : "var(--accent, #46a758)" }} />
      <div style={{ display: "flex", flexDirection: "column" }}>
        <span className="card-title" style={{ fontSize: 15 }}>
          {clkPaused ? "Agents clocked OUT" : "Agents clocked IN"}
        </span>
        <span className="faint" style={{ fontSize: 12 }}>
          {clkPaused
            ? (crew + " stood down — you've got the wheel, your taps still work")
            : (crew + " working: sweeping, scoring, tagging, screening, prepping")}
        </span>
      </div>
      <button onClick={flipClock} disabled={clkBusy}
        style={{ marginLeft: "auto", background: clkPaused ? "var(--accent, #46a758)" : "var(--danger, #e5484d)", color: "#fff", border: "none", borderRadius: 10, padding: "9px 16px", fontSize: 13, fontWeight: 700, fontFamily: "inherit", cursor: "pointer", opacity: clkBusy ? 0.6 : 1 }}>
        {clkBusy ? "…" : (clkPaused ? "🟢 Clock agents IN" : "🕐 Clock agents OUT")}
      </button>
    </div>
  );
}

function SkillForgeCard() {
  // skill_forge: cross-agent pattern → proposed skill, adopted only on a tap.
  const sf = window.useApi("/api/skillforge/pending", { interval: 30000 });
  const d = sf.data || {};
  const pend = Array.isArray(d.pending) ? d.pending : [];
  const [sfBusy, setSfBusy] = useStateM(null);
  const act = async (pid, action) => {
    setSfBusy(pid + action);
    try { await window.apiPost("/api/skillforge/act", { pid, action }); }
    catch (e) { /* refresh shows truth */ }
    setSfBusy(null);
    sf.refresh();
  };
  if (!pend.length) return null;   // silent until there's something to decide
  return (
    <div className="card card-pad">
      <div className="card-title" style={{ fontSize: 15, marginBottom: 4 }}>
        ✨ Skill proposals <span className="faint" style={{ fontSize: 11.5, fontWeight: 400 }}>
          — patterns your agents keep hitting; adopt to make them permanent</span>
      </div>
      {pend.map((p) => (
        <div key={p.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 2px", borderBottom: "1px solid var(--card-2)", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ fontWeight: 600, fontSize: 13.5 }}>{p.title || p.topic}</div>
            <div className="faint" style={{ fontSize: 11 }}>
              seen from {(p.agents || []).join(", ") || "?"} · {p.count || 0} mentions
            </div>
          </div>
          <button className="tab" disabled={sfBusy === p.id + "approve"}
            onClick={() => act(p.id, "approve")}
            style={{ background: "var(--accent, #46a758)", color: "#fff", fontWeight: 700 }}>
            {sfBusy === p.id + "approve" ? "…" : "✅ Adopt"}
          </button>
          <button className="tab" disabled={sfBusy === p.id + "dismiss"}
            onClick={() => act(p.id, "dismiss")}>
            {sfBusy === p.id + "dismiss" ? "…" : "Dismiss"}
          </button>
        </div>
      ))}
    </div>
  );
}

function CommandCenter() {
  const [agent, setAgent] = useStateM("marcus");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <TestModeBanner />
      <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <span className="card-title" style={{ fontSize: 16 }}>Agent Command Center</span>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginLeft: "auto" }}>
          <span className="faint" style={{ fontSize: 12 }}>Agent</span>
          <select value={agent} onChange={(e) => setAgent(e.target.value)}
            style={{ background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 10, padding: "8px 12px", fontSize: 13, fontFamily: "inherit", fontWeight: 600 }}>
            {COMMAND_AGENTS.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </div>
      </div>
      <ClockCard />
      <window.AcePanel />
      <SkillForgeCard />
      <TgAlerts />
      {agent === "marcus" ? <MarcusConsole /> : <ScoutConsole />}
    </div>
  );
}

window.MarcusCommand = CommandCenter;
