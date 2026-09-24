# Solomon — Executive Director (the daycare's one agent)

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-09-24.

Solomon is the daycare's ONE agent. He owns three lanes, each with its own loop, heartbeat
and state file — one identity, one Agent Control Center row, one chat:

| Lane | Engine | Loop / heartbeat | What it does | Section |
|---|---|---|---|---|
| **Brief** (director) | `forge rei/daycare_director.py` | `solomon`, 900 s tick, brief 24 h | the ranked operating brief | §1–9 |
| **Solomon · Replies** (the Reply Desk) | `forge rei/daycare_replies.py` | `daycare_replies`, 300 s | drafts every parent text-back; the owner taps send | §10 |
| **Solomon · Leads** (the Lead Desk) | `forge rei/daycare_leads.py` | `daycare_leads`, 900 s | GET-only enrollment-lead sweep, $0 | §11 |

The lanes report to him: `reply_desk_state()` / `lead_desk_state()` (`daycare_director.py:123`/`:146`)
feed the brief (`replyDesk` / `leadDesk`), his chat (`agents_hub._lanes_block`) and his registry
row. Until 2026-09-24 the Reply Desk had its own roster row (`daycare_replies`) and the Lead Desk
its own card; both were folded in here.

## 1. Identity

| | |
|---|---|
| Business | Daycare (A Touch of Blessings) · hub id `solomon` · emoji 🏛️ |
| Job | Reads the whole center and writes ONE ranked operating brief: Attention Now, Enrollment, Money, People, Roster, Follow-ups, Campaign health, Competitor read, Creative, Delegations. Owns enrollment. Absorbed Nora + Nova (2026-07-25), then the Reply Desk + Lead Desk as his Replies + Leads lanes (2026-09-24). |
| Engine | `forge rei/daycare_director.py` → `SolomonEngine` (`daycare_director.py:235`), connector global `SOLOMON` |
| Seed folder | `forge-solomon/` (skills in `forge-solomon/skills/`) |

## 2. Triggers

**Scheduled loop** (the brief lane; the other two lanes: §10, §11)

| Field | Value |
|---|---|
| Thread | `solomon` (`connector.main`) |
| Gate | `FORGE_MARCUS` != `0`; no other on/off knob, never retired |
| Tick | 900 s, hardcoded (`daycare_director.py:76`) |
| Brief cadence | `FORGE_SOLOMON_BRIEF_EVERY_H`, default 24 (`:69`) |
| Failure backoff | 15 min doubling to 6 h (`:925`) |
| Clock-out | tick skipped on `forge_ops.paused()` (`:962`) |
| Session | builds under `daycare_supabase.BRIDGE.autoadmin_session("127.0.0.1")` |
| Heartbeat | `solomon` every tick (`:990`) |

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

**Bus roles he answers to** — `BUS_ROLES` (`daycare_director.py:64`): `solomon`, `family-comms`, `enrollment`, `ads`, `growth`, `nora`, `nova`, `daycare_replies`, `daycare_leads`. `_read_bus_inbox` (`:420`) pulls unread (≤10 per role, plus `all`), marks them read, feeds the newest 10 into the brief as `busDelegations`.

**Handoffs in:** bus messages to any role above · hub tasks (including any still filed under the retired `daycare_replies` id — `agents_hub._FOLDED`) · his Leads lane feeds `leadDesk` and his Replies lane feeds `replyDesk` into the brief.

**UI:** `window.DaycareDirector` (route key `Director`, `app.jsx:65`; page title "Solomon") — via the Agents hub Console tab, not the Daycare sidebar · Agent Control Center `solomon` (all three lanes) · Agent Office (Daycare room) · "Solomon · Leads" card on the Daycare Dashboard.

## 3. Reads / context load order

`build_brief` (`daycare_director.py:555`):
1. inline role + evidence rule (backstop) — names both live lanes; the brief itself never drafts family text
2. `north_star`
3. `daycare-context.md` [:3500] + `enrollment-ad-agent.md` [:4000] (`daycare_context.py`)
4. creed `agent_creed.block("daycare")` → `daycare-evidence-discipline.md`
5. TOP SKILLS (`TOP_SKILLS`, `:291`): `solomon-decision-loop.md`, `solomon-director-craft.md`, `solomon-systems-craft.md`, `solomon-roster-craft.md`, `solomon-adops-craft.md` (+ any other `solomon-*` non-playbook), seed then vault, never truncated
6. PLAYBOOK (`_playbook_only`): seed `solomon-playbook.md` + vault `Skills/solomon-playbook.md` [:4000]
7. last 2 vault `Reports/daycare/*.md` [:1200 each]
8. user JSON: metrics, alerts, roster, blasts, opt-outs, campaign, competitor, busDelegations, connectedSystems (presence only), `leadDesk` (Solomon · Leads — KPIs + top 10 needs-human), `replyDesk` (Solomon · Replies — pending drafts, escalations, oldest pending age, last sweep, error)

