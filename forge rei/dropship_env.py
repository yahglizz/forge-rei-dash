#!/usr/bin/env python3
"""dropship_env.py — the one reader for FORGE Dropship's config/dropship.env.

Mirrors how the rest of the codebase resolves a business's env (connector._load_env
+ the per-agent _load_env_file): a candidate-path list, first file wins, KEY=value
lines, ``#`` and blanks skipped. os.environ ALWAYS wins over the file, so once the
connector has injected the env at startup every reader agrees.

Stdlib only. Never raises — a missing/broken file yields "" so callers degrade to
"add key" mock instead of erroring. No secret is ever logged or returned to the
browser; callers expose presence only.
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Sibling forge-dropship/ on a workstation AND /opt/forge/... on the box — one list
# covers both, same relative layout as every other business folder.
_CANDIDATES = [
    HERE.parent / "forge-dropship" / "config" / "dropship.env",
    Path.home() / "Desktop" / "forge-dropship" / "config" / "dropship.env",
    Path("/opt/forge/forge-dropship/config/dropship.env"),
]


def read_env() -> dict:
    """The dropship.env as a dict (first existing candidate wins). {} if none."""
    cfg: dict = {}
    for p in _CANDIDATES:
        try:
            if p.exists():
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        cfg[k.strip()] = v.strip()
                break
        except Exception:
            continue
    return cfg


def get(key: str, default: str = "") -> str:
    """os.environ first, then the file, then default. Placeholder values pass through
    unchanged — callers that care (the Anthropic key resolver) guard for them."""
    v = os.environ.get(key)
    if v:
        return v
    return (read_env().get(key) or default)


def inject() -> None:
    """Fold dropship.env into os.environ (real env wins) so every reader agrees.
    Called once by the connector at startup, same as _inject_env for the others."""
    for k, v in read_env().items():
        if v and k not in os.environ:
            os.environ[k] = v
