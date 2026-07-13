"""agency_eco.py — "Eco", the Forge AI Agency ADS-STRATEGY agent.

Eco reviews the (mock) Meta Ads analytics for an account and produces:
  - the best-performing ads (what to scale)
  - the weak ads (what to pause)
  - the next 3 ads to create — each with a hook, headline, primary text, CTA,
    and creative direction
  - competitor research (real Claude call; placeholder fallback if no key)

M1: recommendations()/generate() now call Claude grounded on live analytics
    numbers + Eco's brain playbook (mtime-cached). Template fallback on
    no-key or any Claude failure.

M3: approve_ad(rec_id, concept_index) builds a Meta ad spec from an approved
    concept and calls agency_ads.create_ad(spec, paused=True). Returns
    {ok, detail, url?}. No key / failure → {ok:False, detail:"queued,..."}.

Store: marcus_state/agency_eco.json (generated rec sets, for the Approval Center)
"""
import forge_atomic
import json
import os
import threading
import time
from pathlib import Path

import agency_ads
import agency_approvals_io
import review_agent  # _claude(), MODEL, _api_key()

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_eco.json"
_LOCK = threading.Lock()

# --- agency key (mirrors agency_agents._agency_key) --------------------------
AGENCY_ENV_CANDIDATES = [
    HERE.parent / "forge-agency" / "config" / "agency.env",
    Path.home() / "Desktop" / "forge-agency" / "config" / "agency.env",
]

SEED_SKILLS_DIRS = [
    HERE.parent / "forge-agency" / "skills",
    Path.home() / "Desktop" / "forge-agency" / "skills",
]

_SK_CACHE = {}  # agent_id -> (mtime_sig, text)


def _agency_key():
    """Return (key, source). Agency env wins; falls back to wholesale key."""
    k = os.environ.get("AGENCY_ANTHROPIC_API_KEY")
    if k:
        return k, "agency-env"
    for p in AGENCY_ENV_CANDIDATES:
        if p.exists():
            for line in p.read_text().splitlines():
                s = line.strip()
                if s.startswith("ANTHROPIC_API_KEY=") and not s.startswith("#"):
                    v = s.split("=", 1)[1].strip()
                    if v and not v.startswith("sk-ant-..."):
                        return v, "agency"
    wholesale = review_agent._api_key()
    if wholesale:
        return wholesale, "wholesale"
    return None, None


# --- brain playbook (mtime-cached, mirrors agency_agents._load_skills) --------
def _load_eco_skills():
    """Eco's playbook = seed file + brain-vault version. mtime-cached."""
    try:
        import brain_io
        parts, sig = [], []
        srcs = []
        for d in SEED_SKILLS_DIRS:
            p = d / "eco-playbook.md"
            if p.is_file():
                srcs.append(p)
                break
        srcs.append(brain_io.VAULT / "Skills" / "eco-playbook.md")
        for p in srcs:
            if p.is_file():
                parts.append(p.read_text(errors="ignore"))
                sig.append(p.stat().st_mtime)
        sig = tuple(sig)
        cached = _SK_CACHE.get("eco")
        if not cached or cached[0] != sig:
            text = "\n\n".join(parts)
            _SK_CACHE["eco"] = (sig, text)
            return text
        return cached[1]
    except Exception:
        cached = _SK_CACHE.get("eco")
        return cached[1] if cached else ""


