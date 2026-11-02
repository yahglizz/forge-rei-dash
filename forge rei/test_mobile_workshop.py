"""Mobile workshop (Task 5a): durable tap cards route, task results, and static seam guards for the
phone crew screens. Run with python3 test_mobile_workshop.py (no network, nothing live: the pending
card queue and the task store go to temp files). valjsx only proves the JSX parses; this proves the
wiring. Exit 1 on failure."""
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp(prefix="mobile-workshop-test-"))
os.environ["FORGE_ACTION_LOG"] = str(TMP / "actions.jsonl")
os.environ.setdefault("FORGE_MARCUS", "0")

import agent_bus  # noqa: E402
import agent_office  # noqa: E402
import agents_hub  # noqa: E402
import agents_history  # noqa: E402
import connector  # noqa: E402
import dash_live  # noqa: E402
import forge_ops  # noqa: E402
import mac_link  # noqa: E402
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


# ── GET /api/chat/waiting ("Waiting on you" at the top of Crew) ─────────────────────────────
def test_waiting_route_lists_every_open_dash_card_newest_first():
    ta.STATE = TMP / "pending_waiting.json"
    ta.STATE.write_text("{}")
    key = "sk-ant-" + "x" * 30
    oldest = ta._queue("dash", "solomon", "daycare", "/api/daycare/replies/approve", {"contact_id": "c1"}, "Text a parent")
    mac = ta._queue("dash", "orion", "hq", None, {}, "Run on your Mac: ls",
                    mac={"command": "ls -la", "reason": "look", "why": "any command", "surface": "t"})
    keyed = ta._queue("dash", "dyson", "agency", None, {}, "Run on your Mac: curl",
                      mac={"command": "curl -H 'x: " + key + "' example.test", "reason": "r", "why": "w", "surface": "t"})
    newest = ta._queue("dash", "marcus", "wholesale", None, {}, "Two moves", calls=[
        {"path": "/api/pipeline/move", "body": {"id": "a"}}, {"path": "/api/pipeline/move", "body": {"id": "b"}}])
    ta._queue("-100", "solomon", "daycare", "/api/daycare/replies/approve", {}, "a Telegram card")
    gone = ta._queue("dash", "solomon", "daycare", "/api/daycare/replies/approve", {}, "expired", ttl=60)
    d = json.loads(ta.STATE.read_text())
    now = int(time.time())
    for i, tok in enumerate((oldest, mac, keyed, newest)):
        d[tok]["ts"] = now - 100 + i
    d[gone]["ts"] = now - 600
    ta.STATE.write_text(json.dumps(d))

    code, res = _get("/api/chat/waiting")
    assert code == 200 and res["ok"], res
    toks = [c["tok"] for c in res["cards"]]
    assert toks == [newest, keyed, mac, oldest], "dash only, unexpired only, every business, newest first: %s" % toks
    by = {c["tok"]: c for c in res["cards"]}
    assert by[oldest]["kind"] == "write" and by[newest]["kind"] == "write" and by[mac]["kind"] == "mac"
    for c in res["cards"]:
        assert {"tok", "agent", "summary", "kind", "expiresIn"} <= set(c), c
        assert 0 < c["expiresIn"] <= ta.PENDING_TTL, c
        assert "calls" not in c and "body" not in c, "no raw queue entry leaves the box"
    assert by[mac]["command"] == "ls -la" and by[mac]["redacted"] is False
    assert by[mac]["reason"] == "look" and by[mac]["why"] == "any command" and by[mac]["warning"] == dash_live.MAC_WARNING
    assert key not in json.dumps(res) and "[redacted]" in by[keyed]["command"] and by[keyed]["redacted"] is True
    assert "command" not in by[oldest] and by[newest]["count"] == 2, "a write card carries its in-chat text only"
    assert "/api/chat/waiting" in connector.NO_CACHE
    assert json.loads(ta.STATE.read_text())[keyed]["mac"]["command"].count(key) == 1, "reading never changes the card"

    # not agent-reachable: the whole /api/chat/ family is in DENY, scope aside
    with mock.patch.object(ta, "catalog", lambda: {"GET": {"/api/chat/waiting"}, "POST": set()}):
        for biz in ta.SCOPE:
            assert "off-limits" in ta.allowed(biz, "GET", "/api/chat/waiting")[1], biz
        assert not ta.allowed_read("/api/chat/waiting")[0]


