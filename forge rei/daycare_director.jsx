// daycare_director.jsx — Solomon, the daycare's head agent (executive director).
// Reads the whole center + the business brief, produces a prioritized operating
// brief, owns enrollment, and delegates to role sub-agents via the agent bus.
// Read-only + propose/delegate — every outward action stays owner-approved.
const { useState: useStateDdr } = React;

function DdrChip({ ok, label }) {
  return <span className={"dc-live " + (ok ? "" : "dc-mock")} style={ok ? null : { color: "#F4B860", borderColor: "rgba(244,184,96,.4)" }}>
    <i style={ok ? null : { background: "#F4B860" }} /> {label}
  </span>;
}

function DdrUrgency({ level }) {
  const l = (level || "").toLowerCase();
  const color = l === "high" ? "#EF4444" : l === "med" || l === "medium" ? "#F4B860" : "#22C55E";
  return <span className="dc-severity" style={{ background: color }} title={level || "priority"} />;
}

function DdrList({ title, items, icon }) {
  if (!items || !items.length) return null;
  const Ico = (window.Icons && (window.Icons[icon] || window.Icons.Bot)) || null;
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">{title}</div></div><b>{items.length}</b></div>
    <div className="dc-alert-list">{items.map((t, i) => <div key={i}><span className="dc-severity info" /><div><b style={{ fontWeight: 500 }}>{typeof t === "string" ? t : (t.task || JSON.stringify(t))}</b></div></div>)}</div>
  </div>;
}

