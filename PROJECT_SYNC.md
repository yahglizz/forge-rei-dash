# Project Sync Log

> Shared changelog for AI tools (Claude, Codex, etc.) working on this project.
> Read this file at the start of every session before making changes.
> Append new entries under Log — never delete old ones.

## Current State
- **Last updated:** 2026-07-11 16:35 EDT
- **Last updated by:** Codex
- **Status:** Desktop dashboard and mobile app remain separate frontends with a shared connector revision channel for live cross-session updates; the change is deployed and verified on the 24/7 box.
- **Known issues:** `/tmp/valjsx.js` is absent; validation used the repository's `deploy/valjsx.js` helper used by deployment.
- **Next up:** Exercise a real approved write from each surface and confirm the other open surface refreshes immediately; retain normal polling for external GoHighLevel changes.

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
