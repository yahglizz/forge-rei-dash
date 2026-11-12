"""slack_io.py — Slack transport for FORGE REI OS (mirror of telegram_io's outbound surface).

Telegram -> Slack migration: send / send_photo, Telegram-HTML -> mrkdwn, splitting, the
business -> channel map, the card registry (Task 2), button taps (Task 4: authorized,
handle_interaction) and the Socket Mode listener (Task 5: run_forever, status).

Listener client (Task 5, verified 2026-11-11 against slack_sdk 3.46.0 in a throwaway venv):
  slack_sdk.socket_mode.builtin.SocketModeClient — its own RFC 6455 client over stdlib
  socket/ssl/struct/threading; slack_sdk has no install requirements (pip installs nothing
  else), so the box needs no websocket-client / aiohttp / websockets. slack_sdk is imported
  lazily inside run_forever: missing -> one log line and return, the connector keeps running.
  Box install (Task 10, owner-approved box change, root):
      pip3 install --break-system-packages slack_sdk==3.46.0
  Env: SLACK_APP_TOKEN (xapp-, Socket Mode), SLACK_BOT_TOKEN (xoxb-, Web API),
  SLACK_ALLOWED_USER_IDS; started by connector.py only when FORGE_SLACK=1 and FORGE_MARCUS=1.

Design (same rules as telegram_io):
  • stdlib + `requests` only for sending; slack_sdk only for the listener socket.
  • Secrets live OUTSIDE the web root: forge-slack/config/slack.env + slack-agents.env, folded
    into the env at import (os.environ.setdefault — real env wins). FORGE_SLACK_CONFIG_DIR
    overrides the dir. On the box the dir sits next to forge-telegram/config (/opt/forge/...).
    Only the Slack keys in _ENV_KEYS + SLACK_CHANNEL_<NAME> are taken from those files;
    FORGE_CHAT_TRANSPORT, FORGE_SLACK and SLACK_ONLY_TEST come from the real process env only.
  • Inert by default: FORGE_CHAT_TRANSPORT unset/"telegram" -> send() returns False, no network.
  • #forge-hq must stay owner-only (private, owner invited only): Mac command output and owner
    DM replies mirror there (HQ is the fallback for a chat with no business).
  • State in marcus_state/ (NOT telegram.json — its _load() drops unknown keys):
      slack.json        {"hq": "C..", "<business>": "C..", "dedupe": {key: epoch}}
      slack_cards.json  {card_id: {"channel", "ts", "actions", "at", "consumed",
                                   "origin_chat", "tg_chat_id", "tg_message_id", "tg_bot"}}
                        tg_* = the Telegram twin of a mirrored card (C4: one live button per card,
                        see claim_for_telegram). "tg:<chat>:<msg>" keys are tombstones: a Telegram
                        tap that landed before its Slack copy was registered.
    One threading.Lock guards both. Helpers that take the lock are never called while holding it.
  • Best-effort: send / send_photo / _api never raise; tokens are redacted from every error.
"""
from __future__ import annotations

import collections
import html as _html
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

try:
    import requests
except Exception:  # noqa: BLE001 — a missing lib must never stop the connector importing us
    requests = None

HERE = Path(__file__).resolve().parent
SLACK_DIR = Path(os.environ.get("FORGE_SLACK_CONFIG_DIR") or HERE.parent / "forge-slack" / "config")
STATE = HERE / "marcus_state"            # dir; files below are resolved at call time (tests patch STATE)
API_BASE = "https://slack.com/api"

BUSINESSES = ("wholesale", "agency", "daycare", "dropship")
# Rooms inside a business: its own channel per kind of news. Key "<business>-<topic>" in
# slack.json, env SLACK_CHANNEL_<BUSINESS>_<TOPIC>. An unbound room falls back to the business
# channel. A room IS its business for chat (Solomon answers in #daycare-tours) and for taps.
TOPICS = {"daycare": ("alerts", "tours", "quotes", "starting", "enrolled")}
TOPIC_KEYS = tuple(f"{b}-{t}" for b, ts in TOPICS.items() for t in ts)
# Which room a mirrored alert lands in, by its dedupe_key prefix (the senders' own keys).
_TOPIC_BY_KEY = (("daycare-lead:", "daycare-alerts"), ("dcreply:", "daycare-alerts"),
                 ("cal-remind:", "daycare-tours"), ("daycare-start:", "daycare-starting"))
_DEDUPE_WINDOW = 15 * 60
_DEDUPE_MAX = 200
_CARD_TTL = 7 * 86400                     # ad concepts live 3 days; keep a margin
_CARD_MAX = 500
_MARK_TTL = 90 * 86400                    # consumed markers for pruned twins (L1): Telegram buttons never expire
_MARK_MAX = 2000
_SECTION_MAX = 2900                       # Slack section text limit is 3000
_MSG_SECTIONS = 12                        # sections per message (Slack caps a message at 50 blocks)

_LOCK = threading.Lock()


# ── env load (import-time) ────────────────────────────────────────────────────
# Config files may only carry these Slack keys. Flags that change routing or turn the transport
# on (FORGE_CHAT_TRANSPORT, FORGE_SLACK, SLACK_ONLY_TEST) are read from the real env only.
_ENV_KEYS = {"SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_AGENTS_BOT_TOKEN", "SLACK_SIGNING_SECRET",
             "SLACK_AGENTS_SIGNING_SECRET", "SLACK_ALLOWED_USER_IDS", "SLACK_OWNER_IDS", "SLACK_TEST_CHANNEL_ID"}
_ENV_CHANNEL_RE = re.compile(r"SLACK_CHANNEL_[A-Z_]+")


