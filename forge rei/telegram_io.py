"""telegram_io.py — Telegram alerts + tap-to-approve for FORGE REI OS.

Pushes operator alerts to Telegram (hot lead, warm+ reply-ready for review, weekly
missed sweep, Scout->Marcus handoffs, agency/Dyson+Eco activity) and lets the operator
tap inline buttons to Approve & send / Dismiss / Hand to Marcus — straight from their
phone, no public port. Outbound = sendMessage; inbound = getUpdates long-poll (box-only).

Design (mirrors retell_io.py / review_agent._claude / scout_triage._load_env_file):
  • stdlib only (json, os, time, threading, urllib).
  • Secrets live OUTSIDE the web root: forge-telegram/config/telegram.env, folded into the
    env at import (os.environ.setdefault — real env wins). The token is NEVER served.
  • State (per-event toggles, quiet hours, getUpdates offset, dedupe ring) persists to
    marcus_state/telegram.json behind a threading.Lock.
  • Best-effort everywhere: on_bus_message / send / run_forever NEVER raise; failures are
    swallowed and stored in lastError so the dashboard stays up.

Graceful when no token: configured()->False, settings() still works, send() returns an
error dict, run_forever() returns immediately (no busy spin).
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import forge_heartbeat

HERE = Path(__file__).resolve().parent
TG_DIR = HERE.parent / "forge-telegram"                 # config + .env (outside web root)
STATE = HERE / "marcus_state" / "telegram.json"         # toggles + offset + dedupe
API_BASE = "https://api.telegram.org"

_LOCK = threading.Lock()

# How long a dedupe_key blocks a repeat send (seconds).
_DEDUPE_WINDOW = 15 * 60
# Max dedupe entries kept (ring trim).
_DEDUPE_MAX = 200

# Default per-event toggles + quiet hours — written into STATE on first save/read.
_DEFAULT_TOGGLES = {
    "hot_lead": True,
    "proposal": True,
    "missed_sweep": True,
    "handoff": True,
    "agency": True,
    "edit_request": True,   # new client edit request (agency portal + admin)
    "dyson_plan": True,     # Dyson drafted a plan → approve & ship
}
_DEFAULT_QUIET = {"enabled": False, "start": 22, "end": 7}  # local hour ints

# Callbacks the connector registers (set_actions). action -> callable(arg) -> dict.
_ACTIONS = {}


# ── env load (import-time) ────────────────────────────────────────────────────
def _load_env_file(p):
    """Fold forge-telegram/config/telegram.env into the environment (real env wins)."""
    try:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_env_file(TG_DIR / "config" / "telegram.env")


# ── config resolvers ──────────────────────────────────────────────────────────
def _token():
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def _chat_id():
    return (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()


def _allowed_ids():
    """User ids explicitly allowed to trigger callbacks (TELEGRAM_ALLOWED_IDS comma list)."""
    raw = (os.environ.get("TELEGRAM_ALLOWED_IDS") or "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()]


def _authorized(from_id, chat_id):
    """Authorize a button tap. Two-factor: the message must be in the CONFIGURED chat AND
    the tapper must be allowed. This closes the group hole — in a team group the shared
    chat id is NOT enough; each member's user id must be listed in TELEGRAM_ALLOWED_IDS.

    - Private DM (no allowlist set): allowed only when chat_id == from_id == TELEGRAM_CHAT_ID
      (the operator messaging their own bot).
    - Otherwise: chat_id must equal TELEGRAM_CHAT_ID AND from_id must be in the allowlist.
    Default-deny on anything missing/mismatched.
    """
    from_id, chat_id = str(from_id or ""), str(chat_id or "")
    cid = _chat_id()
    if not cid or not from_id or not chat_id:
        return False
    if chat_id != cid:                      # tap must come from the configured chat
        return False
    allowed = _allowed_ids()
    if allowed:
        return from_id in allowed           # explicit allowlist (required for groups)
    return chat_id == from_id == cid        # personal DM fallback (operator's own chat)


def configured():
    """True only when both a bot token and a chat id are present."""
    return bool(_token()) and bool(_chat_id())


# ── state persistence (threading.Lock, _load/_save) ───────────────────────────
def _load():
    """Load STATE, filling sane defaults. Always returns a usable dict."""
    base = {
        "toggles": dict(_DEFAULT_TOGGLES),
        "quietHours": dict(_DEFAULT_QUIET),
        "offset": 0,            # last consumed getUpdates update_id (alerts bot)
        "agentOffset": 0,       # last consumed update_id for the dedicated agent bot
        "dedupe": {},           # dedupe_key -> epoch seconds last sent
        "lastError": None,
        "lastSentAt": None,
    }
    try:
        if STATE.exists():
            data = json.loads(STATE.read_text())
            if isinstance(data, dict):
                # merge toggles/quietHours so new keys get defaults
                tg = dict(_DEFAULT_TOGGLES)
                tg.update(data.get("toggles") or {})
                base["toggles"] = tg
                qh = dict(_DEFAULT_QUIET)
                qh.update(data.get("quietHours") or {})
                base["quietHours"] = qh
                if isinstance(data.get("offset"), int):
                    base["offset"] = data["offset"]
                if isinstance(data.get("agentOffset"), int):
                    base["agentOffset"] = data["agentOffset"]
                if isinstance(data.get("dedupe"), dict):
                    base["dedupe"] = data["dedupe"]
                base["lastError"] = data.get("lastError")
                base["lastSentAt"] = data.get("lastSentAt")
    except Exception:
        pass
    return base


def _save(state):
    """Persist STATE atomically (tmp + os.replace) so a crash can't corrupt it or strand a
    stale getUpdates offset (which would replay callbacks). Never raises."""
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, STATE)
    except Exception:
        pass


def _redact(s):
    """Strip the bot token from any string before it's stored/returned (errors can contain
    the /bot<TOKEN>/ URL)."""
    s = "" if s is None else str(s)
    for tok in (_token(), _agent_token()):
        if tok and tok in s:
            s = s.replace(tok, "***")
    return s


def _set_error(err):
    """Record a TOKEN-REDACTED lastError without clobbering other state (best-effort)."""
    with _LOCK:
        st = _load()
        st["lastError"] = _redact(err) if err is not None else None
        _save(st)


# ── escaping (HTML parse_mode) ────────────────────────────────────────────────
def _esc(s):
    """Minimal HTML escape so a stray <, >, or & from a seller name/text can't break parse."""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ── Telegram API helper ───────────────────────────────────────────────────────
