// FORGE Mobile — business portal: DAYCARE (A Touch of Blessings) — the management app.
// Styled after the family/staff daycare app (purple + gold, Fraunces/Manrope; scoped
// .biz-daycare theme in mobile.css). Same Supabase + GHL the desktop console drives;
// the connector holds every key and the box auto-admins tailnet traffic as Management.
// Hook aliases for this file: BD. Top-level names: MBD*. Exports: MBDHome, MBDMessages,
// MBDFamilies, MBDLogins + window.M_BIZ.daycare.
//
// Tabs: Home (diagnostics + Solomon) · Messages (GHL) · Families (enrollment) · Logins.
// Solomon is the one daycare agent — Leads + Replies are his lanes; chat = Crew (🤖).
// Every outward/irreversible action is an explicit tap + window.confirm (rule 2):
//   POST /api/daycare/replies/approve {contact_id,text}   send Solomon's (edited) draft
//   POST /api/daycare/ghl/reply       {contact_id,text}   owner-typed text
//   POST /api/daycare/ghl/enroll      {family}            Contact-Form → roster + login
//   POST /api/daycare/child/save      new child (+ parent login) / add login to a child
//   POST /api/daycare/staff/save      new staff login
//   POST /api/daycare/guardian/reset-pin {profile_id}     fresh one-time PIN
// Internal + reversible: /replies/dismiss, /leads/stage, /location/switch.
const { useState: useStateBD, useEffect: useEffectBD } = React;

const MBD_STAGES = [["TOUR_BOOKED", "Tour booked"], ["TOUR_COMPLETED", "Tour complete"],
  ["APPLICATION", "Application"], ["ENROLLED", "Enrolled"], ["LOST", "Lost"]];
const MBD_AUTH_CODES = ["session_expired", "authentication_required", "https_required", "forbidden",
  "management_required", "profile_missing", "inactive_account", "location_mismatch", "origin_rejected"];
const MBD_STALE_MS = 30 * 86400 * 1000;   // matches FORGE_OWNER_ACTIONS_STALE_DAYS

// useApiM puts a daycare error payload in both .data ({ok:false,code}) and .error.
function MBDAuth(res) {
  const d = res && res.data;
  return !!(d && d.ok === false && MBD_AUTH_CODES.includes(d.code))
    || /\b40[13]\b|session expired|login is required/i.test(String((res && res.error) || ""));
}
// Lead Desk / Reply Desk return ok:true WITH an error string when a sweep failed —
// that is stale data (warn), not a failed load.
function MBDFailed(res) { return !!(res && res.error) && !(res.data && res.data.ok === true); }
function MBDAuthLine() {
  return <div className="mw-warn">Daycare session needed — open the desktop Daycare tab once, then pull to refresh.</div>;
}
function MBDAgo(ts) { const a = window.timeAgoM(ts); return !a ? "" : a === "now" ? "just now" : a + " ago"; }
function MBDDur(sec) {
  if (sec == null) return "—";
  return sec < 3600 ? Math.max(1, Math.round(sec / 60)) + " min" : (sec / 3600).toFixed(1) + " h";
}
function MBDLine(x) {
  if (x == null) return "";
  if (typeof x !== "object") return String(x);
  const head = x.title || x.family || x.angle || x.role || x.summary || "";
  const tail = x.why || x.reason || x.task || x.gap || "";
  const next = x.action || x.suggestedNextStep || "";
  return [head, tail].filter(Boolean).join(" — ") + (next ? " → " + next : "");
}
function MBDGo(tab) { if (window.mGoTab) window.mGoTab(tab); }
function MBDName(s, fallback) { const t = String(s || "").trim(); return t.length >= 2 ? t : (fallback || "New family"); }
function MBDInitials(s) { return String(s || "").split(/\s+/).map((w) => (w.match(/[a-z]/i) || [""])[0]).filter(Boolean).slice(0, 2).join("").toUpperCase() || "#"; }
async function MBDCopy(text) {
  try { await navigator.clipboard.writeText(text); window.hapticM && window.hapticM("success"); return true; }
  catch (_) { return false; }
}

function MBDEmblem() { return <img className="mbd-emblem" src="/assets/daycare-emblem.png" alt="" aria-hidden="true" />; }
function MBDHead(props) { return <window.MHeader title={props.title} sub={props.sub} logo={<MBDEmblem />} right={props.right} />; }
function MBDBadge(props) { return <span className={"mbd-badge" + (props.tone ? " " + props.tone : "")}>{props.children}</span>; }
function MBDStat(props) {
  const Ico = window.MIcons[props.ico] || window.MIcons.Heart;
  return <div className="mbd-stat"><span className="mbd-stat-ico"><Ico size={18} /></span>
    <strong>{props.value}</strong><small>{props.label}</small></div>;
}
function MBDSection(props) {
  return <div className="mbd-section"><h3>{props.title}</h3>{props.right || null}</div>;
}
// ok | warn | bad | off | key (credential present, never live-checked) → one diagnostics row.
function MBDCheck(props) {
  return <div className="mbd-row">
    <span className={"mbd-dot " + props.state} />
    <div className="mbd-row-main"><strong>{props.name}</strong><small>{props.detail}</small></div>
    {props.badge || null}
  </div>;
}
function MBDSheet(props) {
  return <div className="m-sheet mbd-sheet">
    <div className="m-sheet-head"><button className="m-tab" style={{ flex: "none", padding: 4 }} onClick={props.onClose} aria-label="Close"><window.MIcons.Back size={22} /></button>
      <b style={{ flex: 1, minWidth: 0 }}>{props.title}</b>{props.right || null}</div>
    <div className="m-sheet-body">{props.children}</div>
    {props.foot && <div className="m-sheet-foot">{props.foot}</div>}
  </div>;
}

// ---------------------------------------------------------------- Home (diagnostics)
const MBD_BRIEF_SECTIONS = [["Attention now", "priorities"], ["Enrollment", "enrollment"], ["Money", "money"],
  ["People", "people"], ["Roster", "roster"], ["Family follow-ups", "followUps"],
  ["Campaign health", "campaignHealth"], ["Creative", "creativeRecommendations"], ["Delegations", "delegations"]];

function MBDBriefSheet(props) {
  const b = props.brief;
  const comp = b.competitorRead && (b.competitorRead.summary || (typeof b.competitorRead === "string" ? b.competitorRead : ""));
  return <MBDSheet title="Solomon's brief" onClose={props.onClose}>
    <div className="m-card"><div className="mbd-display" style={{ fontSize: 19 }}>{b.headline}</div>
      {props.at && <div className="m-fade" style={{ marginTop: 4 }}>Written {MBDAgo(props.at)}</div>}</div>
    <div className="m-card mw-brief">
      {MBD_BRIEF_SECTIONS.filter(([, k]) => Array.isArray(b[k]) && b[k].length).map(([title, k]) => <section key={k}>
        <b>{title}</b>{b[k].map((x, i) => <p key={i}>• {MBDLine(x)}</p>)}
      </section>)}
      {comp && <section><b>Competitor read</b><p>{comp}</p></section>}
    </div>
    <window.MBtn onClick={() => { props.onClose(); MBDGo("agents"); }}>Talk to Solomon →</window.MBtn>
  </MBDSheet>;
}

