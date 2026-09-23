// FORGE Mobile — business portal: DAYCARE (A Touch of Blessings).
// Owner lens only — the things that matter, nothing else. Same-origin /api/* only;
// the connector holds every key (daycare.env, Supabase, GHL, Stripe).
// Hook aliases for this file: BD. Top-level names: MBD*. Exports: MBDHome,
// MBDFamilies, MBDSolomon, MBDMoney + window.M_BIZ.daycare.
//
// Endpoints (all session-gated; the box auto-admins Tailscale Serve traffic):
//   GET  /api/daycare/leads                 Lead Desk: kpis, leads, needsHuman (state only, no GHL call)
//   GET  /api/daycare/overview              live Supabase ops metrics (enrolled, capacity, present, invoices)
//   GET  /api/daycare/director/brief        Solomon's last operating brief (read-only)
//   GET  /api/daycare/ghl/pending-families  Contact-Form inbox — READ-ONLY, loaded only on the Families tab
//   GET  /api/daycare/billing               invoices + payments (Money tab, read-only)
//   POST /api/daycare/leads/stage           {contact_id, stage} — local mark, never GHL, never a family
//   POST /api/daycare/ghl/enroll            {family} — ONLY on explicit tap + window.confirm (writes Supabase + GHL)
// No family texting, invoicing, blasts or ad actions from this side (CLAUDE.md rule 2).
const { useState: useStateBD } = React;

const MBD_STAGES = [["TOUR_BOOKED", "Tour booked"], ["TOUR_COMPLETED", "Tour complete"],
  ["APPLICATION", "Application"], ["ENROLLED", "Enrolled"], ["LOST", "Lost"]];
const MBD_AUTH_CODES = ["session_expired", "authentication_required", "https_required", "forbidden",
  "management_required", "profile_missing", "inactive_account", "location_mismatch", "origin_rejected"];

// useApiM puts a daycare error payload in both .data ({ok:false,code}) and .error.
function MBDAuth(res) {
  const d = res && res.data;
  return !!(d && d.ok === false && MBD_AUTH_CODES.includes(d.code))
    || /\b40[13]\b|session expired|login is required/i.test(String((res && res.error) || ""));
}
// Lead Desk returns ok:true WITH an error string when a sweep failed / never ran —
// that is stale data (warn), not a failed load.
function MBDFailed(res) { return !!(res && res.error) && !(res.data && res.data.ok === true); }
function MBDAuthLine() {
  return <div className="mw-warn">Daycare session needed — open the desktop Daycare tab once.</div>;
}
function MBDMetric(props) {
  return <div className="mw-metric"><b>{props.value}</b><span>{props.label}</span></div>;
}
function MBDAgo(ts) { const a = window.timeAgoM(ts); return !a ? "" : a === "now" ? "just now" : a + " ago"; }
function MBDDur(sec) {
  if (sec == null) return "—";
  return sec < 3600 ? Math.max(1, Math.round(sec / 60)) + " min" : (sec / 3600).toFixed(1) + " h";
}
function MBDLine(x) {
  if (x == null) return "";
  if (typeof x !== "object") return String(x);
  const head = x.title || x.family || x.angle || x.role || x.summary || "";
  const tail = x.why || x.reason || x.task || x.gap || "";
  const next = x.action || x.suggestedNextStep || "";
  return [head, tail].filter(Boolean).join(" — ") + (next ? " → " + next : "");
}
function MBDGo(tab) { if (window.mGoTab) window.mGoTab(tab); }

// Needs-a-human rows joined with the lead record (name, stage) and — when the
// Contact-Form inbox is loaded — the family's phone. Lead Desk itself carries no phone.
function MBDNeeds(leadsData, families) {
  const d = leadsData || {};
  const byId = {};
  (Array.isArray(d.leads) ? d.leads : []).forEach((l) => { byId[l.contactId] = l; });
  const phones = {};
  (families || []).forEach((f) => { if (f.contact_id && f.phone) phones[f.contact_id] = f.phone; });
  return (Array.isArray(d.needsHuman) ? d.needsHuman : []).map((n) => {
    const lead = byId[n.contactId] || {};
    return Object.assign({}, n, {
      name: lead.parentName || "New family",
      stage: lead.stage,
      phone: phones[n.contactId] || "",
    });
  });
}

