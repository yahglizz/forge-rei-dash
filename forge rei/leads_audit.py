#!/usr/bin/env python3
"""Standalone, READ-ONLY GHL audit: pull leads for a target state, pull each contact's
full message thread, classify reply status, dump a CSV.

GET requests only. No sends, no tags, no pipeline moves. Safe to re-run.

Run: python3 leads_audit.py
"""
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TARGET_STATE = "OH"  # 2-letter or full name; case-insensitive exact match against contact.state

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "..", "marcus-wholesale-agent", "config", "ghl.env")
OUT_DIR = os.path.join(HERE, "marcus_state", "leads_export")

# The compliance strings live in ONE place: seller_classify.py, the tracked module
# the live send gate uses. Importing it here (stdlib-only, same folder, no side
# effects) is what stops the offline blast scrubber and production from drifting.
sys.path.insert(0, HERE)
import seller_classify  # noqa: E402
OUT_CSV = os.path.join(OUT_DIR, "ohio_leads_audit.csv")

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

PAGE_LIMIT = 100
CONV_LIMIT = 20
MSG_LIMIT = 100
RETRY_MAX = 3
RETRY_STATUSES = {429, 500, 502, 503}


# ---------------------------------------------------------------------------
# Env / auth
# ---------------------------------------------------------------------------
def load_env(path):
    cfg = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


ENV = load_env(ENV_PATH)
API_KEY = ENV["GHL_API_KEY"]
LOCATION_ID = ENV["GHL_LOCATION_ID"]
BASE_URL = ENV.get("GHL_BASE_URL", "https://services.leadconnectorhq.com")
API_VERSION = ENV.get("GHL_API_VERSION", "2021-07-28")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Version": API_VERSION,
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
}

api_call_count = 0


def ghl_get(path, params=None):
    """GET only. Retries on 429/500/502/503 or transient network error."""
    global api_call_count
    url = f"{BASE_URL}{path}"
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{qs}"
    last_err = None
    for attempt in range(1, RETRY_MAX + 1):
        api_call_count += 1
        req = urllib.request.Request(url, headers=HEADERS, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < RETRY_MAX:
                time.sleep(0.6 * attempt)
                last_err = e
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < RETRY_MAX:
                time.sleep(0.6 * attempt)
                last_err = e
                continue
            raise
    raise last_err or RuntimeError("ghl_get failed with no response")


# ---------------------------------------------------------------------------
# Seller-reply classification — ported verbatim from marcus_engine.py:378-507
# ---------------------------------------------------------------------------
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
    "following up on my note", "still buying as-is",
    "would you consider selling", "have you considered selling",
    "interested in selling your", "consider an offer on",
    "cash for your property", "cash for your home",
    "looking to purchase your", "interested in buying your", "buy your property",
    "buy your house", "buy your home", "are you the owner of the property",
    "are you still looking to sell", "still looking to sell", "still interested in selling",
    "this is yahjair", "hey it's yahjair", "this is forge",
    "touch of blessing", "touch of blessings", "we just missed your call",
    "how can we help you today",
]

_OUR_OUTREACH_RE = re.compile(
    r"(?i)^\s*(?:hey|hi|hello)?\s*[a-z'-]{0,30}[, ]*"
    r"(?:this is yahjair|it'?s yahjair|i(?:'m| am) (?:reaching|following|calling|texting)|"
    r"i (?:wanted|was trying|tried) to (?:reach|call|text|see|ask)|"
    r"we(?:'re| are) (?:looking|interested|buying)|would you (?:consider|be open to) selling)\b"
)


# Phrases a seller can legitimately echo back at us. On their own they mean "our
# outreach" only inside a full-length pitch; a SHORT inbound that contains one is
# the seller talking. Measured on 690 real Ohio outbound + 365 inbound messages
# (2026-08-21): the shortest of our own messages caught by an echoable-only hit is
# 47 chars ("Elizabeth with a touch of blessings home buyers"); the only seller
# reply eaten by one is 19 chars ("Touch of Blessings?", contact MY1qNVo5dCGgbJASuyWV,
# an engaged question we deleted). 32 sits between them with margin on both sides.
# ponytail: length heuristic, not semantics -- if a real pitch ever ships under 32
# chars, add its distinctive words to _OUR_OUTREACH_PHRASES instead of raising this.
_ECHOABLE_OUTREACH_PHRASES = {
    "as-is", "cash offer", "close fast", "close quickly", "we pay cash",
    "no realtor", "no agents", "touch of blessing", "touch of blessings",
}
_ECHO_SHORT_MAX = 32


