// daycare_rewards.jsx — Blessing Coins, the owner half of the reward system the
// parent/staff app already runs (portal-app.tsx + lib/coins.ts). Same two tables,
// same award reasons, same rules: balances are summed from the ledger, the ledger
// is append-only, and prizes are retired (active=false) rather than deleted.
const { useState: useStateDcr, useMemo: useMemoDcr } = React;

// Reward icons are stored as lucide name strings the phone app understands. This
// console has its own icon set, so map to the closest local glyph — resolved to a
// variable first, never a computed JSX tag (collision rule).
const DCR_ICON_MAP = {
  Popcorn: "Meals", CupSoda: "Meals", Candy: "Spark", Cookie: "Meals",
  IceCreamCone: "Spark", Sandwich: "Meals", Pizza: "Meals", Gift: "Rewards",
  Sun: "Spark", Star: "Spark", Sticker: "Spark", Music: "Spark",
  Clapperboard: "Spark", Coins: "Rewards", Award: "Rewards", Trophy: "Rewards",
  Heart: "Spark", Utensils: "Meals", ChevronR: "ChevronR",
};
// The names the phone app offers in its own picker — keep both stores speaking one vocabulary.
const DCR_ICON_CHOICES = ["Gift", "Popcorn", "CupSoda", "Candy", "Cookie", "IceCreamCone", "Sandwich", "Pizza", "Star", "Coins", "Trophy", "Heart"];

function DcrIcon({ name, size = 18 }) {
  const Ico = window.Icons[DCR_ICON_MAP[name] || name] || window.Icons.Rewards || window.Icons.Spark;
  return <Ico size={size} />;
}

function DcrCoins({ value }) {
  const amount = Number(value) || 0;
  return <b className="tabnum" style={{ color: amount > 0 ? "#F4B860" : "var(--text-3)" }}>{amount}</b>;
}

// ── Give Coins ────────────────────────────────────────────────────────────────

function DcrGive({ payload, kids, rooms, onDone }) {
  const [picked, setPicked] = useStateDcr([]);
  const [room, setRoom] = useStateDcr("all");
  const [busy, setBusy] = useStateDcr(false);
  const [notice, setNotice] = useStateDcr("");
  const [custom, setCustom] = useStateDcr(false);
  const [adjust, setAdjust] = useStateDcr(null);
  const balances = payload.balances || {};
  const reasons = Array.isArray(payload.awardReasons) ? payload.awardReasons : [];
  const visible = kids.filter((child) => room === "all" || child.classroom_id === room);
  const toggle = (id) => setPicked((current) => current.includes(id) ? current.filter((value) => value !== id) : current.concat(id));

  const award = async (label, amount, note) => {
    if (!picked.length) { setNotice("Pick at least one child first."); return; }
    setBusy(true); setNotice("");
    try {
      await window.DcxRequest("/coins/award", { body: { child_ids: picked, amount, reason_label: label, note: note || null } });
      setNotice("Awarded +" + amount + " " + label + " to " + picked.length + (picked.length === 1 ? " child." : " children."));
      setPicked([]); setCustom(false); onDone();
    } catch (error) { setNotice(error.message); } finally { setBusy(false); }
  };

  if (!kids.length) return <div className="card dc-state"><window.Icons.Children size={27} /><b>No children enrolled yet</b><span>Enroll a child and they will show up here to award coins.</span></div>;
  return <>
    {rooms.length > 1 && <div className="dc-locbar"><span className="dc-locbar-label"><window.Icons.Classrooms size={13} /> Classroom</span><div className="dc-locbar-tabs"><button className={room === "all" ? "active" : ""} onClick={() => setRoom("all")}>All rooms</button>{rooms.map((item) => <button key={item.id} className={room === item.id ? "active" : ""} onClick={() => setRoom(item.id)}>{item.name}</button>)}</div></div>}

    <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Choose children</div><div className="faint">Tap to select — one award covers everyone picked</div></div><b>{picked.length ? picked.length + " selected" : "None selected"}</b></div>
      <div className="dc-day-grid">{visible.map((child) => { const on = picked.includes(child.id); const roomName = (child.classrooms && child.classrooms.name) || (rooms.find((item) => item.id === child.classroom_id) || {}).name || "Unassigned"; return <button key={child.id} aria-pressed={on} style={on ? { borderColor: "#2DD4BF", background: "rgba(45,212,191,.08)" } : null} onClick={() => toggle(child.id)}><span>{on ? <window.Icons.Check size={18} /> : <window.Icons.Children size={18} />}</span><b>{window.DcxChildName(child)}</b><small>{roomName}</small><DcrCoins value={balances[child.id]} /></button>; })}</div>
      {!visible.length && <div className="dc-inline-empty">No children in that classroom.</div>}
    </div>

    <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Award for</div><div className="faint">Same reasons and amounts the staff app uses</div></div>{notice && <span className={notice.indexOf("Awarded") === 0 ? "dc-saved" : "dc-error-text"}>{notice}</span>}</div>
      <div className="dc-day-grid">
        {reasons.map((reason) => <button key={reason.label} disabled={busy || !picked.length} onClick={() => award(reason.label, reason.amount)}><span><window.Icons.Spark size={18} /></span><b>{reason.label}</b><small style={{ color: "#F4B860", fontWeight: 700 }}>+{reason.amount}</small></button>)}
        <button disabled={busy || !picked.length} onClick={() => setCustom(true)}><span><window.Icons.Plus size={18} /></span><b>Custom</b><small>Any positive amount</small></button>
      </div>
    </div>

    <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Balance correction</div><div className="faint">Adds a signed adjustment row — it never edits history</div></div></div>
      <div className="dc-locbar-tabs">{kids.map((child) => <button key={child.id} onClick={() => setAdjust(child)}>{window.DcxChildName(child)} · {Number(balances[child.id]) || 0}</button>)}</div>
    </div>

    {custom && <DcrCustomAward count={picked.length} busy={busy} onClose={() => setCustom(false)} onSubmit={(amount, note) => award("Custom", amount, note)} />}
    {adjust && <DcrAdjust child={adjust} balance={Number(balances[adjust.id]) || 0} onClose={() => setAdjust(null)} onSaved={() => { setAdjust(null); onDone(); }} />}
  </>;
}

