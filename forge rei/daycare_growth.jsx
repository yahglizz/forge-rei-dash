// daycare_growth.jsx — Ads + Social monitoring for the daycare business.
// Reuses the Agency Meta/Metricool engines with the daycare's own credentials.
// Renders cleanly in "mock" mode until META_ACCESS_TOKEN / METRICOOL_USER_TOKEN
// are added to daycare.env, then lights up live — no rebuild.
const { useState: useStateDca, useEffect: useEffectDca } = React;

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

function DcaCtxBadge({ ctx }) {
  const loaded = ctx && ctx.loaded;
  return <span className={"dc-live " + (loaded ? "" : "dc-mock")} title={ctx && ctx.path ? ctx.path : "daycare-context.md not found"} style={loaded ? null : { color: "#F4B860", borderColor: "rgba(244,184,96,.4)" }}>
    <i style={loaded ? null : { background: "#F4B860" }} /> {loaded ? ("BRIEF LOADED · " + DcaNum(ctx.chars) + " chars") : "BRIEF MISSING"}
  </span>;
}

function DaycareEco() {
  const [busy, setBusy] = useStateDca(false);
  const [err, setErr] = useStateDca(null);
  const [res, setRes] = useStateDca(null);
  // Fast context-status probe so the owner sees the brief is wired before generating.
  const probe = window.DcxUseResource("/eco", "dc-eco", 0);
  const ctx = (res && res.context) || (probe.data && probe.data.context) || {};

  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const out = await window.DcxRequest("/eco/ideas");
      setRes(out);
    } catch (e) {
      setErr((e && e.message) || "Idea generation failed.");
    } finally {
      setBusy(false);
    }
  };

  const best = (res && res.best) || [];
  const weak = (res && res.weak) || [];
  const next = (res && res.next) || [];
  const comp = (res && res.competitor) || {};
  const analyzed = comp && comp.status === "analyzed";

  return <div className="dc-page">
    <window.DcxPageHead title="Enrollment Ideas" eyebrow="GROWTH · ECO AGENT"
      copy="Eco reads the daycare business brief first, then drafts new enrollment angles + studies competitors. Proposals only — launching an ad stays approval-gated."
      actions={<DcaCtxBadge ctx={ctx} />} />
    {!ctx.loaded && <div className="dc-form-hint"><window.Icons.Shield size={14} /> Business brief not found. Add <code>forge-daycare/skills/daycare-context.md</code> so Eco stays on-message.</div>}
    <div className="dc-hero-actions" style={{ margin: "4px 0 14px" }}>
      <button className="dc-primary" onClick={run} disabled={busy}>
        <window.Icons.Bot size={15} /> {busy ? "Eco is thinking…" : "Generate enrollment ideas"}
      </button>
    </div>
    {err && <window.DcxState error={err} onRetry={run} />}
    {!res && !busy && <div className="dc-all-clear"><window.Icons.Bot size={22} /><div><b>No ideas generated yet</b><span>Tap “Generate enrollment ideas” — Eco reads the brief and drafts fresh angles grounded in your numbers.</span></div></div>}
    {next.length > 0 && <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">New enrollment angles</div><div className="faint">Fresh concepts — every one aims to book a tour</div></div><b>{next.length}</b></div>
      <div className="dc-alert-list">{next.map((c, i) => <div key={i} style={{ alignItems: "flex-start" }}><span className="dc-severity info" /><div><b>{c.title || ("Concept " + (i + 1))}</b><small style={{ display: "block", marginTop: 2 }}>{c.hook ? ("Hook: " + c.hook) : ""}</small>{c.headline && <small style={{ display: "block" }}>Headline: {c.headline}</small>}{c.primaryText && <small style={{ display: "block", opacity: .85 }}>{c.primaryText}</small>}{c.cta && <small style={{ display: "block", opacity: .7 }}>CTA: {c.cta}{c.angle ? " · " + c.angle : ""}</small>}</div></div>)}</div></div>}
    {(best.length > 0 || weak.length > 0) && <div className="dc-main-grid">
      <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Scale these</div><div className="faint">Winners worth more budget</div></div><b>{best.length}</b></div>{best.length ? <div className="dc-alert-list">{best.map((b, i) => <div key={i}><span className="dc-severity" style={{ background: "#22C55E" }} /><div><b>{b.name || "Ad"}</b><small>{b.why || ""}</small></div></div>)}</div> : <div className="dc-inline-empty">No standout winners yet.</div>}</div>
      <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Pause / rework</div><div className="faint">Underperformers</div></div><b>{weak.length}</b></div>{weak.length ? <div className="dc-alert-list">{weak.map((w, i) => <div key={i}><span className="dc-severity" style={{ background: "#F4B860" }} /><div><b>{w.name || "Ad"}</b><small>{w.why || ""}</small></div></div>)}</div> : <div className="dc-inline-empty">Nothing to cut yet.</div>}</div>
    </div>}
    {analyzed && <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Competitor read</div><div className="faint">{comp.niche || "Nearby daycares"}</div></div></div>
      {comp.summary && <p className="faint" style={{ marginTop: 6 }}>{comp.summary}</p>}
      {Array.isArray(comp.positioningGaps) && comp.positioningGaps.length > 0 && <div style={{ marginTop: 8 }}><b style={{ fontSize: 13 }}>Gaps to exploit</b><ul className="dc-bullets">{comp.positioningGaps.map((g, i) => <li key={i}>{g}</li>)}</ul></div>}
      {Array.isArray(comp.recommendedDifferentiators) && comp.recommendedDifferentiators.length > 0 && <div style={{ marginTop: 8 }}><b style={{ fontSize: 13 }}>Lean into</b><ul className="dc-bullets">{comp.recommendedDifferentiators.map((d, i) => <li key={i}>{d}</li>)}</ul></div>}
    </div>}
  </div>;
}

