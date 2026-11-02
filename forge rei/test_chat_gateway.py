"""FORGE_CHAT_GATEWAY: dashboard, mobile and box Telegram turns run through agent_gateway.chat_local.

Real connector routes, real submit(), real agent_runner child process. Only Anthropic and the
loopback connector are local fakes, the same ones test_agent_gateway.py uses. No SMS, no live tap.

Run: python3 test_chat_gateway.py
"""
import contextlib
import io
import json
import os
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp(prefix="chat-gateway-test-"))
os.environ["FORGE_ACTION_LOG"] = str(TMP / "actions.jsonl")
os.environ.setdefault("FORGE_MARCUS", "0")
for _k in ("FORGE_CHAT_GATEWAY", "FORGE_CHAT_LIVE", "FORGE_CHAT_ACTIONS", "FORGE_CHAT_AUTO"):
    os.environ.pop(_k, None)

import test_agent_gateway as t  # noqa: E402  (env, fake model, fake connector, Telegram stubs)

import connector  # noqa: E402  (the real route handlers)
import agent_gateway as gw  # noqa: E402
import agency_agents  # noqa: E402
import agents_history  # noqa: E402
import agents_hub  # noqa: E402
import dash_live  # noqa: E402
import telegram_agent as ta  # noqa: E402
import telegram_io  # noqa: E402

agency_agents.STATE = TMP / "agency_agents.json"
telegram_io._api = lambda *a, **k: {"ok": True}
telegram_io._AGENT_CHAT["fn"] = telegram_io._AGENCY_CHAT["fn"] = lambda *a: "old text brain"   # never the network
TAP = "/api/daycare/blast/send"
AUTO = "/api/hub/task"
ON = {"FORGE_CHAT_GATEWAY": "1"}
OWNER = os.environ["FORGE_GATEWAY_OWNER_IDS"]


def _req(path, body):
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


def reset():
    deadline = time.time() + 15
    while gw._ACTIVE and time.time() < deadline:
        time.sleep(0.02)
    assert not gw._ACTIVE, "a job leaked from the last test"
    for f in gw.JOBS.glob("*.json") if gw.JOBS.is_dir() else ():
        f.unlink()
    agents_history.STATE.unlink(missing_ok=True)
    agency_agents.STATE.unlink(missing_ok=True)
    t.SENT.clear()
    t.CALLS["posts"].clear()
    t.MODEL["fn"] = lambda p: t.text("7 open")


def rows(agent="solomon"):
    return agents_history.history(agent)["history"]


def script(*steps):
    steps = list(steps)
    t.MODEL["fn"] = lambda p: steps.pop(0)


def old_hub(reply="from the old path"):
    return mock.patch.object(connector.agents_hub, "chat", lambda *a, **k: {"reply": reply, "agent": "Solomon"})


def active_job():
    for _ in range(200):
        for ctx in list(gw._ACTIVE.values()):
            if ctx.get("child"):
                return ctx
        time.sleep(0.02)
    raise AssertionError("no job started")


def test_flag_off_is_the_old_path():
    reset()
    before = t.CALLS["model"]
    with old_hub():
        code, res = _req("/api/hub/chat", {"agentId": "solomon", "message": "hi"})
    assert code == 200 and res == {"reply": "from the old path", "agent": "Solomon"}, res
    assert gw.chat_local("solomon", "hi", "dash") is None
    assert t.CALLS["model"] == before and not list(gw.JOBS.glob("*.json")), "the flag gates the job"
    assert [r["via"] for r in rows()] == ["dash", "dash"], "old path records as it always did"
    with mock.patch.object(ta, "chat", lambda *a, **k: {"reply": "old telegram", "cards": []}):
        telegram_io._partner_turn("chat-daycare", "solomon", "hi")
    assert "old telegram" in t.SENT[-1][1] and t.CALLS["model"] == before


