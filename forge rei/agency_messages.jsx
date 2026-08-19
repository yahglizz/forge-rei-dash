// agency_messages.jsx — the operator side of the client portal chat.
// Left pane = the client book with unread pills; right pane = that client's
// thread + composer. Backend: /api/agency/messages* (agency_io.py).
//
// STATIC-REACT RULES (no build step in this dashboard):
//   - hooks aliased (…Ms) so nothing collides with the other .jsx files
//   - every top-level name prefixed Ms / MS_
//   - no computed JSX tags — resolve the icon into a const first
//   - shipped on window at the bottom
const { useState: useStateMs, useEffect: useEffectMs } = React;

const MS_ACCENT = "#8B5CF6";
const MS_FEED_ID = "ms-feed";
const msInp = {
  background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 9,
  padding: "9px 11px", color: "var(--text)", fontSize: 13, width: "100%", outline: "none",
};

// ---- left pane row ----------------------------------------------------------
function MsClientBtn({ c, active, unread, onClick }) {
  return (
    <button onClick={onClick}
      style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left",
        padding: "9px 10px", borderRadius: 9, cursor: "pointer", background: active ? MS_ACCENT + "1f" : "transparent",
        border: "1px solid " + (active ? MS_ACCENT : "transparent"), color: "var(--text)" }}>
      <span style={{ width: 30, height: 30, borderRadius: 8, flexShrink: 0, display: "grid", placeItems: "center",
        background: MS_ACCENT + "1f", color: MS_ACCENT, fontWeight: 700, fontSize: 13 }}>
        {(c.name || "?").slice(0, 1).toUpperCase()}
      </span>
      <span style={{ minWidth: 0, flex: 1 }}>
        <span style={{ display: "block", fontWeight: 600, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.name}</span>
        <span className="faint" style={{ display: "block", fontSize: 11.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {c.business || c.site || "—"}
        </span>
      </span>
      {unread > 0 && (
        <span style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: MS_ACCENT,
          padding: "1px 7px", borderRadius: 999, flexShrink: 0 }}>{unread}</span>
      )}
    </button>
  );
}

// ---- one message ------------------------------------------------------------
function MsBubble({ m }) {
  const mine = m.from === "operator";
  return (
    <div style={{ display: "flex", justifyContent: mine ? "flex-end" : "flex-start" }}>
      <div style={{ maxWidth: "78%", display: "flex", flexDirection: "column", gap: 3,
        alignItems: mine ? "flex-end" : "flex-start" }}>
        <div style={{ padding: "8px 11px", borderRadius: 11, fontSize: 13, lineHeight: 1.45,
          whiteSpace: "pre-wrap", wordBreak: "break-word",
          background: mine ? MS_ACCENT : "var(--card-2)",
          color: mine ? "#fff" : "var(--text)",
          border: mine ? "1px solid transparent" : "1px solid var(--border)",
          opacity: m.pending ? 0.6 : 1 }}>
          {m.text}
        </div>
        <span className="faint" style={{ fontSize: 10.5 }}>
          {m.pending ? "Sending…" : window.timeAgo(m.ts)}
        </span>
      </div>
    </div>
  );
}

