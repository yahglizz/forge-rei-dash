#!/usr/bin/env python3
"""agent_env.py — the ONE key source for every FORGE agent: ~/.agent-keys/master.env.

Business env files (ghl.env, agency.env, daycare.env, dropship.env, telegram.env) are no
longer a key source. They may still hold non-secret config (location ids, store domains,
FORGE_* knobs); with_master() keeps those and replaces every key named below with the
master value for ONE account label.

Rules (agents/ENV-MAP.md):
- `NAME__LABEL` in master -> `NAME`, for the asked label only. Another label is never read.
- Unlabelled master names are included only when listed for that label in SHARED.
- A key that master lacks stays ABSENT. Nothing is borrowed from another label or a file.
- No value is ever logged or printed. Stdlib only.
FORGE_MASTER_ENV overrides the path (tests only).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

LABELS = ("WHOLESALE", "AGENCY", "DAYCARE", "DROPSHIP", "SHARED", "FORGE_N8N")

# TELEGRAM_AGENT_BOT_TOKEN is left out on purpose: it is unset on the box (n8n owns that bot's
# webhook, ENV-MAP). Set it in the real env if a process must poll it.
_ALL = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ALLOWED_IDS")

# Unlabelled master names each label may see (ENV-MAP rows + what each business file held).
SHARED = {
    "SHARED": _ALL,
    "FORGE_N8N": (),
    "WHOLESALE": _ALL + ("RETELL_API_KEY", "TWILIO_AUTH_TOKEN"),
    "AGENCY": _ALL + ("HIGGSFIELD_API_KEY", "HIGGSFIELD_API_SECRET"),
    "DAYCARE": _ALL + ("NEXT_PUBLIC_SUPABASE_ANON_KEY", "DAYCARE_TEST_ADMIN_PIN",
                       "DAYCARE_TEST_MANAGER_PIN", "DAYCARE_QA_PIN", "DAYCARE_QA_PARENT_PIN",
                       "DAYCARE_QA_NAME_PIN", "METRICOOL_USER_TOKEN", "HIGGSFIELD_API_KEY",
                       "HIGGSFIELD_API_SECRET", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_YAHJAIR",
                       "GOOGLE_CAL_REFRESH_YAHJAIR", "STRIPE_SECRET_KEY__DAYCARE_TEST",
                       "BILLING_N8N_SECRET", "RESEND_API_KEY"),
    "DROPSHIP": _ALL + ("SHOPIFY_ADMIN_TOKEN", "AUTODS_API_KEY", "GETHOOKED_API_KEY",
                        "WINNINGHUNTER_API_KEY", "EVERBEE_CLIENT_SECRET",
                        "HIGGSFIELD_API_KEY", "HIGGSFIELD_API_SECRET"),
}

# Labelled keys each label owns. Declared so a key missing from master is dropped from the
# business file too (absent, never a file fallback).
LABELLED = {
    "SHARED": (),
    "FORGE_N8N": ("N8N_API_KEY", "N8N_BASE_URL"),   # forge's own n8n instance (master __FORGE_N8N)
    "WHOLESALE": ("ANTHROPIC_API_KEY", "GHL_API_KEY", "GHL_LOCATION_ID"),
    "AGENCY": ("ANTHROPIC_API_KEY", "GHL_API_KEY", "GHL_LOCATION_ID", "STRIPE_SECRET_KEY"),
    "DAYCARE": ("ANTHROPIC_API_KEY", "GHL_API_KEY", "STRIPE_SECRET_KEY", "META_ACCESS_TOKEN",
                "META_AD_ACCOUNT_MAP", "PIPEBOARD_API_TOKEN"),
    "DROPSHIP": ("ANTHROPIC_API_KEY", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_MAP"),
}


def master_path() -> Path:
    return Path(os.environ.get("FORGE_MASTER_ENV") or Path.home() / ".agent-keys" / "master.env")


def _under_test() -> bool:
    """Same rule as forge_atomic.under_test (kept inline: this module stays dependency-free)."""
    if os.environ.get("FORGE_UNDER_TEST") == "1":
        return True
    a0 = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    return a0.startswith("test_") or "unittest" in a0 or "pytest" in a0


def _read_master() -> dict:
    out = {}
    if _under_test() and not os.environ.get("FORGE_MASTER_ENV"):
        return out          # a test never reads the real master; it points FORGE_MASTER_ENV at a fake
    try:
        for raw in master_path().read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:]
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        print("agent_env: master.env not readable; agent keys are absent", file=sys.stderr)
    return out


def load_agent_env(label: str) -> dict:
    """Plain-name keys for ONE label. Empty values are dropped (absent)."""
    label = label.upper()
    if label not in LABELS:
        raise ValueError(f"unknown label {label!r}")
    master, out = _read_master(), {}
    for name, v in master.items():
        base, sep, lab = name.rpartition("__")
        if sep and lab == label and base and v:
            out[base] = v
    for name in SHARED[label]:
        if master.get(name):
            out[name] = master[name]
    return out


def owned(label: str) -> set:
    """Every plain name this label takes from master (whether master has it or not)."""
    label = label.upper()
    return set(LABELLED[label]) | set(SHARED[label])


def with_master(label: str, file_cfg: dict) -> dict:
    """A business file's config with every owned key replaced by master's (or removed)."""
    keys = load_agent_env(label)
    drop = owned(label) | set(keys)
    cfg = {k: v for k, v in (file_cfg or {}).items() if k not in drop}
    cfg.update(keys)
    return cfg
