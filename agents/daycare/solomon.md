# Solomon — Executive Director (the daycare's one agent)

> Code refs are relative to `forge rei/` unless they start with `forge-`. Sections 1–9 and the Replies lane (§10) were re-checked against code 2026-10-31 (line numbers and the fixes listed in that day's change note below); §11–§17 keep their earlier verification date and each states its own. §18 (Calendar) and §19 (keys) were written from code 2026-10-31.

Solomon is the daycare's ONE agent. He owns several lanes, each with its own loop, heartbeat
and state file — one identity, one Agent Control Center row, one chat:

| Lane | Engine | Loop / heartbeat | What it does | Section |
|---|---|---|---|---|
| **Brief** (director) | `forge rei/daycare_director.py` | `solomon`, 900 s tick, brief 24 h — **OFF by default** (`FORGE_SOLOMON_BRIEF=1` turns it on); on-demand brief + chat work either way | the ranked operating brief | §1–9 |
| **Solomon · Replies** (the Reply Desk) | `forge rei/daycare_replies.py` | `daycare_replies`, 60 s | drafts every parent text-back; the owner taps send | §10 |
| **Solomon · Leads** (the Lead Desk) | `forge rei/daycare_leads.py` | `daycare_leads`, 900 s | GET-only enrollment-lead sweep, $0 | §11 |
| **Solomon · Starts** | `forge rei/daycare_starts.py` | `daycare_starts`, 900 s | start dates → owner confirm → start-day app login, $0 Claude | §12 |
| **Solomon · Ads** | `forge rei/daycare_ads_autopilot.py` | `daycare_ads`, wakes 15 min, one cycle per day | daily Meta ad optimizer + creative loop (shadow by default) | §13 |
| **Solomon · Revive** | `forge rei/daycare_revive.py` | rides the `daycare_replies` thread | win-back drafts for quiet leads | §14 |
| **Solomon · Orchestrator** | `forge rei/solomon_orchestrator.py` | `solomon_orchestrator`, 300 s wake — **OFF by default** (`FORGE_SOLOMON_ORCH=1`) | keeps the Command Board current, $0 Claude | §17 |
| **Solomon · Calendar** | `forge rei/daycare_calendar.py` (+ `forge rei/google_cal_io.py`) | `daycare_calendar`, 900 s | tours + first days → one Google calendar, $0 Claude, **QA mode by default** | §18 |
| **Solomon · Pipeline** | `forge rei/daycare_pipeline.py` | `daycare_pipeline`, 300 s, GET-only | the two GHL enrollment boards (ATOB + A Mother's Touch), stage moves = owner taps, $0 Claude | §20 |

The lanes report to him: `reply_desk_state()` / `lead_desk_state()` (`daycare_director.py:142`/`:165`)
feed the brief (`replyDesk` / `leadDesk`), his chat (`agents_hub._lanes_block`) and his registry
row (the Calendar lane is the exception: see §18). Until 2026-09-24 the Reply Desk had its own roster row (`daycare_replies`) and the Lead Desk
its own card; both were folded in here.

## 1. Identity

| | |
|---|---|
| Business | Daycare (A Touch of Blessings) · hub id `solomon` · emoji 🏛️ |
| Job | **Daycare orchestrator (owner, 2026-10-18: Gmail, GHL, ads, billing, social, roster — growth stays first; spec `docs/superpowers/specs/2026-10-18-solomon-daycare-orchestrator-design.md`).** History: 2026-09-30 made him growth director only ("paperwork/compliance/billing/staff admin are not his lane") — reversed; the creed/top-skill wording change is owner-approved separately. Writes ONE ranked growth brief: Attention Now, Enrollment, Growth economics (`money`), Capacity to enroll (`people`), Seats (`roster`), Keep + refer (`followUps`), Campaign health, Competitor read, Creative, Delegations. Absorbed Nora + Nova (2026-07-25), then the Reply Desk + Lead Desk as his Replies + Leads lanes (2026-09-24). |
| Engine | `forge rei/daycare_director.py` → `SolomonEngine` (`daycare_director.py:393`), connector global `SOLOMON` |
| Seed folder | `forge-solomon/` (skills in `forge-solomon/skills/`) |

## 2. Triggers

**Scheduled loop** (the brief lane; the other two lanes: §10, §11)

| Field | Value |
|---|---|
| Thread | `solomon` (`connector.main`) |
| Gate | Box only (`FORGE_MARCUS=1`) **and** `FORGE_SOLOMON_BRIEF` != `0`. **Default is OFF** (`SCHEDULED_BRIEF`, `daycare_director.py:86`; owner cut scheduled briefs 2026-09-30): the thread is not started and `forge_heartbeat.retire("solomon")` runs at boot. The on-demand brief (`POST /api/daycare/director/run`) and chat work either way |
| Tick | 900 s, hardcoded (`POLL_INTERVAL`, `daycare_director.py:95`) |
| Brief cadence | `FORGE_SOLOMON_BRIEF_EVERY_H`, default 24 (`BRIEF_EVERY_MS`, `:88`) |
| Failure backoff | 15 min doubling to 6 h (`backoff_delay_s`, `:1177`) |
| Clock-out | tick skipped on `forge_ops.paused()` (`:1210`) |
| Session | builds under `daycare_supabase.BRIDGE.autoadmin_session("127.0.0.1")` |
| Heartbeat | `solomon` every tick (`:1238`), only while the scheduled brief is on |

**Telegram**

| Form | Effect |
|---|---|
| `/solomon` · `solomon, …` / `solomon: …` / `solomon — …` | chat → `_tg_agent_chat` → `agents_hub.chat` |
| `/task <title>` while active | `agents_hub.send_task("solomon", …)` → he also reads it off the bus at the next brief |

**HTTP** — daycare router, every route needs the secure check + a daycare session (cookie or loopback/Serve auto-admin)

| Method | Routes |
|---|---|
| GET | `/api/daycare/director/{status,overview,brief,bus}` · `/api/daycare/family/{status,overview,brief,bus}` (→ `roster_view()`) · `/api/daycare/adops/{status,overview,brief,bus}` (→ `adops_view()`) · `/api/daycare/eco/ideas` (Claude call on GET) |
| POST | `/api/daycare/director/run` · `/director/learn` · `/family/run` · `/family/learn` · `/adops/run` · `/adops/learn` |

Lane routes: §10 (`/api/daycare/replies*`), §11 (`/api/daycare/leads*`). `replies_view()` /
`leads_view()` exist on the engine (lane view + the lane's live state) but no route serves them yet.

**Bus roles he answers to** — `BUS_ROLES` (`daycare_director.py:73`): `solomon`, `family-comms`, `enrollment`, `ads`, `growth`, `nora`, `nova`, `daycare_replies`, `daycare_leads`. `_read_bus_inbox` (`:587`) pulls unread (≤10 per role, plus `all`), marks them read, feeds the newest 10 into the brief as `busDelegations`.

**Handoffs in:** bus messages to any role above · hub tasks (including any still filed under the retired `daycare_replies` id — `agents_hub._FOLDED`) · his Leads lane feeds `leadDesk` and his Replies lane feeds `replyDesk` into the brief.

**Calendar lane triggers (§18):** the 15-min `daycare_calendar` thread, plus the owner taps `POST /api/daycare/tour/confirm`, `/tour/cancel`, `/starts/calendar` and the read `GET /api/daycare/calendar`.

**UI:** `window.DaycareDirector` (route key `Director`, `app.jsx:69`; page title "Solomon") — via the Agents hub Console tab, not the Daycare sidebar · Agent Control Center `solomon` (all three lanes) · Agent Office (Daycare room) · "Solomon · Leads" card on the Daycare Dashboard · "Google Calendar" status panel (`DcsCalendarStatus`, `daycare.jsx:294`) and the Book tour / Cancel tour buttons on the Lead Desk rows.

## 3. Reads / context load order

`build_brief` (`daycare_director.py:753`):
1. inline role + evidence rule (backstop) — names both live lanes; the brief itself never drafts family text
2. `north_star`
3. `daycare-context.md` [:12000 — whole file; was 3500, which cut the offers/referral/CCIS angle] + `enrollment-ad-agent.md` [:4000] (`daycare_context.py`)
4. creed `agent_creed.block("daycare")` → `daycare-evidence-discipline.md`
5. TOP SKILLS (`TOP_SKILLS`): `solomon-decision-loop.md`, `solomon-director-craft.md`, `solomon-orchestrator-craft.md` (2026-10-18), `solomon-systems-craft.md`, `solomon-roster-craft.md`, `solomon-adops-craft.md` (+ any other `solomon-*` non-playbook), seed then vault, never truncated
6. PLAYBOOK (`_playbook_only`): seed `solomon-playbook.md` + vault `Skills/solomon-playbook.md` [:4000]
7. last 2 vault `Reports/daycare/*.md` [:1200 each]
8. user JSON: metrics, alerts, roster (classrooms with `openSeats`, null = Unknown), blasts, opt-outs, campaign, competitor, busDelegations, connectedSystems (presence only), `leadDesk` (Solomon · Leads — KPIs + top 10 needs-human), `replyDesk` (Solomon · Replies — pending drafts, escalations, oldest pending age, last sweep, error), `startsDesk` (Solomon · Starts — start dates by status + next 10 upcoming), `board` + `mailDesk` (2026-10-18 — the Command Board's counts, top 10 open items with evidence, failed sources; daycare-mail counts + top-5 urgent subjects; `board_state()`, §17)

## 4. Outputs / writes

- `marcus_state/solomon.json`.
- Lane state files: `daycare_replies.json`, `daycare_leads.json` + `daycare_lead_stages.json`, `daycare_starts.json`, `daycare_ads_auto.json`, `daycare_revive.json`, `daycare_board.json`, `daycare_calendar.json` (the Calendar ledger, §18).
- Vault `Reports/daycare/brief-YYYY-MM-DD.md` per brief, `Skills/solomon-playbook.md` on learn.
- Bus: `solomon→all` status per brief · one `handoff` per delegation to `role.lower()` (≤8) · learn status · his Leads lane's owner alerts (`solomon→operator`, §11).

## 5. Autonomy & gates

- Read-only, propose + delegate. Never texts a family, invoices or launches ads, and the brief never writes the DB. His Replies lane drafts family texts, but only the owner's tap sends one (§10).
- **Exception — Auto-enroll lane (ON by default, owner decision 2026-10-07):** `daycare_auto_enroll.py` writes child rows + parent logins to production Supabase for every READY Family Contact Form card, no click; odd cards are held with a reason. PIN texts wait on `FORGE_DAYCARE_AUTO_ENROLL_TEXT=1`. Off: `FORGE_DAYCARE_AUTO_ENROLL=0` (CLAUDE.md §2).
- The brief's own autonomous writes: brief notes, playbook, bus notes. Lane writes are listed per lane: Starts writes a GHL field + tag (§12), Ads writes to Meta only in `auto` mode (§13), Calendar creates, moves and removes events on ONE Google calendar (§18, QA mode by default). Never a text, email to a family, invoice or tag-based message trigger without the owner's tap.
- Kill (brief lane): `FORGE_MARCUS` not `1`, `FORGE_SOLOMON_BRIEF=0` (already the default), clock out, or no key. Key: `SOLOMON_ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY` → agency → wholesale (`_solomon_key`, also used by the Replies lane and his chat).
- Knob `FORGE_SOLOMON_BRIEF_TOKENS` 5000.

## 6. Self-improvement

- `_maybe_learn` every tick: `FORGE_SOLOMON_LEARN_EVERY` (8 briefs) **and** `FORGE_SOLOMON_LEARN_GAP_MIN` (45 min) → about every 8 days at the 24 h cadence.
- Manual: POST `/api/daycare/director/learn` (also `/family/learn`, `/adops/learn`). Not in `daily_learn.sh`.
- Sees only the playbook (`_playbook_only`) — creed and top skills are untouchable.
- The lanes have no `learn()` loop (§10, §11).

## 7. Chat & tasks

- `/api/hub/chat {agentId:"solomon"}` → `agents_hub._director_chat` (`agents_hub.py:329`), key from `daycare_director._solomon_key()`.
- Prompt: role + blurb → creed → `daycare_context.context_block()` → latest brief [:3500] → top skills (**empty** — `daycare_director` has no `top_skills_text`) → `playbook_text(4000)` → **YOUR LIVE LANES** (`_lanes_block` → `_delegate_context("solomon")`: Replies + Leads state, [:2500]) → `open_tasks_block("solomon")` → `caveman.block()`. ≤700 tok.
- Tasks reach him twice: `open_tasks_block` in chat + the bus `task` message read at brief time.
- **Live data (2026-10-18):** `_director_chat` runs `dash_live.ask` — read-only `api_get`/`find_people`/`route_help` over `/api/daycare/*` + brain/owner-actions, ≤4 tool turns; he pulls `/api/daycare/ads/feed` himself before quoting a Meta figure (the per-message `ads_feed_block` preload now runs only when live tools are off). Workspace: Daycare only (cross-workspace `/api/hub/chat {business}` refused). Knob `FORGE_CHAT_LIVE=0`.
- **Cross-agent (owner, 2026-10-18 — agents are not restricted from one another):** he may READ any business's GET route (another business's payload comes back labeled `readFrom` — Marcus's / Dyson's numbers, never his); he WRITES only in the daycare. For a write in another business he files that agent a hub task (`api_post /api/hub/task {agentId, title, note}` — AUTO in dashboard chat, a card in Telegram); any other agent can task him the same way. Refusal pointer: `telegram_agent.foreign_write` in `forge rei/telegram_agent.py`; labeling: `dash_live.label` in `forge rei/dash_live.py`.

## 8. Cost

Claude: yes — 2 calls per brief (competitor read + brief) + learn. Bucket `solomon` on the loop; `operator` for manual runs/chat/`eco/ideas`; `telegram` for Telegram chat. His lane threads bill to `solomon` too (`cost_tracker.THREAD_ALIAS`): the Replies lane's drafts (§10) and the Leads lane ($0 today).

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="solomon")|{status,lastSuccessAt,nextRun,lastError,pendingApprovals,work,detail,heartbeat}'
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="solomon" or .loop=="daycare_replies" or .loop=="daycare_leads" or .loop=="daycare_starts" or .loop=="daycare_calendar")'
# needs a daycare session (auto-admin via loopback/Serve):
curl -s localhost:7799/api/daycare/director/status | jq '{aiReady,creedLoaded,topSkills,briefCount,lastBriefAt,nextBriefAt,failStreak}'
```

His registry row (`agents_hub.registry`): heartbeats from `AGENTS[solomon]["hb"]` (`agents_hub.py:134`) = `solomon` (only when `FORGE_SOLOMON_BRIEF` is on) + `daycare_replies` + `daycare_leads` + `daycare_starts` + `daycare_ads` + `solomon_orchestrator` (only when `FORGE_SOLOMON_ORCH=1`). `daycare_calendar` is NOT in that list: a sick Calendar loop does not change his row status; it shows on `/api/system/health` and sends a loop-down alert to the daycare Telegram chat (`connector._WATCHDOG_BIZ`). A sick lane loop in the list turns his status DEGRADED/FAILED and `lastError` names the lane, approval queue = pending Reply drafts (`WAITING FOR APPROVAL`), `work` = briefs · Replies drafts waiting · Leads needing a human.

## 10. Lane: Solomon · Replies — the Reply Desk (parent-reply drafter, added 2026-09-23)

His `family-comms` lane made concrete: every 60 s (`FORGE_DAYCARE_REPLIES_INTERVAL`), drafts the next text back (a parent gets an answer ~90 s–5 min after texting — never instant) to any parent/guardian who texted the daycare GHL number and is owed a reply, in the center's real texting voice, grounded in the verified fact sheet. **Draft-only by default — the owner's tap sends.** Opt-in `FORGE_DAYCARE_REPLY_AUTO=1` auto-sends ONLY clean, flag-free answers to enrollment *leads* in the safe categories (tour · subsidy · availability · enroll · pricing-deflect); escalations, enrolled families, billing/safety/custody/medical, and anything flagged stay a tap. Cap `FORGE_DAYCARE_AUTO_CAP` (30/day), ≤3 per contact/24 h, 8am–9pm ET, Telegram receipt each send, stopped by clock-out or any staff reply in GHL. Lead-qualifying ladder (age → center → start → subsidy → tour) lives in `daycare-parent-reply.md` §2b.

**Identity + triggers**

| Field | Value |
|---|---|
| Engine | `forge rei/daycare_replies.py` (no engine object — pure functions + a state file), self-check `forge rei/test_daycare_replies.py` |
| Thread | `daycare_replies` (`connector.main`, started next to the Leads thread); bills to `solomon` |
| Gate | `FORGE_MARCUS` != `0` **and** `FORGE_DAYCARE_REPLIES` != `0` (default on; `0` retires the heartbeat) |
| Tick | `FORGE_DAYCARE_REPLIES_INTERVAL` 60 s · ≤`FORGE_DAYCARE_REPLY_MAX` 8 Claude calls + ≤40 thread GETs per sweep |
| Clock-out | whole sweep skipped on `forge_ops.paused()` |
| Heartbeat | `daycare_replies`, label "Solomon · Replies" |
| Model | `FORGE_DAYCARE_REPLY_MODEL`, default `review_agent.SMART_MODEL` (= `FORGE_SMART_MODEL`, default `claude-sonnet-5-5`; `daycare_replies.py:58`) · key = `_solomon_key()` |
| Knobs | `FORGE_DAYCARE_REPLY_GRACE_SEC` (90) · `FORGE_DAYCARE_REPLY_MAX` (8) · `FORGE_DAYCARE_REPLIES_INTERVAL` (60) · `FORGE_DAYCARE_REPLY_AUTO` (0) · `FORGE_DAYCARE_AUTO_CAP` (30) |
| Telegram | no `/replydesk` command and no name trigger — ask Solomon (`solomon, …`) |
| Handoffs | none in — it reads the daycare GHL location directly, the same account the Leads lane and the speed-to-lead website workflow use |

**HTTP** — daycare router, every route needs the secure check + a daycare session:

| Method | Routes |
|---|---|
| GET | `/api/daycare/replies` · `/api/daycare/ghl/conversations` (inbox, one GHL GET) · `/api/daycare/ghl/thread?contact_id=` (one family's messages + `canSend`/`blockReason` + pending draft) |
| POST | `/api/daycare/replies/run` (sweep now, sends nothing) · `/replies/approve {contact_id, text?}` (the owner's send tap) · `/replies/dismiss` · `/api/daycare/ghl/reply {contact_id, text}` (owner-typed text from the mobile Messages tab — `send_manual`, same window/opt-out/DND gates, ≤640 chars, retires a pending draft) |

**Surfaces:** his Agent Control Center row (pending drafts = his approval queue), Owner Actions (one APPROVE row per pending draft, "Solomon · Replies", `owner_actions._src_daycare_replies`), the brief's `replyDesk`, his chat's live-lanes block. No desktop page of its own.

**Reads, in order** (`daycare_replies._system()`):
1. `agent_creed.block("daycare")` — the creed outranks everything below it.
2. `daycare_context.context_block()` — `forge-daycare/skills/daycare-context.md` [:6000].
3. `forge-daycare/skills/daycare-parent-reply.md` — the decision rubric + the verified fact sheet (addresses, phones, hours, offer status, what to answer vs. confirm vs. escalate). Facts here win over the context brief if they ever disagree.
4. `forge-daycare/skills/daycare-voice.md` — how ATOB actually texts, built from 136 real outbound SMS.

Per-thread user prompt: last 15 messages of the conversation, parent/child first names, which of the three centers, current ET time. Missing either skill file raises rather than drafting blind. Never caveman — a family-facing message.

**Outputs / writes:** `marcus_state/daycare_replies.json` only — one row per contact: `pending` (needs the owner's tap), `sent`, `dismissed`, `stale` (someone answered in GHL since), `opted_out`, `no_reply`. No bus messages, no vault writes, no GHL writes on the read path. Per thread the model returns `draft` / `escalate` / `no_reply`, plus `category`, `unknowns` and code `flags`.

**Autonomy & gates — this is the part that matters**

- **Draft-only by default.** Every row is a proposal; nothing sends without `/api/daycare/replies/approve`, except the opt-in `auto_send()` path (`FORGE_DAYCARE_REPLY_AUTO=1`, default OFF, clean enrollment-lead answers only, see the lane intro above). Turning it on is an operator decision.
- **Yields to the GHL automations first** (`gate()`, pure, no Claude): a thread is skipped when —
  - the last message is already outbound (a workflow or a person answered);
  - the parent sent STOP/HELP/START/etc. — the carrier/GHL keyword auto-replies own those words;
  - the parent has opted out or is DND — permanent, never revisited;
  - a fresh website lead is still inside the speed-to-lead window (speed-to-lead tag on and the first touch not out within 15 min, or the overnight `speed-to-lead-queued` → 8am flush) — the workflow owns that first text, not this;
  - the inbound is younger than `FORGE_DAYCARE_REPLY_GRACE_SEC` (90 s) — lets a workflow's stop-on-response or live staff typing back go first;
  - the thread isn't SMS, or the inbound is older than 7 days (the Leads lane's job, not this one's).
- **Code-level draft flags** (`flags()`, always run, never bypassable by the model): a phone number not on the fact sheet (`unverified_phone`), a dollar figure (`money`), an emoji, or a draft over ~3 SMS segments (`long`).
- **`approve()` re-checks the live thread**, not the cached draft: refuses outside 8am–9pm ET, refuses and retires the draft if anyone (staff or a workflow) replied since it was written, refuses if the parent opted out in the meantime. One `daycare_ghl.send_sms` + `action_log` (as `solomon`).
- **`escalate`** category (safety, custody, medical, complaint, billing dispute) never gets a substantive draft — only a short holding line; the owner calls.
- Kill: `FORGE_DAYCARE_REPLIES=0`, clock out, `FORGE_MARCUS=0`, or no Anthropic key. A billing/auth error from Anthropic aborts the sweep mid-way (shows on the heartbeat) rather than silently drafting nothing.

**Self-improvement:** none. `daycare-voice.md` and `daycare-parent-reply.md` are owner-edited skill files (mtime hot-reload via `daycare_context.load_skill`), not a `learn()` loop — they don't drift on their own.

**Chat & tasks:** Solomon answers (§7) with the lane's live state in his prompt. No dedicated task queue; a task still filed under the retired `daycare_replies` id shows in Solomon's open-tasks block.

**Cost:** Claude — up to `FORGE_DAYCARE_REPLY_MAX` (8) `SMART_MODEL` calls per 60 s sweep, only for threads that pass `gate()`. Bucket `solomon` (thread `daycare_replies` aliased in `cost_tracker.THREAD_ALIAS`).

```bash
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="daycare_replies")'
curl -s localhost:7799/api/daycare/replies | jq '{lastRunAt,lastSweep,error,pending:[.pending[]|{center,category,action,flags,draft}]}'
```

## 11. Lane: Solomon · Leads — the Lead Desk (enrollment-lead sweep)

Every 15 min reads the daycare GHL (GET only), derives each enrollment lead's stage + response time, lists who needs a human, and pings the owner. Zero Claude.

**Identity + triggers**

| Field | Value |
|---|---|
| Engine | `forge rei/daycare_leads.py` (module, `run_forever(DAYCARE_GHL)`), self-check `forge rei/test_daycare_leads.py` |
| Thread | `daycare_leads` (`connector.main`); bills to `solomon` ($0) |
| Gate | `FORGE_MARCUS` != `0` **and** `FORGE_DAYCARE_LEADS` != `0` (default on) |
| Off | `FORGE_DAYCARE_LEADS=0` → `forge_heartbeat.retire("daycare_leads")` |
| Interval | `FORGE_DAYCARE_LEADS_INTERVAL`, default 900 s (`daycare_leads.py:58`); first sleep aligned to the last run |
| Clock-out | sweep skipped on `forge_ops.paused()` |
| 429 | aborts the sweep, waits for Retry-After |
| Heartbeat | `daycare_leads`, label "Solomon · Leads" (`daycare_leads.py:677`) |
| Telegram | outbound only (owner pings, "Solomon · Leads — …"). No command, no name trigger — ask Solomon |

**HTTP** — daycare router, session-gated

| Method | Route |
|---|---|
| GET | `/api/daycare/leads` → `view()` (state file only, no network) |
| POST | `/api/daycare/leads/stage` → `set_stage` (LOCAL mark, never written to GHL) |

**Bus:** sends `solomon→operator` alerts (contact id + reason codes only; was `daycare_leads→operator` before 2026-09-24). Reads nothing.

**UI:** "Solomon · Leads" card on the Daycare Dashboard (`daycare.jsx:307`, `DldLeadDesk`).

**Feeds:** Solomon's brief (`leadDesk`) · his chat's live-lanes block · his registry row · Owner Actions (`_src_daycare_leads`, "Solomon · Leads: …") · Mission Control daycare tiles · daily brief/recap stats.

**Reads:** GHL contacts (6×100), conversations search, ≤50 per-contact lookups, messages, tasks · local stage marks + the contact→child ledger. Stage tags from `daycare_leads.STAGE_TAGS`. No creed, skills or playbook.

**Outputs / writes**

- `marcus_state/daycare_leads.json`, `marcus_state/daycare_lead_stages.json`.
- Owner alerts: bus + Telegram (first name only in Telegram, deduped). Display name falls back parent → child ("Ava's family") → "New family"; a parent-name field under 2 characters (e.g. "I") counts as missing (`display_name`).
- Nothing to GHL, nothing to families.

**Autonomy & gates**

- GET-only on GHL; sends nothing to families.
- Alerts only 8am–9pm ET, once per lead+reason episode; first run seeds silently.
- Kill: `FORGE_DAYCARE_LEADS=0` + restart.

**Self-improvement:** none. **Chat & tasks:** none of its own — ask Solomon; the lane is part of his brief input and his chat context.

**Cost:** zero Claude calls (imports no `review_agent`). $0.

```bash
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="daycare_leads")'
curl -s localhost:7799/api/daycare/leads | jq '{lastRunAt,lastOkAt,error,kpis}'   # needs a daycare session
```

## 12. Lane: Solomon · Starts — start date → confirm → start-day app login (added 2026-09-29)

Spec: `docs/superpowers/specs/2026-09-29-daycare-start-date-design.md`. Code: `forge rei/daycare_starts.py`.

- **Trigger:** thread `daycare_starts`, every 15 min on the box (`FORGE_DAYCARE_STARTS=0` retires it), heartbeat `daycare_starts` "Solomon · Starts", bills to `solomon`. Zero Claude.
- **Reads:** changed daycare GHL threads (≤30/sweep) of signup contacts (`website-lead` / `form-type-new-inquiry` / `family-contact-form`). Pure regex extractor: a start word + a date in one message, future ≤120 d; fallback = the form's Desired Start Date.
- **Writes (autonomous, internal + reversible):** `marcus_state/daycare_starts.json` (dates, names, ≤160-char evidence quote — never a PIN/phone/email); GHL field **Agreed Start Date** (`KDzh39WHQIlZIIUb7xLR`) + tag `start-date-proposed`.
- **Owner gate:** Confirm (`POST /api/daycare/starts/confirm`, dashboard "Start dates" card / mobile Families → Start dates; Owner Actions APPROVE row + one Telegram ping from 2 days out) enrolls/updates the child (`enrollment_date` = start) + ensures a parent login, **texting nothing**. That tap approves the ONE start-day text.
- **Outward (after confirm only):** on the start day, first tick 8am–9pm ET: fresh PIN (`provision-user reset-pin`, never stored) → `daycare_ghl.start_day_text` via `daycare_replies.send_manual` (opt-out/DND/window) → tag `app-login-sent`. Marked `sending` first, so a crash never double-texts; 3 failures → Owner Actions FIX.
- **Safety:** a different date in the thread after confirm reopens it to `proposed` (sweep runs before send each tick). Owner edits/dismissals beat older evidence.
- **Verify:** `cd "forge rei" && python3 test_daycare_starts.py`; `GET /api/daycare/starts` → `lastRunAt` fresh.

## 13. Lane: Solomon · Ads — the daily ad optimizer + creative loop (added 2026-09-30)

Code: `forge rei/daycare_ads_autopilot.py` (+ Pipeboard reads/writes in `forge rei/pipeboard_io.py`). Skill: `forge-daycare/skills/daycare-ad-optimizer.md` (marketing-skills Meta decision system, distilled; edit it and the next run uses it). UI: Growth → Autopilot.

- **Trigger:** thread `daycare_ads` wakes every 15 min on the box; the cycle runs once per local day after `FORGE_DAYCARE_ADS_HOUR` (default 8), on COMPLETE days only. `FORGE_DAYCARE_ADS=0` retires it. Heartbeat `daycare_ads` "Solomon · Ads", bills to `solomon`.
- **Reads:** Pipeboard (daycare token from `daycare.env`): account health, campaigns/ad sets/ads, 14 days of per-day ad rows + a 14-day window row for frequency. Competitor ads (Meta Ad Library via `dropship_adspy`, Apify; cached 7 days; ads running ≥21 days = the market's winners) when `APIFY_TOKEN` exists — else "Unknown", never invented.
- **Learning gate (added 2026-10-22):** a campaign whose name starts with `FORGE_DAYCARE_ADS_LEARN_PREFIX` (default `ATOB — Enrollment 2026 — Leads — Oct`) gets no pause/cut/scale/replacement/new ad until it has delivered 7 days with ≥50 results, or 14 days; entities read `learning: day N, X/50 results`; `guard()` + the Ad Studio Build target (`pick_target`) refuse it (fail closed before the first daily read); state `learning` in `daycare_ads_auto.json`, exposed on `…/ads-auto/status` and the feed's autopilot block; board items `learn:<id>` (learning) / `learn:<id>:ready` (3 days after it opens).
- **Decides (pure code, `evaluate`):** thresholds are multiples of TCPL (`FORGE_DAYCARE_ADS_TCPL`, default $30 since 2026-10-22, was $40): 3×T data gate; kill = zero leads at 3×T or CPL >1.5×T at 4×T; delivery-kill a starved mature ad; scale +20% (CPL ≤T, ≥3 leads, 7d ≤1.2×T, freq <3, still converting), cut −25% (7d CPL >1.5×T or no leads). Claude (SMART tier — Sonnet 5.5, low effort, since 2026-10-17) may only veto/annotate and writes the owner note + creative brief; **no Anthropic credit = rules-only**, still works.
- **Writes (only after the mode allows):** `shadow` (default) = proposals + Telegram, nothing on Meta; `auto` = pause/budget/activate with `guard()` (cooldown 5d up / 2d down, ≤+20% step, account ceiling `FORGE_DAYCARE_ADS_MAX_DAILY`, never the last active ad, ≤4/run), each write dry-run → real → re-read verified, `action_log` row, `undo`. Creative loop: ≤1 new test per 3 days, ≤2 in their 14-day read, ad-count ceiling, built PAUSED inside the best delivering ad set (no new spend dimension), Higgsfield art disclosed to Meta (`ai_media`).
- **Gates:** only the operator flips the mode (CLAUDE.md §2 exception). Hold one entity: `POST /api/daycare/ads-auto/hold`.
- **Routes:** `GET /api/daycare/ads-auto/status`; `POST /api/daycare/ads-auto/{run,mode,approve,reject,undo,hold}`. Telegram: Solomon's business-partner chat can `approve` proposals through the same routes (tap-gated).
- **Verify:** `cd "forge rei" && python3 test_daycare_ads_auto.py`; `GET …/ads-auto/status` → `wired`, `lastRun`; `state: forge rei/marcus_state/daycare_ads_auto.json`.
- **Live ad packet (added 2026-10-17).** Every ad number Solomon sees is a FRESH Pipeboard read (no 60 s cache): `daycare_growth.ads_feed()` → windows last 7 / 30 / 90 days + maximum (account lifetime, from `created_time`, ≤37 months), the selected window's day series (+ previous period with `compare`), per-campaign + top/weak ads, reconciliation flags (ad rows vs Meta's account total; leads vs Meta's Results column), `truncated`, `fetchedAt`, evidence caveat, and the autopilot block (mode, TCPL, last run note, pending proposals with reasons, recent actions, held). A failed read is `{unknown:true, error}` — never zeros. Fed to: the brief (`_gather_campaign` → `campaign.feed`), every hub chat message (`agents_hub._director_chat` → `ads_feed_block()`), the idea generator (`eco_ideas`), and the Solomon → Eco share (`share_ad_results`, same fresh reads). Telegram reaches it with `api_get /api/daycare/ads/feed` (same `preset`/`since`/`until`/`compare` params, `fresh` default 1). The rule "the packet is the only source of ad numbers; cite window + source" lives in `forge-solomon/skills/solomon-adops-craft.md` (top skill — `learn()` never sees it) and in the packet itself. Ranges come from `forge rei/ads_range.py` (Meta's picker semantics, in the ad ACCOUNT's timezone — America/New_York — not the box's UTC). Test: `python3 test_daycare_ads_feed.py`.

## 14. Lane: Solomon · Revive — win back quiet leads (added 2026-09-30)

- **Why:** Replies only looks back 7 days and the Lead Desk only flags "needs a human" — paid Meta leads that stalled 2–5 weeks ago had nobody drafting a follow-up. Revive drafts the check-in so reviving a cold lead is one tap.
- **Trigger:** `daycare_revive.run_once` runs right after each Replies sweep in the same `daycare_replies` thread (no drafts-file race). No new loop/heartbeat. `FORGE_DAYCARE_REVIVE=0` or `forge_ops` clock-out stops it.
- **Picks (pure `pick`):** Lead Desk rows, contacted, not enrolled/lost/opted-out, quiet ≥7 d (≤90 d), or — only while the AI circuit is open — a parent text left unanswered at any age. Unanswered parents first, then warmest. ≤5 pending, ≤3 new/sweep, 2 attempts per contact ever, 14 d apart.
- **Draft:** one Claude call (Replies prompt + REVIVE task, creed/fact-sheet/voice loaded) when the AI is up; a voice-matched **template with zero Claude** when it is down — never waits on credits. Always ends with the STOP line; never states a seat, rate, date or offer.
- **Writes:** into the SAME `marcus_state/daycare_replies.json` drafts store (`revive:true`, `category:"revive"`, `autoEligible:false` — never auto-sent), so the Messages tab, Owner Actions ("Revive X — approve Solomon's check-in text") and `approve()` gates (live thread re-check, opt-out, DND, 8am–9pm ET) apply unchanged. When a parent texts back and the AI is up, the Replies lane supersedes the revive draft. One Telegram line per batch (daycare chat). Revive state: `marcus_state/daycare_revive.json`.
- **Starts honesty (same day):** `daycare_starts.extract` now records `confirmed` — whether the PARENT backed the date (their own text, or any parent text after our proposal). Owner Actions says "from your text — the parent has not replied since" when only we proposed it.
- **Verify:** `cd "forge rei" && python3 test_daycare_revive.py && python3 test_daycare_starts.py`; Owner Actions → daycare rows; `state: forge rei/marcus_state/daycare_revive.json`.

## 15. Ad Generator — concepts → images → PAUSED ad (Growth → Ad Studio, added 2026-10-17)

- **What:** the Ad Studio (`forge rei/daycare_ads_studio.py`, UI `forge rei/daycare_adgen.jsx`) upgraded in place. "Generate ad concepts" = one SMART Claude call (low effort) that drafts 3 concepts — angle, headline, copy, CTA, targeting note, image prompt A/B, format (1:1 | 9:16) and an **evidence** line citing the live packet window + source (forced to "Unknown — no live ad data" when the Pipeboard packet is Unknown). Text only: no credits, no Meta.
- **Prompt order:** creed → live ad packet (`daycare_growth.ads_feed_block`) → context brief + ad spec → brand rules `forge-daycare/skills/daycare-adgen-brand.md` (human-owned; loaded via `daycare_context.load_skill`, never through `_load_skills`, so no `learn()` can rewrite it) → the autopilot's stored market intel → image-prompt craft. Hard brand rule: **no children's faces**.
- **Images (one tap each):** `higgsfield_io.generate()` — quote → daily cap → engine → ledger → the concept's `assets[]` + an `adgen_image` action-log row. Engine: **REST** (`HIGGSFIELD_API_KEY`+`_SECRET`) unless its pool is known-empty, else the **Higgsfield CLI** on the owner's app credits, else none. Why REST is empty: the API credit pool is SEPARATE from the Plus app credits (verified 2026-10-17: 403 "Not enough credits" on REST, ~910 credits in the app). A REST 403 is remembered 30 min (`HIGGSFIELD_REST_EMPTY_TTL`) and the call falls back to the CLI.
- **CLI login (owner, once per machine):** `npm i -g @higgsfield/cli` → `higgsfield auth login` (browser OAuth) → `higgsfield workspace list` → `higgsfield workspace set <id>`. Check: `cd "forge rei" && python3 higgsfield_io.py --probe` (read-only: account, workspace, model list/get, a `generate cost` quote — never creates a job).
- **Guards / knobs:** `HIGGSFIELD_DAILY_CREDITS` (default 100) · Unknown cost refused unless the owner taps "generate anyway" (`confirmUnknown`), ≤5 such per day (`HIGGSFIELD_DAILY_UNKNOWN`) · `HIGGSFIELD_CLI_BIN` (else `higgsfield`/`hf` on PATH, version-checked) · `HIGGSFIELD_CLI_IMAGE_MODEL` (default `gpt_image_2_5`; `gpt_image_2` = the pricier text option) · `HIGGSFIELD_CLI_QUALITY` (medium) · `HIGGSFIELD_CLI_RESOLUTION` · `HIGGSFIELD_CLI_PARAMS` · `HIGGSFIELD_REST_MODEL` · `HIGGSFIELD_REST_CREDITS_PER_IMAGE` (REST has no quote → Unknown without it). One generation at a time. Ledger: `forge rei/marcus_state/higgsfield_ledger.json`.
- **Autonomy:** the only unattended image path is the autopilot's existing creative cycle (`attach_image` with no tap) — it goes through the same cap and is refused on Unknown cost. `create_ad` stays PAUSED-only. Solomon's chat sees the lane (`adGenerator` in his lanes block); the Telegram partner may api_get `/api/daycare/adgen/status` + `/api/daycare/nova/ideas` and propose concepts (`/api/daycare/nova/generate`); `/api/daycare/adgen/generate` is a 💸 tap card. **The Higgsfield MCP is for Claude sessions only** (interactive OAuth) — never the box.
- **Routes:** `GET /api/daycare/adgen/status` · `POST /api/daycare/adgen/quote` {ideaId, format, variant} · `POST /api/daycare/adgen/generate` {ideaId, format, variant, confirm:true, confirmUnknown?} · `/api/daycare/nova/image` now routes through the same guarded engine. Dashboard home: "Ad Generator" card next to Enrollment ads.
- **Verify:** `cd "forge rei" && python3 test_daycare_adgen.py`.
- **Telegram approval cards (2026-10-17, `forge rei/daycare_ads_tg.py`).** Shadow runs card every proposal into the daycare chat (✅ Apply → `approve` with a fresh guard · ❌ Skip → `reject` · receipt ↩ Undo). Concept cards (≤3 per ET day on the auto path, every 3 days; skipped while ≥3 are un-actioned, on clock-out or mode off): the concept + a preview image generated as source `auto` — quoted cost only, `HIGGSFIELD_AUTO_CREDITS` (default 25/day) on top of `HIGGSFIELD_DAILY_CREDITS`; no ready engine → text card + the next step, no Build button. ✅ Build PAUSED → `create_ad` (records campaign/ad set/ad ids + image) → LAUNCH card 🚀 $10/$20 per day → `daycare_ads_autopilot.launch()` (guards: clock-out, mode off, budget ∈ `FORGE_DAYCARE_ADS_LAUNCH_BUDGETS`, our recorded ids only, same ad account, image present, account health, no lifetime/CBO budget, idempotent, one launch/24 h unless you tap "launch a second", live total + this ≤ `FORGE_DAYCARE_ADS_MAX_DAILY`, dry-run → write → verify → rollback to PAUSED; logged in `actions[]`, ↩ Undo pauses all three). In shadow the creative loop no longer builds untapped test ads. Telegram partner: `POST /api/daycare/adgen/cards {n}` (💸 tap card). Read model: `GET /api/daycare/adgen/cards`. Kill: `FORGE_DAYCARE_ADS_CARDS=0`.
- **Build = Pipeboard inside the best existing ad set (2026-10-18).** ✅ Build (Telegram) and Ad Studio's "Build PAUSED ad" call `daycare_ads_studio.build()` → `build_paused`: picks the ad set with the most lifetime leads (then lowest CPL) in an OUTCOME_LEADS campaign — evidence = `daycare_growth.ads_report("maximum")` (Meta via Pipeboard, window + tz on the card) mapped to `pb.structure()`; no ad set with a lead → refused in plain words. The new creative copies that ad set's best ad (`get_creative_details`: `object_story_spec.page_id`, `instagram_user_id`, `link_data.link` / `asset_feed_spec.link_urls[].website_url`, `call_to_action.value.lead_gen_form_id`, `url_tags`) with the concept's headline, text, CTA (SIGN_UP / CONTACT_US / LEARN_MORE / GET_QUOTE; SIGN_UP / LEARN_MORE / GET_QUOTE with an instant form) and image (`ai_media` disclosed). Writes `upload_ad_image → create_ad_creative → create_ad` (PAUSED is hard-coded in `pipeboard_io.create_ad`), then verifies the ad exists, sits in that ad set and is PAUSED (if Meta shows it otherwise: re-PAUSE + error; nothing is deleted). Meta = `{account, campaignId, adsetId, adId, creativeId, imageUrl, via:"pipeboard", builtAt, evidence, blockers, launchable}`. Graph `create_ad` only when Pipeboard isn't configured. Launch also refuses if another ad in the ad set is switched on or turning the campaign on would start another ad set; CBO/lifetime/live-sibling blockers are on the concept + Built cards up front and the Launch buttons are withheld ("launch it in Meta yourself"). Live 2026-10-18: both daycare campaigns are CBO. Test: `python3 test_daycare_ads_build.py`.
- **Box engine (owner, once):** on the box `bash "forge rei/deploy/install-higgsfield-cli.sh"` (`--dry-run` first; pinned v1.2.2 + SHA-256) → add `HIGGSFIELD_CLI_BIN=/opt/forge/bin/hf` and `HIGGSFIELD_HOME=/root` to `/etc/default/forge-reios` → `systemctl restart forge-reios` → from the Mac `bash "forge rei/deploy/higgsfield-login-box.sh"` (browser OAuth through `ssh -L 8765`, then `workspace set <id>`). The service has no `$HOME`, so `higgsfield_io` passes `HIGGSFIELD_HOME` (else the passwd home) to every CLI call. A lapsed login → `status().cli.lapsed`, a plain next step, and ONE HQ Telegram alert per ET day when an auto job needed it. Verify: `python3 test_daycare_ads_tg.py`.

## 16. Daycare Gmail — read-only, daycare mail only (added 2026-10-18)

- **What:** `forge rei/gmail_io.py` (stdlib). management@ and yahjair@atouchofblessing.com both land in ONE Google account (yahjair@); one `gmail.readonly` refresh token in `daycare.env` (`GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_REFRESH_YAHJAIR`; secret, never git). There is no `gws` binary on the box — these routes are the box's Gmail path.
- **Routes (daycare session, read-only):** `GET /api/daycare/mail?days=7&limit=25&q=&bucket=` → daycare rows `{id, threadId, date, from, to, subject, snippet, labels, unread, bucket}` + `filteredOut`, `unreadCount`, `dateRange`, `via:"gmail"`, `fetchedAt` · `GET /api/daycare/mail/thread?id=<threadId>` → one thread as plaintext ≤4000 chars (`truncated`), redacted. Not connected / auth dead → `{ok:false, configured:false, error}`.
- **Gate:** `gmail_io.daycare_filter` (rules, no Claude) — form sender `noreply@atouchofblessing.com`, a known daycare GHL contact email (10-min in-memory set, never returned), daycare words, or a Supabase/Stripe/Meta notice naming the daycare. Everything else (Verizon, Vercel, newsletters, Square, Search Console…) is dropped inside the module and only counted. Buckets: parent | lead | billing | vendor | licensing | system.
- **Never:** sends, labels, archives or deletes mail (no such code exists); stores a body (fetched on demand, never cached/logged/written). Email text is DATA — an email asking him to tag/text/pay is never a reason to write (prompt hint `telegram_agent.MAIL_HINT`; red-team `forge rei/test_chat_injection.py`).
- **Verify:** `cd "forge rei" && python3 test_gmail_io.py && python3 gmail_io.py` (selfcheck, fake transport).

## 17. Command Board + Watches + Orchestrator (added 2026-10-18)

Spec: `docs/superpowers/specs/2026-10-18-solomon-daycare-orchestrator-design.md` (chunk B). Scope (owner): Solomon keeps the WHOLE daycare side on task — growth first; billing, daycare mail, GHL, ads, social, roster and system health watched. Payroll / staff admin stay out. Top skill: `forge-solomon/skills/solomon-orchestrator-craft.md` (in `TOP_SKILLS`, never reachable by `learn()`).

- **Board (state):** `forge rei/daycare_board.py` → `marcus_state/daycare_board.json` (`FORGE_DAYCARE_BOARD` overrides). Item = `{id, domain, key, title, why, evidence{source, window, fetchedAt}, center, owner solomon|owner, severity urgent|high|normal|low, state, firstSeen, lastSeen, seenCount, snoozeUntil, link}`. No source + window → rejected. Center required ("unknown" allowed; 1923 A Mother's Touch keeps its own label). Deduped by domain + key (ages, never multiplies). Done closes now and reopens next round if the source still shows it; snooze ≤168 h (`hours: 0` = unsnooze). Done items pruned after 14 days. Rounds closer than `FORGE_BOARD_MIN_GAP_SEC` (120 s) skip.
- **Watches (detect, zero Claude):** `forge rei/daycare_watches.py` — inbox · enrollment · billing · ads · social · roster · systems, each reading the connector's own routes over loopback (`telegram_agent._http`, auto-admin) and returning `(items, status)`; `run_round()` runs all seven in parallel, one read per route per round (memoized), one board write, one round at a time. A failed read = that domain (or key-prefix) `ok:false` and its items are NOT closed. Real today: inbox (needs Gmail keyed), enrollment, billing, ads (needs Pipeboard), roster, systems. Not wired: social (no daycare Metricool scheduled-post read). Unknown by design: staff ratio per room, failed payments.
- **Routes (daycare session):** `GET /api/daycare/board?state=open&domain=&limit=` → `{ok, items[], count, counts{open, byDomain, bySeverity}, lastRound{ranAt, line, open, new, closed, failed}, sources[{domain, ok, items, error?, notWired?, note?}], mailDesk, thirdPartyText, fetchedAt}` · `POST /api/daycare/board/run` → `{ok, ranAt, domains[], open, new[], closed[], urgent[], newItems[], line, thirdPartyText}` (or `{ok, skipped}`) · `POST /api/daycare/board/snooze {id, hours}` · `POST /api/daycare/board/done {id}`. All three POSTs are AUTO in his dashboard chat (`dash_live.AUTO_PATHS`); a board read or round whose payload says `thirdPartyText` (email subjects) taints the message → later writes become ✅ cards.
- **Chat:** live block hint "BOARD: api_get /api/daycare/board — your standing task list" (Solomon only); his lanes block carries board counts only (no titles); his registry `work` line adds "Board: N open (U urgent)".
- **Telegram:** `/board` (zero Claude, daycare chat or HQ) = top 8 open + counts; the partner's prompt points at the board.
- **Orchestrator (timer, DEFAULT OFF):** `forge rei/solomon_orchestrator.py`, thread `solomon_orchestrator`, started only when `FORGE_MARCUS=1` and `FORGE_SOLOMON_ORCH=1` (else heartbeat retired). Wakes every 300 s; a round every `FORGE_SOLOMON_ORCH_EVERY_MIN` (120) 07:00–18:59 ET + one at 20:00 ET. Skips: clock-out, `cost_tracker.over_ceiling("solomon")` (one HQ note per ET day), AI circuit open, a round already running. Digest (≤12 lines) to the DAYCARE chat only when something is new or newly urgent. Zero Claude; writes only the board file. Heartbeat `solomon_orchestrator` "Solomon · Orchestrator" — listed in his row's `hb` only when on. Bills to `solomon` (`cost_tracker.THREAD_ALIAS`).
- **Gates:** nothing outward anywhere in this section — no text, email, invoice, tag, ad change, login. Self-fixes stay in the chat AUTO tier. Kill: `FORGE_SOLOMON_ORCH=0`, clock-out, snooze, the cost ceiling (CLAUDE.md §2 exception).
- **Cost:** $0 Claude. Each round is GET reads only: the Gmail list + one metadata read per message (≤3 pages) + ≤15 header-only thread reads, the enrolled audit's GHL contact scan (≤1000 contacts), billing/children/classrooms per center, one Pipeboard feed pull (60 s cache), system/Stripe/GHL health. Round time not measured yet (Unknown).
- **Verify:** `cd "forge rei" && python3 test_daycare_board.py && python3 test_daycare_watches.py && python3 test_solomon_orchestrator.py && python3 test_daycare_board_ui.py`; on the box `curl -s localhost:7799/api/daycare/board | jq '{counts, lastRound, sources}'`.

## 18. Lane: Solomon · Calendar — tours and first days on one Google calendar (added 2026-10-31)

Code: `forge rei/daycare_calendar.py` (the lane) + `forge rei/google_cal_io.py` (the only Google door). Tests: `forge rei/test_daycare_calendar.py`, `forge rei/test_google_cal_io.py`. Spec: Brand Kit `docs/google-calendar/2026-10-30-tour-first-day-calendar-design.md` (not in this repo; not re-read here). CLAUDE.md section "Solomon · Calendar" has the same rules.

One line: every 15 minutes the lane works out which tour and first-day events should exist, compares that to its ledger, and creates, moves or removes events on one calendar. Zero Claude. One way only: an edit made inside Google does not flow back.

**Identity + triggers**

| Field | Value |
|---|---|
| Engine | `forge rei/daycare_calendar.py` (module, `run_forever(DAYCARE_GHL)`; `tick()` holds a non-blocking lock so two ticks never overlap) |
| Thread | `daycare_calendar` (`connector.main`, box only); heartbeat label "Solomon · Calendar"; makes no Claude call, so there is no cost bucket and no `THREAD_ALIAS` entry |
| Gate | `FORGE_MARCUS=1` (loops run on the box only) **and** `FORGE_DAYCARE_CALENDAR` != `0` (default on; `0` retires the heartbeat, `connector.py:5990`) |
| Interval | `FORGE_DAYCARE_CAL_INTERVAL`, default 900 s (`daycare_calendar.py:56`) |
| Clock-out | tick skipped on `forge_ops.paused()` |
| Mode | **QA by default.** `qa_mode()` is true unless `FORGE_DAYCARE_CAL_QA=0` (owner's switch to real families). QA mode touches only GHL contacts tagged `zz-calendar-qa` and writes only to `GOOGLE_CAL_ID_QA`; live mode uses `GOOGLE_CAL_ID` and skips QA/test contacts |
| Telegram | outbound only: one note per ET day to the daycare chat when a login is rejected, an email fails, or an event fails 3 tries (counts only, never a name); plus tour reminders (below). Loop-down alerts go to the daycare chat via `_WATCHDOG_BIZ`. No command |

**Reads**
- Tours: GHL contacts with tag `tour-scheduled` (not `tour-canceled`), one GET per contact. Fields Tour Date, Tour Time, Tour Location. Needs exactly one center tag, and the tag must agree with Tour Location, or the tour is held (listed on the status panel, no event).
- First days: the Starts state file (`marcus_state/daycare_starts.json`) read strictly, so a bad file raises and removes nothing. Included when the entry is `confirmed`/`sending`/`sent`/`failed`, or `proposed` with the owner's Add to calendar tap (`calendarAt`).
- Centers: `921` (A Touch of Blessings), `2318` (A Touch of Blessings 2 & 3), `1923 AMT` (A Mother's Touch, separate entity). **1923 tours are off** (`tourLabel` is None) until the tour check-in text has an A Mother's Touch version; the center is never guessed.

**Outputs / writes**
- Google Calendar events on ONE calendar, tagged `[921]` / `[2318]` / `[1923 AMT]`, one color per center, 30-minute tours. Stable event ids, so a lost ledger never duplicates. No guests, phone, email, last name, notes or payment type in any event. Past events are never created or moved.
- Ledger `marcus_state/daycare_calendar.json`: event ids, hashes, dates, links, plus a first name in `held`. Never a phone, email or token.
- Owner email (Resend, plain text): once a tour is really on the calendar, one email with the event link to `DAYCARE_CAL_NOTIFY_TO`, and one more if the tour moves (`[QA]` in the subject in QA mode). A blank address turns the email off. That address is the owner's: never a family's.
- Cleanup: 7 days after the event the names are stripped (`SCRUB_AFTER_DAYS`); a stripped row leaves the ledger after 90 days. A tour missing from the GHL search is re-read before its event is removed; a failed read never removes an event. Max 20 Google writes per tick.
- GHL writes happen only on the owner's taps below (Confirm tour, Cancel tour); the tick itself writes nothing to GHL.

**Reminders** (added 2026-10-31, plan `docs/plans/2026-10-31-solomon-calendar-watch.md`). Owner only: no event has guests, so no family is ever reminded by this lane (the GHL Tour Check-in SMS is separate and unchanged).
- Google popups in the event body (`_reminders`, `useDefault: false`): timed tour 1440 + 60 min, first day 900 min (9 AM the day before, in the calendar's own zone), all-day tour none. First-day `source` carries `|r1`, so rows written before this patch once.
- Telegram (`_remind`, after `_tour_emails` in each tick): for each timed tour whose ledger hash matches this tick's plan and whose start is in the future, one note at the nearest of 24 h / 2 h before. Text: `[QA] ` in QA mode, center tag, time, countdown, event link. **Never a name.** Sent with `telegram_io.send_biz("daycare", …, dedupe_key="cal-remind:{key}:{stage}:{start}")`, only when `_biz_chats()` has a daycare chat (unbound = skip, no HQ fallback). Quiet 9 PM-6 AM ET: held to the first tick after 6:00, skipped once the tour has started. `reminded` = `{stage, start}` in the ledger row, written only on an ok or dedupe-skipped result; a moved tour has a new start, so its stages reset. A failed or crashed send is retried next tick and never enters the tick's `error` (3 bad ticks would turn Solomon's row FAILED). Kill: `FORGE_DAYCARE_CAL_REMIND=0`.

**Calendar panel** (`DcsCalendar` in `daycare.jsx`, Daycare dashboard, replaced the old status card): status line (QA mode, updated, errors, held), then the next 14 days grouped Today / Tomorrow / weekday, each row with a center dot, Tour or First day chip, time in ET ("time not set" for an all-day tour), child first name + initial, Open link to the event, and "reminder sent". Shows an empty state in live mode too. Data: `view().upcoming`, built only from rows with a hash, not scrubbed, on the current mode's calendar, dated today or later. The name comes from `_WHO`, filled in memory by each tick and never saved; after a restart rows show without a name until the next tick.

**Solomon sees it:** `daycare_calendar` is in his `hb` (when `FORGE_DAYCARE_CALENDAR` != `0`), so the lane's health folds into his row. `week()` (next 7 days: mode, tour and first-day counts, up to 8 `MM-DD kind [tag]` entries, no names, under 300 chars) sits in `agents_hub._delegate_context("solomon")` before `adGenerator`, inside the 2500-char cut.

**HTTP** — daycare router, daycare session required

| Method | Route | Effect |
|---|---|---|
| GET | `/api/daycare/calendar` | `view()`: state file only, no network. `{mode, lastRunAt, error, events, failed, held, upcoming}`; each `upcoming` row is `{kind, date, time, center, tag, link, reminded, who}` |
| POST | `/api/daycare/tour/confirm` `{contact_id, date, time, center}` | Confirm tour: validates (center 921 or 2318, today to +120 days, Mon-Fri, 6:00 AM-6:00 PM), writes Tour Date / Tour Time / Tour Location, adds `tour-scheduled` (additive, never an upsert) and the center tags if missing, removes `tour-canceled`. Writing Tour Date arms the published Tour Check-in SMS, so **this tap is that text's approval** |
| POST | `/api/daycare/tour/cancel` `{contact_id}` | Removes `tour-scheduled`, adds `tour-canceled`, blanks Tour Date. The next tick removes the event |
| POST | `/api/daycare/starts/calendar` `{contact_id, on}` | Add to calendar / remove for a first day (`daycare_starts.set_calendar`) |

In QA mode all three taps refuse a contact that is not tagged `zz-calendar-qa` (turning a first day off is always allowed).

**Autonomy & gates**
- The lane itself is autonomous but internal: it only mirrors facts the owner already confirmed into a calendar only the owner sees. It never texts, never emails a family, never adds a guest.
- Auth: `google_cal_io` refuses any calendar id other than the two configured ones and any guest. The refresh token can edit every calendar of that Google account, which is why those two guards exist. A service account cannot write here (Workspace blocks outside editors).
- Fail-safe: login rejected (`CalAuthError`) stops the tick and tells the owner to re-consent. Calendar not connected sets `error` and does nothing else.
- Kill: `FORGE_DAYCARE_CALENDAR=0` + restart, clock-out, or blank `GOOGLE_CAL_REFRESH_YAHJAIR`. Blank `DAYCARE_CAL_NOTIFY_TO` kills only the email. `FORGE_DAYCARE_CAL_REMIND=0` kills only the Telegram reminders.
- Real mode needs the owner to set `FORGE_DAYCARE_CAL_QA=0`. Unknown (not verified): whether that has been done on the box today.

**Self-improvement:** none. **Chat & tasks:** none of its own; ask Solomon. His lanes block (`agents_hub._lanes_block`) carries `calendar` = `week()` since 2026-10-31.

**Cost:** zero Claude. Network: GHL reads (contact search, one GET per tagged contact), Google Calendar writes, one Resend POST per new or moved tour, at most two Telegram sends per timed tour.

**Verify it's alive**

```bash
cd "forge rei" && python3 test_daycare_calendar.py && python3 test_google_cal_io.py
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="daycare_calendar")'
curl -s localhost:7799/api/daycare/calendar | jq '{mode,lastRunAt,error,events,failed,held,upcoming}'   # needs a daycare session
```

Healthy: `mode` matches what the owner intends (`qa` until the switch), `lastRunAt` under ~20 min old, `error` null, `failed` 0.

## 19. Keys, MCPs and task file

(Numbered 19 because §10 above is already the Replies lane and other docs link to it.)

### (a) Environment variables Solomon's lanes read

Names only, never values. "Process env" = set in the service environment (the box unit; Mac shell for local runs). "daycare.env" = `forge-daycare/config/daycare.env` (template: `forge-daycare/config/daycare.env.example`), read through `daycare_supabase._read_env()`. Where a module uses `_pick`, the process env wins and `daycare.env` is the fallback, so those names work in either place. Collected by grep of `daycare_director.py`, `daycare_replies.py`, `daycare_leads.py`, `daycare_starts.py`, `daycare_calendar.py`, `google_cal_io.py`, `solomon_orchestrator.py`, `daycare_ads_autopilot.py`, plus `daycare_revive.py` and `daycare_board.py` for their kill switches.

| Name | Lane | Where set |
|---|---|---|
| `FORGE_MARCUS` | all loops (box gate, must be `1`) | process env |
| `SOLOMON_ANTHROPIC_API_KEY`, `ANTHROPIC_API_KEY` | brief, chat, Replies (`_solomon_key()`; falls back to the agency, then wholesale key) | process env |
| `FORGE_SMART_MODEL` | Replies model default (`review_agent.SMART_MODEL`) | process env |
| `FORGE_SOLOMON_BRIEF`, `FORGE_SOLOMON_BRIEF_EVERY_H`, `FORGE_SOLOMON_BRIEF_TOKENS`, `FORGE_SOLOMON_LEARN_EVERY`, `FORGE_SOLOMON_LEARN_GAP_MIN` | brief | process env |
| `FORGE_DAYCARE_REPLIES`, `FORGE_DAYCARE_REPLIES_INTERVAL`, `FORGE_DAYCARE_REPLY_MODEL`, `FORGE_DAYCARE_REPLY_GRACE_SEC`, `FORGE_DAYCARE_REPLY_MAX`, `FORGE_DAYCARE_REPLY_AUTO`, `FORGE_DAYCARE_AUTO_CAP` | Replies | process env |
| `FORGE_DAYCARE_REVIVE` | Revive | process env |
| `FORGE_DAYCARE_LEADS`, `FORGE_DAYCARE_LEADS_INTERVAL` | Leads | process env |
| `FORGE_DAYCARE_STARTS`, `FORGE_DAYCARE_STARTS_INTERVAL` | Starts | process env |
| `FORGE_DAYCARE_ADS`, `FORGE_DAYCARE_ADS_MODE`, `FORGE_DAYCARE_ADS_HOUR`, `FORGE_DAYCARE_ADS_TCPL`, `FORGE_DAYCARE_ADS_MAX_DAILY`, `FORGE_DAYCARE_ADS_MAX_ACTIONS`, `FORGE_DAYCARE_ADS_LEARN_PREFIX`, `FORGE_DAYCARE_ADS_CREATIVE`, `FORGE_DAYCARE_ADS_KEYWORDS`, `FORGE_DAYCARE_ADS_LAUNCH_BUDGETS`, `FORGE_TZ_OFFSET` | Ads | process env (`FORGE_DAYCARE_ADS_MODE` is only a default: the saved mode in `daycare_ads_auto.json` wins) |
| `PIPEBOARD_API_TOKEN`, `PIPEBOARD_AD_ACCOUNT_ID`, `PIPEBOARD_MCP_URL` | Ads (Meta reads/writes through Pipeboard) | daycare.env |
| `APIFY_TOKEN` | Ads competitor read | dropship env (read in `dropship_adspy.py`), not daycare.env |
| `FORGE_SOLOMON_ORCH`, `FORGE_SOLOMON_ORCH_EVERY_MIN` | Orchestrator | process env |
| `FORGE_DAYCARE_BOARD`, `FORGE_BOARD_MIN_GAP_SEC` | Board (state path override, minimum round gap) | process env (named in §17, not re-grepped) |
| `GHL_API_KEY`, `GHL_LOCATION_ID` | Replies, Leads, Starts, Calendar, Revive (the daycare GHL client) | daycare.env |
| `FORGE_DAYCARE_CALENDAR`, `FORGE_DAYCARE_CAL_INTERVAL` | Calendar | process env |
| `FORGE_DAYCARE_CAL_QA` | Calendar (unset or anything but `0` = QA mode) | daycare.env or process env (`_pick`) |
| `GOOGLE_CAL_ID`, `GOOGLE_CAL_ID_QA`, `GOOGLE_CAL_REFRESH_YAHJAIR` | Calendar | daycare.env or process env (`_pick`) |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` | Calendar OAuth client (shared with the Gmail reader, §16) | daycare.env or process env (`_pick`) |
| `RESEND_API_KEY`, `RESEND_FROM`, `DAYCARE_CAL_NOTIFY_TO` | Calendar tour email | daycare.env or process env (`_pick`) |
| `HIGGSFIELD_*` | Ad Generator images (§15) | see §15 (not re-grepped) |

