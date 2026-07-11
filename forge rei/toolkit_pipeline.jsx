// Wholesaler Toolkit — Pipeline Organizer UI (Phase 3).
//
// This is a read-only rendering of the live GHL kanban plus a local reminder
// overlay. It deliberately has no stage-move controls and never sends to GHL.
const { useState: useStatePI, useEffect: useEffectPI, useMemo: useMemoPI } = React;

const PI_GREEN = "#22C55E", PI_YELLOW = "#F59E0B", PI_RED = "#EF4444";
const PI_BLUE = "#4F7CFF", PI_FAINT = "#64748B";
const PI_INPUT = {
  background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 8,
  padding: "9px 10px", color: "var(--text)", fontSize: 13, fontFamily: "inherit", width: "100%",
};

function PIdealId(deal) {
  return String((deal && (deal.contactId || deal.dealId || deal.id)) || "");
}

function PIasMs(value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  if (Number.isFinite(n) && n > 0) return n < 20000000000 ? n * 1000 : n;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

function PIpad(value) { return String(value).padStart(2, "0"); }

function PIinputDate(value) {
  const d = value ? new Date(value) : new Date(Date.now() + 86400000);
  return d.getFullYear() + "-" + PIpad(d.getMonth() + 1) + "-" + PIpad(d.getDate());
}

function PIinputTime(value) {
  const d = value ? new Date(value) : new Date(Date.now() + 86400000);
  return PIpad(d.getHours()) + ":" + PIpad(d.getMinutes());
}

function PIdueText(value) {
  const ms = PIasMs(value);
  return ms ? new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "No due time";
}

function PIdaysMeta(deal) {
  const updated = PIasMs(deal && (deal.updatedAt != null ? deal.updatedAt : deal.updated));
  if (!updated) return { days: null, color: PI_FAINT, label: "date unavailable" };
  const days = Math.max(0, Math.ceil((Date.now() - updated) / 86400000));
  if (days < 3) return { days, color: PI_GREEN, label: "fresh" };
  if (days <= 7) return { days, color: PI_YELLOW, label: "watch" };
  return { days, color: PI_RED, label: "stale" };
}

function PIDaysInStageBadge({ deal }) {
  const meta = PIdaysMeta(deal);
  return (
    <span title={meta.label} className="pill" style={{ color: meta.color, background: meta.color + "1d", border: "1px solid " + meta.color + "42", fontSize: 10.5, whiteSpace: "nowrap" }}>
      {meta.days == null ? "—" : meta.days + "d"}
    </span>
  );
}

function PIReminderStatus({ reminder }) {
  const value = String((reminder && reminder.status) || "pending").toLowerCase();
  const color = value === "sent" ? PI_GREEN : value === "dismissed" ? PI_FAINT : value === "snoozed" ? PI_YELLOW : PI_BLUE;
  const label = value === "sent" ? "handed off" : value;
  return <span className="pill" style={{ color, background: color + "1d", border: "1px solid " + color + "3a", fontSize: 10.5 }}>{label}</span>;
}

function PIReminderModal({ deal, reminder, onClose, onChanged }) {
  const Icons = window.Icons;
  const [date, setDate] = useStatePI(PIinputDate(reminder && reminder.dueAt));
  const [time, setTime] = useStatePI(PIinputTime(reminder && reminder.dueAt));
  const [draft, setDraft] = useStatePI((reminder && reminder.draftMsg) || "");
  const [note, setNote] = useStatePI((reminder && reminder.note) || "");
  const [busy, setBusy] = useStatePI(false);
  const [message, setMessage] = useStatePI(null);
  const dealId = PIdealId(deal);

  useEffectPI(() => {
    setDate(PIinputDate(reminder && reminder.dueAt));
    setTime(PIinputTime(reminder && reminder.dueAt));
    setDraft((reminder && reminder.draftMsg) || "");
    setNote((reminder && reminder.note) || "");
    setMessage(null);
  }, [dealId, reminder && reminder.dueAt, reminder && reminder.draftMsg, reminder && reminder.note]);

  async function act(path, body, success) {
    setBusy(true); setMessage(null);
    try {
      const result = await window.apiPost(path, { dealId, ...body });
      onChanged && onChanged(result);
      setMessage({ ok: true, text: success });
    } catch (err) {
      setMessage({ ok: false, text: err.message || String(err) });
    } finally { setBusy(false); }
  }

  function save() {
    const dueAt = new Date(date + "T" + time).getTime();
    if (!Number.isFinite(dueAt)) { setMessage({ ok: false, text: "Set a valid date and time." }); return; }
    act("/api/toolkit/pipeline/reminder/set", {
      dueAt, draftMsg: draft,
      deal: { name: deal && deal.name, address: deal && deal.address, updatedAt: deal && (deal.updatedAt || deal.updated) },
    }, "Reminder saved locally.");
  }

  function saveNote() {
    act("/api/toolkit/pipeline/reminder/update", { draftMsg: draft, note }, "Draft and note updated.");
  }

  function snooze() {
    act("/api/toolkit/pipeline/reminder/snooze", { untilMs: Date.now() + 86400000 }, "Snoozed for 24 hours.");
  }

  function handoff() {
    if (!window.confirm("Mark this reminder as handed to the operator? This does not send an SMS, email, or GHL update.")) return;
    act("/api/toolkit/pipeline/reminder/send", {}, "Marked as handed off. No message was sent.");
  }

  function dismiss() {
    if (!window.confirm("Dismiss this local reminder? You can create a new one later.")) return;
    act("/api/toolkit/pipeline/reminder/dismiss", {}, "Reminder dismissed.");
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 70, background: "rgba(3,8,18,0.72)", display: "grid", placeItems: "center", padding: 16 }}>
      <div onClick={(event) => event.stopPropagation()} className="card" style={{ width: 560, maxWidth: "100%", maxHeight: "92vh", overflowY: "auto", padding: 20 }}>
        <div style={{ display: "flex", gap: 12, justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ minWidth: 0 }}>
            <div className="faint" style={{ fontSize: 11, letterSpacing: 0.5, textTransform: "uppercase" }}>Follow-up reminder</div>
            <h2 style={{ fontSize: 19, marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{(deal && deal.name) || "Deal"}</h2>
            <div className="faint" style={{ fontSize: 12, marginTop: 3 }}>{(deal && deal.address) || "Local overlay · no GHL changes"}</div>
          </div>
          <button className="tab" onClick={onClose} aria-label="Close reminder"><Icons.Chevron size={17} style={{ transform: "rotate(180deg)" }} /></button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 10, marginTop: 18 }}>
          <label className="faint" style={{ fontSize: 11.5 }}>Due date<input type="date" value={date} onChange={(event) => setDate(event.target.value)} style={{ ...PI_INPUT, marginTop: 5 }} /></label>
          <label className="faint" style={{ fontSize: 11.5 }}>Due time<input type="time" value={time} onChange={(event) => setTime(event.target.value)} style={{ ...PI_INPUT, marginTop: 5 }} /></label>
        </div>
        <label className="faint" style={{ display: "block", fontSize: 11.5, marginTop: 13 }}>Draft message<textarea rows={4} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="What should the operator follow up on?" style={{ ...PI_INPUT, resize: "vertical", lineHeight: 1.45, marginTop: 5 }} /></label>
        <label className="faint" style={{ display: "block", fontSize: 11.5, marginTop: 13 }}>Private note<textarea rows={2} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional context for the operator" style={{ ...PI_INPUT, resize: "vertical", lineHeight: 1.45, marginTop: 5 }} /></label>

        {reminder && <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12 }}><PIReminderStatus reminder={reminder} /><span className="faint" style={{ fontSize: 11.5 }}>Due {PIdueText(reminder.dueAt)}</span></div>}
        {message && <div style={{ marginTop: 13, padding: "9px 11px", borderRadius: 9, fontSize: 12.5, color: message.ok ? PI_GREEN : PI_RED, background: (message.ok ? PI_GREEN : PI_RED) + "14", border: "1px solid " + (message.ok ? PI_GREEN : PI_RED) + "38" }}>{message.text}</div>}

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <button className="tab active" onClick={save} disabled={busy} style={{ minHeight: 40 }}>{busy ? "Saving…" : "Save reminder"}</button>
          {reminder && <button className="tab" onClick={saveNote} disabled={busy} style={{ minHeight: 40 }}>Save draft/note</button>}
          {reminder && <button className="tab" onClick={snooze} disabled={busy} style={{ minHeight: 40 }}>Snooze 24h</button>}
          {reminder && <button className="tab" onClick={handoff} disabled={busy} style={{ minHeight: 40, color: PI_GREEN }}>Hand to operator</button>}
          {reminder && <button className="tab" onClick={dismiss} disabled={busy} style={{ minHeight: 40, color: PI_RED }}>Dismiss</button>}
        </div>
      </div>
    </div>
  );
}

