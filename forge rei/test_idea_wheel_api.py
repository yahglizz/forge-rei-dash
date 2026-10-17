#!/usr/bin/env python3
"""Integration self-check for the Idea Wheel store + /api/ideawheel/* routes.

Runs against a temp state file (FORGE_IDEAWHEEL_STATE), never marcus_state/. Covers
save/retrieve, status workflow + events, duplicate handling, tags, prefs persistence,
one-per-day planner, manual metrics, honest streak, input validation, and the connector
wiring (GET ROUTES + do_POST allowlist, private-network + same-origin guards).

    python3 test_idea_wheel_api.py     # exit 1 on failure
"""
import io
import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timedelta

TMP = tempfile.mkdtemp()
os.environ["FORGE_IDEAWHEEL_STATE"] = os.path.join(TMP, "idea_wheel.json")
os.environ.setdefault("FORGE_MARCUS", "0")
os.environ.setdefault("FORGE_ACTION_LOG", os.path.join(TMP, "actions.jsonl"))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import idea_wheel as w  # noqa: E402

FAILS = []


def check(name):
    def deco(fn):
        try:
            fn()
            print("ok   ", name)
        except Exception:  # noqa: BLE001
            FAILS.append(name)
            print("FAIL ", name)
            traceback.print_exc()
        return fn
    return deco


def post(path, body):
    return w.handle_post(path, body)


def raw():
    return json.load(open(os.environ["FORGE_IDEAWHEEL_STATE"]))


@check("spin persists the idea, seed, filters and recent history")
def _():
    r = post("/api/ideawheel/spin", {"filters": {"industry": "pets"}, "seed": "api1"})
    assert r["ok"], r
    d = raw()
    i = d["ideas"][r["idea"]["id"]]
    assert i["status"] == "new" and i["seed"] == "api1" and i["createdAt"]
    assert d["prefs"]["industry"] == "pets", "chosen filters persist"
    assert d["recent"][-1]["nicheId"] == i["nicheId"] and d["spins"] == 1
    again = w.get_idea(i["id"])
    assert again["ok"] and again["idea"]["title"] == i["title"]


@check("same seed + filters + history → same idea (replayable)")
def _():
    s0 = w.state()["spins"]
    a = post("/api/ideawheel/spin", {"filters": {"industry": "auto"}, "seed": "replay"})
    d = raw()
    d["recent"] = d["recent"][:-1]  # rewind history by one spin
    json.dump(d, open(os.environ["FORGE_IDEAWHEEL_STATE"], "w"))
    b = post("/api/ideawheel/spin", {"filters": {"industry": "auto"}, "seed": "replay"})
    assert a["idea"]["id"] == b["idea"]["id"], (a["idea"]["id"], b["idea"]["id"])
    assert w.state()["spins"] == s0 + 2


@check("save → status workflow → events; posted sets postedAt; un-post clears it")
def _():
    r = post("/api/ideawheel/spin", {"filters": {"industry": "food"}, "seed": "flow"})
    iid = r["idea"]["id"]
    s = post("/api/ideawheel/save", {"id": iid, "tags": ["Reel", "q4"]})
    assert s["ok"] and s["idea"]["status"] == "saved" and s["idea"]["tags"] == ["reel", "q4"]
    for st in ("building", "ready", "posted"):
        x = post("/api/ideawheel/status", {"id": iid, "status": st})
        assert x["ok"] and x["idea"]["status"] == st, x
    assert w.get_idea(iid)["idea"]["postedAt"]
    ev = [(e["from"], e["to"]) for e in w.get_idea(iid)["events"]]
    assert ev == [("new", "saved"), ("saved", "building"), ("building", "ready"), ("ready", "posted")], ev
    x = post("/api/ideawheel/status", {"id": iid, "status": "ready"})
    assert x["idea"]["postedAt"] is None, "un-posting must drop it from the streak"
    x = post("/api/ideawheel/status", {"id": iid, "status": "archived"})
    assert x["idea"]["status"] == "archived"
    bad = post("/api/ideawheel/status", {"id": iid, "status": "new"})
    assert "error" in bad


@check("duplicates: same niche+problem+deliverable asks first; force saves")
def _():
    r = post("/api/ideawheel/spin", {"filters": {"industry": "beauty"}, "seed": "dup"})
    first = r["idea"]
    assert post("/api/ideawheel/save", {"id": first["id"]})["ok"]
    v = post("/api/ideawheel/restyle", {"id": first["id"]})
    assert v["ok"] and v["idea"]["variantOf"] == first["id"]
    assert (v["idea"]["nicheId"], v["idea"]["patternId"], v["idea"]["formatId"]) == \
           (first["nicheId"], first["patternId"], first["formatId"])
    d = post("/api/ideawheel/save", {"id": v["idea"]["id"]})
    assert d.get("duplicate") and d["existing"]["id"] == first["id"] and not d["ok"], d
    assert w.get_idea(v["idea"]["id"])["idea"]["status"] == "new", "duplicate prompt must not save"
    f = post("/api/ideawheel/save", {"id": v["idea"]["id"], "force": True})
    assert f["ok"] and f["idea"]["status"] == "saved"
    again = post("/api/ideawheel/save", {"id": first["id"]})
    assert again["ok"], "re-saving an already-saved idea is idempotent"