function MBDNeedRow(props) {
  const r = props.row;
  const stage = MBD_STAGES.find(([k]) => k === r.stage);
  const sub = [r.center, stage && stage[1], r.why,
    r.ageSec != null ? MBDAgo(Date.now() - r.ageSec * 1000).replace(" ago", " waiting") : ""]
    .filter(Boolean).join(" · ");
  return <div className="mw-lead">
    <div className="mw-lead-main"><b>{r.name}</b><small>{sub}</small></div>
    {r.phone ? <a className="mw-call" href={"tel:" + r.phone}>Call</a>
      : r.ghlUrl && props.onMark ? <a className="mw-call" href={r.ghlUrl} target="_blank" rel="noreferrer">GHL</a> : null}
    {props.onMark
      ? <button className="mw-mark" onClick={() => props.onMark(r)} aria-label="Mark lead stage">•••</button>
      : <button className="mw-mark" onClick={() => MBDGo("families")} aria-label="Open families">›</button>}
  </div>;
}

// ---------------------------------------------------------------- Home
function MBDHome() {
  const leads = window.useApiM("/api/daycare/leads", { interval: 60000 });
  const ov = window.useApiM("/api/daycare/overview", { interval: 120000 });
  const brief = window.useApiM("/api/daycare/director/brief", { interval: 120000 });
  const auth = MBDAuth(leads) || MBDAuth(ov) || MBDAuth(brief);
  const ld = leads.data && leads.data.ok ? leads.data : null;
  const ran = !!(ld && ld.lastRunAt);                      // desk never ran → counts are Unknown, not 0
  const kpis = (ld && ld.kpis) || {};
  const m = (ov.data && ov.data.ok && ov.data.metrics) || null;
  const b = (brief.data && brief.data.ok && brief.data.brief) || null;
  const needs = ran ? MBDNeeds(ld, null) : [];
  const alerts = ((ov.data && ov.data.ok && ov.data.alerts) || []).filter((a) => a.level === "warning");
  const enrolled = !m ? "—" : m.capacityTotal > 0 ? m.childrenActive + "/" + m.capacityTotal : m.childrenActive;
  return <React.Fragment>
    <window.MHeader title="Daycare" sub="A Touch of Blessings" />
    <div className="m-content mw-page">
      <section className="mw-hero daycare">
        <div className="mw-eyebrow">A LITTLE CARE GOES A LONG WAY</div>
        <h1>Growing with<br/>every family.</h1>
        <p>Who needs you, what Solomon sees, and how the center is doing.</p>
        <div className="mw-mascot-note"><window.MForgePal size={56}/><span>One kind call at a time.</span></div>
      </section>
      {auth && <MBDAuthLine/>}
      <window.MCard title="Today at the center">
        <div className="mw-stats" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))" }}>
          <MBDMetric label="New leads · 7d" value={ran && kpis.newLeads7d ? kpis.newLeads7d.total : "—"}/>
          <MBDMetric label="Need you" value={ran && kpis.needsHuman != null ? kpis.needsHuman : "—"}/>
          <MBDMetric label={m && m.capacityTotal > 0 ? "Enrolled / capacity" : "Enrolled"} value={enrolled}/>
          <MBDMetric label="Here today" value={m ? m.presentToday : "—"}/>
        </div>
        {!auth && MBDFailed(leads) && <div className="mw-warn">Lead Desk unavailable — retry.</div>}
        {!auth && ld && ld.error && <div className="mw-warn">Lead Desk: {ld.error}</div>}
        {!auth && MBDFailed(ov) && <div className="mw-warn">Center metrics unavailable — retry.</div>}
        {alerts.map((a, i) => <div className="mw-warn" key={i} style={{ marginTop: 6 }}>{a.title}</div>)}
        {m && m.invoicesDue > 0 && <button className="mw-all-actions" style={{ marginTop: 8 }} onClick={() => MBDGo("money")}>
          {m.invoicesDue} invoice{m.invoicesDue === 1 ? "" : "s"} due →</button>}
      </window.MCard>
      <window.MCard title="Needs you" right={<span className="mw-streak">{ran ? needs.length : "—"}</span>}>
        {leads.loading && !leads.data ? <window.MSpin/> : !ld ? null : !ran ? <div className="m-fade">Lead Desk hasn't swept yet.</div>
          : !needs.length ? <window.MEmpty title="No families waiting" sub="New leads that need a person show here."/>
          : needs.slice(0, 3).map((r) => <MBDNeedRow key={r.id} row={r}/>)}
        {needs.length > 0 && <button className="mw-all-actions" onClick={() => MBDGo("families")}>See all {needs.length} →</button>}
      </window.MCard>
      <window.MCard title="Solomon says" right={b && brief.data.lastBriefAt ? <span className="m-fade">{MBDAgo(brief.data.lastBriefAt)}</span> : null}>
        {brief.loading && !brief.data ? <window.MSpin/> : !auth && MBDFailed(brief) ? <div className="mw-warn">Solomon's brief unavailable — retry.</div>
          : !(brief.data && brief.data.ok) ? null : !b ? <div className="m-fade">No brief yet — Solomon writes one daily on the box.</div>
          : <React.Fragment>
            <div style={{ fontSize: 14, fontWeight: 800, lineHeight: 1.35, marginBottom: 6 }}>{b.headline}</div>
            {(b.priorities || []).slice(0, 3).map((p, i) => <div className="mw-action" key={i}>
              <span className="mw-action-kind">{String(p.urgency || p.area || "NOW").toUpperCase()}</span>
              <div className="mw-lead-main"><b>{p.title || MBDLine(p)}</b><small>{p.why || ""}</small></div>
            </div>)}
            <button className="mw-all-actions" onClick={() => MBDGo("solomon")}>Full brief →</button>
          </React.Fragment>}
      </window.MCard>
    </div>
  </React.Fragment>;
}

