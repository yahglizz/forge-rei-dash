# Feed 3 - INBOUND interface sheet (Slack `/forge <cmd>`, channel text, DMs)

All paths relative to `/Volumes/AgentDrive/claude/forge-rei-dash/forge rei/` unless noted. Read-only pass; nothing run, no tests executed.
Everything the agents emit is **Telegram HTML** (`<b>`, `<code>`, `<i>`, `&amp;` escapes). Slack needs an HTML -> mrkdwn converter on the way out.

## 1. telegram_ops (wholesale remote control)

### `route(text, chat_id, send) -> bool`  (telegram_ops.py:793)
- `text`: raw string (`"/today"`, `"/text arthur: hi"`, or plain English).
- `chat_id`: any hashable/str. Used ONLY as a key into module dict `_SESS` (telegram_ops.py:36) for "reply 1/2" disambiguation (`pick`, 300 s) and `/done` numbering (`todayMap`). Slack: pass a stable string like `"slack:C0123"` or `"slack:D0123"`.
- `send(text, buttons=None)`: callback the router uses to reply. `buttons` = list of rows, each `{"text":..., "callback_data":...}`. Called 0..n times. Router returns nothing useful; output only via `send`.
- Return: `True` = consumed (ran an ops command). `False` = not ours, fall through to agent chat.
- Flow: strips `/marcus|/scout|/atlas ` prefix (:797) -> digit pick reply (:803) -> `_CMD_RE` slash table (:742, :828) -> any other `/x` returns False (:866) -> plain English via `_command_intent` = `_rule_intent` regex (:171, move/tag) else Claude `_intent` (:774, needs `_H["claude_key"]`) -> `chat` action returns False.
- Slash table `_CMD_RE`: today done hot sweep screen find text send checkback proposals report directives orders ops autopilot prep pause resume clockin clockout clock.
- Slack call: `telegram_ops.route("today", cid, lambda t,b=None: post(chan, md(t), b))`. For `/forge today` prepend the slash: `route("/today", ...)`.
- Needs chat context (chat_id state): `/today` (stores todayMap), `/done N` (reads it), `/text`, `/checkback` and any move/tag that finds >1 contact (stores `pick`; next bare digit message resolves). Others ignore chat_id.
- Confirm gates: outward sends queue in `marcus_state/telegram_ops.json` (TTL 3600) and come back as buttons `opsgo:<tok>` / `opsno:<tok>` -> `telegram_ops.confirm(token) -> dict` (:74) / `cancel(token) -> dict` (:119). Result dict: `{"ok":True,"message":...}` or `{"error":...}`. Tokens are NOT bound to a chat (any caller with the token can confirm), so Slack auth must happen before dispatch.
- Requires `telegram_ops.register({...})` already called (connector.py:2484). Anything using `_H` (`ghl_get`, `scout`, ...) raises KeyError otherwise.
- Wholesale-only by caller policy, not by the function: telegram_io only calls it in the wholesale chat (telegram_io.py:1058). Slack must reproduce that gate.

### `handle_agent_command(agent_id, text, source="dashboard") -> dict | None`  (telegram_ops.py:433)
- Only handles move_stage and tag intents. Returns `{"reply": str, "agent": agent_id|"Marcus", "command": "move_stage"|"tag"}` or `None` (not a write command).
- No chat_id, no `send` param. The confirm card goes out via `_send_or_telegram(...)` (:349) -> `_H["telegram_send"]` = Telegram, business wholesale (connector.py:2506). **Using this from Slack would put the confirm buttons in Telegram, not Slack.** Existing caller: dashboard `/api/marcus/chat` (connector.py:3785). For Slack use `route(...)` with a Slack `send` instead.

## 2. telegram_agent (tool-using business partner)

