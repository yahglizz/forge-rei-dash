// FORGE Mobile — Actions tab: the owner's "TODAY — N ACTIONS" list (spec §23 / §15),
// phone lens of owner_actions.jsx. Reads GET /api/owner-actions every 60s. READ-ONLY:
// nothing is approved or sent from here — a row expands its "why" and, where the phone
// app has the screen, "Open" jumps there (approvals stay in their own screens).
// Hook aliases for this file: MOA. Exports: MActionsPage.
const { useState: useStateMOA, useRef: useRefMOA } = React;

const MOA_KIND = {
  CALL: "#EF4444", CALLBACK: "#F59E0B", APPROVE: "#4F7CFF", REVIEW: "#8B5CF6", FIX: "#DC2626",
};
const MOA_BIZ = {
  wholesale: { name: "Wholesale", c: "#4F7CFF" }, agency: { name: "Agency", c: "#8B5CF6" },
  daycare: { name: "Daycare", c: "#2DD4BF" }, system: { name: "System", c: "#64748B" },
};
const MOA_PRIO = { urgent: "#EF4444", revenue: "#22C55E", customer: "#F59E0B", normal: "#64748B" };
const MOA_CHIPS = [
  ["all", "All", null], ["CALL", "Call", ["CALL", "CALLBACK"]], ["APPROVE", "Approve", ["APPROVE"]],
  ["REVIEW", "Review", ["REVIEW"]], ["FIX", "Fix", ["FIX"]],
];

function moaAge(sec) {
  if (sec == null) return "";
  if (sec < 60) return "now";
  if (sec < 3600) return Math.floor(sec / 60) + "m";
  if (sec < 86400) return Math.floor(sec / 3600) + "h";
  return Math.floor(sec / 86400) + "d";
}

// Desktop link → what the phone can open. {thread} = in-page MCThread, {tab} = mGoTab.
// Daycare rows carry link.mobile (messages|families) → that daycare tab. Agency pages
// have no mobile screen → null (row just expands its why).
function moaTarget(link) {
  if (!link) return null;
  if (link.ws === "rei" && link.contactId) return { thread: { contactId: link.contactId, id: link.convId, name: link.name } };
  if (link.view === "health") return { tab: "more", label: "More → Health" };
  if (link.ws === "daycare" && link.mobile) return { tab: "daycare", seg: link.mobile, label: "Daycare → " + link.mobile[0].toUpperCase() + link.mobile.slice(1) };
  if (link.ws === "rei") {
    if (link.page === "Conversations") return { tab: "convos", label: "Convos" };
    if (link.page === "Leads" || link.page === "Agents") return { tab: "home", label: "Home" }; // hot leads + Marcus inbox
  }
  return null;
}

