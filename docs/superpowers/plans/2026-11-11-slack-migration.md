# Telegram → Slack Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Read the spec and the five reference sheets in `docs/superpowers/plans/refs/` before your task; they hold exact signatures and file:line facts.

**Goal:** Slack runs FORGE end to end like Telegram does today (alerts, tap cards, agent chat, ops commands, n8n DM path) with Telegram still working until the owner flips one flag.

**Architecture:** New `forge rei/slack_io.py` mirrors the public surface of `telegram_io` (send / send_photo / taps / listener). `telegram_io.send*` gets a thin, exception-isolated hook that mirrors to Slack by `FORGE_CHAT_TRANSPORT`. Slack taps call the **same** `telegram_io._ACTIONS`. Socket Mode listener runs on the box inside the connector process. n8n gets a new sibling workflow for owner DMs; the live Telegram workflow is not edited.

**Tech Stack:** Python 3 stdlib + `requests` (box has nothing else), `unittest`, Slack Web API + Socket Mode (`slack_sdk` only if the box probe says it can be installed), n8n workflow SDK.

**Spec:** `docs/superpowers/specs/2026-11-11-slack-migration-design.md` (approved 2026-11-11). Refs: `plans/refs/00-telegram-audit.md`, `01-transport.md`, `02-idempotency.md`, `03-inbound-deploy.md`, `04-n8n.md`.

## Base (verified 2026-11-11 by Task 0, see `refs/05-box-probe.md`)
The live source is `~/forge rei dash` (launchd `auto-sync.sh` → GitHub `yahglizz/forge-rei-dash` `main` → box `autopull` every 60 s). The drive checkout `/Volumes/AgentDrive/claude/forge-rei-dash` was **102 commits behind** and is NOT the deploy source. This worktree is reset to `origin/main` (`8817e80`). Refs `00-04` were written against the stale base: **trust the code over their line numbers**; `refs/07-delta.md` lists what drifted. Merging to `main` and pushing = deploy to the box (flags default off). Box facts: Python 3.12.3, `slack_sdk` absent but installable with `--break-system-packages`, repo `/opt/forge/repo`, live tree `/opt/forge/forge-rei`, config `/opt/forge/forge-telegram/config/`, env file `/etc/default/forge-reios`, unit `forge-reios`, health `/api/health` + `/api/system/health`. `deploy-pull.sh` does not rsync a top-level `forge-slack/` dir: Slack code lives in `forge rei/` only.

## Global Constraints
- Flag: `FORGE_CHAT_TRANSPORT` ∈ `telegram` (default) | `both` | `slack`. Listener flag: `FORGE_SLACK=1` AND `FORGE_MARCUS=1`; default off. Every new import in `connector.py` sits inside `try/except` so a Slack failure can never stop the connector.
- Channels: `#forge-hq`, `#forge-daycare`, `#forge-agency`, `#forge-wholesale` (dropship skipped). Private by default. Mapping in `marcus_state/slack.json`; card registry in `marcus_state/slack_cards.json`. Never write Slack keys into `telegram.json` (its `_load()` drops unknown keys).
- Slack tap auth: user id ∈ `SLACK_ALLOWED_USER_IDS` **and** channel ∈ {HQ, bound business channel} **and** click channel == card's issuing channel. Failing → ephemeral "Not authorized", nothing runs.
- `callback_data` format `"<action>:<arg>"` (≤64 bytes) is reused unchanged as the Slack button `value`.
- Tests: stdlib `unittest`, run as `cd "forge rei" && FORGE_MARCUS=0 python3 -m unittest <module>`. Tests never call a real action function (no SMS, ad launch, deploy, PIN reset, GHL write); stub `_ACTIONS`.
- Secrets: never print or log tokens or message bodies; extend `telegram_io._redact` to cover `xoxb-`, `xoxp-`, `xapp-`. Env files are gitignored (`*.env`).
- **Work in a git worktree** `/Volumes/AgentDrive/claude/forge-slack-wt` on branch `slack-migration` (from `main`). Saving files in the live checkout can auto-deploy to the box within ~60 s. Merge to `main` only at Task 11, after every flag-off check passes. No commits to `main` before that.
- Locks are `threading` locks: the listener must run in the connector's process, not a separate one.
- Runtime agents stay Haiku/Sonnet (`test_model_policy.py`); this plan changes no model use.

