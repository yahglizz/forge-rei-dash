#!/usr/bin/env python3
"""Self-check for the Idea Wheel engine (idea_wheel.py + idea_wheel_catalog/).

Covers: catalog size + integrity, seeded determinism, wheel landing == generated niche,
every filter, compatibility rules (no HIPAA/child-data/integration claims), repeat
avoidance + exhausted-pool answer, output validation (idea, content kit, build brief).
Pure functions only — the store/routes are covered by test_idea_wheel_api.py.

    python3 test_idea_wheel.py     # exit 1 on failure
"""
import json
import os
import random
import sys
import tempfile
import traceback

os.environ["FORGE_IDEAWHEEL_STATE"] = os.path.join(tempfile.mkdtemp(), "iw.json")
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


def _sweep(n=400, seed=7):
    o = w.options()
    rnd = random.Random(seed)
    pick = lambda lst, p=1.0: (rnd.choice([x["id"] for x in lst]) if rnd.random() < p else "")
    out = []
    for t in range(n):
        f = {"industry": pick(o["industries"], .6), "output": pick(o["outputs"], .5),
             "buildTime": pick(o["buildTimes"], .4), "complexity": pick(o["complexities"], .2),
             "market": pick(o["markets"], .2), "audience": pick(o["audiences"], .15),
             "aesthetic": pick(o["aesthetics"], .25), "localOnly": rnd.random() < .3}
        r = w.spin(f, "sweep%d" % t)
        out.append((f, r))
    return out


SWEEP = _sweep()
OK = [(f, r) for f, r in SWEEP if r["ok"]]


@check("catalog: ≥100 niches, ≥20 patterns, integrity clean")
def _():
    raw = w.catalog()["raw"]
    assert len(raw["niches"]) >= 100, len(raw["niches"])
    assert len(raw["workflows"]) >= 20, len(raw["workflows"])
    assert len(raw["sectors"]) >= 10
    probs = w.check_catalog()
    assert not probs, probs[:5]
    ids = [n["id"] for n in raw["niches"]]
    assert len(ids) == len(set(ids)), "duplicate niche ids"
    labels = [n["label"].lower() for n in raw["niches"]]
    assert len(labels) == len(set(labels)), "duplicate niche labels (synonyms must be merged)"
    for n in raw["niches"]:
        assert "NAICS" in n["sources"] and n.get("naicsTitle"), n["id"]
    for s in raw["sources"]:
        assert s["url"].startswith("https://") and s["accessed"], s["id"]


@check("research note: exists, counts match, unverified entries flagged")
def _():
    doc = open(os.path.join(HERE, "docs", "ideawheel-research.md"), encoding="utf-8").read()
    raw = w.catalog()["raw"]
    assert "**%d business subtypes**" % len(raw["niches"]) in doc
    assert "**%d reusable workflow patterns**" % len(raw["workflows"]) in doc
    unverified = sum(1 for n in raw["niches"] if not n["workflowVerified"])
    assert doc.count("workflow `unverified`") == unverified, (doc.count("workflow `unverified`"), unverified)
    for s in raw["sources"]:
        assert s["url"] in doc, s["id"]


@check("seeded generation: same seed + filters → same idea; seeds vary")
def _():
    f = {"industry": "home", "localOnly": True}
    a, b = w.spin(f, "abc"), w.spin(f, "abc")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    hist = (["hvac"], [w.combo_key("plumber", "lead_capture", "marketing_site", "industrial")])
    assert json.dumps(w.spin(f, "abc", *hist), sort_keys=True) == json.dumps(w.spin(f, "abc", *hist), sort_keys=True)
    titles = {w.spin(f, "s%d" % i)["idea"]["title"] for i in range(12)}
    assert len(titles) >= 8, len(titles)


@check("wheel: landing segment is the generated niche; 6–10 segments; variety")
def _():
    for f, r in OK:
        segs = r["segments"]
        assert 6 <= len(segs) <= w.SEGMENTS, len(segs)
        assert 0 <= r["landingIndex"] < len(segs)
        assert segs[r["landingIndex"]]["nicheId"] == r["idea"]["nicheId"], (f, r["landingIndex"])
        assert segs[r["landingIndex"]]["sectorId"] == r["idea"]["sectorId"]
    open_spins = [r for f, r in OK if not f["industry"]]
    assert open_spins
    for r in open_spins:
        pool_sectors = {n["sector"] for n in w.pool(r["filters"])}
        want = min(3, len(pool_sectors))
        assert len({s["sectorId"] for s in r["segments"]}) >= want, "segments should span sectors"


