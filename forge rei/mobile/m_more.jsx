// FORGE Mobile — More tab: Buyers/Dispo, Deals, Contracts, Brain, Costs, System health.
// Menu of m-list-item rows; each section opens a full-screen m-sheet.
// Hook aliases for this file: MM. Exports: MMorePage.
const { useState: useStateMM, useEffect: useEffectMM } = React;

// ---- tiny shared bits (MM-prefixed) ------------------------------------------

function MMUsd(n) {
  // Spend numbers are small (cents matter) — 2 decimals, unlike fmtMoneyM.
  const x = Number(n);
  if (n === null || n === undefined || isNaN(x)) return "—";
  return "$" + x.toFixed(2);
}

function MMPill(props) {
  const c = props.color || "#4F7CFF";
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: "3px 8px", borderRadius: 999,
      background: c + "22", color: c, whiteSpace: "nowrap", flex: "none" }}>
      {props.text}
    </span>
  );
}

function MMDot(props) {
  return (
    <span style={{ width: 9, height: 9, borderRadius: 99, background: props.color || "#64748B",
      flex: "none", display: "inline-block" }} />
  );
}

function MMErr(props) {
  return (
    <div className="m-card" style={{ borderColor: "rgba(239,68,68,0.35)" }}>
      <div style={{ color: "var(--red, #EF4444)", fontSize: 13, fontWeight: 700 }}>
        Couldn't load
      </div>
      <div className="m-fade" style={{ marginTop: 4, overflowWrap: "break-word" }}>
        {String(props.msg || "unknown error")}
      </div>
      {props.onRetry ? (
        <window.MBtn kind="ghost" style={{ marginTop: 10, width: "100%" }} onClick={props.onRetry}>
          Retry
        </window.MBtn>
      ) : null}
    </div>
  );
}

// ---- 1. Buyers / Dispo ---------------------------------------------------------

