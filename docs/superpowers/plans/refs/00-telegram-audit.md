# Telegram touchpoint audit (READ-ONLY)

Repo: /Volumes/AgentDrive/claude/forge-rei-dash. Base dir for code: `forge rei/` (paths below are relative to it unless noted).
Method: grep -rIn (case-insensitive) over the repo, excluding node_modules, .git, .swarm, docs/archive, .env*, *.db*. Targeted reads of telegram_io.py, telegram_ops.py, telegram_agent.py, daycare_ads_tg.py, connector.py wiring, and the two n8n memory notes. No env values, secrets, or master.env read. Nothing run that sends messages. No repo files edited.

Verified = read in code this session. Unknown = not traced.

## 1. Touchpoint table (core transport and senders)

| file:line | what it does | direction | business | env (names) | test |
|---|---|---|---|---|---|
| telegram_io.py:33-35 | TG_DIR, STATE = marcus_state/telegram.json, API_BASE | config | HQ | none | none |
| telegram_io.py:61-74 | folds forge-telegram/config/telegram.env into os.environ (real env wins) | config | all | none | none |
| telegram_io.py:78-117 | _token, _chat_id, _allowed_ids, _authorized (callback auth) | auth | all | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ALLOWED_IDS | none direct |
| telegram_io.py:130-148 | _biz_chats / chat_for: business to chat map | config/route | daycare, agency, wholesale, dropship | TELEGRAM_CHAT_<BIZ> (override) | test_telegram_biz_chats.py |
| telegram_io.py:240-258 | _api(): every outbound Telegram HTTP call | send | all | TELEGRAM_BOT_TOKEN, TELEGRAM_AGENT_BOT_TOKEN | indirect |
| telegram_io.py:333-370 | send(): sendMessage, HTML, dedupe 15 min, no truncation | send | by business | none | test_watchdog_alerts.py (stub) |
| telegram_io.py:372-375 | send_biz(): send to business chat | send | by business | none | indirect |
| telegram_io.py:380-414 | send_photo(): sendPhoto, caption cut to 1024 | send | daycare (ads cards) | none | test_daycare_ads_tg.py |
| telegram_io.py:415-417 | send_test() | send | HQ | none | none |
| telegram_io.py:421-428 | set_actions(): callback name to function registry | registry | all | none | none |
| telegram_io.py:430-520 | _event_class, _buttons_for: alert class to inline keyboard | send | wholesale, agency, HQ | none | none |
| telegram_io.py:563-633 | _compose_text, on_bus_message (sends on daemon thread) | send | wholesale, agency | none | none |
| telegram_io.py:635-672 | _result_text, _TAP_AGENT (audit labels) | audit | all | none | none |
| telegram_io.py:673-764 | _handle_callback(): tap auth, dispatch, answerCallbackQuery, edit message | button-tap | all | none | none |
| telegram_io.py:766-905 | agent-chat registry, aliases, help card, keyboard, _BOT_COMMANDS, register_commands (setMyCommands), _msg_authorized | command | all | none | test_telegram_agent.py |
| telegram_io.py:907-928 | _send_to(): agent-chat send, text[:4000] | send | agent chat | none | none |
| telegram_io.py:929-1162 | _handle_message(): all inbound commands and free-text routing | command/receive | all | TELEGRAM_ALLOWED_IDS | test_telegram_agent.py |
| telegram_io.py:1166-1258 | _partner_turn, _send_cards, _on_partner_result (threaded agent turn) | receive/send | business chats | none | test_telegram_agent.py |
| telegram_io.py:1259-1321 | run_forever(): getUpdates long-poll, alerts bot, offset saved before dispatch | receive | all | TELEGRAM_BOT_TOKEN | none |
| telegram_io.py:1323-1398 | run_agent_bot_forever(): long-poll on second bot, own offset | receive | agent DMs | TELEGRAM_AGENT_BOT_TOKEN | none |
| telegram_ops.py:32, 58-118 | STATE = marcus_state/telegram_ops.json; _queue_pending, confirm (opsgo), cancel (opsno) | button-tap | wholesale, daycare | none | none |
| telegram_ops.py:335-398 | _receipt (telegram_send), _send_or_telegram, _queue_move (Move card at 376), _run_tag | send | wholesale | none | none |
| telegram_ops.py:433-440 | handle_agent_command(): shared with dashboard chat | command | all | none | none |
| telegram_ops.py:541-581 | _text_seller, _checkback: SMS draft cards (Send button 561, 575) | send/button-tap | wholesale | none | none |
| telegram_ops.py:582-595 | _proposals: Approve and Dismiss buttons (590) | button-tap | wholesale | none | none |
| telegram_ops.py:704-725 | _clock: clock agents out/in buttons (719-723) | button-tap | HQ | none | none |
| telegram_ops.py:742-745, 793-905 | _CMD_RE command list; route() | command | all | none | none |
| telegram_agent.py:37-38 | STATE = marcus_state/telegram_agent_pending.json; charter = forge-telegram/skills/business-partner.md | state | daycare, agency, wholesale, dropship, HQ | none | test_telegram_agent.py |
| telegram_agent.py:56-98 | SCOPE (per-business API allowlist), DENY, _RISKY | policy | all | none | test_telegram_agent.py |
| telegram_agent.py:208-266 | _queue, confirm (pgo), cancel (pno); tap bound to chat id | button-tap | all | none | test_telegram_agent.py |
| telegram_agent.py:270-277 | card(): Do it (pgo:) and Cancel (pno:) buttons | send | all | none | test_telegram_agent.py |
| telegram_agent.py:346-391 | _run_tool(): model tool calls, POST queued behind tap | command | all | none | test_telegram_agent.py |
| telegram_agent.py:524-566 | chat(): Claude tool-use loop | receive | all | Anthropic key via review_agent (name not traced) | test_telegram_agent.py |
| telegram_agent.py:608-660 | quick(): /status /starts /logins /pin (no model call); reset-pin queued at 656 | command | daycare | none | test_telegram_agent.py |
| daycare_ads_tg.py:121-124 | transport shim: returns telegram_io | send | daycare | none | test_daycare_ads_tg.py (41 defs) |
| daycare_ads_tg.py:146 | callback_data asserted <= 64 bytes | encode | daycare | none | test_daycare_ads_tg.py |
| daycare_ads_tg.py:618-622 | handlers(): adsapply, adsskip, adsundo, adsbuild, adsalt, adsdrop, adslaunch, adsagain, adskeep | button-tap | daycare | FORGE_DAYCARE_ADS_CARDS | test_daycare_ads_tg.py |
| ace.py:798-799, 910-911, 1017-1024 | send_biz("wholesale") alerts | send | wholesale | none | test_telegram_ace.py |
| ace.py:949-1000 | telegram_action_handlers(): aceack, acestop, aceundo | button-tap | wholesale | none | test_telegram_ace.py |
| autopilot.py:36, 197 | send_biz("wholesale") autopilot receipt | send | wholesale | none | test_audit_regressions.py (indirect) |
| daycare_leads.py:440-451 | owner alert (bus plus Telegram, dedupe) | send | daycare | none | test_daycare_leads.py |
| daycare_replies.py:174-196, 244-246 | Solomon needs-human ping; texted-family receipt | send | daycare | none | test_daycare_replies.py |
| daycare_starts.py:579-588 | start-date confirm ping | send | daycare | none | test_daycare_starts.py |
| daycare_revive.py:247-252 | revive batch ping | send | daycare | none | none |
| daycare_ads_autopilot.py:938-939, 1018 | ads proposal and concept cards | send | daycare | FORGE_DAYCARE_ADS_CARDS | test_daycare_ads_tg.py |
| agency_dyson.py:456 | plan announced on bus; Telegram shows Approve and ship / Reject | send | agency | none | none |
| skill_forge.py:17 | skill proposal buttons (Adopt / Dismiss) | send | HQ | none | none |
| marcus_lead.py:101 | directives posted to bus (Comms + Telegram) | send | wholesale | none | none |
| higgsfield_io.py:675-686 | Higgsfield login lapsed alert | send | HQ | none | none |
| sync_monitor.py:177-197 | sync stale or ok ping, once per flip | send | HQ | none | none |
| daily_brief.py:4-5, 106; daily_recap.py:4 | morning brief and evening recap (HTML-escaped) | send | HQ plus per-business split | none | none |
| connector.py:1170, 1313 | import telegram_io; agent_bus.register_notifier(telegram_io.on_bus_message) | wiring | all | none | none |
| connector.py:1926-1934 | _WATCHDOG_BIZ: loop alerts routed to business chat | route | daycare, wholesale, dropship | none | test_watchdog_alerts.py |
| connector.py:1941-1975 | AI dependency (Anthropic credits/auth) alert, HQ | send | HQ | none | test_watchdog_alerts.py |
| connector.py:1995-2032 | daily backlog ping per business | send | per business | none | none |
| connector.py:2042-2090 | loop down and recovered watchdog | send | mapped or HQ | none | test_watchdog_alerts.py |
| connector.py:2204-2216 | _send_split(): brief and recap fan-out | send | HQ plus bound chats | none | none |
| connector.py:2267-2280 | CEO brief push (opt-in) | send | HQ | FORGE_MISSION_BRIEF_TELEGRAM | none |
| connector.py:2321-2371 | _tg_handoff (Hand to Marcus) | button-tap | wholesale | none | none |
| connector.py:2376-2420 | telegram_io.set_actions({...}) full tap map (section C) | registry | all | none | none |
| connector.py:2484-2510 | telegram_ops.register({...}) incl. telegram_send (hardcoded business="wholesale") | registry | all | none | none |
| connector.py:2515-2560 | agent chat and agency chat bindings | command | all | none | none |
| connector.py:3785 | dashboard chat routed to telegram_ops.handle_agent_command | command | all | none | none |
| agents_chat.py:161-162 | dashboard chat calls telegram_ops | command | all | none | none |
| action_log.py:13, 50 | redacts Telegram bot token shape | security | all | none | none |
| agent_bus.py:31, 57 | notifier comments (handoff event) | comment | all | none | none |

