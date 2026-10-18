// chat_actions.jsx — owner-tap cards + "done" lines under an agent's chat reply.
// Backend: chat endpoints return `actions` (TAP cards awaiting the owner) and `done` (AUTO writes
// the agent already ran). ✅ -> POST /api/chat/action/confirm {tok}; ❌ -> .../cancel {tok}.
// Never auto-confirms. Inline styles only; inherits text colour so it works in dark + light.
// Hook aliases for this file: CA. Exports: window.ChatActions. Used by agents_hub, orion_office,
// dashboard, mobile/m_agents (mobile has no api.jsx, so fall back to apiPostM).
const { useState: useStateCA, useRef: useRefCA } = React;

const CA_GREEN = "#16a34a", CA_RED = "#ef4444";
const CA_BOX = {
  margin: "6px 0 0", padding: "9px 11px", borderRadius: 10, fontSize: 12.5, lineHeight: 1.45,
  border: "1px solid var(--border, rgba(127,127,127,.4))", background: "var(--card-2, rgba(127,127,127,.1))",
  color: "inherit", overflowWrap: "anywhere", wordBreak: "break-word", textAlign: "left", maxWidth: "100%", boxSizing: "border-box",
};
const CA_BTN = {
  minHeight: 36, padding: "6px 14px", borderRadius: 8, fontSize: 12.5, fontWeight: 600, cursor: "pointer",
  border: "1px solid var(--border, rgba(127,127,127,.5))", background: "transparent", color: "inherit",
};

function caArr(x) { return Array.isArray(x) ? x : []; }
function caStr(x) { return x == null ? "" : String(x); }
function caTrim(s, n) { s = caStr(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
function caBody(b) {
  if (typeof b === "string") return b;
  try { return JSON.stringify(b); } catch (_) { return caStr(b); }
}
// apiPost / apiPostM throw Error(server message) for any HTTP answer, TypeError when fetch itself failed.
function caIsNetwork(e) { return e instanceof TypeError || /failed to fetch|networkerror|load failed|network request/i.test(caStr(e && e.message)); }

function CADone({ d }) {
  const ok = !!(d && d.ok);
  const n = d && d.count > 1 ? " (" + d.count + ")" : "";
  return <div style={{ ...CA_BOX, display: "flex", gap: 7, alignItems: "baseline", color: ok ? "inherit" : CA_RED }}>
    <b style={{ color: ok ? CA_GREEN : CA_RED, flex: "none" }}>{ok ? "✔" : "✖"}</b>
    <span>{caStr(d && d.summary) || (d && d.path) || "Action"}{n}{!ok && d && d.error ? " — " + caTrim(d.error, 300) : ""}</span>
  </div>;
}

function CACard({ a }) {
  const tok = caStr(a && a.tok);
  const [st, setSt] = useStateCA({ s: "idle" });   // idle | busy | done | cancelled | error
  const guard = useRefCA(false);                     // a double click must not fire two requests
  const preview = caArr(a && a.preview).slice(0, 5);
  const count = Number(a && a.count) || 0;

  async function run(kind) {
    if (guard.current || !tok) return;
    guard.current = true;
    setSt({ s: "busy", kind });
    const post = window.apiPost || window.apiPostM;
    try {
      if (!post) throw new TypeError("Failed to fetch");
      const d = await post("/api/chat/action/" + kind, { tok });
      if (d && d.error) { setSt({ s: "error", msg: caStr(d.error), retry: !!d.cardKept, kind }); return; }   // server said no: token spent, unless cardKept
      setSt(kind === "cancel" ? { s: "cancelled" } : { s: "done", msg: caTrim((d && d.message) || "Done.", 300) });
    } catch (e) {
      const net = caIsNetwork(e);
      setSt({ s: "error", msg: caTrim((e && e.message) || "Failed", 300), retry: net, kind });
      if (net) guard.current = false;                // only a network failure may be retried
    }
  }

  const busy = st.s === "busy", settled = st.s === "done" || st.s === "cancelled" || (st.s === "error" && !st.retry);
  return <div style={{ ...CA_BOX, borderColor: "var(--workspace-accent, var(--border, rgba(127,127,127,.5)))" }}>
    <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
      <b style={{ flex: "1 1 auto", minWidth: 0 }}>{caStr(a && a.summary) || "Proposed action"}</b>
      {count > 1 && <span style={{ flex: "none", fontSize: 11, fontWeight: 700, padding: "1px 8px", borderRadius: 999, border: "1px solid currentColor", opacity: .8 }}>{count} items</span>}
    </div>
    {a && a.risk && <div style={{ fontSize: 11, opacity: .7, marginTop: 2 }}>Risk: {caStr(a.risk)}</div>}
    {preview.length > 0 && <details style={{ marginTop: 6 }}>
      <summary style={{ cursor: "pointer", fontSize: 11.5, opacity: .8 }}>Preview ({preview.length}{count > preview.length ? " of " + count : ""})</summary>
      {preview.map((p, i) => <div key={i} style={{ marginTop: 5, fontFamily: "var(--mono, ui-monospace, Menlo, monospace)", fontSize: 11, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
        <b>{caStr(p && p.path)}</b>{"\n"}{caTrim(caBody(p && p.body), 400)}
      </div>)}
    </details>}
    {!settled && <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
      <button type="button" style={{ ...CA_BTN, opacity: busy ? .5 : 1 }} disabled={busy} onClick={() => run("confirm")}>{busy && st.kind === "confirm" ? "Working…" : st.s === "error" && st.kind === "confirm" ? "✅ Retry" : "✅ Do it"}</button>
      <button type="button" style={{ ...CA_BTN, opacity: busy ? .5 : 1 }} disabled={busy} onClick={() => run("cancel")}>{busy && st.kind === "cancel" ? "Working…" : st.s === "error" && st.kind === "cancel" ? "❌ Retry" : "❌ Cancel"}</button>
    </div>}
    {st.s === "done" && <div role="status" style={{ marginTop: 8, color: CA_GREEN }}>✔ {st.msg}</div>}
    {st.s === "cancelled" && <div role="status" style={{ marginTop: 8, opacity: .7 }}>Cancelled</div>}
    {st.s === "error" && <div role="alert" style={{ marginTop: 8, color: CA_RED }}>✖ {st.msg}{st.retry ? " — card kept, you can retry." : ""}</div>}
  </div>;
}

function ChatActions({ actions, done }) {
  const acts = caArr(actions).filter((a) => a && typeof a === "object");
  const dn = caArr(done).filter((d) => d && typeof d === "object");
  if (!acts.length && !dn.length) return null;
  return <div style={{ marginTop: 2, maxWidth: "100%" }}>
    {dn.map((d, i) => <CADone key={"d" + i} d={d} />)}
    {acts.map((a, i) => <CACard key={a.tok || "a" + i} a={a} />)}
  </div>;
}

Object.assign(window, { ChatActions });