function MMBuyerRoster() {
  const { data, error, loading, refresh } = window.useApiM("/api/buyers/list", { interval: 30000 });
  if (loading && !data) return window.MSpin();
  if (error) return <MMErr msg={error} onRetry={refresh} />;
  const rows = (data && data.buyers) || [];
  if (!rows.length) {
    return <window.MEmpty title="No buyers yet" sub="Add cash buyers on the desktop Buyers tab" />;
  }
  return (
    <React.Fragment>
      {rows.map((b) => {
        const nm = b.name || b.company || b.id;
        const areas = (b.areas || []).slice(0, 3).join(", ");
        const lo = b.minPrice, hi = b.maxPrice;
        const band = lo && hi ? window.fmtMoneyM(lo) + "–" + window.fmtMoneyM(hi)
          : hi ? "≤ " + window.fmtMoneyM(hi)
          : lo ? "≥ " + window.fmtMoneyM(lo)
          : "any price";
        const inactive = b.active === false;
        return (
          <div key={b.id} className="m-list-item"
            style={{ minHeight: 48, opacity: inactive ? 0.55 : 1 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="m-row" style={{ gap: 6, flexWrap: "wrap" }}>
                <span style={{ fontSize: 14, fontWeight: 700 }}>{nm}</span>
                {b.pof ? <MMPill text="POF" color="#22C55E" /> : null}
                {inactive ? <MMPill text="inactive" color="#64748B" /> : null}
              </div>
              {b.company && b.name ? (
                <div className="m-fade" style={{ marginTop: 2 }}>{b.company}</div>
              ) : null}
              <div className="m-fade" style={{ marginTop: 3 }}>
                {(areas || "buys anywhere") + " · " + band}
              </div>
            </div>
          </div>
        );
      })}
    </React.Fragment>
  );
}

function MMDispoList() {
  const { data, error, loading, refresh } = window.useApiM("/api/buyers/dispo", { interval: 30000 });
  if (loading && !data) return window.MSpin();
  if (error) return <MMErr msg={error} onRetry={refresh} />;
  const list = (data && data.dispo) || [];
  if (!list.length) {
    return (
      <window.MEmpty title="Dispo worklist is clear"
        sub="No deals under contract or with offers need buyers right now" />
    );
  }
  return (
    <React.Fragment>
      <div className="m-fade">
        {list.length + " deal" + (list.length === 1 ? "" : "s") + " need buyers · "
          + ((data && data.buyerCount) || 0) + " buyers on the roster"}
      </div>
      {list.map((w, i) => {
        const d = w.deal || {};
        const price = d.offer || d.mao || d.asking;
        const priceLbl = d.offer ? "offer" : d.mao ? "MAO" : d.asking ? "asking" : "price TBD";
        const top3 = (w.matches || []).slice(0, 3);
        return (
          <div key={d.contactId || i} className="m-card">
            <div className="m-row" style={{ alignItems: "flex-start" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 700, overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {d.name || d.address || d.contactId || "Deal"}
                </div>
                <div className="m-fade" style={{ marginTop: 2 }}>
                  {[d.stage, d.address].filter(Boolean).join(" · ") || "no stage"}
                </div>
              </div>
              <div style={{ textAlign: "right", flex: "none" }}>
                <div style={{ fontSize: 14, fontWeight: 800 }}>{window.fmtMoneyM(price)}</div>
                <div className="m-fade">{priceLbl}</div>
              </div>
            </div>
            {top3.length ? (
              top3.map((m) => {
                const FitIco = m.fits ? window.MIcons.Check : window.MIcons.X;
                const best = w.topFit && w.topFit.buyerId === m.buyerId;
                return (
                  <div key={m.buyerId || m.name} className="m-row" style={{ marginTop: 9 }}>
                    <span style={{ color: m.fits ? "#22C55E" : "var(--text-3, #64748B)",
                      flex: "none", display: "flex" }}>
                      <FitIco size={14} />
                    </span>
                    <div style={{ flex: 1, minWidth: 0, fontSize: 13, fontWeight: 600,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {m.name || m.buyerId}
                    </div>
                    {best ? <MMPill text="top fit" color="#22C55E" /> : null}
                    <MMPill text={String(m.score) + " fit"}
                      color={m.fits ? "#22C55E" : "#64748B"} />
                  </div>
                );
              })
            ) : (
              <div className="m-fade" style={{ marginTop: 9 }}>
                No buyer matches yet — add buyers on desktop
              </div>
            )}
          </div>
        );
      })}
    </React.Fragment>
  );
}

function MMBuyersSheet(props) {
  const [view, setView] = useStateMM("roster");
  return (
    <div className="m-sheet">
      <window.MHeader title="Buyers / Dispo" sub="Cash-buyer roster + buy-box matches"
        onBack={props.onBack} />
      <div className="m-seg" style={{ padding: "12px 14px 0" }}>
        <window.MChip active={view === "roster"} onClick={() => setView("roster")}>
          Roster
        </window.MChip>
        <window.MChip active={view === "dispo"} onClick={() => setView("dispo")}>
          Dispo worklist
        </window.MChip>
      </div>
      <div className="m-sheet-body">
        {view === "roster" ? <MMBuyerRoster /> : <MMDispoList />}
      </div>
    </div>
  );
}

// ---- 2. Deals -------------------------------------------------------------------

const MM_CS_COLOR = {
  completed: "#22C55E", sent: "#4F7CFF", delivered: "#38BDF8",
  drafted: "#F59E0B", declined: "#EF4444", voided: "#EF4444",
};

function MMDealsSheet(props) {
  const { data, error, loading, refresh } = window.useApiM("/api/deals/list", { interval: 30000 });
  const rows = (data && data.deals) || [];
  return (
    <div className="m-sheet">
      <window.MHeader title="Deals" sub="Deal sheets · MAO · contracts" onBack={props.onBack} />
      <div className="m-sheet-body">
        {loading && !data ? window.MSpin()
          : error ? <MMErr msg={error} onRetry={refresh} />
          : !rows.length ? (
            <window.MEmpty title="No deals yet"
              sub="Run the Deal Calc on a lead to start a deal sheet" />
          ) : (
            rows.map((d) => {
              const cs = String(d.contractStatus || "none").toLowerCase();
              const csColor = MM_CS_COLOR[cs];
              const numLine = d.offer !== undefined && d.offer !== null
                ? "Offer " + window.fmtMoneyM(d.offer)
                : d.mao !== undefined && d.mao !== null
                  ? "MAO " + window.fmtMoneyM(d.mao)
                  : "No numbers yet";
              return (
                <div key={d.contactId} className="m-list-item" style={{ minHeight: 48 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {d.name || d.address || d.contactId}
                    </div>
                    <div className="m-fade" style={{ marginTop: 2, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {[d.stage || "Lead", d.address].filter(Boolean).join(" · ")}
                    </div>
                    <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 3 }}>{numLine}</div>
                  </div>
                  <div style={{ flex: "none", display: "flex", flexDirection: "column",
                    alignItems: "flex-end", gap: 4 }}>
                    {csColor ? <MMPill text={cs} color={csColor} /> : null}
                    <span className="m-fade">{window.timeAgoM(d.updatedAt)}</span>
                  </div>
                </div>
              );
            })
          )}
      </div>
    </div>
  );
}

// ---- 3. Brain ---------------------------------------------------------------------

function MMBrainSheet(props) {
  const [q, setQ] = useStateMM("");
  const [results, setResults] = useStateMM(null);   // null = no search yet
  const [searching, setSearching] = useStateMM(false);
  const [searchErr, setSearchErr] = useStateMM(null);
  const [notePath, setNotePath] = useStateMM(null);
  const [note, setNote] = useStateMM(null);
  const [noteErr, setNoteErr] = useStateMM(null);
  const recent = window.useApiM("/api/brain/recent?n=20", { interval: 60000 });

  const runSearch = async () => {
    const s = q.trim();
    if (!s) { setResults(null); setSearchErr(null); return; }
    setSearching(true);
    setSearchErr(null);
    try {
      const r = await fetch("/api/brain/search?q=" + encodeURIComponent(s));
      const j = await r.json();
      if (j && j.error) throw new Error(j.error);
      setResults((j && j.results) || []);
    } catch (e) {
      setSearchErr(e.message || "search failed");
    } finally {
      setSearching(false);
    }
  };

  const openNote = async (path) => {
    setNotePath(path);
    setNote(null);
    setNoteErr(null);
    try {
      const r = await fetch("/api/brain/note?path=" + encodeURIComponent(path));
      const j = await r.json();
      if (j && j.error) throw new Error(j.error);
      setNote(j);
    } catch (e) {
      setNoteErr(e.message || "could not load note");
    }
  };

  const noteRow = (key, title, sub, right, onTap) => (
    <button key={key} className="m-list-item"
      style={{ width: "100%", minHeight: 48, textAlign: "left", cursor: "pointer",
        fontFamily: "inherit", color: "inherit" }}
      onClick={onTap}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13.5, fontWeight: 700, overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
        {sub ? (
          <div className="m-fade" style={{ marginTop: 2, display: "-webkit-box",
            WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
            {sub}
          </div>
        ) : null}
      </div>
      {right ? <span className="m-fade" style={{ flex: "none" }}>{right}</span> : null}
    </button>
  );

  // Note reader view (nested inside the sheet — back returns to the list).
  if (notePath) {
    return (
      <div className="m-sheet">
        <window.MHeader title={note && note.title ? note.title : "Note"} sub={notePath}
          onBack={() => { setNotePath(null); setNote(null); setNoteErr(null); }} />
        <div className="m-sheet-body">
          {noteErr ? <MMErr msg={noteErr} onRetry={() => openNote(notePath)} />
            : !note ? window.MSpin()
            : (
              <div className="m-card">
                <div style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.55,
                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                  overflowWrap: "break-word" }}>
                  {note.content || "(empty note)"}
                </div>
              </div>
            )}
        </div>
      </div>
    );
  }

  const SearchIcoMM = window.MIcons.Search;
  const recentItems = (recent.data && recent.data.items) || [];
  return (
    <div className="m-sheet">
      <window.MHeader title="Brain" sub="Obsidian vault — search + read" onBack={props.onBack} />
      <div className="m-sheet-body">
        <div className="m-row">
          <input className="m-input" type="search" enterKeyHint="search"
            placeholder="Search the vault…" value={q} style={{ flex: 1 }}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") runSearch(); }} />
          <window.MBtn onClick={runSearch} disabled={searching || !q.trim()}
            style={{ flex: "none", display: "flex", alignItems: "center",
              justifyContent: "center", minWidth: 48 }}>
            <SearchIcoMM size={17} />
          </window.MBtn>
        </div>

        {searchErr ? <MMErr msg={searchErr} onRetry={runSearch} /> : null}
        {searching ? window.MSpin() : null}

        {results !== null && !searching && !searchErr ? (
          results.length ? (
            <React.Fragment>
              <div className="m-row">
                <div className="m-fade" style={{ flex: 1 }}>
                  {results.length + " result" + (results.length === 1 ? "" : "s")}
                </div>
                <window.MChip onClick={() => { setResults(null); setQ(""); }}>Clear</window.MChip>
              </div>
              {results.map((r, i) =>
                noteRow("s" + i, r.title || r.path, r.snippet || r.path, null,
                  () => openNote(r.path)))}
            </React.Fragment>
          ) : (
            <window.MEmpty title="No matches" sub="Nothing in the vault for that search" />
          )
        ) : null}

        {results === null ? (
          <React.Fragment>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-3, #64748B)",
              textTransform: "uppercase", letterSpacing: "0.6px", marginTop: 4 }}>
              Recent notes
            </div>
            {recent.loading && !recent.data ? window.MSpin()
              : recent.error ? <MMErr msg={recent.error} onRetry={recent.refresh} />
              : !recentItems.length ? (
                <window.MEmpty title="No notes yet" sub="The vault is empty or offline" />
              ) : (
                recentItems.map((it) =>
                  noteRow(it.path, it.title || it.path, it.path,
                    window.timeAgoM(it.mtime), () => openNote(it.path)))
              )}
          </React.Fragment>
        ) : null}
      </div>
    </div>
  );
}

// ---- 4. Costs ---------------------------------------------------------------------

function MMCostsSheet(props) {
  const { data, error, loading, refresh } = window.useApiM("/api/cost/status", { interval: 30000 });
  const d = data || {};
  const today = d.today || {};
  const mtd = d.mtd || {};
  return (
    <div className="m-sheet">
      <window.MHeader title="Costs" sub="Claude + SMS spend" onBack={props.onBack} />
      <div className="m-sheet-body">
        {loading && !data ? window.MSpin()
          : error ? <MMErr msg={error} onRetry={refresh} />
          : (
            <React.Fragment>
              {d.capAlert || d.capWarn ? (
                <div className="m-card" style={{ borderColor: d.capAlert
                  ? "rgba(239,68,68,0.45)" : "rgba(245,158,11,0.45)" }}>
                  <div style={{ fontSize: 13, fontWeight: 700,
                    color: d.capAlert ? "#EF4444" : "#F59E0B" }}>
                    {(d.capAlert ? "OVER" : "80% of") + " the "
                      + MMUsd(d.monthlyCapUSD) + " monthly cap"}
                  </div>
                  <div className="m-fade" style={{ marginTop: 3 }}>
                    {"Month-to-date total " + MMUsd(mtd.totalUSD)}
                  </div>
                </div>
              ) : null}

              <div className="m-card">
                <div className="m-row">
                  <div className="m-kpi">
                    <div className="v">{MMUsd(today.usd)}</div>
                    <div className="l">TODAY</div>
                  </div>
                  <div className="m-kpi">
                    <div className="v">{MMUsd(mtd.totalUSD)}</div>
                    <div className="l">MONTH TOTAL</div>
                  </div>
                </div>
                <div className="m-row" style={{ marginTop: 6 }}>
                  <div className="m-kpi">
                    <div className="v">{MMUsd(mtd.claudeUSD)}</div>
                    <div className="l">CLAUDE MTD</div>
                  </div>
                  <div className="m-kpi">
                    <div className="v">{MMUsd(mtd.smsUSD)}</div>
                    <div className="l">{"SMS MTD (" + (mtd.sms || 0) + ")"}</div>
                  </div>
                </div>
              </div>

              <div className="m-card">
                <div className="m-row">
                  <div className="m-fade" style={{ flex: 1 }}>Today — Claude</div>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{MMUsd(today.claudeUSD)}</div>
                </div>
                <div className="m-row" style={{ marginTop: 8 }}>
                  <div className="m-fade" style={{ flex: 1 }}>Today — SMS sent</div>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{today.sms || 0}</div>
                </div>
                <div className="m-row" style={{ marginTop: 8 }}>
                  <div className="m-fade" style={{ flex: 1 }}>Fixed (prorated MTD)</div>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>
                    {MMUsd(mtd.fixedUSD)}
                    <span className="m-fade" style={{ fontWeight: 500 }}>
                      {" of " + MMUsd(d.fixedMonthlyUSD) + "/mo"}
                    </span>
                  </div>
                </div>
              </div>

              <div className="m-card">
                <div className="m-fade">
                  Fixed costs, SMS rate and the monthly cap — edit on desktop → Costs tab.
                </div>
              </div>
            </React.Fragment>
          )}
      </div>
    </div>
  );
}

// ---- 5. System health ----------------------------------------------------------------

function MMHealthSheet(props) {
  const { data, error, loading, refresh } = window.useApiM("/api/system/health", { interval: 15000 });
  const d = data || {};
  const loops = d.loops || [];
  const pct = (d.disk || {}).pctUsed;
  return (
    <div className="m-sheet">
      <window.MHeader title="System health" sub="Loop heartbeats · disk · alerts"
        onBack={props.onBack} />
      <div className="m-sheet-body">
        {loading && !data ? window.MSpin()
          : error ? <MMErr msg={error} onRetry={refresh} />
          : (
            <React.Fragment>
              <div className="m-card" style={{ borderColor: d.ok
                ? "rgba(34,197,94,0.35)" : "rgba(239,68,68,0.45)" }}>
                <div className="m-row">
                  <MMDot color={d.ok ? "#22C55E" : "#EF4444"} />
                  <div style={{ fontSize: 14, fontWeight: 800, flex: 1 }}>
                    {d.ok ? "All systems go" : "Attention needed"}
                  </div>
                  {d.paused ? <MMPill text="clocked out" color="#F59E0B" /> : null}
                </div>
                {!d.ok && (d.redLoops || []).length ? (
                  <div className="m-fade" style={{ marginTop: 5 }}>
                    {"Red: " + d.redLoops.join(", ")}
                  </div>
                ) : null}
                {!d.loopsEnabled ? (
                  <div className="m-fade" style={{ marginTop: 5 }}>
                    Loops disabled on this instance (UI-only) — staleness not flagged.
                  </div>
                ) : null}
              </div>

              {loops.length ? (
                loops.map((l) => {
                  const color = l.status === "red" ? "#EF4444"
                    : l.status === "amber" ? "#F59E0B" : "#22C55E";
                  const ago = window.timeAgoM(l.lastRun);
                  const ranLine = !l.lastRun ? "never ran"
                    : ago === "now" ? "just ran" : "ran " + ago + " ago";
                  return (
                    <div key={l.loop} className="m-list-item" style={{ minHeight: 48 }}>
                      <MMDot color={color} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13.5, fontWeight: 700 }}>
                          {l.label || l.loop}
                        </div>
                        <div className="m-fade" style={{ marginTop: 2 }}>
                          {ranLine
                            + (l.beats ? " · " + l.beats + " beats" : "")
                            + (l.errStreak ? " · " + l.errStreak + " errs" : "")}
                        </div>
                        {l.lastError ? (
                          <div style={{ color: "var(--red, #EF4444)", fontSize: 11,
                            marginTop: 2, overflow: "hidden", textOverflow: "ellipsis",
                            whiteSpace: "nowrap" }}>
                            {l.lastError}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  );
                })
              ) : (
                <window.MEmpty title="No heartbeats yet"
                  sub="Loops stamp a heartbeat every iteration — check the box" />
              )}

              <div className="m-list-item" style={{ minHeight: 48 }}>
                <MMDot color={d.diskOk === false ? "#EF4444" : "#22C55E"} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 700 }}>Disk</div>
                  <div className="m-fade" style={{ marginTop: 2 }}>
                    {pct !== null && pct !== undefined ? pct + "% used" : "usage unknown"}
                  </div>
                </div>
              </div>
              <div className="m-list-item" style={{ minHeight: 48 }}>
                <MMDot color={d.telegramConfigured ? "#22C55E" : "#64748B"} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 700 }}>Telegram alerts</div>
                  <div className="m-fade" style={{ marginTop: 2 }}>
                    {d.telegramConfigured ? "configured" : "not configured"}
                  </div>
                </div>
              </div>
            </React.Fragment>
          )}
      </div>
    </div>
  );
}

// ---- 6. Contracts (Wholesaler Toolkit Phase 4) ---------------------------------------
// Read/approve/track only — contract CREATION stays on the desktop Contracts tab.
// Colors + labels mirror toolkit_contracts.jsx lifecycle (sandbox DocuSign only).

const MM_CT_STATUS = {
  pending: { color: "#64748B", label: "review needed" },
  sent: { color: "#4F7CFF", label: "awaiting signature" },
  signed: { color: "#22C55E", label: "signed" },
  completed: { color: "#8B5CF6", label: "completed" },
  voided: { color: "#EF4444", label: "voided" },
};

function MMCtMeta(status) {
  const s = String(status || "pending").toLowerCase();
  return MM_CT_STATUS[s] || { color: "#64748B", label: s };
}

function MMCtField(props) {
  const v = props.value;
  const shown = v === null || v === undefined || v === "" ? "—"
    : props.money && !isNaN(Number(v)) ? window.fmtMoneyM(v)
    : String(v);
  return (
    <div className="m-row" style={{ marginTop: 8, alignItems: "flex-start" }}>
      <div className="m-fade" style={{ flex: "none", width: 128 }}>{props.label}</div>
      <div style={{ flex: 1, minWidth: 0, fontSize: 13, fontWeight: 600,
        textAlign: "right", overflowWrap: "break-word" }}>
        {shown}
      </div>
    </div>
  );
}

function MMContractDetail(props) {
  const c = props.contract;
  const [askOp, setAskOp] = useStateMM(false);
  const [opName, setOpName] = useStateMM("");
  const [busy, setBusy] = useStateMM(false);
  const [msg, setMsg] = useStateMM(null);   // {ok, text}

  if (!c) {
    return (
      <div className="m-sheet">
        <window.MHeader title="Contract" sub="Sandbox e-sign" onBack={props.onBack} />
        <div className="m-sheet-body">
          <window.MEmpty title="Contract not in ledger"
            sub="It may have changed — go back and pull the list again" />
        </div>
      </div>
    );
  }

  const status = String(c.status || "pending").toLowerCase();
  const meta = MMCtMeta(status);
  const prefill = c.prefill || {};
  const tabs = prefill.tabs || {};
  const isAssignment = c.templateType === "assignment";

  const runAction = async (fn, okText) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: okText });
    } catch (e) {
      setMsg({ ok: false, text: e.message || String(e) });
    } finally {
      setBusy(false);
      props.refresh();
    }
  };

  const doSend = () => {
    const op = opName.trim();
    if (!op) { setMsg({ ok: false, text: "Operator name is required to send." }); return; }
    if (!window.confirm("Send this contract for signature via the DocuSign sandbox?")) return;
    runAction(async () => {
      await window.apiPostM("/api/toolkit/contracts/send",
        { dealId: c.dealId, operatorId: op, reason: "approved from mobile" });
      setAskOp(false);
    }, "Sandbox envelope sent for signature.");
  };

  const doCheck = () => {
    if (!window.confirm("Check the DocuSign sandbox for this envelope's latest status?")) return;
    runAction(async () => {
      const r = await fetch("/api/toolkit/contracts/status?dealId=" + encodeURIComponent(c.dealId));
      const j = await r.json().catch(() => ({}));
      if (j && j.error) throw new Error(j.error);
    }, "Status checked — ledger refreshed.");
  };

  const doVoid = () => {
    if (!window.confirm("Void this contract in the sandbox? This can't be undone.")) return;
    runAction(async () => {
      await window.apiPostM("/api/toolkit/contracts/void",
        { dealId: c.dealId, reason: "voided from mobile" });
    }, "Contract voided.");
  };

  const ago = window.timeAgoM(c.updatedAt);
  const agoLine = !ago ? "" : ago === "now" ? " · just updated" : " · updated " + ago + " ago";
  return (
    <div className="m-sheet">
      <window.MHeader title={c.dealName || c.dealId}
        sub={c.templateName || c.templateType || "Contract"} onBack={props.onBack} />
      <div className="m-sheet-body">
        <div className="m-card">
          <div className="m-row" style={{ alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 0, fontSize: 14, fontWeight: 800,
              overflowWrap: "break-word" }}>
              {c.address || prefill.propertyAddress || "Address pending"}
            </div>
            <MMPill text={meta.label} color={meta.color} />
          </div>
          {isAssignment ? (
            <React.Fragment>
              <MMCtField label="Assignee (signs)" value={prefill.signerName} />
              <MMCtField label="Assignor" value={tabs.assignor_name} />
              <MMCtField label="Assignment fee" value={prefill.assignmentFee} money />
              <MMCtField label="Original purchase price" value={prefill.purchasePrice} money />
              <MMCtField label="Original contract date" value={tabs.original_contract_date} />
            </React.Fragment>
          ) : (
            <React.Fragment>
              <MMCtField label="Signer" value={prefill.signerName} />
              <MMCtField label="Signer email" value={prefill.signerEmail} />
              <MMCtField label="Property" value={prefill.propertyAddress} />
              <MMCtField label="Purchase price" value={prefill.purchasePrice} money />
            </React.Fragment>
          )}
        </div>

        {c.sendError ? (
          <div className="m-card" style={{ borderColor: "rgba(239,68,68,0.35)" }}>
            <div style={{ color: "var(--red, #EF4444)", fontSize: 12.5, fontWeight: 700 }}>
              Last send attempt
            </div>
            <div className="m-fade" style={{ marginTop: 3, overflowWrap: "break-word" }}>
              {String(c.sendError)}
            </div>
          </div>
        ) : null}

        {c.envelopeId ? (
          <div className="m-card">
            <div className="m-fade" style={{ fontSize: 11, overflowWrap: "break-word",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}>
              {"Sandbox envelope: " + c.envelopeId}
            </div>
          </div>
        ) : null}

        {msg ? (
          <div className="m-card" style={{ borderColor: msg.ok
            ? "rgba(34,197,94,0.35)" : "rgba(239,68,68,0.35)" }}>
            <div style={{ fontSize: 12.5, fontWeight: 700, overflowWrap: "break-word",
              color: msg.ok ? "#22C55E" : "#EF4444" }}>
              {msg.text}
            </div>
          </div>
        ) : null}

        {status === "pending" ? (
          <div className="m-card">
            {!askOp ? (
              <window.MBtn style={{ width: "100%", minHeight: 44 }} disabled={busy}
                onClick={() => { setAskOp(true); setMsg(null); }}>
                Send for signature
              </window.MBtn>
            ) : (
              <React.Fragment>
                <div className="m-fade">Operator name (required — logged on the ledger)</div>
                <input className="m-input" value={opName} placeholder="Your name"
                  style={{ width: "100%", marginTop: 6 }}
                  onChange={(e) => setOpName(e.target.value)} />
                <div className="m-row" style={{ marginTop: 10 }}>
                  <window.MBtn kind="ghost" style={{ flex: 1, minHeight: 44 }} disabled={busy}
                    onClick={() => setAskOp(false)}>
                    Cancel
                  </window.MBtn>
                  <window.MBtn style={{ flex: 1, minHeight: 44 }}
                    disabled={busy || !opName.trim()} onClick={doSend}>
                    {busy ? "Sending…" : "Confirm send"}
                  </window.MBtn>
                </div>
              </React.Fragment>
            )}
          </div>
        ) : null}

        {status === "sent" ? (
          <window.MBtn style={{ width: "100%", minHeight: 44 }} disabled={busy}
            onClick={doCheck}>
            {busy ? "Checking…" : "Check DocuSign status"}
          </window.MBtn>
        ) : null}

        {status === "pending" || status === "sent" ? (
          <window.MBtn kind="ghost" disabled={busy} onClick={doVoid}
            style={{ width: "100%", minHeight: 44, color: "#EF4444" }}>
            Void contract
          </window.MBtn>
        ) : null}

        <div className="m-card">
          <div className="m-fade">
            {"Sandbox e-sign only — draft new contracts on the desktop Contracts tab." + agoLine}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- 6b. Send Contract (quick send — upload YOUR contract, DocuSign emails it) -------
// Upload a PDF/DOCX template once, then: pick template → seller name/email →
// address/price → Send. DocuSign (sandbox) delivers the signing email; the
// envelope lands in the Contracts ledger for status tracking.

function MMSendContractSheet(props) {
  const tpl = window.useApiM("/api/toolkit/contracts/mytemplates", { interval: 0 });
  const templates = (tpl.data && tpl.data.templates) || [];
  const sandbox = tpl.data ? !!tpl.data.sandbox : true;
  const dsReady = tpl.data ? !!tpl.data.configured : false;

  const [picked, setPicked] = useStateMM(null);      // template id
  const [uploading, setUploading] = useStateMM(false);
  const [upErr, setUpErr] = useStateMM(null);
  const [sName, setSName] = useStateMM("");
  const [sEmail, setSEmail] = useStateMM("");
  const [addr, setAddr] = useStateMM("");
  const [price, setPrice] = useStateMM("");
  const [closing, setClosing] = useStateMM("");
  const [notes, setNotes] = useStateMM("");
  const [sending, setSending] = useStateMM(false);
  const [done, setDone] = useStateMM(null);          // {ok, text}

  const activeTpl = templates.find((t) => t.id === picked) || null;
  const canSend = activeTpl && sName.trim() && sEmail.includes("@") && !sending;

  function onFile(fileList) {
    const f = (fileList || [])[0];
    if (!f) return;
    setUploading(true); setUpErr(null);
    const rd = new FileReader();
    rd.onerror = () => { setUploading(false); setUpErr("Couldn't read that file."); };
    rd.onload = async () => {
      try {
        const r = await window.apiPostM("/api/toolkit/contracts/template/upload",
          { name: f.name.replace(/\.(pdf|docx?|)$/i, ""), file: rd.result });
        if (r && r.ok) { tpl.refresh(); setPicked(r.template.id); }
        else setUpErr((r && r.error) || "Upload failed.");
      } catch (e) { setUpErr(e.message || "Upload failed."); }
      setUploading(false);
    };
    rd.readAsDataURL(f);
  }

  async function delTpl(t) {
    if (!window.confirm('Delete template "' + t.name + '"?')) return;
    try {
      await window.apiPostM("/api/toolkit/contracts/template/delete", { id: t.id });
      if (picked === t.id) setPicked(null);
      tpl.refresh();
    } catch (e) { window.alert("Delete: " + e.message); }
  }

  async function doSend() {
    if (!canSend) return;
    const who = sName.trim() + " <" + sEmail.trim() + ">";
    const op = window.prompt(
      'Send "' + activeTpl.name + '" to ' + who +
      (addr.trim() ? " for " + addr.trim() : "") +
      "?\n\nDocuSign emails them the contract to sign. Type YOUR name to approve:");
    if (!op || !op.trim()) return;
    setSending(true); setDone(null);
    try {
      const r = await window.apiPostM("/api/toolkit/contracts/quicksend", {
        templateId: activeTpl.id, sellerName: sName.trim(), sellerEmail: sEmail.trim(),
        address: addr.trim(), price: price.trim(), closingDate: closing.trim(),
        notes: notes.trim(), operatorId: op.trim(),
      });
      if (r && r.ok) {
        setDone({ ok: true, text: "Sent — " + sEmail.trim() + " has the signing email. Track it in Contracts." });
        setSName(""); setSEmail(""); setAddr(""); setPrice(""); setClosing(""); setNotes("");
      } else setDone({ ok: false, text: (r && r.error) || "Send failed." });
    } catch (e) { setDone({ ok: false, text: e.message || "Send failed." }); }
    setSending(false);
  }

  return (
    <div className="m-sheet">
      <window.MHeader title="Send Contract" sub="Your template → DocuSign → seller's inbox"
        onBack={props.onBack} />
      <div className="m-sheet-body">

        {sandbox && (
          <div style={{ padding: "8px 12px", borderRadius: 12, fontSize: 11.5, fontWeight: 600,
            background: "rgba(245,158,11,0.10)", border: "1px solid rgba(245,158,11,0.35)",
            color: "var(--orange, #F59E0B)" }}>
            DocuSign sandbox — real signing emails, demo watermark. Production stays off until the key swap.
          </div>
        )}
        {tpl.data && !dsReady && (
          <div style={{ padding: "8px 12px", borderRadius: 12, fontSize: 11.5, fontWeight: 600,
            background: "rgba(239,68,68,0.10)", border: "1px solid rgba(239,68,68,0.35)",
            color: "var(--red, #EF4444)" }}>
            DocuSign isn't configured on this server — sends will fail until it is.
          </div>
        )}

        {/* 1 — pick or upload the contract template */}
        <window.MCard title="1 · Your contract">
          {tpl.loading && !tpl.data && <window.MSpin />}
          {templates.map((t) => (
            <div key={t.id} className="m-row"
              style={{ padding: "9px 2px", borderTop: "1px solid rgba(255,255,255,0.05)" }}>
              <button className="m-row" onClick={() => setPicked(t.id)}
                style={{ flex: 1, minWidth: 0, background: "none", border: "none",
                  color: "inherit", fontFamily: "inherit", textAlign: "left",
                  cursor: "pointer", gap: 10, padding: 0 }}>
                <span style={{ width: 20, height: 20, borderRadius: "50%", flex: "none",
                  border: "2px solid " + (picked === t.id ? "var(--blue, #4F7CFF)" : "rgba(255,255,255,0.25)"),
                  background: picked === t.id ? "var(--blue, #4F7CFF)" : "transparent",
                  display: "grid", placeItems: "center" }}>
                  {picked === t.id && <window.MIcons.Check size={12} />}
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "block", fontSize: 13.5, fontWeight: 700,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {t.name}
                  </span>
                  <span className="m-fade" style={{ fontSize: 11 }}>
                    {(t.ext || "pdf").toUpperCase()} · {Math.max(1, Math.round((t.size || 0) / 1024))} KB
                  </span>
                </span>
              </button>
              <button className="m-chip" style={{ flex: "none", minHeight: 36, padding: "6px 10px" }}
                onClick={() => delTpl(t)}>
                <window.MIcons.X size={13} />
              </button>
            </div>
          ))}
          {!tpl.loading && !templates.length && (
            <div className="m-fade" style={{ padding: "4px 0 10px" }}>
              No templates yet — upload the contract you already use (PDF or Word).
            </div>
          )}
          <label className="m-btn ghost" style={{ display: "flex", alignItems: "center",
            justifyContent: "center", gap: 8, marginTop: 10, cursor: "pointer" }}>
            <window.MIcons.Doc size={16} />
            {uploading ? "Uploading…" : "Upload contract template"}
            <input type="file" accept="application/pdf,.pdf,.doc,.docx" style={{ display: "none" }}
              onChange={(e) => { onFile(e.target.files); e.target.value = ""; }} />
          </label>
          {upErr && <div style={{ fontSize: 12.5, color: "var(--red, #EF4444)", marginTop: 8 }}>{upErr}</div>}
        </window.MCard>

        {/* 2 — the simple info */}
        <window.MCard title="2 · Seller + deal">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <input className="m-input" value={sName} placeholder="Seller full name"
              onChange={(e) => setSName(e.target.value)} />
            <input className="m-input" value={sEmail} type="email" inputMode="email"
              placeholder="Seller email (DocuSign delivers here)"
              onChange={(e) => setSEmail(e.target.value)} />
            <input className="m-input" value={addr} placeholder="Property address"
              onChange={(e) => setAddr(e.target.value)} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <input className="m-input" value={price} inputMode="numeric"
                placeholder="Price ($)" onChange={(e) => setPrice(e.target.value)} />
              <input className="m-input" value={closing}
                placeholder="Closing (e.g. 7/25)" onChange={(e) => setClosing(e.target.value)} />
            </div>
            <textarea className="m-input" rows={2} value={notes}
              placeholder="Note in the email (optional)"
              onChange={(e) => setNotes(e.target.value)} />
          </div>
        </window.MCard>

        {/* 3 — send */}
        <window.MBtn kind="ok" onClick={doSend} disabled={!canSend}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
            <window.MIcons.Send size={16} />
            {sending ? "Sending…" : "Email contract for signature"}
          </span>
        </window.MBtn>
        {done && (
          <div style={{ fontSize: 12.5, fontWeight: 600,
            color: done.ok ? "var(--green, #22C55E)" : "var(--red, #EF4444)" }}>
            {done.ok ? "✓ " : ""}{done.text}
          </div>
        )}
        <div className="m-fade" style={{ fontSize: 11 }}>
          Price + closing date ride in the email; the seller signs free-form on your
          document. Every send needs your name — nothing goes out on its own.
        </div>
      </div>
    </div>
  );
}

function MMContractsSheet(props) {
  const { data, error, loading, refresh } =
    window.useApiM("/api/toolkit/contracts/list", { interval: 30000 });
  const [openId, setOpenId] = useStateMM(null);
  const rows = (data && data.contracts) || [];

  // Detail view (nested — back returns to the ledger list).
  if (openId !== null) {
    const cur = rows.find((c) => String(c.dealId) === String(openId)) || null;
    return <MMContractDetail contract={cur} refresh={refresh}
      onBack={() => setOpenId(null)} />;
  }

  return (
    <div className="m-sheet">
      <window.MHeader title="Contracts" sub="Sandbox e-sign ledger + status"
        onBack={props.onBack} />
      <div className="m-sheet-body">
        {loading && !data ? window.MSpin()
          : error ? <MMErr msg={error} onRetry={refresh} />
          : !rows.length ? (
            <window.MEmpty title="No contracts yet"
              sub="Draft a sandbox contract on the desktop Contracts tab" />
          ) : (
            rows.map((c) => {
              const meta = MMCtMeta(c.status);
              return (
                <button key={c.dealId} className="m-list-item"
                  style={{ width: "100%", minHeight: 56, textAlign: "left", cursor: "pointer",
                    fontFamily: "inherit", color: "inherit" }}
                  onClick={() => setOpenId(c.dealId)}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {c.dealName || c.dealId}
                    </div>
                    <div className="m-fade" style={{ marginTop: 2, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {[c.templateName || c.templateType, c.address].filter(Boolean).join(" · ")
                        || "Contract"}
                    </div>
                  </div>
                  <div style={{ flex: "none", display: "flex", flexDirection: "column",
                    alignItems: "flex-end", gap: 4 }}>
                    <MMPill text={meta.label} color={meta.color} />
                    <span className="m-fade">{window.timeAgoM(c.updatedAt)}</span>
                  </div>
                </button>
              );
            })
          )}
      </div>
    </div>
  );
}

// ---- the More menu -----------------------------------------------------------------

const MM_MENU = [
  { key: "brief", label: "Daily brief", sub: "Morning ops pulse → Telegram, from anywhere", ico: "Chat" },
  { key: "sendcontract", label: "Send Contract", sub: "Your template → DocuSign → seller email", ico: "Send" },
  { key: "buyers", label: "Buyers / Dispo", sub: "Cash-buyer roster + dispo worklist", ico: "User" },
  { key: "deals", label: "Deals", sub: "Deal sheets, MAO / offers, contracts", ico: "Doc" },
  { key: "contracts", label: "Contracts", sub: "Sandbox e-sign ledger + status", ico: "Doc" },
  { key: "brain", label: "Brain", sub: "Search + read the Obsidian vault", ico: "Brain" },
  { key: "costs", label: "Costs", sub: "Claude + SMS spend, monthly cap", ico: "Dollar" },
  { key: "health", label: "System health", sub: "Loop heartbeats, disk, alerts", ico: "Heart" },
];

// ---- Daily brief — the run-from-anywhere morning pulse -------------------------------
function MMBriefText(props) {
  // The API text carries Telegram HTML (<b>) + escaped &amp;/&lt;/&gt; — render it as
  // plain text for the mobile preview.
  const t = String(props.text || "")
    .replace(/<\/?b>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  return (
    <div style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.5 }}>{t}</div>
  );
}

function MMBriefSheet(props) {
  const { data, error, loading, refresh } = window.useApiM("/api/brief", { interval: 0 });
  const cfg = (data && data.config) || {};
  const [busy, setBusy] = useStateMM(null);   // "toggle" | "hour" | "send"
  const [msg, setMsg] = useStateMM(null);      // {ok, text}
  const HOURS = [6, 7, 8, 9, 10, 18];

  async function saveCfg(patch, tag) {
    setBusy(tag); setMsg(null);
    try { await window.apiPostM("/api/brief/config", patch); refresh(); }
    catch (e) { setMsg({ ok: false, text: "Save failed: " + (e.message || "error") }); }
    setBusy(null);
  }
  async function sendNow() {
    setBusy("send"); setMsg(null);
    try {
      const r = await window.apiPostM("/api/brief/send", {});
      setMsg(r && r.sent
        ? { ok: true, text: "Sent to Telegram ✓" }
        : { ok: false, text: (r && r.note) ? ("Not sent: " + r.note) : "Not sent — check Telegram config" });
      refresh();
    } catch (e) { setMsg({ ok: false, text: "Send failed: " + (e.message || "error") }); }
    setBusy(null);
  }

  const lastSent = cfg.lastSentAt
    ? window.timeAgoM(cfg.lastSentAt) : "not yet today";

  return (
    <div className="m-sheet">
      <window.MHeader title="Daily brief" sub="Morning ops pulse → Telegram" onBack={props.onBack} />
      <div className="m-sheet-body">
        {loading && !data ? window.MSpin()
          : error ? <MMErr msg={error} onRetry={refresh} />
          : (
            <React.Fragment>
              <div className="m-card">
                <div className="m-row">
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 700 }}>Auto-send each morning</div>
                    <div className="m-fade" style={{ marginTop: 2 }}>
                      {cfg.enabled ? "On — pushes daily to your Telegram" : "Off — pull it here anytime"}
                    </div>
                  </div>
                  <window.MBtn kind={cfg.enabled ? "ok" : "ghost"} disabled={busy === "toggle"}
                    style={{ flex: "none", padding: "10px 14px" }}
                    onClick={() => saveCfg({ enabled: !cfg.enabled }, "toggle")}>
                    {busy === "toggle" ? "…" : (cfg.enabled ? "On" : "Off")}
                  </window.MBtn>
                </div>
                <div style={{ marginTop: 12 }}>
                  <div className="m-fade" style={{ marginBottom: 6 }}>
                    Send hour (your time{cfg.localTime ? " · now " + cfg.localTime : ""})
                  </div>
                  <div className="m-seg">
                    {HOURS.map((h) => (
                      <window.MChip key={h} active={cfg.hour === h} onClick={() => saveCfg({ hour: h }, "hour")}>
                        {(h % 12 || 12) + (h < 12 ? "a" : "p")}
                      </window.MChip>
                    ))}
                  </div>
                </div>
              </div>

              <div className="m-card">
                <div className="m-row" style={{ marginBottom: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, flex: 1 }}>Today's brief</span>
                  <span className="m-fade" style={{ fontSize: 11 }}>last push {lastSent}</span>
                </div>
                <MMBriefText text={data && data.text} />
              </div>

              <window.MBtn kind="ok" onClick={sendNow} disabled={busy === "send"}>
                {busy === "send" ? "Sending…" : "Send me the brief now"}
              </window.MBtn>
              {msg && (
                <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 8,
                  color: msg.ok ? "var(--green, #22C55E)" : "var(--red, #EF4444)" }}>
                  {msg.ok ? "✓ " : ""}{msg.text}
                </div>
              )}
              <div className="m-fade" style={{ fontSize: 11, marginTop: 4 }}>
                Delivered by the box's Telegram bot — reaches you anywhere, no tunnel needed.
              </div>
            </React.Fragment>
          )}
      </div>
    </div>
  );
}

