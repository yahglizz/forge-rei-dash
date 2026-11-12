# Security review 2: Slack migration (listener, C4 claim, inbound, wiring)

Date 2026-11-11. Read-only review. No file edited except this one. No network, no sends, no .env or key files read.
Worktree `/Volumes/AgentDrive/claude/forge-slack-wt`, branch `slack-migration`, base `origin/main` 8817e80 (uncommitted working tree reviewed).

**Bottom line:** no CRITICAL, no HIGH. The review-1 HIGH (C4, one live button per card) is fixed correctly for normal `both` mode, and I verified that by reading the code, running the tests, mutation-testing them and running my own proof-of-concept scripts. Two MEDIUM and five LOW remain. Fix the first MEDIUM before any rollback drill that leaves `FORGE_SLACK=1` on. Fix the second before binding real channels.

## What I read
- `forge rei/slack_io.py`: the whole file (856 lines).
- `forge rei/slack_inbound.py`: the whole file (238 lines).
- `forge rei/telegram_io.py`: `git diff origin/main`, plus 740-870 (`_handle_callback`) and 880-1390 (agent chat, for parity).
- `forge rei/connector.py`: the diff (api_health 507-512, `slackselftest` 2504-2505, startup 6344-6352), plus `do_GET` 5912-5951 (access gate).
- `forge rei/telegram_agent.py` 50-520 and 600-875 (SCOPE/DENY, `confirm`, Mac cards, `chat`, `quick`).
- `forge rei/telegram_ops.py` 335-465 and 640-824 (what `/forge <ops>` can do).
- slack_sdk 3.46.0 builtin client source (`/Volumes/AgentDrive/claude/_tmp/slackvenv`), to check what it logs at WARNING and above.
- Tests: `test_slack_claim.py`, `test_slack_listener.py` and `test_slack_inbound.py` in full.

## Tests (verified: I ran them)
- `FORGE_MARCUS=0 python3 -m unittest test_slack_claim test_slack_listener test_slack_inbound test_slack_taps test_slack_mirror test_tap_idempotency` gave **58 tests OK** in 2.5 s. HTTP(S)_PROXY was pointed at a dead port, so nothing could have reached the network.
- **Mutation check.** I patched each guard out at runtime (no file edits) and re-ran the suite to see whether the tests notice. All five mutations were caught:

| Guard removed | Tests that failed |
|---|---|
| `_slack_claim` always returns "free" | 6 of 11 |
| `_read_strict` swapped for the lenient `_read` | 1 of 11 |
| `_owner` accepts any user | 2 of 12 |
| `_drop_tg_buttons` turned into a no-op | 2 of 11 |
| `_envelope_seen` turned off | 3 of 11 |

  The tests are real. I found no assertion that cannot fail.
- **Gaps.** Nothing tests the rollback case (M1), the 7-day prune (L1), the agent-pick race (L3), or the `response_url` guard (`_respond` is stubbed at `test_slack_listener.py:166`). I checked the guard by hand and it is correct (see Info).

## Proof-of-concept results
Script: `/Volumes/AgentDrive/claude/_tmp/claude-501/-Volumes-AgentDrive-claude-forge-rei-dash/af6115d7-f8f7-4e6f-90ed-2ad6f9d6bf59/scratchpad/poc.py`. It uses the same fakes as the tests and makes no network calls. Results, all verified:
- A (rollback): `runs = 2`. The same approval ran twice (M1).
- B (prune after 8 days): `runs = 2` (L1).
- C (corrupt registry): Telegram calls were `answerCallbackQuery, editMessageReplyMarkup`. The refused card lost its buttons (L2).

---

## MEDIUM

### M1. The C4 claim is skipped in `telegram` mode, but the Slack listener still runs taps. A rollback reopens double-runs.
- **Where:** `telegram_io.py:804` only calls the claim when `_slack_mode() != "telegram"`. `slack_io.py:310` also returns "free" in `telegram` mode. `slack_io._interaction` (`slack_io.py:597-668`) never checks the mode. The listener starts on `FORGE_SLACK=1`, which is separate from `FORGE_CHAT_TRANSPORT` (`connector.py:6346`). The runbook itself runs `FORGE_SLACK=1` with the transport set to `telegram` (`slack_io.py:681`).
- **Scenario (verified, PoC A):**
  1. The box runs a day in `both` mode. Seller-SMS approve cards are mirrored, and each Slack copy stays live for 7 days.
  2. The owner rolls back to `FORGE_CHAT_TRANSPORT=telegram` and leaves `FORGE_SLACK=1` on.
  3. The owner taps Approve in Telegram. No claim is made and the action runs.
  4. Later the owner taps the Slack copy. Its card is not consumed, so the action runs again.
  
  The reverse order (Slack first, then Telegram) also double-runs if `_drop_tg_buttons` failed. Whether the second run actually sends a second SMS depends on each action's own idempotency (refs/02). `handoff` and `dysonplan` are not idempotent.
