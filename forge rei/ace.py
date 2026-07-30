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
import re
import threading
import time
from pathlib import Path

import forge_atomic
import forge_ops
import test_mode

STATE = Path(__file__).resolve().parent / "marcus_state" / "ace.json"
_LOCK = threading.Lock()

MODES = ("off", "shadow", "supervised", "full")
MAX_REPLIES = int(os.environ.get("FORGE_ACE_MAX_REPLIES", "5"))
READY_MIN_FACTS = 3
_MAX_LOG = 50

# Phase 3 — per-mode daily auto-send caps (separate from autopilot's cap; both share
# send_ledger so the two tiers can never stack texts on one thread).
CAP_SUPERVISED = int(os.environ.get("FORGE_ACE_CAP_SUPERVISED", "3"))
CAP_FULL = int(os.environ.get("FORGE_ACE_CAP_FULL", "10"))

# Phase 6 — the CALL PIVOT.
#
# Before this, every `escalate` was SILENT: a seller who wrote "how much will you give me?"
# or "yes i want to sell" got no text at all, because decide() escalated and apply() only
# built the operator's call card. Those are the two highest-intent messages a seller ever
# sends, so silence there is the most expensive bug in the funnel. Now the first escalate on
# a thread sends ONE call-pivot text (no number, asks for the call) and then escalates
# exactly as before.
#
# PIVOT_RESERVE keeps slots that ordinary qualifying questions cannot touch. Without it, on
# supervised (cap 3) three questions can burn the whole budget by noon and the 2pm price ask
# gets silence anyway — reintroducing the very bug this feature exists to fix. The operator's
# total daily autonomy budget is unchanged; only the mix is protected.
PIVOT_RESERVE = int(os.environ.get("FORGE_ACE_PIVOT_RESERVE", "1"))

# Reasons that earn a pivot text. Everything else (terminal state, operator-held, DNC,
# clocked out, test-mode scoped out) escalates silently exactly as it always did.
PIVOT_REASONS = ("call-ready", "max replies reached", "all facts gathered")

# Phase 4 — call-ready queue store.
CALL_READY = Path(__file__).resolve().parent / "marcus_state" / "call_ready.json"
_CR_LOCK = threading.Lock()


def cap_for(m=None):
    m = m or mode()
    return CAP_SUPERVISED if m == "supervised" else CAP_FULL if m == "full" else 0


def _prompt_status():
    try:
        import marcus_engine
        health = marcus_engine.skill_sources()
        required = [health.get("replyRubric") or {}]
        required.extend((health.get("playbook") or {}).values())
        degraded = not required or any(
            int(item.get("bytes") or 0) == 0 for item in required
        )
        return health, degraded
    except Exception:
        return {}, True


def reply_cap_for(m=None):
    """Cap for ordinary qualifying questions — the full cap minus the pivot reserve.

    Questions gather facts; the pivot earns the call. When the day's budget is tight the
    pivot is worth more, so it gets the last slot(s). Never drops below 1, so a reserve
    larger than the cap can't silence the question lane entirely."""
    return max(1, cap_for(m) - PIVOT_RESERVE)


def _pivoted(rec):
    """Has this thread already had its one call-pivot? Reads the durable ledger written by
    ConversationEngine.note_call_pivot. Never raises — on doubt, report not-pivoted so the
    seller gets a reply rather than silence."""
    try:
        return bool((rec or {}).get("callPivotAt"))
    except Exception:
        return False


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
    st = status()
    try:
        import agent_bus
        agent_bus.send("ace", "all", "status",
                       f"🤖 ACE mode → {m.upper()}"
                       + (" (drafts queue for approval, no auto-send)" if m == "shadow" else ""),
                       {"type": "ace_mode", "mode": m})
        # Arming ACE while TEST MODE is on reaches nobody but the whitelist — alert, don't
        # let the operator believe autonomy is live when it silently isn't.
        if st.get("warning"):
            agent_bus.send("ace", "all", "alert", f"⚠️ {st['warning']}",
                           {"type": "ace_test_mode_warning", "mode": m})
    except Exception:
        pass
    return st


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


