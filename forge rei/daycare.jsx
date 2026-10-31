// daycare.jsx — authenticated Daycare workspace foundation + overview/settings.
// Supabase remains authoritative through domain-specific connector endpoints.
const { useState: useStateDcx, useEffect: useEffectDcx, useCallback: useCallbackDcx } = React;

const DCX_ACCENT = "#2DD4BF";
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
    // Re-check first: the box re-mints an auto-admin session, so the owner never sees a login
    // screen. Only if that still fails does the sign-in form appear.
    let rechecking = false;
    const expire = async () => {
      if (rechecking) return; rechecking = true;
      try { await check(); } finally { rechecking = false; }
    };
    window.addEventListener("forge-daycare-auth-expired", expire);
    return () => window.removeEventListener("forge-daycare-auth-expired", expire);
  }, [check]);
  useEffectDcx(() => {
    window.__forgeDaycareProfile = state.profile;
    window.dispatchEvent(new CustomEvent("forge-daycare-session", { detail: state }));
  }, [state]);
  if (state.loading) return <div className="dc-auth-loading"><div className="dc-spinner" /><b>Securing Daycare workspace</b></div>;
  if (!state.authenticated) return <DcxLogin reason={state.reason} onAuthenticated={check} testMode={state.testMode} testProfiles={state.testProfiles} />;
  return <DcxLocationScope>{children}</DcxLocationScope>;
}

// Every daycare page is scoped to ONE center at a time. Switching re-keys the subtree so
// each page's DcxUseResource refetches against the new center — no stale rows survive the
// switch. The bar hides itself entirely when the profile belongs to a single center, so
// parents, staff, and single-center managers see exactly what they saw before.
function DcxLocationScope({ children }) {
  const locations = DcxUseResource("/locations", "locations", 60000);
  const rows = Array.isArray(locations.data) ? locations.data : [];
  const [version, setVersion] = useStateDcx(0);
  const [busy, setBusy] = useStateDcx("");

  const pick = async (id) => {
    if (!id || busy) return;
    setBusy(id);
    try {
      await DcxRequest("/location/switch", { body: { location_id: id } });
      locations.refresh();
      setVersion((current) => current + 1);  // remount → every page refetches
    } catch (error) {
      window.alert(error.message || "Could not switch location.");
    } finally {
      setBusy("");
    }
  };

  return <div className="dc-authenticated">
    {rows.length > 1 && <div className="dc-locbar">
      <span className="dc-locbar-label"><window.Icons.Properties size={13}/> Location</span>
      <div className="dc-locbar-tabs">
        {rows.map((row) => <button
          key={row.id}
          className={row.current ? "active" : ""}
          disabled={Boolean(busy)}
          onClick={() => pick(row.id)}>
          {busy === row.id ? "Switching…" : row.name}
        </button>)}
      </div>
      <small className="faint">Each center keeps its own children, staff, and billing.</small>
    </div>}
    <div key={version}>{children}</div>
  </div>;
}

// --- WP-E --- Solomon · Leads — Solomon's enrollment-lead lane, the Lead Desk
// (daycare_leads.py → /api/daycare/leads). Read-only: shows only what GoHighLevel
// recorded — no availability, price or licensing text anywhere.
function DldDuration(sec) {
  if (sec === null || sec === undefined) return "—";
  const s = Number(sec) || 0;
  if (s < 90) return Math.round(s) + "s";
  if (s < 5400) return Math.round(s / 60) + "m";
  if (s < 172800) return Math.round(s / 3600) + "h";
  return Math.round(s / 86400) + "d";
}

// --- W2-5 --- pipeline stages. GHL tags + contact→child ledger + the owner's one-tap LOCAL
// mark (never written to GHL, never messages a family). Furthest stage wins server-side.
const DLD_PIPELINE = [["TOUR_BOOKED", "Tour booked"], ["TOUR_COMPLETED", "Tour done"], ["APPLICATION", "Application"], ["ENROLLED", "Enrolled"], ["LOST", "Lost"]];
const DLD_STAGE_LABEL = { NEW: "New", CONTACTED: "Contacted", RESPONDED: "Responded", NEEDS_HUMAN: "Needs you", ...Object.fromEntries(DLD_PIPELINE) };
const DLD_SOURCE_LABEL = { ghl_tag: "GHL tag", ledger: "enrolled record", local: "your mark", flow: "GHL activity" };
// --- /W2-5 ---

