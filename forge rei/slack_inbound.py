"""slack_inbound.py — what the owner says in Slack reaches the same routers Telegram uses (Task 6).

Spec C7: reuse the routers, not the Telegram-shaped handler. Nothing here edits telegram_io.
  • /forge <text>, or any Telegram command registered as its own Slack slash command (/today,
    /task, /agents, /marcus …; payload["command"] says which) -> help · bind · agents · ace ·
    chats · whoami · task · zero-Claude quick commands (telegram_agent.quick) · wholesale ops
    (telegram_ops.route) · else the agent chat below.
  • plain text in a FORGE channel or the bot's DM -> wholesale plain-English ops (wholesale
    channel, or HQ/DM while wholesale has none — Telegram's rule) · else the business partner:
    the owner's turn runs on agent_gateway.chat_local(origin "slack") like Telegram's, falling
    back to telegram_agent.chat.
Chat string = f"slack:{channel_id}" everywhere: telegram_ops sessions, telegram_agent.chat
(pending ✅ cards are bound to it) and the tap (slack_io passes the same string to confirm).
Sessions share telegram_io._AGENT_SESS under that namespaced key, so the ✅ result hook
(telegram_io._on_partner_result) lands in the same history.

Called on slack_io's listener worker threads (the envelope is already acked), so the work
runs inline. Owner only (SLACK_ALLOWED_USER_IDS); bot posts and any subtype are ignored (no
reply loops). Only "message" events are handled: app_mention duplicates a channel message.
Not ported: /menu's persistent reply keyboard (Slack has none; its native "/" menu lists the
registered slash commands instead) and /unbind (unbind = clear SLACK_CHANNEL_<BIZ> / slack.json).
"""
from __future__ import annotations

import html
import re
import threading

import slack_io

_QUICK = ("status", "starts", "logins", "pin", "board")      # telegram_agent.quick, zero Claude
_BIND = slack_io.BUSINESSES + ("hq",) + slack_io.TOPIC_KEYS
_AGENTS = ("scout", "marcus", "atlas", "dyson", "eco", "solomon", "midas", "orion")
_MENTION = re.compile(r"^\s*<@[A-Z0-9]+>\s*")
_CHAT_LOCKS = {}


def _ops_commands() -> list[str]:
    """Every slash command telegram_ops.route runs, read from its own table (_CMD_RE)."""
    import telegram_ops
    m = re.search(r"\^/\(([^)]*)\)", telegram_ops._CMD_RE.pattern)
    return m.group(1).split("|") if m else []


def _COMMANDS() -> set:
    """Every word that works as /<word> or /forge <word>."""
    return {"forge", "help", "bind", "agents", "who", "ace", "chats", "whoami", "id", "menu", "task", "roster",
            *_QUICK, *_AGENTS, *_ops_commands()}


def help_text() -> str:
    ops = " · ".join(f"`{c}`" for c in _ops_commands())
    return ("*FORGE in Slack* — `/forge <command>`\n"
            f"*Ops* (wholesale channel, or HQ while wholesale has none): {ops}\n"
            "  e.g. `/forge today` · `/forge text arthur: I can call at 3` · `/forge done 3`\n"
            "*No AI*: " + " · ".join(f"`{c}`" for c in _QUICK) + " (`logins`/`pin` take a name)\n"
            "*Crew*: `agents` roster · `task <job>` files a real job for the active agent · "
            "`ace` (off|shadow|supervised|full) · `chats` · `whoami` · `menu` (buttons) · "
            "`roster` (in a daycare room)\n"
            "Each also works as its own command (`/today`, `/task …`, `/solomon …`) once it's in the app's "
            "Slash Commands.\n"
            "*Agents*: in a business channel just talk to its partner. In HQ or a DM start with a name — "
            "`solomon, how many tours?` — HQ talks to Orion by default. Anything that writes comes back "
            "as a ✅ card. In the wholesale channel plain English works too: `text arthur I can call at 3`.\n"
            "*Setup*: in a channel, `/forge bind daycare` (agency · wholesale · dropship · hq).")


def _eph(text) -> dict:
    return {"response_type": "ephemeral", "text": text}


