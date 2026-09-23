// atlas_card.jsx — Atlas call card + 30-second seller header (Wave-2 item 3, spec §7).
// Reads GET /api/prep/get?contactId= (deal_prep.DealPrep.get → {} when no prep yet).
// "Run prep" = POST /api/prep/run — internal underwriting (one Claude call), never outward.
//
// RULE 9 (CLAUDE.md §2): anchors + MAO math are INTERNAL operator prep. The offer is given
// by a human, on the call. This card deliberately has NO send / copy / copy-to-SMS / text
// control anywhere — do not add one.
//
// Collision rules (§7): hook alias useStateAtc, Atc/Atlas-prefixed globals, no computed tags.
const { useState: useStateAtc } = React;

const atcMoney = (v) => (typeof v === "number" ? window.fmtMoney(v) : "—");
const atcKnown = (v) => (v && v !== "unknown" ? v : null);

function AtcField({ label, value, color }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div className="faint" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 12.5, fontWeight: 600, color: value ? (color || "var(--text)") : "var(--text-3)" }}>
        {value || "Unknown"}
      </div>
    </div>
  );
}

function AtcAnchor({ label, value }) {
  return (
    <div style={{ flex: 1, minWidth: 90, textAlign: "center", background: "var(--bg)", borderRadius: 9, padding: "8px 6px" }}>
      <div className="faint" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 800 }}>{atcMoney(value)}</div>
    </div>
  );
}

// contactId (required) · lastContact (optional epoch-ms/ISO of the last thread message —
// neither the prep nor the screening record carries it, so the caller passes it).
function AtlasCallCard({ contactId, lastContact }) {
  const { data, loading, error, refresh } = window.useApi(
    "/api/prep/get?contactId=" + encodeURIComponent(contactId || ""));
  const [busy, setBusy] = useStateAtc(false);
  const [err, setErr] = useStateAtc(null);
  if (!contactId) return null;

  const rec = data || {};
  const p = rec.prep || null;

  async function runPrep() {
    setBusy(true); setErr(null);
    try { await window.apiPost("/api/prep/run", { contactId, force: !!p }); }
    catch (e) { setErr(e.message); }
    setBusy(false);
    refresh();
  }

  const runBtn = (
    <button className="tab" onClick={runPrep} disabled={busy}
      title="Atlas underwrites this seller (internal thinking — nothing is sent)"
      style={{ border: "1px solid var(--violet)", color: "var(--violet)" }}>
      {busy ? "Prepping…" : (p ? "↻ Re-run prep" : "Run prep")}
    </button>
  );
  const errLine = (err || error) && (
    <div style={{ fontSize: 12, color: "var(--red)" }}>Atlas: {err || error}</div>
  );

  const wrap = { border: "1px solid rgba(139,92,246,0.35)", borderRadius: 10, padding: "11px 13px",
    display: "flex", flexDirection: "column", gap: 10, background: "rgba(139,92,246,0.05)" };
  const title = <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--violet)" }}>📐 Atlas call card</div>;

  if (!p) {
    return (
      <div style={wrap}>
        {title}
        {loading && !data ? (
          <div className="faint" style={{ fontSize: 12.5 }}>Loading prep…</div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div className="faint" style={{ fontSize: 12.5, flex: 1, minWidth: 180 }}>
              No prep yet. Atlas auto-preps interested sellers every 15 min, or run it now.
            </div>
            {runBtn}
          </div>
        )}
        {errLine}
      </div>
    );
  }

  const an = p.anchors || {};
  const hasAnchors = an.opening != null || an.target != null || an.walkaway != null;
  const bedsBaths = (p.beds != null || p.baths != null)
    ? `${p.beds != null ? p.beds : "?"}bd/${p.baths != null ? p.baths : "?"}ba` : null;
  const property = [p.address, bedsBaths, atcKnown(p.occupancy)].filter(Boolean).join(" · ");
  const condition = [atcKnown(p.condition), atcKnown(p.repairEstimate)].filter(Boolean).join(" — ");

  return (
    <div style={wrap}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {title}
        <span className="faint" style={{ fontSize: 11, marginRight: "auto" }}>prepped {window.timeAgo(rec.updatedAt)}</span>
        {runBtn}
      </div>

      {/* 30-second seller header */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(140px,1fr))", gap: 12,
        background: "var(--card-2)", borderRadius: 10, padding: "11px 13px" }}>
        <AtcField label="Property" value={property || null} />
        <AtcField label="Timeline" value={atcKnown(p.timeline)} />
        <AtcField label="Seller ask" value={p.askingPrice != null ? atcMoney(p.askingPrice) : null} color="var(--green)" />
        <AtcField label="Condition" value={condition || null} />
        <AtcField label="Last contact" value={lastContact ? window.timeAgo(lastContact) : null} />
      </div>
      {p.motivationRead && (
        <div style={{ fontSize: 12.5, lineHeight: 1.45 }}>
          <span className="faint">Motivation: </span>{p.motivationRead}
        </div>
      )}

      {/* Anchors — INTERNAL */}
      <div style={{ border: "1px solid rgba(239,68,68,0.45)", borderRadius: 10, padding: "10px 12px",
        background: "rgba(239,68,68,0.06)", display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: "var(--red)", letterSpacing: 0.3 }}>
          🔒 INTERNAL — NEVER TEXT. Numbers come out only on the call, only when the seller talks price.
        </div>
        {hasAnchors ? (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <AtcAnchor label="Opening" value={an.opening} />
            <AtcAnchor label="Target" value={an.target} />
            <AtcAnchor label="Walkaway" value={an.walkaway} />
          </div>
        ) : (
          <div style={{ fontSize: 12.5 }}>No seller-stated ask — anchors stay blank. Pull comps first (MAO note below).</div>
        )}
        {p.anchorLogic && <div className="faint" style={{ fontSize: 11.5, lineHeight: 1.4 }}>{p.anchorLogic}</div>}
      </div>

      {p.maoNote && (
        <div style={{ fontSize: 12.5, lineHeight: 1.45 }}>
          <div className="faint" style={{ fontSize: 11, marginBottom: 3 }}>MAO math · comps to pull (internal)</div>
          {p.maoNote}
        </div>
      )}

      {p.callCard && p.callCard.length > 0 && (
        <div>
          <div className="faint" style={{ fontSize: 11, marginBottom: 4 }}>Call card</div>
          <ol style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 3, fontSize: 12.5 }}>
            {p.callCard.map((b, i) => <li key={i}>{b}</li>)}
          </ol>
        </div>
      )}

      {p.redFlags && p.redFlags.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <span className="faint" style={{ fontSize: 11 }}>Deal risks:</span>
          {p.redFlags.map((f, i) => (
            <span key={i} className="pill" style={{ fontSize: 10.5, color: "#EF4444", background: "#EF44441f", border: "1px solid #EF444444" }}>{f}</span>
          ))}
        </div>
      )}
      {errLine}
    </div>
  );
}

Object.assign(window, { AtlasCallCard });