function MOARow(props) {
  const it = props.it;
  const [open, setOpen] = useStateMOA(false);
  const kc = MOA_KIND[it.kind] || MOA_KIND.REVIEW;
  const biz = MOA_BIZ[it.business] || { name: it.business || "—", c: "#64748B" };
  const stale = String(it.id || "").startsWith("stale:");
  const tgt = moaTarget(it.link);
  function go(e) {
    e.stopPropagation();
    if (tgt.thread) props.onThread(tgt.thread);
    else if (window.mGoTab) window.mGoTab(tgt.tab, tgt.seg);
  }
  return (
    <div className="m-list-item" onClick={() => setOpen(!open)}
      style={{ alignItems: "flex-start", cursor: "pointer", opacity: stale ? 0.55 : 1,
        borderColor: it.kind === "FIX" ? "rgba(239,68,68,0.35)" : undefined }}>
      <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: 0.4, color: "#fff", background: kc,
        padding: "3px 6px", borderRadius: 6, flex: "none", minWidth: 58, textAlign: "center", marginTop: 1 }}>
        {it.kind}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="m-row" style={{ gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: biz.c, background: biz.c + "22",
            padding: "1px 7px", borderRadius: 999, flex: "none" }}>{biz.name}</span>
          <span style={{ fontSize: 9.5, fontWeight: 700, color: MOA_PRIO[it.priority] || "#64748B",
            textTransform: "uppercase", letterSpacing: 0.3 }}>{it.priority}</span>
        </div>
        <div style={{ fontSize: 14, fontWeight: 650, lineHeight: 1.3, marginTop: 3 }}>{it.title}</div>
        {it.why && (
          <div className="m-fade" style={open
            ? { marginTop: 3, lineHeight: 1.4, overflowWrap: "break-word" }
            : { marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {it.why}
          </div>
        )}
        {open && tgt && (
          <window.MBtn kind="ghost" style={{ marginTop: 8, minHeight: 36, padding: "6px 12px", fontSize: 12.5 }}
            onClick={go}>
            Open {tgt.thread ? "thread" : tgt.label} →
          </window.MBtn>
        )}
        {open && !tgt && (
          <div className="m-fade" style={{ marginTop: 6, fontSize: 11 }}>Handle this on the desktop dashboard.</div>
        )}
      </div>
      <span className="m-fade" style={{ fontSize: 11, flex: "none", marginTop: 2 }}>{moaAge(it.ageSec)}</span>
    </div>
  );
}

function MActionsPage() {
  const { data, error, loading, refresh } = window.useApiM("/api/owner-actions", { interval: 60000 });
  const [chip, setChip] = useStateMOA("all");
  const [thread, setThread] = useStateMOA(null);
  // useApiM stores an {error} payload as data too — keep the last GOOD list so a failed
  // refresh never renders as "0 actions".
  const goodRef = useRefMOA(null);
  if (data && !data.error && Array.isArray(data.items)) goodRef.current = data;
  const good = goodRef.current;
  const items = (good && good.items) || [];
  const def = MOA_CHIPS.find((c) => c[0] === chip) || MOA_CHIPS[0];
  const shown = def[2] ? items.filter((i) => def[2].includes(i.kind)) : items;
  const countFor = (kinds) => (kinds ? items.filter((i) => kinds.includes(i.kind)).length : items.length);
  const RefreshIco = window.MIcons.Refresh;

  return (
    <React.Fragment>
      <window.MHeader title={"Today — " + (good ? items.length : "…") + " action" + (items.length === 1 ? "" : "s")}
        sub="Call · Approve · Review · Fix — every business"
        right={<button className="m-tab" style={{ flex: "none", padding: 6 }} onClick={refresh}><RefreshIco size={20} /></button>} />
      <div className="m-content">
        <div className="m-seg">
          {MOA_CHIPS.map(([id, label, kinds]) => (
            <window.MChip key={id} active={chip === id} onClick={() => setChip(id)}>
              {label}{good ? " " + countFor(kinds) : ""}
            </window.MChip>
          ))}
        </div>

        {error && (
          <div className="m-card" style={{ borderColor: "rgba(239,68,68,0.35)" }}>
            <div style={{ color: "var(--red, #EF4444)", fontSize: 13, fontWeight: 700 }}>
              {good ? "Refresh failed — list may be stale" : "Owner actions unavailable"}
            </div>
            <div className="m-fade" style={{ marginTop: 4, overflowWrap: "break-word" }}>{String(error)}</div>
            <window.MBtn kind="ghost" style={{ marginTop: 10, width: "100%" }} onClick={refresh}>Retry</window.MBtn>
          </div>
        )}

        {loading && !good && !error && <window.MSpin />}

        {good && shown.length === 0 && (
          <window.MEmpty title={items.length === 0 ? "Nothing needs you right now." : "Nothing in this filter."} />
        )}
        {shown.map((it) => <MOARow key={it.id} it={it} onThread={setThread} />)}
      </div>
      {thread && <window.MCThread convo={thread} onClose={() => setThread(null)} />}
    </React.Fragment>
  );
}

Object.assign(window, { MActionsPage });
