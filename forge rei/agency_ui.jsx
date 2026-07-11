// agency_ui.jsx — shared, reusable building blocks for the Forge AI Agency
// feature sections. Everything is exposed on window.AgUI so each section file
// (agency_requests / dyson / workflows / clientview / ads / eco / approvals)
// reuses ONE set of components instead of redefining them.
//
// STATIC-REACT RULES (this whole dashboard has no build step):
//   - hooks are aliased (…Ui) so top-level consts never collide with other files
//   - every top-level name is prefixed Ui / UI_ for the same reason
//   - shipped on window.AgUI at the bottom
const { useState: useStateUi, useEffect: useEffectUi } = React;

// ---- shared maps + styles ---------------------------------------------------
const UI_PRIORITY = {
  low:    { label: "Low",    color: "#64748B" },
  medium: { label: "Medium", color: "#4F7CFF" },
  high:   { label: "High",   color: "#F59E0B" },
  urgent: { label: "Urgent", color: "#EF4444" },
};
const UI_REQ_STATUS = {
  submitted:   { label: "Submitted",   color: "#4F7CFF" },
  in_review:   { label: "In Review",   color: "#8B5CF6" },
  approved:    { label: "Approved",    color: "#22C55E" },
  in_progress: { label: "In Progress", color: "#F59E0B" },
  completed:   { label: "Completed",   color: "#16A34A" },
  rejected:    { label: "Rejected",    color: "#EF4444" },
};
const UI_RISK = {
  low:    { label: "Low risk",    color: "#22C55E" },
  medium: { label: "Medium risk", color: "#F59E0B" },
  high:   { label: "High risk",   color: "#EF4444" },
};
const UI_APPROVAL_STATUS = {
  pending:  { label: "Pending",  color: "#F59E0B" },
  approved: { label: "Approved", color: "#22C55E" },
  revision: { label: "Revision", color: "#8B5CF6" },
  rejected: { label: "Rejected", color: "#EF4444" },
  failed:   { label: "Execution failed", color: "#EF4444" },
};
const UI_KIND = {
  dyson:    { label: "Dyson · Edit",      color: "#2DD4BF", icon: "Dyson" },
  workflow: { label: "n8n · Workflow",    color: "#4F7CFF", icon: "Workflows" },
  eco:      { label: "Eco · Ads",         color: "#22C55E", icon: "Eco" },
  social:   { label: "Social · Post",     color: "#E1306C", icon: "Spark" },
};

const UI_TYPES = ["Website Edit", "New Page", "Bug Fix", "Content Update",
                  "SEO", "Integration", "Design Change", "AI Agent", "Other"];
const UI_PRIORITIES = ["low", "medium", "high", "urgent"];
const UI_DEMO_CLIENTS = [
  { id: "demo-bloom", name: "Bloom Dental" },
  { id: "demo-peak",  name: "Peak Fitness" },
];

const uiInp = {
  background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 9,
  padding: "9px 11px", color: "var(--text)", fontSize: 13, width: "100%", outline: "none",
};
const uiField = { display: "flex", flexDirection: "column", gap: 5 };
const uiLabel = { fontSize: 11, color: "var(--muted)" };
const uiMoney = (n) => (window.fmtMoney ? window.fmtMoney(n) : "$" + (Number(n) || 0));

// ---- badges -----------------------------------------------------------------
function UiBadge({ status, map }) {
  const m = (map && map[status]) || { label: status || "—", color: "#64748B" };
  return (
    <span style={{ fontSize: 11, fontWeight: 600, color: m.color, background: m.color + "1f",
      padding: "3px 9px", borderRadius: 999, whiteSpace: "nowrap" }}>{m.label}</span>
  );
}
const UiStatusBadge = (p) => <UiBadge status={p.status} map={p.map || UI_REQ_STATUS} />;
const UiPriorityBadge = (p) => <UiBadge status={p.priority} map={UI_PRIORITY} />;
const UiRiskBadge = (p) => <UiBadge status={p.risk} map={UI_RISK} />;
const UiKindBadge = ({ kind }) => {
  const m = UI_KIND[kind] || { label: kind, color: "#64748B" };
  return (
    <span style={{ fontSize: 11, fontWeight: 600, color: m.color, background: m.color + "1f",
      padding: "3px 9px", borderRadius: 999, whiteSpace: "nowrap" }}>{m.label}</span>
  );
};

