// agency.jsx — Forge AI Agency workspace (ClientForge ops, live + persistent).
// Data lives server-side via /api/agency/* (agency_io.py). Hooks are aliased
// (…Ag) so this file's top-level consts don't collide with the other scripts.
const { useState: useStateAg, useEffect: useEffectAg } = React;

const AG_STATUS = {
  lead:     { label: "Lead",       color: "#4F7CFF" },
  building: { label: "Building",   color: "#F59E0B" },
  active:   { label: "Active",     color: "#22C55E" },
  paused:   { label: "Paused",     color: "#8B5CF6" },
  churned:  { label: "Churned",    color: "#64748B" },
};
const AG_ORDER = ["lead", "building", "active", "paused", "churned"];
const AG_PLANS = ["Starter", "Growth", "Pro", "Custom"];
// What a client signed up for — dashboard tags, mirrored to GHL as "signed: x".
const AG_SERVICES = ["Website", "Automations", "AI Receptionist", "AI Chatbot",
  "Ads Management", "SEO", "Lead Gen", "Social Media", "CRM Setup", "Hosting"];
const AG_SVC_COLOR = {
  "Website": "#4F7CFF", "Automations": "#F59E0B", "AI Receptionist": "#2DD4BF",
  "AI Chatbot": "#8B5CF6", "Ads Management": "#EC4899", "SEO": "#22C55E",
  "Lead Gen": "#EF4444", "Social Media": "#E1306C", "CRM Setup": "#0EA5E9",
  "Hosting": "#64748B",
};
const agInp = {
  background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 9,
  padding: "9px 11px", color: "var(--text)", fontSize: 13, width: "100%", outline: "none",
};
const agMoney = (n) => (window.fmtMoney ? window.fmtMoney(n) : "$" + (Number(n) || 0));

function AgPill({ status }) {
  const m = AG_STATUS[status] || AG_STATUS.lead;
  return (
    <span style={{ fontSize: 11, fontWeight: 600, color: m.color, background: m.color + "1f",
      padding: "3px 9px", borderRadius: 999, whiteSpace: "nowrap" }}>{m.label}</span>
  );
}

function AgSvcPill({ name, onRemove }) {
  const color = AG_SVC_COLOR[name] || "#64748B";
  return (
    <span style={{ fontSize: 10.5, fontWeight: 600, color, background: color + "1f",
      padding: "2px 8px", borderRadius: 999, whiteSpace: "nowrap", display: "inline-flex", alignItems: "center", gap: 4 }}>
      {name}{onRemove && <span style={{ cursor: "pointer", opacity: 0.7 }} onClick={onRemove}>✕</span>}
    </span>
  );
}

function AgKpi({ kpi }) {
  const Icons = window.Icons;
  const Ico = Icons[kpi.icon] || Icons.Dashboard;
  return (
    <div className="kpi">
      <div className="kpi-ico" style={{ background: kpi.color + "1f", color: kpi.color }}><Ico size={18} /></div>
      <div className="kpi-label">{kpi.label}</div>
      <div className="kpi-val"><window.CountUp to={Number(kpi.value || 0)} prefix={kpi.prefix || ""} /></div>
      <div className="kpi-delta"><span className="faint">{kpi.sub || ""}</span></div>
    </div>
  );
}

// Agency's OWN GoHighLevel sub-account status + live counts (separate from wholesale).
function AgGhlPanel() {
  const Icons = window.Icons;
  const { data, loading } = window.useApi("/api/agency/ghl/dashboard", { interval: 30000 });
  if (loading && !data) return null;
  const connected = data && data.connected;

  if (!connected) {
    return (
      <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 12, borderColor: "var(--orange)" }}>
        <span style={{ color: "var(--orange)" }}><Icons.Conversations size={18} /></span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13.5 }}>GoHighLevel — not connected</div>
          <div className="faint" style={{ fontSize: 12 }}>
            Add your agency sub-account key to <span className="mono">forge-agency/config/agency.env</span> (separate from wholesale), then redeploy.
          </div>
        </div>
        <span className="faint" style={{ fontSize: 11.5, whiteSpace: "nowrap" }}>separate account</span>
      </div>
    );
  }
  const k = [
    { label: "GHL Contacts",   icon: "Leads",         color: "#8B5CF6", value: data.totalContacts },
    { label: "Conversations",  icon: "Conversations", color: "#2DD4BF", value: data.totalConversations, sub: (data.unread || 0) + " unread" },
    { label: "Open Opps",      icon: "Pipeline",      color: "#4F7CFF", value: data.openOpportunities },
    { label: "GHL Pipeline",   icon: "Dollar",        color: "#22C55E", value: data.pipelineValue, prefix: "$" },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="dot online pulse" />
        <span className="faint" style={{ fontSize: 12 }}>Agency GoHighLevel connected · <span className="mono">{data.locationId}</span></span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
        {k.map((x) => <AgKpi key={x.label} kpi={x} />)}
      </div>
    </div>
  );
}

