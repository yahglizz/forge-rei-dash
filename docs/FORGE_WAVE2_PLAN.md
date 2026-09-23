# WAVE 2 GAPS — FORGE AI vs master spec (2026-09-22)

Read-only audit at HEAD `1137469`. Paths are relative to `forge rei/` unless they start with `docs/`, `CLAUDE.md` or `NORTH_STAR.md`.
I checked each status against the code with grep, not just the docs. Tests re-run today: offline suite (all `test_*.py` except `test_mode.py` and the 4 connector-importing tests) = **33 pass / 0 fail**. The working tree stayed clean afterward.

Legend: **DONE** · **PARTIAL** · **MISSING** · **OWNER** (needs money, keys, or a live-policy decision)

---

## 1. Spec requirement → status

### §3/§23 Repository, §4 scope, §12 24/7, §24 docs
| Req | Status | Evidence |
|---|---|---|
| Backup / checkpoint | DONE (box-local only) | `deploy/backup_state.sh:2`, `deploy/setup_droplet.sh:147-151`. Off-box copy = OWNER |
| Secrets not exposed | DONE | brain `.md`-only read (`test_brain_live.py`). PAT rotation = OWNER |
| 3 active workspaces; archive is recoverable | DONE | `business_scope.py:37,64`; `app.jsx:199-205`; `archived.jsx:44`; `test_business_scope.py` |
| Agents page | DONE | `agents_hub.py:704` `registry()`; `connector.py:2871` |
| Owner Actions | DONE | `owner_actions.py:423` `build()`; stale collapse `:63`; `connector.py:2863` |
| Approvals surface | PARTIAL | only an APPROVE filter chip (`owner_actions.jsx:15-17`). No Action/Agent/Reason/Risk/Expected, no Reject/Edit (see §19) |
| Automation Health | DONE | `connector.py:2654` `/api/system/health`; `app.jsx:126` |
| KPI / Financial Overview | PARTIAL | Costs view (`app.jsx:127`) covers AI spend only. MRR is in `agency_io.py:232-254`. No cross-business P&L |
| 24/7 off the Mac | DONE | box systemd; `docs/FORGE_CURRENT_ARCHITECTURE.md` §7 documents what runs locally vs on the box |
| 6 required docs | DONE | `docs/FORGE_*.md` (stale spots in §2 below) |

### §6 Agency
| Req | Status | Evidence |
|---|---|---|
| Prospecting agent, continuous, on the box | MISSING + OWNER | No prospect module on the box: `grep -il prospect *.py` only hits `agency_calls` / `daycare_ghl` / `owner_actions`. LeadScraper (Apify) runs on the Mac only. Running it on the box needs an Apify key and budget there |
| Prospect record fields | PARTIAL | `agency_callsheet.py:80-85` stores name/company/phone/email/website/location/pain/status/note/last_called. Missing: category, website quality, potential offer (set only on escalate, `:395-405`), next action, dated last contact (`last_called` is `%m/%d %H:%M` with no year, `:252`) |
| Dedupe / no duplicate outreach | DONE (import) | phone key, `agency_callsheet.py:54-61`. No DNC status, so a do-not-contact business can be re-imported |
| 11 statuses | PARTIAL | `agency_callsheet.py:24` has 7 (new/answered/interested/no_answer/callback/dead/bad_number); client book `agency_io.py:18` has lead/building/active/paused/churned. Missing: READY, DEMO BOOKED, PROPOSAL, WON, LOST, DNC |
| Daily call queue | PARTIAL | `owner_actions.py:257-279` (one "N ready to dial" row plus callbacks). Callback rows have `created_ms=None`, so they have no age and never sort or collapse by age. No demos or proposals |
| Zero-research prospect screen (opportunity, offer, talking points) | MISSING | only the `pain` field from the PDF parse (`agency_callsheet.py:112-118`) |
| Follow-up after a call | PARTIAL | `escalate()` `agency_callsheet.py:395-414` creates a client "lead" plus a note. No follow-up task, reminder, callback date or demo scheduling |
| Client agent (requests, bugs, invoices) | PARTIAL | edit requests appear as REVIEW (`owner_actions.py:301`); Dyson plans edits. Agency invoice/payment status is MISSING |
| MRR / client tracking | DONE | `agency_io.py:238-254` |

