// agency_eco.jsx — Eco, the ads strategist tab (Forge AI Agency).
// Eco reviews a client's (mock) Meta Ads analytics and surfaces: best-performing
// ads to scale, weak ads to pause/rework, the next 3 ads to create, and a
// competitor-research placeholder. One button ships the rec set to the Approval
// Center.
//
// Static-React: hooks aliased (…Ec), every top-level name prefixed Ec, page
// component is exactly AgencyEco, shipped on window at the bottom. No build step.
const { useState: useStateEc, useEffect: useEffectEc } = React;

// ---- best-performing ad row -------------------------------------------------
function EcBestRow({ ad }) {
  const Icons = window.Icons;
  const Flame = Icons.Flame;
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 11, padding: "10px 0",
      borderTop: "1px solid var(--border)" }}>
      <span style={{ color: "var(--green)", flexShrink: 0, marginTop: 1 }}><Flame size={16} /></span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 600, fontSize: 13.5 }}>{ad.name}</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--green)", background: "var(--green)1f",
            padding: "3px 9px", borderRadius: 999, whiteSpace: "nowrap" }}>{ad.roas}x ROAS</span>
        </div>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 3 }}>{ad.why}</div>
        {ad.hook && <div className="faint mono" style={{ fontSize: 11.5, marginTop: 3 }}>“{ad.hook}”</div>}
      </div>
    </div>
  );
}

// ---- weak ad row ------------------------------------------------------------
function EcWeakRow({ ad }) {
  const Icons = window.Icons;
  const Activity = Icons.Activity;
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 11, padding: "10px 0",
      borderTop: "1px solid var(--border)" }}>
      <span style={{ color: "var(--orange)", flexShrink: 0, marginTop: 1 }}><Activity size={16} /></span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 600, fontSize: 13.5 }}>{ad.name}</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--red)", background: "var(--red)1f",
            padding: "3px 9px", borderRadius: 999, whiteSpace: "nowrap" }}>{ad.roas}x ROAS</span>
        </div>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 3 }}>{ad.why}</div>
      </div>
    </div>
  );
}

// ---- section shell (icon + title + body) ------------------------------------
function EcSection({ icon, color, title, count, children }) {
  const Icons = window.Icons;
  const Ico = Icons[icon] || Icons.Eco;
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 4 }}>
        <span style={{ color, display: "flex" }}><Ico size={16} /></span>
        <span className="card-title" style={{ margin: 0 }}>{title}</span>
        {count != null && <span className="faint" style={{ fontSize: 12, marginLeft: "auto" }}>{count}</span>}
      </div>
      {children}
    </div>
  );
}

// ---- competitor research panel (real when backend is real, mock-guarded) ----
function CompResearchPanel({ comp, clientId, onRefresh, busy, setBusy }) {
  const Icons = window.Icons;
  const Search = Icons.Search;
  const [compErr, setCompErr] = useStateEc(null);
  const [compDone, setCompDone] = useStateEc(false);
  const [compResult, setCompResult] = useStateEc(null);

  async function runResearch() {
    if (!clientId) return;
    setBusy(true); setCompErr(null); setCompDone(false);
    try {
      const res = await window.apiPost("/api/agency/eco/competitor", { client: clientId });
      setCompResult(res);          // render the just-computed result directly
      setCompDone(true);
      onRefresh && onRefresh();     // also refresh the set view (best-effort)
    } catch (e) {
      setCompErr(e.message || "Research failed");
    }
    setBusy(false);
  }

  // Prefer the freshly-fetched result; fall back to the set's persisted competitor block.
  const view = compResult || comp;
  const isReal = view && view.status && view.status !== "placeholder";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {isReal && view.summary && (
        <div style={{ fontSize: 12.5, color: "var(--text)", lineHeight: 1.45 }}>{view.summary}</div>
      )}
      {isReal && Array.isArray(view.competitorAngles) && view.competitorAngles.length > 0 && (
        <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 3 }}>Competitor angles</div>
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 3 }}>
            {view.competitorAngles.map((c, i) => (
              <li key={i}>{typeof c === "string" ? c : (c.angle || "") + (c.description ? " — " + c.description : "")}</li>
            ))}
          </ul>
        </div>
      )}
      {isReal && Array.isArray(view.positioningGaps) && view.positioningGaps.length > 0 && (
        <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 3 }}>Gaps to exploit</div>
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 3 }}>
            {view.positioningGaps.map((c, i) => <li key={i}>{typeof c === "string" ? c : JSON.stringify(c)}</li>)}
          </ul>
        </div>
      )}
      {isReal && Array.isArray(view.recommendedDifferentiators) && view.recommendedDifferentiators.length > 0 && (
        <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 3 }}>Differentiators to lean into</div>
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 3 }}>
            {view.recommendedDifferentiators.map((c, i) => <li key={i}>{typeof c === "string" ? c : JSON.stringify(c)}</li>)}
          </ul>
        </div>
      )}
      {isReal && Array.isArray(view.competitors) && view.competitors.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: "var(--muted)",
          display: "flex", flexDirection: "column", gap: 3 }}>
          {view.competitors.map((c, i) => <li key={i}>{typeof c === "string" ? c : JSON.stringify(c)}</li>)}
        </ul>
      )}
      {compErr && <div style={{ color: "var(--red)", fontSize: 12 }}>{compErr}</div>}
      {compDone && <div style={{ color: "var(--green)", fontSize: 12 }}>Research complete — check results above.</div>}
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button className="tab" disabled={busy || !clientId} onClick={runResearch}
          style={{ display: "flex", alignItems: "center", gap: 7,
            opacity: (!clientId) ? 0.55 : 1,
            cursor: (!clientId) ? "not-allowed" : "pointer" }}>
          <Search size={13} /> {busy ? "Researching…" : "Run competitor research"}
        </button>
      </div>
    </div>
  );
}

