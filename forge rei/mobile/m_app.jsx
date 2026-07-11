// FORGE Mobile — root app: tab routing + workspace state. Loads LAST.
// Hook aliases for this file: MAP.
const { useState: useStateMAP, useEffect: useEffectMAP } = React;

const M_PAGES = {
  home: () => (window.MHomePage ? <window.MHomePage /> : <window.MEmpty title="Home unavailable" />),
  convos: () => (window.MConvosPage ? <window.MConvosPage /> : <window.MEmpty title="Convos unavailable" />),
  pipeline: () => (window.MPipelinePage ? <window.MPipelinePage /> : <window.MEmpty title="Pipeline unavailable" />),
  calc: () => (window.MCalcPage ? <window.MCalcPage /> : <window.MEmpty title="Calc unavailable" />),
  agents: () => (window.MAgentsPage ? <window.MAgentsPage /> : <window.MEmpty title="Agents unavailable" />),
  more: () => (window.MMorePage ? <window.MMorePage /> : <window.MEmpty title="More unavailable" />),
};

function MApp() {
  const [tab, setTab] = useStateMAP(localStorage.getItem("m_tab") || "home");
  useEffectMAP(() => { localStorage.setItem("m_tab", tab); }, [tab]);
  // Global tab bridge — lets any page jump tabs (Home stat tiles → Pipeline/Convos).
  useEffectMAP(() => {
    window.mGoTab = (t) => { if (M_PAGES[t]) setTab(t); };
    return () => { if (window.mGoTab) delete window.mGoTab; };
  }, []);
  const render = M_PAGES[tab] || M_PAGES.home;
  return (
    <div className="m-app">
      {render()}
      <window.MTabBar tab={tab} onTab={setTab} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<MApp />);
