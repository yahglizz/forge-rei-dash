"""idea_wheel.py — Business Idea Wheel (Agency workspace · Personal lens).

Spin → a coherent, buildable portfolio concept: niche + customer problem + deliverable +
visual direction + content plan. Deterministic and offline: a structured catalog
(`idea_wheel_catalog/*.json`, researched in docs/ideawheel-research.md) combined by a
seeded RNG, so the same seed + filters + history always gives the same idea. No model call
per spin; `_enrich()` is the hook for an optional AI pass later (must re-run validate_idea).

Honesty rules baked in (agency evidence discipline):
  - every concept carries DISCLOSURE; no testimonials, ratings, % lifts or other invented proof
  - medical / minors / finance / legal niches get synthetic-data guardrails, never compliance claims
  - payments, SMS, AI replies, maps, calendar sync are always labeled mock/demo
  - the wheel's landing segment IS the generated niche (server picks the result from the
    segments it returns — no fake spin)
  - "posted" only when the operator marks it; the streak counts only those days

Store: marcus_state/idea_wheel.json (override with FORGE_IDEAWHEEL_STATE for tests), same
idiom as agency_calls.py: forge_atomic + one lock + _load/_save. Internal + reversible, so no
approval gate — nothing here is an outward action.

    python3 idea_wheel.py        # quick self-check (catalog integrity + one spin)
"""
import hashlib
import json
import os
import random
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import forge_atomic

HERE = Path(__file__).resolve().parent
CATALOG_DIR = HERE / "idea_wheel_catalog"
_DEFAULT_STATE = HERE / "marcus_state" / "idea_wheel.json"
_LOCK = threading.Lock()

DISCLOSURE = "Independent concept; not affiliated with or commissioned by a real business."
STATUSES = ("new", "saved", "building", "ready", "posted", "archived")
DELIVERABLES = ("website", "web_app", "mobile_concept", "automation", "crm", "hybrid")
COMPLEXITY = ("quick", "standard", "ambitious")
TECH_LEVELS = {"low": 1, "medium": 2, "high": 3}
HOURS = {"quick": (1, 3), "standard": (3, 6), "ambitious": (6, 12)}
SIZES = {"quick": (4, 4, 4), "standard": (5, 5, 5), "ambitious": (7, 6, 6)}  # features, screens, scope
METRICS = ("inquiries", "demosSent", "bookedCalls", "signedClients")
SEGMENTS = 10
MIN_SEGMENTS = 6
RECENT_NICHES = 12
RECENT_COMBOS = 300
MAX_NEW_KEPT = 150
DIFFICULTY = {1: "Beginner-friendly", 2: "Intermediate", 3: "Advanced"}

