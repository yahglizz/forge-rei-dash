# FORGE AI — Runbook (2026-09-22)

Box: DigitalOcean `forge-reios` (`root@24.199.81.124`, tailnet `forge-reios.tail0a2dda.ts.net`).
SSH: `ssh -i ~/.ssh/forge_droplet root@24.199.81.124`. The Mac is dev-only — production does not
need it open.

## 1. Where things run

| Thing | Where | Check |
|---|---|---|
| Dashboard + every agent loop | box `forge-reios.service` (`/opt/forge/forge-rei/connector.py`) | `systemctl status forge-reios` |
| Deploys | box `forge-autopull.timer` (60 s) ← GitHub `main` ← Mac `com.forge.autosync` (60 s) | `journalctl -u forge-autopull.service -n 20` |
| Nightly learn | box `forge-daily-learn.timer` 20:00 ET | `/opt/forge/forge-rei/marcus_state/daily-learn.log` |
| Weekly review | box `forge-review.timer` Mon 08:00 UTC | `journalctl -u forge-review.service` |
| State backup | box `forge-backup.timer` 03:30 ET → `/root/backups/forge-state-YYYY-MM-DD.tgz` (7 kept) | `ls -lh /root/backups` |
| Vault box→Mac | Mac `com.agentic.brain-sync` (6 h) | Mac only |
| Client portal (public) | box, Funnel `:8443` → `:10000` | `tailscale funnel status` |

## 2. Health checks

```bash
curl -s 127.0.0.1:7799/api/system/health   # loops, heartbeats, disk, AI health
curl -s 127.0.0.1:7799/api/health          # wholesale GHL + scout/followup/contract
curl -s 127.0.0.1:7799/api/cost/status     # spend by agent (flat 0 = AI not running)
curl -s 127.0.0.1:7799/api/owner-actions   # the owner's list (after WP-C)
curl -s 127.0.0.1:7799/api/agents/registry # every agent + status (after WP-D)
```
Secret paths must 404: `/config/ghl.env`, `/.env`, and `/api/brain/note?path=.env` → `not found`.

## 3. Deploy

| Path | Use |
|---|---|
| Save/commit on the Mac | autosync pushes ≤60 s → box deploys ≤~3 min. **Every saved file goes live** — never leave a half-edit in the main tree; build in a worktree/branch and merge when tested. |
| `./forge rei/deploy/quick-deploy.sh` | deploy now instead of waiting |
| `./forge rei/deploy/push.sh root@24.199.81.124` | when a `*.env` secret or the vault changed (rsyncs them; gitignored) |

Bad commit → deploy-pull validation aborts, live keeps running. Autopull compares origin/main to
`/opt/forge/.deployed_sha` (written only after the health gate), so a killed/aborted deploy retries;
max 3 tries per commit (`FORGE_DEPLOY_MAX_TRIES`), reset by the next push. What's live: `cat /opt/forge/.deployed_sha`. **Rollback:** `git revert <sha>`
on the Mac (autosync ships it).

## 4. Kill switches & knobs (`/etc/default/forge-reios`, then `systemctl restart forge-reios`)

| Need | Do |
|---|---|
| Stop all outward agent activity now | Command Center clock-out, or Telegram ops clock-out (`forge_ops.paused()`) |
| Stop every loop | `FORGE_MARCUS=0` in the unit env + restart (UI stays up) |
| ACE / autopilot | off by default — only the operator flips them (`/autopilot off` in Telegram) |
| HOT auto-tag / auto-pipeline | `FORGE_SCOUT_AUTOTAG_HOT=0` / `FORGE_SCOUT_AUTOPIPE_HOT=0` |
| Daycare PIN back on | `FORGE_DAYCARE_OPEN=0` |
| Midas brief / DoToday loop | `FORGE_DROPSHIP_BRIEF`, `FORGE_TODAY_LOOP` (both 0). Turning `FORGE_TODAY_LOOP` on also restarts the scheduled legit audit + Marcus lead directives |

## 5. Incidents

| Symptom | Cause / fix |
|---|---|
| Cost flat $0, briefs stale, chats error "credit balance too low" | **Anthropic credits exhausted** → owner tops up billing at console.anthropic.com. Verify: one agent chat succeeds, `/api/system/health` `ai.ok:true` (Telegram sends one 🟢 recovery). Solomon retries inside his backoff window (≤ 6 h) — force it with `POST /api/daycare/director/run`. |
| Solomon red, `[ads] live fetch failed … Cannot parse access token` | daycare `META_ACCESS_TOKEN` invalid → owner pastes a real system-user token into `forge-daycare/config/daycare.env`, then `push.sh`. |
| Agency Workflows shows fake clients | n8n URL returns 404 → fix `N8N_BASE_URL` in `ghl.env` or ignore (mock labeled after WP-G). |
| Telegram approve says "proposal not found" | phantom module (fixed in WP-A) — restart service if it recurs. |
| Loop red in health | `journalctl`-less app logs: `/opt/forge/connector.err.log` / `.out.log`; watchdog alerts but never restarts — `systemctl restart forge-reios`. |
| Autosync paused ("CONFLICT") | open a terminal in the repo, resolve the rebase conflict; `/tmp/forge-autosync.err` has details. |
| Mac "No space left on device" | worktrees/autosync fail. Free regenerable caches (`npm cache clean --force`, `uv cache prune`). |

## 6. Box cleanup reference (from the 09-22 audit)

- **Safe:** `journalctl --vacuum-time=14d` + `/etc/systemd/journald.conf.d/forge.conf` (`SystemMaxUse=200M`), `: > /var/log/dmesg`, `: > /var/log/btmp`, `apt-get clean`, `__pycache__`, dead `git-sync.log` / `cloudflared.log`.
- **Archive then remove:** `retired-2026-07-25/`, stray `/root/Desktop/Agentic-OS`, `ruvector.db` ×3, `cloudflared` binary → `/root/forge-archive-YYYYMMDD.tgz`.
- **Leave:** `marcus-wholesale-agent/` (live key + imports), `forge-docusign/`, vault, `marcus_state`, uploads, repo, swap, apt lists.
- After a kernel update: reboot, verify service + timers + `tailscale serve status`, then `apt-get autoremove --purge`.

## 7. Owner-only actions (never automated)

Anthropic billing · Meta token · rotating any key (incl. the GitHub PAT that sat in `vault/.env`) ·
ACE/autopilot modes · `FORGE_DAYCARE_OPEN` · tailnet membership · DO off-box backups ($) ·
daycare licensing/staffing compliance · GHL calendar/timezone · any spend.
