// daycare.jsx — Daycare workspace starter. Browser-local data keeps the first
// version useful without introducing backend or compliance assumptions yet.
const { useState: useStateDc, useEffect: useEffectDc } = React;

const DC_STORE_KEY = "forge_daycare_v1";
const DC_ACCENT = "#2DD4BF";
const DC_GOLD = "#F4B860";
const DC_DEFAULT = {
  center: { name: "My Daycare", capacity: 40, openTime: "7:00 AM", closeTime: "6:00 PM", phone: "", address: "" },
  children: [], staff: [], inquiries: [], attendance: {},
  rooms: [
    { id: "infants", name: "Infants", ages: "6 weeks–18 months", capacity: 8, color: "#8B5CF6" },
    { id: "toddlers", name: "Toddlers", ages: "18 months–3 years", capacity: 10, color: "#2DD4BF" },
    { id: "preschool", name: "Preschool", ages: "3–4 years", capacity: 12, color: "#4F7CFF" },
    { id: "prek", name: "Pre-K", ages: "4–5 years", capacity: 10, color: "#F4B860" },
  ],
};

const dcInput = {
  width: "100%", background: "var(--card-2)", border: "1px solid var(--border)",
  borderRadius: 10, padding: "10px 11px", color: "var(--text)", fontSize: 13, outline: "none",
};

function dcReadStore() {
  try {
    const saved = JSON.parse(localStorage.getItem(DC_STORE_KEY) || "null");
    return saved ? { ...DC_DEFAULT, ...saved, center: { ...DC_DEFAULT.center, ...(saved.center || {}) } } : DC_DEFAULT;
  } catch (_) { return DC_DEFAULT; }
}

function DcUseStore() {
  const [store, setStore] = useStateDc(dcReadStore);
  useEffectDc(() => {
    localStorage.setItem(DC_STORE_KEY, JSON.stringify(store));
    window.dispatchEvent(new CustomEvent("forge-daycare-update", { detail: store }));
  }, [store]);
  return [store, setStore];
}

function DcPageHead({ title, eyebrow, action, actionLabel }) {
  const Icons = window.Icons;
  return (
    <div className="dc-page-head">
      <div>
        <div className="dc-eyebrow">{eyebrow || "DAYCARE OPERATIONS"}</div>
        <h1>{title}</h1>
      </div>
      {action && <button className="dc-primary" onClick={action}><Icons.Plus size={14} /> {actionLabel}</button>}
    </div>
  );
}

function DcKpi({ label, value, sub, icon, color = DC_ACCENT }) {
  const Icon = window.Icons[icon] || window.Icons.Dashboard;
  return (
    <div className="kpi dc-kpi">
      <div className="kpi-ico" style={{ color, background: color + "1f" }}><Icon size={18} /></div>
      <div className="kpi-label">{label}</div>
      <div className="kpi-val tabnum">{value}</div>
      <div className="kpi-delta"><span className="faint">{sub}</span></div>
    </div>
  );
}

function DcEmpty({ icon, title, copy, action, actionLabel }) {
  const Icon = window.Icons[icon] || window.Icons.Dashboard;
  return (
    <div className="card empty dc-empty">
      <div className="empty-ico"><Icon size={26} /></div>
      <div className="dc-empty-title">{title}</div>
      <div className="dc-empty-copy">{copy}</div>
      {action && <button className="dc-primary" onClick={action}>{actionLabel}</button>}
    </div>
  );
}

function DcModal({ title, children, onClose }) {
  return (
    <div className="dc-modal-layer" role="dialog" aria-modal="true" aria-label={title}>
      <button className="dc-modal-backdrop" onClick={onClose} aria-label="Close" />
      <div className="card dc-modal">
        <div className="dc-modal-head"><div className="card-title">{title}</div><button onClick={onClose}>✕</button></div>
        {children}
      </div>
    </div>
  );
}