def test_waiting_card_tap_is_the_existing_confirm_and_pops_once():
    ta.STATE = TMP / "pending_waiting_tap.json"
    ta.STATE.write_text("{}")
    tok = ta._queue("dash", "solomon", "daycare", "/api/daycare/ghl/tag", {"contact_id": "c1"}, "Tag a parent")
    drop = ta._queue("dash", "solomon", "daycare", "/api/daycare/ghl/tag", {"contact_id": "c2"}, "Tag another parent")
    sent = []
    fake_http = lambda method, path, query=None, body=None, timeout=90: sent.append((method, path, body)) or {"ok": True}  # noqa: E731
    with mock.patch.object(ta, "catalog", lambda: {"GET": set(), "POST": {"/api/daycare/ghl/tag"}}), \
            mock.patch.object(ta, "_http", fake_http), \
            mock.patch.object(forge_ops, "paused", lambda: False), \
            mock.patch.object(connector, "_dash_tap_history", lambda *a: None):
        listed = [c["tok"] for c in _get("/api/chat/waiting")[1]["cards"]]
        assert set(listed) == {tok, drop}, listed
        first = _post("/api/chat/action/confirm", {"tok": tok})[1]
        second = _post("/api/chat/action/confirm", {"tok": tok})[1]
        assert first.get("ok") and "Tag a parent" in first["message"], first
        assert "expired" in second.get("error", ""), second
        assert sent == [("POST", "/api/daycare/ghl/tag", {"contact_id": "c1"})], "ran once: %s" % sent
        assert _post("/api/chat/action/cancel", {"tok": drop})[1]["ok"]
        assert "error" in _post("/api/chat/action/cancel", {"tok": drop})[1]
        assert _get("/api/chat/waiting")[1]["cards"] == [], "a tapped or cancelled card leaves the list"
    assert len(sent) == 1


def test_waiting_list_wiring():
    w = (M / "m_waiting.jsx").read_text()
    assert '"/api/chat/waiting"' in w and "WY_POLL_MS = 20000" in w
    assert 'document.visibilityState === "visible"' in w and '"visibilitychange"' in w
    assert "clearInterval(iv)" in w and 'removeEventListener("visibilitychange"' in w
    # the in-chat card renderer and its endpoints, never a second approval path
    assert "<window.ChatActions actions={[c]} />" in w
    assert "/api/chat/action" not in w.split("// Hook aliases")[1] and "apiPost" not in w
    assert 'className="m-cards"' in w and "minHeight: 44" in w, "44px taps (.m-cards button) and the refresh button"
    assert '"Waiting on you (" + n + ")"' in w and "if (!shown.length) return null;" in w
    assert "rows[k].until > now" in w, "expired rows drop out between polls"
    assert 'c.kind === "mac" && c.redacted' in w and "<WYHidden c={c} />" in w, "a redacted Mac command gets no ✅"
    assert re.search(r"Object\.assign\(window,\s*\{\s*MAWaitingCard\s*\}\)", w)
    assert not re.search(r"<\w+\[", w), "computed JSX tag"
    declared = set(re.findall(r"use(?:State|Effect|Ref): (\w+)", w))
    assert declared == {"useEffectWY", "useRefWY"}, declared
    for f in list(HERE.glob("*.jsx")) + list(M.glob("*.jsx")):
        if f.name != "m_waiting.jsx":
            for name in declared | {"WY_POLL_MS", "wyName", "wyLeft", "WYHidden", "MAWaitingCard"}:
                assert not re.search(r"\b%s\b" % name, f.read_text()) or (name == "MAWaitingCard" and f.name == "m_agents.jsx"), (name, f.name)
    a = (M / "m_agents.jsx").read_text()
    body = a[a.index('<div className="m-content" style={{ gap: 10 }}>'):]
    assert body.index("<window.MAWaitingCard />") < body.index("(macLine || n8nLine)"), "first thing in Crew"
    html = (M / "index.html").read_text()
    assert html.index('src="../chat_actions.jsx"') < html.index('src="m_waiting.jsx"') < html.index('src="m_app.jsx"')


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


