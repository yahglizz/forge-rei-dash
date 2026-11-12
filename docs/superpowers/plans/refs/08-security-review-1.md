# Security review 1: Slack migration (Tasks 1-4, listener skimmed)

Date 2026-11-11. Read-only review. No file edited except this one. No network, no sends.
Worktree `/Volumes/AgentDrive/claude/forge-slack-wt`, branch `slack-migration`, base `origin/main` 8817e80.

**Bottom line:** no CRITICAL. **One HIGH:** spec C4 ("one live button per card") is not built, so a mirrored card stays live in the other app after a tap. It blocks turning on `FORGE_CHAT_TRANSPORT=both` with real outward taps. It does not block merging the inert code (flags off). Three MEDIUM, six LOW.

## What I read (line ranges at review time)
- `forge rei/slack_io.py`: whole file. First read at 525 lines. Re-read when it reached 724 lines: 1-80 (only the docstring and `import logging` changed), 380-724. Tap code (now 394-536) is the same apart from the line shift. Listener code (539-724) I skimmed only to answer "who calls handle_interaction". It was still being written, so I did not review it.
- `forge rei/telegram_io.py`: 50-249, 337-493, 690-849, 1002-1030 (plus `git diff origin/main`).
- `forge rei/connector.py`: diff only (2495-2502, `slackselftest`).
- `forge rei/agent_gateway.py` 153-158, 505-507, 525-559, 690-717. `forge rei/telegram_agent.py` 320-345, 375-445.
- Task 1 diffs: `marcus_engine.py` (read 1180-1250), `agency_dyson.py` (decision), `daycare_ads_tg.py` (read 72-97 + diff).
- Tests: `test_slack_taps.py`, `test_slack_mirror.py` in full. I ran them with `test_tap_idempotency` offline: `FORGE_MARCUS=0 python3 -m unittest test_slack_taps test_slack_mirror test_tap_idempotency` gave **24 tests OK** (verified).
- `refs/02-idempotency.md`, spec, plan.

## Trust boundaries (STRIDE, short)
1. Slack `block_actions` payload → `handle_interaction`. Spoofing, tampering and replay. Today the only caller is `slack_io._dispatch` (slack_io.py:640-641). It runs on the Socket Mode client (`run_forever`), which authenticates with the xapp token. So the payload is authentic **as long as nothing else ever calls it** (see LOW-4).
2. Telegram send → Slack mirror. Information disclosure (which channel gets the copy) and denial of service (can the mirror hurt Telegram).
3. Config files → `os.environ`. Tampering by misconfiguration (MEDIUM-2).
4. State files `marcus_state/slack*.json`. Races and disclosure (LOW-3).

---

## HIGH

### H1. Cross-transport single use (spec C4) is not built. Each mirrored card has two live buttons.
- **Location:** `slack_io.py:220-229` stores `tg_message_id`, but nothing reads it. `slack_io.py:431-444` `_claim` marks only the Slack card as used. `telegram_io.py:747-845` `_handle_callback` never checks `slack_cards.json`. The second live card is created by the mirror calls at `telegram_io.py:420-421`, `:466-468` and `:1022-1023`.
- **What happens:** in `both` mode, a tap in Telegram removes the Telegram buttons but leaves the Slack twin live for 7 days (`_CARD_TTL`). A tap in Slack leaves the Telegram buttons live (Telegram buttons never expire). The only guard is whether each action handles a second call safely (refs/02).
- **Scenario A (outward, real SMS):** the owner taps Approve in Telegram. `ghl_post("/conversations/messages")` (`marcus_engine.py:1209`) times out after GHL has already accepted the SMS. The exception fires before the pop at `:1217`. The `except` block (`:1234-1242`) then releases the sms_guard reservation and returns "⚠ Read timed out". Telegram drops its keyboard. The Slack Approve is still live, and the owner naturally retries there. That sends a second real SMS to the seller, unless the sms_guard dedupe catches it. **Not verified** whether it does on this path.
- **Scenario B (cost and duplicates):** `handoff` and `dysonplan` are still unsafe on a second tap (refs/02 U4/U5, skipped in Task 1). Tapping once per app means two Claude runs and two draft cards.
- **Scenario C (stale state):** a 7-day-old Slack `opspause`/`opsresume`/`reqdismiss` tap overwrites a newer state.
- **Minimal fix:**
  1. Key a shared claim by `f"{origin_chat}:{tg_message_id}"` in `slack_cards.json`.
  2. Add `slack_io.claim_twin(chat_id, message_id) -> bool`. If the Slack card is already used, it returns False and Telegram answers "Handled in Slack" without dispatching. Otherwise it marks the card used and calls `chat.update` to drop the Slack buttons. If the Slack card is not registered yet (the mirror is async), it writes a tombstone so `register_card` creates the card already used.
  3. Call `claim_twin` in `_handle_callback` right after auth, before `fn(...)`, inside try. If it raises, refuse (fail closed) only when mode != telegram.
  4. In `_interaction`, after a successful `_claim`, call `editMessageReplyMarkup` on `(origin_chat, tg_message_id)` with `{"inline_keyboard": []}`. Store which bot token sent the card (alerts bot or agent bot), because agent-bot cards must be edited with the agent token.
  5. Tests: `test_telegram_tap_consumes_slack_twin`, `test_slack_tap_refused_after_telegram_tap`, `test_telegram_tap_before_slack_register_tombstones`.

