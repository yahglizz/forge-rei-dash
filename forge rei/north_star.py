#!/usr/bin/env python3
"""north_star.py — NORTH_STAR.md, the cross-business constitution every FORGE
agent reads FIRST, above its business creed.

The owner maintains ``NORTH_STAR.md`` at the repo root (mission, cross-business
principles — pointers into CLAUDE.md's RULES, not duplicates — per-business
tone/identity, the brains+skills map, the env/integrations map with NAMES
only, never values). Every agent injects this block before its creed
(``agent_creed.block``) so identity/tone sits above evidence discipline, which
sits above the learned playbook — the same layering Solomon already uses for
his top skills.

mtime-cached hot-reload — edit the markdown and the next run picks it up, no
restart. Stdlib only. Never raises: a missing/broken file yields "" so the
agent falls back to its generic behaviour instead of erroring.

Deploy note: NORTH_STAR.md lives at the repo root, which is HERE.parent both
in local dev (forge rei/ is a subfolder of the git repo) AND on the box,
PROVIDED deploy-pull.sh / push.sh copy it into $LIVE/NORTH_STAR.md — see those
scripts' "sync repo-root constitution" step. Without that step this module
still never raises, it just silently returns "" on the box (fail open, not
fail loud).
"""

from __future__ import annotations

import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent

# HERE.parent is the repo root locally (forge rei/ is a subfolder of the git
# repo) AND $LIVE/ on the box (deploy-pull.sh/push.sh sync forge rei/ into
# $LIVE/forge-rei/, so HERE.parent == $LIVE — see those scripts for the
# NORTH_STAR.md copy step that keeps this candidate valid there too).
_CANDIDATES = [
    HERE.parent / "NORTH_STAR.md",
    Path.home() / "Desktop" / "forge rei dash" / "NORTH_STAR.md",
]

# Truncate the injected block at this marker if present, so the heavy
# reference tables (brains/skills map, env map) never get cut mid-table —
# only the universal identity/principles sections (meant to be short) ride in
# every prompt. Falls back to a hard char limit when the marker is absent.
_INJECT_END_MARKER = "<!-- north-star:inject-end -->"

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
    """Return the full NORTH_STAR.md markdown (mtime-cached). "" if unavailable."""
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


def context_block(limit: int = 6000) -> str:
    """Prompt-ready block: labelled header + the constitution, truncated at the
    inject-end marker (preferred) or `limit` chars (fallback).

    Returns "" when there is no file so callers can concatenate unconditionally.
    Injected FIRST — above the business creed — in every agent's system prompt.
    """
    text = load_context().strip()
    if not text:
        return ""
    idx = text.find(_INJECT_END_MARKER)
    body = text[:idx] if idx != -1 else text[:limit]
    return (
        "\n\n=== NORTH STAR (the constitution — mission, identity, tone, and "
        "principles for every FORGE business; read this FIRST, it outranks "
        "nothing below but frames everything below) ===\n"
        + body.strip()
    )


def status() -> dict:
    """Lightweight introspection — mirrors daycare_context.status()."""
    path = context_path()
    text = load_context()
    return {
        "loaded": bool(text),
        "path": str(path) if path else None,
        "chars": len(text),
    }