DEFAULT_FILTERS = {
    "industry": "", "output": "", "buildTime": "", "complexity": "", "market": "",
    "audience": "", "aesthetic": "", "excludeRecent": True, "localOnly": False, "allowRepeats": False,
}
FILTER_LABELS = {
    "industry": "Any industry", "output": "Any output type", "buildTime": "Any build time",
    "complexity": "Any complexity", "market": "B2B + B2C", "audience": "Any audience",
    "aesthetic": "Any aesthetic", "localOnly": "Not just local businesses",
    "excludeRecent": "Include recent niches", "allowRepeats": "Allow repeats",
}
ID_RE = re.compile(r"^iw_[0-9a-f]{12}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAG_RE = re.compile(r"^[\w][\w \-]{0,23}$")

GUARDS = {
    "medical": "Not HIPAA compliant and not a medical system: synthetic records only, no real patient data, no clinical advice.",
    "minors": "Fictional placeholder profiles only: no real children's names, photos or records.",
    "seniors": "Fictional placeholder profiles only: no real client names or health details.",
    "finance": "Synthetic financial data only: no real quotes, accounts or financial advice.",
    "legal": "Not legal advice: the intake demo collects no real case details.",
    "alcohol": "Include a 21+ age-gate screen.",
    "animal_health": "Synthetic pet records only: no real medical history.",
}
GUARD_ALWAYS = [
    "Synthetic sample data only — no real customer records, names or photos.",
    "Payments, SMS/email, AI replies, maps and calendar sync are shown as mock/demo only.",
    "No testimonials, ratings, metrics or results are invented for this concept.",
]


def _path():
    return Path(os.environ.get("FORGE_IDEAWHEEL_STATE") or _DEFAULT_STATE)


def _rng(*parts):
    key = "|".join(str(p) for p in parts)
    return random.Random(int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big"))


def _hash(*parts, n=12):
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:n]


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- catalog
_CAT = {"mtime": None, "data": None}
_CAT_FILES = ("sectors", "niches", "workflows", "formats", "styles", "angles", "audiences", "sources")


def catalog():
    """Load idea_wheel_catalog/*.json (mtime-cached, so catalog edits apply without a restart)."""
    mtime = max((CATALOG_DIR / (f + ".json")).stat().st_mtime for f in _CAT_FILES)
    if _CAT["mtime"] != mtime:
        raw = {f: json.loads((CATALOG_DIR / (f + ".json")).read_text(encoding="utf-8")) for f in _CAT_FILES}
        idx = {f: {x["id"]: x for x in raw[f]} for f in _CAT_FILES}
        version = _hash(*[json.dumps(raw[f], sort_keys=True) for f in _CAT_FILES], n=8)
        _CAT["data"] = {"raw": raw, "idx": idx, "version": version}
        _CAT["mtime"] = mtime
    return _CAT["data"]


def check_catalog():
    """Referential integrity of the catalog → list of problems (empty = OK)."""
    c = catalog()
    idx, raw = c["idx"], c["raw"]
    errs = []
    for n in raw["niches"]:
        nid = n["id"]
        if n["sector"] not in idx["sectors"]:
            errs.append(nid + ": unknown sector")
        if not re.fullmatch(r"\d{6}", n.get("naics", "")):
            errs.append(nid + ": bad NAICS")
        for p in n["problems"]:
            if p not in idx["workflows"]:
                errs.append(nid + ": unknown pattern " + p)
        for s in n["styles"]:
            st = idx["styles"].get(s)
            if not st:
                errs.append(nid + ": unknown style " + s)
            elif set(st["avoid"]) & set(n["sensitive"]):
                errs.append(nid + ": preferred style %s is avoided for its sensitive tags" % s)
        for a in n["audiences"]:
            if a not in idx["audiences"]:
                errs.append(nid + ": unknown audience " + a)
        for s in n["sources"]:
            if s not in idx["sources"]:
                errs.append(nid + ": unknown source " + s)
        if not _combos(n, DEFAULT_FILTERS):
            errs.append(nid + ": no valid pattern/format combination")
        if len(n["short"]) > 17:
            errs.append(nid + ": short label too long for a wheel segment")
    for p in raw["workflows"]:
        for f in p["formats"]:
            if f not in idx["formats"]:
                errs.append(p["id"] + ": unknown format " + f)
    for f in raw["formats"]:
        if f["deliverable"] not in DELIVERABLES:
            errs.append(f["id"] + ": bad deliverable")
    for s in raw["styles"]:
        if len(s["palette"]) < 4 or not all(re.fullmatch(r"#[0-9A-Fa-f]{6}", h) for h in s["palette"]):
            errs.append(s["id"] + ": bad palette")
    return errs


def options():
    """Filter options for the UI (all from the catalog — nothing hard-coded in the page)."""
    c = catalog()
    raw = c["raw"]
    return {
        "industries": [{"id": s["id"], "label": s["label"]} for s in raw["sectors"]],
        "outputs": [{"id": d, "label": lbl} for d, lbl in (
            ("website", "Website"), ("web_app", "Web app"), ("mobile_concept", "Mobile app concept"),
            ("automation", "AI / automation"), ("crm", "CRM"), ("hybrid", "Hybrid"))],
        "buildTimes": [{"id": "quick", "label": "Quick (1–3 h)"}, {"id": "standard", "label": "Standard (3–6 h)"},
                       {"id": "ambitious", "label": "Ambitious (6–12 h)"}],
        "complexities": [{"id": "low", "label": "Low"}, {"id": "medium", "label": "Medium"}, {"id": "high", "label": "High"}],
        "markets": [{"id": "b2c", "label": "B2C"}, {"id": "b2b", "label": "B2B"}],
        "audiences": [{"id": a["id"], "label": a["label"]} for a in raw["audiences"]],
        "aesthetics": [{"id": s["id"], "label": s["label"]} for s in raw["styles"]],
        "sectors": raw["sectors"],
        "counts": {"niches": len(raw["niches"]), "patterns": len(raw["workflows"]),
                   "styles": len(raw["styles"]), "formats": len(raw["formats"])},
        "catalogVersion": c["version"],
    }


# --------------------------------------------------------------------------- filters
def normalize_filters(f):
    """Validate + fill defaults. Unknown values raise ValueError (trust boundary)."""
    f = dict(f or {})
    c = catalog()
    idx = c["idx"]
    out = dict(DEFAULT_FILTERS)
    allowed = {
        "industry": set(idx["sectors"]), "output": set(DELIVERABLES), "buildTime": set(COMPLEXITY),
        "complexity": set(TECH_LEVELS), "market": {"b2b", "b2c"}, "audience": set(idx["audiences"]),
        "aesthetic": set(idx["styles"]),
    }
    for k, ok in allowed.items():
        v = f.get(k) or ""
        if not isinstance(v, str) or (v and v not in ok):
            raise ValueError("bad filter value for " + k)
        out[k] = v
    for k in ("excludeRecent", "localOnly", "allowRepeats"):
        if k in f:
            if not isinstance(f[k], bool):
                raise ValueError(k + " must be true or false")
            out[k] = f[k]
    return out


def _style_ok(style, niche):
    return not (set(style["avoid"]) & set(niche["sensitive"]))


def _combos(niche, filters):
    """Valid (pattern, format) pairs for a niche under filters — the compatibility core."""
    idx = catalog()["idx"]
    tech_max = TECH_LEVELS.get(filters.get("complexity") or "", None)
    out = []
    for pid in niche["problems"]:
        p = idx["workflows"][pid]
        if tech_max is not None and p["tech"] != tech_max:
            continue
        for fid in p["formats"]:
            fmt = idx["formats"][fid]
            if filters.get("output") and fmt["deliverable"] != filters["output"]:
                continue
            out.append((pid, fid))
    return out


def _niche_ok(n, filters):
    if filters["industry"] and n["sector"] != filters["industry"]:
        return False
    if filters["market"] and n["audience"] not in (filters["market"], "both"):
        return False
    if filters["audience"] and filters["audience"] not in n["audiences"]:
        return False
    if filters["localOnly"] and not n["local"]:
        return False
    if filters["aesthetic"] and not _style_ok(catalog()["idx"]["styles"][filters["aesthetic"]], n):
        return False
    return bool(_combos(n, filters))


def pool(filters, recent_niches=()):
    """Niches eligible under filters minus recent ones (unless repeats are allowed)."""
    niches = sorted(catalog()["raw"]["niches"], key=lambda n: n["id"])
    out = [n for n in niches if _niche_ok(n, filters)]
    if filters["excludeRecent"] and not filters["allowRepeats"]:
        recent = set(recent_niches)
        out = [n for n in out if n["id"] not in recent]
    return out


def relax_suggestions(filters, recent_niches=()):
    """When the pool is empty: which single change would reopen it, biggest pool first."""
    sugg = []
    for k in ("industry", "output", "buildTime", "complexity", "market", "audience", "aesthetic"):
        if filters[k]:
            trial = dict(filters, **{k: ""})
            size = len(pool(trial, recent_niches))
            if size:
                sugg.append({"filter": k, "label": FILTER_LABELS[k], "pool": size})
    if filters["localOnly"]:
        size = len(pool(dict(filters, localOnly=False), recent_niches))
        if size:
            sugg.append({"filter": "localOnly", "label": FILTER_LABELS["localOnly"], "pool": size})
    if not filters["allowRepeats"] and filters["excludeRecent"]:
        size = len(pool(dict(filters, allowRepeats=True), recent_niches))
        if size:
            sugg.append({"filter": "allowRepeats", "label": FILTER_LABELS["allowRepeats"], "pool": size})
    sugg.sort(key=lambda s: -s["pool"])
    return sugg


# --------------------------------------------------------------------------- generation
def _segments(rng, candidates, philly_weight):
    """Rotating subset of industries for the wheel: round-robin across sectors so one spin
    shows variety, Philadelphia-noted niches favored when local emphasis is on."""
    by_sector = {}
    for n in candidates:
        by_sector.setdefault(n["sector"], []).append(n)
    for lst in by_sector.values():
        if philly_weight:
            lst.sort(key=lambda n: (-(3 if n["phillyNote"] else 1) * rng.random(), n["id"]))
        else:
            rng.shuffle(lst)
    sectors = sorted(by_sector)
    rng.shuffle(sectors)
    picked = []
    while len(picked) < SEGMENTS and any(by_sector[s] for s in sectors):
        for s in sectors:
            if by_sector[s] and len(picked) < SEGMENTS:
                picked.append(by_sector[s].pop(0))
    base = list(picked)
    while len(picked) < MIN_SEGMENTS:  # tiny pools: repeat so it still reads as a wheel
        picked.append(base[len(picked) % len(base)])
    return picked


def _cap(s):
    return s[:1].upper() + s[1:] if s else s


def _low(s):
    first = (s or "").split(" ")[0]
    return s if not s or (len(first) > 1 and first.isupper()) else s[:1].lower() + s[1:]


def _spoken(s):
    """Label for prose: drop parentheticals ("Home daycare (family child care)" → "Home daycare")."""
    return re.sub(r"\s*\([^)]*\)", "", s or "").strip()


def _lc(s):
    """Lowercase for mid-sentence use, keeping acronyms (CRM, AI, CPA, 21+)."""
    return " ".join(w if (len(w) > 1 and w.isupper()) else w.lower() for w in (s or "").split(" "))


def _a(phrase):
    """'a'/'an' + phrase (sound heuristic: vowel letter; good enough for catalog labels)."""
    return ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase


def story_ctx(n, p, fmt, st):
    nl, fl, sl, pl = _lc(_spoken(n["label"])), _lc(_spoken(fmt["label"])), _lc(st["label"]), _lc(p["label"])
    return {"niche": n["label"], "niche_lower": nl, "a_niche": _a(nl), "pattern_lower": pl, "a_pattern": _a(pl),
            "format_lower": fl, "a_format": _a(fl), "style_lower": sl, "A_style": _cap(_a(sl)),
            "problem_short": p["problem"].split(",")[0].rstrip(".") + ".",
            "verb": "book" if "book" in p["id"] else "get started"}


def _dedupe(items):
    seen, out = set(), []
    for x in items:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _fill(tpl, ctx):
    try:
        return tpl.format(**ctx)
    except (KeyError, IndexError):
        return tpl


def build_idea(niche_id, pattern_id, format_id, style_id, angle_id, complexity, seed, filters):
    """Assemble one Idea from catalog parts (pure, deterministic)."""
    c = catalog()
    idx = c["idx"]
    n, p, fmt = idx["niches"][niche_id], idx["workflows"][pattern_id], idx["formats"][format_id]
    st, ang, sec = idx["styles"][style_id], idx["angles"][angle_id], idx["sectors"][n["sector"]]
    rng = _rng(seed, niche_id, pattern_id, format_id, style_id, angle_id, complexity)
    nf, ns, nd = SIZES[complexity]
    diff = rng.choice(p["differentiators"])
    features = _dedupe(n["features"] + [diff + " (signature moment)"] + p["features"])[:nf]
    screens = _dedupe(fmt["pages"][:2] + n["pages"] + p["screens"] + fmt["pages"][2:])[:ns]
    scope = _dedupe(p["demoScope"] + ["Synthetic sample data in a local JSON file",
                                     "Responsive layout (desktop + phone)",
                                     "Disclosure line in the footer", "Keyboard + reduced-motion pass"])[:nd]
    tech = p["tech"]
    lo, hi = HOURS[complexity]
    cap = hi + (1 if complexity == "quick" else 2)  # rough estimate, but "quick" must stay quick
    hours = {"min": max(1, round(lo * fmt["hoursFactor"])),
             "max": min(cap, max(2, round(hi * fmt["hoursFactor"] * (1 + 0.15 * (tech - 1)))))}
    if hours["max"] <= hours["min"]:
        hours["max"] = hours["min"] + 1
    level = min(3, tech + (1 if complexity == "ambitious" else 0))
    if complexity == "quick":
        level = min(level, 2)
    seconds = max(15, min(45, ang["seconds"]))
    ctx = story_ctx(n, p, fmt, st)
    hook = _fill(rng.choice(ang["hooks"]), ctx)
    beats = [_fill(b[0], ctx) for b in ang["beats"]]
    feat_title = ", ".join(_low(x) for x in features[:4] if "signature" not in x)
    title = "%s — %s %s — %s — %d-second %s reel" % (
        n["label"], _lc(st["label"]), _lc(fmt["label"]), feat_title, seconds, _lc(ang["label"]))
    fphrase = _a(_lc(_spoken(fmt["label"]))) + ("" if "concept" in fmt["label"].lower() else " concept")
    summary = "%s for %s: %s Built for %s, styled %s, with %s as the signature moment." % (
        _cap(fphrase), ctx["a_niche"], _low(p["summary"].rstrip(".")) + ".",
        _low(n["customer"]), _lc(st["label"]), _low(_spoken(diff)))
    guards = list(GUARD_ALWAYS) + [GUARDS[t] for t in n["sensitive"] if t in GUARDS]
    if p.get("guard"):
        guards.append(p["guard"])
    tags_src = _dedupe(n["sources"] + p["sources"])
    hashtags = _hashtags(n, sec, fmt, filters)
    idea = {
        "id": "iw_" + _hash(seed, json.dumps(filters, sort_keys=True), niche_id, pattern_id, format_id, style_id, angle_id, complexity),
        "seed": str(seed),
        "createdAt": None,
        "industry": sec["label"],
        "subindustry": n["label"],
        "targetCustomer": n["customer"],
        "problem": p["problem"],
        "deliverable": fmt["deliverable"],
        "deliverableLabel": fmt["label"],
        "title": title,
        "conceptSummary": summary,
        "design": {"aesthetic": st["label"], "palette": list(st["palette"]), "typography": st["typography"],
                   "layout": st["layout"], "motion": st["motion"]},
        "features": features,
        "pagesOrScreens": screens,
        "demoScope": scope,
        "complexity": complexity,
        "estimatedDemoHours": hours,
        "content": {
            "hook": hook,
            "videoStoryboard": beats,
            "caption": "%s %s concept: %s. %s" % (n["label"], _lc(fmt["label"]), _lc(p["label"]), DISCLOSURE),
            "cta": "Want a version built around your real services? Message me.",
            "hashtags": hashtags,
        },
        "pitchAngle": ("Lead with the %s moment (%s) as a concept the %s can react to in 30 seconds; offer to adapt "
                       "it to their real services and what they already use — never imply their current site is broken."
                       % (_lc(p["label"]), _low(_spoken(diff)), _low(n["buyer"]))),
        "status": "new",
        "sourceTags": tags_src,
        # --- extras beyond the spec's Idea type (UI + traceability) ---
        "nicheId": niche_id, "sectorId": n["sector"], "patternId": pattern_id, "formatId": format_id,
        "styleId": style_id, "angleId": angle_id, "differentiator": diff, "painPoint": p["problem"],
        "buyer": n["buyer"], "market": n["audience"], "naics": n["naics"], "naicsTitle": n.get("naicsTitle", ""),
        "difficulty": DIFFICULTY[level], "techLevel": tech, "videoSeconds": seconds,
        "guardrails": guards, "disclosure": DISCLOSURE, "patternLabel": p["label"],
        "catalogVersion": c["version"], "filters": filters, "tags": [], "variantOf": None,
        "savedAt": None, "postedAt": None, "kitAt": None,
    }
    return _enrich(idea)


def _enrich(idea):
    # hook: optional server-side AI enrichment (v2). Must keep the schema, time out fast,
    # fall back to this deterministic idea, and pass validate_idea() before returning.
    return idea


def _camel(s):
    return "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", s))