## Review Focus
1. Slack redelivers an event/interaction when the 3 s ack is late (`retry_num` set) → the same tap must not run twice. Dedupe on envelope/event id before dispatch. (Task 5, 4)
2. The bot's own posts come back as `message` events → ignore `bot_id` and any `subtype`; no reply loops, no n8n run burn. (Task 6, 9)
3. Telegram-HTML text with `<`, `&`, long bodies (>3000 chars) or a missing business chat → converted, split, falls back to HQ, never raises. (Task 2)
4. Tap on a card after a box restart or after 3-day/1-hour expiry → "expired", not a crash; card registry survives restart. (Task 4)
5. Mirror failing or Slack being down must never delay or break the Telegram send. (Task 3)
6. Same card tapped in Telegram and Slack → second tap refused, other message edited to "handled in …". (Task 4)

---

### Task 0: Probe the box and prove the deploy path (read-only)
**Files:** Create `docs/superpowers/plans/refs/05-box-probe.md`. **Model:** Sonnet (`sonnet-worker`).
**Interfaces:** Produces facts every later task needs: `box_python_version`, `slack_sdk_installable: bool`, `box_repo_path`, `box_config_dir`, `deploy_source: github-main | other`, `systemd_unit_env_path`.
- [ ] Step 1: Read `forge rei/deploy/ACCESS.md`, `autopull.sh`, `deploy-pull.sh`, `setup_droplet.sh`; state exactly which git remote/branch the box pulls and which local dir `auto-sync.sh` pushes from. Resolve the memory note that calls this drive checkout "stale": run `git -C <dir> log -1` on `/Volumes/AgentDrive/claude/forge-rei-dash` and `~/forge rei dash` and compare with `origin/main`.
- [ ] Step 2: Over SSH (key `~/.ssh/forge_droplet`, see ACCESS.md; **read-only commands only**): `python3 --version`, `python3 -c "import slack_sdk"`, `pip3 --version`, `pip3 download slack_sdk --no-deps -d /tmp/probe` (then delete `/tmp/probe`), `systemctl cat forge-reios | grep -c Environment`, list the dir that holds `forge-telegram/config/` (names only).
- [ ] Step 3: Write the sheet. Expected: every field above filled or marked Unknown. Do not print secrets.

### Task 1: Fix the unsafe-on-second-tap actions (existing Telegram path)
**Files:** Modify `forge rei/marcus_engine.py:~1215-1232` (U1), `forge rei/agency_dyson.py:~577` (U2), `forge rei/daycare_ads_tg.py:62-68,97,~620` (U3). Test: `forge rei/test_tap_idempotency.py` (new). **Model:** Opus 5.5. **Depends:** none. Skip U4/U5 (no outward effect; YAGNI, noted in spec).
**Interfaces:** Produces unchanged public signatures; behavior only: `MARCUS.approve(pid)` pops the proposal before any state write after the SMS call; `agency_dyson.decision(did, "approve"|"reject")` returns `{"error": ...}` unless draft status ∈ {`draft`,`revision`}; `daycare_ads_tg._save(...) -> bool` and `_claim(...)` returns an error when `_save` is False; `adslaunch` refuses cards older than `LAUNCH_CARD_MAX_AGE = 6*3600` seconds.
- [ ] Step 1: Write failing tests, with stubbed `ghl_post`/deploy/Meta calls: `test_approve_second_tap_after_persist_failure_does_not_resend`, `test_dyson_reject_then_approve_refused`, `test_dyson_approve_then_reject_refused`, `test_ads_claim_fails_closed_when_save_fails`, `test_adslaunch_refuses_stale_card`.
- [ ] Step 2: Run `FORGE_MARCUS=0 python3 -m unittest test_tap_idempotency` — expect 5 FAIL.
- [ ] Step 3: Implement the four behaviors per Interfaces (details and line refs in `refs/02-idempotency.md` U1-U3).
- [ ] Step 4: Run the new tests plus `test_telegram_ace test_telegram_agent test_daycare_ads_tg test_watchdog_alerts` — expect all PASS, 19+ prior tests unchanged.
- [ ] Step 5: Leave uncommitted in the worktree; Task 11 merges.