def test_dash_turn_returns_cards_inline_and_the_tap_still_works():
    reset()
    ta.catalog().setdefault("POST", set()).update({TAP, AUTO})
    ta._CATALOG.setdefault("GET", set())
    script(t.tool("api_post", {"path": TAP, "body": {"to": "all"}, "summary": "Text all parents"}),
           t.text("Waiting on your tap."))
    with mock.patch.dict(os.environ, ON), old_hub("wrong path"):
        code, res = _req("/api/hub/chat", {"agentId": "solomon", "message": "text every parent",
                                           "business": "daycare"})
    assert code == 200 and res["reply"] == "Waiting on your tap.", res
    card = res["actions"][0]
    assert card["summary"] == "Text all parents" and card["tok"] and res["done"] == []
    assert not t.SENT, "a dashboard card never goes to Telegram"
    assert not t.CALLS["posts"], "nothing runs before the tap"
    assert ta._load()[card["tok"]]["chat"] == "dash", "bound to the dashboard's confirm route"
    assert dash_live._TL.__dict__.get("c") is None
    code, out = _req("/api/chat/action/confirm", {"tok": card["tok"]})
    assert code == 200 and out.get("ok"), out
    assert t.CALLS["posts"] == [TAP]
    assert rows()[-1]["text"].startswith("[owner tapped ✅]") and rows()[-1]["via"] == "dash"


def test_dash_auto_write_lands_as_a_done_line():
    reset()
    script(t.tool("api_post", {"path": AUTO, "body": {"agentId": "solomon", "title": "Call back"}, "summary": "Task"}),
           t.text("Filed."))
    with mock.patch.dict(os.environ, ON):
        code, res = _req("/api/hub/chat", {"agentId": "solomon", "message": "file a task"})
    assert code == 200 and [d["summary"] for d in res["done"]] == ["Task"] and res["actions"] == [], res
    assert t.CALLS["posts"] == [AUTO]


def test_quiet_turn_adds_no_empty_keys():
    reset()
    with mock.patch.dict(os.environ, ON):
        res = gw.chat_local("solomon", "how many open?", "dash")
    assert res["reply"] == "7 open" and not ({"actions", "done", "consults", "cards", "error"} & set(res)), res
    assert gw._load(res["job"])["receipts"]["cwd"].endswith("forge-solomon")


def test_telegram_turn_sends_the_card_to_the_business_chat_once():
    reset()
    script(t.tool("api_post", {"path": TAP, "body": {}, "summary": "Text all parents"}), t.text("Waiting on your tap."))
    with mock.patch.dict(os.environ, ON), mock.patch.object(ta, "chat", lambda *a, **k: 1 / 0):
        telegram_io._partner_turn("owner-dm", "solomon", "text every parent", from_id=OWNER)
    assert t.SENT[0][0] == "chat-daycare" and "pgo:" in str(t.SENT[0][2]), t.SENT
    assert t.SENT[1][0] == "owner-dm" and "Waiting on your tap." in t.SENT[1][1], t.SENT
    assert len(t.SENT) == 2, "the job sends the card; the turn must not send it again"
    tok = t.SENT[0][2][0][0]["callback_data"].split(":", 1)[1]
    assert ta._load()[tok]["chat"] == "chat-daycare", "the tap must be valid where the card is"
    assert [r["via"] for r in rows()] == ["telegram", "telegram"], rows()