### §7 Wholesale
| Req | Status | Evidence |
|---|---|---|
| AI conversation + qualification | DONE in code, OWNER to run | `marcus_screening.py:298`, ACE. Every Claude call fails on credits (P0-1) |
| Compliance: DNC, opt-out, quiet hours, reply-only-to-sellers | DONE | `sms_guard.py:62,194-197`; `marcus_engine.py:426` |
| Never a price by text | DONE | `marcus_engine.py:781` |
| 5 classes with stored reasons | PARTIAL | `scout_triage.py:91` has 4 buckets; `dead` lumps NOT INTERESTED together with DO NOT CONTACT. Reasons are stored (`:377-411`, AI `:428`) |
| Don't discard on a black-box score | DONE | `scout_triage.py:1081` `retro_audit`, weekly run at `:1405` |
| 30-second owner view | PARTIAL | call-prep in `screening.jsx:73`. The Atlas call card has **no UI**: `/api/prep/*` exists only in `connector.py:2713-2715,1318` and no `.jsx` calls it |
| Intent up → HOT → owner task → alert | DONE | Scout re-score; `owner_actions.py:160` (asap → CALL); `telegram_io.py:46,404` `hot_lead`; auto-tag `scout_triage.py:1421` |
| Owner-task dedupe | DONE | `owner_actions.py:44` `merge_and_sort`; `test_owner_actions.py` |
| Offer / contract / dispo pipeline | DONE (no dashboard tiles) | `deal_prep.py:378-404`, `deals.py:88,95`, `buyers.py:232`, DocuSign poller |

### §8 Daycare
| Req | Status | Evidence |
|---|---|---|
| Meta monitoring (spend/CPL/CTR) | PARTIAL + OWNER | `agency_ads.py:178` live analytics via the `daycare_growth` env-swap. The token is invalid (P0-9) |
| KEEP / PAUSE / TEST / INVESTIGATE verdict | MISSING | no match anywhere in `*.py` |
| No free budget increase | DONE | `agency_ads.py:417-441` creates PAUSED only |
| New lead → CRM, dedupe, source | DONE | website `/api/enroll` → GHL (brand-kit repo); `daycare_leads.py:205-213` source/center |
| AI answers from verified facts | MISSING + OWNER | P3 in the plan. Needs a verified-facts file; open seats per age band are unknown (`forge-daycare/skills/daycare-context.md:63,139`) |
| Tour scheduling + reminders | MISSING + OWNER | no calendar; GHL-calendar decision is the owner's |
| 9-stage pipeline | PARTIAL | `daycare_leads.py:197-198` has only NEW/CONTACTED/RESPONDED/NEEDS_HUMAN; enrolled families are dropped at `:430` |
| Dashboard tiles | PARTIAL | Have: response time + needs-human (`daycare.jsx:247`, `daycare_leads.py:270-274`); open spots = capacity − enrolled (`daycare.jsx:275`), which is the licensed ceiling, not verified vacancy. Missing on the Dashboard: Meta spend, CPL, tours booked/today, applications, enrollments, cost per enrollment |
| Never invent tuition / capacity / etc. | DONE | `agent_creed` daycare creed + context brief |

### §9-§11 Agents
| Req | Status | Evidence |
|---|---|---|
| Registry fields + 6 statuses | DONE | `agents_hub.py:560,704-781` (lastSuccessAt, nextRun, tasksCompleted/Failed, currentTask); `test_agent_registry.py` |
| Dependency health | PARTIAL | `agents_hub.py:765-771` covers AI + heartbeat only. No GHL / Meta / Supabase dependency |
| §10 durable action log (ts, agent, trigger, result, retry, approval) | MISSING | no action/audit log module. Only `send_ledger` (SMS) and `agent_bus` (capped at 200) |
| §11 retry transient failures | PARTIAL | GHL retries 429/5xx (`connector.py:161-173`). **Claude has no retry**: `review_agent.py:93-106` raises on the first 429/529/timeout |
| §11 DEGRADED → escalate → owner/dev task | PARTIAL | DEGRADED at `agents_hub.py:578`; FIX row at `owner_actions.py:376-393`; watchdog alerts but never restarts (`connector.py:1840-1910`). No persisted tech task |