- **Minimal fix (about 30 min):**
  1. In `_interaction`, after `get_card`: if `mode() == "telegram"` and `card.get("tg_chat_id")`, refuse with "Slack copies are off. Tap it in Telegram." This makes Telegram the only live button for mirrored cards during a rollback.
  2. Run the claim in every mode, so cards consumed in Slack before the rollback stay refused in Telegram:
     - In `claim_for_telegram`, replace the `mode() == "telegram"` short-circuit with "registry file missing → free". In `telegram` mode, do the lookup but do not write tombstones.
     - In `telegram_io.py:804`, drop the `_slack_mode() != "telegram"` condition.
     - Update `test_unmirrored_telegram_tap_unchanged_free`: in `telegram` mode with no registry file, the result is "free" and no file is written.
  3. Add a test: `test_rollback_to_telegram_mode_keeps_single_use`.

### M2. `/forge bind` accepts any channel. "HQ is owner-only" is assumed, not enforced.
- **Where:** `slack_inbound.py:101-111` checks only that the channel id starts with `C` or `G`. `slack_io.bind` (`slack_io.py:175-186`) checks only the id format. The `slack_io` docstring (`:25-26`) says #forge-hq must stay private and owner-only, because Mac command output and owner DM replies are mirrored there.
- **Scenario:** the owner runs `/forge bind hq` (or `bind daycare`) in a public channel, a group DM (an `mpim` id starts with `G`), or a Slack Connect channel. From then on, every card, every alert with seller or parent phone numbers, ad spend, and in `both`/`slack` mode the full Mac command output (which can hold env values) is posted where other people can read it. Taps stay owner-only, so this is a disclosure, not a takeover. The owner has to trigger it, so it is MEDIUM, not HIGH. The same gap was flagged in review 1 L2 ("Task 6 must accept private channels only"). It is still open.
- **Also:** one channel can be bound to two businesses. `business_of` returns the first match (wholesale wins), so daycare alerts would land in a channel whose plain-text messages go to Marcus.
- **Minimal fix (about 30 min):**
  1. Before `slack_io.bind`, call `conversations.info`. Refuse unless `is_private` is true, `is_mpim` is false, `is_ext_shared` is false and `is_shared` is false.
  2. For `hq`, also call `conversations.members` and require the members to be exactly {the allowed users} plus the bot.
  3. Refuse a channel that is already bound to another key.
  4. Tests: bind refused for a public channel, an mpim, a shared channel and a duplicate.

---

## LOW

### L1. The 7-day prune can reopen a Telegram twin that was already used in Slack
- **Where:** `slack_io.py:275-276` (7-day TTL) and `:286-287` (500-card cap), both applied in `register_card`.
- **Scenario (verified, PoC B):**
  1. A Slack tap consumes the card. `_drop_tg_buttons` fails (network, Bot API error), so the Telegram buttons stay.
  2. After 7 days, or sooner if 500 cards come through, any new card's `register_card` prunes the consumed record.
  3. A Telegram tap now finds no twin. It writes a tombstone, returns "free" and runs the action again.
  
  Telegram buttons never expire, so the protection lasts only 7 days.
- **Fix (about 15 min):**
  1. Keep `consumed and tg_chat_id` records for 90 days. They are small.
  2. When trimming to `_CARD_MAX`, drop tombstones and unconsumed Slack-only cards first.
  3. Make the "telegram twin edit failed" log line include card id and chat id, so the owner can clear the buttons by hand.

### L2. A transient registry read error removes the Telegram buttons for good
- **Where:** `telegram_io.py:804-814` treats every "taken" the same way. `claim_for_telegram` returns "taken" for any exception (`slack_io.py:327-329`), including a corrupt file or an I/O error.
- **Scenario (verified, PoC C):** `slack_cards.json` cannot be read for a moment. The owner taps Approve. The tap is correctly refused, but the Telegram card also loses its buttons, with the text "Already handled in Slack", which is not true. The approval is gone, and the owner has to ask the agent again. Refusing (fail closed) is right; deleting the buttons is not.
- **Fix:** return a third value, "error". On "error", answer "Couldn't check the Slack copy. Try again." and keep the keyboard. Drop the keyboard only on a real "taken".

