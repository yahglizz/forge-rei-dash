#!/usr/bin/env python3
"""FORGE REI OS — live smoke test.

Curls every GET endpoint on the running box, applies a per-endpoint freshness
assertion, and prints a PASS/FAIL matrix + exit code. The reusable sibling of
push.sh: push.sh proves the deploy landed; this proves the whole surface is
CONNECTED, UP, and LIVE (box <-> GHL, agent loops green, sync bridge alive).

Read-only. The ONLY thing it touches is GET routes. Nothing outward, nothing
mutating. (Deliberately skips /api/goals/today, which has a documented offer
auto-tag GHL write side-effect.)

Usage:
    python3 deploy/live_smoke.py                       # --via tunnel (localhost:7799)
    python3 deploy/live_smoke.py --via ssh --host root@24.199.81.124
    python3 deploy/live_smoke.py --json                # machine-readable for a consolidator
    python3 deploy/live_smoke.py --warn-ok             # unconfigured integrations = pass

Exit 0 iff every CRITICAL endpoint passes and every SECURITY-negative is blocked.
"""
import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "http://localhost:7799"

# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------
class Fetcher:
    """GET a path against the box, return (status, body_text). Never raises."""

    def __init__(self, via, host, base, timeout=8, identity=None):
        self.via = via
        self.host = host
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.identity = identity  # ssh -i key (else rely on ssh config / agent)

    def get(self, path):
        if self.via == "ssh":
            return self._ssh_get(path)
        return self._http_get(path)

    def _http_get(self, path):
        url = self.base + path
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                return r.getcode(), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                body = ""
            return e.code, body
        except Exception as e:  # noqa: BLE001 — connection refused, timeout, etc.
            return 0, "TRANSPORT_ERROR: " + str(e)

    def _ssh_get(self, path):
        # One ssh+curl per endpoint. -w appends a sentinel + HTTP code so we can
        # split the status off a body of any length. curl -s (no -f) so 404s come
        # back with their code instead of erroring.
        remote = ("curl -s -m %d -o - -w '\\n@@STATUS@@%%{http_code}' "
                  "'http://127.0.0.1:7799%s'" % (self.timeout, path))
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if self.identity:
            cmd += ["-i", self.identity]
        cmd += [self.host, remote]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout + 15)
        except Exception as e:  # noqa: BLE001
            return 0, "SSH_ERROR: " + str(e)
        raw = out.stdout
        if "@@STATUS@@" in raw:
            body, _, code = raw.rpartition("@@STATUS@@")
            try:
                return int(code.strip()), body
            except ValueError:
                return 0, raw
        return 0, (out.stderr or raw or "no output")


# ---------------------------------------------------------------------------
# assertion helpers  — each returns (ok: bool, detail: str)
# ---------------------------------------------------------------------------
def _json(body):
    try:
        return json.loads(body)
    except Exception:
        return None


def ok200(status, body):
    """200 + valid JSON + no top-level 'error' key."""
    if status != 200:
        return False, "HTTP %s" % status
    j = _json(body)
    if j is None:
        return False, "non-JSON body"
    if isinstance(j, dict) and j.get("error"):
        return False, "error: %s" % str(j.get("error"))[:60]
    return True, "200 ok"


def sync_fresh(status, body):
    j = _json(body) or {}
    if status != 200:
        return False, "HTTP %s" % status
    ver = str(j.get("version") or "")
    if not re.match(r"^\d+:\d+$", ver):
        return False, "bad version %r" % ver
    if j.get("pollMs") not in (2000, "2000"):
        return False, "pollMs=%r (want 2000)" % j.get("pollMs")
    return True, "version %s pollMs 2000" % ver


def health_ok(status, body):
    j = _json(body) or {}
    if status != 200:
        return False, "HTTP %s" % status
    if not j.get("ok"):
        # surface which probe tripped it
        probes = []
        for k in ("scout", "followup", "contract"):
            p = j.get(k)
            if isinstance(p, dict) and (p.get("stale") or p.get("lastError")):
                probes.append("%s stale/err" % k)
        return False, "ok=false" + (" (" + ", ".join(probes) + ")" if probes else "")
    return True, "ok, loopsEnabled=%s" % j.get("loopsEnabled")


