"""mac_link.py — the box's side of the owner's Mac: one command at a time, a heartbeat, a result.

The Mac dials out (deploy/mac/mac_worker.py), so nothing listens there:

    GET  /api/mac/next    X-Mac-Key   heartbeat + facts, answers the next command or none
    POST /api/mac/result  X-Mac-Key   command id, exit code, output
    GET  /api/mac/status  dashboard   online, last seen, drive, disk: no commands, no output

The first two are the only routes that skip the dashboard's normal path, and PortalHandler never
routes them, so Funnel can't reach them. telegram_agent.DENY keeps all three away from api_get and
api_post. The gates on who may run what live in dash_live.mac_run and the tap in
telegram_agent._confirm_mac; this file refuses on kill switches and never queues for later.

State is in memory: a restart forgets the last heartbeat for about 5 seconds and drops a command in
flight, which the audit log's start row still shows. Self-check: python3 test_mac_link.py
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import forge_atomic
import forge_ops

AUDIT = forge_atomic.guard_state_path(Path(__file__).resolve().parent / "marcus_state" / "mac_audit.jsonl")
OFFLINE_AFTER = 30                     # no heartbeat this long = offline
PICKUP_SECONDS = 30                    # unclaimed this long = dropped, so it can't run on wake
WAIT_SECONDS = 125                     # the worker kills at 120
MAX_OUTPUT = 20000
MAX_COMMAND = 2000                     # a card must show all of it, and Telegram stops near 4,096
MAX_RESULT_BODY = 256 * 1024

# ponytail: a speed bump against model mistakes, not a boundary. A shell can spell any of these
# another way; the tap on a turn that read outside text is the wall. Upgrade: none here, narrow the worker.
RISKY = re.compile(
    r"\b(?:sudo|rm|ssh|scp|rsync|osascript|security|launchctl|vercel)\b"
    r"|\bgit\b[^;&|\n]*\bpush\b"
    r"|\b(?:curl|wget)\b[^;&|\n]*\s(?:--(?:data|form|json|upload|post|body|method|request)"
    r"|(?-i:-[a-zA-Z]*[dFTX]))"        # case-sensitive: -f and -t are harmless, -F and -T send data
    r"|\bmaster\.env\b|\.ssh\b|\.agent-keys\b",
    re.I)

_SECRETS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\bsk-ant-[\w-]+|\bsk-[\w-]{20,}|\b[sr]k_(?:live|test)_\w+|\bgh[pousr]_\w{10,}|\bgithub_pat_\w+"
               r"|\bxox[bp]-[\w-]+|\bAKIA[0-9A-Z]{12,}"),
    re.compile(r"\bBearer\s+\S+", re.I),
)
# The name is bounded and has no leading wildcard: output is outside text, and an unbounded [\w.-]* is
# quadratic on one long word, which would hang the box.
_NAMED_SECRET = re.compile(r"(?i)((?:key|token|secret|passw(?:or)?d)[\w.-]{0,64}[\"']?[ \t]{0,8}[=:][ \t]*)[^\n]+")

_lock = threading.Lock()
_seen = {}                             # the last heartbeat
_job = None                            # the one command in flight


def key_ok(presented):
    """The same check as the gateway keys. An unset hash never matches."""
    digest = hashlib.sha256(str(presented or "").encode()).hexdigest()
    want = (os.environ.get("FORGE_MAC_KEY_SHA256") or "").strip().lower()
    return bool(want) and hmac.compare_digest(digest, want)


def enabled():
    """FORGE_MAC=0 is off. Unset is on only when the box holds a key hash."""
    return os.environ.get("FORGE_MAC") != "0" and bool((os.environ.get("FORGE_MAC_KEY_SHA256") or "").strip())


def refused():
    """Why no command may run right now, or None. Checked when asked, at handout and at the tap."""
    if not enabled():
        return "The Mac link is off (FORGE_MAC=0 or no key on the box). Nothing ran."
    if forge_ops.paused():
        return "Agents are clocked out (forge_ops). Nothing ran on the Mac."
    return None


def unavailable():
    """Why a command can't be taken now, or None: a kill switch, no heartbeat, the Mac's off file."""
    why = refused()
    if why:
        return why
    st = status()
    if not st["online"]:
        return offline_text(st)
    if st["offSwitch"]:
        return "The worker is switched off on the Mac (~/.forge-mac/off). Nothing ran."
    return None


def risky(command):
    return bool(RISKY.search(command))


def bad_command(command):
    """Why this can't be stored as a command, or "". A card must show exactly what runs, so nothing
    invisible: no control characters but newline and tab, no bidi or zero-width marks."""
    import unicodedata
    if not command.strip():
        return "command is required"
    if len(command) > MAX_COMMAND:
        return f"command over {MAX_COMMAND} chars: the owner must see all of it, so shorten it"
    if any(unicodedata.category(c) in ("Cc", "Cf") and c not in "\n\t" for c in command):
        return "command holds invisible characters, so a card couldn't show what runs"
    return ""


def redact(text):
    """Key-shaped strings out, before anything reaches a model, a log or a chat."""
    text = str(text or "")
    for pattern in _SECRETS:
        text = pattern.sub("[redacted]", text)
    return _NAMED_SECRET.sub(lambda m: m.group(1) + "[redacted]", text)


def _clock(ts):
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).strftime("%-I:%M %p ET")
    except Exception:  # noqa: BLE001 — no tz database: an honest time beats a failed status
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M UTC")


def status():
    """What the mac_status tool and GET /api/mac/status both return. Facts older than the offline
    window are Unknown, not the last value. Never a command, never output."""
    with _lock:
        seen = dict(_seen)
        busy = bool(_job and _job["claimed"].is_set())   # the worker doesn't poll while a command runs
    ts = seen.get("ts")
    online = busy or (bool(ts) and time.time() - ts < OFFLINE_AFTER)
    return {"enabled": enabled(), "online": online, "busy": busy, "lastSeen": _clock(ts) if ts else None,
            "driveMounted": seen.get("drive") if online else None,
            "diskFreeGb": seen.get("freeGb") if online else None,
            "power": seen.get("power") if online else None,
            "offSwitch": bool(seen.get("off")) if online else False}


def offline_text(st):
    return f"Mac offline, last seen {st['lastSeen'] or 'Unknown'}"


def _audit(row):
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(AUDIT, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps({"ts": int(time.time()), **row}) + "\n")


def audit_card(command, origin):
    """A command that became a tap card. The run, if he taps, gets its own rows."""
    try:
        _audit({"event": "card", "command": redact(command), "origin": origin})
    except OSError as e:
        print(f"   mac_link: audit failed: {type(e).__name__}", flush=True)


def _facts(query):
    """Worker-sent numbers reach a model, so only these fields, in these shapes."""
    def one(name):
        return ((query.get(name) or [""])[0])[:20]
    try:
        free = round(float(one("free")), 1)
    except (ValueError, OverflowError):
        free = None
    if free is not None and not 0 <= free < 1e6:    # nan and inf would break the phone's JSON.parse
        free = None
    power = one("power")
    return {"drive": one("drive") == "1", "freeGb": free, "power": power if power in ("ac", "battery") else None,
            "off": one("off") == "1"}


def next_command(query):
    """One worker poll: heartbeat, then the command waiting, if any may run."""
    facts = _facts(query)
    why = refused()
    with _lock:
        _seen.update(facts, ts=time.time())
        job = _job
        if job and not job["claimed"].is_set() and not why and not facts["off"]:
            job["claimed"].set()
            return {"command": {"id": job["id"], "command": job["command"], "origin": job["origin"]}}
    return {"command": None}


def post_result(body):
    """The worker's answer. A late one gets an audit row and goes nowhere near a model."""
    job_id = str(body.get("id") or "")
    code = body.get("exitCode")
    code = code if isinstance(code, int) else None
    with _lock:
        job = _job if _job and _job["id"] == job_id and _job["claimed"].is_set() else None
        if job:
            raw = str(body.get("output") or "")
            job["result"] = {"exitCode": code, "raw": raw[:MAX_OUTPUT * 2], "truncated": bool(body.get("truncated"))
                             or len(raw) > MAX_OUTPUT, "timedOut": bool(body.get("timedOut"))}
            job["done"].set()
    if job:
        return {"ok": True}
    if re.fullmatch(r"[0-9a-f]{32}", job_id):
        try:
            _audit({"event": "late", "id": job_id, "exit": code})
        except OSError:
            pass
    return {"ok": True}


