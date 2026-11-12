# Feed 1 — telegram_io.py interface sheet (for a Slack mirror)

File: `/Volumes/AgentDrive/claude/forge-rei-dash/forge rei/telegram_io.py` (1398 lines). All line refs below are to it.
Read fully. Tests run (see section 8). Anything not verified is marked Unknown.

## 0. Module facts
- stdlib only. Config from env: `TELEGRAM_BOT_TOKEN` (:78), `TELEGRAM_CHAT_ID` (:82, HQ chat), `TELEGRAM_ALLOWED_IDS` (:86), `TELEGRAM_CHAT_<BIZ>` (:136), `TELEGRAM_AGENT_BOT_TOKEN` (:234). Env file `forge-telegram/config/telegram.env` folded in at import via `os.environ.setdefault` (:74).
- One global `_LOCK = threading.Lock()` (:37). NOT reentrant. Never call `_load/_save/_biz_chats/_dedupe_*/_set_error` while already holding it = deadlock. `_biz_chats()` takes the lock itself (:132), so do not call it inside a `with _LOCK:` block.
- Every public sender is best-effort: returns dict, never raises (except `_api`, which raises).
- Text format everywhere = Telegram HTML (`<b> <i> <code> <a href>`, entities `&amp; &lt; &gt;` via `_esc` :226). A Slack renderer must convert HTML to mrkdwn and unescape.

## 1. Function sheet

