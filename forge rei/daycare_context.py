#!/usr/bin/env python3
"""Daycare agent context — the business brief every daycare AI task reads FIRST.

The owner maintains ``forge-daycare/skills/daycare-context.md`` (business facts,
mission, current status, brand voice, the agent's standing job). Any daycare AI
path (Eco enrollment ideas, competitor research, future daycare chat) injects this
file into the prompt BEFORE reasoning, so the agents stay on-message and never
invent licensing / pricing / capacity claims.

mtime-cached hot-reload — edit the markdown and the next run picks it up, no
restart. Stdlib only. Never raises: a missing/broken file yields "" so the agent
falls back to its generic behaviour instead of erroring.
"""

from __future__ import annotations

import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Sibling ``forge-daycare/skills/`` on the Mac AND ``/opt/forge/forge-daycare/skills``
# on the box — same relative layout, so one candidate list covers both.
_CANDIDATES = [
    HERE.parent / "forge-daycare" / "skills" / "daycare-context.md",
    Path.home() / "Desktop" / "forge-daycare" / "skills" / "daycare-context.md",
]

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, str]] = {}


def context_path() -> Path | None:
    """First existing candidate path, or None."""
    for p in _CANDIDATES:
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return None


def load_context() -> str:
    """Return the daycare context markdown (mtime-cached). "" if unavailable."""
    path = context_path()
    if path is None:
        return ""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return ""
    with _LOCK:
        cached = _CACHE.get(str(path))
        if cached and cached[0] == mtime:
            return cached[1]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    with _LOCK:
        _CACHE[str(path)] = (mtime, text)
    return text


def context_block(limit: int = 3500) -> str:
    """Prompt-ready block: labelled header + the context, truncated to `limit`.

    Returns "" when there is no context so callers can concatenate unconditionally.
    """
    text = load_context().strip()
    if not text:
        return ""
    return (
        "\n\n=== DAYCARE CONTEXT (read this FIRST — source of truth for the "
        "business; never contradict licensing / pricing / capacity here) ===\n"
        + text[:limit]
    )


def status() -> dict:
    """Lightweight introspection for /api/daycare/eco and health checks."""
    path = context_path()
    text = load_context()
    return {
        "loaded": bool(text),
        "path": str(path) if path else None,
        "chars": len(text),
    }