### `chat(agent_id, text, history, chat_id, key=None, call=None) -> dict`  (telegram_agent.py:524)
- Returns `{"reply": str, "cards": [card dicts]}`, plus `"error": str` on transport failure. No Anthropic key -> reply text + empty cards.
- `history`: list of `{"role": "user"|<anything else = assistant>, "text": str}` (`_messages`, :504). Caller owns history.
- Business is derived, never passed: `AGENT_BUSINESS.get(agent_id, "hq")` (:44) = solomon->daycare, dyson/eco->agency, marcus/scout/atlas->wholesale, midas->dropship, orion->hq. Unknown agent -> hq.
- `call` injectable (tests); default `review_agent.post_messages`. Model `review_agent.SMART_MODEL`, `MAX_TURNS=6`.
- Tools (TOOLS :285): `api_get`, `api_post`, `file_task`, `route_help`, `find_people` (daycare only). `api_post` and `file_task` never execute; they queue and append a card.
- Card dict: `{"tok","agent","path","body","summary"}`. Max `MAX_CARDS=5` per message, body <= `MAX_BODY=900` chars.
- `card(c) -> (html_text, buttons)` (:270). Buttons: `[[{"text":"✅ Do it","callback_data":"pgo:<tok>"},{"text":"❌ Cancel","callback_data":"pno:<tok>"}]]`.
- Tap handlers: `confirm(tok, chat_id=None) -> {"ok":True,"message":...}|{"error":...}` (:222), `cancel(tok, chat_id=None)` (:259). **Chat-bound**: `str(chat_id)` must equal the chat that queued it, else "that card belongs to another chat". So the `chat_id` Slack passes to `chat()` and to `confirm()` must be the same string. Pending store: `marcus_state/telegram_agent_pending.json`, TTL 1800 (`_queue` :208). Re-checks `allowed()` at tap time. After a tap, `_ON_RESULT["fn"]` (telegram_io `_on_partner_result`) writes "[owner tapped ✅] ..." into `_AGENT_SESS` history + agents_history; Slack would need its own hook or share that one (it is keyed by chat_id).
- SCOPE (per business, URL prefix allowlist; telegram_agent.py:57-71): daycare `/api/daycare/`; agency `/api/agency/`, `/api/coach/`; dropship `/api/dropship/`; wholesale scout/marcus/screening/prep/deals/buyers/contract/pipeline/toolkit/today/conversations/contacts/messages/ace/autopilot/followup/outbound/reply/send/dashboard/analytics/goals; hq system/health/cost/agents/actions/sync/businesses/spend/ops/mission-control/brief/recap. All plus `_SHARED` = `/api/brain/`, `/api/owner-actions`, `/api/hub/task`.
- `allowed(business, method, path) -> (ok, why)` (:134) = under `/api/`, no `..`, not in `DENY` (:72: auth, notify, portal, billing, raw `/api/send` `/api/reply/send`, ace/mode, autopilot/toggle, ops/set, businesses/set, brain/undo...), prefix in SCOPE[business], and route really exists in the catalog parsed from connector source. Tool calls go over loopback HTTP `_http` (:154) to `127.0.0.1:PORT`.
- Needs `telegram_agent.register(PORT, ROUTES, Handler, __file__)` (connector.py:5741, in `main()`).
- Session handling is NOT in telegram_agent. It lives in telegram_io: `_AGENT_SESS = {}` (telegram_io.py:775) `chat_id -> {"agent": str, "history": [ {"role","text"} ]}`, in-memory, last 12 entries kept (:1187). `_partner_turn` (:1166) prefers the shared durable thread `agents_history.recent_for_context(agent_id)` and falls back to `sess["history"]`; after a good reply it calls `agents_history.record(agent_id, text, reply, via="telegram")`. One lock per chat (`_CHAT_LOCKS`). Runs on a daemon thread named for the agent (cost_tracker bills by thread name).

