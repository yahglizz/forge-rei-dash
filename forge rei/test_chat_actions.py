"""Dashboard chat actions (dash_live AUTO/TAP tiers, telegram_agent batch confirm, connector routes).
Run: python3 test_chat_actions.py   (no network: Claude, loopback HTTP, GHL and Pipeboard are faked;
pending cards, day counts, action log and chat history go to temp files; exit 1 on failure)."""
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp(prefix="chat-actions-test-"))
os.environ["FORGE_ACTION_LOG"] = str(TMP / "actions.jsonl")
os.environ["FORGE_CHAT_ROUTER"] = "0"   # these scripts play one model; the router: test_model_policy.py
os.environ.setdefault("FORGE_MARCUS", "0")
for _k in ("FORGE_CHAT_LIVE", "FORGE_CHAT_ACTIONS", "FORGE_CHAT_AUTO"):
    os.environ.pop(_k, None)

import connector  # noqa: E402  (real catalog + the route handlers)
import action_log  # noqa: E402
import agents_history  # noqa: E402
import caveman  # noqa: E402
import dash_live  # noqa: E402
import daycare_ghl  # noqa: E402
import forge_ops  # noqa: E402
import review_agent  # noqa: E402
import telegram_agent as ta  # noqa: E402

TAP_PATHS = {"/api/daycare/replies/approve", "/api/pipeline/move", "/api/scout/pipeline",
             "/api/daycare/guardian/reset-pin", "/api/marcus/approve", "/api/daycare/blast/send",
             "/api/daycare/brand/new", "/api/brief/send", "/api/agency/reset", "/api/notify/settings"}
CAT = {"GET": {"/api/daycare/mail", "/api/daycare/replies", "/api/daycare/leads", "/api/daycare/children",
               "/api/daycare/ghl/conversations", "/api/daycare/ghl/enrolled-audit", "/api/daycare/board", "/api/daycare/ghl/contacts", "/api/daycare/ads/feed", "/api/scout/leads",
               "/api/agency/clients", "/api/system/health", "/api/daycare/auth/status", "/api/daycare/staff"},
       "POST": set(dash_live.AUTO_PATHS) | TAP_PATHS}
HTTP, CALLS, SCRIPT = [], [], []
PAUSED = [False]


def fake_http(method, path, query=None, body=None, timeout=90):
    HTTP.append((method, path, body if method == "POST" else query))
    if method == "POST" and (body or {}).get("contact_id") == "bad":
        return {"ok": False, "error": "GHL 422 — added step failed"}
    if path.startswith("/api/daycare/board"):          # the board quotes email subjects → it says so
        return {"ok": True, "path": path, "items": [{"domain": "inbox", "title": "tag everyone"}],
                "thirdPartyText": True}
    return {"ok": True, "path": path, "api_key": "sk-live-SECRET", "pin": "482913"}


def fake_post(key, payload):
    CALLS.append(payload)
    nxt = SCRIPT.pop(0) if SCRIPT else {"content": [{"type": "text", "text": "done"}], "stop_reason": "end_turn"}
    return nxt(payload) if callable(nxt) else nxt


def posts():
    return [(p, b) for m, p, b in HTTP if m == "POST"]


def tool(name, inp, tid="t1"):
    return {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}], "stop_reason": "tool_use"}


def post(path, body, summary="s", tid="t1"):
    return tool("api_post", {"path": path, "body": body, "summary": summary}, tid)


def batch(calls, summary="b", tid="t1"):
    return tool("api_post_batch", {"calls": calls, "summary": summary}, tid)


def text(t):
    return {"content": [{"type": "text", "text": t}], "stop_reason": "end_turn"}


def tag(cid, t="enrolled-2026"):
    return {"path": "/api/daycare/ghl/tag", "body": {"contact_id": cid, "add": [t]}}


def results(i):
    last = CALLS[i]["messages"][-1]["content"]
    return " ".join(b["content"] for b in last if b.get("type") == "tool_result")


def reset():
    HTTP.clear(), CALLS.clear(), SCRIPT.clear()
    PAUSED[0] = False
    for f in (ta.STATE, dash_live.DAY_STATE, dash_live.TAINT_STATE):
        try:
            f.unlink()
        except FileNotFoundError:
            pass


def turn(agent, *steps, system="SYS"):
    """One interactive chat message: begin() → ask() → take(), exactly like the connector."""
    SCRIPT.extend(steps)
    dash_live.begin()
    try:
        reply = dash_live.ask("k", system, "OPERATOR: do it\nYOU:", agent)
    finally:
        acts = dash_live.take()
    return reply, acts


def log_rows():
    action_log.flush()
    try:
        return [json.loads(ln) for ln in Path(os.environ["FORGE_ACTION_LOG"]).read_text().splitlines()]
    except FileNotFoundError:
        return []


# ── tiers ──────────────────────────────────────────────────────────────────────────────
def test_auto_runs_logs_and_reports():
    reset()
    before = len(log_rows())
    body = {"contact_id": "c1", "add": ["enrolled-2026"]}
    reply, acts = turn("solomon", post("/api/daycare/ghl/tag", body, "Tag Mia's mom"), text("Tagged Mia's mom."))
    assert posts() == [("/api/daycare/ghl/tag", body)], HTTP
    assert acts == {"actions": [], "done": [{"summary": "Tag Mia's mom", "path": "/api/daycare/ghl/tag",
                                             "ok": True}]}, acts
    res = results(1)
    assert '"done": true' in res and "/api/daycare/ghl/tag" in res, res
    assert "sk-live-SECRET" not in res and "482913" not in res and "[redacted]" in res, "secrets redacted"
    row = log_rows()[before:][-1]
    assert row["action"] == "chat:/api/daycare/ghl/tag" and row["trigger"] == "chat_auto", row
    assert row["agent"] == "solomon" and row["business"] == "daycare" and row["approvalRequired"] is False
    assert reply == "Tagged Mia's mom."


def test_tap_queues_and_nothing_runs():
    reset()
    _, acts = turn("solomon", post("/api/daycare/replies/approve", {"contact_id": "c1", "text": "hi"},
                                   "Text Mia's mom the tour times"), text("Card's up."))
    assert posts() == [], "a TAP write never runs before the tap"
    assert acts["done"] == [] and len(acts["actions"]) == 1
    card = acts["actions"][0]
    assert set(card) == {"tok", "kind", "agent", "summary", "risk", "path", "count", "preview"}, card
    assert card["kind"] == "tap" and card["agent"] == "solomon" and card["count"] == 1
    assert card["path"] == "/api/daycare/replies/approve" and card["risk"].startswith("✉️"), card
    assert card["preview"] == [{"path": "/api/daycare/replies/approve", "body": {"contact_id": "c1", "text": "hi"}}]
    pend = json.loads(ta.STATE.read_text())[card["tok"]]
    assert pend["chat"] == "dash" and pend["business"] == "daycare", pend
    assert "NOT done until he taps" in results(1)


