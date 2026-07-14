#!/usr/bin/env bash
# auto-sync.sh — keep THIS machine's clone continuously mirrored with GitHub, so
# the Mac and the gaming PC stay in sync hands-free. One pass = commit local
# changes -> pull (rebase, autostash) -> push. Safe for one-machine-at-a-time work.
# On a genuine merge conflict it STOPS and alerts rather than guessing.
#
#   ./auto-sync.sh        # one pass (for launchd / Task Scheduler)
#   ./auto-sync.sh 60     # loop forever, every 60s (for a Git Bash window)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

sync_once() {
  cd "$ROOT" || return 1
  # 1. commit anything local (only creates a commit when the tree is dirty)
  if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git -c user.name="yahglizz" -c user.email="yahjair@atouchofblessing.com" \
      commit -q -m "auto-sync: $(hostname) $(date '+%F %T')"
  fi
  # 2. pull remote onto our commits; autostash guards any in-flight edit
  if ! git pull --rebase --autostash --quiet origin main; then
    git rebase --abort 2>/dev/null || true
    echo "!! auto-sync CONFLICT — paused. Open a terminal and resolve, then it resumes." >&2
    # best-effort desktop nudge (macOS); silent elsewhere
    command -v osascript >/dev/null 2>&1 && \
      osascript -e 'display notification "Resolve git conflict in forge-rei-dash" with title "auto-sync paused"' 2>/dev/null || true
    return 3
  fi
  # 3. push our commits up
  git push --quiet origin main 2>/dev/null || echo "   (push deferred — retry next pass)" >&2
}

INTERVAL="${1:-}"
if [ -n "$INTERVAL" ]; then
  echo "auto-sync running every ${INTERVAL}s in $ROOT — leave this window open. Ctrl-C to stop."
  while true; do sync_once || true; sleep "$INTERVAL"; done
else
  sync_once
fi