@check("filters: every filter is respected")
def _():
    idx = w.catalog()["idx"]
    for f, r in OK:
        i = r["idea"]
        n = idx["niches"][i["nicheId"]]
        if f["industry"]:
            assert i["sectorId"] == f["industry"]
            assert all(s["sectorId"] == f["industry"] for s in r["segments"])
        if f["output"]:
            assert i["deliverable"] == f["output"]
        if f["buildTime"]:
            assert i["complexity"] == f["buildTime"]
        if f["complexity"]:
            assert i["techLevel"] == w.TECH_LEVELS[f["complexity"]]
        if f["market"]:
            assert n["audience"] in (f["market"], "both")
        if f["audience"]:
            assert f["audience"] in n["audiences"]
        if f["aesthetic"]:
            assert i["styleId"] == f["aesthetic"]
        if f["localOnly"]:
            assert n["local"]
    for bad in ({"industry": "nope"}, {"output": "app"}, {"buildTime": 3}, {"localOnly": "yes"}):
        try:
            w.normalize_filters(bad)
            raise AssertionError("accepted bad filter %r" % bad)
        except ValueError:
            pass


@check("defaults: one-click spin works and leans quick")
def _():
    rs = [w.spin({}, "d%d" % i) for i in range(60)]
    assert all(r["ok"] for r in rs)
    quick = sum(1 for r in rs if r["idea"]["complexity"] == "quick")
    assert quick >= 25, quick
    for r in rs:
        if r["idea"]["complexity"] == "quick":
            assert r["idea"]["estimatedDemoHours"]["max"] <= 4


@check("compatibility: sensitive niches get guardrails, never compliance claims")
def _():
    idx = w.catalog()["idx"]
    for nid, n in idx["niches"].items():
        if not n["sensitive"]:
            continue
        pid, fid = w._combos(n, w.DEFAULT_FILTERS)[0]
        for sid in idx["styles"]:
            if not w._style_ok(idx["styles"][sid], n):
                continue
            i = w.build_idea(nid, pid, fid, sid, "ui_reveal", "standard", "c1", w.DEFAULT_FILTERS)
            g = " ".join(i["guardrails"])
            if "medical" in n["sensitive"]:
                assert "Not HIPAA compliant" in g, nid
            if "minors" in n["sensitive"]:
                assert "no real children" in g, nid
            assert not w.validate_idea(i), (nid, sid, w.validate_idea(i)[:3])
            assert set(idx["styles"][sid]["avoid"]).isdisjoint(n["sensitive"])
    medical = [nid for nid, n in idx["niches"].items() if "medical" in n["sensitive"]]
    assert "dental" in medical
    r = w.spin({"industry": "health", "aesthetic": "brutalist"}, "x")
    if r["ok"]:
        assert not set(idx["niches"][r["idea"]["nicheId"]]["sensitive"]) & {"medical", "minors", "seniors"}


@check("validation: every generated idea passes; planted violations are caught")
def _():
    for f, r in OK:
        errs = w.validate_idea(r["idea"])
        assert not errs, (r["idea"]["title"], errs[:3])
    good = OK[0][1]["idea"]
    bad = json.loads(json.dumps(good))
    bad["conceptSummary"] += " Clients love it — 40% more bookings, guaranteed. HIPAA-compliant portal."
    bad["features"].append("Online payments and SMS reminders")
    bad["status"] = "live"
    del bad["design"]["palette"]
    errs = " | ".join(w.validate_idea(bad))
    for needle in ("percentage", "fabricated", "HIPAA", "qualifier", "status", "palette"):
        assert needle in errs, (needle, errs)
    assert w.claim_violations("Not HIPAA compliant: synthetic data only.") == []


