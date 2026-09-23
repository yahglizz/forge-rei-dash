// FORGE Mobile — root app: tab routing + workspace state. Loads LAST.
// Hook aliases for this file: MAP.
const { useState: useStateMAP, useEffect: useEffectMAP } = React;

const M_PAGES = {
  today: () => (window.MPToday ? <window.MPToday /> : <window.MEmpty title="Today unavailable" />),
  home: () => (window.MHomePage ? <window.MHomePage /> : <window.MEmpty title="Today unavailable" />),
  actions: () => (window.MActionsPage ? <window.MActionsPage /> : <window.MEmpty title="Actions unavailable" />),
  agency: () => (window.MWAgency ? <window.MWAgency /> : <window.MEmpty title="Agency unavailable" />),
  daycare: () => (window.MWDaycare ? <window.MWDaycare /> : <window.MEmpty title="Daycare unavailable" />),
  agents: () => (window.MAgentsPage ? <window.MAgentsPage /> : <window.MEmpty title="Agents unavailable" />),
  convos: () => (window.MConvosPage ? <window.MConvosPage /> : <window.MEmpty title="Convos unavailable" />),
  pipeline: () => (window.MPipelinePage ? <window.MPipelinePage /> : <window.MEmpty title="Pipeline unavailable" />),
  calc: () => (window.MCalcPage ? <window.MCalcPage /> : <window.MEmpty title="Calc unavailable" />),
  more: () => (window.MMorePage ? <window.MMorePage /> : <window.MEmpty title="More unavailable" />),
};

function MAPWholesale(props) {
  const [segment, setSegment] = useStateMAP(props.segment || "Approvals");
  useEffectMAP(() => {
    if (props.segment) setSegment(props.segment);
  }, [props.segment]);
  const options = ["Approvals", "Hot", "Convos", "Pipeline", "Calc"];
  const set = (next) => { setSegment(next); window.mGoTab && window.mGoTab("wholesale", next); };
  return <React.Fragment>
    <div className="m-seg mw-business-segments">{options.map((s)=><window.MChip key={s} active={segment===s} onClick={()=>set(s)}>{s}</window.MChip>)}</div>
    {segment === "Convos" ? <window.MConvosPage/> : segment === "Pipeline" ? <window.MPipelinePage/> : segment === "Calc" ? <window.MCalcPage/> : <window.MHomePage embedded segment={segment}/>}
    {segment === "Approvals" && <div className="mw-home-actions"><window.MBtn kind="ghost" onClick={()=>window.mGoTab("actions")}>All owner actions →</window.MBtn><window.MBtn kind="ghost" onClick={()=>window.mGoTab("agents")}>Agents →</window.MBtn></div>}
  </React.Fragment>;
}

function MApp() {
  const stored = localStorage.getItem("m_tab") || "today";
  const [tab, setTab] = useStateMAP(["convos","pipeline","calc"].includes(stored) ? "wholesale" : (stored === "actions" ? "today" : stored));
  const [wholesaleSegment, setWholesaleSegment] = useStateMAP(({ convos: "Convos", pipeline: "Pipeline", calc: "Calc" })[stored] || "Approvals");
  useEffectMAP(() => { localStorage.setItem("m_tab", tab); }, [tab]);
  // Global tab bridge — lets any page jump tabs (Home stat tiles → Pipeline/Convos).
  useEffectMAP(() => {
    window.mGoTab = (t, segment) => {
      if (t === "agents") setTab("agents");
      else if (["convos","pipeline","calc"].includes(t)) { setWholesaleSegment(({convos:"Convos",pipeline:"Pipeline",calc:"Calc"})[t]); setTab("wholesale"); }
      else if (t === "wholesale") { if (segment) setWholesaleSegment(segment); setTab(t); }
      else if (M_PAGES[t]) setTab(t === "home" ? "today" : t);
    };
    window.mGoTabSegment = wholesaleSegment;
    return () => { if (window.mGoTab) delete window.mGoTab; };
  }, [wholesaleSegment]);
  const render = tab === "wholesale" ? () => <MAPWholesale segment={wholesaleSegment}/> : (M_PAGES[tab] || M_PAGES.today);
  return (
    <div className="m-app">
      {render()}
      <window.MTabBar tab={tab === "agents" ? "more" : tab === "actions" ? "today" : tab} onTab={setTab} />
    </div>
  );
}

// ── Business portal mode ────────────────────────────────────────────────────
// m_biz: wholesale|agency|daycare → that business's own tabs (window.M_BIZ[id]);
// all → the classic MApp above, untouched; unset → MLoginPortal (m_login.jsx).
// Anything missing (portal file, M_BIZ entry) falls back to the classic app.
const MAP_BIZ_CHOICES = ["wholesale", "agency", "daycare", "all"];
const MAP_BIZ_ALIAS = { agents: "crew", convos: "inbox" }; // classic key → biz tab key

