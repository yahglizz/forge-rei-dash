#!/usr/bin/env bash
# push.sh — run from YOUR MAC. Copies the app + secrets + brain to the droplet,
# preserving the sibling layout the app expects, then runs setup remotely.
#
# Usage:  ./deploy/push.sh root@<droplet-ip>
# Secrets travel Mac -> droplet over SSH only (never chat, never git).
set -euo pipefail

TARGET="${1:?usage: ./deploy/push.sh root@<droplet-ip>}"
KEY="$HOME/.ssh/forge_droplet"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new"
DASH="/Users/yg4st/forge rei dash/forge rei"
MARCUS="$HOME/Desktop/marcus-wholesale-agent"
AGENCY="$(dirname "$DASH")/forge-agency"   # sibling of "forge rei/", in the main folder
SCOUT="$(dirname "$DASH")/forge-scout"     # Scout agent: config knobs + seed skills
DAYCARE="$(dirname "$DASH")/forge-daycare" # Supabase schema + private Daycare config
SOLOMON="$(dirname "$DASH")/forge-solomon" # Solomon: daycare head-agent config + seed playbook
SCREEN="$(dirname "$DASH")/forge-marcus"   # Marcus screening agent: config knobs + seed screening playbook
TG="$(dirname "$DASH")/forge-telegram"     # Telegram alerts + tap-to-approve: config/telegram.env
VAULT="$HOME/Desktop/Agentic-OS/vault"
REMOTE="/opt/forge"
PORT="${FORGE_PORT:-7799}"

# ---------------------------------------------------------------------------
# Validate BEFORE any rsync — never ship a broken state (CLAUDE.md Rule #1).
# A syntax error in a .py crashes the box on restart; a bad .jsx white-screens the
# live dashboard. Both are caught here on the Mac and abort the push (set -e).
# ---------------------------------------------------------------------------
echo "==> validate (python ast + jsx babel) before pushing"
cd "$DASH"
for f in *.py; do
  python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$f" \
    || { echo "!! PYTHON SYNTAX ERROR in $f — aborting deploy"; exit 1; }
