// FORGE Mobile — Daycare BILLING tab: paid / unpaid invoices + fee links, text a pay link from the phone.
// Default scope = A Touch of Blessings (both ATOB centers merged) every time the tab mounts; never persisted.
// A Mother's Touch is a separate legal entity (own chip, never merged). QA Sandbox is TEST data: last, muted.
// Hook aliases for this file: MBL. Top-level names: MBL*. Exports: MBLBilling (the tab), MBLFeeSheet (fee-link sheet).
// Uses from m_biz_daycare.jsx at run time (exported on window there): MBDHead, MBDSheet, MBDAuth, MBDAuthLine, MBDThread
// (the fee sheet's "Open the conversation" shows the GHL thread that carried the link — read-only audit).
//
// Reads (no side effects):
//   GET  /api/daycare/locations                         centers (chips)
//   GET  /api/daycare/billing?location_id=<uuid>        invoices, once per center in scope
//   GET  /api/daycare/billing/fees?location_id=<uuid>   Stripe fee links paid / unpaid, once per center
//   GET  /api/daycare/billing/timeline?invoice_id=<id>  link + payment history (lazy, when a sheet opens)
//   GET  /api/daycare/ghl/conversations                 family search for the fee form
// Writes:
//   POST /api/daycare/billing/fee-link     {family,amount,purpose,contact_id?,location_id}  mints a link, sends nothing
//   POST /api/daycare/billing/link/compose {invoice_id,location_id}                                    draft text, sends nothing
// Real texts to a parent: owner taps Send, then window.confirm, then the POST (rule 6):
//   POST /api/daycare/billing/link/send    {invoice_id,message,location_id}   message keeps {{PAY_URL}} once
//   POST /api/daycare/ghl/reply            {contact_id,text}      fee link text
// A failed read is shown as a warning and "-" in the tiles: Unknown, not zero.
const { useState: useStateMBL, useEffect: useEffectMBL, useRef: useRefMBL } = React;

const MBL_ATOB = "11111111-1111-1111-1111-111111111111";
const MBL_ATOB2 = "22222222-2222-2222-2222-222222222222";
const MBL_AMT = "44444444-4444-4444-4444-444444444444";
const MBL_QA = "99999999-9999-9999-9999-999999999999";
const MBL_TOKEN = "{{PAY_URL}}";
const MBL_PURPOSES = [["registration-fee", "Registration fee"], ["deposit", "Deposit"], ["supply-fee", "Supply fee"],
  ["late-fee", "Late fee"], ["other", "Other"]];
const MBL_30D = 30 * 86400 * 1000;

