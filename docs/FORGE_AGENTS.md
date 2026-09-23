# FORGE AI — Agents (audit 2026-09-22)

What runs, where, on what trigger, what it may do on its own, and how much of the spec's
Agent Control Center (spec §9) each agent can already report. Code refs are relative to
`forge rei/`.

> **Headline:** every loop below is running on the box 24/7 — but **every Claude call has failed
> since 2026-08-01** (Anthropic credit balance exhausted). Loops that need Claude (scoring,
> drafting, underwriting, briefs, `learn()`) are running blind or on fallbacks. Heartbeats wrap
> the loop, not the Claude call — so since WP-A (2026-09-22) AI health is a separate signal:
> `/api/system/health` `ai` block, an Owner Actions FIX row, and one Telegram alert. Top-up =
> owner action (P0-1).

---

## 1. Loops on the box (`connector.main()`, only when `FORGE_MARCUS=1`)

| Thread | Module | Cadence / knob | Claude? | Outward action + gate | Heartbeat | Live state 09-22 |
|---|---|---|---|---|---|---|
| `scout` | `scout_triage.py` | 180 s `FORGE_SCOUT_INTERVAL` | yes (Haiku scoring, learn, weekly audit) | GHL tag + Hot-stage for **asap** leads only (internal, reversible, `FORGE_SCOUT_AUTOTAG_HOT` / `_AUTOPIPE_HOT`); others wait for approval | `scout` | green; AI scoring failing (credits) |
| per-lead (unnamed) | `_auto_screen` → `marcus_screening` → ACE | event, `FORGE_SCREEN_AUTO=1` | yes | **ACE supervised/full auto-texts sellers** (default **off**, cap 3/10/day, `sms_guard`) | none | ACE mode: off (default) |
| `followup` | `followup.py` | 1800 s | **yes** (drafts via `_ai_draft`) | proposals only; **autopilot** can auto-send re-engage bumps (opt-in, off by default) | `followup` | green |
| `atlas` | `deal_prep.py` | 900 s | yes | none (numbers internal) | `atlas` | green; AI failing |
| `solomon` | `daycare_director.py` | 900 s tick, brief every 24 h | yes | none | `solomon` | **RED** — credits + invalid Meta token; last brief 2026-08-01. Failed briefs now back off 15 m → 6 h (WP-A); a rejected Meta token is cached as not-connected |
| `midas` | `dropship_director.py` | off (`FORGE_DROPSHIP_BRIEF=0`) | yes | none | retired | off by design (archive) |
| `do_today` | `do_today.py` | off (`FORGE_TODAY_LOOP=0`) | **yes** (legit_check + marcus_lead) | email to operator | retired | off — **also disables** scheduled legit audit + Marcus lead directives (undocumented coupling) |
| `marcus` | `marcus_engine.py` legacy SMS loop | off (`FORGE_MARCUS_SMS`) | yes | auto-send hard-disabled | `marcus_sms` | off by design |
| contract (unnamed) | `_contract_poll_forever` | 600 s | no | GHL stage move on real DocuSign signature | `contract` | green |
| `telegram` / `telegram_agent` | `telegram_io.py` | long-poll | yes (chat) | seller SMS only after ✅ confirm tap | both | green |
| watchdog (unnamed) | `_watchdog_forever` | 300 s | no | Telegram alert on red/recover — **never restarts** | `watchdog` | green |
| `brief` | daily_brief 08:00 · daily_recap 18:00 · **Orion** CEO brief 07:00 · sync monitor | 300 s check | **yes (Orion)** | Telegram to operator | `daily_brief` | green; Orion failing (credits) |
| `daycare_leads` | `daycare_leads.py` (WP-E) | 900 s, `FORGE_DAYCARE_LEADS` | no | operator Telegram ping only; GET-only on GHL | `daycare_leads` | new 2026-09-22 |
| `graphify` | `graphify_build.py` | 30 min | no | none | `graphify` | green |
| portal | `PortalHandler` | always (not FORGE_MARCUS-gated) | no | client submits edit request/message | none | up |
| skill_forge (per event) | `skill_forge.py` | bus notifier | yes | vault proposal; adoption needs tap | none | — |

**Outside the process (systemd timers):** `forge-daily-learn` 20:00 ET → learn/run for scout,
screening, style, review, dyson, eco (all failing: credits) · `forge-review` Mon (unit quoting fixed in WP-F d141618, box confirmed
2026-09-22; review failures now return the real error) · `forge-autopull` 60 s (deploys).

