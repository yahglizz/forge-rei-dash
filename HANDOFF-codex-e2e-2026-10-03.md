# HANDOFF → CODEX — wire FORGE REI OS end to end (broken things only)

**Written 2026-10-03 by Claude. Repo `/Users/yg4st/forge rei dash` (public `yahglizz/forge-rei-dash`). Box `root@24.199.81.124`, service `forge-reios`.**

**Goal:** dashboard + agents + chats working on **web, mobile (`/m/`) and Telegram**, 24/7 on the box.
**Scope:** only what is broken or unproven. Working things are listed once (§2) so you don't re-audit them.

Read first: `CLAUDE.md` (rules win), `NORTH_STAR.md`, `agents/README.md`. Older, broader audits exist
(`CODEX_END_TO_END_AND_UI_TASK.md`, `HANDOFF-solomon-2026-09-30.md`) — this file supersedes them for
current state.

## 0. Hard rules (violating one = outage or a real text to a real person)

1. **No build step.** Static React + in-browser Babel; Python stdlib only. No bundler/framework/deps.
2. **JSX collisions = white screen.** Unique hook aliases + unique top-level names per file; no computed JSX tags. Validate: `node "forge rei/deploy/valjsx.js" FILE`. Python: `python3 -c "import ast; ast.parse(open('FILE').read())"`.
3. **Rule 2 — propose → approve.** Never auto-send SMS, launch ads, move pipeline, spend. Do not flip `ACE`, `autopilot`, `FORGE_DAYCARE_REPLY_AUTO`, or `ads-auto` modes. Only the operator flips them.
4. **No price over text, ever** (`marcus_engine._no_price_over_text`).
5. **Secrets:** never print/commit `*.env`; never `cat /etc/default/forge-reios` (grep for a var name). Must stay 404 over HTTP.
6. **Box runs the loops** (`FORGE_MARCUS=1`). Mac is `FORGE_MARCUS=0`, UI-only — never run loops locally.
7. **Don't touch live Anthropic/Stripe/GHL state** to "test". Tests use `FORGE_ACTION_LOG=<tmp>`; never run Agentic-OS `node --test`.
8. **Deploy:** `git push origin main` → box auto-pulls ≤60s (`forge-autopull.timer`). Instant: `./deploy/quick-deploy.sh`. Secrets/vault changed: `./deploy/push.sh root@24.199.81.124`. A commit failing validation aborts and the live version keeps running.
9. **Audits/reviews run on Sonnet 5, not Opus** (CLAUDE.md rule 10).

## 1. Probe results (2026-10-03 ~15:50 UTC, from the box) — what's actually broken

