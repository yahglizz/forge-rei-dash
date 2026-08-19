// shell.jsx — Sidebar, Header, and small shared helpers
const { useState: useStateSh, useEffect: useEffectSh, useRef: useRefSh } = React;

function CountUp({ to, prefix = "", dur = 900 }) {
  const [n, setN] = useStateSh(0);
  useEffectSh(() => {
    if (to === 0) { setN(0); return; }
    let raf, start;
    const step = (t) => {
      if (!start) start = t;
      const p = Math.min((t - start) / dur, 1);
      setN(Math.round((1 - Math.pow(1 - p, 3)) * to));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to]);
  return <span className="tabnum">{prefix}{n.toLocaleString()}</span>;
}

function Logo({ accent = "#4F7CFF" }) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
      <path d="M12 2 3 7v10l9 5 9-5V7z" stroke={accent} strokeOpacity=".72" strokeWidth="1.5" strokeLinejoin="round"/>
      <path d="M12 7v10M8 9l8 6M16 9l-8 6" stroke={accent} strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}

function Sidebar({ active, onNav, goal, brand = "FORGE", sub = "REI OS", nav, showMarcus = true, accent = "#4F7CFF", onHome }) {
  const Icons = window.Icons;
  const items = nav || window.NAV;
  return (
    <aside className="sidebar">
      <button className="brand" onClick={() => onHome && onHome()} title="Back to Mission Control"
        style={{ width: "100%", textAlign: "left", cursor: onHome ? "pointer" : "default", background: "transparent" }}>
        <div className="brand-mark" style={{ boxShadow: "0 0 0 1px " + accent + "40, 0 12px 32px -14px " + accent }}><Logo accent={accent} /></div>
        <div>
          <div className="brand-name">{brand}</div>
          <div className="brand-sub">{sub}</div>
        </div>
      </button>

      <nav className="nav">
        {items.map(([key, label]) => {
          const Ico = Icons[key] || Icons.Dashboard;
          return (
            <button key={key} className={"nav-item" + (active === key ? " active" : "")} onClick={() => onNav(key)}>
              <Ico size={18} />
              <span>{label}</span>
            </button>
          );
        })}
      </nav>

    </aside>
  );
}

