// dropship_connections.jsx — Connections & MCP (FORGE Dropship).
// One page that answers "what is this store wired to, and is it actually up?":
//   1. REST integrations  — Shopify / AutoDS / Meta / PiPiAds health at a glance.
//   2. MCP servers        — registry + live probe (initialize → tools/list) + tool list.
//   3. Tool console       — run an MCP tool. OPERATOR-INITIATED ONLY; anything that is
//      not a read (search_/get_/list_/…) goes through a red confirm dialog first, and
//      the connector pins actor="operator" so no agent can ever reach it (rule 2).
// Tokens never appear here — a server references the NAME of an env var in dropship.env.
const { useState: useStateDsc, useEffect: useEffectDsc } = React;

const DSC_TRANSPORTS = [["http", "HTTP (Streamable)"], ["stdio", "stdio (local command)"]];
const DSC_BLANK = { id: "", name: "", transport: "http", url: "", command: "",
  authEnv: "", authScheme: "Bearer", authHeader: "Authorization", note: "" };

function DscArgsTemplate(schema) {
  // Seed the args box from the tool's own inputSchema so the operator isn't guessing.
  const props = (schema && schema.properties) || {};
  const required = (schema && Array.isArray(schema.required)) ? schema.required : [];
  const keys = required.length ? required : Object.keys(props).slice(0, 4);
  const out = {};
  keys.forEach((k) => {
    const t = (props[k] && props[k].type) || "string";
    out[k] = t === "number" || t === "integer" ? 0 : (t === "boolean" ? false : (t === "array" ? [] : ""));
  });
  return JSON.stringify(out, null, 2);
}

function DscBadge({ text, color = "#64748B" }) {
  return <span className="pill" style={{ color, background: color + "22" }}>{text}</span>;
}

function DscServerCard({ s, probing, expanded, onProbe, onToggle, onEdit, onDelete }) {
  const probe = s.lastProbe || {};
  const stdio = s.transport === "stdio";
  const tools = Array.isArray(probe.tools) ? probe.tools : [];
  const connected = !!probe.connected;
  const info = probe.serverInfo || {};
  const dot = stdio ? "#64748B" : (connected ? "#22C55E" : (s.configured ? "#F87171" : "#F4B860"));
  let status = "Add URL";
  if (stdio) status = "Runs in your Claude session — not reachable from the box";
  else if (connected) status = (info.name || "connected") + (info.version ? " v" + info.version : "");
  else if (probe.error) status = probe.error;
  else if (s.configured) status = "Not probed yet";
  else if (s.url && s.authEnv && !s.hasAuth) status = "Set " + s.authEnv + " in dropship.env";
  return <div className="card card-pad dc-panel" style={{ marginBottom: 12 }}>
    <div className="dc-panel-head">
      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
        <span className={"dc-integration-dot " + (connected ? "online" : "offline")} style={{ background: dot, marginTop: 5 }} />
        <div>
          <div className="card-title">{s.name}</div>
          <div className="faint">{status}</div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <DscBadge text={stdio ? "stdio" : "http"} color={stdio ? "#64748B" : "#38BDF8"} />
        {s.seeded && <DscBadge text="built-in" color="#8B5CF6" />}
        {s.authEnv && <DscBadge text={s.authEnv + (s.hasAuth ? " ✓" : " — missing")} color={s.hasAuth ? "#22C55E" : "#F4B860"} />}
        {tools.length > 0 && <DscBadge text={tools.length + " tools"} color="#22C55E" />}
        {!stdio && <button className="dc-outline" disabled={probing || !s.configured} onClick={onProbe}>{probing ? "Probing…" : "Probe"}</button>}
        <button className="link" onClick={onEdit}>Edit</button>
        <button className="link" onClick={onDelete}>{s.seeded ? "Reset" : "Delete"}</button>
      </div>
    </div>
    <div className="faint" style={{ marginTop: 6, wordBreak: "break-all" }}>
      <code>{stdio ? (s.command || "—") : (s.url || "no URL set")}</code>
    </div>
    {s.note && <div className="faint" style={{ marginTop: 6 }}>{s.note}</div>}
    {probe.instructions && <div className="faint" style={{ marginTop: 6 }}>{probe.instructions}</div>}
    {tools.length > 0 && <div style={{ marginTop: 10 }}>
      <button className="link" onClick={onToggle}>{expanded ? "Hide" : "Show"} {tools.length} tools</button>
      {expanded && <div className="tbl-wrap" style={{ marginTop: 8 }}>
        <table className="tbl"><thead><tr><th>Tool</th><th>Kind</th><th>What it does</th></tr></thead>
          <tbody>{tools.map((t) => <tr key={t.name}>
            <td><code>{t.name}</code></td>
            <td>{t.readOnly ? <DscBadge text="read" color="#22C55E" /> : <DscBadge text="write" color="#F4B860" />}</td>
            <td className="faint">{t.description || "—"}</td>
          </tr>)}</tbody></table>
      </div>}
    </div>}
  </div>;
}