def _clean(raw):
    text = redact(raw)
    return text[:MAX_OUTPUT], len(text) > MAX_OUTPUT


def _wait(job):
    """-> (result code for the audit, the answer)."""
    global _job
    if not job["claimed"].wait(PICKUP_SECONDS):
        with _lock:                    # a claim happens under this lock: either it got out or it never will
            if not job["claimed"].is_set():
                _job = None
                return "not_picked_up", {"error": "The Mac stopped answering before it picked this up. It never ran."}
    if not job["done"].wait(max(0.0, WAIT_SECONDS - (time.time() - job["t0"]))):
        return "no_result", {"ran": True, "error": f"No result from the Mac in {WAIT_SECONDS} seconds. It may still "
                                                   "be running: the Mac kills it at 120 seconds."}
    res = job["result"]
    output, cut = _clean(res["raw"])
    return "ran", {"ran": True, "exitCode": res["exitCode"], "output": output,
                   "truncated": cut or res["truncated"], "timedOut": res["timedOut"]}


def run(command, origin):
    """Queue one command and wait. origin = {surface, agent, via}. Never queues for later: refused,
    offline, off or busy answers at once. Nothing runs unless its audit row landed first.
    -> {ran, exitCode, output, truncated, timedOut} or {error}."""
    global _job
    why = unavailable()
    if why:
        return {"error": why}
    job = {"id": secrets.token_hex(16), "command": command, "origin": origin, "t0": time.time(),
           "claimed": threading.Event(), "done": threading.Event()}
    with _lock:
        if _job:
            return {"error": "The Mac is busy with another command. Nothing ran."}
        try:
            _audit({"event": "start", "id": job["id"], "command": redact(command), "origin": origin})
        except OSError:
            return {"error": "The Mac audit log can't be written, so nothing ran."}
        _job = job
    try:
        result, out = _wait(job)
    finally:
        with _lock:
            if _job is job:
                _job = None
    try:
        _audit({"event": "end", "id": job["id"], "exit": out.get("exitCode"), "result": result})
    except OSError as e:
        print(f"   mac_link: audit failed: {type(e).__name__}", flush=True)
    return out
