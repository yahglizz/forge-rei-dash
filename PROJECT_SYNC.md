# Project Sync Log

> Shared changelog for AI tools (Claude, Codex, etc.) working on this project.
> Read this file at the start of every session before making changes.
> Append new entries under Log — never delete old ones.

## Current State
- **Last updated:** 2026-07-11 18:35 EDT
- **Last updated by:** Claude
- **Status:** Project is now a git repo mirrored to https://github.com/yahglizz/forge-rei-dash (public). `deploy/push.sh` auto-commits + pushes to GitHub after every healthy deploy, so the repo always matches the live box. Box deploy path remains rsync via push.sh; the old `yahglizz/os` box cron pull (`/opt/forge/git-sync.sh`, every 60s) is dormant legacy.
- **Known issues:** `/tmp/valjsx.js` is absent; validation used the repository's `deploy/valjsx.js` helper used by deployment. (resolved 2026-07-11 18:00: box git-sync cron, script, and token-embedded `os` remote removed — F9.)
- **Next up:** Audit CLOSED — 8/8 findings fixed, deployed, live-verified (see AUDIT-PLAN.md + PLAN-REVIEW-LOG.md). Remaining operator switches unchanged (FORGE_BLAST_LIVE, DocuSign prod/rotation).

## Log

### 2026-07-11 16:25 EDT — Codex — Initialize shared project sync log
**Changed:** `PROJECT_SYNC.md`
**What:** Created the shared project changelog from the supplied template.
**Why:** Establish a persistent source of truth for handoffs between Codex, Claude, and other tools.
**Result:** Documentation file created; no application behavior changed.
**Follow-up needed:** All future project edits must refresh the Current State block and append an entry here, including changes that affect shared APIs, configuration, or files.

---

### 2026-07-11 16:28 EDT — Codex — Confirm session sync protocol
**Changed:** `PROJECT_SYNC.md`
**What:** Updated the Current State block and recorded the standing requirement to read this file before edits and log every completed project change.
**Why:** Keep Claude, Codex, and other tools aligned on the repository’s active work and handoff expectations.
**Result:** Sync protocol is explicitly active; no application behavior or shared interfaces changed.
**Follow-up needed:** Any future feature, bug fix, refactor, configuration update, API change, schema change, or other file edit must add a new entry and call out shared-interface impact here.

---

### 2026-07-11 16:34 EDT — Codex — Add live sync between separate dashboard and mobile app
**Changed:** `forge rei/connector.py`, `forge rei/live_sync.js`, `forge rei/api.jsx`, `forge rei/mobile/m_api.jsx`, `forge rei/FORGE REI OS.html`, `forge rei/mobile/index.html`, `PROJECT_SYNC.md`
**What:** Added a no-cache `/api/sync` revision endpoint, incremented its revision after successful POST actions, and connected both separate frontends to a shared browser sync bridge with BroadcastChannel/storage fallback. Existing endpoint polling remains in place for external GoHighLevel changes.
**Why:** Keep the desktop dashboard and mobile app as separate projects while ensuring writes from either surface propagate live to other open sessions through the same 24/7 connector and server-side state.
**Result:** Python AST, both touched JSX files, and `live_sync.js` validated. Local UI-only smoke test returned `/api/sync` 200, desktop/mobile entry points 200, and protected state 404.
**Follow-up needed:** This changes the shared API contract (`/api/sync`) and both frontend data layers. Run `./deploy/push.sh root@24.199.81.124`, then verify the live service, `/api/sync`, `/live_sync.js`, `/mobile/`, and secret 404 checks on the box. The prescribed `/tmp/valjsx.js` helper still needs to be restored or standardized.

---

### 2026-07-11 16:35 EDT — Codex — Deploy and verify live sync contract
**Changed:** Remote `/opt/forge/forge-rei/` deployment state
**What:** Deployed the validated desktop/mobile sync changes with `deploy/push.sh` and ran the required remote health checks.
**Why:** Put both separate frontends and their shared `/api/sync` contract onto the 24/7 service.
**Result:** `forge-reios` is active; `/api/sync`, `/live_sync.js`, and `/mobile/` return 200; `marcus_state/heartbeats.json` and the external `ghl.env` path return 404.
**Follow-up needed:** Confirm an operator-approved write from dashboard and mobile while both are open; no API or config duplication is needed because both clients use the single connector state.

