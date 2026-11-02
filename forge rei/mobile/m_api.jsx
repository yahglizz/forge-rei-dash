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
  const seqRefMX = useRefMX(0);
  const load = async () => {
    const mySeq = ++seqRefMX.current;
    try {
      const r = await fetch(path);
      const j = await r.json();
      if (!aliveMX.current || seqRefMX.current !== mySeq) return;
      setData(j);
      setError(j && j.error ? j.error : null);
    } catch (e) {
      if (aliveMX.current && seqRefMX.current === mySeq) setError(e.message || "network error");
    } finally {
      if (aliveMX.current && seqRefMX.current === mySeq) setLoading(false);
    }
  };
  useEffectMX(() => {
    ++seqRefMX.current;
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

// opts.timeoutMs: abort after this long (default 120 s, a reply draft can run long; chat turns pass 330 s, the gateway's cap).
// A card tap (/api/chat/action/) gets 330 s too: a Mac command waits up to 125 s and a batch card runs its calls in
// order, so a tap that worked must not read "No answer in time" with no retry.
// opts.signal: the caller's AbortSignal (a Cancel button). A timeout throws Error(code "timeout"),
// a cancel throws Error(code "cancelled"); the server may still finish the work either way.
async function apiPostM(path, body, opts) {
  opts = opts || {};
  const ctl = new AbortController();
  let why = "";
  const timer = setTimeout(() => { why = "timeout"; ctl.abort(); }, opts.timeoutMs || (String(path).indexOf("/api/chat/action/") === 0 ? 330000 : 120000));
  const onCancel = () => { why = why || "cancelled"; ctl.abort(); };
  if (opts.signal) { if (opts.signal.aborted) onCancel(); else opts.signal.addEventListener("abort", onCancel); }
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      signal: ctl.signal,
    });
    const j = await r.json().catch((e) => { if (why) throw e; return {}; });
    if (!r.ok || (j && j.error)) { hapticM("error"); throw new Error((j && j.error) || ("HTTP " + r.status)); }
    hapticM("success");
    if (window.ForgeLiveSync) window.ForgeLiveSync.signal(path);
    return j;
  } catch (e) {
    if (why) {
      const err = new Error(why === "timeout" ? "No answer in time" : "Cancelled");
      err.code = why;
      hapticM("error");
      throw err;
    }
    throw e;
  } finally {
    clearTimeout(timer);
    if (opts.signal) opts.signal.removeEventListener("abort", onCancel);
  }
}

// Native iOS shell (ios/ForgeMobile) exposes a haptic bridge; a no-op in Safari/PWA.
function hapticM(kind) {
  try { window.webkit.messageHandlers.forgeHaptic.postMessage(kind || "tap"); } catch (_) {}
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

Object.assign(window, { useApiM, apiPostM, fmtMoneyM, timeAgoM, hapticM });
