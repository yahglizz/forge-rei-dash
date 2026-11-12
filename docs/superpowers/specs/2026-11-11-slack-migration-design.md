# Telegram → Slack migration — design

*Status: DRAFT for owner approval. Nothing is built from this until approved.*
*Date: 2026-11-11. Evidence: Haiku audit (`telegram-audit.md`, scratchpad), spot-checked in source by the main thread.*

## Intent (the why)
The owner wants to run the dashboard and the businesses from Slack with the agents, and move off Telegram.
**Same shape as Telegram today:** one chat per business plus an HQ chat; alerts and approval cards land
there; the owner taps to approve; agents answer in chat. Nothing about what agents may do changes.

## Goals
1. Every outbound alert/card Telegram sends today also arrives in the right Slack channel.
2. Every tap (Approve, Dismiss, Do it, Launch, Ship…) works from Slack and runs the **same** function as the Telegram tap.
3. Owner can talk to every agent from Slack (business channels, DMs, a `/forge` command), including the ops commands.
4. Telegram keeps working untouched until Slack passes the end-to-end test. Cutover and rollback are one flag.
5. n8n is brought along: the "FORGE Agent Chat" path works for Slack, Telegram trigger retired at cutover.
6. Tests for what the audit found uncovered (transport, tap auth).

## Non-goals
- No new agent powers, no new autonomy. Propose → review → execute stays (CLAUDE.md §2).
- No deleting Telegram code, bot tokens or chat bindings (rollback must stay possible).
- Dropship channel: skipped while the business is archived.
- No second human user. Allowlist = the owner only (`SLACK_ALLOWED_USER_IDS`).

## Anti-goals (a failure even if it "works")
- A tap that runs for someone not on the allowlist, or from a channel the card was not issued in.
- The same card acted on twice (once in Telegram, once in Slack) — double SMS, double ad launch, double deploy.
- Slack code running on the Mac (`FORGE_MARCUS` stays box-only), or a half-edit auto-deploying to the box.
- A token, signing secret or message body with customer data written to logs.
- Anything breaking while loops are running.

## Facts the design rests on
- Taps: `callback_data = "<action>:<arg>"` → `telegram_io._ACTIONS` registered in `connector.py:2376-2420`. 18 action types.
  **Outward:** `approve` (real SMS to seller), `opsgo` (GHL stage move / SMS), `dysongo` (client-site deploy),
  `pgo` (queued API write, e.g. daycare PIN reset), `adsapply/adsbuild/adslaunch` (Meta writes; `adslaunch` = $10/$20 per day real spend).
- Only `pgo`/`pno` are bound to the issuing chat (`telegram_io.py:713`). Others trust any authorized chat.
- Pending tokens expire: ops 1 h, partner 30 min, ad concepts 3 days. Ads-launch token lifetime: **Unknown, verify**.
- ~45 modules call `telegram_io.send / send_biz / send_photo` or register on the bus (`agent_bus.register_notifier`).
- n8n (live, verified via MCP): `FORGE Agent Chat` (active; Telegram owner DM + n8n chat page) → `FORGE Agent Dispatch`
  (active sub-workflow) → box agent gateway. n8n budget 2,500 runs/month (memory note).
- Slack side (verified 2026-11-11): bot token and app token valid; add/edit/react/delete passed in `#forge-test`;
  allowed user id valid. Channels today: `#social`, `#forge-test`, `#all-atouchofblessing`, `#new-channel`.

## The design (my calls — owner can overrule any)
**C1. Mirror at the transport, don't touch the 45 callers.** New `slack_io.py` with the same public surface as
`telegram_io` (send, send_biz, send_photo, run_forever). `telegram_io.send/send_biz/send_photo` get one small hook that
also calls `slack_io` when `FORGE_CHAT_TRANSPORT` is `both` or `slack`. Default `telegram` (= today, zero change).
Values: `telegram` | `both` | `slack`.

**C2. Taps reuse the same action table.** `_buttons_for` already yields (label, `action:arg`). `slack_io` renders those as
Block Kit buttons (`value = action:arg`) and, on click, calls the same `_ACTIONS[action]`. Same functions, same audit log (`action_log`).

