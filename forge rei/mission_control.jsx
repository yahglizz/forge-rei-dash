// mission_control.jsx — the FRONT DOOR. One screen that reviews every business at
// once: is it running, what's off, and a one-click jump into the exact spot to fix
// it. Reads /api/mission-control (mission_control.py) every 30s. Selecting a business
// from the dropdown (or a card's Open button) drops you into that workspace.
// Additive, window-global, unique MC* names + useStateMC alias.
const { useState: useStateMC } = React;

const MC_COLOR = { ok: "#22C55E", warn: "#F59E0B", down: "#EF4444", idle: "#64748B", unknown: "#64748B" };
const MC_SEV = { down: "#EF4444", warn: "#F59E0B", info: "#4F7CFF" };

function McDot({ status, size = 11 }) {
  const c = MC_COLOR[status] || MC_COLOR.unknown;
  return <span style={{
    width: size, height: size, borderRadius: "50%", background: c, display: "inline-block",
    flexShrink: 0, boxShadow: status === "down" ? "0 0 0 4px rgba(239,68,68,.16)" : "none",
  }} />;
}

function McMetric({ m, onEnter }) {
  const clickable = m.jump && onEnter;
  return (
    <button
      onClick={() => clickable && onEnter(m.jump.ws, m.jump.page)}
      style={{
        flex: "1 1 0", minWidth: 78, textAlign: "left", padding: "9px 11px",
        borderRadius: 11, background: "var(--card-2)", border: "1px solid transparent",
        cursor: clickable ? "pointer" : "default",
      }}>
      <div className="tabnum" style={{ fontSize: 17, fontWeight: 700 }}>{m.value}</div>
      <div className="faint" style={{ fontSize: 10.5, marginTop: 1, whiteSpace: "nowrap",
        overflow: "hidden", textOverflow: "ellipsis" }}>{m.label}</div>
    </button>
  );
}

function McAttention({ a, onEnter }) {
  const c = MC_SEV[a.sev] || MC_SEV.info;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "7px 0",
      borderTop: "1px solid var(--card-2)" }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: c, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0, fontSize: 12.5, lineHeight: 1.35 }}>{a.text}</div>
      {a.jump && (
        <button className="tab" style={{ fontSize: 11, padding: "3px 9px", flexShrink: 0 }}
          onClick={() => onEnter(a.jump.ws, a.jump.page)}>Jump →</button>
      )}
    </div>
  );
}

function McCard({ card, onEnter }) {
  const accent = card.accent || "#4F7CFF";
  const status = card.status || "unknown";
  return (
    <div className="card card-pad" style={{
      display: "flex", flexDirection: "column", gap: 12,
      borderColor: status === "down" ? "var(--red)" : "var(--card-2)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <div style={{ width: 40, height: 40, borderRadius: 11, flexShrink: 0,
          background: "radial-gradient(circle at 40% 35%, " + accent + ", #16224a)",
          display: "grid", placeItems: "center" }}>
          <window.Logo accent="#fff" />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{card.name}</div>
          <div className="faint" style={{ fontSize: 11.5 }}>{card.tag}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <McDot status={status} />
          <span style={{ fontSize: 11.5, fontWeight: 600, color: MC_COLOR[status] }}>{card.statusLabel}</span>
        </div>
      </div>

      {card.metrics && card.metrics.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {card.metrics.map((m, i) => <McMetric key={i} m={m} onEnter={onEnter} />)}
        </div>
      )}

      {card.attention && card.attention.length > 0 ? (
        <div>{card.attention.map((a, i) => <McAttention key={i} a={a} onEnter={onEnter} />)}</div>
      ) : (
        <div className="faint" style={{ fontSize: 12, padding: "6px 0", borderTop: "1px solid var(--card-2)" }}>
          Nothing needs you here right now.
        </div>
      )}

      <button
        onClick={() => onEnter(card.id, (card.jump && card.jump.page) || "Dashboard")}
        style={{ marginTop: "auto", width: "100%", padding: "10px", borderRadius: 11,
          background: accent, color: "#fff", fontWeight: 600, fontSize: 13.5, cursor: "pointer" }}>
        Open {card.name} →
      </button>
    </div>
  );
}

