"""marcus_lead.py — Marcus as LEAD AGENT: he surveys the whole operation and tells
every agent exactly what to do next.

Fires after the 9 AM Do Today build + legit audit (do_today.run_forever), and on
demand (POST /api/marcus/directives, Telegram /directives). Marcus reads the full
ops picture — Scout's buckets, the screening queue, pending proposals, today's
battle plan, the latest legit audit — and issues numbered directives: one set for
Scout, one for the operator. Both land on the agent bus (visible in Comms +
Telegram) and persist in marcus_state/marcus_lead.json.

Direction only — no outward action. Sends to sellers stay behind the operator's tap.
"""
import json
import re
import threading
import time
from pathlib import Path

import forge_atomic
import review_agent

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "marcus_lead.json"
_LOCK = threading.Lock()

_SYS = (
    "You are Marcus, the LEAD AGENT and head of operations for a real-estate "
    "wholesaling business (FORGE REI OS). The agent team reports to you: Scout "
    "(lead triage — finds/ranks seller replies; never texts) and the operator "
    "(Yahjair — the only human; he makes calls and taps Send on messages). A task "
    "cycle just completed. Read the ops snapshot and DIRECT the team like a sharp "
    "acquisitions manager: exact names, numbered steps, highest-leverage first, no "
    "filler. Cut anything that doesn't advance a deal.\n\n"
    "Return ONE JSON object only:\n"
    '{"scout": "<numbered directives for Scout — re-sweeps, leads to watch/stop '
    'surfacing, what to flag next>", '
    '"operator": "<numbered directives for Yahjair — who to CALL first and why, '
    'what to approve, the one move that makes the most money today>", '
    '"focus": "<one sentence: today\'s single most important objective>"}'
)


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _snapshot(scout, screener, marcus, do_today_engine):
    """Compact ops picture Marcus reads before directing. Best-effort per source."""
    bits = []
    try:
        counts = (scout.summary() or {}).get("counts", {})
        hot = [f"{l.get('name')} (motivation {l.get('motivation')}, "
               f"{(l.get('reason') or '')[:60]})"
               for l in (scout.leads("asap") or {}).get("leads", [])[:6]]
        bits.append(f"SCOUT: {counts.get('asap', 0)} hot / {counts.get('warm', 0)} warm "
                    f"/ {counts.get('nurture', 0)} nurture. Hot now: "
                    + ("; ".join(hot) or "none"))
    except Exception:  # noqa: BLE001
        pass
    try:
        ready = []
        for cid, r in list(getattr(screener, "screenings", {}).items())[:40]:
            rep = r.get("report") or {}
            if rep.get("interest") == "interested":
                ready.append(f"{r.get('name')} (score {rep.get('score')}/10)")
        bits.append("SCREENED CALL-READY: " + (", ".join(ready[:8]) or "none"))
    except Exception:  # noqa: BLE001
        pass
    try:
        pend = [p.get("name") for p in marcus.proposals_list()
                if p.get("status") == "pending"]
        bits.append(f"PENDING DRAFTS AWAITING OPERATOR TAP: {len(pend)}"
                    + (f" ({', '.join(pend[:6])})" if pend else ""))
    except Exception:  # noqa: BLE001
        pass
    try:
        v = do_today_engine.view()
        left = [f"[{t['label']}] {t['title']}" for t in v.get("tasks", [])
                if not t.get("done")][:10]
        bits.append(f"DO TODAY: {v.get('doneCount', 0)}/{v.get('total', 0)} done. "
                    "Still open: " + ("; ".join(left) or "all done"))
    except Exception:  # noqa: BLE001
        pass
    try:
        import legit_check
        la = legit_check.last_audit()
        if la:
            bits.append(f"LEGIT AUDIT: {la.get('checked', 0)} threads judged, "
                        f"{len(la.get('demoted', []))} demoted as not interested "
                        f"({', '.join(d.get('name') or '?' for d in la.get('demoted', [])[:5])})")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(bits) or "(no data)"


def directives(scout, screener, marcus, do_today_engine, trigger="manual"):
    """Marcus surveys the operation and issues directives. Returns the result dict;
    posts each directive on the agent bus (Comms feed + Telegram)."""
    key = review_agent._api_key()
    if not key:
        return {"error": "no ANTHROPIC_API_KEY — Marcus can't direct without a brain"}
    snap = _snapshot(scout, screener, marcus, do_today_engine)
    try:
        raw = review_agent._claude(key, _SYS, f"OPS SNAPSHOT ({trigger}):\n{snap}\n\n"
                                   "Issue your directives now.", max_tokens=700)
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0)) if m else {"operator": raw}
    except Exception as e:  # noqa: BLE001
        return {"error": f"directive call failed: {e}"}
    out = {"ts": int(time.time() * 1000), "trigger": trigger,
           "focus": str(d.get("focus") or "")[:300],
           "scout": str(d.get("scout") or "")[:1200],
           "operator": str(d.get("operator") or "")[:1200]}
    try:
        import agent_bus
        if out["scout"]:
            agent_bus.send("marcus", "scout", "directive",
                           f"📋 Marcus → Scout:\n{out['scout']}"[:900],
                           {"type": "directive", "trigger": trigger})
        if out["operator"]:
            agent_bus.send("marcus", "all", "directive",
                           f"🎯 Marcus's orders — {out['focus']}\n{out['operator']}"[:900],
                           {"type": "directive", "trigger": trigger})
    except Exception:  # noqa: BLE001
        pass
    with _LOCK:
        s = _load()
        s["last"] = out
        s.setdefault("history", []).insert(0, out)
        s["history"] = s["history"][:30]
        forge_atomic.atomic_write_json(STATE, s)
    return out


def last():
    with _LOCK:
        return _load().get("last") or {}
