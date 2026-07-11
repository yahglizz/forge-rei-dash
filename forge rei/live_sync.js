// Shared live-sync bridge for the desktop dashboard and mobile app.
// The two frontends stay separate, but subscribe to the same connector revision
// and broadcast local writes across tabs/windows when the browser supports it.
(function () {
  const listeners = new Set();
  let timer = null;
  let inFlight = false;
  let serverVersion = null;
  let channel = null;

  try {
    if (typeof BroadcastChannel !== "undefined") {
      channel = new BroadcastChannel("forge-rei-live-sync");
      channel.onmessage = (event) => {
        if (event && event.data && event.data.type === "forge-sync") {
          notify(event.data);
        }
      };
    }
  } catch (_) {
    channel = null;
  }

  function notify(payload) {
    listeners.forEach((listener) => {
      try { listener(payload || {}); } catch (_) { /* one subscriber must not block the rest */ }
    });
  }

  async function check() {
    if (inFlight || !listeners.size) return;
    inFlight = true;
    try {
      const response = await fetch("/api/sync", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) return;
      const data = await response.json();
      const next = String(data.version || "");
      if (serverVersion === null) {
        serverVersion = next;
      } else if (next && next !== serverVersion) {
        serverVersion = next;
        notify({ type: "forge-sync", source: "server", ...data });
      }
    } catch (_) {
      // Existing endpoint polling remains responsible for rendering errors.
    } finally {
      inFlight = false;
    }
  }

  function start() {
    if (timer) return;
    check();
    timer = setInterval(check, 2000);
  }

  function stop() {
    if (!timer || listeners.size) return;
    clearInterval(timer);
    timer = null;
    serverVersion = null;
  }

  function subscribe(listener) {
    if (typeof listener !== "function") return () => {};
    listeners.add(listener);
    start();
    return () => {
      listeners.delete(listener);
      stop();
    };
  }

  function signal(reason) {
    const payload = {
      type: "forge-sync",
      source: "client",
      reason: reason || "write",
      at: Date.now(),
    };
    notify(payload);
    try { if (channel) channel.postMessage(payload); } catch (_) { /* optional */ }
    try {
      localStorage.setItem("forge-rei-live-sync", JSON.stringify(payload));
    } catch (_) { /* optional */ }
  }

  try {
    window.addEventListener("storage", (event) => {
      if (event.key !== "forge-rei-live-sync" || !event.newValue) return;
      try { notify(JSON.parse(event.newValue)); } catch (_) { /* optional */ }
    });
  } catch (_) { /* non-browser test harness */ }

  window.ForgeLiveSync = { subscribe, signal, check };
})();
