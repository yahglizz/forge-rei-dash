// app.jsx
const { useState: useStateA } = React;

// Page renderers per workspace. Keys match each workspace's NAV keys.
const REI_PAGES = {
  Dashboard:     () => <window.Dashboard />,
  Leads:         () => <window.Leads />,
  Pipeline:      () => <window.PIPipelineHubPage />,
  Contracts:     () => <window.CTContractsPage />,
  Conversations: () => <window.ConversationsPage />,
  Tasks:         () => <window.TasksPage />,
  Properties:    () => <window.Placeholder title="Properties" icon="Properties" />,
  Command:       () => <window.MarcusCommand />,
  Screening:     () => <window.ScreeningPage />,
  Agents:        () => <window.AgentsPage />,
  DealCalc:      () => <window.DealCalcPage />,
  Buyers:        () => <window.BuyersPage />,
  Blast:         () => <window.BlastPage />,
  Outbound:      () => <window.OutboundPage />,
  Marketing:     () => <window.Placeholder title="Marketing" icon="Marketing" />,
  Analytics:     () => <window.AnalyticsPage />,
  Brain:         () => <window.BrainPage />,
  SystemHealth:  () => <window.SystemHealthPage />,
  Costs:         () => <window.CostPage />,
  Settings:      () => <window.Placeholder title="Settings" icon="Settings" />,
};

const AGENCY_PAGES = {
  Dashboard:  () => <window.AgencyDashboard />,
  Clients:    () => <window.AgencyClients />,
  ClientView: () => <window.AgencyClientView />,
  Requests:   () => <window.AgencyRequests />,
  Agents:     () => <window.AgencyAgents />,
  Dyson:      () => <window.AgencyDyson />,
  Workflows:  () => <window.AgencyWorkflows />,
  Ads:        () => <window.AgencyAds />,
  Social:     () => <window.AgencySocial />,
  Eco:        () => <window.AgencyEco />,
  Approvals:  () => <window.AgencyApprovals />,
  Brain:      () => <window.BrainPage />,
  Pipeline:   () => <window.AgencyPipeline />,
  Projects:   () => <window.AgencyProjects />,
  Revenue:    () => <window.AgencyRevenue />,
  Settings:   () => <window.AgencySettings />,
};

const DAYCARE_PAGES = {
  Dashboard:  () => <window.DaycareDashboard />,
  Children:   () => <window.DaycareChildren />,
  Attendance: () => <window.DaycareAttendance />,
  Classrooms: () => <window.DaycareClassrooms />,
  Staff:      () => <window.DaycareStaff />,
  Enrollment: () => <window.DaycareEnrollment />,
  Billing:    () => <window.DaycareBilling />,
  Meals:      () => <window.DaycareMeals />,
  Calendar:   () => <window.DaycareCalendar />,
  Reports:    () => <window.DaycareReports />,
  Brain:      () => <window.BrainPage />,
  Settings:   () => <window.DaycareSettings />,
};

const PAGE_MAPS = { rei: REI_PAGES, agency: AGENCY_PAGES, daycare: DAYCARE_PAGES };

function App() {
  const wsList = window.WORKSPACES;
  const [wsId, setWsId] = useStateA(() => localStorage.getItem("forge_ws") || "rei");
  const ws = wsList.find((w) => w.id === wsId) || wsList[0];

  const [active, setActive] = useStateA(ws.nav[0][0]);
  const titleMap = Object.fromEntries(ws.nav);
  window.GoTo = setActive;  // let widgets jump pages via "View all"
  // Jump straight into a seller thread from anywhere (Scout chat, dashboard widget).
  window.openConversation = (lead) => {
    window.__forgeOpenConvo = lead;
    if (ws.id !== "rei") switchWs("rei");
    setActive("Conversations");
  };

  function switchWs(id) {
    if (id === wsId) return;
    const next = wsList.find((w) => w.id === id) || wsList[0];
    setWsId(id);
    localStorage.setItem("forge_ws", id);
    setActive(next.nav[0][0]);  // land on the new workspace's first page
  }

  const pageMap = PAGE_MAPS[ws.id] || REI_PAGES;
  const renderPage = pageMap[active] || pageMap[ws.nav[0][0]];

  return (
    <div className={"app app-" + ws.id} style={{ "--workspace-accent": ws.accent }}>
      <window.Sidebar
        active={active} onNav={setActive} goal={0}
        brand={ws.brand} sub={ws.sub} nav={ws.nav} accent={ws.accent} showMarcus={ws.id === "rei"} />
      <div className="main">
        <window.Header title={titleMap[active]} workspaces={wsList} current={ws} onSwitch={switchWs} />
        <div className="content">
          <div key={ws.id + ":" + active} className="page-wrap">{renderPage()}</div>
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
