// FORGE Mobile — Agency (ClientForge) business portal: Home · Calls · Requests · Approvals · Crew.
// Hook alias BA; every top-level name prefixed MBA. Same-origin /api/* only — no keys here.
//   GET  /api/agency/calls · /api/agency/callsheet · /api/agency/stats
//        /api/agency/requests · /api/agency/approvals?status=pending
//   POST /api/agency/request/status {id,status}     — tap + confirm (client sees it in their portal)
//        /api/agency/approval/decision {id,action}  — tap + confirm (approve ships/launches/publishes)
// Calls tab = existing MWAgency (dial tally + call sheet); Crew = MAgentsPage business="agency".
const { useState: useStateBA } = React;

const MBA_OPEN = ["submitted", "in_review", "approved", "in_progress"];
const MBA_REQ_LABEL = { submitted: "Submitted", in_review: "In review", approved: "Approved",
  in_progress: "In progress", completed: "Completed", rejected: "Rejected" };
// Same flow as desktop agency_requests.jsx RQ_NEXT.
const MBA_REQ_NEXT = {
  submitted: [["in_review", "Start review"], ["rejected", "Reject"]],
  in_review: [["approved", "Approve"], ["rejected", "Reject"]],
  approved: [["in_progress", "Start work"]],
  in_progress: [["completed", "Mark complete"]],
  completed: [],
  rejected: [["in_review", "Reopen"]],
};
// kind → [short label, what approving actually does]
const MBA_KIND = {
  dyson: ["Site edit", "Ship this site edit live"],
  eco: ["Ads", "Launch these ads — this can spend money"],
  social: ["Social post", "Publish this post publicly"],
  workflow: ["Workflow", "Push this workflow change live"],
};

function MBAGo(tab) { if (window.mGoTab) window.mGoTab(tab); }

function MBAMetric(p) {
  return <div className="mw-metric"><b>{p.value}</b><span>{p.label}</span></div>;
}