| Fn | Signature | Returns | Side effects | Thread-safety | Body (3 lines) |
|---|---|---|---|---|---|
| `_api` :240 | `_api(method, payload, timeout=15, token=None)` | parsed JSON dict (`{}` if empty body). RAISES RuntimeError("telegram not configured") if no token, urllib errors on HTTP/transport | one HTTPS POST to `api.telegram.org/bot<token>/<method>` | stateless, safe | token = arg or `_token()`; POST json body; json-decode response. URL carries the token (so exceptions can contain it, see section 9) |
| `chat_for` :142 | `chat_for(business=None)` | chat id str: bound biz chat, else HQ `_chat_id()` | reads state file (under lock via `_biz_chats`) | safe | lowercases business; `_biz_chats().get(b) or _chat_id()` |
| `_biz_chats` :130 | `_biz_chats()` | `{business: chat_id_str}` for bound businesses only | reads state file | takes `_LOCK` (do not nest) | state `bizChats` first, then env `TELEGRAM_CHAT_<BIZ>` overrides; drops empties |
| `_authorized` :92 | `_authorized(from_id, chat_id)` | bool | none (calls `_biz_chats`, `_allowed_ids`) | safe | default-deny; chat must be HQ or a bound biz chat; if allowlist set then from_id in allowlist; biz chat w/o allowlist = only operator (HQ id == user id); else DM fallback chat==from==HQ |
| `send` :333 | `send(text, buttons=None, dedupe_key=None, business=None)` | `{"error":str}` (not configured / API fail / exception) or `{"ok":True,"skipped":"dedupe"}` or `{"ok":True,"messageId":int|None}` | sendMessage (HTML, `disable_web_page_preview`, timeout 10); on success commits dedupe, sets `lastSentAt`, clears `lastError`; on fail `_set_error` | blocking network call in caller thread; state writes under lock; dedupe check+commit NOT atomic (two threads same key can both send) | guard `configured()` (needs token AND HQ chat id); `_dedupe_seen` gate; build payload with `chat_for(business)`, `reply_markup={"inline_keyboard": buttons}` if buttons; no text length cap (Telegram 4096 limit unhandled here) |
| `send_biz` :372 | `send_biz(business, text, buttons=None, dedupe_key=None)` | same as `send` | same as `send` | same | one-line wrapper: `send(text, buttons=..., dedupe_key=..., business=business)`. Resolved at call time through module global `send`, so tests that replace `telegram_io.send` also intercept `send_biz` |
| `send_photo` :380 | `send_photo(business, image_url, caption, buttons=None, dedupe_key=None)` | `{"ok":True,"photo":True,"messageId"}`; or `{"ok":True,"skipped":"dedupe"}`; or `{"error":"telegram not configured"}`; on photo failure returns `send()` result plus `"photo":False,"photoError"` | sendPhoto by URL (timeout 20, HTML caption cut to `CAPTION_MAX`=1024 :377); on failure records error then FALLS BACK to `send()` with text `caption + "\n\n🖼 <a href=...>Image</a>"` | same as send | dedupe gate; sendPhoto; success commits dedupe and `lastSentAt`; failure `_set_error("sendPhoto: ...")` then `send(...)`. Beware double-mirror: fallback goes through `send` |
| `send_test` :415 | `send_test()` | `send()` result | sends "✅ FORGE REI OS connected to Telegram. Alerts are live." to HQ | same | `return send("...")` (no business, no dedupe). Called by POST route connector.py:4205 |
| `set_actions` :421 | `set_actions(d)` | None | REBINDS global `_ACTIONS = dict(d)` (replaces, does not merge) if `d` is dict | rebind is atomic under GIL; readers read global each call | connector calls it once at import (connector.py:2384); daycare_ads_tg handlers are merged in by the connector (daycare_ads_tg.py:619) |
| `_ACTIONS` :57 | `dict[str, callable]` action prefix -> `fn(arg)` (or `fn(arg, chat_id)` for `pgo`/`pno`) returning dict `{ok|error|message|apply}` | | module global; tests read/restore it directly (`test_telegram_ace.py:51,83`) | | Keys known from connector: approve, mdismiss, handoff, scoutdismiss, skillgo, skillno, ace*, dyson*, reqdismiss, ops*, pgo, pno, ads*. Full key list Unknown (only read the first lines of connector.py:2384) |
| `_event_class` :430 | `_event_class(msg)` | one of `hot_lead proposal missed_sweep skill_proposal edit_request dyson_plan handoff agency` or None | none | pure | `data.type` in the 6 types wins; else `msg.kind=="handoff"`; else `msg.from in (dyson, eco)` -> "agency"; else None (skip) |
| `_buttons_for` :485 | `_buttons_for(cls, data)` | `list[list[{"text":str,"callback_data":str}]]` or None | none | pure | per class returns a vertical list of 1-button rows (proposal: approve/mdismiss; hot_lead: handoff/scoutdismiss; skill_proposal: skillgo/skillno; edit_request: dysonplan/reqdismiss; dyson_plan: dysongo/dysonno). Needs `pid`/`convId`/`requestId`/`draftId` else None |
| `_compose_text` :563 | `_compose_text(msg, data)` | HTML str (parts joined by blank line) | none | pure | edit_request/dyson_plan -> `_compose_agency_text` (:521); else `msg.text` + `<b>name</b> · phone` + `💬 <b>Seller:</b> "..."` (400 char cut) + `✍️ <b>Marcus's draft:</b> "..."` |
| `on_bus_message` :590 | `on_bus_message(msg)` | `{"ok":True,"queued":True}` or None. Never raises | spawns daemon `threading.Thread(target=send, args=(text, buttons), kwargs={dedupe_key, business=_CLASS_BUSINESS.get(cls)})` | thread-per-message, non-blocking so it is safe under Marcus' engine lock. Registered at connector.py:1313 `agent_bus.register_notifier(telegram_io.on_bus_message)` | guards: dict msg, `configured()`, class not None, toggle on (`toggles.get(cls, True)`), not quiet hours, proposals warm+ only; builds buttons/text; `dedupe_key = f"{cls}:{pid or convId or requestId or draftId or msg.id}"` |
| `_handle_callback` :673 | `_handle_callback(cq, token=None, agent_chat=False)` | None | auth check; dispatch `_ACTIONS[action](arg)`; `action_log.record_result(...)` (ids only); `answerCallbackQuery`; then `editMessageCaption` (photo card) or `editMessageText` (appends result footer, strips keyboard) | runs on the poll thread; one tap at a time per loop | `cq` = Telegram callback_query dict (`id`, `from.id`, `message.{chat.id,message_id,text,caption,photo}`, `data`). `data` is `"action:arg"` (`partition(":")`). Refused taps print an id-only log line (:694). Result label from `_result_text` (:635). Telegram-coupled; a Slack tap handler cannot reuse it as is |
| `_TAP_AGENT` :665 | tuple of `(action_prefix, agent, business)` | | audit labelling only (prefix match via `startswith`) | const | maps tap prefix to the agent name for `action_log` |
| `register_commands` :868 | `register_commands()` | None | `setMyCommands` for alerts bot and agent bot (if set) | called once at boot, connector.py:5912 | iterates `{_token(), _agent_token()}`; failures to `_set_error` |
| `run_forever` :1259 | `run_forever()` | never returns while configured; returns at once if not configured | getUpdates long poll (timeout 50) on alerts bot; persists `offset` BEFORE dispatch (at-most-once); dispatches `callback_query` and `message` | runs as daemon thread "telegram" (connector.py:5915); heartbeat `forge_heartbeat.beat("telegram", 70, ...)` | loop: load offset, getUpdates, advance+save offset per update, `_handle_callback` / `_handle_message`; errors -> `_set_error`, sleep 3 |
| `run_agent_bot_forever` :1330 | `run_agent_bot_forever()` | same pattern; returns at once with no agent token | same, second bot, state key `agentOffset`; tracks `_AGENT_LOOP` dict (polls, lastError) | daemon thread "telegram_agent" (connector.py:5920) | passes `agent_chat=True` to callbacks (auth via `_msg_authorized`) and `reply_token=token` to messages |
| `_handle_message` :929 | `_handle_message(msg, reply_token=None)` | None | ignores unauthorized/empty; handles /start /help /menu /chats /bind /unbind /whoami /agents /ace, /status etc., wholesale ops router (`telegram_ops.route`), agent switch/triggers, `/task`; finally spawns `_partner_turn` thread | `/bind` mutates state under lock; `_AGENT_SESS` unlocked dict | replies via local `reply_to` -> `_send_to`. `/bind` is the only way a chat becomes a biz chat (writes `bizChats[biz]={id,title,boundAt}`) |
| `_partner_turn` :1166 | `_partner_turn(chat_id, agent_id, text, reply_token=None)` | None | sendChatAction(typing); calls `telegram_agent.chat(...)` (LLM, can take minutes); records to `agents_history`; sends reply + cards with `_send_to` | per-chat `threading.Lock` in `_CHAT_LOCKS` (:1163) | falls back to `_AGENT_CHAT`/`_AGENCY_CHAT` fns on error; reply = `<b>Agent</b>\n` + `_esc(reply)` |
| `_send_cards` :1228 | `_send_cards(chat_id, cards, token=None)` | None | one `_send_to` per card: `text, buttons = telegram_agent.card(c)` | | cards are the checkmark/cross approval messages (`pgo:`/`pno:` callbacks, telegram_agent.py:270) |
| `_on_partner_result` :1238 | `_on_partner_result(chat_id, agent_id, text)` | None | appends `[owner tapped ✅] ...` to in-memory session + `agents_history`. Hooked at import: `telegram_agent._ON_RESULT["fn"]` (:1253) | unlocked dict mutation | memory only, no network |
| `_send_to` :907 (extra, not in your list) | `_send_to(chat_id, text, buttons=None, token=None, reply_markup=None)` | `{"ok":True}` / `{"error":...}` | raw sendMessage to ANY chat id, text cut to 4000, NO dedupe, NO business routing | | Second outbound path: agent-chat replies, approval cards, ops confirms (telegram_ops gets it as its `send` lambda, :1062). NOT covered by a hook in `send/send_photo` |