@check("search / filter history by text, status and tag")
def _():
    lst = w.list_ideas(saved_only=True)
    assert lst["total"] >= 3 and "reel" in lst["tags"]
    assert all(i["status"] != "new" for i in lst["ideas"])
    tagged = w.api_ideas({"tag": ["reel"]})
    assert tagged["total"] == 1 and tagged["ideas"][0]["tags"] == ["reel", "q4"]
    arch = w.api_ideas({"status": ["archived"]})
    assert arch["total"] == 1
    none = w.api_ideas({"q": ["definitely-not-a-niche"]})
    assert none["total"] == 0
    assert "error" in w.api_ideas({"status": ["bogus"]})


@check("content kit + brief stored and retrievable")
def _():
    iid = w.list_ideas(saved_only=True)["ideas"][0]["id"]
    k = post("/api/ideawheel/kit", {"id": iid})
    assert k["ok"] and k["kit"]["ideaId"] == iid and k["idea"]["kitAt"]
    got = w.get_idea(iid)
    assert got["kit"]["storyboard"] == k["kit"]["storyboard"]
    b = w.api_brief({"id": [iid]})
    assert b["ok"] and b["markdown"].startswith("# Build brief") and w.DISCLOSURE in b["markdown"]


@check("prefs: validated and persisted")
def _():
    r = post("/api/ideawheel/prefs", {"filters": {"output": "web_app", "localOnly": True}})
    assert r["ok"] and w.state()["prefs"]["output"] == "web_app" and w.state()["prefs"]["localOnly"] is True
    assert "error" in post("/api/ideawheel/prefs", {"filters": {"output": "spaceship"}})
    assert "error" in post("/api/ideawheel/prefs", {"filters": {"localOnly": "yes"}})
    post("/api/ideawheel/prefs", {"filters": {}})


@check("planner: one idea per day, one day per idea, today's idea + next planned")
def _():
    today = datetime.now().strftime("%Y-%m-%d")
    tmr = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    a = post("/api/ideawheel/spin", {"seed": "plan-a"})["idea"]["id"]
    b = post("/api/ideawheel/spin", {"seed": "plan-b"})["idea"]["id"]
    assert post("/api/ideawheel/plan", {"date": today, "id": a})["ok"]
    st = w.state()
    assert st["todayIdea"]["id"] == a and st["todayPlanned"]
    assert w.get_idea(a)["idea"]["status"] == "saved", "planning saves the idea"
    r = post("/api/ideawheel/plan", {"date": today, "id": b})
    assert r["replaced"] == a and w.state()["todayIdea"]["id"] == b, "one post per day"
    post("/api/ideawheel/plan", {"date": tmr, "id": b})
    st = w.state()
    assert st["todayIdea"] is None and st["nextPlanned"]["date"] == tmr, "one day per idea"
    assert any(c["date"] == tmr and c["planned"] and c["planned"]["id"] == b for c in st["calendar"])
    assert post("/api/ideawheel/plan", {"date": tmr, "id": None})["ok"]
    assert w.state()["nextPlanned"] is None
    for bad in ({"date": "2026-13-40", "id": a}, {"date": "tomorrow", "id": a}, {"date": today, "id": "iw_nothexnothex"},
                {"date": "2099-01-01", "id": a}):
        assert "error" in post("/api/ideawheel/plan", bad), bad


@check("metrics: manual, clamped at 0, validated; posts derived from Posted only")
def _():
    m = post("/api/ideawheel/metric", {"metric": "inquiries", "delta": 2})["metrics"]
    assert m["inquiries"] == 2
    m = post("/api/ideawheel/metric", {"metric": "inquiries", "delta": -5})["metrics"]
    assert m["inquiries"] == 0
    for bad in ({"metric": "followers", "delta": 1}, {"metric": "inquiries", "delta": 50},
                {"metric": "inquiries", "delta": True}, {"metric": "inquiries", "delta": "1"}):
        assert "error" in post("/api/ideawheel/metric", bad), bad
    posted = sum(1 for i in raw()["ideas"].values() if i.get("postedAt"))
    assert w.state()["metrics"]["postsCompleted"] == posted