### §15-§17 CEO dashboard + briefs
| Req | Status | Evidence |
|---|---|---|
| Owner Actions (URGENT → REVENUE → CUSTOMER → NORMAL) | DONE | `owner_actions.py:44-61` |
| Agency tiles (Calls Ready, Callbacks, Interested, Demos, Clients, MRR) | MISSING | `mission_control.py:109-140` shows agents online / open tasks / approvals |
| Wholesale tiles (Owner calls, Offers, Contracts, Deals) | PARTIAL | `mission_control.py:77-81` shows hot / warm / active / to-screen |
| Daycare tiles (spend, leads, tours, apps, enrollments, human attention) | MISSING | `mission_control.py:143-165` shows "Systems wired" / "Director AI" |
| Agents tile (healthy, running, failed, waiting) | PARTIAL | loop counts only (`mission_control.py:246-262`), not registry statuses |
| Amazon / personal widget | MISSING + OWNER | needs shift schedule and debt target from the owner |
| §16 morning brief, cross-business | PARTIAL | `daily_brief.py:127-175` + `connector.py:1928-1966` read **wholesale only** (Scout, Marcus, GHL dashboard, cost, red loops). Orion's cross-business brief is Claude-based and currently down |
| §17 nightly report (what failed, revenue, tomorrow) | PARTIAL | `daily_recap.py:117-173`: wholesale open loops only |

### §19-§23
| Req | Status | Evidence |
|---|---|---|
| §19 approval queue (Action/Agent/Reason/Risk/Expected; Approve/Reject/Edit) | PARTIAL | 10 separate queues (Marcus proposals, `agency_approvals_io`, Scout tags, skill_forge, …) funnel into Owner Actions APPROVE rows that only link out |
| §20 alert: HOT seller | DONE | `telegram_io.py:46` |
| §20 alert: daycare needs a human | DONE | `daycare_leads.py:338-355` |
| §20 alert: agent failure / outage / AI down | DONE | `connector.py:1850-1910` |
| §20 alert: agency prompt callback | MISSING | — |
| §20 alert: payment / revenue issue | MISSING | — |
| §20 alert: security issue | MISSING | — |
| §21 wholesale test | DONE | `test_e2e_pipeline.py`, `test_owner_actions.py` |
| §21 agent-failure test | DONE | `test_ai_health.py`, `test_agent_registry.py` |
| §21 archive test | DONE | `test_business_scope.py` |
| §21 agency test | PARTIAL | no follow-up-task / audit-log assertion |
| §21 daycare test | PARTIAL | tour / reminder / attribution not built |
| §22 auth protects the dashboard | OWNER | tailnet-level only (`docs/FORGE_TEST_PLAN.md` §6) |
| §22 backups / rollback | DONE | local tarball; git revert → autopull |
| §23 mobile responsive | PARTIAL | desktop media queries exist, but the mobile PWA has **no Owner Actions / registry / Lead Desk** (`grep owner-actions mobile/*.jsx` → none) |

---

## 2. Doc drift