function MAPReadBiz() {
  // ?biz= wins for this launch (e.g. a per-business home-screen bookmark) but is not saved.
  const q = new URLSearchParams(window.location.search).get("biz");
  if (MAP_BIZ_CHOICES.includes(q)) return q;
  const s = localStorage.getItem("m_biz");
  return MAP_BIZ_CHOICES.includes(s) ? s : null;
}

// A business page is another agent's file — one crash shows a way out, not a white screen.
class MAPBoundary extends React.Component {
  constructor(p) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  render() {
    if (!this.state.err) return this.props.children;
    return <React.Fragment>
      <window.MHeader title="Screen error" sub="This page hit a problem" />
      <div className="m-content">
        <window.MEmpty title="This screen couldn't load" sub={String((this.state.err && this.state.err.message) || this.state.err)} />
        {window.mSwitchBiz && <window.MBtn kind="ghost" onClick={() => window.mSwitchBiz()}>Switch business</window.MBtn>}
      </div>
    </React.Fragment>;
  }
}

function MAPBiz(props) {
  const biz = props.biz;
  const tabs = Array.isArray(biz.tabs) && biz.tabs.length ? biz.tabs : [{ key: "home", label: "Home", ico: "Home" }];
  const keys = tabs.map((t) => t.key);
  const tabStore = "m_tab_" + biz.id;
  const [tab, setTab] = useStateMAP(() => { const s = localStorage.getItem(tabStore); return keys.includes(s) ? s : keys[0]; });
  const [overlay, setOverlay] = useStateMAP(null); // classic page shown inside this business: {key, segment}
  useEffectMAP(() => { localStorage.setItem(tabStore, tab); }, [tab]);
  const goTab = (k) => { setOverlay(null); setTab(k); };
  // mGoTab here: own tab (or alias: agents→crew, convos→inbox) → switch; own id
  // ("wholesale", "Convos") → matching tab, or home when no segment; any other classic
  // page (incl. "wholesale","Hot") → render it inside this business (tab bar kept, header ‹ returns).
  useEffectMAP(() => {
    const own = (k) => keys.includes(k) ? k : keys.includes(MAP_BIZ_ALIAS[k]) ? MAP_BIZ_ALIAS[k] : null;
    window.mGoTab = (t, segment) => {
      const seg = segment ? String(segment).toLowerCase() : "";
      if (own(t)) return goTab(own(t));
      if (t === biz.id) {
        if (!seg) return goTab(keys[0]);
        if (own(seg)) return goTab(own(seg));
      }
      if (t === "wholesale" || M_PAGES[t]) setOverlay({ key: t, segment: segment || null });
    };
    return () => { if (window.mGoTab) delete window.mGoTab; };
  }, [biz]);
  window.mBizBack = overlay ? () => setOverlay(null) : null; // read by MHeader this render
  const Page = biz.pages && biz.pages[tab];
  let body;
  if (overlay && overlay.key === "wholesale") body = <MAPWholesale segment={overlay.segment || "Approvals"} />;
  else if (overlay && overlay.key === "agents") body = window.MAgentsPage ? <window.MAgentsPage business={biz.id} /> : M_PAGES.agents();
  else if (overlay) body = M_PAGES[overlay.key]();
  else body = Page ? <Page /> : <React.Fragment><window.MHeader title={biz.name || biz.id} /><div className="m-content"><window.MEmpty title="Page unavailable" /></div></React.Fragment>;
  return (
    <div className="m-app">
      <MAPBoundary key={overlay ? "o:" + overlay.key : "t:" + tab}>{body}</MAPBoundary>
      <window.MTabBar tabs={tabs} tab={overlay ? null : tab} onTab={goTab} />
    </div>
  );
}

function MAPRoot() {
  const [biz, setBiz] = useStateMAP(MAPReadBiz);
  const Portal = window.MLoginPortal;
  const reg = biz && biz !== "all" && window.M_BIZ && window.M_BIZ[biz];
  const pick = (id) => { localStorage.setItem("m_biz", id); setBiz(id); };
  // Globals read by MHeader during this render (children render after the parent).
  window.mBizActive = reg ? biz : null;
  window.mBizBack = null;
  if (reg || (Portal && biz === "all")) {
    window.mSwitchBiz = () => {
      localStorage.removeItem("m_biz");
      const u = new URL(window.location.href);
      if (u.searchParams.has("biz")) { u.searchParams.delete("biz"); window.history.replaceState(null, "", u.pathname + u.search + u.hash); }
      setBiz(null);
    };
  } else delete window.mSwitchBiz;
  if (reg) return <MAPBiz key={biz} biz={Object.assign({ id: biz }, reg)} />;
  if (!biz && Portal) return <Portal onPick={pick} />;
  return <MApp />;
}

ReactDOM.createRoot(document.getElementById("root")).render(<MAPRoot />);
