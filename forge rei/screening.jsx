// screening.jsx — Marcus Lead-Screening module. Marcus reads each seller thread +
// Scout's triage and writes a Seller Screening Report (1-10 call-readiness score,
// missing info, red flags, call-prep, stage rec) so the operator knows who to CALL.
// Marcus never texts/offers/talks numbers — decision support only. Stage buttons
// reuse Scout's already-gated GHL writes.
const { useState: useStateScr } = React;

const SCR_SCORE = (s) => (s >= 7 ? "#22C55E" : s >= 4 ? "#F59E0B" : s >= 1 ? "#EF4444" : "#64748B");
const SCR_STAGE_COLOR = {
  "Hot Lead - Call Now": "#EF4444", "Qualified - Call": "#22C55E",
  "Needs More Info": "#F59E0B", "Follow-Up": "#8B5CF6",
  "New Lead": "#4F7CFF", "Dead Lead": "#64748B",
};
const SCR_MOT = (m) => (m >= 70 ? "#22C55E" : m >= 40 ? "#F59E0B" : "#EF4444");

function ScrPill({ text, color, faintBg }) {
  return (
    <span className="pill" style={{
      fontSize: 10.5, fontWeight: 600, color,
      background: color + (faintBg || "1f"), border: "1px solid " + color + "44",
    }}>{text}</span>
  );
}

function ScrField({ label, value, color }) {
  if (!value) return null;
  return (
    <div style={{ minWidth: 0 }}>
      <div className="faint" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 12.5, fontWeight: 600, color: color || "var(--text)" }}>{value}</div>
    </div>
  );
}