### L3. Agent-pick race between listener workers: a business channel can briefly run another business's agent
- **Where:** `slack_inbound.py:176-202`. `sess["agent"]` is shared per chat and changed with no lock. `_turn` takes the chat lock only after the agent is chosen.
- **Scenario (reasoned, not run):** the owner sends two messages in #daycare within a few milliseconds, "marcus, x" and "how many tours". Thread A sets `sess["agent"] = "marcus"` (`:182`). Thread B already passed its scope check (`:177`), then reads `sess["agent"]` at `:202` and gets Marcus. Thread A then refuses and resets, but B already runs `_turn("marcus")` in the daycare channel. Marcus has wholesale write scope, so he can queue wholesale POST cards there. Each card still needs a tap. This race is new: Telegram handles messages on one poll thread, one at a time.
- **Fix:** choose the agent into a local variable and never read `sess["agent"]` back after the scope check (pass the local to `_turn`). Or hold `_CHAT_LOCKS[chat]` around the whole of `_handle_text`.

### L4. Pool starvation: long agent turns can hold up approval taps for minutes
- **Where:** `slack_io.py:820` (one pool, `max_workers=4`, unbounded queue) and `slack_inbound.py:209` (`_turn` runs the whole Claude tool loop inline, and the same chat blocks on `_CHAT_LOCKS` while holding a worker).
- **Scenario:** the owner sends 4 quick messages in one channel. One worker runs the turn, which can take minutes, and three sit blocked on the chat lock. Every button tap and `/forge` command queues behind them. The envelope was already acked, so Slack shows no error and nothing happens. Only the owner can trigger this: non-owner events return immediately. It affects availability, not security.
- **Fix:**
  1. Give taps (`interactive`) their own executor, or run agent turns on a separate bounded executor (max 2).
  2. In `_turn`, use `lock.acquire(blocking=False)`. If the lock is busy, reply "Still on your last message" instead of parking a worker.

### L5. Review-1 LOW items still open (re-checked)
- **Redaction regex:** `slack_io.py:109` and `telegram_io.py:208` still miss `xoxe.` refresh tokens and tokens that contain dots. `telegram_io._redact` still does not mask `SLACK_SIGNING_SECRET`.
- **L3 (state files):** `slack_io.py:57` and `:163-171`: `STATE` has no `forge_atomic.guard_state_path`, the tmp file name is fixed, and files use the default umask.
- **L4 (identity fields):** `handle_interaction` still does not check `api_app_id` or `team.id`. It is only documented in the docstring (`:585-588`). That is still safe today, because the only caller is the Socket Mode client.
- **L1 (Mac cards from Slack):** still always refused (fail closed, which is fine). `_foreign_mac_tap` checks Telegram owner ids against a Slack `U…` id.

---

## Info (no action needed, or optional)
- **response_url (SSRF):** the guard is correct. `_respond` posts only when the URL starts with `https://hooks.slack.com/`, with the trailing slash. I tested `/@evil.com`, `/#@evil.com`, `/..%2f@evil.com` and a backslash variant. urllib3 parses the host as `hooks.slack.com` in every case (verified). The payload comes from the authenticated socket anyway. The guard has no test (it is stubbed). Add one.
- **Malformed envelopes:** handled. A non-dict payload returns. An unknown type is acked and logged with its type only. A non-`block_actions` interaction is ignored. A non-dict `event` becomes `{}`. Every path is inside try/except and logs only the exception type.
- **Ack-first ordering:** correct. Each envelope is acked on the receiving thread, then deduped on envelope_id, event_id and trigger_id (10 min, 500-entry ring), then submitted. Slack retries arrive with a new envelope id but the same event id and are caught (tested).
- **Reconnect and stop:** each connection gets a new client, the backoff runs from 1 to 60 s and resets after 60 s of stable connection, and `close()` is called in `finally`. A stop event ends the loop (tested). `pool.shutdown(wait=False)` drops any queued work, and a dropped tap was never claimed, so the owner can tap again.
- **Logging:** our own lines carry ids, types and error codes only (tested with a body and a token). At WARNING level the SDK can print a frame payload in one case ("unsupported data frame", `connection.py:402-406`), which Slack does not send. Optional: set the `forge.slack.socket` logger to ERROR.
- **`status()` in `/api/health`:** it returns `connected`, `last_error` (redacted, an error code or exception text) and `started_at`. No secret was found. GET `/api/*` sits behind `_dashboard_client_allowed` (`connector.py:5913`). Nit: `last_error` is shared by sender failures and the listener, and a reconnect clears earlier send errors.
- **Env loader allowlist:** correct and tested. A child-process test proves `FORGE_CHAT_TRANSPORT`, `SLACK_ONLY_TEST` and `FORGE_SLACK` in `slack.env` are ignored. `forge-slack/config/slack.env` and `slack-channels.env` are covered by `.gitignore` `*.env` (verified with `git check-ignore`).
- **"claimed" from Telegram:** the Slack copy keeps its buttons on screen (no `chat.update`). Tapping one gets "Already handled." Cosmetic only.
- **Posts as the owner's Slack user:** any integration that posts with the owner's user token (n8n with user OAuth, a Claude Slack connector) passes `_owner`. If its posts carry no `bot_id`, they drive the agents. Unknown whether such posts always carry `bot_id` or `app_id`; check one live event. It cannot tap (`block_actions` cannot be sent through the API), so the worst case is unwanted agent turns (cost) and cards the owner must still approve.
- **n8n-owned agent-bot DM taps:** they never reach `_handle_callback` on the box. Unknown whether any of those DM cards are ever mirrored. If n8n sends them directly, they are not, and C4 does not apply to them.

