// data.jsx — seed data (empty-state dashboard; Leads/Pipeline pages seeded so they're explorable)

// One "Agents" tab per workspace — the unified hub (agents_hub.jsx). Every agent across
// all three businesses lives inside it (Chat / Tasks / Console), so the sidebar isn't a
// pile of per-agent tabs. The old per-agent PAGES are untouched — they're now rendered as
// each agent's "Console" inside the hub (HUB_CONSOLE), just no longer their own nav item.
const NAV = [
  ["Dashboard", "Dashboard"], ["Agents", "Agents"], ["Leads", "Leads"], ["Conversations", "Conversations"],
  ["Pipeline", "Deal Pipeline"], ["Contracts", "Contracts"], ["DealCalc", "Deal Calc"], ["Buyers", "Buyers"], ["Blast", "Buyer Blast"], ["Properties", "Properties"],
  ["Outbound", "Outbound"],
  ["Marketing", "Marketing"], ["Tasks", "Tasks"], ["Analytics", "Analytics"],
  ["Brain", "Brain"], ["SystemHealth", "System Health"], ["Costs", "Costs"], ["Settings", "Settings"],
];

// Forge AI Agency workspace — ClientForge ops + control center
const AGENCY_NAV = [
  ["Dashboard", "Dashboard"], ["Agents", "Agents"], ["Build", "Blueprint Studio"], ["Clients", "Clients"], ["ClientView", "Client View"],
  ["Requests", "Edit Requests"],
  ["Workflows", "Workflows"], ["Ads", "Meta Ads"], ["Social", "Social"], ["Approvals", "Approvals"],
  ["Pipeline", "Pipeline"], ["Projects", "Projects"], ["Revenue", "Revenue"],
  ["Brain", "Brain"], ["Settings", "Settings"],
];

// Daycare workspace — center operations, families, staff, enrollment, and billing.
const DAYCARE_NAV = [
  ["Dashboard", "Dashboard"], ["Agents", "Agents"],
  ["Children", "Children"], ["Attendance", "Attendance"],
  ["CareLogs", "Daily Logs"], ["Incidents", "Incidents"], ["Classrooms", "Classrooms"],
  ["Staff", "Staff & Schedules"], ["Enrollment", "Enrollment"], ["ParentLogins", "Parent Logins"], ["Messages", "Messages"],
  ["Announcements", "Announcements"], ["Blast", "Text Blast"],
  ["Billing", "Billing"], ["Payroll", "Payroll"],
  ["Growth", "Ads & Social"],
  ["Meals", "Meals & Menus"], ["Calendar", "Calendar"],
  ["Reports", "Reports"], ["Brain", "Brain"], ["Settings", "Settings"],
];

// FORGE Dropship workspace — Shopify/AutoDS/Meta store run by the Midas agent crew.
const DROPSHIP_NAV = [
  ["Dashboard", "Dashboard"], ["Agents", "Agents"],
  ["Products", "Products"], ["Watch", "Product Watch"], ["Orders", "Orders"], ["Inventory", "Inventory"],
  ["Suppliers", "Suppliers"], ["Ads", "Ads & Creative"], ["Customers", "Customers"],
  ["Analytics", "Analytics"], ["Brain", "Brain"], ["Settings", "Settings"],
];

// Workspaces the profile switcher offers. REI = the existing dash; Agency = new.
const WORKSPACES = [
  { id: "rei",    brand: "FORGE", sub: "REI OS",    accent: "#4F7CFF", tag: "Real Estate", nav: NAV },
  { id: "agency", brand: "FORGE", sub: "AI Agency", accent: "#8B5CF6", tag: "ClientForge",  nav: AGENCY_NAV },
  { id: "daycare", brand: "FORGE", sub: "DAYCARE",  accent: "#2DD4BF", tag: "Daycare Operations", nav: DAYCARE_NAV },
  { id: "dropship", brand: "FORGE", sub: "DROPSHIP", accent: "#F97316", tag: "Dropshipping", nav: DROPSHIP_NAV },
];

const KPIS = [
  { key: "newLeads", label: "New Leads", icon: "Leads", color: "#4F7CFF", value: 0, prefix: "" },
  { key: "conversations", label: "Conversations", icon: "Conversations", color: "#8B5CF6", value: 0, prefix: "" },
  { key: "qualified", label: "Qualified Leads", icon: "Check", color: "#22C55E", value: 0, prefix: "" },
  { key: "appointments", label: "Appointments", icon: "Calendar", color: "#2DD4BF", value: 0, prefix: "" },
  { key: "offers", label: "Offers Sent", icon: "Send", color: "#F59E0B", value: 0, prefix: "" },
  { key: "contracts", label: "Contracts Signed", icon: "Doc", color: "#EC4899", value: 0, prefix: "" },
  { key: "pipeline", label: "Pipeline Value", icon: "Dollar", color: "#4F7CFF", value: 0, prefix: "$" },
  { key: "revenue", label: "Projected Revenue", icon: "Trend", color: "#22C55E", value: 0, prefix: "$" },
];

const HOT_LEADS = [];

const TASKS_SEED = [];

const PIPELINE_COLS = [
  { key: "new", title: "New Lead", accent: "#4F7CFF" },
  { key: "contacted", title: "Contacted", accent: "#8B5CF6" },
  { key: "interested", title: "Interested", accent: "#2DD4BF" },
  { key: "qualified", title: "Qualified", accent: "#22C55E" },
  { key: "offer", title: "Offer Sent", accent: "#F59E0B" },
  { key: "contract", title: "Contract", accent: "#EC4899" },
  { key: "closed", title: "Closed", accent: "#64748B" },
];

const WORKFORCE = [
  { name: "Marcus", role: "Acquisitions & Lead Screening", status: "online", perf: 100 },
  { name: "Sophia", role: "Lead Manager", status: "soon" },
  { name: "Alex", role: "Dispositions Manager", status: "soon" },
  { name: "Jordan", role: "Operations Manager", status: "soon" },
  { name: "Maya", role: "Marketing Manager", status: "soon" },
  { name: "Atlas", role: "Deal Underwriter · preps your offer anchors", status: "online", perf: 100 },
  { name: "Nova", role: "Executive Assistant", status: "soon" },
];

const ACTIVITY = [];

// Empty — leads populate as they come in
const LEADS_TABLE = [];

const STAGE_COLOR = {
  "New Lead": "#4F7CFF", "Contacted": "#8B5CF6", "Interested": "#2DD4BF",
  "Qualified": "#22C55E", "Offer Sent": "#F59E0B", "Contract": "#EC4899", "Closed": "#64748B",
};

Object.assign(window, { NAV, AGENCY_NAV, DAYCARE_NAV, DROPSHIP_NAV, WORKSPACES, KPIS, HOT_LEADS, TASKS_SEED, PIPELINE_COLS, WORKFORCE, ACTIVITY, LEADS_TABLE, STAGE_COLOR });