function ScrList({ title, items, color, prefix }) {
  if (!items || !items.length) return null;
  return (
    <div>
      <div className="faint" style={{ fontSize: 11, marginBottom: 4 }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {items.map((it, i) => (
          <div key={i} style={{ fontSize: 12.5, display: "flex", gap: 7, alignItems: "flex-start" }}>
            <span style={{ color: color || "var(--text-3)", flexShrink: 0 }}>{prefix || "•"}</span>
            <span>{it}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ScrChecklist({ items }) {
  const [done, setDone] = useStateScr({});
  if (!items || !items.length) return null;
  return (
    <div style={{ background: "var(--card-2)", borderRadius: 10, padding: "10px 12px" }}>
      <div className="faint" style={{ fontSize: 11, marginBottom: 6 }}>Missing info — confirm on the call</div>
      {items.map((m, i) => (
        <label key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, padding: "3px 0", cursor: "pointer" }}>
          <input type="checkbox" checked={!!done[i]} onChange={() => setDone((d) => ({ ...d, [i]: !d[i] }))}
            style={{ width: 15, height: 15, accentColor: "var(--blue)" }} />
          <span style={{ textDecoration: done[i] ? "line-through" : "none", opacity: done[i] ? 0.5 : 1 }}>{m}</span>
        </label>
      ))}
    </div>
  );
}

function ScrCallPrep({ cp }) {
  if (!cp) return null;
  return (
    <div style={{ border: "1px solid rgba(79,124,255,0.3)", borderRadius: 10, padding: "11px 13px", display: "flex", flexDirection: "column", gap: 9 }}>
      <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--blue)" }}>📞 Call prep</div>
      {cp.opener && (
        <div style={{ fontSize: 12.5 }}>
          <span className="faint">Opener: </span><span style={{ fontStyle: "italic" }}>"{cp.opener}"</span>
        </div>
      )}
      <ScrList title="Ask" items={cp.questions} color="var(--blue)" prefix="?" />
      <ScrList title="Listen for (motivation)" items={cp.painPoints} color="var(--green)" prefix="♥" />
      <ScrList title="Do NOT say" items={cp.avoid} color="var(--red)" prefix="✕" />
    </div>
  );
}

function ScreeningCard({ s, onChange }) {
  const rep = s.report || {};
  const [busy, setBusy] = useStateScr(null);
  const [note, setNote] = useStateScr(s.notes || "");
  const [saved, setSaved] = useStateScr(false);
  const [nMsg, setNMsg] = useStateScr(rep.nurtureDraft || "");
  const [nSent, setNSent] = useStateScr(!!s.nurtureSentAt);

  async function act(fn, key) {
    setBusy(key);
    try { await fn(); } catch (e) { alert("Marcus: " + e.message); }
    setBusy(null);
    if (onChange) onChange();
  }
  const setStage = (stage) => act(() => window.apiPost("/api/screening/stage", { contactId: s.contactId, stage }), stage);
  const rescreen = () => act(() => window.apiPost("/api/screening/run", { contactId: s.contactId }), "rescreen");
  const sendNurture = () => act(async () => { await window.apiPost("/api/screening/send", { contactId: s.contactId, message: nMsg }); setNSent(true); }, "nurture");
  async function saveNote() {
    try { await window.apiPost("/api/screening/note", { contactId: s.contactId, note }); setSaved(true); setTimeout(() => setSaved(false), 1500); }
    catch (e) { alert("Marcus: " + e.message); }
  }

  const sc = rep.score != null ? rep.score : s.score;
  const stageColor = SCR_STAGE_COLOR[s.stage] || "#4F7CFF";

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ width: 46, height: 46, borderRadius: 12, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
          background: SCR_SCORE(sc) + "22", border: "1px solid " + SCR_SCORE(sc) + "55" }}>
          <span style={{ fontSize: 18, fontWeight: 800, color: SCR_SCORE(sc) }}>{sc}</span>
        </div>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{s.name || "Unknown"}</div>
          <div className="faint mono" style={{ fontSize: 11 }}>{s.phone || "—"} · screened {window.timeAgo(s.updatedAt)}</div>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          {rep.interest === "not_ready" && <ScrPill text="💤 not ready now" color="#F59E0B" />}
          {rep.interest === "interested" && <ScrPill text="✋ interested" color="#22C55E" />}
          <ScrPill text={s.stage} color={stageColor} />
          {s.scoutMotivation != null && <ScrPill text={"Scout " + s.scoutMotivation} color={SCR_MOT(s.scoutMotivation)} />}
          {s.auto && <ScrPill text="auto" color="#8B5CF6" />}
        </div>
      </div>

      {/* Situation */}
      {rep.sellerSituation && <div style={{ fontSize: 13.5, lineHeight: 1.45 }}>{rep.sellerSituation}</div>}

      {/* Seller psychology read */}
      {rep.sellerPsychology && (
        <div style={{ fontSize: 12.5, lineHeight: 1.45, padding: "9px 12px", borderRadius: 10, background: "rgba(139,92,246,0.10)", border: "1px solid rgba(139,92,246,0.30)" }}>
          <span style={{ fontWeight: 700, color: "var(--violet)" }}>🧠 Seller psychology </span>{rep.sellerPsychology}
        </div>
      )}

      {/* Nurture lane — comfort + check-back draft (in your voice) for not-ready sellers */}
      {rep.interest === "not_ready" && rep.nurtureDraft && (
        <div style={{ border: "1px solid rgba(245,158,11,0.4)", borderRadius: 10, padding: "11px 13px", display: "flex", flexDirection: "column", gap: 8, background: "rgba(245,158,11,0.07)" }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--orange)" }}>
            💬 No-pressure check-back{rep.checkBackDays ? ` · in ~${rep.checkBackDays} days` : ""} <span className="faint" style={{ fontWeight: 400 }}>(your voice — Marcus drafts, you send)</span>
          </div>
          <textarea value={nMsg} onChange={(e) => setNMsg(e.target.value)} rows={2}
            style={{ width: "100%", resize: "vertical", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 10, padding: "9px 11px", fontSize: 13, fontFamily: "inherit", lineHeight: 1.4 }} />
          <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "flex-end" }}>
            {nSent && <span className="pill" style={{ fontSize: 10, background: "rgba(34,197,94,0.14)", color: "var(--green)" }}>✓ sent {window.timeAgo(s.nurtureSentAt)}</span>}
            <button onClick={sendNurture} disabled={busy === "nurture" || !nMsg.trim()}
              style={{ padding: "8px 15px", borderRadius: 10, background: "linear-gradient(135deg,#F59E0B,#d97706)", color: "#fff", fontWeight: 600, fontSize: 13, border: "none", cursor: "pointer" }}>
              {busy === "nurture" ? "Sending…" : (nSent ? "Send again" : "Send check-back")}
            </button>
          </div>
        </div>
      )}

      {/* Fact grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 12,
        background: "var(--card-2)", borderRadius: 10, padding: "11px 13px" }}>
        <ScrField label="Motivation" value={rep.motivationLevel} color={rep.motivationLevel === "high" ? "var(--green)" : rep.motivationLevel === "medium" ? "var(--orange)" : undefined} />
        <ScrField label="Property" value={rep.propertyStatus} />
        <ScrField label="Condition" value={rep.conditionNotes} />
        <ScrField label="Timeline" value={rep.timeline} />
        <ScrField label="Seller asking" value={rep.askingPrice} color="var(--green)" />
      </div>

      {/* Why call + recommended */}
      {rep.whyCall && (
        <div style={{ fontSize: 13, padding: "9px 12px", borderRadius: 10, background: SCR_SCORE(sc) + "14", border: "1px solid " + SCR_SCORE(sc) + "33" }}>
          <span className="faint" style={{ fontSize: 11 }}>Worth calling? </span>{rep.whyCall}
        </div>
      )}
      {/* Path to a signed contract */}
      {rep.pathToContract && (
        <div style={{ fontSize: 12.5, lineHeight: 1.45, padding: "10px 12px", borderRadius: 10, background: "rgba(34,197,94,0.10)", border: "1px solid rgba(34,197,94,0.32)" }}>
          <span style={{ fontWeight: 700, color: "var(--green)" }}>🎯 Path to contract </span>{rep.pathToContract}
        </div>
      )}
      {rep.recommendedAction && <div style={{ fontSize: 12.5, color: "var(--violet)", fontWeight: 600 }}>→ {rep.recommendedAction}</div>}

      <ScrChecklist items={rep.missing} />
      {rep.redFlags && rep.redFlags.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <span className="faint" style={{ fontSize: 11 }}>Red flags:</span>
          {rep.redFlags.map((f, i) => <ScrPill key={i} text={f} color="#EF4444" />)}
        </div>
      )}

      <ScrCallPrep cp={rep.callPrep} />

      {/* Operator call notes */}
      <div>
        <div className="faint" style={{ fontSize: 11, marginBottom: 5, display: "flex", justifyContent: "space-between" }}>
          <span>My call notes</span>{saved && <span style={{ color: "var(--green)" }}>saved ✓</span>}
        </div>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} onBlur={saveNote} rows={2}
          placeholder="Notes from your call…"
          style={{ width: "100%", resize: "vertical", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 10, padding: "9px 11px", fontSize: 13, fontFamily: "inherit", lineHeight: 1.4 }} />
      </div>

      {/* Stage actions (reuse Scout's gated GHL writes) */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end", alignItems: "center" }}>
        <button className="tab" onClick={rescreen} disabled={busy === "rescreen"} style={{ marginRight: "auto", border: "1px solid var(--border)" }}>
          {busy === "rescreen" ? "Re-screening…" : "↻ Re-screen"}
        </button>
        <button className="tab" onClick={() => setStage("Dead Lead")} disabled={!!busy} style={{ border: "1px solid var(--border)", color: "var(--text-2)" }}>Dead Lead</button>
        <button className="tab" onClick={() => setStage("Follow-Up")} disabled={!!busy} style={{ border: "1px solid var(--orange)", color: "var(--orange)" }}>→ Follow-Up</button>
        <button onClick={() => setStage("Qualified - Call")} disabled={!!busy}
          style={{ display: "flex", alignItems: "center", gap: 7, padding: "9px 16px", borderRadius: 11, background: "linear-gradient(135deg,#22C55E,#16a34a)", fontWeight: 600, fontSize: 13.5, color: "#fff", border: "none", cursor: "pointer" }}>
          ✓ Qualified – Call
        </button>
      </div>
    </div>
  );
}