def _agent_token():
    """Optional SECOND bot dedicated to agent chat (TELEGRAM_AGENT_BOT_TOKEN). When set,
    its own poll loop routes every DM straight to the agents — a clean separate inbox."""
    return (os.environ.get("TELEGRAM_AGENT_BOT_TOKEN") or "").strip()


def _api(method, payload, timeout=15, token=None):
    """POST to the Bot API. Returns the parsed JSON dict. Raises on transport/HTTP error
    (callers catch). `token` overrides the default alerts-bot token (used by the agent bot)."""
    token = token or _token()
    if not token:
        raise RuntimeError("telegram not configured")
    url = f"{API_BASE}/bot{token}/{method}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


# ── public: settings ──────────────────────────────────────────────────────────
def settings():
    """Operator-visible settings. NEVER includes the raw token (only booleans)."""
    with _LOCK:
        st = _load()
    return {
        "configured": configured(),
        "chatSet": bool(_chat_id()),
        "tokenSet": bool(_token()),
        "toggles": st["toggles"],
        "quietHours": st["quietHours"],
        "lastError": st.get("lastError"),
        "lastSentAt": st.get("lastSentAt"),
        "agentBotSet": bool(_agent_token()),
        "agentLoop": dict(_AGENT_LOOP),
    }


def save_settings(body):
    """Merge body.toggles / body.quietHours into STATE; return settings(). Best-effort."""
    body = body if isinstance(body, dict) else {}
    with _LOCK:
        st = _load()
        incoming_toggles = body.get("toggles")
        if isinstance(incoming_toggles, dict):
            for k, v in incoming_toggles.items():
                if k in _DEFAULT_TOGGLES:
                    st["toggles"][k] = bool(v)
        incoming_quiet = body.get("quietHours")
        if isinstance(incoming_quiet, dict):
            qh = st["quietHours"]
            if "enabled" in incoming_quiet:
                qh["enabled"] = bool(incoming_quiet["enabled"])
            for hk in ("start", "end"):
                if hk in incoming_quiet:
                    try:
                        qh[hk] = max(0, min(23, int(incoming_quiet[hk])))
                    except Exception:
                        pass
        _save(st)
    return settings()


# ── public: send ──────────────────────────────────────────────────────────────
def _dedupe_seen(dedupe_key):
    """Read-only: True if dedupe_key was sent within the window. Trims expired entries."""
    if not dedupe_key:
        return False
    now = time.time()
    with _LOCK:
        st = _load()
        ring = {k: v for k, v in (st.get("dedupe") or {}).items()
                if isinstance(v, (int, float)) and (now - v) < _DEDUPE_WINDOW}
        st["dedupe"] = ring
        _save(st)
        return dedupe_key in ring


def _dedupe_commit(dedupe_key):
    """Mark dedupe_key as sent NOW (called only after a successful delivery)."""
    if not dedupe_key:
        return
    now = time.time()
    with _LOCK:
        st = _load()
        ring = {k: v for k, v in (st.get("dedupe") or {}).items()
                if isinstance(v, (int, float)) and (now - v) < _DEDUPE_WINDOW}
        ring[dedupe_key] = now
        if len(ring) > _DEDUPE_MAX:
            ring = dict(sorted(ring.items(), key=lambda kv: kv[1], reverse=True)[:_DEDUPE_MAX])
        st["dedupe"] = ring
        _save(st)


