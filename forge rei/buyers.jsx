// buyers.jsx — Dispositions: the cash-buyer roster + buy-box match (the dispo half of
// the deal loop). Manage who buys (areas / max price / type / POF), then for every deal
// that needs a home see the ranked buyers to call and one-tap assign one.
// Assign is reversible + internal (writes a link onto the deal record) — no outward action.
const { useState: useStateBy, useEffect: useEffectBy, useCallback: useCallbackBy } = React;

const BY_TYPES = ["sfr", "multi", "land", "mobile", "condo", "commercial"];
const BY_COND = ["any", "light", "heavy"];
const BY_STRAT = ["", "flip", "buyhold", "wholetail", "brrrr"];

const byScoreColor = (s, fits) =>
  !fits ? "#64748B" : s >= 70 ? "#22C55E" : s >= 45 ? "#F59E0B" : "#EF4444";

function ByPill({ text, color }) {
  const c = color || "var(--text-3)";
  return (
    <span className="pill" style={{
      fontSize: 10.5, fontWeight: 600, color: c,
      background: c + "1f", border: "1px solid " + c + "3a",
    }}>{text}</span>
  );
}

function ByField({ label, children }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
      <span className="faint" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</span>
      {children}
    </label>
  );
}

const byInput = {
  background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 8,
  padding: "7px 9px", color: "var(--text)", fontSize: 12.5, fontFamily: "inherit", width: "100%",
};

// ---- buyer add/edit form -------------------------------------------------------
function BuyerForm({ seed, onSaved, onCancel }) {
  const s = seed || {};
  const [f, setF] = useStateBy({
    id: s.id || "", name: s.name || "", company: s.company || "", phone: s.phone || "",
    email: s.email || "", areas: (s.areas || []).join(", "),
    propertyTypes: s.propertyTypes || [], maxPrice: s.maxPrice || "", minBeds: s.minBeds || "",
    condition: s.condition || "any", strategy: s.strategy || "", pof: !!s.pof, notes: s.notes || "",
  });
  const [saving, setSaving] = useStateBy(false);
  const [err, setErr] = useStateBy(null);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const toggleType = (t) =>
    set("propertyTypes", f.propertyTypes.includes(t)
      ? f.propertyTypes.filter((x) => x !== t) : [...f.propertyTypes, t]);

  async function save() {
    if (!f.name.trim() && !f.company.trim()) { setErr("name or company required"); return; }
    setSaving(true); setErr(null);
    try {
      await window.apiPost("/api/buyers/upsert", { ...f });
      onSaved && onSaved();
    } catch (e) { setErr(e.message || String(e)); }
    finally { setSaving(false); }
  }

  return (
    <div className="card" style={{ padding: 14, display: "flex", flexDirection: "column", gap: 11, borderColor: "var(--accent, #4F7CFF)55" }}>
      <div style={{ fontWeight: 700, fontSize: 13 }}>{s.id ? "Edit buyer" : "New cash buyer"}</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9 }}>
        <ByField label="Name"><input style={byInput} value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Buyer name" /></ByField>
        <ByField label="Company"><input style={byInput} value={f.company} onChange={(e) => set("company", e.target.value)} placeholder="LLC / entity" /></ByField>
        <ByField label="Phone"><input style={byInput} value={f.phone} onChange={(e) => set("phone", e.target.value)} placeholder="(___) ___-____" /></ByField>
        <ByField label="Email"><input style={byInput} value={f.email} onChange={(e) => set("email", e.target.value)} placeholder="buyer@email.com" /></ByField>
      </div>
      <ByField label="Buy areas (city / zip / county — comma separated)">
        <input style={byInput} value={f.areas} onChange={(e) => set("areas", e.target.value)} placeholder="Wilmington, 19805, New Castle County, Dover" />
      </ByField>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 9 }}>
        <ByField label="Max price"><input style={byInput} value={f.maxPrice} onChange={(e) => set("maxPrice", e.target.value)} placeholder="$150,000" /></ByField>
        <ByField label="Min beds"><input style={byInput} value={f.minBeds} onChange={(e) => set("minBeds", e.target.value)} placeholder="3" /></ByField>
        <ByField label="Condition tolerance">
          <select style={byInput} value={f.condition} onChange={(e) => set("condition", e.target.value)}>
            {BY_COND.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </ByField>
      </div>
      <ByField label="Property types (none = any)">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {BY_TYPES.map((t) => {
            const on = f.propertyTypes.includes(t);
            return (
              <button key={t} onClick={() => toggleType(t)} className="tab"
                style={{ fontSize: 11, padding: "4px 9px", textTransform: "uppercase", letterSpacing: 0.3,
                  background: on ? "var(--accent, #4F7CFF)" : "var(--card-2)",
                  color: on ? "#fff" : "var(--text-3)", border: "1px solid " + (on ? "transparent" : "var(--border)") }}>
                {t}
              </button>
            );
          })}
        </div>
      </ByField>
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 9, alignItems: "end" }}>
        <ByField label="Strategy">
          <select style={byInput} value={f.strategy} onChange={(e) => set("strategy", e.target.value)}>
            {BY_STRAT.map((c) => <option key={c} value={c}>{c || "—"}</option>)}
          </select>
        </ByField>
        <label style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12.5, paddingBottom: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={f.pof} onChange={(e) => set("pof", e.target.checked)} /> Proof of funds on file
        </label>
      </div>
      <ByField label="Notes">
        <textarea style={{ ...byInput, minHeight: 52, resize: "vertical" }} value={f.notes} onChange={(e) => set("notes", e.target.value)} placeholder="POF source, deal preferences, last deal…" />
      </ByField>
      {err && <div className="mono" style={{ color: "var(--red)", fontSize: 11.5 }}>{err}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn-primary" onClick={save} disabled={saving}
          style={{ padding: "8px 16px", borderRadius: 8, border: "none", fontWeight: 600, fontSize: 12.5,
            background: "var(--accent, #4F7CFF)", color: "#fff", cursor: "pointer", opacity: saving ? 0.6 : 1 }}>
          {saving ? "Saving…" : s.id ? "Save changes" : "Add buyer"}
        </button>
        <button className="tab" onClick={onCancel} style={{ padding: "8px 14px" }}>Cancel</button>
      </div>
    </div>
  );
}

