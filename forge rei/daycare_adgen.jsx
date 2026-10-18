// daycare_adgen.jsx — the daycare Ad Generator (Growth → Ad Studio tab + a Dashboard card).
// Concepts are TEXT (Claude, no credits). Every image is ONE owner tap: quote → confirm →
// /adgen/generate (the backend re-checks engine, cost and the daily cap). Building an ad is
// the existing PAUSED-only /nova/create-ad. No video in this build.
const { useState: useStateDcg, useEffect: useEffectDcg } = React;

const DCG_FORMATS = [["1:1", "1:1 feed"], ["9:16", "9:16 stories / reels"]];

function DcgCredits(v) { return v == null ? "Unknown" : (Math.round(Number(v) * 100) / 100) + " credits"; }

function DcgEngineBadge({ eng }) {
  const ready = !!(eng && eng.ready);
  const c = ready ? "#22C55E" : "#F4B860";
  const label = !eng ? "CHECKING…" : ready ? "IMAGES READY · " + String(eng.engine).toUpperCase() : "IMAGES NOT READY";
  return <span className="dc-live dc-mock" style={{ color: c, borderColor: c }}><i style={{ background: c }} /> {label}</span>;
}

// Engine status strip: what will draw the image, credits, today's spend vs the cap, the next step.
function DcgEngineStrip({ st, onRecheck, busy }) {
  const eng = st && st.engine;
  if (!eng) return null;
  const cap = eng.cap || {}, cli = eng.cli || {}, rest = eng.rest || {};
  const restTxt = !rest.keyed ? "API key not set" : rest.funded === false ? "API credit pool EMPTY" : rest.funded ? "API pool funded" : "API pool balance Unknown";
  const cliTxt = !cli.installed ? "CLI not installed" : cli.loggedIn === false ? "CLI not logged in" : cli.needsWorkspace ? "CLI needs login + workspace" : cli.ready ? "CLI ready · " + DcgCredits(cli.credits) + " on account" : "CLI not answering";
  return <div className="card card-pad dc-panel dcg-strip">
    <div className="dc-panel-head" style={{ flexWrap: "wrap", gap: 8 }}>
      <div style={{ minWidth: 0 }}><div className="card-title">Image engine</div><div className="faint">{restTxt} · {cliTxt}</div></div>
      <div className="dcg-actions"><DcgEngineBadge eng={eng} /><button className="link" disabled={busy} onClick={onRecheck}>{busy ? "Checking…" : "Re-check"}</button></div>
    </div>
    <div className="dcg-note" style={{ marginTop: 8 }}>{eng.nextStep}</div>
    <div className="faint dcg-note" style={{ marginTop: 6 }}>Today: {DcgCredits(cap.spentToday)} of {cap.daily} credit cap{cap.unknownToday ? " · " + cap.unknownToday + " image(s) of Unknown cost" : ""} · every image is your tap, quoted first.</div>
  </div>;
}

function DcgAsset({ a }) {
  return <div className="dcg-asset">
    <a href={a.imageUrl} target="_blank" rel="noopener noreferrer"><img src={a.imageUrl} alt={"Generated ad image, " + a.format} loading="lazy" /></a>
    <div className="faint dcg-note">{a.format} · {a.engine} · {a.model} · {DcgCredits(a.credits)}{a.createdAt ? " · " + new Date(a.createdAt).toLocaleDateString([], { month: "short", day: "numeric" }) : ""}</div>
    <details><summary className="faint" style={{ cursor: "pointer", fontSize: 11 }}>Prompt</summary><div className="faint dcg-note" style={{ whiteSpace: "pre-wrap" }}>{a.prompt}</div></details>
  </div>;
}

