// agency_workflows.jsx — n8n MCP Workflows tab (Forge AI Agency).
// Two-column: workflow list (left) | detail / draft-edit panel (right).
// Draft edits are saved + queued for approval BEFORE they push to n8n.
// Static-React: hooks aliased (…Wf), top-level names prefixed Wf, shipped on window.
const { useState: useStateWf, useEffect: useEffectWf } = React;

const WF_STATUS_MAP = {
  active:   { label: "Active",   color: "var(--green)" },
  inactive: { label: "Inactive", color: "var(--muted)" },
  draft:    { label: "Draft",    color: "var(--orange)" },
};
const WF_DRAFT_STATUS = {
  draft:    { label: "Pending approval", color: "#F59E0B" },
  approved: { label: "Approved",         color: "#22C55E" },
  revision: { label: "Revision asked",   color: "#8B5CF6" },
  rejected: { label: "Rejected",         color: "#EF4444" },
};

// ---- connection settings card (read-only, env-driven) ----------------------
function WfConnectionCard({ connection }) {
  const Icons = window.Icons;
  const conn = connection || {};
  if (conn.connected) {
    const isLive = conn.source === "live";
    return (
      <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className="dot online pulse" />
        <span style={{ fontWeight: 600, fontSize: 14 }}>n8n — connected</span>
        {isLive && (
          <span style={{ fontSize: 11, fontWeight: 600, color: "#22C55E",
            background: "#22C55E1f", padding: "3px 9px", borderRadius: 999 }}>LIVE</span>
        )}
        <span className="faint mono" style={{ fontSize: 12, marginLeft: "auto" }}>{conn.baseUrl}</span>
      </div>
    );
  }
  const SetIco = window.Icons.Settings || window.Icons.Sliders;
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12,
      borderColor: "var(--orange)", boxShadow: "0 0 0 1px var(--orange)33" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ color: "var(--orange)" }}><SetIco size={16} /></span>
        <span style={{ fontWeight: 600, fontSize: 15 }}>n8n — not connected</span>
      </div>
      {conn.todo && <div className="faint" style={{ fontSize: 12.5 }}>{conn.todo}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div style={window.AgUI.field}>
          <span style={window.AgUI.fieldLabel}>Base URL (env: N8N_BASE_URL)</span>
          <input style={{ ...window.AgUI.inp, opacity: 0.65 }} disabled readOnly
            value={conn.baseUrl || ""} placeholder="set via environment variable" />
        </div>
        <div style={window.AgUI.field}>
          <span style={window.AgUI.fieldLabel}>API Key (env: N8N_API_KEY)</span>
          <input style={{ ...window.AgUI.inp, opacity: 0.65 }} disabled readOnly
            value={conn.hasKey ? "••••••••" : ""} placeholder="set via environment variable" />
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <button className="tab" disabled style={{ opacity: 0.55, cursor: "not-allowed" }}>Connect via env</button>
        <span className="faint" style={{ fontSize: 11.5 }}>
          Set N8N_BASE_URL + N8N_API_KEY in agency.env to enable live push.
        </span>
      </div>
    </div>
  );
}