def system_health_ok(status, body):
    j = _json(body) or {}
    if status != 200:
        return False, "HTTP %s" % status
    if not j.get("ok"):
        red = j.get("redLoops") or []
        return False, "ok=false redLoops=%s diskOk=%s" % (red, j.get("diskOk"))
    if not j.get("active", True):
        return False, "active=false (loops off or paused)"
    red = j.get("redLoops") or []
    if red:
        return False, "redLoops=%s" % red
    loops = j.get("loops") or []
    greens = sum(1 for l in loops if l.get("status") == "green")
    return True, "%d/%d loops green, diskOk=%s" % (greens, len(loops), j.get("diskOk"))


def ace_off(status, body):
    j = _json(body) or {}
    if status != 200:
        return False, "HTTP %s" % status
    if j.get("mode") != "off":
        return False, "mode=%r (must be off on live box)" % j.get("mode")
    return True, "mode off"


def dashboard_live(status, body):
    j = _json(body) or {}
    if status != 200:
        return False, "HTTP %s" % status
    names = j.get("pipelineNames") or j.get("pipelines")
    if not names:
        # pipelineValue present is a weaker but acceptable GHL-reachable signal
        if j.get("pipelineValue") is None and j.get("openOpportunities") is None:
            return False, "no pipeline data (box<->GHL down?)"
    conv = j.get("totalConversations")
    return True, "pipelines=%s conv=%s" % (
        len(names) if isinstance(names, (list, dict)) else "y", conv)


def convos_nonempty(status, body):
    j = _json(body) or {}
    if status != 200:
        return False, "HTTP %s" % status
    c = j.get("conversations")
    if not isinstance(c, list) or not c:
        return False, "conversations empty (GHL mirror stale?)"
    return True, "%d conversations" % len(c)


def contacts_nonempty(status, body):
    j = _json(body) or {}
    if status != 200:
        return False, "HTTP %s" % status
    n = j.get("total") or j.get("count")
    lst = j.get("contacts")
    if not n and not (isinstance(lst, list) and lst):
        return False, "no contacts"
    return True, "contacts=%s" % (n or len(lst))


def ops_not_paused(status, body):
    j = _json(body) or {}
    if status != 200:
        return False, "HTTP %s" % status
    if j.get("paused"):
        return False, "paused=true (crew clocked out — loops frozen)"
    return True, "not paused"


def testmode_off(status, body):
    j = _json(body) or {}
    if status != 200:
        return False, "HTTP %s" % status
    if j.get("enabled"):
        return False, "test-mode ENABLED (phones=%s) — expected off" % j.get("phones")
    return True, "test-mode off"


def warn_ok(status, body):
    """WARN tier: 200 is connected; anything else is a non-fatal 'not connected'."""
    if status == 200:
        j = _json(body)
        if isinstance(j, dict) and j.get("error"):
            return None, "reachable, not connected: %s" % str(j.get("error"))[:40]
        return True, "connected"
    return None, "not connected (HTTP %s)" % status


def blocked(status, body):
    """SECURITY-negative: the path must NOT be served (expect 403/404)."""
    if status == 200:
        return False, "SERVED (200) — secret/state leak!"
    return True, "blocked (HTTP %s)" % status


