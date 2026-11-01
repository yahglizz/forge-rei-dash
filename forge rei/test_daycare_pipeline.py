"""test_daycare_pipeline.py — Solomon · Pipeline (the GHL Enrollment board), checked offline.

Covers: paged read, view() makes no network call, pipe-propose tag parsing, move()
validation (unknown opportunity/stage rejected), proposal-tag removal, the move-all cap +
confirm, a failed read keeps the last board, the manual refresh rate limit, the kill switch.

Run from `forge rei/`:  FORGE_MARCUS=0 python3 test_daycare_pipeline.py   (no network)
"""
import os
import tempfile
import urllib.error
from pathlib import Path

import daycare_pipeline as dp

_TMP = Path(tempfile.mkdtemp())
PID = "PIPE-LIVE"
STAGES = [("s-new", "New Lead", 0), ("s-con", "Contacted", 1), ("s-tour", "Tour Scheduled", 2),
          ("s-app", "Application Sent", 3), ("s-enr", "Enrolled", 4), ("s-lost", "Lost", 5)]


def opp(i, stage="s-new", tags=()):
    return {"id": f"o{i}", "name": f"Child {i}", "pipelineId": PID, "pipelineStageId": stage,
            "status": "open", "createdAt": "2026-10-20T14:00:00.000Z", "source": "website",
            "contactId": f"c{i}", "contact": {"id": f"c{i}", "name": f"child {i}", "tags": list(tags)}}


class FakeGHL:
    """GET/PUT/DELETE recorder. Search pages by startAfterId through `opps`."""

    def __init__(self, opps, page=2, fail_search=False, fail_pipelines=False, fail_put=None):
        self.configured, self.location_id = True, "LOC"
        self.opps, self.page = opps, page
        self.fail_search, self.fail_pipelines, self.fail_put = fail_search, fail_pipelines, fail_put
        self.calls = []

    def get(self, endpoint, params=None, retries=3):
        self.calls.append(("GET", endpoint, dict(params or {})))
        if endpoint == "/opportunities/pipelines":
            if self.fail_pipelines:
                raise urllib.error.URLError("down")
            return {"pipelines": [{"id": "other", "name": "Tours", "stages": []},
                                  {"id": PID, "name": "Enrollment",
                                   "stages": [{"id": i, "name": n, "position": p}
                                              for i, n, p in reversed(STAGES)]}]}
        if endpoint == "/opportunities/search":
            if self.fail_search:
                raise urllib.error.HTTPError("u", 500, "x", {}, None)
            assert params["pipeline_id"] in (PID, dp.FALLBACK_PIPELINE_ID)
            start = 0
            if params.get("startAfterId"):
                start = next(i for i, o in enumerate(self.opps) if o["id"] == params["startAfterId"]) + 1
            chunk = self.opps[start:start + self.page]
            meta = {"total": len(self.opps)}
            if chunk:
                meta.update(startAfterId=chunk[-1]["id"], startAfter=1700000000000 + start)
            return {"opportunities": chunk, "meta": meta}
        raise AssertionError("unexpected GET " + endpoint)

    def put(self, endpoint, body, retries=2):
        self.calls.append(("PUT", endpoint, body))
        if self.fail_put:
            raise urllib.error.HTTPError("u", self.fail_put, "x", {}, None)
        return {"opportunity": {}}

    def delete(self, endpoint, body=None, retries=2):
        self.calls.append(("DELETE", endpoint, body))
        return {}

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]


def fresh_state(name):
    dp.STATE = _TMP / f"{name}.json"
    dp._manual_at = 0.0
    os.environ.pop("FORGE_DAYCARE_PIPELINE", None)


def test_paging_and_live_stages():
    fresh_state("paging")
    opps = [opp(i) for i in range(5)]
    ghl = FakeGHL(opps, page=2)
    r = dp.refresh(ghl)
    assert r["ok"] and r["total"] == 5, r
    searches = [c for c in ghl.calls if c[1] == "/opportunities/search"]
    assert len(searches) == 3, searches                       # 2 + 2 + 1, stops on meta.total
    assert searches[1][2]["startAfterId"] == "o1" and "startAfter" in searches[1][2]
    assert not ghl.writes()                                   # refresh is GET-only
    v = dp.view()
    assert [s["name"] for s in v["stages"]] == [n for _, n, _ in STAGES]   # sorted by position
    assert v["stages"][0]["count"] == 5 and v["total"] == 5 and v["stageSource"] == "live"
    card = v["stages"][0]["cards"][0]
    assert card["name"].startswith("Child ") and card["stageName"] == "New Lead"
    assert isinstance(card["createdAt"], int)