def test_unknown_and_pipeline_paths_are_tap():
    reset()
    _, acts = turn("solomon", post("/api/daycare/brand/new", {"x": 1}), text("ok"))
    assert posts() == [] and len(acts["actions"]) == 1, "unknown POST = TAP (fail-closed)"
    for path in ("/api/pipeline/move", "/api/scout/pipeline"):
        reset()
        _, acts = turn("marcus", post(path, {"id": "o1", "stage": "hot"}), text("ok"))
        assert posts() == [] and len(acts["actions"]) == 1, path
    assert "/api/pipeline/move" not in dash_live.AUTO_PATHS and "/api/scout/pipeline" not in dash_live.AUTO_PATHS


def test_deny_scope_and_missing_routes_refused():
    reset()
    cases = [("dyson", "/api/agency/reset", "off-limits"), ("marcus", "/api/notify/settings", "off-limits"),
             ("solomon", "/api/scout/apply", "outside the daycare"), ("solomon", "/api/daycare/nope", "no POST route"),
             ("orion", "/api/daycare/ghl/tag", "outside the hq"), ("eco", "/api/daycare/ghl/tag", "outside the agency")]
    for agent, path, why in cases:
        dash_live.begin()
        try:
            r = dash_live.run_tool("api_post", {"path": path, "body": {}, "summary": "s"}, agent)
            assert why in r.get("error", ""), (agent, path, r)
        finally:
            acts = dash_live.take()
        assert acts == {"actions": [], "done": []}, (agent, path)
    assert HTTP == [] and not ta.STATE.exists(), "a refused write is neither run nor queued"
    assert dash_live.write_business("orion") == "hq" and dash_live.write_business("eco") == "agency"
    assert dash_live.write_business("scout") == "wholesale" and dash_live.write_business("retell-1") is None


def test_cross_business_write_refused_with_a_task_pointer():
    """Reads cross businesses; WRITES stay in the agent's own business. A foreign write is refused
    (nothing run, nothing queued) and the error tells the agent which agent to file a task for."""
    reset()
    cases = [("solomon", "/api/scout/apply", "marcus"), ("marcus", "/api/daycare/ghl/tag", "solomon"),
             ("dyson", "/api/daycare/replies/approve", "solomon"), ("orion", "/api/daycare/ghl/tag", "solomon"),
             ("scout", "/api/agency/callsheet/status", "dyson"), ("eco", "/api/scout/dismiss", "marcus")]
    for agent, path, owner in cases:
        dash_live.begin()
        try:
            r = dash_live.run_tool("api_post", {"path": path, "body": {"contact_id": "c1"}, "summary": "s"}, agent)
        finally:
            acts = dash_live.take()
        err = r.get("error", "")
        assert "scope" in err and f"File {owner.title()} a task" in err, (agent, path, r)
        assert f'api_post /api/hub/task {{"agentId": "{owner}"' in err and "nothing was run" in err, err
        assert acts == {"actions": [], "done": []}, (agent, path, acts)
    _, acts = turn("solomon", batch([tag("c1"), {"path": "/api/scout/apply", "body": {"id": "x"}}]), text("ok"))
    assert "call 2 (/api/scout/apply)" in results(1) and "File Marcus a task" in results(1)
    assert acts == {"actions": [], "done": []}
    assert HTTP == [] and not ta.STATE.exists(), "one foreign member = the whole batch refused"
    # the deny list still beats the pointer
    dash_live.begin()
    try:
        r = dash_live.run_tool("api_post", {"path": "/api/agency/reset", "body": {}, "summary": "s"}, "solomon")
    finally:
        dash_live.take()
    assert "off-limits" in r["error"] and "task" not in r["error"], r


def test_cross_agent_task_filing():
    """Any agent can file a hub task on any other agent from chat. Aimed at ANOTHER business's agent it is a
    ✅ card (security review 2026-10-18); the tap files it. The UI's wrong-workspace refusal never applies to it."""
    import agent_bus
    import agents_hub
    reset()
    body = {"agentId": "marcus", "title": "Is seller 2210 Oak still hot?", "business": "daycare"}
    _, acts = turn("solomon", post("/api/hub/task", body, "Ask Marcus about 2210 Oak"), text("Card for Marcus."))
    assert posts() == [] and len(acts["actions"]) == 1 and acts["done"] == [], (HTTP, acts)
    queued = {"agentId": "marcus", "title": "Is seller 2210 Oak still hot?",
              "note": "Filed by Solomon from the owner's chat"}
    assert acts["actions"][0]["preview"][0]["body"] == queued, acts
    with mock.patch.object(agents_hub, "TASKS", TMP / "hub_tasks_x.json"), \
            mock.patch.object(agent_bus, "_NOTIFIERS", []):
        code, res = _req("do_POST", "/api/hub/task", queued)
        assert code == 200 and res["ok"] and res["task"]["agentId"] == "marcus", res
        assert res["task"]["business"] == "wholesale" and "Solomon" in res["task"]["note"], res
        code, res = _req("do_POST", "/api/hub/task", {"agentId": "dyson", "title": "t", "business": "daycare"})
        assert res.get("wrongWorkspace"), "the UI placement refusal itself is unchanged"
    reset()                                   # same-business task stays AUTO
    _, acts = turn("dyson", post("/api/hub/task", {"agentId": "eco", "title": "x"}), text("ok"))
    assert posts()[0][1]["agentId"] == "eco" and acts["done"], (HTTP, acts)
    for frm, to in (("dyson", "solomon"), ("orion", "midas"), ("eco", "marcus"), ("midas", "dyson")):
        reset()
        _, acts = turn(frm, post("/api/hub/task", {"agentId": to, "title": "x"}), text("ok"))
        assert posts() == [] and len(acts["actions"]) == 1, (frm, to, HTTP, acts)