Note: telegram_ops.py:344 and connector.py:2506 mean every telegram_ops receipt goes to the wholesale chat, even daycare-command receipts. Verified in code. Unknown whether that is intended.

## A. Outbound alert types and destination chat

| alert | destination | source |
|---|---|---|
| Hot lead (Marcus READY/PRICE) | wholesale | telegram_io.py:444, 485-497 |
| Proposal (warm or better) | wholesale | telegram_io.py:457-465 |
| Missed sweep, handoff | wholesale | telegram_io.py:444 |
| Agency edit request, Dyson plan | agency | telegram_io.py:445, 508-516 |
| Skill proposal | HQ | telegram_io.py:444 comment, 501 |
| Command receipts | wholesale (hardcoded) | connector.py:2506 |
| Daycare lead, reply, start, revive, ads cards | daycare | see table |
| Autopilot, ACE | wholesale | ace.py, autopilot.py |
| Loop down / recovered | mapped business, else HQ | connector.py:1926-1934, 2042-2090 |
| Anthropic credits/auth | HQ (all businesses) | connector.py:1941-1975 |
| Clock, telegram, graphify, sync watchdogs | HQ | connector.py:1934 comment; sync_monitor.py:186 |
| Brief and recap | per bound chat, HQ gets system lines | connector.py:2204-2216 |
| Higgsfield login lapsed | HQ | higgsfield_io.py:683 |
Graphify watchdog Telegram path: Unknown (only a comment at connector.py:1934 found).

