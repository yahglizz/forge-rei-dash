// agency_clientview.jsx — Client Dashboard section (Forge AI Agency).
// The client-facing view: submit requests, track status, see delivered updates.
// Acts AS a chosen client (preview mode — no real auth yet).
// Static-React: hooks aliased (…Cv), top-level names prefixed Cv, shipped on window.
const { useState: useStateCv, useEffect: useEffectCv } = React;

// last-30-days window for the "This Month" metric
const CV_MONTH_MS = 30 * 24 * 60 * 60 * 1000;
function cvWithin30(ts) {
  if (!ts) return false;
  const t = new Date(ts).getTime();
  return !isNaN(t) && (Date.now() - t) <= CV_MONTH_MS;
}
const CV_OPEN = ["submitted", "in_review", "approved", "in_progress"];
const CV_DELIVERED = ["approved", "completed"];

// ---- preview-mode notice ----------------------------------------------------
function CvPreviewBanner() {
  const Icons = window.Icons;
  return (
    <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 10,
      borderColor: "var(--orange)", background: "var(--orange)11", padding: "10px 13px" }}>
      <span style={{ color: "var(--orange)", display: "flex" }}><Icons.Spark size={15} /></span>
      <span className="faint" style={{ fontSize: 12.5 }}>
        Preview mode — client login / permissions not enabled yet. You're viewing the dashboard a client would see.
      </span>
    </div>
  );
}

// ---- client login gate scaffold (behind window.AGENCY_CLIENT_LOGIN flag) ---
// Default OFF — keep preview mode. Set window.AGENCY_CLIENT_LOGIN = true (in
// the HTML or agency.env delivered config) to activate the login gate.
const CV_LOGIN_FLAG = typeof window !== "undefined" && !!window.AGENCY_CLIENT_LOGIN;

function CvLoginGate({ onAuthenticated }) {
  const [email, setEmail] = useStateCv("");
  const [token, setToken] = useStateCv("");
  const [loggingIn, setLoggingIn] = useStateCv(false);
  const [loginErr, setLoginErr] = useStateCv(null);

  async function doLogin() {
    if (!email.trim()) { setLoginErr("Email is required"); return; }
    if (!token.trim()) { setLoginErr("Access token is required"); return; }
    setLoggingIn(true); setLoginErr(null);
    try {
      const res = await window.apiPost("/api/agency/client/login", { email: email.trim(), token: token.trim() });
      if (res && res.ok && res.clientId) {
        onAuthenticated && onAuthenticated({ clientId: res.clientId, clientName: res.clientName || email });
      } else {
        setLoginErr("Invalid credentials — check your email and access token.");
      }
    } catch (e) {
      setLoginErr(e.message || "Login failed");
    }
    setLoggingIn(false);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minHeight: "60vh",
      justifyContent: "center", alignItems: "center" }}>
      <div className="card card-pad" style={{ maxWidth: 400, width: "100%", display: "flex",
        flexDirection: "column", gap: 14 }}>
        <div style={{ fontWeight: 700, fontSize: 20, textAlign: "center", letterSpacing: "-0.4px" }}>
          Client Portal
        </div>
        <div className="faint" style={{ fontSize: 12.5, textAlign: "center" }}>
          Enter the email and access token from your welcome email.
        </div>
        <div>
          <div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Email</div>
          <input style={{ ...window.AgUI.inp, width: "100%" }} type="email" value={email}
            onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
        </div>
        <div>
          <div className="faint" style={{ fontSize: 11, marginBottom: 5 }}>Access token</div>
          <input style={{ ...window.AgUI.inp, width: "100%" }} type="password" value={token}
            onChange={(e) => setToken(e.target.value)} placeholder="••••••••" />
        </div>
        {loginErr && <div style={{ color: "var(--red)", fontSize: 12.5 }}>{loginErr}</div>}
        <button className="tab" disabled={loggingIn} onClick={doLogin}
          style={{ background: "var(--green)", color: "#04210f", fontWeight: 700, borderColor: "transparent" }}>
          {loggingIn ? "Signing in…" : "Sign in"}
        </button>
      </div>
    </div>
  );
}

