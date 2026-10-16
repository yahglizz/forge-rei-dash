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

REPO="${FORGE_DEPLOY_REPO:-/opt/forge/repo}"   # overridable ONLY for the offline test harness
LIVE="${FORGE_DEPLOY_LIVE:-/opt/forge}"        # live tree root: forge-rei + sibling agent folders
APP="$REPO/forge rei"                 # app subfolder inside the repo (note the space)
PORT="${FORGE_PORT:-7799}"
HEALTH_WAIT="${FORGE_DEPLOY_HEALTH_WAIT:-60}"  # secs to wait for system health ok:true after a restart
case "$HEALTH_WAIT" in ''|*[!0-9]*) HEALTH_WAIT=60 ;; esac

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
# A function so the rollback below re-syncs the last good commit the same way.
# ---------------------------------------------------------------------------
sync_tree() {
  echo "==> sync app code -> $LIVE/forge-rei"
  rsync -a --delete \
    --exclude '__pycache__' --exclude 'marcus_state' --exclude '*.log' \
    --exclude 'deploy/keys' --exclude 'deploy/.cache' --exclude '.git' \
    --exclude 'ruvector.db' --exclude 'uploads' \
    "$APP/" "$LIVE/forge-rei/" || return 1

  echo "==> sync non-secret agent folders (config/*.env preserved on box)"
  for d in forge-agency forge-scout forge-marcus forge-solomon forge-telegram forge-daycare forge-dropship forge-mission; do
    if [ -d "$REPO/$d" ]; then
      rsync -a --exclude '__pycache__' --exclude 'config' --exclude '*.env' \
        "$REPO/$d/" "$LIVE/$d/" || return 1
      echo "   synced $d"
    fi
  done

  echo "==> sync repo-root constitution -> $LIVE/NORTH_STAR.md"
  if [ -f "$REPO/NORTH_STAR.md" ]; then
    cp "$REPO/NORTH_STAR.md" "$LIVE/NORTH_STAR.md" || return 1
    echo "   synced NORTH_STAR.md"
  else
    echo "   (NORTH_STAR.md not found in repo — skipping)"
  fi
}

# /api/system/health -> "true" | "false <reason>" | "down" (unreachable / not JSON).
# ok must be JSON true — the key merely existing is not health.
fleet_ok() {
  local body
  body="$(curl -fsS --max-time 10 "http://127.0.0.1:$PORT/api/system/health" 2>/dev/null)" \
    || { echo down; return 0; }
  printf '%s' "$body" | python3 -c 'import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("down"); sys.exit(0)
if not isinstance(d, dict):
    print("down")
elif d.get("ok") is True:
    print("true")
else:
    print("false", d.get("reason") or "")' 2>/dev/null || echo down
}

# Telegram alert to HQ via the EXISTING telegram_io helper in the live tree. Env-only
# resolvers + _api: never writes marcus_state/telegram.json (the service owns its offset).
alert() {
  echo "$1"
  local to=""
  command -v timeout >/dev/null 2>&1 && to="timeout 30"
  ( cd "$LIVE/forge-rei" && $to python3 -c 'import sys, telegram_io as t
if t._token() and t._chat_id():
    t._api("sendMessage", {"chat_id": t._chat_id(), "text": sys.argv[1]}, timeout=10)
    print("   telegram alert sent")
else:
    print("   (telegram not configured - alert only in this log)")' "$1" ) 2>&1 | tail -1 || true
}

# The gate. $1 = fleet health BEFORE this deploy. Always required: service active,
# /api/health 200, /api/system/health reachable JSON, state not served. ok must be true —
# unless the fleet was ALREADY not-ok before we touched it (AI credits dead, a red loop,
# disk): then this commit didn't cause it, and blocking/rolling back would freeze every
# deploy (and restart twice per commit) for an outage code can't fix.
health_gate() {
  local pre="$1" waited=0 st hc
  echo "==> verify healthy (system health before deploy: $pre)"
  sleep 3
  while :; do
    st="$(fleet_ok)"
    [ "${st%% *}" = true ] && break
    [ "${st%% *}" = false ] && [ "$pre" != true ] && break   # same not-ok as before: stop waiting
    [ "$waited" -ge "$HEALTH_WAIT" ] && break
    sleep 5; waited=$((waited + 5))
  done
  systemctl is-active --quiet forge-reios \
    || { echo '   !! forge-reios NOT active'; systemctl status forge-reios --no-pager -l | tail -20; return 1; }
  curl -fsS --max-time 10 "http://127.0.0.1:$PORT/api/health" >/dev/null \
    || { echo '   !! /api/health not 200'; return 1; }
  hc=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/marcus_state/heartbeats.json")
  [ "$hc" = 404 ] || { echo "   !! heartbeats.json served ($hc) — must 404"; return 1; }
  case "${st%% *}" in
    true) echo "   OK: service active · endpoints 200 · system health ok:true · state not served" ;;
    false)
      if [ "$pre" = true ]; then
        echo "   !! /api/system/health ok:false after ${waited}s (was ok:true before deploy): ${st#false}"
        return 1
      fi
      echo "   WARN: /api/system/health ok:false, but it was already '$pre' BEFORE this deploy —"
      echo "         not this commit's fault, not rolling back:${st#false}" ;;
    *) echo "   !! /api/system/health unreachable or not JSON after ${waited}s"; return 1 ;;
  esac
}