// ---- one buyer card in the roster ----------------------------------------------
function BuyerCard({ b, onEdit, onChanged }) {
  const Icons = window.Icons;
  const [busy, setBusy] = useStateBy(false);
  async function act(path, body) {
    setBusy(true);
    try { await window.apiPost(path, body); onChanged && onChanged(); }
    finally { setBusy(false); }
  }
  const remove = () => { if (window.confirm(`Remove buyer ${b.name || b.company}?`)) act("/api/buyers/remove", { id: b.id }); };
  const toggle = () => act("/api/buyers/upsert", { id: b.id, active: !b.active });
  return (
    <div className="card" style={{ padding: 13, display: "flex", flexDirection: "column", gap: 8, opacity: b.active ? 1 : 0.55 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 13.5 }}>{b.name || b.company || b.id}</div>
          {b.company && b.name && <div className="faint" style={{ fontSize: 11.5 }}>{b.company}</div>}
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          {b.pof && <ByPill text="POF" color="#22C55E" />}
          {!b.active && <ByPill text="paused" color="#64748B" />}
        </div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {b.maxPrice ? <ByPill text={"≤ " + window.fmtMoney(b.maxPrice)} color="#4F7CFF" /> : null}
        {(b.areas || []).slice(0, 4).map((a) => <ByPill key={a} text={a} color="#2DD4BF" />)}
        {(b.propertyTypes || []).map((t) => <ByPill key={t} text={t} color="#8B5CF6" />)}
        {b.minBeds ? <ByPill text={b.minBeds + "+ bd"} color="#F59E0B" /> : null}
        {b.condition && b.condition !== "any" ? <ByPill text={b.condition + " rehab"} color="#EC4899" /> : null}
      </div>
      {(b.phone || b.email) && (
        <div className="faint mono" style={{ fontSize: 11, display: "flex", gap: 12 }}>
          {b.phone && <span>{b.phone}</span>}{b.email && <span>{b.email}</span>}
        </div>
      )}
      {b.notes && <div className="faint" style={{ fontSize: 11.5, lineHeight: 1.4 }}>{b.notes}</div>}
      <div style={{ display: "flex", gap: 7, marginTop: 2 }}>
        <button className="tab" onClick={() => onEdit(b)} style={{ fontSize: 11.5, padding: "5px 11px" }}>Edit</button>
        <button className="tab" onClick={toggle} disabled={busy} style={{ fontSize: 11.5, padding: "5px 11px" }}>{b.active ? "Pause" : "Activate"}</button>
        <button className="tab" onClick={remove} disabled={busy} style={{ fontSize: 11.5, padding: "5px 11px", color: "var(--red)" }}>Remove</button>
      </div>
    </div>
  );
}

// ---- one match row inside a dispo deal -----------------------------------------
function MatchRow({ m, deal, assigned, onAssign }) {
  const isAssigned = assigned === m.buyerId;
  const c = byScoreColor(m.score, m.fits);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderTop: "1px solid var(--border)" }}>
      <div style={{ width: 34, textAlign: "center", flexShrink: 0 }}>
        <div style={{ fontWeight: 800, fontSize: 15, color: c }}>{m.score}</div>
        <div style={{ height: 3, borderRadius: 2, background: "var(--card-2)", marginTop: 2 }}>
          <div style={{ height: 3, borderRadius: 2, width: m.score + "%", background: c }} />
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 12.5, display: "flex", alignItems: "center", gap: 7 }}>
          {m.name || m.buyerId}
          {m.fits ? <ByPill text="fits" color="#22C55E" /> : <ByPill text="stretch" color="#64748B" />}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 3 }}>
          {(m.reasons || []).slice(0, 4).map((r, i) => (
            <span key={i} className="faint" style={{ fontSize: 10.5 }}>{i ? "· " : ""}{r}</span>
          ))}
        </div>
      </div>
      <button className="tab" onClick={() => onAssign(isAssigned ? "" : m.buyerId)}
        style={{ fontSize: 11.5, padding: "6px 12px", flexShrink: 0,
          background: isAssigned ? "#22C55E" : "var(--card-2)", color: isAssigned ? "#fff" : "var(--text)",
          border: "1px solid " + (isAssigned ? "transparent" : "var(--border)") }}>
        {isAssigned ? "✓ Assigned" : "Assign"}
      </button>
    </div>
  );
}