// Same fallback as daycare_leads.display_name: a 1-letter parent field ("I") is no name.
function DldWho(lead) {
  const parent = String(lead.parentName || "").trim();
  if (parent.length >= 2) return parent;
  const child = String(lead.childName || "").trim();
  return child.length >= 2 ? child + "'s family" : "New family";
}

// --- CALENDAR --- Solomon · Calendar (daycare_calendar.py). Confirm tour writes the GHL tour fields + tag:
// the event follows within 15 min, and the published Tour Check-in text goes to the family.
const DTR_CENTERS = [["loc-921-n-18th", "921 N 18th"], ["loc-2318-cecil-b-moore", "2318 Cecil B. Moore"]];

function DtrTourControl(props) {
  const lead = props.lead;
  const known = DTR_CENTERS.some(([tag]) => tag === lead.centerTag);
  const booked = lead.tagStage === "TOUR_BOOKED";
  const [open, setOpen] = useStateDcx(false);
  const [date, setDate] = useStateDcx("");
  const [time, setTime] = useStateDcx("10:00");
  const [center, setCenter] = useStateDcx(known ? lead.centerTag : "");
  const [busy, setBusy] = useStateDcx(false);
  const [note, setNote] = useStateDcx("");
  if (lead.centerTag === "loc-1923-cecil-b-moore") return null;
  const send = async (path, body, ask) => {
    if (!window.confirm(ask)) return;
    setBusy(true); setNote("");
    try {
      const res = await DcxRequest(path, { body: { contact_id: lead.contactId, ...body } });
      if (res.ok === false) setNote(res.error || "Could not save.");
      else { setOpen(false); props.onDone(); }
    } catch (error) { setNote(error.message); } finally { setBusy(false); }
  };
  const confirmAsk = "Confirm this tour for " + date + " at " + time + "?\n\nThe family gets the Tour Check-in text on the tour day, and it goes on the calendar within 15 minutes.";
  return <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end", flexBasis: open ? "100%" : "auto" }}>
    {!open ? <div style={{ display: "flex", gap: 8 }}>
      <button className="link" disabled={busy} onClick={() => setOpen(true)}>{booked ? "Move tour" : "Book tour"}</button>
      {booked && <button className="link" disabled={busy} onClick={() => send("/tour/cancel", {}, "Cancel this tour? It comes off the calendar within 15 minutes.")}>Cancel tour</button>}
    </div> : <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", justifyContent: "flex-end" }}>
      <input type="date" aria-label="Tour date" value={date} onChange={(event) => setDate(event.target.value)}/>
      <input type="time" aria-label="Tour time" step="1800" value={time} onChange={(event) => setTime(event.target.value)}/>
      {!known && <select aria-label="Tour center" value={center} onChange={(event) => setCenter(event.target.value)}><option value="">Center</option>{DTR_CENTERS.map(([tag, label]) => <option key={tag} value={tag}>{label}</option>)}</select>}
      <button className="dc-primary" disabled={busy || !date || !time || !center} onClick={() => send("/tour/confirm", { date, time, center }, confirmAsk)}>{busy ? "Saving…" : "Confirm tour"}</button>
      <button className="link" disabled={busy} onClick={() => setOpen(false)}>Close</button>
    </div>}
    {note && <small className="dc-error-text" role="alert">{note}</small>}
  </div>;
}

