// Agency and daycare mobile views. UI calls existing same-origin routes only.
const { useState: useStateMW } = React;

function MWMetric(props) {
  return <div className="mw-metric"><b>{props.value}</b><span>{props.label}</span></div>;
}

function MWAgency() {
  const calls = window.useApiM("/api/agency/calls", { interval: 30000 });
  const sheet = window.useApiM("/api/agency/callsheet", { interval: 60000 });
  const [busy, setBusy] = useStateMW(false);
  const [filter, setFilter] = useStateMW("Due now");
  const [notice, setNotice] = useStateMW("");
  const today = calls.data && calls.data.today || {};
  const rows = sheet.data && (sheet.data.rows || sheet.data.leads || sheet.data.calls || []) || [];
  const due = rows.filter((r) => filter !== "Due now" || r.dueNow || r.status === "callback" || r.callbackDue);
  async function log(outcome) {
    setBusy(true); setNotice("");
    try { await window.apiPostM("/api/agency/calls/log", { outcome }); calls.refresh(); }
    catch (e) { setNotice("Call tally unavailable — retry."); }
    setBusy(false);
  }
  async function mark(row, status) {
    try { await window.apiPostM("/api/agency/callsheet/status", { id: row.id, status }); sheet.refresh(); calls.refresh(); }
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
        <div className="m-seg">{["Due now","All"].map((f)=><window.MChip key={f} active={filter===f} onClick={()=>setFilter(f)}>{f}</window.MChip>)}</div>
        <div className="mw-list">
          {sheet.loading && !sheet.data ? <window.MSpin/> : !sheet.error && due.length ? due.map((r)=><div className="mw-lead" key={r.id || r.phone}>
            <div className="mw-lead-main"><b>{r.name || r.company || "Prospect"}</b><small>{r.company && r.name ? r.company + " · " : ""}{r.callbackAt ? "Callback · " + r.callbackAt : (r.status || "New")}</small></div>
            {r.phone && <a className="mw-call" href={"tel:" + r.phone}>Call</a>}
            <button className="mw-mark" onClick={()=>mark(r,"answered")} aria-label="Mark answered">✓</button>
          </div>) : !sheet.error ? <window.MEmpty title={filter === "Due now" ? "No callbacks due" : "Your call sheet is ready"} sub="Add leads from the desktop call center."/> : null}
        </div>
        <div className="mw-desktop-hint">Import a lead list from the desktop Call Center.</div>
      </window.MCard>
    </div>
  </React.Fragment>;
}

function MWDaycare() {
  const leads = window.useApiM("/api/daycare/leads", { interval: 60000 });
  const brief = window.useApiM("/api/daycare/director/brief", { interval: 60000 });
  const [notice, setNotice] = useStateMW("");
  const data = leads.data || {};
  const needs = data.needsHuman || data.needs_human || data.needsHumanList || [];
  const stages = data.stages || {};
  const auth = leads.error && /401|403|unauthor/i.test(String(leads.error));
  async function stage(row) {
    const next = prompt("Move this lead to which stage? (TOUR_BOOKED, TOUR_COMPLETED, APPLICATION, ENROLLED, LOST)");
    if (!next) return;
    if (!window.confirm("Save this stage locally for " + (row.parentName || "this lead") + "?")) return;
    try { await window.apiPostM("/api/daycare/leads/stage", { contactId: row.contactId || row.id, stage: next.trim().toUpperCase() }); leads.refresh(); }
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
          <div className="mw-stats mw-stage-stats">{["newLeads","needsHuman","tourBooked","tourCompleted","application","enrolled"].map((k,i)=><MWMetric key={k} label={["New","Needs you","Tour booked","Tour complete","Application","Enrolled"][i]} value={stages[k] ?? stages[k.replace(/[A-Z]/g,(c)=>"_"+c.toLowerCase())] ?? "—"}/>)}</div>
          {data.avgResponseTime && <div className="mw-response">Average response · {data.avgResponseTime}</div>}
        </window.MCard>
        <window.MCard title="Needs a human" right={<span className="mw-streak">{needs.length}</span>}>
          {needs.length ? needs.map((r)=><div className="mw-lead" key={r.contactId || r.id}>
            <div className="mw-lead-main"><b>{r.parentName || r.name || "Family lead"}</b><small>{[r.center,r.stage,r.waiting || r.age].filter(Boolean).join(" · ")}</small></div>
            {r.phone && <a className="mw-call" href={"tel:"+r.phone}>Call</a>}
            <button className="mw-mark" onClick={()=>stage(r)} aria-label="Mark lead stage">•••</button>
          </div>) : <window.MEmpty title="No follow-ups waiting" sub="New leads that need a person will show here."/>}
        </window.MCard>
      </>}
      {notice && <div className="mw-warn">{notice}</div>}
      <window.MCard title="Solomon's brief" right={<span className="mw-streak">READ ONLY</span>}>
        {brief.loading && !brief.data ? <window.MSpin/> : brief.error ? <div className="mw-warn">Solomon's brief unavailable — retry.</div> : <div className="mw-brief">{(brief.data && (brief.data.sections || brief.data.brief?.sections) || []).map((s,i)=><section key={i}><b>{s.title || s.heading || "Update"}</b><p>{s.body || s.text || s.content || ""}</p></section>)}{!brief.data?.sections?.length && <p>{brief.data?.text || brief.data?.brief?.text || "No brief available yet."}</p>}</div>}
      </window.MCard>
    </div>
  </React.Fragment>;
}

Object.assign(window, { MWAgency, MWDaycare });
