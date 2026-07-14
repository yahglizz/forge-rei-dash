#!/usr/bin/env bash
# quick-deploy.sh — the everyday deploy, from ANY machine (Mac or the gaming PC
# via Git Bash). Commits your edits, pushes to GitHub, then tells the box to pull
# + validate + restart. No secrets or rsync needed on the client — the box already
# holds them. For SECRET or VAULT changes, use the Mac's ./deploy/push.sh instead.
#
#   Usage:  ./deploy/quick-deploy.sh ["commit message"]
set -euo pipefail

BOX="root@24.199.81.124"
KEY="$HOME/.ssh/forge_droplet"
ROOT="$(git rev-parse --show-toplevel)"
MSG="${1:-deploy: $(date '+%Y-%m-%d %H:%M') — quick-deploy}"

cd "$ROOT"

# Optional local JSX guard (skipped if node missing, e.g. a bare Windows box).
if command -v node >/dev/null 2>&1 && [ -f "forge rei/deploy/valjsx.js" ]; then
  echo "==> validate JSX locally"
  ( cd "forge rei" && node deploy/valjsx.js *.jsx mobile/*.jsx ) \
    || { echo "!! JSX validation failed — fix before deploying"; exit 1; }
fi

echo "==> commit + push"
if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git -c user.name="yahglizz" -c user.email="yahjair@atouchofblessing.com" commit -q -m "$MSG"
  echo "   committed: $MSG"
else
  echo "   (nothing to commit — deploying current HEAD)"
fi
git push origin main

echo "==> trigger box pull + restart"
ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$BOX" \
  'bash "/opt/forge/repo/forge rei/deploy/deploy-pull.sh"'

echo
echo "Deployed. Live: https://forge-reios.tail0a2dda.ts.net"