### Task 2: `slack_io` core (send, format, channel map, card registry)
**Files:** Create `forge rei/slack_io.py`, `forge rei/test_slack_io.py`. Modify `forge rei/telegram_io.py` `_redact` only. **Model:** Opus 5.5. **Depends:** Task 0 (state dir).
**Interfaces (Produces):**
`mode() -> str` (env `FORGE_CHAT_TRANSPORT`, default `"telegram"`); `to_mrkdwn(html: str) -> str`; `split_text(text: str, limit: int = 2900) -> list[str]`; `chat_for(business: str | None) -> str | None` (business channel → HQ → None); `bind(business: str, channel_id: str) -> None`; `render_blocks(text: str, buttons: list[list[dict]] | None, card_id: str | None) -> list[dict]` (buttons are `{"text","callback_data"}`; Block Kit button `value=callback_data`, `action_id=f"{callback_data}"[:255]`); `send(text: str, business: str | None = None, buttons=None, dedupe_key: str | None = None) -> bool`; `send_photo(photo, caption: str, business=None, buttons=None, dedupe_key=None) -> bool` (match the exact `photo` type used by `telegram_io.send_photo`, see `refs/01-transport.md`); `register_card(card_id: str, channel: str, ts: str, actions: list[str]) -> None`; `get_card(card_id: str) -> dict | None`.
- [ ] Step 1: Failing tests: `test_to_mrkdwn_escapes_amp_lt_gt_and_converts_b_i_code_a`, `test_split_text_never_exceeds_limit_and_preserves_content`, `test_chat_for_falls_back_to_hq_then_none`, `test_render_blocks_one_button_per_callback_value_len_le_64`, `test_send_uses_stubbed_api_and_returns_false_on_slack_error_without_raising`, `test_send_dedupes_same_key_within_900s`, `test_redact_covers_xoxb_xoxp_xapp`, `test_state_file_is_slack_json_not_telegram_json`.
- [ ] Step 2: Run — expect FAIL (module missing).
- [ ] Step 3: Implement. Load `forge-slack/config/slack.env` + `slack-agents.env` into `os.environ` the way `telegram_io` loads its env (real env wins). One `_api(method, token, **params)` over `requests`, 10 s timeout, errors returned not raised, token redacted in any message. Own `threading.Lock` and state files under `marcus_state/`; never call a locked helper while holding the lock (`refs/01-transport.md` §6).
- [ ] Step 4: Run `test_slack_io test_telegram_biz_chats` — expect PASS.
- [ ] Step 5: Live check (harmless): `FORGE_CHAT_TRANSPORT=both python3 -c "import slack_io; print(slack_io.send('slack_io smoke', business=None))"` posts one line to `#forge-test` via `SLACK_TEST_CHANNEL_ID` only when `SLACK_ONLY_TEST=1`; expect `True`, then delete the message with `chat.delete`.

### Task 3: Mirror hook in `telegram_io`
**Files:** Modify `forge rei/telegram_io.py` (`send` after `_dedupe_commit` ~line 359, `send_photo` success branch ~line 399, `_send_to` ~line 907, plus a `_mirror` helper). Test: `forge rei/test_slack_mirror.py`. **Model:** Opus 5.5. **Depends:** Task 2.
**Interfaces:** Consumes `slack_io.send/send_photo/mode`. Produces `telegram_io._mirror(kind: str, **kw) -> None` — runs `slack_io` on a daemon thread inside try/except; no-op when `mode()=="telegram"`. When `mode()=="slack"`, `send`/`send_photo` return `slack_io`'s result and skip the Telegram HTTP call. Do not mirror in `send_photo`'s failure path (it falls back to `send` and would double-post). The `_send_to` hook is **required**, not optional: `agent_gateway._send_card` and `telegram_agent._deliver_mac` post approval cards through it. Pass the card's token/callback data and `origin_chat` to `slack_io` so Task 4 can register them. Startup block for the listener goes after `connector.py` ~:6333 inside `if LOOPS_ENABLED:`.
- [ ] Step 1: Failing tests (use the synchronous-Thread patch pattern from `test_telegram_biz_chats.py`): `test_mode_telegram_never_calls_slack`, `test_mode_both_calls_slack_once_per_send`, `test_mode_slack_skips_telegram_api`, `test_slack_exception_never_breaks_telegram_send`, `test_send_photo_failure_fallback_mirrors_once`, `test_send_to_agent_reply_is_mirrored`.
- [ ] Step 2: Run — expect FAIL.
- [ ] Step 3: Implement `_mirror` and the three call sites.
- [ ] Step 4: Run `test_slack_mirror test_telegram_biz_chats test_watchdog_alerts test_telegram_agent test_telegram_ace test_daycare_ads_tg` — expect all PASS.
- [ ] Step 5: Confirm with `FORGE_CHAT_TRANSPORT` unset that no Slack function is called anywhere (grep the test output; default must be inert).