function DcrCustomAward({ count, busy, onClose, onSubmit }) {
  const [amount, setAmount] = useStateDcr("");
  const [note, setNote] = useStateDcr("");
  const [error, setError] = useStateDcr("");
  const value = Math.round(Number(amount));
  const submit = () => {
    if (!(value > 0)) { setError("Amount must be a positive whole number."); return; }
    if (!note.trim()) { setError("Add a short note so the ledger explains itself."); return; }
    onSubmit(value, note.trim());
  };
  return <window.DcxModal title="Custom award" copy={"A one-off positive amount for " + count + (count === 1 ? " child." : " children.")} onClose={onClose}>
    {error && <div className="dc-form-error">{error}</div>}
    <div className="dc-form-grid"><window.DcxField label="Coins to award"><input autoFocus type="number" min="1" step="1" value={amount} onChange={(event) => setAmount(event.target.value)} /></window.DcxField><window.DcxField label="Note"><input value={note} onChange={(event) => setNote(event.target.value)} placeholder="What was this for?" /></window.DcxField></div>
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={submit}>{busy ? "Awarding…" : "Award +" + (value > 0 ? value : 0)}</button></div>
  </window.DcxModal>;
}

function DcrAdjust({ child, balance, onClose, onSaved }) {
  const [amount, setAmount] = useStateDcr("");
  const [note, setNote] = useStateDcr("");
  const [busy, setBusy] = useStateDcr(false);
  const [error, setError] = useStateDcr("");
  const value = Math.round(Number(amount));
  const save = async () => {
    if (!Number.isFinite(value) || value === 0) { setError("Use a non-zero amount — a minus sign removes coins."); return; }
    if (!note.trim()) { setError("Adjustments require a reason."); return; }
    setBusy(true); setError("");
    try { await window.DcxRequest("/coins/adjust", { body: { child_id: child.id, amount: value, note: note.trim() } }); onSaved(); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };
  return <window.DcxModal title={"Adjust " + window.DcxChildName(child) + "'s balance"} copy={"Current balance: " + balance + " Blessing Coins. A negative amount corrects an over-award."} onClose={onClose}>
    {error && <div className="dc-form-error">{error}</div>}
    <div className="dc-form-grid"><window.DcxField label="Adjustment (+ credit / − debit)"><input autoFocus type="number" step="1" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="e.g. -5" /></window.DcxField><window.DcxField label="Reason (required)"><input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Why this correction?" /></window.DcxField></div>
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Apply adjustment"}</button></div>
  </window.DcxModal>;
}

// ── Store (redeem) ────────────────────────────────────────────────────────────

function DcrStore({ payload, kids, onDone }) {
  const [redeem, setRedeem] = useStateDcr(null);
  const items = (payload.rewardItems || []).filter((item) => item.active);
  if (!items.length) return <div className="card dc-state"><window.Icons.Rewards size={27} /><b>The prize store is empty</b><span>Add prizes under Manage catalog — they appear in the app the moment you save.</span></div>;
  return <>
    <div className="dc-classroom-grid">{items.map((item) => <button key={item.id} className="card card-pad dc-classroom" style={{ "--room-color": "#F4B860", textAlign: "left" }} onClick={() => setRedeem({ item })}>
      <span className="dc-classroom-icon"><DcrIcon name={item.icon} size={19} /></span>
      <div><h3>{item.name}</h3><p>{item.description || "Prize store item"}</p></div>
      <small style={{ color: "#F4B860", fontWeight: 700 }}>{item.cost} coins</small>
    </button>)}
      <button className="card card-pad dc-classroom" style={{ "--room-color": "#2DD4BF", textAlign: "left" }} onClick={() => setRedeem({ custom: true })}>
        <span className="dc-classroom-icon"><window.Icons.Plus size={19} /></span>
        <div><h3>Custom redemption</h3><p>Something that is not in the catalog</p></div>
        <small className="faint">Any amount</small>
      </button>
    </div>
    {redeem && <DcrRedeem kids={kids} balances={payload.balances || {}} item={redeem.item} onClose={() => setRedeem(null)} onSaved={() => { setRedeem(null); onDone(); }} />}
  </>;
}

function DcrRedeem({ kids, balances, item, onClose, onSaved }) {
  const [childId, setChildId] = useStateDcr(kids.length ? kids[0].id : "");
  const [label, setLabel] = useStateDcr("");
  const [amount, setAmount] = useStateDcr("");
  const [busy, setBusy] = useStateDcr(false);
  const [error, setError] = useStateDcr("");
  const cost = item ? Number(item.cost) : Math.round(Number(amount));
  const balance = Number(balances[childId]) || 0;
  const save = async () => {
    if (!childId) { setError("Pick the child redeeming this."); return; }
    if (!item && !(cost > 0)) { setError("Enter a positive cost."); return; }
    if (!item && !label.trim()) { setError("Name what they are redeeming."); return; }
    setBusy(true); setError("");
    const body = item ? { child_id: childId, reward_item_id: item.id } : { child_id: childId, amount: cost, reason_label: label.trim() };
    try { await window.DcxRequest("/coins/redeem", { body }); onSaved(); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };
  return <window.DcxModal title={item ? "Redeem " + item.name : "Custom redemption"} copy={item ? item.cost + " coins will be deducted from the child's balance." : "Deduct coins for something outside the catalog."} onClose={onClose}>
    {error && <div className="dc-form-error">{error}</div>}
    <div className="dc-form-grid">
      <window.DcxField label="Child"><select value={childId} onChange={(event) => setChildId(event.target.value)}>{kids.map((child) => <option key={child.id} value={child.id}>{window.DcxChildName(child)} · {Number(balances[child.id]) || 0} coins</option>)}</select></window.DcxField>
      {!item && <window.DcxField label="Reward name"><input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="e.g. Extra story time" /></window.DcxField>}
      {!item && <window.DcxField label="Cost in coins"><input type="number" min="1" step="1" value={amount} onChange={(event) => setAmount(event.target.value)} /></window.DcxField>}
    </div>
    {/* The app lets a redemption run a balance negative too; the owner should see it coming. */}
    {cost > balance && <div className="dc-form-hint"><window.Icons.AlertTriangle size={14} /> This leaves the balance at {balance - cost}. Redeem anyway only if you meant to front them the prize.</div>}
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy ? "Redeeming…" : "Redeem for " + (cost > 0 ? cost : 0) + " coins"}</button></div>
  </window.DcxModal>;
}

// ── Catalog ───────────────────────────────────────────────────────────────────

function DcrCatalog({ payload, onDone }) {
  const [edit, setEdit] = useStateDcr(null);
  const [busy, setBusy] = useStateDcr("");
  const items = payload.rewardItems || [];
  const setActive = async (item, active) => {
    setBusy(item.id);
    try { await window.DcxRequest("/reward-item/active", { body: { id: item.id, active } }); onDone(); }
    catch (error) { window.alert(error.message); } finally { setBusy(""); }
  };
  return <>
    <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Prize catalog</div><div className="faint">Retired prizes stay on past redemptions — they are hidden, never deleted</div></div><button className="dc-primary" onClick={() => setEdit({})}><window.Icons.Plus size={14} /> Add prize</button></div>
      <div className="dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Prize</th><th>Cost</th><th>Icon</th><th>Status</th><th></th></tr></thead><tbody>
        {items.map((item) => <tr key={item.id}>
          <td><div className="dc-person"><div className="dc-avatar"><DcrIcon name={item.icon} size={15} /></div><div><b>{item.name}</b><small>{item.description || "No description"}</small></div></div></td>
          <td><DcrCoins value={item.cost} /></td>
          <td className="faint">{item.icon || "Gift"}</td>
          <td>{item.active ? <span className="dc-week">ACTIVE</span> : <span className="faint">Retired</span>}</td>
          <td><div className="dc-row-actions"><button onClick={() => setEdit(item)}>Edit</button><button className={item.active ? "danger" : ""} disabled={busy === item.id} onClick={() => setActive(item, !item.active)}>{busy === item.id ? "…" : item.active ? "Retire" : "Restore"}</button></div></td>
        </tr>)}
      </tbody></table>{!items.length && <div className="dc-inline-empty">No prizes yet — add the first one.</div>}</div>
    </div>
    {edit && <DcrItemForm item={edit.id ? edit : null} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); onDone(); }} />}
  </>;
}

