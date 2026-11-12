# Slack cutover runbook

Status as of 2026-11-11. Facts come from the migration fact sheet, verified 2026-11-11 unless noted.
The live box state is not re-checked by this document. Check it before acting.

## Current state

Slack runs beside Telegram. The box is set to `FORGE_SLACK=1` and `FORGE_CHAT_TRANSPORT=both`, and the soak started 2026-11-12 00:30 UTC. The env file is `/etc/default/forge-reios`. Its backup is `/etc/default/forge-reios.bak-slack-20261112002603`.

Telegram is still the default. The Telegram workflow "FORGE Agent Chat" (id `tEvB32PbQepvq9gl`) is untouched. The Slack workflow "FORGE Slack Agent Chat" (id `IdaV0FLI0JFFCTMD`) is published and calls the unchanged "FORGE Agent Dispatch" (`XNvR287qpWUR6xPk`).

## Soak checklist (3 days in `both`)

Run each item once a day. Mark each one pass or fail with the evidence.

1. `GET /api/health` on the box (dashboard on :7799, loopback or tailnet only) shows `slack.connected` true.
2. Alerts appear in the right channels: `#forge-hq`, `#forge-daycare`, `#forge-agency`, `#forge-wholesale`.
3. Tap one harmless card and one real card of each type. Each works once. The other app's buttons on that card disappear.
4. `/forge help` answers in HQ. A question in a business channel gets an answer from that business's agent.
5. An owner DM through n8n gets an answer.
6. Telegram still delivers, with the same alerts it sent before.
7. The n8n run count stays within budget. The limit is 2,500 runs a month. The 15-minute "ATOB Tour - Text Scans" workflow alone is about 1,470.
8. No `listener error` lines in the logs (grep list below).

