// pixel_office.jsx — the Agent Office: every FORGE agent as a live pixel character.
//
// The idea is lifted from pixel-agents (github.com/pixel-agents-hq/pixel-agents), which
// draws Claude Code sessions as pixel people in an office. That project is Vite +
// React 19 + Fastify + a VS Code extension; this dashboard is buildless React 18 UMD
// on a stdlib connector, so nothing there could be dropped in. What IS the same: four
// rooms (our four departments), twelve characters (our twelve real agents), and
// animation driven by real work — pixel_office.state() derives every pose from the
// agent bus, the task store and each engine's own status().
//
// Characters are drawn procedurally with fillRect — no sprite sheets, so no third-party
// art licensing lands in a public repo and there is nothing to download or ship.
//
// Collision discipline (CLAUDE.md §7): unique hook aliases, every top-level name
// prefixed PO/PixelOffice, no computed JSX tags.
const { useState: useStatePO, useEffect: useEffectPO, useRef: useRefPO } = React;

// ── floor geometry (logical pixel-art coords, scaled up by CSS) ───────────────
// Deliberately small: the canvas is upscaled ~2x by CSS with image-rendering:pixelated,
// which is what makes an 11px-tall character read as pixel art instead of a smudge.
const PO_W = 476;
const PO_H = 298;
const PO_ROOM_W = 238;
const PO_ROOM_H = 149;
const PO_ROOM_POS = { rei: [0, 0], agency: [1, 0], daycare: [0, 1], dropship: [1, 1] };

const PO_PALETTE = [
  { skin: "#e8b58c", hair: "#2f2418", shirt: "#4F7CFF" },
  { skin: "#8d5a34", hair: "#150f0a", shirt: "#22C55E" },
  { skin: "#f2cfae", hair: "#8a4b1e", shirt: "#EC4899" },
  { skin: "#5f3a21", hair: "#20160d", shirt: "#F59E0B" },
];

// activity -> how the operator reads it. Kept in one place so the canvas, the legend
// and the roster cards never disagree.
const PO_ACTIVITY = {
  walk:      { label: "Heading to desk", color: "#9FB0C7" },
  read:      { label: "Reading brief",   color: "#2DD4BF" },
  think:     { label: "Working",         color: "#4F7CFF" },
  report:    { label: "Writing up",      color: "#8B5CF6" },
  done:      { label: "Done",            color: "#22C55E" },
  reporting: { label: "Just reported",   color: "#22C55E" },
  queued:    { label: "Task waiting",    color: "#F59E0B" },
  idle:      { label: "Idle",            color: "#64748B" },
  error:     { label: "Needs you",       color: "#EF4444" },
  unknown:   { label: "Not reachable",   color: "#475569" },
};

function poMeta(a) { return PO_ACTIVITY[a] || PO_ACTIVITY.unknown; }
function poBusy(a) { return ["walk", "read", "think", "report"].indexOf(a) >= 0; }

// ── pixel drawing ────────────────────────────────────────────────────────────
function poRect(c, x, y, w, h, fill) { c.fillStyle = fill; c.fillRect(x | 0, y | 0, w, h); }

// One 11x17 character, feet at (x, y). `t` is the animation clock in ms.
function poDrawAgent(c, x, y, pal, activity, t, selected) {
  const bob = poBusy(activity) ? (Math.sin(t / 160) > 0 ? 1 : 0)
                               : (Math.sin(t / 520) > 0 ? 1 : 0);
  const top = y - 17 + bob;

  if (selected) {                                   // selection ring on the floor
    poRect(c, x - 2, y - 1, 15, 1, "#F1F5FB");
    poRect(c, x - 2, y - 2, 1, 1, "#F1F5FB");
    poRect(c, x + 12, y - 2, 1, 1, "#F1F5FB");
  }
  poRect(c, x, y - 1, 11, 1, "rgba(0,0,0,0.45)");   // shadow

  // legs — alternate while walking
  const stride = activity === "walk" && Math.sin(t / 90) > 0;
  poRect(c, x + 2, top + 13, 3, 4, "#1b2436");
  poRect(c, x + 6, top + 13 - (stride ? 1 : 0), 3, 4 + (stride ? 1 : 0), "#1b2436");

  poRect(c, x + 1, top + 6, 9, 7, pal.shirt);        // torso
  poRect(c, x + 1, top + 11, 9, 2, "#0d1422");       // belt

  // arms — typing flutter while working
  const type = (activity === "think" || activity === "report") && Math.sin(t / 70) > 0;
  poRect(c, x - 1, top + 7, 2, type ? 4 : 5, pal.skin);
  poRect(c, x + 10, top + 7, 2, type ? 5 : 4, pal.skin);

  poRect(c, x + 2, top + 1, 7, 6, pal.skin);         // head
  poRect(c, x + 2, top, 7, 2, pal.hair);             // hair
  poRect(c, x + 1, top + 1, 1, 3, pal.hair);
  poRect(c, x + 9, top + 1, 1, 3, pal.hair);
  const blink = Math.sin(t / 1400) > 0.985;
  if (!blink && activity !== "read") {
    poRect(c, x + 3, top + 3, 1, 1, "#101827");
    poRect(c, x + 7, top + 3, 1, 1, "#101827");
  } else {
    poRect(c, x + 3, top + 4, 1, 1, "#101827");
    poRect(c, x + 7, top + 4, 1, 1, "#101827");
  }

  poDrawBubble(c, x, top, activity, t);
}

