"""skill_forge.py — the meta-agent that turns repeated learning into PROPOSED skills.

Each agent already improves its own playbook (`learn()` → vault, git-committed). What no
one does is watch ACROSS agents for a pattern that deserves to become a standalone skill.
skill_forge does exactly that, and ONLY proposes — nothing is adopted without a tap:

  1. LISTEN  — registered as an `agent_bus` notifier; every broadcast (learn events,
     handoffs, status notes) feeds a lightweight keyword signal store. No Claude call
     per message — detection is cheap counting.
  2. DETECT  — a topic becomes a candidate when it shows up from >= FORGE_SKILLFORGE_MIN_AGENTS
     distinct agents (default 2) or >= FORGE_SKILLFORGE_MIN_ENCOUNTERS mentions (default 8),
     rate-limited to one proposal per FORGE_SKILLFORGE_INTERVAL_MIN (default 360 min),
     and skipped when an existing vault playbook / ~/.claude/skills entry already covers it.
  3. DRAFT   — one Claude call writes the skill markdown (SKILL.md frontmatter format).
     The draft lands in the vault at `Skills/proposals/<pid>.md` via brain_io.write_note
     (git-committed → reversible). ~/.claude/skills is NEVER touched at draft time.
  4. GATE    — proposal broadcast on the bus (`type: skill_proposal`) → Telegram buttons
     ✅ Adopt (`skillgo:<pid>`) / 🗑 Dismiss (`skillno:<pid>`) + a Command Center card.
  5. LEARN   — approved vs rejected topics are folded into the next drafting prompt, so
     what the operator actually adopts shapes what gets proposed next.

State: marcus_state/skill_forge.json (locked + atomic, mirrors ace.py).
"""
import json
import os
import re
import threading
import time
from pathlib import Path

import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "skill_forge.json"
_LOCK = threading.Lock()

MIN_AGENTS = int(os.environ.get("FORGE_SKILLFORGE_MIN_AGENTS", "2"))
MIN_ENCOUNTERS = int(os.environ.get("FORGE_SKILLFORGE_MIN_ENCOUNTERS", "8"))
INTERVAL_MIN = int(os.environ.get("FORGE_SKILLFORGE_INTERVAL_MIN", "360"))
CLAUDE_SKILLS_DIR = Path(os.environ.get(
    "FORGE_CLAUDE_SKILLS", str(Path.home() / ".claude" / "skills")))

_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "its",
         "from", "this", "that", "was", "has", "have", "had", "is", "are", "be", "it",
         "at", "by", "as", "his", "her", "their", "our", "your", "my", "new", "now",
         "updated", "self", "improvement", "playbook", "agent", "recent", "encounters"}


def _now_ms():
    return int(time.time() * 1000)


def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:48] or "pattern"


def _topics(text):
    """Cheap keyword topics from a bus message. 2-word shingles beat single words."""
    words = [w for w in re.findall(r"[a-z][a-z']{3,}", (text or "").lower())
             if w not in _STOP]
    out = set()
    for i in range(len(words) - 1):
        out.add(words[i] + " " + words[i + 1])
    return list(out)[:12]


def _already_covered(topic):
    """True if an existing vault playbook or Claude skill already mentions this topic."""
    frags = [f for f in topic.split() if len(f) > 3]
    if not frags:
        return True
    try:
        import brain_io
        skills_dir = brain_io.VAULT / "Skills"
        if skills_dir.exists():
            for p in skills_dir.glob("*.md"):
                body = p.read_text(errors="ignore").lower()
                if all(f in body for f in frags):
                    return True
    except Exception:
        pass
    try:
        if CLAUDE_SKILLS_DIR.exists():
            for p in CLAUDE_SKILLS_DIR.glob("*/SKILL.md"):
                body = p.read_text(errors="ignore").lower()
                if all(f in body for f in frags):
                    return True
    except Exception:
        pass
    return False


# ── 1+2. LISTEN + DETECT ──────────────────────────────────────────────────────────────