## 4. Outputs / writes

- `marcus_state/solomon.json`.
- Vault `Reports/daycare/brief-YYYY-MM-DD.md` per brief, `Skills/solomon-playbook.md` on learn.
- Bus: `solomon→all` status per brief · one `handoff` per delegation to `role.lower()` (≤8) · learn status · his Leads lane's owner alerts (`solomon→operator`, §11).

## 5. Autonomy & gates

- Read-only, propose + delegate. Never texts a family, invoices, launches ads, or writes the DB. His Replies lane drafts family texts, but only the owner's tap sends one (§10).
- Only autonomous writes: brief notes, playbook, bus notes (plus each lane's own state file).
- Kill: `FORGE_MARCUS=0`, clock out, or no key. Key: `SOLOMON_ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY` → agency → wholesale (`_solomon_key`, also used by the Replies lane and his chat).
- Knob `FORGE_SOLOMON_BRIEF_TOKENS` 5000.

## 6. Self-improvement

- `_maybe_learn` every tick: `FORGE_SOLOMON_LEARN_EVERY` (8 briefs) **and** `FORGE_SOLOMON_LEARN_GAP_MIN` (45 min) → about every 8 days at the 24 h cadence.
- Manual: POST `/api/daycare/director/learn` (also `/family/learn`, `/adops/learn`). Not in `daily_learn.sh`.
- Sees only the playbook (`_playbook_only`) — creed and top skills are untouchable.
- The lanes have no `learn()` loop (§10, §11).

## 7. Chat & tasks

- `/api/hub/chat {agentId:"solomon"}` → `agents_hub._director_chat` (`agents_hub.py:301`), key from `daycare_director._solomon_key()`.
- Prompt: role + blurb → creed → `daycare_context.context_block()` → latest brief [:3500] → top skills (**empty** — `daycare_director` has no `top_skills_text`) → `playbook_text(4000)` → **YOUR LIVE LANES** (`_lanes_block` → `_delegate_context("solomon")`: Replies + Leads state, [:2500]) → `open_tasks_block("solomon")` → `caveman.block()`. ≤700 tok.
- Tasks reach him twice: `open_tasks_block` in chat + the bus `task` message read at brief time.

## 8. Cost

Claude: yes — 2 calls per brief (competitor read + brief) + learn. Bucket `solomon` on the loop; `operator` for manual runs/chat/`eco/ideas`; `telegram` for Telegram chat. His lane threads bill to `solomon` too (`cost_tracker.THREAD_ALIAS`): the Replies lane's drafts (§10) and the Leads lane ($0 today).

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="solomon")|{status,lastSuccessAt,nextRun,lastError,pendingApprovals,work,detail,heartbeat}'
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="solomon" or .loop=="daycare_replies" or .loop=="daycare_leads")'
# needs a daycare session (auto-admin via loopback/Serve):
curl -s localhost:7799/api/daycare/director/status | jq '{aiReady,creedLoaded,topSkills,briefCount,lastBriefAt,nextBriefAt,failStreak}'
```

His registry row (`agents_hub.registry`): heartbeats `solomon` + `daycare_replies` + `daycare_leads` (a sick lane loop turns his status DEGRADED/FAILED and `lastError` names the lane), approval queue = pending Reply drafts (`WAITING FOR APPROVAL`), `work` = briefs · Replies drafts waiting · Leads needing a human.

## 10. Lane: Solomon · Replies — the Reply Desk (parent-reply drafter, added 2026-09-23)

His `family-comms` lane made concrete: every 5 min, drafts the next text back to any parent/guardian who texted the daycare GHL number and is owed a reply, in the center's real texting voice, grounded in the verified fact sheet. **Draft-only — the owner's tap sends.**

**Identity + triggers**

| Field | Value |
|---|---|
| Engine | `forge rei/daycare_replies.py` (no engine object — pure functions + a state file), self-check `forge rei/test_daycare_replies.py` |
| Thread | `daycare_replies` (`connector.main`, started next to the Leads thread); bills to `solomon` |
| Gate | `FORGE_MARCUS` != `0` **and** `FORGE_DAYCARE_REPLIES` != `0` (default on; `0` retires the heartbeat) |
| Tick | `FORGE_DAYCARE_REPLIES_INTERVAL` 300 s · ≤`FORGE_DAYCARE_REPLY_MAX` 8 Claude calls + ≤40 thread GETs per sweep |
| Clock-out | whole sweep skipped on `forge_ops.paused()` |
| Heartbeat | `daycare_replies`, label "Solomon · Replies" |
| Model | `FORGE_DAYCARE_REPLY_MODEL`, default `claude-sonnet-5` · key = `_solomon_key()` |
| Knobs | `FORGE_DAYCARE_REPLY_GRACE_MIN` (5) · `FORGE_DAYCARE_REPLY_MAX` (8) · `FORGE_DAYCARE_REPLIES_INTERVAL` (300) |
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

- **Draft-only.** Every row is a proposal; nothing sends without `/api/daycare/replies/approve`. Auto-send is NOT built; turning it on is an operator decision.
- **Yields to the GHL automations first** (`gate()`, pure, no Claude): a thread is skipped when —
  - the last message is already outbound (a workflow or a person answered);
  - the parent sent STOP/HELP/START/etc. — the carrier/GHL keyword auto-replies own those words;
  - the parent has opted out or is DND — permanent, never revisited;
  - a fresh website lead is still inside the speed-to-lead window (speed-to-lead tag on and the first touch not out within 15 min, or the overnight `speed-to-lead-queued` → 8am flush) — the workflow owns that first text, not this;
  - the inbound is younger than `FORGE_DAYCARE_REPLY_GRACE_MIN` — lets a workflow's stop-on-response or live staff typing back go first;
  - the thread isn't SMS, or the inbound is older than 7 days (the Leads lane's job, not this one's).
- **Code-level draft flags** (`flags()`, always run, never bypassable by the model): a phone number not on the fact sheet (`unverified_phone`), a dollar figure (`money`), an emoji, or a draft over ~3 SMS segments (`long`).
- **`approve()` re-checks the live thread**, not the cached draft: refuses outside 8am–9pm ET, refuses and retires the draft if anyone (staff or a workflow) replied since it was written, refuses if the parent opted out in the meantime. One `daycare_ghl.send_sms` + `action_log` (as `solomon`).
- **`escalate`** category (safety, custody, medical, complaint, billing dispute) never gets a substantive draft — only a short holding line; the owner calls.
- Kill: `FORGE_DAYCARE_REPLIES=0`, clock out, `FORGE_MARCUS=0`, or no Anthropic key. A billing/auth error from Anthropic aborts the sweep mid-way (shows on the heartbeat) rather than silently drafting nothing.

**Self-improvement:** none. `daycare-voice.md` and `daycare-parent-reply.md` are owner-edited skill files (mtime hot-reload via `daycare_context.load_skill`), not a `learn()` loop — they don't drift on their own.

**Chat & tasks:** Solomon answers (§7) with the lane's live state in his prompt. No dedicated task queue; a task still filed under the retired `daycare_replies` id shows in Solomon's open-tasks block.

**Cost:** Claude — up to `FORGE_DAYCARE_REPLY_MAX` (8) Sonnet 5 calls per 5-min sweep, only for threads that pass `gate()`. Bucket `solomon` (thread `daycare_replies` aliased in `cost_tracker.THREAD_ALIAS`).

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
| Heartbeat | `daycare_leads`, label "Solomon · Leads" (`daycare_leads.py:660`) |
| Telegram | outbound only (owner pings, "Solomon · Leads — …"). No command, no name trigger — ask Solomon |

**HTTP** — daycare router, session-gated

| Method | Route |
|---|---|
| GET | `/api/daycare/leads` → `view()` (state file only, no network) |
| POST | `/api/daycare/leads/stage` → `set_stage` (LOCAL mark, never written to GHL) |

**Bus:** sends `solomon→operator` alerts (contact id + reason codes only; was `daycare_leads→operator` before 2026-09-24). Reads nothing.

**UI:** "Solomon · Leads" card on the Daycare Dashboard (`daycare.jsx:248`, `DldLeadDesk`).

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