def _hashtags(n, sec, fmt, filters):
    tags = ["#" + _camel(n["short"]), "#" + _camel(sec["label"].split("&")[0]), "#SmallBusiness",
            "#WebDesign" if fmt["deliverable"] in ("website", "hybrid") else "#AppDesign",
            "#UIDesign", "#ConceptDesign", "#BuildInPublic"]
    if filters.get("localOnly"):
        tags.append("#PhillySmallBusiness")
    return _dedupe(tags)[:8]


def spin(filters, seed, recent_niches=(), recent_combos=()):
    """Pure: filters + seed + history → wheel segments + landing index + idea, or an
    exhausted-pool answer with relax suggestions. Same inputs → same output."""
    filters = normalize_filters(filters)
    c = catalog()
    idx = c["idx"]
    candidates = pool(filters, recent_niches)
    if not candidates:
        only_recent = bool(pool(dict(filters, allowRepeats=True), recent_niches))
        return {"ok": False, "exhausted": True,
                "message": ("You've already seen every niche that matches these filters. Allow repeats, or relax a filter.")
                if only_recent else "No niche in the catalog matches this combination of filters. Relax one of them.",
                "relax": relax_suggestions(filters, recent_niches), "filters": filters}
    rng = _rng("spin", seed, json.dumps(filters, sort_keys=True), ",".join(sorted(recent_niches)))
    segs = _segments(rng, candidates, filters["localOnly"])
    landing = rng.randrange(len(segs))
    niche = segs[landing]
    blocked = set() if filters["allowRepeats"] else set(recent_combos)
    combos = _combos(niche, filters)
    rng.shuffle(combos)
    complexity = filters["buildTime"] or rng.choices(COMPLEXITY, weights=(6, 3, 1))[0]
    styles_all = sorted(s for s in idx["styles"] if _style_ok(idx["styles"][s], niche))
    angles = sorted(idx["angles"])
    chosen = None
    for pid, fid in combos:
        if filters["aesthetic"]:
            sid = filters["aesthetic"]
        else:
            pref = [s for s in niche["styles"] if s in styles_all]
            broad = [s for s in styles_all if idx["styles"][s].get("broad")]
            sid = rng.choice(pref) if (pref and rng.random() < 0.75) else rng.choice(broad or styles_all)
        key = combo_key(niche["id"], pid, fid, sid)
        if key not in blocked:
            chosen = (pid, fid, sid)
            break
    if chosen is None:  # every combo for this niche already shown — take the first, flagged
        pid, fid = combos[0]
        chosen = (pid, fid, filters["aesthetic"] or (niche["styles"][0] if niche["styles"][0] in styles_all else styles_all[0]))
    angle = rng.choice(angles)
    idea = build_idea(niche["id"], chosen[0], chosen[1], chosen[2], angle, complexity, seed, filters)
    segments = [{"nicheId": s["id"], "label": s["short"], "sectorId": s["sector"],
                 "sector": idx["sectors"][s["sector"]]["label"], "icon": idx["sectors"][s["sector"]]["icon"],
                 "color": idx["sectors"][s["sector"]]["color"]} for s in segs]
    return {"ok": True, "seed": str(seed), "segments": segments, "landingIndex": landing,
            "idea": idea, "poolSize": len(candidates), "filters": filters}


