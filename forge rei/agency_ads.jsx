// agency_ads.jsx — Meta Ads Analytics tab (Forge AI Agency).
// Spend / performance per client ad account, top vs underperforming ads.
// Static-React: hooks aliased (…Ad), top-level names prefixed Ad, shipped on window.
// Reads the live mock backend (agency_ads.py) via /api/agency/ads + accounts.
const { useState: useStateAd, useEffect: useEffectAd } = React;

// ---- small formatting helpers ----------------------------------------------
const adNum = (n) => (n == null ? "—" : Number(n).toLocaleString());
const adMoney = (n) => (window.fmtMoney ? window.fmtMoney(n) : "$" + adNum(Math.round(Number(n) || 0)));
const adPct = (n) => (n == null ? "—" : Number(n).toFixed(2) + "%");
const adX = (n) => (n == null ? "—" : Number(n).toFixed(2) + "x");

const AD_OBJECTIVE = {
  Leads:       { label: "Leads",       color: "#4F7CFF" },
  Conversions: { label: "Conversions", color: "#22C55E" },
  Awareness:   { label: "Awareness",   color: "#8B5CF6" },
  Traffic:     { label: "Traffic",     color: "#F59E0B" },
};
const AD_STATUS = {
  active:   { label: "Active",   color: "#22C55E" },
  paused:   { label: "Paused",   color: "#64748B" },
  inactive: { label: "Inactive", color: "#64748B" },
};

// ---- Meta connection settings card -----------------------------------------
function AdConnectionCard({ connection }) {
  const Icons = window.Icons;
  const conn = connection || {};
  const isLive = conn.source === "live";

  if (conn.connected) {
    return (
      <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <span style={{ color: "#22C55E" }}><Icons.Check size={18} /></span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>Meta Ads — connected</div>
          <div className="faint" style={{ fontSize: 12, marginTop: 2 }}>
            {isLive
              ? "Live data via META_ACCESS_TOKEN — real spend and performance numbers."
              : "Access token detected via environment (META_ACCESS_TOKEN)."}
          </div>
        </div>
        <window.AgUI.Badge status={isLive ? "active" : "paused"} map={AD_STATUS} />
        {isLive && (
          <span style={{ fontSize: 11, fontWeight: 600, color: "#22C55E",
            background: "#22C55E1f", padding: "3px 9px", borderRadius: 999 }}>LIVE</span>
        )}
      </div>
    );
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12,
      borderColor: "#F59E0B", background: "#F59E0B12" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <span style={{ color: "#F59E0B" }}><Icons.Settings size={18} /></span>
        <span style={{ fontWeight: 600, fontSize: 14.5 }}>Meta Ads — not connected</span>
      </div>
      {conn.todo && <div className="faint" style={{ fontSize: 12.5 }}>{conn.todo}</div>}
      <div style={window.AgUI.field}>
        <span style={window.AgUI.fieldLabel}>Access Token (env: META_ACCESS_TOKEN)</span>
        <input style={{ ...window.AgUI.inp, opacity: 0.6, cursor: "not-allowed" }} disabled
          value={conn.hasToken ? "••••••••" : ""} placeholder="set via environment variable" />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <button className="tab" disabled style={{ opacity: 0.55, cursor: "not-allowed" }}>
          Connect via env
        </button>
        <span className="faint" style={{ fontSize: 11.5 }}>
          Showing mock Meta data. Set META_ACCESS_TOKEN in agency.env to go live.
        </span>
      </div>
    </div>
  );
}

