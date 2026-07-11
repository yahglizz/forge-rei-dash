"""style_agent.py — end-of-day learning agent for FORGE REI OS.

Reads the day's GoHighLevel SMS threads, studies how YAHJAIR actually texts
sellers (tone, openers, closers, objection handling), and distills it into
reusable *skills* written into the Obsidian brain:

  • Skills/yahjair-voice.md   — the voice/style guide (Marcus reads this to text like him)
  • Skills/closing-plays.md    — named, reusable plays (trigger -> what to send)
  • Log/forge-daily-<date>.md  — the day's digest

Run it: POST /api/style/run  (manual "Learn from today" button + a daily LaunchAgent).
Graceful: no ANTHROPIC_API_KEY -> {"needsKey": true}; the dashboard shows a hint.

Reuses review_agent's Claude plumbing and analytics_engine's conversation puller so
there's one place each lives.
"""
import json
import time
from datetime import datetime
from pathlib import Path

import brain_io
import review_agent
from analytics_engine import _pull_conversations, _to_ms

HERE = Path(__file__).resolve().parent
from concurrent.futures import ThreadPoolExecutor


def _collect_pairs(ghl_get, convos, sample=40, max_msgs=140):
    """Sample threads; return [(inbound_context, outbound_text)] — Yahjair's replies
    with the seller line that prompted them. Outbound bodies are the teaching signal."""
    picked = convos[:sample]

    def one(c):
        try:
            cid = c.get("id")
            data = ghl_get(f"/conversations/{cid}/messages", {"limit": 50})
            raw = data.get("messages", data)
            if isinstance(raw, dict):
                raw = raw.get("messages", [])
            msgs = []
            for m in (raw or []):
                b = (m.get("body") or "").strip()
                if b:
                    msgs.append((m.get("direction"), _to_ms(m.get("dateAdded")) or 0, b))
            msgs.sort(key=lambda x: x[1])
            pairs = []
            for i, (d, _t, body) in enumerate(msgs):
                if d == "outbound":
                    prev_in = ""
                    for d2, _t2, b2 in reversed(msgs[:i]):
                        if d2 == "inbound":
                            prev_in = b2
                            break
                    pairs.append((prev_in, body))
            return pairs
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(one, picked))
    flat = [p for r in results for p in r]
    return flat[:max_msgs]


def _corpus(pairs):
    lines = []
    for seller, me in pairs:
        if seller:
            lines.append(f"SELLER: {seller}")
        lines.append(f"YAHJAIR: {me}")
        lines.append("")
    return "\n".join(lines)


# Line-based format (NOT JSON) so seller-text quotes/apostrophes can't break parsing.
_FORMAT = (
    "SUMMARY: <one line on how Yahjair texts>\n"
    "EMOJI: none|light|heavy\n"
    "LENGTH: short|medium|long\n"
    "TONE: word | word | word\n"
    "OPENERS: phrasing he opens with | another\n"
    "CLOSERS: how he pushes to a call | another\n"
    "DOS: do this | do that\n"
    "DONTS: avoid this | avoid that\n"
    "SKILL: short name :: when seller does X :: what to send and why\n"
    "SKILL: ... (one line per skill, 3-6 total)\n"
    "SNIPPET: situation :: a copy-ready message in his voice\n"
    "SNIPPET: ... (3-6 total)\n"
    "INSIGHT: one thing that worked today\n"
    "INSIGHT: ..."
)


def _split(v, sep="|"):
    return [x.strip() for x in v.split(sep) if x.strip()]


def _parse_lines(txt):
    voice = {"summary": "", "tone": [], "openers": [], "closers": [],
             "emoji_use": "", "avg_length": "", "dos": [], "donts": []}
    skills, snippets, insights = [], [], []
    for raw in txt.splitlines():
        ln = raw.strip()
        if not ln or ":" not in ln:
            continue
        tag, _, val = ln.partition(":")
        tag = tag.strip().upper()
        val = val.strip()
        if tag == "SUMMARY":
            voice["summary"] = val
        elif tag == "EMOJI":
            voice["emoji_use"] = val
        elif tag == "LENGTH":
            voice["avg_length"] = val
        elif tag == "TONE":
            voice["tone"] = _split(val)
        elif tag == "OPENERS":
            voice["openers"] = _split(val)
        elif tag == "CLOSERS":
            voice["closers"] = _split(val)
        elif tag == "DOS":
            voice["dos"] = _split(val)
        elif tag == "DONTS":
            voice["donts"] = _split(val)
        elif tag == "SKILL":
            parts = _split(val, "::")
            if parts:
                skills.append({"name": parts[0], "trigger": parts[1] if len(parts) > 1 else "",
                               "play": parts[2] if len(parts) > 2 else ""})
        elif tag == "SNIPPET":
            parts = _split(val, "::")
            if parts:
                snippets.append({"when": parts[0], "text": parts[1] if len(parts) > 1 else parts[0]})
        elif tag == "INSIGHT":
            insights.append(val)
    return {"voice": voice, "skills": skills, "snippets": snippets, "insights": insights}


