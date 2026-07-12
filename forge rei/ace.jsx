// ace.jsx — ACE Autonomy panel: segmented mode control (off → shadow → supervised → full),
// live status (sends vs cap, block reasons), the call-ready queue, and a one-tap KILL
// switch. Mounted in the Command Center; a compact strip version rides the Dashboard.
// Additive, window-global, unique Ace* names + useStateAce alias, no computed tags.
const { useState: useStateAce } = React;

const ACE_MODES = [
  ["off", "Off", "everything manual"],
  ["shadow", "Shadow", "drafts queue for your tap, no sends"],
  ["supervised", "Supervised", "auto-texts, low cap, full gates"],
  ["full", "Full", "auto-texts, normal cap, full gates"],
];
const ACE_MODE_COLOR = { off: "#64748B", shadow: "#4F7CFF", supervised: "#F59E0B", full: "#22C55E" };

function AceModeControl({ mode, onSet, busy }) {
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      {ACE_MODES.map(([m, label, hint]) => {
        const active = mode === m;
        return (
          <button key={m} className="tab" disabled={busy} title={hint}
            onClick={() => onSet(m)}
            style={{
              fontWeight: 700,
              background: active ? ACE_MODE_COLOR[m] : "var(--card-2)",
              color: active ? "#fff" : "var(--text)",
              opacity: busy ? 0.6 : 1,
            }}>
            {label}
          </button>
        );
      })}
    </div>
  );
}

function AceCallReadyRow({ row, onAck, busy }) {
  const a = row.anchors || {};
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 2px",
                  borderBottom: "1px solid var(--card-2)", flexWrap: "wrap" }}>
      <div style={{ flex: 1, minWidth: 170 }}>
        <div style={{ fontWeight: 600, fontSize: 13.5 }}>📞 {row.name || row.convId}</div>
        <div className="faint" style={{ fontSize: 11 }}>
          {row.askingPrice ? "seller asked " + row.askingPrice + " · " : ""}
          {a.opening ? ("anchors $" + Math.round(a.opening).toLocaleString()
            + " / $" + Math.round(a.target || 0).toLocaleString()
            + " / $" + Math.round(a.walkaway || 0).toLocaleString()) : "no anchors yet"}
        </div>
      </div>
      {row.ackAt
        ? <span className="faint" style={{ fontSize: 11.5 }}>✅ yours</span>
        : <button className="tab" disabled={busy}
            onClick={() => onAck(row.convId)}
            style={{ background: "var(--accent, #46a758)", color: "#fff", fontWeight: 700 }}>
            {busy ? "…" : "✅ Got it"}
          </button>}
    </div>
  );
}

