// agency_social.jsx — Social tab: Instagram + TikTok control via Metricool.
// Connection + real best-time heatmaps + post composer + scheduling queue +
// analytics. Posting executes via the Metricool MCP (operator) or REST (box w/
// token). Static-React: hooks aliased (…So), names prefixed So, shipped on window.
const { useState: useStateSo, useEffect: useEffectSo } = React;

const SO_NETS = [
  { id: "instagram", label: "Instagram", icon: "Conversations", color: "#E1306C" },
  { id: "tiktok",    label: "TikTok",    icon: "Spark",         color: "#2DD4BF" },
];
const SO_POST_STATUS = {
  draft:  { label: "Draft",  color: "#64748B" },
  ready:  { label: "Ready",  color: "#F59E0B" },
  posted: { label: "Posted", color: "#22C55E" },
  failed: { label: "Failed", color: "#EF4444" },
};
const SO_HOURS = [0, 3, 6, 9, 12, 15, 18, 21];

function SoConnBanner({ c }) {
  const Icons = window.Icons;
  if (!c) return null;
  return (
    <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span style={{ color: "var(--green)" }}><Icons.Spark size={18} /></span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 13.5, display: "flex", alignItems: "center", gap: 8 }}>
          <span className="dot online pulse" /> {c.source === "live" ? "Metricool connected" : "Metricool cockpit ready"} · <span className="mono">{c.brand}</span>
          <span className="faint" style={{ fontWeight: 400 }}>· Instagram + TikTok</span>
        </div>
        <div className="faint" style={{ fontSize: 12, marginTop: 2 }}>{c.note}</div>
      </div>
      <span style={{ fontSize: 11, fontWeight: 600, whiteSpace: "nowrap",
        color: c.autonomous ? "var(--green)" : "var(--orange)" }}>
        {c.autonomous ? "AUTONOMOUS" : "MCP-DRIVEN"}
      </span>
    </div>
  );
}