// ---- client selector --------------------------------------------------------
// Pulls the live client book (/api/agency/clients); if empty, falls back to the
// demo clients so every mock section still has someone to point at.
function UiClientSelector({ value, onChange, allowAll = false, label = "Client" }) {
  const { data } = window.useApi("/api/agency/clients");
  const live = (data && data.clients) || [];
  const clients = live.length ? live.map((c) => ({ id: c.id, name: c.name })) : UI_DEMO_CLIENTS;
  return (
    <div style={uiField}>
      <span style={uiLabel}>{label}</span>
      <select style={uiInp} value={value || ""} onChange={(e) => {
        const id = e.target.value;
        const c = clients.find((x) => x.id === id);
        onChange && onChange(id, c);
      }}>
        {allowAll && <option value="">All clients</option>}
        {!value && !allowAll && <option value="">Select a client…</option>}
        {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    </div>
  );
}

// ---- reusable edit-request form (used by Requests tab + Client Dashboard) ----
function UiRequestForm({ initial, lockClient = false, onSaved, onCancel }) {
  const blank = { clientId: "", clientName: "", title: "", type: "Website Edit",
                  priority: "medium", detail: "" };
  const [f, setF] = useStateUi(initial ? { ...blank, ...initial } : blank);
  const [saving, setSaving] = useStateUi(false);
  const [err, setErr] = useStateUi(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  async function submit() {
    if (!f.title.trim()) { setErr("Title is required"); return; }
    if (!f.clientId) { setErr("Pick a client"); return; }
    setSaving(true); setErr(null);
    try {
      await window.apiPost("/api/agency/request/save", { request: f });
      onSaved && onSaved();
    } catch (e) { setErr(e.message || "Save failed"); }
    setSaving(false);
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontWeight: 600, fontSize: 15 }}>{initial && initial.id ? "Edit request" : "New edit request"}</div>
      {!lockClient && <UiClientSelector value={f.clientId}
        onChange={(id, c) => setF((s) => ({ ...s, clientId: id, clientName: c ? c.name : "" }))} />}
      <div style={uiField}><span style={uiLabel}>Title *</span>
        <input style={uiInp} value={f.title} onChange={(e) => set("title", e.target.value)}
          placeholder="e.g. Swap homepage hero image" /></div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div style={uiField}><span style={uiLabel}>Request type</span>
          <select style={uiInp} value={f.type} onChange={(e) => set("type", e.target.value)}>
            {UI_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select></div>
        <div style={uiField}><span style={uiLabel}>Priority</span>
          <select style={uiInp} value={f.priority} onChange={(e) => set("priority", e.target.value)}>
            {UI_PRIORITIES.map((p) => <option key={p} value={p}>{UI_PRIORITY[p].label}</option>)}
          </select></div>
      </div>
      <div style={uiField}><span style={uiLabel}>Details</span>
        <textarea style={{ ...uiInp, minHeight: 70, resize: "vertical", fontFamily: "inherit" }}
          value={f.detail} onChange={(e) => set("detail", e.target.value)}
          placeholder="Describe the change you want…" /></div>
      {err && <div style={{ color: "var(--red)", fontSize: 12.5 }}>{err}</div>}
      <div style={{ display: "flex", gap: 9, justifyContent: "flex-end" }}>
        {onCancel && <button className="tab" onClick={onCancel}>Cancel</button>}
        <button className="tab" onClick={submit} disabled={saving}
          style={{ background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
          {saving ? "Saving…" : "Submit request"}
        </button>
      </div>
    </div>
  );
}

// ---- analytics metric card --------------------------------------------------
function UiAnalyticsCard({ label, value, prefix = "", suffix = "", sub, icon = "Analytics", color = "#4F7CFF" }) {
  const Icons = window.Icons;
  const Ico = Icons[icon] || Icons.Analytics;
  const display = typeof value === "number" ? value.toLocaleString() : (value != null ? value : "—");
  return (
    <div className="kpi">
      <div className="kpi-ico" style={{ background: color + "1f", color }}><Ico size={18} /></div>
      <div className="kpi-label">{label}</div>
      <div className="kpi-val">{prefix}{display}{suffix}</div>
      <div className="kpi-delta"><span className="faint">{sub || ""}</span></div>
    </div>
  );
}

// ---- approval card (Approval Center + inline agent sections) -----------------
function UiApprovalCard({ item, onApprove, onRevise, onReject, busy }) {
  const Icons = window.Icons;
  const payload = item.payload || {};
  const lines = payload.steps || payload.affected || payload.next || [];
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 11 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
        <UiKindBadge kind={item.kind} />
        {item.risk && <UiRiskBadge risk={item.risk} />}
        {item.status && item.status !== "pending" && <UiBadge status={item.status} map={UI_APPROVAL_STATUS} />}
        <span className="faint" style={{ fontSize: 11.5, marginLeft: "auto" }}>
          {item.client || ""}{item.createdAt ? " · " + window.timeAgo(item.createdAt) : ""}</span>
      </div>
      <div style={{ fontWeight: 600, fontSize: 14.5 }}>{item.title}</div>
      <div className="faint" style={{ fontSize: 13 }}>{item.summary}</div>
      {lines.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: "var(--muted)", display: "flex", flexDirection: "column", gap: 3 }}>
          {lines.slice(0, 5).map((l, i) => <li key={i}>{typeof l === "string" ? l : JSON.stringify(l)}</li>)}
        </ul>
      )}
      {item.status === "pending" ? (
        <div style={{ display: "flex", gap: 9, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button className="tab" disabled={busy} onClick={() => onReject && onReject(item)}
            style={{ color: "var(--red)" }}><Icons.Activity size={13} /> Reject</button>
          <button className="tab" disabled={busy} onClick={() => onRevise && onRevise(item)}
            style={{ color: "#8B5CF6" }}><Icons.Reply size={13} /> Request Revision</button>
          <button className="tab" disabled={busy} onClick={() => onApprove && onApprove(item)}
            style={{ background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
            <Icons.Check size={13} /> Approve</button>
        </div>
      ) : item.status === "failed" ? (
        <React.Fragment>
          {item.result && item.result.detail && (
            <div className="faint mono" style={{ fontSize: 11.5, color: "var(--red)" }}>{item.result.detail}</div>
          )}
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button className="tab" disabled={busy} onClick={() => onApprove && onApprove(item)}
              style={{ color: "var(--orange)" }}><Icons.Activity size={13} /> Retry</button>
          </div>
        </React.Fragment>
      ) : (
        <div className="faint" style={{ fontSize: 12, textAlign: "right" }}>
          Decided{item.decidedAt ? " " + window.timeAgo(item.decidedAt) : ""}
        </div>
      )}
    </div>
  );
}

// ---- Eco recommendation card ------------------------------------------------
function UiAgentRecCard({ rec }) {
  const row = (k, v) => (
    <div style={{ display: "flex", gap: 8, fontSize: 12.5 }}>
      <span className="faint" style={{ minWidth: 78, flexShrink: 0 }}>{k}</span>
      <span style={{ color: "var(--text)" }}>{v}</span>
    </div>
  );
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 9 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>{rec.title}</span>
        <span style={{ marginLeft: "auto" }}><UiBadge status={rec.angle} map={{ [rec.angle]: { label: rec.angle, color: "#22C55E" } }} /></span>
      </div>
      {row("Hook", rec.hook)}
      {row("Headline", rec.headline)}
      {row("Body", rec.primaryText)}
      {row("CTA", rec.cta)}
      {row("Creative", rec.creativeDirection)}
    </div>
  );
}

// ---- n8n workflow card ------------------------------------------------------
function UiWorkflowCard({ wf, selected, onClick }) {
  const Icons = window.Icons;
  const statusMap = {
    active:   { label: "Active",   color: "#22C55E" },
    inactive: { label: "Inactive", color: "#64748B" },
    draft:    { label: "Draft",    color: "#F59E0B" },
  };
  return (
    <button onClick={() => onClick && onClick(wf)} className="card card-pad"
      style={{ textAlign: "left", display: "flex", flexDirection: "column", gap: 7, width: "100%",
        borderColor: selected ? "var(--accent, #4F7CFF)" : "var(--border)",
        boxShadow: selected ? "0 0 0 1px var(--accent, #4F7CFF)" : "none" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: "#4F7CFF" }}><Icons.Workflows size={16} /></span>
        <span style={{ fontWeight: 600, fontSize: 13.5 }}>{wf.name}</span>
        <span style={{ marginLeft: "auto" }}><UiBadge status={wf.status} map={statusMap} /></span>
      </div>
      <div className="faint" style={{ fontSize: 12 }}>{wf.description}</div>
      <div className="faint" style={{ fontSize: 11.5, display: "flex", gap: 12 }}>
        <span>{wf.nodes} nodes</span><span>{wf.trigger}</span>
        {wf.client && <span>· {wf.client}</span>}
        {wf.draft && <span style={{ color: "#F59E0B" }}>· unsaved draft</span>}
      </div>
    </button>
  );
}

// ---- ship it ----------------------------------------------------------------
window.AgUI = {
  // badges
  Badge: UiBadge, StatusBadge: UiStatusBadge, PriorityBadge: UiPriorityBadge,
  RiskBadge: UiRiskBadge, KindBadge: UiKindBadge,
  // inputs / pickers / forms
  ClientSelector: UiClientSelector, RequestForm: UiRequestForm,
  // cards
  AnalyticsCard: UiAnalyticsCard, ApprovalCard: UiApprovalCard,
  AgentRecCard: UiAgentRecCard, WorkflowCard: UiWorkflowCard,
  // shared maps + helpers
  PRIORITY: UI_PRIORITY, REQ_STATUS: UI_REQ_STATUS, RISK: UI_RISK,
  APPROVAL_STATUS: UI_APPROVAL_STATUS, KIND: UI_KIND,
  TYPES: UI_TYPES, PRIORITIES: UI_PRIORITIES,
  inp: uiInp, field: uiField, fieldLabel: uiLabel, money: uiMoney,
};
