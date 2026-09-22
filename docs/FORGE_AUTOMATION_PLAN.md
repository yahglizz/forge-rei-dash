# FORGE AI — Automation Plan & Build Orchestration (2026-09-22)

Inputs every builder reads first, in order:
1. `~/Downloads/FORGE_AI_MASTER_SPEC.md` (owner spec — source of truth)
2. `CLAUDE.md` (rules — §2 rules outrank convenience) + `forge rei/CLAUDE.md`
3. `docs/FORGE_CURRENT_ARCHITECTURE.md`, `docs/FORGE_AGENTS.md`, this file

Priority key: **P0** foundation/critical · **P1** required automation · **P2** useful · **P3** later.

---

## 0. Ground rules for the build (non-negotiable)

- **Additive only.** Never remove a feature, route, file, or data. Archive = hide, not delete.
- **Propose → approve → execute** (CLAUDE.md rule 2). New code never sends SMS/email, moves money,
  launches/changes ads, or writes a CRM record on its own — unless it reuses an existing
  documented exception. Never flip ACE/autopilot modes on the live box.
- **Never invent facts** (creed). Unknown → say Unknown / escalate.
- **Secrets**: never read/print `*.env` values; never log tokens.
- **Frontend collision rules** (CLAUDE.md §7): unique hook aliases + prefixed globals per `.jsx`,
  no computed JSX tags, new `.jsx` must be added to `FORGE REI OS.html` before `app.jsx`.
- **Validate before merge:** `python3 -c "import ast;ast.parse(open(F).read())"` for every `.py`;
  `node "/Users/yg4st/forge rei dash/forge rei/deploy/valjsx.js" F.jsx` for every `.jsx`;
  run the relevant `test_*.py` (from `forge rei/`, `FORGE_MARCUS=0`, `FORGE_VAULT=<tmpdir>`).
  Do NOT run the 4 connector-importing tests against real state
  (`test_audit_hardening`, `test_audit_regressions`, `test_autopilot_routes`,
  `test_daycare_connector_contract`) unless you point `marcus_state` at a temp copy.
- **Deploy path:** the Mac's `com.forge.autosync` pushes `main` every 60 s and the box autopulls.
  **Builders work in isolated git worktrees and never touch the main working tree.** The lead
  integrates, reviews, tests, then merges to `main` (= deploy).
- Every new loop: named thread (cost attribution), `forge_heartbeat.beat()`, `forge_ops.paused()`
  check, and `forge_heartbeat.retire()` when switched off.
- Every non-trivial logic change leaves one runnable check (`test_*.py` or `__main__` assert).

---

## 1. P0 — foundation / critical

| # | Item | Owner | Status |
|---|---|---|---|
| P0-1 | **Top up Anthropic credits.** Every Claude call 400s since 2026-08-01 (all 3 keys on the box share one exhausted account). Blocks: Scout AI scoring, Marcus drafts, Atlas, Solomon, Orion, Dyson/Eco, every chat, every `learn()`. | **OWNER (money)** | open |
| P0-2 | Brain API served `vault/.env` (GitHub PAT) to tailnet | lead | **fixed + deployed** (`brain_io.read_note` md-only). OWNER: rotate that PAT; delete `vault/.env` (unused on box). |
| P0-3 | **AI health visible** — heartbeat `lastSuccessAt` / `errorsTotal` / `lastError`; `_claude` records a global AI-health signal (billing/auth errors); `/api/system/health` exposes it; watchdog Telegram-alerts once when AI goes down / recovers | WP-A | **built** (per-key hard-down) |
| P0-4 | **Solomon retry storm** — exponential backoff on failed brief; treat invalid Meta token as "not connected" instead of hitting Meta every 15 min | WP-A | **built** |
| P0-5 | **Phantom `connector` module** (`agents_hub.py:107`, `pixel_office.py:102` re-import the running `__main__`) → stale Telegram action handlers / double writers | WP-A (+ Codex review) | **built** (`sys.modules` alias) |
| P0-6 | **Backups** — nightly tar of `marcus_state/`, vault, configs → `/root/backups` (7-day rotation). Off-box copy / DO backups = owner decision (~$1–2/mo) | WP-F | **done on box** (`forge-backup.timer` 03:30 ET) |
| P0-7 | Box hygiene — journald cap + vacuum, stale logs, apt clean, env files `600 root`, `forge-review.timer` quoting fix, archive-then-remove dead items, kernel reboot | WP-F | **done** (22%→17% disk, journal 1.2G→161M, kernel 6.8.0-139) |
| P0-8 | Daycare compliance items in the private brand-kit compliance audit (licensing + staffing) outrank any daycare growth build | **OWNER** | open |
| P0-9 | Daycare `META_ACCESS_TOKEN` on box is not a real token (32 chars) → replace with a valid system-user token | **OWNER** | open |
| P0-10 | Tailnet = operator. Keep only operator devices on the tailnet (4 devices today: box, MacBook, iPhone, offline Windows PC). `FORGE_DAYCARE_OPEN=1` stays by owner choice | **OWNER** | review |