| # | Finding | Evidence | Owner-only? |
|---|---------|----------|-------------|
| **B1** | **Anthropic credits exhausted → every agent/chat is DEGRADED.** Hard-down since ~Sep 22 (`downSince 1790086841092`), `failStreak 4263`, health `ok:false`. Marcus last success Jul 27, Solomon Aug 1. | `GET /api/system/health` → `ai.kind=billing`; `GET /api/agents/registry` → Marcus/Dyson/Solomon `DEGRADED`, `dependencyHealth.ai=down` | **YES — operator tops up the account / replaces key.** Not fixable in code. Code work is B2 + the recovery check (§4). |
| **B2** | **Hub chat has no offline fallback.** With AI down `POST /api/hub/chat {"agent":"marcus"}` returns `"Hit an error reaching my brain: Anthropic API error (400): [circuit open] …"` — raw error as the reply. `POST /api/office/chat` already degrades correctly (`offline:true`, answers from live floor state). Same raw-error path for `/api/agents/chat`, `/api/agency/agents/chat`, `marcus_chat`, `_director_chat`, Telegram partner. | Reproduced on box. `agents_hub.chat` (agents_hub.py:501), `agency_agents.chat` (:400), `agent_office.chat` is the model to copy | no |
| **B3** | **Meta log spam + one dead token.** 5,118 lines of `[ads] live fetch failed, falling back to mock: Meta 400: Invalid OAuth access token - Cannot parse access token` in `/opt/forge/connector.err.log`. `daycare.env` has a `META_ACCESS_TOKEN` that Meta rejects; Pipeboard (`PIPEBOARD_API_TOKEN`) is the working path and `/api/agency/ads` correctly reports `via:"pipeboard", dataSource:"live"`. Some path still tries the raw token first / every poll. | `grep -c "live fetch failed" /opt/forge/connector.err.log` = 5118 | Token rotate/removal = owner. Make Pipeboard-first + throttle the log = Codex. |
| **B4** | **`daycare_replies` error counter climbs 2,306+** while status shows green. Each 60 s sweep records an error under the open AI breaker instead of skipping silently; makes Solomon's `errorCount` meaningless and buries real errors. CLAUDE.md says the sweep "skips its whole sweep while open". | health `loops[daycare_replies].errorsTotal=2306`; Solomon registry `errorCount:2306` | no |
| **B5** | **Telegram unproven end to end.** `/api/notify/settings`: `lastError:"The read operation timed out"`, `lastSentAt 1790836413` (≈2.4 days ago). Bot polling is alive (`agentLoop.polls 4136`, `telegram` + `telegram_agent` loops green; `telegram_agent` 17 lifetime errors, last Oct 2). The partner agent (plain-message → tool loop) needs Claude, so it is also dead until B1. Per-biz chats bound: wholesale/agency/daycare ✔, dropship ✘ (archived — fine). | notify settings JSON above | no |
| **B6** | **`test_agent_registry.py` fails (stale test).** `test_solomon_owns_reply_and_lead_lanes` asserts `hb == [replies, leads, starts]`; code now returns `[replies, leads, starts, daycare_ads]`. Update the test (the code is right). | run it: exit 1, only failure of 64 | no |
| **B7** | **Junk tracked in git:** `.swarm/agentdb-memory.db{,-shm,-wal}` and `forge rei/.swarm/{agentdb-memory.db*,ewc-fisher.json}` show modified on every session → noisy auto-sync commits, merge risk between Mac and PC. `git rm --cached` + `.gitignore` both `.swarm/`. | `git status` | no |
| **B8** | **Box headroom is thin.** 961 MB RAM, ~80 MB free, 43 MB swap used (1 GB swapfile). No OOM in 24 h, connector peaks ~120 MB. Not broken — watch it; don't add resident threads/caches. | `free -m`, `journalctl … oom` = 0 | no |
| **B9** | **Verify, don't assume:** (a) `forge-daily-learn.timer` still fires nightly 00:00 UTC although `FORGE_SELF_IMPROVE` is meant to be OFF — confirm the unit honors the knob and isn't spending/rewriting playbooks; (b) `GET /api/mission` and `GET /api/review` return 404 — confirm which route Mission Control and the AI Weekly Review card actually call (`/api/review/run` is POST) and that the UI doesn't hit a dead route; (c) `GET /api/daycare/ads` returned no `dataSource`/`via`/`dateRange` keys — CLAUDE.md §10 says ad payloads carry them. | probes | no |

### Owner-only queue (do NOT try to clear in code — surface only)
- Top up Anthropic credits (B1). Stripe available balance $0 (info).
- 38 Marcus seller replies + 50 pending approvals, 5 Solomon reply drafts, 13 daycare leads needing a human, Solomon task "Confirm infant room capacity". These are the operator's taps (rule 2).
- Dead `META_ACCESS_TOKEN` in `forge-daycare/config/daycare.env` (B3).

## 2. Verified working — do not re-audit

- Box: `forge-reios` + `forge-autopull.timer` active; deployed SHA `d5105ec` = `origin/main`; disk 20 %; backup timer 03:30 ET ok.
- **All 129 GET routes in `connector.py` `ROUTES` return 200** on the box (sole non-200: `/api/portal/bootstrap` 405 = POST-only, expected). `/` and `/m/` serve 200.
- Secrets 404 over HTTP: `/config/ghl.env`, `/forge-telegram/config/telegram.env`, `/marcus_state/telegram.json`, `/.env`.
- 13 heartbeat loops green: atlas, contract, daily_brief(clock), daycare_ads, daycare_leads, daycare_replies, daycare_starts, followup, graphify, scout, telegram, telegram_agent, watchdog.
- Every `.jsx` in `forge rei/` and `forge rei/mobile/` passes `valjsx.js`.
- Python tests: 63/64 pass (only B6 fails). Run: `cd "forge rei" && for t in test_*.py; do FORGE_ACTION_LOG=/tmp/act.jsonl FORGE_MARCUS=0 python3 $t >/tmp/o_$t.txt 2>&1 || echo "FAIL $t"; done`
- `POST /api/office/chat` degrades gracefully with AI down (the pattern B2 should copy).
- Agency Meta read is live via Pipeboard. Stripe live and healthy. GHL (`crm`) ok.

## 3. Work for Codex (in order)

