// idea_wheel.jsx — Business Idea Wheel (Agency workspace · Personal lens).
// Spin → one buildable portfolio concept per day. The server (idea_wheel.py) generates the
// idea AND picks it from the wheel segments it returns, so the landing segment always equals
// the result. This file is presentation only: the wheel animation never decides anything.
//
// STATIC-REACT RULES (no build step):
//   - hooks aliased (…Iw) so top-level consts never collide with other files
//   - every top-level name prefixed Iw / IW_
//   - never use computed-member JSX tags — resolve the component to a var first
//   - shipped on window at the bottom
const { useState: useStateIw, useEffect: useEffectIw, useRef: useRefIw } = React;

const IW_DURATION = 3200; // ms — inside the spec's 2–4 s window
const IW_R = 212;         // segment radius inside the 500×500 viewBox (rim covers 214–248)
const IW_STATUS_LABEL = { new: "New", saved: "Saved", building: "Building", ready: "Ready", posted: "Posted", archived: "Archived" };
const IW_STATUS_SET = ["saved", "building", "ready", "posted", "archived"];
const IW_METRICS = [["inquiries", "Inquiries"], ["demosSent", "Demos sent"], ["bookedCalls", "Booked calls"], ["signedClients", "Signed clients"]];
const IW_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function iwReduceMotion() {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return false; }
}
function iwHash(s) {
  let h = 0;
  for (let i = 0; i < String(s).length; i++) h = (h * 31 + String(s).charCodeAt(i)) >>> 0;
  return h;
}
function iwPoint(deg, r) {
  const a = (deg * Math.PI) / 180;
  return [250 + r * Math.sin(a), 250 - r * Math.cos(a)];
}
function iwDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString([], { month: "short", day: "numeric" });
}
async function iwCopy(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch (e) { /* fall through to the textarea path */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch (e) { return false; }
}

// ---------------------------------------------------------------------------- wheel
function IwWheel({ segments, rotation, instant, landed, spinning, onSpin, busy }) {
  const n = segments.length || 1;
  const seg = 360 / n;
  const label = "Idea wheel with " + n + " industries: " + segments.map((s) => s.label).join(", ");
  return (
    <div className="iw-wheel-wrap">
      <svg className={"iw-wheel" + (instant ? " is-instant" : "")} viewBox="0 0 500 500" role="img" aria-label={label}
        style={{ transform: "rotate(" + rotation + "deg)", "--iw-duration": IW_DURATION + "ms" }}
        data-rotation={rotation}>
        <circle cx="250" cy="250" r="248" fill="#0b1522" />
        {segments.map((s, i) => {
          const a0 = i * seg, a1 = (i + 1) * seg, mid = a0 + seg / 2;
          const [x0, y0] = iwPoint(a0, IW_R);
          const [x1, y1] = iwPoint(a1, IW_R);
          const d = "M250 250 L" + x0.toFixed(2) + " " + y0.toFixed(2) + " A" + IW_R + " " + IW_R + " 0 " + (seg > 180 ? 1 : 0) + " 1 " + x1.toFixed(2) + " " + y1.toFixed(2) + " Z";
          const txt = s.label.length > 16 ? s.label.slice(0, 15) + "…" : s.label;
          const long = txt.length > 12;
          return (
            <g key={i + ":" + s.nicheId} data-niche={s.nicheId}>
              <path d={d} className={"iw-seg" + (landed === i ? " is-landed" : "")}
                fill={s.color} fillOpacity={i % 2 ? 0.26 : 0.36} />
              <g transform={"rotate(" + mid + " 250 250)"}>
                <use href={"assets/ideawheel/sectors.svg#" + s.icon} className="iw-seg-icon" x="240" y="44" width="20" height="20" />
                <text className="iw-seg-label" x="250" y="74" textAnchor="end" dominantBaseline="middle"
                  transform="rotate(-90 250 74)" {...(long ? { textLength: 82, lengthAdjust: "spacingAndGlyphs" } : {})}>{txt}</text>
              </g>
            </g>
          );
        })}
        <circle cx="250" cy="250" r="88" fill="#0a1320" stroke="rgba(255,255,255,.06)" />
      </svg>
      <img className="iw-rim" src="assets/ideawheel/rim.svg" alt="" aria-hidden="true" />
      <img className={"iw-pointer" + (spinning && !instant ? " is-ticking" : "")} src="assets/ideawheel/pointer.svg" alt="" aria-hidden="true" />
      <button className={"iw-hub" + (spinning ? " is-spinning" : "")} onClick={onSpin} aria-disabled={busy}
        aria-label={spinning ? "Spinning" : "Spin for an Idea"}>
        <span>{spinning ? "Spinning…" : "Spin for an Idea"}</span>
        <small>{spinning ? "landing soon" : "2–4 s spin"}</small>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------- result
function IwList({ items }) {
  return <ul>{(items || []).map((x, i) => <li key={i}>{x}</li>)}</ul>;
}

function IwResult({ idea, kitReady, busy, onAction, exhausted, onRelax, fromHistory }) {
  if (exhausted) {
    return (
      <section className="iw-result" aria-label="Spin result">
        <div className="iw-result-empty">
          <span className="iw-ico iw-ico--bulb iw-ico--hero" aria-hidden="true" />
          <b style={{ color: "var(--text)" }}>Pool exhausted</b>
          <div>{exhausted.message}</div>
          <div className="iw-meta" style={{ justifyContent: "center" }}>
            {(exhausted.relax || []).map((r) => (
              <button key={r.filter} className="btn" onClick={() => onRelax(r.filter)}>
                {r.label} <span className="faint">({r.pool})</span>
              </button>
            ))}
          </div>
        </div>
      </section>
    );
  }
  if (!idea) {
    return (
      <section className="iw-result" aria-label="Spin result">
        <div className="iw-result-empty">
          <span className="iw-ico iw-ico--bulb iw-ico--hero" aria-hidden="true" />
          <b style={{ color: "var(--text)" }}>Spin for today's concept</b>
          <div>One click gives a niche, a problem worth solving, a deliverable, a visual direction and a content plan.</div>
        </div>
      </section>
    );
  }
  const d = idea.design || {};
  const busyAny = !!busy; // aria-disabled while busy keeps keyboard focus on the button
  const act = (k) => () => onAction(k);
  return (
    <section className="iw-result" aria-label="Spin result" aria-busy={busyAny}>
      <div>
        <div className="iw-kicker">{idea.industry} · {idea.subindustry}{fromHistory ? " · from history" : ""}</div>
        <h2 className="iw-title" style={{ margin: "6px 0 8px" }}>{idea.title}</h2>
        <p className="iw-summary" style={{ margin: 0 }}>{idea.conceptSummary}</p>
      </div>
      <div className="iw-meta">
        <span className={"iw-status iw-status--" + idea.status}>{IW_STATUS_LABEL[idea.status]}</span>
        <span className="iw-chip iw-chip--accent">{idea.deliverableLabel}</span>
        <span className="iw-chip">{idea.complexity} · ~{idea.estimatedDemoHours.min}–{idea.estimatedDemoHours.max} h (rough)</span>
        <span className="iw-chip">{idea.difficulty}</span>
        <span className="iw-chip">{(idea.market || "").toUpperCase()}</span>
        <span className="iw-chip">{d.aesthetic}</span>
        {(idea.tags || []).map((t) => <span key={t} className="iw-chip">#{t}</span>)}
      </div>
      <dl className="iw-fields">
        <div className="iw-field"><dt>Business type</dt><dd>{idea.subindustry} <span className="faint">(NAICS {idea.naics})</span></dd></div>
        <div className="iw-field"><dt>Target audience</dt><dd>{idea.targetCustomer}</dd></div>
        <div className="iw-field"><dt>Pain point</dt><dd>{idea.problem}</dd></div>
        <div className="iw-field"><dt>Recommended build</dt><dd>{idea.deliverableLabel} <span className="faint">({idea.deliverable})</span></dd></div>
        <div className="iw-field"><dt>Visual style</dt><dd>
          <div className="iw-swatches" style={{ marginBottom: 6 }}>
            {(d.palette || []).map((h) => <span key={h} className="iw-swatch" style={{ background: h }} title={h} />)}
          </div>
          {d.aesthetic}: {d.typography}. {d.layout}.
        </dd></div>
        <div className="iw-field"><dt>Content hook</dt><dd>“{idea.content.hook}”</dd></div>
        <div className="iw-field"><dt>Feature set</dt><dd><IwList items={idea.features} /></dd></div>
        <div className="iw-field"><dt>Pages / screens</dt><dd><IwList items={idea.pagesOrScreens} /></dd></div>
        <div className="iw-field"><dt>MVP scope</dt><dd><IwList items={idea.demoScope} /></dd></div>
        <div className="iw-field"><dt>Difficulty & effort</dt><dd>{idea.difficulty} · rough demo effort {idea.estimatedDemoHours.min}–{idea.estimatedDemoHours.max} h ({idea.complexity})</dd></div>
        <div className="iw-field"><dt>Pitch angle</dt><dd>{idea.pitchAngle}</dd></div>
        <div className="iw-field"><dt>Guardrails</dt><dd><IwList items={idea.guardrails} /></dd></div>
      </dl>
      <div className="iw-disclosure" role="note">{idea.disclosure}</div>
      <div className="iw-actions">
        <button className="btn btn-primary" onClick={act("save")} aria-disabled={busyAny} disabled={idea.status !== "new"}>
          {idea.status === "new" ? "Save Idea" : "Saved"}
        </button>
        <button className="btn" onClick={act("spin")} aria-disabled={busyAny}>Spin Again</button>
        <button className="btn" onClick={act("restyle")} aria-disabled={busyAny}>Regenerate Style</button>
        <button className="btn" onClick={act("kit")} aria-disabled={busyAny}>{kitReady ? "Regenerate Content Kit" : "Generate Content Kit"}</button>
        <button className="btn" onClick={act("building")} aria-disabled={busyAny} disabled={idea.status === "building"}>Mark Building</button>
        <button className="btn" onClick={act("posted")} aria-disabled={busyAny} disabled={idea.status === "posted"}>Mark Posted</button>
        <button className="btn" onClick={act("brief")} aria-disabled={busyAny}>Copy Build Brief</button>
        <button className="btn" onClick={act("today")} aria-disabled={busyAny}>Plan for Today</button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------- side panels
function IwFilters({ options, filters, onChange }) {
  if (!options) return null;
  const sel = (key, label, list) => (
    <label className="iw-filter">{label}
      <select value={filters[key] || ""} onChange={(e) => onChange({ ...filters, [key]: e.target.value })}>
        <option value="">Any</option>
        {list.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>
  );
  const tog = (key, label) => (
    <label className="iw-toggle">
      <input type="checkbox" checked={!!filters[key]} onChange={(e) => onChange({ ...filters, [key]: e.target.checked })} />
      {label}
    </label>
  );
  return (
    <section className="iw-panel" aria-label="Filters">
      <h2>Filters <small>defaults spin anything</small></h2>
      <div className="iw-filters">
        {sel("industry", "Industry", options.industries)}
        {sel("output", "Output type", options.outputs)}
        {sel("buildTime", "Build time", options.buildTimes)}
        {sel("complexity", "Complexity", options.complexities)}
        {sel("market", "B2B / B2C", options.markets)}
        {sel("audience", "Target audience", options.audiences)}
        {sel("aesthetic", "Aesthetic", options.aesthetics)}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
        {tog("excludeRecent", "Exclude recent niches")}
        {tog("localOnly", "Local-business emphasis")}
        {tog("allowRepeats", "Allow repeats")}
      </div>
      <div className="faint" style={{ fontSize: 11.5 }}>
        Catalog: {options.counts.niches} niches · {options.counts.patterns} workflow patterns · {options.counts.styles} styles. Research: docs/ideawheel-research.md
      </div>
    </section>
  );
}

function IwToday({ st, onOpen, onPlanToday }) {
  const t = st.todayIdea;
  const s = st.suggestion;
  return (
    <section className="iw-panel iw-today" aria-label="Today's idea">
      <h2>Today's Idea <small>{st.today}</small></h2>
      {t ? (
        <div className="iw-row">
          <div style={{ minWidth: 0 }}>
            <b>{t.subindustry}</b>
            <div className="faint">{t.deliverableLabel} · <span className={"iw-status iw-status--" + t.status}>{IW_STATUS_LABEL[t.status]}</span></div>
          </div>
          <div className="iw-row-actions"><button className="btn" onClick={() => onOpen(t.id)}>Open</button></div>
        </div>
      ) : s ? (
        <div className="iw-row">
          <div style={{ minWidth: 0 }}>
            <b>Suggested: {s.subindustry}</b>
            <div className="faint">Not planned yet · {IW_STATUS_LABEL[s.status]}</div>
          </div>
          <div className="iw-row-actions">
            <button className="btn" onClick={() => onOpen(s.id)}>Open</button>
            <button className="btn btn-primary" onClick={() => onPlanToday(s.id)}>Plan for today</button>
          </div>
        </div>
      ) : (
        <div className="faint" style={{ fontSize: 12.5 }}>Nothing planned. Spin, save an idea, then plan it for today.</div>
      )}
      <div className="faint" style={{ fontSize: 12 }}>
        Next planned post: {st.nextPlanned ? (st.nextPlanned.date + " — " + st.nextPlanned.idea.subindustry) : "none yet"}
      </div>
    </section>
  );
}

function IwMetricsPanel({ st, onBump, busy }) {
  const m = st.metrics || {};
  const k = st.streak || {};
  return (
    <section className="iw-panel" aria-label="Progress">
      <h2>Progress <small>tracked by hand</small></h2>
      <div className="iw-streak">
        <span>Posting streak: <b>{k.current || 0}</b> day{k.current === 1 ? "" : "s"}</span>
        <span>Posted {k.daysPostedLast7 || 0} of the last 7 days</span>
      </div>
      <div className="iw-metrics">
        <div className="iw-metric"><b>{m.postsCompleted || 0}</b><span>Posts completed</span></div>
        {IW_METRICS.map(([key, label]) => (
          <div className="iw-metric" key={key}>
            <b>{m[key] || 0}</b><span>{label}</span>
            <div className="iw-metric-btns">
              <button className="iw-mini" aria-label={"Decrease " + label} disabled={busy || !m[key]} onClick={() => onBump(key, -1)}>−</button>
              <button className="iw-mini" aria-label={"Increase " + label} disabled={busy} onClick={() => onBump(key, 1)}>+</button>
            </div>
          </div>
        ))}
      </div>
      <div className="faint" style={{ fontSize: 11.5 }}>Posts count only ideas you marked Posted. Nothing is published from here.</div>
    </section>
  );
}

// ---------------------------------------------------------------------------- tabs
function IwHistory({ savedOnly, refreshKey, onOpen, onStatus }) {
  const [q, setQ] = useStateIw("");
  const [status, setStatus] = useStateIw("");
  const [tag, setTag] = useStateIw("");
  const [rows, setRows] = useStateIw(null);
  const [tags, setTags] = useStateIw([]);
  const [err, setErr] = useStateIw("");
  useEffectIw(() => {
    let live = true;
    const qs = "?q=" + encodeURIComponent(q) + "&status=" + status + "&tag=" + encodeURIComponent(tag) + "&saved=" + (savedOnly ? "1" : "0");
    const t = setTimeout(() => {
      window.apiGet("/api/ideawheel/ideas" + qs)
        .then((d) => { if (live) { setRows(d.ideas); setTags(d.tags || []); setErr(""); } })
        .catch((e) => { if (live) setErr(e.message); });
    }, 180);
    return () => { live = false; clearTimeout(t); };
  }, [q, status, tag, savedOnly, refreshKey]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="iw-filters">
        <label className="iw-filter">Search<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="niche, title, tag" /></label>
        <label className="iw-filter">Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {Object.keys(IW_STATUS_LABEL).map((s) => <option key={s} value={s}>{IW_STATUS_LABEL[s]}</option>)}
          </select>
        </label>
        <label className="iw-filter">Tag
          <select value={tag} onChange={(e) => setTag(e.target.value)}>
            <option value="">All</option>
            {tags.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
      </div>
      {err && <div className="iw-disclosure">Couldn't load history: {err}</div>}
      {!rows && !err && <div className="faint">Loading…</div>}
      {rows && !rows.length && <div className="faint" style={{ fontSize: 12.5 }}>{savedOnly ? "No saved ideas yet." : "No spins yet."}</div>}
      <div className="iw-list">
        {(rows || []).map((r) => (
          <div className="iw-row" key={r.id}>
            <div style={{ minWidth: 0 }}>
              <b style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.title}>{r.subindustry} — {r.deliverableLabel}</b>
              <div className="faint">
                {iwDate(r.savedAt || r.createdAt)} · {r.aesthetic} · {r.complexity}
                {r.plannedFor ? " · planned " + r.plannedFor : ""}{r.hasKit ? " · kit ready" : ""}
                {(r.tags || []).map((t) => " #" + t).join("")}
              </div>
            </div>
            <div className="iw-row-actions">
              <span className={"iw-status iw-status--" + r.status}>{IW_STATUS_LABEL[r.status]}</span>
              <select aria-label={"Set status for " + r.subindustry} value="" onChange={(e) => e.target.value && onStatus(r.id, e.target.value)}
                style={{ background: "#0c1723", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: 8, fontSize: 12 }}>
                <option value="">Status…</option>
                {IW_STATUS_SET.filter((s) => s !== r.status).map((s) => <option key={s} value={s}>{IW_STATUS_LABEL[s]}</option>)}
              </select>
              <button className="btn" onClick={() => onOpen(r.id)}>Open</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function IwPlanner({ st, idea, onAssign, onClear, onOpen, busy }) {
  const cal = st.calendar || [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="faint" style={{ fontSize: 12.5 }}>
        One post per day. {idea ? <>Click a day to plan <b style={{ color: "var(--text)" }}>{idea.subindustry}</b>.</> : "Open or spin an idea, then click a day to plan it."}
      </div>
      <div className="iw-cal" role="grid" aria-label="Posting plan, two weeks">
        {IW_WEEKDAYS.map((d) => <div key={d} className="iw-cal-head" role="columnheader">{d}</div>)}
        {cal.map((c) => {
          const cls = "iw-cal-day" + (c.isToday ? " is-today" : "") + (c.postedCount ? " is-posted" : "") + (c.planned ? " is-planned" : "");
          const click = () => (idea ? onAssign(c.date, idea.id) : c.planned ? onOpen(c.planned.id) : null);
          return (
            <div key={c.date} className={cls} role="gridcell">
              <button onClick={click} disabled={busy || (!idea && !c.planned)} style={{ width: "100%", textAlign: "left", color: "inherit" }}
                aria-label={c.date + (c.planned ? ", planned: " + c.planned.subindustry : ", nothing planned") + (c.postedCount ? ", posted" : "")}>
                <b>{c.date.slice(8)}</b>
                <div style={{ marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {c.planned ? c.planned.subindustry : "—"}
                </div>
                {c.postedCount ? <div style={{ color: "#6ee795" }}>posted</div> : null}
              </button>
              {c.planned && (
                <button className="faint" style={{ fontSize: 10, marginTop: 2 }} onClick={() => onClear(c.date)} disabled={busy}
                  aria-label={"Clear plan for " + c.date}>clear</button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function IwKitPanel({ idea, kit, brief, onKit, busy }) {
  if (!idea) return <div className="faint" style={{ fontSize: 12.5 }}>Spin or open an idea first.</div>;
  if (!kit && !brief) {
    return (
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span className="faint" style={{ fontSize: 12.5 }}>No content kit for this idea yet.</span>
        <button className="btn btn-primary" onClick={onKit} disabled={busy}>Generate Content Kit</button>
      </div>
    );
  }
  return (
    <div className="iw-kit">
      {kit && (
        <>
          <div className="iw-disclosure" role="note">{kit.disclosure}</div>
          <h3>Storyboard · {kit.durationSeconds}s</h3>
          <div className="iw-list" style={{ maxHeight: "none" }}>
            {kit.storyboard.map((b, i) => (
              <div className="iw-row" key={i}>
                <div style={{ minWidth: 0 }}>
                  <b>{b.t} · {b.beat}</b>
                  <div className="faint">Shot: {b.shot}</div>
                  <div style={{ fontSize: 12.5, marginTop: 3 }}>On screen: {b.onScreen}</div>
                  <div style={{ fontSize: 12.5, color: "var(--text-2)" }}>VO: {b.voiceover}</div>
                </div>
              </div>
            ))}
          </div>
          <h3>Thumbnail headline</h3><pre>{kit.thumbnailHeadline}</pre>
          <h3>Instagram caption</h3><pre>{kit.captions.instagram}</pre>
          <h3>TikTok caption</h3><pre>{kit.captions.tiktok}</pre>
          <h3>LinkedIn caption</h3><pre>{kit.captions.linkedin}</pre>
          <h3>Hashtags</h3><pre>{kit.hashtags.join(" ")}</pre>
          <h3>Voiceover script</h3><pre>{kit.voiceover}</pre>
          <h3>DM pitch</h3><pre>{kit.dmPitch}</pre>
        </>
      )}
      {brief && (<><h3>Build brief (Markdown)</h3><pre>{brief}</pre></>)}
    </div>
  );
}

// ---------------------------------------------------------------------------- page
function AgencyIdeaWheel() {
  const st = window.useApi("/api/ideawheel/state");
  const data = st.data;
  const [filters, setFilters] = useStateIw(null);
  const [segments, setSegments] = useStateIw([]);
  const [rotation, setRotation] = useStateIw(0);
  const [instant, setInstant] = useStateIw(false);
  const [landed, setLanded] = useStateIw(null);
  const [spinning, setSpinning] = useStateIw(false);
  const [idea, setIdea] = useStateIw(null);
  const [fromHistory, setFromHistory] = useStateIw(false);
  const [kit, setKit] = useStateIw(null);
  const [brief, setBrief] = useStateIw("");
  const [exhausted, setExhausted] = useStateIw(null);
  const [busy, setBusy] = useStateIw(false);
  const [tab, setTab] = useStateIw("history");
  const [toast, setToast] = useStateIw("");
  const [announce, setAnnounce] = useStateIw("");
  const [histKey, setHistKey] = useStateIw(0);
  const rotRef = useRefIw(0);
  const pending = useRefIw(null);
  const toastTimer = useRefIw(null);
  const kitRef = useRefIw(null);

  // First load: adopt the saved filters and show placeholder segments (one per industry).
  useEffectIw(() => {
    if (!data) return;
    if (!filters) setFilters(data.prefs);
    if (!segments.length) {
      setSegments(data.options.sectors.slice(0, 10).map((s) => ({
        nicheId: "sector:" + s.id, label: s.label.split(" & ")[0], sectorId: s.id, icon: s.icon, color: s.color,
      })));
    }
  }, [data]);
  useEffectIw(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current); }, []);

  function say(msg) {
    setToast(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 2800);
  }
  function refreshAll() { st.refresh(); setHistKey((k) => k + 1); }

  function finishSpin(res) {
    if (!pending.current || pending.current !== res) return;
    pending.current = null;
    setLanded(res.landingIndex);
    setIdea(res.idea); setFromHistory(false); setKit(null); setBrief("");
    setSpinning(false);
    setAnnounce("Landed on " + res.segments[res.landingIndex].label + ". " + res.idea.title);
    refreshAll();
  }

  async function spin(noAnim, override) {
    if (spinning || busy) return;
    const f = override || filters || {};
    setSpinning(true); setExhausted(null); setLanded(null);
    let res;
    try {
      res = await window.apiPost("/api/ideawheel/spin", { filters: f });
    } catch (e) {
      setSpinning(false);
      say("Spin failed: " + e.message + " — try again.");
      return;
    }
    if (!res.ok) {
      setSpinning(false); setExhausted(res); setAnnounce(res.message);
      return;
    }
    const n = res.segments.length, seg = 360 / n;
    const center = (res.landingIndex + 0.5) * seg;
    const jitter = ((iwHash(res.seed) % 600) / 1000 - 0.3) * seg; // stays inside the segment
    const cur = rotRef.current;
    const base = cur - (((cur % 360) + 360) % 360);
    const reduce = noAnim || iwReduceMotion();
    let target = base + ((360 - center - jitter) % 360 + 360) % 360;
    if (!reduce) target += 360 * 5;
    if (target <= cur) target += 360;
    rotRef.current = target;
    pending.current = res;
    setSegments(res.segments);
    setInstant(reduce);
    setRotation(target);
    if (reduce) finishSpin(res);
    else setTimeout(() => finishSpin(res), IW_DURATION + 250); // transitionend can be skipped in background tabs
  }

  async function act(kind) {
    if (!idea || busy || spinning) return;
    if (kind === "spin") return spin(false);
    setBusy(true);
    try {
      if (kind === "save") {
        let r = await window.apiPost("/api/ideawheel/save", { id: idea.id });
        if (r.duplicate) {
          if (!window.confirm(r.message + "\n\nExisting: " + r.existing.subindustry + " (" + IW_STATUS_LABEL[r.existing.status] + ")")) { setBusy(false); return; }
          r = await window.apiPost("/api/ideawheel/save", { id: idea.id, force: true });
        }
        setIdea(r.idea); say("Saved.");
      } else if (kind === "restyle") {
        const r = await window.apiPost("/api/ideawheel/restyle", { id: idea.id });
        setIdea(r.idea); setKit(null); setBrief(""); say("New style: " + r.idea.design.aesthetic);
      } else if (kind === "kit") {
        const r = await window.apiPost("/api/ideawheel/kit", { id: idea.id });
        setKit(r.kit); setIdea(r.idea); setTab("kit"); say("Content kit ready.");
        setTimeout(() => kitRef.current && kitRef.current.scrollIntoView({ behavior: iwReduceMotion() ? "auto" : "smooth", block: "start" }), 50);
      } else if (kind === "building") {
        const r = await window.apiPost("/api/ideawheel/status", { id: idea.id, status: "building" });
        setIdea(r.idea); say("Marked building.");
      } else if (kind === "posted") {
        if (!window.confirm("Mark this idea as posted?\n\nOnly do this after you actually published it — the streak counts only what you mark.")) { setBusy(false); return; }
        const r = await window.apiPost("/api/ideawheel/status", { id: idea.id, status: "posted" });
        setIdea(r.idea); say("Marked posted.");
      } else if (kind === "brief") {
        const r = await window.apiGet("/api/ideawheel/brief?id=" + idea.id);
        setBrief(r.markdown);
        const ok = await iwCopy(r.markdown);
        setTab("kit");
        say(ok ? "Build brief copied to clipboard." : "Clipboard blocked — the brief is shown in the Content Kit tab.");
      } else if (kind === "today") {
        await window.apiPost("/api/ideawheel/plan", { date: data.today, id: idea.id });
        const r = await window.apiGet("/api/ideawheel/idea?id=" + idea.id);
        setIdea(r.idea); say("Planned for today.");
      }
      refreshAll();
    } catch (e) {
      say("Didn't work: " + e.message);
    }
    setBusy(false);
  }

  async function openIdea(id) {
    try {
      const r = await window.apiGet("/api/ideawheel/idea?id=" + id);
      setIdea(r.idea); setKit(r.kit || null); setBrief(""); setLanded(null); setExhausted(null); setFromHistory(true);
      setAnnounce("Opened " + r.idea.title);
      window.scrollTo && document.querySelector(".content") && document.querySelector(".content").scrollTo({ top: 0, behavior: iwReduceMotion() ? "auto" : "smooth" });
    } catch (e) { say("Couldn't open: " + e.message); }
  }
  async function quick(path, body, msg) {
    setBusy(true);
    try {
      const r = await window.apiPost(path, body);
      if (r.idea && idea && r.idea.id === idea.id) setIdea(r.idea);
      if (msg) say(msg);
      refreshAll();
    } catch (e) { say("Didn't work: " + e.message); }
    setBusy(false);
  }
  async function changeFilters(next) {
    setFilters(next);
    try { await window.apiPost("/api/ideawheel/prefs", { filters: next }); } catch (e) { say("Filters not saved: " + e.message); }
  }
  function relax(key) {
    const next = { ...filters, [key]: key === "allowRepeats" ? true : key === "localOnly" ? false : "" };
    changeFilters(next);
    spin(false, next);
  }

  if (st.loading && !data) return <div className="iw-page"><div className="faint" style={{ padding: 14 }}>Loading the Idea Wheel…</div></div>;
  if (st.error && !data) {
    return (
      <div className="iw-page">
        <div className="iw-panel" role="alert">
          <h2>Idea Wheel didn't load</h2>
          <div className="faint mono" style={{ fontSize: 12 }}>{st.error}</div>
          <div><button className="btn" onClick={st.refresh}>Retry</button></div>
        </div>
      </div>
    );
  }
  const f = filters || data.prefs;
  const counts = data.counts || {};
  return (
    <div className="iw-page">
      <div className="iw-head">
        <div>
          <h1 style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="iw-ico iw-ico--spark" aria-hidden="true" style={{ fontSize: 22, color: "var(--workspace-accent)" }} />
            Idea Wheel
          </h1>
          <p>Spin a buildable portfolio concept — one strong demo a day, turned into agency leads.</p>
        </div>
        <div className="iw-meta">
          <span className="iw-chip">Streak {data.streak.current}d</span>
          <span className="iw-chip">{counts.saved + counts.building + counts.ready || 0} in backlog</span>
          <span className="iw-chip">{data.metrics.postsCompleted} posted</span>
          <span className="iw-chip">{data.spins} spins</span>
        </div>
      </div>

      <div className="iw-grid">
        <section className="iw-stage" aria-label="Idea wheel">
          <IwWheel segments={segments} rotation={rotation} instant={instant} landed={landed}
            spinning={spinning} busy={spinning || busy} onSpin={() => spin(false)} />
          <div className="iw-controls">
            <button className="btn" onClick={() => spin(true)} aria-disabled={spinning || busy}>
              <span className="iw-ico iw-ico--bulb" aria-hidden="true" style={{ fontSize: 15 }} />
              Surprise Me (no animation)
            </button>
            <label className="iw-toggle">
              <input type="checkbox" checked={!!f.allowRepeats} onChange={(e) => changeFilters({ ...f, allowRepeats: e.target.checked })} />
              Allow repeats
            </label>
          </div>
          <div className="faint" style={{ fontSize: 11.5, textAlign: "center", position: "relative" }}>
            The wheel shows a rotating set of industries; the result is always the segment it lands on.
          </div>
        </section>
        <IwResult idea={idea} kitReady={!!kit} busy={busy || spinning} onAction={act}
          exhausted={exhausted} onRelax={relax} fromHistory={fromHistory} />
      </div>

      <div className="iw-row-grid">
        <IwToday st={data} onOpen={openIdea} onPlanToday={(id) => quick("/api/ideawheel/plan", { date: data.today, id }, "Planned for today.")} />
        <IwMetricsPanel st={data} busy={busy} onBump={(metric, delta) => quick("/api/ideawheel/metric", { metric, delta })} />
        <IwFilters options={data.options} filters={f} onChange={changeFilters} />
      </div>

      <section className="iw-panel" ref={kitRef} aria-label="History, planner and content kit">
        <div className="iw-tabs" role="tablist">
          {[["history", "History"], ["saved", "Saved ideas"], ["planner", "Daily planner"], ["kit", "Content kit"]].map(([k, label]) => (
            <button key={k} role="tab" className="iw-tab" aria-selected={tab === k} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
        <div role="tabpanel">
          {tab === "history" && <IwHistory savedOnly={false} refreshKey={histKey} onOpen={openIdea}
            onStatus={(id, s) => (s === "posted" && !window.confirm("Mark as posted? Only after you actually published it.")) ? null : quick("/api/ideawheel/status", { id, status: s }, "Status: " + IW_STATUS_LABEL[s])} />}
          {tab === "saved" && <IwHistory savedOnly={true} refreshKey={histKey} onOpen={openIdea}
            onStatus={(id, s) => (s === "posted" && !window.confirm("Mark as posted? Only after you actually published it.")) ? null : quick("/api/ideawheel/status", { id, status: s }, "Status: " + IW_STATUS_LABEL[s])} />}
          {tab === "planner" && <IwPlanner st={data} idea={idea} busy={busy} onOpen={openIdea}
            onAssign={(date, id) => quick("/api/ideawheel/plan", { date, id }, "Planned for " + date)}
            onClear={(date) => quick("/api/ideawheel/plan", { date, id: null }, "Cleared " + date)} />}
          {tab === "kit" && <IwKitPanel idea={idea} kit={kit} brief={brief} busy={busy} onKit={() => act("kit")} />}
        </div>
      </section>

      <div className="iw-sr" aria-live="polite">{announce}</div>
      {toast && <div className="iw-toast" role="status">{toast}</div>}
    </div>
  );
}

Object.assign(window, { AgencyIdeaWheel });