def _reserve_send_slot(m, kind="reply"):
    """Atomically reserve one ACE auto-send slot before drafting.

    The screening bridge can run several worker threads. A separate check-then-bump can let
    two threads pass the daily cap at once, so reserve under the same lock and release on any
    downstream draft/gate failure.

    `kind="pivot"` may spend the full cap; `kind="reply"` (a qualifying question) may only
    spend cap - PIVOT_RESERVE, so the day's last slot(s) stay available for the one text
    that actually earns the call.
    """
    hard_cap = cap_for(m)
    cap = hard_cap if kind == "pivot" else reply_cap_for(m)
    if hard_cap <= 0:
        return {"error": f"ace daily cap {hard_cap} reached", "cap": hard_cap}
    with _LOCK:
        d = _roll(_load())
        sent = int(d.get("sentToday") or 0)
        if sent >= cap:
            note = (f"ace daily cap {hard_cap} reached" if kind == "pivot"
                    else f"ace question cap {cap} reached (pivot reserve held back "
                         f"{hard_cap - cap})")
            return {"error": note, "cap": cap, "sentToday": sent}
        d["sentToday"] = sent + 1
        _save(d)
        return {"ok": True, "sentToday": d["sentToday"], "cap": hard_cap}


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
    prompt_health, degraded_prompt = _prompt_status()
    try:
        with _LOCK:
            d = _roll(_load())
            test = test_mode.status()
            mode_now = d.get("mode", "off")
            # The silent-no-op trap: ACE armed while TEST MODE is on means every seller who
            # isn't on the whitelist is skipped ("contact is not whitelisted") — the operator
            # thinks autonomy is live when it is reaching nobody. Say so, loudly.
            warning = None
            if mode_now != "off" and test.get("enabled"):
                warning = (f"TEST MODE is ON — ACE is armed ({mode_now}) but will only text the "
                           f"{len(test.get('phones') or [])} whitelisted number(s). Real sellers "
                           f"are being skipped. Turn TEST MODE off to go live.")
            return {
                "mode": mode_now,
                "sentToday": int(d.get("sentToday") or 0),
                "day": d.get("day"),
                "maxReplies": MAX_REPLIES,
                "log": (d.get("log") or [])[:20],
                "testScoped": bool(test.get("enabled")),
                "testPhoneCount": len(test.get("phones") or []),
                "warning": warning,
                "promptHealth": prompt_health,
                "degradedPrompt": degraded_prompt,
            }
    except Exception as e:  # noqa: BLE001
        return {
            "mode": "off",
            "sentToday": 0,
            "error": str(e),
            "log": [],
            "promptHealth": prompt_health,
            "degradedPrompt": degraded_prompt,
        }


def _stop(reason):
    return {"action": "stop", "reason": reason}


