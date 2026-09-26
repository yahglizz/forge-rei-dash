// daycare_pass.jsx — Blessings Pass, the owner half of the season pass the parent app runs
// (portal-app.tsx PassPage + lib/pass.ts). XP, levels and ranks are computed in the database
// from attendance + behavior; this page shows the board and edits the config: seasons,
// the per-level reward track, rank names/perks, and the prize hand-over queue.
// Money perks are typed in here by the owner — nothing is auto-applied to invoices.
const { useState: useStateDcp, useMemo: useMemoDcp } = React;

// Season dates are plain calendar days. DcxDate() runs them through new Date("YYYY-MM-DD"),
// which is UTC midnight — the evening before in Philadelphia — so a season ending Dec 31
// would read "Dec 30". Pin to local noon instead.
function DcpDay(value) {
  return value ? new Date(value + "T12:00:00").toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" }) : "—";
}

function DcpKidName(child) {
  return child ? window.DcxChildName(child) : "Child";
}

// ── Leaderboard ─────────────────────────────────────────────────────────────

function DcpBoard({ rows }) {
  if (!rows.length) return <div className="card dc-state"><window.Icons.Pass size={27} /><b>No one on the board yet</b><span>Start a season under Season setup — children rank up from their attendance and green days.</span></div>;
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Season leaderboard</div><div className="faint">Parents see the nickname only — real names show for their own children</div></div></div>
    <div className="dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>#</th><th>Child</th><th>Nickname</th><th>Classroom</th><th>Level</th><th>XP</th><th>Rank</th><th>Days</th></tr></thead><tbody>
      {rows.map((row) => <tr key={row.place + "-" + row.nickname}>
        <td><b className="tabnum" style={{ color: row.place <= 3 ? "#F4B860" : "var(--text-2)" }}>{row.place}</b></td>
        <td><b>{row.child_name || "—"}</b></td>
        <td>{row.nickname || "—"}</td>
        <td className="faint">{row.classroom || "Unassigned"}</td>
        <td><span className="dc-week">LV {row.level}</span></td>
        <td className="tabnum">{row.xp}</td>
        <td>{row.rank_name || "—"}</td>
        <td className="tabnum faint">{row.lifetime_days}</td>
      </tr>)}
    </tbody></table></div>
  </div>;
}

// ── Season setup ────────────────────────────────────────────────────────────

function DcpSeasons({ payload, onDone }) {
  const seasons = payload.seasons || [];
  const [picked, setPicked] = useStateDcp(seasons.length ? seasons[0].id : "");
  const [edit, setEdit] = useStateDcp(null);
  const [rewardEdit, setRewardEdit] = useStateDcp(null);
  const [busy, setBusy] = useStateDcp("");
  const season = seasons.find((item) => item.id === picked) || seasons[0];
  const rewards = (payload.rewards || []).filter((item) => season && item.season_id === season.id);
  const today = window.DcxToday();
  const remove = async (reward) => {
    if (!window.confirm("Delete \"" + reward.title + "\" from the pass?")) return;
    setBusy(reward.id);
    try { await window.DcxRequest("/pass/reward/delete", { body: { id: reward.id } }); onDone(); }
    catch (error) { window.alert(error.message.indexOf("foreign key") >= 0 ? "A family already claimed this reward, so it stays on the pass." : error.message); }
    finally { setBusy(""); }
  };
  return <>
    <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Seasons</div><div className="faint">The pass resets each season. The season running today is the live one.</div></div><button className="dc-primary" onClick={() => setEdit({})}><window.Icons.Plus size={14} /> New season</button></div>
      {seasons.length ? <div className="dc-locbar-tabs">{seasons.map((item) => { const live = item.starts_on <= today && today <= item.ends_on; return <button key={item.id} className={season && season.id === item.id ? "active" : ""} onClick={() => setPicked(item.id)}>{item.name}{live ? " · LIVE" : ""}</button>; })}</div> : <div className="dc-inline-empty">No seasons yet — create the first one to turn the pass on.</div>}
      {season && <div className="faint" style={{ marginTop: 10 }}>{DcpDay(season.starts_on)} → {DcpDay(season.ends_on)} · {season.xp_per_level} XP per level · {season.max_level} levels · <button className="dc-quiet" onClick={() => setEdit(season)}>Edit season</button></div>}
    </div>

    {season && <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Reward track</div><div className="faint">Coins drop straight into the child's Blessing Coins. Prizes (free lunch, free day, discount…) wait in the hand-over queue.</div></div><button className="dc-primary" onClick={() => setRewardEdit({ season_id: season.id, kind: "coins" })}><window.Icons.Plus size={14} /> Add reward</button></div>
      <div className="dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Level</th><th>Reward</th><th>Type</th><th></th></tr></thead><tbody>
        {rewards.map((reward) => <tr key={reward.id}>
          <td><span className="dc-week">LV {reward.level}</span></td>
          <td><b>{reward.title}</b>{reward.description && <small className="faint" style={{ display: "block" }}>{reward.description}</small>}</td>
          <td>{reward.kind === "coins" ? <b style={{ color: "#F4B860" }}>+{reward.coin_amount} coins</b> : <span>Prize</span>}</td>
          <td><div className="dc-row-actions"><button onClick={() => setRewardEdit(reward)}>Edit</button><button className="danger" disabled={busy === reward.id} onClick={() => remove(reward)}>{busy === reward.id ? "…" : "Delete"}</button></div></td>
        </tr>)}
      </tbody></table>{!rewards.length && <div className="dc-inline-empty">No rewards on this season yet.</div>}</div>
    </div>}

    {edit && <DcpSeasonForm season={edit.id ? edit : null} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); onDone(); }} />}
    {rewardEdit && <DcpRewardForm reward={rewardEdit} maxLevel={season ? season.max_level : 20} onClose={() => setRewardEdit(null)} onSaved={() => { setRewardEdit(null); onDone(); }} />}
  </>;
}