function DropshipConnections() {
  const mcp = window.DsUseResource("/mcp", null, 60000);
  const shopify = window.DsUseResource("/shopify/health", null, 120000);
  const autods = window.DsUseResource("/autods/health", null, 120000);
  const pipiads = window.DsUseResource("/pipiads/health", null, 120000);
  const ads = window.DsUseResource("/ads", null, 120000);

  const [probing, setProbing] = useStateDsc("");
  const [expanded, setExpanded] = useStateDsc("");
  const [editing, setEditing] = useStateDsc(null);
  const [notice, setNotice] = useStateDsc("");
  const [confirm, setConfirm] = useStateDsc(null);
  const [con, setCon] = useStateDsc({ id: "", tool: "", args: "{}" });
  const [running, setRunning] = useStateDsc(false);
  const [result, setResult] = useStateDsc(null);

  const servers = (mcp.data && mcp.data.servers) || [];
  const receipts = (mcp.data && mcp.data.recent) || [];
  const live = servers.filter((s) => s.transport === "http" && s.lastProbe && Array.isArray(s.lastProbe.tools) && s.lastProbe.tools.length);
  const conServer = live.find((s) => s.id === con.id) || null;
  const conTools = conServer ? conServer.lastProbe.tools : [];
  const conTool = conTools.find((t) => t.name === con.tool) || null;

  // Keep the console pointed at something real as probes land.
  useEffectDsc(() => {
    if (!con.id && live.length) setCon((c) => ({ ...c, id: live[0].id }));
  }, [live.length]);

  const probe = async (id) => {
    setProbing(id); setNotice("");
    try {
      const r = await window.DsRequest("/mcp/probe", { body: { id } });
      setNotice(r.connected ? (r.name + " connected — " + (r.toolCount || 0) + " tools")
        : (r.name + ": " + (r.error || r.detail || "not connected")));
      mcp.refresh();
    } catch (e) { setNotice(e.message); } finally { setProbing(""); }
  };

  const save = async () => {
    setNotice("");
    try { await window.DsRequest("/mcp/save", { body: editing }); setEditing(null); setNotice("Server saved."); mcp.refresh(); }
    catch (e) { setNotice(e.message); }
  };

  const remove = async (s) => {
    setNotice("");
    try {
      const r = await window.DsRequest("/mcp/delete", { body: { id: s.id } });
      setNotice(r.revertedToDefault ? (s.name + " reset to its built-in default.") : (s.name + " removed."));
      mcp.refresh();
    } catch (e) { setNotice(e.message); }
  };

  const pickTool = (name) => {
    const t = conTools.find((x) => x.name === name);
    setCon({ ...con, tool: name, args: t ? DscArgsTemplate(t.inputSchema) : "{}" });
    setResult(null);
  };

  const fire = async () => {
    setRunning(true); setResult(null); setNotice("");
    let args = {};
    try { args = con.args.trim() ? JSON.parse(con.args) : {}; }
    catch (e) { setRunning(false); setNotice("Arguments must be valid JSON."); return; }
    try {
      const r = await window.DsRequest("/mcp/call", { body: { id: con.id, tool: con.tool, args } });
      setResult(r);
      if (!r.ok) setNotice(r.error || "Tool call failed.");
      mcp.refresh();
    } catch (e) { setNotice(e.message); } finally { setRunning(false); setConfirm(null); }
  };

  const run = () => {
    if (!conTool) return;
    if (conTool.readOnly) return fire();
    setConfirm({ server: conServer.name, tool: con.tool, args: con.args });
  };

  const sh = shopify.data || {}; const ad = autods.data || {};
  const pp = pipiads.data || {}; const meta = (ads.data && ads.data.connection) || {};

  return <div className="dc-page">
    <window.DsPageHead title="Connections & MCP"
      copy="Every system this store talks to — REST bridges and MCP servers — in one place. Keys live in dropship.env and never appear here; a server only references the NAME of its env var."
      actions={<button className="dc-outline" onClick={() => setEditing({ ...DSC_BLANK })}>+ Add MCP server</button>} />

    {notice && <div className="card card-pad" style={{ marginBottom: 12 }}><span className={notice.includes("connected") || notice.includes("saved") || notice.includes("reset") || notice.includes("removed") ? "dc-saved" : "dc-error-text"}>{notice}</span></div>}

    <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">REST integrations</div><div className="faint">The always-on bridges — read-only today, every write stays gated</div></div><button className="link" onClick={() => window.GoTo("Settings")}>Settings</button></div>
      <div className="dc-room-strip">
        <div><window.DsChannel name="Shopify (store)" connected={!!sh.connected} detail={sh.detail || sh.error} /></div>
        <div><window.DsChannel name="AutoDS (sourcing)" connected={!!ad.connected} detail={ad.detail || ad.error} /></div>
        <div><window.DsChannel name="Meta Ads" connected={!!(meta.connected || meta.source === "live")} detail="Add META_ACCESS_TOKEN" /></div>
        <div><window.DsChannel name="PiPiAds (trend spy)" connected={!!pp.connected} detail={pp.detail || pp.error} /></div>
      </div>
    </div>

    <div className="dc-panel-head" style={{ marginTop: 18 }}>
      <div><div className="card-title">MCP servers</div><div className="faint">Probe runs the real handshake (initialize → tools/list). A tool list here always comes from the server itself.</div></div>
    </div>
    <window.DsState loading={mcp.loading} error={mcp.error} empty={!servers.length} icon="Sliders"
      title="No MCP servers" copy="Add one to get started." onRetry={mcp.refresh}>
      <div>{servers.map((s) => <DscServerCard key={s.id} s={s}
        probing={probing === s.id}
        expanded={expanded === s.id}
        onProbe={() => probe(s.id)}
        onToggle={() => setExpanded(expanded === s.id ? "" : s.id)}
        onEdit={() => setEditing({ ...DSC_BLANK, ...s })}
        onDelete={() => remove(s)} />)}</div>
    </window.DsState>

    <div className="card card-pad dc-panel" style={{ marginTop: 6 }}>
      <div className="dc-panel-head"><div><div className="card-title">Tool console</div><div className="faint">You run these — agents cannot. Anything that isn't a read asks you to confirm first.</div></div></div>
      {!live.length ? <div className="dc-all-clear"><window.Icons.Bot size={22} /><div><b>No probed server yet</b><span>Probe an MCP server above; its tools show up here.</span></div></div> : <>
        <div className="dc-form-grid">
          <window.DsField label="Server">
            <select value={con.id} onChange={(e) => setCon({ id: e.target.value, tool: "", args: "{}" })}>
              {live.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </window.DsField>
          <window.DsField label="Tool">
            <select value={con.tool} onChange={(e) => pickTool(e.target.value)}>
              <option value="">— pick a tool —</option>
              {conTools.map((t) => <option key={t.name} value={t.name}>{t.name}{t.readOnly ? "" : "  (write)"}</option>)}
            </select>
          </window.DsField>
        </div>
        {conTool && <div className="faint" style={{ marginTop: 6 }}>{conTool.description || "No description from the server."}</div>}
        <textarea className="dc-textarea" rows="6" value={con.args} onChange={(e) => setCon({ ...con, args: e.target.value })} placeholder='{"query": "mug"}' />
        <div className="dc-modal-actions">
          {conTool && !conTool.readOnly && <span className="dc-error-text">Write tool — confirmation required</span>}
          <button className="dc-primary" disabled={running || !con.tool} onClick={run}>{running ? "Running…" : "Run tool"}</button>
        </div>
        {result && <div className="card card-pad" style={{ marginTop: 10 }}>
          <div className="faint" style={{ marginBottom: 6 }}>{result.ok ? "Result" : "Failed"} · <code>{result.tool}</code></div>
          <pre className="dc-pre">{JSON.stringify(result.ok ? result.result : (result.error || result), null, 2)}</pre>
        </div>}
      </>}
    </div>

    {receipts.length > 0 && <div className="card card-pad dc-panel" style={{ marginTop: 6 }}>
      <div className="dc-panel-head"><div><div className="card-title">Recent tool calls</div><div className="faint">Every invocation leaves a receipt here and on the agent bus</div></div><b>{receipts.length}</b></div>
      <div className="tbl-wrap"><table className="tbl"><thead><tr><th>When</th><th>Server</th><th>Tool</th><th>Kind</th><th>Result</th></tr></thead>
        <tbody>{receipts.map((r, i) => <tr key={i}>
          <td className="faint">{r.ts ? new Date(r.ts).toLocaleString() : "—"}</td>
          <td>{r.server}</td><td><code>{r.tool}</code></td>
          <td>{r.readOnly ? <DscBadge text="read" color="#22C55E" /> : <DscBadge text="write" color="#F4B860" />}</td>
          <td>{r.ok ? <DscBadge text="ok" color="#22C55E" /> : <span className="dc-error-text">{r.error || "failed"}</span>}</td>
        </tr>)}</tbody></table></div>
    </div>}

    {editing && <window.DsModal title={editing.id ? "Edit MCP server" : "Add MCP server"}
      copy="Tokens stay in dropship.env — put the variable NAME here, not the value."
      onClose={() => setEditing(null)} wide>
      <div className="dc-form-grid">
        <window.DsField label="Name"><input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder="e.g. AutoDS MCP" /></window.DsField>
        <window.DsField label="Transport">
          <select value={editing.transport} onChange={(e) => setEditing({ ...editing, transport: e.target.value })}>
            {DSC_TRANSPORTS.map((t) => <option key={t[0]} value={t[0]}>{t[1]}</option>)}
          </select>
        </window.DsField>
        {editing.transport === "stdio"
          ? <window.DsField label="Command" wide><input value={editing.command} onChange={(e) => setEditing({ ...editing, command: e.target.value })} placeholder="npx -y @shopify/dev-mcp@latest" /></window.DsField>
          : <window.DsField label="URL" wide><input value={editing.url} onChange={(e) => setEditing({ ...editing, url: e.target.value })} placeholder="https://your-store.myshopify.com/api/mcp" /></window.DsField>}
        <window.DsField label="Auth env var (optional)"><input value={editing.authEnv} onChange={(e) => setEditing({ ...editing, authEnv: e.target.value })} placeholder="AUTODS_MCP_TOKEN" /></window.DsField>
        <window.DsField label="Auth header"><input value={editing.authHeader} onChange={(e) => setEditing({ ...editing, authHeader: e.target.value })} placeholder="Authorization" /></window.DsField>
      </div>
      <div className="faint" style={{ marginTop: 8 }}>A stdio server runs in your Claude/operator session — the box can't reach it, so it's listed for reference only.</div>
      <div className="dc-modal-actions">
        <button className="dc-outline" onClick={() => setEditing(null)}>Cancel</button>
        <button className="dc-primary" disabled={!editing.name.trim()} onClick={save}>Save server</button>
      </div>
    </window.DsModal>}

    {confirm && <window.DsModal title="Run a write tool?"
      copy="This is not a read — it can change something on the other side. Nothing has run yet."
      onClose={() => setConfirm(null)}>
      <div className="dc-alert-list"><div><span className="dc-severity high" /><div>
        <b>{confirm.tool}</b><small>on {confirm.server}</small>
      </div></div></div>
      <pre className="dc-pre">{confirm.args}</pre>
      <div className="dc-modal-actions">
        <button className="dc-outline" onClick={() => setConfirm(null)}>Cancel</button>
        <button className="dc-primary" style={{ background: "#F87171", borderColor: "#F87171" }} disabled={running} onClick={fire}>{running ? "Running…" : "Yes, run it"}</button>
      </div>
    </window.DsModal>}
  </div>;
}

Object.assign(window, { DropshipConnections, DscBadge, DscServerCard, DscArgsTemplate, DSC_TRANSPORTS, DSC_BLANK });