| Doc:line | Claim | Code reality |
|---|---|---|
| `docs/FORGE_APP_GUIDE.md:91` | "Open read-only" views an archived business without reactivating it | The button is "Open (archived)" (`archived.jsx:44`) and **actions still work** (`app.jsx:234`, banner `app.jsx:309`). This is safety-relevant: the owner may think taps there are inert |
| `docs/FORGE_APP_GUIDE.md:78`; `CLAUDE.md` §9 daily-brief bullet | Daily brief / recap covers "All" businesses | Wholesale-only content (`connector.py:1928-1966`) |
| `CLAUDE.md:212` "Seven brains"; `CLAUDE.md:570` "all 7 agents" | 7 brains | `agents_hub.py:76` roster: 12 rows, **8 brains** (scout, marcus, atlas, dyson, eco, solomon, midas, orion) |
| `CLAUDE.md:273` | `node /tmp/valjsx.js` | validator is `forge rei/deploy/valjsx.js` (the automation plan has it right) |
| `CLAUDE.md:354-355` | Agent Office nav "in all four workspaces" | Dropship is archived, so 3 are visible |
| `CLAUDE.md:448` | dashboard and app Supabase migrations are "byte-identical" | 30 vs 39 files; the 9 missing ones date 2026-08-30..09-13 |
| `NORTH_STAR.md:25` | "Four businesses" | Dropship is archived by default (`business_scope.py:37`) |
| `docs/FORGE_TEST_PLAN.md:25` | 32 pass / 0 fail after wave 1 | 33 pass / 0 fail today |
| `docs/FORGE_AGENTS.md:38`; `docs/FORGE_CURRENT_ARCHITECTURE.md:100` | forge-review timer "BROKEN" (unquoted JSON) | Repo fixed: `deploy/setup_droplet.sh:133` quotes `-d '{"days":7}'` (commit d141618). Box unit not re-verified (would need SSH) |
| `docs/FORGE_CURRENT_ARCHITECTURE.md:50` | 5 model ids, 6+4+3 refs | Code has 2 ids: `review_agent.py:28` (sonnet-4-5), `:31` + `marcus_engine.py:922` (haiku-4-5) |
| `docs/FORGE_CURRENT_ARCHITECTURE.md:57,60,81,124` | "No archive flag", "No ErrorBoundary", "Backups: none", "No agent registry" | All superseded: `business_scope.py`, `app.jsx:146` AppErrorBoundary, `deploy/backup_state.sh`, `agents_hub.py:704`. The audit snapshot was never updated after wave 1 |
| `docs/FORGE_INTEGRATIONS.md:16` | Eco page mock data unlabeled | Still true: `agency_eco.py:451-458` drops `agency_ads` `source` (live/mock/auth_error, `agency_ads.py:270,312,356`); `agency_eco.jsx` has no badge. It is an open gap, so it is item 10 below |

---

## 3. Ranked Wave-2 build list (pure code, additive, nothing outward made autonomous)

**1. Cross-business morning brief + nightly report (§16/§17, zero Claude)** — ✅ DONE 2026-09-23
- **Files:** `connector.py:1928` `_gather_brief_stats`, `daily_brief.py:127`, `daily_recap.py:117`.
- **Reuses:** `owner_actions.build` (top 5 + counts), `agents_hub.registry` (status counts), `agency_callsheet.list_leads` counts, `agency_io.stats()` (clients/MRR), `daycare_leads.view()` (cached state, no network).
- **Recap adds:** what failed today (red loops + FIX rows) and tomorrow's first 5 actions.
- **Accept:** a new `test_brief_sections.py` passes fixture stats and asserts AGENCY / WHOLESALE / DAYCARE / AGENTS / OWNER TASKS sections; a missing source omits its line (never a fake 0); archived businesses are skipped; the dedupe keys (`connector.py:1979,2006`) are unchanged.
- **Risk:** low. The message goes to the operator only; this replaces Orion's function while credits are down.

**2. Mission Control spec tiles (§15)** — ✅ DONE 2026-09-23
- **Files:** `mission_control.py:69/109/143/246`.
- **Agency:** Calls ready / Callbacks / Interested / Clients / MRR.
- **Wholesale:** + Owner calls required (Owner Actions CALL count) + Contracts / Deals (`deals.list_deals`).
- **Daycare:** New leads / Needs human / Response time from `daycare_leads.view()`.
- **Agents:** Healthy / Running / Failed / Waiting from the registry.
- **Accept:** a snapshot fixture test asserts the labels; a failing source drops its metric and adds one warn line; no network added to the snapshot path.
- **Risk:** low, but `registry()` latency needs a check.