@check("repeat avoidance: recent niches/combos skipped; allow repeats overrides")
def _():
    f = {"industry": "pets"}
    first = w.spin(f, "r1")
    recent = [first["idea"]["nicheId"]]
    again = w.spin(f, "r1", recent)
    assert again["idea"]["nicheId"] not in recent
    assert all(s["nicheId"] not in recent for s in again["segments"])
    allow = w.spin(dict(f, allowRepeats=True), "r1", recent)
    assert allow["ok"]
    keyed = first["idea"]
    key = w.combo_key(keyed["nicheId"], keyed["patternId"], keyed["formatId"], keyed["styleId"])
    nxt = w.spin(dict(f, excludeRecent=False), "r1", [], [key])
    if nxt["idea"]["nicheId"] == keyed["nicheId"]:
        k2 = w.combo_key(nxt["idea"]["nicheId"], nxt["idea"]["patternId"], nxt["idea"]["formatId"], nxt["idea"]["styleId"])
        assert k2 != key


@check("exhausted pool: explains and offers to relax filters")
def _():
    pets = [n["id"] for n in w.catalog()["raw"]["niches"] if n["sector"] == "pets"]
    r = w.spin({"industry": "pets"}, "e1", pets)
    assert not r["ok"] and r["exhausted"] and r["message"]
    kinds = {s["filter"] for s in r["relax"]}
    assert "industry" in kinds and "allowRepeats" in kinds, kinds
    r2 = w.spin({"industry": "community", "output": "crm"}, "e2")
    assert not r2["ok"] and any(s["filter"] in ("industry", "output") for s in r2["relax"]), r2
    assert w.spin({"industry": "pets", "allowRepeats": True}, "e1", pets)["ok"]


@check("content kit: 15–45 s storyboard, 3 captions, disclosure, no invented proof")
def _():
    for f, r in OK[:150]:
        kit = w.generate_kit(r["idea"])
        assert not w.kit_violations(kit), w.kit_violations(kit)
        beats = [b["beat"] for b in kit["storyboard"]]
        assert beats[0] == "Hook" and beats[-1] == "CTA" and "Value prop" in beats, beats
        assert kit["storyboard"][-1]["t"].endswith("%ds" % kit["durationSeconds"])
        assert set(kit["captions"]) == {"instagram", "tiktok", "linkedin"}
        assert kit["hashtags"] and kit["thumbnailHeadline"] and kit["voiceover"] and kit["dmPitch"]
        assert w.DISCLOSURE in kit["dmPitch"]


@check("build brief: Markdown with pages, components, synthetic data, design, scope, criteria")
def _():
    for f, r in OK[:80]:
        md = w.build_brief(r["idea"], w.generate_kit(r["idea"]))
        for h in ("# Build brief", "## Concept/demo vs production", "## Pages / screens", "## Components",
                  "## Synthetic sample data", "## Visual design", "## Scope (in)", "## Out of scope",
                  "## Acceptance criteria", "## Guardrails", w.DISCLOSURE, "```json"):
            assert h in md, h
        assert not w.claim_violations(md), w.claim_violations(md)
        body = md.split("```json", 1)[1].split("```", 1)[0]
        json.loads(body)


@check("restyle: same niche/problem/deliverable, new compatible style")
def _():
    i = w.spin({"industry": "beauty"}, "rs")["idea"]
    j = w.restyle_idea(i, 1)
    assert (j["nicheId"], j["patternId"], j["formatId"]) == (i["nicheId"], i["patternId"], i["formatId"])
    assert j["styleId"] != i["styleId"] and j["variantOf"] == i["id"] and j["id"] != i["id"]
    assert not w.validate_idea(j)


@check("title reads like a brief (niche — style deliverable — features — reel)")
def _():
    t = w.spin({"industry": "auto"}, "t1")["idea"]["title"]
    parts = t.split(" — ")
    assert len(parts) == 4 and parts[3].endswith("reel") and "-second" in parts[3], t


# --------------------------------------------------------------------------- Claude + Codex agent prompt (P6)
IDEAS = [r["idea"] for _, r in OK]
for _k, _f in enumerate([{"industry": "care"}, {"industry": "health"}, {"industry": "education"}] * 6):
    _r = w.spin(_f, "calm%d" % _k)
    if _r["ok"]:
        IDEAS.append(_r["idea"])


def _sections(md):
    parts = md.split("\n## ")
    return {p.split("\n", 1)[0][:13]: p for p in parts}


def _bad_fit(idea, dna):
    ctx, m = set(dna["context"]), dna["mechanic"]
    if ctx & {"transactional", "calm", "b2b_quote"} and m["hijack"]:
        return "scroll takeover %s on %s" % (m["id"], sorted(ctx & {"transactional", "calm", "b2b_quote"}))
    if "calm" in ctx and m["heavy"]:
        return "heavy %s on calm" % m["id"]
    if "b2b_quote" in ctx and not m["subtle"]:
        return "loud %s on B2B quote tool" % m["id"]
    return None