// ---------------------------------------------------------------- Families
function MBDStageSheet(props) {
  const r = props.row;
  const [pick, setPick] = useStateBD(MBD_STAGES.some(([k]) => k === r.stage) ? r.stage : "TOUR_BOOKED");
  const [busy, setBusy] = useStateBD(false);
  const [err, setErr] = useStateBD("");
  async function save(stage) {
    setBusy(true); setErr("");
    try { await window.apiPostM("/api/daycare/leads/stage", { contact_id: r.contactId, stage }); props.onDone(); }
    catch (e) { setErr("Couldn't save the mark — " + ((e && e.message) || "retry") + "."); setBusy(false); }
  }
  return <div className="m-sheet">
    <div className="m-sheet-head"><button className="m-tab" onClick={props.onClose}>‹</button><b style={{ flex: 1 }}>Mark lead stage</b></div>
    <div className="m-sheet-body">
      <div className="m-card"><b>{r.name}</b><div className="m-fade" style={{ marginTop: 4 }}>Local mark only — it doesn't change GoHighLevel or message the family.</div></div>
      {MBD_STAGES.map(([k, label]) => <button key={k} className={"mw-stage-choice" + (pick === k ? " active" : "")} onClick={() => setPick(k)}>{label}{pick === k ? " ✓" : ""}</button>)}
      {err && <div className="mw-warn">{err}</div>}
      <window.MBtn kind="ok" disabled={busy} onClick={() => save(pick)}>{busy ? "Saving…" : "Save mark"}</window.MBtn>
      {MBD_STAGES.some(([k]) => k === r.stage) && <window.MBtn kind="ghost" disabled={busy} onClick={() => save("")}>Clear mark</window.MBtn>}
      <window.MBtn kind="ghost" onClick={props.onClose}>Cancel</window.MBtn>
    </div>
  </div>;
}

// The enroll response carries the parent's one-time PIN exactly once — show it or lose it.
function MBDCredsSheet(props) {
  const p = props.provision || {};
  return <div className="m-sheet">
    <div className="m-sheet-head"><b style={{ flex: 1 }}>{p.existing ? "Parent account linked" : "Save these credentials now"}</b></div>
    <div className="m-sheet-body">
      <div className="m-card">
        <div className="m-fade">Login ID</div><b style={{ fontSize: 18 }}>{p.login_id || "—"}</b>
        {!p.existing && <React.Fragment><div className="m-fade" style={{ marginTop: 10 }}>One-time PIN</div><b style={{ fontSize: 18 }}>{p.pin || "—"}</b></React.Fragment>}
        <div className="m-fade" style={{ marginTop: 10 }}>{p.existing ? "The existing parent account was connected." : "The PIN is shown once and not stored. Hand it to the parent directly — not in notes or messages."}</div>
      </div>
      <window.MBtn kind="ok" onClick={props.onClose}>I saved them</window.MBtn>
    </div>
  </div>;
}