function SoHeatmap({ net }) {
  const { data } = window.useApi("/api/agency/social/besttime?network=" + net);
  if (!data) return <window.LoadingRow label="Loading best times…" />;
  const max = data.max || 1;
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div className="card-title">Best time to post · {net === "tiktok" ? "TikTok" : "Instagram"}</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {(data.top || []).map((t, i) => (
            <span key={i} style={{ fontSize: 11, fontWeight: 600, color: "#22C55E", background: "#22C55E1f",
              padding: "3px 9px", borderRadius: 999 }}>{t.day} {String(t.hour).padStart(2, "0")}:00</span>
          ))}
        </div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 10 }}>
          <thead>
            <tr>
              <th></th>
              {Array.from({ length: 24 }, (_, h) => (
                <th key={h} className="faint" style={{ fontWeight: 400, padding: "0 1px", width: 14 }}>
                  {SO_HOURS.includes(h) ? h : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data.rows || []).map((row) => (
              <tr key={row.dow}>
                <td className="faint" style={{ paddingRight: 8, fontSize: 11, whiteSpace: "nowrap" }}>{row.day}</td>
                {row.hours.map((v, h) => {
                  const a = Math.max(0.04, v / max);
                  return <td key={h} title={row.day + " " + String(h).padStart(2, "0") + ":00 · " + v}
                    style={{ width: 14, height: 16, background: "rgba(34,197,94," + a.toFixed(2) + ")",
                      borderRadius: 2 }} />;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="faint" style={{ fontSize: 11 }}>Times in {data.timezone}. Darker green = more of your audience online. Live from Metricool.</div>
    </div>
  );
}

function SoComposer({ net, onSaved }) {
  const Icons = window.Icons;
  const blank = { text: "", mediaUrl: "", link: "", scheduledAt: "" };
  const [f, setF] = useStateSo(blank);
  const [saving, setSaving] = useStateSo(false);
  const [err, setErr] = useStateSo(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  async function save() {
    if (!f.text.trim() && !f.mediaUrl.trim()) { setErr("Add caption text or a media URL"); return; }
    setSaving(true); setErr(null);
    try {
      await window.apiPost("/api/agency/social/post/save", { post: { ...f, network: net, status: "draft" } });
      setF(blank); onSaved && onSaved();
    } catch (e) { setErr(e.message || "Save failed"); }
    setSaving(false);
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ fontWeight: 600, fontSize: 15 }}>Compose · {net === "tiktok" ? "TikTok" : "Instagram"}</div>
      <textarea style={{ ...window.AgUI.inp, minHeight: 80, resize: "vertical", fontFamily: "inherit" }}
        value={f.text} onChange={(e) => set("text", e.target.value)} placeholder="Caption / script…" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div style={window.AgUI.field}><span style={window.AgUI.fieldLabel}>Media URL (image/video)</span>
          <input style={window.AgUI.inp} value={f.mediaUrl} onChange={(e) => set("mediaUrl", e.target.value)} placeholder="https://…" /></div>
        <div style={window.AgUI.field}><span style={window.AgUI.fieldLabel}>Link (optional)</span>
          <input style={window.AgUI.inp} value={f.link} onChange={(e) => set("link", e.target.value)} placeholder="https://…" /></div>
      </div>
      <div style={window.AgUI.field}><span style={window.AgUI.fieldLabel}>Schedule (your time)</span>
        <input type="datetime-local" style={window.AgUI.inp} value={f.scheduledAt} onChange={(e) => set("scheduledAt", e.target.value)} /></div>
      {err && <div style={{ color: "var(--red)", fontSize: 12.5 }}>{err}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button className="tab" onClick={save} disabled={saving}
          style={{ background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
          <Icons.Plus size={14} /> {saving ? "Saving…" : "Save to queue"}
        </button>
      </div>
    </div>
  );
}

function SoPostRow({ p, onChanged }) {
  const Icons = window.Icons;
  const [busy, setBusy] = useStateSo(false);
  async function act(fn) { setBusy(true); try { await fn(); onChanged && onChanged(); } catch (e) { window.alert(e.message || e); } setBusy(false); }
  const status = (s) => window.apiPost("/api/agency/social/post/status", { id: p.id, status: s });
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ minWidth: 0, flex: 1, fontSize: 13.5, whiteSpace: "pre-wrap" }}>{p.text || <span className="faint">(media only)</span>}</div>
        <window.AgUI.Badge status={p.status} map={SO_POST_STATUS} />
      </div>
      <div className="faint" style={{ fontSize: 11.5, display: "flex", gap: 12, flexWrap: "wrap" }}>
        {p.scheduledAt && <span>⏰ {p.scheduledAt.replace("T", " ")}</span>}
        {p.mediaUrl && <span>🖼 media</span>}
        {p.link && <span>🔗 link</span>}
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
        {p.status === "draft" && <button className="tab" disabled={busy} onClick={() => act(() => status("ready"))}
          style={{ color: "#F59E0B" }}>Mark Ready</button>}
        {p.status === "ready" && <span className="faint" style={{ fontSize: 11.5 }}>Awaiting Approval Center decision</span>}
        <button className="tab" disabled={busy} onClick={() => { if (window.confirm("Delete this post?")) act(() => window.apiPost("/api/agency/social/post/delete", { id: p.id })); }}
          style={{ color: "var(--red)" }}>✕</button>
      </div>
    </div>
  );
}

function SoQueue({ net, refreshKey }) {
  const { data, loading, refresh } = window.useApi("/api/agency/social/posts?network=" + net + "&k=" + refreshKey);
  const Icons = window.Icons;
  const posts = (data && data.posts) || [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="card-title">Queue · {posts.length}</div>
      {loading && !data && <window.LoadingRow label="Loading posts…" />}
      {!loading && posts.length === 0 && (
        <div className="card empty" style={{ minHeight: "24vh" }}>
          <div className="empty-ico" style={{ width: 60, height: 60 }}><Icons.Calendar size={26} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 15 }}>No posts queued</div>
          <div style={{ fontSize: 12.5, maxWidth: 320, textAlign: "center" }}>Compose one above. Mark it Ready, then approve it in the Approval Center before Metricool publishing.</div>
        </div>
      )}
      {posts.map((p) => <SoPostRow key={p.id} p={p} onChanged={refresh} />)}
    </div>
  );
}

function AgencySocial() {
  const Icons = window.Icons;
  const { data: conn } = window.useApi("/api/agency/social", { interval: 30000 });
  const { data: stats } = window.useApi("/api/agency/social/analytics", {});
  const [net, setNet] = useStateSo("instagram");
  const [k, setK] = useStateSo(0);
  const analytics = window.useApi("/api/agency/social/analytics?network=" + net);
  const a = analytics.data || {};

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Social</h1>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>Instagram + TikTok — best times, compose, schedule, and post via Metricool.</div>
      </div>

      <SoConnBanner c={conn} />

      <div className="tabs" style={{ display: "flex", gap: 8 }}>
        {SO_NETS.map((n) => (
          <button key={n.id} className={"tab" + (net === n.id ? " active" : "")} onClick={() => setNet(n.id)}>{n.label}</button>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
        <window.AgUI.AnalyticsCard label="Followers" value={a.followers || 0} icon="Leads" color="#8B5CF6" sub={net === "tiktok" ? "TikTok" : "Instagram"} />
        <window.AgUI.AnalyticsCard label="Posts" value={a.posts || 0} icon="Doc" color="#4F7CFF" />
        <window.AgUI.AnalyticsCard label="Engagement" value={a.engagement || 0} suffix="%" icon="Trend" color="#22C55E" />
      </div>
      {a.note && <div className="faint" style={{ fontSize: 11.5, marginTop: -6 }}>{a.note}</div>}

      <SoHeatmap net={net} />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(320px, 1fr) minmax(320px, 1fr)", gap: 16, alignItems: "start" }}>
        <SoComposer net={net} onSaved={() => setK((x) => x + 1)} />
        <SoQueue net={net} refreshKey={k} />
      </div>
    </div>
  );
}

Object.assign(window, { AgencySocial });
