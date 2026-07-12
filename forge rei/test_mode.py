"""test_mode.py — FORGE REI OS scoped-autopilot gate (TEST MODE).

A scoped autopilot kill-switch + whitelist. When enabled, the AI agents
auto-act ONLY for whitelisted test phone(s): Marcus auto-sends replies, Scout
auto-organizes (tags + pipeline) — for test contacts ONLY. Real sellers stay
review-gated exactly as today. OFF by default.

Server-side JSON store mirroring agent_bus.py: the 24/7 connector owns the
single source of truth at marcus_state/test_mode.json, so the whitelist
persists across reloads and survives restarts/redeploys. No DB — just a
thread-locked JSON file. Stdlib only.

State shape: {"enabled": false, "phones": [<normalized last-10-digits>]}.
Phones are stored AND compared normalized (last 10 digits, digits only) so any
format — "+12679160166", "(267) 916-0166", "267-916-0166" — matches.

Env: FORGE_TEST_PHONES (comma list) is always UNIONed into the whitelist
(normalized). Env phones add to the list but do NOT force-enable; effective
`enabled` = the file's enabled flag.

Public API (connector + both engines depend on these EXACT names):
- norm(phone)   -> last-10-digits string (digits only); handles None.
- _load()       -> dict with defaults filled; UNIONs env FORGE_TEST_PHONES.
- status()      -> {"enabled": bool, "phones": [normalized], "envPhones": [...]}.
- is_test(phone)-> enabled AND norm(phone) in phones.
- update(body)  -> merge enabled/phones into file, save under lock, return status().
"""
import json
import os
import threading
from pathlib import Path

import forge_atomic

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "test_mode.json"
_LOCK = threading.Lock()

ENV_PHONES = "FORGE_TEST_PHONES"


def norm(phone):
    """Return a valid US 10-digit phone. Reject incomplete numbers fail-closed."""
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def _env_phones():
    """Normalized phones from the FORGE_TEST_PHONES env (comma list). May be empty."""
    raw = os.environ.get(ENV_PHONES, "") or ""
    out = []
    for part in raw.split(","):
        n = norm(part)
        if n and n not in out:
            out.append(n)
    return out


def _read_file():
    """Read the raw store from disk; defaults filled. Best-effort (never raises)."""
    enabled = False
    phones = []
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict):
                enabled = bool(d.get("enabled", False))
                raw = d.get("phones", [])
                if isinstance(raw, list):
                    for p in raw:
                        n = norm(p)
                        if n and n not in phones:
                            phones.append(n)
        except Exception:
            pass
    return {"enabled": enabled, "phones": phones}


def _load():
    """Effective state: file defaults + UNION env FORGE_TEST_PHONES (normalized).

    `enabled` = the file's enabled flag (env phones add to the whitelist but
    do not force-enable). `phones` = union(file.phones, env), normalized.
    """
    d = _read_file()
    env = _env_phones()
    phones = list(d["phones"])
    for n in env:
        if n not in phones:
            phones.append(n)
    return {"enabled": d["enabled"], "phones": phones, "envPhones": env}


def status():
    """Public state snapshot.

    {"enabled": <file.enabled>, "phones": union(file, env), "envPhones": [...]}.
    """
    d = _load()
    return {
        "enabled": bool(d["enabled"]),
        "phones": list(d["phones"]),
        "envPhones": list(d["envPhones"]),
    }


def is_test(phone):
    """True iff TEST MODE is enabled AND norm(phone) is whitelisted."""
    n = norm(phone)
    if not n:
        return False
    s = status()
    return bool(s["enabled"]) and n in s["phones"]


def update(body):
    """Merge body.enabled (bool) and/or body.phones (list) into the file.

    Phones are normalized before storing. Saves under lock. Returns status().
    Never raises — best-effort; on error returns the current status().
    """
    try:
        if not isinstance(body, dict):
            body = {}
        with _LOCK:
            cur = _read_file()
            enabled = cur["enabled"]
            phones = list(cur["phones"])
            if "enabled" in body:
                enabled = bool(body.get("enabled"))
            if "phones" in body:
                raw = body.get("phones")
                if isinstance(raw, list):
                    phones = []
                    for p in raw:
                        n = norm(p)
                        if n and n not in phones:
                            phones.append(n)
            STATE.parent.mkdir(parents=True, exist_ok=True)
            forge_atomic.atomic_write_json(
                STATE, {"enabled": enabled, "phones": phones})
    except Exception:
        pass
    return status()


def add_phone(phone):
    """Convenience: add a single phone to the whitelist (normalized). Returns status()."""
    n = norm(phone)
    if not n:
        return status()
    cur = _read_file()
    phones = list(cur["phones"])
    if n not in phones:
        phones.append(n)
    return update({"phones": phones})