function AcePanel() {
  const st = window.useApi("/api/ace/status", { interval: 15000 });
  const dg = window.useApi("/api/ace/digest", { interval: 30000 });
  const cr = window.useApi("/api/ace/callready", { interval: 30000 });
  const [aceBusy, setAceBusy] = useStateAce(false);
  const [ackBusy, setAckBusy] = useStateAce(null);

  const s = st.data || {};
  const d = dg.data || {};
  const sum = d.summary || {};
  const rows = (cr.data && cr.data.callReady) || [];
  const mode = s.mode || "off";
  const modeColor = ACE_MODE_COLOR[mode] || ACE_MODE_COLOR.off;

  const setMode = async (m) => {
    setAceBusy(true);
    try { await window.apiPost("/api/ace/mode", { mode: m }); }
    catch (e) { /* refresh shows truth */ }
    setAceBusy(false);
    st.refresh(); dg.refresh();
  };
  const ack = async (convId) => {
    setAckBusy(convId);
    try { await window.apiPost("/api/ace/ack", { convId }); }
    catch (e) { /* refresh shows truth */ }
    setAckBusy(null);
    cr.refresh();
  };

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div className="card-title" style={{ fontSize: 15 }}>
            🤖 ACE Autonomy
            <span style={{ marginLeft: 8, fontSize: 11.5, fontWeight: 800, color: modeColor,
                           letterSpacing: 1 }}>{mode.toUpperCase()}</span>
            {s.testScoped && <span style={{ marginLeft: 8, fontSize: 10.5, fontWeight: 800,
              color: "#60A5FA", letterSpacing: 0.8 }}>TEST-SCOPED · {s.testPhoneCount || 0} PHONE</span>}
          </div>
          <div className="faint" style={{ fontSize: 11.5 }}>
            {mode === "off" ? "asleep — every text is your tap" :
              (s.sentToday || 0) + "/" + (d.cap || 0) + " auto-texts today · "
              + (sum.shadowDrafts || 0) + " drafts · " + (sum.escalations || 0) + " escalations · "
              + (sum.blocked || 0) + " blocked by gates"}
          </div>
        </div>
        {mode !== "off" && (
          <button onClick={() => setMode("off")} disabled={aceBusy}
            style={{ background: "var(--danger, #e5484d)", color: "#fff", border: "none",
                     borderRadius: 10, padding: "9px 16px", fontSize: 13, fontWeight: 800,
                     fontFamily: "inherit", cursor: "pointer", opacity: aceBusy ? 0.6 : 1 }}>
            🛑 KILL — all autonomy off
          </button>
        )}
      </div>
      <AceModeControl mode={mode} onSet={setMode} busy={aceBusy} />
      <div className="faint" style={{ fontSize: 10.5 }}>
        Every ACE text runs the FULL gate stack (legit thread check, 9–8 ET, DNC, price-scrub,
        dedupe, clock-out) — never quotes a price. Clock-out and Off both stop it instantly.
        {s.testScoped ? " Test Mode is ON: non-whitelisted contacts are blocked server-side." : ""}
      </div>

      {rows.length > 0 && (
        <div>
          <div className="card-title" style={{ fontSize: 13.5, margin: "4px 0" }}>
            Call-ready queue {cr.data && cr.data.waiting ? `(${cr.data.waiting} waiting)` : ""}
          </div>
          {rows.slice(0, 6).map((r) => (
            <AceCallReadyRow key={r.convId} row={r} onAck={ack} busy={ackBusy === r.convId} />
          ))}
        </div>
      )}

      {(d.events || []).length > 0 && (
        <div>
          <div className="card-title" style={{ fontSize: 13.5, margin: "4px 0" }}>Last activity</div>
          {(d.events || []).slice(0, 8).map((e, i) => (
            <div key={i} className="faint" style={{ fontSize: 11.5, padding: "3px 2px" }}>
              <span style={{ fontWeight: 700 }}>{e.kind}</span>
              {e.name ? " · " + e.name : ""} — {String(e.detail || "").slice(0, 90)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Compact strip for the main Dashboard: mode + today's counts + call-ready, tap → Command.
function AceStrip() {
  const st = window.useApi("/api/ace/digest", { interval: 30000 });
  const d = st.data || {};
  const sum = d.summary || {};
  const mode = d.mode || "off";
  if (mode === "off") return null;   // dashboard stays clean until autonomy is on
  const c = ACE_MODE_COLOR[mode] || "#64748B";
  return (
    <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 12,
                                            cursor: "pointer", flexWrap: "wrap" }}
      onClick={() => window.GoTo && window.GoTo("Command")}>
      <span style={{ width: 10, height: 10, borderRadius: "50%", background: c, flexShrink: 0 }} />
      <div style={{ fontWeight: 700, fontSize: 13.5 }}>ACE {mode.toUpperCase()}</div>
      <div className="faint" style={{ fontSize: 12 }}>
        {(d.sentToday || 0)}/{d.cap || 0} auto-texts · {sum.escalations || 0} escalations ·
        {" "}{d.callReadyWaiting || 0} call-ready
      </div>
      <span className="faint" style={{ marginLeft: "auto", fontSize: 11 }}>manage →</span>
    </div>
  );
}

Object.assign(window, { AcePanel, AceStrip });
