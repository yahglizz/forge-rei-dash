"""agency_instagram.py — AGENCY Instagram toolkit (@forgelabsphiladelphia).

Wraps the vendored instagram-agent-skill (forge-agency/instagram/, MIT, see VENDOR.md):
five stdlib-only Python tools that score a Reel hook, time a beat sheet, lint a caption,
strip the AI fingerprint and rank a swipe file. Each runs as a short subprocess (no
network, no imports into this process) behind /api/agency/instagram/*.

AGENCY ONLY. The Meta side is pinned to the agency's own ids (docs/META_ACCOUNTS.md);
nothing here reads or writes the daycare's Page, Instagram or ad account, and a draft that
names the daycare is refused. NOTHING POSTS: save_draft() queues an Instagram *draft* in
the existing agency Social queue (agency_social); Ready -> Approval Center -> Metricool
publishing stays the owner's tap (CLAUDE.md rule 2).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import agency_social

HERE = Path(__file__).resolve().parent
IG_DIR = HERE.parent / "forge-agency" / "instagram"
SKILLS = IG_DIR / "skills"
VOICE = IG_DIR / "voice.md"
STATE_DIR = HERE.parent / "forge-agency" / "data" / "instagram"

# --- the agency's OWN Meta identities (docs/META_ACCOUNTS.md). Not secrets. ---
AGENCY_AD_ACCOUNT = "act_2344043939684594"      # ClienForgePhiladelphia
IG_HANDLE = "forgelabsphiladelphia"
IG_ID = "17841464279234508"
VENDOR_COMMIT = "d03c56bb598be770c60b201f94237e5d1a4268a6"

MAX_CHARS = 20000
TIMEOUT = 10

# tool -> (script, doc skill). Order = the order agents see.
TOOLS = {
    "hook":     ("ig-reel/hookscore.py",   "/ig-reel"),    # score hooks, one per line
    "beats":    ("ig-reel/beats.py",       "/ig-reel"),    # time a script into a beat sheet
    "caption":  ("ig-caption/caption.py",  "/ig-caption"), # lint vs the feed truncation
    "humanize": ("ig-human/humanize.py",   "/ig-human"),   # strip the AI fingerprint
    "detect":   ("ig-human/detect.py",     "/ig-human"),   # score how machine-written it reads
    "swipe":    ("ig-viral/swipe.py",      "/ig-viral"),   # rank collected reels by outlier multiple
}

# The daycare is a SEPARATE business. Its handle, ids and name never appear in agency posts.
_DAYCARE_RE = re.compile(
    r"atouchofblessing|a touch of blessing|mother'?s touch|1175564690150627|"
    r"939494549239823|17841436257715501|17841439350588476", re.I)


def _num(v, lo, hi):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if lo <= f <= hi else None


def _args(tool, opts):
    a = ["--json"]
    if tool == "beats":
        if _num(opts.get("wpm"), 60, 300) is not None:
            a += ["--wpm", str(_num(opts["wpm"], 60, 300))]
        if _num(opts.get("target"), 5, 180) is not None:
            a += ["--target", str(_num(opts["target"], 5, 180))]
    elif tool == "caption":
        kw = str(opts.get("keywords") or "")[:200]
        if kw.strip():
            a += ["--keywords", kw]
    return a


def run_tool(tool, text, opts=None):
    """Run one vendored tool on `text`. Never throws. -> {ok, tool, skill, result} | {error}."""
    if tool not in TOOLS:
        return {"error": f"unknown tool {tool!r}; one of {list(TOOLS)}"}
    if not isinstance(text, str) or not text.strip():
        return {"error": "text required"}
    if len(text) > MAX_CHARS:
        return {"error": f"text too long (max {MAX_CHARS} chars)"}
    script = SKILLS / TOOLS[tool][0]
    if not script.is_file():
        return {"error": f"tool missing on disk: {script.name}"}
    cmd = [sys.executable, "-I", str(script)] + _args(tool, opts or {}) + ["-"]
    try:
        p = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=TIMEOUT,
                           env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"})
    except subprocess.TimeoutExpired:
        return {"error": f"{tool} timed out after {TIMEOUT}s"}
    except OSError as e:
        return {"error": f"{tool} failed to start: {e}"}
    try:
        result = json.loads(p.stdout)
    except ValueError:
        return {"error": f"{tool} exit {p.returncode}: {(p.stderr or p.stdout).strip()[:300]}"}
    return {"ok": True, "tool": tool, "skill": TOOLS[tool][1], "result": result}


def voice_unknowns():
    """How many `Unknown` answers remain in voice.md (the owner fills these in)."""
    try:
        return len(re.findall(r"\bUnknown\b", VOICE.read_text(errors="ignore")))
    except OSError:
        return None


def status():
    """Connection + tool inventory for the Social tab and for agents. Read-only, never throws."""
    conn = agency_social.connection()
    return {
        "account": {"business": "agency", "handle": IG_HANDLE, "instagramId": IG_ID,
                    "adAccount": AGENCY_AD_ACCOUNT,
                    "facebookPage": None,   # Unknown: the agency has no Page yet (docs/META_ACCOUNTS.md)
                    "doNotUse": "the daycare's Page, Instagram, ad account (docs/META_ACCOUNTS.md)"},
        "metricool": {"brand": conn.get("brand"), "source": conn.get("source"),
                      "autonomous": conn.get("autonomous"),
                      "instagramLinked": None,   # Unknown until verified in Metricool
                      "note": "Posting needs Instagram linked to Metricool brand forgelabsx + METRICOOL_USER_TOKEN."},
        "tools": [{"tool": t, "skill": s} for t, (_, s) in TOOLS.items()],
        "toolsOnDisk": all((SKILLS / sc).is_file() for sc, _ in TOOLS.values()),
        "vendor": {"source": "github.com/Jakeschincariol/instagram-agent-skill", "commit": VENDOR_COMMIT},
        "voice": {"path": "forge-agency/instagram/voice.md", "unknownAnswers": voice_unknowns()},
        "stateDir": "forge-agency/data/instagram/",
        "publishes": False,
    }


def save_draft(text, keywords=""):
    """Humanize + lint + score a caption, then queue it as an Instagram DRAFT (never ready/posted).
    -> {ok, post, humanized, caption, detect, changed} | {error}. Publishing stays approval-gated."""
    if not isinstance(text, str) or not text.strip():
        return {"error": "text required"}
    if _DAYCARE_RE.search(text):
        return {"error": "refused: names the daycare (a separate business). Agency posts never mention it."}
    h = run_tool("humanize", text)
    if not h.get("ok"):
        return h
    clean = (h["result"] or {}).get("text") or text
    cap = run_tool("caption", clean, {"keywords": keywords})
    det = run_tool("detect", clean)
    saved = agency_social.save_post({"network": "instagram", "text": clean, "status": "draft"})
    if saved.get("error"):
        return saved
    return {"ok": True, "post": saved.get("post"), "changed": clean != text,
            "humanized": h["result"], "caption": cap.get("result", cap), "detect": det.get("result", det),
            "note": "Saved as a draft. Mark Ready in the Social tab; the Approval Center gates publishing."}