def test_busy_gateway_falls_back_and_logs_it():
    reset()
    gate = threading.Event()
    done = []

    def stall(p):
        gate.wait(20)
        return t.text("first")
    t.MODEL["fn"] = stall
    with mock.patch.dict(os.environ, ON):
        first = threading.Thread(target=lambda: done.append(gw.chat_local("solomon", "one", "dash")))
        first.start()
        active_job()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), old_hub("old path answer"):
            code, res = _req("/api/hub/chat", {"agentId": "solomon", "message": "two"})
        assert code == 200 and res["reply"] == "old path answer", res
        assert "fell back" in out.getvalue() and "429" in out.getvalue(), out.getvalue()
        assert "two" not in out.getvalue().split(), "the log never holds the message"
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(ta, "chat", lambda *a, **k: {
                "reply": "old telegram", "cards": []}):
            telegram_io._partner_turn("chat-daycare", "solomon", "three", from_id=OWNER)
        assert "old telegram" in t.SENT[-1][1]
        gate.set()
        first.join(15)
    assert done[0]["reply"] == "first"
    texts = [r["text"] for r in rows() if r["role"] == "user"]
    assert sorted(texts) == ["one", "three", "two"], rows()


def test_a_failed_job_falls_back_before_anything_ran():
    reset()
    t.MODEL["fn"] = lambda p: t.text("")
    with mock.patch.dict(os.environ, ON), old_hub("old path answer"), contextlib.redirect_stdout(io.StringIO()):
        code, res = _req("/api/hub/chat", {"agentId": "solomon", "message": "hi"})
    assert res["reply"] == "old path answer", res
    assert [r["via"] for r in rows()] == ["dash", "dash"] and len(rows()) == 2, "a dead job records nothing"
    real = gw.submit
    gw.submit = lambda req: 1 / 0
    try:
        with mock.patch.dict(os.environ, ON), contextlib.redirect_stdout(io.StringIO()):
            assert gw.chat_local("solomon", "hi", "dash") is None, "chat_local itself never raises"
    finally:
        gw.submit = real


def test_a_job_that_wrote_something_never_replays():
    reset()
    script(t.tool("api_post", {"path": AUTO, "body": {"agentId": "solomon", "title": "x"}, "summary": "Task"}),
           t.text(""))
    with mock.patch.dict(os.environ, ON), old_hub("REPLAYED"):
        code, res = _req("/api/hub/chat", {"agentId": "solomon", "message": "file it"})
    assert res["reply"] != "REPLAYED" and res["error"] and "Task" in res["reply"], res
    assert [d["summary"] for d in res["done"]] == ["Task"] and t.CALLS["posts"] == [AUTO], res


def test_a_card_that_never_reached_telegram_says_so():
    reset()
    script(t.tool("api_post", {"path": TAP, "body": {}, "summary": "Text"}), t.text("Waiting on your tap."))
    real = telegram_io._send_to
    telegram_io._send_to = lambda chat, text, buttons=None, **k: (
        {"error": "send failed"} if buttons else t.SENT.append((chat, text, None)) or {"ok": True})
    try:
        with mock.patch.dict(os.environ, ON), mock.patch.object(ta, "chat", lambda *a, **k: 1 / 0):
            telegram_io._partner_turn("chat-daycare", "solomon", "text them", from_id=OWNER)
    finally:
        telegram_io._send_to = real
    assert "could not reach Telegram" in t.SENT[-1][1], t.SENT


def test_history_context_matches_the_old_path():
    reset()
    seen = {}

    def model(p):
        seen["msgs"] = p["messages"]
        return t.text("ok")
    t.MODEL["fn"] = model
    agents_history.record("solomon", "shared question", "shared answer", via="telegram")
    with mock.patch.dict(os.environ, ON):
        gw.chat_local("solomon", "next", "dash")
        assert "shared question" in json.dumps(seen["msgs"]), "no body history: the shared thread"
        _req("/api/hub/chat", {"agentId": "solomon", "message": "again",
                               "history": [{"role": "user", "text": "from the phone"}]})
    assert "from the phone" in json.dumps(seen["msgs"]) and "shared question" not in json.dumps(seen["msgs"])


def test_same_text_twice_is_two_jobs():
    reset()
    before = t.CALLS["model"]
    with mock.patch.dict(os.environ, ON):
        one = gw.chat_local("solomon", "same words", "dash")
        two = gw.chat_local("solomon", "same words", "dash")
    assert one["job"] != two["job"] and t.CALLS["model"] == before + 2
    assert [r["text"] for r in rows() if r["role"] == "user"] == ["same words", "same words"]


