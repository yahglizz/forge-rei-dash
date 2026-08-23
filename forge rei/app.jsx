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
  // Agents = the unified hub. Command/Screening keys stay mapped (nothing removed) —
  // they're reachable as each agent's Console inside the hub.
  Agents:        () => <window.HubAgentsPage ws="rei" />,
  Office:        () => <window.PixelOfficePage />,
  Command:       () => <window.MarcusCommand />,
  Screening:     () => <window.ScreeningPage />,
  DealCalc:      () => <window.DealCalcPage />,
  Buyers:        () => <window.BuyersPage />,
  Blast:         () => <window.BlastPage />,
  Outbound:      () => <window.OutboundPage />,
  Analytics:     () => <window.AnalyticsPage />,
  Brain:         () => <window.BrainPage />,
  SystemHealth:  () => <window.SystemHealthPage />,
  Costs:         () => <window.CostPage />,
};

const AGENCY_PAGES = {
  Dashboard:  () => <window.AgencyDashboard />,
  // --- Personal lens (data.jsx AGENCY_NAV "p") -------------------------------
  // The daycare pages are the daycare's own components, wrapped in the daycare's
  // own auth gate. Surfacing them here does NOT widen access: DaycareWorkspace
  // still calls /api/daycare/auth/status and shows the login screen when the
  // browser has no daycare session, exactly as it does in the daycare workspace.
  MyBiz:      () => <window.AgencyPersonal />,
  MyAds:      () => <window.DaycareWorkspace><window.DaycareAds /></window.DaycareWorkspace>,
  MySocial:   () => <window.DaycareWorkspace><window.DaycareSocial /></window.DaycareWorkspace>,
  MyStudio:   () => <window.DaycareWorkspace><window.DaycareNova /></window.DaycareWorkspace>,
  // --- Business lens (client work) -------------------------------------------
  Clients:    () => <window.AgencyClients />,
  Messages:   () => <window.AgencyMessages />,
  ClientView: () => <window.AgencyClientView />,
  Requests:   () => <window.AgencyRequests />,
  Agents:     () => <window.HubAgentsPage ws="agency" />,
  Office:     () => <window.PixelOfficePage />,
  Build:      () => <window.AgencyBuild />,
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
  Office:     () => <window.PixelOfficePage />,
  Director:   () => <window.DaycareDirector />,
  Children:   () => <window.DaycareChildren />,
  Attendance: () => <window.DaycareAttendance />,
  CareLogs:   () => <window.DaycareCareLogs />,
  Incidents:  () => <window.DaycareIncidents />,
  Rewards:    () => <window.DaycareRewards />,
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
  Reports:    () => <window.DaycareReports />,
  Brain:      () => <window.BrainPage />,
  Settings:   () => <window.DaycareSettings />,
};

const DROPSHIP_PAGES = {
  Dashboard:  () => <window.DropshipDashboard />,
  Agents:     () => <window.DropshipAgents />,
  Office:     () => <window.PixelOfficePage />,
  Products:   () => <window.DropshipProducts />,
  Watch:      () => <window.DropshipWatch />,
  Orders:     () => <window.DropshipOrders />,
  Inventory:  () => <window.DropshipInventory />,
  Suppliers:  () => <window.DropshipSuppliers />,
  Ads:        () => <window.DropshipAds />,
  Customers:  () => <window.DropshipSupport />,
  Analytics:  () => <window.DropshipAnalytics />,
  Connections: () => <window.DropshipConnections />,
  Brain:      () => <window.BrainPage />,
  Settings:   () => <window.DropshipSettings />,
};

const PAGE_MAPS = { rei: REI_PAGES, agency: AGENCY_PAGES, daycare: DAYCARE_PAGES, dropship: DROPSHIP_PAGES };

// The agency workspace has two lenses (Personal = my own businesses, Business =
// clients). A nav tuple's optional 3rd element is its lens; no 3rd element means
// it belongs to both. Every other workspace ignores scope and returns its nav
// untouched, so this is a no-op outside the agency.
function navFor(ws, scope) {
  if (!ws || ws.id !== "agency") return ws.nav;
  return ws.nav.filter((item) => !item[2] || item[2] === scope);
}

function App() {
  const wsList = window.WORKSPACES;
  const [wsId, setWsId] = useStateA(() => localStorage.getItem("forge_ws") || "rei");
  const ws = wsList.find((w) => w.id === wsId) || wsList[0];

  // Mission Control is the front door: the app opens here (a cross-business review)
  // unless the operator already picked a business this session. "home" = landing.
  const [view, setView] = useStateA(() => localStorage.getItem("forge_view") || "home");
  // Which agency lens is showing. Persisted like wsId so a reload comes back to
  // the same side of the house. Default "b" = Business (what the tab was before).
  const [agScope, setAgScope] = useStateA(() => localStorage.getItem("forge_agency_scope") || "b");
  const nav = navFor(ws, agScope);
  const [active, setActive] = useStateA(nav[0][0]);
  const titleMap = Object.fromEntries(nav.map((item) => [item[0], item[1]]));
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
    // A lens-scoped agency page also flips the lens, so a jump from Mission
    // Control can never land on a page the current lens is hiding.
    const hit = page && next.nav.find((n) => n[0] === page);
    let scope = agScope;
    if (hit && hit[2] && hit[2] !== scope) {
      scope = hit[2];
      setAgScope(scope);
      localStorage.setItem("forge_agency_scope", scope);
    }
    setActive(hit ? page : navFor(next, scope)[0][0]);
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
    setActive(navFor(next, agScope)[0][0]);  // land on the new workspace's first page
  }

  // Flip the agency lens. Lands on the first page of the lens being entered,
  // because the page that was open may not exist on this side.
  function switchScope(scope) {
    if (scope === agScope) return;
    setAgScope(scope);
    localStorage.setItem("forge_agency_scope", scope);
    setActive(navFor(ws, scope)[0][0]);
  }

  const pageMap = PAGE_MAPS[ws.id] || REI_PAGES;
  const renderPage = pageMap[active] || pageMap[nav[0][0]];

  if (view === "home") {
    return <window.MissionControl onEnter={enterBusiness} workspaces={wsList} />;
  }

  return (
    <div className={"app app-" + ws.id} style={{ "--workspace-accent": ws.accent }}>
      <window.Sidebar
        active={active} onNav={setActive} onHome={goHome}
        brand={ws.brand} sub={ws.sub} nav={nav} accent={ws.accent}
        scopes={ws.id === "agency" ? window.AGENCY_SCOPES : null} scope={agScope} onScope={switchScope} />
      <div className="main">
        <window.Header title={titleMap[active]} workspaces={wsList} current={{ ...ws, nav }} onSwitch={switchWs} onNavigate={setActive} onHome={goHome} />
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
