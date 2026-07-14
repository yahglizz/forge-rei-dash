// daycare_family.jsx — Nora, the daycare's roster organizer & family follow-up
// agent. Reads the roster + recent Family Text Blast history, produces roster
// findings + named follow-up candidates, and picks up Solomon's bus delegations.
// Read-only + propose — every outward action stays owner-approved.
const { useState: useStateNr } = React;

function NrChip({ ok, label }) {
  return <span className={"dc-live " + (ok ? "" : "dc-mock")} style={ok ? null : { color: "#F4B860", borderColor: "rgba(244,184,96,.4)" }}>
    <i style={ok ? null : { background: "#F4B860" }} /> {label}
  </span>;
}

function NrUrgency({ level }) {
  const l = (level || "").toLowerCase();
  const color = l === "high" ? "#EF4444" : l === "med" || l === "medium" ? "#F4B860" : "#22C55E";
  return <span className="dc-severity" style={{ background: color }} title={level || "priority"} />;
}

function NrFindings({ title, items, icon }) {
  if (!items || !items.length) return null;
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">{title}</div></div><b>{items.length}</b></div>
    <div className="dc-alert-list">{items.map((p, i) => <div key={i} style={{ alignItems: "flex-start" }}>
      <NrUrgency level={p.urgency} />
      <div><b>{p.title}</b><small style={{ display: "block", marginTop: 2, opacity: .85 }}>{p.why}</small><small style={{ opacity: .6 }}>{p.area || ""}</small></div>
    </div>)}</div>
  </div>;
}

function NrFollowUps({ items }) {
  if (!items || !items.length) return null;
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Follow-ups</div><div className="faint">Families who may need a nudge</div></div><b>{items.length}</b></div>
    <div className="dc-alert-list">{items.map((f, i) => <div key={i}><span className="dc-severity info" /><div><b style={{ fontWeight: 500 }}>{f.family}</b><small style={{ display: "block", opacity: .85 }}>{f.reason}</small><small style={{ display: "block", opacity: .6 }}>→ {f.suggestedNextStep}</small></div></div>)}</div>
  </div>;
}