function DaycareDirector() {
  const [busy, setBusy] = useStateDdr(false);
  const [learning, setLearning] = useStateDdr(false);
  const [err, setErr] = useStateDdr(null);
  const ov = window.DcxUseResource("/director/overview", "dc-director", 15000);
  const bus = window.DcxUseResource("/director/bus", "dc-director-bus", 15000);
  const data = ov.data || {};
  const brief = data.brief || null;
  const learn = data.learn || {};
  const systems = data.systems || [];
  const activity = data.activity || [];
  const messages = (bus.data && bus.data.messages) || [];

  const run = async () => {
    setBusy(true); setErr(null);
    try { await window.DcxRequest("/director/run", { body: {} }); ov.refresh(); bus.refresh(); }
    catch (e) { setErr((e && e.message) || "Brief failed."); }
    finally { setBusy(false); }
  };
  const doLearn = async () => {
    setLearning(true); setErr(null);
    try { await window.DcxRequest("/director/learn", { body: {} }); ov.refresh(); bus.refresh(); }
    catch (e) { setErr((e && e.message) || "Learn failed."); }
    finally { setLearning(false); }
  };

  const briefAgo = data.lastBriefAt ? window.DcxDate(data.lastBriefAt, true) : "never";

  return <div className="dc-page">
    <div className="dc-hero" style={{ marginBottom: 14 }}>
      <div>
        <div className="dc-eyebrow">HEAD AGENT · EXECUTIVE DIRECTOR</div>
        <h1>Solomon</h1>
        <p>Your 30-year daycare director. He reads the whole center and the business brief, ranks what matters today, owns enrollment, and hands work to the role agents you add under him. He proposes and delegates — every outward action stays your one-tap approval.</p>
        <div className="dc-hero-actions">
          <button className="dc-primary" onClick={run} disabled={busy}><window.Icons.Bot size={15} /> {busy ? "Solomon is reviewing…" : "Build operating brief"}</button>
          <button className="dc-outline" onClick={doLearn} disabled={learning} style={{ borderColor: "rgba(139,92,246,.5)", color: "#C4B5FD" }}><window.Icons.Brain size={15} /> {learning ? "Learning…" : "Learn from brain"}</button>
        </div>
      </div>
    </div>

    <div className="dc-kpi-grid">
      <window.DcxKpi label="Scoring" value={data.aiReady ? "Claude" : "no key"} sub={data.aiReady ? "live model" : "add a key"} icon="Bot" color={data.aiReady ? "#22C55E" : "#F4B860"} />
      <window.DcxKpi label="Playbook" value={data.skillsLoaded ? "Loaded" : "—"} sub="from the brain" icon="Brain" color="#8B5CF6" />
      <window.DcxKpi label="Self-improved" value={learn.learnCount || 0} sub={"×  · " + (brief ? (brief.priorities || []).length + " priorities" : "no brief yet")} icon="Trend" color="#38BDF8" />
      <window.DcxKpi label="Last brief" value={data.briefCount || 0} sub={briefAgo} icon="Doc" />
    </div>

    <div className="dc-form-hint" style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
      <span style={{ opacity: .7 }}>Connected systems:</span>
      {systems.map((s) => <DdrChip key={s.key} ok={s.connected} label={s.name.replace(/\s*\(.*\)/, "")} />)}
    </div>

    <window.DcxState loading={ov.loading && !brief} error={err} onRetry={run} />

    {!brief && !busy && <div className="dc-all-clear"><window.Icons.Bot size={22} /><div><b>No operating brief yet</b><span>Tap “Build operating brief” — Solomon reads the center + the brief and ranks today’s moves.</span></div></div>}

    {brief && <div className="card card-pad dc-panel" style={{ borderColor: "rgba(45,212,191,.35)" }}>
      <div className="dc-panel-head"><div><div className="dc-eyebrow">OPERATING BRIEF</div><div className="card-title" style={{ fontSize: 18 }}>{brief.headline}</div></div><DdrChip ok={brief.contextLoaded} label={brief.contextLoaded ? "brief read" : "no brief"} /></div>
      <div className="dc-alert-list" style={{ marginTop: 8 }}>
        {(brief.priorities || []).map((p, i) => <div key={i} style={{ alignItems: "flex-start" }}>
          <DdrUrgency level={p.urgency} />
          <div><b>{p.title}</b><small style={{ display: "block", marginTop: 2, opacity: .85 }}>{p.why}</small><small style={{ opacity: .6 }}>{(p.area || "") + (p.urgency ? " · " + p.urgency : "")}</small></div>
        </div>)}
      </div>
    </div>}

    {brief && <div className="dc-main-grid">
      <DdrList title="Enrollment — Solomon owns this" items={brief.enrollment} icon="Children" />
      <DdrList title="Money" items={brief.money} icon="Billing" />
    </div>}
    {brief && <div className="dc-main-grid">
      <DdrList title="People & staffing" items={brief.people} icon="Staff" />
      {brief.delegations && brief.delegations.length > 0 && <div className="card card-pad dc-panel">
        <div className="dc-panel-head"><div><div className="card-title">Delegations</div><div className="faint">Handed to role agents via the bus</div></div><b>{brief.delegations.length}</b></div>
        <div className="dc-alert-list">{brief.delegations.map((d, i) => <div key={i}><span className="dc-severity" style={{ background: "#8B5CF6" }} /><div><b>{d.role}</b><small style={{ display: "block" }}>{d.task}</small></div></div>)}</div>
      </div>}
    </div>}

    <div className="dc-main-grid">
      <div className="card card-pad dc-panel">
        <div className="dc-panel-head"><div><div className="card-title">Activity</div><div className="faint">Solomon’s recent work</div></div></div>
        {activity.length ? <div className="dc-alert-list">{activity.slice(0, 10).map((a, i) => <div key={i}><span className="dc-severity info" /><div><b style={{ fontWeight: 500 }}>{a.text}</b><small style={{ display: "block", opacity: .6 }}>{a.kind + " · " + window.DcxDate(a.ts, true)}</small></div></div>)}</div> : <div className="dc-inline-empty">No activity yet.</div>}
      </div>
      <div className="card card-pad dc-panel">
        <div className="dc-panel-head"><div><div className="card-title">Agent comms</div><div className="faint">The bus Solomon leads</div></div></div>
        {messages.length ? <div className="dc-alert-list">{messages.slice(0, 10).map((m, i) => <div key={m.id || i}><span className="dc-severity" style={{ background: m.kind === "handoff" ? "#8B5CF6" : m.kind === "alert" ? "#EF4444" : "#22C55E" }} /><div><b style={{ fontWeight: 500 }}>{m.text}</b><small style={{ display: "block", opacity: .6 }}>{m.from + " → " + m.to + " · " + m.kind}</small></div></div>)}</div> : <div className="dc-inline-empty">No messages yet.</div>}
      </div>
    </div>
  </div>;
}

Object.assign(window, { DaycareDirector });
