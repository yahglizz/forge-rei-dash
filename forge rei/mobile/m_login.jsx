// FORGE Mobile — business portal: "Where are you headed?" One tap picks a business
// lens (window.M_BIZ[id]) or "Everything" (the classic 5-tab app). Same one-tap
// pattern as the daycare app's login page. No PIN/password: the tailnet is the
// trust boundary (same as the desktop dashboard) — never add fake client-side auth.
// Top-level prefix: MLG. Exports: MLoginPortal. Consumed by m_app.jsx (onPick(id)).

const MLG_ORDER = ["wholesale", "agency", "daycare"];
// business_scope.py / mission-control ids differ from the mobile biz ids.
const MLG_SCOPE_ID = { wholesale: "rei" };

// One live line from /api/mission-control — first 2 real metrics, or null (never fake).
function MLGLiveLine(bizId, mission) {
  const list = mission && Array.isArray(mission.businesses) ? mission.businesses : [];
  const scopeId = MLG_SCOPE_ID[bizId] || bizId;
  const b = list.find((x) => x && x.id && (x.id === scopeId || String(x.id).includes(bizId)));
  const metrics = b && Array.isArray(b.metrics) ? b.metrics : [];
  const parts = metrics.filter((m) => m && m.label && m.value !== null && m.value !== undefined && m.value !== "")
    .slice(0, 2).map((m) => m.label + " " + m.value);
  return parts.length ? parts.join(" · ") : null;
}

function MLGCard(props) {
  const Ico = window.MIcons[props.ico] || window.MIcons.More;
  return (
    <button type="button" className={"mlg-card" + (props.extra ? " " + props.extra : "")}
      style={{ "--biz": props.accent || "#0968EA" }} onClick={props.onClick}>
      <span className="mlg-icon"><Ico size={26} /></span>
      <span className="mlg-copy">
        <strong>{props.title}</strong>
        {props.detail && <small>{props.detail}</small>}
        {props.live && <small className="mlg-live">{props.live}</small>}
      </span>
      <span className="mlg-enter" aria-hidden="true">→</span>
    </button>
  );
}

function MLoginPortal(props) {
  const mission = window.useApiM("/api/mission-control", { interval: 60000 });
  const scope = window.useApiM("/api/businesses");
  // Hide a business only when /api/businesses explicitly says archived (fail open).
  const archived = new Set(((scope.data && scope.data.businesses) || [])
    .filter((b) => b && b.archived).map((b) => b.id));
  const reg = window.M_BIZ || {};
  const rank = (id) => (MLG_ORDER.indexOf(id) + 1) || 99;
  const ids = Object.keys(reg).filter((id) => reg[id] && !archived.has(MLG_SCOPE_ID[id] || id))
    .sort((a, b) => rank(a) - rank(b));
  const pick = (id) => { if (window.hapticM) window.hapticM("tap"); props.onPick && props.onPick(id); };
  return (
    <main className="mlg-page">
      <section className="mlg-brand">
        <div className="mlg-mark"><window.MForgePal size={56} /></div>
        <p className="mlg-eyebrow">Command center</p>
        <h1 className="mlg-title">FORGE</h1>
      </section>
      <section className="mlg-panel">
        <div className="mlg-wrap">
          <h1 className="mlg-h1">Where are you headed?</h1>
          <p className="mlg-sub">Tap your business and you're in.</p>
          <div className="mlg-grid" aria-label="Choose a business">
            {ids.map((id) => {
              const b = reg[id];
              return <MLGCard key={id} ico={b.ico} accent={b.accent} title={b.name || id}
                detail={b.tagline} live={MLGLiveLine(id, mission.data)} onClick={() => pick(id)} />;
            })}
            <MLGCard extra="mlg-all" ico="Home" accent="#C9962B" title="Everything"
              detail="Owner view — all businesses" onClick={() => pick("all")} />
          </div>
          <p className="mlg-foot">Secured by your Tailscale network.</p>
        </div>
      </section>
    </main>
  );
}

Object.assign(window, { MLoginPortal });
