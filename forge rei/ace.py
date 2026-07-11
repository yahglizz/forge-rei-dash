"""ace.py — ACE (Autonomous Conversation Engine) controller: the reply-vs-escalate brain.

Phase 2 scope = **SHADOW only**: for a live seller thread that still has a missing qualifying
fact, ACE drafts ONE next question and drops it into Marcus's existing approval inbox
(`make_proposal_for`) — the operator still approves. NOTHING auto-sends in Phase 2; supervised/
full auto-send is Phase 3 and reuses the same central gate (`sms_guard`).

Mirrors `autopilot.py`: a small locked/atomic JSON state (`marcus_state/ace.json`), a mode
that **defaults OFF**, a per-day counter, and a rolling log. `decide()` is the ordered
trigger function; `consider()` applies the shadow action. The engine never calls `ghl_post`
directly and never composes a price/offer — the drafter is Marcus's voice drafter and every
eventual send flows through `sms_guard`.

State: {mode, sentToday, day, log[:50]}. Modes: off|shadow|supervised|full.
"""
import json
import os
import threading
import time
from pathlib import Path

import forge_atomic
import forge_ops

STATE = Path(__file__).resolve().parent / "marcus_state" / "ace.json"
_LOCK = threading.Lock()

MODES = ("off", "shadow", "supervised", "full")
MAX_REPLIES = int(os.environ.get("FORGE_ACE_MAX_REPLIES", "5"))
_MAX_LOG = 50

# Phase 3 — per-mode daily auto-send caps (separate from autopilot's cap; both share
# send_ledger so the two tiers can never stack texts on one thread).
CAP_SUPERVISED = int(os.environ.get("FORGE_ACE_CAP_SUPERVISED", "3"))
CAP_FULL = int(os.environ.get("FORGE_ACE_CAP_FULL", "10"))

# Phase 4 — call-ready queue store.
CALL_READY = Path(__file__).resolve().parent / "marcus_state" / "call_ready.json"
_CR_LOCK = threading.Lock()


def cap_for(m=None):
    m = m or mode()
    return CAP_SUPERVISED if m == "supervised" else CAP_FULL if m == "full" else 0


def _today_key():
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        return time.strftime("%Y-%m-%d")


def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _roll(d):
    """Reset the per-day counter on a new ET day."""
    today = _today_key()
    if d.get("day") != today:
        d["day"] = today
        d["sentToday"] = 0
    d.setdefault("mode", "off")
    d.setdefault("sentToday", 0)
    d.setdefault("log", [])
    return d


def mode():
    try:
        with _LOCK:
            m = _roll(_load()).get("mode", "off")
        return m if m in MODES else "off"
    except Exception:
        return "off"


def set_mode(m):
    m = (m or "").strip().lower()
    if m not in MODES:
        return {"error": f"mode must be one of {MODES}"}
    with _LOCK:
        d = _roll(_load())
        d["mode"] = m
        _save(d)
    try:
        import agent_bus
        agent_bus.send("ace", "all", "status",
                       f"🤖 ACE mode → {m.upper()}"
                       + (" (drafts queue for approval, no auto-send)" if m == "shadow" else ""),
                       {"type": "ace_mode", "mode": m})
    except Exception:
        pass
    return status()


def log_event(kind, conv_id, detail, extra=None):
    """Append to the rolling ACE log (blocks, escalations, shadow drafts) for the digest."""
    try:
        with _LOCK:
            d = _roll(_load())
            entry = {"ts": int(time.time() * 1000), "kind": kind,
                     "convId": conv_id, "detail": str(detail)[:200]}
            if extra:
                entry.update(extra)
            d.setdefault("log", []).insert(0, entry)
            d["log"] = d["log"][:_MAX_LOG]
            _save(d)
    except Exception:
        pass


def _bump_sent():
    with _LOCK:
        d = _roll(_load())
        d["sentToday"] = int(d.get("sentToday") or 0) + 1
        _save(d)
        return d["sentToday"]


def _reserve_send_slot(m):
    """Atomically reserve one ACE auto-send slot before drafting.

    The screening bridge can run several worker threads. A separate check-then-bump can let
    two threads pass the daily cap at once, so reserve under the same lock and release on any
    downstream draft/gate failure.
    """
    cap = cap_for(m)
    if cap <= 0:
        return {"error": f"ace daily cap {cap} reached", "cap": cap}
    with _LOCK:
        d = _roll(_load())
        sent = int(d.get("sentToday") or 0)
        if sent >= cap:
            return {"error": f"ace daily cap {cap} reached", "cap": cap, "sentToday": sent}
        d["sentToday"] = sent + 1
        _save(d)
        return {"ok": True, "sentToday": d["sentToday"], "cap": cap}