# --- template fallback (original _ANGLE_LIBRARY logic, unchanged) -------------
_ANGLE_LIBRARY = [
    {"angle": "Transformation UGC",
     "headline": "Real results, real members",
     "primaryText": "Stop scrolling. {client} members are getting results — "
                    "here's proof. Tap to start your first week free.",
     "cta": "Sign Up",
     "creativeDirection": "15s vertical UGC reel, member tells their story, "
                          "before/after on screen, captions burned in."},
    {"angle": "Problem → Solution",
     "headline": "Tired of {pain}?",
     "primaryText": "You don't need {pain}. {client} makes it simple — book in "
                    "60 seconds and we handle the rest.",
     "cta": "Book Now",
     "creativeDirection": "Punchy hook on a bold text card (first 3s), then "
                          "fast cuts of the offer. Mobile-first 4:5."},
    {"angle": "Social Proof / Reviews",
     "headline": "Rated 5★ by local clients",
     "primaryText": "{count}+ happy clients can't be wrong. See why {client} is "
                    "the local favorite.",
     "cta": "Learn More",
     "creativeDirection": "Carousel of 3 real review screenshots + a clean "
                          "brand end-card. Static, fast to ship."},
    {"angle": "Offer / Urgency",
     "headline": "This week only",
     "primaryText": "{offer} — limited spots. Claim yours before it's gone.",
     "cta": "Get Offer",
     "creativeDirection": "Single bold image, offer front-and-center, countdown "
                          "vibe. A/B the offer wording."},
]


def _template_build(a, top, weak, acct):
    """Original rule-based concept generation. Used as fallback on Claude failure."""
    win_hooks = [t["hook"] for t in top if t.get("hook")]
    pain = "wasted ad spend"
    offer = "First week free"
    count = max(50, int(a["totals"].get("leads", 0)) + 40)
    client_name = acct["clientName"]

    def fill(s):
        return (s.replace("{client}", client_name)
                 .replace("{pain}", pain).replace("{offer}", offer)
                 .replace("{count}", str(count)))

    chosen = _ANGLE_LIBRARY[:3]
    nxt = []
    for i, ang in enumerate(chosen):
        hook = (win_hooks[i] if i < len(win_hooks)
                else f"{client_name} — {ang['angle'].lower()}")
        nxt.append({
            "title": f"Concept {i + 1}: {ang['angle']}",
            "angle": ang["angle"],
            "hook": hook,
            "headline": fill(ang["headline"]),
            "primaryText": fill(ang["primaryText"]),
            "cta": ang["cta"],
            "creativeDirection": fill(ang["creativeDirection"]),
        })
    return nxt


def _format_analytics_block(a):
    """Compact analytics summary for the Claude prompt."""
    t = a["totals"]
    lines = [
        f"Client: {a['account']['clientName']} | Account: {a['account']['id']}",
        f"Totals ({a['days']}d): spend ${t['spend']}, impressions {t['impressions']}, "
        f"clicks {t['clicks']}, leads {t['leads']}, conversions {t['conversions']}, "
        f"CTR {t['ctr']}%, CPC ${t['cpc']}, CPL ${t['cpl']}, ROAS {t['roas']}x",
        "",
        "TOP ADS (best performers — scale these):",
    ]
    for ad in a["topAds"]:
        lines.append(
            f"  [{ad['name']}] ROAS {ad['roas']}x | {ad['leads']} leads | "
            f"CPL ${ad['cpl']} | hook: \"{ad.get('hook', '')}\"")
    lines.append("")
    lines.append("WEAK ADS (low performers — pause or rework):")
    for ad in a["weakAds"]:
        lines.append(
            f"  [{ad['name']}] ROAS {ad['roas']}x | {ad['leads']} leads | "
            f"CPL ${ad.get('cpl', 0)} | hook: \"{ad.get('hook', '')}\"")
    lines.append("")
    lines.append("CAMPAIGNS:")
    for c in a["campaigns"]:
        lines.append(
            f"  [{c['name']}] {c['objective']} | spend ${c['spend']} | "
            f"leads {c['leads']} | ROAS {c['roas']}x")
    return "\n".join(lines)


