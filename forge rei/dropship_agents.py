"""dropship_agents.py — Hawk, Blaze, Otto: the dropship specialist crew.

Three self-improving specialists under Midas (dropship_director.py), sharing one file
the way agency_agents.py holds Dyson + Eco:

  • Hawk  — product research. Scores ideas (from the local watchlist or a pasted list)
            against margin headroom, demand signal, ad-ability, fulfillment sanity.
  • Blaze — creative & ads. Reads Meta performance (agency Meta engine via a dropship
            env-swap) and drafts new ad concepts. Never spends.
  • Otto  — fulfillment & support. Reads Shopify for fulfillment risks (unshipped,
            stockouts, tracking gaps) and drafts customer replies. Never sends.

Each follows the FORGE self-improving-agent pattern: key fallback, creed injected via
agent_creed (never rewritten), the business brief read FIRST (dropship_context), a
learned playbook in the vault it rewrites via learn() (folding in agent_coach peer
insights), state in marcus_state/<agent>.json. Propose-only — every outward action
stays the operator's one-tap approval (rule 2).
"""
import contextlib
import json
import os
import threading
import time
from pathlib import Path

import forge_atomic
import review_agent

HERE = Path(__file__).resolve().parent
DROPSHIP_DIR = HERE.parent / "forge-dropship"


def _dropship_key():
    """Shared crew key: DROPSHIP_ANTHROPIC_API_KEY → shared env → agency → wholesale."""
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


def _context_block():
    try:
        import dropship_context
        return dropship_context.context_block()
    except Exception:
        return ""