def _is_our_message(body):
    """True if the text reads like OUR outreach (not a seller's reply)."""
    b = (body or "").lower()
    hits = [p for p in _OUR_OUTREACH_PHRASES if p in b]
    if _OUR_OUTREACH_RE.search(body or ""):
        return True
    if not hits:
        return False
    # Only echoable marketing/brand words, in a message far too short to be our
    # pitch -> the seller is quoting us back, not us texting ourselves.
    if len(b.strip()) <= _ECHO_SHORT_MAX and all(h in _ECHOABLE_OUTREACH_PHRASES
                                                  for h in hits):
        return False
    return True


_REACT_POS = ("👍", "❤", "♥", "😍", "😎", "😂", "🤣", "🔥", "👏", "🙏", "✅", "💯",
              "😊", "🙂", "👌", "💪", "liked", "loved", "laughed", "emphasized")
_REACT_NEG = ("👎", "disliked")
_REACT_Q = ("❓", "❔", "questioned")
_REACT_LEAD = re.compile(r"^[\s​‌‍⁦-⁩️]+")


def _reaction_kind(body):
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
    return _reaction_kind(body) is not None


def _is_seller_message(body):
    """True for genuine seller text, including reactions that quote our outreach."""
    return bool((body or "").strip()) and (
        not _is_our_message(body) or _is_reaction(body)
    )


# ---------------------------------------------------------------------------
# Dead-end classifiers — ported verbatim from marcus_engine.py (DNC keywords:
# _fallback_classify lines 76; soft_no: 238-250; hard_no: 257-267; opt_out: 328-371;
# denial: 272-363). A "STOP"/"not interested"/"sold"/wrong-number reply is a genuine
# seller message but must NEVER be treated as a re-engage-worthy or pending-response
# lead — re-texting these is a compliance risk (DNC) or just wasted/annoying outreach.
# ---------------------------------------------------------------------------
_DNC_PHRASES = ["stop", "unsubscribe", "remove me", "do not text"]

_SOFT_NO_PHRASES = [
    "not for sale", "not selling", "not interested", "no longer selling",
    "not looking to sell", "not gonna sell", "not going to sell", "won't sell",
    "wont sell", "not right now", "not at this time",
    "not at the moment", "maybe later", "not the right time",
    "not ready to sell", "decided not to sell", "changed my mind",
    "keeping the house", "keeping the property",
]

# Anchored on purpose: a search-anywhere "no" would eat "no rush", "no problem",
# "I have no idea". Recall is added by widening the ALTERNATION (standalone forms
# found in the Ohio data: "Nfs", "No sale.", "Not intrested"), never by unanchoring.
_HARD_NO_RE = re.compile(
    r"^\s*(no+|nope|nah+|no\s*thanks?|no\s*thank\s*you|not\s*int[a-z]{0,4}sted"
    r"|no\s*i'?m?\s*good|no\s*sorry|sorry\s*no|not\s*for\s*me|no\s*thx"
    r"|nfs|no\s*sale|not\s*sell?ing|hard\s*(?:no|pass)|pass)"
    r"[\s.!?,'\"\-]*$",
    re.IGNORECASE,
)

# Unambiguous refusals that can sit inside a longer sentence. Kept tiny on purpose.
_REFUSAL_ANY_RE = re.compile(
    r"(?i)\bnfs\b|\bnot\s+for\s+sale\b|\bno\s+sale\b"
    r"|\bnot\s+int[a-z]{0,4}sted\s+in\s+sell")

_OPT_OUT_PHRASES = [
    "remove my number", "take me off", "off your list", "off your website",
    "leave me alone", "stop bothering", "stop contacting", "stop messaging",
    "stop texting me", "quit texting", "quit calling", "quit contacting",
    "harassing me", "this is harassment",
    # Added for this audit (same "remove me" family, not yet in marcus_engine.py's
    # list — found live in the Ohio data: "please delete my contact info"). Worth
    # backporting.
    "delete my contact", "delete my info", "delete my number", "remove my info",
    "remove my contact",
]