### `quick(cmd, arg, chat_id, business) -> (html_text, [cards]) | None`  (telegram_agent.py:608)
- Zero Claude calls. `cmd` includes the slash: `/status`, `/starts`, `/logins`, `/pin`. Anything else -> `None`.
- `/status` works in any business. The other three return a "daycare command" refusal unless `business in (None, "daycare")`. `/pin` returns a card (reset-pin, queued under chat_id). `/logins` and `/pin` need `arg` (name).
- Telegram calls it as `quick(qcmd, text.partition(" ")[2].strip(), chat_id, chat_biz)` (telegram_io.py:1043-1050), then `_send_cards`.

## 3. telegram_io._handle_message flow  (telegram_io.py:929-1161)

**All Telegram-shaped at the top, no transport-independent function underneath.** Input is a Telegram `msg` dict (`chat.id`, `from.id`, `text`), output goes through `_send_to(chat_id, ..., token=reply_token)` which calls the Telegram HTTP API. Auth is `_msg_authorized(from_id)` (:896) against env `TELEGRAM_CHAT_ID` / `TELEGRAM_ALLOWED_IDS` (Telegram ids only). Business-of-chat comes from Telegram `/bind` state (`_business_of_chat` :147, `_biz_chats` :130).

Order of checks:
1. :936 drop if no text / no chat / not authorized
2. :944 quick-keyboard label map -> rewritten to a command (`☀️ today` -> `/today`)
3. :948 `/start` `/help` (help card, `_AGENT_HELP` :804); :953 `/menu`; :960 `/menu off`
4. :961 strip `@botname` -> `cmd`; :962 `/chats`; :971 `/bind` `/unbind` (writes bizChats, seeds `_AGENT_SESS[chat_id]`); :1001 `/whoami` `/id`; :1004 `/agents` `/who`
5. :1018 `/ace [mode]`
6. :1039 `chat_biz = _business_of_chat(chat_id)`
7. :1043 zero-Claude `/status /starts /logins /pin` -> `telegram_agent.quick`
8. :1058 `telegram_ops.route(...)` ONLY if `chat_biz == "wholesale"` or (`chat_biz is None` and wholesale has no bound chat). True = done.
9. :1068 get/create `sess = _AGENT_SESS[chat_id]` (default agent = business partner, or orion in HQ: `_default_agent` :1223)
10. :1071 agent alias switch (see section 4); :1079 trigger-word switch; :1087-1105 refusal rules (Orion only in HQ; foreign-business agent refused in a business chat; HQ refuses an agent whose business has its own chat)
11. :1106 bare switch with no text -> "Now talking to X"
12. :1115 `/task <text>` (hub task via `agents_hub.send_task`, or `_AGENCY_TASK` for dyson/eco), then falls through with `text = title`
13. :1159 spawn `_partner_turn` thread -> `telegram_agent.chat` -> `_send_to` reply + `_send_cards`. Fallback on exception: `_AGENT_CHAT`/`_AGENCY_CHAT` fn (registered at connector.py:2536/2560)

Button taps are a separate path: `_handle_callback(cq, token, agent_chat)` (:673) parses `"action:arg"`, looks up `_ACTIONS[action]` (registered via `set_actions` connector.py:2384), calls `fn(arg, chat_id)` for `pgo`/`pno` else `fn(arg)`. Also Telegram-shaped (callback_query dict, `answerCallbackQuery`, `editMessageText`). `opsgo/opsno/approve/ace*/dyson*` etc. are plain `fn(arg)` and reusable as-is.

### Smallest extraction (proposal)
Move steps 6-13 (lines ~1039-1160, moved not rewritten) into one function inside telegram_io.py:

```
def handle_text(chat_id, text, chat_biz, reply, send_buttons, spawn):
    # reply(text, markup=None); send_buttons(text, buttons); spawn(fn,*args) runs _partner_turn
```
and split `_partner_turn` (:1166) into `_partner_core(chat_id, agent_id, text) -> (reply, cards)` (history load, `telegram_agent.chat`, history save, no sending) + a Telegram wrapper that sends. `_handle_message` keeps steps 1-5 (Telegram-only: keyboard, menu, bind, chats, whoami) and calls `handle_text(...)` with `_send_to` lambdas. Three small changes needed so Slack ids work: `_default_agent(chat_id)` and the `_biz_chats()` guards at :1096-1105 must take an explicit `chat_biz` (Slack maps channel -> business itself, e.g. config dict) instead of reading Telegram bindings; keep chat ids namespaced (`"slack:C…"`) so `_AGENT_SESS`, `_SESS`, and pending cards never collide with Telegram ids. Existing `RoutingTests` (test_telegram_agent.py:191) already cover the behavior, so a pure move is testable.

Lazier alternative (no edit to telegram_io): Slack module calls primitives directly: map `/forge <cmd>` -> `route("/"+cmd)` for wholesale else `quick()` else `chat(agent, text, hist, "slack:<id>")`, reusing `telegram_io._AGENT_ALIASES`, `_AGENT_TRIGGER`, `_AGENT_SESS`, `_agent_business`, `_BIZ_AGENT`, `_send_cards`-style card loop. Duplicates the refusal rules (steps 10-11). Recommendation: do the extraction; the refusal rules are the safety boundary between businesses and should have one copy.

## 4. Agent aliases

- `_AGENT_ALIASES` (telegram_io.py:776): `/scout /marcus /atlas /dyson /eco /solomon /midas /orion` -> agent id (lowercase name).
- Applied at :1071: `for alias, aid in _AGENT_ALIASES.items(): if low == alias or low.startswith(alias + " ")` -> `sess["agent"] = aid`, `text` = remainder. Rest of the message is the question for that agent.
- Trigger words, same effect without slash (:785 `_AGENT_TRIGGER`, applied :1079): name must be first word followed by end / comma / colon / spaced dash, e.g. `solomon, ratios?`.
- Routing to the agent chat = `sess["agent"]` -> `_partner_turn(chat_id, agent_id, text)` (:1166) -> `telegram_agent.chat(agent_id, ...)`; business follows from `AGENT_BUSINESS`.
- Roster/help text: `_AGENT_ROSTER` (:792). Bus/hub mapping of agents to business: `_BIZ_AGENT` (:127) wholesale->marcus, agency->dyson, daycare->solomon, dropship->midas.
- Wholesale ops route also strips `/marcus|/scout|/atlas ` before its own command table (telegram_ops.py:797).

## 5. Tests

- Framework: stdlib `unittest` (class `TestCase`, `unittest.main()` at the bottom: test_telegram_agent.py:260, test_telegram_ace.py:240). **pytest is not installed** on this Mac (`import pytest` fails). Local `python3` is 3.9.6.
- Run command (cwd matters, modules import bare): `cd "/Volumes/AgentDrive/claude/forge-rei-dash/forge rei" && python3 test_telegram_agent.py` (same for `test_telegram_ace.py`, `test_telegram_biz_chats.py`). `python3 -m unittest test_telegram_agent` also works from that dir. Not executed in this job.
- Stubbing, test_telegram_agent.py:
  - No network: `mock.patch.object(ta, "_http", fake)` (loopback HTTP), `chat(..., call=fake)` injects the Anthropic call (`ta.chat` accepts `key=` and `call=`), `system_prompt` patched to `"sys"`, `ta._source` patched to a fixture connector source string (route catalog parse), `ta.register(7799, routes, handler_cls, tmp_file)`.
  - State dirs: `tempfile.TemporaryDirectory()` + `mock.patch.object(ta, "STATE", tmp/"p.json")` and `mock.patch.object(tg, "STATE", tmp/"telegram.json")`.
  - Telegram: `mock.patch.dict(os.environ, {TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ALLOWED_IDS})`, `tg._api` -> `{"ok":True}`, `tg._send_to` -> appends `(chat, text, buttons)` to a list, `tg.threading.Thread` -> `_SyncThread` (runs inline), `tg._AGENT_SESS.clear()`, `sys.modules["agents_history"]` -> MagicMock, `ta.chat` -> lambda returning `{"reply","cards"}`, `telegram_ops.route` patched to `side_effect=AssertionError` or `return_value=False`.
  - Drive: `tg._handle_message({"chat":{"id":..,"type":"supergroup"},"from":{"id":..},"text":..})`.