# ── Run now: an open task runs through the office job ─────────────────────────────────────
def _post(path, body):
    payload = json.dumps(body).encode()
    h = object.__new__(connector.Handler)
    h.path = path
    h.headers = {"Host": "localhost:7799", "Content-Length": str(len(payload))}
    h.rfile = io.BytesIO(payload)
    h.client_address = ("127.0.0.1", 5555)
    h._dashboard_client_allowed = lambda: True
    out = []
    h._send_json = lambda obj, code=200, headers=None: out.append((code, obj))
    h._daycare_resolve_session = lambda sid: (object(), None)
    h._daycare_require_secure = lambda: None
    connector.Handler.do_POST(h)
    assert len(out) == 1, out
    return out[0]


def _wait_job(jid):
    for _ in range(100):
        j = agent_office.job(jid)["job"]
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_run_now_runs_the_existing_task_with_chat_gates():
    agents_hub.TASKS = TMP / "hub_tasks_run.json"
    agent_office._JOBS.clear()
    seen = []

    def fake_chat(ghl_get, loc, agent_id, message, **kw):
        col = dash_live._col()                    # the chat collector: AUTO writes + TAP cards
        seen.append(col is not None)
        if col is not None:
            col["actions"].append({"tok": "t1", "kind": "tap", "agent": agent_id, "summary": "Text a parent"})
            col["done"].append({"summary": "Tagged 2 leads", "ok": True})
        return {"reply": "Here is the plan.", "agent": agent_id}

    row = agents_hub.send_task("solomon", "Draft the tour follow-up", "short", business="daycare")["task"]
    with mock.patch.object(agent_office, "AUTO_CHECKIN", False), \
            mock.patch.object(agent_bus, "STATE", TMP / "bus.json"), \
            mock.patch.object(agents_hub, "chat", fake_chat), \
            mock.patch.object(agents_history, "record", lambda *a, **k: None), \
            mock.patch.object(forge_ops, "paused", lambda: False):
        # a plain office dispatch stays read-only: no collector
        plain = _post("/api/office/task", {"agentId": "marcus", "title": "Plain job", "business": "wholesale"})[1]
        assert plain["ok"], plain
        _wait_job(plain["jobId"])
        assert seen == [False], "a floor dispatch never opens the write gates"
        rows_before = len(agents_hub.tasks()["tasks"])

        code, res = _post("/api/office/task", {"agentId": "solomon", "title": "ignored", "taskId": row["id"],
                                               "business": "daycare"})
        assert code == 200 and res["ok"] and res["taskId"] == row["id"], res
        job = _wait_job(res["jobId"])
        assert job["status"] == "done" and seen[-1] is True, "run now opens chat's collector"
        assert "Here is the plan." in job["result"] and "Did: Tagged 2 leads" in job["result"]
        assert "1 card(s) are waiting for your tap" in job["result"]
        assert job["title"] == "Draft the tour follow-up", "the stored task is the truth, not the request body"
        assert len(agents_hub.tasks()["tasks"]) == rows_before, "no second task row"
        done = next(t for t in agents_hub.tasks("solomon")["tasks"] if t["id"] == row["id"])
        assert done["status"] == "done" and done["result"].startswith("Here is the plan."), done

        # not open any more / another agent's / wrong workspace / clocked out: refused, nothing runs
        n = len(seen)
        assert "isn't open" in _post("/api/office/task", {"agentId": "solomon", "title": "x", "taskId": row["id"]})[1]["error"]
        other = agents_hub.send_task("marcus", "Marcus job", "", business="wholesale")["task"]
        assert "isn't open" in _post("/api/office/task", {"agentId": "solomon", "title": "x", "taskId": other["id"]})[1]["error"]
        assert "floor" in _post("/api/office/task", {"agentId": "marcus", "title": "x", "taskId": other["id"],
                                                     "business": "daycare"})[1]["error"]
        with mock.patch.object(forge_ops, "paused", lambda: True):
            assert "clocked out" in _post("/api/office/task", {"agentId": "marcus", "title": "x", "taskId": other["id"]})[1]["error"]
        assert len(seen) == n


