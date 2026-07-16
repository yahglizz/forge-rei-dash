"""agency_build_studio.py — the Agency "Blueprint Studio".

The operator brings an IDEA (a website, an automation/workflow, an AI receptionist,
anything the agency builds), fills a short intake, and clicks one button. Claude turns
that raw idea into a complete, build-ready BLUEPRINT:

  concept -> how it works -> architecture/layout -> skills & tools required ->
  an ordered build plan (each step owned by a specific agent) -> a concrete TEST plan ->
  the info still needed before a clean build.

The blueprint is saved (marcus_state/agency_build_studio.json), listed, and can be handed
off to the building agent (Dyson) via the agent bus. Every OUTWARD/executing action stays
approval-gated per CLAUDE.md rule 2 — this engine PROPOSES a plan; it never builds or
ships anything on its own. Mirrors agency_io.py (locked JSON store, atomic writes) and
reuses review_agent._claude + the agency key resolver.
"""
import json
import threading
import time
from pathlib import Path

import forge_atomic
import review_agent
import agency_agents  # _agency_key() -> (key, source)

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_build_studio.json"
_LOCK = threading.Lock()

# What the agency builds. Each type steers the architect prompt toward the right shape.
BUILD_TYPES = [
    {"id": "website", "label": "Website / Landing page",
     "shape": "pages & sections, the stack, content blocks, forms/CTAs, hosting & deploy"},
    {"id": "workflow", "label": "Automation / Workflow",
     "shape": "the trigger, each ordered step, the integrations/APIs touched, "
              "branch/error handling, and what data moves between steps"},
    {"id": "receptionist", "label": "AI Receptionist / Voice agent",
     "shape": "the call flow, the intents it must handle, the script/persona, the "
              "knowledge it needs, escalation/handoff rules, and the phone/booking wiring"},
    {"id": "chatbot", "label": "AI Chatbot / Assistant",
     "shape": "the channels, the intents, the knowledge base, guardrails, and the "
              "handoff-to-human rule"},
    {"id": "other", "label": "Something else",
     "shape": "the core components, how they connect, and what makes it work"},
]
_TYPE_IDS = {t["id"] for t in BUILD_TYPES}

STATUSES = ["draft", "handed_off", "building", "testing", "done"]

# The agency roster the plan can assign steps to. Kept honest: only agents/roles that
# actually exist. Dyson builds; Eco does ads/creative; the operator owns credentials,
# approvals, and any money/outward action.
_ROSTER = ("Dyson (build: websites, code, workflows)",
           "Eco (ads & creative strategy)",
           "Operator (you: credentials, approvals, outward actions, final go)")


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("blueprints"), list):
                d.setdefault("seq", 0)
                return d
        except Exception:
            pass
    return {"blueprints": [], "seq": 0}