// ── Nova's ad studio — idea → image → PAUSED live ad ─────────────────────────
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
    catch (e) { setErr((e && e.message) || "Nova couldn't draft ideas."); }
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
      copy="Nova reads the business brief and the live ad spec, then drafts complete enrollment ads — hook, headline, copy, targeting, budget, and the image prompt. One tap builds the real campaign, PAUSED."
      actions={<DcaCtxBadge ctx={ctx} />} />

    {!ctx.loaded && <div className="dc-form-hint"><window.Icons.Shield size={14} /> Business brief not found. Add <code>forge-daycare/skills/daycare-context.md</code> so Nova stays on-message.</div>}
    {!st.metaReady && <div className="dc-form-hint"><window.Icons.Shield size={14} /> Meta isn't connected — add <code>META_ACCESS_TOKEN</code> to <code>daycare.env</code> to build campaigns.</div>}
    {!st.imageReady && <div className="dc-form-hint"><window.Icons.Shield size={14} /> Nova can't generate images herself yet — no <code>HIGGSFIELD_API_KEY</code> in <code>daycare.env</code>. She writes the prompt; generate it in Higgsfield and paste the URL back, or add the key and it becomes one tap.</div>}

    <div className="dc-hero-actions" style={{ margin: "4px 0 14px" }}>
      <button className="dc-primary" onClick={generate} disabled={busy}>
        <window.Icons.Bot size={15} /> {busy ? "Nova is drafting…" : "Generate enrollment ads"}
      </button>
    </div>

    {err && <window.DcxState error={err} onRetry={generate} />}
    {!ideas.length && !busy && <div className="dc-all-clear"><window.Icons.Bot size={22} /><div><b>No ad concepts yet</b><span>Tap “Generate enrollment ads” — Nova drafts complete, buildable ads from your brief. They stay here until you build or discard them.</span></div></div>}

    {ideas.map((idea) => <DcaNovaCard key={idea.id} idea={idea}
      onImage={onImage} onBuild={onBuild} onDiscard={onDiscard}
      imageReady={!!st.imageReady} metaReady={!!st.metaReady} />)}
  </div>;
}

function DaycareGrowth() {
  const [tab, setTab] = useStateDca("ideas");
  return <div className="dc-page">
    <div className="dc-hero" style={{ marginBottom: 14 }}><div><div className="dc-eyebrow">GROWTH ENGINE</div><h1>Grow enrollment. Run the ads. Watch the socials.</h1><p>The daycare's marketing command center — <b>Nova</b> drafts complete enrollment ads from your business brief and builds them on Meta, PAUSED. Going live, changing budget, and publishing posts stay behind your one-tap approval.</p><div className="dc-hero-actions"><button className={tab === "ideas" ? "dc-primary" : "dc-outline"} onClick={() => setTab("ideas")}><window.Icons.Bot size={15} /> Ad Studio</button><button className={tab === "ads" ? "dc-primary" : "dc-outline"} onClick={() => setTab("ads")}><window.Icons.Dollar size={15} /> Ads</button><button className={tab === "social" ? "dc-primary" : "dc-outline"} onClick={() => setTab("social")}><window.Icons.Bell size={15} /> Social</button></div></div></div>
    {tab === "ideas" ? <DaycareNova /> : tab === "ads" ? <DaycareAds /> : <DaycareSocial />}
  </div>;
}

Object.assign(window, { DaycareGrowth, DaycareAds, DaycareSocial, DaycareEco,
  DaycareNova, DcaNovaCard });