- test_telegram_ace.py: same unittest style, but swaps module globals by hand in `setUp` (`ace.STATE`, `conversation_engine.STATE`, `telegram_io._ACTIONS`, `_api`, `send`) into a tmp dir and restores in `tearDown`. It also AST-parses `connector.py` to assert the production `set_actions({...})` registry includes the shared ACE handlers (line ~215-236). **Any edit to the `telegram_io.set_actions` call in connector.py can trip that test**; adding a new key is fine, removing/renaming ACE ones is not.
- Docs consistency: `test_agents_docs.py` (plain functions with `assert`, runnable as `python3 test_agents_docs.py`, exit 1 on failure). It asserts ONLY (a) every agent in `agents_hub.AGENTS` has a card under `../agents/<business>/<id>.md` and Orion has a card, (b) backticked `forge rei/x.py` / `forge-*/...(.py|.md)` paths cited inside `agents/*.md` and its README exist, plus relative md links resolve, (c) any `` `name.md` `` skill cited in a card exists under some `forge-*/skills/`. **It does NOT read CLAUDE.md or AGENTS.md.** Grep confirmed no `test_*` file references CLAUDE.md or AGENTS.md. So editing those two files will not fail a test here. (A new `agents/` card or a card that cites a not-yet-created file would fail it.) AGENTS.md itself says to update CLAUDE.md first (convention, not enforced).

## 6. Deploy