// Per-client request-portal link. Each client gets their OWN token-scoped link
// (?c=<id>&k=<token>) — they only ever see + submit their own requests, so nothing
// is cross-contaminated between clients. `compact` = a one-tap generate+copy button
// (for the client row); full = the labeled panel (for the client form).
function AgPortalLink({ clientId, compact }) {
  const [url, setUrl] = useStateAg("");
  const [busy, setBusy] = useStateAg(false);
  const [copied, setCopied] = useStateAg(false);
  const [err, setErr] = useStateAg(null);

  async function gen(rotate) {
    if (!clientId) { setErr("Save the client first"); return; }
    if (rotate && !window.confirm("Generate a NEW link? This client's current link stops working.")) return;
    setBusy(true); setErr(null);
    try {
      const r = await window.apiPost("/api/agency/portal/token", { clientId, rotate: !!rotate });
      if (r && r.url) {
        setUrl(r.url);
        try { await navigator.clipboard.writeText(r.url); setCopied(true); setTimeout(() => setCopied(false), 1600); } catch (e) {}
        return r.url;
      }
      setErr((r && r.error) || "Failed");
    } catch (e) { setErr(e.message || "Failed"); }
    finally { setBusy(false); }
  }
  async function copy() {
    if (!url) return;
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1600); }
    catch (e) { window.prompt("Copy this link:", url); }
  }

  if (compact) {
    return (
      <button className="tab" style={{ padding: "5px 10px", fontSize: 12, color: copied ? "var(--green)" : undefined }}
        disabled={busy} onClick={() => gen(false)} title="Generate + copy this client's private request-portal link">
        {copied ? "Link copied ✓" : (busy ? "…" : "🔗 Portal link")}
      </button>
    );
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 12, background: "var(--card-2)" }}>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 3 }}>🔗 Client Request Portal</div>
      <div className="faint" style={{ fontSize: 11, marginBottom: 10 }}>
        This client's own private link. They submit + track only their own edit requests — nothing is shared
        between clients. Send it once; it keeps working until you regenerate it.
      </div>
      {!clientId && <div className="faint" style={{ fontSize: 12 }}>Save the client first, then generate their link.</div>}
      {clientId && !url && (
        <button className="tab" disabled={busy} onClick={() => gen(false)}
          style={{ background: "#8B5CF6", color: "#fff", fontWeight: 700, borderColor: "transparent" }}>
          {busy ? "Generating…" : "Generate portal link"}
        </button>
      )}
      {url && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <input readOnly value={url} onClick={(e) => e.target.select()} style={{ ...agInp, fontFamily: "var(--mono, monospace)", fontSize: 12 }} />
          <div style={{ display: "flex", gap: 8 }}>
            <button className="tab" onClick={copy} style={{ color: copied ? "var(--green)" : undefined }}>
              {copied ? "Copied ✓" : "Copy link"}</button>
            <button className="tab" disabled={busy} onClick={() => gen(true)} style={{ color: "var(--muted)" }}>Regenerate</button>
          </div>
        </div>
      )}
      {err && <div style={{ color: "var(--red)", fontSize: 12, marginTop: 6 }}>{err}</div>}
    </div>
  );
}

