"""Version-controlled seller message classification and fallback drafting."""

import re


# ---------------------------------------------------------------------------
# Opt-out / DNC detection (compliance-grade).
#
# A hit here blocks EVERY send, operator included (sms_guard.guard -> gate
# "hard_no"), so precision matters as much as recall. Every pattern below is
# grounded in real Ohio thread text from the 5,527-contact audit (2026-08-21);
# test_optout_hardening.py holds the quoted cases.
# ---------------------------------------------------------------------------

# Carrier STOP keywords arrive glued together: STOPALL / STOPALLCONTACT / STOPP.
# \bstop\b matches NONE of them -- 77 of 270 real Ohio opt-outs were this family --
# so they are matched explicitly, and first.
_STOP_KEYWORD_RE = re.compile(
    r"\b(?:stop\s*all(?:\s*contact)?|stopall\w*|sto+pp+|stpp+|stpo+|st0p+|"
    r"unsubscribe|unsub)\b",
    re.IGNORECASE,
)

# Bare "stop" -- but never "stop by/in/over/at" (a seller inviting us to visit:
# "All business discussions are handled in person. Feel free to stop by"), and
# never inside a word (the naive substring form matched "Chri-stop-her").
# The lookbehinds kill the noun senses ("a stop sign", "the bus stop") without
# touching the imperative sense, which is the only one a seller ever means.
_BARE_STOP_RE = re.compile(
    r"(?<!a )(?<!the )(?<!bus )(?<!one )(?<!last )"
    r"\bstop(?!\s+(?:by|in|over|at|sign|light)\b)\b",
    re.IGNORECASE,
)

# "stop / stpp / quit / don't ... text|call|contact", at most one word in between.
# Real hits: "STPP TEXTING ME", "Quiting texting me", "No and please don't text me",
# "Please don't text or call me anymore respect my wishes", "do not contact list".
_OPT_OUT_SENTENCE_RE = re.compile(
    r"\b(?:sto+p+|stpp+|stpo+|quit(?:t?ing|s)?|cease|do\s+not|don'?t|dont|no\s+more)"
    r"\s*(?:\w{1,12}\s+)?"
    r"(?:text|txt|call|contact|messag|msg|bother|harass|send|reach|email)",
    re.IGNORECASE,
)

# Profanity aimed AT US (22 real cases). Deliberately NOT bare profanity: a
# motivated seller swearing about a trashed house ("this place is fucked up") is
# the best lead we have.
_PROFANE_STOP_RE = re.compile(
    r"\b(?:f+u+c+k+\w*|fuk\w*|fck)\s*(?:you|u|off|yourself|your\s*self)\b"
    r"|\bgo\s+f+u+c+k\b|\bpiss\s+off\b|\bstfu\b"
    r"|\bf\s*\*+\s*c?k?\s*(?:you|off)\b"
    r"|\bleave\s+me\s+(?:the\s+\w+\s+)?alone\b",
    re.IGNORECASE,
)

# Legal / spam escalation. "attorney"/"lawyer" are deliberately NOT here: zero
# hits in 5,527 threads, and a probate seller ("my attorney handles the estate")
# is a lead, not a threat.
_LEGAL_THREAT_RE = re.compile(
    r"\b(?:harass(?:ing|ment|ed)?|(?:i'?m\s+)?suing\s+you|sue\s+you|"
    r"report(?:ing)?\s+(?:you|this)|for\s+spam|"
    r"do\s*not\s*(?:contact|call|text)\s*list|fcc|tcpa)\b",
    re.IGNORECASE,
)

# "lose my number" / "number blocked" / "take me off your list".
_LOSE_NUMBER_RE = re.compile(
    r"\b(?:lo+se|loose|forget|delete|remove)\s+(?:my|this)\s+"
    r"(?:number|info|contact|details)\b"
    r"|\b(?:number|phone)\s+(?:is\s+)?blocked\b"
    r"|\bblock(?:ed|ing)?\s+(?:you|your\s+number|this\s+number)\b"
    r"|\btake\s+me\s+off\b|\boff\s+(?:your|the)\s+list\b",
    re.IGNORECASE,
)

# Legacy phrase set, kept verbatim minus bare "stop" (now _BARE_STOP_RE).
_DNC_RE = re.compile(
    r"\b(?:unsubscribe|remove\s+me|do\s+not\s+text|do\s+not\s+contact|"
    r"don'?t\s+text|don'?t\s+contact)\b",
    re.IGNORECASE,
)