function DcgConceptCard({ idea, eng, metaReady, onChanged }) {
  const [fmt, setFmt] = useStateDcg(idea.format === "9:16" ? "9:16" : "1:1");
  const [variant, setVariant] = useStateDcg(0);
  const [quotes, setQuotes] = useStateDcg({});        // "fmt|variant" → quote result
  const [busy, setBusy] = useStateDcg("");
  const [msg, setMsg] = useStateDcg(null);
  const [url, setUrl] = useStateDcg("");
  const built = idea.status === "built";
  const assets = idea.assets || [];
  const ready = !!(eng && eng.ready);
  const tgt = idea.targeting || {};
  const cap = (eng && eng.cap) || {};
  const q = quotes[fmt + "|" + variant] || null;
  const qFresh = !!q;
  const run = async (label, fn) => { setBusy(label); setMsg(null); try { await fn(); } catch (e) { setMsg({ ok: false, text: (e && e.message) || "Failed." }); } finally { setBusy(""); } };

  // Quotes BOTH formats (read-only `generate cost`, no job) so each format shows its own price.
  const doQuote = () => run("quote", async () => {
    const next = { ...quotes };
    for (const f of DCG_FORMATS) {
      const out = await window.DcxRequest("/adgen/quote", { body: { ideaId: idea.id, format: f[0], variant } });
      if (out && out.ok === false) throw new Error(out.error || "Quote failed.");
      next[f[0] + "|" + variant] = out;
    }
    setQuotes(next);
  });
  const doGenerate = () => {
    if (!ready) { setMsg({ ok: false, text: "Not generating — " + ((eng && eng.nextStep) || "no image engine is ready.") }); return; }
    const est = qFresh ? (q.credits != null ? "≈ " + DcgCredits(q.credits) : "cost Unknown") : "cost not quoted yet (it is checked before anything runs)";
    if (!window.confirm("Generate ONE " + fmt + " image for “" + (idea.title || "this concept") + "”?\n\nEngine: " + eng.engine + " · " + est + "\nToday: " + DcgCredits(cap.spentToday) + " of " + cap.daily + " credit cap.")) return;
    run("gen", async () => {
      let out = await window.DcxRequest("/adgen/generate", { body: { ideaId: idea.id, format: fmt, variant, confirm: true } });
      if (out && out.needsConfirm && !out.ok) {
        if (!window.confirm((out.error || "Cost Unknown.") + "\n\nGenerate anyway? It still counts against today's cap.")) { setMsg({ ok: false, text: "Not generated — cost Unknown and you chose to wait." }); return; }
        out = await window.DcxRequest("/adgen/generate", { body: { ideaId: idea.id, format: fmt, variant, confirm: true, confirmUnknown: true } });
      }
      if (!out || out.ok === false) throw new Error((out && out.error) || "Image not generated.");
      setMsg({ ok: true, text: "Image ready · " + out.engine + " · " + DcgCredits(out.credits) + "." });
      onChanged();
    });
  };
  const doAttach = () => run("attach", async () => {
    const out = await window.DcxRequest("/nova/image", { body: { id: idea.id, imageUrl: url.trim() } });
    if (out && out.ok === false) throw new Error(out.error || "Not attached.");
    setUrl(""); onChanged();
  });
  const doBuild = () => {
    if (!window.confirm("Build this as a PAUSED campaign on Meta? Nothing serves and nothing spends until you turn it on in Meta.")) return;
    run("build", async () => {
      const out = await window.DcxRequest("/nova/create-ad", { body: { id: idea.id } });
      if (out && out.ok === false) throw new Error(out.detail || out.error || "Build failed.");
      onChanged();
    });
  };
  const doDiscard = () => {
    if (!window.confirm("Discard this concept and its images from the studio?")) return;
    run("discard", async () => { await window.DcxRequest("/nova/discard", { body: { id: idea.id } }); onChanged(); });
  };

  return <div className="card card-pad dc-panel dcg-card">
    <div className="dc-panel-head" style={{ flexWrap: "wrap", gap: 8 }}>
      <div style={{ minWidth: 0 }}><div className="card-title">{idea.title || "Concept"}</div><div className="faint">{idea.angle || ""}</div></div>
      <span className="dc-live dc-mock" style={built ? { color: "#22C55E", borderColor: "#22C55E" } : null}><i style={built ? { background: "#22C55E" } : null} /> {built ? "BUILT · PAUSED" : assets.length ? assets.length + " IMAGE" + (assets.length > 1 ? "S" : "") : idea.imageUrl ? "IMAGE ATTACHED" : "DRAFT"}</span>
    </div>
    <div className="dcg-copy">
      {idea.headline && <div><b>{idea.headline}</b></div>}
      {idea.hook && <div className="faint">{idea.hook}</div>}
      {idea.primaryText && <div>{idea.primaryText}</div>}
      <div className="faint" style={{ fontSize: 12 }}>CTA {idea.cta || "—"}{idea.dailyBudget ? " · $" + idea.dailyBudget + "/day suggested" : ""}{tgt.age_min ? " · ages " + tgt.age_min + "–" + tgt.age_max : ""}{tgt.radius_miles ? " · " + tgt.radius_miles + " mi" : ""}{idea.targetingNote ? " · " + idea.targetingNote : ""}</div>
      <div className="dcg-evidence"><b>Evidence</b> · {idea.evidence || "Unknown — no evidence cited"}</div>
    </div>

    {assets.length > 0 ? <div className="dcg-assets">{assets.slice().reverse().map((a) => <DcgAsset key={a.id} a={a} />)}</div>
      : idea.imageUrl ? <div className="dcg-assets"><div className="dcg-asset"><img src={idea.imageUrl} alt="Attached ad image" loading="lazy" /><div className="faint dcg-note">pasted image</div></div></div> : null}

    {!built && <>
      <div className="dcg-actions" style={{ marginTop: 10 }} role="group" aria-label="Image format">
        {DCG_FORMATS.map((f) => { const fq = quotes[f[0] + "|" + variant]; return <button key={f[0]} type="button" className={fmt === f[0] ? "dc-primary" : "dc-outline"} aria-pressed={fmt === f[0]} onClick={() => setFmt(f[0])}>{f[1]}{fq ? " · " + (fq.credits != null ? "≈ " + DcgCredits(fq.credits) : "cost Unknown") : ""}</button>; })}
        {idea.imagePromptAlt && [0, 1].map((v) => <button key={v} type="button" className={variant === v ? "dc-primary" : "dc-outline"} aria-pressed={variant === v} onClick={() => setVariant(v)}>Prompt {v ? "B" : "A"}</button>)}
      </div>
      <details style={{ marginTop: 8 }}><summary className="faint" style={{ cursor: "pointer", fontSize: 12 }}>Image prompt {variant ? "B" : "A"}</summary>
        <div className="faint dcg-note dcg-prompt">{variant ? idea.imagePromptAlt : idea.imagePrompt}</div>
        <button className="link" onClick={() => navigator.clipboard && navigator.clipboard.writeText(variant ? idea.imagePromptAlt : idea.imagePrompt)}>Copy prompt</button>
      </details>
      {qFresh && <div className="dcg-note" style={{ marginTop: 8 }}>{q.credits != null ? "≈ " + DcgCredits(q.credits) + " via " + q.engine + (q.withinCap === false ? " — over today's cap" : "") : "Cost Unknown" + (q.note ? " — " + q.note : "")}</div>}
      <div className="dcg-actions" style={{ marginTop: 10 }}>
        <button className="dc-outline" disabled={!!busy} onClick={doQuote}>{busy === "quote" ? "Quoting…" : "Quote cost"}</button>
        <button className="dc-primary" disabled={!!busy} onClick={doGenerate} title={ready ? "One image, after you confirm" : (eng && eng.nextStep) || ""}>{busy === "gen" ? "Generating… (can take minutes)" : "Generate image" + (qFresh && q.credits != null ? " (≈ " + DcgCredits(q.credits) + ")" : "")}</button>
        <button className="dc-outline" disabled title="Video generation isn't built yet">Video (coming)</button>
      </div>
      <div className="dcg-actions" style={{ marginTop: 8 }}>
        <input className="input" placeholder="…or paste an image URL" value={url} onChange={(e) => setUrl(e.target.value)} style={{ flex: "1 1 160px", minWidth: 0 }} aria-label="Image URL" />
        <button className="dc-outline" disabled={!url.trim() || !!busy} onClick={doAttach}>Attach</button>
      </div>
      <div className="dcg-actions" style={{ marginTop: 10 }}>
        <button className="dc-primary" disabled={!!busy || !metaReady} onClick={doBuild} title={metaReady ? "Creates the real Meta campaign, PAUSED" : "Needs META_ACCESS_TOKEN in daycare.env"}>{busy === "build" ? "Building…" : "Build PAUSED ad"}</button>
        <button className="dc-outline" disabled={!!busy} onClick={doDiscard}>Discard</button>
      </div>
      {!metaReady && <div className="faint dcg-note" style={{ marginTop: 6 }}>Build needs META_ACCESS_TOKEN in daycare.env.</div>}
    </>}
    {built && <div className="dc-form-hint" style={{ marginTop: 10 }}><window.Icons.Shield size={14} /> Built and <b>PAUSED</b> on Meta — nothing serving, nothing spending.{idea.meta && idea.meta.url ? <> · <a href={idea.meta.url} target="_blank" rel="noreferrer">Open in Meta</a></> : null}</div>}
    {msg && <div className="dcg-note" style={{ marginTop: 8, color: msg.ok ? "#22C55E" : "#EF4444" }} role="status">{msg.text}</div>}
  </div>;
}