def _load_env_file(p):
    """Fold the allowed KEY=VALUE lines of a file into the environment (real env wins). Never raises."""
    try:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k in _ENV_KEYS or _ENV_CHANNEL_RE.fullmatch(k):
                        os.environ.setdefault(k, v.strip().strip("'\""))
    except Exception:  # noqa: BLE001
        pass


for _f in ("slack.env", "slack-agents.env", "slack-channels.env"):   # channels: SLACK_CHANNEL_<BIZ|HQ>
    _load_env_file(SLACK_DIR / _f)


def _token():
    return (os.environ.get("SLACK_BOT_TOKEN") or "").strip()


def mode() -> str:
    """FORGE_CHAT_TRANSPORT: telegram (default, Slack inert) | both | slack."""
    m = (os.environ.get("FORGE_CHAT_TRANSPORT") or "").strip().lower()
    return m if m in ("telegram", "both", "slack") else "telegram"


# ── secrets ───────────────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(r"x(?:ox[abposr]|app)-[A-Za-z0-9-]+")


def _redact(s) -> str:
    s = "" if s is None else str(s)
    for k in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_AGENTS_BOT_TOKEN",
              "SLACK_SIGNING_SECRET", "SLACK_AGENTS_SIGNING_SECRET"):
        v = (os.environ.get(k) or "").strip()
        if v and v in s:
            s = s.replace(v, "***")
    return _TOKEN_RE.sub("***", s)


