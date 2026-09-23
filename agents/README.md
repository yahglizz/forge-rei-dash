# FORGE — Agents

One card per agent/worker, filed by business. Every card has the same 9 sections:
Identity · Triggers · Reads · Outputs · Autonomy & gates · Self-improvement · Chat & tasks ·
Cost · Verify it's alive. Code refs are relative to `forge rei/`. Last verified against code
2026-09-22.

**These cards are documentation, not behavior.** Editing one changes nothing at runtime. What
agents actually load: creed (`forge-*/skills/<business>-evidence-discipline.md`, human-only,
invisible to `learn()`) → top skills (human-only) → learned playbook (vault
`Skills/<agent>-playbook.md`, rewritten by `learn()`). See `CLAUDE.md` §4a.

## Index

Roster = `agents_hub.AGENTS` (12 rows, the Agent Control Center). Workers marked † are real
triggers in the code but not roster agents.

| Agent | Business | Card | Engine | Scheduled trigger | Telegram | Hub id | Autonomy |
|---|---|---|---|---|---|---|---|
| Scout | Wholesale | [scout](wholesale/scout.md) | `forge rei/scout_triage.py` | thread `scout`, 180 s | `/scout`, `scout, …` | `scout` | HOT auto-tag + auto-stage; else proposals; never texts |
| Marcus | Wholesale | [marcus](wholesale/marcus.md) | `forge rei/marcus_screening.py` + `forge rei/marcus_engine.py` | event (Scout `on_scored`); legacy `marcus` loop off | `/marcus` (default), `marcus, …` | `marcus` | every seller SMS is a tap; never a price |
| Atlas | Wholesale | [atlas](wholesale/atlas.md) | `forge rei/deal_prep.py` | thread `atlas`, 900 s | `/atlas`, `atlas, …`, `/prep` | `atlas` | internal only |
| Follow-up | Wholesale | [followup](wholesale/followup.md) | `forge rei/followup.py` | thread `followup`, 1800 s | — (`/checkback`) | `followup` → Marcus | drafts only |
| ACE | Wholesale | [ace](wholesale/ace.md) | `forge rei/ace.py` + `forge rei/conversation_engine.py` | event (after each screen) | `/ace [mode]` | `ace` → Marcus | off by default; supervised/full auto-send |
| Autopilot | Wholesale | [autopilot](wholesale/autopilot.md) | `forge rei/autopilot.py` | rides the `followup` thread | `/autopilot on\|off` | `autopilot` → Marcus | off by default; auto-sends bumps |
| Dyson | Agency | [dyson](agency/dyson.md) | `forge rei/agency_agents.py` + `forge rei/agency_dyson.py` | none (on-demand) | `/dyson`, `dyson, …` | `dyson` | ships only on approval |
| Eco | Agency | [eco](agency/eco.md) | `forge rei/agency_agents.py` + `forge rei/agency_eco.py` | none (on-demand) | `/eco`, `eco, …` | `eco` | PAUSED ads only on approval |
| Solomon | Daycare | [solomon](daycare/solomon.md) | `forge rei/daycare_director.py` | thread `solomon`, 900 s tick, brief 24 h | `/solomon`, `solomon, …` | `solomon` | read + propose only |
| Lead Desk † | Daycare | [lead-desk](daycare/lead-desk.md) | `forge rei/daycare_leads.py` | thread `daycare_leads`, 900 s | outbound only | — | GET-only, $0 |
| Midas | Dropship (archived) | [midas](dropship/midas.md) | `forge rei/dropship_director.py` | thread `midas` — **off** (`FORGE_DROPSHIP_BRIEF=0`) | `/midas`, `midas, …` | `midas` | read + propose only |
| Orion | Cross | [orion](cross-business/orion.md) | `forge rei/mission_control_agent.py` | `brief` thread, daily 07:00 | **none** | `orion` | read + propose only |
| Daily brief | System | [daily-brief](cross-business/daily-brief.md) | `forge rei/daily_brief.py` | `brief` thread, 08:00 | outbound only | `briefs` → Orion | operator Telegram only, $0 |
| Daily recap | System | [daily-recap](cross-business/daily-recap.md) | `forge rei/daily_recap.py` | `brief` thread, 18:00 | outbound only | `briefs` → Orion | operator Telegram only, $0 |
| skill_forge † | Cross | [skill-forge](cross-business/skill-forge.md) | `forge rei/skill_forge.py` | bus notifier | taps `skillgo`/`skillno` | — | proposes skills |
| style_agent † | Wholesale voice | [style-agent](cross-business/style-agent.md) | `forge rei/style_agent.py` | systemd 20:00 ET | — | — | internal |
| review_agent † | Wholesale playbook | [review-agent](cross-business/review-agent.md) | `forge rei/review_agent.py` | systemd Mon 08:00 + 20:00 ET | — | — | internal |

