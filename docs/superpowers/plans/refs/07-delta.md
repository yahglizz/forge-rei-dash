# 07 - Delta: refs 01/02/03 (written vs 39f067d) corrected to 8817e80

Method: `git diff 39f067d 8817e80` per file + grep of current code in this worktree. Read-only, nothing run, no tests executed.
Paths are under `forge rei/`. Anything not listed here is UNCHANGED (verified by empty diff for `daycare_ads_tg.py`, `agency_dyson.py`, `ace.py`, `skill_forge.py`; set_actions and telegram_ops.register blocks diffed byte-identical).
102 commits between the two SHAs.

## 1. telegram_io.py (now 1436 lines, was 1398)

Signatures UNCHANGED: `send` :334, `send_biz` :373, `send_photo` :381, `send_test` :416, `set_actions` :422, `_buttons_for` :488 (button table identical), `_api` :241, `_send_to` :939 `(chat_id, text, buttons=None, token=None, reply_markup=None)`, `_dedupe_seen` :304, `_dedupe_commit` :318, `_redact` :208 (still Telegram tokens only), `_set_error` :218, `_esc` :227, `_ACTIONS` :58, `_LOCK` :38, `STATE` :35, `CAPTION_MAX` :378, `_TAP_AGENT` :668, `_AGENT_SESS` :793, `_AGENT_ALIASES` :794, `_AGENT_TRIGGER` :803, `_AGENT_ROSTER` :823, `_msg_authorized` :928, `_agent_business` :1251, `_default_agent` :1261, `_send_cards` :1266, `_on_partner_result` :1276 (hook install :1291), `run_forever` :1297, `agent_bot_configured` :1361, `run_agent_bot_forever` :1368, `register_agent_chat` :913, `register_agency_chat` :919, `register_commands` :900, `_BIZ_AGENT` :128. Add 1 to most old numbers before :431, add 10-40 after (table above is exact).

CHANGED:
- `_event_class` :431: new early return `None` for `data.type == "collab"` (agent-to-agent consult traffic). Event class list in 01 sec1 is otherwise right.
- `_handle_callback` :684 (was :673). New step before dispatch (:719-726): `pgo` taps whose card is a Mac card (`telegram_agent.is_mac_card(tok)`, helper `_foreign_mac_tap` :676) are refused unless `agent_gateway.is_owner(from_id)` (owner ids = env `FORGE_GATEWAY_OWNER_IDS`, Telegram ids). A Slack tap handler MUST do its own Mac-card owner check; never let a Slack tap run a Mac card unless the Slack user maps to an owner. Dispatch line still `fn(arg, chat_id) if action in ("pgo","pno") else fn(arg)`.
- `_partner_turn` :1197 is now `(chat_id, agent_id, text, reply_token=None, from_id="")`. Thread spawn at :1189 passes `from_id`. For an owner (`agent_gateway.is_owner(from_id)`), it first calls `agent_gateway.chat_local(agent_id, text, "telegram", history=...)` (:1222) when env `FORGE_CHAT_GATEWAY=1`; on a result the job already recorded history and sent its cards (`recorded=True`), else falls to `telegram_agent.chat(...)` as before. Reply now strips `**` (:1247).
- `_handle_message` :961 (was :929). Zero-Claude command set is now `/status /starts /logins /pin /board` (:1075). `telegram_ops.route` call now :1093. `_named_agent(text)` :811 added: HQ-only fuzzy agent switch ("Solomon how many tours", typo-tolerant via difflib), applied at ~:1116 when `not chat_biz`. REMOVED: the old refusal "HQ refuses an agent whose business has its own chat" (old :1096-1105 block). 03 sec3 step 10 third rule no longer exists; Orion-only-in-HQ and foreign-business refusal in a business chat remain.
- `/board` added to `_AGENT_HELP` and `_BOT_COMMANDS` (:890 region).
- NEW import `difflib` (:24). No new send function, no new kwarg on `send`/`send_photo`/`send_biz`. No Slack/mirror hook exists yet (grep `_mirror|slack` in telegram_io.py = empty).

SHIFTED FACT that breaks the 01 hook plan (sec 6): cards from the agent gateway bypass `send()`. `agent_gateway._send_card` (agent_gateway.py:698-717) calls `telegram_io._send_to(_chat_id(business), text, buttons=...)` directly; `telegram_agent._deliver_mac` (telegram_agent.py:402-412) also calls `_send_to`. So a mirror only in `send()`/`send_photo()` misses every gateway/Mac card. The `_send_to` hook (01 sec 6, "NOT covered") is now required, not optional, if Slack should show approval cards. Gateway cards are bound to the Telegram chat id `telegram_io.chat_for(business)` (agent_gateway.py:505-507, :483), so a Slack `pgo` tap with a Slack chat id returns "that card belongs to another chat".

## 2. connector.py (now 6370 lines; all refs below are new)