function MBAWhen(iso) {
  const t = Date.parse(iso || "");
  return isNaN(t) ? "" : new Date(t).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function MBAList(src, key) {
  return !src.error && src.data && Array.isArray(src.data[key]) ? src.data[key] : [];
}

// Honest data: ad/metric payloads that aren't live get labeled, never passed off as live.
function MBADataNote(props) {
  const it = props.item;
  const ds = (it.payload || {}).dataSource;
  if (ds === "live" || (!ds && it.kind !== "eco")) return null;
  const txt = ds === "mock" ? "MOCK data — not live"
    : ds === "token_rejected" ? "Meta token rejected — data not live"
    : "Ad data source not stated — verify on desktop Eco";
  return <div style={{ color: "#B45309", fontSize: 11, fontWeight: 700, marginTop: 6 }}>{txt}</div>;
}

function MBAHome() {
  const calls = window.useApiM("/api/agency/calls", { interval: 30000 });
  const sheet = window.useApiM("/api/agency/callsheet", { interval: 60000 });
  const stats = window.useApiM("/api/agency/stats", { interval: 120000 });
  const reqs = window.useApiM("/api/agency/requests", { interval: 60000 });
  const appr = window.useApiM("/api/agency/approvals?status=pending", { interval: 30000 });
  const val = (src, fn) => (src.loading && !src.data ? "…" : src.error || !src.data ? "—" : fn(src.data));

  const leads = MBAList(sheet, "leads");
  const requests = MBAList(reqs, "requests");
  const pending = MBAList(appr, "queue").filter((a) => a.status === "pending");
  const callbacks = leads.filter((l) => l.due && l.callbackAt);
  const hot = leads.filter((l) => l.due && !l.callbackAt && (l.status === "interested" || l.status === "ready"));
  const dueCount = sheet.data && sheet.data.counts ? sheet.data.counts.due : 0;
  const callRows = callbacks.map((l) => ({ id: "cb" + l.id, tab: "calls", kind: "CALLBACK", phone: l.phone,
    title: l.name || l.company || "Prospect", sub: [l.name && l.company, "due " + MBAWhen(l.callbackAt)] }))
    .concat(hot.map((l) => ({ id: "hot" + l.id, tab: "calls", kind: "CALL", phone: l.phone,
      title: l.name || l.company || "Prospect", sub: [l.name && l.company, l.status] })));
  if (!callRows.length && dueCount) callRows.push({ id: "queue", tab: "calls", kind: "CALLS",
    title: dueCount + " leads ready to call", sub: ["Today's call queue"] });
  const all = callRows
    .concat(pending.map((a) => ({ id: "ap" + a.id, tab: "approvals", kind: "APPROVE", title: a.title,
      sub: [a.client, (MBA_KIND[a.kind] || [a.kind])[0], a.risk && a.risk + " risk"] })))
    .concat(requests.filter((r) => r.status === "submitted").map((r) => ({ id: "rq" + r.id, tab: "requests",
      kind: "REQUEST", title: r.title, sub: [r.clientName, r.priority, window.timeAgoM(r.createdAt)] })));
  const shown = all.slice(0, 5);
  const moreTabs = Array.from(new Set(all.slice(5).map((x) => x.tab)));

  return <React.Fragment>
    <window.MHeader title="Agency" sub="ClientForge · clients & calls" />
    <div className="m-content mw-page">
      <section className="mw-hero agency">
        <div className="mw-eyebrow">CLIENTFORGE</div>
        <h1>Calls, clients,<br/>what needs you.</h1>
        <p>Only what moves the agency today.</p>
        <div className="mw-mascot-note"><window.MForgePal size={56}/><span>Dial first. Polish later.</span></div>
      </section>
      {calls.error && <div className="mw-warn">Call tally unavailable — retry.</div>}
      {sheet.error && <div className="mw-warn">Call sheet unavailable — retry.</div>}
      {stats.error && <div className="mw-warn">Client stats unavailable — retry.</div>}
      {reqs.error && <div className="mw-warn">Edit requests unavailable — retry.</div>}
      {appr.error && <div className="mw-warn">Approvals unavailable — retry.</div>}
      <window.MCard title="Today" right={<span className="mw-streak">🔥 {val(calls, (d) => d.streak || 0)} day streak</span>}>
        <div className="mw-stats" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))" }}>
          <MBAMetric label="Calls today" value={val(calls, (d) => ((d.today && d.today.dials) || 0) + "/" + (d.goal || 0))}/>
          <MBAMetric label="Due to call" value={val(sheet, (d) => (d.counts ? d.counts.due : "—"))}/>
          <MBAMetric label={"MRR" + (stats.data && !stats.error ? " · " + (stats.data.activeClients || 0) + " active" : "")}
            value={val(stats, (d) => window.fmtMoneyM(d.mrr))}/>
          <MBAMetric label="Open requests" value={val(reqs, (d) => (d.requests || []).filter((r) => MBA_OPEN.includes(r.status)).length)}/>
        </div>
      </window.MCard>
      <window.MCard title="Needs you" right={<span className="mw-streak">{all.length}</span>}>
        {(sheet.loading && !sheet.data) || (appr.loading && !appr.data) ? <window.MSpin/>
          : !shown.length ? (sheet.error || appr.error || reqs.error ? <div className="m-fade">Nothing to show — a source failed above.</div>
            : <window.MEmpty title="All clear" sub="No callbacks, approvals or new requests waiting."/>)
          : shown.map((it) => <div className="mw-action" key={it.id}>
            <span className="mw-action-kind">{it.kind}</span>
            <div className="mw-lead-main"><b>{it.title}</b><small>{it.sub.filter(Boolean).join(" · ")}</small></div>
            {it.phone ? <a className="mw-call" href={"tel:" + it.phone}>Call</a>
              : <button className="mw-mark" onClick={() => MBAGo(it.tab)} aria-label="Open">›</button>}
          </div>)}
        {moreTabs.map((t) => <button key={t} className="mw-all-actions" style={{ marginTop: 8 }} onClick={() => MBAGo(t)}>See all {t} →</button>)}
      </window.MCard>
    </div>
  </React.Fragment>;
}

