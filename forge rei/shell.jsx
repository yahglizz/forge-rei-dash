// shell.jsx — Sidebar, Header, and small shared helpers
const { useState: useStateSh, useEffect: useEffectSh } = React;

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

function Logo() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
      <path d="M12 2 3 7v10l9 5 9-5V7z" stroke="#6f93ff" strokeWidth="1.5" strokeLinejoin="round"/>
      <path d="M12 7v10M8 9l8 6M16 9l-8 6" stroke="#4F7CFF" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}

function Sidebar({ active, onNav, goal, brand = "FORGE", sub = "REI OS", nav, showMarcus = true }) {
  const Icons = window.Icons;
  const items = nav || window.NAV;
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"><Logo /></div>
        <div>
          <div className="brand-name">{brand}</div>
          <div className="brand-sub">{sub}</div>
        </div>
      </div>

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

      {showMarcus && (
      <div className="sidebar-card">
        <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 14 }}>
          <div className="mini-avatar"><Icons.Bot size={20} /></div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 14 }}>Marcus AI</div>
            <div style={{ fontSize: 11.5, whiteSpace: "nowrap" }} className="faint">Acquisitions Manager</div>
            <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 5 }}>
              <span className="dot online pulse" /><span style={{ fontSize: 10.5, color: "var(--green)", fontWeight: 600 }}>ONLINE</span>
            </div>
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, marginBottom: 7 }}>
          <span className="faint">Monthly Goal</span>
        </div>
        <div className="progress"><div style={{ width: `${goal}%` }} /></div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginTop: 7 }}>
          <span className="faint">$0 / $50,000</span><span className="muted tabnum">{goal}%</span>
        </div>
      </div>
      )}
    </aside>
  );
}

function Header({ title, workspaces = [], current = {}, onSwitch = () => {} }) {
  const Icons = window.Icons;
  const [menu, setMenu] = useStateSh(false);
  return (
    <header className="header">
      <div className="search">
        <Icons.Search size={16} />
        <input placeholder="Search anything..." />
        <span className="kbd">⌘K</span>
      </div>

      <div style={{ flex: 1 }} />

      <div className="card" style={{ display: "flex", alignItems: "center", gap: 9, padding: "8px 13px", borderRadius: 12, whiteSpace: "nowrap" }}>
        <span style={{ color: "var(--green)" }}><Icons.Activity size={17} /></span>
        <div style={{ lineHeight: 1.25 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600 }}>AI Activity</div>
          <div style={{ fontSize: 11, color: "var(--green)", display: "flex", alignItems: "center", gap: 4 }}>
            <span className="dot online pulse" /> Live
          </div>
        </div>
      </div>

      <div style={{ lineHeight: 1.25, padding: "0 6px", whiteSpace: "nowrap" }}>
        <div style={{ fontSize: 11.5 }} className="faint">Revenue (This Month)</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--green)" }} className="tabnum">$0.00</div>
      </div>

      <button className="card" style={{ width: 42, height: 42, display: "grid", placeItems: "center", borderRadius: 12, position: "relative" }}>
        <Icons.Bell size={18} />
        <span style={{ position: "absolute", top: 7, right: 8, background: "var(--red)", color: "#fff", fontSize: 9.5, fontWeight: 700, borderRadius: 999, minWidth: 15, height: 15, display: "grid", placeItems: "center", padding: "0 3px" }}>3</span>
      </button>

      <div style={{ position: "relative" }}>
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
              <div className="faint" style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", padding: "6px 8px 8px" }}>Workspaces</div>
              {workspaces.map((w) => (
                <button key={w.id} onClick={() => { onSwitch(w.id); setMenu(false); }}
                  style={{ display: "flex", alignItems: "center", gap: 11, width: "100%", padding: "9px 8px", borderRadius: 10, background: w.id === current.id ? "var(--card-2)" : "transparent", textAlign: "left" }}>
                  <div style={{ width: 32, height: 32, borderRadius: 9, background: "radial-gradient(circle at 40% 35%, " + w.accent + ", #16224a)", display: "grid", placeItems: "center", flexShrink: 0 }}>
                    <Logo />
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