function DispoDeal({ row, onAssign }) {
  const d = row.deal;
  const price = d.offer || d.mao || d.purchasePrice || d.asking;
  return (
    <div className="card" style={{ padding: 13, display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 13 }}>{d.name || d.contactId}</div>
          <div className="faint" style={{ fontSize: 11.5 }}>{d.address || "address TBD"}</div>
        </div>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          {price ? <div style={{ fontWeight: 700, fontSize: 13, color: "#4F7CFF" }}>{window.fmtMoney(price)}</div> : null}
          <ByPill text={d.stage || "Offer"} color="#EC4899" />
        </div>
      </div>
      {row.assignedBuyerId && (
        <div style={{ fontSize: 11.5, color: "#22C55E", fontWeight: 600 }}>🤝 Assigned → {d.assignedBuyerName || row.assignedBuyerId}</div>
      )}
      {(row.matches || []).length ? (
        <div>{row.matches.map((m) => (
          <MatchRow key={m.buyerId} m={m} deal={d} assigned={row.assignedBuyerId}
            onAssign={(bid) => onAssign(d.contactId, bid, d.name)} />
        ))}</div>
      ) : (
        <div className="faint" style={{ fontSize: 11.5, paddingTop: 4 }}>No buyers in range — add a cash buyer for this area/price.</div>
      )}
    </div>
  );
}

// ---- the page ------------------------------------------------------------------
function BuyersPage() {
  const Icons = window.Icons;
  const { data: roster, refresh: refreshRoster } = window.useApi("/api/buyers/list", { interval: 0 });
  const { data: dispo, refresh: refreshDispo } = window.useApi("/api/buyers/dispo", { interval: 0 });
  const [adding, setAdding] = useStateBy(false);
  const [editing, setEditing] = useStateBy(null);

  const refreshAll = useCallbackBy(() => { refreshRoster(); refreshDispo(); }, [refreshRoster, refreshDispo]);
  const buyers = (roster && roster.buyers) || [];
  const dispoRows = (dispo && dispo.dispo) || [];

  async function assign(contactId, buyerId, name) {
    await window.apiPost("/api/buyers/assign", { contactId, buyerId, name });
    refreshDispo();
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontWeight: 800, fontSize: 20, letterSpacing: -0.4 }}>Dispositions · Cash Buyers</div>
          <div className="faint" style={{ fontSize: 12.5 }}>
            {buyers.length} buyer{buyers.length === 1 ? "" : "s"} · {dispoRows.length} deal{dispoRows.length === 1 ? "" : "s"} to place — the locked-contract endgame.
          </div>
        </div>
        {!adding && (
          <button className="btn-primary" onClick={() => { setEditing(null); setAdding(true); }}
            style={{ padding: "9px 16px", borderRadius: 8, border: "none", fontWeight: 600, fontSize: 12.5,
              background: "var(--accent, #4F7CFF)", color: "#fff", cursor: "pointer", display: "flex", alignItems: "center", gap: 7 }}>
            <Icons.Plus size={15} /> Add cash buyer
          </button>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.15fr 1fr", gap: 16, alignItems: "start" }}>
        {/* Dispo worklist — the action */}
        <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
          <div className="faint" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600 }}>Deals to place</div>
          {dispoRows.length ? dispoRows.map((row) => (
            <DispoDeal key={row.deal.contactId} row={row} onAssign={assign} />
          )) : (
            <div className="card" style={{ padding: 22, textAlign: "center" }}>
              <div className="faint" style={{ fontSize: 12.5 }}>No deals need a buyer yet.</div>
              <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>Deals appear here once they have an offer or contract. Build the buyer list now so matches are ready.</div>
            </div>
          )}
        </div>

        {/* Buyer roster — the management */}
        <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
          {(adding || editing) && (
            <BuyerForm seed={editing} onCancel={() => { setAdding(false); setEditing(null); }}
              onSaved={() => { setAdding(false); setEditing(null); refreshAll(); }} />
          )}
          <div className="faint" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600 }}>Buyer roster</div>
          {buyers.length ? buyers.map((b) => (
            <BuyerCard key={b.id} b={b} onChanged={refreshAll}
              onEdit={(bb) => { setAdding(false); setEditing(bb); }} />
          )) : !adding && (
            <div className="card" style={{ padding: 22, textAlign: "center" }}>
              <div className="faint" style={{ fontSize: 12.5 }}>No cash buyers yet.</div>
              <button className="tab" onClick={() => setAdding(true)} style={{ marginTop: 10 }}>Add your first buyer</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { BuyersPage });
