// daycare_growth.jsx — Ads + Social monitoring for the daycare business.
// Reuses the Agency Meta/Metricool engines with the daycare's own credentials.
// Renders cleanly in "mock" mode until META_ACCESS_TOKEN / METRICOOL_USER_TOKEN
// are added to daycare.env, then lights up live — no rebuild.
const { useState: useStateDca, useEffect: useEffectDca, useRef: useRefDca } = React;

function DcaConnBadge({ conn }) {
  if (conn && conn.source === "auth_error") return <span className="dc-live dc-mock" style={{ color: "#EF4444", borderColor: "rgba(239,68,68,.45)" }}>
    <i style={{ background: "#EF4444" }} /> TOKEN REJECTED — replace it
  </span>;
  const live = conn && (conn.connected || conn.source === "live");
  return <span className={"dc-live " + (live ? "" : "dc-mock")} style={live ? null : { color: "#F4B860", borderColor: "rgba(244,184,96,.4)" }}>
    <i style={live ? null : { background: "#F4B860" }} /> {live ? "LIVE" : "NOT CONNECTED"}
  </span>;
}

function DcaTodo({ conn }) {
  if (!conn || conn.connected || conn.source === "live" || !conn.todo) return null;
  return <div className="dc-form-hint"><window.Icons.Shield size={14} /> {conn.todo}</div>;
}

// Creed badge beside a metric that isn't live Meta data (agency_ads.dataSource).
function DcaDataBadge({ src }) {
  if (!src || src === "live") return null;
  const bad = src === "token_rejected";
  const c = bad ? "#EF4444" : "#F4B860";
  return <span className="dc-live dc-mock" style={{ color: c, borderColor: c }}>
    <i style={{ background: c }} /> {bad ? "TOKEN REJECTED — replace it" : src === "none" ? "NO AD DATA" : "MOCK DATA"}
  </span>;
}

function DcaDateRange(a) {
  const r = a && a.dateRange;
  return r && r.since ? r.since + " → " + r.until : (a && a.days ? a.days + "-day window" : "recent window");
}

function DcaNum(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) ? n : (fallback === undefined ? 0 : fallback);
}

