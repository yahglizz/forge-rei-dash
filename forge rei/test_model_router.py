"""test_model_router.py — offline unit tests for the multi-model router.

No network, no real Codex. We monkeypatch `review_agent._claude`, the codex
availability probes, and `_run_codex` to prove the ROUTING + FALLBACK logic:
  • default/unknown model -> Anthropic path (unchanged behavior)
  • codex model, codex available -> codex path, no Anthropic call
  • codex model, codex down, key present -> falls back to Claude
  • codex model, codex down, no key -> raises (handler turns it into an error msg)
  • needs_key() gates the handler's needsKey return correctly
  • prefs round-trip (global + per-agent) resolves as expected

Run: python3 test_model_router.py   (from the `forge rei/` folder)
"""
import os
import sys
import tempfile
from pathlib import Path

import model_router as mr
import review_agent


def _reset_prefs(tmp):
    mr.PREFS = Path(tmp) / "model_prefs.json"


def test_provider_of():
    assert mr.provider_of("claude-sonnet-4-5") == "anthropic"
    assert mr.provider_of("") == "anthropic"
    assert mr.provider_of(None) == "anthropic"
    assert mr.provider_of("codex") == "codex"
    assert mr.provider_of("codex:gpt-5.5") == "codex"
    assert mr.provider_of("gpt-5.5") == "codex"
    assert mr.provider_of("openai:gpt-4o") == "openai"


def test_codex_model_extract():
    assert mr._codex_model("codex") is None
    assert mr._codex_model("codex:gpt-5.5") == "gpt-5.5"
    assert mr._codex_model("gpt-5.5") == "gpt-5.5"


def test_default_routes_to_anthropic(monkeypatch_calls):
    # No model set -> Anthropic path, calling _claude verbatim.
    mr.complete("SYS", "USER", agent="scout", key="k-123")
    assert monkeypatch_calls["claude"] == [("k-123", "SYS", "USER")]
    assert monkeypatch_calls["codex"] == []


def test_codex_when_available(monkeypatch_calls):
    mr.set_model("codex:gpt-5.5", agent="scout")
    out = mr.complete("SYS", "USER", agent="scout", key="k-123")
    assert out == "CODEX_OK"
    assert monkeypatch_calls["codex"] == ["codex:gpt-5.5"]
    assert monkeypatch_calls["claude"] == []  # codex answered; no Claude call


def test_codex_down_falls_back_to_claude(monkeypatch_calls, make_codex_fail):
    mr.set_model("codex:gpt-5.5", agent="scout")
    make_codex_fail()
    mr.complete("SYS", "USER", agent="scout", key="k-123")
    # codex was attempted, then Claude answered
    assert monkeypatch_calls["claude"] == [("k-123", "SYS", "USER")]


def test_codex_down_no_key_raises(monkeypatch_calls, make_codex_fail):
    mr.set_model("codex:gpt-5.5", agent="scout")
    make_codex_fail()
    try:
        mr.complete("SYS", "USER", agent="scout", key=None)
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError when codex fails with no key")


def test_needs_key(monkeypatch, tmp):
    _reset_prefs(tmp)
    # codex available -> can serve without an Anthropic key
    monkeypatch(mr, "codex_available", lambda: True)
    mr.set_model("codex:gpt-5.5", agent="scout")
    assert mr.needs_key("scout") is False
    # codex down -> we DO need the Anthropic key
    monkeypatch(mr, "codex_available", lambda: False)
    assert mr.needs_key("scout") is True
    # anthropic model always needs the key
    mr.set_model("claude-sonnet-4-5", agent="scout")
    assert mr.needs_key("scout") is True


def test_prefs_roundtrip(tmp):
    _reset_prefs(tmp)
    assert mr.model_for("scout") == mr.DEFAULT_MODEL          # nothing set yet
    mr.set_model("codex", None)                               # global default
    assert mr.model_for("atlas") == "codex"
    mr.set_model("claude-opus-4-1", "atlas")                  # per-agent override
    assert mr.model_for("atlas") == "claude-opus-4-1"
    assert mr.model_for("scout") == "codex"                   # still the global


# ── tiny test harness (no pytest dependency; matches this repo's style) ──────────
def _run():
    tmp = tempfile.mkdtemp()
    _reset_prefs(tmp)

    calls = {"claude": [], "codex": []}
    _orig_claude = review_agent._claude
    _orig_codex_avail = mr.codex_available
    _orig_run_codex = mr._run_codex
    _patches = []

    def monkeypatch(obj, name, val):
        _patches.append((obj, name, getattr(obj, name)))
        setattr(obj, name, val)

    # default stubs
    review_agent._claude = lambda key, system, user, max_tokens=1200, tools=None: (
        calls["claude"].append((key, system, user)) or "CLAUDE_OK")

    def _fake_codex(model, system, user, timeout=150):
        calls["codex"].append(model)
        return "CODEX_OK"
    mr._run_codex = _fake_codex
    mr.codex_available = lambda: True

    def make_codex_fail():
        def _boom(model, system, user, timeout=150):
            calls["codex"].append(model)
            raise RuntimeError("codex boom")
        mr._run_codex = _boom

    fixtures = {
        "monkeypatch_calls": calls,
        "monkeypatch": monkeypatch,
        "tmp": tmp,
        "make_codex_fail": make_codex_fail,
    }

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        # fresh prefs dir per test (also the `tmp` fixture) so no state leaks between them
        fixtures["tmp"] = tempfile.mkdtemp()
        _reset_prefs(fixtures["tmp"])
        calls["claude"].clear()
        calls["codex"].clear()
        mr._run_codex = _fake_codex
        mr.codex_available = lambda: True
        import inspect
        kwargs = {p: fixtures[p] for p in inspect.signature(t).parameters if p in fixtures}
        try:
            t(**kwargs)
            print(f"  ok  {t.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {t.__name__}: {e}")
            raise
        finally:
            for obj, name, val in reversed(_patches):
                setattr(obj, name, val)
            _patches.clear()

    # restore
    review_agent._claude = _orig_claude
    mr.codex_available = _orig_codex_avail
    mr._run_codex = _orig_run_codex
    print(f"\n{passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
