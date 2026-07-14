"""daycare_family.py — Nora, the daycare's roster organizer & family follow-up agent.

Nora reports to Solomon (``daycare_director.py``) and picks up his
"Family-Comms" / "Enrollment" bus delegations. She has two jobs that share one
brief:

1. Keep the roster organized — flag new enrollments needing setup, existing
   kids with data gaps (missing guardian contact), and classroom capacity/ratio
   issues, all read straight from Supabase.
2. Follow up on family communications — after a Family Text Blast goes out
   (``daycare_blast.py``), surface families who need a nudge (opted out, a send
   that failed/skipped, no phone on file), grounded only in what the blast log
   actually recorded.

Nora never takes an outward or irreversible action. No SMS, no record write, no
message send. She proposes; a human executes via the existing Blast/Messages
tools. Her ONLY autonomous writes are her own brain playbook (``learn()``) and
bus notes — same rule as Solomon and Scout.

Mirrors the FORGE self-improving-agent pattern (``daycare_director.py`` /
``scout_triage.py``): own env folder + key fallback, mtime-cached brain
playbook, ``learn()`` self-improvement, ``agent_bus`` comms (including reading
her own bus inbox — the first daycare agent to actually consume Solomon's
delegations), background loop gated by ``FORGE_MARCUS`` so only the box runs
it. State persists to ``marcus_state/nora.json`` — no new database.
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
STATE = HERE / "marcus_state" / "nora.json"
NORA_DIR = HERE.parent / "forge-nora"        # config + seed skills (outside web root)

PLAYBOOK_REL = "Skills/nora-playbook.md"
BRIEF_DIR_REL = "Reports/nora"             # living operating record written every brief
BUS_ROLES = ("family-comms", "enrollment", "nora")   # bus identities she listens under
LEARN_EVERY = int(os.environ.get("FORGE_NORA_LEARN_EVERY", "8"))
LEARN_MIN_INTERVAL_MS = int(os.environ.get("FORGE_NORA_LEARN_GAP_MIN", "45")) * 60 * 1000
BRIEF_EVERY_MS = int(float(os.environ.get("FORGE_NORA_BRIEF_EVERY_H", "6")) * 3600 * 1000)
POLL_INTERVAL = 900  # seconds between loop ticks (self-improve + due-brief check)

RECENT_BLASTS = 3   # how many recent blasts to reason over per brief


def _load_env_file(p):
    """Fold forge-nora/config/nora.env into the environment (real env wins)."""
    try:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_env_file(NORA_DIR / "config" / "nora.env")


def _nora_key():
    """Nora's Anthropic key: own (NORA_ANTHROPIC_API_KEY) → shared env → Solomon's
    resolver (which itself falls back agency → wholesale). Placeholder values
    ignored, so she runs before her own key is provisioned."""
    for env_key in ("NORA_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
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


def _north_star_block():
    """The cross-business constitution — never truncated, frames everything below
    it. Sourced from north_star, which learn() cannot see, so self-improvement can
    never rewrite it."""
    try:
        import north_star
        return north_star.context_block()
    except Exception:
        return ""


def _creed_block():
    """The daycare creed (evidence discipline) — never truncated, outranks the playbook.
    Sourced from agent_creed, which learn() cannot see, so self-improvement can never
    rewrite it. Same creed Solomon and every daycare role agent run on."""
    try:
        import agent_creed
        return agent_creed.block("daycare")
    except Exception:
        return ""


def _strip_fences(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


class NoraEngine:
    """Nora — roster organizer & family follow-up, reporting to Solomon."""

    def __init__(self):
        self.lock = threading.RLock()
        self.activity = []          # ring buffer of {ts, kind, text}
        self.last_error = None
        self.last_brief = None      # last roster/follow-up brief dict
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
    # Prompt order: CREED (daycare-evidence-discipline, via agent_creed — never
    # reachable from learn()) → TOP SKILLS below → the learned playbook last.
    TOP_SKILLS = ("nora-decision-loop.md",)
    PLAYBOOK_MD = "nora-playbook.md"

    def _load_skills(self):
        """The CONSTITUTION: top skills + any other nora-* skill, in priority order.

        Excludes the learned playbook (see _playbook_only) so the two get separate
        context budgets, and self-improvement can never rewrite the constitution.
        """
        try:
            import brain_io
            seed = NORA_DIR / "skills"
            vault = brain_io.VAULT / "Skills"
            skip = set(self.TOP_SKILLS) | {self.PLAYBOOK_MD}

            paths = []
            for name in self.TOP_SKILLS:           # top skills first, seed then vault
                paths += [seed / name, vault / name]
            for d in (seed, vault):                # then any other nora-* skill
                if d.is_dir():
                    paths += sorted(p for p in d.glob("nora-*.md")
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
        """ONLY the learned rubric (Skills/nora-playbook.md) — never the top skills."""
        try:
            import brain_io
            parts = []
            for p in (NORA_DIR / "skills" / self.PLAYBOOK_MD,
                      brain_io.VAULT / "Skills" / self.PLAYBOOK_MD):
                if p.is_file():
                    parts.append(p.read_text(errors="ignore"))
            return "\n\n".join(parts)
        except Exception:
            return ""

    # --- bus: consume Solomon's delegations -----------------------------------
    def _read_bus_inbox(self, mark_read=True):
        """Pull unread messages addressed to Nora's bus identities and mark them
        read. First daycare agent to actually consume Solomon's hand-offs rather
        than just displaying the feed."""
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

    # --- the roster + follow-up brief -----------------------------------------
    def _gather(self, session):
        """Pull the live roster + recent blast history. Returns (data, err)."""
        if session is None:
            return {}, "no session"
        try:
            import daycare_supabase
            children = daycare_supabase.get_children(session).get("children", []) or []
            classrooms = daycare_supabase.get_classrooms(session).get("classrooms", []) or []
        except Exception as e:  # noqa: BLE001 — brief still works from blast data alone
            return {}, str(e)

        roster = {
            "childrenActive": sum(1 for c in children if c.get("active")),
            "childrenTotal": len(children),
            "missingGuardianContact": [
                {"child": c.get("first_name", "") + " " + c.get("last_name", ""),
                 "classroom": (c.get("classrooms") or {}).get("name")}
                for c in children
                if c.get("active") and not (
                    (c.get("guardian_profile") or {}).get("phone")
                    or (c.get("guardian_profile") or {}).get("auth_email"))
            ][:10],
            "classrooms": [
                {"name": r.get("name"), "capacity": r.get("capacity"),
                 "ratio": r.get("ratio_children"), "enrolled": r.get("enrolled")}
                for r in classrooms if r.get("active", True)
            ],
        }
        return roster, None

    def _gather_blasts(self):
        try:
            import daycare_blast
            blasts = daycare_blast.list_blasts()[:RECENT_BLASTS]
            optouts = daycare_blast.list_optouts()
        except Exception:
            return [], []
        summarized = []
        for b in blasts:
            recips = b.get("recipients") or []
            summarized.append({
                "id": b.get("id"), "title": b.get("title"), "audience": b.get("audience"),
                "status": b.get("status"), "sentAt": b.get("sentAt"),
                "recipientCount": len(recips),
                "skippedOptOut": b.get("skippedOptOut", 0),
                "notSent": [
                    {"name": r.get("name"), "note": r.get("note")}
                    for r in recips if r.get("status") not in ("sent", "stub-sent")
                ][:10],
            })
        return summarized, optouts

    def build_brief(self, session=None):
        """Read the roster + recent blast history, produce roster findings + named
        follow-up candidates. Read-only. Never contacts anyone."""
        key = _nora_key()
        if not key:
            return {"ok": False, "error": "no anthropic key"}

        import daycare_context
        ctx = daycare_context.context_block()
        roster, gather_err = self._gather(session)
        blasts, optouts = self._gather_blasts()
        inbox = self._read_bus_inbox()

        skills = self._load_skills()      # constitution — never truncated
        playbook = self._playbook_only()  # learned rubric — own budget
        system = (
            "You are Nora, the roster organizer and family follow-up lead for A "
            "Touch of Blessings Learning Academy. You report to Solomon and pick "
            "up his Family-Comms / Enrollment delegations. Read the DAYCARE "
            "CONTEXT brief FIRST and never contradict its facts. You have two "
            "jobs sharing one brief: keep the roster organized (new enrollments, "
            "data gaps, classroom capacity/ratio) and follow up on family "
            "communications (who needs a nudge after a Family Text Blast, "
            "grounded ONLY in what the blast log actually recorded — never invent "
            "a family's response). You NEVER take an outward action — you surface "
            "and delegate; the human approves. EVIDENCE DISCIPLINE outranks "
            "everything: every claim must come from the roster/blast data below "
            "or the brief — never from what sounds plausible. Unknown beats a "
            "guess. Output ONLY valid JSON with keys: headline (string), "
            "rosterFindings (array of {title, why, area, urgency}), followUps "
            "(array of {family, reason, suggestedNextStep}), delegationsSeen "
            "(array of strings — what you picked up from Solomon's bus inbox this "
            "run, empty if none). 3-6 roster findings + follow-ups combined, "
            "ranked; lead with any classroom over ratio/capacity or missing "
            "guardian contact, then follow-ups."
            + _north_star_block()
            + (ctx or "")
            + _creed_block()
            + ("\n\n=== YOUR TOP SKILLS (the constitution) ===\n" + skills if skills else "")
            + ("\n\n=== YOUR PLAYBOOK (learned rubric) ===\n" + playbook[:4000] if playbook else "")
        )
        live = {
            "roster": roster,
            "recentBlasts": blasts,
            "optOuts": len(optouts),
            "solomonDelegations": [
                {"from": m.get("from"), "text": m.get("text")} for m in inbox
            ],
        }
        user = (
            "TODAY'S LIVE ROSTER + BLAST DATA (ground the brief in these — do not "
            "invent findings):\n" + json.dumps(live, indent=2)
            + ("\n\n(Live roster data was unavailable this run — reason from the "
               "blast log + brief only; do not fabricate roster counts.)" if gather_err else "")
            + "\n\nProduce the roster & follow-up brief now."
        )
        try:
            raw = _strip_fences(review_agent._claude(key, system, user, max_tokens=2200))
            parsed = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"brief: {e}"
            return {"ok": False, "error": f"brief generation failed: {e}"}

        brief = {
            "headline": parsed.get("headline", "Roster & follow-up brief"),
            "rosterFindings": parsed.get("rosterFindings") or [],
            "followUps": parsed.get("followUps") or [],
            "delegationsSeen": parsed.get("delegationsSeen") or [],
            "roster": roster,
            "generatedAt": int(time.time() * 1000),
            "contextLoaded": bool(ctx),
        }
        with self.lock:
            self.last_brief = brief
            self.last_brief_at = brief["generatedAt"]
            self.brief_count += 1
            self.learn_state["briefsSinceLearn"] = self.learn_state.get("briefsSinceLearn", 0) + 1
            self.last_error = gather_err if gather_err else None
            self._log("brief", f"Built roster & follow-up brief — "
                               f"{len(brief['rosterFindings'])} roster findings, "
                               f"{len(brief['followUps'])} follow-ups")
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
            lines = [f"---", f"agent: nora", f"kind: roster-followup-brief",
                     f"generated: {stamp}", f"---", "",
                     f"# Roster & Follow-Up Brief — {day}", "",
                     f"**{brief.get('headline','')}**", ""]
            def _sec(title, items, fmt):
                if not items:
                    return
                lines.append(f"## {title}")
                for it in items:
                    lines.append("- " + fmt(it))
                lines.append("")
            _sec("Roster findings", brief.get("rosterFindings"),
                 lambda p: f"[{p.get('urgency','?')}/{p.get('area','?')}] {p.get('title','')} — {p.get('why','')}")
            _sec("Follow-ups", brief.get("followUps"),
                 lambda f: f"{f.get('family','?')} — {f.get('reason','')} → {f.get('suggestedNextStep','')}")
            content = "\n".join(lines)
            res = brain_io.write_note(f"{BRIEF_DIR_REL}/brief-{day}.md", content,
                                      reason=f"nora roster/followup brief {stamp}")
            return bool(res.get("committed"))
        except Exception:
            return False

    def _broadcast_brief(self, brief):
        try:
            import agent_bus
            agent_bus.send("nora", "solomon", "status",
                           f"Nora built the roster & follow-up brief — "
                           f"{len(brief['rosterFindings'])} roster findings, "
                           f"{len(brief['followUps'])} follow-ups.",
                           {"briefCount": self.brief_count})
            agent_bus.send("nora", "all", "status",
                           f"Nora: {brief.get('headline','')}", {})
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
        """Claude reflects on Nora's recent briefs + current playbook, then rewrites
        her operating playbook into the brain (Skills/nora-playbook.md, git-committed).
        Next brief reloads it — closed adaptive loop."""
        key = _nora_key()
        if not key:
            return {"error": "no anthropic key"}
        with self.lock:
            recent = [a for a in self.activity if a.get("kind") == "brief"][-8:]
            last = self.last_brief
        sample = []
        if last:
            for r in (last.get("rosterFindings") or [])[:5]:
                sample.append(f"roster[{r.get('urgency','?')}/{r.get('area','?')}] "
                              f"{r.get('title','')} — {r.get('why','')}")
            for f in (last.get("followUps") or [])[:5]:
                sample.append(f"followup: {f.get('family','?')} — {f.get('reason','')}")
        if not sample:
            return {"error": "no briefs to learn from yet"}
        current = self._playbook_only() or "(no playbook yet — create one)"
        system = (
            "You are Nora, a SELF-IMPROVING daycare roster & family follow-up "
            "agent. Below is your CURRENT operating playbook and a sample of the "
            "briefs you actually produced. Improve yourself: sharpen how you rank "
            "roster gaps vs. follow-ups, tighten which follow-up reasons are worth "
            "surfacing, and cut guidance that didn't help. Keep the hard rules "
            "(read the business brief first; never act outward; ground everything "
            "in real data; the JSON output contract). You ALSO carry a separate, "
            "permanent creed (evidence discipline) and a decision-loop skill — "
            "those are NOT yours to rewrite and are not shown here; assume they "
            "always apply. Output the FULL UPDATED playbook as clean markdown — "
            "ONLY the markdown."
        )
        user = ("CURRENT PLAYBOOK:\n" + current[:4000]
                + "\n\nRECENT BRIEFS YOU PRODUCED (learn from these):\n" + "\n".join(sample))
        try:
            import agent_coach
            user += agent_coach.insights_block("nora", "daycare")
        except Exception:
            pass
        try:
            new_md = review_agent._claude(key, system, user, max_tokens=2000)
        except Exception as e:  # noqa: BLE001
            return {"error": f"claude: {e}"}
        if not new_md or len(new_md) < 150:
            return {"error": "learning produced nothing usable"}
        stamp = time.strftime("%Y-%m-%d %H:%M")
        header = (f"---\nagent: nora\nupdated: {stamp}\n"
                  f"source: self-improvement (learned from {len(recent)} recent briefs)\n---\n\n")
        try:
            import brain_io
            res = brain_io.write_note(PLAYBOOK_REL, header + new_md.strip(),
                                      reason=f"nora self-improve {stamp}")
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
            agent_bus.send("nora", "all", "status",
                           f"Nora sharpened her operating playbook (self-improvement "
                           f"#{self.learn_state['learnCount']}).",
                           {"learnCount": self.learn_state["learnCount"]})
        except Exception:
            pass
        return {"ok": True, "learnCount": self.learn_state["learnCount"],
                "wrote": PLAYBOOK_REL, "committed": res.get("committed"), "auto": auto}

    def loaded_skill_names(self):
        try:
            import brain_io
            seed = NORA_DIR / "skills"
            vault = brain_io.VAULT / "Skills"
            names = []
            for name in self.TOP_SKILLS:
                if (seed / name).is_file() or (vault / name).is_file():
                    names.append(name[:-3])
            for d in (seed, vault):
                if d.is_dir():
                    for p in sorted(d.glob("nora-*.md")):
                        if p.name in set(self.TOP_SKILLS) | {self.PLAYBOOK_MD}:
                            continue
                        if p.stem not in names:
                            names.append(p.stem)
            return names
        except Exception:
            return []

    # --- console reads ----------------------------------------------------------
    def status(self):
        key = _nora_key()
        return {
            "ok": True,
            "agent": "nora",
            "name": "Nora",
            "title": "Roster Organizer & Family Follow-Up",
            "aiReady": bool(key),
            "skillsLoaded": bool(self._load_skills()),
            "topSkills": self.loaded_skill_names(),
            "northStarLoaded": bool(_north_star_block()),
            "creedLoaded": bool(_creed_block()),
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
                key = _nora_key()
                now = int(time.time() * 1000)
                due = (self.last_brief_at is None
                       or (now - self.last_brief_at) >= BRIEF_EVERY_MS)
                if due and key:
                    session = None
                    try:
                        import daycare_supabase
                        session = daycare_supabase.BRIDGE.autoadmin_session("127.0.0.1")
                    except Exception:
                        session = None
                    self.build_brief(session)
                self._maybe_learn(key)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"loop: {e}"
            finally:
                try:
                    forge_heartbeat.beat("nora", POLL_INTERVAL, "Nora roster & follow-up",
                                         error=self.last_error)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL)