def combo_key(niche_id, pattern_id, format_id, style_id):
    return "|".join((niche_id, pattern_id, format_id, style_id))


def restyle_idea(idea, attempt):
    """Same niche/problem/deliverable, a different compatible visual direction."""
    idx = catalog()["idx"]
    niche = idx["niches"][idea["nicheId"]]
    styles = sorted(s for s in idx["styles"] if _style_ok(idx["styles"][s], niche) and s != idea["styleId"]
                    and (s in niche["styles"] or idx["styles"][s].get("broad")))
    rng = _rng("restyle", idea["seed"], idea["id"], attempt)
    sid = rng.choice(styles)
    new = build_idea(idea["nicheId"], idea["patternId"], idea["formatId"], sid, idea["angleId"],
                     idea["complexity"], "%s:r%d" % (idea["seed"], attempt), idea.get("filters") or DEFAULT_FILTERS)
    new["variantOf"] = idea["id"]
    return new


# --------------------------------------------------------------------------- validation
IDEA_SCHEMA = {
    "type": "object",
    "required": {
        "id": str, "seed": str, "industry": str, "subindustry": str, "targetCustomer": str, "problem": str,
        "deliverable": str, "title": str, "conceptSummary": str, "design": dict, "features": list,
        "pagesOrScreens": list, "demoScope": list, "complexity": str, "estimatedDemoHours": dict,
        "content": dict, "pitchAngle": str, "status": str, "sourceTags": list,
    },
    "enums": {"deliverable": DELIVERABLES, "complexity": COMPLEXITY, "status": STATUSES},
    "design": {"aesthetic": str, "palette": list, "typography": str, "layout": str, "motion": str},
    "content": {"hook": str, "videoStoryboard": list, "caption": str, "cta": str, "hashtags": list},
}

# Claims an honest concept must never make. Negations ("not HIPAA compliant") are allowed.
_CLAIMS = [
    (re.compile(r"(?i)(?<!not )(?<!never )(?<!no )\bHIPAA[- ]?(compliant|certified|secure)"), "HIPAA compliance claim"),
    (re.compile(r"\b\d{1,3}(\.\d+)?\s?%"), "percentage claim"),
    (re.compile(r"(?i)(?<!no )(?<!never )\b(testimonials?|5[- ]star|five[- ]star|guarantee[ds]?|money[- ]back|#1|number one|best in (the )?(city|philly|town))\b"),
     "fabricated proof / guarantee"),
    (re.compile(r"(?i)\b(clients? (say|love)|customers? (say|love)|trusted by \d+)\b"), "fabricated endorsement"),
    (re.compile(r"(?i)\b(fully|really|actually) (works|integrated|automated)\b"), "live-integration claim"),
]
_INTEGRATION = re.compile(r"(?i)\b(payments?|checkout|credit card|card on file|sms|text message|e-?mail|ai\b|assistant|gps|maps?|"
                          r"calendar sync|deposit|autoship|recurring billing)\b")
_QUALIFIER = re.compile(r"(?i)(mock|demo|no real|concept|static|preview|placeholder|illustrative|sample|scripted|synthetic|fictional)")


def claim_violations(text):
    return [label for rx, label in _CLAIMS if rx.search(text or "")]


