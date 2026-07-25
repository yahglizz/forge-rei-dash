"""dropship_director.py — Midas, the dropship store's HEAD agent (e-com director).

Midas is the head of all dropship agents: an e-commerce operator. He reads the whole
store — Shopify (orders, products, inventory), AutoDS (sourcing), Meta ads, the
connected-systems health, and the business brief (forge-dropship/skills/
dropship-context.md, read FIRST) — then produces a prioritized OPERATING BRIEF
(Attention Now, Winners, Money, Ops, Delegations). He OWNS product strategy and
DELEGATES the rest to Hawk (research), Blaze (creative/ads), and Otto
(fulfillment/support) via the shared agent bus.

Midas never takes an outward or irreversible action. No ad launch, budget change,
supplier order, listing publish, or customer message. He proposes + delegates; a
human taps to execute. His ONLY autonomous writes are his own brain playbook
(learn()) and bus notes — same rule as Solomon.

Mirrors the FORGE self-improving-agent pattern (daycare_director.py): own env folder
+ key fallback, mtime-cached brain playbook, learn() self-improvement, agent_bus
comms, background loop gated by FORGE_MARCUS so only the box runs it. State persists
to marcus_state/midas.json — no new database.
"""
import contextlib
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
STATE = HERE / "marcus_state" / "midas.json"
DROPSHIP_DIR = HERE.parent / "forge-dropship"      # config + seed skills (outside web root)
_LOCK = threading.Lock()

PLAYBOOK_REL = "Skills/midas-playbook.md"
BRIEF_DIR_REL = "Reports/dropship"         # living operating record written every brief
LEARN_EVERY = int(os.environ.get("FORGE_DROPSHIP_LEARN_EVERY", "8"))
LEARN_MIN_INTERVAL_MS = int(os.environ.get("FORGE_DROPSHIP_LEARN_GAP_MIN", "45")) * 60 * 1000
BRIEF_EVERY_MS = int(float(os.environ.get("FORGE_DROPSHIP_BRIEF_EVERY_H", "24")) * 3600 * 1000)
POLL_INTERVAL = 900  # seconds between loop ticks (self-improve + due-brief check)

# Connected systems Midas watches — (env key, display name). Presence only; he
# never reads or emits the secret value, only whether it is wired.
_SYSTEMS = [
    ("SHOPIFY_ADMIN_TOKEN", "Shopify (store)"),
    ("AUTODS_API_KEY", "AutoDS (sourcing)"),
    ("PIPIADS_API_KEY", "PiPiAds (trend spy)"),
    ("META_ACCESS_TOKEN", "Meta Ads"),
    ("KLAVIYO_API_KEY", "Klaviyo (email/SMS)"),
    ("TIKTOK_ACCESS_TOKEN", "TikTok"),
    ("AFTERSHIP_API_KEY", "AfterShip (tracking)"),
]


# Keys that share a name with ANOTHER business's env are NEVER globally injected —
# they'd leak across workspaces (e.g. the agency reads META_ACCESS_TOKEN straight from
# os.environ). Dropship reads its own copies of these via dropship_env + a per-call
# scoped swap (Blaze's Meta), so keeping them file-only preserves isolation. Everything
# else in dropship.env is uniquely named (SHOPIFY_*, AUTODS_*, DROPSHIP_*, FORGE_DROPSHIP_*)
# and safe to expose.
_SHARED_PREFIXES = ("META_", "GHL_")


def _load_env_file(p):
    """Fold forge-dropship/config/dropship.env into the environment (real env wins),
    EXCEPT shared-namespace keys, which stay file-only to prevent cross-workspace leaks."""
    try:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if any(k.startswith(pre) for pre in _SHARED_PREFIXES):
                        continue
                    os.environ.setdefault(k, v.strip())
    except Exception:
        pass


_load_env_file(DROPSHIP_DIR / "config" / "dropship.env")