### Task 4: Slack taps, auth and consumed-sync
**Files:** Modify `forge rei/slack_io.py`; Create `forge rei/test_slack_taps.py`. Register one harmless action `slackselftest` in `connector.py`'s `set_actions` dict (edits the message only). **Model:** Opus 5.5 (+ Task 12 security review). **Depends:** Tasks 1, 2.
**Interfaces:** Produces `authorized(user_id: str, channel_id: str, card: dict | None) -> bool`; `handle_interaction(payload: dict) -> dict` (Block Kit `block_actions` payload in; `{"ok": bool, "result": ...}` out; edits the message with `chat.update` to show the result and drop the buttons; posts an ephemeral on refusal). Consumes `telegram_io._ACTIONS` and `telegram_io._TAP_AGENT` + `action_log.record_result(...)` exactly as `_handle_callback` does. `pgo`/`pno` receive the chat string `f"slack:{channel_id}"` (same string must go to `telegram_agent.chat` in Task 6). **Gateway/Mac cards (refs/07-delta.md §2):** `agent_gateway._send_card` and `telegram_agent._deliver_mac` call `_send_to` directly and issue `pgo` tokens bound to the *Telegram* chat id. `register_card` therefore also stores `origin_chat` (the Telegram chat id the token was issued for); for `pgo`/`pno`, once `authorized(...)` passes (user + channel == card channel), call `telegram_agent.confirm(tok, origin_chat)` — not `f"slack:{channel}"`. Keep the Mac-card owner rule from `_handle_callback` (~:719-726). Cards created by Slack-originated chats (Task 6) use `f"slack:{channel_id}"` instead. Consumed-sync: first accepted tap marks `card_id` consumed in `slack_cards.json` and edits the Telegram twin when a `tg_message_id` is recorded.
- [ ] Step 1: Failing tests with stub `_ACTIONS`: `test_wrong_user_refused_action_not_called`, `test_right_user_wrong_channel_refused`, `test_click_channel_must_equal_card_channel`, `test_unknown_or_expired_card_says_expired`, `test_second_tap_same_card_refused`, `test_retry_delivery_same_envelope_runs_once`, `test_result_audited_via_action_log`, `test_pgo_gets_slack_chat_string`.
- [ ] Step 2: Run — expect FAIL.
- [ ] Step 3: Implement per Interfaces.
- [ ] Step 4: Run `test_slack_taps` and the Task 1/3 suites — PASS.

### Task 5: Socket Mode listener and box wiring
**Files:** Modify `forge rei/slack_io.py` (`run_forever(stop: threading.Event | None = None) -> None`), `forge rei/connector.py` `main()` (start only when `FORGE_SLACK=1` and `LOOPS_ENABLED`, import inside `try`). Test: `forge rei/test_slack_listener.py`. **Model:** Opus 5.5. **Depends:** Tasks 0, 4.
**Interfaces:** Consumes the Task 0 decision. If `slack_sdk` is installable on the box use its Socket Mode client; otherwise write a minimal stdlib websocket client (RFC 6455 framing, ping/pong, reconnect with backoff) — record the choice in the file's docstring. Envelope handling: ack within 3 s on the receiving thread, then dispatch on a worker thread; dedupe on `envelope_id`/`event_id` (ring of 500, 10 min). Routes: `interactive` → `handle_interaction`; `slash_commands` → `slack_inbound.handle_slash` and `events_api` → `slack_inbound.handle_message_event`, both resolved by lazy import inside `try` and ignored (logged once) while `slack_inbound` does not exist yet, so Task 5 ships and tests without Task 6.
- [ ] Step 1: Failing tests with a fake socket client feeding canned envelopes: `test_envelope_acked_before_dispatch`, `test_duplicate_envelope_dispatched_once`, `test_unknown_envelope_type_ignored`, `test_reconnect_after_disconnect`, `test_listener_not_started_without_flags`.
- [ ] Step 2: Run — expect FAIL.
- [ ] Step 3: Implement; confirm `connector.py` edit is one small atomic block, flag-off by default, and `test_telegram_ace.py` (AST check of `set_actions`) still passes.
- [ ] Step 4: Run all suites listed in Tasks 1-4 — PASS.

