"""agency_approvals_io.py — central Approval Center queue (Forge AI Agency).

One queue that aggregates everything waiting on YOUR sign-off:
  - Dyson edit drafts          (kind="dyson")
  - n8n workflow draft edits   (kind="workflow")
  - Eco ad recommendations     (kind="eco")

Generators (agency_dyson / agency_eco / agency_workflows_io) call add() to push
an item here. The Approval Center UI lists the queue and POSTs a decision
(approve / revise / reject) back through decide().

Store: marcus_state/agency_approvals.json. Mirrors agency_io.py pattern.
This is the single human-in-the-loop gate — nothing an agent drafts goes live
until it is approved here. (Wiring the "live" side is future work; see
AGENCY_DASHBOARD_FEATURES.md.)
"""
import forge_atomic
import json
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_approvals.json"
_LOCK = threading.Lock()

KINDS = ["dyson", "workflow", "eco", "social"]
ACTIONS = {"approve": "approved", "revise": "revision", "reject": "rejected"}
STATUSES = ["pending", "approved", "revision", "rejected", "failed"]

_NOW = int(time.time() * 1000)

# --- MOCK SEED so the Approval Center is explorable on first load -----------
_SEED = {
    "seq": 2,
    "queue": [
        {
            "id": "a1", "kind": "dyson", "refId": "seed-d1",
            "title": "Dyson: Swap homepage hero — Bloom Dental",
            "summary": "Replace hero image + headline on index. 1 file, low risk.",
            "client": "Bloom Dental", "risk": "low",
            "payload": {"affected": ["index.html"], "steps": [
                "Backup current hero block",
                "Swap <img> src + alt",
                "Update H1 copy",
                "Preview, then publish"]},
            "status": "pending",
            "createdAt": _NOW - 3600 * 1000, "decidedAt": None,
        },
        {
            "id": "a2", "kind": "eco", "refId": "seed-e1",
            "title": "Eco: 3 new ad concepts — Peak Fitness",
            "summary": "Pause weak 'generic gym' ad; launch 3 UGC-style hooks.",
            "client": "Peak Fitness", "risk": "medium",
            "payload": {"ads": 3, "topAngle": "Transformation UGC"},
            "status": "pending",
            "createdAt": _NOW - 2 * 3600 * 1000, "decidedAt": None,
        },
    ],
}


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("queue"), list):
                return d
        except Exception:
            pass
    return json.loads(json.dumps(_SEED))


def _save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    forge_atomic.atomic_write_json(STATE, d)


def _slim(it):
    return {
        "id": it.get("id"),
        "kind": it.get("kind") if it.get("kind") in KINDS else "dyson",
        "refId": it.get("refId") or "",
        "title": it.get("title") or "(untitled)",
        "summary": it.get("summary") or "",
        "client": it.get("client") or "",
        "risk": it.get("risk") or "low",
        "payload": it.get("payload") or {},
        "status": it.get("status") if it.get("status") in STATUSES else "pending",
        "createdAt": it.get("createdAt"),
        "decidedAt": it.get("decidedAt"),
        "result": it.get("result"),
    }


def add(kind, ref_id, title, summary, client="", risk="low", payload=None):
    """Push (or refresh) an item into the approval queue.

    Deduped by (kind, ref_id): re-generating a draft updates the existing entry
    and resets it to pending rather than stacking duplicates.
    """
    if kind not in KINDS:
        return {"error": f"kind must be one of {KINDS}"}
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        q = d.get("queue", [])
        existing = next((x for x in q
                         if x.get("kind") == kind and x.get("refId") == ref_id), None)
        if existing:
            existing.update({
                "title": title, "summary": summary, "client": client,
                "risk": risk, "payload": payload or {},
                "status": "pending", "createdAt": now, "decidedAt": None,
            })
            item = existing
        else:
            d["seq"] = d.get("seq", 0) + 1
            item = {
                "id": f"a{d['seq']}_{now}", "kind": kind, "refId": ref_id,
                "title": title, "summary": summary, "client": client,
                "risk": risk, "payload": payload or {},
                "status": "pending", "createdAt": now, "decidedAt": None,
            }
            q.append(item)
        d["queue"] = q
        _save(d)
        return {"ok": True, "item": _slim(item)}


def list_queue(status=None):
    with _LOCK:
        d = _load()
        items = [_slim(x) for x in d.get("queue", [])]
        counts = {s: 0 for s in STATUSES}
        for x in items:
            counts[x["status"]] = counts.get(x["status"], 0) + 1
        if status in STATUSES:
            items = [x for x in items if x["status"] == status]
        items.sort(key=lambda x: (x["status"] != "pending", -(x.get("createdAt") or 0)))
        return {"queue": items, "counts": counts, "kinds": KINDS}


