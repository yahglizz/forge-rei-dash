// api.jsx — live data layer. Talks to the local GHL connector (same origin).
const { useState: useStateApi, useEffect: useEffectApi, useRef: useRefApi, useCallback: useCallbackApi } = React;

async function apiGet(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || data.error || "";
    throw new Error(`${res.status} ${detail}`.trim());
  }
  if (data.error) throw new Error(data.error);
  return data;
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `${res.status}`);
  if (window.ForgeLiveSync) window.ForgeLiveSync.signal(path);
  return data;
}

// useApi(path, { interval }) — fetch on mount, optional polling, manual refresh.
function useApi(path, opts = {}) {
  const { interval = 0 } = opts;
  const [data, setData] = useStateApi(null);
  const [error, setError] = useStateApi(null);
  const [loading, setLoading] = useStateApi(true);
  const [refreshedAt, setRefreshedAt] = useStateApi(null);
  const mounted = useRefApi(true);
  const requestSeq = useRefApi(0);

  const load = useCallbackApi(async (silent) => {
    const requestId = ++requestSeq.current;
    if (!silent) setLoading(true);
    try {
      const d = await apiGet(path);
      if (!mounted.current || requestId !== requestSeq.current) return;
      setData(d);
      setError(null);
      setRefreshedAt(new Date());
    } catch (e) {
      if (mounted.current && requestId === requestSeq.current) {
        setError(e.message || String(e));
      }
    } finally {
      if (mounted.current && requestId === requestSeq.current) setLoading(false);
    }
  }, [path]);

  useEffectApi(() => {
    mounted.current = true;
    load(false);
    const unsubscribe = window.ForgeLiveSync
      ? window.ForgeLiveSync.subscribe(() => load(true)) : null;
    let timer;
    if (interval > 0) timer = setInterval(() => load(true), interval);
    return () => {
      mounted.current = false;
      requestSeq.current += 1;
      if (timer) clearInterval(timer);
      if (unsubscribe) unsubscribe();
    };
  }, [path, interval]);

  return { data, error, loading, refreshedAt, refresh: () => load(true) };
}

function fmtMoney(n) {
  const v = Number(n || 0);
  return "$" + v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function timeAgo(ts) {
  if (!ts) return "—";
  const d = typeof ts === "number" ? new Date(ts) : new Date(ts);
  if (isNaN(d)) return "—";
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}

function LoadingRow({ label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 9, padding: 14 }} className="faint">
      <span className="dot online pulse" /> {label || "Loading from GoHighLevel…"}
    </div>
  );
}

function ErrorRow({ error, onRetry }) {
  const Icons = window.Icons;
  return (
    <div className="card" style={{ padding: 16, borderColor: "var(--red)", display: "flex", alignItems: "center", gap: 12 }}>
      <span style={{ color: "var(--red)" }}><Icons.Activity size={18} /></span>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600 }}>Couldn’t reach GoHighLevel</div>
        <div className="faint mono" style={{ fontSize: 12 }}>{error}</div>
      </div>
      {onRetry && <button className="tab" onClick={onRetry}>Retry</button>}
    </div>
  );
}

Object.assign(window, { useApi, apiGet, apiPost, fmtMoney, timeAgo, LoadingRow, ErrorRow });