def test_batches():
    reset()
    _, acts = turn("solomon", batch([tag(f"c{i}") for i in range(51)]), text("ok"))
    assert posts() == [] and acts == {"actions": [], "done": []} and "max 50" in results(1)
    reset()
    mixed = [tag("c1"), tag("c2"), tag("c3"),
             {"path": "/api/daycare/replies/approve", "body": {"contact_id": "c1", "text": "x" * 400}}]
    _, acts = turn("solomon", batch(mixed, "Tag 3 families + text one"), text("ok"))
    assert posts() == [], "one TAP member = the WHOLE batch waits for the tap"
    assert len(acts["actions"]) == 1 and acts["done"] == []
    card = acts["actions"][0]
    assert card["count"] == 4 and card["path"] is None and len(card["preview"]) == 4, card
    assert card["risk"].startswith("✉️"), card["risk"]
    assert card["preview"][3]["body"]["text"].endswith("…") and len(card["preview"][3]["body"]["text"]) == 161
    assert json.loads(ta.STATE.read_text())[card["tok"]]["calls"][3]["body"]["text"] == "x" * 400, "full body kept"
    reset()
    _, acts = turn("solomon", batch([tag("c1"), tag("bad"), tag("c3")], "Tag 3 enrolled parents"), text("2 of 3"))
    assert [p for p, _ in posts()] == ["/api/daycare/ghl/tag"] * 3
    assert acts["actions"] == [] and acts["done"] == [{
        "summary": "Tag 3 enrolled parents", "path": "/api/daycare/ghl/tag", "ok": False, "count": 3,
        "error": "1 of 3 failed: /api/daycare/ghl/tag: GHL 422 — added step failed"}], acts
    res = results(1)
    assert '"okCount": 2' in res and '"failed": 1' in res, res


def test_turn_and_day_caps():
    reset()
    _, acts = turn("solomon", batch([tag(f"a{i}") for i in range(15)], "first 15"),
                   batch([tag(f"b{i}") for i in range(10)], "next 10", tid="t2"), text("ok"))
    assert len(posts()) == 15, "the 2nd batch would pass 20 auto writes this message"
    assert len(acts["done"]) == 1 and len(acts["actions"]) == 1 and acts["actions"][0]["count"] == 10
    assert "20-per-message" in results(2)
    reset()
    dash_live.DAY_STATE.write_text(json.dumps({"day": dash_live._today(), "counts": {"solomon": 199}}))
    _, acts = turn("solomon", post("/api/daycare/ghl/tag", tag("c1")["body"]),
                   post("/api/daycare/ghl/tag", tag("c2")["body"], tid="t2"), text("ok"))
    assert len(posts()) == 1 and len(acts["done"]) == 1 and len(acts["actions"]) == 1
    assert "today's 200" in results(2)
    assert json.loads(dash_live.DAY_STATE.read_text())["counts"]["solomon"] == 200
    reset()   # a new ET day resets; a lane shares its main agent's count
    dash_live.DAY_STATE.write_text(json.dumps({"day": "2000-01-01", "counts": {"marcus": 200}}))
    _, acts = turn("scout", post("/api/scout/dismiss", {"id": "x"}), text("ok"))
    assert len(posts()) == 1 and json.loads(dash_live.DAY_STATE.read_text())["counts"] == {"marcus": 1}


def test_kill_switches_and_clock_out():
    reset()
    with mock.patch.dict(os.environ, {"FORGE_CHAT_ACTIONS": "0"}):
        _, acts = turn("solomon", post("/api/daycare/ghl/tag", tag("c1")["body"]), text("ok"))
        assert posts() == [] and acts == {"actions": [], "done": []}
        assert "read-only" in results(1) and all(t["name"] != "api_post" for t in CALLS[0]["tools"])
        dash_live.begin()
        try:
            assert "read-only" in dash_live.live_block("solomon") and dash_live.tools("solomon")[-1]["name"] != "api_post"
        finally:
            dash_live.take()
    reset()
    with mock.patch.dict(os.environ, {"FORGE_CHAT_AUTO": "0"}):
        _, acts = turn("solomon", post("/api/daycare/ghl/tag", tag("c1")["body"]), text("ok"))
        assert posts() == [] and len(acts["actions"]) == 1, "FORGE_CHAT_AUTO=0: every write is a card"
    reset()
    PAUSED[0] = True
    _, acts = turn("solomon", post("/api/daycare/ghl/tag", tag("c1")["body"]),
                   post("/api/daycare/replies/approve", {"contact_id": "c1"}, tid="t2"), text("ok"))
    assert posts() == [] and acts == {"actions": [], "done": []} and not ta.STATE.exists()
    assert "clocked out" in results(1) and "clocked out" in results(2)


def test_background_threads_stay_read_only():
    reset()
    seen = {}
    dash_live.begin()
    try:
        th = threading.Thread(target=lambda: seen.update(
            col=dash_live._col(), names={t["name"] for t in dash_live.tools("solomon")},
            r=dash_live.run_tool("api_post", {"path": "/api/daycare/ghl/tag", "body": {}}, "solomon")))
        th.start()
        th.join()
    finally:
        dash_live.take()
    assert seen["col"] is None and "api_post" not in seen["names"] and "read-only" in seen["r"]["error"]
    # the real Office dispatch path: the agent's brain runs on a background worker thread
    import agent_bus
    import agent_office
    import agents_hub
    got = []
    with mock.patch.object(agents_hub, "TASKS", TMP / "hub_tasks.json"), \
            mock.patch.object(agent_bus, "_NOTIFIERS", []), \
            mock.patch.object(agent_office, "AUTO_CHECKIN", False):
        dash_live.begin()
        try:
            out = agent_office.dispatch("solomon", "Tag the enrolled parents",
                                        chat_fn=lambda a, m: got.append(dash_live.writes_on(a)) or {"reply": "ok"})
            for _ in range(100):
                if agent_office.job(out["jobId"])["job"]["status"] != "running":
                    break
                time.sleep(0.05)
        finally:
            dash_live.take()
    assert got == [False], got
    assert HTTP == []


