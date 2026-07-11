"""legit_check.py — strict "is this seller actually worth our time?" gate.

The Do Today list was filling up with sellers who never showed real interest. This
module READS THE ACTUAL THREAD before anything earns a task: a Claude verdict on
whether the seller is legitimately interested in selling (or at least having a real
conversation about it). Strict by design — wrong numbers, hostile replies, one-word
brush-offs, agents/realtors, dead air, and "not interested" all fail.

Verdicts cache per convId + lastMessageDate (marcus_state/legit_check.json), so a
thread is only re-judged when the seller says something new. No key → everything
passes (degrades to the old behavior instead of emptying the list).

audit_tagged() is the cleanup sweep: walks every asap/warm Scout lead + every
screening still flagged for check-backs, judges each thread, and DEMOTES the fakes
(Scout bucket → dead, checkBackDue cleared) so they stop resurfacing.
"""
import json
import re
import threading
import time
from pathlib import Path

import forge_atomic
import review_agent

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "legit_check.json"
_LOCK = threading.Lock()

MAX_CACHE = 800            # newest verdicts kept

_SYS = (
    "You are a STRICT gatekeeper for a real-estate wholesaler's daily call/text list. "
    "You read one SMS thread between the operator (outbound) and a property owner "
    "(inbound) and decide TWO things: (1) is this seller LEGITIMATELY interested in "
    "selling (or at least having a real conversation about selling), and (2) how URGENT "
    "is acting on them TODAY.\n\n"
    "FAIL (legit=false) when: the seller said no / not interested / not selling / stop; "
    "hostile or annoyed; wrong number; they're an agent/realtor/investor pitching us; "
    "only one-word or emoji replies with no selling signal; asking us to stop; thread is "
    "only OUR outbound with no real inbound engagement; or the only inbound is a "
    "question like 'who is this' that went nowhere.\n"
    "PASS (legit=true) only when the seller gave a real signal: asked what we'd offer, "
    "named a price, described the property/situation, agreed to talk/call, said 'maybe "
    "later / not right now' in a way that invites a future check-back, or is actively "
    "negotiating.\n\n"
    "URGENCY (only matters when legit=true):\n"
    "  \"high\"   = ACT TODAY. Seller is engaged RIGHT NOW: asked for an offer, named a "
    "price, is negotiating, agreed to talk/call, gave their timeline as soon/urgent, or "
    "the ball is in OUR court on a live hot thread. This is a today move.\n"
    "  \"medium\" = real interest but NOT hot right now: they engaged before then went "
    "quiet/ghosted, said 'maybe later / few months', or it's a warm thread cooling off. "
    "A re-engage, not a today-emergency.\n"
    "  \"low\"    = faint/borderline signal, barely legit, long dead-air.\n"
    "If legit=false, urgency is \"low\".\n\n"
    "Return ONE JSON object only: "
    "{\"legit\": true|false, \"urgency\": \"high|medium|low\", \"reason\": \"<short>\"}"
)


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"verdicts": {}}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _thread_text(msgs, limit=24):
    lines = []
    for m in (msgs or [])[-limit:]:
        who = "SELLER" if m.get("direction") == "inbound" else "US"
        body = (m.get("body") or "").strip()
        if body:
            lines.append(f"{who}: {body[:300]}")
    return "\n".join(lines)