1. **B2 — offline fallback for every chat surface.** One shared helper (put it next to `agent_office.chat`'s offline logic; reuse, don't duplicate) that, when `review_agent` raises/returns an AI-down error (circuit open, billing, auth), returns `{"reply": <live-state answer>, "offline": true, "aiError": <short>}`. Wire into: `agents_hub.chat` (`/api/hub/chat`, `/api/agents/chat`), `agency_agents.chat`, `marcus_chat`, `_director_chat`, `telegram_agent` (reply on Telegram with the same live-state text + "AI offline"; the zero-Claude `/status /starts /logins /pin` fallbacks must still work). Web `agent_center.jsx` / `agents_hub.jsx` and mobile `mobile/m_agents.jsx` must render `offline` with a visible "AI offline" badge — **no raw `Anthropic API error (400)` string in any UI**. Never fabricate agent reasoning (creed: say what's live, label it offline).
2. **B4** — in `daycare_replies` sweep: when `review_agent` breaker is open, return early *before* recording an error; heartbeat stays green/"paused: AI down". Add/extend `test_daycare_replies.py` + `test_ai_breaker.py`. Confirm `errorsTotal` stops climbing on the box.
3. **B3** — make Pipeboard the first and only read path whenever `PIPEBOARD_API_TOKEN` is set (`agency_ads`, `daycare_growth`, any `[ads]` caller); stop logging the same Meta 400 on every poll (log once per 15 min, mirror the existing 15-min rejection cache). Fix B9(c) so `/api/daycare/ads` carries `via` / `dataSource` / `dateRange`. Test: `test_eco_datasource.py`, `test_pipeboard_io.py`.
4. **B6** — update `test_agent_registry.py` expectation to include `daycare_ads`.
5. **B7** — untrack + gitignore `.swarm/` (both locations). Don't delete files on disk.
6. **B9 (a)(b)** — resolve and document the answers in the PR body; fix any dead route the UI actually calls.
7. **B5 — Telegram proof.** From the box: `POST /api/notify/test` (operator-approved: one test ping to HQ is fine, nothing else), confirm delivery, clear/explain `lastError "read operation timed out"` (if it's the long-poll timeout being recorded as an error, stop recording it). Verify each bound biz chat resolves (`/chats`), tap-to-approve cards still two-factor gated.
8. **Recovery check (needs B1 done by the owner).** After credits return, confirm within one cycle: `ai.ok` true, health `ok:true`, Marcus/Dyson/Solomon registry status leave `DEGRADED`, breaker closes (`FORGE_AI_PROBE_SEC` 900 s → force a probe by restarting the service if needed), `/api/hub/chat` returns a real reply, Telegram partner answers, Orion check-in works. Write the result in the PR/commit message. If the owner hasn't topped up, say so and stop — do not paper over it.

## 4. End-to-end acceptance (run on the box + both UIs; report pass/fail per line)

Web (`https://forge-reios.tail0a2dda.ts.net` or tunnel `open-dashboard.sh`): load all 4 workspace nav items (Dropship archived) with no console errors; Owner Actions renders; Agent Control Center lists 5 rows; each agent chat answers (live when AI up, labeled offline when down); Agent Office loads and "Check in on team" works with AI down; Brain tab reads/writes + git-commits; Costs tab renders.

Mobile (`/m/`, desktop browser at 375 px + iOS sim `./sim-run.sh` in `ios/ForgeMobile`): login portal → each of Wholesale / Agency / Daycare / Everything opens; Home, Inbox/Convos, Pipeline, Actions, Crew tabs render; Crew chat works/labels offline; daycare Messages lists threads and a *draft* approve is blocked outside 8am–9pm ET. **Do not send any real SMS — stop at the confirm() dialog.**

Telegram: `/status` and `/chats` respond; `/solomon …` routes to Solomon in the daycare chat; a refused cross-business message is refused; `pgo:` approval card posts but is **not** tapped.

24/7: `systemctl is-active forge-reios forge-autopull.timer`; all loops green for 30 min after the final deploy; `journalctl -u forge-reios --since -30min | grep -iE "traceback|error"` clean; deployed SHA == `origin/main`; no new restarts.

## 5. Deliverable

Small commits per item, each validated, pushed to `main` (box auto-deploys). Final message: per-B-number status (fixed / owner-blocked / not-a-bug + evidence), remaining owner actions, and the acceptance checklist results. Update `agents/README.md` "Known inconsistencies" and the relevant `agents/<biz>/<agent>.md` card if triggers change (`test_agents_docs.py` enforces it).
