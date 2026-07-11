// cost.jsx — "Costs" tab (REI). How much money the OS burns to run: Claude tokens (auto),
// GHL SMS (auto), fixed monthly services (manual). Daily + month-to-date totals, a 14-day
// trend, and a monthly cap alert. Reads /api/cost/status; writes /api/cost/manual +
// /api/cost/settings. Additive, window-global, unique Ct* names + useStateCt alias.
const { useState: useStateCt } = React;

const CT_GREEN = "#22C55E", CT_AMBER = "#F59E0B", CT_RED = "#EF4444";

const ctInp = {
  background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 9,
  padding: "9px 11px", color: "var(--text)", fontSize: 13, width: "100%", outline: "none",
};

function ctUsd(n, digits) {
  const v = Number(n) || 0;
  return "$" + v.toFixed(digits === undefined ? 2 : digits);
}

function CtStat({ label, value, sub, color }) {
  return (
    <div className="card card-pad" style={{ textAlign: "center" }}>
      <div className="tabnum" style={{ fontSize: 22, fontWeight: 700, color: color || "var(--text)" }}>{value}</div>
      <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>{label}</div>
      {sub ? <div className="faint" style={{ fontSize: 10.5, marginTop: 1 }}>{sub}</div> : null}
    </div>
  );
}

function CtTrend({ trend }) {
  const rows = Array.isArray(trend) ? trend : [];
  if (!rows.length) {
    return <div className="faint" style={{ fontSize: 12.5, padding: "10px 4px" }}>
      No usage logged yet — costs appear as the agents run.</div>;
  }
  const max = Math.max(0.01, ...rows.map((r) => Number(r.usd) || 0));
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 5, height: 74, padding: "4px 2px" }}>
      {rows.map((r) => {
        const v = Number(r.usd) || 0;
        const h = Math.max(3, Math.round((v / max) * 64));
        return (
          <div key={r.day} title={r.day + " · " + ctUsd(v)}
            style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
            <div style={{ width: "100%", height: h, borderRadius: 3, background: "var(--accent, #4F7CFF)", opacity: 0.85 }} />
            <div className="faint" style={{ fontSize: 8.5 }}>{r.day.slice(8)}</div>
          </div>
        );
      })}
    </div>
  );
}

function CtFixedForm({ onSaved }) {
  const [f, setF] = useStateCt({ service: "", monthlyUSD: "", note: "" });
  const [saving, setSaving] = useStateCt(false);
  const [err, setErr] = useStateCt(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  async function submit() {
    if (!f.service.trim()) { setErr("Service name required"); return; }
    setSaving(true); setErr(null);
    try {
      await window.apiPost("/api/cost/manual", {
        service: f.service, monthlyUSD: Number(f.monthlyUSD) || 0, note: f.note });
      setF({ service: "", monthlyUSD: "", note: "" });
      onSaved && onSaved();
    } catch (e) { setErr(e.message || "Save failed"); }
    setSaving(false);
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 9 }}>
        <div>
          <div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Service</div>
          <input style={ctInp} value={f.service} onChange={(e) => set("service", e.target.value)}
            placeholder="digitalocean, retell…" />
        </div>
        <div>
          <div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Monthly $</div>
          <input style={ctInp} type="number" value={f.monthlyUSD}
            onChange={(e) => set("monthlyUSD", e.target.value)} placeholder="24" />
        </div>
      </div>
      <input style={ctInp} value={f.note} onChange={(e) => set("note", e.target.value)}
        placeholder="note (optional)" />
      {err && <div style={{ color: "var(--red)", fontSize: 12 }}>{err}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button className="tab" onClick={submit} disabled={saving}>
          {saving ? "Saving…" : "Save fixed cost"}
        </button>
      </div>
      <div className="faint" style={{ fontSize: 10.5 }}>
        Enter 0 to remove a service. Fixed costs prorate into the month-to-date total.
      </div>
    </div>
  );
}

function CtCapForm({ current, onSaved }) {
  const [cap, setCap] = useStateCt(current || "");
  const [saving, setSaving] = useStateCt(false);
  async function submit() {
    setSaving(true);
    try {
      await window.apiPost("/api/cost/settings", { monthlyCapUSD: Number(cap) || 0 });
      onSaved && onSaved();
    } catch (e) { /* surfaced by refresh */ }
    setSaving(false);
  }
  return (
    <div style={{ display: "flex", gap: 9, alignItems: "center" }}>
      <input style={{ ...ctInp, width: 110 }} type="number" value={cap}
        onChange={(e) => setCap(e.target.value)} placeholder="cap $/mo" />
      <button className="tab" onClick={submit} disabled={saving}>
        {saving ? "…" : "Set cap"}
      </button>
      <div className="faint" style={{ fontSize: 10.5 }}>0 = alert off</div>
    </div>
  );
}