def test_wrong_workspace_refuses_first():
    reset()
    before = t.CALLS["model"]
    with mock.patch.dict(os.environ, ON):
        code, res = _req("/api/hub/chat", {"agentId": "solomon", "message": "hi", "business": "wholesale"})
    assert res.get("refused") and res.get("wrongWorkspace"), res
    assert t.CALLS["model"] == before and not rows(), "a refusal never lands in the thread"


def test_a_dashboard_chat_leaves_a_slot_for_n8n():
    reset()
    gate = threading.Event()

    def stall(p):
        gate.wait(20)
        return t.text("ok")
    t.MODEL["fn"] = stall
    with mock.patch.dict(os.environ, ON), contextlib.redirect_stdout(io.StringIO()):
        first = threading.Thread(target=lambda: gw.chat_local("solomon", "one", "dash"))
        first.start()
        active_job()
        assert gw.chat_local("dyson", "two", "dash") is None, "one local chat at a time"
        code, job = t.run("dyson.lead_review", "slot-1", {})
        assert code == 202, ("the free slot is n8n's", job)
        gate.set()
        first.join(15)
    reset()
    gate.clear()
    t.MODEL["fn"] = stall
    code, job = t.run("dyson.lead_review", "slot-2", {})
    assert code == 202
    active_job()
    with mock.patch.dict(os.environ, ON), contextlib.redirect_stdout(io.StringIO()):
        assert gw.chat_local("solomon", "busy box", "dash") is None
    gate.set()


def test_hourly_rate_limit_counts_local_chats():
    reset()
    for i in range(gw.MAX_AGENT_HOUR):
        gw._save({"id": f"sol-{i:032x}", "status": "done", "mode": "chat", "agent": "solomon"})
    out = io.StringIO()
    with mock.patch.dict(os.environ, ON), contextlib.redirect_stdout(out):
        assert gw.chat_local("solomon", "one more", "dash") is None
    assert "gateway rate limit" in out.getvalue()
    reset()
    with mock.patch.dict(os.environ, ON):
        gw.chat_local("solomon", "a real turn", "telegram")
    assert gw._recent("solomon", time.time())[0] == 1, "a local chat spends the same hourly budget"


def test_router_and_folder_receipts_apply():
    reset()
    seen = []

    def model(p):
        seen.append((p["model"], [x["name"] for x in p["tools"]]))
        return t.tool("escalate", {}) if len(seen) == 1 else t.text("Here is the plan")
    t.MODEL["fn"] = model
    with mock.patch.dict(os.environ, {**ON, "FORGE_CHAT_ROUTER": "1"}):
        res = gw.chat_local("solomon", "plan next week", "dash")
    assert res["reply"] == "Here is the plan"
    assert [s[0] for s in seen] == ["claude-haiku-5-5", "claude-sonnet-5-5"], seen
    assert "escalate" in seen[0][1] and "escalate" not in seen[1][1]
    receipts = gw._load(res["job"])["receipts"]
    assert receipts["escalated"] is True and receipts["model"] == "claude-sonnet-5-5"
    assert len(receipts["files"]) == len(gw.AGENTS["solomon"]["files"])
    assert all(len(f["sha256"]) == 64 for f in receipts["files"])


def test_prompt_names_the_real_surface():
    reset()
    seen = {}

    def model(p):
        seen["system"] = p["system"][0]["text"]
        return t.text("ok")
    t.MODEL["fn"] = model
    with mock.patch.dict(os.environ, ON):
        gw.chat_local("solomon", "hi", "dash")
        assert "OWNER CHAT ON THE DASHBOARD" in seen["system"] and "n8n chat page" not in seen["system"]
        assert "under your reply" in seen["system"]
        gw.chat_local("solomon", "hi", "telegram")
    assert "OWNER CHAT ON TELEGRAM" in seen["system"] and "n8n chat page" not in seen["system"]
    assert "business Telegram chat" in seen["system"]