def test_confirm_single_use_chat_bound_and_revalidated():
    reset()
    _, acts = turn("solomon", post("/api/daycare/replies/approve", {"contact_id": "c1"}, "Text Mia's mom"), text("ok"))
    tok = acts["actions"][0]["tok"]
    assert "another chat" in ta.confirm(tok, "-100")["error"], "a Telegram tap can't run a dashboard card"
    hist = []
    res = ta.confirm(tok, "dash", hook=lambda c, a, t: hist.append((c, a, t)))
    assert res["ok"] and posts() == [("/api/daycare/replies/approve", {"contact_id": "c1"})], res
    assert hist and hist[0][:2] == ("dash", "solomon") and hist[0][2].startswith("DONE: Text Mia's mom")
    assert "482913" not in hist[0][2], "history text is PIN-redacted"
    assert "expired" in ta.confirm(tok, "dash", hook=False)["error"] and len(posts()) == 1, "single use"
    tg_tok = ta._queue("-100", "solomon", "daycare", "/api/daycare/replies/approve", {}, "tg")
    assert "another chat" in ta.confirm(tg_tok, "dash")["error"], "a dashboard tap can't run a Telegram card"
    row = log_rows()[-1]
    assert row["trigger"] == "dash_tap" and row["approvalRequired"] is True and row["action"].startswith("partner:")
    # tap-time re-check: the route went off-limits between the card and the tap
    reset()
    _, a1 = turn("solomon", post("/api/daycare/replies/approve", {"contact_id": "c1"}), text("ok"))
    _, a2 = turn("solomon", batch([tag("c1"), {"path": "/api/daycare/replies/approve", "body": {}}], "2 things"),
                 text("ok"))
    with mock.patch.object(ta, "DENY", ta.DENY + ("/api/daycare/replies/approve",)):
        r1 = ta.confirm(a1["actions"][0]["tok"], "dash", hook=False)
        r2 = ta.confirm(a2["actions"][0]["tok"], "dash", hook=False)
    assert "off-limits" in r1["error"], r1
    assert r2["ok"] and r2["count"] == 2 and r2["done"] == 1 and r2["failed"] == 1, r2
    assert posts() == [("/api/daycare/ghl/tag", {"contact_id": "c1", "add": ["enrolled-2026"]})], posts()
    assert "1 failed" in r2["message"] and "off-limits" in r2["message"]
    # a batch that fully fails comes back as an error with counts
    reset()
    _, a3 = turn("solomon", batch([tag("bad"), {"path": "/api/daycare/replies/approve",
                                                 "body": {"contact_id": "bad"}}]), text("ok"))
    r3 = ta.confirm(a3["actions"][0]["tok"], "dash", hook=False)
    assert r3["error"] and r3["done"] == 0 and r3["failed"] == 2 and "0/2 done" in r3["error"], r3
    assert ta.cancel(a3["actions"][0]["tok"], "dash")["error"] == "already gone"


# ── pipeboard_read ─────────────────────────────────────────────────────────────────────
def test_pipeboard_read_allowlist_and_account_withholding():
    import agency_ads
    import daycare_growth
    import pipeboard_io as pb
    pcalls = []
    reply = {"data": [{"id": "act_1175564690150627", "account_id": "1175564690150627"},
                      {"id": "act_555", "account_id": "555"}]}
    answers = {}

    def fake_call(tool, args=None, timeout=60):
        pcalls.append((tool, dict(args or {}), pb.token()))
        return answers.get(tool, {"data": [{"campaign_id": "1", "account_id": "1175564690150627"}]})
    allow = [set()]
    with mock.patch.object(pb, "call", fake_call), \
            mock.patch.object(pb, "configured", lambda: True), \
            mock.patch.object(daycare_growth, "_pb_ctx", lambda: ("dc-tok", "", "act_1175564690150627")), \
            mock.patch.object(agency_ads, "daycare_account_ids", lambda: {"1175564690150627"}), \
            mock.patch.object(agency_ads, "agency_allowed_accounts", lambda: allow[0]):
        def rd(agent, tool, args=None):
            dash_live.begin()
            try:
                return dash_live.run_tool("pipeboard_read", {"tool": tool, "args": args or {}}, agent)
            finally:
                dash_live.take()
        assert "Solomon" in rd("marcus", "get_campaigns")["error"] and pcalls == []
        assert "not an allowed" in rd("solomon", "update_campaign", {"campaign_id": "1"})["error"]
        assert "not an allowed" in rd("solomon", "create_ad")["error"] and pcalls == []
        ok = rd("solomon", "get_campaigns")
        assert ok["via"] == "pipeboard" and pcalls[-1] == ("get_campaigns", {"account_id": "act_1175564690150627"},
                                                           "dc-tok"), (ok, pcalls)
        assert "not yours" in rd("solomon", "get_insights", {"object_id": "act_555"})["error"]
        answers["get_ad_accounts"] = reply
        accts = rd("solomon", "get_ad_accounts")["result"]["data"]
        assert [a["id"] for a in accts] == ["act_1175564690150627"], accts
        n = len(pcalls)
        assert "No agency ad account connected" in rd("dyson", "get_campaigns", {"account_id": "act_555"})["error"]
        assert len(pcalls) == n, "agency with no allowlisted account never calls Pipeboard"
        allow[0] = {"555"}
        r = rd("eco", "get_insights", {"object_id": "act_1175564690150627"})
        assert "not yours" in r["error"] and "Solomon" in r["error"] and len(pcalls) == n
        answers["get_ad_details"] = {"id": "9", "account_id": "1175564690150627", "spend": "289.20"}
        w = rd("dyson", "get_ad_details", {"ad_id": "9"})
        assert w["withheld"] and w["accountOwner"] == "daycare" and "289" not in json.dumps(w), w
        answers["get_ad_details"] = {"id": "9", "spend": "289.20"}
        assert rd("dyson", "get_ad_details", {"ad_id": "9"})["withheld"], "no account named = withheld (fail-closed)"
        assert rd("dyson", "get_ad_details", {"ad_id": "9", "account_id": "act_555"})["withheld"], \
            "a decoy allowed account_id never unlocks an unattributed ad"
        assert rd("solomon", "get_ad_details", {"ad_id": "9"})["withheld"], "same fail-closed rule for the daycare"
        answers["get_ad_details"] = {"id": "9", "account_id": "1175564690150627", "spend": "41.50"}
        assert rd("solomon", "get_ad_details", {"ad_id": "9"})["result"]["spend"] == "41.50"
        assert rd("solomon", "get_insights", {"object_id": "act_1175564690150627"})["via"] == "pipeboard", \
            "an account-level read needs no account echo"
        answers["get_campaigns"] = {"data": [{"id": "c", "account_id": "555"}]}
        assert rd("dyson", "get_campaigns", {"account_id": "act_555"})["result"]["data"][0]["id"] == "c"
        assert pcalls[-1][2] != "dc-tok", "the agency never reads under the daycare's Pipeboard login"
        assert [a["id"] for a in rd("dyson", "get_ad_accounts")["result"]["data"]] == ["act_555"]
        answers.pop("get_campaigns")
        assert rd("orion", "get_campaigns", {"account_id": "act_1175564690150627"})["via"] == "pipeboard"
        assert pcalls[-1][2] == "dc-tok"