function McSystemStrip({ sys, onEnter }) {
  if (!sys) return null;
  const stat = (n, label, color) => (
    <div style={{ textAlign: "center", minWidth: 62 }}>
      <div className="tabnum" style={{ fontSize: 18, fontWeight: 700, color: color || "var(--text)" }}>{n}</div>
      <div className="faint" style={{ fontSize: 10.5 }}>{label}</div>
    </div>
  );
  return (
    <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, flex: 1, minWidth: 160 }}>
        <span style={{ color: sys.active ? (sys.ok ? MC_COLOR.ok : MC_COLOR.down) : MC_COLOR.idle }}>
          <window.Icons.Activity size={18} />
        </span>
        <div>
          <div style={{ fontWeight: 600, fontSize: 13.5 }}>System &amp; background loops</div>
          <div className="faint" style={{ fontSize: 11 }}>
            {sys.active ? "Fleet running" : (sys.loopsEnabled ? "Crew clocked out" : "UI-only (loops off)")}
            {" · "}{sys.loopsTotal || 0} monitored
          </div>
        </div>
      </div>
      {stat(sys.loopsHealthy || 0, "Healthy", MC_COLOR.ok)}
      {stat(sys.loopsDown || 0, "Down", sys.loopsDown ? MC_COLOR.down : null)}
      {stat(sys.loopsStale || 0, "Stale", sys.loopsStale ? MC_COLOR.warn : null)}
      {stat(sys.diskPct != null ? sys.diskPct + "%" : "—", "Disk", sys.diskPct >= 92 ? MC_COLOR.down : null)}
      <button className="tab" onClick={() => onEnter((sys.jump && sys.jump.ws) || "rei", (sys.jump && sys.jump.page) || "SystemHealth")}>
        System Health →
      </button>
    </div>
  );
}

// ---- Monthly Spend: the operator's OWN subscriptions/bills, grouped by business. ----
// Backed by /api/spend/status (spend_tracker.py). Every row is inline-editable; you keep
// the numbers current, the dashboard keeps the running monthly/yearly total.
function mcUSD(n) {
  return "$" + Number(n || 0).toLocaleString(undefined,
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function McSpendRow({ item, onSaved, onEnter }) {
  const [amount, setAmount] = useStateMC(String(item.amount != null ? item.amount : ""));
  const [cadence, setCadence] = useStateMC(item.cadence || "monthly");
  const [busy, setBusy] = useStateMC(false);
  const dirty = String(item.amount) !== amount.trim() || (item.cadence || "monthly") !== cadence;

  async function save(nextCadence) {
    const cad = nextCadence || cadence;
    setBusy(true);
    try {
      await window.apiPost("/api/spend/save",
        { id: item.id, amount: parseFloat(amount) || 0, cadence: cad });
      onSaved();
    } catch (e) { /* transient — the next refresh reconciles */ }
    setBusy(false);
  }
  async function remove() {
    setBusy(true);
    try { await window.apiPost("/api/spend/delete", { id: item.id }); onSaved(); }
    catch (e) { /* ignore */ }
    setBusy(false);
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0",
      borderTop: "1px solid var(--card-2)", opacity: busy ? 0.55 : 1 }}>
      <div style={{ flex: 1, minWidth: 0, fontSize: 12.5, whiteSpace: "nowrap",
        overflow: "hidden", textOverflow: "ellipsis" }}>{item.name}</div>
      <span className="faint" style={{ fontSize: 12 }}>$</span>
      <input value={amount} inputMode="decimal" placeholder="0.00"
        onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))}
        onBlur={() => dirty && save()}
        onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); }}
        style={{ width: 66, textAlign: "right", fontSize: 12.5, padding: "4px 6px",
          borderRadius: 8, background: "var(--card-2)", border: "1px solid transparent",
          color: "var(--text)" }} className="tabnum" />
      <select value={cadence} onChange={(e) => { setCadence(e.target.value); save(e.target.value); }}
        style={{ fontSize: 11.5, padding: "4px 4px", borderRadius: 8,
          background: "var(--card-2)", border: "1px solid transparent", color: "var(--text)" }}>
        <option value="monthly">/mo</option>
        <option value="yearly">/yr</option>
      </select>
      <button onClick={remove} title="Remove" className="faint"
        style={{ fontSize: 15, lineHeight: 1, padding: "0 4px", cursor: "pointer" }}>×</button>
    </div>
  );
}

