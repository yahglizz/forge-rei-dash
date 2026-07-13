// daycare.jsx — authenticated Daycare workspace foundation + overview/settings.
// Supabase remains authoritative through domain-specific connector endpoints.
const { useState: useStateDcx, useEffect: useEffectDcx, useCallback: useCallbackDcx } = React;

const DCX_ACCENT = "#2DD4BF";
const DCX_GOLD = "#F4B860";
const DCX_API_ROOT = "/api/daycare";

function DcxApiError(message, status, body) {
  const error = new Error(message || "Daycare request failed");
  error.status = status || 0;
  error.body = body || null;
  return error;
}

async function DcxRequest(path, options = {}) {
  const method = options.method || (options.body === undefined ? "GET" : "POST");
  const response = await fetch(DCX_API_ROOT + path, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { payload = null; }
  if (!response.ok) {
    const message = payload && (payload.error || payload.message);
    const error = DcxApiError(message || (response.status === 401 ? "Your Daycare session expired." : "Daycare request failed."), response.status, payload);
    if (response.status === 401) window.dispatchEvent(new CustomEvent("forge-daycare-auth-expired"));
    throw error;
  }
  return payload === null ? {} : payload;
}

function DcxUnwrap(payload, key, fallback) {
  if (payload === undefined || payload === null) return fallback;
  if (key && payload[key] !== undefined) return payload[key];
  if (payload.data !== undefined) {
    if (key && payload.data && payload.data[key] !== undefined) return payload.data[key];
    return payload.data;
  }
  return payload;
}

function DcxArray(payload, key) {
  const value = DcxUnwrap(payload, key, []);
  return Array.isArray(value) ? value : [];
}

function DcxName(item, fallback = "Unknown") {
  if (!item) return fallback;
  const profile = item.profiles || item.profile || item;
  return profile.display_name || [profile.first_name, profile.last_name].filter(Boolean).join(" ") || profile.name || fallback;
}

function DcxChildName(child) {
  if (!child) return "Unknown child";
  return child.preferred_name || [child.first_name, child.last_name].filter(Boolean).join(" ") || child.name || "Unknown child";
}

function DcxMoney(value) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value) || 0);
}