function DcsCalendarStatus() {
  const res = DcxUseResource("/calendar", null, 60000);
  const data = res.data && !Array.isArray(res.data) ? res.data : {};
  const held = data.held || [];
  if (res.loading || res.error || (!data.error && !held.length && data.mode !== "qa")) return null;
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Google Calendar</div><div className="faint">{data.mode === "qa" ? "QA mode · only test contacts · " : ""}{data.events || 0} event(s) on the calendar{data.lastRunAt ? " · updated " + DcxDate(data.lastRunAt, true) : ""}</div></div></div>
    {data.error && <div className="dc-error-text" role="alert">{data.error}</div>}
    {held.length > 0 && <div className="dc-alert-list">{held.map((row) => <div key={row.kind + row.contactId}><span className="dc-severity warning"/><div><b>{row.who}</b><small>{row.reason}</small></div></div>)}</div>}
  </div>;
}
// --- /CALENDAR ---

function DldLeadDesk() {
  const desk = DcxUseResource("/leads", null, 60000);
  const [dldBusy, setDldBusy] = useStateDcx("");
  const [dldNote, setDldNote] = useStateDcx("");
  const dldMark = async (contactId, stage) => {
    setDldBusy(contactId); setDldNote("");
    try {
      const result = await DcxRequest("/leads/stage", { body: { contact_id: contactId, stage: stage || null } });
      if (result.ok === false) setDldNote(result.error || "Could not save the stage.");
      desk.setData(await DcxRequest("/leads"));
    } catch (error) { setDldNote(error.message); } finally { setDldBusy(""); }
  };
  const data = desk.data && !Array.isArray(desk.data) ? desk.data : {};
  const k = data.kpis || {};
  const d7 = k.newLeads7d || {};
  const d30 = k.newLeads30d || {};
  const items = data.needsHuman || [];
  const pipe = k.pipeline || {};
  const leads = data.leads || [];
  const err = desk.error ? (desk.error.message || "Solomon · Leads is unavailable.") : data.error;
  const ran = Boolean(data.lastRunAt);
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Solomon · Leads</div><div className="faint">Enrollment leads from GoHighLevel · read-only{ran ? " · updated " + DcxDate(data.lastRunAt, true) : ""}</div></div><b>{items.length}</b></div>
    {err && <div className="dc-error-text" role="alert">{err}</div>}
    {desk.loading ? <div className="dc-inline-empty">Loading leads…</div> : ran && <>
      <div className="dc-kpi-grid">
        <DcxKpi label="New Leads (7d)" value={d7.total || 0} sub={"30d: " + (d30.total || 0) + " · Meta " + (d30.meta || 0) + " · organic " + (d30.organic || 0)} icon="Children"/>
        <DcxKpi label="Lead Response Time" value={DldDuration(k.medianResponseSec)} sub={"median first reply, 30d · human " + DldDuration(k.medianHumanResponseSec)} icon="Conversations" color="#38BDF8"/>
        <DcxKpi label="Leads Needing Human Attention" value={items.length} sub="waiting on you now" icon="Bell" color={items.length ? "#F4B860" : "#22C55E"}/>
      </div>
      <div className="dc-kpi-grid">{DLD_PIPELINE.map(([key, label]) => <DcxKpi key={key} label={label} value={pipe[key] ?? "—"} sub={pipe[key] == null ? "not recorded yet" : "leads at this stage, 90d"} icon={key === "ENROLLED" ? "Check" : "Children"} color={key === "LOST" ? "#94A3B8" : key === "ENROLLED" ? "#22C55E" : "#8B5CF6"}/>)}</div>
      {items.length ? <div className="dc-alert-list">{items.map((item) => <div key={item.id}><span className={"dc-severity " + (item.priority === "URGENT" ? "danger" : "warning")}/><div><b>{item.title} · {DldDuration(item.ageSec)}</b><small>{item.why}{item.ghlUrl ? <> · <a className="link" style={{ fontSize: "inherit" }} href={item.ghlUrl} target="_blank" rel="noreferrer">Open in GHL ↗</a></> : null}</small></div></div>)}</div>
        : <div className="dc-all-clear"><window.Icons.Check size={22}/><div><b>Nothing waiting on you</b><span>No unanswered replies, overdue call tasks or call-me requests.</span></div></div>}
      {leads.length > 0 && <details style={{ marginTop: 12 }}><summary className="faint" style={{ cursor: "pointer" }}>All leads ({leads.length}) — mark a stage (internal only) · Book tour updates GHL and texts the family on the tour day</summary>
        {dldNote && <div className="dc-error-text" role="alert">{dldNote}</div>}
        <div className="dc-alert-list">{leads.map((lead) => <div key={lead.contactId} style={{ alignItems: "center", flexWrap: "wrap" }}><span className={"dc-severity " + (lead.reasons && lead.reasons.length ? "warning" : "info")}/><div style={{ flex: 1 }}><b>{DldWho(lead)} · {lead.center}</b><small>{DLD_STAGE_LABEL[lead.stage] || lead.stage} · from {DLD_SOURCE_LABEL[lead.stageSource] || "GHL activity"}</small></div><select aria-label="Mark stage" style={{ flex: "0 0 110px" }} value={lead.localStage || ""} disabled={dldBusy === lead.contactId} onChange={(event) => dldMark(lead.contactId, event.target.value)}><option value="">Auto</option>{DLD_PIPELINE.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><DtrTourControl lead={lead} onDone={desk.refresh}/></div>)}</div>
      </details>}
    </>}
  </div>;
}
// --- /WP-E ---

// --- STARTS --- Solomon · Starts (daycare_starts.py → /api/daycare/starts). The start date
// agreed in the family's texts, proposed here + on their GHL contact. Confirm (prompted 2 days
// before) enrolls the child with no text; on the start day the lane texts the app login + guide.
const DST_STATUS = { proposed: "Needs your confirm", confirmed: "Confirmed · login texts that morning", sending: "Sending…", sent: "Login sent", failed: "Send failed" };
const DST_NEEDS = { email: ["Parent email", "email"], child_dob: ["Child birth date", "date"], child_first: ["Child first name", "text"], child_last: ["Child last name", "text"], location_id: ["Center", "center"] };
const DST_CENTERS = [["11111111-1111-1111-1111-111111111111", "A Touch of Blessings (921 N 18th)"], ["22222222-2222-2222-2222-222222222222", "A Touch of Blessings 2 (2318 Cecil B. Moore)"], ["44444444-4444-4444-4444-444444444444", "A Mother's Touch (1923 Cecil B. Moore)"]];

function DstWhen(row) {
  const d = row.daysUntil;
  if (d === null || d === undefined) return "";
  if (d < 0) return Math.abs(d) + "d ago";
  return d === 0 ? "today" : d === 1 ? "tomorrow" : "in " + d + " days";
}

function DstRow(props) {
  const r = props.row;
  const [date, setDate] = useStateDcx(r.startDate || "");
  const [needs, setNeeds] = useStateDcx([]);
  const [extras, setExtras] = useStateDcx({});
  const [busy, setBusy] = useStateDcx("");
  const [note, setNote] = useStateDcx("");
  const child = String(r.childName || r.childFirst || "").trim();
  const parent = String(r.parentName || "").trim();
  const who = child && child.toLowerCase() !== parent.toLowerCase() ? child + (parent ? " · parent " + parent : "") : (parent ? parent + "'s family" : "New family");
  const call = async (kind, body, ask) => {
    if (ask && !window.confirm(ask)) return;
    setBusy(kind); setNote("");
    try {
      const res = await DcxRequest("/starts/" + kind, { body: { contact_id: r.contactId, ...body } });
      if (res.ok === false) { setNote(res.error || "Could not save."); setNeeds(res.needs || []); }
      else { setNeeds([]); props.onDone(); }
    } catch (error) { setNote(error.message); } finally { setBusy(""); }
  };
  const open = r.status === "proposed";
  const confirmAsk = "Confirm " + (r.childFirst || "this child") + " starts " + date + "?\n\nThis enrolls the child (start date " + date + ") and makes sure the parent has an app login — nothing is texted now. On " + date + " after 8am, the parent is texted their login + how to get the app.";
  return <div style={{ alignItems: "flex-start" }}>
    <span className={"dc-severity " + (r.status === "failed" ? "danger" : r.confirmOpen ? "warning" : r.status === "proposed" ? "info" : "success")}/>
    <div style={{ flex: 1 }}>
      <b>{who} · {r.center}</b>
      <small>{DST_STATUS[r.status] || r.status} · starts {r.startDate} ({DstWhen(r)}){r.reopened ? " · date changed in their texts — re-confirm" : ""}</small>
      <small className="faint">“{r.evidence}”{r.source === "messages" && r.evidenceAt ? " · " + DcxDate(r.evidenceAt, true) : ""}</small>
      {r.lastError && <small className="dc-error-text">{r.lastError}</small>}
      {open && <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8, alignItems: "center" }}>
        <input type="date" aria-label="Start date" value={date} onChange={(event) => setDate(event.target.value)}/>
        {needs.map((key) => { const [label, type] = DST_NEEDS[key] || [key, "text"]; return type === "center"
          ? <select key={key} aria-label={label} value={extras[key] || ""} onChange={(event) => setExtras({ ...extras, [key]: event.target.value })}><option value="">{label}…</option>{DST_CENTERS.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select>
          : <input key={key} type={type} placeholder={label} aria-label={label} value={extras[key] || ""} onChange={(event) => setExtras({ ...extras, [key]: event.target.value })}/>; })}
        <button className="dc-primary" disabled={Boolean(busy) || !date} onClick={() => call("confirm", { start_date: date, extras }, confirmAsk)}>{busy === "confirm" ? "Confirming…" : "Confirm start date"}</button>
        {date !== r.startDate && <button className="dc-outline" disabled={Boolean(busy)} onClick={() => call("date", { start_date: date })}>Save date only</button>}
        <button className="dc-outline" disabled={Boolean(busy)} onClick={() => call("calendar", { on: !r.calendarAt })}>{r.calendarAt ? "On calendar · remove" : "Add to calendar"}</button>
        <button className="link" disabled={Boolean(busy)} onClick={() => call("dismiss", {}, "Not a start date? It drops off this list.")}>Not a start date</button>
      </div>}
      {r.status === "confirmed" && <div style={{ marginTop: 6 }}><button className="link" disabled={Boolean(busy)} onClick={() => call("date", { start_date: r.startDate }, "Undo the confirm? Nothing will be texted until you confirm again.")}>Undo confirm</button></div>}
      {note && <small className="dc-error-text" role="alert">{note}</small>}
    </div>
  </div>;
}

