"""marcus_engine.py — Marcus, the autonomous acquisitions responder.

Trigger-on-need: watches GoHighLevel for UNREAD INBOUND seller texts, classifies
each (reusing Marcus's own classifier from the wholesale toolkit), drafts a reply
(templates, or Claude if ANTHROPIC_API_KEY is set), and queues a PROPOSAL for human
approval. Nothing is texted to a real seller until approved (propose -> review ->
execute). "stop"/DNC messages are auto-suppressed (tagged, never replied to).

Runs inside the dashboard connector — one process, already polling GHL.
No new database: proposals persist to marcus_state/*.jsonl (append log).
"""

import forge_atomic
import json
import os
import re
import send_ledger
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

import forge_heartbeat
import test_mode

HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / "marcus_state"
STATE_DIR.mkdir(exist_ok=True)
PROPOSALS_LOG = STATE_DIR / "proposals.jsonl"
HANDLED_LOG = STATE_DIR / "handled.jsonl"
SEEN_CONTACTS_LOG = STATE_DIR / "seen_contacts.jsonl"  # contactIds we've ever proposed for
                                                       # → first-contact = 🆕 new-lead speed ping
CONFIG_FILE = STATE_DIR / "config.json"  # toggle state, survives restart

# --- locate Marcus's wholesale toolkit so we reuse his real classifier --------
_SCRIPTS_CANDIDATES = [
    HERE.parent / "marcus-wholesale-agent" / "scripts",
    Path.home() / "Desktop" / "marcus-wholesale-agent" / "scripts",
]
classify = None
draft_reply = None
for _sd in _SCRIPTS_CANDIDATES:
    if (_sd / "scan_missed_replies.py").exists():
        sys.path.insert(0, str(_sd))
        try:
            from importlib import import_module
            _m = import_module("scan_missed_replies")
            classify = _m.classify
            draft_reply = _m.draft_reply
        except Exception:
            classify = None
        break


# Fallback classifier if the toolkit can't be imported (keeps Marcus alive).
def _fallback_classify(body):
    b = (body or "").lower()
    if any(p in b for p in ["stop", "unsubscribe", "remove me", "do not text"]):
        return "DNC"
    if any(p in b for p in ["who is this", "wrong number", "who are you"]):
        return "HELP"
    if any(p in b for p in ["not now", "not right now", "later", "few months"]):
        return "NRN"
    if any(p in b for p in ["how much", "offer", "price", "$"]):
        return "PRICE"
    if any(p in b for p in ["yes", "interested", "sure", "talk", "tell me more"]):
        return "READY"
    return "CONTINUE"


def _fallback_draft(first, cls):
    first = first or "there"
    return f"Hey {first}, this is Yahjair — sorry for the slow reply. Still happy to talk through the property if you're open to it. What's the situation on your end?"


if classify is None:
    classify = _fallback_classify
    draft_reply = _fallback_draft

# Map a classification to a recommended action shown on the dashboard.
ACTION_BY_CLASS = {
    "DNC": {"label": "Suppress + tag DNC", "kind": "suppress", "tag": "DNC"},
    "HELP": {"label": "Call to clarify", "kind": "reply", "tag": "Needs You"},
    "NRN": {"label": "Polite defer + follow-up", "kind": "reply", "tag": "nrn-followup"},
    "PRICE": {"label": "Move toward offer", "kind": "reply", "tag": "PRICE"},
    "READY": {"label": "HOT — book the call", "kind": "reply", "tag": "HOT"},
    "CONTINUE": {"label": "Re-engage", "kind": "reply", "tag": "WARM"},
    "WRONG_NUMBER": {"label": "Apologize + close", "kind": "reply", "tag": "Wrong Number"},
}

# Fixed reply Yahjair wants for every "not selling / not right now" seller:
# graceful exit + referral ask. Sent verbatim (his voice), no Claude rewrite.
CANNED_NRN_REPLY = (
    "100% if you ever change your mind, just save my contact and send me a text "
    "or a call we also do referrals so if anyone you know want to sell youll earn commission"
)

# Wrong-number handling is deterministic. Never let a model re-pitch someone who has
# explicitly said they are not the seller/person we meant to reach.
CANNED_WRONG_NUMBER_REPLY = (
    "sorry about that i have the wrong number, ill remove it from my list"
)

# Phrases that mean "soft no / not selling now" -> force the canned referral reply.
# DNC ("stop", etc.) is classified first and always wins over this.
# Clear "not selling" signals only. Removed over-broad matches ("no thanks",
# "no thank you", "not really") that could misfire on an otherwise-warm reply.
_SOFT_NO_PHRASES = [
    "not for sale", "not selling", "not interested", "no longer selling",
    "not looking to sell", "not gonna sell", "not going to sell", "won't sell",
    "wont sell", "not right now", "not at this time",
    "not at the moment", "maybe later", "not the right time",
    "not ready to sell", "decided not to sell", "changed my mind",
    "keeping the house", "keeping the property",
]


def _is_soft_no(body):
    b = (body or "").lower()
    return any(p in b for p in _SOFT_NO_PHRASES)


# A flat rejection where the WHOLE message is essentially "no" — "No", "No!!!",
# "nope", "nah", "not interested", "no thanks". Anchored ^...$ so it only fires on a
# standalone no; "no pictures, I want 20k" (a 'no' inside a warm reply) is NOT caught.
# This is the gap that let bare "No" replies score as warm/hot leads.
_HARD_NO_RE = re.compile(
    r"^\s*(no+|nope|nah+|no\s*thanks?|no\s*thank\s*you|not\s*interested"
    r"|no\s*i'?m?\s*good|no\s*sorry|sorry\s*no|not\s*for\s*me|no\s*thx)"
    r"[\s.!?,'\"\-]*$",
    re.IGNORECASE,
)


def _is_hard_no(body):
    """True only when the entire message is a flat rejection (whole-message match)."""
    return bool(_HARD_NO_RE.match(body or ""))


