#!/usr/bin/env python3
"""Dropship agent context — the business brief every dropship AI task reads FIRST.

The owner maintains ``forge-dropship/skills/dropship-context.md`` (niche, target
margin, price bands, supplier realities, brand voice, standing job). Every dropship
AI path injects this file into the prompt BEFORE reasoning, so the agents stay
on-message and never invent margin / stock / supplier claims.

mtime-cached hot-reload — edit the markdown and the next run picks it up, no restart.
Stdlib only. Never raises: a missing/broken file yields "" so the agent falls back to
its generic behaviour instead of erroring. Mirrors daycare_context.py.
"""

from __future__ import annotations

import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent

_CANDIDATES = [
    HERE.parent / "forge-dropship" / "skills" / "dropship-context.md",
    Path.home() / "Desktop" / "forge-dropship" / "skills" / "dropship-context.md",
    Path("/opt/forge/forge-dropship/skills/dropship-context.md"),
]

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, str]] = {}


def context_path() -> Path | None:
    for p in _CANDIDATES:
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return None


def load_context() -> str:
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
    Returns "" when there is no context so callers can concatenate unconditionally."""
    text = load_context().strip()
    if not text:
        return ""
    return (
        "\n\n=== DROPSHIP CONTEXT (read this FIRST — source of truth for the business; "
        "never contradict its niche / margin / price / supplier facts) ===\n"
        + text[:limit]
    )


def status() -> dict:
    path = context_path()
    text = load_context()
    return {"loaded": bool(text), "path": str(path) if path else None, "chars": len(text)}
