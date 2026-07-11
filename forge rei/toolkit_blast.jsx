// Wholesaler Toolkit — Buyer Blast UI (Phase 2). The dispo blast page: pick a deal
// (homeowner search or from the dispo worklist), review its buyer-facing deal sheet,
// pick the buyers whose box it fits, then create + send a blast and track each
// buyer's response. Open Decision #1 resolved GHL-native: sends are real GHL SMS
// only when FORGE_BLAST_LIVE=1 on the box ({live} from /api/toolkit/blast/list);
// otherwise they stay stubbed and nothing leaves the box.
//
// Endpoints wired:
//   GET  /api/toolkit/blast/matches?contactId=  -> {deal, sheet, matches, buyerCount}
//   GET  /api/toolkit/blast/list                -> {blasts:[...]}
//   GET  /api/toolkit/blast/get?id=             -> {blast}
//   GET  /api/contacts?query=&limit=8           -> {contacts:[...]}
//   GET  /api/buyers/dispo                       -> {dispo:[...], buyerCount}
//   POST /api/toolkit/blast/photos              {dealId, photos:[dataURL]}
//   POST /api/toolkit/blast/create              {contactId, channels, buyerIds}
//   POST /api/toolkit/blast/send                {id}
//   POST /api/toolkit/blast/recipient          {id, buyerId, ...draft/status/note}
//   POST /api/toolkit/blast/respond            {id, buyerId, verdict}
//
// Conventions (root CLAUDE.md §7 — violation = white screen):
//   - Hook aliases reserved for this file: useStateBl/useEffectBl/useRefBl/useMemoBl
//   - Top-level names prefixed Bl...   - Export via Object.assign(window, {...})
//   - No computed JSX tags — resolve icons to a const first
//   - Never display an assignment fee on the deal sheet.
const { useState: useStateBl, useEffect: useEffectBl, useRef: useRefBl, useMemo: useMemoBl } = React;

const BL_GREEN = "#22C55E", BL_ORANGE = "#F59E0B", BL_RED = "#EF4444",
  BL_BLUE = "#4F7CFF", BL_VIOLET = "#8B5CF6", BL_FAINT = "#64748B";

const blInput = {
  background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 8,
  padding: "8px 10px", color: "var(--text)", fontSize: 12.5, fontFamily: "inherit", width: "100%",
};

// ≥80 green · ≥50 orange · else faint
const BlScoreColor = (s) => (s >= 80 ? BL_GREEN : s >= 50 ? BL_ORANGE : BL_FAINT);

// unwrap {blast} or a bare blast record
function blUnwrap(r) { return r && r.blast ? r.blast : r; }

// per-recipient status -> pill color + label
function BlStatusMeta(s) {
  const v = String(s || "queued").toLowerCase();
  if (v === "sent" || v === "stub-sent" || v === "stub_sent" || v === "blasted") return { c: BL_BLUE, label: v.replace("_", "-") };
  if (v === "skipped") return { c: BL_ORANGE, label: v };
  if (v === "failed") return { c: BL_RED, label: v };
  return { c: BL_FAINT, label: v };
}

function BlPill({ text, color }) {
  const c = color || BL_FAINT;
  return (
    <span className="pill" style={{ fontSize: 10.5, fontWeight: 600, color: c, background: c + "1f", border: "1px solid " + c + "3a" }}>{text}</span>
  );
}

function BlSectionLabel({ children, right }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
      <div className="faint" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600 }}>{children}</div>
      {right != null && <div className="faint" style={{ fontSize: 11 }}>{right}</div>}
    </div>
  );
}

function BlStat({ label, value, color }) {
  return (
    <div style={{ flex: 1, minWidth: 96 }}>
      <div className="faint" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div className="tabnum" style={{ fontSize: 17, fontWeight: 800, color: color || "var(--text)", marginTop: 2 }}>{value}</div>
    </div>
  );
}

