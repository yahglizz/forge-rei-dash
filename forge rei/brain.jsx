// brain.jsx — Brain tab. Vault (Obsidian) + Graphify (global knowledge graph).
// Two data sources, same force-graph renderer.
const { useState: useStateB } = React;

function BrainMd({ text }) {
  if (!text) return null;
  const lines = text.split("\n");
  const out = [];
  let inFm = false;
  lines.forEach((ln, i) => {
    if (i === 0 && ln.trim() === "---") { inFm = true; return; }
    if (inFm) { if (ln.trim() === "---") inFm = false; return; }
    const link = (s) => s.split(/(\[\[[^\]]+\]\])/g).map((p, j) =>
      p.startsWith("[[") ? <span key={j} style={{ color: "var(--blue-soft)" }}>{p.slice(2, -2)}</span> : p);
    const bold = (s) => (typeof s === "string" ? s : "").split(/(\*\*[^*]+\*\*)/g).map((p, j) =>
      p.startsWith("**") ? <b key={j}>{p.slice(2, -2)}</b> : link(p));
    if (/^#\s/.test(ln)) out.push(<div key={i} style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>{ln.replace(/^#\s/, "")}</div>);
    else if (/^##\s/.test(ln)) out.push(<div key={i} style={{ fontSize: 15, fontWeight: 700, marginTop: 14, marginBottom: 4 }}>{ln.replace(/^##\s/, "")}</div>);
    else if (/^\s*[-*]\s/.test(ln)) out.push(<div key={i} style={{ fontSize: 13, lineHeight: 1.6, paddingLeft: 14 }}>• {bold(ln.replace(/^\s*[-*]\s/, ""))}</div>);
    else if (ln.trim()) out.push(<div key={i} style={{ fontSize: 13.5, lineHeight: 1.6, marginBottom: 6 }}>{bold(ln)}</div>);
  });
  return <div>{out}</div>;
}

// folder -> stable color
const FOLDER_COLORS = ["#4F7CFF", "#8B5CF6", "#2DD4BF", "#22C55E", "#F59E0B", "#EC4899", "#EF4444", "#0EA5E9"];
function folderColor(s) {
  let h = 0; for (let i = 0; i < (s || "").length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return FOLDER_COLORS[h % FOLDER_COLORS.length];
}

// ── Force-directed graph (vanilla, no lib). Settles then stops. ───────────────
function BrainGraph({ data, selId, onPick }) {
  const BOX = { w: 820, h: 580, cx: 410, cy: 290 };
  const nodes = (data && data.nodes) || [];
  const links = (data && data.links) || [];
  const posRef = React.useRef({});
  const velRef = React.useRef({});
  const rafRef = React.useRef(0);
  const [, setTick] = useStateB(0);
  const [hover, setHover] = useStateB(null);

  const ids = nodes.map((n) => n.id).join("|");
  React.useEffect(() => {
    // (re)seed any new nodes on a circle; keep existing positions
    const N = nodes.length || 1;
    nodes.forEach((n, i) => {
      if (!posRef.current[n.id]) {
        const a = (i / N) * Math.PI * 2;
        posRef.current[n.id] = { x: BOX.cx + Math.cos(a) * 200, y: BOX.cy + Math.sin(a) * 200 };
        velRef.current[n.id] = { x: 0, y: 0 };
      }
    });
    Object.keys(posRef.current).forEach((id) => { if (!nodes.find((n) => n.id === id)) { delete posRef.current[id]; delete velRef.current[id]; } });

    let iter = 0;
    const step = () => {
      const P = posRef.current, V = velRef.current;
      const arr = nodes;
      for (let i = 0; i < arr.length; i++) {
        const a = arr[i], pa = P[a.id]; if (!pa) continue;
        let fx = (BOX.cx - pa.x) * 0.012, fy = (BOX.cy - pa.y) * 0.012; // gravity
        for (let j = 0; j < arr.length; j++) {
          if (i === j) continue;
          const pb = P[arr[j].id]; if (!pb) continue;
          let dx = pa.x - pb.x, dy = pa.y - pb.y;
          let d2 = dx * dx + dy * dy || 0.01;
          const f = Math.min(1600 / d2, 3);
          const d = Math.sqrt(d2);
          fx += (dx / d) * f; fy += (dy / d) * f; // repulsion
        }
        const va = V[a.id];
        va.x = (va.x + fx) * 0.82; va.y = (va.y + fy) * 0.82;
      }
      links.forEach((l) => {
        const pa = P[l.source], pb = P[l.target]; if (!pa || !pb) return;
        let dx = pb.x - pa.x, dy = pb.y - pa.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const f = (d - 74) * 0.018; // spring
        const ux = dx / d, uy = dy / d;
        V[l.source].x += ux * f; V[l.source].y += uy * f;
        V[l.target].x -= ux * f; V[l.target].y -= uy * f;
      });
      arr.forEach((n) => {
        const p = P[n.id], v = V[n.id]; if (!p) return;
        p.x = Math.max(20, Math.min(BOX.w - 20, p.x + v.x));
        p.y = Math.max(20, Math.min(BOX.h - 20, p.y + v.y));
      });
      setTick((t) => t + 1);
      iter++;
      if (iter < 480) rafRef.current = requestAnimationFrame(step);
    };
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafRef.current);
  }, [ids]);

  const P = posRef.current;
  if (!nodes.length) return <div className="empty" style={{ flex: 1 }}><div className="empty-ico"><window.Icons.Brain size={24} /></div><div style={{ fontWeight: 600, color: "var(--text)" }}>Brain is empty</div><div style={{ fontSize: 12 }}>Notes appear here as the agents learn.</div></div>;

  return (
    <svg viewBox={`0 0 ${BOX.w} ${BOX.h}`} style={{ width: "100%", height: "100%", display: "block" }}>
      {links.map((l, i) => {
        const a = P[l.source], b = P[l.target]; if (!a || !b) return null;
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="var(--border)" strokeWidth="1" opacity="0.6" />;
      })}
      {nodes.map((n) => {
        const p = P[n.id]; if (!p) return null;
        const r = 5 + Math.min(n.deg || 0, 6) * 1.6;
        const on = n.id === selId || n.id === hover;
        const col = folderColor(n.folder);
        return (
          <g key={n.id} transform={`translate(${p.x},${p.y})`} style={{ cursor: "pointer" }}
            onClick={() => onPick(n.id)} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}>
            <circle r={r} fill={col} stroke={on ? "#fff" : "transparent"} strokeWidth="1.5" opacity={on ? 1 : 0.9} />
            {(on || (n.deg || 0) >= 2 || nodes.length <= 40) && (
              <text x={r + 3} y={3.5} fontSize="9" fill={on ? "var(--text)" : "var(--text-3)"} style={{ pointerEvents: "none", fontWeight: on ? 700 : 400 }}>{n.title}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ── Live activity rail: what the brain learned/updated, with undo ─────────────
function BrainActivity({ onUndone }) {
  const Icons = window.Icons;
  const { data, refresh } = window.useApi("/api/brain/activity?n=30", { interval: 12000 });
  const [busy, setBusy] = useStateB(null);
  const [msg, setMsg] = useStateB(null);
  const items = (data && data.items) || [];

  async function undo(path) {
    if (!window.confirm(`Undo the last change to:\n${path}\n\nRestores the previous version.`)) return;
    setBusy(path); setMsg(null);
    try {
      const r = await window.apiPost("/api/brain/undo", { path });
      setMsg(r.ok ? `Undone: ${path.split("/").pop()}` : `Failed: ${r.error || "?"}`);
      refresh(); onUndone && onUndone();
    } catch (e) { setMsg(`Failed: ${e.message}`); }
    setBusy(null);
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 0, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div className="card-title" style={{ margin: 0, display: "flex", alignItems: "center", gap: 7 }}><Icons.Activity size={15} /> Brain Activity</div>
        <span className="dot online pulse" />
      </div>
      {msg && <div className="faint" style={{ fontSize: 11, color: msg.startsWith("Undone") ? "var(--green)" : "var(--red)" }}>{msg}</div>}
      <div style={{ overflowY: "auto", display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>
        {data && !data.hasGit && <div className="faint" style={{ fontSize: 11.5 }}>Vault has no git history — undo unavailable.</div>}
        {items.length === 0 && <div className="faint" style={{ fontSize: 11.5 }}>No learnings yet. Run “Learn from today.”</div>}
        {items.map((it, i) => (
          <div key={it.hash + i} style={{ borderLeft: "2px solid var(--blue)", paddingLeft: 9 }}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{it.reason}</div>
            <div className="faint" style={{ fontSize: 10.5, marginTop: 1 }}>{window.timeAgo(it.when)}</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4, alignItems: "center" }}>
              {it.files.map((f) => <span key={f} className="pill" style={{ background: "var(--card-2)", fontSize: 9.5 }}>{f.split("/").pop()}</span>)}
              {data.hasGit && it.files[0] && (
                <button onClick={() => undo(it.files[0])} disabled={busy === it.files[0]}
                  className="link" style={{ fontSize: 10.5, color: "var(--orange)" }}>{busy === it.files[0] ? "…" : "undo"}</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Daily style learning ──────────────────────────────────────────────────────
function LearnPanel({ onLearned }) {
  const Icons = window.Icons;
  const { data, refresh } = window.useApi("/api/style/latest", { interval: 0 });
  const [running, setRunning] = useStateB(false);
  const [res, setRes] = useStateB(null);

  async function learn() {
    setRunning(true); setRes(null);
    try {
      const r = await window.apiPost("/api/style/run", { days: 1 });
      setRes(r); refresh(); onLearned && onLearned();
    } catch (e) { setRes({ error: e.message }); }
    setRunning(false);
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div className="card-title" style={{ margin: 0, display: "flex", alignItems: "center", gap: 7 }}><Icons.Spark size={15} /> Daily Learning</div>
        <button className="tab" onClick={learn} disabled={running} style={{ fontSize: 11, border: "1px solid var(--border)" }}>
          {running ? "Learning…" : "Learn from today"}
        </button>
      </div>
      <div className="faint" style={{ fontSize: 11, lineHeight: 1.45 }}>
        Reads today's texts, learns your voice, turns it into skills Marcus copies. Runs nightly; or hit the button.
      </div>
      {res && res.needsKey && <div style={{ fontSize: 11.5, color: "var(--orange)" }}>{res.message}</div>}
      {res && res.error && <div style={{ fontSize: 11.5, color: "var(--red)" }}>Error: {res.error}</div>}
      {res && res.message && !res.needsKey && <div className="faint" style={{ fontSize: 11.5 }}>{res.message}</div>}
      {res && res.ok && (
        <div style={{ fontSize: 11.5, color: "var(--green)" }}>
          Learned from {res.pairs} texts → {res.skills} skills, {res.snippets} snippets written.
        </div>
      )}
      {data && data.hasDigest && (
        <div className="faint" style={{ fontSize: 10.5, borderTop: "1px solid var(--border)", paddingTop: 6 }}>
          Last digest: {data.date}{data.voice ? " · voice guide active (Marcus uses it)" : ""}
        </div>
      )}
    </div>
  );
}

// ── Graphify node detail (reader panel when in GRAPHIFY mode) ─────────────────
function GraphifyNodeDetail({ nodeId, allNodes, allLinks }) {
  if (!nodeId) return <div className="faint" style={{ padding: 16 }}>Click a node in the graph to explore.</div>;
  const node = allNodes.find((n) => n.id === nodeId);
  if (!node) return <div className="faint" style={{ padding: 16 }}>Node not found.</div>;

  const nbrs = [];
  allLinks.forEach((l) => {
    if (l.source === nodeId) {
      const t = allNodes.find((n) => n.id === l.target);
      if (t) nbrs.push({ node: t, rel: l.kind || l.relation || "→", dir: "→" });
    } else if (l.target === nodeId) {
      const s = allNodes.find((n) => n.id === l.source);
      if (s) nbrs.push({ node: s, rel: l.kind || l.relation || "←", dir: "←" });
    }
  });

  const repoColor = { "forge-rei-os": "#4F7CFF", "agentic-os": "#8B5CF6", "clientforge": "#2DD4BF", "lead-scraper": "#22C55E" };
  const ftColor   = { code: "var(--blue-soft)", document: "var(--green)", rationale: "#F59E0B" };
  const rc = repoColor[node.repo] || "#aaa";
  const fc = ftColor[node.file_type] || "var(--text-3)";

  return (
    <div style={{ padding: 16, fontSize: 13, lineHeight: 1.6 }}>
      <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 6 }}>{node.title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        <span className="pill" style={{ background: rc + "22", color: rc, border: `1px solid ${rc}55` }}>{node.repo}</span>
        <span className="pill" style={{ background: "var(--card-2)", color: fc }}>{node.file_type}</span>
        <span className="pill" style={{ background: "var(--card-2)", color: "var(--text-3)" }}>community {node.community}</span>
      </div>
      {node.source_file && <div className="faint mono" style={{ fontSize: 11, marginBottom: 12 }}>📄 {node.source_file}</div>}
      {nbrs.length > 0 && (
        <div>
          <div className="faint" style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", marginBottom: 6 }}>⇄ Connections ({nbrs.length})</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 320, overflowY: "auto" }}>
            {nbrs.slice(0, 30).map((nb, i) => {
              const nrc = repoColor[nb.node.repo] || "#aaa";
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 8px", background: "var(--card-2)", borderRadius: 5, fontSize: 12 }}>
                  <span style={{ color: "var(--text-3)", minWidth: 14 }}>{nb.dir}</span>
                  <span style={{ flex: 1, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{nb.node.title}</span>
                  <span className="pill" style={{ background: nrc + "22", color: nrc, fontSize: 9.5, flexShrink: 0 }}>{nb.node.repo}</span>
                  <span className="faint" style={{ fontSize: 10, flexShrink: 0 }}>{nb.rel}</span>
                </div>
              );
            })}
            {nbrs.length > 30 && <div className="faint" style={{ fontSize: 10.5 }}>+ {nbrs.length - 30} more</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function BrainPage() {
  const Icons = window.Icons;
  const [src, setSrc]       = useStateB("vault");          // "vault" | "graphify"
  const [view, setView]     = useStateB("graph");           // graph | files
  const [sel, setSel]       = useStateB("Skills/marcus-playbook.md");
  const [gfySel, setGfySel] = useStateB(null);             // selected graphify node id
  const [q, setQ]           = useStateB("");
  const [results, setResults]     = useStateB(null);
  const [gfyResults, setGfyResults] = useStateB(null);

  const { data: tree, error } = window.useApi("/api/brain/tree", { interval: 0 });
  const brainStatus = window.useApi("/api/brain/status", { interval: 30000 });
  const graph    = window.useApi("/api/brain/graph?limit=90",  { interval: 30000 });
  const gfyGraph = window.useApi("/api/graphify/graph",         { interval: 60000 });
  const gfyStats = window.useApi("/api/graphify/stats",         { interval: 60000 });
  const note     = window.useApi(sel ? `/api/brain/note?path=${encodeURIComponent(sel)}` : "/api/brain/tree", { interval: 0 });
  const folders  = (tree && tree.folders) || [];

  const isGfy = src === "graphify";

  async function search(e) {
    e && e.preventDefault();
    if (!q.trim()) { setResults(null); setGfyResults(null); return; }
    if (isGfy) {
      try {
        const r = await window.apiGet(`/api/graphify/search?q=${encodeURIComponent(q.trim())}`);
        setGfyResults(r);
      } catch (err) { setGfyResults({ hits: [] }); }
    } else {
      try { setResults(await window.apiGet(`/api/brain/search?q=${encodeURIComponent(q.trim())}`)); }
      catch (err) { setResults({ results: [], mode: "error" }); }
    }
  }

  const pick = (path) => { setSel(path); setView("files"); };
  const pickGfy = (id) => { setGfySel(id); setView("files"); };

  const gfyNodes = (gfyGraph.data && gfyGraph.data.nodes) || [];
  const gfyLinks = (gfyGraph.data && gfyGraph.data.links) || [];

  // sub-label under the title
  let subtitle = "";
  if (isGfy) {
    if (gfyStats.data && gfyStats.data.ok) {
      const gs = gfyStats.data;
      subtitle = `${gs.nodes} nodes · ${gs.links} links · ${gs.communities} communities — ${Object.entries(gs.byRepo || {}).map(([r,c]) => `${r}:${c}`).join(" · ")}`;
    }
  } else {
    const bs = brainStatus.data;
    subtitle = (tree ? tree.vault : "Obsidian vault…")
      + (graph.data ? ` · ${graph.data.nodes.length} notes · ${graph.data.links.length} links` : "")
      + (bs ? ` · ${bs.live ? "LIVE" : "CHECK"} · ${bs.agentsReady || 0}/${bs.agentsTotal || 0} agents fed` : "");
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px", display: "flex", alignItems: "center", gap: 10 }}>
            <Icons.Brain size={22} /> Brain
          </h1>
          <p className="faint mono" style={{ fontSize: 12, marginTop: 3 }}>{subtitle}</p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {/* Source toggle */}
          <div className="tabs">
            <button className={"tab" + (!isGfy ? " active" : "")} onClick={() => { setSrc("vault"); setView("graph"); setQ(""); setResults(null); setGfyResults(null); }}>📓 Vault</button>
            <button className={"tab" + (isGfy ? " active" : "")} style={isGfy ? { borderColor: "#8B5CF6", color: "#8B5CF6", background: "rgba(139,92,246,0.15)" } : {}} onClick={() => { setSrc("graphify"); setView("graph"); setQ(""); setResults(null); setGfyResults(null); }}>🕸 Graphify</button>
          </div>
          <div style={{ width: 1, height: 22, background: "var(--border)" }} />
          {/* View toggle */}
          <div className="tabs">
            <button className={"tab" + (view === "graph" ? " active" : "")} onClick={() => setView("graph")}>Graph</button>
            <button className={"tab" + (view === "files" ? " active" : "")} onClick={() => setView("files")}>{isGfy ? "Detail" : "Files"}</button>
          </div>
          <form className="search" style={{ width: 240 }} onSubmit={search}>
            <Icons.Search size={16} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={isGfy ? "Search graphify…" : "Search the brain…"} />
          </form>
        </div>
      </div>

      {!isGfy && error && <window.ErrorRow error={error} />}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 300px", gap: 16, alignItems: "stretch", flex: 1, minHeight: 0 }}>
        {/* MAIN — graph OR detail/files */}
        {view === "graph" ? (
          <div className="card" style={{ position: "relative", overflow: "hidden", minHeight: 0 }}>
            {isGfy ? (
              gfyGraph.loading && !gfyGraph.data
                ? <window.LoadingRow label="Loading knowledge graph…" />
                : gfyGraph.data && <BrainGraph data={gfyGraph.data} selId={gfySel} onPick={pickGfy} />
            ) : (
              graph.loading && !graph.data
                ? <window.LoadingRow label="Mapping the brain…" />
                : graph.data && <BrainGraph data={graph.data} selId={sel} onPick={pick} />
            )}
            <div className="faint" style={{ position: "absolute", left: 12, bottom: 10, fontSize: 10.5 }}>
              {isGfy ? `${gfyNodes.length} nodes across all projects — click to explore` : "click a node to open · auto-refreshes"}
            </div>
          </div>
        ) : isGfy ? (
          /* Graphify detail view */
          <div style={{ display: "grid", gridTemplateColumns: "240px minmax(0,1fr)", gap: 14, minHeight: 0 }}>
            <div className="card" style={{ overflowY: "auto", minHeight: 0 }}>
              {gfyResults ? (
                <div style={{ padding: 10 }}>
                  <div className="faint" style={{ fontSize: 11, padding: "4px 8px", display: "flex", justifyContent: "space-between" }}>
                    <span>{(gfyResults.hits || []).length} hits</span>
                    <button className="link" onClick={() => { setGfyResults(null); setQ(""); }}>clear</button>
                  </div>
                  {(gfyResults.hits || []).map((h) => (
                    <button key={h.id} onClick={() => setGfySel(h.id)} className={"nav-item" + (gfySel === h.id ? " active" : "")} style={{ width: "100%", textAlign: "left", flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
                      <span style={{ fontSize: 12, fontWeight: 600 }}>{h.label}</span>
                      <span className="faint" style={{ fontSize: 10, whiteSpace: "normal" }}>{h.repo} · {h.file_type}</span>
                    </button>
                  ))}
                </div>
              ) : (
                /* repo tree */
                (gfyGraph.data && gfyGraph.data.folders || []).map((repo) => {
                  const repoNodes = gfyNodes.filter((n) => n.folder === repo).slice(0, 40);
                  return (
                    <div key={repo} style={{ padding: "6px 8px" }}>
                      <div className="faint" style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, padding: "6px 8px" }}>
                        🗂 {repo} <span style={{ opacity: 0.6 }}>{gfyNodes.filter((n) => n.folder === repo).length}</span>
                      </div>
                      {repoNodes.map((n) => (
                        <button key={n.id} onClick={() => setGfySel(n.id)}
                          className={"nav-item" + (gfySel === n.id ? " active" : "")}
                          style={{ width: "100%", textAlign: "left", fontSize: 12, padding: "5px 10px" }}>
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{n.title}</span>
                        </button>
                      ))}
                    </div>
                  );
                })
              )}
            </div>
            <div className="card" style={{ overflowY: "auto", minHeight: 0 }}>
              <GraphifyNodeDetail nodeId={gfySel} allNodes={gfyNodes} allLinks={gfyLinks} />
            </div>
          </div>
        ) : (
          /* Vault files view */
          <div style={{ display: "grid", gridTemplateColumns: "240px minmax(0,1fr)", gap: 14, minHeight: 0 }}>
            <div className="card" style={{ overflowY: "auto", minHeight: 0 }}>
              {results ? (
                <div style={{ padding: 10 }}>
                  <div className="faint" style={{ fontSize: 11, padding: "4px 8px", display: "flex", justifyContent: "space-between" }}>
                    <span>{results.results.length} hits · {results.mode}</span>
                    <button className="link" onClick={() => { setResults(null); setQ(""); }}>clear</button>
                  </div>
                  {results.results.map((r) => (
                    <button key={r.path} onClick={() => setSel(r.path)} className="nav-item" style={{ width: "100%", textAlign: "left", flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
                      <span style={{ fontSize: 12.5, fontWeight: 600 }}>{r.title}</span>
                      <span className="faint" style={{ fontSize: 10.5, whiteSpace: "normal" }}>{r.snippet}</span>
                    </button>
                  ))}
                </div>
              ) : (
                folders.map((f) => (
                  <div key={f.name} style={{ padding: "6px 8px" }}>
                    <div className="faint" style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, padding: "6px 8px", display: "flex", alignItems: "center", gap: 6 }}>
                      <Icons.Folder size={12} /> {f.name} <span style={{ opacity: 0.6 }}>{f.count}</span>
                    </div>
                    {f.files.map((file) => (
                      <button key={file.path} onClick={() => setSel(file.path)}
                        className={"nav-item" + (sel === file.path ? " active" : "")}
                        style={{ width: "100%", textAlign: "left", fontSize: 12.5, padding: "6px 10px" }}>
                        <Icons.Doc size={13} /> <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{file.title}</span>
                      </button>
                    ))}
                  </div>
                ))
              )}
            </div>
            <div className="card card-pad" style={{ overflowY: "auto", minHeight: 0 }}>
              {note.loading && <window.LoadingRow label="Reading note…" />}
              {note.data && note.data.error && <div className="faint">{note.data.error}</div>}
              {note.data && note.data.content && (
                <div>
                  <div className="faint mono" style={{ fontSize: 11, marginBottom: 14 }}>{note.data.path}</div>
                  <BrainMd text={note.data.content} />
                </div>
              )}
            </div>
          </div>
        )}

        {/* RIGHT RAIL — learning + activity/undo */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: 0 }}>
          <LearnPanel onLearned={() => graph.refresh && graph.refresh()} />
          <BrainActivity onUndone={() => { graph.refresh && graph.refresh(); note.refresh && note.refresh(); }} />
        </div>
      </div>
    </div>
  );
}

window.BrainPage = BrainPage;