function DaycareDashboard() {
  const [store] = DcUseStore();
  const checkedIn = Object.values(store.attendance || {}).filter((x) => x === "in").length;
  const capacity = Number(store.center.capacity) || 0;
  const enrolled = store.children.length;
  const checklist = [
    { done: store.center.name !== "My Daycare", label: "Add your center details", page: "Settings" },
    { done: enrolled > 0, label: "Add your first enrolled child", page: "Children" },
    { done: store.staff.length > 0, label: "Add teachers and staff", page: "Staff" },
    { done: store.inquiries.length > 0, label: "Start your enrollment pipeline", page: "Enrollment" },
  ];
  const today = new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  return (
    <div className="dc-page">
      <section className="dc-hero">
        <div>
          <div className="dc-eyebrow">{today.toUpperCase()}</div>
          <h1>Good morning, Yahjair.</h1>
          <p>{store.center.name} is ready for the day. Your people, rooms, enrollment, and finances now have one home.</p>
        </div>
        <div className="dc-hero-mark"><span>DC</span><small>DAYCARE OS</small></div>
      </section>

      <div className="dc-kpi-grid">
        <DcKpi label="Enrolled Children" value={enrolled} sub={(capacity - enrolled) + " spots available"} icon="Children" />
        <DcKpi label="Checked In Now" value={checkedIn} sub="today's attendance" icon="Attendance" color="#22C55E" />
        <DcKpi label="Team Members" value={store.staff.length} sub="teachers & staff" icon="Staff" color="#8B5CF6" />
        <DcKpi label="Enrollment Leads" value={store.inquiries.length} sub="families in pipeline" icon="Enrollment" color={DC_GOLD} />
      </div>

      <div className="dc-main-grid">
        <div className="card card-pad dc-panel">
          <div className="dc-panel-head"><div><div className="card-title">Today at a glance</div><div className="faint">Live center operations</div></div><span className="dc-live"><i /> OPEN</span></div>
          <div className="dc-day-grid">
            <button onClick={() => window.GoTo("Attendance")}><span><window.Icons.Attendance size={18} /></span><b>Attendance</b><small>{checkedIn ? checkedIn + " checked in" : "Ready for first check-in"}</small></button>
            <button onClick={() => window.GoTo("Classrooms")}><span><window.Icons.Classrooms size={18} /></span><b>Classrooms</b><small>{store.rooms.length} rooms configured</small></button>
            <button onClick={() => window.GoTo("Meals")}><span><window.Icons.Meals size={18} /></span><b>Meals</b><small>Plan today's menu</small></button>
            <button onClick={() => window.GoTo("Billing")}><span><window.Icons.Billing size={18} /></span><b>Billing</b><small>Review tuition</small></button>
          </div>
        </div>

        <div className="card card-pad dc-panel">
          <div className="dc-panel-head"><div><div className="card-title">Launch checklist</div><div className="faint">Build your daycare workspace</div></div><b>{checklist.filter((x) => x.done).length}/4</b></div>
          <div className="dc-checklist">
            {checklist.map((item) => <button key={item.label} onClick={() => window.GoTo(item.page)} className={item.done ? "done" : ""}>
              <span>{item.done ? "✓" : ""}</span><em>{item.label}</em><window.Icons.ChevronR size={14} />
            </button>)}
          </div>
        </div>
      </div>

      <div className="card card-pad dc-panel">
        <div className="dc-panel-head"><div><div className="card-title">Classroom capacity</div><div className="faint">Enrollment by room</div></div><button className="link" onClick={() => window.GoTo("Classrooms")}>Manage rooms</button></div>
        <div className="dc-room-strip">
          {store.rooms.map((room) => {
            const count = store.children.filter((child) => child.room === room.id).length;
            const pct = Math.min(100, Math.round((count / room.capacity) * 100));
            return <div key={room.id}><div className="dc-room-top"><span style={{ color: room.color }}>{room.name}</span><b>{count}/{room.capacity}</b></div><small>{room.ages}</small><div className="progress"><div style={{ width: pct + "%", background: room.color }} /></div></div>;
          })}
        </div>
      </div>
    </div>
  );
}