function DcxDate(value, includeTime = false) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString([], includeTime ? { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" } : { month: "short", day: "numeric", year: "numeric" });
}

function DcxToday() {
  const now = new Date();
  return now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
}

function DcxUseResource(path, key, pollMs = 15000) {
  const [data, setData] = useStateDcx([]);
  const [loading, setLoading] = useStateDcx(true);
  const [error, setError] = useStateDcx(null);
  const [version, setVersion] = useStateDcx(0);
  const refresh = useCallbackDcx(() => setVersion((value) => value + 1), []);
  useEffectDcx(() => {
    let active = true;
    let timer = null;
    const load = async (quiet) => {
      if (!quiet) setLoading(true);
      try {
        const payload = await DcxRequest(path);
        if (active) { setData(DcxUnwrap(payload, key, Array.isArray(data) ? [] : {})); setError(null); }
      } catch (requestError) {
        if (active) setError(requestError);
      } finally { if (active) setLoading(false); }
    };
    load(false);
    if (pollMs) timer = window.setInterval(() => { if (!document.hidden) load(true); }, pollMs);
    return () => { active = false; if (timer) window.clearInterval(timer); };
  }, [path, key, pollMs, version]);
  return { data, loading, error, refresh, setData };
}

function DcxPageHead({ title, eyebrow = "DAYCARE OPERATIONS", actions, copy }) {
  return <div className="dc-page-head"><div><div className="dc-eyebrow">{eyebrow}</div><h1>{title}</h1>{copy && <p>{copy}</p>}</div>{actions && <div className="dc-head-actions">{actions}</div>}</div>;
}

function DcxKpi({ label, value, sub, icon, color = DCX_ACCENT }) {
  const Icon = window.Icons[icon] || window.Icons.Dashboard;
  return <div className="kpi dc-kpi"><div className="kpi-ico" style={{ color, background: color + "1f" }}><Icon size={18} /></div><div className="kpi-label">{label}</div><div className="kpi-val tabnum">{value}</div><div className="kpi-delta"><span className="faint">{sub}</span></div></div>;
}

function DcxState({ loading, error, empty, icon = "Dashboard", title, copy, onRetry, children }) {
  const Icon = window.Icons[icon] || window.Icons.Dashboard;
  if (loading) return <div className="card dc-state"><div className="dc-spinner" /><b>Loading live daycare data</b><span>Connecting securely to Supabase…</span></div>;
  if (error) return <div className="card dc-state dc-state-error"><Icon size={27} /><b>{error.status === 401 ? "Session expired" : "Daycare data is unavailable"}</b><span>{error.message || "Check the integration and try again."}</span>{onRetry && <button className="dc-primary" onClick={onRetry}>Try again</button>}</div>;
  if (empty) return <div className="card dc-state"><Icon size={27} /><b>{title}</b><span>{copy}</span>{children}</div>;
  return children;
}

function DcxModal({ title, copy, onClose, children, wide = false }) {
  return <div className="dc-modal-layer" role="dialog" aria-modal="true" aria-label={title}><button className="dc-modal-backdrop" onClick={onClose} aria-label="Close dialog" /><div className={"card dc-modal" + (wide ? " dc-modal-wide" : "")}><div className="dc-modal-head"><div><div className="card-title">{title}</div>{copy && <div className="faint">{copy}</div>}</div><button onClick={onClose} aria-label="Close">✕</button></div>{children}</div></div>;
}

function DcxConfirm({ title, copy, confirmLabel = "Confirm", danger = false, busy = false, onConfirm, onClose }) {
  return <DcxModal title={title} copy={copy} onClose={onClose}><div className="dc-confirm-note">This action updates the shared daycare database and will be visible in the parent/staff app.</div><div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className={danger ? "dc-danger" : "dc-primary"} disabled={busy} onClick={onConfirm}>{busy ? "Working…" : confirmLabel}</button></div></DcxModal>;
}

function DcxField({ label, children, wide = false }) {
  return <label className={wide ? "dc-field-wide" : ""}><span>{label}</span>{children}</label>;
}

function DcxLogin({ reason, onAuthenticated, testMode = false, testProfiles = [] }) {
  const [loginId, setLoginId] = useStateDcx("");
  const [pin, setPin] = useStateDcx("");
  const [busy, setBusy] = useStateDcx(false);
  const [busyProfile, setBusyProfile] = useStateDcx("");
  const [error, setError] = useStateDcx(null);
  const submit = async (event) => {
    event.preventDefault();
    if (!loginId.trim() || !pin.trim()) { setError("Enter your management Login ID and PIN."); return; }
    setBusy(true); setError(null);
    try {
      const payload = await DcxRequest("/auth/login", { body: { loginId: loginId.trim(), pin: pin.trim() } });
      setPin(""); onAuthenticated(payload);
    } catch (loginError) { setError(loginError.message); }
    finally { setBusy(false); }
  };
  const enterTestProfile = async (profile) => {
    setBusyProfile(profile); setError(null);
    try { const payload = await DcxRequest("/auth/test-login", { body: { profile } }); onAuthenticated(payload); }
    catch (loginError) { setError(loginError.message); }
    finally { setBusyProfile(""); }
  };
  if (testMode && testProfiles.length) return <div className="dc-login-shell"><div className="dc-login-art"><div className="dc-login-orbit"><span>DC</span></div><div><div className="dc-eyebrow">TEST PHASE · PRIVATE ACCESS</div><h1>Choose your<br/>test profile.</h1><p>Real Supabase data stays connected while this private dashboard uses server-controlled one-click access. The Login ID and PIN screen remains available when test mode is turned off.</p></div></div><div className="card dc-login-card"><div className="dc-login-badge"><window.Icons.Shield size={18} /></div><h2>Open a test profile</h2><p>{reason || "No password is needed during the test phase."}</p>{error && <div className="dc-form-error">{error}</div>}<div className="dc-test-profiles">{testProfiles.map((profile)=>{const isAdmin=profile==="admin";const title=isAdmin?"Management / Admin":"Manager";const detail=isAdmin?"Full center operations, staff, billing, and settings":"Daily center operations and classroom oversight";const Icon=isAdmin?window.Icons.Shield:window.Icons.Classrooms;return <button key={profile} className="dc-test-profile" disabled={Boolean(busyProfile)} onClick={()=>enterTestProfile(profile)}><span><Icon size={18}/></span><div><b>{busyProfile===profile?"Opening…":title}</b><small>{detail}</small></div><window.Icons.ChevronR size={16}/></button>;})}</div><small><window.Icons.Lock size={13} /> Test access is HTTPS-only and controlled by a private server flag. No PIN is sent to this browser.</small></div></div>;
  return <div className="dc-login-shell"><div className="dc-login-art"><div className="dc-login-orbit"><span>DC</span></div><div><div className="dc-eyebrow">SECURE MANAGEMENT ACCESS</div><h1>Your center.<br/>One command view.</h1><p>Live attendance, family records, staff coverage, care reporting, communication, and finances—all backed by the same Supabase data used by your daycare app.</p></div></div><form className="card dc-login-card" onSubmit={submit}><div className="dc-login-badge"><window.Icons.Lock size={18} /></div><h2>Management sign in</h2><p>{reason || "Use the management Login ID and PIN assigned in your daycare app."}</p>{error && <div className="dc-form-error">{error}</div>}<DcxField label="Login ID"><input autoFocus autoComplete="username" value={loginId} onChange={(event) => setLoginId(event.target.value)} placeholder="Your Login ID" /></DcxField><DcxField label="PIN"><input type="password" inputMode="numeric" autoComplete="current-password" value={pin} onChange={(event) => setPin(event.target.value)} placeholder="••••" /></DcxField><button className="dc-primary dc-login-submit" disabled={busy}>{busy ? "Signing in…" : "Open management workspace"}</button><small><window.Icons.Shield size={13} /> Credentials and Supabase tokens are never stored in this browser.</small></form></div>;
}

function DaycareWorkspace({ children }) {
  const [state, setState] = useStateDcx({ loading: true, authenticated: false, reason: "", profile: null, testMode: false, testProfiles: [] });
  const check = useCallbackDcx(async () => {
    try {
      const payload = await DcxRequest("/auth/status");
      const auth = payload.authenticated !== undefined ? payload.authenticated : Boolean(payload.user || payload.profile);
      const data=payload.data||{};setState({ loading: false, authenticated: auth, reason: "", profile: payload.profile || payload.user || data.profile || null, testMode: Boolean(payload.testMode||data.testMode), testProfiles: Array.isArray(payload.testProfiles)?payload.testProfiles:(Array.isArray(data.testProfiles)?data.testProfiles:[]) });
    } catch (error) {
      setState({ loading: false, authenticated: false, reason: error.status === 502 ? "The Daycare integration is not configured yet." : error.message, profile: null, testMode: false, testProfiles: [] });
    }
  }, []);
  useEffectDcx(() => {
    check();
    const expire = () => setState((current) => ({ ...current, loading: false, authenticated: false, reason: "Your secure session expired. Sign in again to continue.", profile: null }));
    window.addEventListener("forge-daycare-auth-expired", expire);
    return () => window.removeEventListener("forge-daycare-auth-expired", expire);
  }, [check]);
  useEffectDcx(() => {
    window.__forgeDaycareProfile = state.profile;
    window.dispatchEvent(new CustomEvent("forge-daycare-session", { detail: state }));
  }, [state]);
  if (state.loading) return <div className="dc-auth-loading"><div className="dc-spinner" /><b>Securing Daycare workspace</b></div>;
  if (!state.authenticated) return <DcxLogin reason={state.reason} onAuthenticated={check} testMode={state.testMode} testProfiles={state.testProfiles} />;
  return <div className="dc-authenticated">{children}</div>;
}

function DaycareDashboard() {
  const overview = DcxUseResource("/overview", "overview", 30000);
  const classrooms = DcxUseResource("/classrooms", "classrooms", 30000);
  const value = overview.data || {};
  const metrics = value.metrics || {};
  const center = value.center || value.location || {};
  const rooms = Array.isArray(classrooms.data) ? classrooms.data : (value.classrooms || value.rooms || []);
  const alerts = value.alerts || [];
  const enrolled = Number(metrics.childrenActive ?? value.enrolled_count ?? value.enrolled ?? value.children_count ?? 0);
  const checkedIn = Number(metrics.presentToday ?? value.checked_in_count ?? value.checked_in ?? 0);
  const staff = Number(metrics.staffActive ?? value.staff_count ?? value.active_staff ?? 0);
  const capacity = Number(metrics.capacityTotal ?? value.capacity ?? center.capacity ?? rooms.reduce((sum, room) => sum + (Number(room.capacity) || 0), 0));
  const invoicesDue = Number(metrics.invoicesDue ?? value.invoices_due ?? 0);
  const amountDue = Number(metrics.amountDue ?? value.amount_due ?? 0);
  const unread = Number(metrics.unreadNotifications ?? value.unread ?? 0);
  const today = new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  return <div className="dc-page"><DcxState loading={overview.loading || classrooms.loading} error={overview.error || classrooms.error} onRetry={()=>{overview.refresh();classrooms.refresh();}}><>
    <section className="dc-hero"><div><div className="dc-eyebrow">{today.toUpperCase()} · LIVE OPERATIONS</div><h1>{center.name || "Daycare command center"}</h1><p>See what needs attention now, then move directly into the operating record shared with your families and team.</p><div className="dc-hero-actions"><button className="dc-primary" onClick={() => window.GoTo("Attendance")}><window.Icons.Attendance size={15}/> Open attendance</button><button className="dc-outline" onClick={() => window.GoTo("Messages")}><window.Icons.Conversations size={15}/> Family messages</button></div></div><div className="dc-hero-mark"><span>{checkedIn}</span><small>ON SITE NOW</small></div></section>
    <div className="dc-kpi-grid"><DcxKpi label="Enrolled" value={enrolled} sub={Math.max(0, capacity - enrolled) + " of " + capacity + " spots open"} icon="Children"/><DcxKpi label="Checked In" value={checkedIn} sub="live attendance" icon="Attendance" color="#22C55E"/><DcxKpi label="Active Staff" value={staff} sub="center team" icon="Staff" color="#8B5CF6"/><DcxKpi label="Balances Due" value={DcxMoney(amountDue)} sub={invoicesDue + " open invoices"} icon="Billing" color={invoicesDue ? "#F4B860" : "#22C55E"}/><DcxKpi label="Unread" value={unread} sub="family + team messages" icon="Bell" color={unread ? "#38BDF8" : "#22C55E"}/><DcxKpi label="Open Alerts" value={alerts.length} sub="items needing review" icon="Bell" color={alerts.length ? "#F4B860" : "#22C55E"}/></div>
    <div className="dc-main-grid"><div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Center pulse</div><div className="faint">Fast paths for today’s operations</div></div><span className="dc-live"><i/> LIVE</span></div><div className="dc-day-grid">{[["Attendance","Attendance",checkedIn + " currently in"],["CareLogs","Daily Logs","Care updates"],["Incidents","Incidents","Safety records"],["Billing","Billing","Family balances"]].map((item) => { const Icon = window.Icons[item[0]] || window.Icons.Dashboard; return <button key={item[0]} onClick={() => window.GoTo(item[0])}><span><Icon size={18}/></span><b>{item[1]}</b><small>{item[2]}</small></button>; })}</div></div><div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Management alerts</div><div className="faint">Prioritized operational exceptions</div></div><b>{alerts.length}</b></div>{alerts.length ? <div className="dc-alert-list">{alerts.slice(0,5).map((alert, index) => <div key={alert.id || index}><span className={"dc-severity " + (alert.severity || "info")}/><div><b>{alert.title || alert.kind || "Needs review"}</b><small>{alert.body || alert.message || "Open the related page for details."}</small></div></div>)}</div> : <div className="dc-all-clear"><window.Icons.Check size={22}/><div><b>All clear</b><span>No operational alerts right now.</span></div></div>}</div></div>
    <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Classroom capacity</div><div className="faint">Live enrollment by room</div></div><button className="link" onClick={() => window.GoTo("Classrooms")}>Manage classrooms</button></div><div className="dc-room-strip">{rooms.length ? rooms.map((room) => { const count = Number(room.enrolled_count ?? room.child_count ?? (room.children || []).length ?? 0); const cap = Number(room.capacity) || 0; const color = room.color || DCX_ACCENT; return <div key={room.id}><div className="dc-room-top"><span style={{color}}>{room.name}</span><b>{count}/{cap}</b></div><small>{room.age_group || "Age group not set"}</small><div className="progress"><div style={{width: Math.min(100, cap ? count / cap * 100 : 0) + "%", background: color}}/></div></div>; }) : <div className="dc-inline-empty">No active classrooms yet.</div>}</div></div>
  </></DcxState></div>;
}

function DaycareDeferred({ kind }) {
  const isMeals = kind === "Meals";
  const Icon = isMeals ? window.Icons.Meals : window.Icons.Calendar;
  return <div className="dc-page"><DcxPageHead title={isMeals ? "Meals & Menus" : "Calendar"} eyebrow="PLANNED EXPANSION"/><div className="card dc-deferred"><div className="dc-deferred-mark"><Icon size={30}/></div><span className="dc-week">LATER PHASE</span><h2>{isMeals ? "Meal planning will live here." : "The center calendar will live here."}</h2><p>{isMeals ? "Menus, meal compliance, allergies, and family visibility will be added after the core management data is fully operating." : "Closures, tours, staff schedules, and family events will be added after the core management data is fully operating."}</p><div className="dc-deferred-note">No placeholder controls are active. This prevents changes that look saved but never reach Supabase.</div></div></div>;
}

function DaycareMeals() { return <DaycareDeferred kind="Meals"/>; }
function DaycareCalendar() { return <DaycareDeferred kind="Calendar"/>; }

function DaycareSettings() {
  const status = DcxUseResource("/status", "status", 30000);
  const ghlHealth = DcxUseResource("/ghl/health", "ghl-health", 120000);
  const [form, setForm] = useStateDcx({ name: "", phone: "", address: "", opening_time: "", closing_time: "" });
  const [saving, setSaving] = useStateDcx(false);
  const [notice, setNotice] = useStateDcx("");
  useEffectDcx(() => { const center = (status.data && (status.data.center || status.data.location)) || {}; setForm({ name: center.name || "", phone: center.phone || "", address: center.address || "", opening_time: center.opening_time || center.openTime || "", closing_time: center.closing_time || center.closeTime || "" }); }, [status.data]);
  const save = async () => { setSaving(true); setNotice(""); try { await DcxRequest("/settings/save", { body: form }); setNotice("Center settings saved."); status.refresh(); } catch (error) { setNotice(error.message); } finally { setSaving(false); } };
  const logout = async () => { try { await DcxRequest("/auth/logout", { body: {} }); } finally { window.dispatchEvent(new CustomEvent("forge-daycare-auth-expired")); } };
  const info = status.data || {};
  return <div className="dc-page"><DcxPageHead title="Settings & Integration" copy="Center details, secure connection health, and management access."/><DcxState loading={status.loading} error={status.error} onRetry={status.refresh}><div className="dc-settings-grid"><div className="card card-pad dc-settings"><div className="dc-panel-head"><div><div className="card-title">Center profile</div><div className="faint">Shared with the daycare app</div></div>{notice && <span className={notice.includes("saved") ? "dc-saved" : "dc-error-text"}>{notice}</span>}</div><div className="dc-form-grid"><DcxField label="Center name"><input value={form.name} onChange={(event) => setForm({...form,name:event.target.value})}/></DcxField><DcxField label="Phone"><input value={form.phone} onChange={(event) => setForm({...form,phone:event.target.value})}/></DcxField><DcxField label="Opening time"><input type="time" value={form.opening_time || ""} onChange={(event) => setForm({...form,opening_time:event.target.value})}/></DcxField><DcxField label="Closing time"><input type="time" value={form.closing_time || ""} onChange={(event) => setForm({...form,closing_time:event.target.value})}/></DcxField><DcxField label="Address" wide><textarea rows="3" value={form.address} onChange={(event) => setForm({...form,address:event.target.value})}/></DcxField></div><div className="dc-settings-actions"><button className="dc-primary" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save center profile"}</button></div></div><div className="dc-settings-side"><div className="card card-pad"><div className="dc-integration-head"><span className={"dc-integration-dot " + (info.live || info.configured ? "online" : "offline")}/><div><b>Supabase integration</b><small>{info.live || info.configured ? "Connected and authoritative" : "Not configured"}</small></div></div><dl className="dc-details"><div><dt>Location</dt><dd>{info.location_name || info.location_id || "—"}</dd></div><div><dt>Mode</dt><dd>{info.live ? "Live" : "Read-only / unavailable"}</dd></div><div><dt>Session</dt><dd>Server managed</dd></div><div><dt>Last check</dt><dd>{DcxDate(info.checked_at || new Date().toISOString(), true)}</dd></div></dl></div><div className="card card-pad"><div className="dc-integration-head"><span className={"dc-integration-dot " + ((ghlHealth.data && ghlHealth.data.connected) ? "online" : "offline")}/><div><b>GoHighLevel</b><small>{ghlHealth.data ? (ghlHealth.data.connected ? "Connected — family messaging ready" : (ghlHealth.data.detail || "Not connected")) : "Checking…"}</small></div></div></div>{info.familyAppUrl && <div className="card card-pad dc-signout"><b>Family app</b><p>The parent &amp; staff companion app, sharing this same live data.</p><a className="dc-primary" href={info.familyAppUrl} target="_blank" rel="noreferrer"><window.Icons.Children size={14}/> Open family app</a></div>}<div className="card card-pad dc-signout"><b>Management session</b><p>Logging out clears the server-side Supabase session for this browser.</p><button className="dc-danger" onClick={logout}><window.Icons.Logout size={14}/> Log out of Daycare</button></div></div></div></DcxState></div>;
}

Object.assign(window, {
  DCX_ACCENT, DCX_GOLD, DcxRequest, DcxUnwrap, DcxArray, DcxName, DcxChildName, DcxMoney, DcxDate, DcxToday,
  DcxUseResource, DcxPageHead, DcxKpi, DcxState, DcxModal, DcxConfirm, DcxField,
  DaycareWorkspace, DaycareDashboard, DaycareMeals, DaycareCalendar, DaycareSettings,
});