The master key file `~/.agent-keys/master.env` is not read by any of these modules; this card does not list or open it.

### (b) MCPs relevant to a daycare agent

Suggested for Claude sessions that work on Solomon. **Not read from code**: the connector never calls an MCP; it uses direct HTTP clients.

- Supabase MCP, project ref `eqblpbeqothkpyqiafzs` (daycare DB; the connector reaches it through `daycare_supabase.py`, not through the MCP).
- GoHighLevel MCP (daycare location only; never cross into the wholesale account).
- Google Calendar MCP (read the calendar the Calendar lane writes; the lane uses `google_cal_io`, not the MCP).
- Gmail MCP (read-only reading of daycare mail; the box path is `gmail_io.py`, §16).
- Stripe MCP (daycare billing reads).
- Resend is an HTTP API, not an MCP: `daycare_calendar._send_email` posts to `https://api.resend.com/emails`.

### (c) Task file

This card is Solomon's canonical task file: what he does, which lane does it, what gates apply, how to verify. Runtime is unchanged: the code still loads the creed, top skills and playbook from `forge-solomon/skills/` (and `forge-daycare/skills/` for the Replies/Ads/Ad Studio lanes). This is a documentation pointer only, no runtime change.

## 20. Lane: Solomon · Pipeline — the two GHL enrollment boards (added 2026-11-01)

