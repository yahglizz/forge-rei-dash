"""daycare_director.py — Solomon, the daycare's HEAD agent (executive director).

Solomon is the head of all daycare agents: a 30-year childcare executive director.
He reads the whole center — live ops metrics + alerts (Supabase), billing, staffing,
the growth channels, the connected-systems health (GHL / Stripe / Meta / Metricool),
and the business brief (forge-daycare/skills/daycare-context.md, read FIRST) — then
produces a prioritized OPERATING BRIEF (Attention Now, Enrollment, Money, People,
Delegations). He OWNS enrollment and DELEGATES the rest to role sub-agents via the
shared agent bus.

Solomon never takes an outward or irreversible action. No SMS, invoice send, ad
launch, or Supabase/GHL write. He proposes + delegates; a human taps to execute.
His ONLY autonomous writes are his own brain playbook (learn()) and bus notes —
same rule as Scout.

Mirrors the FORGE self-improving-agent pattern (scout_triage.py): own env folder +
key fallback, mtime-cached brain playbook, learn() self-improvement, agent_bus
comms, background loop gated by FORGE_MARCUS so only the box runs it. State persists
to marcus_state/solomon.json — no new database.
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
STATE = HERE / "marcus_state" / "solomon.json"
SOLOMON_DIR = HERE.parent / "forge-solomon"        # config + seed skills (outside web root)
_LOCK = threading.Lock()

PLAYBOOK_REL = "Skills/solomon-playbook.md"
BRIEF_DIR_REL = "Reports/daycare"          # living operating record written every brief
LEARN_EVERY = int(os.environ.get("FORGE_SOLOMON_LEARN_EVERY", "8"))
LEARN_MIN_INTERVAL_MS = int(os.environ.get("FORGE_SOLOMON_LEARN_GAP_MIN", "45")) * 60 * 1000
BRIEF_EVERY_MS = int(float(os.environ.get("FORGE_SOLOMON_BRIEF_EVERY_H", "6")) * 3600 * 1000)
POLL_INTERVAL = 900  # seconds between loop ticks (self-improve + due-brief check)

# Connected systems Solomon watches — (env key, display name). Presence only; he
# never reads or emits the secret value, only whether it is wired.
_SYSTEMS = [
    ("NEXT_PUBLIC_SUPABASE_URL", "Supabase (center data)"),
    ("GHL_API_KEY", "GoHighLevel (family SMS)"),
    ("STRIPE_SECRET_KEY", "Stripe (invoicing)"),
    ("META_ACCESS_TOKEN", "Meta Ads"),
    ("METRICOOL_USER_TOKEN", "Metricool (social)"),
]


def _load_env_file(p):
    """Fold forge-solomon/config/solomon.env into the environment (real env wins)."""
    try:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_env_file(SOLOMON_DIR / "config" / "solomon.env")


def _solomon_key():
    """Solomon's Anthropic key: own (SOLOMON_ANTHROPIC_API_KEY) → shared env →
    agency key → wholesale. Placeholder values ignored, so he runs before his
    own key is provisioned."""
    for env_key in ("SOLOMON_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
        v = os.environ.get(env_key)
        if v and not v.startswith("sk-ant-..."):
            return v
    try:
        import agency_eco
        k, _src = agency_eco._agency_key()
        if k:
            return k
    except Exception:
        pass
    return review_agent._api_key()


def connected_systems():
    """Report which daycare systems are wired — presence only, never the value.

    This is Solomon's read-access to the env: he learns what he can rely on
    without ever exposing a secret. Reads the daycare env the same way the rest
    of the daycare code does.
    """
    creds = {}
    try:
        import daycare_supabase
        creds = daycare_supabase._read_env() or {}
    except Exception:
        creds = {}
    out = []
    for key, name in _SYSTEMS:
        val = (os.environ.get(key) or creds.get(key) or "").strip()
        out.append({"key": key, "name": name, "connected": bool(val)})
    return out


def playbook_text(limit=2000):
    """Solomon's merged playbook (seed + vault) for chat grounding, no live instance."""
    parts = []
    try:
        import brain_io
        for p in (SOLOMON_DIR / "skills" / "solomon-playbook.md",
                  brain_io.VAULT / "Skills" / "solomon-playbook.md"):
            if p.is_file():
                parts.append(p.read_text(errors="ignore"))
    except Exception:
        pass
    return ("\n\n".join(parts))[:limit]


