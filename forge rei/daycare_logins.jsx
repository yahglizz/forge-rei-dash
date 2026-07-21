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

function DclPendingPanel({ families, activeLoc, onCreate, onDismiss, error, busyContact }) {
  // Organize by center: the roster + dedup are scoped to the active center (RLS), so
  // this center's families are actionable here; families for other centers get a
  // "switch center" nudge (unknown-location families fall through to the active center).
  const here = families.filter((f) => !f.location_id || f.location_id === activeLoc);
  const elsewhere = families.filter((f) => f.location_id && f.location_id !== activeLoc);
  const fresh = here.filter((f) => !f.in_roster && !f.dismissed);
  // Split by enrollment: only an actually-enrolled family gets a parent app login.
  // Brand-new website inquiries (not in the daycare yet) are shown MARKED, no login —
  // they live in the Enrollment pipeline until they enroll.
  const enrolledFresh = fresh.filter((f) => f.enrolled);
  const inquiries = fresh.filter((f) => !f.enrolled);
  const linked = here.length - fresh.length;
  const centerName = (here.find((f) => f.location_name) || {}).location_name || "";
  const dismissBtn = (f) => <button className="dc-quiet" title="Dismiss — already handled" disabled={busyContact === f.contact_id}
      style={{ flex: "0 0 auto", fontSize: "16px", lineHeight: 1 }} onClick={() => onDismiss(f.contact_id)}>&times;</button>;
  const row = (f, action) => <div key={f.contact_id} className="dcl-inbox-row" style={{ display: "flex", alignItems: "center", gap: "12px", padding: "10px 0", borderTop: "1px solid rgba(255,255,255,.06)" }}>
      <span className={"dc-severity " + (f.enrolled ? "info" : "warning")} style={{ flex: "0 0 auto" }} />
      <div style={{ flex: "1 1 auto", minWidth: 0 }}>
        <b style={{ fontWeight: 500 }}>{f.child_name || "Student"}{f.parent_name ? " · " + f.parent_name : ""}</b>
        <small style={{ display: "block", opacity: .6 }}>{[f.location_name || f.location_tag, f.email, f.phone].filter(Boolean).join("  ·  ") || "No contact details"}</small>
      </div>
      {action}
      {dismissBtn(f)}
    </div>;
  return <div className="card card-pad dc-panel dcl-pending">
    <div className="dc-panel-head"><div><div className="card-title">From the Contact Form{centerName ? " · " + centerName : ""}</div><div className="faint">Enrolled families who filled out the form for this center, not yet in the dashboard</div></div><b>{enrolledFresh.length}</b></div>
    {error && <div className="dc-form-hint" style={{ color: "#f28b82" }}>Couldn't load the newest submissions ({error.message || "connection error"}) — showing the last successful load. Refresh to retry.</div>}
    {enrolledFresh.length === 0
      ? <div className="dc-all-clear"><window.Icons.Check size={20} /><div><b>All caught up</b><span>{linked ? linked + " form families are already in the dashboard for this center." : "New form submissions for this center will show here to create a login."}</span></div></div>
      : <div className="dcl-inbox-list">{enrolledFresh.map((f) => row(f,
          <button className="dc-primary" style={{ flex: "0 0 auto", whiteSpace: "nowrap" }} disabled={busyContact === f.contact_id} onClick={() => onCreate(f)}><window.Icons.Shield size={13} /> {busyContact === f.contact_id ? "Enrolling…" : "Create login"}</button>))}</div>}
    {inquiries.length > 0 && <div className="dcl-inquiries" style={{ marginTop: "14px" }}>
      <div className="faint" style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 500 }}><window.Icons.Bell size={13} /> New inquiries — not enrolled yet · no app login</div>
      <div className="dcl-inbox-list">{inquiries.map((f) => row(f,
        <span style={{ flex: "0 0 auto", whiteSpace: "nowrap", fontSize: "11px", fontWeight: 600, color: "#f6c979", background: "rgba(244,184,96,.1)", borderRadius: "99px", padding: "3px 9px" }}>Inquiry · Enrollment pipeline</span>))}</div>
      <div className="dc-form-hint">Brand-new inquiries stay a lead in GoHighLevel. A login is created only once they enroll.</div>
    </div>}
    {elsewhere.length > 0 && <div className="dc-form-hint">{elsewhere.length} more form {elsewhere.length === 1 ? "family is" : "families are"} waiting at other centers — switch center at the top to see them.</div>}
    {linked > 0 && enrolledFresh.length > 0 && <div className="dc-form-hint">{linked} other form {linked === 1 ? "family is" : "families are"} already in this center.</div>}
  </div>;
}