# ---------------------------------------------------------------------------
# endpoint inventory  (path, tier, check)
#   tier: CRIT (must pass), WARN (non-fatal), SEC (must be blocked)
# ---------------------------------------------------------------------------
ENDPOINTS = [
    # -- CRITICAL: health / sync / liveness --
    ("/api/sync", "CRIT", sync_fresh),
    ("/api/health", "CRIT", health_ok),
    ("/api/system/health", "CRIT", system_health_ok),
    ("/api/ace/status", "CRIT", ace_off),
    ("/api/cost/status", "CRIT", ok200),
    ("/api/ops/status", "CRIT", ops_not_paused),
    ("/api/test-mode", "CRIT", testmode_off),

    # -- CRITICAL: GHL live read (box <-> GHL) --
    ("/api/dashboard", "CRIT", dashboard_live),
    ("/api/contacts?limit=5", "CRIT", contacts_nonempty),
    ("/api/conversations?limit=10", "CRIT", convos_nonempty),
    ("/api/pipeline", "CRIT", ok200),
    ("/api/tasks?scan=10", "CRIT", ok200),
    ("/api/analytics", "CRIT", ok200),

    # -- CRITICAL: agents (LOCAL in-mem) --
    ("/api/scout/summary", "CRIT", ok200),
    ("/api/scout/leads?bucket=asap", "CRIT", ok200),
    ("/api/scout/pipeline", "CRIT", ok200),
    ("/api/scout/overview", "CRIT", ok200),
    ("/api/scout/audit", "CRIT", ok200),
    ("/api/marcus/status", "CRIT", ok200),
    ("/api/marcus/proposals", "CRIT", ok200),
    ("/api/marcus/directives", "CRIT", ok200),
    ("/api/screening/queue", "CRIT", ok200),
    ("/api/screening/status", "CRIT", ok200),
    ("/api/followup/status", "CRIT", ok200),
    ("/api/today", "CRIT", ok200),
    ("/api/prep/list", "CRIT", ok200),
    ("/api/prep/status", "CRIT", ok200),
    ("/api/deals/list", "CRIT", ok200),
    ("/api/deals/stats", "CRIT", ok200),
    ("/api/ace/state", "CRIT", ok200),
    ("/api/ace/callready", "CRIT", ok200),
    ("/api/ace/digest", "CRIT", ok200),
    ("/api/skillforge/pending", "CRIT", ok200),
    ("/api/bus?limit=20", "CRIT", ok200),

    # -- CRITICAL: brain / vault (proves vault synced to box) --
    ("/api/brain/tree", "CRIT", ok200),
    ("/api/brain/status", "CRIT", ok200),
    ("/api/brain/recent", "CRIT", ok200),
    ("/api/brain/graph", "CRIT", ok200),
    ("/api/brain/activity", "CRIT", ok200),
    ("/api/graphify/graph", "CRIT", ok200),
    ("/api/graphify/stats", "CRIT", ok200),

    # -- CRITICAL: toolkit / local stores --
    ("/api/toolkit/calc/config", "CRIT", ok200),
    ("/api/toolkit/blast/list", "CRIT", ok200),
    ("/api/toolkit/pipeline/reminders", "CRIT", ok200),
    ("/api/toolkit/contracts/list", "CRIT", ok200),
    ("/api/toolkit/contracts/mytemplates", "CRIT", ok200),
    ("/api/buyers/list", "CRIT", ok200),
    ("/api/buyers/dispo", "CRIT", ok200),
    ("/api/contract/config", "CRIT", ok200),
    ("/api/goals/monthly", "CRIT", ok200),
    ("/api/notify/settings", "CRIT", ok200),
    ("/api/brief", "CRIT", ok200),
    ("/api/recap", "CRIT", ok200),

    # -- WARN: live-if-cred integrations (pass even if MOCK/not-connected) --
    ("/api/outbound/status", "WARN", warn_ok),
    ("/api/outbound/calls?limit=5", "WARN", warn_ok),
    ("/api/outbound/agent", "WARN", warn_ok),
    ("/api/outbound/voices", "WARN", warn_ok),
    ("/api/agents/list", "WARN", warn_ok),
    ("/api/review/latest", "WARN", warn_ok),
    ("/api/style/latest", "WARN", warn_ok),
    ("/api/agency/clients", "WARN", warn_ok),
    ("/api/agency/stats", "WARN", warn_ok),
    ("/api/agency/health", "WARN", warn_ok),
    ("/api/agency/requests", "WARN", warn_ok),
    ("/api/agency/workflows", "WARN", warn_ok),
    ("/api/agency/ads", "WARN", warn_ok),
    ("/api/agency/ads/accounts", "WARN", warn_ok),
    ("/api/agency/eco", "WARN", warn_ok),
    ("/api/agency/social", "WARN", warn_ok),
    ("/api/agency/approvals", "WARN", warn_ok),
    ("/api/agency/agents", "WARN", warn_ok),
    ("/api/agency/settings", "WARN", warn_ok),
    ("/api/agency/deploy/status", "WARN", warn_ok),
    ("/api/agency/ghl/dashboard", "WARN", warn_ok),

    # -- SECURITY-negative: must NOT be served --
    ("/ghl.env", "SEC", blocked),
    ("/marcus_state/heartbeats.json", "SEC", blocked),
    ("/connector.py", "SEC", blocked),
    ("/deploy/push.sh", "SEC", blocked),
]


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
def run(fetcher, warn_ok_mode=False):
    rows = []
    for path, tier, check in ENDPOINTS:
        status, body = fetcher.get(path)
        ok, detail = check(status, body)
        # WARN "not connected" comes back as ok=None
        verdict = "PASS" if ok is True else ("WARN" if ok is None else "FAIL")
        if tier == "WARN" and verdict == "WARN" and warn_ok_mode:
            verdict = "PASS"
        rows.append({"path": path, "tier": tier, "http": status,
                     "verdict": verdict, "detail": detail})
    return rows