_DENIAL_CLAUSE = (
    r"(?:"
    r"i\s+(?:do\s+not|don'?t)\s+know\s+you"
    r"|(?:(?:(?:i\s+(?:think|believe)\s+)?you\s+(?:have|got)"
    r"|you(?:'ve|ve)\s+got|this\s+is|it(?:'?s|\s+is))\s+)?"
    r"(?:the\s+)?wrong\s+"
    r"(?:number|person|contact|recipient|owner|seller)"
    r"|(?:i(?:'?m|\s+am)\s+)?not\s+who\s+you\s+think(?:\s+i\s+am)?"
    r"|(?:i(?:'?m|\s+am)\s+)?not\s+(?:the\s+person\s+)?"
    r"who\s+you(?:'?re|\s+are)\s+looking\s+for"
    r")"
)
_DENIAL_MESSAGE_RE = re.compile(
    rf"^\s*(?:sorry(?:\s*[,;:-]\s*(?:but\s+)?|\s+but\s+|\s+))?"
    rf"{_DENIAL_CLAUSE}"
    rf"(?:\s*[,;.!-]+\s*{_DENIAL_CLAUSE})*\s*[.!?]*\s*$",
    re.IGNORECASE,
)
_STANDALONE_DENIAL_RE = re.compile(
    r"^\s*(?:"
    r"did\s+i\s+call\s+you|did\s+you\s+call\s+me|you\s+called\s+me|"
    r"i\s+(?:did\s+not|didn'?t)\s+call\s+you|"
    r"(?:i\s+)?never\s+(?:called|talked\s+to|spoke\s+to)\s+you|"
    # "who is this / who are you / who dis" REMOVED 2026-08-21: it is the single
    # most normal reply to a cold text, not a wrong number. It killed 5 real leads
    # in the Ohio audit (D3ugTFgL48MGaf4M1icx had SIX inbound messages). Production
    # seller_classify already calls this HELP; this now matches.
    r"what\s+is\s+this"
    r")\s*[?.!,]*(?:\s*(?:no+|nope|nah+))?\s*[?.!,]*$",
    re.IGNORECASE,
)
_IDENTITY_DENIAL_RE = re.compile(
    r"^\s*(?:"
    r"(?:i\s*am|i'?m)\s+not\s+(?:the\s+)?(?:owner|seller)(?:\s+anymore)?"
    r"|i\s+(?:do\s+not|don'?t)\s+own\s+"
    r"(?:it|this|that|the\s+(?:house|home|property))(?:\s+anymore)?"
    r"|(?:i(?:'ve|\s+have)?\s+)?never\s+owned\s+"
    r"(?:it|this|that|the\s+(?:house|home|property))"
    r"|(?:this|that)(?:\s+is\s+not|\s+isn'?t|'?s\s+not)\s+"
    r"(?:me|my\s+(?:house|home|property))(?:\s+anymore)?"
    r")(?=\s*(?:[.!?]+(?:\s|$)|$))",
    re.IGNORECASE,
)

_NAMED_IDENTITY_DENIAL_RE = re.compile(
    r"^\s*(?:(?:i\s*am|i'?m)\s+not"
    r"|(?:this|that)(?:\s+is\s+not|\s+isn'?t|'?s\s+not))\s+"
    r"(?P<name>[a-z][a-z'-]*(?:\s+[a-z][a-z'-]*)*)"
    r"(?=\s*(?:[.!?]+(?:\s|$)|$))",
    re.IGNORECASE,
)


def _named_identity_match(body, expected_name=None):
    """Return True/False for a named identity statement, or None when absent.
    Ported from marcus_engine.py:336-345."""
    named = _NAMED_IDENTITY_DENIAL_RE.search(body or "")
    if not named:
        return None
    expected_tokens = re.findall(r"[a-z][a-z'-]*", (expected_name or "").lower())
    if not expected_tokens or expected_tokens[0] == "unknown":
        return False
    denied_name = " ".join(re.findall(r"[a-z][a-z'-]*", named.group("name").lower()))
    return denied_name in (expected_tokens[0], " ".join(expected_tokens))


