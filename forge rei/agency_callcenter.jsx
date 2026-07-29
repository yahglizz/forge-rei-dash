// agency_callcenter.jsx — Call Center (Forge AI Agency).
// Tap-to-log call tracker: two big buttons (Answered / No Answer), a stat
// strip with today's tally + streak, a goal editor, today's log, and a
// 7-day history strip. Internal tally only — no outward action, no
// approval gate (see agency_calls.py).
//
// STATIC-REACT RULES (no build step):
//   - hooks aliased (…Cc) so top-level consts never collide with other files
//   - every top-level name prefixed Cc / CC_
//   - never use computed-member JSX tags — resolve the component to a var first
//   - shipped on window at the bottom
const { useState: useStateCc } = React;

function CcStat({ label, value }) {
  return (
    <div className="card card-pad" style={{ flex: 1, minWidth: 110, textAlign: "center" }}>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
      <div className="faint" style={{ fontSize: 12, marginTop: 2 }}>{label}</div>
    </div>
  );
}

const CC_STATUS_LABEL = {
  new: "To call", answered: "Called", interested: "Interested",
  no_answer: "No answer", callback: "Call back", dead: "Said no",
  bad_number: "Dead line",
};
const CC_STATUS_STYLE = {
  interested: { color: "#ffd479", background: "rgba(255,212,121,.16)" },
  answered: { color: "#81c995", background: "rgba(129,201,149,.12)" },
  callback: { color: "#f6c979", background: "rgba(244,184,96,.12)" },
  no_answer: { color: "#8ab4f8", background: "rgba(138,180,248,.12)" },
  dead: { color: "#f28b82", background: "rgba(242,139,130,.12)" },
  bad_number: { color: "#9aa0a6", background: "rgba(154,160,166,.14)" },
  new: { opacity: 0.7, background: "rgba(255,255,255,.06)" },
};
const CC_FILTERS = [
  ["all", "All"], ["new", "To call"], ["interested", "⭐ Interested"],
  ["answered", "Called"], ["no_answer", "No answer"],
  ["callback", "Call back"], ["dead", "Said no"], ["bad_number", "Dead line"],
];

// The dial bar. Order = how often you press it. Uniform blocks so the hand
// learns the position and stops reading the labels.
const CC_DIAL_KEYS = [
  { status: "answered", label: "CALLED", tone: "ok" },
  { status: "no_answer", label: "NO ANS", tone: "" },
  { status: "bad_number", label: "DEAD", tone: "dim" },
  { status: "callback", label: "CB", tone: "" },
  { status: "dead", label: "NO", tone: "bad" },
];

// What they said they want. MUST match agency_io.SERVICES exactly — the client
// book drops anything not on that list.
const CC_SERVICES = ["Website", "Automations", "AI Receptionist", "AI Chatbot",
                     "Ads Management", "SEO", "CRM Setup", "Hosting"];