def _owner(user) -> bool:
    return bool(user) and str(user) in slack_io._allowed_users()


def _clean(text) -> str:
    return html.unescape(_MENTION.sub("", str(text or ""))).strip()


def _poster(channel, thread=None):
    """send(text, buttons=None) into `channel`. Taps only count in HQ/business channels
    (slack_io.authorized), so a card asked for in a DM goes to HQ, still bound to this DM's chat."""
    tappable = channel in slack_io._channels()
    chat = f"slack:{channel}"

    def post(text, buttons=None):
        if buttons and not tappable:
            hq = slack_io.chat_for(None)
            ok = bool(hq) and slack_io.send(text, buttons=buttons, channel=hq, origin_chat=chat)
            slack_io.send("🟡 Approval card posted in HQ — tap it there." if ok else
                          "⚠️ Can't post the approval card: no HQ channel. Run <code>/forge bind hq</code> "
                          "in #forge-hq.", channel=channel, thread_ts=thread)
            return ok
        return slack_io.send(text, buttons=buttons, channel=channel, thread_ts=thread)
    return post


def _bind_refusal(biz, channel) -> str | None:
    """Why `channel` may not become a FORGE channel, or None. Cards, alerts (phone numbers, ad
    spend) and Mac output land there: private, not shared outside the workspace, not a DM;
    HQ also owner-only (every member on SLACK_ALLOWED_USER_IDS, or this bot). Any Slack API
    error refuses (fail closed). Needs bot scopes groups:read (+ channels:read to see public)."""
    tok = slack_io._token()
    info = slack_io._api("conversations.info", tok, channel=channel)
    ch = info.get("channel") if info.get("ok") else None
    if not isinstance(ch, dict):
        return (f"couldn't check this channel with Slack ({slack_io._redact(info.get('error'))[:60]}). "
                "Invite the FORGE bot to it, then try again.")
    if ch.get("is_im") or ch.get("is_mpim"):
        return "DMs and group DMs can't be FORGE channels. Use a private channel."
    if not ch.get("is_private"):
        return "this channel is public. Use a private channel."
    if any(ch.get(k) for k in ("is_shared", "is_ext_shared", "is_org_shared", "is_pending_ext_shared")):
        return "this channel is shared outside this workspace. Use a private, unshared channel."
    if biz != "hq":
        return None
    me = slack_io._api("auth.test", tok)
    mem = slack_io._api("conversations.members", tok, channel=channel, limit=1000)
    members = mem.get("members") if mem.get("ok") else None
    if not me.get("ok") or not me.get("user_id") or not isinstance(members, list) \
            or (mem.get("response_metadata") or {}).get("next_cursor"):
        err = me.get("error") if not me.get("ok") else mem.get("error") or "member list"
        return f"couldn't check who is in this channel ({slack_io._redact(err)[:60]})."
    strangers = [m for m in members if m not in slack_io._allowed_users() | {me["user_id"]}]
    if strangers:
        return (f"HQ must be owner-only, and {len(strangers)} member(s) aren't on "
                "SLACK_ALLOWED_USER_IDS. Remove them first.")
    return None


# ── /forge ────────────────────────────────────────────────────────────────────
def handle_slash(payload: dict) -> dict:
    """/forge <text>. -> ack body for the person who typed it ({} when the answer went to the
    channel). Never raises."""
    try:
        return _slash(payload if isinstance(payload, dict) else {})
    except Exception as e:  # noqa: BLE001
        print(f"[slack] /forge failed: {type(e).__name__}", flush=True)
        return _eph("⚠️ That didn't run. Try again.")