function DstStartDates() {
  const res = DcxUseResource("/starts", null, 60000);
  const data = res.data && !Array.isArray(res.data) ? res.data : {};
  const rows = (data.starts || []).filter((r) => r.status !== "sent" || (r.daysUntil ?? -99) >= -3);
  const waiting = rows.filter((r) => r.confirmOpen || r.status === "failed").length;
  if (!res.loading && !rows.length && !data.error) return null;
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Start dates</div><div className="faint">From their texts · confirm 2 days before · the app login + guide texts on the start day{data.lastRunAt ? " · updated " + DcxDate(data.lastRunAt, true) : ""}</div></div><b>{waiting}</b></div>
    {data.error && <div className="dc-error-text" role="alert">{data.error}</div>}
    {res.loading ? <div className="dc-inline-empty">Loading start dates…</div>
      : <div className="dc-alert-list">{rows.map((row) => <DstRow key={row.contactId + row.startDate + row.status} row={row} onDone={res.refresh}/>)}</div>}
  </div>;
}
// --- /STARTS ---

// --- BOARD --- Solomon · Board (daycare_board.py → /api/daycare/board). Zero-AI watch rounds fill it
// (daycare_watches.py). Snooze / Done / Run round are internal + reversible: Done reopens next round if
// the source still shows the problem. A source that failed is Unknown — never "0 items".
const DBD_SEV = [["urgent", "Urgent", "danger"], ["high", "High", "warning"], ["normal", "Normal", "info"], ["low", "Low", "success"]];
const DBD_SRC = { inbox: "Gmail", enrollment: "Enrollment (GHL · Starts · Auto-enroll)", billing: "Billing (Supabase)", ads: "Ads (Meta via Pipeboard)", social: "Social (Metricool)", roster: "Roster (Supabase)", systems: "Systems" };

