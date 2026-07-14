// daycare_adops.jsx — Nova, the daycare's ad ops agent. Reads campaign health +
// the existing competitor read, recommends which live creative angle needs
// fresh work. Read-only + propose — launching/spending/generating creative
// stays a human (or a chat session with Higgsfield/Meta tool access) action.
const { useState: useStateNv } = React;

function NvChip({ ok, label }) {
  return <span className={"dc-live " + (ok ? "" : "dc-mock")} style={ok ? null : { color: "#F4B860", borderColor: "rgba(244,184,96,.4)" }}>
    <i style={ok ? null : { background: "#F4B860" }} /> {label}
  </span>;
}

function NvUrgency({ level }) {
  const l = (level || "").toLowerCase();
  const color = l === "high" ? "#EF4444" : l === "med" || l === "medium" ? "#F4B860" : "#22C55E";
  return <span className="dc-severity" style={{ background: color }} title={level || "priority"} />;
}

function NvCampaignHealth({ items }) {
  if (!items || !items.length) return null;
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Campaign health</div></div><b>{items.length}</b></div>
    <div className="dc-alert-list">{items.map((p, i) => <div key={i} style={{ alignItems: "flex-start" }}>
      <NvUrgency level={p.urgency} />
      <div><b>{p.title}</b><small style={{ display: "block", marginTop: 2, opacity: .85 }}>{p.why}</small></div>
    </div>)}</div>
  </div>;
}

function NvCreative({ items }) {
  if (!items || !items.length) return null;
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Creative recommendations</div><div className="faint">Which angle needs fresh work</div></div><b>{items.length}</b></div>
    <div className="dc-alert-list">{items.map((c, i) => <div key={i}><span className="dc-severity" style={{ background: "#8B5CF6" }} /><div><b style={{ fontWeight: 500 }}>{c.angle}</b><small style={{ display: "block", opacity: .85 }}>{c.why}</small><small style={{ display: "block", opacity: .6 }}>→ {c.action}</small></div></div>)}</div>
  </div>;
}

