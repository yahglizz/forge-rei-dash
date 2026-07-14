"""daycare_adops.py — Nova, the daycare's ad ops agent.

Nova reports to Solomon (``daycare_director.py``) and picks up his "Ads" /
"Enrollment" bus delegations. She runs point on:

1. Campaign health — is the daycare's Meta account connected, and if so, is
   anything broken or underperforming (``daycare_growth.ads_overview``).
2. Competitor intel — reuses the existing daycare-scoped competitor read
   (``agency_eco._daycare_competitor``) rather than re-deriving it.
3. Creative direction — which of the live angles (Urgency / Trust / Offer, per
   ``forge-daycare/skills/enrollment-ad-agent.md``) needs fresh creative, and
   what to generate.

Nova never launches or activates a campaign, changes budget, or generates a
Higgsfield image herself — the background loop has no tool access to Meta Ads
Manager or Higgsfield (those are MCP tools available only in a chat/agent
session). She recommends; the owner (or a chat session with those tools) acts
on her delegation. Her ONLY autonomous writes are her own brain playbook
(``learn()``) and bus notes — same rule as Solomon and Nora.

Mirrors the FORGE self-improving-agent pattern (``daycare_director.py`` /
``daycare_family.py``): own env folder + key fallback, mtime-cached brain
playbook, ``learn()`` self-improvement, ``agent_bus`` comms (incl. reading her
own bus inbox), background loop gated by ``FORGE_MARCUS``. State persists to
``marcus_state/nova.json`` — no new database.
"""
import json
import os
import threading
import time
from pathlib import Path

import forge_atomic
import forge_heartbeat
import forge_ops
import review_agent

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "nova.json"
NOVA_DIR = HERE.parent / "forge-nova"        # config + seed skills (outside web root)

PLAYBOOK_REL = "Skills/nova-playbook.md"
BRIEF_DIR_REL = "Reports/nova"             # living operating record written every brief
BUS_ROLES = ("ads", "growth", "enrollment", "nova")   # bus identities she listens under
LEARN_EVERY = int(os.environ.get("FORGE_NOVA_LEARN_EVERY", "8"))
LEARN_MIN_INTERVAL_MS = int(os.environ.get("FORGE_NOVA_LEARN_GAP_MIN", "45")) * 60 * 1000
BRIEF_EVERY_MS = int(float(os.environ.get("FORGE_NOVA_BRIEF_EVERY_H", "6")) * 3600 * 1000)
POLL_INTERVAL = 900  # seconds between loop ticks (self-improve + due-brief check)


def _load_env_file(p):
    """Fold forge-nova/config/nova.env into the environment (real env wins)."""
    try:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_env_file(NOVA_DIR / "config" / "nova.env")