function DcChildForm({ rooms, onSave, onClose }) {
  const [form, setForm] = useStateDc({ name: "", guardian: "", room: rooms[0]?.id || "", phone: "" });
  const save = () => { if (form.name.trim()) onSave({ ...form, id: "child-" + Date.now(), status: "enrolled" }); };
  return <DcModal title="Add enrolled child" onClose={onClose}><div className="dc-form-grid">
    <label><span>Child's name *</span><input autoFocus style={dcInput} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
    <label><span>Parent / guardian</span><input style={dcInput} value={form.guardian} onChange={(e) => setForm({ ...form, guardian: e.target.value })} /></label>
    <label><span>Classroom</span><select style={dcInput} value={form.room} onChange={(e) => setForm({ ...form, room: e.target.value })}>{rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
    <label><span>Guardian phone</span><input style={dcInput} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
  </div><div className="dc-modal-actions"><button className="tab" onClick={onClose}>Cancel</button><button className="dc-primary" onClick={save}>Add child</button></div></DcModal>;
}

function DaycareChildren() {
  const [store, setStore] = DcUseStore();
  const [adding, setAdding] = useStateDc(false);
  const add = (child) => { setStore({ ...store, children: [...store.children, child] }); setAdding(false); };
  return <div className="dc-page"><DcPageHead title="Children" action={() => setAdding(true)} actionLabel="Add child" />
    {store.children.length === 0 ? <DcEmpty icon="Children" title="No children added yet" copy="Create a secure roster with each child’s classroom and guardian contact." action={() => setAdding(true)} actionLabel="Add your first child" /> :
      <div className="card dc-table-wrap"><table className="lead-table"><thead><tr><th>Child</th><th>Classroom</th><th>Parent / guardian</th><th>Phone</th><th>Status</th></tr></thead><tbody>{store.children.map((child) => { const room = store.rooms.find((r) => r.id === child.room); return <tr key={child.id}><td><b>{child.name}</b></td><td>{room?.name || "Unassigned"}</td><td>{child.guardian || "—"}</td><td>{child.phone || "—"}</td><td><span className="dc-status">Enrolled</span></td></tr>; })}</tbody></table></div>}
    {adding && <DcChildForm rooms={store.rooms} onSave={add} onClose={() => setAdding(false)} />}
  </div>;
}

function DaycareAttendance() {
  const [store, setStore] = DcUseStore();
  const setStatus = (id, status) => setStore({ ...store, attendance: { ...store.attendance, [id]: status } });
  return <div className="dc-page"><DcPageHead title="Attendance" eyebrow="TODAY'S OPERATIONS" />
    {store.children.length === 0 ? <DcEmpty icon="Attendance" title="Attendance starts with your roster" copy="Add enrolled children first, then check them in and out from this screen." action={() => window.GoTo("Children")} actionLabel="Go to children" /> :
    <div className="dc-attendance-list">{store.children.map((child) => { const status = store.attendance[child.id] || "out"; return <div className="card" key={child.id}><div className="dc-avatar">{child.name.slice(0, 1).toUpperCase()}</div><div><b>{child.name}</b><small>{store.rooms.find((r) => r.id === child.room)?.name || "Unassigned"}</small></div><span className={"dc-presence " + status}>{status === "in" ? "Checked in" : "Not in center"}</span><button className={status === "in" ? "dc-outline" : "dc-primary"} onClick={() => setStatus(child.id, status === "in" ? "out" : "in")}>{status === "in" ? "Check out" : "Check in"}</button></div>; })}</div>}
  </div>;
}

function DaycareClassrooms() {
  const [store] = DcUseStore();
  return <div className="dc-page"><DcPageHead title="Classrooms" />
    <div className="dc-classroom-grid">{store.rooms.map((room) => { const kids = store.children.filter((c) => c.room === room.id); const pct = Math.round((kids.length / room.capacity) * 100); return <div className="card card-pad dc-classroom" key={room.id} style={{ "--room-color": room.color }}><div className="dc-classroom-icon"><window.Icons.Classrooms size={21} /></div><div><h3>{room.name}</h3><p>{room.ages}</p></div><div className="dc-capacity"><span><b>{kids.length}</b> enrolled</span><span>{room.capacity} capacity</span></div><div className="progress"><div style={{ width: pct + "%", background: room.color }} /></div><small>{Math.max(0, room.capacity - kids.length)} spots available</small></div>; })}</div>
  </div>;
}

function DcStaffForm({ onSave, onClose }) {
  const [form, setForm] = useStateDc({ name: "", role: "Teacher", phone: "" });
  const save = () => { if (form.name.trim()) onSave({ ...form, id: "staff-" + Date.now() }); };
  return <DcModal title="Add team member" onClose={onClose}><div className="dc-form-grid"><label><span>Name *</span><input autoFocus style={dcInput} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label><span>Role</span><select style={dcInput} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}><option>Director</option><option>Lead Teacher</option><option>Teacher</option><option>Assistant</option><option>Cook</option></select></label><label><span>Phone</span><input style={dcInput} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label></div><div className="dc-modal-actions"><button className="tab" onClick={onClose}>Cancel</button><button className="dc-primary" onClick={save}>Add member</button></div></DcModal>;
}