_NEG_GLYPHS = "\U0001F44E\U0001F6D1\U0001F92C\U0001F595"  # thumbs-down, stop sign, cursing, finger
_LETTERS_RE = re.compile(r"[a-z]+", re.IGNORECASE)
_GLYPH_ONLY_WORDS = {"", "no", "nope", "nah", "stop", "nothanks", "nothx"}


def _is_negative_glyph(text):
    """True only when the message is essentially JUST a negative glyph -- the bare
    "\U0001F92C" / "\U0001F6D1" / "No \U0001F44E" replies. A glyph inside a real sentence
    ("roof is shot \U0001F44E") is still a live seller talking, not an opt-out."""
    if not any(g in text for g in _NEG_GLYPHS):
        return False
    return "".join(_LETTERS_RE.findall(text)).lower() in _GLYPH_ONLY_WORDS


# An iMessage tapback / quote-reply echoes OUR OWN message back at us as inbound
# text -- and our outreach footer literally reads "If you'd rather not receive
# messages reply STOPALL contact". Matching opt-out patterns inside that quoted
# span reads our own compliance line as the seller's opt-out: a positive 👍 on our
# follow-up would classify DNC and block the operator from answering it. Only the
# seller's own words -- the text OUTSIDE the quote -- count.
_QUOTED_SPAN_RE = re.compile(
    r"[\u201c\u201e\"][^\u201c\u201d\"]{20,}(?:[\u201d\"]|$)")


def _seller_words(text):
    """Strip a long quoted span (our echoed message) from an inbound body."""
    return _QUOTED_SPAN_RE.sub(" ", text or "")


def is_opt_out(text):
    """Compliance-grade, permanent opt-out: STOP family (incl. STOPALL),
    "don't text me", profanity aimed at us, legal/spam threat, "lose my number",
    or a bare negative glyph. Shared with leads_audit.py so the offline blast
    scrubber and the live send gate can never drift apart."""
    t = _seller_words(text)
    if not t.strip():
        return False
    return bool(
        _STOP_KEYWORD_RE.search(t)
        or _BARE_STOP_RE.search(t)
        or _OPT_OUT_SENTENCE_RE.search(t)
        or _DNC_RE.search(t)
        or _PROFANE_STOP_RE.search(t)
        or _LEGAL_THREAT_RE.search(t)
        or _LOSE_NUMBER_RE.search(t)
        or _is_negative_glyph(t)
    )
_HELP_RE = re.compile(
    r"\b(?:who\s+is\s+this|who\s+are\s+you|wrong\s+number)\b",
    re.IGNORECASE,
)
_NRN_RE = re.compile(
    r"\b(?:not\s+now|not\s+right\s+now|not\s+interested|later|"
    r"(?:a\s+)?few\s+months)\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"(?:\b(?:"
    r"how\s+much|"
    r"what\s+would\s+you\s+(?:give|pay|offer)|"
    r"what\s+can\s+you\s+(?:do|give|pay|offer)|"
    r"price|"
    r"what(?:'?s|\s+is)\s+your\s+(?:offer|range)|"
    r"what(?:\s+kind\s+of)?\s+numbers?\s+(?:are|were)\s+you\s+"
    r"(?:thinking|considering)|"
    r"(?:give|send)\s+me\s+(?:a\s+ballpark|your\s+(?:best|offer|range))|"
    r"what(?:'?s|\s+is)\s+the\s+most\s+you\s+can\s+(?:do|give|pay|offer)|"
    r"what(?:'?s|\s+is)\s+it\s+worth\s+to\s+you|"
    r"what\s+number\b.{0,25}\bhave\s+in\s+mind|"
    r"what\s+are\s+you\s+offering|what\s+were\s+you\s+thinking"
    r")\b|\$)",
    re.IGNORECASE,
)
_READY_RE = re.compile(
    r"\b(?:yes|interested|open\s+to|let'?s\s+talk|tell\s+me\s+more|"
    r"sure|okay|ok|talk)\b",
    re.IGNORECASE,
)


def classify(body: str) -> str:
    """Classify one inbound seller message with deterministic phrase rules."""
    text = body or ""
    if is_opt_out(text):
        return "DNC"
    if _HELP_RE.search(text):
        return "HELP"
    if _NRN_RE.search(text):
        return "NRN"
    if _PRICE_RE.search(text):
        return "PRICE"
    if _READY_RE.search(text):
        return "READY"
    return "CONTINUE"


def draft_reply(first: str, cls: str) -> str:
    """Return the tracked, price-free fallback when no legacy drafter is present."""
    first = first or "there"
    return (
        f"Hey {first}, this is Yahjair - sorry for the slow reply. Still happy to "
        "talk through the property if you're open to it. What's the situation on your end?"
    )
