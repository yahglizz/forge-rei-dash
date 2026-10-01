# FORGE REI OS — Cross-Cutting Layer Audit (2026-09-30)

Scope: the layer that sits above the per-business pages (Mission Control, Owner Actions, Agent Control Center,
Agent Office, Orion, bus/coach, Brain, Telegram, Health/Costs, action log, backups, mobile shell, autopilot/ACE/follow-up
gates, business_scope) plus the AI dependency map and Dyson/Eco <-> Solomon comms. Wholesale / agency / daycare pages
are covered by the sibling audits in this folder.

Method. READ-ONLY. Code read in `/Users/yg4st/forge rei dash/forge rei`; box probed with GET only
(`ssh ... curl localhost:7799/...`), `systemctl list-timers`, `ls`/`tail` of logs, `grep -c` of env VAR NAMES (no values read).
Python tests were run in a **sandbox copy** (no `*.env`, empty `marcus_state`, temp vault, `ANTHROPIC_API_KEY` unset,
`FORGE_ACTION_LOG` = temp file) so nothing touched real state. No POSTs, no sends, no runs triggered.

Tests run (all pass in sandbox): test_owner_actions, test_agent_registry, test_ai_health (31), test_claude_retry (12),
test_business_scope, test_model_policy, test_action_log, test_cost_tracker (10), test_agents_docs, test_mission_tiles,
test_brief_sections, test_telegram_biz_chats (7), test_telegram_agent (12), test_autopilot_routes, test_agent_office_ui,
test_office_dogs, test_brain_live, test_telegram_ace, test_ace, test_triggers_cost, test_sms_guard.
(`test_optout_hardening` errored only because the sandbox has no `marcus-wholesale-agent/config/ghl.env`.)
`deploy/valjsx.js` validates all 19 cross-cutting/mobile JSX files OK.

---

## 0. Headline facts (live box, 2026-09-30 ~23:50 UTC)

| Fact | Evidence |
|---|---|
| Anthropic credits exhausted; `ai_health.hard=true, kind=billing`, `failStreak=3969`, `callsTotal==errorsTotal==3969`, `lastOkAt=null`, one key fingerprint down | `/api/system/health` |
| **The outage is almost certainly ~2 months old, not 8 days.** `downSince` = 2026-09-22 is only when WP-A instrumentation started writing `ai_health.json`. `marcus_state/cost_tracker.json` last modified **2026-08-01 09:10 UTC** (it is written only on a *successful* call); Solomon `lastSuccessAt` = 2026-08-01 09:10:02; Marcus `lastSuccessAt` = 2026-07-27; last real-Claude seller draft = 2026-07-17, last (template) draft = 2026-08-27; all playbook mtimes Jul 27-30 | cost_tracker.json mtime, registry, `/api/marcus/proposals`, `/api/brain/status` |
| The *only* loop hammering the API right now is `daycare_replies`: errStreak 1778 and climbing ~1/min; 2,029 "credit balance" lines in the current `connector.out.log` window, **100% of them `[daycare_replies]`** | `/api/system/health`, `grep -c` on the box log |
| `FORGE_*` knobs are **all unset** in `/etc/default/forge-reios` (every default applies: SELF_IMPROVE/BRIEFS/SKILL_FORGE/TODAY_LOOP/SOLOMON_BRIEF off; REPLY_AUTO off; `FORGE_DAYCARE_OPEN=1`) | grep of var names |
| Meta token problem is the **daycare** token: `META_ACCESS_TOKEN` is non-empty only in `daycare.env` (agency.env and the service env have none). `connector.err.log` has 5,118 "[ads] live fetch failed ... Invalid OAuth access token" lines | grep -c |
| Backups run nightly (03:30 ET), 7 tarballs of ~5.2 MB, latest 2026-09-30 07:30; **all on the same disk** as the live state | `ls /root/backups`, `deploy/backup_state.sh:6` |
| Telegram bot up (`telegram` + `telegram_agent` loops green, 161k beats); HQ + wholesale + agency + daycare chats bound, dropship unbound | `/api/notify/settings`, `/api/system/health` |
| Wholesale is flagged `maintenance:true` in `/api/businesses` (visual only) and has been effectively dormant: newest pending seller proposal 2026-08-27, weekly missed-leads sweep = "scanned 0" every week since Aug 30 | `/api/businesses`, vault `Reports/missed-leads-2026-09-27.md` |

---

## 1. Status table

Class legend: WORKING · WORKING-NEEDS-AI (works, but its value depends on Claude) · BLOCKED-AI-CREDITS · BLOCKED-OTHER-KEY · BROKEN · STUB.