def _all_text(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _all_text(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_text(v)


def validate_idea(idea):
    """Schema + honesty check → list of problems (empty = valid)."""
    errs = []
    if not isinstance(idea, dict):
        return ["idea must be an object"]
    for k, t in IDEA_SCHEMA["required"].items():
        if not isinstance(idea.get(k), t):
            errs.append("%s must be %s" % (k, t.__name__))
    for k, allowed in IDEA_SCHEMA["enums"].items():
        if idea.get(k) not in allowed:
            errs.append("%s not in %s" % (k, allowed))
    for part in ("design", "content"):
        d = idea.get(part) if isinstance(idea.get(part), dict) else {}
        for k, t in IDEA_SCHEMA[part].items():
            if not isinstance(d.get(k), t):
                errs.append("%s.%s must be %s" % (part, k, t.__name__))
    pal = (idea.get("design") or {}).get("palette") or []
    if not all(isinstance(h, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", h) for h in pal) or len(pal) < 4:
        errs.append("design.palette must be ≥4 hex colors")
    h = idea.get("estimatedDemoHours") or {}
    if not (isinstance(h.get("min"), int) and isinstance(h.get("max"), int) and 0 < h["min"] < h["max"]):
        errs.append("estimatedDemoHours must be ints with 0 < min < max")
    for k in ("features", "pagesOrScreens", "demoScope"):
        if isinstance(idea.get(k), list) and not idea[k]:
            errs.append(k + " must not be empty")
    if isinstance(idea.get("id"), str) and not ID_RE.match(idea["id"]):
        errs.append("id format")
    if isinstance(idea.get("title"), str) and idea.get("subindustry") and idea["subindustry"] not in idea["title"]:
        errs.append("title must name the subindustry")
    for t in _all_text({k: v for k, v in idea.items() if k not in ("guardrails",)}):
        for v in claim_violations(t):
            errs.append("claim: %s in %r" % (v, t[:80]))
    for f in idea.get("features") or []:
        if isinstance(f, str) and _INTEGRATION.search(f) and not _QUALIFIER.search(f):
            errs.append("integration feature lacks a mock/demo qualifier: %r" % f)
    if DISCLOSURE not in ((idea.get("content") or {}).get("caption") or ""):
        errs.append("caption missing disclosure")
    return errs


# --------------------------------------------------------------------------- content kit + brief
_NAMES = ["Avery R.", "Jordan P.", "Morgan L.", "Riley T.", "Casey M.", "Quinn S.", "Rowan K.", "Emerson D."]


def generate_kit(idea):
    """Deterministic content kit: 15–45 s storyboard (hook, screen beats, value prop, CTA),
    captions for Instagram/TikTok/LinkedIn, hashtags, thumbnail, voiceover, DM pitch, disclosure."""
    idx = catalog()["idx"]
    n, p = idx["niches"][idea["nicheId"]], idx["workflows"][idea["patternId"]]
    fmt, st, ang = idx["formats"][idea["formatId"]], idx["styles"][idea["styleId"]], idx["angles"][idea["angleId"]]
    ctx = story_ctx(n, p, fmt, st)
    rng = _rng("kit", idea["id"])
    total = idea.get("videoSeconds") or 30
    a_niche = ctx["a_niche"]
    sdiff = _low(_spoken(idea["differentiator"]))
    lines = {  # (on-screen overlay, voiceover) per beat kind — no stats, no testimonials, no promises
        "hook": (idea["content"]["hook"], idea["content"]["hook"]),
        "problem": ("The time sink", "If you run %s, you know this one: %s" % (a_niche, _low(p["problem"]))),
        "status_quo": ("Texts. Calls. Sticky notes.", "Right now this usually runs on texts, calls and memory."),
        "reveal": (_cap(idea["deliverableLabel"]), "Here's the concept: %s, styled %s." % (
            _lc(idea["deliverableLabel"]), _lc(idea["design"]["aesthetic"]))),
        "flow": (_cap(idea["features"][0]), "Watch the %s flow: %s." % (_lc(p["label"]), _low(idea["features"][0]))),
        "flow2": (_cap(idea["features"][1] if len(idea["features"]) > 1 else idea["features"][0]),
                  "Everything you see is demo data, so nothing here is a real customer."),
        "owner": ("Owner view", "And the owner's side: everything in one place."),
        "value": (_cap(p["outcome"]), "The point: %s." % p["outcome"]),
        "timelapse": ("Blank canvas → layout", "From a blank canvas to the layout, sped up."),
        "palette": (" ".join(idea["design"]["palette"][:3]), "%s palette; %s." % (
            idea["design"]["aesthetic"], _low(idea["design"]["typography"]))),
        "closeup": (_cap(idea["differentiator"]), "The signature moment: %s." % sdiff),
        "flowmap": ("Inquiry → done", "Inquiry to done, step by step: %s." % "; ".join(_low(x) for x in p["steps"][:3])),
        "messages": ("Message previews (mock)", "These are message previews — mock only, nothing actually sends."),
        "cta": ("Concept for %s · DM to adapt it" % a_niche, idea["content"]["cta"]),
    }
    beats = [(_fill(sh, ctx), kind) for sh, kind in ang["beats"]]
    body = [b for b in beats if b[1] not in ("hook", "cta")]
    if not any(k == "value" for _, k in body):
        body.append(("Value line on screen", "value"))
    hook_len, cta_len = 3, 4
    step = max(2, (total - hook_len - cta_len) // len(body))
    board, t = [], 0
    timeline = [beats[0]] + body + [beats[-1]]
    for k, (shot, kind) in enumerate(timeline):
        if k == 0:
            start, end = 0, hook_len
        elif k == len(timeline) - 1:
            start, end = total - cta_len, total
        else:
            start, end = t, (total - cta_len if k == len(timeline) - 2 else min(t + step, total - cta_len))
        overlay, vo = lines.get(kind, (_cap(shot), _cap(shot) + "."))
        board.append({"t": "%d–%ds" % (start, end), "beat": {"hook": "Hook", "cta": "CTA", "value": "Value prop"}.get(kind, "Screen"),
                      "shot": shot, "onScreen": overlay, "voiceover": vo})
        t = end
    vo = " ".join(b["voiceover"] for b in board)
    tags = idea["content"]["hashtags"]
    hook = idea["content"]["hook"]
    ig = "\n".join([hook, "", "%s for %s: %s." % (_cap(_lc(_spoken(idea["deliverableLabel"]))), a_niche, sdiff),
                    "Built with demo data — a concept, not a client project.", "", idea["content"]["cta"], "",
                    DISCLOSURE, "", " ".join(tags)])
    tt = "%s\n%s concept, %s. %s\n%s" % (hook, idea["subindustry"], _lc(idea["design"]["aesthetic"]),
                                         DISCLOSURE, " ".join(tags[:5]))
    li = "\n\n".join([
        "Concept study: %s for %s." % (_lc(_spoken(idea["deliverableLabel"])), a_niche),
        "The problem I designed around: %s" % idea["problem"],
        "What I built (demo data only): %s." % "; ".join(_low(f) for f in idea["features"][:3]),
        "The goal: %s." % p["outcome"],
        "If you run %s and want this adapted to what you already use, I'm happy to walk through it." % a_niche,
        DISCLOSURE])
    thumb = rng.choice([
        "%s, reimagined" % idea["subindustry"],
        "%s in 3 taps" % _cap(_lc(p["label"]).split(" & ")[0]),
        "%s concept" % _cap(_a(_lc(idea["design"]["aesthetic"]))),
    ])
    dm = ("Hi! I'm a local web designer. I made an independent concept showing how %s could handle %s "
          "(%s), alongside whatever you already use. Not a pitch in this message — happy to send the %d-second "
          "walkthrough if you're curious. (%s)") % (a_niche, _lc(p["label"]), sdiff,
                                                    total, DISCLOSURE)
    return {"ideaId": idea["id"], "generatedAt": _now_iso(), "durationSeconds": total, "storyboard": board,
            "captions": {"instagram": ig, "tiktok": tt, "linkedin": li}, "hashtags": tags,
            "thumbnailHeadline": thumb, "voiceover": vo, "dmPitch": dm, "cta": idea["content"]["cta"],
            "disclosure": DISCLOSURE}


def kit_violations(kit):
    errs = []
    for t in _all_text(kit):
        errs += claim_violations(t)
    if not 15 <= kit.get("durationSeconds", 0) <= 45:
        errs.append("duration outside 15–45 s")
    for k in ("instagram", "tiktok", "linkedin"):
        if DISCLOSURE not in kit["captions"].get(k, ""):
            errs.append("caption %s missing disclosure" % k)
    if DISCLOSURE not in kit.get("dmPitch", ""):
        errs.append("dm missing disclosure")
    return errs


def _sample_data(idea):
    idx = catalog()["idx"]
    n = idx["niches"][idea["nicheId"]]
    rng = _rng("sample", idea["id"])
    minors, medical = "minors" in n["sensitive"], "medical" in n["sensitive"] or "seniors" in n["sensitive"]
    names = (["Child A (fictional)", "Child B (fictional)", "Child C (fictional)", "Child D (fictional)"] if minors
             else ["Client 001 (synthetic)", "Client 002 (synthetic)", "Client 003 (synthetic)", "Client 004 (synthetic)"]
             if medical else rng.sample(_NAMES, 4))
    services = ["%s — %s" % (n["short"], tier) for tier in ("Essential", "Standard", "Premium")]
    statuses = ["requested", "confirmed", "in progress", "completed"]
    rows = []
    base = datetime(2026, 11, 2, 9, 0)
    for i, nm in enumerate(names):
        rows.append({"id": "rec_%03d" % (i + 1), "name": nm, "service": services[i % 3],
                     "when": (base + timedelta(days=i, hours=2 * i)).strftime("%Y-%m-%d %H:%M"),
                     "status": statuses[i % 4], "note": "sample record"})
    return {"business": "Sample %s (fictional)" % _lc(n["label"]), "services": services, "records": rows}


def build_brief(idea, kit=None):
    """Copy Build Brief: a Markdown prompt ready for Claude Code / Codex."""
    d = idea["design"]
    sample = json.dumps(_sample_data(idea), indent=2, ensure_ascii=False)
    lines = [
        "# Build brief — %s" % idea["subindustry"],
        "",
        "> **%s**" % DISCLOSURE,
        "",
        "**Concept:** %s" % idea["title"],
        "",
        idea["conceptSummary"],
        "",
        "## Concept/demo vs production",
        "This is a **portfolio concept/demo**, not a production system.",
        "",
        "| In this demo | Production would need (out of scope) |",
        "|---|---|",
        "| Synthetic sample data in a local JSON file | Real database, auth, backups |",
        "| Mock payment / message / AI / map / calendar UI | Real provider accounts, keys, compliance review |",
        "| Static deploy (any static host) | Monitoring, privacy policy, terms, accessibility audit |",
        "",
        "## Audience & problem",
        "- **Target customer:** %s" % idea["targetCustomer"],
        "- **Likely buyer:** %s" % idea["buyer"],
        "- **Pain point:** %s" % idea["problem"],
        "- **Market:** %s · **Deliverable:** %s (`%s`)" % (idea["market"].upper(), idea["deliverableLabel"], idea["deliverable"]),
        "- **Complexity:** %s · **Rough demo effort:** %d–%d h (rough estimate) · **Difficulty:** %s" % (
            idea["complexity"], idea["estimatedDemoHours"]["min"], idea["estimatedDemoHours"]["max"], idea["difficulty"]),
        "",
        "## Pages / screens",
    ]
    lines += ["- [ ] %s" % s for s in idea["pagesOrScreens"]]
    lines += ["", "## Feature set"] + ["- %s" % f for f in idea["features"]]
    lines += ["", "## Components",
              "- App shell (header/nav, footer with the disclosure line)",
              "- %s module (the signature moment: %s)" % (idea["patternLabel"], idea["differentiator"]),
              "- Cards, form controls with validation states, empty/loading/error states",
              "- Toast/confirmation pattern; modal or drawer for detail views", ""]
    lines += ["## Synthetic sample data", "Use exactly this shape (extend as needed; keep every name fictional):", "",
              "```json", sample, "```", ""]
    lines += ["## Visual design",
              "- **Aesthetic:** %s" % d["aesthetic"],
              "- **Palette:** %s" % ", ".join("`%s`" % h for h in d["palette"]),
              "- **Typography:** %s" % d["typography"],
              "- **Layout:** %s" % d["layout"],
              "- **Motion:** %s; respect `prefers-reduced-motion` (no animation when set)" % d["motion"],
              "- **Accessibility:** WCAG AA contrast, visible focus, keyboard-operable controls, labeled inputs", ""]
    lines += ["## Scope (in)"] + ["- %s" % s for s in idea["demoScope"]]
    lines += ["", "## Out of scope",
              "- Real payments, SMS/email sending, live AI, live maps/GPS, calendar sync, real accounts",
              "- Any real customer, patient, child or financial data", ""]
    lines += ["## Acceptance criteria",
              "- [ ] Every listed page/screen exists and is reachable from the nav",
              "- [ ] The %s flow works end to end on the sample data" % idea["patternLabel"].lower(),
              "- [ ] Mock integrations are visibly labeled as demo/mock",
              "- [ ] Layout works at 1440 px and 375 px wide; no horizontal scroll on mobile",
              "- [ ] Keyboard-only run-through succeeds; reduced-motion disables animation",
              "- [ ] Footer shows: \"%s\"" % DISCLOSURE,
              "- [ ] No testimonials, ratings, metrics or client logos anywhere", ""]
    lines += ["## Guardrails"] + ["- %s" % g for g in idea["guardrails"]]
    lines += ["", "## Content plan", "- **Hook:** %s" % idea["content"]["hook"]]
    lines += ["- **Storyboard (%ds):** %s" % (idea["videoSeconds"], " → ".join(idea["content"]["videoStoryboard"]))]
    if kit:
        lines += ["- **Thumbnail:** %s" % kit["thumbnailHeadline"]]
    lines += ["", "## Build notes",
              "- Static front end (plain HTML/CSS/JS or a single React app); no backend, no external APIs, no trackers.",
              "- Keep sample data in `data/sample.json`; never fetch real data.",
              "- Catalog provenance tags (see docs/ideawheel-research.md): %s" % ", ".join(idea["sourceTags"]), ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- store
def _empty():
    return {"version": 1, "ideas": {}, "events": [], "kits": {}, "prefs": dict(DEFAULT_FILTERS),
            "recent": [], "plan": {}, "metrics": {m: 0 for m in METRICS}, "metricLog": [], "spins": 0}


def _load():
    p = _path()
    if p.exists():
        try:
            d = json.loads(p.read_text())
            if isinstance(d, dict) and isinstance(d.get("ideas"), dict):
                base = _empty()
                base.update(d)
                for m in METRICS:
                    base["metrics"].setdefault(m, 0)
                return base
        except Exception:
            pass
    return _empty()


def _save(d):
    forge_atomic.atomic_write_json(_path(), d)


def _check_id(v):
    if not isinstance(v, str) or not ID_RE.match(v):
        raise ValueError("bad idea id")
    return v


def _slim(i, plan_by_id=None):
    return {"id": i["id"], "title": i["title"], "subindustry": i["subindustry"], "industry": i["industry"],
            "sectorId": i["sectorId"], "status": i["status"], "tags": i.get("tags") or [],
            "createdAt": i.get("createdAt"), "savedAt": i.get("savedAt"), "postedAt": i.get("postedAt"),
            "deliverableLabel": i["deliverableLabel"], "aesthetic": i["design"]["aesthetic"],
            "complexity": i["complexity"], "hasKit": bool(i.get("kitAt")),
            "plannedFor": (plan_by_id or {}).get(i["id"])}


def _event(d, idea_id, frm, to):
    d["events"].append({"ideaId": idea_id, "from": frm, "to": to, "at": _now_iso()})
    d["events"] = d["events"][-2000:]


def _prune(d):
    news = sorted((i for i in d["ideas"].values() if i["status"] == "new"),
                  key=lambda i: i.get("createdAt") or "", reverse=True)
    planned = set(d["plan"].values())
    for i in news[MAX_NEW_KEPT:]:
        if i["id"] not in planned:
            d["ideas"].pop(i["id"], None)
            d["kits"].pop(i["id"], None)


def _record(d, idea):
    idea["createdAt"] = idea.get("createdAt") or _now_iso()
    existing = d["ideas"].get(idea["id"])
    if existing:  # same seed + filters + history → same idea; keep its saved state
        return existing
    d["ideas"][idea["id"]] = idea
    return idea


def do_spin(filters=None, seed=None):
    seed = str(seed) if seed not in (None, "") else secrets.token_hex(4)
    if len(seed) > 40 or not re.fullmatch(r"[\w:\-]+", seed):
        raise ValueError("seed must be ≤40 letters, digits, _ - :")
    with _LOCK:
        d = _load()
        f = normalize_filters(filters if filters is not None else d.get("prefs"))
        recent_niches = [r["nicheId"] for r in d["recent"][-RECENT_NICHES:]]
        recent_combos = [r["key"] for r in d["recent"][-RECENT_COMBOS:]]
        res = spin(f, seed, recent_niches, recent_combos)
        d["prefs"] = f
        if res["ok"]:
            idea = _record(d, res["idea"])
            res["idea"] = idea
            i = idea
            d["recent"].append({"nicheId": i["nicheId"], "at": _now_iso(),
                                "key": combo_key(i["nicheId"], i["patternId"], i["formatId"], i["styleId"])})
            d["recent"] = d["recent"][-RECENT_COMBOS:]
            d["spins"] = d.get("spins", 0) + 1
            _prune(d)
        _save(d)
        return res


def do_restyle(idea_id):
    _check_id(idea_id)
    with _LOCK:
        d = _load()
        cur = d["ideas"].get(idea_id)
        if not cur:
            return {"error": "idea not found"}
        attempt = 1 + sum(1 for i in d["ideas"].values() if i.get("variantOf") == idea_id)
        new = restyle_idea(cur, attempt)
        new = _record(d, new)
        d["recent"].append({"nicheId": new["nicheId"], "at": _now_iso(),
                            "key": combo_key(new["nicheId"], new["patternId"], new["formatId"], new["styleId"])})
        d["recent"] = d["recent"][-RECENT_COMBOS:]
        _prune(d)
        _save(d)
        return {"ok": True, "idea": new}


def dedupe_key(i):
    return "|".join((i["nicheId"], i["patternId"], i["formatId"]))


def save_idea(idea_id, tags=None, force=False):
    _check_id(idea_id)
    tags = _clean_tags(tags) if tags is not None else None
    with _LOCK:
        d = _load()
        i = d["ideas"].get(idea_id)
        if not i:
            return {"error": "idea not found"}
        if i["status"] == "new" and not force:
            dup = [o for o in d["ideas"].values() if o["id"] != idea_id and dedupe_key(o) == dedupe_key(i)
                   and o["status"] in ("saved", "building", "ready", "posted")]
            if dup:
                return {"ok": False, "duplicate": True, "existing": _slim(dup[0]),
                        "message": "You already saved this niche + problem + deliverable. Save anyway?"}
        if i["status"] == "new":
            _event(d, idea_id, "new", "saved")
            i["status"] = "saved"
        i["savedAt"] = i.get("savedAt") or _now_iso()
        if tags is not None:
            i["tags"] = tags
        _save(d)
        return {"ok": True, "idea": i}


def _clean_tags(tags):
    if not isinstance(tags, list) or len(tags) > 8:
        raise ValueError("tags must be a list of up to 8")
    out = []
    for t in tags:
        t = (t or "").strip().lower() if isinstance(t, str) else ""
        if not TAG_RE.match(t):
            raise ValueError("tag must be 1–24 letters, digits, spaces or dashes")
        if t not in out:
            out.append(t)
    return out


def set_tags(idea_id, tags):
    _check_id(idea_id)
    tags = _clean_tags(tags)
    with _LOCK:
        d = _load()
        i = d["ideas"].get(idea_id)
        if not i:
            return {"error": "idea not found"}
        i["tags"] = tags
        _save(d)
        return {"ok": True, "idea": i}


def set_status(idea_id, status):
    """new→saved→building→ready→posted→archived; any step may jump forward or be undone, never back
    to 'new'. 'posted' is only ever set here, by the operator's tap — nothing auto-posts."""
    _check_id(idea_id)
    if status not in STATUSES or status == "new":
        raise ValueError("status must be one of saved, building, ready, posted, archived")
    with _LOCK:
        d = _load()
        i = d["ideas"].get(idea_id)
        if not i:
            return {"error": "idea not found"}
        frm = i["status"]
        if frm != status:
            _event(d, idea_id, frm, status)
            i["status"] = status
            i["savedAt"] = i.get("savedAt") or _now_iso()
            if status == "posted":
                i["postedAt"] = _now_iso()
            elif frm == "posted" and status != "archived":
                i["postedAt"] = None  # un-posting a mistake: the streak must not keep it
        _save(d)
        return {"ok": True, "idea": i}


def make_kit(idea_id):
    _check_id(idea_id)
    with _LOCK:
        d = _load()
        i = d["ideas"].get(idea_id)
        if not i:
            return {"error": "idea not found"}
        kit = generate_kit(i)
        d["kits"][idea_id] = kit
        i["kitAt"] = kit["generatedAt"]
        _save(d)
        return {"ok": True, "kit": kit, "idea": i}


def plan_day(date, idea_id=None):
    if not isinstance(date, str) or not DATE_RE.match(date):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        day = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("date must be a real calendar date") from None
    if abs((day - datetime.now()).days) > 366:
        raise ValueError("date must be within a year")
    if idea_id is not None:
        _check_id(idea_id)
    with _LOCK:
        d = _load()
        prev = d["plan"].get(date)
        if idea_id is None:
            d["plan"].pop(date, None)
        else:
            if idea_id not in d["ideas"]:
                return {"error": "idea not found"}
            for k in [k for k, v in d["plan"].items() if v == idea_id]:
                d["plan"].pop(k)  # one day per idea, one idea per day
            d["plan"][date] = idea_id
            i = d["ideas"][idea_id]
            if i["status"] == "new":
                _event(d, idea_id, "new", "saved")
                i["status"] = "saved"
                i["savedAt"] = _now_iso()
        _save(d)
        return {"ok": True, "date": date, "ideaId": idea_id, "replaced": prev if prev != idea_id else None}


def bump_metric(metric, delta):
    if metric not in METRICS:
        raise ValueError("metric must be one of " + ", ".join(METRICS))
    if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0 or abs(delta) > 5:
        raise ValueError("delta must be a non-zero integer between -5 and 5")
    with _LOCK:
        d = _load()
        d["metrics"][metric] = max(0, d["metrics"].get(metric, 0) + delta)
        d["metricLog"].append({"date": _today(), "metric": metric, "delta": delta, "at": _now_iso()})
        d["metricLog"] = d["metricLog"][-1000:]
        _save(d)
        return {"ok": True, "metrics": d["metrics"]}


def set_prefs(filters):
    f = normalize_filters(filters)
    with _LOCK:
        d = _load()
        d["prefs"] = f
        _save(d)
        return {"ok": True, "prefs": f}


def _posted_days(d):
    return sorted({(i.get("postedAt") or "")[:10] for i in d["ideas"].values()
                   if i["status"] in ("posted", "archived") and i.get("postedAt")})


def streak_view(d, today=None):
    """Honest streak: consecutive days with ≥1 idea the operator marked Posted. An unposted
    today doesn't break it (counts from yesterday) — no guilt timers, no fake progress."""
    today = today or _today()
    days = set(_posted_days(d))
    cur = datetime.strptime(today, "%Y-%m-%d")
    if today not in days:
        cur -= timedelta(days=1)
    n = 0
    while cur.strftime("%Y-%m-%d") in days:
        n += 1
        cur -= timedelta(days=1)
    t = datetime.strptime(today, "%Y-%m-%d")
    last7 = sum(1 for k in range(7) if (t - timedelta(days=k)).strftime("%Y-%m-%d") in days)
    return {"current": n, "postedToday": today in days, "daysPostedLast7": last7, "totalPostedDays": len(days)}


def state():
    with _LOCK:
        d = _load()
    today = _today()
    plan_by_id = {v: k for k, v in d["plan"].items()}
    ideas = d["ideas"]
    hist = sorted(ideas.values(), key=lambda i: i.get("createdAt") or "", reverse=True)
    planned_id = d["plan"].get(today)
    today_idea = ideas.get(planned_id) if planned_id else None
    suggestion = None
    if not today_idea:
        cands = sorted((i for i in ideas.values() if i["status"] in ("saved", "building", "ready")
                        and (plan_by_id.get(i["id"]) or "") <= today),
                       key=lambda i: (i["status"] != "ready", i["status"] != "building", i.get("savedAt") or ""))
        suggestion = cands[0] if cands else None
    upcoming = sorted((k, v) for k, v in d["plan"].items() if k >= today and v in ideas and ideas[v]["status"] != "posted")
    nxt = None
    if upcoming:
        nxt = {"date": upcoming[0][0], "idea": _slim(ideas[upcoming[0][1]], plan_by_id)}
    monday = datetime.strptime(today, "%Y-%m-%d") - timedelta(days=datetime.strptime(today, "%Y-%m-%d").weekday())
    posted_by_day = {}
    for i in ideas.values():
        if i.get("postedAt"):
            posted_by_day.setdefault(i["postedAt"][:10], []).append(i["id"])
    cal = []
    for k in range(14):
        day = (monday + timedelta(days=k)).strftime("%Y-%m-%d")
        pid = d["plan"].get(day)
        cal.append({"date": day, "isToday": day == today,
                    "planned": _slim(ideas[pid], plan_by_id) if pid in ideas else None,
                    "postedCount": len(posted_by_day.get(day, []))})
    counts = {s: 0 for s in STATUSES}
    for i in ideas.values():
        counts[i["status"]] += 1
    metrics = dict(d["metrics"])
    metrics["postsCompleted"] = sum(1 for i in ideas.values() if i.get("postedAt"))
    return {
        "ok": True, "today": today, "prefs": d["prefs"], "options": options(),
        "todayIdea": _slim(today_idea, plan_by_id) if today_idea else None,
        "todayPlanned": bool(today_idea),
        "suggestion": _slim(suggestion, plan_by_id) if suggestion else None,
        "nextPlanned": nxt, "streak": streak_view(d, today), "metrics": metrics,
        "counts": counts, "spins": d.get("spins", 0), "calendar": cal,
        "history": [_slim(i, plan_by_id) for i in hist[:40]],
        "disclosure": DISCLOSURE,
    }


def list_ideas(q="", status="", tag="", saved_only=False, limit=100):
    if status and status not in STATUSES:
        raise ValueError("bad status")
    q = (q or "").strip().lower()[:80]
    tag = (tag or "").strip().lower()[:24]
    with _LOCK:
        d = _load()
    plan_by_id = {v: k for k, v in d["plan"].items()}
    rows = []
    for i in d["ideas"].values():
        if saved_only and i["status"] == "new":
            continue
        if status and i["status"] != status:
            continue
        if tag and tag not in (i.get("tags") or []):
            continue
        if q and q not in " ".join([i["title"], i["subindustry"], i["industry"], " ".join(i.get("tags") or [])]).lower():
            continue
        rows.append(i)
    rows.sort(key=lambda i: i.get("savedAt") or i.get("createdAt") or "", reverse=True)
    all_tags = sorted({t for i in d["ideas"].values() for t in (i.get("tags") or [])})
    return {"ok": True, "ideas": [_slim(i, plan_by_id) for i in rows[:max(1, min(200, int(limit)))]],
            "total": len(rows), "tags": all_tags}


def get_idea(idea_id):
    _check_id(idea_id)
    with _LOCK:
        d = _load()
    i = d["ideas"].get(idea_id)
    if not i:
        return {"error": "idea not found"}
    plan_by_id = {v: k for k, v in d["plan"].items()}
    return {"ok": True, "idea": i, "kit": d["kits"].get(idea_id), "plannedFor": plan_by_id.get(idea_id),
            "events": [e for e in d["events"] if e["ideaId"] == idea_id][-20:]}


def get_brief(idea_id):
    r = get_idea(idea_id)
    if not r.get("ok"):
        return r
    return {"ok": True, "markdown": build_brief(r["idea"], r.get("kit")), "ideaId": idea_id}


# --------------------------------------------------------------------------- HTTP glue
def _q(q, k):
    v = (q or {}).get(k) or [""]
    return v[0] if isinstance(v, list) else v


def api_state(_q_):
    return state()


def api_ideas(q):
    try:
        return list_ideas(_q(q, "q"), _q(q, "status"), _q(q, "tag"), _q(q, "saved") in ("1", "true"),
                          int(_q(q, "limit") or 100))
    except ValueError as e:
        return {"error": str(e)}


def api_idea(q):
    try:
        return get_idea(_q(q, "id"))
    except ValueError as e:
        return {"error": str(e)}


def api_brief(q):
    try:
        return get_brief(_q(q, "id"))
    except ValueError as e:
        return {"error": str(e)}


GET_ROUTES = {"/api/ideawheel/state": api_state, "/api/ideawheel/ideas": api_ideas,
              "/api/ideawheel/idea": api_idea, "/api/ideawheel/brief": api_brief}
POST_PATHS = ("/api/ideawheel/spin", "/api/ideawheel/restyle", "/api/ideawheel/save",
              "/api/ideawheel/status", "/api/ideawheel/tags", "/api/ideawheel/kit",
              "/api/ideawheel/plan", "/api/ideawheel/metric", "/api/ideawheel/prefs")


def handle_post(path, body):
    """connector.do_POST delegates the /api/ideawheel/* allowlist here. Bad input → {"error"}."""
    b = body if isinstance(body, dict) else {}
    try:
        if path == "/api/ideawheel/spin":
            return do_spin(b.get("filters"), b.get("seed"))
        if path == "/api/ideawheel/restyle":
            return do_restyle(b.get("id"))
        if path == "/api/ideawheel/save":
            return save_idea(b.get("id"), b.get("tags"), b.get("force") is True)
        if path == "/api/ideawheel/status":
            return set_status(b.get("id"), b.get("status"))
        if path == "/api/ideawheel/tags":
            return set_tags(b.get("id"), b.get("tags"))
        if path == "/api/ideawheel/kit":
            return make_kit(b.get("id"))
        if path == "/api/ideawheel/plan":
            return plan_day(b.get("date"), b.get("id"))
        if path == "/api/ideawheel/metric":
            return bump_metric(b.get("metric"), b.get("delta"))
        if path == "/api/ideawheel/prefs":
            return set_prefs(b.get("filters"))
    except ValueError as e:
        return {"error": str(e)}
    return None


if __name__ == "__main__":
    import tempfile
    os.environ["FORGE_IDEAWHEEL_STATE"] = os.path.join(tempfile.mkdtemp(), "iw.json")
    problems = check_catalog()
    assert not problems, problems
    r = do_spin({}, "selfcheck")
    assert r["ok"] and r["segments"][r["landingIndex"]]["nicheId"] == r["idea"]["nicheId"], r
    assert not validate_idea(r["idea"]), validate_idea(r["idea"])
    print("ok —", r["idea"]["title"])
