// FORGE Mobile — Wholesale business portal (FORGE REI · seller leads).
// Home = the uncluttered dashboard: 4 numbers, replies to approve, hot sellers, tools.
// Every other tab is an existing page. Send / redo / dismiss / handoff logic is NOT
// rebuilt here — it is m_home's MHApprovals / MHOpsPill / MHLeadsSheet and m_more's
// sheets, reached as global function declarations (one shared Babel scope) and guarded
// so a missing one degrades to its legacy route instead of a white screen.
// Nothing here fires on its own: every outward action is a tap + window.confirm inside
// the reused component.
// Hook aliases: BW. Top-level names: MBW*.
const { useState: useStateBW } = React;

// Full-screen sheets that already exist (m_home / m_more), keyed by what Home opens.
const MBW_SHEETS = { hot: "MHLeadsSheet", deals: "MMDealsSheet", contracts: "MMContractsSheet", buyers: "MMBuyersSheet" };
const MBW_TOOLS = [["deals", "Deals"], ["contracts", "Contracts"], ["buyers", "Buyers"]];

// Mission Control's wholesale card ("rei") — Owner calls / Contracts tiles live there.
function MBWRei(mission) {
  const list = mission.data && Array.isArray(mission.data.businesses) ? mission.data.businesses : [];
  return list.find((b) => b.id === "rei" || b.id === "wholesale") || null;
}

// A tile the server dropped (source failed) stays "—", never a fake 0.
function MBWTile(rei, re) {
  const m = rei && (rei.metrics || []).find((x) => re.test(x.label || ""));
  return m && m.value != null ? m.value : "—";
}

// MHApprovals renders ≤6 of feed.data.proposals — hand it a slice so Home shows 3
// and "See all" really shows all (chunks of 6).
function MBWSlice(feed, a, b) {
  if (!feed.data) return feed;
  return { ...feed, data: { ...feed.data, proposals: (feed.data.proposals || []).slice(a, b) } };
}

function MBWMetric(props) {
  return (
    <button type="button" className="mw-metric" onClick={props.onTap}
      style={{ border: 0, fontFamily: "inherit", color: "inherit", cursor: props.onTap ? "pointer" : "default" }}>
      <b>{props.value}</b><span>{props.label}{props.onTap ? " ›" : ""}</span>
    </button>
  );
}

function MBWApprovalsSheet(props) {
  const feed = props.feed;
  const list = (feed.data && feed.data.proposals) || [];
  const starts = [];
  for (let i = 0; i < list.length; i += 6) starts.push(i);
  return (
    <div className="m-sheet">
      <window.MHeader title="Replies to approve" sub={list.length + " drafted by Marcus · nothing sends until you tap"}
        onBack={props.onClose} />
      <div className="m-sheet-body">
        {starts.length
          ? starts.map((i) => <window.MHApprovals key={i} feed={MBWSlice(feed, i, i + 6)} />)
          : <window.MHApprovals feed={feed} />}
      </div>
    </div>
  );
}