# Denial / wrong-number / confused-recipient replies — NOT a seller conversation at all.
# "Did I call you? No", "I'm not [name]", "who dis", "wrong person" etc. These currently
# fall through every bucket to CONTINUE ("warm", 45) — burning a Marcus screening call and
# a Do Today task on someone who isn't a lead. Edit this list as new phrasing shows up.
_DENIAL_PHRASES = [
    "did i call you", "did you call me", "i didn't call you", "i did not call you",
    "you called me", "i don't know you", "i dont know you", "i do not know you",
    "who dis", "who's this", "whos this", "who is this", "who are you", "what is this",
    "wrong number", "wrong person", "not who you think", "not who you're looking for",
    "not the person you're looking for", "never called you", "never talked to you",
    "never spoke to you", "you have the wrong",
]

# "I am not [name]" / "this isn't [name]" identity denials — can't be a fixed phrase list
# since the name varies (real examples hit: "I am not geraldine", "THIS IS NOT KRISTEN").
# Excludes the common continuations that are a real seller signal, not a denial
# ("I'm not interested" / "I am not selling" / "I'm not ready" are NRN, not this).
_IDENTITY_DENIAL_RE = re.compile(
    r"(?i)\b(?:i\s*am\s*not|i'?m\s*not|this\s*is\s*not|this\s*isn'?t|that'?s\s*not)\s+"
    r"(?!interested|selling|sure|ready|available|looking|able|going|going\s*to)"
    r"[a-z]{2,}\b"
)

# Explicit opt-out / harassment complaints that AREN'T in the DNC phrase list ("stop",
# "unsubscribe", "remove me", ...) but mean the exact same thing — e.g. Kristen Moffett's
# real reply: "REMOVE MY NUMBER FROM YOUR WEBSITE ... LEAVE ME ALONE". Currently only
# caught because Claude happens to read it right; if Claude's ever down this compliance
# request gets missed entirely. Free rule-layer catch, same severity as DNC.
_OPT_OUT_PHRASES = [
    "remove my number", "take me off", "off your list", "off your website",
    "leave me alone", "stop bothering", "stop contacting", "stop messaging",
    "stop texting me", "quit texting", "quit calling", "quit contacting",
    "harassing me", "this is harassment",
]


def _is_denial(body):
    """True for wrong-number / mistaken-identity / 'did I call you?' / 'who is this'
    replies — never a real seller conversation. Skip Claude, skip screening, skip Do
    Today entirely."""
    b = (body or "").lower()
    if any(p in b for p in _DENIAL_PHRASES):
        return True
    return bool(_IDENTITY_DENIAL_RE.search(body or ""))


def _is_opt_out(body):
    """True for an explicit 'remove my number' / 'leave me alone' style opt-out that
    isn't literally 'stop'/'unsubscribe' but means the same thing — treat as DNC-grade,
    not a lead to nurture or nudge back into a conversation."""
    b = (body or "").lower()
    return any(p in b for p in _OPT_OUT_PHRASES)


# Phrases that mean THIS IS OUR OWN OUTREACH, not a seller's message. GHL sometimes
# surfaces our blast/opener as if it were inbound — never draft a reply to ourselves.
# A real seller does not say "we buy houses" or "this is yahjair". Edit this list to
# match your actual outreach scripts.
_OUR_OUTREACH_PHRASES = [
    "we buy houses", "we buy homes", "we buy property", "we pay cash",
    "cash offer", "close fast", "close quickly", "as-is", "no realtor", "no agents",
    "i was calling about", "i'm calling about", "im calling about",
    "calling about potentially selling", "potentially selling a home",
    "just following up", "just checking in", "circle back", "circling back",
    "reaching out about your", "saw your property", "saw your home",
    "wanted to reach out", "wanted to see if", "wanted to ask if",
    "trying to reach you", "tried calling you", "following up on my call",
    "following up on my text", "following up about the property",
    "would you consider selling", "have you considered selling",
    "interested in selling your", "consider an offer on",
    "cash for your property", "cash for your home",
    "looking to purchase your", "interested in buying your", "buy your property",
    "buy your house", "buy your home", "are you the owner of the property",
    "are you still looking to sell", "still looking to sell", "still interested in selling",
    "this is yahjair", "hey it's yahjair", "this is forge",
    # Our other businesses' automations that bleed into this number (GHL mis-flags as
    # inbound). A real seller never says these. Add your own autotext lines here.
    "touch of blessing", "touch of blessings", "we just missed your call",
    "how can we help you today",
]

_OUR_OUTREACH_RE = re.compile(
    r"(?i)^\s*(?:hey|hi|hello)?\s*[a-z'-]{0,30}[, ]*"
    r"(?:this is yahjair|it'?s yahjair|i(?:'m| am) (?:reaching|following|calling|texting)|"
    r"i (?:wanted|was trying|tried) to (?:reach|call|text|see|ask)|"
    r"we(?:'re| are) (?:looking|interested|buying)|would you (?:consider|be open to) selling)\b"
)


def _is_our_message(body):
    """True if the text reads like OUR outreach (not a seller's reply)."""
    b = (body or "").lower()
    return any(p in b for p in _OUR_OUTREACH_PHRASES) or bool(_OUR_OUTREACH_RE.search(body or ""))