Log lines to grep (use `journalctl -u forge-reios`, the service's journal):

- `[slack] listener connected` (expected at start)
- `[slack] listener error:` (must be absent)
- `listener off: slack_sdk not installed` (must be absent; box needs `slack_sdk==3.46.0`)
- `[slack] duplicate envelope` (expected occasionally; a rising count needs a look)
- `[slack] /forge REFUSED` (expected only for real refusals)
- `[slack] send failed:` (must be absent or rare)

## Cutover (owner's explicit go only)

Do not start this without the owner's yes. Each step changes a live system.

1. Confirm the soak checklist passed for 3 days and the owner said go.
2. Back up the env file, using the same pattern as the existing backup (`/etc/default/forge-reios.bak-slack-<timestamp>`).
3. Set `FORGE_CHAT_TRANSPORT=slack` in `/etc/default/forge-reios`.
4. Run `systemctl restart forge-reios`.
5. In n8n, deactivate (do not delete) the Telegram trigger in "FORGE Agent Chat" (`tEvB32PbQepvq9gl`).
6. Repeat the soak checklist items 1, 4 and 5 after the restart.

## Rollback

1. Set `FORGE_CHAT_TRANSPORT` back to `both` or `telegram` in `/etc/default/forge-reios`. Or restore the backup file.
2. Run `systemctl restart forge-reios`.
3. With `telegram`, Slack taps are refused with "Slack actions are paused". Telegram works as before.
4. If step 5 of cutover was done, reactivate the Telegram trigger in n8n. This step is the reverse of cutover step 5.

## Known caveats

- The box gateway accepts only the owner's Telegram numeric id as `sender_id`. The Slack workflow sends that id. The real gate is the owner-only DM filter in n8n plus the Slack signing secret.
- `FORGE_CHAT_TRANSPORT` and `SLACK_ONLY_TEST` must never go in a config file. The loader ignores them, and only the real environment counts.
- `#forge-hq` must stay owner-only, because Mac command output is copied there.
- Mac cards cannot be run from Slack. Only Telegram numeric ids in `FORGE_GATEWAY_OWNER_IDS` can run them.
- Not ported to Slack: `/task`, `/agents`, `/ace`, `/menu`, plain-English ops outside `/forge`, and the agent_gateway owner path.
- Before any deploy check from the AgentDrive checkout, run `git fetch origin main`. That checkout can be far behind. The live source is `~/forge rei dash`.

## Unknown or not verified here

- Whether the soak is running on the box right now. Check `/api/health` and the logs.
- Current n8n run count for this month. Check the n8n instance.

## Daycare rooms + commands (added 2026-11-12)

Rooms (private, owner-only, created by `forge-slack/bootstrap_channels.py`, ids in `slack-channels.env` as `SLACK_CHANNEL_DAYCARE_<TOPIC>`):

| Room | Gets |
|---|---|
| `#daycare-alerts` | new leads, parent replies that need the owner, families entering **New Lead** |
| `#daycare-tours` | tour reminders, families entering **Tour Scheduled** |
| `#daycare-quotes` | families entering **Application Sent** |
| `#daycare-starting` | start dates to confirm |
| `#daycare-enrolled` | families entering **Enrolled** |

### Site channels (added 2026-11-12)

| Channel | Id | Env key | Gets |
|---|---|---|---|
| `#daycare-921` | `C0CJ19VS2E4` | `SLACK_CHANNEL_DAYCARE_ATOB_ONE` | ATOB 921 N 18th: lead, parent-reply, tour-reminder, start-date alerts |
| `#daycare-2318` | `C0CHAKJKBU4` | `SLACK_CHANNEL_DAYCARE_ATOB_TWO` | ATOB 2 at 2318 Cecil B. Moore: same alerts |
| `#amt-1923` | `C0CGRH7KTEK` | `SLACK_CHANNEL_DAYCARE_AMT` | A Mother's Touch (separate entity): alerts for families on the AMT board only |

- Site is proven from the boards, never from alert text (`slack_rooms.site_of`): ATOB = room_ok passes and the family's ATOB card has exactly one ATOB `loc-` tag and no AMT mark; AMT = contact on the AMT board and not the ATOB one. Site wins over the topic room. Topic rooms keep stage moves, rosters and alerts with no provable site. Can't prove it → `#forge-daycare`.
- AMT guard: a card with any `1923` `loc-` tag or `entity-amt` (cards carry `centers` + `amt`) never enters an ATOB room, site channel or stage-move post.
- `#amt-1923` is NOT a room: no Solomon chat, no taps there (so no ATOB data can be pulled into it). `#daycare-921`/`#daycare-2318` are rooms (Solomon answers, ✅ cards tap).
- Box ids: `/opt/forge/forge-slack/config/slack-channels.env` (backup `.bak-sites-20261112`).
- Owner sidebar sections (owner-level, set via the web client's `users.channelSections.*`): HQ · Daycare · all sites (#forge-daycare + 5 rooms) · Daycare · ATOB 921 · Daycare · ATOB 2318 · Daycare · AMT 1923 · Agency · Wholesale. No reorder API found; they sit under Agents, drag the block up if wanted.

- Code: `forge rei/slack_rooms.py` (stage moves, rosters, seed, site_of), topic + site routing in `slack_io._deliver`. Zero Claude, GHL or n8n calls: it reads the box lanes' own state.
- **A Touch of Blessings only.** An alert enters a room only when a contact id in its dedupe key is on the ATOB board and the AMT board has been read and does not hold it. Anything else stays in `#forge-daycare`.
- A room is its business: talk to Solomon in any of them; ✅ cards tap there.
- Unbound room = its alerts fall back to `#forge-daycare`. Rebind: `/forge bind daycare-tours` inside the channel.
- State: `marcus_state/slack_rooms.json` (`seeded`, `announced`). Delete `seeded` to re-post rosters; delete `announced` to re-snapshot (no posts).
- Commands: every Telegram command as `/forge <cmd>` or its own slash command (`forge-slack/slash-commands.yaml`, applied with `add_slash_commands.py` + a one-time App Configuration Token). Plus `/forge roster [room]`, `/forge menu` (buttons), `/forge chats`. `/roster` and `/menu` are not registered as their own commands yet.
- Buttons that never consume their card: `cmd:<command>` and `draft:<contactId>` (`slack_io.LIVE_ACTIONS`). Draft reply asks Solomon; any send still comes back as a ✅ card.
- Owner in Slack = `SLACK_OWNER_IDS` when set, else `SLACK_ALLOWED_USER_IDS`. Set `SLACK_OWNER_IDS` before allowlisting a teammate.
- Log lines: `[slack] slash /x verb=… channel=… owner=…`, `[slack] button …`, `[slack_rooms] on_refresh failed: …`.