function MBWHome() {
  const feed = window.useApiM("/api/marcus/proposals", { interval: 20000 });
  const leads = window.useApiM("/api/scout/leads?bucket=asap", { interval: 30000 });
  const mission = window.useApiM("/api/mission-control", { interval: 60000 });
  const ops = window.useApiM("/api/ops/status", { interval: 15000 });
  const [open, setOpen] = useStateBW(null);
  const [thread, setThread] = useStateBW(null);

  const proposals = (feed.data && feed.data.proposals) || [];
  const hotRows = (leads.data && leads.data.leads) || [];
  const hot = leads.data ? (leads.data.count != null ? leads.data.count : hotRows.length) : "—";
  const toApprove = feed.data ? proposals.length : "—";
  const rei = MBWRei(mission);
  const warns = rei ? (rei.attention || []).filter((a) => a.sev === "warn") : [];

  function openSheet(key) {
    const ok = key === "approvals" ? window.MHApprovals : window[MBW_SHEETS[key]];
    if (ok) return setOpen(key);
    // Sheet not loaded → the legacy route that hosts it.
    if (window.mGoTab) {
      if (key === "approvals") window.mGoTab("wholesale", "Approvals");
      else if (key === "hot") window.mGoTab("wholesale", "Hot");
      else window.mGoTab("more");
    }
  }
  const close = () => setOpen(null);
  const Sheet = open && open !== "approvals" ? window[MBW_SHEETS[open]] : null;
  const Pill = window.MHOpsPill;
  const Approvals = window.MHApprovals;

  const note = typeof hot === "number" ? (hot ? hot + " hot sellers waiting" : "No hot sellers right now") : "Your crew is on it!";

  return (
    <React.Fragment>
      <window.MHeader title="Wholesale" sub="FORGE REI · seller leads" right={Pill ? <Pill ops={ops} /> : null} />
      <div className="m-content mw-page">
        <section className="mw-hero" style={{ background: "linear-gradient(135deg,#DCE8FF,#EEF3FF 55%,#FFEBD9)" }}>
          <div className="mw-eyebrow">FORGE REI · SELLER LEADS</div>
          <h1>Motivated sellers.<br />On the phone.</h1>
          <p>Scout ranks, Marcus drafts, you approve and call. Never a price by text.</p>
          <div className="mw-mascot-note"><window.MForgePal size={56} /><span>{note}</span></div>
        </section>

        <div className="mw-stats" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", margin: 0 }}>
          <MBWMetric label="Hot leads" value={hot} onTap={() => openSheet("hot")} />
          <MBWMetric label="Replies to approve" value={toApprove} onTap={() => openSheet("approvals")} />
          <MBWMetric label="Owner calls" value={MBWTile(rei, /owner call/i)} />
          <MBWMetric label="Live contracts" value={MBWTile(rei, /^contracts/i)} onTap={() => openSheet("contracts")} />
        </div>
        {mission.error && !mission.data && <div className="mw-warn">Mission Control unavailable — owner calls + contracts unknown.</div>}
        {warns.map((a, i) => <div className="mw-warn" key={i}>{a.text}</div>)}

        <div className="m-section"><span className="m-section-l">Needs you</span><span className="m-section-line" /></div>

        <window.MCard title="Replies to approve" right={<span className="mw-streak">{toApprove}</span>}>
          {feed.error && !feed.data ? <div className="mw-warn">Marcus approvals unavailable — retry.</div>
            : Approvals ? <Approvals feed={MBWSlice(feed, 0, 3)} />
            : <div className="mw-warn">Approval cards not loaded — use See all.</div>}
          {(proposals.length > 3 || !Approvals) && (
            <button className="mw-all-actions" onClick={() => openSheet("approvals")}>See all {proposals.length || ""} replies →</button>
          )}
        </window.MCard>

        <window.MCard title="Hot sellers" right={<span className="mw-streak">🔥 {hot}</span>}>
          {leads.loading && !leads.data ? <window.MSpin />
            : leads.error && !leads.data ? <div className="mw-warn">Scout leads unavailable — retry.</div>
            : !hotRows.length ? <window.MEmpty title="No hot sellers" sub="Scout flags them here the moment one replies." />
            : hotRows.slice(0, 3).map((l) => (
              <div className="mw-lead" key={l.id}>
                <div className="mw-lead-main" style={{ cursor: "pointer" }} onClick={() => window.MCThread && setThread(l)}>
                  <b>{l.name || "Seller"}</b>
                  <small>{[l.motivation != null ? "motivation " + l.motivation : null, window.timeAgoM(l.lastMessageDate), l.needsReply ? "needs reply" : null].filter(Boolean).join(" · ")}</small>
                  {l.lastMessage && <small>“{l.lastMessage}”</small>}
                </div>
                {l.phone && <a className="mw-call" href={"tel:" + l.phone}>Call</a>}
                <button className="mw-mark" onClick={() => window.MCThread && setThread(l)} aria-label="Open messages">›</button>
              </div>
            ))}
          {hotRows.length > 0 && (
            <button className="mw-all-actions" onClick={() => openSheet("hot")}>See all hot leads · hand to Marcus →</button>
          )}
        </window.MCard>

        <div className="m-section"><span className="m-section-l">Tools</span><span className="m-section-line" /></div>
        <div style={{ display: "flex", gap: 8 }}>
          {MBW_TOOLS.map(([k, label]) => (
            <window.MBtn key={k} kind="ghost" style={{ flex: 1, fontSize: 12 }} onClick={() => openSheet(k)}>{label}</window.MBtn>
          ))}
        </div>
      </div>

      {open === "approvals" && <MBWApprovalsSheet feed={feed} onClose={close} />}
      {Sheet && <Sheet onBack={close} onClose={close} />}
      {thread && window.MCThread && <window.MCThread convo={thread} onClose={() => setThread(null)} />}
    </React.Fragment>
  );
}

// Tabs 2-5 are the existing pages, resolved at render (load order independent).
const MBWInbox = () => (window.MConvosPage ? <window.MConvosPage /> : <window.MEmpty title="Inbox unavailable" />);
const MBWPipeline = () => (window.MPipelinePage ? <window.MPipelinePage /> : <window.MEmpty title="Pipeline unavailable" />);
const MBWCalc = () => (window.MCalcPage ? <window.MCalcPage /> : <window.MEmpty title="Calculator unavailable" />);
const MBWCrew = () => (window.MAgentsPage ? <window.MAgentsPage business="wholesale" /> : <window.MEmpty title="Crew unavailable" />);

window.M_BIZ = window.M_BIZ || {};
window.M_BIZ.wholesale = {
  id: "wholesale", name: "Wholesale", tagline: "FORGE REI · seller leads", accent: "#4F7CFF", ico: "Board",
  tabs: [
    { key: "home", label: "Home", ico: "Home" },
    { key: "inbox", label: "Inbox", ico: "Chat" },
    { key: "pipeline", label: "Pipeline", ico: "Board" },
    { key: "calc", label: "Calc", ico: "Calc" },
    { key: "crew", label: "Crew", ico: "Bot" },
  ],
  pages: { home: MBWHome, inbox: MBWInbox, pipeline: MBWPipeline, calc: MBWCalc, crew: MBWCrew },
};

Object.assign(window, { MBWHome, MBWInbox, MBWPipeline, MBWCalc, MBWCrew, MBWApprovalsSheet });
