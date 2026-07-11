"""conversation_engine.py — ACE Phase 1: the per-thread conversation state machine.

The autonomy plan (see plan file / CODEX_REVIEW.md) needs one shared, durable answer to
"where is each seller conversation, and what do we still need from them?". This module is that
answer — and NOTHING more in Phase 1: it is READ-ONLY. It derives, from Marcus's existing
screening report, which of the five qualifying facts we already have (condition, timeline,
price, motivation, occupancy) and advances a small state machine per thread. It sends nothing,
texts nothing, and reuses the screening call the system already makes on every hot lead — so it
adds zero outward risk and zero new model calls.

Later phases (the drafter + ramp in ace.py) read this state to decide reply-vs-escalate. Keeping
the state machine isolated here means Phase 1 can ship + be reviewed on its own.

State: marcus_state/conversations.json (atomic + locked, mirrors send_ledger.py / autopilot.py).
Record per convId:
  {convId, contactId, name, state, facts{condition,timeline,price,motivation,occupancy},
   replies, held, lastInboundMs, lastState, updatedAt, history[:30]}
States: NEW -> ENGAGING -> QUALIFYING -> CALL_READY -> HANDED_OFF -> DEAD.
"""
import json
import re
import threading
import time
from pathlib import Path

import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "conversations.json"
_LOCK = threading.Lock()

TARGET_FACTS = ("condition", "timeline", "price", "motivation", "occupancy")
_TERMINAL = ("HANDED_OFF", "DEAD")
_MAX_HISTORY = 30

# Order we ASK for missing facts (price last — a stated price = call-ready trigger).
_ASK_ORDER = ("condition", "timeline", "occupancy", "motivation", "price")

# Canned, voice-appropriate, PRICE-FREE fallback questions (one per fact). Asking the
# SELLER's own number is allowed (their price, not our offer) — the drafter never quotes.
_CANNED_Q = {
    "condition": "what kind of shape is the place in right now",
    "timeline": "how soon are you looking to sell",
    "occupancy": "is it vacant right now or is someone living there",
    "motivation": "what's got you thinking about selling it",
    "price": "do you have a number in mind for it",
}

# Keywords that tie a screening callPrep question to the fact it would uncover.
_FACT_KEYWORDS = {
    "condition": ("condition", "repair", "shape", "roof", "hvac", "foundation", "fix", "updated", "damage"),
    "timeline": ("timeline", "how soon", "when", "timeframe", "close", "quickly", "months"),
    "occupancy": ("vacant", "occupied", "living", "tenant", "rented", "renting", "move"),
    "motivation": ("why", "motivat", "reason", "situation", "goal", "selling because", "thinking about"),
    "price": ("price", "asking", "number", "worth", "looking to get", "how much"),
}

_PRICE_NUMBER_RE = re.compile(
    r"(?i)(\$\s*\d|\b\d{2,3}\s*k\b|\b\d{2,3}[,.]?\d{3}\b)"
)
_OFFER_NUMBER_RE = re.compile(
    r"(?i)\b(offer|offering|pay|paying|can do|take|buy it for|sell it for|purchase price)\b"
)


def _known(val, unknown_markers=("", "unknown", "not mentioned", "none", "n/a")):
    """A screening field counts as a KNOWN fact when it carries real content."""
    if val is None:
        return False
    s = str(val).strip().lower()
    return bool(s) and s not in unknown_markers


def _quotes_price_or_offer(text):
    """True when a candidate question includes our price/offer number."""
    q = str(text or "")
    if _PRICE_NUMBER_RE.search(q):
        return True
    return bool(_OFFER_NUMBER_RE.search(q) and re.search(r"\d", q))


def _derive_facts(report):
    """Map a screening report to the five target facts (True = we have it). Reused verbatim
    from Marcus's screen() output — no new model call."""
    report = report or {}
    return {
        "condition": _known(report.get("conditionNotes")),
        "timeline": _known(report.get("timeline")),
        "price": _known(report.get("askingPrice")),
        "motivation": _known(report.get("motivationLevel")),
        "occupancy": _known(report.get("propertyStatus")),
    }