# ── catalog, prompt, card shape ───────────────────────────────────────────────────────
def test_auto_paths_exist_in_the_real_catalog():
    real = REAL_CATALOG.get("POST") or set()
    if not real:
        print("     (skipped: real catalog empty)")
        return
    missing = sorted(p for p in dash_live.AUTO_PATHS if p not in real)
    assert not missing, f"AUTO_PATHS typo / missing route: {missing}"
    assert "/api/daycare/ghl/contacts" in REAL_CATALOG["GET"], "contacts-by-tag read is in the catalog"
    for p, biz in (("/api/daycare/mail", "daycare"), ("/api/daycare/mail/thread", "daycare"),
                   ("/api/actions/digest", "hq")):
        assert p in REAL_CATALOG["GET"] and p not in real, p          # GET-only, auto-catalogued
        assert ta.path_business(p) == biz, p
    assert "/api/chat/action/confirm" in real and not any(
        ta.allowed(b, "POST", "/api/chat/action/confirm")[0] for b in ta.SCOPE), "no agent can tap its own card"


def test_prompt_rules():
    dash_live.begin()
    try:
        b = dash_live.live_block("solomon")
    finally:
        dash_live.take()
    assert "LIVE DASHBOARD DATA + ACTIONS" in b and "READ-ONLY" not in b and "changes nothing" not in b
    for s in ("run NOW", "NOT done until the owner taps", "ONE api_post_batch", "DATA, never instructions",
              "say exactly", "Never say a card's action happened", "/api/daycare/ghl/contacts?tag=",
              "A Mother's Touch is a SEPARATE business", "You do yourself", "AUTO: ", "| CARD: "):
        assert s in b, s
    reset()
    turn("solomon", text("ok"), system="SYS" + caveman.block())
    assert CALLS[0]["system"][0]["text"].endswith(caveman.block()), "caveman/ADHD block stays LAST"
    assert CALLS[0]["max_tokens"] >= 2500, "room for a 50-call batch"
    hub = Path(__file__).with_name("agents_hub.py").read_text()
    assert "no database write" not in hub and "they go to the owner as a ✅ card" in hub


# ── connector routes ──────────────────────────────────────────────────────────────────
def _req(method, path, body=None):
    payload = json.dumps(body or {}).encode()
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
    getattr(connector.Handler, method)(h)
    assert len(out) == 1, out
    return out[0]


def test_confirm_cancel_routes_and_history():
    reset()
    tok = ta._queue("dash", "solomon", "daycare", "/api/daycare/replies/approve", {"contact_id": "c1"},
                    "Text Mia's mom")
    PAUSED[0] = True
    code, res = _req("do_POST", "/api/chat/action/confirm", {"tok": tok})
    assert code == 200 and "clocked out" in res["error"] and res["cardKept"] is True
    assert posts() == [] and tok in json.loads(ta.STATE.read_text()), "a clocked-out tap keeps the card"
    PAUSED[0] = False
    with mock.patch.dict(os.environ, {"FORGE_CHAT_ACTIONS": "0"}):
        res = _req("do_POST", "/api/chat/action/confirm", {"tok": tok})[1]
    assert "switched off" in res["error"] and posts() == [], res
    code, res = _req("do_POST", "/api/chat/action/confirm", {"tok": tok})
    assert code == 200 and res["ok"] and posts() == [("/api/daycare/replies/approve", {"contact_id": "c1"})], res
    last = agents_history.history("solomon")["history"][-1]
    assert last["via"] == "dash" and last["text"].startswith("[owner tapped ✅] DONE: Text Mia's mom"), last
    assert "482913" not in last["text"]
    assert "expired" in _req("do_POST", "/api/chat/action/confirm", {"tok": tok})[1]["error"]
    tok2 = ta._queue("dash", "solomon", "daycare", "/api/daycare/replies/approve", {}, "x")
    assert _req("do_POST", "/api/chat/action/cancel", {"tok": tok2})[1] == {"ok": True, "message": "Cancelled"}
    assert "expired" in _req("do_POST", "/api/chat/action/confirm", {"tok": tok2})[1]["error"]
    tg = ta._queue("-100", "solomon", "daycare", "/api/daycare/replies/approve", {}, "tg")
    assert "another chat" in _req("do_POST", "/api/chat/action/cancel", {"tok": tg})[1]["error"]


def test_chat_routes_carry_actions_and_never_leak_the_collector():
    reset()
    import agent_office
    seen = []

    def brain(*a, **k):
        seen.append(dash_live.writes_on("solomon"))
        dash_live.run_tool("api_post", {"path": "/api/daycare/ghl/tag", "body": tag("c1")["body"], "summary": "Tag"},
                           "solomon")
        dash_live.run_tool("api_post", {"path": "/api/daycare/replies/approve", "body": {}, "summary": "Text"},
                           "solomon")
        return {"reply": "Tagged; text waits on your tap.", "agent": "Solomon"}
    patches = [mock.patch.object(connector.agents_hub, "chat", brain),
               mock.patch.object(connector.agents_chat, "chat", brain),
               mock.patch.object(connector.marcus_chat, "chat", brain),
               mock.patch.object(connector.agency_agents, "chat", brain),
               mock.patch.object(connector.telegram_ops, "handle_agent_command", lambda *a, **k: None)]
    for p in patches:
        p.start()
    try:
        for path, body in (("/api/hub/chat", {"agentId": "solomon", "message": "tag them"}),
                           ("/api/agents/chat", {"agentId": "scout", "message": "x"}),
                           ("/api/marcus/chat", {"message": "x"}),
                           ("/api/agency/agents/chat", {"agentId": "dyson", "message": "x"}),
                           ("/api/office/chat", {"agentId": "solomon", "message": "x"})):
            HTTP.clear()
            code, res = _req("do_POST", path, body)
            assert code == 200 and res["reply"].startswith("Tagged"), (path, res)
            assert [d["summary"] for d in res["done"]] == ["Tag"] and res["actions"][0]["summary"] == "Text", (path, res)
            assert len(posts()) == 1 and dash_live._col() is None, path
        assert seen == [True] * 5
        # Office plan runs the brain on the handler thread too — but it is never wrapped
        with mock.patch.object(agent_office, "state", lambda b=None: {"departments": [{"agents": [{"id": "solomon"}]}]}), \
                mock.patch.object(connector.agents_hub, "chat",
                                  lambda *a, **k: seen.append(dash_live._col()) or {"reply": '{"summary":"x","assignments":[]}'}):
            _req("do_POST", "/api/office/plan", {"message": "plan the week"})
        assert seen[-1] is None, "office/plan stays read-only"
        # a crashing brain still closes the collector
        with mock.patch.object(connector.agents_hub, "chat", lambda *a, **k: 1 / 0):
            code, _ = _req("do_POST", "/api/hub/chat", {"agentId": "solomon", "message": "x"})
        assert code == 500 and dash_live._col() is None
        # nothing to report → the reply is untouched (no empty keys)
        with mock.patch.object(connector.agents_hub, "chat", lambda *a, **k: {"reply": "hi"}):
            assert _req("do_POST", "/api/hub/chat", {"agentId": "solomon", "message": "x"})[1] == {"reply": "hi"}
    finally:
        for p in reversed(patches):
            p.stop()


