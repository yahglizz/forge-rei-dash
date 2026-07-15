"""scout_triage.py — Scout, the wholesale lead-triage agent.

Reads every GoHighLevel seller conversation, scores how motivated / price-ready each
seller is, and ranks who to text back FIRST (speed to lead). Filters out dead weight
(people who said STOP or "not interested") so no time is wasted on them.

Scout NEVER texts a seller — Marcus owns all outbound (review-gated). Scout's only
GHL write is contact tags, and ONLY when the operator clicks "Apply tags" in the
dashboard (propose -> review -> execute). The 24/7 loop itself is read-only on GHL.

Runs inside the dashboard connector as a background thread (gated by FORGE_MARCUS, so
only the box runs it — no double-tagging from the Mac). No new database: triage state
persists to marcus_state/scout.json.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

import forge_atomic
import forge_heartbeat
import forge_ops
import marcus_engine
import review_agent
import test_mode

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "scout.json"
SCOUT_DIR = HERE.parent / "forge-scout"          # Scout's config + seed skills (outside web root)
_LOCK = threading.Lock()


def _load_env_file(p):
    """Fold forge-scout/config/scout.env into the environment (real env wins)."""
    try:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_env_file(SCOUT_DIR / "config" / "scout.env")


def _scout_key():
    """Scout's Anthropic key: its own (scout.env / SCOUT_ANTHROPIC_API_KEY) else the
    wholesale key. Mirrors agency_agents._agency_key resolution."""
    k = os.environ.get("SCOUT_ANTHROPIC_API_KEY")
    if k and not k.startswith("sk-ant-..."):
        return k
    for env_key in ("SCOUT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
        v = os.environ.get(env_key)
        if v and not v.startswith("sk-ant-..."):
            return v
    return review_agent._api_key()


def _north_star_loaded():
    """True when the cross-business constitution is actually on disk — console
    introspection only, mirrors _creed_block()-style helpers elsewhere."""
    try:
        import north_star
        return bool(north_star.context_block())
    except Exception:
        return False


POLL_INTERVAL = int(os.environ.get("FORGE_SCOUT_INTERVAL", "180"))   # seconds between sweeps
SCORE_BATCH = int(os.environ.get("FORGE_SCOUT_BATCH", "15"))          # max Claude-scored convos / pass
SCAN_PAGES = int(os.environ.get("FORGE_SCOUT_PAGES", "4"))            # conversation pages to sweep (~100 each)
MAX_RECORDS = 300                                                     # prune cap
LEARN_EVERY = int(os.environ.get("FORGE_SCOUT_LEARN_EVERY", "25"))    # auto self-improve after N new scorings
LEARN_MIN_INTERVAL_MS = int(os.environ.get("FORGE_SCOUT_LEARN_GAP_MIN", "45")) * 60 * 1000
PLAYBOOK_REL = "Skills/scout-playbook.md"                             # learned playbook in the Obsidian brain

# --- Missed-leads deep audit ----------------------------------------------
AUDIT_CANDIDATES = int(os.environ.get("FORGE_SCOUT_AUDIT_CANDIDATES", "30"))  # max threads deep-read per audit
AUDIT_THREAD_MSGS = int(os.environ.get("FORGE_SCOUT_AUDIT_MSGS", "15"))       # msgs pulled per thread
AUDIT_WINDOW_PAGES = int(os.environ.get("FORGE_SCOUT_AUDIT_PAGES", "8"))      # conversation pages to scan
WEEKLY_AUDIT_MS = 7 * 24 * 60 * 60 * 1000
WEEKLY_RETRY_MS = int(os.environ.get("FORGE_SCOUT_AUDIT_RETRY_MIN", "360")) * 60 * 1000  # 6h
AUDIT_REPORT_REL = "Reports"   # brain folder for the markdown report
MAX_AUDITS = 5                 # keep last N reports in scout.json

BUCKETS = ["asap", "warm", "nurture", "dead"]
BUCKET_LABEL = {"asap": "Text ASAP", "warm": "Warm", "nurture": "Nurture", "dead": "Dead"}

# Auto-tag HOT leads. Triage tags ("triage: asap", "motivated: high") are INTERNAL +
# reversible, so asap-bucket leads get their tags pushed to GHL the moment Scout flags
# them — no approval gate (matches the offer auto-tag the operator already authorized).
# Warm/nurture stay proposals (reviewed). Outward actions (SMS/pipeline/ads) stay gated.
# Flip off with FORGE_SCOUT_AUTOTAG_HOT=0.
AUTOTAG_HOT = os.environ.get("FORGE_SCOUT_AUTOTAG_HOT", "1").strip() not in ("0", "false", "no", "")
AUTOPIPE_HOT = os.environ.get("FORGE_SCOUT_AUTOPIPE_HOT", "1").strip() not in ("0", "false", "no", "")

# --- Offer detection + auto-tagging ---------------------------------------
# Yahjair has EXPLICITLY authorized Scout to auto-tag (no approval gate) contacts he's
# made a cash offer to, so the daily grind tracker can count offers. The tag is reversible
# (a remove button strips it). This is the ONE Scout write that skips propose->review.
OFFER_TAG = os.environ.get("FORGE_OFFER_TAG", "offer-made").strip().lower()
# Offer phrases — module-level tuple so it's easy to edit. An outbound message counts as a
# cash offer only if it ALSO carries a >=3-digit dollar amount (see detect_offer). This
# keeps "you said $200k, that's too high" (no offer intent) from being tagged.
OFFER_PHRASES = (
    "offer", "i can do", "i can pay", "we can pay", "able to do", "able to offer",
    "cash offer", "my offer", "come up to", "best i can", "i can give",
    "can offer you", "would offer", "pay you", "give you",
)
# A dollar amount with >=3 digits ($850, $8,500, $ 12000 ...). The {2,} after the lead
# digit guarantees at least three total digits.
_OFFER_AMOUNT_RE = re.compile(r"\$\s?\d[\d,]{2,}")

# Scout pushes leads into the wholesale GHL pipeline (review-gated, one click). Pick the
# pipeline whose name contains this; fall back to the first pipeline.
PIPELINE_PREF = os.environ.get("FORGE_SCOUT_PIPELINE", "wholesal").lower()
# Map a triage bucket / button to a pipeline STAGE name (matched case-insensitively).
STAGE_BY_BUCKET = {"asap": "Hot", "warm": "Warm", "nurture": "Responded"}
STAGE_ALIASES = {"hot": "Hot", "warm": "Warm", "follow-up": "Responded",
                 "followup": "Responded", "responded": "Responded",
                 "nurture": "Responded", "new": "New Lead"}
# Deal-lifecycle stage moves (operator-initiated on offer/contract send; signature-driven
# on close). Env-overridable so they match whatever the GHL pipeline is named.
DEAL_STAGE = {
    "offer": os.environ.get("FORGE_STAGE_OFFER", "Appointment Set"),
    "contract": os.environ.get("FORGE_STAGE_CONTRACT", "Under Contract"),
    "closed": os.environ.get("FORGE_STAGE_CLOSED", "Closed / Won"),
}


# --- helpers ---------------------------------------------------------------
def _price_band(amt):
    if not amt or amt <= 0:
        return ""
    if amt < 100_000:
        return "<100k"
    if amt < 250_000:
        return "100-250k"
    if amt < 500_000:
        return "250-500k"
    return "500k+"


def _motiv_label(score):
    s = score or 0
    if s >= 70:
        return "high"
    if s >= 40:
        return "med"
    return "low"


def _extract_price(text):
    """Best-effort asking-price extraction from a seller text. Returns int USD or None."""
    if not text:
        return None
    t = text.lower()
    best = None
    # 250k / 250 k / $250k
    for m in re.finditer(r"\$?\s*(\d{1,4})\s*k\b", t):
        try:
            best = max(best or 0, int(m.group(1)) * 1000)
        except ValueError:
            pass
    # $250,000 / $250000 / 250,000
    for m in re.finditer(r"\$\s*(\d{1,3}(?:,\d{3})+|\d{4,7})", t):
        try:
            best = max(best or 0, int(m.group(1).replace(",", "")))
        except ValueError:
            pass
    # bare comma-grouped number ("asking 250,000")
    for m in re.finditer(r"\b(\d{1,3}(?:,\d{3})+)\b", t):
        try:
            v = int(m.group(1).replace(",", ""))
            if v >= 10_000:
                best = max(best or 0, v)
        except ValueError:
            pass
    # bare integer ("i want 35000", "give me 8500", "60000 firm") — the most common
    # seller price reply. 4-7 digits; the 5k floor below drops house numbers/years.
    for m in re.finditer(r"\b(\d{4,7})\b", t):
        try:
            best = max(best or 0, int(m.group(1)))
        except ValueError:
            pass
    if best and 5_000 <= best <= 50_000_000:
        return best
    return None


def _parse_json(text):
    """Strip markdown fences and load JSON; tolerate trailing prose."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        # last resort: grab the outermost [...] or {...}
        for op, cl in (("[", "]"), ("{", "}")):
            i, j = s.find(op), s.rfind(cl)
            if i != -1 and j != -1 and j > i:
                try:
                    return json.loads(s[i:j + 1])
                except Exception:
                    pass
    return None


def _to_ms(v):
    """Normalize a GHL timestamp (epoch int/str OR ISO-8601 string) to epoch ms, or None.
    Conversation lastMessageDate is epoch-ms; message dateAdded is ISO-8601 — unify them."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


# Rule-based provisional score from Marcus's classifier (free, no Claude).
_RULE = {
    "READY":    ("ready", 75),
    "PRICE":    ("price", 70),
    "HELP":     ("warm", 50),
    "CONTINUE": ("warm", 45),
}

# Strong money/intent signals — a stated asking price or a clear "yes" is a HOT lead,
# even when the keyword classifier underrates it AND even when Claude is down. These are
# the two signals the operator cares about most, so they get a deterministic fast-path to
# asap (DNC + hard/soft-no are filtered BEFORE these, so a "no" with a number stays cold).
_AFFIRM_RE = re.compile(
    r"\b(?:yes|yeah|yep|yup|sure|absolutely|definitely|i'?m\s+interested|interested|"
    r"let'?s\s+talk|i\s+want\s+to\s+sell|want\s+to\s+sell|ready\s+to\s+sell|sounds\s+good|"
    r"it'?s\s+for\s+sale|its\s+for\s+sale|for\s+sell|its\s+for\s+sell)\b",
    re.IGNORECASE)


def _has_price_signal(body):
    """True if the seller stated a plausible asking price. Reuses _extract_price (the one
    price detector) so the rule fast-path and the priceBand tag never disagree."""
    return _extract_price(body) is not None


def _is_affirmative(body):
    """True if the seller said yes / it's for sale / wants to sell."""
    return bool(_AFFIRM_RE.search(body or ""))


