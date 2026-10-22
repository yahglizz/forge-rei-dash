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


def world(ads_cfg, budget=3500, status="ACTIVE", cbo=True, days=14, name="camp"):
    """ads_cfg: [(ad_id, per_day, leads_per_day)] all in one adset of one campaign, delivering `days` days."""
    camp = {"id": "C1", "name": name, "status": "ACTIVE", "daily_budget": str(budget) if cbo else None}
    aset = {"id": "S1", "name": "set", "status": "ACTIVE", "campaign_id": "C1",
            "daily_budget": None if cbo else str(budget)}
    ads, daily, win = [], [], {}
    for ad, per_day, lpd in ads_cfg:
        ads.append({"id": ad, "name": f"ad {ad}", "adset_id": "S1", "campaign_id": "C1", "status": status,
                    "effective_status": status, "created_time": "2026-08-01T10:00:00-0400"})
        daily += rows(ad, "C1", "S1", per_day, lpd, days=days)
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


LEARN = "ATOB — Enrollment 2026 — Leads — Oct"


def check_learning():
    """Meta learning gate: hands off the new campaign until day 7 + 50 results, or day 14."""
    def run(days, lpd, name=LEARN):
        return ap.evaluate(world([("W", 20, lpd), ("L", 40, 0)], days=days, name=name), C)
    # day 3 — blocked even at 51 results: no pause, no budget move, no replacement queued
    for lpd, res in ((17, 51), (2, 6)):
        r = run(3, lpd)
        assert r["decisions"] == [] and r["refresh"] == [], r["decisions"]
        g = r["learning"]["C1"]
        assert not g["open"] and (g["day"], g["results"]) == (3, res), g
        assert r["entities"] and all(e["verdict"] == "learning" for e in r["entities"]), r["entities"]
        assert r["entities"][0]["reason"] == f"learning: day 3, {res}/50 results", r["entities"][0]
    # the same world under any other name is judged as before (L: zero leads at 3×T → pause)
    r = run(3, 17, name="Trust — Sept")
    assert ("status", "ad", "L", "PAUSED") in kinds(r) and r["learning"] == {}, kinds(r)
    # day 7: 49 results still learning; 56 results → gate open, the rules apply
    r = run(7, 7)
    assert not r["learning"]["C1"]["open"] and r["decisions"] == [], r["learning"]
    r = run(7, 8)
    assert r["learning"]["C1"]["open"] and ("status", "ad", "L", "PAUSED") in kinds(r), r["learning"]
    # day 14: open on time alone, even at 14/50 results
    r = run(14, 1)
    assert r["learning"]["C1"]["open"] and r["learning"]["C1"]["results"] == 14, r["learning"]
    assert ("status", "ad", "L", "PAUSED") in kinds(r), kinds(r)
    # hyphen / en dash / no dash / case / suffix still match; a different month does not; no delivery = day 0
    for typed in ("atob - enrollment 2026 - leads - oct (copy)", "ATOB – Enrollment 2026 – Leads – October",
                  "ATOB Enrollment 2026 Leads Oct"):
        assert ap.learn_match(typed, C), typed
    assert not ap.learn_match("ATOB — Enrollment 2026 — Leads — Nov", C)
    assert not ap.learn_match("Enrollment 2026 — Leads — Oct", C)
    w = world([("W", 20, 1)], name=LEARN)
    w["daily"] = []
    g = ap.evaluate(w, C)["learning"]["C1"]
    assert g["day"] == 0 and not g["open"] and g["note"].endswith("no complete day of delivery yet"), g


def check_learning_guard():
    """guard() refuses every action on a learning campaign (fail closed before any read); the creative
    loop and the Ad Studio Build never pick its ad set."""
    w = world([("W", 20, 1), ("L", 10, 0)], name=LEARN)
    pause = {"kind": "status", "level": "ad", "id": "L", "name": "x", "from": "ACTIVE", "to": "PAUSED"}
    cut = {"kind": "budget", "level": "campaign", "id": "C1", "name": "c", "from": 3500, "to": 2600}
    for st in ({}, {"learning": {"C1": {"open": False, "note": "learning: day 3, 4/50 results"}}}):
        for d in (pause, cut):
            ok, why = ap.guard(d, w, st, C)
            assert not ok and "learning" in why, (st, why)
    abo = world([("W", 20, 1), ("L", 10, 0)], name=LEARN, cbo=False)
    up = {"kind": "budget", "level": "adset", "id": "S1", "name": "s", "from": 3500, "to": 4200}
    assert not ap.guard(up, abo, {}, C)[0]
    st = {"learning": {"C1": {"open": True}}}
    assert ap.guard(pause, w, st, C)[0] and ap.guard(cut, w, st, C)[0] and ap.guard(up, abo, st, C)[0]
    assert ap.guard(pause, world([("W", 20, 1), ("L", 10, 0)]), {}, C)[0]      # other names: unchanged
    r = ap.evaluate(world([("W", 20, 17), ("L", 40, 0)], days=3, name=LEARN), C)
    assert ap._target_adset(r, w) is None, "no new test inside a learning ad set"

    import daycare_ads_studio as studio
    ap.STATE = Path(tempfile.mkdtemp()) / "learn.json"                      # no daily read yet
    s = {"campaigns": [{"id": "C1", "name": LEARN, "objective": "OUTCOME_LEADS", "status": "ACTIVE"},
                       {"id": "C2", "name": "Trust", "objective": "OUTCOME_LEADS", "status": "PAUSED"}],
         "adsets": [{"id": "S1", "campaign_id": "C1", "status": "ACTIVE"},
                    {"id": "S2", "campaign_id": "C2", "status": "PAUSED"}],
         "ads": [{"id": "A1", "adset_id": "S1"}, {"id": "A2", "adset_id": "S2"}]}
    rep = {"ads": [{"id": "A1", "leads": 30, "spend": 300}, {"id": "A2", "leads": 5, "spend": 150}]}
    t, _ = studio.pick_target(rep, s)
    assert t and t["adset"]["id"] == "S2", t
    rep["ads"] = rep["ads"][:1]
    t, why = studio.pick_target(rep, s)
    assert t is None and "learning phase" in why, why
    ap._save({"learning": {"C1": {"open": True}}})
    assert studio.pick_target(rep, s)[0]["adset"]["id"] == "S1"