// Spreadsheet chrome. One <style> tag, scoped to .cc-sheet — buildless-safe.
const CC_SHEET_CSS = `
.cc-wrap{border:1px solid rgba(255,255,255,.16);border-radius:8px;overflow:auto;max-height:72vh}
.cc-sheet{border-collapse:separate;border-spacing:0;width:100%;font-size:12.5px}
.cc-sheet th{position:sticky;top:0;z-index:3;background:var(--card-2,#1b1f27);
  font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;
  color:rgba(255,255,255,.55);text-align:left;padding:7px 10px;white-space:nowrap;
  border-bottom:1px solid rgba(255,255,255,.2);border-right:1px solid rgba(255,255,255,.09)}
.cc-sheet td{padding:5px 10px;border-bottom:1px solid rgba(255,255,255,.07);
  border-right:1px solid rgba(255,255,255,.07);vertical-align:middle}
.cc-sheet{min-width:1130px}
.cc-sheet td:nth-child(2){min-width:165px}
.cc-sheet td:nth-child(3),.cc-sheet td:nth-child(5){white-space:nowrap}
.cc-sheet td:nth-child(4){max-width:180px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cc-sheet td:nth-child(6){min-width:230px}
.cc-sheet td:nth-child(7){min-width:140px}
.cc-sheet tbody tr:nth-child(even){background:rgba(255,255,255,.025)}
.cc-sheet tbody tr:hover{background:rgba(93,124,255,.11)}
.cc-sheet tbody tr.cc-hot{background:rgba(255,212,121,.07)}
.cc-sheet tbody tr.cc-hot:hover{background:rgba(255,212,121,.14)}
.cc-sheet .cc-rn{width:34px;text-align:center;color:rgba(255,255,255,.35);
  font-size:11px;background:var(--card-2,#1b1f27);position:sticky;left:0;z-index:2}
.cc-sheet th.cc-rn{z-index:4}
.cc-sheet .cc-cell{width:100%;background:transparent;border:none;color:inherit;
  font:inherit;padding:2px 0;outline:none}
.cc-sheet .cc-cell:focus{background:rgba(255,255,255,.07);border-radius:3px;padding:2px 4px}
.cc-btn{border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.05);
  border-radius:5px;padding:2px 7px;font-size:11.5px;line-height:1.6;color:inherit}
.cc-btn:hover:not(:disabled){background:rgba(255,255,255,.13)}
.cc-btn.cc-yes{border-color:rgba(255,212,121,.5);background:rgba(255,212,121,.14);color:#ffd479;font-weight:600}
.cc-btn.cc-yes:hover:not(:disabled){background:rgba(255,212,121,.26)}
/* dial bar — uniform blocks, muscle-memory positions, one tap per outcome */
.cc-dial{display:flex;gap:3px;white-space:nowrap}
.cc-dial button{min-width:52px;padding:7px 8px;border-radius:6px;font-size:10.5px;
  font-weight:700;letter-spacing:.06em;line-height:1;color:inherit;
  border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.06)}
.cc-dial button:hover:not(:disabled){background:rgba(255,255,255,.17)}
.cc-dial button:active:not(:disabled){transform:translateY(1px)}
.cc-dial button:disabled{opacity:.45}
.cc-dial .d-win{min-width:74px;border-color:rgba(255,212,121,.55);
  background:rgba(255,212,121,.16);color:#ffd479}
.cc-dial .d-win:hover:not(:disabled){background:rgba(255,212,121,.3)}
.cc-dial .d-ok{border-color:rgba(129,201,149,.42);background:rgba(129,201,149,.13);color:#a5dbb5}
.cc-dial .d-ok:hover:not(:disabled){background:rgba(129,201,149,.26)}
.cc-dial .d-bad{border-color:rgba(242,139,130,.4);background:rgba(242,139,130,.12);color:#f0a9a3}
.cc-dial .d-bad:hover:not(:disabled){background:rgba(242,139,130,.24)}
.cc-dial .d-dim{color:rgba(255,255,255,.45)}
.cc-dial .d-x{min-width:26px;padding:7px 4px;color:rgba(255,255,255,.35);
  border-color:transparent;background:transparent}
.cc-dial .d-x:hover:not(:disabled){background:rgba(255,255,255,.1)}
.cc-pain{color:#ffcf8a}
.cc-pain::placeholder{color:rgba(255,255,255,.25);font-style:italic}
.cc-tab{border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.04);
  border-radius:7px 7px 0 0;border-bottom:none;padding:6px 13px;font-size:12px;color:inherit}
.cc-tab.on{background:rgba(93,124,255,.2);border-color:rgba(93,124,255,.5);font-weight:600}
.cc-modal-back{position:fixed;inset:0;background:rgba(0,0,0,.62);z-index:900;
  display:flex;align-items:flex-start;justify-content:center;padding:6vh 16px;overflow:auto}
.cc-modal{width:100%;max-width:560px;background:var(--card,#161a22);
  border:1px solid rgba(255,255,255,.16);border-radius:12px;padding:20px}
.cc-modal label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  color:rgba(255,255,255,.55);margin-bottom:4px}
.cc-modal input,.cc-modal textarea{width:100%;background:rgba(255,255,255,.05);
  border:1px solid rgba(255,255,255,.13);border-radius:6px;color:inherit;
  padding:7px 9px;font-size:13px;font-family:inherit}
/* offer sheet — what you read off while they're on the line */
.cc-offers{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.cc-offer{text-align:left;border:1px solid rgba(255,255,255,.14);border-radius:9px;
  padding:11px 12px;background:rgba(255,255,255,.04);color:inherit;font:inherit;cursor:pointer}
.cc-offer:hover{background:rgba(255,255,255,.09);border-color:rgba(255,255,255,.28)}
.cc-offer.on{border-color:#ffd479;background:rgba(255,212,121,.14);box-shadow:0 0 0 1px rgba(255,212,121,.35) inset}
.cc-offer .o-name{font-weight:700;font-size:13px}
.cc-offer .o-price{font-size:21px;font-weight:700;color:#ffd479;margin:3px 0 5px}
.cc-offer ul{margin:0;padding-left:15px;font-size:11px;line-height:1.55;color:rgba(255,255,255,.62)}
.cc-offer.o-custom{border-style:dashed}
.cc-offer.o-custom .o-price{font-size:15px;color:rgba(255,255,255,.75)}
`;

