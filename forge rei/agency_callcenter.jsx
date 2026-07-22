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
