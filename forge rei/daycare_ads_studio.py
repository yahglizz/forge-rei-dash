"""daycare_ads_studio.py — Nova's enrollment ad studio: idea → image → live PAUSED ad.

The Growth tab used to end at "here are 3 ideas" — good copy you then had to rebuild by
hand in Meta. This closes the loop: every idea Nova drafts is a COMPLETE ad package, it
persists so you can come back to it, and one tap builds the real campaign.

The pipeline:
    1. ideas()       — Nova drafts full packages: hook, headline, primary text, CTA,
                       targeting, daily budget, AND a production-ready image prompt
                       (gpt_image_2, per forge-daycare/skills/enrollment-ad-agent.md).
                       Persisted to marcus_state/daycare_ideas.json.
    2. attach_image() — the image step. If HIGGSFIELD_API_KEY is in daycare.env, Nova
                       generates it. Otherwise she hands you the prompt and takes a URL.
                       (See IMAGE NOTE below — this is a real, honest limitation.)
    3. create_ad()   — builds the campaign → adset → creative → ad on the daycare's REAL
                       Meta account, **PAUSED**. Returns the Meta link.

AUTONOMY (CLAUDE.md rule 2 + the runbook's own gate): building a PAUSED campaign is
internal and reversible — nothing serves, nothing spends, and deleting it costs nothing.
**Flipping it ACTIVE, changing budget, and scaling stay one-tap owner approvals**, and
this module never does them. create_ad() is hard-wired paused=True; there is no code path
here that activates a campaign or moves money.

IMAGE NOTE — why images aren't auto-generated yet:
The enrollment-ad-agent runbook calls `higgsfield:generate_image`, which is an **MCP tool**
— it runs inside a Claude session, not inside this connector. The box cannot reach it, and
there is no Higgsfield API key in daycare.env. So rather than pretend, this module is
explicit: `image_ready()` reports whether autonomous generation is actually wired, the UI
says so plainly, and the prompt is always produced so the image can be made in one paste.
Add HIGGSFIELD_API_KEY to daycare.env and generation turns on with no other change.
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import agency_ads
import agency_eco
import daycare_context

HERE = Path(__file__).resolve().parent
STORE = HERE / "marcus_state" / "daycare_ideas.json"
_LOCK = threading.Lock()

# The daycare's REAL Meta assets (business identifiers, not secrets — the runbook, §41-42).
AD_ACCOUNT = os.environ.get("DAYCARE_AD_ACCOUNT", "act_1175564690150627")
PAGE_ID = os.environ.get("DAYCARE_PAGE_ID", "939494549239823")
TOUR_LINK = os.environ.get("DAYCARE_TOUR_LINK", "https://atouchofblessing.com")

# Higgsfield defaults from the runbook's model table (§67-96).
HIGGSFIELD_MODEL = os.environ.get("HIGGSFIELD_MODEL", "gpt_image_2")
_HF_BASE = "https://platform.higgsfield.ai/v1"


# ── store ─────────────────────────────────────────────────────────────────────
def _load():
    try:
        if STORE.exists():
            return json.loads(STORE.read_text()) or []
    except Exception:
        pass
    return []


def _save(rows):
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        import forge_atomic
        forge_atomic.atomic_write_json(STORE, rows[-60:])
    except Exception:
        pass


def _daycare_env():
    """The daycare's own creds (never the agency's)."""
    try:
        import daycare_supabase
        return daycare_supabase._read_env() or {}
    except Exception:
        return {}


def _hf_key():
    creds = _daycare_env()
    return (os.environ.get("HIGGSFIELD_API_KEY")
            or creds.get("HIGGSFIELD_API_KEY") or "").strip()


def image_ready():
    """True only when Nova can ACTUALLY generate an image herself. Never claim otherwise —
    a UI that says 'generating' while nothing is wired is exactly the confident lie the
    creed forbids."""
    return bool(_hf_key())


def meta_ready():
    creds = _daycare_env()
    return bool((os.environ.get("META_ACCESS_TOKEN")
                 or creds.get("META_ACCESS_TOKEN") or "").strip())


def status():
    return {
        "imageReady": image_ready(),
        "metaReady": meta_ready(),
        "adAccount": AD_ACCOUNT,
        "pageId": PAGE_ID,
        "model": HIGGSFIELD_MODEL,
        "ideas": len(_load()),
    }


# ── 1. ideas — the full ad package ────────────────────────────────────────────
_PACKAGE_KEYS = ("title", "angle", "hook", "headline", "primaryText", "cta",
                 "creativeDirection", "imagePrompt", "targeting", "dailyBudget")


def _nova_system():
    """Nova's persona + the ad-package contract. She is the DAYCARE's ad agent — the
    Growth tab used to call this 'Eco' (the agency's strategist), which was just wrong."""
    return (
        "You are NOVA, the enrollment ad agent for A Touch of Blessings Learning Academy. "
        "You own the daycare's Meta ads: campaign angles, copy, and creative direction. "
        "Your single goal is to grow enrollment — every concept must plausibly get another "
        "family to book a tour.\n\n"
        "Output a JSON object with exactly three keys: 'best' (enrollment plays already "
        "working per the brief; may be empty), 'weak' (may be empty), and 'next' (array of "
        "exactly 3 NEW complete ad packages).\n\n"
        "Each 'next' item is a COMPLETE, BUILDABLE ad — not a sketch:\n"
        "{title, angle, hook, headline, primaryText, cta, creativeDirection, imagePrompt, "
        "targeting, dailyBudget}\n"
        "  • title: 'Concept N: AngleName'\n"
        "  • hook: the scroll-stopping first line\n"
        "  • headline: <=40 chars, Meta headline\n"
        "  • primaryText: the ad body — warm, specific, real trust signals (licensed, "
        "CCIS/subsidy accepted, ages 6 weeks-12 years, the real locations)\n"
        "  • cta: one of LEARN_MORE, SIGN_UP, BOOK_TRAVEL, GET_QUOTE, CONTACT_US\n"
        "  • imagePrompt: a PRODUCTION-READY image-generation prompt for gpt_image_2 — "
        "photoreal, warm, natural light, real childcare setting, diverse Philadelphia "
        "families, NO text baked into the image unless the angle needs an overlay (then "
        "specify the exact overlay text). Be concrete about subject, setting, lighting, "
        "composition, mood. This gets pasted straight into an image model.\n"
        "  • targeting: {age_min, age_max, radius_miles, interests:[...]} — parents near "
        "North Philadelphia\n"
        "  • dailyBudget: suggested daily spend in DOLLARS (integer, 10-50 range)\n\n"
        "Honor the brand voice (warm, trustworthy, never corporate). Respect the "
        "licensing/CCIS trust signals. NEVER promise capacity or a start date the brief "
        "flags as constrained, and never invent a price. Output ONLY valid JSON."
    )


def ideas(account=None):
    """Nova drafts 3 complete ad packages, grounded in the brief + the ad runbook.

    Persists them so they SIT in the Growth tab — you can come back tomorrow and build
    the one you liked instead of regenerating and losing it.
    """
    ctx = daycare_context.context_block() + daycare_context.ad_agent_block()
    try:
        import daycare_director
        pb = daycare_director.playbook_text(1500)
        if pb:
            ctx += ("\n\n=== SOLOMON'S ENROLLMENT PLAYBOOK (he owns enrollment — apply "
                    "his strategy) ===\n" + pb)
    except Exception:
        pass
    try:
        import agent_creed
        ctx = agent_creed.block("daycare") + ctx
    except Exception:
        pass

    key, _src = agency_eco._agency_key()
    if not key:
        return {"ok": False, "error": "No Anthropic key — add one to daycare.env."}

    import review_agent
    user = ("Draft 3 fresh, COMPLETE enrollment ad packages for A Touch of Blessings — "
            "each buildable as-is. Ground everything in the brief and the live ad spec "
            "above. Output ONLY the JSON object.\n\n" + ctx)
    try:
        raw = review_agent._claude(key, _nova_system(), user, max_tokens=3000)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Nova couldn't reach her brain: {e}"}

    try:
        parsed = json.loads(_strip(raw))
    except Exception:
        return {"ok": False, "error": "Nova returned malformed JSON — try again."}

    now = int(time.time() * 1000)
    fresh = []
    for i, item in enumerate(parsed.get("next") or []):
        if not isinstance(item, dict):
            continue
        row = {k: item.get(k) for k in _PACKAGE_KEYS}
        row["id"] = f"idea{now}_{i}"
        row["createdAt"] = now
        row["status"] = "draft"     # draft → image → built
        row["imageUrl"] = ""
        row["meta"] = {}            # filled by create_ad
        fresh.append(row)

    with _LOCK:
        rows = _load()
        rows.extend(fresh)
        _save(rows)

    return {"ok": True, "next": fresh,
            "best": parsed.get("best") or [], "weak": parsed.get("weak") or [],
            "competitor": parsed.get("competitor") or {},
            "context": daycare_context.status(), "status": status()}


def _strip(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def saved():
    """Every idea Nova has drafted — newest first. This is what makes them 'sit' in the
    section instead of vanishing on refresh."""
    return {"ideas": list(reversed(_load())), "status": status()}


def _find(idea_id):
    for r in _load():
        if r.get("id") == idea_id:
            return r
    return None


def _update(idea_id, patch):
    with _LOCK:
        rows = _load()
        hit = None
        for r in rows:
            if r.get("id") == idea_id:
                r.update(patch)
                hit = r
                break
        if hit:
            _save(rows)
    return hit


# ── 2. image ──────────────────────────────────────────────────────────────────
def attach_image(idea_id, image_url=""):
    """Give an idea its creative.

    If a URL is supplied (you generated it in Higgsfield / anywhere), we attach it.
    Otherwise, if HIGGSFIELD_API_KEY is wired, Nova generates it from her own imagePrompt.
    If neither — we say so plainly and hand back the prompt. We never fake an image.
    """
    idea = _find(idea_id)
    if not idea:
        return {"ok": False, "error": "unknown idea"}

    url = (image_url or "").strip()
    if url:
        if not url.lower().startswith(("http://", "https://")):
            return {"ok": False, "error": "That doesn't look like an image URL."}
        _update(idea_id, {"imageUrl": url, "status": "image"})
        return {"ok": True, "imageUrl": url, "source": "pasted"}

    if not image_ready():
        return {
            "ok": False,
            "needsKey": True,
            "prompt": idea.get("imagePrompt") or "",
            "model": HIGGSFIELD_MODEL,
            "error": ("Nova can't generate the image herself yet — no HIGGSFIELD_API_KEY "
                      "in daycare.env. Her prompt is ready: generate it in Higgsfield and "
                      "paste the URL back, or add the key and she'll do it in one tap."),
        }

    out = _higgsfield_image(idea.get("imagePrompt") or "")
    if not out.get("ok"):
        return out
    _update(idea_id, {"imageUrl": out["imageUrl"], "status": "image"})
    return {"ok": True, "imageUrl": out["imageUrl"], "source": "higgsfield"}


def _higgsfield_image(prompt):
    """Generate via the shared Higgsfield helper (same key, same account Eco uses).
    Only runs when a key is present; keeps Nova's high/2k quality settings."""
    import higgsfield_io
    return higgsfield_io.generate_image(
        prompt, key=_hf_key(), model=HIGGSFIELD_MODEL,
        extra={"quality": "high", "resolution": "2k"})


# ── 3. build the ad (PAUSED — never active, never spends) ──────────────────────
_CTAS = {"LEARN_MORE", "SIGN_UP", "BOOK_TRAVEL", "GET_QUOTE", "CONTACT_US"}


def create_ad(idea_id):
    """Build the real Meta campaign → adset → creative → ad, **PAUSED**.

    Paused is the whole point: nothing serves, nothing spends, and you can delete it for
    free. Going ACTIVE / changing budget stays your one tap in Meta (or a future approved
    action) — this function cannot activate anything, by construction.
    """
    idea = _find(idea_id)
    if not idea:
        return {"ok": False, "error": "unknown idea"}
    if not meta_ready():
        return {"ok": False, "error": "No META_ACCESS_TOKEN in daycare.env."}

    tgt = idea.get("targeting") or {}
    try:
        radius = int(tgt.get("radius_miles") or 10)
    except (TypeError, ValueError):
        radius = 10
    targeting = {
        "age_min": int(tgt.get("age_min") or 22),
        "age_max": int(tgt.get("age_max") or 45),
        "geo_locations": {"custom_locations": [{
            "latitude": 39.9790, "longitude": -75.1600,   # North Philadelphia
            "radius": max(1, min(radius, 50)), "distance_unit": "mile",
        }]},
    }
    try:
        budget_dollars = int(idea.get("dailyBudget") or 20)
    except (TypeError, ValueError):
        budget_dollars = 20
    budget_dollars = max(5, min(budget_dollars, 200))     # sane guardrail

    cta = (idea.get("cta") or "LEARN_MORE").upper()
    if cta not in _CTAS:
        cta = "LEARN_MORE"

    creative = {
        "message": idea.get("primaryText") or "",
        "link": TOUR_LINK,
        "headline": (idea.get("headline") or "")[:40],
        "description": idea.get("hook") or "",
        "call_to_action": cta,
    }
    if idea.get("imageUrl"):
        creative["picture"] = idea["imageUrl"]

    spec = {
        "name": f"[Nova] {idea.get('title') or 'Enrollment'}",
        "objective": "OUTCOME_LEADS",
        "adset_name": f"{idea.get('angle') or 'Enrollment'} — Set 1",
        "targeting": targeting,
        "creative": creative,
        "budget_daily": budget_dollars * 100,     # Meta wants minor units (cents)
        "ad_account_id": AD_ACCOUNT,
        "page_id": PAGE_ID,
    }

    # Meta call runs with the DAYCARE's creds, never the agency's — reusing the locked
    # env-swap daycare_growth already ships (one implementation, not two).
    import daycare_growth
    with daycare_growth._ENV_LOCK, daycare_growth._scoped_env(("META_ACCESS_TOKEN",)):
        out = agency_ads.create_ad(spec, paused=True)   # hard-wired paused. Never active.

    if out.get("ok"):
        _update(idea_id, {"status": "built", "meta": {
            "detail": out.get("detail"), "url": out.get("url"),
            "builtAt": int(time.time() * 1000), "paused": True,
            "dailyBudget": budget_dollars,
        }})
        try:
            import agent_bus
            agent_bus.send("nova", "all", "status",
                           f"Built PAUSED campaign '{idea.get('title')}' "
                           f"(${budget_dollars}/day when you activate it).",
                           {"ideaId": idea_id})
        except Exception:
            pass
    return {**out, "paused": True, "dailyBudget": budget_dollars}


def discard(idea_id):
    with _LOCK:
        rows = [r for r in _load() if r.get("id") != idea_id]
        _save(rows)
    return {"ok": True}