function McSpendGroup({ group, onSaved }) {
  const [adding, setAdding] = useStateMC(false);
  const [name, setName] = useStateMC("");
  const [amount, setAmount] = useStateMC("");

  async function add() {
    if (!name.trim()) { setAdding(false); return; }
    try {
      await window.apiPost("/api/spend/save",
        { name: name.trim(), amount: parseFloat(amount) || 0, business: group.id });
      setName(""); setAmount(""); setAdding(false); onSaved();
    } catch (e) { /* ignore */ }
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
        <span style={{ width: 9, height: 9, borderRadius: "50%", background: group.color,
          display: "inline-block", flexShrink: 0, alignSelf: "center" }} />
        <div style={{ fontWeight: 700, fontSize: 13.5, flex: 1 }}>{group.label}</div>
        <div className="tabnum" style={{ fontWeight: 700, fontSize: 13.5 }}>{mcUSD(group.monthlyUSD)}</div>
        <span className="faint" style={{ fontSize: 10.5 }}>/mo</span>
      </div>

      {group.items.length === 0 && !adding && (
        <div className="faint" style={{ fontSize: 12, padding: "5px 0" }}>Nothing here yet.</div>
      )}
      {group.items.map((it) => <McSpendRow key={it.id} item={it} onSaved={onSaved} />)}

      {adding ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 0 2px",
          borderTop: "1px solid var(--card-2)" }}>
          <input autoFocus value={name} placeholder="What is it? (e.g. Metricool)"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") add(); if (e.key === "Escape") setAdding(false); }}
            style={{ flex: 1, minWidth: 0, fontSize: 12.5, padding: "5px 8px", borderRadius: 8,
              background: "var(--card-2)", border: "1px solid transparent", color: "var(--text)" }} />
          <input value={amount} inputMode="decimal" placeholder="0.00"
            onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))}
            onKeyDown={(e) => { if (e.key === "Enter") add(); if (e.key === "Escape") setAdding(false); }}
            style={{ width: 66, textAlign: "right", fontSize: 12.5, padding: "5px 6px", borderRadius: 8,
              background: "var(--card-2)", border: "1px solid transparent", color: "var(--text)" }}
            className="tabnum" />
          <button className="tab" style={{ fontSize: 11.5, padding: "5px 10px" }} onClick={add}>Add</button>
        </div>
      ) : (
        <button onClick={() => setAdding(true)} className="faint"
          style={{ textAlign: "left", fontSize: 12, padding: "6px 0 2px", cursor: "pointer",
            borderTop: "1px solid var(--card-2)", marginTop: 2 }}>+ Add subscription</button>
      )}
    </div>
  );
}

function McSpend() {
  const { data, error, loading, refresh } = window.useApi("/api/spend/status");
  const d = data || {};
  const groups = d.groups || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Monthly Spend</div>
          <div className="faint" style={{ fontSize: 11.5 }}>
            What you pay to run everything — edit any number to keep it current
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="tabnum" style={{ fontSize: 22, fontWeight: 700 }}>{mcUSD(d.monthlyUSD)}</div>
          <div className="faint" style={{ fontSize: 11 }}>{mcUSD(d.yearlyUSD)} / year</div>
        </div>
      </div>

      {loading && !data && <window.LoadingRow label="Loading your subscriptions…" />}
      {error && !data && <window.ErrorRow error={error} onRetry={refresh} />}

      {data && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 14 }}>
          {groups.map((g) => <McSpendGroup key={g.id} group={g} onSaved={refresh} />)}
        </div>
      )}
    </div>
  );
}