---

## Answers to the review questions

1. **Listener block (`slack_io.py:671-856`).** No exploitable issue. Ack-first is correct, dedupe is correct, malformed input is safe, the reconnect loop is bounded, stop works, logs are clean and the `response_url` guard is correct. One availability issue: pool starvation (L4).
2. **Claim, tombstones, registry, `_drop_tg_buttons`.**
   - **Races:** none inside one process. Every read-modify-write of `slack_cards.json` (Telegram claim, Slack `_claim`, `register_card`) runs under `_LOCK`. The 25-round barrier test proves exactly one run per card.
   - **Two processes:** not safe. `_LOCK` is a threading lock. Today this is fine: the box runs one connector, and both Telegram poll loops (`telegram_io.py:1449`, `:1527`) and the listener live in it. Keep the docstring rule.
   - **Corrupt registry:** fails closed, but destroys the card (L2).
   - **7-day pruning:** reopens Telegram twins (L1).
   - **Fail-closed or fail-open:** closed in `both` mode. Open on rollback (M1).
   - **Tombstones cannot be tapped:** `get_card` hides them, so `_claim` is never reached for one (verified).
3. **`slack_inbound`.**
   - **Owner check:** allowlist only, applied to slash commands and messages. Empty means nobody.
   - **Business-scope bypass:** none by alias, trigger word or name. Business channels refuse any agent from another business and Orion, and are stricter than Telegram. A business channel cannot reach HQ or another agent except through the L3 race.
   - **Bind:** owner-only (verified in code and tests). The owner can bind an unsafe channel (M2).
   - **Prompt injection:** Slack text reaches only `telegram_agent.chat`. That allows immediate reads (DENY-filtered) and writes only as ✅ cards, re-checked against scope and deny at tap time. There is no gateway or AUTO path and no Mac-card creation. Model output is HTML-escaped before mrkdwn, so it cannot create links or `<!channel>` pings.
   - **DM card into HQ:** the card is bound to `slack:<D…>` and confirmed with that same string (tested).
   - **Locks and threads:** `_CHAT_LOCKS` grows by one per channel (bounded). No thread leak. `_turn` restores the thread name.
   - **Other `/forge` commands:** `/forge autopilot on`, `pause` and `resume`, and `tag` run without a card. That is the same as Telegram (operator switches and internal tags) and is owner-only.
4. **`telegram_io` claim hunk.** It is placed correctly: after auth and the Mac-owner check, before dispatch. It fails closed when `_slack_claim` raises. The issues are the mode gate (M1) and dropping the buttons on errors (L2).
5. **`connector.py`.** The listener starts only under `LOOPS_ENABLED` and `FORGE_SLACK != "0"`, inside try/except, on a daemon thread (verified by the AST test). There is no import at module level. `status()` leaks nothing sensitive.
6. **Env loader.** The allowlist is correct and tested (review-1 M2 closed).
7. **Tests.** 58 pass, and the mutations show they are real. Missing tests: rollback mode, prune, the race, bind refusals and `response_url`.

## Positive observations
- The C4 fix is keyed on the Telegram message (chat id plus message id), never on callback_data. A test shows two cards with the same `opspause` value stay independent.
- Tombstones correctly handle the case where the Telegram tap lands before the Slack copy is registered. The late copy is created already used and its buttons are removed.
- Default-deny holds everywhere: empty allowlist, unknown channel, wrong card channel, a value not in the card, an expired or tombstoned card.
- Ack-first plus a pool means Slack never redelivers a slow tap, and a tap is never claimed until it actually runs.
- The env allowlist closes review-1 M2, with a clean child-process test.
- Business channels are stricter than Telegram: they refuse Orion and any other business's agent.
- Logs and errors carry types and ids only, checked against a real body and real-looking tokens.

## Order to fix
1. M1 before any rollback that leaves `FORGE_SLACK=1` on (about 30 min including the test).
2. M2 before running `/forge bind` on real channels (about 30 min).
3. L1 and L2 together, since both touch the claim (about 30 min).
4. L3 and L4 before heavy daily Slack chat use (about 45 min).
5. The L5 carry-overs in one pass (about 30 min).