function CostPage() {
  const Icons = window.Icons;
  const Ico = (Icons && Icons.Dollar) || Icons.Bot;
  const { data, error, loading, refresh, refreshedAt } = window.useApi(
    "/api/cost/status", { interval: 30000 });

  if (loading && !data) return <window.LoadingRow label="Adding up the bills…" />;
  if (error && !data) return <window.ErrorRow error={error} onRetry={refresh} />;

  const d = data || {};
  const today = d.today || {};
  const mtd = d.mtd || {};
  const fixed = d.fixed || {};
  const capColor = d.capAlert ? CT_RED : d.capWarn ? CT_AMBER : CT_GREEN;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Verdict banner */}
      <div className="card card-pad" style={{
        display: "flex", alignItems: "center", gap: 14,
        borderColor: d.capAlert ? "var(--red)" : "var(--card-2)",
      }}>
        <span style={{ color: capColor }}><Ico size={22} /></span>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 17, fontWeight: 700 }}>
            {ctUsd(mtd.totalUSD)} <span className="faint" style={{ fontSize: 12, fontWeight: 400 }}>this month</span>
          </div>
          <div className="faint" style={{ fontSize: 12 }}>
            claude {ctUsd(mtd.claudeUSD)} · sms {ctUsd(mtd.smsUSD)} · fixed {ctUsd(mtd.fixedUSD)}
            {d.monthlyCapUSD ? " · cap " + ctUsd(d.monthlyCapUSD, 0) : ""}
            {d.capAlert ? " — OVER CAP" : d.capWarn ? " — 80% of cap" : ""}
          </div>
        </div>
        <button className="tab" onClick={refresh}>Refresh</button>
      </div>

      {/* Today tally */}
      <div className="card-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
        <CtStat label="Spent today" value={ctUsd(today.usd)} color={CT_GREEN} />
        <CtStat label="Claude today" value={ctUsd(today.claudeUSD)}
          sub={(today.claudeIn || 0) + " in / " + (today.claudeOut || 0) + " out tok"} />
        <CtStat label="Texts today" value={today.sms || 0}
          sub={"@ " + ctUsd(d.smsRate, 4) + "/msg"} />
        <CtStat label="Fixed monthly" value={ctUsd(d.fixedMonthlyUSD)} />
      </div>

      {/* Trend */}
      <div className="card card-pad">
        <div className="card-title" style={{ fontSize: 15, marginBottom: 6 }}>Last 14 days (usage $)</div>
        <CtTrend trend={d.trend} />
      </div>

      {/* Fixed services + cap */}
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 12 }}>
        <div className="card card-pad">
          <div className="card-title" style={{ fontSize: 15, marginBottom: 8 }}>Fixed monthly services</div>
          {Object.keys(fixed).length === 0 && (
            <div className="faint" style={{ fontSize: 12.5, marginBottom: 8 }}>
              Nothing yet — add the droplet, Retell, or any flat bill below.
            </div>
          )}
          {Object.keys(fixed).map((k) => (
            <div key={k} style={{
              display: "flex", justifyContent: "space-between", padding: "7px 2px",
              borderBottom: "1px solid var(--card-2)", fontSize: 13,
            }}>
              <div>
                <span style={{ fontWeight: 600 }}>{k}</span>
                {fixed[k].note ? <span className="faint" style={{ fontSize: 11 }}> · {fixed[k].note}</span> : null}
              </div>
              <div className="tabnum" style={{ fontWeight: 600 }}>{ctUsd(fixed[k].monthlyUSD)}/mo</div>
            </div>
          ))}
          <div style={{ marginTop: 10 }}>
            <CtFixedForm onSaved={refresh} />
          </div>
        </div>
        <div className="card card-pad">
          <div className="card-title" style={{ fontSize: 15, marginBottom: 8 }}>Monthly cap alert</div>
          <div className="faint" style={{ fontSize: 12, marginBottom: 10 }}>
            Card turns amber at 80%, red over the cap. Also flagged in the daily brief.
          </div>
          <CtCapForm current={d.monthlyCapUSD} onSaved={refresh} />
        </div>
      </div>

      <div className="faint" style={{ fontSize: 11, textAlign: "right" }}>
        auto-refreshes every 30s{refreshedAt ? " · updated " + window.timeAgo(refreshedAt) : ""}
      </div>
    </div>
  );
}

Object.assign(window, { CostPage });