function Header({ title, workspaces = [], current = {}, onSwitch = () => {}, onNavigate = () => {}, onHome }) {
  const Icons = window.Icons;
  const [menu, setMenu] = useStateSh(false);
  const [search, setSearch] = useStateSh("");
  const searchRef = useRefSh(null);
  const daycare = current.id === "daycare";
  const [daycareCount, setDaycareCount] = useStateSh(0);
  const [daycareSession, setDaycareSession] = useStateSh(null);
  useEffectSh(() => {
    if (!daycare) return;
    const receive = (event) => setDaycareSession(event.detail || null);
    window.addEventListener("forge-daycare-session", receive);
    return () => window.removeEventListener("forge-daycare-session", receive);
  }, [daycare]);
  useEffectSh(() => {
    if (!daycare || !daycareSession || !daycareSession.authenticated) return;
    let active = true;
    const syncDaycareCount = async () => {
      try {
        const response = await fetch("/api/daycare/overview", { credentials: "same-origin", cache: "no-store" });
        const payload = await response.json();
        if (active && response.ok) setDaycareCount(Number((payload.metrics || {}).childrenActive || 0));
      } catch (_) { if (active) setDaycareCount(0); }
    };
    syncDaycareCount();
    const timer = window.setInterval(syncDaycareCount, 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [daycare, daycareSession && daycareSession.authenticated]);
  useEffectSh(() => {
    const onKeyDown = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current && searchRef.current.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
  const runSearch = () => {
    const needle = search.trim().toLowerCase();
    if (!needle) return;
    const hit = (current.nav || []).find(([key, label]) =>
      key.toLowerCase().includes(needle) || label.toLowerCase().includes(needle));
    if (hit) {
      onNavigate(hit[0]);
      setSearch("");
    }
  };
  return (
    <header className="header">
      <div className="search">
        <Icons.Search size={16} />
        <input ref={searchRef} value={search} onChange={(event) => setSearch(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && runSearch()}
          placeholder="Go to a page..." aria-label="Go to a page" />
        <span className="kbd">⌘K</span>
      </div>

      <div style={{ flex: 1 }} />

      {daycare && <div className="card header-status" style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 13px", borderRadius: 12, whiteSpace: "nowrap" }}>
        <span style={{ color: (!daycareSession || !daycareSession.authenticated) ? "var(--orange)" : "var(--green)" }}><Icons.Activity size={17} /></span>
        <div style={{ lineHeight: 1.25 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600 }}>Center Status</div>
          <div style={{ fontSize: 11, color: "var(--green)", display: "flex", alignItems: "center", gap: 4 }}>
            <span className={"dot " + ((!daycareSession || !daycareSession.authenticated) ? "" : "online pulse")} /> {daycareSession && daycareSession.authenticated ? "Supabase live" : "Secure sign-in required"}
          </div>
        </div>
      </div>}

      {daycare && <div className="header-metric" style={{ lineHeight: 1.25, padding: "0 6px", whiteSpace: "nowrap" }}>
        <div style={{ fontSize: 11.5 }} className="faint">Children Enrolled</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: current.accent || "var(--green)" }} className="tabnum">{daycareSession && daycareSession.authenticated ? daycareCount : "—"}</div>
      </div>}

      {daycare && <button className="card header-bell" onClick={() => onNavigate("Announcements")} title="Open announcements" style={{ width: 42, height: 42, display: "grid", placeItems: "center", borderRadius: 12 }}>
        <Icons.Bell size={18} />
      </button>}

      <div className="header-profile" style={{ position: "relative" }}>
        <button onClick={() => setMenu((m) => !m)} style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 38, height: 38, borderRadius: 11, background: "radial-gradient(circle at 40% 35%, " + (current.accent || "#5b7bff") + ", #16224a)", display: "grid", placeItems: "center", fontWeight: 700, fontSize: 14 }}>Y</div>
          <div style={{ lineHeight: 1.2, textAlign: "left" }}>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>Yahjair</div>
            <div style={{ fontSize: 11, color: "var(--orange)", fontWeight: 600, display: "flex", alignItems: "center", gap: 4, whiteSpace: "nowrap" }}>
              <Icons.Spark size={11} /> {(current.brand || "FORGE") + " " + (current.sub || "")}
            </div>
          </div>
          <span className="faint"><Icons.Chevron size={16} /></span>
        </button>

        {menu && (
          <>
            <div onClick={() => setMenu(false)} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
            <div className="card" style={{ position: "absolute", right: 0, top: "calc(100% + 8px)", width: 248, padding: 8, zIndex: 50, borderRadius: 14 }}>
              {onHome && (
                <button onClick={() => { onHome(); setMenu(false); }}
                  style={{ display: "flex", alignItems: "center", gap: 11, width: "100%", padding: "9px 8px", borderRadius: 10, background: "transparent", textAlign: "left", marginBottom: 2 }}>
                  <div style={{ width: 32, height: 32, borderRadius: 9, background: "var(--card-2)", display: "grid", placeItems: "center", flexShrink: 0 }}>
                    <Icons.Activity size={17} />
                  </div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>Mission Control</div>
                    <div className="faint" style={{ fontSize: 11 }}>All businesses overview</div>
                  </div>
                </button>
              )}
              <div className="faint" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", padding: "6px 8px 8px" }}>Workspaces</div>
              {workspaces.map((w) => (
                <button key={w.id} onClick={() => { onSwitch(w.id); setMenu(false); }}
                  style={{ display: "flex", alignItems: "center", gap: 11, width: "100%", padding: "9px 8px", borderRadius: 10, background: w.id === current.id ? "var(--card-2)" : "transparent", textAlign: "left" }}>
                  <div style={{ width: 32, height: 32, borderRadius: 9, background: "radial-gradient(circle at 40% 35%, " + w.accent + ", #16224a)", display: "grid", placeItems: "center", flexShrink: 0 }}>
                    <Logo accent={w.accent} />
                  </div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{w.brand} {w.sub}</div>
                    <div className="faint" style={{ fontSize: 11 }}>{w.tag}</div>
                  </div>
                  {w.id === current.id && <span style={{ color: "var(--green)" }}><Icons.Check size={15} /></span>}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </header>
  );
}

Object.assign(window, { CountUp, Sidebar, Header, Logo });
