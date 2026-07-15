// dropship_watch.jsx — Product Watch: track products you can't dropship yourself yet,
// and let Hawk score each 1–10 with winning numbers, why it wins, and what ads to make.
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
  return <window.DsModal title={item && item.id ? "Edit watched product" : "Add product to watch"} copy="Track a product you can't dropship yourself yet — Hawk scores it on demand." onClose={onClose}>
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

function DswCard({ item, onScore, onEdit, onDelete, scoring }) {
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
      <button className="dc-primary dsw-score-btn" disabled={scoring} onClick={() => onScore(item)}>{scoring ? "Hawk scoring…" : (a ? "Re-score" : "Score with Hawk")}</button>
    </div>
    {a ? <>
      <button className="link dsw-toggle" onClick={() => setOpen(!open)}>{open ? "Hide breakdown" : "Show breakdown"}</button>
      {open && <DswAnalysis a={a} />}
    </> : <div className="dsw-empty-hint">Not scored yet — hit “Score with Hawk” for the 1–10 read, winning numbers, and ad plays.</div>}
    <div className="dc-mini-actions">
      {item.sourceUrl && <a className="link" href={item.sourceUrl} target="_blank" rel="noreferrer">Source ↗</a>}
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
  const items = Array.isArray(watch.data) ? watch.data : (watch.data && watch.data.items) || [];
  const scored = items.filter((i) => i.score);
  const avg = scored.length ? Math.round(scored.reduce((s, i) => s + Number(i.score || 0), 0) / scored.length) : 0;
  const top = scored.reduce((m, i) => (Number(i.score || 0) > Number((m && m.score) || 0) ? i : m), null);

  const score = async (item) => {
    setScoringId(item.id); setErr("");
    try { await window.DsRequest("/hawk/watch", { body: { id: item.id } }); watch.refresh(); }
    catch (e) { setErr("Hawk: " + e.message); } finally { setScoringId(null); }
  };
  const del = async (id) => { if (!window.confirm("Remove this watched product?")) return; try { await window.DsRequest("/watchlist/delete", { body: { id } }); watch.refresh(); } catch (e) { window.alert(e.message); } };

  return <div className="dc-page">
    <window.DsPageHead title="Product Watch" copy="Products on your radar you can't dropship yet. Hawk rates each 1–10 with winning numbers, why it should win, and what ads to make." actions={<button className="dc-primary" onClick={() => { setEditing(null); setOpen(true); }}><window.Icons.Plus size={14}/> Add product</button>} />
    <div className="dc-kpi-grid">
      <window.DsKpi label="Watching" value={items.length} sub="on the radar" icon="Watch"/>
      <window.DsKpi label="Scored" value={scored.length} sub={(items.length - scored.length) + " to score"} icon="Target" color="#8B5CF6"/>
      <window.DsKpi label="Avg score" value={avg ? avg + "/10" : "—"} sub="Hawk rating" icon="Trend" color={DswScoreColor(avg)}/>
      <window.DsKpi label="Top pick" value={top ? (top.score + "/10") : "—"} sub={top ? top.name : "score some products"} icon="Flame" color={DswScoreColor(top && top.score)}/>
    </div>
    {err && <div className="dc-form-error">{err}</div>}
    <window.DsState loading={watch.loading} error={watch.error} empty={!items.length} icon="Watch" title="Nothing on watch yet" copy="Add a product you spotted — then let Hawk score it." onRetry={watch.refresh}>
      <div className="dsw-grid">
        {items.map((it) => <DswCard key={it.id} item={it} scoring={scoringId === it.id} onScore={score} onEdit={(i) => { setEditing(i); setOpen(true); }} onDelete={del} />)}
      </div>
    </window.DsState>
    {open && <DswAddModal item={editing} onClose={() => setOpen(false)} onSaved={watch.refresh} />}
  </div>;
}

Object.assign(window, { DropshipWatch });