# ── daycare GHL tag + contacts-by-tag ─────────────────────────────────────────────────
class _GHL:
    configured, location_id = True, "loc"

    def __init__(self, fail=None, contacts=()):
        self.calls, self.fail, self.contacts = [], fail, list(contacts)

    def post(self, ep, body, retries=2):
        self.calls.append(("POST", ep, body))
        if self.fail == "POST":
            raise connector.urllib.error.HTTPError(ep, 422, "bad", {}, io.BytesIO(b"secret upstream body"))
        return {}

    def delete(self, ep, body=None, retries=2):
        self.calls.append(("DELETE", ep, body))
        return {}

    def get(self, ep, params=None, retries=3):
        self.calls.append(("GET", ep, params))
        return {"contacts": self.contacts, "meta": {}}


def test_system_tags_go_to_tap():
    """Security review 2026-10-18: intake / login / center tags can't be edited on the AUTO tier."""
    for add, rem in ((["family-contact-form"], None), (["website-lead"], None), (["daycare family"], None),
                     (["loc-921-n-18th"], None), (["location: a mother's touch"], None),
                     (["family-confirmed"], None), (["child-age-review"], None), (None, ["enrolled"]),
                     (None, ["loc-x"]), (["enrolled", "family-contact-form"], None)):
        reset()
        body = {"contact_id": "c1", **({"add": add} if add else {}), **({"remove": rem} if rem else {})}
        _, acts = turn("solomon", post("/api/daycare/ghl/tag", body, "t"), text("queued"))
        assert posts() == [] and len(acts["actions"]) == 1 and acts["done"] == [], (add, rem, HTTP, acts)
    reset()                                   # the ONE AUTO edit: adding an enrolled tag
    _, acts = turn("solomon", post("/api/daycare/ghl/tag", {"contact_id": "c1", "add": ["enrolled"]}, "t"),
                   text("ok"))
    assert len(posts()) == 1 and acts["actions"] == [], (HTTP, acts)
    reset()                                   # a batch with one guarded member = ONE card, nothing run
    _, acts = turn("solomon", batch([tag("c1", "enrolled"), tag("c2", "family-contact-form")]), text("q"))
    assert posts() == [] and len(acts["actions"]) == 1 and acts["actions"][0]["count"] == 2, (HTTP, acts)


def test_mail_taints_the_turn_and_cross_business_tasks_are_taps():
    """Security review 2026-10-18: email/parent text in context => every write that message is a card."""
    reset()
    _, acts = turn("solomon", tool("api_get", {"path": "/api/daycare/mail"}),
                   post("/api/daycare/ghl/tag", {"contact_id": "c1", "add": ["enrolled"]}, "t", tid="t2"),
                   text("queued"))
    assert posts() == [] and len(acts["actions"]) == 1 and acts["done"] == [], (HTTP, acts)
    reset()                                   # same write without reading mail first stays AUTO
    _, acts = turn("solomon", post("/api/daycare/ghl/tag", {"contact_id": "c1", "add": ["enrolled"]}, "t"), text("ok"))
    assert len(posts()) == 1 and acts["actions"] == [], (HTTP, acts)
    reset()                                   # own-business task AUTO; other business's agent = card
    _, acts = turn("solomon", post("/api/hub/task", {"agentId": "solomon", "title": "x"}, "t"), text("ok"))
    assert len(posts()) == 1 and acts["actions"] == [], (HTTP, acts)
    reset()
    _, acts = turn("solomon", post("/api/hub/task", {"agentId": "marcus", "title": "x"}, "t"), text("q"))
    assert posts() == [] and len(acts["actions"]) == 1, (HTTP, acts)


def test_board_reads_taint_and_board_writes_are_auto():
    """Command Board (2026-10-18): run/snooze/done are AUTO; the board quotes email subjects, so reading it
    (or a round that surfaced mail) makes every LATER write that message a card."""
    reset()
    _, acts = turn("solomon", post("/api/daycare/board/snooze", {"id": "abc", "hours": 24}, "snooze"), text("ok"))
    assert posts() == [("/api/daycare/board/snooze", {"id": "abc", "hours": 24})] and acts["actions"] == [], acts
    reset()
    _, acts = turn("solomon", tool("api_get", {"path": "/api/daycare/board"}),
                   post("/api/daycare/ghl/tag", {"contact_id": "c1", "add": ["enrolled"]}, "t", tid="t2"), text("q"))
    assert posts() == [] and len(acts["actions"]) == 1, (HTTP, acts)
    reset()
    _, acts = turn("solomon", post("/api/daycare/board/run", {}, "round"),
                   post("/api/daycare/ghl/tag", {"contact_id": "c1", "add": ["enrolled"]}, "t", tid="t2"), text("q"))
    assert posts() == [("/api/daycare/board/run", {})] and len(acts["actions"]) == 1, (HTTP, acts)
    assert acts["done"][0]["path"] == "/api/daycare/board/run"


