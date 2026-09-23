// Agency and daycare mobile views. UI calls existing same-origin routes only.
const { useState: useStateMW } = React;

function MWMetric(props) {
  return <div className="mw-metric"><b>{props.value}</b><span>{props.label}</span></div>;
}

function MPToday() {
  const actions = window.useApiM("/api/owner-actions", { interval: 60000 });
  const mission = window.useApiM("/api/mission-control", { interval: 30000 });
  const registry = window.useApiM("/api/agents/registry", { interval: 60000 });
  const items = actions.data && !actions.data.error && Array.isArray(actions.data.items) ? actions.data.items : [];
  const businesses = mission.data && Array.isArray(mission.data.businesses) ? mission.data.businesses : [];
  function jump(biz) {
    const id = String(biz || "").toLowerCase();
    window.mGoTab(id.includes("agency") ? "agency" : id.includes("daycare") ? "daycare" : "wholesale");
  }
  return <React.Fragment>
    <window.MHeader title="FORGE Today" sub="Your business, at a glance" right={<button className="mw-header-bot" onClick={()=>window.mGoTab("agents")} aria-label="Open agents">🤖</button>} />
    <div className="m-content mw-page">
      <section className="mw-hero today"><div className="mw-eyebrow">YOUR DAILY DASHBOARD</div><h1>Hey, boss.<br/>Here’s the big picture.</h1><p>Quick actions for Wholesale, Agency and Daycare.</p><div className="mw-mascot-note"><window.MForgePal size={58}/><span>Your crew is on it!</span></div></section>
      <window.MCard title="Needs you" right={<span className="mw-streak">{actions.loading && !actions.data ? "…" : actions.error ? "Retry" : items.length + " actions"}</span>}>
        {actions.loading && !actions.data ? <window.MSpin/> : actions.error ? <div className="mw-warn">Owner actions unavailable — retry.</div> : !items.length ? <window.MEmpty title="All clear" sub="Nothing needs your attention right now."/> : items.slice(0,3).map((it)=><div className="mw-action" key={it.id}>
          <span className="mw-action-kind">{it.kind || "REVIEW"}</span><div className="mw-lead-main"><b>{it.title || "Needs review"}</b><small>{it.why || it.business || ""}</small></div>
          {it.phone && (it.kind === "CALL" || it.kind === "CALLBACK") ? <a className="mw-call" href={"tel:"+it.phone}>Call</a> : <button className="mw-mark" onClick={()=>jump(it.business || (it.link && it.link.ws))} aria-label="Open action">›</button>}
        </div>)}
        {items.length > 3 && <button className="mw-all-actions" onClick={()=>window.mGoTab("actions")}>See all {items.length} actions →</button>}
      </window.MCard>
      <div className="m-section"><span className="m-section-l">Your businesses</span><span className="m-section-line"/></div>
      {mission.loading && !mission.data ? <window.MCard><window.MSpin/></window.MCard> : mission.error ? <div className="mw-warn">Business overview unavailable — retry.</div> : businesses.map((b)=><div className="mw-business-wrap" key={b.id}>
        <button className="mw-business" onClick={()=>jump(b.id)} style={{"--biz":b.accent || "#4F7CFF"}}><span className="mw-business-icon">{b.id === "daycare" ? "♥" : b.id === "agency" ? "✳" : "⌂"}</span><span className="mw-business-copy"><b>{b.name}</b><small>{b.tag || b.statusLabel || "Open workspace"}</small>{b.metrics && <small>{b.metrics.slice(0,3).map((m)=>m.label + " " + m.value).join(" · ")}</small>}</span><span className="mw-business-go">›</span></button>
        {(b.attention || []).filter((a)=>a.sev === "warn").map((a,i)=><div className="mw-warn" key={i}>{a.text}</div>)}
      </div>)}
      {registry.error ? <div className="mw-warn">Agent roster unavailable — retry.</div> : registry.data && <button className="mw-agent-strip" onClick={()=>window.mGoTab("agents")}><span>🤖</span><b>Agent crew</b><small>{(registry.data.agents || registry.data.items || []).length} agents · View roster</small><i>›</i></button>}
    </div>
  </React.Fragment>;
}