`briefs` is the single roster row for both pulses — [briefs](cross-business/briefs.md).
`→ X` = `chatVia`: that agent has no brain; X answers in chat and sees its tasks.

Not documented as agents (no brain, no agent role): `do_today` (thread `do_today`, off via
`FORGE_TODAY_LOOP=0`), `graphify` (knowledge-graph rebuild), contract poller, watchdog,
`telegram` / `telegram_agent` poll loops, `sync_monitor` (runs inside the `brief` thread).

## How triggering works

### 1. Scheduled loops — `connector.main()` (`connector.py:5060`)

- Every loop starts only when `FORGE_MARCUS` != `0` (`LOOPS_ENABLED`, `connector.py:45`). The box
  runs them; a UI-only Mac sets `FORGE_MARCUS=0`. With it off, no thread starts and nothing is retired.
- Each loop names its thread; that name is also its cost bucket (`cost_tracker.AGENT_THREADS`).
- A loop switched off by its own knob must call `forge_heartbeat.retire("<loop>")`. Only
  `daycare_leads`, `midas`, `do_today` do (`connector.py:5113/5134/5147`).
- Most loops also stand down on clock-out (`forge_ops.paused()`); exceptions are in each card.

| Thread | Knob (default) | Heartbeat |
|---|---|---|
| `scout` | `FORGE_SCOUT_INTERVAL` (180) | `scout` |
| `marcus` | `FORGE_MARCUS_SMS` (**0 = off**) | `marcus_sms` |
| `followup` | `FORGE_FOLLOWUP_INTERVAL` (1800) | `followup` |
| `atlas` | hardcoded 900; `FORGE_PREP_AUTO` (1) | `atlas` |
| `solomon` | hardcoded 900 tick; `FORGE_SOLOMON_BRIEF_EVERY_H` (24) | `solomon` |
| `daycare_leads` | `FORGE_DAYCARE_LEADS` (1), `FORGE_DAYCARE_LEADS_INTERVAL` (900) | `daycare_leads` |
| `midas` | `FORGE_DROPSHIP_BRIEF` (**0 = off**) | `midas` (retired) |
| `do_today` | `FORGE_TODAY_LOOP` (**0 = off**) | `do_today` (retired) |
| `brief` | `FORGE_BRIEF_CHECK_SEC` (300): daily brief, recap, Orion, sync monitor | `daily_brief` |
| `telegram` / `telegram_agent` | long-poll | `telegram` / `telegram_agent` |
| `graphify` | 30 min | `graphify` |

Outside the process (systemd heredocs in `deploy/setup_droplet.sh`): `forge-daily-learn.timer`
20:00 America/New_York → `deploy/daily_learn.sh` → POST learn for scout, screening, style,
review (days=1), dyson, eco · `forge-review.timer` Mon 08:00 → `/api/review/run {"days":7}`.

### 2. Event triggers (no loop)

| Event | Fires |
|---|---|
| Scout scores asap/warm | `SCOUT.on_scored = _auto_screen` (`connector.py:1254`) → Marcus screen → ACE update (unnamed thread). Gate `FORGE_SCREEN_AUTO` (1) |
| POST `/api/screening/run` | Marcus screen → ACE update (HTTP thread, not `FORGE_MARCUS`-gated) |
| Follow-up drafts a bump | `autopilot.maybe_send` |
| Any bus message | notifiers `telegram_io.on_bus_message` (`connector.py:1236`) + `skill_forge.on_bus_message` (`:2198`) |