_FACT_REPORT_FIELDS = {
    "condition": "conditionNotes",
    "timeline": "timeline",
    "price": "askingPrice",
    "motivation": "motivationLevel",
    "occupancy": "propertyStatus",
}
_UNKNOWN_VALUES = ("", "unknown", "not mentioned", "none", "n/a", "null")
_FACT_DRAFT_PATTERNS = {
    "condition": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\b(?:condition|shape)\b",
        r"\b(?:repairs?|fix(?:es|ed|ing)?|renovat(?:e|ed|ion|ions)|updates?|updated|"
        r"damage[sd]?|roof|hvac|foundation)\b",
        r"\b(?:needs?|requires?)\s+(?:some\s+|any\s+)?work\b",
        r"\bwhat\s+(?:kind of\s+)?work\b.{0,30}\b(?:need|require|done)\b",
        r"\bwork\s+(?:is|was|would be|needs? to be)\s+(?:needed|required|done)\b",
    )),
    "timeline": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\b(?:timeline|timeframe|deadline|closing date)\b",
        r"\bhow soon\b",
        r"\bwhen\b.{0,50}\b(?:sell(?:ing)?|close|closing|move|moving|vacate|done|"
        r"wrap(?:ped|ping)? up)\b",
        r"\b(?:sell(?:ing)?|close|closing|move|moving|vacate|done|"
        r"wrap(?:ped|ping)? up)\b.{0,50}\b(?:when|soon|date|deadline|days?|weeks?|"
        r"months?|years?)\b",
        r"\b(?:need|want|hope|looking|plan(?:ning)?|ready)\b.{0,35}\b(?:sell(?:ing)?|"
        r"close|closing|move|moving|done|wrap(?:ped|ping)? up)\b",
        r"\b(?:this|next|within|by|in)\s+(?:the\s+next\s+)?(?:\d+\s+)?"
        r"(?:days?|weeks?|months?|years?)\b",
    )),
    "price": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\b(?:asking price|price|asking|number in mind)\b",
        r"\b(?:looking|hoping|want|need)\b.{0,20}\b(?:get|for it|for the "
        r"(?:property|house|home))\b",
        r"\bwhat\b.{0,20}\b(?:number|amount)\b",
        r"\b(?:take|accept)\b.{0,20}\b(?:for it|for the (?:property|house|home))\b",
    )),
    "motivation": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\b(?:reason|motivat\w*)\b.{0,35}\b(?:sale|sell(?:ing)?|move|moving)\b",
        r"\b(?:sale|sell(?:ing)?|move|moving)\b.{0,35}\b(?:reason|motivat\w*)\b",
        r"\bwhy\b.{0,35}\b(?:sell(?:ing)?|move|moving|let(?:ting)? "
        r"(?:it|the property|the house|the home) go)\b",
        r"\bwhat(?:'s| is|s)\b.{0,25}\b(?:got|made|making|driv(?:e|ing)|prompt(?:ed|ing))"
        r"\b.{0,40}\b(?:sell(?:ing)?|move|moving|this)\b",
        r"\bwhat changed\b",
    )),
    "occupancy": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\b(?:vacant|occupied|occupancy|occup(?:y|ies|ied|ying)|tenant|renter|rented|"
        r"owner[- ]occupied)\b",
        r"\b(?:who|anyone|someone|somebody)\b.{0,50}\b(?:live|living|stay|staying)\b",
        r"\bwho\b.{0,40}\bcalls?\s+(?:the\s+)?(?:property|place|house)\s+home\b",
        r"\b(?:is|does)\b.{0,20}\b(?:someone|anyone|owner|seller)\b.{0,20}"
        r"\b(?:living|live|staying|stay)\b",
    )),
}
_FACT_REASK_PATTERNS = {
    "condition": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\bwhat(?:'s| is)?\s+(?:kind of\s+)?(?:condition|shape)\b",
        r"\bwhat\s+(?:kind of\s+)?(?:repairs?|work|updates?|fixes?)\b",
        r"\b(?:is|was)\s+(?:it|the\s+(?:property|house|home|place))\b.{0,20}"
        r"\b(?:condition|shape|updated|damaged)\b",
        r"\b(?:does|do)\s+(?:it|the\s+(?:property|house|home|place))\b.{0,20}"
        r"\b(?:need|require)\b.{0,20}"
        r"\b(?:repairs?|work|fix(?:es|ing)?|updates?)\b",
        r"\b(?:has|have)\s+(?:it|the\s+(?:property|house|home|place))\b.{0,20}"
        r"\b(?:updated|renovated|damaged|repaired)\b",
        r"\b(?:is|are)\s+(?:the\s+)?(?:roof|hvac|foundation)\b.{0,15}"
        r"\b(?:new|old|working|damaged|updated|replaced)\b",
        r"\b(?:how|what)\b.{0,20}\b(?:roof|hvac|foundation)\b",
    )),
    "timeline": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\bhow soon\s+(?:are|do|would|can|could|will)\s+you\b",
        r"\bwhat(?:'s| is)?\s+(?:your\s+|the\s+)?(?:timeline|timeframe|deadline|"
        r"closing date)\b",
        r"\bwhen\s+(?:do|are|would|can|could|will)\b.{0,35}"
        r"\b(?:sell|close|move|vacate|wrap)\w*\b",
        r"\b(?:do|are|would|can|could|will)\s+you\b.{0,35}"
        r"\b(?:sell|close|move|vacate|done|wrap(?:ped|ping)? up)\b",
        r"\b(?:is|was)\s+there\b.{0,15}\b(?:timeline|timeframe|deadline|"
        r"closing date)\b",
        r"\b(?:do|did)\s+you\b.{0,20}\b(?:have|need|want)\b.{0,20}"
        r"\b(?:timeline|timeframe|deadline|closing date)\b",
    )),
    "price": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\bwhat(?:'s| is| are)?\b.{0,20}\b(?:price|asking|number|amount)\b",
        r"\b(?:do|did)\s+you\b.{0,20}\b(?:have|want|need)\b.{0,20}"
        r"\b(?:price|number|amount|for it)\b",
        r"\bhow much\b",
        r"\b(?:are|were)\s+you\b.{0,20}\b(?:looking|hoping)\b.{0,15}\bget\b",
    )),
    "motivation": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\bwhy\s+(?:are|do|did|would|will)\s+you\b.{0,35}"
        r"\b(?:sell|move|let)\w*\b",
        r"\bwhat(?:'s| is|s)\b.{0,25}\b(?:got|made|making|driv(?:e|ing)|"
        r"prompt(?:ed|ing)|motivat(?:e|es|ed|ing))\b.{0,40}"
        r"\b(?:sale|sell(?:ing)?|move|moving|this)\b",
        r"\bwhat(?:'s| is)?\s+(?:your\s+|the\s+)?(?:reason|motivation)\b",
        r"\bwhat changed\b",
    )),
    "occupancy": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\b(?:is|are)\s+(?:it|the\s+(?:property|house|home|place))\s+"
        r"(?:vacant|occupied|rented|owner[- ]occupied)\b",
        r"\b(?:is|are)\b.{0,20}\b(?:anyone|someone|tenant|renter)\b.{0,20}"
        r"\b(?:living|staying|there)\b",
        r"\bwho\b.{0,40}\b(?:live|living|stay|staying|calls?\s+(?:the\s+)?"
        r"(?:property|place|house)\s+home|occup(?:y|ies|ied|ying))\b",
        r"\bdoes\b.{0,25}\b(?:live|stay)\b.{0,15}\bthere\b",
        r"\b(?:are there|do you have)\s+any\s+(?:tenants?|renters?)\b",
    )),
}
_FACT_REQUEST_AUX_RE = re.compile(
    r"\b(?:can|could|would)\s+you\s+(?:please\s+)?"
    r"(?:tell\s+me|describe|walk\s+me\s+through|"
    r"share\s+(?:your|the|more\s+about))\b",
    re.IGNORECASE,
)
_FACT_REQUEST_IMPERATIVE_RE = re.compile(
    r"(?:^|,)\s*(?:please\s+)?"
    r"(?:tell\s+me|describe|walk\s+me\s+through|"
    r"share\s+(?:your|the|more\s+about))\b",
    re.IGNORECASE,
)
_FACT_REQUEST_CLAUSE_SPLIT_RE = re.compile(
    r"[.?!;,]+|\b(?:and|but|so|then)\b",
    re.IGNORECASE,
)
_FACT_REQUEST_TOPIC_PATTERNS = {
    "condition": re.compile(
        r"(?:condition|shape|repairs?|work|updates?|fix(?:es)?)\b",
        re.IGNORECASE,
    ),
    "timeline": re.compile(
        r"(?:timeline|timeframe|deadline|closing date|when\b.{0,35}\b"
        r"(?:sell|close|move|vacate|wrap))\w*\b",
        re.IGNORECASE,
    ),
    "price": re.compile(
        r"(?:asking price|price|number|amount|how much)\b",
        re.IGNORECASE,
    ),
    "motivation": re.compile(
        r"(?:reason|motivat\w*|why\b.{0,35}\b(?:sell|move)|"
        r"what\b.{0,35}\b(?:sell|move))\w*\b",
        re.IGNORECASE,
    ),
    "occupancy": re.compile(
        r"(?:occupancy|vacant|occupied|tenant|renter|"
        r"who\b.{0,35}\b(?:live|stay|occup))\w*\b",
        re.IGNORECASE,
    ),
}


