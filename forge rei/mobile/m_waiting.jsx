// FORGE Mobile — Crew > "Waiting on you": every still-open dashboard tap card from every business, at the top
// of Crew, so a card made in another chat, another tab or a Run now job is never out of sight.
// GET /api/chat/waiting → {cards: [{tok, agent, business, summary, kind: "mac"|"write", command, reason, why,
// warning, risk, count, preview, ts, expiresIn, redacted}]}, newest first. Each row IS the in-chat card
// (window.ChatActions → POST /api/chat/action/confirm|cancel {tok}): no second approval path.
// A Mac card whose command was redacted gets no ✅ here: he must read every character, so he opens the full card.
// Refresh: on open, every 20 s while the page is visible, and when the page comes back into view.
// Hook aliases for this file: WY. Exports: MAWaitingCard.
const { useEffect: useEffectWY, useRef: useRefWY } = React;
const WY_POLL_MS = 20000;

function wyName(id) {
  const s = String(id || "agent");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function wyLeft(s) {
  const m = Math.ceil(Math.max(0, s) / 60);
  return m <= 1 ? "under a minute left" : m + " min left";
}

function WYHidden({ c }) {
  return (
    <div style={{ marginTop: 6, padding: "9px 11px", borderRadius: 10, fontSize: 12.5, lineHeight: 1.45,
      border: "1px solid var(--border, rgba(127,127,127,.4))", overflowWrap: "anywhere" }}>
      <b>{String(c.summary || "Run on your Mac")}</b>
      <div role="alert" style={{ color: "#ef4444", fontWeight: 700, marginTop: 6 }}>⚠️ {String(c.warning || "")}</div>
      <pre style={{ margin: "6px 0 0", whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 11.5 }}>{String(c.command || "")}</pre>
      <div style={{ marginTop: 6 }}>
        Part of this command looks like a key, so it is hidden here and there is no ✅ on this list.
        Open {wyName(c.agent)}'s chat in the {String(c.business || "")} Crew to read every character before you run it.
        Left alone, it expires on its own.
      </div>
    </div>
  );
}

function MAWaitingCard({ hide }) {   // hide = toks already on screen in the open chat: one copy, one ✅
  const w = window.useApiM("/api/chat/waiting");
  const rowsRefWY = useRefWY({});      // tok -> {c, until, live, tapped}: a card tapped here keeps its result until it expires
  const dataRefWY = useRefWY(null);

  useEffectWY(() => {
    const tick = () => { if (document.visibilityState === "visible") w.refresh(); };
    const iv = setInterval(tick, WY_POLL_MS);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(iv); document.removeEventListener("visibilitychange", tick); };
  }, []);

  const now = Date.now() / 1000;
  const rows = rowsRefWY.current;
  const list = w.data && Array.isArray(w.data.cards) ? w.data.cards : null;
  if (list && w.data !== dataRefWY.current) {   // a fresh answer from the box: it is the truth for open cards
    dataRefWY.current = w.data;
    const live = {};
    list.forEach((c) => { if (c && c.tok) live[c.tok] = c; });
    Object.keys(rows).forEach((k) => {
      if (live[k]) return;
      if (rows[k].tapped) rows[k].live = false; else delete rows[k];   // gone elsewhere (tapped, cancelled) → row goes
    });
    Object.keys(live).forEach((k) => {
      rows[k] = { c: live[k], until: now + (Number(live[k].expiresIn) || 0), live: true, tapped: !!(rows[k] && rows[k].tapped) };
    });
  }
  Object.keys(rows).forEach((k) => { if (!(rows[k].until > now)) delete rows[k]; });   // expired → row disappears

  const shown = Object.keys(rows).map((k) => rows[k]).filter((r) => !(hide || []).includes(r.c.tok)).sort((a, b) => (Number(b.c.ts) || 0) - (Number(a.c.ts) || 0));
  const n = shown.filter((r) => r.live).length;
  window.MAWaitingN = n;               // m_agents reads it: with cards waiting, opening Crew stays at the top
  const toppedRefWY = useRefWY(false);
  useEffectWY(() => {                  // the chat may have scrolled down before this list loaded: once per open, go up
    if (n > 0 && !toppedRefWY.current) {
      toppedRefWY.current = true;
      document.querySelectorAll(".m-content").forEach((el) => { el.scrollTop = 0; });
      window.scrollTo(0, 0);
    }
  }, [n > 0]);
  if (!shown.length) return null;
  return (
    <window.MCard title={n ? "Waiting on you (" + n + ")" : "Waiting on you: all answered"}
      right={<button className="m-tab" style={{ flex: "none", minWidth: 44, minHeight: 44, padding: 4 }}
        aria-label="Refresh waiting cards" onClick={w.refresh}><window.MIcons.Refresh size={18} /></button>}>
      <div className="m-fade" style={{ fontSize: 12 }}>
        Every card an agent is waiting on, from any chat. Nothing runs until you tap ✅.
      </div>
      <div className="m-cards" style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 6 }}>
        {shown.map((r) => {
          const c = r.c;
          return (
            <div key={c.tok} onClickCapture={(e) => {
              if (e.target && e.target.closest && e.target.closest("button") && rows[c.tok]) rows[c.tok].tapped = true;
            }}>
              <div className="m-fade" style={{ fontSize: 11.5 }}>
                {wyName(c.agent)}{c.business ? " · " + c.business : ""} · {wyLeft(r.until - now)}
              </div>
              {c.kind === "mac" && c.redacted
                ? <WYHidden c={c} />
                : window.ChatActions ? <window.ChatActions actions={[c]} /> : null}
            </div>
          );
        })}
      </div>
    </window.MCard>
  );
}

Object.assign(window, { MAWaitingCard });