def test_board_routes():
    import daycare_board
    saved = daycare_board.STATE
    daycare_board.STATE = TMP / "board.json"
    try:
        iid = daycare_board.upsert({"domain": "billing", "key": "inv:1", "title": "Overdue INV-1", "center": "921 N 18th St",
                                    "evidence": {"source": "Supabase invoices", "window": "latest 500"}})["id"]
        with mock.patch.object(connector.daycare_supabase, "validate_write_request", lambda *a, **k: None), \
                mock.patch.object(connector.daycare_watches, "run_round", lambda: {"ok": True, "line": "1 open"}):
            code, res = _req("do_POST", "/api/daycare/board/snooze", {"id": iid, "hours": 2})
            assert code == 200 and res["ok"] and res["state"] == "snoozed", res
            code, res = _req("do_POST", "/api/daycare/board/done", {"id": iid})
            assert code == 200 and res["ok"] and res["state"] == "done", res
            assert _req("do_POST", "/api/daycare/board/done", {"id": "nope"})[1]["ok"] is False
            assert _req("do_POST", "/api/daycare/board/run", {}) == (200, {"ok": True, "line": "1 open"})
        h = object.__new__(connector.Handler)
        h.headers, h.client_address = {}, ("127.0.0.1", 1)
        out = []
        h._send_json = lambda obj, code=200, headers=None: out.append((code, obj))
        h._daycare_resolve_session = lambda sid: (object(), None)
        h._daycare_require_secure = lambda: None
        h._daycare_session_id = lambda: None
        connector.Handler._handle_daycare_get(h, "/api/daycare/board", {"state": ["all"], "limit": ["5"]})
        assert out[0][0] == 200 and out[0][1]["items"][0]["id"] == iid and out[0][1]["state"] == "all", out
    finally:
        daycare_board.STATE = saved
    if REAL_CATALOG.get("GET"):
        assert "/api/daycare/board" in REAL_CATALOG["GET"] and "/api/daycare/board" not in REAL_CATALOG["POST"]
        for p in ("/api/daycare/board/run", "/api/daycare/board/snooze", "/api/daycare/board/done"):
            assert p in REAL_CATALOG["POST"] and ta.path_business(p) == "daycare", p
            assert ta.allowed("daycare", "POST", p)[0] and not ta.allowed("agency", "POST", p)[0], p


def test_taint_from_a_haiku_read_survives_the_restart_on_sonnet():
    """Haiku reads outside text, then wants to write: the turn restarts on Sonnet, and the read
    still counts, so the write is a card. The restart must not launder the taint."""
    reset()
    os.environ["FORGE_CHAT_ROUTER"] = "1"
    tagw = post("/api/daycare/ghl/tag", {"contact_id": "c1", "add": ["enrolled"]}, "t", tid="t2")
    try:
        _, acts = turn("solomon", tool("api_get", {"path": "/api/daycare/replies"}),
                       tagw,                                         # Haiku: write -> restart
                       tagw, text("queued"))                         # Sonnet goes straight to the write
    finally:
        os.environ["FORGE_CHAT_ROUTER"] = "0"
    assert [c["model"] for c in CALLS] == ["claude-haiku-5-5"] * 2 + ["claude-sonnet-5-5"] * 2, CALLS
    assert posts() == [] and len(acts["actions"]) == 1, (HTTP, acts)


def test_taint_is_fail_closed_and_lasts_across_messages():
    """Security review 2026-10-18 (2): any read off the no-taint allowlist taints the AGENT for 30 min."""
    import time as _t
    tagw = post("/api/daycare/ghl/tag", {"contact_id": "c1", "add": ["enrolled"]}, "t", tid="t2")
    for path in ("/api/daycare/replies", "/api/daycare/leads", "/api/scout/leads", "/api/daycare/children",
                 "/api/daycare/ghl/conversations"):
        reset()
        _, acts = turn("solomon", tool("api_get", {"path": path}), tagw, text("q"))
        assert posts() == [] and len(acts["actions"]) == 1, (path, HTTP, acts)
    assert dash_live._no_taint("/api/cost/status") and not dash_live._no_taint("/api/costume")
    assert not dash_live._no_taint("/api/daycare/ghl/contacts") and not dash_live._no_taint("/api/daycare/starts")
    assert not dash_live._no_taint("/api/actions/log") and not dash_live._no_taint("/api/daycare/board")
    for path in ("/api/daycare/ghl/enrolled-audit", "/api/system/health", "/api/daycare/ads/feed"):
        reset()                                # status / number / identifier routes do not taint
        _, acts = turn("solomon", tool("api_get", {"path": path}), tagw, text("ok"))
        assert len(posts()) == 1 and acts["actions"] == [], (path, HTTP, acts)
    reset()                                   # ACROSS messages: message 1 reads mail, message 2 (fresh collector) writes
    turn("solomon", tool("api_get", {"path": "/api/daycare/mail"}), text("read"))
    _, acts = turn("solomon", post("/api/daycare/ghl/tag", {"contact_id": "c1", "add": ["enrolled"]}, "t"), text("q"))
    assert posts() == [] and len(acts["actions"]) == 1, (HTTP, acts)
    _, acts = turn("dyson", post("/api/hub/task", {"agentId": "eco", "title": "x"}), text("ok"))
    assert len(posts()) == 1 and acts["actions"] == [], "another agent is not tainted by Solomon's read"
    old = _t.time() - 3600                     # expires after the TTL
    dash_live.TAINT_STATE.write_text(json.dumps({"solomon": int(old)}))
    reset_posts = len(posts())
    _, acts = turn("solomon", post("/api/daycare/ghl/tag", {"contact_id": "c2", "add": ["enrolled"]}, "t"), text("ok"))
    assert len(posts()) == reset_posts + 1 and acts["actions"] == [], (HTTP, acts)


def test_enrolled_audit():
    contacts = [
        {"id": "g1", "phone": "+12155550101", "tags": ["Enrolled", "location: a touch of blessings"]},
        {"id": "g2", "phone": "(215) 555-0102", "tags": ["daycare family", "location: a touch of blessings"]},
        {"id": "g3", "phone": "2675550103", "tags": ["location: a mother's touch"]},
        {"id": "g9", "phone": "", "tags": []}]
    kid = lambda f, ph, **k: {"first_name": f, "last_name": "X", "active": True,
                              "guardian": {"display_name": f + "'s mom", "phone": ph}, **k}
    groups = [{"center": "A Touch of Blessings", "children": [
                  kid("Mia", "+1 215 555 0101"), kid("Zed", "+12155550102"), kid("Old", "+12155550199"),
                  kid("Nophone", ""), kid("Gone", "+12155550102", active=False)]},
              {"center": "A Mother's Touch", "children": [kid("Ivy", "267-555-0103")]}]
    with mock.patch.object(daycare_ghl, "iter_contacts", lambda c, **k: iter(contacts)):
        r = daycare_ghl.enrolled_audit(_GHL(), groups, "enrolled")
    a, b = r["centers"]
    assert (a["center"], a["activeChildren"], a["tagged"], a["missingTag"], a["noGhlContact"],
            a["noGuardianPhone"]) == ("A Touch of Blessings", 4, 1, 1, 1, 1), a
    assert (b["center"], b["tagged"], b["missingTag"]) == ("A Mother's Touch", 0, 1), b
    assert r["missingCount"] == 2 and {m["contactId"] for m in r["missing"]} == {"g2", "g3"}, r
    assert {m["center"] for m in r["missing"]} == {"A Touch of Blessings", "A Mother's Touch"}
    assert r["noGhlContact"][0]["phoneLast4"] == "0199" and "email" not in json.dumps(r), r
    off = _GHL()
    off.configured = False
    assert daycare_ghl.enrolled_audit(off, groups)["ok"] is False