function MBDLoop(loops, key) { return (loops || []).find((l) => l.loop === key) || null; }
function MBDLoopCheck(props) {
  const l = props.loop;
  if (!l) return <MBDCheck state="off" name={props.name} detail="No heartbeat — only the box runs this loop." />;
  const state = l.status === "green" ? "ok" : l.status === "red" ? "bad" : "warn";
  const detail = l.lastError && state !== "ok" ? String(l.lastError).slice(0, 120)
    : "Last run " + (MBDAgo(l.lastRun) || "—") + (l.interval ? " · every " + MBDDur(l.interval) : "");
  return <MBDCheck state={state} name={props.name} detail={detail} />;
}

function MBDHome() {
  const me = window.useApiM("/api/daycare/auth/status");
  const locs = window.useApiM("/api/daycare/locations");
  const ov = window.useApiM("/api/daycare/overview", { interval: 120000 });
  const rooms = window.useApiM("/api/daycare/classrooms", { interval: 300000 });
  const leads = window.useApiM("/api/daycare/leads", { interval: 60000 });
  const reps = window.useApiM("/api/daycare/replies", { interval: 60000 });
  const brief = window.useApiM("/api/daycare/director/brief", { interval: 120000 });
  const dir = window.useApiM("/api/daycare/director/status", { interval: 120000 });
  const st = window.useApiM("/api/daycare/status", { interval: 300000 });
  const ghl = window.useApiM("/api/daycare/ghl/health", { interval: 300000 });
  const sys = window.useApiM("/api/system/health", { interval: 60000 });
  const [switching, setSwitching] = useStateBD("");
  const [err, setErr] = useStateBD("");
  const [showBrief, setShowBrief] = useStateBD(false);

  const auth = MBDAuth(ov) || MBDAuth(locs) || MBDAuth(leads);
  const prof = (me.data && me.data.profile) || null;
  const locList = (locs.data && locs.data.ok && locs.data.locations) || [];
  const activeLoc = locs.data && locs.data.activeLocationId;
  const center = (ov.data && ov.data.center && ov.data.center.name) || (locList.find((l) => l.id === activeLoc) || {}).name || "A Touch of Blessings";
  const m = (ov.data && ov.data.ok && ov.data.metrics) || null;
  const alerts = (ov.data && ov.data.ok && ov.data.alerts) || [];
  const roomList = (rooms.data && rooms.data.ok && rooms.data.classrooms || []).filter((r) => r.active !== false);
  const ld = leads.data && leads.data.ok ? leads.data : null;
  const kpis = (ld && ld.kpis) || {};
  const pending = (reps.data && reps.data.ok && reps.data.pending) || [];
  const b = (brief.data && brief.data.ok && brief.data.brief) || null;
  const ds = dir.data || {};
  const loops = (sys.data && sys.data.loops) || [];
  const ai = (sys.data && sys.data.ai) || null;
  const s = st.data || {};
  const g = ghl.data || {};

  async function switchTo(id) {
    if (!id || id === activeLoc) return;
    setSwitching(id); setErr("");
    try { await window.apiPostM("/api/daycare/location/switch", { location_id: id }); locs.refresh(); }
    catch (e) { setErr("Couldn't switch center — " + ((e && e.message) || "retry")); }
    setSwitching("");
  }

  const briefAge = ds.lastBriefAt ? Date.now() - ds.lastBriefAt : null;
  const briefState = ds.lastError ? (ds.failStreak > 1 ? "bad" : "warn") : briefAge == null ? "off" : briefAge > 48 * 3600e3 ? "warn" : "ok";
  const keyed = (ds.systems || []).filter((x) => /stripe|meta|metricool/i.test(x.key + " " + x.name));

  return <React.Fragment>
    <MBDHead title="Management" sub={center} />
    <div className="m-content mbd-page">
      <section className="mbd-hero">
        <div className="mbd-hero-top"><img src="/assets/daycare-emblem.png" alt="" /><div>
          <small>SIGNED IN AS MANAGEMENT</small>
          <h2>{center}</h2>
          <p>{prof ? (prof.display_name || [prof.first_name, prof.last_name].filter(Boolean).join(" ")) + " · " + prof.role : "Connecting to the center…"}</p>
        </div></div>
        {locList.length > 1 && <div className="mbd-locs">{locList.map((l) => <button key={l.id}
          className={"mbd-loc" + (l.id === activeLoc ? " active" : "")} disabled={!!switching}
          onClick={() => switchTo(l.id)}>{switching === l.id ? "…" : l.name}</button>)}</div>}
      </section>
      {auth && <MBDAuthLine />}
      {err && <div className="mw-warn">{err}</div>}

      <div className="mbd-stats">
        <MBDStat ico="Check" label="Here today" value={m ? m.presentToday : "—"} />
        <MBDStat ico="Heart" label={m && m.capacityTotal ? "Enrolled / capacity" : "Enrolled"} value={!m ? "—" : m.capacityTotal ? m.childrenActive + "/" + m.capacityTotal : m.childrenActive} />
        <MBDStat ico="User" label="Staff active" value={m ? m.staffActive : "—"} />
        <MBDStat ico="Flame" label="Open incidents" value={m ? m.openIncidents : "—"} />
      </div>
      {!auth && MBDFailed(ov) && <div className="mw-warn">Center metrics unavailable — {String(ov.error)}</div>}
      {alerts.map((a, i) => <div className={a.level === "warning" ? "mw-warn" : "mbd-note"} key={i}>{a.title}{a.body ? " — " + a.body : ""}</div>)}

      <MBDSection title="Needs you" />
      <div className="m-card mbd-list">
        <button className="mbd-row mbd-tap" onClick={() => MBDGo("messages")}>
          <span className="mbd-row-ico"><window.MIcons.Chat size={18} /></span>
          <div className="mbd-row-main"><strong>Parent replies</strong><small>{pending.length ? pending.length + " Solomon draft" + (pending.length === 1 ? "" : "s") + " ready to send" : "No drafts waiting"}</small></div>
          {pending.length > 0 && <MBDBadge tone="gold">{pending.length}</MBDBadge>}<span className="mbd-chev">›</span>
        </button>
        <button className="mbd-row mbd-tap" onClick={() => MBDGo("families")}>
          <span className="mbd-row-ico"><window.MIcons.Phone size={18} /></span>
          <div className="mbd-row-main"><strong>New families to call</strong><small>{ld && ld.lastRunAt ? (kpis.needsHuman || 0) + " waiting · median human reply " + MBDDur(kpis.medianHumanResponseSec) : "Lead sweep hasn't run yet"}</small></div>
          {kpis.needsHuman > 0 && <MBDBadge tone="red">{kpis.needsHuman}</MBDBadge>}<span className="mbd-chev">›</span>
        </button>
        <button className="mbd-row mbd-tap" onClick={() => MBDGo("logins")}>
          <span className="mbd-row-ico"><window.MIcons.Key size={18} /></span>
          <div className="mbd-row-main"><strong>Logins</strong><small>Create parent + staff logins, reset PINs</small></div><span className="mbd-chev">›</span>
        </button>
      </div>

      <MBDSection title="Solomon" right={b && brief.data.lastBriefAt ? <span className="m-fade">{MBDAgo(brief.data.lastBriefAt)}</span> : null} />
      <div className="m-card">
        {brief.loading && !brief.data ? <window.MSpin /> : !b ? <div className="m-fade">No brief yet — Solomon writes one daily on the box.</div>
          : <React.Fragment>
            <div className="mbd-display" style={{ fontSize: 17, marginBottom: 6 }}>{b.headline}</div>
            {(b.priorities || []).slice(0, 3).map((p, i) => <div className="mbd-row" key={i}>
              <MBDBadge tone="gold">{String(p.urgency || p.area || "now").slice(0, 10)}</MBDBadge>
              <div className="mbd-row-main"><strong>{p.title || MBDLine(p)}</strong><small>{p.why || ""}</small></div>
            </div>)}
          </React.Fragment>}
        <div className="mbd-actions">
          {b && <window.MBtn kind="ghost" onClick={() => setShowBrief(true)}>Full brief</window.MBtn>}
          <window.MBtn onClick={() => MBDGo("agents")}>Talk to Solomon</window.MBtn>
        </div>
      </div>

      {roomList.length > 0 && <React.Fragment>
        <MBDSection title="Classrooms" right={<span className="m-fade">{roomList.length} rooms</span>} />
        <div className="m-card mbd-list">{roomList.map((r) => {
          const pct = r.capacity ? Math.min(100, Math.round((r.enrolled / r.capacity) * 100)) : 0;
          return <div className="mbd-room" key={r.id}>
            <div className="mbd-room-head"><strong>{r.name}</strong><small>{r.enrolled}/{r.capacity} · 1:{r.ratio_children}</small></div>
            <div className="mbd-bar"><i style={{ width: pct + "%", background: pct >= 100 ? "var(--dc-red)" : pct >= 85 ? "var(--dc-gold)" : "var(--dc-purple)" }} /></div>
            <small className="m-fade">{r.age_group}{r.capacity > r.enrolled ? " · " + (r.capacity - r.enrolled) + " open" : " · full"}</small>
          </div>;
        })}</div>
      </React.Fragment>}

      <MBDSection title="System check" right={<button className="m-chip" onClick={() => { sys.refresh(); st.refresh(); ghl.refresh(); dir.refresh(); }}>Refresh</button>} />
      <div className="m-card mbd-list">
        <MBDCheck name="Daycare database" state={s.healthy && s.live ? (s.writesEnabled ? "ok" : "warn") : st.data ? "bad" : "off"}
          detail={!st.data ? "Checking…" : s.healthy && s.live ? (s.writesEnabled ? "Supabase live · writes on" : "Supabase live · writes OFF (read-only)") : "Supabase not reachable"} />
        <MBDCheck name="GoHighLevel" state={g.connected ? "ok" : ghl.data ? "bad" : "off"}
          detail={!ghl.data ? "Checking…" : g.connected ? "Messages + contacts connected" : (g.detail || "Not connected")} />
        <MBDCheck name="Claude (agents' brain)" state={!ai ? "off" : ai.ok ? "ok" : "bad"}
          detail={!ai ? "Unknown" : ai.ok ? "Answering" : (ai.reason || ai.kind || "Down") + (ai.hard ? " — needs owner action" : "")} />
        <MBDCheck name="Solomon · brief" state={briefState}
          detail={ds.lastError ? String(ds.lastError).slice(0, 120) : ds.lastBriefAt ? "Last brief " + MBDAgo(ds.lastBriefAt) : "No brief yet"} />
        <MBDLoopCheck name="Solomon · Replies" loop={MBDLoop(loops, "daycare_replies")} />
        <MBDLoopCheck name="Solomon · Leads" loop={MBDLoop(loops, "daycare_leads")} />
        {keyed.map((x) => <MBDCheck key={x.key} name={x.name} state={x.connected ? "key" : "off"}
          detail={x.connected ? "Key on file (not a live check)" : "No key — add it to daycare.env"} />)}
      </div>
    </div>
    {showBrief && b && <MBDBriefSheet brief={b} at={brief.data.lastBriefAt} onClose={() => setShowBrief(false)} />}
  </React.Fragment>;
}