**3. Atlas call card + 30-second seller header (P1-7, §7)** — ✅ DONE 2026-09-23
- **Files:** `screening.jsx` (or a new `atlas_card.jsx` added to `FORGE REI OS.html`); uses the existing `GET /api/prep/get` (`connector.py:1318`) and `POST /api/prep/run`.
- **Shows:** property, timeline, ask, condition, motivation, last contact, anchors (labeled **INTERNAL — never text**), MAO note, comps to pull, call-card bullets. Deep-link it from the Owner Actions "Atlas call card ready" row.
- **Accept:** `valjsx` passes; "No prep yet" state; no send or copy-to-SMS control anywhere on the card (rule 9).
- **Risk:** low.

**4. Agency call-sheet lifecycle (§6)** — ✅ DONE 2026-09-23
- **Files:** `agency_callsheet.py:24` (additive statuses: `ready`, `demo_booked`, `proposal`, `won`, `lost`, `dnc`; new fields `callbackAt`, `attempts`, `lastContactAt` ISO, `nextAction`, `category`), `owner_actions.py:257-279`, `agency_callcenter.jsx`.
- **Queue rules:** a future `callbackAt` stays hidden until due; a due callback → REVENUE CALLBACK with a real age; `dnc` is excluded and blocks re-import by phone.
- **Optional:** an operator-only Telegram ping when a callback comes due (deduped), which covers the §20 agency alert.
- **Accept:** the `agency_callsheet` self-check is extended (dnc re-import blocked, attempts increment, tomorrow's callback not in today's list); `test_owner_actions` still green.
- **Risk:** low. Old statuses stay valid; new fields default.

**5. Daycare pipeline stages + tours / apps / enrollments (§8)** — ✅ DONE 2026-09-23
- **Files:** `daycare_leads.py:158` `derive`, `:244` `kpis`, `daycare.jsx` Lead Desk.
- **Stages:** read TOUR_BOOKED / TOUR_COMPLETED / APPLICATION / ENROLLED / LOST from GHL tags when present, plus a one-tap **local** stage mark stored in `marcus_state/daycare_lead_stages.json` (internal, reversible, never written to GHL). ENROLLED is also derived from the contact→child ledger (`daycare_ghl.py:84`).
- **Accept:** `test_daycare_leads.py` extended for stage precedence; tiles show "—" (Unknown) when there is no source, never 0; enrolled families stay out of needs-human.
- **Risk:** medium. The Lead Desk ↔ Owner Actions one-row-per-family contract (`owner_actions.py:353`) must hold.

**6. Durable agent action log (§10, P1-9)** — ✅ DONE 2026-09-23
- **Files:** new `action_log.py` — append-only `marcus_state/agent_actions.jsonl`, size-rotated, redacts key/Bearer patterns (reuse the `agent_coach` secret guard). Fields: ts / agent / business / trigger / ref / action / result / ok / error / retry / approvalRequired.
- **Hooks (post-action, try/except):** `sms_guard` send result, `scout_triage._autotag_hot:1421` + autopipe, marcus approve, telegram approve tap, contract stage move, `agency_eco.approve_ad`.
- **Also:** `GET /api/actions/log`; the registry shows each agent's last action.
- **Accept:** `test_action_log.py` covers append, rotate, redaction, concurrent writers, and an unwritable log never blocking the action.
- **Risk:** medium, because it touches send paths. The hooks must never gate an action.

**7. Claude transient retry + wider dependency health (§11)** — ✅ DONE 2026-09-23
- **Files:** `review_agent.py:93-106` and `marcus_engine.py:~922` — ≤2 retries with backoff on 429/500/502/503/529 and timeouts only; **never** on 400/401/403 (credits/auth). `agents_hub.py:765` `dependencyHealth` gains `crm` (heartbeat lastError / GHL health) and `meta` (`agency_ads._auth_dead`).
- **Accept:** fake-urlopen test: 529 → 529 → 200 returns text with one `ai_ok`; a credit 400 raises at once and marks hard-down.
- **Risk:** low-medium: adds a few seconds of latency on a bad day. It must not interact with the per-key hardBy fix already in flight elsewhere.

