"""Task 5b: what agents can reach from chat, read-only. Real route catalog, fakes at the network seams.
Run: python3 test_agent_access.py   (no network; exit 1 on failure)."""
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("FORGE_ACTION_LOG", str(Path(tempfile.mkdtemp()) / "actions.jsonl"))
os.environ["FORGE_CHAT_ROUTER"] = "0"

import agency_workflows_io as awio
import connector
import dash_live
import stripe_io
import telegram_agent as ta

ta.register(7799, connector.ROUTES, connector.Handler, connector.__file__)
FAKE_SK = "sk_test_" + "A1b2C3d4E5f6G7h8"


def test_stripe_reads_are_in_scope_and_writes_stay_denied():
    for p in ("/api/stripe/status", "/api/stripe/offers"):
        assert ta.allowed_read(p) == (True, ""), p
        assert dash_live.read_ok(dash_live.ALL, p) == (True, ""), p
        assert p in ta.all_gets(), p
    # the scope is two exact routes, not the /api/stripe/ prefix: the link maker is a POST and stays out
    assert "/api/stripe/link" in ta.catalog()["POST"]
    for biz in ta.SCOPE:
        assert not ta.allowed(biz, "POST", "/api/stripe/link")[0], biz
        assert not ta.allowed(biz, "POST", "/api/stripe/status")[0], biz
    assert not ta.allowed_read("/api/stripe/link")[0]
    assert dash_live.run_tool("api_post", {"path": "/api/stripe/link", "body": {}, "summary": "x"},
                              "orion").get("error"), "no write door"


def test_stripe_routes_carry_no_secret():
    real_req, real_key = stripe_io._req, stripe_io._secret_key
    stripe_io._HEALTH.update(at=0.0, val=None)
    stripe_io._secret_key = lambda: FAKE_SK
    stripe_io._req = lambda method, path, *a, **k: {"available": [{"amount": 1250}], "pending": [{"amount": 300}]}
    try:
        out = json.dumps(connector.ROUTES["/api/stripe/status"]({}))
        offers = json.dumps(connector.ROUTES["/api/stripe/offers"]({}))
    finally:
        stripe_io._req, stripe_io._secret_key = real_req, real_key
        stripe_io._HEALTH.update(at=0.0, val=None)
    assert FAKE_SK not in out and "A1b2C3d4E5f6G7h8" not in out, out
    assert '"availableUSD": 12.5' in out and '"mode": "test"' in out, out
    assert "sk_" not in offers.replace("sk_test", "").replace("sk_live", "") and "secret" not in offers.lower()
    # the chat tool also scrubs secret-named keys before the model sees a result
    assert ta.redact({"api_key": FAKE_SK, "ok": True})["api_key"] == "[redacted]"


