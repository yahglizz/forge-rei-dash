"""model_router.py — pluggable chat-model routing (Hermes-agent style).

WHY THIS EXISTS
The whole app funnels every LLM call through `review_agent._claude` (Anthropic
HTTP). This module is a thin, OPT-IN layer that lets the OPERATOR pick which
model answers in the **Agents chat** — Claude (default) or their ChatGPT, driven
by the local **Codex CLI** so it rides the ChatGPT subscription instead of a
pay-per-token OpenAI API key.

HARD BOUNDARIES (CLAUDE.md)
  • ADDITIVE + DEFAULT-OFF. With no prefs set and nothing configured, every
    caller behaves EXACTLY as before — `complete()` just forwards to
    `review_agent._claude`. `review_agent.py` is not modified, so the ~22
    internal callers (scoring, briefs, learn loops) and the seller-facing
    drafter (`marcus_engine`) are untouched and stay on Claude.
  • Only operator chat opts in. Sellers never see a non-Claude model.
  • No secrets in code or logs. Codex authenticates via ~/.codex/auth.json
    (ChatGPT sign-in); Anthropic uses the existing key resolver.
  • Anything unavailable FALLS BACK to Claude — a bad Codex setup never errors
    a chat that could have been answered by Claude.

PROVIDERS (resolved from the model string)
  • "claude-*" / "anthropic:*"          -> review_agent._claude (existing path)
  • "codex" / "codex:<m>" / "gpt-*"      -> `codex exec` subprocess (subscription)
  • "openai:<m>" (needs OPENAI_API_KEY)  -> OpenAI-compatible HTTP (dormant)

The Codex CLI must be installed + logged in on whatever machine RUNS the agents
(the box: `npm i -g @openai/codex` then `codex login`, or copy ~/.codex/auth.json
from a signed-in machine). Where it isn't, the picker shows "not set up" and
Claude keeps answering.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import review_agent  # safe: review_agent does NOT import this module (no cycle)

HERE = Path(__file__).resolve().parent
PREFS = HERE / "marcus_state" / "model_prefs.json"
_LOCK = threading.Lock()

# Global default when no pref is saved. FORGE_CHAT_MODEL lets the box override it.
DEFAULT_MODEL = os.environ.get("FORGE_CHAT_MODEL", "claude-sonnet-4-5")

# Pickable models the UI offers, grouped by provider. Operator can extend freely;
# an unknown-but-valid model string still routes by its provider prefix.
CATALOG = {
    "anthropic": [
        {"id": "claude-sonnet-4-5", "label": "Claude Sonnet 4.5"},
        {"id": "claude-opus-4-1", "label": "Claude Opus 4.1"},
        {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
    ],
    "codex": [
        {"id": "codex", "label": "ChatGPT — Codex default"},
        {"id": "codex:gpt-5.5", "label": "ChatGPT · GPT-5.5"},
        {"id": "codex:gpt-5.5-codex", "label": "ChatGPT · GPT-5.5-Codex"},
    ],
}


# ── provider resolution ─────────────────────────────────────────────────────────
def provider_of(model):
    m = (model or "").strip().lower()
    if m == "codex" or m.startswith("codex:") or m.startswith("gpt-") or m.startswith("gpt5"):
        return "codex"
    if m.startswith("openai:"):
        return "openai"
    return "anthropic"  # bare claude-*, anthropic:*, or empty/unknown


# ── prefs store (mirrors agency_io: lock + _load/_save, atomic write) ────────────
def _load_prefs():
    try:
        if PREFS.exists():
            d = json.loads(PREFS.read_text())
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def _save_prefs(d):
    try:
        PREFS.parent.mkdir(parents=True, exist_ok=True)
        import forge_atomic
        forge_atomic.atomic_write_json(PREFS, d)
    except Exception:
        pass


def global_default():
    return _load_prefs().get("default") or DEFAULT_MODEL


def model_for(agent=None):
    """Resolve the model for a chat: per-agent pref -> global default pref ->
    FORGE_CHAT_MODEL env -> hardcoded Claude Sonnet."""
    d = _load_prefs()
    if agent:
        a = (d.get("agents") or {}).get(agent)
        if a:
            return a
    return d.get("default") or DEFAULT_MODEL


def set_model(model, agent=None):
    """Persist a model choice — global (agent=None) or per-agent. Additive: an
    empty/unknown value is rejected, never crashes the store."""
    model = (model or "").strip()
    if not model:
        return {"error": "model required"}
    with _LOCK:
        d = _load_prefs()
        if agent:
            d.setdefault("agents", {})[agent] = model
        else:
            d["default"] = model
        _save_prefs(d)
    return {"ok": True, "model": model, "agent": agent}


# ── Codex CLI (ChatGPT subscription) ─────────────────────────────────────────────
def _codex_home():
    return os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")


def codex_bin():
    """Resolve the codex executable: FORGE_CODEX_BIN -> PATH -> common install dirs.
    Returns None when not installed."""
    b = os.environ.get("FORGE_CODEX_BIN")
    if b and Path(b).exists():
        return b
    for name in ("codex", "codex.cmd", "codex.exe"):
        p = shutil.which(name)
        if p:
            return p
    candidates = [
        Path.home() / ".local" / "bin" / "codex",
        Path(os.environ.get("APPDATA", "")) / "npm" / "codex.cmd",
        Path("/usr/local/bin/codex"),
        Path("/usr/bin/codex"),
    ]
    for c in candidates:
        try:
            if str(c) and c.exists():
                return str(c)
        except Exception:
            pass
    return None


def codex_logged_in():
    try:
        return (Path(_codex_home()) / "auth.json").exists()
    except Exception:
        return False


def codex_available():
    return bool(codex_bin()) and codex_logged_in()


def _codex_model(model):
    """Extract the -m value from a codex model string. 'codex' (bare) -> None
    (let the Codex config default, e.g. gpt-5.5, apply)."""
    m = (model or "").strip()
    low = m.lower()
    if low.startswith("codex:"):
        return m.split(":", 1)[1].strip() or None
    if low == "codex":
        return None
    if low.startswith("gpt"):
        return m
    return None


def _run_codex(model, system, user, timeout=150):
    """Run `codex exec` non-interactively and return its final message.

    Read-only sandbox + --skip-git-repo-check so it answers the prompt without
    touching files or needing a git repo. Prompt goes in on stdin (no shell
    escaping); the final message is captured with -o.
    """
    bin_ = codex_bin()
    if not bin_:
        raise RuntimeError("Codex CLI not found")
    mdl = _codex_model(model)
    body = ((system or "").strip() + "\n\n" + (user or "").strip()).strip()
    prompt = ("You are answering a chat message directly and concisely, in the "
              "persona and with the context described below. Do not modify files "
              "or run tools — just reply.\n\n" + body)
    with tempfile.TemporaryDirectory() as td:
        out_file = Path(td) / "last.txt"
        cmd = [bin_, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
               "-o", str(out_file)]
        if mdl:
            cmd += ["-m", mdl]
        cmd += ["-"]  # prompt from stdin
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True,
                                  text=True, timeout=timeout, cwd=td,
                                  env=dict(os.environ))
        except FileNotFoundError:
            raise RuntimeError("Codex CLI not found")
        except subprocess.TimeoutExpired:
            raise RuntimeError("ChatGPT (Codex) timed out")
        try:
            if out_file.exists():
                txt = out_file.read_text(errors="replace").strip()
                if txt:
                    return txt
        except Exception:
            pass
        out = (proc.stdout or "").strip()
        if not out:
            err = (proc.stderr or "").strip()[-400:]
            raise RuntimeError(
                f"Codex exec returned nothing (exit {proc.returncode})"
                + (f": {err}" if err else ""))
        return out


# ── OpenAI-compatible HTTP (dormant until a key/base is configured) ──────────────
def _openai_base():
    return (os.environ.get("FORGE_OPENAI_BASE")
            or "https://api.openai.com/v1").rstrip("/")


def _openai_ready():
    return bool(os.environ.get("OPENAI_API_KEY"))


def _run_openai(model, system, user, max_tokens):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    mdl = model.split(":", 1)[1].strip() if ":" in model else model
    payload = {
        "model": mdl or "gpt-4o-mini",
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system or ""},
                     {"role": "user", "content": user or ""}],
    }
    req = urllib.request.Request(
        _openai_base() + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key,
                 "content-type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            msg = (body.get("error") or {}).get("message") or str(e)
        except Exception:
            msg = str(e)
        raise RuntimeError(f"OpenAI API error ({e.code}): {msg}") from None
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI returned no choices")
    return (choices[0].get("message") or {}).get("content", "").strip()


# ── availability + gating (for the UI + the chat handlers) ───────────────────────
def can_serve_without_anthropic(agent=None, model=None):
    """True when the resolved provider can answer with NO Anthropic key —
    i.e. Codex or OpenAI is actually ready."""
    prov = provider_of(model or model_for(agent))
    if prov == "codex":
        return codex_available()
    if prov == "openai":
        return _openai_ready()
    return False


def needs_key(agent=None, model=None):
    """The chat handler's needsKey gate: only require an Anthropic key when we
    can't serve the selected model another way."""
    return not can_serve_without_anthropic(agent, model)