def test_fallback_stage_ids_when_pipelines_read_fails():
    fresh_state("fallback")
    ghl = FakeGHL([dict(opp(1, stage=dp.FALLBACK_STAGES[1][0]), pipelineId=dp.FALLBACK_PIPELINE_ID)],
                  fail_pipelines=True)
    assert dp.refresh(ghl)["ok"]
    v = dp.view()
    assert v["stageSource"].startswith("fallback") and v["stages"][1]["count"] == 1


def test_view_makes_no_network_call():
    fresh_state("view")
    dp.refresh(FakeGHL([opp(1)]))
    import urllib.request
    real = urllib.request.urlopen

    def boom(*a, **k):
        raise AssertionError("view() must not touch the network")
    urllib.request.urlopen = boom
    try:
        v = dp.view(configured=True)
    finally:
        urllib.request.urlopen = real
    assert v["ok"] and v["configured"] and v["total"] == 1 and not v["stale"]


def test_proposal_tag_parsing():
    slugs = {"new-lead", "contacted", "tour-scheduled", "application-sent", "enrolled", "lost"}
    assert dp.proposed_slug(["website-lead", "pipe-propose:tour-scheduled"], slugs) == "tour-scheduled"
    assert dp.proposed_slug(["Pipe-Propose:Contacted "], slugs) == "contacted"      # case/space
    assert dp.proposed_slug(["pipe-propose:maybe"], slugs) is None                  # unknown slug
    assert dp.proposed_slug(["pipe-propose:contacted", "pipe-propose:lost"], slugs) == "lost"
    assert dp.proposal_tags(["a", "pipe-propose:lost", "PIPE-PROPOSE:x"]) == ["pipe-propose:lost", "PIPE-PROPOSE:x"]
    fresh_state("parse")
    dp.refresh(FakeGHL([opp(1, tags=["pipe-propose:contacted"]),
                        opp(2, stage="s-con", tags=["pipe-propose:contacted"]),   # same = no chip
                        opp(3)]))
    v = dp.view()
    cards = {c["opportunityId"]: c for s in v["stages"] for c in s["cards"]}
    assert cards["o1"]["proposedStageName"] == "Contacted" and cards["o1"]["proposedStageId"] == "s-con"
    assert cards["o2"]["proposedStageId"] is None and cards["o3"]["proposedStageId"] is None
    assert v["proposals"] == 1
    assert v["stages"][0]["cards"][0]["opportunityId"] == "o1"                     # proposals first


def test_move_validation_and_tag_removal():
    fresh_state("move")
    ghl = FakeGHL([opp(1, tags=["website-lead", "pipe-propose:tour-scheduled"]), opp(2)])
    dp.refresh(ghl)
    ghl.calls.clear()
    assert not dp.move(ghl, "nope", "contacted")["ok"]                 # unknown opportunity
    assert not dp.move(ghl, "o1", "graduated")["ok"]                   # unknown stage
    assert not dp.move(ghl, "", "s-con")["ok"]
    assert not ghl.writes()                                            # rejected = zero writes
    r = dp.move(ghl, "o1", "tour-scheduled")                           # slug accepted
    assert r["ok"] and r["stageId"] == "s-tour" and r["tagsCleared"], r
    assert ghl.writes() == [("PUT", "/opportunities/o1", {"pipelineStageId": "s-tour"}),
                            ("DELETE", "/contacts/c1/tags", {"tags": ["pipe-propose:tour-scheduled"]})]
    v = dp.view()
    tour = next(s for s in v["stages"] if s["id"] == "s-tour")
    assert tour["count"] == 1 and tour["cards"][0]["proposedStageId"] is None and v["proposals"] == 0
    ghl.calls.clear()
    assert dp.move(ghl, "o2", "s-lost")["ok"]                          # id accepted, no tags to clear
    assert ghl.writes() == [("PUT", "/opportunities/o2", {"pipelineStageId": "s-lost"})]
    bad = FakeGHL([], fail_put=403)
    r = dp.move(bad, "o2", "s-con")
    assert not r["ok"] and "403" in r["error"] and len(bad.writes()) == 1   # no tag delete after a failed PUT
    assert dp.move(None, "o2", "s-con")["ok"] is False                 # not connected


