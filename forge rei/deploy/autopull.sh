#!/usr/bin/env bash
# autopull.sh — runs ON THE BOX on a 60s systemd timer. Checks GitHub; if
# origin/main moved, runs deploy-pull.sh (validate -> sync -> restart -> health).
# Makes deploy from ANY machine as simple as `git push` — no SSH key on the client.
# If a commit fails validation, deploy-pull.sh aborts (set -e) and the live version
# keeps running; the next good push recovers.
set -euo pipefail

REPO="/opt/forge/repo"
git -C "$REPO" fetch --quiet origin main
LOCAL="$(git -C "$REPO" rev-parse HEAD)"
REMOTE="$(git -C "$REPO" rev-parse origin/main)"

if [ "$LOCAL" != "$REMOTE" ]; then
  echo "$(date '+%F %T') new commit $REMOTE — deploying"
  bash "/opt/forge/repo/forge rei/deploy/deploy-pull.sh"
  echo "$(date '+%F %T') deploy complete"
fi
