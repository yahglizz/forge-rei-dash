#!/usr/bin/python3
"""mac_worker.py — runs on the owner's Mac. It dials out to the box; nothing listens here.

Every 5 seconds it asks the box for work over the tailnet, which also serves as the heartbeat. A
command runs in zsh with stdin closed, in its own process group, and the group is killed at 120
seconds. One at a time. Output goes to the box, which redacts it; only the command and its exit
code land in ~/Library/Logs/forge-mac-worker.log.

Switches: touch ~/.forge-mac/off (heartbeats as off, runs nothing), or launchctl bootout.
Install: deploy/mac/install.sh. Stdlib only, Python 3.9 (/usr/bin/python3).
"""
import json
import os
import select
import shutil
import signal
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BOX = "https://forge-reios.tail0a2dda.ts.net"
HOME = str(Path.home())
DIR = Path.home() / ".forge-mac"
KEY_FILE, OFF_FILE = DIR / "key", DIR / "off"
LOG = Path.home() / "Library" / "Logs" / "forge-mac-worker.log"
VOLUME = "/Volumes/AgentDrive"
WORK = VOLUME + "/claude"
POLL_SECONDS = 5
MAX_BACKOFF = 60
COMMAND_TIMEOUT = 120
HTTP_TIMEOUT = 15
MAX_OUTPUT = 20000
POWER_EVERY = 60
_power = {"at": 0.0, "value": ""}


def tls_context():
    return ssl.create_default_context()


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=tls_context()))


def log(row):
    fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **row}) + "\n")


def is_mounted():
    return os.path.ismount(VOLUME) and os.path.isdir(WORK)


def disk_free_gb():
    for path in ("/System/Volumes/Data", "/"):
        try:
            return round(shutil.disk_usage(path).free / 2 ** 30, 1)
        except OSError:
            continue
    return ""


def power():
    """pmset costs a process, so once a minute, not every poll."""
    if time.time() - _power["at"] > POWER_EVERY:
        try:
            out = subprocess.run(["/usr/bin/pmset", "-g", "ps"], capture_output=True, text=True, timeout=5).stdout
            _power["value"] = "ac" if "AC Power" in out else "battery" if "Battery Power" in out else ""
        except (OSError, subprocess.SubprocessError):
            _power["value"] = ""
        _power["at"] = time.time()
    return _power["value"]


def facts():
    return {"drive": int(is_mounted()), "free": disk_free_gb(), "power": power(), "off": int(OFF_FILE.exists())}


def call(method, path, key, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(BOX + path, data=data, method=method, headers={"X-Mac-Key": key})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with _OPENER.open(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode() or "{}")


def run_command(command):
    """-> {exitCode, output, truncated, timedOut}. Reads with select, not communicate(): a background
    child that keeps the pipe open must not hang the worker, and `yes` must not fill its memory."""
    mounted = is_mounted()
    env = dict(os.environ)
    if mounted:
        env["TMPDIR"] = os.path.join(WORK, "_tmp")
        os.makedirs(env["TMPDIR"], exist_ok=True)
    proc = subprocess.Popen(["/bin/zsh", "-lc", command], cwd=WORK if mounted else HOME, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    fd = proc.stdout.fileno()
    keep, size, overflow, timed_out = [], 0, False, False
    deadline = time.monotonic() + COMMAND_TIMEOUT
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            break
        ready = select.select([fd], [], [], min(left, 0.25))[0]
        if ready:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            if size < MAX_OUTPUT * 4:  # four bytes covers any character
                keep.append(chunk)
                size += len(chunk)
            else:
                overflow = True
        elif proc.poll() is not None:  # the shell is done; a silent background child may hold the pipe
            break
    proc.stdout.close()
    code = proc.wait()
    text = b"".join(keep).decode("utf-8", "replace")
    return {"exitCode": code, "output": text[:MAX_OUTPUT], "truncated": overflow or len(text) > MAX_OUTPUT,
            "timedOut": timed_out}


def post_result(key, body):
    """A few tries, then give up: the box's wait has an end of its own."""
    for attempt in range(3):
        try:
            return call("POST", "/api/mac/result", key, body)
        except (OSError, ValueError) as e:
            if attempt == 2:
                log({"event": "result_lost", "id": body["id"], "why": type(e).__name__})
            else:
                time.sleep(2)


def handle(job, key):
    job_id, command = job.get("id"), job.get("command")
    if not isinstance(job_id, str) or not isinstance(command, str):
        raise ValueError("a job needs an id and a command")
    refusal = "Refused: the off file is present on the Mac." if OFF_FILE.exists() else ""   # it can land after the poll
    try:
        log({"event": "start", "id": job_id, "command": command, "origin": job.get("origin")})
    except OSError:                    # no log, no command: this disk is often full
        refusal = "Refused: the Mac's log can't be written, so nothing ran. Is the disk full?"
    if refusal:
        result = {"exitCode": -1, "output": refusal, "truncated": False, "timedOut": False}
    else:
        try:
            result = run_command(command)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            result = {"exitCode": -1, "output": f"The worker could not start it: {type(e).__name__}", "truncated": False,
                      "timedOut": False}
    try:
        log({"event": "end", "id": job_id, "exit": result["exitCode"], "timedOut": result["timedOut"]})
    except OSError:                    # the box still needs the result
        pass
    post_result(key, {"id": job_id, **result})


def describe(error):
    if isinstance(error, urllib.error.HTTPError):
        return f"box refused the worker (HTTP {error.code})"
    return f"box unreachable ({type(error).__name__})"


def loop(stop=None):
    """Never exits on an error. Quiet: one log line when the trouble changes, one when it clears."""
    stop = stop or threading.Event()
    delay, trouble = POLL_SECONDS, ""
    while not stop.is_set():
        try:
            key = KEY_FILE.read_text().strip()
            job = call("GET", "/api/mac/next?" + urllib.parse.urlencode(facts()), key).get("command")
            if trouble:
                log({"event": "box reachable"})
            delay, trouble = POLL_SECONDS, ""
            if job:
                handle(job, key)
                continue               # a queued follow-up shouldn't wait out a poll
        except Exception as e:  # noqa: BLE001 — network, TLS, a bad answer: the loop outlives all of it
            delay = min(delay * 2, MAX_BACKOFF)
            if describe(e) != trouble:
                trouble = describe(e)
                try:
                    log({"event": trouble})
                except OSError:
                    pass
        stop.wait(delay)


if __name__ == "__main__":
    loop()
