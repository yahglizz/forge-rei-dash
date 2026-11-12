# n8n: FORGE Slack Agent Chat (Task 9 build, 2026-11-11)

Status: **created, INACTIVE, never published.** No other workflow changed. No Slack app setting changed. No live DM sent.

- Workflow id `IdaV0FLI0JFFCTMD`: https://atob.app.n8n.cloud/workflow/IdaV0FLI0JFFCTMD (personal project, no folder).
- Production webhook URL (Slack Trigger, webhookId `63b67164-ca43-4f84-8dd2-32a583e77609`):
  `https://atob.app.n8n.cloud/webhook/63b67164-ca43-4f84-8dd2-32a583e77609/webhook`
  Built from the node's webhookId plus the trigger's `path: 'webhook'` (n8n source). Live only after publish. Check it on the node in the editor before pasting it into Slack.

## Nodes (linear)
1. **Slack DM In**: slackTrigger v1, event `message`, watchWorkspace=true, cred `FORGE Slack Agents Bot` (Q1nyZgNL84eMJCxe). `options.userIds = [U0CH2JW4U5A]`. In n8n this option means "Usernames or IDs to **ignore**" (source verified), so the bot's own replies are dropped inside the trigger and start no execution. That they carry `user=U0CH2JW4U5A` is not verified; if they don't, node 2 drops them at 1 run each.
2. **Owner DM Only**: Filter v2.4, all of: `user == U0CGS6KHZ6X`, `channel_type == im`, `bot_id` empty, `subtype` empty.
3. **Build Agent Request**: Set v3.4. `route=chat`; `body.agent` and `body.message` use the same first-word regex as Parse Telegram (`^[\/@]?(marcus|scout|atlas|dyson|eco|solomon|orion)\b[:,]?\s*`, case-insensitive, default orion, empty becomes "Say hi and tell me what you can do from here."). Slack's `&amp; &lt; &gt;` are unescaped first. `body.sender_id = "8506156626"`, see below. `body.idempotency_key = "slack-" + event.ts`. The `slack-` prefix follows Telegram's `tg-` and keeps keys from colliding across surfaces; the gateway allows 8-200 chars. Also `channel` and `thread_ts` (= `thread_ts || ts`).
4. **Ask The Agent (Slack)**: Execute Workflow v1.4 → `FORGE Agent Dispatch` (XNvR287qpWUR6xPk), mode once, wait=true. Dispatch is unchanged.
5. **Format Slack Reply**: Set. `failed` → "That did not run: <error>"; else reply or "No answer came back."; `needs_approval` appends "Waiting on your tap in the business channel." Converts `**` to `*`, escapes `& < >` for Slack, and cuts at 3900 chars.
6. **Send Slack Reply**: Slack v2.7 message/post to `channel`, threaded on `thread_ts`, includeLinkToWorkflow=false, same cred.

## sender_id finding (mismatch, documented)
- Gateway `agent_gateway.validate_chat` returns 403 "sender is not the owner" unless `sender_id ∈ FORGE_GATEWAY_OWNER_IDS`. These are Telegram numeric ids, and a Slack `U…` id fails that check.
- Adding the Slack id to `FORGE_GATEWAY_OWNER_IDS` is **not** safe as-is. `telegram_agent._deliver_mac` sends Mac output by Telegram to every id in that set, so it would try to DM "U0CGS6KHZ6X". `test_mac_link.py` also assumes the env holds one id.
- **Chosen:** hard-code the owner's Telegram id `8506156626`. The live `FORGE Agent Chat` chat-page lane does exactly this. The gateway check only re-reads n8n's own claim, since n8n holds the owner key, so the real gate is the Filter (`user == U0CGS6KHZ6X`) plus Slack request signing.
- Gateway origin is `n8n`, so Mac auto-run is never offered on this path (`origin != "n8n"` rule).
- Live value of `FORGE_GATEWAY_OWNER_IDS` on the box was not read. It is assumed to contain 8506156626 because the Telegram trigger and chat page use it. Unverified.

## Signing secret (security, blocking for activation)
- n8n Slack Trigger answers `url_verification` without a secret, so it **works** without one.
- But `verifySignature` skips the check when the credential's `signatureSecret` is empty (n8n source, `skipIfNoExpectedSignature` → true). Without it, anyone who knows the URL can POST a fake event with `user=U0CGS6KHZ6X` and get an owner-trust agent turn. Internal AUTO writes run; outward actions stay taps.
- With it set: HMAC v0 over the raw body, timestamp window 300 s.
- **Rule: put App B's Signing Secret into the n8n credential `FORGE Slack Agents Bot` → "Signature Secret" before publishing.**

## Test results (manual pin-data runs; Dispatch and Slack post pinned, nothing external called)
| Exec | Input | Result |
|---|---|---|
| 1014 | owner DM "Solomon, how many tours … &amp; … &lt;new&gt;?" | PASS. Passed Filter. Request `agent=solomon`, message unescaped, sender 8506156626, key `slack-1762900000.000100`. Reached Ask The Agent → Format → Send. needs_approval suffix added; `**3**`→`*3*`; `& < >` escaped. |
| 1015 | bot echo (bot_id), non-owner DM, owner `message_changed` edit, owner in a public channel | PASS. All 4 went to the Filter's discard output; last node executed = Owner DM Only; Build/Ask/Send did not run. |
| 1016 | "what is on today" (no prefix) and "@Dyson:" in a thread | PASS. agent=orion; agent=dyson with the default message; thread_ts kept; failed → "That did not run: Gateway said 403". |
- `FORGE Agent Dispatch` executions since 23:00Z: **0** (checked). Box gateway not called. No Slack message posted.
- n8n execution ids used: 1014-1016, all mode `manual`. Whether manual runs count toward the 2,500 plan: Unknown. n8n Cloud normally counts production runs only; verify on the billing page.

## Budget
Each owner DM = 1 run of this workflow + 1 Dispatch sub-execution (whether sub-executions count is Unknown, see `04-n8n.md` §4). Non-owner and bot events that reach the Filter cost 1 run each. Bot echoes from U0CH2JW4U5A cost 0 if the ignore list matches.

## Activation steps (main thread, after the owner says go)
1. Slack App B (A0CH2JN94LC) → Basic Information → copy the Signing Secret → n8n credential `FORGE Slack Agents Bot` → paste into "Signature Secret" → save. Never print it.
2. App B → App Home → Messages Tab on, plus "Allow users to send … messages". Current state Unknown.
3. Publish workflow `IdaV0FLI0JFFCTMD` (publish_workflow or the editor toggle). This makes the URL live.
4. App B → Event Subscriptions → Enable → Request URL = the production URL above → must show "Verified" → Subscribe to bot events: `message.im` → Save → reinstall if prompted.
5. Owner DMs `forge_agents` "orion ping". Expect a threaded reply, 1 execution here + 1 Dispatch execution. Check that the bot's reply started no execution. Record counts.
Rollback: unpublish `IdaV0FLI0JFFCTMD`. The Telegram workflow is untouched throughout.

## Unknowns
- That bot replies carry `user=U0CH2JW4U5A`; confirm on the first live run.
- Whether Slack retries ever fire. The trigger is `responseMode: onReceived` (immediate 200), so retries are unlikely. A retry would make a 2nd execution; the same idempotency key gives the same gateway job, so expect a duplicate reply post, not a second agent run.
- The gateway prompt for origin `n8n` says the owner is "from Telegram or the n8n chat page" and cards go to "his business Telegram chat". The wording is off for Slack DMs. It is box-side, out of Task 9 scope.
- n8n instance version vs the n8n `master` source used for the signature/ignore-list facts.