// ---- deal sheet card (buyer-facing numbers + photos) ---------------------------
function BlDealSheet({ sheet, contactId, onRefresh }) {
  const Icons = window.Icons;
  const M = window.fmtMoney;
  const [uploading, setUploading] = useStateBl(false);
  const [err, setErr] = useStateBl(null);
  const s = sheet || {};
  const photos = s.photos || [];

  const specParts = [];
  if (s.beds != null && s.beds !== "") specParts.push(s.beds + " bd");
  if (s.baths != null && s.baths !== "") specParts.push(s.baths + " ba");
  if (s.sqft != null && s.sqft !== "") specParts.push(Number(s.sqft).toLocaleString() + " sqft");

  const profitLine = (s.profit != null ? M(s.profit) : "—") + (s.roiPct != null ? "  ·  " + Math.round(s.roiPct) + "% ROI" : "");

  function onPhotoFiles(fileList) {
    const arr = Array.prototype.slice.call(fileList || []);
    if (!arr.length) return;
    setUploading(true); setErr(null);
    Promise.all(arr.map((f) => new Promise((res) => {
      const rd = new FileReader();
      rd.onload = () => res(rd.result);
      rd.onerror = () => res(null);
      rd.readAsDataURL(f);
    }))).then(async (urls) => {
      const dataUrls = urls.filter(Boolean);
      if (!dataUrls.length) { setUploading(false); return; }
      try {
        await window.apiPost("/api/toolkit/blast/photos", { dealId: contactId, photos: dataUrls });
        onRefresh && onRefresh();
      } catch (e) { setErr(e.message || String(e)); }
      finally { setUploading(false); }
    });
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 13 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{s.address || s.name || "Deal sheet"}</div>
          <div className="faint" style={{ fontSize: 12, marginTop: 2 }}>
            {specParts.length ? specParts.join("  ·  ") : "specs TBD"}
            {s.condition ? "   —   " + s.condition + " condition" : ""}
          </div>
        </div>
        <BlPill text="buyer view" color={BL_VIOLET} />
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", borderTop: "1px solid var(--border)", paddingTop: 12 }}>
        <BlStat label="ARV" value={M(s.arv)} />
        <BlStat label="Buyer price" value={M(s.purchase)} color={BL_BLUE} />
        <BlStat label="Est. profit" value={profitLine} color={BL_GREEN} />
      </div>

      {/* Photo strip */}
      <div>
        <div className="faint" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>Photos</div>
        {photos.length ? (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {photos.map((p, i) => (
              <img key={i} src={p} alt="" style={{ height: 72, width: 96, borderRadius: 8, objectFit: "cover", border: "1px solid var(--border)" }} />
            ))}
          </div>
        ) : (
          <div className="faint" style={{ fontSize: 11.5 }}>No photos yet — add a few so buyers can see the property.</div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 9 }}>
          <label className="tab" style={{ fontSize: 11.5, padding: "6px 12px", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 7 }}>
            <Icons.Import size={13} /> {uploading ? "Uploading…" : "Add photos"}
            <input type="file" accept="image/*" multiple onChange={(e) => onPhotoFiles(e.target.files)} disabled={uploading} style={{ display: "none" }} />
          </label>
          {err && <span className="mono" style={{ color: "var(--red)", fontSize: 11 }}>{err}</span>}
        </div>
      </div>
    </div>
  );
}