def test_n8n_not_connected_is_exactly_connected_false():
    saved = {k: os.environ.pop(k, None) for k in ("N8N_BASE_URL", "N8N_API_KEY")}
    try:
        assert connector.ROUTES["/api/system/n8n"]({}) == {"connected": False}
        os.environ["N8N_BASE_URL"] = "https://n8n.example.test"      # a base URL alone is still not connected
        assert connector.ROUTES["/api/system/n8n"]({}) == {"connected": False}
    finally:
        os.environ.pop("N8N_BASE_URL", None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_n8n_route_is_a_no_taint_read_but_not_mac_clean():
    p = "/api/system/n8n"
    assert ta.allowed_read(p) == (True, "") and dash_live.read_ok(dash_live.ALL, p) == (True, "")
    assert dash_live._no_taint(p) and "/api/system" in dash_live.NO_TAINT_PREFIXES
    assert not dash_live._mac_clean_call("api_get", {"path": p}), "a new read never joins the Mac clean list"
    assert dash_live.MAC_CLEAN_PREFIXES == ("/api/cost/status",)
    assert p in connector.NO_CACHE and not ta.allowed("hq", "POST", p)[0]


def _fake_n8n(pages, seen):
    def req(method, endpoint, body=None):
        seen.append((method, endpoint))
        if endpoint.startswith("/api/v1/workflows"):
            return {"data": [{"id": "w1", "name": "Daily Enrollment Organizer", "active": True, "nodes": []},
                             {"id": "w2", "name": "Tour Reply Watcher", "active": True, "nodes": []}]}
        return pages.pop(0)
    return req


def _run(r, wid="w1", status="success", at="2026-11-02T01:00:00.000Z"):
    return {"id": r, "workflowId": wid, "status": status, "startedAt": at, "stoppedAt": at,
            "finished": status == "success", "errorMessage": "Hill family 555-0100 wanted a tour"}


def test_n8n_connected_counts_the_month_and_leaks_nothing():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    os.environ.update(N8N_BASE_URL="https://n8n.example.test", N8N_API_KEY="n8n-KEY-0123456789")
    real, seen = awio._n8n_req, []
    pages = [{"data": [_run(5), _run(4, "w2", "error"), _run(3, "w1", "error"), _run(2, "w2"),
                       _run(1, "w1", at="2026-10-31T23:59:00.000Z")], "nextCursor": "c1"}]
    awio._n8n_req = _fake_n8n(pages, seen)
    try:
        out = awio.n8n_status(now)
    finally:
        awio._n8n_req = real
        os.environ.pop("N8N_BASE_URL"), os.environ.pop("N8N_API_KEY")
    assert out["connected"] is True and out["month"] == "2026-11"
    assert (out["runsThisMonth"], out["failedThisMonth"], out["capped"]) == (4, 2, False), out
    assert [r["workflow"] for r in out["recentFailures"]] == ["Tour Reply Watcher", "Daily Enrollment Organizer"]
    assert out["recent"][0]["workflow"] == "Daily Enrollment Organizer"
    text = json.dumps(out)
    assert "n8n-KEY" not in text and "example.test" not in text, "no key, no host"
    assert "Hill" not in text and "555" not in text, "no execution error text"
    assert all(m == "GET" for m, _ in seen), seen
    assert len([e for _, e in seen if "executions" in e]) == 1, "an older row ends the scan after one page"


def test_n8n_fetch_failure_stays_clean():
    os.environ.update(N8N_BASE_URL="https://n8n.example.test", N8N_API_KEY="n8n-KEY-0123456789")
    real = awio._n8n_req

    def boom(*a, **k):
        raise RuntimeError("n8n 401: bad key n8n-KEY-0123456789 at https://n8n.example.test")
    awio._n8n_req = boom
    try:
        out = awio.n8n_status()
    finally:
        awio._n8n_req = real
        os.environ.pop("N8N_BASE_URL"), os.environ.pop("N8N_API_KEY")
    assert out["connected"] is False and "n8n-KEY" not in json.dumps(out) and "example.test" not in json.dumps(out)


def test_agents_are_told_what_they_have():
    block = dash_live.live_block("marcus")
    for word in ("/api/system/n8n", "/api/stripe/status", "/api/stripe/offers", "/api/daycare/calendar",
                 "/api/brain/search", "/api/brain/recent"):
        assert word in block, word
    can = dash_live._can_line("orion", dash_live.ALL, mac=True)
    for word in ("Stripe", "Calendar", "n8n", "brain", "Mac"):
        assert word in can, word
    assert "Mac" not in dash_live._can_line("orion", dash_live.ALL)
    for biz in dash_live.CAN:        # every business's agent gets it, not only HQ
        assert "Stripe" in dash_live._can_line({"wholesale": "marcus", "agency": "dyson", "daycare": "solomon",
                                                "dropship": "midas", "hq": "orion"}[biz], dash_live.ALL)


def test_brain_is_only_on_the_scheduled_non_parent_task():
    import agent_gateway as gw
    brain = {"/api/brain/search", "/api/brain/recent"}
    assert brain <= set(gw.TASKS["solomon.pipeline_review"]["get"])
    for narrow in ("solomon.tour_followup", "dyson.lead_review"):       # a parent or a lead triggers these
        assert not brain & set(gw.TASKS[narrow]["get"]), narrow
    assert "/api/brain/search" in gw.TASKS["solomon.pipeline_review"]["prompt"]
    real, seen = ta._http, []
    ta._http = lambda method, path, query=None, **k: seen.append((method, path, query)) or {}
    try:
        ok = gw._workflow_tool({"job": {"task": "solomon.pipeline_review"}}, "api_get",
                               {"path": "/api/brain/search?q=waitlist"})
        no = gw._workflow_tool({"job": {"task": "solomon.tour_followup"}}, "api_get",
                               {"path": "/api/brain/search?q=waitlist"})
    finally:
        ta._http = real
    assert seen == [("GET", "/api/brain/search", {"q": "waitlist"})] and no.get("refused") and "refused" not in ok


def test_deny_list_untouched():
    for d in ("/auth/", "/api/agency/billing/", "/api/chat/", "/api/mac/", "/api/gateway/", "/api/send"):
        assert d in ta.DENY, d


if __name__ == "__main__":
    tests = sorted((v for k, v in globals().items() if k.startswith("test_")), key=lambda f: f.__code__.co_firstlineno)
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"all {len(tests)} passed")