def _strip_fences(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


class _Specialist:
    """Base class for a propose-only, self-improving dropship specialist."""

    AGENT = ""          # bus id, e.g. "hawk"
    NAME = ""           # display, e.g. "Hawk"
    TITLE = ""          # e.g. "Product Research"
    PLAYBOOK_MD = ""    # e.g. "hawk-playbook.md"
    ROLE_PROMPT = ""    # short system-prompt persona line
    LEARN_EVERY = 6

    def __init__(self):
        self.lock = threading.RLock()
        self.activity = []
        self.last_error = None
        self.last_result = None
        self.run_count = 0
        self.learn_state = {"lastLearnedAt": None, "learnCount": 0, "runsSinceLearn": 0}
        self._state = HERE / "marcus_state" / f"{self.AGENT}.json"
        self._load()

    # --- persistence ---------------------------------------------------------
    def _load(self):
        try:
            if self._state.exists():
                d = json.loads(self._state.read_text())
                self.activity = d.get("activity", []) or []
                self.last_result = d.get("lastResult")
                self.run_count = d.get("runCount", 0) or 0
                self.learn_state = d.get("learnState", self.learn_state) or self.learn_state
        except Exception:
            pass

    def _save(self):
        try:
            self._state.parent.mkdir(parents=True, exist_ok=True)
            forge_atomic.atomic_write_json(self._state, {
                "activity": self.activity[-100:],
                "lastResult": self.last_result,
                "runCount": self.run_count,
                "learnState": self.learn_state,
            })
        except Exception:
            pass

    def _log(self, kind, text):
        self.activity.append({"ts": int(time.time() * 1000), "kind": kind, "text": text})
        self.activity = self.activity[-100:]

    # --- playbook (learned rubric; seed + vault, vault wins) -----------------
    @property
    def playbook_rel(self):
        return f"Skills/{self.PLAYBOOK_MD}"

    def _playbook(self):
        parts = []
        try:
            import brain_io
            for p in (DROPSHIP_DIR / "skills" / self.PLAYBOOK_MD,
                      brain_io.VAULT / "Skills" / self.PLAYBOOK_MD):
                if p.is_file():
                    parts.append(p.read_text(errors="ignore"))
        except Exception:
            pass
        return "\n\n".join(parts)

    def _system_prompt(self, extra=""):
        pb = self._playbook()
        return (
            self.ROLE_PROMPT
            + _north_star_block()
            + _context_block()
            + _creed_block()
            + ("\n\n=== YOUR PLAYBOOK (learned rubric) ===\n" + pb[:4000] if pb else "")
            + (extra or "")
        )

    # --- the core Claude call ------------------------------------------------
    def analyze(self, task, data=None, max_tokens=1800):
        """Run the specialist against a task + optional grounded data. Returns parsed
        JSON when the model complies, else {"raw": <text>}. Read-only, proposes only."""
        key = _dropship_key()
        if not key:
            return {"ok": False, "error": "no anthropic key"}
        system = self._system_prompt()
        user = str(task or "").strip()
        if data is not None:
            user += ("\n\nGROUNDED DATA (use these — do not invent numbers; label mock/"
                     "unconnected channels as mock):\n" + json.dumps(data, indent=2, default=str))
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
            self.run_count += 1
            self.learn_state["runsSinceLearn"] = self.learn_state.get("runsSinceLearn", 0) + 1
            self.last_result = parsed
            self._log("run", (parsed.get("headline") if isinstance(parsed, dict) else "") or "analysis")
            self._save()
        self._broadcast(parsed)
        self._maybe_learn(key)
        return {"ok": True, "result": parsed}

    def _broadcast(self, parsed):
        try:
            import agent_bus
            head = (parsed.get("headline") if isinstance(parsed, dict) else "") or f"{self.NAME} ran an analysis"
            agent_bus.send(self.AGENT, "midas", "note", f"{self.NAME}: {head}",
                           {"runCount": self.run_count})
        except Exception:
            pass

    # --- self-improvement ----------------------------------------------------
    def _maybe_learn(self, key):
        st = self.learn_state
        if key and st.get("runsSinceLearn", 0) >= self.LEARN_EVERY:
            try:
                self.learn(auto=True)
            except Exception as e:  # noqa: BLE001
                self.last_error = f"learn: {e}"

    def learn(self, auto=False):
        key = _dropship_key()
        if not key:
            return {"error": "no anthropic key"}
        with self.lock:
            recent = [a for a in self.activity if a.get("kind") == "run"][-8:]
        if not recent and not self.last_result:
            return {"error": "no runs to learn from yet"}
        current = self._playbook() or "(no playbook yet — create one)"
        sample = "\n".join(f"- {a.get('text','')}" for a in recent) or "(recent analysis)"
        system = (
            f"You are {self.NAME}, a SELF-IMPROVING dropship {self.TITLE.lower()} specialist. "
            "Below is your CURRENT playbook and a sample of your recent work. Improve "
            "yourself: sharpen your judgment, tighten what fits THIS store, cut guidance "
            "that didn't help. Keep the hard rules (read the business brief first; never act "
            "outward; never invent a metric/margin/status; ground everything; your JSON "
            "output contract). Your evidence-discipline creed is permanent, not shown here, "
            "and not yours to rewrite — assume it always applies. Output the FULL UPDATED "
            "playbook as clean markdown — ONLY the markdown."
        )
        user = ("CURRENT PLAYBOOK:\n" + current[:4000]
                + "\n\nRECENT WORK:\n" + sample)
        try:
            import agent_coach
            user += agent_coach.insights_block(self.AGENT, "dropship")
        except Exception:
            pass
        try:
            new_md = review_agent._claude(key, system, user, max_tokens=2200)
        except Exception as e:  # noqa: BLE001
            return {"error": f"claude: {e}"}
        if not new_md or len(new_md) < 150:
            return {"error": "learning produced nothing usable"}
        stamp = time.strftime("%Y-%m-%d %H:%M")
        header = (f"---\nagent: {self.AGENT}\nupdated: {stamp}\n"
                  f"source: self-improvement\n---\n\n")
        try:
            import brain_io
            res = brain_io.write_note(self.playbook_rel, header + new_md.strip(),
                                      reason=f"{self.AGENT} self-improve {stamp}")
        except Exception as e:  # noqa: BLE001
            return {"error": f"brain write failed: {e}"}
        with self.lock:
            self.learn_state["lastLearnedAt"] = int(time.time() * 1000)
            self.learn_state["learnCount"] = self.learn_state.get("learnCount", 0) + 1
            self.learn_state["runsSinceLearn"] = 0
            self._log("learn", f"Self-improved playbook ({'auto' if auto else 'manual'})")
            self._save()
        try:
            import agent_bus
            agent_bus.send(self.AGENT, "all", "status",
                           f"{self.NAME} sharpened his playbook (#{self.learn_state['learnCount']}).",
                           {"learnCount": self.learn_state["learnCount"]})
        except Exception:
            pass
        return {"ok": True, "learnCount": self.learn_state["learnCount"],
                "wrote": self.playbook_rel, "committed": res.get("committed"), "auto": auto}

    # --- console reads -------------------------------------------------------
    def status(self):
        key = _dropship_key()
        creed = False
        try:
            import agent_creed
            creed = agent_creed.loaded("dropship")
        except Exception:
            pass
        return {
            "ok": True, "agent": self.AGENT, "name": self.NAME, "title": self.TITLE,
            "aiReady": bool(key),
            "playbookLoaded": bool(self._playbook()),
            "creedLoaded": creed,
            "runCount": self.run_count,
            "learn": self.learn_state,
            "lastError": self.last_error,
        }

    def overview(self):
        return {"ok": True, **self.status(), "lastResult": self.last_result,
                "activity": list(reversed(self.activity[-30:]))}


# ---------------------------------------------------------------------------
# Hawk — product research
# ---------------------------------------------------------------------------
class HawkEngine(_Specialist):
    AGENT, NAME, TITLE = "hawk", "Hawk", "Product Research"
    PLAYBOOK_MD = "hawk-playbook.md"
    ROLE_PROMPT = (
        "You are Hawk, the product researcher for the FORGE Dropship store. You hunt for "
        "winning products and score ideas against margin headroom, demand signal, "
        "ad-ability, fulfillment sanity, and saturation. You report to Midas. You never "
        "source, order, list, or spend — you research and recommend; a human approves."
    )

    def research(self, payload=None):
        """Score product ideas. payload: {ideas: "free text or list", data: {...}}.
        If no ideas are given, pulls the local watchlist so there is always something to
        chew on."""
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
        task = ("Research + score these product ideas per your output contract.\n\nIDEAS:\n"
                + (ideas if isinstance(ideas, str) else json.dumps(ideas)))
        return self.analyze(task, data)


# ---------------------------------------------------------------------------
# Blaze — creative & ads (reuses the agency Meta engine via a dropship env-swap)
# ---------------------------------------------------------------------------
_META_KEYS = ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_MAP")
_ENV_LOCK = threading.Lock()


@contextlib.contextmanager
def _scoped_meta_env():
    """Overlay the dropship store's OWN Meta creds onto os.environ for one call,
    then restore — same trick as daycare_growth._scoped_env so the agency workspace
    is never disturbed."""
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


class BlazeEngine(_Specialist):
    AGENT, NAME, TITLE = "blaze", "Blaze", "Creative & Ads"
    PLAYBOOK_MD = "blaze-playbook.md"
    ROLE_PROMPT = (
        "You are Blaze, the creative + paid-ads strategist for the FORGE Dropship store. "
        "You read Meta performance against healthy-range benchmarks over a MEANINGFUL "
        "window, call scale/hold/kill/refresh, and draft new ad concepts. You report to "
        "Midas. You never spend or launch — you recommend and draft; a human approves every "
        "launch and budget change."
    )

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
        """Claude reads the Meta numbers (dropship account) + drafts concepts."""
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
                   "what you can see, and draft 2–3 fresh ad concepts per your output "
                   "contract. If no live ad data is connected, say so and draft concepts "
                   "from the brief + brand voice instead of inventing numbers.")
        data = payload.get("data") or ({"metaAnalytics": analytics} if analytics else
                                       {"metaAnalytics": "not connected (mock)"})
        return self.analyze(task, data)


