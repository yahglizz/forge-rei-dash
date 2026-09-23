// FORGE Mobile — shell: icons, header, tab bar, shared UI atoms.
// Hook aliases for this file: MSH. Exports: MIcons, MHeader, MTabBar, MCard,
// MBtn, MChip, MEmpty, MSpin.
const { useState: useStateMSH } = React;

function MIco(props) {
  const s = props.size || 20;
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={props.sw || 1.9} strokeLinecap="round" strokeLinejoin="round">
      {props.children}
    </svg>
  );
}

// Original FORGE house mascot, generated for this mobile UI.
function MForgePal(props) {
  const size = props.size || 42;
  return <img className="m-forge-pal" src="forge-house-mascot.png" width={size} height={size}
    alt="" aria-hidden="true" />;
}

const MIcons = {
  Home: (p) => <MIco {...p}><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V21h14V9.5" /></MIco>,
  Chat: (p) => <MIco {...p}><path d="M21 12a8 8 0 0 1-8 8H4l1.7-3.4A8 8 0 1 1 21 12z" /></MIco>,
  Board: (p) => <MIco {...p}><rect x="3" y="4" width="5" height="16" rx="1.5" /><rect x="10" y="4" width="5" height="10" rx="1.5" /><rect x="17" y="4" width="4" height="13" rx="1.5" /></MIco>,
  Calc: (p) => <MIco {...p}><rect x="4" y="2.5" width="16" height="19" rx="2.5" /><path d="M8 7h8" /><path d="M8 12h.01M12 12h.01M16 12h.01M8 16h.01M12 16h.01M16 16h.01" /></MIco>,
  Bot: (p) => <MIco {...p}><rect x="4" y="7" width="16" height="12" rx="3" /><path d="M12 7V3.5" /><circle cx="9" cy="13" r="1" /><circle cx="15" cy="13" r="1" /></MIco>,
  More: (p) => <MIco {...p}><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></MIco>,
  Send: (p) => <MIco {...p}><path d="m22 2-7 20-4-9-9-4z" /><path d="M22 2 11 13" /></MIco>,
  Check: (p) => <MIco {...p}><path d="M20 6 9 17l-5-5" /></MIco>,
  X: (p) => <MIco {...p}><path d="M18 6 6 18M6 6l12 12" /></MIco>,
  Flame: (p) => <MIco {...p}><path d="M12 2s5 4.5 5 9a5 5 0 0 1-10 0c0-1.5.5-3 1.5-4.5C9 8 10 9 11 9c0-3 1-5.5 1-7z" /></MIco>,
  Search: (p) => <MIco {...p}><circle cx="11" cy="11" r="7" /><path d="m21 21-4-4" /></MIco>,
  Back: (p) => <MIco {...p}><path d="M15 18 9 12l6-6" /></MIco>,
  Refresh: (p) => <MIco {...p}><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 3v6h-6" /></MIco>,
  Dollar: (p) => <MIco {...p}><path d="M12 2v20" /><path d="M17 5.5H9.5a3 3 0 0 0 0 6h5a3 3 0 0 1 0 6H6.5" /></MIco>,
  User: (p) => <MIco {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.5-6 8-6s8 2 8 6" /></MIco>,
  Phone: (p) => <MIco {...p}><path d="M5 3h4l2 5-2.5 1.5a12 12 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A17 17 0 0 1 3 5a2 2 0 0 1 2-2z" /></MIco>,
  Pause: (p) => <MIco {...p}><rect x="6" y="4" width="4" height="16" rx="1" /><rect x="14" y="4" width="4" height="16" rx="1" /></MIco>,
  Play: (p) => <MIco {...p}><path d="m6 4 14 8-14 8z" /></MIco>,
  Doc: (p) => <MIco {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></MIco>,
  Brain: (p) => <MIco {...p}><circle cx="12" cy="12" r="3" /><circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="5" cy="18" r="2" /><circle cx="19" cy="18" r="2" /><path d="M9.8 10.4 6.6 7.4M14.2 10.4l3.2-3M9.8 13.6l-3.2 3M14.2 13.6l3.2 3" /></MIco>,
  Heart: (p) => <MIco {...p}><path d="M12 21S4 14.5 4 9a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 9c0 5.5-8 12-8 12z" /></MIco>,
  Swap: (p) => <MIco {...p}><path d="M7 4 3 8l4 4" /><path d="M3 8h14" /><path d="m17 12 4 4-4 4" /><path d="M21 16H7" /></MIco>,
};

function MHeader(props) {
  // Business mode (m_app.jsx) only: a classic page opened inside a business gets a back
  // arrow (window.mBizBack); ⇄ returns to the portal (window.mSwitchBiz). Both unset in
  // the classic app, so it renders exactly as before.
  const onBack = props.onBack || window.mBizBack || null;
  return (
    <div className="m-head">
      {!onBack && (window.mSwitchBiz
        ? <button className="m-mascot mlg-mascot-switch" onClick={() => window.mSwitchBiz()}
            aria-label={"Switch business" + (window.mBizActive ? " (now " + window.mBizActive + ")" : "")}>
            <MForgePal size={40} /><span className="mlg-switch-badge"><MIcons.Swap size={12} /></span>
          </button>
        : <div className="m-mascot"><MForgePal size={40} /></div>)}
      {onBack && (
        <button className="m-tab" style={{ flex: "none", padding: 4 }} onClick={onBack}>
          <MIcons.Back size={22} />
        </button>
      )}
      <div className="m-head-copy">
        <div className="m-head-title">
          {props.title}
        </div>
        {props.sub && <div className="m-head-sub">{props.sub}</div>}
      </div>
      {!onBack && <button className="mw-header-bot" onClick={() => window.mGoTab && window.mGoTab("agents")} aria-label="Open agents">🤖</button>}
      {props.right || null}
    </div>
  );
}

const M_TABS = [
  { key: "today", label: "Today", ico: "Home" },
  { key: "wholesale", label: "Wholesale", ico: "Board" },
  { key: "agency", label: "Agency", ico: "Phone" },
  { key: "daycare", label: "Daycare", ico: "Heart" },
  { key: "more", label: "More", ico: "More" },
];

function MTabBar(props) {
  return (
    <div className="m-tabbar">
      {(props.tabs || M_TABS).map((t) => {
        const Ico = MIcons[t.ico] || MIcons.More;
        return (
          <button key={t.key} className={"m-tab" + (props.tab === t.key ? " active" : "")}
            onClick={() => props.onTab(t.key)}>
            <Ico size={21} />
            <span>{t.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function MCard(props) {
  return (
    <div className="m-card" style={props.style}>
      {props.title && (
        <div className="m-row" style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, flex: 1 }}>{props.title}</div>
          {props.right || null}
        </div>
      )}
      {props.children}
    </div>
  );
}

function MBtn(props) {
  return (
    <button className={"m-btn" + (props.kind ? " " + props.kind : "")}
      onClick={props.onClick} disabled={props.disabled} style={props.style}>
      {props.children}
    </button>
  );
}

function MChip(props) {
  return (
    <button className={"m-chip" + (props.active ? " active" : "")} onClick={props.onClick}>
      {props.children}
    </button>
  );
}

function MEmpty(props) {
  return (
    <div className="m-empty">
      <MForgePal size={62} />
      <div style={{ fontSize: 13, fontWeight: 600 }}>{props.title || "Nothing here"}</div>
      {props.sub && <div className="m-fade" style={{ marginTop: 4 }}>{props.sub}</div>}
    </div>
  );
}

function MSpin() {
  return <div className="m-fade" style={{ textAlign: "center", padding: 20 }}>Loading…</div>;
}

Object.assign(window, { MIcons, MHeader, MTabBar, MCard, MBtn, MChip, MEmpty, MSpin, M_TABS, MForgePal });