def _known_value(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, sort_keys=True)
    else:
        text = str(value).strip()
    return text[:300] if text.lower() not in _UNKNOWN_VALUES else None


def _known_fact_names(rec, report, exclude=None):
    facts = (rec or {}).get("facts") or {}
    report = report or {}
    known = set()
    for name, report_field in _FACT_REPORT_FIELDS.items():
        if name == exclude:
            continue
        marker = facts.get(name)
        marker_known = marker if isinstance(marker, bool) else _known_value(marker) is not None
        if marker_known or _known_value(report.get(report_field)) is not None:
            known.add(name)
    return known


def _qualification_hint(decision, rec, report, retry=False):
    """Ground a one-fact draft and make already-known values explicit."""
    fact = decision.get("fact")
    known = []
    fact_flags = (rec or {}).get("facts") or {}
    report = report or {}
    known_facts = _known_fact_names(rec, report, exclude=fact)
    for name, report_field in _FACT_REPORT_FIELDS.items():
        if name == fact:
            continue
        conversation_value = _known_value(fact_flags.get(name))
        report_value = _known_value(report.get(report_field))
        if name in known_facts:
            value = conversation_value or report_value or "already known (value unavailable)"
            known.append(f"{name}: {value}")
    known_context = "; ".join(known) if known else "none"
    retry_line = (
        f" REQUIRED RETRY: the prior draft missed {fact}; ask specifically about {fact}."
        if retry else ""
    )
    return (
        f"Assigned fact: {fact}. Ask the seller, in your voice, ONE short natural question "
        f"specifically to learn that fact. Suggested question: \"{decision.get('question') or ''}\". "
        f"Known facts - Do not re-ask any of these: {known_context}. "
        f"Do not quote a price or make an offer.{retry_line}"
    )