def on_bus_message(msg):
    """agent_bus notifier tap. Cheap counting only; drafting happens on a side thread.
    NEVER raises (a telemetry failure must not break the sender's loop)."""
    try:
        if not isinstance(msg, dict) or msg.get("from") in ("skill_forge", None, ""):
            return
        frm = str(msg.get("from"))
        text = f"{msg.get('text') or ''} {json.dumps(msg.get('data') or {})[:300]}"
        candidate = None
        with _LOCK:
            d = _load()
            sig = d.setdefault("signals", {})
            for t in _topics(text):
                row = sig.setdefault(t, {"agents": {}, "count": 0,
                                         "first": _now_ms(), "samples": []})
                row["agents"][frm] = int(row["agents"].get(frm) or 0) + 1
                row["count"] = int(row["count"] or 0) + 1
                row["last"] = _now_ms()
                if len(row["samples"]) < 6:
                    row["samples"].append(str(msg.get("text") or "")[:200])
            # prune the long tail so the store stays small
            if len(sig) > 400:
                for k in sorted(sig, key=lambda k: sig[k].get("count", 0))[:len(sig) - 400]:
                    sig.pop(k, None)
            candidate = _pick_candidate(d)
            if candidate:
                d["lastProposalTs"] = _now_ms()   # reserve the rate-limit slot now
            _save(d)
        if candidate:
            threading.Thread(target=_propose, args=(candidate,), daemon=True).start()
    except Exception:
        pass


def _pick_candidate(d):
    """Best uncovered topic past threshold, honoring the rate limit. Call under _LOCK."""
    if _now_ms() - int(d.get("lastProposalTs") or 0) < INTERVAL_MIN * 60_000:
        return None
    proposed = {p.get("topic") for p in (d.get("proposals") or {}).values()}
    best = None
    for topic, row in (d.get("signals") or {}).items():
        if topic in proposed:
            continue
        agents, count = len(row.get("agents") or {}), int(row.get("count") or 0)
        if agents < MIN_AGENTS and count < MIN_ENCOUNTERS:
            continue
        score = agents * 10 + count
        if best is None or score > best[0]:
            best = (score, topic, row)
    if best is None:
        return None
    if _already_covered(best[1]):
        return None
    return {"topic": best[1], "row": best[2]}


# ── 3. DRAFT (proposal only — never applies anything) ─────────────────────────────────

def _draft_md(topic, row, stats):
    """Claude-drafted SKILL.md body; template fallback when no key. Never raises."""
    samples = "\n".join(f"- {s}" for s in (row.get("samples") or [])[:6])
    agents = ", ".join(sorted((row.get("agents") or {}).keys()))
    fallback = (f"---\nname: {_slug(topic)}\n"
                f"description: Recurring cross-agent pattern '{topic}' seen from {agents} "
                f"— captured for reuse.\n---\n\n# {topic}\n\n## Where it showed up\n"
                f"{samples}\n\n## Draft rubric\n- (fill in after review)\n")
    try:
        import review_agent
        key = review_agent._api_key()
        if not key:
            return fallback
        feedback = ""
        if stats.get("topicsApproved") or stats.get("topicsRejected"):
            feedback = ("\nOperator taste so far — proposals ADOPTED: "
                        + ", ".join(stats.get("topicsApproved") or ["none"])
                        + "; REJECTED: " + ", ".join(stats.get("topicsRejected") or ["none"])
                        + ". Propose in the spirit of what got adopted.")
        out = review_agent._claude(
            key,
            "You are skill_forge inside FORGE REI OS (real-estate-wholesaling AI ops). "
            "Write ONE reusable skill file in markdown. Start with YAML frontmatter "
            "(--- name: <kebab-slug> / description: <one line, when to use> ---), then a "
            "short recipe: when it applies, the steps, the pitfalls. Ground it ONLY in the "
            "evidence given — do not invent tools or APIs. Keep it under 60 lines." + feedback,
            f"Recurring pattern detected across agents ({agents}): \"{topic}\".\n"
            f"Evidence from the agent bus:\n{samples}\n\nWrite the skill file:",
            max_tokens=1200)
        return out if len(out or "") > 100 else fallback
    except Exception:
        return fallback