// ---- one matched-buyer row (selectable) ----------------------------------------
function BlMatchRow({ m, checked, onToggle }) {
  const [open, setOpen] = useStateBl(false);
  const b = m.buyer || {};
  const sc = BlScoreColor(m.score);
  const reasons = m.reasons || [];
  const w = Math.max(0, Math.min(100, m.score || 0));
  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "9px 0", display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <input type="checkbox" checked={!!checked} onChange={() => onToggle(m.buyerId)} style={{ width: 16, height: 16, cursor: "pointer", flexShrink: 0 }} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 12.5, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span>{m.name || m.buyerId}</span>
            {m.fits ? <BlPill text="fits box" color={BL_GREEN} /> : <BlPill text="outside box" color={BL_FAINT} />}
          </div>
          <div className="faint mono" style={{ fontSize: 10.5, display: "flex", gap: 12, marginTop: 3, alignItems: "center" }}>
            <span title="phone on file" style={{ color: b.phone ? "var(--green)" : "var(--text-3)" }}>{"☎"} {b.phone ? "✓" : "—"}</span>
            <span title="email on file" style={{ color: b.email ? "var(--green)" : "var(--text-3)" }}>{"✉"} {b.email ? "✓" : "—"}</span>
            {reasons.length > 0 && (
              <span className="link" style={{ cursor: "pointer", fontSize: 11 }} onClick={() => setOpen((o) => !o)}>{open ? "hide why" : "why"}</span>
            )}
          </div>
        </div>
        <div style={{ width: 42, textAlign: "center", flexShrink: 0 }}>
          <div style={{ fontWeight: 800, fontSize: 15, color: sc }}>{m.score}</div>
          <div style={{ height: 3, borderRadius: 2, background: "var(--card-2)", marginTop: 2 }}>
            <div style={{ height: 3, borderRadius: 2, width: w + "%", background: sc }} />
          </div>
        </div>
      </div>
      {open && reasons.length > 0 && (
        <div style={{ paddingLeft: 26, display: "flex", flexDirection: "column", gap: 2 }}>
          {reasons.map((r, i) => (<div key={i} className="faint" style={{ fontSize: 10.5 }}>{"· " + r}</div>))}
        </div>
      )}
    </div>
  );
}