function MWAgency() {
  const calls = window.useApiM("/api/agency/calls", { interval: 30000 });
  const sheet = window.useApiM("/api/agency/callsheet", { interval: 60000 });
  const [busy, setBusy] = useStateMW(false);
  const [filter, setFilter] = useStateMW("Due now");
  const [query, setQuery] = useStateMW("");
  const [statusLead, setStatusLead] = useStateMW(null);
  const [notice, setNotice] = useStateMW("");
  const today = calls.data && calls.data.today || {};
  const rows = sheet.data && (sheet.data.rows || sheet.data.leads || sheet.data.calls || []) || [];
  const due = rows.filter((r) => {
    const callbackTime = Date.parse(r.callbackAt || "");
    const dueNow = r.dueNow || r.callbackDue || (r.status === "callback" && (!callbackTime || callbackTime <= Date.now()));
    return (filter !== "Due now" || dueNow) && (!query || [r.name,r.company,r.phone].join(" ").toLowerCase().includes(query.toLowerCase()));
  });
  async function log(outcome) {
    setBusy(true); setNotice("");
    try { await window.apiPostM("/api/agency/calls/log", { outcome }); calls.refresh(); }
    catch (e) { setNotice("Call tally unavailable — retry."); }
    setBusy(false);
  }
  async function mark(row, status) {
    try { await window.apiPostM("/api/agency/callsheet/status", { id: row.id, status }); sheet.refresh(); calls.refresh(); setStatusLead(null); }
    catch (e) { setNotice("Call sheet unavailable — retry."); }
  }
  return <React.Fragment>
    <window.MHeader title="Agency" sub="ClientForge · Call Center" />
    <div className="m-content mw-page">
      <section className="mw-hero agency">
        <div className="mw-eyebrow">YOUR NEXT CALL</div>
        <h1>Small steps.<br/>Big momentum.</h1>
        <p>Make a call, mark the outcome, keep your streak alive.</p>
        <div className="mw-mascot-note"><window.MForgePal size={56}/><span>Let’s make today count!</span></div>
      </section>
      {calls.error && <div className="mw-warn">Call tally unavailable — retry.</div>}
      {sheet.error && <div className="mw-warn">Agency call sheet unavailable — retry.</div>}
      <window.MCard title="Today's progress" right={<span className="mw-streak">🔥 {calls.data ? calls.data.streak || 0 : "—"} day streak</span>}>
        {calls.loading && !calls.data ? <window.MSpin/> : calls.error ? null : <>
          <div className="mw-stats"><MWMetric label="Dials" value={today.dials ?? 0}/><MWMetric label="Answered" value={today.answered ?? 0}/><MWMetric label="No answer" value={today.no_answer ?? 0}/></div>
          <div className="mw-goal"><span style={{width: Math.min(100, (today.dials || 0) / Math.max(1, calls.data.goal || 1) * 100) + "%"}}/></div>
          <div className="mw-goal-label">{today.dials || 0} of {calls.data.goal || 0} calls today</div>
          <div className="mw-call-buttons"><window.MBtn kind="ok" disabled={busy} onClick={() => log("answered")}>✓ Answered</window.MBtn><window.MBtn kind="ghost" disabled={busy} onClick={() => log("no_answer")}>↗ No answer</window.MBtn></div>
          <button className="mw-undo" disabled={busy} onClick={async()=>{setBusy(true);try{await window.apiPostM("/api/agency/calls/undo",{});calls.refresh();}catch(e){setNotice("Undo unavailable — retry.");}setBusy(false);}}>Undo last call</button>
        </>}
      </window.MCard>
      {notice && <div className="mw-warn">{notice}</div>}
      <window.MCard title="Call sheet" right={<span className="m-fade">{rows.length} leads</span>}>
        <input className="m-input" value={query} placeholder="Search names or phone" onChange={(e)=>setQuery(e.target.value)} />
        <div className="m-seg">{["Due now","All"].map((f)=><window.MChip key={f} active={filter===f} onClick={()=>setFilter(f)}>{f}</window.MChip>)}</div>
        <div className="mw-list">
          {sheet.loading && !sheet.data ? <window.MSpin/> : !sheet.error && due.length ? due.map((r)=><div className="mw-lead" key={r.id || r.phone}>
            <div className="mw-lead-main"><b>{r.name || r.company || "Prospect"}</b><small>{r.company && r.name ? r.company + " · " : ""}{r.callbackAt ? "Callback · " + r.callbackAt : (r.status || "New")}</small></div>
            {r.phone && <a className="mw-call" href={"tel:" + r.phone}>Call</a>}
            <button className="mw-mark" onClick={()=>setStatusLead(r)} aria-label="Update call status">•••</button>
          </div>) : !sheet.error ? <window.MEmpty title={filter === "Due now" ? "No callbacks due" : "Your call sheet is ready"} sub="Add leads from the desktop call center."/> : null}
        </div>
        <div className="mw-desktop-hint">Import a lead list from the desktop Call Center.</div>
      </window.MCard>
    </div>
    {statusLead && <div className="m-sheet"><div className="m-sheet-head"><button className="m-tab" onClick={()=>setStatusLead(null)}>‹</button><b style={{flex:1}}>Update call status</b></div><div className="m-sheet-body"><div className="m-card"><b>{statusLead.name || statusLead.company || "Prospect"}</b><div className="m-fade" style={{marginTop:4}}>Choose the outcome for this call.</div></div>{[["new","New"],["answered","Answered"],["no_answer","No answer"],["callback","Call back"],["dead","Move on"]].map(([value,label])=><button key={value} className="mw-stage-choice" onClick={()=>mark(statusLead,value)}>{label}</button>)}<window.MBtn kind="ghost" onClick={()=>setStatusLead(null)}>Cancel</window.MBtn></div></div>}
  </React.Fragment>;
}

