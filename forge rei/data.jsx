// data.jsx — seed data (empty-state dashboard; Leads/Pipeline pages seeded so they're explorable)

// One "Agents" tab per workspace — the unified hub (agents_hub.jsx). Every agent across
// all three businesses lives inside it (Chat / Tasks / Console), so the sidebar isn't a
// pile of per-agent tabs. The old per-agent PAGES are untouched — they're now rendered as
// each agent's "Console" inside the hub (HUB_CONSOLE), just no longer their own nav item.
const NAV = [
  ["Dashboard", "Dashboard"], ["Agents", "Agents"], ["Office", "Agent Office"], ["Leads", "Leads"], ["Conversations", "Conversations"],
  ["Pipeline", "Deal Pipeline"], ["Contracts", "Contracts"], ["DealCalc", "Deal Calc"], ["Buyers", "Buyers"], ["Blast", "Buyer Blast"],
  ["Outbound", "Outbound"],
  ["Tasks", "Tasks"], ["Analytics", "Analytics"],
  ["Brain", "Brain"], ["SystemHealth", "System Health"], ["Costs", "Costs"],
];

// Forge AI Agency workspace — ClientForge ops + control center
const AGENCY_NAV = [
  ["Dashboard", "Dashboard"], ["Agents", "Agents"], ["Office", "Agent Office"], ["Build", "Blueprint Studio"], ["Clients", "Clients"], ["Messages", "Client Chat"], ["ClientView", "Client View"],
  ["Requests", "Edit Requests"],
  ["Workflows", "Workflows"], ["Ads", "Meta Ads"], ["Social", "Social"], ["Approvals", "Approvals"],
  ["CallCenter", "Call Center"],
  ["Pipeline", "Pipeline"], ["Projects", "Projects"], ["Revenue", "Revenue"],
  ["Brain", "Brain"], ["Settings", "Settings"],
];

// Daycare workspace — center operations, families, staff, enrollment, and billing.
const DAYCARE_NAV = [
  ["Dashboard", "Dashboard"], ["Agents", "Agents"], ["Office", "Agent Office"],
  ["Children", "Children"], ["Attendance", "Attendance"],
  ["CareLogs", "Daily Logs"], ["Incidents", "Incidents"], ["Rewards", "Blessing Coins"], ["Classrooms", "Classrooms"],
  ["Staff", "Staff & Schedules"], ["Enrollment", "Enrollment"], ["ParentLogins", "Parent Logins"], ["Messages", "Messages"],
  ["Announcements", "Announcements"], ["Blast", "Text Blast"],
  ["Billing", "Billing"], ["Payroll", "Payroll"],
  ["Growth", "Ads & Social"],
  ["Reports", "Reports"], ["Brain", "Brain"], ["Settings", "Settings"],
];

// FORGE Dropship workspace — Shopify/AutoDS/Meta store run by the Midas agent crew.
const DROPSHIP_NAV = [
  ["Dashboard", "Dashboard"], ["Agents", "Agents"], ["Office", "Agent Office"],
  ["Products", "Products"], ["Watch", "Product Watch"], ["Orders", "Orders"], ["Inventory", "Inventory"],
  ["Suppliers", "AutoDS · Suppliers"], ["Ads", "Ads & Creative"], ["Customers", "Customers"],
  ["Analytics", "Analytics"], ["Connections", "Connections & MCP"],
  ["Brain", "Brain"], ["Settings", "Settings"],
];

// Workspaces the profile switcher offers. REI = the existing dash; Agency = new.
const WORKSPACES = [
  { id: "rei",    brand: "FORGE", sub: "REI OS",    accent: "#4F7CFF", tag: "Real Estate", nav: NAV },
  { id: "agency", brand: "FORGE", sub: "AI Agency", accent: "#8B5CF6", tag: "ClientForge",  nav: AGENCY_NAV },
  { id: "daycare", brand: "FORGE", sub: "DAYCARE",  accent: "#2DD4BF", tag: "Daycare Operations", nav: DAYCARE_NAV },
  { id: "dropship", brand: "FORGE", sub: "DROPSHIP", accent: "#F97316", tag: "Dropshipping", nav: DROPSHIP_NAV },
];

Object.assign(window, { NAV, AGENCY_NAV, DAYCARE_NAV, DROPSHIP_NAV, WORKSPACES });