# --- M1: real Claude recommendations -----------------------------------------
def _claude_recommendations(a, key, extra_context=""):
    """Call Claude to generate best/weak analysis + 3 new concepts.

    Returns (best_list, weak_list, next_list) using the same keys as _build().
    Raises on failure so caller can fall back to template.

    ``extra_context`` (optional) is injected verbatim ahead of the playbook — the
    daycare passes its business brief (``daycare_context.context_block()``) here so
    Eco reasons on-message. Empty for the agency, so behaviour is unchanged.
    """
    playbook = _load_eco_skills()
    playbook_block = (
        "\n\n=== ECO PLAYBOOK (apply these rules) ===\n" + playbook[:2500]
        if playbook else ""
    )

    analytics_block = _format_analytics_block(a)
    client_name = a["account"]["clientName"]

    system = (
        "You are Eco, the ads strategist for Forge AI Agency. "
        "Analyze Meta Ads performance data and output a JSON object with exactly "
        "three keys: 'best' (array), 'weak' (array), 'next' (array of 3 concepts). "
        "Each 'best' item: {name, roas, leads, cpl, hook, why}. "
        "Each 'weak' item: {name, roas, leads, cpl, why}. "
        "Each 'next' item: {title, angle, hook, headline, primaryText, cta, creativeDirection}. "
        "title format: 'Concept N: AngleName'. "
        "Ground every recommendation in the actual numbers. Be specific and numeric. "
        "Output ONLY valid JSON — no markdown, no commentary."
        + (extra_context or "")
        + playbook_block
    )

    user = (
        f"Analyze this Meta Ads account and generate recommendations:\n\n"
        f"{analytics_block}\n\n"
        f"Client context: {client_name}. "
        "Return JSON with keys: best (array, top performers + why to scale), "
        "weak (array, underperformers + why to pause/rework), "
        "next (array of exactly 3 new ad concepts grounded in what is winning)."
    )

    raw = review_agent._claude(key, system, user, max_tokens=3200)
    # Strip possible markdown code fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    parsed = json.loads(raw)

    best = parsed.get("best", [])
    weak = parsed.get("weak", [])
    nxt_raw = parsed.get("next", [])

    # Normalise concept shape to match existing keys exactly
    nxt = []
    for i, c in enumerate(nxt_raw[:3]):
        nxt.append({
            "title": c.get("title", f"Concept {i + 1}"),
            "angle": c.get("angle", ""),
            "hook": c.get("hook", ""),
            "headline": c.get("headline", ""),
            "primaryText": c.get("primaryText", ""),
            "cta": c.get("cta", "Learn More"),
            "creativeDirection": c.get("creativeDirection", ""),
        })

    return best, weak, nxt


# --- M1: real Claude competitor research -------------------------------------
def _claude_competitor_research(a, key, extra_context=""):
    """Call Claude to generate competitor analysis for the account's niche.

    Returns a competitor dict replacing the old placeholder block.
    Raises on failure. ``extra_context`` injects the daycare brief when set.
    """
    playbook = _load_eco_skills()
    playbook_block = (
        "\n\n=== ECO PLAYBOOK ===\n" + playbook[:1500] if playbook else ""
    )
    client_name = a["account"]["clientName"]
    analytics_block = _format_analytics_block(a)

    # Infer niche from client name + top ad hooks for better context
    top_hooks = [ad.get("hook", "") for ad in a["topAds"] if ad.get("hook")]

    system = (
        "You are Eco, the ads strategist for Forge AI Agency. "
        "Produce a competitor analysis for a Meta advertiser in JSON format with keys: "
        "status (string: 'analyzed'), niche (string), "
        "competitorAngles (array of {angle, description, threat}), "
        "positioningGaps (array of strings — opportunities competitors aren't exploiting), "
        "recommendedDifferentiators (array of strings), "
        "summary (2-3 sentences). "
        "Base analysis on the niche + winning hooks provided. "
        "Output ONLY valid JSON."
        + (extra_context or "")
        + playbook_block
    )

    hooks_str = "; ".join(top_hooks[:3]) if top_hooks else "not available"
    user = (
        f"Client: {client_name}\n"
        f"Current winning ad hooks: {hooks_str}\n"
        f"Analytics context:\n{analytics_block[:800]}\n\n"
        "Analyze the competitive landscape for this business niche. "
        "Identify the common competitor ad angles, gaps in the market they're missing, "
        "and specific differentiators {client_name} should lean into."
    ).replace("{client_name}", client_name)

    raw = review_agent._claude(key, system, user, max_tokens=1600)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    parsed = json.loads(raw)
    parsed.setdefault("status", "analyzed")
    return parsed


