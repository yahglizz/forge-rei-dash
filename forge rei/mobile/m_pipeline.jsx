// FORGE Mobile — Pipeline tab: GHL stages as horizontally-snapping columns.
// Tap a card -> stage sheet -> same POST /api/pipeline/move the desktop uses.
// Hook aliases for this file: MP. Exports: MPipelinePage.
const { useState: useStateMP, useEffect: useEffectMP, useRef: useRefMP, useMemo: useMemoMP } = React;

const MP_ACCENTS = ["#4F7CFF", "#8B5CF6", "#2DD4BF", "#22C55E", "#F59E0B", "#EC4899", "#64748B", "#EF4444"];

// ---- Phase 3 pipeline overlay: days-in-stage badge + local follow-up reminders.
// Mirrors desktop toolkit_pipeline.jsx (PIdealId / PIasMs / PIdaysMeta / reminder
// modal semantics). Local-only overlay — none of this ever writes to GHL.
const MP_GREEN = "#22C55E", MP_YELLOW = "#F59E0B", MP_RED = "#EF4444";
const MP_BLUE = "#4F7CFF", MP_FAINT = "#64748B";

function MPdealId(deal) {
  return String((deal && (deal.contactId || deal.dealId || deal.id)) || "");
}

function MPasMs(value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  if (Number.isFinite(n) && n > 0) return n < 20000000000 ? n * 1000 : n;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

function MPdaysMeta(deal) {
  const updated = MPasMs(deal && (deal.updatedAt != null ? deal.updatedAt : deal.updated));
  if (!updated) return { days: null, color: MP_FAINT, label: "date unavailable" };
  const days = Math.max(0, Math.ceil((Date.now() - updated) / 86400000));
  if (days < 3) return { days, color: MP_GREEN, label: "fresh" };
  if (days <= 7) return { days, color: MP_YELLOW, label: "watch" };
  return { days, color: MP_RED, label: "stale" };
}

function MPdueText(value) {
  const ms = MPasMs(value);
  return ms ? new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "no due time";
}

function MPtoLocalInput(ms) {
  const d = ms ? new Date(ms) : new Date(Date.now() + 86400000);
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T" + p(d.getHours()) + ":" + p(d.getMinutes());
}

function MPremStatus(reminder) {
  return String((reminder && reminder.status) || "pending").toLowerCase();
}

function MPremOverdue(reminder) {
  const st = MPremStatus(reminder);
  if (st === "snoozed") { const u = MPasMs(reminder.snoozedUntil); return u != null && u < Date.now(); }
  if (st === "pending") { const d = MPasMs(reminder.dueAt); return d != null && d < Date.now(); }
  return false;
}

function MPDaysBadge({ deal }) {
  const meta = MPdaysMeta(deal);
  return (
    <span title={meta.label} style={{
      color: meta.color, background: meta.color + "1d", border: "1px solid " + meta.color + "42",
      borderRadius: 999, padding: "2px 8px", fontSize: 10.5, fontWeight: 800, whiteSpace: "nowrap", flexShrink: 0,
    }}>
      {meta.days == null ? "—" : meta.days + "d"}
    </span>
  );
}

// ⏰ chip on a deal card. Pending/snoozed reminder -> due info (red tint when
// overdue); otherwise a faint "Remind" action. Rendered as a span because it
// lives inside the card <button>; stopPropagation keeps the move sheet closed.
function MPReminderChip({ reminder, onOpen }) {
  const st = MPremStatus(reminder);
  const live = !!reminder && (st === "pending" || st === "snoozed");
  const overdue = live && MPremOverdue(reminder);
  const color = !live ? "var(--text-3, #64748B)" : overdue ? MP_RED : MP_BLUE;
  const text = !live
    ? "Remind"
    : (st === "snoozed" ? "back " + MPdueText(reminder.snoozedUntil || reminder.dueAt) : "due " + MPdueText(reminder.dueAt))
      + (overdue ? " · overdue" : "");
  return (
    <span role="button" tabIndex={0}
      onClick={(e) => { e.stopPropagation(); e.preventDefault(); onOpen(); }}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6, minHeight: 40, padding: "0 12px",
        borderRadius: 999, fontSize: 11.5, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap",
        color,
        border: "1px solid " + (live ? (overdue ? "rgba(239,68,68,0.45)" : "rgba(79,124,255,0.4)") : "rgba(255,255,255,0.12)"),
        background: live ? (overdue ? "rgba(239,68,68,0.12)" : "rgba(79,124,255,0.10)") : "var(--card, #101827)",
      }}>
      <span aria-hidden="true">⏰</span>{text}
    </span>
  );
}