class ConversationEngine:
    def __init__(self):
        self.lock = _LOCK

    # -- store --------------------------------------------------------------
    def _load(self):
        try:
            d = json.loads(STATE.read_text())
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save(self, d):
        forge_atomic.atomic_write_json(STATE, d)

    def get(self, conv_id):
        if not conv_id:
            return None
        with self.lock:
            return self._load().get(str(conv_id))

    def all(self):
        with self.lock:
            return list(self._load().values())

    # -- state derivation ---------------------------------------------------
    def _next_state(self, prev_state, facts, interest, classify_cls, legit):
        """Deterministic transition. interest/classify/legit are optional (None ok)."""
        if prev_state in _TERMINAL:
            return prev_state                      # never regress out of terminal in Phase 1
        cls = (classify_cls or "").upper()
        if interest == "not_interested" or cls == "DNC":
            return "DEAD"
        known = sum(1 for f in TARGET_FACTS if facts.get(f))
        urgency = (legit or {}).get("urgency")
        # Call-ready: everything gathered, or the seller is clearly ready/asking price now.
        if known >= len(TARGET_FACTS):
            return "CALL_READY"
        if cls in ("READY", "PRICE") and urgency == "high":
            return "CALL_READY"
        if interest == "interested" and known >= 1:
            return "QUALIFYING"
        if interest in ("interested", "not_ready") or known >= 1:
            return "ENGAGING"
        return prev_state or "ENGAGING"

    def update(self, conv_id, contact_id=None, name=None, report=None,
               classify_cls=None, legit=None, last_inbound_ms=None):
        """Recompute facts + advance state from the latest screening. Never raises."""
        if not conv_id:
            return None
        try:
            facts = _derive_facts(report)
            interest = (report or {}).get("interest")
            now = int(time.time() * 1000)
            with self.lock:
                d = self._load()
                rec = d.get(str(conv_id)) or {
                    "convId": str(conv_id), "state": "NEW", "replies": 0,
                    "held": False, "history": [], "createdAt": now,
                }
                if contact_id:
                    rec["contactId"] = contact_id
                if name:
                    rec["name"] = name
                if last_inbound_ms:
                    rec["lastInboundMs"] = last_inbound_ms
                prev = rec.get("state") or "NEW"
                nxt = self._next_state(prev, facts, interest, classify_cls, legit)
                rec["facts"] = facts
                rec["interest"] = interest
                rec["lastState"] = prev
                rec["state"] = nxt
                rec["updatedAt"] = now
                if nxt != prev:
                    rec.setdefault("history", []).insert(
                        0, {"ts": now, "from": prev, "to": nxt})
                    rec["history"] = rec["history"][:_MAX_HISTORY]
                d[str(conv_id)] = rec
                self._save(d)
                return rec
        except Exception:
            return None

    # -- helpers used by later phases (defined now, no-op behavior in P1) ----
    def note_reply(self, conv_id):
        """Increment the per-thread autonomous-reply counter (used by the ramp in Phase 3)."""
        if not conv_id:
            return 0
        try:
            with self.lock:
                d = self._load()
                rec = d.get(str(conv_id))
                if not rec:
                    return 0
                rec["replies"] = int(rec.get("replies") or 0) + 1
                rec["lastReplyAt"] = int(time.time() * 1000)
                self._save(d)
                return rec["replies"]
        except Exception:
            return 0

    def set_state(self, conv_id, state):
        """Force a state (operator ack -> HANDED_OFF, reopen, etc.). Never raises."""
        if not conv_id or not state:
            return None
        try:
            now = int(time.time() * 1000)
            with self.lock:
                d = self._load()
                rec = d.get(str(conv_id)) or {"convId": str(conv_id), "history": []}
                prev = rec.get("state")
                rec["state"] = state
                rec["lastState"] = prev
                rec["updatedAt"] = now
                if state != prev:
                    rec.setdefault("history", []).insert(
                        0, {"ts": now, "from": prev, "to": state})
                    rec["history"] = rec["history"][:_MAX_HISTORY]
                d[str(conv_id)] = rec
                self._save(d)
                return rec
        except Exception:
            return None

    def set_held(self, conv_id, held=True):
        """Operator 'stop this thread' flag — ACE will skip a held thread (Phase 3)."""
        if not conv_id:
            return None
        try:
            with self.lock:
                d = self._load()
                rec = d.get(str(conv_id)) or {"convId": str(conv_id), "history": []}
                rec["held"] = bool(held)
                rec["updatedAt"] = int(time.time() * 1000)
                d[str(conv_id)] = rec
                self._save(d)
                return rec
        except Exception:
            return None

    def next_question(self, rec, report=None):
        """The single best next qualifying question, or None if all 5 facts are known.

        Picks the top still-missing fact (in _ASK_ORDER), then prefers a matching line from the
        screening `callPrep.questions[]`, else a canned price-free question. Returns
        {"fact": <fact>, "question": <text>, "source": "callprep|canned"} or None. Never raises,
        never returns a question that quotes OUR price."""
        try:
            facts = (rec or {}).get("facts") or _derive_facts(report)
            missing = [f for f in _ASK_ORDER if not facts.get(f)]
            if not missing:
                return None
            fact = missing[0]
            questions = (((report or {}).get("callPrep") or {}).get("questions") or [])
            kws = _FACT_KEYWORDS.get(fact, ())
            for q in questions:
                ql = str(q or "").lower()
                if ql and any(k in ql for k in kws):
                    # never let a callPrep line that quotes a price/offer number through
                    if not _quotes_price_or_offer(q):
                        return {"fact": fact, "question": str(q).strip(), "source": "callprep"}
            return {"fact": fact, "question": _CANNED_Q[fact], "source": "canned"}
        except Exception:
            return None

    def summary(self):
        """Counts by state — for the /api/ace/state view + the autonomy digest."""
        try:
            rows = self.all()
            by_state = {}
            for r in rows:
                by_state[r.get("state", "?")] = by_state.get(r.get("state", "?"), 0) + 1
            return {"total": len(rows), "byState": by_state}
        except Exception:
            return {"total": 0, "byState": {}}