def test_agency_route_keeps_its_own_thread():
    reset()
    with mock.patch.dict(os.environ, ON), mock.patch.object(connector.agency_agents, "chat", lambda *a, **k: 1 / 0):
        code, res = _req("/api/agency/agents/chat", {"agentId": "dyson", "message": "hi"})
    assert code == 200 and res["reply"] == "7 open", res
    assert [r["text"] for r in agency_agents.history("dyson")["history"]] == ["hi", "7 open"], \
        "the phone reads /api/agency/agents/history"
    assert [r["via"] for r in rows("dyson")] == ["dash", "dash"], rows("dyson")


def test_agents_the_gateway_cannot_run_stay_on_the_old_path():
    reset()
    with mock.patch.dict(os.environ, ON), old_hub("voice persona"), contextlib.redirect_stdout(io.StringIO()):
        assert _req("/api/hub/chat", {"agentId": "midas", "message": "hi"})[1]["reply"] == "voice persona"
        assert _req("/api/hub/chat", {"agentId": "retell-x", "message": "hi"})[1]["reply"] == "voice persona"
        assert gw.chat_local("solomon", "x" * 4001, "dash") is None
        assert gw.chat_local("solomon", "   ", "dash") is None


def test_chat_live_kill_switch_still_works():
    reset()
    before = t.CALLS["model"]
    with mock.patch.dict(os.environ, {**ON, "FORGE_CHAT_LIVE": "0"}):
        assert gw.chat_local("solomon", "hi", "dash") is None
    assert t.CALLS["model"] == before


def test_the_wait_ends_with_the_job():
    reset()
    gate = threading.Event()

    def stall(p):
        gate.wait(20)
        return t.text("too late")
    t.MODEL["fn"] = stall
    wall = gw.WALL_SECONDS
    gw.WALL_SECONDS = 1
    start = time.time()
    try:
        with mock.patch.dict(os.environ, ON), contextlib.redirect_stdout(io.StringIO()):
            assert gw.chat_local("solomon", "slow", "dash") is None
    finally:
        gw.WALL_SECONDS = wall
        gate.set()
    assert time.time() - start < 10
    assert not rows(), "a timed-out job records nothing; the old path owns the turn"


def test_the_n8n_door_is_unchanged():
    reset()
    code, job = t.api("POST", "/v1/chat", t.OWNER_KEY, {
        "agent": "solomon", "message": "hi", "sender_id": os.environ["FORGE_GATEWAY_OWNER_IDS"],
        "idempotency_key": "door-0001"})
    assert code == 202, job
    job = t.wait(job["id"], t.OWNER_KEY)
    assert job["status"] == "done"
    for _ in range(100):
        if rows():
            break
        time.sleep(0.05)
    assert rows()[-1]["via"] == "n8n", rows()


def job_files():
    return [json.loads(f.read_text()) for f in gw.JOBS.glob("*.json")]


def wait_idle():
    for _ in range(300):
        if not gw._ACTIVE:
            return
        time.sleep(0.02)
    raise AssertionError("the job never ended")


