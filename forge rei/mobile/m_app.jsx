// FORGE Mobile — root app: tab routing + workspace state. Loads LAST.
// Hook aliases for this file: MAP.
const { useState: useStateMAP, useEffect: useEffectMAP } = React;

const M_PAGES = {
  today: () => (window.MHomePage ? <window.MHomePage /> : <window.MEmpty title="Today unavailable" />),
  home: () => (window.MHomePage ? <window.MHomePage /> : <window.MEmpty title="Today unavailable" />),
  actions: () => (window.MActionsPage ? <window.MActionsPage /> : <window.MEmpty title="Actions unavailable" />),
  agency: () => (window.MWAgency ? <window.MWAgency /> : <window.MEmpty title="Agency unavailable" />),
  daycare: () => (window.MWDaycare ? <window.MWDaycare /> : <window.MEmpty title="Daycare unavailable" />),
  agents: () => (window.MAgentsPage ? <window.MAgentsPage /> : <window.MEmpty title="Agents unavailable" />),
  convos: () => (window.MConvosPage ? <window.MConvosPage /> : <window.MEmpty title="Convos unavailable" />),
  pipeline: () => (window.MPipelinePage ? <window.MPipelinePage /> : <window.MEmpty title="Pipeline unavailable" />),
  calc: () => (window.MCalcPage ? <window.MCalcPage /> : <window.MEmpty title="Calc unavailable" />),
  agents: () => (window.MAgentsPage ? <window.MAgentsPage /> : <window.MEmpty title="Agents unavailable" />),
  more: () => (window.MMorePage ? <window.MMorePage /> : <window.MEmpty title="More unavailable" />),
};

function MAPWholesale() {
  const [segment, setSegment] = useStateMAP("Approvals");
  useEffectMAP(() => {
    if (window.mGoTabSegment) setSegment(window.mGoTabSegment);
  }, []);
  const options = ["Approvals", "Hot", "Convos", "Pipeline", "Calc"];
  const set = (next) => { setSegment(next); window.mGoTabSegment = ""; };
  return <React.Fragment>
    <window.MHeader title="Wholesale" sub="A Touch of Blessings Home Buyers" />
    <div className="m-seg mw-business-segments">{options.map((s)=><window.MChip key={s} active={segment===s} onClick={()=>set(s)}>{s}</window.MChip>)}</div>
    {segment === "Convos" ? <window.MConvosPage/> : segment === "Pipeline" ? <window.MPipelinePage/> : segment === "Calc" ? <window.MCalcPage/> : <window.MHomePage/>}
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
  const render = tab === "wholesale" ? MAPWholesale : (M_PAGES[tab] || M_PAGES.today);
  return (
    <div className="m-app">
      {render()}
      <window.MTabBar tab={tab === "agents" ? "more" : tab} onTab={setTab} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<MApp />);
