#!/usr/bin/env bash
# autopull.sh — runs ON THE BOX on a 60s systemd timer. Checks GitHub; if
# origin/main != the last HEALTHY deploy (/opt/forge/.deployed_sha), runs deploy-pull.sh (validate -> sync -> restart -> health).
# Makes deploy from ANY machine as simple as `git push` — no SSH key on the client.
# If a commit fails validation, deploy-pull.sh aborts (set -e) and the live version
# keeps running; the next good push recovers.
set -euo pipefail

REPO="/opt/forge/repo"
QUIET_SECS="${FORGE_DEPLOY_DEBOUNCE:-90}"   # only deploy commits older than this,
                                            # so rapid auto-sync saves don't restart
                                            # the live service mid-edit. 0 = instant.
MARK="/opt/forge/.deployed_sha"             # written by deploy-pull.sh ONLY after its
                                            # health gate passes = what is really live
TRIES="/opt/forge/.deploy_attempts"         # "<sha> <n>" — caps retries of one commit
MAX_TRIES="${FORGE_DEPLOY_MAX_TRIES:-3}"
git -C "$REPO" fetch --quiet origin main
# Compare against the deployed marker, not HEAD: deploy-pull resets HEAD first, so a
# deploy that aborts/gets killed after the reset left HEAD == origin and never retried.
# No marker yet (first run after this change) → fall back to HEAD, i.e. old behavior.
LOCAL="$(cat "$MARK" 2>/dev/null || true)"
[ -n "$LOCAL" ] || LOCAL="$(git -C "$REPO" rev-parse HEAD)"
REMOTE="$(git -C "$REPO" rev-parse origin/main)"

if [ "$LOCAL" != "$REMOTE" ]; then
  # Debounce: wait until editing has settled before touching the live box.
  AGE=$(( $(date +%s) - $(git -C "$REPO" log -1 --format=%ct origin/main) ))
  if [ "$AGE" -lt "$QUIET_SECS" ]; then
    echo "$(date '+%F %T') commit $REMOTE only ${AGE}s old — waiting for edits to settle"
    exit 0
  fi
  # Retry cap: a commit that fails validation aborts before rsync/restart (harmless to
  # retry), but one that fails the POST-restart health gate would restart the live
  # service every 60s. Give one commit MAX_TRIES, then wait for the next push.
  read -r TSHA TN 2>/dev/null < "$TRIES" || true
  [ "${TSHA:-}" = "$REMOTE" ] || TN=0
  case "${TN:-}" in ''|*[!0-9]*) TN=0 ;; esac          # digits only — never let file text reach $(( ))
  case "$MAX_TRIES" in ''|*[!0-9]*) MAX_TRIES=3 ;; esac
  if [ "${TN:-0}" -ge "$MAX_TRIES" ]; then
    echo "$(date '+%F %T') commit $REMOTE failed $TN deploy attempts — skipping until a new push"
    exit 0
  fi
  echo "$REMOTE $(( ${TN:-0} + 1 ))" > "$TRIES"
  echo "$(date '+%F %T') new commit $REMOTE (${AGE}s old, live ${LOCAL:0:7}) — deploying"
  bash "/opt/forge/repo/forge rei/deploy/deploy-pull.sh"
  echo "$(date '+%F %T') deploy complete"
fi