function MBLCents(c) {
  if (c == null || isNaN(c)) return "—";
  return "$" + (c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function MBLWhole(c) { return "$" + Math.round(c / 100).toLocaleString("en-US"); }
function MBLMoneyText(c) { return c % 100 === 0 ? "$" + c / 100 : "$" + (c / 100).toFixed(2); }
function MBLAgo(ts) { const a = window.timeAgoM(ts); return !a ? "" : a === "now" ? "just now" : a + " ago"; }
function MBLDay(d) {
  const s = String(d || "").slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return "";
  return new Date(s + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
function MBLTime(ts) {
  const ms = Date.parse(ts);
  return isNaN(ms) ? "" : new Date(ms).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
function MBLTodayET() { return new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" }); }
function MBLMs(ts) { const ms = Date.parse(ts); return isNaN(ms) ? 0 : ms; }
async function MBLCopy(text) {
  try { await navigator.clipboard.writeText(text); window.hapticM && window.hapticM("success"); return true; }
  catch (_) { return false; }
}
// Plain GET that never throws: a failed read becomes {ok:false, detail} so the screen can say "Unknown", not "0".
async function MBLGet(path) {
  try {
    const r = await fetch(path);
    const j = await r.json().catch(() => null);
    if (j && j.ok) return j;
    return { ok: false, code: j && j.code, detail: (j && (j.detail || j.error)) || "HTTP " + r.status };
  } catch (e) { return { ok: false, detail: (e && e.message) || "network error" }; }
}
function MBLAuthed(x) { return !!x && x.ok === false && !!window.MBDAuth && window.MBDAuth({ data: x, error: x.detail }); }

// ---------------------------------------------------------------- scopes + data
// Chips: merged ATOB (default) · each ATOB center · A Mother's Touch · QA TEST. The last two only when the
// center list says this session can see them.
function MBLScopes(locs) {
  const have = {};
  (locs || []).forEach((l) => { have[l.id] = l.name; });
  const loaded = (locs || []).length > 0;
  const out = [
    { key: "atob", label: "A Touch of Blessings", title: "A Touch of Blessings · both centers", ids: [MBL_ATOB, MBL_ATOB2] },
    { key: MBL_ATOB, label: "921 N 18th", title: (have[MBL_ATOB] || "A Touch of Blessings") + " · 921 N 18th", ids: [MBL_ATOB] },
    { key: MBL_ATOB2, label: "2318 Cecil B. Moore", title: (have[MBL_ATOB2] || "A Touch of Blessings 2") + " · 2318 Cecil B. Moore", ids: [MBL_ATOB2] },
  ];
  if (loaded && have[MBL_AMT]) out.push({ key: MBL_AMT, label: "A Mother's Touch", title: have[MBL_AMT] + " · separate entity", ids: [MBL_AMT] });
  if (loaded && have[MBL_QA]) out.push({ key: MBL_QA, label: "QA TEST", title: "QA Sandbox · TEST data only", ids: [MBL_QA], test: true });
  return out;
}

// One load = invoices + fees for every center in scope. A stale answer (scope changed meanwhile) is dropped.
function MBLLoad(ids) {
  const key = ids.join(",");
  const [st, setSt] = useStateMBL({ loading: true, src: [] });
  const seq = useRefMBL(0);
  async function load() {
    const mine = ++seq.current;
    const src = await Promise.all(ids.map(async (id) => {
      const q = "?location_id=" + encodeURIComponent(id);
      const [inv, fee] = await Promise.all([MBLGet("/api/daycare/billing" + q), MBLGet("/api/daycare/billing/fees" + q)]);
      return { id, inv, fee };
    }));
    if (mine === seq.current) setSt({ loading: false, src });
  }
  useEffectMBL(() => {
    setSt({ loading: true, src: [] });
    load();
    const iv = setInterval(load, 120000);
    return () => { seq.current++; clearInterval(iv); };
  }, [key]);
  return { loading: st.loading, src: st.src, refresh: load };
}

const MBL_ORDER = { overdue: 0, due: 1, unpaidFee: 2, paid: 3, draft: 4, void: 4 };

// Invoices + fee links -> one list. cat: overdue | due | unpaidFee | paid | draft | void.
function MBLRows(src, names) {
  const today = MBLTodayET();
  const rows = [];
  src.forEach((s) => {
    const center = names[s.id] || "";
    if (s.inv.ok) (s.inv.invoices || []).forEach((inv) => {
      const amt = Number(inv.amount) || 0;
      const got = (inv.payments || []).filter((p) => p && (p.status || "succeeded") === "succeeded").reduce((a, p) => a + (Number(p.amount) || 0), 0);
      const bal = Math.max(0, amt - got);
      let cat;
      if (inv.status === "void" || inv.status === "draft") cat = inv.status;
      else if (inv.status === "paid" || bal <= 0) cat = "paid";
      else if (inv.status === "overdue" || (inv.due_on && String(inv.due_on).slice(0, 10) < today)) cat = "overdue";
      else cat = "due";
      rows.push({ kind: "inv", key: "i" + inv.id, cat, center, centerId: s.id, raw: inv,
        cents: Math.round(amt * 100), balCents: Math.round(bal * 100),
        ts: cat === "paid" ? MBLMs(inv.paid_at) || MBLMs(inv.issued_on) : MBLMs(inv.issued_on) });
    });
    if (s.fee.ok) (s.fee.fees || []).forEach((f) => {
      const paid = f.status === "paid";
      rows.push({ kind: "fee", key: "f" + s.id + f.id, cat: paid ? "paid" : "unpaidFee", center, centerId: s.id, raw: f,
        cents: f.amountCents, balCents: paid ? 0 : f.amountCents, ts: MBLMs(paid ? f.paidAt || f.lastActivity : f.lastActivity) });
    });
  });
  rows.sort((a, b) => (MBL_ORDER[a.cat] - MBL_ORDER[b.cat]) || (b.ts - a.ts));
  return rows;
}

// Tiles. A source that failed makes its tiles "-", never 0.
function MBLTotals(rows, src) {
  const invBad = src.some((s) => !s.inv.ok), feeBad = src.some((s) => !s.fee.ok);
  const now = Date.now();
  const unpaid = rows.filter((r) => r.cat === "overdue" || r.cat === "due" || r.cat === "unpaidFee");
  const over = rows.filter((r) => r.cat === "overdue");
  const paid = rows.filter((r) => r.cat === "paid" && r.ts && now - r.ts <= MBL_30D);
  const sum = (a) => a.reduce((t, r) => t + (r.balCents || 0), 0);
  const unknownFees = unpaid.filter((r) => r.kind === "fee" && r.cents == null).length;
  return {
    unpaid: invBad || feeBad || !src.length ? null : { cents: sum(unpaid), n: unpaid.length, unknown: unknownFees },
    overdue: invBad || !src.length ? null : { cents: sum(over), n: over.length },
    paid: invBad || feeBad || !src.length ? null : { cents: paid.reduce((t, r) => t + (r.cents || 0), 0), n: paid.length },
  };
}

// ---------------------------------------------------------------- small pieces
const MBL_PILL = { overdue: ["Overdue", "bad"], due: ["Due", "warn"], unpaidFee: ["Unpaid", "warn"], paid: ["Paid", "ok"], draft: ["Draft", ""], void: ["Void", ""] };
function MBLPill(props) {
  const p = MBL_PILL[props.cat] || ["", ""];
  return <span className={"mbl-pill" + (p[1] ? " " + p[1] : "")}>{p[0]}</span>;
}
function MBLTile(props) {
  return <div className={"mbl-tile" + (props.tone ? " " + props.tone : "")}>
    <small>{props.label}</small><strong>{props.value}</strong><small>{props.sub}</small>
  </div>;
}
function MBLLinkLine(l) {
  if (!l) return "Not sent";
  if (l.paid_at) return "Link paid " + MBLAgo(l.paid_at);
  if (l.status === "failed" || l.status === "undelivered") return "Link failed" + (l.sent_at ? " · " + MBLAgo(l.sent_at) : "");
  const opened = l.opened_at || Number(l.open_count) > 0;
  return "Link sent " + (MBLAgo(l.sent_at) || "") + (opened ? " · opened" + (Number(l.open_count) > 1 ? " ×" + l.open_count : "") : "");
}
function MBLChild(inv) { const c = inv.children; return c ? [c.first_name, c.last_name].filter(Boolean).join(" ") : ""; }
function MBLFirst(name) { return String(name || "").trim().split(/\s+/)[0] || "this parent"; }

function MBLRow(props) {
  const r = props.row, x = r.raw;
  const isInv = r.kind === "inv";
  const title = isInv ? (x.guardian_name || MBLChild(x) || "Invoice") : x.family || "Fee link";
  const bits = isInv
    ? [MBLChild(x) && x.guardian_name ? MBLChild(x) : "", x.invoice_number, r.center, x.due_on && r.cat !== "paid" ? "due " + MBLDay(x.due_on) : ""]
    : [x.label, r.center, x.status === "paid" ? "paid " + MBLAgo(x.paidAt) : x.lastActivity ? "active " + MBLAgo(x.lastActivity) : "no opens"];
  const amount = isInv ? (r.cat === "paid" || r.cat === "void" ? r.cents : r.balCents) : r.cents;
  const flag = isInv && x.reminder_failed === true && r.balCents > 0 ? "Reminder failed" : isInv && x.needs_review === true && r.balCents > 0 ? "Needs review" : "";
  return <button className="mbd-row mbd-tap mbl-row" onClick={() => props.onOpen(r)}>
    <div className="mbd-row-main"><strong>{title}</strong>
      <small>{bits.filter(Boolean).join(" · ")}</small>
      {isInv && r.cat !== "void" && r.cat !== "draft" && <small className="mbl-link">{MBLLinkLine(x.link)}</small>}
      {flag && <small className="mbl-flag">{flag}</small>}</div>
    <div className="mbd-row-side"><b className="mbl-amt">{MBLCents(amount)}</b><MBLPill cat={r.cat} /></div>
  </button>;
}

// ---------------------------------------------------------------- send a fee text (confirm, then ghl/reply)
function MBLFeeText(props) {
  const [text, setText] = useStateMBL(props.initial || "");
  const [busy, setBusy] = useStateMBL(false);
  const [err, setErr] = useStateMBL("");
  const [sent, setSent] = useStateMBL(false);
  async function send() {
    const body = text.trim();
    if (!body || !props.contactId) return;
    if (!window.confirm("Text " + props.family + " this link? This sends a real text.")) return;
    setBusy(true); setErr("");
    try {
      await window.apiPostM("/api/daycare/ghl/reply", { contact_id: props.contactId, text: body });
      setSent(true); window.hapticM && window.hapticM("success"); props.onSent && props.onSent();
    } catch (e) { setErr("Not sent — " + ((e && e.message) || "retry")); }
    setBusy(false);
  }
  if (sent) return <div className="mbd-note">Texted {props.family}.</div>;
  return <div className="mbl-block">
    <textarea className="m-input mbd-input" rows={4} maxLength={640} value={text} disabled={busy} onChange={(e) => setText(e.target.value)} />
    {err && <div className="mw-warn">{err}</div>}
    <window.MBtn disabled={busy || !text.trim()} onClick={send}>{busy ? "Sending…" : "Send text"}</window.MBtn>
  </div>;
}

function MBLUrlBox(props) {
  const [copied, setCopied] = useStateMBL(false);
  return <div className="mbl-block">
    <input className="m-input" readOnly value={props.url} onFocus={(e) => e.target.select()} />
    <window.MBtn kind="ghost" onClick={async () => setCopied(await MBLCopy(props.url))}>{copied ? "Copied ✓" : "Copy link"}</window.MBtn>
  </div>;
}

// ---------------------------------------------------------------- fee-link sheet (also opened from a parent thread)
function MBLFamilyPick(props) {
  const conv = window.useApiM("/api/daycare/ghl/conversations");
  const rows = (conv.data && conv.data.ok && conv.data.conversations) || [];
  const q = props.value.trim().toLowerCase();
  const hits = props.picked || q.length < 2 ? [] : rows.filter((c) => (String(c.name || "") + " " + String(c.phone || "")).toLowerCase().includes(q)).slice(0, 5);
  return <React.Fragment>
    <input className="m-input" placeholder="Search a family or type a name" value={props.value} autoCapitalize="words"
      onChange={(e) => props.onType(e.target.value)} />
    {hits.map((c) => <button key={c.contactId} className="mbl-hit" onClick={() => props.onPick(String(c.name || "").trim(), c.contactId)}>
      <b>{c.name || c.phone || "Unknown"}</b><small>{c.phone || ""}</small></button>)}
    {props.picked && <small className="m-fade">Contact attached ✓ — the text can go from here.</small>}
    {!props.picked && q.length >= 2 && !hits.length && <small className="m-fade">{conv.error ? "Search unavailable" : "No match"} — you can still make the link and copy it.</small>}
  </React.Fragment>;
}

function MBLFeeSheet(props) {
  const centers = [[MBL_ATOB, "A Touch of Blessings · 921 N 18th"], [MBL_ATOB2, "A Touch of Blessings 2 · 2318 Cecil B. Moore"]]
    .concat(props.allowQa ? [[MBL_QA, "QA Sandbox · TEST"]] : []);
  const [family, setFamily] = useStateMBL(props.name || "");
  const [contact, setContact] = useStateMBL(props.contactId || "");
  const [purpose, setPurpose] = useStateMBL("registration-fee");
  const [amount, setAmount] = useStateMBL("");
  const [center, setCenter] = useStateMBL(centers.some(([id]) => id === props.locationId) ? props.locationId : MBL_ATOB);
  const [busy, setBusy] = useStateMBL(false);
  const [err, setErr] = useStateMBL("");
  const [made, setMade] = useStateMBL(null);
  const usd = parseFloat(amount);
  const fixed = !!props.contactId;                       // opened from a thread: the family is already known
  async function make() {
    if (family.trim().length < 2) return setErr("Enter the family name.");
    if (!(usd >= 1)) return setErr("Amount must be at least $1.");
    setBusy(true); setErr("");
    try {
      const body = { family: family.trim(), amount: usd, purpose, location_id: center };
      if (contact) body.contact_id = contact;
      const res = await window.apiPostM("/api/daycare/billing/fee-link", body);
      if (!res || res.ok === false || !res.url) throw new Error((res && (res.detail || res.error)) || "No link came back");
      setMade(res); props.onMade && props.onMade();
    } catch (e) { setErr((e && e.message) || "Couldn't make the link — retry."); }
    setBusy(false);
  }
  const body = made
    ? <React.Fragment>
      <div className="mbd-note">Link made. Nothing was sent and nobody was charged.{made.testMode ? " TEST MODE." : ""}</div>
      <MBLUrlBox url={made.url} />
      {contact ? <MBLFeeText contactId={contact} family={family.trim()} initial={made.draft || ""} />
        : <div className="m-fade">No contact attached - copy the link.</div>}
    </React.Fragment>
    : <div className="mbd-form">
      {fixed ? <div className="m-card"><b>{family}</b><div className="m-fade" style={{ marginTop: 4 }}>From this conversation · the text can go to them.</div></div>
        : <div className="mbd-field"><span>Family</span>
          <MBLFamilyPick value={family} picked={!!contact}
            onType={(v) => { setFamily(v); setContact(""); }} onPick={(n, id) => { setFamily(n); setContact(id); }} /></div>}
      <label className="mbd-field"><span>What for</span>
        <select className="m-input" value={purpose} onChange={(e) => setPurpose(e.target.value)}>
          {MBL_PURPOSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      <label className="mbd-field"><span>Amount (dollars)</span>
        <input className="m-input" type="number" inputMode="decimal" min="1" step="0.01" placeholder="49" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
      <label className="mbd-field"><span>Center</span>
        <select className="m-input" value={center} onChange={(e) => setCenter(e.target.value)}>
          {centers.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      {err && <div className="mw-warn">{err}</div>}
      <window.MBtn disabled={busy} onClick={make}>{busy ? "Making…" : "Make link"}</window.MBtn>
      <div className="m-fade">Making a link sends nothing and charges no one.</div>
    </div>;
  return <window.MBDSheet title="Fee link" onClose={props.onClose}>{body}</window.MBDSheet>;
}

// ---------------------------------------------------------------- fee row sheet
function MBLFeeRowSheet(props) {
  const f = props.row.raw, unpaid = f.status !== "paid";
  const [thread, setThread] = useStateMBL(false);
  const name = f.family || "this family";
  const initial = "Here is the link for the " + (f.amountCents ? MBLMoneyText(f.amountCents) + " " : "") + (f.label || "fee") + ": " + (f.url || "") + " Thank you!";
  return <window.MBDSheet title={f.label ? f.label.replace(/^./, (c) => c.toUpperCase()) : "Fee link"} onClose={props.onClose}>
    <div className="m-card mbl-facts">
      <div><small>Family</small><b>{name}</b></div>
      <div><small>Center</small><b>{props.row.center || "—"}</b></div>
      <div><small>Status</small><MBLPill cat={props.row.cat} /></div>
      <div><small>Amount</small><b>{MBLCents(f.amountCents)}</b></div>
      <div><small>Opened</small><b>{f.opens || 0} time{f.opens === 1 ? "" : "s"}</b></div>
      {f.paidAt && <div><small>Paid</small><b>{MBLTime(f.paidAt)}</b></div>}
      {!f.paidAt && f.lastActivity && <div><small>Last activity</small><b>{MBLTime(f.lastActivity)}</b></div>}
    </div>
    {f.contactId && window.MBDThread && <window.MBtn kind="ghost" onClick={() => setThread(true)}>Open the conversation</window.MBtn>}
    {thread && <window.MBDThread contactId={f.contactId} onClose={() => setThread(false)} />}
    {f.url ? <MBLUrlBox url={f.url} /> : unpaid && <div className="mw-warn">No link on file for this one.</div>}
    {unpaid && f.url && (f.contactId
      ? <React.Fragment><div className="mbd-sub">Text this link</div>
        <MBLFeeText contactId={f.contactId} family={name} initial={initial} onSent={props.onChanged} /></React.Fragment>
      : <div className="m-fade">No contact attached - copy the link.</div>)}
  </window.MBDSheet>;
}

// ---------------------------------------------------------------- invoice sheet
function MBLTimeline(props) {
  const d = props.data;
  if (!d) return <window.MSpin />;
  if (!d.ok) return <div className="mw-warn">Timeline unavailable — {String(d.detail)}. This is Unknown, not "nothing happened".</div>;
  const sends = (Array.isArray(d.sends) ? d.sends : []).filter(Boolean).slice().sort((a, b) => MBLMs(b.sent_at) - MBLMs(a.sent_at));
  const pays = Array.isArray(d.payments) ? d.payments.filter(Boolean) : [];
  const rems = Array.isArray(d.reminders) ? d.reminders.filter(Boolean) : [];
  return <div className="mbl-tl">
    {!sends.length && <div className="m-fade">No pay link has been texted for this invoice yet.</div>}
    {sends.map((s, i) => <div className="mbl-tl-row" key={s.id || i}>
      <span>Link {s.status || "sent"}</span><span>{MBLTime(s.sent_at) || "—"}</span><span>{Number(s.open_count) > 0 ? "opened ×" + s.open_count : "not opened"}</span></div>)}
    {pays.map((p, i) => <div className="mbl-tl-row" key={p.id || "p" + i}>
      <span>{p.method_label || "Payment"}</span><span>{typeof p.amount_cents === "number" ? MBLCents(p.amount_cents) : "—"}</span><span>{p.status || "Unknown"} · {MBLTime(p.paid_at) || "—"}</span></div>)}
    {rems.map((x, i) => <div className="mbl-tl-row" key={"r" + i}>
      <span>Reminder</span><span>{x.status || ""}</span><span>{MBLTime(x.sent_at) || "—"}</span></div>)}
  </div>;
}

function MBLInvoiceSheet(props) {
  const r = props.row, inv = r.raw;
  const [tl, setTl] = useStateMBL(null);
  const [draft, setDraft] = useStateMBL(null);
  const [text, setText] = useStateMBL("");
  const [busy, setBusy] = useStateMBL("");
  const [err, setErr] = useStateMBL("");
  const [note, setNote] = useStateMBL("");
  const [warn, setWarn] = useStateMBL(false);
  async function loadTl() { setTl(await MBLGet("/api/daycare/billing/timeline?invoice_id=" + encodeURIComponent(inv.id) + "&location_id=" + encodeURIComponent(r.centerId))); }
  useEffectMBL(() => { loadTl(); }, [inv.id]);
  const why = r.cat === "paid" ? "Paid — nothing to collect." : r.cat === "void" ? "Void — nothing to collect."
    : r.cat === "draft" ? "Draft — issue it before texting a pay link." : "";
  const tokens = text.split(MBL_TOKEN).length - 1;
  async function compose() {
    setBusy("compose"); setErr(""); setNote("");
    try {
      const res = await window.apiPostM("/api/daycare/billing/link/compose", { invoice_id: inv.id, location_id: r.centerId });
      if (!res || res.ok === false || !res.message) throw new Error((res && (res.detail || res.error)) || "No draft came back");
      setDraft(res); setText(res.message);
    } catch (e) { setErr((e && e.message) || "Couldn't write the draft — retry."); }
    setBusy("");
  }
  async function send() {
    const body = text.trim();
    if (!draft || !body) return;
    if (tokens !== 1) return setErr("Keep " + MBL_TOKEN + " in the text exactly once — the pay link goes there.");
    const who = (draft.facts && draft.facts.parent_first_name) || "this parent";
    const bal = (draft.facts && draft.facts.balance) || String(r.balCents / 100);
    if (!window.confirm("Text " + who + " the pay link for $" + bal + "? This sends a real text.")) return;
    setBusy("send"); setErr("");
    try {
      const res = await window.apiPostM("/api/daycare/billing/link/send", { invoice_id: inv.id, message: body, location_id: r.centerId });
      const bad = res && (res.status === "failed" || res.status === "undelivered");
      const w = res && typeof res.warning === "string" ? res.warning.trim() : "";
      setNote(bad ? "Link created but the text did not go out — check the timeline below." : "Pay link texted to " + who + "." + (w ? " " + w : ""));
      setWarn(!!bad || !!w);
      setDraft(null); setText("");
      window.hapticM && window.hapticM("success");
      loadTl(); props.onChanged();
    } catch (e) { setErr("Not sent — " + ((e && e.message) || "retry")); }
    setBusy("");
  }
  const kid = MBLChild(inv);
  return <window.MBDSheet title={inv.invoice_number || "Invoice"} onClose={props.onClose}>
    <div className="m-card mbl-facts">
      <div><small>Family</small><b>{inv.guardian_name || "—"}</b></div>
      {kid && <div><small>Child</small><b>{kid}</b></div>}
      <div><small>Center</small><b>{r.center || "—"}</b></div>
      <div><small>Status</small><MBLPill cat={r.cat} /></div>
      <div><small>Amount</small><b>{MBLCents(r.cents)}</b></div>
      <div><small>Balance</small><b>{MBLCents(r.balCents)}</b></div>
      {inv.due_on && <div><small>Due</small><b>{MBLDay(inv.due_on)}</b></div>}
      {inv.issued_on && <div><small>Issued</small><b>{MBLDay(inv.issued_on)}</b></div>}
      {inv.description && <div className="wide"><small>For</small><b>{inv.description}</b></div>}
      <div className="wide"><small>Pay link</small><b>{MBLLinkLine(inv.link)}</b></div>
    </div>
    {inv.needs_review === true && r.balCents > 0 && <div className="mw-warn">Needs review before collecting.</div>}
    {inv.reminder_failed === true && r.balCents > 0 && <div className="mw-warn">The last reminder failed to send.</div>}

    <div className="mbd-sub">Text pay link</div>
    {note && <div className={warn ? "mw-warn" : "mbd-note"}>{note}</div>}
    {why ? <div className="m-fade">{why}</div> : !draft
      ? <window.MBtn disabled={!!busy} onClick={compose}>{busy === "compose" ? "Writing…" : "Text pay link"}</window.MBtn>
      : <div className="mbl-block">
        {(draft.warnings || []).map((w, i) => <div className="mw-warn" key={i}>{w}</div>)}
        {draft.facts && draft.facts.livemode === false && <div className="mbd-note">TEST center — no real parent gets this.</div>}
        <textarea className="m-input mbd-input" rows={6} maxLength={640} value={text} disabled={busy === "send"} onChange={(e) => setText(e.target.value)} />
        <small className="m-fade">The pay link goes where <code>{MBL_TOKEN}</code> is. Keep it once. {text.length}/640</small>
        {err && <div className="mw-warn">{err}</div>}
        <div className="mbd-actions">
          <window.MBtn kind="ghost" disabled={busy === "send"} onClick={() => { setDraft(null); setErr(""); }}>Cancel</window.MBtn>
          <window.MBtn disabled={busy === "send" || !text.trim() || tokens !== 1} onClick={send}>{busy === "send" ? "Sending…" : "Send"}</window.MBtn>
        </div>
      </div>}
    {!draft && err && <div className="mw-warn">{err}</div>}

    <div className="mbd-sub">Timeline</div>
    <MBLTimeline data={tl} />
  </window.MBDSheet>;
}

// ---------------------------------------------------------------- the tab
function MBLBilling() {
  const locs = window.useApiM("/api/daycare/locations");
  const [scopeKey, setScopeKey] = useStateMBL("atob");     // always starts on A Touch of Blessings; never saved
  const [seg, setSeg] = useStateMBL("all");
  const [open, setOpen] = useStateMBL(null);
  const [fee, setFee] = useStateMBL(false);
  const locList = (locs.data && locs.data.ok && locs.data.locations) || [];
  const scopes = MBLScopes(locList);
  const scope = scopes.find((s) => s.key === scopeKey) || scopes[0];
  const names = { [MBL_ATOB]: "A Touch of Blessings", [MBL_ATOB2]: "A Touch of Blessings 2" };
  locList.forEach((l) => { names[l.id] = l.name; });
  if (scope.test) names[MBL_QA] = "QA TEST";
  const d = MBLLoad(scope.ids);
  const rows = MBLRows(d.src, names);
  const tot = MBLTotals(rows, d.src);
  const bad = [];
  d.src.forEach((s) => {
    if (!s.inv.ok) bad.push(["Invoices", names[s.id] || "this center", s.inv]);
    if (!s.fee.ok) bad.push(["Fee links", names[s.id] || "this center", s.fee]);
  });
  const auth = d.src.some((s) => MBLAuthed(s.inv) || MBLAuthed(s.fee));
  const isUnpaid = (r) => r.cat === "overdue" || r.cat === "due" || r.cat === "unpaidFee";
  const shown = rows.filter((r) => seg === "all" || (seg === "unpaid" ? isUnpaid(r) : r.cat === "paid"));
  const counts = { all: rows.length, unpaid: rows.filter(isUnpaid).length, paid: rows.filter((r) => r.cat === "paid").length };
  const dash = (t, f) => (t ? f(t) : "—");
  const refresh = () => { d.refresh(); };

  return <React.Fragment>
    <window.MBDHead title="Billing" sub={scope.title} />
    <div className="m-content mbd-page">
      {auth && window.MBDAuthLine && <window.MBDAuthLine />}
      <div className="m-seg mbl-chips">
        {scopes.map((s) => <button key={s.key} className={"m-chip" + (s.key === scope.key ? " active" : "") + (s.test ? " mbl-muted" : "")}
          onClick={() => setScopeKey(s.key)}>{s.label}</button>)}
      </div>
      {scope.test && <div className="mbd-note">TEST data only — nothing here is a real family.</div>}
      {!auth && bad.map(([what, where, x], i) => <div className="mw-warn" key={i}>{what} unavailable for {where} — {String(x.detail)}. Totals marked — are Unknown, not zero.</div>)}

      <div className="mbl-tiles">
        <MBLTile label="Unpaid" value={dash(tot.unpaid, (t) => MBLWhole(t.cents))}
          sub={dash(tot.unpaid, (t) => t.n + " open" + (t.unknown ? " · " + t.unknown + " no amount" : ""))} />
        <MBLTile label="Overdue" tone={tot.overdue && tot.overdue.n ? "bad" : ""} value={dash(tot.overdue, (t) => MBLWhole(t.cents))}
          sub={dash(tot.overdue, (t) => t.n + " invoice" + (t.n === 1 ? "" : "s"))} />
        <MBLTile label="Paid · 30d" tone="ok" value={dash(tot.paid, (t) => MBLWhole(t.cents))} sub={dash(tot.paid, (t) => t.n + " paid")} />
      </div>

      <window.MBtn onClick={() => setFee(true)}>+ Fee link</window.MBtn>

      <div className="m-seg mbl-seg">
        {[["all", "All"], ["unpaid", "Unpaid"], ["paid", "Paid"]].map(([k, l]) =>
          <window.MChip key={k} active={seg === k} onClick={() => setSeg(k)}>{l}{d.loading ? "" : " · " + counts[k]}</window.MChip>)}
        <button className="m-chip" onClick={refresh} aria-label="Refresh"><window.MIcons.Refresh size={16} /></button>
      </div>

      <div className="m-card mbd-list">
        {d.loading ? <window.MSpin />
          : !shown.length ? (bad.length
            ? <div className="m-fade" style={{ padding: "12px 2px" }}>Nothing to show because a read failed. That is not the same as nothing owed.</div>
            : <window.MEmpty title={seg === "paid" ? "No paid items yet" : seg === "unpaid" ? "Nothing unpaid" : "No invoices or fee links"} sub="Fee links and invoices for this scope show here." />)
          : shown.map((r) => <MBLRow key={r.key} row={r} onOpen={setOpen} />)}
      </div>
    </div>
    {open && open.kind === "inv" && <MBLInvoiceSheet row={open} onClose={() => setOpen(null)} onChanged={refresh} />}
    {open && open.kind === "fee" && <MBLFeeRowSheet row={open} onClose={() => setOpen(null)} onChanged={refresh} />}
    {fee && <MBLFeeSheet allowQa={scope.test} locationId={scope.ids.length === 1 ? scope.ids[0] : MBL_ATOB}
      onClose={() => setFee(false)} onMade={refresh} />}
  </React.Fragment>;
}

Object.assign(window, { MBLBilling, MBLFeeSheet });