// Add / edit a client. onSaved() refreshes the parent list.
function AgClientForm({ initial, onSaved, onCancel }) {
  const blankWs = { repo: "", branch: "", liveUrl: "", stack: "", brand: "", assets: "", accessNotes: "" };
  const blank = { name: "", business: "", site: "", plan: "Growth", mrr: "", status: "lead", services: [], ghlContactId: "", notes: "", workspace: blankWs };
  const [f, setF] = useStateAg(initial ? { ...blank, ...initial, mrr: initial.mrr || "", services: initial.services || [], workspace: { ...blankWs, ...(initial.workspace || {}) } } : blank);
  const toggleSvc = (s) => setF((st) => ({ ...st, services: (st.services || []).includes(s)
    ? st.services.filter((x) => x !== s) : [...(st.services || []), s] }));
  const [saving, setSaving] = useStateAg(false);
  const [err, setErr] = useStateAg(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const setWs = (k, v) => setF((s) => ({ ...s, workspace: { ...(s.workspace || blankWs), [k]: v } }));

  async function submit() {
    if (!f.name.trim()) { setErr("Name is required"); return; }
    setSaving(true); setErr(null);
    try {
      await window.apiPost("/api/agency/client/save", { client: { ...f, mrr: Number(f.mrr) || 0 } });
      onSaved && onSaved();
    } catch (e) { setErr(e.message || "Save failed"); }
    setSaving(false);
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontWeight: 600, fontSize: 15 }}>{initial ? "Edit client" : "New client"}</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Name *</div>
          <input style={agInp} value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Client / contact name" /></div>
        <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Business</div>
          <input style={agInp} value={f.business} onChange={(e) => set("business", e.target.value)} placeholder="Company" /></div>
        <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Website</div>
          <input style={agInp} value={f.site} onChange={(e) => set("site", e.target.value)} placeholder="example.com" /></div>
        <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Plan</div>
          <select style={agInp} value={f.plan} onChange={(e) => set("plan", e.target.value)}>
            {AG_PLANS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select></div>
        <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>MRR ($/mo)</div>
          <input style={agInp} type="number" value={f.mrr} onChange={(e) => set("mrr", e.target.value)} placeholder="0" /></div>
        <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Status</div>
          <select style={agInp} value={f.status} onChange={(e) => set("status", e.target.value)}>
            {AG_ORDER.map((s) => <option key={s} value={s}>{AG_STATUS[s].label}</option>)}
          </select></div>
      </div>
      <div>
        <div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Signed services (tags) — also pushed to GHL</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
          {AG_SERVICES.map((s) => {
            const on = (f.services || []).includes(s);
            const color = AG_SVC_COLOR[s] || "#64748B";
            return (
              <button key={s} type="button" onClick={() => toggleSvc(s)}
                style={{ fontSize: 11.5, fontWeight: 600, padding: "5px 11px", borderRadius: 999,
                  cursor: "pointer", border: "1px solid " + (on ? color : "var(--border)"),
                  color: on ? color : "var(--muted)", background: on ? color + "1f" : "transparent" }}>
                {on ? "✓ " : ""}{s}
              </button>
            );
          })}
        </div>
      </div>
      <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>GHL Contact ID (optional — tags applied to this contact on sync)</div>
        <input style={agInp} value={f.ghlContactId} onChange={(e) => set("ghlContactId", e.target.value)} placeholder="paste the agency GHL contact id" /></div>
      {/* Workspace & Access — gives the agents (Dyson) the repo + context to make real changes. */}
      <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 12, background: "var(--card-2)" }}>
        <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 3 }}>🛠 Workspace &amp; Access</div>
        <div className="faint" style={{ fontSize: 11, marginBottom: 10 }}>
          Link the site's GitHub repo and Dyson can write the change itself and open a PR you merge to go live.
          No passwords here — put logins in your password manager and note where.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>GitHub repo (owner/repo)</div>
            <input style={agInp} value={f.workspace.repo} onChange={(e) => setWs("repo", e.target.value)} placeholder="yahglizz/bloom-dental" /></div>
          <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Live URL</div>
            <input style={agInp} value={f.workspace.liveUrl} onChange={(e) => setWs("liveUrl", e.target.value)} placeholder="https://bloomdental.com" /></div>
          <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Stack</div>
            <input style={agInp} value={f.workspace.stack} onChange={(e) => setWs("stack", e.target.value)} placeholder="Static HTML · React/Vite · Next.js" /></div>
          <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Deploy branch (optional)</div>
            <input style={agInp} value={f.workspace.branch} onChange={(e) => setWs("branch", e.target.value)} placeholder="main (default)" /></div>
        </div>
        <div style={{ marginTop: 10 }}><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Brand / design notes (so the agent matches the look)</div>
          <textarea style={{ ...agInp, minHeight: 44, resize: "vertical", fontFamily: "inherit" }}
            value={f.workspace.brand} onChange={(e) => setWs("brand", e.target.value)} placeholder="Colors, fonts, voice, do's & don'ts" /></div>
        <div style={{ marginTop: 10 }}><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Assets (logo / brand kit / image links)</div>
          <input style={agInp} value={f.workspace.assets} onChange={(e) => setWs("assets", e.target.value)} placeholder="Drive / Figma / asset URLs" /></div>
        <div style={{ marginTop: 10 }}><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Access notes (where logins live — NOT the passwords)</div>
          <textarea style={{ ...agInp, minHeight: 44, resize: "vertical", fontFamily: "inherit" }}
            value={f.workspace.accessNotes} onChange={(e) => setWs("accessNotes", e.target.value)} placeholder="e.g. Hosting = Vercel (my account). Domain at Namecheap. Logins in 1Password › Bloom." /></div>
      </div>
      <div><div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Notes</div>
        <textarea style={{ ...agInp, minHeight: 60, resize: "vertical", fontFamily: "inherit" }}
          value={f.notes} onChange={(e) => set("notes", e.target.value)} placeholder="What you're building for them, status, next step…" /></div>
      <AgPortalLink clientId={f.id} />
      {err && <div style={{ color: "var(--red)", fontSize: 12.5 }}>{err}</div>}
      <div style={{ display: "flex", gap: 9, justifyContent: "flex-end" }}>
        <button className="tab" onClick={onCancel}>Cancel</button>
        <button className="tab" onClick={submit} disabled={saving}
          style={{ background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
          {saving ? "Saving…" : (initial ? "Save changes" : "Add client")}
        </button>
      </div>
    </div>
  );
}