**C3. Slack tap auth is stricter than Telegram's.** Every click must pass: user id ∈ `SLACK_ALLOWED_USER_IDS`
**and** channel ∈ {HQ, bound business channel} **and** (new, Slack only) the card's issuing channel == click channel.
Failing = ephemeral "Not authorized", nothing runs.

**C4. One live button per card.** When a card is mirrored to both transports, acting on either marks the card consumed on both
(edit the other message to "handled in Slack/Telegram"). Before shipping, verify every action is idempotent on a second
tap (approve pops the proposal; ops/partner tokens pop; **ads, dyson, opspause need checking**). If one is not, add a consumed-flag.

**C5. Receive via Socket Mode on the box** (outbound websocket, no public URL, matches "no inbound webhooks" in
`FORGE_CURRENT_ARCHITECTURE.md`). Dedupe on Slack `event_id` (Slack has no offset like Telegram). Ack inside 3 s, work on a thread.
Listener starts only where `FORGE_MARCUS=1`.

**C6. Channels.** `#forge-hq`, `#forge-daycare`, `#forge-agency`, `#forge-wholesale` (dropship later). Mapping stored in
`marcus_state/slack.json` (like `telegram.json`'s `bizChats`), set by an owner command `/forge bind <biz>` run in the channel.
Bot must be invited to each channel (private channels need it; public work via `chat:write.public` for sending only).

**C7. Inbound.** One slash command `/forge <anything>` (Slack has no runtime command menu) routes into
`telegram_ops.route` / `handle_agent_command` — the same router the dashboard chat uses. Plain text in a business
channel or the bot's DM goes to `telegram_agent` (the business-partner tool loop), same as Telegram groups/DMs.
Agent names work as prefixes ("solomon, …") like the n8n chat.

**C8. Formatting.** Telegram HTML → Slack mrkdwn (escape `& < >`). Long text split at ~3000 chars per block.
Photos (ads cards) → image block via file upload (`send_photo`).

**C9. n8n — mirror the Telegram split (owner decision 2026-11-01: "n8n as manager, DM through n8n").**
Two Slack apps, like the two Telegram bots: **App A "Forge"** (existing; Socket Mode on the box; channels, alerts, tap cards) and
**App B "Forge Agents"** (new; Events API → n8n webhook; owner DMs only). A Slack app cannot do Socket Mode and HTTP events at once,
which is the same reason Telegram needed two bots. In n8n, `FORGE Agent Chat` gets a Slack trigger (App B DMs) in place of the Telegram
trigger and still calls `FORGE Agent Dispatch`; the Telegram trigger is deactivated at cutover, not deleted. Cost: 1 n8n run per
DM (budget 2,500/month; owner-only DMs expected well under that). Business channels and taps bypass n8n, as today.
*Fallback if the owner prefers one app:* everything on the box via Socket Mode, zero n8n runs, n8n keeps only the chat page.

**C11. Box facts (verified in `deploy/setup_droplet.sh`, `ACCESS.md`).** 1 vCPU / 1 GB droplet; Python 3 + `requests` only; deploys push code,
no pip step. Socket Mode needs `slack_sdk` (pure-Python, its built-in client needs no extra websocket package — **verify**). One-time:
`pip3 install slack_sdk` on the box over SSH and copy the Slack env into the box's config. Both touch the live box → asked for at P2, not assumed.

**C12. Card registry.** New `marcus_state/slack_cards.json`: card id → channel, message `ts`, state. Survives restarts; powers C3 and C4.
A card goes to one Slack channel only (business channel, HQ fallback — same fallback as Telegram).

**C13. Parity of sending (my call).** The Slack hook sits inside `telegram_io.send*`, so it fires in exactly the same processes
Telegram does. Only the Socket Mode listener is box-only (`FORGE_MARCUS=1`).

**C10. Safety on the box.** Saving a file auto-deploys in ~60 s. So: new files first; edits to `telegram_io.py`/`connector.py`
land as one atomic small change each, flag default OFF, tests green before save.

## Phases
| # | Phase | Output | Gate |
|---|---|---|---|
| P0 | Slack keys + smoke test | **Done 2026-11-11** | add/edit/react/remove PASS |
| P1 | Outbound mirror (`slack_io.send*`, formatting, channel map, flag) | alerts in Slack, plain text, no buttons | stub-transport tests + 1 live alert per channel |
| P2 | Cards + taps (Block Kit, Socket Mode, C3/C4 auth, consumed-sync) | harmless taps work end to end | auth tests incl. wrong user/wrong channel/expired/double tap |
| P3 | Inbound (`/forge`, channel text, DMs, agent aliases) | talk to every agent | agent chat tests; `/forge` parity list vs Telegram command list |
| P4 | n8n (C9) | workflow updated, tested | test run through n8n, execution count noted |
| P5 | Parallel run, then cutover | `both` for the soak period, then `slack` | soak checklist all green; rollback = flag back |
| P6 | Docs | CLAUDE.md §2/§5, AGENTS.md, ARCHITECTURE, daily note | doc tests pass |

**Test rule:** tests and E2E use stub actions or harmless taps only. No real seller SMS, ad launch, deploy or PIN reset is ever
triggered to prove a button works; the real functions are proven by the existing Telegram tests plus a unit test that the Slack tap calls the same registered function.

## Who builds what (token saving)
- **Haiku** (`haiku-worker`): inventories, greps, parity lists, log reads, doc/status edits, test-run reports. Never writes to a live system.
- **Opus 5.5** (`opus-worker`): P2 tap auth/consumed-sync, P1 transport hook, security review.
- **Fable 5.2**: P3 inbound router and P5 cutover plan — the hardest cross-module work.
- **Sonnet** only for single-file test writing. Escalate to Opus after two Sonnet failures.
- Build-time agents may use Opus/Fable. The **runtime** agents stay on Haiku/Sonnet (`test_model_policy.py` unchanged).

## Left to the builder
Library choice for Socket Mode (`slack_sdk` if installed on the box, else stdlib websocket — check first); Block Kit layout of each card;
exact mrkdwn conversion; state-file shape for `slack.json`.

## Slack app setup still needed (owner clicks in the Slack admin UI, I open the pages)
Current bot scopes (verified): app_mentions:read, assistant:write, channels:history/read, chat:write(.public), groups:history/read,
im:history/read/write, reactions:read/write, users:read. App token + Socket Mode: works.
**Missing:** `commands`, `files:write`; (optional) `groups:write`, `channels:manage` if the bot should create channels.
**Also to switch on in App A:** Interactivity & Shortcuts; slash command `/forge`; Event Subscriptions → `message.channels`, `message.groups`, `message.im`, `app_mention`.
**App B "Forge Agents" — CREATED 2026-11-11** (app id `A0CH2JN94LC`, installed, bot `forge_agents` `U0CH2JW4U5A`, scopes chat:write, im:history/read/write, users:read, no event URL yet).
Token in `forge-slack/config/slack-agents.env` (gitignored, 600). n8n credentials made via API: `FORGE Slack Bot` (App A) and `FORGE Slack Agents Bot` (App B). Test workflow `FORGE Slack Test Ping` ran OK.
Still to do for App B: Event Subscriptions (`message.im`) pointed at the n8n Slack Trigger webhook URL, and its signing secret.

## Owner decisions (answered 2026-11-11 where marked)
- Shape = same as Telegram — **answered: yes**.
- **Answered 2026-11-11 (owner):** Slack becomes the manager instead of Telegram; **all** functions migrate; the box runs it 24/7 end to end;
  n8n is integrated with Slack (owner adds Slack credentials in n8n now so the build is not blocked). Reading: C9 two-app split stands (n8n = DMs, box = channels/taps).
  Final state = every Telegram function has a Slack equivalent live. Enabling order inside the soak is still a safety call (money taps last, each after its own test), not a scope cut.
- 1. n8n split (C9): two Slack apps, DMs via n8n (my default, matches your Nov 2 decision) or one app, all on the box?
- 2. During the soak (`both`), are the outward taps (`approve`, `opsgo`, `dysongo`, `pgo`, `adslaunch`/`adsapply`/`adsbuild`) live in Slack from day one, or Telegram-only until proven?
- 3. Channels private (recommended: cards hold seller/parent names, phones and ad spend) or public? Does anyone besides you read the Telegram business chats?
- Defaults I chose, not yet confirmed: 3-day soak in `both`; channel names `#forge-hq`, `#forge-daycare`, `#forge-agency`, `#forge-wholesale`; you create the channels, I bind them.