def _midas_key():
    """Midas's Anthropic key: own (DROPSHIP_ANTHROPIC_API_KEY) → shared env → agency
    key → wholesale. Placeholder values ignored, so he runs before his own key is
    provisioned."""
    for env_key in ("DROPSHIP_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
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
    """Report which dropship systems are wired — presence only, never the value.

    Reads the dropship env the same way the rest of the dropship code does, so Midas
    learns what he can rely on without ever exposing a secret.
    """
    creds = {}
    try:
        import dropship_env
        creds = dropship_env.read_env() or {}
    except Exception:
        creds = {}
    out = []
    for key, name in _SYSTEMS:
        val = (os.environ.get(key) or creds.get(key) or "").strip()
        # A template placeholder is not "connected".
        connected = bool(val) and not val.startswith("sk-ant-...") and "your-store" not in val
        out.append({"key": key, "name": name, "connected": connected})
    return out


def playbook_text(limit=2000):
    """Midas's merged playbook (seed + vault) for chat grounding, no live instance."""
    parts = []
    try:
        import brain_io
        for p in (DROPSHIP_DIR / "skills" / "midas-playbook.md",
                  brain_io.VAULT / "Skills" / "midas-playbook.md"):
            if p.is_file():
                parts.append(p.read_text(errors="ignore"))
    except Exception:
        pass
    return ("\n\n".join(parts))[:limit]


def _north_star_block():
    try:
        import north_star
        return north_star.context_block()
    except Exception:
        return ""


def _creed_block():
    try:
        import agent_creed
        return agent_creed.block("dropship")
    except Exception:
        return ""


def _strip_fences(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


# --- the store's OWN Meta creds, for one call (absorbed from Blaze) -----------
_META_KEYS = ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_MAP")
_ENV_LOCK = threading.Lock()


@contextlib.contextmanager
def _scoped_meta_env():
    """Overlay the dropship store's OWN Meta creds onto os.environ for one call, then
    restore — same trick as daycare_growth._scoped_env so the agency workspace is never
    disturbed. Always held under _ENV_LOCK by the caller."""
    creds = {}
    try:
        import dropship_env
        creds = dropship_env.read_env() or {}
    except Exception:
        creds = {}
    saved = {k: os.environ.get(k) for k in _META_KEYS}
    try:
        for k in _META_KEYS:
            value = (creds.get(k) or "").strip()
            if value:
                os.environ[k] = value
            else:
                os.environ.pop(k, None)
        yield
    finally:
        for k, prev in saved.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


class MidasEngine:
    """Midas — the dropship store's e-com-director orchestrator."""

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
    # Prompt order: CREED (dropship-evidence-discipline, via agent_creed — never
    # reachable from learn()) → TOP SKILLS below → the learned playbook last.
    # The two ad frameworks were Blaze's hardcoded floors; they're top skills now so
    # learn() still can't rewrite them (they load via _load_skills, never _playbook_only).
    TOP_SKILLS = ("midas-decision-loop.md", "midas-craft.md",
                  "dropship-four-triggers-ad-writer.md",
                  "dropship-meta-ads-diagnostician.md")
    PLAYBOOK_MD = "midas-playbook.md"

    def _load_skills(self):
        """The CONSTITUTION: top skills + any other midas-* skill, in priority order.
        Excludes the learned playbook (see _playbook_only) so the two get separate
        context budgets and self-improvement can never rewrite the constitution."""
        try:
            import brain_io
            seed = DROPSHIP_DIR / "skills"
            vault = brain_io.VAULT / "Skills"
            skip = set(self.TOP_SKILLS) | {self.PLAYBOOK_MD}

            paths = []
            for name in self.TOP_SKILLS:           # top skills first, seed then vault
                paths += [seed / name, vault / name]
            for d in (seed, vault):                # then any other midas-* skill
                if d.is_dir():
                    paths += sorted(p for p in d.glob("midas-*.md")
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
        """ONLY the learned rubric (Skills/midas-playbook.md) — never the top skills.
        learn() rewrites whatever it is given, so it must only ever see the playbook."""
        try:
            import brain_io
            parts = []
            for p in (DROPSHIP_DIR / "skills" / self.PLAYBOOK_MD,
                      brain_io.VAULT / "Skills" / self.PLAYBOOK_MD):
                if p.is_file():
                    parts.append(p.read_text(errors="ignore"))
            return "\n\n".join(parts)
        except Exception:
            return ""

    # --- brain: read continuity + write the living operating record ----------
    def _recent_brain_context(self):
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
        """Write each operating brief into the vault (git-committed) so the dropship
        brain updates LIVE on every run and shows in the Brain tab."""
        try:
            import brain_io
            stamp = time.strftime("%Y-%m-%d %H%M")
            day = time.strftime("%Y-%m-%d")
            lines = ["---", "agent: midas", "kind: operating-brief", f"generated: {stamp}",
                     "---", "", f"# Operating Brief — {day}", "",
                     f"**{brief.get('headline','')}**", ""]

            def _sec(title, items, fmt):
                if not items:
                    return
                lines.append(f"## {title}")
                for it in items:
                    lines.append("- " + fmt(it))
                lines.append("")
            _sec("Attention now", brief.get("priorities"),
                 lambda p: f"[{p.get('urgency','?')}/{p.get('area','?')}] {p.get('title','')} — {p.get('why','')}")
            _sec("Winners (Midas owns)", brief.get("winners"), lambda s: str(s))
            _sec("Money", brief.get("money"), lambda s: str(s))
            _sec("Ops", brief.get("ops"), lambda s: str(s))
            _sec("Delegations", brief.get("delegations"),
                 lambda d: f"**{d.get('role','team')}** → {d.get('task','')}  [[midas-playbook]]")
            content = "\n".join(lines)
            res = brain_io.write_note(f"{BRIEF_DIR_REL}/brief-{day}.md", content,
                                      reason=f"midas operating brief {stamp}")
            return bool(res.get("committed"))
        except Exception:
            return False

    # --- the operating brief -------------------------------------------------
    def _gather(self):
        """Pull the live store picture from Shopify + AutoDS. Returns (data, err)."""
        data = {}
        err = None
        try:
            import dropship_shopify
            data["shopify"] = dropship_shopify.snapshot()
        except Exception as e:  # noqa: BLE001 — brief still works from the brief
            err = f"shopify: {e}"
        try:
            import dropship_autods
            data["autods"] = dropship_autods.health()
        except Exception as e:  # noqa: BLE001
            err = (err + f"; autods: {e}") if err else f"autods: {e}"
        return data, err

    def build_brief(self):
        """Read the whole store + the brief, produce a prioritized operating brief.
        Read-only. Never contacts anyone. Delegations are recorded + posted to the
        bus for the specialists; the human executes any outward action."""
        key = _midas_key()
        if not key:
            return {"ok": False, "error": "no anthropic key"}

        import dropship_context
        ctx = dropship_context.context_block()
        live, gather_err = self._gather()
        systems = connected_systems()
        offline = [s["name"] for s in systems if not s["connected"]]

        skills = self._load_skills()      # constitution — never truncated
        playbook = self._playbook_only()  # learned rubric — own budget
        system = (
            "You are Midas, the e-commerce director of the FORGE Dropship store and the "
            "HEAD of its agents. Read the DROPSHIP CONTEXT brief FIRST and never contradict "
            "its niche, target margin, price bands, or supplier facts. Build today's "
            "OPERATING BRIEF for the operator: rank ruthlessly, ground every point in the "
            "real data below, and tie everything to growing PROFITABLE revenue while keeping "
            "the merchant + ad accounts healthy. You OWN product strategy. You DELEGATE the "
            "rest to Hawk (product research), Blaze (creative/ads), and Otto "
            "(fulfillment/support) — name one of those as the role so they pick the work up. "
            "You NEVER take an outward action — you surface and delegate; the human approves. "
            "EVIDENCE DISCIPLINE (outranks everything else): every number, metric, or margin "
            "you state must come from the real data below or the brief — never from what "
            "sounds plausible — and carries its source and window. Never call a product a "
            "winner or profitable without the margin math. If you cannot reach a fact, say "
            "it is Unknown and make finding it out a priority. Then CLOSE THE LOOP: once more "
            "looking would not change your recommendation, decide. "
            "Output ONLY valid JSON with keys: headline (string), priorities (array of "
            "{title, why, area, urgency}), winners (array of strings — products to "
            "scale/hold/kill, each tied to margin + signal), money (array of strings), ops "
            "(array of strings — fulfillment/support), delegations (array of {role, task}). "
            "3–5 priorities, ranked; lead with anything threatening the merchant/ad account "
            "or a fulfillment fire, then margin, then winners."
            + _north_star_block()
            + (ctx or "")
            + _creed_block()
            + ("\n\n=== YOUR TOP SKILLS (these OUTRANK the learned playbook below; when "
               "they conflict, these win) ===\n" + skills if skills else "")
            + ("\n\n=== YOUR PLAYBOOK (learned rubric — apply it within the skills above) "
               "===\n" + playbook[:4000] if playbook else "")
            + self._recent_brain_context()
        )
        payload = {
            "store": live,
            "connectedSystems": [{"name": s["name"], "connected": s["connected"]} for s in systems],
            "offlineChannels": offline,
        }
        user = (
            "TODAY'S LIVE STORE DATA (ground the brief in these — do not invent numbers, "
            "and label anything from a mock/unconnected channel as mock):\n"
            + json.dumps(payload, indent=2)
            + ("\n\n(Some live store data was unavailable this run — reason from the brief "
               "and connected-systems status; do not fabricate numbers.)" if gather_err else "")
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
            "winners": parsed.get("winners") or [],
            "money": parsed.get("money") or [],
            "ops": parsed.get("ops") or [],
            "delegations": parsed.get("delegations") or [],
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
            agent_bus.send("midas", "all", "status",
                           f"Midas built the operating brief — {len(brief['priorities'])} "
                           f"priorities, {len(brief['delegations'])} delegations.",
                           {"briefCount": self.brief_count})
            for d in brief.get("delegations", [])[:8]:
                role = (d.get("role") or "team").strip()
                task = (d.get("task") or "").strip()
                if task:
                    agent_bus.send("midas", role.lower(), "handoff",
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
        """Claude reflects on Midas's recent briefs + current playbook, then rewrites his
        operating playbook into the brain (Skills/midas-playbook.md, git-committed).
        Next brief reloads it — closed adaptive loop."""
        key = _midas_key()
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
            for w in (last.get("winners") or [])[:4]:
                sample.append(f"winner: {w}")
            for d in (last.get("delegations") or [])[:5]:
                sample.append(f"delegated → {d.get('role','?')}: {d.get('task','')}")
        if not sample:
            return {"error": "no briefs to learn from yet"}
        current = self._playbook_only() or "(no playbook yet — create one)"
        system = (
            "You are Midas, a SELF-IMPROVING e-commerce director. Below is your CURRENT "
            "operating playbook and a sample of the briefs you actually produced. Improve "
            "yourself: sharpen how you rank priorities, tighten the product/scaling calls "
            "that fit THIS store, refine which work you delegate to Hawk/Blaze/Otto, and cut "
            "guidance that didn't help. Keep the hard rules (read the business brief first; "
            "never act outward; never state a margin without real cost inputs; never call a "
            "product a winner without the signal + math; ground everything in real data; the "
            "JSON output contract). You ALSO carry separate, permanent top skills — evidence "
            "discipline, the decision loop, and e-com craft. Those are NOT yours to rewrite "
            "and are not shown here. Do not restate them; assume they always apply and keep "
            "the playbook to what you have actually learned running THIS store. Output the "
            "FULL UPDATED playbook as clean markdown — ONLY the markdown."
        )
        user = ("CURRENT PLAYBOOK:\n" + current[:4000]
                + "\n\nRECENT BRIEFS YOU PRODUCED (learn from these):\n" + "\n".join(sample))
        try:
            import agent_coach
            user += agent_coach.insights_block("midas", "dropship")
        except Exception:
            pass
        try:
            new_md = review_agent._claude(key, system, user, max_tokens=2400)
        except Exception as e:  # noqa: BLE001
            return {"error": f"claude: {e}"}
        if not new_md or len(new_md) < 200:
            return {"error": "learning produced nothing usable"}
        stamp = time.strftime("%Y-%m-%d %H:%M")
        header = (f"---\nagent: midas\nupdated: {stamp}\n"
                  f"source: self-improvement (learned from {len(recent)} recent briefs)\n---\n\n")
        try:
            import brain_io
            res = brain_io.write_note(PLAYBOOK_REL, header + new_md.strip(),
                                      reason=f"midas self-improve {stamp}")
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
            agent_bus.send("midas", "all", "status",
                           f"Midas sharpened his operating playbook (self-improvement "
                           f"#{self.learn_state['learnCount']}).",
                           {"learnCount": self.learn_state["learnCount"]})
        except Exception:
            pass
        return {"ok": True, "learnCount": self.learn_state["learnCount"],
                "wrote": PLAYBOOK_REL, "committed": res.get("committed"), "auto": auto}

    def loaded_skill_names(self):
        try:
            import brain_io
            seed = DROPSHIP_DIR / "skills"
            vault = brain_io.VAULT / "Skills"
            names = []
            for name in self.TOP_SKILLS:
                if (seed / name).is_file() or (vault / name).is_file():
                    names.append(name[:-3])
            for d in (seed, vault):
                if d.is_dir():
                    for p in sorted(d.glob("midas-*.md")):
                        if p.name in set(self.TOP_SKILLS) | {self.PLAYBOOK_MD}:
                            continue
                        if p.stem not in names:
                            names.append(p.stem)
            return names
        except Exception:
            return []

    # --- console reads -------------------------------------------------------
    def status(self):
        key = _midas_key()
        return {
            "ok": True,
            "agent": "midas",
            "name": "Midas",
            "title": "E-com Director",
            "aiReady": bool(key),
            "skillsLoaded": bool(self._load_skills()),
            "topSkills": self.loaded_skill_names(),
            "northStarLoaded": bool(_north_star_block()),
            "creedLoaded": bool(_creed_block()),
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

    # --- lane views (Hawk/Blaze/Otto's old consoles read these shapes) --------
    # The three specialists were merged into Midas on 2026-07-25. Their routes now
    # narrow his brief instead of running three more agents with three more playbooks.
    def _lane(self, name, title, keys):
        b = self.last_brief or {}
        lane = {k: b.get(k) for k in keys} if b else {}
        if b:
            lane["headline"] = b.get("headline", title)
            lane["generatedAt"] = b.get("generatedAt")
        return {"ok": True, **self.status(), "lane": name, "title": title,
                "brief": lane or None, "result": self.last_result,
                "lastBriefAt": self.last_brief_at,
                "activity": list(reversed(self.activity[-40:]))}

    def products_view(self):
        return self._lane("products", "Product Research", ("winners", "priorities"))

    def ads_view(self):
        return self._lane("ads", "Creative & Ads", ("ads", "priorities"))

    def ops_view(self):
        return self._lane("ops", "Fulfillment & Support", ("ops", "money"))

    # --- lane work (absorbed from Hawk / Blaze / Otto) ------------------------
    def analyze(self, task, data=None, max_tokens=1800, lane=""):
        """One grounded Claude call in Midas's own voice, for a lane task.

        Same constitution as the brief (creed → top skills → playbook) so a lane task
        and the daily brief are the same operator, not two personalities. Read-only:
        it returns a proposal, it never acts.
        """
        key = _midas_key()
        if not key:
            return {"ok": False, "error": "no anthropic key"}
        try:
            import dropship_context
            ctx = dropship_context.context_block()
        except Exception:
            ctx = ""
        skills = self._load_skills()
        playbook = self._playbook_only()
        system = (
            "You are Midas, the e-commerce director of the FORGE Dropship store. You run "
            "product research, creative & ads, and fulfillment & support yourself. Read the "
            "DROPSHIP CONTEXT brief FIRST and never contradict its niche, target margin, "
            "price bands, or supplier facts. You NEVER take an outward action — no ad "
            "launch, budget change, supplier order, listing edit, customer message, or "
            "refund. You propose; the operator approves. EVIDENCE DISCIPLINE outranks "
            "everything: every number carries its source and window, or is Unknown. Never "
            "call a product a winner without the margin math. Label anything from a mock or "
            "unconnected channel as mock."
            + (f" You are working the {lane} lane right now." if lane else "")
            + _north_star_block()
            + (ctx or "")
            + _creed_block()
            + ("\n\n=== YOUR TOP SKILLS (these OUTRANK the learned playbook below; when "
               "they conflict, these win) ===\n" + skills if skills else "")
            + ("\n\n=== YOUR PLAYBOOK (learned rubric — apply it within the skills above) "
               "===\n" + playbook[:4000] if playbook else "")
        )
        user = str(task or "").strip()
        if data is not None:
            user += ("\n\nGROUNDED DATA (use these — do not invent numbers; label mock/"
                     "unconnected channels as mock):\n"
                     + json.dumps(data, indent=2, default=str))
        user += "\n\nRespond with ONLY the JSON your playbook's output contract specifies."
        try:
            raw = _strip_fences(review_agent._claude(key, system, user, max_tokens=max_tokens))
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            return {"ok": False, "error": f"claude: {e}"}
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw": raw}
        with self.lock:
            self.last_result = parsed
            self._log("run", (parsed.get("headline") if isinstance(parsed, dict) else "")
                      or f"{lane or 'lane'} analysis")
            self._save()
        try:
            import agent_bus
            head = (parsed.get("headline") if isinstance(parsed, dict) else "") or ""
            agent_bus.send("midas", "all", "note",
                           f"Midas ran the {lane or 'lane'} analysis. {head}"[:300],
                           {"lane": lane})
        except Exception:
            pass
        return {"ok": True, "result": parsed}

    def research(self, payload=None):
        """Product research lane. payload: {ideas: "free text or list", data: {...}}.
        With no ideas, chews on the local watchlist so there's always something to score."""
        payload = payload or {}
        ideas = payload.get("ideas") or payload.get("task") or ""
        data = payload.get("data")
        if not ideas:
            try:
                import dropship_io
                wl = dropship_io.list_watchlist()
                data = {"watchlist": wl.get("items", [])}
                ideas = ("Score the current product watchlist below. For each, give a verdict "
                         "(test/pass/watch), grounded reasons, the biggest Unknown, and the "
                         "cheapest next step.")
            except Exception:
                ideas = "No product ideas provided. Ask the operator to add ideas to the watchlist."
        task = ("Research + score these product ideas per the Product Research output "
                "contract in your playbook.\n\nIDEAS:\n"
                + (ideas if isinstance(ideas, str) else json.dumps(ideas)))
        return self.analyze(task, data, lane="product research")

    def watch_score(self, item):
        """Deep single-product WATCH analysis for something on the operator's radar they
        can't dropship themselves yet. 1–10 upside read. Read-only proposal."""
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            return {"ok": False, "error": "product item with a name required"}
        contract = (
            "Output ONLY this JSON object, nothing else:\n"
            "{\n"
            '  "product": "<name>",\n'
            '  "score": <integer 1-10 — your honest read of how good this product can be>,\n'
            '  "verdict": "test|watch|pass",\n'
            '  "headline": "<one line: the core reason for the score>",\n'
            '  "winningNumbers": ["<a reason WITH a number: margin/markup, price band, '
            "demand signal, competition — ground it in the item data or the category; if "
            'you don\'t know it, write it as Unknown>", "..."],\n'
            '  "whyItWins": "<why it should sell: the problem it solves or the wow factor>",\n'
            '  "audience": "<who to target — the buyer>",\n'
            '  "adTypes": ["<ad FORMAT to make: UGC unboxing video, problem→agitate reel, '
            'before/after, demo, founder story, etc.>", "..."],\n'
            '  "adAngles": ["<a specific hook/angle to test in the copy>", "..."],\n'
            '  "biggestUnknown": "<the one thing that could kill it>",\n'
            '  "nextStep": "<the cheapest way to validate before committing>"\n'
            "}\n"
            "NEVER invent a fake metric — every number is grounded or labeled Unknown. The "
            "score weighs margin headroom, real demand signal, ad-ability, and fulfillment "
            "sanity, against saturation."
        )
        task = ("Analyze this ONE product the operator is WATCHING — they can't dropship it "
                "themselves yet and want to know how good it can be and how to attack it.\n\n"
                + contract)
        return self.analyze(task, {"product": item}, max_tokens=1600, lane="product research")

    def meta_overview(self):
        """Read-only Meta connection + analytics under the dropship account (mock until
        keyed). No Claude — instant for the Ads tab."""
        with _ENV_LOCK, _scoped_meta_env():
            try:
                import agency_ads
                return {
                    "ok": True,
                    "connection": agency_ads.connection(),
                    "accounts": agency_ads.accounts().get("accounts", []),
                    "analytics": agency_ads.analytics(client="dropship", days=7),
                }
            except Exception as e:  # noqa: BLE001
                return {"ok": True, "connection": {"connected": False},
                        "detail": f"Meta not available ({e})."}

    def analyze_ads(self, payload=None):
        """Creative & ads lane — read the store's Meta numbers, draft concepts."""
        payload = payload or {}
        analytics = None
        with _ENV_LOCK, _scoped_meta_env():
            try:
                import agency_ads
                conn = agency_ads.connection()
                if conn.get("connected") or conn.get("source") == "live":
                    analytics = agency_ads.analytics(client="dropship", days=7)
            except Exception:
                analytics = None
        task = (payload.get("task")
                or "Read the store's Meta ad performance, call scale/hold/kill/refresh on "
                   "what you can see, and draft 2–3 fresh ad concepts per the Creative & Ads "
                   "output contract in your playbook. If no live ad data is connected, say so "
                   "and draft concepts from the brief + brand voice instead of inventing "
                   "numbers.")
        data = payload.get("data") or ({"metaAnalytics": analytics} if analytics else
                                       {"metaAnalytics": "not connected (mock)"})
        return self.analyze(task, data, lane="creative & ads")

    def _store_data(self):
        data = {}
        try:
            import dropship_shopify
            data["orders"] = dropship_shopify.orders(limit=50)
            data["inventory"] = dropship_shopify.inventory()
        except Exception as e:  # noqa: BLE001
            data["error"] = str(e)
        return data

    def fulfillment_check(self, payload=None):
        """Fulfillment & support lane — health read from Shopify, plus a drafted reply
        when payload['ticket'] is present. Never sends, orders, or refunds."""
        payload = payload or {}
        data = self._store_data()
        ticket = payload.get("ticket")
        if ticket:
            task = ("Draft an honest, factual customer support reply to the ticket below, "
                    "grounded in the order/store data. Never invent a status or ship date. "
                    "Also flag any fulfillment risks you see. Per the Fulfillment & Support "
                    "output contract in your playbook.\n\nTICKET:\n" + str(ticket))
        else:
            task = ("Read the store's fulfillment health from the data below and surface the "
                    "risks (unshipped/late orders, stockouts, tracking gaps, refund signal), "
                    "ranked, each with a recommendation. Per the Fulfillment & Support output "
                    "contract in your playbook.")
        return self.analyze(task, data, lane="fulfillment & support")

    # --- background loop (box only, FORGE_MARCUS gate) -----------------------
    def run_once(self):
        return self.build_brief()

    def run_forever(self):
        while True:
            try:
                if forge_ops.paused():
                    time.sleep(POLL_INTERVAL)
                    continue
                key = _midas_key()
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
                    forge_heartbeat.beat("midas", POLL_INTERVAL, "Midas director",
                                         error=self.last_error)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL)