def _draft_requests_fact(text, fact):
    """Match seller-directed requests whose fact topic stays in the same sentence."""
    topic_pattern = _FACT_REQUEST_TOPIC_PATTERNS.get(fact)
    if not topic_pattern:
        return False
    for clause in _FACT_REQUEST_CLAUSE_SPLIT_RE.split(text):
        for lead_pattern in (_FACT_REQUEST_AUX_RE, _FACT_REQUEST_IMPERATIVE_RE):
            for lead in lead_pattern.finditer(clause):
                if topic_pattern.search(clause, lead.end()):
                    return True
    return False


def _draft_targets_fact(text, fact):
    return (
        any(pattern.search(text) for pattern in _FACT_REASK_PATTERNS.get(fact, ()))
        or _draft_requests_fact(text, fact)
    )


def _draft_reasks_fact(text, fact):
    return any(pattern.search(text) for pattern in _FACT_REASK_PATTERNS.get(fact, ()))


def _draft_adherence_reason(proposal, fact, known_facts=None):
    """Return a stable failure reason when a qualifying draft misses its assigned fact."""
    text = str((proposal or {}).get("suggestedReply")
               or (proposal or {}).get("sentReply") or "").strip()
    if not text:
        return "draft text unavailable"
    normalized = re.sub(r"\s+", " ", text.lower().replace("\u2019", "'"))
    if not _draft_targets_fact(normalized, fact):
        return f"draft does not ask about assigned fact: {fact}"
    for known_fact in sorted(known_facts or ()):
        if known_fact != fact and _draft_reasks_fact(normalized, known_fact):
            return f"draft re-asks already-known fact: {known_fact}"
    try:
        import sms_guard
        if sms_guard._quotes_price_or_offer(text):
            return "draft quotes price or offer"
    except Exception:
        return "price safety check unavailable"
    return None