def _slash(p):
    user, channel = str(p.get("user_id") or ""), str(p.get("channel_id") or "")
    text = _clean(p.get("text"))
    cmd = str(p.get("command") or "/forge").strip().lower().lstrip("/")
    if cmd and cmd != "forge":                  # /today x == /forge today x
        text = f"{cmd} {text}".strip()
    print(f"[slack] slash /{cmd} verb={text.split(' ')[0][:20].lower()!r} user={user or '?'} "
          f"channel={channel or '?'} owner={_owner(user)}", flush=True)     # ids + verb only, never the text
    if not _owner(user):
        print(f"[slack] /forge REFUSED user={user or '?'} channel={channel or '?'}", flush=True)
        return _eph("Not authorized")
    verb, _, rest = text.lower().partition(" ")
    if verb in ("", "help"):
        return _eph(help_text())
    if verb == "bind":
        biz = rest.strip()
        if biz not in _BIND:
            return _eph("Which business? `/forge bind daycare` (agency · wholesale · dropship · hq)")
        if not channel.startswith(("C", "G")):
            return _eph("Run `/forge bind <business>` inside that business's channel, not a DM.")
        why = _bind_refusal(biz, channel)
        if why:
            print(f"[slack] bind {biz} REFUSED channel={channel}", flush=True)
            return _eph(f"Bind refused: {why} Nothing changed.")
        try:
            slack_io.bind(biz, channel)
        except ValueError as e:
            return _eph(f"Bind failed: {e}")
        print(f"[slack] bound {biz} -> {channel}", flush=True)
        import telegram_io as tio
        partner = "Orion" if biz == "hq" else tio._BIZ_AGENT[biz.split("-")[0]].title()
        return _eph(f"✅ This channel is now *{biz}*. Its alerts and ✅ cards land here; "
                    f"plain messages go to *{partner}*.")
    dm = channel.startswith("D")
    biz = slack_io.business_of(channel)
    if not dm and biz is None:
        return _eph("Use /forge in a FORGE channel (bind it first) or in a DM with me.")
    _handle_text(text, channel, None if biz in (None, "hq") else biz, p.get("thread_ts"), slash=True, user=user)
    return {}


# ── plain messages ────────────────────────────────────────────────────────────
def handle_message_event(event: dict) -> None:
    """One Events API `message` event. Owner text in a FORGE channel or the bot's DM -> agent.
    Never raises."""
    try:
        _message(event if isinstance(event, dict) else {})
    except Exception as e:  # noqa: BLE001
        print(f"[slack] message failed: {type(e).__name__}", flush=True)


def _message(ev):
    if ev.get("type") != "message" or ev.get("bot_id") or ev.get("subtype"):
        return                                  # our own posts, edits, joins: never answer
    user, channel = str(ev.get("user") or ""), str(ev.get("channel") or "")
    text = _clean(ev.get("text"))
    if not text or not channel or not _owner(user):
        return
    biz = slack_io.business_of(channel)
    first, _, rest = text.partition(" ")
    if ev.get("channel_type") != "im" and biz is None \
            and not (first.lower() == "/forge" and rest.lower().startswith("bind ")):
        return                                  # not a FORGE channel (a typed bind may make it one)
    if first.startswith("/") and first[1:].lower() in _COMMANDS():
        # Slack runs no slash commands in threads, on some phones, or when its popup swallowed the
        # command: the literal "/task x" arrives as a message. Run it as the command it is.
        body = _slash({"command": first, "text": rest, "user_id": user, "channel_id": channel,
                       "thread_ts": ev.get("thread_ts")})
        if body.get("text"):
            _poster(channel, ev.get("thread_ts"))(body["text"])
        return
    _handle_text(text, channel, None if biz in (None, "hq") else biz,
                 ev.get("thread_ts"), slash=False, user=user)


# ── shared: commands, agent pick, business scope, the turn ────────────────────
def _roster(chat, chat_biz) -> str:
    """Telegram /agents: the crew (a business channel lists only its own), active one marked."""
    import telegram_io as tio
    cur = (tio._AGENT_SESS.get(chat) or {}).get("agent") or tio._BIZ_AGENT.get(chat_biz) or "orion"
    lines = ["🕹 <b>Your crew</b> — say a name, then just talk:"]
    for aid, emo, blurb in tio._AGENT_ROSTER:
        if chat_biz and tio._agent_business(aid) != chat_biz:
            continue
        lines.append(f"{emo} <code>{aid}</code> — {blurb}" + ("  ← active" if aid == cur else ""))
    lines.append("\n<code>/forge task …</code> hands the active agent a job.")
    return "\n".join(lines)


