// FORGE Mobile — data layer. Same-origin /api/* (identical endpoints to the
// desktop dashboard; no keys in the app — the connector holds all secrets).
// Hook aliases for this file: MX. Exports: useApiM, apiPostM, fmtMoneyM, timeAgoM.
const { useState: useStateMX, useEffect: useEffectMX, useRef: useRefMX } = React;

function useApiM(path, opts) {
  opts = opts || {};
  const [data, setData] = useStateMX(null);
  const [error, setError] = useStateMX(null);
  const [loading, setLoading] = useStateMX(true);
  const aliveMX = useRefMX(true);
  const load = async () => {
    try {
      const r = await fetch(path);
      const j = await r.json();
      if (!aliveMX.current) return;
      setData(j);
      setError(j && j.error ? j.error : null);
    } catch (e) {
      if (aliveMX.current) setError(e.message || "network error");
    } finally {
      if (aliveMX.current) setLoading(false);
    }
  };
  useEffectMX(() => {
    aliveMX.current = true;
    setLoading(true);
    load();
    const unsubscribe = window.ForgeLiveSync
      ? window.ForgeLiveSync.subscribe(() => load()) : null;
    const iv = opts.interval ? setInterval(load, opts.interval) : null;
    return () => {
      aliveMX.current = false;
      if (iv) clearInterval(iv);
      if (unsubscribe) unsubscribe();
    };
  }, [path]);
  return { data, error, loading, refresh: load };
}

async function apiPostM(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || (j && j.error)) throw new Error((j && j.error) || ("HTTP " + r.status));
  if (window.ForgeLiveSync) window.ForgeLiveSync.signal(path);
  return j;
}

function fmtMoneyM(n) {
  const x = Number(n);
  if (n === null || n === undefined || isNaN(x)) return "—";
  return "$" + Math.round(x).toLocaleString();
}

function timeAgoM(ts) {
  if (!ts) return "";
  const ms = typeof ts === "number" ? ts : Date.parse(ts);
  if (isNaN(ms)) return "";
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return "now";
  if (s < 3600) return Math.floor(s / 60) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  return Math.floor(s / 86400) + "d";
}

Object.assign(window, { useApiM, apiPostM, fmtMoneyM, timeAgoM });