# Health failed after the new code went live: put the last HEALTHY commit (.deployed_sha)
# back, restart, re-check, alert, exit 1. .deployed_sha is never pointed at the bad commit.
rollback() {
  echo "!! DEPLOY ${AFTER:0:7} FAILED the health gate"
  # Burn this commit's autopull retry budget: retrying a post-restart failure costs two
  # restarts per try. The next push (or a manual deploy-pull.sh) tries again.
  printf '%s %s\n' "$AFTER" 999 > "$LIVE/.deploy_attempts"
  if [ -z "$PREV" ] || [ "$PREV" = "$AFTER" ] || ! git -C "$REPO" cat-file -e "$PREV^{commit}" 2>/dev/null; then
    alert "🔴 FORGE deploy ${AFTER:0:7} failed its health check and there is no other last-good commit to roll back to (.deployed_sha='${PREV:0:7}'). The box may be down — check it."
    exit 1
  fi
  echo "==> ROLLBACK: restore last good $PREV"
  local how="rolled back to ${PREV:0:7} and it is healthy again"
  if git -C "$REPO" reset --hard --quiet "$PREV" && sync_tree; then
    if [ "$NEED_RESTART" = 1 ]; then
      echo "==> restart forge-reios (rollback)"
      systemctl restart forge-reios || true
    fi
    health_gate "$PRE" || how="rolled back to ${PREV:0:7} but it is ALSO unhealthy — check the box"
  else
    how="ROLLBACK to ${PREV:0:7} FAILED (git/rsync error) — check the box"
  fi
  alert "🔴 FORGE deploy ${AFTER:0:7} failed its health check; $how. Fix and push again."
  exit 1
}

# Restart only when something the Python process loads changed. jsx/css/html/images
# are read from disk per request and .md (skills, NORTH_STAR) is mtime hot-reloaded, so
# a UI- or docs-only commit needs none. Mac auto-sync commits every minute; restarting on
# each one (~4.5/h) dropped daycare sessions and in-memory caches (Meta token rejection).
# Tool churn the process never loads is excluded too: ruflo's .swarm/ db, the audit
# agent's output/agent-audit/, Playwright MCP snapshots. FORGE_FORCE_RESTART=1 forces it.
# (Diff captured first, then grepped from a here-string: `git diff | grep -q` under
# pipefail reads a SIGPIPE'd git as failure on a big diff and would SKIP a needed restart.)
PREV="$(cat "$LIVE/.deployed_sha" 2>/dev/null || true)"
NEED_RESTART=1
if [ "${FORGE_FORCE_RESTART:-0}" != 1 ] && [ -n "$PREV" ] \
   && git -C "$REPO" cat-file -e "$PREV^{commit}" 2>/dev/null \
   && CHANGED="$(git -C "$REPO" diff --name-only "$PREV" "$AFTER")" \
   && ! { [ -n "$CHANGED" ] && grep -qvE '\.(jsx|css|html|md|png|jpe?g|svg|webp|ico|woff2?)$|^ios/|^docs/|(^|/)\.swarm/|^output/agent-audit/|(^|/)\.playwright-mcp/' <<<"$CHANGED"; }; then
  NEED_RESTART=0
fi

PRE="$(fleet_ok)"; PRE="${PRE%% *}"      # health of what is live now, before we touch it
sync_tree
if [ "$NEED_RESTART" = 1 ]; then
  echo "==> restart forge-reios"
  systemctl restart forge-reios || echo "   !! systemctl restart failed — the health gate decides"
else
  echo "==> static/docs-only change since $PREV — no restart needed"
fi

# ---------------------------------------------------------------------------
# Post-deploy health gate — verify the box actually came back up; roll back if not.
# ---------------------------------------------------------------------------
health_gate "$PRE" || rollback

# LAST step, only after the health gate: record what is actually live. autopull.sh
# compares origin/main against THIS (not repo HEAD — the reset above moves HEAD before
# validate/rsync/restart, so a deploy killed mid-way used to look "done" forever).
printf '%s\n' "$AFTER" > "$LIVE/.deployed_sha.tmp" && mv "$LIVE/.deployed_sha.tmp" "$LIVE/.deployed_sha"
rm -f "$LIVE/.deploy_attempts"
echo "Done. Live: https://forge-reios.tail0a2dda.ts.net"