---

## MEDIUM

### M1. Mac command output is mirrored into the Slack HQ channel, not to the owner privately
- **Location:** `telegram_agent.py:409` (`_send_to(owner_id, _mac_output_text(...))`) → `telegram_io.py:1022` `_mirror("send_to")` → `telegram_io.py:358` `_business_of_chat(owner_id)` is None → `slack_io.chat_for(None)` = HQ channel.
- **Scenario:** a Mac card runs "as you, with your keys and signed-in sessions" (`telegram_agent.py:452-453`). The Telegram design sends its output **only** to the owner's own id ("Staff can sit in a business chat", `:403`). In `both` mode the full output, which may hold env values or API keys, is posted to `#forge-hq`. Slack keeps it, indexes it and pushes it to phones. `slack_io._redact` masks only Slack tokens. In `slack` mode it posts once per id in `FORGE_GATEWAY_OWNER_IDS`. Agent-bot DM replies to the owner (`telegram_io.py:1316`, `:1342`) also land in HQ.
- **Minimal fix:** in `_slack_send`'s `send_to` branch, `if chat in agent_gateway._owner_ids(): return False` (both mode: the Telegram DM already has it). For `slack` mode, send to a configured owner DM (`SLACK_OWNER_DM_ID`, a `D…` id), or drop it with a log line. Add a test for owner-id routing.

### M2. Slack config files can flip the transport flag and the test-routing switch
- **Location:** `slack_io.py:65-79` copies **every** key from `slack.env`, `slack-agents.env` and `slack-channels.env` into `os.environ`. The redirect is used at `slack_io.py:169-170` and `:186-187`.
- **Scenario 1:** Task 2 Step 5 uses `SLACK_ONLY_TEST=1`. If that line ends up in `slack.env` on the box, every business card (seller names and phones, parent data, ad spend) goes to `SLACK_TEST_CHANNEL_ID`. That is the existing `#forge-test` channel, and who is in it is **Unknown**. `_channels()` also makes that channel valid for taps.
- **Scenario 2:** `FORGE_CHAT_TRANSPORT=both` placed in `slack.env` turns on mirroring in **every** process that imports `telegram_io` where that file exists, including the Mac checkout (the spec says real Slack tokens live there). The Mac then posts cards and registers them in its own `marcus_state`. Box taps on them say "expired" (fail closed), but the result is duplicate, confusing traffic.
- **Minimal fix:** an allowlist in `_load_env_file`. Accept only `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_AGENTS_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_AGENTS_SIGNING_SECRET`, `SLACK_ALLOWED_USER_IDS`, `SLACK_TEST_CHANNEL_ID` and keys matching `^SLACK_CHANNEL_[A-Z]+$`. `SLACK_ONLY_TEST` and any `FORGE_*` must come from the real process env only. Add a test for the loader.

### M3. `slack` mode loses messages without any signal
- **Location:** `telegram_io.py:379-381` `_slack_only` returns `{"error": "slack send failed"}`. It does not call `_set_error`, prints nothing and gives no reason. `slack_io.py:337-338` (no token or no channel) and `:349-350` (no blocks) return False with no log. A Slack `ratelimited` error (`:353-355`) is logged and the message dropped, with no retry.
- **Scenario:** after the flip, one unbound channel, a missing token on the box, or a burst over about 1 message/s/channel makes alerts and approval cards disappear. About 45 callers ignore the return value. Telegram health stays green because `lastError` is never set. This is fail-closed for security but fail-silent for operations.
- **Minimal fix:** on failure, `_slack_only` calls `_set_error("slack: <reason>")` and prints once. `_deliver` logs its reason through `_warn_once` (already exists, :567). `status()` reports `configured = bool(_token() and chat_for(None))`. Runbook gate: refuse to set `slack` unless `status()["connected"]` is true and HQ is bound. Optional: honour `Retry-After` once on `ratelimited`.

---

## LOW