# --- core build (real Claude + template fallback) ----------------------------
def _build(account=None, client=None, use_ai=True, include_competitor_ai=False,
           extra_context=""):
    """Strategy pass.

    Dashboard reads must stay fast: they can render the deterministic template
    view. Explicit user actions can opt into Claude-backed strategy generation.

    ``extra_context`` flows into the Claude prompts (daycare business brief); the
    agency passes "" so its output is byte-for-byte what it was before.
    """
    a = agency_ads.analytics(account=account, client=client)
    acct = a["account"]
    top = a["topAds"]
    weak = a["weakAds"]

    key, _src = _agency_key()

    # --- M1: real Claude recommendations (with fallback) ---------------------
    best_list = []
    weak_list = []
    next_list = []
    used_claude_recs = False

    if use_ai and key:
        try:
            best_list, weak_list, next_list = _claude_recommendations(a, key, extra_context)
            used_claude_recs = True
        except Exception:
            pass  # fall through to template

    if not used_claude_recs:
        # Template fallback: shape identical to the Claude path
        best_list = [
            {"name": t["name"], "roas": t["roas"], "leads": t["leads"],
             "cpl": t["cpl"], "hook": t.get("hook", ""),
             "why": (f"ROAS {t['roas']}x, {t['leads']} leads at "
                     f"${t['cpl']} CPL — scale this.")}
            for t in top
        ]
        weak_list = [
            {"name": w["name"], "roas": w["roas"], "leads": w["leads"],
             "cpl": w["cpl"],
             "why": (f"ROAS {w['roas']}x, only {w['leads']} leads"
                     + (f" at ${w['cpl']} CPL" if w["cpl"] else "")
                     + " — pause or rework.")}
            for w in weak
        ]
        next_list = _template_build(a, top, weak, acct)

    # --- M1: real competitor research (with fallback) -------------------------
    competitor = {
        "status": "placeholder",
        "todo": ("Wire competitor research: pull rival ads from the Meta Ad "
                 "Library (ads_library_search) + summarize angles. Not live yet."),
        "note": ("Eco will compare your winning hooks against competitors' "
                 "active ads here."),
    }

    if include_competitor_ai and key:
        try:
            competitor = _claude_competitor_research(a, key, extra_context)
        except Exception:
            pass  # keep placeholder on failure

    return {
        "account": acct,
        "best": best_list,
        "weak": weak_list,
        "next": next_list,
        "competitor": competitor,
        "_source": "claude" if used_claude_recs else "template",
    }


# --- persistence helpers (unchanged) -----------------------------------------
def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("sets"), list):
                return d
        except Exception:
            pass
    return {"sets": [], "seq": 0}


def _save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    forge_atomic.atomic_write_json(STATE, d)


# --- public API (same shape as before) ----------------------------------------
def recommendations(account=None, client=None, extra_context=""):
    """Read-only strategy view (no persistence, no approval push).

    Keep this endpoint bounded. The Eco tab calls it while rendering, so the
    heavy Claude path belongs behind the explicit generate/research buttons.
    """
    return {"ok": True, **_build(account=account, client=client, use_ai=False,
                                 extra_context=extra_context)}


def generate(account=None, client=None, extra_context="", include_competitor_ai=False):
    """Generate a rec set, persist it, and push it to the Approval Center."""
    built = _build(account=account, client=client, use_ai=True,
                   include_competitor_ai=include_competitor_ai,
                   extra_context=extra_context)
    with _LOCK:
        d = _load()
        now = int(time.time() * 1000)
        d["seq"] = d.get("seq", 0) + 1
        rec = {"id": f"eco{d['seq']}_{now}", "createdAt": now,
               "status": "draft", **built}
        d.setdefault("sets", []).append(rec)
        _save(d)

    acct = built["account"]
    agency_approvals_io.add(
        "eco", rec["id"],
        f"Eco: {len(built['next'])} new ad concepts — {acct['clientName']}",
        f"Scale {len(built['best'])} winners, pause {len(built['weak'])} weak, "
        f"launch {len(built['next'])} new concepts.",
        client=acct["clientName"], risk="medium",
        payload={"next": [n["title"] for n in built["next"]],
                 "topAngle": built["next"][0]["angle"] if built["next"] else ""})
    return {"ok": True, "rec": rec}


