// daycare_operations.jsx — children, enrollment, attendance, classrooms, staff, schedules.
const { useState: useStateDco, useEffect: useEffectDco } = React;

function DcoChildForm({ classrooms, child, enrollmentMode, initial, onClose, onSaved }) {
  const empty = { first_name: "", last_name: "", preferred_name: "", birth_date: "", classroom_id: "", allergies: "", medical_notes: "", pickup_notes: "", guardian_first_name: "", guardian_last_name: "", guardian_phone: "", guardian_email: "" };
  const [form, setForm] = useStateDco(child ? { ...empty, ...child } : { ...empty, ...(initial || {}) });
  const [busy, setBusy] = useStateDco(false); const [error, setError] = useStateDco("");
  const save = async () => {
    if (!form.first_name.trim() || !form.last_name.trim() || !form.birth_date) { setError("First name, last name, and birth date are required."); return; }
    // Enrollment and parent-login are independent: a child is enrolled the moment this
    // saves, whether or not a guardian login is created in the same step. Guardian
    // fields are optional — only require an email if the owner started filling them in
    // (matches the backend's own save_child validation).
    const guardianStarted = !child && (form.guardian_first_name.trim() || form.guardian_last_name.trim() || form.guardian_phone.trim());
    if (guardianStarted && !form.guardian_email.trim()) { setError("Guardian email is required to create their login — or leave all guardian fields blank to enroll the child now and add a login later."); return; }
    setBusy(true); setError("");
    try { const payload = await window.DcxRequest("/child/save", { body: { child: { ...form, id: child && child.id, active: true } } }); onSaved(payload.provision || null); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };
  return <window.DcxModal wide title={child ? "Edit child record" : enrollmentMode ? "Enroll child" : "Add child"} copy="Saved securely to the shared daycare database." onClose={onClose}>{error && <div className="dc-form-error">{error}</div>}{!child && form.location_name && <div className="dc-form-hint"><window.Icons.Properties size={14}/> Enrolling into <b>{form.location_name}</b> — the center from the family's form.</div>}<div className="dc-section-label">Child information</div><div className="dc-form-grid"><window.DcxField label="First name *"><input autoFocus value={form.first_name} onChange={(e)=>setForm({...form,first_name:e.target.value})}/></window.DcxField><window.DcxField label="Last name *"><input value={form.last_name} onChange={(e)=>setForm({...form,last_name:e.target.value})}/></window.DcxField><window.DcxField label="Preferred name"><input value={form.preferred_name || ""} onChange={(e)=>setForm({...form,preferred_name:e.target.value})}/></window.DcxField><window.DcxField label="Birth date *"><input type="date" value={form.birth_date || ""} onChange={(e)=>setForm({...form,birth_date:e.target.value})}/></window.DcxField><window.DcxField label="Classroom"><select value={form.classroom_id || ""} onChange={(e)=>setForm({...form,classroom_id:e.target.value})}><option value="">Unassigned</option>{classrooms.map((room)=><option key={room.id} value={room.id}>{room.name}</option>)}</select></window.DcxField><window.DcxField label="Allergies"><input value={form.allergies || ""} onChange={(e)=>setForm({...form,allergies:e.target.value})}/></window.DcxField><window.DcxField label="Medical notes" wide><textarea rows="2" value={form.medical_notes || ""} onChange={(e)=>setForm({...form,medical_notes:e.target.value})}/></window.DcxField><window.DcxField label="Authorized pickup notes" wide><textarea rows="2" value={form.pickup_notes || ""} onChange={(e)=>setForm({...form,pickup_notes:e.target.value})}/></window.DcxField><window.DcxField label="Subsidy"><label className="dc-switch-row"><input type="checkbox" checked={Boolean(form.ccis)} onChange={(e)=>setForm({...form,ccis:e.target.checked,ccis_case_id:form.ccis_case_id || "" /* kept when leaving CCIS: past CCIS sheets still need it */})}/><span>CCIS (Child Care Works)</span></label></window.DcxField>{form.ccis && <window.DcxField label="CCIS case ID (optional)"><input maxLength={40} value={form.ccis_case_id || ""} onChange={(e)=>setForm({...form,ccis_case_id:e.target.value})}/></window.DcxField>}</div>{!child && <><div className="dc-section-label">Parent login (optional)</div><div className="dc-form-grid"><window.DcxField label="Guardian first name"><input value={form.guardian_first_name} onChange={(e)=>setForm({...form,guardian_first_name:e.target.value})}/></window.DcxField><window.DcxField label="Guardian last name"><input value={form.guardian_last_name} onChange={(e)=>setForm({...form,guardian_last_name:e.target.value})}/></window.DcxField><window.DcxField label="Guardian phone"><input type="tel" value={form.guardian_phone} onChange={(e)=>setForm({...form,guardian_phone:e.target.value})}/></window.DcxField><window.DcxField label="Guardian email"><input type="email" value={form.guardian_email} onChange={(e)=>setForm({...form,guardian_email:e.target.value})} placeholder="family@example.com"/></window.DcxField></div><div className="dc-form-hint"><window.Icons.Shield size={14}/> The child is enrolled as soon as you save — with or without a parent login. Fill these in now to also generate their Login ID + one-time PIN, or leave blank and add a login later from Parent Logins.</div></>}<div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : child ? "Save changes" : "Create enrollment"}</button></div></window.DcxModal>;
}

function DcoProvisionCredentials({ provision, onClose }) {
  const existing = Boolean(provision && provision.existing);
  const loginId = provision && provision.login_id || "";
  const texted = provision && provision.texted;
  const pin = provision && provision.pin || ""; // a reissued PIN comes back with existing:true
  return <window.DcxModal title={existing ? "Guardian account linked" : "Save these credentials now"} copy={existing ? "The existing guardian account was connected to this enrollment." : "The generated PIN is returned once and is not stored in FORGE."} onClose={onClose}><div className="dc-form-grid"><window.DcxField label={loginId.startsWith("BL-") ? "Login ID" : "Sign-in name"}><input readOnly value={loginId || "—"}/></window.DcxField>{(!existing || pin) && <window.DcxField label="One-time PIN"><input readOnly value={pin || "—"}/></window.DcxField>}</div>{texted && (texted.ok ? <div className="dc-form-hint">Texted to the parent's phone.</div> : <div className="dc-form-error">Not texted: {texted.error || "send failed"}. Share the PIN in person.</div>)}<div className="dc-confirm-note">Share credentials directly with the authorized account holder. Share them only with the parent.</div><div className="dc-modal-actions"><button className="dc-primary" onClick={onClose}>I saved them securely</button></div></window.DcxModal>;
}

function DcoChildrenView({ enrollmentMode = false }) {
  const childrenResource = window.DcxUseResource("/children", "children", 15000);
  const roomsResource = window.DcxUseResource("/classrooms", "classrooms", 30000);
  const [modal, setModal] = useStateDco(null); const [confirm, setConfirm] = useStateDco(null); const [credentials, setCredentials] = useStateDco(null); const [search, setSearch] = useStateDco("");
  const children = Array.isArray(childrenResource.data) ? childrenResource.data : [];
  const rooms = Array.isArray(roomsResource.data) ? roomsResource.data : [];
  const visible = children.filter((child) => (window.DcxChildName(child) + " " + (child.guardian_name || "")).toLowerCase().includes(search.toLowerCase()));
  const refresh = (provision) => { setModal(null); if (provision) setCredentials(provision); childrenResource.refresh(); };
  const deactivate = async () => { try { await window.DcxRequest("/child/deactivate", { body: { child_id: confirm.id } }); setConfirm(null); childrenResource.refresh(); } catch (error) { window.alert(error.message); } };
  const guardianId = (child) => child.guardian_profile_id || (child.guardian_profile && child.guardian_profile.id) || (child.guardian && child.guardian.id) || null;
  const resetPin = async (child) => { const gid = guardianId(child); if (!gid) { window.alert("No parent account is linked to this child yet — add a guardian first."); return; } if (!window.confirm("Reset this parent's login PIN? Their current PIN stops working immediately and a new one is shown once.")) return; try { const payload = await window.DcxRequest("/guardian/reset-pin", { body: { profile_id: gid } }); if (payload.provision) setCredentials(payload.provision); } catch (error) { window.alert(error.message); } };
  const actions = <><div className="dc-search"><window.Icons.Search size={14}/><input value={search} onChange={(e)=>setSearch(e.target.value)} placeholder="Search roster"/></div><button className="dc-primary" onClick={()=>setModal("new")}><window.Icons.Plus size={14}/> {enrollmentMode ? "Enroll family" : "Add child"}</button></>;
  return <div className="dc-page"><window.DcxPageHead title={enrollmentMode ? "Enrollment & Guardians" : "Children"} eyebrow={enrollmentMode ? "FAMILY ONBOARDING" : "SECURE CENTER ROSTER"} copy={enrollmentMode ? "Create a child record and provision guardian access in one flow." : "Shared child, classroom, care, and guardian records."} actions={actions}/><window.DcxState loading={childrenResource.loading || roomsResource.loading} error={childrenResource.error || roomsResource.error} onRetry={()=>{childrenResource.refresh();roomsResource.refresh();}} empty={!children.length} icon="Children" title="No children enrolled" copy="Add the first child to begin attendance and care tracking."><button className="dc-primary" onClick={()=>setModal("new")}>Create first enrollment</button></window.DcxState>{children.length > 0 && <div className="card dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Child</th><th>Classroom</th><th>Age / birthday</th><th>Guardian</th><th>Care flags</th><th></th></tr></thead><tbody>{visible.map((child)=>{ const room = child.classrooms || rooms.find((candidate)=>candidate.id === child.classroom_id); return <tr key={child.id}><td><div className="dc-person"><div className="dc-avatar">{window.DcxChildName(child).slice(0,1)}</div><div><b>{window.DcxChildName(child)}</b><small>{child.active === false ? "Inactive" : "Active enrollment"}</small></div></div></td><td>{room ? room.name : "Unassigned"}</td><td>{window.DcxDate(child.birth_date)}</td><td>{child.guardian_name || window.DcxName(child.guardian || child.guardian_profile, "Not provisioned")}</td><td><div className="dc-flags">{child.ccis && <span title={child.ccis_case_id ? "CCIS case " + child.ccis_case_id : "CCIS (Child Care Works)"}>CCIS</span>}{child.allergies && <span className="warn">Allergies</span>}{child.medical_notes && <span>Medical</span>}{!child.ccis && !child.allergies && !child.medical_notes && <span className="quiet">None</span>}</div></td><td><div className="dc-row-actions"><button onClick={()=>setModal(child)}>Edit</button>{guardianId(child) && <button onClick={()=>resetPin(child)}>Reset login</button>}{child.active !== false && <button className="danger" onClick={()=>setConfirm(child)}>Deactivate</button>}</div></td></tr>;})}</tbody></table>{!visible.length && <div className="dc-inline-empty">No roster records match that search.</div>}</div>}{modal && <DcoChildForm classrooms={rooms} child={modal === "new" ? null : modal} enrollmentMode={enrollmentMode} onClose={()=>setModal(null)} onSaved={refresh}/>} {confirm && <window.DcxConfirm danger title={"Deactivate " + window.DcxChildName(confirm) + "?"} copy="Their history remains available, but they will leave the active roster." confirmLabel="Deactivate child" onClose={()=>setConfirm(null)} onConfirm={deactivate}/>} {credentials && <DcoProvisionCredentials provision={credentials} onClose={()=>setCredentials(null)}/>}</div>;
}

function DaycareChildren() { return <DcoChildrenView/>; }
function DaycareEnrollment() { return <DcoChildrenView enrollmentMode/>; }

// Classic red/yellow/green clip chart — one tap per color. Same model as the
// parent/staff app: append-only moves, newest wins, green is the daily default.
const DCO_BEHAVIOR = [["green", "Green"], ["yellow", "Yellow"], ["red", "Red"]];
function DcoBehaviorDots({ color, busy, onSet }) {
  return <div className="dc-beh-dots" role="group" aria-label={"Behavior chart — on " + color}>{DCO_BEHAVIOR.map(([value, label])=><button key={value} type="button" className={"dc-beh-dot " + value + (color === value ? " active" : "")} disabled={busy} aria-pressed={color === value} aria-label={"Move to " + label} title={label} onClick={()=>onSet(value)}/>)}</div>;
}

function dcoTime(value) {
  const parsed = value ? new Date(value) : null;
  return parsed && !Number.isNaN(parsed.getTime()) ? parsed.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "—";
}

// Key in one child's day from the signed paper sheet. The DB (record_paper_attendance)
// decides what is allowed and says why when it refuses — that sentence is shown as-is.
function DcoPaperForm({ children, onClose, onSaved }) {
  const [form, setForm] = useStateDco({ child_id: "", date: window.DcxToday(), time_in: "", time_out: "", note: "" });
  const [busy, setBusy] = useStateDco(false); const [error, setError] = useStateDco("");
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
  const save = async () => {
    if (!form.child_id || !form.date || !form.time_in) { setError("Child, date and arrival time are required."); return; }
    setBusy(true); setError("");
    try { await window.DcxRequest("/attendance/paper", { body: form }); onSaved(form.date); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };
  return <window.DcxModal title="Key in paper sheet" copy="Times as written on the signed sheet. The day is marked Paper everywhere it is reported." onClose={onClose}>
    {error && <div className="dc-form-error">{error}</div>}
    <div className="dc-form-grid">
      <window.DcxField label="Child *" wide><select autoFocus value={form.child_id} onChange={set("child_id")}><option value="">Choose child</option>{children.map((child)=><option key={child.id} value={child.id}>{window.DcxChildName(child)}</option>)}</select></window.DcxField>
      <window.DcxField label="Date *"><input type="date" max={window.DcxToday()} value={form.date} onChange={set("date")}/></window.DcxField>
      <window.DcxField label="Arrival time *"><input type="time" value={form.time_in} onChange={set("time_in")}/></window.DcxField>
      <window.DcxField label="Pickup time"><input type="time" value={form.time_out} onChange={set("time_out")}/></window.DcxField>
      <window.DcxField label="Note" wide><input maxLength={300} value={form.note} onChange={set("note")} placeholder="Optional"/></window.DcxField>
    </div>
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save paper entry"}</button></div>
  </window.DcxModal>;
}

function DaycareAttendance() {
  const [date, setDate] = useStateDco(window.DcxToday());
  const childrenResource = window.DcxUseResource("/children", "children", 15000);
  const attendanceResource = window.DcxUseResource("/attendance?date=" + encodeURIComponent(date), "attendance", 10000);
  const behaviorResource = window.DcxUseResource("/behavior?date=" + encodeURIComponent(date), "behavior", 10000);
  const [working, setWorking] = useStateDco(""); const [confirmAll, setConfirmAll] = useStateDco(false); const [paper, setPaper] = useStateDco(false);
  const children = Array.isArray(childrenResource.data) ? childrenResource.data.filter((child)=>child.active !== false) : [];
  const records = Array.isArray(attendanceResource.data) ? attendanceResource.data : [];
  const behavior = Array.isArray(behaviorResource.data) ? behaviorResource.data : [];
  const recordFor = (id) => records.find((record)=>record.child_id === id || record.childId === id);
  // Rows arrive oldest-first, so the last matching move is the child's color now.
  const behaviorColor = (id) => { const moves = behavior.filter((move)=>move.child_id === id); return moves.length ? moves[moves.length-1].color : "green"; };
  const setBehavior = async (child, color) => { if (behaviorColor(child.id) === color) return; setWorking("beh-"+child.id); try { await window.DcxRequest("/behavior/set", { body: { childId: child.id, date, color } }); behaviorResource.refresh(); } catch (error) { window.alert(error.message); } finally { setWorking(""); } };
  // Closing a PAST day asks for the real pickup time (the server refuses "now" for an old day).
  const act = async (child, action) => { let time; if (action === "check-out" && date < window.DcxToday()) { time = window.prompt("Pickup time on " + date + " (24-hour HH:MM, e.g. 17:15)"); if (!time) return; } setWorking(child.id); try { await window.DcxRequest("/attendance/set", { body: { childId: child.id, date, action, time } }); attendanceResource.refresh(); } catch (error) { window.alert(error.message); } finally { setWorking(""); } };
  // Declining clears the family's request; the child stays on site and the parent is told.
  const decline = async (record) => { setWorking(record.child_id); try { await window.DcxRequest("/attendance/decline-pickup", { body: { attendance_id: record.id } }); attendanceResource.refresh(); } catch (error) { window.alert(error.message); } finally { setWorking(""); } };
  const signOutAll = async () => { setWorking("all"); try { await window.DcxRequest("/attendance/sign-out-all", { body: { date } }); setConfirmAll(false); attendanceResource.refresh(); } catch (error) { window.alert(error.message); } finally { setWorking(""); } };
  const present = records.filter((record)=>record.status === "present" || (record.checked_in_at && !record.checked_out_at));
  // A family waiting at the door is confirmed one by one, never by "Sign out all" (the server skips them too).
  const bulk = present.filter((record)=>!record.pickup_requested_at); const waiting = present.length - bulk.length;
  return <div className="dc-page"><window.DcxPageHead title="Attendance" eyebrow="LIVE CHECK-IN / OUT" copy="Every change is written to the shared daily attendance record." actions={<><input className="dc-date-input" type="date" value={date} onChange={(e)=>setDate(e.target.value)}/><button className="dc-outline" onClick={()=>setPaper(true)}>Key in paper sheet</button>{bulk.length > 0 && <button className="dc-outline" onClick={()=>setConfirmAll(true)}>Sign out all ({bulk.length})</button>}</>}/><div className="dc-attendance-summary"><span><i className="green"/>{present.length} present</span><span><i/>{Math.max(0, children.length-present.length)} not on site</span><span>{children.length} active children</span></div><window.DcxState loading={childrenResource.loading || attendanceResource.loading} error={childrenResource.error || attendanceResource.error} onRetry={()=>{childrenResource.refresh();attendanceResource.refresh();behaviorResource.refresh();}} empty={!children.length} icon="Attendance" title="Attendance starts with enrollment" copy="Enroll a child before recording check-in and check-out."><button className="dc-primary" onClick={()=>window.GoTo("Enrollment")}>Open enrollment</button></window.DcxState>{children.length > 0 && <div className="dc-attendance-list">{children.map((child)=>{ const record = recordFor(child.id); const isIn = Boolean(record && (record.status === "present" || (record.checked_in_at && !record.checked_out_at))); const pickup = Boolean(record && record.pickup_requested_at && !record.checked_out_at); return <div className="card" key={child.id}><div className="dc-avatar">{window.DcxChildName(child).slice(0,1)}</div><div><b>{window.DcxChildName(child)}</b><small>{child.classrooms && child.classrooms.name || "Unassigned"}</small></div><div className="dc-attendance-times"><span>{record && record.checked_in_at ? "In " + window.DcxDate(record.checked_in_at,true) : "Not checked in"}</span>{record && record.checked_out_at && <small>Out {window.DcxDate(record.checked_out_at,true)}</small>}{(pickup || (record && record.source === "paper")) && <div className="dc-flags">{pickup && <span className="warn">Pickup requested by {record.pickup_request_signature || "family"} at {dcoTime(record.pickup_requested_at)}</span>}{record.source === "paper" && <span>Paper</span>}</div>}{pickup && <div className="dc-row-actions" style={{ justifyContent: "flex-start", marginTop: 5 }}><button className="danger" disabled={working===child.id} onClick={()=>decline(record)}>Decline pickup</button></div>}</div><DcoBehaviorDots color={behaviorColor(child.id)} busy={working==="beh-"+child.id} onSet={(color)=>setBehavior(child,color)}/><span className={"dc-presence " + (isIn ? "in" : "out")}>{isIn ? "On site" : "Off site"}</span><button className={isIn && !pickup ? "dc-outline" : "dc-primary"} disabled={working===child.id} onClick={()=>act(child,isIn ? "check-out" : "check-in")}>{working===child.id ? "Saving…" : pickup ? "Confirm pickup" : isIn ? "Check out" : "Check in"}</button></div>;})}</div>}{confirmAll && <window.DcxConfirm title="Sign out everyone?" copy={"This records a check-out time for " + bulk.length + " " + (bulk.length === 1 ? "child" : "children") + " on site." + (waiting ? " " + waiting + " with a family waiting at the door " + (waiting === 1 ? "is" : "are") + " left for Confirm pickup." : "")} confirmLabel="Sign out all" busy={working==="all"} onClose={()=>setConfirmAll(false)} onConfirm={signOutAll}/>}{paper && <DcoPaperForm children={children} onClose={()=>setPaper(false)} onSaved={(day)=>{ setPaper(false); if (day === date) attendanceResource.refresh(); else setDate(day); }}/>}</div>;
}

// ---- Time Sheets: CCIS + private-pay hours by classroom. The `timesheets` edge function is
// the ONLY place hours are totalled — this page renders its numbers, never recomputes them.
const DCO_TS_COLS = [["days_attended", "Days attended"], ["days_absent", "Days absent"], ["hours", "Hours"], ["full_days", "Full days"], ["part_days", "Part days"], ["paper_days", "Paper days"], ["open_days", "Open"]];
const dcoIso = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
const dcoParts = (iso) => String(iso || "").split("-").map(Number);
function dcoRange(mode, iso) {
  const [y, m, d] = dcoParts(iso);
  if (!y || !m || !d) return null;
  if (mode === "month") return { start: dcoIso(new Date(y, m - 1, 1)), end: dcoIso(new Date(y, m, 0)) };
  const back = (new Date(y, m - 1, d).getDay() + 6) % 7; // Monday-Sunday week
  return { start: dcoIso(new Date(y, m - 1, d - back)), end: dcoIso(new Date(y, m - 1, d - back + 6)) };
}
const dcoDay = (iso, opts) => { const [y, m, d] = dcoParts(iso); return new Date(y, m - 1, d).toLocaleDateString("en-US", opts || { weekday: "short", month: "short", day: "numeric" }); };
const dcoMonth = (iso) => dcoDay(iso, { month: "long", year: "numeric" });
const dcoVal = (key, value) => key === "hours" ? (Number(value) || 0).toFixed(1) : (value == null ? 0 : value);
function dcoDownload(payload) {
  const bytes = Uint8Array.from(atob(payload.pdf_base64 || ""), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
  const link = document.createElement("a");
  link.href = url; link.download = payload.filename || "time-sheet.pdf";
  document.body.appendChild(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// A private-pay month becomes an invoice. The owner types the amount — never prefilled.
function DcoTimesheetInvoice({ child, period, onClose, onSaved }) {
  const [y, m] = dcoParts(period.start);
  const [form, setForm] = useStateDco({ description: "Tuition — " + dcoMonth(period.start) + " · " + child.days_attended + " days · " + dcoVal("hours", child.hours) + " hrs", amount: "", due_on: dcoIso(new Date(y, m, 1)) });
  const [busy, setBusy] = useStateDco(false); const [error, setError] = useStateDco("");
  const save = async () => {
    if (!form.description.trim() || !(Number(form.amount) > 0)) { setError("A description and a positive amount are required."); return; }
    if (!form.due_on || form.due_on < window.DcxToday()) { setError("Pick a due date of today or later — the invoice is issued today."); return; }
    setBusy(true); setError("");
    try { await window.DcxRequest("/invoice/save", { body: { invoice: { guardian_id: child.guardian_profile_id, child_id: child.id, description: form.description, amount: Number(form.amount), status: "due", issued_on: window.DcxToday(), due_on: form.due_on, period_start: period.start, period_end: period.end } } }); onSaved(); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };
  return <window.DcxModal title={"Invoice · " + child.name} copy="Records an amount due on Billing; it does not charge a card." onClose={onClose}>
    {error && <div className="dc-form-error">{error}</div>}
    <div className="dc-form-grid">
      <window.DcxField label="Description" wide><input value={form.description} onChange={(e)=>setForm({...form,description:e.target.value})}/></window.DcxField>
      <window.DcxField label="Amount *"><input autoFocus type="number" min="0.01" step="0.01" value={form.amount} onChange={(e)=>setForm({...form,amount:e.target.value})} placeholder="0.00"/></window.DcxField>
      <window.DcxField label="Due date"><input type="date" value={form.due_on} onChange={(e)=>setForm({...form,due_on:e.target.value})}/></window.DcxField>
    </div>
    <div className="dc-form-hint">Bills {dcoDay(period.start)} – {dcoDay(period.end)}. The family sees these days on the invoice.</div>
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Create invoice"}</button></div>
  </window.DcxModal>;
}

function DcoBlankSheet({ rooms, onClose }) {
  const [date, setDate] = useStateDco(window.DcxToday()); const [room, setRoom] = useStateDco("");
  const [busy, setBusy] = useStateDco(false); const [error, setError] = useStateDco("");
  const download = async () => {
    setBusy(true); setError("");
    try { dcoDownload(await window.DcxRequest("/timesheets", { body: { mode: "blank", date, classroom_id: room || null } })); onClose(); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };
  return <window.DcxModal title="Blank paper sign-in sheet" copy="Names pre-filled; In, Out and Signature left blank for families to sign by hand." onClose={onClose}>
    {error && <div className="dc-form-error">{error}</div>}
    <div className="dc-form-grid">
      <window.DcxField label="Date"><input type="date" value={date} onChange={(e)=>setDate(e.target.value)}/></window.DcxField>
      <window.DcxField label="Classroom"><select value={room} onChange={(e)=>setRoom(e.target.value)}><option value="">All classrooms</option>{rooms.map((r)=><option key={r.id} value={r.id}>{r.name}</option>)}</select></window.DcxField>
    </div>
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy || !date} onClick={download}>{busy ? "Building…" : "Download PDF"}</button></div>
  </window.DcxModal>;
}

function DaycareTimesheets() {
  const roomsResource = window.DcxUseResource("/classrooms", "classrooms", 0);
  const locationsResource = window.DcxUseResource("/locations", "locations", 0);
  const rooms = (Array.isArray(roomsResource.data) ? roomsResource.data : []).filter((room)=>room.active !== false);
  const current = (Array.isArray(locationsResource.data) ? locationsResource.data : []).find((row)=>row.current);
  const [mode, setMode] = useStateDco("week"); const [date, setDate] = useStateDco(window.DcxToday());
  const [room, setRoom] = useStateDco(""); const [group, setGroup] = useStateDco("all");
  const [sheet, setSheet] = useStateDco(null); const [busy, setBusy] = useStateDco(""); const [error, setError] = useStateDco("");
  const [open, setOpen] = useStateDco({}); const [invoice, setInvoice] = useStateDco(null); const [blank, setBlank] = useStateDco(false);
  const [fullDay, setFullDay] = useStateDco(""); const [fullDayNote, setFullDayNote] = useStateDco("");
  const range = dcoRange(mode, date);
  const request = (kind) => ({ mode: kind, start: range.start, end: range.end, classroom_id: room || null, group });
  const run = async (kind) => {
    if (!range) { setError("Pick a date first."); return; }
    setBusy(kind); setError("");
    try {
      // The PDF is the sheet on screen (its own period / classroom / group), not whatever the
      // controls were changed to after Calculate.
      const body = kind === "pdf" && sheet ? { mode: "pdf", start: sheet.period.start, end: sheet.period.end, classroom_id: sheet.classroom_id || null, group: sheet.group } : request(kind);
      const payload = await window.DcxRequest("/timesheets", { body });
      if (kind === "pdf") { dcoDownload(payload); return; }
      setSheet({ ...payload, view: mode }); setOpen({});
      if (payload.location && payload.location.full_day_hours != null) setFullDay(String(payload.location.full_day_hours));
    } catch (requestError) { setError(requestError.message); } finally { setBusy(""); }
  };
  const saveFullDay = async () => {
    const hours = Number(fullDay);
    if (!(hours >= 1 && hours <= 12)) { setFullDayNote("Enter 1 to 12 hours."); return; }
    setBusy("hours"); setFullDayNote("");
    try { await window.DcxRequest("/settings/full-day-hours", { body: { full_day_hours: hours } }); setFullDayNote("Saved — applies to the next Calculate."); }
    catch (requestError) { setFullDayNote(requestError.message); } finally { setBusy(""); }
  };
  const actions = <><div className="dc-locbar-tabs">{[["week", "Week"], ["month", "Month"]].map(([value, label])=><button key={value} className={mode === value ? "active" : ""} onClick={()=>setMode(value)}>{label}</button>)}</div>
    <input className="dc-date-input" type="date" value={date} onChange={(e)=>setDate(e.target.value)}/>
    <select style={{ width: "auto" }} value={room} onChange={(e)=>setRoom(e.target.value)} aria-label="Classroom"><option value="">All classrooms</option>{rooms.map((r)=><option key={r.id} value={r.id}>{r.name}</option>)}</select>
    <select style={{ width: "auto" }} value={group} onChange={(e)=>setGroup(e.target.value)} aria-label="Group"><option value="all">All children</option><option value="ccis">CCIS</option><option value="private">Private pay</option></select>
    <button className="dc-primary" disabled={Boolean(busy)} onClick={()=>run("summary")}>{busy === "summary" ? "Calculating…" : "Calculate"}</button></>;
  const monthView = sheet && sheet.view === "month";
  const childRow = (child) => {
    const expanded = Boolean(open[child.id]);
    // Only the Private pay sheet for all classrooms: it holds only private-pay days, so a child
    // who was on CCIS earlier in the month is never billed for subsidized days.
    // A child who moved rooms is one line per room: the button sits on the first line only and
    // the invoice totals every line.
    const lines = sheet.classrooms.flatMap((room) => room.children.filter((line) => line.id === child.id));
    const invoiceable = monthView && !child.ccis && sheet.group === "private" && !sheet.classroom_id && lines[0] === child;
    const whole = { ...child, days_attended: lines.reduce((sum, line) => sum + line.days_attended, 0), hours: lines.reduce((sum, line) => sum + Number(line.hours || 0), 0) };
    return <React.Fragment key={child.id}>
      <tr>
        <td><b>{child.name}</b>{child.ccis && <div className="dc-flags"><span>CCIS</span></div>}{child.ccis && child.ccis_case_id && <small>Case {child.ccis_case_id}</small>}{child.active === false && <small>Inactive</small>}</td>
        {DCO_TS_COLS.map(([key])=><td key={key} className="tabnum">{dcoVal(key, child[key])}</td>)}
        <td><div className="dc-row-actions"><button onClick={()=>setOpen({ ...open, [child.id]: !expanded })}>{expanded ? "Hide days" : "Days"}</button>{invoiceable && <button disabled={!child.guardian_profile_id} title={child.guardian_profile_id ? "" : "Link a parent login to this child first"} onClick={()=>setInvoice(whole)}>Create invoice</button>}</div>{invoiceable && !child.guardian_profile_id && <small>No parent login linked</small>}</td>
      </tr>
      {expanded && <tr><td colSpan={DCO_TS_COLS.length + 2}>
        {child.days && child.days.length ? <table className="lead-table"><thead><tr><th>Date</th><th>In</th><th>Out</th><th>Hours</th><th></th></tr></thead><tbody>{child.days.map((day)=><tr key={day.date}><td>{dcoDay(day.date)}</td><td>{dcoTime(day.in)}</td><td>{day.out ? dcoTime(day.out) : "—"}</td><td className="tabnum">{day.hours == null ? "—" : dcoVal("hours", day.hours)}</td><td><div className="dc-flags">{day.kind && <span className="quiet">{day.kind === "full" ? "Full day" : "Part day"}</span>}{day.source === "paper" && <span>Paper</span>}{day.pending_pickup ? <span className="warn">Pickup pending</span> : day.open && <span className="warn">Not signed out</span>}</div></td></tr>)}</tbody></table> : <div className="dc-inline-empty">No visits in this period.</div>}
        {child.absent_dates && child.absent_dates.length > 0 && <small>Absent: {child.absent_dates.map((d)=>dcoDay(d, { month: "short", day: "numeric" })).join(", ")}</small>}
      </td></tr>}
    </React.Fragment>;
  };
  const totalsRow = (label, totals) => <tr><td><b>{label}</b><small>{totals.children} children</small></td>{DCO_TS_COLS.map(([key])=><td key={key} className="tabnum"><b>{dcoVal(key, totals[key])}</b></td>)}<td></td></tr>;
  const head = <thead><tr><th>Child</th>{DCO_TS_COLS.map(([key, label])=><th key={key}>{label}</th>)}<th></th></tr></thead>;
  return <div className="dc-page">
    <window.DcxPageHead title="Time Sheets" eyebrow="CCIS & PRIVATE-PAY HOURS" copy={"Hours by child and classroom for " + ((sheet && sheet.location && sheet.location.name) || (current && current.name) || "the active center") + (range ? " · " + dcoDay(range.start) + " – " + dcoDay(range.end) : "") + "."} actions={actions}/>
    <div className="dc-attendance-summary">
      <span>Full day = <input type="number" min="1" max="12" step="0.5" value={fullDay} placeholder="5" onChange={(e)=>{ setFullDay(e.target.value); setFullDayNote(""); }} style={{ width: 64 }} aria-label="Full day hours"/> hours</span>
      <button className="dc-outline" disabled={Boolean(busy)} onClick={saveFullDay}>{busy === "hours" ? "Saving…" : "Save"}</button>
      {fullDayNote && <span>{fullDayNote}</span>}
      <span style={{ marginLeft: "auto" }}><button className="dc-outline" disabled={!sheet || Boolean(busy)} onClick={()=>run("pdf")}>{busy === "pdf" ? "Building…" : "Download PDF"}</button> <button className="dc-outline" onClick={()=>setBlank(true)}>Print blank paper sheet</button></span>
    </div>
    {error && <div className="dc-form-error">{error}</div>}
    {!sheet ? <div className="card dc-state"><window.Icons.TimeSheets size={27}/><b>Pick a week or month</b><span>Choose the period, classroom and group, then Calculate.</span></div> : <>
      {sheet.classrooms.map((classroom)=><div key={classroom.id || "unassigned"}>
        <div className="dc-section-title"><b>{classroom.name}</b><span>{dcoDay(sheet.period.start)} – {dcoDay(sheet.period.end)} · {sheet.period.weekdays} weekdays</span></div>
        <div className="card dc-table-wrap"><table className="lead-table dc-table">{head}<tbody>{classroom.children.map(childRow)}{totalsRow("Classroom total", classroom.totals)}</tbody></table>{!classroom.children.length && <div className="dc-inline-empty">No children in this group.</div>}</div>
      </div>)}
      {!sheet.classrooms.length && <div className="card dc-state"><b>No children match</b><span>Try another classroom or group.</span></div>}
      <div className="dc-section-title"><b>Center totals</b><span>{sheet.location && sheet.location.name} · full day ≥ {sheet.location && sheet.location.full_day_hours} hrs</span></div>
      <div className="card dc-table-wrap"><table className="lead-table dc-table">{head}<tbody>{totalsRow("Center total", sheet.totals)}</tbody></table></div>
    </>}
    {invoice && <DcoTimesheetInvoice child={invoice} period={sheet.period} onClose={()=>setInvoice(null)} onSaved={()=>{ setInvoice(null); window.alert("Invoice created — it is on Billing."); }}/>}
    {blank && <DcoBlankSheet rooms={rooms} onClose={()=>setBlank(false)}/>}
  </div>;
}

function DcoClassroomForm({ room, onClose, onSaved }) {
  const [form,setForm]=useStateDco(room ? {...room} : {name:"",age_group:"",capacity:10,ratio_children:8,color:"#2DD4BF"}); const [busy,setBusy]=useStateDco(false); const [error,setError]=useStateDco("");
  const save=async()=>{ if(!form.name.trim()){setError("Classroom name is required.");return;} setBusy(true);try{await window.DcxRequest("/classroom/save",{body:{classroom:{...form,capacity:Number(form.capacity),ratio_children:Number(form.ratio_children)}}});onSaved();}catch(requestError){setError(requestError.message);}finally{setBusy(false);}};
  return <window.DcxModal title={room?"Edit classroom":"Add classroom"} onClose={onClose}>{error&&<div className="dc-form-error">{error}</div>}<div className="dc-form-grid"><window.DcxField label="Room name"><input autoFocus value={form.name} onChange={(e)=>setForm({...form,name:e.target.value})}/></window.DcxField><window.DcxField label="Age group"><input value={form.age_group||""} onChange={(e)=>setForm({...form,age_group:e.target.value})}/></window.DcxField><window.DcxField label="Capacity"><input type="number" min="1" value={form.capacity} onChange={(e)=>setForm({...form,capacity:e.target.value})}/></window.DcxField><window.DcxField label="Children per staff"><input type="number" min="1" value={form.ratio_children||""} onChange={(e)=>setForm({...form,ratio_children:e.target.value})}/></window.DcxField><window.DcxField label="Room color"><input type="color" value={form.color||"#2DD4BF"} onChange={(e)=>setForm({...form,color:e.target.value})}/></window.DcxField></div><div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy?"Saving…":"Save classroom"}</button></div></window.DcxModal>;
}

function DaycareClassrooms() {
  const roomsResource=window.DcxUseResource("/classrooms","classrooms",15000); const [modal,setModal]=useStateDco(null); const [confirm,setConfirm]=useStateDco(null); const rooms=Array.isArray(roomsResource.data)?roomsResource.data:[];
  const archive=async()=>{try{await window.DcxRequest("/classroom/archive",{body:{classroom_id:confirm.id}});setConfirm(null);roomsResource.refresh();}catch(error){window.alert(error.message);}};
  return <div className="dc-page"><window.DcxPageHead title="Classrooms" copy="Capacity, ratios, assignments, and soft archival." actions={<button className="dc-primary" onClick={()=>setModal("new")}><window.Icons.Plus size={14}/> Add classroom</button>}/><window.DcxState loading={roomsResource.loading} error={roomsResource.error} onRetry={roomsResource.refresh} empty={!rooms.length} icon="Classrooms" title="No active classrooms" copy="Create the rooms used for enrollment and staff coverage."><button className="dc-primary" onClick={()=>setModal("new")}>Add first classroom</button></window.DcxState>{rooms.length>0&&<div className="dc-classroom-grid">{rooms.map((room)=>{const count=Number(room.enrolled_count??room.child_count??(room.children||[]).length??0);const cap=Number(room.capacity)||0;const color=room.color||window.DCX_ACCENT;return <div className="card card-pad dc-classroom" key={room.id} style={{"--room-color":color}}><div className="dc-classroom-top"><div className="dc-classroom-icon"><window.Icons.Classrooms size={21}/></div><div className="dc-row-actions"><button onClick={()=>setModal(room)}>Edit</button><button className="danger" onClick={()=>setConfirm(room)}>Archive</button></div></div><div><h3>{room.name}</h3><p>{room.age_group||"Age group not set"}</p></div><div className="dc-capacity"><span><b>{count}</b> enrolled</span><span>{cap} capacity</span></div><div className="progress"><div style={{width:Math.min(100,cap?count/cap*100:0)+"%",background:color}}/></div><small>{Math.max(0,cap-count)} spots available · 1:{room.ratio_children||"—"} ratio</small></div>;})}</div>}{modal&&<DcoClassroomForm room={modal==="new"?null:modal} onClose={()=>setModal(null)} onSaved={()=>{setModal(null);roomsResource.refresh();}}/>}{confirm&&<window.DcxConfirm danger title={"Archive "+confirm.name+"?"} copy="The room leaves active operations. Existing history remains intact." confirmLabel="Archive classroom" onClose={()=>setConfirm(null)} onConfirm={archive}/>}</div>;
}

function DcoStaffForm({ member, classrooms, onClose, onSaved }) {
  const profile=member&&member.profiles||{}; const [form,setForm]=useStateDco(member?{...member,first_name:profile.first_name||"",last_name:profile.last_name||"",phone:profile.phone||"",classroom_ids:(member.staff_classrooms||[]).map((x)=>x.classroom_id)}:{first_name:"",last_name:"",phone:"",job_title:"Teacher",hourly_rate:"",hire_date:"",color:"#8B5CF6",classroom_ids:[]}); const [busy,setBusy]=useStateDco(false); const [error,setError]=useStateDco("");
  const save=async()=>{if(!form.first_name.trim()||!form.last_name.trim()){setError("First and last name are required.");return;}setBusy(true);try{const payload=await window.DcxRequest("/staff/save",{body:{staff:{...form,id:member&&member.id,hourly_rate:form.hourly_rate===""?null:Number(form.hourly_rate)}}});onSaved(payload.provision||null);}catch(requestError){setError(requestError.message);}finally{setBusy(false);}};
  const toggleRoom=(id)=>setForm({...form,classroom_ids:form.classroom_ids.includes(id)?form.classroom_ids.filter((item)=>item!==id):[...form.classroom_ids,id]});
  return <window.DcxModal wide title={member?"Edit team member":"Add team member"} onClose={onClose}>{error&&<div className="dc-form-error">{error}</div>}<div className="dc-form-grid"><window.DcxField label="First name"><input autoFocus value={form.first_name} onChange={(e)=>setForm({...form,first_name:e.target.value})}/></window.DcxField><window.DcxField label="Last name"><input value={form.last_name} onChange={(e)=>setForm({...form,last_name:e.target.value})}/></window.DcxField><window.DcxField label="Job title"><input value={form.job_title||""} onChange={(e)=>setForm({...form,job_title:e.target.value})}/></window.DcxField><window.DcxField label="Phone"><input value={form.phone||""} onChange={(e)=>setForm({...form,phone:e.target.value})}/></window.DcxField><window.DcxField label="Hourly rate"><input type="number" min="0" step="0.01" value={form.hourly_rate??""} onChange={(e)=>setForm({...form,hourly_rate:e.target.value})}/></window.DcxField><window.DcxField label="Hire date"><input type="date" value={form.hire_date||""} onChange={(e)=>setForm({...form,hire_date:e.target.value})}/></window.DcxField><window.DcxField label="Classroom assignments" wide><div className="dc-check-grid">{classrooms.map((room)=><label key={room.id}><input type="checkbox" checked={form.classroom_ids.includes(room.id)} onChange={()=>toggleRoom(room.id)}/><span>{room.name}</span></label>)}</div></window.DcxField></div><div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy?"Saving…":"Save team member"}</button></div></window.DcxModal>;
}

function DcoScheduleForm({ member, onClose, onSaved }) {
  const existing=member.staff_schedules||[]; const [rows,setRows]=useStateDco(existing.length?existing:[{weekday:1,start_time:"08:00",end_time:"17:00"}]); const [busy,setBusy]=useStateDco(false); const days=["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
  const save=async()=>{setBusy(true);try{await window.DcxRequest("/schedule/save",{body:{staff_id:member.id,schedules:rows}});onSaved();}catch(error){window.alert(error.message);}finally{setBusy(false);}};
  return <window.DcxModal title={"Schedule · "+window.DcxName(member)} onClose={onClose}><div className="dc-schedule-list">{rows.map((row,index)=><div key={row.id||index}><select value={row.weekday} onChange={(e)=>setRows(rows.map((item,i)=>i===index?{...item,weekday:Number(e.target.value)}:item))}>{days.map((day,i)=><option key={day} value={i}>{day}</option>)}</select><input type="time" value={(row.start_time||"").slice(0,5)} onChange={(e)=>setRows(rows.map((item,i)=>i===index?{...item,start_time:e.target.value}:item))}/><span>to</span><input type="time" value={(row.end_time||"").slice(0,5)} onChange={(e)=>setRows(rows.map((item,i)=>i===index?{...item,end_time:e.target.value}:item))}/><button onClick={()=>setRows(rows.filter((_,i)=>i!==index))}>✕</button></div>)}</div><button className="dc-inline-add" onClick={()=>setRows([...rows,{weekday:1,start_time:"08:00",end_time:"17:00"}])}>+ Add schedule day</button><div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy?"Saving…":"Save schedule"}</button></div></window.DcxModal>;
}

function DaycareStaff() {
  const staffResource=window.DcxUseResource("/staff","staff",15000); const roomsResource=window.DcxUseResource("/classrooms","classrooms",30000); const [modal,setModal]=useStateDco(null);const [schedule,setSchedule]=useStateDco(null);const [confirm,setConfirm]=useStateDco(null);const [credentials,setCredentials]=useStateDco(null); const staff=Array.isArray(staffResource.data)?staffResource.data:[];const rooms=Array.isArray(roomsResource.data)?roomsResource.data:[];
  const deactivate=async()=>{try{await window.DcxRequest("/staff/deactivate",{body:{staff_id:confirm.id}});setConfirm(null);staffResource.refresh();}catch(error){window.alert(error.message);}};
  return <div className="dc-page"><window.DcxPageHead title="Staff & Schedules" copy="Profiles, classroom coverage, hours, and active status." actions={<button className="dc-primary" onClick={()=>setModal("new")}><window.Icons.Plus size={14}/> Add team member</button>}/><window.DcxState loading={staffResource.loading||roomsResource.loading} error={staffResource.error||roomsResource.error} onRetry={()=>{staffResource.refresh();roomsResource.refresh();}} empty={!staff.length} icon="Staff" title="No active staff" copy="Add directors, teachers, assistants, and support staff."><button className="dc-primary" onClick={()=>setModal("new")}>Add first team member</button></window.DcxState>{staff.length>0&&<div className="dc-staff-grid">{staff.map((member)=><div className="card card-pad dc-staff-card" key={member.id}><div className="dc-person"><div className="dc-avatar">{window.DcxName(member).slice(0,1)}</div><div><b>{window.DcxName(member)}</b><small>{member.job_title||"Team member"}</small></div></div><span className="dc-status">Active</span><div className="dc-staff-meta"><span>{(member.staff_classrooms||[]).length} rooms</span><span>{(member.staff_schedules||[]).length} schedule days</span><span>{member.hourly_rate==null?"Rate private":window.DcxMoney(member.hourly_rate)+"/hr"}</span></div><div className="dc-card-actions"><button onClick={()=>setModal(member)}>Edit</button><button onClick={()=>setSchedule(member)}>Schedule</button><button className="danger" onClick={()=>setConfirm(member)}>Deactivate</button></div></div>)}</div>}{modal&&<DcoStaffForm member={modal==="new"?null:modal} classrooms={rooms} onClose={()=>setModal(null)} onSaved={(provision)=>{setModal(null);if(provision)setCredentials(provision);staffResource.refresh();}}/>}{schedule&&<DcoScheduleForm member={schedule} onClose={()=>setSchedule(null)} onSaved={()=>{setSchedule(null);staffResource.refresh();}}/>}{confirm&&<window.DcxConfirm danger title={"Deactivate "+window.DcxName(confirm)+"?"} copy="Their history remains available, but management access and active scheduling are removed." confirmLabel="Deactivate staff" onClose={()=>setConfirm(null)} onConfirm={deactivate}/>} {credentials&&<DcoProvisionCredentials provision={credentials} onClose={()=>setCredentials(null)}/>}</div>;
}

Object.assign(window,{DaycareChildren,DaycareEnrollment,DaycareAttendance,DaycareTimesheets,DaycareClassrooms,DaycareStaff,DcoChildForm,DcoProvisionCredentials});
