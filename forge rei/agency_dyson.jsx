// agency_dyson.jsx — Dyson edit-agent tab (Forge AI Agency).
// Dyson drafts a plan for every requested change and waits for your approval
// before anything goes live. Generate plans from open requests, then approve /
// request revision / reject each draft.
// Static-React: hooks aliased (…Dy), top-level names prefixed Dy, shipped on window.
const { useState: useStateDy } = React;

// status → AgUI.Badge mapping (mirrors AgUI.APPROVAL_STATUS shape)
const DY_STATUS = {
  draft:    { label: "Awaiting approval", color: "#F59E0B" },
  approved: { label: "Approved",          color: "#22C55E" },
  revision: { label: "Revision",          color: "#8B5CF6" },
  rejected: { label: "Rejected",          color: "#EF4444" },
};
const DY_AFFECT = {
  file:     { color: "#4F7CFF" },
  page:     { color: "#22C55E" },
  workflow: { color: "#F59E0B" },
};
const DY_DECISIONS = [
  { action: "reject",  label: "Reject",           color: "#EF4444", icon: "Activity" },
  { action: "revise",  label: "Request Revision", color: "#8B5CF6", icon: "Reply" },
  { action: "approve", label: "Approve",          color: "#22C55E", icon: "Check" },
];

function DyAffectPill({ a }) {
  const m = DY_AFFECT[a.type] || { color: "#64748B" };
  return (
    <span style={{ fontSize: 11, fontWeight: 600, color: m.color, background: m.color + "1f",
      padding: "3px 9px", borderRadius: 999, whiteSpace: "nowrap" }}>{a.type}: {a.name}</span>
  );
}

function DyDraftCard({ d, onChanged }) {
  const Icons = window.Icons;
  const [busy, setBusy] = useStateDy(false);
  const affected = d.affected || [];
  const steps = d.steps || [];

  async function decide(action) {
    setBusy(true);
    try { await window.apiPost("/api/agency/dyson/decision", { id: d.id, action }); onChanged && onChanged(); }
    catch (e) { window.alert("Decision failed: " + (e.message || e)); }
    setBusy(false);
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 14.5 }}>{d.title}</div>
          <div className="faint" style={{ fontSize: 12, marginTop: 3 }}>
            {d.clientName}{d.createdAt ? " · " + window.timeAgo(d.createdAt) : ""}
          </div>
        </div>
        <window.AgUI.RiskBadge risk={d.risk} />
      </div>

      {d.recommendation && (
        <div style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 11px", borderRadius: 9,
          background: d.recommendation === "agent" ? "#22C55E18" : "#F59E0B18",
          border: "1px solid " + (d.recommendation === "agent" ? "#22C55E44" : "#F59E0B44") }}>
          <span style={{ fontSize: 15 }}>{d.recommendation === "agent" ? "🤖" : "👤"}</span>
          <div style={{ fontSize: 12.5 }}>
            <b style={{ color: d.recommendation === "agent" ? "#22C55E" : "#F59E0B" }}>
              {d.recommendation === "agent" ? "Agent can handle this" : "Recommend you do this one"}</b>
            {d.recommendationReason ? " — " + d.recommendationReason : ""}
          </div>
        </div>
      )}

      {d.summary && <div className="faint" style={{ fontSize: 13 }}>{d.summary}</div>}
      {d.riskReason && (
        <div className="faint" style={{ fontSize: 12 }}>Risk: {d.riskReason}</div>
      )}

      {(d.files && d.files.length > 0) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="card-title">✍️ Change written · {d.files.length} file{d.files.length > 1 ? "s" : ""} (ships as a PR on approve)</div>
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
            {d.files.map((fl, i) => (
              <span key={i} className="mono" style={{ fontSize: 11.5, padding: "3px 8px", borderRadius: 6,
                background: "var(--card-2)", border: "1px solid var(--border)" }}>{fl.path}</span>
            ))}
          </div>
        </div>
      )}

      {affected.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="card-title">Affected</div>
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
            {affected.map((a, i) => <DyAffectPill key={i} a={a} />)}
          </div>
        </div>
      )}

      {steps.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="card-title">Implementation steps</div>
          <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: "var(--muted)",
            display: "flex", flexDirection: "column", gap: 4 }}>
            {steps.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
        </div>
      )}

      {d.status === "draft" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", gap: 9, justifyContent: "flex-end", flexWrap: "wrap" }}>
            {DY_DECISIONS.map((b) => {
              const Ico = Icons[b.icon] || Icons.Dashboard;
              const isApprove = b.action === "approve";
              return (
                <button key={b.action} className="tab" disabled={busy} onClick={() => decide(b.action)}
                  style={isApprove
                    ? { background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }
                    : { color: b.color }}>
                  <Ico size={13} /> {b.label}
                </button>
              );
            })}
          </div>
          <div className="faint" style={{ fontSize: 11.5, textAlign: "right" }}>
            Nothing is applied until you approve.
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 10, justifyContent: "flex-end", flexWrap: "wrap" }}>
          {(d.prUrl || d.commitUrl) && (
            <a href={d.prUrl || d.commitUrl} target="_blank" rel="noopener noreferrer"
              style={{ fontSize: 12, fontWeight: 700, color: "#2DD4BF", textDecoration: "none",
                border: "1px solid #2DD4BF55", background: "#2DD4BF18", padding: "4px 10px", borderRadius: 8 }}>
              {d.prUrl ? "View PR ↗" : "View commit ↗"}
            </a>
          )}
          <div className="faint" style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 7 }}>
            Status: <window.AgUI.Badge status={d.status} map={DY_STATUS} />
          </div>
        </div>
      )}
    </div>
  );
}

