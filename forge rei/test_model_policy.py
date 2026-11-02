"""Run with python3 test_model_policy.py — the cost policy: two model tiers behind a hard
allowlist, the chat router, scheduled briefs + self-improvement OFF by default, one main agent
per business. No network: urlopen and the model are faked."""
import ast
import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

os.environ.pop("FORGE_SELF_IMPROVE", None)
HERE = Path(__file__).parent


def check():
    import review_agent as ra
    assert ra.FAST_MODEL == "claude-haiku-5-5" and ra.SMART_MODEL == "claude-sonnet-5-5"
    assert ra.ALLOWED_MODELS == ("claude-haiku-5-5", "claude-sonnet-5-5")
    assert ra.MODEL == ra.FAST_MODEL, "an unnamed call site must default to the cheap tier"
    assert ra.DRAFT_MODEL == ra.SMART_MODEL, "inbound seller replies run on the smart tier"
    # Haiku 5.5 thinks by default and thinking eats max_tokens: adaptive, low, with headroom.
    assert ra.thinking_params(ra.FAST_MODEL, 500, "low") == {
        "max_tokens": 500 + 2048, "thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}
    assert ra.thinking_params(ra.SMART_MODEL, 500, "low")["output_config"] == {"effort": "low"}
    assert ra.self_improve_on() is False
    os.environ["FORGE_SELF_IMPROVE"] = "1"
    assert ra.self_improve_on() is True
    del os.environ["FORGE_SELF_IMPROVE"]

    # Opus / Fable are never a default anywhere in the app.
    for p in HERE.glob("*.py"):
        if p.name.startswith("test_") or p.name == "cost_tracker.py":
            continue
        assert not re.search(r'claude-(opus|fable|mythos)', p.read_text()), p.name

    # Switches are OFF unless the env says otherwise.
    conn = (HERE / "connector.py").read_text()
    assert 'BRIEFS_ON = os.environ.get("FORGE_BRIEFS", "0") != "0"' in conn
    import daycare_director
    assert daycare_director.SCHEDULED_BRIEF is False
    assert 'os.environ.get("FORGE_SKILL_FORGE", "0") == "0"' in (HERE / "skill_forge.py").read_text()
    for f in ("scout_triage", "deal_prep", "marcus_screening", "daycare_director",
              "mission_control_agent", "dropship_director", "agency_agents"):
        assert "self_improve_on()" in (HERE / (f + ".py")).read_text(), f

    # Re-engage bumps stay on the smart tier: seller-facing.
    assert "model=review_agent.SMART_MODEL" in (HERE / "reengage_draft.py").read_text()
    assert "model=review_agent.SMART_MODEL" in (HERE / "reengage_copy.py").read_text()
    assert "import review_agent" in (HERE / "daycare_replies.py").read_text()
    import daycare_replies
    assert daycare_replies.MODEL == ra.SMART_MODEL

    # One main agent per business + the CEO.
    import agents_hub
    assert [a["id"] for a in agents_hub.roster()["agents"]] == ["marcus", "dyson", "solomon", "midas", "orion"]
    print("model policy OK")


# Every _claude() call in these files must name both a model and an effort, so nothing silently
# falls back to the default tier or to a model's own default effort.
AGENT_BRAIN_FILES = (
    "review_agent", "legit_check", "marcus_lead", "daycare_ads_autopilot", "mission_control_agent",
    "daycare_director", "dropship_director", "style_agent", "skill_forge", "scout_triage",
    "deal_prep", "marcus_screening", "agency_agents", "agents_chat", "agent_collab", "dash_live",
    "toolkit_calc",
)


def check_agent_calls_named():
    import ast
    bad = []
    for f in AGENT_BRAIN_FILES:
        for n in ast.walk(ast.parse((HERE / (f + ".py")).read_text())):
            fn = getattr(n, "func", None)
            if isinstance(n, ast.Call) and getattr(fn, "attr", getattr(fn, "id", None)) == "_claude":
                kw = {k.arg for k in n.keywords}
                if not {"model", "effort"} <= kw:
                    bad.append(f"{f}.py:{n.lineno}")
    assert not bad, "_claude() without model= and effort=: " + ", ".join(bad)
    print("agent calls named OK")


# The audit's Haiku list (rule: Sonnet if it reaches a parent, seller or client, or drives a money
# decision; plans and briefs Sonnet; everything else Haiku). Two unnamed sites default to FAST.
# Not here, on purpose: agent_collab.consult_round (the operator's final reply, can restate deal
# numbers) and legit_check.verdict (gates every non-operator seller SMS, sms_guard + autopilot).
FAST_SITES = sorted([
    ("agency_agents.py", "learn"), ("agent_collab.py", "ask"),
    ("agents_chat.py", "chat"), ("agents_chat.py", "chat"),
    ("marcus_lead.py", "directives"), ("marcus_screening.py", "screen"),
    ("scout_triage.py", "_claude_batch"), ("scout_triage.py", "retro_audit"),
])
UNNAMED_SITES = sorted([("agency_callsheet.py", "_leads_from_ai"), ("telegram_ops.py", "_intent")])


def _claude_sites():
    """-> {"FAST_MODEL"|"SMART_MODEL"|other|None: [(file, enclosing fn)]} over all app code."""
    out = {}

    def walk(n, f, fn):
        for c in ast.iter_child_nodes(n):
            inner = c.name if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if isinstance(c, ast.Call) and getattr(c.func, "attr", getattr(c.func, "id", None)) == "_claude":
                m = next((k.value for k in c.keywords if k.arg == "model"), None)
                tier = getattr(m, "attr", getattr(m, "id", None)) if m is not None else None
                out.setdefault(tier, []).append((f, fn))
            walk(c, f, inner)
    for p in HERE.glob("*.py"):
        if not p.name.startswith("test_"):
            walk(ast.parse(p.read_text()), p.name, None)
    return out


def check_tiers():
    sites = _claude_sites()
    assert sorted(sites["FAST_MODEL"]) == FAST_SITES, sorted(sites["FAST_MODEL"])
    assert sorted(sites[None]) == UNNAMED_SITES, sorted(sites[None])
    assert ("toolkit_calc.py", "find_arv") in sites["SMART_MODEL"], "ARV is a money input"
    assert ("scout_triage.py", "learn") in sites["SMART_MODEL"]
    assert ("agent_collab.py", "consult_round") in sites["SMART_MODEL"], "operator's final reply"
    assert ("legit_check.py", "verdict") in sites["SMART_MODEL"], "gates seller-facing SMS"
    # Haiku runs at low effort: no FAST site may ask for more.
    for p in HERE.glob("*.py"):
        if not p.name.startswith("test_"):
            for n in ast.walk(ast.parse(p.read_text())):
                if isinstance(n, ast.Call) and any(k.arg == "model" and getattr(k.value, "attr", "") == "FAST_MODEL"
                                                   for k in n.keywords):
                    effort = next((k.value.value for k in n.keywords if k.arg == "effort"), "low")
                    assert effort == "low", f"{p.name}:{n.lineno}"
    print("tiers OK")


class _Sent:
    """Stands in for urlopen; keeps the bytes that really left."""
    def __init__(self):
        self.bodies = []

    def __call__(self, req, timeout=None):
        self.bodies.append(json.loads(req.data))
        outer = self

        class R:
            def read(self):
                return json.dumps({"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                                   "model": outer.bodies[-1]["model"]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R()


class _Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _door_problems(src, name):
    """Every function holding the Anthropic URL or version header is a door. It must call
    claude_urlopen and must not open the socket itself. The header catches a URL read from env."""
    bad = []

    def called(fn):
        return {getattr(c.func, "attr", getattr(c.func, "id", None)) for c in ast.walk(fn) if isinstance(c, ast.Call)}

    def walk(n, fn):
        for c in ast.iter_child_nodes(n):
            hit = isinstance(c, ast.Constant) and isinstance(c.value, str) and " " not in c.value and (
                "api.anthropic.com" in c.value or c.value == "anthropic-version")
            if hit and fn is None:
                bad.append(f"{name}:{c.lineno} module-level door")
            elif hit and ("claude_urlopen" not in called(fn) or "urlopen" in called(fn)):
                bad.append(f"{name}:{c.lineno} {fn.name} goes around the gate")
            walk(c, c if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn)
    walk(ast.parse(src), None)
    return bad


def check_every_door_goes_through_the_gate():
    """Find every path to Anthropic; each one must call claude_urlopen, and it must run the gate."""
    doors, bad = set(), []
    for p in HERE.glob("*.py"):
        src = p.read_text()
        if p.name.startswith("test_"):
            continue
        assert not re.search(r"^\s*(import|from) anthropic\b", src, re.M), f"SDK bypass in {p.name}"
        if "api.anthropic.com" in src:
            doors.add(p.name)
        bad += _door_problems(src, p.name)
    assert not bad, bad
    assert doors == {"agent_runner.py", "marcus_engine.py", "review_agent.py"}, doors
    # The gate runs first in claude_urlopen, before anything can reach the socket.
    tree = ast.parse((HERE / "review_agent.py").read_text())
    fn = next(n for n in tree.body if getattr(n, "name", "") == "claude_urlopen")
    assert getattr(fn.body[1].value.func, "id", None) == "_enforce_model", ast.dump(fn.body[1])
    # The checker itself: a second ungated door beside a real claude_urlopen def is caught.
    real = "def claude_urlopen(req, timeout):\n    _enforce_model(req)\n"
    sneaky = ('def f(key):\n    req = Request("https://api.anthropic.com/v1/messages")\n'
              "    return urllib.request.urlopen(req)\n")
    assert _door_problems(real + sneaky, "x") == ["x:4 f goes around the gate"], "direct urlopen"
    assert _door_problems(real + 'U = "https://api.anthropic.com/v1/messages"\n', "x") == ["x:3 module-level door"]
    assert _door_problems(real + 'def g(u):\n    return urlopen(Request(u, headers={"anthropic-version": "1"}))\n',
                          "x"), "URL from a variable"
    assert not _door_problems(real + 'def h():\n    return claude_urlopen(Request("https://api.anthropic.com/x"), 5)\n',
                              "x"), "a gated door passes"
    print("every door gated OK")


def check_allowlist():
    import review_agent as ra
    sent, log = _Sent(), _Records()
    logging.getLogger("forge.models").addHandler(log)
    real = urllib.request.urlopen
    urllib.request.urlopen = sent
    gate_was = ra._circuit_gate
    ra._circuit_gate = lambda req: None
    try:
        for bad in ("claude-opus-5-5", "claude-fable-5-1", "claude-mythos-5-1", "claude-haiku-4-5-20251001",
                    "gpt-whatever", "", None):
            # straight through the gate, the way agent_runner and marcus_engine call it
            req = urllib.request.Request("https://api.anthropic.com/v1/messages", method="POST",
                                         data=json.dumps({"model": bad, "max_tokens": 100}).encode())
            ra.claude_urlopen(req, 5)
            assert sent.bodies[-1]["model"] == ra.SMART_MODEL, bad
            assert sent.bodies[-1]["output_config"] == {"effort": "low"}, "an old id sent no effort"
            # through the shared helpers, the way 50 call sites do
            ra._claude("k", "s", "u", model=bad or "x")
            assert sent.bodies[-1]["model"] == ra.SMART_MODEL, bad
        assert any("claude-opus-5-5" in x for x in log.lines), "a blocked model must be logged"
        n = len(log.lines)
        for good in ra.ALLOWED_MODELS:
            ra._claude("k", "s", "u", model=good)
            assert sent.bodies[-1]["model"] == good
        assert len(log.lines) == n, "an allowed model logs nothing"
    finally:
        urllib.request.urlopen = real
        ra._circuit_gate = gate_was
        logging.getLogger("forge.models").removeHandler(log)
    print("allowlist OK")


_ENV_PROBE = """
import json, sys, urllib.request
sys.path.insert(0, %r)
import review_agent as ra, daycare_replies
sent = []
class R:
    def read(self): return b'{"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}'
    def __enter__(self): return self
    def __exit__(self, *a): return False
def fake(req, timeout=None):
    sent.append(json.loads(req.data)["model"])
    return R()
urllib.request.urlopen = fake
ra._circuit_gate = lambda req: None
for m in (ra.FAST_MODEL, ra.SMART_MODEL, ra.MODEL, ra.HAIKU_MODEL, ra.DRAFT_MODEL, daycare_replies.MODEL):
    ra._claude("k", "s", "u", model=m)
ra._claude("k", "s", "u")
print(json.dumps(sent))
"""


def check_env_cannot_reach_a_banned_model():
    """Each FORGE_*_MODEL knob, set to Opus or Fable, in a fresh process with no restart tricks."""
    src = " ".join(p.read_text() for p in HERE.glob("*.py") if not p.name.startswith("test_"))
    knobs = sorted(set(re.findall(r"FORGE_[A-Z_]*MODEL\b", src)))
    assert knobs == ["FORGE_DAYCARE_REPLY_MODEL", "FORGE_DRAFT_MODEL", "FORGE_FAST_MODEL", "FORGE_HAIKU_MODEL",
                     "FORGE_REVIEW_MODEL", "FORGE_SMART_MODEL"], knobs
    for knob in knobs:
        for bad in ("claude-opus-5-5", "claude-fable-5-1"):
            env = {**os.environ, knob: bad, "PYTHONDONTWRITEBYTECODE": "1"}
            r = subprocess.run([sys.executable, "-c", _ENV_PROBE % str(HERE)], env=env, cwd=HERE,
                               capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, r.stderr[-400:]
            sent = json.loads(r.stdout.strip().splitlines()[-1])
            assert len(sent) == 7 and set(sent) <= {"claude-haiku-5-5", "claude-sonnet-5-5"}, (knob, bad, sent)
            assert bad in r.stderr, f"{knob}={bad} must log a warning"
    print("env knobs OK")


# ── the chat router: the same scenarios through all three tool loops ─────────────────────────
H, S = "claude-haiku-5-5", "claude-sonnet-5-5"
ORIGINAL = "how many tours"


def _use(name="api_get", tid="t1", extra=()):
    return {"content": [*extra, {"type": "tool_use", "id": tid, "name": name, "input": {"path": "/api/x"}}],
            "stop_reason": "tool_use"}


def _text(t):
    return {"content": [{"type": "text", "text": t}], "stop_reason": "end_turn"}


TOOL = {"name": "api_get", "description": "read", "input_schema": {"type": "object"}}


def _dash(script, payloads, ran):
    import dash_live
    import review_agent
    saved = (dash_live.active, dash_live.live_block, dash_live.tools, dash_live.run_tool, dash_live.writes_on,
             review_agent.post_messages)

    def post(key, payload):
        payloads.append(json.loads(json.dumps(payload)))
        return script.pop(0) if script else _text("done")
    dash_live.active, dash_live.live_block = (lambda a: True), (lambda a: "")
    dash_live.tools, dash_live.writes_on = (lambda a: [TOOL]), (lambda a: False)
    dash_live.run_tool = lambda name, inp, a: (ran.append(name), "result")[1]
    review_agent.post_messages = post
    try:
        return dash_live.ask("k", "SYS", ORIGINAL, "solomon")
    finally:
        (dash_live.active, dash_live.live_block, dash_live.tools, dash_live.run_tool, dash_live.writes_on,
         review_agent.post_messages) = saved


def _telegram(script, payloads, ran):
    import telegram_agent as ta
    saved = ta.system_prompt, ta._run_tool

    def call(key, payload):
        payloads.append(json.loads(json.dumps(payload)))
        return script.pop(0) if script else _text("done")
    ta.system_prompt = lambda a, b: "SYS"
    ta._run_tool = lambda name, inp, *a: (ran.append(name), "result")[1]
    try:
        return ta.chat("solomon", ORIGINAL, [], "1", key="k", call=call)["reply"]
    finally:
        ta.system_prompt, ta._run_tool = saved


def _gateway(script, payloads, ran):
    import agent_runner as ar
    import review_agent
    saved = ar.load_files, ar.call_model, ar.call_tool

    def call(spec, payload):
        payloads.append(json.loads(json.dumps(payload)))
        return script.pop(0) if script else _text("done")
    ar.load_files = lambda rels, root: ("", [])
    ar.call_model = call
    ar.call_tool = lambda spec, name, inp: (ran.append(name), {"result": "result"})[1]
    try:
        return ar.run({"files": [], "root": ".", "head": "h", "tail": "t", "tools": [TOOL], "max_tokens": 2500,
                       "messages": [{"role": "user", "content": ORIGINAL}], "max_turns": 3,
                       "models": review_agent.chat_models()})["reply"]
    finally:
        ar.load_files, ar.call_model, ar.call_tool = saved


LOOPS = {"dash": _dash, "telegram": _telegram, "gateway": _gateway}


def _run(loop, script):
    payloads, ran = [], []
    reply = LOOPS[loop](list(script), payloads, ran)
    return reply, payloads, ran


def _offers(payload):
    return "escalate" in [t["name"] for t in payload["tools"]]


def _first_user(p):
    c = p["messages"][0]["content"]
    return c if isinstance(c, str) else json.dumps(c)


def check_router():
    import review_agent as ra
    os.environ.pop("FORGE_CHAT_ROUTER", None)
    assert ra.chat_models() == [H, S]
    esc = ra.ESCALATE_TOOL["description"].lower()
    for word in ("judgment", "writing", "planning", "money", "multi-step"):
        assert word in esc, word

    for loop in LOOPS:
        # A lookup stays on Haiku the whole way and never touches Sonnet.
        reply, ps, ran = _run(loop, [_use(), _text("3 tours")])
        assert reply == "3 tours" and [p["model"] for p in ps] == [H, H] and ran == ["api_get"], loop
        assert all(_offers(p) for p in ps), loop
        assert ps[0]["output_config"] == {"effort": "low"} and ps[0]["thinking"] == {"type": "adaptive"}, loop

        # escalate first thing: Sonnet gets the turn, no tool ran, and Sonnet is not offered escalate.
        reply, ps, ran = _run(loop, [_use("escalate"), _text("the plan")])
        assert reply == "the plan" and [p["model"] for p in ps] == [H, S] and ran == [], (loop, ps)
        assert not _offers(ps[1]), loop

        # escalate after a read: restart from the ORIGINAL messages, no Haiku transcript or thinking.
        think = {"type": "thinking", "thinking": "", "signature": "sig"}
        reply, ps, ran = _run(loop, [_use(extra=[think]), _use("escalate", "t2", [think]), _text("the plan")])
        assert reply == "the plan" and [p["model"] for p in ps] == [H, H, S], (loop, [p["model"] for p in ps])
        assert ps[2]["messages"] == ps[0]["messages"], (loop, ps[2]["messages"])
        assert len(ps[2]["messages"]) == 1 and ORIGINAL in _first_user(ps[2]), loop
        assert "thinking" not in json.dumps(ps[2]["messages"]), loop

        # Thinking blocks go back unchanged inside a loop, empty text and signature included.
        assert ps[1]["messages"][1] == {"role": "assistant", "content": _use(extra=[think])["content"]}, loop

        # Haiku never writes: a write restarts on Sonnet before it runs, so nothing runs twice.
        reply, ps, ran = _run(loop, [_use("api_post"), _text("filed")])
        assert reply == "filed" and [p["model"] for p in ps] == [H, S] and ran == [], (loop, ran)

        # So does a teammate consult: it counts against caps and logs to the bus, so never twice.
        reply, ps, ran = _run(loop, [_use("ask_agent"), _text("asked")])
        assert reply == "asked" and [p["model"] for p in ps] == [H, S] and ran == [], (loop, ran)

        # A tool nobody listed as a read is not a read: fail safe, restart first.
        reply, ps, ran = _run(loop, [_use("some_new_tool"), _text("ok")])
        assert [p["model"] for p in ps] == [H, S] and ran == [], (loop, ran)

        # An empty Haiku ending (thinking ate the cap, refusal) restarts rather than says nothing.
        for dead in ({"content": [{"type": "thinking", "thinking": "", "signature": "s"}], "stop_reason": "max_tokens"},
                     {"content": [], "stop_reason": "refusal"}):
            reply, ps, ran = _run(loop, [dead, _text("answer")])
            assert reply == "answer" and [p["model"] for p in ps] == [H, S], (loop, dead)

        # At most one restart, however many times anything asks.
        reply, ps, ran = _run(loop, [_use("escalate"), _text("x"), _use("escalate"), _text("y")])
        assert reply == "x" and len(ps) == 2, loop

        # Kill switch: straight to Sonnet, no escalate on offer.
        os.environ["FORGE_CHAT_ROUTER"] = "0"
        try:
            assert ra.chat_models() == [S]
            reply, ps, ran = _run(loop, [_use(), _text("3 tours")])
            assert reply == "3 tours" and [p["model"] for p in ps] == [S, S], loop
            assert not any(_offers(p) for p in ps), loop
        finally:
            del os.environ["FORGE_CHAT_ROUTER"]

    # The capped tool_choice:none turn on Haiku still answers, and escalate stays declared on it
    # so the tool list never changes under replayed thinking blocks.
    for loop, cap in (("dash", 4), ("telegram", 6), ("gateway", 3)):
        reply, ps, ran = _run(loop, [_use(tid=f"t{i}") for i in range(cap)] + [_text("from what I read")])
        assert reply == "from what I read", (loop, reply)
        assert ps[-1]["tool_choice"] == {"type": "none"} and ps[-1]["model"] == H and _offers(ps[-1]), loop
        assert len(ps) == cap + 1, loop
    print("router OK")


def check_consult_round_final_is_sonnet():
    import agent_collab
    import review_agent as ra
    seen, real_claude, real_ask = [], ra._claude, agent_collab.ask

    def fake(key, system, user, max_tokens=1200, tools=None, model=None, effort="low"):
        seen.append((model, effort))
        return "final answer"
    ra._claude, agent_collab.ask = fake, lambda *a, **k: "3 hot"
    try:
        out = agent_collab.consult_round("marcus", "SYS", "u", "[ASK SCOUT] how many hot?", "k")
    finally:
        ra._claude, agent_collab.ask = real_claude, real_ask
    assert out.startswith("final answer") and seen == [(ra.SMART_MODEL, "low")], (out, seen)
    print("consult round OK")


def check_gateway_spec_routes_chat_only():
    import agent_gateway as gw
    src = (HERE / "agent_gateway.py").read_text()
    assert '"models": review_agent.chat_models()' in src, "gateway chat starts on the router"
    assert '"FORGE_CHAT_ROUTER"' not in src, "the child has no such env: the choice travels in the spec"
    assert gw.RUNNER.exists()
    print("gateway spec OK")


def check_pause_turn_passes_thinking_back():
    import review_agent as ra
    think = {"type": "thinking", "thinking": "", "signature": "sig"}
    seen, real = [], ra.post_messages

    def post(key, payload):
        seen.append(json.loads(json.dumps(payload["messages"])))
        return ({"content": [think], "stop_reason": "pause_turn"} if len(seen) == 1 else _text("ok"))
    ra.post_messages = post
    try:
        assert ra._claude("k", "s", "u", model=ra.FAST_MODEL, effort="low") == "ok"
    finally:
        ra.post_messages = real
    assert seen[1][-1] == {"role": "assistant", "content": [think]}, seen
    print("pause_turn OK")


def check_max_tokens_never_ends_empty():
    import review_agent as ra
    seen = []
    real = ra.post_messages

    def post(key, payload):
        seen.append(payload["max_tokens"])
        if len(seen) == 1:
            return {"content": [{"type": "thinking", "thinking": "", "signature": "s"}], "stop_reason": "max_tokens"}
        return _text('{"intent": "x"}')
    ra.post_messages = post
    try:
        assert ra._claude("k", "s", "u", max_tokens=50, model=ra.FAST_MODEL, effort="low") == '{"intent": "x"}'
        assert seen == [2098, 4196], seen
    finally:
        ra.post_messages = real
    # ...and only once: a second empty answer comes back empty for the caller's own fallback.
    seen.clear()
    ra.post_messages = lambda k, p: (seen.append(1), {"content": [], "stop_reason": "max_tokens"})[1]
    try:
        assert ra._claude("k", "s", "u", max_tokens=50, model=ra.FAST_MODEL, effort="low") == ""
        assert len(seen) == 2
    finally:
        ra.post_messages = real
    print("max_tokens OK")


def check_reply_style():
    import caveman
    assert os.environ.get("FORGE_CAVEMAN_LEVEL") in (None, "full") and caveman._level() == "full"
    # Every operator chat call site puts the style on the prompt its reply is written from.
    for f, names in (("agents_chat.py", ("_claude", "ask", "consult_round")), ("agents_hub.py", ("ask",)),
                     ("agency_agents.py", ("ask",)), ("marcus_chat.py", ("ask", "consult_round"))):
        src = (HERE / f).read_text()
        hits = 0
        for n in ast.walk(ast.parse(src)):
            name = getattr(n.func, "attr", None) if isinstance(n, ast.Call) else None
            if name in names and (name != "ask" or getattr(n.func.value, "id", "") == "dash_live"):
                hits += 1
                assert "caveman.block()" in ast.get_source_segment(src, n.args[1]), f"{f}:{n.lineno}"
        assert hits, f
    # The text style tells the model how to open and close; SMS and scoring stay out of it.
    for rule in ("no opener", "no sign-off", "grounding:", "no title line"):
        assert rule in caveman._TEXT.lower(), rule
    for f in ("marcus_engine.py", "daycare_replies.py", "daycare_revive.py", "scout_triage.py", "marcus_screening.py",
              "agent_creed.py", "legit_check.py"):
        assert "caveman" not in re.sub(r"(?m)#.*$|\"\"\".*?\"\"\"", "", (HERE / f).read_text(), flags=re.S), f
    # Gateway chat: the texting style is the last thing in the prompt, and on his newest message.
    gw = (HERE / "agent_gateway.py").read_text()
    assert "+ live + caveman.text_block()" in gw and 'req["message"] + caveman.TEXT_NUDGE' in gw
    print("reply style OK")


if __name__ == "__main__":
    check()
    check_agent_calls_named()
    check_tiers()
    check_every_door_goes_through_the_gate()
    check_allowlist()
    check_env_cannot_reach_a_banned_model()
    check_router()
    check_consult_round_final_is_sonnet()
    check_gateway_spec_routes_chat_only()
    check_pause_turn_passes_thinking_back()
    check_max_tokens_never_ends_empty()
    check_reply_style()
