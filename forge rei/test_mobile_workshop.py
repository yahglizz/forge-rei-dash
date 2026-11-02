"""Mobile workshop (Task 5a): durable tap cards route, task results, and static seam guards for the
phone crew screens. Run with python3 test_mobile_workshop.py (no network, nothing live: the pending
card queue and the task store go to temp files). valjsx only proves the JSX parses; this proves the
wiring. Exit 1 on failure."""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp(prefix="mobile-workshop-test-"))
os.environ["FORGE_ACTION_LOG"] = str(TMP / "actions.jsonl")
os.environ.setdefault("FORGE_MARCUS", "0")

import agents_hub  # noqa: E402
import connector  # noqa: E402
import dash_live  # noqa: E402
import telegram_agent as ta  # noqa: E402

HERE = Path(__file__).parent
M = HERE / "mobile"


def _get(path):
    h = object.__new__(connector.Handler)
    h.path = path
    h.headers = {"Host": "localhost:7799"}
    h.client_address = ("127.0.0.1", 5555)
    h._dashboard_client_allowed = lambda: True
    out = []
    h._send_json = lambda obj, code=200, headers=None: out.append((code, obj))
    connector.Handler.do_GET(h)
    assert len(out) == 1, out
    return out[0]


# ── GET /api/chat/cards ───────────────────────────────────────────────────────────────────
def test_cards_route_lists_open_dash_cards_only():
    ta.STATE = TMP / "pending.json"
    ta.STATE.write_text("{}")
    tap = ta._queue("dash", "solomon", "daycare", "/api/daycare/replies/approve", {"contact_id": "c1"}, "Text a parent")
    batch = ta._queue("dash", "marcus", "wholesale", None, {}, "Two moves", calls=[
        {"path": "/api/pipeline/move", "body": {"id": "a"}}, {"path": "/api/pipeline/move", "body": {"id": "b"}}])
    mac = ta._queue("dash", "orion", "hq", None, {}, "Run on your Mac: ls",
                    mac={"command": "ls", "reason": "look", "why": "any command", "surface": "t"})
    ta._queue("-100", "solomon", "daycare", "/api/daycare/replies/approve", {}, "a Telegram card")
    old = ta._queue("dash", "solomon", "daycare", "/api/daycare/replies/approve", {}, "expired", ttl=60)
    d = json.loads(ta.STATE.read_text())
    d[old]["ts"] = int(time.time()) - 600
    ta.STATE.write_text(json.dumps(d))

    code, res = _get("/api/chat/cards")
    assert code == 200 and res["ok"], res
    toks = [c["tok"] for c in res["cards"]]
    assert set(toks) == {tap, batch, mac}, "dash chat only, and no expired card: %s" % toks
    by = {c["tok"]: c for c in res["cards"]}
    assert by[tap]["kind"] == "tap" and by[tap]["path"] == "/api/daycare/replies/approve" and by[tap]["count"] == 1
    assert by[batch]["count"] == 2 and by[batch]["path"] is None and len(by[batch]["preview"]) == 2
    assert by[mac]["kind"] == "mac" and by[mac]["command"] == "ls" and by[mac]["warning"] == dash_live.MAC_WARNING
    assert all(c["expiresAt"] > time.time() for c in res["cards"])
    assert all("calls" not in c and "body" not in c for c in res["cards"]), "no raw queue entry leaves the box"

    # a workspace sees its own cards plus Orion's, never another business's
    wanted = lambda b: {c["agent"] for c in _get("/api/chat/cards?business=" + b)[1]["cards"]}  # noqa: E731
    assert wanted("daycare") == {"solomon", "orion"}
    assert wanted("wholesale") == {"marcus", "orion"}
    assert wanted("agency") == {"orion"}

    # reading never spends a card: the same tok still confirms once
    assert tap in json.loads(ta.STATE.read_text())
    ta.cancel(tap, "dash")
    assert tap not in [c["tok"] for c in _get("/api/chat/cards")[1]["cards"]], "a cancelled card is gone"
    assert "/api/chat/cards" in connector.NO_CACHE


def test_cards_route_is_not_agent_reachable():
    with mock.patch.object(ta, "catalog", lambda: {"GET": {"/api/chat/cards"}, "POST": set()}):
        for biz in ta.SCOPE:
            assert not ta.allowed(biz, "GET", "/api/chat/cards")[0], biz
        assert not ta.allowed_read("/api/chat/cards")[0]
    assert "/api/chat/" in ta.DENY, "belt: DENY names the whole tap-card family, scope aside"
    for biz in ta.SCOPE:
        for path in ("/api/chat/cards", "/api/chat/action/confirm"):
            assert "off-limits" in ta.allowed(biz, "GET", path)[1], (biz, path)