function DyGenerator({ requests, onGenerated }) {
  const Icons = window.Icons;
  const [sel, setSel] = useStateDy("");
  const [busy, setBusy] = useStateDy(false);
  const open = (requests || []).filter((r) => ["completed", "rejected"].indexOf(r.status) === -1);

  async function generate() {
    if (!sel) return;
    setBusy(true);
    try { await window.apiPost("/api/agency/dyson/generate", { requestId: sel }); setSel(""); onGenerated && onGenerated(); }
    catch (e) { window.alert("Dyson failed: " + (e.message || e)); }
    setBusy(false);
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 11 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: "#2DD4BF" }}><Icons.Spark size={16} /></span>
        <div style={{ fontWeight: 600, fontSize: 14.5 }}>Generate a plan</div>
      </div>
      {open.length === 0 ? (
        <div className="faint" style={{ fontSize: 12.5 }}>
          No open requests —{" "}
          <span className="link" style={{ cursor: "pointer" }}
            onClick={() => window.GoTo && window.GoTo("Requests")}>add one in the Requests tab</span>.
        </div>
      ) : (
        <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <select style={window.AgUI.inp} value={sel} onChange={(e) => setSel(e.target.value)}>
              <option value="">Pick a request for Dyson to plan…</option>
              {open.map((r) => (
                <option key={r.id} value={r.id}>{r.clientName} — {r.title}</option>
              ))}
            </select>
          </div>
          <button className="tab" disabled={busy || !sel} onClick={generate}
            style={{ display: "flex", alignItems: "center", gap: 6,
              background: "#2DD4BF22", color: "#2DD4BF", borderColor: "#2DD4BF55", fontWeight: 600,
              opacity: busy || !sel ? 0.55 : 1 }}>
            <Icons.Dyson size={14} /> {busy ? "Drafting…" : "Ask Dyson to draft"}
          </button>
        </div>
      )}
    </div>
  );
}

function AgencyDyson() {
  const Icons = window.Icons;
  const drafts = window.useApi("/api/agency/dyson/drafts", { interval: 20000 });
  const reqs = window.useApi("/api/agency/requests");
  const list = (drafts.data && drafts.data.drafts) || [];
  const requests = (reqs.data && reqs.data.requests) || [];

  const counts = { draft: 0, approved: 0, revision: 0, rejected: 0 };
  list.forEach((d) => { counts[d.status] = (counts[d.status] || 0) + 1; });
  const kpis = [
    { label: "Drafts",            value: list.length,      icon: "Dyson",    color: "#2DD4BF" },
    { label: "Awaiting Approval", value: counts.draft,     icon: "Activity", color: "#F59E0B" },
    { label: "Approved",          value: counts.approved,  icon: "Check",    color: "#22C55E" },
    { label: "Needs Revision",    value: counts.revision,  icon: "Reply",    color: "#8B5CF6" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div className="kpi-ico" style={{ width: 40, height: 40, borderRadius: 11,
          background: "#2DD4BF1f", color: "#2DD4BF", display: "flex",
          alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <Icons.Dyson size={20} />
        </div>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Dyson</h1>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>
            Your edit agent — drafts a plan for every change and waits for your approval before anything goes live.
          </div>
        </div>
      </div>

      {drafts.error && <window.ErrorRow error={drafts.error} onRetry={drafts.refresh} />}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
        {kpis.map((k) => <window.AgUI.AnalyticsCard key={k.label} {...k} />)}
      </div>

      <DyGenerator requests={requests} onGenerated={drafts.refresh} />

      {drafts.loading && !drafts.data && <window.LoadingRow label="Loading drafts…" />}

      {!drafts.loading && list.length === 0 ? (
        <div className="card empty" style={{ minHeight: "32vh" }}>
          <div className="empty-ico" style={{ width: 72, height: 72 }}><Icons.Dyson size={30} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>No plans yet</div>
          <div style={{ fontSize: 13, maxWidth: 360, textAlign: "center" }}>
            Send a request to Dyson above and it will draft a step-by-step plan for your approval.
          </div>
        </div>
      ) : (
        list.map((d) => <DyDraftCard key={d.id} d={d} onChanged={drafts.refresh} />)
      )}
    </div>
  );
}

Object.assign(window, { AgencyDyson });