function DcpSeasonForm({ season, onClose, onSaved }) {
  const [form, setForm] = useStateDcp({ name: "", starts_on: window.DcxToday(), ends_on: "", xp_per_level: 400, max_level: 20, ...(season || {}) });
  const [busy, setBusy] = useStateDcp(false);
  const [error, setError] = useStateDcp("");
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });
  const save = async () => {
    if (!String(form.name).trim()) { setError("Name the season (e.g. Fall 2026)."); return; }
    if (!form.starts_on || !form.ends_on) { setError("Pick a start and end date."); return; }
    setBusy(true); setError("");
    try { await window.DcxRequest("/pass/season/save", { body: { id: season && season.id, name: String(form.name).trim(), starts_on: form.starts_on, ends_on: form.ends_on, xp_per_level: Number(form.xp_per_level), max_level: Number(form.max_level) } }); onSaved(); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };
  return <window.DcxModal title={season ? "Edit season" : "New season"} copy="+100 XP per day checked in, +50 more for a green day. A full-time child earns about 700 XP a week." onClose={onClose}>
    {error && <div className="dc-form-error">{error}</div>}
    <div className="dc-form-grid">
      <window.DcxField label="Season name *"><input autoFocus value={form.name} onChange={set("name")} placeholder="Fall 2026" /></window.DcxField>
      <window.DcxField label="Starts *"><input type="date" value={form.starts_on} onChange={set("starts_on")} /></window.DcxField>
      <window.DcxField label="Ends *"><input type="date" value={form.ends_on} onChange={set("ends_on")} /></window.DcxField>
      <window.DcxField label="XP per level"><input type="number" min="50" step="50" value={form.xp_per_level} onChange={set("xp_per_level")} /></window.DcxField>
      <window.DcxField label="Levels"><input type="number" min="1" max="100" value={form.max_level} onChange={set("max_level")} /></window.DcxField>
    </div>
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save season"}</button></div>
  </window.DcxModal>;
}

function DcpRewardForm({ reward, maxLevel, onClose, onSaved }) {
  const [form, setForm] = useStateDcp({ level: 1, title: "", description: "", kind: "coins", coin_amount: "", ...reward });
  const [busy, setBusy] = useStateDcp(false);
  const [error, setError] = useStateDcp("");
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });
  const save = async () => {
    if (!String(form.title).trim()) { setError("Give the reward a title parents will read."); return; }
    if (form.kind === "coins" && !(Math.round(Number(form.coin_amount)) > 0)) { setError("Coin rewards need a positive amount."); return; }
    setBusy(true); setError("");
    const body = { id: reward.id, season_id: reward.season_id, level: Number(form.level), title: String(form.title).trim(), description: String(form.description || "").trim() || null, kind: form.kind, coin_amount: form.kind === "coins" ? Math.round(Number(form.coin_amount)) : null };
    try { await window.DcxRequest("/pass/reward/save", { body }); onSaved(); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };
  return <window.DcxModal title={reward.id ? "Edit reward" : "Add reward"} copy="Parents see this on the pass the moment you save. For a discount or free day, write the exact terms — that is the promise." onClose={onClose}>
    {error && <div className="dc-form-error">{error}</div>}
    <div className="dc-form-grid">
      <window.DcxField label="Unlocks at level *"><input type="number" min="1" max={maxLevel} value={form.level} onChange={set("level")} /></window.DcxField>
      <window.DcxField label="Type"><select value={form.kind} onChange={set("kind")}><option value="coins">Blessing Coins</option><option value="prize">Prize (handed over by staff)</option></select></window.DcxField>
      <window.DcxField label="Title *"><input value={form.title} onChange={set("title")} placeholder={form.kind === "coins" ? "25 Blessing Coins" : "Free lunch on us"} /></window.DcxField>
      {form.kind === "coins" && <window.DcxField label="Coins *"><input type="number" min="1" step="1" value={form.coin_amount || ""} onChange={set("coin_amount")} /></window.DcxField>}
      <window.DcxField label="Details" wide><textarea rows="2" value={form.description || ""} onChange={set("description")} placeholder="Optional — e.g. one weekday, book with the front desk" /></window.DcxField>
    </div>
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save reward"}</button></div>
  </window.DcxModal>;
}

