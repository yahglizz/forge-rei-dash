// FORGE Mobile — Home tab (Command Center). Approvals-first operator console:
// KPI row (/api/dashboard + /api/scout/summary), Marcus approval inbox
// (/api/marcus/proposals + approve/dismiss), Scout hot leads (/api/scout/leads
// + handoff), and the agent time-clock pill (/api/ops/status + /api/ops/set).
// Hook aliases for this file: MH. Exports: MHomePage.
const { useState: useStateMH, useEffect: useEffectMH, useRef: useRefMH, useMemo: useMemoMH } = React;

// Icons resolved once (m_shell.jsx loads before this file; computed JSX tags are banned).
const MHFlameIco = window.MIcons.Flame;
const MHCheckIco = window.MIcons.Check;
const MHXIco = window.MIcons.X;
const MHSendIco = window.MIcons.Send;
const MHPauseIco = window.MIcons.Pause;
const MHPlayIco = window.MIcons.Play;
const MHChatIco = window.MIcons.Chat;
const MHBoardIco = window.MIcons.Board;
const MHDollarIco = window.MIcons.Dollar;

const MH_CLS_COLOR = {
  READY: "#22C55E", PRICE: "#F59E0B", NRN: "#8B5CF6",
  HELP: "#EF4444", CONTINUE: "#4F7CFF", DNC: "#64748B",
};
const MH_BUCKET_COLOR = { asap: "#EF4444", warm: "#F59E0B", nurture: "#4F7CFF", dead: "#64748B" };
const MH_BUCKET_LABEL = { asap: "HOT", warm: "WARM", nurture: "NURTURE", dead: "DEAD" };
const MH_BUCKET_CHIPS = [["all", "All"], ["asap", "Hot"], ["warm", "Warm"], ["nurture", "Nurture"]];
const MH_ELLIPSIS = { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };

function MHSnip(t, n) {
  const s = String(t || "").replace(/\s+/g, " ").trim();
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

// Phone-width money: $1.2M / $85k / $4,200 — the full fmtMoneyM overflows a KPI tile.
function MHMoneyShort(n) {
  const x = Number(n);
  if (n === null || n === undefined || isNaN(x)) return "—";
  if (Math.abs(x) >= 1e6) return "$" + (x / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (Math.abs(x) >= 1e4) return "$" + Math.round(x / 1e3) + "k";
  return window.fmtMoneyM(x);
}

// --- Agent time-clock pill (header right) ----------------------------------
function MHOpsPill(props) {
  const ops = props.ops;
  const [flipBusy, setFlipBusy] = useStateMH(false);
  const d = ops.data || {};
  const paused = !!d.paused;

  if (ops.loading && !ops.data) return <span className="m-fade" style={{ padding: "0 6px" }}>…</span>;
  if (ops.error && !ops.data) return <span className="m-fade" style={{ color: "#EF4444", padding: "0 6px" }}>ops?</span>;

  const flip = async () => {
    const crew = (d.crew || []).join(", ") || "the agents";
    const msg = paused
      ? ("Clock agents back IN? " + crew + " resume autonomous work — sweeping, scoring, screening, prepping.")
      : ("Clock agents OUT? " + crew + " stand down; nothing autonomous runs until you clock back in. Your own taps still work.");
    if (!window.confirm(msg)) return;
    setFlipBusy(true);
    try { await window.apiPostM("/api/ops/set", { paused: !paused }); }
    catch (e) { window.alert("Ops clock: " + e.message); }
    setFlipBusy(false);
    ops.refresh();
  };

  const col = paused ? "#EF4444" : "#22C55E";
  const StateIco = paused ? MHPlayIco : MHPauseIco; // shows the action a tap takes
  return (
    <button onClick={flip} disabled={flipBusy}
      style={{
        display: "flex", alignItems: "center", gap: 6, minHeight: 44,
        padding: "8px 12px", borderRadius: 999, cursor: "pointer",
        background: paused ? "rgba(239,68,68,0.12)" : "rgba(34,197,94,0.12)",
        border: "1px solid " + (paused ? "rgba(239,68,68,0.35)" : "rgba(34,197,94,0.35)"),
        color: col, fontFamily: "inherit", fontSize: 11.5, fontWeight: 800,
        letterSpacing: "0.3px", opacity: flipBusy ? 0.6 : 1, flex: "none",
      }}>
      <StateIco size={13} />
      {flipBusy ? "…" : (paused ? "CLOCKED OUT" : "ON DUTY")}
    </button>
  );
}

// --- Snapshot stat grid -----------------------------------------------------
// 2×2 tiles — the glanceable metrics get real visual weight (accent icon chip
// + big value), instead of a cramped flat 4-across row.
const MH_STATS = [
  { key: "hot", label: "Hot leads", color: "#EF4444", Ico: MHFlameIco },
  { key: "replies", label: "Replies waiting", color: "#F59E0B", Ico: MHChatIco },
  { key: "pipe", label: "Pipeline", color: "#22C55E", Ico: MHDollarIco },
  { key: "opps", label: "Open opps", color: "#4F7CFF", Ico: MHBoardIco },
];

function MHStat(props) {
  const Ico = props.Ico;
  return (
    <div className={"m-stat" + (props.onTap ? " tappable" : "")}
      onClick={props.onTap || undefined} role={props.onTap ? "button" : undefined}>
      <div className="m-row" style={{ alignItems: "flex-start" }}>
        <div className="m-stat-ico" style={{ background: props.color + "1f", color: props.color }}>
          <Ico size={16} />
        </div>
        {props.onTap && (
          <span style={{ marginLeft: "auto", color: "var(--text-3, #64748B)",
            fontSize: 16, fontWeight: 700, lineHeight: 1 }}>›</span>
        )}
      </div>
      <div className="m-stat-v" style={{ color: props.color }}>{props.value}</div>
      <div className="m-stat-l">{props.label}</div>
    </div>
  );
}

function MHKpis(props) {
  const dd = props.dash.data;
  const sd = props.scout.data;
  const vals = {
    hot: sd && sd.counts ? (sd.counts.asap || 0) : "—",
    replies: dd ? (dd.activeConversations || 0) : "—",
    pipe: dd ? MHMoneyShort(dd.pipelineValue) : "—",
    opps: dd ? (dd.openOpportunities || 0) : "—",
  };
  const taps = props.onTapStat || {};
  return (
    <div>
      <div className="m-stat-grid">
        {MH_STATS.map((s) => (
          <MHStat key={s.key} label={s.label} color={s.color} Ico={s.Ico} value={vals[s.key]}
            onTap={taps[s.key]} />
        ))}
      </div>
      {props.dash.error && !dd && (
        <div className="m-fade" style={{ textAlign: "center", marginTop: 8 }}>Dashboard: {props.dash.error}</div>
      )}
      {props.scout.error && !sd && (
        <div className="m-fade" style={{ textAlign: "center", marginTop: 6 }}>Scout: {props.scout.error}</div>
      )}
    </div>
  );
}

// --- Section header ----------------------------------------------------------
// Quiet uppercase label + optional count pill → zones the page so the eye lands.
function MHSection(props) {
  const hasCount = props.count != null && props.count !== "" && props.count !== 0;
  const accent = props.accent || "#9FB0C7";
  return (
    <div className="m-section">
      <span className="m-section-l">{props.label}</span>
      {hasCount && (
        <span className="m-section-count"
          style={{ color: accent, background: accent + "1f", border: "1px solid " + accent + "4d" }}>
          {props.count}
        </span>
      )}
      <span className="m-section-line" />
    </div>
  );
}

// --- Marcus approval inbox ----------------------------------------------------
function MHApprovals(props) {
  const feed = props.feed;
  const [actBusy, setActBusy] = useStateMH(null);
  const list = (feed.data && feed.data.proposals) || [];

  async function act(kind, p) {
    const q = kind === "approve"
      ? ("Send Marcus's draft to " + p.name + "? This texts the seller.")
      : ("Dismiss the drafted reply for " + p.name + "?");
    if (!window.confirm(q)) return;
    setActBusy(kind + p.id);
    try {
      if (kind === "approve") {
        await window.apiPostM("/api/marcus/approve", { id: p.id, message: p.suggestedReply });
      } else {
        await window.apiPostM("/api/marcus/dismiss", { id: p.id });
      }
    } catch (e) { window.alert("Marcus: " + e.message); }
    setActBusy(null);
    feed.refresh();
  }

  let body;
  if (feed.loading && !feed.data) {
    body = <window.MSpin />;
  } else if (feed.error && !list.length) {
    body = <div className="m-fade" style={{ padding: "6px 0" }}>Couldn't load approvals: {feed.error}</div>;
  } else if (!list.length) {
    body = <window.MEmpty title="Inbox zero" sub="No drafted replies waiting on your approval" />;
  } else {
    const shown = list.slice(0, 6);
    body = (
      <div>
        {shown.map((p, i) => {
          const cc = MH_CLS_COLOR[p.classification] || "#9FB0C7";
          const aKey = "approve" + p.id;
          const dKey = "dismiss" + p.id;
          return (
            <div key={p.id} style={{ padding: "10px 0", borderTop: i ? "1px solid rgba(255,255,255,0.06)" : "none" }}>
              <div className="m-row" style={{ gap: 8 }}>
                <span style={{ ...MH_ELLIPSIS, fontSize: 13.5, fontWeight: 700, flex: 1, minWidth: 0 }}>{p.name}</span>
                <span style={{ fontSize: 10, fontWeight: 800, color: cc, letterSpacing: "0.4px", flex: "none" }}>{p.classification}</span>
                <span className="m-fade" style={{ fontSize: 11, flex: "none" }}>{window.timeAgoM(p.ts)}</span>
              </div>
              {p.inbound && (
                <div className="m-fade" style={{ marginTop: 4, ...MH_ELLIPSIS }}>They said: “{MHSnip(p.inbound, 90)}”</div>
              )}
              <div style={{
                marginTop: 6, padding: "8px 11px", borderRadius: 10,
                background: "var(--card-2, #17203a)", fontSize: 13, lineHeight: 1.45,
              }}>
                {MHSnip(p.suggestedReply, 220)}
              </div>
              <div className="m-row" style={{ marginTop: 8 }}>
                <window.MBtn kind="ok" style={{ flex: 1 }} disabled={actBusy === aKey}
                  onClick={() => act("approve", p)}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <MHCheckIco size={15} />{actBusy === aKey ? "Sending…" : "Approve"}
                  </span>
                </window.MBtn>
                <window.MBtn kind="no" style={{ flex: 1 }} disabled={actBusy === dKey}
                  onClick={() => act("dismiss", p)}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <MHXIco size={15} />{actBusy === dKey ? "…" : "Dismiss"}
                  </span>
                </window.MBtn>
              </div>
            </div>
          );
        })}
        {list.length > shown.length && (
          <div className="m-fade" style={{ textAlign: "center", paddingTop: 8 }}>
            +{list.length - shown.length} more waiting in the Agents tab
          </div>
        )}
      </div>
    );
  }

  return <window.MCard>{body}</window.MCard>;
}

// --- Scout hot leads ----------------------------------------------------------
function MHHotLeads(props) {
  const [bucket, setBucket] = useStateMH("all");
  const path = "/api/scout/leads" + (bucket === "all" ? "" : "?bucket=" + bucket);
  const feed = window.useApiM(path, { interval: 30000 });
  const [handed, setHanded] = useStateMH({});
  const leads = (feed.data && feed.data.leads) || [];

  async function handoff(l) {
    if (!window.confirm("Hand " + l.name + " to Marcus? He screens the lead and drafts a reply into your approval inbox.")) return;
    setHanded((h) => ({ ...h, [l.id]: "busy" }));
    try {
      await window.apiPostM("/api/scout/handoff", { id: l.id });
      setHanded((h) => ({ ...h, [l.id]: "done" }));
      feed.refresh();
      if (props.onHandoff) props.onHandoff(); // pull the new draft into the approvals card
    } catch (e) {
      setHanded((h) => ({ ...h, [l.id]: null }));
      window.alert("Handoff: " + e.message);
    }
  }

  let body;
  if (feed.loading && !feed.data) {
    body = <window.MSpin />;
  } else if (feed.error && !leads.length) {
    body = <div className="m-fade" style={{ padding: "6px 0" }}>Couldn't load leads: {feed.error}</div>;
  } else if (!leads.length) {
    body = <window.MEmpty title="No leads here"
      sub={bucket === "all" ? "Scout hasn't scored any live leads yet" : "Nothing in the " + (MH_BUCKET_LABEL[bucket] || bucket).toLowerCase() + " bucket"} />;
  } else {
    body = (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {leads.slice(0, 8).map((l) => {
          const bc = MH_BUCKET_COLOR[l.bucket] || "#64748B";
          const hs = handed[l.id];
          const meta = [
            window.timeAgoM(l.lastMessageDate),
            l.askingPrice ? "ask " + window.fmtMoneyM(l.askingPrice) : null,
            l.needsReply ? "needs reply" : null,
          ].filter(Boolean).join(" · ");
          return (
            <div key={l.id} className="m-list-item">
              <div style={{
                width: 34, height: 34, borderRadius: 10, flex: "none",
                display: "flex", alignItems: "center", justifyContent: "center",
                color: bc, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)",
              }}>
                <MHFlameIco size={17} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="m-row" style={{ gap: 6 }}>
                  <span style={{ ...MH_ELLIPSIS, fontSize: 13.5, fontWeight: 700, minWidth: 0 }}>{l.name}</span>
                  <span style={{ fontSize: 11, fontWeight: 800, color: bc, flex: "none" }}>
                    {l.motivation != null ? l.motivation : "—"}
                  </span>
                  <span className="m-fade" style={{ fontSize: 10, fontWeight: 700, color: bc, flex: "none" }}>
                    {MH_BUCKET_LABEL[l.bucket] || (l.bucket || "").toUpperCase()}
                  </span>
                </div>
                {l.lastMessage && <div className="m-fade" style={{ ...MH_ELLIPSIS, marginTop: 2 }}>“{MHSnip(l.lastMessage, 70)}”</div>}
                {meta && <div className="m-fade" style={{ ...MH_ELLIPSIS, fontSize: 10.5, marginTop: 1 }}>{meta}</div>}
              </div>
              <window.MBtn kind="ghost" style={{ flex: "none", padding: "10px 11px", fontSize: 12 }}
                disabled={hs === "busy" || hs === "done"} onClick={() => handoff(l)}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  {hs === "done" ? <MHCheckIco size={13} /> : <MHSendIco size={13} />}
                  {hs === "busy" ? "…" : (hs === "done" ? "Handed" : "Marcus")}
                </span>
              </window.MBtn>
            </div>
          );
        })}
        {leads.length > 8 && (
          <div className="m-fade" style={{ textAlign: "center" }}>+{leads.length - 8} more in the Convos tab</div>
        )}
      </div>
    );
  }

  return (
    <window.MCard>
      <div className="m-row" style={{ marginBottom: 10, gap: 8 }}>
        <div className="m-seg" style={{ flex: 1, marginBottom: 0 }}>
          {MH_BUCKET_CHIPS.map(([k, label]) => (
            <window.MChip key={k} active={bucket === k} onClick={() => setBucket(k)}>{label}</window.MChip>
          ))}
        </div>
        {feed.data && (
          <span className="m-fade" style={{ fontSize: 10.5, fontWeight: 600, flex: "none" }}>
            {feed.data.count || 0} live
          </span>
        )}
      </div>
      {body}
    </window.MCard>
  );
}

// --- Full-screen Hot Leads sheet (tap the Hot Leads stat tile) -------------------
// Every Scout-scored lead — not the Home top-8 — with bucket filters + handoff.
function MHLeadsSheet(props) {
  const [bucket, setBucket] = useStateMH("asap");
  const path = "/api/scout/leads" + (bucket === "all" ? "" : "?bucket=" + bucket);
  const feed = window.useApiM(path, { interval: 30000 });
  const [handed, setHanded] = useStateMH({});
  const leads = (feed.data && feed.data.leads) || [];
  const chips = MH_BUCKET_CHIPS.concat([["dead", "Dead"]]);

  async function handoff(l) {
    if (!window.confirm("Hand " + l.name + " to Marcus? He screens the lead and drafts a reply into your approval inbox.")) return;
    setHanded((h) => ({ ...h, [l.id]: "busy" }));
    try {
      await window.apiPostM("/api/scout/handoff", { id: l.id });
      setHanded((h) => ({ ...h, [l.id]: "done" }));
      feed.refresh();
    } catch (e) {
      setHanded((h) => ({ ...h, [l.id]: null }));
      window.alert("Handoff: " + e.message);
    }
  }

  return (
    <div className="m-sheet">
      <div className="m-sheet-head">
        <button className="m-tab" style={{ flex: "none", minWidth: 44, minHeight: 44, padding: 4 }} onClick={props.onClose}>
          <window.MIcons.Back size={22} />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 800 }}>Scout leads</div>
          <div className="m-fade">{feed.data ? (feed.data.count || leads.length) + " in this bucket" : "live triage"}</div>
        </div>
        <button className="m-tab" style={{ flex: "none", minWidth: 44, minHeight: 44, padding: 4 }} onClick={feed.refresh}>
          <window.MIcons.Refresh size={19} />
        </button>
      </div>
      <div className="m-sheet-body">
        <div className="m-seg">
          {chips.map(([k, label]) => (
            <window.MChip key={k} active={bucket === k} onClick={() => setBucket(k)}>{label}</window.MChip>
          ))}
        </div>
        {feed.loading && !feed.data && <window.MSpin />}
        {feed.error && !leads.length && (
          <div className="m-fade" style={{ padding: "6px 0" }}>Couldn't load leads: {feed.error}</div>
        )}
        {!feed.loading && !feed.error && !leads.length && (
          <window.MEmpty title="No leads here"
            sub={"Nothing in the " + (MH_BUCKET_LABEL[bucket] || bucket).toLowerCase() + " bucket right now"} />
        )}
        {leads.map((l) => {
          const bc = MH_BUCKET_COLOR[l.bucket] || "#64748B";
          const hs = handed[l.id];
          const meta = [
            window.timeAgoM(l.lastMessageDate),
            l.askingPrice ? "ask " + window.fmtMoneyM(l.askingPrice) : null,
            l.needsReply ? "needs reply" : null,
          ].filter(Boolean).join(" · ");
          return (
            <div key={l.id} className="m-list-item">
              <div style={{
                width: 34, height: 34, borderRadius: 10, flex: "none",
                display: "flex", alignItems: "center", justifyContent: "center",
                color: bc, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)",
              }}>
                <MHFlameIco size={17} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="m-row" style={{ gap: 6 }}>
                  <span style={{ ...MH_ELLIPSIS, fontSize: 13.5, fontWeight: 700, minWidth: 0 }}>{l.name}</span>
                  <span style={{ fontSize: 11, fontWeight: 800, color: bc, flex: "none" }}>
                    {l.motivation != null ? l.motivation : "—"}
                  </span>
                  <span className="m-fade" style={{ fontSize: 10, fontWeight: 700, color: bc, flex: "none" }}>
                    {MH_BUCKET_LABEL[l.bucket] || (l.bucket || "").toUpperCase()}
                  </span>
                </div>
                {l.lastMessage && <div className="m-fade" style={{ ...MH_ELLIPSIS, marginTop: 2 }}>“{MHSnip(l.lastMessage, 70)}”</div>}
                {meta && <div className="m-fade" style={{ ...MH_ELLIPSIS, fontSize: 10.5, marginTop: 1 }}>{meta}</div>}
              </div>
              <window.MBtn kind="ghost" style={{ flex: "none", padding: "10px 11px", fontSize: 12 }}
                disabled={hs === "busy" || hs === "done"} onClick={() => handoff(l)}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  {hs === "done" ? <MHCheckIco size={13} /> : <MHSendIco size={13} />}
                  {hs === "busy" ? "…" : (hs === "done" ? "Handed" : "Marcus")}
                </span>
              </window.MBtn>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- Page ----------------------------------------------------------------------
function MHomePage() {
  const dash = window.useApiM("/api/dashboard", { interval: 30000 });
  const scout = window.useApiM("/api/scout/summary", { interval: 30000 });
  const feed = window.useApiM("/api/marcus/proposals", { interval: 20000 });
  const ops = window.useApiM("/api/ops/status", { interval: 15000 });

  const approvalsCount = (feed.data && feed.data.proposals) ? feed.data.proposals.length : 0;
  const [leadsOpen, setLeadsOpen] = useStateMH(false);
  // Tile taps: Hot leads → full-screen Scout sheet; the rest jump tabs.
  const tileTaps = {
    hot: () => setLeadsOpen(true),
    replies: () => window.mGoTab && window.mGoTab("convos"),
    pipe: () => window.mGoTab && window.mGoTab("pipeline"),
    opps: () => window.mGoTab && window.mGoTab("pipeline"),
  };

  return (
    <React.Fragment>
      <window.MHeader title="FORGE" sub="Command Center" right={<MHOpsPill ops={ops} />} />
      <div className="m-content">
        <MHKpis dash={dash} scout={scout} onTapStat={tileTaps} />
        <MHSection label="Needs you" accent="#F59E0B" count={approvalsCount} />
        <MHApprovals feed={feed} />
        <MHSection label="Scout · hot leads" accent="#EF4444" />
        <MHHotLeads onHandoff={feed.refresh} />
      </div>
      {leadsOpen && <MHLeadsSheet onClose={() => setLeadsOpen(false)} />}
    </React.Fragment>
  );
}

Object.assign(window, { MHomePage });