def verdict(scout, conv_id, name=""):
    """{"legit": bool, "reason": str}. No key or no thread → pass-through (legit)."""
    if not conv_id or scout is None:
        return {"legit": True, "reason": "no thread to judge"}
    key = review_agent._api_key()
    if not key:
        return {"legit": True, "reason": "no key — gate off"}
    msgs = scout._thread_transcript(conv_id)
    if not msgs:
        return {"legit": True, "reason": "thread unreadable"}
    last_ms = max((m.get("date") or 0) for m in msgs)
    ck = f"{conv_id}:{last_ms}"
    with _LOCK:
        cached = _load().get("verdicts", {}).get(ck)
    # Only trust a cached verdict that already carries an urgency score — pre-upgrade
    # verdicts lack it, and honoring them would silently default every old lead to
    # 'high' and never populate the re-engage bucket. Missing urgency → re-judge once.
    if cached and cached.get("urgency"):
        return cached
    inbound = [m for m in msgs if m.get("direction") == "inbound"
               and (m.get("body") or "").strip()]
    if not inbound:
        out = {"legit": False, "urgency": "low",
               "reason": "no real inbound from the seller"}
    else:
        user = (f"Seller: {name or 'unknown'}\nThread (oldest first):\n"
                f"{_thread_text(msgs)}\n\nJudge it now.")
        try:
            raw = review_agent._claude(key, _SYS, user, max_tokens=180)
            m = re.search(r"\{.*\}", raw, re.S)
            j = json.loads(m.group(0)) if m else {}
            legit = bool(j.get("legit"))
            urg = str(j.get("urgency") or "").lower()
            if urg not in ("high", "medium", "low"):
                urg = "high" if legit else "low"   # unlabeled legit lead defaults to a today move
            out = {"legit": legit, "urgency": urg if legit else "low",
                   "reason": str(j.get("reason") or "")[:160]}
        except Exception as e:  # noqa: BLE001
            return {"legit": True, "urgency": "high",
                    "reason": f"judge error, passed through: {e}"}
    with _LOCK:
        d = _load()
        v = d.setdefault("verdicts", {})
        v[ck] = out
        if len(v) > MAX_CACHE:                       # trim oldest half
            for k in list(v)[: len(v) - MAX_CACHE]:
                v.pop(k, None)
        _save(d)
    return out


def audit_tagged(scout, screener):
    """Sweep every tagged/active lead, judge the real thread, demote the fakes.
    Returns a report the dashboard/Telegram can show."""
    report = {"ts": int(time.time() * 1000), "checked": 0,
              "demoted": [], "kept": [], "errors": 0}
    # 1. Scout's asap/warm leads — the ones feeding "text back" tasks.
    for r in (scout._active() if scout else []):
        if r.get("bucket") not in ("asap", "warm"):
            continue
        report["checked"] += 1
        v = verdict(scout, r.get("convId"), r.get("name"))
        if v.get("legit"):
            report["kept"].append({"name": r.get("name"), "why": v.get("reason")})
            continue
        try:
            # _active() snapshots the list but returns the LIVE record dicts —
            # mutating r under the lock is the real demotion.
            with scout.lock:
                r["bucket"] = "dead"
                r["reason"] = f"legit-audit: {v.get('reason')}"
                scout._save()
            report["demoted"].append({"name": r.get("name"), "kind": "scout",
                                      "why": v.get("reason")})
        except Exception:  # noqa: BLE001
            report["errors"] += 1
    # 2. Screenings still scheduled for check-backs — stop nurturing dead ends.
    for cid, r in list(getattr(screener, "screenings", {}).items() if screener else []):
        rep = r.get("report") or {}
        if not (r.get("checkBackDue") or rep.get("checkBackDays")):
            continue
        report["checked"] += 1
        v = verdict(scout, r.get("convId"), r.get("name"))
        if v.get("legit"):
            continue
        try:
            r["checkBackDue"] = False
            r["legitAudit"] = v.get("reason")
            rep["checkBackDays"] = None
            screener._save()
            report["demoted"].append({"name": r.get("name"), "kind": "checkback",
                                      "why": v.get("reason")})
        except Exception:  # noqa: BLE001
            report["errors"] += 1
    # Persist the last audit so /api/audit/legit GET can show it.
    with _LOCK:
        d = _load()
        d["lastAudit"] = report
        _save(d)
    try:
        import agent_bus
        agent_bus.send("scout", "all", "alert",
                       f"🧹 Legit-interest audit: {report['checked']} checked, "
                       f"{len(report['demoted'])} demoted as not actually interested.",
                       {"type": "legit_audit"})
    except Exception:  # noqa: BLE001
        pass
    return report


def last_audit():
    with _LOCK:
        return _load().get("lastAudit") or {}