## 2. State file `marcus_state/telegram.json` (schema from `_load` :157, keys only)
Path = `STATE` (:34) = `forge rei/marcus_state/telegram.json`. Written atomically (tmp + `os.replace`, :195). Top-level keys:
- `toggles` {hot_lead, proposal, missed_sweep, handoff, agency, edit_request, dyson_plan} (all bool; `skill_proposal` has no toggle, defaults True)
- `quietHours` {enabled, start, end}
- `offset` (int, alerts-bot getUpdates)
- `agentOffset` (int, agent-bot getUpdates)
- `dedupe` {dedupe_key: epoch_seconds_float}
- `lastError` (str|null, token-redacted)
- `lastSentAt` (int epoch|null)
- `bizChats` {business: {id, title, boundAt}}

WARNING: `_load()` rebuilds from a whitelist, so any NEW key someone adds to this file is DROPPED on the next `_save`. Slack must keep its own state file (e.g. `marcus_state/slack.json`) with its own lock. Also: single-process lock only, no cross-process safety.

## 3. Dedupe ring (:303-:330)
- Window `_DEDUPE_WINDOW` = 900 s (:40); cap `_DEDUPE_MAX` = 200 (:42).
- `_dedupe_seen(key)`: falsy key -> False. Under lock: load, drop entries older than window or non-numeric, SAVE the trimmed ring (a disk write on every call), return `key in ring`.
- `_dedupe_commit(key)`: only called after a successful Telegram delivery. Trim, set `ring[key]=now`, if > 200 keep the 200 newest, save.
- Consequences: failed send does not suppress retry; key is global (not per chat), so same key to two businesses blocks the second (connector uses `dedupe + ":" + biz` at connector.py:2207); check-then-commit race exists; `_send_to` has no dedupe.

