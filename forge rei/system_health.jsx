// system_health.jsx — "System Health" tab (REI). One screen that answers "is the whole
// fleet running?": every background loop's heartbeat freshness (green/amber/red), its last
// error, plus disk + log pressure. Reads /api/system/health (forge_heartbeat snapshot).
// Polls every 15s. Additive, window-global, unique Sh* names + useStateSh alias.
const { useState: useStateSh } = React;

const SH_COLOR = { green: "#22C55E", amber: "#F59E0B", red: "#EF4444", grey: "#64748B" };

function shFmtBytes(n) {
  if (n === null || n === undefined) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let v = Number(n), i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(v < 10 && i > 0 ? 1 : 0) + " " + u[i];
}

function ShDot({ status }) {
  const c = SH_COLOR[status] || SH_COLOR.grey;
  return (
    <span style={{
      width: 10, height: 10, borderRadius: "50%", background: c,
      display: "inline-block", flexShrink: 0,
      boxShadow: status === "red" ? "0 0 0 3px rgba(239,68,68,.18)" : "none",
    }} />
  );
}

function ShLoopRow({ loop }) {
  const timeAgo = window.timeAgo;
  const c = SH_COLOR[loop.status] || SH_COLOR.grey;
  const err = loop.lastError;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, padding: "11px 4px",
      borderBottom: "1px solid var(--card-2)",
    }}>
      <ShDot status={loop.status} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 13.5 }}>{loop.label || loop.loop}</div>
        {err && (
          <div className="faint mono" style={{
            fontSize: 11, color: "var(--red)", marginTop: 2,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 420,
          }}>
            {loop.errStreak > 1 ? `×${loop.errStreak} ` : ""}{err}
          </div>
        )}
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div className="tabnum" style={{ fontSize: 12.5, fontWeight: 600, color: c }}>
          {loop.stale ? "STALE" : timeAgo(loop.lastRun)}
        </div>
        <div className="faint" style={{ fontSize: 10.5 }}>
          {loop.interval ? `every ${loop.interval < 120 ? loop.interval + "s" : Math.round(loop.interval / 60) + "m"}` : ""}
        </div>
      </div>
    </div>
  );
}

function ShStat({ label, value, color }) {
  return (
    <div className="card card-pad" style={{ textAlign: "center" }}>
      <div className="tabnum" style={{ fontSize: 22, fontWeight: 700, color: color || "var(--text)" }}>{value}</div>
      <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>{label}</div>
    </div>
  );
}

function SystemHealthPage() {
  const Icons = window.Icons;
  const Ico = (Icons && Icons.Activity) || Icons.Bot;
  const { data, error, loading, refresh, refreshedAt } = window.useApi(
    "/api/system/health", { interval: 15000 });

  if (loading && !data) return <window.LoadingRow label="Reading loop heartbeats…" />;
  if (error && !data) return <window.ErrorRow error={error} onRetry={refresh} />;

  const d = data || {};
  const loops = Array.isArray(d.loops) ? d.loops : [];
  const disk = d.disk || {};
  const logs = d.logs || {};
  const okColor = d.ok ? SH_COLOR.green : SH_COLOR.red;
  const greens = loops.filter((l) => l.status === "green").length;
  const reds = loops.filter((l) => l.status === "red").length;
  const ambers = loops.filter((l) => l.status === "amber").length;

  // Only the "at rest" states dim the verdict — a UI-only Mac or a clocked-out crew is
  // intentionally idle, not broken.
  const verdict = !d.active
    ? (d.loopsEnabled ? "CLOCKED OUT" : "UI-ONLY (loops off)")
    : (d.ok ? "ALL SYSTEMS GO" : "ATTENTION NEEDED");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Verdict banner */}
      <div className="card card-pad" style={{
        display: "flex", alignItems: "center", gap: 14,
        borderColor: d.active && !d.ok ? "var(--red)" : "var(--card-2)",
      }}>
        <span style={{ color: d.active ? okColor : SH_COLOR.grey }}><Ico size={22} /></span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 17, fontWeight: 700, color: d.active ? okColor : "var(--text)" }}>{verdict}</div>
          <div className="faint" style={{ fontSize: 12 }}>
            {loops.length} loops monitored · {d.note || ""}
            {d.paused ? " · crew clocked out" : ""}
          </div>
        </div>
        <button className="tab" onClick={refresh}>Refresh</button>
      </div>

      {/* Loop tally */}
      <div className="card-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
        <ShStat label="Loops healthy" value={greens} color={SH_COLOR.green} />
        <ShStat label="Warnings" value={ambers} color={ambers ? SH_COLOR.amber : undefined} />
        <ShStat label="Down" value={reds} color={reds ? SH_COLOR.red : undefined} />
        <ShStat label="Disk used" value={disk.pctUsed != null ? disk.pctUsed + "%" : "—"}
          color={disk.pctUsed != null && disk.pctUsed >= 92 ? SH_COLOR.red : undefined} />
      </div>

      {/* Per-loop heartbeats */}
      <div className="card card-pad">
        <div className="card-title" style={{ fontSize: 15, marginBottom: 6 }}>Background loops</div>
        {loops.length === 0 && (
          <div className="faint" style={{ fontSize: 12.5, padding: "10px 4px" }}>
            No heartbeats yet — loops record their first beat one interval after boot
            {d.loopsEnabled ? "" : " (loops are OFF on this instance)"}.
          </div>
        )}
        {loops.map((l) => <ShLoopRow key={l.loop} loop={l} />)}
      </div>

      {/* Disk + logs */}
      <div className="card card-pad">
        <div className="card-title" style={{ fontSize: 15, marginBottom: 10 }}>Disk &amp; logs</div>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 12.5 }}>
          <div>
            <div className="faint" style={{ fontSize: 11 }}>Disk free</div>
            <div className="tabnum" style={{ fontWeight: 600 }}>
              {shFmtBytes(disk.freeBytes)} / {shFmtBytes(disk.totalBytes)}
            </div>
          </div>
          <div>
            <div className="faint" style={{ fontSize: 11 }}>State store</div>
            <div className="tabnum" style={{ fontWeight: 600 }}>{shFmtBytes(d.stateBytes)}</div>
          </div>
          {Object.keys(logs).map((name) => (
            <div key={name}>
              <div className="faint" style={{ fontSize: 11 }}>{name}</div>
              <div className="tabnum" style={{ fontWeight: 600 }}>{shFmtBytes(logs[name])}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="faint" style={{ fontSize: 11, textAlign: "right" }}>
        auto-refreshes every 15s{refreshedAt ? " · updated " + window.timeAgo(refreshedAt) : ""}
      </div>
    </div>
  );
}

Object.assign(window, { SystemHealthPage });