def _ace(arg) -> str:
    """Telegram /ace: status, or set off|shadow|supervised|full (ace.set_mode validates)."""
    import ace
    if not arg:
        st = ace.status()
        return (f"🤖 ACE mode: <b>{str(st.get('mode', 'off')).upper()}</b> · sent today {st.get('sentToday', 0)}\n"
                "Set with <code>/forge ace off|shadow|supervised|full</code>")
    res = ace.set_mode(arg.split()[0])
    if res.get("error"):
        return "⚠️ " + str(res["error"])
    return (f"🤖 ACE → <b>{str(res.get('mode', '?')).upper()}</b>"
            + (" — drafts queue for your approval, no auto-send" if res.get("mode") == "shadow" else ""))


def _chats() -> str:
    lines = ["📂 <b>Slack channels</b>"]
    for b in slack_io.BUSINESSES + ("hq",):
        ch = slack_io.chat_for(b) if b != "hq" else slack_io.chat_for(None)
        own = b == "hq" or slack_io.business_of(ch) == b
        lines.append(f"{b} — " + (f"✅ <code>{ch}</code>" if ch and own else "→ HQ (not bound)"))
    for k in slack_io.TOPIC_KEYS + (slack_io.AMT_KEY,):
        ch = slack_io.topic_channel(k)
        lines.append(f"  {k} — " + (f"✅ <code>{ch}</code>" if ch else f"→ {k.split('-')[0]} channel"))
    lines.append("\nIn a private channel with me: <code>/forge bind daycare</code> (agency · wholesale · dropship · hq).")
    return "\n".join(lines)


def _task(chat, agent_id, title, post) -> bool:
    """Telegram /task: file a real job. Agency agents (Dyson/Eco) queue on the Agency board and stop
    there; everyone else is filed in the hub (inbox + dashboard board) and also answered in chat.
    -> True when the caller should still run the chat turn."""
    import telegram_io as tio
    if agent_id in tio._AGENCY_AGENTS:
        tfn = tio._AGENCY_TASK.get("fn")
        if not tfn:
            post("Agency tasks aren't wired up yet.")
            return False
        try:
            res = tfn(agent_id, title) or {}
        except Exception as e:  # noqa: BLE001
            res = {"error": str(e)}
        if res.get("error"):
            post(f"⚠️ {tio._esc(str(res['error']))}")
        else:
            plan = (res.get("task") or {}).get("plan") or res.get("plan") or res.get("reply") or "queued"
            post(f"📋 <b>Queued for {agent_id.title()}</b> — it's on the Agency board.\n{tio._esc(str(plan)[:1200])}")
        return False
    try:
        import agents_hub
        filed = not (agents_hub.send_task(agent_id, title) or {}).get("error")
    except Exception:  # noqa: BLE001
        filed = False
    if filed:
        post(f"📥 <b>Filed for {agent_id.title()}</b> — in their inbox, they pick it up on the next run.\n"
             f"<i>{tio._esc(title)}</i>")
    return True


_MENU = {"daycare": ("board", "starts", "roster tours", "roster quotes", "roster enrolled"),
         "wholesale": ("today", "hot", "proposals", "report"),
         None: ("status", "agents", "chats")}


def _menu(chat_biz):
    """Quick-tap buttons (Telegram's /menu keyboard). Each runs its command; the card stays."""
    cmds = _MENU.get(chat_biz) or _MENU[None]
    return ("<b>Quick taps</b> — or just tell me what you need.",
            [[{"text": c.title(), "callback_data": f"cmd:{c}"} for c in cmds]])


def handle_button(action, arg, user, channel) -> None:
    """A LIVE_ACTIONS tap (slack_io already checked owner + channel + card). Never raises."""
    try:
        if action == "draft":
            import slack_rooms
            slack_rooms.draft(arg, channel, user)
            return
        body = _slash({"command": "/forge", "text": arg, "user_id": user, "channel_id": channel})
        if body.get("text"):
            _poster(channel)(body["text"])
    except Exception as e:  # noqa: BLE001
        print(f"[slack] button {action} failed: {type(e).__name__}", flush=True)


