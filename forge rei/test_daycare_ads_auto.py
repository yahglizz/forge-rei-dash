"""Self-check for Solomon · Ads (daycare_ads_autopilot): the rules engine, the guardrails, and what
each mode is allowed to touch. No network, no Claude. Run: python3 test_daycare_ads_auto.py"""
import datetime as dt
import tempfile
from pathlib import Path

import daycare_ads_autopilot as ap
import pipeboard_io as pb

TODAY = dt.date(2026, 10, 15)
C = dict(ap.cfg(), tcpl=40.0, maxDaily=100.0)


def rows(ad, camp, adset, per_day, leads_per_day, days=14, impr=1000):
    """per_day spend + leads for each of the last `days` complete days."""
    out = []
    for i in range(1, days + 1):
        d = (TODAY - dt.timedelta(days=i)).isoformat()
        out.append({"day": d, "ad_id": ad, "campaign_id": camp, "adset_id": adset, "spend": str(per_day),
                    "impressions": str(impr), "clicks": str(int(impr * 0.02)),
                    "actions": [{"action_type": "onsite_web_lead", "value": str(leads_per_day)}]
                    if leads_per_day else []})
    return out


def world(ads_cfg, budget=3500, status="ACTIVE", cbo=True):
    """ads_cfg: [(ad_id, per_day, leads_per_day)] all in one adset of one campaign."""
    camp = {"id": "C1", "name": "camp", "status": "ACTIVE", "daily_budget": str(budget) if cbo else None}
    aset = {"id": "S1", "name": "set", "status": "ACTIVE", "campaign_id": "C1",
            "daily_budget": None if cbo else str(budget)}
    ads, daily, win = [], [], {}
    for ad, per_day, lpd in ads_cfg:
        ads.append({"id": ad, "name": f"ad {ad}", "adset_id": "S1", "campaign_id": "C1", "status": status,
                    "effective_status": status, "created_time": "2026-08-01T10:00:00-0400"})
        daily += rows(ad, "C1", "S1", per_day, lpd)
        win[ad] = {"frequency": "1.5", "impressions": "14000"}
    return {"campaigns": [camp], "adsets": [aset], "ads": ads, "daily": daily, "win": win, "today": TODAY}


def kinds(res):
    return [(d["kind"], d["level"], d["id"], d.get("to")) for d in res["decisions"]]


def check_rules():
    # winner (CPL $20 on 14d) + loser (zero leads on $294) in one set → pause loser, scale the winner budget
    res = ap.evaluate(world([("W", 20, 1), ("L", 10, 0)]), C)
    k = kinds(res)
    assert ("status", "ad", "L", "PAUSED") in k, k
    scale = [d for d in res["decisions"] if d["kind"] == "budget"]
    assert scale and scale[0]["to"] == 4200 and scale[0]["from"] == 3500, scale   # +20%, whole dollars
    assert not any(d["id"] == "W" for d in res["decisions"] if d["kind"] == "status")

    # not enough spend → WAIT: no actions at all (the 3×TCPL data gate)
    res = ap.evaluate(world([("A", 3, 0), ("B", 3, 0)]), C)       # $42 each, $84 entity < $120
    assert res["decisions"] == [], res["decisions"]

    # delivery kill: sibling hogs the ad set's real spend, the other got scraps (and is 7+ days old)
    w = world([("HOG", 30, 1), ("SCRAP", 1, 0)])
    res = ap.evaluate(w, C)
    assert ("status", "ad", "SCRAP", "PAUSED") in kinds(res), kinds(res)
    # …but an ad set that simply under-spends does NOT starve anyone
    res = ap.evaluate(world([("A", 3, 0), ("B", 3, 0)]), C)
    assert not [d for d in res["decisions"] if d["kind"] == "status"]

    # last ad standing is never paused, even dead
    res = ap.evaluate(world([("ONLY", 30, 0)]), C)
    assert not [d for d in res["decisions"] if d["kind"] == "status"], res["decisions"]
    assert res["refresh"], "a dying lone ad must queue a replacement"

    # bleeding budget: 7d CPL far over 1.5×T → cut 25%, floor respected
    res = ap.evaluate(world([("A", 30, 0.2), ("B", 30, 0.2)], budget=3500), C)
    cut = [d for d in res["decisions"] if d["kind"] == "budget"]
    assert cut and cut[0]["to"] == 2600, cut
    res = ap.evaluate(world([("A", 30, 0), ("B", 30, 0)], budget=600), C)
    cut = [d for d in res["decisions"] if d["kind"] == "budget"]
    assert cut and cut[0]["to"] == 500, cut                         # $5 floor

    # account ceiling: already at $100/day → no scale-up even for a winner
    res = ap.evaluate(world([("W", 20, 1), ("W2", 20, 1)], budget=10000), C)
    assert not [d for d in res["decisions"] if d["kind"] == "budget"]

    # paused campaign delivers nothing → nothing evaluated
    w = world([("W", 20, 1), ("L", 10, 0)])
    w["campaigns"][0]["status"] = "PAUSED"
    res = ap.evaluate(w, C)
    assert res["decisions"] == [] and res["entities"] == []

    # lead counting takes ONE action type, not the sum
    assert pb.lead_count({"actions": [{"action_type": "lead", "value": "4"},
                                      {"action_type": "onsite_web_lead", "value": "4"}]}) == 4


