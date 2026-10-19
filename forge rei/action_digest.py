"""action_digest.py — "what did the agents do" over action_log. Zero Claude, read-only.

digest(hours=24) -> per agent: totals, ok/failed, counts by trigger (chat_auto = ran by itself
in a dashboard chat, dash_tap / telegram_tap = the owner's ✅), the latest items, and an `undo`
hint wherever the write has a known inverse (tag add ↔ remove, dismiss ↔ undismiss …).
GET /api/actions/digest?hours=24 (hq scope — every agent can read it). Spec 2026-10-18 P0(e).
Test: python3 test_action_digest.py
"""
import time

import action_log

# Known inverses, keyed by the route the action ran. A hint, not a button: the log keeps ids +
# outcome only (no bodies), so the agent/owner re-reads the item's ref for the exact args.
# ponytail: record the AUTO tag body in the log if undo should become one exact tap.
INVERSE = {
    "/api/daycare/ghl/tag": {"path": "/api/daycare/ghl/tag",
                             "how": "same contact_id with add ↔ remove swapped"},
    "/api/daycare/ghl/dismiss": {"path": "/api/daycare/ghl/undismiss", "how": "same id"},
    "/api/daycare/ghl/undismiss": {"path": "/api/daycare/ghl/dismiss", "how": "same id"},
    "/api/hub/task": {"path": "/api/hub/task/update", "how": "{id, status: 'dismissed'}"},
    "/api/daycare/leads/stage": {"path": "/api/daycare/leads/stage", "how": "mark the previous stage"},
    "/api/scout/apply": {"path": "/api/scout/remove",
                         "how": "pulls the hot tags (also marks the opportunity Lost — a ✅ card)"},
}
MAX_LATEST = 5
SCAN = 500          # action_log.recent() ceiling


def _path(action):
    """'chat:/api/x' / 'partner:/api/x' -> '/api/x'; anything else (sms_send, …) -> None."""
    _, _, rest = str(action or "").partition(":")
    return rest if rest.startswith("/api/") else None


def digest(hours=24):
    try:
        hours = max(1, min(int(hours), 168))
    except (TypeError, ValueError):
        hours = 24
    now = int(time.time() * 1000)
    since = now - hours * 3600 * 1000
    scanned = action_log.recent(SCAN)                 # newest first
    rows = [r for r in scanned if int(r.get("ts") or 0) >= since]
    agents = {}
    for r in rows:
        a = agents.setdefault(r.get("agent") or "unknown",
                              {"total": 0, "ok": 0, "failed": 0, "byTrigger": {}, "latest": []})
        ok = bool(r.get("ok"))
        a["total"] += 1
        a["ok" if ok else "failed"] += 1
        trig = r.get("trigger") or "other"
        a["byTrigger"][trig] = a["byTrigger"].get(trig, 0) + 1
        if len(a["latest"]) < MAX_LATEST:
            path = _path(r.get("action"))
            item = {"ts": r.get("ts"), "trigger": trig, "summary": r.get("ref") or r.get("action"),
                    "path": path, "business": r.get("business"), "ok": ok}
            if not ok:
                item["error"] = r.get("error")
            elif path in INVERSE:
                item["undo"] = INVERSE[path]
            a["latest"].append(item)
    return {"ok": True, "hours": hours, "since": since, "count": len(rows), "agents": agents,
            # every scanned line is inside the window → older in-window lines may be missing
            "truncated": len(scanned) >= SCAN and len(rows) == len(scanned), "generatedAt": now}
