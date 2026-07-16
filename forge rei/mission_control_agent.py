"""mission_control_agent.py — Orion, the FORGE Chief of Staff (cross-business CEO agent).

Orion sits ABOVE the four business directors (Scout/Marcus·REI, Dyson/Eco·Agency,
Solomon·Daycare, Midas·Dropship). Every morning he reads what each business's agents
actually produced — their cached operating briefs, what they broadcast on the agent bus,
the cross-agent coaching insights, new client requests, trending-product signal — and
SYNTHESIZES one ranked "attack today" brief for the owner: the single thing to focus on,
a fresh idea to act on now (a trend, a product, an ad, an enrollment push), and the
top priorities across the whole portfolio. It greets the owner the moment the dashboard
opens (Mission Control reads the CACHED brief — instant + free; a paid Claude call only
runs once a day on the box, or when the owner taps Refresh).

Same self-improving pattern as Midas/Solomon: key fallback, reads the brain, a learned
playbook it rewrites via learn(), state in marcus_state/mission_brief.json. Read-only +
propose — Orion never takes an outward action; he tells the owner what to attack. He
grounds every recommendation in a signal an agent actually reported — never a guess.
"""
import json
import os
import threading
import time
from pathlib import Path

import forge_atomic
import review_agent

HERE = Path(__file__).resolve().parent
MISSION_DIR = HERE.parent / "forge-mission"
STATE = HERE / "marcus_state" / "mission_brief.json"

PLAYBOOK_MD = "orion-playbook.md"
# Auto-build cadence: once per day, after this local hour (shares FORGE_TZ_OFFSET zone).
BUILD_AFTER_HOUR = int(os.environ.get("FORGE_MISSION_BRIEF_HOUR", "7"))
LEARN_EVERY = int(os.environ.get("FORGE_MISSION_LEARN_EVERY", "10"))