def decide(rec, report, convo, last_seller_msg=None):
    """Ordered reply/escalate/stop decision for one thread. Pure (no side effects, never
    raises). Phase 2 acts only on 'reply'; 'escalate'/'stop' are logged for later phases."""
    try:
        m = mode()
        if m == "off":
            return _stop("ace off")
        if forge_ops.paused():
            return _stop("clocked out")
        # Test Mode is a hard ACE scope, not just a UI hint. This lets the operator
        # run FULL automation on whitelisted phones while every real seller stops here.
        test = test_mode.status()
        if test.get("enabled") and not test_mode.is_test((rec or {}).get("phone")):
            return _stop("test mode: contact is not whitelisted")
        state = (rec or {}).get("state")
        if state in ("HANDED_OFF", "DEAD"):
            return _stop(f"terminal:{state}")
        if (rec or {}).get("held"):
            return _stop("operator-held")
        # The thread already got its one call-pivot — it belongs to the operator now. This
        # sits ABOVE every escalation trigger on purpose: it must also stop the qualifying
        # question lane, because _next_state can regress a thread out of CALL_READY and
        # would otherwise let ACE start texting a handed-off seller again.
        if _pivoted(rec):
            return {"action": "escalate", "reason": "call-pivot sent — operator's call"}
        # Escalation triggers → hand the operator the call. The FIRST one on a thread also
        # sends a single call-pivot text (action "pivot"); apply() escalates either way.
        if state == "CALL_READY":
            return {"action": "pivot", "escalate": True, "reason": "call-ready"}
        if int((rec or {}).get("replies") or 0) >= MAX_REPLIES:
            return {"action": "pivot", "escalate": True, "reason": "max replies reached"}
        if last_seller_msg:
            try:
                import marcus_engine
                cls = (marcus_engine.classify(last_seller_msg) or "").upper()
                known_facts = sum(
                    1 for fact in _FACT_REPORT_FIELDS
                    if ((rec or {}).get("facts") or {}).get(fact)
                )
                if cls == "PRICE":
                    return {"action": "pivot", "escalate": True, "reason": f"classify:{cls}"}
                if cls == "READY" and known_facts >= READY_MIN_FACTS:
                    return {"action": "pivot", "escalate": True, "reason": f"classify:{cls}"}
            except Exception:
                pass
        nq = convo.next_question(rec, report)
        if not nq:
            return {"action": "pivot", "escalate": True, "reason": "all facts gathered"}
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
        if action == "pivot":
            # Shadow dress-rehearsal: draft the exact pivot into the approval inbox so the
            # operator can read real ones before arming supervised/full. Deliberately does
            # NOT write the callPivotAt ledger — nothing was sent, so the thread must stay
            # eligible for a real pivot when the mode is flipped.
            res = {}
            if marcus is not None:
                res = marcus.make_proposal_for(
                    conv_id, contact_id=(rec or {}).get("contactId"),
                    pivot=True, seller_said=last_seller_msg)
            ok = bool(res.get("ok"))
            log_event("shadow_pivot" if ok else "draft_fail", conv_id, d.get("reason"),
                      {"name": (rec or {}).get("name"), "err": res.get("error")})
            d["proposed"] = ok
            return d
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
        res = _draft_qualifying_proposal(
            marcus, conv_id, contact_id, d, rec, report, last_seller_msg
        )
        ok = bool(res.get("ok"))
        log_event("shadow_draft" if ok else "draft_fail", conv_id,
                  d.get("question"), {"fact": d.get("fact"),
                                      "name": (rec or {}).get("name"),
                                      "err": res.get("error")})
        d["proposed"] = ok
        if not ok:
            d["error"] = res.get("error")
            d["gate"] = res.get("gate")
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


def _dismiss_draft(marcus, pid, proposal):
    try:
        dismiss = getattr(marcus, "dismiss", None)
        if callable(dismiss):
            dismiss(pid)
            return
        if proposal is not None:
            proposal["status"] = "dismissed"
    except Exception:
        if proposal is not None:
            proposal["status"] = "dismissed"


def _draft_qualifying_proposal(marcus, conv_id, contact_id, decision, rec, report,
                                last_seller_msg=None):
    """Draft at most twice, admitting only a question about the assigned fact."""
    if marcus is None:
        return {"error": "Marcus unavailable", "gate": "fact_adherence"}
    last_reason = "draft failed fact adherence"
    for attempt in range(2):
        hint = _qualification_hint(decision, rec, report, retry=bool(attempt))
        res = marcus.make_proposal_for(
            conv_id, contact_id=contact_id, hint=hint, seller_said=last_seller_msg
        )
        if not res.get("ok"):
            return res
        pid = res.get("proposalId")
        proposal = (getattr(marcus, "proposals", {}) or {}).get(pid) if pid else None
        if proposal is None:
            found = _find_pending_pid(marcus, conv_id)
            if found:
                pid, proposal = found
        assigned_fact = decision.get("fact")
        last_reason = _draft_adherence_reason(
            proposal, assigned_fact,
            known_facts=_known_fact_names(rec, report, exclude=assigned_fact),
        )
        if not last_reason:
            return {"ok": True, "proposalId": pid, "proposal": proposal,
                    "attempts": attempt + 1}
        if pid:
            _dismiss_draft(marcus, pid, proposal)
    return {"error": last_reason, "gate": "fact_adherence", "attempts": 2}


