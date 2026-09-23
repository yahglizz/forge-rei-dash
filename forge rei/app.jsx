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

// --- Business archive (P1-1) + home sub-views + crash guard -------------------
// Archive = HIDE, never delete: an archived workspace leaves the switchers but its
// PAGE_MAPS entry and scripts still load, so "Open (archived)" can still show it.
// Server truth is /api/businesses (business_scope.py); until it answers we assume
// the default seed so an archived business never flashes into the switcher.
const APP_ARCHIVE_SEED = ["dropship", "agency:p"];

// forge_view values. "home" = Mission Control, "workspace" = inside a business,
// the rest are full-screen home sub-views: [title, window component name].
const APP_SUB_VIEWS = {
  archived: ["Archived Businesses", "ArchivedBusinessesPage"],
  agents:   ["Agent Control Center", "AgentControlCenter"],
  health:   ["System Health", "SystemHealthPage"],
  costs:    ["Costs", "CostPage"],
};
const APP_VIEWS = ["home", "workspace"].concat(Object.keys(APP_SUB_VIEWS));

// Pseudo-entry appended to the header's Workspaces menu so Archived Businesses is
// reachable from every workspace without touching shell.jsx. switchWs intercepts it.
const APP_ARCHIVED_ENTRY = { id: "__archived", brand: "Archived", sub: "Businesses",
  accent: "#64748B", tag: "Hidden · reactivate or view" };

// localStorage can throw (private mode, blocked storage) — never let that blank the app.
function appRead(key, fallback) {
  try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
}
function appWrite(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* view state just won't persist */ }
}

// One bad page (or a missing window.X) used to white-screen the whole app. This keeps
// the crash inside the page area with a readable message + Reload.
class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { err: null };
  }
  static getDerivedStateFromError(err) {
    return { err };
  }
  componentDidCatch(err, info) {
    console.error("[forge] page crashed:", err, info && info.componentStack);
  }
  render() {
    const err = this.state.err;
    if (!err) return this.props.children;
    return (
      <div className="card" style={{ margin: 24, padding: 22, maxWidth: 680, flex: "none", alignSelf: "flex-start" }}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>This page hit an error</div>
        <div className="faint" style={{ fontSize: 13, marginBottom: 12 }}>
          The rest of FORGE is fine. Switch pages, or reload to try again.
        </div>
        <pre className="mono" style={{ fontSize: 12, whiteSpace: "pre-wrap", color: "var(--red)", margin: "0 0 14px" }}>
          {String((err && err.message) || err)}
        </pre>
        <button className="tab active" onClick={() => window.location.reload()}>Reload</button>
      </div>
    );
  }
}

// A home sub-view: "← Home" + title, then the page (or a note if it isn't loaded).
function AppSubView({ view, onHome, onEnter }) {
  const [title, compName] = APP_SUB_VIEWS[view];
  const Page = window[compName];
  return (
    <div style={{ height: "100vh", overflowY: "auto", background: "var(--bg)", padding: "26px clamp(16px, 4vw, 52px) 60px" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <button className="tab" onClick={onHome} style={{ padding: "9px 15px", fontSize: 13, fontWeight: 600 }}>← Home</button>
          <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: -0.3 }}>{title}</div>
        </div>
        <AppErrorBoundary>
          {Page ? <Page onHome={onHome} onEnter={onEnter} />
                : <div className="card faint" style={{ padding: 18 }}>{title} not installed.</div>}
        </AppErrorBoundary>
      </div>
    </div>
  );
}