done
echo "   python: all $(ls *.py | wc -l | tr -d ' ') files parse"
if command -v node >/dev/null 2>&1; then
  # Desktop AND mobile JSX — a mobile Babel error white-screens the PWA silently,
  # so both trees must pass before anything ships (audit F6, 2026-07-11).
  node "$DASH/deploy/valjsx.js" *.jsx mobile/*.jsx \
    || { echo "!! JSX validation failed — aborting deploy"; exit 1; }
else
  echo "   (node not found — skipping JSX transform check; install node to enable)"
fi

echo "==> make remote dirs"
$SSH "$TARGET" "mkdir -p $REMOTE/forge-rei $REMOTE/marcus-wholesale-agent/config $REMOTE/marcus-wholesale-agent/scripts $REMOTE/forge-agency/config $REMOTE/forge-agency/skills $REMOTE/forge-scout/config $REMOTE/forge-scout/skills $REMOTE/forge-daycare/config $REMOTE/forge-solomon/config $REMOTE/forge-solomon/skills $REMOTE/forge-marcus/config $REMOTE/forge-marcus/skills $REMOTE/forge-telegram/config $REMOTE/vault"

echo "==> push dashboard (deploy/keys excluded — never ship SSH keys/secret backups to the box)"
rsync -az --delete -e "$SSH" \
  --exclude '__pycache__' --exclude 'marcus_state' --exclude '*.log' \
  --exclude 'deploy/keys' --exclude 'deploy/.cache' --exclude '.git' --exclude 'ruvector.db' --exclude 'uploads' \
  "$DASH/" "$TARGET:$REMOTE/forge-rei/"

echo "==> push secrets (ghl.env) + classifier scripts"
rsync -az -e "$SSH" "$MARCUS/config/ghl.env" "$TARGET:$REMOTE/marcus-wholesale-agent/config/ghl.env"
rsync -az -e "$SSH" "$MARCUS/scripts/" "$TARGET:$REMOTE/marcus-wholesale-agent/scripts/"

echo "==> push agency secrets (agency.env) — SEPARATE GHL sub-account"
if [ -f "$AGENCY/config/agency.env" ]; then
  rsync -az -e "$SSH" "$AGENCY/config/agency.env" "$TARGET:$REMOTE/forge-agency/config/agency.env"
else
  echo "   (no $AGENCY/config/agency.env yet — skipping; agency GHL stays 'not connected')"
fi
if [ -d "$AGENCY" ]; then
  # Ship the complete non-secret agency folder, including root operating docs. Config
  # secrets are handled explicitly above and never mirrored by this rsync.
  rsync -az --delete -e "$SSH" --exclude '__pycache__' --exclude 'config' --exclude '*.env' \
    "$AGENCY/" "$TARGET:$REMOTE/forge-agency/"
fi

echo "==> push Daycare integration (tracked schema + private publishable config)"
if [ -d "$DAYCARE" ]; then
  # Schema/function files are change-control artifacts only. setup_droplet never
  # applies them to Supabase; production migrations remain separately reviewed.
  rsync -az --delete -e "$SSH" --exclude '__pycache__' --exclude 'config' --exclude '*.env' \
    "$DAYCARE/" "$TARGET:$REMOTE/forge-daycare/"
  if [ -f "$DAYCARE/config/daycare.env" ]; then
    rsync -az -e "$SSH" "$DAYCARE/config/daycare.env" "$TARGET:$REMOTE/forge-daycare/config/daycare.env"
    $SSH "$TARGET" "chmod 600 $REMOTE/forge-daycare/config/daycare.env"
  else
    echo "   (no $DAYCARE/config/daycare.env — Daycare API stays safely unconfigured)"
  fi
else
  echo "   (no $DAYCARE folder — Daycare API stays safely unconfigured)"
fi

echo "==> push Scout folder (config knobs + seed skills; learned playbook lives in the vault)"
if [ -d "$SCOUT" ]; then
  rsync -az -e "$SSH" --exclude '__pycache__' "$SCOUT/" "$TARGET:$REMOTE/forge-scout/"
else
  echo "   (no $SCOUT yet — skipping; Scout falls back to vault skills + wholesale key)"
fi

echo "==> push Solomon folder (daycare head-agent config + seed playbook; learned copy lives in the vault)"
if [ -d "$SOLOMON" ]; then
  rsync -az -e "$SSH" --exclude '__pycache__' "$SOLOMON/" "$TARGET:$REMOTE/forge-solomon/"
else
  echo "   (no $SOLOMON yet — skipping; Solomon falls back to vault skills + shared key)"
fi

echo "==> push Marcus screening folder (config knobs + seed screening playbook; learned copy lives in the vault)"
if [ -d "$SCREEN" ]; then
  rsync -az -e "$SSH" --exclude '__pycache__' "$SCREEN/" "$TARGET:$REMOTE/forge-marcus/"
else
  echo "   (no $SCREEN yet — skipping; Marcus screening falls back to vault skills + wholesale key)"
fi

echo "==> push Telegram folder (config/telegram.env secret ships Mac -> box over SSH, like ghl.env)"
if [ -d "$TG" ]; then
  rsync -az -e "$SSH" --exclude '__pycache__' "$TG/" "$TARGET:$REMOTE/forge-telegram/"
else
  echo "   (no $TG yet — skipping; Telegram alerts stay 'not configured')"
fi

echo "==> push graphify knowledge graph"
GRAPHIFY_SRC="$HOME/.graphify/global-graph.json"
if [ -f "$GRAPHIFY_SRC" ]; then
  $SSH "$TARGET" "mkdir -p /root/.graphify"
  rsync -az -e "$SSH" "$GRAPHIFY_SRC" "$TARGET:/root/.graphify/global-graph.json"
else
  echo "   (no ~/.graphify/global-graph.json — skipping; graphify tab shows empty)"
fi

echo "==> push brain vault (learned voice/playbook carry over)"
# --update: NEVER overwrite a box file that is newer than the Mac's. The box runs the
# agents 24/7 and learns daily (8pm sweep) — its playbooks are the source of truth. Without
# --update a deploy would revert the brain to the Mac's stale copy. --exclude .git preserves
# the box's own commit history (the daily learn commits each write).
rsync -az --update -e "$SSH" \
  --exclude '.obsidian' --exclude '.git' --exclude '*.env' --exclude '.env' \
  --exclude '*.pem' --exclude '*.key' "$VAULT/" "$TARGET:$REMOTE/vault/"

echo "==> run setup on the droplet"
$SSH "$TARGET" "bash $REMOTE/forge-rei/deploy/setup_droplet.sh"

# ---------------------------------------------------------------------------
# Post-deploy health gate — verify the box actually came back up (CLAUDE.md Rule #1:
# SSH-verify service active, endpoints 200, secrets 404). Curls hit box localhost since
# the dashboard is tailnet-private. Fails loud so a dead deploy can't pass silently.
# ---------------------------------------------------------------------------
echo "==> verify the box came back healthy"
$SSH "$TARGET" "
  set -e
  systemctl is-active --quiet forge-reios || { echo '   !! forge-reios NOT active'; systemctl status forge-reios --no-pager -l | tail -20; exit 1; }
  sleep 3
  curl -fsS http://127.0.0.1:$PORT/api/health >/dev/null || { echo '   !! /api/health not 200'; exit 1; }
  curl -fsS http://127.0.0.1:$PORT/api/system/health | grep -q '\"ok\"' || { echo '   !! /api/system/health missing ok'; exit 1; }
  curl -fsS http://127.0.0.1:$PORT/api/daycare/auth/status | grep -q '\"authenticated\"' || { echo '   !! /api/daycare/auth/status not healthy'; exit 1; }
  if curl --max-time 10 -fsS https://forge-reios.tail0a2dda.ts.net/api/daycare/auth/status | grep -q '\"authenticated\"'; then
    https_ok=1
  else
    https_ok=0
    echo '   !! Tailscale HTTPS is pending the one-time tailnet Serve approval; Daycare writes fail closed meanwhile.'
  fi
  hc=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/marcus_state/heartbeats.json); [ \"\$hc\" = 404 ] || { echo \"   !! heartbeats.json served (\$hc) — must 404\"; exit 1; }
  sc=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/../marcus-wholesale-agent/config/ghl.env); [ \"\$sc\" != 200 ] || { echo '   !! ghl.env is being served — secret leak'; exit 1; }
  dc=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/../forge-daycare/config/daycare.env); [ "\$dc" != 200 ] || { echo '   !! daycare.env is being served — secret leak'; exit 1; }
  if [ "\$https_ok" = 1 ]; then
    dch=\$(curl --max-time 10 -s -o /dev/null -w '%{http_code}' https://forge-reios.tail0a2dda.ts.net/forge-daycare/config/daycare.env); [ "\$dch" = 404 ] || { echo "   !! HTTPS daycare.env path returned \$dch — must 404"; exit 1; }
    echo '   OK: service active · local + Tailscale HTTPS Daycare auth status 200 · state/secrets not served'
  else
    echo '   OK: service active · local Daycare auth status 200 · state/secrets not served · HTTPS approval pending'
  fi
"

# ---------------------------------------------------------------------------
# GitHub mirror — every successful deploy is committed + pushed to
# github.com/yahglizz/forge-rei-dash so the repo always matches the live box.
# Best-effort: a GitHub outage must never block or roll back a healthy deploy,
# so failures warn loudly but do not exit non-zero. Secrets/state are excluded
# by the repo-root .gitignore (validated: *.env, marcus_state/, vault stays out).
# ---------------------------------------------------------------------------
echo "==> mirror to GitHub (yahglizz/forge-rei-dash)"
REPO_ROOT="$(dirname "$DASH")"
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if ! git -C "$REPO_ROOT" diff --quiet HEAD 2>/dev/null || [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
    git -C "$REPO_ROOT" add -A
    git -C "$REPO_ROOT" -c user.name="yahglizz" -c user.email="yahjair@atouchofblessing.com" \
      commit -q -m "deploy: $(date '+%Y-%m-%d %H:%M') — synced to 24/7 box" || true
  fi
  git -C "$REPO_ROOT" push origin main \
    && echo "   OK: GitHub mirror up to date" \
    || echo "   !! GitHub push failed (deploy itself is fine — push manually: git -C \"$REPO_ROOT\" push origin main)"
else
  echo "   (repo root $REPO_ROOT is not a git repo — skipping mirror)"
fi

echo
echo "Done pushing. Private URL: https://forge-reios.tail0a2dda.ts.net"