// The speech / status bubble above a character's head.
function poDrawBubble(c, x, top, activity, t) {
  let glyph = null, color = "#F1F5FB", bg = "#0B1220";
  if (activity === "error") { glyph = "!"; color = "#fff"; bg = "#EF4444"; }
  else if (activity === "done" || activity === "reporting") { glyph = "✓"; color = "#05140a"; bg = "#22C55E"; }
  else if (activity === "think") { glyph = "⚙"; color = "#0a1226"; bg = "#4F7CFF"; }
  else if (activity === "read") { glyph = "≡"; color = "#04211e"; bg = "#2DD4BF"; }
  else if (activity === "report") { glyph = "✎"; color = "#12071f"; bg = "#8B5CF6"; }
  else if (activity === "queued") { glyph = "•"; color = "#1a1102"; bg = "#F59E0B"; }
  else if (activity === "idle" && Math.sin(t / 900) > 0.4) { glyph = "z"; color = "#9FB0C7"; bg = "#0B1220"; }
  if (!glyph) return;
  const by = top - 11 + (Math.sin(t / 300) > 0 ? 0 : 1);
  poRect(c, x + 1, by, 9, 8, bg);
  poRect(c, x + 4, by + 8, 2, 2, bg);
  c.fillStyle = color;
  c.font = "7px ui-monospace, monospace";
  c.textAlign = "center";
  c.fillText(glyph, x + 5.5, by + 6.5);
  c.textAlign = "left";
}

function poDrawDesk(c, x, y, accent, lit, t) {
  poRect(c, x, y, 26, 10, "#20304d");          // desk top
  poRect(c, x, y + 10, 26, 3, "#16203a");
  poRect(c, x + 1, y + 13, 3, 5, "#111a2e");
  poRect(c, x + 22, y + 13, 3, 5, "#111a2e");
  poRect(c, x + 7, y - 9, 13, 9, "#0a1120");   // monitor
  poRect(c, x + 8, y - 8, 11, 7, lit ? accent : "#132038");
  if (lit) {                                    // scanline flicker while working
    const row = ((t / 90) | 0) % 7;
    poRect(c, x + 8, y - 8 + row, 11, 1, "rgba(255,255,255,0.55)");
  }
  poRect(c, x + 12, y, 3, 1, "#0a1120");
}

function poDrawRoom(c, rx, ry, dept, t) {
  poRect(c, rx, ry, PO_ROOM_W, PO_ROOM_H, "#0a1120");            // wall
  poRect(c, rx + 3, ry + 21, PO_ROOM_W - 6, PO_ROOM_H - 24, "#0e1728");  // floor
  for (let i = rx + 3; i < rx + PO_ROOM_W - 6; i += 16) {        // floor tiles
    poRect(c, i, ry + 21, 1, PO_ROOM_H - 24, "rgba(255,255,255,0.025)");
  }
  for (let j = ry + 21; j < ry + PO_ROOM_H - 3; j += 16) {
    poRect(c, rx + 3, j, PO_ROOM_W - 6, 1, "rgba(255,255,255,0.025)");
  }
  poRect(c, rx, ry, PO_ROOM_W, 18, "#111c33");                   // nameplate bar
  poRect(c, rx, ry + 17, PO_ROOM_W, 1, dept.accent);
  poRect(c, rx, ry, 3, PO_ROOM_H, dept.accent + "44");
  const live = (dept.agents || []).filter((a) => poBusy(a.activity)).length;
  c.fillStyle = dept.accent;
  c.font = "bold 10px ui-monospace, monospace";
  c.fillText(dept.label.toUpperCase(), rx + 8, ry + 12);
  c.fillStyle = live ? "#22C55E" : "#475569";
  c.font = "9px ui-monospace, monospace";
  c.textAlign = "right";
  c.fillText(live ? live + " WORKING" : "QUIET", rx + PO_ROOM_W - 8, ry + 12);
  c.textAlign = "left";
  // a plant in the corner, because an office needs one
  poRect(c, rx + PO_ROOM_W - 18, ry + PO_ROOM_H - 16, 8, 6, "#7c4a2a");
  poRect(c, rx + PO_ROOM_W - 20, ry + PO_ROOM_H - 24, 12, 8, "#1f7a4d");
  void t;
}