// ---------------------------------------------------------------- Messages (GHL)
function MBDDraftCard(props) {
  const d = props.draft;
  const [text, setText] = useStateBD(d.draft || "");
  const [busy, setBusy] = useStateBD("");
  const [err, setErr] = useStateBD("");
  const name = MBDName(d.parentName, "Parent");
  async function send() {
    if (!text.trim()) return;
    if (!window.confirm("Text " + name + " now?\n\n\"" + text.trim() + "\"")) return;
    setBusy("send"); setErr("");
    try { await window.apiPostM("/api/daycare/replies/approve", { contact_id: d.contactId, text: text.trim() }); props.onDone(); }
    catch (e) { setErr("Not sent — " + ((e && e.message) || "retry")); setBusy(""); }
  }
  async function skip() {
    setBusy("skip"); setErr("");
    try { await window.apiPostM("/api/daycare/replies/dismiss", { contact_id: d.contactId }); props.onDone(); }
    catch (e) { setErr((e && e.message) || "retry"); setBusy(""); }
  }
  return <div className="m-card mbd-draft">
    <div className="mbd-draft-head"><span className="mbd-avatar">{MBDInitials(name)}</span>
      <div className="mbd-row-main"><strong>{name}</strong><small>{[d.center, d.category, MBDAgo(d.inboundAt)].filter(Boolean).join(" · ")}</small></div>
      <button className="mbd-link" onClick={() => props.onOpen(d.contactId)}>Thread</button></div>
    {d.inboundText && <div className="mbd-quote">“{d.inboundText}”</div>}
    {(d.flags || []).length > 0 && <div className="mbd-flags">{d.flags.map((f, i) => <MBDBadge key={i} tone="red">{String(f)}</MBDBadge>)}</div>}
    <textarea className="m-input mbd-input" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
    {d.why && <div className="m-fade">Solomon: {d.why}</div>}
    {err && <div className="mw-warn">{err}</div>}
    <div className="mbd-actions">
      <window.MBtn kind="ghost" disabled={!!busy} onClick={skip}>{busy === "skip" ? "…" : "Skip"}</window.MBtn>
      <window.MBtn disabled={!!busy || !text.trim()} onClick={send}>{busy === "send" ? "Sending…" : "Send"}</window.MBtn>
    </div>
  </div>;
}