function DaycareAdOpsAgent() {
  const [busy, setBusy] = useStateNv(false);
  const [learning, setLearning] = useStateNv(false);
  const [err, setErr] = useStateNv(null);
  const ov = window.DcxUseResource("/adops/overview", "dc-nova", 15000);
  const bus = window.DcxUseResource("/adops/bus", "dc-nova-bus", 15000);
  const data = ov.data || {};
  const brief = data.brief || null;
  const learn = data.learn || {};
  const activity = data.activity || [];
  const messages = (bus.data && bus.data.messages) || [];

  const run = async () => {
    setBusy(true); setErr(null);
    try { await window.DcxRequest("/adops/run", { body: {} }); ov.refresh(); bus.refresh(); }
    catch (e) { setErr((e && e.message) || "Brief failed."); }
    finally { setBusy(false); }
  };
  const doLearn = async () => {
    setLearning(true); setErr(null);
    try { await window.DcxRequest("/adops/learn", { body: {} }); ov.refresh(); bus.refresh(); }
    catch (e) { setErr((e && e.message) || "Learn failed."); }
    finally { setLearning(false); }
  };

  const briefAgo = data.lastBriefAt ? window.DcxDate(data.lastBriefAt, true) : "never";
  const campaign = (brief && brief.campaign) || {};
  const competitor = (brief && brief.competitorRead) || {};

  return <div className="dc-page">
    <div className="dc-hero" style={{ marginBottom: 14 }}>
      <div>
        <div className="dc-eyebrow">ROLE AGENT · AD OPS</div>
        <h1>Nova</h1>
        <p>Runs point on ads — campaign health, competitor intel, and which live creative angle needs fresh work — grounded in the real Meta account &amp; the Higgsfield→Pipeboard workflow. She reports to Solomon and recommends only; launching, spending, and generating creative stay your call.</p>
        <div className="dc-hero-actions">
          <button className="dc-primary" onClick={run} disabled={busy}><window.Icons.Trend size={15} /> {busy ? "Nova is reviewing…" : "Build ad ops brief"}</button>
          <button className="dc-outline" onClick={doLearn} disabled={learning} style={{ borderColor: "rgba(139,92,246,.5)", color: "#C4B5FD" }}><window.Icons.Brain size={15} /> {learning ? "Learning…" : "Learn from brain"}</button>
        </div>
      </div>
    </div>

    <div className="dc-kpi-grid">
      <window.DcxKpi label="Scoring" value={data.aiReady ? "Claude" : "no key"} sub={data.aiReady ? "live model" : "add a key"} icon="Bot" color={data.aiReady ? "#22C55E" : "#F4B860"} />
      <window.DcxKpi label="Playbook" value={data.skillsLoaded ? "Loaded" : "—"} sub="from the brain" icon="Brain" color="#8B5CF6" />
      <window.DcxKpi label="Self-improved" value={learn.learnCount || 0} sub={"×  · " + (brief ? (brief.campaignHealth || []).length + " campaign items" : "no brief yet")} icon="Trend" color="#38BDF8" />
      <window.DcxKpi label="Last brief" value={data.briefCount || 0} sub={briefAgo} icon="Doc" />
    </div>

    <div className="dc-form-hint" style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
      <span style={{ opacity: .7 }}>Meta Ads:</span>
      <NvChip ok={campaign.connected} label={campaign.connected ? "connected" : "not connected (mock data)"} />
    </div>

    <window.DcxState loading={ov.loading && !brief} error={err} onRetry={run} />

    {!brief && !busy && <div className="dc-all-clear"><window.Icons.Trend size={22} /><div><b>No brief yet</b><span>Tap “Build ad ops brief” — Nova reads campaign health + the competitor read and recommends what needs attention.</span></div></div>}

    {brief && <div className="card card-pad dc-panel" style={{ borderColor: "rgba(45,212,191,.35)" }}>
      <div className="dc-panel-head"><div><div className="dc-eyebrow">AD OPS BRIEF</div><div className="card-title" style={{ fontSize: 18 }}>{brief.headline}</div></div><NvChip ok={brief.contextLoaded} label={brief.contextLoaded ? "brief read" : "no brief"} /></div>
      {competitor.summary && <p className="faint" style={{ marginTop: 8 }}>{competitor.summary}</p>}
    </div>}

    {brief && <div className="dc-main-grid">
      <NvCampaignHealth items={brief.campaignHealth} />
      <NvCreative items={brief.creativeRecommendations} />
    </div>}

    {brief && brief.delegationsSeen && brief.delegationsSeen.length > 0 && <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Picked up from Solomon</div><div className="faint">Delegations she acted on this brief</div></div><b>{brief.delegationsSeen.length}</b></div>
      <div className="dc-alert-list">{brief.delegationsSeen.map((d, i) => <div key={i}><span className="dc-severity" style={{ background: "#8B5CF6" }} /><div><b style={{ fontWeight: 500 }}>{d}</b></div></div>)}</div>
    </div>}

    <div className="dc-main-grid">
      <div className="card card-pad dc-panel">
        <div className="dc-panel-head"><div><div className="card-title">Activity</div><div className="faint">Nova’s recent work</div></div></div>
        {activity.length ? <div className="dc-alert-list">{activity.slice(0, 10).map((a, i) => <div key={i}><span className="dc-severity info" /><div><b style={{ fontWeight: 500 }}>{a.text}</b><small style={{ display: "block", opacity: .6 }}>{a.kind + " · " + window.DcxDate(a.ts, true)}</small></div></div>)}</div> : <div className="dc-inline-empty">No activity yet.</div>}
      </div>
      <div className="card card-pad dc-panel">
        <div className="dc-panel-head"><div><div className="card-title">Agent comms</div><div className="faint">Nova ↔ Solomon on the bus</div></div></div>
        {messages.length ? <div className="dc-alert-list">{messages.slice(0, 10).map((m, i) => <div key={m.id || i}><span className="dc-severity" style={{ background: m.kind === "handoff" ? "#8B5CF6" : m.kind === "alert" ? "#EF4444" : "#22C55E" }} /><div><b style={{ fontWeight: 500 }}>{m.text}</b><small style={{ display: "block", opacity: .6 }}>{m.from + " → " + m.to + " · " + m.kind}</small></div></div>)}</div> : <div className="dc-inline-empty">No messages yet.</div>}
      </div>
    </div>
  </div>;
}

Object.assign(window, { DaycareAdOpsAgent });