## B. Inbound

- Auth, alerts bot (telegram_io.py:92-117): chat must be HQ or a bound business chat AND from_id in TELEGRAM_ALLOWED_IDS. Personal DM fallback (only if allowlist empty): chat == from == TELEGRAM_CHAT_ID.
- Auth, agent chat (telegram_io.py:896-904): from_id must be TELEGRAM_CHAT_ID or in allowlist. Any chat allowed.
- Commands in telegram_io.py:948-1160: /start /help, /menu [on|off], /chats, /bind <biz>, /unbind <biz> (bind requires the alerts bot token, line 971-983), /whoami /id, /agents /who, /ace, /status /starts /logins /pin, /task, aliases /scout /marcus /atlas /dyson /eco /solomon /midas /orion, and taps via _KEYBOARD_MAP.
- Ops commands (telegram_ops.py:742-745): /today /done /hot /sweep /screen /find /text /send /checkback /proposals /report /directives /orders /ops /autopilot /prep /pause /resume /clockin /clockout /clock.
- Free text: business chats go to telegram_agent (tool loop). Telegram groups need admin for plain text (privacy mode; tip at telegram_io.py:1151). Otherwise /command or reply to bot.
- Recognized slash commands are checked before free text. Ops intents then go to the agent loop.

## C. Tap flow (highest risk)