@check("dna catalog: ≥12 mechanics, ≥8 archetypes / interactions / rule-breakers, integrity + block rules clean")
def _():
    dna = w.dna_catalog()
    assert not w.check_dna_catalog(), w.check_dna_catalog()
    assert len(dna["mechanics"]) >= 12 and len(dna["archetypes"]) >= 8
    assert len(dna["interactions"]) >= 8 and len(dna["ruleBreakers"]) >= 8


@check("every mechanic: how, implementation, reduced-motion fallback, perf budget, mobile behaviour")
def _():
    for m in w.dna_catalog()["mechanics"]:
        for f in ("how", "implementation", "reducedMotion", "perf", "mobile"):
            assert len(m[f].strip()) > 20, (m["id"], f)
        assert isinstance(m["hijack"], bool) and isinstance(m["heavy"], bool) and isinstance(m["subtle"], bool), m["id"]


@check("agent prompt deterministic: same idea + remix → same DNA + identical markdown")
def _():
    for i in IDEAS[:40]:
        for rx in (0, 3):
            a, b = w.pick_dna(i, rx), w.pick_dna(i, rx)
            assert w._dna_ids(a) == w._dna_ids(b)
            assert w.build_agent_prompt(i, rx) == w.build_agent_prompt(i, rx)


@check("remix changes the DNA and only section 3 of the prompt")
def _():
    for i in IDEAS[:60]:
        a, b = w.pick_dna(i, 0), w.pick_dna(i, 1)
        assert a["mechanic"]["id"] != b["mechanic"]["id"], i["id"]
        sa, sb = _sections(w.build_agent_prompt(i, 0, a)), _sections(w.build_agent_prompt(i, 1, b))
        assert sa.keys() == sb.keys()
        changed = [k for k in sa if sa[k] != sb[k]]
        assert changed == ["3. Design DNA"], changed


@check("variety: 100+ ideas → ≥12 distinct mechanics, ≥8 archetypes, no mechanic > 25%")
def _():
    from collections import Counter
    picks = [w.pick_dna(i, 0) for i in IDEAS]
    assert len(picks) >= 100, len(picks)
    mc = Counter(p["mechanic"]["id"] for p in picks)
    ac = Counter(p["archetype"]["id"] for p in picks)
    assert len(mc) >= 12 and len(ac) >= 8, (len(mc), len(ac))
    assert mc.most_common(1)[0][1] / len(picks) <= 0.25, mc.most_common(3)
    assert ac.most_common(1)[0][1] / len(picks) <= 0.25, ac.most_common(3)


@check("fit rules: no scroll takeover on booking/quote/medical/childcare, no heavy 3D on calm, B2B quote = subtle")
def _():
    seen = {"calm": 0, "transactional": 0, "minors": 0, "medical": 0}
    niches = w.catalog()["idx"]["niches"]
    for i in IDEAS:
        for rx in range(6):
            dna = w.pick_dna(i, rx)
            assert not _bad_fit(i, dna), _bad_fit(i, dna)
            for k in ("calm", "transactional"):
                seen[k] += k in dna["context"]
        for t in ("minors", "medical"):
            if t in niches[i["nicheId"]]["sensitive"]:
                seen[t] += 1
                assert "calm" in w.dna_context(i), i["subindustry"]
    assert all(v > 0 for v in seen.values()), seen  # the sample really covers the guarded cases


@check("anti-sameness (pure): recent picks are skipped; exhausted pool repeats and says so")
def _():
    i = IDEAS[0]
    first = w.pick_dna(i, 0, recent=[])
    again = w.pick_dna(i, 0, recent=[(first["mechanic"]["id"], first["archetype"]["id"])])
    assert again["mechanic"]["id"] != first["mechanic"]["id"] and again["archetype"]["id"] != first["archetype"]["id"]
    every = [(m["id"], a["id"]) for m, a in zip(w.dna_catalog()["mechanics"], w.dna_catalog()["archetypes"] * 2)]
    ex = w.pick_dna(i, 0, recent=every, prev={"mechanic": first["mechanic"]["id"]})
    assert ex["repeated"]["mechanic"] and ex["mechanic"]["id"] != first["mechanic"]["id"]
    assert "so this pick repeats one" in w.build_agent_prompt(i, 0, ex)
    assert "Not checked against recent prompts" in w.build_agent_prompt(i, 0)