function App() {
  const wsList = window.WORKSPACES;
  const bizApi = window.useApi("/api/businesses");
  const bizRows = bizApi.data && bizApi.data.businesses;
  const archived = new Set(bizRows ? bizRows.filter((b) => b.archived).map((b) => b.id) : APP_ARCHIVE_SEED);
  // MAINTENANCE (business_scope): visual only — the business stays active + clickable;
  // switchers grey it and prefix its tag, the workspace shows a banner.
  const maint = new Set(bizRows ? bizRows.filter((b) => b.maintenance).map((b) => b.id) : []);
  const activeWs = wsList.filter((w) => !archived.has(w.id))
    .map((w) => maint.has(w.id) ? { ...w, maintenance: true, tag: "🛠 Maintenance · " + (w.tag || "") } : w);
  // An archived workspace opened via "Open (archived)" (session only — a reload drops it).
  const [roWs, setRoWs] = useStateA(null);
  const [wsId, setWsId] = useStateA(() => appRead("forge_ws", "rei"));
  // A stale forge_ws pointing at an archived business falls back to rei.
  const ws = wsList.find((w) => w.id === wsId && (!archived.has(w.id) || w.id === roWs))
    || activeWs.find((w) => w.id === "rei") || activeWs[0] || wsList[0];

  // Mission Control is the front door: the app opens here (a cross-business review)
  // unless the operator already picked a business this session. "home" = landing.
  const [view, setView] = useStateA(() => {
    const v = appRead("forge_view", "home");
    return APP_VIEWS.includes(v) ? v : "home";
  });
  // Which agency lens is showing. Persisted like wsId so a reload comes back to
  // the same side of the house. Default "b" = Business (what the tab was before).
  // While the Personal lens is archived, a stale "p" is forced to "b".
  const [agScopeSaved, setAgScope] = useStateA(() => appRead("forge_agency_scope", "b"));
  const lensArchived = archived.has("agency:p");
  const agScope = lensArchived ? "b" : agScopeSaved;
  const nav = navFor(ws, agScope);
  const [active, setActive] = useStateA(nav[0][0]);
  const titleMap = Object.fromEntries(nav.map((item) => [item[0], item[1]]));
  window.GoTo = setActive;  // let widgets jump pages via "View all"

  function openView(name) {
    const v = APP_VIEWS.includes(name) ? name : "home";
    setView(v);
    appWrite("forge_view", v);
  }
  function goHome() {
    openView("home");
  }
  // Enter a business from Mission Control — optionally landing on a specific page.
  // An archived id opens anyway, actions live (that's what the Archived page's button calls).
  function enterBusiness(id, page) {
    const next = wsList.find((w) => w.id === id) || wsList[0];
    setRoWs(archived.has(next.id) ? next.id : null);
    setWsId(next.id);
    appWrite("forge_ws", next.id);
    // A lens-scoped agency page also flips the lens, so a jump from Mission
    // Control can never land on a page the current lens is hiding.
    let hit = page && next.nav.find((n) => n[0] === page);
    if (hit && hit[2] === "p" && lensArchived) hit = null;  // archived lens: land on Business
    let scope = agScope;
    if (hit && hit[2] && hit[2] !== scope) {
      scope = hit[2];
      setAgScope(scope);
      appWrite("forge_agency_scope", scope);
    }
    setActive(hit ? page : navFor(next, scope)[0][0]);
    openView("workspace");
  }
  window.forgeGoHome = goHome;         // let any page return to the front door
  window.forgeEnterBusiness = enterBusiness;
  // forgeOpenView("home" | "archived" | "agents" | "health" | "costs" | "workspace").
  // Unknown names go home.
  window.forgeOpenView = openView;
  // Jump straight into a seller thread from anywhere (Scout chat, dashboard widget).
  window.openConversation = (lead) => {
    window.__forgeOpenConvo = lead;
    if (ws.id !== "rei") switchWs("rei");
    setActive("Conversations");
  };

  function switchWs(id) {
    if (id === APP_ARCHIVED_ENTRY.id) return openView("archived");
    if (id === ws.id) return;
    const next = wsList.find((w) => w.id === id) || wsList[0];
    setWsId(id);
    appWrite("forge_ws", id);
    setActive(navFor(next, agScope)[0][0]);  // land on the new workspace's first page
  }

  // Flip the agency lens. Lands on the first page of the lens being entered,
  // because the page that was open may not exist on this side.
  function switchScope(scope) {
    if (scope === agScope) return;
    setAgScope(scope);
    appWrite("forge_agency_scope", scope);
    setActive(navFor(ws, scope)[0][0]);
  }

  const pageMap = PAGE_MAPS[ws.id] || REI_PAGES;
  const renderPage = pageMap[active] || pageMap[nav[0][0]];

  if (view === "home") {
    return (
      <AppErrorBoundary key="home">
        <window.MissionControl onEnter={enterBusiness} workspaces={activeWs} />
      </AppErrorBoundary>
    );
  }
  if (APP_SUB_VIEWS[view]) {
    return <AppSubView key={view} view={view} onHome={goHome} onEnter={enterBusiness} />;
  }

  return (
    <div className={"app app-" + ws.id} style={{ "--workspace-accent": ws.accent }}>
      <window.Sidebar
        active={active} onNav={setActive} onHome={goHome}
        brand={ws.brand} sub={ws.sub} nav={nav} accent={ws.accent}
        scopes={ws.id === "agency" && !lensArchived ? window.AGENCY_SCOPES : null} scope={agScope} onScope={switchScope} />
      <div className="main">
        <window.Header title={titleMap[active]} workspaces={activeWs.concat([APP_ARCHIVED_ENTRY])} current={{ ...ws, nav }} onSwitch={switchWs} onNavigate={setActive} onHome={goHome} />
        {archived.has(ws.id) && (
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 26px", fontSize: 12.5,
                        background: "rgba(100,116,139,.14)", borderBottom: "1px solid var(--border)" }}>
            <span className="pill" style={{ background: "rgba(100,116,139,.25)" }}>Archived</span>
            <span className="faint" style={{ flex: 1 }}>
              Viewing an archived business — actions still work. It's hidden from the switcher, Mission Control and agent briefs; its data is untouched.
            </span>
            <button className="tab" onClick={() => openView("archived")}>Manage</button>
          </div>
        )}
        {maint.has(ws.id) && (
          <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 26px", fontSize: 12.5,
                        background: "rgba(245,158,11,.12)", borderBottom: "1px solid var(--border)" }}>
            <span className="pill" style={{ background: "rgba(245,158,11,.22)", color: "#F59E0B" }}>🛠 Maintenance</span>
            <span className="faint" style={{ flex: 1 }}>
              This business is under maintenance — everything is still live: agents, loops and every action work normally.
            </span>
          </div>
        )}
        <div className="content">
          <div key={ws.id + ":" + active} className="page-wrap">
            <AppErrorBoundary>
              {ws.id === "daycare" ? <window.DaycareWorkspace>{renderPage()}</window.DaycareWorkspace> : renderPage()}
            </AppErrorBoundary>
          </div>
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