Path for a new `.py` (CLAUDE.md section 7, "Three deploy paths"):
1. Mac `auto-sync.sh` (deploy/auto-sync.sh): `git add -A` + commit + `pull --rebase --autostash` + push every N s. **It commits half-finished files too** (CLAUDE.md: saving auto-deploys in ~60 s). Untracked `forge-slack/` and `docs/...slack-migration-design.md` will be swept up on the next pass.
2. Box `autopull.sh` (60 s systemd timer `forge-autopull.timer`): fetch origin/main; if != `/opt/forge/.deployed_sha`, and commit is older than `FORGE_DEPLOY_DEBOUNCE` (90 s), and < `FORGE_DEPLOY_MAX_TRIES` (3) failed attempts -> run `deploy-pull.sh`.
3. `deploy-pull.sh`: `git reset --hard origin/main` in `/opt/forge/repo` -> validate: **`ast.parse` of every `*.py`** (syntax only, not import) + JSX babel check, abort on failure (live keeps running) -> `rsync -a --delete "forge rei/" -> /opt/forge/forge-rei/` (excludes marcus_state, uploads, __pycache__, ruvector.db, deploy/keys) -> also rsync sibling dirs `forge-agency forge-scout forge-marcus forge-solomon forge-telegram forge-daycare forge-dropship forge-mission` with `--exclude config --exclude '*.env'` -> copy NORTH_STAR.md.
- **`forge-slack/` is NOT in that sibling list** (deploy-pull.sh, the `for d in ...` loop) and `*.env` is gitignored (.gitignore:2) AND excluded from rsync. A Slack config dir/skills dir needs (a) adding `forge-slack` to the loop, (b) the tokens placed on the box by `push.sh` or by hand (push.sh also has no forge-slack entry; grep confirmed none). Same for `forge-slack/config/slack*.env` - do not read them.
- Restart: yes on any changed file NOT matching `jsx|css|html|md|png|jpg|svg|webp|ico|woff` / `ios/` / `docs/` / `.swarm/` / `output/agent-audit/` / `.playwright-mcp/`. A new `.py` triggers `systemctl restart forge-reios` (unless `FORGE_FORCE_RESTART` forces it anyway). `.md`-only changes (CLAUDE.md, AGENTS.md, skills) do NOT restart.
- pip/requirements: **none.** No requirements file anywhere (`find` found none). `setup_droplet.sh` (one-time) does `apt-get install python3 python3-pip git ufw curl rsync` and `pip3 install --break-system-packages requests` (line 30). Deploy never installs anything. A new third-party dep (e.g. `slack_sdk`) must be installed on the box by hand over SSH. Service runs `/usr/bin/python3 -u connector.py` (setup_droplet.sh:87), env from `EnvironmentFile=-/etc/default/forge-reios`.
- Health gate (blocks/rolls back): after restart waits up to 60 s for `/api/system/health` `ok:true`; also needs service `active`, `/api/health` 200, `/marcus_state/heartbeats.json` 404. If fleet was already not-ok before deploy it only WARNs. On failure: rollback to `.deployed_sha`, restart, Telegram alert, burn retry budget. So an import error at module top level in connector (box won't boot) IS caught and rolled back. An error inside a background thread or a lazily-imported module that only fires when a Slack message arrives is NOT caught (health stays ok).
- Feature flag for a new, not-yet-active file: yes. (1) Ship the file with nothing importing it: deploy-pull just rsyncs it, restarts once, code is inert. (2) Gate startup on an env flag like the existing pattern `if os.environ.get("FORGE_DAYCARE_LEADS", "1") != "0":` (connector.py:5794; others 5806, 5815, 5833; loops also need `FORGE_MARCUS=1`, connector.py:51). Use default `"0"` for Slack, import it inside the `if` and a `try/except`, so a bad module cannot break boot. Flip by editing `/etc/default/forge-reios` + `systemctl restart forge-reios` (no push). Telegram-start sites to mirror: connector.py:5909-5921.
- Other paths: `deploy/quick-deploy.sh` (SSH, immediate deploy-pull), `deploy/push.sh root@24.199.81.124` (Mac-only, ships secrets + vault, mirrors code). Offline harness: `deploy/test_deploy_pull.sh`.

## 7. WebSocket / Python version

- Repo-wide `grep -ril websocket` (excluding node_modules, .git, docs): only `docs/superpowers/specs/2026-11-11-slack-migration-design.md` plus the vendored JS `assets/vendor/babel.min.js` and `deploy/.cache/babel-standalone-7.26.4.js`. **No Python websocket client, stdlib or vendored, in the repo.** Python stdlib has none either (would be a hand-rolled RFC 6455 over `ssl`+`socket`). The Slack spec itself says "slack_sdk ... its built-in client needs no extra websocket package - **verify**" (spec line 86) and "slack_sdk if installed on the box, else stdlib websocket - check first" (line 120). Unknown whether `slack_sdk` is installed on the box.
- Box Python version: **Unknown (not pinned anywhere).** `setup_droplet.sh` uses apt `python3`; `deploy/ACCESS.md:8` says Ubuntu 24.04, which normally ships Python 3.12 (inference, not verified). pip on 24.04 needs `--break-system-packages` (already used at setup_droplet.sh:30). Mac dev Python is 3.9.6, so any new code must parse on 3.9 for local tests and on the box version. Check on box: `ssh box 'python3 --version; python3 -c "import slack_sdk"'`.

## Unknowns / flags
- Box python version and whether `slack_sdk` is installed: Unknown.
- `_rule_intent`/`_intent` Claude fallback needs `claude_key`; behavior on Slack identical to Telegram only if `register()` was done (it is, at import of connector).
- `handle_agent_command` + Slack: see section 1 (confirm card would go to Telegram).
- Tests were read, not run; no pass/fail claim.
