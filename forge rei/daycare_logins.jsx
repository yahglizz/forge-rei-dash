// Daycare · Parent Logins — one place to look up a parent or student and hand off
// the family's app Login ID + a fresh one-time PIN. Reuses the existing provisioning
// backend (get_children carries guardian.login_id; /guardian/reset-pin issues a new
// PIN; DcoChildForm + DcoProvisionCredentials come from daycare_operations.jsx).
// No PIN is ever stored — the Login ID is safe to read; the PIN appears once on reveal.
const { useState: useStateDcl } = React;

function DclCopy({ text }) {
  const [ok, setOk] = useStateDcl(false);
  if (!text) return null;
  const go = async () => {
    try { await navigator.clipboard.writeText(text); } catch (e) { /* clipboard blocked */ }
    setOk(true); window.setTimeout(() => setOk(false), 1400);
  };
  return <button className="dc-quiet dcl-copy" onClick={go} title="Copy Login ID">{ok ? "Copied" : "Copy"}</button>;
}

function DclPendingPanel({ families, onCreate }) {
  const fresh = families.filter((f) => !f.in_roster);
  const linked = families.length - fresh.length;
  return <div className="card card-pad dc-panel dcl-pending">
    <div className="dc-panel-head"><div><div className="card-title">From the Contact Form</div><div className="faint">Families who filled out the form, not yet in the dashboard</div></div><b>{fresh.length}</b></div>
    {fresh.length === 0
      ? <div className="dc-all-clear"><window.Icons.Check size={20} /><div><b>All caught up</b><span>{linked ? linked + " form families are already in the dashboard." : "New form submissions will show here to create a login."}</span></div></div>
      : <div className="dcl-inbox-list">{fresh.map((f) => <div key={f.contact_id} className="dcl-inbox-row" style={{ display: "flex", alignItems: "center", gap: "12px", padding: "10px 0", borderTop: "1px solid rgba(255,255,255,.06)" }}>
          <span className="dc-severity info" style={{ flex: "0 0 auto" }} />
          <div style={{ flex: "1 1 auto", minWidth: 0 }}>
            <b style={{ fontWeight: 500 }}>{f.parent_name || "Parent"}{f.child_name ? " · " + f.child_name : ""}</b>
            <small style={{ display: "block", opacity: .6 }}>{[f.location_tag, f.email, f.phone].filter(Boolean).join("  ·  ") || "No contact details"}</small>
          </div>
          <button className="dc-primary" style={{ flex: "0 0 auto", whiteSpace: "nowrap" }} onClick={() => onCreate(f)}><window.Icons.Shield size={13} /> Create login</button>
        </div>)}</div>}
    {linked > 0 && fresh.length > 0 && <div className="dc-form-hint">{linked} other form {linked === 1 ? "family is" : "families are"} already in the dashboard.</div>}
  </div>;
}