def send(text, buttons=None, dedupe_key=None):
    """Send an HTML message to the configured chat. Returns {ok} or {error}.

    buttons = list[list[{text, callback_data}]] -> inline_keyboard. Dedupe: if dedupe_key
    was sent in the last ~15 min, skip (returns {ok, skipped}). Never raises."""
    if not configured():
        return {"error": "telegram not configured"}
    # dedupe is checked here but only COMMITTED after a successful send, so a transient
    # failure doesn't suppress the retry for the whole window.
    if _dedupe_seen(dedupe_key):
        return {"ok": True, "skipped": "dedupe"}
    payload = {
        "chat_id": _chat_id(),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        resp = _api("sendMessage", payload, timeout=10)
        if not isinstance(resp, dict) or not resp.get("ok", False):
            err = (resp.get("description") if isinstance(resp, dict) else None) or "sendMessage failed"
            _set_error(err)
            return {"error": _redact(err)}
        _dedupe_commit(dedupe_key)
        with _LOCK:
            st = _load()
            st["lastSentAt"] = int(time.time())
            st["lastError"] = None
            _save(st)
        result = resp.get("result") or {}
        return {"ok": True, "messageId": result.get("message_id")}
    except Exception as e:  # noqa: BLE001
        _set_error(e)
        return {"error": _redact(e)}


def send_test():
    """Operator 'Send test' button -> a friendly confirmation message."""
    return send("✅ FORGE REI OS connected to Telegram. Alerts are live.")


# ── public: callback action registry ──────────────────────────────────────────
def set_actions(d):
    """Stash callables for callback dispatch. Keys: approve(pid), mdismiss(pid),
    handoff(conv_id), scoutdismiss(conv_id). Each returns a dict {ok|error}."""
    global _ACTIONS
    if isinstance(d, dict):
        _ACTIONS = dict(d)


# ── event classification + button building ────────────────────────────────────
def _event_class(msg):
    """Map a bus message to an event class, or None to skip."""
    data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
    dtype = data.get("type")
    if dtype in ("hot_lead", "proposal", "missed_sweep", "skill_proposal",
                 "edit_request", "dyson_plan"):
        return dtype
    if msg.get("kind") == "handoff":
        return "handoff"
    if msg.get("from") in ("dyson", "eco"):
        return "agency"
    return None


# Marcus classification -> tier. Only hot/warm get a proposal notification.
_TIER = {
    "READY": "hot", "PRICE": "hot",
    "HELP": "warm", "CONTINUE": "warm",
    "NRN": "nurture", "DNC": "dead",
}


def _proposal_is_warm_or_better(data):
    """Warm-or-better filter for proposals: notify only if tier in {hot,warm}."""
    cls = (data.get("cls") or "").upper()
    tier = _TIER.get(cls)
    # Unknown classification -> default to allowing (don't silently drop a real reply).
    if tier is None:
        return True
    return tier in ("hot", "warm")


def _in_quiet_hours(quiet):
    """True if quiet hours are enabled and the current local hour is inside the window."""
    if not (quiet and quiet.get("enabled")):
        return False
    try:
        start = int(quiet.get("start", 22))
        end = int(quiet.get("end", 7))
    except Exception:
        return False
    hour = time.localtime().tm_hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    # window wraps past midnight (e.g. 22 -> 7)
    return hour >= start or hour < end


def _buttons_for(cls, data):
    """Inline keyboard per event class. None = no buttons."""
    pid = data.get("pid")
    conv = data.get("convId")
    if cls == "proposal" and pid:
        return [
            [{"text": "✅ Approve & send", "callback_data": f"approve:{pid}"}],
            [{"text": "\U0001f5d1 Dismiss", "callback_data": f"mdismiss:{pid}"}],
        ]
    if cls == "hot_lead" and conv:
        return [
            [{"text": "\U0001f91d Hand to Marcus", "callback_data": f"handoff:{conv}"}],
            [{"text": "\U0001f515 Dismiss", "callback_data": f"scoutdismiss:{conv}"}],
        ]
    if cls == "skill_proposal" and pid:
        return [
            [{"text": "✅ Adopt skill", "callback_data": f"skillgo:{pid}"}],
            [{"text": "\U0001f5d1 Dismiss", "callback_data": f"skillno:{pid}"}],
        ]
    if cls == "edit_request":
        rid = data.get("requestId")
        if rid:
            return [
                [{"text": "\U0001f6e0 Plan with Dyson", "callback_data": f"dysonplan:{rid}"}],
                [{"text": "\U0001f5d1 Dismiss", "callback_data": f"reqdismiss:{rid}"}],
            ]
    if cls == "dyson_plan":
        did = data.get("draftId")
        if did:
            return [
                [{"text": "✅ Approve & ship", "callback_data": f"dysongo:{did}"}],
                [{"text": "\U0001f5d1 Reject", "callback_data": f"dysonno:{did}"}],
            ]
    return None


def _compose_agency_text(msg, data):
    """HTML message for agency edit-request events (new request / Dyson plan)."""
    dtype = data.get("type")
    parts = [_esc(msg.get("text") or "")]
    client = data.get("client")
    title = data.get("title")
    meta = []
    if client:
        meta.append(f"<b>{_esc(client)}</b>")
    if data.get("reqType"):
        meta.append(_esc(data.get("reqType")))
    if data.get("priority"):
        meta.append(_esc(str(data.get("priority")).title()))
    if data.get("risk"):
        meta.append(f"{_esc(str(data.get('risk')).title())} risk")
    if meta:
        parts.append(" · ".join(meta))
    if title:
        parts.append(f"📝 <b>{_esc(str(title)[:200])}</b>")
    if dtype == "edit_request" and data.get("detail"):
        parts.append(f"\"{_esc(str(data.get('detail'))[:400])}\"")
    if dtype == "dyson_plan":
        reco = data.get("recommendation")
        if reco:
            who = ("🤖 <b>Agent can handle this</b>" if reco == "agent"
                   else "👤 <b>Recommend you do this one</b>")
            rr = data.get("recommendationReason")
            parts.append(who + (f" — {_esc(str(rr)[:200])}" if rr else ""))
        n = data.get("filesCount") or 0
        if n:
            changed = data.get("changedFiles") or []
            flist = (": " + _esc(", ".join(changed[:4]))) if changed else ""
            parts.append(f"✍️ <b>{n} file(s) written</b>{flist} — tap Approve to open the PR.")
        if data.get("summary"):
            parts.append(_esc(str(data.get("summary"))[:300]))
        steps = data.get("steps") or []
        if steps:
            body = "\n".join(f"{i+1}. {_esc(str(s)[:120])}" for i, s in enumerate(steps[:6]))
            parts.append(f"<b>Plan:</b>\n{body}")
    return "\n\n".join(p for p in parts if p)


def _compose_text(msg, data):
    """Clean HTML message: headline + name/phone, the SELLER'S message that triggered this,
    and (for a reply proposal) Marcus's drafted reply so the operator can approve in context."""
    if data.get("type") in ("edit_request", "dyson_plan"):
        return _compose_agency_text(msg, data)
    parts = [_esc(msg.get("text") or "")]
    name = data.get("name")
    phone = data.get("phone")
    detail = []
    if name:
        detail.append(f"<b>{_esc(name)}</b>")
    if phone:
        detail.append(_esc(phone))
    if detail:
        parts.append(" · ".join(detail))
    # what the seller actually said (the trigger) — inbound (proposal) or lastMessage (hot lead)
    said = data.get("inbound") or data.get("lastMessage")
    if said:
        parts.append(f"💬 <b>Seller:</b> \"{_esc(str(said)[:400])}\"")
    # the draft you'd be approving (reply proposals only)
    reply = data.get("reply")
    if reply:
        parts.append(f"✍️ <b>Marcus's draft:</b> \"{_esc(str(reply)[:400])}\"")
    return "\n\n".join(p for p in parts if p)


# ── public: the bus tap ───────────────────────────────────────────────────────
def on_bus_message(msg):
    """Best-effort bus tap: filter -> build -> send. NEVER raises."""
    try:
        if not isinstance(msg, dict):
            return None
        if not configured():
            return None
        cls = _event_class(msg)
        if cls is None:
            return None

        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}

        # per-event toggle + quiet hours (cheap, no network)
        with _LOCK:
            st = _load()
        toggles = st.get("toggles") or _DEFAULT_TOGGLES
        toggle_key = "proposal" if cls == "proposal" else cls  # hot_lead|missed_sweep|handoff|agency
        if not toggles.get(toggle_key, True):
            return None
        if _in_quiet_hours(st.get("quietHours")):
            return None
        if cls == "proposal" and not _proposal_is_warm_or_better(data):
            return None

        buttons = _buttons_for(cls, data)
        text = _compose_text(msg, data)
        dedupe_key = f"{cls}:" + str(
            data.get("pid") or data.get("convId") or data.get("requestId")
            or data.get("draftId") or msg.get("id"))
        # Fire the network send on a daemon thread so a slow Telegram POST can NEVER block
        # the caller — agent_bus.send is sometimes called while Marcus holds its engine lock.
        threading.Thread(target=send, args=(text, buttons),
                         kwargs={"dedupe_key": dedupe_key}, daemon=True).start()
        return {"ok": True, "queued": True}
    except Exception as e:  # noqa: BLE001
        try:
            _set_error(e)
        except Exception:
            pass
        return None


