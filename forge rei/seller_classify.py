"""Version-controlled seller message classification and fallback drafting."""

import re


_DNC_RE = re.compile(
    r"\b(?:stop|unsubscribe|remove\s+me|do\s+not\s+text|do\s+not\s+contact|"
    r"don'?t\s+text|don'?t\s+contact)\b",
    re.IGNORECASE,
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
    r"what\s+would\s+you|"
    r"your\s+offer|"
    r"what\s+can\s+you|"
    r"price|offer|pay|"
    r"ballpark|range|numbers|"
    r"what\s+number|your\s+best|most\s+you\s+can|worth\s+to\s+you|"
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
    if _DNC_RE.search(text):
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