@check("agent prompt honesty + structure: disclosure, synthetic data, roles, contract-first, ownership, 1800–3500 words")
def _():
    sample = IDEAS[:90] + [x for x in IDEAS if x["complexity"] == "ambitious"][:30]
    for i in sample:
        md = w.build_agent_prompt(i, 2)
        assert not w.agent_prompt_violations(md), (i["subindustry"], w.agent_prompt_violations(md))
        assert "**Claude Code must not:**" in md and "**Codex must not:**" in md
        assert "Reduced motion (mandatory)" in md and "Which scroll effect and why" in md


@check("skills data: every listed skill is installed on disk; style map covers every style")
def _():
    home = os.path.expanduser("~")
    sk = w.agent_skills()
    styles = {s["id"] for s in w.catalog()["raw"]["styles"]}
    assert styles <= set(sk["claude"]["style"]["map"]), styles - set(sk["claude"]["style"]["map"])
    assert set(sk["claude"]["style"]["map"].values()) <= {s["name"] for s in sk["claude"]["style"]["skills"]}
    if not os.path.isdir(os.path.join(home, ".claude", "skills")):
        print("      (skip disk check: no ~/.claude/skills on this machine)")
        return
    import glob
    c = sk["claude"]
    for s in c["core"] + c["style"]["skills"] + c["app"] + c["reel"]:
        if s.get("plugin"):
            hits = glob.glob(os.path.join(home, ".claude", "plugins", "cache", "*", s["plugin"], "*", "skills", s["name"], "SKILL.md"))
            assert hits, "plugin skill missing: %s:%s" % (s["plugin"], s["name"])
        else:
            assert os.path.isfile(os.path.join(home, ".claude", "skills", s["name"], "SKILL.md")), s["name"]
    for s in sk["codex"]["core"] + sk["codex"]["app"]:
        assert os.path.isfile(os.path.join(home, ".codex", "skills", s["name"], "SKILL.md")), "codex " + s["name"]


@check("no network or model calls: idea_wheel.py imports stdlib + forge_atomic only")
def _():
    import ast
    allowed = {"hashlib", "json", "os", "random", "re", "secrets", "threading", "time", "datetime", "pathlib",
               "forge_atomic", "tempfile", "sys"}  # sys: forge_atomic's test-isolation guard (main, 2026-10)
    for fn in ("idea_wheel.py", "forge_atomic.py"):
        src = open(os.path.join(HERE, fn), encoding="utf-8").read()
        mods = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        assert mods <= allowed, (fn, mods - allowed)
        import re as _re
        hits = [x for x in (r"urlopen", r"\burllib\b", r"http\.client", r"\bsocket\b", r"\bimport requests\b",
                            r"\brequests\.(get|post|Session)", r"\banthropic\b", r"\bopenai\b", r"\bsubprocess\b",
                            r"review_agent", r"_claude\(", r"\bfetch\(") if _re.search(x, src)]
        assert not hits, (fn, hits)


@check("mutation: unblocking a scroll-takeover mechanic for booking tools is caught")
def _():
    import copy
    real = w._JSON["experience_dna"]
    bad = copy.deepcopy(real[1])
    rail = next(m for m in bad["mechanics"] if m["id"] == "horizontal_rail")
    rail["blocks"] = []
    bad["mechanics"][0]["reducedMotion"] = ""
    w._JSON["experience_dna"] = (real[0], bad)  # same mtime → served from cache
    try:
        probs = w.check_dna_catalog()
        assert any("horizontal_rail" in p for p in probs) and any("reducedMotion" in p for p in probs), probs
        caught = [i["id"] for i in IDEAS if "transactional" in w.dna_context(i)
                  for rx in range(16) if _bad_fit(i, w.pick_dna(i, rx))]
        assert caught, "fit-rule check must fail once the block is removed"
    finally:
        w._JSON["experience_dna"] = real
    assert not w.check_dna_catalog()


if __name__ == "__main__":
    print("\n%d spins in sweep (%d ok, %d exhausted)" % (len(SWEEP), len(OK), len(SWEEP) - len(OK)))
    if FAILS:
        print("FAILED: %d — %s" % (len(FAILS), ", ".join(FAILS)))
        sys.exit(1)
    print("OK — idea wheel engine")