def _strip_fences(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


class SolomonEngine:
    """Solomon — the daycare's executive-director orchestrator."""

    def __init__(self):
        self.lock = threading.RLock()
        self.activity = []          # ring buffer of {ts, kind, text}
        self.last_error = None
        self.last_brief = None      # last operating brief dict
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
    # TOP skills load FIRST and are never truncated away: evidence discipline
    # (house rule for every agent) → decision loop (how Solomon reasons) →
    # director craft (what 50 years knows) → the learned playbook last.
    TOP_SKILLS = ("agent-evidence-discipline.md", "solomon-decision-loop.md",
                  "solomon-director-craft.md")
    PLAYBOOK_MD = "solomon-playbook.md"

    def _load_skills(self):
        """The CONSTITUTION: top skills + any other solomon-* skill, in priority order.

        Excludes the learned playbook (see _playbook_only) so the two get separate
        context budgets — the constitution is never truncated away by a long playbook,
        and self-improvement can never rewrite the constitution.
        """
        try:
            import brain_io
            seed = SOLOMON_DIR / "skills"
            vault = brain_io.VAULT / "Skills"
            skip = set(self.TOP_SKILLS) | {self.PLAYBOOK_MD}

            paths = []
            for name in self.TOP_SKILLS:           # top skills first, seed then vault
                paths += [seed / name, vault / name]
            for d in (seed, vault):                # then any other solomon-* skill
                if d.is_dir():
                    paths += sorted(p for p in d.glob("solomon-*.md")
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
        """ONLY the learned rubric (Skills/solomon-playbook.md) — never the top skills.

        learn() rewrites whatever it is given, so it must only ever see the playbook.
        The top skills (evidence discipline / decision loop / director craft) are the
        constitution: human-owned, stable, and NOT rewritten by self-improvement.
        """
        try:
            import brain_io
            parts = []
            for p in (SOLOMON_DIR / "skills" / self.PLAYBOOK_MD,
                      brain_io.VAULT / "Skills" / self.PLAYBOOK_MD):
                if p.is_file():
                    parts.append(p.read_text(errors="ignore"))
            return "\n\n".join(parts)
        except Exception:
            return ""

    # --- brain: read continuity + write the living operating record ----------
    def _recent_brain_context(self):
        """Pull the last operating brief + recent daycare notes from the vault so
        Solomon has continuity — utilizing the brain on READ, not just writing it."""
        try:
            import brain_io
            d = brain_io.VAULT / BRIEF_DIR_REL
            if not d.is_dir():
                return ""
            files = sorted([p for p in d.glob("*.md")],
                           key=lambda p: p.stat().st_mtime, reverse=True)[:2]
            if not files:
                return ""
            blocks = []
            for p in files:
                blocks.append(f"### {p.stem}\n" + p.read_text(errors="ignore")[:1200])
            return ("\n\n=== YOUR RECENT OPERATING RECORD (from the brain — build on "
                    "it, note what changed) ===\n" + "\n\n".join(blocks))
        except Exception:
            return ""

    def _write_brief_note(self, brief):
        """Write each operating brief into the vault (git-committed) so the daycare
        brain updates LIVE on every run and shows in the Brain tab."""
        try:
            import brain_io
            stamp = time.strftime("%Y-%m-%d %H%M")
            day = time.strftime("%Y-%m-%d")
            lines = [f"---", f"agent: solomon", f"kind: operating-brief", f"generated: {stamp}",
                     f"---", "", f"# Operating Brief — {day}", "",
                     f"**{brief.get('headline','')}**", ""]
            m = brief.get("metrics") or {}
            if m:
                lines.append("## Center snapshot")
                lines.append(f"- Enrolled {m.get('childrenActive','?')} · present {m.get('presentToday','?')} "
                             f"· staff {m.get('staffActive','?')} · capacity {m.get('capacityTotal','?')}")
                lines.append(f"- Invoices due {m.get('invoicesDue','?')} (${m.get('amountDue','?')}) "
                             f"· open incidents {m.get('openIncidents','?')} · unread {m.get('unreadNotifications','?')}")
                lines.append("")
            def _sec(title, items, fmt):
                if not items:
                    return
                lines.append(f"## {title}")
                for it in items:
                    lines.append("- " + fmt(it))
                lines.append("")
            _sec("Attention now", brief.get("priorities"),
                 lambda p: f"[{p.get('urgency','?')}/{p.get('area','?')}] {p.get('title','')} — {p.get('why','')}")
            _sec("Enrollment (Solomon owns)", brief.get("enrollment"), lambda s: str(s))
            _sec("Money", brief.get("money"), lambda s: str(s))
            _sec("People", brief.get("people"), lambda s: str(s))
            _sec("Delegations", brief.get("delegations"),
                 lambda d: f"**{d.get('role','team')}** → {d.get('task','')}  [[solomon-playbook]]")
            content = "\n".join(lines)
            res = brain_io.write_note(f"{BRIEF_DIR_REL}/brief-{day}.md", content,
                                      reason=f"solomon operating brief {stamp}")
            return bool(res.get("committed"))
        except Exception:
            return False

    # --- the operating brief -------------------------------------------------
    def _gather(self, session):
        """Pull the live center picture. Returns (metrics, alerts, err)."""
        if session is None:
            return {}, [], "no session"
        try:
            import daycare_supabase
            ov = daycare_supabase.get_overview(session)
            return ov.get("metrics", {}) or {}, ov.get("alerts", []) or [], None
        except Exception as e:  # noqa: BLE001 — brief still works from the context brief
            return {}, [], str(e)

    def build_brief(self, session=None):
        """Read the whole center + the brief, produce a prioritized operating brief.

        Read-only. Never contacts anyone. Delegations are recorded + posted to the
        bus for role agents; the human executes any outward action.
        """
        key = _solomon_key()
        if not key:
            return {"ok": False, "error": "no anthropic key"}

        import daycare_context
        ctx = daycare_context.context_block()
        metrics, alerts, gather_err = self._gather(session)
        systems = connected_systems()
        offline = [s["name"] for s in systems if not s["connected"]]

        skills = self._load_skills()      # constitution — never truncated
        playbook = self._playbook_only()  # learned rubric — own budget
        system = (
            "You are Solomon, the executive director of A Touch of Blessings Learning "
            "Academy with 50 years running childcare centers — the HEAD of the daycare's "
            "agents. Read the DAYCARE CONTEXT brief FIRST and never contradict its "
            "licensing, CCIS, pricing, or capacity facts. Build today's OPERATING BRIEF "
            "for the owner: rank ruthlessly, ground every point in the real data below, "
            "and tie everything to growing enrollment while keeping the center safe, "
            "staffed, and paid. You OWN enrollment. You DELEGATE other work to role "
            "agents (Enrollment, Billing, Family-Comms, Staffing, Compliance). You NEVER "
            "take an outward action — you surface and delegate; the human approves. "
            "EVIDENCE DISCIPLINE (outranks everything else): every number or status you "
            "state must come from the real data below or the brief — never from what "
            "sounds plausible. If you cannot reach a fact, say it is unknown and make "
            "finding it out a priority; an honest unknown beats a confident guess. Then "
            "CLOSE THE LOOP: once more looking would not change your recommendation, "
            "decide. Ship the brief with what you have and name the residual risk. "
            "Output ONLY valid JSON with keys: headline (string), priorities (array of "
            "{title, why, area, urgency}), enrollment (array of strings — concrete moves "
            "to book tours, grounded in the brief), money (array of strings), people "
            "(array of strings), delegations (array of {role, task}). 3–5 priorities, "
            "ranked; lead with anything unsafe / under-ratio / money-at-risk, then "
            "enrollment."
            + (ctx or "")
            + ("\n\n=== YOUR TOP SKILLS (the constitution — these OUTRANK the learned "
               "playbook below; when they conflict, these win) ===\n" + skills
               if skills else "")
            + ("\n\n=== YOUR PLAYBOOK (learned rubric — apply it within the skills "
               "above) ===\n" + playbook[:4000] if playbook else "")
            + self._recent_brain_context()
        )
        live = {
            "metrics": metrics,
            "alerts": alerts,
            "connectedSystems": [{"name": s["name"], "connected": s["connected"]} for s in systems],
            "offlineChannels": offline,
        }
        user = (
            "TODAY'S LIVE CENTER DATA (ground the brief in these — do not invent "
            "numbers):\n" + json.dumps(live, indent=2)
            + ("\n\n(Live ops metrics were unavailable this run — reason from the brief "
               "and connected-systems status; do not fabricate counts.)" if gather_err else "")
            + "\n\nProduce the operating brief now."
        )
        try:
            raw = _strip_fences(review_agent._claude(key, system, user, max_tokens=2600))
            parsed = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"brief: {e}"
            return {"ok": False, "error": f"brief generation failed: {e}"}

        brief = {
            "headline": parsed.get("headline", "Operating brief"),
            "priorities": parsed.get("priorities") or [],
            "enrollment": parsed.get("enrollment") or [],
            "money": parsed.get("money") or [],
            "people": parsed.get("people") or [],
            "delegations": parsed.get("delegations") or [],
            "metrics": metrics,
            "systems": systems,
            "generatedAt": int(time.time() * 1000),
            "contextLoaded": bool(ctx),
        }
        with self.lock:
            self.last_brief = brief
            self.last_brief_at = brief["generatedAt"]
            self.brief_count += 1
            self.learn_state["briefsSinceLearn"] = self.learn_state.get("briefsSinceLearn", 0) + 1
            self.last_error = gather_err if gather_err else None
            self._log("brief", f"Built operating brief — {len(brief['priorities'])} priorities, "
                               f"{len(brief['delegations'])} delegations")
            self._save()
        committed = self._write_brief_note(brief)   # live vault update every brief
        brief["brainCommitted"] = committed
        self._broadcast_brief(brief)
        return {"ok": True, "brief": brief, "gatherError": gather_err, "brainCommitted": committed}

    def _broadcast_brief(self, brief):
        """Post a status note + a delegation hand-off per role onto the shared bus."""
        try:
            import agent_bus
            agent_bus.send("solomon", "all", "status",
                           f"Solomon built the operating brief — {len(brief['priorities'])} "
                           f"priorities, {len(brief['delegations'])} delegations.",
                           {"briefCount": self.brief_count})
            for d in brief.get("delegations", [])[:8]:
                role = (d.get("role") or "team").strip()
                task = (d.get("task") or "").strip()
                if task:
                    agent_bus.send("solomon", role.lower(), "handoff",
                                   f"[{role}] {task}", {"role": role})
        except Exception:
            pass

    # --- self-improvement ----------------------------------------------------
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
        """Claude reflects on Solomon's recent briefs + current playbook, then rewrites
        his operating playbook into the brain (Skills/solomon-playbook.md, git-committed).
        Next brief reloads it — closed adaptive loop."""
        key = _solomon_key()
        if not key:
            return {"error": "no anthropic key"}
        with self.lock:
            recent = [a for a in self.activity if a.get("kind") == "brief"][-8:]
            last = self.last_brief
        sample = []
        if last:
            for p in (last.get("priorities") or [])[:5]:
                sample.append(f"priority[{p.get('urgency','?')}/{p.get('area','?')}] "
                              f"{p.get('title','')} — {p.get('why','')}")
            for e in (last.get("enrollment") or [])[:4]:
                sample.append(f"enrollment: {e}")
            for d in (last.get("delegations") or [])[:5]:
                sample.append(f"delegated → {d.get('role','?')}: {d.get('task','')}")
        if not sample:
            return {"error": "no briefs to learn from yet"}
        current = self._playbook_only() or "(no playbook yet — create one)"
        system = (
            "You are Solomon, a SELF-IMPROVING daycare executive director. Below is your "
            "CURRENT operating playbook and a sample of the briefs you actually produced. "
            "Improve yourself: sharpen how you rank priorities, tighten the enrollment "
            "plays that fit this specific daycare, refine which work you delegate to which "
            "role agent, and cut guidance that didn't help. Keep the hard rules (read the "
            "business brief first; never act outward; never quote a price or promise a "
            "start date the brief doesn't support; ground everything in real data; the "
            "JSON output contract). "
            "You ALSO carry separate, permanent top skills — evidence discipline, the "
            "decision loop, and director craft. Those are NOT yours to rewrite and are not "
            "shown here. Do not restate or summarize them in the playbook; assume they "
            "always apply and keep the playbook to what you have actually learned from "
            "running THIS center. Output the FULL UPDATED playbook as clean markdown — "
            "ONLY the markdown."
        )
        user = ("CURRENT PLAYBOOK:\n" + current[:4000]
                + "\n\nRECENT BRIEFS YOU PRODUCED (learn from these):\n" + "\n".join(sample))
        try:
            new_md = review_agent._claude(key, system, user, max_tokens=2400)
        except Exception as e:  # noqa: BLE001
            return {"error": f"claude: {e}"}
        if not new_md or len(new_md) < 200:
            return {"error": "learning produced nothing usable"}
        stamp = time.strftime("%Y-%m-%d %H:%M")
        header = (f"---\nagent: solomon\nupdated: {stamp}\n"
                  f"source: self-improvement (learned from {len(recent)} recent briefs)\n---\n\n")
        try:
            import brain_io
            res = brain_io.write_note(PLAYBOOK_REL, header + new_md.strip(),
                                      reason=f"solomon self-improve {stamp}")
        except Exception as e:  # noqa: BLE001
            return {"error": f"brain write failed: {e}"}
        with self.lock:
            self.learn_state["lastLearnedAt"] = int(time.time() * 1000)
            self.learn_state["learnCount"] = self.learn_state.get("learnCount", 0) + 1
            self.learn_state["briefsSinceLearn"] = 0
            self._sk_mtime = None  # force reload of the freshly-written playbook
            self._log("learn", f"Self-improved playbook from {len(sample)} brief signals "
                               f"({'auto' if auto else 'manual'})")
            self._save()
        try:
            import agent_bus
            agent_bus.send("solomon", "all", "status",
                           f"Solomon sharpened his operating playbook (self-improvement "
                           f"#{self.learn_state['learnCount']}).",
                           {"learnCount": self.learn_state["learnCount"]})
        except Exception:
            pass
        return {"ok": True, "learnCount": self.learn_state["learnCount"],
                "wrote": PLAYBOOK_REL, "committed": res.get("committed"), "auto": auto}

    def loaded_skill_names(self):
        """Which constitution skills are actually live (seed or vault) — so the console
        shows what Solomon is really running on rather than assuming."""
        try:
            import brain_io
            seed = SOLOMON_DIR / "skills"
            vault = brain_io.VAULT / "Skills"
            names = []
            for name in self.TOP_SKILLS:
                if (seed / name).is_file() or (vault / name).is_file():
                    names.append(name[:-3])
            for d in (seed, vault):
                if d.is_dir():
                    for p in sorted(d.glob("solomon-*.md")):
                        if p.name in set(self.TOP_SKILLS) | {self.PLAYBOOK_MD}:
                            continue
                        if p.stem not in names:
                            names.append(p.stem)
            return names
        except Exception:
            return []

    # --- console reads -------------------------------------------------------
    def status(self):
        key = _solomon_key()
        return {
            "ok": True,
            "agent": "solomon",
            "name": "Solomon",
            "title": "Executive Director",
            "aiReady": bool(key),
            "skillsLoaded": bool(self._load_skills()),
            "topSkills": self.loaded_skill_names(),
            "playbookLoaded": bool(self._playbook_only()),
            "systems": connected_systems(),
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

    # --- background loop (box only, FORGE_MARCUS gate) -----------------------
    def run_once(self, session=None):
        return self.build_brief(session)

    def run_forever(self):
        while True:
            try:
                if forge_ops.paused():
                    time.sleep(POLL_INTERVAL)
                    continue
                key = _solomon_key()
                # Due a fresh autonomous brief? Build one under an auto-admin session.
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
                    forge_heartbeat.beat("solomon", POLL_INTERVAL, "Solomon director",
                                         error=self.last_error)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL)