def _ceo_key():
    """Orion's key: own → shared → any business → wholesale (review_agent)."""
    for env_key in ("MISSION_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
        v = os.environ.get(env_key)
        if v and not v.startswith("sk-ant-..."):
            return v
    for mod, fn in (("agency_eco", "_agency_key"), ("dropship_agents", "_dropship_key")):
        try:
            m = __import__(mod)
            k = getattr(m, fn)()
            k = k[0] if isinstance(k, tuple) else k
            if k:
                return k
        except Exception:
            pass
    return review_agent._api_key()


def _strip_fences(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def _north_star_block():
    try:
        import north_star
        return north_star.context_block()
    except Exception:
        return ""


class OrionEngine:
    """The cross-business Chief of Staff. Synthesizes the daily 'attack today' brief."""

    def __init__(self):
        self.lock = threading.RLock()
        self.activity = []
        self.last_error = None
        self.last_brief = None
        self.last_brief_at = None
        self.last_build_day = ""
        self.brief_count = 0
        self.learn_state = {"lastLearnedAt": None, "learnCount": 0, "briefsSinceLearn": 0}
        self._sk_text = ""
        self._sk_mtime = None
        self._load()

    # --- persistence ---------------------------------------------------------
    def _load(self):
        try:
            if STATE.exists():
                d = json.loads(STATE.read_text())
                self.activity = d.get("activity", []) or []
                self.last_brief = d.get("lastBrief")
                self.last_brief_at = d.get("lastBriefAt")
                self.last_build_day = d.get("lastBuildDay", "") or ""
                self.brief_count = d.get("briefCount", 0) or 0
                self.learn_state = d.get("learnState", self.learn_state) or self.learn_state
        except Exception:
            pass

    def _save(self):
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            forge_atomic.atomic_write_json(STATE, {
                "activity": self.activity[-120:],
                "lastBrief": self.last_brief,
                "lastBriefAt": self.last_brief_at,
                "lastBuildDay": self.last_build_day,
                "briefCount": self.brief_count,
                "learnState": self.learn_state,
            })
        except Exception:
            pass

    def _log(self, kind, text):
        self.activity.append({"ts": int(time.time() * 1000), "kind": kind, "text": text})
        self.activity = self.activity[-120:]

    # --- playbook (learned rubric; seed + vault, vault wins) -----------------
    def _playbook(self):
        parts = []
        try:
            import brain_io
            paths = (MISSION_DIR / "skills" / PLAYBOOK_MD, brain_io.VAULT / "Skills" / PLAYBOOK_MD)
            sig = []
            for p in paths:
                if p.is_file():
                    parts.append(p.read_text(errors="ignore"))
                    sig.append((str(p), p.stat().st_mtime))
            sig = tuple(sig)
            if self._sk_mtime != sig:
                self._sk_text = "\n\n---\n\n".join(parts)
                self._sk_mtime = sig
            return self._sk_text
        except Exception:
            return self._sk_text

    # --- cross-business gather (all cheap/cached reads — NO Claude) -----------
    def _gather(self, scout=None, solomon=None, midas=None, screener=None):
        """Assemble everything the specialist agents produced. Every source is wrapped;
        a failing business degrades to a note, never takes the gather down."""
        data = {"rei": {}, "agency": {}, "daycare": {}, "dropship": {},
                "bus": [], "coaching": [], "clientRequests": []}

        # REI — Scout's read + the screening queue.
        try:
            if scout:
                s = scout.summary() or {}
                data["rei"] = {"counts": s.get("counts") or {}, "total": s.get("total"),
                               "aiScoring": s.get("aiScoring"), "lastError": s.get("lastError")}
            if screener:
                q = screener.queue() or {}
                data["rei"]["toScreen"] = q.get("count") if q.get("count") is not None \
                    else len(q.get("queue") or q.get("reports") or [])
        except Exception as e:  # noqa: BLE001
            data["rei"]["error"] = str(e)[:120]

        # Agency — agent status + NEW client requests + pending approvals.
        try:
            import agency_agents
            data["agency"]["agents"] = agency_agents.status() or {}
        except Exception as e:  # noqa: BLE001
            data["agency"]["error"] = str(e)[:120]
        try:
            import agency_requests_io
            reqs = (agency_requests_io.list_requests() or {}).get("requests") or []
            fresh = [r for r in reqs if r.get("status") in ("submitted", "in_progress", None)]
            data["clientRequests"] = [
                {"client": r.get("clientName"), "title": r.get("title"),
                 "type": r.get("type"), "priority": r.get("priority"),
                 "status": r.get("status")} for r in fresh[:8]]
        except Exception:
            pass
        try:
            import agency_approvals_io
            aq = agency_approvals_io.list_queue("pending") or {}
            data["agency"]["approvalsPending"] = int(
                (aq.get("counts") or {}).get("pending") or len(aq.get("queue") or []))
        except Exception:
            pass

        # Daycare — Solomon's CACHED brief (his latest priorities) + status.
        try:
            if solomon:
                data["daycare"]["status"] = solomon.status() or {}
                b = solomon.brief() if hasattr(solomon, "brief") else None
                bb = (b or {}).get("brief") if isinstance(b, dict) else None
                if bb:
                    data["daycare"]["directorBrief"] = {
                        "headline": bb.get("headline"),
                        "priorities": (bb.get("priorities") or [])[:4]}
        except Exception as e:  # noqa: BLE001
            data["daycare"]["error"] = str(e)[:120]

        # Dropship — Midas's CACHED brief + trending signal (only if a source is keyed).
        try:
            if midas:
                data["dropship"]["status"] = midas.status() or {}
                b = midas.brief() if hasattr(midas, "brief") else None
                bb = (b or {}).get("brief") if isinstance(b, dict) else None
                if bb:
                    data["dropship"]["directorBrief"] = {
                        "headline": bb.get("headline"),
                        "priorities": (bb.get("priorities") or [])[:4],
                        "winners": (bb.get("winners") or [])[:3]}
            import dropship_io
            data["dropship"]["watchlist"] = dropship_io.stats()
        except Exception as e:  # noqa: BLE001
            data["dropship"]["error"] = str(e)[:120]

        # Cross-agent: the bus (what agents spotted/broadcast) + coaching insights.
        try:
            import agent_bus
            bus = agent_bus.recent(30) or []
            rows = bus.get("items") if isinstance(bus, dict) else bus
            data["bus"] = [{"from": m.get("from"), "kind": m.get("kind"),
                            "text": (m.get("text") or "")[:200]} for m in (rows or [])[-20:]]
        except Exception:
            pass
        try:
            import agent_coach
            data["coaching"] = [
                {"from": c.get("from"), "text": (c.get("text") or c.get("insight") or "")[:200]}
                for c in (agent_coach.feed(20) or [])][-12:]
        except Exception:
            pass
        return data

    def _system_prompt(self):
        pb = self._playbook()
        return (
            "You are Orion, the CHIEF OF STAFF for the owner of a four-business portfolio: "
            "FORGE REI (real-estate wholesaling), FORGE Agency (ClientForge web/ads agency), "
            "A Touch of Blessings (daycare), and FORGE Dropship (e-commerce). You sit above "
            "every specialist agent. Each morning you read what those agents ACTUALLY "
            "produced — their operating briefs, what they broadcast on the agent bus, the "
            "coaching insights they shared, new client requests, and trending-product "
            "signal — and you tell the owner ONE thing to attack today plus the ranked "
            "priorities across all four businesses.\n\n"
            "HARD RULES:\n"
            "• Ground EVERY recommendation in a real signal from the data below, and name "
            "where it came from (which business / which agent spotted it). If a business "
            "gave you nothing, say so — never invent a metric, a lead count, a trend, or a "
            "result.\n"
            "• Rank by LEVERAGE across the whole portfolio — the owner has limited hours; "
            "put the highest-return action first. A fire (account health, a client waiting, "
            "a compliance/safety issue) outranks growth.\n"
            "• The 'idea' must be specific and actionable NOW — a concrete trend to ride, a "
            "product to test, an ad angle to run, an enrollment push — drawn from what an "
            "agent surfaced, not generic advice.\n"
            "• Close the loop and DECIDE. Don't hedge. Speak plainly and directly to the "
            "owner.\n"
            "• You never take an outward action yourself — you tell the owner what to do; "
            "he acts.\n\n"
            "Output ONLY valid JSON with keys: greeting (one short warm line), headline "
            "(the single most important focus today), focus (the theme in a few words), "
            "idea (one specific high-leverage thing to attack now, tied to a real signal), "
            "priorities (array of 3-5 {title, business, why, action, urgency} — business is "
            "one of rei/agency/daycare/dropship; urgency is now/today/soon), byBusiness "
            "(object with rei/agency/daycare/dropship → one honest line each), "
            "clientRequests (array of strings — client asks needing action today), watchouts "
            "(array of strings — risks to keep an eye on)."
            + _north_star_block()
            + ("\n\n=== YOUR PLAYBOOK (learned rubric) ===\n" + pb[:3500] if pb else "")
        )

    # --- the daily synthesis (the ONE paid Claude call) ----------------------
    def build_brief(self, scout=None, solomon=None, midas=None, screener=None):
        key = _ceo_key()
        if not key:
            return {"ok": False, "error": "no anthropic key"}
        data = self._gather(scout, solomon, midas, screener)
        system = self._system_prompt()
        user = (
            "Here is what every business + agent produced. Synthesize the owner's "
            "'attack today' brief per your output contract. Ground everything in this "
            "data; do not invent numbers or trends:\n\n"
            + json.dumps(data, indent=2, default=str)
            + "\n\nProduce the brief now."
        )
        try:
            raw = _strip_fences(review_agent._claude(key, system, user, max_tokens=2400))
            parsed = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"brief: {e}"
            return {"ok": False, "error": f"brief generation failed: {e}"}

        brief = {
            "greeting": parsed.get("greeting", "Here's where to aim today."),
            "headline": parsed.get("headline", "Today's focus"),
            "focus": parsed.get("focus", ""),
            "idea": parsed.get("idea", ""),
            "priorities": parsed.get("priorities") or [],
            "byBusiness": parsed.get("byBusiness") or {},
            "clientRequests": parsed.get("clientRequests") or [],
            "watchouts": parsed.get("watchouts") or [],
            "generatedAt": int(time.time() * 1000),
        }
        with self.lock:
            self.last_brief = brief
            self.last_brief_at = brief["generatedAt"]
            self.brief_count += 1
            self.learn_state["briefsSinceLearn"] = self.learn_state.get("briefsSinceLearn", 0) + 1
            self._log("brief", f"CEO brief — {brief['headline'][:60]} "
                               f"({len(brief['priorities'])} priorities)")
            self._save()
        self._write_note(brief)
        try:
            import agent_bus
            agent_bus.send("orion", "all", "note",
                           f"Orion CEO brief: {brief['headline'][:80]}",
                           {"focus": brief.get("focus")})
        except Exception:
            pass
        self._maybe_learn(key)
        return {"ok": True, "brief": brief}

    def _write_note(self, brief):
        try:
            import brain_io
            day = time.strftime("%Y-%m-%d")
            lines = [f"# Orion CEO brief — {day}", "", f"**{brief.get('headline','')}**", ""]
            if brief.get("idea"):
                lines += [f"💡 Attack now: {brief['idea']}", ""]
            for p in brief.get("priorities") or []:
                lines.append(f"- [{p.get('urgency','?')}/{p.get('business','?')}] "
                             f"{p.get('title','')} — {p.get('why','')}")
            brain_io.write_note(f"Reports/ceo-brief-{day}.md", "\n".join(lines),
                                reason=f"orion ceo brief {day}")
        except Exception:
            pass

    # --- daily scheduler hook (box) ------------------------------------------
    def maybe_daily(self, scout=None, solomon=None, midas=None, screener=None):
        """Build today's brief once, after the set hour. Called by the box scheduler."""
        try:
            offset = float(os.environ.get("FORGE_TZ_OFFSET", "-4") or -4)
            lt = time.gmtime(time.time() + offset * 3600.0)
            day = time.strftime("%Y-%m-%d", lt)
            if lt.tm_hour < BUILD_AFTER_HOUR or self.last_build_day == day:
                return {"ok": True, "skipped": True}
            res = self.build_brief(scout, solomon, midas, screener)
            if res.get("ok"):
                with self.lock:
                    self.last_build_day = day
                    self._save()
            return res
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:160]}

    # --- self-improvement ----------------------------------------------------
    def _maybe_learn(self, key):
        if key and self.learn_state.get("briefsSinceLearn", 0) >= LEARN_EVERY:
            try:
                self.learn(auto=True)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"learn: {e}"

    def learn(self, auto=False):
        key = _ceo_key()
        if not key:
            return {"error": "no anthropic key"}
        with self.lock:
            recent = [a for a in self.activity if a.get("kind") == "brief"][-8:]
        if not recent and not self.last_brief:
            return {"error": "no briefs to learn from yet"}
        current = self._playbook() or "(no playbook yet — create one)"
        sample = "\n".join(f"- {a.get('text','')}" for a in recent) or "(recent brief)"
        system = (
            "You are Orion, a SELF-IMPROVING chief of staff. Below is your CURRENT playbook "
            "and a sample of your recent CEO briefs. Improve yourself: sharpen how you rank "
            "leverage across four businesses, what signals matter most, how to spot the ONE "
            "thing worth attacking. Keep the hard rules (ground every rec in a real reported "
            "signal; never invent a metric; rank fires above growth; close the loop and "
            "decide; propose, never act). Output the FULL UPDATED playbook as clean "
            "markdown — ONLY the markdown."
        )
        user = "CURRENT PLAYBOOK:\n" + current[:3500] + "\n\nRECENT BRIEFS:\n" + sample
        try:
            import agent_coach
            user += agent_coach.insights_block("orion", "mission")
        except Exception:
            pass
        try:
            new_md = review_agent._claude(key, system, user, max_tokens=2000)
        except Exception as e:  # noqa: BLE001
            return {"error": f"claude: {e}"}
        if not new_md or len(new_md) < 150:
            return {"error": "learning produced nothing usable"}
        stamp = time.strftime("%Y-%m-%d %H:%M")
        header = f"---\nagent: orion\nupdated: {stamp}\nsource: self-improvement\n---\n\n"
        try:
            import brain_io
            res = brain_io.write_note(f"Skills/{PLAYBOOK_MD}", header + new_md.strip(),
                                      reason=f"orion self-improve {stamp}")
        except Exception as e:  # noqa: BLE001
            return {"error": f"brain write failed: {e}"}
        with self.lock:
            self.learn_state["lastLearnedAt"] = int(time.time() * 1000)
            self.learn_state["learnCount"] = self.learn_state.get("learnCount", 0) + 1
            self.learn_state["briefsSinceLearn"] = 0
            self._log("learn", f"Self-improved playbook ({'auto' if auto else 'manual'})")
            self._save()
        return {"ok": True, "learnCount": self.learn_state["learnCount"],
                "committed": res.get("committed"), "auto": auto}

    # --- console reads -------------------------------------------------------
    def cached_brief(self):
        """Instant, free — the last brief for the dashboard greeting."""
        return {"ok": True, "brief": self.last_brief, "generatedAt": self.last_brief_at,
                "briefCount": self.brief_count, "aiReady": bool(_ceo_key()),
                "learn": self.learn_state}

    def status(self):
        return {"ok": True, "agent": "orion", "name": "Orion", "title": "Chief of Staff",
                "aiReady": bool(_ceo_key()), "playbookLoaded": bool(self._playbook()),
                "briefCount": self.brief_count, "lastBriefAt": self.last_brief_at,
                "learn": self.learn_state, "lastError": self.last_error}

    def overview(self):
        return {"ok": True, **self.status(), "lastBrief": self.last_brief,
                "activity": list(reversed(self.activity[-30:]))}
