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
  // Agents = the unified hub. Command/Screening keys stay mapped (nothing removed) —
  // they're reachable as each agent's Console inside the hub.
  Agents:        () => <window.HubAgentsPage ws="rei" />,
  Command:       () => <window.MarcusCommand />,
  Screening:     () => <window.ScreeningPage />,
  AgentsLegacy:  () => <window.AgentsPage />,
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
  Agents:     () => <window.HubAgentsPage ws="agency" />,
  Build:      () => <window.AgencyBuild />,
  AgencyAgentsLegacy: () => <window.AgencyAgents />,
  Dyson:      () => <window.AgencyDyson />,
  Workflows:  () => <window.AgencyWorkflows />,
  Ads:        () => <window.AgencyAds />,
  Social:     () => <window.AgencySocial />,
  Eco:        () => <window.AgencyEco />,
  Approvals:  () => <window.AgencyApprovals />,
  CallCenter: () => <window.AgencyCallCenter />,
  Brain:      () => <window.BrainPage />,
  Pipeline:   () => <window.AgencyPipeline />,
  Projects:   () => <window.AgencyProjects />,
  Revenue:    () => <window.AgencyRevenue />,
  Settings:   () => <window.AgencySettings />,
};

const DAYCARE_PAGES = {
  Dashboard:  () => <window.DaycareDashboard />,
  Agents:     () => <window.HubAgentsPage ws="daycare" />,
  Director:   () => <window.DaycareDirector />,
  Family:     () => <window.DaycareFamilyAgent />,
  AdOps:      () => <window.DaycareAdOpsAgent />,
  Children:   () => <window.DaycareChildren />,
  Attendance: () => <window.DaycareAttendance />,
  CareLogs:   () => <window.DaycareCareLogs />,
  Incidents:  () => <window.DaycareIncidents />,
  Classrooms: () => <window.DaycareClassrooms />,
  Staff:      () => <window.DaycareStaff />,
  Enrollment: () => <window.DaycareEnrollment />,
  ParentLogins: () => <window.DaycareParentLogins />,
  Messages:   () => <window.DaycareMessages />,
  Announcements: () => <window.DaycareAnnouncements />,
  Blast:      () => <window.DaycareBlast />,
  Billing:    () => <window.DaycareBilling />,
  Payroll:    () => <window.DaycarePayroll />,
  Growth:     () => <window.DaycareGrowth />,
  Meals:      () => <window.DaycareMeals />,
  Calendar:   () => <window.DaycareCalendar />,
  Reports:    () => <window.DaycareReports />,
  Brain:      () => <window.BrainPage />,
  Settings:   () => <window.DaycareSettings />,
};

const DROPSHIP_PAGES = {
  Dashboard:  () => <window.DropshipDashboard />,
  Agents:     () => <window.DropshipAgents />,
  Products:   () => <window.DropshipProducts />,
  Watch:      () => <window.DropshipWatch />,
  Orders:     () => <window.DropshipOrders />,
  Inventory:  () => <window.DropshipInventory />,
  Suppliers:  () => <window.DropshipSuppliers />,
  Ads:        () => <window.DropshipAds />,
  Customers:  () => <window.DropshipSupport />,
  Analytics:  () => <window.DropshipAnalytics />,
  Brain:      () => <window.BrainPage />,
  Settings:   () => <window.DropshipSettings />,
};

const PAGE_MAPS = { rei: REI_PAGES, agency: AGENCY_PAGES, daycare: DAYCARE_PAGES, dropship: DROPSHIP_PAGES };

function App() {
  const wsList = window.WORKSPACES;
  const [wsId, setWsId] = useStateA(() => localStorage.getItem("forge_ws") || "rei");
  const ws = wsList.find((w) => w.id === wsId) || wsList[0];

  // Mission Control is the front door: the app opens here (a cross-business review)
  // unless the operator already picked a business this session. "home" = landing.
  const [view, setView] = useStateA(() => localStorage.getItem("forge_view") || "home");
  const [active, setActive] = useStateA(ws.nav[0][0]);
  const titleMap = Object.fromEntries(ws.nav);
  window.GoTo = setActive;  // let widgets jump pages via "View all"

  function goHome() {
    setView("home");
    localStorage.setItem("forge_view", "home");
  }
  // Enter a business from Mission Control — optionally landing on a specific page.
  function enterBusiness(id, page) {
    const next = wsList.find((w) => w.id === id) || wsList[0];
    setWsId(next.id);
    localStorage.setItem("forge_ws", next.id);
    setActive(page && next.nav.some((n) => n[0] === page) ? page : next.nav[0][0]);
    setView("workspace");
    localStorage.setItem("forge_view", "workspace");
  }
  window.forgeGoHome = goHome;         // let any page return to the front door
  window.forgeEnterBusiness = enterBusiness;
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

  if (view === "home") {
    return <window.MissionControl onEnter={enterBusiness} workspaces={wsList} />;
  }

  return (
    <div className={"app app-" + ws.id} style={{ "--workspace-accent": ws.accent }}>
      <window.Sidebar
        active={active} onNav={setActive} goal={0} onHome={goHome}
        brand={ws.brand} sub={ws.sub} nav={ws.nav} accent={ws.accent} showMarcus={ws.id === "rei"} />
      <div className="main">
        <window.Header title={titleMap[active]} workspaces={wsList} current={ws} onSwitch={switchWs} onHome={goHome} />
        <div className="content">
          <div key={ws.id + ":" + active} className="page-wrap">
            {ws.id === "daycare" ? <window.DaycareWorkspace>{renderPage()}</window.DaycareWorkspace> : renderPage()}
          </div>
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