// ---- one recipient row in the blast detail (draft + response) ------------------
function BlRecipientRow({ blast, r, onChanged }) {
  const rchan = String(r.channel || "").toLowerCase() === "email"
    ? "email"
    : (((blast.channels || []).indexOf("email") >= 0 && (blast.channels || []).indexOf("sms") < 0) ? "email" : "sms");
  const [sms, setSms] = useStateBl(r.smsDraft || "");
  const [subj, setSubj] = useStateBl(r.emailSubject || "");
  const [body, setBody] = useStateBl(r.emailBody || "");
  const [busy, setBusy] = useStateBl(false);
  const [msg, setMsg] = useStateBl(null);
  const meta = BlStatusMeta(r.status);
  const cur = String(r.verdict || r.response || "none").toLowerCase();

  async function saveDraft() {
    setBusy(true); setMsg(null);
    try {
      const payload = { id: blast.id, buyerId: r.buyerId, channel: rchan };
      if (rchan === "email") { payload.emailSubject = subj; payload.emailBody = body; }
      else { payload.smsDraft = sms; }
      const res = await window.apiPost("/api/toolkit/blast/recipient", payload);
      onChanged(blUnwrap(res));
      setMsg({ ok: true, t: "saved" });
    } catch (e) { setMsg({ ok: false, t: e.message || String(e) }); }
    finally { setBusy(false); }
  }
  async function respond(verdict) {
    setBusy(true);
    try {
      const res = await window.apiPost("/api/toolkit/blast/respond", { id: blast.id, buyerId: r.buyerId, verdict });
      onChanged(blUnwrap(res));
    } catch (e) { setMsg({ ok: false, t: e.message || String(e) }); }
    finally { setBusy(false); }
  }

  const RESP = [
    { key: "interested", label: "Interested", color: BL_GREEN },
    { key: "passed", label: "Passed", color: BL_RED },
    { key: "noreply", label: "No reply", color: BL_FAINT },
  ];

  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "11px 0", display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ fontWeight: 600, fontSize: 12.5, flex: 1, minWidth: 120 }}>
          {r.name || r.buyerId}
          {r.score != null && <span className="tabnum" style={{ marginLeft: 8, fontSize: 12, fontWeight: 800, color: BlScoreColor(r.score) }}>{r.score}</span>}
        </div>
        <BlPill text={rchan.toUpperCase()} color={BL_VIOLET} />
        <BlPill text={meta.label} color={meta.c} />
      </div>
      {r.note && <div className="faint" style={{ fontSize: 11 }}>{r.note}</div>}

      {rchan === "email" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <input style={blInput} value={subj} onChange={(e) => setSubj(e.target.value)} placeholder="Email subject" />
          <textarea style={{ ...blInput, minHeight: 60, resize: "vertical", lineHeight: 1.4 }} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Email body draft…" />
        </div>
      ) : (
        <textarea style={{ ...blInput, minHeight: 54, resize: "vertical", lineHeight: 1.4 }} value={sms} onChange={(e) => setSms(e.target.value)} placeholder="SMS draft to this buyer…" />
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <button className="tab" onClick={saveDraft} disabled={busy} style={{ fontSize: 11.5, padding: "5px 12px" }}>{busy ? "Saving…" : "Save draft"}</button>
        {/* response segmented control */}
        <div style={{ display: "flex", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          {RESP.map((o) => {
            const on = cur === o.key;
            return (
              <button key={o.key} onClick={() => respond(o.key)} disabled={busy}
                style={{ fontSize: 11, fontWeight: 600, padding: "5px 11px", border: "none", cursor: "pointer",
                  borderRight: "1px solid var(--border)",
                  background: on ? o.color : "var(--card-2)", color: on ? "#fff" : "var(--text-3)" }}>
                {o.label}
              </button>
            );
          })}
        </div>
        {msg && <span style={{ fontSize: 11.5, fontWeight: 600, color: msg.ok ? "var(--green)" : "var(--red)" }}>{msg.ok ? "✓ " : ""}{msg.t}</span>}
      </div>
    </div>
  );
}

// ---- the active blast detail ----------------------------------------------------
function BlBlastDetail({ blast, onChanged, live }) {
  const [sending, setSending] = useStateBl(false);
  const [summary, setSummary] = useStateBl(null);
  const [err, setErr] = useStateBl(null);
  const recips = blast.recipients || [];
  const meta = BlStatusMeta(blast.status);

  async function send() {
    const n = recips.length;
    const ask = live
      ? `LIVE — this texts ${n} buyer${n === 1 ? "" : "s"} through GHL right now. Send?`
      : `This is a STUB — nothing actually sends yet. Mark ${n} buyer${n === 1 ? "" : "s"} as blasted?`;
    if (!window.confirm(ask)) return;
    setSending(true); setErr(null);
    try {
      const res = await window.apiPost("/api/toolkit/blast/send", { id: blast.id });
      setSummary(res.summary ? { ...res.summary, live: !!res.live } : null);
      onChanged(blUnwrap(res));
    } catch (e) { setErr(e.message || String(e)); }
    finally { setSending(false); }
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 13 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{blast.dealName || blast.dealId || "Blast"}</div>
          <div className="faint" style={{ fontSize: 12, marginTop: 2 }}>{blast.address || "address TBD"}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <BlPill text={meta.label} color={meta.c} />
          <button onClick={send} disabled={sending}
            style={{ display: "flex", alignItems: "center", gap: 7, padding: "9px 15px", borderRadius: 10, fontSize: 12.5, fontWeight: 700, color: "#fff", border: "none", cursor: "pointer",
              background: live ? "linear-gradient(135deg,#22C55E,#15803d)" : "linear-gradient(135deg,#F59E0B,#d97706)", opacity: sending ? 0.6 : 1 }}>
            {sending ? "Sending…" : live ? "Send blast (LIVE)" : "Send blast (stub)"}
          </button>
        </div>
      </div>

      {err && <div className="mono" style={{ color: "var(--red)", fontSize: 11.5 }}>{err}</div>}
      {summary && (
        <div style={{ display: "flex", gap: 14, background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 14px", fontSize: 12.5, fontWeight: 600 }}>
          <span style={{ color: summary.live ? BL_GREEN : BL_BLUE }}>{summary.sent || 0} {summary.live ? "sent" : "stub-sent"}</span>
          <span style={{ color: BL_ORANGE }}>{summary.skipped || 0} skipped</span>
          <span style={{ color: BL_RED }}>{summary.failed || 0} failed</span>
          <span className="faint" style={{ marginLeft: "auto", fontWeight: 500 }}>{summary.live ? "sent via GHL SMS" : "no texts/emails left the box"}</span>
        </div>
      )}

      <div>
        <BlSectionLabel right={recips.length + " recipient" + (recips.length === 1 ? "" : "s")}>Recipients</BlSectionLabel>
        {recips.length ? recips.map((r) => (
          <BlRecipientRow key={r.buyerId} blast={blast} r={r} onChanged={onChanged} />
        )) : (
          <div className="faint" style={{ fontSize: 11.5, paddingTop: 8 }}>No recipients on this blast.</div>
        )}
      </div>
    </div>
  );
}

// ---- collapsible recent-blasts list --------------------------------------------
function BlRecentBlasts({ rows, loading, error, activeId, onOpen }) {
  const [open, setOpen] = useStateBl(true);
  const Icons = window.Icons;
  const Chev = open ? Icons.Chevron : Icons.ChevronR;
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div onClick={() => setOpen((o) => !o)} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
        <Chev size={16} />
        <div style={{ fontWeight: 700, fontSize: 13.5 }}>Recent blasts</div>
        <div className="faint" style={{ fontSize: 11.5, marginLeft: "auto" }}>{rows.length || 0}</div>
      </div>
      {open && (
        <div style={{ display: "flex", flexDirection: "column" }}>
          {loading && !rows.length ? (
            <div className="faint" style={{ fontSize: 11.5, padding: "6px 0" }}>Loading…</div>
          ) : error ? (
            <div className="mono" style={{ color: "var(--red)", fontSize: 11.5, padding: "6px 0" }}>{error}</div>
          ) : rows.length ? rows.map((bl) => {
            const meta = BlStatusMeta(bl.status);
            const rc = (bl.recipients || []).length;
            const on = activeId === bl.id;
            return (
              <div key={bl.id} onClick={() => onOpen(bl.id)}
                style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 8px", cursor: "pointer", borderTop: "1px solid var(--border)",
                  borderRadius: 8, background: on ? "var(--card-2)" : "transparent" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 12.5 }}>{bl.dealName || bl.dealId || bl.id}</div>
                  <div className="faint" style={{ fontSize: 11 }}>{bl.address || "address TBD"}</div>
                </div>
                <div className="faint" style={{ fontSize: 11 }}>{rc} bx</div>
                <BlPill text={meta.label} color={meta.c} />
                <div className="faint mono" style={{ fontSize: 10.5, minWidth: 62, textAlign: "right" }}>{window.timeAgo(bl.createdAt)}</div>
              </div>
            );
          }) : (
            <div className="faint" style={{ fontSize: 11.5, padding: "6px 0" }}>No blasts yet — create one above.</div>
          )}
        </div>
      )}
    </div>
  );
}