def list_sets():
    with _LOCK:
        d = _load()
        return {"sets": sorted(d.get("sets", []),
                               key=lambda x: x.get("createdAt") or 0, reverse=True)}


def decision(rec_id, action):
    state_map = {"approve": "approved", "revise": "revision", "reject": "rejected"}
    if action not in state_map:
        return {"error": f"action must be one of {list(state_map)}"}
    with _LOCK:
        d = _load()
        r = next((x for x in d.get("sets", []) if x.get("id") == rec_id), None)
        if not r:
            return {"error": "rec set not found"}
        r["status"] = state_map[action]
        _save(d)
    # FUTURE: on "approve", Eco creates the ads via the Meta Ads MCP (paused).
    return {"ok": True, "rec": r}


# --- M3: approve → Meta ad spec creation (paused) ----------------------------
def _release_concept(rec_id, idx):
    """Release an idempotency claim on (rec_id, concept idx) so a retry is possible."""
    try:
        with _LOCK:
            d = _load()
            r = next((x for x in d.get("sets", []) if x.get("id") == rec_id), None)
            if r is not None and idx in r.get("appliedConcepts", []):
                r["appliedConcepts"] = [i for i in r["appliedConcepts"] if i != idx]
                _save(d)
    except Exception:
        pass


def approve_ad(rec_id, concept_index=0):
    """Build a Meta ad spec from an approved concept and call agency_ads.create_ad.

    The ad is created PAUSED (never auto-spends). Operator un-pauses in Meta.
    Writes a brain note + agent_bus message on success.

    Returns {ok, detail, url?} or {ok:False, detail:'queued, needs META_ACCESS_TOKEN'}.
    """
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        return {"ok": False, "detail": "queued, needs META_ACCESS_TOKEN"}

    # Load the rec set
    with _LOCK:
        d = _load()
        r = next((x for x in d.get("sets", []) if x.get("id") == rec_id), None)

    if not r:
        return {"ok": False, "detail": f"rec set {rec_id!r} not found"}

    nxt = r.get("next", [])
    if not nxt:
        return {"ok": False, "detail": "rec set has no concepts"}

    idx = max(0, min(concept_index, len(nxt) - 1))
    concept = nxt[idx]
    acct = r.get("account", {})

    # Idempotency guard: two routes (Approvals Center + Eco tab) can both approve
    # the same concept. Atomically claim it so the Meta ad is created once.
    # Released on failure so the operator can retry after fixing the key/account.
    with _LOCK:
        d = _load()
        r2 = next((x for x in d.get("sets", []) if x.get("id") == rec_id), None)
        if r2 is not None:
            applied = r2.setdefault("appliedConcepts", [])
            if idx in applied:
                return {"ok": True, "detail": "ad already created for this concept (idempotent)"}
            applied.append(idx)
            _save(d)

    spec = {
        "account_id": acct.get("id", ""),
        "name": concept.get("title", f"Eco Concept {idx + 1}"),
        "angle": concept.get("angle", ""),
        "hook": concept.get("hook", ""),
        "headline": concept.get("headline", ""),
        "primary_text": concept.get("primaryText", ""),
        "cta": concept.get("cta", "Learn More"),
        "creative_direction": concept.get("creativeDirection", ""),
        "client_name": acct.get("clientName", ""),
        "rec_id": rec_id,
        "concept_index": idx,
        "created_by": "eco",
    }

    try:
        result = agency_ads.create_ad(spec, paused=True)
    except Exception as e:
        _release_concept(rec_id, idx)
        return {"ok": False, "detail": f"agency_ads.create_ad failed: {e}"}

    if not result.get("ok"):
        _release_concept(rec_id, idx)
        return {"ok": False, "detail": result.get("detail", "create_ad returned not-ok")}

    # Write brain note on success
    _write_brain_note(acct, concept, result)

    # Broadcast on agent bus
    _broadcast_ad_created(acct, concept, result)

    out = {"ok": True, "detail": f"Ad created (paused): {concept.get('title')}"}
    if result.get("url"):
        out["url"] = result["url"]
    if result.get("adId"):
        out["adId"] = result["adId"]
    return out