def _api(method, token, **params) -> dict:
    """POST a Web API method (form-encoded; list/dict params JSON-encoded). Returns Slack's
    dict, or {"ok": False, "error": <redacted>} on any failure. Never raises."""
    if requests is None:
        return {"ok": False, "error": "requests not installed"}
    if not token:
        return {"ok": False, "error": "slack not configured"}
    data = {k: (json.dumps(v) if isinstance(v, (list, dict, bool)) else v)   # bool -> "true"/"false"
            for k, v in params.items() if v is not None}
    try:
        r = requests.post(f"{API_BASE}/{method}", data=data, timeout=10,
                          headers={"Authorization": f"Bearer {token}"})
        try:
            out = r.json()
        except ValueError:
            return {"ok": False, "error": f"http {r.status_code}"}
        return out if isinstance(out, dict) else {"ok": False, "error": "bad response"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": _redact(f"{type(e).__name__}: {e}")[:200]}


# ── state (call only WITHOUT _LOCK held from public fns; these two never lock) ─
def _read(name) -> dict:
    try:
        data = json.loads((STATE / name).read_text())
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _read_strict(name) -> dict:
    """Like _read, but only a MISSING file reads as empty; unreadable / corrupt raises."""
    p = STATE / name
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{name} is not a JSON object")
    return data


def _write(name, data) -> bool:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        tmp = STATE / (name + ".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, STATE / name)
        return True
    except Exception:  # noqa: BLE001
        return False


# ── channels ──────────────────────────────────────────────────────────────────
def bind(business: str, channel_id: str) -> None:
    """Point `business` (or "hq") at a Slack channel id. ValueError on bad input."""
    b = str(business or "").strip().lower()
    cid = str(channel_id or "").strip()
    if b not in BUSINESSES + ("hq",) + TOPIC_KEYS:
        raise ValueError(f"unknown business: {b!r}")
    if not re.fullmatch(r"[CDG][A-Z0-9]{2,}", cid):
        raise ValueError("bad channel id")
    with _LOCK:
        st = _read("slack.json")
        st[b] = cid
        _write("slack.json", st)


def _env_channel(key) -> str | None:
    return (os.environ.get(f"SLACK_CHANNEL_{key.upper().replace('-', '_')}") or "").strip() or None


def topic_channel(key) -> str | None:
    """The room's own channel ("daycare-tours"), or None while it has none (bound, then env)."""
    if key not in TOPIC_KEYS or os.environ.get("SLACK_ONLY_TEST") == "1":
        return None
    with _LOCK:
        st = _read("slack.json")
    return st.get(key) or _env_channel(key)


def topic_of(channel_id) -> str | None:
    """"tours" for the daycare-tours room, None for any other channel."""
    cid = str(channel_id or "").strip()
    return next((k.split("-", 1)[1] for k in TOPIC_KEYS if cid and cid == topic_channel(k)), None)


def chat_for(business: str | None) -> str | None:
    """Bound business channel -> env SLACK_CHANNEL_<BIZ> -> HQ (bound, then env SLACK_CHANNEL_HQ)
    -> None. SLACK_ONLY_TEST=1 routes everything to SLACK_TEST_CHANNEL_ID."""
    if os.environ.get("SLACK_ONLY_TEST") == "1":
        return (os.environ.get("SLACK_TEST_CHANNEL_ID") or "").strip() or None
    with _LOCK:
        st = _read("slack.json")
    b = str(business or "").strip().lower()
    if b in BUSINESSES:
        c = st.get(b) or _env_channel(b)
        if c:
            return c
    return st.get("hq") or _env_channel("hq") or None


def _channels() -> set:
    """Every channel a tap may come from: HQ + each business channel (bound or env)."""
    with _LOCK:
        st = _read("slack.json")
    out = {st.get(k) or _env_channel(k) for k in BUSINESSES + ("hq",) + TOPIC_KEYS}
    if os.environ.get("SLACK_ONLY_TEST") == "1":
        out.add((os.environ.get("SLACK_TEST_CHANNEL_ID") or "").strip())
    return {c for c in out if c}


def business_of(channel_id) -> str | None:
    """Which FORGE channel this is: a business, "hq", or None. A business wins over HQ."""
    cid = str(channel_id or "").strip()
    if not cid:
        return None
    with _LOCK:
        st = _read("slack.json")
    for k in BUSINESSES + ("hq",):
        if cid == (st.get(k) or _env_channel(k)):
            return k
    for k in TOPIC_KEYS:                       # a room is its business
        if cid == (st.get(k) or _env_channel(k)):
            return k.split("-", 1)[0]
    if os.environ.get("SLACK_ONLY_TEST") == "1" and cid == (os.environ.get("SLACK_TEST_CHANNEL_ID") or "").strip():
        return "hq"
    return None


# ── dedupe (same semantics as telegram_io: check before, commit after success) ─
def _ring(st, now):
    return {k: v for k, v in (st.get("dedupe") or {}).items()
            if isinstance(v, (int, float)) and now - v < _DEDUPE_WINDOW}


def _dedupe_seen(key) -> bool:
    if not key:
        return False
    with _LOCK:
        return key in _ring(_read("slack.json"), time.time())


def _dedupe_commit(key) -> None:
    # ponytail: check-then-commit race, same as telegram_io; reserve-before-send if it ever bites.
    if not key:
        return
    now = time.time()
    with _LOCK:
        st = _read("slack.json")
        ring = _ring(st, now)
        ring[key] = now
        if len(ring) > _DEDUPE_MAX:
            ring = dict(sorted(ring.items(), key=lambda kv: kv[1], reverse=True)[:_DEDUPE_MAX])
        st["dedupe"] = ring
        _write("slack.json", st)


# ── card registry ─────────────────────────────────────────────────────────────
def _tombstone_key(chat, message_id) -> str:
    return f"tg:{chat}:{message_id}"


def _prune(cards, now) -> dict:
    """Drop cards past _CARD_TTL / over _CARD_MAX. A dropped card that was used and has a
    Telegram twin leaves a consumed marker {"tombstone", "consumed", "at"} at tg:<chat>:<msg>
    for _MARK_TTL (newest _MARK_MAX kept), so the twin's old buttons stay refused (L1)."""
    keep, marks, gone = {}, {}, []
    for k, v in cards.items():
        if not isinstance(v, dict):
            continue
        age = now - (v.get("at") or 0)
        if v.get("tombstone") and v.get("consumed"):
            if age < _MARK_TTL:
                marks[k] = v
        elif age < _CARD_TTL:
            keep[k] = v
        else:
            gone.append(v)
    if len(keep) > _CARD_MAX:
        ordered = sorted(keep.items(), key=lambda kv: kv[1].get("at") or 0, reverse=True)
        keep = dict(ordered[:_CARD_MAX])
        gone += [v for _, v in ordered[_CARD_MAX:]]
    for v in gone:
        if v.get("consumed") and v.get("tg_chat_id") and v.get("tg_message_id") is not None:
            marks[_tombstone_key(v["tg_chat_id"], v["tg_message_id"])] = {
                "tombstone": True, "consumed": True, "at": now}
    if len(marks) > _MARK_MAX:
        marks = dict(sorted(marks.items(), key=lambda kv: kv[1].get("at") or 0, reverse=True)[:_MARK_MAX])
    keep.update(marks)
    return keep


def register_card(card_id: str, channel: str, ts: str, actions: list[str],
                  origin_chat: str | None = None, tg_message_id=None,
                  tg_chat_id: str | None = None, tg_bot: str | None = None) -> bool:
    """origin_chat = the Telegram chat id a pgo/pno token was issued for (None = a Slack-born
    card, whose taps use f"slack:{channel}"). tg_chat_id + tg_message_id = the Telegram twin, if
    any; tg_bot = "agent" when the agent bot sent it (its own token must edit it).
    -> True when the twin was already tapped in Telegram (a tombstone): the card is born used."""
    now = time.time()
    with _LOCK:
        cards = _prune(_read("slack_cards.json"), now)
        twin = tg_chat_id and tg_message_id is not None
        used = bool(twin and cards.pop(_tombstone_key(tg_chat_id, tg_message_id), None))
        cards[str(card_id)] = {"channel": channel, "ts": ts, "actions": list(actions or []),
                               "at": now, "consumed": used,
                               "origin_chat": str(origin_chat) if origin_chat else None,
                               "tg_chat_id": str(tg_chat_id) if twin else None,
                               "tg_message_id": tg_message_id, "tg_bot": tg_bot}
        if used:
            cards[str(card_id)].update(consumedAt=now, consumedBy="telegram")
        _write("slack_cards.json", _prune(cards, now))
    return used


def get_card(card_id: str) -> dict | None:
    with _LOCK:
        card = _read("slack_cards.json").get(str(card_id or ""))
    return dict(card) if isinstance(card, dict) and not card.get("tombstone") else None


def claim_for_telegram(chat_id, message_id) -> str:
    """C4, one live button per card: called by telegram_io._handle_callback before a Telegram tap
    runs. -> "free"    no Slack twin: Telegram runs exactly as before.
       -> "claimed" this tap took the shared card (its Slack copy now refuses taps).
       -> "taken"   the Slack copy was already used (or a pruned twin's consumed marker): refuse.
       -> "unreadable" the registry could not be read or the claim not written: refuse, but
                    the card was not used (telegram_io keeps its buttons) (L2).
    Keyed by the Telegram message (chat id + message id), never by callback_data: the same
    value (opspause, adslaunch:10) appears on many cards. A missing registry or no twin = "free".
    Runs in every mode (M1: a rollback to telegram keeps cards used in Slack refused). With no
    twin yet (the Slack copy is posted on a thread and may still be in flight) a tombstone is
    left so register_card creates that copy already used; not in telegram mode (no copy comes).
    Never raises.
    Same-process assumption: _LOCK is a threading lock, so Telegram's poll loops and the Slack
    listener must run in one process (the connector), as they do today."""
    if not chat_id or message_id is None:
        return "free"
    chat, mid = str(chat_id), str(message_id)
    try:
        with _LOCK:
            cards = _read_strict("slack_cards.json")
            for cid, card in cards.items():
                if (isinstance(card, dict) and not card.get("tombstone")
                        and str(card.get("tg_chat_id") or "") == chat
                        and str(card.get("tg_message_id")) == mid):
                    if card.get("consumed"):
                        return "taken"
                    card.update(consumed=True, consumedAt=time.time(), consumedBy="telegram")
                    return "claimed" if _write("slack_cards.json", cards) else "unreadable"
            key = _tombstone_key(chat, mid)
            if isinstance(cards.get(key), dict) and cards[key].get("consumed"):
                return "taken"                    # its card was pruned after a Slack tap (L1)
            if mode() != "telegram":
                cards[key] = {"tombstone": True, "at": time.time()}
                _write("slack_cards.json", cards)     # best effort: no twin exists to protect yet
        return "free"
    except Exception as e:  # noqa: BLE001 — cannot tell whether Slack used it: refuse
        _log(f"claim_for_telegram failed closed: {type(e).__name__}")
        return "unreadable"


def _drop_tg_buttons(card) -> None:
    """Best effort after a Slack tap claimed a mirrored card: remove the Telegram twin's buttons
    (telegram_io's own Bot API helper, the bot that sent it). Never raises."""
    try:
        chat, mid = card.get("tg_chat_id"), card.get("tg_message_id")
        if not chat or mid is None:
            return
        import telegram_io as tio
        tok = tio._agent_token() if card.get("tg_bot") == "agent" else None
        tio._api("editMessageReplyMarkup", {"chat_id": str(chat), "message_id": mid,
                                            "reply_markup": {"inline_keyboard": []}},
                 timeout=10, token=tok or None)
    except Exception as e:  # noqa: BLE001 — type only: the Bot API URL carries the token
        _log(f"telegram twin edit failed: {type(e).__name__}")


# ── formatting ────────────────────────────────────────────────────────────────
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)((?:\s[^<>]*)?)\s*/?>")
_HREF_RE = re.compile(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_MARK = {"b": "*", "strong": "*", "i": "_", "em": "_", "s": "~", "strike": "~", "del": "~",
         "code": "`", "pre": "```"}
_DROP = {"u", "ins", "span", "tg-spoiler", "tg-emoji", "blockquote"}   # keep text, lose styling


def _esc(s) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_mrkdwn(html: str) -> str:
    """Telegram HTML -> Slack mrkdwn. Text is unescaped then re-escaped (& < >); <b>/<i>/<code>/
    <pre>/<s> become * _ ` ``` ~; <a href> becomes <url|text>; <br> a newline. A tag Telegram
    doesn't know is kept as escaped text."""
    if not html:
        return ""
    out, pos, link = [], 0, None              # link = (url, text parts) while inside <a>
    sink = out
    for m in _TAG_RE.finditer(html):
        sink.append(_esc(_html.unescape(html[pos:m.start()])))
        pos = m.end()
        closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3) or ""
        if tag in _MARK:
            sink.append(_MARK[tag])
        elif tag == "br":
            sink.append("\n")
        elif tag == "a" and not closing:
            h = _HREF_RE.search(attrs)
            url = _html.unescape((h.group(1) or h.group(2)) if h else "")
            sink = []
            link = (url, sink)
        elif tag == "a" and closing and link is not None:
            url, text = link[0], "".join(link[1])
            sink, link = out, None
            url = url.replace("<", "%3C").replace(">", "%3E").replace("|", "%7C")
            out.append(f"<{url}|{text}>" if url.startswith(("http://", "https://", "mailto:", "tel:"))
                       else text)
        elif tag in _DROP or tag == "a":
            pass
        else:
            sink.append(_esc(m.group(0)))
    sink.append(_esc(_html.unescape(html[pos:])))
    if link is not None:                      # unclosed <a>: keep its text
        out.extend(link[1])
    return "".join(out)


def split_text(text: str, limit: int = _SECTION_MAX) -> list[str]:
    """Cut `text` into chunks of at most `limit` chars; "".join(chunks) == text. Breaks after
    the last newline (else space) in the back half of the window, else hard-cuts."""
    text, limit = text or "", max(1, int(limit))
    chunks = []
    while len(text) > limit:
        window = text[:limit]
        cut = window.rfind("\n") + 1 or window.rfind(" ") + 1
        if cut <= limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:]
    if text:
        chunks.append(text)
    return chunks


