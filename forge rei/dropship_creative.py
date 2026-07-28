#!/usr/bin/env python3
"""dropship_creative.py — closes the loop from decision packet to actual creative.

The packet already ends with a copy plan: the angle to run, what to change, and a
Higgsfield prompt written in the winning creative's STYLE. Until now nothing
consumed that prompt — the operator copied it somewhere by hand. This module
takes it and generates.

Reuses ``higgsfield_io`` (already shipped, already generating for the daycare) —
no second Higgsfield client. Key resolution is that module's: env →
passed creds → a scan of daycare.env / agency.env / dropship.env, so an existing
paste anywhere already works here.

**Autonomy.** Generating an image is INTERNAL and REVERSIBLE — a file, deletable,
that nobody outside sees. Same class as the daycare's creative builds, which run
without a gate while activating a campaign or changing a budget stays a one-tap
approval. So generation is allowed; **launching** is not, and nothing in this
module can launch, boost, publish, or spend.

**Two hard lines, enforced here rather than trusted to a prompt:**

1. *Never reproduce a competitor's asset.* Copying the angle, trigger, structure
   and offer shape is legitimate competitive practice. Copying their image or
   video is IP infringement and a Meta rejection trigger. ``_reject_asset_reuse``
   refuses a prompt that reads as a description of someone else's specific
   creative, or that names a protected brand.
2. *AI imagery must be disclosed.* Meta requires it, and Etsy requires disclosure
   in the listing description. Every asset this module returns carries
   ``disclosure`` and ``aiGenerated: True`` so the requirement travels with the
   file instead of living in someone's memory.
"""
from __future__ import annotations

import re
import time

import research_guard as guard

SOURCE = "Higgsfield"

# Meta requires disclosure of AI-generated imagery; Etsy requires it in the
# listing description. Carried on every asset so it cannot be forgotten downstream.
DISCLOSURE = ("AI-generated imagery — disclose on Meta (required) and in any Etsy "
              "listing description (required by Etsy's Creativity Standards).")

_BRAND_RE = re.compile(
    r"\b(nike|adidas|apple|disney|marvel|pokemon|louis vuitton|gucci|chanel|"
    r"rolex|supreme|lego|nintendo|sanrio|hello kitty|stanley|dyson|yeti|"
    r"harry potter|star wars|nfl|nba|fifa)\b", re.IGNORECASE)

# Phrasing that means "reproduce THEIR asset" rather than "make one in this style".
_ASSET_REUSE_RE = re.compile(
    r"\b(recreate|replicate|copy|clone|reproduce|duplicate|same as|identical to|"
    r"exact(ly)? (like|as)|rip off|remake)\b.{0,40}\b(their|his|her|its|the "
    r"competitor|this ad|that ad|the ad|the video|the image|the creative)\b",
    re.IGNORECASE)


def configured() -> bool:
    try:
        import higgsfield_io
        return bool(higgsfield_io.ready())
    except Exception:  # noqa: BLE001
        return False


def _mock(extra: dict | None = None) -> dict:
    out = {"ok": True, "configured": False, "source": SOURCE,
           "detail": ("Add HIGGSFIELD_API_KEY + HIGGSFIELD_API_SECRET to dropship.env "
                      "(or reuse the existing paste in daycare.env / agency.env).")}
    if extra:
        out.update(extra)
    return out


def _reject_asset_reuse(prompt: str) -> str:
    """Returns a refusal reason, or "" when the prompt is clean."""
    text = str(prompt or "")
    if not text.strip():
        return "empty prompt"
    hit = _ASSET_REUSE_RE.search(text)
    if hit:
        return (f"Prompt asks to reproduce a competitor's asset ('{hit.group(0)}'). Copy the "
                f"angle and structure, never the asset — that is IP infringement and a Meta "
                f"rejection trigger. Rewrite it as an original scene in the same style.")
    hit = _BRAND_RE.search(text)
    if hit:
        return (f"Prompt names a protected brand ('{hit.group(0)}'). Meta rejects the creative "
                f"and the IP holder can take the listing down. Remove the brand.")
    return ""


