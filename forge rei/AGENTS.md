# AGENTS.md — FORGE REI OS (read before editing)

This is a live 24/7 real-estate-wholesaling + AI-agency dashboard. The code here runs on a
DigitalOcean box (`root@24.199.81.124`, service `forge-reios`, port 7799). **Editing files
here changes NOTHING on the live box until you run the deploy script.** Full detail lives in
`CLAUDE.md` (same folder) — this file is the short operating contract.

## Golden rules
1. **Additive edits only.** Don't delete working features/code. Don't rotate or print secrets.
2. **Secrets stay out of the web root.** API keys live in `*.env` / `*.pem` files OUTSIDE this
   folder, git-ignored, and must 404 over HTTP. Never paste a key into a file here or into chat.
3. **No build step.** The UI is React UMD + in-browser Babel. `.jsx` files load as
   `<script type="text/babel">` in `FORGE REI OS.html`. A syntax error or collision = white
   screen on the LIVE dashboard. Validate before every deploy (below).
4. **Validate → deploy → verify, in that order. Never push a broken state.**

## JSX collision rules (break one = white screen)
Every `.jsx` shares ONE global scope after Babel. So:
- **Unique hook aliases per file**: `const { useState: useStateP } = React;` — each file uses its
  own suffix (`useStateP`, `useStateM`, `useStateAg`, `useStateD`, …). Never reuse across files.
- **No computed JSX tags**: `<Icons[x] />` is forbidden. Resolve first:
  `const Ico = Icons[x] || Icons.Bot;` then `<Ico/>`.
- **Unique top-level names** across all files (components, consts) — shared scope, no shadowing.
- Components are exposed as `window` globals via `Object.assign(window, { ... })` at file end.

## Backend pattern (`connector.py`, Python stdlib, no deps)
- GET routes: add to the `ROUTES` dict (+ `NO_CACHE` if it must not cache).
- POST routes: add the path to the `do_POST` allowlist tuple AND an `elif` dispatch branch.
- Handlers read query as `q.get("key", [None])[0]` (values are lists).
- JSON stores live in `marcus_state/` — write them via `forge_atomic.atomic_write_json` (atomic).
- GHL calls go through `ghl_get` / `ghl_post` / `ghl_put` (retry + auth already wired).

## Validate (run from this folder before deploying)
```bash
# Python — every .py you touched:
python3 -c "import ast; ast.parse(open('connector.py').read())"
# JSX — every .jsx you touched (Babel transform + computed-tag scan):
node /tmp/valjsx.js pages.jsx
```
If `/tmp/valjsx.js` is missing, ask the operator — do not skip JSX validation.

## Deploy to the live box (the ONLY way changes go live)
```bash
./deploy/push.sh root@24.199.81.124
```
Needs SSH key `~/.ssh/forge_droplet` on this machine (works from the Mac; will NOT work from a
remote/cloud sandbox that can't reach the box). The script rsyncs the app, restarts the service,
and re-runs `deploy/setup_droplet.sh`. It does NOT ship `marcus_state`, `*.env`, `.git`, or keys.

## Verify after deploy (SSH-check — don't assume)
```bash
ssh -i ~/.ssh/forge_droplet root@24.199.81.124 'systemctl is-active forge-reios; curl -s --max-time 8 http://127.0.0.1:7799/api/health'
```
Expect `active` + `{"ok": true, ...}`. Confirm any new endpoint returns 200 and any secret file 404s.

## The 24/7 agents (don't make them text sellers without a gate)
- **Scout** (`scout_triage.py`) scores/triages every inbound, auto-tags hot, hands to Marcus. Never texts.
- **Marcus** (`marcus_screening.py`) screens leads → call-ready reports. Outbound SMS is gated (operator approves).
- **Follow-up** (`followup.py`), **agency** (`agency_agents.py`), contract poller — all in `connector.py`'s loops.
- Propose → review → execute for any outward action (SMS / pipeline move / ads / contract send).
  The operator's one click IS the approval. Don't auto-fire outward actions.

## Local UI-only run (safe — does NOT touch GHL or sellers)
```bash
FORGE_MARCUS=0 FORGE_PORT=7799 python3 connector.py   # then open http://localhost:7799
```
`FORGE_MARCUS=0` = UI only, no poll/triage loops (so you never double-contact a seller while testing).