def _release_send_slot():
    """Undo a reserved ACE slot when the draft/send never completed."""
    try:
        with _LOCK:
            d = _roll(_load())
            d["sentToday"] = max(0, int(d.get("sentToday") or 0) - 1)
            _save(d)
    except Exception:
        pass


def status():
    try:
        with _LOCK:
            d = _roll(_load())
            return {
                "mode": d.get("mode", "off"),
                "sentToday": int(d.get("sentToday") or 0),
                "day": d.get("day"),
                "maxReplies": MAX_REPLIES,
                "log": (d.get("log") or [])[:20],
            }
    except Exception as e:  # noqa: BLE001
        return {"mode": "off", "sentToday": 0, "error": str(e), "log": []}


def _stop(reason):
    return {"action": "stop", "reason": reason}


def decide(rec, report, convo, last_seller_msg=None):
    """Ordered reply/escalate/stop decision for one thread. Pure (no side effects, never
    raises). Phase 2 acts only on 'reply'; 'escalate'/'stop' are logged for later phases."""
    try:
        m = mode()
        if m == "off":
            return _stop("ace off")
        if forge_ops.paused():
            return _stop("clocked out")
        state = (rec or {}).get("state")
        if state in ("HANDED_OFF", "DEAD"):
            return _stop(f"terminal:{state}")
        if (rec or {}).get("held"):
            return _stop("operator-held")
        # Escalation triggers → hand the operator the call, stop texting.
        if state == "CALL_READY":
            return {"action": "escalate", "reason": "call-ready"}
        if int((rec or {}).get("replies") or 0) >= MAX_REPLIES:
            return {"action": "escalate", "reason": "max replies reached"}
        if last_seller_msg:
            try:
                import marcus_engine
                cls = (marcus_engine.classify(last_seller_msg) or "").upper()
                if cls in ("PRICE", "READY"):
                    return {"action": "escalate", "reason": f"classify:{cls}"}
            except Exception:
                pass
        nq = convo.next_question(rec, report)
        if not nq:
            return {"action": "escalate", "reason": "all facts gathered"}
        return {"action": "reply", "reason": f"qualify:{nq['fact']}",
                "fact": nq["fact"], "question": nq["question"], "source": nq.get("source")}
    except Exception as e:  # noqa: BLE001
        return _stop(f"decide error: {e}")


def consider(conv_id, rec, report, convo, marcus, last_seller_msg=None):
    """Phase 2 SHADOW: if the decision is 'reply', draft the next qualifying question into
    Marcus's approval inbox (no send). Escalate/stop are logged only. Returns the decision.
    Never raises out — a telemetry/draft error can never break the screening sweep."""
    try:
        d = decide(rec, report, convo, last_seller_msg=last_seller_msg)
        action = d.get("action")
        if action == "escalate":
            log_event("escalate", conv_id, d.get("reason"),
                      {"name": (rec or {}).get("name")})
            return d
        if action == "stop":
            # Only log the meaningful stops (not the constant "ace off" no-op).
            if d.get("reason") not in ("ace off", "clocked out"):
                log_event("stop", conv_id, d.get("reason"))
            return d
        # action == "reply": shadow-draft the question as a gated proposal.
        contact_id = (rec or {}).get("contactId")
        hint = ("Ask the seller, in your voice, ONE short natural question to learn their "
                f"{d['fact']}: \"{d['question']}\". Do not quote a price or make an offer.")
        res = {}
        if marcus is not None:
            res = marcus.make_proposal_for(conv_id, contact_id=contact_id, hint=hint,
                                           seller_said=last_seller_msg)
        ok = bool(res.get("ok"))
        log_event("shadow_draft" if ok else "draft_fail", conv_id,
                  d.get("question"), {"fact": d.get("fact"),
                                      "name": (rec or {}).get("name"),
                                      "err": res.get("error")})
        d["proposed"] = ok
        return d
    except Exception as e:  # noqa: BLE001
        log_event("error", conv_id, f"consider: {e}")
        return {"action": "stop", "reason": f"consider error: {e}"}


# ── Phase 3: supervised/full auto-send ──────────────────────────────────────────────────

def _find_pending_pid(marcus, conv_id):
    """Newest pending proposal for this conversation (make_proposal_for doesn't return it)."""
    try:
        best = None
        for pid, p in dict(getattr(marcus, "proposals", {})).items():
            if p.get("conversationId") != conv_id or p.get("status") not in (None, "pending"):
                continue
            if best is None or int(p.get("ts") or 0) > int(best[1].get("ts") or 0):
                best = (pid, p)
        return best
    except Exception:
        return None