### L1. Mac cards can never be run from Slack (fails closed; parity gap hidden by a stub)
`slack_io.py:493-499` passes the Slack `U…` id to `telegram_io._foreign_mac_tap`. That calls `agent_gateway.is_owner`, which checks `FORGE_GATEWAY_OWNER_IDS` (Telegram ids, `agent_gateway.py:153-158`), so the result is always "foreign" and the tap is always refused. The tests stub this function (`test_slack_taps.py:55`, `:181`), so the gap is invisible. Putting the Slack id into `FORGE_GATEWAY_OWNER_IDS` would also make `_deliver_mac` call `_send_to("U…")`. **Fix:** add `SLACK_OWNER_IDS`. In slack_io: `foreign = telegram_agent.is_mac_card(arg) and user not in SLACK_OWNER_IDS`, where empty means refuse. Add one test against the real function.

### L2. Copies can land in the wrong business channel when one Telegram chat serves two businesses
`telegram_io.py:148-149`, used at `:358`, returns the **first** business bound to a chat. If two businesses share one Telegram group (**Unknown** on the live box), every `_send_to` copy for the second business (agent replies, gateway `pgo` cards) goes to the first business's Slack channel. A future `_send_to("slack:C…")` (Task 6) would land in HQ. Also, a Slack bind overrides the env value (`slack_io.py:175`), the reverse of Telegram where env wins (`telegram_io.py:131-140`). Once `/forge bind` exists, a bind run in the wrong channel cannot be overridden by a pinned env. **Fix:** return a business only when exactly one matches, else None (HQ). Send a `slack:<C>` chat straight to channel `<C>`. Make env win. In Task 6, `/forge bind` must be owner-only and accept private channels only (`conversations.info` `is_private`).

### L3. State files: no test isolation, default permissions, threading-only lock
`slack_io.py:50` sets `STATE` to the live `marcus_state` with no `forge_atomic.guard_state_path` (`forge_atomic.py:31-47`). A test that forgets to patch `STATE` writes the live `slack_cards.json`. `_write` (`:136-144`) uses a fixed tmp name and the default umask (probably 0644). The lock is per process. That is fine today, because the only caller of `_claim` is `_dispatch` inside `run_forever`, which runs in the connector. It breaks if the listener ever becomes its own service. **Fix:** `STATE = forge_atomic.guard_state_path(HERE / "marcus_state")`, write with `forge_atomic.atomic_write_json`, `chmod 0o600`, and add a docstring rule: "listener must run in the connector process".

### L4. `handle_interaction` trusts the identity fields in the payload
It is safe today: the only caller is `_dispatch` (`slack_io.py:640-641`), fed by the authenticated Socket Mode client. But `slack.env.example` lists `SLACK_SIGNING_SECRET` for "HTTP events". If anyone later wires an HTTP or n8n path into `handle_interaction`, the user, channel and value fields are chosen by the attacker, and only the 64-bit random card id stands in the way. **Fix (2 lines):** when `SLACK_APP_ID`/`SLACK_TEAM_ID` are set, require `payload["api_app_id"]` and `payload["team"]["id"]` to match. Add a comment: never call this from HTTP without the v0 HMAC check and a 5-minute timestamp check.

### L5. Redaction gaps
`slack_io.py:93` `_TOKEN_RE` and `telegram_io.py:208` `_SLACK_TOKEN_RE` miss `xoxe-` (refresh tokens). `telegram_io._redact` does not mask the `SLACK_SIGNING_SECRET` value. **Fix:** use `x(?:ox[abeposr]|app)-[A-Za-z0-9.-]+` in both, and add the signing secrets to telegram_io's env-value list.

### L6. One mirror thread per message, no limit
`telegram_io.py:369-376` starts a new `threading.Thread` for every send. A burst of N alerts means N threads, each up to about 10 s per Slack call, on a 1 vCPU / 1 GB box. Together with M3 this means drops in `both` mode during bursts. **Fix:** one module-level `ThreadPoolExecutor(max_workers=2)` and `.submit(...)`.

### Info
- `slackselftest` is registered in the production action table (`connector.py:2498-2499`). It is harmless: a pure lambda that returns ok, checked by the AST test.
- Claim-before-dispatch burns the Slack card even when the action fails. That is fail-closed by design. Retrying needs a fresh card (or, until H1 is fixed, the Telegram twin).

---