# ── task result ───────────────────────────────────────────────────────────────────────────
def test_task_result_is_kept_on_done_and_cleared_on_reopen():
    agents_hub.TASKS = TMP / "hub_tasks.json"
    row = agents_hub.send_task("solomon", "Draft a tour follow-up", "short", business="daycare")["task"]
    assert "result" not in row and row["status"] == "open"
    done = agents_hub.update_task(row["id"], "done", result="Here is the draft.\nLine two.")["task"]
    assert done["result"].startswith("Here is the draft.")
    listed = agents_hub.tasks("solomon")["tasks"][0]
    assert listed["result"] == done["result"], "GET /api/hub/tasks carries it"
    assert agents_hub.update_task(row["id"], "done")["task"]["result"] == done["result"], "a plain re-done keeps it"
    assert "result" not in agents_hub.update_task(row["id"], "open")["task"]
    long = agents_hub.update_task(row["id"], "done", result="x" * 9000)["task"]
    assert len(long["result"]) == 4000
    # the hub route never takes a result from the phone: only the agent's own run writes one
    src = (HERE / "connector.py").read_text()
    assert 'agents_hub.update_task(body.get("id"), body.get("status"))' in src
    assert 'agents_hub.update_task(job["taskId"], "done", result=reply)' in (HERE / "agent_office.py").read_text()


# ── static seam guards on the phone screens ───────────────────────────────────────────────
def test_static_roster_matches_agents_hub():
    src = (M / "m_agents.jsx").read_text()
    block = src[src.index("const MA_AGENTS = ["):src.index("const MA_KNOWN_BIZ")]
    ids = re.findall(r'\{ id: "(\w+)"', block)
    biz = dict(re.findall(r'id: "(\w+)".*?business: "(\w+)"', block, re.S))
    want = {a["id"]: a["business"] for a in agents_hub.AGENTS
            if not a.get("lane") and a["business"] in ("wholesale", "agency", "daycare", "cross")}
    assert sorted(ids) == sorted(want), (ids, sorted(want))
    assert biz == want, (biz, want)
    assert "midas" not in ids, "archived Dropship stays off the phone"


def test_crew_screen_wiring():
    a = (M / "m_agents.jsx").read_text()
    # 1. slow replies: a 330 s cap on chat, a 20 s "still working", a Cancel, Retry that keeps the text
    assert "MA_TIMEOUT_MS = 330000" in a and "MA_SLOW_S = 20" in a
    assert "timeoutMs: MA_TIMEOUT_MS" in a and "signal: ctl.signal" in a and "maCancel" in a
    assert ">Cancel</button>" in a and ">Retry</button>" in a and "still working" in a
    assert "setDrafts((d) => (d[a.id] ? d : Object.assign({}, d, { [a.id]: q })))" in a, "typed message kept"
    # 2. durable cards: read from the queue, count badge in the tab bar and the header bot
    assert '"/api/chat/cards"' in a and "ChatActions actions={myCards}" in a and "d.actions" in a
    sh = (M / "m_shell.jsx").read_text()
    assert "function MCrewBadge" in sh and '"/api/chat/cards"' in sh
    assert 't.key === "crew" && <MCrewBadge />' in sh and "<MCrewBadge /></button>" in sh
    assert ".m-cards button" in (M / "mobile.css").read_text() and "min-height:44px" in (M / "mobile.css").read_text().replace(" ", "")
    # 4. status line from the registry rows already polled, no new timer for it
    assert "function MAState" in a and "pendingApprovals" in a and "openTasks" in a and "Waiting on you" in a
    assert a.count("interval:") == 3 and a.count("setInterval") == 1, "same polls as before (bus, registry, history) plus the seconds counter"
    # 6. Orion in every crew; an unknown business is never routed to the hub chat by default
    assert 'b === business || b === "cross"' in a
    assert "return null;" in a[a.index("function MAChatTarget"):a.index("function MAState")]
    assert "}).filter((a) => a.ep)" in a
    assert '/api/office/chat' in a
    # 7. Mac state from the status route, refreshed with the registry poll
    assert '"/api/mac/status"' in a and "Mac offline, last seen" in a and "mac.enabled" in a
    assert "macM.refresh()" in a and "rosterM.data.generatedAt" in a


def test_tasks_screen_wiring():
    t = (M / "m_tasks.jsx").read_text()
    for needle in ('"/api/hub/tasks"', '"/api/hub/task"', '"/api/hub/task/update"', "window.MATasksCard", "t.result", "Mark done",
                   "a.business !== \"cross\""):
        assert needle in t or needle.replace("window.", "") in t, needle
    assert re.search(r"Object\.assign\(window,\s*\{\s*MATasksCard\s*\}\)", t)
    assert "window.MATasksCard" in (M / "m_agents.jsx").read_text()
    html = (M / "index.html").read_text()
    assert html.index('src="m_agents.jsx"') < html.index('src="m_tasks.jsx"') < html.index('src="m_more.jsx"')
    for f in ("m_tasks.jsx", "m_agents.jsx", "m_shell.jsx", "m_api.jsx"):
        s = (M / f).read_text()
        assert not re.search(r"<\w+\[", s), f + " computed JSX tag"
    # hook aliases: the file's own, declared once, used nowhere else (one Babel scope for every script)
    declared = set(re.findall(r"use(?:State|Effect|Ref): (\w+)", t))
    assert declared and all(x.endswith("MT") for x in declared), declared
    for alias in declared:
        for f in list(HERE.glob("*.jsx")) + list(M.glob("*.jsx")):
            if f.name != "m_tasks.jsx":
                assert not re.search(r"\b%s\b" % alias, f.read_text()), (alias, "reused in", f.name)


