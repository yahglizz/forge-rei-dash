#!/usr/bin/env bash
# deploy-pull.sh — runs ON THE BOX. Pulls the latest CODE from GitHub
# (yahglizz/forge-rei-dash, public) and syncs it into the live tree, then
# validates + restarts + health-checks. This is the everyday, machine-agnostic
# deploy path: edit on Mac OR PC -> `git push` -> trigger this -> box updates.
#
# What it does NOT touch (by design): secrets (*.env / config/), the brain vault,
# marcus_state, uploads, ruvector.db. Those live only on the box (and, for secrets,
# on the Mac). To change a SECRET or the VAULT, use the Mac's ./deploy/push.sh.
#
# One-time box setup:
#   git clone https://github.com/yahglizz/forge-rei-dash.git /opt/forge/repo
# Then trigger from any machine:
#   ssh box 'bash "/opt/forge/repo/forge rei/deploy/deploy-pull.sh"'
set -euo pipefail

REPO="/opt/forge/repo"
LIVE="/opt/forge"                     # live tree root: forge-rei + sibling agent folders
APP="$REPO/forge rei"                 # app subfolder inside the repo (note the space)
PORT="${FORGE_PORT:-7799}"

echo "==> fetch latest from GitHub (origin/main)"
git -C "$REPO" fetch --quiet origin main
BEFORE="$(git -C "$REPO" rev-parse HEAD)"
git -C "$REPO" reset --hard --quiet origin/main
AFTER="$(git -C "$REPO" rev-parse HEAD)"
echo "   $BEFORE -> $AFTER"
if [ "$BEFORE" = "$AFTER" ]; then
  echo "   (no new commits — re-syncing anyway to guarantee box matches origin)"
fi

# ---------------------------------------------------------------------------
# Validate BEFORE any rsync — never ship a broken state (CLAUDE.md Rule #1).
# A syntax error in a .py crashes the box on restart; a bad .jsx white-screens
# the live dashboard. Both are caught here and abort the deploy (set -e).
# ---------------------------------------------------------------------------
echo "==> validate (python ast + jsx babel)"
cd "$APP"
for f in *.py; do
  python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$f" \
    || { echo "!! PYTHON SYNTAX ERROR in $f — aborting deploy"; exit 1; }
done
echo "   python: all $(ls *.py | wc -l | tr -d ' ') files parse"
if command -v node >/dev/null 2>&1; then
  node "$APP/deploy/valjsx.js" *.jsx mobile/*.jsx \
    || { echo "!! JSX validation failed — aborting deploy"; exit 1; }
else
  echo "   (node not found — skipping JSX transform check)"
fi

# ---------------------------------------------------------------------------
# Sync CODE into the live tree. Excludes mirror push.sh so box-only state
# (secrets, marcus_state, uploads, vault, ruvector.db, .git) is preserved.
# ---------------------------------------------------------------------------
echo "==> sync app code -> $LIVE/forge-rei"
rsync -a --delete \
  --exclude '__pycache__' --exclude 'marcus_state' --exclude '*.log' \
  --exclude 'deploy/keys' --exclude 'deploy/.cache' --exclude '.git' \
  --exclude 'ruvector.db' --exclude 'uploads' \
  "$APP/" "$LIVE/forge-rei/"

echo "==> sync non-secret agent folders (config/*.env preserved on box)"
for d in forge-agency forge-scout forge-marcus forge-solomon forge-telegram forge-daycare; do
  if [ -d "$REPO/$d" ]; then
    rsync -a --exclude '__pycache__' --exclude 'config' --exclude '*.env' \
      "$REPO/$d/" "$LIVE/$d/"
    echo "   synced $d"
  fi
done

echo "==> restart forge-reios"
systemctl restart forge-reios

# ---------------------------------------------------------------------------
# Post-deploy health gate — verify the box actually came back up.
# ---------------------------------------------------------------------------
echo "==> verify healthy"
systemctl is-active --quiet forge-reios \
  || { echo '   !! forge-reios NOT active'; systemctl status forge-reios --no-pager -l | tail -20; exit 1; }
sleep 3
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null \
  || { echo '   !! /api/health not 200'; exit 1; }
curl -fsS "http://127.0.0.1:$PORT/api/system/health" | grep -q '"ok"' \
  || { echo '   !! /api/system/health missing ok'; exit 1; }
hc=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/marcus_state/heartbeats.json")
[ "$hc" = 404 ] || { echo "   !! heartbeats.json served ($hc) — must 404"; exit 1; }

echo "   OK: service active · endpoints 200 · state not served"
echo "Done. Live: https://forge-reios.tail0a2dda.ts.net"