def _propose(candidate):
    """Write the vault proposal + broadcast for a tap. Runs on a side thread."""
    try:
        topic, row = candidate["topic"], candidate["row"]
        with _LOCK:
            stats = _load().get("stats") or {}
        body = _draft_md(topic, row, stats)
        pid = f"sf_{_slug(topic)}_{_now_ms()}"
        rel = f"Skills/proposals/{pid}.md"
        try:
            import brain_io
            brain_io.write_note(rel, body, reason=f"skill_forge proposal: {topic}")
        except Exception:
            pass
        prop = {"id": pid, "status": "pending", "topic": topic, "path": rel,
                "title": topic, "body": body[:4000], "ts": _now_ms(),
                "agents": sorted((row.get("agents") or {}).keys()),
                "count": int(row.get("count") or 0)}
        with _LOCK:
            d = _load()
            d.setdefault("proposals", {})[pid] = prop
            _save(d)
        try:
            import agent_bus
            agent_bus.send("skill_forge", "all", "alert",
                           f"✨ New skill proposal: \"{topic}\" (seen from "
                           f"{', '.join(prop['agents'])}). Tap to adopt or dismiss.",
                           {"type": "skill_proposal", "pid": pid, "name": topic})
        except Exception:
            pass
    except Exception:
        pass


# ── 4. GATE — approve / dismiss (the only paths that apply anything) ──────────────────

def approve(pid):
    """Operator tap: adopt the proposal → vault Skills/<slug>.md (git-committed)."""
    with _LOCK:
        d = _load()
        p = (d.get("proposals") or {}).get(pid)
        if not p or p.get("status") != "pending":
            return {"error": "proposal not found or already handled"}
        rel = f"Skills/{_slug(p.get('topic'))}.md"
        try:
            import brain_io
            wrote = brain_io.write_note(rel, p.get("body") or "",
                                        reason=f"skill_forge ADOPTED: {p.get('topic')}")
            if isinstance(wrote, dict) and wrote.get("error"):
                raise RuntimeError(wrote.get("error"))
        except Exception as e:  # noqa: BLE001
            p["lastError"] = f"adopt write failed: {e}"
            _save(d)
            return {"error": p["lastError"]}
        p["status"] = "approved"
        p["decidedAt"] = _now_ms()
        p["adoptedPath"] = rel
        p.pop("lastError", None)
        st = d.setdefault("stats", {})
        st["approved"] = int(st.get("approved") or 0) + 1
        st.setdefault("topicsApproved", []).append(p.get("topic"))
        st["topicsApproved"] = st["topicsApproved"][-12:]
        _save(d)
    try:
        import agent_bus
        agent_bus.send("skill_forge", "all", "status",
                       f"✅ Skill adopted: \"{p.get('topic')}\" → vault Skills/. "
                       "Agents pick it up on their next brain search.", {})
    except Exception:
        pass
    return {"ok": True, "message": f"adopted: {p.get('topic')}"}


def dismiss(pid):
    with _LOCK:
        d = _load()
        p = (d.get("proposals") or {}).get(pid)
        if not p or p.get("status") != "pending":
            return {"error": "proposal not found or already handled"}
        p["status"] = "dismissed"
        p["decidedAt"] = _now_ms()
        st = d.setdefault("stats", {})
        st["rejected"] = int(st.get("rejected") or 0) + 1
        st.setdefault("topicsRejected", []).append(p.get("topic"))
        st["topicsRejected"] = st["topicsRejected"][-12:]
        _save(d)
    return {"ok": True, "message": "dismissed"}


# ── read API ───────────────────────────────────────────────────────────────────────────

def pending():
    try:
        with _LOCK:
            d = _load()
        props = sorted((d.get("proposals") or {}).values(),
                       key=lambda p: -(p.get("ts") or 0))
        return {"ok": True,
                "pending": [p for p in props if p.get("status") == "pending"],
                "recent": [p for p in props if p.get("status") != "pending"][:10],
                "stats": d.get("stats") or {},
                "signals": len(d.get("signals") or {})}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "pending": [], "recent": []}