### Task 6: Inbound — `/forge`, channel text, DMs
**Files:** Create `forge rei/slack_inbound.py`, `forge rei/test_slack_inbound.py`; modify `forge rei/slack_io.py` to delegate. **Model:** Opus 5.5. **Depends:** Task 5.
**Interfaces:** `handle_slash(payload: dict) -> dict` (`/forge <text>` → `telegram_ops.route(text, f"slack:{channel}", send)` where `send(text, buttons)` posts via `slack_io.send` to the same channel; returns an immediate ack body ≤3 s); `handle_message_event(event: dict) -> None` (ignore `bot_id`/`subtype`/non-owner; in a business channel or the owner's DM with the bot → alias detection using `telegram_io._AGENT_ALIASES` then `telegram_agent.chat(...)` with `AGENT_BUSINESS` for the channel's business; card replies from `telegram_agent.card()` rendered via `render_blocks`). Do **not** refactor `telegram_io._handle_message` (spec C7: reuse the routers, not the Telegram-shaped handler). `/forge bind <biz>` inside a channel calls `slack_io.bind`. `/forge help` lists the same commands as `telegram_ops._CMD_RE` (`refs/03-inbound-deploy.md` §1).
- [ ] Step 1: Failing tests (stub `telegram_ops.route`, `telegram_agent.chat`): `test_forge_today_routes_to_ops_route`, `test_forge_bind_sets_channel_for_business`, `test_non_owner_message_ignored`, `test_bot_message_ignored_no_loop`, `test_business_channel_text_goes_to_partner_chat_for_that_business`, `test_alias_prefix_solomon_routes_to_daycare_agent`, `test_confirm_card_chat_string_matches_tap_chat_string`, `test_help_lists_every_ops_command`.
- [ ] Step 2: Run — expect FAIL. Step 3: Implement. Step 4: Run all suites — PASS.

### Task 7: Slack app settings (done by the main thread with the browser harness)
**Files:** none in repo; update spec. **Model:** main thread (`browser-harness`, signed-in Chrome). **Depends:** none (run in parallel with Tasks 1-2).
- [ ] Step 1: Open app A (`A0CGH3MHL15`) → App Manifest. Read the current manifest, **merge** (never replace): add bot scopes `commands`, `files:write`, `groups:write`, `channels:manage`; enable Interactivity; add slash command `/forge` ("Run a FORGE command"); bot events `message.channels`, `message.groups`, `message.im`, `app_mention`; keep `socket_mode_enabled: true`. Type text with real input events after `Page.bringToFront` (CodeMirror API alone does not update the form — learned 2026-11-11).
- [ ] Step 2: Save, **Reinstall**. Verify the `x-oauth-scopes` header from `auth.test` lists the new scopes and `python3 forge-slack/smoke_test.py` still passes.

### Task 8: Channels and bindings
**Files:** Create `forge-slack/bootstrap_channels.py`. **Model:** Sonnet. **Depends:** Tasks 2, 7.
**Interfaces:** `python3 forge-slack/bootstrap_channels.py [--dry-run]` creates `#forge-hq`, `#forge-daycare`, `#forge-agency`, `#forge-wholesale` as **private** channels if missing, invites `SLACK_ALLOWED_USER_IDS` and the bot, writes the mapping with `slack_io.bind`. Idempotent.
- [ ] Step 1: Run `--dry-run`, expect the four names listed, nothing created. Step 2: Run live; expect four channel ids and `marcus_state/slack.json` bindings. Step 3: Re-run; expect "already exists", no changes.