# ── callback dispatch ─────────────────────────────────────────────────────────
def _result_text(action, result):
    """Short human result for answerCallbackQuery + the editMessageText footer."""
    if isinstance(result, dict) and result.get("error"):
        return f"⚠ {result['error']}"
    # Dyson approve → ship: surface the real outcome + the PR link (not a static label).
    if action == "dysongo" and isinstance(result, dict):
        ap = result.get("apply") or {}
        if ap.get("ok"):
            url = ap.get("url") or ""
            return "✅ Shipped — PR opened" + (f": {url}" if url else " (Vercel deploys on merge)")
        if ap:  # approved but the ship couldn't complete (no repo linked / no token)
            return f"⚠ Approved, not shipped: {ap.get('detail', 'deploy failed')}"
    if isinstance(result, dict) and result.get("message"):
        return f"✅ {result['message']}"
    labels = {
        "approve": "✅ Approved & sent",
        "mdismiss": "\U0001f5d1 Dismissed",
        "handoff": "\U0001f91d Handed to Marcus",
        "scoutdismiss": "\U0001f515 Dismissed",
        "opspause": "🕐 Agents clocked out",
        "opsresume": "🟢 Agents clocked in",
        "dysonplan": "\U0001f6e0 Dyson is drafting a plan…",
        "reqdismiss": "\U0001f5d1 Request dismissed",
        "dysongo": "✅ Approved — shipping",
        "dysonno": "\U0001f5d1 Plan rejected",
    }
    return labels.get(action, "✅ Done")