def check_guard():
    s = world([("W", 20, 1), ("L", 10, 0)])
    st = {}
    pause = {"kind": "status", "level": "ad", "id": "L", "name": "x", "from": "ACTIVE", "to": "PAUSED"}
    up = {"kind": "budget", "level": "campaign", "id": "C1", "name": "c", "from": 3500, "to": 4200}
    assert ap.guard(pause, s, st, C)[0] and ap.guard(up, s, st, C)[0]
    # cooldown: scaled 2 days ago → blocked; a cut is only held 2d so allowed after 3
    st = {"changed": {"C1": 1000.0}}
    assert not ap.guard(up, s, st, C, now=1000.0 + 2 * 86400)[0]
    assert ap.guard(up, s, st, C, now=1000.0 + 6 * 86400)[0]
    cut = dict(up, **{"from": 3500, "to": 2600})
    assert not ap.guard(cut, s, st, C, now=1000.0 + 1 * 86400)[0]
    assert ap.guard(cut, s, st, C, now=1000.0 + 3 * 86400)[0]
    # held, stale budget, oversized step, ceiling
    assert not ap.guard(up, s, {"held": ["C1"]}, C)[0]
    assert not ap.guard(dict(up, **{"from": 9999}), s, {}, C)[0]
    assert not ap.guard(dict(up, **{"to": 9000}), s, {}, C)[0]
    big = world([("W", 20, 1), ("L", 10, 0)], budget=9900)
    assert not ap.guard(dict(up, **{"from": 9900, "to": 11800}), big, {}, C)[0]
    # last active ad cannot be paused
    only = world([("ONLY", 30, 0)])
    assert not ap.guard(dict(pause, id="ONLY"), only, {}, C)[0]


class FakePB:
    """Records every write; serves a fixed structure."""
    PipeboardError = pb.PipeboardError
    lead_count = staticmethod(pb.lead_count)
    creds = staticmethod(pb.creds)

    def __init__(self, s):
        self.s, self.calls = s, []

    def structure(self, _):
        return {k: self.s[k] for k in ("campaigns", "adsets", "ads")}

    def set_budget(self, level, id_, cents, dry_run=False):
        self.calls.append(("budget", id_, cents, dry_run))
        if not dry_run:
            for x in self.s["campaigns" if level == "campaign" else "adsets"]:
                if x["id"] == id_:
                    x["daily_budget"] = str(cents)

    def set_status(self, level, id_, status, dry_run=False):
        self.calls.append(("status", id_, status, dry_run))
        if not dry_run:
            for x in self.s["ads"]:
                if x["id"] == id_:
                    x["status"] = status


def check_modes():
    ap.STATE = Path(tempfile.mkdtemp()) / "ads.json"
    ap.local_now = lambda now=None: dt.datetime(2026, 10, 15, 9, 0)
    s = world([("W", 20, 1), ("L", 10, 0)])
    decisions = ap.evaluate(s, C)["decisions"]
    assert len(decisions) == 2

    real = ap.pb
    try:
        # SHADOW: records proposals, writes nothing
        ap.pb = fake = FakePB(s)
        st = {}
        recs = ap._apply(decisions, s, st, C, "shadow")
        assert [r["status"] for r in recs] == ["proposed", "proposed"] and fake.calls == [], fake.calls
        ap._commit(st)

        # approving a proposal re-guards against live Meta, dry-runs, then writes
        ap._creds = lambda: pb.creds("t")
        ap._account = lambda: "act_1"
        ap._env = lambda: {"PIPEBOARD_API_TOKEN": "x"}
        aid = ap._load()["actions"][0]["aid"]
        out = ap.approve(aid)
        assert out["ok"], out
        wrote = [c for c in fake.calls if not c[3]]
        assert len(wrote) == 1 and any(c[3] for c in fake.calls), fake.calls    # dry run first, then real
        assert ap.approve(aid)["ok"] is False                                   # single-use

        # AUTO: executes, caps actions per run, never re-touches inside the cooldown
        ap.STATE = Path(tempfile.mkdtemp()) / "ads2.json"
        ap.set_mode("auto")                       # the persisted mode is the truth — a caller can never exceed it
        s2 = world([("W", 20, 1), ("L", 10, 0)])
        ap.pb = fake = FakePB(s2)
        st = {}
        recs = ap._apply(ap.evaluate(s2, C)["decisions"], s2, st, C, "auto")
        assert [r["status"] for r in recs] == ["executed", "executed"], recs
        assert s2["ads"][1]["status"] == "PAUSED" and s2["campaigns"][0]["daily_budget"] == "4200"
        st2 = {"changed": st["changed"]}
        again = ap._apply(ap.evaluate(world([("W", 20, 1), ("L", 10, 0)]), C)["decisions"],
                          {**s2}, st2, C, "auto")
        assert all(r["status"] == "skipped" for r in again), again               # cooldown / already paused

        # maxActions blast-radius cap
        s3 = world([("W", 20, 1), ("L", 10, 0)])
        ap.pb = FakePB(s3)
        recs = ap._apply(ap.evaluate(s3, C)["decisions"], s3, {}, dict(C, maxActions=1), "auto")
        assert [r["status"] for r in recs] == ["executed", "skipped"], recs

        # operator kill mid-run: mode flipped to off stops further writes
        s4 = world([("W", 20, 1), ("L", 10, 0)])
        ap.pb = fake = FakePB(s4)
        ap.STATE = Path(tempfile.mkdtemp()) / "ads3.json"
        ap.set_mode("off")
        assert ap._apply(ap.evaluate(s4, C)["decisions"], s4, {}, C, "auto") == [] and fake.calls == []
    finally:
        ap.pb = real

    assert ap.set_mode("nope")["ok"] is False and ap.set_mode("shadow")["ok"]
    # pause-only: the Pipeboard layer refuses anything that could delete
    try:
        pb.set_status("ad", "1", "DELETED")
        raise AssertionError("DELETED must be refused")
    except pb.PipeboardError:
        pass


if __name__ == "__main__":
    check_rules()
    check_guard()
    check_modes()
    print("daycare ads autopilot OK")
