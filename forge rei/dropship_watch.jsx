// dropship_watch.jsx — Product Watch: track products you can't dropship yourself yet,
// and let Midas score each 1–10 with winning numbers, why it wins, and what ads to make.
const { useState: useStateDsw } = React;

const DSW_STAGES = ["idea", "researching", "testing", "winner", "killed"];

function DswScoreColor(n) {
  const s = Number(n);
  if (!s) return "#8B8FA3";
  if (s >= 7) return "#22C55E";
  if (s >= 4) return "#F4B860";
  return "#F87171";
}

function DswMargin(item) {
  const cost = Number(item.cost) || 0; const price = Number(item.price) || 0;
  if (!cost || !price) return "—";
  const gross = price - cost;
  return "$" + gross.toFixed(2) + " (" + Math.round((gross / price) * 100) + "%)";
}

function DswAddModal({ item, onClose, onSaved }) {
  const [form, setForm] = useStateDsw(item || { name: "", stage: "idea", supplier: "", cost: "", price: "", sourceUrl: "", angle: "", notes: "" });
  const [busy, setBusy] = useStateDsw(false);
  const [err, setErr] = useStateDsw("");
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const save = async () => {
    if (!form.name.trim()) { setErr("Name required"); return; }
    setBusy(true); setErr("");
    try { await window.DsRequest("/watchlist/save", { body: form }); onSaved(); onClose(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return <window.DsModal title={item && item.id ? "Edit watched product" : "Add product to watch"} copy="Track a product you can't dropship yourself yet — Midas scores it on demand." onClose={onClose}>
    {err && <div className="dc-form-error">{err}</div>}
    <div className="dc-form-grid">
      <window.DsField label="Product name"><input autoFocus value={form.name} onChange={set("name")} placeholder="what is it" /></window.DsField>
      <window.DsField label="Stage"><select value={form.stage} onChange={set("stage")}>{DSW_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}</select></window.DsField>
      <window.DsField label="Supplier / source"><input value={form.supplier} onChange={set("supplier")} placeholder="AliExpress / CJ / TikTok …" /></window.DsField>
      <window.DsField label="Landed cost"><input value={form.cost} onChange={set("cost")} placeholder="incl. shipping" /></window.DsField>
      <window.DsField label="Sell price"><input value={form.price} onChange={set("price")} placeholder="what you'd charge" /></window.DsField>
      <window.DsField label="Source URL"><input value={form.sourceUrl} onChange={set("sourceUrl")} placeholder="link you spotted it at" /></window.DsField>
      <window.DsField label="Angle" wide><input value={form.angle} onChange={set("angle")} placeholder="the hook you have in mind (optional)" /></window.DsField>
      <window.DsField label="Notes" wide><textarea rows="2" value={form.notes} onChange={set("notes")} placeholder="why it caught your eye" /></window.DsField>
    </div>
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button></div>
  </window.DsModal>;
}

function DswSignalLine(sig) {
  if (!sig || typeof sig !== "object") return "";
  const parts = [];
  const push = (k, v) => { if (v !== null && v !== undefined && v !== "") parts.push(k + ": " + v); };
  push("ads", sig.adCount); push("revenue/GMV", sig.revenueTrend); push("sold", sig.sold);
  push("sell price", sig.sellPrice); push("category", sig.category);
  push("impressions", sig.impressions); push("country", sig.country); push("first seen", sig.firstSeen);
  push("supplier", sig.supplierName);
  return parts.join(" · ");
}

// Pull REAL trending / winning products from whatever ad-spy source is keyed (PiPiAds /
// AutoDS marketplace). Manual pull only — NEVER auto-polls, so it never spends quota on a
// timer. One-tap adds a product to the watchlist (carrying its real signal) for Midas.
function DswTrending({ onAdded }) {
  const [q, setQ] = useStateDsw("");
  const [data, setData] = useStateDsw(null);
  const [loading, setLoading] = useStateDsw(false);
  const [err, setErr] = useStateDsw("");
  const [adding, setAdding] = useStateDsw(null);
  const [open, setOpen] = useStateDsw(false);
  const pull = async () => {
    setLoading(true); setErr("");
    try { const r = await window.DsRequest("/trending?limit=24&q=" + encodeURIComponent(q.trim())); setData(r); setOpen(true); }
    catch (e) { setErr(e.message); } finally { setLoading(false); }
  };
  const add = async (p) => {
    setAdding(p.sourceUrl + p.name);
    const notes = [DswSignalLine(p.signal), p.source ? "via " + p.source : ""].filter(Boolean).join(" — ");
    try {
      await window.DsRequest("/watchlist/save", { body: { name: p.name, supplier: p.supplier || p.source || "", cost: p.cost || "", sourceUrl: p.sourceUrl || "", notes } });
      if (onAdded) onAdded();
    } catch (e) { window.alert(e.message); } finally { setAdding(null); }
  };
  const products = (data && data.products) || [];
  const sources = (data && data.sources) || [];
  const anyKeyed = data && data.configured;
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head">
      <div><div className="card-title">Pull trending products</div><div className="faint">Real winners from PiPiAds / AutoDS ad-spy — the API spend that matters. Manual pull only.</div></div>
      <div className="dsw-pull-row"><input className="dsw-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="keyword / category (optional)" onKeyDown={(e) => { if (e.key === "Enter") pull(); }} /><button className="dc-primary" disabled={loading} onClick={pull}>{loading ? "Pulling…" : "Pull trending"}</button></div>
    </div>
    {err && <div className="dc-form-error">{err}</div>}
    {open && !anyKeyed && <div className="dsw-addkey"><b>No trend source keyed yet.</b><span>{(data && data.detail) || "Add PIPIADS_API_KEY (pipispy.com) or AUTODS_API_KEY to dropship.env to pull real trending products. $0 until then."}</span></div>}
    {open && anyKeyed && <div className="dsw-src-line">{sources.filter((s) => s.configured).map((s) => <span key={s.source} className={"dsw-src " + (s.ok ? "ok" : "bad")}>{s.source}: {s.ok ? (s.count + " found") : (s.error || "error")}</span>)}</div>}
    {open && anyKeyed && products.length ? <div className="dsw-trend-list">{products.map((p, i) => <div key={i} className="dsw-trend-item"><div className="dsw-trend-main"><b>{p.name}</b>{DswSignalLine(p.signal) && <small className="faint">{DswSignalLine(p.signal)}</small>}<small className="faint">source: {p.source}{p.cost ? " · cost " + p.cost : ""}</small></div><div className="dsw-trend-actions">{p.sourceUrl && <a className="link" href={p.sourceUrl} target="_blank" rel="noreferrer">View ↗</a>}<button className="dc-outline dsw-add-btn" disabled={adding === (p.sourceUrl + p.name)} onClick={() => add(p)}>{adding === (p.sourceUrl + p.name) ? "Adding…" : "＋ Watch"}</button></div></div>)}</div> : (open && anyKeyed ? <div className="dc-inline-empty">No trending products returned for that query.</div> : null)}
  </div>;
}

function DswDiscover({ onAdded }) {
  const [data, setData] = useStateDsw(null);
  const [busy, setBusy] = useStateDsw(false);
  const [adding, setAdding] = useStateDsw(null);
  const [err, setErr] = useStateDsw("");
  const scan = async () => {
    setBusy(true); setErr("");
    try { setData(await window.DsRequest("/research/discover", { body: { limit: 10 } })); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const add = async (item) => {
    setAdding(item.name);
    try {
      await window.DsRequest("/watchlist/save", { body: { name: item.name, stage: "researching", sourceUrl: item.sourceUrl || "", notes: item.headline || "" } });
      if (onAdded) onAdded();
    } catch (e) { window.alert(e.message); } finally { setAdding(null); }
  };
  const items = (data && data.candidates) || [];
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Find & rank 10 beginner products</div><div className="faint">GetHookd finds active winning Shopify ads; Midas excludes beginner-hostile categories and ranks the remaining evidence. $40/day, $120 maximum test once supplier math clears.</div></div><button className="dc-primary" disabled={busy} onClick={scan}>{busy ? "Midas is ranking…" : "Find 10 products"}</button></div>
    {err && <div className="dc-form-error">{err}</div>}
    {data && data.error && <div className="dc-form-error">{data.error}</div>}
    {data && <div className="dsw-src-line"><span className="dsw-src ok">GetHookd used {data.usedCredits || 0} credits · {data.remainingCredits || "?"} remaining</span><span className="faint">{data.note}</span></div>}
    {items.length ? <div className="dsw-trend-list">{items.map((item, i) => <div key={i} className="dsw-trend-item"><div className="dsw-score" style={{ borderColor: DswScoreColor(item.score), color: DswScoreColor(item.score) }}>{item.score}<small>/10</small></div><div className="dsw-trend-main"><b>{item.name}</b><small className="faint">{item.headline || "Evidence-ranked candidate"}</small>{Array.isArray(item.adAngles) && item.adAngles.length ? <small className="faint">Angles: {item.adAngles.join(" · ")}</small> : null}<small className="faint">Unknown: {item.biggestUnknown || "source cost and shipping"}</small></div><div className="dsw-trend-actions">{item.sourceUrl && <a className="link" href={item.sourceUrl} target="_blank" rel="noreferrer">Source ↗</a>}<button className="dc-outline dsw-add-btn" disabled={adding === item.name} onClick={() => add(item)}>{adding === item.name ? "Adding…" : "＋ Watch"}</button></div></div>)}</div> : (data ? <div className="dc-inline-empty">No beginner-safe physical products were identifiable in this scan. Run it again later; it will not invent candidates.</div> : null)}
  </div>;
}

// Competitor Ads — what OTHER stores are running right now, out of the Meta Ad Library.
// Days-running is the headline number on purpose: nobody keeps paying to run a losing
// ad, so a 60-day-old ad is a proven ad. Manual pull only — each search fires a PAID
// Apify actor run, so this NEVER auto-polls.
function DswAdAge(d) {
  const n = Number(d);
  if (!n && n !== 0) return "#8B8FA3";
  if (n >= 60) return "#22C55E";
  if (n >= 21) return "#F4B860";
  return "#8B8FA3";
}

function DswAdCard({ ad, winner }) {
  const days = ad.daysRunning;
  const color = DswAdAge(days);
  const body = (ad.body || "").replace(/\s+/g, " ").trim();
  return <div className="dsw-trend-item">
    <div className="dsw-score" style={{ borderColor: color, color }}>{(days === 0 || days) ? days : "–"}<small>days</small></div>
    <div className="dsw-trend-main">
      <b>{ad.pageName || "(unknown page)"}{winner ? <span className="dsw-chip" style={{ marginLeft: 8, borderColor: "#22C55E55", color: "#22C55E" }}>proven</span> : null}</b>
      {ad.title && <small className="faint">{ad.title}</small>}
      {body && <small className="faint">{body.length > 160 ? body.slice(0, 160) + "…" : body}</small>}
      <small className="faint">{[ad.cta ? "CTA: " + ad.cta : "", ad.mediaType || "", ad.startDate ? "since " + String(ad.startDate) : ""].filter(Boolean).join(" · ") || "no creative detail returned"}</small>
    </div>
    <div className="dsw-trend-actions">
      {ad.linkUrl && <a className="link" href={ad.linkUrl} target="_blank" rel="noreferrer">Landing ↗</a>}
      {ad.snapshotUrl && <a className="link" href={ad.snapshotUrl} target="_blank" rel="noreferrer">Ad ↗</a>}
    </div>
  </div>;
}

function DswCompetitorAds() {
  const [adq, setAdq] = useStateDsw("");
  const [addata, setAddata] = useStateDsw(null);
  const [adloading, setAdloading] = useStateDsw(false);
  const [aderr, setAderr] = useStateDsw("");
  const search = async () => {
    if (!adq.trim()) { setAderr("Type a keyword first"); return; }
    setAdloading(true); setAderr("");
    try { const r = await window.DsRequest("/adspy/search", { body: { q: adq.trim(), min_days: 21 } }); setAddata(r); }
    catch (e) { setAderr(e.message); } finally { setAdloading(false); }
  };
  const ads = (addata && addata.ads) || [];
  const wins = (addata && addata.winners) || [];
  const winIds = {};
  wins.forEach((a) => { if (a.id) winIds[a.id] = true; });
  const rest = ads.filter((a) => !(a.id && winIds[a.id]));
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head">
      <div><div className="card-title">Competitor Ads</div><div className="faint">Live Meta Ad Library pull — who's advertising this and for how long. Long-running = proven. Manual pull only (each search is a paid scrape).</div></div>
      <div className="dsw-pull-row"><input className="dsw-search" value={adq} onChange={(e) => setAdq(e.target.value)} placeholder="product / keyword" onKeyDown={(e) => { if (e.key === "Enter") search(); }} /><button className="dc-primary" disabled={adloading} onClick={search}>{adloading ? "Searching…" : "Search ads"}</button></div>
    </div>
    {aderr && <div className="dc-form-error">{aderr}</div>}
    {addata && !addata.configured && <div className="dsw-addkey"><b>No ad-spy key yet.</b><span>{addata.detail || "Add APIFY_TOKEN to dropship.env to pull real competitor ads. $0 until then."}</span></div>}
    {addata && addata.configured && addata.error && <div className="dc-form-error">{addata.error}</div>}
    {addata && addata.configured && !addata.error ? (ads.length ? <div className="dsw-trend-list">
      {wins.length ? <small className="faint">Proven — running {addata.minDays || 21}+ days ({wins.length})</small> : null}
      {wins.map((a, i) => <DswAdCard key={"w" + i} ad={a} winner />)}
      {rest.length ? <small className="faint">Newer / unproven ({rest.length})</small> : null}
      {rest.map((a, i) => <DswAdCard key={"r" + i} ad={a} />)}
    </div> : <div className="dc-inline-empty">No ads returned for that keyword.</div>) : null}
  </div>;
}

function DswChips({ label, items, color }) {
  if (!Array.isArray(items) || !items.length) return null;
  return <div className="dsw-chips-row"><small className="faint">{label}</small><div className="dsw-chips">{items.map((t, i) => <span key={i} className="dsw-chip" style={color ? { borderColor: color + "55", color } : null}>{String(t)}</span>)}</div></div>;
}

function DswAnalysis({ a }) {
  if (!a) return null;
  if (a.raw) return <div className="dsw-analysis"><pre className="dsw-raw">{a.raw}</pre></div>;
  return <div className="dsw-analysis">
    {a.headline && <div className="dsw-headline">{a.headline}</div>}
    {Array.isArray(a.winningNumbers) && a.winningNumbers.length ? <div className="dsw-block"><small className="faint">Winning numbers</small><ul className="dsw-list">{a.winningNumbers.map((w, i) => <li key={i}>{String(w)}</li>)}</ul></div> : null}
    {a.whyItWins && <div className="dsw-block"><small className="faint">Why it wins</small><p>{a.whyItWins}</p></div>}
    {a.audience && <div className="dsw-block"><small className="faint">Who it's for</small><p>{a.audience}</p></div>}
    <DswChips label="Ad types" items={a.adTypes} color="#F97316" />
    <DswChips label="Ad angles" items={a.adAngles} color="#8B5CF6" />
    {a.biggestUnknown && <div className="dsw-block dsw-unknown"><small className="faint">Biggest unknown</small><p>{a.biggestUnknown}</p></div>}
    {a.nextStep && <div className="dsw-block"><small className="faint">Cheapest next step</small><p>{a.nextStep}</p></div>}
  </div>;
}

// ---------------------------------------------------------------------------
// Decision packet (research_packet.build) — evidence + money math + kill flags.
// Everything below renders the packet EXACTLY as the creed emits it: a stamped
// figure never appears without its source, a missing input reads "Unknown"
// rather than a confident number, and vendor text is rendered as inert data.
// ---------------------------------------------------------------------------

const DSW_VERDICT_COLOR = {
  STRONG: "#22C55E", WORKABLE: "#F4B860", HARD: "#F97316", DEAD: "#F87171",
  OK: "#22C55E", THIN: "#F4B860", Unknown: "#8B8FA3",
};
const DSW_SEVERITY_COLOR = { stop: "#F87171", warn: "#F4B860", unknown: "#8B8FA3" };

function DswVerdictColor(v) { return DSW_VERDICT_COLOR[String(v || "")] || "#8B8FA3"; }

// The one stamped-value renderer. `s` is either a bare value or the guard's
// {value, unknown, source, window, fetchedAt, confidence, display} envelope —
// a number without its source is not allowed to look like a fact.
function DswStat({ label, s, prefix, suffix, strong }) {
  if (s === null || s === undefined || s === "") return null;
  const obj = typeof s === "object";
  const unknown = obj ? !!s.unknown : false;
  const raw = obj ? (s.display !== undefined && s.display !== null ? String(s.display) : String(s.value)) : String(s);
  const full = obj ? [
    s.source ? "source: " + s.source : "",
    s.window ? "window: " + s.window : "",
    s.confidence ? "confidence: " + s.confidence : "",
    s.fetchedAt ? "fetched " + s.fetchedAt : "",
    s.why ? "why: " + s.why : "",
  ].filter(Boolean).join(" · ") : "";
  const brief = obj ? [s.source, s.window].filter((x) => x && x !== "Unknown").join(" · ") : "";
  return <div className="dsw-block" title={full || undefined} style={{ minWidth: 0 }}>
    {label && <small className="faint">{label}</small>}
    <div style={{ fontWeight: 700, fontSize: strong ? 20 : 15, color: unknown ? "#8B8FA3" : undefined }}>
      {unknown ? "Unknown" : ((prefix || "") + raw + (suffix || ""))}
    </div>
    {brief && <small className="faint">{brief}</small>}
  </div>;
}

// Vendor-written text is {text, untrusted, flagged, label} — never a string, and
// never an instruction. `flagged` means the field carried text addressed at a
// reading model; we show it as inert data with a marker, we never obey it.
function DswText({ v }) {
  if (v === null || v === undefined) return null;
  if (typeof v !== "object") return <span>{String(v)}</span>;
  const t = v.text || "";
  if (!t) return null;
  return <span>
    {v.flagged ? <span title="This vendor field contained text addressed at an AI model. It was treated as inert data and never followed." style={{ color: "#F4B860", marginRight: 6 }}>⚠</span> : null}
    {t}
  </span>;
}

// The money line — the most prominent thing on the packet, because most
// candidates die on breakeven CVR before a dollar moves. Renders whichever shape
// the packet actually carries (paid-traffic breakeven vs. Etsy fee net).
function DswMoneyLine({ money }) {
  if (!money || typeof money !== "object") return null;
  const verdict = money.verdict || "Unknown";
  const color = DswVerdictColor(verdict);
  const bePct = money.breakevenCvrPct;
  return <div className="dsw-block" style={{ border: "1px solid " + color + "44", background: color + "12", borderRadius: 12, padding: "12px 14px" }}>
    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
      <span className="dsw-chip" style={{ borderColor: color + "88", color, fontWeight: 700 }}>{verdict}</span>
      {(bePct !== undefined && bePct !== null)
        ? <b style={{ fontSize: 20 }}>needs {bePct}% conversion to break even</b>
        : (verdict === "Unknown" ? <b style={{ fontSize: 17, color: "#8B8FA3" }}>money math can't run — inputs missing</b> : null)}
    </div>
    <div className="dsw-chips-row" style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 8 }}>
      <DswStat label="Gross margin / sale" s={money.margin} prefix="$" strong />
      <DswStat label="~cost to acquire one order" s={money.cacAtMedianCvr} prefix="$" strong />
      <DswStat label="Net / sale (after Etsy fees)" s={money.net} prefix="$" strong />
      <DswStat label="Etsy fees / sale" s={money.fees} prefix="$" />
      {(money.feePct !== undefined && money.feePct !== null) ? <DswStat label="Fees as % of sale" s={money.feePct + "%"} /> : null}
      <DswStat label="Cost per click" s={money.cpc} prefix="$" />
      <DswStat label="Margin needed at median CVR" s={money.marginNeededAtMedian} prefix="$" />
      <DswStat label="Breakeven CVR" s={money.breakevenCvr} />
      {(money.salesToRecover100 !== undefined && money.salesToRecover100 !== null) ? <DswStat label="Sales to recover $100 spend" s={money.salesToRecover100} /> : null}
    </div>
    {money.note && <p style={{ marginTop: 8 }}>{money.note}</p>}
  </div>;
}

function DswKillFlags({ flags }) {
  if (!Array.isArray(flags) || !flags.length) return null;
  return <div className="dsw-block">
    <small className="faint">Kill flags ({flags.length})</small>
    {flags.map((f, i) => {
      const sev = String(f.severity || "unknown");
      const c = DSW_SEVERITY_COLOR[sev] || "#8B8FA3";
      return <div key={i} style={{ borderLeft: "3px solid " + c, padding: "6px 0 6px 10px", margin: "8px 0", background: sev === "stop" ? c + "12" : "transparent" }}>
        <b style={{ color: c }}>{sev === "stop" ? "STOP" : sev.toUpperCase()} · {f.flag}</b>
        <div className="faint">{f.detail}</div>
      </div>;
    })}
  </div>;
}

function DswUnknowns({ unknowns }) {
  if (!Array.isArray(unknowns) || !unknowns.length) return null;
  return <div className="dsw-block dsw-unknown">
    <small className="faint">Unknowns — nothing here is guessed</small>
    <ul className="dsw-list">{unknowns.map((u, i) => <li key={i}>{String(u)}</li>)}</ul>
  </div>;
}

function DswRead({ read }) {
  if (!read || typeof read !== "object") return null;
  const rows = [
    ["Why it's winning", read.whyWinning], ["Trigger", read.trigger],
    ["Creative format", read.creativeFormat], ["Hook (first 3s)", read.hook],
    ["Offer structure", read.offerStructure], ["Saturation", read.saturation],
  ];
  const plan = (read.copyPlan && typeof read.copyPlan === "object") ? read.copyPlan : null;
  return <div className="dsw-analysis">
    {read.headline && <div className="dsw-headline">{read.headline}</div>}
    {rows.filter((r) => r[1]).map((r, i) => <div key={i} className="dsw-block"><small className="faint">{r[0]}</small><p>{String(r[1])}</p></div>)}
    {plan ? <div className="dsw-block" style={{ border: "1px solid #8B5CF655", borderRadius: 12, padding: "10px 12px" }}>
      <small className="faint">Copy plan</small>
      {plan.angle && <p><b>Angle:</b> {String(plan.angle)}</p>}
      {plan.whatToChange && <p><b>What to change:</b> {String(plan.whatToChange)}</p>}
      {plan.higgsfieldPrompt && <><small className="faint">Higgsfield prompt</small><pre className="dsw-raw">{String(plan.higgsfieldPrompt)}</pre></>}
    </div> : null}
    {read.biggestUnknown && <div className="dsw-block dsw-unknown"><small className="faint">Biggest unknown</small><p>{String(read.biggestUnknown)}</p></div>}
    {read.nextStep && <div className="dsw-block"><small className="faint">Cheapest next step</small><p>{String(read.nextStep)}</p></div>}
  </div>;
}

// Generate creative from the packet's copy plan. Generating is NOT launching —
// an image is an internal, deletable file. Every asset carries its AI disclosure.
function DswCreativePanel({ packet }) {
  const [cbusy, setCbusy] = useStateDsw(false);
  const [cres, setCres] = useStateDsw(null);
  const [cerr, setCerr] = useStateDsw("");
  const [ccount, setCcount] = useStateDsw("1");
  const read = (packet && packet.read) || null;
  const plan = (read && typeof read.copyPlan === "object") ? read.copyPlan : null;
  const blocked = !!(packet && packet.blocked);
  const go = async () => {
    setCbusy(true); setCerr(""); setCres(null);
    try {
      const r = await window.DsRequest("/creative/make", { body: { packet, count: Math.max(1, Math.min(Number(ccount) || 1, 4)) } });
      setCres(r);
      if (r && r.ok === false) setCerr(r.error || "Generation refused.");
    } catch (e) { setCerr(e.message); } finally { setCbusy(false); }
  };
  const assets = (cres && cres.assets) || [];
  const errors = (cres && cres.errors) || [];
  const disclosure = (cres && cres.disclosure) || (assets[0] && assets[0].disclosure) || "";
  return <div className="dsw-block" style={{ borderTop: "1px solid #ffffff14", paddingTop: 12, marginTop: 12 }}>
    <div className="dc-panel-head">
      <div>
        <div className="card-title">Creative</div>
        <div className="faint">Generating is <b>not</b> launching — the result is an internal file. Publishing, boosting or spending against it stays a one-tap approval.</div>
      </div>
      <div className="dsw-pull-row">
        <select className="dsw-search" value={ccount} onChange={(e) => setCcount(e.target.value)} title="How many images (each one costs a generation)">
          {["1", "2", "3", "4"].map((n) => <option key={n} value={n}>{n} image{n === "1" ? "" : "s"}</option>)}
        </select>
        <button className="dc-primary" disabled={cbusy || blocked || !plan} onClick={go}>{cbusy ? "Generating…" : "Generate creative"}</button>
      </div>
    </div>
    {packet && packet.copyRule ? <div className="dsw-addkey"><b>Copy rule</b><span>{packet.copyRule}</span></div> : null}
    {blocked ? <div className="dc-inline-empty">Candidate is blocked — no generation spend on a dead candidate.</div>
      : (!plan ? <div className="dc-inline-empty">No copy plan on this packet yet — the Higgsfield prompt comes from the why-it's-winning read.</div> : null)}
    {cerr && <div className="dc-form-error">{cerr}</div>}
    {cres && cres.configured === false ? <div className="dsw-addkey"><b>Higgsfield not keyed.</b><span>{cres.detail || "Add HIGGSFIELD_API_KEY + HIGGSFIELD_API_SECRET to dropship.env."}</span></div> : null}
    {errors.length ? <div className="dsw-block"><small className="faint">Generation errors</small><ul className="dsw-list">{errors.map((e, i) => <li key={i}>{String(e)}</li>)}</ul></div> : null}
    {assets.length ? <div className="dsw-block">
      <div className="dsw-chips" style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {assets.map((a, i) => <div key={i} style={{ maxWidth: 260 }}>
          <a href={a.url} target="_blank" rel="noreferrer"><img src={a.url} alt={"generated creative " + (i + 1)} style={{ width: "100%", borderRadius: 10, display: "block" }} /></a>
          <small className="faint" style={{ display: "block", marginTop: 4 }}>{a.disclosure || disclosure}</small>
        </div>)}
      </div>
      {disclosure && <small className="faint" style={{ display: "block", marginTop: 6 }}>{disclosure}</small>}
      {cres && cres.note && <small className="faint" style={{ display: "block", marginTop: 4 }}>{cres.note}</small>}
    </div> : null}
  </div>;
}

function DswPacket({ packet }) {
  if (!packet) return null;
  const cand = packet.candidate || {};
  return <div className="dsw-analysis">
    {packet.blocked ? <div className="dc-form-error" style={{ fontSize: 15, fontWeight: 700 }}>
      BLOCKED — a stop-severity kill flag fired. Do not spend on this candidate.
    </div> : null}
    {packet.headline && <div className="dsw-headline">{packet.headline}</div>}
    <small className="faint"><DswText v={cand.name} /> · channel: {cand.channel || "dropship"}{cand.shipDays ? " · " + cand.shipDays + "d transit" : ""}</small>
    <DswMoneyLine money={packet.money} />
    <DswKillFlags flags={packet.killFlags} />
    <DswUnknowns unknowns={packet.unknowns} />
    {packet.note && <div className="dsw-block"><small className="faint">Note</small><p>{packet.note}</p></div>}
    {packet.readError && <div className="dc-form-error">Read unavailable: {String(packet.readError)}</div>}
    <DswRead read={packet.read} />
    <DswCreativePanel packet={packet} />
  </div>;
}

// One packet surface, two entry points: the "Build packet" button on a watched
// product (pre-filled), or the manual candidate form from the page head.
function DswPacketModal({ seed, onClose }) {
  const [pform, setPform] = useStateDsw({
    name: (seed && seed.name) || "", channel: (seed && seed.channel) || "dropship",
    price: (seed && seed.price) || "", landedCost: (seed && seed.landedCost) || "",
    shipDays: (seed && seed.shipDays) || "",
  });
  const [pbusy, setPbusy] = useStateDsw(false);
  const [perr, setPerr] = useStateDsw("");
  const [packet, setPacket] = useStateDsw(null);
  const setP = (k) => (e) => setPform({ ...pform, [k]: e.target.value });
  const moneyReady = String(pform.price).trim() !== "" && String(pform.landedCost).trim() !== "";
  const build = async () => {
    if (!String(pform.name).trim()) { setPerr("Product name required"); return; }
    setPbusy(true); setPerr(""); setPacket(null);
    try {
      const r = await window.DsRequest("/research/packet", {
        body: {
          name: String(pform.name).trim(), channel: pform.channel,
          price: pform.price, landedCost: pform.landedCost, shipDays: pform.shipDays,
        },
      });
      if (r && r.packet) setPacket(r.packet);
      else setPerr((r && r.error) || "No packet returned.");
    } catch (e) { setPerr(e.message); } finally { setPbusy(false); }
  };
  return <window.DsModal wide title="Decision packet" copy="Evidence + the money math + kill flags, then the read. Nothing here lists, buys, advertises or messages." onClose={onClose}>
    {perr && <div className="dc-form-error">{perr}</div>}
    <div className="dc-form-grid">
      <window.DsField label="Product name"><input autoFocus value={pform.name} onChange={setP("name")} placeholder="what you'd search the ad library for" /></window.DsField>
      <window.DsField label="Channel"><select value={pform.channel} onChange={setP("channel")}><option value="dropship">dropship (paid traffic)</option><option value="etsy">etsy</option></select></window.DsField>
      <window.DsField label="Sell price ★"><input value={pform.price} onChange={setP("price")} placeholder="what you'd charge" /></window.DsField>
      <window.DsField label="Landed cost ★"><input value={pform.landedCost} onChange={setP("landedCost")} placeholder="product + shipping to the door" /></window.DsField>
      <window.DsField label="Transit days"><input value={pform.shipDays} onChange={setP("shipDays")} placeholder="e.g. 12 — over 30 trips the FTC rule" /></window.DsField>
    </div>
    <div className={moneyReady ? "dsw-src-line" : "dsw-addkey"}>
      {moneyReady
        ? <span className="dsw-src ok">★ Price and landed cost are set — the breakeven math will run.</span>
        : <><b>★ Price and landed cost are what make the money math run.</b><span>Leave either blank and the packet returns Unknown by design — it will not guess a margin, a breakeven conversion rate, or a cost per order.</span></>}
    </div>
    <div className="dc-modal-actions">
      <button className="dc-quiet" onClick={onClose}>Close</button>
      <button className="dc-primary" disabled={pbusy} onClick={build}>{pbusy ? "Building…" : (packet ? "Rebuild packet" : "Build packet")}</button>
    </div>
    <DswPacket packet={packet} />
  </window.DsModal>;
}

// Presence-only health for the research + creative keys. Never shows a value.
function DswHealthStrip() {
  const gh = window.DsUseResource("/gethookd/health", null, 0);
  const eb = window.DsUseResource("/everbee/health", null, 0);
  const cr = window.DsUseResource("/creative/health", null, 0);
  const rows = [["GetHookd (ad intelligence)", gh], ["EverBee (Etsy)", eb], ["Higgsfield (creative)", cr]];
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Research connections</div><div className="faint">Presence only — keys live in dropship.env and never show here. Unkeyed reads Unknown, never a fake number.</div></div></div>
    <div className="dc-room-strip">{rows.map((row) => {
      const res = row[1]; const d = res.data || {};
      const on = !!(d.configured || d.connected || d.ready);
      const detail = d.detail || (res.error ? res.error.message : "Add key in dropship.env");
      return <div key={row[0]}><window.DsChannel name={row[0]} connected={on} detail={detail} /></div>;
    })}</div>
  </div>;
}

function DswCard({ item, onScore, onEdit, onDelete, onPacket, scoring }) {
  const [open, setOpen] = useStateDsw(false);
  const a = item.analysis;
  const score = item.score || (a && a.score);
  const color = DswScoreColor(score);
  const verdict = item.verdict || (a && a.verdict);
  return <div className="card card-pad dsw-card">
    <div className="dsw-card-head">
      <div className="dsw-score" style={{ borderColor: color, color }}>{score ? score : "–"}<small>/10</small></div>
      <div className="dsw-card-title">
        <b>{item.name}</b>
        <small className="faint">stage: {item.stage} · margin {DswMargin(item)}{item.supplier ? " · " + item.supplier : ""}{verdict ? " · " : ""}{verdict ? <span style={{ color }}>{verdict}</span> : null}</small>
      </div>
      <button className="dc-primary dsw-score-btn" disabled={scoring} onClick={() => onScore(item)}>{scoring ? "Midas scoring…" : (a ? "Re-score" : "Score with Midas")}</button>
    </div>
    {a ? <>
      <button className="link dsw-toggle" onClick={() => setOpen(!open)}>{open ? "Hide breakdown" : "Show breakdown"}</button>
      {open && <DswAnalysis a={a} />}
    </> : <div className="dsw-empty-hint">Not scored yet — hit “Score with Midas” for the 1–10 read, winning numbers, and ad plays.</div>}
    <div className="dc-mini-actions">
      {item.sourceUrl && <a className="link" href={item.sourceUrl} target="_blank" rel="noreferrer">Source ↗</a>}
      {onPacket && <button className="link" onClick={() => onPacket(item)} title="Evidence + breakeven math + kill flags">Build packet</button>}
      <button className="link" onClick={() => onEdit(item)}>Edit</button>
      <button className="link" onClick={() => onDelete(item.id)}>Delete</button>
    </div>
  </div>;
}

function DropshipWatch() {
  const watch = window.DsUseResource("/watchlist", "items", 30000);
  const [open, setOpen] = useStateDsw(false);
  const [editing, setEditing] = useStateDsw(null);
  const [scoringId, setScoringId] = useStateDsw(null);
  const [err, setErr] = useStateDsw("");
  const [packetSeed, setPacketSeed] = useStateDsw(null);
  const items = Array.isArray(watch.data) ? watch.data : (watch.data && watch.data.items) || [];
  const scored = items.filter((i) => i.score);
  const avg = scored.length ? Math.round(scored.reduce((s, i) => s + Number(i.score || 0), 0) / scored.length) : 0;
  const top = scored.reduce((m, i) => (Number(i.score || 0) > Number((m && m.score) || 0) ? i : m), null);

  const score = async (item) => {
    setScoringId(item.id); setErr("");
    try { await window.DsRequest("/hawk/watch", { body: { id: item.id } }); watch.refresh(); }
    catch (e) { setErr("Midas: " + e.message); } finally { setScoringId(null); }
  };
  const openPacket = (it) => setPacketSeed({
    name: it.name || "", channel: "dropship",
    price: it.price || "", landedCost: it.cost || "", shipDays: it.shipDays || "",
  });
  const del = async (id) => { if (!window.confirm("Remove this watched product?")) return; try { await window.DsRequest("/watchlist/delete", { body: { id } }); watch.refresh(); } catch (e) { window.alert(e.message); } };

  return <div className="dc-page">
    <window.DsPageHead title="Product Watch" copy="Products on your radar you can't dropship yet. Midas rates each 1–10 with winning numbers, why it should win, and what ads to make." actions={<><button className="dc-outline" onClick={() => setPacketSeed({})}><window.Icons.Target size={14}/> Build packet</button><button className="dc-primary" onClick={() => { setEditing(null); setOpen(true); }}><window.Icons.Plus size={14}/> Add product</button></>} />
    <div className="dc-kpi-grid">
      <window.DsKpi label="Watching" value={items.length} sub="on the radar" icon="Watch"/>
      <window.DsKpi label="Scored" value={scored.length} sub={(items.length - scored.length) + " to score"} icon="Target" color="#8B5CF6"/>
      <window.DsKpi label="Avg score" value={avg ? avg + "/10" : "—"} sub="Midas rating" icon="Trend" color={DswScoreColor(avg)}/>
      <window.DsKpi label="Top pick" value={top ? (top.score + "/10") : "—"} sub={top ? top.name : "score some products"} icon="Flame" color={DswScoreColor(top && top.score)}/>
    </div>
    {err && <div className="dc-form-error">{err}</div>}
    <DswHealthStrip />
    <DswDiscover onAdded={watch.refresh} />
    <DswTrending onAdded={watch.refresh} />
    <DswCompetitorAds />
    <window.DsState loading={watch.loading} error={watch.error} empty={!items.length} icon="Watch" title="Nothing on watch yet" copy="Pull trending products above, or add one you spotted — then let Midas score it." onRetry={watch.refresh}>
      <div className="dsw-grid">
        {items.map((it) => <DswCard key={it.id} item={it} scoring={scoringId === it.id} onScore={score} onEdit={(i) => { setEditing(i); setOpen(true); }} onDelete={del} onPacket={openPacket} />)}
      </div>
    </window.DsState>
    {open && <DswAddModal item={editing} onClose={() => setOpen(false)} onSaved={watch.refresh} />}
    {packetSeed && <DswPacketModal seed={packetSeed} onClose={() => setPacketSeed(null)} />}
  </div>;
}

Object.assign(window, { DropshipWatch });