def test_owner_commands_stay_deterministic():
    reset()
    before = t.CALLS["model"]
    ran = []

    def command(agent, text, source="dashboard"):
        ran.append((agent, text))
        return {"reply": "Tagged in code.", "agent": agent, "command": "tag"}
    with mock.patch.dict(os.environ, ON), mock.patch.object(connector.telegram_ops, "handle_agent_command", command):
        for agent, said in (("marcus", "tag Pat Test as hot"), ("scout", "move Pat Test to under contract"),
                            ("atlas", "remove tag hot from Pat Test")):
            code, res = _req("/api/hub/chat", {"agentId": agent, "message": said})
            assert code == 200 and res["reply"] == "Tagged in code." and "job" not in res, (agent, res)
    assert [r[0] for r in ran] == ["marcus"] * 3, "the parser ran, in code (agents_hub resolves a lane first)"
    with mock.patch.dict(os.environ, ON), mock.patch.object(connector.telegram_ops, "_intent", lambda x: {
            "action": "move_stage", "contact": "Pat", "stage": "new"}), old_hub("the model read it as a move"):
        res = _req("/api/hub/chat", {"agentId": "marcus", "message": "shift Pat over to new"})[1]
    assert res["reply"] == "the model read it as a move", "same intent reader as the old path"
    with mock.patch.dict(os.environ, ON), mock.patch.object(connector.telegram_ops, "_intent", lambda x: None), \
            old_hub("the sweep ran"):
        res = _req("/api/hub/chat", {"agentId": "scout", "message": "go through my messages from last week"})[1]
    assert res["reply"] == "the sweep ran", "Scout's audit ask stays on the old path"
    assert t.CALLS["model"] == before and not job_files(), "no job for a command"

    with mock.patch.dict(os.environ, ON), mock.patch.object(connector.telegram_ops, "_intent", lambda x: None):
        res = _req("/api/hub/chat", {"agentId": "marcus", "message": "how many leads today?"})[1]
    assert res["reply"] == "7 open" and res["job"], "a plain question is still a gateway turn"
    with mock.patch.dict(os.environ, ON), mock.patch.object(
            connector.telegram_ops, "_intent", lambda x: {"action": "text", "contact": "Pat"}):
        res = _req("/api/hub/chat", {"agentId": "marcus", "message": "text Pat hello"})[1]
    assert res.get("job"), "only move_stage and tag are commands, as in handle_agent_command"
    with mock.patch.dict(os.environ, ON), mock.patch.object(connector.telegram_ops, "_command_intent", lambda x: 1 / 0):
        assert _req("/api/hub/chat", {"agentId": "solomon", "message": "hi"})[1]["job"], "other agents don't classify"

    with mock.patch.dict(os.environ, ON), mock.patch.object(connector.telegram_ops, "_command_intent",
                                                            lambda x: 1 / 0), old_hub("old path answer"):
        res = _req("/api/hub/chat", {"agentId": "marcus", "message": "hi"})[1]
    assert res["reply"] == "old path answer", "a broken classifier never kills the message"

    with mock.patch.object(connector.telegram_ops, "_command_intent", lambda x: 1 / 0), old_hub():
        assert _req("/api/hub/chat", {"agentId": "marcus", "message": "hi"})[0] == 200, "flag off spends nothing here"


def test_a_slow_spec_build_leaves_one_answer():
    """The wait starts at submit, WALL_SECONDS only after _build_spec. The child is alive when the wait
    ends and would answer at t=3.8, after the old path already did."""
    reset()
    start = time.time()
    build = gw._build_spec

    def slow(ctx):
        time.sleep(1)
        return build(ctx)

    def late(p):
        time.sleep(max(0, start + 3.8 - time.time()))
        return t.text("late reply")
    t.MODEL["fn"] = late
    gw._build_spec = slow
    wall, grace = gw.WALL_SECONDS, gw.STOP_GRACE
    gw.WALL_SECONDS, gw.STOP_GRACE = 3, 0
    try:
        with mock.patch.dict(os.environ, ON), old_hub("old path answer"), contextlib.redirect_stdout(io.StringIO()):
            res = _req("/api/hub/chat", {"agentId": "solomon", "message": "slow one"})[1]
        assert res["reply"] == "old path answer", res
        wait_idle()
        stopped = time.time() - start
        time.sleep(1)                      # past the moment the child would have answered
    finally:
        gw._build_spec = build
        gw.WALL_SECONDS, gw.STOP_GRACE = wall, grace
    assert stopped < 3.6, ("the child is stopped when the wait ends, not when it answers", stopped)
    assert [r["text"] for r in rows()] == ["slow one", "old path answer"], rows()
    job = job_files()[0]
    assert job["status"] == "failed" and job["reply"] == "" and "stopped waiting" in job["error"], job
    assert not gw._ACTIVE and not gw._TOKENS, "the slot and the token are free"