// ---- the page ------------------------------------------------------------------
function BlastPage() {
  const Icons = window.Icons;
  const M = window.fmtMoney;
  const SendIco = window.Icons.Send || window.Icons.Bot;

  const [mode, setMode] = useStateBl("search");   // "search" | "dispo"
  const [cq, setCq] = useStateBl("");
  const [cres, setCres] = useStateBl([]);
  const [picked, setPicked] = useStateBl(null);   // {id, name, address, phone}
  const [channels, setChannels] = useStateBl(["sms"]);
  const [checked, setChecked] = useStateBl({});   // buyerId -> bool
  const [activeBlast, setActiveBlast] = useStateBl(null);
  const [creating, setCreating] = useStateBl(false);
  const [createErr, setCreateErr] = useStateBl(null);

  const detailRef = useRefBl(null);
  const initedRef = useRefBl(null);

  const contactId = picked ? picked.id : null;
  const matchesPath = contactId
    ? "/api/toolkit/blast/matches?contactId=" + encodeURIComponent(contactId)
    : "/api/toolkit/blast/matches?contactId=__none__";
  const matchesApi = window.useApi(matchesPath);
  const listApi = window.useApi("/api/toolkit/blast/list");
  const dispoApi = window.useApi("/api/buyers/dispo");

  const matchData = contactId ? matchesApi.data : null;
  const matches = (matchData && matchData.matches) || [];
  const sheet = matchData && matchData.sheet;
  const buyerCount = matchData && matchData.buyerCount != null ? matchData.buyerCount : (dispoApi.data && dispoApi.data.buyerCount);

  // default-check every buyer whose box fits, once per picked deal
  useEffectBl(() => {
    if (!contactId) { initedRef.current = null; return; }
    if (!matchData || !matchData.matches) return;
    if (initedRef.current === contactId) return;
    const init = {};
    matchData.matches.forEach((m) => { init[m.buyerId] = !!m.fits; });
    setChecked(init);
    initedRef.current = contactId;
  }, [contactId, matchData]);

  // debounced homeowner search
  useEffectBl(() => {
    if (picked || mode !== "search") { return; }
    if (cq.trim().length < 2) { setCres([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`/api/contacts?query=${encodeURIComponent(cq.trim())}&limit=8`);
        const j = await r.json();
        setCres((j.contacts || []).filter((c) => c.phone));
      } catch (e) { setCres([]); }
    }, 350);
    return () => clearTimeout(t);
  }, [cq, picked, mode]);

  const checkedIds = useMemoBl(() => matches.filter((m) => checked[m.buyerId]).map((m) => m.buyerId), [matches, checked]);
  const activeChan = channels.indexOf("sms") >= 0 && channels.indexOf("email") >= 0
    ? "both" : (channels.indexOf("email") >= 0 ? "email" : "sms");
  const dispoRows = (dispoApi.data && dispoApi.data.dispo) || [];
  const blasts = (listApi.data && listApi.data.blasts) || [];
  const live = !!(listApi.data && listApi.data.live);

  function toggle(id) { setChecked((p) => ({ ...p, [id]: !p[id] })); }
  function pickContact(obj) { setPicked(obj); setCres([]); setCq(obj.name || ""); setCreateErr(null); }
  function unpick() { setPicked(null); setCq(""); setCres([]); initedRef.current = null; }

  const CHAN = [
    { key: "sms", label: "SMS", val: ["sms"] },
    { key: "email", label: "Email", val: ["email"] },
    { key: "both", label: "Both", val: ["sms", "email"] },
  ];

  async function createBlast() {
    if (!contactId || !checkedIds.length) return;
    setCreating(true); setCreateErr(null);
    try {
      const res = await window.apiPost("/api/toolkit/blast/create", { contactId, channels, buyerIds: checkedIds });
      const b = blUnwrap(res);
      setActiveBlast(b);
      listApi.refresh();
      setTimeout(() => { detailRef.current && detailRef.current.scrollIntoView({ behavior: "smooth", block: "start" }); }, 60);
    } catch (e) { setCreateErr(e.message || String(e)); }
    finally { setCreating(false); }
  }

  async function openBlast(id) {
    try {
      const r = await window.apiGet("/api/toolkit/blast/get?id=" + encodeURIComponent(id));
      setActiveBlast(blUnwrap(r));
      setTimeout(() => { detailRef.current && detailRef.current.scrollIntoView({ behavior: "smooth", block: "start" }); }, 60);
    } catch (e) { /* leave prior detail in place */ }
  }

  function onDetailChanged(updated) {
    if (updated) setActiveBlast(updated);
    listApi.refresh();
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Header */}
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px", display: "flex", alignItems: "center", gap: 10 }}>
          <SendIco size={22} /> Buyer Blast
        </h1>
        <p className="faint" style={{ fontSize: 13.5, marginTop: 3 }}>Push a locked deal to your matched cash buyers — pick the deal, select who it fits, blast + track responses.</p>
      </div>

      {/* Send-mode banner: live (GHL) vs stub */}
      {live ? (
        <div style={{ background: "rgba(34,197,94,0.10)", border: "1px solid var(--green)", borderRadius: 11, padding: "11px 14px", fontSize: 12.5, lineHeight: 1.5 }}>
          <span style={{ color: "var(--green)", fontWeight: 700 }}>{"●"} Sends are LIVE via GHL SMS</span>
          <span className="faint"> — approving a blast texts real buyers (9am-8pm ET window enforced). Unset FORGE_BLAST_LIVE on the box to go back to stub mode.</span>
        </div>
      ) : (
        <div style={{ background: "var(--orange)14", border: "1px solid var(--orange)", borderRadius: 11, padding: "11px 14px", fontSize: 12.5, lineHeight: 1.5 }}>
          <span style={{ color: "var(--orange)", fontWeight: 700 }}>{"⚠"} Sends are STUBBED</span>
          <span className="faint"> — GHL transport is wired but OFF. Set FORGE_BLAST_LIVE=1 on the box to text real buyers; until then nothing leaves the box.</span>
        </div>
      )}

      {/* Mode picker */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {!picked ? (
          <React.Fragment>
            <div style={{ display: "flex", gap: 8 }}>
              <button className={"tab" + (mode === "search" ? " active" : "")} onClick={() => setMode("search")} style={{ fontSize: 12 }}>Search homeowner</button>
              <button className={"tab" + (mode === "dispo" ? " active" : "")} onClick={() => setMode("dispo")} style={{ fontSize: 12 }}>From dispo</button>
            </div>

            {mode === "search" ? (
              <div style={{ position: "relative", maxWidth: 480 }}>
                <div className="search" style={{ width: "100%" }}>
                  <Icons.Search size={16} />
                  <input value={cq} onChange={(e) => setCq(e.target.value)} placeholder="Search a homeowner by name or phone…" />
                </div>
                {cres.length > 0 && (
                  <div className="card" style={{ position: "absolute", zIndex: 5, top: "100%", left: 0, right: 0, marginTop: 4, maxHeight: 280, overflowY: "auto" }}>
                    {cres.map((c) => (
                      <div key={c.id} onClick={() => pickContact({ id: c.id, name: c.name, address: c.addr, phone: c.phone })}
                        className="row-item" style={{ padding: "10px 12px", cursor: "pointer" }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 13, fontWeight: 600 }}>{c.name || "(no name)"}</div>
                          <div className="faint mono" style={{ fontSize: 11 }}>{c.phone}{c.addr ? "  ·  " + c.addr : ""}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {dispoApi.loading && !dispoRows.length ? (
                  <div className="faint" style={{ fontSize: 12 }}>Loading…</div>
                ) : dispoApi.error ? (
                  <div className="mono" style={{ color: "var(--red)", fontSize: 12 }}>{dispoApi.error}</div>
                ) : dispoRows.length ? dispoRows.map((row) => {
                  const d = row.deal || {};
                  return (
                    <div key={d.contactId} onClick={() => pickContact({ id: d.contactId, name: d.name, address: d.address })}
                      className="row-item" style={{ padding: "10px 12px", cursor: "pointer", background: "var(--card-2)", borderRadius: 8, borderBottom: "none" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>{d.name || d.contactId}</div>
                        <div className="faint" style={{ fontSize: 11 }}>{d.address || "address TBD"}</div>
                      </div>
                      <BlPill text={d.stage || "Offer"} color={BL_VIOLET} />
                    </div>
                  );
                }) : (
                  <div className="faint" style={{ fontSize: 12 }}>No deals in the dispo worklist yet. Lock a deal or search a homeowner above.</div>
                )}
              </div>
            )}
          </React.Fragment>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 10, background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 13px" }}>
            <Icons.MapPin size={16} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>{picked.name || picked.id}</div>
              <div className="faint mono" style={{ fontSize: 11.5 }}>{picked.address || ""}{picked.phone ? (picked.address ? "  ·  " : "") + picked.phone : ""}</div>
            </div>
            <button className="link" onClick={unpick} style={{ fontSize: 12 }}>change</button>
          </div>
        )}
      </div>

      {/* Deal + matches (only when a deal is picked) */}
      {contactId && (
        <React.Fragment>
          {matchesApi.loading && !matchData ? (
            <div className="faint" style={{ fontSize: 12.5, padding: "4px 2px" }}>Loading deal sheet…</div>
          ) : matchesApi.error ? (
            <div className="card card-pad"><div className="mono" style={{ color: "var(--red)", fontSize: 12.5 }}>{matchesApi.error}</div></div>
          ) : (
            <React.Fragment>
              {sheet && <BlDealSheet sheet={sheet} contactId={contactId} onRefresh={matchesApi.refresh} />}

              {/* Channels */}
              <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                  <div className="faint" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600 }}>Channel</div>
                  <div style={{ display: "flex", gap: 7 }}>
                    {CHAN.map((o) => {
                      const on = activeChan === o.key;
                      return (
                        <button key={o.key} onClick={() => setChannels(o.val)} className="tab"
                          style={{ fontSize: 11.5, padding: "5px 13px", background: on ? BL_BLUE : "var(--card-2)", color: on ? "#fff" : "var(--text-3)", border: "1px solid " + (on ? "transparent" : "var(--border)") }}>
                          {o.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Matched buyers */}
                <BlSectionLabel right={(buyerCount != null ? buyerCount + " buyers · " : "") + checkedIds.length + " selected"}>Matched buyers</BlSectionLabel>
                {matches.length ? (
                  <div>
                    {matches.map((m) => (
                      <BlMatchRow key={m.buyerId} m={m} checked={!!checked[m.buyerId]} onToggle={toggle} />
                    ))}
                  </div>
                ) : (
                  <div className="faint" style={{ fontSize: 11.5, paddingTop: 4 }}>No buyers match this deal yet — add cash buyers on the Dispositions page for this area/price.</div>
                )}

                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 2 }}>
                  <button onClick={createBlast} disabled={creating || !checkedIds.length}
                    style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 18px", borderRadius: 11, fontSize: 13, fontWeight: 700, color: "#fff", border: "none",
                      cursor: checkedIds.length ? "pointer" : "default",
                      background: checkedIds.length ? "linear-gradient(135deg,#4F7CFF,#6366F1)" : "var(--card-2)", opacity: creating ? 0.6 : 1 }}>
                    <Icons.Send size={15} /> {creating ? "Creating…" : `Create blast (${checkedIds.length})`}
                  </button>
                  {createErr && <span style={{ fontSize: 12, fontWeight: 600, color: "var(--red)" }}>{createErr}</span>}
                  <span className="faint" style={{ fontSize: 11 }}>Creates the blast + drafts — sending stays a separate, approval-gated step below.</span>
                </div>
              </div>
            </React.Fragment>
          )}
        </React.Fragment>
      )}

      {/* Recent blasts */}
      <BlRecentBlasts rows={blasts} loading={listApi.loading} error={listApi.error} activeId={activeBlast && activeBlast.id} onOpen={openBlast} />

      {/* Active blast detail */}
      <div ref={detailRef}>
        {activeBlast && <BlBlastDetail blast={activeBlast} onChanged={onDetailChanged} live={live} />}
      </div>
    </div>
  );
}

Object.assign(window, { BlastPage });