def render_blocks(text: str, buttons: list[list[dict]] | None, card_id: str | None) -> list[dict]:
    """mrkdwn `text` -> section blocks (split at 2900); each Telegram button row -> one actions
    block (value = callback_data, action_id = callback_data[:255], block_id = "<card_id>#<row>").
    Buttons with an empty or >64-byte callback_data are dropped (Telegram refuses them too)."""
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": c}}
              for c in split_text(text) if c.strip()]
    for i, row in enumerate(buttons or []):
        elems = []
        for b in row or []:
            url = str((b or {}).get("url") or "")
            if url.startswith("https://"):     # link button: opens the page, runs nothing
                elems.append({"type": "button", "text": {"type": "plain_text", "emoji": True,
                                                         "text": str(b.get("text") or "Open")[:75]},
                              "url": url[:3000], "action_id": f"url{i}-{len(elems)}"})
                continue
            cb = str((b or {}).get("callback_data") or "")
            if not cb or len(cb.encode()) > 64:
                continue
            label = str(b.get("text") or cb)[:75] or cb[:75]
            elems.append({"type": "button", "text": {"type": "plain_text", "text": label, "emoji": True},
                          "value": cb, "action_id": cb[:255]})
        if elems:
            blocks.append({"type": "actions", "block_id": f"{card_id or 'nocard'}#{i}"[:255],
                           "elements": elems[:25]})
    return blocks


