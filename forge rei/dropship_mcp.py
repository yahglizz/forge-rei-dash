#!/usr/bin/env python3
"""dropship_mcp.py — MCP (Model Context Protocol) client for FORGE Dropship.

The connector's own way of talking to an MCP server over **Streamable HTTP**, so the
dashboard can answer "is this MCP actually up, and what can it do?" without a Claude
session in the loop. Stdlib only (urllib + retry), same shape as ``dropship_shopify``
/ ``dropship_autods`` / ``stripe_io``.

WHAT IT DOES
  • ``probe(server)``  — full handshake: ``initialize`` → ``notifications/initialized``
    → ``tools/list``. Returns the server's own name/version, the negotiated protocol
    version, and its REAL tool list. Never a fabricated tool — an unconfigured server
    returns a clean "add URL" result and a failing one returns an honest error.
  • ``call(server, tool, args, actor)`` — invokes a tool.

AUTONOMY (root CLAUDE.md rule 2)
  ``call()`` refuses unless ``actor == "operator"``. No agent, loop, or engine in this
  codebase has a code path to it — it is reachable ONLY from the connector's
  operator-facing POST route, which the dashboard fires behind a confirm dialog. The
  dialog IS the approval gate (same class as the daycare "Text" button). Every call
  leaves a receipt on the agent bus + ``marcus_state/dropship_mcp_log.json``.

SECRETS (rule 4)
  A server record stores the *name* of an env var (``authEnv``), never a token. The
  value is read from ``dropship.env`` via ``dropship_env.get()`` at call time and is
  never returned to the browser — callers surface presence only.

TRANSPORTS
  ``http``  — Streamable HTTP JSON-RPC. Fully supported (probe + call).
  ``stdio`` — e.g. ``npx -y @shopify/dev-mcp@latest``. NOT reachable from the connector
  process; stored for reference and reported as ``transport_unsupported`` so the UI can
  render it honestly as an operator/Claude-session tool instead of pretending it's down.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import dropship_env
import forge_atomic

HERE = Path(__file__).resolve().parent
LOG = HERE / "marcus_state" / "dropship_mcp_log.json"
_LOG_LOCK = threading.Lock()
MAX_LOG = 100

_TIMEOUT = 25
_RETRIES = 1
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "forge-dropship-connector", "version": "1.0.0"}

# Tools whose name starts with one of these read like a read. Surfaced to the UI so it
# knows which invocations deserve the red confirm dialog. Advisory only — the operator
# confirm is the real gate, and anything not matching is treated as a write.
_READ_PREFIXES = ("search_", "get_", "list_", "read_", "fetch_", "find_", "query_")


class McpError(Exception):
    def __init__(self, status: int, message: str, code: str = "mcp_error"):
        super().__init__(message)
        self.status = int(status)
        self.message = message
        self.code = code


# ---------------------------------------------------------------------------
# server record helpers
# ---------------------------------------------------------------------------

def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def transport(server: dict) -> str:
    t = _s((server or {}).get("transport")).lower()
    return t if t in ("http", "stdio") else "http"


def url_of(server: dict) -> str:
    return _s((server or {}).get("url"))


def auth_env(server: dict) -> str:
    return _s((server or {}).get("authEnv"))


def has_auth(server: dict) -> bool:
    """Presence only — is the referenced env var actually set? Never the value."""
    name = auth_env(server)
    return bool(name and _s(dropship_env.get(name, "")))


def configured(server: dict) -> bool:
    """True when this server could be reached right now. An authEnv that names a var
    with no value counts as NOT configured — better an honest "add key" than a 401."""
    if transport(server) != "http":
        return False
    if not url_of(server):
        return False
    if auth_env(server) and not has_auth(server):
        return False
    return True


def is_read_only(tool_name: str) -> bool:
    return _s(tool_name).lower().startswith(_READ_PREFIXES)


def _not_configured(server: dict) -> dict:
    t = transport(server)
    if t == "stdio":
        return {
            "ok": True, "configured": False, "connected": False,
            "code": "transport_unsupported",
            "detail": "stdio server — runs in your Claude/operator session, not on the box.",
            "tools": [],
        }
    if not url_of(server):
        return {"ok": True, "configured": False, "connected": False,
                "code": "no_url", "detail": "Add the MCP server URL.", "tools": []}
    return {"ok": True, "configured": False, "connected": False,
            "code": "no_auth",
            "detail": f"Set {auth_env(server)} in dropship.env.", "tools": []}


# ---------------------------------------------------------------------------
# transport — Streamable HTTP JSON-RPC (plain JSON or SSE-framed responses)
# ---------------------------------------------------------------------------

def parse_sse(raw: str, want_id):
    """Pull the JSON-RPC message for ``want_id`` out of an SSE body.

    Streamable HTTP servers may answer a POST with ``text/event-stream`` instead of
    ``application/json``; the payload is one or more ``data:`` lines. Returns the
    matching message dict, or None.
    """
    fallback = None
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            msg = json.loads(chunk)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("id") == want_id:
            return msg
        if fallback is None and ("result" in msg or "error" in msg):
            fallback = msg
    return fallback


def _headers(server: dict, session_id: str = "", initialized: bool = False) -> dict:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    name = auth_env(server)
    if name:
        token = _s(dropship_env.get(name, ""))
        if token:
            scheme = _s(server.get("authScheme")) or "Bearer"
            header = _s(server.get("authHeader")) or "Authorization"
            h[header] = token if header.lower() != "authorization" else f"{scheme} {token}"
    if session_id:
        h["Mcp-Session-Id"] = session_id
    if initialized:
        h["MCP-Protocol-Version"] = PROTOCOL_VERSION
    return h


def _rpc(server: dict, method: str, params: dict | None, req_id,
         session_id: str = "", initialized: bool = False):
    """One JSON-RPC round trip. Returns (result, session_id). req_id=None → notification
    (no response expected, servers answer 202 with an empty body)."""
    url = url_of(server)
    if not url:
        raise McpError(503, "MCP server has no URL", "no_url")
    payload: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    if req_id is not None:
        payload["id"] = req_id
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(_RETRIES + 1):
        request = urllib.request.Request(
            url, data=body, headers=_headers(server, session_id, initialized), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                sid = response.headers.get("Mcp-Session-Id") or session_id
                raw = response.read().decode("utf-8", "replace")
                ctype = (response.headers.get("Content-Type") or "").lower()
                if req_id is None:
                    return None, sid
                if "text/event-stream" in ctype:
                    msg = parse_sse(raw, req_id)
                else:
                    try:
                        msg = json.loads(raw) if raw.strip() else None
                    except ValueError:
                        msg = parse_sse(raw, req_id)
                if not isinstance(msg, dict):
                    raise McpError(502, f"MCP server returned no result for {method}",
                                   "bad_response")
                if msg.get("error"):
                    err = msg["error"] or {}
                    raise McpError(502, str(err.get("message") or "MCP error")[:300],
                                   "rpc_error")
                return msg.get("result") or {}, sid
        except urllib.error.HTTPError as error:
            detail = f"MCP request failed ({error.code})"
            try:
                payload_err = json.loads(error.read().decode("utf-8", "replace"))
                got = (payload_err.get("error") or {}).get("message")
                if got:
                    detail = str(got)[:300]
            except Exception:  # noqa: BLE001 — never leak a raw body
                pass
            if error.code in (429, 500, 502, 503, 504) and attempt < _RETRIES:
                time.sleep(0.6 * (attempt + 1))
                last_error = error
                continue
            if error.code in (401, 403):
                raise McpError(error.code, detail, "unauthorized") from None
            raise McpError(error.code, detail, "http_error") from None
        except McpError:
            raise
        except Exception as error:  # noqa: BLE001 — urllib/timeout/DNS
            last_error = error
            if attempt < _RETRIES:
                time.sleep(0.6 * (attempt + 1))
                continue
    raise McpError(502, "MCP server is unreachable", "unreachable") from last_error


def _connect(server: dict):
    """initialize → notifications/initialized. Returns (initResult, sessionId)."""
    result, sid = _rpc(server, "initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": CLIENT_INFO,
    }, 1)
    try:
        _rpc(server, "notifications/initialized", {}, None, sid, initialized=True)
    except McpError:
        pass  # some servers 4xx the notification; the session is still usable
    return result or {}, sid


def _slim_tool(t: dict) -> dict:
    name = _s(t.get("name"))
    return {
        "name": name,
        "title": _s(t.get("title")),
        "description": _s(t.get("description"))[:400],
        "inputSchema": t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {},
        "readOnly": is_read_only(name),
    }


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def probe(server: dict) -> dict:
    """Handshake + tools/list. Honest result always — never invented tools."""
    if not isinstance(server, dict):
        return {"ok": False, "connected": False, "error": "server record required",
                "tools": []}
    if not configured(server):
        return _not_configured(server)
    try:
        info, sid = _connect(server)
        result, _ = _rpc(server, "tools/list", {}, 2, sid, initialized=True)
        raw_tools = (result or {}).get("tools")
        tools = [_slim_tool(t) for t in raw_tools if isinstance(t, dict)] \
            if isinstance(raw_tools, list) else []
        return {
            "ok": True, "configured": True, "connected": True,
            "serverInfo": info.get("serverInfo") or {},
            "protocolVersion": info.get("protocolVersion") or "",
            "instructions": _s(info.get("instructions"))[:600],
            "tools": tools,
            "toolCount": len(tools),
            "ts": int(time.time() * 1000),
        }
    except McpError as e:
        return {"ok": False, "configured": True, "connected": False,
                "error": e.message, "code": e.code, "tools": [],
                "ts": int(time.time() * 1000)}


def call(server: dict, tool: str, args: dict | None = None,
         actor: str = "") -> dict:
    """Invoke an MCP tool. OPERATOR ONLY (rule 2) — the dashboard's confirm dialog is
    the approval gate; no agent or background loop can reach this."""
    if actor != "operator":
        return {"ok": False, "error": "MCP tool calls are operator-initiated only.",
                "code": "operator_only"}
    tool = _s(tool)
    if not tool:
        return {"ok": False, "error": "tool name required", "code": "bad_request"}
    if not isinstance(server, dict):
        return {"ok": False, "error": "server record required", "code": "bad_request"}
    if not configured(server):
        out = _not_configured(server)
        out["ok"] = False
        return out
    args = args if isinstance(args, dict) else {}
    started = int(time.time() * 1000)
    try:
        _, sid = _connect(server)
        result, _ = _rpc(server, "tools/call", {"name": tool, "arguments": args}, 3,
                         sid, initialized=True)
        out = {"ok": True, "tool": tool, "readOnly": is_read_only(tool),
               "result": result or {}, "ts": started}
    except McpError as e:
        out = {"ok": False, "tool": tool, "readOnly": is_read_only(tool),
               "error": e.message, "code": e.code, "ts": started}
    _receipt(server, tool, args, out)
    return out


# ---------------------------------------------------------------------------
# receipts — every operator invocation is logged + broadcast
# ---------------------------------------------------------------------------

def _receipt(server: dict, tool: str, args: dict, out: dict) -> None:
    entry = {
        "ts": out.get("ts") or int(time.time() * 1000),
        "server": _s(server.get("id")) or _s(server.get("name")),
        "tool": tool,
        "readOnly": bool(out.get("readOnly")),
        "ok": bool(out.get("ok")),
        "error": _s(out.get("error"))[:200],
        "args": _redact(args),
        "actor": "operator",
    }
    try:
        with _LOG_LOCK:
            rows = []
            if LOG.exists():
                try:
                    rows = json.loads(LOG.read_text())
                except Exception:  # noqa: BLE001
                    rows = []
            rows = rows if isinstance(rows, list) else []
            rows.insert(0, entry)
            forge_atomic.atomic_write_json(LOG, rows[:MAX_LOG])
    except Exception:  # noqa: BLE001 — a receipt must never break the call
        pass
    try:
        import agent_bus
        verb = "ran" if entry["ok"] else "failed to run"
        agent_bus.send("midas", "all", "note",
                       f"Operator {verb} MCP tool `{tool}` on {entry['server']}"
                       + ("" if entry["ok"] else f" — {entry['error']}"),
                       {"kind": "mcp_call", **entry})
    except Exception:  # noqa: BLE001
        pass


def _redact(args: dict) -> dict:
    """Args go into a log — strip anything that smells like a credential."""
    out = {}
    for k, v in (args or {}).items():
        if any(s in str(k).lower() for s in ("token", "secret", "key", "password", "auth")):
            out[k] = "***"
        else:
            out[k] = (v if not isinstance(v, str) else v[:200])
    return out


def recent(limit: int = 25) -> list:
    try:
        rows = json.loads(LOG.read_text()) if LOG.exists() else []
        return rows[:limit] if isinstance(rows, list) else []
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# self-check — python3 dropship_mcp.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sse = ('event: message\n'
           'data: {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"search_shop_catalog"}]}}\n\n')
    got = parse_sse(sse, 2)
    assert got and got["result"]["tools"][0]["name"] == "search_shop_catalog", got
    assert parse_sse("data: not-json\n", 2) is None
    # id mismatch still yields the only real response (servers that renumber)
    assert parse_sse('data: {"jsonrpc":"2.0","id":9,"result":{}}\n', 2)["id"] == 9

    assert is_read_only("search_shop_catalog") and is_read_only("get_cart")
    assert not is_read_only("update_cart")

    # unconfigured → clean add-key result, NEVER a fabricated tool list
    for rec in ({"transport": "http", "url": ""},
                {"transport": "stdio", "command": "npx -y @shopify/dev-mcp@latest"},
                {"transport": "http", "url": "https://x/api/mcp", "authEnv": "NOPE_MISSING"}):
        r = probe(rec)
        assert r["connected"] is False and r["tools"] == [], r
        assert r.get("code") in ("no_url", "transport_unsupported", "no_auth"), r

    # a non-operator can never invoke a tool (rule 2)
    denied = call({"transport": "http", "url": "https://x/api/mcp"}, "update_cart",
                  {}, actor="midas")
    assert denied["ok"] is False and denied["code"] == "operator_only", denied

    assert _redact({"query": "mug", "api_token": "shpat_live"})["api_token"] == "***"
    print("dropship_mcp self-check OK")