function DcrItemForm({ item, onClose, onSaved }) {
  const [form, setForm] = useStateDcr({ name: "", description: "", cost: "", icon: "Gift", ...(item || {}) });
  const [busy, setBusy] = useStateDcr(false);
  const [error, setError] = useStateDcr("");
  const save = async () => {
    if (!String(form.name).trim()) { setError("Give the prize a name."); return; }
    if (!(Math.round(Number(form.cost)) > 0)) { setError("Cost must be a positive whole number of coins."); return; }
    setBusy(true); setError("");
    const body = { id: item && item.id, name: String(form.name).trim(), description: String(form.description || "").trim() || null, cost: Math.round(Number(form.cost)), icon: form.icon || "Gift" };
    try { await window.DcxRequest("/reward-item/save", { body }); onSaved(); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };
  return <window.DcxModal title={item ? "Edit prize" : "Add prize"} copy="Saved to the shared database — the staff and parent app see it immediately." onClose={onClose}>
    {error && <div className="dc-form-error">{error}</div>}
    <div className="dc-form-grid">
      <window.DcxField label="Prize name *"><input autoFocus value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></window.DcxField>
      <window.DcxField label="Cost in coins *"><input type="number" min="1" step="1" value={form.cost} onChange={(event) => setForm({ ...form, cost: event.target.value })} /></window.DcxField>
      <window.DcxField label="Icon"><select value={form.icon || "Gift"} onChange={(event) => setForm({ ...form, icon: event.target.value })}>{DCR_ICON_CHOICES.map((name) => <option key={name} value={name}>{name}</option>)}</select></window.DcxField>
      <window.DcxField label="Description" wide><textarea rows="2" value={form.description || ""} onChange={(event) => setForm({ ...form, description: event.target.value })} /></window.DcxField>
    </div>
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : item ? "Save prize" : "Add prize"}</button></div>
  </window.DcxModal>;
}