function PIReminderList({ reminders, onOpen }) {
  const Icons = window.Icons;
  const rows = reminders || [];
  return (
    <div className="card" style={{ padding: 15, minWidth: 260, maxWidth: 340 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 10 }}><div style={{ fontWeight: 700, fontSize: 14, display: "flex", alignItems: "center", gap: 7 }}><Icons.Calendar size={15} /> Follow-ups</div><span className="tabnum faint" style={{ fontSize: 12 }}>{rows.length}</span></div>
      {!rows.length ? <div className="faint" style={{ fontSize: 12.5, lineHeight: 1.5, textAlign: "center" }}><img src="assets/empty-reminders.png" alt="Empty follow-up reminders illustration" style={{ width: "100%", maxWidth: 180, height: "auto", display: "block", margin: "0 auto 4px" }} />No local reminders. Open a deal card to set the next follow-up.</div> : <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        {rows.map((reminder) => <button key={reminder.dealId} onClick={() => onOpen(reminder)} style={{ textAlign: "left", padding: 10, border: "1px solid var(--border)", borderRadius: 10, background: "var(--card-2)", color: "var(--text)", cursor: "pointer", minHeight: 56 }}><div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}><div style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 600, fontSize: 12.5 }}>{reminder.dealName || reminder.dealId}</div><PIReminderStatus reminder={reminder} /></div><div className="faint" style={{ fontSize: 11, marginTop: 5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{PIdueText(reminder.dueAt)} · {reminder.draftMsg || "No draft"}</div></button>)}
      </div>}
    </div>
  );
}