@check("streak: consecutive Posted days; unposted today doesn't break it")
def _():
    d = raw()
    ids = [i for i in d["ideas"]][:4]
    now = datetime.now()
    for k, iid in enumerate(ids[:3]):  # yesterday, 2 and 3 days ago
        d["ideas"][iid]["status"] = "posted"
        d["ideas"][iid]["postedAt"] = (now - timedelta(days=k + 1)).isoformat(timespec="seconds")
    for iid in ids[3:]:
        d["ideas"][iid]["postedAt"] = None
        if d["ideas"][iid]["status"] == "posted":
            d["ideas"][iid]["status"] = "ready"
    for iid in list(d["ideas"])[4:]:
        if d["ideas"][iid].get("postedAt"):
            d["ideas"][iid]["postedAt"] = None
            d["ideas"][iid]["status"] = "ready"
    json.dump(d, open(os.environ["FORGE_IDEAWHEEL_STATE"], "w"))
    s = w.state()["streak"]
    assert s["current"] == 3 and not s["postedToday"] and s["daysPostedLast7"] == 3, s
    post("/api/ideawheel/status", {"id": ids[3], "status": "posted"})
    s = w.state()["streak"]
    assert s["current"] == 4 and s["postedToday"], s
    d = raw()
    d["ideas"][ids[1]]["postedAt"] = (now - timedelta(days=9)).isoformat(timespec="seconds")
    json.dump(d, open(os.environ["FORGE_IDEAWHEEL_STATE"], "w"))
    assert w.state()["streak"]["current"] == 2, "a gap breaks the chain"


@check("input validation at the trust boundary")
def _():
    assert "error" in post("/api/ideawheel/save", {"id": "../../etc/passwd"})
    assert "error" in post("/api/ideawheel/save", {"id": "iw_000000000000"})  # well-formed, unknown
    assert "error" in post("/api/ideawheel/spin", {"filters": {"industry": "x"}})
    assert "error" in post("/api/ideawheel/spin", {"seed": "a b;rm"})
    assert "error" in post("/api/ideawheel/tags", {"id": w.list_ideas()["ideas"][0]["id"], "tags": ["<script>"]})
    assert "error" in post("/api/ideawheel/tags", {"id": w.list_ideas()["ideas"][0]["id"], "tags": ["a"] * 9})
    assert post("/api/ideawheel/nope", {}) is None
    assert "error" in w.api_idea({"id": ["bad"]})


@check("store survives a corrupt file (backs it up, falls back to empty, never crashes)")
def _():
    keep = open(os.environ["FORGE_IDEAWHEEL_STATE"]).read()
    open(os.environ["FORGE_IDEAWHEEL_STATE"], "w").write("{not json")
    st = w.state()
    assert st["ok"] and st["counts"]["new"] == 0
    backups = [f for f in os.listdir(TMP) if f.startswith("idea_wheel.json.corrupt-")]
    assert backups, "corrupt store must be kept aside, not silently overwritten"
    open(os.environ["FORGE_IDEAWHEEL_STATE"], "w").write(keep)


@check("connector wiring: GET routes + POST allowlist + guards")
def _():
    import connector
    for p in w.GET_ROUTES:
        assert connector.ROUTES.get(p) is w.GET_ROUTES[p] and p in connector.NO_CACHE, p
    assert connector.ROUTES["/api/ideawheel/state"]({})["ok"]

    def do_post(path, body, allowed=True, origin=None):
        payload = json.dumps(body).encode("utf-8")
        h = object.__new__(connector.Handler)
        h.path = path
        h.headers = {"Host": "localhost:7799", "Content-Length": str(len(payload))}
        if origin:
            h.headers["Origin"] = origin
        h.rfile = io.BytesIO(payload)
        h._dashboard_client_allowed = lambda: allowed
        out = []
        h._send_json = lambda obj, code=200, headers=None: out.append((code, obj))
        connector.Handler.do_POST(h)
        return out[0]

    for p in w.POST_PATHS:
        code, obj = do_post(p, {})
        assert code != 404 or obj.get("error") != "unknown endpoint", p
    code, obj = do_post("/api/ideawheel/spin", {"seed": "wired", "filters": {"industry": "retail"}})
    assert code == 200 and obj["ok"] and obj["segments"][obj["landingIndex"]]["nicheId"] == obj["idea"]["nicheId"]
    code, obj = do_post("/api/ideawheel/spin", {"seed": "x"}, allowed=False)
    assert code == 403
    code, obj = do_post("/api/ideawheel/spin", {"seed": "x"}, origin="https://evil.example")
    assert code == 403
    code, obj = do_post("/api/ideawheel/metric", {"metric": "nope", "delta": 1})
    assert code == 200 and "error" in obj


if __name__ == "__main__":
    print("\nstate file:", os.environ["FORGE_IDEAWHEEL_STATE"])
    if FAILS:
        print("FAILED: %d — %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("OK — idea wheel store + routes")