## 2. Agent roster

| Agent | Business | Purpose | Autonomy |
|---|---|---|---|
| **Scout** | Wholesale | find/score/bucket seller replies, HOT auto-tag, weekly missed-leads audit, hands asap/warm to Marcus | never texts |
| **Marcus** (screener + SMS drafter + chat + lead directives) | Wholesale | call-ready screening report; every seller text is a proposal; `_no_price_over_text` code guard | proposals only (gate on) |
| **ACE** | Wholesale | per-thread state machine; reply-vs-escalate; call-ready queue | **modes off/shadow/supervised/full — supervised/full auto-send.** Default off. Documented in CLAUDE.md §2 (2026-09-22). |
| **Autopilot** | Wholesale | auto-send routine re-engage bumps | opt-in, off by default; 7 gates |
| **Atlas** | Wholesale | underwriting, offer anchors, negotiation call card | internal only — **no UI** (`/api/prep/*` unused by UI) |
| **Dyson** | Agency | plans/ships client site edits | ships only on approval |
| **Eco** | Agency | ad strategy / Meta analysis | creates PAUSED ads only on approval |
| **Solomon** | Daycare | single operating brief for the center (absorbed Nora/Nova) | proposes only |
| **Midas** | Dropship | store director | **archive** |
| **Orion** | Cross-business | daily "attack today" CEO brief on Mission Control | Telegram push optional. In CLAUDE.md §5 and the hub roster (2026-09-22). |
| style_agent / review_agent / skill_forge / agent_coach | Cross | learn operator voice, weekly review, propose skills, share insights | internal |

Retired (2026-07-25): Nora, Nova, Hawk, Blaze, Otto — skills merged; leftover alias routes + `/opt/forge/retired-2026-07-25` remain.

## 3. Spec §9 registry — what each agent can report today

`Y` available · `~` derivable · `N` missing

| Agent | Status | Last Run | Last **Success** | Next Run | Done | Failed | Error count | Current task | Dependency health |
|---|---|---|---|---|---|---|---|---|---|
| Scout | Y hb | Y | Y | ~ | ~ | N | ~ consecutive only | N | ~ |
| Marcus screener | N | ~ | ~ | N (event) | ~ | N | ~ | N | ~ |
| Atlas | Y hb | ~ | ~ | ~ | ~ | N | ~ | N | ~ |
| Follow-up | Y hb | Y | ~ | ~ | ~ | N | ~ | N | N |
| ACE / Autopilot | ~ mode | ~ | ~ | N | Y sentToday | ~ | N | N | ~ |
| Dyson / Eco | ~ key present | ~ | N | N | ~ | N | N | ~ | ~ |
| Solomon | Y hb | Y | ~ | ~ | ~ | N | ~ | N | Y (presence only) |
| Orion | N | Y | ~ | ~ | ~ | N | ~ | N | ~ |
| daily_brief / recap | ~ hb | Y | Y | Y | N | N | N | N | ~ |
| Contract poller | Y hb | Y | ~ | ~ | ~ | ~ | ~ | N | Y |

**Gaps for the Agent Control Center:** last-successful-run, cumulative error count, failed-task
count, durable current task, **AI dependency health** (would have caught the 51-day outage).
**Shipped in wave 1:** heartbeats carry `lastSuccessAt` / `errorsTotal` / `lastError`; AI health
is recorded at both Claude call sites; `agents_hub.registry()` serves all of it at
`/api/agents/registry`. Still missing: failed-task count history, durable current task (P1-9).

## 4. Statuses (spec) → existing signals

| Spec status | Source |
|---|---|
| RUNNING | heartbeat fresh + pixel_office job running |
| IDLE | heartbeat fresh, no job |
| WAITING FOR APPROVAL | pending items in that agent's queue (Marcus proposals, Scout pending tags, agency approvals, skill_forge) |
| DEGRADED | errStreak ≥ 1, or the agent uses Claude and `forge_heartbeat.ai_health().hard` |
| FAILED | heartbeat red (stale or errStreak ≥ 3) |
| DISABLED | `forge_heartbeat.retire()` / env knob off / archived business |

## 5. Rules that bind every agent (unchanged)

Creed per business (`agent_creed.py`, un-rewritable by `learn()`) · propose → approve → execute ·
one agent per outward channel · never a price by text · reply to sellers only · secrets never
logged. New agents: use the `forge-self-improving-agent` skill; ask first whether a brief section
of an existing agent does the job.