function DaycareParentLogins() {
  const childrenRes = window.DcxUseResource("/children", "children", 30000);
  const roomsRes = window.DcxUseResource("/classrooms", "classrooms", 60000);
  const pendingRes = window.DcxUseResource("/ghl/pending-families", "families", 60000);
  const [search, setSearch] = useStateDcl("");
  const [credentials, setCredentials] = useStateDcl(null);
  const [enrollInit, setEnrollInit] = useStateDcl(null);
  const [busyGid, setBusyGid] = useStateDcl("");
  const children = Array.isArray(childrenRes.data) ? childrenRes.data : [];
  const rooms = Array.isArray(roomsRes.data) ? roomsRes.data : [];
  const pending = Array.isArray(pendingRes.data) ? pendingRes.data : [];

  // One row per parent — group children by guardian; children with no linked
  // guardian each get their own "no login yet" row.
  const groups = {}; const solo = [];
  children.forEach((child) => {
    const guardian = child.guardian || child.guardian_profile || null;
    const gid = child.guardian_profile_id || (guardian && guardian.id) || null;
    const student = window.DcxChildName(child);
    if (gid) {
      if (!groups[gid]) groups[gid] = { gid, parent: child.guardian_name || window.DcxName(guardian, "Parent"), loginId: (guardian && guardian.login_id) || "", students: [] };
      groups[gid].students.push(student);
    } else {
      solo.push({ gid: null, parent: child.guardian_name || "No guardian linked", loginId: "", students: [student] });
    }
  });
  const families = Object.values(groups).concat(solo);
  const query = search.trim().toLowerCase();
  const visible = !query ? families : families.filter((f) => (f.parent || "").toLowerCase().includes(query) || f.students.some((s) => s.toLowerCase().includes(query)));

  const resetPin = async (gid) => {
    if (!gid) return;
    if (!window.confirm("Reveal a fresh login PIN for this parent? Their current PIN stops working immediately and the new one is shown once.")) return;
    setBusyGid(gid);
    try { const payload = await window.DcxRequest("/guardian/reset-pin", { body: { profile_id: gid } }); if (payload.provision) setCredentials(payload.provision); }
    catch (error) { window.alert(error.message); }
    finally { setBusyGid(""); }
  };

  const createFromForm = (family) => setEnrollInit({
    first_name: family.child_first || "", last_name: family.child_last || "", birth_date: family.child_dob || "",
    guardian_first_name: family.parent_first || "", guardian_last_name: family.parent_last || "",
    guardian_phone: family.phone || "", guardian_email: family.email || "",
  });

  const actions = <div className="dc-search"><window.Icons.Search size={14} /><input placeholder="Search parent or student…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>;

  return <div className="dc-page">
    <window.DcxPageHead title="Parent Logins" eyebrow="APP ACCESS" copy="Look up a parent or student, then hand off their Login ID. PINs are shown once — reveal a fresh one when a parent needs it. Nothing is stored." actions={actions} />
    {pending.length > 0 && <DclPendingPanel families={pending} onCreate={createFromForm} />}
    <window.DcxState loading={childrenRes.loading} error={childrenRes.error} onRetry={childrenRes.refresh} empty={!families.length} icon="Children" title="No families yet" copy="Enroll a child (or create a login from a form submission above) to generate parent app access." />
    {families.length > 0 && <div className="card dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Parent</th><th>Student(s)</th><th>Login ID</th><th></th></tr></thead><tbody>{visible.map((f, index) => <tr key={f.gid || ("solo-" + index)}>
      <td><div className="dc-person"><div className="dc-avatar">{(f.parent || "?").slice(0, 1)}</div><div><b>{f.parent}</b><small>{f.students.length} {f.students.length === 1 ? "child" : "children"}</small></div></div></td>
      <td>{f.students.join(", ")}</td>
      <td>{f.loginId ? <span className="dcl-login"><code>{f.loginId}</code> <DclCopy text={f.loginId} /></span> : <span className="quiet">No login yet</span>}</td>
      <td><div className="dc-row-actions">{f.gid ? <button onClick={() => resetPin(f.gid)} disabled={busyGid === f.gid}>{busyGid === f.gid ? "Revealing…" : "Reveal / Reset PIN"}</button> : <button onClick={() => window.GoTo("Enrollment")}>Enroll</button>}</div></td>
    </tr>)}</tbody></table>{!visible.length && <div className="dc-inline-empty">No parent or student matches that search.</div>}</div>}
    {enrollInit && <window.DcoChildForm classrooms={rooms} child={null} initial={enrollInit} enrollmentMode onClose={() => setEnrollInit(null)} onSaved={(provision) => { setEnrollInit(null); if (provision) setCredentials(provision); childrenRes.refresh(); pendingRes.refresh(); }} />}
    {credentials && <window.DcoProvisionCredentials provision={credentials} onClose={() => setCredentials(null)} />}
  </div>;
}

Object.assign(window, { DaycareParentLogins });