function MBDFamilies() {
  const leads = window.useApiM("/api/daycare/leads", { interval: 60000 });
  // Heavy GHL read (paged contacts + intake notes) — load on this tab only, no poll.
  const inbox = window.useApiM("/api/daycare/ghl/pending-families");
  const [seg, setSeg] = useStateBD("needs");
  const [markRow, setMarkRow] = useStateBD(null);
  const [busyId, setBusyId] = useStateBD("");
  const [notice, setNotice] = useStateBD("");
  const [creds, setCreds] = useStateBD(null);
  const auth = MBDAuth(leads) || MBDAuth(inbox);
  const ld = leads.data && leads.data.ok ? leads.data : null;
  const ran = !!(ld && ld.lastRunAt);
  const kpis = (ld && ld.kpis) || {};
  const pd = inbox.data && inbox.data.ok ? inbox.data : null;
  const families = (pd && Array.isArray(pd.families)) ? pd.families : [];
  const needs = ran ? MBDNeeds(ld, families) : [];
  const activeLoc = (pd && pd.active_location_id) || "";
  const here = families.filter((f) => !f.location_id || String(f.location_id) === String(activeLoc));
  const elsewhere = families.filter((f) => !f.dismissed && !f.in_roster && f.location_id && String(f.location_id) !== String(activeLoc)).length;
  const fresh = here.filter((f) => !f.in_roster && !f.dismissed);
  const toEnroll = fresh.filter((f) => f.enrolled);
  const inquiries = fresh.filter((f) => !f.enrolled);

  async function enroll(f) {
    const child = f.child_name || "this child";
    const who = child + (f.parent_name ? " (parent " + f.parent_name + ")" : "") + (f.location_name ? " at " + f.location_name : "");
    const what = f.child_id
      ? who + " is already on the roster. Link/create the parent's app login and clear this card?"
      : "Enroll " + who + "?";
    if (!window.confirm(what + "\n\nThis writes to the daycare roster, creates the parent's app login if an email is on file, and updates their GoHighLevel contact. No text is sent from here.")) return;
    setBusyId(f.contact_id); setNotice("");
    try {
      const r = await window.apiPostM("/api/daycare/ghl/enroll", { family: f });
      if (r && r.provision) setCreds(r.provision);
      setNotice(child + " enrolled." + (r && r.ghlSync && r.ghlSync.ok === false ? " GHL sync: " + (r.ghlSync.detail || "failed") + "." : ""));
      inbox.refresh();
    } catch (e) { setNotice("Enroll failed — " + ((e && e.message) || "retry") + ". Nothing was sent to the family."); }
    setBusyId("");
  }

  const famRow = (f, action) => <div className="mw-lead" key={f.contact_id}>
    <div className="mw-lead-main"><b>{f.child_name || "Student"}{f.parent_name ? " · " + f.parent_name : ""}</b>
      <small>{[f.location_name || f.location_tag, f.enrolled ? (f.child_id ? "On roster" : "Form · enrolled family") : "Inquiry · not enrolled"].filter(Boolean).join(" · ")}</small></div>
    {f.phone && <a className="mw-call" href={"tel:" + f.phone}>Call</a>}
    {action}
  </div>;

  return <React.Fragment>
    <window.MHeader title="Families" sub="Lead Desk · Contact-Form inbox" />
    <div className="m-content mw-page">
      {auth && <MBDAuthLine/>}
      <div className="m-seg">
        <window.MChip active={seg === "needs"} onClick={() => setSeg("needs")}>Need you{ran ? " · " + needs.length : ""}</window.MChip>
        <window.MChip active={seg === "inbox"} onClick={() => setSeg("inbox")}>Contact form{pd ? " · " + fresh.length : ""}</window.MChip>
      </div>
      {notice && <div className="mw-warn">{notice}</div>}
      {seg === "needs" ? <window.MCard title="Need a human" right={<button className="m-chip" onClick={leads.refresh}>Refresh</button>}>
        {!auth && MBDFailed(leads) && <div className="mw-warn">Lead Desk unavailable — retry.</div>}
        {!auth && ld && ld.error && <div className="mw-warn">Lead Desk: {ld.error}</div>}
        {leads.loading && !leads.data ? <window.MSpin/> : !ld ? null : !ran ? <div className="m-fade">Lead Desk hasn't swept yet.</div>
          : !needs.length ? <window.MEmpty title="No families waiting" sub="New leads that need a person show here."/>
          : <div className="mw-list">{needs.map((r) => <MBDNeedRow key={r.id} row={r} onMark={setMarkRow}/>)}</div>}
        {ran && <div className="mw-response">Median human response (30d) · {MBDDur(kpis.medianHumanResponseSec)}</div>}
        {ran && needs.some((r) => !r.phone) && <div className="mw-desktop-hint">No phone on a row? The Lead Desk doesn't carry one — GHL opens the contact.</div>}
      </window.MCard> : <window.MCard title="From the Contact Form" right={<button className="m-chip" onClick={inbox.refresh}>Refresh</button>}>
        {!auth && MBDFailed(inbox) && <div className="mw-warn">Contact-Form inbox unavailable — retry.</div>}
        {pd && pd.connected === false && <div className="mw-warn">Daycare GoHighLevel isn't connected — the inbox can't load.</div>}
        {inbox.loading && !inbox.data ? <window.MSpin/> : pd && <React.Fragment>
          {pd.connected !== false && !toEnroll.length && !inquiries.length && <window.MEmpty title="All caught up" sub="New form submissions for this center show here."/>}
          {toEnroll.length > 0 && <div className="mw-list">{toEnroll.map((f) => famRow(f,
            <button className="mw-call" disabled={busyId === f.contact_id} onClick={() => enroll(f)}>
              {busyId === f.contact_id ? "…" : f.child_id ? "Finish" : "Enroll"}</button>))}</div>}
          {inquiries.length > 0 && <React.Fragment>
            <div className="m-fade" style={{ marginTop: 12, fontWeight: 700 }}>New inquiries — not enrolled yet · no login</div>
            <div className="mw-list">{inquiries.map((f) => famRow(f, null))}</div>
          </React.Fragment>}
          {elsewhere > 0 && <div className="mw-desktop-hint">{elsewhere} more waiting at other centers — switch center on the desktop to see them.</div>}
        </React.Fragment>}
      </window.MCard>}
    </div>
    {markRow && <MBDStageSheet row={markRow} onClose={() => setMarkRow(null)} onDone={() => { setMarkRow(null); leads.refresh(); }}/>}
    {creds && <MBDCredsSheet provision={creds} onClose={() => setCreds(null)}/>}
  </React.Fragment>;
}

// ---------------------------------------------------------------- Solomon
const MBD_BRIEF_SECTIONS = [["Attention now", "priorities"], ["Enrollment", "enrollment"], ["Money", "money"],
  ["People", "people"], ["Roster", "roster"], ["Family follow-ups", "followUps"],
  ["Campaign health", "campaignHealth"], ["Creative", "creativeRecommendations"], ["Delegations", "delegations"]];

function MBDSolomon() {
  const brief = window.useApiM("/api/daycare/director/brief", { interval: 120000 });
  const b = (brief.data && brief.data.ok && brief.data.brief) || null;
  const at = brief.data && brief.data.lastBriefAt;
  const stale = at && Date.now() - at > 48 * 3600 * 1000;
  const comp = b && b.competitorRead && (b.competitorRead.summary || (typeof b.competitorRead === "string" ? b.competitorRead : ""));
  return <React.Fragment>
    <window.MHeader title="Solomon" sub="Director · operating brief" />
    <div className="m-content mw-page">
      {MBDAuth(brief) ? <MBDAuthLine/> : MBDFailed(brief) ? <div className="mw-warn">Solomon's brief unavailable — retry.</div> : null}
      {stale && <div className="mw-warn">This brief is {window.timeAgoM(at)} old — Solomon's loop may be paused or backing off.</div>}
      <window.MCard title={b ? b.headline : "Operating brief"} right={<span className="mw-streak">READ ONLY</span>}>
        {brief.loading && !brief.data ? <window.MSpin/> : !(brief.data && brief.data.ok) ? null : !b ? <window.MEmpty title="No brief yet" sub="Solomon writes one daily on the box."/>
          : <div className="mw-brief">
            {at && <div className="m-fade">Written {MBDAgo(at)}</div>}
            {MBD_BRIEF_SECTIONS.filter(([, k]) => Array.isArray(b[k]) && b[k].length).map(([title, k]) => <section key={k}>
              <b>{title}</b>{b[k].map((x, i) => <p key={i}>• {MBDLine(x)}</p>)}
            </section>)}
            {comp && <section><b>Competitor read</b><p>{comp}</p></section>}
          </div>}
      </window.MCard>
      <window.MBtn kind="ok" onClick={() => MBDGo("agents")}>Ask Solomon →</window.MBtn>
    </div>
  </React.Fragment>;
}

// ---------------------------------------------------------------- Money (read-only)
function MBDMoney() {
  const bill = window.useApiM("/api/daycare/billing", { interval: 120000 });
  const invoices = (bill.data && bill.data.ok && Array.isArray(bill.data.invoices)) ? bill.data.invoices : null;
  const today = new Date().toISOString().slice(0, 10);
  const open = (invoices || []).filter((inv) => inv.status !== "void").map((inv) => {
    const paid = (inv.payments || []).reduce((s, p) => s + (Number(p.amount) || 0), 0);
    return { inv, bal: Math.max(0, (Number(inv.amount) || 0) - paid) };
  }).filter((x) => x.bal > 0).sort((a, b) => String(a.inv.due_on || "").localeCompare(String(b.inv.due_on || "")));
  const outstanding = open.reduce((s, x) => s + x.bal, 0);
  const overdue = open.filter((x) => x.inv.status === "overdue" || (x.inv.due_on && x.inv.due_on < today)).length;
  return <React.Fragment>
    <window.MHeader title="Money" sub="Open balances · read only" />
    <div className="m-content mw-page">
      {MBDAuth(bill) ? <MBDAuthLine/> : MBDFailed(bill) ? <div className="mw-warn">Billing unavailable — retry.</div> : null}
      <window.MCard title="Outstanding">
        <div className="mw-stats">
          <MBDMetric label="Owed" value={invoices ? window.fmtMoneyM(outstanding) : "—"}/>
          <MBDMetric label="Open invoices" value={invoices ? open.length : "—"}/>
          <MBDMetric label="Overdue" value={invoices ? overdue : "—"}/>
        </div>
        {bill.loading && !bill.data ? <window.MSpin/> : invoices && (!open.length
          ? <window.MEmpty title="Nothing owed" sub="Every recorded invoice is paid."/>
          : <div className="mw-list">{open.slice(0, 25).map(({ inv, bal }) => <div className="mw-lead" key={inv.id}>
            <div className="mw-lead-main"><b>{inv.guardian_name || "Family account"}</b>
              <small>{[inv.invoice_number, inv.due_on ? "due " + inv.due_on : "", inv.due_on && inv.due_on < today ? "overdue" : inv.status].filter(Boolean).join(" · ")}</small></div>
            <b style={{ fontSize: 13, whiteSpace: "nowrap" }}>{window.fmtMoneyM(bal)}</b>
          </div>)}</div>)}
        {open.length > 25 && <div className="mw-desktop-hint">Showing the 25 oldest of {open.length}.</div>}
        <div className="mw-desktop-hint">Send invoices, record payments and text families from the desktop Billing tab.</div>
      </window.MCard>
    </div>
  </React.Fragment>;
}

Object.assign(window, { MBDHome, MBDFamilies, MBDSolomon, MBDMoney });
window.M_BIZ = window.M_BIZ || {};
window.M_BIZ.daycare = {
  id: "daycare", name: "Daycare", tagline: "A Touch of Blessings", accent: "#7CB342", ico: "Heart",
  tabs: [
    { key: "home", label: "Home", ico: "Home" },
    { key: "families", label: "Families", ico: "User" },
    { key: "solomon", label: "Solomon", ico: "Brain" },
    { key: "money", label: "Money", ico: "Dollar" },
  ],
  pages: { home: MBDHome, families: MBDFamilies, solomon: MBDSolomon, money: MBDMoney },
};