def _distill(key, corpus, n_pairs):
    system = (
        "You study how a real-estate wholesaler named Yahjair texts property sellers, "
        "then turn it into reusable skills his AI agent (Marcus) can copy so the whole "
        "agency texts in his voice and closes more deals. Learn from HIS messages "
        "(the YAHJAIR lines) — his phrasing, rhythm, how he handles objections and pushes "
        "to a call. Be concrete; capture his actual style, don't invent a generic salesy tone.\n\n"
        "Output ONLY these labeled lines, nothing else. One item per line. Separate list "
        "items with ' | ' and skill/snippet fields with ' :: '. Do not use those separators "
        "inside the content itself. Format:\n" + _FORMAT
    )
    user = (
        f"Here are {n_pairs} real seller->Yahjair text exchanges:\n\n"
        f"{corpus[:14000]}\n\nReturn the labeled lines now."
    )
    txt = review_agent._claude(key, system, user, max_tokens=1800)
    parsed = _parse_lines(txt)
    if not parsed["voice"]["summary"] and not parsed["skills"]:
        raise ValueError("could not parse learning output")
    return parsed


def _render_voice(v, date):
    L = ["---", "name: yahjair-voice", f"updated: {date}",
         "source: daily style_agent (learned from GHL messages)", "---", "",
         "# Yahjair's Texting Voice", "", v.get("summary", ""), ""]
    def sec(title, items):
        if items:
            L.append(f"## {title}")
            for it in items:
                L.append(f"- {it}")
            L.append("")
    L.append(f"**Emoji:** {v.get('emoji_use','?')}  ·  **Length:** {v.get('avg_length','?')}")
    L.append("")
    sec("Tone", v.get("tone"))
    sec("Openers he uses", v.get("openers"))
    sec("How he closes / pushes to call", v.get("closers"))
    sec("Do", v.get("dos"))
    sec("Don't", v.get("donts"))
    return "\n".join(L)


def _render_skills(skills, snippets, date):
    L = ["---", "name: closing-plays", f"updated: {date}",
         "source: daily style_agent", "---", "", "# Closing Plays (learned)", ""]
    for s in (skills or []):
        L.append(f"## {s.get('name','(play)')}")
        L.append(f"**When:** {s.get('trigger','')}")
        L.append(f"**Play:** {s.get('play','')}")
        L.append("")
    if snippets:
        L.append("# Copy-ready snippets (Yahjair's voice)")
        L.append("")
        for sn in snippets:
            L.append(f"- **{sn.get('when','')}** — “{sn.get('text','')}”")
        L.append("")
    return "\n".join(L)


def _render_digest(result, date, n_pairs):
    v = result.get("voice", {})
    L = ["---", f"name: forge-daily-{date}", f"date: {date}", "type: daily-digest", "---", "",
         f"# Daily Learning — {date}", "",
         f"Studied **{n_pairs}** of today's seller↔Yahjair exchanges.", "",
         "## Voice", v.get("summary", "—"), ""]
    if result.get("insights"):
        L.append("## What worked today")
        for it in result["insights"]:
            L.append(f"- {it}")
        L.append("")
    L.append(f"## New skills captured: {len(result.get('skills', []))}")
    for s in result.get("skills", []):
        L.append(f"- **{s.get('name','')}** — {s.get('trigger','')}")
    L.append("")
    L.append("Written to [[yahjair-voice]] and [[closing-plays]] — Marcus now texts from these.")
    return "\n".join(L)


def run(ghl_get, location_id, days=1, pages=4, sample=40):
    key = review_agent._api_key()
    if not key:
        return {"needsKey": True,
                "message": "Add ANTHROPIC_API_KEY to ghl.env so the daily agent can learn."}
    date = datetime.now().strftime("%Y-%m-%d")
    convos = _pull_conversations(ghl_get, location_id, pages=pages)
    now = int(time.time() * 1000)
    window = days * 86400 * 1000
    scope = [c for c in convos if (_to_ms(c.get("lastMessageDate")) or 0) >= now - window] or convos
    pairs = _collect_pairs(ghl_get, scope, sample=sample)
    if len(pairs) < 3:
        return {"ok": False, "date": date, "pairs": len(pairs),
                "message": "Not enough of your sent texts today to learn from yet."}
    try:
        result = _distill(key, _corpus(pairs), len(pairs))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "date": date, "error": str(e)}

    voice_md = _render_voice(result.get("voice", {}), date)
    skills_md = _render_skills(result.get("skills", []), result.get("snippets", []), date)
    digest_md = _render_digest(result, date, len(pairs))
    brain_io.write_note("Skills/yahjair-voice.md", voice_md, reason=f"daily voice {date}")
    brain_io.write_note("Skills/closing-plays.md", skills_md, reason=f"daily plays {date}")
    brain_io.write_note(f"Log/forge-daily-{date}.md", digest_md, reason=f"daily digest {date}")

    return {
        "ok": True, "date": date, "pairs": len(pairs),
        "skills": len(result.get("skills", [])),
        "snippets": len(result.get("snippets", [])),
        "voice": result.get("voice", {}),
        "insights": result.get("insights", []),
        "notes": ["Skills/yahjair-voice.md", "Skills/closing-plays.md", f"Log/forge-daily-{date}.md"],
    }


def latest():
    """Most recent daily digest + the current voice guide, for the dashboard."""
    out = {"hasDigest": False, "voice": None, "digest": None, "date": None}
    voice_p = brain_io.VAULT / "Skills" / "yahjair-voice.md"
    if voice_p.is_file():
        out["voice"] = voice_p.read_text(errors="ignore")
    log_dir = brain_io.VAULT / "Log"
    if log_dir.is_dir():
        digs = sorted(log_dir.glob("forge-daily-*.md"))
        if digs:
            p = digs[-1]
            out["hasDigest"] = True
            out["digest"] = p.read_text(errors="ignore")
            out["date"] = p.stem.replace("forge-daily-", "")
    return out