function PIPipelineCard({ card, reminder, onOpen }) {
  const Icons = window.Icons;
  return (
    <button onClick={() => onOpen(card)} className="kcard" style={{ cursor: "pointer", width: "100%", textAlign: "left", color: "var(--text)", display: "flex", flexDirection: "column", gap: 7, minHeight: 108 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}><div style={{ fontWeight: 650, fontSize: 13, lineHeight: 1.3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{card.name || "Untitled deal"}</div><PIDaysInStageBadge deal={card} /></div>
      {card.value > 0 && <div className="tabnum" style={{ color: "var(--green)", fontWeight: 700, fontSize: 12.5 }}>{window.fmtMoney(card.value)}</div>}
      {card.phone && <div className="faint mono" style={{ fontSize: 10.5 }}>{card.phone}</div>}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 7, marginTop: "auto" }}><span className="faint" style={{ fontSize: 10.5, display: "inline-flex", gap: 5, alignItems: "center" }}><Icons.Calendar size={12} /> {reminder ? PIdueText(reminder.dueAt) : "Set follow-up"}</span>{reminder && <PIReminderStatus reminder={reminder} />}</div>
    </button>
  );
}

const PI_GUIDES = [
  { title: "Deal Calc", detail: "Price the opportunity", image: "assets/tutorial-calc.png", alt: "Deal Calculator tutorial illustration", page: "DealCalc" },
  { title: "Buyer Blast", detail: "Package buyer outreach", image: "assets/tutorial-blast.png", alt: "Buyer Blast tutorial illustration", page: "Blast" },
  { title: "Pipeline", detail: "Track the next follow-up", image: "assets/tutorial-pipeline.png", alt: "Deal Pipeline tutorial illustration", page: "Pipeline" },
  { title: "Contracts", detail: "Review sandbox e-sign", image: "assets/tutorial-contracts.png", alt: "Contracts tutorial illustration", page: "Contracts" },
];

function PIToolkitGuides() {
  return <div className="card card-pad"><div style={{ fontWeight: 700, fontSize: 14 }}>Toolkit guides</div><div className="faint" style={{ fontSize: 12, marginTop: 3 }}>A quick visual map of the four operator workflows.</div><div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginTop: 12 }}>{PI_GUIDES.map((guide) => <button key={guide.page} onClick={() => window.GoTo && window.GoTo(guide.page)} style={{ color: "var(--text)", textAlign: "left", border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden", background: "var(--card-2)", cursor: "pointer", padding: 0 }}><img src={guide.image} alt={guide.alt} style={{ width: "100%", height: "auto", display: "block", aspectRatio: "3 / 2", objectFit: "cover" }} /><span style={{ display: "block", padding: "9px 10px 2px", fontSize: 12.5, fontWeight: 650 }}>{guide.title}</span><span className="faint" style={{ display: "block", padding: "0 10px 10px", fontSize: 11 }}>{guide.detail}</span></button>)}</div></div>;
}

function PIPipelineHubPage() {
  const Icons = window.Icons;
  const { data, error, loading, refresh } = window.useApi("/api/pipeline", { interval: 30000 });
  const reminderApi = window.useApi("/api/toolkit/pipeline/reminders", { interval: 15000 });
  const [pipelineIndex, setPipelineIndex] = useStatePI(0);
  const [modalDeal, setModalDeal] = useStatePI(null);
  const pipelines = (data && data.pipelines) || [];
  const active = pipelines[Math.min(pipelineIndex, Math.max(0, pipelines.length - 1))];
  const reminders = (reminderApi.data && reminderApi.data.reminders) || [];
  const remindersByDeal = useMemoPI(() => Object.fromEntries(reminders.map((reminder) => [String(reminder.dealId), reminder])), [reminders]);

  useEffectPI(() => { if (pipelineIndex >= pipelines.length) setPipelineIndex(0); }, [pipelines.length, pipelineIndex]);

  function openReminder(dealOrReminder) {
    if (dealOrReminder && dealOrReminder.dealId && !dealOrReminder.id) {
      setModalDeal({ id: dealOrReminder.dealId, contactId: dealOrReminder.dealId, name: dealOrReminder.dealName, address: dealOrReminder.address });
    } else setModalDeal(dealOrReminder);
  }

  function changed() { reminderApi.refresh(); refresh(); }
  const selectedReminder = modalDeal && remindersByDeal[PIdealId(modalDeal)];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, minHeight: 0 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14, flexWrap: "wrap" }}>
        <div><h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Deal Pipeline</h1><p className="faint" style={{ fontSize: 13.5, marginTop: 4 }}>Live kanban, read-only · days in stage + local follow-up reminders</p></div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}><span className="pill" style={{ color: PI_BLUE, background: PI_BLUE + "18", border: "1px solid " + PI_BLUE + "35", fontSize: 10.5 }}>GHL read-only</span><button className="tab" onClick={changed} style={{ minHeight: 36, display: "inline-flex", alignItems: "center", gap: 6 }}><Icons.Activity size={13} /> Refresh</button></div>
      </div>
      <div style={{ padding: "10px 13px", borderRadius: 11, background: "rgba(79,124,255,0.08)", border: "1px solid rgba(79,124,255,0.25)", color: "var(--text-2)", fontSize: 12.5 }}>Reminders stay on this box only. “Hand to operator” records your review; it never sends an SMS, email, or changes a GHL stage.</div>
      {error && <window.ErrorRow error={error} onRetry={refresh} />}
      {reminderApi.error && <window.ErrorRow error={reminderApi.error} onRetry={reminderApi.refresh} />}
      {loading && !data && <window.LoadingRow label="Loading live pipeline…" />}
      {pipelines.length > 1 && <div className="tabs" style={{ alignSelf: "flex-start", maxWidth: "100%", overflowX: "auto" }}>{pipelines.map((pipeline, index) => <button key={pipeline.id} className={"tab" + (index === pipelineIndex ? " active" : "")} onClick={() => setPipelineIndex(index)}>{pipeline.name}</button>)}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(260px,320px)", gap: 16, minHeight: 0 }}>
        <div style={{ minWidth: 0 }}>
          {active ? <div className="kanban" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", alignItems: "start" }}>{active.stages.map((stage, index) => <div key={stage.id} className="kcol" style={{ "--col-accent": [PI_BLUE, "#8B5CF6", "#2DD4BF", PI_GREEN, PI_YELLOW, "#EC4899", PI_FAINT][index % 7], minHeight: 180 }}><div className="kcol-head"><span className="kcol-title">{stage.name}</span><span className="kcol-count tabnum">{stage.count}</span></div>{stage.value > 0 && <div className="faint" style={{ fontSize: 11, color: "var(--green)", margin: "-5px 0 7px" }}>{window.fmtMoney(stage.value)}</div>}{stage.cards.length ? stage.cards.map((card) => <PIPipelineCard key={card.id} card={card} reminder={remindersByDeal[PIdealId(card)]} onOpen={openReminder} />) : <div className="kempty">No deals</div>}</div>)}</div> : !loading && <div className="empty card"><img src="assets/empty-pipeline.png" alt="Empty deal pipeline illustration" style={{ width: "min(220px, 75vw)", height: "auto", opacity: 0.86 }} /><div style={{ fontWeight: 650, color: "var(--text)" }}>No deals in the live pipeline</div><div style={{ fontSize: 12.5 }}>When a deal appears, its card will show stage age and local reminder controls.</div></div>}
        </div>
        <PIReminderList reminders={reminders} onOpen={openReminder} />
      </div>
      <PIToolkitGuides />
      {modalDeal && <PIReminderModal deal={modalDeal} reminder={selectedReminder} onClose={() => setModalDeal(null)} onChanged={changed} />}
    </div>
  );
}

Object.assign(window, { PIPipelineHubPage, PIDaysInStageBadge, PIReminderModal, PIReminderList });
