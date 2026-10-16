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


def atomic_write(path, text, mode=None):
    """Write `text` to `path` atomically (tmp in the same dir + os.replace).
    `mode` (e.g. 0o600 for a token file): the tmp is created with it, so the secret is
    never world-readable, not even for the instant before the rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if mode is None:
        tmp.write_text(text)
    else:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        os.fchmod(fd, mode)                 # O_CREAT's mode is masked by umask / ignored if tmp existed
        with os.fdopen(fd, "w") as f:
            f.write(text)
    os.replace(tmp, path)


def atomic_write_json(path, obj, indent=2, mode=None):
    """Serialize `obj` to JSON and write it atomically."""
    atomic_write(path, json.dumps(obj, indent=indent), mode=mode)