def _is_dnc(body):
    """Compliance-grade opt-out, delegated to the tracked live classifier.

    The legacy substring list is still ORed in MINUS bare "stop", so this can only
    gain recall, never lose it. Bare "stop" as a substring was matching inside words
    ("Chri-STOP-her") and inside "feel free to stop by"; the STOPALL family it DID
    catch by accident (77 real Ohio opt-outs) is now matched explicitly by
    seller_classify._STOP_KEYWORD_RE. Verified: the STOPALL count did not drop."""
    b = (body or "").lower()
    if not b.strip():
        return False
    if seller_classify.is_opt_out(body):
        return True
    return any(p in b for p in _DNC_PHRASES if p != "stop")


def _is_opt_out(body):
    b = (body or "").lower()
    return any(p in b for p in _OPT_OUT_PHRASES)


def _is_soft_no(body):
    b = (body or "").lower()
    return any(p in b for p in _SOFT_NO_PHRASES)


def _is_hard_no(body):
    return bool(_HARD_NO_RE.match(body or "") or _REFUSAL_ANY_RE.search(body or ""))


# The rules above are effectively fullmatch (^...$), so ANY extra clause defeated
# them -- "Look man you got the wrong number. Good luck." stayed in a KEEP bucket
# (55 such rows in the Ohio audit). This is the search-anywhere companion: it fires
# only on an unambiguous wrong-number/not-the-owner core phrase, never on a bare "no".
_WRONG_NUMBER_ANY_RE = re.compile(
    r"(?i)\b(?:wrong|wring|worng|incorrect)\s+(?:number|person|phone|guy|gal|lady|"
    r"contact|name)\b"
    r"|\byou(?:'?ve|\s+have|\s+got|\s+hv)?\s+(?:have|got)?\s*(?:the\s+)?wrong\b"
    r"|\b(?:that|this)(?:'?s|\s+is)\s+not\s+my\s+(?:name|number)\b"
    r"|\bi\s+(?:do\s+not|don'?t|dont)\s+own\s+(?:it|this|that|any|the|a\b)"
    r"|\bnever\s+owned\b"
    r"|\bno\s*(?:one|body)\s+here\s+owns\b"
    r"|\bnot\s+(?:the\s+)?(?:owner|seller)\b")


def _is_denial(body, expected_name=None):
    if _WRONG_NUMBER_ANY_RE.search(body or ""):
        return True
    if _DENIAL_MESSAGE_RE.match(body or ""):
        return True
    if _STANDALONE_DENIAL_RE.match(body or ""):
        return True
    if _IDENTITY_DENIAL_RE.search(body or ""):
        return True
    return _named_identity_match(body, expected_name) is True


# NOT ported from existing code — no "already sold" classifier exists anywhere in
# marcus_engine.py/scout_triage.py today (verified by grep). Added here for this audit
# only, narrow standalone-message match so it can't misfire inside a longer reply. Flag
# to the operator: worth backporting into marcus_engine.py's real dead-end detection.
_SOLD_RE = re.compile(
    r"^\s*(?:(?:it'?s|its|already|house\s+is|home\s+is|property\s+is)\s+)?sold[\s.!?]*$",
    re.IGNORECASE,
)

# Search-anywhere companion. _SOLD_RE fired exactly ONCE in 5,527 rows because it is
# fullmatch: "No it's been sold", "It's sold please forget about it", "Sold them all
# sorry" and "Carbon has been sold" all stayed in KEEP buckets. _SOLD_RE had ZERO
# false positives and that is the property to protect, so every branch below needs a
# subject or an auxiliary verb glued to "sold", and _NOT_SOLD_RE vetoes first.
_SOLD_ANY_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:has|have|had|hs)\s+(?:been\s+)?sold"
    r"|(?:is|was|are|were)\s+sold"
    r"|(?:it|that|this|its|it'?s|they|house|home|property|place)\s*"
    r"(?:'?s|is|was|been|already)?\s*(?:been\s+)?sold"
    r"|already\s+sold"
    r"|sold\s+(?:it|them|that|this|already|last|off|the\s+\w+)"
    r")\b")

