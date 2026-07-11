"""retell_io.py — read-only Retell AI bridge for the FORGE Outbound tab.

The dashboard's Python connector talks to api.retellai.com directly (the Retell
*MCP* is a Claude-side tool; this standalone server needs its own REST key).

What it does NOW (no AI agent built yet):
  • status()  -> key present? + agents / phone numbers / concurrency
  • calls()   -> recent calls normalized into the Outbound "call breakdown" shape
                 (AI summary + the few seller facts we care about)

What it deliberately does NOT do yet:
  • create/configure an agent, or place outbound calls. Those land once the
    voice agent + its post-call analysis schema are built. When that happens,
    custom_analysis_data fills the fields below automatically (alias-matched).

Key lookup order: env RETELL_API_KEY -> the shared marcus ghl.env files.
Graceful: no key -> {"hasKey": false}; the UI falls back to sample cards.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.retellai.com"
HERE = Path(__file__).resolve().parent
_ENV_FILES = [
    HERE.parent / "marcus-wholesale-agent" / "config" / "ghl.env",
    Path.home() / "Desktop" / "marcus-wholesale-agent" / "config" / "ghl.env",
]

# Small cache so the Outbound tab's auto-refresh doesn't burn Retell rate limit.
_CACHE = {}
_TTL = 30


def _key():
    k = os.environ.get("RETELL_API_KEY", "").strip()
    if k:
        return k
    for p in _ENV_FILES:
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if line.startswith("RETELL_API_KEY") and "=" in line:
                v = line.partition("=")[2].strip().strip('"').strip("'")
                # ignore an unfilled placeholder like RETELL_API_KEY=key_xxx
                if v and not v.lower().startswith("key_xxx") and v.lower() != "key_here":
                    return v
    return ""


def has_key():
    return bool(_key())


def _req(method, path, body=None, timeout=25):
    key = _key()
    if not key:
        raise RuntimeError("no RETELL_API_KEY")
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            detail = ""
            try:
                detail = e.read().decode("utf-8")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(f"retell {e.code}: {detail or e.reason}")


def _cached(key, fn):
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < _TTL:
        return hit[1]
    val = fn()
    _CACHE[key] = (time.time(), val)
    return val


# --- field mapping: post-call analysis -> the Outbound card -------------------
# Once the agent's post-call analysis is built, name its fields anything close to
# these and they auto-populate. Until then everything falls back to "—".
_ALIASES = {
    "motivation": ["motivation", "seller_motivation", "reason_for_selling", "reason"],
    "timeline": ["timeline", "timeframe", "how_soon", "selling_timeline"],
    "price": ["asking_price", "price", "desired_price", "wants", "price_expectation"],
    "condition": ["condition", "property_condition", "repairs", "repairs_needed"],
    "owed": ["mortgage_owed", "amount_owed", "mortgage", "loan_balance", "owed"],
    "occupancy": ["occupancy", "occupied", "is_occupied", "tenant", "vacant"],
}


def _pick(cad, names):
    if not isinstance(cad, dict):
        return "—"
    low = {k.lower(): v for k, v in cad.items()}
    for n in names:
        if n in low and low[n] not in (None, "", []):
            v = low[n]
            if isinstance(v, bool):
                return "Yes" if v else "No"
            return str(v)
    return "—"


def _dur(ms):
    if not ms:
        return ""
    s = int(ms // 1000)
    return f"{s // 60}m {s % 60:02d}s"


def _outcome(call):
    status = call.get("call_status", "")
    if status in ("registered", "ongoing", "in_progress"):
        return "In Progress", "inprogress"
    ana = call.get("call_analysis") or {}
    if ana.get("call_successful") is True:
        return "Successful", "positive"
    sentiment = (ana.get("user_sentiment") or "").lower()
    if ana.get("call_successful") is False or sentiment == "negative":
        return "Not Interested", "negative"
    if status == "ended":
        return "Completed", "neutral"
    return status.replace("_", " ").title() or "—", "neutral"


def _normalize(call):
    ana = call.get("call_analysis") or {}
    cad = ana.get("custom_analysis_data") or {}
    dyn = call.get("retell_llm_dynamic_variables") or {}
    outcome, kind = _outcome(call)
    name = dyn.get("contact_name") or dyn.get("name") or call.get("to_number") or "Unknown"
    return {
        "callId": call.get("call_id"),
        "name": name,
        "phone": call.get("to_number") or "",
        "market": dyn.get("market") or "",
        "startTs": call.get("start_timestamp") or 0,
        "dur": _dur(call.get("duration_ms")),
        "outcome": outcome,
        "outcomeKind": kind,  # positive | neutral | negative | inprogress
        "summary": ana.get("call_summary") or "(no summary yet)",
        "recordingUrl": call.get("recording_url") or "",
        "motivation": _pick(cad, _ALIASES["motivation"]),
        "timeline": _pick(cad, _ALIASES["timeline"]),
        "price": _pick(cad, _ALIASES["price"]),
        "condition": _pick(cad, _ALIASES["condition"]),
        "owed": _pick(cad, _ALIASES["owed"]),
        "occupancy": _pick(cad, _ALIASES["occupancy"]),
    }


# --- public API ---------------------------------------------------------------
def status():
    if not has_key():
        return {"hasKey": False, "agents": [], "phoneNumbers": [], "concurrency": None}

    def build():
        agents, numbers, conc = [], [], None
        try:
            raw = _req("GET", "/list-agents")
            arr = raw if isinstance(raw, list) else raw.get("agents", [])
            agents = [{"id": a.get("agent_id"), "name": a.get("agent_name") or "(unnamed)",
                       "voice": a.get("voice_id", ""), "language": a.get("language", "")}
                      for a in arr]
        except Exception as e:  # noqa: BLE001
            agents = []
            _agents_err = str(e)
        try:
            raw = _req("GET", "/list-phone-numbers")
            arr = raw if isinstance(raw, list) else raw.get("phone_numbers", [])
            numbers = [{"number": n.get("phone_number"),
                        "outboundAgent": n.get("outbound_agent_id") or None,
                        "nick": n.get("nickname") or ""} for n in arr]
        except Exception:  # noqa: BLE001
            numbers = []
        try:
            conc = _req("GET", "/get-concurrency")
        except Exception:  # noqa: BLE001
            conc = None
        return {"hasKey": True, "agents": agents, "phoneNumbers": numbers,
                "concurrency": conc}

    return _cached("status", build)


def calls(limit=20):
    if not has_key():
        return {"hasKey": False, "calls": []}

    def build():
        try:
            raw = _req("POST", "/v2/list-calls",
                       {"sort_order": "descending", "limit": int(limit)})
        except Exception as e:  # noqa: BLE001
            return {"hasKey": True, "calls": [], "error": str(e)}
        arr = raw if isinstance(raw, list) else raw.get("calls", [])
        return {"hasKey": True, "calls": [_normalize(c) for c in arr]}

    return _cached(f"calls:{limit}", build)


# ── Agent editor: read + write the agent's tone/questions/opener/voice ────────
# Editable surface = the linked Retell LLM (general_prompt holds tone + the
# questions to ask; begin_message is the opener) + agent voice/name/language.
def list_voices():
    if not has_key():
        return {"hasKey": False, "voices": []}

    def build():
        try:
            raw = _req("GET", "/list-voices")
        except Exception:  # noqa: BLE001
            return {"hasKey": True, "voices": []}
        arr = raw if isinstance(raw, list) else raw.get("voices", [])
        out = [{"id": v.get("voice_id"), "name": v.get("voice_name") or v.get("voice_id"),
                "provider": v.get("provider", ""), "gender": v.get("gender", ""),
                "accent": v.get("accent", "")} for v in arr]
        return {"hasKey": True, "voices": out}

    return _cached("voices", build)


def get_agent(agent_id=None):
    """Full editable view of an agent + its LLM. If no agent_id, use the first agent."""
    if not has_key():
        return {"hasKey": False, "found": False}
    if not agent_id:
        s = status()
        ags = s.get("agents") or []
        if not ags:
            return {"hasKey": True, "found": False}
        agent_id = ags[0]["id"]
    agent = _req("GET", f"/get-agent/{agent_id}")
    eng = agent.get("response_engine") or {}
    etype = eng.get("type", "")
    out = {
        "hasKey": True, "found": True, "agentId": agent.get("agent_id"),
        "agentName": agent.get("agent_name") or "",
        "voiceId": agent.get("voice_id") or "",
        "language": agent.get("language") or "en-US",
        "engine": etype, "editable": etype == "retell-llm",
        "llmId": eng.get("llm_id") or "",
        "model": "", "beginMessage": "", "generalPrompt": "",
    }
    if etype == "retell-llm" and out["llmId"]:
        try:
            llm = _req("GET", f"/get-retell-llm/{out['llmId']}")
            out["model"] = llm.get("model") or ""
            out["beginMessage"] = llm.get("begin_message") or ""
            out["generalPrompt"] = llm.get("general_prompt") or ""
        except Exception:  # noqa: BLE001
            pass
    return out


def update_agent(body):
    """Save edits from the dashboard back to Retell. body: agentId, llmId,
    agentName, voiceId, language, model, beginMessage, generalPrompt."""
    if not has_key():
        return {"ok": False, "error": "no RETELL_API_KEY"}
    aid = body.get("agentId")
    lid = body.get("llmId")
    if not aid:
        return {"ok": False, "error": "agentId required"}
    try:
        agent_patch = {}
        if body.get("agentName") is not None:
            agent_patch["agent_name"] = body["agentName"]
        if body.get("voiceId"):
            agent_patch["voice_id"] = body["voiceId"]
        if body.get("language"):
            agent_patch["language"] = body["language"]
        if agent_patch:
            _req("PATCH", f"/update-agent/{aid}", agent_patch)
        if lid:
            llm_patch = {}
            if body.get("generalPrompt") is not None:
                llm_patch["general_prompt"] = body["generalPrompt"]
            if body.get("beginMessage") is not None:
                llm_patch["begin_message"] = body["beginMessage"]
            if body.get("model"):
                llm_patch["model"] = body["model"]
            if llm_patch:
                _req("PATCH", f"/update-retell-llm/{lid}", llm_patch)
        # Push it live (best-effort; older keys may not expose publish).
        published = False
        try:
            _req("POST", f"/publish-agent/{aid}")
            published = True
        except Exception:  # noqa: BLE001
            published = False
        _CACHE.pop("status", None)
        return {"ok": True, "published": published}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


_DEFAULT_PROMPT = """You are an outbound acquisitions caller for a real estate wholesaler (the owner is Yahjair, company "A Touch of Blessings Home Buyers"). You call property owners to see if they'd sell their house for cash.