def _dispatch_approve(it):
    """Dispatch an approved item to its executor. Returns {ok, detail, url?}.

    Canonical executor invocation: the Approval Center decide() is the single
    gate. Module-level decision() paths (agency_dyson.decision, etc.) are
    independent entry points for direct per-module UIs — they do NOT share
    call sites with this dispatcher, so there is no double-execution risk.

    Imports are deferred (inside the function) to avoid circular imports at
    module load time.
    """
    kind = it.get("kind")
    ref_id = it.get("refId", "")
    payload = it.get("payload") or {}

    try:
        if kind == "dyson":
            import agency_dyson  # deferred
            with agency_dyson._LOCK:
                d = agency_dyson._load()
                draft = next(
                    (x for x in d.get("drafts", []) if x.get("id") == ref_id),
                    None,
                )
            if draft is None:
                return {"ok": False, "detail": f"could not resolve source dyson object (id={ref_id!r})"}
            return agency_dyson.apply(draft)

        if kind == "workflow":
            import agency_workflows_io  # deferred
            with agency_workflows_io._LOCK:
                d = agency_workflows_io._load()
                # refId is workflowId for workflow drafts
                draft = next(
                    (x for x in d.get("drafts", [])
                     if x.get("workflowId") == ref_id or x.get("id") == ref_id),
                    None,
                )
            if draft is None:
                return {"ok": False, "detail": f"could not resolve source workflow object (refId={ref_id!r})"}
            return agency_workflows_io.push(draft)

        if kind == "eco":
            import agency_eco  # deferred
            # payload carries concept_index when the approval was added via generate()
            concept_index = payload.get("concept_index", 0)
            rec_id = ref_id
            if not rec_id:
                return {"ok": False, "detail": "could not resolve source eco object (no refId)"}
            return agency_eco.approve_ad(rec_id, concept_index=concept_index)

        if kind == "social":
            import agency_social  # deferred
            with agency_social._LOCK:
                d = agency_social._load()
                post = next(
                    (x for x in d.get("posts", []) if x.get("id") == ref_id),
                    None,
                )
            if post is None:
                return {"ok": False, "detail": f"could not resolve source social object (id={ref_id!r})"}
            return agency_social.publish(post)

        return {"ok": False, "detail": f"unknown kind {kind!r} — no executor registered"}

    except Exception as exc:
        return {"ok": False, "detail": f"executor error ({kind}): {exc}"}


def _sync_source_status(it, status):
    """Keep the originating draft/post aligned with the central queue."""
    kind = it.get("kind")
    ref_id = it.get("refId", "")
    try:
        if kind == "dyson":
            import agency_dyson
            with agency_dyson._LOCK:
                d = agency_dyson._load()
                draft = next((x for x in d.get("drafts", []) if x.get("id") == ref_id), None)
                if draft:
                    draft["status"] = status
                    agency_dyson._save(d)
        elif kind == "workflow":
            import agency_workflows_io
            with agency_workflows_io._LOCK:
                d = agency_workflows_io._load()
                draft = next((x for x in d.get("drafts", [])
                              if x.get("workflowId") == ref_id or x.get("id") == ref_id), None)
                if draft:
                    draft["status"] = status
                    agency_workflows_io._save(d)
        elif kind == "eco":
            import agency_eco
            with agency_eco._LOCK:
                d = agency_eco._load()
                rec = next((x for x in d.get("sets", []) if x.get("id") == ref_id), None)
                if rec:
                    rec["status"] = status
                    agency_eco._save(d)
    except Exception:
        # Queue state and executor receipts remain authoritative if a source
        # store is unavailable; this sync is a consistency convenience.
        pass


def decide(item_id, action):
    """Approve / revise / reject a queued item.

    On "approve": flips status to 'approved', dispatches to the matching executor
    (agency_dyson.apply / agency_workflows_io.push / agency_eco.approve_ad /
    agency_social.publish), attaches the executor result to item["result"], and
    persists. Never raises — executor failures are stored as {ok:False, detail:...}.

    Canonical executor path: this function is the single gate. The module-level
    decision() functions on each module are independent entry points used by the
    per-module UIs (/api/agency/dyson/decision etc.) and do not share call sites
    with this dispatcher — no double-execution.
    """
    if action not in ACTIONS:
        return {"error": f"action must be one of {list(ACTIONS)}"}
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        it = next((x for x in d.get("queue", []) if x.get("id") == item_id), None)
        if not it:
            return {"error": "approval item not found"}
        it["decidedAt"] = now

        if action == "approve":
            exec_result = _dispatch_approve(it)
            it["result"] = exec_result
            it["status"] = ("approved" if isinstance(exec_result, dict)
                             and exec_result.get("ok") else "failed")
        else:
            it["status"] = ACTIONS[action]
        _sync_source_status(it, it["status"])

        _save(d)
        return {"ok": True, "item": _slim(it)}
