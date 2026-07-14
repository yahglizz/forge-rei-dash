"""deal_prep.py — Atlas, the deal-UNDERWRITING agent for FORGE REI OS.

When Marcus screens a seller as "interested", Atlas automatically preps the DEAL so
the operator (Yahjair) walks into the call with numbers in hand: extracted property
facts, an offer-anchor range, the MAO math spelled out (unknowns flagged), and a
negotiation-ready call card. Atlas NEVER contacts anyone — pure decision support;
the human makes the call.

Chain of command: Atlas reports to Marcus (the lead agent). Atlas CONSUMES Marcus's
screening report + the full seller thread (Scout's read-only transcript) and adds
the underwriting layer neither of them does. Every number Atlas produces is INTERNAL
operator prep — anchors and MAO math never leak into any outbound message, and the
call card never contradicts the screening's callPrep.

Anchor discipline (hard rule, enforced in the prompt AND a code guard): anchors
derive ONLY from the SELLER'S OWN stated price (opening ~70-75% of ask, target
~80-85%, walkaway = the ask). No seller-stated ask → anchors stay null and maoNote
spells out exactly what comp data the operator needs to pull. Atlas never invents
an ARV or a market value.

Loads a playbook merged from the forge-marcus seed (`forge-marcus/skills/
atlas-underwriter.md`) + the brain vault copy (mtime hot-reload), mirroring Marcus.
State persists to marcus_state/deal_prep.json (cap 100 newest, atomic writes).
Reuses review_agent._claude (one call per prep); broadcasts each finished prep to
Marcus on the agent bus.
"""

import forge_atomic
import forge_heartbeat
import forge_ops
import json
import os
import re
import threading
import time
from pathlib import Path

import review_agent

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "deal_prep.json"
MARCUS_DIR = HERE.parent / "forge-marcus"        # Atlas rides on Marcus's team folder


def _load_env_file(p):
    """Fold forge-marcus/config/marcus.env into the environment (real env wins)."""
    try:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_env_file(MARCUS_DIR / "config" / "marcus.env")


def _atlas_key():
    """Atlas's Anthropic key: his own (ATLAS_ANTHROPIC_API_KEY) else Marcus's else
    the shared wholesale key. Mirrors _marcus_key resolution; ignores placeholders."""
    for env_key in ("ATLAS_ANTHROPIC_API_KEY", "MARCUS_ANTHROPIC_API_KEY",
                    "ANTHROPIC_API_KEY"):
        v = os.environ.get(env_key)
        if v and not v.startswith("sk-ant-..."):
            return v
    return review_agent._api_key()


AUTO_PREP = os.environ.get("FORGE_PREP_AUTO", "1") != "0"             # auto-prep interested screenings
SWEEP_CAP = int(os.environ.get("FORGE_PREP_SWEEP_CAP", "5"))          # Claude calls per sweep
PREP_MSGS = int(os.environ.get("FORGE_PREP_MSGS", "40"))              # transcript msgs fed to the model
SKILL_REL = "Skills/atlas-underwriter.md"                             # learned playbook in the brain
MAX_RECORDS = 100

# Self-improvement cadence — lower than Scout's 25: Atlas only fires on
# screened-interested sellers (15-min sweep, cap 5 Claude calls/sweep).
LEARN_EVERY = int(os.environ.get("FORGE_ATLAS_LEARN_EVERY", "12"))
LEARN_MIN_INTERVAL_MS = int(os.environ.get("FORGE_ATLAS_LEARN_GAP_MIN", "45")) * 60 * 1000

CONDITIONS = ("move-in", "light rehab", "heavy rehab", "unknown")
OCCUPANCIES = ("owner", "tenant", "vacant", "unknown")


def _parse_obj(text):
    """Extract the first {...} JSON object from a model reply. Returns dict or None."""
    if not text:
        return None
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        obj = json.loads(text[s:e + 1])
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    # Defensive: if the model wrapped the prep under a single key (e.g.
    # {"deal_prep": {...}}), unwrap to the inner object.
    if "anchors" not in obj and "maoNote" not in obj:
        for v in obj.values():
            if isinstance(v, dict) and ("anchors" in v or "maoNote" in v or "callCard" in v):
                return v
    return obj