// Telegram approval cards (daycare_ads_tg): what was sent to the daycare chat and what you did with it.
const DCG_KIND = { optimize: "Proposal", concept: "New concept", launch: "Launch", launch2: "2nd launch", undo: "Receipt" };
const DCG_STATE_C = { pending: "#F4B860", launched: "#22C55E", applied: "#22C55E", built: "#22C55E", failed: "#EF4444" };

function DcgTgCards() {
  const res = window.DcxUseResource("/adgen/cards", "dcg-cards", 60000);
  const d = (res.data && !Array.isArray(res.data)) ? res.data : null;
  if (res.error) return <div className="dc-form-hint">Telegram cards Unknown — {res.error.message}</div>;
  if (!d) return null;
  const cards = (d.cards || []).filter((c) => c.kind !== "undo").slice(0, 12);
  return <div className="card card-pad dc-panel dcg-strip" style={{ marginTop: 12 }}>
    <div className="dc-panel-head" style={{ flexWrap: "wrap", gap: 8 }}>
      <div style={{ minWidth: 0 }}><div className="card-title">Telegram cards</div><div className="faint">Proposals, new concepts and launches sent to the daycare chat — each one is your tap there.</div></div>
      <span className="dc-live dc-mock" style={d.pending ? { color: "#F4B860", borderColor: "#F4B860" } : null}><i style={d.pending ? { background: "#F4B860" } : null} /> {d.enabled === false ? "CARDS OFF" : d.pending + " WAITING"}</span>
    </div>
    {!cards.length && <div className="faint dcg-note" style={{ marginTop: 8 }}>No cards sent yet.</div>}
    {cards.map((c) => <div key={c.id} className="dcg-note" style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap", minWidth: 0 }}>
      <b style={{ color: DCG_STATE_C[c.state] || undefined, minWidth: 64 }}>{String(c.state || "").toUpperCase()}</b>
      <span className="faint">{DCG_KIND[c.kind] || c.kind}</span>
      <span style={{ flex: "1 1 140px", minWidth: 0, overflowWrap: "anywhere" }}>{c.title || "—"}{c.usd ? " · $" + c.usd + "/day" : ""}{c.credits != null ? " · " + DcgCredits(c.credits) : ""}{c.noImage ? " · no image: " + c.noImage : ""}{c.sent === false ? " · not delivered" + (c.sendError ? " (" + c.sendError + ")" : "") : ""}</span>
      <span className="faint">{c.createdAt ? new Date(c.createdAt).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""}</span>
    </div>)}
  </div>;
}