def test_a_spec_build_slower_than_the_wait_never_reaches_the_model():
    reset()
    before = t.CALLS["model"]
    build = gw._build_spec

    def slow(ctx):
        time.sleep(1.5)
        return build(ctx)
    gw._build_spec = slow
    wall, grace = gw.WALL_SECONDS, gw.STOP_GRACE
    gw.WALL_SECONDS, gw.STOP_GRACE = 1, 0
    try:
        with mock.patch.dict(os.environ, ON), contextlib.redirect_stdout(io.StringIO()):
            assert gw.chat_local("solomon", "stuck", "dash") is None
        wait_idle()
    finally:
        gw._build_spec = build
        gw.WALL_SECONDS, gw.STOP_GRACE = wall, grace
    assert t.CALLS["model"] == before, "no child, no model call"
    assert job_files()[0]["status"] == "failed" and not rows()


def test_a_timed_out_job_that_wrote_reports_and_never_replays():
    reset()
    build = gw._build_spec
    gate = threading.Event()
    steps = [t.tool("api_post", {"path": AUTO, "body": {"agentId": "solomon", "title": "x"}, "summary": "Task"})]

    def model(p):
        if steps:
            return steps.pop()
        gate.wait(20)
        return t.text("too late")

    def slow(ctx):
        time.sleep(1)
        return build(ctx)
    t.MODEL["fn"] = model
    gw._build_spec = slow
    wall, grace = gw.WALL_SECONDS, gw.STOP_GRACE
    gw.WALL_SECONDS, gw.STOP_GRACE = 3, 0
    try:
        with mock.patch.dict(os.environ, ON), old_hub("REPLAYED"):
            res = _req("/api/hub/chat", {"agentId": "solomon", "message": "file it"})[1]
        wait_idle()
    finally:
        gate.set()
        gw._build_spec = build
        gw.WALL_SECONDS, gw.STOP_GRACE = wall, grace
    assert res["reply"] != "REPLAYED" and "Task" in res["reply"] and res["error"], res
    assert [d["summary"] for d in res["done"]] == ["Task"] and t.CALLS["posts"] == [AUTO], res
    assert not rows(), "the abandoned job records nothing"


def test_the_waiter_never_stops_a_job_that_is_already_ending():
    child = mock.Mock()
    ctx = {"ended_by": "job", "finished": threading.Event(), "token": "x", "child": child}
    ctx["finished"].set()
    gw._give_up(ctx)
    child.kill.assert_not_called()


def test_only_the_owner_gets_the_gateway_on_telegram():
    reset()
    before = t.CALLS["model"]
    card = {"tok": "abc", "agent": "solomon", "path": TAP, "body": {}, "summary": "Text"}
    old = mock.patch.object(ta, "chat", lambda *a, **k: {"reply": "old telegram", "cards": [card]})
    with mock.patch.dict(os.environ, {**ON, "TELEGRAM_ALLOWED_IDS": f"{OWNER},555"}), old:
        telegram_io._partner_turn("team-chat", "solomon", "hi", from_id="555")
        telegram_io._partner_turn("team-chat", "solomon", "hi again")
    assert t.CALLS["model"] == before and not job_files(), "an allowlisted teammate never reaches AUTO"
    assert "pgo:abc" in str(t.SENT[-1][2]), "he stays on the old card path"
    assert [r["via"] for r in rows()] == ["telegram"] * 4

    reset()
    with mock.patch.dict(os.environ, {**ON, "FORGE_GATEWAY_OWNER_IDS": ""}), old:
        telegram_io._partner_turn("team-chat", "solomon", "hi", from_id=OWNER)
    assert not job_files(), "no owner set = nobody gets it"