function MissionControl({ onEnter, workspaces = [] }) {
  const Icons = window.Icons;
  const [menu, setMenu] = useStateMC(false);
  const { data, error, loading, refresh, refreshedAt } = window.useApi(
    "/api/mission-control", { interval: 30000 });

  const d = data || {};
  const cards = d.businesses || [];
  const vColor = MC_COLOR[d.verdictStatus] || MC_COLOR.idle;

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)", padding: "26px clamp(16px, 4vw, 52px) 60px" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>

        {/* Top bar */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flex: 1, minWidth: 200 }}>
            <div style={{ width: 44, height: 44, borderRadius: 12, display: "grid", placeItems: "center",
              background: "radial-gradient(circle at 40% 35%, #4F7CFF, #16224a)" }}>
              <window.Logo accent="#fff" />
            </div>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: -0.3 }}>Mission Control</div>
              <div className="faint" style={{ fontSize: 12.5 }}>Every business, one screen</div>
            </div>
          </div>

          <div style={{ position: "relative" }}>
            <button className="tab" style={{ padding: "9px 15px", fontSize: 13, fontWeight: 600,
              display: "flex", alignItems: "center", gap: 8 }} onClick={() => setMenu((m) => !m)}>
              Jump to a business <Icons.Chevron size={15} />
            </button>
            {menu && (
              <>
                <div onClick={() => setMenu(false)} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
                <div className="card" style={{ position: "absolute", right: 0, top: "calc(100% + 8px)",
                  width: 250, padding: 8, zIndex: 50, borderRadius: 14 }}>
                  {workspaces.map((w) => (
                    <button key={w.id} onClick={() => { setMenu(false); onEnter(w.id); }}
                      style={{ display: "flex", alignItems: "center", gap: 11, width: "100%",
                        padding: "9px 8px", borderRadius: 10, textAlign: "left", cursor: "pointer" }}>
                      <div style={{ width: 30, height: 30, borderRadius: 8, flexShrink: 0,
                        background: "radial-gradient(circle at 40% 35%, " + w.accent + ", #16224a)",
                        display: "grid", placeItems: "center" }}>
                        <window.Logo accent="#fff" />
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>{w.brand} {w.sub}</div>
                        <div className="faint" style={{ fontSize: 11 }}>{w.tag}</div>
                      </div>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          <button className="tab" onClick={refresh} style={{ padding: "9px 13px" }}>Refresh</button>
        </div>

        {loading && !data && <window.LoadingRow label="Reading the whole operation…" />}
        {error && !data && <window.ErrorRow error={error} onRetry={refresh} />}

        {data && (
          <>
            {/* Verdict banner */}
            <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 15,
              borderColor: d.verdictStatus === "down" ? "var(--red)" : "var(--card-2)" }}>
              <McDot status={d.verdictStatus} size={16} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: vColor }}>{d.verdict}</div>
                <div className="faint" style={{ fontSize: 12 }}>
                  {d.attentionCount ? (d.attentionCount + " item" + (d.attentionCount !== 1 ? "s" : "") + " want your attention")
                    : "Nothing flagged — you're clear"}
                  {refreshedAt ? " · updated " + window.timeAgo(refreshedAt) : ""}
                </div>
              </div>
            </div>

            {/* System / loops */}
            <McSystemStrip sys={d.system} onEnter={onEnter} />

            {/* Business cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 14 }}>
              {cards.map((c) => <McCard key={c.id} card={c} onEnter={onEnter} />)}
            </div>

            {/* Monthly spend — the operator's own subscriptions, grouped by business */}
            <McSpend />

            <div className="faint" style={{ fontSize: 11, textAlign: "right" }}>
              auto-refreshes every 30s — pick a business above or open one below to dive in
            </div>
          </>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { MissionControl });
