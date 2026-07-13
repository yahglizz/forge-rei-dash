// icons.jsx — lucide-style stroke icons
const I = ({ d, size = 18, sw = 1.8, fill = "none", children, ...p }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke="currentColor"
    strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" {...p}>
    {d ? <path d={d} /> : children}
  </svg>
);

const Icons = {
  Dashboard: (p) => <I {...p}><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></I>,
  Leads: (p) => <I {...p}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></I>,
  Conversations: (p) => <I {...p} d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>,
  Pipeline: (p) => <I {...p}><path d="M3 6h18M7 12h10M10 18h4"/></I>,
  Properties: (p) => <I {...p}><path d="M3 9.5 12 3l9 6.5V21a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/></I>,
  Command: (p) => <I {...p}><path d="M18 3a3 3 0 0 0-3 3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3"/></I>,
  Marketing: (p) => <I {...p}><path d="m3 11 18-5v12L3 14v-3zM11.6 16.8a3 3 0 1 1-5.8-1.6"/></I>,
  Tasks: (p) => <I {...p}><path d="M11 3 8 6 6.5 4.5M11 9l-3 3-1.5-1.5M16 5h5M16 11h5M16 17h5M11 15l-3 3-1.5-1.5"/></I>,
  Analytics: (p) => <I {...p}><path d="M3 3v18h18M7 14l3-4 3 3 4-6"/></I>,
  Settings: (p) => <I {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></I>,

  Search: (p) => <I {...p}><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></I>,
  Bell: (p) => <I {...p}><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0"/></I>,
  Activity: (p) => <I {...p} d="M22 12h-4l-3 9L9 3l-3 9H2"/>,
  SystemHealth: (p) => <I {...p}><path d="M12 21S3 14.5 3 8a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 1.2-.3 2.4-.9 3.5"/><path d="M13 12h3l2 3 3-6"/></I>,
  Chevron: (p) => <I {...p} d="m6 9 6 6 6-6"/>,
  ChevronR: (p) => <I {...p} d="m9 18 6-6-6-6"/>,
  Send: (p) => <I {...p}><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></I>,
  Blast: (p) => <I {...p}><path d="m3 11 15-5v12L3 13z"/><path d="M11.6 16.8a3 3 0 0 1-5.8-1.6"/><path d="M18 8a4 4 0 0 1 0 6"/></I>,
  Phone: (p) => <I {...p} d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>,
  Spark: (p) => <I {...p} d="M13 2 3 14h7l-1 8 10-12h-7z" fill="currentColor"/>,
  Check: (p) => <I {...p} d="M20 6 9 17l-5-5"/>,
  Flame: (p) => <I {...p}><path d="M8.5 14.5c0 2 1.5 3.5 3.5 3.5s3.5-1.5 3.5-3.7c0-1.5-1-2.8-1.5-3.3 0 .8-.6 1.5-1.3 1.5-1 0-1.2-1-1.2-2C11.5 7.5 13 5 13 5s-7 3-7 9a6 6 0 0 0 .9 3.2"/></I>,
  Clipboard: (p) => <I {...p}><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/></I>,
  Message: (p) => <I {...p} d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>,
  Reply: (p) => <I {...p}><path d="M9 17 4 12l5-5"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></I>,
  Calendar: (p) => <I {...p}><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></I>,
  Doc: (p) => <I {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></I>,
  Screening: (p) => <I {...p}><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/></I>,
  Dollar: (p) => <I {...p}><path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></I>,
  Trend: (p) => <I {...p}><path d="m23 6-9.5 9.5-5-5L1 18"/><path d="M17 6h6v6"/></I>,
  Plus: (p) => <I {...p} d="M12 5v14M5 12h14"/>,
  Filter: (p) => <I {...p} d="M22 3H2l8 9.46V19l4 2v-8.54z"/>,
  Import: (p) => <I {...p}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></I>,
  Bot: (p) => <I {...p}><rect x="3" y="8" width="18" height="12" rx="3"/><path d="M12 8V4M8 2h8"/><circle cx="8.5" cy="14" r="1.2" fill="currentColor" stroke="none"/><circle cx="15.5" cy="14" r="1.2" fill="currentColor" stroke="none"/></I>,
  Target: (p) => <I {...p}><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/></I>,
  Agents: (p) => <I {...p}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></I>,
  DealCalc: (p) => <I {...p}><rect x="4" y="2" width="16" height="20" rx="2"/><path d="M8 6h8M8 10h0M12 10h0M16 10h0M8 14h0M12 14h0M16 14v4M8 18h4"/></I>,
  MapPin: (p) => <I {...p}><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></I>,
  Sliders: (p) => <I {...p}><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/></I>,
  Brain: (p) => <I {...p}><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2zM14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2z"/></I>,
  Folder: (p) => <I {...p}><path d="M4 4h6l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/></I>,
  PhoneCall: (p) => <I {...p}><path d="M14.5 2a6 6 0 0 1 6 6M14.5 6a2 2 0 0 1 2 2"/><path d="M13.4 14.6 12 16a16 16 0 0 1-6-6l1.4-1.4a2 2 0 0 0 .45-2.11A12.8 12.8 0 0 1 7.1 3.7 2 2 0 0 0 5.1 2H3.6a2 2 0 0 0-2 2.18 19.8 19.8 0 0 0 17.2 17.2 2 2 0 0 0 2.18-2v-1.5a2 2 0 0 0-1.7-2 12.8 12.8 0 0 1-2.79-.75 2 2 0 0 0-2.11.45z"/></I>,
  Outbound: (p) => <I {...p}><path d="M14.5 2a6 6 0 0 1 6 6M14.5 6a2 2 0 0 1 2 2"/><path d="M13.4 14.6 12 16a16 16 0 0 1-6-6l1.4-1.4a2 2 0 0 0 .45-2.11A12.8 12.8 0 0 1 7.1 3.7 2 2 0 0 0 5.1 2H3.6a2 2 0 0 0-2 2.18 19.8 19.8 0 0 0 17.2 17.2 2 2 0 0 0 2.18-2v-1.5a2 2 0 0 0-1.7-2 12.8 12.8 0 0 1-2.79-.75 2 2 0 0 0-2.11.45z"/></I>,

  // --- Forge AI Agency feature-section icons ---
  Requests: (p) => <I {...p}><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></I>,
  Dyson: (p) => <I {...p}><path d="M14.7 6.3a4 4 0 0 0-5.4 5.3L3 18l3 3 6.4-6.3a4 4 0 0 0 5.3-5.4l-2.8 2.8-2.1-.7-.7-2.1z"/></I>,
  Workflows: (p) => <I {...p}><rect x="3" y="3" width="6" height="6" rx="1.5"/><rect x="15" y="15" width="6" height="6" rx="1.5"/><path d="M9 6h4a2 2 0 0 1 2 2v7"/></I>,
  Ads: (p) => <I {...p}><path d="M3 11v3a1 1 0 0 0 1 1h2.5L11 19V5L6.5 9H4a1 1 0 0 0-1 1z"/><path d="M16 8.5a4 4 0 0 1 0 7M19 6a8 8 0 0 1 0 12"/></I>,
  Growth: (p) => <I {...p}><path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/><path d="M17 8h3v3"/></I>,
  Director: (p) => <I {...p}><path d="M3 8l4 3 5-7 5 7 4-3-2 11H5L3 8z"/><path d="M5 19h14"/></I>,
  Eco: (p) => <I {...p}><path d="M11 20A7 7 0 0 1 4 13C4 7 12 4 20 3c-1 8-4 16-9 17z"/><path d="M4 21c1.5-3.5 4.5-6 8-7.5"/></I>,
  Approvals: (p) => <I {...p}><path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/><path d="m9 12 2 2 4-4"/></I>,
  ClientView: (p) => <I {...p}><rect x="3" y="4" width="18" height="13" rx="1.5"/><path d="M3 9h18M8 21h8M12 17v4"/></I>,
  Social: (p) => <I {...p}><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/></I>,

  // --- Daycare operations icons ---
  Children: (p) => <I {...p}><circle cx="9" cy="8" r="3"/><circle cx="17" cy="10" r="2.5"/><path d="M3 21v-2a5 5 0 0 1 10 0v2M14 16.5a4 4 0 0 1 7 2.5v2"/></I>,
  Attendance: (p) => <I {...p}><rect x="3" y="4" width="18" height="17" rx="2"/><path d="M8 2v4M16 2v4M3 10h18m-13 5 2 2 5-5"/></I>,
  Classrooms: (p) => <I {...p}><path d="M3 21V6l9-4 9 4v15M3 9h18M8 13h2M14 13h2M8 17h2M14 17h2"/></I>,
  Staff: (p) => <I {...p}><circle cx="8" cy="8" r="3"/><circle cx="17" cy="7" r="2"/><path d="M2 21v-2a6 6 0 0 1 12 0v2M14 14a5 5 0 0 1 8 4v3"/></I>,
  Enrollment: (p) => <I {...p}><path d="M4 3h13l3 3v15H4zM17 3v4h4M8 12h8M8 16h5"/><path d="M10 7H8v2"/></I>,
  Billing: (p) => <I {...p}><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M7 15h3"/></I>,
  Meals: (p) => <I {...p}><path d="M7 3v7a3 3 0 0 0 3 3V3M7 7h3M8.5 13v8M16 3v18M16 3c3 2 4 5 4 8h-4"/></I>,
  Reports: (p) => <I {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></I>,
  CareLogs: (p) => <I {...p}><path d="M4 3h16v18H4zM8 8h8M8 12h8M8 16h5"/><path d="M9 3V1M15 3V1"/></I>,
  Incidents: (p) => <I {...p}><path d="M12 3 2 21h20z"/><path d="M12 9v5M12 18h.01"/></I>,
  Payroll: (p) => <I {...p}><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h10M7 14h4M16 13v4M14 15h4"/></I>,
  Messages: (p) => <I {...p} d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>,
  Announcements: (p) => <I {...p}><path d="M3 11v3a1 1 0 0 0 1 1h2.5L11 19V5L6.5 9H4a1 1 0 0 0-1 1z"/><path d="M16 8.5a4 4 0 0 1 0 7"/></I>,
  AlertTriangle: (p) => <I {...p}><path d="M12 3 2 21h20z"/><path d="M12 9v5M12 18h.01"/></I>,
  Lock: (p) => <I {...p}><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></I>,
  Shield: (p) => <I {...p}><path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/><path d="m9 12 2 2 4-4"/></I>,
  Logout: (p) => <I {...p}><path d="M10 17l5-5-5-5M15 12H3M21 3v18h-7"/></I>,
};

window.Icons = Icons;
