"""test_daycare_pipeline.py — Solomon · Pipeline (the GHL enrollment boards), checked offline.

Covers: paged read, view() makes no network call, pipe-propose tag parsing, move()
validation (unknown opportunity/stage rejected), proposal-tag removal, the move-all cap +
confirm, a failed read keeps the last board, the manual refresh rate limit, the kill switch.
Two boards (A Touch of Blessings `enrollment` + A Mother's Touch `amt`): isolation, a
wrong-board move rejected, the default board unchanged, a missing AMT pipeline = an honest
empty board, and the live pipeline check before a move.

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
AMT_PID = "PIPE-AMT"
AMT_STAGES = [("a-" + i[2:], n, p) for i, n, p in STAGES]


def amt_opp(i, stage="a-new", tags=()):
    return dict(opp(f"a{i}", stage, tags), id=f"aa{i}", pipelineId=AMT_PID)


def opp(i, stage="s-new", tags=()):
    return {"id": f"o{i}", "name": f"Child {i}", "pipelineId": PID, "pipelineStageId": stage,
            "status": "open", "createdAt": "2026-10-20T14:00:00.000Z", "source": "website",
            "contactId": f"c{i}", "contact": {"id": f"c{i}", "name": f"child {i}", "tags": list(tags)}}


class FakeGHL:
    """GET/PUT/DELETE recorder. Search pages by startAfterId through `opps`."""

    def __init__(self, opps, page=2, fail_search=False, fail_pipelines=False, fail_put=None,
                 amt=False):
        self.configured, self.location_id = True, "LOC"
        self.opps, self.page = opps, page
        self.fail_search, self.fail_pipelines, self.fail_put = fail_search, fail_pipelines, fail_put
        self.amt = amt                 # include the "A Mother's Touch" pipeline in the list
        self.where = {}                # opportunity id -> live pipelineId override (n8n moved it)
        self.fail_opp_get = False
        self.calls = []

    def get(self, endpoint, params=None, retries=3):
        self.calls.append(("GET", endpoint, dict(params or {})))
        if endpoint == "/opportunities/pipelines":
            if self.fail_pipelines:
                raise urllib.error.URLError("down")
            out = [{"id": "other", "name": "Tours", "stages": []},
                   {"id": PID, "name": "Enrollment",
                    "stages": [{"id": i, "name": n, "position": p} for i, n, p in reversed(STAGES)]}]
            if self.amt:               # curly apostrophe on purpose: the match must normalize it
                out.append({"id": AMT_PID, "name": "A Mother\u2019s Touch",
                            "stages": [{"id": i, "name": n, "position": p} for i, n, p in AMT_STAGES]})
            return {"pipelines": out}
        if endpoint.startswith("/opportunities/") and endpoint.count("/") == 2 \
                and endpoint != "/opportunities/search":
            if self.fail_opp_get:
                raise urllib.error.HTTPError("u", 404, "x", {}, None)
            oid = endpoint.rsplit("/", 1)[1]
            known = next((o for o in self.opps if o["id"] == oid), {})
            return {"opportunity": {"id": oid, "pipelineId": self.where.get(oid)
                                    or known.get("pipelineId") or PID}}
        if endpoint == "/opportunities/search":
            if self.fail_search:
                raise urllib.error.HTTPError("u", 500, "x", {}, None)
            assert params["pipeline_id"] in (PID, AMT_PID, dp.FALLBACK_PIPELINE_ID,
                                             dp.AMT_FALLBACK_PIPELINE_ID)
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
    dp.STATE_AMT = _TMP / f"{name}-amt.json"
    dp._manual_at = {}
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


ORIGINAL_VIEW_KEYS = {"ok", "enabled", "configured", "stages", "proposals", "total", "unstaged",
                      "fetchedAt", "lastRunAt", "stale", "stageSource", "error"}


def two_boards():
    """Both pipelines in GHL; the search fake ignores pipeline_id (returns every opp), so the
    module's own pipelineId filter is what keeps the boards apart."""
    return FakeGHL([opp(1, tags=["pipe-propose:contacted"]), opp(2),
                    amt_opp(1, tags=["entity-amt", "pipe-propose:tour-scheduled"]),
                    amt_opp(2, stage="a-con"), amt_opp(3, tags=["pipe-propose:lost"])],
                   page=100, amt=True)