// ---- draft-edit form -------------------------------------------------------
function WfEditForm({ wf, onSaved, onCancel }) {
  const [f, setF] = useStateWf({
    name: wf.name || "", description: wf.description || "",
    trigger: wf.trigger || "", client: wf.client || "",
    stepsText: (wf.steps || []).join("\n"),
  });
  const [saving, setSaving] = useStateWf(false);
  const [err, setErr] = useStateWf(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  async function save() {
    if (!f.name.trim()) { setErr("Workflow name is required"); return; }
    setSaving(true); setErr(null);
    const steps = f.stepsText.split("\n").map((s) => s.trim()).filter(Boolean);
    try {
      await window.apiPost("/api/agency/workflow/save", {
        workflow: {
          workflowId: wf.id, name: f.name.trim(), description: f.description,
          trigger: f.trigger, client: f.client, steps,
        },
      });
      window.alert("Draft saved — review it in the Approval Center.");
      onSaved && onSaved();
    } catch (e) { setErr(e.message || "Save failed"); }
    setSaving(false);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontWeight: 600, fontSize: 15 }}>Edit workflow draft</div>
      <div style={window.AgUI.field}><span style={window.AgUI.fieldLabel}>Name *</span>
        <input style={window.AgUI.inp} value={f.name} onChange={(e) => set("name", e.target.value)}
          placeholder="Workflow name" /></div>
      <div style={window.AgUI.field}><span style={window.AgUI.fieldLabel}>Description</span>
        <textarea style={{ ...window.AgUI.inp, minHeight: 56, resize: "vertical", fontFamily: "inherit" }}
          value={f.description} onChange={(e) => set("description", e.target.value)}
          placeholder="What this automation does…" /></div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div style={window.AgUI.field}><span style={window.AgUI.fieldLabel}>Trigger</span>
          <input style={window.AgUI.inp} value={f.trigger} onChange={(e) => set("trigger", e.target.value)}
            placeholder="e.g. Webhook / Schedule" /></div>
        <div style={window.AgUI.field}><span style={window.AgUI.fieldLabel}>Client</span>
          <input style={window.AgUI.inp} value={f.client} onChange={(e) => set("client", e.target.value)}
            placeholder="Client name" /></div>
      </div>
      <div style={window.AgUI.field}><span style={window.AgUI.fieldLabel}>Steps (one per line)</span>
        <textarea style={{ ...window.AgUI.inp, minHeight: 120, resize: "vertical", fontFamily: "inherit" }}
          value={f.stepsText} onChange={(e) => set("stepsText", e.target.value)}
          placeholder={"Webhook\nDedupe contact\nCreate GHL contact\nSlack notify"} /></div>
      {err && <div style={{ color: "var(--red)", fontSize: 12.5 }}>{err}</div>}
      <div style={{ display: "flex", gap: 9, justifyContent: "flex-end" }}>
        {onCancel && <button className="tab" onClick={onCancel} disabled={saving}>Cancel</button>}
        <button className="tab" onClick={save} disabled={saving}
          style={{ background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
          {saving ? "Saving…" : "Save Draft"}
        </button>
      </div>
    </div>
  );
}

// ---- detail panel ----------------------------------------------------------
function WfDetail({ wf, onChanged, n8nConnected }) {
  const Icons = window.Icons;
  const [editing, setEditing] = useStateWf(false);
  const [busy, setBusy] = useStateWf(false);
  useEffectWf(() => { setEditing(false); }, [wf && wf.id]);

  if (!wf) {
    return (
      <div className="card empty" style={{ minHeight: "40vh" }}>
        <div className="empty-ico" style={{ width: 64, height: 64 }}><Icons.Workflows size={26} /></div>
        <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 15 }}>Select a workflow</div>
        <div style={{ fontSize: 12.5 }}>Pick one on the left to see its steps and edit a draft.</div>
      </div>
    );
  }

  async function decide(action) {
    setBusy(true);
    try { await window.apiPost("/api/agency/workflow/decision", { id: wf.id, action }); onChanged && onChanged(); }
    catch (e) { window.alert("Decision failed: " + (e.message || e)); }
    setBusy(false);
  }

  const row = (k, v) => (
    <div style={{ display: "flex", gap: 8, fontSize: 13 }}>
      <span className="faint" style={{ minWidth: 78, flexShrink: 0 }}>{k}</span>
      <span style={{ color: "var(--text)" }}>{v}</span>
    </div>
  );

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {editing ? (
        <WfEditForm wf={wf} onSaved={() => { setEditing(false); onChanged && onChanged(); }}
          onCancel={() => setEditing(false)} />
      ) : (
        <React.Fragment>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={{ color: "#4F7CFF" }}><Icons.Workflows size={18} /></span>
            <span style={{ fontWeight: 700, fontSize: 17, letterSpacing: "-0.3px" }}>{wf.name}</span>
            <span style={{ marginLeft: "auto" }}><window.AgUI.Badge status={wf.status} map={WF_STATUS_MAP} /></span>
            <button className="tab" onClick={() => setEditing(true)} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Icons.Settings size={13} /> Edit
            </button>
          </div>

          {wf.description && <div style={{ fontSize: 13.5, color: "var(--muted)" }}>{wf.description}</div>}

          <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            {row("Client", wf.client || "—")}
            {row("Trigger", wf.trigger || "—")}
            {row("Nodes", (wf.nodes != null ? wf.nodes : (wf.steps || []).length) + " nodes")}
            {row("Last run", wf.lastRun ? window.timeAgo(wf.lastRun) : "never")}
          </div>

          <div>
            <div className="card-title" style={{ marginBottom: 6 }}>Steps</div>
            {(wf.steps || []).length ? (
              <ol style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: "var(--text)",
                display: "flex", flexDirection: "column", gap: 4 }}>
                {wf.steps.map((s, i) => <li key={i}>{s}</li>)}
              </ol>
            ) : <div className="faint" style={{ fontSize: 12.5 }}>No steps defined yet.</div>}
          </div>

          {/* approval-before-push strip */}
          {wf.draft && (
            <div className="card-pad" style={{ display: "flex", flexDirection: "column", gap: 10,
              border: "1px solid var(--orange)", borderRadius: 11, background: "var(--orange)14" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
                <span style={{ color: "var(--orange)" }}><Icons.Activity size={14} /></span>
                <span style={{ fontWeight: 600, fontSize: 13.5 }}>Unsaved draft pending approval</span>
                <span style={{ marginLeft: "auto" }}>
                  <window.AgUI.Badge status={wf.draft.status || "draft"} map={WF_DRAFT_STATUS} />
                </span>
              </div>
              <div style={{ display: "flex", gap: 9, flexWrap: "wrap" }}>
                <button className="tab" disabled={busy} onClick={() => decide("approve")}
                  style={{ background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
                  <Icons.Check size={13} /> Approve</button>
                <button className="tab" disabled={busy} onClick={() => decide("revise")} style={{ color: "#8B5CF6" }}>
                  <Icons.Reply size={13} /> Request Revision</button>
                <button className="tab" disabled={busy} onClick={() => decide("reject")} style={{ color: "var(--red)" }}>
                  Reject</button>
              </div>
            </div>
          )}

          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
            borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            {n8nConnected ? (
              <button className="tab" disabled={busy} onClick={() => decide("approve")}
                style={{ background: "#4F7CFF", color: "#fff", borderColor: "transparent", fontWeight: 700,
                  display: "flex", alignItems: "center", gap: 6 }}>
                <Icons.Send size={13} /> Approve &amp; Push to n8n
              </button>
            ) : (
              <React.Fragment>
                <button className="tab" disabled style={{ opacity: 0.55, cursor: "not-allowed",
                  background: "#4F7CFF22", color: "#4F7CFF", borderColor: "#4F7CFF55", fontWeight: 700,
                  display: "flex", alignItems: "center", gap: 6 }}>
                  <Icons.Send size={13} /> Approve &amp; Push to n8n
                </button>
                <span className="faint" style={{ fontSize: 11.5 }}>connect n8n to enable</span>
              </React.Fragment>
            )}
          </div>
        </React.Fragment>
      )}
    </div>
  );
}