function CcStatusPill({ status }) {
  return (
    <span style={Object.assign({ borderRadius: 99, padding: "3px 9px", fontSize: 11, fontWeight: 600 }, CC_STATUS_STYLE[status] || CC_STATUS_STYLE.new)}>
      {CC_STATUS_LABEL[status] || status}
    </span>
  );
}

function CcRow({ n, lead, busy, onMark, onNote, onDelete, onInterested }) {
  const cur = busy ? "default" : "pointer";
  const head = lead.name || lead.company || "(no name)";
  const sub = [lead.company && lead.company !== head ? lead.company : "", lead.location]
    .filter(Boolean).join(" · ");
  return (
    <tr className={lead.status === "interested" ? "cc-hot" : ""}>
      <td className="cc-rn">{n}</td>
      <td>
        <div style={{ fontWeight: 600 }}>{head}</div>
        {sub && <div className="faint" style={{ fontSize: 11 }}>{sub}</div>}
      </td>
      <td>
        {lead.phone ? (
          <a href={"tel:" + lead.phone} className="mono" style={{ color: "inherit", textDecoration: "underline dotted" }}>
            {lead.phone}
          </a>
        ) : <span className="faint">—</span>}
        {lead.last_called && <div className="faint mono" style={{ fontSize: 10 }}>{lead.last_called}</div>}
      </td>
      <td className="faint" style={{ fontSize: 11.5 }}>{lead.email || "—"}</td>
      <td><CcStatusPill status={lead.status} /></td>
      <td>
        <input className="cc-cell cc-pain" defaultValue={lead.pain}
          placeholder="what's broken for them?"
          title="The one specific thing you open the call with"
          onBlur={(e) => e.target.value !== (lead.pain || "") && onNote(lead.id, e.target.value, "pain")} />
      </td>
      <td>
        <input className="cc-cell" defaultValue={lead.note} placeholder="note…"
          onBlur={(e) => e.target.value !== (lead.note || "") && onNote(lead.id, e.target.value)} />
      </td>
      <td>
        <div className="cc-dial">
          <button className="d-win" title="Interested — capture their info, push to Pipeline"
            disabled={busy} onClick={() => onInterested(lead)} style={{ cursor: cur }}>★ YES</button>
          {CC_DIAL_KEYS.map((k) => (
            <button key={k.status} className={k.tone ? "d-" + k.tone : ""}
              title={CC_STATUS_LABEL[k.status]} disabled={busy}
              onClick={() => onMark(lead.id, k.status)} style={{ cursor: cur }}>{k.label}</button>
          ))}
          <button className="d-x" title="Remove from sheet" disabled={busy}
            onClick={() => onDelete(lead.id)} style={{ cursor: cur }}>×</button>
        </div>
        {lead.client_id && (
          <div style={{ fontSize: 10.5, color: "#ffd479", marginTop: 3 }}>
            → in Pipeline {lead.escalated ? "(" + lead.escalated + ")" : ""}
            {lead.offer ? " · " + lead.offer : ""}
          </div>
        )}
      </td>
    </tr>
  );
}

