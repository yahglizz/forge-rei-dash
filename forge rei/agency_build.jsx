// agency_build.jsx — Blueprint Studio (Forge AI Agency).
// Bring an idea (website / workflow / AI receptionist / anything). Fill a short intake,
// click one button, and Claude returns a build-ready BLUEPRINT: concept, how it works,
// the architecture/layout, the skills & tools required, an ordered build plan (each step
// owned by an agent), and a concrete test plan — plus the info still needed. Then hand it
// off to the building agent. Execution/testing stays approval-gated (propose-only).
//
// Static-React: hooks aliased (…Bld), every top-level name prefixed Bld, page component
// is exactly AgencyBuild, shipped on window at the bottom. No build step.
const { useState: useStateBld, useEffect: useEffectBld } = React;

const BLD_TYPES_FALLBACK = [
  { id: "website", label: "Website / Landing page" },
  { id: "workflow", label: "Automation / Workflow" },
  { id: "receptionist", label: "AI Receptionist / Voice agent" },
  { id: "chatbot", label: "AI Chatbot / Assistant" },
  { id: "other", label: "Something else" },
];

const BLD_STATUS_COLOR = {
  draft: "var(--muted)", handed_off: "var(--purple, #8B5CF6)",
  building: "var(--orange)", testing: "#4F7CFF", done: "var(--green)",
};
const BLD_STATUS_LABEL = {
  draft: "Draft", handed_off: "Handed off", building: "Building",
  testing: "Testing", done: "Done",
};

function BldIco(name, size) {
  const Icons = window.Icons;
  const Ico = Icons[name] || Icons.Bot;
  return <Ico size={size || 15} />;
}

// ---- a labeled list block inside the blueprint ------------------------------
function BldBlock({ icon, color, title, children }) {
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <span style={{ color: color || "var(--purple, #8B5CF6)", display: "flex" }}>{BldIco(icon, 16)}</span>
        <span className="card-title" style={{ margin: 0 }}>{title}</span>
      </div>
      {children}
    </div>
  );
}