# ── send ──────────────────────────────────────────────────────────────────────
def _fail(why, channel) -> bool:
    """A Slack send that did not go out: one log line (reason + channel id, never a body or a
    token) and status()["last_error"]. -> False."""
    why = _redact(why)[:120]
    _STATUS["last_error"] = why
    _log(f"send failed: {why} channel={channel or '?'}")
    return False


def _deliver(html_text, business, buttons, dedupe_key, image_url=None,
             origin_chat=None, tg_message_id=None, channel=None, thread_ts=None,
             tg_chat_id=None, tg_bot=None) -> bool:
    # An explicit channel = a reply to something the owner said in Slack (slack_inbound); it
    # goes out in every mode. Mirrored alerts (no channel) stay inert in telegram mode.
    if mode() == "telegram" and not channel:
        return False
    token = _token()
    if not channel and business in TOPICS:     # a mirrored alert goes to its room when it has one
        room = next((k for pre, k in _TOPIC_BY_KEY if str(dedupe_key or "").startswith(pre)
                     and k.startswith(business + "-")), None)
        try:                                   # A Mother's Touch never enters a room (fail closed)
            import slack_rooms
            channel = topic_channel(room) if room and slack_rooms.room_ok(dedupe_key, html_text) else None
        except Exception:  # noqa: BLE001
            channel = None
    channel = channel or chat_for(business)
    if not token:
        return _fail("not configured (no SLACK_BOT_TOKEN)", channel)
    if not channel:
        return _fail(f"no channel for {business or 'hq'}", None)
    if _dedupe_seen(dedupe_key):
        return True
    md = to_mrkdwn(html_text)
    pieces = split_text(md, _MSG_SECTIONS * _SECTION_MAX) or [""]
    card_id = uuid.uuid4().hex[:16] if buttons else None
    for i, piece in enumerate(pieces):
        last = i == len(pieces) - 1
        blocks = render_blocks(piece, buttons if last else None, card_id)
        if image_url and i == 0:
            blocks.insert(0, {"type": "image", "image_url": image_url, "alt_text": "image"})
        if not blocks:
            return _fail("empty message", channel)
        res = _api("chat.postMessage", token, channel=channel, text=piece[:3000] or "FORGE",
                   blocks=blocks, unfurl_links=False, unfurl_media=False, thread_ts=thread_ts)
        if not res.get("ok"):
            return _fail(str(res.get("error") or "chat.postMessage failed"), channel)
        if last and card_id:
            ch, ts = res.get("channel") or channel, str(res.get("ts") or "")
            if register_card(card_id, ch, ts,
                             [e["value"] for b in blocks if b["type"] == "actions" for e in b["elements"] if "value" in e],
                             origin_chat=origin_chat, tg_message_id=tg_message_id,
                             tg_chat_id=tg_chat_id, tg_bot=tg_bot):
                # Tapped in Telegram before this copy landed: drop the Slack buttons (best effort).
                _api("chat.update", token, channel=ch, ts=ts, text=piece[:3000] or "FORGE",
                     blocks=[b for b in blocks if b["type"] != "actions"]
                     + [{"type": "context", "elements": [{"type": "mrkdwn", "text": "Handled in Telegram"}]}])
    _dedupe_commit(dedupe_key)
    return True


def send(text: str, business: str | None = None, buttons=None, dedupe_key: str | None = None,
         origin_chat: str | None = None, tg_message_id=None,
         channel: str | None = None, thread_ts: str | None = None,
         tg_chat_id: str | None = None, tg_bot: str | None = None) -> bool:
    """Post Telegram-HTML `text` to the business channel (HQ fallback), or to `channel`
    (optionally in thread `thread_ts`). True = delivered (or deduped). False = inert mode /
    unconfigured / Slack error (logged, status()["last_error"]). Never raises."""
    try:
        return _deliver(text, business, buttons, dedupe_key,
                        origin_chat=origin_chat, tg_message_id=tg_message_id,
                        channel=channel, thread_ts=thread_ts, tg_chat_id=tg_chat_id, tg_bot=tg_bot)
    except Exception as e:  # noqa: BLE001 — type only: the error text could carry the body
        return _fail(f"error {type(e).__name__}", channel)


def send_photo(photo, caption: str, business=None, buttons=None, dedupe_key=None,
               origin_chat=None, tg_message_id=None, tg_chat_id=None, tg_bot=None) -> bool:
    """`photo` is an image URL string (as telegram_io.send_photo's image_url). Image block +
    caption + buttons; if Slack refuses the image, falls back to send() with an Image link."""
    try:
        url = str(photo or "")
        twin = dict(origin_chat=origin_chat, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id, tg_bot=tg_bot)
        if url.startswith(("http://", "https://")) and len(url) <= 3000:
            if _deliver(caption, business, buttons, dedupe_key, image_url=url, **twin):
                return True
        return send(f"{caption or ''}\n\n🖼 <a href=\"{_html.escape(url)}\">Image</a>",
                    business=business, buttons=buttons, dedupe_key=dedupe_key, **twin)
    except Exception as e:  # noqa: BLE001 — type only: the error text could carry the caption
        return _fail(f"error {type(e).__name__}", None)