def _wholesale_here(chat_biz) -> bool:
    """Telegram's rule: ops run in the wholesale channel, or in HQ/a DM while wholesale has none."""
    return chat_biz == "wholesale" or (
        chat_biz is None and slack_io.business_of(slack_io.chat_for("wholesale")) != "wholesale")


def _handle_text(text, channel, chat_biz, thread, slash, user=""):
    """chat_biz = the channel's business, None for HQ / a DM (any agent by name)."""
    import telegram_io as tio
    chat, post = f"slack:{channel}", _poster(channel, thread)
    word, arg, task = "", "", None
    if slash:
        first, _, arg = text.partition(" ")
        word, arg = first.lower().lstrip("/"), arg.strip()
        if word in _AGENTS:
            text = "/" + text.lstrip("/")       # the alias switch below takes "/solomon …"
        elif word in ("agents", "who"):
            post(_roster(chat, chat_biz))
            return
        elif word == "ace":
            post(_ace(arg.lower()))
            return
        elif word == "chats":
            post(_chats())
            return
        elif word in ("whoami", "id"):
            post(f"channel: <code>{channel}</code>\nyour id: <code>{user}</code>")
            return
        elif word == "menu":
            post(*_menu(chat_biz))
            return
        elif word == "roster":
            import slack_rooms
            post(*slack_rooms.roster(arg.lower() or slack_io.topic_of(channel) or ""))
            return
        elif word == "task":
            if not arg:
                post("<code>/forge task what you need done</code> — goes to the active agent.")
                return
            task = arg
        elif word in _QUICK:
            import telegram_agent
            out = telegram_agent.quick("/" + word, arg, chat, chat_biz)
            if out:
                post(out[0])
                for c in out[1] or []:
                    post(*telegram_agent.card(c))
                return

    ops = slash and word in _ops_commands()
    if task is None and _wholesale_here(chat_biz):
        import telegram_ops
        if telegram_ops.route("/" + text if ops else text, chat, post):
            return
    elif ops:
        post(f"<code>/forge {word}</code> is a wholesale command — run it in the wholesale channel.")
        return

    default = tio._BIZ_AGENT.get(chat_biz) or "orion"
    sess = tio._AGENT_SESS.setdefault(chat, {"agent": default, "history": []})
    if chat_biz and tio._agent_business(sess["agent"]) != chat_biz:
        sess["agent"] = default                 # a business channel only ever gets its own agents
    if task is not None:
        if _task(chat, sess["agent"], task, post):
            _turn(chat, sess["agent"], task, post, user)
        return
    low, switched = text.lower(), False
    for alias, aid in tio._AGENT_ALIASES.items():
        if low == alias or low.startswith(alias + " "):
            sess["agent"], text, switched = aid, text[len(alias):].strip(), True
            break
    if not switched:
        m = tio._AGENT_TRIGGER.match(text)
        if m:
            sess["agent"], text, switched = (m.group(1) or m.group(3)).lower(), (m.group(2) or "").strip(), True
    if not switched and not chat_biz:          # HQ / DM: the name alone is enough
        named = tio._named_agent(text)
        if named:
            (sess["agent"], text), switched = named, True
    if switched and chat_biz and tio._agent_business(sess["agent"]) != chat_biz:
        asked = sess["agent"]
        sess["agent"] = default
        where = "the HQ channel" if asked == "orion" else "its own channel"
        post(f"{asked.title()} works in {where} — ask there. This channel is "
             f"{tio._BIZ_LABEL[chat_biz]} with <b>{default.title()}</b>.")
        return
    if switched and not text:
        post(f"Now talking to <b>{sess['agent'].title()}</b>. What do you need?\n"
             "<code>/forge task …</code> files it as a real job.")
        return
    _turn(chat, sess["agent"], text, post, user)


_BULLET = re.compile(r"^\s*(?:[-•*]|\d{1,2}[.)])\s+")
_ABBR = {"mr", "mrs", "ms", "dr", "st", "ave", "no", "vs", "etc", "approx", "a.m", "p.m", "e.g", "i.e",
         "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
         "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun"}
MAX_SENTENCES, MAX_BULLETS = 2, 5
_MORE = " (more: just ask)"


