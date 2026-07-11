// analytics.jsx — Messages Analytics tab + AI Weekly Review panel.
const { useState: useStateAn } = React;

const CLS_C = { READY: "#22C55E", PRICE: "#F59E0B", NRN: "#8B5CF6", HELP: "#EF4444", CONTINUE: "#4F7CFF", DNC: "#64748B" };

function BarRow({ label, value, max, color }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "4px 0" }}>
      <div style={{ width: 96, fontSize: 12, textAlign: "right", flexShrink: 0 }} className="faint">{label}</div>
      <div style={{ flex: 1, height: 18, background: "var(--card-2)", borderRadius: 6, overflow: "hidden" }}>
        <div style={{ width: pct + "%", height: "100%", background: color || "#4F7CFF", borderRadius: 6, transition: "width .5s" }} />
      </div>
      <div className="tabnum" style={{ width: 44, fontSize: 12.5, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

function ChartCard({ title, children, sub }) {
  return (
    <div className="card card-pad">
      <div className="card-title" style={{ fontSize: 15, marginBottom: sub ? 2 : 12 }}>{title}</div>
      {sub && <div className="faint" style={{ fontSize: 11.5, marginBottom: 12 }}>{sub}</div>}
      {children}
    </div>
  );
}

// minimal markdown -> elements (headings, bullets, bold)
function Md({ text }) {
  if (!text) return null;
  const lines = text.split("\n");
  const out = [];
  lines.forEach((ln, i) => {
    const bold = (s) => s.split(/(\*\*[^*]+\*\*)/g).map((p, j) =>
      p.startsWith("**") ? <b key={j}>{p.slice(2, -2)}</b> : p);
    if (/^###?\s/.test(ln)) out.push(<div key={i} style={{ fontSize: 14, fontWeight: 700, marginTop: 14, marginBottom: 4 }}>{ln.replace(/^#+\s/, "")}</div>);
    else if (/^\s*[-*]\s/.test(ln)) out.push(<div key={i} style={{ fontSize: 13, lineHeight: 1.5, paddingLeft: 14, marginBottom: 2 }}>• {bold(ln.replace(/^\s*[-*]\s/, ""))}</div>);
    else if (ln.trim()) out.push(<div key={i} style={{ fontSize: 13, lineHeight: 1.5, marginBottom: 4 }}>{bold(ln)}</div>);
  });
  return <div>{out}</div>;
}

function WeeklyReview() {
  const Icons = window.Icons;
  const { data, refresh } = window.useApi("/api/review/latest", { interval: 0 });
  const [running, setRunning] = useStateAn(false);
  const [err, setErr] = useStateAn(null);
  const r = data || {};

  async function run() {
    setRunning(true); setErr(null);
    try {
      const res = await window.apiPost("/api/review/run", { days: 7 });
      if (res.needsKey) setErr(res.message || "Add ANTHROPIC_API_KEY to enable.");
      refresh();
    } catch (e) { setErr(e.message); }
    setRunning(false);
  }

  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ color: "var(--violet)" }}><Icons.Spark size={18} /></span>
          <span className="card-title" style={{ fontSize: 16 }}>AI Weekly Review</span>
          {r.stamp && <span className="faint" style={{ fontSize: 11.5 }}>· {r.stamp}</span>}
        </div>
        <button onClick={run} disabled={running}
          style={{ display: "flex", alignItems: "center", gap: 7, padding: "9px 16px", borderRadius: 11, background: "linear-gradient(135deg,#8B5CF6,#6d28d9)", fontWeight: 600, fontSize: 13.5, color: "#fff", opacity: running ? 0.6 : 1 }}>
          <Icons.Spark size={15} /> {running ? "Running analysts…" : "Run analysis now"}
        </button>
      </div>

      {err && <div className="card" style={{ padding: 12, borderColor: "var(--orange)", fontSize: 12.5, marginBottom: 12 }}>{err}</div>}
      {(r.needsKey && !r.hasReview) && (
        <div className="empty" style={{ padding: 28 }}>
          <div className="empty-ico"><Icons.Spark size={24} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)" }}>Add your Anthropic key to switch this on</div>
          <div style={{ fontSize: 12.5, maxWidth: 360 }}>Put <span className="mono">ANTHROPIC_API_KEY=sk-ant-…</span> in <span className="mono">ghl.env</span> and restart. Then Marcus + the weekly review go live.</div>
        </div>
      )}
      {running && (
        <div className="faint" style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 12.5, padding: 8 }}>
          <span className="dot online pulse" /> 5 analysts running in parallel + synthesizing…
        </div>
      )}
      {r.hasReview && (
        <div>
          <div className="faint" style={{ fontSize: 11.5, marginBottom: 8 }}>
            {r.analysts ? r.analysts.length : 0} analysts · {r.scope} conversations · {r.elapsedSec}s · saved to brain → <span className="mono">{r.logPath}</span>{r.committed ? " (git ✓)" : ""}
          </div>
          <div style={{ maxHeight: 460, overflowY: "auto", paddingRight: 8 }}><Md text={r.report} /></div>
        </div>
      )}
    </div>
  );
}