# ── taps (Block Kit block_actions) ────────────────────────────────────────────
# A tap runs the SAME telegram_io._ACTIONS function a Telegram tap runs. Order: retry dedupe ->
# user + channel auth -> card lookup (expired) -> card channel + button value -> already
# handled -> Mac-card owner rule -> claim (persisted BEFORE dispatch, fail closed) -> dispatch ->
# audit -> chat.update (result shown, buttons dropped). Refusals answer with an ephemeral.
_SEEN = collections.deque(maxlen=500)     # delivery ids already handled (Slack redelivers late acks)


def _allowed_users() -> set:
    return {u.strip() for u in (os.environ.get("SLACK_ALLOWED_USER_IDS") or "").split(",") if u.strip()}


def authorized(user_id: str, channel_id: str, card: dict | None) -> bool:
    """Default-deny. The user is on SLACK_ALLOWED_USER_IDS AND the channel is HQ or a business
    channel AND, when `card` is given, the click came from the channel that card was issued in.
    card=None checks user + channel only (used before the card is looked up)."""
    user_id, channel_id = str(user_id or ""), str(channel_id or "")
    if not user_id or not channel_id or user_id not in _allowed_users():
        return False
    if channel_id not in _channels():
        return False
    return card is None or str(card.get("channel") or "") == channel_id


def _seen(keys) -> bool:
    keys = [k for k in keys if k]
    with _LOCK:
        if any(k in _SEEN for k in keys):
            return True
        _SEEN.extend(keys)
    return False


def _expired(card) -> bool:
    return not isinstance(card, dict) or time.time() - (card.get("at") or 0) >= _CARD_TTL


def _claim(card_id, user):
    """Mark the card consumed on disk before anything runs. -> (card, None) or (None, why)."""
    with _LOCK:
        cards = _read("slack_cards.json")
        card = cards.get(card_id)
        if _expired(card):
            return None, "expired"
        if card.get("consumed"):
            return None, "already handled"
        card.update(consumed=True, consumedAt=time.time(), consumedBy=user)
        cards[card_id] = card
        if not _write("slack_cards.json", cards):
            return None, "could not record the tap. Nothing ran"
    return card, None


def _ephemeral(channel, user, text) -> None:
    if channel and user:
        _api("chat.postEphemeral", _token(), channel=channel, user=user, text=text)


def _refuse(channel, user, text, result=None) -> dict:
    _ephemeral(channel, user, text)
    return {"ok": False, "result": result or text}


def handle_interaction(payload: dict, envelope_id: str | None = None) -> dict:
    """Run one Slack button tap. -> {"ok": bool, "result": str}. Never raises.

    SECURITY: call this ONLY with a payload from a verified Socket Mode envelope (_dispatch, fed
    by the xapp-authenticated client). It trusts the payload's user, channel and value fields.
    Any HTTP / n8n path must first verify the Slack request signature (v0 HMAC-SHA256 with
    SLACK_SIGNING_SECRET, timestamp within 5 minutes) and drop the request otherwise.
    A claimed card with a Telegram twin also loses its Telegram buttons (C4, best effort)."""
    try:
        return _interaction(payload if isinstance(payload, dict) else {}, envelope_id)
    except Exception as e:  # noqa: BLE001
        print(f"[slack] tap error: {_redact(e)[:120]}", flush=True)
        return {"ok": False, "result": "error"}