def apply(conv_id, rec, report, convo, marcus, last_seller_msg=None, deal_prep=None):
    """Phase 3 SUPERVISED/FULL: decide, then AUTO-SEND the next qualifying question through
    the exact same gated path a tap uses (make_proposal_for → approve → sms_guard).
    LOCKED CONTRACT: the proposal is marked autonomous=True in BOTH modes — an ACE send
    never bypasses a gate (legit, hours, DNC, price-scrub, clock-out, dedupe all fire).
    The only supervised-vs-full difference is the daily cap. Never raises."""
    reserved = False
    try:
        d = decide(rec, report, convo, last_seller_msg=last_seller_msg)
        action = d.get("action")
        if action == "escalate":
            log_event("escalate", conv_id, d.get("reason"), {"name": (rec or {}).get("name")})
            if d.get("reason") == "call-ready":
                call_ready_upsert(rec, report, deal_prep)
            return d
        if action == "stop":
            if d.get("reason") not in ("ace off", "clocked out"):
                log_event("stop", conv_id, d.get("reason"))
            return d
        # reply → reserve ACE's own daily cap BEFORE drafting (cheap fail-fast, race-safe).
        m = mode()
        slot = _reserve_send_slot(m)
        if not slot.get("ok"):
            cap = slot.get("cap", cap_for(m))
            log_event("blocked", conv_id, slot.get("error") or f"ace daily cap {cap} reached",
                      {"name": (rec or {}).get("name")})
            return {"action": "stop", "reason": slot.get("error") or f"ace daily cap {cap} reached"}
        reserved = True
        cap = slot.get("cap", cap_for(m))
        contact_id = (rec or {}).get("contactId")
        hint = ("Ask the seller, in your voice, ONE short natural question to learn their "
                f"{d['fact']}: \"{d['question']}\". Do not quote a price or make an offer.")
        res = marcus.make_proposal_for(conv_id, contact_id=contact_id, hint=hint,
                                       seller_said=last_seller_msg) if marcus else {}
        if not res.get("ok"):
            _release_send_slot()
            reserved = False
            log_event("draft_fail", conv_id, d.get("question"), {"err": res.get("error")})
            d["error"] = res.get("error")
            return d
        found = _find_pending_pid(marcus, conv_id)
        if not found:
            _release_send_slot()
            reserved = False
            log_event("draft_fail", conv_id, "proposal not found after draft")
            return d
        pid, p = found
        p["autonomous"] = True          # full gate stack in sms_guard — both modes (locked)
        p["ace"] = True
        sres = marcus.approve(pid)      # → _send → sms_guard.guard(autonomous=True)
        if sres.get("ok"):
            reserved = False
            n = slot.get("sentToday")
            try:
                convo.note_reply(conv_id)
            except Exception:
                pass
            log_event("auto_send", conv_id, p.get("sentReply") or d.get("question"),
                      {"fact": d.get("fact"), "name": (rec or {}).get("name")})
            d["sent"] = True
            try:
                import telegram_io
                telegram_io.send(
                    f"🤖 <b>ACE auto-text #{n}/{cap}</b> ({m}) → "
                    f"{(rec or {}).get('name') or 'seller'}\n"
                    f"✍️ \"{(p.get('sentReply') or d.get('question') or '')[:300]}\"",
                    buttons=[
                        [{"text": "⛔ Stop this thread", "callback_data": f"acestop:{conv_id}"}],
                        [{"text": "↩ Undo (hold + flag)", "callback_data": f"aceundo:{conv_id}"}],
                    ],
                    dedupe_key=f"acesend:{conv_id}:{n}")
            except Exception:
                pass
        else:
            _release_send_slot()
            reserved = False
            log_event("blocked", conv_id, sres.get("error"),
                      {"gate": sres.get("gate"), "name": (rec or {}).get("name")})
            d["error"] = sres.get("error")
            d["gate"] = sres.get("gate")
        return d
    except Exception as e:  # noqa: BLE001
        if reserved:
            _release_send_slot()
        log_event("error", conv_id, f"apply: {e}")
        return {"action": "stop", "reason": f"apply error: {e}"}