def test_boards_are_isolated_and_default_unchanged():
    fresh_state("iso")
    ghl = two_boards()
    assert dp.refresh(ghl)["ok"] and dp.refresh(ghl, board="amt")["ok"]
    assert not ghl.writes()
    atob, amt = dp.view(), dp.view(board="amt")
    assert ORIGINAL_VIEW_KEYS <= set(atob)                       # original payload kept
    assert atob == dp.view(board="enrollment") == dp.view(board="")
    ids = lambda v: {c["opportunityId"] for s in v["stages"] for c in s["cards"]}
    assert ids(atob) == {"o1", "o2"} and atob["total"] == 2 and atob["proposals"] == 1
    assert ids(amt) == {"aa1", "aa2", "aa3"} and amt["total"] == 3 and amt["proposals"] == 2, ids(amt)
    assert atob["label"] == "A Touch of Blessings" and amt["label"] == "A Mother's Touch"
    assert [s["id"] for s in amt["stages"]] == [i for i, _, _ in AMT_STAGES]
    assert amt["stageSource"] == "live" and not amt["missing"] and not atob["missing"]
    assert dp.STATE.exists() and dp.STATE_AMT.exists() and dp.STATE != dp.STATE_AMT
    c = dp.counts()
    assert set(c) == {"enrollment", "amt"} and c["enrollment"]["total"] == 2 and c["amt"]["total"] == 3
    assert c["amt"]["byStage"]["Contacted"] == 1 and "total" not in c       # never summed
    assert not dp.view(board="bogus")["ok"]


def test_wrong_board_move_rejected():
    fresh_state("wrong")
    ghl = two_boards()
    dp.refresh(ghl)
    dp.refresh(ghl, board="amt")
    ghl.calls.clear()
    assert not dp.move(ghl, "aa1", "contacted")["ok"]                    # AMT card on ATOB board
    assert not dp.move(ghl, "o1", "contacted", board="amt")["ok"]        # ATOB card on AMT board
    assert not dp.move(ghl, "aa1", "s-con", board="amt")["ok"]           # ATOB stage id on AMT
    assert not dp.move(ghl, "o1", "a-con")["ok"]                         # AMT stage id on ATOB
    assert not dp.move(ghl, "aa1", "contacted", board="bogus")["ok"]
    assert not dp.move_all_proposed(ghl, confirm=True, board="bogus")["ok"]
    assert not ghl.writes()
    r = dp.move(ghl, "aa1", "tour-scheduled", board="amt")
    assert r["ok"] and r["stageId"] == "a-tour", r
    assert ghl.writes()[0] == ("PUT", "/opportunities/aa1", {"pipelineStageId": "a-tour"})
    ghl.calls.clear()
    r = dp.move_all_proposed(ghl, confirm=True, board="amt")             # only aa3 (Lost) left
    assert r["moved"] == 1 and [w[1] for w in ghl.writes() if w[0] == "PUT"] == ["/opportunities/aa3"]
    assert dp.view()["proposals"] == 1 and dp.view(board="amt")["proposals"] == 0   # ATOB untouched


def test_move_checks_live_pipeline_first():
    fresh_state("live")
    ghl = two_boards()
    dp.refresh(ghl)
    ghl.calls.clear()
    ghl.where["o1"] = AMT_PID                  # n8n moved this family to A Mother's Touch
    r = dp.move(ghl, "o1", "contacted")
    assert not r["ok"] and "no longer in this pipeline" in r["error"] and not ghl.writes(), r
    ghl.where.clear()
    ghl.fail_opp_get = True                    # cannot confirm -> no write (fail-closed)
    r = dp.move(ghl, "o1", "contacted")
    assert not r["ok"] and not ghl.writes(), r
    ghl.fail_opp_get = False
    assert dp.move(ghl, "o1", "contacted")["ok"]


def test_missing_amt_pipeline_is_honest_empty():
    fresh_state("missing")
    ghl = FakeGHL([opp(1)], amt=False)
    r = dp.refresh(ghl, board="amt")
    assert r["ok"] and r["total"] == 0, r
    assert not any(c[1] == "/opportunities/search" for c in ghl.calls)   # nothing to search
    v = dp.view(board="amt")
    assert v["ok"] and v["missing"] and v["error"] is None and v["total"] == 0
    assert len(v["stages"]) == 6 and v["stageSource"] == "missing"
    assert dp.refresh(ghl)["ok"] and dp.view()["total"] == 1 and not dp.view()["missing"]
    assert not dp.move(ghl, "o1", "contacted", board="amt")["ok"] and not ghl.writes()


def test_manual_refresh_is_per_board():
    fresh_state("manual2")
    ghl = two_boards()
    assert dp.refresh_manual(ghl)["ok"] and dp.refresh_manual(ghl, board="amt")["ok"]
    assert not dp.refresh_manual(ghl, board="amt")["ok"]


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
