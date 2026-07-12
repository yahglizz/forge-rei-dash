"""marcus_screening.py — Marcus, the wholesale lead-SCREENING agent.

Marcus reads a seller's GoHighLevel SMS thread + Scout's triage, then writes a
**Seller Screening Report**: a 1-10 call-readiness score, the seller's situation,
what info is missing, red flags, call-prep notes, and a recommended lead stage —
so the operator (Yahjair) knows who to personally CALL.

Marcus is NOT a closer. He never texts a seller, never makes an offer, never talks
numbers (no ARV / MAO / price unless the seller already gave one), never writes a
contract. He only produces decision-support reports; the human calls.

Division of labour (do NOT duplicate Scout):
- Scout owns triage: motivation 0-100, bucket, tags, pipeline pushes, hot alerts,
  the missed-leads audit. Marcus CONSUMES Scout's per-lead record as input.
- Marcus adds the deep qualification layer + call-prep that Scout doesn't do.
- The only GHL writes Marcus triggers are the operator's stage-button clicks, and
  those REUSE Scout's already-gated apply_tags / add_to_pipeline / dismiss.

Self-improving (mirrors Scout): loads a playbook merged from the forge-marcus seed
(`forge-marcus/skills/marcus-screening-playbook.md`) + the brain vault copy
(mtime hot-reload); `learn()` reflects on recent screenings and rewrites the vault
playbook (git-committed); broadcasts on the agent bus. Reuses review_agent._claude.

State persists to marcus_state/screenings.json. The dormant SMS engine
(marcus_engine.py) is untouched and stays off — screening is Marcus's front door.
"""

import forge_atomic
import json
import os
import re
import send_ledger
import threading
import time
from pathlib import Path

import review_agent
import agent_context   # per-lead brain search (past screenings, closing plays, lessons)
import marcus_engine   # classify / _is_soft_no / _is_our_message — judge seller interest

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "screenings.json"
MARCUS_DIR = HERE.parent / "forge-marcus"        # Marcus's config + seed skills (outside web root)


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