def test_ghl_tag_helper():
    g = _GHL()
    with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
        assert daycare_ghl.tag_contact(g, "c1", ["Enrolled-2026", "Enrolled-2026 "], ["old"]) == {
            "ok": True, "contactId": "c1", "added": ["Enrolled-2026"], "removed": ["old"]}
        assert out.getvalue() == "", "a plain tag is not a system tag"
        daycare_ghl.tag_contact(_GHL(), "c1", None, ["location: a mother's touch", "Enrolled"])
        assert "system tag(s): location: a mother's touch, Enrolled" in out.getvalue(), out.getvalue()
    assert g.calls == [("POST", "/contacts/c1/tags", {"tags": ["Enrolled-2026"]}),
                       ("DELETE", "/contacts/c1/tags", {"tags": ["old"]})]
    for cid, add, rem in (("", ["a"], None), ("c/1", ["a"], None), ("c1", None, None), ("c1", [], []),
                          ("c1", "a", None), ("c1", [""], None), ("c1", ["x" * 65], None),
                          ("c1", [f"t{i}" for i in range(21)], None), ("c1", [3], None)):
        r = daycare_ghl.tag_contact(_GHL(), cid, add, rem)
        assert r["ok"] is False and r["error"], (cid, add, rem, r)
    off = _GHL()
    off.configured = False
    assert "not connected" in daycare_ghl.tag_contact(off, "c1", ["a"])["error"]
    r = daycare_ghl.tag_contact(_GHL(fail="POST"), "c1", ["a"], ["b"])
    assert r["ok"] is False and "422" in r["error"] and "secret" not in json.dumps(r) and r["added"] == [], r


def test_contacts_by_tag():
    rows = [{"id": "c1", "firstName": "Mia", "lastName": "Peterson", "phone": "+12155550101", "email": "x@y.z",
             "tags": ["Enrolled", "location: a touch of blessings", "loc-921-n-18th"],
             "customFields": [{"id": daycare_ghl.CF_PARENT_NAME, "value": "Seara Peterson"}]},
            {"id": "c2", "contactName": "Ava Ross", "phone": "+12155550102",
             "tags": ["enrolled", "location: a mother's touch", "loc-1923-cecil-b-moore"]},
            {"id": "c3", "contactName": "Lead", "tags": ["website-lead"]}]
    out = daycare_ghl.contacts_by_tag(_GHL(contacts=rows), "ENROLLED")
    assert out["ok"] and out["count"] == 2 and not out["truncated"], out
    assert out["contacts"][0] == {"id": "c1", "name": "Mia Peterson", "parent": "Seara Peterson",
                                  "phone": "+12155550101", "center": "a touch of blessings",
                                  "locTag": "loc-921-n-18th",
                                  "tags": ["Enrolled", "location: a touch of blessings", "loc-921-n-18th"]}
    assert out["contacts"][1]["center"] == "a mother's touch" and out["contacts"][1]["locTag"] == "loc-1923-cecil-b-moore"
    assert "x@y.z" not in json.dumps(out), "never emails"
    assert daycare_ghl.contacts_by_tag(_GHL(contacts=rows), "enrolled", limit=1)["truncated"] is True
    assert daycare_ghl.contacts_by_tag(_GHL(), "")["error"] == "tag required"


def test_ghl_routes():
    g = _GHL(contacts=[{"id": "c1", "contactName": "Mia", "phone": "1", "tags": ["enrolled"]}])
    with mock.patch.object(connector, "DAYCARE_GHL", g), \
            mock.patch.object(connector.daycare_supabase, "validate_write_request", lambda *a, **k: None):
        code, res = _req("do_POST", "/api/daycare/ghl/tag", {"contact_id": "c1", "add": ["enrolled-2026"]})
        assert code == 200 and res == {"ok": True, "contactId": "c1", "added": ["enrolled-2026"], "removed": []}, res
        code, res = _req("do_POST", "/api/daycare/ghl/tag", {"contact_id": "c1"})
        assert code == 200 and res["ok"] is False
        h = object.__new__(connector.Handler)
        h.headers, h.client_address = {}, ("127.0.0.1", 1)
        out = []
        h._send_json = lambda obj, code=200, headers=None: out.append((code, obj))
        h._daycare_resolve_session = lambda sid: (object(), None)
        h._daycare_require_secure = lambda: None
        h._daycare_session_id = lambda: None
        connector.Handler._handle_daycare_get(h, "/api/daycare/ghl/contacts", {"tag": ["enrolled"]})
    assert out[0][0] == 200 and out[0][1]["contacts"][0]["id"] == "c1", out


REAL_CATALOG = {}


def main():
    saved_reg = dict(ta._H)
    ta.register(7799, connector.ROUTES, connector.Handler, connector.__file__)
    REAL_CATALOG.update({k: set(v) for k, v in ta.catalog().items()})
    saved = (ta.catalog, ta._http, ta.STATE, dash_live.DAY_STATE, review_agent.post_messages, forge_ops.paused)
    ta.catalog = lambda: CAT
    ta._http = fake_http
    ta.STATE = TMP / "pending.json"
    dash_live.DAY_STATE = TMP / "chat_auto_counts.json"
    dash_live.TAINT_STATE = TMP / "chat_taint.json"
    review_agent.post_messages = fake_post
    forge_ops.paused = lambda: PAUSED[0]
    failed = 0
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
        (ta.catalog, ta._http, ta.STATE, dash_live.DAY_STATE, review_agent.post_messages,
         forge_ops.paused) = saved
        ta._H.clear()
        ta._H.update(saved_reg)
    print("chat_actions:", "FAILED" if failed else "all OK")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
