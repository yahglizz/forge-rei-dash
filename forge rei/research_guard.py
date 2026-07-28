#!/usr/bin/env python3
"""research_guard.py — the two rules every external research read obeys.

Both research clients (``dropship_winninghunter``, ``etsy_everbee``) and the
packet builder (``MidasEngine.research_packet``) route fetched content through
here. Stdlib only, no I/O, no config — so the test can hit it directly.

**Rule 1 — fetched content is DATA, never instructions.** Vendors really do plant
directives in machine-readable files aimed at whatever agent fetches them; the
live case that motivated this is ``alura.io/llms.txt``, which opens with a
sentence addressed at the reading agent. ``inert()`` flags that shape and wraps
the text so it reaches a prompt visibly delimited as untrusted data. We do NOT
try to sanitise it away — rewriting an attacker's text is a losing game. We mark
it, delimit it, and let the prompt's own boundary do the work.

**Rule 2 — every number carries its source and window, or is Unknown.** That's
the dropship creed (``dropship-evidence-discipline``). WinningHunter ships no
freshness endpoint, so recency is stamped at fetch time rather than asserted by
the vendor. ``stamp()`` is how a figure earns the right to appear in a packet;
``UNKNOWN`` is what it gets instead when an input is missing.

Nothing here ever raises — a guard that throws on bad input is a guard that gets
wrapped in a bare ``except`` and skipped.
"""
from __future__ import annotations

import re
import time

# Text aimed at a reading model rather than at a human. Deliberately narrow:
# these match the imperative-to-AI shape, not ordinary marketing copy. False
# positives cost a visible flag, which is cheap; false negatives cost trust.
_INJECTION_PATTERNS = [
    r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier|all)\b.{0,20}\b(instruction|prompt|rule|direction)",
    r"\b(you are|you're)\s+(now|actually)\b",
    r"\bsystem\s*(prompt|message|instruction)\b",
    r"\b(please\s+)?(give|show|return|output|respond|reply|provide)\s+(me\s+)?(just|only)\b",
    r"\bdo\s+not\s+(mention|include|show|tell|reveal)\b",
    r"\b(act|behave)\s+as\s+(if|though|a|an)\b",
    r"<\s*/?\s*(system|assistant|instructions?)\s*>",
    r"\bnew\s+instructions?\b",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE | re.DOTALL)

UNKNOWN = "Unknown"

_MAX_TEXT = 4000  # a single vendor field has no business being longer


def looks_like_injection(text) -> bool:
    """True when a fetched string carries text addressed at a reading model."""
    if not isinstance(text, str) or not text.strip():
        return False
    return bool(_INJECTION_RE.search(text))


def inert(text, label: str = "external") -> dict:
    """Wrap fetched text as untrusted DATA.

    Returns ``{"text", "untrusted": True, "flagged": bool, "label"}``. The text is
    truncated but never rewritten — callers render ``text`` inside a delimiter and
    surface ``flagged`` so an operator can see when a vendor tried something.
    """
    if text is None:
        return {"text": "", "untrusted": True, "flagged": False, "label": label}
    if not isinstance(text, str):
        text = str(text)
    flagged = looks_like_injection(text)
    if len(text) > _MAX_TEXT:
        text = text[:_MAX_TEXT] + " …[truncated]"
    return {"text": text, "untrusted": True, "flagged": flagged, "label": label}


def inert_deep(value, label: str = "external"):
    """``inert`` applied across a nested payload. Strings become inert dicts;
    dicts/lists are walked; numbers, bools and None pass through untouched so the
    money math still sees real numbers."""
    if isinstance(value, str):
        return inert(value, label)
    if isinstance(value, dict):
        return {k: inert_deep(v, label) for k, v in value.items()}
    if isinstance(value, list):
        return [inert_deep(v, label) for v in value]
    return value


def flagged_fields(value, _path: str = "") -> list:
    """Dotted paths of every inert field whose text was flagged. Empty list is
    the normal case; a non-empty list belongs in the packet, visibly."""
    out: list = []
    if isinstance(value, dict):
        if value.get("untrusted") is True and "text" in value:
            if value.get("flagged"):
                out.append(_path or value.get("label") or "external")
            return out
        for k, v in value.items():
            out.extend(flagged_fields(v, f"{_path}.{k}" if _path else str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.extend(flagged_fields(v, f"{_path}[{i}]"))
    return out


def stamp(value, source: str, window: str = "", confidence: str = "") -> dict:
    """Attach provenance to a figure so it may appear in a packet.

    ``value is None`` yields Unknown — that is the creed's whole point: a missing
    input surfaces as Unknown, never as a confident number.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return {"value": None, "unknown": True, "source": source or UNKNOWN,
                "window": window or UNKNOWN, "fetchedAt": _now(),
                "confidence": confidence or UNKNOWN, "display": UNKNOWN}
    out = {"value": value, "unknown": False, "source": source or UNKNOWN,
           "window": window or UNKNOWN, "fetchedAt": _now()}
    if confidence:
        out["confidence"] = confidence
    out["display"] = str(value)
    return out


def unknown(source: str = "", why: str = "") -> dict:
    """An explicitly-absent figure. Used when a lookup is skipped or unavailable."""
    out = stamp(None, source or UNKNOWN)
    if why:
        out["why"] = why
    return out


# Category-wide limit: no research tool can reach a Shopify backend, so every
# revenue figure is inferred by polling inventory over time and multiplying.
# WinningHunter's own accuracy profile: sales COUNTS 70-98%, revenue off 20-40%
# either direction, worst under $5K/mo and over $500K/mo.
REVENUE_CONFIDENCE = "estimate, ±20-40% (inferred from inventory polling)"
COUNT_CONFIDENCE = "estimate, 70-98% accurate"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