def test_move_all_cap_and_confirm():
    fresh_state("moveall")
    ghl = FakeGHL([opp(i, tags=["pipe-propose:contacted"]) for i in range(55)], page=100)
    dp.refresh(ghl)
    assert dp.view()["proposals"] == 55
    ghl.calls.clear()
    assert not dp.move_all_proposed(ghl)["ok"] and not ghl.writes()   # confirm required
    r = dp.move_all_proposed(ghl, confirm=True)
    assert r["moved"] == 50 and r["failed"] == 0 and r["remaining"] == 5, {k: r[k] for k in ("moved", "remaining")}
    assert sum(1 for c in ghl.writes() if c[0] == "PUT") == 50
    r = dp.move_all_proposed(ghl, confirm=True)
    assert r["moved"] == 5 and r["remaining"] == 0 and dp.view()["proposals"] == 0
    limited = FakeGHL([], fail_put=429)
    fresh_state("moveall429")
    dp.refresh(FakeGHL([opp(i, tags=["pipe-propose:lost"]) for i in range(4)]))
    r = dp.move_all_proposed(limited, confirm=True)
    assert r["failed"] == 1 and len(r["results"]) == 1 and r["remaining"] == 4    # stops on 429


def test_failed_read_keeps_board_and_view_still_returns():
    fresh_state("fail")
    dp.refresh(FakeGHL([opp(1), opp(2)]))
    r = dp.refresh(FakeGHL([], fail_search=True))
    assert not r["ok"] and "500" in r["error"], r
    v = dp.view()
    assert v["ok"] and v["total"] == 2 and "GHL read failed" in v["error"]
    fresh_state("fail-first")
    assert not dp.refresh(FakeGHL([], fail_search=True))["ok"]
    v = dp.view()
    assert v["ok"] and v["total"] == 0 and v["stale"] and len(v["stages"]) == 6   # fallback columns
    fresh_state("never")
    v = dp.view()
    assert v["ok"] and "Not read yet" in v["error"]
    nc = FakeGHL([])
    nc.configured = False
    assert "not connected" in dp.refresh(nc)["error"] and not nc.calls


def test_move_during_refresh_is_not_overwritten():
    fresh_state("race")
    ghl = FakeGHL([opp(1, tags=["pipe-propose:enrolled"])])
    dp.refresh(ghl)
    real_get = ghl.get

    def get_and_tap(endpoint, params=None, retries=3):
        out = real_get(endpoint, params, retries)
        if endpoint == "/opportunities/search":
            assert dp.move(ghl, "o1", "enrolled")["ok"]               # owner taps mid-read
        return out
    ghl.get = get_and_tap
    assert dp.refresh(ghl)["ok"]                                        # read still says New Lead
    card = next(c for s in dp.view()["stages"] for c in s["cards"])
    assert card["stageId"] == "s-enr" and card["proposedStageId"] is None, card


def test_manual_refresh_rate_limit():
    fresh_state("manual")
    ghl = FakeGHL([opp(1)])
    assert dp.refresh_manual(ghl)["ok"]
    r = dp.refresh_manual(ghl)
    assert not r["ok"] and "try again" in r["error"]
    assert sum(1 for c in ghl.calls if c[1] == "/opportunities/search") == 1


def test_kill_switch():
    fresh_state("kill")
    ghl = FakeGHL([opp(1, tags=["pipe-propose:lost"])])
    dp.refresh(ghl)
    ghl.calls.clear()
    os.environ["FORGE_DAYCARE_PIPELINE"] = "0"
    try:
        assert not dp.enabled()
        assert not dp.refresh(ghl)["ok"] and not dp.move(ghl, "o1", "lost")["ok"]
        assert not dp.move_all_proposed(ghl, confirm=True)["ok"]
        assert not ghl.calls
        v = dp.view()
        assert v["enabled"] is False and "off" in v["error"]
        src = (Path(__file__).resolve().parent / "connector.py").read_text()
        assert "if daycare_pipeline.enabled():" in src                  # loop start is gated
    finally:
        os.environ.pop("FORGE_DAYCARE_PIPELINE", None)


if __name__ == "__main__":
    import sys
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print("FAIL", name, "-", type(e).__name__, e)
    sys.exit(1 if failed else 0)