def test_run_now_is_tainted_so_an_auto_write_becomes_a_card():
    """A filed task's title and note can carry outside text, so a Run now job's collector starts tainted:
    a write that is AUTO tier in plain chat is a tap card here, and nothing runs."""
    agents_hub.TASKS = TMP / "hub_tasks_taint.json"
    ta.STATE = TMP / "pending_taint.json"
    ta.STATE.write_text("{}")
    http = []
    tag = {"path": "/api/daycare/ghl/tag", "body": {"contact_id": "c1", "add": ["enrolled-2026"]}, "summary": "Tag a parent"}
    fake_http = lambda method, path, query=None, body=None, timeout=90: http.append((method, path)) or {"ok": True}  # noqa: E731

    def fake_chat(ghl_get, loc, agent_id, message, **kw):
        out = dash_live._write("api_post", tag, "solomon", dash_live._col())
        return {"reply": "Tried a tag: " + json.dumps(out)[:80], "agent": agent_id}

    row = agents_hub.send_task("solomon", "Tag the new families (from an outside note)", "x", business="daycare")["task"]
    with mock.patch.object(ta, "catalog", lambda: {"GET": set(), "POST": {"/api/daycare/ghl/tag"}}), \
            mock.patch.object(ta, "_http", fake_http), \
            mock.patch.object(dash_live, "DAY_STATE", TMP / "day_taint.json"), \
            mock.patch.object(dash_live, "TAINT_STATE", TMP / "taint_taint.json"), \
            mock.patch.object(agent_office, "AUTO_CHECKIN", False), \
            mock.patch.object(agent_bus, "STATE", TMP / "bus_taint.json"), \
            mock.patch.object(agents_hub, "chat", fake_chat), \
            mock.patch.object(agents_history, "record", lambda *a, **k: None), \
            mock.patch.object(forge_ops, "paused", lambda: False):
        # control: the same write on a plain interactive chat collector runs by itself (AUTO tier)
        dash_live.begin()
        assert dash_live._write("api_post", tag, "solomon", dash_live._col()).get("done"), "AUTO in plain chat"
        dash_live.take()
        assert http == [("POST", "/api/daycare/ghl/tag")]
        del http[:]
        dash_live.TAINT_STATE.unlink(missing_ok=True)

        res = _post("/api/office/task", {"agentId": "solomon", "title": "x", "taskId": row["id"], "business": "daycare"})[1]
        assert res["ok"], res
        job = _wait_job(res["jobId"])
        assert http == [], "a Run now write must not run by itself: %s" % http
        assert "1 card(s) are waiting for your tap" in job["result"] and "Did:" not in job["result"], job["result"]
        queued = json.loads(ta.STATE.read_text())
        assert len(queued) == 1 and next(iter(queued.values()))["chat"] == "dash", "one dash card, durable"
        assert len(_get("/api/chat/cards")[1]["cards"]) == 1
        assert not dash_live.TAINT_STATE.exists() and not dash_live._recently_tainted("solomon"), \
            "the collector is tainted, not the agent on disk"