// ---- one request row in the status tracker ----------------------------------
function CvStatusRow({ r }) {
  return (
    <tr>
      <td>
        <div style={{ fontWeight: 600, fontSize: 13 }}>{r.title}</div>
        {r.detail && <div className="faint" style={{ fontSize: 11.5, marginTop: 2,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 320 }}>{r.detail}</div>}
      </td>
      <td className="faint" style={{ fontSize: 12.5 }}>{r.type}</td>
      <td><window.AgUI.PriorityBadge priority={r.priority} /></td>
      <td><window.AgUI.StatusBadge status={r.status} /></td>
      <td className="faint mono" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
        {window.timeAgo(r.updatedAt || r.createdAt)}
      </td>
    </tr>
  );
}

// ---- delivered-update card --------------------------------------------------
function CvDeliveredCard({ r }) {
  return (
    <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: 13.5 }}>{r.title}</div>
        <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>
          {r.type} · Delivered {window.timeAgo(r.updatedAt || r.createdAt)}
        </div>
      </div>
      <window.AgUI.StatusBadge status={r.status} />
    </div>
  );
}

// ---- the page ---------------------------------------------------------------
function AgencyClientView() {
  const Icons = window.Icons;
  const clientsApi = window.useApi("/api/agency/clients");
  const reqApi = window.useApi("/api/agency/requests", { interval: 20000 });

  const clients = (clientsApi.data && clientsApi.data.clients) || [];
  const [sel, setSel] = useStateCv({ clientId: "", clientName: "" });
  const [creating, setCreating] = useStateCv(false);
  // Login gate state — only used when AGENCY_CLIENT_LOGIN flag is on.
  const [loginSel, setLoginSel] = useStateCv(null);

  // If login gate is active and authenticated, override selector with logged-in client.
  const effectiveSel = (CV_LOGIN_FLAG && loginSel) ? loginSel : sel;

  // default to first live client once they load (only if nothing chosen yet and not gated)
  useEffectCv(() => {
    if (!CV_LOGIN_FLAG && !sel.clientId && clients.length) {
      setSel({ clientId: clients[0].id, clientName: clients[0].name });
    }
  }, [clients.length]);

  // Login gate — show ONLY when flag is on and not yet authenticated.
  if (CV_LOGIN_FLAG && !loginSel) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Client Dashboard</h1>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>Secure portal for ClientForge clients.</div>
        </div>
        <CvLoginGate onAuthenticated={(auth) => setLoginSel(auth)} />
      </div>
    );
  }

  const reqs = (reqApi.data && reqApi.data.requests) || [];
  const selClient = clients.find((c) => c.id === effectiveSel.clientId);
  const mine = effectiveSel.clientId
    ? reqs.filter((r) => r.clientId === effectiveSel.clientId)
        .slice().sort((a, b) => new Date(b.updatedAt || b.createdAt) - new Date(a.updatedAt || a.createdAt))
    : [];

  const openCount = mine.filter((r) => CV_OPEN.indexOf(r.status) >= 0).length;
  const doneCount = mine.filter((r) => r.status === "completed").length;
  const monthCount = mine.filter((r) => cvWithin30(r.updatedAt || r.createdAt)).length;
  const planText = selClient && selClient.plan ? selClient.plan : "—";

  const kpis = [
    { label: "Open Requests", value: openCount, icon: "Requests", color: "#4F7CFF" },
    { label: "Completed", value: doneCount, icon: "Check", color: "#22C55E" },
    { label: "Plan", value: planText, icon: "Dollar", color: "#8B5CF6" },
    { label: "This Month", value: monthCount, sub: "last 30 days", icon: "Calendar", color: "#F59E0B" },
  ];

  const delivered = mine.filter((r) => CV_DELIVERED.indexOf(r.status) >= 0);
  const err = clientsApi.error || reqApi.error;
  const loading = (clientsApi.loading && !clientsApi.data) || (reqApi.loading && !reqApi.data);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Client Dashboard</h1>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>
          What your client sees — submit requests, track status, view delivered updates.
        </div>
      </div>

      {/* Only show preview banner + client selector in non-gated (preview) mode */}
      {!CV_LOGIN_FLAG && <CvPreviewBanner />}

      {err && <window.ErrorRow error={err} onRetry={() => { clientsApi.refresh(); reqApi.refresh(); }} />}

      {/* viewing-as client selector — hidden when login gate is active */}
      {!CV_LOGIN_FLAG && (
        <div className="card card-pad" style={{ display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
          <div style={{ minWidth: 240, flex: 1 }}>
            <window.AgUI.ClientSelector label="Viewing as" value={sel.clientId}
              onChange={(id, c) => { setSel({ clientId: id, clientName: c ? c.name : "" }); setCreating(false); }} />
          </div>
          {sel.clientName && (
            <div className="faint" style={{ fontSize: 12, paddingBottom: 9 }}>
              Acting as <span style={{ color: "var(--text)", fontWeight: 600 }}>{sel.clientName}</span>
            </div>
          )}
        </div>
      )}

      {/* When gated + logged in, show who is viewing */}
      {CV_LOGIN_FLAG && loginSel && (
        <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="dot online pulse" />
          <span style={{ fontWeight: 600, fontSize: 13.5 }}>{loginSel.clientName}</span>
          <button className="tab" style={{ marginLeft: "auto", fontSize: 12 }}
            onClick={() => setLoginSel(null)}>Sign out</button>
        </div>
      )}

      {loading && !reqApi.data && <window.LoadingRow label="Loading client dashboard…" />}

      {!effectiveSel.clientId && !loading && (
        <div className="card empty" style={{ minHeight: "32vh" }}>
          <div className="empty-ico" style={{ width: 72, height: 72 }}><Icons.ClientView size={30} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 16 }}>Pick a client to preview</div>
          <div style={{ fontSize: 13, maxWidth: 340, textAlign: "center" }}>
            Choose a client above to see exactly what their dashboard looks like.
          </div>
        </div>
      )}

      {effectiveSel.clientId && (
        <React.Fragment>
          {/* analytics overview */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
            {kpis.map((k) => <window.AgUI.AnalyticsCard key={k.label} {...k} />)}
          </div>

          {/* submit a request */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div className="card-title">Submit a request</div>
              {!creating && <button className="tab" style={{ display: "flex", alignItems: "center", gap: 6 }}
                onClick={() => setCreating(true)}><Icons.Plus size={14} /> New Request</button>}
            </div>
            {creating ? (
              <window.AgUI.RequestForm lockClient
                initial={{ clientId: effectiveSel.clientId, clientName: effectiveSel.clientName }}
                onSaved={() => { setCreating(false); reqApi.refresh(); }}
                onCancel={() => setCreating(false)} />
            ) : (
              <div className="faint" style={{ fontSize: 12.5 }}>
                Need a change to your site? Submit a request and we'll track it through to delivery.
              </div>
            )}
          </div>

          {/* request status tracker */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="card-title">Request status</div>
            {mine.length === 0 ? (
              <div className="card empty" style={{ minHeight: "22vh" }}>
                <div className="empty-ico" style={{ width: 60, height: 60 }}><Icons.Requests size={26} /></div>
                <div style={{ fontWeight: 600, color: "var(--text)", fontSize: 15 }}>No requests yet</div>
                <div style={{ fontSize: 12.5, maxWidth: 320, textAlign: "center" }}>
                  Submit your first request above to start tracking it here.
                </div>
              </div>
            ) : (
              <div className="card" style={{ overflow: "hidden" }}>
                <table className="lead-table" style={{ width: "100%", fontSize: 13 }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left" }}>Request</th>
                      <th style={{ textAlign: "left" }}>Type</th>
                      <th style={{ textAlign: "left" }}>Priority</th>
                      <th style={{ textAlign: "left" }}>Status</th>
                      <th style={{ textAlign: "left" }}>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mine.map((r) => <CvStatusRow key={r.id} r={r} />)}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* approved & delivered */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="card-title">Approved &amp; delivered updates</div>
            {delivered.length === 0 ? (
              <div className="faint" style={{ fontSize: 12.5 }}>No delivered updates yet.</div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {delivered.map((r) => <CvDeliveredCard key={r.id} r={r} />)}
              </div>
            )}
          </div>
        </React.Fragment>
      )}
    </div>
  );
}

Object.assign(window, { AgencyClientView });