## Answers to the specific questions
1. **Auth bypass:** none found. `authorized` denies by default: empty allowlist means nobody (`slack_io.py:411`), empty channel set means deny, and the channel must equal the card's channel (`:415`). Verified by reading and by tests.
2. **Wrong-channel or wrong-user tap:** refused, nothing runs, the card is not used up (`:480-488`). Tested.
3. **Replay or duplicate:** `_seen` checks envelope_id and trigger_id (`:418-424`), the listener has its own `_envelope_seen` (`:578-590`), and a persisted claim backs both up. Safe after a restart because the claim is on disk.
4. **TOCTOU on the claim:** none. `_claim` re-checks expiry and the used flag under `_LOCK`, then writes before dispatch, and fails closed on a write error (`:431-444`). The card's channel and action list never change after it is registered, so not re-checking them is fine. **Not proven by a concurrency test** (see test gaps).
5. **Edited button value:** refused unless `value` is in the card's own `actions` list (`:486`). Tested.
6. **Forged payloads:** today only from Socket Mode (`:640-641`). The assumption is recorded in L4.
7. **Mac-card owner rule parity:** the order matches Telegram (refused before the claim, so the card stays for the owner). The id namespace does not match, so it always refuses (L1).
8. **`origin_chat` misuse:** a Slack tap **cannot** confirm a token issued to a different Telegram chat. `origin_chat` and the token travel in the same send call into the same card record, and `telegram_agent.confirm` re-checks `p["chat"]` (`telegram_agent.py:326`). The one soft spot is the future `slack:<C>` card being placed in HQ (L2). That stays owner-only.
9. **State races:** fine inside one process. Across processes, see L3.
10. **Token or PII in logs:** log lines carry ids and error codes only (`:354`, `:481`, `:487`, `:535`, listener `_log`). The test run showed `slack down ***` (redaction works, verified). Mac output in the HQ channel is the real disclosure (M1).
11. **Env loader side effects:** M2.
12. **Mirror failure isolation:** good. In `both` mode the copy runs on a daemon thread after Telegram succeeds. If `slack_io` is broken, `_slack_mode()` falls back to `"telegram"`. Tested with a real hung thread (`test_slack_mirror.py:159-172`, under 1 s). The only cost is the thread count (L6).
13. **`slack` mode dropping messages silently:** yes (M3).
14. **Fail-open vs fail-closed:** every tap error path fails closed: unknown card, expired, write failure, Mac check raising, unknown action. The transport fails open toward Telegram when `slack_io` is broken. That is the right direction.
15. **HQ fallback leaking:** the same as Telegram for unbound businesses (into HQ, owner-only). Real cross-business cases: shared Telegram chats (L2) and `SLACK_ONLY_TEST` (M2).

## Task 1 diffs (verified by reading + tests pass)
- `marcus_engine.py:1215-1217`: the pop now happens right after the SMS call. Correct. **What is left (existing before this change):** if `ghl_post` raises after GHL accepted the message, the proposal survives and the reservation is released (`:1234-1240`). That is what makes H1 scenario A possible.
- `agency_dyson.py` `decision`: the status guard sits inside `_LOCK`, before the status is set. It closes reject→approve→ship. Correct.
- `daycare_ads_tg.py`: `_save` now returns a bool and `_claim` fails closed. `_too_old` runs after the claim and moves the card to "expired" (fail closed). A missing `createdAt` counts as too old. `createdAt` is in ms (`:75-77`), matching the check at `:589`. Correct.

## Test quality
Strong: the default-mode payloads are tested byte for byte, a real-thread test shows the mirror does not block Telegram, the failed claim write fails closed, an edited value is refused, an empty allowlist denies, and a garbage payload does not crash.
Weak or missing:
1. No test for cross-transport single use (H1). It cannot exist until H1 is built.
2. The Mac-rule tests stub `_foreign_mac_tap`, so the real "always refused" behaviour is untested (L1).
3. No concurrency test that sends two threads at `_claim` on the same card.
4. No test of the env-loader key filter or of `SLACK_ONLY_TEST` widening the tap channels (M2).
5. No test that a `slack`-mode failure shows up (lastError or a log line) (M3).
6. `test_send_to_agent_reply_is_mirrored` covers business routing but not owner-DM / Mac-output routing (M1).

## Positive observations
- Default-deny auth on three factors (user, allowed channel, issuing channel), plus the value-in-card check. Stricter than Telegram.
- The claim is written to disk before dispatch, under the lock, and fails closed. A restart cannot replay a tap.
- Flag-off is inert, and a test proves it (`test_mode_telegram_never_calls_slack`: not even a thread starts).
- Every new `slack_io` touchpoint in `telegram_io` sits in try/except. A broken `slack_io` falls back to Telegram.
- The listener acks before dispatch, routes only known envelope types, keeps the SDK logger at WARNING ("never a payload"), and only posts to `response_url` when it starts with `https://hooks.slack.com/` (an SSRF guard).
- The gateway child env is scrubbed and runs as `nobody` (`agent_gateway.py:525-558`), so Slack tokens loaded into the connector env do not leak to the agent child.

## Order to fix
1. H1 before `both` with outward taps (about 2-3 h including tests).
2. M1 and M2 (about 30 min each).
3. M3 before the `slack` flip (about 45 min).
4. The LOW items in one pass (about 1 h).