def check_default_tcpl():
    import os
    saved = os.environ.pop("FORGE_DAYCARE_ADS_TCPL", None)
    try:
        assert ap.cfg()["tcpl"] == 30.0, ap.cfg()["tcpl"]
        os.environ["FORGE_DAYCARE_ADS_TCPL"] = "45"
        assert ap.cfg()["tcpl"] == 45.0                              # the env knob still overrides
    finally:
        os.environ.pop("FORGE_DAYCARE_ADS_TCPL", None)
        if saved is not None:
            os.environ["FORGE_DAYCARE_ADS_TCPL"] = saved


class FakeRunPB(FakePB):
    """FakePB + the reads run_once makes."""
    def account_info(self, _):
        return {"account_status_label": "ACTIVE"}

    def daily_ad_rows(self, *_):
        return self.s["daily"]

    def window_ad_rows(self, *_):
        return [dict(v, ad_id=k) for k, v in self.s["win"].items()]


def check_run_once_learning():
    """End to end through run_once (fakes, no network, no Claude, no Telegram): a learning run proposes
    nothing and records the gate; the gate-open run proposes again and stamps openedOn once."""
    import agent_bus
    ap.STATE = Path(tempfile.mkdtemp()) / "run.json"
    ap.local_now = lambda now=None: dt.datetime(2026, 10, 15, 9, 0)
    ap._creds = lambda: pb.creds("t")
    ap._account = lambda: "act_1"
    ap._env = lambda: {"PIPEBOARD_API_TOKEN": "x"}
    ap.set_mode("shadow")
    sent = []
    saved = (ap.pb, ap._notify, ap._after_run, ap.creative_cycle, ap.market_intel, ap._claude_key, agent_bus.send)
    try:
        ap._notify = lambda text, key: sent.append(key)
        ap._after_run = lambda run, mode: None
        ap.creative_cycle = lambda *a, **k: {"ran": False, "why": "test"}
        ap.market_intel = lambda *a, **k: {"summary": "n/a"}
        ap._claude_key = lambda: ""
        agent_bus.send = lambda *a, **k: None
        ap.pb = FakeRunPB(world([("W", 20, 2), ("L", 40, 0)], days=3, name=LEARN))
        out = ap.run_once()
        assert out["ok"] and out["counts"] == {} and sent == [], (out.get("counts"), sent)
        g = ap.status()["learning"]["C1"]
        assert not g["open"] and g["note"] == "learning: day 3, 6/50 results" and "openedOn" not in g, g
        ap.pb = FakeRunPB(world([("W", 20, 1), ("L", 40, 0)], days=14, name=LEARN))
        out = ap.run_once()
        assert out["counts"].get("proposed") and len(sent) == 1, (out["counts"], sent)
        assert any(p["id"] == "L" and p["to"] == "PAUSED" for p in ap.status()["pending"]), "rules apply again"
        g = ap.status()["learning"]["C1"]
        assert g["open"] and g["openedOn"] == "2026-10-15", g
        st = ap._load()
        st["learning"]["C1"]["openedOn"] = "2026-10-12"
        ap._save(st)
        ap.pb = FakeRunPB(world([("W", 20, 1), ("L", 40, 0)], days=14, name=LEARN))
        ap.run_once()
        assert ap.status()["learning"]["C1"]["openedOn"] == "2026-10-12", "openedOn is kept, not re-stamped"
        assert ap.get_mode() == "shadow"
    finally:
        (ap.pb, ap._notify, ap._after_run, ap.creative_cycle, ap.market_intel, ap._claude_key, agent_bus.send) = saved


if __name__ == "__main__":
    check_rules()
    check_guard()
    check_modes()
    check_learning()
    check_learning_guard()
    check_default_tcpl()
    check_run_once_learning()
    print("daycare ads autopilot OK")