def available(agent=None):
    """Provider/model status for the picker. No secrets — presence flags only."""
    anth = False
    try:
        anth = bool(review_agent._api_key())
    except Exception:
        pass
    cbin = codex_bin()
    cauth = codex_logged_in()
    providers = [
        {"id": "anthropic", "label": "Claude (Anthropic)", "ready": anth,
         "note": "connected" if anth else "no ANTHROPIC_API_KEY",
         "models": CATALOG["anthropic"]},
        {"id": "codex", "label": "ChatGPT — Codex CLI (your subscription)",
         "ready": bool(cbin and cauth),
         "note": ("connected" if (cbin and cauth)
                  else ("not logged in — run: codex login" if cbin
                        else "Codex CLI not installed on this machine")),
         "models": CATALOG["codex"]},
    ]
    if _openai_ready():
        providers.append({"id": "openai", "label": "OpenAI API", "ready": True,
                          "note": "API key set", "models": []})
    return {"providers": providers,
            "default": global_default(),
            "current": model_for(agent),
            "agent": agent}


# ── the one entry point chat handlers call ───────────────────────────────────────
def complete(system, user, max_tokens=1200, agent=None, key=None, tools=None,
             model=None):
    """Route a single completion. Backward-compatible: with an Anthropic model
    (the default) this is exactly `review_agent._claude(key, system, user, ...)`.

    On a Codex/OpenAI failure it falls back to Claude when a `key` is available,
    so a chat never dies just because the alternate provider hiccuped.
    """
    mdl = model or model_for(agent)
    prov = provider_of(mdl)

    if prov == "codex":
        if codex_available():
            try:
                return _run_codex(mdl, system, user)
            except Exception:
                if key:
                    return review_agent._claude(key, system, user,
                                                max_tokens=max_tokens, tools=tools)
                raise
        if key:  # picked Codex but it's not set up here — Claude still answers
            return review_agent._claude(key, system, user, max_tokens=max_tokens,
                                        tools=tools)
        raise RuntimeError("ChatGPT (Codex) isn't set up on this machine, and "
                           "there's no Claude key to fall back to.")

    if prov == "openai":
        if _openai_ready():
            try:
                return _run_openai(mdl, system, user, max_tokens)
            except Exception:
                if key:
                    return review_agent._claude(key, system, user,
                                                max_tokens=max_tokens, tools=tools)
                raise
        if key:
            return review_agent._claude(key, system, user, max_tokens=max_tokens,
                                        tools=tools)
        raise RuntimeError("OpenAI provider isn't configured (no OPENAI_API_KEY).")

    # anthropic (default) — unchanged behavior
    return review_agent._claude(key, system, user, max_tokens=max_tokens, tools=tools)