### Task 9: n8n — new `FORGE Slack Agent Chat` workflow
**Files:** none in repo; create the workflow via the n8n MCP (skill `n8n-workflow-builder`); document in `docs/FORGE_CURRENT_ARCHITECTURE.md` (Task 12). **Model:** Opus 5.5. **Depends:** none (parallel).
**Interfaces:** Nodes in order: Slack Trigger (`message`, app B credential `FORGE Slack Agents Bot`) → Filter (drop `bot_id`, any `subtype`, `user` ≠ `U0CGS6KHZ6X`) → Set (`route` by first-word regex exactly as the Telegram workflow, `body.idempotency_key = event.ts`, `body.sender_id`: see Task 0 note) → Execute Workflow `FORGE Agent Dispatch` (id `XNvR287qpWUR6xPk`, unchanged) → Slack post in the DM thread. Do not edit `FORGE Agent Chat` (`tEvB32PbQepvq9gl`). Budget guard: filter first so ignored events cost no downstream runs.
- [ ] Step 1: Read `refs/04-n8n.md`; validate with `validate_workflow`; create inactive. Step 2: Pin-data dry run (`test_workflow`) with a fake owner DM and a fake bot echo — expect the owner event reaches Dispatch, the bot echo stops at the Filter. Step 3: Fetch App B's signing secret and Event Subscriptions URL via the browser harness; set Request URL to the workflow's production webhook, bot event `message.im`; Slack must show "Verified". Step 4: Activate; DM `forge_agents` "orion ping"; expect a reply and one execution. Step 5: Record execution count against the 2,500 budget.

### Task 10: Box deploy, secrets and soak start
**Files:** none new; box config. **Model:** Opus 5.5. **Depends:** Tasks 0-9 and Task 11 steps 1-2 (merge). **Order:** Task 11 steps 1-2 → Task 10 → Task 11 steps 3-4.
- [ ] Step 1: Copy `slack.env`, `slack-agents.env` to the box config dir from Task 0 (mode 600, owner only, never printed); install `slack_sdk` if Task 0 chose it. Step 2: Set `FORGE_SLACK=1` in the unit env; leave `FORGE_CHAT_TRANSPORT=telegram` for the first restart. Step 3: Restart via the normal deploy gate; expect health OK and a log line "slack listener connected" with no token text. Step 4: Set `FORGE_CHAT_TRANSPORT=both`.

### Task 11: Merge inert code, then end-to-end proof
**Files:** merge `slack-migration` → `main`. **Model:** Opus 5.5 + main thread. **Depends:** Tasks 1-6, 8.
- [ ] Step 1: In the worktree run every suite from Tasks 1-6 and `test_agents_docs`; expect PASS; `python3 -m py_compile` on touched files. Step 2: Merge with flags off; confirm the box deploy gate passes and Telegram alerts still arrive (watch `connector.err.log` read-only). Step 3 (after Task 10): E2E in `both` — a live alert per channel, a `slackselftest` tap (expect edit-in-place, then second tap refused), wrong-channel tap refused, `/forge today`, a channel question to each business agent, an owner DM through n8n, a deliberate Slack outage (revoke nothing; point `slack_io` at a bad host) with Telegram still delivering. Step 4: Read the box logs for each; report PASS/FAIL per check.

### Task 12: Security review, docs, soak and cutover runbook
**Files:** Modify `CLAUDE.md` (§2, §5), `AGENTS.md`, `docs/FORGE_CURRENT_ARCHITECTURE.md`, daily note; Create `docs/runbooks/slack-cutover.md`. **Model:** security review Opus 5.5 (`security-auditor`); docs Haiku. **Depends:** Task 11.
- [ ] Step 1: Security-auditor reviews `slack_io.py`, `slack_inbound.py`, the `connector.py` and `telegram_io.py` hooks for: tap auth bypass, replay, token leakage in logs, retry double-run. Fix findings, re-run suites. Step 2: Haiku updates docs; `test_agents_docs` PASS. Step 3: Runbook: soak checklist (3 days in `both`), the exact one-line flip to `FORGE_CHAT_TRANSPORT=slack`, rollback (set back to `telegram`), then deactivate (not delete) the Telegram trigger in `FORGE Agent Chat`. **The flip itself waits for the owner's go.**