# Anything that means NOT sold. Checked first, so "not sold yet", "thinking of
# getting it sold" and "sold my other house" can never reach the rule above.
_NOT_SOLD_RE = re.compile(
    r"(?i)\b(?:not|isn'?t|hasn'?t|haven'?t|hadn'?t|aren'?t|wasn'?t|weren'?t|never|"
    r"won'?t|would|could|should|might|may|if|when|once|unless|before|until|"
    r"get(?:ting)?|to\s+be|want(?:ing|ed)?\s+to|trying\s+to|thinking\s+(?:of|about)|"
    r"plan(?:ning)?\s+to|going\s+to|hoping\s+to|need(?:ing)?\s+to|like\s+to)\s+"
    r"(?:\w+\s+){0,3}?sold\b"
    r"|\bsold\s+(?:my\s+|the\s+|another\s+)?other\b"
    r"|\bnot\s+for\s+sale\b")


def _is_sold(body):
    b = (body or "").strip()
    if not b:
        return False
    if _NOT_SOLD_RE.search(b):
        return False
    return bool(_SOLD_RE.match(b) or _SOLD_ANY_RE.search(b))


def _compliance_reason(inbound_msgs):
    """dnc/opt-out found ANYWHERE in the thread wins, permanently.

    _dead_end_reason only ever saw the LAST inbound. 11+ Ohio threads had an explicit
    seller opt-out earlier with a benign final message -- Is62uAj55dJ5UPcUguzy said
    "Please stop damn texting me" and then sent a bare emoji, and classified
    active_pending_us. A seller can change their mind about SELLING; nobody un-says
    STOP. Non-compliance dead ends (sold/hard_no/wrong_number) deliberately stay on
    the most recent genuine reply."""
    reason = None
    for m in inbound_msgs:
        body = m.get("body")
        if _is_dnc(body):
            return "dnc"
        if reason is None and _is_opt_out(body):
            reason = "opt_out"
    return reason


# Timing objections ("call me in the spring") that _SOFT_NO_PHRASES has no word for --
# it contains no "later"/"few months" form at all, so genuine timing leads land in
# active_pending_us/replied_then_cold instead of soft_no. Consumed by
# full_leads_audit.py to re-label them soft_no_revisit; it is NEVER an exclusion here,
# so a false positive costs a copy angle, not a lead.
_TIMING_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:call|text|hit|reach|contact|check|try|get)\s+(?:me\s+|back\s+|up\s+|"
    r"with\s+me\s+)*(?:back\s+)?(?:in|around|after|next|later|this\s+(?:spring|"
    r"summer|fall|winter))\b"
    r"|give\s+me\s+(?:a\s+)?(?:\d{1,2}|few|couple(?:\s+of)?|some)\s*"
    r"(?:more\s+)?(?:days?|weeks?|months?|years?)"
    r"|check\s+back\s+(?:in|with|next|later|around)"
    r"|(?:in|after)\s+(?:a\s+)?(?:few|couple(?:\s+of)?|\d{1,2})\s+"
    r"(?:more\s+)?(?:days?|weeks?|months?|years?)"
    r"|(?:next|this\s+coming)\s+(?:spring|summer|fall|autumn|winter|year|month)"
    r"|down\s+the\s+road|later\s+(?:this|next)\s+year"
    r"|maybe\s+(?:in|next|later)|ask\s+me\s+(?:again|later)"
    r")\b")


def _is_timing(body):
    return bool(_TIMING_RE.search(body or ""))


def _dead_end_reason(body, expected_name=None):
    """Priority order: compliance-grade first (DNC/opt-out never expire), then
    content-based dead ends. None means the message is a live, actionable seller reply."""
    if body is None:
        return None
    if _is_dnc(body):
        return "dnc"
    if _is_opt_out(body):
        return "opt_out"
    if _is_denial(body, expected_name):
        return "wrong_number"
    if _is_sold(body):
        return "sold"
    if _is_hard_no(body):
        return "hard_no"
    if _is_soft_no(body):
        return "soft_no"
    return None