### 3. Telegram routing — exact precedence (`telegram_io._handle_message`, `telegram_io.py:810`)

0. Auth: sender id must be `TELEGRAM_CHAT_ID` or in `TELEGRAM_ALLOWED_IDS` (`_msg_authorized`, `:777`). Button taps use the two-factor `_authorized(from_id, chat_id)` (`:92`).
1. Quick-tap keyboard labels → mapped to their command (`_KEYBOARD_MAP`).
2. `/start` `/help` · `/menu` · `/menu off` · `/whoami` · `/agents`.
3. `/ace` or `/ace <mode>` (`:856`).
4. **Ops router** `telegram_ops.route` (`telegram_ops.py:793`):
   - strips a leading `/marcus ` `/scout ` `/atlas ` and checks the rest;
   - ops slash commands (`_CMD_RE`, `:742`): `/today /done /hot /sweep /screen /find /text /send /checkback /proposals /report /directives /orders /ops /autopilot /prep /pause /resume /clockin /clockout /clock` → consumed;
   - any other `/…` falls through;
   - **plain text → `_command_intent`** = regex `_rule_intent`, then a Claude `_intent` classifier (`:774`). If it maps to an action (text a seller, screen, sweep…), it is consumed. Anything classed as chat falls through.
5. Agent slash alias `/scout /marcus /atlas /dyson /eco /solomon /midas` → switches the chat's active agent (`_AGENT_ALIASES`, `:670`).
6. Name trigger (`_AGENT_TRIGGER`, `:679`): the name as FIRST word followed by `,` or `:` (spaces optional) or a spaced dash `—`/`–`/`-` — or the bare name alone. "I told marcus to call" does not trigger.
7. `/task <title>` → files for the **active** agent (default `marcus`). Non-agency → `agents_hub.send_task` + answered in chat; Dyson/Eco → `agency_agents.send_task` (Agency board only).
8. Anything else → chat with the active agent (in-memory session per chat id; history from `agents_history`).

Chat backends: Scout/Marcus/Atlas → `agents_chat.chat` (commands off); Solomon/Midas →
`agents_hub.chat`; Dyson/Eco → `agency_agents.chat` (`connector.py:2324-2369`). Orion,
Follow-up, ACE, Autopilot and the briefs are **not** reachable as Telegram chat agents.

### 4. Dashboard / HTTP

- Every GET/POST: peer IP in `FORGE_ALLOWED_CLIENT_CIDRS`, Host allowlist; POST also same-origin
  (a request with no `Origin` passes) — `connector.py:3240`, `4859`. `/api/daycare/*` also needs a
  daycare session. No other route has per-user auth.
- `/api/hub/chat {agentId}` → `agents_hub._chat` (`agents_hub.py:410`): `chatVia` delegate → owner's
  brain with live state (commands off) · agency → `agency_agents.chat` · daycare/dropship/cross →
  `_director_chat` · wholesale → `agents_chat.chat` (commands on: tags run, stage moves need a confirm).
- `/api/hub/task` → `agents_hub.send_task`: `marcus_state/hub_tasks.json` + bus `task` message
  (+ agency board for Dyson/Eco).
- `/api/office/task` (Agent Office) → `send_task` + a background `agents_hub.chat` run. The floor has
  7 characters: marcus, scout, atlas, dyson, eco, solomon, midas (`pixel_office.py:37`).
- Agent Control Center: `/api/agents/registry` (`agents_hub.registry`).

### 5. Bus roles and tasks

- `agent_bus.inbox(name)` returns messages to `name` **or `all`**. Only two agents read the bus:
  Solomon (`BUS_ROLES` = solomon, family-comms, enrollment, ads, growth, nora, nova) and Midas
  (`midas`), both inside their brief.
