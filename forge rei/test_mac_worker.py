"""The real Mac worker against a local fake box, then against the real connector routes.

Commands are harmless and run in a scratch folder. Nothing here talks to the live box.

Run: python3 test_mac_worker.py
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
_base = "/Volumes/AgentDrive/claude/_tmp"
SCRATCH = Path(tempfile.mkdtemp(prefix="mac-worker-test-", dir=_base if os.path.isdir(_base) else None))
KEY = "worker-" + "d" * 40
BOX = {"jobs": [], "results": [], "polls": [], "status": 200, "hang": False}


def load():
    spec = importlib.util.spec_from_file_location("mac_worker", HERE / "deploy" / "mac" / "mac_worker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


w = load()


class FakeBox(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        BOX["polls"].append({"path": parsed.path, "key": self.headers.get("X-Mac-Key"),
                             "query": urllib.parse.parse_qs(parsed.query)})
        if BOX["status"] != 200:
            return self._send(BOX["status"], {"error": "forbidden"})
        self._send(200, {"command": BOX["jobs"].pop(0) if BOX["jobs"] else None})

    def do_POST(self):
        BOX["results"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self._send(200, {"ok": True})


def job(command, jid="a" * 32):
    return {"id": jid, "command": command, "origin": {"surface": "dash", "agent": "solomon", "via": "auto"}}


def setup():
    home = SCRATCH / f"home-{time.time_ns()}"
    (home / "work" / "_tmp").mkdir(parents=True)
    w.DIR, w.KEY_FILE, w.OFF_FILE = home, home / "key", home / "off"
    w.LOG = home / "worker.log"
    w.KEY_FILE.write_text(KEY)
    w.WORK, w.VOLUME, w.HOME = str(home / "work"), str(home), str(home)
    w.is_mounted = lambda: True
    w.POLL_SECONDS, w.COMMAND_TIMEOUT = 0.02, 120
    BOX.update(jobs=[], results=[], polls=[], status=200)
    return home


def run_loop(until, seconds=20):
    stop = threading.Event()
    th = threading.Thread(target=w.loop, args=(stop,), daemon=True)
    th.start()
    deadline = time.time() + seconds
    while time.time() < deadline and not until():
        time.sleep(0.02)
    stop.set()
    th.join(5)
    assert not th.is_alive(), "the loop did not stop"
    assert until(), "timed out"


def test_runs_a_command_and_posts_the_result():
    home = setup()
    BOX["jobs"].append(job('pwd; echo "tmp=$TMPDIR"; echo err >&2; exit 3'))
    run_loop(lambda: BOX["results"])
    r = BOX["results"][0]
    assert r["id"] == "a" * 32 and r["exitCode"] == 3, r
    assert str(home / "work") in r["output"] and f"tmp={home}/work/_tmp" in r["output"], r
    assert "err" in r["output"], "stderr too"
    assert BOX["polls"][0]["key"] == KEY and BOX["polls"][0]["path"] == "/api/mac/next"
    q = BOX["polls"][0]["query"]
    assert q["drive"] == ["1"] and q["off"] == ["0"] and float(q["free"][0]) > 0, q
    log = w.LOG.read_text()
    assert "exit 3" in log and '"exit": 3' in log, log


def test_log_holds_command_and_exit_never_output_or_key():
    setup()
    BOX["jobs"].append(job("echo PRIVATE-OUTPUT-$((40+2))"))
    run_loop(lambda: BOX["results"])
    assert "PRIVATE-OUTPUT-42" in BOX["results"][0]["output"]
    log = w.LOG.read_text()
    assert "echo PRIVATE-OUTPUT-$((40+2))" in log and "PRIVATE-OUTPUT-42" not in log and KEY not in log, log
    assert w.LOG.stat().st_mode & 0o777 == 0o600
    assert '"via": "auto"' in log and '"agent": "solomon"' in log


def test_stdin_is_closed():
    setup()
    BOX["jobs"].append(job("cat; echo after"))
    t0 = time.time()
    run_loop(lambda: BOX["results"])
    assert time.time() - t0 < 10 and BOX["results"][0]["exitCode"] == 0 and "after" in BOX["results"][0]["output"]


def test_runs_from_home_with_the_drive_unmounted():
    home = setup()
    w.is_mounted = lambda: False
    BOX["jobs"].append(job('pwd; echo "tmp=${TMPDIR:-none}"'))
    run_loop(lambda: BOX["results"])
    r = BOX["results"][0]
    assert str(home) in r["output"] and "/work" not in r["output"], r
    assert BOX["polls"][0]["query"]["drive"] == ["0"]


def test_kills_the_whole_group_at_the_timeout():
    home = setup()
    w.COMMAND_TIMEOUT = 1
    marker = home / "survived"
    BOX["jobs"].append(job(f"(sleep 3; touch {marker}) & echo started; sleep 30"))
    t0 = time.time()
    run_loop(lambda: BOX["results"])
    took = time.time() - t0
    r = BOX["results"][0]
    assert took < 5 and r["timedOut"] is True and "started" in r["output"], (took, r)
    assert r["exitCode"] != 0
    time.sleep(3)
    assert not marker.exists(), "a child outlived the group kill"


def test_a_background_child_holding_the_pipe_cannot_hang_the_worker():
    setup()
    BOX["jobs"].append(job("sleep 20 & echo quick"))
    t0 = time.time()
    run_loop(lambda: BOX["results"])
    assert time.time() - t0 < 6, "the worker waited on a pipe nobody needed"
    assert BOX["results"][0]["exitCode"] == 0 and "quick" in BOX["results"][0]["output"]


def test_redirected_output_still_dies_at_the_timeout():
    """`npm run dev > log 2>&1`: the pipe hits EOF at once and the process runs on."""
    home = setup()
    w.COMMAND_TIMEOUT = 1
    marker = home / "survived"
    BOX["jobs"].append(job(f"(sleep 3; touch {marker}) > {home}/log 2>&1"))
    BOX["jobs"].append(job("echo polling-again", "b" * 32))
    t0 = time.time()
    run_loop(lambda: len(BOX["results"]) >= 2)
    assert time.time() - t0 < 6, "the worker stopped polling"
    assert BOX["results"][0]["timedOut"] is True and BOX["results"][0]["exitCode"] != 0, BOX["results"][0]
    assert "polling-again" in BOX["results"][1]["output"]
    time.sleep(3)
    assert not marker.exists(), "it outlived the kill"


def test_a_silent_background_child_does_not_outlive_the_command():
    home = setup()
    marker = home / "survived"
    BOX["jobs"].append(job(f"(sleep 2; touch {marker}) > /dev/null 2>&1 & echo quick"))
    run_loop(lambda: BOX["results"])
    assert BOX["results"][0]["exitCode"] == 0 and "quick" in BOX["results"][0]["output"]
    time.sleep(2.5)
    assert not marker.exists(), "a background child outlived its command"


def test_huge_output_is_capped_without_filling_memory():
    setup()
    w.COMMAND_TIMEOUT = 2
    BOX["jobs"].append(job("yes aaaaaaaa"))
    run_loop(lambda: BOX["results"])
    r = BOX["results"][0]
    assert len(r["output"]) == w.MAX_OUTPUT and r["truncated"] is True, len(r["output"])


def test_off_file_heartbeats_disabled_and_runs_nothing():
    home = setup()
    w.OFF_FILE.write_text("")
    marker = home / "ran"
    BOX["jobs"].append(job(f"touch {marker}"))
    run_loop(lambda: BOX["results"])
    assert BOX["polls"][0]["query"]["off"] == ["1"]
    assert not marker.exists() and BOX["results"][0]["exitCode"] == -1, BOX["results"]
    assert "off" in BOX["results"][0]["output"].lower()


def test_a_log_that_cannot_be_written_refuses_at_once_and_says_why():
    home = setup()
    marker = home / "ran"
    real_log = w.log

    def full(row):
        raise OSError(28, "No space left on device")

    w.log = full
    try:
        w.handle(job(f"touch {marker}"), KEY)
    finally:
        w.log = real_log
    assert not marker.exists() and BOX["results"][0]["exitCode"] == -1, BOX["results"]
    assert "disk full" in BOX["results"][0]["output"]


def test_a_full_disk_after_the_run_still_reports_the_result():
    setup()
    real_log, calls = w.log, []

    def second_fails(row):
        calls.append(row)
        if row["event"] == "end":
            raise OSError(28, "No space left on device")

    w.log = second_fails
    try:
        w.handle(job("echo landed"), KEY)
    finally:
        w.log = real_log
    assert "landed" in BOX["results"][0]["output"], BOX["results"]


def test_survives_network_failure_and_backs_off_quietly():
    setup()
    good = w.BOX
    w.BOX = "http://127.0.0.1:9"       # nothing listens
    sleeps = []
    BOX["jobs"].append(job("echo back"))

    class Stop:
        def is_set(self):
            return bool(BOX["results"])

        def wait(self, s):
            sleeps.append(s)
            if len(sleeps) == 7:       # the network comes back, inside the same loop
                w.BOX = good

    w.POLL_SECONDS = 5
    try:
        w.loop(Stop())
    finally:
        w.BOX, w.POLL_SECONDS = good, 0.02
    assert sleeps == [10, 20, 40, 60, 60, 60, 60], sleeps
    assert "back" in BOX["results"][0]["output"], "and it recovers"
    log = w.LOG.read_text()
    assert log.count("box unreachable") == 1, "quiet: one line, not one per try"
    assert log.count("box reachable") == 1, log


def test_a_refused_key_backs_off_and_never_crashes():
    setup()
    BOX["status"] = 403
    run_loop(lambda: len(BOX["polls"]) >= 2)
    assert "refused" in w.LOG.read_text() and KEY not in w.LOG.read_text()


def test_a_bad_answer_from_the_box_never_crashes_the_loop():
    setup()
    BOX["jobs"].append({"id": 5})
    BOX["jobs"].append(job("echo fine"))
    run_loop(lambda: BOX["results"])
    assert "fine" in BOX["results"][0]["output"]


def test_https_uses_a_verifying_context():
    ctx = w.tls_context()
    import ssl
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    assert w.BOX == BOX_DEFAULT


def test_runs_on_the_macs_own_python():
    if not Path("/usr/bin/python3").exists():
        return
    src = (HERE / "deploy" / "mac" / "mac_worker.py")
    out = subprocess.run(["/usr/bin/python3", "-c", f"import ast;ast.parse(open({str(src)!r}).read(),feature_version=(3,9))"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert not {"requests", "httpx", "aiohttp"} & set(src.read_text().split()), "stdlib only"


def test_end_to_end_real_worker_real_routes():
    """/usr/bin/python3 running the real worker against the real connector over HTTP."""
    if not Path("/usr/bin/python3").exists() or not Path("/bin/zsh").exists():
        return
    home = setup()
    os.environ["FORGE_MAC_KEY_SHA256"] = hashlib.sha256(KEY.encode()).hexdigest()
    os.environ["FORGE_MARCUS"] = "0"
    sys.path.insert(0, str(HERE))
    import connector
    import mac_link
    srv = ThreadingHTTPServer(("127.0.0.1", 0), connector.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    code = (f"import importlib.util as u;s=u.spec_from_file_location('mac_worker',{str(HERE / 'deploy/mac/mac_worker.py')!r});"
            "w=u.module_from_spec(s);s.loader.exec_module(w);"
            f"w.BOX={base!r};w.DIR=w.Path({str(home)!r});w.KEY_FILE=w.DIR/'key';w.OFF_FILE=w.DIR/'off';"
            f"w.LOG=w.DIR/'worker.log';w.WORK={str(home / 'work')!r};w.VOLUME={str(home)!r};w.HOME={str(home)!r};"
            "w.is_mounted=lambda:True;w.POLL_SECONDS=0.2;w.loop()")
    child = subprocess.Popen(["/usr/bin/python3", "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            if mac_link.status()["online"]:
                break
            time.sleep(0.1)
        assert mac_link.status()["online"], "the worker never reached the route"
        out = mac_link.run('pwd; echo "API_KEY=abc123"', {"surface": "test", "agent": "orion", "via": "auto"})
        assert out["exitCode"] == 0 and str(home / "work") in out["output"], out
        assert "abc123" not in out["output"] and "[redacted]" in out["output"], out
    finally:
        child.terminate()
        child.wait(5)
        srv.shutdown()


BOX_DEFAULT = "https://forge-reios.tail0a2dda.ts.net"


if __name__ == "__main__":
    if not Path("/bin/zsh").exists():
        print("skip: no /bin/zsh (Mac only)")
        raise SystemExit(0)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeBox)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fake = f"http://127.0.0.1:{srv.server_address[1]}"
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    order = sorted(tests, key=lambda f: f.__code__.co_firstlineno)
    failed = 0
    for fn in order:
        w.BOX = BOX_DEFAULT if fn is test_https_uses_a_verifying_context else fake
        try:
            fn()
            print("ok  ", fn.__name__, flush=True)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("FAIL", fn.__name__, f"{type(e).__name__}: {str(e)[:300]}", flush=True)
    print(f"{len(order) - failed} of {len(order)} passed")
    raise SystemExit(1 if failed else 0)