Old -> new line map: bus tap `register_notifier(telegram_io.on_bus_message)` 1313 -> **1346**; `set_actions({` 2384 -> **2471** (block ends :2500); `telegram_ops.register({` 2484 -> **2571**; `telegram_send` lambda 2506 -> **2593**; `_tg_agent_chat` registration 2536 -> **2623**; `_tg_agency_chat` registration 2560 -> **2647**; `_tg_handoff` 2321 -> **2354**; `_send_split` 2207 -> **2233** (dedupe suffix `:{biz}` at :2240); `send_test` route 4205 -> **4474**; `handle_agent_command` caller 3785 -> **4011**; `main()` 5723 -> **6123**; `telegram_agent.register(...)` 5726 -> **6126**; register_commands 5889 -> **6324**; `run_forever` thread 5892 -> **6327**; agent-bot thread (new) **6330-6333**; `LOOPS_ENABLED` :52 (was :51).

Tap table at :2471-2500, keys CURRENT and COMPLETE (identical set to 39f067d, no new keys):
`approve, mdismiss, handoff, scoutdismiss, skillgo, skillno, acestop, aceundo, aceack, opsgo, opsno, opspause, opsresume, dysonplan, reqdismiss, dysongo, dysonno, pgo, pno, adsapply, adsskip, adsundo, adsbuild, adsalt, adsdrop, adslaunch, adsagain, adskeep`.
(ACE three from `ace.telegram_action_handlers(CONVO)` ace.py:949; ads nine from `daycare_ads_tg.handlers()` daycare_ads_tg.py:618.) This closes the "Full key list Unknown" gap in 01 sec1 `_ACTIONS` row. The telegram_ops.register dict (:2571-2603) is byte-identical.

New in connector since old: `import agent_gateway` :2412; `agent_gateway.start_server()` :6361 (n8n door, only if `FORGE_GATEWAY_PORT`); `agent_gateway.tool_http` route :3768; `solomon_orchestrator` thread :6278-6281.

main() start-up for a Slack listener: everything long-running sits inside `if LOOPS_ENABLED:` (FORGE_MARCUS=1) which ends at the `else:` print at :6359 ("loops DISABLED"). Telegram block is :6320-6334 (print, `register_commands()` in try/except, `telegram` daemon thread, optional `telegram_agent` thread; `forge_heartbeat.retire("telegram_agent")` in else). Insert Slack after :6333, before the Watchdog comment (~:6335), same shape:
```
if os.environ.get("FORGE_SLACK", "0") != "0":
    try: import slack_io; threading.Thread(target=slack_io.run_forever, daemon=True, name="slack").start()
    except Exception as e: print(...)
else: forge_heartbeat.retire("slack")
```
Flag convention verified: opt-in loops use `os.environ.get("FORGE_X", "0") != "0"` (FORGE_MARCUS_SMS :6149, FORGE_DROPSHIP_BRIEF :6294, FORGE_TODAY_LOOP :6306, FORGE_BRIEFS :2324); default-on daycare loops use `"1"` (:6179-6265); module-level `enabled()` style also exists: `solomon_orchestrator.enabled()` = `FORGE_SOLOMON_ORCH == "1"`. Gateway flags: `FORGE_CHAT_GATEWAY=1` (agent_gateway.chat_on), `FORGE_GATEWAY_PORT`, `FORGE_GATEWAY_OWNER_IDS`. Start `telegram_agent.register` (:6126) happens at top of main() before any thread, so Slack thread can safely call `telegram_agent.chat/quick` and `telegram_ops.route`.

## 3. telegram_agent.py (now 873 lines; +279/-66)

Signatures: `chat(agent_id, text, history, chat_id, key=None, call=None)` :721 UNCHANGED. `quick(cmd, arg, chat_id, business)` :815 UNCHANGED signature; `/board` added (returns `daycare_board.telegram_text(...)`, daycare-only, zero Claude). `card(c)` :448 `(text, buttons)`, same button shape, plus a Mac-card variant (`c["mac"]`, buttons "Run it"/"Cancel", still `pgo:`/`pno:`). Moved: `confirm` :222 -> **:320**, `cancel` :259 -> **:437**, `_queue` :208 -> **:269**, `allowed` :134 -> **:149**, `_http` :154 -> **:215**, `SCOPE` :57 -> **:60**, `DENY` :72 -> **:77**, `_ON_RESULT` :219 -> **:292**, `route_help` :312 -> **:499**, `system_prompt` :440 -> **:629**, `_messages` :504 -> **:701**, `register` :99 -> **:114**, `AGENT_BUSINESS` :44 -> :45, `PENDING_TTL=1800` :39, `MAX_CARDS=5` :103, `MAX_BODY=900` :104.