- Everyone else sees assigned work only through `agents_hub.open_tasks_block(<id>)` in their **chat**
  prompt (`agents_chat._tasks`, `marcus_chat._hub_tasks`, `agency_agents`, `_director_chat`). A
  `chatVia` agent's tasks show in its owner's block.
- Bus → Telegram forwards only types `hot_lead, proposal, missed_sweep, skill_proposal,
  edit_request, dyson_plan`, any `kind=handoff`, and messages from dyson/eco (`telegram_io.py:345`).

### 6. Cost buckets

`cost_tracker._who()` = thread name if in `AGENT_THREADS` (scout, marcus, atlas, followup, solomon,
midas, dyson, eco, do_today, telegram, brief, graphify), else `operator`. So: unnamed threads
(auto-screen, ACE, Telegram handoff, skill_forge), every HTTP call, the systemd learn curls, and the
`telegram_agent` bot all bill to `operator`. Orion bills to `brief`.

## Keeping these honest

- **Update the card in the same change** whenever an agent's trigger changes: a thread name,
  interval, env knob, route, Telegram command/alias/trigger regex, bus role, `chatVia`, or learn cadence.
- `CLAUDE.md` §2/§5 stay canonical for policy; these cards are canonical for *triggers*.
- Run `cd "forge rei" && python3 test_agents_docs.py` — it fails if a roster agent has no card, a card
  is filed under the wrong business, or a cited path/skill doesn't exist.

## Known inconsistencies (code vs. docs, found 2026-09-22)

Docs-only pass — none of these were fixed.

**Doc claims that don't match code**
1. `CLAUDE.md` §9 says "`/task orion …` still reaches them" (Orion and the briefs). False: `/task` always files for the active Telegram agent (`telegram_io.py:919-934`) and there is no `/orion` alias or trigger word (`telegram_io.py:670-683`). Orion is reachable only from the dashboard.
2. `CLAUDE.md` §9 Agent Office: "twelve agents as pixel characters" and "`analyze`/`build_brief` for the dropship four". The floor has 7 agents (`pixel_office.py:37-46`) and every task runs through `agents_hub.chat` (`pixel_office.py:284-295`).
3. `CLAUDE.md` §4a/§10: Solomon has 5 top skills, not 4 — `solomon-systems-craft.md` is also loaded (`daycare_director.py:228-230`). And "one brief, one Claude call": a brief is 2 calls (competitor read `agency_eco.py:382` + brief `daycare_director.py:615`).
4. `CLAUDE.md` §4a table: the wholesale creed file lives only in `forge-scout/skills/`, not `forge-marcus/skills/` (still loads — `agent_creed` searches both).
5. `CLAUDE.md` §2 ACE: "One POST (`/api/ace/mode`) … only the operator flips it". Telegram `/ace <mode>` also flips it (`telegram_io.py:866`), and the POST has only network/Host/same-origin checks (`connector.py:3240-3246`). "After every Scout auto-screen": also after a manual `/api/screening/run` (`connector.py:3745`). "Capped 3/10": questions are really 2/9 (`FORGE_ACE_PIVOT_RESERVE`, `ace.py:53`, `:83-89`).
6. `docs/FORGE_AGENTS.md` §2: "Atlas … no UI (`/api/prep/*` unused by UI)" — stale; `atlas_card.jsx` uses `/api/prep/get` + `/run`.
7. The "Solomon · Director" tab named in `CLAUDE.md` §10 doesn't exist as a string in the UI; the Director, Dyson and Eco pages have no sidebar entry — reached via the Agents hub Console tab (`agents_hub.jsx:17-24`). The Director hero says "30-year" (`daycare_director.jsx:61`) vs. 50 years in the prompt (`daycare_director.py:538`).
8. `forge rei/test_agents_docs.py:50` comment says Orion is "deliberately absent from the roster" — he is in it (`agents_hub.py:124`).
9. `deploy/setup_droplet.sh:125` says the weekly review is "Mon 08:00 UTC" but `OnCalendar=Mon *-*-* 08:00:00` has no zone → box-local.

**Trigger / behavior gotchas in code**