GOAL: have a short, friendly conversation, find out if they're open to a cash offer, and book a callback/appointment for Yahjair.

TONE: casual, warm, respectful, persistent but never pushy. Talk like a real neighbor, not a salesperson. Keep it short.

ASK (work these in naturally, don't interrogate):
- Are they the owner, and would they consider selling?
- Why might they sell / what's their situation (motivation)?
- Condition of the property?
- Any mortgage owed, roughly?
- Is it vacant, owner-occupied, or rented?
- What kind of price are they hoping for?
- Timeline — how soon would they want to move?

ALWAYS give them an easy out ("totally fine if not"). If interested, set a time for Yahjair to call back. Never give a specific price on the call. If they say stop/not interested, politely end."""


def create_starter_agent(seed_voice_guide=True):
    """Create a ready-to-edit outbound agent (LLM + agent) so the user can tune it
    from the dashboard. Seeds the prompt with Yahjair's learned voice if available."""
    if not has_key():
        return {"ok": False, "error": "no RETELL_API_KEY"}
    prompt = _DEFAULT_PROMPT
    if seed_voice_guide:
        try:
            from brain_io import VAULT
            vg = VAULT / "Skills" / "yahjair-voice.md"
            if vg.is_file():
                prompt += "\n\nMATCH THIS VOICE (learned from Yahjair's real texts):\n" + vg.read_text(errors="ignore")[:1500]
        except Exception:  # noqa: BLE001
            pass
    # pick a default voice
    voice_id = "11labs-Adrian"
    vs = list_voices().get("voices") or []
    if vs:
        voice_id = vs[0]["id"]
    try:
        llm = _req("POST", "/create-retell-llm", {
            "model": "gpt-4o-mini",
            "general_prompt": prompt,
            "begin_message": "Hey, this is the team at A Touch of Blessings Home Buyers — is this a good time for a quick minute about your property?",
        })
        lid = llm.get("llm_id")
        agent = _req("POST", "/create-agent", {
            "agent_name": "Ava — Outbound Acquisitions",
            "voice_id": voice_id,
            "language": "en-US",
            "response_engine": {"type": "retell-llm", "llm_id": lid},
        })
        _CACHE.pop("status", None)
        return {"ok": True, "agentId": agent.get("agent_id"), "llmId": lid}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