// ---- page ------------------------------------------------------------------
function AgencyWorkflows() {
  const Icons = window.Icons;
  const { data, error, loading, refresh } = window.useApi("/api/agency/workflows", { interval: 20000 });
  const [selectedId, setSelectedId] = useStateWf(null);
  const workflows = (data && data.workflows) || [];
  const connection = (data && data.connection) || {};

  useEffectWf(() => {
    if (!selectedId && workflows.length) setSelectedId(workflows[0].id);
    if (selectedId && workflows.length && !workflows.some((w) => w.id === selectedId)) setSelectedId(workflows[0].id);
  }, [workflows.length, selectedId]);

  const selected = workflows.find((w) => w.id === selectedId) || null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>n8n Workflows</h1>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>
          Automations per client — draft edits here, approve before they push to n8n.
        </div>
      </div>

      <WfConnectionCard connection={connection} />

      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {loading && !data && <window.LoadingRow label="Loading workflows…" />}

      {!loading && workflows.length === 0 ? (
        <div className="card empty" style={{ minHeight: "36vh" }}>
          <div className="empty-ico" style={{ width: 72, height: 72 }}><Icons.Workflows size={30} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>No workflows yet</div>
          <div style={{ fontSize: 13, maxWidth: 340, textAlign: "center" }}>
            n8n automations show up here once connected. Mock workflows load when wiring is pending.
          </div>
        </div>
      ) : (workflows.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 360px) 1fr", gap: 16, alignItems: "start" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {workflows.map((wf) => (
              <window.AgUI.WorkflowCard key={wf.id} wf={wf} selected={wf.id === selectedId}
                onClick={() => setSelectedId(wf.id)} />
            ))}
          </div>
          <WfDetail wf={selected} onChanged={refresh} n8nConnected={connection.connected} />
        </div>
      ))}
    </div>
  );
}

Object.assign(window, { AgencyWorkflows });