def test_double_tap_starts_one_job():
    agents_hub.TASKS = TMP / "hub_tasks_dbl.json"
    agent_office._JOBS.clear()
    gate = threading.Event()

    def slow_chat(aid, msg):
        gate.wait(5)
        return {"reply": "done", "agent": aid}

    with mock.patch.object(agent_office, "AUTO_CHECKIN", False), mock.patch.object(agent_bus, "STATE", TMP / "bus_dbl.json"):
        before = len(agents_hub.tasks()["tasks"])
        outs = []
        ts = [threading.Thread(target=lambda: outs.append(agent_office.dispatch("marcus", "Same job", "", slow_chat)))
              for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        gate.set()
        ok = [o for o in outs if o.get("ok")]
        assert len(ok) == 1 and sum("already on a task" in str(o.get("error")) for o in outs) == 5, outs
        assert len(agents_hub.tasks()["tasks"]) == before + 1, "a refused tap files no task row"
        assert ok[0]["taskId"] and agent_office.job(ok[0]["jobId"])["job"]["taskId"] == ok[0]["taskId"]
        _wait_job(ok[0]["jobId"])


def test_live_qa_fixes():
    d = (M / "m_biz_daycare.jsx").read_text()
    tabs = d[d.index("window.M_BIZ.daycare = {"):]
    assert tabs.count("label:") <= 5 and 'key: "crew", label: "Crew"' in tabs and "crew: MBDCrew" in tabs
    assert '<window.MAgentsPage business="daycare" />' in d and "Talk to Solomon" in d
    # Solomon on the daycare crew goes through the hub chat, like every other place he is offered
    a = (M / "m_agents.jsx").read_text()
    assert 'return { ep: "/api/hub/chat", business: portal };' in a[a.index("function MAChatTarget"):a.index("function MAState")]
    # the feed is not the scroller: the composer under the newest line is scrolled into view
    assert "composeRefMA.current.scrollIntoView" in a and 'ref={composeRefMA}' in a
    for dep in ("busyId", "thread.length", "local", "acts", "sendErr"):
        assert dep in a[a.index("scrollIntoView"):a.index("async function maSend")], dep
    # "N agents" counts what the chips show: archived agents are left out
    w = (M / "m_workspaces.jsx").read_text()
    assert ".filter((a)=>a && !a.archived).length} agents" in w
    # Run now sits on the open row itself, not inside the collapsed details
    t = (M / "m_tasks.jsx").read_text()
    assert t.index(">Run now</button>") < t.index("{open && (") and t.count(">Run now</button>") == 1
    css = (M / "mobile.css").read_text()
    assert ".mw-mark{min-width:44px;" in css and "min-width:42px" not in css


def test_run_now_button_set_matches_the_office():
    t = (M / "m_tasks.jsx").read_text()
    ids = re.search(r"const MT_RUNNABLE = \[([^\]]*)\]", t).group(1)
    ids = sorted(re.findall(r'"(\w+)"', ids))
    assert ids == sorted(set(agent_office.DEPT_OF) - set(agent_office.LANE_OF)), ids
    assert "canRun={MT_RUNNABLE.includes(t.agentId)}" in t and ">Run now</button>" in t
    assert '"/api/office/task"' in t and "taskId: t.id" in t and '"/api/office/jobs"' in t
    assert "setInterval" in t and "[anyRunning]" in t, "polls only while a run is live"
    assert "Filing a task only saves it" in t, "default stays file only"
    assert "dash_live.begin(tainted=True)" in (HERE / "connector.py").read_text()


# ── Mac tap + dropped connection ────────────────────────────────────────────────────────
def test_mac_tap_says_when_agentdrive_is_unmounted():
    card = {"agent": "marcus", "mac": {"command": "ls", "surface": "t"}}
    res = {"ran": True, "exitCode": 0, "timedOut": False, "truncated": False, "output": "a.txt"}
    for mounted, says in ((False, True), (True, False), (None, False)):
        with mock.patch.object(mac_link, "status", lambda m=mounted: {"driveMounted": m}), \
                mock.patch.object(mac_link, "run", lambda *a, **k: dict(res)), \
                mock.patch.object(dash_live, "_mark_tainted", lambda a: None):
            out = dash_live.mac_tap(card)
        assert out["ok"] and out["message"].endswith("a.txt")
        assert ("AgentDrive is not mounted so it ran from the home folder" in out["message"].splitlines()[0]) is says, (mounted, out)


def test_dropped_connection_on_a_mac_card_is_not_called_card_kept():
    src = (HERE / "chat_actions.jsx").read_text()
    assert "the command may have run: check the Mac before you retry" in src.replace("The command", "the command")
    assert 'st.retry ? (cmd ?' in src and "card kept, you can retry" in src, "other cards keep the old line"


def test_n8n_line_in_the_crew_header():
    a = (M / "m_agents.jsx").read_text()
    assert '"/api/system/n8n"' in a and "n8n.connected" in a and "runs this month" in a and "failed" in a
    assert "macM.refresh(); n8nM.refresh();" in a, "refreshed with the registry poll, no timer of its own"
    assert a.count("interval:") == 3 and a.count("setInterval") == 1


def main():
    failed = 0
    saved = (ta.STATE, agents_hub.TASKS)
    jobs0 = list(agent_office._JOBS)
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
