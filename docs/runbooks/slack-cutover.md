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

### Site channels (added 2026-11-12, reorganized the same day)

**Owner layout:** the main chat and the shared rooms are the overview (briefs only); the site channels are the specifics.

| Channel | Env key | Gets |
|---|---|---|
| `#forge-daycare` | `SLACK_CHANNEL_DAYCARE` | Per-site brief at 8 AM + 6 PM ET (921, 2318, AMT counts, no-site-tag warning), plus urgent / unprovable-site alerts |
| `#daycare-alerts` `-tours` `-quotes` `-starting` `-enrolled` | `SLACK_CHANNEL_DAYCARE_<TOPIC>` | All-sites brief for that topic at 8 AM + 6 PM ET. **No single events.** |
| `#daycare-921` (`C0CJ19VS2E4`) | `SLACK_CHANNEL_DAYCARE_ATOB_ONE` | ATOB 921 N 18th: new leads, parent replies, New Lead stage moves |
| `#921-tours` / `#921-quotes` / `#921-enrolled` | `SLACK_CHANNEL_DAYCARE_ATOB_ONE_TOURS` / `_QUOTES` / `_ENROLLED` | 921: tours + reminders / Application Sent / Enrolled + start dates |
| `#daycare-2318` (`C0CHAKJKBU4`) | `SLACK_CHANNEL_DAYCARE_ATOB_TWO` | ATOB 2318 Cecil B. Moore: same as 921 |
| `#2318-tours` / `#2318-quotes` / `#2318-enrolled` | `SLACK_CHANNEL_DAYCARE_ATOB_TWO_TOURS` / `_QUOTES` / `_ENROLLED` | 2318: same three |
| `#amt-1923` (`C0CGRH7KTEK`) | `SLACK_CHANNEL_DAYCARE_AMT` | A Mother's Touch (separate entity): alerts for families on the AMT board only |
| `#forge-knowledge` | `SLACK_CHANNEL_KNOWLEDGE` | Agents' knowledge base (`slack_knowledge.py`) |

- Site is proven from the boards, never from alert text (`slack_rooms.site_of` / `_card_site`): ATOB = room_ok passes and the family's ATOB card has exactly one ATOB `loc-` tag and no AMT mark; AMT = contact on the AMT board and not the ATOB one. A sub-channel that isn't bound falls back to its site channel; no provable site → `#forge-daycare` (alerts) or no line at all (stage moves; the brief counts them).
- AMT guard: a card with any `1923` `loc-` tag or `entity-amt` never enters an ATOB channel. Stage moves wait while the AMT board has never been read (fail closed), then post.
- `#amt-1923` and `#forge-knowledge` are NOT rooms: no Solomon chat, no taps there. Every ATOB site channel and sub-channel is a room (Solomon answers, ✅ cards tap).
- Rosters: `/forge roster` in any site channel or sub-channel lists that site (or that stage at that site); `/forge roster atob-one-tours` works from anywhere. Each site channel gets its roster once when first bound (`slack_rooms._seed`, waits until both boards were read).
- Briefs: `slack_briefs.tick()` runs after every pipeline read (`slack_rooms.on_refresh`), posts each slot once in the 4 hours after 8:00 / 18:00 ET. State `marcus_state/slack_briefs.json` (`done`, `snap`); delete a slot id from `done` to re-post it. Zero Claude, GHL or n8n calls.
- Create channels: `python3 forge-slack/bootstrap_channels.py --dry-run`, then without the flag (creates the 7 new private channels, sets every purpose, rewrites `slack-channels.env`). Copy the new `SLACK_CHANNEL_*` lines to the box `/opt/forge/forge-slack/config/slack-channels.env` and restart.
- Knowledge: `python3 forge-slack/seed_knowledge.py --dry-run` → read the preview → run without the flag. Agents read with `GET /api/knowledge?q=` and write with `POST /api/knowledge/post` (exception in `CLAUDE.md` §2). Needs bot scope `groups:history` (verified 2026-11-12).
- Center tags: `forge rei/daycare_center_tag.py` tags untagged ATOB families by their own form fields after every board read (kill `FORGE_DAYCARE_AUTO_CENTER=0`; state `marcus_state/daycare_center_tag.json`, delete a contact id from `checked` to re-check it now). One `🏷 Tagged …` line per tag in the site channel. Tap cards are one plain line; the route and arguments only show for routes with no template.
- Box ids: `/opt/forge/forge-slack/config/slack-channels.env` (backup `.bak-sites-20261112`).
- Owner sidebar sections (owner-level, set via the web client's `users.channelSections.*`): HQ · Daycare · all sites (#forge-daycare + 5 rooms) · Daycare · ATOB 921 · Daycare · ATOB 2318 · Daycare · AMT 1923 · Agency · Wholesale. No reorder API found; they sit under Agents, drag the block up if wanted. Add each new site channel to its site's section.

- Code: `forge rei/slack_rooms.py` (stage moves, rosters, seed, site_of, site_target), `forge rei/slack_briefs.py` (briefs), `forge rei/slack_knowledge.py` (knowledge), site routing in `slack_io.site_channel`. Zero Claude, GHL or n8n calls: it reads the box lanes' own state.
- **A Touch of Blessings only.** An alert enters an ATOB site channel only when a contact id in its dedupe key is on the ATOB board, the AMT board has been read and does not hold it, and the card proves the site. Anything else stays in `#forge-daycare`.
- A room is its business: talk to Solomon in any of them; ✅ cards tap there.
- Unbound site sub-channel = its posts fall back to the site channel; unbound site channel = alerts go to `#forge-daycare`, stage moves post nothing. Rebind inside the channel: `/forge bind daycare-atob-one-tours` (keys: `daycare-atob-one|atob-two[-tours|-quotes|-enrolled]`, `daycare-alerts|tours|quotes|starting|enrolled`).
- State: `marcus_state/slack_rooms.json` (`seeded`, `announced`). Delete `seeded` to re-post rosters; delete `announced` to re-snapshot (no posts).
- Commands: every Telegram command as `/forge <cmd>` or its own slash command (`forge-slack/slash-commands.yaml`, applied with `add_slash_commands.py` + a one-time App Configuration Token). Plus `/forge roster [room]`, `/forge menu` (buttons), `/forge chats`. `/roster` and `/menu` are not registered as their own commands yet.
- Buttons that never consume their card: `cmd:<command>` and `draft:<contactId>` (`slack_io.LIVE_ACTIONS`). Draft reply asks Solomon; any send still comes back as a ✅ card.
- Owner in Slack = `SLACK_OWNER_IDS` when set, else `SLACK_ALLOWED_USER_IDS`. Set `SLACK_OWNER_IDS` before allowlisting a teammate.
- Log lines: `[slack] slash /x verb=… channel=… owner=…`, `[slack] button …`, `[slack_rooms] on_refresh failed: …`.
