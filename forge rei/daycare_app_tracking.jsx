// Daycare · App Tracking — how each center's families use the parent app: adoption, coins,
// Pass progress, payments. Read-only: one RPC per center (app_tracking, Supabase migration
// 202610060001). The only action is Resend login (same route as Parent Logins).
// Spec: A Touch of Blessings — Brand Kit/docs/superpowers/specs/2026-10-06-app-tracking-and-login-fixes-design.md
const { useState: useStateDat } = React;

const DAT_CENTERS = [["921", "ATOB 921"], ["2318", "ATOB 2318"], ["1923", "A Mother's Touch"]];
const DAT_LOC = { "921": "11111111-1111-1111-1111-111111111111", "2318": "22222222-2222-2222-2222-222222222222", "1923": "44444444-4444-4444-4444-444444444444" };

function datAgo(iso) {
  if (!iso) return null;
  const days = Math.floor((Date.now() - Date.parse(iso)) / 86400000);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : days + " days ago";
}
const datMoney = (n) => "$" + Number(n || 0).toFixed(2);
const datTh = (cols) => <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>;

function DatCenter({ center }) {
  const res = window.DcxUseResource("/app-tracking?center=" + center, "tracking", 60000);
  const [busy, setBusy] = useStateDat("");
  const [credentials, setCredentials] = useStateDat(null);
  const [open, setOpen] = useStateDat("");
  const t = res.data && !Array.isArray(res.data) ? res.data : null;
  const amt = center === "1923";
  const coinName = amt ? "Heart Coins" : "Blessing Coins";
  const passName = amt ? "Touch Pass" : "Blessings Pass";

  const resend = async (f) => {
    if (!window.confirm("Text " + f.name + " a fresh login PIN through GoHighLevel? Their current PIN stops working and any signed-in phone is signed out.")) return;
    setBusy(f.profile_id);
    try {
      const payload = await window.DcxRequest("/guardian/resend-login", { body: { profile_id: f.profile_id, location_id: DAT_LOC[center] } });
      if (payload.queued) window.alert("It's after 9pm — the login text is queued and goes out after 8am with a fresh PIN.");
      else if (payload.provision) setCredentials(payload.provision);
      res.refresh();
    } catch (error) { window.alert(error.message); }
    finally { setBusy(""); }
  };

  if (!t) return <window.DcxState loading={res.loading} error={res.error} onRetry={res.refresh} empty={!res.loading && !res.error} icon="Children" title="No data for this center" copy="Nothing came back — refresh to try again." />;
  const tot = t.totals || {};
  const fams = (t.families || []).slice().sort((a, b) => ((b.has_login && !b.last_sign_in_at) - (a.has_login && !a.last_sign_in_at)) || String(a.name).localeCompare(String(b.name)));
  const kids = t.children || [];
  const orders = kids.flatMap((k) => (k.open_orders || []).map((o) => ({ ...o, child: k.name })));
  const owed = kids.flatMap((k) => (k.prizes_owed || []).map((p) => ({ ...p, child: k.name })));

  return <React.Fragment>
    {res.error && <div className="dc-form-hint" style={{ color: "#f28b82" }}>Couldn't refresh ({res.error.message}) — showing the last load.</div>}
    <div className="dc-kpi-grid">
      <window.DcxKpi label="Families on the app" value={(tot.signed_in_ever || 0) + " of " + (tot.families || 0)} sub={(tot.active_7d || 0) + " active this week"} icon="Children" />
      <window.DcxKpi label="Never signed in" value={tot.never_signed_in || 0} sub="login made, not used yet" icon="Shield" color="#f6c979" />
      <window.DcxKpi label="Phone alerts on" value={tot.push_on || 0} sub="families with push" icon="Bell" />
      <window.DcxKpi label={coinName + " outstanding"} value={tot.coins_outstanding || 0} sub={(tot.open_orders || 0) + " store orders waiting"} icon="Rewards" />
      <window.DcxKpi label="Prizes owed" value={tot.prizes_owed || 0} sub={passName} icon="Check" />
      <window.DcxKpi label="Unpaid" value={datMoney(tot.unpaid_total)} sub={(tot.autopay_on || 0) + " on autopay"} icon="Billing" />
    </div>

    <div className="card dc-table-wrap"><div className="card-title" style={{ padding: "14px 16px 0" }}>Family adoption</div>
      <table className="lead-table dc-table">{datTh(["Parent", "Login", "Last seen", "Alerts", "Autopay", "Unpaid", "Last payment", ""])}<tbody>
        {fams.map((f) => <tr key={f.profile_id}>
          <td><b>{f.name}</b></td>
          <td>{f.login_id ? <code>{f.login_id}</code> : <span className="quiet">No login</span>}</td>
          <td>{f.last_sign_in_at ? datAgo(f.last_sign_in_at) : <span style={{ color: "#f28b82" }}>never</span>}</td>
          <td>{f.push_devices > 0 ? "On" : <span className="quiet">Off</span>}</td>
          <td>{f.autopay_on ? "On" : <span className="quiet">Off</span>}</td>
          <td>{Number(f.unpaid_total) > 0 ? <span style={{ color: "#f6c979" }}>{datMoney(f.unpaid_total)} ({f.unpaid_invoices})</span> : <span className="quiet">—</span>}</td>
          <td>{f.last_payment_at ? datMoney(f.last_payment_amount) + " · " + datAgo(f.last_payment_at) : <span className="quiet">—</span>}</td>
          <td><div className="dc-row-actions">{f.has_login && <button disabled={busy === f.profile_id} onClick={() => resend(f)}>{busy === f.profile_id ? "Sending…" : "Resend login"}</button>}</div></td>
        </tr>)}
      </tbody></table>{!fams.length && <div className="dc-inline-empty">No parent accounts at this center yet.</div>}</div>

    <div className="card dc-table-wrap"><div className="card-title" style={{ padding: "14px 16px 0" }}>Children · {coinName} + {passName}{t.season ? " · " + t.season.name + " (" + t.season.starts_on + " → " + t.season.ends_on + ")" : " · no active season"}</div>
      <table className="lead-table dc-table">{datTh(["Child", "Classroom", coinName, passName + " level", "XP", "Rank", "Prizes owed"])}<tbody>
        {kids.map((k) => <React.Fragment key={k.child_id}>
          <tr style={{ cursor: "pointer" }} onClick={() => setOpen(open === k.child_id ? "" : k.child_id)}>
            <td><b>{k.name}</b>{k.nickname && <small style={{ display: "block", opacity: .6 }}>{k.nickname}</small>}</td>
            <td>{k.classroom || <span className="quiet">Unassigned</span>}</td>
            <td>{k.coin_balance}</td><td>{k.pass_level}</td><td>{k.pass_xp}</td>
            <td>{k.rank_name || <span className="quiet">—</span>}</td>
            <td>{(k.prizes_owed || []).length ? <span style={{ color: "#f6c979" }}>{k.prizes_owed.length}</span> : <span className="quiet">0</span>}</td>
          </tr>
          {open === k.child_id && <tr><td colSpan={7}><small>{(k.recent_coins || []).length ? k.recent_coins.map((c, i) => <span key={i} style={{ display: "block" }}>{new Date(c.created_at).toLocaleDateString()} · {c.kind} · {c.amount > 0 ? "+" : ""}{c.amount} · {c.reason_label || ""}</span>) : "No coin activity yet."}</small></td></tr>}
        </React.Fragment>)}
      </tbody></table>{!kids.length && <div className="dc-inline-empty">No active children at this center.</div>}</div>

    <div className="dc-report-grid">
      <div className="card card-pad"><div className="card-title">Store orders waiting</div>{orders.length ? orders.map((o) => <div key={o.order_no} className="faint">#{o.order_no} · {o.child} · {o.total} {coinName} · {datAgo(o.placed_at)}</div>) : <div className="faint">None — all handed over.</div>}</div>
      <div className="card card-pad"><div className="card-title">{passName} · prizes owed + top 5</div>{owed.length ? owed.map((p, i) => <div key={i} style={{ color: "#f6c979" }}>{p.child} · L{p.level} {p.title} · claimed {datAgo(p.claimed_at)}</div>) : <div className="faint">No prizes waiting.</div>}<div style={{ marginTop: "10px" }}>{(t.leaderboard || []).map((r, i) => <div key={i} className="faint">{i + 1}. {r.nickname || r.name} · L{r.pass_level} · {r.pass_xp} XP</div>)}</div></div>
    </div>
    {credentials && <window.DcoProvisionCredentials provision={credentials} onClose={() => setCredentials(null)} />}
  </React.Fragment>;
}

function DaycareAppTracking() {
  const [center, setCenter] = useStateDat("921");
  const tabs = <div className="dc-locbar-tabs">{DAT_CENTERS.map(([code, label]) => <button key={code} className={center === code ? "active" : ""} onClick={() => setCenter(code)}>{label}</button>)}</div>;
  return <div className="dc-page">
    <window.DcxPageHead title="App Tracking" eyebrow="PARENT APP" copy="How each center's families use the app — who's signed in, coins, Pass progress, payments. Updates every minute. Read-only." actions={tabs} />
    <DatCenter key={center} center={center} />
  </div>;
}

Object.assign(window, { DaycareAppTracking });