def _marcus_key():
    """Marcus's Anthropic key: his own (marcus.env / MARCUS_ANTHROPIC_API_KEY) else
    the shared wholesale key. Mirrors _scout_key resolution; ignores placeholders."""
    for env_key in ("MARCUS_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
        v = os.environ.get(env_key)
        if v and not v.startswith("sk-ant-..."):
            return v
    return review_agent._api_key()


SCREEN_MSGS = int(os.environ.get("FORGE_SCREEN_MSGS", "20"))             # msgs pulled per thread
AUTO_SCREEN = os.environ.get("FORGE_SCREEN_AUTO", "1") != "0"            # auto-screen Scout's hot leads
LEARN_EVERY = int(os.environ.get("FORGE_MARCUS_LEARN_EVERY", "15"))      # auto self-improve after N screenings
LEARN_MIN_INTERVAL_MS = int(os.environ.get("FORGE_MARCUS_LEARN_GAP_MIN", "45")) * 60 * 1000
PLAYBOOK_REL = "Skills/marcus-screening-playbook.md"                     # learned playbook in the brain
MAX_RECORDS = 300

STAGES = ["New Lead", "Needs More Info", "Follow-Up",
          "Qualified - Call", "Hot Lead - Call Now", "Dead Lead"]
STAGE_ORDER = {"Hot Lead - Call Now": 0, "Qualified - Call": 1, "Needs More Info": 2,
               "Follow-Up": 3, "New Lead": 4, "Dead Lead": 5}
_MOTIV = {"low": "low", "med": "medium", "medium": "medium", "high": "high"}
SAFE_NURTURE_FALLBACK = (
    "100% no worries at all, is it ok if i check back with you in a few months"
)


def _safe_nurture_draft(text, seller_context=""):
    """Never put model failure/meta/persona/price-confirmation text in the UI."""
    cleaned = marcus_engine.MarcusEngine._scrub_voice(text or "")
    if not cleaned:
        return None, None
    reason = marcus_engine._draft_safety_reason(cleaned, seller_context)
    if reason:
        return SAFE_NURTURE_FALLBACK, reason
    return cleaned, None


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
    # Defensive: if the model wrapped the report under a single key (e.g.
    # {"screening_report": {...}}), unwrap to the inner object.
    if "score" not in obj and "sellerSituation" not in obj:
        for v in obj.values():
            if isinstance(v, dict) and ("score" in v or "sellerSituation" in v or "callPrep" in v):
                return v
    return obj


def _stage_from_score(score):
    if score >= 9:
        return "Hot Lead - Call Now"
    if score >= 7:
        return "Qualified - Call"
    if score >= 4:
        return "Follow-Up"
    if score >= 1:
        return "New Lead"
    return "Dead Lead"


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


class Screener:
    def __init__(self, ghl_get, location_id, scout=None, ghl_post=None):
        self.ghl_get = ghl_get
        self.ghl_post = ghl_post
        self.location_id = location_id
        self.scout = scout            # Scout engine — triage input + gated GHL writes
        self.lock = threading.Lock()
        self.screenings = {}          # contactId -> screening record
        self.activity = []            # ring buffer of screening actions
        self.last_error = None
        self.learn_state = {"lastLearnedAt": None, "learnCount": 0, "screenedSinceLearn": 0}
        self._sk_text = ""
        self._sk_mtime = None
        self._voice_text = ""      # operator's learned texting voice (for nurture drafts)
        self._voice_mtime = None
        self._load()

    # -- persistence --------------------------------------------------------
    def _load(self):
        try:
            if STATE.exists():
                d = json.loads(STATE.read_text())
                if isinstance(d, dict):
                    self.screenings = d.get("screenings", {}) or {}
                    self.activity = d.get("activity", []) or []
                    self.learn_state = d.get("learnState", self.learn_state) or self.learn_state
        except Exception:
            self.screenings, self.activity = {}, []

    def _log(self, kind, text, contact_id=None):
        self.activity.insert(0, {"ts": int(time.time() * 1000), "kind": kind,
                                 "text": text, "contactId": contact_id})
        self.activity = self.activity[:100]

    def _save(self):
        if len(self.screenings) > MAX_RECORDS:
            keep = sorted(self.screenings.values(),
                          key=lambda r: r.get("updatedAt") or 0, reverse=True)[:MAX_RECORDS]
            self.screenings = {r["contactId"]: r for r in keep}
        forge_atomic.atomic_write_json(STATE, {"screenings": self.screenings,
                                               "activity": self.activity,
                                               "learnState": self.learn_state})

    # -- brain skills (mtime-cached seed + learned vault playbook) -----------
    def _load_skills(self):
        try:
            import brain_io
            parts, sig = [], []
            srcs = [MARCUS_DIR / "skills" / "marcus-lead-agent.md",
                    brain_io.VAULT / "Skills" / "marcus-lead-agent.md",
                    MARCUS_DIR / "skills" / "marcus-screening-playbook.md",
                    brain_io.VAULT / "Skills" / "marcus-screening-playbook.md",
                    MARCUS_DIR / "skills" / "marcus-critical-thinking.md",
                    brain_io.VAULT / "Skills" / "marcus-critical-thinking.md",
                    MARCUS_DIR / "skills" / "marcus-seller-psychology.md",
                    brain_io.VAULT / "Skills" / "marcus-seller-psychology.md",
                    MARCUS_DIR / "skills" / "marcus-nurture-followup.md",
                    brain_io.VAULT / "Skills" / "marcus-nurture-followup.md",
                    MARCUS_DIR / "skills" / "wholesale-seller-texter.md",
                    brain_io.VAULT / "Skills" / "wholesale-seller-texter.md"]
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

    def _load_voice(self):
        """The operator's learned texting voice (style_agent → vault) so any draft Marcus
        writes sounds like him. mtime-cached. Used for the nurture/check-back message."""
        try:
            import brain_io
            parts, sig = [], []
            for rel in ("Skills/yahjair-voice.md", "Skills/marcus-playbook.md"):
                p = brain_io.VAULT / rel
                if p.is_file():
                    parts.append(p.read_text(errors="ignore"))
                    sig.append(p.stat().st_mtime)
            sig = tuple(sig)
            if self._voice_mtime != sig:
                self._voice_text = "\n\n".join(parts)
                self._voice_mtime = sig
            return self._voice_text
        except Exception:
            return self._voice_text

    # -- lead resolution + transcript ---------------------------------------
    def _resolve(self, contact_id=None, conv_id=None):
        """Resolve a lead to (convId, contactId, name, phone, scout-rec). Prefers
        Scout's record; falls back to a GHL conversation search by contactId."""
        rec = None
        if self.scout is not None:
            if conv_id:
                rec = self.scout.records.get(conv_id)
            if not rec and contact_id:
                rec = next((r for r in self.scout.records.values()
                            if r.get("contactId") == contact_id), None)
        name = phone = None
        if rec:
            conv_id = conv_id or rec.get("convId")
            contact_id = contact_id or rec.get("contactId")
            name, phone = rec.get("name"), rec.get("phone")
        if not conv_id and contact_id:
            try:
                data = self.ghl_get("/conversations/search",
                                    {"locationId": self.location_id, "contactId": contact_id})
                convos = data.get("conversations", []) or []
                if convos:
                    c = convos[0]
                    conv_id = c.get("id")
                    name = name or c.get("fullName") or c.get("contactName")
                    phone = phone or c.get("phone")
                    contact_id = contact_id or c.get("contactId")
            except Exception as e:  # noqa: BLE001
                self.last_error = f"resolve: {e}"
        return {"convId": conv_id, "contactId": contact_id,
                "name": name or "(unknown)", "phone": phone or "", "rec": rec}

    def _thread(self, conv_id):
        """Full seller thread oldest-first: list of {direction, body}. Read-only."""
        if not conv_id:
            return []
        try:
            data = self.ghl_get(f"/conversations/{conv_id}/messages", {"limit": SCREEN_MSGS})
        except Exception as e:  # noqa: BLE001
            self.last_error = f"thread: {e}"
            return []
        raw = data.get("messages", data) if isinstance(data, dict) else data
        if isinstance(raw, dict):
            raw = raw.get("messages", [])
        msgs = [{"direction": m.get("direction"), "body": (m.get("body") or "").strip()}
                for m in (raw or []) if (m.get("body") or "").strip()]
        msgs.reverse()  # GHL newest-first -> chat order
        return msgs

    def _transcript(self, msgs):
        lines = []
        for m in msgs[-SCREEN_MSGS:]:
            who = "Seller" if m.get("direction") == "inbound" else "You (operator)"
            lines.append(f"{who}: {m['body'][:400]}")
        return "\n".join(lines) if lines else "(no messages in this thread yet)"

    # -- the screen ---------------------------------------------------------
    def screen(self, contact_id=None, conv_id=None, auto=False):
        """Generate (or refresh) a seller screening report. One Claude call."""
        info = self._resolve(contact_id, conv_id)
        conv_id, contact_id = info["convId"], info["contactId"]
        if not contact_id:
            return {"error": "no contact for this lead"}
        if not conv_id:
            return {"error": "no conversation for this contact yet — they haven't texted in"}
        key = _marcus_key()
        if not key:
            return {"error": "no anthropic key"}
        msgs = self._thread(conv_id)
        transcript = self._transcript(msgs)
        rec = info["rec"] or {}

        # Cheap pre-filter so Marcus doesn't waste a screen on someone he shouldn't entertain:
        # need a real seller message, and skip hard opt-outs (STOP/remove me). The model then
        # reads the whole thread and decides interest (interested / not_ready / not_interested).
        inbound = [m["body"] for m in msgs if m.get("direction") == "inbound" and (m.get("body") or "").strip()]
        last_in = inbound[-1] if inbound else ""
        if not marcus_engine._is_seller_message(last_in):
            return {"skipped": "no seller message to screen yet — not entertaining"}
        if marcus_engine.classify(last_in) == "DNC":
            return {"skipped": "seller opted out (stop/remove) — not entertaining"}
        if marcus_engine._is_opt_out(last_in):
            return {"skipped": "explicit opt-out / please stop contacting — not entertaining"}
        if marcus_engine._is_denial(last_in):
            return {"skipped": "wrong number / not the seller — not entertaining"}

        triage = "Scout's triage for this lead: (not yet scored by Scout)"
        if rec:
            triage = ("Scout's triage (INPUT — do not recompute): "
                      f"motivation {rec.get('motivation')}/100, bucket {rec.get('bucket')}, "
                      f"intent {rec.get('intent')}, reason \"{rec.get('reason') or '-'}\""
                      + (f", seller-stated asking ${rec.get('askingPrice')}"
                         if rec.get("askingPrice") else ", no asking price stated"))

        system = (
            "You are Marcus, a real-estate WHOLESALING lead-SCREENING analyst (the operator "
            "is Yahjair). Think like a sharp analyst AND a student of seller psychology: read "
            "the seller's text thread + Scout's triage critically (separate fact from inference "
            "from assumption), figure out the seller's REAL motivation and emotional state, and "
            "map the realistic PATH TO A SIGNED CONTRACT — then arm the operator's CALL. Apply "
            "the CRITICAL-THINKING and SELLER-PSYCHOLOGY skills below.\n\n"
            "OUTPUT: return ONE JSON object and NOTHING else — no prose, no markdown, no code "
            "fences, no wrapper key, no extra keys. Use EXACTLY these keys and types:\n"
            '{"score": <integer 1-10>, '
            '"interest": "<interested | not_ready | not_interested>", '
            '"stage": "<one of: New Lead | Needs More Info | Follow-Up | Qualified - Call | Hot Lead - Call Now | Dead Lead>", '
            '"sellerSituation": "<1-3 sentence evidence-based read of their TRUE situation>", '
            '"motivationLevel": "<low|medium|high>", '
            '"sellerPsychology": "<1-3 sentences: the seller\'s likely emotion + decision style + what drives THEM (the real motivation/trigger), and the trust driver that matters most>", '
            '"propertyStatus": "<owner-occupied|tenant-occupied|vacant|unknown>", '
            '"conditionNotes": "<what the thread reveals, or \'not mentioned\'>", '
            '"timeline": "<their timeline, or \'unknown\'>", '
            '"askingPrice": <the price string the SELLER stated, else null>, '
            '"missing": ["<key facts the thread never revealed>"], '
            '"redFlags": ["<concrete concerns + deal-killers e.g. spouse not aligned, no real pain>"], '
            '"whyCall": "<1-2 sentences: worth calling or not>", '
            '"pathToContract": "<the realistic play to move THIS convo toward a signed contract: where they are on the commitment ladder, the biggest obstacle to clear, and the leverage to use — strategy for the operator, NEVER an offer or a price>", '
            '"recommendedAction": "<single next best action>", '
            '"checkBackDays": <integer 30-180 if the seller is NOT ready to sell right now, else null>, '
            '"nurtureDraft": "<ONLY if the seller is NOT ready to sell right now: a short warm no-pressure SMS in the OPERATOR\'S VOICE (all lowercase, casual) that respects their not-now, reassures them there is no rush/obligation, and asks if it is ok to check back in ~checkBackDays. NO price, NO offer. Else null>", '
            '"callPrep": {"opener": "<price-free first line matched to their decision style>", "questions": ["<3-6 questions that confirm the hypothesis + uncover motivation>"], '
            '"painPoints": ["<emotional/motivation signals to listen for>"], "avoid": ["<what NOT to say>"]}}\n\n'
            "SCORE BANDS: 9-10 hot/call now, 7-8 qualified/call soon, 4-6 follow-up, 1-3 weak, 0 dead. "
            "Score on MOTIVATION + real problem, not friendliness; a thin thread = low score + lots of Missing Info, not a hopeful guess.\n"
            "INTEREST LANES (decide from the WHOLE thread): 'interested' = engaged / shows some willingness to sell "
            "→ full qualification + call prep, set nurtureDraft and checkBackDays to null. "
            "'not_ready' = says not selling right now / not for sale / not interested for now / maybe later / a few "
            "months — but did NOT hard opt-out (no stop/remove/hostile) → set stage 'Follow-Up', and FILL "
            "nurtureDraft (a short no-pressure comfort + check-back message in the OPERATOR'S voice, apply the nurture "
            "skill) + checkBackDays (30-180). 'not_interested' = clear permanent no / wrong number / not the owner / "
            "hostile → set stage 'Dead Lead', nurtureDraft null. Treat a plain 'not for sale' / 'not selling' as "
            "not_ready (keep-in-touch), NOT not_interested.\n"
            "HARD RULES (never break): never contact the seller yourself; NO ARV, NO MAO, NO offer numbers; "
            "NO price unless the seller already stated one (then just report it); no contracts; "
            "pathToContract + callPrep are strategy for the operator, never a quote or offer; nurtureDraft is "
            "comfort + a check-back only, never a price/offer; always include 'don't lead with price / don't make "
            "an offer yet' in callPrep.avoid; do NOT recompute Scout's triage — use it as input. Output ONLY the JSON object."
        )
        skills = self._load_skills()
        if skills:
            system += ("\n\n=== YOUR SKILLS (screening rubric + critical-thinking + seller-psychology + nurture — apply them) ===\n"
                       + skills[:9000])
        voice = self._load_voice()
        if voice:
            system += ("\n\n=== THE OPERATOR'S VOICE (write ANY draft EXACTLY like this — his real texting style) ===\n"
                       + voice[:2500])
        # Pull the brain's relevant history for THIS seller's situation (past screenings,
        # closing plays, seller-psychology, missed-lead lessons) so Marcus reasons WITH what
        # the system has already learned, not just the static rubric. Best-effort → "".
        ctx = agent_context.brain_context(
            agent_context.seller_query(rec.get("name"), rec.get("reason"),
                                       rec.get("intent"), last_in),
            header="RELEVANT BRAIN NOTES (past screenings, closing plays, seller psychology, lessons)")
        if ctx:
            system += "\n\n" + ctx
        user = (triage + "\n\nSELLER TEXT THREAD (oldest first):\n" + transcript
                + "\n\nReturn the screening report JSON now.")
        try:
            raw = review_agent._claude(key, system, user, max_tokens=1400)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"claude: {e}"
            return {"error": f"claude: {e}"}
        obj = _parse_obj(raw)
        if not obj:
            return {"error": "screening produced no usable report"}

        # Normalize the report defensively.
        try:
            score = int(obj.get("score"))
        except (ValueError, TypeError):
            score = 0
        score = max(0, min(10, score))
        # Interest lane comes from the model's read of the whole thread.
        interest = obj.get("interest")
        if interest not in ("interested", "not_ready", "not_interested"):
            interest = "interested"
        not_ready = interest == "not_ready"
        stage = obj.get("stage") if obj.get("stage") in STAGES else _stage_from_score(score)
        if interest == "not_interested":
            stage = "Dead Lead"
        elif not_ready and stage == "Dead Lead":
            stage = "Follow-Up"   # a "not right now" lead is nurtured, not dead
        cp = obj.get("callPrep") or {}
        # Asking price: ONLY seller-stated. Trust the model's value; else fall back to
        # Scout's regex-extracted price (also seller-stated). Never invent one.
        asking = obj.get("askingPrice")
        if not asking and rec.get("askingPrice"):
            asking = f"${rec['askingPrice']:,}"
        # Nurture fields — only for not-ready sellers; comfort + check-back, never a price.
        try:
            cb = max(30, min(180, int(obj.get("checkBackDays"))))
        except (ValueError, TypeError):
            cb = 90 if not_ready else None
        nurture = str(obj.get("nurtureDraft") or "").strip()[:600] or None
        seller_context = "\n".join(inbound[-8:])
        nurture, nurture_blocked = _safe_nurture_draft(nurture, seller_context)
        if not not_ready:
            nurture, cb, nurture_blocked = None, None, None
        report = {
            "score": score,
            "stage": stage,
            "interest": interest,
            "sellerSituation": str(obj.get("sellerSituation") or "").strip()[:600],
            "motivationLevel": _MOTIV.get(str(obj.get("motivationLevel") or "").lower(), "unknown"),
            "sellerPsychology": str(obj.get("sellerPsychology") or "").strip()[:600],
            "checkBackDays": cb,
            "nurtureDraft": nurture,
            "nurtureSafety": ({"replaced": True, "reason": nurture_blocked}
                              if nurture_blocked else None),
            "propertyStatus": str(obj.get("propertyStatus") or "unknown").strip()[:60],
            "conditionNotes": str(obj.get("conditionNotes") or "not mentioned").strip()[:400],
            "timeline": str(obj.get("timeline") or "unknown").strip()[:200],
            "askingPrice": asking or None,
            "missing": _slist(obj.get("missing")),
            "redFlags": _slist(obj.get("redFlags")),
            "whyCall": str(obj.get("whyCall") or "").strip()[:400],
            "pathToContract": str(obj.get("pathToContract") or "").strip()[:600],
            "recommendedAction": str(obj.get("recommendedAction") or "").strip()[:300],
            "callPrep": {
                "opener": str(cp.get("opener") or "").strip()[:300],
                "questions": _slist(cp.get("questions")),
                "painPoints": _slist(cp.get("painPoints")),
                "avoid": _slist(cp.get("avoid")) or ["Don't lead with a price or make an offer on the first call."],
            },
        }

        now = int(time.time() * 1000)
        with self.lock:
            prev = self.screenings.get(contact_id) or {}
            self.screenings[contact_id] = {
                "contactId": contact_id,
                "convId": conv_id,
                "name": info["name"],
                "phone": info["phone"],
                "score": score,
                "stage": prev.get("stageOverride") and prev.get("stage") or stage,
                "report": report,
                "scoutMotivation": rec.get("motivation"),
                "scoutBucket": rec.get("bucket"),
                "notes": prev.get("notes", ""),          # preserve operator call notes on re-screen
                "stageOverride": prev.get("stageOverride", False),
                "nurtureSentAt": prev.get("nurtureSentAt"),   # preserve check-back sent state
                "nurtureSent": prev.get("nurtureSent"),
                "status": "screened",
                "auto": bool(auto),
                "createdAt": prev.get("createdAt") or now,
                "updatedAt": now,
            }
            self.learn_state["screenedSinceLearn"] = self.learn_state.get("screenedSinceLearn", 0) + 1
            self._log("screen", f"Screened {info['name']} — score {score}/10, {stage}"
                      + (" (auto)" if auto else ""), contact_id)
            self.last_error = None
            self._save()

        self._write_brain_note(contact_id)
        self._maybe_learn(key)
        return {"ok": True, "screening": self._slim(self.screenings[contact_id])}

    def auto_screen(self, contact_id=None, conv_id=None):
        """Best-effort screen triggered when Scout flags a hot lead (bus tap)."""
        if not AUTO_SCREEN:
            return {"skipped": "auto-screen off"}
        try:
            return self.screen(contact_id=contact_id, conv_id=conv_id, auto=True)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"auto: {e}"
            return {"error": str(e)}

    def _write_brain_note(self, contact_id):
        """Best-effort: mirror the latest report into the Obsidian brain (git-committed)."""
        try:
            import brain_io
            r = self.screenings.get(contact_id)
            if not r:
                return
            rep = r["report"]
            stamp = time.strftime("%Y-%m-%d %H:%M")
            cp = rep["callPrep"]
            md = (f"---\nagent: marcus\ntype: seller-screening\nupdated: {stamp}\n"
                  f"contact: {r['name']}\nscore: {rep['score']}\nstage: {rep['stage']}\n---\n\n"
                  f"# Seller Screening — {r['name']}\n\n"
                  f"**Score:** {rep['score']}/10 · **Stage:** {rep['stage']} · "
                  f"**Motivation:** {rep['motivationLevel']} (Scout {r.get('scoutMotivation')}/100)\n\n"
                  f"**Situation:** {rep['sellerSituation']}\n\n"
                  + (f"**Psychology:** {rep.get('sellerPsychology')}\n\n" if rep.get('sellerPsychology') else "")
                  + f"- Property: {rep['propertyStatus']} · Condition: {rep['conditionNotes']}\n"
                  f"- Timeline: {rep['timeline']}"
                  + (f" · Seller asking: {rep['askingPrice']}" if rep['askingPrice'] else "") + "\n\n"
                  f"**Why call:** {rep['whyCall']}\n\n"
                  + (f"**Path to contract:** {rep.get('pathToContract')}\n\n" if rep.get('pathToContract') else "")
                  + f"**Recommended:** {rep['recommendedAction']}\n\n"
                  f"**Missing:** {', '.join(rep['missing']) or '—'}\n\n"
                  f"**Red flags:** {', '.join(rep['redFlags']) or '—'}\n\n"
                  f"## Call prep\n- Opener: {cp['opener']}\n"
                  + "".join(f"- Ask: {q}\n" for q in cp['questions'])
                  + "".join(f"- Listen for: {p}\n" for p in cp['painPoints'])
                  + "".join(f"- Avoid: {a}\n" for a in cp['avoid']))
            safe = re.sub(r"[^a-zA-Z0-9]+", "-", (r["name"] or contact_id)).strip("-").lower() or contact_id
            brain_io.write_note(f"Reports/screening-{safe}.md", md,
                                reason=f"marcus screening {r['name']}")
        except Exception:
            pass

    # -- public reads -------------------------------------------------------
    def _slim(self, r):
        rep = r.get("report") or {}
        return {
            "contactId": r.get("contactId"),
            "convId": r.get("convId"),
            "name": r.get("name"),
            "phone": r.get("phone"),
            "score": rep.get("score", r.get("score")),
            "stage": r.get("stage"),
            "scoutMotivation": r.get("scoutMotivation"),
            "scoutBucket": r.get("scoutBucket"),
            "notes": r.get("notes", ""),
            "auto": r.get("auto", False),
            "nurtureSentAt": r.get("nurtureSentAt"),
            "createdAt": r.get("createdAt"),
            "updatedAt": r.get("updatedAt"),
            "report": rep,
        }

    def queue(self):
        rows = list(self.screenings.values())
        rows.sort(key=lambda r: (STAGE_ORDER.get(r.get("stage"), 9),
                                 -((r.get("report") or {}).get("score") or 0),
                                 -(r.get("updatedAt") or 0)))
        return {"screenings": [self._slim(r) for r in rows], "count": len(rows),
                "stages": STAGES}

    def report(self, contact_id):
        r = self.screenings.get(contact_id)
        if not r:
            return {"error": "no screening for this contact"}
        return {"ok": True, "screening": self._slim(r)}

    def note(self, contact_id, text):
        with self.lock:
            r = self.screenings.get(contact_id)
            if not r:
                return {"error": "no screening for this contact"}
            r["notes"] = (text or "")[:4000]
            r["updatedAt"] = int(time.time() * 1000)
            self._log("note", f"Saved call notes for {r.get('name')}", contact_id)
            self._save()
            return {"ok": True}

    def set_stage(self, contact_id, stage):
        """Operator picks a lead stage. Records the verdict and, via Scout's already-
        gated writes, reflects it into GHL (tags/pipeline) or dismisses it."""
        if stage not in STAGES:
            return {"error": f"unknown stage '{stage}'"}
        with self.lock:
            r = self.screenings.get(contact_id)
            if not r:
                return {"error": "no screening for this contact"}
            conv_id = r.get("convId")
            r["stage"] = stage
            r["stageOverride"] = True
            r["updatedAt"] = int(time.time() * 1000)
            self._log("stage", f"{r.get('name')} → {stage}", contact_id)
            self._save()
        # Reflect into GHL via Scout's gated methods (best-effort; needs Scout to know the conv).
        ghl = None
        if self.scout is not None and conv_id and conv_id in getattr(self.scout, "records", {}):
            try:
                if stage in ("Qualified - Call", "Hot Lead - Call Now"):
                    self.scout.apply_tags(conv_id)
                    ghl = self.scout.add_to_pipeline(conv_id, stage="Hot")
                elif stage in ("Follow-Up", "Needs More Info"):
                    ghl = self.scout.add_to_pipeline(conv_id, stage="Warm")
                elif stage == "Dead Lead":
                    ghl = self.scout.dismiss(conv_id)
            except Exception as e:  # noqa: BLE001
                ghl = {"error": str(e)}
        return {"ok": True, "stage": stage, "ghl": ghl}

    # -- nurture send (gated; the only outward action) ----------------------
    def send_nurture(self, contact_id, message=None):
        """Operator clicks 'Send check-back': send the comfort/check-back SMS to a
        NOT-READY seller via GHL. Gated (one click) — never auto. Nurture only:
        comfort + a check-back, never a price or offer."""
        with self.lock:
            r = self.screenings.get(contact_id)
        if not r:
            return {"error": "no screening for this contact"}
        conv_id = r.get("convId")
        rep = r.get("report") or {}
        text = (message if message is not None else rep.get("nurtureDraft") or "").strip()
        if not conv_id:
            return {"error": "no conversation to send to"}
        if not text:
            return {"error": "no nurture message to send"}
        gate = {}
        safety_check = getattr(self, "safety_check", None)
        if not callable(safety_check):
            return {"error": "central sms_guard unavailable", "gate": "sms_guard_missing"}
        gate = safety_check(contact_id, text, conv_id=conv_id, name=r.get("name"),
                            kind="screening_nurture", autonomous=False)
        if not gate.get("ok"):
            return gate
        reservation = gate.get("reservation")
        try:
            self.ghl_post("/conversations/messages",
                          {"type": "SMS", "conversationId": conv_id,
                           "contactId": contact_id, "message": text})
        except Exception as e:  # noqa: BLE001
            safety_release = getattr(self, "safety_release", None)
            if callable(safety_release):
                try:
                    safety_release(reservation)
                except Exception:
                    pass
            return {"error": f"GHL send failed: {e}"}
        with self.lock:
            r = self.screenings.get(contact_id) or r
            now = int(time.time() * 1000)
            r["nurtureSentAt"] = now
            r["nurtureSent"] = text
            r["checkBackCount"] = (r.get("checkBackCount") or 0) + 1  # cadence touch count
            r["checkBackDue"] = False                                 # clear the due flag
            r["updatedAt"] = now
            self._log("nurture", f"Sent no-pressure check-back to {r.get('name')} "
                      f"(touch {r['checkBackCount']})", contact_id)
            self._save()
        safety_record = getattr(self, "safety_record", None)
        if callable(safety_record):
            safety_record(reservation=reservation, conv_id=conv_id, contact_id=contact_id,
                          message=text, kind="nurture")
        return {"ok": True, "sent": text}

    # -- not-ready audit (read-only) ----------------------------------------
    def audit_not_ready(self, days=7):
        """Read-only sweep of the last `days` of seller threads for sellers who said they
        are NOT ready to sell right now, plus how the operator replied. For nurturing the
        'not now' pile. Returns the list (no GHL writes)."""
        if self.scout is None:
            return {"error": "scout unavailable"}
        try:
            days = max(1, min(120, int(days)))
        except (ValueError, TypeError):
            days = 7
        cutoff = int(time.time() * 1000) - days * 24 * 60 * 60 * 1000
        try:
            convos = self.scout._fetch_conversations_since(cutoff)
        except Exception as e:  # noqa: BLE001
            return {"error": f"fetch failed: {e}"}
        found = []
        for c in convos:
            if len(found) >= 40:
                break
            cid, contact_id = c.get("id"), c.get("contactId")
            if not cid or not contact_id:
                continue
            msgs = self.scout._thread_transcript(cid)  # oldest-first {direction, body, date}
            if not msgs:
                continue
            nr_idx = None
            for i, m in enumerate(msgs):
                if m.get("direction") != "inbound":
                    continue
                b = m.get("body") or ""
                if not marcus_engine._is_seller_message(b):
                    continue
                if marcus_engine.classify(b) == "NRN" or marcus_engine._is_soft_no(b):
                    nr_idx = i   # keep the LATEST not-ready message
            if nr_idx is None:
                continue
            your_reply = ""
            for m in msgs[nr_idx + 1:]:
                if m.get("direction") == "outbound" and (m.get("body") or "").strip():
                    your_reply = m.get("body").strip()
                    break
            found.append({
                "contactId": contact_id, "convId": cid,
                "name": c.get("fullName") or c.get("contactName") or "(unknown)",
                "phone": c.get("phone") or "",
                "sellerSaid": (msgs[nr_idx].get("body") or "")[:300],
                "yourReply": (your_reply[:300] if your_reply else "(you didn't reply back)"),
                "replied": bool(your_reply),
                "lastMessageDate": c.get("lastMessageDate"),
            })
        return {"ok": True, "days": days, "scanned": len(convos),
                "count": len(found), "notReady": found}

    # -- self-improvement ---------------------------------------------------
    def _maybe_learn(self, key):
        now = int(time.time() * 1000)
        st = self.learn_state
        if (key and st.get("screenedSinceLearn", 0) >= LEARN_EVERY
                and (now - (st.get("lastLearnedAt") or 0)) >= LEARN_MIN_INTERVAL_MS):
            try:
                self.learn(auto=True)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"learn: {e}"

    def learn(self, auto=False):
        """Claude reflects on Marcus's recent screenings + current playbook, then
        rewrites the screening playbook into the brain (git-committed). Next screen
        reloads it — closed adaptive loop."""
        key = _marcus_key()
        if not key:
            return {"error": "no anthropic key"}
        with self.lock:
            rows = sorted(self.screenings.values(),
                          key=lambda r: -(r.get("updatedAt") or 0))[:12]
        if not rows:
            return {"error": "no screenings to learn from yet"}
        lines = []
        for r in rows:
            rep = r.get("report") or {}
            lines.append(f"[{rep.get('stage')}] score={rep.get('score')} "
                         f"mot={rep.get('motivationLevel')} why={rep.get('whyCall') or '-'} "
                         f":: situation: {(rep.get('sellerSituation') or '')[:160]}")
        current = self._load_skills() or "(no playbook yet — create one)"
        system = (
            "You are Marcus, a SELF-IMPROVING real-estate WHOLESALING lead-SCREENING "
            "analyst. Below is your CURRENT screening playbook and a sample of real "
            "screenings you produced. Improve yourself: sharpen the qualification signals "
            "that correctly flagged call-worthy sellers, demote ones that caused false "
            "'call now', add patterns you notice. KEEP the hard rules intact (never text "
            "the seller, no ARV/MAO/offers, no price unless the seller stated one, no "
            "contracts) and KEEP the exact JSON report contract. Output the FULL UPDATED "
            "playbook as clean markdown — ONLY the markdown."
        )
        user = ("CURRENT PLAYBOOK:\n" + current[:4000]
                + "\n\nRECENT REAL SCREENINGS (learn from these):\n" + "\n".join(lines))
        try:
            new_md = review_agent._claude(key, system, user, max_tokens=2400)
        except Exception as e:  # noqa: BLE001
            return {"error": f"claude: {e}"}
        if not new_md or len(new_md) < 200:
            return {"error": "learning produced nothing usable"}
        stamp = time.strftime("%Y-%m-%d %H:%M")
        header = (f"---\nagent: marcus\ntype: skill\nname: marcus-screening-playbook\n"
                  f"updated: {stamp}\nsource: self-improvement (from {len(lines)} screenings)\n---\n\n")
        try:
            import brain_io
            res = brain_io.write_note(PLAYBOOK_REL, header + new_md.strip(),
                                      reason=f"marcus self-improve {stamp}")
        except Exception as e:  # noqa: BLE001
            return {"error": f"brain write failed: {e}"}
        with self.lock:
            self.learn_state["lastLearnedAt"] = int(time.time() * 1000)
            self.learn_state["learnCount"] = self.learn_state.get("learnCount", 0) + 1
            self.learn_state["screenedSinceLearn"] = 0
            self._sk_mtime = None  # force reload of the freshly-written playbook
            self._log("learn", f"Self-improved screening playbook from {len(lines)} screenings "
                      f"({'auto' if auto else 'manual'})")
            self._save()
        try:
            import agent_bus
            agent_bus.send("marcus", "all", "status",
                           f"Marcus updated his screening playbook (self-improvement "
                           f"#{self.learn_state['learnCount']}, from {len(lines)} screenings).",
                           {"learnCount": self.learn_state["learnCount"]})
        except Exception:
            pass
        return {"ok": True, "learnCount": self.learn_state["learnCount"],
                "wrote": PLAYBOOK_REL, "fromScreenings": len(lines),
                "committed": (res or {}).get("committed"), "auto": auto}

    def status(self):
        return {
            "connected": True,
            "aiScreening": bool(_marcus_key()),
            "model": review_agent.MODEL,
            "autoScreen": AUTO_SCREEN,
            "total": len(self.screenings),
            "lastError": self.last_error,
            "activity": self.activity[:40],
            "learn": self.learn_state,
            "skillsLoaded": bool(self._load_skills()),
        }


def playbook_text(limit=2000):
    """Marcus's screening playbook (seed + brain) for chat grounding — read from disk."""
    try:
        import brain_io
        parts = []
        for p in (MARCUS_DIR / "skills" / "marcus-screening-playbook.md",
                  brain_io.VAULT / "Skills" / "marcus-screening-playbook.md",
                  MARCUS_DIR / "skills" / "marcus-critical-thinking.md",
                  MARCUS_DIR / "skills" / "marcus-seller-psychology.md",
                  MARCUS_DIR / "skills" / "marcus-nurture-followup.md"):
            if p.is_file():
                parts.append(p.read_text(errors="ignore"))
        return ("\n\n".join(parts))[:limit]
    except Exception:
        return ""