function DaycareFamilyAgent() {
  const [busy, setBusy] = useStateNr(false);
  const [learning, setLearning] = useStateNr(false);
  const [err, setErr] = useStateNr(null);
  const ov = window.DcxUseResource("/family/overview", "dc-nora", 15000);
  const bus = window.DcxUseResource("/family/bus", "dc-nora-bus", 15000);
  const data = ov.data || {};
  const brief = data.brief || null;
  const learn = data.learn || {};
  const activity = data.activity || [];
  const messages = (bus.data && bus.data.messages) || [];

  const run = async () => {
    setBusy(true); setErr(null);
    try { await window.DcxRequest("/family/run", { body: {} }); ov.refresh(); bus.refresh(); }
    catch (e) { setErr((e && e.message) || "Brief failed."); }
    finally { setBusy(false); }
  };
  const doLearn = async () => {
    setLearning(true); setErr(null);
    try { await window.DcxRequest("/family/learn", { body: {} }); ov.refresh(); bus.refresh(); }
    catch (e) { setErr((e && e.message) || "Learn failed."); }
    finally { setLearning(false); }
  };

  const briefAgo = data.lastBriefAt ? window.DcxDate(data.lastBriefAt, true) : "never";
  const roster = (brief && brief.roster) || {};

  return <div className="dc-page">
    <div className="dc-hero" style={{ marginBottom: 14 }}>
      <div>
        <div className="dc-eyebrow">ROLE AGENT · ROSTER &amp; FAMILY FOLLOW-UP</div>
        <h1>Nora</h1>
        <p>Keeps the roster organized — new enrollments, classroom capacity/ratio, missing guardian info — and follows up on family communications like the Family Text Blast, surfacing who needs a nudge. She reports to Solomon and proposes only; every send stays your one-tap approval.</p>
        <div className="dc-hero-actions">
          <button className="dc-primary" onClick={run} disabled={busy}><window.Icons.Children size={15} /> {busy ? "Nora is reviewing…" : "Build roster & follow-up brief"}</button>
          <button className="dc-outline" onClick={doLearn} disabled={learning} style={{ borderColor: "rgba(139,92,246,.5)", color: "#C4B5FD" }}><window.Icons.Brain size={15} /> {learning ? "Learning…" : "Learn from brain"}</button>
        </div>
      </div>
    </div>

    <div className="dc-kpi-grid">
      <window.DcxKpi label="Scoring" value={data.aiReady ? "Claude" : "no key"} sub={data.aiReady ? "live model" : "add a key"} icon="Bot" color={data.aiReady ? "#22C55E" : "#F4B860"} />
      <window.DcxKpi label="Playbook" value={data.skillsLoaded ? "Loaded" : "—"} sub="from the brain" icon="Brain" color="#8B5CF6" />
      <window.DcxKpi label="Self-improved" value={learn.learnCount || 0} sub={"×  · " + (brief ? (brief.rosterFindings || []).length + " roster findings" : "no brief yet")} icon="Trend" color="#38BDF8" />
      <window.DcxKpi label="Last brief" value={data.briefCount || 0} sub={briefAgo} icon="Doc" />
    </div>

    {roster && (roster.childrenTotal || roster.childrenTotal === 0) && <div className="dc-form-hint" style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
      <span style={{ opacity: .7 }}>Roster:</span>
      <NrChip ok label={(roster.childrenActive || 0) + " active / " + (roster.childrenTotal || 0) + " total"} />
      {(roster.missingGuardianContact || []).length > 0 && <NrChip label={(roster.missingGuardianContact || []).length + " missing guardian contact"} />}
    </div>}

    <window.DcxState loading={ov.loading && !brief} error={err} onRetry={run} />

    {!brief && !busy && <div className="dc-all-clear"><window.Icons.Children size={22} /><div><b>No brief yet</b><span>Tap “Build roster &amp; follow-up brief” — Nora reads the roster + recent blast log and surfaces what needs attention.</span></div></div>}

    {brief && <div className="card card-pad dc-panel" style={{ borderColor: "rgba(45,212,191,.35)" }}>
      <div className="dc-panel-head"><div><div className="dc-eyebrow">ROSTER &amp; FOLLOW-UP BRIEF</div><div className="card-title" style={{ fontSize: 18 }}>{brief.headline}</div></div><NrChip ok={brief.contextLoaded} label={brief.contextLoaded ? "brief read" : "no brief"} /></div>
    </div>}

    {brief && <div className="dc-main-grid">
      <NrFindings title="Roster findings" items={brief.rosterFindings} icon="Children" />
      <NrFollowUps items={brief.followUps} />
    </div>}

    {brief && brief.delegationsSeen && brief.delegationsSeen.length > 0 && <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Picked up from Solomon</div><div className="faint">Delegations she acted on this brief</div></div><b>{brief.delegationsSeen.length}</b></div>
      <div className="dc-alert-list">{brief.delegationsSeen.map((d, i) => <div key={i}><span className="dc-severity" style={{ background: "#8B5CF6" }} /><div><b style={{ fontWeight: 500 }}>{d}</b></div></div>)}</div>
    </div>}

    <div className="dc-main-grid">
      <div className="card card-pad dc-panel">
        <div className="dc-panel-head"><div><div className="card-title">Activity</div><div className="faint">Nora’s recent work</div></div></div>
        {activity.length ? <div className="dc-alert-list">{activity.slice(0, 10).map((a, i) => <div key={i}><span className="dc-severity info" /><div><b style={{ fontWeight: 500 }}>{a.text}</b><small style={{ display: "block", opacity: .6 }}>{a.kind + " · " + window.DcxDate(a.ts, true)}</small></div></div>)}</div> : <div className="dc-inline-empty">No activity yet.</div>}
      </div>
      <div className="card card-pad dc-panel">
        <div className="dc-panel-head"><div><div className="card-title">Agent comms</div><div className="faint">Nora ↔ Solomon on the bus</div></div></div>
        {messages.length ? <div className="dc-alert-list">{messages.slice(0, 10).map((m, i) => <div key={m.id || i}><span className="dc-severity" style={{ background: m.kind === "handoff" ? "#8B5CF6" : m.kind === "alert" ? "#EF4444" : "#22C55E" }} /><div><b style={{ fontWeight: 500 }}>{m.text}</b><small style={{ display: "block", opacity: .6 }}>{m.from + " → " + m.to + " · " + m.kind}</small></div></div>)}</div> : <div className="dc-inline-empty">No messages yet.</div>}
      </div>
    </div>
  </div>;
}

Object.assign(window, { DaycareFamilyAgent });