function DbdSourceLine(s) {
  if (s.domain === "inbox") return (s.notWired ? "Gmail not connected" : "Gmail read failed") + " — 0 mail items is Unknown, not zero";
  return (DBD_SRC[s.domain] || s.domain) + (s.notWired ? " not wired" : " read failed") + " — 0 " + s.domain + " items is Unknown, not zero";
}

function DbdBoard() {
  const bd = DcxUseResource("/board?limit=60", null, 60000);
  const [dbdBusy, setDbdBusy] = useStateDcx("");
  const [dbdNote, setDbdNote] = useStateDcx("");
  const dbdAct = async (kind, body) => {
    setDbdBusy(kind + (body && body.id ? ":" + body.id : "")); setDbdNote("");
    try {
      const res = await DcxRequest("/board/" + kind, { body: body || {} });
      if (res.ok === false) setDbdNote(res.error || "Could not update the board.");
      else if (res.skipped) setDbdNote(res.skipped);
      else if (res.line) setDbdNote("Round done — " + res.line);
    } catch (error) { setDbdNote(error.message); } finally { setDbdBusy(""); bd.refresh(); }
  };
  const data = bd.data && !Array.isArray(bd.data) ? bd.data : {};
  const items = data.items || [];
  const counts = data.counts || {};
  const bad = (data.sources || []).filter((s) => !s.ok);
  const mail = data.mailDesk || null;
  const lr = data.lastRound || null;
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Solomon · Board</div><div className="faint">Every daycare domain in one ranked list · zero-AI watch rounds · {lr ? "last round " + DcxDate(lr.ranAt, true) : "no round yet"}{counts.snoozed ? " · " + counts.snoozed + " snoozed" : ""}</div></div><div style={{ display: "flex", gap: 8, alignItems: "center" }}><b>{counts.open || 0}</b><button className="dc-outline" disabled={Boolean(dbdBusy)} onClick={() => dbdAct("run")}>{dbdBusy === "run" ? "Running…" : "Run round now"}</button></div></div>
    {bd.error && <div className="dc-error-text" role="alert">{bd.error.message || "The board is unavailable."}</div>}
    {bad.map((s) => <div key={s.domain} className="dc-error-text" role="alert">⚠️ {DbdSourceLine(s)}{s.error ? " · " + s.error : ""}</div>)}
    {dbdNote && <div className="faint" role="status">{dbdNote}</div>}
    {bd.loading ? <div className="dc-inline-empty">Loading the board…</div> : !items.length
      ? <div className="dc-all-clear"><window.Icons.Check size={22}/><div><b>Nothing open — last round {lr ? DcxDate(lr.ranAt, true) : "not run yet"}</b><span>{lr ? lr.line : "Run a round to fill the board."}</span></div></div>
      : DBD_SEV.map(([sev, label, tone]) => { const rows = items.filter((i) => i.severity === sev); return rows.length ? <div key={sev} style={{ marginTop: 10 }}>
        <div className="dc-section-label">{label} · {rows.length}</div>
        <div className="dc-alert-list">{rows.map((i) => <div key={i.id} style={{ alignItems: "flex-start" }}>
          <span className={"dc-severity " + tone}/>
          <div style={{ flex: 1 }}>
            <b>{i.title}</b>
            <small><span className="dc-severity-pill">{i.domain}</span> · {i.center} · {DldDuration(i.ageSec)} old{i.owner === "solomon" ? " · Solomon can fix this himself" : ""}</small>
            {i.why && <small>{i.why}</small>}
            <small className="faint">{(i.evidence || {}).source} · {(i.evidence || {}).window}</small>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <button className="link" disabled={Boolean(dbdBusy)} onClick={() => dbdAct("snooze", { id: i.id, hours: 24 })}>Snooze 24h</button>
            <button className="link" disabled={Boolean(dbdBusy)} title="Comes back next round if the source still shows it" onClick={() => dbdAct("done", { id: i.id })}>Done</button>
          </div>
        </div>)}</div></div> : null; })}
    {mail && <details style={{ marginTop: 12 }} open={Boolean(mail.top && mail.top.length)}><summary className="faint" style={{ cursor: "pointer" }}>Inbox — {mail.ok === false ? "Unknown (" + (mail.error || "read failed") + ")" : (mail.unread || 0) + " unread daycare mail · " + (mail.needsAnswer || 0) + " need an answer · " + (mail.window || "")}</summary>
      {(mail.top || []).length ? <div className="dc-alert-list">{mail.top.map((m, idx) => <div key={idx}><span className="dc-severity info"/><div><b>{m.subject || "(no subject)"}</b><small>{m.from} · {m.bucket}{m.date ? " · " + DcxDate(m.date, true) : ""}</small></div></div>)}</div>
        : mail.ok !== false && <div className="dc-inline-empty">No unread daycare mail.</div>}
    </details>}
  </div>;
}
// --- /BOARD ---

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
    <DbdBoard/>{/* --- BOARD --- */}
    <DstStartDates/>{/* --- STARTS --- */}
    <DcsCalendarStatus/>{/* --- CALENDAR --- */}
    <DldLeadDesk/>{/* --- WP-E --- */}
    {window.DcaAdsCard && <window.DcaAdsCard/>}{/* --- ENROLLMENT ADS (Pipeboard) --- */}
    {window.DcaAdGenCard && <window.DcaAdGenCard/>}{/* --- AD GENERATOR --- */}
    <div className="dc-main-grid"><div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Center pulse</div><div className="faint">Fast paths for today’s operations</div></div><span className="dc-live"><i/> LIVE</span></div><div className="dc-day-grid">{[["Attendance","Attendance",checkedIn + " currently in"],["CareLogs","Daily Logs","Care updates"],["Incidents","Incidents","Safety records"],["Billing","Billing","Family balances"]].map((item) => { const Icon = window.Icons[item[0]] || window.Icons.Dashboard; return <button key={item[0]} onClick={() => window.GoTo(item[0])}><span><Icon size={18}/></span><b>{item[1]}</b><small>{item[2]}</small></button>; })}</div></div><div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Management alerts</div><div className="faint">Prioritized operational exceptions</div></div><b>{alerts.length}</b></div>{alerts.length ? <div className="dc-alert-list">{alerts.slice(0,5).map((alert, index) => <div key={alert.id || index}><span className={"dc-severity " + (alert.severity || "info")}/><div><b>{alert.title || alert.kind || "Needs review"}</b><small>{alert.body || alert.message || "Open the related page for details."}</small></div></div>)}</div> : <div className="dc-all-clear"><window.Icons.Check size={22}/><div><b>All clear</b><span>No operational alerts right now.</span></div></div>}</div></div>
    <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Classroom capacity</div><div className="faint">Live enrollment by room</div></div><button className="link" onClick={() => window.GoTo("Classrooms")}>Manage classrooms</button></div><div className="dc-room-strip">{rooms.length ? rooms.map((room) => { const count = Number(room.enrolled_count ?? room.child_count ?? (room.children || []).length ?? 0); const cap = Number(room.capacity) || 0; const color = room.color || DCX_ACCENT; return <div key={room.id}><div className="dc-room-top"><span style={{color}}>{room.name}</span><b>{count}/{cap}</b></div><small>{room.age_group || "Age group not set"}</small><div className="progress"><div style={{width: Math.min(100, cap ? count / cap * 100 : 0) + "%", background: color}}/></div></div>; }) : <div className="dc-inline-empty">No active classrooms yet.</div>}</div></div>
  </></DcxState></div>;
}


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
  DCX_ACCENT, DcxRequest, DcxUnwrap, DcxName, DcxChildName, DcxMoney, DcxDate, DcxToday,
  DcxUseResource, DcxPageHead, DcxKpi, DcxState, DcxModal, DcxConfirm, DcxField,
  DaycareWorkspace, DaycareDashboard, DaycareSettings,
});