// ── Ranks & perks ───────────────────────────────────────────────────────────

function DcpRanks({ payload, onDone }) {
  const ranks = payload.ranks || [];
  const [edit, setEdit] = useStateDcp(null);
  return <>
    <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">Lifetime ranks</div><div className="faint">Never reset. Days attended plus pre-app tenure from each child's enrollment date. A family's membership tier is its highest-ranked child.</div></div><button className="dc-primary" onClick={() => setEdit({})}><window.Icons.Plus size={14} /> Add rank</button></div>
      <div className="dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>From day</th><th>Rank</th><th>Membership perk</th><th></th></tr></thead><tbody>
        {ranks.map((rank) => <tr key={rank.id}>
          <td className="tabnum">{rank.min_days}</td>
          <td><b>{rank.name}</b></td>
          <td className={rank.perk ? "" : "faint"}>{rank.perk || "No perk yet"}</td>
          <td><div className="dc-row-actions"><button onClick={() => setEdit(rank)}>Edit</button></div></td>
        </tr>)}
      </tbody></table>{!ranks.length && <div className="dc-inline-empty">No ranks yet.</div>}</div>
    </div>
    {edit && <DcpRankForm rank={edit.id ? edit : null} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); onDone(); }} />}
  </>;
}

function DcpRankForm({ rank, onClose, onSaved }) {
  const [form, setForm] = useStateDcp({ name: "", min_days: "", perk: "", ...(rank || {}) });
  const [busy, setBusy] = useStateDcp("");
  const [error, setError] = useStateDcp("");
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });
  const save = async () => {
    if (!String(form.name).trim()) { setError("Name the rank."); return; }
    setBusy("save"); setError("");
    try { await window.DcxRequest("/pass/rank/save", { body: { id: rank && rank.id, name: String(form.name).trim(), min_days: Number(form.min_days), perk: String(form.perk || "").trim() || null } }); onSaved(); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(""); }
  };
  const remove = async () => {
    if (!window.confirm("Remove the " + rank.name + " rank?")) return;
    setBusy("delete");
    try { await window.DcxRequest("/pass/rank/delete", { body: { id: rank.id } }); onSaved(); }
    catch (requestError) { setError(requestError.message); } finally { setBusy(""); }
  };
  return <window.DcxModal title={rank ? "Edit rank" : "Add rank"} copy="A perk is a promise to every family at this rank — write the exact terms (amount, how often)." onClose={onClose}>
    {error && <div className="dc-form-error">{error}</div>}
    <div className="dc-form-grid">
      <window.DcxField label="Rank name *"><input autoFocus value={form.name} onChange={set("name")} /></window.DcxField>
      <window.DcxField label="Reached at day *"><input type="number" min="0" step="1" value={form.min_days} onChange={set("min_days")} /></window.DcxField>
      <window.DcxField label="Membership perk" wide><input value={form.perk || ""} onChange={set("perk")} placeholder="Optional — e.g. one free day per season" /></window.DcxField>
    </div>
    <div className="dc-modal-actions">{rank && <button className="dc-danger" disabled={Boolean(busy)} onClick={remove}>{busy === "delete" ? "Removing…" : "Remove"}</button>}<button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={Boolean(busy)} onClick={save}>{busy === "save" ? "Saving…" : "Save rank"}</button></div>
  </window.DcxModal>;
}

// ── Hand-over queue ─────────────────────────────────────────────────────────