def _save(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    forge_atomic.atomic_write_json(STATE, d)


def _clean_type(t):
    t = (t or "").strip().lower()
    return t if t in _TYPE_IDS else "other"


def _slim(b):
    return {
        "id": b.get("id"),
        "title": b.get("title") or "(untitled)",
        "buildType": b.get("buildType") or "other",
        "idea": b.get("idea") or "",
        "client": b.get("client") or "",
        "goal": b.get("goal") or "",
        "constraints": b.get("constraints") or "",
        "integrations": b.get("integrations") or "",
        "status": b.get("status") if b.get("status") in STATUSES else "draft",
        "blueprint": b.get("blueprint") or None,
        "model": b.get("model") or "",
        "error": b.get("error") or "",
        "createdAt": b.get("createdAt"),
        "updatedAt": b.get("updatedAt"),
        "generatedAt": b.get("generatedAt"),
    }


def meta():
    """Static options the intake form needs."""
    return {"buildTypes": BUILD_TYPES, "statuses": STATUSES}


def list_blueprints():
    with _LOCK:
        d = _load()
        items = [_slim(b) for b in d.get("blueprints", [])]
        items.sort(key=lambda b: b.get("updatedAt") or b.get("createdAt") or 0, reverse=True)
        return {"ok": True, "blueprints": items, "count": len(items),
                "buildTypes": BUILD_TYPES, "statuses": STATUSES}


def get_blueprint(bid):
    with _LOCK:
        d = _load()
        b = next((x for x in d.get("blueprints", []) if x.get("id") == bid), None)
        return _slim(b) if b else None


# --- the architect: idea -> structured blueprint -----------------------------------------

_BLUEPRINT_SHAPE = (
    '{"concept":"2-4 sentence sharpened statement of what this is and the outcome it '
    'delivers","how_it_works":"plain-English walkthrough a non-engineer understands",'
    '"architecture":[{"name":"component/page/step","detail":"what it is and does"}],'
    '"skills_tools":[{"name":"skill, tool, integration or API","why":"what it is needed '
    'for"}],"build_plan":[{"step":"imperative action","owner":"one of the roster","detail":'
    '"concretely how","done_when":"the checkable done condition"}],"test_plan":[{"check":'
    '"what to verify","how":"the concrete action/tool to run it","pass":"the pass '
    'criteria"}],"info_needed":["a specific question or asset still required before a clean '
    'build"],"estimate":"rough scope/effort (e.g. ~2-3 build sessions)"}'
)


def _architect_system():
    base = (
        "You are the FORGE AI Agency's solutions architect. The operator brings a raw "
        "idea for something the agency will BUILD (a website, an automation/workflow, an "
        "AI receptionist, a chatbot, or similar). Turn it into a complete, build-ready "
        "blueprint that a builder agent can execute with minimal back-and-forth.\n\n"
        "Rules:\n"
        "- Be concrete and specific to THIS idea. No generic filler, no boilerplate steps.\n"
        "- Ground every claim in what the operator actually gave you. If a detail is "
        "missing, DO NOT invent it — put the specific question in info_needed.\n"
        "- The build_plan must be ORDERED and each step owned by exactly one roster role. "
        "The test_plan must be things a builder agent can actually run to prove it works.\n"
        "- Anything that spends money, goes outward (publishing, calling, texting), or "
        "touches credentials is owned by the Operator and stays approval-gated — never "
        "assume it is auto-executed.\n\n"
        f"Roster (assign owners only from these): {'; '.join(_ROSTER)}.\n\n"
        "Return STRICT JSON, no prose outside it, exactly this shape:\n" + _BLUEPRINT_SHAPE
    )
    try:
        import agent_creed
        # Agency evidence discipline (never invent a client's metric/request) outranks all.
        return agent_creed.block("agency") + "\n\n" + base
    except Exception:
        return base


def _architect_user(intake):
    t = _clean_type(intake.get("buildType"))
    shape = next((x["shape"] for x in BUILD_TYPES if x["id"] == t), BUILD_TYPES[-1]["shape"])
    lines = [
        f"BUILD TYPE: {t} — focus the architecture on: {shape}.",
        f"TITLE: {intake.get('title') or '(none given)'}",
        f"THE IDEA (verbatim from the operator):\n{intake.get('idea') or '(none)'}",
    ]
    if intake.get("client"):
        lines.append(f"FOR CLIENT: {intake['client']}")
    if intake.get("goal"):
        lines.append(f"GOAL / OUTCOME WANTED: {intake['goal']}")
    if intake.get("constraints"):
        lines.append(f"CONSTRAINTS: {intake['constraints']}")
    if intake.get("integrations"):
        lines.append(f"TOOLS / INTEGRATIONS THEY MENTIONED: {intake['integrations']}")
    lines.append("\nProduce the blueprint JSON now.")
    return "\n\n".join(lines)


def _parse_json(txt):
    s, e = txt.find("{"), txt.rfind("}")
    if s < 0 or e <= s:
        raise ValueError("no JSON object in architect response")
    return json.loads(txt[s:e + 1])


def generate(payload):
    """Idea in -> structured blueprint out. Creates a new blueprint record (or updates an
    existing one when id is given) and returns it. Never raises to the caller."""
    if not isinstance(payload, dict):
        return {"error": "intake object required"}
    idea = (payload.get("idea") or "").strip()
    title = (payload.get("title") or "").strip()
    if not idea:
        return {"error": "Describe the idea first."}

    key, src = agency_agents._agency_key()
    if not key:
        return {"needsKey": True,
                "error": "Add ANTHROPIC_API_KEY to forge-agency/config/agency.env, then reload."}

    intake = {
        "title": title or idea[:60],
        "buildType": _clean_type(payload.get("buildType")),
        "idea": idea,
        "client": (payload.get("client") or "").strip(),
        "goal": (payload.get("goal") or "").strip(),
        "constraints": (payload.get("constraints") or "").strip(),
        "integrations": (payload.get("integrations") or "").strip(),
    }

    blueprint = None
    err = ""
    model = review_agent.MODEL
    try:
        txt = review_agent._claude(key, _architect_system(), _architect_user(intake),
                                   max_tokens=2600)
        blueprint = _parse_json(txt)
    except Exception as ex:  # noqa: BLE001
        err = str(ex)

    now = int(time.time() * 1000)
    with _LOCK:
        d = _load()
        bid = payload.get("id")
        rec = next((x for x in d.get("blueprints", []) if x.get("id") == bid), None) if bid else None
        if rec:
            rec.update(intake)
            rec["blueprint"] = blueprint
            rec["error"] = err
            rec["model"] = model
            rec["updatedAt"] = now
            rec["generatedAt"] = now
            if blueprint and rec.get("status") not in STATUSES:
                rec["status"] = "draft"
        else:
            d["seq"] = d.get("seq", 0) + 1
            rec = {
                "id": f"bp{d['seq']}_{now}",
                **intake,
                "status": "draft",
                "blueprint": blueprint,
                "error": err,
                "model": model,
                "createdAt": now,
                "updatedAt": now,
                "generatedAt": now,
            }
            d.setdefault("blueprints", []).append(rec)
        _save(d)
        out = _slim(rec)
    if err and not blueprint:
        out["error"] = err
    out["keySource"] = src
    return {"ok": bool(blueprint), **out}


def delete_blueprint(bid):
    if not bid:
        return {"error": "id required"}
    with _LOCK:
        d = _load()
        before = len(d.get("blueprints", []))
        d["blueprints"] = [x for x in d.get("blueprints", []) if x.get("id") != bid]
        _save(d)
    return {"ok": True, "removed": before - len(d["blueprints"])}


def set_status(bid, status):
    status = (status or "").strip().lower()
    if status not in STATUSES:
        return {"error": "invalid status"}
    with _LOCK:
        d = _load()
        rec = next((x for x in d.get("blueprints", []) if x.get("id") == bid), None)
        if not rec:
            return {"error": "blueprint not found"}
        rec["status"] = status
        rec["updatedAt"] = int(time.time() * 1000)
        _save(d)
        return {"ok": True, "blueprint": _slim(rec)}


def hand_off(bid):
    """Queue the blueprint for the building agent (Dyson) via the agent bus and mark it
    handed_off. This is a PROPOSAL — the actual build/test stays approval-gated. Posting a
    bus note is internal + reversible, so it needs no separate approval."""
    with _LOCK:
        d = _load()
        rec = next((x for x in d.get("blueprints", []) if x.get("id") == bid), None)
        if not rec:
            return {"error": "blueprint not found"}
        if not rec.get("blueprint"):
            return {"error": "Generate the blueprint before handing it off."}
        rec["status"] = "handed_off"
        rec["updatedAt"] = int(time.time() * 1000)
        _save(d)
        slim = _slim(rec)
    try:
        import agent_bus
        bp = slim.get("blueprint") or {}
        steps = len(bp.get("build_plan") or [])
        tests = len(bp.get("test_plan") or [])
        agent_bus.send(
            "build-studio", "dyson", "handoff",
            f"New build handed off: {slim['title']} ({slim['buildType']}). "
            f"{steps} build steps, {tests} test checks. Concept: {bp.get('concept','')[:200]}",
            data={"blueprintId": bid})
    except Exception:
        pass
    return {"ok": True, "blueprint": slim}