function AgencyEco() {
  const Icons = window.Icons;
  const Bot = Icons.Bot;
  const Eco = Icons.Eco;
  const Spark = Icons.Spark;
  const Send = Icons.Send;
  const Search = Icons.Search;

  const [client, setClient] = useStateEc(null);   // { id, name }
  const [busy, setBusy] = useStateEc(false);

  const selectedId = client ? client.id : "";
  const path = selectedId ? `/api/agency/eco?client=${selectedId}` : `/api/agency/eco`;
  const { data, loading, error, refresh } = window.useApi(path);

  // Default to the first available client once the selector resolves one.
  function onPickClient(id, c) { setClient(id ? { id, name: c ? c.name : "" } : null); }

  async function sendToApproval() {
    setBusy(true);
    try {
      await window.apiPost("/api/agency/eco/generate", { client: selectedId });
      window.alert("Eco's recommendations sent to the Approval Center.");
      if (window.GoTo) window.GoTo("Approvals");
    } catch (e) {
      window.alert("Eco couldn't send recommendations: " + (e.message || e));
    }
    setBusy(false);
  }

  const ok = data && data.ok;
  const acct = ok ? data.account : null;
  const best = (ok && data.best) || [];
  const weak = (ok && data.weak) || [];
  const next = (ok && data.next) || [];
  const comp = (ok && data.competitor) || {};

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
        <div style={{ width: 46, height: 46, borderRadius: 12, flexShrink: 0,
          background: "var(--green)1f", color: "var(--green)",
          display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Eco size={24} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px",
            display: "flex", alignItems: "center", gap: 8 }}>
            Eco <span style={{ color: "var(--muted)", display: "flex" }}><Bot size={18} /></span>
          </h1>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>
            Your ads strategist — finds what's working, what's not, and the next 3 ads to run.
          </div>
        </div>
      </div>

      {/* client selector */}
      <div className="card card-pad" style={{ display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <window.AgUI.ClientSelector value={selectedId} onChange={onPickClient} label="Strategize for" />
        </div>
        {ok && (
          <button className="tab" disabled={busy} onClick={sendToApproval}
            style={{ display: "flex", alignItems: "center", gap: 7,
              background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
            <Send size={14} /> {busy ? "Sending…" : "Send recommendations to Approval Center"}
          </button>
        )}
      </div>

      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {loading && !data && <window.LoadingRow label="Eco is analyzing…" />}

      {!selectedId && !loading && (
        <div className="card empty" style={{ minHeight: "30vh" }}>
          <div className="empty-ico" style={{ width: 72, height: 72 }}><Eco size={30} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>Pick a client to strategize</div>
          <div className="faint" style={{ fontSize: 13, maxWidth: 340, textAlign: "center" }}>
            Choose a client above and Eco will review their ad account.
          </div>
        </div>
      )}

      {ok && selectedId && (
        <React.Fragment>
          {/* reviewing line */}
          <div className="faint" style={{ fontSize: 12.5, display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ color: "var(--green)", display: "flex" }}><Spark size={13} /></span>
            Reviewing {acct.clientName} · {acct.name}
          </div>

          {/* best-performing ads */}
          <EcSection icon="Flame" color="var(--green)" title="Best-performing ads" count={best.length + " scaling"}>
            {best.length === 0
              ? <div className="faint" style={{ fontSize: 12.5, paddingTop: 6 }}>No standout winners yet.</div>
              : best.map((ad, i) => <EcBestRow key={i} ad={ad} />)}
          </EcSection>

          {/* weak ads */}
          <EcSection icon="Activity" color="var(--orange)" title="Weak ads — pause or rework" count={weak.length + " flagged"}>
            {weak.length === 0
              ? <div className="faint" style={{ fontSize: 12.5, paddingTop: 6 }}>Nothing to pause right now.</div>
              : weak.map((ad, i) => <EcWeakRow key={i} ad={ad} />)}
          </EcSection>

          {/* next 3 ads */}
          <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
            <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: "#22C55E", display: "flex" }}><Spark size={15} /></span>
              Next 3 ads to create
            </div>
            {next.map((rec, i) => <window.AgUI.AgentRecCard key={i} rec={rec} />)}
          </div>

          {/* competitor research */}
          <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: "var(--muted)", display: "flex" }}><Search size={15} /></span>
              Competitor research
            </div>
            {comp.status === "placeholder" || !comp.status ? (
              <div className="faint" style={{ fontSize: 13 }}>
                {comp.note || "Eco will analyze competitor ads for this client."}
              </div>
            ) : (
              <div style={{ fontSize: 13 }}>{comp.note}</div>
            )}
            {comp.status === "placeholder" && comp.todo && (
              <div className="faint mono" style={{ fontSize: 11.5, opacity: 0.8 }}>TODO · {comp.todo}</div>
            )}
            <CompResearchPanel comp={comp} clientId={selectedId} onRefresh={refresh} busy={busy} setBusy={setBusy} />
          </div>

          {/* bottom action bar */}
          <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 2 }}>
            <button className="tab" disabled={busy} onClick={sendToApproval}
              style={{ display: "flex", alignItems: "center", gap: 7,
                background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
              <Send size={14} /> {busy ? "Sending…" : "Send recommendations to Approval Center"}
            </button>
          </div>
        </React.Fragment>
      )}
    </div>
  );
}

Object.assign(window, { AgencyEco });
