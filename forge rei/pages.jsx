// pages.jsx — live pages backed by the GoHighLevel connector.
const { useState: useStateP, useMemo: useMemoP, useEffect: useEffectP, useRef: useRefP } = React;

const scoreColor = (s) => (s >= 80 ? "#22C55E" : s >= 60 ? "#F59E0B" : "#EF4444");

// ---------------------------------------------------------------------------
// Leads — pulls contacts from GoHighLevel, with search + tag filter + detail.
// ---------------------------------------------------------------------------
function Leads() {
  const Icons = window.Icons;
  const [q, setQ] = useStateP("");
  const [tag, setTag] = useStateP("All");
  const [selected, setSelected] = useStateP(null);
  // Server search when a query is present, else list latest 100.
  const path = q.trim() ? `/api/contacts?limit=100&query=${encodeURIComponent(q.trim())}` : "/api/contacts?limit=100";
  const { data, error, loading, refresh } = window.useApi(path);
  const rows = (data && data.contacts) || [];

  const tags = useMemoP(() => {
    const set = new Set();
    rows.forEach((r) => (r.tags || []).forEach((t) => set.add(t)));
    return ["All", ...Array.from(set).sort().slice(0, 24)];
  }, [data]);

  const filtered = rows.filter((l) => tag === "All" || (l.tags || []).includes(tag));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Leads</h1>
          <p className="faint" style={{ fontSize: 13.5, marginTop: 3 }}>
            {data ? `${filtered.length} shown · ${(data.total || 0).toLocaleString()} total in GoHighLevel` : "Loading from GoHighLevel…"}
          </p>
        </div>
        <button className="tab" onClick={refresh} style={{ display: "flex", alignItems: "center", gap: 7, border: "1px solid var(--border)" }}>
          <Icons.Activity size={15} /> Refresh
        </button>
      </div>

      {error && <window.ErrorRow error={error} onRetry={refresh} />}

      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: 14, borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
          <div className="search" style={{ width: 300 }}>
            <Icons.Search size={16} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, phone, email…" />
          </div>
          <div className="tabs" style={{ flexWrap: "wrap" }}>
            {tags.map((s) => (
              <button key={s} className={"tab" + (tag === s ? " active" : "")} onClick={() => setTag(s)}>{s}</button>
            ))}
          </div>
        </div>

        <table className="lead-table">
          <thead>
            <tr><th>Lead</th><th>Phone</th><th>Email</th><th>Tags</th><th>Added</th><th></th></tr>
          </thead>
          <tbody>
            {filtered.map((l) => (
              <tr key={l.id} onClick={() => setSelected(l)} style={{ cursor: "pointer" }}>
                <td>
                  <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                    <div style={{ width: 34, height: 34, borderRadius: 10, background: "var(--card-2)", border: "1px solid var(--border)", display: "grid", placeItems: "center" }} className="faint"><Icons.Leads size={15} /></div>
                    <div>
                      <div style={{ fontWeight: 600 }}>{l.name}</div>
                      {l.addr && <div className="faint" style={{ fontSize: 11.5, display: "flex", alignItems: "center", gap: 4 }}><Icons.MapPin size={11} /> {l.addr}</div>}
                    </div>
                  </div>
                </td>
                <td className="muted mono" style={{ fontSize: 12.5 }}>{l.phone || "—"}</td>
                <td className="muted" style={{ fontSize: 12.5 }}>{l.email || "—"}</td>
                <td>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", maxWidth: 220 }}>
                    {(l.tags || []).slice(0, 3).map((t) => (
                      <span key={t} className="pill" style={{ background: "var(--card-2)", fontSize: 10.5 }}>{t}</span>
                    ))}
                    {(l.tags || []).length > 3 && <span className="faint" style={{ fontSize: 11 }}>+{l.tags.length - 3}</span>}
                  </div>
                </td>
                <td className="faint" style={{ fontSize: 12.5 }}>{window.timeAgo(l.dateAdded)}</td>
                <td><button className="faint" style={{ padding: 4 }}><Icons.ChevronR size={16} /></button></td>
              </tr>
            ))}
            {loading && (<tr><td colSpan="6"><window.LoadingRow /></td></tr>)}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan="6"><div className="empty"><div className="empty-ico"><Icons.Leads size={24} /></div><div style={{ fontWeight: 600, color: "var(--text)" }}>No matching leads</div></div></td></tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && <LeadDrawer lead={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function LeadDrawer({ lead, onClose }) {
  const Icons = window.Icons;
  const [tab, setTab] = useStateP("Details");
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 50, display: "flex", justifyContent: "flex-end" }}>
      <div onClick={(e) => e.stopPropagation()} className="card" style={{ width: 440, maxWidth: "92vw", height: "100%", borderRadius: 0, display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "20px 24px 0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: 14 }}>
            <div>
              <h2 style={{ fontSize: 20, fontWeight: 700 }}>{lead.name}</h2>
              <div className="faint mono" style={{ fontSize: 12, marginTop: 4 }}>{lead.phone || lead.id}</div>
            </div>
            <button className="tab" onClick={onClose}>Close</button>
          </div>
          <div className="tabs">
            {["Details", "Messages"].map((t) => (
              <button key={t} className={"tab" + (tab === t ? " active" : "")} onClick={() => setTab(t)}>
                {t === "Messages" ? <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><Icons.Message size={13} /> Messages</span> : t}
              </button>
            ))}
          </div>
        </div>

        {tab === "Details" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: 24, overflowY: "auto" }}>
            <Field icon="Phone" label="Phone" value={lead.phone} />
            <Field icon="Message" label="Email" value={lead.email} />
            <Field icon="MapPin" label="Address" value={lead.addr} />
            <Field icon="Spark" label="Source" value={lead.source} />
            <Field icon="Calendar" label="Added" value={lead.dateAdded ? new Date(lead.dateAdded).toLocaleString() : "—"} />
            <div>
              <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>Tags</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {(lead.tags || []).length ? lead.tags.map((t) => <span key={t} className="pill" style={{ background: "var(--card-2)" }}>{t}</span>) : <span className="faint">—</span>}
              </div>
            </div>
          </div>
        )}

        {tab === "Messages" && <LeadMessages lead={lead} />}
      </div>
    </div>
  );
}

