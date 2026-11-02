// FORGE Mobile — Crew > Tasks: open tasks per agent, file a task, mark one done or dismissed.
// Same pattern as the Bus view in m_agents.jsx (a card the crew page swaps in).
// A task is an assignment, never an outward action (agents_hub.send_task); nothing here sends or spends.
// Hook aliases for this file: MT. Exports: MATasksCard.
//
// Endpoints:
//   GET  /api/hub/tasks                  -> {tasks:[{id,agentId,agentName,title,note,status,createdAt,result?,error?}]}
//   POST /api/hub/task        {agentId,title,note,business?}
//   POST /api/hub/task/update {id,status: open|done|dismissed|failed}
const { useState: useStateMT } = React;

const MT_LABEL = { open: "Open", done: "Done", dismissed: "Dismissed", failed: "Failed" };
const MT_COLOR = { open: "#4F7CFF", done: "#22C55E", dismissed: "#64748B", failed: "#EF4444" };
const MT_RECENT = 12;   // closed tasks kept in view; the open ones are always all shown

function MTRow(props) {
  const t = props.t;
  const [open, setOpen] = useStateMT(false);
  const st = MT_LABEL[t.status] ? t.status : "open";
  const first = String(t.result || "").trim().split("\n")[0];
  return (
    <div className="m-list-item" style={{ display: "block", padding: 0 }}>
      <button type="button" onClick={() => setOpen(!open)}
        style={{ all: "unset", boxSizing: "border-box", display: "block", width: "100%", minHeight: 44,
          padding: "10px 12px", cursor: "pointer" }}>
        <div className="m-row" style={{ gap: 6, marginBottom: 3 }}>
          <span style={{ fontSize: 12, fontWeight: 800 }}>{t.agentName || t.agentId}</span>
          <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 8px", borderRadius: 999,
            color: MT_COLOR[st], border: "1px solid " + MT_COLOR[st] }}>{MT_LABEL[st]}</span>
          <span className="m-fade" style={{ marginLeft: "auto", fontSize: 11, flexShrink: 0 }}>
            {window.timeAgoM(t.createdAt)}
          </span>
        </div>
        <div style={{ fontSize: 13.5, lineHeight: 1.35, wordBreak: "break-word", fontWeight: 600 }}>{t.title}</div>
        {!open && st === "done" && first && (
          <div className="m-fade" style={{ marginTop: 3, overflow: "hidden", textOverflow: "ellipsis",
            whiteSpace: "nowrap" }}>Result: {first}</div>
        )}
        {!open && st === "failed" && t.error && (
          <div style={{ marginTop: 3, fontSize: 12, color: "var(--red, #EF4444)" }}>{String(t.error).slice(0, 120)}</div>
        )}
      </button>
      {open && (
        <div style={{ padding: "0 12px 12px", fontSize: 13, lineHeight: 1.4 }}>
          {t.note && <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", marginBottom: 8 }}>{t.note}</div>}
          {st === "done" && (t.result
            ? <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", marginBottom: 8, padding: "8px 10px",
                borderRadius: 10, background: "var(--card-2, #17203a)" }}>
                <div className="m-fade" style={{ marginBottom: 3 }}>Result</div>{t.result}
              </div>
            : <div className="m-fade" style={{ marginBottom: 8 }}>Marked done. No result was saved.</div>)}
          {st === "failed" && t.error && (
            <div style={{ marginBottom: 8, color: "var(--red, #EF4444)", wordBreak: "break-word" }}>{t.error}</div>
          )}
          <div className="m-row" style={{ gap: 8, flexWrap: "wrap" }}>
            {st === "open" ? (
              <React.Fragment>
                <button className="m-btn" style={{ minHeight: 44, flex: 1 }} disabled={props.busy}
                  onClick={() => props.onSet(t, "done")}>Mark done</button>
                <button className="m-btn ghost" style={{ minHeight: 44, flex: 1 }} disabled={props.busy}
                  onClick={() => props.onSet(t, "dismissed")}>Dismiss</button>
              </React.Fragment>
            ) : (
              <button className="m-btn ghost" style={{ minHeight: 44, flex: 1 }} disabled={props.busy}
                onClick={() => props.onSet(t, "open")}>Reopen</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// props.agents = this crew's agents [{id,name,business}], props.business = the portal id or undefined.
function MATasksCard(props) {
  const agents = props.agents || [];
  const ids = agents.map((a) => a.id);
  const tasks = window.useApiM("/api/hub/tasks");
  const [pick, setPick] = useStateMT("");
  const [title, setTitle] = useStateMT("");
  const [note, setNote] = useStateMT("");
  const [busy, setBusy] = useStateMT(false);
  const [err, setErr] = useStateMT("");
  const target = ids.includes(pick) ? pick : ids[0];
  const mine = ((tasks.data && tasks.data.tasks) || []).filter((t) => t && ids.includes(t.agentId));
  const openRows = mine.filter((t) => t.status === "open");
  const closedRows = mine.filter((t) => t.status !== "open").slice(0, MT_RECENT);

  async function file() {
    const a = agents.find((x) => x.id === target);
    if (!a || !title.trim() || busy) return;
    setBusy(true); setErr("");
    try {
      // Orion works across businesses, so a portal's workspace guard would refuse him; everyone else carries it.
      const body = { agentId: a.id, title: title.trim(), note: note.trim() };
      if (props.business && a.business !== "cross") body.business = props.business;
      await window.apiPostM("/api/hub/task", body);
      setTitle(""); setNote("");
      tasks.refresh();
    } catch (e) {
      setErr("Couldn't file the task (" + ((e && e.message) || "connection error") + "). Your text is still here.");
    }
    setBusy(false);
  }

  async function setStatus(t, status) {
    if (busy) return;
    setBusy(true); setErr("");
    try {
      await window.apiPostM("/api/hub/task/update", { id: t.id, status });
      tasks.refresh();
    } catch (e) {
      setErr("Couldn't update the task (" + ((e && e.message) || "connection error") + ").");
    }
    setBusy(false);
  }

  return (
    <window.MCard title="Tasks"
      right={<button className="m-chip" style={{ minHeight: 44, display: "flex", alignItems: "center", gap: 5 }}
        onClick={tasks.refresh}><window.MIcons.Refresh size={14} /> Refresh</button>}>
      <div className="m-fade" style={{ marginBottom: 10 }}>
        Work you gave the crew. An agent picks up open tasks on its next run.
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
        <select className="m-input" style={{ minHeight: 44 }} value={target || ""} onChange={(e) => setPick(e.target.value)}
          aria-label="Agent">
          {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <input className="m-input" style={{ minHeight: 44 }} value={title} placeholder="What should they do?"
          maxLength={200} onChange={(e) => setTitle(e.target.value)} />
        <textarea className="m-input" rows={2} value={note} placeholder="Details (optional)"
          style={{ minHeight: 60 }} onChange={(e) => setNote(e.target.value)} />
        <button className="m-btn" style={{ minHeight: 44 }} disabled={busy || !title.trim() || !target} onClick={file}>
          {busy ? "Working…" : "File task"}
        </button>
      </div>

      {err && (
        <div role="alert" style={{ padding: "10px 12px", borderRadius: 12, marginBottom: 10,
          background: "rgba(239,68,68,0.10)", border: "1px solid rgba(239,68,68,0.3)",
          color: "var(--red, #EF4444)", fontSize: 12.5 }}>{err}</div>
      )}
      {tasks.error && !tasks.data && (
        <div className="m-fade" style={{ marginBottom: 10 }}>Couldn't load tasks: {String(tasks.error)}</div>
      )}
      {tasks.loading && !tasks.data && <window.MSpin />}
      {!tasks.loading && !tasks.error && !mine.length && (
        <window.MEmpty title="No tasks yet" sub="File one above and it shows up here." />
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {openRows.length > 0 && <div className="m-fade" style={{ fontWeight: 700 }}>Open ({openRows.length})</div>}
        {openRows.map((t) => <MTRow key={t.id} t={t} busy={busy} onSet={setStatus} />)}
        {closedRows.length > 0 && <div className="m-fade" style={{ fontWeight: 700, marginTop: 6 }}>Recent</div>}
        {closedRows.map((t) => <MTRow key={t.id} t={t} busy={busy} onSet={setStatus} />)}
      </div>
    </window.MCard>
  );
}

Object.assign(window, { MATasksCard });