// ---- a generic ads table (campaigns / top ads / weak ads) ------------------
function AdCampaignTable({ rows }) {
  if (!rows || !rows.length) return <div className="faint" style={{ fontSize: 12.5, padding: "4px 2px" }}>No campaigns.</div>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="lead-table" style={{ width: "100%", fontSize: 12.5, minWidth: 720 }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Campaign</th>
            <th style={{ textAlign: "left" }}>Objective</th>
            <th style={{ textAlign: "left" }}>Status</th>
            <th style={{ textAlign: "right" }}>Spend</th>
            <th style={{ textAlign: "right" }}>Clicks</th>
            <th style={{ textAlign: "right" }}>CTR</th>
            <th style={{ textAlign: "right" }}>CPL</th>
            <th style={{ textAlign: "right" }}>ROAS</th>
            <th style={{ textAlign: "right" }}>Leads</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td style={{ fontWeight: 600 }}>{c.name}</td>
              <td><window.AgUI.Badge status={c.objective} map={AD_OBJECTIVE} /></td>
              <td><window.AgUI.Badge status={c.status} map={AD_STATUS} /></td>
              <td className="mono" style={{ textAlign: "right" }}>{adMoney(c.spend)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{adNum(c.clicks)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{adPct(c.ctr)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{adMoney(c.cpl)}</td>
              <td className="mono" style={{ textAlign: "right",
                color: c.roas >= 2 ? "var(--green)" : c.roas < 1 ? "var(--red)" : "var(--text)" }}>{adX(c.roas)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{adNum(c.leads)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AdAdsTable({ rows, accent }) {
  if (!rows || !rows.length) return <div className="faint" style={{ fontSize: 12.5, padding: "4px 2px" }}>No ads.</div>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="lead-table" style={{ width: "100%", fontSize: 12.5, minWidth: 760 }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Ad</th>
            <th style={{ textAlign: "left" }}>Hook</th>
            <th style={{ textAlign: "right" }}>Spend</th>
            <th style={{ textAlign: "right" }}>CTR</th>
            <th style={{ textAlign: "right" }}>CPC</th>
            <th style={{ textAlign: "right" }}>Leads</th>
            <th style={{ textAlign: "right" }}>CPL</th>
            <th style={{ textAlign: "right" }}>ROAS</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td style={{ fontWeight: 600 }}>
                {a.name}
                {a.campaign && <div className="faint" style={{ fontSize: 11, fontWeight: 400 }}>{a.campaign}</div>}
              </td>
              <td className="faint" style={{ maxWidth: 220 }}>{a.hook || "—"}</td>
              <td className="mono" style={{ textAlign: "right" }}>{adMoney(a.spend)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{adPct(a.ctr)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{adMoney(a.cpc)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{adNum(a.leads)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{adMoney(a.cpl)}</td>
              <td className="mono" style={{ textAlign: "right",
                color: accent === "green" ? "var(--green)" : accent === "red" ? "var(--red)" : "var(--text)",
                fontWeight: 600 }}>{adX(a.roas)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- section header with an accent icon -------------------------------------
function AdSectionHead({ icon, title, sub, color }) {
  const Icons = window.Icons;
  const Ico = Icons[icon] || Icons.Analytics;
  const c = color || "var(--text)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
      <span style={{ color: c }}><Ico size={17} /></span>
      <div>
        <div className="card-title" style={{ color: c }}>{title}</div>
        {sub && <div className="faint" style={{ fontSize: 11.5, marginTop: 1 }}>{sub}</div>}
      </div>
    </div>
  );
}

// ---- page -------------------------------------------------------------------
function AgencyAds() {
  const Icons = window.Icons;

  // accounts + connection state
  const acctRes = window.useApi("/api/agency/ads/accounts");
  const accounts = (acctRes.data && acctRes.data.accounts) || [];
  const connection = (acctRes.data && acctRes.data.connection) || {};

  // selected ad account — defaults to the first account once they load
  const [selectedAcct, setSelectedAcct] = useStateAd("");
  useEffectAd(() => {
    if (!selectedAcct && accounts.length) setSelectedAcct(accounts[0].id);
  }, [accounts, selectedAcct]);

  // analytics — path is keyed on the account so it auto-refetches on change
  const analyticsPath = selectedAcct ? `/api/agency/ads?account=${selectedAcct}` : `/api/agency/ads`;
  const { data, loading, error, refresh } = window.useApi(analyticsPath, { interval: 30000 });

  const totals = (data && data.totals) || {};
  const acctName = (data && data.account && data.account.name) || "";

  // 10-metric grid built from totals
  const cards = [
    { label: "Spend",       value: totals.spend,       prefix: "$", icon: "Dollar",   color: "#22C55E" },
    { label: "Impressions", value: totals.impressions,              icon: "Activity", color: "#4F7CFF" },
    { label: "Reach",       value: totals.reach,                    icon: "Leads",    color: "#8B5CF6" },
    { label: "Clicks",      value: totals.clicks,                   icon: "Target",   color: "#06B6D4" },
    { label: "CTR",         value: totals.ctr,         suffix: "%", icon: "Trend",    color: "#F59E0B" },
    { label: "CPC",         value: totals.cpc,         prefix: "$", icon: "Dollar",   color: "#EAB308" },
    { label: "Leads",       value: totals.leads,                    icon: "Leads",    color: "#4F7CFF" },
    { label: "CPL",         value: totals.cpl,         prefix: "$", icon: "Dollar",   color: "#F97316" },
    { label: "Conversions", value: totals.conversions,              icon: "Check",    color: "#16A34A" },
    { label: "ROAS",        value: totals.roas,        suffix: "x", icon: "Trend",    color: "#22C55E" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* header */}
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Meta Ads Analytics</h1>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>
          Spend, performance, and the ads that work — per client account.
        </div>
      </div>

      {/* connection settings */}
      <AdConnectionCard connection={connection} />

      {/* controls */}
      <div className="card card-pad" style={{ display: "flex", alignItems: "flex-end", gap: 14, flexWrap: "wrap" }}>
        <div style={{ ...window.AgUI.field, minWidth: 240 }}>
          <span style={window.AgUI.fieldLabel}>Ad account</span>
          <select style={window.AgUI.inp} value={selectedAcct}
            onChange={(e) => setSelectedAcct(e.target.value)}>
            {!accounts.length && <option value="">No ad accounts</option>}
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <button className="tab" onClick={refresh} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Icons.Activity size={14} /> Refresh
        </button>
        {acctName && <span className="faint" style={{ fontSize: 12, marginLeft: "auto" }}>
          {acctName}{data && data.days ? ` · last ${data.days} days` : ""}</span>}
      </div>

      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {loading && !data && <window.LoadingRow label="Loading Meta Ads analytics…" />}

      {data && (
        <React.Fragment>
          {/* totals — 10 analytics cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 14 }}>
            {cards.map((k) => <window.AgUI.AnalyticsCard key={k.label} {...k} />)}
          </div>

          {/* campaigns */}
          <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <AdSectionHead icon="Marketing" title="Campaigns"
              sub="Performance by campaign" color="#4F7CFF" />
            <AdCampaignTable rows={data.campaigns} />
          </div>

          {/* top ads */}
          <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12,
            borderColor: "#22C55E55" }}>
            <AdSectionHead icon="Flame" title="Top-performing ads"
              sub="Highest ROAS — scale these" color="#22C55E" />
            <AdAdsTable rows={data.topAds} accent="green" />
          </div>

          {/* weak ads */}
          <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12,
            borderColor: "#EF444455" }}>
            <AdSectionHead icon="Activity" title="Underperforming — pause or rework"
              sub="Lowest ROAS — cut or rebuild the creative" color="#EF4444" />
            <AdAdsTable rows={data.weakAds} accent="red" />
          </div>
        </React.Fragment>
      )}

      {!loading && !data && !error && (
        <div className="card empty" style={{ minHeight: "30vh" }}>
          <div className="empty-ico" style={{ width: 72, height: 72 }}><Icons.Ads size={30} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>No ad data yet</div>
          <div style={{ fontSize: 13, maxWidth: 340, textAlign: "center" }}>
            Pick an ad account to see spend and performance.
          </div>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { AgencyAds });
