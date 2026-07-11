// Wholesaler Toolkit — Deal Calculator panels (Phase 1).
// Mounted inside DealCalcPage (pages.jsx). Math lives in toolkit_calc.py —
// this posts inputs to /api/toolkit/calc/eval (debounced) and renders results.
// Hook aliases: useStateTk/useEffectTk/useRefTk. Globals prefixed Tk.
const { useState: useStateTk, useEffect: useEffectTk, useRef: useRefTk } = React;

const TK_BOX = { background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 13, padding: 16 };
const TK_TIER_LABEL = { light: "Light", moderate: "Moderate", heavy: "Heavy", full_gut: "Full gut" };

function TkIn(label, value, onChange, opts) {
  opts = opts || {};
  return (
    <div style={{ flex: 1, minWidth: 130 }}>
      <div className="faint" style={{ fontSize: 11.5, marginBottom: 5 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "center", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 10, padding: "0 11px" }}>
        {opts.prefix && <span className="faint" style={{ fontSize: 14 }}>{opts.prefix}</span>}
        <input type="number" value={value} onChange={(e) => onChange(e.target.value)} placeholder={opts.placeholder || "0"}
          style={{ flex: 1, background: "none", border: "none", outline: "none", color: "var(--text)", fontSize: 14, fontWeight: 600, padding: "10px 6px", width: "100%" }} />
        {opts.suffix && <span className="faint" style={{ fontSize: 14 }}>{opts.suffix}</span>}
      </div>
    </div>
  );
}

function TkRow(label, val, opts) {
  opts = opts || {};
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
      <span className="faint">{label}</span>
      <span className="tabnum" style={{ fontWeight: opts.bold ? 700 : 500, color: opts.color || "var(--text)" }}>{val}</span>
    </div>
  );
}