function MBACalls() {
  return window.MWAgency ? <window.MWAgency/> : <window.MEmpty title="Call center unavailable"/>;
}

function MBACrew() {
  return window.MAgentsPage ? <window.MAgentsPage business="agency"/> : <window.MEmpty title="Agents unavailable"/>;
}

function MBARequests() {
  const reqs = window.useApiM("/api/agency/requests", { interval: 60000 });
  const [filter, setFilter] = useStateBA("Open");
  const [sel, setSel] = useStateBA(null);
  const [busy, setBusy] = useStateBA(false);
  const [notice, setNotice] = useStateBA("");
  const all = MBAList(reqs, "requests");
  const rows = filter === "Open" ? all.filter((r) => MBA_OPEN.includes(r.status)) : all;
  async function move(r, to, label) {
    if (!window.confirm(label + ": \"" + r.title + "\"?\n\nThe client sees this status in their portal.")) return;
    setBusy(true); setNotice("");
    try { await window.apiPostM("/api/agency/request/status", { id: r.id, status: to }); setSel(null); reqs.refresh(); }
    catch (e) { setNotice("Status update failed — " + (e.message || "retry")); }
    setBusy(false);
  }
  return <React.Fragment>
    <window.MHeader title="Requests" sub="Client edit requests" />
    <div className="m-content mw-page">
      {reqs.error && <div className="mw-warn">Edit requests unavailable — retry.</div>}
      {notice && <div className="mw-warn">{notice}</div>}
      <window.MCard title="Edit requests" right={<span className="m-fade">{rows.length} shown</span>}>
        <div className="m-seg">{["Open", "All"].map((f) => <window.MChip key={f} active={filter === f} onClick={() => setFilter(f)}>{f}</window.MChip>)}</div>
        <div className="mw-list">
          {reqs.loading && !reqs.data ? <window.MSpin/> : rows.length ? rows.map((r) => <div className="mw-lead" key={r.id}>
            <div className="mw-lead-main"><b>{r.title}</b><small>{[r.clientName, MBA_REQ_LABEL[r.status], r.priority, window.timeAgoM(r.updatedAt || r.createdAt)].filter(Boolean).join(" · ")}</small></div>
            <button className="mw-mark" onClick={() => setSel(r)} aria-label="Open request">•••</button>
          </div>) : !reqs.error && <window.MEmpty title={filter === "Open" ? "No open requests" : "No requests yet"} sub="Client portal submissions land here."/>}
        </div>
        <div className="mw-desktop-hint">Hand a request to Dyson from the desktop Requests page.</div>
      </window.MCard>
    </div>
    {sel && <div className="m-sheet"><div className="m-sheet-head"><button className="m-tab" onClick={() => setSel(null)}>‹</button><b style={{ flex: 1 }}>Edit request</b></div><div className="m-sheet-body">
      <div className="m-card">
        <b>{sel.title}</b>
        <div className="m-fade" style={{ marginTop: 4 }}>{[sel.clientName, sel.type, sel.priority, MBA_REQ_LABEL[sel.status]].filter(Boolean).join(" · ")}</div>
        {sel.detail && <div style={{ marginTop: 8, fontSize: 12, whiteSpace: "pre-wrap" }}>{sel.detail}</div>}
        {sel.pageUrl && <div className="m-fade" style={{ marginTop: 6, wordBreak: "break-all" }}>{sel.pageUrl}</div>}
      </div>
      {(MBA_REQ_NEXT[sel.status] || []).map(([to, label]) => <button key={to} className="mw-stage-choice" disabled={busy} onClick={() => move(sel, to, label)}>{label}</button>)}
      {!(MBA_REQ_NEXT[sel.status] || []).length && <div className="m-fade">No further steps for this request.</div>}
      <window.MBtn kind="ghost" onClick={() => setSel(null)}>Cancel</window.MBtn>
    </div></div>}
  </React.Fragment>;
}

