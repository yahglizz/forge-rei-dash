// FORGE Mobile — Deal Calculator tab. Mirrors desktop DealCalcPage math
// (pages.jsx) + Wholesaler Toolkit panels (toolkit_calc.jsx) in one column.
// Hook aliases for this file: MK. All top-level identifiers prefixed MK.
const { useState: useStateMK, useEffect: useEffectMK, useRef: useRefMK } = React;

// Same flat presets as desktop REPAIR_PRESETS (pages.jsx).
const MK_PRESETS = [
  { label: "Light", amt: 10000, hint: "paint, carpet, fixtures" },
  { label: "Moderate", amt: 25000, hint: "kitchen/bath, flooring" },
  { label: "Heavy", amt: 50000, hint: "roof, HVAC, systems" },
  { label: "Full gut", amt: 90000, hint: "down to studs" },
];
const MK_TIER_LABEL = { light: "Light", moderate: "Moderate", heavy: "Heavy", full_gut: "Full gut" };
const MK_MODES = [["subto", "Sub-To"], ["sellerfi", "Seller finance"], ["novation", "Novation"]];

function MKNum(v) { const x = parseFloat(v); return isNaN(x) ? 0 : x; }

function MKIn(label, value, onChange, opts) {
  opts = opts || {};
  return (
    <label style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 5 }}>
      <span className="m-fade">{label}</span>
      <input className="m-input" type="number" inputMode={opts.inputMode || "numeric"}
        value={value} placeholder={opts.placeholder || "0"}
        onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function MKRow(label, val, opts) {
  opts = opts || {};
  return (
    <div className="m-row" style={{ justifyContent: "space-between", minHeight: 22, borderTop: opts.top ? "1px solid rgba(255,255,255,0.07)" : "none", paddingTop: opts.top ? 8 : 0 }}>
      <span className="m-fade" style={{ fontSize: 12.5 }}>{label}</span>
      <span style={{ fontSize: 13.5, fontWeight: opts.bold ? 800 : 600, color: opts.color || "var(--text, #F1F5FB)" }}>{val}</span>
    </div>
  );
}