// Interested → capture what they told you, push a Pipeline lead into the client book.
// Internal + reversible: it creates a client row with status "lead". Nothing is sent.
function CcEscalate({ lead, busy, onCancel, onSave }) {
  // Prices come from the server (agency_offers.py), which is kept in sync with
  // the public ClientForge site. Never hardcode a price here — quoting a number
  // the prospect can't find on the site is how a deal dies at the follow-up.
  const cat = window.useApi("/api/agency/offers", { interval: 0 });
  const offers = (cat.data && cat.data.offers) || [];
  const [pick, setPick] = useStateCc(null);      // offer id, "custom", or null
  const [cd, setCd] = useStateCc({ name: "", price: "", monthly: false, includes: "" });
  const [f, setF] = useStateCc({
    name: lead.name || lead.company || "",
    business: lead.company || lead.name || "",
    phone: lead.phone || "",
    email: lead.email || "",
    site: lead.website || "",
    mrr: "",
    next_step: "",
    notes: "",
    services: [],
  });
  const set = (k, v) => setF((p) => Object.assign({}, p, { [k]: v }));
  const toggle = (s) => setF((p) => Object.assign({}, p, {
    services: p.services.indexOf(s) < 0 ? p.services.concat([s]) : p.services.filter((x) => x !== s),
  }));
  const row = { display: "flex", gap: 10, marginBottom: 10 };
  const setCust = (k, v) => setCd((p) => Object.assign({}, p, { [k]: v }));

  function chosenOffer() {
    if (pick === "custom") {
      if (!cd.name.trim() && !cd.price) return null;
      return { custom: true, name: cd.name || "Custom deal", price: cd.price || 0,
               monthly: cd.monthly, includes: cd.includes };
    }
    return pick ? { id: pick } : null;
  }

  return (
    <div className="cc-modal-back" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="cc-modal">
        <div style={{ fontSize: 17, fontWeight: 700 }}>⭐ Interested — {lead.company || lead.name}</div>
        <div className="faint" style={{ fontSize: 12, margin: "4px 0 12px" }}>
          Goes to the Pipeline as a lead. Nothing gets sent to them.
        </div>
        {lead.pain && (
          <div style={{ fontSize: 12, marginBottom: 14, padding: "7px 10px", borderRadius: 6,
            background: "rgba(255,212,121,.1)", border: "1px solid rgba(255,212,121,.28)", color: "#ffcf8a" }}>
            <b>Their pain:</b> {lead.pain}
          </div>
        )}

        <div style={{ marginBottom: 14 }}>
          <label>What you're offering them</label>
          {cat.error && <div className="faint" style={{ fontSize: 12 }}>Couldn't load the offer sheet — you can still save without one.</div>}
          <div className="cc-offers">
            {offers.map((o) => (
              <button key={o.id} type="button"
                className={"cc-offer" + (pick === o.id ? " on" : "")}
                onClick={() => setPick(pick === o.id ? null : o.id)}>
                <div className="o-name">{o.name}</div>
                <div className="o-price">{o.from ? "From " : ""}{o.display}</div>
                <ul>{o.includes.slice(0, 3).map((x, i) => <li key={i}>{x}</li>)}</ul>
              </button>
            ))}
            <button type="button"
              className={"cc-offer o-custom" + (pick === "custom" ? " on" : "")}
              onClick={() => setPick(pick === "custom" ? null : "custom")}>
              <div className="o-name">✎ Custom deal</div>
              <div className="o-price">Name your own</div>
              <ul><li>Whatever closes them</li><li>Marked off-sheet</li></ul>
            </button>
          </div>
        </div>

        {pick === "custom" && (
          <div style={{ marginBottom: 14, padding: 12, borderRadius: 9,
            border: "1px dashed rgba(255,212,121,.45)", background: "rgba(255,212,121,.06)" }}>
            <div style={row}>
              <div style={{ flex: 2 }}>
                <label>Deal name</label>
                <input value={cd.name} onChange={(e) => setCust("name", e.target.value)}
                  placeholder="Starter site + 2 months support" />
              </div>
              <div style={{ flex: 1 }}>
                <label>Price</label>
                <input type="number" min="0" value={cd.price}
                  onChange={(e) => setCust("price", e.target.value)} placeholder="200" />
              </div>
            </div>
            <div style={{ marginBottom: 8 }}>
              <label>What they get</label>
              <input value={cd.includes} onChange={(e) => setCust("includes", e.target.value)}
                placeholder="5-page site, booking form, 2 months of edits" />
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 7, textTransform: "none",
              fontSize: 12.5, letterSpacing: 0, color: "inherit", marginBottom: 0 }}>
              <input type="checkbox" checked={cd.monthly} style={{ width: "auto" }}
                onChange={(e) => setCust("monthly", e.target.checked)} />
              Recurring — bill this every month
            </label>
            <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
              Only a recurring deal counts toward MRR. One-time builds don't.
            </div>
          </div>
        )}

        <div style={row}>
          <div style={{ flex: 1 }}>
            <label>Who you talked to *</label>
            <input value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Owner / manager name" />
          </div>
          <div style={{ flex: 1 }}>
            <label>Business</label>
            <input value={f.business} onChange={(e) => set("business", e.target.value)} />
          </div>
        </div>

        <div style={row}>
          <div style={{ flex: 1 }}>
            <label>Phone</label>
            <input value={f.phone} onChange={(e) => set("phone", e.target.value)} />
          </div>
          <div style={{ flex: 1 }}>
            <label>Email</label>
            <input value={f.email} onChange={(e) => set("email", e.target.value)} placeholder="for the invite" />
          </div>
        </div>

        <div style={row}>
          <div style={{ flex: 2 }}>
            <label>Their current site</label>
            <input value={f.site} onChange={(e) => set("site", e.target.value)} placeholder="none / url" />
          </div>
          <div style={{ flex: 1 }}>
            <label>Est. $/mo</label>
            <input type="number" min="0" value={f.mrr} onChange={(e) => set("mrr", e.target.value)}
              placeholder="0" title="Only if you agreed something recurring outside the offer above" />
          </div>
        </div>

        <div style={{ marginBottom: 10 }}>
          <label>What they want</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {CC_SERVICES.map((s) => (
              <button key={s} type="button" className={"cc-btn" + (f.services.indexOf(s) >= 0 ? " cc-yes" : "")}
                onClick={() => toggle(s)} style={{ cursor: "pointer" }}>{s}</button>
            ))}
          </div>
        </div>

        <div style={{ marginBottom: 10 }}>
          <label>Next step</label>
          <input value={f.next_step} onChange={(e) => set("next_step", e.target.value)}
            placeholder="Zoom Thu 10am — showing the mockup" />
        </div>

        <div style={{ marginBottom: 16 }}>
          <label>What they said</label>
          <textarea value={f.notes} onChange={(e) => set("notes", e.target.value)} rows={3}
            placeholder="No way to book a tour on the site. Been meaning to fix it for a year." />
        </div>

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="cc-btn faint" disabled={busy} onClick={onCancel} style={{ cursor: "pointer", padding: "7px 14px" }}>Cancel</button>
          <button className="cc-btn cc-yes" disabled={busy || !f.name.trim()}
            onClick={() => onSave(Object.assign({}, f, { offer: chosenOffer() }))}
            style={{ cursor: busy || !f.name.trim() ? "default" : "pointer", padding: "7px 14px" }}>
            {busy ? "Saving…" : "Save → Pipeline"}
          </button>
        </div>
      </div>
    </div>
  );
}

