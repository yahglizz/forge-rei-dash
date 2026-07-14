"""review_agent.py — weekly AI review for FORGE REI OS.

Spins up several focused analysts IN PARALLEL (concurrent Claude calls), each
examining one angle of the message analytics, then a synthesizer merges them into
(1) a human report and (2) a rewritten "Marcus playbook" that closes the learning
loop — Marcus loads that playbook into his reply-draft prompt.

Writes both into the Obsidian brain vault (Log/ + Skills/marcus-playbook.md).
Needs ANTHROPIC_API_KEY; without it returns {needsKey: true} and the UI prompts for it.
"""

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import brain_io
import forge_atomic

HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / "marcus_state"
STATE_DIR.mkdir(exist_ok=True)
LATEST_FILE = STATE_DIR / "review_latest.json"
MODEL = os.environ.get("FORGE_REVIEW_MODEL", "claude-sonnet-4-5")


def _api_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    for p in [HERE.parent / "marcus-wholesale-agent" / "config" / "ghl.env",
              Path.home() / "Desktop" / "marcus-wholesale-agent" / "config" / "ghl.env"]:
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    v = line.split("=", 1)[1].strip()
                    if v and not v.startswith("sk-ant-..."):
                        return v
    return None


def _claude(key, system, user, max_tokens=1200, tools=None):
    messages = [{"role": "user", "content": user}]
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools:
        # e.g. [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}]
        payload["tools"] = tools
    continuations = 0
    while True:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode(),
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            # urllib's default str(e) is just "HTTP Error 400: Bad Request" — the
            # real reason (low credit balance, rate limit, bad model) lives in the
            # JSON body, which urllib discards. Read it so every agent's "reaching
            # my brain" message shows the actual cause instead of an opaque code.
            try:
                body = json.loads(e.read().decode())
                msg = (body.get("error") or {}).get("message") or str(e)
            except Exception:  # noqa: BLE001
                msg = str(e)
            raise RuntimeError(f"Anthropic API error ({e.code}): {msg}") from None
        try:  # cost telemetry — best-effort, never blocks the call
            import cost_tracker
            u = data.get("usage") or {}
            cost_tracker.record_anthropic(MODEL, u.get("input_tokens"), u.get("output_tokens"))
        except Exception:
            pass
        if data.get("stop_reason") == "pause_turn" and continuations < 3:
            messages.append({"role": "assistant", "content": data["content"]})
            continuations += 1
            continue
        return "".join(b.get("text", "") for b in data.get("content", [])).strip()


# The parallel analyst panel — each gets the full metrics, focuses on one lens.
ANALYSTS = [
    ("response", "response speed & coverage — unanswered seller texts, reply rate, "
     "median reply latency, and the cost of slow replies in wholesale"),
    ("messaging", "message & objection quality — the classification mix (READY/PRICE/"
     "NRN/HELP/DNC), what sellers are actually saying, and what's converting vs stalling"),
    ("markets", "per-market performance — which market tags produce engaged sellers vs "
     "dead volume, and where to concentrate or cut spend"),
    ("conversion", "conversion — how conversations turn into opportunities & pipeline value, "
     "and the biggest leak between reply and deal"),
    ("marcus", "Marcus reply quality — based on his sent/suppressed/dismissed counts and "
     "classification handling, how his drafting should improve"),
]


def _analyst(key, lens_key, lens_desc, metrics):
    system = (
        "You are a sharp real-estate wholesaling analyst reviewing a week of "
        "GoHighLevel SMS data for an operator (Yahjair). Be specific and numeric. "
        f"Focus ONLY on: {lens_desc}. "
        "Return STRICT JSON: {\"findings\":[\"...\"],\"recommendations\":[\"...\"],"
        "\"playbook_notes\":[\"concrete reply guidance Marcus should follow\"]}. "
        "3-5 items each, no prose outside JSON."
    )
    user = f"METRICS:\n{json.dumps(metrics, indent=2)}\n\nReturn the JSON now."
    try:
        txt = _claude(key, system, user, max_tokens=900)
        s, e = txt.find("{"), txt.rfind("}")
        if s < 0 or e <= s:
            raise ValueError("no JSON object in analyst response")
        return {"lens": lens_key, **json.loads(txt[s:e + 1])}
    except Exception as ex:  # noqa: BLE001
        return {"lens": lens_key, "findings": [], "recommendations": [],
                "playbook_notes": [], "error": str(ex)}