function DaycareParentLogins() {
  const childrenRes = window.DcxUseResource("/children", "children", 30000);
  const roomsRes = window.DcxUseResource("/classrooms", "classrooms", 60000);
  const pendingRes = window.DcxUseResource("/ghl/pending-families", "pendingfam", 60000);
  const [search, setSearch] = useStateDcl("");
  const [credentials, setCredentials] = useStateDcl(null);
  const [busyGid, setBusyGid] = useStateDcl("");
  const [busyContact, setBusyContact] = useStateDcl("");
  const children = Array.isArray(childrenRes.data) ? childrenRes.data : [];
  const pendingPayload = (pendingRes.data && typeof pendingRes.data === "object" && !Array.isArray(pendingRes.data)) ? pendingRes.data : {};
  const pending = Array.isArray(pendingPayload.families) ? pendingPayload.families : [];
  const activeLoc = pendingPayload.active_location_id || "";

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

  const dismissFamily = async (contactId) => {
    try { await window.DcxRequest("/ghl/dismiss", { body: { contact_id: contactId } }); pendingRes.refresh(); }
    catch (error) { window.alert(error.message); }
  };

  // One click does everything: creates the child (classroom auto-matched by the form's
  // age-band tag), creates the guardian login when parent info is present, syncs GHL,
  // and dismisses the card — no review form. The click itself is the approval (an
  // explicit owner action on one already-consented family record).
  const createFromForm = async (family) => {
    setBusyContact(family.contact_id);
    try {
      const payload = await window.DcxRequest("/ghl/enroll", { body: { family } });
      if (payload.provision) setCredentials(payload.provision);
      childrenRes.refresh(); roomsRes.refresh(); pendingRes.refresh();
    } catch (error) { window.alert(error.message); }
    finally { setBusyContact(""); }
  };

  const actions = <div className="dc-search"><window.Icons.Search size={14} /><input placeholder="Search parent or student…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>;

  return <div className="dc-page">
    <window.DcxPageHead title="Parent Logins" eyebrow="APP ACCESS" copy="Look up a parent or student, then hand off their Login ID. PINs are shown once — reveal a fresh one when a parent needs it. Nothing is stored." actions={actions} />
    {(pending.length > 0 || pendingRes.error) && <DclPendingPanel families={pending} activeLoc={activeLoc} onCreate={createFromForm} onDismiss={dismissFamily} error={pendingRes.error} busyContact={busyContact} />}
    <window.DcxState loading={childrenRes.loading} error={childrenRes.error} onRetry={childrenRes.refresh} empty={!families.length} icon="Children" title="No families yet" copy="Enroll a child (or create a login from a form submission above) to generate parent app access." />
    {families.length > 0 && <div className="card dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Parent</th><th>Student(s)</th><th>Login ID</th><th></th></tr></thead><tbody>{visible.map((f, index) => <tr key={f.gid || ("solo-" + index)}>
      <td><div className="dc-person"><div className="dc-avatar">{(f.parent || "?").slice(0, 1)}</div><div><b>{f.parent}</b><small>{f.students.length} {f.students.length === 1 ? "child" : "children"}</small></div></div></td>
      <td>{f.students.join(", ")}</td>
      <td>{f.loginId ? <span className="dcl-login"><code>{f.loginId}</code> <DclCopy text={f.loginId} /></span> : <span className="quiet">No login yet</span>}</td>
      <td><div className="dc-row-actions">{f.gid ? <button onClick={() => resetPin(f.gid)} disabled={busyGid === f.gid}>{busyGid === f.gid ? "Revealing…" : "Reveal / Reset PIN"}</button> : <button onClick={() => window.GoTo("Enrollment")}>Enroll</button>}</div></td>
    </tr>)}</tbody></table>{!visible.length && <div className="dc-inline-empty">No parent or student matches that search.</div>}</div>}
    {credentials && <window.DcoProvisionCredentials provision={credentials} onClose={() => setCredentials(null)} />}
  </div>;
}

Object.assign(window, { DaycareParentLogins });
