// dropship.jsx — FORGE Dropship workspace foundation + Dashboard + Settings + Agents.
// Open workspace (no auth gate, like the agency side); all data comes from /api/dropship/*.
const { useState: useStateDs, useEffect: useEffectDs, useCallback: useCallbackDs } = React;

const DS_ACCENT = "#F97316";
const DS_API_ROOT = "/api/dropship";

async function DsRequest(path, options = {}) {
  const method = options.method || (options.body === undefined ? "GET" : "POST");
  const response = await fetch(DS_API_ROOT + path, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { payload = null; }
  if (!response.ok) {
    const message = payload && (payload.error || payload.detail || payload.message);
    const error = new Error(message || "Dropship request failed");
    error.status = response.status; error.body = payload;
    throw error;
  }
  return payload === null ? {} : payload;
}

function DsUnwrap(payload, key, fallback) {
  if (payload === undefined || payload === null) return fallback;
  if (key && payload[key] !== undefined) return payload[key];
  return payload;
}

function DsUseResource(path, key, pollMs = 20000) {
  const [data, setData] = useStateDs(null);
  const [loading, setLoading] = useStateDs(true);
  const [error, setError] = useStateDs(null);
  const [version, setVersion] = useStateDs(0);
  const refresh = useCallbackDs(() => setVersion((v) => v + 1), []);
  useEffectDs(() => {
    let active = true; let timer = null;
    const load = async (quiet) => {
      if (!quiet) setLoading(true);
      try {
        const payload = await DsRequest(path);
        if (active) { setData(DsUnwrap(payload, key, payload)); setError(null); }
      } catch (e) { if (active) setError(e); }
      finally { if (active) setLoading(false); }
    };
    load(false);
    if (pollMs) timer = window.setInterval(() => { if (!document.hidden) load(true); }, pollMs);
    return () => { active = false; if (timer) window.clearInterval(timer); };
  }, [path, key, pollMs, version]);
  return { data, loading, error, refresh, setData };
}

function DsPageHead({ title, eyebrow = "FORGE DROPSHIP", actions, copy }) {
  return <div className="dc-page-head"><div><div className="dc-eyebrow">{eyebrow}</div><h1>{title}</h1>{copy && <p>{copy}</p>}</div>{actions && <div className="dc-head-actions">{actions}</div>}</div>;
}

function DsKpi({ label, value, sub, icon, color = DS_ACCENT }) {
  const Icon = window.Icons[icon] || window.Icons.Dashboard;
  return <div className="kpi dc-kpi"><div className="kpi-ico" style={{ color, background: color + "1f" }}><Icon size={18} /></div><div className="kpi-label">{label}</div><div className="kpi-val tabnum">{value}</div><div className="kpi-delta"><span className="faint">{sub}</span></div></div>;
}

function DsState({ loading, error, empty, icon = "Dashboard", title, copy, onRetry, children }) {
  const Icon = window.Icons[icon] || window.Icons.Dashboard;
  if (loading) return <div className="card dc-state"><div className="dc-spinner" /><b>Loading store data</b><span>Reading Shopify / AutoDS / Meta…</span></div>;
  if (error) return <div className="card dc-state dc-state-error"><Icon size={27} /><b>Store data unavailable</b><span>{error.message || "Check the integration and try again."}</span>{onRetry && <button className="dc-primary" onClick={onRetry}>Try again</button>}</div>;
  if (empty) return <div className="card dc-state"><Icon size={27} /><b>{title}</b><span>{copy}</span>{children}</div>;
  return children;
}

function DsModal({ title, copy, onClose, children, wide = false }) {
  return <div className="dc-modal-layer" role="dialog" aria-modal="true" aria-label={title}><button className="dc-modal-backdrop" onClick={onClose} aria-label="Close dialog" /><div className={"card dc-modal" + (wide ? " dc-modal-wide" : "")}><div className="dc-modal-head"><div><div className="card-title">{title}</div>{copy && <div className="faint">{copy}</div>}</div><button onClick={onClose} aria-label="Close">✕</button></div>{children}</div></div>;
}

function DsField({ label, children, wide = false }) {
  return <label className={wide ? "dc-field-wide" : ""}><span>{label}</span>{children}</label>;
}

// A small "connected / add key" chip used across the dropship tabs.
function DsChannel({ name, connected, detail }) {
  return <div className="dc-integration-head"><span className={"dc-integration-dot " + (connected ? "online" : "offline")} /><div><b>{name}</b><small>{connected ? "Connected" : (detail || "Add key in dropship.env")}</small></div></div>;
}

function DropshipDashboard() {
  const overview = DsUseResource("/overview", "overview", 30000);
  const director = DsUseResource("/director/brief", "brief", 60000);
  const v = overview.data || {};
  const store = v.store || {};
  const wl = v.watchlist || {};
  const systems = Array.isArray(v.systems) ? v.systems : [];
  const brief = (director.data && director.data.brief) || null;
  const connectedCount = systems.filter((s) => s.connected).length;
  const orders = store.orders ?? 0;
  const unfulfilled = store.unfulfilled ?? 0;
  const lowStock = store.lowStock ?? 0;
  return <div className="dc-page"><DsState loading={overview.loading} error={overview.error} onRetry={overview.refresh}><>
    <section className="dc-hero"><div><div className="dc-eyebrow">LIVE STORE · FORGE DROPSHIP</div><h1>{(store.shop && store.shop.name) || "Dropship command center"}</h1><p>Grow profitable revenue while the merchant &amp; ad accounts stay healthy. Everything outward stays your one-tap approval.</p><div className="dc-hero-actions"><button className="dc-primary" onClick={() => window.GoTo("Agents")}><window.Icons.Bot size={15}/> Ask the crew</button><button className="dc-outline" onClick={() => window.GoTo("Orders")}><window.Icons.Orders size={15}/> Orders</button></div></div><div className="dc-hero-mark"><span>{orders}</span><small>ORDERS PULLED</small></div></section>
    <div className="dc-kpi-grid">
      <DsKpi label="Orders" value={orders} sub={store.connected ? "recent (Shopify)" : "connect Shopify"} icon="Orders"/>
      <DsKpi label="Unfulfilled" value={unfulfilled} sub="need shipping" icon="Suppliers" color={unfulfilled ? "#F4B860" : "#22C55E"}/>
      <DsKpi label="Low stock" value={lowStock} sub="variants ≤5" icon="Inventory" color={lowStock ? "#F87171" : "#22C55E"}/>
      <DsKpi label="Winners" value={wl.winners ?? 0} sub={(wl.testing ?? 0) + " in testing"} icon="Target" color="#22C55E"/>
      <DsKpi label="Ideas" value={wl.totalIdeas ?? 0} sub="research watchlist" icon="Products" color="#8B5CF6"/>
      <DsKpi label="Systems" value={connectedCount + "/" + systems.length} sub="integrations wired" icon="Sliders" color={connectedCount ? DS_ACCENT : "#F87171"}/>
    </div>
    <div className="dc-main-grid">
      <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Fast paths</div><div className="faint">Jump into the store</div></div></div><div className="dc-day-grid">{[["Products","Products","Ideas + live catalog"],["Orders","Orders","Fulfillment"],["Ads","Ads & Creative","Blaze"],["Analytics","Analytics","Store + ads"]].map((item) => { const Icon = window.Icons[item[0]] || window.Icons.Dashboard; return <button key={item[0]} onClick={() => window.GoTo(item[0])}><span><Icon size={18}/></span><b>{item[1]}</b><small>{item[2]}</small></button>; })}</div></div>
      <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Midas brief</div><div className="faint">{brief ? (brief.headline || "Latest operating brief") : "No brief yet"}</div></div><button className="link" onClick={() => window.GoTo("Agents")}>Open crew</button></div>{brief && Array.isArray(brief.priorities) && brief.priorities.length ? <div className="dc-alert-list">{brief.priorities.slice(0,5).map((p, i) => <div key={i}><span className={"dc-severity " + ((p.urgency||"info").toLowerCase())}/><div><b>{p.title}</b><small>{p.why}</small></div></div>)}</div> : <div className="dc-all-clear"><window.Icons.Bot size={22}/><div><b>No brief yet</b><span>Run Midas from the Agents tab to get a ranked operating brief.</span></div></div>}</div>
    </div>
    <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Connected systems</div><div className="faint">Presence only — keys live in dropship.env (never shown)</div></div><button className="link" onClick={() => window.GoTo("Settings")}>Settings</button></div><div className="dc-room-strip">{systems.map((s) => <div key={s.key}><DsChannel name={s.name} connected={s.connected}/></div>)}</div></div>
  </></DsState></div>;
}

function DropshipSettings() {
  const settings = DsUseResource("/settings", null, 60000);
  const shopify = DsUseResource("/shopify/health", null, 120000);
  const autods = DsUseResource("/autods/health", null, 120000);
  const ads = DsUseResource("/ads", null, 120000);
  const [form, setForm] = useStateDs({ storeName: "", niche: "", targetMargin: "", priceBand: "", currency: "USD" });
  const [saving, setSaving] = useStateDs(false);
  const [notice, setNotice] = useStateDs("");
  useEffectDs(() => { const s = settings.data || {}; setForm({ storeName: s.storeName || "", niche: s.niche || "", targetMargin: s.targetMargin || "", priceBand: s.priceBand || "", currency: s.currency || "USD" }); }, [settings.data]);
  const save = async () => { setSaving(true); setNotice(""); try { await DsRequest("/settings/save", { body: form }); setNotice("Store settings saved."); settings.refresh(); } catch (e) { setNotice(e.message); } finally { setSaving(false); } };
  const sh = shopify.data || {}; const ad = autods.data || {}; const meta = (ads.data && ads.data.connection) || {};
  return <div className="dc-page"><DsPageHead title="Settings & Integrations" copy="Store facts the crew grounds on, plus connection health. Keys stay in dropship.env — never shown here."/><div className="dc-settings-grid"><div className="card card-pad dc-settings"><div className="dc-panel-head"><div><div className="card-title">Store profile</div><div className="faint">A fast mirror of dropship-context.md</div></div>{notice && <span className={notice.includes("saved") ? "dc-saved" : "dc-error-text"}>{notice}</span>}</div><div className="dc-form-grid"><DsField label="Store name"><input value={form.storeName} onChange={(e) => setForm({...form,storeName:e.target.value})}/></DsField><DsField label="Niche"><input value={form.niche} onChange={(e) => setForm({...form,niche:e.target.value})} placeholder="e.g. home & kitchen gadgets"/></DsField><DsField label="Target margin"><input value={form.targetMargin} onChange={(e) => setForm({...form,targetMargin:e.target.value})} placeholder="e.g. 3x landed or 30%"/></DsField><DsField label="Price band"><input value={form.priceBand} onChange={(e) => setForm({...form,priceBand:e.target.value})} placeholder="e.g. $29–$59"/></DsField><DsField label="Currency"><input value={form.currency} onChange={(e) => setForm({...form,currency:e.target.value})}/></DsField></div><div className="dc-settings-actions"><button className="dc-primary" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save store profile"}</button></div></div><div className="dc-settings-side"><div className="card card-pad"><DsChannel name="Shopify (store)" connected={!!sh.connected} detail={sh.detail}/></div><div className="card card-pad"><DsChannel name="AutoDS (sourcing)" connected={!!ad.connected} detail={ad.detail}/></div><div className="card card-pad"><DsChannel name="Meta Ads" connected={!!(meta.connected || meta.source === "live")} detail={"Add META_ACCESS_TOKEN"}/></div><div className="card card-pad dc-signout"><b>How keys work</b><p>Drop real keys into <code>forge-dropship/config/dropship.env</code> on the box. They 404 over HTTP and are never shown in the UI. Until set, each channel reads mock/"add key" — nothing errors, nothing charges.</p></div></div></div></div>;
}

Object.assign(window, {
  DS_ACCENT, DsRequest, DsUnwrap, DsUseResource, DsPageHead, DsKpi, DsState, DsModal, DsField, DsChannel,
  DropshipDashboard, DropshipSettings,
});