def _pivot_text(proposal):
    """Final safety net on the pivot wording, evaluated before we hand it to approve().

    The drafter is told the blocked words, but "give you" in particular slips into sentences
    that have nothing to do with price ("so i can give you something solid") and sms_guard
    rejects the whole message on sight — which means the seller gets silence at the exact
    moment they asked to do business. So re-run the gate's own check here and substitute the
    known-safe twin rather than gamble the highest-intent text in the funnel.

    Fails CLOSED: if sms_guard can't be imported, return the twin."""
    try:
        import marcus_engine
        safe = marcus_engine.CALL_PIVOT_FALLBACK
    except Exception:
        return None
    text = ((proposal or {}).get("suggestedReply") or "").strip()
    if not text:
        return safe
    try:
        import sms_guard
        if sms_guard._quotes_price_or_offer(text):
            return safe
    except Exception:
        return safe
    try:
        if text == marcus_engine.MarcusEngine._PRICE_FALLBACK:
            return safe          # the operator-facing fallback is gate-blocked when autonomous
    except Exception:
        pass
    return text


def _do_pivot(conv_id, rec, report, convo, marcus, d, last_seller_msg=None, deal_prep=None):
    """Send ONE call-pivot text, then escalate to the operator.

    Ordering here is load-bearing:
      * reserve the cap slot BEFORE drafting (same race-safety as the reply path);
      * write the `callPivotAt` ledger ONLY after a confirmed send — a gate block (send
        hours, legit_check, ledger dedupe) must leave the thread eligible so the next sweep
        retries, otherwise "blocked at 8:59pm" silently becomes "silent forever";
      * escalate + build the call card UNCONDITIONALLY, so a blocked text still reaches the
        operator as a 📞 card rather than vanishing.
    Never raises — a pivot failure can't be allowed to break the screening sweep."""
    reserved = False
    sent = False
    name = (rec or {}).get("name")
    try:
        m = mode()
        slot = _reserve_send_slot(m, kind="pivot")
        if not slot.get("ok"):
            log_event("blocked", conv_id, slot.get("error") or "cap reached",
                      {"name": name, "pivot": True})
        else:
            reserved = True
            cap = slot.get("cap", cap_for(m))
            res = marcus.make_proposal_for(
                conv_id, contact_id=(rec or {}).get("contactId"),
                pivot=True, seller_said=last_seller_msg) if marcus else {}
            if not res.get("ok"):
                _release_send_slot()
                reserved = False
                log_event("draft_fail", conv_id, "pivot draft failed",
                          {"err": res.get("error"), "name": name})
                d["error"] = res.get("error")
            else:
                pid = res.get("proposalId")
                p = (getattr(marcus, "proposals", {}) or {}).get(pid) if pid else None
                if p is None:
                    found = _find_pending_pid(marcus, conv_id)
                    if found:
                        pid, p = found
                if p is None:
                    _release_send_slot()
                    reserved = False
                    log_event("draft_fail", conv_id, "pivot proposal not found after draft",
                              {"name": name})
                else:
                    text = _pivot_text(p)
                    p["autonomous"] = True     # full sms_guard stack, both modes (locked)
                    p["ace"] = True
                    p["acePivot"] = True       # autopilot.maybe_send must skip this
                    sres = marcus.approve(pid, text) if text else marcus.approve(pid)
                    if sres.get("ok"):
                        reserved = False
                        sent = True
                        for fn, arg in ((convo.note_call_pivot, d.get("reason") or ""),
                                        (convo.note_reply, None)):
                            try:
                                fn(conv_id, arg) if arg is not None else fn(conv_id)
                            except Exception:
                                pass
                        try:
                            convo.set_state(conv_id, "CALL_READY")
                        except Exception:
                            pass
                        log_event("call_pivot", conv_id, p.get("sentReply") or text,
                                  {"name": name, "why": d.get("reason")})
                        d["pivoted"] = True
                        try:
                            import telegram_io
                            telegram_io.send(
                                f"📣 <b>ACE call-pivot</b> ({slot.get('sentToday')}/{cap}) → "
                                f"{name or 'seller'}\n"
                                f"<i>why: {d.get('reason')}</i>\n"
                                f"✍️ \"{(p.get('sentReply') or text or '')[:300]}\"",
                                buttons=[
                                    [{"text": "⛔ Stop this thread",
                                      "callback_data": f"acestop:{conv_id}"}],
                                    [{"text": "↩ Undo (hold + flag)",
                                      "callback_data": f"aceundo:{conv_id}"}],
                                ],
                                dedupe_key=f"acepivot:{conv_id}")
                        except Exception:
                            pass
                    else:
                        _release_send_slot()
                        reserved = False
                        log_event("blocked", conv_id, sres.get("error"),
                                  {"gate": sres.get("gate"), "name": name, "pivot": True})
                        d["error"] = sres.get("error")
                        d["gate"] = sres.get("gate")
    except Exception as e:  # noqa: BLE001
        if reserved:
            _release_send_slot()
        log_event("error", conv_id, f"pivot: {e}")
    # Escalate regardless of whether the text made it out.
    try:
        log_event("escalate", conv_id, d.get("reason"),
                  {"name": name, "pivot": bool(sent)})
        call_ready_upsert(dict(rec or {}, state="CALL_READY"), report, deal_prep)
    except Exception:
        pass
    return d


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
        if action == "pivot":
            _do_pivot(conv_id, rec, report, convo, marcus, d,
                      last_seller_msg=last_seller_msg, deal_prep=deal_prep)
            return d
        if action == "escalate":
            log_event("escalate", conv_id, d.get("reason"), {"name": (rec or {}).get("name")})
            # Build the call card on ANY escalate reason, not just "call-ready" — the
            # operator's job is now the call, so every handed-off thread earns a card.
            # call_ready_upsert dedupes its own Telegram ping via row["pingedAt"].
            call_ready_upsert(rec, report, deal_prep)
            return d
        if action == "stop":
            if d.get("reason") not in ("ace off", "clocked out"):
                log_event("stop", conv_id, d.get("reason"))
            return d
        # reply → reserve ACE's own daily cap BEFORE drafting (cheap fail-fast, race-safe).
        m = mode()
        slot = _reserve_send_slot(m, kind="reply")
        if not slot.get("ok"):
            cap = slot.get("cap", cap_for(m))
            log_event("blocked", conv_id, slot.get("error") or f"ace daily cap {cap} reached",
                      {"name": (rec or {}).get("name")})
            return {"action": "stop", "reason": slot.get("error") or f"ace daily cap {cap} reached"}
        reserved = True
        cap = slot.get("cap", cap_for(m))
        contact_id = (rec or {}).get("contactId")
        res = _draft_qualifying_proposal(
            marcus, conv_id, contact_id, d, rec, report, last_seller_msg
        )
        if not res.get("ok"):
            _release_send_slot()
            reserved = False
            log_event("draft_fail", conv_id, d.get("question"),
                      {"err": res.get("error"), "gate": res.get("gate")})
            d["error"] = res.get("error")
            d["gate"] = res.get("gate")
            return d
        # make_proposal_for RETURNS the proposalId — trust it, and only fall back to the
        # conversation scan if it's missing. (The scan alone is fragile: anything that
        # consumes the proposal between the draft and the lookup makes it vanish.)
        pid = res.get("proposalId")
        p = res.get("proposal")
        if p is None:
            p = (getattr(marcus, "proposals", {}) or {}).get(pid) if pid else None
        if p is None:
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
                "questionCap": reply_cap_for(d.get("mode")), "pivotReserve": PIVOT_RESERVE,
                "summary": {"autoSends": by_kind.get("auto_send", 0),
                            "callPivots": by_kind.get("call_pivot", 0),
                            "shadowPivots": by_kind.get("shadow_pivot", 0),
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