def _reaction_score(kind):
    """Map an emoji/tapback reaction to our text into a triage bucket. A 👍 is a warm
    buy-signal worth a human follow-up — NOT auto-hot (it's a soft yes, not a stated price),
    so it surfaces as warm (auto-handed to Marcus) rather than firing the hot auto-tags."""
    if kind == "pos":
        return {"intent": "warm", "bucket": "warm", "motivation": 62,
                "reason": "reacted positively (👍) to our message — warm buy-signal",
                "scoreSource": "reaction"}
    if kind == "q":
        return {"intent": "warm", "bucket": "warm", "motivation": 50,
                "reason": "reacted with a question (❓) to our message — wants info",
                "scoreSource": "reaction"}
    return {"intent": "nurture", "bucket": "nurture", "motivation": 18,
            "reason": "reacted negatively (👎) to our message",
            "scoreSource": "reaction"}


class ScoutEngine:
    def __init__(self, ghl_get, ghl_post, location_id, ghl_put=None, ghl_delete=None):
        self.ghl_get = ghl_get
        self.ghl_post = ghl_post
        self.ghl_put = ghl_put
        self.ghl_delete = ghl_delete
        self.location_id = location_id
        self.lock = threading.RLock()  # reentrant: read methods (_active) lock too, and
        # some are called from inside a `with self.lock:` block (e.g. overview()).
        self.records = {}        # convId -> record
        self.dismissed = {}      # convId -> convKey it was dismissed at
        self.last_run = None
        self.last_error = None
        self.on_scored = None     # optional callback(rec) — fired for new call-worthy leads
                                  # (asap/warm) so Marcus auto-screens them. Set by connector.
        self.activity = []        # ring buffer of Scout actions (tag/pipeline/dismiss/learn)
        # Self-improvement state: Scout rewrites its own playbook from real encounters.
        self.learn_state = {"lastLearnedAt": None, "learnCount": 0, "scoredSinceLearn": 0}
        # Missed-leads deep-audit state (newest-first report cache + sweep bookkeeping).
        self.audits = []          # list of report dicts, newest-first, capped MAX_AUDITS
        self.audit_state = {"lastWeeklyAt": None, "lastRanAt": None, "running": False}
        self.offers = []          # offer-made events {contactId,name,at,day}, capped 500
        self._pl_cache = None     # (pipelineId, {stageNameLower: stageId}, pipelineName)
        self._sk_text = ""        # cached brain+seed skills text
        self._sk_mtime = None
        self._load()

    # -- persistence --------------------------------------------------------
    def _load(self):
        try:
            if STATE.exists():
                d = json.loads(STATE.read_text())
                if isinstance(d, dict):
                    self.records = d.get("records", {}) or {}
                    self.dismissed = d.get("dismissed", {}) or {}
                    self.activity = d.get("activity", []) or []
                    self.learn_state = d.get("learnState", self.learn_state) or self.learn_state
                    self.audits = d.get("audits", []) or []
                    self.offers = d.get("offers", []) or []
                    self.audit_state = d.get("auditState", self.audit_state) or self.audit_state
                    # Never resume a stuck "running" flag across a restart.
                    self.audit_state["running"] = False
                    self.last_run = d.get("lastRun")
        except Exception:
            self.records, self.dismissed, self.activity = {}, {}, []

    def _log(self, kind, text, conv_id=None):
        self.activity.insert(0, {"ts": int(time.time() * 1000), "kind": kind,
                                 "text": text, "convId": conv_id})
        self.activity = self.activity[:100]

    def _save(self):
        # prune oldest beyond MAX_RECORDS
        if len(self.records) > MAX_RECORDS:
            keep = sorted(self.records.values(),
                          key=lambda r: r.get("lastMessageDate") or 0, reverse=True)[:MAX_RECORDS]
            self.records = {r["convId"]: r for r in keep}
        tmp = {"records": self.records, "dismissed": self.dismissed,
               "activity": self.activity, "learnState": self.learn_state,
               "audits": self.audits, "auditState": self.audit_state,
               "offers": self.offers[-500:], "lastRun": self.last_run}
        forge_atomic.atomic_write_json(STATE, tmp)   # tmp + os.replace — never a partial scout.json

    # -- brain skills (actively learned from the Obsidian vault) -------------
    def _load_skills(self):
        """Scout's playbook = the forge-scout seed + the brain-learned vault version +
        closing plays. mtime-cached; reloads when any source changes (so a self-improve
        write or a manual vault edit is picked up on the next sweep)."""
        try:
            import brain_io
            parts, sig = [], []
            srcs = [SCOUT_DIR / "skills" / "scout-playbook.md",
                    brain_io.VAULT / "Skills" / "scout-playbook.md",
                    brain_io.VAULT / "Skills" / "closing-plays.md"]
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

    # -- scoring ------------------------------------------------------------
    def _rule_score(self, cls, body, needs_reply):
        """Deterministic provisional score (no Claude). Returns a partial record dict."""
        if cls == "DNC":
            return {"intent": "dead", "motivation": 0, "bucket": "dead",
                    "reason": "said stop / do not contact", "scoreSource": "rule"}
        # Explicit opt-out/harassment complaint that isn't literally "stop" ("remove my
        # number", "leave me alone") — DNC-grade, caught here so it never depends on
        # Claude being up. Checked before the generic wrong-number denial below.
        if marcus_engine._is_opt_out(body):
            return {"intent": "dead", "motivation": 0, "bucket": "dead",
                    "reason": "explicit opt-out / please stop contacting", "scoreSource": "rule"}
        # Wrong number / mistaken identity / "did I call you?" / "who is this" — not a
        # seller conversation. Dead bucket skips Claude AND auto-screen (never call-worthy).
        if marcus_engine._is_denial(body):
            return {"intent": "dead", "motivation": 0, "bucket": "dead",
                    "reason": "wrong number / not the seller — ignored", "scoreSource": "rule"}
        if cls == "NRN" or marcus_engine._is_soft_no(body):
            return {"intent": "nurture", "motivation": 20, "bucket": "nurture",
                    "reason": "not selling right now", "scoreSource": "rule"}
        # Deterministic HOT fast-path: a stated asking price or a clear "yes" is a hot lead
        # regardless of what the keyword classifier returns — and even when Claude is down.
        # (DNC + hard/soft-no already returned above, so a "no" with a number can't land here.)
        if _has_price_signal(body):
            return {"intent": "price", "motivation": 72,
                    "bucket": "asap" if needs_reply else "warm",
                    "reason": "stated an asking price", "scoreSource": "rule"}
        if _is_affirmative(body):
            return {"intent": "ready", "motivation": 75,
                    "bucket": "asap" if needs_reply else "warm",
                    "reason": "said yes / wants to sell", "scoreSource": "rule"}
        intent, motiv = _RULE.get(cls, ("nurture", 30))
        bucket = "nurture"
        if intent in ("ready", "price"):
            bucket = "asap" if needs_reply else "warm"
        elif intent == "warm":
            bucket = "warm"
        return {"intent": intent, "motivation": motiv, "bucket": bucket,
                "reason": "", "scoreSource": "rule"}

    def _claude_batch(self, key, items):
        """items: list of (idx, body). Returns {idx: {intent, motivation, askingPrice, reason}}."""
        if not items:
            return {}
        lines = []
        for i, body in items:
            snippet = (body or "").replace("\n", " ").strip()[:300]
            lines.append(f"{i}. \"{snippet}\"")
        system = (
            "You are Scout, a lead-triage analyst for a real estate WHOLESALING business. "
            "Each line is the most recent inbound TEXT from a property seller. Rate how "
            "motivated they are to sell soon and how urgently the operator should follow up. "
            "Return STRICT JSON ONLY — a list, one object per item, no prose:\n"
            '[{"i":0,"intent":"ready|price|warm|nurture|dead","motivation":0-100,'
            '"askingPrice":<number USD or null>,"reason":"<=12 words"}]\n'
            "intent: ready=wants to talk/sell, price=negotiating numbers, warm=engaged but "
            "early, nurture=maybe later, dead=not selling/stop. motivation: 0 (cold) to 100 "
            "(hot). askingPrice: only if they state a number, else null. Be terse."
        )
        # NORTH STAR first (the cross-business constitution), then the CREED
        # (wholesale evidence discipline) — neither truncated, neither reachable
        # by learn(), so self-improvement can never rewrite either.
        try:
            import north_star
            system += north_star.context_block()
        except Exception:
            pass
        try:
            import agent_creed
            system += agent_creed.block("wholesale")
        except Exception:
            pass
        skills = self._load_skills()
        if skills:
            system += ("\n\n=== YOUR PLAYBOOK (learned rubric from the brain — apply it) ===\n"
                       + skills[:3500])
        user = "Seller messages:\n" + "\n".join(lines)
        try:
            # Structured intent/motivation/price extraction — a classification task,
            # not a judgment call. Highest-volume Claude call in the system, so the
            # cheap tier here is where model tiering actually moves the bill.
            raw = review_agent._claude(key, system, user, max_tokens=1500,
                                       model=review_agent.HAIKU_MODEL)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"claude: {e}"
            return {}
        parsed = _parse_json(raw)
        out = {}
        if isinstance(parsed, list):
            for obj in parsed:
                if isinstance(obj, dict) and "i" in obj:
                    out[int(obj["i"])] = obj
        return out

    def _bucket_from_intent(self, intent, motivation, needs_reply):
        if intent == "dead":
            return "dead"
        if intent == "nurture":
            return "nurture"
        if intent in ("ready", "price") and (motivation or 0) >= 50:
            return "asap" if needs_reply else "warm"
        return "warm"

    def _proposed_tags(self, rec):
        tags = [f"triage: {rec['bucket']}"]
        if rec["bucket"] != "dead":
            tags.append(f"motivated: {_motiv_label(rec.get('motivation'))}")
        if rec.get("priceBand"):
            tags.append(f"ask: {rec['priceBand']}")
        return tags

    # -- the sweep ----------------------------------------------------------
    def _fetch_conversations(self):
        """Pull recent conversations, paging best-effort so seller replies aren't
        buried under newer outbound blasts. Stops when a page returns nothing new
        (so it degrades safely if the API ignores the paging cursor)."""
        convos, seen = [], set()
        start_after_date = None
        for _ in range(SCAN_PAGES):
            params = {"locationId": self.location_id, "limit": 100,
                      "sortBy": "last_message_date", "sort": "desc"}
            if start_after_date:
                params["startAfterDate"] = start_after_date
            data = self.ghl_get("/conversations/search", params)
            batch = data.get("conversations", []) or []
            fresh = [c for c in batch if c.get("id") not in seen]
            if not fresh:
                break
            for c in fresh:
                seen.add(c.get("id"))
            convos.extend(fresh)
            last_date = batch[-1].get("lastMessageDate")
            if not last_date or len(batch) < 100:
                break
            start_after_date = last_date
        return convos

    def reconcile_buckets(self):
        """Re-judge EXISTING records against the hard-no / our-message rules and demote
        false positives that were scored before those rules existed (or by Claude). Local
        only — no GHL writes. Idempotent; safe to run every sweep. Skips manual overrides."""
        moved = 0
        with self.lock:
            for r in self.records.values():
                if r.get("scoreSource") == "manual":
                    continue
                body = r.get("lastMessage") or ""
                if not marcus_engine._is_seller_message(body):
                    if r.get("bucket") != "dead":
                        r.update(intent="dead", bucket="dead", motivation=0,
                                 reason="our own outreach (not a seller)",
                                 scoreSource="reconcile")
                        moved += 1
                elif marcus_engine._is_opt_out(body):
                    if r.get("bucket") != "dead":
                        r.update(intent="dead", bucket="dead", motivation=0,
                                 reason="explicit opt-out / please stop contacting",
                                 scoreSource="reconcile")
                        moved += 1
                elif marcus_engine._is_denial(body):
                    if r.get("bucket") != "dead":
                        r.update(intent="dead", bucket="dead", motivation=0,
                                 reason="wrong number / not the seller — ignored",
                                 scoreSource="reconcile")
                        moved += 1
                elif marcus_engine._is_hard_no(body):
                    if r.get("bucket") in ("asap", "warm"):
                        r.update(intent="nurture", bucket="nurture", motivation=20,
                                 reason="said no / not interested",
                                 scoreSource="reconcile")
                        moved += 1
            if moved:
                self._save()
        return {"ok": True, "moved": moved}

    def poll_once(self):
        if forge_ops.paused():            # crew clocked out — stand down, don't sweep
            self.last_run = int(time.time() * 1000)   # idle on purpose, not wedged
            self.last_error = None
            return
        try:
            convos = self._fetch_conversations()
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            return
        self.reconcile_buckets()   # heal any false-positive hot/warm leads first
        self._autotag_hot()        # push triage tags for hot leads (runs every poll, incl. backlog)
        key = _scout_key()

        to_score = []      # convos needing a fresh score this pass
        for c in convos:
            cid = c.get("id")
            contact_id = c.get("contactId")
            if not cid or not contact_id:
                continue   # can't act on it without a contact
            # Speed-to-lead: only triage threads where the SELLER spoke last (they're
            # waiting on a reply). Outbound-last = our blast/follow-up, ball's in their
            # court — scoring our own words tells us nothing. Skip them.
            if c.get("lastMessageDirection") != "inbound":
                continue
            # Skip our OWN outreach mis-flagged as inbound — score sellers, not ourselves.
            # EXCEPT an emoji/tapback reaction to our text (e.g. '👍 to "..."'): it quotes our
            # words (so _is_our_message fires) but is a REAL seller buy-signal — keep + score it.
            _body0 = c.get("lastMessageBody")
            if not marcus_engine._is_seller_message(_body0):
                continue
            conv_key = f"{cid}:{c.get('lastMessageDate')}"
            if self.dismissed.get(cid) == conv_key:
                continue   # dismissed at this exact message; resurfaces on a new one
            existing = self.records.get(cid)
            if existing and existing.get("convKey") == conv_key:
                continue   # already scored this message
            to_score.append(c)

        if not to_score:
            self.last_run = int(time.time() * 1000)
            self.last_error = None
            return

        # Stage 1 (free): deterministic classify + price regex for everything.
        staged = []
        live_for_claude = []
        for c in to_score:
            body = c.get("lastMessageBody") or ""
            needs_reply = c.get("lastMessageDirection") == "inbound"
            react = marcus_engine._reaction_kind(body)
            if react:
                # Seller tapped a reaction on our text (👍/👎/❓). Deterministic — skip Claude.
                base = _reaction_score(react)
                price = _extract_price(body)
                staged.append((c, body, needs_reply, base, price, "REACT"))
                continue
            cls = marcus_engine.classify(body)
            if cls != "DNC" and (cls == "NRN" or marcus_engine._is_soft_no(body)
                                 or marcus_engine._is_hard_no(body)):
                cls = "NRN"   # a flat "No"/"not interested" is NOT a warm lead
            base = self._rule_score(cls, body, needs_reply)
            price = _extract_price(body)
            staged.append((c, body, needs_reply, base, price, cls))
            # Only live, nuanced leads go to Claude (skip dead/nurture — already filtered).
            if key and base["bucket"] not in ("dead", "nurture") and len(live_for_claude) < SCORE_BATCH:
                live_for_claude.append((len(staged) - 1, body))

        claude_out = self._claude_batch(key, live_for_claude) if live_for_claude else {}

        newly_asap = []  # recs that just transitioned into the "asap" bucket this sweep
        screenable = []  # new call-worthy recs (asap/warm) → auto-handed to Marcus to screen
        test_recs = []   # TEST MODE — whitelisted phones to auto-organize after the lock
        with self.lock:
            for idx, (c, body, needs_reply, base, price, cls) in enumerate(staged):
                rec = {
                    "convId": c.get("id"),
                    "contactId": c.get("contactId"),
                    "name": c.get("fullName") or c.get("contactName") or "(unknown)",
                    "phone": c.get("phone") or "",
                    "lastMessage": body,
                    "lastMessageDate": c.get("lastMessageDate"),
                    "convKey": f"{c.get('id')}:{c.get('lastMessageDate')}",
                    "needsReply": needs_reply,
                    "intent": base["intent"],
                    "motivation": base["motivation"],
                    "askingPrice": price,
                    "reason": base["reason"],
                    "bucket": base["bucket"],
                    "scoreSource": base["scoreSource"],
                    "tagsAppliedAt": None,
                    "scoredAt": int(time.time() * 1000),
                }
                ai = claude_out.get(idx)
                if ai:
                    rec["intent"] = ai.get("intent") or rec["intent"]
                    try:
                        rec["motivation"] = max(0, min(100, int(ai.get("motivation", rec["motivation"]))))
                    except (ValueError, TypeError):
                        pass
                    if ai.get("askingPrice"):
                        try:
                            rec["askingPrice"] = int(ai["askingPrice"])
                        except (ValueError, TypeError):
                            pass
                    if ai.get("reason"):
                        rec["reason"] = str(ai["reason"])[:120]
                    rec["bucket"] = self._bucket_from_intent(rec["intent"], rec["motivation"], needs_reply)
                    rec["scoreSource"] = "claude"
                rec["priceBand"] = _price_band(rec.get("askingPrice"))
                rec["proposedTags"] = self._proposed_tags(rec)
                # Detect transition INTO asap: fire only when this rec is asap and the
                # prior stored record for the conv was not asap (or didn't exist). Read
                # prev BEFORE overwriting so a lead only alerts once per hot transition.
                prev = self.records.get(rec["convId"])
                was_asap = bool(prev) and prev.get("bucket") == "asap"
                self.records[rec["convId"]] = rec
                if rec["bucket"] == "asap" and not was_asap:
                    newly_asap.append(rec)
                if rec["bucket"] in ("asap", "warm"):
                    screenable.append(rec)
                # TEST MODE — whitelisted phones get auto-organized after the lock (only
                # when test_mode is enabled AND the phone is whitelisted; real sellers skip).
                if test_mode.is_test(rec.get("phone")):
                    test_recs.append(rec)
            self.learn_state["scoredSinceLearn"] = self.learn_state.get("scoredSinceLearn", 0) + len(staged)
            self.last_run = int(time.time() * 1000)
            self.last_error = None
            self._save()

        # Broadcast newly-hot leads on the bus (best-effort, outside the lock so a slow
        # notifier can't stall the sweep). Only fires on the asap transition -> no spam.
        for rec in newly_asap:
            try:
                import agent_bus
                agent_bus.send("scout", "all", "alert",
                    f"🔥 Hot lead — {rec['name']} wants to talk. Text back now.",
                    {"type": "hot_lead", "convId": rec["convId"], "contactId": rec["contactId"],
                     "name": rec["name"], "phone": rec.get("phone"), "motivation": rec.get("motivation"),
                     "inbound": rec.get("lastMessage")})
            except Exception as e:  # noqa: BLE001
                self._log("error", f"Hot-lead alert failed for {rec.get('name')}: {e}",
                          rec.get("convId"))

        # Auto-hand each new call-worthy lead to Marcus to screen (hands-free pipeline).
        # asap first, capped per sweep so a big blast can't fire a burst of model calls.
        if self.on_scored and screenable:
            screenable.sort(key=lambda r: 0 if r.get("bucket") == "asap" else 1)
            for rec in screenable[:10]:
                try:
                    self.on_scored(rec)
                except Exception as e:  # noqa: BLE001
                    # A dropped handoff means a call-worthy lead never gets
                    # screened — surface it instead of swallowing silently.
                    self.last_error = f"Handoff to Marcus failed for {rec.get('name')}: {e}"
                    self._log("error", self.last_error, rec.get("convId"))

        # TEST MODE — scoped autopilot. For whitelisted test phones ONLY, auto-apply
        # tags and auto-push/move the pipeline to the bucket's stage. Real (non-test)
        # sellers are never here (test_recs is gated by test_mode.is_test). Each rec is
        # wrapped in try/except so one failure never breaks the sweep. apply_tags +
        # add_to_pipeline take the lock themselves, so call them OUTSIDE the lock.
        for rec in test_recs:
            try:
                if not rec.get("tagsAppliedAt"):
                    self.apply_tags(rec["convId"])
                target = STAGE_BY_BUCKET.get(rec.get("bucket"))
                if target and rec.get("pipelineStage") != target and rec.get("bucket") != "dead":
                    self.add_to_pipeline(rec["convId"], stage=target)
                self._log("autopilot",
                          f"TEST MODE — organized {rec.get('name')} → {rec.get('bucket')}",
                          rec["convId"])
            except Exception:
                pass

        # Self-improvement: after enough fresh encounters, Scout rewrites its own
        # playbook from what it just saw (rate-limited so it can't run too often).
        self._maybe_learn(key)

    def _maybe_learn(self, key):
        now = int(time.time() * 1000)
        st = self.learn_state
        last = st.get("lastLearnedAt") or 0
        if (key and st.get("scoredSinceLearn", 0) >= LEARN_EVERY
                and (now - last) >= LEARN_MIN_INTERVAL_MS):
            try:
                self.learn(auto=True)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"learn: {e}"

    # -- public API ---------------------------------------------------------
    def _slim(self, r):
        return {
            "id": r.get("convId"),
            "contactId": r.get("contactId"),
            "name": r.get("name"),
            "phone": r.get("phone"),
            "lastMessage": r.get("lastMessage"),
            "lastMessageDate": r.get("lastMessageDate"),
            "bucket": r.get("bucket"),
            "intent": r.get("intent"),
            "motivation": r.get("motivation"),
            "askingPrice": r.get("askingPrice"),
            "priceBand": r.get("priceBand") or "",
            "reason": r.get("reason") or "",
            "needsReply": r.get("needsReply", False),
            "proposedTags": r.get("proposedTags") or [],
            "tagsAppliedAt": r.get("tagsAppliedAt"),
            "pipelineStage": r.get("pipelineStage"),
            "pipelineSyncedAt": r.get("pipelineSyncedAt"),
            "scoreSource": r.get("scoreSource"),
        }

    def backfill(self, screener, limit=80):
        """Rebuild triage records for threads the normal sweep can no longer see.

        poll_once only scores conversations where the SELLER spoke last. Once we reply, the
        thread goes outbound-last and is skipped forever — so if the records store is ever
        lost, those leads never come back on their own. This re-scores them off their LAST
        INBOUND seller message (the same thing poll_once would have scored), seeded from
        Marcus's screening store. Read-only on GHL; scores with the same rule+Claude path.
        """
        seeds = list((getattr(screener, "screenings", {}) or {}).values())
        key = _scout_key()
        staged, live_for_claude, skipped = [], [], 0
        for s in seeds:
            conv_id, contact_id = s.get("convId"), s.get("contactId")
            if not conv_id or not contact_id or conv_id in self.records:
                skipped += 1
                continue
            if self.dismissed.get(conv_id):
                skipped += 1
                continue
            try:
                msgs = self._thread_transcript(conv_id) or []
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            inbound = [m for m in msgs
                       if m.get("direction") == "inbound" and (m.get("body") or "").strip()
                       and marcus_engine._is_seller_message(m.get("body"))]
            if not inbound:
                skipped += 1
                continue
            last = inbound[-1]
            body = (last.get("body") or "").strip()
            c = {"id": conv_id, "contactId": contact_id,
                 "fullName": s.get("name"), "phone": s.get("phone") or "",
                 "lastMessageBody": body,
                 "lastMessageDate": last.get("dateAdded") or s.get("updatedAt")
                 or s.get("createdAt") or int(time.time() * 1000),
                 "lastMessageDirection": "inbound"}
            cls = marcus_engine.classify(body)
            if cls != "DNC" and (cls == "NRN" or marcus_engine._is_soft_no(body)
                                 or marcus_engine._is_hard_no(body)):
                cls = "NRN"
            base = self._rule_score(cls, body, True)
            staged.append((c, body, base, _extract_price(body)))
            if key and base["bucket"] not in ("dead", "nurture") and len(live_for_claude) < SCORE_BATCH:
                live_for_claude.append((len(staged) - 1, body))
            if len(staged) >= limit:
                break

        claude_out = self._claude_batch(key, live_for_claude) if live_for_claude else {}
        restored = []
        with self.lock:
            for idx, (c, body, base, price) in enumerate(staged):
                rec = {
                    "convId": c["id"], "contactId": c["contactId"],
                    "name": c.get("fullName") or "(unknown)", "phone": c.get("phone") or "",
                    "lastMessage": body, "lastMessageDate": c.get("lastMessageDate"),
                    "convKey": f"{c['id']}:{c.get('lastMessageDate')}",
                    "needsReply": True,
                    "intent": base["intent"], "motivation": base["motivation"],
                    "askingPrice": price, "reason": base["reason"],
                    "bucket": base["bucket"], "scoreSource": base["scoreSource"],
                    "tagsAppliedAt": None, "scoredAt": int(time.time() * 1000),
                }
                ai = claude_out.get(idx)
                if ai:
                    rec["intent"] = ai.get("intent") or rec["intent"]
                    try:
                        rec["motivation"] = max(0, min(100, int(ai.get("motivation", rec["motivation"]))))
                    except (ValueError, TypeError):
                        pass
                    if ai.get("askingPrice"):
                        try:
                            rec["askingPrice"] = int(ai["askingPrice"])
                        except (ValueError, TypeError):
                            pass
                    if ai.get("reason"):
                        rec["reason"] = str(ai["reason"])[:120]
                    rec["bucket"] = self._bucket_from_intent(rec["intent"], rec["motivation"], True)
                    rec["scoreSource"] = "claude"
                rec["priceBand"] = _price_band(rec.get("askingPrice"))
                rec["proposedTags"] = self._proposed_tags(rec)
                self.records[rec["convId"]] = rec
                restored.append(rec)
            self._log("backfill", f"Rebuilt {len(restored)} triage records from screened threads")
            self._save()
        buckets = {}
        for r in restored:
            buckets[r["bucket"]] = buckets.get(r["bucket"], 0) + 1
        return {"ok": True, "restored": len(restored), "skipped": skipped,
                "buckets": buckets, "total": len(self.records)}

    def _active(self):
        # Snapshot under the (reentrant) lock so a concurrent poll-loop mutation can't
        # raise "dict changed size during iteration" on a dashboard refresh.
        with self.lock:
            snap = list(self.records.values())
            dismissed = dict(self.dismissed)
        return [r for r in snap
                if dismissed.get(r.get("convId")) != r.get("convKey")]

    def summary(self):
        counts = {b: 0 for b in BUCKETS}
        for r in self._active():
            b = r.get("bucket")
            if b in counts:
                counts[b] += 1
        return {
            "connected": True,
            "aiScoring": bool(_scout_key()),
            "model": review_agent.MODEL,
            "lastRun": self.last_run,
            "lastError": self.last_error,
            "total": len(self._active()),
            "counts": counts,
            "labels": BUCKET_LABEL,
            "learn": self.learn_state,
            "skillsLoaded": bool(self._load_skills()),
            "northStarLoaded": bool(_north_star_loaded()),
        }

    def leads(self, bucket=None):
        rows = self._active()
        if bucket and bucket in BUCKETS:
            rows = [r for r in rows if r.get("bucket") == bucket]
        else:
            rows = [r for r in rows if r.get("bucket") != "dead"]  # hide dead by default
        order = {"asap": 0, "warm": 1, "nurture": 2, "dead": 3}
        rows.sort(key=lambda r: (order.get(r.get("bucket"), 9),
                                 -(r.get("motivation") or 0),
                                 -(r.get("lastMessageDate") or 0)))
        return {"leads": [self._slim(r) for r in rows], "count": len(rows),
                "bucket": bucket or "all"}

    def overview(self):
        """Command Center view: counts + what Scout has organized + what awaits review."""
        active = self._active()
        order = {"asap": 0, "warm": 1, "nurture": 2, "dead": 3}
        def srt(rows):
            return sorted(rows, key=lambda r: (order.get(r.get("bucket"), 9),
                                               -(r.get("motivation") or 0)))
        pending = srt([r for r in active if r.get("bucket") in ("asap", "warm")
                       and not r.get("tagsAppliedAt")])
        tagged = sorted([r for r in active if r.get("tagsAppliedAt")],
                        key=lambda r: -(r.get("tagsAppliedAt") or 0))
        pipeline = sorted([r for r in active if r.get("pipelineStage")],
                          key=lambda r: -(r.get("pipelineSyncedAt") or 0))
        s = self.summary()
        return {
            "connected": True,
            "aiScoring": s["aiScoring"],
            "model": s["model"],
            "lastRun": self.last_run,
            "lastError": self.last_error,
            "counts": s["counts"],
            "taggedCount": len(tagged),
            "pipelineCount": len(pipeline),
            "pendingTags": [self._slim(r) for r in pending],
            "tagged": [self._slim(r) for r in tagged[:50]],
            "pipeline": [self._slim(r) for r in pipeline[:50]],
            "activity": self.activity[:40],
            "learn": self.learn_state,
            "skillsLoaded": bool(self._load_skills()),
            "northStarLoaded": bool(_north_star_loaded()),
        }

    # -- self-improvement (learn from every encounter, rewrite own playbook) --
    def learn(self, auto=False):
        """Claude reflects on Scout's recent real triage + current playbook, then
        rewrites Scout's playbook into the Obsidian brain (Skills/scout-playbook.md,
        git-committed). Next sweep reloads it — closed adaptive loop."""
        key = _scout_key()
        if not key:
            return {"error": "no anthropic key"}
        with self.lock:
            active = self._active()
        lines = []
        for b in ("asap", "warm", "nurture", "dead"):
            rows = sorted([r for r in active if r.get("bucket") == b],
                          key=lambda r: -(r.get("scoredAt") or 0))[:6]
            for r in rows:
                lines.append(f"[{b}] mot={r.get('motivation')} intent={r.get('intent')} "
                             f"reason={r.get('reason') or '-'} :: "
                             f"\"{(r.get('lastMessage') or '')[:140]}\"")
        if not lines:
            return {"error": "no encounters to learn from yet"}
        current = self._load_skills() or "(no playbook yet — create one)"
        system = (
            "You are Scout, a SELF-IMPROVING lead-triage analyst for a real estate "
            "WHOLESALING business. Below is your CURRENT playbook and a sample of how you "
            "actually scored real seller messages. Improve yourself: sharpen the signals "
            "that correctly flagged motivated sellers, demote signals that caused false "
            "hots, and add new patterns you notice in the real messages. Output the FULL "
            "UPDATED playbook as clean markdown — a practical rubric a triage agent "
            "follows (motivation 0-100 scoring, distress/urgency signals, buckets "
            "asap/warm/nurture/dead, price bands, next-best-action, pipeline mapping, "
            "hard rules: never text the seller, tags+pipeline human-approved). Keep it "
            "tight and actionable. Output ONLY the markdown."
        )
        user = ("CURRENT PLAYBOOK:\n" + current[:4000]
                + "\n\nRECENT REAL ENCOUNTERS (your own scores — learn from these):\n"
                + "\n".join(lines))
        try:
            import agent_coach
            user += agent_coach.insights_block("scout", "wholesale")
        except Exception:
            pass
        try:
            new_md = review_agent._claude(key, system, user, max_tokens=2200)
        except Exception as e:  # noqa: BLE001
            return {"error": f"claude: {e}"}
        if not new_md or len(new_md) < 200:
            return {"error": "learning produced nothing usable"}
        stamp = time.strftime("%Y-%m-%d %H:%M")
        header = (f"---\nagent: scout\nupdated: {stamp}\n"
                  f"source: self-improvement (learned from {len(lines)} recent encounters)\n---\n\n")
        try:
            import brain_io
            res = brain_io.write_note(PLAYBOOK_REL, header + new_md.strip(),
                                      reason=f"scout self-improve {stamp}")
        except Exception as e:  # noqa: BLE001
            return {"error": f"brain write failed: {e}"}
        with self.lock:
            self.learn_state["lastLearnedAt"] = int(time.time() * 1000)
            self.learn_state["learnCount"] = self.learn_state.get("learnCount", 0) + 1
            self.learn_state["scoredSinceLearn"] = 0
            self._sk_mtime = None  # force reload of the freshly-written playbook
            self._log("learn", f"Self-improved playbook from {len(lines)} encounters "
                      f"({'auto' if auto else 'manual'})")
            self._save()
        try:
            import agent_bus
            agent_bus.send("scout", "all", "status",
                           f"Scout updated its triage playbook (self-improvement "
                           f"#{self.learn_state['learnCount']}, from {len(lines)} encounters).",
                           {"learnCount": self.learn_state["learnCount"]})
        except Exception:
            pass
        return {"ok": True, "learnCount": self.learn_state["learnCount"],
                "wrote": PLAYBOOK_REL, "fromEncounters": len(lines),
                "committed": (res or {}).get("committed"), "auto": auto}

    # -- missed-leads deep audit (read-only sweep) --------------------------
    def _fetch_conversations_since(self, cutoff_ms, max_pages=AUDIT_WINDOW_PAGES):
        """Page conversations newest-first, stopping once the page's oldest
        lastMessageDate drops below cutoff_ms (or pages run out). Same paging
        shape as _fetch_conversations (startAfterDate cursor + dedupe by id).
        Read-only on GHL. Returns the conversations newer than the cutoff."""
        convos, seen = [], set()
        start_after_date = None
        for _ in range(max(1, max_pages)):
            params = {"locationId": self.location_id, "limit": 100,
                      "sortBy": "last_message_date", "sort": "desc"}
            if start_after_date:
                params["startAfterDate"] = start_after_date
            data = self.ghl_get("/conversations/search", params)
            batch = data.get("conversations", []) or []
            fresh = [c for c in batch if c.get("id") not in seen]
            if not fresh:
                break
            for c in fresh:
                seen.add(c.get("id"))
                lmd = c.get("lastMessageDate")
                if (lmd or 0) >= (cutoff_ms or 0):
                    convos.append(c)
            last_date = batch[-1].get("lastMessageDate")
            # Stop once we've paged past the window or the API stops cursoring.
            if not last_date or (last_date or 0) < (cutoff_ms or 0) or len(batch) < 100:
                break
            start_after_date = last_date
        return convos

    def _thread_transcript(self, conv_id, limit=AUDIT_THREAD_MSGS):
        """GET /conversations/{conv_id}/messages?limit=N (read-only). GHL returns
        newest-first; tolerate the messages / messages.messages nesting (see
        connector.api_messages). Return list of {direction, body, date} oldest-first."""
        if not conv_id:
            return []
        try:
            data = self.ghl_get(f"/conversations/{conv_id}/messages", {"limit": limit})
        except Exception as e:  # noqa: BLE001
            self.last_error = f"transcript: {e}"
            return []
        raw = data.get("messages", data) if isinstance(data, dict) else data
        if isinstance(raw, dict):
            raw = raw.get("messages", [])
        msgs = [
            {
                "direction": m.get("direction"),
                "body": m.get("body") or "",
                "date": _to_ms(m.get("dateAdded") or m.get("date")),
            }
            for m in (raw or [])
        ]
        msgs.reverse()  # GHL newest-first -> oldest-first like a chat
        return msgs

    def _audit_default(self):
        """Empty default report (also the shape audit_report falls back to)."""
        return {"ok": True, "ranAt": None, "days": 7, "query": None,
                "scanned": 0, "candidates": 0,
                "running": bool(self.audit_state.get("running")),
                "lastWeeklyAt": self.audit_state.get("lastWeeklyAt"),
                "found": [], "summary": "No sweep run yet."}

    def retro_audit(self, days=7, query=None, auto=False):
        """Deep-audit the last `days` of conversations for MISSED leads. Synchronous.
        Read-only on GHL (only /conversations/search + /conversations/{id}/messages
        GETs). Returns the report dict (REPORT shape)."""
        with self.lock:
            if self.audit_state.get("running"):
                # Already sweeping — don't launch a second fan-out of GHL+Claude calls.
                latest = dict(self.audits[0]) if self.audits else self._audit_default()
                latest["running"] = True
                latest["summary"] = "A sweep is already running — showing the last result."
                return latest
            self.audit_state["running"] = True   # in-memory single-flight (no save here)
        now = int(time.time() * 1000)
        day_ms = 86400_000
        try:
            # Persist running=True INSIDE the try so a _save() failure can't strand the
            # flag — the finally below always resets it (and _load() resets on restart).
            with self.lock:
                self._save()
            days = max(1, min(60, int(days or 7)))
            cutoff = now - days * day_ms
            fetch_ok = True
            try:
                convos = self._fetch_conversations_since(cutoff)
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
                convos = []
                fetch_ok = False
            scanned = len(convos)

            # --- Build candidate list (no GHL writes) ------------------------
            inbound_c, outbound_c = [], []   # split so soft-nos can't eat the whole budget
            for c in convos:
                cid = c.get("id")
                contact_id = c.get("contactId")
                if not cid or not contact_id:
                    continue
                body = c.get("lastMessageBody") or ""
                # Skip dead / DNC ("said stop / not interested").
                if marcus_engine.classify(body) == "DNC":
                    continue
                last_dir = c.get("lastMessageDirection")
                inbound_last = (last_dir == "inbound"
                                and marcus_engine._is_seller_message(body))
                if inbound_last:
                    # Inbound-last that's an explicit soft-no isn't a MISSED lead — it's
                    # nurture. Don't let it consume a deep-read slot.
                    if marcus_engine._is_soft_no(body):
                        continue
                    inbound_c.append((c, True))
                else:
                    # Outbound-last (our follow-up went unanswered) — the classic
                    # cold-after-a-reply case. Keep for the deep read to decide.
                    outbound_c.append((c, False))
            inbound_c.sort(key=lambda t: -(t[0].get("lastMessageDate") or 0))
            outbound_c.sort(key=lambda t: -(t[0].get("lastMessageDate") or 0))
            # Reserve ~1/3 of the budget for cold-after-reply (outbound-last) leads so a
            # wave of fresh inbound replies can't crowd them out, then backfill.
            out_quota = max(1, AUDIT_CANDIDATES // 3)
            picked = outbound_c[:out_quota] + inbound_c
            picked = picked[:AUDIT_CANDIDATES]
            # Backfill any unused outbound budget with more inbound (and vice-versa).
            if len(picked) < AUDIT_CANDIDATES:
                extra = outbound_c[out_quota:]
                picked = (picked + extra)[:AUDIT_CANDIDATES]
            candidates = picked
            n_candidates = len(candidates)

            # --- Deep-read each candidate's transcript -----------------------
            enriched = []   # parallel to the prompt index
            for c, inbound_last in candidates:
                cid = c.get("id")
                msgs = self._thread_transcript(cid)
                # Last inbound (seller) message that is NOT our own outreach.
                last_seller_said, last_seller_date = "", None
                for m in reversed(msgs):
                    if (m.get("direction") == "inbound"
                            and marcus_engine._is_seller_message(m.get("body"))):
                        last_seller_said = (m.get("body") or "").strip()
                        last_seller_date = m.get("date")
                        break
                if not last_seller_date:
                    # Fall back to the conversation summary fields.
                    if inbound_last:
                        last_seller_said = (c.get("lastMessageBody") or "").strip()
                    last_seller_date = c.get("lastMessageDate")
                lsd = _to_ms(last_seller_date) or 0
                days_cold = round((now - lsd) / day_ms, 1) if lsd else 0
                # Compact labelled transcript (last ~12 msgs).
                tlines = []
                for m in msgs[-12:]:
                    who = ("SELLER" if m.get("direction") == "inbound"
                           and marcus_engine._is_seller_message(m.get("body")) else "US")
                    snippet = (m.get("body") or "").replace("\n", " ").strip()[:200]
                    if snippet:
                        tlines.append(f"{who}: {snippet}")
                if not tlines and last_seller_said:
                    tlines.append(f"SELLER: {last_seller_said[:200]}")
                enriched.append({
                    "id": cid,
                    "contactId": c.get("contactId"),
                    "name": c.get("fullName") or c.get("contactName") or "(unknown)",
                    "phone": c.get("phone") or "",
                    "transcript": "\n".join(tlines),
                    "lastSellerSaid": last_seller_said,
                    "lastSellerDate": lsd or None,
                    "daysCold": days_cold,
                    "inboundLast": inbound_last,
                })

            # --- Claude judgement in batches (~8 transcripts/call) -----------
            key = _scout_key()
            verdicts = {}   # idx -> {missed, score, signal, recommendedAction}
            if key and enriched:
                playbook = (self._load_skills() or "")[:2500]
                base_system = (
                    "You are Scout, a missed-lead analyst for a real estate WHOLESALING "
                    "business. You are reviewing past seller text threads to find MISSED "
                    "LEADS — sellers who showed a genuine selling/interest signal (a price, "
                    "'yes it's for sale', asked about our process, gave condition/timeline, "
                    "real engagement) but the ball was DROPPED: the last message is an "
                    "unanswered inbound from them, OR the thread went cold after a positive "
                    "signal. NOT a missed lead: people who said STOP / not interested, or "
                    "our-own-outreach with no real seller engagement. Be strict — only flag "
                    "real opportunities worth re-engaging. Return STRICT JSON ONLY, a list, "
                    "one object per item, no prose:\n"
                    '[{"i":0,"missed":true,"score":0-100,'
                    '"signal":"<=15 words why it is a missed lead",'
                    '"recommendedAction":"<=18 words next move"}]\n'
                    "score: 0 (no opportunity) to 100 (clear hot lead we dropped)."
                )
                if playbook:
                    base_system += ("\n\n=== YOUR PLAYBOOK (learned rubric — apply it) ===\n"
                                    + playbook)
                if query:
                    base_system += ("\n\nOperator is specifically looking for: "
                                    + str(query)[:300])
                for start in range(0, len(enriched), 8):
                    chunk = enriched[start:start + 8]
                    blocks = []
                    for j, e in enumerate(chunk):
                        idx = start + j
                        blocks.append(f"--- THREAD {idx} (cold {e['daysCold']}d) ---\n"
                                      + (e["transcript"] or "(no transcript)"))
                    user = "Threads to judge:\n\n" + "\n\n".join(blocks)
                    try:
                        raw = review_agent._claude(key, base_system, user, max_tokens=1500)
                    except Exception as ex:  # noqa: BLE001
                        self.last_error = f"claude: {ex}"
                        continue
                    parsed = _parse_json(raw)
                    if isinstance(parsed, list):
                        for obj in parsed:
                            if not isinstance(obj, dict) or "i" not in obj:
                                continue
                            try:
                                vi = int(obj["i"])
                            except (ValueError, TypeError):
                                continue
                            if 0 <= vi < len(enriched):   # ignore out-of-range indices
                                verdicts[vi] = obj

            # --- Build found rows --------------------------------------------
            found = []
            for idx, e in enumerate(enriched):
                v = verdicts.get(idx)
                if v is not None:
                    if not v.get("missed"):
                        continue
                    try:
                        score = max(0, min(100, int(v.get("score", 0))))
                    except (ValueError, TypeError):
                        score = 0
                    signal = str(v.get("signal") or "")[:120]
                    rec_action = str(v.get("recommendedAction") or "")[:160]
                else:
                    # Deterministic degrade (no Claude key or call failed): score from
                    # the seller's real words. Works for BOTH inbound-last (they replied,
                    # we never answered) AND outbound-last (our follow-up went cold) — so
                    # the reserved outbound quota isn't wasted when there's no key.
                    said = e["lastSellerSaid"] or ""
                    if not said:
                        continue   # no real seller signal to judge → not a missed lead
                    cls = marcus_engine.classify(said)
                    if cls == "DNC" or marcus_engine._is_soft_no(said):
                        continue
                    score = 35
                    if cls in ("READY", "PRICE"):
                        score = 70
                    elif cls in ("HELP", "CONTINUE"):
                        score = 50
                    if _extract_price(said):
                        score = min(100, score + 15)
                    if e["daysCold"] and e["daysCold"] >= 2:
                        score = min(100, score + 5)
                    if e["inboundLast"]:
                        signal = "Seller replied and we never answered" if score >= 50 \
                            else "Inbound seller went cold without a reply"
                    else:
                        signal = "Seller engaged then the thread went cold after our last text"
                    rec_action = "Text the seller back today to re-open the conversation."
                found.append({
                    "id": e["id"],
                    "contactId": e["contactId"],
                    "name": e["name"],
                    "phone": e["phone"],
                    "score": score,
                    "signal": signal,
                    "lastSellerSaid": (e["lastSellerSaid"] or "")[:280],
                    "lastSellerDate": e["lastSellerDate"],
                    "daysCold": e["daysCold"],
                    "recommendedAction": rec_action,
                    "auto": bool(auto),
                })
            found.sort(key=lambda r: (-(r.get("score") or 0), -(r.get("daysCold") or 0)))

            # --- Summary (deterministic; optional Claude one-liner) ----------
            if not fetch_ok:
                summary = ("Sweep couldn't reach GoHighLevel to read your threads — "
                           "no results this run. It will retry automatically.")
            elif not found:
                summary = (f"Swept the last {days} days ({scanned} threads) — "
                           "no missed leads worth re-engaging.")
            else:
                top = found[0]
                summary = (f"Found {len(found)} missed lead(s) worth re-engaging from "
                           f"{scanned} threads — top: {top['name']} (score {top['score']}).")

            report = {
                "ok": bool(fetch_ok),
                "ranAt": now,
                "days": days,
                "query": query,
                "scanned": scanned,
                "candidates": n_candidates,
                "running": False,  # this report represents a COMPLETED run
                "lastWeeklyAt": (now if (auto and fetch_ok)
                                 else self.audit_state.get("lastWeeklyAt")),
                "summary": summary,
                "found": found,
            }

            with self.lock:
                self.audits.insert(0, report)
                self.audits = self.audits[:MAX_AUDITS]
                self.audit_state["lastRanAt"] = now
                if auto:
                    self.audit_state["lastWeeklyAttemptAt"] = now
                    if fetch_ok:
                        self.audit_state["lastWeeklyAt"] = now
                self._log("audit",
                          f"Swept {days}d: {len(found)} missed lead(s) from {scanned} threads"
                          + (" (weekly auto)" if auto else "")
                          + ("" if fetch_ok else " — GHL fetch FAILED"))
                if fetch_ok:
                    self.last_error = None   # only clear on a real, successful read
                self._save()

            # --- Brain note (best-effort) ------------------------------------
            try:
                import brain_io
                rows_md = ["| Score | Name | Phone | Cold | Signal | Next move |",
                           "|------:|------|-------|-----:|--------|-----------|"]
                for r in found:
                    rows_md.append(
                        f"| {r['score']} | {r['name']} | {r['phone'] or '-'} | "
                        f"{r['daysCold']}d | {(r['signal'] or '-').replace('|', '/')} | "
                        f"{(r['recommendedAction'] or '-').replace('|', '/')} |")
                stamp = time.strftime("%Y-%m-%d")
                header = (f"---\nagent: scout\ntype: missed-leads-audit\ndate: {stamp}\n"
                          f"days: {days}\nscanned: {scanned}\nfound: {len(found)}\n---\n\n")
                content = (header + f"# Missed Leads — {stamp}\n\n{summary}\n\n"
                           + "\n".join(rows_md) + "\n")
                brain_io.write_note(f"{AUDIT_REPORT_REL}/missed-leads-{stamp}.md", content,
                                    reason=f"scout missed-leads sweep {stamp}")
            except Exception as e:  # noqa: BLE001
                self.last_error = f"brain write: {e}"

            # --- Bus alert (best-effort) -------------------------------------
            try:
                import agent_bus
                msg = (f"Weekly sweep: {len(found)} missed leads from {scanned} threads "
                       f"(last {days}d)." if auto
                       else f"Sweep done: {len(found)} missed leads from {scanned} threads "
                       f"(last {days}d).")
                agent_bus.send("scout", "all", "alert", msg,
                               {"type": "missed_sweep", "found": len(found), "days": days})
            except Exception:
                pass

            return report
        except Exception as e:  # noqa: BLE001
            self.last_error = f"audit: {e}"
            # Stamp the attempt clock for auto runs so a crash here triggers the bounded
            # WEEKLY_RETRY_MS backoff (not a retry every single poll).
            if auto:
                with self.lock:
                    self.audit_state["lastWeeklyAttemptAt"] = now
            return {"ok": False, "error": str(e), "ranAt": now, "days": days,
                    "query": query, "scanned": 0, "candidates": 0, "running": False,
                    "lastWeeklyAt": self.audit_state.get("lastWeeklyAt"),
                    "summary": f"Sweep failed: {e}", "found": []}
        finally:
            with self.lock:
                self.audit_state["running"] = False
                self._save()

    def audit_report(self):
        """Latest report dict (running + lastWeeklyAt always reflected at top level),
        or an empty default if no sweep has run yet."""
        with self.lock:
            latest = self.audits[0] if self.audits else None
            running = bool(self.audit_state.get("running"))
            last_weekly = self.audit_state.get("lastWeeklyAt")
        if not latest:
            d = self._audit_default()
            d["running"] = running
            d["lastWeeklyAt"] = last_weekly
            return d
        out = dict(latest)
        out["running"] = running
        out["lastWeeklyAt"] = last_weekly
        return out

    def _maybe_weekly_audit(self):
        """Run a weekly auto-sweep if due. Self-rate-limited, safe to call every loop.
        Success cadence ~weekly; on failure it retries after WEEKLY_RETRY_MS (not every
        poll, not a 7-day blackout). Runs even with no Anthropic key (deterministic
        degrade in retro_audit)."""
        try:
            if self.audit_state.get("running"):
                return
            now = int(time.time() * 1000)
            last_ok = self.audit_state.get("lastWeeklyAt") or 0
            last_try = self.audit_state.get("lastWeeklyAttemptAt") or 0
            if (now - last_ok) >= WEEKLY_AUDIT_MS and (now - last_try) >= WEEKLY_RETRY_MS:
                self.retro_audit(7, auto=True)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"weekly audit: {e}"

    def _autotag_hot(self):
        """Push triage tags to GHL for every asap (hot) lead not yet tagged — backlog
        included. Internal + reversible tags, so no approval gate (FORGE_SCOUT_AUTOTAG_HOT
        flips it off). Idempotent: apply_tags stamps tagsAppliedAt -> each lead tags once.
        apply_tags takes the lock itself, so snapshot records and call OUTSIDE the lock."""
        if not AUTOTAG_HOT:
            return
        for rec in list(self.records.values()):
            if rec.get("bucket") == "asap" and not rec.get("tagsAppliedAt") \
                    and rec.get("contactId") and rec.get("proposedTags"):
                try:
                    self.apply_tags(rec["convId"])
                except Exception as e:  # noqa: BLE001
                    self.last_error = f"Auto-tag failed for {rec.get('name')}: {e}"
                    self._log("error", self.last_error, rec.get("convId"))
            # Hot leads also auto-land in the pipeline's Hot stage (same rationale as
            # auto-tags: internal + reversible — the opportunity can be moved/marked Lost
            # with one click). FORGE_SCOUT_AUTOPIPE_HOT=0 reverts to the gated button.
            if AUTOPIPE_HOT and rec.get("bucket") == "asap" \
                    and not rec.get("pipelineSyncedAt") and rec.get("contactId"):
                try:
                    self.add_to_pipeline(rec["convId"], stage="hot")
                except Exception as e:  # noqa: BLE001
                    self.last_error = f"Auto-pipeline failed for {rec.get('name')}: {e}"
                    self._log("error", self.last_error, rec.get("convId"))

    def apply_tags(self, conv_id):
        with self.lock:
            r = self.records.get(conv_id)
            if not r:
                return {"error": "lead not found"}
            cid = r.get("contactId")
            tags = r.get("proposedTags") or []
            if not cid:
                return {"error": "no contact linked"}
            if not tags:
                return {"error": "no proposed tags"}
            try:
                self.ghl_post(f"/contacts/{cid}/tags", {"tags": tags})
            except Exception as e:  # noqa: BLE001
                return {"error": f"GHL tag failed: {e}"}
            r["tagsAppliedAt"] = int(time.time() * 1000)
            self._log("tag", f"Tagged {r.get('name')}: {', '.join(tags)}", conv_id)
            self._save()
            return {"ok": True, "applied": tags, "lead": self._slim(r)}

    def apply_contact_tags(self, contact_id, tags, name=None, conv_id=None):
        """Apply explicit operator-requested tags to one contact. Internal + reversible."""
        clean = [str(t).strip() for t in (tags or []) if str(t).strip()]
        if not contact_id:
            return {"error": "contactId required"}
        if not clean:
            return {"error": "no tags provided"}
        try:
            self.ghl_post(f"/contacts/{contact_id}/tags", {"tags": clean})
        except Exception as e:  # noqa: BLE001
            return {"error": f"GHL tag failed: {e}"}
        with self.lock:
            self._log("tag", f"Tagged {name or contact_id}: {', '.join(clean)}", conv_id)
            self._save()
        return {"ok": True, "applied": clean, "contactId": contact_id}

    def remove_contact_tags(self, contact_id, tags, name=None, conv_id=None):
        """Remove explicit operator-requested tags from one contact."""
        clean = [str(t).strip() for t in (tags or []) if str(t).strip()]
        if not contact_id:
            return {"error": "contactId required"}
        if not clean:
            return {"error": "no tags provided"}
        if not self.ghl_delete:
            return {"error": "GHL tag removal is not wired"}
        try:
            self.ghl_delete(f"/contacts/{contact_id}/tags", {"tags": clean})
        except Exception as e:  # noqa: BLE001
            return {"error": f"GHL tag remove failed: {e}"}
        with self.lock:
            self._log("tag", f"Removed tags from {name or contact_id}: {', '.join(clean)}", conv_id)
            self._save()
        return {"ok": True, "removed": clean, "contactId": contact_id}

    # -- offer detection + auto-tagging (operator-authorized, no approval gate) --
    def detect_offer(self, msgs, since_ms=0):
        """True if ANY message is an OUTBOUND cash offer. Pure (no lock, no I/O).
        msgs: list of {direction, body, date(ms)} like _thread_transcript returns.
        An offer = outbound + (since_ms<=0 OR date>=since_ms) + a >=3-digit dollar
        amount + at least one OFFER_PHRASES phrase (case-insensitive). Conservative on
        purpose: a bare amount or a bare phrase alone is NOT an offer."""
        for m in (msgs or []):
            if (m.get("direction") or "").lower() != "outbound":
                continue
            if since_ms and (m.get("date") or 0) < since_ms:
                continue
            body = (m.get("body") or "")
            if not _OFFER_AMOUNT_RE.search(body):
                continue
            low = body.lower()
            if any(p in low for p in OFFER_PHRASES):
                return True
        return False

    def scan_thread_offer(self, contact_id, name, msgs, since_ms=0):
        """If the thread contains an outbound cash offer, auto-tag the contact OFFER_TAG
        and record an offer event (deduped to one per contact per day). Failed GHL tags
        remain pending and retry on the next scan of that thread. Returns True only when
        a NEW offer event was recorded this call."""
        if not contact_id:
            return False
        if not self.detect_offer(msgs, since_ms):
            return False
        new_event = False
        with self.lock:
            today = time.strftime("%Y-%m-%d")
            event = next((ev for ev in self.offers
                          if ev.get("contactId") == contact_id and ev.get("day") == today),
                         None)
            if event and event.get("tagSynced"):
                return False
            if not event:
                event = {"contactId": contact_id, "name": name or "",
                         "at": int(time.time() * 1000), "day": today,
                         "tagSynced": False}
                self.offers.append(event)
                self.offers = self.offers[-500:]
                new_event = True
            # Reversible auto-tag (operator-authorized). Keep failures retryable.
            try:
                self.ghl_post(f"/contacts/{contact_id}/tags", {"tags": [OFFER_TAG]})
                event["tagSynced"] = True
                event["tagSyncedAt"] = int(time.time() * 1000)
                event.pop("tagError", None)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"offer tag: {e}"
                event["tagSynced"] = False
                event["tagError"] = str(e)[:300]
            if new_event:
                state = "tagged" if event.get("tagSynced") else "recorded; tag retry pending"
                self._log("offer", f"Offer {state} for {name or contact_id}", None)
            elif event.get("tagSynced"):
                self._log("offer", f"Retried offer tag for {name or contact_id}", None)
            self._save()
        if new_event:
            # Best-effort bus note (outside the lock so notifier latency cannot block state).
            try:
                import agent_bus
                suffix = (f"tagged '{OFFER_TAG}'" if event.get("tagSynced")
                          else "recorded; GHL tag will retry")
                agent_bus.send("scout", "all", "status",
                               f"💵 Offer made — {name or contact_id} {suffix}.",
                               {"type": "offer_made", "contactId": contact_id,
                                "name": name or "", "tagSynced": event.get("tagSynced")})
            except Exception:
                pass
        return new_event

    def offers_today(self):
        """Count of offer events recorded today (local day, same convention as the rest
        of the file). Drives the daily grind tracker's offer count."""
        today = time.strftime("%Y-%m-%d")
        return sum(1 for ev in self.offers if ev.get("day") == today)

    # -- pipeline push (review-gated GHL write) -----------------------------
    def _resolve_pipeline(self):
        if self._pl_cache:
            return self._pl_cache
        data = self.ghl_get("/opportunities/pipelines", {"locationId": self.location_id})
        pls = data.get("pipelines", []) or []
        if not pls:
            raise RuntimeError("no pipelines in GHL")
        pick = next((p for p in pls if PIPELINE_PREF in (p.get("name") or "").lower()), pls[0])
        stages = {(s.get("name") or "").lower(): s.get("id") for s in (pick.get("stages") or [])}
        self._pl_cache = (pick.get("id"), stages, pick.get("name"))
        return self._pl_cache

    def pipeline_info(self):
        try:
            pid, stages, pname = self._resolve_pipeline()
            return {"connected": True, "pipeline": pname, "stages": list(stages.keys())}
        except Exception as e:  # noqa: BLE001
            return {"connected": False, "error": str(e)}

    def add_to_pipeline(self, conv_id, stage=None):
        with self.lock:
            r = self.records.get(conv_id)
            if not r:
                return {"error": "lead not found"}
            cid = r.get("contactId")
            if not cid:
                return {"error": "no contact linked"}
            try:
                pid, stages, pname = self._resolve_pipeline()
            except Exception as e:  # noqa: BLE001
                return {"error": f"pipeline lookup failed: {e}"}
            target = (STAGE_ALIASES.get((stage or "").lower())
                      or stage
                      or STAGE_BY_BUCKET.get(r.get("bucket"), "Warm"))
            stage_id = stages.get((target or "").lower())
            if not stage_id:
                return {"error": f"stage '{target}' not in {pname}"}
            try:
                found = self.ghl_get("/opportunities/search",
                                     {"location_id": self.location_id, "contact_id": cid})
                opps = found.get("opportunities", []) or []
                if opps:
                    oid = opps[0].get("id")
                    self.ghl_put(f"/opportunities/{oid}",
                                 {"pipelineStageId": stage_id, "pipelineId": pid})
                    action = "moved"
                else:
                    self.ghl_post("/opportunities/", {
                        "pipelineId": pid, "locationId": self.location_id,
                        "pipelineStageId": stage_id, "name": r.get("name") or "Seller lead",
                        "status": "open", "contactId": cid,
                    })
                    action = "created"
            except Exception as e:  # noqa: BLE001
                return {"error": f"GHL pipeline write failed: {e}"}
            r["pipelineStage"] = target
            r["pipelineSyncedAt"] = int(time.time() * 1000)
            self._log("pipeline", f"{action.title()} {r.get('name')} → {target} in {pname}", conv_id)
            self._save()
            return {"ok": True, "action": action, "stage": target,
                    "pipeline": pname, "lead": self._slim(r)}

    def advance_opp(self, contact_id, kind, value=None, name=None):
        """Move a contact's GHL opportunity to the deal-lifecycle stage for `kind`
        (offer / contract / closed). Works by contactId (no Scout record needed), so the
        offer-send + contract-send + signature-close paths can all advance the pipeline.
        Operator-initiated (offer/contract) or signature-driven (closed) — NOT an autonomous
        agent move. `closed` also marks the opp won (+ optional monetaryValue=assignment fee)."""
        if not contact_id:
            return {"error": "contactId required"}
        target = DEAL_STAGE.get(kind)
        if not target:
            return {"error": f"unknown deal kind '{kind}'"}
        try:
            pid, stages, pname = self._resolve_pipeline()
        except Exception as e:  # noqa: BLE001
            return {"error": f"pipeline lookup failed: {e}"}
        stage_id = stages.get(target.lower())
        if not stage_id:
            return {"error": f"stage '{target}' not in {pname}"}
        payload = {"pipelineStageId": stage_id, "pipelineId": pid}
        if kind == "closed":
            payload["status"] = "won"
            if value is not None:
                try:
                    payload["monetaryValue"] = float(value)
                except (ValueError, TypeError):
                    pass
        try:
            found = self.ghl_get("/opportunities/search",
                                 {"location_id": self.location_id, "contact_id": contact_id})
            opps = found.get("opportunities", []) or []
            if opps:
                self.ghl_put(f"/opportunities/{opps[0].get('id')}", payload)
                action = "moved"
            else:
                try:
                    contact = (self.ghl_get(f"/contacts/{contact_id}") or {}).get(
                        "contact", {})
                except Exception:
                    return {"error": "GHL contact lookup failed: stale or invalid contactId"}
                if not contact or contact.get("id") != contact_id:
                    return {"error": "GHL contact lookup failed: stale or invalid contactId"}
                payload.update({"locationId": self.location_id, "contactId": contact_id,
                                "name": name or "Seller lead", "status": payload.get("status", "open")})
                self.ghl_post("/opportunities/", payload)
                action = "created"
        except Exception as e:  # noqa: BLE001
            return {"error": f"GHL pipeline write failed: {e}"}
        self._log("pipeline", f"{action.title()} opp ({kind}) → {target} in {pname}", None)
        return {"ok": True, "stage": target, "action": action, "kind": kind}

    def dismiss(self, conv_id):
        with self.lock:
            r = self.records.get(conv_id)
            if not r:
                return {"error": "lead not found"}
            self.dismissed[conv_id] = r.get("convKey")
            self._log("dismiss", f"Dismissed {r.get('name')}", conv_id)
            self._save()
            return {"ok": True}

    def remove_lead(self, conv_id):
        """'Not actually hot.' Undo Scout's hot-lead writes on GHL: strip the tags
        Scout applied off the contact (leaving unrelated tags), mark its opportunity
        Lost (reversible — stays in GHL history), then drop it from triage. The user
        clicking Remove IS the approval (CLAUDE.md rule 2)."""
        with self.lock:
            r = self.records.get(conv_id)
            if not r:
                return {"error": "lead not found"}
            cid = r.get("contactId")
            tags = list(r.get("proposedTags") or [])
            removed_tags, opp_action, errors = [], None, []

            # 1) strip the Scout hot tags off the GHL contact (unrelated tags untouched)
            if cid and tags and self.ghl_delete:
                try:
                    self.ghl_delete(f"/contacts/{cid}/tags", {"tags": tags})
                    removed_tags = tags
                except Exception as e:  # noqa: BLE001
                    errors.append(f"tag remove failed: {e}")

            # 2) mark its opportunity Lost (reversible, reopenable in GHL)
            if cid and self.ghl_put:
                try:
                    found = self.ghl_get("/opportunities/search",
                                         {"location_id": self.location_id, "contact_id": cid})
                    opps = found.get("opportunities", []) or []
                    for o in opps:
                        oid = o.get("id")
                        if oid:
                            self.ghl_put(f"/opportunities/{oid}", {"status": "lost"})
                    opp_action = "lost" if opps else "none"
                except Exception as e:  # noqa: BLE001
                    errors.append(f"opportunity update failed: {e}")

            # 3) drop from triage locally + clear the applied markers
            self.dismissed[conv_id] = r.get("convKey")
            r["tagsAppliedAt"] = None
            r["pipelineStage"] = None
            r["removedAt"] = int(time.time() * 1000)
            self._log("remove",
                      f"Removed {r.get('name')} (not hot): tags off "
                      f"({', '.join(removed_tags) or 'none'}), opp {opp_action or 'n/a'}",
                      conv_id)
            self._save()
            return {"ok": True, "removedTags": removed_tags,
                    "opportunity": opp_action, "errors": errors}

    def note_handoff(self, conv_id, to="marcus"):
        """Record that Scout handed a lead to another agent (the actual proposal is
        created by the connector via the target agent)."""
        with self.lock:
            r = self.records.get(conv_id)
            name = (r or {}).get("name", "lead")
            self._log("handoff", f"Handed {name} to {to.title()}", conv_id)
            self._save()
        return {"name": name, "contactId": (r or {}).get("contactId") if r else None}

    def context(self):
        """Grounding text for Scout's chat in the AI Agents tab."""
        s = self.summary()
        rows = self.leads("asap")["leads"][:10]
        lines = [f"Triage right now: {s['counts']['asap']} ASAP, {s['counts']['warm']} warm, "
                 f"{s['counts']['nurture']} nurture, {s['counts']['dead']} dead."]
        if rows:
            lines.append("Top sellers to text back FIRST:")
            for i, r in enumerate(rows, 1):
                price = f" | asks {r['priceBand']}" if r.get("priceBand") else ""
                lines.append(f"{i}. {r['name']} ({r['phone']}) — motivation {r['motivation']}"
                             f"{price} — {r['reason'] or r['intent']} — last: \"{(r['lastMessage'] or '')[:80]}\"")
        else:
            lines.append("No hot leads in the ASAP bucket right now.")
        return "\n".join(lines)

    def run_once(self):
        self.poll_once()
        return self.summary()

    # -- module-level read (for chat grounding without the live instance) ----
    @staticmethod
    def context_from_disk():
        return context_from_disk()

    def run_forever(self):
        fails = 0          # consecutive sweeps that couldn't reach GHL
        alerted = False    # fire the down-alert once per outage, re-arm on recovery
        while True:
            prev_run = self.last_run
            try:
                self.poll_once()
                self._maybe_weekly_audit()
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
            # Dead-man's-switch: last_run advances on every healthy sweep (incl. the
            # no-new-leads path). If it didn't move, the sweep failed to even fetch from
            # GHL — after 3 in a row, ping the operator via the bus (-> Telegram) once.
            if self.last_run == prev_run:
                fails += 1
                if fails >= 3 and not alerted:
                    try:
                        import agent_bus
                        agent_bus.send("scout", "all", "alert",
                            f"⚠️ Scout is down — {fails} sweeps in a row couldn't reach "
                            f"GoHighLevel. Last error: {self.last_error or 'unknown'}.",
                            {"type": "agent_down", "agent": "scout", "fails": fails,
                             "lastError": self.last_error})
                        alerted = True
                    except Exception:
                        pass
            else:
                fails = 0
                alerted = False
            forge_heartbeat.beat("scout", POLL_INTERVAL, "Scout triage",
                                 error=self.last_error)
            time.sleep(POLL_INTERVAL)


def playbook_text(limit=2000):
    """Scout's learned playbook (seed + brain) for chat grounding — read from disk."""
    try:
        import brain_io
        parts = []
        for p in (SCOUT_DIR / "skills" / "scout-playbook.md",
                  brain_io.VAULT / "Skills" / "scout-playbook.md"):
            if p.is_file():
                parts.append(p.read_text(errors="ignore"))
        return ("\n\n".join(parts))[:limit]
    except Exception:
        return ""


def context_from_disk():
    """Build Scout's chat-grounding text straight from marcus_state/scout.json.

    Lets agents_chat answer "who do I text first?" from live triage data without
    holding a reference to the connector's ScoutEngine instance.
    """
    try:
        d = json.loads(STATE.read_text()) if STATE.exists() else {}
    except Exception:
        d = {}
    records = (d.get("records") or {})
    dismissed = (d.get("dismissed") or {})
    active = [r for r in records.values() if dismissed.get(r.get("convId")) != r.get("convKey")]
    counts = {b: 0 for b in BUCKETS}
    for r in active:
        if r.get("bucket") in counts:
            counts[r["bucket"]] += 1
    asap = sorted([r for r in active if r.get("bucket") == "asap"],
                  key=lambda r: (-(r.get("motivation") or 0), -(r.get("lastMessageDate") or 0)))[:10]
    lines = [f"Triage right now: {counts['asap']} ASAP, {counts['warm']} warm, "
             f"{counts['nurture']} nurture, {counts['dead']} dead."]
    if asap:
        lines.append("Top sellers to text back FIRST:")
        for i, r in enumerate(asap, 1):
            band = f" | asks {r.get('priceBand')}" if r.get("priceBand") else ""
            lines.append(f"{i}. {r.get('name')} ({r.get('phone')}) — motivation "
                         f"{r.get('motivation')}{band} — {r.get('reason') or r.get('intent')} — "
                         f"last: \"{(r.get('lastMessage') or '')[:80]}\"")
    else:
        lines.append("No hot leads in the ASAP bucket right now.")
    return "\n".join(lines)


def audit_from_disk():
    """Read the latest missed-leads report from marcus_state/scout.json.

    Lets agents_chat ground a "did I miss anyone?" answer without holding a
    reference to the live ScoutEngine. Returns {ranAt, days, query, scanned,
    found:[rows]} or an empty default.
    """
    empty = {"ranAt": None, "days": 7, "query": None, "scanned": 0, "found": []}
    try:
        d = json.loads(STATE.read_text()) if STATE.exists() else {}
    except Exception:
        return empty
    audits = d.get("audits") or []
    if not audits or not isinstance(audits, list):
        return empty
    latest = audits[0] if isinstance(audits[0], dict) else None
    if not latest:
        return empty
    return {
        "ranAt": latest.get("ranAt"),
        "days": latest.get("days", 7),
        "query": latest.get("query"),
        "scanned": latest.get("scanned", 0),
        "found": latest.get("found") or [],
    }