def _money(v):
    """Coerce a seller price into a positive number ($85,000 / 85k / 85000 → 85000).
    Returns int/float or None. Never invents — junk in, None out."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        n = float(v)
    elif isinstance(v, str):
        m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?", v)
        if not m:
            return None
        try:
            n = float(m.group(1).replace(",", ""))
        except ValueError:
            return None
        if m.group(2):
            n *= 1000
    else:
        return None
    if n <= 0:
        return None
    return int(n) if n == int(n) else round(n, 2)


def _num(v):
    """Small count like beds/baths: int/float or None."""
    if v is None or isinstance(v, bool):
        return None
    try:
        n = float(v)
    except (ValueError, TypeError):
        return None
    if n < 0:
        return None
    return int(n) if n == int(n) else n


def _s(v, limit=400):
    return str(v or "").strip()[:limit]


def _slist(v, limit=8):
    """Coerce a value into a clean list of short strings."""
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    out = []
    for x in v:
        s = str(x).strip()
        if s:
            out.append(s[:240])
        if len(out) >= limit:
            break
    return out


def _fmt_money(v):
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "—"


class DealPrep:
    def __init__(self, scout, screener, ghl_get, location_id):
        self.scout = scout            # Scout engine — read-only thread transcripts
        self.screener = screener      # Marcus's Screener — screening reports are the input
        self.ghl_get = ghl_get        # kept for future read-only GHL fact pulls
        self.location_id = location_id
        self.lock = threading.Lock()
        self.preps = {}               # contactId -> prep record
        self.activity = []            # ring buffer of prep actions
        self.last_error = None
        self._sk_text = ""
        self._sk_mtime = None
        self.learn_state = {"lastLearnedAt": None, "learnCount": 0, "preppedSinceLearn": 0}
        self._load()

    # -- persistence ----------------------------------------------------------
    def _load(self):
        try:
            if STATE.exists():
                d = json.loads(STATE.read_text())
                if isinstance(d, dict):
                    self.preps = d.get("preps", {}) or {}
                    self.activity = d.get("activity", []) or []
                    self.learn_state = d.get("learnState", self.learn_state) or self.learn_state
        except Exception:
            self.preps, self.activity = {}, []

    def _log(self, kind, text, contact_id=None):
        self.activity.insert(0, {"ts": int(time.time() * 1000), "kind": kind,
                                 "text": text, "contactId": contact_id})
        self.activity = self.activity[:100]

    def _save(self):
        if len(self.preps) > MAX_RECORDS:
            keep = sorted(self.preps.values(),
                          key=lambda r: r.get("updatedAt") or 0, reverse=True)[:MAX_RECORDS]
            self.preps = {r["contactId"]: r for r in keep}
        forge_atomic.atomic_write_json(STATE, {"preps": self.preps,
                                               "activity": self.activity,
                                               "learnState": self.learn_state})

    # -- brain skills (mtime-cached seed + learned vault playbook) --------------
    def _load_skills(self):
        try:
            import brain_io
            parts, sig = [], []
            srcs = [MARCUS_DIR / "skills" / "atlas-underwriter.md",
                    brain_io.VAULT / "Skills" / "atlas-underwriter.md"]
            for p in srcs:
                if p.is_file():
                    parts.append(p.read_text(errors="ignore"))
                    sig.append(p.stat().st_mtime)
            sig = tuple(sig)
            if self._sk_mtime != sig:
                self._sk_text = "\n\n".join(parts)
                self._sk_mtime = sig
            return self._sk_text
        except Exception:
            return self._sk_text

    # -- transcript (read-only, via Scout) --------------------------------------
    def _transcript(self, conv_id):
        """Full seller thread oldest-first as prompt lines. Read-only on GHL."""
        if not conv_id or self.scout is None:
            return "(no thread available)"
        try:
            msgs = self.scout._thread_transcript(conv_id)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"transcript: {e}"
            return "(no thread available)"
        lines = []
        for m in (msgs or [])[-PREP_MSGS:]:
            body = (m.get("body") or "").strip()
            if not body:
                continue
            who = "Seller" if m.get("direction") == "inbound" else "You (operator)"
            lines.append(f"{who}: {body[:400]}")
        return "\n".join(lines) if lines else "(no messages in this thread yet)"

    # -- the prep ----------------------------------------------------------------
    def prep(self, contact_id, force=False):
        """Underwrite one interested screening into a deal-prep record. One Claude
        call. Cache: skipped if the screening hasn't changed since the last prep."""
        if self.screener is None:
            return {"error": "screener unavailable"}
        r = self.screener.screenings.get(contact_id)
        if not r:
            return {"error": "no screening for this contact — Marcus screens first"}
        rep = r.get("report") or {}
        screened_at = r.get("updatedAt")
        existing = self.preps.get(contact_id)
        if existing and not force and existing.get("screenedAt") == screened_at:
            return {"ok": True, "cached": True, "prep": existing}
        key = _atlas_key()
        if not key:
            return {"error": "no anthropic key"}
        conv_id = r.get("convId")
        name = r.get("name") or "(unknown)"
        transcript = self._transcript(conv_id)

        system = (
            "You are Atlas, the deal-UNDERWRITING analyst on a real-estate WHOLESALING "
            "team (the operator is Yahjair; you report to Marcus, the lead agent). Marcus "
            "screened this seller as INTERESTED — your job is to prep the DEAL so the "
            "operator walks into the call with numbers in hand. You are pure decision "
            "support: you never contact the seller, and every number you produce is "
            "INTERNAL operator prep — anchors and MAO math are NEVER sent to the seller.\n\n"
            "OUTPUT: return ONE JSON object and NOTHING else — no prose, no markdown, no "
            "code fences, no wrapper key, no extra keys. Use EXACTLY these keys and types:\n"
            '{"address": "<street/city if stated in the thread, else null>", '
            '"askingPrice": <number the SELLER stated (digits only), else null>, '
            '"beds": <number|null>, "baths": <number|null>, '
            '"condition": "<move-in | light rehab | heavy rehab | unknown>", '
            '"occupancy": "<owner | tenant | vacant | unknown>", '
            '"timeline": "<the seller\'s timeline, or \'unknown\'>", '
            '"motivationRead": "<1-2 sentences: the REAL motivation behind the sale>", '
            '"repairEstimate": "<low|medium|high|unknown> with a one-line why", '
            '"anchors": {"opening": <number|null>, "target": <number|null>, "walkaway": <number|null>}, '
            '"anchorLogic": "<2-3 sentences: how the anchors were derived>", '
            '"maoNote": "<the MAO formula spelled out with the UNKNOWNS flagged: '
            'MAO = ARV x 0.70 - repairs - assignment fee. If ARV is unknown say exactly '
            'what comp data the operator needs to pull>", '
            '"callCard": ["<5-7 short tactical bullets: open, key questions, objection counters, the close>"], '
            '"redFlags": ["<concrete deal risks>"]}\n\n'
            "ANCHOR RULES (hard, never break): anchors derive ONLY from the SELLER'S OWN "
            "stated price when one exists — opening ~70-75% of the ask, target ~80-85% of "
            "the ask, walkaway = the ask. NEVER invent an ARV, comp value, or market price. "
            "If the seller never stated a price, set askingPrice and ALL THREE anchors to "
            "null and make maoNote spell out exactly what to pull (comps for the zip, price "
            "per sqft on recent sales) before any number gets quoted. These are PREP numbers "
            "for the operator only — clearly internal, never sent to the seller.\n"
            "FACTS: extract only what the thread + screening actually say; anything not in "
            "evidence is null/'unknown' — never guess. repairEstimate is a bucket read from "
            "condition language, not a dollar figure.\n"
            "CALL CARD: short, tactical, consistent with Marcus's screening callPrep below — "
            "never contradict it. The operator opens with rapport and questions, NEVER with "
            "a price; anchors only come out mid-negotiation when the seller talks numbers. "
            "Output ONLY the JSON object."
        )
        # The CREED first (wholesale evidence discipline) — never truncated, outranks the
        # playbook. Matters most for Atlas: his anchors are INTERNAL and never invented.
        try:
            import agent_creed
            system += agent_creed.block("wholesale")
        except Exception:
            pass
        skills = self._load_skills()
        if skills:
            system += ("\n\n=== YOUR SKILLS (underwriting rubric — apply it) ===\n"
                       + skills[:7000])
        # Brain history for this deal's shape (past preps, comps notes, closing plays).
        try:
            import agent_context
            ctx = agent_context.brain_context(
                agent_context.seller_query(name, rep.get("sellerSituation"),
                                           rep.get("propertyStatus"), rep.get("conditionNotes")),
                header="RELEVANT BRAIN NOTES (past deal preps, comps + underwriting lessons)")
            if ctx:
                system += "\n\n" + ctx
        except Exception:  # noqa: BLE001
            pass
        screening_input = {
            "score": rep.get("score"), "interest": rep.get("interest"),
            "sellerSituation": rep.get("sellerSituation"),
            "propertyStatus": rep.get("propertyStatus"),
            "conditionNotes": rep.get("conditionNotes"),
            "timeline": rep.get("timeline"), "askingPrice": rep.get("askingPrice"),
            "sellerPsychology": rep.get("sellerPsychology"),
            "pathToContract": rep.get("pathToContract"),
            "callPrep": rep.get("callPrep"),
        }
        user = (f"Seller: {name}\n\nMARCUS'S SCREENING REPORT (INPUT — trust it, do not "
                "recompute):\n" + json.dumps(screening_input, indent=1)
                + "\n\nSELLER TEXT THREAD (oldest first):\n" + transcript
                + "\n\nReturn the deal-prep JSON now.")
        # The model intermittently wraps the object in prose/fences or truncates it, which
        # _parse_obj can't salvage — that silently killed ~half of all preps. Retry once with
        # a blunter instruction before giving up.
        obj = None
        for attempt in range(2):
            u = user if attempt == 0 else (
                user + "\n\nYour previous reply was not valid JSON. Return ONLY the raw JSON "
                "object — no prose, no markdown, no code fences. Start with { and end with }.")
            try:
                raw = review_agent._claude(key, system, u, max_tokens=900)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"claude: {e}"
                return {"error": f"claude: {e}"}
            obj = _parse_obj(raw)
            if obj:
                break
            self._log("parse_retry", f"Prep JSON unparseable for {name} — retrying", contact_id)
        if not obj:
            self.last_error = "prep produced no usable JSON (after retry)"
            return {"error": "prep produced no usable JSON (after retry)"}

        # Normalize defensively. The ask is ONLY seller-stated: model's extraction,
        # else the screening's (also seller-stated). No ask → anchors stay null no
        # matter what the model said (the never-invent-an-ARV guard in code).
        ask = _money(obj.get("askingPrice"))
        if ask is None:
            ask = _money(rep.get("askingPrice"))
        a = obj.get("anchors") if isinstance(obj.get("anchors"), dict) else {}
        if ask is None:
            anchors = {"opening": None, "target": None, "walkaway": None}
        else:
            anchors = {"opening": _money(a.get("opening")),
                       "target": _money(a.get("target")),
                       "walkaway": _money(a.get("walkaway")) or ask}
        condition = _s(obj.get("condition"), 40).lower()
        if condition not in CONDITIONS:
            condition = "unknown"
        occupancy = _s(obj.get("occupancy"), 40).lower()
        if occupancy not in OCCUPANCIES:
            occupancy = "unknown"
        prep = {
            "address": _s(obj.get("address"), 200) or None,
            "askingPrice": ask,
            "beds": _num(obj.get("beds")),
            "baths": _num(obj.get("baths")),
            "condition": condition,
            "occupancy": occupancy,
            "timeline": _s(obj.get("timeline"), 200) or "unknown",
            "motivationRead": _s(obj.get("motivationRead"), 400),
            "repairEstimate": _s(obj.get("repairEstimate"), 300) or "unknown",
            "anchors": anchors,
            "anchorLogic": _s(obj.get("anchorLogic"), 500),
            "maoNote": _s(obj.get("maoNote"), 600),
            "callCard": _slist(obj.get("callCard"), 7),
            "redFlags": _slist(obj.get("redFlags"), 8),
        }

        now = int(time.time() * 1000)
        with self.lock:
            prev = self.preps.get(contact_id) or {}
            self.preps[contact_id] = {
                "contactId": contact_id,
                "convId": conv_id,
                "name": name,
                "screeningScore": rep.get("score"),
                "interest": rep.get("interest"),
                "screenedAt": screened_at,    # cache key: re-prep only when the screening moves
                "prep": prep,
                "createdAt": prev.get("createdAt") or now,
                "updatedAt": now,
            }
            self._log("prep", f"Prepped deal for {name} — anchors "
                      f"{_fmt_money(anchors['opening'])}/{_fmt_money(anchors['target'])}/"
                      f"{_fmt_money(anchors['walkaway'])}", contact_id)
            self.last_error = None
            self.learn_state["preppedSinceLearn"] = self.learn_state.get("preppedSinceLearn", 0) + 1
            self._save()
        return {"ok": True, "prep": self.preps[contact_id]}

    # -- the sweep -----------------------------------------------------------------
    def auto_prep_interested(self, min_score=6):
        """Walk Marcus's screenings, prep every interest=='interested' lead scoring
        >= min_score that has no fresh prep. Cap SWEEP_CAP Claude calls per sweep;
        best-effort per lead (one failure never kills the sweep). Each finished prep
        is reported to Marcus (the lead agent) on the bus."""
        prepped, skipped, calls = [], 0, 0
        if forge_ops.paused():               # clocked out — Atlas stops auto-prepping
            return {"prepped": prepped, "skipped": skipped, "paused": True}
        if self.screener is None:
            return {"prepped": prepped, "skipped": skipped}
        for cid, r in list(getattr(self.screener, "screenings", {}).items()):
            rep = r.get("report") or {}
            try:
                score = int(rep.get("score") or 0)
            except (ValueError, TypeError):
                score = 0
            if rep.get("interest") != "interested" or score < min_score:
                skipped += 1
                continue
            existing = self.preps.get(cid)
            if existing and existing.get("screenedAt") == r.get("updatedAt"):
                skipped += 1
                continue
            if calls >= SWEEP_CAP:
                break
            calls += 1
            try:
                res = self.prep(cid)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"auto-prep {cid}: {e}"
                continue
            if not (isinstance(res, dict) and res.get("ok")):
                continue
            rec = res.get("prep") or {}
            name = rec.get("name") or "(unknown)"
            prepped.append(name)
            an = (rec.get("prep") or {}).get("anchors") or {}
            try:
                import agent_bus
                agent_bus.send("atlas", "marcus", "handoff",
                               f"📐 Deal prep ready for {name} — anchors "
                               f"{_fmt_money(an.get('opening'))}/{_fmt_money(an.get('target'))}/"
                               f"{_fmt_money(an.get('walkaway'))}",
                               {"type": "deal_prep", "contactId": cid})
            except Exception:
                pass
        self._maybe_learn(_atlas_key())
        return {"prepped": prepped, "skipped": skipped}

    # -- self-improvement (learn from real preps, rewrite own playbook) ------------
    def _maybe_learn(self, key):
        now = int(time.time() * 1000)
        st = self.learn_state
        last = st.get("lastLearnedAt") or 0
        if (key and st.get("preppedSinceLearn", 0) >= LEARN_EVERY
                and (now - last) >= LEARN_MIN_INTERVAL_MS):
            try:
                self.learn(auto=True)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"learn: {e}"

    def learn(self, auto=False):
        """Claude reflects on Atlas's recent real deal preps + current playbook,
        then rewrites Skills/atlas-underwriter.md into the Obsidian brain
        (git-committed). Next prep reloads it — closed adaptive loop, mirrors
        Scout's learn() (scout_triage.py)."""
        key = _atlas_key()
        if not key:
            return {"error": "no anthropic key"}
        rows = sorted(self.preps.values(), key=lambda r: -(r.get("updatedAt") or 0))[:10]
        lines = []
        for r in rows:
            p = r.get("prep") or {}
            an = p.get("anchors") or {}
            lines.append(
                f"[{p.get('condition')}] anchors={_fmt_money(an.get('opening'))}/"
                f"{_fmt_money(an.get('target'))}/{_fmt_money(an.get('walkaway'))} :: "
                f"logic={(p.get('anchorLogic') or '')[:160]} :: "
                f"mao={(p.get('maoNote') or '')[:160]} :: "
                f"redFlags={'; '.join(p.get('redFlags') or [])[:160]}")
        if not lines:
            return {"error": "no encounters to learn from yet"}
        current = self._load_skills() or "(no playbook yet — create one)"
        system = (
            "You are Atlas, a SELF-IMPROVING deal-underwriting analyst for a real estate "
            "WHOLESALING business. Below is your CURRENT playbook and a sample of real "
            "deal preps you actually produced. Improve yourself: sharpen the anchor "
            "derivation logic, the MAO math guidance, condition/repair-estimate reads, "
            "red-flag patterns, and call-card structure based on what worked. Output the "
            "FULL UPDATED playbook as clean markdown — a practical underwriting rubric. "
            "HARD RULE, restate it verbatim and never soften it: anchors derive ONLY from "
            "the SELLER'S OWN stated price (opening ~70-75% of ask, target ~80-85%, "
            "walkaway = the ask) — never invent an ARV, comp value, or market price; no "
            "seller-stated ask means anchors stay null and maoNote spells out exactly what "
            "comp data the operator needs to pull. Atlas never contacts anyone and every "
            "number is INTERNAL operator prep. Keep it tight and actionable. Output ONLY "
            "the markdown."
        )
        user = ("CURRENT PLAYBOOK:\n" + current[:4000]
                + "\n\nRECENT REAL DEAL PREPS (your own output — learn from these):\n"
                + "\n".join(lines))
        try:
            new_md = review_agent._claude(key, system, user, max_tokens=2200)
        except Exception as e:  # noqa: BLE001
            return {"error": f"claude: {e}"}
        if not new_md or len(new_md) < 200:
            return {"error": "learning produced nothing usable"}
        stamp = time.strftime("%Y-%m-%d %H:%M")
        header = (f"---\nagent: atlas\nupdated: {stamp}\n"
                  f"source: self-improvement (learned from {len(lines)} recent preps)\n---\n\n")
        try:
            import brain_io
            res = brain_io.write_note(SKILL_REL, header + new_md.strip(),
                                      reason=f"atlas self-improve {stamp}")
        except Exception as e:  # noqa: BLE001
            return {"error": f"brain write failed: {e}"}
        with self.lock:
            self.learn_state["lastLearnedAt"] = int(time.time() * 1000)
            self.learn_state["learnCount"] = self.learn_state.get("learnCount", 0) + 1
            self.learn_state["preppedSinceLearn"] = 0
            self._sk_mtime = None  # force reload of the freshly-written playbook
            self._log("learn", f"Self-improved underwriting playbook from {len(lines)} "
                      f"preps ({'auto' if auto else 'manual'})")
            self._save()
        try:
            import agent_bus
            agent_bus.send("atlas", "marcus", "status",
                           f"Atlas updated its underwriting playbook (self-improvement "
                           f"#{self.learn_state['learnCount']}, from {len(lines)} preps).",
                           {"learnCount": self.learn_state["learnCount"]})
        except Exception:
            pass
        return {"ok": True, "learnCount": self.learn_state["learnCount"],
                "wrote": SKILL_REL, "fromEncounters": len(lines),
                "committed": (res or {}).get("committed"), "auto": auto}

    # -- public reads ----------------------------------------------------------------
    def get(self, contact_id):
        return self.preps.get(contact_id) or {}

    def list_all(self):
        """Newest-first prep records for the dashboard."""
        rows = sorted(self.preps.values(), key=lambda r: -(r.get("updatedAt") or 0))
        return {"preps": rows, "count": len(rows)}

    def status(self):
        return {
            "connected": True,
            "aiPrep": bool(_atlas_key()),
            "model": review_agent.MODEL,
            "autoPrep": AUTO_PREP,
            "total": len(self.preps),
            "lastError": self.last_error,
            "activity": self.activity[:40],
            "skillsLoaded": bool(self._load_skills()),
            "learn": self.learn_state,
        }

    # -- the loop ----------------------------------------------------------------------
    def run_forever(self, interval=900):
        """Sweep every 15 min: prep what Marcus screened as interested. Never raises."""
        while True:
            try:
                if AUTO_PREP:
                    self.auto_prep_interested()
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
            forge_heartbeat.beat("atlas", interval, "Atlas underwriter",
                                 error=self.last_error)
            time.sleep(interval)
