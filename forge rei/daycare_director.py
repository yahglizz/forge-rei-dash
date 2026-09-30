"""daycare_director.py — Solomon, the daycare's HEAD agent (executive director).

Solomon is the daycare's GROWTH director (2026-09-30, owner decision: enrollment only —
paperwork, compliance, billing collections and staff admin are not his lane). He reads
the lead flow (Lead/Reply/Starts desks), seats per classroom (Supabase), retention
signals, the growth channels (Meta / Metricool) and the business brief
(forge-daycare/skills/daycare-context.md, read FIRST) — then produces a ranked GROWTH
BRIEF (Attention Now, Enrollment, growth economics, capacity, Seats, Keep + refer,
Campaign Health, Creative, Delegations). The JSON keys are unchanged (money/people/
roster/followUps) so every UI surface keeps working.

2026-07-25: the daycare crew collapsed into one director. Nora (roster + family
follow-ups) and Nova (ad ops) were merged into Solomon — their craft skills live on as
solomon-roster-craft.md / solomon-adops-craft.md (top skills, never rewritten by learn()),
their data reads are the _gather_roster/_gather_blasts/_gather_campaign/_gather_competitor
methods below, and their old routes narrow this brief via roster_view()/adops_view().
One brief, one Claude call, one auto-admin session — instead of three of each.

2026-09-24: Solomon is the daycare's ONE agent and owns three lanes:
  • the brief (this engine)  — the director's operating brief, every
    FORGE_SOLOMON_BRIEF_EVERY_H hours (heartbeat `solomon`);
  • Solomon · Replies        — daycare_replies.py (the Reply Desk): drafts the next text
    to every parent owed a reply; the OWNER approves + sends each one (heartbeat
    `daycare_replies`, knob FORGE_DAYCARE_REPLIES);
  • Solomon · Leads          — daycare_leads.py (the Lead Desk): GET-only GHL enrollment
    lead sweep, zero Claude (heartbeat `daycare_leads`, knob FORGE_DAYCARE_LEADS).
The lane loops keep their own threads, state files and routes; they report here —
reply_desk_state() / lead_desk_state() feed the brief (replyDesk / leadDesk), his chat
and his Agent Control Center row, and their spend bills to `solomon`.

Solomon never takes an outward or irreversible action. No SMS, invoice send, ad
launch, or Supabase/GHL write. He proposes + delegates; a human taps to execute. (His Replies lane drafts family
texts, but only the owner's tap sends one — the brief itself never writes family text.)
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
# Bus identities Solomon answers to. The role names Nora and Nova used are kept so
# delegations already on the bus (and anything Solomon addresses to a role in his own
# brief) still get consumed now that he owns those lanes himself. Same for his Replies
# and Leads lanes: a task filed to the old `daycare_replies` hub id, or anything sent to
# `daycare_leads`, lands in his brief.
BUS_ROLES = ("solomon", "family-comms", "enrollment", "ads", "growth", "nora", "nova",
             "daycare_replies", "daycare_leads")
RECENT_BLASTS = 5                          # blast history depth for the follow-up lane
LEARN_EVERY = int(os.environ.get("FORGE_SOLOMON_LEARN_EVERY", "8"))
# The autonomous daily operating brief is OFF (owner cut scheduled briefs 2026-09-30): Solomon's
# value is the Replies/Leads/Starts lanes. On-demand brief + chat still work.
SCHEDULED_BRIEF = os.environ.get("FORGE_SOLOMON_BRIEF", "0") != "0"
LEARN_MIN_INTERVAL_MS = int(os.environ.get("FORGE_SOLOMON_LEARN_GAP_MIN", "45")) * 60 * 1000
BRIEF_EVERY_MS = int(float(os.environ.get("FORGE_SOLOMON_BRIEF_EVERY_H", "24")) * 3600 * 1000)
# The brief is ONE json object covering 9 sections (ops, enrollment, money, people,
# roster, follow-ups, campaign health, competitor read, creative). Absorbing Nora's and
# Nova's lanes on 2026-07-25 made it materially longer, and 2600 started truncating it
# mid-string — a cut-off brief fails json.loads and the whole run is lost after ~2 min
# of Claude time. Sized with headroom; raise if a section ever comes back clipped.
BRIEF_MAX_TOKENS = int(os.environ.get("FORGE_SOLOMON_BRIEF_TOKENS", "5000"))
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


def reply_desk_state(now_ms=None):
    """Solomon · Replies (daycare_replies — the Reply Desk): parent-reply drafts waiting on
    the owner's tap. State file only — no network, no Claude — and never raises, so the
    brief, his chat and the registry all still work without it."""
    try:
        import daycare_replies
        v = daycare_replies.view() or {}
    except Exception as e:  # noqa: BLE001
        return {"error": f"reply desk unavailable: {type(e).__name__}"}
    pending = v.get("pending") or []
    now_ms = now_ms or int(time.time() * 1000)
    oldest = min((d["inboundAt"] for d in pending if d.get("inboundAt")), default=None)
    return {
        "pending": len(pending),
        # safety / custody / medical / complaint / billing threads: a holding line only
        "escalations": sum(1 for d in pending if d.get("action") == "escalate"),
        "oldestPendingAgeSec": max(0, (now_ms - oldest) // 1000) if oldest else None,
        "lastRunAt": v.get("lastRunAt"),
        "lastSweep": v.get("lastSweep"),
        "error": v.get("error"),
    }


def lead_desk_state():
    """Solomon · Leads (daycare_leads — the Lead Desk): enrollment lead flow from its saved
    state — no network. KPIs + who needs a human right now. Never raises."""
    try:
        import daycare_leads
        desk = daycare_leads.view()
    except Exception as e:  # noqa: BLE001 — the brief still works without it
        return {"error": f"lead desk unavailable: {type(e).__name__}"}
    return {
        "kpis": desk.get("kpis"),
        "needsHuman": [{k: i.get(k) for k in ("title", "why", "ageSec", "priority", "center")}
                       for i in (desk.get("needsHuman") or [])[:10]],
        "lastRunAt": desk.get("lastRunAt"),
        "error": desk.get("error"),
    }


def starts_desk_state():
    """Solomon · Starts (daycare_starts): start dates in flight — the enrolled-but-not-
    started leak. State file only — no network. Never raises."""
    try:
        import daycare_starts
        v = daycare_starts.view()
    except Exception as e:  # noqa: BLE001 — the brief still works without it
        return {"error": f"starts desk unavailable: {type(e).__name__}"}
    rows = v.get("starts") or []
    by_status = {}
    for r in rows:
        by_status[r.get("status")] = by_status.get(r.get("status"), 0) + 1
    return {
        "byStatus": by_status,
        "upcoming": [{"family": daycare_starts.display_name(r), "startDate": r.get("startDate"),
                      "daysUntil": r.get("daysUntil"), "status": r.get("status"),
                      "confirmOpen": r.get("confirmOpen")}
                     for r in rows if r.get("status") != "sent"][:10],
        "lastRunAt": v.get("lastRunAt"),
        "error": v.get("error"),
    }


def _seat_row(r):
    """One classroom as inventory. openSeats only when capacity AND enrolled are real
    numbers — otherwise None (Unknown), never a fake 0 or a fake vacancy."""
    cap, enr = r.get("capacity"), r.get("enrolled")
    known = isinstance(cap, (int, float)) and isinstance(enr, (int, float))
    return {"name": r.get("name"), "capacity": cap, "enrolled": enr,
            "ratio": r.get("ratio_children"),
            "openSeats": max(0, int(cap - enr)) if known else None}


def top_skills_text():
    """Solomon's constitution (top skills) for chat — so the Solomon you talk to runs on
    the same growth skills as the one that writes the brief. agents_hub looks this up."""
    try:
        return SolomonEngine()._load_skills() or ""
    except Exception:  # noqa: BLE001
        return ""


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
        connected = bool(val)
        if connected and key == "META_ACCESS_TOKEN":
            try:  # a token Meta already rejected is present, not wired (in-process cache)
                import agency_ads
                connected = not agency_ads._auth_dead(val)
            except Exception:
                pass
        out.append({"key": key, "name": name, "connected": connected})
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


def _north_star_block():
    """The cross-business constitution — never truncated, frames everything below
    it (creed, top skills, playbook). Sourced from north_star, which learn()
    cannot see, so self-improvement can never rewrite it."""
    try:
        import north_star
        return north_star.context_block()
    except Exception:
        return ""


def _creed_block():
    """The daycare creed (evidence discipline) — never truncated, outranks the playbook.
    Sourced from agent_creed, which learn() cannot see, so self-improvement can never
    rewrite it."""
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
        self.fail_streak = 0          # WP-A — consecutive failed briefs (backoff input)
        self.last_attempt_at = None   # WP-A — ms epoch of the last brief attempt
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
                self.fail_streak = int(d.get("failStreak") or 0)          # WP-A
                self.last_attempt_at = d.get("lastAttemptAt")             # WP-A
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
                "failStreak": self.fail_streak,          # WP-A
                "lastAttemptAt": self.last_attempt_at,   # WP-A
            })
        except Exception:
            pass

    def _log(self, kind, text):
        self.activity.append({"ts": int(time.time() * 1000), "kind": kind, "text": text})
        self.activity = self.activity[-120:]

    # --- brain skills (mtime-cached seed + vault) ----------------------------
    # Prompt order: CREED (daycare-evidence-discipline, via agent_creed — never
    # reachable from learn()) → TOP SKILLS below → the learned playbook last.
    # decision loop (how Solomon reasons) → director craft (what 50 years knows)
    # → systems craft (what is actually wired, verified, and broken).
    TOP_SKILLS = ("solomon-decision-loop.md", "solomon-director-craft.md",
                  "solomon-systems-craft.md",
                  "solomon-roster-craft.md", "solomon-adops-craft.md")
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
            _sec("Roster", brief.get("roster"),
                 lambda r: f"[{r.get('urgency','?')}/{r.get('area','?')}] {r.get('title','')} — {r.get('why','')}")
            _sec("Family follow-ups", brief.get("followUps"),
                 lambda f: f"{f.get('family','?')} — {f.get('reason','')} → {f.get('suggestedNextStep','')}")
            _sec("Campaign health", brief.get("campaignHealth"),
                 lambda c: f"[{c.get('urgency','?')}] {c.get('title','')} — {c.get('why','')}")
            _sec("Creative direction", brief.get("creativeRecommendations"),
                 lambda c: f"{c.get('angle','?')} — {c.get('why','')} → {c.get('action','')}")
            _sec("Delegations", brief.get("delegations"),
                 lambda d: f"**{d.get('role','team')}** → {d.get('task','')}  [[solomon-playbook]]")
            content = "\n".join(lines)
            res = brain_io.write_note(f"{BRIEF_DIR_REL}/brief-{day}.md", content,
                                      reason=f"solomon operating brief {stamp}")
            return bool(res.get("committed"))
        except Exception:
            return False

    # --- bus: consume delegations addressed to any lane Solomon owns ----------
    def _read_bus_inbox(self, mark_read=True):
        """Unread messages addressed to Solomon's bus identities, marked read.

        Absorbed from Nora/Nova when the daycare crew collapsed into one director —
        a delegation posted to family-comms/ads/enrollment still gets picked up.
        """
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

    def _gather_roster(self, session):
        """Live roster detail for the family-comms lane. Returns (roster, err).

        Same session Solomon already opened for _gather — one auto-admin session for
        the whole brief instead of the three the old crew opened.
        """
        if session is None:
            return {}, "no session"
        try:
            import daycare_supabase
            children = daycare_supabase.get_children(session).get("children", []) or []
            classrooms = daycare_supabase.get_classrooms(session).get("classrooms", []) or []
        except Exception as e:  # noqa: BLE001 — brief still works from the blast log alone
            return {}, str(e)
        # Growth lens only (2026-09-30): seats are sellable inventory. The old
        # missing-guardian-contact audit was paperwork and is gone from the brief.
        return {
            "childrenActive": sum(1 for c in children if c.get("active")),
            "childrenTotal": len(children),
            "classrooms": [_seat_row(r) for r in classrooms if r.get("active", True)],
        }, None

    def _gather_blasts(self):
        """Recent Family Text Blast history — the only grounded source for follow-ups."""
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

    def _gather_campaign(self):
        """Meta campaign health for the ad-ops lane. Returns (data, err)."""
        try:
            import daycare_growth
            ads = daycare_growth.ads_overview()
        except Exception as e:  # noqa: BLE001 — brief still works from the context brief
            return {}, str(e)
        connection = ads.get("connection") or {}
        connected = bool(connection.get("connected") or connection.get("source") == "live")
        data = {
            "connected": connected,
            "source": connection.get("source"),
            "accounts": ads.get("accounts") or [],
            "analytics": ads.get("analytics") or {},
        }
        if not connected:
            # Not an outage — there is genuinely no campaign data for this center yet.
            # Surface it as an err so the prompt's "do not fabricate ad performance
            # numbers" rail fires; silence here previously let the brief fill the gap.
            return data, (ads.get("detail")
                          or "Meta is not connected for the daycare — no campaign "
                             "numbers exist for this center.")
        return data, None

    # --- WP-E ---
    def _gather_leads(self):
        """Enrollment leads from his Leads lane's saved state — see lead_desk_state()."""
        return lead_desk_state()
    # --- /WP-E ---

    def _gather_competitor(self, key):
        """Daycare-scoped competitor read (best-effort — never blocks the brief)."""
        try:
            import agency_eco
            import daycare_context
            return agency_eco._daycare_competitor(daycare_context.context_block(), key)
        except Exception as e:  # noqa: BLE001
            return {"status": "unavailable", "error": str(e)}

    def build_brief(self, session=None):
        """Read the whole center + the brief, produce a prioritized operating brief.

        Read-only. Never contacts anyone. Delegations are recorded + posted to the
        bus for role agents; the human executes any outward action.
        """
        key = _solomon_key()
        if not key:
            return {"ok": False, "error": "no anthropic key"}

        import daycare_context
        # The enrollment-ad-agent spec rides along with the business brief now that
        # Solomon owns the ad-ops lane (it used to be injected by Nova).
        ctx = daycare_context.context_block() + daycare_context.ad_agent_block()
        metrics, alerts, gather_err = self._gather(session)
        roster, roster_err = self._gather_roster(session)
        blasts, optouts = self._gather_blasts()
        campaign, campaign_err = self._gather_campaign()
        competitor = self._gather_competitor(key)
        inbox = self._read_bus_inbox()
        behavior = {}
        if session is not None:
            try:
                import daycare_supabase
                behavior = daycare_supabase.behavior_week_summary(session)
            except Exception:  # noqa: BLE001 — brief still works without the signal
                behavior = {}
        systems = connected_systems()
        offline = [s["name"] for s in systems if not s["connected"]]

        skills = self._load_skills()      # constitution — never truncated
        playbook = self._playbook_only()  # learned rubric — own budget
        system = (
            "You are Solomon, the growth director of A Touch of Blessings Learning "
            "Academy with 50 years filling childcare centers. ONE job: more families "
            "touring, starting, and staying. Paperwork is NOT your lane — licensing, "
            "inspections, records, clearances, billing collections, payroll, staff "
            "schedules and roster data hygiene never become priorities (creed §5 has the "
            "only two narrow exceptions). Read the DAYCARE CONTEXT brief FIRST and never "
            "contradict its licensing, CCIS, pricing, offer, or capacity facts. Build "
            "today's GROWTH BRIEF for the owner. Run your triage in this order and never "
            "reorder it: (1) families waiting on us — leadDesk.needsHuman, replyDesk "
            "pending drafts (oldest first), startsDesk confirmed/upcoming starts; (2) the "
            "worst funnel leak — leadDesk.kpis response times + pipeline stages "
            "(null = untracked = Unknown, never 0); (3) sellable seats — roster.classrooms "
            "openSeats (null = Unknown) matched against leads by age band; (4) retention — "
            "behaviorChart clusters and attendance drift are families to keep, never "
            "discipline; (5) demand — campaign health, competitor read, referral, "
            "partnerships, reviews; (6) the offer clock in the context brief. Three live "
            "lanes report to you: SOLOMON · REPLIES (replyDesk — parent texts drafted, each "
            "waiting on the OWNER's approve tap; escalations are threads that need him, not "
            "a canned reply), SOLOMON · LEADS (leadDesk — enrollment lead flow + who needs "
            "a human) and SOLOMON · STARTS (startsDesk — agreed start dates; enrolled-but-"
            "not-started is the most painful leak). You NEVER take an outward action and "
            "never draft family text here; you never launch, activate, or re-budget a "
            "campaign — name who/why and the move, the owner taps to execute. EVIDENCE "
            "DISCIPLINE (outranks everything): every number or status comes from the data "
            "below or the brief, with its window — never from what sounds plausible. Can't "
            "reach it → say Unknown and make finding it out a priority. Then CLOSE THE "
            "LOOP: once more looking would not change the recommendation, decide. Never "
            "name a child in an outward-sounding action. "
            "Output ONLY valid JSON with keys: headline (string — the single biggest growth "
            "fact today), priorities (array of {title, why, area, urgency} — 3–5, ranked by "
            "the triage above; area is one of speed-to-lead | funnel | seats | retention | "
            "demand | offer; every one carries the move), enrollment (array of strings — "
            "concrete moves to book tours and starts this week), money (array of strings — "
            "growth economics ONLY: offer deadlines, ad spend vs tours booked, seats sitting "
            "empty; never billing collections or balances; may be empty), people (array of "
            "strings — ONLY where staffing gates a sellable seat; usually empty), roster "
            "(array of {title, why, area, urgency} — seat findings per your seats craft), "
            "followUps (array of {family, reason, suggestedNextStep} — retention + referral "
            "moves grounded ONLY in recorded data, never an invented family response), "
            "campaignHealth (array of {title, why, urgency}), competitorRead (object "
            "{summary, angles, gap}), creativeRecommendations (array of {angle, why, "
            "action}), delegations (array of {role, task} — role is who does it: Owner, "
            "Director, Front desk, or Ads). Empty arrays beat invented findings."
            + _north_star_block()
            + (ctx or "")
            + _creed_block()
            + ("\n\n=== YOUR TOP SKILLS (these OUTRANK the learned playbook below; "
               "when they conflict, these win) ===\n" + skills
               if skills else "")
            + ("\n\n=== YOUR PLAYBOOK (learned rubric — apply it within the skills "
               "above) ===\n" + playbook[:4000] if playbook else "")
            + self._recent_brain_context()
        )
        live = {
            "metrics": metrics,
            "alerts": alerts,
            "behaviorChart": behavior,
            "roster": roster,
            "recentBlasts": blasts,
            "optOuts": len(optouts),
            "campaign": campaign,
            "competitor": competitor,
            "busDelegations": [{"from": m.get("from"), "text": m.get("text")} for m in inbox],
            "connectedSystems": [{"name": s["name"], "connected": s["connected"]} for s in systems],
            "offlineChannels": offline,
        }
        live["leadDesk"] = self._gather_leads()  # --- WP-E --- GHL enrollment leads (read-only)
        live["replyDesk"] = reply_desk_state()   # Solomon · Replies — drafts awaiting the owner
        live["startsDesk"] = starts_desk_state() # Solomon · Starts — enrolled-but-not-started
        user = (
            "TODAY'S LIVE CENTER DATA (ground the brief in these — do not invent "
            "numbers):\n" + json.dumps(live, indent=2)
            + ("\n\n(Live ops metrics were unavailable this run — reason from the brief "
               "and connected-systems status; do not fabricate counts.)" if gather_err else "")
            + ("\n\n(Live roster detail was unavailable this run — leave roster empty or "
               "reason from the blast log only; do not fabricate roster counts.)"
               if roster_err else "")
            + ("\n\n(No campaign data for this center this run — say so plainly in "
               "campaignHealth; do not fabricate ad performance numbers.)"
               if campaign_err else "")
            + "\n\nProduce the growth brief now."
        )
        try:
            raw = _strip_fences(review_agent._claude(key, system, user, max_tokens=BRIEF_MAX_TOKENS, effort="medium", model=review_agent.SMART_MODEL))
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
            # roster + family-comms lane (absorbed from Nora)
            "roster": parsed.get("roster") or [],
            "followUps": parsed.get("followUps") or [],
            # ad-ops lane (absorbed from Nova)
            "campaignHealth": parsed.get("campaignHealth") or [],
            "competitorRead": parsed.get("competitorRead") or {},
            "creativeRecommendations": parsed.get("creativeRecommendations") or [],
            "delegations": parsed.get("delegations") or [],
            "metrics": metrics,
            "rosterData": roster,
            "campaign": campaign,
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
                               f"{len(brief['roster'])} roster findings, "
                               f"{len(brief['campaignHealth'])} campaign items, "
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
        import review_agent
        if not review_agent.self_improve_on():   # scheduled self-improvement is OFF by default (cost)
            return
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
            for r in (last.get("roster") or [])[:4]:
                sample.append(f"roster[{r.get('urgency','?')}] {r.get('title','')} — {r.get('why','')}")
            for f in (last.get("followUps") or [])[:3]:
                sample.append(f"followUp: {f.get('family','?')} — {f.get('reason','')}")
            for c in (last.get("campaignHealth") or [])[:3]:
                sample.append(f"campaign[{c.get('urgency','?')}] {c.get('title','')} — {c.get('why','')}")
            for c in (last.get("creativeRecommendations") or [])[:3]:
                sample.append(f"creative[{c.get('angle','?')}] {c.get('why','')} → {c.get('action','')}")
            for d in (last.get("delegations") or [])[:5]:
                sample.append(f"delegated → {d.get('role','?')}: {d.get('task','')}")
        if not sample:
            return {"error": "no briefs to learn from yet"}
        current = self._playbook_only() or "(no playbook yet — create one)"
        system = (
            "You are Solomon, a SELF-IMPROVING daycare executive director. Below is your "
            "CURRENT operating playbook and a sample of the briefs you actually produced. "
            "Improve yourself as a GROWTH director: sharpen how you rank families waiting, "
            "funnel leaks, sellable seats, retention and demand; tighten the enrollment "
            "plays that fit this specific daycare; cut guidance that didn't move tours or "
            "starts. Never add paperwork, compliance, billing-collection or staff-admin "
            "guidance — that is not your lane. Keep the hard rules (read the "
            "business brief first; never act outward; never quote a price or promise a "
            "start date the brief doesn't support; ground everything in real data; the "
            "JSON output contract). "
            "You ALSO carry separate, permanent top skills — evidence discipline, the "
            "decision loop, growth craft, seats craft, systems craft, and ad-ops craft. Those "
            "are NOT "
            "yours to rewrite and are not "
            "shown here. Do not restate or summarize them in the playbook; assume they "
            "always apply and keep the playbook to what you have actually learned from "
            "running THIS center. Output the FULL UPDATED playbook as clean markdown — "
            "ONLY the markdown."
        )
        user = ("CURRENT PLAYBOOK:\n" + current[:4000]
                + "\n\nRECENT BRIEFS YOU PRODUCED (learn from these):\n" + "\n".join(sample))
        try:
            import agent_coach
            user += agent_coach.insights_block("solomon", "daycare")
        except Exception:
            pass
        try:
            new_md = review_agent._claude(key, system, user, max_tokens=2400, effort="medium")
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
            "northStarLoaded": bool(_north_star_block()),
            "creedLoaded": bool(_creed_block()),
            "playbookLoaded": bool(self._playbook_only()),
            "systems": connected_systems(),
            "briefCount": self.brief_count,
            "lastBriefAt": self.last_brief_at,
            "learn": self.learn_state,
            "lastError": self.last_error,
            "failStreak": self.fail_streak,          # WP-A — consecutive failed briefs
            "lastAttemptAt": self.last_attempt_at,   # WP-A
            "nextBriefAt": self.next_brief_at(),     # WP-A — cadence + backoff, whichever is later
        }

    def overview(self):
        return {"ok": True, **self.status(), "brief": self.last_brief,
                "activity": list(reversed(self.activity[-40:]))}

    def brief(self):
        return {"ok": True, "brief": self.last_brief, "lastBriefAt": self.last_brief_at}

    # --- lane views (Nora/Nova's old consoles read these shapes) --------------
    # Nora and Nova were merged into Solomon; their routes now narrow his brief to
    # the lane instead of running a second agent. Same keys the old briefs emitted,
    # so anything still pointed at /api/daycare/{family,adops}/* keeps working.
    def _lane(self, name, title, keys):
        b = self.last_brief or {}
        lane = {k: b.get(k) for k in keys} if b else {}
        if b:
            lane["headline"] = b.get("headline", title)
            lane["generatedAt"] = b.get("generatedAt")
        return {"ok": True, **self.status(), "lane": name, "title": title,
                "brief": lane or None, "lastBriefAt": self.last_brief_at,
                "activity": list(reversed(self.activity[-40:]))}

    def roster_view(self):
        return self._lane("roster", "Seats & Retention",
                          ("roster", "followUps", "rosterData"))

    def adops_view(self):
        return self._lane("adops", "Ad Ops",
                          ("campaignHealth", "competitorRead", "creativeRecommendations",
                           "campaign"))

    # Solomon · Replies / Solomon · Leads: those lanes run their own loops, so the view
    # carries their LIVE state (not a copy frozen into the last brief) beside his headline.
    def replies_view(self):
        return {**self._lane("replies", "Solomon · Replies", ()), "live": reply_desk_state()}

    def leads_view(self):
        return {**self._lane("leads", "Solomon · Leads", ()), "live": lead_desk_state()}

    # --- background loop (box only, FORGE_MARCUS gate) -----------------------
    def run_once(self, session=None):
        return self.build_brief(session)

    # --- WP-A --- failed-brief backoff: 15 min → 30 → 60 → 2 h → 4 h → cap 6 h. Without
    # it a dead Anthropic key was retried every tick forever (errStreak ~4,900), and each
    # retry re-gathered Meta with an invalid token. A successful brief resets the streak.
    # failStreak / lastAttemptAt persist in solomon.json so a restart keeps the schedule.
    BACKOFF_BASE_S = POLL_INTERVAL
    BACKOFF_CAP_S = 6 * 3600

    @classmethod
    def backoff_delay_s(cls, fail_streak):
        if fail_streak <= 0:
            return 0
        return min(cls.BACKOFF_BASE_S * 2 ** (fail_streak - 1), cls.BACKOFF_CAP_S)

    def _brief_due(self, now):
        due = (self.last_brief_at is None
               or (now - self.last_brief_at) >= BRIEF_EVERY_MS)
        wait_ms = self.backoff_delay_s(self.fail_streak) * 1000
        return due and (now - (self.last_attempt_at or 0)) >= wait_ms

    def _note_brief_result(self, ok, now):
        with self.lock:
            self.last_attempt_at = now
            self.fail_streak = 0 if ok else self.fail_streak + 1
            self._save()

    def next_brief_at(self):
        """ms epoch of the next autonomous brief: the 24h cadence OR the backoff window,
        whichever ends later. None until the first brief/attempt (= due now)."""
        if self.last_brief_at is None and self.last_attempt_at is None:
            return None
        return max((self.last_brief_at or 0) + BRIEF_EVERY_MS,
                   (self.last_attempt_at or 0) + self.backoff_delay_s(self.fail_streak) * 1000)
    # --- /WP-A ---

    def run_forever(self):
        while True:
            # WP-A — only a tick that ATTEMPTED a brief (or itself raised) reports an error
            # to the heartbeat. A backoff tick attempts nothing; re-beating the stale
            # last_error inflated errStreak/errorsTotal ~96/day during an outage.
            attempted = False
            try:
                if forge_ops.paused():
                    time.sleep(POLL_INTERVAL)
                    continue
                key = _solomon_key()
                # Due a fresh autonomous brief? Build one under an auto-admin session.
                now = int(time.time() * 1000)
                if SCHEDULED_BRIEF and self._brief_due(now) and key:
                    attempted = True
                    session = None
                    try:
                        import daycare_supabase
                        session = daycare_supabase.BRIDGE.autoadmin_session("127.0.0.1")
                    except Exception:
                        session = None
                    ok = False
                    try:
                        result = self.build_brief(session) or {}
                        ok = bool(result.get("ok"))
                        if not ok:
                            self.last_error = result.get("error") or "brief failed (no error detail)"
                    finally:
                        self._note_brief_result(ok, now)   # WP-A — an exception counts as a fail
                self._maybe_learn(key)
            except Exception as e:  # noqa: BLE001
                attempted = True
                self.last_error = f"loop: {e}"
            finally:
                try:
                    forge_heartbeat.beat("solomon", POLL_INTERVAL, "Solomon director",
                                         error=self.last_error if attempted else None)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL)
