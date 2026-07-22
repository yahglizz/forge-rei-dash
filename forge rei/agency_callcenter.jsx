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
  new: "New", answered: "Answered", no_answer: "No answer",
  callback: "Call back", dead: "Move on",
};
const CC_STATUS_STYLE = {
  answered: { color: "#81c995", background: "rgba(129,201,149,.12)" },
  callback: { color: "#f6c979", background: "rgba(244,184,96,.12)" },
  no_answer: { color: "#8ab4f8", background: "rgba(138,180,248,.12)" },
  dead: { color: "#f28b82", background: "rgba(242,139,130,.12)" },
  new: { opacity: 0.7, background: "rgba(255,255,255,.06)" },
};
const CC_FILTERS = [
  ["all", "All"], ["new", "New"], ["answered", "Answered"],
  ["no_answer", "No answer"], ["callback", "Call back"], ["dead", "Move on"],
];

function CcStatusPill({ status }) {
  return (
    <span style={Object.assign({ borderRadius: 99, padding: "3px 9px", fontSize: 11, fontWeight: 600 }, CC_STATUS_STYLE[status] || CC_STATUS_STYLE.new)}>
      {CC_STATUS_LABEL[status] || status}
    </span>
  );
}

function CcRow({ lead, busy, onMark, onNote, onDelete }) {
  return (
    <tr>
      <td>
        <div style={{ fontWeight: 600 }}>{lead.name || lead.company || "(no name)"}</div>
        {((lead.name && lead.company) || lead.location) && (
          <div className="faint" style={{ fontSize: 11.5 }}>
            {[lead.name ? lead.company : "", lead.location].filter(Boolean).join(" · ")}
          </div>
        )}
      </td>
      <td>
        {lead.phone ? (
          <a href={"tel:" + lead.phone} className="mono" style={{ color: "inherit", textDecoration: "underline dotted" }}>
            {lead.phone}
          </a>
        ) : <span className="faint">—</span>}
        {lead.last_called && <div className="faint" style={{ fontSize: 11 }}>last: {lead.last_called}</div>}
      </td>
      <td>{lead.email || <span className="faint">—</span>}</td>
      <td><CcStatusPill status={lead.status} /></td>
      <td>
        <input
          defaultValue={lead.note}
          onBlur={(e) => onNote(lead.id, e.target.value)}
          placeholder="note…"
          style={{ width: 140, fontSize: 12, background: "transparent", border: "none", borderBottom: "1px solid rgba(255,255,255,.12)", color: "inherit" }}
        />
      </td>
      <td>
        <div style={{ display: "flex", gap: 4 }}>
          <button title="Answered" disabled={busy} onClick={() => onMark(lead.id, "answered")} style={{ cursor: busy ? "default" : "pointer" }}>✅</button>
          <button title="No answer" disabled={busy} onClick={() => onMark(lead.id, "no_answer")} style={{ cursor: busy ? "default" : "pointer" }}>📵</button>
          <button title="Call back later" disabled={busy} onClick={() => onMark(lead.id, "callback")} style={{ cursor: busy ? "default" : "pointer" }}>⏰</button>
          <button title="Move on" disabled={busy} onClick={() => onMark(lead.id, "dead")} style={{ cursor: busy ? "default" : "pointer" }}>⛔</button>
          <button title="Remove" className="faint" disabled={busy} onClick={() => onDelete(lead.id)} style={{ background: "none", border: "none", cursor: busy ? "default" : "pointer" }}>×</button>
        </div>
      </td>
    </tr>
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

  async function saveNote(id, note) {
    setSheetBusy(true);
    try {
      await window.apiPost("/api/agency/callsheet/note", { id, note });
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
    if (!window.confirm("Remove all 'move on' businesses from the sheet?")) return;
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
              🧹 Clear move-ons
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
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search business, phone…"
              style={{ fontSize: 12.5, flex: "1 1 200px", minWidth: 160 }}
            />
            {CC_FILTERS.map(([key, label]) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                style={{
                  fontSize: 11.5, padding: "4px 10px", borderRadius: 99, cursor: "pointer",
                  background: filter === key ? "rgba(255,255,255,.14)" : "rgba(255,255,255,.05)",
                  border: "1px solid rgba(255,255,255,.1)",
                }}
              >
                {label} {counts[key] !== undefined ? "(" + (key === "all" ? counts.total || 0 : counts[key] || 0) + ")" : ""}
              </button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <div className="faint" style={{ fontSize: 12.5 }}>No businesses match.</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="lead-table">
                <thead>
                  <tr>
                    <th>Business</th>
                    <th>Phone</th>
                    <th>Email</th>
                    <th>Status</th>
                    <th>Note</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((lead) => (
                    <CcRow key={lead.id} lead={lead} busy={sheetBusy} onMark={mark} onNote={saveNote} onDelete={removeLead} />
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