function MBAApprovals() {
  const q = window.useApiM("/api/agency/approvals?status=pending", { interval: 30000 });
  const [busyId, setBusyId] = useStateBA(null);
  const [notice, setNotice] = useStateBA("");
  const items = MBAList(q, "queue").filter((x) => x.status === "pending");
  async function decide(it, action) {
    const k = MBA_KIND[it.kind] || [it.kind, "Approve and run this"];
    const msg = action === "approve"
      ? k[1] + (it.client ? " for " + it.client : "") + "?\n\n" + it.title
      : "Reject \"" + it.title + "\"? Nothing goes live.";
    if (!window.confirm(msg)) return;
    setBusyId(it.id); setNotice("");
    try {
      const r = await window.apiPostM("/api/agency/approval/decision", { id: it.id, action });
      if (r.item && r.item.status === "failed") setNotice("Approved, but it failed to run: " + ((r.item.result && r.item.result.detail) || "unknown error"));
      q.refresh();
    } catch (e) { setNotice("Decision failed — " + (e.message || "retry")); }
    setBusyId(null);
  }
  return <React.Fragment>
    <window.MHeader title="Approvals" sub="Nothing goes live until you approve" />
    <div className="m-content mw-page">
      {q.error && <div className="mw-warn">Approvals unavailable — retry.</div>}
      {notice && <div className="mw-warn">{notice}</div>}
      {q.loading && !q.data ? <window.MCard><window.MSpin/></window.MCard>
        : !items.length ? !q.error && <window.MCard><window.MEmpty title="Nothing waiting" sub="Dyson edits, Eco ads and social posts queue here."/></window.MCard>
        : items.map((it) => <window.MCard key={it.id}>
          <div className="m-row" style={{ marginBottom: 8 }}>
            <span className="mw-action-kind">{(MBA_KIND[it.kind] || [it.kind])[0]}</span>
            <span className="m-fade" style={{ flex: 1 }}>{[it.risk && it.risk + " risk", window.timeAgoM(it.createdAt)].filter(Boolean).join(" · ")}</span>
          </div>
          <b style={{ fontSize: 13.5 }}>{it.title}</b>
          {it.client && <div className="m-fade" style={{ marginTop: 3 }}>{it.client}</div>}
          {it.summary && <div style={{ marginTop: 6, fontSize: 12, lineHeight: 1.45 }}>{it.summary}</div>}
          <MBADataNote item={it}/>
          <div className="mw-call-buttons">
            <window.MBtn kind="ok" disabled={busyId === it.id} onClick={() => decide(it, "approve")}>Approve</window.MBtn>
            <window.MBtn kind="no" disabled={busyId === it.id} onClick={() => decide(it, "reject")}>Reject</window.MBtn>
          </div>
        </window.MCard>)}
      <div className="mw-desktop-hint">Request a revision from the desktop Approval Center.</div>
    </div>
  </React.Fragment>;
}

window.M_BIZ = window.M_BIZ || {};
window.M_BIZ.agency = {
  id: "agency", name: "Agency", tagline: "ClientForge · clients & calls", accent: "#8B5CF6", ico: "Phone",
  tabs: [
    { key: "home", label: "Home", ico: "Home" },
    { key: "calls", label: "Calls", ico: "Phone" },
    { key: "requests", label: "Requests", ico: "Doc" },
    { key: "approvals", label: "Approvals", ico: "Check" },
    { key: "crew", label: "Crew", ico: "Bot" },
  ],
  pages: { home: MBAHome, calls: MBACalls, requests: MBARequests, approvals: MBAApprovals, crew: MBACrew },
};

Object.assign(window, { MBAHome, MBACalls, MBACrew, MBARequests, MBAApprovals });