## 4. Button representation (c)
`buttons` = `list[list[dict]]` (rows of buttons). Each dict = `{"text": str, "callback_data": str}`. `callback_data` = `"<action>:<arg>"`, <= 64 bytes (daycare_ads_tg.py:146 asserts it). Passed straight to Telegram as `reply_markup={"inline_keyboard": buttons}`. No url buttons, no tuples anywhere seen. Separate raw `reply_markup` dict only in `_send_to` (reply keyboard / remove_keyboard), Telegram-only, ignore for Slack.
Slack conversion: each row -> one `actions` block (<=25 elements); `text` -> `button.text`; `action_id` = the `callback_data` action prefix (or whole string), `value` = whole `callback_data`. Taps must be routed to the SAME `_ACTIONS` dict (`fn(arg)` after `partition(":")`; `pgo`/`pno` also need the chat id string).

## 5. How callers call send / send_biz / send_photo (d)
Method: AST scan of every non-test `forge rei/*.py` (27 call sites). No caller passes `parse_mode` (hard-coded HTML inside). No caller passes `photo=`.

| Fn | kwargs used (count of sites) |
|---|---|
| `send_biz(biz, text, ...)` (14 sites; business is always positional arg 1) | `dedupe_key` only: 6 · `buttons`+`dedupe_key`: 5 · none: 3 |
| `send(text, ...)` (11 sites) | `dedupe_key` only: 6 · `business`+`dedupe_key`: 4 · `business`+`buttons`+`dedupe_key`: 1 (connector.py:2506 `telegram_send` lambda for telegram_ops) |
| `send_photo(biz, url, caption, ...)` (1 site, daycare_ads_tg.py:140) | `buttons`+`dedupe_key` |
| `send_test()` (1 site) | none (connector.py:4205) |

Callers: ace.py (3, wholesale), autopilot.py:197, connector.py (many: watchdog 1963/1974/2071/2084, backlog 2032, daily brief `_send_split` 2207, CEO brief 2280, handoff 2356-2371, telegram_send lambda 2506, bus tap 1313), daycare_ads_autopilot.py:939, daycare_ads_tg.py (`_tg()` wrapper :123, `_send` :133, `_send_photo` :139), daycare_leads.py:450, daycare_replies.py:195/246, daycare_revive.py:252, daycare_starts.py:588, higgsfield_io.py:684, sync_monitor.py:186/197, telegram_ops.py:342/353 (through `_H["telegram_send"]`). `daycare_leads.py:450` and `daycare_starts.py:588` pre-escape text with `html.escape`. Positional/kwarg mix: `buttons` and `dedupe_key` always by keyword.
Not found by scan: callers using other aliases (e.g. `from telegram_io import send`). Plain grep for `telegram_io` found no such import in non-test code. Callers outside `forge rei/`: none (grep of repo, .py only). JS or other languages: Unknown (not searched).

## 6. Best single hook point (e)
Put ONE private function, e.g. `_mirror(kind, business, text, buttons, dedupe_key, message_id, image_url=None)`, and call it from exactly two places:
1. `send()` right after the success branch (after `_dedupe_commit` at :359, with `business` = the argument as given, `text`, `buttons`, `dedupe_key`, `result["messageId"]`).
2. `send_photo()` success branch only (after :399; pass `image_url`, `cap`/caption, buttons). Do NOT mirror in its failure path; that path calls `send()` which mirrors (avoids double post).
This covers every caller: `send_biz` -> `send`; `send_test` -> `send`; `on_bus_message` -> `send` (thread); `telegram_ops` -> lambda -> `send`; `send_photo` fallback -> `send`.
Rules for `_mirror`:
- Fire-and-forget: daemon thread or queue, own try/except, never raise, short timeout. `send()` callers sit on hot paths (watchdog tick, Marcus engine lock).
- Pass through: resolved business (None = HQ; map to a Slack channel by business, mirror `chat_for` logic), HTML text, buttons (list of rows), dedupe_key (reuse as Slack idempotency key), photo URL + caption. Keep the Telegram `messageId` if Slack wants a cross-reference to later edit/strike a message.
- Trade-off: after the dedupe gate and after `configured()` (:339), a Telegram failure or an unconfigured Telegram means no Slack mirror. If Slack must work independently, hook before the `configured()` guard and run its own dedupe in its own state file.
- NOT covered by this hook: `_send_to` (:907, agent chat replies, approval cards, ops confirms), and message edits done in `_handle_callback`. To mirror those, hook `_send_to` too (it already has the `chat_id`, so map via `_business_of_chat`) and decide if bot conversation belongs in Slack. Unknown (product decision).
- Inbound Slack taps (if wanted) need a new handler that reuses `_ACTIONS`, `_result_text`, the `action_log.record_result` call, and its own authorization; `_handle_callback`/`_authorized` assume Telegram ids.