function AgClientRow({ c, onEdit, onDelete, onChanged }) {
  const Icons = window.Icons;
  const [syncing, setSyncing] = useStateAg(false);
  const svcs = c.services || [];

  async function syncGhl() {
    setSyncing(true);
    try {
      const r = await window.apiPost("/api/agency/client/sync-ghl", { id: c.id });
      const created = ((r.ensured || {}).created || []).length;
      const applied = ((r.applied || {}).applied || []).length;
      window.alert("GHL: " + (created ? created + " tag(s) created. " : "tags already exist. ")
        + (applied ? applied + " applied to the linked contact." : (c.ghlContactId ? "" : "Link a GHL contact id to tag a specific contact.")));
      onChanged && onChanged();
    } catch (e) { window.alert("GHL sync failed: " + (e.message || e)); }
    setSyncing(false);
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ width: 38, height: 38, borderRadius: 10, flexShrink: 0, display: "grid", placeItems: "center",
          background: (AG_STATUS[c.status] || AG_STATUS.lead).color + "1f", color: (AG_STATUS[c.status] || AG_STATUS.lead).color, fontWeight: 700 }}>
          {(c.name || "?").slice(0, 1).toUpperCase()}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{c.name}</div>
          <div className="faint" style={{ fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {[c.business, c.site].filter(Boolean).join(" · ") || "—"}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontWeight: 700, fontSize: 14 }}>{agMoney(c.mrr)}<span className="faint" style={{ fontSize: 11, fontWeight: 400 }}>/mo</span></div>
          <div className="faint" style={{ fontSize: 11 }}>{c.plan || "—"}</div>
        </div>
        <AgPill status={c.status} />
        <button className="tab" style={{ padding: "6px 9px" }} onClick={() => onEdit(c)}><Icons.Settings size={14} /></button>
        <button className="tab" style={{ padding: "6px 9px", color: "var(--red)" }}
          onClick={() => { if (window.confirm("Delete " + c.name + "?")) onDelete(c.id); }}>✕</button>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap", borderTop: "1px solid var(--border)", paddingTop: 9 }}>
        {svcs.length > 0 ? svcs.map((s) => <AgSvcPill key={s} name={s} />)
          : <span className="faint" style={{ fontSize: 11.5 }}>No services tagged — edit to add</span>}
        <div style={{ marginLeft: "auto", display: "flex", gap: 7 }}>
          <AgPortalLink clientId={c.id} compact />
          <button className="tab" style={{ padding: "5px 10px", fontSize: 12 }} disabled={syncing || svcs.length === 0} onClick={syncGhl}>
            <Icons.Conversations size={12} /> {syncing ? "Syncing…" : "Push tags to GHL"}
          </button>
        </div>
        {c.ghlSyncedAt && <span className="faint" style={{ fontSize: 11 }}>· synced</span>}
      </div>
    </div>
  );
}

function AgencyClients() {
  const Icons = window.Icons;
  const { data, error, loading, refresh } = window.useApi("/api/agency/clients");
  const [editing, setEditing] = useStateAg(null);   // client object or {} for new
  const [tagBusy, setTagBusy] = useStateAg(false);
  const clients = (data && data.clients) || [];

  async function del(id) {
    try { await window.apiPost("/api/agency/client/delete", { id }); refresh(); }
    catch (e) { window.alert("Delete failed: " + (e.message || e)); }
  }

  async function createGhlTags() {
    setTagBusy(true);
    try {
      const r = await window.apiPost("/api/agency/ghl/tags/sync", {});
      const made = (r.created || []).length, had = (r.existed || []).length;
      window.alert("GHL service tags ready: " + made + " created, " + had + " already existed.\n"
        + (r.tags || []).join(", "));
    } catch (e) { window.alert("Couldn't create GHL tags: " + (e.message || e)); }
    setTagBusy(false);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Clients</h1>
        {!editing && <div style={{ display: "flex", gap: 9 }}>
          <button className="tab" style={{ display: "flex", alignItems: "center", gap: 6 }}
            disabled={tagBusy} onClick={createGhlTags} title="Create the 'signed: …' service tags in your agency GHL sub-account">
            <Icons.Conversations size={14} /> {tagBusy ? "Creating…" : "Create GHL tags"}</button>
          <button className="tab" style={{ display: "flex", alignItems: "center", gap: 6 }}
            onClick={() => setEditing({})}><Icons.Plus size={14} /> Add Client</button>
        </div>}
      </div>
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {editing && <AgClientForm initial={editing.id ? editing : null}
        onSaved={() => { setEditing(null); refresh(); }} onCancel={() => setEditing(null)} />}

      {!editing && loading && <window.LoadingRow label="Loading clients…" />}
      {!editing && !loading && clients.length === 0 && (
        <div className="card empty" style={{ minHeight: "46vh" }}>
          <div className="empty-ico" style={{ width: 72, height: 72 }}><Icons.Leads size={30} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>No clients yet</div>
          <div style={{ fontSize: 13, maxWidth: 340, textAlign: "center" }}>Add your first ClientForge customer — plan, MRR, site, and status all tracked here.</div>
          <button className="tab" style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 6 }}
            onClick={() => setEditing({})}><Icons.Plus size={14} /> Add Client</button>
        </div>
      )}
      {!editing && clients.map((c) => <AgClientRow key={c.id} c={c} onEdit={setEditing} onDelete={del} onChanged={refresh} />)}
    </div>
  );
}