function DaycareStaff() {
  const [store, setStore] = DcUseStore(); const [adding, setAdding] = useStateDc(false);
  const add = (member) => { setStore({ ...store, staff: [...store.staff, member] }); setAdding(false); };
  return <div className="dc-page"><DcPageHead title="Staff" action={() => setAdding(true)} actionLabel="Add team member" />{store.staff.length === 0 ? <DcEmpty icon="Staff" title="Build your team roster" copy="Keep your directors, teachers, assistants, and support staff organized here." action={() => setAdding(true)} actionLabel="Add first team member" /> : <div className="dc-staff-grid">{store.staff.map((member) => <div className="card card-pad dc-staff-card" key={member.id}><div className="dc-avatar">{member.name.slice(0, 1).toUpperCase()}</div><div><b>{member.name}</b><small>{member.role}</small></div><span className="dc-status">Active</span></div>)}</div>}{adding && <DcStaffForm onSave={add} onClose={() => setAdding(false)} />}</div>;
}

function DcInquiryForm({ onSave, onClose }) {
  const [form, setForm] = useStateDc({ child: "", guardian: "", phone: "", stage: "inquiry" });
  const save = () => { if (form.child.trim()) onSave({ ...form, id: "inq-" + Date.now() }); };
  return <DcModal title="Add enrollment lead" onClose={onClose}><div className="dc-form-grid"><label><span>Child's name *</span><input autoFocus style={dcInput} value={form.child} onChange={(e) => setForm({ ...form, child: e.target.value })} /></label><label><span>Parent / guardian</span><input style={dcInput} value={form.guardian} onChange={(e) => setForm({ ...form, guardian: e.target.value })} /></label><label><span>Phone</span><input style={dcInput} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label></div><div className="dc-modal-actions"><button className="tab" onClick={onClose}>Cancel</button><button className="dc-primary" onClick={save}>Add lead</button></div></DcModal>;
}

function DaycareEnrollment() {
  const [store, setStore] = DcUseStore(); const [adding, setAdding] = useStateDc(false);
  const stages = [{ id: "inquiry", label: "New Inquiry", color: "#4F7CFF" }, { id: "tour", label: "Tour Scheduled", color: "#8B5CF6" }, { id: "application", label: "Application", color: DC_GOLD }, { id: "enrolled", label: "Ready to Enroll", color: "#22C55E" }];
  const add = (lead) => { setStore({ ...store, inquiries: [...store.inquiries, lead] }); setAdding(false); };
  const advance = (lead) => { const index = stages.findIndex((s) => s.id === lead.stage); const next = stages[Math.min(index + 1, stages.length - 1)].id; setStore({ ...store, inquiries: store.inquiries.map((x) => x.id === lead.id ? { ...x, stage: next } : x) }); };
  return <div className="dc-page"><DcPageHead title="Enrollment" action={() => setAdding(true)} actionLabel="Add inquiry" /><div className="dc-pipeline">{stages.map((stage) => { const leads = store.inquiries.filter((x) => x.stage === stage.id); return <div className="dc-pipe-col" key={stage.id} style={{ "--stage-color": stage.color }}><div className="dc-pipe-head"><b>{stage.label}</b><span>{leads.length}</span></div>{leads.map((lead) => <button className="dc-lead-card" key={lead.id} onClick={() => advance(lead)} title="Click to advance"><b>{lead.child}</b><small>{lead.guardian || "Family inquiry"}</small><em>Advance →</em></button>)}{leads.length === 0 && <div className="dc-pipe-empty">No families here</div>}</div>; })}</div>{adding && <DcInquiryForm onSave={add} onClose={() => setAdding(false)} />}</div>;
}