def _to_ms(v):
    """Normalize a GHL timestamp (epoch int/str OR ISO-8601 string) to epoch ms, or None.
    Ported from scout_triage.py:_to_ms — GHL is inconsistent: conversation
    lastMessageDate is epoch-ms, but message dateAdded (what /messages actually
    returns) is an ISO-8601 string. Ignoring this would silently sort/format wrong."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# GHL pulls
# ---------------------------------------------------------------------------
def list_all_contacts():
    """Cursor-paginate /contacts/ for the location. Returns list of raw contact dicts.

    GHL's `dateAdded` on each contact is an ISO string, not the epoch-ms cursor the
    pagination actually wants — the real cursor comes back in the response's `meta`
    block (`meta.startAfter` epoch ms + `meta.startAfterId`). Fall back to the last
    contact's own `startAfter` field (a [epoch_ms, id] pair GHL attaches) if meta is
    ever missing.
    """
    contacts = []
    start_after = None
    start_after_id = None
    while True:
        params = {"locationId": LOCATION_ID, "limit": PAGE_LIMIT}
        if start_after is not None:
            params["startAfter"] = start_after
            params["startAfterId"] = start_after_id
        data = ghl_get("/contacts/", params)
        page = data.get("contacts") or []
        if not page:
            break
        contacts.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        meta = data.get("meta") or {}
        start_after = meta.get("startAfter")
        start_after_id = meta.get("startAfterId")
        if start_after is None or start_after_id is None:
            last = page[-1]
            cursor = last.get("startAfter")
            if isinstance(cursor, list) and len(cursor) == 2:
                start_after, start_after_id = cursor
            else:
                start_after, start_after_id = None, None
        if start_after is None or start_after_id is None:
            break
    return contacts


def list_conversations(contact_id):
    data = ghl_get("/conversations/search", {
        "locationId": LOCATION_ID,
        "contactId": contact_id,
        "limit": CONV_LIMIT,
        "sortBy": "last_message_date",
    })
    return data.get("conversations") or []


def get_messages(conversation_id):
    data = ghl_get(f"/conversations/{conversation_id}/messages", {"limit": MSG_LIMIT})
    msgs = data.get("messages")
    if isinstance(msgs, dict):
        msgs = msgs.get("messages")
    return msgs or []


REAL_MESSAGE_TYPES = {"TYPE_SMS"}  # GHL also returns TYPE_ACTIVITY_CONTACT etc. (system
# log lines like "DnD enabled by customer" / "Opportunity created" / "Tag added") mixed
# into /messages with real direction+body fields — those are NOT texts and must be
# dropped before classification, confirmed via live sample pull 2026-08-01.


def full_thread(contact_id):
    """All real SMS messages across all conversations for a contact, chronological
    (oldest first). Non-SMS system activity-log entries are filtered out."""
    all_msgs = []
    for conv in list_conversations(contact_id):
        conv_id = conv.get("id")
        if not conv_id:
            continue
        msgs = get_messages(conv_id)
        all_msgs.extend(m for m in msgs if m.get("messageType") in REAL_MESSAGE_TYPES)
    all_msgs.sort(key=lambda m: _to_ms(m.get("dateAdded")) or 0)
    return all_msgs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def contact_name(c):
    name = c.get("name")
    if name:
        return name
    parts = [c.get("firstName") or "", c.get("lastName") or ""]
    full = " ".join(p for p in parts if p).strip()
    return full or "(no name)"


def snippet(body, n=120):
    b = (body or "").replace("\n", " ").strip()
    return b[:n]


def iso(v):
    ms = _to_ms(v)
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def classify(messages, expected_name=None):
    """messages: chronological list of dicts with 'direction' + 'body'.
    Returns (status_category, last_inbound, last_outbound, total_inbound, total_outbound,
             last_msg_direction, last_msg_date_ms, dead_end_reason).

    dead_end_reason is checked against the seller's MOST RECENT genuine reply (not
    necessarily the last message overall — we may have sent one more follow-up after
    a "not interested"). When set, status_category becomes "dead_end" regardless of
    what the reply-recency logic below would otherwise say: never re-engage a DNC/
    opt-out/hard-no/sold/wrong-number lead just because we happened to text last.
    """
    inbound_seller_msgs = [m for m in messages if m.get("direction") == "inbound"
                            and _is_seller_message(m.get("body"))]
    outbound_msgs = [m for m in messages if m.get("direction") == "outbound"]
    total_inbound = len(inbound_seller_msgs)
    total_outbound = len(outbound_msgs)

    last_inbound = inbound_seller_msgs[-1] if inbound_seller_msgs else None
    last_outbound = outbound_msgs[-1] if outbound_msgs else None
    # Compliance first, across the WHOLE thread, and it outranks the last reply.
    dead_end_reason = _compliance_reason(inbound_seller_msgs) or (
        _dead_end_reason(last_inbound.get("body"), expected_name)
        if last_inbound else None)

    if not messages:
        return ("no_outbound_yet", last_inbound, last_outbound, total_inbound,
                 total_outbound, "", None, dead_end_reason)

    if total_outbound == 0:
        # never messaged them at all (edge case)
        return ("no_outbound_yet", last_inbound, last_outbound, total_inbound,
                 total_outbound, messages[-1].get("direction", ""), messages[-1].get("dateAdded"),
                 dead_end_reason)

    if total_inbound == 0:
        return ("never_replied", last_inbound, last_outbound, total_inbound,
                 total_outbound, messages[-1].get("direction", ""), messages[-1].get("dateAdded"),
                 dead_end_reason)

    if dead_end_reason:
        last_msg = messages[-1]
        return ("dead_end", last_inbound, last_outbound, total_inbound, total_outbound,
                 last_msg.get("direction", ""), last_msg.get("dateAdded"), dead_end_reason)

    # We have both outbound + at least one genuine, non-dead-end seller reply somewhere.
    last_msg = messages[-1]
    last_is_seller_reply = (last_msg.get("direction") == "inbound"
                             and _is_seller_message(last_msg.get("body")))
    if last_is_seller_reply:
        status = "active_pending_us"
    else:
        status = "replied_then_cold"

    return (status, last_inbound, last_outbound, total_inbound, total_outbound,
            last_msg.get("direction", ""), last_msg.get("dateAdded"), dead_end_reason)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"[leads_audit] pulling all contacts for location {LOCATION_ID} ...")
    all_contacts = list_all_contacts()
    print(f"[leads_audit] total contacts pulled: {len(all_contacts)}")

    target_contacts = []
    unknown_state_count = 0
    for c in all_contacts:
        state = (c.get("state") or "").strip()
        if not state:
            unknown_state_count += 1
            continue
        norm = state.strip().upper()
        if norm == TARGET_STATE.upper() or norm == "OHIO":
            target_contacts.append(c)

    print(f"[leads_audit] {TARGET_STATE} contacts: {len(target_contacts)} "
          f"(unknown-state skipped: {unknown_state_count})")

    rows = []
    errors = []
    status_counts = {}

    for i, c in enumerate(target_contacts, 1):
        cid = c.get("id")
        try:
            messages = full_thread(cid)
            (status, last_in, last_out, n_in, n_out,
             last_dir, last_date_ms, dead_end_reason) = classify(messages, contact_name(c))

            status_counts[status] = status_counts.get(status, 0) + 1

            rows.append({
                "contact_id": cid,
                "name": contact_name(c),
                "phone": c.get("phone") or "",
                "email": c.get("email") or "",
                "address1": c.get("address1") or "",
                "city": c.get("city") or "",
                "state": c.get("state") or "",
                "postal_code": c.get("postalCode") or "",
                "current_tags": ";".join(c.get("tags") or []),
                "last_message_date_iso": iso(last_date_ms),
                "last_message_direction": last_dir,
                "status_category": status,
                "dead_end_reason": dead_end_reason or "",
                "last_inbound_snippet": snippet(last_in.get("body")) if last_in else "",
                "last_outbound_snippet": snippet(last_out.get("body")) if last_out else "",
                "total_inbound_count": n_in,
                "total_outbound_count": n_out,
            })
        except Exception as e:
            errors.append((cid, contact_name(c), str(e)))
            continue

        if i % 25 == 0:
            print(f"[leads_audit] processed {i}/{len(target_contacts)} contacts "
                  f"({api_call_count} api calls so far)...")

    CSV_FIELDS = [
        "contact_id", "name", "phone", "email", "address1", "city", "state",
        "postal_code", "current_tags",
        "last_message_date_iso", "last_message_direction", "status_category",
        "dead_end_reason", "last_inbound_snippet", "last_outbound_snippet",
        "total_inbound_count", "total_outbound_count",
    ]

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)

    # ---- Dedup pass: same property/seller often has 2 GHL contacts (2 phone numbers
    # imported separately, e.g. "ohio 1 st number" / "ohio second number" tags). Group by
    # normalized property address (falls back to name when address is blank) and collapse
    # to ONE row per real-world lead.
    #
    # Merge priority is NOT "most active wins" — compliance-grade dead ends (dnc/opt_out)
    # on ANY duplicate contact record must win over every other signal: if one of this
    # person's two phone numbers ever said "STOP", the whole person is off-limits, even if
    # their other number looks like a live pending reply. Below that, pick the most
    # actionable status.
    # Every dead-end reason is about the PERSON or the PROPERTY and therefore beats
    # a live sibling row: 7 Ohio KEEP survivors swallowed a dead_end duplicate of the
    # same seller (VFfQJHM5bR9fiALwHSZK kept over j9NaCdLdNqjBgNOz2lXN "No").
    # wrong_number is the one exception -- like a Twilio-undeliverable handset it is
    # scoped to THAT PHONE, not the person, and thousands of contacts carry
    # "ohio 1st/2nd number" tags, so letting it poison the address would delete the
    # seller's good number along with the bad one. Same rule as plan section 4's
    # opt_out-vs-undeliverable split.
    HANDSET_SCOPED = {"wrong_number"}
    STATUS_RANK = {"active_pending_us": 4, "replied_then_cold": 3, "dead_end": 2,
                   "never_replied": 1, "no_outbound_yet": 0}

    def merge_rank(row):
        if row["status_category"] == "dead_end":
            # handset-scoped reasons must LOSE to a live sibling row for the same
            # address; every other dead end is unbeatable.
            return -1 if row["dead_end_reason"] in HANDSET_SCOPED else 100
        return STATUS_RANK.get(row["status_category"], -1)

    def dedup_key(row):
        addr = (row["address1"] or "").strip().lower()
        if addr:
            return f"addr:{addr}|{row['postal_code']}"
        return f"name:{row['name'].strip().lower()}"

    groups = {}
    for row in rows:
        groups.setdefault(dedup_key(row), []).append(row)

    deduped = []
    for key, group in groups.items():
        best = max(group, key=merge_rank)
        merged = dict(best)
        merged["duplicate_contact_ids"] = ";".join(
            r["contact_id"] for r in group if r["contact_id"] != best["contact_id"])
        merged["duplicate_count"] = len(group) - 1
        deduped.append(merged)

    dedup_csv = os.path.join(OUT_DIR, "ohio_leads_audit_deduped.csv")
    with open(dedup_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS + [
            "duplicate_contact_ids", "duplicate_count",
        ])
        w.writeheader()
        w.writerows(deduped)

    dedup_status_counts = {}
    dedup_reason_counts = {}
    for row in deduped:
        dedup_status_counts[row["status_category"]] = (
            dedup_status_counts.get(row["status_category"], 0) + 1)
        if row["status_category"] == "dead_end":
            reason = row["dead_end_reason"] or "unknown"
            dedup_reason_counts[reason] = dedup_reason_counts.get(reason, 0) + 1

    elapsed = time.time() - t0
    print("\n===== SUMMARY =====")
    print(f"Total GHL contacts (all states): {len(all_contacts)}")
    print(f"{TARGET_STATE} contacts found: {len(target_contacts)}")
    print(f"Unknown-state contacts skipped: {unknown_state_count}")
    print("Status breakdown:")
    for k, v in sorted(status_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    print(f"Errored contacts: {len(errors)}")
    for cid, name, err in errors[:50]:
        print(f"  ERROR contact={cid} name={name!r}: {err}")
    print(f"API calls made: {api_call_count}")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"Raw CSV written: {OUT_CSV}")
    print()
    print(f"===== DEDUPED (by property address, name fallback) =====")
    print(f"Unique leads after collapsing duplicate contacts: {len(deduped)} "
          f"(raw rows: {len(rows)}, {len(rows) - len(deduped)} were duplicates)")
    for k, v in sorted(dedup_status_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    if dedup_reason_counts:
        print("  dead_end breakdown:")
        for k, v in sorted(dedup_reason_counts.items(), key=lambda kv: -kv[1]):
            print(f"    {k}: {v}")
    print(f"Deduped CSV written: {dedup_csv}")

    return {
        "total_contacts": len(all_contacts),
        "target_contacts": len(target_contacts),
        "unknown_state": unknown_state_count,
        "status_counts": status_counts,
        "dedup_status_counts": dedup_status_counts,
        "dedup_total": len(deduped),
        "errors": errors,
        "api_calls": api_call_count,
        "elapsed": elapsed,
    }


if __name__ == "__main__":
    main()