def summarize(rows):
    crit = [r for r in rows if r["tier"] == "CRIT"]
    warn = [r for r in rows if r["tier"] == "WARN"]
    sec = [r for r in rows if r["tier"] == "SEC"]
    crit_pass = sum(1 for r in crit if r["verdict"] == "PASS")
    warn_conn = sum(1 for r in warn if r["verdict"] == "PASS")
    sec_block = sum(1 for r in sec if r["verdict"] == "PASS")
    crit_ok = crit_pass == len(crit)
    sec_ok = sec_block == len(sec)
    return {
        "critical": "%d/%d" % (crit_pass, len(crit)),
        "warn_connected": "%d/%d" % (warn_conn, len(warn)),
        "security_blocked": "%d/%d" % (sec_block, len(sec)),
        "pass": crit_ok and sec_ok,
    }


def main():
    ap = argparse.ArgumentParser(description="FORGE REI OS live smoke test")
    ap.add_argument("--via", choices=["tunnel", "ssh"], default="tunnel")
    ap.add_argument("--host", default="root@24.199.81.124",
                    help="ssh target for --via ssh")
    ap.add_argument("--identity", "-i", default=None,
                    help="ssh identity file for --via ssh (e.g. ~/.ssh/forge_droplet)")
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help="base URL for --via tunnel")
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--warn-ok", action="store_true",
                    help="treat unconfigured integrations as PASS")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON")
    args = ap.parse_args()

    identity = args.identity
    if identity and identity.startswith("~"):
        import os
        identity = os.path.expanduser(identity)
    fetcher = Fetcher(args.via, args.host, args.base, args.timeout, identity)
    rows = run(fetcher, warn_ok_mode=args.warn_ok)
    summary = summarize(rows)

    if args.json:
        print(json.dumps({"summary": summary, "rows": rows}, indent=2))
    else:
        icon = {"PASS": "✓", "WARN": "~", "FAIL": "✗"}
        print("\nFORGE REI OS — live smoke  (via %s)\n" % args.via)
        for r in rows:
            print("  %s  %-5s %-42s %-4s  %s" % (
                icon.get(r["verdict"], "?"), r["tier"], r["path"],
                r["http"], r["detail"]))
        print("\n  CRITICAL: %s PASS   ·   WARN: %s connected   ·   SECURITY: %s blocked"
              % (summary["critical"], summary["warn_connected"], summary["security_blocked"]))
        print("  VERDICT: %s\n" % ("LIVE ✓ (connected · up)" if summary["pass"]
                                    else "FAIL — see ✗ rows above"))

    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
