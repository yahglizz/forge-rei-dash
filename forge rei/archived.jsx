// archived.jsx — Archived Businesses (P1-1). Archive = HIDE, never delete.
// Lists every business/lens from /api/businesses with a Reactivate or Archive toggle
// (POST /api/businesses/set). Archived workspaces can still be opened (fully working) via
// window.forgeEnterBusiness (app.jsx). Rendered by app.jsx as the "archived" home view.
const { useState: useStateArc } = React;

function ArchivedBusinessesPage() {
  const { data, error, loading, refresh } = window.useApi("/api/businesses");
  const [busyArc, setBusyArc] = useStateArc(null);
  const [errArc, setErrArc] = useStateArc(null);
  const rows = (data && data.businesses) || [];

  async function toggleArc(b) {
    const archive = !b.archived;
    if (archive && !window.confirm("Archive " + b.label + "? It leaves the switcher, Mission Control, "
        + "Orion's brief, the Agent Office and coaching. Nothing is deleted; reactivate any time.")) return;
    setBusyArc(b.id);
    setErrArc(null);
    try {
      await window.apiPost("/api/businesses/set", { id: b.id, archived: archive });
      refresh();
    } catch (e) {
      setErrArc((archive ? "Archive " : "Reactivate ") + b.label + " failed: " + (e.message || String(e)));
    } finally {
      setBusyArc(null);
    }
  }

  // Maintenance = visual flag only (greyed + badge); the business stays fully live.
  async function toggleMaint(b) {
    setBusyArc(b.id + ":m");
    setErrArc(null);
    try {
      await window.apiPost("/api/businesses/set", { id: b.id, maintenance: !b.maintenance });
      refresh();
    } catch (e) {
      setErrArc("Maintenance toggle for " + b.label + " failed: " + (e.message || String(e)));
    } finally {
      setBusyArc(null);
    }
  }

  function arcRow(b) {
    const isLens = b.id.indexOf(":") !== -1;
    const canOpen = b.archived && !isLens && window.forgeEnterBusiness;
    return (
      <div key={b.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 4px",
                               borderTop: "1px solid var(--border)", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>{b.label}</div>
          <div className="faint mono" style={{ fontSize: 11.5 }}>{b.id}{isLens ? " · lens" : " · workspace"}</div>
        </div>
        <span className="pill" style={{ background: b.archived ? "rgba(100,116,139,.25)" : "rgba(34,197,94,.15)",
                                        color: b.archived ? "var(--text-2)" : "var(--green)" }}>
          {b.archived ? "Archived" : "Active"}
        </span>
        {b.maintenance && (
          <span className="pill" style={{ background: "rgba(245,158,11,.18)", color: "#F59E0B" }}>🛠 Maintenance</span>
        )}
        {!b.archived && !isLens && (
          <button className="tab" disabled={busyArc === b.id + ":m"} onClick={() => toggleMaint(b)}>
            {busyArc === b.id + ":m" ? "Saving…" : b.maintenance ? "End maintenance" : "Maintenance"}
          </button>
        )}
        {canOpen && (
          <button className="tab" onClick={() => window.forgeEnterBusiness(b.id)}>Open (archived)</button>
        )}
        <button className={"tab" + (b.archived ? " active" : "")} disabled={busyArc === b.id}
          onClick={() => toggleArc(b)}>
          {busyArc === b.id ? "Saving…" : b.archived ? "Reactivate" : "Archive"}
        </button>
      </div>
    );
  }

  const archivedRows = rows.filter((b) => b.archived);
  const activeRows = rows.filter((b) => !b.archived);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="faint" style={{ fontSize: 13, maxWidth: 760 }}>
        Archived businesses are hidden from the switcher, Mission Control, Orion's daily brief,
        the Agent Office and the coaching feed. Nothing is deleted: code, routes, data and agents
        stay put, and Reactivate brings them straight back.
      </div>

      {errArc && (
        <div className="card" style={{ padding: 14, borderColor: "var(--red)", color: "var(--red)", fontSize: 13 }}>
          {errArc}
        </div>
      )}
      {error && (
        <div className="card" style={{ padding: 14, borderColor: "var(--red)", display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ flex: 1, color: "var(--red)", fontSize: 13 }}>Couldn't load businesses: {error}</div>
          <button className="tab" onClick={refresh}>Retry</button>
        </div>
      )}
      {loading && !data && <window.LoadingRow label="Loading businesses…" />}

      {data && (
        <div className="card" style={{ padding: "14px 18px" }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Archived ({archivedRows.length})</div>
          {archivedRows.length ? archivedRows.map(arcRow)
            : <div className="faint" style={{ fontSize: 13, padding: "10px 4px" }}>Nothing archived.</div>}
        </div>
      )}
      {data && (
        <div className="card" style={{ padding: "14px 18px" }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Active ({activeRows.length})</div>
          {activeRows.map(arcRow)}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { ArchivedBusinessesPage });