Written from code 2026-11-01 (`forge rei/daycare_pipeline.py`). Not in his `hb` list: a sick
loop shows on `/api/system/health` and alerts the daycare Telegram chat (`connector._WATCHDOG_BIZ`).

| | |
|---|---|
| Boards | `enrollment` = GHL "Enrollment" (A Touch of Blessings: 921 N 18th + 2318 Cecil B. Moore) · `amt` = GHL "A Mother's Touch" (1923 Cecil B. Moore — **separate legal entity**). Never summed, never mixed. |
| Stages | New Lead → Contacted → Tour Scheduled → Application Sent → Enrolled → Lost (same on both; ids resolved live by pipeline name, hard-coded fallback) |
| Business tags | AMT = `entity-amt` or `loc-1923-cecil-b-moore`; ATOB centers `entity-atob`, `loc-921-n-18th`, `loc-2318-cecil-b-moore` |
| Who moves stages | Daily n8n workflow `R5knymRU7t30uR8x` (9 PM ET, outside this repo): forward only, quoted evidence line, nothing past Contacted without a parent reply, Enrolled needs high confidence or the `enrolled` tag; moves AMT contacts into their own pipeline. **Lost = tag `pipe-propose:lost`, moved only by the owner's Approve tap.** This repo never moves a stage on its own. |
| "Enrolled" truth | A child row in the production roster; the `enrolled` GHL tag mirrors it. A Family Contact Form (emergency-contact PDF, brand `atob`/`amt`, `forge rei/daycare_family_forms.py`) = paperwork done, **not** enrolled in the app. |
| State | `marcus_state/daycare_pipeline.json` (ATOB) · `marcus_state/daycare_pipeline_amt.json` (AMT) |
| Routes | GET `/api/daycare/pipeline[?board=amt]` (state only) · POST `/api/daycare/pipeline/{move,move-all,refresh}` with body `board` (default `enrollment`) |
| Gates | Owner's session-gated tap; the card + stage must belong to THAT board, and a live GET of the opportunity must still show that board's pipeline before the PUT (fail-closed). In chat a pipeline move is a ✅ tap card. Kill `FORGE_DAYCARE_PIPELINE=0`. |
| His context | Chat `_lanes_block` → `pipeline` = `daycare_pipeline.counts()` (per board: total, proposals, byStage, stale, missing — no names). Seed skill `solomon-enrollment-pipelines.md` (loaded with his other `solomon-*` skills). |
| Test | `forge rei/test_daycare_pipeline.py` |