Encoding: callback_data = `<action>:<arg>`, arg is a server-side id or token. Split at first ":" (telegram_io.py:700-711). Max 64 bytes (daycare_ads_tg.py:146).

Storage of state: telegram_ops.json (pending TTL), telegram_agent_pending.json (bound to chat), ads card state file, Marcus proposal store (pop on approve), ACE state, agency drafts, agency requests, skill_forge proposals.

Action map (connector.py:2376-2420):
1. approve:pid. Marcus.approve sends a real SMS to a seller. OUTWARD.
2. mdismiss:pid. Dismiss, no send.
3. handoff:conv. Marcus screens and drafts a reply, then posts a new Approve card. No send.
4. scoutdismiss:conv. Dismiss.
5. skillgo / skillno. Adopt skill into vault or dismiss.
6. opsgo:tok. Runs queued action: move_stage (GHL pipeline move plus tag), send_sms (GHL SMS, handle_send_post), or send_nurture (check-back SMS). OUTWARD.
7. opsno:tok. Cancel.
8. opspause / opsresume. Clock agents out or in (forge_ops.set_paused). Affects loops.
9. aceack / acestop / aceundo. ACE thread hold and undo, mark handed off.
10. dysonplan:rid. Dyson drafts a plan. No ship.
11. reqdismiss:rid. Sets request status rejected.
12. dysongo:did. agency_dyson.decision approve, runs apply(), live client-site deploy. OUTWARD, high risk.
13. dysonno:did. Reject.
14. pgo:tok. Runs queued allowed POST route on box (telegram_agent.py:222-258). Examples in scope: daycare reset-pin (queued at line 656, new login PIN). Chat-bound. OUTWARD or state-changing.
15. pno:tok. Cancel.
16. adsapply / adsskip / adsundo. Applies or undoes Meta ad optimization. Meta write. Creates Meta changes.
17. adsbuild / adsalt / adsdrop / adsagain / adskeep. Builds ad PAUSED on Meta (Pipeboard) or drops or regenerates concept. Creates Meta objects.
18. adslaunch:<usd>. Turns ON a Meta ad at allowed budget (launch_budgets). REAL SPEND.
Gap: pgo and pno are bound to chat id (telegram_io.py:713-714). Other taps are not. A tap in any authorized chat can confirm a token issued elsewhere. Token secrecy is the only barrier. Unknown whether ads card tokens have TTL.

## D. n8n