**8. Wholesale 5-class label (§7)** — ✅ DONE 2026-09-23
- **Files:** `scout_triage.py:377-411` — add explicit `optOut` / `wrongNumber` flags and a derived `classification` (HOT / WARM / NURTURE / NOT_INTERESTED / DO_NOT_CONTACT). Buckets are untouched. Show it in the leads UI.
- **Accept:** a test asserts "stop" → DO_NOT_CONTACT, "not selling" → NOT_INTERESTED, reason preserved, bucket unchanged.
- **Risk:** low.

**9. Mobile Owner Actions tab (§23)** — ✅ DONE 2026-09-23 (`mobile/m_actions.jsx`, Actions tab)
- **Files:** new `mobile/m_actions.jsx` (unique hook aliases), `m_app.jsx` / `m_shell.jsx` tab, `GET /api/owner-actions`. Read-only, with the same error-row honesty as desktop.
- **Accept:** `valjsx` on mobile; a fetch failure shows "list may be stale".
- **Risk:** low.

**10. Eco / daycare-growth mock labeling (creed honesty)** — ✅ DONE 2026-09-23
- **Files:** `agency_eco.py:451` — return `dataSource` + date range from `agency_ads.analytics`; `agency_eco.jsx` and the daycare Ideas view get MOCK / TOKEN REJECTED badges.
- **Accept:** a test asserts `dataSource == "mock"` with no token.
- **Risk:** trivial.

**Next after these 10:**
- Unified §19 approval view (Risk / Expected Result, Reject, Edit) over the existing queues.
- Deterministic Meta KEEP / PAUSE / TEST / INVESTIGATE verdict (useful once the token works).
- Desktop brief/recap config page.
- Refresh the architecture docs (§2 above).

**Excluded as instructed:** heartbeat per-key hardBy reconciliation; autopull retry after an aborted deploy.

---

## 4. Owner-only blockers

1. **Anthropic credits (P0-1).** Every Claude call has failed since 2026-08-01. This blocks Scout AI scoring, Marcus, Atlas, Solomon, Orion, Dyson/Eco, chats and `learn()`.
2. **Rotate the GitHub PAT** that was exposed through the brain API, and delete `vault/.env` (P0-2).
3. **Daycare Meta token** is invalid (32 chars, OAuth 190). Replace it in `daycare.env` and run `push.sh` (P0-9).
4. **Daycare compliance items** (licensing and staffing) outrank growth work (P0-8). Licensing paperwork for 921 and 1923 and the STARS rating are not on file (`daycare-context.md:53`).
5. **Daycare facts only you have:** open seats by age band per center (`daycare-context.md:63,139`); whether the referral bonus stacks (`:74`); tuition figures. These block item 5's verified vacancy and any AI parent answers.
6. **The daycare enrollment offer expired 2026-09-12** (`daycare-context.md:73`). The site countdown and the agents' context still reference it; a successor offer is needed.
7. **Tour booking:** decide on a GHL calendar and tag convention (tour-booked / tour-completed / application).
8. **Agency prospect engine on the box:** needs an Apify key and spend there, or accept that it stays on the Mac (P1-8).
9. **Dashboard authentication policy:** the tailnet is the only gate, and `FORGE_DAYCARE_OPEN=1`. Review tailnet members and the ACL (P0-10, §22).
10. **Off-box backups** (DigitalOcean backups, about $1–2/mo) (P0-6).
11. **Meta spend guardrails:** set a max daily budget / delta if you ever want anything beyond one-tap approval (§8).
12. **n8n:** supply a real workspace URL or retire the page.
13. **Confirm `FORGE_DAYCARE_TEST_MODE=1` on production is intended.**
14. **Amazon shift schedule and debt target** for the §15 personal widget.
15. **Supabase migrations resync** into the *public* repo exposes 9 more schema/RLS files. Your call before anyone copies them.
16. **ACE / autopilot modes** stay operator-only; nothing in Wave 2 touches them.
