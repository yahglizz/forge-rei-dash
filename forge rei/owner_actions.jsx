// owner_actions.jsx — "TODAY — N ACTIONS": the one list the owner works from (spec §15).
// Reads /api/owner-actions (owner_actions.py) every 60s. Read-only: every row is a deep
// link into the tab that owns the action — nothing is approved or sent from here.
// Additive, window-global, unique Oa* names + useStateOa alias.
const { useState: useStateOa } = React;

const OA_KIND = {
  CALL: "#EF4444", CALLBACK: "#F59E0B", APPROVE: "#4F7CFF", REVIEW: "#8B5CF6", FIX: "#DC2626",
};
const OA_BIZ = {
  wholesale: { name: "Wholesale", c: "#4F7CFF" }, agency: { name: "Agency", c: "#8B5CF6" },
  daycare: { name: "Daycare", c: "#2DD4BF" }, system: { name: "System", c: "#64748B" },
};
const OA_PRIO = { urgent: "#EF4444", revenue: "#22C55E", customer: "#F59E0B", normal: "#64748B" };
// Chip → which kinds it shows. "Approve" is the spec's Approvals-queue view.
const OA_CHIPS = [
  ["all", "All", null], ["CALL", "Call", ["CALL", "CALLBACK"]], ["APPROVE", "Approve", ["APPROVE"]],
  ["REVIEW", "Review", ["REVIEW"]], ["FIX", "Fix", ["FIX"]],
];

function oaAge(sec) {
  if (sec == null) return "";
  if (sec < 60) return "now";
  if (sec < 3600) return Math.floor(sec / 60) + "m";
  if (sec < 86400) return Math.floor(sec / 3600) + "h";
  return Math.floor(sec / 86400) + "d";
}

function oaOpen(link) {
  if (!link) return;
  if (link.view) { if (window.forgeOpenView) window.forgeOpenView(link.view); return; }
  if (link.ws && window.forgeEnterBusiness) window.forgeEnterBusiness(link.ws, link.page);
}

function OaRow({ it }) {
  const kc = OA_KIND[it.kind] || OA_KIND.REVIEW;
  const biz = OA_BIZ[it.business] || { name: it.business || "—", c: "#64748B" };
  const canOpen = it.link && (it.link.view ? !!window.forgeOpenView : !!window.forgeEnterBusiness);
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "9px 0",
      borderTop: "1px solid var(--card-2)" }}>
      <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: .4, color: "#fff", background: kc,
        padding: "3px 7px", borderRadius: 6, flexShrink: 0, minWidth: 58, textAlign: "center", marginTop: 1 }}>
        {it.kind === "FIX" ? "FIX" : it.kind}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: biz.c, background: biz.c + "22",
            padding: "1px 7px", borderRadius: 999, flexShrink: 0 }}>{biz.name}</span>
          <span style={{ fontSize: 13.5, fontWeight: 650, lineHeight: 1.3 }}>{it.title}</span>
          <span style={{ fontSize: 9.5, fontWeight: 700, color: OA_PRIO[it.priority] || "#64748B",
            textTransform: "uppercase", letterSpacing: .3 }}>{it.priority}</span>
        </div>
        {it.why && <div className="faint" style={{ fontSize: 12, marginTop: 2, lineHeight: 1.4,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.why}</div>}
      </div>
      <span className="faint tabnum" style={{ fontSize: 11, flexShrink: 0, marginTop: 3, minWidth: 24, textAlign: "right" }}>
        {oaAge(it.ageSec)}
      </span>
      {canOpen && (
        <button className="tab" style={{ fontSize: 11, padding: "3px 9px", flexShrink: 0 }}
          onClick={() => oaOpen(it.link)}>Open →</button>
      )}
    </div>
  );
}

function OwnerActionsCard() {
  const { data, error, loading, refresh, refreshedAt } = window.useApi("/api/owner-actions", { interval: 60000 });
  const [chip, setChip] = useStateOa("all");
  const items = (data && data.items) || [];
  const def = OA_CHIPS.find((c) => c[0] === chip) || OA_CHIPS[0];
  const shown = def[2] ? items.filter((i) => def[2].includes(i.kind)) : items;
  const countFor = (kinds) => (kinds ? items.filter((i) => kinds.includes(i.kind)).length : items.length);

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 10,
      borderColor: items.some((i) => i.kind === "FIX") ? "var(--red)" : "var(--card-2)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: .2 }}>
            TODAY — {data ? items.length : "…"} ACTION{items.length === 1 ? "" : "S"}
          </div>
          <div className="faint" style={{ fontSize: 11.5 }}>
            Call · Approve · Review · Fix — every business, sorted urgent → revenue → customer
            {refreshedAt ? " · updated " + window.timeAgo(refreshedAt) : ""}
          </div>
        </div>
        <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
          {OA_CHIPS.map(([id, label, kinds]) => (
            <button key={id} className="tab" onClick={() => setChip(id)}
              style={{ fontSize: 11.5, padding: "4px 10px",
                background: chip === id ? "var(--accent, #4F7CFF)" : "var(--card-2)",
                color: chip === id ? "#fff" : "var(--text)" }}>
              {label} {data ? countFor(kinds) : ""}
            </button>
          ))}
          <button className="tab" onClick={refresh} style={{ fontSize: 11.5, padding: "4px 10px" }}>↻</button>
        </div>
      </div>

      {/* An error is ALWAYS visible — never rendered as "0 actions". */}
      {error && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 9,
          background: "rgba(239,68,68,.10)", border: "1px solid var(--red)" }}>
          <span style={{ color: "var(--red)", fontWeight: 700, fontSize: 12 }}>
            {data ? "Refresh failed — list may be stale" : "Owner actions unavailable"}
          </span>
          <span className="faint mono" style={{ fontSize: 11.5, flex: 1, minWidth: 0, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{error}</span>
          <button className="tab" style={{ fontSize: 11, padding: "3px 9px" }} onClick={refresh}>Retry</button>
        </div>
      )}

      {loading && !data && !error && <div className="faint" style={{ fontSize: 12.5 }}>Reading every queue…</div>}

      {data && shown.length === 0 && (
        <div className="faint" style={{ fontSize: 12.5, padding: "6px 0", borderTop: "1px solid var(--card-2)" }}>
          {items.length === 0 ? "Nothing needs you right now." : "Nothing in this filter."}
        </div>
      )}
      {shown.length > 0 && <div>{shown.map((it) => <OaRow key={it.id} it={it} />)}</div>}
    </div>
  );
}

Object.assign(window, { OwnerActionsCard });