function DaycareAds() {
  // Same Meta-style range picker as the Dashboard card (shared remembered range).
  const [range, setRangeState] = useStateDca(() => {
    const saved = DcaLsGet(DCA_RANGE_KEY, null);
    return saved && saved.preset ? saved : { preset: "last_30d", since: null, until: null, compare: false };
  });
  const setRange = (r) => { setRangeState(r); DcaLsSet(DCA_RANGE_KEY, r); };
  const res = window.DcxUseResource("/ads?" + DcaRangeQuery(range), "dc-ads", 60000);
  const data = (res.data && !Array.isArray(res.data)) ? res.data : {};
  const rr = (data.analytics && data.analytics.dateRange) || {};
  const todayA = ((data.analytics && data.analytics.fetchedAt) || "").slice(0, 10) || DcaIso(new Date(Date.now() - new Date().getTimezoneOffset() * 60000));
  const freshA = rr.preset === range.preset && (range.preset !== "custom" || (rr.since === range.since && rr.until === range.until));
  const guessA = range.preset === "custom" ? [range.since, range.until] : DcaResolve(range.preset, todayA);
  const shownA = { ...range, since: freshA ? rr.since : guessA[0], until: freshA ? rr.until : guessA[1] };
  const conn = data.connection || {};
  const totals = (data.analytics && (data.analytics.totals || data.analytics.summary)) || {};
  const campaigns = (data.analytics && (data.analytics.campaigns || [])) || [];
  const topAds = (data.analytics && (data.analytics.topAds || [])) || [];
  const spend = DcaNum(totals.spend ?? totals.amountSpent);
  const leads = DcaNum(totals.leads ?? totals.results);
  const roas = totals.roas != null ? totals.roas : (totals.cpl != null ? null : null);
  const cpl = totals.cpl != null ? DcaNum(totals.cpl) : (leads ? spend / leads : null);
  return <div className="dc-page">
    <window.DcxPageHead title="Ads" eyebrow="GROWTH · META" copy="Monitor the daycare's Meta ad performance. Launching campaigns stays approval-gated." actions={data.connection ? <DcaConnBadge conn={conn} /> : null} />
    <div style={{ marginBottom: 10 }}><DcaRangePicker value={shownA} today={todayA} tz={rr.tz || ""} onChange={setRange} /></div>
    {data.analytics && data.analytics.unknown && <div className="dc-form-hint" style={{ color: "#F4B860" }}>Ad numbers Unknown — {data.analytics.error}</div>}
    <DcaTodo conn={conn} />
    {data.analytics && <DcaDataBadge src={data.analytics.dataSource} />}
    {!(data.analytics && data.analytics.unknown) && <div className="dc-kpi-grid">
      <window.DcxKpi label="Spend" value={window.DcxMoney(spend)} sub={DcaDateRange(data.analytics)} icon="Dollar" />
      <window.DcxKpi label="Leads" value={leads} sub="from ads" icon="Children" color="#22C55E" />
      <window.DcxKpi label="Cost / Lead" value={cpl != null ? window.DcxMoney(cpl) : "—"} sub="blended CPL" icon="Billing" color="#F4B860" />
      <window.DcxKpi label="Campaigns" value={campaigns.length} sub={campaigns.some((c) => c.status) ? campaigns.filter((c) => String(c.status).toLowerCase() === "active").length + " active" : "in window"} icon="Doc" color="#8B5CF6" />
    </div>}
    <window.DcxState loading={res.loading} error={res.error} onRetry={res.refresh} />
    {campaigns.length > 0 && <div className="card dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Campaign</th><th>Spend</th><th>Leads</th><th>CPL</th><th>ROAS</th></tr></thead><tbody>{campaigns.map((c, i) => <tr key={c.id || i}><td><b>{c.name || "Campaign"}</b></td><td className="tabnum">{window.DcxMoney(DcaNum(c.spend))}</td><td className="tabnum">{DcaNum(c.leads)}</td><td className="tabnum">{c.cpl != null && DcaNum(c.leads) ? window.DcxMoney(DcaNum(c.cpl)) : "—"}</td><td className="tabnum">{c.roas != null ? DcaNum(c.roas) + "x" : "—"}</td></tr>)}</tbody></table></div>}
    {topAds.length > 0 && <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Top performers</div><div className="faint">Best ads in the window</div></div></div><div className="dc-day-grid">{topAds.slice(0, 4).map((ad, i) => <button key={ad.id || i} style={{ cursor: "default" }}><b>{ad.name || "Ad"}</b><small>{DcaNum(ad.leads)} leads · {window.DcxMoney(DcaNum(ad.spend))}</small></button>)}</div></div>}
  </div>;
}

// ── Dashboard card: enrollment ads at a glance (Meta via Pipeboard) ─────────
// Read-only. Own resource + own error state so a Pipeboard hiccup never breaks the
// Daycare Dashboard around it. Same /api/daycare/ads the Growth → Ads tab reads.
// Dates are resolved by the BACKEND in the ad account's timezone (ads_range.py — Meta's own
// picker semantics); this file only mirrors them for the calendar preview.
const DCA_PRESETS = [["today", "Today"], ["yesterday", "Yesterday"], ["today_and_yesterday", "Today and yesterday"],
  ["last_7d", "Last 7 days"], ["last_14d", "Last 14 days"], ["last_28d", "Last 28 days"], ["last_30d", "Last 30 days"],
  ["last_90d", "Last 90 days"], ["this_week", "This week"], ["last_week", "Last week"], ["this_month", "This month"],
  ["last_month", "Last month"], ["maximum", "Maximum"]];
const DCA_RANGE_KEY = "dca_ads_range_v1";
const DCA_RECENT_KEY = "dca_ads_recent_v1";
const DCA_TZ_NAMES = { "America/New_York": "Eastern Time", "America/Chicago": "Central Time",
  "America/Denver": "Mountain Time", "America/Los_Angeles": "Pacific Time", "America/Phoenix": "Arizona Time" };

function DcaD(iso) { const p = String(iso).split("-").map(Number); return new Date(Date.UTC(p[0], p[1] - 1, p[2] || 1)); }
function DcaIso(d) { return d.toISOString().slice(0, 10); }
function DcaAdd(iso, n) { const d = DcaD(iso); d.setUTCDate(d.getUTCDate() + n); return DcaIso(d); }
function DcaFmt(iso, opts) { return iso ? DcaD(iso).toLocaleDateString("en-US", Object.assign({ month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }, opts || {})) : "—"; }
function DcaTzName(tz) { return tz ? (DCA_TZ_NAMES[tz] || tz) : "account time"; }
function DcaPresetLabel(p) { const hit = DCA_PRESETS.find((x) => x[0] === p); return hit ? hit[1] : (p === "custom" ? "Custom" : p); }
function DcaLsGet(k, fb) { try { const v = window.localStorage.getItem(k); return v ? JSON.parse(v) : fb; } catch (e) { return fb; } }
function DcaLsSet(k, v) { try { window.localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } }

// Client mirror of ads_range.resolve (preview only — the backend is the authority).
function DcaResolve(p, today) {
  const y = DcaAdd(today, -1), dow = DcaD(today).getUTCDay();          // 0 = Sunday, like Meta's US weeks
  if (p === "today") return [today, today];
  if (p === "yesterday") return [y, y];
  if (p === "today_and_yesterday") return [y, today];
  if (p === "this_week") return [DcaAdd(today, -dow), today];
  if (p === "last_week") { const sun = DcaAdd(today, -dow); return [DcaAdd(sun, -7), DcaAdd(sun, -1)]; }
  if (p === "this_month") return [today.slice(0, 8) + "01", today];
  if (p === "last_month") { const last = DcaAdd(today.slice(0, 8) + "01", -1); return [last.slice(0, 8) + "01", last]; }
  if (p === "maximum") return [null, today];
  const m = /^last_(\d+)d$/.exec(p || "");
  return m ? [DcaAdd(today, -Number(m[1])), y] : [null, null];
}

function DcaRangeQuery(r) {
  const q = r.preset && r.preset !== "custom" ? "preset=" + r.preset : "since=" + r.since + "&until=" + r.until;
  return q + (r.compare ? "&compare=1" : "");
}

function DcaMonth({ first, today, start, end, onPick }) {
  const d0 = DcaD(first), lead = d0.getUTCDay();
  const days = new Date(Date.UTC(d0.getUTCFullYear(), d0.getUTCMonth() + 1, 0)).getUTCDate();
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(<span key={"b" + i} />);
  for (let n = 1; n <= days; n++) {
    const iso = first.slice(0, 8) + String(n).padStart(2, "0");
    const future = iso > today;
    const inR = start && end && iso >= start && iso <= end;
    const edge = iso === start || iso === end;
    cells.push(<button key={iso} type="button" disabled={future} onClick={() => onPick(iso)}
      className={"dca-day" + (inR ? " in" : "") + (edge ? " edge" : "") + (iso === today ? " today" : "")}
      aria-label={DcaFmt(iso)} aria-pressed={!!(inR || edge)}>{n}</button>);
  }
  return <div className="dca-month">
    <div className="dca-month-name">{DcaFmt(first, { day: undefined, month: "long" })}</div>
    <div className="dca-dow">{["S", "M", "T", "W", "T", "F", "S"].map((x, i) => <span key={i}>{x}</span>)}</div>
    <div className="dca-grid">{cells}</div>
  </div>;
}

// Meta-style date-range picker. value = {preset, since, until, compare}; today = account-tz ISO date.
function DcaRangePicker({ value, today, tz, onChange }) {
  const [open, setOpen] = useStateDca(false);
  const [draft, setDraft] = useStateDca(value);
  const [view, setView] = useStateDca(today.slice(0, 8) + "01");
  const [recent, setRecent] = useStateDca(() => DcaLsGet(DCA_RECENT_KEY, []));
  const btnRef = useRefDca(null);
  const openIt = () => {
    const r = value.preset && value.preset !== "custom" ? DcaResolve(value.preset, today) : [value.since, value.until];
    setDraft({ ...value, since: r[0] || value.since, until: r[1] || value.until });
    setView(DcaAdd((r[1] || today).slice(0, 8) + "01", -1).slice(0, 8) + "01");
    setOpen(true);
  };
  const close = () => { setOpen(false); if (btnRef.current) btnRef.current.focus(); };
  useEffectDca(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  const pickPreset = (p) => { const r = DcaResolve(p, today); setDraft({ ...draft, preset: p, since: r[0], until: r[1] }); };
  const pickDay = (iso) => {
    if (!draft.since || (draft.since && draft.until && draft.preset !== "pending")) setDraft({ ...draft, preset: "pending", since: iso, until: null });
    else if (iso < draft.since) setDraft({ ...draft, preset: "pending", since: iso });
    else setDraft({ ...draft, preset: "custom", until: iso });
  };
  const setInput = (k, v) => setDraft({ ...draft, preset: "custom", [k]: v });
  const valid = draft.preset === "maximum" || (draft.preset !== "pending" && draft.since && draft.until && draft.since <= draft.until && draft.since <= today);
  const apply = () => {
    if (!valid) return;
    const out = { preset: draft.preset === "pending" ? "custom" : draft.preset, since: draft.since, until: draft.until > today ? today : draft.until, compare: !!draft.compare };
    if (out.preset !== "custom") {
      const nr = [out.preset].concat(recent.filter((x) => x !== out.preset)).slice(0, 3);
      setRecent(nr); DcaLsSet(DCA_RECENT_KEY, nr);
    }
    onChange(out); close();
  };
  const next = DcaAdd(DcaAdd(view, 32).slice(0, 8) + "01", 0);
  const rlist = recent.filter((p) => DCA_PRESETS.some((x) => x[0] === p));
  const presetBtn = (p, label) => <button key={p} type="button" className={"dca-preset" + (draft.preset === p ? " on" : "")} onClick={() => pickPreset(p)}>{label}</button>;
  return <>
    <button ref={btnRef} type="button" className="dca-range-btn" onClick={openIt} aria-haspopup="dialog" aria-expanded={open}>
      <window.Icons.Calendar size={14} />
      <span><b>{DcaPresetLabel(value.preset)}</b> · {value.preset === "maximum" && !value.since ? "account lifetime" : DcaFmt(value.since) + " – " + DcaFmt(value.until)} · {DcaTzName(tz)}{value.compare ? " · vs previous" : ""}</span>
    </button>
    {open && ReactDOM.createPortal(<div className="dc-modal-layer dca-layer" role="dialog" aria-modal="true" aria-label="Choose a date range">
      <button className="dc-modal-backdrop" onClick={close} aria-label="Close date picker" />
      <div className="card dca-picker">
        <div className="dca-picker-body">
          <div className="dca-presets">
            {rlist.length > 0 && <div className="dca-preset-head">Recently used</div>}
            {rlist.map((p) => presetBtn(p, DcaPresetLabel(p)))}
            {rlist.length > 0 && <div className="dca-preset-head">Presets</div>}
            {DCA_PRESETS.map((x) => presetBtn(x[0], x[1]))}
          </div>
          <div className="dca-cal">
            <div className="dca-cal-nav">
              <button type="button" className="dc-quiet" onClick={() => setView(DcaAdd(view, -1).slice(0, 8) + "01")} aria-label="Previous month">‹</button>
              <button type="button" className="dc-quiet" disabled={next > today} onClick={() => setView(next)} aria-label="Next month">›</button>
            </div>
            <div className="dca-months">
              <DcaMonth first={view} today={today} start={draft.since} end={draft.until || draft.since} onPick={pickDay} />
              <DcaMonth first={next} today={today} start={draft.since} end={draft.until || draft.since} onPick={pickDay} />
            </div>
            <div className="dca-inputs">
              <label><span>Start</span><input type="date" max={today} value={draft.since || ""} onChange={(e) => setInput("since", e.target.value)} /></label>
              <label><span>End</span><input type="date" max={today} value={draft.until || ""} onChange={(e) => setInput("until", e.target.value)} /></label>
            </div>
            {draft.preset === "maximum" && <div className="faint" style={{ fontSize: 11 }}>Maximum = the ad account's first day through today (Meta keeps 37 months).</div>}
            <label className="dca-compare"><input type="checkbox" style={{ width: "auto" }} checked={!!draft.compare} onChange={(e) => setDraft({ ...draft, compare: e.target.checked })} /> Compare to the previous period</label>
          </div>
        </div>
        <div className="dca-picker-foot">
          <span className="faint">Dates are shown in {DcaTzName(tz)}{tz && DCA_TZ_NAMES[tz] ? " (" + tz + ")" : ""}</span>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" className="dc-quiet" onClick={close}>Cancel</button>
            <button type="button" className="dc-primary" disabled={!valid} onClick={apply}>Update</button>
          </div>
        </div>
      </div>
    </div>, document.body)}
  </>;
}

function DcaStatusPill({ status }) {
  const s = String(status || "").toLowerCase();
  const on = s === "active" || s === "delivering";
  const c = on ? "#22C55E" : "#94A3B8";
  return <span className="dc-live dc-mock" style={{ color: c, borderColor: c }}><i style={{ background: c }} /> {on ? "ACTIVE" : (s ? s.toUpperCase() : "—")}</span>;
}

// "vs $361.01 ▼ 100%" — for CPL a DROP is good; leads/clicks a rise is good; spend is neutral.
function DcaDelta({ prev, pct, money, lowerIsBetter, neutral }) {
  if (prev === undefined) return null;
  const fmt = (v) => (v == null ? "—" : money ? window.DcxMoney(v) : String(v));
  if (pct == null) return <span className="faint">vs {fmt(prev)}</span>;
  const good = lowerIsBetter ? pct < 0 : pct > 0;
  const c = pct === 0 || neutral ? "var(--text-2)" : good ? "#22C55E" : "#EF4444";   // spend up/down is neither good nor bad
  return <span><span className="faint">vs {fmt(prev)} </span><b style={{ color: c }}>{pct > 0 ? "▲" : pct < 0 ? "▼" : "•"} {Math.abs(pct)}%</b></span>;
}

function DcaHhmm(iso) {
  const m = /T(\d\d):(\d\d)/.exec(iso || "");
  if (!m) return null;
  const h = Number(m[1]);
  return (h % 12 || 12) + ":" + m[2] + (h < 12 ? " AM" : " PM");
}

// Day-by-day (or month-by-month for long windows) spend bars with lead markers. No chart lib.
function DcaTrend({ series }) {
  if (!series) return null;
  if (series.unknown) return <div className="dc-inline-empty">Daily trend Unknown — {series.error}</div>;
  const pts = series.points || [];
  if (!pts.length) return null;
  const max = Math.max.apply(null, pts.map((p) => p.spend)) || 0;
  const leadsTot = pts.reduce((a, p) => a + p.leads, 0);
  const fmtP = (d) => series.granularity === "month" ? DcaFmt(d + "-01", { day: undefined }) : DcaFmt(d, { year: undefined });
  return <div className="dca-trend">
    <div className="dca-trend-head"><b>{series.granularity === "month" ? "Spend per month" : "Spend per day"}</b><span className="faint"> · <i className="dca-dot" /> = leads that {series.granularity === "month" ? "month" : "day"} · {leadsTot} total</span></div>
    {max === 0 ? <div className="dc-inline-empty" style={{ padding: 12 }}>No spend on any {series.granularity} in this window (Meta returned no delivery).</div> :
      <div className="dca-bars" role="img" aria-label={"Spend per " + series.granularity}>
        {pts.map((p) => <div key={p.d} className="dca-bar" title={fmtP(p.d) + ": " + window.DcxMoney(p.spend) + " · " + p.leads + " leads · " + p.clicks + " clicks"}>
          {p.leads > 0 && <i className="dca-dot" />}
          <span style={{ height: Math.max(p.spend > 0 ? 3 : 0, Math.round(p.spend / max * 56)) + "px" }} />
        </div>)}
      </div>}
    {max > 0 && <div className="dca-trend-axis faint"><span>{fmtP(pts[0].d)}</span><span>peak {window.DcxMoney(max)}</span><span>{fmtP(pts[pts.length - 1].d)}</span></div>}
  </div>;
}

function DcaAutopilotStrip() {
  const res = window.DcxUseResource("/ads-auto/status", "dc-ads-auto-strip", 120000);
  const d = (res.data && !Array.isArray(res.data)) ? res.data : null;
  if (!d) return res.error ? <div className="dca-auto faint">Autopilot status Unknown — {res.error.message}</div> : null;
  const mode = String(d.mode || "").toUpperCase() || "UNKNOWN";
  const c = d.mode === "auto" ? "#22C55E" : d.mode === "shadow" ? "#F4B860" : "#94A3B8";
  const run = d.lastRun, cfgd = d.config || {}, pend = d.pending || [];
  const fmtA = (a) => a.kind === "budget" ? a.name + ": $" + (a.from / 100).toFixed(0) + " → $" + (a.to / 100).toFixed(0) + "/day" : (a.to === "PAUSED" ? "Pause " : "Turn on ") + a.level + " “" + a.name + "”";
  const open = () => { window.__dcaGrowthTab = "auto"; window.GoTo("Growth"); };
  return <div className="dca-auto">
    <div className="dca-auto-row">
      <span className="dc-live dc-mock" style={{ color: c, borderColor: c }}><i style={{ background: c }} /> AUTOPILOT {mode}</span>
      <span className="faint">{run ? "Last run " + run.day + " · " + (run.judge === "claude" ? "analyst reviewed" : "rules only") : (d.lastRunDay ? "Last run " + d.lastRunDay : "No run recorded on this server yet")}{d.mode !== "off" && cfgd.hour != null ? " · runs daily after " + cfgd.hour + ":00 (box)" + (d.dueNow ? " · due now" : "") : ""}</span>
      <button className="link" onClick={open}>Open Autopilot</button>
    </div>
    {run && run.note && <div className="faint dca-auto-note">{run.note}</div>}
    {d.lastError && <div className="dca-auto-note" style={{ color: "#EF4444" }}>Last run failed: {d.lastError}</div>}
    {pend.length > 0 && <div className="dca-auto-note"><b>{pend.length} proposal{pend.length > 1 ? "s" : ""} waiting for your tap</b>{pend.slice(0, 3).map((a) => <div key={a.aid} className="faint">• {fmtA(a)} — {a.reason}</div>)}</div>}
  </div>;
}

function DcaAdsCard() {
  const [range, setRangeState] = useStateDca(() => {
    const saved = DcaLsGet(DCA_RANGE_KEY, null);
    return saved && saved.preset ? saved : { preset: "last_30d", since: null, until: null, compare: false };
  });
  const setRange = (r) => { setRangeState(r); DcaLsSet(DCA_RANGE_KEY, r); };
  const res = window.DcxUseResource("/ads?" + DcaRangeQuery(range), "dc-ads-card", 120000);
  const data = (res.data && !Array.isArray(res.data)) ? res.data : {};   // hook starts as [] — not a payload
  const conn = data.connection || {};
  const a = data.analytics || {};
  const r = a.dateRange || {};
  const t = a.totals || a.summary || {};
  const cmp = a.compare && !a.compare.unknown ? a.compare : null;
  const pt = cmp ? cmp.totals : {}, dl = cmp ? cmp.delta : {};
  const campaigns = a.campaigns || [];
  const topAds = a.topAds || [];
  const spend = DcaNum(t.spend ?? t.amountSpent);
  const leads = DcaNum(t.leads ?? t.results);
  const clicks = DcaNum(t.clicks);
  const impressions = DcaNum(t.impressions);
  const delivering = impressions > 0;
  const tz = r.tz && !r.tzFallback ? r.tz : (a.accountTz || r.tz || "");
  const today = (a.fetchedAt || "").slice(0, 10) || DcaIso(new Date(Date.now() - new Date().getTimezoneOffset() * 60000));
  // The payload's dates are the authority — but only once it answers THIS range (while a new
  // range loads, the old payload is still on screen), else the client preview of the preset.
  const fresh = r.preset === range.preset && (range.preset !== "custom" || (r.since === range.since && r.until === range.until));
  const guess = range.preset === "custom" ? [range.since, range.until] : DcaResolve(range.preset, today);
  const shown = { ...range, since: fresh ? r.since : guess[0], until: fresh ? r.until : guess[1] };
  const actNum = String(a.accountId || (data.accounts && data.accounts[0] && data.accounts[0].id) || "").replace(/^act_/, "");
  const metaBase = "https://adsmanager.facebook.com/adsmanager/manage/";
  const rec = a.reconciled;
  const recBad = rec && ["spend", "impressions", "clicks", "leads"].filter((k) => rec[k] === false);
  const loaded = !!data.analytics;
  return <div className="card card-pad dc-panel dc-ads-card">
    <div className="dc-panel-head" style={{ flexWrap: "wrap", gap: 10 }}>
      <div style={{ minWidth: 0 }}>
        <div className="card-title">Enrollment ads</div>
        <div className="faint">Meta{conn.via === "pipeboard" ? " · via Pipeboard" : ""}{a.fetchedAt ? " · Updated " + DcaHhmm(a.fetchedAt) + " " + DcaTzName(tz) : ""}{res.loading && loaded ? " · updating…" : ""}</div>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", minWidth: 0 }}>
        {loaded && <DcaConnBadge conn={conn} />}
        {actNum && <a className="link" href={metaBase + "campaigns?act=" + actNum} target="_blank" rel="noopener noreferrer">Open in Meta Ads Manager ↗</a>}
        <button className="link" onClick={() => window.GoTo("Growth")}>Open Growth</button>
      </div>
    </div>
    <div style={{ margin: "10px 0" }}><DcaRangePicker value={shown} today={today} tz={tz} onChange={setRange} /></div>
    {r.tzFallback && <div className="dc-form-hint">Account timezone unavailable — dates use the server's FORGE_TZ_OFFSET ({r.tz}).</div>}
    {data.ok === false && <div className="dc-form-hint" style={{ color: "#EF4444" }}>{data.error}</div>}
    <DcaTodo conn={conn} />
    {loaded && !a.unknown && <DcaDataBadge src={a.dataSource} />}
    <window.DcxState loading={res.loading && !loaded} error={res.error} onRetry={res.refresh}>
      {a.unknown ? <div className="dc-inline-empty" style={{ color: "#F4B860" }}>Ad numbers Unknown — {a.error}</div> : loaded && <>
        <div className="dc-kpi-grid">
          <window.DcxKpi label="Spend" value={window.DcxMoney(spend)} sub={cmp ? <DcaDelta prev={pt.spend} pct={dl.spend} money neutral /> : (r.days ? r.days + "-day window" : "window")} icon="Dollar" />
          <window.DcxKpi label="Leads" value={leads} sub={cmp ? <DcaDelta prev={pt.leads} pct={dl.leads} /> : "Meta-reported, not enrollments"} icon="Children" color="#22C55E" />
          <window.DcxKpi label="Cost / Lead" value={t.cpl != null ? window.DcxMoney(t.cpl) : "—"} sub={cmp ? <DcaDelta prev={pt.cpl} pct={dl.cpl} money lowerIsBetter /> : (t.tcpl ? "target " + window.DcxMoney(t.tcpl) : "blended CPL")} icon="Billing" color="#F4B860" />
          <window.DcxKpi label="Clicks" value={clicks} sub={cmp ? <DcaDelta prev={pt.clicks} pct={dl.clicks} /> : (t.ctr != null ? t.ctr + "% CTR" : impressions + " impressions")} icon="Bell" color="#38BDF8" />
        </div>
        {cmp && <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>Compared with {DcaFmt(cmp.dateRange.since)} – {DcaFmt(cmp.dateRange.until)} (same number of days, just before).</div>}
        {a.compare && a.compare.unknown && <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>Previous period Unknown — {a.compare.error}</div>}
        {r.partialToday && <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>Includes today so far — today's numbers are still moving.</div>}
        {!delivering && <div className="dc-inline-empty">No ad delivery in this window — campaigns are paused or nothing ran. Try Last 90 days or Maximum for the history.</div>}
        <DcaTrend series={a.series} />
        {recBad && recBad.length > 0 && <div className="dc-form-hint">Ad-level rows don't add up to Meta's account total ({recBad.join(", ")}) — the tiles show Meta's account total.</div>}
        {a.truncated && <div className="dc-form-hint">Meta returned more ad rows than were read (truncated) — tiles use Meta's account-level totals; the ad list may be incomplete.</div>}
        {rec && !(recBad && recBad.length) && !a.truncated && <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>✓ Ad rows reconcile with Meta's account totals{rec.leadsMatchMetaResults ? " · leads match Meta's Results column" : ""}.</div>}
        {campaigns.length > 0 && <div className="dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Campaign</th><th>Status</th><th>Spend</th><th>Leads</th><th>CPL</th></tr></thead><tbody>{campaigns.map((c, i) => <tr key={c.id || i}><td><b>{actNum && /^\d+$/.test(String(c.id)) ? <a className="link" href={metaBase + "adsets?act=" + actNum + "&selected_campaign_ids=" + c.id} target="_blank" rel="noopener noreferrer">{c.name || "Campaign"} ↗</a> : (c.name || "Campaign")}</b></td><td><DcaStatusPill status={c.status} /></td><td className="tabnum">{window.DcxMoney(DcaNum(c.spend))}</td><td className="tabnum">{DcaNum(c.leads)}</td><td className="tabnum">{c.cpl != null && DcaNum(c.leads) ? window.DcxMoney(DcaNum(c.cpl)) : "—"}</td></tr>)}</tbody></table></div>}
        {topAds.length > 0 && <div className="dc-day-grid" style={{ marginTop: 10 }}>{topAds.slice(0, 3).map((ad, i) => <button key={ad.id || i} style={{ cursor: "default" }}><b>{ad.name || "Ad"}</b><small>{DcaNum(ad.leads)} leads · {window.DcxMoney(DcaNum(ad.spend))}</small></button>)}</div>}
        <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>{a.evidence || "Leads are Meta-reported, not enrollments."}</div>
      </>}
    </window.DcxState>
    <DcaAutopilotStrip />
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

function DcaCtxBadge({ ctx }) {
  const loaded = ctx && ctx.loaded;
  return <span className={"dc-live " + (loaded ? "" : "dc-mock")} title={ctx && ctx.path ? ctx.path : "daycare-context.md not found"} style={loaded ? null : { color: "#F4B860", borderColor: "rgba(244,184,96,.4)" }}>
    <i style={loaded ? null : { background: "#F4B860" }} /> {loaded ? ("BRIEF LOADED · " + DcaNum(ctx.chars) + " chars") : "BRIEF MISSING"}
  </span>;
}


// ── Ad studio — idea → image → PAUSED live ad ───────────────────────────────
// This is the DAYCARE's ad agent. It used to be branded "Eco" (the AGENCY's ads
// strategist), which was simply the wrong agent on the wrong business. Nova owns
// enrollment ads; the label now matches reality.
function DcaNovaCard({ idea, onImage, onBuild, onDiscard, imageReady, metaReady }) {
  const [url, setUrl] = useStateDca("");
  const [busy, setBusy] = useStateDca("");
  const [err, setErr] = useStateDca(null);
  const built = idea.status === "built";
  const meta = idea.meta || {};

  const doImage = async (pasted) => {
    setBusy("image"); setErr(null);
    try { await onImage(idea.id, pasted || ""); }
    catch (e) { setErr((e && e.message) || "Image step failed."); }
    finally { setBusy(""); }
  };
  const doBuild = async () => {
    setBusy("build"); setErr(null);
    try { await onBuild(idea.id); }
    catch (e) { setErr((e && e.message) || "Ad build failed."); }
    finally { setBusy(""); }
  };

  const tgt = idea.targeting || {};
  return <div className="card card-pad dc-panel" style={{ marginBottom: 12 }}>
    <div className="dc-panel-head">
      <div>
        <div className="card-title">{idea.title || "Concept"}</div>
        <div className="faint">{idea.angle || ""}</div>
      </div>
      <span className={"dc-live " + (built ? "" : "dc-mock")}
        style={built ? null : { color: "#F4B860", borderColor: "rgba(244,184,96,.4)" }}>
        <i style={built ? null : { background: "#F4B860" }} />
        {built ? "Built · PAUSED" : idea.imageUrl ? "Image ready" : "Draft"}
      </span>
    </div>

    {idea.imageUrl && <img src={idea.imageUrl} alt="" style={{
      width: "100%", maxHeight: 260, objectFit: "cover", borderRadius: 10, margin: "8px 0",
    }} />}

    <div style={{ display: "grid", gap: 6, marginTop: 6, fontSize: 13 }}>
      {idea.hook && <div><b>Hook</b> · {idea.hook}</div>}
      {idea.headline && <div><b>Headline</b> · {idea.headline}</div>}
      {idea.primaryText && <div style={{ opacity: .9 }}>{idea.primaryText}</div>}
      <div className="faint" style={{ fontSize: 12 }}>
        CTA {idea.cta || "LEARN_MORE"}
        {idea.dailyBudget ? " · $" + idea.dailyBudget + "/day suggested" : ""}
        {tgt.age_min ? " · ages " + tgt.age_min + "-" + tgt.age_max : ""}
        {tgt.radius_miles ? " · " + tgt.radius_miles + "mi radius" : ""}
      </div>
    </div>

    {idea.imagePrompt && !idea.imageUrl && <details style={{ marginTop: 10 }}>
      <summary style={{ cursor: "pointer", fontSize: 12, opacity: .75 }}>
        Image prompt (ready to generate)
      </summary>
      <div className="faint" style={{
        fontSize: 12, marginTop: 6, whiteSpace: "pre-wrap",
        background: "rgba(255,255,255,.04)", padding: 10, borderRadius: 8,
      }}>{idea.imagePrompt}</div>
      <button className="dc-outline" style={{ marginTop: 6 }}
        onClick={() => navigator.clipboard && navigator.clipboard.writeText(idea.imagePrompt)}>
        Copy prompt
      </button>
    </details>}

    {err && <div style={{ color: "#EF4444", fontSize: 12, marginTop: 8 }}>{err}</div>}

    {!built && <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
      {!idea.imageUrl && imageReady && <button className="dc-outline" disabled={!!busy}
        onClick={() => doImage("")}>
        <window.Icons.Bot size={14} /> {busy === "image" ? "Generating…" : "Generate image"}
      </button>}
      {!idea.imageUrl && !imageReady && <React.Fragment>
        <input className="input" placeholder="Paste image URL from Higgsfield…"
          value={url} onChange={(e) => setUrl(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
        <button className="dc-outline" disabled={!url.trim() || !!busy}
          onClick={() => doImage(url.trim())}>Attach</button>
      </React.Fragment>}
      <button className="dc-primary" onClick={doBuild} disabled={!!busy || !metaReady}
        title={metaReady ? "Creates the real Meta campaign, PAUSED" : "Needs META_ACCESS_TOKEN"}>
        <window.Icons.Dollar size={14} /> {busy === "build" ? "Building…" : "Create ad (paused)"}
      </button>
      <button className="dc-outline" onClick={() => onDiscard(idea.id)} disabled={!!busy}>Discard</button>
    </div>}

    {built && <div className="dc-form-hint" style={{ marginTop: 10 }}>
      <window.Icons.Shield size={14} />
      Campaign built and <b>PAUSED</b> on Meta — nothing is serving and nothing is spending.
      Review it, then flip it live in Meta when you're ready.
      {meta.url && <React.Fragment> · <a href={meta.url} target="_blank" rel="noreferrer">Open in Meta</a></React.Fragment>}
    </div>}
  </div>;
}

function DaycareNova() {
  const [busy, setBusy] = useStateDca(false);
  const [err, setErr] = useStateDca(null);
  const [ideas, setIdeas] = useStateDca([]);
  const [st, setSt] = useStateDca({});
  const probe = window.DcxUseResource("/eco", "dc-eco", 0);
  const ctx = (probe.data && probe.data.context) || {};
  const novaSrc = probe.data && probe.data.dataSource;

  const refresh = async () => {
    try {
      const out = await window.DcxRequest("/nova/ideas");   // no body → GET
      setIdeas(Array.isArray(out && out.ideas) ? out.ideas : []);
      setSt((out && out.status) || {});
    } catch (e) { /* empty state is fine */ }
  };
  useEffectDca(() => { refresh(); }, []);

  // DcxRequest sends GET unless a body is present — these routes are POST-only, so each
  // one must carry a body (even an empty object) or it 404s as a GET.
  const generate = async () => {
    setBusy(true); setErr(null);
    try { await window.DcxRequest("/nova/generate", { body: {} }); await refresh(); }
    catch (e) { setErr((e && e.message) || "Solomon couldn't draft ideas."); }
    finally { setBusy(false); }
  };
  const onImage = async (id, imageUrl) => {
    const out = await window.DcxRequest("/nova/image", { body: { id, imageUrl } });
    if (out && out.needsKey) throw new Error(out.error);
    await refresh();
  };
  const onBuild = async (id) => {
    const out = await window.DcxRequest("/nova/create-ad", { body: { id } });
    if (out && out.ok === false) throw new Error(out.detail || out.error || "Build failed.");
    await refresh();
  };
  const onDiscard = async (id) => {
    await window.DcxRequest("/nova/discard", { body: { id } });
    await refresh();
  };

  return <div className="dc-page">
    <window.DcxPageHead title="Enrollment Ad Studio" eyebrow="GROWTH · NOVA"
      copy="Solomon reads the business brief and the live ad spec, then drafts complete enrollment ads — hook, headline, copy, targeting, budget, and the image prompt. One tap builds the real campaign, PAUSED."
      actions={<DcaCtxBadge ctx={ctx} />} />

    {!ctx.loaded && <div className="dc-form-hint"><window.Icons.Shield size={14} /> Business brief not found. Add <code>forge-daycare/skills/daycare-context.md</code> so the ad studio stays on-message.</div>}
    {novaSrc === "token_rejected" && <div className="dc-form-hint"><DcaDataBadge src={novaSrc} /> Meta rejected <code>META_ACCESS_TOKEN</code> in <code>daycare.env</code> — ideas use the brief only until it's replaced.</div>}
    {!st.metaReady && <div className="dc-form-hint"><window.Icons.Shield size={14} /> Meta isn't connected — add <code>META_ACCESS_TOKEN</code> to <code>daycare.env</code> to build campaigns.</div>}
    {!st.imageReady && <div className="dc-form-hint"><window.Icons.Shield size={14} /> The ad studio can't generate images yet — no <code>HIGGSFIELD_API_KEY</code> in <code>daycare.env</code>. It writes the prompt; generate it in Higgsfield and paste the URL back, or add the key and it becomes one tap.</div>}

    <div className="dc-hero-actions" style={{ margin: "4px 0 14px" }}>
      <button className="dc-primary" onClick={generate} disabled={busy}>
        <window.Icons.Bot size={15} /> {busy ? "Solomon is drafting…" : "Generate enrollment ads"}
      </button>
    </div>

    {err && <window.DcxState error={err} onRetry={generate} />}
    {!ideas.length && !busy && <div className="dc-all-clear"><window.Icons.Bot size={22} /><div><b>No ad concepts yet</b><span>Tap “Generate enrollment ads” — Solomon drafts complete, buildable ads from your brief. They stay here until you build or discard them.</span></div></div>}

    {ideas.map((idea) => <DcaNovaCard key={idea.id} idea={idea}
      onImage={onImage} onBuild={onBuild} onDiscard={onDiscard}
      imageReady={!!st.imageReady} metaReady={!!st.metaReady} />)}
  </div>;
}

// ── Solomon · Ads — the daily optimizer. Shadow = proposes (one tap each); Auto = executes inside
// hard guardrails; Off = nothing. Only the operator flips the mode (CLAUDE.md §2 exception).
const DCAA_MODES = [["off", "Off", "Does nothing."],
  ["shadow", "Shadow", "Decides every day, tells you, changes nothing until you tap Approve."],
  ["auto", "Auto", "Pauses losers, cuts bleeding budgets 25%, scales winners +20% — on its own, inside the guardrails."]];

function DcaaPill({ on, label }) {
  const c = on ? "#22C55E" : "#F4B860";
  return <span className="dc-live dc-mock" style={{ color: c, borderColor: c, marginRight: 6 }}><i style={{ background: c }} /> {label}{on ? "" : " — not wired"}</span>;
}

function DaycareAdsAuto() {
  const res = window.DcxUseResource("/ads-auto/status", "dc-ads-auto", 30000);
  const [busy, setBusy] = useStateDca("");
  const [msg, setMsg] = useStateDca(null);
  const d = res.data || {};
  const cfgd = d.config || {}, wired = d.wired || {}, run = d.lastRun || null;
  const act = async (label, path, body, okMsg) => {
    setBusy(label); setMsg(null);
    try {
      const out = await window.DcxRequest(path, { body: body || {} });
      if (out && out.ok === false) throw new Error(out.error || "Not applied.");
      setMsg({ ok: true, text: okMsg || "Done." }); if (res.refresh) res.refresh();
    } catch (e) { setMsg({ ok: false, text: (e && e.message) || "Failed." }); }
    finally { setBusy(""); }
  };
  const setMode = (m) => {
    if (m === "auto" && !window.confirm("Switch to AUTO? Solomon will pause losing ads, cut budgets 25% and scale winners +20% on his own — never above $" + (cfgd.maxDaily || "?") + "/day total. Every action is logged and undoable, and you can switch it off any time.")) return;
    act("mode", "/ads-auto/mode", { mode: m }, "Mode is now " + m + ".");
  };
  const ads = ((run && run.entities) || []).filter((e) => e.level === "ad");
  const money = (v) => (v == null ? "—" : window.DcxMoney(DcaNum(v)));
  const when = (ts) => ts ? new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
  const fmt = (a) => a.kind === "budget"
    ? (a.to > a.from ? "▲ " : "▼ ") + a.name + ": $" + (a.from / 100).toFixed(0) + " → $" + (a.to / 100).toFixed(0) + "/day"
    : (a.to === "PAUSED" ? "⏸ Pause " : "▶ Turn on ") + a.level + " “" + a.name + "”";

  return <div className="dc-page">
    <window.DcxPageHead title="Ads autopilot" eyebrow="GROWTH · SOLOMON"
      copy={"Every morning Solomon reads yesterday's results from Meta (via Pipeboard), judges each ad against a $" + (cfgd.tcpl || "—") + " target cost per lead, and decides what to turn up and what to turn down. Then he drafts and draws one new test ad from what's winning in your market."}
      actions={<button className="dc-outline" onClick={() => act("run", "/ads-auto/run", {}, "Run finished — see below.")} disabled={!!busy}>{busy === "run" ? "Running…" : "Run now"}</button>} />
    <window.DcxState loading={res.loading && !res.data} error={res.error} onRetry={res.refresh} />
    {msg && <div className="dc-form-hint" style={{ color: msg.ok ? undefined : "#EF4444" }}>{msg.text}</div>}

    <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Mode</div><div className="faint">{(DCAA_MODES.find((m) => m[0] === d.mode) || [])[2]}</div></div></div>
      <div className="dc-hero-actions">{DCAA_MODES.map((m) => <button key={m[0]} className={d.mode === m[0] ? "dc-primary" : "dc-outline"} disabled={!!busy || !d.mode} onClick={() => d.mode !== m[0] && setMode(m[0])}>{m[1]}</button>)}</div>
      <div style={{ marginTop: 10 }}>
        <DcaaPill on={wired.pipeboard} label="Pipeboard (Meta)" /><DcaaPill on={wired.claude} label="Claude" />
        <DcaaPill on={wired.higgsfield} label="Higgsfield art" /><DcaaPill on={wired.competitorIntel} label="Competitor ads (Apify)" />
      </div>
      <div className="faint" style={{ marginTop: 8 }}>Guardrails: target CPL ${cfgd.tcpl} · total daily budget never above ${cfgd.maxDaily} · +{Math.round((cfgd.step || 0) * 100)}% / −{Math.round((cfgd.cutStep || 0) * 100)}% steps · 5-day cooldown · never pauses the last ad in an ad set · pause only, never delete.</div>
    </div>

    {d.lastError && <div className="dc-form-hint" style={{ color: "#EF4444" }}><window.Icons.Shield size={14} /> Last run failed: {d.lastError}</div>}

    {run && <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Latest read — {run.day}</div><div className="faint">{run.mode} mode · {run.judge === "claude" ? "analyst reviewed" : "rules only"} · {money(run.totalBudget)}/day total budget · leads are Meta pixel leads, not enrollments</div></div></div>
      <p style={{ margin: "6px 0" }}>{run.note}</p>
      {run.creative && <div className="faint">🎨 {run.creative.ran ? "New test: " + run.creative.title + (run.creative.activated ? " (live)" : " (built PAUSED)") : "No new test — " + (run.creative.why || "n/a")}</div>}
    </div>}

    {(d.pending || []).length > 0 && <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Waiting for your tap</div><div className="faint">Shadow-mode proposals — nothing has changed on Meta.</div></div></div>
      {d.pending.map((a) => <div key={a.aid} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 0", borderTop: "1px solid rgba(255,255,255,.06)" }}>
        <div style={{ flex: 1 }}><b>{fmt(a)}</b><div className="faint">{a.reason}</div></div>
        <button className="dc-primary" disabled={!!busy} onClick={() => act("ap" + a.aid, "/ads-auto/approve", { id: a.aid }, "Applied on Meta.")}>Approve</button>
        <button className="dc-outline" disabled={!!busy} onClick={() => act("rj" + a.aid, "/ads-auto/reject", { id: a.aid }, "Skipped.")}>Skip</button>
      </div>)}
    </div>}

    {ads.length > 0 && <div className="card dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Ad</th><th>Verdict</th><th>14d spend</th><th>Leads</th><th>CPL</th><th>Freq</th><th>Why</th></tr></thead><tbody>
      {ads.map((e) => <tr key={e.id}><td><b>{e.name}</b></td><td>{e.verdict}</td><td className="tabnum">{money(e.spend14)}</td><td className="tabnum">{e.leads14}</td><td className="tabnum">{money(e.cpl14)}</td><td className="tabnum">{e.freq ? DcaNum(e.freq).toFixed(1) : "—"}</td><td className="faint">{e.reason}</td></tr>)}
    </tbody></table></div>}
    {run && !ads.length && <div className="dc-all-clear"><window.Icons.Dollar size={22} /><div><b>Nothing is delivering</b><span>No campaign, ad set and ad are all ACTIVE together, so there is nothing to turn up or down. Turn a campaign on in Meta (or approve a launch) and Solomon takes it from there.</span></div></div>}

    {(d.recent || []).length > 0 && <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">What he did</div><div className="faint">Every action is logged. Executed ones can be undone while Meta still shows the value he set.</div></div></div>
      {d.recent.slice(0, 12).map((a) => <div key={a.aid} style={{ display: "flex", gap: 10, alignItems: "center", padding: "6px 0", borderTop: "1px solid rgba(255,255,255,.06)" }}>
        <div style={{ flex: 1 }}><b>{fmt(a)}</b> <span className="faint">· {a.status}{a.verified === false ? " · NOT VERIFIED on Meta" : ""} · {when(a.ts)}</span><div className="faint">{a.why || a.reason}</div></div>
        {a.status === "executed" && (a.kind === "budget" || a.kind === "status") && <button className="dc-outline" disabled={!!busy} onClick={() => act("un" + a.aid, "/ads-auto/undo", { id: a.aid }, "Undone.")}>Undo</button>}
      </div>)}
    </div>}
  </div>;
}

function DaycareGrowth() {
  const [tab, setTab] = useStateDca(() => { const t = window.__dcaGrowthTab; window.__dcaGrowthTab = null; return t || "ideas"; });   // the dashboard's "Open Autopilot" lands on its tab
  return <div className="dc-page">
    <div className="dc-hero" style={{ marginBottom: 14 }}><div><div className="dc-eyebrow">GROWTH ENGINE</div><h1>Grow enrollment. Run the ads. Watch the socials.</h1><p>The daycare's marketing command center — <b>Solomon</b> drafts complete enrollment ads from your business brief and builds them on Meta, PAUSED. Going live, changing budget, and publishing posts stay behind your one-tap approval — unless you switch Autopilot to Auto.</p><div className="dc-hero-actions"><button className={tab === "ideas" ? "dc-primary" : "dc-outline"} onClick={() => setTab("ideas")}><window.Icons.Bot size={15} /> Ad Studio</button><button className={tab === "ads" ? "dc-primary" : "dc-outline"} onClick={() => setTab("ads")}><window.Icons.Dollar size={15} /> Ads</button><button className={tab === "auto" ? "dc-primary" : "dc-outline"} onClick={() => setTab("auto")}><window.Icons.Shield size={15} /> Autopilot</button><button className={tab === "social" ? "dc-primary" : "dc-outline"} onClick={() => setTab("social")}><window.Icons.Bell size={15} /> Social</button></div></div></div>
    {tab === "ideas" ? <DaycareNova /> : tab === "ads" ? <DaycareAds /> : tab === "auto" ? <DaycareAdsAuto /> : <DaycareSocial />}
  </div>;
}

Object.assign(window, { DaycareGrowth, DaycareAds, DcaAdsCard, DcaRangePicker, DaycareSocial, DaycareAdsAuto,
  DaycareNova, DcaNovaCard });
