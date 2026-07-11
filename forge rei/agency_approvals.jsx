// agency_approvals.jsx — Approval Center (Forge AI Agency).
// The single human-in-the-loop gate: Dyson edit drafts, n8n workflow drafts,
// and Eco ad recommendations all queue here, and nothing goes live until the
// operator approves. Reuses AgUI.ApprovalCard for each item.
//
// STATIC-REACT RULES (no build step):
//   - hooks aliased (…Ap) so top-level consts never collide with other files
//   - every top-level name prefixed Ap / AP_
//   - never use computed-member JSX tags — resolve the component to a var first
//   - shipped on window at the bottom
const { useState: useStateAp, useEffect: useEffectAp } = React;

// status filter tabs (client-side) — value "all" means no status filter
const AP_STATUS_TABS = [
  { id: "all",      label: "All" },
  { id: "pending",  label: "Pending" },
  { id: "approved", label: "Approved" },
  { id: "revision", label: "Revision" },
  { id: "rejected", label: "Rejected" },
  { id: "failed",   label: "Failed" },
];

// kind filter tabs (client-side) — value "all" means no kind filter
const AP_KIND_TABS = [
  { id: "all",      label: "All types" },
  { id: "dyson",    label: "Dyson" },
  { id: "workflow", label: "Workflow" },
  { id: "eco",      label: "Eco" },
  { id: "social",   label: "Social" },
];

// KPI definitions, read off the live counts block.
const AP_KPIS = [
  { key: "pending",  label: "Pending",  icon: "Activity",  color: "#F59E0B" },
  { key: "approved", label: "Approved", icon: "Check",     color: "#22C55E" },
  { key: "revision", label: "Revision", icon: "Reply",     color: "#8B5CF6" },
  { key: "rejected", label: "Rejected", icon: "Approvals", color: "#EF4444" },
];

function AgencyApprovals() {
  const Icons = window.Icons;
  const { data, loading, error, refresh } = window.useApi("/api/agency/approvals", { interval: 15000 });
  const [statusFilter, setStatusFilter] = useStateAp("pending");
  const [kindFilter, setKindFilter] = useStateAp("all");
  const [busyId, setBusyId] = useStateAp(null);

  const counts = (data && data.counts) || {};
  let items = (data && data.queue) || [];
  if (statusFilter !== "all") items = items.filter((it) => it.status === statusFilter);
  if (kindFilter !== "all") items = items.filter((it) => it.kind === kindFilter);

  // POST a decision, then refresh the queue. busyId disables that one card.
  async function decide(id, action) {
    setBusyId(id);
    try {
      await window.apiPost("/api/agency/approval/decision", { id, action });
      refresh();
    } catch (e) {
      window.alert("Decision failed: " + (e.message || e));
    }
    setBusyId(null);
  }

  const ApprovalCard = window.AgUI.ApprovalCard;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* header */}
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Approval Center</h1>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>
          One queue for everything waiting on your sign-off — nothing goes live until you approve.
        </div>
      </div>

      {error && <window.ErrorRow error={error} onRetry={refresh} />}

      {/* KPI row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
        {AP_KPIS.map((k) => (
          <window.AgUI.AnalyticsCard
            key={k.key}
            label={k.label}
            value={counts[k.key] || 0}
            icon={k.icon}
            color={k.color}
          />
        ))}
      </div>

      {/* status filter */}
      <div className="tabs" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {AP_STATUS_TABS.map((t) => (
          <button
            key={t.id}
            className={"tab" + (statusFilter === t.id ? " active" : "")}
            onClick={() => setStatusFilter(t.id)}
          >
            {t.label}
            {t.id !== "all" && counts[t.id] ? " (" + counts[t.id] + ")" : ""}
          </button>
        ))}
      </div>

      {/* kind filter */}
      <div className="tabs" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {AP_KIND_TABS.map((t) => (
          <button
            key={t.id}
            className={"tab" + (kindFilter === t.id ? " active" : "")}
            onClick={() => setKindFilter(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* loading */}
      {loading && !data && <window.LoadingRow label="Loading approvals…" />}

      {/* empty state */}
      {!loading && items.length === 0 && (
        <div className="card empty" style={{ minHeight: "36vh" }}>
          <div className="empty-ico" style={{ width: 72, height: 72 }}><Icons.Approvals size={30} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>
            {statusFilter === "pending" && kindFilter === "all" ? "All caught up" : "Nothing here"}
          </div>
          <div style={{ fontSize: 13, maxWidth: 360, textAlign: "center" }}>
            {statusFilter === "pending" && kindFilter === "all"
              ? "Nothing pending — you're all caught up. New drafts from Dyson, n8n, and Eco land here for sign-off."
              : "No items match this filter."}
          </div>
        </div>
      )}

      {/* queue */}
      {items.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {items.map((item) => (
            <ApprovalCard
              key={item.id}
              item={item}
              busy={busyId === item.id}
              onApprove={(it) => decide(it.id, "approve")}
              onRevise={(it) => decide(it.id, "revise")}
              onReject={(it) => decide(it.id, "reject")}
            />
          ))}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { AgencyApprovals });