def _interaction(payload, envelope_id):
    if payload.get("type") != "block_actions":
        return {"ok": False, "result": "ignored"}
    acts = payload.get("actions") or []
    act = acts[0] if acts and isinstance(acts[0], dict) else {}
    if _seen((envelope_id, payload.get("trigger_id"))):
        return {"ok": False, "result": "duplicate"}
    user = str((payload.get("user") or {}).get("id") or "")
    channel = str((payload.get("channel") or {}).get("id")
                  or (payload.get("container") or {}).get("channel_id") or "")
    value = str(act.get("value") or "")
    card_id = str(act.get("block_id") or "").split("#")[0]
    action, _, arg = value.partition(":")
    if not value and str(act.get("action_id") or "").startswith("url"):
        return {"ok": True, "result": "link"}      # a link button: Slack opened the page itself

    if not authorized(user, channel, None):
        print(f"[slack] tap REFUSED user={user or '?'} channel={channel or '?'}", flush=True)
        return _refuse(channel, user, "Not authorized")
    if mode() == "telegram":              # M1: rolled back (listener may still run): Telegram only
        return _refuse(channel, user, "Slack actions are paused. Tap it in Telegram.", "paused")
    card = get_card(card_id)
    if _expired(card):
        return _refuse(channel, user, "This card expired. Ask again.", "expired")
    if not authorized(user, channel, card) or value not in (card.get("actions") or []):
        print(f"[slack] tap REFUSED user={user} channel={channel} card={card_id}", flush=True)
        return _refuse(channel, user, "Not authorized")
    if action in LIVE_ACTIONS:            # menu / room buttons: every tap runs, the card stays
        key = (value, channel)
        with _LOCK:
            if key in _LIVE_BUSY:              # a double tap must not start a second agent turn
                busy = True
            else:
                busy = False
                _LIVE_BUSY.add(key)
        if busy:
            return _refuse(channel, user, "Already working on that one.", "busy")
        print(f"[slack] button {action} arg={arg[:40]!r} user={user} channel={channel}", flush=True)

        def run():                             # own thread: an agent turn must not hold the tap pool
            try:
                import slack_inbound
                slack_inbound.handle_button(action, arg, user, channel)
            finally:
                with _LOCK:
                    _LIVE_BUSY.discard(key)
        threading.Thread(target=run, daemon=True, name="slack-button").start()
        return {"ok": True, "result": action}
    if card.get("consumed"):
        return _refuse(channel, user, "Already handled.", "already handled")

    import telegram_io as tio
    if action == "pgo":                   # a Mac card runs a shell as the owner: owner ids only
        try:
            foreign = tio._foreign_mac_tap(arg, user)
        except Exception:  # noqa: BLE001 — cannot tell, so refuse
            foreign = True
        if foreign:
            return _refuse(channel, user, "Only the owner can run a Mac command")

    card, why = _claim(card_id, user)
    if why:
        return _refuse(channel, user, why[:1].upper() + why[1:] + ".", why)

    fn = tio._ACTIONS.get(action)
    if not fn:
        result = {"error": f"unknown action: {action}"}
    else:
        try:
            # pgo/pno tokens are bound to the chat they were issued in: the Telegram chat for a
            # mirrored card, "slack:<channel>" for a card born in Slack.
            chat = card.get("origin_chat") or f"slack:{channel}"
            result = fn(arg, chat) if action in ("pgo", "pno") else fn(arg)
            if not isinstance(result, dict):
                result = {"ok": True}
        except Exception as e:  # noqa: BLE001
            result = {"error": str(e)}

    try:  # audit trail, ids only (same call as telegram_io._handle_callback)
        import action_log
        who, biz = next(((a, b) for k, a, b in tio._TAP_AGENT if action.startswith(k)), ("slack", None))
        action_log.record_result(result, who, f"tap:{action}", business=biz,
                                 trigger="slack_tap", ref=arg, approval_required=True)
    except Exception:  # noqa: BLE001
        pass

    summary = _redact(tio._result_text(action, result))
    kept = [b for b in ((payload.get("message") or {}).get("blocks") or [])
            if isinstance(b, dict) and b.get("type") != "actions"]
    res = _api("chat.update", _token(), channel=channel,
               ts=card.get("ts") or (payload.get("container") or {}).get("message_ts"),
               text=summary[:3000],
               blocks=kept[:48] + [{"type": "section", "text": {"type": "mrkdwn", "text": _esc(summary)[:2900]}}])
    if not res.get("ok"):
        print(f"[slack] chat.update failed: {_redact(res.get('error'))[:120]}", flush=True)
    _drop_tg_buttons(card)
    return {"ok": not result.get("error"), "result": summary}


# ── Socket Mode listener (Task 5) ─────────────────────────────────────────────
# One client per connection. Every envelope is ACKed on the receiving thread first (Slack
# redelivers anything not acked in 3 s), then deduped on envelope_id + event_id/trigger_id and
# handed to a 4-worker pool (button taps: their own 2-worker pool). Logs carry envelope types and ids only — never a payload, a
# message body or a token. Reconnects with exponential backoff (1..60 s) until `stop` is set.
#
# Task 10 (box), in order, each an owner-approved box change:
#   1. pip3 install --break-system-packages slack_sdk==3.46.0
#   2. /opt/forge/forge-slack/config/slack.env (mode 600): SLACK_BOT_TOKEN, SLACK_APP_TOKEN,
#      SLACK_ALLOWED_USER_IDS (or set FORGE_SLACK_CONFIG_DIR to where they live)
#   3. /etc/default/forge-reios: FORGE_SLACK=1 (FORGE_CHAT_TRANSPORT stays telegram at first)
#   4. systemctl restart forge-reios; grep the log for "[slack] listener connected" and
#      "[slack] listener" errors; GET /api/health -> "slack": {"connected": true, ...}
_ROUTED = ("interactive", "slash_commands", "events_api")
# Buttons that never consume their card: "cmd:<command>" runs that command, "draft:<contactId>"
# asks the channel's agent for a reply draft (which itself comes back as a ✅ card).
LIVE_ACTIONS = ("cmd", "draft")
_LIVE_BUSY = set()                        # (button value, channel) running right now (guarded by _LOCK)
_ENV_TTL = 10 * 60
_ENV_MAX = 500
_BACKOFF_MIN, _BACKOFF_MAX = 1.0, 60.0
_POLL = 1.0                               # how often the loop checks the socket is still up
_STABLE = 60.0                            # a connection this old resets the backoff
_ENVELOPES = collections.OrderedDict()    # dedupe key -> first-seen epoch (guarded by _LOCK)
_STATUS = {"connected": False, "last_error": None, "started_at": None}
_WARNED = set()


def _log(msg) -> None:
    print(f"[slack] {msg}", flush=True)


def _warn_once(key, msg) -> None:
    if key not in _WARNED:
        _WARNED.add(key)
        _log(msg)


def status() -> dict:
    """Listener state for /api/health: connected, last_error (redacted), started_at."""
    return dict(_STATUS)


def _envelope_seen(keys) -> bool:
    """True if any key was seen in the last 10 min (ring of 500); else records them all."""
    keys = [str(k) for k in keys if k]
    now = time.time()
    with _LOCK:
        while _ENVELOPES and (len(_ENVELOPES) > _ENV_MAX
                              or now - next(iter(_ENVELOPES.values())) > _ENV_TTL):
            _ENVELOPES.popitem(last=False)
        if any(k in _ENVELOPES for k in keys):
            return True
        for k in keys:
            _ENVELOPES[k] = now
    return False