function DcpClaims({ payload, onDone }) {
  const [busy, setBusy] = useStateDcp("");
  const claims = payload.claims || [];
  const open = claims.filter((claim) => !claim.fulfilled_at);
  const fulfill = async (claim) => {
    setBusy(claim.id);
    try { await window.DcxRequest("/pass/claim/fulfill", { body: { claim_id: claim.id } }); onDone(); }
    catch (error) { window.alert(error.message); } finally { setBusy(""); }
  };
  return <div className="card card-pad dc-panel">
    <div className="dc-panel-head"><div><div className="card-title">Claimed rewards</div><div className="faint">Prizes wait here until someone marks them handed over. A discount is applied by hand on the family's invoice.</div></div><b>{open.length} waiting</b></div>
    <div className="dc-table-wrap"><table className="lead-table dc-table"><thead><tr><th>Child</th><th>Reward</th><th>Claimed</th><th>Status</th></tr></thead><tbody>
      {claims.map((claim) => { const reward = claim.pass_rewards || {}; return <tr key={claim.id}>
        <td><b>{DcpKidName(claim.children)}</b></td>
        <td>{reward.title || "Reward"} <span className="faint">· LV {reward.level}</span></td>
        <td className="faint">{window.DcxDate(claim.claimed_at, true)}</td>
        <td>{claim.fulfilled_at ? <span className="faint">{reward.kind === "coins" ? "Coins added" : "Handed over"}</span> : <button className="dc-primary" disabled={busy === claim.id} onClick={() => fulfill(claim)}>{busy === claim.id ? "…" : "Mark handed over"}</button>}</td>
      </tr>; })}
    </tbody></table>{!claims.length && <div className="dc-inline-empty">No rewards claimed yet.</div>}</div>
  </div>;
}

// ── Page ────────────────────────────────────────────────────────────────────

function DaycarePass() {
  const pass = window.DcxUseResource("/pass", null, 30000);
  const [tab, setTab] = useStateDcp("board");
  const payload = pass.data && !Array.isArray(pass.data) ? pass.data : {};
  const board = Array.isArray(payload.leaderboard) ? payload.leaderboard : [];
  const today = window.DcxToday();
  const stats = useMemoDcp(() => {
    const live = (payload.seasons || []).find((item) => item.starts_on <= today && today <= item.ends_on);
    const waiting = (payload.claims || []).filter((claim) => !claim.fulfilled_at).length;
    const top = board.length ? board[0] : null;
    return { live, waiting, top, claimed: (payload.claims || []).length };
  }, [payload, board, today]);

  const tabs = [["board", "Leaderboard"], ["claims", "Hand-over queue"], ["season", "Season setup"], ["ranks", "Ranks & perks"]];
  return <div className="dc-page">
    <window.DcxPageHead title="Blessings Pass" eyebrow="MEMBERSHIP & SEASON PASS" copy="Children level up from attendance and green days; families climb ranks the longer they stay. Rewards unlock per level." actions={<button className="dc-outline" onClick={pass.refresh}><window.Icons.Activity size={14} /> Refresh</button>} />
    <window.DcxState loading={pass.loading} error={pass.error} onRetry={pass.refresh}><>
      <div className="dc-kpi-grid">
        <window.DcxKpi label="Live Season" value={stats.live ? stats.live.name : "None"} sub={stats.live ? "ends " + DcpDay(stats.live.ends_on) : "create one under Season setup"} icon="Pass" color="#F4B860" />
        <window.DcxKpi label="Top of the Board" value={stats.top ? stats.top.child_name || stats.top.nickname : "—"} sub={stats.top ? "Level " + stats.top.level + " · " + stats.top.xp + " XP" : "no XP yet"} icon="Spark" color="#8B5CF6" />
        <window.DcxKpi label="Prizes Waiting" value={stats.waiting} sub="claimed, not handed over" icon="Rewards" color="#2DD4BF" />
        <window.DcxKpi label="Rewards Claimed" value={stats.claimed} sub="all seasons (latest 200)" icon="Check" color="#38BDF8" />
      </div>
      <div className="dc-locbar"><span className="dc-locbar-label"><window.Icons.Pass size={13} /> View</span><div className="dc-locbar-tabs">{tabs.map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>)}</div></div>
      {tab === "board" && <DcpBoard rows={board} />}
      {tab === "claims" && <DcpClaims payload={payload} onDone={pass.refresh} />}
      {tab === "season" && <DcpSeasons payload={payload} onDone={pass.refresh} />}
      {tab === "ranks" && <DcpRanks payload={payload} onDone={pass.refresh} />}
    </></window.DcxState>
  </div>;
}

Object.assign(window, { DaycarePass, DcpBoard, DcpSeasons, DcpRanks, DcpClaims });