function MWDaycare() {
  const leads = window.useApiM("/api/daycare/leads", { interval: 60000 });
  const brief = window.useApiM("/api/daycare/director/brief", { interval: 60000 });
  const [notice, setNotice] = useStateMW("");
  const [stageLead, setStageLead] = useStateMW(null);
  const [stageValue, setStageValue] = useStateMW("TOUR_BOOKED");
  const data = leads.data || {};
  const needs = Array.isArray(data.needsHuman) ? data.needsHuman : [];
  const kpis = data.kpis || {};
  const stages = kpis.pipeline || kpis.stages || {};
  const auth = leads.error && /401|403|unauthor/i.test(String(leads.error));
  async function stage() {
    if (!stageLead || !window.confirm("Save this stage locally? It will not update GoHighLevel.")) return;
    try { await window.apiPostM("/api/daycare/leads/stage", { contactId: stageLead.contactId || stageLead.id, stage: stageValue }); leads.refresh(); setStageLead(null); }
    catch (e) { setNotice("Daycare stage unavailable — retry."); }
  }
  return <React.Fragment>
    <window.MHeader title="Daycare" sub="A Touch of Blessings · Lead Desk" />
    <div className="m-content mw-page">
      <section className="mw-hero daycare">
        <div className="mw-eyebrow">A LITTLE CARE GOES A LONG WAY</div>
        <h1>Growing with<br/>every family.</h1>
        <p>See which families need a personal follow-up today.</p>
        <div className="mw-mascot-note"><window.MForgePal size={56}/><span>One kind call at a time.</span></div>
      </section>
      {auth ? <div className="mw-warn">Daycare needs a session — open the desktop Daycare tab once.</div> : leads.error ? <div className="mw-warn">Daycare leads unavailable — retry.</div> : null}
      {leads.loading && !leads.data ? <window.MCard><window.MSpin/></window.MCard> : !leads.error && <>
        <window.MCard title="Lead stages">
          <div className="mw-stats mw-stage-stats"><MWMetric label="New leads · 7d" value={kpis.newLeads7d ? kpis.newLeads7d.total : "—"}/><MWMetric label="Needs you" value={kpis.needsHuman ?? "—"}/>{[["TOUR_BOOKED","Tour booked"],["TOUR_COMPLETED","Tour complete"],["APPLICATION","Application"],["ENROLLED","Enrolled"]].map(([key,label])=><MWMetric key={key} label={label} value={stages[key] ?? "—"}/>)}</div>
          <div className="mw-response">Median human response · {kpis.medianHumanResponseSec == null ? "—" : Math.max(1, Math.round(kpis.medianHumanResponseSec/60)) + " min"}</div>
        </window.MCard>
        <window.MCard title="Needs a human" right={<span className="mw-streak">{needs.length}</span>}>
          {needs.length ? needs.map((r)=><div className="mw-lead" key={r.contactId || r.id}>
            <div className="mw-lead-main"><b>{r.parentName || r.name || "Family lead"}</b><small>{[r.center,r.stage,r.waiting || r.age].filter(Boolean).join(" · ")}</small></div>
            {r.phone && <a className="mw-call" href={"tel:"+r.phone}>Call</a>}
            <button className="mw-mark" onClick={()=>{setStageLead(r);setStageValue("TOUR_BOOKED");}} aria-label="Mark lead stage">•••</button>
          </div>) : <window.MEmpty title="No follow-ups waiting" sub="New leads that need a person will show here."/>}
        </window.MCard>
      </>}
      {notice && <div className="mw-warn">{notice}</div>}
      <window.MCard title="Solomon's brief" right={<span className="mw-streak">READ ONLY</span>}>
        {brief.loading && !brief.data ? <window.MSpin/> : brief.error ? <div className="mw-warn">Solomon's brief unavailable — retry.</div> : <div className="mw-brief">{(brief.data && (brief.data.sections || brief.data.brief?.sections) || []).map((s,i)=><section key={i}><b>{s.title || s.heading || "Update"}</b><p>{s.body || s.text || s.content || ""}</p></section>)}{!brief.data?.sections?.length && <p>{brief.data?.text || brief.data?.brief?.text || "No brief available yet."}</p>}</div>}
      </window.MCard>
    </div>
    {stageLead && <div className="m-sheet"><div className="m-sheet-head"><button className="m-tab" onClick={()=>setStageLead(null)}>‹</button><b style={{flex:1}}>Update lead stage</b></div><div className="m-sheet-body"><div className="m-card"><b>{stageLead.parentName || stageLead.name || "Family lead"}</b><div className="m-fade" style={{marginTop:4}}>This is a local mobile note. It does not update GoHighLevel.</div></div>{["TOUR_BOOKED","TOUR_COMPLETED","APPLICATION","ENROLLED","LOST"].map((s)=><button key={s} className={"mw-stage-choice"+(stageValue===s?" active":"")} onClick={()=>setStageValue(s)}>{s.replaceAll("_"," ")}{stageValue===s?" ✓":""}</button>)}<window.MBtn kind="ok" onClick={stage}>Confirm stage</window.MBtn><window.MBtn kind="ghost" onClick={()=>setStageLead(null)}>Cancel</window.MBtn></div></div>}
  </React.Fragment>;
}

Object.assign(window, { MPToday, MWAgency, MWDaycare });