// Desk anchor for agent #i of n inside a room at (rx, ry). Two staggered rows so four
// agents never overlap, and everything stays inside the room's walls.
function poDeskXY(rx, ry, i, n) {
  const span = PO_ROOM_W - 62;
  const step = n > 1 ? span / (n - 1) : 0;
  const x = rx + 20 + (n > 1 ? step * i : span / 2);
  const y = ry + (i % 2 === 0 ? 56 : 101);
  return [x, y];
}

// ── the canvas floor ─────────────────────────────────────────────────────────
function PixelOfficeFloor({ departments, selected, onSelect }) {
  const canvasRef = useRefPO(null);
  const actorsRef = useRefPO({});      // agentId -> {x, y, tx, ty, activity, box}
  const deptRef = useRefPO(departments);
  const selRef = useRefPO(selected);
  deptRef.current = departments;
  selRef.current = selected;

  useEffectPO(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const c = cv.getContext("2d");
    c.imageSmoothingEnabled = false;
    let raf;

    const frame = (t) => {
      const depts = deptRef.current || [];
      poRect(c, 0, 0, PO_W, PO_H, "#050B18");

      depts.forEach((d) => {
        const pos = PO_ROOM_POS[d.id] || [0, 0];
        const rx = pos[0] * PO_ROOM_W;
        const ry = pos[1] * PO_ROOM_H;
        poDrawRoom(c, rx, ry, d, t);

        const n = (d.agents || []).length;
        (d.agents || []).forEach((a, i) => {
          const desk = poDeskXY(rx, ry, i, n);
          poDrawDesk(c, desk[0], desk[1], d.accent, poBusy(a.activity), t);

          let act = actorsRef.current[a.id];
          if (!act) {
            act = { x: desk[0] + 8, y: desk[1] + 30, seed: i * 977 };
            actorsRef.current[a.id] = act;
          }
          // Busy agents stand at their desk. Idle ones drift nearby — a slow lissajous
          // instead of pathfinding, which is plenty for a 340px room.
          if (poBusy(a.activity) || a.activity === "queued") {
            act.tx = desk[0] + 8;
            act.ty = desk[1] + 26;
          } else {
            act.tx = desk[0] + 8 + Math.sin((t + act.seed) / 2600) * 20;
            act.ty = desk[1] + 28 + Math.cos((t + act.seed) / 3300) * 7;
          }
          const speed = a.activity === "walk" ? 0.09 : 0.03;
          act.x += (act.tx - act.x) * speed;
          act.y += (act.ty - act.y) * speed;
          const moving = Math.abs(act.tx - act.x) > 1.2;
          const shown = a.activity === "walk" && !moving ? "think"
                      : (moving && !poBusy(a.activity) ? "walk" : a.activity);

          const pal = PO_PALETTE[i % PO_PALETTE.length];
          const dim = a.activity === "unknown";
          if (dim) c.globalAlpha = 0.42;
          poDrawAgent(c, act.x, act.y, pal, shown, t, selRef.current === a.id);
          c.globalAlpha = 1;

          c.fillStyle = selRef.current === a.id ? "#F1F5FB" : "#9FB0C7";
          c.font = "8px ui-monospace, monospace";
          c.textAlign = "center";
          c.fillText(a.name.toUpperCase(), act.x + 5, act.y + 9);
          c.textAlign = "left";
          act.box = [act.x - 8, act.y - 30, 27, 42];   // click target
        });
      });
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, []);

  function hit(e) {
    const cv = canvasRef.current;
    const r = cv.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * PO_W;
    const y = ((e.clientY - r.top) / r.height) * PO_H;
    const entries = Object.entries(actorsRef.current);
    for (let i = 0; i < entries.length; i++) {
      const b = entries[i][1].box;
      if (b && x >= b[0] && x <= b[0] + b[2] && y >= b[1] && y <= b[1] + b[3]) {
        onSelect(entries[i][0]);
        return;
      }
    }
  }

  return (
    <canvas ref={canvasRef} width={PO_W} height={PO_H} onClick={hit}
      style={{ width: "100%", display: "block", imageRendering: "pixelated",
               cursor: "pointer", borderRadius: 14, border: "1px solid var(--border)",
               background: "#050B18" }} />
  );
}

// ── the agent panel: status, live step log, and the task box ─────────────────
function PixelOfficePanel({ agent, job, onDispatch, sending, err }) {
  const [title, setTitle] = useStatePO("");
  const Icons = window.Icons;
  if (!agent) {
    return (
      <div className="card" style={{ padding: 18, height: "100%" }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Pick an agent</div>
        <div className="faint" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
          Click a character on the floor. You'll get their status, a live log of what
          they're doing, and a box to hand them a task — the same brain the Agents tab
          uses, so the work is real. Outward actions stay approval-gated.
        </div>
      </div>
    );
  }
  const meta = poMeta(agent.activity);
  const steps = (job && job.steps) || [];
  const running = job && job.status === "running";

  return (
    <div className="card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, height: "100%", minHeight: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <div style={{ width: 40, height: 40, borderRadius: 11, background: "var(--card-2)", display: "grid", placeItems: "center", fontSize: 20 }}>{agent.emoji}</div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{agent.name}</div>
          <div className="faint" style={{ fontSize: 11.5 }}>{agent.role}</div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 12 }}>
        <span style={{ width: 8, height: 8, borderRadius: 9, background: meta.color }} />
        <span style={{ color: meta.color, fontWeight: 600 }}>{meta.label}</span>
        {agent.openTasks > 0 && <span className="faint">· {agent.openTasks} open</span>}
      </div>
      {agent.detail && (
        <div className="faint" style={{ fontSize: 11.5, lineHeight: 1.5, maxHeight: 54, overflow: "hidden" }}>{agent.detail}</div>
      )}

      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 11 }}>
        <div className="faint" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 7 }}>
          {running ? "Working now" : "Last run"}
        </div>
        {steps.length === 0 && <div className="faint" style={{ fontSize: 12 }}>No run yet this session.</div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {steps.map((s, i) => (
            <div key={i} style={{ display: "flex", gap: 8, fontSize: 11.5, alignItems: "flex-start" }}>
              <span style={{ width: 7, height: 7, borderRadius: 9, marginTop: 4, flexShrink: 0, background: poMeta(s.phase).color }} />
              <span style={{ color: s.phase === "error" ? "var(--red)" : "var(--text-2)", lineHeight: 1.45 }}>{s.text}</span>
            </div>
          ))}
        </div>
      </div>

      {job && job.status === "done" && job.result && (
        <div style={{ background: "var(--card-2)", borderRadius: 10, padding: 11, fontSize: 12, lineHeight: 1.55, whiteSpace: "pre-wrap", overflowY: "auto", maxHeight: 240, flex: "1 1 auto", minHeight: 0 }}>
          {job.result}
        </div>
      )}
      {job && job.status === "error" && (
        <div style={{ color: "var(--red)", fontSize: 12 }}>{job.error}</div>
      )}

      <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 7 }}>
        {err && <div style={{ color: "var(--red)", fontSize: 11.5 }}>{err}</div>}
        <textarea value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder={"Give " + agent.name + " a task…"} rows={2}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && title.trim()) {
              onDispatch(title.trim()); setTitle("");
            }
          }}
          style={{ width: "100%", background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 10, padding: "9px 11px", color: "var(--text)", fontSize: 12.5, fontFamily: "var(--font)", resize: "vertical" }} />
        <button className="btn"
          disabled={sending || running || !title.trim()}
          onClick={() => { onDispatch(title.trim()); setTitle(""); }}
          style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, padding: "9px 12px", borderRadius: 10, fontSize: 12.5, fontWeight: 600, background: running ? "var(--card-2)" : "var(--workspace-accent)", color: running ? "var(--text-3)" : "#fff", opacity: (sending || running || !title.trim()) ? 0.55 : 1 }}>
          <Icons.Send size={14} /> {running ? "Working…" : sending ? "Sending…" : "Send task"}
        </button>
        <div className="faint" style={{ fontSize: 10.5, lineHeight: 1.45 }}>
          Runs the agent's real brain and reports back. Never texts, spends, or posts —
          outward actions stay one-tap gated.
        </div>
      </div>
    </div>
  );
}

