# FORGE AI — Current Architecture (audit 2026-09-22)

Source of truth for the build: `FORGE_AI_MASTER_SPEC.md` (owner's spec). This file maps what
**exists today** so nothing working gets rebuilt. Read-only audit: nothing was deleted, no
production data or schema changed. One security guard was added (see §8).

Related: [FORGE_AGENTS.md](FORGE_AGENTS.md) · [FORGE_INTEGRATIONS.md](FORGE_INTEGRATIONS.md) ·
[FORGE_AUTOMATION_PLAN.md](FORGE_AUTOMATION_PLAN.md) · [FORGE_TEST_PLAN.md](FORGE_TEST_PLAN.md) ·
[FORGE_RUNBOOK.md](FORGE_RUNBOOK.md)

---

## 1. Repository

| Item | Value |
|---|---|
| Repo | `yahglizz/forge-rei-dash` — **PUBLIC** on GitHub. Branch `main` only. |
| Git state at audit | clean, HEAD `fc0f93c`, box HEAD identical |
| Mac auto-sync | launchd `com.forge.autosync` runs `forge rei/deploy/auto-sync.sh` every 60 s: `git add -A` → commit → pull --rebase → push. **Every saved file reaches GitHub in ≤60 s and production in ≤~3 min.** Uncommitted work never lingers. |
| Secret hygiene | `*.env` gitignored. Full-history scan (Stripe/GHL/Meta/GitHub/Slack/AWS/Anthropic/Google/Telegram/private-key patterns): **only placeholder `sk-ant-xxxx` hits** in `.env.example` files. Clean. |

### Layout
```
forge rei dash/
├── forge rei/            THE APP — ~106 Python modules + 51 desktop .jsx + 9 mobile .jsx
│   ├── connector.py      HTTP server + all background loops (single process)
│   ├── FORGE REI OS.html desktop entry (loads every .jsx, then app.jsx)
│   ├── mobile/           PWA (wholesale-centric)
│   ├── portal.html       agency client portal (public via Funnel, separate listener)
│   ├── deploy/           push.sh, quick-deploy.sh, deploy-pull.sh, autopull.sh, auto-sync.sh, valjsx.js, live_smoke.py
│   └── test_*.py         ~33 test files (see FORGE_TEST_PLAN.md)
├── forge-agency/  forge-scout/  forge-marcus/  forge-solomon/  forge-daycare/
├── forge-telegram/  forge-dropship/  forge-mission/     per-business config (*.env, gitignored) + seed skills
├── marcus-wholesale-agent/   gitignored; holds the LIVE wholesale ghl.env + scripts marcus_engine imports — keep
├── docs/                     this documentation
└── CLAUDE.md / NORTH_STAR.md operating manual + constitution
```
Business-truth for the daycare lives **outside** this repo in the private
`~/Desktop/A Touch of Blessings — Brand Kit/` folder (website, forms, compliance, context).

---

## 2. Framework

| Layer | Technology |
|---|---|
| Frontend | React 18 UMD + in-browser Babel standalone, **no build step**. Components are `window` globals. Vendored React/Babel with SRI under `/assets/vendor/`. |
| Backend | Python 3 **stdlib only** (`http.server`, `urllib`, `threading`). One process: `connector.py`. |
| Persistence | JSON files in `forge rei/marcus_state/` (60+ stores, atomic writes + per-module locks), Supabase (daycare), GoHighLevel (CRM system of record for wholesale + daycare families), Obsidian vault (markdown, git-committed) for agent playbooks/reports. |
| AI | Anthropic Messages API via `review_agent._claude` (shared) + a direct call in `marcus_engine`. Models in code: `claude-sonnet-4-5` (6 refs), `claude-haiku-4-5-20251001` (4), `claude-sonnet-5`, `claude-opus-4-8`, `claude-fable-5` (1 each). |

---

## 3. Frontend

- Desktop: 51 `.jsx`, all loaded, **0 orphans**, all pass `deploy/valjsx.js`, 0 name collisions, 0 computed JSX tags.
- **Workspaces are hardcoded** in `data.jsx:68-73`: `rei` (16 nav items), `agency` (22, incl. a "Personal" lens), `daycare` (21), `dropship` (14). Only visibility state = `localStorage`. **No archive/enable flag exists anywhere.**
- Home = **Mission Control** (`mission_control.jsx`) — per-business attention cards, Orion CEO brief, subscription spend. Closest thing to the spec's CEO home.
- Mobile PWA (`mobile/`): 6 tabs — wholesale-only + agent chat. Daily brief / night recap config UI exists **only** on mobile.
- No React ErrorBoundary → one bad page white-screens the app. Archiving must hide nav, never stop loading files.

## 4. Backend

- `connector.py` ≈ **417 API routes**: GET `ROUTES` (126) + daycare GET (43) + dropship GET (31); POST allowlist (139) + daycare (57) + dropship (21); portal listener (1 page + 3 POSTs).
- Routes by business: wholesale 56 GET / 68 POST · agency 32 / 47 · daycare 43 / 57 · dropship 31 / 21 · system 38 / 24.
- All loops start in `connector.main()`, gated by `FORGE_MARCUS=1` (box only). Full loop table → [FORGE_AGENTS.md](FORGE_AGENTS.md).
- GHL client: `connector.GHLClient`, 3 instances (wholesale / agency / daycare sub-accounts), retries 429/5xx.

## 5. Database / data layer

| Business | System of record | Local stores (`marcus_state/`) |
|---|---|---|
| Wholesale | GHL wholesale sub-account | scout, screenings, deal_prep, proposals.jsonl (append-only, never compacted), followup, ace, autopilot, send_ledger, sms_guard, buyers, deals, … |
| Agency | **Local JSON** (`agency.json`) for clients; agency GHL sub-account for contacts/tags | agency_*, callsheet, calls, approvals, dyson, eco |
| Daycare | **Supabase** (RLS) for children/staff/attendance/billing; daycare GHL for families & leads; Stripe invoices | solomon, daycare_blast, daycare_form_children (GHL contact → child ledger) |
| Dropship (archive) | Shopify / AutoDS / Meta (read) | dropship, midas |
| Cross-business | Obsidian vault via `brain_io` | agent_bus (cap 200 msgs), hub_tasks, heartbeats, cost_tracker, spend_tracker, skill_forge, ops_clock |

**Drift:** dashboard copy of Supabase migrations (`forge-daycare/supabase/migrations`) is **9 migrations behind** the parent/staff app — the "byte-identical" contract is broken.

**Backups:** none. `marcus_state/` exists only on the box; box vault has no git remote.

## 6. Authentication / authorization

| Surface | Gate |
|---|---|
| Dashboard :7799 | Peer-IP allowlist (loopback + tailnet CIDR) + Host allowlist + same-Origin on POST. **No user login.** Tailscale Serve proxies from 127.0.0.1, so **tailnet membership = full operator access** (read CRM, send SMS). |
| Daycare routes | Cookie session (Secure/HttpOnly/SameSite=Strict). With `FORGE_DAYCARE_OPEN=1` (set on box), every Serve caller gets an auto-admin session — documented, owner-accepted trade-off (CLAUDE.md §10). |
| Client portal :10000 | Public via Tailscale Funnel :8443. Isolated handler, 3 token-scoped POSTs, `compare_digest`. Verified isolated. |
| Telegram | Taps need configured chat + (allowlist or operator-DM fallback). Default-deny. |
| Static files | Decode-then-check, resolved-path jail, extension allowlist; `.env`/`.git`/`marcus_state`/`.py` all 404 (verified live). |

## 7. Deployment / 24-7 infrastructure

| Component | Where | Notes |
|---|---|---|
| `forge-reios.service` | DO droplet `forge-reios` (1 vCPU, 1 GB RAM + 1 GB swap, 24 GB disk, Ubuntu 24.04) | Single Python process, `Restart=always`, 0 restarts / 0 OOMs, ~90 MB RSS. All agent loops live here. |
| `forge-autopull.timer` | box, every 60 s | `git reset --hard origin/main` → validate (py ast + jsx) → rsync code → restart → health check. Bad commit aborts; live keeps running. |
| `forge-daily-learn.timer` | box, 20:00 ET | POSTs learn/run routes for 6 agents. |
| `forge-review.timer` | box, Mon 08:00 UTC | **BROKEN** — unquoted JSON in `ExecStart`; weekly review never ran. |
| Tailscale Serve / Funnel | box | Serve → :7799 (tailnet only). Funnel :8443 → portal :10000 (public). |
| ufw | box | deny incoming except 22/tcp + `tailscale0`. |
| **Runs on the Mac (dev box)** | launchd | `com.forge.autosync` (code → GitHub), `com.agentic.brain-sync` (vault box→Mac, every 6 h), `com.graphify.brain-sync`. `~/Desktop/LeadScraper` (Apify) is Mac-only. **If the Mac is closed, production keeps running**; only vault mirroring to the Mac and lead scraping pause. |
| Not present | — | No n8n on the box (agency n8n points at an external workspace that returns 404), no cron jobs, no Docker, no queue system, no inbound webhooks (Telegram is long-poll). cloudflared binary present but unused/stale. |

## 8. Businesses — active vs archive

| Business / module | Status | Action |
|---|---|---|
| **Agency (ClientForge)** — business lens | ACTIVE | keep |
| **Wholesale (REI)** incl. Outbound/Retell page, `marcus-wholesale-agent/` | ACTIVE | keep |
| **Daycare (ATOB + AMT)** | ACTIVE | keep |
| **Dropship** (workspace, 12 py modules, `forge-dropship/`, Midas) | **ARCHIVE** | hide from UI; keep code/routes/data; scheduled loop already off; still feeds Orion's paid daily brief + Mission Control health pings → filter those |
| **Agency "Personal" lens** (MyBiz/MyAds/MySocial/MyStudio) | **ARCHIVE** | duplicates Daycare Growth + launches Dropship |
| Shared infra (Mission Control/Orion, Agents hub, Agent Office, Brain, Costs, Health, Telegram, bus, coaching) | KEEP | becomes the spec's top-level surfaces |
| Amazon / credit repair / Etsy | not in repo | nothing to archive |

Mechanism (none exists yet) → [FORGE_AUTOMATION_PLAN.md](FORGE_AUTOMATION_PLAN.md) P1-1.

## 9. Technical debt (ranked)

1. **AI brains down since 2026-08-01** — Anthropic credit balance exhausted; every Claude call 400s. Heartbeats wrap loops, not Claude calls, so health stays green → blind for 51 days.
2. **Phantom connector module** — `agents_hub.py:107` / `pixel_office.py:102` `import connector` while it runs as `__main__` → a second copy re-registers Telegram action callbacks onto stale engine objects. Risk: approve taps on the wrong objects, stale overwrites of `scout.json`. **Fixed in WP-A** (`sys.modules.setdefault("connector", …)` alias at the top of `connector.py`; a test pins the two importers).
3. **No agent registry** — agent lists duplicated in ≥8 places; Orion missing from most; heartbeat lacks last-success + cumulative error counts.
4. **No generic approval queue** — 10 separate queues; only Agency has an "Approvals" page.
5. **No durable agent action log** (spec §10) — bus capped at 200, per-engine activity lists in memory.
6. Solomon retry storm + invalid 32-char daycare Meta token — **backoff + auth-dead cache shipped in WP-A**; the token itself is an owner fix (P0-9).
7. Hidden-fail UI: ~34 data hooks ignore errors; n8n mock shown as "connected · LIVE"; agency approvals seed data ("Bloom Dental", "Peak Fitness") when state file missing.
8. Duplicates: 8 env loaders, ~8 Anthropic key resolvers, 4 liveness checks, 4 "morning brief" concepts, 4 task stores, 4 chat routers.
9. Undocumented autonomy: **ACE** (supervised/full modes auto-text sellers, default off) and **Orion** (8th Claude agent) missing from CLAUDE.md; CLAUDE.md's "zero Claude calls" claim for followup/do_today is wrong.
10. Logs have no timestamps; journald unbounded (1.2 GB); kernel reboot pending 107 days.

## 10. Security concerns

| Sev | Finding | Status |
|---|---|---|
| HIGH | `/api/brain/note?path=.env` served `vault/.env` (a GitHub PAT) to any tailnet device | **Fixed 2026-09-22** — `brain_io.read_note` serves `.md` only, never dotfiles (`test_brain_live.py`). Owner: rotate that PAT + delete `vault/.env` (unused on box). |
| HIGH | No operator auth behind Tailscale Serve (tailnet device = full CRM + SMS send) | By design. Mitigate with tailnet ACLs (only operator devices) + future session gate. |
| HIGH | Daycare open mode = admin for every tailnet device | By design (CLAUDE.md §10). `FORGE_DAYCARE_OPEN=0` restores the PIN. |
| MED | Six `*.env` files on box are mode 644, owner uid 501 (rsync from Mac) | chmod 600 + `push.sh --chmod=F600`. |
| MED | No backups of box-only state | P0 plan. |
| LOW | `FORGE_DAYCARE_TEST_MODE=1` on production box — confirm intended | owner check |
| LOW | Raw Meta exception text logged (`agency_ads.py:367`); refused Telegram taps log ids | cosmetic |
| OK | Portal isolation, static-file jail, Origin checks, cookie flags, git history — verified |

Independent review: Codex CLI (gpt-6-astra) confirmed the two HIGH trust-model findings and verified the safe list.

## 11. Reusable systems (do not rebuild)

`sms_guard` (single outbound SMS gate) · `marcus_engine._no_price_over_text` (pattern for a `_no_unverified_fact` guard) · `scout_triage` (poll → score → bucket → reversible tag) · `followup` · `autopilot.maybe_send` gates · `telegram_io` tap-to-approve · `forge_heartbeat` + watchdog · `cost_tracker` thread attribution · `agent_bus` + `agents_hub` tasks · `agent_creed` (un-rewritable evidence discipline) · `brain_io` · `mission_control` snapshot · `daily_brief` / `daily_recap` · `daycare_ghl` (lead vs enrolled, contact→child ledger) · `daycare_supabase` capacity reads · `agency_callsheet` + `agency_calls` (call queue + tally) · `agency_approvals_io` · website `/api/enroll` + GHL speed-to-lead workflow (private brand-kit repo).