def _handle_callback(cq, token=None, agent_chat=False):
    """Authorize, dispatch to a registered action, then ack + edit the message.

    The dedicated agent bot sends its own inline buttons. Telegram delivers taps
    for those buttons to that same bot token, so ack/edit must use `token` too.
    """
    cq_id = cq.get("id")
    from_id = str((cq.get("from") or {}).get("id", ""))
    message = cq.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    message_id = message.get("message_id")

    # AUTHORIZATION (mandatory security control): two-factor — right chat AND allowed user.
    # A shared group chat id alone is NOT enough (see _authorized). Otherwise refuse.
    authorized = _msg_authorized(from_id) if agent_chat else _authorized(from_id, chat_id)
    if not authorized:
        try:
            _api("answerCallbackQuery",
                 {"callback_query_id": cq_id, "text": "Not authorized", "show_alert": True},
                 timeout=10, token=token)
        except Exception:  # noqa: BLE001
            pass
        return

    raw = cq.get("data") or ""
    action, _, arg = raw.partition(":")
    fn = _ACTIONS.get(action)
    if not fn:
        result = {"error": f"unknown action: {action}"}
    else:
        try:
            result = fn(arg)
            if not isinstance(result, dict):
                result = {"ok": True}
        except Exception as e:  # noqa: BLE001
            result = {"error": str(e)}

    summary = _result_text(action, result)

    # ack the button (clears the spinner)
    try:
        _api("answerCallbackQuery",
             {"callback_query_id": cq_id, "text": summary[:200]}, timeout=10, token=token)
    except Exception:  # noqa: BLE001
        pass

    # append the outcome to the original message so the operator sees what happened
    if chat_id and message_id is not None:
        orig = message.get("text") or ""
        footer = _esc(summary)   # summary may carry an error string with < > &
        new_text = f"{_esc(orig)}\n\n{footer}" if orig else footer
        try:
            # drop the inline keyboard so the (now-acted) buttons can't be tapped again
            _api("editMessageText",
                 {"chat_id": chat_id, "message_id": message_id, "text": new_text,
                  "parse_mode": "HTML", "reply_markup": {"inline_keyboard": []}},
                 timeout=10, token=token)
        except Exception:  # noqa: BLE001
            pass


# ── agent chat: talk to your AI agents in a separate Telegram chat ────────────
# A second Telegram chat (a group with the bot, or /commands anywhere) becomes a
# direct line to the agents. SECURITY: only the operator's own Telegram account is
# authorized (from_id == TELEGRAM_CHAT_ID, or an explicit TELEGRAM_ALLOWED_IDS entry) —
# so a stranger in the group can't command your CRM. GHL writes (texting a seller)
# still flow back through the gated Approve button, never auto-fired from chat.
_AGENT_CHAT = {"fn": None}                # fn(agent_id, message, history) -> reply str  (REI)
_AGENCY_CHAT = {"fn": None}               # fn(agent_id, message, history) -> reply str  (Dyson/Eco)
_AGENCY_TASK = {"fn": None}               # fn(agent_id, title) -> {reply|error}         (Dyson/Eco /task)
_AGENT_SESS = {}                          # chat_id -> {"agent": str, "history": [...]}  (in-memory)
_AGENT_ALIASES = {"/scout": "scout", "/marcus": "marcus", "/atlas": "atlas",
                  "/dyson": "dyson", "/eco": "eco"}
_AGENCY_AGENTS = ("dyson", "eco")         # routed to the agency chat/task backend

# The full crew, one line each — /agents and the unified /help both read from this.
_AGENT_ROSTER = (
    ("marcus", "🤝", "acquisitions — screen a lead, draft a reply, work your GHL"),
    ("scout", "🔭", "lead triage — who to text back first, “audit last week”"),
    ("atlas", "🏠", "underwriting — deal prep, offer anchors, MAO math"),
    ("dyson", "🛠", "agency builds — client website/code edits (plans, you approve)"),
    ("eco", "📣", "agency ads — Meta strategy + analysis (recommends, you launch)"),
)