def _synthesize(key, metrics, analysts):
    system = (
        "You are the Chief of Staff synthesizing analyst reports into one weekly "
        "review for a real-estate wholesaler. Output GitHub-flavored markdown with "
        "these sections: '## TL;DR' (3 bullets), '## What's working', '## What to fix "
        "this week' (ranked, specific, numeric), '## Marcus playbook' (concrete SMS "
        "reply rules: tone, objection handling, what to say for READY/PRICE/NRN/HELP). "
        "Be direct and tactical. No fluff."
    )
    user = ("WEEK METRICS:\n" + json.dumps(metrics, indent=2)
            + "\n\nANALYST REPORTS:\n" + json.dumps(analysts, indent=2)
            + "\n\nWrite the markdown review now.")
    try:
        import agent_coach
        user += agent_coach.insights_block("marcus", "wholesale")
    except Exception:
        pass
    return _claude(key, system, user, max_tokens=2000)


def _extract_playbook(report_md):
    """Pull the '## Marcus playbook' section out of the synthesized report."""
    marker = "## Marcus playbook"
    i = report_md.find(marker)
    if i < 0:
        return ""
    return report_md[i + len(marker):].strip()


def latest():
    if LATEST_FILE.exists():
        try:
            return json.loads(LATEST_FILE.read_text())
        except Exception:
            pass
    return {"hasReview": False, "needsKey": _api_key() is None}


def run(get_metrics):
    """get_metrics() -> the analytics bundle. Returns a summary dict for the UI."""
    key = _api_key()
    if not key:
        return {"needsKey": True,
                "message": "Add ANTHROPIC_API_KEY to ghl.env to enable the weekly review."}
    started = time.time()
    metrics = get_metrics()

    # Fan out the analyst panel in parallel.
    with ThreadPoolExecutor(max_workers=5) as ex:
        reports = list(ex.map(
            lambda a: _analyst(key, a[0], a[1], metrics), ANALYSTS))

    report_md = _synthesize(key, metrics, reports)
    playbook = _extract_playbook(report_md)

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Write the full report into the brain Log.
    log_rel = f"Log/forge-review-{date}.md"
    log_md = (f"---\ntype: review\nsource: forge-rei-os\ndate: {date}\n---\n\n"
              f"# FORGE Weekly Review — {date}\n\n_Generated {stamp} from "
              f"{metrics.get('scope', 0)} conversations._\n\n{report_md}\n")
    w1 = brain_io.write_note(log_rel, log_md, reason=f"weekly review {date}")

    # Maintain the living Marcus playbook (closes the learning loop).
    pb_md = (f"---\ntype: skill\nname: marcus-playbook\nupdated: {date}\n---\n\n"
             f"# Marcus Playbook\n\n_Auto-maintained by the FORGE weekly review "
             f"({stamp}). Marcus loads this into his reply-draft prompt._\n\n"
             f"{playbook or 'No playbook guidance this week.'}\n")
    w2 = brain_io.write_note("Skills/marcus-playbook.md", pb_md,
                             reason=f"update Marcus playbook {date}")

    summary = {
        "hasReview": True,
        "date": date,
        "stamp": stamp,
        "scope": metrics.get("scope", 0),
        "report": report_md,
        "logPath": log_rel,
        "playbookPath": "Skills/marcus-playbook.md",
        "committed": w1.get("committed") or w2.get("committed"),
        "analysts": [{"lens": r["lens"], "findings": len(r.get("findings", [])),
                      "error": r.get("error")} for r in reports],
        "elapsedSec": round(time.time() - started, 1),
        "needsKey": False,
    }
    forge_atomic.atomic_write_json(LATEST_FILE, summary)
    return summary


if __name__ == "__main__":
    # Standalone weekly run (used by the LaunchAgent): hit the live connector for metrics.
    import urllib.request as _u
    def _metrics():
        with _u.urlopen("http://localhost:7799/api/analytics?days=7", timeout=120) as r:
            return json.loads(r.read().decode())
    print(json.dumps(run(_metrics), indent=2)[:500])