function AnalyticsPage() {
  const Icons = window.Icons;
  const { data, error, loading, refresh } = window.useApi("/api/analytics?days=30", { interval: 0 });
  const d = data || {};
  const v = d.volume || {};
  const lat = d.latency || {};
  const cls = d.classification || {};
  const ch = d.channels || {};
  const markets = d.markets || {};
  const dow = (d.timing || {}).byDow || {};

  const fmtLat = (s) => s == null ? "—" : s < 90 ? Math.round(s) + "s" : s < 5400 ? Math.round(s / 60) + "m" : (s / 3600).toFixed(1) + "h";
  const clsMax = Math.max(1, ...Object.values(cls));
  const chMax = Math.max(1, ...Object.values(ch));
  const mkMax = Math.max(1, ...Object.values(markets));
  const dowOrder = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const dowMax = Math.max(1, ...Object.values(dow));

  const kpis = [
    { label: "Response Rate", val: (d.responseRate || 0) + "%", color: "#22C55E", icon: "Trend" },
    { label: "Unanswered", val: v.unanswered || 0, color: "#EF4444", icon: "Message" },
    { label: "Hot Signals", val: d.hotSignals || 0, color: "#F59E0B", icon: "Flame", sub: "READY + PRICE" },
    { label: "Median Reply", val: fmtLat(lat.medianReplySeconds), color: "#4F7CFF", icon: "Activity" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Messages Analytics</h1>
          <p className="faint" style={{ fontSize: 13.5, marginTop: 3 }}>
            {data ? `${d.scope} recent conversations · last ${d.days} days` : "Crunching GoHighLevel messages…"}
          </p>
        </div>
        <button className="tab" onClick={refresh} style={{ display: "flex", alignItems: "center", gap: 7, border: "1px solid var(--border)" }}>
          <Icons.Activity size={15} /> {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {loading && !data && <window.LoadingRow label="Aggregating conversations + sampling threads…" />}

      <div className="kpi-row">
        {kpis.map((k) => {
          const Ico = Icons[k.icon] || Icons.Activity;
          return (
          <div className="kpi" key={k.label}>
            <div className="kpi-ico" style={{ background: k.color + "1f", color: k.color }}><Ico size={18} /></div>
            <div className="kpi-label">{k.label}</div>
            <div className="kpi-val">{typeof k.val === "number" ? <window.CountUp to={k.val} /> : <span className="tabnum">{k.val}</span>}</div>
            <div className="kpi-delta"><span className="faint">{k.sub || "live · GoHighLevel"}</span></div>
          </div>
          );
        })}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <ChartCard title="What sellers are saying" sub="Marcus classification of inbound-last conversations">
          {Object.keys(cls).length === 0 && <div className="faint" style={{ fontSize: 12.5 }}>No inbound-last conversations in window.</div>}
          {Object.entries(cls).sort((a, b) => b[1] - a[1]).map(([k, val]) =>
            <BarRow key={k} label={k} value={val} max={clsMax} color={CLS_C[k] || "#4F7CFF"} />)}
        </ChartCard>

        <ChartCard title="Inbound by day" sub="When sellers text you back">
          {dowOrder.map((day) => <BarRow key={day} label={day} value={dow[day] || 0} max={dowMax} color="#2DD4BF" />)}
        </ChartCard>

        <ChartCard title="Channel mix">
          {Object.entries(ch).sort((a, b) => b[1] - a[1]).map(([k, val]) =>
            <BarRow key={k} label={k} value={val} max={chMax} color="#8B5CF6" />)}
        </ChartCard>

        <ChartCard title="Top markets" sub="By contact tag volume">
          {Object.keys(markets).length === 0 && <div className="faint" style={{ fontSize: 12.5 }}>No market tags found.</div>}
          {Object.entries(markets).slice(0, 7).map(([k, val]) =>
            <BarRow key={k} label={k.length > 14 ? k.slice(0, 13) + "…" : k} value={val} max={mkMax} color="#4F7CFF" />)}
        </ChartCard>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
        {[
          { l: "Outbound last", v: v.outboundLast || 0 },
          { l: "Inbound last", v: v.inboundLast || 0 },
          { l: "Avg turns", v: lat.avgTurns || 0 },
          { l: "Marcus sent", v: (d.marcus || {}).sent || 0 },
        ].map((s) => (
          <div className="card card-pad" key={s.l} style={{ textAlign: "center" }}>
            <div className="tabnum" style={{ fontSize: 24, fontWeight: 700 }}>{s.v}</div>
            <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>{s.l}</div>
          </div>
        ))}
      </div>

      <WeeklyReview />
    </div>
  );
}

window.AnalyticsPage = AnalyticsPage;
