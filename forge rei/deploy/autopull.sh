#!/usr/bin/env bash
# autopull.sh — runs ON THE BOX on a 60s systemd timer. Checks GitHub; if
# origin/main moved, runs deploy-pull.sh (validate -> sync -> restart -> health).
# Makes deploy from ANY machine as simple as `git push` — no SSH key on the client.
# If a commit fails validation, deploy-pull.sh aborts (set -e) and the live version
# keeps running; the next good push recovers.
set -euo pipefail

REPO="/opt/forge/repo"
QUIET_SECS="${FORGE_DEPLOY_DEBOUNCE:-90}"   # only deploy commits older than this,
                                            # so rapid auto-sync saves don't restart
                                            # the live service mid-edit. 0 = instant.
git -C "$REPO" fetch --quiet origin main
LOCAL="$(git -C "$REPO" rev-parse HEAD)"
REMOTE="$(git -C "$REPO" rev-parse origin/main)"

if [ "$LOCAL" != "$REMOTE" ]; then
  # Debounce: wait until editing has settled before touching the live box.
  AGE=$(( $(date +%s) - $(git -C "$REPO" log -1 --format=%ct origin/main) ))
  if [ "$AGE" -lt "$QUIET_SECS" ]; then
    echo "$(date '+%F %T') commit $REMOTE only ${AGE}s old — waiting for edits to settle"
    exit 0
  fi
  echo "$(date '+%F %T') new commit $REMOTE (${AGE}s old) — deploying"
  bash "/opt/forge/repo/forge rei/deploy/deploy-pull.sh"
  echo "$(date '+%F %T') deploy complete"
fi