function AgencyDashboard() {
  const Icons = window.Icons;
  const { data: s, error, refresh } = window.useApi("/api/agency/stats", { interval: 20000 });
  const { data: cd } = window.useApi("/api/agency/clients", { interval: 20000 });
  const st = s || {};
  const recent = ((cd && cd.clients) || []).slice(0, 5);
  const kpis = [
    { label: "Active Clients", icon: "Leads",    color: "#22C55E", value: st.activeClients, sub: (st.totalClients || 0) + " total" },
    { label: "MRR",            icon: "Dollar",   color: "#22C55E", value: st.mrr, prefix: "$", sub: agMoney(st.arr) + "/yr" },
    { label: "Pipeline",       icon: "Pipeline", color: "#4F7CFF", value: st.leads, sub: "leads to close" },
    { label: "In Production",  icon: "Folder",   color: "#F59E0B", value: st.building, sub: "builds in flight" },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Forge AI Agency</h1>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>Command center for ClientForge — websites + AI agents.</div>
        </div>
        <button className="tab" style={{ display: "flex", alignItems: "center", gap: 6 }}
          onClick={() => window.GoTo && window.GoTo("Clients")}><Icons.Plus size={14} /> Add Client</button>
      </div>
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      <AgGhlPanel />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
        {kpis.map((k) => <AgKpi key={k.label} kpi={k} />)}
      </div>

      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div className="card-title">Recent clients</div>
          <button className="link" onClick={() => window.GoTo && window.GoTo("Clients")}>View all</button>
        </div>
        {recent.length === 0 && <div className="faint" style={{ fontSize: 13 }}>No clients yet — add your first from the Clients tab.</div>}
        {recent.map((c) => (
          <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <span style={{ fontWeight: 600, fontSize: 13.5 }}>{c.name}</span>
              <span className="faint" style={{ fontSize: 12 }}>  {c.business || c.site || ""}</span>
            </div>
            <span className="faint" style={{ fontSize: 12.5 }}>{agMoney(c.mrr)}/mo</span>
            <AgPill status={c.status} />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- AgencyPipeline helpers -------------------------------------------------
function AgPipeCard({ c, onStatusChange, busy }) {
  const [localStatus, setLocalStatus] = useStateAg(c.status);
  const [saving, setSavingPipe] = useStateAg(false);

  async function changeStatus(newStatus) {
    if (newStatus === localStatus) return;
    setLocalStatus(newStatus);
    setSavingPipe(true);
    try {
      await window.apiPost("/api/agency/client/save", { client: { ...c, status: newStatus } });
      onStatusChange && onStatusChange();
    } catch (e) {
      setLocalStatus(c.status); // revert on error
      window.alert("Status update failed: " + (e.message || e));
    }
    setSavingPipe(false);
  }

  return (
    <div style={{ background: "var(--card-2)", borderRadius: 9, padding: "9px 11px",
      display: "flex", flexDirection: "column", gap: 7 }}>
      <div style={{ fontWeight: 600, fontSize: 13 }}>{c.name}</div>
      <div className="faint" style={{ fontSize: 11.5 }}>
        {c.business || c.site || ""} · {agMoney(c.mrr)}/mo
      </div>
      <select value={localStatus} disabled={saving || busy}
        onChange={(e) => changeStatus(e.target.value)}
        style={{ ...agInp, padding: "5px 8px", fontSize: 11.5, opacity: saving ? 0.6 : 1 }}>
        {AG_ORDER.map((s) => (
          <option key={s} value={s}>{AG_STATUS[s].label}</option>
        ))}
      </select>
    </div>
  );
}

function AgencyPipeline() {
  const { data, error, loading, refresh } = window.useApi("/api/agency/clients", { interval: 20000 });
  const clients = (data && data.clients) || [];
  const cols = AG_ORDER.filter((s) => s !== "churned");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Pipeline</h1>
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {loading && !data && <window.LoadingRow label="Loading pipeline…" />}
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${cols.length}, 1fr)`, gap: 14, alignItems: "start" }}>
        {cols.map((s) => {
          const list = clients.filter((c) => c.status === s);
          const m = AG_STATUS[s];
          return (
            <div key={s} className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                borderBottom: "2px solid " + m.color, paddingBottom: 8 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>{m.label}</span>
                <span className="faint" style={{ fontSize: 12 }}>{list.length}</span>
              </div>
              {list.length === 0 && <div className="faint" style={{ fontSize: 12 }}>—</div>}
              {list.map((c) => (
                <AgPipeCard key={c.id} c={c} onStatusChange={refresh} />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- Inline SVG bar chart for MRR by client --------------------------------
function AgMrrBarChart({ clients }) {
  if (!clients || clients.length === 0) return null;
  const maxMrr = Math.max(...clients.map((c) => c.mrr));
  if (maxMrr === 0) return null;
  const BAR_H = 18;
  const BAR_GAP = 10;
  const LABEL_W = 120;
  const VALUE_W = 70;
  const CHART_W = 340;
  const chartH = clients.length * (BAR_H + BAR_GAP);

  return (
    <svg width="100%" viewBox={`0 0 ${LABEL_W + CHART_W + VALUE_W + 16} ${chartH}`}
      style={{ display: "block", overflow: "visible" }}>
      {clients.map((c, i) => {
        const barW = Math.max(4, Math.round((c.mrr / maxMrr) * CHART_W));
        const y = i * (BAR_H + BAR_GAP);
        const color = (AG_STATUS[c.status] || AG_STATUS.lead).color;
        return (
          <g key={c.id}>
            {/* label */}
            <text x={LABEL_W - 8} y={y + BAR_H * 0.72} textAnchor="end"
              fontSize="11" fill="var(--muted)"
              style={{ fontFamily: "inherit" }}>
              {(c.name || "").length > 14 ? c.name.slice(0, 13) + "…" : c.name}
            </text>
            {/* background track */}
            <rect x={LABEL_W} y={y} width={CHART_W} height={BAR_H}
              rx="4" fill="var(--card-2)" />
            {/* filled bar */}
            <rect x={LABEL_W} y={y} width={barW} height={BAR_H}
              rx="4" fill={color + "cc"} />
            {/* value */}
            <text x={LABEL_W + CHART_W + 8} y={y + BAR_H * 0.72}
              fontSize="11" fill="var(--text)" fontWeight="600"
              style={{ fontFamily: "inherit" }}>
              {agMoney(c.mrr)}/mo
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function AgencyRevenue() {
  const { data, error, refresh } = window.useApi("/api/agency/clients", { interval: 20000 });
  const { data: s } = window.useApi("/api/agency/stats", { interval: 20000 });
  const clients = ((data && data.clients) || []).filter((c) => c.mrr > 0)
    .sort((a, b) => b.mrr - a.mrr);
  const st = s || {};
  const totalMrr = clients.reduce((sum, c) => sum + c.mrr, 0);
  const totalArr = totalMrr * 12;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Revenue</h1>
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
        <AgKpi kpi={{ label: "MRR", icon: "Dollar", color: "#22C55E", value: st.mrr || totalMrr, prefix: "$", sub: "monthly recurring" }} />
        <AgKpi kpi={{ label: "ARR", icon: "Trend", color: "#22C55E", value: st.arr || totalArr, prefix: "$", sub: "annual run-rate" }} />
        <AgKpi kpi={{ label: "Paying Clients", icon: "Leads", color: "#4F7CFF", value: clients.length, sub: "with MRR > 0" }} />
      </div>

      {/* SVG bar chart */}
      {clients.length > 0 && (
        <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card-title">MRR by client</div>
          <AgMrrBarChart clients={clients} />
        </div>
      )}

      {/* ARR callout */}
      {clients.length > 0 && (
        <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 12,
          background: "#22C55E0d", borderColor: "#22C55E33" }}>
          <div style={{ flex: 1 }}>
            <div className="faint" style={{ fontSize: 12 }}>Annual Recurring Revenue (ARR)</div>
            <div style={{ fontWeight: 700, fontSize: 22, color: "#22C55E" }}>{agMoney(st.arr || totalArr)}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="faint" style={{ fontSize: 12 }}>Monthly</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{agMoney(st.mrr || totalMrr)}</div>
          </div>
        </div>
      )}

      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div className="card-title">By client</div>
        {clients.length === 0 && <div className="faint" style={{ fontSize: 13 }}>No paying clients yet.</div>}
        {clients.map((c) => (
          <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ flex: 1, minWidth: 0, fontWeight: 600, fontSize: 13.5 }}>{c.name}
              <span className="faint" style={{ fontWeight: 400, fontSize: 12 }}>  {c.plan}</span></div>
            <AgPill status={c.status} />
            <span style={{ fontWeight: 700, fontSize: 14 }}>{agMoney(c.mrr)}<span className="faint" style={{ fontSize: 11, fontWeight: 400 }}>/mo</span></span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- AgencyProjects helpers -------------------------------------------------
function AgProjectCard({ c, allRequests }) {
  const Icons = window.Icons;
  const reqs = (allRequests || []).filter((r) => r.clientId === c.id);
  const openReqs = reqs.filter((r) => ["submitted", "in_review", "approved", "in_progress"].indexOf(r.status) >= 0);
  const lastReq = reqs.length > 0
    ? reqs.slice().sort((a, b) => new Date(b.updatedAt || b.createdAt || 0) - new Date(a.updatedAt || a.createdAt || 0))[0]
    : null;
  const lastActivity = lastReq ? (lastReq.updatedAt || lastReq.createdAt) : null;

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, flexShrink: 0, display: "grid", placeItems: "center",
          background: (AG_STATUS[c.status] || AG_STATUS.lead).color + "1f",
          color: (AG_STATUS[c.status] || AG_STATUS.lead).color, fontWeight: 700, fontSize: 15 }}>
          {(c.name || "?").slice(0, 1).toUpperCase()}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{c.name}</div>
          <div className="faint" style={{ fontSize: 12 }}>
            {[c.business, c.site].filter(Boolean).join(" · ") || "—"}
          </div>
        </div>
        <AgPill status={c.status} />
      </div>

      {/* notes */}
      {c.notes && (
        <div className="faint" style={{ fontSize: 12.5, borderTop: "1px solid var(--border)", paddingTop: 9 }}>
          {c.notes}
        </div>
      )}

      {/* request detail row */}
      <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap",
        borderTop: "1px solid var(--border)", paddingTop: 9 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ color: "#4F7CFF", display: "flex" }}><Icons.Requests size={14} /></span>
          <span style={{ fontWeight: 600, fontSize: 13 }}>{openReqs.length}</span>
          <span className="faint" style={{ fontSize: 12 }}>open request{openReqs.length !== 1 ? "s" : ""}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span className="faint" style={{ fontSize: 12 }}>
            {reqs.length} total · last activity {lastActivity ? window.timeAgo(lastActivity) : "none"}
          </span>
        </div>
        {/* service pills */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginLeft: "auto" }}>
          {(c.services || []).slice(0, 3).map((s) => <AgSvcPill key={s} name={s} />)}
          {(c.services || []).length > 3 && (
            <span className="faint" style={{ fontSize: 11 }}>+{(c.services || []).length - 3}</span>
          )}
        </div>
      </div>

      {/* latest open request preview */}
      {openReqs.length > 0 && (
        <div style={{ background: "var(--card-2)", borderRadius: 8, padding: "8px 10px",
          display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 12.5 }}>{openReqs[0].title}</div>
            <div className="faint" style={{ fontSize: 11.5 }}>{openReqs[0].type} · {openReqs[0].priority} priority</div>
          </div>
          <window.AgUI.StatusBadge status={openReqs[0].status} />
        </div>
      )}
    </div>
  );
}

function AgencyProjects() {
  const { data, error, refresh } = window.useApi("/api/agency/clients", { interval: 20000 });
  const { data: reqData } = window.useApi("/api/agency/requests", { interval: 30000 });
  const Icons = window.Icons;
  const allRequests = (reqData && reqData.requests) || [];
  const builds = ((data && data.clients) || []).filter((c) => c.status === "building" || c.status === "active");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Projects</h1>
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {builds.length === 0 && (
        <div className="card empty" style={{ minHeight: "46vh" }}>
          <div className="empty-ico" style={{ width: 72, height: 72 }}><Icons.Folder size={30} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>No active builds</div>
          <div style={{ fontSize: 13, maxWidth: 340, textAlign: "center" }}>Clients marked Building or Active show up here as live projects.</div>
        </div>
      )}
      {builds.map((c) => (
        <AgProjectCard key={c.id} c={c} allRequests={allRequests} />
      ))}
    </div>
  );
}

// ---- AgencySettings helpers -------------------------------------------------
function AgSettingsTeamRow({ member, onRemove }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0",
      borderTop: "1px solid var(--border)" }}>
      <div style={{ width: 32, height: 32, borderRadius: 8, background: "#8B5CF61f", color: "#8B5CF6",
        display: "grid", placeItems: "center", fontWeight: 700, flexShrink: 0, fontSize: 13 }}>
        {(member.name || "?").slice(0, 1).toUpperCase()}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>{member.name}</div>
        <div className="faint" style={{ fontSize: 11.5 }}>{member.role || member.email || "—"}</div>
      </div>
      <button className="tab" style={{ padding: "4px 8px", color: "var(--red)", fontSize: 12 }}
        onClick={() => onRemove && onRemove(member)}>✕</button>
    </div>
  );
}

function AgencySettings() {
  const Icons = window.Icons;
  const { data, loading, refresh } = window.useApi("/api/agency/settings");
  const [f, setFAg] = useStateAg(null);
  const [saving, setSavingAg] = useStateAg(false);
  const [errAg, setErrAg] = useStateAg(null);
  const [okAg, setOkAg] = useStateAg(false);
  const [newMember, setNewMember] = useStateAg({ name: "", role: "" });

  // Sync form from API response once loaded (graceful empty-state for 404).
  useEffectAg(() => {
    if (data) {
      setFAg({
        billingSource: data.billingSource || "",
        defaultPlan: data.defaultPlan || "Growth",
        defaultServices: data.defaultServices || [],
        teamMembers: data.teamMembers || [],
      });
    } else if (!loading) {
      setFAg({
        billingSource: "", defaultPlan: "Growth", defaultServices: [], teamMembers: [],
      });
    }
  }, [data, loading]);

  const setField = (k, v) => setFAg((s) => ({ ...s, [k]: v }));

  function toggleSvcAg(s) {
    setFAg((st) => {
      const cur = st.defaultServices || [];
      return { ...st, defaultServices: cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s] };
    });
  }

  function removeTeamMember(member) {
    setFAg((st) => ({ ...st, teamMembers: (st.teamMembers || []).filter((m) => m !== member) }));
  }

  function addTeamMember() {
    if (!newMember.name.trim()) return;
    setFAg((st) => ({ ...st, teamMembers: [...(st.teamMembers || []), { ...newMember }] }));
    setNewMember({ name: "", role: "" });
  }

  async function saveSettings() {
    if (!f) return;
    setSavingAg(true); setErrAg(null); setOkAg(false);
    try {
      await window.apiPost("/api/agency/settings/save", { settings: f });
      setOkAg(true);
      refresh();
      setTimeout(() => setOkAg(false), 2500);
    } catch (e) {
      setErrAg(e.message || "Save failed");
    }
    setSavingAg(false);
  }

  if (loading && !f) return <window.LoadingRow label="Loading settings…" />;

  const settingsForm = f || { billingSource: "", defaultPlan: "Growth", defaultServices: [], teamMembers: [] };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Settings</h1>
        <button className="tab" onClick={saveSettings} disabled={saving || !f}
          style={{ background: saving ? undefined : "var(--green)", color: saving ? undefined : "#04210f",
            fontWeight: 700, borderColor: "transparent" }}>
          {saving ? "Saving…" : "Save settings"}
        </button>
      </div>

      {errAg && <div className="card card-pad" style={{ color: "var(--red)", fontSize: 13 }}>{errAg}</div>}
      {okAg && <div className="card card-pad" style={{ color: "var(--green)", fontSize: 13 }}>Settings saved.</div>}

      {/* Billing source */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="card-title">Billing</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div>
            <div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Billing source</div>
            <input style={agInp} value={settingsForm.billingSource}
              onChange={(e) => setField("billingSource", e.target.value)}
              placeholder="e.g. Stripe, Wave, Invoice Ninja…" />
          </div>
          <div>
            <div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Default plan for new clients</div>
            <select style={agInp} value={settingsForm.defaultPlan}
              onChange={(e) => setField("defaultPlan", e.target.value)}>
              {AG_PLANS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
        </div>
      </div>

      {/* Default services */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="card-title">Default services offered</div>
        <div className="faint" style={{ fontSize: 12 }}>Pre-selected when adding a new client.</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
          {AG_SERVICES.map((s) => {
            const on = (settingsForm.defaultServices || []).includes(s);
            const color = AG_SVC_COLOR[s] || "#64748B";
            return (
              <button key={s} type="button" onClick={() => toggleSvcAg(s)}
                style={{ fontSize: 11.5, fontWeight: 600, padding: "5px 11px", borderRadius: 999,
                  cursor: "pointer", border: "1px solid " + (on ? color : "var(--border)"),
                  color: on ? color : "var(--muted)", background: on ? color + "1f" : "transparent" }}>
                {on ? "✓ " : ""}{s}
              </button>
            );
          })}
        </div>
      </div>

      {/* Team members */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="card-title">Team members</div>
        {(settingsForm.teamMembers || []).length === 0 && (
          <div className="faint" style={{ fontSize: 12.5 }}>No team members added yet.</div>
        )}
        {(settingsForm.teamMembers || []).map((m, i) => (
          <AgSettingsTeamRow key={i} member={m} onRemove={removeTeamMember} />
        ))}
        <div style={{ display: "flex", gap: 9, alignItems: "flex-end", flexWrap: "wrap",
          borderTop: "1px solid var(--border)", paddingTop: 10 }}>
          <div style={{ flex: 1, minWidth: 140 }}>
            <div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Name</div>
            <input style={agInp} value={newMember.name}
              onChange={(e) => setNewMember((s) => ({ ...s, name: e.target.value }))}
              placeholder="Team member name" />
          </div>
          <div style={{ flex: 1, minWidth: 140 }}>
            <div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Role</div>
            <input style={agInp} value={newMember.role}
              onChange={(e) => setNewMember((s) => ({ ...s, role: e.target.value }))}
              placeholder="e.g. Developer, Designer" />
          </div>
          <button className="tab" onClick={addTeamMember}
            style={{ display: "flex", alignItems: "center", gap: 6, paddingBottom: 9 }}>
            <Icons.Plus size={13} /> Add
          </button>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { AgencyDashboard, AgencyClients, AgencyPipeline, AgencyProjects, AgencyRevenue, AgencySettings });