def test_api_post_has_a_timeout_and_cancel():
    s = (M / "m_api.jsx").read_text()
    body = s[s.index("async function apiPostM"):s.index("// Native iOS shell")]
    assert "AbortController" in body and "signal: ctl.signal" in body and "opts.timeoutMs ||" in body and "120000" in body
    assert '/api/chat/action/' in body and "330000" in body, "card taps get the long cap"
    assert 'why = "timeout"' in body and 'why === "timeout"' in body and 'err.code = why' in body
    assert "removeEventListener" in body and "clearTimeout(timer)" in body


def test_status_line_checks_status_before_approvals():
    a = (M / "m_agents.jsx").read_text()
    fn = a[a.index("function MAState"):a.index("function MAgentsPage")]
    assert fn.index('"FAILED" || st === "DEGRADED"') < fn.index("approvals > 0 ||"), "trouble before 'waiting on you'"


NODE_CHECK = r"""
const http = require('http'), fs = require('fs');
global.window = global;
const src = fs.readFileSync(process.argv[2], 'utf8');
const seen = [];
const srv = http.createServer((req, res) => {
  let b = ''; req.on('data', d => b += d);
  req.on('end', () => setTimeout(() => {
    seen.push(req.url); res.setHeader('content-type', 'application/json');
    if (req.url.startsWith('/err')) { res.statusCode = 500; return res.end('{"error":"boom"}'); }
    res.end('{"ok":true,"echo":' + b + '}');
  }, req.url.startsWith('/slow') ? 400 : 0));
});
srv.listen(0, async () => {
  const base = 'http://127.0.0.1:' + srv.address().port, real = fetch;
  global.fetch = (u, o) => real(base + u, o);
  const timers = [];
  const st = global.setTimeout;
  global.setTimeout = (f, ms, ...r) => { timers.push(ms); return st(f, ms, ...r); };
  new Function(src + ';global.apiPostM = apiPostM;')();
  const out = {};
  out.fast = await apiPostM('/fast', { a: 1 });
  const grab = async (path, opts) => { timers.length = 0; await apiPostM(path, {}, opts); return timers[0]; };
  out.capDefault = await grab('/fast');
  out.capTap = await grab('/api/chat/action/confirm');
  out.capChat = await grab('/fast', { timeoutMs: 330000 });
  const tryIt = async (path, opts) => { try { await apiPostM(path, {}, opts); return 'no throw'; } catch (e) { return e.code + ':' + e.message; } };
  out.timeout = await tryIt('/slow', { timeoutMs: 100 });
  const c = new AbortController(); st(() => c.abort(), 100);
  out.cancel = await tryIt('/slow', { signal: c.signal });
  const pre = new AbortController(); pre.abort();
  out.pre = await tryIt('/slow', { signal: pre.signal });
  out.err = await tryIt('/err');
  console.log(JSON.stringify(out));
  srv.close();
});
"""


def test_api_post_timeout_and_cancel_run_for_real():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("skip  test_api_post_timeout_and_cancel_run_for_real (no node)")
        return
    script = TMP / "api_check.js"
    script.write_text(NODE_CHECK)
    src = re.sub(r"^const \{[^}]*\} = React;", "", (M / "m_api.jsx").read_text(), flags=re.M)
    jsx = TMP / "m_api_plain.js"
    jsx.write_text(src)
    r = subprocess.run([node, str(script), str(jsx)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["fast"] == {"ok": True, "echo": {"a": 1}}, out
    assert out["capDefault"] == 120000 and out["capTap"] == 330000 and out["capChat"] == 330000, out
    assert out["timeout"] == "timeout:No answer in time", out
    assert out["cancel"] == "cancelled:Cancelled" and out["pre"] == "cancelled:Cancelled", out
    assert out["err"] == "undefined:boom", out


def main():
    failed = 0
    saved = (ta.STATE, agents_hub.TASKS)
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and callable(fn):
                try:
                    fn()
                    print("ok  ", name)
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    import traceback
                    print("FAIL", name, "->", repr(e))
                    traceback.print_exc()
    finally:
        ta.STATE, agents_hub.TASKS = saved
    print("mobile workshop:", "FAILED" if failed else "all OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