| # | Surface | Route(s) | Class | Notes |
|---|---|---|---|---|
| 1a | Mission Control tiles + verdict | `GET /api/mission-control` | **WORKING** | Live: verdict NEEDS ATTENTION, 12 loops (11 healthy, 1 down), 3 business cards, agents strip (failed 1 / degraded 3). Zero Claude. Daycare card shows "Response time 1s" — looks suspect (verify in daycare audit). |
| 1b | Mission Control Orion brief card | `GET /api/mission-control/brief{,/overview}` | **BLOCKED-AI-CREDITS** | Cached brief is from **2026-07-30** (briefCount 18) and talks about a "sixteen-day daycare crisis / DHS suspension risk" — 2 months stale, pre-Solomon-growth-reset. `aiReady:true` only means "a key string exists" (`mission_control_agent.py:430`), not that AI works. Scheduled brief is off (`FORGE_BRIEFS=0`). |
| 2 | Owner Actions | `GET /api/owner-actions` (`owner_actions.py`) | **WORKING** | 16 rows: 4 CALL (3 daycare parents unanswered 15+ min — correct degraded behavior when the Reply Desk can't draft), 3 APPROVE (Starts confirms), 2 FIX (AI credits, Replies loop), 7 stale-collapsed REVIEW. Zero Claude; each source fails soft to one FIX row. Wholesale has no fresh rows (dormant). |
| 3 | Agent Control Center | `GET /api/agents/registry` (`agents_hub.registry`) | **WORKING** | Honest: Solomon FAILED (2024 errors), Marcus/Dyson/Orion DEGRADED (ai=down), Midas DISABLED+archived. **Gaps:** `dependencyHealth.meta` is computed for Dyson only (`agents_hub.py:955`), so the daycare's dead Meta token shows nowhere (Solomon = "n/a"); Midas is still returned in the payload (UI must filter); README says lane interval 300 s but code is 60 s. |
| 4a | Agent Office 3D — floor state, Orion check-in | `GET /api/office/{state,job,jobs,checkins}`, `POST /api/office/checkin` | **WORKING** | State = real signals; check-in is zero-Claude (`agent_office.py:663`); shows "AI is offline" banner from `ai_health`. `checkins` currently empty (none run since last reset). |
| 4b | Agent Office — chat / task / plan | `POST /api/office/{chat,task,plan}` | **BLOCKED-AI-CREDITS** | Chat degrades to a labelled live-status reply (`agent_office.py:706-721`) — good. `task` files a hub task then runs `agents_hub.chat` in a thread → will fail and close the task as failed (1 wasted API call per task). `plan` returns an error. 1 open Solomon task queued. |
| 5 | Orion CEO | `mission_control_agent.py`, `/api/hub/chat {orion}` | **BLOCKED-AI-CREDITS** | Brief/learn/chat need Claude. No schedule (by design). Office + Telegram HQ default to Orion; both degrade politely. |
| 6 | agent_bus | `GET /api/bus`, `/api/hub/bus` | **WORKING (degraded by noise)** | Cap 200 messages shared by all kinds (`agent_bus.py:32`). Live bus = **122/200 `watchdog` alerts** (69 "Solomon · Replies is DOWN", 39 "Solomon director is DOWN", Telegram-agent flaps), 41 of newest 50 unread. Loop flaps red->green->red so the watchdog re-alerts every time (Telegram de-dupes at 15 min, the bus does not). Bus kinds `directive` and `ask` are silently coerced to `note` (`agent_bus.py:28,74-76`). |
| 7 | agent_coach | `GET /api/coach/feed`, `POST /api/coach/{broadcast,ask}` | **BROKEN** | Live `{"feed": []}`. The two Jul-30 insights (eco->all, dyson->all) exist only in vault `Coaching/feed.md`, which nothing reads back; the bus (authoritative store) evicted them. See section 4. |
| 8 | Brain tab | `/api/brain/{tree,note,search,recent,graph,activity,status}`, `POST /api/brain/undo` | **WORKING** | 339 notes, 7/7 agents "ready", semantic proxy (`:7878`) answering, graph OK. Traversal safe: `.env`, `../.env`, `Skills/../../../etc/passwd` all refused (`brain_io.py:37-46, 95-106`). Notes: box vault git has uncommitted rsynced edits (`Businesses/Daycare.md`, `Skills/solomon-playbook.md`) and an untracked `.env` (PAT) in the vault root — blocked from serving, but it is inside the vault that `backup_state.sh` tars. `write_note` has no extension/path allowlist (only no-escape), callers are all constants today. |
| 9a | Telegram — transport, per-biz chats, taps | `telegram_io.py`, `/api/notify/{settings,test}` | **WORKING** | Configured, agent bot set, `bizChats` = wholesale/agency/daycare bound, dropship not. `TELEGRAM_ALLOWED_IDS` empty, so taps in business chats are operator-only (safe default). 15-min dedupe ring. |
| 9b | Telegram — zero-Claude fallbacks | `/status /starts /logins /pin` + ops slash cmds | **WORKING** | `telegram_agent.quick` (`:595`) and `telegram_ops._CMD_RE` (`:742`) need no Claude. |
| 9c | Telegram — partner chat, intent router | `telegram_agent.chat`, `telegram_ops._intent` | **BLOCKED-AI-CREDITS** | Partner returns "Couldn't reach my brain ... slash commands still work" (graceful, `telegram_agent.py:527-529`). **But** in the wholesale chat every plain message first tries the Claude intent classifier (`telegram_ops.py:771-782`) and swallows the failure, i.e. one wasted call per message. |
| 10a | System Health view + watchdog | `GET /api/system/health`, `system_health.jsx` | **WORKING** | Correctly red, names the red loop, shows disk 19%, stripe live, ONE Telegram alert for AI down (`alerted:true`) + one on recovery. Says "down since 2026-09-22" (understates, see section 0). |
| 10b | Costs view | `GET /api/cost/status`, `cost.jsx` | **WORKING (misleading)** | Shows $0 MTD and a trend that ends 2026-08-01, with no "AI down" banner (only Agents / Office / Health have one). `monthlyCapUSD: 0` so no cap alerts. Failed calls are not counted anywhere. |
| 11 | Action log | `GET /api/actions/log` (`action_log.py`) | **WORKING** | 3 rows in `agent_actions.jsonl` (2 Stripe link sends, 1 daycare manual send); ids redacted; low volume consistent with dormant wholesale. Nothing recorded from Telegram taps / Marcus approve / ACE since. |
| 12 | Backups | `forge-backup.timer`, `deploy/backup_state.sh` | **WORKING (single-host)** | 7 daily tgz in `/root/backups` incl. marcus_state, uploads, vault, all `*/config` (secrets) and `/etc/default/forge-reios`; archive read-back verified by script. **No off-box copy** (script comment `:6`), no restore drill evidence. Disk 19% used. |
| 13 | Mobile app shell + business portal | `/m/` -> `<base href="/mobile/">`, `mobile/m_login.jsx`, `m_biz_*.jsx` | **WORKING** | `/m/` 200, `/mobile/*.jsx` 200, secrets/state URLs 404, all mobile JSX validates. Portal = Wholesale / Agency / Daycare / Everything; no Dropship tile. Not exercised visually in this audit (no device). |
| 14 | Autopilot | `/api/autopilot/{status,toggle}`, `autopilot.py` | **WORKING (OFF) — latent hazard** | `enabled:false`, 0/10 today. Gate 7 is `legit_check.verdict`, which **fails OPEN** when Claude errors (`legit_check.py:118-123`: `legit: True ... judge error, passed through`), and nothing checks `draftSource`, so with credits out an enabled autopilot would auto-send the static template bump. See F3. |
| 15 | ACE | `/api/ace/{state,status,mode,...}` | **WORKING (mode off) — mostly guarded** | `mode: off`. Pivot path uses `CALL_PIVOT_FALLBACK` and `_pivot_text` fails closed; question path has `_draft_adherence_reason` (fact adherence) which a template would fail. No explicit `draftSource` refusal (ace.py has none). Autopilot's missing Test-Mode check noted in agents/README #16. |
| 16 | Follow-up | thread `followup`, 1800 s | **WORKING-NEEDS-AI** | Green; 5 threads tracked. With credits out `make_proposal_for` queues a template-source proposal (`marcus_engine.py:974`); `/api/marcus/proposals` already holds 2 `draftSource:"template"` pending items ("apologies for the slow reply", 2026-06-06 and 2026-08-27) awaiting an owner tap. |
| 17 | business_scope archive | `GET /api/businesses`, `POST /api/businesses/set` | **WORKING (hide-only)** | dropship + agency:p archived (default seed), rei `maintenance:true` (visual flag; not in CLAUDE.md, which only documents archive). Archive gates **no loop, route, Telegram agent or registry row** — Midas is still in `/api/agents/registry` (DISABLED) and `/midas` Telegram still routes; `agent_coach` correctly drops archived businesses (`agent_coach.py:91-98`). |
| 18 | Scheduled nightly learn (systemd) | `forge-daily-learn.timer` 00:00 UTC, `deploy/daily_learn.sh` | **BLOCKED-AI-CREDITS — contradicts docs** | Timer is live; `daily-learn.log` shows all 6 jobs (scout, screening, voice, review, dyson, eco) failing with "credit balance too low" every night. It is **not gated by `FORGE_SELF_IMPROVE`** (see F2). |

---

## 2. AI dependency map

### 2.1 How a Claude call works today (and what happens when credits are out)

Two transports, one health signal:

* `review_agent.post_messages` (`review_agent.py:143`) <- `review_agent._claude` (`:183`) <- ~45 call sites. Also `telegram_agent.chat` uses `post_messages` directly (`telegram_agent.py:519`).
* `marcus_engine._ai_draft` (`marcus_engine.py:931-941`) builds its own request and calls `review_agent.claude_urlopen` directly (bypasses `post_messages`).

Retry policy (`review_agent.py:109-139`): `claude_urlopen` retries **only** 429/500/502/503/529 and fast network errors, 2 retries, fixed 2 s / 5 s, never on timeout, never on 400/401/403. So an exhausted-credit **HTTP 400 is one HTTP request per logical call**. Good (no retry storm inside a call).

Health stamping: `ai_fail(code,msg,key)` (`forge_heartbeat.py:271`) classifies `400 + "credit balance"` as billing/hard and records `hardBy[fingerprint]`. `ai_health()` is consumed **only for display / alerting** (`connector.py:540,1885`, `agents_hub.py:681`, `agent_office.py:541`, `owner_actions.py:461`, `mission_control.py:281`). **No call site consults it before making a request.**

Consequences when credits are out:

| Layer | Behavior | Verdict |
|---|---|---|
| Per-call | 1 request, fails fast (400) | fine |
| Per-loop backoff | `daycare_replies.run_forever` sleeps a fixed `INTERVAL` (60 s) after every sweep, errors or not (`daycare_replies.py:664-677`); no backoff. Within a sweep it `break`s on the first Anthropic error (`:463-465`), so worst case 1 failed call + 1 GHL conversations search + up to a few thread GETs **per minute** (~1,440 failed calls/day while any parent is waiting for a draft). | **hammering** |
| Circuit breaker | **None.** Nothing short-circuits. | gap |
| Solomon brief | Has its own 15 min -> 6 h backoff for failed briefs (CLAUDE.md wave-1), but the brief loop is off (`FORGE_SOLOMON_BRIEF=0`) | only local fix |
| Scout | Claude failure -> `_claude_batch` returns `{}` -> deterministic `_rule_score` record with `scoreSource:"rule"` is kept, not retried (`scout_triage.py:517-521, 432`) | graceful, no storm |
| Marcus drafts | Failure -> **static template draft** returned as if normal (`marcus_engine.py:970-981`), tagged `draftSource:"template"` | silent degrade, see F3 |
| Judges (legit_check) | Fail-open, not cached on error -> re-asks Claude next time (`legit_check.py:118-123`) | wrong direction |
| Telegram | Intent classifier swallows failure (`telegram_ops.py:783`) but still spends a call per plain wholesale message | wasteful |
| Nightly systemd | 6 POSTs/night regardless (`deploy/daily_learn.sh:27-37`) | wasteful + ungated |

Attribution of the 3,969: 2,029 are `daycare_replies` in the current log window (errorsTotal on that heartbeat is 2,024). The other ~1,900 cannot be attributed — `ai_fail` records no caller. (`cost_tracker` already buckets by `threading.current_thread().name`; the same name could be stamped on failures.)

### 2.2 Every Claude call site — what lights up when credits return

Model tiers (`review_agent.py:36-42`): `FAST_MODEL`=Haiku 4.5 (default for `_claude`), `SMART_MODEL`=Sonnet 5.5, `DRAFT_MODEL`=SMART. `effort` column: low unless noted.

**A. Fires on a timer or event with no human in the loop (these are what lights up by itself):**

| Call site | What | Model | Trigger | State today | If credits return |
|---|---|---|---|---|---|
| `daycare_replies.py:340` `draft_reply` | parent text-back draft | SMART (`FORGE_DAYCARE_REPLY_MODEL`) | thread `daycare_replies`, **every 60 s**, <=8 drafts/sweep, 7-day lookback | **burning failed calls now** | Immediately drafts a backlog burst (<=8 Sonnet calls per minute) for every unanswered parent in the last 7 days, Telegram-pings each escalation. Drafts only (owner taps send) unless `FORGE_DAYCARE_REPLY_AUTO=1` (unset; auto also refuses drafts >12 h old). |
| `scout_triage.py:516` `_claude_batch` | classify new seller threads | FAST (Haiku) | thread `scout`, 180 s, only for threads with a new inbound | rule fallback active | Scores new inbound only; existing rule-scored records are not re-scored. Then `on_scored` -> Marcus screening (below). |
| `marcus_screening.py:417` `screen` | call-ready report | FAST medium | Scout `on_scored` for asap/warm (`FORGE_SCREEN_AUTO=1`), `/api/screening/run`, Telegram `/screen` | Mission Control: **69 "To screen"** backlog | Auto-screens only *newly* scored call-worthy leads; the 69-lead backlog needs a manual run. |
| `deal_prep.py:360` `prep` | Atlas underwriting | FAST medium | thread `atlas`, 900 s `auto_prep_interested` | green (nothing pending: 39 prepped) | Preps whatever Marcus newly screens as interested. |
| `marcus_engine.py:941` `_ai_draft` | seller / bump draft | SMART inbound, FAST for re-engage | `make_proposal_for` from Scout handoff, Follow-up (1800 s), ACE, `reengage_*` scripts; Marcus SMS loop off (`FORGE_MARCUS_SMS=0`) | falls back to template | Real drafts again; proposals stay tap-gated; autopilot/ACE off. |
| `legit_check.py:110` `verdict` | "is this a real seller" judge | FAST | Autopilot gate 7; `audit_tagged` (only in `do_today` loop, off); Scout `urgency` | autopilot off | Only matters if autopilot is turned on. |
| `scout_triage.py:1287` `retro_audit` | weekly missed-leads | FAST | once a week inside Scout loop (ignores clock-out) | wrote "scanned 0, found 0" weekly | Same, plus real verdicts if any threads exist. |
| `telegram_ops.py:781` `_intent` | NL intent router | FAST | every plain message in the wholesale chat | silently failing | Resumes. |
| `telegram_agent.py:519` (`post_messages`, <=7 turns) | business-partner chat | SMART | every plain message in a business/HQ chat | "couldn't reach my brain" | Resumes. Write tools still produce a tap-card (`pgo:`), never auto-run. |
| `style_agent.py:156` `_distill` | rewrite Marcus voice | FAST medium | **systemd nightly** `/api/style/run {days:1}` | failing nightly | **Rewrites `Skills/yahjair-voice.md` every night from 1 day of data.** |
| `review_agent.py:240,267` `_analyst`/`_synthesize` | weekly review + Marcus playbook | FAST + FAST medium | **systemd nightly `{days:1}` AND Mon 08:00** | failing | Overwrites `Skills/marcus-playbook.md` nightly with a 1-day view (agents/README #22). |
| `scout_triage.py:1044`, `marcus_screening.py:796`, `agency_agents.py:594,648` (Dyson, Eco) `learn` | playbook rewrite (+ Dyson/Eco also make a 2nd call to distill a coaching tip) | FAST medium | **systemd nightly**; ungated by `FORGE_SELF_IMPROVE` (F2) | failing | Five playbooks rewritten nightly, git-committed. |

**B. Fires only on an owner action or an opted-in flag (stays dark until someone asks):**

| Call site | Trigger | Gate |
|---|---|---|
| `daycare_director.py:803` Solomon brief (SMART medium) + `agency_eco.py:382` competitor read | `/api/daycare/director/run`; loop only if `FORGE_SOLOMON_BRIEF=1` | off |
| `daycare_director.py:937` Solomon learn, `deal_prep.py:541`, `dropship_director.py:661`, `mission_control_agent.py:404` learn | manual Learn buttons; auto only if `FORGE_SELF_IMPROVE=1` | off |
| `mission_control_agent.py:298` Orion brief | manual run; scheduled only if `FORGE_BRIEFS=1` | off |
| `agents_hub.py:408` `_director_chat` (Solomon/Midas/Orion/briefs, SMART) | `/api/hub/chat`, Agent Office chat/task/plan | owner |
| `agents_chat.py:215,247,288,321`, `marcus_chat.py:184`, `agent_collab.py:83,119` | Scout/Atlas/Marcus chat (+ up to 2 consult calls per answer) | owner |
| `agency_agents.py:436,486`, `agency_dyson.py:315`, `agency_eco.py:206,278`, `agency_build_studio.py:218`, `agency_callsheet.py:171` | Dyson/Eco chat, plans, draft fields, recommendations, competitor research, Build Studio, call-sheet PDF parse (regex fallback exists) | owner/UI |
| `agency_eco.py:329`, `daycare_ads_studio.py:195` | daycare enrollment ideas. **`GET /api/daycare/eco/ideas` makes a Claude call on a GET** (agents/README #25) | UI |
| `dropship_director.py:554,810`, `skill_forge.py:186`, `marcus_lead.py:107` | Midas (archived), skill forge (`FORGE_SKILL_FORGE=0`), Marcus directives (`do_today` loop off / `/directives`) | off |
| `toolkit_calc.py:300` | ARV lookup with web_search tool (effort medium) | button |

### 2.3 Stays dark vs stays lit (zero Claude)

**Zero-Claude and working right now:** Mission Control tiles, Owner Actions, Agent Control Center registry, Agent Office state + Orion check-in + status replies, bus + coach feed reads, Brain (tree/search/graph/undo), System Health, Costs, action log, backups, mobile shell, Telegram transport + `/status /starts /logins /pin` + ops slash commands, Solomon · Leads and · Starts lanes, Scout rule scoring + HOT auto-tag/auto-pipe, Follow-up scheduling, sms_guard / DNC / price-scrub, Stripe links / invoicing, agency call center + call sheet (regex import), contract poller, graphify, daily brief/recap (off, zero-Claude anyway).

**Dark until credits return:** everything in A and B above. Also dark and *not* fixed by credits alone: the Meta ad reads for the daycare (invalid token, separate from Anthropic), Orion's stale brief (needs a manual run), the 69-lead screening backlog, Solomon's brief (knob off), Atlas for old deals.

### 2.4 Retry / backoff / breaker — direct answers

* Do failing loops hammer ~4k failed calls? Yes, one loop does: `daycare_replies`, ~1 call/min, ~1,440/day, because nothing ever marks a draft as "tried" when the call fails and the interval never widens.
* Is there a circuit breaker? **No.** The state needed for one already exists (`ai_health.hardBy`, per-key fingerprint, `since`) but no request path reads it.
* Does the 15 min -> 6 h backoff help? Only for Solomon's (disabled) brief loop.

---

## 3. Proposed circuit breaker (design only — no source edited)

Goal: while a key is hard-down (billing/auth), make **zero** Anthropic requests except one probe per back-off window, everywhere, without touching each call site.

1. **State (reuse `ai_health.json`).** In `forge_heartbeat.py` beside `ai_ok/ai_fail` (`:254-271`) add `ai_gate(key) -> None | str`:
   * no `hardBy[fp]` entry -> `None` (closed, allow);
   * entry exists -> compute `probeAt` (stored on the entry; initial = `since` + 15 min, then doubling 15, 30, 60, 120, 240, 360 min, capped 6 h — same ladder Solomon's brief already uses);
   * if `now >= probeAt`: under `_LOCK` bump `probeAt` first and return `None` so exactly **one** caller is the half-open probe;
   * else return a reason string `"AI circuit open - Anthropic credit balance exhausted; next probe HH:MM"`.
   `ai_ok` already pops the fingerprint (closes the breaker); `ai_fail` on a probe keeps it open and doubles the step. A replaced key has a new fingerprint, so it is never blocked; `_ai_reconcile` already drops retired fingerprints.
   Scope to *hard* kinds only (billing/auth); transient 429/5xx keep today's 2-retry behavior.
2. **One choke point for requests.** `review_agent.post_messages` (`review_agent.py:143`), before `claude_urlopen`:
   `why = forge_heartbeat.ai_gate(key); if why: raise RuntimeError("Anthropic API error (400): " + why)`.
   Keep the `Anthropic API error` prefix — `daycare_replies.py:463` and the Telegram/Office error text key off it. Do **not** call `_ai_health(False, ...)` for a blocked call (it never left the box, must not inflate `failStreak`).
   Make `marcus_engine._ai_draft` (`marcus_engine.py:931`) use the same gate (or route through `post_messages`) — it is the one site that bypasses the choke point. On a blocked draft return `draftSource:"ai_down"`, not `"template"`.
3. **Stop the hammering at the loop level too (saves GHL calls).** `daycare_replies.run_once` (`:389`): if the gate is closed, return `{"ok": True, "skipped": "ai_down"}` *before* the GHL `/conversations/search`. Beat the heartbeat with no error (the dedicated AI alert already exists) — this also ends the red/green flapping that floods the bus with watchdog alerts. Apply the same early-out to `telegram_ops._intent` (`:771`), Office `dispatch` (`agent_office.py:452`) and `skill_forge`.
4. **Fail closed where a human isn't watching.**
   * `legit_check.verdict` (`:118-123`): when the gate is closed or the judge errors, return `{"legit": False, "reason": "judge unavailable"}` for autonomous callers (autopilot gate 7); keep pass-through only for display callers.
   * `autopilot.maybe_send` (after gate 2, `autopilot.py:~117`) and `ace.apply` (before `marcus.approve`, `ace.py:~898`): refuse when `proposal["draftSource"] in {"template","ai_down","blocked"}`.
5. **Close the systemd hole.** `deploy/daily_learn.sh` and the Monday review: pre-flight `curl /api/system/health`, skip when `ai.hard`; and put `review_agent.self_improve_on()` inside the `learn()` methods themselves (`scout_triage.py:1003`, `marcus_screening.py`, `agency_agents.learn`, `style_agent.run`) for `auto:true` callers so the flag means what CLAUDE.md says.
6. **Owner controls + visibility.** Add `POST /api/system/ai/probe` (owner tap, forces `probeAt=now`) so a top-up is noticed in seconds, not up to 6 h; show "circuit open - next probe HH:MM" in the existing FIX row (`owner_actions._src_system`), System Health and the Agents banner; stamp failures with `threading.current_thread().name` so the next outage is attributable.
7. **Tests** (extend `test_ai_health.py` / `test_claude_retry.py`): while open, N calls -> 0 HTTP and exactly one probe per window under 20 concurrent threads; success closes; hard failure doubles the window; key rotation bypasses; blocked calls don't change `failStreak`; `daycare_replies.run_once` makes no GHL GET when blocked.

Expected effect: ~1,440+ failed calls/day -> <= ~10 probes/day for the whole fleet; recovery lag <= the current window, or instant with the probe button.

---

## 4. Agent-to-agent communication today: Dyson / Eco <-> Solomon

### 4.1 What exists

| Mechanism | Where | Dyson/Eco -> Solomon | Solomon -> Dyson/Eco |
|---|---|---|---|
| Bus `status` broadcasts to `all` | `agency_agents.py:508,629`, `agency_deploy.py:215`, `daycare_director.py:851,963` | Yes, informational | Yes, informational; nobody reads it |
| Bus `handoff` to a role | Solomon `daycare_director.py:859` (role string is LLM free-text) | — | Sent to `role.lower()` which is one of *Solomon's own* `BUS_ROLES` (`:67`) or an invented word; **never `eco`/`dyson`** |
| Bus `task` | `agents_hub.py:593`, `agent_office.py:501` | Operator/Orion only | Operator/Orion only |
| Hub task store (`open_tasks_block`) | `agents_hub.py` | seen in chat prompts only | same |
| `agent_coach.broadcast` -> bus kind `coach` + vault `Coaching/feed.md` | `agent_coach.py:124-152` | **Only automatic broadcaster in the system**: Dyson/Eco `learn()` distills 1 tip to `to="all"` (`agency_agents.py:637-655`) | none — `daycare_director` never calls `broadcast` (grep: only `agency_agents.py:651` + the manual route) |
| `agent_coach.ask` (Q&A via target's chat) | `agent_coach.py:235-258`, `POST /api/coach/ask`, `agents_hub.py:991` | Manual only (owner in the Agent Network tab); costs a Claude call | same |
| `insights_block` injected into `learn()` | Solomon `daycare_director.py:933`; Dyson/Eco `agency_agents.py:590`; also Scout/Marcus/Atlas/Midas/Orion | yes | **only inside `learn()`** |
| `agent_collab` consults | `agent_collab.py` | Marcus <-> Scout only (regex `SCOUT|MARCUS`) | — |
| Direct code reuse | Solomon's ideas/competitor read call `agency_eco.daycare_enrollment_ideas` / `_daycare_competitor` (`agency_eco.py:329,382`) via a locked env-swap in `daycare_growth.py` | — | The real Eco<->daycare link; **no bus trace, no shared learning** |

Routing tables: `agents_hub.LANE_OF` (`agents_hub.py:157`: lane -> owner; used for chat/tasks/office/registry), `daycare_director.BUS_ROLES` (`:67`), `agent_coach.BUSINESS_OF` (`agent_coach.py:36-41`: a *third*, independent map).

### 4.2 Does FORGE_SELF_IMPROVE=0 mean coaching is never absorbed?

Short answer: **for Solomon, yes. For Dyson/Eco, no — and that is itself a bug.**

* The flag gates only the *in-process auto-learn* triggers: `daycare_director.py:867`, `agency_agents.py:663`, `scout_triage.py:796`, `deal_prep.py:483`, `marcus_screening.py:748`, `mission_control_agent.py:370`, `dropship_director.py:606`.
* Solomon's `learn()` (and therefore the only place his coaching block is read) runs only from those triggers or the manual Learn button. **Solomon is not in `daily_learn.sh`**, so with the flag off he never absorbs anything unless the owner presses Learn.
* Dyson and Eco *are* in `daily_learn.sh` and their `learn()` has no flag check, so the nightly systemd job still runs their `learn()` — absorbing peer insights and broadcasting a new tip — whenever credits work. Today it fails nightly on credits.
* Net: the only running pipeline is agency -> everyone via a tip that Solomon absorbs only if someone presses his Learn button; nothing flows daycare -> agency.

### 4.3 Gap list (file:line)

| # | Gap | Evidence |
|---|---|---|
| G1 | **Coach feed is empty on the box even though insights exist.** The bus is the declared source of truth (`agent_coach.py:15-19,101-107`) but capped at 200 messages across all kinds (`agent_bus.py:32,93`). 122 of the live 200 are watchdog alerts, so the two Jul-30 tips were evicted. The durable copy `Coaching/feed.md` (written at `agent_coach.py:155-183`) is write-only. | live `/api/coach/feed` = `[]`; vault `Coaching/feed.md` has eco + dyson entries dated 2026-07-30 |
| G2 | One-way network: only Dyson/Eco ever broadcast automatically (`agency_agents.py:651`). Solomon, Scout, Marcus, Atlas, Midas, Orion never do. | `grep agent_coach.broadcast` |
| G3 | Insights reach only the playbook-rewrite prompt. Solomon's brief (`daycare_director.py:803`), enrollment ideas (`agency_eco.py:329`) and chats never include `insights_block`. A tip has no effect until a successful `learn()` rewrites a playbook. | `grep insights_block` (8 sites, all in learn/synthesize) |
| G4 | `FORGE_SELF_IMPROVE` semantics are inconsistent (above): Solomon never auto-absorbs; Dyson/Eco/Scout/Screening/Voice/Review still learn nightly from systemd regardless of the flag. CLAUDE.md §5 says "All scheduled self-improvement is OFF" — false for `deploy/daily_learn.sh:27-37`. | `scout_triage.py:1003` (no gate) vs `:796` (gate) |
| G5 | Solomon's bus reader swallows coach tips as "delegations": `_read_bus_inbox` (`daycare_director.py:526-550`) calls `agent_bus.inbox(role)` for 9 roles; `inbox` includes `to=="all"` of any kind (`agent_bus.py:122-127`), then `mark_read` is global. Dyson/Eco status + coach broadcasts land in `busDelegations` (`:782`) and are marked read for everyone. No `kind` filter. | code |
| G6 | Solomon cannot actually delegate to Eco/Dyson: handoffs go to LLM-chosen `role.lower()` (`daycare_director.py:859`); his `BUS_ROLES` are his own names so he re-reads them himself; Dyson/Eco never read the bus at all (only hub tasks in chat). The same shape exists for Midas (`dropship_director.py:598`). | code; agents/README #13 |
| G7 | Bus kinds silently coerced: `directive` (`marcus_lead.py:120,124`) and `ask` (`agent_collab.py:38`) are not in `KINDS` (`agent_bus.py:28`) so they become `note` (`:74-76`) — not filterable, not routable. | code |
| G8 | Three inconsistent agent maps: `LANE_OF` (hub), `BUSINESS_OF` (coach), `BUS_ROLES`. `agent_coach.BUSINESS_OF` lacks `ace, followup, autopilot, orion, daycare_replies, daycare_leads, daycare_starts`; `ask(to="daycare_leads")` -> "unknown agent" (`agent_coach.py:245`); Orion learns with business `"mission"` (`mission_control_agent.py:400`), which no broadcast ever targets. | code |
| G9 | No consumed/absorbed marker: `insights_for` returns the newest 8 every time (`agent_coach.py:187-231`, `since_ms` never passed), so the same tips are re-injected each `learn()` and old ones roll off after 8. | code |
| G10 | The Eco<->daycare link is a direct function call with a locked env swap, not comms: Eco's agency-side learned playbook/tips never inform Solomon's ads angle and Solomon's results never flow back. | `agency_eco.py:329,382`; `daycare_growth.py` |
| G11 | `ask()` depends on the target's chat (Claude) and records the answer only to the asker (`agent_coach.py:257`); with credits out the whole feature is dead, and it is not exposed to agents (only the owner UI). | code |
| G12 | Secret-guard false positives: any >=20-char non-space run containing a letter and a digit (URLs, ids) drops the whole insight (`agent_coach.py:74-84`). Safe but lossy. | code |

Recommended minimum fixes: (1) exempt `kind=="coach"` from the 200 cap or give coach its own store, and make `feed()` fall back to parsing `Coaching/feed.md`; (2) filter `kind` in `_read_bus_inbox` and stop marking others' broadcasts read; (3) add `insights_block` to Solomon's brief/ideas prompt and let `learn()` callers broadcast a tip; (4) one shared `AGENT_MAP`; (5) decide the truth for `FORGE_SELF_IMPROVE` and either gate the nightly curls or update CLAUDE.md.

---

## 5. Findings list (ranked)

| # | Sev | Finding | Where |
|---|---|---|---|
| F1 | High | No circuit breaker; `daycare_replies` makes ~1 failed Sonnet call/min (and a GHL search) indefinitely; `ai_health` already knows the key is hard-down but nothing consults it. | `daycare_replies.py:464,677`; `review_agent.py:143`; `forge_heartbeat.py:254` |
| F2 | High | `FORGE_SELF_IMPROVE=0` does not stop nightly self-improvement: `forge-daily-learn.timer` runs scout/screening/voice/review/dyson/eco learn every night; on credit return it will rewrite `marcus-playbook.md`, `yahjair-voice.md` and three other playbooks from 1 day of data without any tap. | `deploy/daily_learn.sh:27-37`; `scout_triage.py:1003`; `style_agent.py`; box timers |
| F3 | High (latent) | Autopilot/ACE fail open under an AI outage: `legit_check.verdict` returns `legit:true` on a judge error, `_ai_draft` returns a generic template on any failure, and neither autopilot nor ACE checks `draftSource`. Two `template` drafts are already in the approval queue. Safe today only because autopilot and ACE are off. | `legit_check.py:118-123`; `marcus_engine.py:970-981`; `autopilot.py:106-145` |
| F4 | Medium | Outage is ~2 months old (last success 2026-08-01), not 8 days; every surface says "down since 2026-09-22". Orion/Mission Control show a 2-month-old brief; Costs shows $0 with no banner. | cost_tracker.json mtime, `/api/mission-control/brief`, `cost.jsx` |
| F5 | Medium | Coaching network is effectively dead (empty feed, one-way, learn-only absorption, bus eviction, Solomon's reader eats tips). | section 4 |
| F6 | Medium | Watchdog flap spam: `daycare_replies` toggles red/green so the bus gets a new "DOWN" alert each cycle (69 + 39 in the live 200) and the daycare Telegram chat is re-pinged every 15 min. | `connector.py:1916-1926` |
| F7 | Medium | Daycare Meta token invalid but surfaced nowhere: registry computes `meta` for Dyson only; Mission Control shows it only as "Not connected: Meta Ads" under daycare; 5,118 log lines. | `agents_hub.py:955`, `agency_ads.py:366-376` |
| F8 | Low | Wholesale operationally dormant (maintenance flag, no fresh proposals since 2026-08-27) while Mission Control shows "17 hot leads waiting on a call" — stale numbers with no age. | `/api/mission-control`, `/api/marcus/proposals` |
| F9 | Low | Backups are on-box only; vault root contains an untracked `.env`; box vault has uncommitted rsynced edits. | `backup_state.sh:6`; box vault `git status` |
| F10 | Low | Doc drift: agents/README says `daycare_replies` interval 300 s (code 60 s, `daycare_replies.py:56`); `maintenance` flag undocumented; CLAUDE.md "scheduled self-improvement OFF" (F2); archive described as hiding Midas from the Agent Control Center (registry still returns him). | docs vs code |

Not covered / unverified: the mobile UI was not exercised on a device; daycare "Response time 1s" and Mission Control wholesale counts were not re-derived; the source of the other ~1,900 unattributed failed calls is unknown (no per-caller failure ledger).
