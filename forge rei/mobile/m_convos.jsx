// FORGE Mobile — Conversations tab. Live GHL conversation list + full-screen
// thread with the operator-gated reply flow (Draft (AI) fills the textarea,
// Send confirms first — NEVER auto-sends).
//
// Endpoints (identical to desktop):
//   GET  /api/conversations?limit=100   (poll 25s; no query param — filter client-side)
//   GET  /api/messages?contactId=<id>   (oldest -> newest; poll 15s)
//   POST /api/reply/draft  { convId, contactId, name }                      -> { draft, source }
//   POST /api/reply/send   { contactId, convId, message, name, lastMessageDate }
//
// Hook aliases for this file: MC. Exports: MConvosPage.
const { useState: useStateMC, useEffect: useEffectMC, useRef: useRefMC } = React;

const MC_AVA_COLORS = ["#4F7CFF", "#8B5CF6", "#2DD4BF", "#22C55E", "#F59E0B", "#EC4899", "#EF4444", "#0EA5E9"];

function MCAvaColor(s) {
  let h = 0;
  for (let i = 0; i < (s || "").length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return MC_AVA_COLORS[h % MC_AVA_COLORS.length];
}

function MCInitials(name) {
  const parts = (name || "?").trim().split(/\s+/).filter(Boolean);
  return ((parts[0] || "?")[0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

function MCAvatar(props) {
  const c = props.convo || {};
  return (
    <div style={{ width: 42, height: 42, borderRadius: "50%", flexShrink: 0, display: "grid", placeItems: "center",
      background: MCAvaColor(c.contactId || c.name), color: "#fff", fontSize: 14, fontWeight: 700 }}>
      {MCInitials(c.name)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Thread — full-screen sheet: bubbles + operator-gated reply composer.
// ---------------------------------------------------------------------------
function MCThread(props) {
  const MI = window.MIcons;
  const convo = props.convo;
  const { data, error, loading, refresh } = window.useApiM(
    "/api/messages?contactId=" + encodeURIComponent(convo.contactId || ""), { interval: 15000 });

  const [draft, setDraft] = useStateMC("");
  const [draftMeta, setDraftMeta] = useStateMC("");  // draft source tag (ai/template)
  const [drafting, setDrafting] = useStateMC(false);
  const [sending, setSending] = useStateMC(false);
  const [note, setNote] = useStateMC(null);        // { kind: "ok"|"err", text }
  const [pending, setPending] = useStateMC([]);    // optimistic outbound bubbles
  const endRef = useRefMC(null);
  const hasDraft = !!draft.trim();

  const msgs = ((data && data.messages) || []).concat(
    pending.map((b) => ({ direction: "outbound", body: b, date: Date.now(), pending: true })));

  // Newest at bottom — jump there on open + whenever the thread grows.
  useEffectMC(() => {
    if (endRef.current) endRef.current.scrollIntoView({ block: "end" });
  }, [msgs.length, loading]);

  // "Draft (AI)" fills the textarea; "Redo" (variation=true) remakes a fresh,
  // different reply off the same thread. Operator edits, then Approve & send.
  async function doDraft(variation) {
    if (drafting || sending) return;
    setDrafting(true);
    setNote(null);
    const prev = draft.trim();
    const reqBody = { convId: convo.id, contactId: convo.contactId, name: convo.name };
    if (variation && prev) {
      reqBody.hint = ("Rewrite this reply completely differently — a new angle and a "
        + "fresh opening. Do not reuse the wording of this previous draft: \"" + prev
        + "\". Keep it short and in-voice.");
    }
    try {
      const r = await window.apiPostM("/api/reply/draft", reqBody);
      setDraft(r.draft || "");
      setDraftMeta(r.source || "");
      setNote({ kind: "ok", text: (variation ? "Fresh take ready" : "Draft ready")
        + (r.source ? " · " + r.source : "") + " — edit, then Approve" });
    } catch (e) {
      setNote({ kind: "err", text: "Draft failed: " + e.message });
    }
    setDrafting(false);
  }

  // Dismiss — clear the AI draft without sending.
  function doDismiss() {
    setDraft("");
    setDraftMeta("");
    setNote(null);
  }

  // Send — window.confirm gates every send. Same POST as the desktop reply flow.
  async function doSend() {
    const text = draft.trim();
    if (!text || sending || drafting) return;
    const who = convo.name + (convo.phone ? " (" + convo.phone + ")" : "");
    if (!window.confirm('Send this SMS to ' + who + '?\n\n"' + text + '"')) return;
    setSending(true);
    setNote(null);
    setPending((p) => p.concat([text]));
    try {
      const r = await window.apiPostM("/api/reply/send", {
        contactId: convo.contactId, convId: convo.id, message: text,
        name: convo.name, lastMessageDate: convo.lastMessageDate,
      });
      setDraft("");
      setDraftMeta("");
      setNote({ kind: "ok", text: "Sent ✓" + (r && r.markedDone ? " · checked off Do Today" : "") });
      setTimeout(() => { refresh(); setPending((p) => p.slice(1)); }, 1200);
    } catch (e) {
      setPending((p) => p.slice(0, -1));   // roll back the optimistic bubble
      setNote({ kind: "err", text: "Send failed: " + e.message });
    }
    setSending(false);
  }

  return (
    <div className="m-sheet">
      <div className="m-sheet-head">
        <button className="m-tab" style={{ flex: "none", minWidth: 44, minHeight: 44, padding: 4 }} onClick={props.onClose}>
          <MI.Back size={22} />
        </button>
        <MCAvatar convo={convo} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15.5, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {convo.name}
          </div>
          <div className="m-fade">{convo.phone || (data ? (data.count || 0) + " messages" : "")}</div>
        </div>
        <button className="m-tab" style={{ flex: "none", minWidth: 44, minHeight: 44, padding: 4 }} onClick={refresh}>
          <MI.Refresh size={19} />
        </button>
      </div>

      <div className="m-sheet-body">
        {loading && !data && <window.MSpin />}
        {error && (
          <div className="m-fade" style={{ color: "var(--red, #EF4444)", textAlign: "center", padding: 8 }}>
            {String(error)} — <span style={{ textDecoration: "underline" }} onClick={refresh}>retry</span>
          </div>
        )}
        {!loading && !error && msgs.length === 0 && (
          <window.MEmpty title="No messages yet" sub="Draft a reply below to start the thread." />
        )}
        {msgs.map((m, i) => {
          const out = m.direction === "outbound";
          return (
            <div key={i} className={"m-bubble " + (out ? "out" : "in")}
              style={{ whiteSpace: "pre-wrap", opacity: m.pending ? 0.6 : 1 }}>
              {m.body}
              <div style={{ fontSize: 10, opacity: 0.6, marginTop: 4, textAlign: "right" }}>
                {m.pending ? "sending…" : window.timeAgoM(m.date)}
              </div>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>

      <div className="m-sheet-foot">
        {note && (
          <div className="m-fade" style={{ marginBottom: 8, color: note.kind === "err" ? "var(--red, #EF4444)" : "var(--green, #22C55E)" }}>
            {note.text}
          </div>
        )}
        {hasDraft && (
          <div className="m-row" style={{ marginBottom: 6, gap: 6 }}>
            <span style={{ flex: 1, fontSize: 11, fontWeight: 700, color: "var(--blue, #4F7CFF)" }}>
              ✨ AI draft{draftMeta ? " · " + draftMeta : ""} — approve, redo, or edit
            </span>
          </div>
        )}
        <textarea className="m-input" rows={2} value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={"Text " + ((convo.name || "").split(" ")[0] || "seller") + "…"} />
        {hasDraft ? (
          <div className="m-row" style={{ marginTop: 8, gap: 6 }}>
            <window.MBtn kind="ghost" onClick={() => doDraft(true)} disabled={drafting || sending}
              style={{ flex: "none", padding: "10px 12px" }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                <MI.Refresh size={15} />{drafting ? "…" : "Redo"}
              </span>
            </window.MBtn>
            <window.MBtn kind="no" onClick={doDismiss} disabled={sending}
              style={{ flex: "none", padding: "10px 12px" }}>
              <MI.X size={15} />
            </window.MBtn>
            <window.MBtn kind="ok" onClick={doSend} disabled={sending || drafting || !draft.trim()} style={{ flex: 1 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <MI.Check size={15} />{sending ? "Sending…" : "Approve & send"}
              </span>
            </window.MBtn>
          </div>
        ) : (
          <div className="m-row" style={{ marginTop: 8 }}>
            <window.MBtn kind="ghost" onClick={() => doDraft(false)} disabled={drafting || sending} style={{ flex: 1 }}>
              {drafting ? "Drafting…" : "Draft (AI)"}
            </window.MBtn>
            <window.MBtn kind="ok" onClick={doSend} disabled={sending || drafting || !draft.trim()} style={{ flex: 1 }}>
              {sending ? "Sending…" : "Send"}
            </window.MBtn>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Conversations tab — searchable live list, tap a row to open the thread.
// ---------------------------------------------------------------------------
function MConvosPage() {
  const MI = window.MIcons;
  const [q, setQ] = useStateMC("");
  const [sel, setSel] = useStateMC(null);   // tapped conversation (snapshot)
  const { data, error, loading, refresh } = window.useApiM("/api/conversations?limit=100", { interval: 25000 });

  const all = (data && data.conversations) || [];
  // /api/conversations has no search param — filter client-side like the desktop.
  const convos = all.filter((c) =>
    q === "" || ((c.name || "") + (c.lastMessage || "") + (c.phone || "")).toLowerCase().includes(q.toLowerCase()));

  // Keep the open thread's convo fresh as the list auto-refreshes.
  const active = sel ? (all.find((c) => c.id === sel.id) || sel) : null;

  return (
    <React.Fragment>
      <window.MHeader title="Conversations"
        sub={data ? (data.total || all.length).toLocaleString() + " total · live" : "live GHL threads"}
        right={
          <button className="m-tab" style={{ flex: "none", minWidth: 44, minHeight: 44, padding: 4 }} onClick={refresh}>
            <MI.Refresh size={20} />
          </button>
        } />
      <div className="m-content">
        <div className="m-row" style={{ gap: 8 }}>
          <span className="m-fade" style={{ flexShrink: 0, display: "grid", placeItems: "center" }}><MI.Search size={17} /></span>
          <input className="m-input" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, message, phone…" style={{ flex: 1 }} />
        </div>

        {loading && !data && <window.MSpin />}
        {error && (
          <div className="m-fade" style={{ color: "var(--red, #EF4444)", textAlign: "center", padding: 8 }}>
            {String(error)} — <span style={{ textDecoration: "underline" }} onClick={refresh}>retry</span>
          </div>
        )}
        {!loading && !error && convos.length === 0 && (
          <window.MEmpty title={q ? "No matches" : "No conversations"}
            sub={q ? "Nothing matches “" + q + "”." : "Seller threads from GHL will show up here."} />
        )}

        {convos.map((c) => (
          <div key={c.id} className="m-list-item" onClick={() => setSel(c)}
            style={{ cursor: "pointer", minHeight: 44 }}>
            <MCAvatar convo={c} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="m-row" style={{ gap: 8 }}>
                <span style={{ flex: 1, minWidth: 0, fontSize: 14, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {c.name}
                </span>
                <span className="m-fade" style={{ flexShrink: 0, fontSize: 11 }}>{window.timeAgoM(c.lastMessageDate)}</span>
              </div>
              <div className="m-fade" style={{ marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {c.lastMessage || "—"}
              </div>
            </div>
            {c.unread > 0 && (
              <span style={{ flexShrink: 0, minWidth: 20, height: 20, padding: "0 6px", borderRadius: 10,
                background: "var(--blue, #4F7CFF)", color: "#fff", fontSize: 11, fontWeight: 700,
                display: "grid", placeItems: "center" }}>
                {c.unread}
              </span>
            )}
          </div>
        ))}
      </div>
      {active && <MCThread convo={active} onClose={() => setSel(null)} />}
    </React.Fragment>
  );
}

// MCThread + MCAvatar are exported so Home can open a seller's thread directly
// when you tap a person (see m_home.jsx tap-to-open).
Object.assign(window, { MConvosPage, MCThread, MCAvatar });