## 2. P1 — required automation

| # | Item | WP |
|---|---|---|
| P1-1 | **Archive mechanism**: `marcus_state/businesses.json`, `GET /api/businesses`, `POST /api/businesses/set`; switcher + Mission Control filter; Agency Personal lens guard; **Archived Businesses** page with Reactivate; backend skips archived (Mission Control snapshot, Orion gather, hub roster, pixel office, coaching). Seed: `dropship`, `agency:p` archived. + top-level React ErrorBoundary | WP-B |
| P1-2 | **Owner Actions v1** (spec §15): read-only aggregator `owner_actions.py` → `GET /api/owner-actions`: CALL / CALLBACK / APPROVE / REVIEW / FIX REQUIRED from existing sources; sort URGENT → REVENUE → CUSTOMER → NORMAL; dedupe; "TODAY — N ACTIONS" card at top of Mission Control; **Approvals** view = APPROVE-filtered list with deep links (v1: the card's Approve chip — no separate page) | WP-C |
| P1-3 | **Agent Control Center** (spec §9): `GET /api/agents/registry` (single roster: hub agents + Orion + follow-up + ACE + autopilot + briefs) with spec fields + statuses RUNNING/IDLE/WAITING FOR APPROVAL/DEGRADED/FAILED/DISABLED; top-level page; every agent **chat + task** reachable (reuse `agents_hub.chat` / `send_task`); add Orion to the hub | WP-D |
| P1-4 | **Daycare Lead Desk** (read-only): `daycare_leads.py` polls daycare GHL every 15 min, derives stage (NEW/CONTACTED/RESPONDED/NEEDS HUMAN), source, center, response time, overdue call tasks; `/api/daycare/leads`; KPI card (New Leads, Lead Response Time, Leads Needing Human Attention); Telegram ping on unanswered parent reply (business hours, deduped); feeds Solomon's brief. **Zero Claude calls, sends nothing** | WP-E |
| P1-5 | UI honesty debt: n8n mock labeled mock; agency approvals seed removed; DailyNonNegotiables + DealCalc error states; DashHealthDot/ClockCard errors; dead Mission Control jumps; the 2 failing tests | WP-G |
| P1-6 | Docs truth: document ACE + Orion in CLAUDE.md §2/§5; fix "zero Claude calls" claim; document Do-Today loop coupling | lead |
| P1-7 | Wholesale 30-second seller view: Atlas call card has no UI (`/api/prep/*`) — surface on HOT lead | next wave |
| P1-8 | Agency prospect engine on the box (LeadScraper is Mac-only) → daily READY-TO-CALL queue into the existing Call Sheet | next wave |
| P1-9 | Durable agent action log (spec §10) — append-only JSONL with retention | next wave |
| P1-10 | Daycare verified-facts file (owner-maintained, dated, Unknown by default) + tour stage/tag | next wave (owner input) |

## 3. P2 — useful

Cost attribution thread names (auto-screen, Orion, telegram_agent) · timestamps in connector logs ·
`proposals.jsonl` compaction · agent_bus retention for coaching · mobile Agency/Daycare tabs ·
model-id refresh (`claude-sonnet-4-5` → current) · dead alias routes · single env loader / key
resolver · desktop page for daily brief / recap config · Supabase migrations resync (9 behind).

## 4. P3 — later

Daycare AI draft replies (fact-gated `_no_unverified_fact` guard) · Meta Ads Agent with CAPI +
enrollment attribution · Retell voice for wholesale · cross-business P&L · Amazon shift widget ·
GHL calendar for tours.

---

## 5. Build orchestration — wave 1

Model tiering: **Fable** = hard / cross-cutting / concurrency · **Opus** = medium features ·
**Sonnet** = mechanical · **Codex CLI** = independent review of risky diffs. A **Fable reviewer**
checks every work package against the spec, CLAUDE.md rules and these docs before merge.

| WP | Scope | Model | Owns files (others must not edit) |
|---|---|---|---|
| **WP-A** | P0-3, P0-4, P0-5 | Fable | `forge_heartbeat.py`, `review_agent.py`, `daycare_director.py`, `connector.py` (top-of-file module alias + watchdog + `/api/system/health` only), `agency_ads.py` (Meta auth cache), `marcus_engine.py` (`_ai_draft` AI-health hunk), new tests |
| **WP-B** | P1-1 | Opus | new `business_scope.py`, `app.jsx`, `shell.jsx`, new `archived.jsx`, `mission_control.py`, `mission_control_agent.py`, `pixel_office.py`, `agent_coach.py`, `FORGE REI OS.html`; connector routes block B |
| **WP-C** | P1-2 | Fable | new `owner_actions.py`, `mission_control.jsx`, new `owner_actions.jsx`; connector routes block C |
| **WP-D** | P1-3 | Opus | `agents_hub.py`, `agents_hub.jsx`, new `agent_center.jsx` (reached from Mission Control / `forgeOpenView("agents")`, no nav entry), registry code in `agents_hub.py`; connector routes block D |
| **WP-E** | P1-4 | Opus | new `daycare_leads.py`, `daycare.jsx` (dashboard card only), `daycare_director.py` **only** a `_gather_leads` hook (coordinate with WP-A via small, separate hunk); connector daycare route + loop start |
| **WP-F** | P0-6, P0-7 (box ops via SSH) | Opus | box only + `deploy/setup_droplet.sh`, `deploy/push.sh`, new `deploy/backup_state.sh` |
| **WP-G** | P1-5 | Sonnet | `pages.jsx`, `toolkit_calc.jsx`, `agency_workflows_io.py`, `agency_approvals_io.py`, `dashboard.jsx`, `marcus.jsx`, `scout_triage.py` (`_rule_score` reason only), `test_marcus_filters.py` / `marcus_engine.py` path normalization |

`connector.py` is shared: each WP adds its routes as a **self-contained block with a
`# --- WP-X ---` comment**, never reformatting surrounding code, so the lead can merge cleanly.

**Wave 2** (after wave-1 merge + deploy + credits): P1-6..P1-10, then P2.

### First vertical slice (recommendation)

**Owner Actions v1 on top of truthful agent health (WP-A + WP-C).** It turns every existing
system into the one list the owner works from (CALL / APPROVE / REVIEW / FIX), sends nothing,
reuses existing stores, and — had it existed — would have raised "FIX REQUIRED: AI credits" on
2026-08-01 instead of 51 silent days. Second slice: **Daycare Lead Desk** (WP-E) — the enrollment
leak is follow-through, not capture.

---

## 6. Box cleanup policy (janitor)

Tiers from the 09-22 box audit (`docs/FORGE_RUNBOOK.md` §6 has commands):
- **SAFE** (regenerable/unreferenced): journald vacuum + 200 MB cap, `/var/log/dmesg`, `btmp`, apt cache, `__pycache__`, dead `git-sync.log` / `cloudflared.log` — **do**.
- **PROBABLY-UNUSED**: `retired-2026-07-25/`, stray `/root/Desktop/Agentic-OS`, `ruvector.db` ×3, `cloudflared` binary → **tar to `/root/forge-archive-YYYYMMDD.tgz` first**, then remove.
- **QUESTIONABLE → LEAVE**: `marcus-wholesale-agent/` (live key + imports), `forge-docusign/` (live), vault, `marcus_state`, uploads, repo, apt lists, swap, LLVM/bpftrace packages.