def test_the_sender_reaches_the_turn_from_a_real_message():
    reset()
    telegram_io._AGENT_SESS.clear()
    telegram_io._AGENT_SESS["t-team"] = {"agent": "solomon", "history": []}

    def say(sender):
        t.SENT.clear()
        telegram_io._handle_message({"chat": {"id": "t-team", "type": "supergroup"}, "from": {"id": sender},
                                     "text": "how many open?"})
        for _ in range(500):
            if t.SENT:
                return t.SENT[-1][1]
            time.sleep(0.02)
        raise AssertionError("no reply")
    with mock.patch.dict(os.environ, {**ON, "TELEGRAM_ALLOWED_IDS": f"{OWNER},555"}), \
            mock.patch.object(ta, "chat", lambda *a, **k: {"reply": "old telegram", "cards": []}), \
            mock.patch("telegram_ops.route", return_value=False):
        assert "old telegram" in say("555")
        assert not job_files()
        assert "7 open" in say(OWNER)
        assert len(job_files()) == 1


def test_a_turn_over_real_http_through_the_real_connector():
    """No fakes but the model: the route blocks on the job while the child calls /api/gateway/tool on
    the same server, so a server that can't serve both at once would hang here."""
    reset()
    srv = connector.ThreadingHTTPServer(("127.0.0.1", 0), connector.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    ta.register(port, connector.ROUTES, connector.Handler, connector.__file__)
    seen = {}

    def model(p):
        last = p["messages"][-1]["content"]
        if isinstance(last, str):
            return t.tool("api_get", {"path": "/api/system/health"})
        if "api_post" not in seen:
            seen["api_post"], seen["read"] = True, last[0]["content"]
            return t.tool("api_post", {"path": TAP, "body": {}, "summary": "Text all parents"})
        return t.text("Waiting on your tap.")
    t.MODEL["fn"] = model

    def post(path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    try:
        with mock.patch.dict(os.environ, ON):
            res = post("/api/hub/chat", {"agentId": "solomon", "message": "health, then text them"})
        tools = gw._load(res["job"])["receipts"]["tools"]
        assert [x["name"] for x in tools] == ["api_get", "api_post"], tools
        assert "redLoops" in seen["read"], ("the real route answered the child", seen)
        card = res["actions"][0]
        assert card["path"] == TAP and ta._load()[card["tok"]]["chat"] == "dash", res
        assert post("/api/chat/action/cancel", {"tok": card["tok"]}).get("ok"), "the dashboard owns this card"
    finally:
        srv.shutdown()


if __name__ == "__main__":
    FAKE_MODEL, FAKE_CONNECTOR = t.serve(t.FakeModel), t.serve(t.FakeConnector)
    os.environ["FORGE_GATEWAY_ANTHROPIC_URL"] = f"http://127.0.0.1:{FAKE_MODEL}/v1/messages"
    ta._H["port"] = FAKE_CONNECTOR
    t.PORT = t.serve(gw.GatewayHandler)
    agents_hub._lanes_block = lambda a: ""
    agents_hub.open_tasks_block = lambda a: ""
    ta.catalog().setdefault("POST", set()).update({TAP, AUTO})
    ta._CATALOG.setdefault("GET", set())
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    order = sorted(tests, key=lambda f: f.__code__.co_firstlineno)
    failed = 0
    for fn in order:
        try:
            fn()
            print("ok  ", fn.__name__, flush=True)
        except Exception as e:  # noqa: BLE001 — show every RED at once
            failed += 1
            print("FAIL", fn.__name__, f"{type(e).__name__}: {str(e)[:300]}", flush=True)
    print(f"{len(order) - failed} of {len(order)} passed")
    raise SystemExit(1 if failed else 0)
