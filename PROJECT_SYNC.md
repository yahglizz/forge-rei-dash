# Project Sync Log

> Shared changelog for AI tools (Claude, Codex, etc.) working on this project.
> Read this file at the start of every session before making changes.
> Append new entries under Log — never delete old ones.

## Current State
- **Last updated:** 2026-07-11 17:05 EDT
- **Last updated by:** Claude
- **Status:** Project is now a git repo mirrored to https://github.com/yahglizz/forge-rei-dash (public). `deploy/push.sh` auto-commits + pushes to GitHub after every healthy deploy, so the repo always matches the live box. Box deploy path remains rsync via push.sh; the old `yahglizz/os` box cron pull (`/opt/forge/git-sync.sh`, every 60s) is dormant legacy.
- **Known issues:** `/tmp/valjsx.js` is absent; validation used the repository's `deploy/valjsx.js` helper used by deployment. Box git-sync cron still points at frozen `yahglizz/os` — harmless no-op but should be repointed or removed (audit item).
- **Next up:** Adversarial end-to-end review (grill-me-codex) of the whole app + box wiring; findings ledger will assign each fix an owner (Claude vs Codex).

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