def competitor_research(client=None, extra_context=""):
    """Public wrapper for competitor analysis — called by the /api/agency/eco/competitor route.

    Builds a minimal analytics context (using the mock/live analytics for the
    given client), then delegates to _claude_competitor_research if a key is
    present. Falls back to a structured placeholder if no key or Claude fails.

    Returns a dict that CompResearchPanel reads. Relevant keys the UI uses:
      status ("placeholder"|"analyzed"|"error")
      competitors  — list of strings or competitor objects (UI renders both)
      competitorAngles, positioningGaps, recommendedDifferentiators, summary
    Never raises.
    """
    try:
        a = agency_ads.analytics(client=client)
        key, _src = _agency_key()
        if key:
            try:
                result = _claude_competitor_research(a, key, extra_context)
                return result
            except Exception:
                pass  # fall through to placeholder

        # Placeholder fallback — key not present or Claude call failed.
        client_name = a["account"]["clientName"] if a.get("account") else (client or "your client")
        return {
            "status": "placeholder",
            "competitors": [],
            "competitorAngles": [],
            "positioningGaps": [],
            "recommendedDifferentiators": [],
            "summary": (
                f"Competitor research for {client_name} is ready to run. "
                "Add an Anthropic API key (ANTHROPIC_API_KEY in agency.env) "
                "and click 'Run competitor research' to generate a live analysis."
            ),
            "todo": (
                "Wire competitor research: Claude analyzes the niche + active "
                "competitor angles based on your ad account context. Requires ANTHROPIC_API_KEY."
            ),
        }
    except Exception as exc:
        return {
            "status": "error",
            "competitors": [],
            "summary": f"Competitor research failed: {exc}",
        }


def _write_brain_note(acct, concept, result):
    """Write a brain note recording the approved ad creation."""
    try:
        import brain_io
        stamp = time.strftime("%Y-%m-%d %H:%M")
        client = acct.get("clientName", "unknown")
        title = concept.get("title", "Ad")
        rel = f"Reports/eco-ad-created-{time.strftime('%Y%m%d-%H%M%S')}.md"
        content = (
            f"---\nagent: eco\ncreated: {stamp}\nclient: {client}\n---\n\n"
            f"# Ad Created (Paused): {title}\n\n"
            f"**Client:** {client}  \n"
            f"**Account:** {acct.get('id', '')}  \n"
            f"**Hook:** {concept.get('hook', '')}  \n"
            f"**Headline:** {concept.get('headline', '')}  \n"
            f"**CTA:** {concept.get('cta', '')}  \n"
            f"**Creative:** {concept.get('creativeDirection', '')}  \n\n"
            f"Ad created PAUSED — operator un-pauses in Meta when ready.\n"
        )
        if result.get("url"):
            content += f"\n[View in Meta Ads Manager]({result['url']})\n"
        brain_io.write_note(rel, content, reason=f"Eco created ad: {title}")
    except Exception:
        pass


def _broadcast_ad_created(acct, concept, result):
    """Send agent bus message on successful ad creation."""
    try:
        import agent_bus
        client = acct.get("clientName", "unknown")
        title = concept.get("title", "Ad")
        agent_bus.send(
            "eco", "all", "status",
            f"Eco created ad (paused): {title} for {client}",
            {"recId": concept.get("rec_id"), "adId": result.get("adId"),
             "client": client, "title": title})
    except Exception:
        pass