## 7. Test-impact gotchas for the hook
- `test_telegram_biz_chats.py:28` patches `tg.threading.Thread` with `_SyncThread`. That is the GLOBAL `threading.Thread`, so a mirror thread started inside `send()` runs inline in those tests (so stub the Slack client or no-op when unconfigured).
- `test_telegram_ace.py:73`, `test_ace.py:145` replace `telegram_io.send` outright; `test_daycare_replies.py:152` replaces `send_biz`; `test_daycare_leads.py:373` replaces the whole module with a SimpleNamespace. A mirror inside `send()` is skipped by these; fine.
- `test_daycare_ads_tg.py:122` / `test_daycare_ads_build.py:132` patch `_api` and `STATE` and call real `send_photo`; the mirror must be a no-op when Slack env is unset.

## 8. Tests: stubbing, isolation, command
- `test_telegram_biz_chats.py` (136 lines): `mock.patch.object(tg, "STATE", tmpdir/telegram.json)` (TemporaryDirectory per test); `mock.patch.dict(os.environ, {TELEGRAM_BOT_TOKEN:"tok", TELEGRAM_CHAT_ID:"7001", TELEGRAM_ALLOWED_IDS:""})`; pops `TELEGRAM_CHAT_<BIZ>`; patches `tg._api` (records `(method, payload)`, returns `{"ok":True,"result":{"message_id":1}}`) and `tg._send_to` (records `(chat, text)`); patches `tg.threading.Thread` with `_SyncThread`; clears `tg._AGENT_SESS`. Some tests also patch `tg.send` with a lambda (`test_bus_events_route_by_business`) and `telegram_agent.chat`.
- `test_watchdog_alerts.py` (234 lines): does NOT exercise `telegram_io` code. It lifts functions out of `connector.py` source via `ast`, `exec`s them into a namespace with `telegram_io` replaced by `FakeTelegram` (records `{text,key,business}`, has `send/configured/_esc`). State isolation: tmp dir, with `forge_heartbeat.STATE`, `AI_STATE` and `_ai_configured_fps` swapped and restored in setUp/tearDown. A Slack hook inside `telegram_io.send` cannot affect this test; changing the watchdog's call signature (`telegram_io.send(txt, dedupe_key=..., business=...)`) would.
- No env var for state dir; isolation = patching module attributes + `tempfile`.
- Command (run by me, VERIFIED): `cd "/Volumes/AgentDrive/claude/forge-rei-dash/forge rei" && TMPDIR=/Volumes/AgentDrive/claude/_tmp PYTHONDONTWRITEBYTECODE=1 FORGE_MARCUS=0 python3 -m unittest test_telegram_biz_chats test_watchdog_alerts` -> `Ran 19 tests ... OK`. `git status -- marcus_state` clean before and after. (Both files also run standalone via `python3 <file>` from that dir.) `FORGE_MARCUS=0` is not read by these tests as far as I saw; kept per brief.

## 9. Logging / leak review (f)
Only one `print` in the module (:694): `[telegram] tap REFUSED from_id=... chat_id=... configured_chat=... allowlist=set|EMPTY`. IDs only, no token, no message text. No `logging` module use. No message bodies logged.
Risk points:
- `_api` URL embeds the token (:246). Anything that stores or prints a raw exception from it can leak. `_set_error` redacts via `_redact` (:207), but `_redact` only knows the two Telegram tokens. A Slack token (`xoxb-`, `xapp-`) is not covered; extend `_redact` or give Slack its own redactor.
- `_send_to` returns `{"error": str(e)}` UNREDACTED (:926); `_handle_callback` shows `str(e)` of action errors in the chat (:718, via `_result_text`); `_partner_turn` puts `e2` into the reply (:1198).
- `_AGENT_LOOP["lastError"] = str(e)[:120]` (:1363) is unredacted and is exposed by `settings()` -> `agentLoop` (:273) to the dashboard.
- `lastError` in `telegram.json` and `settings()` (:269) is redacted for Telegram tokens only; urllib HTTPError text is usually just "HTTP Error N: reason" (not verified for every error type).
- `connector.py` was only partly read; other modules log message bodies? Unknown (not audited).
- Related untracked dir `forge rei/../forge-slack/` exists (config/, smoke_test.py) and `docs/superpowers/specs/2026-11-11-slack-migration-design.md`; NOT read (out of brief). Unknown whether the design already fixes a hook point.