// ── Page ──────────────────────────────────────────────────────────────────────

function DaycareRewards() {
  const rewards = window.DcxUseResource("/rewards", null, 20000);
  const childrenResource = window.DcxUseResource("/children", "children", 30000);
  const roomsResource = window.DcxUseResource("/classrooms", "classrooms", 60000);
  const [tab, setTab] = useStateDcr("give");
  const payload = rewards.data && !Array.isArray(rewards.data) ? rewards.data : {};
  const kids = (Array.isArray(childrenResource.data) ? childrenResource.data : []).filter((child) => child.active !== false);
  const rooms = Array.isArray(roomsResource.data) ? roomsResource.data : [];
  const refresh = () => { rewards.refresh(); childrenResource.refresh(); };

  const totals = useMemoDcr(() => {
    const balances = payload.balances || {};
    const values = kids.map((child) => Number(balances[child.id]) || 0);
    const outstanding = values.reduce((sum, value) => sum + value, 0);
    const top = values.length ? Math.max.apply(null, values) : 0;
    return { outstanding, top, active: (payload.rewardItems || []).filter((item) => item.active).length };
  }, [payload, kids]);

  const tabs = [["give", "Give coins"], ["store", "Store"], ["catalog", "Manage catalog"]];
  return <div className="dc-page">
    <window.DcxPageHead title="Blessing Coins" eyebrow="POSITIVE REINFORCEMENT" copy="The same reward ledger the staff and parent app run on — award, redeem, and manage the prize store from here." actions={<button className="dc-outline" onClick={refresh}><window.Icons.Activity size={14} /> Refresh</button>} />
    <window.DcxState loading={rewards.loading || childrenResource.loading} error={rewards.error || childrenResource.error} onRetry={refresh}><>
      <div className="dc-kpi-grid">
        <window.DcxKpi label="Coins Outstanding" value={totals.outstanding} sub="across every enrolled child" icon="Rewards" color="#F4B860" />
        <window.DcxKpi label="Highest Balance" value={totals.top} sub="top saver right now" icon="Spark" color="#8B5CF6" />
        <window.DcxKpi label="Active Prizes" value={totals.active} sub="visible in the app store" icon="Meals" color="#2DD4BF" />
        <window.DcxKpi label="Ledger Entries" value={Number(payload.ledgerCount) || 0} sub="awards, redemptions, corrections" icon="CareLogs" color="#38BDF8" />
      </div>

      <div className="dc-locbar"><span className="dc-locbar-label"><window.Icons.Rewards size={13} /> View</span><div className="dc-locbar-tabs">{tabs.map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>)}</div><small className="faint">Every coin written here appears in the family app instantly.</small></div>

      {tab === "give" && <DcrGive payload={payload} kids={kids} rooms={rooms} onDone={refresh} />}
      {tab === "store" && <DcrStore payload={payload} kids={kids} onDone={refresh} />}
      {tab === "catalog" && <DcrCatalog payload={payload} onDone={refresh} />}

      <div className="card card-pad dc-panel">
        <div className="dc-panel-head"><div><div className="card-title">Recent coin activity</div><div className="faint">Newest {Number(payload.recentLimit) || 200} entries — the ledger is append-only</div></div></div>
        <div className="dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Child</th><th>Type</th><th>Coins</th><th>Reason</th><th>When</th></tr></thead><tbody>
          {(payload.coins || []).slice(0, 40).map((row) => <tr key={row.id}>
            <td><b>{window.DcxChildName(row.children)}</b></td>
            <td>{row.kind === "award" ? <span className="dc-week">AWARD</span> : row.kind === "redemption" ? <span className="faint">Redemption</span> : <span className="dc-week partial">ADJUSTMENT</span>}</td>
            <td><DcrCoins value={row.amount} /></td>
            <td className="dc-long-cell">{row.reason_label}{row.note ? " — " + row.note : ""}</td>
            <td className="faint">{window.DcxDate(row.created_at, true)}</td>
          </tr>)}
        </tbody></table>{!(payload.coins || []).length && <div className="dc-inline-empty">No coins awarded yet.</div>}</div>
      </div>
    </></window.DcxState>
  </div>;
}

Object.assign(window, { DaycareRewards, DcrGive, DcrStore, DcrCatalog, DcrIcon });
