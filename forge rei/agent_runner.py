#!/usr/bin/env python3
"""agent_runner.py — one agent job in one short-lived process.

agent_gateway.py spawns this with cwd = the agent's own folder and an env holding only one
Anthropic key + a per-job token, so "runs from its folder" and "sees only its own key" are facts
of the process, not comments. It reads its instruction files RELATIVE TO THAT CWD and reports
exactly what it read (path, sha256, chars). A missing file or an oversized set fails the job —
never a silent cut.

It holds no tool logic and no business credentials: every tool call goes back to the connector
(POST /api/gateway/tool), where scope, deny lists, taint and tap cards already live. It writes no
shared state; usage, cards and receipts go back through the result file.

Self-check: python3 test_agent_gateway.py
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import review_agent

MAX_FOLDER_CHARS = 60000
TOOL_TIMEOUT = 120
_SECRET_NAME = re.compile(r"key|token|secret|password|auth", re.I)


class JobError(Exception):
    pass


def load_files(rels, root):
    """-> (prompt text, receipts). Paths are relative to the cwd and stay inside `root`."""
    root, cwd = Path(root).resolve(), Path.cwd().resolve()
    blocks, receipts, total = [], [], 0
    for rel in rels:
        path = (cwd / rel).resolve()
        if root not in path.parents:
            raise JobError(f"instruction file outside the agent root: {rel}")
        try:
            raw = path.read_bytes()
        except OSError:
            raise JobError(f"instruction file missing: {rel}") from None
        text = raw.decode("utf-8", "replace")
        total += len(text)
        if total > MAX_FOLDER_CHARS:
            raise JobError(f"instruction files over {MAX_FOLDER_CHARS} chars at {rel}")
        blocks.append(f"\n\n--- {rel} ---\n{text}")
        receipts.append({"path": str(path.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest(),
                         "chars": len(text)})
    return "".join(blocks), receipts


def call_tool(spec, name, inp):
    req = urllib.request.Request(
        f"http://127.0.0.1:{spec['port']}/api/gateway/tool",
        data=json.dumps({"name": name, "input": inp}).encode(),
        headers={"Content-Type": "application/json", "X-Job-Token": os.environ["FORGE_JOB_TOKEN"]},
        method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=TOOL_TIMEOUT) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"result": f"tool refused (HTTP {e.code})", "refused": True}
    except Exception as e:  # noqa: BLE001 — the model sees the failure and says so
        return {"result": f"tool failed: {e}", "refused": True}


def call_model(spec, payload):
    req = urllib.request.Request(
        spec.get("api_url") or "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={"x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        method="POST")
    try:
        return review_agent.claude_urlopen(req, review_agent.call_timeout(payload["max_tokens"]))
    except urllib.error.HTTPError as e:
        try:
            msg = (json.loads(e.read().decode()).get("error") or {}).get("message") or str(e)
        except Exception:  # noqa: BLE001
            msg = str(e)
        err = JobError(f"Anthropic API error ({e.code}): {msg}")
        err.code = e.code
        raise err from None


def _run_turn(spec, system, model, extra, out):
    """One model's tool loop, from the job's original messages. review_agent.ESCALATED = start over."""
    msgs, last = list(spec["messages"]), spec["max_turns"]
    for turn in range(last + 1):
        payload = {"model": model, "system": system, "messages": msgs, "tools": spec["tools"] + extra,
                   **review_agent.thinking_params(model, spec["max_tokens"], "low")}
        if turn == last:                       # cap: answer from what was read, no more tools
            payload["tool_choice"] = {"type": "none"}
        data = call_model(spec, payload)
        out["modelCalled"], out["model"] = True, model
        out["turns"] += 1
        u = data.get("usage") or {}
        call = {"in": int(u.get("input_tokens") or 0), "out": int(u.get("output_tokens") or 0),
                "cacheWrite": int(u.get("cache_creation_input_tokens") or 0),
                "cacheRead": int(u.get("cache_read_input_tokens") or 0)}
        for k, v in call.items():
            out["usage"][k] += v
        out["calls"].append({"model": model, **call})      # priced per request: the rate depends on its size
        content = data.get("content") or []
        said = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        uses = [b for b in content if b.get("type") == "tool_use"]
        final = not uses or turn == last or data.get("stop_reason") in ("max_tokens", "refusal")
        if extra and review_agent.hand_up(uses, said, final):
            out["escalated"] = True
            return review_agent.ESCALATED
        if final:
            out["reply"], out["stop"] = said, data.get("stop_reason")
            return out
        msgs.append({"role": "assistant", "content": content})
        results = []
        for use in uses:
            res = call_tool(spec, use["name"], use.get("input") or {})
            out["tools"].append({"name": use["name"], "path": str((use.get("input") or {}).get("path") or ""),
                                 "ok": not (res.get("refused") or res.get("failed"))})
            results.append({"type": "tool_result", "tool_use_id": use["id"],
                            "content": "<data>" + str(res.get("result") or "") + "</data>"})
        msgs.append({"role": "user", "content": results})


def run(spec):
    folder_text, files = load_files(spec["files"], spec["root"])
    out = {"cwd": str(Path.cwd().resolve()), "files": files, "reply": "", "tools": [],
           "usage": {"in": 0, "out": 0, "cacheWrite": 0, "cacheRead": 0}, "calls": [], "turns": 0,
           "modelCalled": False, "escalated": False,
           "secretEnvNames": sorted(k for k in os.environ if _SECRET_NAME.search(k))}
    system = [{"type": "text", "cache_control": {"type": "ephemeral"},
               "text": spec["head"] + "\n\n=== YOUR FOLDER FILES (read from " + out["cwd"] + ") ==="
               + folder_text + spec["tail"]}]
    out["systemChars"] = len(system[0]["text"])
    review_agent.routed(lambda model, extra: _run_turn(spec, system, model, extra, out), spec["models"])
    if spec.get("foreign_probe"):              # the isolation check runs in code, not on the model's word
        probe = call_tool(spec, "api_get", {"path": spec["foreign_probe"]})
        out["foreignProbe"] = {"path": spec["foreign_probe"], "refused": bool(probe.get("refused"))}
    return out


def main():
    os.umask(0o077)
    spec = json.loads(Path(sys.argv[1]).read_text())
    try:
        out = run(spec)
    except JobError as e:
        out = {"error": str(e)[:400], "errorCode": getattr(e, "code", None)}
    except Exception as e:  # noqa: BLE001 — a transient network failure is a job failure, not a traceback
        out = {"error": f"{type(e).__name__}: {e}"[:400]}
    tmp = Path(spec["result_path"] + ".tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, spec["result_path"])


if __name__ == "__main__":
    main()