def _nova_key():
    """Nova's Anthropic key: own (NOVA_ANTHROPIC_API_KEY) → shared env → Solomon's
    resolver (which itself falls back agency → wholesale). Placeholder values
    ignored, so she runs before her own key is provisioned."""
    for env_key in ("NOVA_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
        v = os.environ.get(env_key)
        if v and not v.startswith("sk-ant-..."):
            return v
    try:
        import daycare_director
        k = daycare_director._solomon_key()
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


class NovaEngine:
    """Nova — ad ops: campaign health, competitor intel, creative direction."""

    def __init__(self):
        self.lock = threading.RLock()
        self.activity = []          # ring buffer of {ts, kind, text}
        self.last_error = None
        self.last_brief = None      # last ad-ops brief dict
        self.last_brief_at = None
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
                "briefCount": self.brief_count,
                "learnState": self.learn_state,
            })
        except Exception:
            pass

    def _log(self, kind, text):
        self.activity.append({"ts": int(time.time() * 1000), "kind": kind, "text": text})
        self.activity = self.activity[-120:]

    # --- brain skills (mtime-cached seed + vault) ----------------------------
    TOP_SKILLS = ("agent-evidence-discipline.md", "nova-decision-loop.md")
    PLAYBOOK_MD = "nova-playbook.md"

    def _load_skills(self):
        """The CONSTITUTION: top skills + any other nova-* skill, in priority order.

        Excludes the learned playbook (see _playbook_only) so the two get separate
        context budgets, and self-improvement can never rewrite the constitution.
        """
        try:
            import brain_io
            seed = NOVA_DIR / "skills"
            vault = brain_io.VAULT / "Skills"
            skip = set(self.TOP_SKILLS) | {self.PLAYBOOK_MD}

            paths = []
            for name in self.TOP_SKILLS:
                paths += [seed / name, vault / name]
            for d in (seed, vault):
                if d.is_dir():
                    paths += sorted(p for p in d.glob("nova-*.md")
                                    if p.name not in skip)

            parts, sig, seen = [], [], set()
            for p in paths:
                rp = str(p)
                if rp in seen or not p.is_file():
                    continue
                seen.add(rp)
                parts.append(p.read_text(errors="ignore"))
                sig.append((rp, p.stat().st_mtime))
            sig = tuple(sig)
            if self._sk_mtime != sig:
                self._sk_text = "\n\n---\n\n".join(parts)
                self._sk_mtime = sig
            return self._sk_text
        except Exception:
            return self._sk_text

    def _playbook_only(self):
        """ONLY the learned rubric (Skills/nova-playbook.md) — never the top skills."""
        try:
            import brain_io
            parts = []
            for p in (NOVA_DIR / "skills" / self.PLAYBOOK_MD,
                      brain_io.VAULT / "Skills" / self.PLAYBOOK_MD):
                if p.is_file():
                    parts.append(p.read_text(errors="ignore"))
            return "\n\n".join(parts)
        except Exception:
            return ""

    # --- bus: consume Solomon's delegations -----------------------------------
    def _read_bus_inbox(self, mark_read=True):
        try:
            import agent_bus
        except Exception:
            return []
        seen_ids, out = set(), []
        for role in BUS_ROLES:
            try:
                res = agent_bus.inbox(role, unread_only=True)
            except Exception:
                continue
            for m in (res.get("messages") or [])[:10]:
                mid = m.get("id")
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    out.append(m)
                if mark_read and mid:
                    try:
                        agent_bus.mark_read(mid)
                    except Exception:
                        pass
        out.sort(key=lambda m: -(m.get("ts") or 0))
        return out[:10]

    # --- the ad-ops brief -------------------------------------------------------
    def _gather(self):
        """Pull campaign health + competitor read. Returns (data, err)."""
        try:
            import daycare_growth
            ads = daycare_growth.ads_overview()
        except Exception as e:  # noqa: BLE001 — brief still works from the brief alone
            return {}, str(e)
        connection = ads.get("connection") or {}
        return {
            "connected": bool(connection.get("connected") or connection.get("source") == "live"),
            "source": connection.get("source"),
            "accounts": ads.get("accounts") or [],
            "analytics": ads.get("analytics") or {},
        }, None

    def _gather_competitor(self, key):
        try:
            import agency_eco
            import daycare_context
            return agency_eco._daycare_competitor(daycare_context.context_block(), key)
        except Exception as e:  # noqa: BLE001 — competitor read is best-effort
            return {"status": "unavailable", "error": str(e)}

    def build_brief(self, session=None):
        """Read campaign health + competitor intel, produce ranked ad-ops
        recommendations. Read-only. Never launches or spends anything."""
        key = _nova_key()
        if not key:
            return {"ok": False, "error": "no anthropic key"}

        import daycare_context
        ctx = daycare_context.context_block() + daycare_context.ad_agent_block()
        campaign, gather_err = self._gather()
        competitor = self._gather_competitor(key)
        inbox = self._read_bus_inbox()

        skills = self._load_skills()      # constitution — never truncated
        playbook = self._playbook_only()  # learned rubric — own budget
        system = (
            "You are Nova, the ad ops lead for A Touch of Blessings Learning "
            "Academy. You report to Solomon and pick up his Ads / Enrollment "
            "delegations. Read the DAYCARE CONTEXT and ENROLLMENT AD AGENT SPEC "
            "below FIRST — they hold the real Meta account, live angles, ad copy, "
            "image prompts, and targeting; use those exact assets, never invent "
            "new ones. You run point on: campaign health, competitor intel, and "
            "which live angle (Urgency/Trust/Offer) needs fresh creative. You "
            "NEVER launch, activate, or change budget on a campaign, and you "
            "never generate a Higgsfield image yourself — you have no tool "
            "access to them from this loop. You recommend; the owner (or a chat "
            "session with those tools) executes. EVIDENCE DISCIPLINE outranks "
            "everything: ground every number in the campaign data below — if "
            "the Meta account isn't connected, say so plainly instead of "
            "describing mock data as real. Output ONLY valid JSON with keys: "
            "headline (string), campaignHealth (array of {title, why, urgency}), "
            "competitorRead (object: {summary, angles, gap}), "
            "creativeRecommendations (array of {angle, why, action}), "
            "delegationsSeen (array of strings, empty if none). All new "
            "campaigns you ever reference start PAUSED."
            + (ctx or "")
            + ("\n\n=== YOUR TOP SKILLS (the constitution) ===\n" + skills if skills else "")
            + ("\n\n=== YOUR PLAYBOOK (learned rubric) ===\n" + playbook[:4000] if playbook else "")
        )
        live = {
            "campaign": campaign,
            "competitor": competitor,
            "solomonDelegations": [
                {"from": m.get("from"), "text": m.get("text")} for m in inbox
            ],
        }
        user = (
            "TODAY'S LIVE CAMPAIGN + COMPETITOR DATA (ground the brief in these — "
            "do not invent metrics):\n" + json.dumps(live, indent=2)
            + ("\n\n(Campaign data was unavailable this run — reason from the "
               "brief + competitor read only; do not fabricate ad performance "
               "numbers.)" if gather_err else "")
            + "\n\nProduce the ad-ops brief now."
        )
        try:
            raw = _strip_fences(review_agent._claude(key, system, user, max_tokens=2400))
            parsed = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"brief: {e}"
            return {"ok": False, "error": f"brief generation failed: {e}"}

        brief = {
            "headline": parsed.get("headline", "Ad ops brief"),
            "campaignHealth": parsed.get("campaignHealth") or [],
            "competitorRead": parsed.get("competitorRead") or {},
            "creativeRecommendations": parsed.get("creativeRecommendations") or [],
            "delegationsSeen": parsed.get("delegationsSeen") or [],
            "campaign": campaign,
            "generatedAt": int(time.time() * 1000),
            "contextLoaded": bool(ctx),
        }
        with self.lock:
            self.last_brief = brief
            self.last_brief_at = brief["generatedAt"]
            self.brief_count += 1
            self.learn_state["briefsSinceLearn"] = self.learn_state.get("briefsSinceLearn", 0) + 1
            self.last_error = gather_err if gather_err else None
            self._log("brief", f"Built ad ops brief — "
                               f"{len(brief['campaignHealth'])} campaign items, "
                               f"{len(brief['creativeRecommendations'])} creative recs")
            self._save()
        committed = self._write_brief_note(brief)
        brief["brainCommitted"] = committed
        self._broadcast_brief(brief)
        return {"ok": True, "brief": brief, "gatherError": gather_err, "brainCommitted": committed}

    def _write_brief_note(self, brief):
        try:
            import brain_io
            stamp = time.strftime("%Y-%m-%d %H%M")
            day = time.strftime("%Y-%m-%d")
            lines = [f"---", f"agent: nova", f"kind: adops-brief",
                     f"generated: {stamp}", f"---", "",
                     f"# Ad Ops Brief — {day}", "",
                     f"**{brief.get('headline','')}**", ""]
            def _sec(title, items, fmt):
                if not items:
                    return
                lines.append(f"## {title}")
                for it in items:
                    lines.append("- " + fmt(it))
                lines.append("")
            _sec("Campaign health", brief.get("campaignHealth"),
                 lambda p: f"[{p.get('urgency','?')}] {p.get('title','')} — {p.get('why','')}")
            _sec("Creative recommendations", brief.get("creativeRecommendations"),
                 lambda c: f"{c.get('angle','?')} — {c.get('why','')} → {c.get('action','')}")
            content = "\n".join(lines)
            res = brain_io.write_note(f"{BRIEF_DIR_REL}/brief-{day}.md", content,
                                      reason=f"nova ad-ops brief {stamp}")
            return bool(res.get("committed"))
        except Exception:
            return False

    def _broadcast_brief(self, brief):
        try:
            import agent_bus
            agent_bus.send("nova", "solomon", "status",
                           f"Nova built the ad ops brief — "
                           f"{len(brief['campaignHealth'])} campaign items, "
                           f"{len(brief['creativeRecommendations'])} creative recs.",
                           {"briefCount": self.brief_count})
            agent_bus.send("nova", "all", "status",
                           f"Nova: {brief.get('headline','')}", {})
        except Exception:
            pass

    # --- self-improvement ------------------------------------------------------
    def _maybe_learn(self, key):
        now = int(time.time() * 1000)
        st = self.learn_state
        if (key and st.get("briefsSinceLearn", 0) >= LEARN_EVERY
                and (now - (st.get("lastLearnedAt") or 0)) >= LEARN_MIN_INTERVAL_MS):
            try:
                self.learn(auto=True)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"learn: {e}"

    def learn(self, auto=False):
        """Claude reflects on Nova's recent briefs + current playbook, then rewrites
        her operating playbook into the brain (Skills/nova-playbook.md, git-committed).
        Next brief reloads it — closed adaptive loop."""
        key = _nova_key()
        if not key:
            return {"error": "no anthropic key"}
        with self.lock:
            recent = [a for a in self.activity if a.get("kind") == "brief"][-8:]
            last = self.last_brief
        sample = []
        if last:
            for c in (last.get("campaignHealth") or [])[:5]:
                sample.append(f"campaign[{c.get('urgency','?')}] "
                              f"{c.get('title','')} — {c.get('why','')}")
            for r in (last.get("creativeRecommendations") or [])[:5]:
                sample.append(f"creative: {r.get('angle','?')} — {r.get('why','')} → {r.get('action','')}")
        if not sample:
            return {"error": "no briefs to learn from yet"}
        current = self._playbook_only() or "(no playbook yet — create one)"
        system = (
            "You are Nova, a SELF-IMPROVING daycare ad ops agent. Below is your "
            "CURRENT operating playbook and a sample of the briefs you actually "
            "produced. Improve yourself: sharpen how you rank campaign health vs. "
            "creative recommendations, tighten which competitor gaps are worth "
            "surfacing, and cut guidance that didn't help. Keep the hard rules "
            "(read the business brief + ad agent spec first; never launch/spend/ "
            "generate creative yourself; ground everything in real data; the JSON "
            "output contract; all new campaigns start PAUSED). Output the FULL "
            "UPDATED playbook as clean markdown — ONLY the markdown."
        )
        user = ("CURRENT PLAYBOOK:\n" + current[:4000]
                + "\n\nRECENT BRIEFS YOU PRODUCED (learn from these):\n" + "\n".join(sample))
        try:
            new_md = review_agent._claude(key, system, user, max_tokens=2000)
        except Exception as e:  # noqa: BLE001
            return {"error": f"claude: {e}"}
        if not new_md or len(new_md) < 150:
            return {"error": "learning produced nothing usable"}
        stamp = time.strftime("%Y-%m-%d %H:%M")
        header = (f"---\nagent: nova\nupdated: {stamp}\n"
                  f"source: self-improvement (learned from {len(recent)} recent briefs)\n---\n\n")
        try:
            import brain_io
            res = brain_io.write_note(PLAYBOOK_REL, header + new_md.strip(),
                                      reason=f"nova self-improve {stamp}")
        except Exception as e:  # noqa: BLE001
            return {"error": f"brain write failed: {e}"}
        with self.lock:
            self.learn_state["lastLearnedAt"] = int(time.time() * 1000)
            self.learn_state["learnCount"] = self.learn_state.get("learnCount", 0) + 1
            self.learn_state["briefsSinceLearn"] = 0
            self._sk_mtime = None
            self._log("learn", f"Self-improved playbook from {len(sample)} brief signals "
                               f"({'auto' if auto else 'manual'})")
            self._save()
        try:
            import agent_bus
            agent_bus.send("nova", "all", "status",
                           f"Nova sharpened her operating playbook (self-improvement "
                           f"#{self.learn_state['learnCount']}).",
                           {"learnCount": self.learn_state["learnCount"]})
        except Exception:
            pass
        return {"ok": True, "learnCount": self.learn_state["learnCount"],
                "wrote": PLAYBOOK_REL, "committed": res.get("committed"), "auto": auto}

    def loaded_skill_names(self):
        try:
            import brain_io
            seed = NOVA_DIR / "skills"
            vault = brain_io.VAULT / "Skills"
            names = []
            for name in self.TOP_SKILLS:
                if (seed / name).is_file() or (vault / name).is_file():
                    names.append(name[:-3])
            for d in (seed, vault):
                if d.is_dir():
                    for p in sorted(d.glob("nova-*.md")):
                        if p.name in set(self.TOP_SKILLS) | {self.PLAYBOOK_MD}:
                            continue
                        if p.stem not in names:
                            names.append(p.stem)
            return names
        except Exception:
            return []

    # --- console reads ----------------------------------------------------------
    def status(self):
        key = _nova_key()
        return {
            "ok": True,
            "agent": "nova",
            "name": "Nova",
            "title": "Ad Ops",
            "aiReady": bool(key),
            "skillsLoaded": bool(self._load_skills()),
            "topSkills": self.loaded_skill_names(),
            "playbookLoaded": bool(self._playbook_only()),
            "briefCount": self.brief_count,
            "lastBriefAt": self.last_brief_at,
            "learn": self.learn_state,
            "lastError": self.last_error,
        }

    def overview(self):
        return {"ok": True, **self.status(), "brief": self.last_brief,
                "activity": list(reversed(self.activity[-40:]))}

    def brief(self):
        return {"ok": True, "brief": self.last_brief, "lastBriefAt": self.last_brief_at}

    # --- background loop (box only, FORGE_MARCUS gate) ---------------------------
    def run_once(self, session=None):
        return self.build_brief(session)

    def run_forever(self):
        while True:
            try:
                if forge_ops.paused():
                    time.sleep(POLL_INTERVAL)
                    continue
                key = _nova_key()
                now = int(time.time() * 1000)
                due = (self.last_brief_at is None
                       or (now - self.last_brief_at) >= BRIEF_EVERY_MS)
                if due and key:
                    self.build_brief()
                self._maybe_learn(key)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"loop: {e}"
            finally:
                try:
                    forge_heartbeat.beat("nova", POLL_INTERVAL, "Nova ad ops",
                                         error=self.last_error)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL)