# Model-output admission checks. These are intentionally deterministic and are run once
# before a proposal is persisted and again by sms_guard immediately before any agent send.
_DRAFT_META_RE = re.compile(
    r"(?i)\b(?:i (?:do not|don'?t|can'?t|cannot) (?:see|have|assist|help)|"
    r"i(?:'m| am) (?:unable|sorry,? but i can'?t)|as an ai|language model|"
    r"seller'?s message (?:is )?(?:missing|not provided|isn'?t provided)|"
    r"provide (?:the )?(?:seller|message|context)|need (?:the )?(?:seller'?s )?(?:message|context)|"
    r"insufficient context|no context|cannot generate|can'?t generate|unable to generate)\b"
)
_DRAFT_PLACEHOLDER_RE = re.compile(
    r"(?i)(?:\[(?:company|business|your|seller|property|address|name)[^\]]*\]|"
    r"\{\{?[^}\n]+\}?\}|<(?:company|business|name|address)[^>]*>)"
)
_DRAFT_PERSONA_RE = re.compile(r"(?i)\bmarcus\b")
_SELLER_PRICE_RE = re.compile(
    r"(?i)(?:\$\s*\d|\b\d{1,3}(?:,\d{3})+\b|\b\d{1,6}(?:\.\d+)?\s*(?:k|grand|thousand)\b|"
    r"\b(?:price|asking|ask|take|want|need|worth|offer|consider)\D{0,18}\d{2,})"
)
_PRICE_CONFIRM_RE = re.compile(
    r"(?i)\b(?:in the ballpark|ballpark|solid starting point|good starting point|"
    r"reasonable starting point|sounds reasonable|sounds fair|seems fair|that(?:'s| is) fair|"
    r"that works|could work|can work with that|work with that|make that work|"
    r"we(?:'re| are) close|not far off|around there|in range|within range|"
    r"that number (?:works|is fair|is reasonable|sounds good)|"
    r"your (?:number|price|ask|asking price) (?:works|is fair|is reasonable|sounds good))\b"
)
_AMBIGUOUS_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*[.!?]?\s*$")


def _draft_safety_reason(text, seller_said=""):
    """Return a stable reason when model output is not safe to queue/send."""
    out = (text or "").strip().replace("’", "'").replace("‘", "'")
    if not out:
        return "empty draft"
    if _DRAFT_META_RE.search(out):
        return "model refusal or meta/confusion text"
    if _DRAFT_PLACEHOLDER_RE.search(out):
        return "unfilled placeholder"
    if _DRAFT_PERSONA_RE.search(out):
        return "Marcus persona/name leak"
    if _SELLER_PRICE_RE.search(seller_said or "") and _PRICE_CONFIRM_RE.search(out):
        return "verbally confirmed seller price"
    return None


def _is_ambiguous_numeric_message(body):
    """A bare 1-3 digit inbound has no safe property/seller meaning by itself."""
    return bool(_AMBIGUOUS_NUMBER_RE.fullmatch(body or ""))


# An iMessage tapback / emoji REACTION to one of our texts arrives as an INBOUND message
# whose body QUOTES our own words — e.g. '👍 to "Hey Robert, just following up..."' or
# 'Liked "..."'. _is_our_message() flags those (they contain our outreach text) so we'd
# drop them — but a 👍 is a real seller buy-signal. Detect reactions so Scout keeps + scores
# them instead of silently discarding the lead.
_REACT_POS = ("👍", "❤", "♥", "😍", "😎", "😂", "🤣", "🔥", "👏", "🙏", "✅", "💯",
              "😊", "🙂", "👌", "💪", "liked", "loved", "laughed", "emphasized")
_REACT_NEG = ("👎", "disliked")
_REACT_Q = ("❓", "❔", "questioned")
_REACT_LEAD = re.compile(r"^[\s​‌‍⁦-⁩️]+")


def _reaction_kind(body):
    """Classify an SMS/iMessage reaction to our message: 'pos' | 'neg' | 'q' | None.
    Fires only when the message is a reaction that QUOTES our text (a normal seller reply
    that merely contains an emoji is NOT mistaken for a tapback)."""
    if not body:
        return None
    b = _REACT_LEAD.sub("", body)
    low = b.lower()
    quoted = ('"' in b) or ('“' in b) or (' to ' in low[:8])
    if not quoted:
        return None
    head = low[:16]
    if any(head.startswith(o) for o in _REACT_NEG):
        return "neg"
    if any(head.startswith(o) for o in _REACT_Q):
        return "q"
    if any(head.startswith(o) for o in _REACT_POS):
        return "pos"
    return None


def _is_reaction(body):
    """True if the message is an emoji/tapback reaction to our text (a kept buy-signal)."""
    return _reaction_kind(body) is not None


def _is_seller_message(body):
    """True for genuine seller text, including reactions that quote our outreach."""
    return bool((body or "").strip()) and (
        not _is_our_message(body) or _is_reaction(body)
    )


