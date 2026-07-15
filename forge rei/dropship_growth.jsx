// dropship_growth.jsx — Ads & Creative (Blaze), Analytics, and the Agents crew console.
const { useState: useStateDsg } = React;

// ---- Ads & Creative (Blaze) ----
function DsgList({ items, render }) {
  if (!items || !items.length) return null;
  return <div className="dc-alert-list">{items.map((it, i) => <div key={i}><span className="dc-severity info" />{render(it)}</div>)}</div>;
}

function DropshipAds() {
  const ads = window.DsUseResource("/ads", null, 60000);
  const [busy, setBusy] = useStateDsg(false);
  const [result, setResult] = useStateDsg(null);
  const [err, setErr] = useStateDsg("");
  const conn = (ads.data && ads.data.connection) || {};
  const connected = !!(conn.connected || conn.source === "live");
  const run = async () => {
    setBusy(true); setErr(""); setResult(null);
    try { const r = await window.DsRequest("/blaze/run", { body: {} }); setResult(r.result || r); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const res = result || {};
  return <div className="dc-page">
    <window.DsPageHead title="Ads & Creative" copy="Blaze reads Meta performance and drafts concepts. Launching / changing budget stays your approval." actions={<button className="dc-primary" disabled={busy} onClick={run}>{busy ? "Analyzing…" : "Analyze & draft concepts"}</button>} />
    <div className="card card-pad"><window.DsChannel name="Meta Ads (dropship account)" connected={connected} detail="Add META_ACCESS_TOKEN + META_AD_ACCOUNT_MAP to dropship.env" /></div>
    {err && <div className="dc-form-error">{err}</div>}
    {res.raw && <div className="card card-pad dc-panel"><pre className="dc-pre">{res.raw}</pre></div>}
    {res.verdicts && res.verdicts.length > 0 && <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Verdicts</div><div className="faint">scale / hold / kill / refresh — recommendations only</div></div></div><DsgList items={res.verdicts} render={(v) => <div><b>{v.adOrProduct}: {v.call}</b><small>{v.why}{v.window ? " · " + v.window : ""}</small></div>} /></div>}
    {res.concepts && res.concepts.length > 0 && <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Concept drafts</div><div className="faint">proposals — nothing runs until you launch it</div></div></div><DsgList items={res.concepts} render={(c) => <div><b>{c.hook}</b><small>{c.angle}{c.format ? " · " + c.format : ""} — {c.why}</small></div>} /></div>}
    {res.notes && res.notes.length > 0 && <div className="card card-pad"><ul className="dc-notes">{res.notes.map((n, i) => <li key={i}>{n}</li>)}</ul></div>}
  </div>;
}

// ---- Analytics ----
function DropshipAnalytics() {
  const a = window.DsUseResource("/analytics", null, 45000);
  const store = (a.data && a.data.shopify) || {};
  const ads = (a.data && a.data.ads) || {};
  const conn = ads.connection || {};
  return <div className="dc-page">
    <window.DsPageHead title="Analytics" copy="Store + ad performance at a glance. Every number carries its source; mock until keyed." />
    <window.DsState loading={a.loading} error={a.error} onRetry={a.refresh}>
      <div className="dc-kpi-grid">
        <window.DsKpi label="Orders" value={store.orders ?? 0} sub={store.connected ? "Shopify" : "connect Shopify"} icon="Orders"/>
        <window.DsKpi label="Unfulfilled" value={store.unfulfilled ?? 0} sub="need shipping" icon="Suppliers" color={(store.unfulfilled ?? 0) ? "#F4B860" : "#22C55E"}/>
        <window.DsKpi label="Low stock" value={store.lowStock ?? 0} sub="variants ≤5" icon="Inventory" color={(store.lowStock ?? 0) ? "#F87171" : "#22C55E"}/>
        <window.DsKpi label="Meta ads" value={conn.connected || conn.source === "live" ? "Live" : "Mock"} sub="ad account" icon="Ads" color={conn.connected ? "#22C55E" : "#64748B"}/>
      </div>
      <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Notes</div><div className="faint">honest reads only</div></div></div><ul className="dc-notes"><li>Store data is {store.connected ? "live from Shopify" : "mock until SHOPIFY_ADMIN_TOKEN is set"}.</li><li>Ad metrics are {conn.connected || conn.source === "live" ? "live from Meta" : "mock until META_ACCESS_TOKEN is set"}.</li><li>Profit / margin needs real cost inputs (product + shipping + fees + ad cost) — set them per product in the watchlist and the crew grounds on them.</li></ul></div>
    </window.DsState>
  </div>;
}

// ---- Agents crew console (Midas + Hawk / Blaze / Otto) ----
function DsgAgentCard({ agent, runPath, learnPath, tab, onDone }) {
  const [busy, setBusy] = useStateDsg("");
  const act = async (path, label) => {
    setBusy(label);
    try { await window.DsRequest(path, { body: {} }); onDone && onDone(); }
    catch (e) { window.alert(e.message); } finally { setBusy(""); }
  };
  const learn = agent.learn || {};
  return <div className="card card-pad dc-agent-card">
    <div className="dc-panel-head"><div><div className="card-title">{agent.name} <span className="faint">· {agent.title}</span></div><div className="faint">{agent.aiReady ? "AI ready" : "no Claude key"}{agent.creedLoaded ? " · creed ✓" : ""}{agent.playbookLoaded ? " · playbook ✓" : ""}</div></div></div>
    <div className="dc-chip-row">
      <span className="pill" style={{ color: agent.aiReady ? "#22C55E" : "#F87171", background: (agent.aiReady ? "#22C55E" : "#F87171") + "22" }}>{agent.aiReady ? "ready" : "no key"}</span>
      {typeof agent.briefCount === "number" && <span className="pill">{agent.briefCount} briefs</span>}
      {typeof agent.runCount === "number" && <span className="pill">{agent.runCount} runs</span>}
      {typeof learn.learnCount === "number" && <span className="pill">learned ×{learn.learnCount}</span>}
    </div>
    <div className="dc-modal-actions">
      <button className="dc-primary" disabled={!!busy} onClick={() => act(runPath, "run")}>{busy === "run" ? "Running…" : "Run"}</button>
      <button className="dc-quiet" disabled={!!busy} onClick={() => act(learnPath, "learn")}>{busy === "learn" ? "Learning…" : "Self-improve"}</button>
      {tab && <button className="link" onClick={() => window.GoTo(tab)}>Open tab →</button>}
    </div>
  </div>;
}

function DropshipAgents() {
  const crew = window.DsUseResource("/agents", "agents", 30000);
  const brief = window.DsUseResource("/director/brief", "brief", 45000);
  const bus = window.DsUseResource("/director/bus", null, 30000);
  const agents = (crew.data && (Array.isArray(crew.data) ? crew.data : crew.data.agents)) || [];
  const byId = {}; agents.forEach((a) => { byId[a.agent] = a; });
  const b = (brief.data && brief.data.brief) || null;
  const busMsgs = Array.isArray(bus.data) ? bus.data : (bus.data && bus.data.messages) || [];
  const refresh = () => { crew.refresh(); brief.refresh(); bus.refresh(); };
  const section = (title, items) => (items && items.length) ? <div className="dc-brief-sec"><b>{title}</b><ul className="dc-notes">{items.map((x, i) => <li key={i}>{typeof x === "string" ? x : (x.title ? (x.title + (x.why ? " — " + x.why : "")) : (x.role ? (x.role + " → " + x.task) : JSON.stringify(x)))}</li>)}</ul></div> : null;
  return <div className="dc-page">
    <window.DsPageHead title="Agents — the Midas crew" copy="Midas directs; Hawk / Blaze / Otto specialize. Everyone proposes — you approve every outward action." actions={<button className="dc-outline" onClick={refresh}>Refresh</button>} />
    <window.DsState loading={crew.loading} error={crew.error} onRetry={refresh}>
      <div className="card card-pad dc-panel">
        <div className="dc-panel-head"><div><div className="card-title">Midas · E-com Director</div><div className="faint">{b ? (b.headline || "Latest operating brief") : "No brief yet — run Midas"}</div></div><div className="dc-modal-actions"><button className="dc-primary" onClick={() => window.DsRequest("/director/run", { body: {} }).then(refresh).catch((e) => window.alert(e.message))}>Run brief</button><button className="dc-quiet" onClick={() => window.DsRequest("/director/learn", { body: {} }).then(refresh).catch((e) => window.alert(e.message))}>Self-improve</button></div></div>
        {b ? <div className="dc-brief">{section("Attention now", b.priorities)}{section("Winners", b.winners)}{section("Money", b.money)}{section("Ops", b.ops)}{section("Delegations", b.delegations)}</div> : <div className="dc-inline-empty">Run Midas to generate a ranked operating brief (reads Shopify / AutoDS / Meta + the brief).</div>}
      </div>
      <div className="dc-crew-grid">
        {byId.hawk && <DsgAgentCard agent={byId.hawk} runPath="/hawk/run" learnPath="/hawk/learn" tab="Products" onDone={refresh} />}
        {byId.blaze && <DsgAgentCard agent={byId.blaze} runPath="/blaze/run" learnPath="/blaze/learn" tab="Ads" onDone={refresh} />}
        {byId.otto && <DsgAgentCard agent={byId.otto} runPath="/otto/run" learnPath="/otto/learn" tab="Customers" onDone={refresh} />}
      </div>
      <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Agent comms</div><div className="faint">the shared bus — handoffs + status across FORGE</div></div></div>{busMsgs.length ? <div className="dc-alert-list">{busMsgs.slice(0, 12).map((m, i) => <div key={m.id || i}><span className="dc-severity info" /><div><b>{m.from} → {m.to}</b><small>{m.text}</small></div></div>)}</div> : <div className="dc-inline-empty">No messages yet.</div>}</div>
    </window.DsState>
  </div>;
}

Object.assign(window, { DropshipAds, DropshipAnalytics, DropshipAgents });