# ONE help card. /start, /help, and telegram_ops's /ops entry all land here.
_AGENT_HELP = (
    "<b>FORGE REI OS</b> — your crew, from your phone\n"
    "\n🕹 <b>Agents</b> — pick one, then just chat:\n"
    + "\n".join(f"• <code>/{aid}</code> {emo} {blurb}" for aid, emo, blurb in _AGENT_ROSTER)
    + "\n• <code>/task fix the hero copy</code> — hand the ACTIVE agent a job "
    "(Dyson/Eco queue it as a planned task; Marcus/Scout/Atlas act on it in chat)\n"
    "• <code>/agents</code> — the roster · <code>/menu</code> — quick-tap buttons\n"
    "\n☀️ <b>Daily</b>: <code>/today</code> · <code>/done 3</code> · <code>/hot</code> · "
    "<code>/report</code> · <code>/sweep</code> · <code>/proposals</code>\n"
    "\n🤖 <b>Autonomy</b>: <code>/ace</code> (off|shadow|supervised|full) · "
    "<code>/autopilot on|off</code> · <code>/clock</code> in/out kill switch\n"
    "\n⚙️ <b>Direct</b>: <code>/text name: msg</code> · <code>/screen name</code> · "
    "<code>/prep name</code> · <code>/find name</code> · <code>/checkback name</code>\n"
    "\nPlain English works too: “text arthur I can call at 3”.\n"
    "Anything that touches a seller still comes back as a ✅ confirm button first. "
    "<code>/ops</code> = the detailed ops card."
)

# Quick-tap reply keyboard (persistent, /menu to show, /menu off to remove). Each label
# maps to an existing command so zero new backend logic runs behind a tap.
_KEYBOARD_MAP = {
    "☀️ today": "/today", "🔥 hot": "/hot", "📊 report": "/report",
    "🕹 agents": "/agents", "🕐 clock": "/clock", "✅ proposals": "/proposals",
}
_KEYBOARD_ROWS = [["☀️ Today", "🔥 Hot", "📊 Report"],
                  ["🕹 Agents", "✅ Proposals", "🕐 Clock"]]

# Native Telegram command menu (the "/" button). Curated — not every alias, just the
# ones worth a menu slot. setMyCommands is best-effort at boot.
_BOT_COMMANDS = [
    ("today", "Today's battle plan"),
    ("hot", "Hot leads to text back now"),
    ("report", "Ops snapshot"),
    ("agents", "The crew roster"),
    ("task", "Hand the active agent a job"),
    ("marcus", "Chat with Marcus (acquisitions)"),
    ("scout", "Chat with Scout (triage)"),
    ("atlas", "Chat with Atlas (underwriting)"),
    ("dyson", "Chat with Dyson (agency builds)"),
    ("eco", "Chat with Eco (agency ads)"),
    ("proposals", "Pending reply approvals"),
    ("clock", "Clock the crew in/out"),
    ("ace", "ACE autonomy mode"),
    ("autopilot", "Re-engage autopilot on/off"),
    ("menu", "Quick-tap buttons"),
    ("help", "Everything in one card"),
]


def register_commands():
    """Publish the native '/' command menu (setMyCommands) for the alerts bot and, if
    configured, the dedicated agent bot. Best-effort — a failure never blocks boot."""
    cmds = [{"command": c, "description": d} for c, d in _BOT_COMMANDS]
    for tok in {_token(), _agent_token()}:
        if not tok:
            continue
        try:
            _api("setMyCommands", {"commands": cmds}, timeout=10, token=tok)
        except Exception as e:  # noqa: BLE001
            _set_error(e)


def register_agent_chat(fn):
    """Wire the REI agent-chat backend. fn(agent_id, message, history) -> reply string.
    The connector points this at agents_chat.chat (marcus/scout/atlas)."""
    _AGENT_CHAT["fn"] = fn


def register_agency_chat(chat_fn, task_fn=None):
    """Wire the AGENCY side (Dyson/Eco). chat_fn(agent_id, message, history) -> reply;
    task_fn(agent_id, title) -> {reply|error} queues a planned task (plan-only, no
    execution — same contract as the Agency dashboard's task queue)."""
    _AGENCY_CHAT["fn"] = chat_fn
    if task_fn:
        _AGENCY_TASK["fn"] = task_fn


def _msg_authorized(from_id):
    """Agent chat is locked to the operator: from_id must equal TELEGRAM_CHAT_ID (their
    own user id) or be in TELEGRAM_ALLOWED_IDS. Any chat is fine as long as the USER is
    authorized — that's what lets a separate group act as the agent chat."""
    from_id = str(from_id or "")
    if not from_id:
        return False
    allowed = _allowed_ids()
    return (from_id in allowed) if allowed else (from_id == _chat_id())


