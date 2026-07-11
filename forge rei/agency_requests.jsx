// agency_requests.jsx — Client Edit Requests tab (Forge AI Agency).
// Submit/edit requests, track status, view history, admin-approve, hand to Dyson.
// Static-React: hooks aliased (…Rq), top-level names prefixed Rq, shipped on window.
const { useState: useStateRq, useEffect: useEffectRq } = React;

const RQ_FLOW = ["submitted", "in_review", "approved", "in_progress", "completed"];
// Admin buttons available from each status → [{to, label}]
const RQ_NEXT = {
  submitted:   [{ to: "in_review", label: "Start Review" }, { to: "rejected", label: "Reject" }],
  in_review:   [{ to: "approved", label: "Approve" }, { to: "rejected", label: "Reject" }],
  approved:    [{ to: "in_progress", label: "Start Work" }],
  in_progress: [{ to: "completed", label: "Mark Complete" }],
  completed:   [],
  rejected:    [{ to: "in_review", label: "Reopen" }],
};

function RqHistory({ history }) {
  if (!history || !history.length) return <div className="faint" style={{ fontSize: 12 }}>No history yet.</div>;
  return (
    <table className="lead-table" style={{ width: "100%", fontSize: 12.5 }}>
      <thead><tr><th style={{ textAlign: "left" }}>When</th><th style={{ textAlign: "left" }}>Action</th><th style={{ textAlign: "left" }}>Note</th></tr></thead>
      <tbody>
        {history.slice().reverse().map((h, i) => (
          <tr key={i}>
            <td className="faint mono">{window.timeAgo(h.ts)}</td>
            <td><window.AgUI.Badge status={h.action} map={window.AgUI.REQ_STATUS} /></td>
            <td className="faint">{h.note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RqRow({ r, onChanged }) {
  const Icons = window.Icons;
  const [open, setOpen] = useStateRq(false);
  const [busy, setBusy] = useStateRq(false);
  const [editing, setEditing] = useStateRq(false);

  async function move(to) {
    setBusy(true);
    try { await window.apiPost("/api/agency/request/status", { id: r.id, status: to }); onChanged && onChanged(); }
    catch (e) { window.alert("Update failed: " + (e.message || e)); }
    setBusy(false);
  }
  async function toDyson() {
    setBusy(true);
    try {
      await window.apiPost("/api/agency/dyson/generate", { requestId: r.id });
      window.alert("Dyson drafted a plan — review it in the Dyson tab or Approval Center.");
      if (window.GoTo) window.GoTo("Dyson");
    } catch (e) { window.alert("Dyson failed: " + (e.message || e)); }
    setBusy(false);
  }
  async function del() {
    if (!window.confirm("Delete this request?")) return;
    setBusy(true);
    try { await window.apiPost("/api/agency/request/delete", { id: r.id }); onChanged && onChanged(); }
    catch (e) { window.alert("Delete failed: " + (e.message || e)); }
    setBusy(false);
  }

  if (editing) {
    return <window.AgUI.RequestForm initial={r}
      onSaved={() => { setEditing(false); onChanged && onChanged(); }}
      onCancel={() => setEditing(false)} />;
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{r.title}</div>
          <div className="faint" style={{ fontSize: 12 }}>{r.clientName} · {r.type}</div>
        </div>
        <window.AgUI.PriorityBadge priority={r.priority} />
        <window.AgUI.StatusBadge status={r.status} />
        <button className="tab" style={{ padding: "6px 9px" }} onClick={() => setOpen((o) => !o)}>
          {open ? <Icons.Chevron size={14} /> : <Icons.ChevronR size={14} />}
        </button>
      </div>

      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
          {r.detail && <div style={{ fontSize: 13 }}>{r.detail}</div>}

          {/* status tracker */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            {RQ_FLOW.map((s, i) => {
              const reached = RQ_FLOW.indexOf(r.status) >= i || r.status === "completed";
              const m = window.AgUI.REQ_STATUS[s];
              return (
                <React.Fragment key={s}>
                  {i > 0 && <span className="faint" style={{ fontSize: 11 }}>→</span>}
                  <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 8px", borderRadius: 999,
                    color: reached ? m.color : "var(--muted)",
                    background: reached ? m.color + "1f" : "var(--card-2)" }}>{m.label}</span>
                </React.Fragment>
              );
            })}
            {r.status === "rejected" && <window.AgUI.StatusBadge status="rejected" />}
          </div>

          {/* admin approval buttons */}
          <div style={{ display: "flex", gap: 9, flexWrap: "wrap" }}>
            {(RQ_NEXT[r.status] || []).map((b) => (
              <button key={b.to} className="tab" disabled={busy} onClick={() => move(b.to)}
                style={b.to === "rejected" ? { color: "var(--red)" }
                  : b.to === "approved" || b.to === "completed"
                  ? { background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" } : {}}>
                {b.label}
              </button>
            ))}
            <button className="tab" disabled={busy} onClick={toDyson}
              style={{ background: "#2DD4BF22", color: "#2DD4BF", borderColor: "#2DD4BF55", fontWeight: 600 }}>
              <Icons.Dyson size={13} /> Send to Dyson
            </button>
            <div style={{ marginLeft: "auto", display: "flex", gap: 9 }}>
              <button className="tab" disabled={busy} onClick={() => setEditing(true)}><Icons.Settings size={13} /> Edit</button>
              <button className="tab" disabled={busy} onClick={del} style={{ color: "var(--red)" }}>✕</button>
            </div>
          </div>

          {/* history */}
          <div>
            <div className="card-title" style={{ marginBottom: 6 }}>History</div>
            <RqHistory history={r.history} />
          </div>
        </div>
      )}
    </div>
  );
}

function AgencyRequests() {
  const Icons = window.Icons;
  const { data, error, loading, refresh } = window.useApi("/api/agency/requests", { interval: 20000 });
  const [creating, setCreating] = useStateRq(false);
  const [filter, setFilter] = useStateRq("all");
  const reqs = (data && data.requests) || [];
  const shown = filter === "all" ? reqs : reqs.filter((r) => r.status === filter);

  const counts = {};
  reqs.forEach((r) => { counts[r.status] = (counts[r.status] || 0) + 1; });
  const kpis = [
    { label: "Open", value: (counts.submitted || 0) + (counts.in_review || 0), icon: "Requests", color: "#4F7CFF" },
    { label: "In Progress", value: counts.in_progress || 0, icon: "Sliders", color: "#F59E0B" },
    { label: "Completed", value: counts.completed || 0, icon: "Check", color: "#22C55E" },
    { label: "Total", value: reqs.length, icon: "Clipboard", color: "#8B5CF6" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Client Edit Requests</h1>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>Submit, track, and approve client change requests.</div>
        </div>
        {!creating && <button className="tab" style={{ display: "flex", alignItems: "center", gap: 6 }}
          onClick={() => setCreating(true)}><Icons.Plus size={14} /> New Request</button>}
      </div>

      {error && <window.ErrorRow error={error} onRetry={refresh} />}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
        {kpis.map((k) => <window.AgUI.AnalyticsCard key={k.label} {...k} />)}
      </div>

      {creating && <window.AgUI.RequestForm
        onSaved={() => { setCreating(false); refresh(); }} onCancel={() => setCreating(false)} />}

      {/* status filter */}
      <div className="tabs" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {["all", ...RQ_FLOW, "rejected"].map((s) => (
          <button key={s} className={"tab" + (filter === s ? " active" : "")} onClick={() => setFilter(s)}>
            {s === "all" ? "All" : (window.AgUI.REQ_STATUS[s] ? window.AgUI.REQ_STATUS[s].label : s)}
            {s !== "all" && counts[s] ? " (" + counts[s] + ")" : ""}
          </button>
        ))}
      </div>

      {loading && !data && <window.LoadingRow label="Loading requests…" />}
      {!loading && shown.length === 0 && (
        <div className="card empty" style={{ minHeight: "36vh" }}>
          <div className="empty-ico" style={{ width: 72, height: 72 }}><Icons.Requests size={30} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>No requests here</div>
          <div style={{ fontSize: 13, maxWidth: 340, textAlign: "center" }}>Client edit requests show up here. Create one to see the full flow.</div>
        </div>
      )}
      {shown.map((r) => <RqRow key={r.id} r={r} onChanged={refresh} />)}
    </div>
  );
}

Object.assign(window, { AgencyRequests });