# ---------------------------------------------------------------------------
# Otto — fulfillment & support
# ---------------------------------------------------------------------------
class OttoEngine(_Specialist):
    AGENT, NAME, TITLE = "otto", "Otto", "Fulfillment & Support"
    PLAYBOOK_MD = "otto-playbook.md"
    ROLE_PROMPT = (
        "You are Otto, the fulfillment + customer-support operator for the FORGE Dropship "
        "store. You watch the order pipeline (unshipped/late, stockouts, tracking gaps, "
        "refund/chargeback signal) and draft customer replies. You report to Midas. You "
        "never place a supplier order, send a message, or issue a refund — you flag and "
        "draft; a human approves every outward action. Account health outranks everything."
    )

    def _store_data(self):
        data = {}
        try:
            import dropship_shopify
            data["orders"] = dropship_shopify.orders(limit=50)
            data["inventory"] = dropship_shopify.inventory()
        except Exception as e:  # noqa: BLE001
            data["error"] = str(e)
        return data

    def check(self, payload=None):
        """Fulfillment-health read from Shopify. Optionally drafts a reply if a ticket is
        provided in payload['ticket']."""
        payload = payload or {}
        data = self._store_data()
        ticket = payload.get("ticket")
        if ticket:
            task = ("Draft an honest, factual customer support reply to the ticket below, "
                    "grounded in the order/store data. Never invent a status or ship date. "
                    "Also flag any fulfillment risks you see. Per your output contract.\n\n"
                    "TICKET:\n" + str(ticket))
        else:
            task = ("Read the store's fulfillment health from the data below and surface the "
                    "risks (unshipped/late orders, stockouts, tracking gaps, refund signal), "
                    "ranked, each with a recommendation. Per your output contract.")
        return self.analyze(task, data)