CHANGED:
- `confirm(tok, chat_id=None, hook=True)`: new `hook` kwarg (True = telegram_io history hook, callable = dashboard hook, False = none). Chat binding unchanged: `str(chat_id) != p["chat"]` -> "that card belongs to another chat" (:326-327), check runs only when `chat_id is not None`. Dashboard cards use chat `"dash"`. `cancel(tok, chat_id=None)` same.
- `_queue(chat_id, agent_id, business, path, body, summary, calls=None, ttl=None, no_history=False, mac=None)`: card record may now carry `calls` (batch card, `_confirm_calls` :352), `ttl` (per-card, overrides 1800), `noHistory`, `mac`. TTL is per card, not a flat 1800.
- Mac cards (`is_mac_card` :375, `_confirm_mac` :415): run a shell on the owner's Mac via `mac_link`; output DM'd to owner ids via `telegram_io._send_to`. Slack must not allow these without an owner check.
- `SCOPE` (:60-76): `_SHARED` now also includes `/api/coach/` (:59); hq adds `/api/stripe/status`, `/api/stripe/offers`. `DENY` adds `/api/daycare/ads-auto/mode`, `/api/gateway/`, `/api/mac/`, `/api/chat/`, `/api/daycare/media/`, `/api/agency/portal/`, `/api/agency/billing/`, `/api/dropship/mcp/`, `/api/sync/check`. 01/03 SCOPE list for agency (`/api/agency/`, `/api/coach/`) is now: agency = `/api/agency/` + shared (coach moved to shared).
- `TOOLS` list :472 still api_get, api_post, find_people, route_help, file_task in the first 5 entries (names grep only; later entries not listed, `mac_run`/`mac_status` are named in the DENY comment at :98-100, so more may exist: Verify).

## 4. Idempotency (refs/02): all three bugs STILL PRESENT

Files `agency_dyson.py`, `daycare_ads_tg.py` have an empty diff. `marcus_engine.py` diff = 2 comment edits only (line numbers unchanged).
- **U1** present, same lines: `marcus_engine.py` `_send` :1182, SMS post :1210, `p["status"]="sent"` :1220, `_persist_proposal(p)` :1222 (def :666, plain append), `proposals.pop` :1230, except :1231; `approve` :1242, `dismiss` :1258.
- **U2** present: `agency_dyson.py` `decision()` :577-599, assignment `dr["status"] = state_map[action]` at :593 with no status guard inside `with _LOCK` (:588). `generate_draft` :389 (U5) unchanged, still no per-requestId guard.
- **U3** present: `daycare_ads_tg.py` `_save` :62-68 swallows all exceptions (:66-67), `_claim` :97-109 unchanged. `h_apply` :456, `h_skip` :479, `h_undo` :489, `h_build` :503, `h_alt` :533, `h_drop` :543, `h_launch` :583, `h_again` :597, `h_keep` :611 (all same).
- U4: `_tg_handoff` moved to connector.py **:2354**, body not re-read for a guard; assume still unguarded (Verify).
- Line shifts in 02: `telegram_agent.confirm` now :320 (pop+save :326-334 region), `cancel` :437; `_handle_callback` now :684, offset-before-dispatch lives in `run_forever` :1297. `telegram_ops.confirm` :74 / `cancel` :119 unchanged.

## 5. telegram_ops.py (+3/-1, one hunk at `_intent`)

`route(text, chat_id, send)` **:794** (was :793; +1 only because `_intent` :774 grew one line, it now calls Claude with `model=review_agent.SMART_MODEL`). `handle_agent_command(agent_id, text, source="dashboard")` :433 UNCHANGED, still sends its confirm card via `_send_or_telegram` :349 -> `_H["telegram_send"]` -> Telegram (connector.py:2593). `confirm` :74, `cancel` :119, `register` :40, `_SESS` :37, `_CMD_RE` :742, `_rule_intent` :171, `_command_intent` :789. Caller in telegram_io now :1093 (was :1058); dashboard caller connector.py:4011.

## 6. NEW modules / taps in the 102 commits relevant to Telegram or taps

New tap action names: NONE. New modules touching Telegram/cards: `agent_gateway.py` (n8n door + in-process `chat_local`; sends pgo cards, see sec 1), `agent_runner.py`, `mac_link.py` + `deploy/mac/mac_worker.py` (Mac command cards), `solomon_orchestrator.py` (Command Board digest to daycare chat via `telegram_io.send_biz`), `daycare_board.py` (`/board` text), `action_digest.py`, `daycare_pipeline.py`, `daycare_calendar.py`, `daycare_watches.py`, `daycare_billing_reminders.py`, `gmail_io.py`, `google_cal_io.py`, `chat_actions.jsx` (dashboard tap cards, chat `"dash"`). Modified: `daycare_ads_autopilot.py`, `daycare_ads_studio.py`, `agency_ads.py`. Not re-audited beyond file names: Unknown whether any of these add a `telegram_io.send*` call site beyond the 27 counted in 01 sec5 (re-run the AST scan before relying on that count).

## Not verified
Nothing executed. Box Python / slack_sdk status (03 sec7) not re-checked. `agent_gateway.chat_local(..., origin)` accepts only origins present in `CHAT_SURFACES` (agent_gateway.py:464, KeyError at :495 otherwise, swallowed by `except Exception` and falls back); a `"slack"` origin would need a new entry. Deploy refs (03 sec6) not re-diffed (`git diff --stat` grep for deploy-pull/autopull/setup_droplet/push.sh/quick-deploy returned nothing, so those files are unchanged).
