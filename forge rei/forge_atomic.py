"""Atomic JSON-store writes.

A truncate-in-place write (`Path.write_text`) leaves an empty or half-written file if the
process is killed mid-write (systemd restart, OOM, deploy). On next boot the store's
`_load()` hits its except and silently resets to empty — for scout.json that means losing
every record and re-tagging the whole backlog + re-alerting every hot lead.

Write to a temp file in the same directory, then `os.replace()` (atomic on POSIX): a
concurrent reader or a restart sees either the complete old file or the complete new one,
never a partial one. telegram_io.py already did this inline; this is the shared version.
"""
import json
import os
from pathlib import Path


def atomic_write(path, text):
    """Write `text` to `path` atomically (tmp in the same dir + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def atomic_write_json(path, obj, indent=2):
    """Serialize `obj` to JSON and write it atomically."""
    atomic_write(path, json.dumps(obj, indent=indent))


# --- Test isolation: a test run must never write the live marcus_state/ ----------------
# Tests imported action_log / agent_bus / agents_history with their default paths and
# appended fixture rows ("ads PAUSED", "$774 Stripe link sent") to the real audit log.
# Production never changes: systemd runs `python3 connector.py`, so argv[0] is not a test
# entry point and FORGE_UNDER_TEST is unset there.
_LIVE_STATE = Path(__file__).resolve().parent / "marcus_state"
_TEST_DIR = []


def under_test():
    """True when this process is a test run: FORGE_UNDER_TEST=1, `python3 test_x.py`,
    `python3 -m unittest`, or pytest."""
    if os.environ.get("FORGE_UNDER_TEST") == "1":
        return True
    import sys
    a0 = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    return a0.startswith("test_") or "unittest" in a0 or "pytest" in a0


def guard_state_path(path):
    """`path` unchanged in production. Under a test, a path inside the live marcus_state/
    is redirected to a per-process temp dir (and FORGE_UNDER_TEST=1 is exported so child
    processes inherit the guard)."""
    path = Path(path)
    if not under_test():
        return path
    os.environ["FORGE_UNDER_TEST"] = "1"
    try:
        rel = path.resolve().relative_to(_LIVE_STATE)
    except ValueError:
        return path                    # already a temp / explicit test path
    if not _TEST_DIR:
        import tempfile
        # ponytail: one mkdtemp per test process, never cleaned; files are tiny.
        _TEST_DIR.append(Path(tempfile.mkdtemp(prefix="forge-test-state-")))
    return _TEST_DIR[0] / rel