---

### 2026-07-11 17:05 EDT — Claude — GitHub mirror: repo init + auto-push on every deploy
**Changed:** `.gitignore` (new, repo root), `forge rei/deploy/push.sh`, `PROJECT_SYNC.md`
**What:** Initialized a git repo at the project root and pushed the full app (211 files) to https://github.com/yahglizz/forge-rei-dash (main). Added a best-effort GitHub mirror step to `deploy/push.sh` that runs after the post-deploy health gate: commits all changes and pushes to origin/main, warning (not failing) on push errors.
**Why:** Operator asked for the app to live on GitHub and stay always up to date with the deployed box.
**Result:** Initial push + first auto-mirror both verified (`c5a82fd..5677c67`). Secret scan before push: only placeholder `.env.example` values are tracked; `*.env`, `marcus_state/`, vault, and 318MB sibling `marcus-wholesale-agent/` are git-ignored. Deploy health gate passed.
**Follow-up needed:** Repo is PUBLIC — operator should confirm or flip to private. Box cron `/opt/forge/git-sync.sh` still pulls frozen `yahglizz/os` every 60s (dormant no-op) — repoint or remove during the audit.

---

### 2026-07-11 18:10 EDT — Claude + Codex — Fix all 8 audit findings, deploy, live-verify
**Changed:** `forge rei/connector.py`, `forge rei/deploy/push.sh`, `forge rei/toolkit_contracts.py`, `forge rei/test_toolkit_contracts.py`, `forge rei/pages.jsx`, `forge rei/review_agent.py`, `forge rei/mobile/m_api.jsx`, `forge rei/mobile/m_agents.jsx`, box crontab/remote (F9), `AUDIT-PLAN.md`, `PLAN-REVIEW-LOG.md`
**What:** Shipped the full audit ledger: shared agent thread now honored by desktop (history load) and Telegram (store-first); deploy gate validates mobile JSX; quick_send writes the ledger row before DocuSign; _claude handles pause_turn; useApiM stale-fetch guard; mobile roster merges dynamic agents; legacy box git-sync retired.
**Why:** grill-me-codex audit converged (3 rounds, APPROVED); operator gave the one sign-off.
**Result:** 68 py ast-clean, all JSX valjsx-clean, 13 suites green (contracts 20 tests). Health gate passed. Live-fire: Telegram ping ok, agent-chat history round-trip ok, sandbox envelope sent→voided through the new pending→sent path, live ARV ok, /api/agents/list serves 10 agents.
**Follow-up needed:** None for the audit. Shared-API note: /api/agents/history is now consumed by desktop AND mobile; keep its shape stable.

---

### 2026-07-11 18:35 EDT — Claude — Mobile: AI-reply approve/redo/dismiss + tap-a-person → thread
**Changed:** `forge rei/mobile/m_convos.jsx`, `forge rei/mobile/m_home.jsx`
**What:** (1) AI reply drafts now get quick Approve / **Redo (remake differently)** / Dismiss — in the Convos thread footer (draft → 3-button approve row) AND the Home approval inbox (added a Redo button; regenerated text is what Approve sends). Redo reuses `/api/reply/draft` with a "rewrite differently" hint (no backend change; `/api/marcus/approve` already honors a `message` override). (2) Tapping a person on Home (Scout hot-leads list + the full Hot Leads sheet) opens that seller's message thread — `MCThread`/`MCAvatar` are now exported from m_convos and mounted from m_home using the lead's existing contactId/convId.
**Why:** Operator wanted faster reply triage (remake a different AI reply in one tap) and direct person → messages navigation from Home.
**Result:** Both mobile JSX validated (now gated on deploy per F6). Deployed + GitHub-mirrored (5f0365d..ce88b0e). Live-verified on the box via DOM drive: tapping a lead opens the thread; Draft (AI) returns a Claude draft and the footer switches to Redo / Approve & send; Home approvals render Approve / Redo / ✕.
**Follow-up needed:** None. No shared-API changes (reused /api/reply/draft + /api/marcus/approve).