function MCalcPage() {
  const M = window.fmtMoneyM;
  const MKI = window.MIcons;

  // ---- MAO card state (desktop parity: fee 10000, pct 70) ----
  const [arv, setArv] = useStateMK("");
  const [repairs, setRepairs] = useStateMK("");
  const [fee, setFee] = useStateMK("10000");
  const [pct, setPct] = useStateMK("70");
  const [asking, setAsking] = useStateMK("");

  // ---- Toolkit state (same field names as toolkit_calc.jsx) ----
  const [sqft, setSqft] = useStateMK("");
  const [tier, setTier] = useStateMK("");
  const [mode, setMode] = useStateMK("subto");
  const [st, setSt] = useStateMK({ piti: "", rent: "", balance: "", entryFee: "", arrears: "", closingCosts: "" });
  const [sf, setSf] = useStateMK({ price: "", down: "", ratePct: "6", termYears: "30", balloonYears: "" });
  const [nv, setNv] = useStateMK({ sellerPrice: "", sellCostPct: "8" });
  const [view, setView] = useStateMK("internal");
  const [buyerPrice, setBuyerPrice] = useStateMK("");
  const [holding, setHolding] = useStateMK("");
  const [res, setRes] = useStateMK({});
  const [evalErr, setEvalErr] = useStateMK(null);
  const evalTimerMK = useRefMK(null);

  // ---- Send-offer state ----
  const [cq, setCq] = useStateMK("");
  const [cres, setCres] = useStateMK([]);
  const [csearching, setCsearching] = useStateMK(false);
  const [cerr, setCerr] = useStateMK(null);
  const [picked, setPicked] = useStateMK(null);
  const [offer, setOffer] = useStateMK("");
  const [offerTouched, setOfferTouched] = useStateMK(false);
  const [sending, setSending] = useStateMK(false);
  const [sendMsg, setSendMsg] = useStateMK(null);
  const [saving, setSaving] = useStateMK(false);
  const [saveMsg, setSaveMsg] = useStateMK(null);

  // ---- AI ARV finder state ----
  const [arvAddr, setArvAddr] = useStateMK("");
  const [arvBusy, setArvBusy] = useStateMK(false);
  const [arvRes, setArvRes] = useStateMK(null);
  const [arvErr, setArvErr] = useStateMK(null);

  // Tier rates/hints for the repair estimator.
  const cfg = window.useApiM("/api/toolkit/calc/config");
  const rates = (cfg.data && cfg.data.rates) || null;
  const tiers = (cfg.data && cfg.data.tiers) || (rates ? Object.keys(rates) : []);
  const hints = (cfg.data && cfg.data.hints) || {};

  // ---- MAO math — EXACT desktop formula + verdict thresholds ----
  const arvN = MKNum(arv), repN = MKNum(repairs), feeN = MKNum(fee), pctN = MKNum(pct), askN = MKNum(asking);
  const mao = Math.max(0, arvN * (pctN / 100) - repN - feeN);
  const spread = askN > 0 ? mao - askN : null;

  let verdict = null;
  if (arvN > 0 && askN > 0) {
    if (askN <= mao) verdict = { t: "GO", c: "#22C55E", msg: "Seller's at/under your max. Lock it up." };
    else if (askN <= mao + 15000) verdict = { t: "NEGOTIATE", c: "#F59E0B", msg: `They're ${M(askN - mao)} over. Anchor low, counter near ${M(mao)}.` };
    else verdict = { t: "PASS", c: "#EF4444", msg: `They're ${M(askN - mao)} over max. Don't chase it.` };
  }

  // ---- ONE debounced eval covering repair / creative / views cards ----
  const evalBody = () => ({
    arv, repairs, fee, pct, asking, sqft, tier, buyerPrice, holding,
    subto: st, sellerFinance: sf, novation: nv,
  });
  useEffectMK(() => {
    if (evalTimerMK.current) clearTimeout(evalTimerMK.current);
    const hasAny = arvN > 0 || (MKNum(sqft) > 0 && tier) || MKNum(st.piti) > 0 ||
      MKNum(sf.price) > 0 || MKNum(nv.sellerPrice) > 0;
    if (!hasAny) { setRes({}); setEvalErr(null); return; }
    evalTimerMK.current = setTimeout(async () => {
      try { setRes(await window.apiPostM("/api/toolkit/calc/eval", evalBody())); setEvalErr(null); }
      catch (e) { setEvalErr(e.message || "calc server unreachable"); }
    }, 400);
    return () => clearTimeout(evalTimerMK.current);
  }, [arv, repairs, fee, pct, asking, sqft, tier, buyerPrice, holding, st, sf, nv]);

  const rep = res.repair && !res.repair.error ? res.repair : null;
  const sub = res.subto && !res.subto.error ? res.subto : null;
  const fin = res.sellerFinance && !res.sellerFinance.error ? res.sellerFinance : null;
  const nov = res.novation && !res.novation.error ? res.novation : null;
  const itn = res.internal || null;
  const byr = res.buyer && !res.buyer.error ? res.buyer : null;
  const setK = (setter) => (k) => (v) => setter((p) => ({ ...p, [k]: v }));
  const stK = setK(setSt), sfK = setK(setSf), nvK = setK(setNv);

  // ---- Contact search (debounced 350ms, phone-only results — desktop parity) ----
  useEffectMK(() => {
    if (picked || cq.trim().length < 2) { setCres([]); setCerr(null); setCsearching(false); return; }
    setCsearching(true);
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`/api/contacts?query=${encodeURIComponent(cq.trim())}&limit=8`);
        const j = await r.json();
        setCres((j.contacts || []).filter((c) => c.phone));
        setCerr(j && j.error ? j.error : null);
      } catch (e) { setCres([]); setCerr(e.message || "search failed"); }
      finally { setCsearching(false); }
    }, 350);
    return () => clearTimeout(t);
  }, [cq, picked]);

  // ---- Offer auto-draft — EXACT desktop template + voice ----
  const firstName = picked ? (picked.name || "").split(" ")[0] : "";
  const addr = picked && picked.addr ? picked.addr : "your property";
  useEffectMK(() => {
    if (!picked || offerTouched) return;
    if (mao <= 0) { setOffer(""); return; }
    setOffer(`hey ${firstName} its yahjair with a touch of blessings home buyers. my cash offer on ${addr} is ${M(mao)} as is i cover all the closing costs and can close in 2 weeks or on your timeline. want me to send the contract over`);
  }, [picked, mao, offerTouched]);

  function pick(c) { setPicked(c); setCq(c.name || ""); setCres([]); setOfferTouched(false); setSendMsg(null); setSaveMsg(null); }
  function unpick() { setPicked(null); setCq(""); setOffer(""); setOfferTouched(false); setSendMsg(null); setSaveMsg(null); }

  async function sendOffer() {
    if (!picked || !offer.trim() || sending) return;
    if (!window.confirm(`Send this cash offer to ${picked.name} (${picked.phone})?\n\n"${offer.trim()}"`)) return;
    setSending(true); setSendMsg(null);
    try {
      // Persist the deal first (same body as desktop) so the pipeline tracks it.
      const a = (picked.addr || "").split(",").map((s) => s.trim());
      await window.apiPostM("/api/deals/save", {
        contactId: picked.id, name: picked.name, email: picked.email || "",
        property_street: a[0] || picked.addr || "", property_city: a[1] || "",
        arv: arvN, repairs: repN, fee: feeN, pct: pctN, asking: askN, mao: Math.round(mao),
        offer: Math.round(mao), stage: "Offer",
      });
      await window.apiPostM("/api/send", { contactId: picked.id, name: picked.name, message: offer.trim() });
      setSendMsg({ ok: true, t: `Offer sent to ${picked.name} — deal saved, pipeline → Offer.` });
    } catch (e) {
      setSendMsg({ ok: false, t: "Send failed: " + (e.message || "error") });
    } finally { setSending(false); }
  }

  // AI ARV — Claude + live web search pulls comps for the address (~20-60s).
  async function findArv() {
    const a = arvAddr.trim();
    if (a.length < 8 || arvBusy) return;
    setArvBusy(true); setArvErr(null); setArvRes(null);
    try {
      const r = await window.apiPostM("/api/toolkit/calc/arv", { address: a, sqft });
      if (r && r.ok) setArvRes(r);
      else setArvErr((r && r.error) || "No number came back — try again.");
    } catch (e) { setArvErr(e.message || "ARV lookup failed"); }
    setArvBusy(false);
  }

  function applyArv() {
    if (!arvRes) return;
    setArv(String(arvRes.arv));
    if (arvRes.sqft && !MKNum(sqft)) setSqft(String(arvRes.sqft));
  }

  async function saveScenario() {
    if (!picked || saving) return;
    setSaving(true); setSaveMsg(null);
    try {
      await window.apiPostM("/api/toolkit/calc/save", { contactId: picked.id, ...evalBody() });
      setSaveMsg({ ok: true, t: "Scenario saved to deal record." });
    } catch (e) { setSaveMsg({ ok: false, t: "Save failed: " + (e.message || "error") }); }
    finally { setSaving(false); }
  }

  const msgLine = (m) => m && (
    <div style={{ fontSize: 12.5, fontWeight: 600, color: m.ok ? "var(--green, #22C55E)" : "var(--red, #EF4444)" }}>
      {m.ok ? "✓ " : ""}{m.t}
    </div>
  );
  const evalDown = evalErr && (
    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--red, #EF4444)" }}>
      Calc failed: {evalErr} — edit any number to retry.
    </div>
  );
  const grid2 = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 };

  return (
    <React.Fragment>
      <window.MHeader title="Deal Calculator"
        sub={`MAO = ARV × ${pctN || 70}% − repairs − assignment fee`}
        right={<MKI.Calc size={20} />} />
      <div className="m-content">

        {/* ---- 0. AI ARV finder ---- */}
        <window.MCard title="AI ARV finder" right={
          <span className="m-fade" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.4 }}>
            LIVE COMPS
          </span>
        }>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <input className="m-input" value={arvAddr} type="text" inputMode="text"
              placeholder="123 Main St, Wilmington, DE"
              onChange={(e) => setArvAddr(e.target.value)} />
            <window.MBtn onClick={findArv} disabled={arvBusy || arvAddr.trim().length < 8}>
              {arvBusy ? "Searching comps… ~30s" : "Find ARV with AI"}
            </window.MBtn>
            {arvErr && (
              <div style={{ fontSize: 12.5, color: "var(--red, #EF4444)" }}>{arvErr}</div>
            )}
            {arvRes && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8,
                borderTop: "1px solid rgba(255,255,255,0.07)", paddingTop: 10 }}>
                <div className="m-row" style={{ alignItems: "baseline", gap: 10 }}>
                  <span style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.8px",
                    color: "var(--green, #22C55E)" }}>{M(arvRes.arv)}</span>
                  {(arvRes.low || arvRes.high) && (
                    <span className="m-fade" style={{ fontSize: 12 }}>
                      {M(arvRes.low || arvRes.arv)} – {M(arvRes.high || arvRes.arv)}
                    </span>
                  )}
                  <span style={{ marginLeft: "auto", fontSize: 10, fontWeight: 800,
                    textTransform: "uppercase", letterSpacing: 0.5, padding: "3px 8px",
                    borderRadius: 999, flex: "none",
                    color: arvRes.confidence === "high" ? "#22C55E" : arvRes.confidence === "medium" ? "#F59E0B" : "#EF4444",
                    background: (arvRes.confidence === "high" ? "#22C55E" : arvRes.confidence === "medium" ? "#F59E0B" : "#EF4444") + "1f" }}>
                    {arvRes.confidence} conf
                  </span>
                </div>
                {(arvRes.sqft || arvRes.beds) && (
                  <div className="m-fade" style={{ fontSize: 12 }}>
                    {[arvRes.beds ? arvRes.beds + " bd" : null,
                      arvRes.baths ? arvRes.baths + " ba" : null,
                      arvRes.sqft ? arvRes.sqft.toLocaleString() + " sqft" : null]
                      .filter(Boolean).join(" · ")}
                  </div>
                )}
                {arvRes.summary && (
                  <div style={{ fontSize: 12.5, lineHeight: 1.45 }}>{arvRes.summary}</div>
                )}
                {(arvRes.comps || []).length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                    <div className="m-fade" style={{ fontSize: 10.5, fontWeight: 700,
                      textTransform: "uppercase", letterSpacing: 0.5 }}>Comps</div>
                    {arvRes.comps.map((c, i) => (
                      <div key={i} className="m-row" style={{ gap: 8, fontSize: 12 }}>
                        <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {c.address}{c.note ? " · " + c.note : ""}
                        </span>
                        <span style={{ fontWeight: 700, flex: "none" }}>{M(c.price)}</span>
                      </div>
                    ))}
                  </div>
                )}
                <window.MBtn kind="ok" onClick={applyArv}>
                  Apply {M(arvRes.arv)} → ARV
                </window.MBtn>
                <div className="m-fade" style={{ fontSize: 11 }}>
                  Internal prep number — verify with your own comps before you offer.
                </div>
              </div>
            )}
          </div>
        </window.MCard>

        {/* ---- 1. MAO ---- */}
        <window.MCard title="Max Allowable Offer">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={grid2}>
              {MKIn("ARV ($)", arv, setArv)}
              {MKIn("Seller asking ($, optional)", asking, setAsking)}
            </div>
            <div>
              <div className="m-fade" style={{ marginBottom: 5 }}>Estimated repairs</div>
              <div className="m-seg" style={{ marginBottom: 7 }}>
                {MK_PRESETS.map((r) => (
                  <window.MChip key={r.label} active={MKNum(repairs) === r.amt} onClick={() => setRepairs(String(r.amt))}>
                    {r.label} · {M(r.amt)}
                  </window.MChip>
                ))}
              </div>
              <input className="m-input" type="number" inputMode="numeric" value={repairs}
                placeholder="custom repair $" onChange={(e) => setRepairs(e.target.value)} />
            </div>
            <div style={grid2}>
              {MKIn("Assignment fee ($)", fee, setFee)}
              {MKIn("ARV % (formula)", pct, setPct)}
            </div>

            <div style={{ borderTop: "1px solid rgba(255,255,255,0.07)", paddingTop: 10 }}>
              <div className="m-fade" style={{ fontWeight: 700, letterSpacing: 0.4 }}>MAX ALLOWABLE OFFER</div>
              <div style={{ fontSize: 36, fontWeight: 800, lineHeight: 1.15, letterSpacing: "-1px", color: mao > 0 ? "var(--green, #22C55E)" : "var(--text-3, #64748B)" }}>
                {M(mao)}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {MKRow("ARV", M(arvN))}
              {MKRow(`× ${pctN || 70}%`, M(arvN * (pctN / 100)))}
              {MKRow("− repairs", "−" + M(repN), { color: "var(--red, #EF4444)" })}
              {MKRow("− assignment fee", "−" + M(feeN), { color: "var(--red, #EF4444)" })}
              {MKRow("Max offer", M(mao), { bold: true, color: "var(--green, #22C55E)", top: true })}
              {spread !== null && MKRow(`vs asking ${M(askN)}`, (spread >= 0 ? "+" : "") + M(spread),
                { bold: true, color: spread >= 0 ? "var(--green, #22C55E)" : "var(--red, #EF4444)" })}
            </div>
            {verdict ? (
              <div style={{ borderRadius: 12, padding: "12px 14px", background: verdict.c + "1a", border: "1px solid " + verdict.c + "66" }}>
                <div style={{ fontSize: 16, fontWeight: 800, color: verdict.c }}>{verdict.t}</div>
                <div style={{ fontSize: 12.5, marginTop: 3 }}>{verdict.msg}</div>
              </div>
            ) : (
              <div className="m-fade">Enter ARV + seller's asking price for a GO / NEGOTIATE / PASS verdict.</div>
            )}
          </div>
        </window.MCard>

        {/* ---- 2. Repair estimator ---- */}
        <window.MCard title="Repair estimator">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {cfg.loading && window.MSpin()}
            {!cfg.loading && cfg.error && (
              <div style={{ fontSize: 12.5, color: "var(--red, #EF4444)" }}>
                Couldn't load $/sqft rates: {cfg.error}{" "}
                <button className="m-chip" onClick={cfg.refresh} style={{ marginLeft: 6 }}>Retry</button>
              </div>
            )}
            {!cfg.loading && !cfg.error && rates && (
              <React.Fragment>
                {MKIn("Square footage (sqft)", sqft, setSqft)}
                <div className="m-seg">
                  {tiers.map((k) => (
                    <window.MChip key={k} active={tier === k} onClick={() => setTier(tier === k ? "" : k)}>
                      {MK_TIER_LABEL[k] || k} · ${rates[k]}/sqft
                    </window.MChip>
                  ))}
                </div>
                {tier && hints[tier] && <div className="m-fade">{MK_TIER_LABEL[tier] || tier}: {hints[tier]}</div>}
                {evalDown}
                {!evalErr && rep && (
                  <React.Fragment>
                    {MKRow(`${MK_TIER_LABEL[rep.tier] || rep.tier} · ${rep.sqft} sqft × $${rep.perSqft}`, M(rep.total),
                      { bold: true, color: "var(--orange, #F59E0B)", top: true })}
                    <window.MBtn kind="ghost" onClick={() => setRepairs(String(rep.total))}>
                      Apply {M(rep.total)} → repairs
                    </window.MBtn>
                  </React.Fragment>
                )}
                {!evalErr && !rep && res.repair && res.repair.error && (
                  <div style={{ fontSize: 12.5, color: "var(--red, #EF4444)" }}>{res.repair.error}</div>
                )}
                {!evalErr && !res.repair && <div className="m-fade">Enter sqft + pick a condition tier.</div>}
              </React.Fragment>
            )}
          </div>
        </window.MCard>

        {/* ---- 3. Creative finance ---- */}
        <window.MCard title="Creative finance">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="m-seg">
              {MK_MODES.map(([k, lbl]) => (
                <window.MChip key={k} active={mode === k} onClick={() => setMode(k)}>{lbl}</window.MChip>
              ))}
            </div>
            {mode === "subto" && (
              <React.Fragment>
                <div style={grid2}>
                  {MKIn("Monthly PITI ($)", st.piti, stK("piti"))}
                  {MKIn("Market rent ($)", st.rent, stK("rent"))}
                </div>
                <div style={grid2}>
                  {MKIn("Loan balance ($)", st.balance, stK("balance"))}
                  {MKIn("Cash to seller ($)", st.entryFee, stK("entryFee"))}
                </div>
                <div style={grid2}>
                  {MKIn("Arrears ($)", st.arrears, stK("arrears"))}
                  {MKIn("Closing costs ($)", st.closingCosts, stK("closingCosts"))}
                </div>
                {evalDown}
                {!evalErr && sub && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid rgba(255,255,255,0.07)", paddingTop: 8 }}>
                    {MKRow("Entry cash", M(sub.entryCash))}
                    {MKRow("Monthly cash flow", M(sub.monthlyFlow), { bold: true, color: sub.monthlyFlow >= 0 ? "var(--green, #22C55E)" : "var(--red, #EF4444)" })}
                    {MKRow("Annual", M(sub.annualFlow))}
                    {sub.cashOnCash != null && MKRow("Cash-on-cash", sub.cashOnCash + "%", { bold: true, color: "var(--green, #22C55E)" })}
                  </div>
                )}
                {!evalErr && !sub && res.subto && res.subto.error && (
                  <div style={{ fontSize: 12.5, color: "var(--red, #EF4444)" }}>{res.subto.error}</div>
                )}
                {!evalErr && !res.subto && <div className="m-fade">Enter the monthly PITI to run the sub-to numbers.</div>}
              </React.Fragment>
            )}
            {mode === "sellerfi" && (
              <React.Fragment>
                <div style={grid2}>
                  {MKIn("Price ($)", sf.price, sfK("price"))}
                  {MKIn("Down ($)", sf.down, sfK("down"))}
                </div>
                <div style={grid2}>
                  {MKIn("Rate (%)", sf.ratePct, sfK("ratePct"), { inputMode: "decimal" })}
                  {MKIn("Term (years)", sf.termYears, sfK("termYears"))}
                </div>
                {MKIn("Balloon (years)", sf.balloonYears, sfK("balloonYears"), { placeholder: "none" })}
                {evalDown}
                {!evalErr && fin && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid rgba(255,255,255,0.07)", paddingTop: 8 }}>
                    {MKRow("Note amount", M(fin.loan))}
                    {MKRow("Monthly payment", M(fin.monthly), { bold: true, color: "var(--blue, #4F7CFF)" })}
                    {MKRow("Total interest", M(fin.totalInterest))}
                    {fin.balloonBalance != null && MKRow(`Balloon @ ${Math.round(fin.balloonMonths / 12)}yr`, M(fin.balloonBalance), { bold: true, color: "var(--orange, #F59E0B)" })}
                  </div>
                )}
                {!evalErr && !fin && res.sellerFinance && res.sellerFinance.error && (
                  <div style={{ fontSize: 12.5, color: "var(--red, #EF4444)" }}>{res.sellerFinance.error}</div>
                )}
                {!evalErr && !res.sellerFinance && <div className="m-fade">Enter a price to amortize the seller-carry note.</div>}
              </React.Fragment>
            )}
            {mode === "novation" && (
              <React.Fragment>
                <div style={grid2}>
                  {MKIn("Seller nets ($)", nv.sellerPrice, nvK("sellerPrice"))}
                  {MKIn("Selling costs (%)", nv.sellCostPct, nvK("sellCostPct"), { inputMode: "decimal" })}
                </div>
                <div className="m-fade">Uses ARV + repairs from the MAO card above.</div>
                {evalDown}
                {!evalErr && nov && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid rgba(255,255,255,0.07)", paddingTop: 8 }}>
                    {MKRow("ARV − repairs − costs", M(nov.arv - nov.repairs - nov.sellingCosts))}
                    {MKRow("Seller nets", "−" + M(nov.sellerPrice), { color: "var(--red, #EF4444)" })}
                    {MKRow("Novation profit", M(nov.profit), { bold: true, color: nov.profit >= 0 ? "var(--green, #22C55E)" : "var(--red, #EF4444)" })}
                    {nov.vsWholesale != null && MKRow("vs wholesale fee", (nov.vsWholesale >= 0 ? "+" : "") + M(nov.vsWholesale),
                      { color: nov.vsWholesale >= 0 ? "var(--green, #22C55E)" : "var(--red, #EF4444)" })}
                  </div>
                )}
                {!evalErr && !nov && res.novation && res.novation.error && (
                  <div style={{ fontSize: 12.5, color: "var(--red, #EF4444)" }}>{res.novation.error}</div>
                )}
                {!evalErr && !res.novation && <div className="m-fade">Enter what the seller nets to compare vs your wholesale fee.</div>}
              </React.Fragment>
            )}
          </div>
        </window.MCard>

        {/* ---- 4. Deal views (internal vs buyer — fee never shown to buyer) ---- */}
        <window.MCard title="Deal views" right={
          <div style={{ display: "flex", gap: 6 }}>
            <window.MChip active={view === "internal"} onClick={() => setView("internal")}>Internal</window.MChip>
            <window.MChip active={view === "buyer"} onClick={() => setView("buyer")}>Buyer sees</window.MChip>
          </div>
        }>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {evalDown}
            {view === "internal" && !evalErr && (itn ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {MKRow("MAO (you pay seller)", M(itn.mao), { bold: true, color: "var(--green, #22C55E)" })}
                {MKRow("Assignment fee", M(itn.fee))}
                {MKRow("Buyer pays", M(itn.buyerPrice), { bold: true })}
                {itn.spread != null && MKRow("Spread vs asking", (itn.spread >= 0 ? "+" : "") + M(itn.spread),
                  { color: itn.spread >= 0 ? "var(--green, #22C55E)" : "var(--red, #EF4444)" })}
              </div>
            ) : <div className="m-fade">Enter an ARV in the MAO card above.</div>)}
            {view === "buyer" && !evalErr && (
              <React.Fragment>
                <div style={grid2}>
                  {MKIn("Buyer price ($)", buyerPrice, setBuyerPrice, { placeholder: itn ? String(Math.round(itn.buyerPrice)) : "MAO + fee" })}
                  {MKIn("Holding costs ($)", holding, setHolding)}
                </div>
                {byr ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid rgba(255,255,255,0.07)", paddingTop: 8 }}>
                    {MKRow("ARV (resale)", M(byr.arv))}
                    {MKRow("Purchase", "−" + M(byr.purchase), { color: "var(--red, #EF4444)" })}
                    {MKRow("Repairs", "−" + M(byr.repairs), { color: "var(--red, #EF4444)" })}
                    {MKRow("Closing (buy + sell)", "−" + M(byr.buyClosing + byr.sellClosing), { color: "var(--red, #EF4444)" })}
                    {byr.holding > 0 && MKRow("Holding", "−" + M(byr.holding), { color: "var(--red, #EF4444)" })}
                    {MKRow("Buyer profit", M(byr.profit), { bold: true, color: byr.profit >= 0 ? "var(--green, #22C55E)" : "var(--red, #EF4444)" })}
                    {byr.roiPct != null && MKRow("Cash-in ROI", byr.roiPct + "%", { bold: true, color: "var(--green, #22C55E)" })}
                  </div>
                ) : <div className="m-fade">Enter an ARV in the MAO card above.</div>}
                <div className="m-fade" style={{ fontSize: 11 }}>
                  This is the sheet buyers see — one purchase number, your fee never shown.
                </div>
              </React.Fragment>
            )}
          </div>
        </window.MCard>

        {/* ---- 5. Send offer ---- */}
        <window.MCard title="Send offer to homeowner">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {!picked ? (
              <React.Fragment>
                <div className="m-row">
                  <MKI.Search size={17} />
                  <input className="m-input" style={{ flex: 1 }} value={cq}
                    placeholder="Search homeowner by name or phone…"
                    onChange={(e) => setCq(e.target.value)} />
                </div>
                {csearching && <div className="m-fade">Searching…</div>}
                {!csearching && cerr && (
                  <div style={{ fontSize: 12.5, color: "var(--red, #EF4444)" }}>Search failed: {cerr}</div>
                )}
                {!csearching && !cerr && cq.trim().length >= 2 && cres.length === 0 && (
                  window.MEmpty({ title: "No matches with a phone number", sub: "Only textable contacts show here." })
                )}
                {cres.map((c) => (
                  <button key={c.id} className="m-list-item" onClick={() => pick(c)}
                    style={{ width: "100%", textAlign: "left", cursor: "pointer", fontFamily: "inherit", color: "var(--text, #F1F5FB)" }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{c.name || "(no name)"}</div>
                      <div className="m-fade">{c.phone}{c.addr ? " · " + c.addr : ""}</div>
                    </div>
                    <MKI.Check size={17} />
                  </button>
                ))}
              </React.Fragment>
            ) : (
              <div className="m-list-item" style={{ padding: "10px 12px" }}>
                <MKI.User size={18} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>{picked.name}</div>
                  <div className="m-fade">{picked.phone}{picked.addr ? " · " + picked.addr : ""}</div>
                </div>
                <button className="m-chip" onClick={unpick} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <MKI.X size={13} /> change
                </button>
              </div>
            )}

            {picked && mao <= 0 && <div className="m-fade">Enter an ARV above to generate the offer number.</div>}

            {picked && mao > 0 && (
              <React.Fragment>
                <div>
                  <div className="m-fade" style={{ marginBottom: 5 }}>Offer message (edit before sending — it's in your voice)</div>
                  <textarea className="m-input" rows={4} value={offer}
                    onChange={(e) => { setOffer(e.target.value); setOfferTouched(true); }} />
                </div>
                <window.MBtn kind="ok" onClick={sendOffer} disabled={sending || !offer.trim()}>
                  {sending ? "Sending…" : `Send ${M(mao)} offer`}
                </window.MBtn>
                {msgLine(sendMsg)}
                <div className="m-fade" style={{ fontSize: 11 }}>
                  Texts via GoHighLevel from your number. Confirm prompt before it goes out.
                </div>
              </React.Fragment>
            )}

            <window.MBtn kind="ghost" onClick={saveScenario} disabled={!picked || saving}>
              {saving ? "Saving…" : "Save scenario to deal"}
            </window.MBtn>
            {!picked && <div className="m-fade" style={{ fontSize: 11 }}>Pick a homeowner to save the full calc onto their deal record.</div>}
            {msgLine(saveMsg)}
          </div>
        </window.MCard>

      </div>
    </React.Fragment>
  );
}

Object.assign(window, { MCalcPage });
