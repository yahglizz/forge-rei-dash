"""sync_monitor.py — alert when a workstation falls behind on git auto-sync.

FORGE runs on multiple machines (the Mac + the gaming PC), each pushing to origin/main
via deploy/auto-sync.sh every ~60s. The always-on box autopulls from GitHub. If a
workstation's autosync stalls (or the machine is off), that machine drifts behind and
edits stop flowing. This module watches for that and pings Telegram ONCE per transition.

How it detects staleness: every auto-sync commit is titled ``auto-sync: <hostname> ...``.
We read the newest commit per hostname from the local git repo and compare its age to a
threshold (FORGE_SYNC_STALE_H, default 6h). A machine that crosses fresh→stale fires one
alert; when it syncs again it fires one recovery note. No repeat spam in between.

Box-only + gated: the connector only ticks this when LOOPS_ENABLED (box) and not
forge_ops.paused(), same as the daily brief. State persists to marcus_state so
transitions survive a restart. Read-only on git — never commits, pushes, or pulls.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "sync_monitor.json"
_LOCK = threading.Lock()

STALE_H = float(os.environ.get("FORGE_SYNC_STALE_H", "6"))
CHECK_MIN = int(os.environ.get("FORGE_SYNC_CHECK_MIN", "30"))  # how often the tick runs a real check

_AUTOSYNC_RE = re.compile(r"auto-sync:\s*(\S+)")


# --- state -------------------------------------------------------------------------
def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"machines": {}, "lastCheckTs": 0}


def _save(d: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d, indent=2))
    except Exception:
        pass


# --- git ---------------------------------------------------------------------------
def _repo_dir() -> str | None:
    """Locate a git work tree. On the box the history lives in /opt/forge/repo (the live
    tree is a plain rsync copy with no .git); on a workstation it's the repo root above
    'forge rei/'. Try the explicit override, then the box path, then walk up."""
    cands = []
    if os.environ.get("FORGE_REPO_DIR"):
        cands.append(os.environ["FORGE_REPO_DIR"])
    cands.append("/opt/forge/repo")
    cands.append(str(HERE.parent))           # repo root above this folder (workstation)
    for c in cands:
        try:
            r = subprocess.run(["git", "-C", c, "rev-parse", "--git-dir"],
                               capture_output=True, timeout=8)
            if r.returncode == 0:
                return c
        except Exception:
            continue
    return None


def _head_short(repo: str) -> str:
    try:
        r = subprocess.run(["git", "-C", repo, "rev-parse", "--short", "origin/main"],
                           capture_output=True, text=True, timeout=8)
        return r.stdout.strip() or "?"
    except Exception:
        return "?"


def _machines(repo: str, limit: int = 400) -> dict[str, int]:
    """{hostname: last_auto_sync_epoch_sec} from the newest `limit` commits."""
    out: dict[str, int] = {}
    try:
        r = subprocess.run(
            ["git", "-C", repo, "log", f"-{limit}", "--format=%ct%x09%s"],
            capture_output=True, text=True, timeout=15)
    except Exception:
        return out
    for line in r.stdout.splitlines():
        try:
            ct, _, subject = line.partition("\t")
            m = _AUTOSYNC_RE.search(subject)
            if not m:
                continue
            host = m.group(1)
            ts = int(ct)
            if host not in out or ts > out[host]:  # newest wins (log is newest-first anyway)
                out[host] = ts
        except Exception:
            continue
    return out


# --- status + alerting -------------------------------------------------------------
def status(stale_h: float | None = None) -> dict:
    """Read-only snapshot: every known workstation, its last sync age, and stale flag.
    Powers /api/sync/status and the check."""
    stale_h = STALE_H if stale_h is None else stale_h
    repo = _repo_dir()
    if not repo:
        return {"ok": False, "error": "no git repo found", "machines": []}
    now = int(time.time())
    machines = _machines(repo)
    rows = []
    for host, ts in sorted(machines.items(), key=lambda kv: kv[1], reverse=True):
        age_min = max(0, (now - ts) // 60)
        rows.append({
            "host": host,
            "lastSyncTs": ts * 1000,
            "ageMin": age_min,
            "ageH": round(age_min / 60, 1),
            "stale": age_min > stale_h * 60,
        })
    return {"ok": True, "head": _head_short(repo), "staleH": stale_h,
            "now": now * 1000, "machines": rows}


def check_and_alert(force: bool = False) -> dict:
    """Compute status, compare to saved per-machine state, and Telegram-ping ONCE on each
    fresh->stale and stale->fresh transition. Called by the box scheduler tick (rate-
    limited to CHECK_MIN) and by the manual /api/sync/check route (force=True)."""
    with _LOCK:
        d = _load()
        now_ms = int(time.time() * 1000)
        if not force:
            last = d.get("lastCheckTs", 0)
            if now_ms - last < CHECK_MIN * 60 * 1000:
                return {"skipped": "rate-limited", "nextInMin":
                        CHECK_MIN - int((now_ms - last) / 60000)}
        d["lastCheckTs"] = now_ms

        st = status()
        if not st.get("ok"):
            _save(d)
            return st

        head = st["head"]
        saved = d.get("machines", {})
        alerts = []
        for row in st["machines"]:
            host = row["host"]
            now_stale = row["stale"]
            prev = (saved.get(host) or {}).get("state", "fresh")
            saved.setdefault(host, {})
            saved[host]["lastSyncTs"] = row["lastSyncTs"]
            saved[host]["ageMin"] = row["ageMin"]
            if now_stale and prev != "stale":
                alerts.append(_alert_stale(host, row, head))
                saved[host]["state"] = "stale"
                saved[host]["alertedTs"] = now_ms
            elif not now_stale and prev == "stale":
                alerts.append(_alert_recovered(host, row, head))
                saved[host]["state"] = "fresh"
            else:
                saved[host]["state"] = "stale" if now_stale else "fresh"
        d["machines"] = saved
        _save(d)
        return {"ok": True, "checked": len(st["machines"]), "alertsSent": len([a for a in alerts if a]),
                "machines": st["machines"]}


def _alert_stale(host: str, row: dict, head: str) -> bool:
    try:
        import telegram_io
    except Exception:
        return False
    hours = row["ageH"]
    text = (f"⚠️ <b>Sync alert</b> — <code>{_esc(host)}</code> hasn't synced in "
            f"<b>{hours}h</b>.\nBox + GitHub are current at <code>{_esc(head)}</code>. "
            f"That machine may be off or its autosync stalled.\n"
            f"Fix: power it on (autosync catches up in ~1 min), or run "
            f"<code>git pull --rebase origin main</code> there.")
    res = telegram_io.send(text, dedupe_key=f"sync_stale:{host}:{row['lastSyncTs']}")
    return bool(res.get("ok"))


def _alert_recovered(host: str, row: dict, head: str) -> bool:
    try:
        import telegram_io
    except Exception:
        return False
    text = (f"✅ <code>{_esc(host)}</code> is back in sync "
            f"(current at <code>{_esc(head)}</code>).")
    res = telegram_io.send(text, dedupe_key=f"sync_ok:{host}:{row['lastSyncTs']}")
    return bool(res.get("ok"))


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