- Repo code: no n8n call site found that touches Telegram in forge rei/*.py.
- Memory (2026-11-01/02, read): owner decided no new bot. @Forgeagentsbot DM runs through n8n. @Forgelabsxbot groups, tap cards and alerts stay on the box (webhook and polling cannot share one bot). Each Telegram message through n8n costs one execution. Budget 2,500/mo.
- Conflict: docs/FORGE_CURRENT_ARCHITECTURE.md:108 says no n8n on the box and no inbound webhooks. Memory says gateway live (commit 97c5951). Repo has TELEGRAM_AGENT_BOT_TOKEN long-poll (telegram_io.py:1323) for DMs, which contradicts "DM on n8n". Which path is live: Unknown. The n8n workflow itself is not in the repo: Unknown.

## E. Chat ids and bindings (names only)

- Env: TELEGRAM_CHAT_ID (HQ), TELEGRAM_CHAT_<BIZ> (override), TELEGRAM_ALLOWED_IDS, TELEGRAM_BOT_TOKEN, TELEGRAM_AGENT_BOT_TOKEN. Values not read.
- Files: forge-telegram/config/telegram.env (gitignored, not read), forge-telegram/config/telegram.env.example (template).
- State: marcus_state/telegram.json: keys bizChats (per business: id, title, boundAt), offset, lastSentAt, lastError, dedupe ring, per-event toggles, quiet hours.
- Other state: marcus_state/telegram_ops.json, marcus_state/telegram_agent_pending.json. Agent chat sessions are in memory only (_AGENT_SESS).
- Not a DB.

## F. Tests

Files and counts (def test count, grep):
- test_telegram_agent.py: 12
- test_telegram_biz_chats.py: 8
- test_telegram_ace.py: 4
- test_daycare_ads_tg.py: 41
- test_watchdog_alerts.py: 11 (stubs telegram_io)
Gap: no test_telegram_io.py or test_telegram_ops.py. Also not covered: run_forever, _handle_callback auth, opsgo path.
Run command (NOT run): `cd "/Volumes/AgentDrive/claude/forge-rei-dash/forge rei" && FORGE_MARCUS=0 python3 -m unittest test_telegram_agent test_telegram_ace test_telegram_biz_chats test_daycare_ads_tg test_watchdog_alerts -v`. Pattern from E2E_TEST_CHECKLIST.md:13-14.

## G. Telegram-specific, no obvious Slack equivalent

1. HTML parse_mode with escaping (telegram_io.py:226). Slack needs mrkdwn or Block Kit and escapes &, <, >.
2. Inline keyboards and callback_data (64 bytes, daycare_ads_tg.py:146). Slack: Block Kit buttons with action_id and value (about 2000 chars).
3. answerCallbackQuery toast (telegram_io.py:733). Slack: ack within 3 s, then response_url or ephemeral message. Knowledge, not verified against current Slack docs.
4. editMessageText and editMessageCaption footer (telegram_io.py:739-762). Slack: chat.update using stored ts.
5. getUpdates long-poll, no inbound port (telegram_io.py:1259). Slack: Socket Mode (outbound socket, fits no-inbound box) or Events API (needs public URL, which docs say is blocked). Socket Mode is the nearest fit.
6. Offset-based at-most-once replay (telegram_io.py:1290-1310). Slack has no offset. Dedupe needed on event id or ts.
7. Length: send() uncapped (telegram_io.py:333-370), _send_to 4000 (line 913), Telegram 4096. Slack section text 3000, message text about 40k. Confirm limits before build.
8. Photo caption 1024 (telegram_io.py:377). Slack: image block or file upload.
9. Native "/" menu via setMyCommands (telegram_io.py:868-878). Slack: slash commands declared in app manifest, no runtime menu.
10. Persistent reply keyboard, is_persistent (telegram_io.py:832-837, 951). No Slack equivalent. Use App Home or shortcuts.
11. Group privacy mode and admin requirement (telegram_io.py:1151). Slack: bot sees channel messages only when invited, scopes channels:history, groups:history, im:history.
12. /bind with @botname suffix (telegram_io.py:961). Slack: channel ID, bot must be invited.
13. Telegram chat_id as DM user id (telegram_io.py:116). Slack: conversations.open to get DM channel id.
14. Second bot (TELEGRAM_AGENT_BOT_TOKEN). Slack: second app or same app with DM.
15. disable_web_page_preview (telegram_io.py:343-350). Slack: unfurl_links false.
16. Reply-to-message routing. Slack: thread_ts.
17. Numeric allowlist (TELEGRAM_ALLOWED_IDS). Slack: user IDs (U...).

Other items for the owner:
- forge-slack/ already exists in the repo (untracked). Listed files: smoke_test.py, config/slack.env.example, config/slack.env. slack.env was NOT read. Its state: Unknown.
- docs/FORGE_CURRENT_ARCHITECTURE.md:127 notes a phantom connector import that double-registers Telegram callbacks.

Unknown list: graphify watchdog path; n8n live state; ACE callback exact payloads beyond 3 keys; ads token TTL; whether /autopilot changes autopilot directly; full _authorized edge cases beyond lines 92-117.
