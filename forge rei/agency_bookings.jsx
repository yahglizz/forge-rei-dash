// agency_bookings.jsx — Bookings tab (Forge AI Agency, Business lens).
// ClientForge "Book a call": the public booking link, per-prospect ref links (an
// unguessable token per Call Sheet lead), upcoming calls, phone-match confirm, cancel.
// Static-React: hooks aliased (…Bk), top-level names prefixed Bk, shipped on window.
const { useState: useStateBk, useEffect: useEffectBk } = React;

const BK_NEED = { website: "Website", ads: "Ads", booking: "Booking / CRM", other: "Other" };

async function bkCopy(text, done) {
  try { await navigator.clipboard.writeText(text); done(); }
  catch (e) { window.prompt("Copy this link:", text); }
}

function BkLinkRow({ label, url }) {
  const [copied, setCopied] = useStateBk(false);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 11px",
      background: "var(--card-2)", borderRadius: 10 }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>{label}</div>
        <div className="faint mono" style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap" }}>{url}</div>
      </div>
      <button className="btn" aria-label={"Copy " + label}
        onClick={() => bkCopy(url, () => { setCopied(true); setTimeout(() => setCopied(false), 1500); })}>
        {copied ? "Copied" : "Copy"}
      </button>
      <a className="btn" href={url} target="_blank" rel="noopener noreferrer">Open</a>
    </div>
  );
}

function BkRefBuilder({ base }) {
  const [leads, setLeads] = useStateBk(null);
  const [pick, setPick] = useStateBk("");
  const [made, setMade] = useStateBk(null);
  const [err, setErr] = useStateBk("");

  useEffectBk(() => {
    let alive = true;
    window.apiGet("/api/agency/callsheet").then((d) => {
      if (!alive) return;
      const open = (d.leads || []).filter((l) => !["dnc", "won", "lost", "dead", "bad_number"].includes(l.status));
      setLeads(open);
    }).catch((e) => alive && setErr(e.message || "Could not load the Call Sheet"));
    return () => { alive = false; };
  }, []);

  async function make() {
    if (!pick) return;
    setErr(""); setMade(null);
    try { setMade(await window.apiPost("/api/agency/bookings/link", { leadId: pick })); }
    catch (e) { setErr(e.message || "Could not make the link"); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontWeight: 600, fontSize: 13.5 }}>Per-prospect link</div>
      <div className="faint" style={{ fontSize: 12 }}>
        Pick a Call Sheet lead. When they book through their link, the row moves to Demo booked by itself.
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <select className="input" style={{ flex: "1 1 240px", minWidth: 0, padding: "0 10px" }} value={pick}
          aria-label="Call Sheet lead" onChange={(e) => { setPick(e.target.value); setMade(null); }}>
          <option value="">{leads ? (leads.length ? "Choose a lead…" : "No open Call Sheet leads") : "Loading leads…"}</option>
          {(leads || []).map((l) => (
            <option key={l.id} value={l.id}>{(l.company || l.name || l.id) + (l.phone ? " · " + l.phone : "") + " · " + l.status}</option>
          ))}
        </select>
        <button className="btn btn-primary" disabled={!pick} onClick={make}>Make link</button>
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 12.5 }}>{err}</div>}
      {made && made.url && <BkLinkRow label={"Link for " + made.lead} url={made.url} />}
      {!base && <div className="faint" style={{ fontSize: 11.5 }}>Booking link base unknown.</div>}
    </div>
  );
}

function BkRow({ b, busy, onCancel, onConfirm }) {
  const need = (b.need || []).map((n) => BK_NEED[n] || n).join(" · ");
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{b.name} · {b.business}</div>
          <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 2 }}>{b.when}</div>
        </div>
        <button className="btn" disabled={busy} onClick={() => onCancel(b)}
          aria-label={"Cancel call with " + b.name}>Cancel</button>
      </div>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12.5 }}>
        <a href={"mailto:" + b.email} style={{ color: "var(--text)" }}>{b.email}</a>
        {b.phone && <a href={"tel:" + b.phone.replace(/[^\d+]/g, "")} style={{ color: "var(--text)" }}>{b.phone}</a>}
        {b.website && <span className="faint">{b.website}</span>}
      </div>
      {need && <div style={{ fontSize: 12.5 }}><span className="faint">Wants help with:</span> {need}</div>}
      {b.notes && <div style={{ fontSize: 12.5, whiteSpace: "pre-wrap" }}><span className="faint">Notes:</span> {b.notes}</div>}
      <div className="faint" style={{ fontSize: 11.5, display: "flex", gap: 12, flexWrap: "wrap" }}>
        <span>Source: {b.leadId ? "Call Sheet " + b.leadId + (b.leadMatch === "ref" ? " (their link)" : " (confirmed match)") : "booking page"}</span>
        {b.tz && <span>Their time zone: {b.tz}</span>}
        {b.eventId && <span>On Google Calendar</span>}
      </div>
      {b.suggestedLead && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", borderRadius: 9,
          background: "var(--card-2)", fontSize: 12.5, flexWrap: "wrap" }}>
          <span style={{ flex: 1 }}>Possible match: <b>{b.suggestedName}</b> (same phone on the Call Sheet)</span>
          <button className="btn" disabled={busy} onClick={() => onConfirm(b)}>Mark demo booked</button>
        </div>
      )}
      {b.googleError && <div style={{ color: "var(--amber, #F59E0B)", fontSize: 12 }}>Google Calendar: {b.googleError}</div>}
    </div>
  );
}

function AgencyBookings() {
  const { data, loading, error, refresh } = window.useApi("/api/agency/bookings", { interval: 60000 });
  const [busy, setBusy] = useStateBk(false);
  const rows = (data && data.bookings) || [];
  const ev = (data && data.event) || {};

  async function act(path, body, fail) {
    setBusy(true);
    try { await window.apiPost(path, body); refresh(); }
    catch (e) { window.alert(fail + ": " + (e.message || e)); }
    setBusy(false);
  }
  function cancel(b) {
    if (!window.confirm("Cancel the call with " + b.name + " (" + b.when + ")? This frees the slot"
      + (b.eventId ? " and deletes the Google Calendar event" : "") + ". Nothing is sent to them.")) return;
    act("/api/agency/bookings/cancel", { id: b.id }, "Cancel failed");
  }
  function confirmLead(b) {
    if (!window.confirm("Link this booking to " + b.suggestedName + " and mark that Call Sheet row Demo booked?")) return;
    act("/api/agency/bookings/confirm-lead", { id: b.id }, "Update failed");
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Bookings</h1>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>
          {ev.title ? ev.title + " · " + ev.durationMin + " min · " : ""}prospects book themselves; nothing is sent to them.
          {data && !data.google && " Google Calendar not connected — bookings are kept here only."}
        </div>
      </div>

      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {data && data.link ? <BkLinkRow label="Booking link" url={data.link} /> : <window.LoadingRow label="Loading link…" />}
        {data && <BkRefBuilder base={data.link} />}
      </div>

      <div>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Upcoming calls{rows.length ? " (" + rows.length + ")" : ""}</div>
        {error && <div style={{ color: "var(--red)", fontSize: 12.5 }}>{error}</div>}
        {loading && !data && <window.LoadingRow label="Loading bookings…" />}
        {data && rows.length === 0 && (
          <div className="card empty">
            <div className="empty-ico">📅</div>
            <div style={{ fontSize: 13 }}>No calls booked yet. Share the booking link with prospects.</div>
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {rows.map((b) => <BkRow key={b.id} b={b} busy={busy} onCancel={cancel} onConfirm={confirmLead} />)}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { AgencyBookings });