// ---- right pane: one client's thread ---------------------------------------
// Only mounted once a client is picked, so the poll never fires with no id.
function MsThread({ clientId, clientName, onRead }) {
  const { data, error, loading, refresh } =
    window.useApi("/api/agency/messages?clientId=" + encodeURIComponent(clientId), { interval: 10000 });
  const [text, setText] = useStateMs("");
  const [sending, setSending] = useStateMs(false);
  const [pending, setPending] = useStateMs([]);
  const [readFor, setReadFor] = useStateMs("");
  const msgs = ((data && data.messages) || []).concat(pending);

  // Clear the unread badge once — the first time this client's thread loads.
  useEffectMs(() => {
    if (!data || readFor === clientId) return;
    setReadFor(clientId);
    window.apiPost("/api/agency/message/read", { clientId })
      .then(() => onRead && onRead())
      .catch(() => {});
  }, [clientId, data, readFor]);

  // Pin the feed to the newest message.
  useEffectMs(() => {
    const el = document.getElementById(MS_FEED_ID);
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs.length, clientId]);

  async function send() {
    const t = text.trim();
    if (!t || sending) return;
    const tmp = { id: "tmp" + Date.now(), clientId, from: "operator", text: t, ts: new Date().toISOString(), pending: true };
    setSending(true); setText("");
    setPending((p) => p.concat([tmp]));
    try {
      await window.apiPost("/api/agency/message/send", { clientId, text: t });
      await refresh();
      setPending((p) => p.filter((x) => x.id !== tmp.id));
    } catch (e) {
      setPending((p) => p.filter((x) => x.id !== tmp.id));
      setText(t);   // give the operator their words back
      window.alert("Send failed: " + (e.message || e));
    }
    setSending(false);
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 10, minHeight: 420 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, borderBottom: "1px solid var(--border)", paddingBottom: 9 }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>{clientName || "Client"}</span>
        <span className="faint" style={{ fontSize: 11.5, marginLeft: "auto" }}>{msgs.length} message{msgs.length === 1 ? "" : "s"}</span>
      </div>
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      <div id={MS_FEED_ID} style={{ flex: 1, minHeight: 240, maxHeight: "52vh", overflowY: "auto",
        display: "flex", flexDirection: "column", gap: 10, paddingRight: 4 }}>
        {loading && !data && <window.LoadingRow label="Loading conversation…" />}
        {!loading && msgs.length === 0 && (
          <div className="faint" style={{ fontSize: 12.5, padding: "18px 2px" }}>
            No messages yet — say hello and they'll see it the next time they open their portal.
          </div>
        )}
        {msgs.map((m) => <MsBubble key={m.id} m={m} />)}
      </div>
      <div style={{ display: "flex", gap: 9, alignItems: "flex-end", borderTop: "1px solid var(--border)", paddingTop: 10 }}>
        <textarea style={{ ...msInp, minHeight: 44, resize: "vertical", fontFamily: "inherit" }}
          value={text} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="Write to this client…  (Enter sends)"
          title="Enter sends · Shift+Enter starts a new line" />
        <button className="tab" disabled={sending || !text.trim()} onClick={send}
          style={{ background: MS_ACCENT, color: "#fff", fontWeight: 700, borderColor: "transparent",
            opacity: (sending || !text.trim()) ? 0.5 : 1, whiteSpace: "nowrap" }}>
          {sending ? "Sending…" : "Send"}
        </button>
      </div>
    </div>
  );
}

// ---- the page ---------------------------------------------------------------
function AgencyMessages() {
  const Icons = window.Icons;
  const Ico = Icons.Messages || Icons.Message || Icons.Bot;
  const { data: cd, error, loading, refresh } = window.useApi("/api/agency/clients", { interval: 20000 });
  const { data: ud, refresh: refreshUnread } = window.useApi("/api/agency/messages/unread", { interval: 15000 });
  const [sel, setSel] = useStateMs("");
  const [q, setQ] = useStateMs("");

  const unread = (ud && ud.byClient) || {};
  const all = (cd && cd.clients) || [];
  const needle = q.trim().toLowerCase();
  const clients = (needle
    ? all.filter((c) => ((c.name || "") + " " + (c.business || "") + " " + (c.site || "")).toLowerCase().includes(needle))
    : all.slice()
  // /api/agency/clients already comes back newest-activity-first; a stable sort
  // just floats the unread threads above it.
  ).sort((a, b) => (unread[b.id] ? 1 : 0) - (unread[a.id] ? 1 : 0));
  const current = all.find((c) => c.id === sel);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Client Chat</h1>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>
          Your direct line with each client — the same thread they see inside their private portal.
        </div>
      </div>
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {loading && !cd && <window.LoadingRow label="Loading clients…" />}

      {!loading && all.length === 0 && (
        <div className="card empty" style={{ minHeight: "40vh" }}>
          <div className="empty-ico" style={{ width: 72, height: 72 }}><Ico size={30} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>No clients yet</div>
          <div style={{ fontSize: 13, maxWidth: 340, textAlign: "center" }}>
            Add a client first — every client gets their own portal thread here.
          </div>
          <button className="tab" style={{ marginTop: 14 }} onClick={() => window.GoTo && window.GoTo("Clients")}>
            Go to Clients
          </button>
        </div>
      )}

      {all.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-start" }}>
          <div className="card card-pad" style={{ flex: "1 1 250px", minWidth: 230, maxWidth: 340,
            display: "flex", flexDirection: "column", gap: 8 }}>
            {all.length > 6 && (
              <input style={msInp} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search clients…" />
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: "58vh", overflowY: "auto" }}>
              {clients.length === 0 && <div className="faint" style={{ fontSize: 12.5, padding: 6 }}>No match.</div>}
              {clients.map((c) => (
                <MsClientBtn key={c.id} c={c} active={c.id === sel} unread={Number(unread[c.id]) || 0}
                  onClick={() => setSel(c.id)} />
              ))}
            </div>
          </div>

          <div style={{ flex: "3 1 340px", minWidth: 280 }}>
            {sel ? (
              <MsThread key={sel} clientId={sel} clientName={current ? current.name : ""} onRead={refreshUnread} />
            ) : (
              <div className="card empty" style={{ minHeight: 340 }}>
                <div className="empty-ico" style={{ width: 64, height: 64 }}><Ico size={26} /></div>
                <div style={{ fontSize: 13, color: "var(--muted)" }}>Pick a client to open the conversation.</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { AgencyMessages });
