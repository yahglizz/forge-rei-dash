// daycare_growth.jsx — Ads + Social monitoring for the daycare business.
// Reuses the Agency Meta/Metricool engines with the daycare's own credentials.
// Renders cleanly in "mock" mode until META_ACCESS_TOKEN / METRICOOL_USER_TOKEN
// are added to daycare.env, then lights up live — no rebuild.
const { useState: useStateDca } = React;

function DcaConnBadge({ conn }) {
  const live = conn && (conn.connected || conn.source === "live");
  return <span className={"dc-live " + (live ? "" : "dc-mock")} style={live ? null : { color: "#F4B860", borderColor: "rgba(244,184,96,.4)" }}>
    <i style={live ? null : { background: "#F4B860" }} /> {live ? "LIVE" : "NOT CONNECTED"}
  </span>;
}

function DcaTodo({ conn }) {
  if (!conn || conn.connected || conn.source === "live" || !conn.todo) return null;
  return <div className="dc-form-hint"><window.Icons.Shield size={14} /> {conn.todo}</div>;
}

function DcaNum(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) ? n : (fallback === undefined ? 0 : fallback);
}

function DaycareAds() {
  const res = window.DcxUseResource("/ads", "dc-ads", 60000);
  const data = res.data || {};
  const conn = data.connection || {};
  const totals = (data.analytics && (data.analytics.totals || data.analytics.summary)) || {};
  const campaigns = (data.analytics && (data.analytics.campaigns || [])) || [];
  const topAds = (data.analytics && (data.analytics.topAds || [])) || [];
  const spend = DcaNum(totals.spend ?? totals.amountSpent);
  const leads = DcaNum(totals.leads ?? totals.results);
  const roas = totals.roas != null ? totals.roas : (totals.cpl != null ? null : null);
  const cpl = totals.cpl != null ? DcaNum(totals.cpl) : (leads ? spend / leads : 0);
  return <div className="dc-page">
    <window.DcxPageHead title="Ads" eyebrow="GROWTH · META" copy="Monitor the daycare's Meta ad performance. Launching campaigns stays approval-gated." actions={<DcaConnBadge conn={conn} />} />
    <DcaTodo conn={conn} />
    <div className="dc-kpi-grid">
      <window.DcxKpi label="Spend" value={window.DcxMoney(spend)} sub={(data.analytics && data.analytics.days ? data.analytics.days + "-day window" : "recent window")} icon="Dollar" />
      <window.DcxKpi label="Leads" value={leads} sub="from ads" icon="Children" color="#22C55E" />
      <window.DcxKpi label="Cost / Lead" value={window.DcxMoney(cpl)} sub="blended CPL" icon="Billing" color="#F4B860" />
      <window.DcxKpi label="Campaigns" value={campaigns.length} sub="active" icon="Doc" color="#8B5CF6" />
    </div>
    <window.DcxState loading={res.loading} error={res.error} onRetry={res.refresh} />
    {campaigns.length > 0 && <div className="card dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Campaign</th><th>Spend</th><th>Leads</th><th>CPL</th><th>ROAS</th></tr></thead><tbody>{campaigns.map((c, i) => <tr key={c.id || i}><td><b>{c.name || "Campaign"}</b></td><td className="tabnum">{window.DcxMoney(DcaNum(c.spend))}</td><td className="tabnum">{DcaNum(c.leads)}</td><td className="tabnum">{window.DcxMoney(DcaNum(c.cpl))}</td><td className="tabnum">{c.roas != null ? DcaNum(c.roas) + "x" : "—"}</td></tr>)}</tbody></table></div>}
    {topAds.length > 0 && <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Top performers</div><div className="faint">Best ads in the window</div></div></div><div className="dc-day-grid">{topAds.slice(0, 4).map((ad, i) => <button key={ad.id || i} style={{ cursor: "default" }}><b>{ad.name || "Ad"}</b><small>{DcaNum(ad.leads)} leads · {window.DcxMoney(DcaNum(ad.spend))}</small></button>)}</div></div>}
  </div>;
}

function DaycareSocial() {
  const res = window.DcxUseResource("/social", "dc-social", 60000);
  const data = res.data || {};
  const conn = data.connection || {};
  const analytics = data.analytics || {};
  const postsRaw = data.posts;
  const posts = Array.isArray(postsRaw) ? postsRaw : (postsRaw && Array.isArray(postsRaw.posts) ? postsRaw.posts : []);
  const followers = DcaNum(analytics.followers ?? analytics.audience);
  const engagement = analytics.engagement != null ? analytics.engagement : (analytics.engagementRate != null ? analytics.engagementRate : null);
  const reach = DcaNum(analytics.reach ?? analytics.impressions);
  const best = data.bestTime || {};
  return <div className="dc-page">
    <window.DcxPageHead title="Social" eyebrow="GROWTH · METRICOOL" copy="Watch the daycare's social presence. Scheduling posts stays approval-gated." actions={<DcaConnBadge conn={conn} />} />
    <DcaTodo conn={conn} />
    <div className="dc-kpi-grid">
      <window.DcxKpi label="Followers" value={followers} sub="across networks" icon="Children" />
      <window.DcxKpi label="Reach" value={reach} sub="recent window" icon="Bell" color="#38BDF8" />
      <window.DcxKpi label="Engagement" value={engagement != null ? engagement + "%" : "—"} sub="avg rate" icon="Attendance" color="#22C55E" />
      <window.DcxKpi label="Scheduled" value={posts.length} sub="upcoming posts" icon="Calendar" color="#8B5CF6" />
    </div>
    <window.DcxState loading={res.loading} error={res.error} onRetry={res.refresh} />
    <div className="dc-main-grid">
      <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Scheduled posts</div><div className="faint">Queued across connected networks</div></div><b>{posts.length}</b></div>{posts.length ? <div className="dc-alert-list">{posts.slice(0, 6).map((p, i) => <div key={p.id || i}><span className="dc-severity info" /><div><b>{p.text || p.caption || p.title || "Post"}</b><small>{(p.network || p.provider || "social") + " · " + (p.scheduled_at || p.date || p.status || "queued")}</small></div></div>)}</div> : <div className="dc-all-clear"><window.Icons.Calendar size={22} /><div><b>No posts scheduled</b><span>Connect Metricool and schedule from the approval queue.</span></div></div>}</div>
      <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Best time to post</div><div className="faint">By network</div></div></div>{best && (best.network || best.hour || best.times) ? <dl className="dc-details"><div><dt>Network</dt><dd>{best.network || "—"}</dd></div><div><dt>Best hour</dt><dd>{best.hour != null ? best.hour + ":00" : (best.time || "—")}</dd></div><div><dt>Source</dt><dd>{conn.source || "mock"}</dd></div></dl> : <div className="dc-inline-empty">Best-time insights appear once Metricool is connected.</div>}</div>
    </div>
  </div>;
}

function DaycareGrowth() {
  const [tab, setTab] = useStateDca("ads");
  return <div className="dc-page">
    <div className="dc-hero" style={{ marginBottom: 14 }}><div><div className="dc-eyebrow">GROWTH ENGINE</div><h1>Run the ads. Watch the socials.</h1><p>The daycare's marketing command center — Meta ads and social insights in one place. Outward actions (launching ads, publishing posts) stay behind your one-tap approval.</p><div className="dc-hero-actions"><button className={tab === "ads" ? "dc-primary" : "dc-outline"} onClick={() => setTab("ads")}><window.Icons.Dollar size={15} /> Ads</button><button className={tab === "social" ? "dc-primary" : "dc-outline"} onClick={() => setTab("social")}><window.Icons.Bell size={15} /> Social</button></div></div></div>
    {tab === "ads" ? <DaycareAds /> : <DaycareSocial />}
  </div>;
}

Object.assign(window, { DaycareGrowth, DaycareAds, DaycareSocial });