function ScreeningPage() {
  const Icons = window.Icons;
  const { data, refresh } = window.useApi("/api/screening/queue", { interval: 15000 });
  const st = window.useApi("/api/screening/status", { interval: 15000 });
  const [cid, setCid] = useStateScr("");
  const [busy, setBusy] = useStateScr(null);
  const [aud, setAud] = useStateScr(null);
  const [audBusy, setAudBusy] = useStateScr(false);

  const o = st.data || {};
  const learn = o.learn || {};
  const rows = (data && data.screenings) || [];
  const reload = () => { refresh(); st.refresh(); };

  async function act(fn, key) {
    setBusy(key);
    try { await fn(); } catch (e) { alert("Marcus: " + e.message); }
    setBusy(null);
    reload();
  }
  const learnNow = () => act(() => window.apiPost("/api/screening/learn", {}), "learn");
  const screenOne = () => { if (cid.trim()) act(async () => { await window.apiPost("/api/screening/run", { contactId: cid.trim() }); setCid(""); }, "screen"); };
  async function auditNotReady() {
    setAudBusy(true);
    try { setAud(await window.apiPost("/api/screening/audit-not-ready", { days: 7 })); }
    catch (e) { alert("Audit: " + e.message); }
    setAudBusy(false);
  }

  const counts = {};
  rows.forEach((r) => { counts[r.stage] = (counts[r.stage] || 0) + 1; });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {/* Header */}
      <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
        <div className="marcus-orb" style={{ width: 60, height: 60, flexShrink: 0 }}>
          <div className="orb-core" style={{ width: 38, height: 38 }} />
        </div>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h1 style={{ fontSize: 22, fontWeight: 700 }}>Marcus · Lead Screening</h1>
            <span className="pill" style={{ background: "rgba(34,197,94,0.12)", color: "var(--green)", border: "1px solid rgba(34,197,94,0.3)" }}>
              <span className="dot online pulse" /> SCREENING
            </span>
          </div>
          <div className="faint" style={{ fontSize: 13, marginTop: 4 }}>Reads each seller thread + Scout's triage, scores call-readiness 1–10, and preps your call. Never texts, never offers, never talks price. You make the call.</div>
          <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>
            Screening: <b style={{ color: o.aiScreening ? "var(--green)" : "var(--orange)" }}>{o.aiScreening ? "Claude" : "no key"}</b>
            {" · "}playbook <b style={{ color: o.skillsLoaded ? "var(--green)" : "var(--orange)" }}>{o.skillsLoaded ? "loaded from brain" : "none"}</b>
            {" · "}auto-screen <b style={{ color: o.autoScreen ? "var(--green)" : "var(--text-3)" }}>{o.autoScreen ? "on" : "off"}</b>
            {" · "}self-improved <b>{learn.learnCount || 0}×</b>{learn.lastLearnedAt ? ` (last ${window.timeAgo(learn.lastLearnedAt)})` : ""}
            {o.lastError && <span style={{ color: "var(--red)" }}> · err: {o.lastError}</span>}
          </div>
        </div>
        <button className="tab" onClick={learnNow} disabled={busy === "learn"} style={{ borderColor: "var(--violet)", color: "var(--violet)" }} title="Marcus reflects on recent screenings + rewrites his playbook in the brain">
          {busy === "learn" ? "Learning…" : "Learn from brain"}
        </button>
      </div>

      {/* Screen-on-demand */}
      <div className="card card-pad" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span className="faint" style={{ fontSize: 12.5 }}>Screen a lead by contact ID</span>
        <input value={cid} onChange={(e) => setCid(e.target.value)} placeholder="GHL contactId"
          onKeyDown={(e) => { if (e.key === "Enter") screenOne(); }}
          style={{ flex: 1, minWidth: 200, background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: 10, padding: "9px 12px", fontSize: 13, fontFamily: "inherit" }} />
        <button className="tab" onClick={screenOne} disabled={busy === "screen" || !cid.trim()} style={{ border: "1px solid var(--blue)", color: "var(--blue)" }}>
          {busy === "screen" ? "Screening…" : "Screen"}
        </button>
        <span className="faint" style={{ fontSize: 11 }}>Hot leads auto-screen; or hand a lead to Marcus from Scout.</span>
      </div>

      {/* "Not ready" audit — last week's soft-no sellers + how you replied */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <div className="card-title" style={{ fontSize: 15, flex: 1, minWidth: 160 }}>💤 "Not ready" sellers — last week</div>
          <button className="tab" onClick={auditNotReady} disabled={audBusy} style={{ border: "1px solid var(--orange)", color: "var(--orange)" }}>
            {audBusy ? "Scanning…" : "Audit last 7 days"}
          </button>
        </div>
        <div className="faint" style={{ fontSize: 11 }}>Scans your last week of seller threads for "not right now" replies + how you responded — so you can nurture them with a check-back.</div>
        {aud && aud.notReady && (aud.notReady.length === 0 ? (
          <div className="faint" style={{ fontSize: 12.5 }}>None found in the last {aud.days} days (scanned {aud.scanned}).</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div className="faint" style={{ fontSize: 11.5 }}>{aud.count} found · scanned {aud.scanned}</div>
            {aud.notReady.map((n, i) => (
              <div key={i} style={{ background: "var(--card-2)", borderRadius: 10, padding: "9px 11px", fontSize: 12.5 }}>
                <div style={{ fontWeight: 600 }}>{n.name} <span className="faint mono" style={{ fontSize: 10.5, fontWeight: 400 }}>{n.phone}</span></div>
                <div style={{ marginTop: 3 }}><span className="faint">seller: </span>"{n.sellerSaid}"</div>
                <div style={{ marginTop: 2, color: n.replied ? "var(--text)" : "var(--red)" }}><span className="faint">you: </span>{n.yourReply}</div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Stage tallies */}
      {rows.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {(o.stages || Object.keys(counts)).filter((s) => counts[s]).map((s) => (
            <ScrPill key={s} text={`${s} · ${counts[s]}`} color={SCR_STAGE_COLOR[s] || "#4F7CFF"} faintBg="14" />
          ))}
        </div>
      )}

      {/* Queue */}
      {rows.length === 0 ? (
        <div className="card empty" style={{ minHeight: 200 }}>
          <div className="empty-ico"><Icons.Search size={26} /></div>
          <div style={{ fontWeight: 600, color: "var(--text)" }}>No screenings yet</div>
          <div style={{ fontSize: 12.5 }}>Marcus auto-screens hot leads Scout flags. Or paste a contact ID above to screen one now.</div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {rows.map((s) => <ScreeningCard key={s.contactId} s={s} onChange={reload} />)}
        </div>
      )}
    </div>
  );
}

window.ScreeningPage = ScreeningPage;