function DaycareBilling() {
  const [store] = DcUseStore();
  return <div className="dc-page"><DcPageHead title="Billing" /><div className="dc-kpi-grid"><DcKpi label="Tuition Collected" value="$0" sub="this month" icon="Billing" color="#22C55E" /><DcKpi label="Outstanding" value="$0" sub="open balances" icon="Dollar" color="#EF4444" /><DcKpi label="Active Accounts" value={store.children.length} sub="enrolled families" icon="Children" /><DcKpi label="Next Billing Run" value="—" sub="not configured" icon="Calendar" color={DC_GOLD} /></div><DcEmpty icon="Billing" title="Billing is ready to configure" copy="Next, we can connect your tuition platform, set rates by classroom, create invoices, and track family balances." /></div>;
}

function DaycareMeals() {
  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
  return <div className="dc-page"><DcPageHead title="Meals & Menus" /><div className="card card-pad dc-menu"><div className="dc-panel-head"><div><div className="card-title">Weekly menu</div><div className="faint">Breakfast, lunch, and afternoon snack</div></div><span className="dc-week">THIS WEEK</span></div><div className="dc-menu-grid">{days.map((day) => <div key={day}><b>{day}</b><span>Breakfast <em>Not planned</em></span><span>Lunch <em>Not planned</em></span><span>Snack <em>Not planned</em></span></div>)}</div></div></div>;
}

function DaycareCalendar() {
  const month = new Date().toLocaleDateString([], { month: "long", year: "numeric" });
  return <div className="dc-page"><DcPageHead title="Calendar" /><div className="card card-pad dc-calendar"><div className="dc-panel-head"><div><div className="card-title">{month}</div><div className="faint">Tours, staff schedules, closures, and family events</div></div><button className="dc-outline">+ Add event</button></div><div className="dc-calendar-empty"><window.Icons.Calendar size={32} /><b>No events scheduled</b><span>Your daycare calendar is ready for important dates.</span></div></div></div>;
}

function DaycareReports() {
  const reports = [{ icon: "Attendance", title: "Attendance summary", copy: "Daily check-ins, absences, and trends" }, { icon: "Children", title: "Enrollment & capacity", copy: "Occupancy by classroom and available spots" }, { icon: "Billing", title: "Tuition performance", copy: "Collected, outstanding, and aging balances" }, { icon: "Staff", title: "Staffing overview", copy: "Team roster and classroom coverage" }];
  return <div className="dc-page"><DcPageHead title="Reports" /><div className="dc-report-grid">{reports.map((report) => { const Icon = window.Icons[report.icon] || window.Icons.Reports; return <div className="card card-pad" key={report.title}><div className="dc-report-icon"><Icon size={20} /></div><h3>{report.title}</h3><p>{report.copy}</p><button className="link">Available as data is added</button></div>; })}</div></div>;
}

function DaycareSettings() {
  const [store, setStore] = DcUseStore(); const [form, setForm] = useStateDc(store.center); const [saved, setSaved] = useStateDc(false);
  const save = () => { setStore({ ...store, center: { ...form, capacity: Number(form.capacity) || 0 } }); setSaved(true); setTimeout(() => setSaved(false), 2200); };
  return <div className="dc-page"><DcPageHead title="Settings" /><div className="card card-pad dc-settings"><div className="dc-panel-head"><div><div className="card-title">Center profile</div><div className="faint">The basics for your daycare workspace</div></div>{saved && <span className="dc-saved">✓ Saved</span>}</div><div className="dc-form-grid"><label><span>Daycare name</span><input style={dcInput} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label><span>Licensed capacity</span><input type="number" style={dcInput} value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} /></label><label><span>Opening time</span><input style={dcInput} value={form.openTime} onChange={(e) => setForm({ ...form, openTime: e.target.value })} /></label><label><span>Closing time</span><input style={dcInput} value={form.closeTime} onChange={(e) => setForm({ ...form, closeTime: e.target.value })} /></label><label><span>Phone</span><input style={dcInput} value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label><label><span>Address</span><input style={dcInput} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></label></div><div className="dc-settings-actions"><button className="dc-primary" onClick={save}>Save center profile</button></div></div></div>;
}

Object.assign(window, { DaycareDashboard, DaycareChildren, DaycareAttendance, DaycareClassrooms, DaycareStaff, DaycareEnrollment, DaycareBilling, DaycareMeals, DaycareCalendar, DaycareReports, DaycareSettings });