class MarcusEngine:
    def __init__(self, ghl_get, ghl_post, location_id):
        self.ghl_get = ghl_get
        self.ghl_post = ghl_post
        self.location_id = location_id
        self.lock = threading.Lock()
        self.enabled = True
        self.auto_send = False  # human approval required by default (all classes)
        # NRN ("not selling / not right now") referral reply is ALSO a proposal by default —
        # propose→review→execute holds for every outward text (CLAUDE.md §2). Flip on with
        # the dashboard toggle (or config) if you want the safe canned line to auto-send.
        self.auto_send_nrn = False
        self.poll_interval = 60
        self.last_poll = None
        self.last_error = None
        self.proposals = {}          # id -> proposal (pending only)
        self.activity = []           # recent events (ring buffer)
        self.handled = set()         # conversation:lastMessageDate keys
        self.seen_contacts = set()   # contactIds we've proposed for → first time = new lead
        self.counts = {"proposed": 0, "sent": 0, "suppressed": 0, "dismissed": 0}
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or self._key_from_env_file()
        self._load_config()  # restore enabled/auto_send toggles from last run
        self._load()

    # -- persistence ---------------------------------------------------------
    def _key_from_env_file(self):
        for p in [HERE.parent / "marcus-wholesale-agent" / "config" / "ghl.env",
                  Path.home() / "Desktop" / "marcus-wholesale-agent" / "config" / "ghl.env"]:
            if p.exists():
                for line in p.read_text().splitlines():
                    if line.strip().startswith("ANTHROPIC_API_KEY="):
                        v = line.split("=", 1)[1].strip()
                        if v and not v.startswith("sk-ant-..."):
                            return v
        return None

    def _load_config(self):
        """Toggle state persists across restarts (systemd Restart=always would
        otherwise silently revert auto_send to its default on every crash)."""
        try:
            if CONFIG_FILE.exists():
                c = json.loads(CONFIG_FILE.read_text())
                if "enabled" in c:
                    self.enabled = bool(c["enabled"])
                if "auto_send" in c:
                    self.auto_send = bool(c["auto_send"])
                if "auto_send_nrn" in c:
                    self.auto_send_nrn = bool(c["auto_send_nrn"])
        except Exception:
            pass

    def _save_config(self):
        try:
            forge_atomic.atomic_write_json(CONFIG_FILE, {
                "enabled": self.enabled,
                "auto_send": self.auto_send,
                "auto_send_nrn": self.auto_send_nrn,
            })
        except Exception:
            pass

    def _auto_send_allowed(self):
        """TCPA guard: never auto-text outside quiet hours (default 8am-9pm ET).
        Disable with FORGE_QUIET_HOURS=0. Window/zone via FORGE_QUIET_START/END/TZ.
        Manual approvals are NOT gated — only autonomous sends."""
        if os.environ.get("FORGE_QUIET_HOURS", "1") == "0":
            return True
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            hr = datetime.now(ZoneInfo(os.environ.get("FORGE_TZ", "America/New_York"))).hour
        except Exception:
            hr = time.localtime().tm_hour
        start = int(os.environ.get("FORGE_QUIET_START", "8"))
        end = int(os.environ.get("FORGE_QUIET_END", "21"))
        return start <= hr < end

    def _load(self):
        if HANDLED_LOG.exists():
            for line in HANDLED_LOG.read_text().splitlines():
                if line.strip():
                    self.handled.add(line.strip())
        if SEEN_CONTACTS_LOG.exists():
            for line in SEEN_CONTACTS_LOG.read_text().splitlines():
                if line.strip():
                    self.seen_contacts.add(line.strip())
        if PROPOSALS_LOG.exists():
            # Append-only log -> last write per id wins; keep only still-pending.
            latest = {}
            for line in PROPOSALS_LOG.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    p = json.loads(line)
                except Exception:
                    continue
                latest[p["id"]] = p
            migrations = []
            for p in latest.values():
                if p.get("status") != "pending":
                    continue
                inbound = p.get("inbound") or ""
                reply = p.get("suggestedReply") or ""
                if _is_denial(inbound):
                    # Upgrade old model-written wrong-number re-pitches in place before
                    # evaluating their stale copy; the deterministic close replaces it.
                    p["classification"] = "WRONG_NUMBER"
                    p["action"] = ACTION_BY_CLASS["WRONG_NUMBER"]["label"]
                    p["tag"] = ACTION_BY_CLASS["WRONG_NUMBER"]["tag"]
                    p["suggestedReply"] = CANNED_WRONG_NUMBER_REPLY
                    p["draftSource"] = "canned_wrong_number"
                    migrations.append(p)
                    self.proposals[p["id"]] = p
                    continue
                reason = _draft_safety_reason(reply, inbound)
                if _is_ambiguous_numeric_message(inbound):
                    reason = "ambiguous numeric-only inbound"
                elif not _is_seller_message(inbound) and not p.get("reengage"):
                    reason = "inbound is our own outreach"
                if reason:
                    p["status"] = "quarantined"
                    p["quarantineReason"] = reason
                    migrations.append(p)
                    self._log("draft_guard", f"Quarantined legacy proposal: {reason}",
                              {"id": p.get("id"), "conversationId": p.get("conversationId")})
                    continue
                self.proposals[p["id"]] = p
            for p in migrations:
                self._persist_proposal(p)

    def _persist_proposal(self, p):
        with open(PROPOSALS_LOG, "a") as f:
            f.write(json.dumps(p) + "\n")

    def _persist_handled(self, key):
        with open(HANDLED_LOG, "a") as f:
            f.write(key + "\n")

    def _mark_seen(self, contact_id):
        """Record a contactId as seen; return True the FIRST time (a brand-new lead)."""
        cid = (contact_id or "").strip()
        if not cid or cid in self.seen_contacts:
            return False
        self.seen_contacts.add(cid)
        try:
            with open(SEEN_CONTACTS_LOG, "a") as f:
                f.write(cid + "\n")
        except Exception:
            pass
        return True

    def _log(self, kind, text, extra=None):
        ev = {"ts": int(time.time() * 1000), "kind": kind, "text": text}
        if extra:
            ev.update(extra)
        self.activity.insert(0, ev)
        del self.activity[120:]

    # -- drafting ------------------------------------------------------------
    def _load_playbook(self):
        """Load the brain guidance Marcus follows: the weekly review playbook PLUS
        the daily-learned Yahjair voice guide. Cached, reloads on mtime change."""
        try:
            import brain_io
            parts, sig = [], []
            for rel in ("Skills/marcus-playbook.md", "Skills/yahjair-voice.md",
                        "Skills/wholesale-seller-texter.md"):
                p = brain_io.VAULT / rel
                if p.is_file():
                    parts.append(p.read_text(errors="ignore"))
                    sig.append(p.stat().st_mtime)
            sig = tuple(sig)
            if getattr(self, "_pb_mtime", None) != sig:
                self._pb_text = "\n\n".join(parts)
                self._pb_mtime = sig
            return self._pb_text
        except Exception:
            return ""

    def _load_reply_rubric(self):
        """The seller-reply DECISION rubric the drafter must read every time: adapt to the
        seller, never a price/offer by text, always drive to a quick call, stand your ground.
        Loaded in FULL (short + non-negotiable) and injected uncapped, separate from the
        [:1500]-sliced voice playbook so the hard rule is never truncated away. mtime-cached."""
        try:
            import brain_io
            p = brain_io.VAULT / "Skills" / "seller-reply-playbook.md"
            if not p.is_file():
                return ""
            sig = p.stat().st_mtime
            if getattr(self, "_rr_mtime", None) != sig:
                txt = p.read_text(errors="ignore")
                # strip the yaml frontmatter — the model wants the body, not metadata
                if txt.startswith("---"):
                    end = txt.find("\n---", 3)
                    if end != -1:
                        txt = txt[end + 4:]
                self._rr_text = txt.strip()
                self._rr_mtime = sig
            return self._rr_text
        except Exception:
            return ""

    def _recent_thread(self, conv_id, fallback=""):
        """Return (recent inbound context, role-labelled history) for grounded drafts.
        Best-effort; the central send gate repeats the read and fails closed."""
        if not conv_id:
            return fallback or "", []
        try:
            data = self.ghl_get(f"/conversations/{conv_id}/messages", {"limit": 12})
            raw = data.get("messages", data) if isinstance(data, dict) else data
            if isinstance(raw, dict):
                raw = raw.get("messages", [])
            ordered = list(reversed(raw or []))  # GHL newest-first -> oldest-first
            inbound = [(m.get("body") or "").strip() for m in ordered
                       if m.get("direction") == "inbound" and (m.get("body") or "").strip()]
            history = []
            for m in ordered[-8:]:
                body = (m.get("body") or "").strip()
                if body:
                    who = "Seller" if m.get("direction") == "inbound" else "You"
                    history.append(f"{who}: {body[:500]}")
            return "\n".join(inbound[-8:]) or (fallback or ""), history
        except Exception:
            return fallback or "", []

    def _recent_seller_context(self, conv_id, fallback=""):
        return self._recent_thread(conv_id, fallback)[0]

    @staticmethod
    def _scrub_voice(text, seller_said=""):
        """Deterministic voice guard on every draft: Yahjair never uses em-dashes,
        semicolons, or exclamation marks (unless the seller used one first). The
        prompt asks for this; this enforces it even when the model slips."""
        if not text:
            return text
        out = text.replace("\u2014", ",").replace("\u2013", ",").replace(";", ",")
        if "!" not in (seller_said or ""):
            out = out.replace("!", ".")
        out = out.replace(" ,", ",").replace(",.", ".").replace("..", ".")
        return " ".join(out.split())

    # Detect a price/offer leaking into OUR outgoing draft. Only MONETARY shapes — kept tight
    # so his real voice ("100%", "5 min", "0 fees", "3 bed 2 bath") never false-triggers:
    #   $ figure ($40, $40k, $40,000) · comma-thousands (40,000) · Nk/N grand/N thousand ·
    #   an offer verb immediately followed by a 2+ digit number (give you 40, offer 40k).
    # Runs on OUR text only — the seller's own stated number is never scrubbed.
    _PRICE_RE = re.compile(
        r"\$\s*\d[\d,]*(\.\d+)?\s*(k|grand|thousand)?"
        r"|\b\d{1,3}(,\d{3})+\b"
        r"|\b\d{1,4}\s*(k\b|grand|thousand)"
        r"|\b(offer|offering|give you|gave you|pay you|get you|can do|could do)\s+\$?\s*\d{2,}",
        re.IGNORECASE,
    )
    # A safe, on-voice fallback that pivots any price talk back to the call — no number.
    _PRICE_FALLBACK = (
        "honestly i dont wanna throw out a random number and waste your time, "
        "you deserve an accurate offer not a lowball, whats a good time for a quick call "
        "today so i can get you a real one"
    )

    def _no_price_over_text(self, text, cls=None, seller_said=""):
        """Hard boundary enforced in CODE, not just the prompt: an agent NEVER sends a
        price/offer/number by text (operator rule — the offer lives on the call). If a draft
        leaks a figure, swap the whole reply for the call-pivot fallback and log it. Returns
        (safe_text, leaked_bool)."""
        if not text:
            return text, False
        if (self._PRICE_RE.search(text)
                or (_SELLER_PRICE_RE.search(seller_said or "")
                    and _PRICE_CONFIRM_RE.search(text))):
            try:
                self._log("price_guard", f"Blocked a texted number in a {cls or '?'} draft "
                          f"— swapped to call-pivot: \"{text[:80]}\"", {})
            except Exception:
                pass
            return self._PRICE_FALLBACK, True
        return text, False

    def _ai_draft(self, first, cls, body, history, hint=None, seller_context=None):
        """Claude-written reply if a key is present; else Marcus's template.

        `hint` (optional) is Scout's recommended re-engage angle for a missed/cold lead;
        when present Marcus reopens the thread on that angle instead of a generic reply."""
        seller_said = body or ""
        safety_context = seller_context or seller_said

        def _template_reply():
            t = self._scrub_voice(draft_reply(first, cls), seller_said=seller_said)
            t, _ = self._no_price_over_text(t, cls, safety_context)
            return t

        if not self.anthropic_key:
            return _template_reply(), "template"
        sys_prompt = (
            "You are Marcus, an acquisitions manager for a real estate wholesaler "
            "(the human is Yahjair). Write ONE short, warm, natural SMS reply to a "
            "property seller. 1-2 sentences, no greeting fluff, sound like a real "
            f"person texting. The seller's message classified as {cls}. "
            "REPLY TO WHAT THE SELLER ACTUALLY SAID — mirror their message, answer their real "
            "question or objection, don't send a canned line. Short, simple, straightforward, "
            "powerful.\n"
            "THE ONE JOB: drive to a quick phone call. The call is where the offer is given "
            "(by a human, on the phone). Your text exists to get them on that call.\n"
            "HARD RULE — NEVER a price/offer over text: do NOT state, negotiate, hint at, or "
            "invent ANY dollar amount, range, or number as an offer (no '$40k', '40,000', "
            "'around 40', 'i can give you...'). If the seller asks for a number, acknowledge "
            "it honestly, say you want to give them a REAL accurate offer not a random guess, "
            "and ask for a quick call. If they push again, stand your ground — deflect a "
            "different natural way, still no number. Never invent addresses either. "
            "Output only the SMS text.\n\n"
            "TEXT EXACTLY LIKE YAHJAIR — this matters:\n"
            "- all lowercase, casual, like thumb-typing fast\n"
            "- NO em-dashes (—), NO semicolons, NO exclamation marks, NO fancy punctuation\n"
            "- minimal commas; skip the comma if a text would still read fine\n"
            "- no corporate/AI tone, no 'I hope this finds you well', no buzzwords\n"
            "- short. one breath. a real person, not a script.\n"
            "The PLAYBOOKS below are how Yahjair actually texts — copy that voice + follow the rules."
        )
        # The CREED (wholesale evidence discipline) — FIRST and never truncated. This is the
        # draft path that reaches a real seller, so "never invent what they said, never put a
        # number in a text" has to be in the prompt before anything else competes with it.
        try:
            import agent_creed
            sys_prompt += agent_creed.block("wholesale")
        except Exception:
            pass
        # The seller-reply DECISION rubric (adapt + never price + push to call + stand ground).
        # Injected in FULL and FIRST so the hard rule is never truncated — this governs WHAT to say.
        rubric = self._load_reply_rubric()
        if rubric:
            sys_prompt += ("\n\n=== SELLER-REPLY PLAYBOOK (read before drafting — follow it) ===\n"
                           + rubric)
        # Closed learning loop: fold in the weekly playbook the review agent maintains.
        playbook = self._load_playbook()
        if playbook:
            sys_prompt += ("\n\nWEEKLY VOICE PLAYBOOK (learned from past messages — copy the voice):\n"
                           + playbook[:1500])
        # Brain: pull relevant vault notes (voice, closing plays, seller psychology) for
        # THIS seller/thread — same per-lead injection Marcus-screening and Atlas already do.
        try:
            import agent_context
            ctx = agent_context.brain_context(
                agent_context.seller_query(first, body, hint),
                header="RELEVANT BRAIN NOTES (your voice, closing plays, seller psychology)")
            if ctx:
                sys_prompt += "\n\n" + ctx
        except Exception:
            pass
        if hint:
            sys_prompt += ("\n\nRE-ENGAGE: this lead went cold after showing real interest. "
                           "Scout's recommended angle: " + str(hint)[:300]
                           + "\nReopen the conversation naturally on that angle — like you're "
                           "picking back up with someone you already talked to, not a cold blast.")
        convo = "\n".join(history[-6:]) if history else f"Seller: {body}"
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps({
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "system": sys_prompt,
                    "messages": [{"role": "user", "content":
                                  f"Conversation so far:\n{convo}\n\nWrite Marcus's reply:"}],
                }).encode(),
                headers={
                    "x-api-key": self.anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            try:  # cost telemetry — best-effort, never blocks the draft
                import cost_tracker
                u = data.get("usage") or {}
                cost_tracker.record_anthropic("claude-haiku-4-5-20251001",
                                              u.get("input_tokens"), u.get("output_tokens"))
            except Exception:
                pass
            text = "".join(b.get("text", "") for b in data.get("content", [])).strip()
            text = self._scrub_voice(text, seller_said=body or "")
            # Hard boundary in code: if the model leaked a number, swap for the call-pivot.
            text, leaked = self._no_price_over_text(text, cls, safety_context)
            unsafe = _draft_safety_reason(text, safety_context)
            if unsafe:
                self.last_error = f"AI draft blocked: {unsafe}"
                self._log("draft_guard", self.last_error, {"classification": cls})
                return None, "blocked"
            return (text or _template_reply()), ("price_guard" if leaked else "claude")
        except urllib.error.HTTPError as e:
            # str(e) is just "HTTP Error 400: Bad Request" — read the body so
            # last_error shows the real Anthropic reason (e.g. low credit balance).
            try:
                err_body = json.loads(e.read().decode())
                msg = (err_body.get("error") or {}).get("message") or str(e)
            except Exception:  # noqa: BLE001
                msg = str(e)
            self.last_error = f"AI draft failed: Anthropic API error ({e.code}): {msg}"
            return _template_reply(), "template"
        except Exception as e:  # noqa: BLE001
            self.last_error = f"AI draft failed: {e}"
            return _template_reply(), "template"

    # -- the trigger loop ----------------------------------------------------
    def poll_once(self):
        if not self.enabled:
            return
        try:
            data = self.ghl_get("/conversations/search", {
                "locationId": self.location_id, "limit": 100,
                "sortBy": "last_message_date",
            })
            convos = data.get("conversations", []) or []
            for c in convos:
                if (c.get("lastMessageDirection") != "inbound"
                        or (c.get("unreadCount") or 0) <= 0):
                    continue
                key = f"{c.get('id')}:{c.get('lastMessageDate')}"
                if key in self.handled:
                    continue
                # Never draft a reply to OUR OWN outreach mistakenly flagged inbound.
                if not _is_seller_message(c.get("lastMessageBody")):
                    with self.lock:
                        self.handled.add(key)
                        self._persist_handled(key)
                    self._log("skipped", "Skipped own outreach (not a seller message) — "
                              f"{(c.get('fullName') or c.get('contactName') or 'contact')}", {})
                    continue
                self._make_proposal(c, key)
            self.last_poll = int(time.time() * 1000)
            self.last_error = None
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)

    def _make_proposal(self, c, key, hint=None, body_override=None, allow_auto=True):
        # allow_auto=False: the CALLER owns the send decision (Scout handoff wants a gated
        # proposal; ACE approves it itself). Without this, TEST MODE's auto-send below fires
        # inside the draft call, sends immediately and pops the proposal — so the caller's
        # lookup finds nothing ("proposal not found after draft") and a handoff that is
        # supposed to stay review-gated goes out on its own. Auto-send belongs to poll_once.
        # body_override: for a re-engage handoff where OUR text is the last message, draft
        # off the seller's real earlier words (passed in) instead of our own outbound.
        body = (body_override if body_override else c.get("lastMessageBody")) or ""
        if _is_ambiguous_numeric_message(body):
            with self.lock:
                self.handled.add(key)
                self._persist_handled(key)
                self._log("draft_guard", "Held ambiguous numeric-only inbound for human review",
                          {"conversationId": c.get("id"), "inbound": body})
            return {"error": "ambiguous numeric-only inbound", "gate": "draft_context"}
        cls = classify(body)
        # Any "not selling / not right now" seller (but NOT a DNC/STOP) gets
        # Yahjair's fixed referral message verbatim — overrides the AI draft.
        if cls != "DNC" and (cls == "NRN" or _is_soft_no(body)):
            cls = "NRN"
        if _is_denial(body):
            cls = "WRONG_NUMBER"
        full = c.get("fullName") or c.get("contactName") or ""
        first = (full.split() or ["there"])[0]
        action = ACTION_BY_CLASS.get(cls, ACTION_BY_CLASS["CONTINUE"])

        with self.lock:
            self.handled.add(key)
            self._persist_handled(key)

            # DNC: auto-suppress — tag, never reply. Safe, compliance-positive.
            if action["kind"] == "suppress":
                try:
                    self.ghl_post(f"/contacts/{c.get('contactId')}/tags", {"tags": [action["tag"]]})
                except Exception:
                    pass
                self.counts["suppressed"] += 1
                self._log("suppress", f"Suppressed {full or 'contact'} (said STOP) — tagged DNC",
                          {"contactId": c.get("contactId")})
                return

            # A hinted handoff is an operator-chosen re-engage of a cold lead — always
            # draft a real reply on Scout's angle, even if the last text reads soft-no.
            seller_context = body
            if cls == "WRONG_NUMBER":
                reply, source = CANNED_WRONG_NUMBER_REPLY, "canned_wrong_number"
            elif cls == "NRN" and not hint:
                reply, source = CANNED_NRN_REPLY, "canned"
            else:
                seller_context, recent_history = self._recent_thread(c.get("id"), body)
                reply, source = self._ai_draft(first, cls, body, recent_history, hint=hint,
                                               seller_context=seller_context)
            unsafe = _draft_safety_reason(reply, seller_context)
            if unsafe:
                self.last_error = f"Draft blocked before queue: {unsafe}"
                self._log("draft_guard", self.last_error,
                          {"conversationId": c.get("id"), "classification": cls})
                return {"error": self.last_error, "gate": "draft_safety"}
            # Speed-to-lead: first time we've EVER proposed for this contact = a brand-new
            # lead entering the funnel. Flag it so the Telegram ping shouts 🆕 (reply fast).
            # A re-engage (hint) is by definition an old lead, never "new".
            is_new = (not hint) and self._mark_seen(c.get("contactId"))
            pid = f"p_{c.get('id')}_{c.get('lastMessageDate')}"
            proposal = {
                "id": pid,
                "status": "pending",
                "ts": int(time.time() * 1000),
                "conversationId": c.get("id"),
                "contactId": c.get("contactId"),
                "name": full or "(unknown)",
                "phone": c.get("phone") or "",
                "inbound": body,
                "classification": cls,
                "action": action["label"],
                "tag": action["tag"],
                "suggestedReply": reply,
                "draftSource": source,
                "unread": c.get("unreadCount") or 0,
                "reengage": bool(hint),
                "newLead": bool(is_new),
            }
            self.proposals[pid] = proposal
            self._persist_proposal(proposal)
            # Broadcast a warm-or-better proposal on the bus (best-effort). The notifier
            # re-checks the warm+ tier; skipping NRN/DNC here keeps dead leads off the bus.
            if cls not in ("NRN", "DNC"):
                try:
                    import agent_bus
                    lead_tag = "🆕 NEW LEAD — reply fast. " if is_new else ""
                    agent_bus.send("marcus", "all", "alert",
                        f"{lead_tag}✅ Reply ready for {full or 'a seller'} ({cls}) — review to send.",
                        {"type": "proposal", "pid": pid, "convId": c.get("id"), "contactId": c.get("contactId"),
                         "name": full or "(unknown)", "cls": cls, "new_lead": bool(is_new),
                         "inbound": body, "reply": reply})
                except Exception:
                    pass
            self.counts["proposed"] += 1
            self._log("propose", f"{cls}: {full or 'contact'} — \"{body[:60]}\"",
                      {"id": pid})

            # Auto-send if globally enabled, OR if this is the safe canned NRN reply.
            # Held back outside quiet hours -> stays a pending proposal for morning.
            # Skipped entirely when the caller owns the send (allow_auto=False) — see the
            # note on the signature: otherwise this steals the proposal out from under them.
            if allow_auto:
                if test_mode.is_test(c.get("phone")):
                    proposal["autonomous"] = True
                    self._send(pid, reply)
                    self._log("autosend", f"TEST MODE — auto-replied to {full or 'contact'}", {"id": pid})
                else:
                    wants_auto = self.auto_send or (cls == "NRN" and source == "canned" and self.auto_send_nrn)
                    if wants_auto and self._auto_send_allowed():
                        proposal["autonomous"] = True
                        self._send(pid, reply)
                    elif wants_auto:
                        self._log("deferred", f"Quiet hours — held auto-reply to {full or 'contact'} "
                                  f"for review", {"id": pid})
            return {"ok": True, "proposalId": pid}

    def make_proposal_for(self, conversation_id, contact_id=None, hint=None, seller_said=None):
        """Force a reply proposal for one conversation — used by Scout's handoff so a
        hot/missed lead lands in Marcus's approval inbox with a drafted reply (still gated).

        `contact_id` resolves leads deeper than the latest 100 threads (a missed-lead sweep
        scans hundreds back). `hint` is Scout's re-engage angle. `seller_said` is the
        seller's real last words — used to ground the draft when OUR follow-up is the last
        message in the thread (the classic cold/missed lead)."""
        if not conversation_id:
            return {"error": "conversationId required"}
        try:
            data = self.ghl_get("/conversations/search", {
                "locationId": self.location_id, "limit": 100,
                "sortBy": "last_message_date"})
            convos = data.get("conversations", []) or []
            c = next((x for x in convos if x.get("id") == conversation_id), None)
            # Not in the recent window — pull the contact's own thread directly so old
            # missed leads still hand off cleanly.
            if not c and contact_id:
                scoped = self.ghl_get("/conversations/search", {
                    "locationId": self.location_id, "contactId": contact_id})
                cands = scoped.get("conversations", []) or []
                # Require the exact conversation — never silently draft against a
                # different thread for the same contact.
                c = next((x for x in cands if x.get("id") == conversation_id), None)
            if not c:
                return {"error": "conversation not found"}
            # Block drafting a reply TO our own outreach — UNLESS this is a deliberate
            # re-engage (hint present). A missed lead's last message is often our own
            # unanswered follow-up; re-engaging it is exactly the point.
            if not _is_seller_message(c.get("lastMessageBody")) and not hint:
                return {"error": "last message is our own outreach, not a seller message"}
            key = f"{c.get('id')}:{c.get('lastMessageDate')}"
            with self.lock:
                self.handled.discard(key)            # allow a fresh proposal
                self.proposals.pop(f"p_{c.get('id')}_{c.get('lastMessageDate')}", None)
            # allow_auto=False — this proposal is REVIEW-GATED by contract. Scout's handoff
            # wants it sitting in the approval inbox; ACE approves it itself (autonomous=True
            # → full sms_guard stack). Letting _make_proposal auto-send here would both
            # bypass the gate and pop the proposal before the caller can find it.
            made = self._make_proposal(c, key, hint=hint, body_override=seller_said,
                                       allow_auto=False)
            if not (made or {}).get("ok"):
                return made or {"error": "draft was not queued", "gate": "draft_safety"}
            return {"ok": True, "conversationId": conversation_id,
                    "proposalId": made.get("proposalId"), "reengage": bool(hint)}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    # -- actions -------------------------------------------------------------
    def _send(self, pid, message):
        p = self.proposals.get(pid)
        if not p:
            return {"error": "not found"}
        unsafe = _draft_safety_reason(message, p.get("inbound") or "")
        if unsafe:
            self._log("draft_guard", f"Blocked proposal at send boundary: {unsafe}",
                      {"id": pid, "conversationId": p.get("conversationId")})
            return {"error": f"unsafe draft: {unsafe}", "gate": "draft_safety"}
        gate = {}
        safety_check = getattr(self, "safety_check", None)
        if not callable(safety_check):
            return {"error": "central sms_guard unavailable", "gate": "sms_guard_missing"}
        send_kind = "marcus_nrn" if p.get("classification") == "NRN" else "marcus_approve"
        gate = safety_check(
            p.get("contactId"),
            message,
            conv_id=p.get("conversationId"),
            name=p.get("name"),
            last_seller_message=p.get("inbound"),
            kind=send_kind,
            autonomous=bool(p.get("autonomous") or p.get("autopilot")),
        )
        if not gate.get("ok"):
            return gate
        reservation = gate.get("reservation")
        try:
            self.ghl_post("/conversations/messages", {
                "type": "SMS",
                "conversationId": p["conversationId"],
                "contactId": p["contactId"],
                "message": message,
            })
            if p.get("tag"):
                try:
                    self.ghl_post(f"/contacts/{p['contactId']}/tags", {"tags": [p["tag"]]})
                except Exception:
                    pass
            p["status"] = "sent"
            p["sentReply"] = message
            self._persist_proposal(p)
            self.counts["sent"] += 1
            safety_record = getattr(self, "safety_record", None)
            if callable(safety_record):
                safety_record(reservation=reservation, conv_id=p["conversationId"],
                              contact_id=p["contactId"], message=message,
                              kind="marcus_nrn" if p.get("classification") == "NRN" else "marcus_approve")
            self._log("sent", f"Replied to {p['name']} ({p['classification']})", {"id": pid})
            self.proposals.pop(pid, None)
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            safety_release = getattr(self, "safety_release", None)
            if callable(safety_release):
                try:
                    safety_release(reservation)
                except Exception:
                    pass
            self.last_error = str(e)
            return {"error": str(e)}

    def approve(self, pid, edited=None):
        with self.lock:
            p = self.proposals.get(pid)
            if not p:
                return {"error": "proposal not found or already handled"}
            return self._send(pid, edited or p["suggestedReply"])

    def dismiss(self, pid):
        with self.lock:
            p = self.proposals.pop(pid, None)
            if not p:
                return {"error": "not found"}
            p["status"] = "dismissed"
            self._persist_proposal(p)
            self.counts["dismissed"] += 1
            self._log("dismiss", f"Dismissed proposal for {p['name']}", {"id": pid})
            return {"ok": True}

    def toggle(self, enabled=None, auto_send=None, auto_send_nrn=None):
        with self.lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if auto_send is not None:
                self.auto_send = bool(auto_send)
            if auto_send_nrn is not None:
                self.auto_send_nrn = bool(auto_send_nrn)
            self._save_config()  # survive restart
            self._log("config", f"enabled={self.enabled} auto_send={self.auto_send} "
                                f"auto_send_nrn={self.auto_send_nrn}")
            return self.status()

    # -- snapshot for the dashboard -----------------------------------------
    def status(self):
        breakdown = {}
        for p in self.proposals.values():
            breakdown[p["classification"]] = breakdown.get(p["classification"], 0) + 1
        return {
            "enabled": self.enabled,
            "autoSend": self.auto_send,
            "autoSendNrn": self.auto_send_nrn,
            "online": True,
            "hasAI": bool(self.anthropic_key),
            "draftMode": "claude" if self.anthropic_key else "templates",
            "lastPoll": self.last_poll,
            "pollInterval": self.poll_interval,
            "pending": len(self.proposals),
            "breakdown": breakdown,
            "counts": self.counts,
            "lastError": self.last_error,
            "task": (f"{len(self.proposals)} seller replies waiting on you"
                     if self.proposals else "Idle — watching GoHighLevel for replies"),
        }

    def proposals_list(self):
        return sorted(self.proposals.values(), key=lambda p: -p["ts"])

    def run_forever(self):
        while True:
            try:
                self.poll_once()
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
            try:
                forge_heartbeat.beat("marcus_sms", self.poll_interval,
                                     "Marcus SMS responder",
                                     error=self.last_error)
            except Exception:
                pass
            time.sleep(self.poll_interval)