// Bottom sheet for a deal's local reminder. Mirrors desktop PIReminderModal
// semantics: save / snooze +1d / dismiss / "Mark handled" (records an operator
// handoff only — it NEVER texts anyone and never touches GHL).
function MPReminderSheet({ card, reminder, onClose, onDone }) {
  const dealId = MPdealId(card);
  const st = MPremStatus(reminder);
  const live = !!reminder && (st === "pending" || st === "snoozed");
  const [due, setDue] = useStateMP(MPtoLocalInput(MPasMs(reminder && reminder.dueAt)));
  const [draft, setDraft] = useStateMP((reminder && reminder.draftMsg) || "");
  const [rbusy, setRbusy] = useStateMP(false);
  const [errMsg, setErrMsg] = useStateMP(null);

  async function act(path, body, okText) {
    if (rbusy) return;
    setRbusy(true); setErrMsg(null);
    try {
      await window.apiPostM(path, { dealId, ...body });
      onDone(okText);            // parent refreshes reminders + closes this sheet
    } catch (e) {
      setErrMsg(e.message || "Request failed");
      setRbusy(false);
    }
  }

  function save() {
    const ms = new Date(due).getTime();
    if (!Number.isFinite(ms)) { setErrMsg("Pick a valid date and time."); return; }
    act("/api/toolkit/pipeline/reminder/set", {
      dueAt: ms, draftMsg: draft,
      deal: { name: card && card.name, address: card && card.address, updatedAt: card && (card.updatedAt != null ? card.updatedAt : card.updated) },
    }, "Reminder saved · local only");
  }

  function snooze() {
    act("/api/toolkit/pipeline/reminder/snooze", { untilMs: Date.now() + 86400000 }, "Snoozed 24h");
  }

  function markHandled() {
    if (!window.confirm("Mark this reminder handled? This only records your handoff — it never sends an SMS, email, or GHL update.")) return;
    act("/api/toolkit/pipeline/reminder/send", {}, "Marked handled · nothing was sent");
  }

  function dismiss() {
    if (!window.confirm("Dismiss this local reminder? You can set a new one later.")) return;
    act("/api/toolkit/pipeline/reminder/dismiss", {}, "Reminder dismissed");
  }

  return (
    <div className="m-sheet" style={{ zIndex: 60 }}>
      <div className="m-sheet-head">
        <button onClick={() => { if (!rbusy) onClose(); }} aria-label="Close"
          style={{ background: "none", border: "none", color: "var(--text-3, #64748B)", minWidth: 44, minHeight: 44, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", padding: 0 }}>
          <window.MIcons.X size={22} />
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: "-0.3px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {(card && card.name) || "Deal"}
          </div>
          <div className="m-fade" style={{ marginTop: 1 }}>
            {live
              ? (st === "snoozed" ? "Snoozed · back " + MPdueText(reminder.snoozedUntil || reminder.dueAt) : "Due " + MPdueText(reminder.dueAt))
              : "New follow-up reminder"}
          </div>
        </div>
      </div>
      <div className="m-sheet-body">
        <div style={{ padding: "9px 12px", borderRadius: 11, fontSize: 12, background: "rgba(79,124,255,0.08)", border: "1px solid rgba(79,124,255,0.25)", color: "var(--text-2, #9FB0C7)" }}>
          Local reminder only — nothing here texts the seller or touches GoHighLevel.
        </div>
        <label className="m-fade" style={{ display: "block", fontWeight: 700, letterSpacing: "0.4px" }}>
          DUE
          <input type="datetime-local" className="m-input" value={due}
            onChange={(e) => setDue(e.target.value)} style={{ marginTop: 6 }} />
        </label>
        <label className="m-fade" style={{ display: "block", fontWeight: 700, letterSpacing: "0.4px" }}>
          DRAFT MESSAGE
          <textarea className="m-input" rows={4} value={draft} placeholder="What should the operator follow up on?"
            onChange={(e) => setDraft(e.target.value)} style={{ marginTop: 6 }} />
        </label>
        {errMsg && (
          <div style={{ padding: "9px 12px", borderRadius: 11, fontSize: 12.5, fontWeight: 600, color: MP_RED, background: "rgba(239,68,68,0.10)", border: "1px solid rgba(239,68,68,0.4)" }}>
            {errMsg}
          </div>
        )}
        {live && (
          <React.Fragment>
            <div className="m-fade" style={{ fontWeight: 700, letterSpacing: "0.4px", marginTop: 4 }}>REMINDER ACTIONS</div>
            <button className="m-btn ghost" disabled={rbusy} onClick={snooze}>Snooze +1d</button>
            <button className="m-btn ghost" disabled={rbusy} onClick={markHandled} style={{ color: MP_GREEN }}>Mark handled · records handoff, never texts</button>
            <button className="m-btn no" disabled={rbusy} onClick={dismiss}>Dismiss reminder</button>
          </React.Fragment>
        )}
      </div>
      <div className="m-sheet-foot" style={{ display: "flex", gap: 8 }}>
        <window.MBtn kind="ghost" onClick={() => { if (!rbusy) onClose(); }} disabled={rbusy} style={{ flex: 1 }}>Cancel</window.MBtn>
        <window.MBtn onClick={save} disabled={rbusy} style={{ flex: 1.4 }}>{rbusy ? "Saving…" : "Save reminder"}</window.MBtn>
      </div>
    </div>
  );
}

function MPipelinePage() {
  const { data, error, loading, refresh } = window.useApiM("/api/pipeline", { interval: 30000 });
  const [idx, setIdx] = useStateMP(0);
  const [local, setLocal] = useStateMP(null);   // optimistic copy of pipelines
  const [sheet, setSheet] = useStateMP(null);   // {card, fromStageId}
  const [flash, setFlash] = useStateMP(null);   // {kind:"ok"|"err", msg}
  const [busy, setBusy] = useStateMP(false);    // move POST in flight
  const pendingMP = useRefMP(0);                // in-flight move count
  const [rems, setRems] = useStateMP([]);       // Phase 3 overlay: local follow-up reminders
  const [remSheet, setRemSheet] = useStateMP(null); // {card} -> reminder bottom sheet

  // Phase 3 overlay: fetch local reminders on mount + after every mutation.
  // Read-only w.r.t. GHL — reminders live only in the connector's local store.
  async function loadReminders() {
    try {
      const r = await fetch("/api/toolkit/pipeline/reminders");
      const j = await r.json();
      setRems((j && j.reminders) || []);
    } catch (e) { /* keep last known reminders */ }
  }
  useEffectMP(() => { loadReminders(); }, []);

  const remByDeal = useMemoMP(() => {
    const map = {};
    for (const r of rems || []) map[String(r.dealId)] = r;
    return map;
  }, [rems]);

  // Adopt fresh server data, but never clobber an optimistic move mid-flight.
  useEffectMP(() => {
    if (data && data.pipelines && pendingMP.current === 0) setLocal(data.pipelines);
  }, [data]);

  // Auto-clear the flash banner.
  useEffectMP(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 3200);
    return () => clearTimeout(t);
  }, [flash]);

  const pls = local || (data && data.pipelines) || [];
  const safeIdx = Math.min(idx, Math.max(0, pls.length - 1));
  const active = pls[safeIdx];

  const kpis = useMemoMP(() => {
    if (!active) return null;
    let hot = null;
    for (const s of active.stages || []) if (!hot || s.count > hot.count) hot = s;
    return {
      deals: active.totalDeals || 0,
      value: active.totalValue || 0,
      hotName: hot ? hot.name : "—",
      hotCount: hot ? hot.count : 0,
    };
  }, [active]);

  // Mirror of the desktop optimistic move: splice the card into its new stage
  // and recompute counts/values so the board updates instantly.
  function applyMove(oppId, toStageId) {
    setLocal((prev) => {
      const base = prev || (data && data.pipelines) || [];
      const next = base.map((p) => ({
        ...p, stages: (p.stages || []).map((s) => ({ ...s, cards: (s.cards || []).slice() })),
      }));
      const p = next[safeIdx];
      if (!p) return prev;
      let moved = null;
      for (const s of p.stages) {
        const i = s.cards.findIndex((c) => c.id === oppId);
        if (i >= 0) { moved = s.cards.splice(i, 1)[0]; break; }
      }
      const dest = p.stages.find((s) => s.id === toStageId);
      if (!moved || !dest) return prev;
      dest.cards.push({ ...moved, stageId: toStageId });
      p.stages.forEach((s) => {
        s.count = s.cards.length;
        s.value = s.cards.reduce((a, c) => a + (c.value || 0), 0);
      });
      p.totalDeals = p.stages.reduce((a, s) => a + s.count, 0);
      p.totalValue = p.stages.reduce((a, s) => a + s.value, 0);
      return next;
    });
  }

  async function moveTo(toStageId) {
    const sh = sheet;
    if (!sh || busy) return;
    if (sh.fromStageId === toStageId) { setSheet(null); return; }
    const snapshot = local;            // revert target if the GHL write fails
    setBusy(true);
    applyMove(sh.card.id, toStageId);
    pendingMP.current += 1;
    try {
      // Exact same POST body the desktop drag-drop sends.
      await window.apiPostM("/api/pipeline/move", {
        id: sh.card.id,
        stageId: toStageId,
        pipelineId: active && active.id,
      });
      setFlash({ kind: "ok", msg: "Moved · synced to GoHighLevel" });
      setSheet(null);
    } catch (e) {
      setLocal(snapshot);              // undo optimistic move
      setFlash({ kind: "err", msg: "Move failed — " + (e.message || "GHL error") + ". Reverted." });
    } finally {
      setBusy(false);
      pendingMP.current -= 1;
      if (pendingMP.current === 0) { refresh(); loadReminders(); }   // re-pull truth from GHL + local overlay
    }
  }

  const sheetStageName = sheet && active
    ? (((active.stages || []).find((s) => s.id === sheet.fromStageId) || {}).name || "—")
    : "";

  return (
    <React.Fragment>
      <window.MHeader
        title="Pipeline"
        sub={active
          ? `${active.totalDeals} deals · ${window.fmtMoneyM(active.totalValue)} · tap a card to move it`
          : (loading ? "Loading opportunities…" : "GoHighLevel pipeline")}
        right={
          <button onClick={refresh} aria-label="Refresh"
            style={{ background: "none", border: "none", color: "var(--text-3, #64748B)", minWidth: 44, minHeight: 44, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", padding: 0 }}>
            <window.MIcons.Refresh size={20} />
          </button>
        }
      />

      <div className="m-content">
        {flash && (
          <div style={{
            padding: "10px 13px", borderRadius: 12, fontSize: 13, fontWeight: 600,
            display: "flex", alignItems: "center", gap: 8,
            border: "1px solid " + (flash.kind === "ok" ? "rgba(34,197,94,0.4)" : "rgba(239,68,68,0.4)"),
            background: flash.kind === "ok" ? "rgba(34,197,94,0.10)" : "rgba(239,68,68,0.10)",
            color: flash.kind === "ok" ? "#22C55E" : "#EF4444",
          }}>
            {flash.kind === "ok" ? <window.MIcons.Check size={15} /> : <window.MIcons.X size={15} />}
            <span style={{ flex: 1, minWidth: 0 }}>{flash.msg}</span>
          </div>
        )}

        {error && pls.length === 0 && !loading && (
          <div className="m-card" style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "flex-start" }}>
            <div className="m-fade" style={{ color: "#EF4444", fontSize: 13 }}>Couldn't load the pipeline — {String(error)}</div>
            <window.MBtn kind="ghost" onClick={refresh}>Retry</window.MBtn>
          </div>
        )}

        {loading && pls.length === 0 && !error && window.MSpin()}

        {!loading && !error && pls.length === 0 && (
          <window.MEmpty title="No pipelines" sub="No GoHighLevel pipelines found for this location." />
        )}

        {error && pls.length > 0 && (
          <div className="m-fade" style={{ color: "#EF4444" }}>Sync error — showing last known board. Pull refresh above.</div>
        )}

        {pls.length > 1 && (
          <div className="m-seg">
            {pls.map((p, i) => (
              <window.MChip key={p.id} active={i === safeIdx} onClick={() => setIdx(i)}>{p.name}</window.MChip>
            ))}
          </div>
        )}

        {kpis && (
          <div className="m-card" style={{ display: "flex", padding: "6px 4px" }}>
            <div className="m-kpi">
              <div className="v">{kpis.deals}</div>
              <div className="l">DEALS</div>
            </div>
            <div className="m-kpi">
              <div className="v">{window.fmtMoneyM(kpis.value)}</div>
              <div className="l">PIPELINE VALUE</div>
            </div>
            <div className="m-kpi">
              <div className="v">{kpis.hotCount}</div>
              <div className="l" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {String(kpis.hotName || "—").toUpperCase()}
              </div>
            </div>
          </div>
        )}

        {active && (
          <div className="m-hscroll" style={{ alignItems: "flex-start" }}>
            {(active.stages || []).map((s, i) => {
              const accent = MP_ACCENTS[i % MP_ACCENTS.length];
              return (
                <div key={s.id} className="m-col">
                  <div className="m-card" style={{ borderTop: "3px solid " + accent, display: "flex", flexDirection: "column", gap: 8 }}>
                    <div className="m-row">
                      <div style={{ fontSize: 13.5, fontWeight: 800, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</div>
                      <span style={{ fontSize: 12.5, fontWeight: 800, color: accent, flexShrink: 0 }}>{s.count}</span>
                    </div>
                    <div className="m-fade" style={{ color: "#22C55E", fontWeight: 600 }}>
                      {s.value > 0 ? window.fmtMoneyM(s.value) : "—"}
                    </div>
                    {(s.cards || []).length === 0 && (
                      <div className="m-fade" style={{ textAlign: "center", padding: "18px 0" }}>No deals in this stage</div>
                    )}
                    {(s.cards || []).map((c) => {
                      const crem = remByDeal[MPdealId(c)];
                      return (
                        <button key={c.id} className="m-list-item"
                          onClick={() => setSheet({ card: c, fromStageId: s.id })}
                          style={{ width: "100%", boxSizing: "border-box", textAlign: "left", cursor: "pointer", color: "inherit", fontFamily: "inherit", minHeight: 44, background: "var(--card-2, #17203a)" }}>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                              <div style={{ flex: 1, minWidth: 0, fontSize: 13.5, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</div>
                              <MPDaysBadge deal={c} />
                            </div>
                            {c.updated && <div className="m-fade" style={{ marginTop: 2 }}>updated {window.timeAgoM(c.updated)}</div>}
                            <div style={{ marginTop: 6 }}>
                              <MPReminderChip reminder={crem} onOpen={() => setRemSheet({ card: c })} />
                            </div>
                          </div>
                          {c.value > 0 && (
                            <span style={{ fontSize: 12.5, fontWeight: 800, color: "#22C55E", flexShrink: 0 }}>{window.fmtMoneyM(c.value)}</span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {sheet && active && (
        <div className="m-sheet">
          <div className="m-sheet-head">
            <button onClick={() => { if (!busy) setSheet(null); }} aria-label="Close"
              style={{ background: "none", border: "none", color: "var(--text-3, #64748B)", minWidth: 44, minHeight: 44, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", padding: 0 }}>
              <window.MIcons.X size={22} />
            </button>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: "-0.3px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {sheet.card.name}
              </div>
              <div className="m-fade" style={{ marginTop: 1 }}>
                {(sheet.card.value > 0 ? window.fmtMoneyM(sheet.card.value) + " · " : "") + (busy ? "Moving…" : "now in " + sheetStageName)}
              </div>
            </div>
          </div>
          <div className="m-sheet-body">
            <div className="m-fade" style={{ fontWeight: 700, letterSpacing: "0.4px" }}>MOVE TO STAGE</div>
            {(active.stages || []).map((s, i) => {
              const cur = s.id === sheet.fromStageId;
              return (
                <button key={s.id} className="m-btn ghost" disabled={busy || cur} onClick={() => moveTo(s.id)}
                  style={{ display: "flex", alignItems: "center", gap: 10, minHeight: 54, textAlign: "left", borderLeft: "3px solid " + MP_ACCENTS[i % MP_ACCENTS.length] }}>
                  <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
                  {cur
                    ? <window.MIcons.Check size={18} />
                    : <span className="m-fade" style={{ flexShrink: 0 }}>{s.count}</span>}
                </button>
              );
            })}
          </div>
          <div className="m-sheet-foot">
            <window.MBtn kind="no" onClick={() => setSheet(null)} disabled={busy} style={{ width: "100%" }}>Cancel</window.MBtn>
          </div>
        </div>
      )}

      {remSheet && (
        <MPReminderSheet
          card={remSheet.card}
          reminder={remByDeal[MPdealId(remSheet.card)] || null}
          onClose={() => setRemSheet(null)}
          onDone={(msg) => { setRemSheet(null); setFlash({ kind: "ok", msg }); loadReminders(); }}
        />
      )}
    </React.Fragment>
  );
}

Object.assign(window, { MPipelinePage });