// ── the page ─────────────────────────────────────────────────────────────────
function PixelOfficePage() {
  const [state, setState] = useStatePO(null);
  const [err, setErr] = useStatePO(null);
  const [selected, setSelected] = useStatePO(null);
  const [job, setJob] = useStatePO(null);
  const [sending, setSending] = useStatePO(false);
  const [sendErr, setSendErr] = useStatePO(null);
  const jobIdRef = useRefPO(null);

  // Floor state — 2.5s poll. Everything here is derived server-side from real signals.
  useEffectPO(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await window.apiGet("/api/office/state");
        if (alive) { setState(d); setErr(null); }
      } catch (e) { if (alive) setErr(e.message || String(e)); }
    };
    load();
    const timer = setInterval(load, 2500);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const agents = [];
  ((state && state.departments) || []).forEach((d) => (d.agents || []).forEach((a) => agents.push(a)));
  const agent = agents.find((a) => a.id === selected) || null;

  // Follow whichever job belongs to the selected agent — live while running, then the
  // finished result stays on screen.
  const followId = (agent && (agent.jobId || (agent.lastJob && agent.lastJob.id))) || null;
  useEffectPO(() => {
    jobIdRef.current = followId;
    if (!followId) { setJob(null); return; }
    let alive = true;
    const load = async () => {
      try {
        const d = await window.apiGet("/api/office/job?id=" + encodeURIComponent(followId));
        if (alive && d.job && jobIdRef.current === followId) setJob(d.job);
      } catch (_) { /* a job that aged out of the log is not an error */ }
    };
    load();
    const timer = setInterval(load, 1200);
    return () => { alive = false; clearInterval(timer); };
  }, [followId]);

  async function dispatch(title) {
    if (!agent || !title) return;
    setSending(true); setSendErr(null);
    try {
      const d = await window.apiPost("/api/office/task", { agentId: agent.id, title });
      if (d.jobId) {
        jobIdRef.current = d.jobId;
        setJob({ id: d.jobId, status: "running", steps: [] });
      }
      const s = await window.apiGet("/api/office/state");
      setState(s);
    } catch (e) { setSendErr(e.message || String(e)); }
    setSending(false);
  }

  const busy = agents.filter((a) => poBusy(a.activity)).length;
  const legend = ["think", "read", "report", "queued", "idle", "error"];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="card" style={{ padding: "13px 16px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14.5 }}>Agent Office</div>
          <div className="faint" style={{ fontSize: 11.5 }}>
            All four departments, live. {agents.length} agents · {busy} working right now.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {legend.map((k) => (
            <span key={k} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11 }}>
              <span style={{ width: 8, height: 8, borderRadius: 9, background: poMeta(k).color }} />
              <span className="faint">{poMeta(k).label}</span>
            </span>
          ))}
        </div>
      </div>

      {err && <div className="card" style={{ padding: 14, color: "var(--red)", fontSize: 12.5 }}>Office feed: {err}</div>}

      <div className="office-grid" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 330px", gap: 14, alignItems: "start" }}>
        <div>
          <PixelOfficeFloor
            departments={(state && state.departments) || []}
            selected={selected}
            onSelect={setSelected} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(150px,1fr))", gap: 8, marginTop: 12 }}>
            {agents.map((a) => {
              const m = poMeta(a.activity);
              return (
                <button key={a.id} onClick={() => setSelected(a.id)}
                  className="card"
                  style={{ padding: "9px 11px", display: "flex", alignItems: "center", gap: 9, textAlign: "left", borderRadius: 12, border: selected === a.id ? "1px solid var(--workspace-accent)" : "1px solid var(--border)" }}>
                  <span style={{ fontSize: 16 }}>{a.emoji}</span>
                  <span style={{ minWidth: 0, flex: 1 }}>
                    <span style={{ display: "block", fontSize: 12.5, fontWeight: 600 }}>{a.name}</span>
                    <span style={{ display: "block", fontSize: 10.5, color: m.color }}>{m.label}</span>
                  </span>
                  {a.openTasks > 0 && (
                    <span className="tabnum" style={{ fontSize: 10.5, color: "var(--orange)", fontWeight: 700 }}>{a.openTasks}</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div style={{ position: "sticky", top: 12, height: "min(78vh, 720px)" }}>
          <PixelOfficePanel agent={agent} job={job} onDispatch={dispatch}
            sending={sending} err={sendErr} />
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { PixelOfficePage, PixelOfficeFloor, PixelOfficePanel });