function DcgAdStudio() {
  const res = window.DcxUseResource("/adgen/status", "dcg-adgen", 60000);
  const st = (res.data && !Array.isArray(res.data)) ? res.data : null;
  const [ideas, setIdeas] = useStateDcg([]);
  const [busy, setBusy] = useStateDcg("");
  const [msg, setMsg] = useStateDcg(null);
  const [eng, setEng] = useStateDcg(null);
  useEffectDcg(() => { if (st && st.engine) setEng(st.engine); }, [st]);
  const loadIdeas = async () => {
    try { const out = await window.DcxRequest("/nova/ideas"); setIdeas(Array.isArray(out && out.ideas) ? out.ideas : []); }
    catch (e) { setMsg({ ok: false, text: "Saved concepts unavailable — " + ((e && e.message) || "error") }); }
  };
  useEffectDcg(() => { loadIdeas(); }, []);
  const changed = () => { loadIdeas(); if (res.refresh) res.refresh(); };
  const recheck = async () => {
    setBusy("check");
    try { const out = await window.DcxRequest("/adgen/status?fresh=1"); if (out && out.engine) setEng(out.engine); }
    catch (e) { setMsg({ ok: false, text: (e && e.message) || "Re-check failed." }); }
    finally { setBusy(""); }
  };
  const generate = async () => {
    setBusy("concepts"); setMsg(null);
    try {
      const out = await window.DcxRequest("/nova/generate", { body: {} });
      if (out && out.ok === false) throw new Error(out.error || "No concepts drafted.");
      setMsg({ ok: true, text: (out.next || []).length + " new concepts drafted." + (out.packetUnknown ? " The live ad packet was Unknown" + (out.packetError ? " (" + out.packetError + ")" : "") + " — they cite no ad numbers." : "") });
      await loadIdeas();
    } catch (e) { setMsg({ ok: false, text: (e && e.message) || "Solomon couldn't draft concepts." }); }
    finally { setBusy(""); }
  };
  return <div className="dc-page">
    <window.DcxPageHead title="Ad Generator" eyebrow="GROWTH · AD STUDIO"
      copy="Solomon reads the live Meta numbers, the business brief and the brand rules, then drafts complete enrollment ad concepts. Images are one tap each, quoted first and capped per day. Building an ad creates it PAUSED."
      actions={<DcgEngineBadge eng={eng} />} />
    {res.error && <div className="dc-form-hint" style={{ color: "#EF4444" }}>Engine status Unknown — {res.error.message}</div>}
    <DcgEngineStrip st={eng ? { engine: eng } : null} onRecheck={recheck} busy={busy === "check"} />
    <DcgTgCards />
    <div className="dc-hero-actions" style={{ margin: "12px 0" }}>
      <button className="dc-primary" onClick={generate} disabled={!!busy}><window.Icons.Bot size={15} /> {busy === "concepts" ? "Drafting concepts… (about a minute)" : "Generate ad concepts"}</button>
      <span className="faint dcg-note" style={{ alignSelf: "center" }}>Text only — uses no image credits.</span>
    </div>
    {msg && <div className="dc-form-hint" style={{ color: msg.ok ? undefined : "#EF4444" }} role="status">{msg.text}</div>}
    {!ideas.length && busy !== "concepts" && <div className="dc-all-clear"><window.Icons.Bot size={22} /><div><b>No ad concepts yet</b><span>Tap “Generate ad concepts”. They stay here until you build or discard them.</span></div></div>}
    {ideas.map((idea) => <DcgConceptCard key={idea.id} idea={idea} eng={eng} metaReady={!!(st && st.metaReady)} onChanged={changed} />)}
  </div>;
}