function LeadMessages({ lead }) {
  const Icons = window.Icons;
  const { data, error, loading, refresh } = window.useApi(
    `/api/messages?contactId=${encodeURIComponent(lead.id)}`, { interval: 15000 });
  const [draft, setDraft] = useStateP("");
  const [sending, setSending] = useStateP(false);
  const [sent, setSent] = useStateP([]);      // optimistic local sends
  const [sendErr, setSendErr] = useStateP(null);
  const feedRef = React.useRef(null);

  const msgs = (data && data.messages) || [];
  const view = msgs.concat(sent.map((b) => ({ direction: "outbound", body: b, date: Date.now(), pending: true })));

  React.useEffect(() => { if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight; }, [data, sent]);

  async function send() {
    const body = draft.trim();
    if (!body || sending) return;
    if (!window.confirm(`Send this SMS to ${lead.name} (${lead.phone})?\n\n"${body}"`)) return;
    setSending(true); setSendErr(null);
    setSent((s) => [...s, body]);
    setDraft("");
    try {
      await window.apiPost("/api/send", { contactId: lead.id, message: body });
      setTimeout(() => { refresh(); setSent((s) => s.slice(1)); }, 1200);
    } catch (e) {
      setSendErr(e.message);
      setSent((s) => s.slice(0, -1));   // roll back optimistic bubble
      setDraft(body);
    }
    setSending(false);
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 24px", borderBottom: "1px solid var(--border)" }}>
        <span className="faint" style={{ fontSize: 12 }}>{data ? `${data.count} messages · GoHighLevel` : "Loading thread…"}</span>
        <button className="tab" onClick={refresh} style={{ fontSize: 11 }}>Refresh</button>
      </div>

      <div ref={feedRef} style={{ flex: 1, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
        {loading && !data && <window.LoadingRow label="Loading messages…" />}
        {error && <window.ErrorRow error={error} onRetry={refresh} />}
        {!loading && view.length === 0 && !error && (
          <div className="empty" style={{ flex: 1 }}>
            <div className="empty-ico"><Icons.Message size={24} /></div>
            <div style={{ fontWeight: 600, color: "var(--text)" }}>No messages yet</div>
            <div style={{ fontSize: 12 }}>Start the conversation below.</div>
          </div>
        )}
        {view.map((m, i) => {
          const out = m.direction === "outbound";
          return (
            <div key={i} style={{ display: "flex", justifyContent: out ? "flex-end" : "flex-start", opacity: m.pending ? 0.6 : 1 }}>
              <div style={{ maxWidth: "82%", padding: "9px 13px", borderRadius: 14, fontSize: 13, lineHeight: 1.4, whiteSpace: "pre-wrap",
                background: out ? "linear-gradient(135deg,#4F7CFF,#3a63e0)" : "var(--card-2)",
                color: out ? "#fff" : "var(--text)",
                border: out ? "none" : "1px solid var(--border)",
                borderBottomRightRadius: out ? 4 : 14, borderBottomLeftRadius: out ? 14 : 4 }}>
                {m.body}
                <div style={{ fontSize: 10, opacity: 0.6, marginTop: 4, textAlign: "right" }}>{m.pending ? "sending…" : window.timeAgo(m.date)}</div>
              </div>
            </div>
          );
        })}
      </div>

      {sendErr && <div style={{ padding: "6px 20px", fontSize: 11.5, color: "var(--red)" }}>Send failed: {sendErr}</div>}
      <div style={{ borderTop: "1px solid var(--border)", padding: 14, display: "flex", gap: 9, alignItems: "flex-end" }}>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          rows={1}
          placeholder={`Text ${(lead.name || "").split(" ")[0] || "lead"}…`}
          style={{ flex: 1, resize: "none", maxHeight: 120, background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 12, padding: "11px 13px", fontSize: 13, fontFamily: "inherit", lineHeight: 1.4 }}
        />
        <button onClick={send} disabled={sending || !draft.trim()}
          style={{ display: "grid", placeItems: "center", width: 42, height: 42, flexShrink: 0, borderRadius: 12, background: draft.trim() ? "linear-gradient(135deg,#4F7CFF,#3a63e0)" : "var(--card-2)", color: "#fff", opacity: sending ? 0.6 : 1 }}>
          <Icons.Send size={17} />
        </button>
      </div>
    </div>
  );
}

function Field({ icon, label, value }) {
  const Icons = window.Icons;
  const Ico = Icons[icon] || Icons.Spark;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <div style={{ width: 34, height: 34, borderRadius: 9, background: "var(--card-2)", display: "grid", placeItems: "center" }} className="faint"><Ico size={15} /></div>
      <div>
        <div className="faint" style={{ fontSize: 11.5 }}>{label}</div>
        <div style={{ fontSize: 13.5, fontWeight: 500 }}>{value || "—"}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Conversations — pulls all conversations, latest message, auto-refresh.
// ---------------------------------------------------------------------------
// iMessage-style: contact list on the left, tap a person -> thread + reply on the right.
function initials(name) {
  const parts = (name || "?").trim().split(/\s+/).filter(Boolean);
  return ((parts[0] || "?")[0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}
const AVA_COLORS = ["#4F7CFF", "#8B5CF6", "#2DD4BF", "#22C55E", "#F59E0B", "#EC4899", "#EF4444", "#0EA5E9"];
function avaColor(s) {
  let h = 0; for (let i = 0; i < (s || "").length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return AVA_COLORS[h % AVA_COLORS.length];
}

// Scout's triage list — ranked sellers to text back, by bucket. Clicking a card
// selects the conversation so the right pane shows the thread (reply via Marcus there).
function ScoutLeads({ bucket, activeId, onPick }) {
  const Icons = window.Icons;
  const { data, error, loading, refresh } = window.useApi(`/api/scout/leads?bucket=${bucket}`, { interval: 15000 });
  const [busy, setBusy] = useStateP(null);
  const [pipe, setPipe] = useStateP(null);
  const leads = (data && data.leads) || [];

  async function applyTags(e, id) {
    e.stopPropagation();
    setBusy(id);
    try { await window.apiPost("/api/scout/apply", { id }); refresh(); }
    catch (err) { alert("Apply tags failed: " + err.message); }
    setBusy(null);
  }

  async function toPipeline(e, id, stage) {
    e.stopPropagation();
    setPipe(id + stage);
    try {
      const r = await window.apiPost("/api/scout/pipeline", { id, stage });
      refresh();
      if (r && r.pipeline) { /* moved/created into r.stage of r.pipeline */ }
    } catch (err) { alert("Pipeline push failed: " + err.message); }
    setPipe(null);
  }

  // "Not actually hot" — strip the Scout hot tags off the GHL contact and mark its
  // opportunity Lost, then drop it from triage. GHL write, so confirm first.
  async function removeLead(e, l) {
    e.stopPropagation();
    if (!window.confirm(`Remove ${l.name} as a hot lead?\n\nThis takes the hot tags off the GHL contact and marks their opportunity Lost (reopenable in GHL).`)) return;
    setBusy("rm" + l.id);
    try {
      const r = await window.apiPost("/api/scout/remove", { id: l.id });
      if (r && r.errors && r.errors.length) alert("Removed, with warnings:\n" + r.errors.join("\n"));
      refresh();
    } catch (err) { alert("Remove failed: " + err.message); }
    setBusy(null);
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
      {loading && !data && <window.LoadingRow />}
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {leads.map((l) => {
        const on = activeId === l.id;
        return (
          <div key={l.id} onClick={() => onPick(l)} className="row-item"
            style={{ display: "block", padding: "11px 13px", borderBottom: "1px solid var(--border)", cursor: "pointer",
              background: on ? "var(--card-2)" : "transparent", borderLeft: on ? "3px solid var(--blue)" : "3px solid transparent" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 13.5, fontWeight: 600, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.name}</span>
              <span title="motivation" style={{ fontSize: 12, fontWeight: 800, color: scoreColor(l.motivation), flexShrink: 0 }}>{l.motivation}</span>
            </div>
            <div className="faint mono" style={{ fontSize: 11, marginTop: 1 }}>{l.phone || "no phone"} · {window.timeAgo(l.lastMessageDate)}</div>
            {l.reason && <div style={{ fontSize: 12, marginTop: 4, color: "var(--text)" }}>{l.reason}</div>}
            <div className="faint" style={{ fontSize: 12, marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>"{l.lastMessage || "—"}"</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 6 }}>
              {(l.proposedTags || []).map((t) => (
                <span key={t} className="pill" style={{ fontSize: 9.5, background: "var(--card-2)" }}>{t}</span>
              ))}
            </div>
            <div style={{ display: "flex", gap: 7, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
              {l.tagsAppliedAt
                ? <span className="pill" style={{ fontSize: 10, background: "rgba(34,197,94,0.12)", color: "var(--green)" }}>tags applied ✓</span>
                : <button className="tab" onClick={(e) => applyTags(e, l.id)} disabled={busy === l.id}
                    style={{ fontSize: 11, border: "1px solid var(--border)" }}>{busy === l.id ? "Applying…" : "Apply tags"}</button>}
              <button className="tab" onClick={(e) => { e.stopPropagation(); onPick(l); }} style={{ fontSize: 11, border: "1px solid var(--border)" }}>Open thread</button>
              <button className="tab" onClick={(e) => removeLead(e, l)} disabled={busy === "rm" + l.id} title="Not actually hot — remove tags + mark opportunity Lost"
                style={{ fontSize: 11, marginLeft: "auto", border: "1px solid rgba(239,68,68,0.4)", color: "#EF4444" }}>
                {busy === "rm" + l.id ? "Removing…" : "✕ Not hot"}</button>
            </div>
            <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
              {l.pipelineStage
                ? <span className="pill" style={{ fontSize: 9.5, background: "rgba(59,130,246,0.14)", color: "var(--blue)" }}>● in pipeline: {l.pipelineStage}</span>
                : <span className="faint" style={{ fontSize: 10 }}>add to pipeline:</span>}
              {[["hot", "🔥 Hot"], ["warm", "Warm"], ["follow-up", "Follow-up"]].map(([k, lab]) => (
                <button key={k} className="tab" disabled={pipe === l.id + k}
                  onClick={(e) => toPipeline(e, l.id, k)}
                  style={{ fontSize: 10.5, padding: "3px 8px", border: "1px solid var(--border)" }}>
                  {pipe === l.id + k ? "…" : lab}
                </button>
              ))}
            </div>
          </div>
        );
      })}
      {!loading && leads.length === 0 && (
        <div className="empty" style={{ padding: 30 }}><div className="empty-ico"><Icons.Spark size={22} /></div><div style={{ fontWeight: 600, color: "var(--text)", fontSize: 13 }}>Nothing here yet</div><div style={{ fontSize: 12 }}>Scout sweeps every few minutes.</div></div>
      )}
    </div>
  );
}

// Scout's deep-audit "Missed Leads" sweep — scans the last N days of seller threads
// for genuine signals we never capitalized on (dropped ball / went cold). Run sweep on
// demand; a weekly auto-sweep runs on the box. Clicking a row opens the thread.
function ScoutMissed({ onPick }) {
  const Icons = window.Icons;
  const { data, error, loading, refresh } = window.useApi("/api/scout/audit", { interval: 20000 });
  const [days, setDays] = useStateP(7);
  const [busy, setBusy] = useStateP(false);
  const [handed, setHanded] = useStateP({});   // convId -> "busy" | "done" | "err:<msg>"
  const a = data || {};
  const found = a.found || [];
  const ranAt = a.ranAt;
  const scanned = a.scanned || 0;

  async function runSweep() {
    setBusy(true);
    try { await window.apiPost("/api/scout/audit/run", { days }); }
    catch (err) { alert("Sweep failed: " + err.message); }
    setBusy(false);
    refresh();
  }

  // Hand a missed lead to Marcus: he drafts a re-engage reply (on Scout's angle) into
  // his approval inbox. Still gated — nothing sends until you approve in the Agents tab.
  async function handToMarcus(row) {
    setHanded((h) => ({ ...h, [row.id]: "busy" }));
    try {
      const r = await window.apiPost("/api/scout/handoff",
        { id: row.id, contactId: row.contactId, hint: row.recommendedAction || row.signal, lastSaid: row.lastSellerSaid });
      setHanded((h) => ({ ...h, [row.id]: (r && r.error) ? ("err:" + r.error) : "done" }));
    } catch (err) {
      setHanded((h) => ({ ...h, [row.id]: "err:" + err.message }));
    }
  }

  const DAY_OPTS = [7, 30, 60];

  return (
    <div style={{ flex: 1, overflowY: "auto", minHeight: 0, display: "flex", flexDirection: "column" }}>
      {/* Sweep controls */}
      <div style={{ padding: 12, borderBottom: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span className="faint" style={{ fontSize: 11, fontWeight: 700 }}>Window:</span>
          {DAY_OPTS.map((d) => (
            <button key={d} className={"tab" + (days === d ? " active" : "")} disabled={busy}
              onClick={() => setDays(d)} style={{ fontSize: 11, padding: "3px 9px", border: "1px solid var(--border)" }}>
              {d}d
            </button>
          ))}
          <button className="tab" onClick={runSweep} disabled={busy || a.running}
            style={{ fontSize: 11.5, fontWeight: 600, marginLeft: "auto", border: "1px solid var(--border)",
              background: busy ? "var(--card-2)" : "rgba(59,130,246,0.14)", color: "var(--blue)" }}>
            {busy || a.running ? "Sweeping…" : "Run sweep"}
          </button>
        </div>
        <div className="faint" style={{ fontSize: 10.5 }}>
          Deep-reads threads with Claude — can take ~10–20s.
        </div>
        {ranAt ? (
          <div className="faint mono" style={{ fontSize: 10.5 }}>
            Last swept {window.timeAgo(ranAt)} · scanned {scanned} · {found.length} missed
          </div>
        ) : (
          <div className="faint" style={{ fontSize: 10.5 }}>No sweep run yet.</div>
        )}
        {a.summary && (
          <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.4 }}>{a.summary}</div>
        )}
      </div>

      {/* Found rows */}
      <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
        {loading && !data && <window.LoadingRow />}
        {error && <window.ErrorRow error={error} onRetry={refresh} />}
        {found.map((row) => (
          <div key={row.id} onClick={() => onPick(row)} className="row-item"
            style={{ display: "block", padding: "11px 13px", borderBottom: "1px solid var(--border)", cursor: "pointer" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 13.5, fontWeight: 600, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.name}</span>
              {row.auto && <span className="pill" style={{ fontSize: 9, background: "var(--card-2)" }}>auto</span>}
              <span title="missed-lead score" style={{ fontSize: 12, fontWeight: 800, color: scoreColor(row.score), flexShrink: 0 }}>{row.score}</span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 4, alignItems: "center" }}>
              {row.signal && <span style={{ fontSize: 12, color: "var(--text)" }}>{row.signal}</span>}
              <span className="pill" style={{ fontSize: 9.5, background: "rgba(245,158,11,0.14)", color: "var(--amber, #F59E0B)" }}>cold {row.daysCold}d</span>
            </div>
            {row.lastSellerSaid && (
              <div className="faint" style={{ fontSize: 12, marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>"{row.lastSellerSaid}"</div>
            )}
            {row.recommendedAction && (
              <div style={{ fontSize: 12, marginTop: 5, color: "var(--blue)", fontWeight: 600 }}>→ {row.recommendedAction}</div>
            )}
            <div style={{ display: "flex", gap: 7, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
              <button className="tab" onClick={(e) => { e.stopPropagation(); onPick(row); }} style={{ fontSize: 11, border: "1px solid var(--border)" }}>Open thread</button>
              {(() => {
                const st = handed[row.id];
                if (st === "done") return <span className="pill" style={{ fontSize: 10.5, background: "rgba(236,72,153,0.14)", color: "#EC4899" }}>✓ Marcus has the draft — approve in Agents</span>;
                if (st && st.startsWith("err:")) return <span className="pill" style={{ fontSize: 10.5, background: "rgba(239,68,68,0.12)", color: "var(--red)" }} title={st.slice(4)}>handoff failed</span>;
                return (
                  <button className="tab" onClick={(e) => { e.stopPropagation(); handToMarcus(row); }} disabled={st === "busy"}
                    style={{ fontSize: 11, border: "1px solid #EC4899", color: "#EC4899", fontWeight: 600 }}
                    title="Marcus drafts a re-engage text on Scout's angle (review-gated — nothing sends yet)">
                    {st === "busy" ? "Handing…" : "→ Hand to Marcus"}
                  </button>
                );
              })()}
            </div>
          </div>
        ))}
        {!loading && found.length === 0 && (
          <div className="empty" style={{ padding: 30 }}>
            <div className="empty-ico"><Icons.Spark size={22} /></div>
            <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 13 }}>{ranAt ? "No missed leads found" : "No sweep run yet"}</div>
            <div style={{ fontSize: 12 }}>{ranAt ? "Clean window — nothing dropped." : "Run a sweep to deep-read your threads."}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function ConversationsPage() {
  const Icons = window.Icons;
  const [q, setQ] = useStateP("");
  const [sel, setSel] = useStateP(null);   // selected conversation
  const [view, setView] = useStateP("all"); // all | asap | warm | nurture (Scout buckets)
  const { data, error, loading, refreshedAt, refresh } = window.useApi("/api/conversations?limit=100", { interval: 10000 });
  const scoutSum = window.useApi("/api/scout/summary", { interval: 20000 });
  const counts = (scoutSum.data && scoutSum.data.counts) || {};
  const convos = ((data && data.conversations) || []).filter((c) =>
    q === "" || (c.name + c.lastMessage + c.phone).toLowerCase().includes(q.toLowerCase())
  );
  const VIEWS = [["all", "All"], ["asap", "🔥 Text ASAP"], ["warm", "Warm"], ["nurture", "Nurture"], ["missed", "💎 Missed"]];

  // Call routed through GHL: open the seller's GHL contact (dialer) so the call goes
  // out on the GHL number — logged + recorded. Falls back to a device tel: dial if the
  // contact/location isn't known.
  const loc = (data && data.locationId) || "";
  const callHref = (contactId, phone) => (loc && contactId)
    ? `https://app.gohighlevel.com/v2/location/${loc}/contacts/detail/${contactId}`
    : `tel:${(phone || "").replace(/[^\d+]/g, "")}`;

  // Open a specific thread when jumped here from Scout chat / dashboard widget.
  useEffectP(() => {
    const pending = window.__forgeOpenConvo;
    if (pending) { setSel(pending); setView("all"); window.__forgeOpenConvo = null; }
  }, []);

  // Keep the selected convo object fresh as the list auto-refreshes.
  const active = sel ? (convos.find((c) => c.id === sel.id) || sel) : null;
  const lead = active && active.contactId
    ? { id: active.contactId, name: active.name, phone: active.phone }
    : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Conversations</h1>
          <p className="faint" style={{ fontSize: 13.5, marginTop: 3 }}>
            {data ? `${(data.total || 0).toLocaleString()} total · ` : ""}<span className="dot online pulse" /> live · refreshed {window.timeAgo(refreshedAt)}
            {scoutSum.data ? <span> · Scout: {counts.asap || 0} to text now</span> : ""}
          </p>
        </div>
        <div className="tabs" style={{ flexWrap: "wrap" }}>
          {VIEWS.map(([k, label]) => (
            <button key={k} className={"tab" + (view === k ? " active" : "")} onClick={() => setView(k)}>
              {label}{k !== "all" && counts[k] != null ? ` ${counts[k]}` : ""}
            </button>
          ))}
        </div>
      </div>

      {error && <window.ErrorRow error={error} onRetry={refresh} />}

      <div className="card" style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex" }}>
        {/* LEFT — conversation list (All) or Scout triage list (ASAP/Warm/Nurture) */}
        <div style={{ width: 320, flexShrink: 0, borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", minHeight: 0 }}>
          {view === "missed" ? (
            <ScoutMissed onPick={(l) => setSel(l)} />
          ) : view !== "all" ? (
            <ScoutLeads bucket={view} activeId={active && active.id} onPick={(l) => setSel(l)} />
          ) : (
          <React.Fragment>
          <div style={{ padding: 12, borderBottom: "1px solid var(--border)" }}>
            <div className="search" style={{ width: "100%" }}>
              <Icons.Search size={16} />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" />
            </div>
          </div>
          <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
            {loading && !data && <window.LoadingRow />}
            {convos.map((c) => {
              const on = active && active.id === c.id;
              return (
                <div key={c.id} onClick={() => setSel(c)} className="row-item"
                  style={{ padding: "11px 13px", borderBottom: "1px solid var(--border)", cursor: "pointer",
                    background: on ? "var(--card-2)" : "transparent", borderLeft: on ? "3px solid var(--blue)" : "3px solid transparent" }}>
                  <div style={{ width: 40, height: 40, borderRadius: "50%", flexShrink: 0, display: "grid", placeItems: "center",
                    background: avaColor(c.contactId || c.name), color: "#fff", fontSize: 13, fontWeight: 700 }}>
                    {initials(c.name)}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                      <span style={{ fontSize: 13.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</span>
                      <span className="faint" style={{ fontSize: 10.5, flexShrink: 0 }}>{window.timeAgo(c.lastMessageDate)}</span>
                    </div>
                    <div className="faint" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 2 }}>
                      {c.lastMessage || "—"}
                    </div>
                  </div>
                  {c.unread > 0 && <span style={{ flexShrink: 0, minWidth: 18, height: 18, padding: "0 5px", borderRadius: 9, background: "var(--blue)", color: "#fff", fontSize: 10.5, fontWeight: 700, display: "grid", placeItems: "center" }}>{c.unread}</span>}
                  {(c.phone || c.contactId) && (
                    <a href={callHref(c.contactId, c.phone)} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} title={`Call ${c.name} on GHL`}
                      style={{ display: "grid", placeItems: "center", width: 28, height: 28, borderRadius: "50%", color: "var(--green)", flexShrink: 0 }}>
                      <Icons.Phone size={15} />
                    </a>
                  )}
                </div>
              );
            })}
            {!loading && convos.length === 0 && (
              <div className="empty" style={{ padding: 30 }}><div className="empty-ico"><Icons.Message size={22} /></div><div style={{ fontWeight: 600, color: "var(--text)", fontSize: 13 }}>No conversations</div></div>
            )}
          </div>
          </React.Fragment>
          )}
        </div>

        {/* RIGHT — thread + composer */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0 }}>
          {active ? (
            <React.Fragment>
              <div style={{ display: "flex", alignItems: "center", gap: 11, padding: "12px 18px", borderBottom: "1px solid var(--border)" }}>
                <div style={{ width: 38, height: 38, borderRadius: "50%", display: "grid", placeItems: "center", background: avaColor(active.contactId || active.name), color: "#fff", fontSize: 13, fontWeight: 700 }}>{initials(active.name)}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 14.5 }}>{active.name}</div>
                  {active.phone && <div className="faint mono" style={{ fontSize: 11.5 }}>{active.phone}</div>}
                </div>
                {(active.phone || active.contactId) && (
                  <a href={callHref(active.contactId, active.phone)} target="_blank" rel="noopener noreferrer" title={`Call ${active.name} on GHL`}
                    style={{ display: "flex", alignItems: "center", gap: 7, padding: "8px 14px", borderRadius: 11, background: "linear-gradient(135deg,#22C55E,#16a34a)", color: "#fff", fontSize: 13, fontWeight: 600, flexShrink: 0, textDecoration: "none" }}>
                    <Icons.Phone size={15} /> Call on GHL
                  </a>
                )}
              </div>
              {lead
                ? <LeadMessages key={lead.id} lead={lead} />
                : <div className="empty" style={{ flex: 1 }}><div className="empty-ico"><Icons.Message size={24} /></div><div style={{ fontWeight: 600, color: "var(--text)" }}>No contact linked</div><div style={{ fontSize: 12 }}>This conversation has no contact record to message.</div></div>}
            </React.Fragment>
          ) : (
            <div className="empty" style={{ flex: 1 }}>
              <div className="empty-ico"><Icons.Conversations size={26} /></div>
              <div style={{ fontWeight: 600, color: "var(--text)" }}>Select a conversation</div>
              <div style={{ fontSize: 12 }}>Pick someone on the left to read the thread and reply.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AI Agents — iMessage-style, but the left rail is your AGENTS, not leads.
// Pick an agent -> chat with it. Marcus answers from live GHL threads; Retell
// agents answer in their configured persona (test their tone in text).
// ---------------------------------------------------------------------------
// When chatting with Scout, show his live "text back now" list as clickable chips —
// tap one to jump straight into that seller's thread (the flow you described).
function ScoutChatStrip() {
  const { data } = window.useApi("/api/scout/leads?bucket=asap", { interval: 15000 });
  const leads = (data && data.leads) || [];
  if (!leads.length) return null;
  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6 }}>
      <div className="faint" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.4 }}>🔥 TEXT BACK NOW — tap to open the thread</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {leads.slice(0, 8).map((l) => (
          <button key={l.id} className="tab" onClick={() => window.openConversation(l)}
            style={{ fontSize: 11, border: "1px solid var(--border)", display: "flex", gap: 6, alignItems: "center" }}>
            {l.name}<span style={{ fontWeight: 800, color: scoreColor(l.motivation) }}>{l.motivation}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function agentHistoryRowsP(rows) {
  return (rows || []).map((m) => ({
    role: m.role === "user" ? "user" : "ai",
    text: m.text || "",
    time: m.ts ? new Date(m.ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "",
    via: m.via,
  }));
}

function AgentThread({ agent }) {
  const Icons = window.Icons;
  const [msgs, setMsgs] = useStateP([]);
  const [draft, setDraft] = useStateP("");
  const [typing, setTyping] = useStateP(false);
  const feedRef = useRefP(null);
  const historyRunP = useRefP(0);
  const mountedP = useRefP(true);
  const now = () => new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const historyPath = "/api/agents/history?agentId=" + encodeURIComponent(agent.id) + "&limit=60";

  async function fetchAgentHistoryP() {
    const res = await fetch(historyPath, { headers: { Accept: "application/json" } });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.error || ("HTTP " + res.status));
    return agentHistoryRowsP(j.history);
  }

  // Each agent keeps its own thread; reset the view when you switch agents.
  useEffectP(() => {
    mountedP.current = true;
    const myRun = ++historyRunP.current;
    setMsgs([]); setDraft("");
    fetchAgentHistoryP().then((rows) => {
      if (!mountedP.current || historyRunP.current !== myRun) return;
      setMsgs((local) => rows.concat(local.filter((m) => m.optimistic)));
    }).catch(() => {});
    return () => { mountedP.current = false; };
  }, [agent.id]);
  useEffectP(() => { if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight; }, [msgs, typing]);

  async function send() {
    const q = draft.trim();
    if (!q || typing) return;
    const history = msgs.slice(-8).map((m) => ({ role: m.role, text: m.text }));
    setMsgs((m) => [...m, { role: "user", text: q, time: now(), optimistic: true }]);
    setDraft(""); setTyping(true);
    let reply;
    let sentOk = false;
    try {
      const res = await fetch("/api/agents/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agentId: agent.id, message: q, history }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.error || ("HTTP " + res.status));
      reply = j.reply;
      sentOk = true;
    } catch (e) {
      reply = "Couldn't reach me just now (" + (e.message || "connection error") + "). Make sure the connector is running.";
    }
    setTyping(false);
    setMsgs((m) => [...m, { role: "ai", text: (reply || "").trim() || "On it.", time: now(), optimistic: true }]);
    if (sentOk && mountedP.current) {
      try {
        const rows = await fetchAgentHistoryP();
        if (mountedP.current) setMsgs(rows);
      } catch (e) { /* optimistic transcript remains visible if the refresh fails */ }
    }
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div ref={feedRef} style={{ flex: 1, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
        {msgs.length === 0 && !typing && (
          <div className="empty" style={{ flex: 1 }}>
            <div className="empty-ico"><Icons.Bot size={24} /></div>
            <div style={{ fontWeight: 600, color: "var(--text)" }}>Chat with {agent.name}</div>
            <div style={{ fontSize: 12 }}>{agent.role}</div>
          </div>
        )}
        {msgs.map((m, i) => {
          const out = m.role === "user";
          return (
            <div key={i} style={{ display: "flex", justifyContent: out ? "flex-end" : "flex-start" }}>
              <div style={{ maxWidth: "82%", padding: "9px 13px", borderRadius: 14, fontSize: 13, lineHeight: 1.45, whiteSpace: "pre-wrap",
                background: out ? "linear-gradient(135deg,#4F7CFF,#3a63e0)" : "var(--card-2)",
                color: out ? "#fff" : "var(--text)",
                border: out ? "none" : "1px solid var(--border)",
                borderBottomRightRadius: out ? 4 : 14, borderBottomLeftRadius: out ? 14 : 4 }}>
                {m.text}
                <div style={{ fontSize: 10, opacity: 0.6, marginTop: 4, textAlign: "right" }}>{m.time}</div>
              </div>
            </div>
          );
        })}
        {typing && (
          <div style={{ display: "flex", justifyContent: "flex-start" }}>
            <div style={{ padding: "10px 14px", borderRadius: 14, background: "var(--card-2)", border: "1px solid var(--border)" }}>
              <span className="typing"><span></span><span></span><span></span></span>
            </div>
          </div>
        )}
      </div>

      {agent.id === "scout" && <ScoutChatStrip />}

      <div style={{ borderTop: "1px solid var(--border)", padding: 14, display: "flex", gap: 9, alignItems: "flex-end" }}>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          rows={1}
          placeholder={`Message ${(agent.name || "").split(" ")[0] || "agent"}…`}
          style={{ flex: 1, resize: "none", maxHeight: 120, background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 12, padding: "11px 13px", fontSize: 13, fontFamily: "inherit", lineHeight: 1.4 }}
        />
        <button onClick={send} disabled={typing || !draft.trim()}
          style={{ display: "grid", placeItems: "center", width: 42, height: 42, flexShrink: 0, borderRadius: 12, background: draft.trim() ? "linear-gradient(135deg,#4F7CFF,#3a63e0)" : "var(--card-2)", color: "#fff", opacity: typing ? 0.6 : 1 }}>
          <Icons.Send size={17} />
        </button>
      </div>
    </div>
  );
}

function AgentsPage() {
  const Icons = window.Icons;
  const [sel, setSel] = useStateP(null);
  const { data, error, loading, refresh } = window.useApi("/api/agents/list", { interval: 30000 });
  const agents = (data && data.agents) || [];
  const active = sel ? (agents.find((a) => a.id === sel.id) || sel) : (agents[0] || null);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>AI Agents</h1>
          <p className="faint" style={{ fontSize: 13.5, marginTop: 3 }}>
            {agents.length} agent{agents.length === 1 ? "" : "s"} · talk to any of them directly
          </p>
        </div>
      </div>

      {error && <window.ErrorRow error={error} onRetry={refresh} />}

      <div className="card" style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex" }}>
        {/* LEFT — agent roster */}
        <div style={{ width: 320, flexShrink: 0, borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", fontSize: 12, fontWeight: 700, letterSpacing: 0.4, color: "var(--text-3)" }}>YOUR AGENTS</div>
          <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
            {loading && !data && <window.LoadingRow />}
            {agents.map((a) => {
              const on = active && active.id === a.id;
              return (
                <div key={a.id} onClick={() => setSel(a)} className="row-item"
                  style={{ padding: "11px 13px", borderBottom: "1px solid var(--border)", cursor: "pointer",
                    background: on ? "var(--card-2)" : "transparent", borderLeft: on ? "3px solid var(--blue)" : "3px solid transparent" }}>
                  <div style={{ width: 40, height: 40, borderRadius: "50%", flexShrink: 0, display: "grid", placeItems: "center",
                    background: avaColor(a.id), color: "#fff" }}>
                    <Icons.Bot size={19} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                      <span style={{ fontSize: 13.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</span>
                      {a.kind === "coordinator"
                        ? <span className="pill" style={{ background: "rgba(34,197,94,0.12)", color: "var(--green)", fontSize: 9.5, flexShrink: 0 }}>LIVE</span>
                        : <span className="pill" style={{ background: "var(--card-2)", fontSize: 9.5, flexShrink: 0 }}>VOICE</span>}
                    </div>
                    <div className="faint" style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 2 }}>{a.role}</div>
                  </div>
                </div>
              );
            })}
            {!loading && agents.length === 0 && (
              <div className="empty" style={{ padding: 30 }}><div className="empty-ico"><Icons.Bot size={22} /></div><div style={{ fontWeight: 600, color: "var(--text)", fontSize: 13 }}>No agents yet</div><div style={{ fontSize: 12 }}>Marcus appears here; add a Retell key for voice agents.</div></div>
            )}
          </div>
        </div>

        {/* RIGHT — chat with the selected agent */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0 }}>
          {active ? (
            <React.Fragment>
              <div style={{ display: "flex", alignItems: "center", gap: 11, padding: "12px 18px", borderBottom: "1px solid var(--border)" }}>
                <div style={{ width: 38, height: 38, borderRadius: "50%", display: "grid", placeItems: "center", background: avaColor(active.id), color: "#fff" }}><Icons.Bot size={18} /></div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14.5 }}>{active.name}</div>
                  <div className="faint" style={{ fontSize: 11.5 }}>{active.role}</div>
                </div>
              </div>
              <AgentThread key={active.id} agent={active} />
            </React.Fragment>
          ) : (
            <div className="empty" style={{ flex: 1 }}>
              <div className="empty-ico"><Icons.Bot size={26} /></div>
              <div style={{ fontWeight: 600, color: "var(--text)" }}>Select an agent</div>
              <div style={{ fontSize: 12 }}>Pick an agent on the left to start chatting.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Deal Calc — ARV + Max Allowable Offer. MAO = ARV*% - repairs - assignment fee.
// Manual for now (comps auto-fill via RentCast is a later add).
// ---------------------------------------------------------------------------
const REPAIR_PRESETS = [
  { label: "Light", amt: 10000, hint: "paint, carpet, fixtures" },
  { label: "Moderate", amt: 25000, hint: "kitchen/bath, flooring" },
  { label: "Heavy", amt: 50000, hint: "roof, HVAC, systems" },
  { label: "Full gut", amt: 90000, hint: "down to studs" },
];

function calcInput(label, value, onChange, opts) {
  opts = opts || {};
  return (
    <div style={{ flex: 1, minWidth: 150 }}>
      <div className="faint" style={{ fontSize: 11.5, marginBottom: 5 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "center", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 10, padding: "0 11px" }}>
        {opts.prefix && <span className="faint" style={{ fontSize: 14 }}>{opts.prefix}</span>}
        <input type="number" value={value} onChange={(e) => onChange(e.target.value)} placeholder={opts.placeholder || "0"}
          style={{ flex: 1, background: "none", border: "none", outline: "none", color: "var(--text)", fontSize: 15, fontWeight: 600, padding: "11px 6px", width: "100%" }} />
        {opts.suffix && <span className="faint" style={{ fontSize: 14 }}>{opts.suffix}</span>}
      </div>
    </div>
  );
}

function DealCalcPage() {
  const Icons = window.Icons;
  const M = window.fmtMoney;
  const [arv, setArv] = useStateP("");
  const [repairs, setRepairs] = useStateP("");
  const [fee, setFee] = useStateP("10000");
  const [pct, setPct] = useStateP("70");
  const [asking, setAsking] = useStateP("");
  const [comps, setComps] = useStateP([]);          // comp sale prices
  const [compDraft, setCompDraft] = useStateP("");
  // Send-offer state
  const [cq, setCq] = useStateP("");                 // contact search query
  const [cres, setCres] = useStateP([]);             // search results
  const [picked, setPicked] = useStateP(null);       // selected homeowner
  const [offer, setOffer] = useStateP("");
  const [offerTouched, setOfferTouched] = useStateP(false);
  const [sending, setSending] = useStateP(false);
  const [sendMsg, setSendMsg] = useStateP(null);
  // Contract (DocuSign) state
  const [showContract, setShowContract] = useStateP(false);
  const [dsCfg, setDsCfg] = useStateP(null);          // /api/contract/config
  const [cfields, setCfields] = useStateP({});        // operator field overrides
  const [csSending, setCsSending] = useStateP(false);
  const [csMsg, setCsMsg] = useStateP(null);
  const [csRetrying, setCsRetrying] = useStateP(false);
  const contractDealPath = picked
    ? `/api/deals/get?contactId=${encodeURIComponent(picked.id)}`
    : "/api/deals/get?contactId=__none__";
  const contractDeal = window.useApi(contractDealPath);
  const pausedContract = contractDeal.data && contractDeal.data.deal &&
    contractDeal.data.deal.contractPollPausedAt ? contractDeal.data.deal : null;

  const n = (v) => { const x = parseFloat(v); return isNaN(x) ? 0 : x; };
  const arvN = n(arv), repN = n(repairs), feeN = n(fee), pctN = n(pct), askN = n(asking);
  const mao = Math.max(0, arvN * (pctN / 100) - repN - feeN);
  const spread = askN > 0 ? mao - askN : null;     // +ve = room, -ve = over

  let verdict = null;
  if (arvN > 0 && askN > 0) {
    if (askN <= mao) verdict = { t: "GO", c: "#22C55E", msg: "Seller's at/under your max. Lock it up." };
    else if (askN <= mao + 15000) verdict = { t: "NEGOTIATE", c: "#F59E0B", msg: `They're ${M(askN - mao)} over. Anchor low, counter near ${M(mao)}.` };
    else verdict = { t: "PASS", c: "#EF4444", msg: `They're ${M(askN - mao)} over max. Don't chase it.` };
  }

  function addComp() {
    const v = n(compDraft);
    if (v <= 0) return;
    const next = comps.concat(v);
    setComps(next); setCompDraft("");
    setArv(String(Math.round(next.reduce((a, b) => a + b, 0) / next.length)));
  }
  function clearComps() { setComps([]); }

  // Search GHL contacts (debounced) for the homeowner to offer.
  React.useEffect(() => {
    if (picked || cq.trim().length < 2) { setCres([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`/api/contacts?query=${encodeURIComponent(cq.trim())}&limit=8`);
        const j = await r.json();
        setCres((j.contacts || []).filter((c) => c.phone));
      } catch (e) { setCres([]); }
    }, 350);
    return () => clearTimeout(t);
  }, [cq, picked]);

  // Auto-draft the offer in Yahjair's voice when a homeowner is picked / MAO changes.
  const firstName = picked ? (picked.name || "").split(" ")[0] : "";
  const addr = picked && picked.addr ? picked.addr : "your property";
  React.useEffect(() => {
    if (!picked || offerTouched) return;
    if (mao <= 0) { setOffer(""); return; }
    setOffer(`hey ${firstName} its yahjair with a touch of blessings home buyers. my cash offer on ${addr} is ${M(mao)} as is i cover all the closing costs and can close in 2 weeks or on your timeline. want me to send the contract over`);
  }, [picked, mao, offerTouched]);

  function pick(c) { setPicked(c); setCq(c.name || ""); setCres([]); setOfferTouched(false); }
  function unpick() { setPicked(null); setCq(""); setOffer(""); setOfferTouched(false); setSendMsg(null); }

  async function sendOffer() {
    if (!picked || !offer.trim() || sending) return;
    if (!window.confirm(`Send this cash offer to ${picked.name} (${picked.phone})?\n\n"${offer.trim()}"`)) return;
    setSending(true); setSendMsg(null);
    try {
      // Persist the deal first so the contract has numbers to prefill + the pipeline tracks it.
      const a = (picked.addr || "").split(",").map((s) => s.trim());
      await window.apiPost("/api/deals/save", {
        contactId: picked.id, name: picked.name, email: picked.email || "",
        property_street: a[0] || picked.addr || "", property_city: a[1] || "",
        arv: arvN, repairs: repN, fee: feeN, pct: pctN, asking: askN, mao: Math.round(mao),
        offer: Math.round(mao), stage: "Offer",
      });
      await window.apiPost("/api/send", { contactId: picked.id, name: picked.name, message: offer.trim() });
      setSendMsg({ ok: true, t: `Offer sent to ${picked.name} — deal saved, pipeline → Offer.` });
    } catch (e) {
      setSendMsg({ ok: false, t: "Send failed: " + (e.message || "error") });
    } finally { setSending(false); }
  }

  // ---- Contract (DocuSign) ----
  React.useEffect(() => {
    if (!showContract || dsCfg) return;
    fetch("/api/contract/config").then((r) => r.json()).then(setDsCfg).catch(() => {});
  }, [showContract]);
  function cval(key, dflt) { const v = cfields[key]; return (v === undefined || v === null) ? (dflt || "") : v; }
  function setCf(key, val) { setCfields((p) => ({ ...p, [key]: val })); }
  function cdefaults() {
    const a = (picked && picked.addr) ? picked.addr : "";
    const parts = a.split(",").map((s) => s.trim());
    return {
      seller_name: picked ? (picked.name || "") : "",
      email: picked ? (picked.email || "") : "",
      property_street: parts[0] || a, property_city: parts[1] || "",
      buyer_name: "A Touch of Blessings Home Buyers LLC", buyer_signer: "Yahjair Mack", buyer_title: "Member",
      purchase_price: mao > 0 ? String(Math.round(mao)) : "", earnest_money: "1000",
    };
  }
  const CFIELDS = ["seller_name", "seller_phone", "email", "buyer_name", "buyer_signer", "buyer_title",
    "property_street", "property_city", "property_zip", "county", "parcel", "purchase_price",
    "earnest_money", "closing_date", "closing_year", "title_company", "title_address", "title_officer", "title_email"];
  async function sendContract() {
    const D = cdefaults(); const f = {};
    CFIELDS.forEach((k) => { f[k] = cval(k, D[k]); });
    if (!f.email) { setCsMsg({ ok: false, t: "Seller email required — DocuSign signs via email." }); return; }
    if (!window.confirm(`Send the Ohio Purchase Agreement to ${f.seller_name} (${f.email}) for e-signature?`)) return;
    setCsSending(true); setCsMsg(null);
    try {
      const r = await window.apiPost("/api/contract/send", { contactId: picked.id, ...f });
      if (r && r.error) setCsMsg({ ok: false, t: r.error });
      else {
        setCsMsg({ ok: true, t: `Sent to ${f.seller_name}. They'll get a DocuSign email to sign.` });
        contractDeal.refresh();
      }
    } catch (e) { setCsMsg({ ok: false, t: "Send failed: " + (e.message || "error") }); }
    finally { setCsSending(false); }
  }
  async function retryContractPoll() {
    if (!picked || csRetrying) return;
    const replacement = window.prompt(
      "Optional replacement DocuSign envelope ID. Leave blank to retry the existing one:",
      pausedContract && pausedContract.contractEnvelopeId || "");
    if (replacement === null) return;
    setCsRetrying(true); setCsMsg(null);
    try {
      await window.apiPost("/api/contract/retry", {
        contactId: picked.id, envelopeId: replacement.trim(),
      });
      await contractDeal.refresh();
      setCsMsg({ ok: true, t: "DocuSign polling resumed. The next check will verify the envelope." });
    } catch (e) {
      setCsMsg({ ok: false, t: "Could not resume polling: " + (e.message || e) });
    } finally { setCsRetrying(false); }
  }
  const cfld = (label, key, opts = {}) => {
    const D = cdefaults();
    return (
      <label style={{ display: "flex", flexDirection: "column", gap: 4, flex: opts.full ? "1 1 100%" : "1 1 160px", minWidth: 120 }}>
        <span className="faint" style={{ fontSize: 11 }}>{label}{opts.req ? " *" : ""}</span>
        <input type={opts.type || "text"} value={cval(key, D[key])} onChange={(e) => setCf(key, e.target.value)}
          placeholder={opts.ph || ""} style={{ background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 9, padding: "9px 11px", fontSize: 13, fontFamily: "inherit" }} />
      </label>
    );
  };

  const box = { background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 13, padding: 16 };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px", display: "flex", alignItems: "center", gap: 10 }}>
          <Icons.DealCalc size={22} /> Deal Calculator
        </h1>
        <p className="faint" style={{ fontSize: 13.5, marginTop: 3 }}>ARV → Max Allowable Offer. MAO = ARV × {pctN || 70}% − repairs − assignment fee.</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1fr)", gap: 16, alignItems: "start" }}>
        {/* LEFT — inputs */}
        <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          {/* Comps -> ARV */}
          <div style={box}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, display: "flex", alignItems: "center", gap: 7 }}><Icons.Properties size={14} /> Comps → ARV</div>
            <div style={{ display: "flex", gap: 8 }}>
              <div style={{ flex: 1, display: "flex", alignItems: "center", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 10, padding: "0 11px" }}>
                <span className="faint" style={{ fontSize: 14 }}>$</span>
                <input type="number" value={compDraft} onChange={(e) => setCompDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addComp()}
                  placeholder="comp sale price" style={{ flex: 1, background: "none", border: "none", outline: "none", color: "var(--text)", fontSize: 14, padding: "10px 6px" }} />
              </div>
              <button className="tab" onClick={addComp} style={{ fontWeight: 600 }}>Add</button>
            </div>
            {comps.length > 0 && (
              <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                {comps.map((c, i) => <span key={i} className="pill" style={{ background: "var(--card)", fontSize: 11.5 }}>{M(c)}</span>)}
                <span className="faint" style={{ fontSize: 11.5, marginLeft: "auto" }}>avg {M(Math.round(comps.reduce((a, b) => a + b, 0) / comps.length))} → ARV</span>
                <button className="link" onClick={clearComps} style={{ fontSize: 11.5 }}>clear</button>
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {calcInput("ARV (after-repair value)", arv, setArv, { prefix: "$" })}
            {calcInput("Assignment fee", fee, setFee, { prefix: "$" })}
          </div>

          {/* Repairs */}
          <div>
            <div className="faint" style={{ fontSize: 11.5, marginBottom: 6 }}>Estimated repairs</div>
            <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 9 }}>
              {REPAIR_PRESETS.map((r) => (
                <button key={r.label} className={"tab" + (n(repairs) === r.amt ? " active" : "")} onClick={() => setRepairs(String(r.amt))}
                  title={r.hint} style={{ fontSize: 12 }}>{r.label} · {M(r.amt)}</button>
              ))}
            </div>
            {calcInput("", repairs, setRepairs, { prefix: "$", placeholder: "custom repair $" })}
          </div>

          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {calcInput("ARV % (formula)", pct, setPct, { suffix: "%" })}
            {calcInput("Seller asking (optional)", asking, setAsking, { prefix: "$" })}
          </div>
        </div>

        {/* RIGHT — result */}
        <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 14, position: "sticky", top: 8 }}>
          <div className="faint" style={{ fontSize: 12, fontWeight: 600, letterSpacing: 0.4 }}>MAX ALLOWABLE OFFER</div>
          <div className="tabnum" style={{ fontSize: 40, fontWeight: 800, lineHeight: 1, color: mao > 0 ? "var(--green)" : "var(--text-3)" }}>{M(mao)}</div>

          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12, display: "flex", flexDirection: "column", gap: 7, fontSize: 13 }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span className="faint">ARV</span><span className="tabnum">{M(arvN)}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span className="faint">× {pctN || 70}%</span><span className="tabnum">{M(arvN * (pctN / 100))}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span className="faint">− repairs</span><span className="tabnum" style={{ color: "var(--red)" }}>−{M(repN)}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span className="faint">− assignment fee</span><span className="tabnum" style={{ color: "var(--red)" }}>−{M(feeN)}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between", borderTop: "1px solid var(--border)", paddingTop: 7, fontWeight: 700 }}><span>Max offer</span><span className="tabnum" style={{ color: "var(--green)" }}>{M(mao)}</span></div>
          </div>

          {spread !== null && (
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, fontWeight: 600 }}>
              <span className="faint">vs asking {M(askN)}</span>
              <span style={{ color: spread >= 0 ? "var(--green)" : "var(--red)" }}>{spread >= 0 ? "+" : ""}{M(spread)}</span>
            </div>
          )}

          {verdict ? (
            <div style={{ borderRadius: 11, padding: "12px 14px", background: verdict.c + "1a", border: "1px solid " + verdict.c + "66" }}>
              <div style={{ fontSize: 16, fontWeight: 800, color: verdict.c }}>{verdict.t}</div>
              <div style={{ fontSize: 12.5, marginTop: 3 }}>{verdict.msg}</div>
            </div>
          ) : (
            <div className="faint" style={{ fontSize: 12 }}>Enter ARV + seller's asking price for a GO / NEGOTIATE / PASS verdict.</div>
          )}

          <div className="faint" style={{ fontSize: 11, lineHeight: 1.5, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            Tip: drop to <b>65%</b> if ARV is sliding or repairs are uncertain. Always estimate repairs high — buyers verify at the table.
          </div>
        </div>
      </div>

      {/* Send the offer straight to the homeowner via GoHighLevel */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <Icons.Send size={16} /> Send offer to homeowner
        </div>

        {!picked ? (
          <div style={{ position: "relative", maxWidth: 460 }}>
            <div className="search" style={{ width: "100%" }}>
              <Icons.Search size={16} />
              <input value={cq} onChange={(e) => setCq(e.target.value)} placeholder="Search a homeowner by name or phone…" />
            </div>
            {cres.length > 0 && (
              <div className="card" style={{ position: "absolute", zIndex: 5, top: "100%", left: 0, right: 0, marginTop: 4, maxHeight: 260, overflowY: "auto" }}>
                {cres.map((c) => (
                  <div key={c.id} onClick={() => pick(c)} className="row-item" style={{ padding: "10px 12px", cursor: "pointer", borderBottom: "1px solid var(--border)" }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 600 }}>{c.name || "(no name)"}</div>
                      <div className="faint mono" style={{ fontSize: 11.5 }}>{c.phone}{c.addr ? " · " + c.addr : ""}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 10, background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 11, padding: "10px 13px", maxWidth: 460 }}>
            <div style={{ width: 34, height: 34, borderRadius: "50%", display: "grid", placeItems: "center", background: avaColor(picked.id), color: "#fff", fontSize: 12, fontWeight: 700 }}>{initials(picked.name)}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>{picked.name}</div>
              <div className="faint mono" style={{ fontSize: 11.5 }}>{picked.phone}{picked.addr ? " · " + picked.addr : ""}</div>
            </div>
            <button className="link" onClick={unpick} style={{ fontSize: 12 }}>change</button>
          </div>
        )}

        {picked && mao <= 0 && <div className="faint" style={{ fontSize: 12.5 }}>Enter an ARV above to generate the offer number.</div>}

        {picked && mao > 0 && (
          <React.Fragment>
            <div>
              <div className="faint" style={{ fontSize: 11.5, marginBottom: 5 }}>Offer message (edit before sending — it's in your voice)</div>
              <textarea value={offer} onChange={(e) => { setOffer(e.target.value); setOfferTouched(true); }} rows={3}
                style={{ width: "100%", resize: "vertical", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 12, padding: "11px 13px", fontSize: 13.5, fontFamily: "inherit", lineHeight: 1.45 }} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <button onClick={sendOffer} disabled={sending || !offer.trim()}
                style={{ display: "flex", alignItems: "center", gap: 8, padding: "11px 18px", borderRadius: 12, fontSize: 14, fontWeight: 700, color: "#fff", background: offer.trim() ? "linear-gradient(135deg,#22C55E,#16a34a)" : "var(--card-2)", opacity: sending ? 0.6 : 1 }}>
                <Icons.Send size={16} /> {sending ? "Sending…" : `Send ${M(mao)} offer`}
              </button>
              {!offerTouched && <button className="tab" onClick={() => setOfferTouched(true)} style={{ fontSize: 12 }}>edit text</button>}
              {sendMsg && <span style={{ fontSize: 13, fontWeight: 600, color: sendMsg.ok ? "var(--green)" : "var(--red)" }}>{sendMsg.ok ? "✓ " : ""}{sendMsg.t}</span>}
            </div>
            <div className="faint" style={{ fontSize: 11 }}>Texts via GoHighLevel from your number. Confirm prompt before it goes out.</div>
          </React.Fragment>
        )}
      </div>

      {/* Fill out + send the full Ohio Purchase Agreement via DocuSign */}
      {picked && (
        <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 11 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ fontSize: 15, fontWeight: 700, flex: 1 }}>📄 Purchase agreement — fill out & send (DocuSign)</div>
            <button className="tab" onClick={() => setShowContract((s) => !s)} style={{ fontWeight: 600 }}>
              {showContract ? "hide" : "prepare contract"}
            </button>
          </div>
          {showContract && (dsCfg && !dsCfg.configured ? (
            <div className="faint" style={{ fontSize: 12.5 }}>DocuSign not connected. Missing: {(dsCfg.missing || []).join(", ")}.</div>
          ) : (
            <React.Fragment>
              {pausedContract && (
                <div className="card-pad" style={{ border: "1px solid var(--orange)", borderRadius: 10, background: "var(--orange)14", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <span style={{ color: "var(--orange)", fontWeight: 700, fontSize: 12.5, flex: 1 }}>
                    DocuSign polling paused for this deal because the envelope could not be accessed.
                  </span>
                  <button className="tab" onClick={retryContractPoll} disabled={csRetrying} style={{ color: "var(--orange)" }}>
                    {csRetrying ? "Resuming…" : "Resume polling"}
                  </button>
                </div>
              )}
              <div className="faint" style={{ fontSize: 11.5 }}>Fills every blank on the Ohio Purchase Agreement. Edit anything; blanks stay blank. Seller signs via email.</div>

              <div className="faint" style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.3, marginTop: 2 }}>PARTIES & PROPERTY</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                {cfld("Seller name", "seller_name", { req: true })}
                {cfld("Seller email", "email", { req: true, type: "email", ph: "needed for e-sign" })}
                {cfld("Seller phone", "seller_phone")}
                {cfld("Property street", "property_street", { full: true })}
                {cfld("City", "property_city")}
                {cfld("Zip", "property_zip")}
                {cfld("County", "county")}
                {cfld("Parcel # (PPN)", "parcel")}
              </div>

              <div className="faint" style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.3, marginTop: 4 }}>MONEY & CLOSING</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                {cfld("Purchase price", "purchase_price", { type: "number" })}
                {cfld("Earnest money", "earnest_money", { type: "number" })}
                {cfld("Closing date", "closing_date", { ph: "e.g. July 15" })}
                {cfld("Closing year (20__)", "closing_year", { ph: "26" })}
              </div>

              <div className="faint" style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.3, marginTop: 4 }}>TITLE / ESCROW</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                {cfld("Title company", "title_company")}
                {cfld("Title address", "title_address", { full: true })}
                {cfld("Closing officer", "title_officer")}
                {cfld("Title email", "title_email", { type: "email" })}
              </div>

              <div className="faint" style={{ fontSize: 11, fontWeight: 700, letterSpacing: 0.3, marginTop: 4 }}>BUYER (you)</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                {cfld("Buyer entity", "buyer_name", { full: true })}
                {cfld("Signed by", "buyer_signer")}
                {cfld("Title", "buyer_title")}
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 6 }}>
                <button onClick={sendContract} disabled={csSending}
                  style={{ display: "flex", alignItems: "center", gap: 8, padding: "11px 18px", borderRadius: 12, fontSize: 14, fontWeight: 700, color: "#fff", background: "linear-gradient(135deg,#4F7CFF,#6366F1)", opacity: csSending ? 0.6 : 1 }}>
                  📄 {csSending ? "Sending…" : "Send contract for signature"}
                </button>
                {csMsg && <span style={{ fontSize: 13, fontWeight: 600, color: csMsg.ok ? "var(--green)" : "var(--red)" }}>{csMsg.ok ? "✓ " : ""}{csMsg.t}</span>}
              </div>
              <div className="faint" style={{ fontSize: 11 }}>One click = the approval. Sends the Ohio PA to the seller's email to e-sign.</div>
            </React.Fragment>
          ))}
        </div>
      )}

      {/* Wholesaler Toolkit — repair estimator, creative finance, dual-view ROI */}
      {window.TkCalcPanels && (
        <window.TkCalcPanels arv={arvN} repairs={repN} fee={feeN} pct={pctN} asking={askN}
          contactId={picked ? picked.id : null}
          onApplyRepairs={(v) => setRepairs(String(v))}
          onApplyArv={(v) => setArv(String(v))} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pipeline — all opportunities by stage, with deal values.
// ---------------------------------------------------------------------------
// Drag a card to another stage -> optimistic move + PUT to GoHighLevel.
// GHL -> dashboard stays in sync via the 30s poll (skipped while a move is in flight).
function PipelinePage() {
  const Icons = window.Icons;
  const { data, error, loading, refresh } = window.useApi("/api/pipeline", { interval: 30000 });
  const [idx, setIdx] = useStateP(0);
  const [local, setLocal] = useStateP(null);     // optimistic copy of pipelines
  const [drag, setDrag] = useStateP(null);       // {id, fromStageId}
  const [overStage, setOverStage] = useStateP(null);
  const [flash, setFlash] = useStateP(null);     // {kind:"ok"|"err", msg}
  const pendingRef = useRefP(0);                  // in-flight move count
  const accents = ["#4F7CFF", "#8B5CF6", "#2DD4BF", "#22C55E", "#F59E0B", "#EC4899", "#64748B", "#EF4444"];

  // Adopt fresh server data, but never clobber an optimistic move mid-flight.
  useEffectP(() => {
    if (data && data.pipelines && pendingRef.current === 0) setLocal(data.pipelines);
  }, [data]);

  // Auto-clear the flash banner.
  useEffectP(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 3200);
    return () => clearTimeout(t);
  }, [flash]);

  const pls = local || (data && data.pipelines) || [];
  const active = pls[idx];

  function applyMove(oppId, toStageId) {
    setLocal((prev) => {
      const base = prev || (data && data.pipelines) || [];
      const next = base.map((p) => ({
        ...p, stages: p.stages.map((s) => ({ ...s, cards: s.cards.slice() })),
      }));
      const p = next[idx];
      if (!p) return prev;
      let moved = null;
      for (const s of p.stages) {
        const i = s.cards.findIndex((c) => c.id === oppId);
        if (i >= 0) { moved = s.cards.splice(i, 1)[0]; break; }
      }
      const dest = p.stages.find((s) => s.id === toStageId);
      if (!moved || !dest) return prev;
      dest.cards.push({ ...moved, stageId: toStageId });
      p.stages.forEach((s) => {
        s.count = s.cards.length;
        s.value = s.cards.reduce((a, c) => a + (c.value || 0), 0);
      });
      p.totalDeals = p.stages.reduce((a, s) => a + s.count, 0);
      p.totalValue = p.stages.reduce((a, s) => a + s.value, 0);
      return next;
    });
  }

  async function onDrop(toStageId) {
    const d = drag;
    setDrag(null); setOverStage(null);
    if (!d || d.fromStageId === toStageId) return;
    const snapshot = local;            // revert target if GHL write fails
    applyMove(d.id, toStageId);
    pendingRef.current += 1;
    try {
      const res = await fetch("/api/pipeline/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: d.id, stageId: toStageId, pipelineId: active && active.id }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok || j.error) throw new Error(j.error || ("HTTP " + res.status));
      setFlash({ kind: "ok", msg: "Moved · synced to GoHighLevel" });
    } catch (e) {
      setLocal(snapshot);              // undo optimistic move
      setFlash({ kind: "err", msg: "Move failed — " + (e.message || "GHL error") + ". Reverted." });
    } finally {
      pendingRef.current -= 1;
      if (pendingRef.current === 0) refresh();   // re-pull truth from GHL
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Pipeline</h1>
          <p className="faint" style={{ fontSize: 13.5, marginTop: 3 }}>
            {active ? `${active.totalDeals} deals · ${window.fmtMoney(active.totalValue)} in ${active.name} · drag a card to move its stage` : "Loading opportunities…"}
          </p>
        </div>
        <div className="tabs">
          {pls.map((p, i) => (
            <button key={p.id} className={"tab" + (i === idx ? " active" : "")} onClick={() => setIdx(i)}>{p.name}</button>
          ))}
        </div>
      </div>

      {flash && (
        <div style={{
          padding: "9px 14px", borderRadius: 10, fontSize: 13, fontWeight: 500,
          border: "1px solid " + (flash.kind === "ok" ? "rgba(34,197,94,0.4)" : "rgba(239,68,68,0.4)"),
          background: flash.kind === "ok" ? "rgba(34,197,94,0.10)" : "rgba(239,68,68,0.10)",
          color: flash.kind === "ok" ? "var(--green)" : "var(--red)",
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <Icons.Check size={14} /> {flash.msg}
        </div>
      )}

      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {loading && !data && <window.LoadingRow />}

      {active && (
        <div className="kanban" style={{ flex: 1, alignItems: "start" }}>
          {active.stages.map((s, i) => (
            <div
              key={s.id}
              className={"kcol" + (overStage === s.id ? " dragover" : "")}
              style={{ "--col-accent": accents[i % accents.length] }}
              onDragOver={(e) => { if (drag) { e.preventDefault(); if (overStage !== s.id) setOverStage(s.id); } }}
              onDragLeave={(e) => { if (overStage === s.id && !e.currentTarget.contains(e.relatedTarget)) setOverStage(null); }}
              onDrop={(e) => { e.preventDefault(); onDrop(s.id); }}
            >
              <div className="kcol-head">
                <span className="kcol-title">{s.name}</span>
                <span className="kcol-count tabnum">{s.count}</span>
              </div>
              {s.value > 0 && <div className="faint" style={{ fontSize: 11, padding: "0 2px 6px", color: "var(--green)" }}>{window.fmtMoney(s.value)}</div>}
              {s.count === 0 && <div className="kempty">{overStage === s.id ? "Drop here" : "—"}</div>}
              {s.cards.map((card) => (
                <div
                  key={card.id}
                  className={"kcard" + (drag && drag.id === card.id ? " dragging" : "")}
                  draggable
                  onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; setDrag({ id: card.id, fromStageId: s.id }); }}
                  onDragEnd={() => { setDrag(null); setOverStage(null); }}
                  style={{ display: "flex", flexDirection: "column", gap: 6, cursor: "grab" }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <div style={{ fontWeight: 600, fontSize: 13, lineHeight: 1.25, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{card.name}</div>
                    {card.value > 0 && <span className="tabnum" style={{ fontSize: 12.5, fontWeight: 700, color: "var(--green)", flexShrink: 0 }}>{window.fmtMoney(card.value)}</span>}
                  </div>
                  {card.phone && <div className="faint mono" style={{ fontSize: 11 }}>{card.phone}</div>}
                  {(card.tags || []).length > 0 && <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>{card.tags.slice(0, 2).map((t) => <span key={t} className="pill" style={{ background: "var(--card-2)", fontSize: 10 }}>{t}</span>)}</div>}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Daily Non-Negotiables — fixed activity targets, reset every day, tracked
// until the first deal closes. Server-persisted (survives restart + midnight reset).
// ---------------------------------------------------------------------------
const GOAL_META = {
  messages:      { label: "Messages sent",       icon: "Message", step: 10, color: "#4F7CFF" },
  conversations: { label: "Conversations",       icon: "Conversations", step: 1, color: "#8B5CF6" },
  calls:         { label: "Calls",               icon: "PhoneCall", step: 5, color: "#2DD4BF" },
  offers:        { label: "Offers made",         icon: "Send", step: 1, color: "#F59E0B" },
};

function DailyNonNegotiables() {
  const Icons = window.Icons;
  const [g, setG] = useStateP(null);
  const [editing, setEditing] = useStateP(false);
  const [busy, setBusy] = useStateP(false);

  async function load() {
    try { const r = await fetch("/api/goals/today"); setG(await r.json()); } catch (e) {}
  }
  React.useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, []);

  async function post(body) {
    setBusy(true);
    try {
      const r = await fetch("/api/goals/update", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      setG(await r.json());
    } catch (e) {} finally { setBusy(false); }
  }
  const bump = (metric, delta) => post({ metric, delta });
  const setVal = (metric, value) => post({ metric, value });

  if (!g) return <div className="card card-pad"><window.LoadingRow label="Loading today's non-negotiables…" /></div>;

  if (g.dealClosed) {
    return (
      <div className="card card-pad" style={{ textAlign: "center", border: "1px solid rgba(34,197,94,0.4)", background: "rgba(34,197,94,0.06)" }}>
        <div style={{ fontSize: 30 }}>🏆</div>
        <div style={{ fontSize: 18, fontWeight: 700, marginTop: 6 }}>First deal closed!</div>
        <div className="faint" style={{ fontSize: 13, marginTop: 4 }}>
          Took {g.dayNumber} days · {g.completedDays} non-negotiable days hit. Onto the next.
        </div>
        <button className="tab" style={{ marginTop: 14 }} onClick={() => post({ dealClosed: false })}>Start a new grind</button>
      </div>
    );
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
            <Icons.Target size={17} /> Daily Non-Negotiables
          </div>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 3 }}>
            Day {g.dayNumber} chasing your first deal · {g.metricsDone}/{g.metricsTotal} hit today
            {g.streak > 0 && <span style={{ color: "var(--green)", fontWeight: 600 }}> · 🔥 {g.streak}-day streak</span>}
            <div style={{ marginTop: 3, fontSize: 11, opacity: 0.8, display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ color: "var(--green)" }}>⚡</span> messages · conversations · calls auto-sync from GoHighLevel · offers auto-tagged by Scout
            </div>
          </div>
        </div>
        <button className="tab" onClick={() => setEditing((e) => !e)} style={{ fontSize: 11.5 }}>{editing ? "Done" : "Edit targets"}</button>
      </div>

      {g.dayComplete && (
        <div style={{ padding: "9px 13px", borderRadius: 10, background: "rgba(34,197,94,0.10)", border: "1px solid rgba(34,197,94,0.4)", color: "var(--green)", fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
          <Icons.Check size={14} /> All non-negotiables hit today. That's how deals get done. Keep going.
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 12 }}>
        {g.metrics.map((m) => {
          const meta = GOAL_META[m] || { label: m, icon: "Spark", step: 1, color: "#4F7CFF" };
          const pm = g.perMetric[m] || { progress: 0, target: 0, pct: 0, complete: false };
          const Ico = Icons[meta.icon] || Icons.Spark;
          return (
            <div key={m} style={{ border: "1px solid " + (pm.complete ? "rgba(34,197,94,0.45)" : "var(--border)"), borderRadius: 13, padding: 13, background: pm.complete ? "rgba(34,197,94,0.06)" : "var(--card-2)" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 600 }}>
                  <span style={{ color: meta.color }}><Ico size={14} /></span> {meta.label}
                </div>
                <div className={"checkbox" + (pm.complete ? " done" : "")} style={{ flexShrink: 0 }}>{pm.complete && <Icons.Check size={12} />}</div>
              </div>

              {editing ? (
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10 }}>
                  <span className="faint" style={{ fontSize: 11.5 }}>Target</span>
                  <input type="number" defaultValue={pm.target} min={0}
                    onBlur={(e) => post({ targets: { [m]: e.target.value } })}
                    style={{ width: 70, background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 8, padding: "5px 8px", fontSize: 13 }} />
                </div>
              ) : (
                <React.Fragment>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 5, marginTop: 8 }}>
                    <span className="tabnum" style={{ fontSize: 24, fontWeight: 800 }}>{pm.progress}</span>
                    <span className="faint" style={{ fontSize: 13 }}>/ {pm.target}</span>
                  </div>
                  <div style={{ height: 6, borderRadius: 4, background: "var(--border)", marginTop: 8, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: pm.pct + "%", background: pm.complete ? "var(--green)" : meta.color, transition: "width .25s" }} />
                  </div>
                  <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
                    <button className="tab" disabled={busy} onClick={() => bump(m, -meta.step)} style={{ flex: "0 0 auto", fontSize: 13, padding: "5px 10px" }}>−{meta.step}</button>
                    <button className="tab" disabled={busy} onClick={() => bump(m, meta.step)} style={{ flex: 1, fontSize: 13, fontWeight: 600, padding: "5px 10px", borderColor: meta.color, color: meta.color }}>+{meta.step}</button>
                    {!pm.complete && <button className="tab" disabled={busy} onClick={() => setVal(m, pm.target)} style={{ flex: "0 0 auto", fontSize: 11.5, padding: "5px 9px" }}>Hit it ✓</button>}
                  </div>
                </React.Fragment>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", borderTop: "1px solid var(--border)", paddingTop: 12 }}>
        <span className="faint" style={{ fontSize: 11.5 }}>Resets at midnight · started {g.startDate || "today"}</span>
        <button className="nba" style={{ width: "auto", padding: "8px 14px" }} onClick={() => { if (window.confirm("Mark your FIRST DEAL as closed? 🎉")) post({ dealClosed: true }); }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>🏁 I closed a deal</span>
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Goals & Deals helpers (Gd-prefixed, unique top-level names).
// ---------------------------------------------------------------------------
function GdSectionTitle({ icon, color, title, sub }) {
  const Icons = window.Icons;
  const Ico = Icons[icon] || Icons.Spark;
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
      <div>
        <div className="card-title" style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: color || "var(--text)" }}><Ico size={16} /></span> {title}
        </div>
        {sub != null && <div className="faint" style={{ fontSize: 12, marginTop: 3 }}>{sub}</div>}
      </div>
    </div>
  );
}

function GdProgressBar({ pct, color }) {
  const w = Math.max(0, Math.min(100, pct || 0));
  return (
    <div style={{ height: 7, borderRadius: 4, background: "var(--border)", overflow: "hidden" }}>
      <div style={{ height: "100%", width: w + "%", background: color || "var(--green)", transition: "width .25s" }} />
    </div>
  );
}

function GdStatTile({ icon, color, label, value, sub }) {
  const Icons = window.Icons;
  const Ico = Icons[icon] || Icons.Spark;
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 13, padding: 14, background: "var(--card-2)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11.5, fontWeight: 600 }} className="faint">
        <span style={{ color: color || "var(--blue)" }}><Ico size={13} /></span> {label}
      </div>
      <div className="tabnum" style={{ fontSize: 26, fontWeight: 800, marginTop: 7, color: "var(--text)" }}>{value}</div>
      {sub != null && <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tasks — Goals & Deals command center. GHL stats (auto-refresh) + editable
// dashboard-owned monthly goals.
// ---------------------------------------------------------------------------
function TasksPage() {
  const Icons = window.Icons;
  const [filter, setFilter] = useStateP("Open");
  const { data, error, loading, refresh } = window.useApi("/api/tasks?scan=60");
  const { data: stats } = window.useApi("/api/deals/stats", { interval: 60000 });
  const [goals, setGoals] = useStateP(null);
  const [goalsErr, setGoalsErr] = useStateP(null);
  const [newGoal, setNewGoal] = useStateP("");
  const [busy, setBusy] = useStateP(false);

  async function loadGoals() {
    try { const r = await fetch("/api/goals/monthly"); setGoals(await r.json()); setGoalsErr(null); }
    catch (e) { setGoalsErr(e.message || String(e)); }
  }
  useEffectP(() => { loadGoals(); }, []);

  async function goalPost(body, optimistic) {
    if (optimistic) setGoals(optimistic);
    setBusy(true);
    try {
      const r = await window.apiPost("/api/goals/monthly/update", body);
      setGoals(r);
    } catch (e) {
      window.alert("Couldn't save goal: " + (e.message || e));
      loadGoals();
    } finally { setBusy(false); }
  }
  function toggleGoal(gid) {
    const opt = goals ? { ...goals, goals: goals.goals.map((x) => x.id === gid ? { ...x, done: !x.done } : x) } : null;
    goalPost({ op: "toggle", gid }, opt);
  }
  function removeGoal(gid) {
    const opt = goals ? { ...goals, goals: goals.goals.filter((x) => x.id !== gid) } : null;
    goalPost({ op: "remove", gid }, opt);
  }
  function editGoal(gid, text) {
    const t = (text || "").trim();
    if (!t) return;
    const opt = goals ? { ...goals, goals: goals.goals.map((x) => x.id === gid ? { ...x, text: t } : x) } : null;
    goalPost({ op: "edit", gid, text: t }, opt);
  }
  function addGoal() {
    const t = newGoal.trim();
    if (!t) return;
    setNewGoal("");
    goalPost({ op: "add", text: t });
  }

  const today = new Date().toISOString().slice(0, 10);
  const monthPrefix = today.slice(0, 7);
  const all = (data && data.tasks) || [];
  const counts = {
    Open: all.filter((t) => !t.completed).length,
    Today: all.filter((t) => !t.completed && (t.dueDate || "").startsWith(today)).length,
    Completed: all.filter((t) => t.completed).length,
    All: all.length,
  };
  const rows = all.filter((t) =>
    filter === "All" ? true :
    filter === "Open" ? !t.completed :
    filter === "Today" ? (!t.completed && (t.dueDate || "").startsWith(today)) :
    t.completed
  );
  const isOverdue = (t) => t.dueDate && t.dueDate.slice(0, 10) < today && !t.completed;

  const monthTasks = all.filter((t) => (t.dueDate || "").slice(0, 7) === monthPrefix);
  const lt = (stats && stats.lifetime) || { dealsClosed: 0, totalEarned: 0, avgFee: 0, jvDeals: 0, fellThrough: 0 };
  const mo = (stats && stats.month) || { dealsClosed: 0, earned: 0, fellThrough: 0 };
  const fellList = (stats && stats.fellThroughList) || [];
  const g = goals || { goals: [] };
  const gList = g.goals || [];
  const gDone = gList.filter((x) => x.done).length;
  const gTotal = gList.length;
  const gPct = gTotal ? Math.round((gDone / gTotal) * 100) : 0;
  const money = (n) => "$" + (Number(n) || 0).toLocaleString();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Tasks</h1>
          <p className="faint" style={{ fontSize: 13.5, marginTop: 3 }}>
            {data ? `${counts.Open} open · ${counts.Today} due today · scanned ${data.scanned} contacts` : "Loading tasks from GoHighLevel…"}
          </p>
        </div>
        <div className="tabs">
          {["Open", "Today", "Completed", "All"].map((f) => (
            <button key={f} className={"tab" + (filter === f ? " active" : "")} onClick={() => setFilter(f)}>{f} {counts[f] ? `(${counts[f]})` : ""}</button>
          ))}
        </div>
      </div>

      <DailyNonNegotiables />

      {/* This Month — GHL tasks due this month + deal snapshot */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 13 }}>
        <GdSectionTitle icon="Calendar" color="var(--blue)" title="This Month"
          sub={<span><strong style={{ color: "var(--green)" }}>{mo.dealsClosed || 0}</strong> closed this month · <strong style={{ color: "var(--green)" }}>{money(mo.earned)}</strong> earned</span>} />
        {monthTasks.length === 0 ? (
          <div className="faint" style={{ fontSize: 12.5 }}>No tasks due this month.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {monthTasks.map((t) => (
              <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", border: "1px solid var(--border)", borderRadius: 10, background: "var(--card-2)" }}>
                <div className={"checkbox" + (t.completed ? " done" : "")} style={{ flexShrink: 0 }}>{t.completed && <Icons.Check size={12} />}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, textDecoration: t.completed ? "line-through" : "none", opacity: t.completed ? 0.6 : 1 }}>{t.title}</div>
                  <div className="faint" style={{ fontSize: 11 }}><Icons.Leads size={10} /> {t.contactName}</div>
                </div>
                <div style={{ fontSize: 12, fontWeight: 600, flexShrink: 0, color: isOverdue(t) ? "var(--red)" : "var(--text-2)" }}>
                  {t.dueDate ? new Date(t.dueDate).toLocaleDateString() : ""}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Monthly Goals — editable, dashboard-owned */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 13 }}>
        <GdSectionTitle icon="Target" color="var(--orange)" title="Monthly Goals"
          sub={gTotal ? `${gDone}/${gTotal} done · resets monthly, unchecked` : "Set the goals that move you toward your first deal."} />
        {gTotal > 0 && <GdProgressBar pct={gPct} color={gPct >= 100 ? "var(--green)" : "var(--orange)"} />}
        {goalsErr && <div className="faint mono" style={{ fontSize: 11.5, color: "var(--red)" }}>{goalsErr}</div>}

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {gList.map((x) => (
            <div key={x.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", border: "1px solid " + (x.done ? "rgba(34,197,94,0.45)" : "var(--border)"), borderRadius: 10, background: x.done ? "rgba(34,197,94,0.06)" : "var(--card-2)" }}>
              <button onClick={() => toggleGoal(x.id)} disabled={busy} title="Toggle" style={{ background: "none", border: "none", padding: 0, cursor: "pointer", flexShrink: 0 }}>
                <div className={"checkbox" + (x.done ? " done" : "")}>{x.done && <Icons.Check size={12} />}</div>
              </button>
              <input defaultValue={x.text} key={x.id + ":" + x.text}
                onBlur={(e) => { if (e.target.value.trim() && e.target.value.trim() !== x.text) editGoal(x.id, e.target.value); }}
                onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); }}
                style={{ flex: 1, minWidth: 0, background: "transparent", color: "var(--text)", border: "none", outline: "none", fontSize: 13, fontWeight: 600, textDecoration: x.done ? "line-through" : "none", opacity: x.done ? 0.65 : 1 }} />
              <button onClick={() => removeGoal(x.id)} disabled={busy} title="Remove" className="faint" style={{ background: "none", border: "none", cursor: "pointer", fontSize: 15, lineHeight: 1, flexShrink: 0, padding: "0 2px" }}>✕</button>
            </div>
          ))}
          {gTotal === 0 && !goalsErr && (
            <div className="faint" style={{ fontSize: 12.5 }}>No goals yet — add your first one below.</div>
          )}
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 2 }}>
          <input value={newGoal} placeholder="Add a monthly goal…"
            onChange={(e) => setNewGoal(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") addGoal(); }}
            style={{ flex: 1, background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 9, padding: "8px 11px", fontSize: 13 }} />
          <button className="tab" disabled={busy || !newGoal.trim()} onClick={addGoal} style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 600, borderColor: "var(--orange)", color: "var(--orange)" }}>
            <Icons.Plus size={13} /> Add
          </button>
        </div>
      </div>

      {/* Lifetime Stats */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 13 }}>
        <GdSectionTitle icon="Trend" color="var(--green)" title="Lifetime Stats"
          sub={lt.dealsClosed > 0 ? "Every closed deal, all time" : null} />
        {lt.dealsClosed === 0 ? (
          <div className="empty" style={{ padding: 30 }}>
            <div className="empty-ico"><Icons.Target size={26} /></div>
            <div style={{ fontWeight: 600, color: "var(--text)" }}>No deals closed yet — your first one lands here 🎯</div>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 12 }}>
            <GdStatTile icon="Check" color="var(--green)" label="Deals Closed" value={lt.dealsClosed} />
            <GdStatTile icon="Dollar" color="var(--green)" label="Total Earned" value={money(lt.totalEarned)} />
            <GdStatTile icon="Agents" color="var(--blue)" label="JV Deals Done" value={lt.jvDeals || 0} />
            <GdStatTile icon="Dollar" color="var(--orange)" label="Avg Fee" value={money(lt.avgFee)} />
          </div>
        )}
      </div>

      {/* Deals That Fell Through */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 13 }}>
        <GdSectionTitle icon="Flame" color="var(--red)" title="Deals That Fell Through"
          sub={fellList.length ? `${fellList.length} lost or abandoned` : null} />
        {fellList.length === 0 ? (
          <div className="faint" style={{ fontSize: 12.5 }}>None — nothing slipped through. Keep it that way.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {fellList.map((d) => (
              <div key={d.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 12px", border: "1px solid var(--border)", borderRadius: 10, background: "var(--card-2)" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{d.name || "Unnamed"}</div>
                  <div className="faint" style={{ fontSize: 11 }}>{d.stage || d.status || "—"} · {window.timeAgo(d.updated)}</div>
                </div>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--red)", flexShrink: 0 }}>{money(d.value)}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {error && <window.ErrorRow error={error} onRetry={refresh} />}

      {/* Existing GHL task list (filter tabs above drive it) */}
      <div className="card" style={{ overflow: "hidden" }}>
        {loading && !data && <window.LoadingRow label="Scanning contacts for tasks…" />}
        {rows.map((t) => (
          <div className="row-item" key={t.id} style={{ padding: "13px 16px", borderBottom: "1px solid var(--border)" }}>
            <div className={"checkbox" + (t.completed ? " done" : "")} style={{ flexShrink: 0 }}>{t.completed && <Icons.Check size={13} />}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13.5, fontWeight: 600, textDecoration: t.completed ? "line-through" : "none", opacity: t.completed ? 0.6 : 1 }}>{t.title}</div>
              <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>
                <Icons.Leads size={11} /> {t.contactName}{t.body ? " · " + t.body.slice(0, 60) : ""}
              </div>
            </div>
            <div style={{ textAlign: "right", flexShrink: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: isOverdue(t) ? "var(--red)" : "var(--text-2)" }}>
                {t.dueDate ? new Date(t.dueDate).toLocaleDateString() : "No due date"}
              </div>
              {isOverdue(t) && <div style={{ fontSize: 10, color: "var(--red)", fontWeight: 600 }}>OVERDUE</div>}
            </div>
          </div>
        ))}
        {!loading && rows.length === 0 && (
          <div className="empty" style={{ padding: 40 }}><div className="empty-ico"><Icons.Clipboard size={26} /></div><div style={{ fontWeight: 600, color: "var(--text)" }}>No {filter.toLowerCase()} tasks</div></div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Outbound — live AI-voice agency console (Retell). Tag a contact -> the agent
// calls them, qualifies, books, and the outcome lands here as a call breakdown.
// Everything is driven by live Retell data; no placeholders.
//   trigger  = GHL contact tag (e.g. "ai-call")  [tag->call wiring is the next build]
//   engine   = Retell voice agent (editable from the Agent Editor below)
//   callback = call result -> note/tag/opportunity in GHL  [next build]
// ---------------------------------------------------------------------------
// Fields the agent pulls from each call — the "main things we need to know".
const CALL_FIELDS = [
  ["Motivation", "motivation"], ["Timeline", "timeline"], ["Asking Price", "price"],
  ["Condition", "condition"], ["Mortgage Owed", "owed"], ["Occupancy", "occupancy"],
];

const OUTCOME_COLOR = {
  positive: "var(--green)", neutral: "var(--orange)",
  negative: "var(--text-3)", inprogress: "var(--blue)",
};

function OutboundCallCard({ c }) {
  const oc = OUTCOME_COLOR[c.outcomeKind] || "var(--text-2)";
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="empty-ico" style={{ width: 40, height: 40, margin: 0 }}><window.Icons.PhoneCall size={18} /></div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 14.5 }}>{c.name}</div>
            <div className="faint" style={{ fontSize: 11.5, marginTop: 1 }}>{c.phone} · {c.market} · {c.dur}</div>
          </div>
        </div>
        <span className="pill" style={{ background: "var(--card-2)", color: oc, border: "1px solid var(--border)", fontSize: 11 }}>
          <span className="dot" style={{ background: oc }} /> {c.outcome}
        </span>
      </div>

      <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--text-2)", background: "var(--card-2)", borderRadius: 8, padding: "9px 11px" }}>
        <span style={{ color: "var(--blue-soft)", fontWeight: 700, fontSize: 10.5, letterSpacing: ".4px" }}>AI SUMMARY  </span>
        {c.summary}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
        {CALL_FIELDS.map(([label, key]) => (
          <div key={key}>
            <div className="faint" style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".4px", textTransform: "uppercase" }}>{label}</div>
            <div style={{ fontSize: 12.5, marginTop: 2, color: c[key] === "—" ? "var(--text-3)" : "var(--text)" }}>{c[key]}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

const RETELL_MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "claude-3.7-sonnet", "claude-3.5-haiku"];
const RETELL_LANGS = [["en-US", "English (US)"], ["en-GB", "English (UK)"], ["es-ES", "Spanish (Spain)"], ["es-419", "Spanish (LatAm)"]];

function fieldLabel(t) {
  return <div className="faint" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: ".4px", textTransform: "uppercase", marginBottom: 4 }}>{t}</div>;
}
const inputStyle = { width: "100%", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 9, padding: "9px 11px", fontSize: 13, fontFamily: "inherit", lineHeight: 1.45, boxSizing: "border-box" };

// Edit the live Retell agent — tone, questions, opener, voice — straight from here.
function OutboundAgentEditor() {
  const Icons = window.Icons;
  const ag = window.useApi("/api/outbound/agent", { interval: 0 });
  const vs = window.useApi("/api/outbound/voices", { interval: 0 });
  const [form, setForm] = useStateP(null);
  const [saving, setSaving] = useStateP(false);
  const [creating, setCreating] = useStateP(false);
  const [msg, setMsg] = useStateP(null);
  const a = ag.data || {};
  const voices = (vs.data && vs.data.voices) || [];

  React.useEffect(() => {
    if (a.found && (!form || form.agentId !== a.agentId)) setForm({ ...a });
  }, [a.agentId, a.found]);

  const up = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    if (!window.confirm("Save these changes to the live Retell agent? This updates how it talks on calls.")) return;
    setSaving(true); setMsg(null);
    try {
      const r = await window.apiPost("/api/outbound/agent/update", form);
      setMsg(r.ok ? (r.published ? "Saved + published live." : "Saved (draft).") : `Failed: ${r.error || "?"}`);
      ag.refresh();
    } catch (e) { setMsg(`Failed: ${e.message}`); }
    setSaving(false);
  }
  async function create() {
    if (!window.confirm("Create the outbound agent in Retell now? You can edit everything after.")) return;
    setCreating(true); setMsg(null);
    try {
      const r = await window.apiPost("/api/outbound/agent/create", {});
      setMsg(r.ok ? "Agent created — editing below." : `Failed: ${r.error || "?"}`);
      ag.refresh();
    } catch (e) { setMsg(`Failed: ${e.message}`); }
    setCreating(false);
  }

  if (ag.data && ag.data.hasKey === false) return null;   // page banner already covers no-key

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <div className="card-title" style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}><Icons.Sliders size={15} /> Agent Editor</div>
        {a.found && a.editable && (
          <button className="tab" onClick={save} disabled={saving} style={{ border: "1px solid var(--blue)", color: "var(--blue-soft)", fontWeight: 600 }}>
            {saving ? "Saving…" : "Save + publish"}
          </button>
        )}
      </div>
      {msg && <div style={{ fontSize: 12, color: msg.startsWith("Saved") || msg.startsWith("Agent") ? "var(--green)" : "var(--red)" }}>{msg}</div>}

      {ag.loading && !ag.data && <window.LoadingRow label="Loading agent…" />}

      {ag.data && a.hasKey && !a.found && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "flex-start" }}>
          <div className="faint" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
            No outbound agent yet. Create a ready-to-tune one (seeded with your learned texting voice), then edit its tone + questions right here.
          </div>
          <button className="tab" onClick={create} disabled={creating} style={{ border: "1px solid var(--blue)", color: "var(--blue-soft)", fontWeight: 600 }}>
            {creating ? "Creating…" : "Create the outbound agent"}
          </button>
        </div>
      )}

      {a.found && !a.editable && (
        <div className="faint" style={{ fontSize: 12.5 }}>
          This agent uses a Conversation Flow ({a.engine}). Inline editing supports prompt-based agents — edit this one in the Retell console for now.
        </div>
      )}

      {a.found && a.editable && form && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
            <div>
              {fieldLabel("Agent name")}
              <input style={inputStyle} value={form.agentName || ""} onChange={(e) => up("agentName", e.target.value)} />
            </div>
            <div>
              {fieldLabel("Voice")}
              <select style={inputStyle} value={form.voiceId || ""} onChange={(e) => up("voiceId", e.target.value)}>
                {!voices.find((v) => v.id === form.voiceId) && form.voiceId && <option value={form.voiceId}>{form.voiceId}</option>}
                {voices.map((v) => <option key={v.id} value={v.id}>{v.name}{v.gender ? ` · ${v.gender}` : ""}{v.accent ? ` · ${v.accent}` : ""}</option>)}
              </select>
            </div>
            <div>
              {fieldLabel("Model")}
              <select style={inputStyle} value={form.model || ""} onChange={(e) => up("model", e.target.value)}>
                {form.model && !RETELL_MODELS.includes(form.model) && <option value={form.model}>{form.model}</option>}
                {RETELL_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 12 }}>
            <div>
              {fieldLabel("Language")}
              <select style={inputStyle} value={form.language || "en-US"} onChange={(e) => up("language", e.target.value)}>
                {RETELL_LANGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              {fieldLabel("Opening line (first thing it says)")}
              <input style={inputStyle} value={form.beginMessage || ""} onChange={(e) => up("beginMessage", e.target.value)} />
            </div>
          </div>

          <div>
            {fieldLabel("Tone + questions (the agent's brain — edit freely)")}
            <textarea style={{ ...inputStyle, minHeight: 260, resize: "vertical", fontFamily: "ui-monospace, monospace", fontSize: 12.5 }}
              value={form.generalPrompt || ""} onChange={(e) => up("generalPrompt", e.target.value)} />
            <div className="faint" style={{ fontSize: 11, marginTop: 5 }}>
              Change the tone, add/remove questions, set the goal — plain English. Hit <b>Save + publish</b> and the next call uses it.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function OutboundPage() {
  const Icons = window.Icons;
  const st = window.useApi("/api/outbound/status", { interval: 30000 });
  const cl = window.useApi("/api/outbound/calls?limit=24", { interval: 30000 });

  const status = st.data || {};
  const live = !!status.hasKey;                        // Retell key present in connector
  const calls = (cl.data && cl.data.calls) || [];
  const agents = (status.agents || []).map((a) => ({
    name: a.name, role: a.language ? `Voice agent · ${a.language}` : "Voice agent",
    desc: a.voice ? `Voice: ${a.voice}` : "", id: a.id,
  }));

  // KPIs from live calls only.
  const connected = calls.filter((c) => c.outcomeKind !== "inprogress").length;
  const positive = calls.filter((c) => c.outcomeKind === "positive").length;
  const kpis = [
    { label: "Calls", value: calls.length, ico: "PhoneCall", color: "var(--blue)" },
    { label: "Connected", value: connected, ico: "Phone", color: "var(--violet)" },
    { label: "Positive", value: positive, ico: "Check", color: "var(--green)" },
    { label: "Concurrency", value: status.concurrency ? (status.concurrency.current_concurrency ?? "—") + "/" + (status.concurrency.concurrency_limit ?? "—") : "—", ico: "Activity", color: "var(--orange)" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px", display: "flex", alignItems: "center", gap: 10 }}>
            <Icons.PhoneCall size={22} /> Outbound
          </h1>
          <p className="faint" style={{ fontSize: 13.5, marginTop: 3 }}>AI voice agents that call your sellers — every call broken down for you</p>
        </div>
        {live ? (
          <span className="pill" style={{ background: "rgba(34,197,94,0.12)", color: "var(--green)", border: "1px solid rgba(34,197,94,0.3)" }}>
            <span className="dot" style={{ background: "var(--green)" }} /> RETELL CONNECTED
          </span>
        ) : (
          <span className="pill" style={{ background: "rgba(245,158,11,0.12)", color: "var(--orange)", border: "1px solid rgba(245,158,11,0.3)" }}>
            <span className="dot" style={{ background: "var(--orange)" }} /> RETELL NOT CONNECTED
          </span>
        )}
      </div>

      {/* Connection banner when key missing */}
      {!live && (
        <div className="card card-pad" style={{ borderLeft: "3px solid var(--orange)", fontSize: 12.5, lineHeight: 1.55, color: "var(--text-2)" }}>
          <b style={{ color: "var(--text)" }}>Plug in Retell to go live.</b>{" "}
          Add <code style={{ color: "var(--blue-soft)" }}>RETELL_API_KEY=...</code> to{" "}
          <code>marcus-wholesale-agent/config/ghl.env</code> and restart the connector. Agents, phone numbers,
          and call breakdowns light up here, and you can build + edit the agent from the editor below.
        </div>
      )}

      {/* The outbound agent(s) */}
      {live && (
        <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="card-title" style={{ margin: 0 }}>Outbound Agents {agents.length ? `(${agents.length})` : ""}</div>
          {agents.length === 0 && (
            <div className="faint" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
              No agent yet — build one in the Agent Editor below, then it shows here.
            </div>
          )}
          {agents.map((a) => (
            <div key={a.id || a.name} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div className="empty-ico" style={{ width: 48, height: 48, margin: 0 }}><Icons.Bot size={22} /></div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 15 }}>{a.name}</div>
                  <div className="faint" style={{ fontSize: 12 }}>{a.role}</div>
                  {a.desc ? <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>{a.desc}</div> : null}
                </div>
              </div>
              <span className="pill" style={{ background: "rgba(34,197,94,0.12)", color: "var(--green)", border: "1px solid rgba(34,197,94,0.3)", fontSize: 11 }}>
                <span className="dot" style={{ background: "var(--green)" }} /> LIVE
              </span>
            </div>
          ))}
          {(status.phoneNumbers && status.phoneNumbers.length) ? (
            <div className="faint" style={{ fontSize: 11.5, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
              Outbound numbers: {status.phoneNumbers.map((n) => n.number).join("  ·  ")}
            </div>
          ) : null}
        </div>
      )}

      {/* Live agent editor — build/edit tone, questions, opener, voice */}
      {live && <OutboundAgentEditor />}

      {/* KPI strip */}
      {live && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          {kpis.map((k) => {
            const Ico = Icons[k.ico] || Icons.Activity;
            return (
              <div key={k.label} className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{ color: k.color }}><Ico size={20} /></span>
                <div>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{k.value}</div>
                  <div className="faint" style={{ fontSize: 11.5 }}>{k.label}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Per-call breakdowns */}
      {live && (
        <React.Fragment>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <div className="card-title" style={{ margin: 0 }}>Call Breakdowns</div>
            {calls.length > 0 && <span className="faint" style={{ fontSize: 11.5 }}>{calls.length} live calls from Retell</span>}
          </div>
          {cl.error ? <window.ErrorRow error={cl.error} onRetry={cl.refresh} /> : null}
          {calls.length === 0 && !cl.error ? (
            <div className="card empty" style={{ minHeight: "24vh" }}>
              <div className="empty-ico"><Icons.PhoneCall size={24} /></div>
              <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 14.5 }}>No calls yet</div>
              <div style={{ fontSize: 12.5, maxWidth: 360 }}>Once the agent starts dialing, each call shows up here with the seller's motivation, price, timeline, condition and more.</div>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(330px, 1fr))", gap: 14 }}>
              {calls.map((c, i) => <OutboundCallCard key={c.callId || i} c={c} />)}
            </div>
          )}
        </React.Fragment>
      )}
    </div>
  );
}

function Placeholder({ title, icon }) {
  const Icons = window.Icons;
  const Ico = Icons[icon] || Icons.Dashboard;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>{title}</h1>
      <div className="card empty" style={{ minHeight: "60vh" }}>
        <div className="empty-ico" style={{ width: 72, height: 72 }}><Ico size={30} /></div>
        <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>{title} is coming online</div>
        <div style={{ fontSize: 13, maxWidth: 320 }}>Marcus is wiring up this module. Connect your data and it'll light up here.</div>
      </div>
    </div>
  );
}

Object.assign(window, { Leads, ConversationsPage, AgentsPage, DealCalcPage, PipelinePage, TasksPage, OutboundPage, Placeholder });