def hold(conv_id, convo, reason="operator stop"):
    """Telegram ⛔/↩ tap → durable operator-held flag; decide() stops the thread first thing."""
    try:
        rec = convo.set_held(conv_id, True) if convo else None
        log_event("held", conv_id, reason, {"name": (rec or {}).get("name")})
        return {"ok": True, "message": "thread held — ACE will not text it again"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


# ── Phase 4: call-ready queue + escalation ──────────────────────────────────────────────

def _cr_load():
    try:
        d = json.loads(CALL_READY.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def call_ready_upsert(rec, report, deal_prep=None):
    """Build/refresh the call card for a CALL_READY thread + ping the operator ONCE.
    Combines the screening (callPrep/pathToContract/redFlags/score/askingPrice), Atlas
    anchors, and the ACE-gathered facts. Never raises."""
    try:
        conv_id = (rec or {}).get("convId")
        if not conv_id:
            return None
        contact_id = (rec or {}).get("contactId")
        rep = report or {}
        prep = {}
        try:
            prep = (deal_prep.get(contact_id) or {}).get("prep") or {} if deal_prep else {}
        except Exception:
            prep = {}
        with _CR_LOCK:
            d = _cr_load()
            row = d.get(conv_id) or {"convId": conv_id, "createdAt": int(time.time() * 1000)}
            row.update({
                "contactId": contact_id,
                "name": (rec or {}).get("name"),
                "state": (rec or {}).get("state"),
                "facts": (rec or {}).get("facts"),
                "score": rep.get("score"),
                "askingPrice": rep.get("askingPrice"),
                "callPrep": rep.get("callPrep"),
                "pathToContract": rep.get("pathToContract"),
                "redFlags": rep.get("redFlags"),
                "anchors": prep.get("anchors"),
                "updatedAt": int(time.time() * 1000),
            })
            first_ping = not row.get("pingedAt")
            if first_ping:
                row["pingedAt"] = int(time.time() * 1000)
            d[conv_id] = row
            forge_atomic.atomic_write_json(CALL_READY, d)
        if first_ping:
            log_event("call_ready", conv_id, (rec or {}).get("name"))
            try:
                import agent_bus
                agent_bus.send("ace", "all", "handoff",
                               f"📞 Call-ready: {(rec or {}).get('name') or conv_id} — "
                               "all facts gathered, your call.",
                               {"type": "ace_call_ready", "convId": conv_id})
            except Exception:
                pass
            try:
                import telegram_io
                a = row.get("anchors") or {}
                anchor_line = ""
                if a.get("opening"):
                    anchor_line = (f"\n🎯 anchors ${a['opening']:,.0f} open / "
                                   f"${a.get('target', 0):,.0f} target / "
                                   f"${a.get('walkaway', 0):,.0f} walk")
                telegram_io.send(
                    f"📞 <b>CALL-READY:</b> {row.get('name') or conv_id}"
                    + (f"\n💰 seller asked {row.get('askingPrice')}" if row.get("askingPrice") else "")
                    + anchor_line,
                    buttons=[[{"text": "✅ Got it — my call",
                               "callback_data": f"aceack:{conv_id}"}]],
                    dedupe_key=f"acecall:{conv_id}")
            except Exception:
                pass
        return row
    except Exception:
        return None


def ack(conv_id, convo=None):
    """Operator ✅ on the call-ready ping → thread HANDED_OFF, queue entry marked."""
    try:
        with _CR_LOCK:
            d = _cr_load()
            row = d.get(conv_id)
            if row is not None:
                row["ackAt"] = int(time.time() * 1000)
                forge_atomic.atomic_write_json(CALL_READY, d)
        if convo is not None:
            try:
                convo.set_state(conv_id, "HANDED_OFF")
            except Exception:
                pass
        log_event("ack", conv_id, "operator took the call")
        return {"ok": True, "message": "yours now — marked HANDED_OFF"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def call_ready_list():
    """The call queue, newest first: un-acked on top."""
    try:
        with _CR_LOCK:
            rows = list(_cr_load().values())
        rows.sort(key=lambda r: (bool(r.get("ackAt")), -(r.get("updatedAt") or 0)))
        return {"ok": True, "callReady": rows,
                "waiting": sum(1 for r in rows if not r.get("ackAt"))}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "callReady": [], "waiting": 0}


# ── Phase 5: autonomy digest ────────────────────────────────────────────────────────────

def digest(days=1):
    """Roll the ACE log up for the daily brief + the Autonomy card. Never raises."""
    try:
        since = int(time.time() * 1000) - days * 24 * 3600 * 1000
        with _LOCK:
            d = _roll(_load())
        events = [e for e in (d.get("log") or []) if int(e.get("ts") or 0) >= since]
        by_kind = {}
        blocks = {}
        for e in events:
            k = e.get("kind") or "?"
            by_kind[k] = by_kind.get(k, 0) + 1
            if k == "blocked":
                g = (e.get("gate") or e.get("detail") or "?")[:40]
                blocks[g] = blocks.get(g, 0) + 1
        cr = call_ready_list()
        return {"ok": True, "mode": d.get("mode", "off"),
                "sentToday": int(d.get("sentToday") or 0), "cap": cap_for(d.get("mode")),
                "summary": {"autoSends": by_kind.get("auto_send", 0),
                            "shadowDrafts": by_kind.get("shadow_draft", 0),
                            "escalations": by_kind.get("escalate", 0),
                            "callReady": by_kind.get("call_ready", 0),
                            "blocked": by_kind.get("blocked", 0),
                            "held": by_kind.get("held", 0),
                            "errors": by_kind.get("error", 0)},
                "blocksByReason": blocks,
                "callReadyWaiting": cr.get("waiting", 0),
                "events": events[:30]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "summary": {}, "events": []}