function TkCalcPanels(props) {
  const Icons = window.Icons;
  const M = window.fmtMoney;
  // repair estimator
  const [sqft, setSqft] = useStateTk("");
  const [tier, setTier] = useStateTk("");
  const [rates, setRates] = useStateTk(null);
  const [rateDraft, setRateDraft] = useStateTk({});
  const [showRates, setShowRates] = useStateTk(false);
  // creative finance
  const [mode, setMode] = useStateTk("subto");
  const [st, setSt] = useStateTk({ piti: "", rent: "", balance: "", entryFee: "", arrears: "", closingCosts: "" });
  const [sf, setSf] = useStateTk({ price: "", down: "", ratePct: "6", termYears: "30", balloonYears: "" });
  const [nv, setNv] = useStateTk({ sellerPrice: "", sellCostPct: "8" });
  // dual view
  const [view, setView] = useStateTk("internal");
  const [buyerPrice, setBuyerPrice] = useStateTk("");
  const [holding, setHolding] = useStateTk("");
  // results
  const [res, setRes] = useStateTk({});
  const [saveMsg, setSaveMsg] = useStateTk(null);
  const [saving, setSaving] = useStateTk(false);
  const timerTk = useRefTk(null);
  // AI ARV finder
  const [arvAddr, setArvAddr] = useStateTk("");
  const [arvBusy, setArvBusy] = useStateTk(false);
  const [arvRes, setArvRes] = useStateTk(null);
  const [arvErr, setArvErr] = useStateTk(null);

  useEffectTk(() => {
    fetch("/api/toolkit/calc/config").then((r) => r.json())
      .then((c) => { setRates(c.rates || null); setRateDraft(c.rates || {}); })
      .catch(() => {});
  }, []);

  const bodyTk = () => ({
    arv: props.arv, repairs: props.repairs, fee: props.fee, pct: props.pct,
    asking: props.asking, sqft, tier, buyerPrice, holding,
    subto: st, sellerFinance: sf, novation: nv,
  });

  useEffectTk(() => {
    if (timerTk.current) clearTimeout(timerTk.current);
    timerTk.current = setTimeout(async () => {
      try { setRes(await window.apiPost("/api/toolkit/calc/eval", bodyTk())); }
      catch (e) { /* server down — panels just stay empty */ }
    }, 400);
    return () => clearTimeout(timerTk.current);
  }, [props.arv, props.repairs, props.fee, props.pct, props.asking,
      sqft, tier, buyerPrice, holding, st, sf, nv]);

  async function saveRates() {
    try {
      const r = await window.apiPost("/api/toolkit/calc/rates", { rates: rateDraft });
      if (r && r.rates) { setRates(r.rates); setShowRates(false); }
    } catch (e) {}
  }

  async function saveSnapshot() {
    if (!props.contactId || saving) return;
    setSaving(true); setSaveMsg(null);
    try {
      const r = await window.apiPost("/api/toolkit/calc/save", { contactId: props.contactId, ...bodyTk() });
      setSaveMsg(r && r.ok ? { ok: true, t: "Saved to deal record." } : { ok: false, t: (r && r.error) || "save failed" });
    } catch (e) { setSaveMsg({ ok: false, t: "save failed: " + (e.message || "error") }); }
    finally { setSaving(false); }
  }

  const rep = res.repair && !res.repair.error ? res.repair : null;
  const sub = res.subto && !res.subto.error ? res.subto : null;
  const fin = res.sellerFinance && !res.sellerFinance.error ? res.sellerFinance : null;
  const nov = res.novation && !res.novation.error ? res.novation : null;
  const itn = res.internal || null;
  const byr = res.buyer && !res.buyer.error ? res.buyer : null;
  const setK = (setter) => (k) => (v) => setter((p) => ({ ...p, [k]: v }));
  const stK = setK(setSt), sfK = setK(setSf), nvK = setK(setNv);

  // AI ARV — Claude + web search comps for the address (~20-60s round trip).
  async function tkFindArv() {
    const a = arvAddr.trim();
    if (a.length < 8 || arvBusy) return;
    setArvBusy(true); setArvErr(null); setArvRes(null);
    try {
      const r = await window.apiPost("/api/toolkit/calc/arv", { address: a, sqft });
      if (r && r.ok) setArvRes(r);
      else setArvErr((r && r.error) || "No number came back — try again.");
    } catch (e) { setArvErr(e.message || "ARV lookup failed"); }
    setArvBusy(false);
  }
  const arvConfColor = arvRes
    ? (arvRes.confidence === "high" ? "var(--green)" : arvRes.confidence === "medium" ? "var(--orange)" : "var(--red)")
    : "var(--text-3)";

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16, alignItems: "start" }}>

      {/* ---- AI ARV finder ---- */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <Icons.Search size={15} /> AI ARV finder
          <span className="faint" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.4, marginLeft: "auto" }}>LIVE COMPS</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input type="text" value={arvAddr} onChange={(e) => setArvAddr(e.target.value)}
            placeholder="123 Main St, Wilmington, DE"
            style={{ flex: 1, background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 10,
              color: "var(--text)", fontSize: 13.5, padding: "10px 12px", outline: "none" }} />
          <button className="btn" onClick={tkFindArv} disabled={arvBusy || arvAddr.trim().length < 8}>
            {arvBusy ? "Searching…" : "Find ARV"}
          </button>
        </div>
        {arvErr && <div style={{ fontSize: 12.5, color: "var(--red)" }}>{arvErr}</div>}
        {arvRes && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <span className="tabnum" style={{ fontSize: 26, fontWeight: 800, color: "var(--green)" }}>{M(arvRes.arv)}</span>
              {(arvRes.low || arvRes.high) && (
                <span className="faint" style={{ fontSize: 12 }}>{M(arvRes.low || arvRes.arv)} – {M(arvRes.high || arvRes.arv)}</span>
              )}
              <span style={{ marginLeft: "auto", fontSize: 10, fontWeight: 800, textTransform: "uppercase",
                letterSpacing: 0.5, color: arvConfColor }}>{arvRes.confidence} confidence</span>
            </div>
            {arvRes.summary && <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>{arvRes.summary}</div>}
            {(arvRes.comps || []).map((c, i) => TkRow(c.address + (c.note ? " · " + c.note : ""), M(c.price)))}
            {props.onApplyArv && (
              <button className="btn" onClick={() => props.onApplyArv(arvRes.arv)}>
                Apply {M(arvRes.arv)} → ARV
              </button>
            )}
            <div className="faint" style={{ fontSize: 11 }}>Internal prep number — verify before you offer.</div>
          </div>
        )}
        {!arvRes && !arvErr && !arvBusy && (
          <div className="faint" style={{ fontSize: 12 }}>Type the property address — AI pulls live comps and hands back a conservative ARV.</div>
        )}
      </div>

      {/* ---- Repair estimator ---- */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <Icons.Sliders size={15} /> Repair estimator
          <button className="link" onClick={() => setShowRates((s) => !s)} style={{ fontSize: 11, marginLeft: "auto" }}>
            {showRates ? "hide rates" : "edit $/sqft"}
          </button>
        </div>
        {showRates && rates && (
          <div style={TK_BOX}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {Object.keys(rates).map((k) => (
                <React.Fragment key={k}>
                  {TkIn(TK_TIER_LABEL[k] || k, rateDraft[k] == null ? rates[k] : rateDraft[k],
                    (v) => setRateDraft((p) => ({ ...p, [k]: v })), { prefix: "$", suffix: "/sqft" })}
                </React.Fragment>
              ))}
            </div>
            <button className="tab" onClick={saveRates} style={{ marginTop: 10, fontWeight: 600 }}>Save rates</button>
          </div>
        )}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {TkIn("Square footage", sqft, setSqft, { suffix: "sqft" })}
        </div>
        <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
          {(rates ? Object.keys(rates) : []).map((k) => (
            <button key={k} className={"tab" + (tier === k ? " active" : "")} onClick={() => setTier(k)} style={{ fontSize: 12 }}>
              {TK_TIER_LABEL[k] || k} · ${rates[k]}/sqft
            </button>
          ))}
        </div>
        {rep ? (
          <div style={TK_BOX}>
            {TkRow(`${TK_TIER_LABEL[rep.tier] || rep.tier} · ${rep.sqft} sqft × $${rep.perSqft}`, M(rep.total), { bold: true, color: "var(--orange)" })}
            {props.onApplyRepairs && (
              <button className="tab" onClick={() => props.onApplyRepairs(rep.total)} style={{ marginTop: 10, fontWeight: 600 }}>
                Apply {M(rep.total)} → repairs
              </button>
            )}
          </div>
        ) : (
          <div className="faint" style={{ fontSize: 12 }}>Enter sqft + pick a condition tier.</div>
        )}
      </div>

      {/* ---- Creative finance ---- */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <Icons.Dollar size={15} /> Creative finance
        </div>
        <div style={{ display: "flex", gap: 7 }}>
          {[["subto", "Sub-To"], ["sellerfi", "Seller finance"], ["novation", "Novation"]].map(([k, lbl]) => (
            <button key={k} className={"tab" + (mode === k ? " active" : "")} onClick={() => setMode(k)} style={{ fontSize: 12 }}>{lbl}</button>
          ))}
        </div>
        {mode === "subto" && (
          <React.Fragment>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Monthly PITI", st.piti, stK("piti"), { prefix: "$" })}
              {TkIn("Market rent", st.rent, stK("rent"), { prefix: "$" })}
              {TkIn("Loan balance", st.balance, stK("balance"), { prefix: "$" })}
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Cash to seller", st.entryFee, stK("entryFee"), { prefix: "$" })}
              {TkIn("Arrears", st.arrears, stK("arrears"), { prefix: "$" })}
              {TkIn("Closing costs", st.closingCosts, stK("closingCosts"), { prefix: "$" })}
            </div>
            {sub && (
              <div style={{ ...TK_BOX, display: "flex", flexDirection: "column", gap: 6 }}>
                {TkRow("Entry cash", M(sub.entryCash))}
                {TkRow("Monthly cash flow", M(sub.monthlyFlow), { bold: true, color: sub.monthlyFlow >= 0 ? "var(--green)" : "var(--red)" })}
                {TkRow("Annual", M(sub.annualFlow))}
                {sub.cashOnCash != null && TkRow("Cash-on-cash", sub.cashOnCash + "%", { bold: true, color: "var(--green)" })}
              </div>
            )}
          </React.Fragment>
        )}
        {mode === "sellerfi" && (
          <React.Fragment>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Price", sf.price, sfK("price"), { prefix: "$" })}
              {TkIn("Down", sf.down, sfK("down"), { prefix: "$" })}
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Rate", sf.ratePct, sfK("ratePct"), { suffix: "%" })}
              {TkIn("Term (years)", sf.termYears, sfK("termYears"), { suffix: "yr" })}
              {TkIn("Balloon (years)", sf.balloonYears, sfK("balloonYears"), { suffix: "yr", placeholder: "none" })}
            </div>
            {fin && (
              <div style={{ ...TK_BOX, display: "flex", flexDirection: "column", gap: 6 }}>
                {TkRow("Note amount", M(fin.loan))}
                {TkRow("Monthly payment", M(fin.monthly), { bold: true, color: "var(--blue)" })}
                {TkRow("Total interest", M(fin.totalInterest))}
                {fin.balloonBalance != null && TkRow(`Balloon @ ${Math.round(fin.balloonMonths / 12)}yr`, M(fin.balloonBalance), { bold: true, color: "var(--orange)" })}
              </div>
            )}
          </React.Fragment>
        )}
        {mode === "novation" && (
          <React.Fragment>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Seller nets", nv.sellerPrice, nvK("sellerPrice"), { prefix: "$" })}
              {TkIn("Selling costs", nv.sellCostPct, nvK("sellCostPct"), { suffix: "%" })}
            </div>
            <div className="faint" style={{ fontSize: 11.5 }}>Uses ARV + repairs from the calculator above.</div>
            {nov && (
              <div style={{ ...TK_BOX, display: "flex", flexDirection: "column", gap: 6 }}>
                {TkRow("ARV − repairs − costs", M(nov.arv - nov.repairs - nov.sellingCosts))}
                {TkRow("Seller nets", "−" + M(nov.sellerPrice), { color: "var(--red)" })}
                {TkRow("Novation profit", M(nov.profit), { bold: true, color: nov.profit >= 0 ? "var(--green)" : "var(--red)" })}
                {nov.vsWholesale != null && TkRow("vs wholesale fee", (nov.vsWholesale >= 0 ? "+" : "") + M(nov.vsWholesale), { color: nov.vsWholesale >= 0 ? "var(--green)" : "var(--red)" })}
              </div>
            )}
          </React.Fragment>
        )}
      </div>

      {/* ---- Dual-view ROI ---- */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <Icons.Target size={15} /> Deal views
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <button className={"tab" + (view === "internal" ? " active" : "")} onClick={() => setView("internal")} style={{ fontSize: 11.5 }}>Internal</button>
            <button className={"tab" + (view === "buyer" ? " active" : "")} onClick={() => setView("buyer")} style={{ fontSize: 11.5 }}>Buyer sees</button>
          </div>
        </div>
        {view === "internal" && (itn ? (
          <div style={{ ...TK_BOX, display: "flex", flexDirection: "column", gap: 6 }}>
            {TkRow("MAO (you pay seller)", M(itn.mao), { bold: true, color: "var(--green)" })}
            {TkRow("Assignment fee", M(itn.fee))}
            {TkRow("Buyer pays", M(itn.buyerPrice), { bold: true })}
            {itn.spread != null && TkRow("Spread vs asking", (itn.spread >= 0 ? "+" : "") + M(itn.spread), { color: itn.spread >= 0 ? "var(--green)" : "var(--red)" })}
          </div>
        ) : <div className="faint" style={{ fontSize: 12 }}>Enter an ARV above.</div>)}
        {view === "buyer" && (
          <React.Fragment>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {TkIn("Buyer price", buyerPrice, setBuyerPrice, { prefix: "$", placeholder: itn ? String(Math.round(itn.buyerPrice)) : "MAO + fee" })}
              {TkIn("Holding costs", holding, setHolding, { prefix: "$" })}
            </div>
            {byr ? (
              <div style={{ ...TK_BOX, display: "flex", flexDirection: "column", gap: 6 }}>
                {TkRow("ARV (resale)", M(byr.arv))}
                {TkRow("Purchase", "−" + M(byr.purchase), { color: "var(--red)" })}
                {TkRow("Repairs", "−" + M(byr.repairs), { color: "var(--red)" })}
                {TkRow("Closing (buy + sell)", "−" + M(byr.buyClosing + byr.sellClosing), { color: "var(--red)" })}
                {byr.holding > 0 && TkRow("Holding", "−" + M(byr.holding), { color: "var(--red)" })}
                {TkRow("Buyer profit", M(byr.profit), { bold: true, color: byr.profit >= 0 ? "var(--green)" : "var(--red)" })}
                {byr.roiPct != null && TkRow("Cash-in ROI", byr.roiPct + "%", { bold: true, color: "var(--green)" })}
              </div>
            ) : <div className="faint" style={{ fontSize: 12 }}>Enter an ARV above.</div>}
            <div className="faint" style={{ fontSize: 11 }}>This is the sheet buyers see — one purchase number, your fee never shown. Feeds Buyer Blast deal sheets (Phase 2).</div>
          </React.Fragment>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <button className="tab" onClick={saveSnapshot} disabled={!props.contactId || saving} style={{ fontWeight: 600, opacity: props.contactId ? 1 : 0.5 }}>
            {saving ? "Saving…" : "Save scenario to deal"}
          </button>
          {!props.contactId && <span className="faint" style={{ fontSize: 11 }}>pick a homeowner above to save</span>}
          {saveMsg && <span style={{ fontSize: 12, fontWeight: 600, color: saveMsg.ok ? "var(--green)" : "var(--red)" }}>{saveMsg.ok ? "✓ " : ""}{saveMsg.t}</span>}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { TkCalcPanels });