def _send_to(chat_id, text, buttons=None, token=None, reply_markup=None):
    """sendMessage to a specific chat (the agent chat). No dedupe. Never raises.
    `token` lets the dedicated agent bot reply through its own token. `reply_markup`
    (a raw keyboard/remove_keyboard dict) wins over `buttons` (inline keyboard rows)."""
    if not (token or _token()) or not chat_id:
        return {"error": "no chat"}
    payload = {"chat_id": str(chat_id), "text": text[:4000], "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    elif buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        resp = _api("sendMessage", payload, timeout=12, token=token)
        if not isinstance(resp, dict) or not resp.get("ok", False):
            return {"error": "send failed"}
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        _set_error(e)
        return {"error": str(e)}


def _handle_message(msg, reply_token=None):
    """Route an inbound Telegram text to the right agent and reply in the same chat.
    reply_token = which bot answers (the dedicated agent bot passes its own token)."""
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    from_id = str((msg.get("from") or {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    if not text or not chat_id or not _msg_authorized(from_id):
        return
    low = text.lower()

    def reply_to(t, markup=None):
        return _send_to(chat_id, t, token=reply_token, reply_markup=markup)

    # Quick-tap keyboard labels are just commands in disguise — translate + fall through.
    mapped = _KEYBOARD_MAP.get(low)
    if mapped:
        text, low = mapped, mapped

    if low in ("/start", "/help"):
        reply_to(_AGENT_HELP,
                 markup={"keyboard": _KEYBOARD_ROWS, "resize_keyboard": True,
                         "is_persistent": True} if low == "/start" else None)
        return
    if low in ("/menu", "/menu on"):
        reply_to("Quick taps on. <code>/menu off</code> removes them.",
                 markup={"keyboard": _KEYBOARD_ROWS, "resize_keyboard": True,
                         "is_persistent": True})
        return
    if low == "/menu off":
        reply_to("Quick taps off.", markup={"remove_keyboard": True})
        return
    if low in ("/whoami", "/id"):
        reply_to(f"chat id: <code>{chat_id}</code>\nyour id: <code>{from_id}</code>")
        return
    if low in ("/agents", "/who"):
        cur = (_AGENT_SESS.get(chat_id) or {}).get("agent", "marcus")
        lines = ["🕹 <b>Your crew</b> — tap one, then just talk:"]
        for aid, emo, blurb in _AGENT_ROSTER:
            now = "  ← active" if aid == cur else ""
            lines.append(f"{emo} <code>/{aid}</code> — {blurb}{now}")
        lines.append("\n<code>/task ...</code> hands the active agent a job.")
        reply_to("\n".join(lines))
        return

    # ACE autonomy control: /ace  (status) · /ace off|shadow|supervised|full
    if low == "/ace" or low.startswith("/ace "):
        parts = low.split()
        try:
            import ace
            if len(parts) == 1:
                st = ace.status()
                reply_to(f"🤖 ACE mode: <b>{str(st.get('mode', 'off')).upper()}</b> · "
                         f"sent today {st.get('sentToday', 0)}\n"
                         "Set with <code>/ace off|shadow|supervised|full</code>")
            else:
                res = ace.set_mode(parts[1])
                if res.get("error"):
                    reply_to("⚠️ " + res["error"])
                else:
                    reply_to(f"🤖 ACE → <b>{str(res.get('mode', '?')).upper()}</b>"
                             + (" — drafts queue for your approval, no auto-send"
                                if res.get("mode") == "shadow" else ""))
        except Exception as e:  # noqa: BLE001
            reply_to("ACE error: " + str(e))
        return

    # Remote-control ops layer: slash commands + plain-English actions (gated sends
    # come back as ✅/❌ confirm buttons). Returns True when it consumed the message;
    # plain conversation falls through to the agent chat below.
    try:
        import telegram_ops
        if telegram_ops.route(text, chat_id,
                              lambda t, b=None: _send_to(chat_id, t, buttons=b,
                                                         token=reply_token)):
            return
    except Exception as e:  # noqa: BLE001
        _set_error(e)

    sess = _AGENT_SESS.setdefault(chat_id, {"agent": "marcus", "history": []})
    # Agent switch via prefix: "/dyson status on the smith site" or just "/atlas".
    for alias, aid in _AGENT_ALIASES.items():
        if low == alias or low.startswith(alias + " "):
            sess["agent"] = aid
            text = text[len(alias):].strip()
            if not text:
                reply_to(f"Now talking to <b>{aid.title()}</b>. What do you need?"
                         + ("\n<code>/task ...</code> queues a planned job."
                            if aid in _AGENCY_AGENTS else ""))
                return
            low = text.lower()
            break

    agent_id = sess["agent"]

    # /task <description> — hand the ACTIVE agent a job. Dyson/Eco queue a planned task
    # (plan-only, approval-gated downstream, same as the Agency dashboard); the REI crew
    # are conversational dispatchers, so their "task" just flows through chat.
    if low == "/task" or low.startswith("/task "):
        title = text[5:].strip()
        if not title:
            reply_to(f"<code>/task what you need done</code> — goes to "
                     f"<b>{agent_id.title()}</b> (active agent).")
            return
        if agent_id in _AGENCY_AGENTS:
            tfn = _AGENCY_TASK.get("fn")
            if not tfn:
                reply_to("Agency tasks aren't wired up yet.")
                return
            try:
                res = tfn(agent_id, title) or {}
            except Exception as e:  # noqa: BLE001
                res = {"error": str(e)}
            if res.get("error"):
                reply_to(f"⚠️ {_esc(str(res['error']))}")
            else:
                plan = ((res.get("task") or {}).get("plan")
                        or res.get("plan") or res.get("reply") or "queued")
                reply_to(f"📋 <b>Queued for {agent_id.title()}</b> — it's on the "
                         f"Agency board.\n{_esc(str(plan)[:1200])}")
            return
        text = title          # REI agent: treat the task as the chat message below
        low = text.lower()

    # Route to the right brain: Dyson/Eco → agency backend, the rest → REI agents_chat.
    fn = _AGENCY_CHAT.get("fn") if agent_id in _AGENCY_AGENTS else _AGENT_CHAT.get("fn")
    if not fn:
        reply_to(f"{agent_id.title()}'s chat isn't wired up yet.")
        return
    try:
        _api("sendChatAction", {"chat_id": chat_id, "action": "typing"},
             timeout=8, token=reply_token)
    except Exception:  # noqa: BLE001
        pass
    try:
        reply = fn(agent_id, text, list(sess["history"]))
    except Exception as e:  # noqa: BLE001
        _set_error(e)
        reply = f"({agent_id.title()} hit an error: {e})"
    reply = reply or "On it."
    sess["history"].append({"role": "user", "text": text})
    sess["history"].append({"role": "assistant", "text": reply})
    sess["history"] = sess["history"][-12:]
    reply_to(f"<b>{agent_id.title()}</b>\n{_esc(reply)}")


# ── public: the long-poll loop ────────────────────────────────────────────────
def run_forever():
    """getUpdates long-poll: consume callback_query updates, authorize, dispatch.
    Returns immediately (no busy spin) when not configured. NEVER raises out."""
    if not configured():
        return
    while True:
        forge_heartbeat.beat("telegram", 70, "Telegram poll")
        try:
            with _LOCK:
                offset = _load().get("offset", 0)
            params = urllib.parse.urlencode({
                "timeout": 50,
                "offset": offset + 1,
                "allowed_updates": json.dumps(["callback_query", "message"]),
            })
            token = _token()
            if not token:
                return
            url = f"{API_BASE}/bot{token}/getUpdates?{params}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # noqa: BLE001
            _set_error(f"getUpdates {e.code}")
            time.sleep(3)
            continue
        except Exception as e:  # noqa: BLE001
            _set_error(e)
            time.sleep(3)
            continue

        if not isinstance(resp, dict) or not resp.get("ok"):
            time.sleep(3)
            continue
        results = resp.get("result")
        if not isinstance(results, list):
            time.sleep(3)
            continue

        for update in results:
            if not isinstance(update, dict):
                continue
            uid = update.get("update_id")
            # ADVANCE + PERSIST OFFSET FIRST, then dispatch. At-most-once: if the action
            # (an outbound SMS approval) runs and the process crashes, the update is already
            # consumed and won't be re-fetched + re-sent. (Marcus.approve is also idempotent
            # — it pops the proposal — so a same-batch retry can't double-text either.)
            if isinstance(uid, int):
                with _LOCK:
                    st = _load()
                    if uid > st.get("offset", 0):
                        st["offset"] = uid
                        _save(st)
            try:
                cq = update.get("callback_query")
                if isinstance(cq, dict):
                    _handle_callback(cq, token=token)
                mensaje = update.get("message")
                if isinstance(mensaje, dict):
                    _handle_message(mensaje)
            except Exception as e:  # noqa: BLE001
                _set_error(e)   # one bad update can't kill the loop


def agent_bot_configured():
    return bool(_agent_token())


_AGENT_LOOP = {"started": False, "polls": 0, "lastError": None, "lastMsgFrom": None}


def run_agent_bot_forever():
    """Long-poll the DEDICATED agent bot (TELEGRAM_AGENT_BOT_TOKEN). Every DM goes straight
    to the agents and is answered through this bot. Separate offset so it never collides
    with the alerts bot. Returns immediately if no agent bot is configured. NEVER raises."""
    if not _agent_token():
        _AGENT_LOOP["lastError"] = "no agent token at start"
        return
    _AGENT_LOOP["started"] = True
    while True:
        _AGENT_LOOP["polls"] += 1
        forge_heartbeat.beat("telegram_agent", 70, "Telegram agent bot",
                             error=_AGENT_LOOP.get("lastError"))
        try:
            with _LOCK:
                offset = _load().get("agentOffset", 0)
            token = _agent_token()
            if not token:
                return
            params = urllib.parse.urlencode({
                "timeout": 50,
                "offset": offset + 1,
                "allowed_updates": json.dumps(["callback_query", "message"]),
            })
            url = f"{API_BASE}/bot{token}/getUpdates?{params}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # noqa: BLE001
            _AGENT_LOOP["lastError"] = f"HTTP {e.code}"
            _set_error(f"agent getUpdates {e.code}")
            time.sleep(3)
            continue
        except Exception as e:  # noqa: BLE001
            _AGENT_LOOP["lastError"] = str(e)[:120]
            _set_error(e)
            time.sleep(3)
            continue

        if not isinstance(resp, dict) or not resp.get("ok"):
            time.sleep(3)
            continue
        results = resp.get("result")
        if not isinstance(results, list):
            time.sleep(3)
            continue

        for update in results:
            if not isinstance(update, dict):
                continue
            uid = update.get("update_id")
            if isinstance(uid, int):
                with _LOCK:
                    st = _load()
                    if uid > st.get("agentOffset", 0):
                        st["agentOffset"] = uid
                        _save(st)
            try:
                cq = update.get("callback_query")
                if isinstance(cq, dict):
                    _handle_callback(cq, token=token, agent_chat=True)
                mensaje = update.get("message")
                if isinstance(mensaje, dict):
                    _handle_message(mensaje, reply_token=token)
            except Exception as e:  # noqa: BLE001
                _set_error(e)