function MMorePage() {
  const [open, setOpen] = useStateMM(null);
  const close = () => setOpen(null);
  return (
    <React.Fragment>
      <window.MHeader title="More" sub="Send Contract · Buyers · Deals · Contracts · Brain · Health" />
      <div className="m-content">
        {MM_MENU.map((item) => {
          const Ico = window.MIcons[item.ico] || window.MIcons.More;
          return (
            <button key={item.key} className="m-list-item"
              style={{ width: "100%", minHeight: 56, textAlign: "left", cursor: "pointer",
                fontFamily: "inherit", color: "inherit" }}
              onClick={() => setOpen(item.key)}>
              <div style={{ width: 38, height: 38, borderRadius: 12, flex: "none",
                background: "rgba(79,124,255,0.12)", color: "var(--blue, #4F7CFF)",
                display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Ico size={19} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 700 }}>{item.label}</div>
                <div className="m-fade" style={{ marginTop: 1 }}>{item.sub}</div>
              </div>
              <span style={{ color: "var(--text-3, #64748B)", fontSize: 22, fontWeight: 600,
                flex: "none", lineHeight: 1 }}>
                ›
              </span>
            </button>
          );
        })}

        <window.MCard>
          <div style={{ textAlign: "center" }}>
            <div className="m-fade" style={{ fontWeight: 600 }}>
              FORGE Mobile v1 · full controls on the desktop dashboard
            </div>
            <div className="m-fade" style={{ marginTop: 4 }}>
              Runs on the 24/7 box — open via SSH tunnel → localhost:7799
            </div>
          </div>
        </window.MCard>
      </div>

      {open === "brief" ? <MMBriefSheet onBack={close} /> : null}
      {open === "sendcontract" ? <MMSendContractSheet onBack={close} /> : null}
      {open === "buyers" ? <MMBuyersSheet onBack={close} /> : null}
      {open === "deals" ? <MMDealsSheet onBack={close} /> : null}
      {open === "contracts" ? <MMContractsSheet onBack={close} /> : null}
      {open === "brain" ? <MMBrainSheet onBack={close} /> : null}
      {open === "costs" ? <MMCostsSheet onBack={close} /> : null}
      {open === "health" ? <MMHealthSheet onBack={close} /> : null}
    </React.Fragment>
  );
}

Object.assign(window, { MMorePage });