function CcCallSheet({ refreshTally }) {
  const sheet = window.useApi("/api/agency/callsheet", { interval: 60000 });
  const leads = (sheet.data && sheet.data.leads) || [];
  const counts = (sheet.data && sheet.data.counts) || {};

  const [q, setQ] = useStateCc("");
  const [filter, setFilter] = useStateCc("all");
  const [paste, setPaste] = useStateCc(null); // null=closed, string=textarea value
  const [sheetBusy, setSheetBusy] = useStateCc(false);
  const [escLead, setEscLead] = useStateCc(null); // lead being escalated, or null

  async function uploadPdf(file) {
    if (!file) return;
    setSheetBusy(true);
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const res = await window.apiPost("/api/agency/callsheet/import-pdf", { file: dataUrl });
      if (res && res.ok === false) window.alert(res.detail || "Import failed.");
      sheet.refresh();
    } catch (e) {
      window.alert("Upload failed: " + (e.message || e));
    }
    setSheetBusy(false);
  }

  async function importPaste() {
    setSheetBusy(true);
    try {
      const res = await window.apiPost("/api/agency/callsheet/import-text", { text: paste });
      if (res && res.ok === false) window.alert(res.detail || "Import failed.");
      else setPaste(null);
      sheet.refresh();
    } catch (e) {
      window.alert("Import failed: " + (e.message || e));
    }
    setSheetBusy(false);
  }

  async function mark(id, status) {
    setSheetBusy(true);
    try {
      await window.apiPost("/api/agency/callsheet/status", { id, status });
      sheet.refresh();
      if (status === "answered" || status === "no_answer") refreshTally();
    } catch (e) {
      window.alert("Mark failed: " + (e.message || e));
    }
    setSheetBusy(false);
  }

  async function escalate(info) {
    if (!escLead) return;
    setSheetBusy(true);
    try {
      const res = await window.apiPost("/api/agency/callsheet/escalate", { id: escLead.id, info });
      if (res && res.ok === false) window.alert(res.detail || "Couldn't save that lead.");
      else {
        setEscLead(null);
        refreshTally();
      }
      sheet.refresh();
    } catch (e) {
      window.alert("Save failed: " + (e.message || e));
    }
    setSheetBusy(false);
  }

  async function saveNote(id, note, field) {
    setSheetBusy(true);
    try {
      await window.apiPost("/api/agency/callsheet/note", { id, note, field: field || "note" });
      sheet.refresh();
    } catch (e) {
      window.alert("Note save failed: " + (e.message || e));
    }
    setSheetBusy(false);
  }

  async function removeLead(id) {
    setSheetBusy(true);
    try {
      await window.apiPost("/api/agency/callsheet/delete", { id });
      sheet.refresh();
    } catch (e) {
      window.alert("Remove failed: " + (e.message || e));
    }
    setSheetBusy(false);
  }

  async function clearDead() {
    if (!window.confirm("Remove every 'said no' business from the sheet?")) return;
    setSheetBusy(true);
    try {
      await window.apiPost("/api/agency/callsheet/clear-dead", {});
      sheet.refresh();
    } catch (e) {
      window.alert("Clear failed: " + (e.message || e));
    }
    setSheetBusy(false);
  }

  const ql = q.trim().toLowerCase();
  const filtered = leads.filter((l) => {
    if (filter !== "all" && l.status !== filter) return false;
    if (!ql) return true;
    return [l.name, l.company, l.phone, l.email].some((v) => (v || "").toLowerCase().includes(ql));
  });

  return (
    <div className="card card-pad">
      <style>{CC_SHEET_CSS}</style>
      {escLead && (
        <CcEscalate lead={escLead} busy={sheetBusy} onCancel={() => setEscLead(null)} onSave={escalate} />
      )}
      <input id="cc-pdf-input" type="file" accept="application/pdf" style={{ display: "none" }}
        onChange={(e) => uploadPdf(e.target.files[0])} />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <div>
          <span style={{ fontWeight: 700 }}>Call Sheet</span>{" "}
          <span className="faint" style={{ fontSize: 12 }}>{counts.total || 0} businesses</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button disabled={sheetBusy} onClick={() => document.getElementById("cc-pdf-input").click()} style={{ fontSize: 12.5, cursor: sheetBusy ? "default" : "pointer" }}>
            {sheetBusy ? "Parsing…" : "📄 Upload PDF"}
          </button>
          <button disabled={sheetBusy} onClick={() => setPaste(paste === null ? "" : null)} style={{ fontSize: 12.5, cursor: sheetBusy ? "default" : "pointer" }}>
            ✏️ Paste leads
          </button>
          {counts.dead > 0 && (
            <button className="faint" disabled={sheetBusy} onClick={clearDead} style={{ fontSize: 12.5, background: "none", cursor: sheetBusy ? "default" : "pointer" }}>
              🧹 Clear said-no
            </button>
          )}
        </div>
      </div>

      {paste !== null && (
        <div style={{ marginBottom: 12 }}>
          <textarea
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            placeholder="Paste business leads here — name, phone, email, one per line…"
            style={{ width: "100%", minHeight: 120, background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.1)", borderRadius: 8, color: "inherit", padding: 10, fontSize: 13 }}
          />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button disabled={sheetBusy} onClick={importPaste} style={{ fontSize: 12.5, cursor: sheetBusy ? "default" : "pointer" }}>Add to sheet</button>
            <button className="faint" disabled={sheetBusy} onClick={() => setPaste(null)} style={{ fontSize: 12.5, background: "none", cursor: sheetBusy ? "default" : "pointer" }}>Cancel</button>
          </div>
        </div>
      )}

      {leads.length === 0 ? (
        <div className="card empty">
          <div className="empty-ico">📄</div>
          <div style={{ fontSize: 13 }}>Upload a PDF of business leads — every business becomes a row you can mark as you dial.</div>
        </div>
      ) : (
        <React.Fragment>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search business, phone…"
            style={{ fontSize: 12.5, width: "100%", marginBottom: 10 }}
          />

          <div style={{ display: "flex", gap: 3, flexWrap: "wrap", alignItems: "flex-end" }}>
            {CC_FILTERS.map(([key, label]) => (
              <button
                key={key}
                className={"cc-tab" + (filter === key ? " on" : "")}
                onClick={() => setFilter(key)}
                style={{ cursor: "pointer" }}
              >
                {label} <span className="faint">{key === "all" ? counts.total || 0 : counts[key] || 0}</span>
              </button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <div className="faint" style={{ fontSize: 12.5, padding: "14px 2px" }}>No businesses match.</div>
          ) : (
            <div className="cc-wrap">
              <table className="cc-sheet">
                <thead>
                  <tr>
                    <th className="cc-rn"></th>
                    <th>Business</th>
                    <th>Phone</th>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Pain point</th>
                    <th>Note</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((lead, i) => (
                    <CcRow key={lead.id} n={i + 1} lead={lead} busy={sheetBusy}
                      onMark={mark} onNote={saveNote} onDelete={removeLead}
                      onInterested={setEscLead} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </React.Fragment>
      )}
    </div>
  );
}

function AgencyCallCenter() {
  const { data, loading, error, refresh } = window.useApi("/api/agency/calls", { interval: 30000 });
  const [busy, setBusy] = useStateCc(false);
  const [goalInput, setGoalInput] = useStateCc("");

  const today = (data && data.today) || { answered: 0, no_answer: 0, dials: 0, rate: 0, log: [] };
  const week = (data && data.week) || [];
  const goal = (data && data.goal) || 0;
  const streak = (data && data.streak) || 0;
  const goalMet = goal > 0 && today.dials >= goal;

  async function log(outcome) {
    setBusy(true);
    try {
      await window.apiPost("/api/agency/calls/log", { outcome });
      refresh();
    } catch (e) {
      window.alert("Log failed: " + (e.message || e));
    }
    setBusy(false);
  }

  async function undo() {
    setBusy(true);
    try {
      await window.apiPost("/api/agency/calls/undo", {});
      refresh();
    } catch (e) {
      window.alert("Undo failed: " + (e.message || e));
    }
    setBusy(false);
  }

  async function saveGoal() {
    const n = parseInt(goalInput, 10);
    if (isNaN(n) || n < 0) return;
    setBusy(true);
    try {
      await window.apiPost("/api/agency/calls/goal", { goal: n });
      setGoalInput("");
      refresh();
    } catch (e) {
      window.alert("Goal save failed: " + (e.message || e));
    }
    setBusy(false);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* header */}
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Call Center</h1>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>
          Tap after every dial — logged + tallied for the day.
        </div>
      </div>

      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {loading && !data && <window.LoadingRow label="Loading call center…" />}

      {/* stat strip */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <CcStat label="Dials today" value={today.dials} />
        <CcStat label="Answered" value={today.answered} />
        <CcStat label="No answer" value={today.no_answer} />
        <CcStat label="Answer %" value={today.rate + "%"} />
        <CcStat label="🔥 Streak (days)" value={streak} />
      </div>
      <div className="faint" style={{ fontSize: 12.5 }}>
        {goalMet ? "Goal hit ✅" : today.dials + " / " + goal + " dials"}
      </div>

      {/* big tap buttons */}
      <div style={{ display: "flex", gap: 12 }}>
        <button
          className="card card-pad"
          disabled={busy}
          onClick={() => log("answered")}
          style={{ flex: 1, minHeight: 90, fontSize: 18, fontWeight: 700, cursor: busy ? "default" : "pointer" }}
        >
          ✅ Answered
        </button>
        <button
          className="card card-pad"
          disabled={busy}
          onClick={() => log("no_answer")}
          style={{ flex: 1, minHeight: 90, fontSize: 18, fontWeight: 700, cursor: busy ? "default" : "pointer" }}
        >
          📵 No Answer
        </button>
      </div>
      <div>
        <button
          className="faint mono"
          disabled={busy || today.log.length === 0}
          onClick={undo}
          style={{ background: "none", border: "none", fontSize: 12, cursor: busy || today.log.length === 0 ? "default" : "pointer" }}
        >
          Undo last
        </button>
      </div>

      {/* goal editor */}
      <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div className="faint" style={{ fontSize: 12.5 }}>Daily goal: {goal} dials</div>
        <input
          type="number"
          min="0"
          value={goalInput}
          onChange={(e) => setGoalInput(e.target.value)}
          placeholder={String(goal)}
          style={{ width: 70, fontSize: 12.5 }}
        />
        <button className="faint" disabled={busy} onClick={saveGoal} style={{ fontSize: 12.5, cursor: busy ? "default" : "pointer" }}>
          Save
        </button>
      </div>

      {/* call sheet */}
      <CcCallSheet refreshTally={refresh} />

      {/* today's log */}
      <div className="card card-pad">
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Today's log</div>
        {today.log.length === 0 ? (
          <div className="card empty">
            <div className="empty-ico">📞</div>
            <div style={{ fontSize: 13 }}>No calls logged yet today — start dialing.</div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {today.log.map((entry, i) => (
              <div key={i} style={{ display: "flex", gap: 8, fontSize: 13 }}>
                <span className="mono faint">{entry.ts}</span>
                <span>·</span>
                <span>{entry.outcome === "answered" ? "Answered" : "No answer"}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 7-day history */}
      <div className="card card-pad">
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Last 7 days</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {week.map((w) => (
            <div key={w.date} style={{ display: "flex", gap: 12, fontSize: 13 }}>
              <span style={{ minWidth: 90 }}>{w.date}</span>
              <span>{w.dials} dials</span>
              <span className="faint">{w.answered} answered</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { AgencyCallCenter });