10. Telegram name triggers run AFTER the ops router's plain-English intent classifier (`telegram_ops.py:871-874`), so "solomon, …" first costs a Claude intent call (bucket `telegram`) and could be consumed as an ops action.
11. `cost_tracker.AGENT_THREADS` lists `dyson` and `eco`, but no thread has those names; screening, ACE, skill_forge, style, review and all learn curls bill to `operator` (`connector.py:1248`, `:2189`).
12. Telegram `/task` for Dyson/Eco skips the hub task store (`telegram_io.py:937-948`), so it never shows in the Agent Control Center task counts; `/api/hub/task` writes both.
13. Solomon and Midas mark `all` broadcasts read for every agent (`agent_bus.inbox` includes `all`, `agent_bus.py:122`; `mark_read` is global). Marcus's `directive` messages to `scout` (`marcus_lead.py:120`) and Solomon's delegations to billing/staffing/compliance are never read by anyone.
14. Atlas chat always says "(prep data unavailable)" — it slices the dict returned by `list_all()` (`agents_chat.py:266-272`, `deal_prep.py:576`).
15. Bus alerts that never reach Telegram despite comments saying they do: Scout `agent_down` (`scout_triage.py:1860`) and Follow-up `checkback_due` (`followup.py:13`, `:225`) — `_event_class` drops both (`telegram_io.py:345-356`). ACE's call-ready likely pings twice (bus handoff + direct send, `ace.py:1010-1030`) — verify on the box.
16. Autopilot has no Test Mode check (ACE does, `ace.py:544`) and counts its day in box-local time (`autopilot.py:50`) while ACE uses ET.
17. ACE question drafts carry `reengage: true` because they pass a `hint` (`marcus_engine.py:1092`, `ace.py:674`), contradicting `autopilot.py:143-148`; shadow-mode drafts also count as Follow-up approvals (`agents_hub.py:624`). Unknown — verify with a shadow-mode test.
18. Scout's weekly audit ignores clock-out (`scout_triage.py:1854-1855`) and still calls Claude.
19. Midas's auto-learn only runs from `run_forever` (`dropship_director.py:1133`), so it never fires while the loop is off (the default). Archiving dropship gates no route, Telegram path, or loop.
20. `_director_chat` checks only `review_agent._api_key()` (`agents_hub.py:298`) — Solomon/Midas/Orion chat can say "no key" while their own `*_ANTHROPIC_API_KEY` is set. Solomon's chat gets no top skills (no `top_skills_text` in `daycare_director`).
21. No chat surface loads the wholesale creed (Scout/Marcus/Atlas chat, `agents_chat.py`, `marcus_chat.py`); only their scoring/screening/drafting/prep prompts do. Dyson's draft generator and Eco's generate path skip the agency creed (`agency_dyson.py:269`, `agency_eco.py:176`).
22. `daily_learn.sh` runs `/api/review/run {"days":1}` nightly, overwriting the Monday 7-day playbook; its `{"auto":true}` bodies are ignored and bypass learn rate limits (`connector.py:3702`, `:3755`); Atlas, Solomon, Midas, Orion aren't in it.
23. No `retire()` in the off branch for `marcus_sms` (`connector.py:5083-5087`). Intervals with no env knob: Marcus SMS 60 s, Atlas 900 s, Solomon/Midas 900 s tick, agency 45-min learn gap.
24. Daily brief/recap/Orion use fixed `FORGE_TZ_OFFSET` (default −4) while the connector sets `TZ=America/New_York` (`connector.py:46-48`) → one hour off in winter unless set to −5.
25. `GET /api/daycare/eco/ideas` makes a Claude call on a GET and no UI calls it (`daycare_growth.jsx` uses `/nova/*`).

## Scope notes vs. the requested layout

- `cross-business/` replaces the old `portfolio/` folder. `portfolio/orion.md` is now a pointer
  stub because root `AGENTS.md:21` links to it; `portfolio/briefs.md` was removed.
- Added `cross-business/briefs.md` — the test requires a card named after roster id `briefs`.
- Nothing requested was skipped: every listed agent/worker exists in code.