function MBDThread(props) {
  const th = window.useApiM("/api/daycare/ghl/thread?contact_id=" + encodeURIComponent(props.contactId));
  const t = (th.data && th.data.ok) ? th.data : null;
  const [text, setText] = useStateBD(null);
  const [busy, setBusy] = useStateBD(false);
  const [err, setErr] = useStateBD("");
  useEffectBD(() => { if (t && text === null) setText((t.draft && t.draft.draft) || ""); }, [t]);
  useEffectBD(() => { const el = document.querySelector(".mbd-sheet .m-sheet-body"); if (el) el.scrollTop = el.scrollHeight; }, [t && t.messages && t.messages.length]);
  const name = t ? MBDName(t.name, "Parent") : "Conversation";
  async function send() {
    const body = (text || "").trim();
    if (!body || !t) return;
    if (!window.confirm("Text " + name + " now?\n\n\"" + body + "\"")) return;
    setBusy(true); setErr("");
    try {
      await window.apiPostM(t.draft ? "/api/daycare/replies/approve" : "/api/daycare/ghl/reply", { contact_id: t.contactId, text: body });
      setText(""); th.refresh(); props.onSent && props.onSent();
    } catch (e) { setErr("Not sent — " + ((e && e.message) || "retry")); }
    setBusy(false);
  }
  return <MBDSheet title={name} onClose={props.onClose}
    right={t && t.phone ? <a className="mbd-call" href={"tel:" + t.phone} aria-label="Call"><window.MIcons.Phone size={18} /></a> : null}
    foot={t && <React.Fragment>
      {!t.canSend && <div className="mw-warn" style={{ marginBottom: 8 }}>Can't text now — {t.blockReason}.</div>}
      {t.draft && <div className="m-fade" style={{ marginBottom: 6 }}>Solomon's draft is loaded — edit, then send.</div>}
      {err && <div className="mw-warn" style={{ marginBottom: 8 }}>{err}</div>}
      <div className="m-tg-compose">
        <textarea className="m-input m-tg-input" rows={2} maxLength={640} placeholder={t.canSend ? "Type a message…" : ""}
          disabled={!t.canSend || busy} value={text || ""} onChange={(e) => setText(e.target.value)} />
        <button className="m-tg-sendbtn mbd-send" disabled={!t.canSend || busy || !(text || "").trim()} onClick={send} aria-label="Send">
          <window.MIcons.Send size={18} /></button>
      </div>
    </React.Fragment>}>
    {th.loading && !th.data ? <window.MSpin /> : !t ? <div className="mw-warn">Couldn't load this conversation — {String(th.error || "retry")}</div>
      : <React.Fragment>
        <div className="m-fade" style={{ textAlign: "center" }}>{[t.center, t.phone].filter(Boolean).join(" · ")}</div>
        {!t.messages.length && <window.MEmpty title="No messages yet" />}
        {t.messages.map((mm) => <div key={mm.id + mm.at} className={"m-bubble " + (mm.dir === "outbound" ? "out" : "in")}>
          <div style={{ whiteSpace: "pre-wrap" }}>{mm.body || "(" + mm.kind + ")"}</div>
          <div className="mbd-bubble-meta">{MBDAgo(mm.at)}{mm.auto ? " · auto" : ""}{mm.kind && mm.kind !== "sms" ? " · " + mm.kind : ""}</div>
        </div>)}
      </React.Fragment>}
  </MBDSheet>;
}

function MBDMessages() {
  const conv = window.useApiM("/api/daycare/ghl/conversations", { interval: 60000 });
  const reps = window.useApiM("/api/daycare/replies", { interval: 60000 });
  const [seg, setSeg] = useStateBD("needs");
  const [q, setQ] = useStateBD("");
  const [open, setOpen] = useStateBD(null);
  const cd = conv.data && conv.data.ok ? conv.data : null;
  const rows = (cd && cd.conversations) || [];
  const pending = (reps.data && reps.data.ok && reps.data.pending) || [];
  const repErr = reps.data && reps.data.ok && reps.data.error;
  const needs = rows.filter((c) => c.direction === "inbound" || c.draft);
  const ql = q.trim().toLowerCase();
  const list = (seg === "needs" ? needs : rows).filter((c) => !ql || (c.name + " " + c.phone + " " + c.lastMessage).toLowerCase().includes(ql));
  const refresh = () => { conv.refresh(); reps.refresh(); };
  return <React.Fragment>
    <MBDHead title="Messages" sub="GoHighLevel · every parent thread" />
    <div className="m-content mbd-page">
      {(MBDAuth(conv) || MBDAuth(reps)) && <MBDAuthLine />}
      {cd && cd.connected === false && <div className="mw-warn">Daycare GoHighLevel isn't connected — add its key to daycare.env.</div>}
      {!MBDAuth(conv) && MBDFailed(conv) && <div className="mw-warn">Couldn't load messages — {String(conv.error)}</div>}
      {cd && cd.inHours === false && <div className="mbd-note">Outside the 8am–9pm ET texting window — you can read and draft; sending unlocks at 8am.</div>}

      {pending.length > 0 && <React.Fragment>
        <MBDSection title="Solomon drafted" right={<MBDBadge tone="gold">{pending.length}</MBDBadge>} />
        {pending.map((d) => <MBDDraftCard key={d.contactId + ":" + (d.inboundAt || "")} draft={d} onOpen={setOpen} onDone={refresh} />)}
      </React.Fragment>}
      {repErr && <div className="mw-warn">Reply drafts paused — {String(repErr).slice(0, 160)}</div>}

      <div className="m-seg">
        <window.MChip active={seg === "needs"} onClick={() => setSeg("needs")}>Needs reply{cd ? " · " + needs.length : ""}</window.MChip>
        <window.MChip active={seg === "all"} onClick={() => setSeg("all")}>All{cd ? " · " + rows.length : ""}</window.MChip>
        <button className="m-chip" onClick={refresh} aria-label="Refresh"><window.MIcons.Refresh size={16} /></button>
      </div>
      <input className="m-input mbd-input" placeholder="Search name, phone or message" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="m-card mbd-list">
        {conv.loading && !conv.data ? <window.MSpin /> : !list.length
          ? <window.MEmpty title={seg === "needs" ? "Everyone's answered" : "No conversations"} sub={seg === "needs" ? "Threads where a parent wrote last show here." : ""} />
          : list.map((c) => <button key={c.contactId} className="mbd-row mbd-tap" onClick={() => setOpen(c.contactId)}>
            <span className="mbd-avatar">{MBDInitials(c.name)}</span>
            <div className="mbd-row-main"><strong>{MBDName(c.name, c.phone || "Unknown")}</strong>
              <small>{c.direction === "outbound" ? "You: " : ""}{c.lastMessage || "(" + (c.type || "message") + ")"}</small></div>
            <div className="mbd-row-side"><small>{window.timeAgoM(c.lastAt)}</small>
              {c.draft ? <MBDBadge tone="gold">Draft</MBDBadge> : c.unread > 0 ? <MBDBadge tone="red">{c.unread}</MBDBadge> : null}</div>
          </button>)}
      </div>
    </div>
    {open && <MBDThread contactId={open} onClose={() => { setOpen(null); refresh(); }} onSent={refresh} />}
  </React.Fragment>;
}

// ---------------------------------------------------------------- Families (enrollment)
// Needs-a-human rows joined with the lead record (name, stage) and — when the
// Contact-Form inbox is loaded — the family's phone. Lead Desk itself carries no phone.
function MBDNeeds(leadsData, families) {
  const d = leadsData || {};
  const byId = {};
  (Array.isArray(d.leads) ? d.leads : []).forEach((l) => { byId[l.contactId] = l; });
  const phones = {};
  (families || []).forEach((f) => { if (f.contact_id && f.phone) phones[f.contact_id] = f.phone; });
  return (Array.isArray(d.needsHuman) ? d.needsHuman : []).map((n) => {
    const lead = byId[n.contactId] || {};
    return Object.assign({}, n, { name: MBDName(lead.parentName, lead.childName ? lead.childName + "'s family" : "New family"), stage: lead.stage, phone: phones[n.contactId] || "" });
  });
}

function MBDNeedRow(props) {
  const r = props.row;
  const stage = MBD_STAGES.find(([k]) => k === r.stage);
  const sub = [r.center, stage && stage[1], r.why,
    r.ageSec != null ? MBDAgo(Date.now() - r.ageSec * 1000).replace(" ago", " waiting") : ""].filter(Boolean).join(" · ");
  // Tap the family → their GHL thread (read, call, text); ••• → local stage mark.
  return <div className="mbd-row">
    <button className="mbd-row-open" onClick={() => r.contactId && props.onText(r.contactId)}>
      <span className="mbd-avatar">{MBDInitials(r.name)}</span>
      <div className="mbd-row-main"><strong>{r.name}</strong><small className="wrap">{sub}</small></div>
    </button>
    {r.phone ? <a className="mbd-call" href={"tel:" + r.phone} aria-label="Call"><window.MIcons.Phone size={17} /></a> : null}
    <button className="mbd-call" onClick={() => props.onMark(r)} aria-label="Mark lead stage">•••</button>
  </div>;
}

function MBDStageSheet(props) {
  const r = props.row;
  const [pick, setPick] = useStateBD(MBD_STAGES.some(([k]) => k === r.stage) ? r.stage : "TOUR_BOOKED");
  const [busy, setBusy] = useStateBD(false);
  const [err, setErr] = useStateBD("");
  async function save(stage) {
    setBusy(true); setErr("");
    try { await window.apiPostM("/api/daycare/leads/stage", { contact_id: r.contactId, stage }); props.onDone(); }
    catch (e) { setErr("Couldn't save the mark — " + ((e && e.message) || "retry") + "."); setBusy(false); }
  }
  return <MBDSheet title="Mark lead stage" onClose={props.onClose}>
    <div className="m-card"><b>{r.name}</b><div className="m-fade" style={{ marginTop: 4 }}>Local mark only — it doesn't change GoHighLevel or message the family.</div></div>
    {MBD_STAGES.map(([k, label]) => <button key={k} className={"mw-stage-choice" + (pick === k ? " active" : "")} onClick={() => setPick(k)}>{label}{pick === k ? " ✓" : ""}</button>)}
    {err && <div className="mw-warn">{err}</div>}
    <window.MBtn disabled={busy} onClick={() => save(pick)}>{busy ? "Saving…" : "Save mark"}</window.MBtn>
    {MBD_STAGES.some(([k]) => k === r.stage) && <window.MBtn kind="ghost" disabled={busy} onClick={() => save("")}>Clear mark</window.MBtn>}
  </MBDSheet>;
}

// Any provision response carries the one-time PIN exactly once — show it or lose it.
function MBDCredsSheet(props) {
  const p = props.provision || {};
  const [copied, setCopied] = useStateBD(false);
  const text = "Login ID: " + (p.login_id || "") + (p.pin ? "\nPIN: " + p.pin : "");
  return <MBDSheet title={p.existing ? "Account linked" : "Save these now"} onClose={props.onClose}>
    <div className="m-card mbd-creds">
      {props.who && <div className="m-fade">{props.who}</div>}
      <small>Login ID</small><b>{p.login_id || "—"}</b>
      {!p.existing && p.pin && <React.Fragment><small>One-time PIN</small><b>{p.pin}</b></React.Fragment>}
      <div className="m-fade">{p.existing ? "An existing account was connected — their current PIN still works." : "The PIN is shown once and never stored. Hand it over in person — not in notes."}</div>
    </div>
    {p.login_id && <window.MBtn kind="ghost" onClick={async () => setCopied(await MBDCopy(text))}>{copied ? "Copied ✓" : "Copy login"}</window.MBtn>}
    <window.MBtn onClick={props.onClose}>I saved them</window.MBtn>
  </MBDSheet>;
}

function MBDFamilies() {
  const leads = window.useApiM("/api/daycare/leads", { interval: 60000 });
  // Heavy GHL read (paged contacts + intake notes) — load on this tab only, no poll.
  const inbox = window.useApiM("/api/daycare/ghl/pending-families");
  const [seg, setSeg] = useStateBD("needs");
  const [markRow, setMarkRow] = useStateBD(null);
  const [thread, setThread] = useStateBD(null);
  const [busyId, setBusyId] = useStateBD("");
  const [notice, setNotice] = useStateBD("");
  const [creds, setCreds] = useStateBD(null);
  const [showOld, setShowOld] = useStateBD(false);
  const auth = MBDAuth(leads) || MBDAuth(inbox);
  const ld = leads.data && leads.data.ok ? leads.data : null;
  const ran = !!(ld && ld.lastRunAt);
  const kpis = (ld && ld.kpis) || {};
  const pipe = kpis.pipeline || {};
  const pd = inbox.data && inbox.data.ok ? inbox.data : null;
  const families = (pd && Array.isArray(pd.families)) ? pd.families : [];
  const needs = ran ? MBDNeeds(ld, families) : [];
  const fresh = needs.filter((r) => r.ageSec == null || r.ageSec * 1000 < MBD_STALE_MS);
  const old = needs.filter((r) => r.ageSec != null && r.ageSec * 1000 >= MBD_STALE_MS);
  const activeLoc = (pd && pd.active_location_id) || "";
  const here = families.filter((f) => !f.location_id || String(f.location_id) === String(activeLoc));
  const elsewhere = families.filter((f) => !f.dismissed && !f.in_roster && f.location_id && String(f.location_id) !== String(activeLoc)).length;
  const waiting = here.filter((f) => !f.in_roster && !f.dismissed);
  const toEnroll = waiting.filter((f) => f.enrolled);
  const inquiries = waiting.filter((f) => !f.enrolled);

  async function enroll(f) {
    const child = f.child_name || "this child";
    const who = child + (f.parent_name ? " (parent " + f.parent_name + ")" : "") + (f.location_name ? " at " + f.location_name : "");
    const what = f.child_id ? who + " is already on the roster. Link/create the parent's app login and clear this card?" : "Enroll " + who + "?";
    if (!window.confirm(what + "\n\nThis writes to the daycare roster, creates the parent's app login if an email is on file, and updates their GoHighLevel contact. No text is sent.")) return;
    setBusyId(f.contact_id); setNotice("");
    try {
      const r = await window.apiPostM("/api/daycare/ghl/enroll", { family: f });
      if (r && r.provision) setCreds({ provision: r.provision, who: f.parent_name || child });
      setNotice(child + " enrolled." + (r && r.ghlSync && r.ghlSync.ok === false ? " GHL sync: " + (r.ghlSync.detail || "failed") + "." : ""));
      inbox.refresh();
    } catch (e) { setNotice("Enroll failed — " + ((e && e.message) || "retry") + ". Nothing was sent to the family."); }
    setBusyId("");
  }

  const famRow = (f, action) => <div className="mbd-row" key={f.contact_id}>
    <span className="mbd-avatar">{MBDInitials(f.child_name || f.parent_name)}</span>
    <div className="mbd-row-main"><strong>{MBDName(f.child_name, "Student")}{f.parent_name ? " · " + f.parent_name : ""}</strong>
      <small>{[f.location_name || f.location_tag, f.enrolled ? (f.child_id ? "On roster" : "Enrolled family") : "Inquiry"].filter(Boolean).join(" · ")}</small></div>
    {f.phone && <a className="mbd-call" href={"tel:" + f.phone} aria-label="Call"><window.MIcons.Phone size={17} /></a>}
    {action}
  </div>;

  return <React.Fragment>
    <MBDHead title="Families" sub="New enrollment · Solomon · Leads" />
    <div className="m-content mbd-page">
      {auth && <MBDAuthLine />}
      <div className="mbd-pipe">
        {[["New · 7d", kpis.newLeads7d ? kpis.newLeads7d.total : null], ["Tours", pipe.TOUR_BOOKED], ["Applied", pipe.APPLICATION], ["Enrolled", pipe.ENROLLED]].map(([l, v]) =>
          <div key={l}><b>{ran && v != null ? v : "—"}</b><small>{l}</small></div>)}
      </div>
      <div className="m-seg">
        <window.MChip active={seg === "needs"} onClick={() => setSeg("needs")}>Call back{ran ? " · " + fresh.length : ""}</window.MChip>
        <window.MChip active={seg === "inbox"} onClick={() => setSeg("inbox")}>Contact form{pd ? " · " + waiting.length : ""}</window.MChip>
      </div>
      {notice && <div className="mbd-note">{notice}</div>}
      {seg === "needs" ? <div className="m-card mbd-list">
        {!auth && MBDFailed(leads) && <div className="mw-warn">Lead sweep unavailable — retry.</div>}
        {!auth && ld && ld.error && <div className="mw-warn">Solomon · Leads: {ld.error}</div>}
        {leads.loading && !leads.data ? <window.MSpin /> : !ld ? null : !ran ? <div className="m-fade">Solomon's lead sweep hasn't run yet.</div>
          : !fresh.length && !old.length ? <window.MEmpty title="No families waiting" sub="New leads that need a person show here." />
          : fresh.map((r) => <MBDNeedRow key={r.id} row={r} onMark={setMarkRow} onText={setThread} />)}
        {old.length > 0 && <button className="mbd-row mbd-tap" onClick={() => setShowOld(!showOld)}>
          <div className="mbd-row-main"><strong>{old.length} older than 30 days</strong><small>Re-engage or mark Lost to clear</small></div>
          <span className="mbd-chev">{showOld ? "⌃" : "›"}</span></button>}
        {showOld && old.map((r) => <MBDNeedRow key={r.id} row={r} onMark={setMarkRow} onText={setThread} />)}
        {ran && <div className="m-fade" style={{ padding: "10px 2px 0" }}>Median human response (30d) · {MBDDur(kpis.medianHumanResponseSec)}</div>}
      </div> : <div className="m-card mbd-list">
        {!auth && MBDFailed(inbox) && <div className="mw-warn">Contact-Form inbox unavailable — retry.</div>}
        {pd && pd.connected === false && <div className="mw-warn">Daycare GoHighLevel isn't connected — the inbox can't load.</div>}
        {inbox.loading && !inbox.data ? <window.MSpin /> : pd && <React.Fragment>
          {pd.connected !== false && !toEnroll.length && !inquiries.length && <window.MEmpty title="All caught up" sub="New form submissions for this center show here." />}
          {toEnroll.map((f) => famRow(f, <button className="mbd-pill" disabled={busyId === f.contact_id} onClick={() => enroll(f)}>
            {busyId === f.contact_id ? "…" : f.child_id ? "Finish" : "Enroll"}</button>))}
          {inquiries.length > 0 && <div className="mbd-sub">New inquiries — not enrolled yet · no login</div>}
          {inquiries.map((f) => famRow(f, null))}
          {elsewhere > 0 && <div className="m-fade" style={{ padding: "10px 2px 0" }}>{elsewhere} more waiting at other centers — switch center on Home.</div>}
        </React.Fragment>}
        <div className="mbd-actions"><window.MBtn kind="ghost" onClick={inbox.refresh}>Refresh inbox</window.MBtn></div>
      </div>}
    </div>
    {markRow && <MBDStageSheet row={markRow} onClose={() => setMarkRow(null)} onDone={() => { setMarkRow(null); leads.refresh(); }} />}
    {thread && <MBDThread contactId={thread} onClose={() => setThread(null)} />}
    {creds && <MBDCredsSheet provision={creds.provision} who={creds.who} onClose={() => setCreds(null)} />}
  </React.Fragment>;
}

// ---------------------------------------------------------------- Logins
function MBDField(props) {
  return <label className="mbd-field"><span>{props.label}</span>
    {props.options ? <select className="m-input" value={props.value} onChange={(e) => props.onChange(e.target.value)}>
      {props.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      : <input className="m-input" type={props.type || "text"} value={props.value} placeholder={props.placeholder || ""}
        inputMode={props.inputMode} autoCapitalize={props.type === "email" ? "none" : "words"}
        onChange={(e) => props.onChange(e.target.value)} />}
  </label>;
}

// kind: "family" (new child + parent login) | "staff" | "guardian" (existing child, add parent login)
function MBDCreateSheet(props) {
  const rooms = props.rooms || [];
  const c = props.child || null;
  const [kind, setKind] = useStateBD(c ? "guardian" : "family");
  const [f, setF] = useStateBD({ first: "", last: "", dob: "", room: "", gFirst: "", gLast: "", gEmail: "", gPhone: "",
    sFirst: "", sLast: "", role: "staff", job: "", rate: "", sRooms: [] });
  const [busy, setBusy] = useStateBD(false);
  const [err, setErr] = useStateBD("");
  const set = (k) => (v) => setF(Object.assign({}, f, { [k]: v }));
  const roomOpts = [["", "No classroom yet"]].concat(rooms.map((r) => [r.id, r.name + " · " + r.age_group]));

  async function submit() {
    setErr("");
    let path, body, who, what;
    if (kind === "staff") {
      if (!f.sFirst.trim() || !f.sLast.trim() || !f.job.trim()) return setErr("First name, last name and job title are required.");
      path = "/api/daycare/staff/save"; who = f.sFirst + " " + f.sLast;
      body = { first_name: f.sFirst.trim(), last_name: f.sLast.trim(), role: f.role, job_title: f.job.trim(),
        hourly_rate: f.rate.trim() || null, classroom_ids: f.sRooms };
      what = "Create a " + f.role + " login for " + who + "?";
    } else {
      if (!f.gFirst.trim() || !f.gLast.trim() || !/.+@.+\..+/.test(f.gEmail.trim())) return setErr("Parent first name, last name and a valid email are required.");
      const guardian = { guardian_first_name: f.gFirst.trim(), guardian_last_name: f.gLast.trim(),
        guardian_email: f.gEmail.trim(), guardian_phone: f.gPhone.trim() || null };
      who = f.gFirst + " " + f.gLast;
      path = "/api/daycare/child/save";
      if (kind === "guardian") {
        // save_child PATCHes every field — resend the child's current values unchanged.
        body = Object.assign({ id: c.id, first_name: c.first_name, last_name: c.last_name, preferred_name: c.preferred_name,
          birth_date: c.birth_date, classroom_id: c.classroom_id, allergies: c.allergies, medical_notes: c.medical_notes,
          pickup_notes: c.pickup_notes, enrollment_date: c.enrollment_date, active: c.active !== false }, guardian);
        what = "Create a parent login for " + who + " and link it to " + c.first_name + "?";
      } else {
        if (!f.first.trim() || !f.last.trim() || !f.dob) return setErr("Child first name, last name and birth date are required.");
        body = Object.assign({ first_name: f.first.trim(), last_name: f.last.trim(), birth_date: f.dob, classroom_id: f.room || null }, guardian);
        what = "Enroll " + f.first + " " + f.last + " and create a parent login for " + who + "?";
      }
    }
    if (!window.confirm(what + "\n\nThis writes to the daycare database" + (kind === "staff" ? "" : " and adds the family to GoHighLevel") + ". No text or email is sent.")) return;
    setBusy(true);
    try {
      const r = await window.apiPostM(path, body);
      props.onCreated(r && r.provision ? { provision: r.provision, who } : null,
        r && r.ghlSync && r.ghlSync.ok === false ? "Saved. GHL sync: " + (r.ghlSync.detail || "failed") : "Saved.");
    } catch (e) { setErr((e && e.message) || "Couldn't save — retry."); setBusy(false); }
  }

  return <MBDSheet title={kind === "guardian" ? "Add parent login" : "Quick create"} onClose={props.onClose}
    foot={<window.MBtn style={{ width: "100%" }} disabled={busy} onClick={submit}>{busy ? "Creating…" : "Create login"}</window.MBtn>}>
    {kind !== "guardian" && <div className="m-seg">
      <window.MChip active={kind === "family"} onClick={() => setKind("family")}>New family</window.MChip>
      <window.MChip active={kind === "staff"} onClick={() => setKind("staff")}>Staff member</window.MChip>
    </div>}
    {kind === "guardian" && <div className="mbd-note">For {c.first_name} {c.last_name} — no parent login yet.</div>}
    {kind === "family" && <div className="m-card mbd-form"><div className="mbd-sub">Child</div>
      <div className="mbd-two"><MBDField label="First name" value={f.first} onChange={set("first")} /><MBDField label="Last name" value={f.last} onChange={set("last")} /></div>
      <MBDField label="Birth date" type="date" value={f.dob} onChange={set("dob")} />
      <MBDField label="Classroom" value={f.room} onChange={set("room")} options={roomOpts} />
    </div>}
    {kind !== "staff" && <div className="m-card mbd-form"><div className="mbd-sub">Parent / guardian</div>
      <div className="mbd-two"><MBDField label="First name" value={f.gFirst} onChange={set("gFirst")} /><MBDField label="Last name" value={f.gLast} onChange={set("gLast")} /></div>
      <MBDField label="Email (their login)" type="email" inputMode="email" value={f.gEmail} onChange={set("gEmail")} />
      <MBDField label="Phone (optional)" type="tel" inputMode="tel" value={f.gPhone} onChange={set("gPhone")} />
    </div>}
    {kind === "staff" && <div className="m-card mbd-form">
      <div className="mbd-two"><MBDField label="First name" value={f.sFirst} onChange={set("sFirst")} /><MBDField label="Last name" value={f.sLast} onChange={set("sLast")} /></div>
      <MBDField label="Role" value={f.role} onChange={set("role")} options={[["staff", "Staff"], ["manager", "Manager"]]} />
      <MBDField label="Job title" value={f.job} onChange={set("job")} placeholder="Lead Teacher" />
      <MBDField label="Hourly rate (optional)" type="number" inputMode="decimal" value={f.rate} onChange={set("rate")} />
      {rooms.length > 0 && <div className="mbd-sub">Classrooms</div>}
      <div className="m-seg" style={{ flexWrap: "wrap" }}>{rooms.map((r) => <window.MChip key={r.id} active={f.sRooms.includes(r.id)}
        onClick={() => set("sRooms")(f.sRooms.includes(r.id) ? f.sRooms.filter((x) => x !== r.id) : f.sRooms.concat(r.id))}>{r.name}</window.MChip>)}</div>
    </div>}
    {err && <div className="mw-warn">{err}</div>}
    <div className="m-fade">A Login ID + one-time PIN appear once after saving — hand them over in person.</div>
  </MBDSheet>;
}

function MBDLogins() {
  const kids = window.useApiM("/api/daycare/children");
  const staff = window.useApiM("/api/daycare/staff");
  const rooms = window.useApiM("/api/daycare/classrooms");
  const [seg, setSeg] = useStateBD("parents");
  const [q, setQ] = useStateBD("");
  const [busy, setBusy] = useStateBD("");
  const [err, setErr] = useStateBD("");
  const [creds, setCreds] = useStateBD(null);
  const [create, setCreate] = useStateBD(null); // {child?} | {}
  const [copied, setCopied] = useStateBD("");
  const [notice, setNotice] = useStateBD("");
  const auth = MBDAuth(kids) || MBDAuth(staff);
  const childList = (kids.data && kids.data.ok && kids.data.children) || [];
  const staffList = (staff.data && staff.data.ok && staff.data.staff) || [];
  const roomList = ((rooms.data && rooms.data.ok && rooms.data.classrooms) || []).filter((r) => r.active !== false);
  const ql = q.trim().toLowerCase();
  const hit = (...xs) => !ql || xs.join(" ").toLowerCase().includes(ql);

  // One card per guardian, their children listed; children with no guardian surface separately.
  const byG = {};
  const orphans = [];
  childList.filter((c) => c.active !== false).forEach((c) => {
    const g = c.guardian || null;
    if (!c.guardian_profile_id || !g) { orphans.push(c); return; }
    (byG[g.id] = byG[g.id] || { g, kids: [] }).kids.push(c);
  });
  const parents = Object.values(byG).filter((x) => hit(x.g.display_name, x.g.first_name, x.g.last_name, x.g.login_id,
    x.kids.map((k) => k.first_name + " " + k.last_name).join(" "))).sort((a, b) => String(a.g.last_name).localeCompare(String(b.g.last_name)));
  const staffRows = staffList.map((s) => ({ s, p: s.profiles || {} })).filter(({ p, s }) => p.active !== false
    && hit(p.display_name, p.first_name, p.last_name, p.login_id, s.job_title));

  async function resetPin(profileId, who) {
    if (!window.confirm("Reset " + who + "'s PIN?\n\nTheir current PIN stops working immediately. The new one shows once — hand it over in person.")) return;
    setBusy(profileId); setErr("");
    try { const r = await window.apiPostM("/api/daycare/guardian/reset-pin", { profile_id: profileId }); setCreds({ provision: r.provision, who }); }
    catch (e) { setErr("PIN reset failed — " + ((e && e.message) || "retry")); }
    setBusy("");
  }
  async function copy(id) { if (await MBDCopy(id)) { setCopied(id); setTimeout(() => setCopied(""), 1500); } }
  const idChip = (id) => id ? <button className="mbd-idchip" onClick={() => copy(id)}>{copied === id ? "Copied ✓" : id}</button> : <MBDBadge tone="red">No login ID</MBDBadge>;

  return <React.Fragment>
    <MBDHead title="Logins" sub="Parent + staff app access" />
    <div className="m-content mbd-page">
      {auth && <MBDAuthLine />}
      <button className="mbd-create" onClick={() => setCreate({})}>
        <span className="mbd-row-ico"><window.MIcons.Key size={18} /></span>
        <div className="mbd-row-main"><strong>Quick create a login</strong><small>New family (child + parent) or staff member</small></div>
        <span className="mbd-chev">＋</span>
      </button>
      {err && <div className="mw-warn">{err}</div>}
      {notice && <div className="mbd-note">{notice}</div>}
      <div className="m-seg">
        <window.MChip active={seg === "parents"} onClick={() => setSeg("parents")}>Parents{kids.data ? " · " + Object.keys(byG).length : ""}</window.MChip>
        <window.MChip active={seg === "staff"} onClick={() => setSeg("staff")}>Staff{staff.data ? " · " + staffRows.length : ""}</window.MChip>
      </div>
      <input className="m-input mbd-input" placeholder="Search name or login ID" value={q} onChange={(e) => setQ(e.target.value)} />

      {seg === "parents" ? <React.Fragment>
        {orphans.length > 0 && <div className="m-card mbd-list">
          <div className="mbd-sub">No parent login yet · {orphans.length}</div>
          {orphans.map((c) => <div className="mbd-row" key={c.id}>
            <span className="mbd-avatar">{MBDInitials(c.first_name + " " + c.last_name)}</span>
            <div className="mbd-row-main"><strong>{c.first_name} {c.last_name}</strong><small>{(c.classrooms && c.classrooms.name) || "No classroom"}</small></div>
            <button className="mbd-pill" onClick={() => setCreate({ child: c })}>Add login</button>
          </div>)}
        </div>}
        <div className="m-card mbd-list">
          {kids.loading && !kids.data ? <window.MSpin /> : MBDFailed(kids) && !auth ? <div className="mw-warn">Couldn't load families — {String(kids.error)}</div>
            : !parents.length ? <window.MEmpty title={ql ? "No match" : "No parent logins at this center"} />
            : parents.map(({ g, kids: ks }) => <div className="mbd-row mbd-login" key={g.id}>
              <span className="mbd-avatar">{MBDInitials(g.display_name || g.first_name + " " + g.last_name)}</span>
              <div className="mbd-row-main"><strong>{g.display_name || [g.first_name, g.last_name].join(" ")}</strong>
                <small>{ks.map((k) => k.preferred_name || k.first_name).join(", ")}{g.auth_email ? " · " + g.auth_email : ""}</small>
                <div className="mbd-login-line">{idChip(g.login_id)}</div></div>
              <button className="mbd-pill ghost" disabled={busy === g.id} onClick={() => resetPin(g.id, g.display_name || g.first_name)}>{busy === g.id ? "…" : "Reset PIN"}</button>
            </div>)}
        </div>
      </React.Fragment> : <div className="m-card mbd-list">
        {staff.loading && !staff.data ? <window.MSpin /> : MBDFailed(staff) && !auth ? <div className="mw-warn">Couldn't load staff — {String(staff.error)}</div>
          : !staffRows.length ? <window.MEmpty title={ql ? "No match" : "No staff at this center"} />
          : staffRows.map(({ s, p }) => <div className="mbd-row mbd-login" key={s.id}>
            <span className="mbd-avatar">{MBDInitials(p.display_name || p.first_name + " " + p.last_name)}</span>
            <div className="mbd-row-main"><strong>{p.display_name || [p.first_name, p.last_name].join(" ")}</strong>
              <small>{[s.job_title, p.role].filter(Boolean).join(" · ")}</small>
              <div className="mbd-login-line">{idChip(p.login_id)}</div></div>
            {p.role !== "admin" && <button className="mbd-pill ghost" disabled={busy === s.profile_id} onClick={() => resetPin(s.profile_id, p.display_name || p.first_name)}>{busy === s.profile_id ? "…" : "Reset PIN"}</button>}
          </div>)}
      </div>}
      <div className="m-fade" style={{ textAlign: "center" }}>Parents + staff sign in to the A Touch of Blessings app with their Login ID + PIN.</div>
    </div>
    {create && <MBDCreateSheet rooms={roomList} child={create.child} onClose={() => setCreate(null)}
      onCreated={(c, msg) => { setCreate(null); setErr(""); kids.refresh(); staff.refresh(); setNotice(msg); if (c) setCreds(c); }} />}
    {creds && <MBDCredsSheet provision={creds.provision} who={creds.who} onClose={() => setCreds(null)} />}
  </React.Fragment>;
}

Object.assign(window, { MBDHome, MBDMessages, MBDFamilies, MBDLogins });
window.M_BIZ = window.M_BIZ || {};
window.M_BIZ.daycare = {
  id: "daycare", name: "Daycare", tagline: "A Touch of Blessings · management", accent: "#5b2c8e", ico: "Heart",
  tabs: [
    { key: "home", label: "Home", ico: "Pulse" },
    { key: "messages", label: "Messages", ico: "Chat" },
    { key: "families", label: "Families", ico: "Heart" },
    { key: "logins", label: "Logins", ico: "Key" },
  ],
  pages: { home: MBDHome, messages: MBDMessages, families: MBDFamilies, logins: MBDLogins },
};