// Dashboard home card — compact, read-only; opens the Ad Studio tab.
function DcaAdGenCard() {
  const res = window.DcxUseResource("/adgen/status", "dcg-adgen-card", 120000);
  const st = (res.data && !Array.isArray(res.data)) ? res.data : null;
  const eng = st && st.engine;
  const cap = (eng && eng.cap) || {};
  const tg = window.DcxUseResource("/adgen/cards", "dcg-cards-home", 120000);
  const tgPending = tg.data && !Array.isArray(tg.data) ? tg.data.pending : null;
  const open = () => { window.__dcaGrowthTab = "ideas"; window.GoTo("Growth"); };
  return <div className="card card-pad dc-panel dcg-home">
    <div className="dc-panel-head" style={{ flexWrap: "wrap", gap: 8 }}>
      <div style={{ minWidth: 0 }}><div className="card-title">Ad Generator</div><div className="faint">Concepts + images for enrollment ads</div></div>
      <div className="dcg-actions">{st && <DcgEngineBadge eng={eng} />}<button className="link" onClick={open}>Open Ad Studio</button></div>
    </div>
    {res.error && <div className="dc-inline-empty">Ad Generator status Unknown — {res.error.message}</div>}
    {st && <>
      <div className="dcg-note" style={{ marginTop: 8 }}>{st.ideas} concept{st.ideas === 1 ? "" : "s"} · {st.drafts} draft{st.drafts === 1 ? "" : "s"} · {st.assets} image{st.assets === 1 ? "" : "s"} · {st.built} built (paused)</div>
      {eng && !eng.ready && <div className="faint dcg-note" style={{ marginTop: 6 }}>{eng.nextStep}</div>}
      {eng && <div className="faint dcg-note" style={{ marginTop: 6 }}>Today: {DcgCredits(cap.spentToday)} of {cap.daily} credit cap.</div>}
      {tgPending != null && <div className="dcg-note" style={{ marginTop: 6 }}>{tgPending} Telegram card{tgPending === 1 ? "" : "s"} waiting for your tap.</div>}
    </>}
  </div>;
}

Object.assign(window, { DcgAdStudio, DcgConceptCard, DcgEngineStrip, DcaAdGenCard, DcgTgCards });
