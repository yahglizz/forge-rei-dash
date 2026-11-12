# 05 - Box probe (Task 0), read-only, 2026-11-11

Method: read deploy scripts locally; SSH (`~/.ssh/forge_droplet`, public IP `24.199.xxx.xxx`, root) with read-only commands only. No restart, no file copy, no secret values printed. Env var NAMES only.

## Fields

| field | value |
|---|---|
| box_python_version | 3.12.3 (`/usr/bin/python3`), pip 24.0 (`/usr/lib/python3/dist-packages/pip`) |
| slack_sdk_installed | NO (`ModuleNotFoundError`). Only `requests 2.31.0` present of the relevant libs; no websocket/websockets/aiohttp. |
| slack_sdk_installable | YES for download: `pip3 download slack_sdk --no-deps` fetched `slack_sdk-3.46.0-py2.py3-none-any.whl` (325 kB), `/tmp/probe` removed. PEP 668 applies: `/usr/lib/python3.12/EXTERNALLY-MANAGED` exists; `pip3 install --dry-run slack_sdk` fails with "externally-managed-environment". Flag needed: `--break-system-packages` (same flag `setup_droplet.sh:30` already uses for `requests`). Not installed in this probe. slack_sdk's built-in Socket Mode client needs no extra deps (Unverified on 3.46.0 - confirm at install; `--dry-run` with the flag was not run). |
| box_repo_path | Git clone: `/opt/forge/repo` (what autopull follows). Live tree the service runs from: `/opt/forge/forge-rei` (rsync'd copy of `repo/forge rei/`). Service `WorkingDirectory=/opt/forge/forge-rei`, `ExecStart=/usr/bin/python3 -u /opt/forge/forge-rei/connector.py`. |
| box_config_dir | `/opt/forge/forge-telegram/config/` (holds `telegram.env`, mode 600 root, `ruvector.db`, `.gitignore`, `telegram.env.example`). Config dirs are never overwritten by deploy (`rsync --exclude config --exclude '*.env'`). `/opt/forge/forge-slack` does NOT exist on the box. |
| deploy_source | github-main. Remote `https://github.com/yahglizz/forge-rei-dash.git`, branch `main`. Box `forge-autopull.timer` (60 s) runs `autopull.sh`: fetch origin/main, compare to `/opt/forge/.deployed_sha`, debounce 90 s commit age, max 3 tries, then `deploy-pull.sh`. Box `HEAD` = `.deployed_sha` = `8817e8092b5f` = `git ls-remote origin main`. Local pusher: launchd `com.forge.autosync` runs `~/forge rei dash/forge rei/deploy/auto-sync.sh` every 60 s (commit all, pull --rebase, push), root = `/Users/yg4st/forge rei dash`. |
| live source (Mac) | `~/forge rei dash` = LIVE (HEAD `8817e80` = origin/main, clean tree). `/Volumes/AgentDrive/claude/forge-rei-dash` = STALE: HEAD `39f067d` (2026-10-18), an ancestor of origin/main, 102 commits behind. The memory note ("not the stale drive checkout") is correct. |
| systemd_unit_name | `forge-reios.service` (+ drop-in `forge-reios.service.d/unbuffered.conf`). Also `forge-autopull.{service,timer}`, `forge-daily-learn`, `forge-review`, `forge-backup` timers. |
| systemd_env_mechanism | Both. `EnvironmentFile=-/etc/default/forge-reios` (mode 600 root) plus `Environment=` lines in the unit: FORGE_PORT, FORGE_HOST, FORGE_VAULT, FORGE_MARCUS, FORGE_TZ, TZ, PYTHONUNBUFFERED. Names in the EnvironmentFile include FORGE_DAYCARE_LIVE/WRITES/TEST_MODE/OPEN, FORGE_PORTAL_PORT/BASE, FORGE_SOLOMON_ORCH, FORGE_GATEWAY_*, FORGE_CHAT_GATEWAY, FORGE_MAC_KEY_SHA256, HIGGSFIELD_*, N8N_*, plus API-key and token vars. Best place for `FORGE_SLACK=1` and `FORGE_CHAT_TRANSPORT`: `/etc/default/forge-reios` (edit on box needs SSH; deploy never touches it). |
| service_user | root (no `User=` in unit). |
| free_memory_mb | RAM total 961, used 428, free 212, available 533. Swap 1023 total, 73 used. Disk `/` 24G, 19G free. |
| health_endpoint_path | `deploy-pull.sh` `health_gate`: service active + `GET http://127.0.0.1:7799/api/health` 200 + `GET /api/system/health` JSON `ok:true` (tolerated if already not-ok before deploy) + `/marcus_state/heartbeats.json` must 404. Live now: `/api/health` 200, `/api/system/health` ok=True. Rolls back to last `.deployed_sha` and Telegram-alerts on failure. |
| restarts_on_deploy | Conditional. Restart only if the diff vs `.deployed_sha` touches a file outside `.jsx .css .html .md .png .jpg .svg .webp .ico .woff ios/ docs/ .swarm/ output/agent-audit/ .playwright-mcp/`. Any `.py` change restarts `forge-reios`. `FORGE_FORCE_RESTART=1` forces. Env-file edits do NOT trigger a restart; run `systemctl restart forge-reios` manually. |

## Findings that change later tasks

1. `deploy-pull.sh` rsync loop lists only: forge-agency, forge-scout, forge-marcus, forge-solomon, forge-telegram, forge-daycare, forge-dropship, forge-mission. `forge-slack` is NOT in it. Code in `forge rei/` ships; anything under `forge-slack/` does not reach the box. Slack code must live in `forge rei/` (as planned: `slack_io.py`, `slack_inbound.py`), and Task 10 must create `/opt/forge/forge-slack/config/` by hand, or the loop gets a new entry (touches `deploy-pull.sh`, validated by `test_deploy_pull.sh`).
2. The worktree `/Volumes/AgentDrive/claude/forge-slack-wt` is at `39f067d`, 102 commits behind origin/main (`8817e80`). Rebase or recreate it from origin/main before Task 1, or code and tests are written against old files (`telegram_io.py`, `connector.py` and the n8n gateway work all changed).
3. `slack_sdk` needs `pip3 install --break-system-packages slack_sdk` on the box. This is a box mutation; do it in Task 10 only after owner approval. Fallback stays the stdlib websocket client (note `requests` is present).
4. Box is small: ~530 MB available, 1 vCPU. A Socket Mode listener thread inside `connector.py` is fine; do not add a second Python process.

## Not verified

- Behaviour of `pip3 install --break-system-packages slack_sdk` (not run, read-only rule).
- Whether any file under `/opt/forge/repo` differs from the live tree (not diffed).
- Whether `sync-down.sh` (launchd `com.forge.drive-syncdown`) overwrites the drive checkout from anywhere (script not read).