def _sentences(text) -> list[str]:
    """Split prose into sentences. An initial ("Cecil B. Moore"), a known abbreviation ("Nov. 13",
    "St.") or a number ("2.5") never ends one."""
    out, start = [], 0
    for m in re.finditer(r"[.!?][\"”’)]*\s+(?=[\"“(]?[A-Z0-9])", text):
        word = re.split(r"[\s(\"“]", text[start:m.start()])[-1].lower()
        if text[m.start()] == "." and (len(word) <= 1 or word in _ABBR or word[-1:].isdigit() and text[m.end():m.end() + 1].isdigit()):
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    tail = text[start:].strip()
    return out + ([tail] if tail else [])


def clamp(reply) -> str:
    """The Slack reply cap, enforced here because a prompt alone drifts: at most MAX_SENTENCES
    sentences, or (when the agent answered with a list) its lead line + MAX_BULLETS bullets and
    nothing after them. A cut reply ends with "(more: just ask)" so nothing is hidden silently."""
    text = str(reply or "").strip()
    lines = [ln for ln in text.split("\n") if ln.strip()]
    marks = [bool(_BULLET.match(ln)) for ln in lines]
    if sum(marks) >= 2:
        first = marks.index(True)
        lead = lines[:first][-1:]                       # one lead line at most
        bullets = [ln for ln, b in zip(lines[first:], marks[first:]) if b]
        last = len(lines) - 1 - marks[::-1].index(True)
        cut = len(bullets) > MAX_BULLETS or last < len(lines) - 1 or first > 1
        short = [" ".join(_sentences(b)[:MAX_SENTENCES]) for b in bullets[:MAX_BULLETS]]
        cut = cut or short != bullets[:MAX_BULLETS]
        lead = [" ".join(_sentences(ln)[:1]) for ln in lead]
        return "\n".join(lead + short) + (_MORE if cut else "")
    sents = _sentences(" ".join(lines))
    if len(sents) <= MAX_SENTENCES:
        return text
    return " ".join(sents[:MAX_SENTENCES]) + _MORE


def _turn(chat, agent_id, text, post, user=""):
    """One partner turn, inline on the listener's worker thread (renamed for the agent so
    cost_tracker bills it like a Telegram turn). One turn at a time per chat. The owner's turn
    goes through agent_gateway.chat_local first (same job, tools and gates as Telegram's; it
    records the turn and sends its own ✅ cards to the business channel); None = old path."""
    import telegram_io as tio
    with _CHAT_LOCKS.setdefault(chat, threading.Lock()):
        sess = tio._AGENT_SESS.setdefault(chat, {"agent": agent_id, "history": []})
        try:
            import agents_history
            stored = agents_history.recent_for_context(agent_id)
            hist = stored or list(sess["history"])
        except Exception:  # noqa: BLE001
            agents_history, stored, hist = None, [], list(sess["history"])
        me = threading.current_thread()
        name, me.name = me.name, agent_id
        out, recorded = None, False
        try:
            import agent_gateway
            if agent_gateway.is_owner(user):
                out = agent_gateway.chat_local(agent_id, text, "slack", history=None if stored else hist)
                recorded = out is not None
        except Exception:  # noqa: BLE001 — the old path still answers
            out = None
        try:
            if out is None:
                import telegram_agent
                out = telegram_agent.chat(agent_id, text, hist, chat) or {}
        except Exception as e:  # noqa: BLE001
            out = {"reply": f"({agent_id.title()} hit an error: {type(e).__name__})", "error": True}
        finally:
            me.name = name
        reply, cards = clamp(out.get("reply") or "On it."), out.get("cards") or []
        if not out.get("error"):                # an outage message is not a conversation turn
            sess["history"] = (sess["history"] + [{"role": "user", "text": text},
                                                  {"role": "assistant", "text": reply}])[-12:]
            if agents_history is not None and not recorded:
                try:
                    agents_history.record(agent_id, text, reply, via="slack")
                except Exception:  # noqa: BLE001
                    pass
        post(f"<b>{agent_id.title()}</b>\n{tio._esc(reply.replace('**', ''))}")
        if cards:
            import telegram_agent
            for c in cards:
                post(*telegram_agent.card(c))