def _sdk_factory():
    """-> a no-arg builder of slack_sdk's builtin SocketModeClient, or None (logged once)."""
    try:
        from slack_sdk.socket_mode.builtin import SocketModeClient
    except Exception:  # noqa: BLE001 — missing on the box until Task 10
        _warn_once("sdk", "listener off: slack_sdk not installed "
                          "(pip3 install --break-system-packages slack_sdk==3.46.0)")
        return None
    app_token = (os.environ.get("SLACK_APP_TOKEN") or "").strip()
    if not app_token:
        _warn_once("app_token", "listener off: SLACK_APP_TOKEN not set")
        return None
    sdk_log = logging.getLogger("forge.slack.socket")
    sdk_log.setLevel(logging.WARNING)     # the SDK prints payloads at DEBUG; never let that on
    # auto_reconnect off: run_forever owns reconnects (one client per connection, own backoff).
    return lambda: SocketModeClient(app_token=app_token, logger=sdk_log, auto_reconnect_enabled=False)


def _inbound():
    """slack_inbound (Task 6), or None while it doesn't exist / fails to import (logged once)."""
    try:
        import slack_inbound
        return slack_inbound
    except Exception as e:  # noqa: BLE001
        _warn_once("inbound", f"slack_inbound unavailable ({type(e).__name__}); "
                              "slash commands and messages ignored")
        return None


def _respond(payload, body) -> None:
    """Show a slash command's reply to the person who typed it (response_url, else ephemeral)."""
    text = str((body or {}).get("text") or "")
    if not text:
        return
    url = str(payload.get("response_url") or "")
    if requests is not None and url.startswith("https://hooks.slack.com/"):
        try:
            requests.post(url, json={"response_type": "ephemeral", "text": text[:3000]}, timeout=10)
            return
        except Exception as e:  # noqa: BLE001
            _log(f"slash reply failed: {type(e).__name__}")
    _ephemeral(payload.get("channel_id"), payload.get("user_id"), text[:3000])


def _dispatch(kind, payload, envelope_id) -> None:
    """Worker thread: run one envelope. Never raises."""
    try:
        if kind == "interactive":
            handle_interaction(payload, envelope_id=envelope_id)
            return
        mod = _inbound()
        if mod is None:
            return
        if kind == "slash_commands":
            _respond(payload, mod.handle_slash(payload))
        else:
            event = payload.get("event")
            mod.handle_message_event(event if isinstance(event, dict) else {})
    except Exception as e:  # noqa: BLE001 — type only: a message could ride in the error text
        _log(f"dispatch {kind} failed: {type(e).__name__}")


def _on_request(client, req, pool, tap_pool=None) -> None:
    """Receiving thread: ACK first, then dedupe and hand off (taps to `tap_pool`, so slow agent
    turns on `pool` never delay a button). Never raises."""
    eid = str(getattr(req, "envelope_id", None) or "")
    kind = str(getattr(req, "type", None) or "")
    if eid:
        try:
            client.send_socket_mode_response({"envelope_id": eid})
        except Exception as e:  # noqa: BLE001
            _log(f"ack failed type={kind} envelope={eid}: {type(e).__name__}")
    try:
        if kind not in _ROUTED:
            _log(f"ignored envelope type={kind or '?'}")
            return
        payload = getattr(req, "payload", None)
        if not isinstance(payload, dict):
            return
        if _envelope_seen((eid, payload.get("event_id"), payload.get("trigger_id"))):
            _log(f"duplicate envelope type={kind} envelope={eid} retry={getattr(req, 'retry_attempt', None)}")
            return
        (tap_pool if kind == "interactive" and tap_pool else pool).submit(_dispatch, kind, payload, eid)
    except Exception as e:  # noqa: BLE001
        _log(f"envelope type={kind} not dispatched: {type(e).__name__}")


def run_forever(stop: threading.Event | None = None, client_factory=None) -> None:
    """Socket Mode loop. `client_factory()` builds a client with slack_sdk's builtin surface:
    socket_mode_request_listeners (list of fn(client, req)), connect(), is_connected(), close(),
    send_socket_mode_response(dict). Default = slack_sdk; missing SDK/token -> returns. Never raises."""
    from concurrent.futures import ThreadPoolExecutor
    stop = stop or threading.Event()
    factory = client_factory or _sdk_factory()
    if factory is None:
        return
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="slack-worker")
    tap_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="slack-tap")   # taps never queue behind agent turns
    _STATUS.update(started_at=time.time(), connected=False)
    delay = _BACKOFF_MIN
    try:
        while not stop.is_set():
            client, up_at = None, None
            try:
                client = factory()
                client.socket_mode_request_listeners.append(
                    lambda c, r: _on_request(c, r, pool, tap_pool))
                client.connect()
                up_at = time.time()
                _STATUS.update(connected=True, last_error=None)
                _log("listener connected")
                while not stop.is_set() and client.is_connected():
                    stop.wait(_POLL)
            except Exception as e:  # noqa: BLE001
                _STATUS["last_error"] = _redact(f"{type(e).__name__}: {e}")[:200]
                _log(f"listener error: {_STATUS['last_error']}")
            finally:
                _STATUS["connected"] = False
                if client is not None:
                    try:
                        client.close()
                    except Exception:  # noqa: BLE001
                        pass
            if stop.is_set():
                break
            if up_at and time.time() - up_at >= _STABLE:
                delay = _BACKOFF_MIN
            _log(f"listener disconnected; reconnect in {delay:.0f}s")
            stop.wait(delay)
            delay = min(_BACKOFF_MAX, delay * 2)
    finally:
        pool.shutdown(wait=False)
        tap_pool.shutdown(wait=False)
        _STATUS["connected"] = False
        _log("listener stopped")