def generate(prompt: str, count: int = 1, **opts) -> dict:
    """One or more images from a prompt. Read-only to the outside world — the
    result is a file reference, nothing is published anywhere."""
    refusal = _reject_asset_reuse(prompt)
    if refusal:
        return {"ok": False, "error": refusal, "code": "asset_reuse_blocked",
                "source": SOURCE}
    if not configured():
        return _mock({"assets": [], "prompt": guard.inert(prompt, "prompt")})
    try:
        import higgsfield_io
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"higgsfield_io unavailable: {e}", "assets": []}

    n = max(1, min(int(count or 1), 4))   # a hard ceiling — generation costs money
    assets, errors = [], []
    for i in range(n):
        try:
            r = higgsfield_io.generate_image(prompt, **opts)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e)[:200])
            continue
        url = r.get("url") if isinstance(r, dict) else None
        if not url:
            errors.append((r or {}).get("error") or "no image url returned")
            continue
        assets.append({
            "url": url,
            "index": i,
            "aiGenerated": True,
            "disclosure": DISCLOSURE,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": SOURCE,
        })
    return {"ok": bool(assets), "configured": True, "source": SOURCE,
            "assets": assets, "count": len(assets),
            "prompt": guard.inert(prompt, "prompt"),
            "disclosure": DISCLOSURE,
            "errors": errors or None,
            "note": ("Generated, not launched. Publishing, boosting or spending against "
                     "this asset stays a one-tap approval.")}


def from_packet(packet: dict, count: int = 1, **opts) -> dict:
    """Generate straight from a decision packet's copy plan.

    Refuses when the packet is blocked — if a candidate died on a trademark or the
    FTC transit rule, paying to render creative for it is waste.
    """
    packet = packet if isinstance(packet, dict) else {}
    if packet.get("blocked"):
        stops = [f["flag"] for f in (packet.get("killFlags") or [])
                 if f.get("severity") == "stop"]
        return {"ok": False, "code": "candidate_blocked",
                "error": f"Candidate is blocked ({', '.join(stops) or 'kill flag'}). "
                         f"Not spending a generation on it."}
    read = packet.get("read")
    plan = (read or {}).get("copyPlan") if isinstance(read, dict) else None
    if not isinstance(plan, dict) or not str(plan.get("higgsfieldPrompt") or "").strip():
        return {"ok": False, "code": "no_copy_plan",
                "error": "Packet carries no copy plan yet. Build the packet first — "
                         "the prompt comes from the why-it's-winning read."}
    out = generate(plan["higgsfieldPrompt"], count=count, **opts)
    out["angle"] = plan.get("angle")
    out["whatToChange"] = plan.get("whatToChange")
    out["format"] = (read or {}).get("creativeFormat")
    out["hook"] = (read or {}).get("hook")
    return out


def demo() -> int:
    """Self-check: the two hard lines hold. `python3 dropship_creative.py`"""
    fails = []

    def check(label, cond):
        print(("  ok   " if cond else "  FAIL ") + label)
        if not cond:
            fails.append(label)

    print("dropship_creative guards")
    for bad in ["recreate their ad exactly",
                "copy the competitor's video frame for frame",
                "make it identical to the ad they are running"]:
        check(f"blocks asset reuse: {bad[:34]}…", bool(_reject_asset_reuse(bad)))
    check("blocks a protected brand", bool(_reject_asset_reuse("a Nike style running shoe")))
    check("allows an original scene",
          not _reject_asset_reuse("A cotton tote bag on a sunlit kitchen counter, "
                                  "UGC phone-camera look, morning light"))
    check("empty prompt refused", bool(_reject_asset_reuse("")))

    r = generate("recreate their ad exactly")
    check("generate() refuses reuse before spending", r["ok"] is False
          and r["code"] == "asset_reuse_blocked")

    r = from_packet({"blocked": True, "killFlags": [{"flag": "trademark", "severity": "stop"}]})
    check("from_packet refuses a blocked candidate", r["ok"] is False
          and r["code"] == "candidate_blocked")

    r = from_packet({"blocked": False, "read": {}})
    check("from_packet refuses without a copy plan", r["code"] == "no_copy_plan")

    if not configured():
        r = generate("A cotton tote bag on a sunlit counter, UGC look")
        check("unkeyed → honest mock, no invented asset",
              r["configured"] is False and r["assets"] == [])

    check("disclosure names Meta", "Meta" in DISCLOSURE)
    check("disclosure names Etsy", "Etsy" in DISCLOSURE)

    print()
    if fails:
        print(f"FAILED — {len(fails)}: {', '.join(fails)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(demo())