// ---- the generated blueprint, fully rendered --------------------------------
function BldBlueprintView({ bp }) {
  if (!bp) return null;
  const arch = bp.architecture || [];
  const skills = bp.skills_tools || [];
  const plan = bp.build_plan || [];
  const tests = bp.test_plan || [];
  const info = bp.info_needed || [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
      {bp.concept && (
        <BldBlock icon="Spark" title="The concept">
          <div style={{ fontSize: 13.5, lineHeight: 1.5 }}>{bp.concept}</div>
          {bp.estimate && (
            <div className="faint" style={{ fontSize: 12, marginTop: 2 }}>Rough scope: {bp.estimate}</div>
          )}
        </BldBlock>
      )}

      {bp.how_it_works && (
        <BldBlock icon="Bot" title="How it works">
          <div style={{ fontSize: 13, lineHeight: 1.5, color: "var(--text-2, var(--muted))",
            whiteSpace: "pre-wrap" }}>{bp.how_it_works}</div>
        </BldBlock>
      )}

      {arch.length > 0 && (
        <BldBlock icon="Properties" title="Architecture / layout">
          <div style={{ display: "flex", flexDirection: "column" }}>
            {arch.map((a, i) => (
              <div key={i} style={{ padding: "8px 0", borderTop: i ? "1px solid var(--border)" : "none" }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{a.name || a.step || ("Part " + (i + 1))}</div>
                {a.detail && <div className="faint" style={{ fontSize: 12.5, marginTop: 2 }}>{a.detail}</div>}
              </div>
            ))}
          </div>
        </BldBlock>
      )}

      {skills.length > 0 && (
        <BldBlock icon="Brain" title="Skills & tools it needs">
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {skills.map((s, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                <span style={{ fontWeight: 600, fontSize: 12.5, minWidth: 130 }}>{s.name}</span>
                <span className="faint" style={{ fontSize: 12.5, flex: 1 }}>{s.why}</span>
              </div>
            ))}
          </div>
        </BldBlock>
      )}

      {plan.length > 0 && (
        <BldBlock icon="Check" color="var(--green)" title={"Build plan · " + plan.length + " steps"}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {plan.map((p, i) => (
              <div key={i} style={{ display: "flex", gap: 11, padding: "9px 0",
                borderTop: i ? "1px solid var(--border)" : "none" }}>
                <div style={{ width: 22, height: 22, borderRadius: "50%", flexShrink: 0,
                  background: "var(--purple, #8B5CF6)1f", color: "var(--purple, #8B5CF6)",
                  display: "grid", placeItems: "center", fontSize: 11.5, fontWeight: 700 }}>{i + 1}</div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{p.step}</div>
                  {p.detail && <div className="faint" style={{ fontSize: 12.5, marginTop: 2 }}>{p.detail}</div>}
                  <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4 }}>
                    {p.owner && <span style={{ fontSize: 11, fontWeight: 600, color: "var(--purple, #8B5CF6)" }}>{p.owner}</span>}
                    {p.done_when && <span className="faint" style={{ fontSize: 11 }}>✓ when: {p.done_when}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </BldBlock>
      )}

      {tests.length > 0 && (
        <BldBlock icon="Activity" color="#4F7CFF" title={"Test plan · " + tests.length + " checks"}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {tests.map((t, i) => (
              <div key={i} style={{ padding: "8px 0", borderTop: i ? "1px solid var(--border)" : "none" }}>
                <div style={{ fontWeight: 600, fontSize: 12.5 }}>{t.check}</div>
                {t.how && <div className="faint" style={{ fontSize: 12, marginTop: 2 }}>Run: {t.how}</div>}
                {t.pass && <div style={{ fontSize: 12, marginTop: 2, color: "var(--green)" }}>Pass: {t.pass}</div>}
              </div>
            ))}
          </div>
        </BldBlock>
      )}

      {info.length > 0 && (
        <BldBlock icon="Search" color="var(--orange)" title="Info still needed before a clean build">
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
            {info.map((q, i) => <li key={i} style={{ fontSize: 12.5 }}>{typeof q === "string" ? q : JSON.stringify(q)}</li>)}
          </ul>
        </BldBlock>
      )}
    </div>
  );
}

// ---- one saved blueprint in the list ----------------------------------------
function BldListRow({ b, active, onClick }) {
  const color = BLD_STATUS_COLOR[b.status] || "var(--muted)";
  return (
    <button onClick={onClick} style={{ display: "flex", alignItems: "center", gap: 10, width: "100%",
      padding: "10px 11px", borderRadius: 11, textAlign: "left", cursor: "pointer",
      background: active ? "var(--card-2)" : "transparent",
      border: "1px solid " + (active ? "var(--purple, #8B5CF6)55" : "transparent") }}>
      <span style={{ color: "var(--purple, #8B5CF6)", flexShrink: 0, display: "flex" }}>{BldIco("Spark", 15)}</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{b.title}</div>
        <div className="faint" style={{ fontSize: 11 }}>{b.buildType}{b.client ? " · " + b.client : ""}</div>
      </div>
      <span style={{ fontSize: 10.5, fontWeight: 700, color, flexShrink: 0 }}>{BLD_STATUS_LABEL[b.status] || b.status}</span>
    </button>
  );
}

function AgencyBuild() {
  const { data, loading, error, refresh } = window.useApi("/api/agency/build/list");
  const types = (data && data.buildTypes) || BLD_TYPES_FALLBACK;
  const statuses = (data && data.statuses) || ["draft", "handed_off", "building", "testing", "done"];
  const list = (data && data.blueprints) || [];

  const [buildType, setBuildType] = useStateBld("website");
  const [title, setTitle] = useStateBld("");
  const [idea, setIdea] = useStateBld("");
  const [goal, setGoal] = useStateBld("");
  const [client, setClient] = useStateBld("");
  const [constraints, setConstraints] = useStateBld("");
  const [integrations, setIntegrations] = useStateBld("");
  const [more, setMore] = useStateBld(false);

  const [busy, setBusy] = useStateBld(false);
  const [selected, setSelected] = useStateBld(null); // full blueprint record
  const [msg, setMsg] = useStateBld(null);

  const FIELD = { width: "100%", fontSize: 13, padding: "9px 11px", borderRadius: 10,
    background: "var(--card-2)", border: "1px solid var(--border)", color: "var(--text)" };

  async function generate() {
    if (!idea.trim()) { setMsg({ err: "Describe the idea first." }); return; }
    setBusy(true); setMsg(null);
    try {
      const res = await window.apiPost("/api/agency/build/generate",
        { buildType, title, idea, goal, client, constraints, integrations });
      if (res.needsKey) { setMsg({ err: res.error || "Add ANTHROPIC_API_KEY to agency.env." }); }
      else if (!res.ok) { setMsg({ err: res.error || "Couldn't build the blueprint." }); }
      else { setSelected(res); setMsg({ ok: "Blueprint ready." }); refresh(); }
    } catch (e) {
      setMsg({ err: e.message || "Generation failed." });
    }
    setBusy(false);
  }

  async function handOff() {
    if (!selected) return;
    setBusy(true);
    try {
      const res = await window.apiPost("/api/agency/build/handoff", { id: selected.id });
      if (res.ok) { setSelected(res.blueprint); setMsg({ ok: "Handed to Dyson — queued on the agent bus." }); refresh(); }
      else setMsg({ err: res.error || "Handoff failed." });
    } catch (e) { setMsg({ err: e.message || "Handoff failed." }); }
    setBusy(false);
  }

  async function changeStatus(status) {
    if (!selected) return;
    try {
      const res = await window.apiPost("/api/agency/build/status", { id: selected.id, status });
      if (res.ok) { setSelected({ ...selected, status: res.blueprint.status }); refresh(); }
    } catch (e) { /* ignore */ }
  }

  async function remove() {
    if (!selected) return;
    if (!window.confirm("Delete this blueprint?")) return;
    setBusy(true);
    try {
      await window.apiPost("/api/agency/build/delete", { id: selected.id });
      setSelected(null); setMsg(null); refresh();
    } catch (e) { /* ignore */ }
    setBusy(false);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
        <div style={{ width: 46, height: 46, borderRadius: 12, flexShrink: 0,
          background: "var(--purple, #8B5CF6)1f", color: "var(--purple, #8B5CF6)",
          display: "flex", alignItems: "center", justifyContent: "center" }}>{BldIco("Spark", 24)}</div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Blueprint Studio</h1>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>
            Bring an idea → get a full, build-ready plan: concept, layout, the skills it needs,
            an ordered build plan, and a test plan. One button. Then hand it to your build agent.
          </div>
        </div>
      </div>

      {/* intake */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {types.map((t) => (
            <button key={t.id} onClick={() => setBuildType(t.id)} className="tab"
              style={{ fontSize: 12.5, padding: "7px 13px",
                background: buildType === t.id ? "var(--purple, #8B5CF6)" : "var(--card-2)",
                color: buildType === t.id ? "#fff" : "var(--text)",
                borderColor: buildType === t.id ? "transparent" : "var(--border)" }}>
              {t.label}
            </button>
          ))}
        </div>

        <input value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="Give it a name (optional)" style={FIELD} />

        <textarea value={idea} onChange={(e) => setIdea(e.target.value)} rows={4}
          placeholder="Describe the idea in your own words. What should it do? Who's it for? Be as rough as you like — the more you say, the sharper the plan."
          style={{ ...FIELD, resize: "vertical", lineHeight: 1.5 }} />

        {!more ? (
          <button onClick={() => setMore(true)} className="faint"
            style={{ textAlign: "left", fontSize: 12, cursor: "pointer" }}>+ Add goal, client, constraints, integrations (optional)</button>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input value={goal} onChange={(e) => setGoal(e.target.value)}
              placeholder="Goal / outcome wanted (e.g. book more calls)" style={FIELD} />
            <input value={client} onChange={(e) => setClient(e.target.value)}
              placeholder="For which client (optional)" style={FIELD} />
            <input value={constraints} onChange={(e) => setConstraints(e.target.value)}
              placeholder="Constraints (budget, deadline, must-use tools)" style={FIELD} />
            <input value={integrations} onChange={(e) => setIntegrations(e.target.value)}
              placeholder="Tools / integrations to use (GHL, Stripe, Calendly, Retell…)" style={FIELD} />
          </div>
        )}

        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <button className="tab" disabled={busy} onClick={generate}
            style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700,
              background: "var(--purple, #8B5CF6)", color: "#fff", borderColor: "transparent",
              padding: "10px 18px", opacity: busy ? 0.6 : 1 }}>
            {BldIco("Spark", 15)} {busy ? "Building the plan…" : "Generate blueprint"}
          </button>
          {msg && msg.ok && <span style={{ color: "var(--green)", fontSize: 12.5 }}>{msg.ok}</span>}
          {msg && msg.err && <span style={{ color: "var(--red)", fontSize: 12.5 }}>{msg.err}</span>}
        </div>
      </div>

      {/* selected blueprint */}
      {selected && selected.blueprint && (
        <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
          <div className="card card-pad" style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>{selected.title}</div>
              <div className="faint" style={{ fontSize: 11.5 }}>
                {selected.buildType}{selected.client ? " · " + selected.client : ""} ·
                <span style={{ color: BLD_STATUS_COLOR[selected.status], fontWeight: 600 }}> {BLD_STATUS_LABEL[selected.status] || selected.status}</span>
              </div>
            </div>
            <select value={selected.status} onChange={(e) => changeStatus(e.target.value)}
              style={{ fontSize: 12, padding: "6px 8px", borderRadius: 9, background: "var(--card-2)",
                border: "1px solid var(--border)", color: "var(--text)" }}>
              {statuses.map((s) => <option key={s} value={s}>{BLD_STATUS_LABEL[s] || s}</option>)}
            </select>
            <button className="tab" disabled={busy} onClick={handOff}
              style={{ display: "flex", alignItems: "center", gap: 7, fontWeight: 700,
                background: "var(--purple, #8B5CF6)", color: "#fff", borderColor: "transparent" }}>
              {BldIco("Send", 13)} Hand to Dyson
            </button>
            <button className="tab" disabled={busy} onClick={remove}
              style={{ fontSize: 12, color: "var(--red)" }}>Delete</button>
          </div>
          <div className="faint" style={{ fontSize: 11.5, display: "flex", alignItems: "center", gap: 6, marginTop: -6 }}>
            {BldIco("Check", 12)} Building & testing run through your build agent under the approval gate — nothing ships on its own.
          </div>
          <BldBlueprintView bp={selected.blueprint} />
        </div>
      )}

      {selected && !selected.blueprint && selected.error && (
        <div className="card card-pad" style={{ color: "var(--red)", fontSize: 13 }}>
          Couldn't build this one: {selected.error}
        </div>
      )}

      {/* saved blueprints */}
      <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 8, margin: 0 }}>
          {BldIco("Doc", 15)} Saved blueprints
          <span className="faint" style={{ fontSize: 12, marginLeft: "auto" }}>{list.length}</span>
        </div>
        {error && <window.ErrorRow error={error} onRetry={refresh} />}
        {loading && !data && <window.LoadingRow label="Loading blueprints…" />}
        {!loading && list.length === 0 && (
          <div className="faint" style={{ fontSize: 12.5, padding: "6px 0" }}>
            No blueprints yet — describe an idea above and hit Generate.
          </div>
        )}
        {list.map((b) => (
          <BldListRow key={b.id} b={b} active={selected && selected.id === b.id}
            onClick={() => { setSelected(b); setMsg(null); }} />
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { AgencyBuild });
