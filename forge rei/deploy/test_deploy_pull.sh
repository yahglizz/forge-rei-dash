#!/usr/bin/env bash
# test_deploy_pull.sh — offline dry-run harness for deploy-pull.sh (run on the Mac, never the box):
# fake git origin/repo/live tree in a temp dir, stub systemctl/curl/sleep/node/timeout on PATH. Never touches /opt/forge.
set -uo pipefail
SCRIPT="$(cd "$(dirname "$0")" && pwd)/deploy-pull.sh"
PASS=0; FAIL=0
ALLW=()
trap 'rm -rf ${ALLW[@]+"${ALLW[@]}"}' EXIT
ok()   { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

setup() {
  W="$(mktemp -d)"; export W; ALLW+=("$W")
  STUB="$W/stub"; mkdir -p "$STUB" "$W/live/forge-rei"
  # --- stubs ---
  cat > "$STUB/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$W/systemctl.log"
case "$1" in
  is-active) [ -e "$W/live/forge-rei/crash_marker.py" ] && exit 3; exit 0 ;;
  status) echo "stub status: failed"; exit 3 ;;
  *) exit 0 ;;
esac
EOF
  cat > "$STUB/curl" <<'EOF'
#!/usr/bin/env bash
url="${@: -1}"
echo "$url" >> "$W/curl.log"
[ -e "$W/live/forge-rei/crash_marker.py" ] && exit 7          # process dead
case "$url" in
  */marcus_state/heartbeats.json) printf 404 ;;
  */api/health) echo '{"ok": true}' ;;
  */api/system/health)
    if [ -e "$W/live/forge-rei/bad_marker.py" ] || [ -e "$W/fleet_down" ]; then
      echo '{"ok": false, "reason": "AI hard-down: stub", "redLoops": []}'
    else
      echo '{"ok": true, "reason": null, "redLoops": []}'
    fi ;;
esac
exit 0
EOF
  printf '#!/bin/sh\nexit 0\n' > "$STUB/sleep"
  printf '#!/bin/sh\nexit 0\n' > "$STUB/node"
  printf '#!/bin/sh\nshift; exec "$@"\n' > "$STUB/timeout"
  chmod +x "$STUB"/*
  # --- fake origin + box clone ---
  git init -q --bare "$W/origin.git"
  git -C "$W/origin.git" symbolic-ref HEAD refs/heads/main
  git clone -q "$W/origin.git" "$W/src" 2>/dev/null
  mkdir -p "$W/src/forge rei/deploy"
  echo 'print("v1")' > "$W/src/forge rei/connector.py"
  cat > "$W/src/forge rei/telegram_io.py" <<'EOF'
import os
def _token(): return "stub-token"
def _chat_id(): return "123"
def _api(method, payload, timeout=15, token=None):
    with open(os.path.join(os.environ["W"], "alerts.log"), "a") as f:
        f.write(payload["text"] + "\n")
    return {"ok": True}
EOF
  echo "# north" > "$W/src/NORTH_STAR.md"
  git -C "$W/src" add -A && git -C "$W/src" -c user.name=t -c user.email=t@t commit -qm c1
  git -C "$W/src" branch -M main && git -C "$W/src" push -q origin main
  git clone -q "$W/origin.git" "$W/repo"
  C1="$(git -C "$W/repo" rev-parse HEAD)"
  # live = c1 deployed and healthy
  rsync -a --exclude .git "$W/repo/forge rei/" "$W/live/forge-rei/"
  echo "$C1" > "$W/live/.deployed_sha"
  : > "$W/systemctl.log"
}

commit() {  # commit <msg> <cmds...>: run cmds in src, commit + push
  local msg="$1"; shift
  ( cd "$W/src" && eval "$@" ) && git -C "$W/src" add -A \
    && git -C "$W/src" -c user.name=t -c user.email=t@t commit -qm "$msg" \
    && git -C "$W/src" push -q origin main
  git -C "$W/src" rev-parse HEAD
}

run_deploy() {
  PATH="$STUB:$PATH" FORGE_DEPLOY_REPO="$W/repo" FORGE_DEPLOY_LIVE="$W/live" \
    FORGE_DEPLOY_HEALTH_WAIT=10 bash "$SCRIPT" > "$W/out.log" 2>&1
  echo $?
}
restarts() { grep -c '^restart forge-reios' "$W/systemctl.log" || true; }

echo "== A: healthy code deploy passes"
setup
/bin/sleep 1.1; # rsync quick-check is 1 s mtime: keep c2 off c1's second
C2="$(commit c2 "echo 'print(\"v2\")' > 'forge rei/connector.py'")"
rc="$(run_deploy)"
check "exit 0" '[ "$rc" = 0 ]'
check "restarted once" '[ "$(restarts)" = 1 ]'
check ".deployed_sha = new commit" '[ "$(cat $W/live/.deployed_sha)" = "$C2" ]'
check "live has new code" 'grep -q v2 "$W/live/forge-rei/connector.py"'
check "no alert" '[ ! -s "$W/alerts.log" ]'
check "gate saw ok:true" 'grep -q "system health ok:true" "$W/out.log"'

echo "== B: deploy whose system health is ok:false (was ok:true) rolls back"
setup
C1="$(cat "$W/live/.deployed_sha")"
C3="$(commit c3 "echo 'x=1' > 'forge rei/bad_marker.py'")"
rc="$(run_deploy)"
check "exit non-zero" '[ "$rc" != 0 ]'
check "restarted twice (deploy + rollback)" '[ "$(restarts)" = 2 ]'
check ".deployed_sha still last good" '[ "$(cat $W/live/.deployed_sha)" = "$C1" ]'
check "bad file removed from live" '[ ! -e "$W/live/forge-rei/bad_marker.py" ]'
check "repo HEAD reset to last good" '[ "$(git -C $W/repo rev-parse HEAD)" = "$C1" ]'
check "alert sent: rolled back + healthy" 'grep -q "rolled back to ${C1:0:7} and it is healthy" "$W/alerts.log"'
check "retry budget burned" '[ "$(cat $W/live/.deploy_attempts)" = "$C3 999" ]'
check "log names the failure" 'grep -q "ok:false after" "$W/out.log"'

echo "== C: .swarm / output/agent-audit / .playwright-mcp only -> no restart"
setup
C4="$(commit c4 "mkdir -p .swarm 'forge rei/.swarm' output/agent-audit .playwright-mcp 'forge rei/.playwright-mcp'; echo a > .swarm/agentdb-memory.db; echo b > 'forge rei/.swarm/agentdb-memory.db-wal'; echo c > output/agent-audit/r.json; echo d > .playwright-mcp/p.yml; echo e > 'forge rei/.playwright-mcp/q.yml'")"
rc="$(run_deploy)"
check "exit 0" '[ "$rc" = 0 ]'
check "no restart" '[ "$(restarts)" = 0 ]'
check "said static/docs-only" 'grep -q "no restart needed" "$W/out.log"'
check ".deployed_sha updated" '[ "$(cat $W/live/.deployed_sha)" = "$C4" ]'

echo "== C2: .swarm change PLUS a .py change -> restart"
setup
commit c5 "mkdir -p .swarm; echo a > .swarm/x.db; echo 'print(3)' > 'forge rei/connector.py'" >/dev/null
rc="$(run_deploy)"
check "exit 0" '[ "$rc" = 0 ]'
check "restarted" '[ "$(restarts)" = 1 ]'

echo "== D: fleet already ok:false BEFORE deploy (AI down) -> deploy proceeds, WARN, no rollback"
setup
touch "$W/fleet_down"
C6="$(commit c6 "echo 'print(6)' > 'forge rei/connector.py'")"
rc="$(run_deploy)"
check "exit 0" '[ "$rc" = 0 ]'
check "restarted once" '[ "$(restarts)" = 1 ]'
check "WARN logged" 'grep -q "WARN: /api/system/health ok:false" "$W/out.log"'
check ".deployed_sha updated" '[ "$(cat $W/live/.deployed_sha)" = "$C6" ]'
check "no alert" '[ ! -s "$W/alerts.log" ]'

echo "== E: new code crashes the service -> rollback even though fleet was down before"
setup
touch "$W/fleet_down"
C1="$(cat "$W/live/.deployed_sha")"
commit c7 "echo 'x=1' > 'forge rei/crash_marker.py'" >/dev/null
rc="$(run_deploy)"
check "exit non-zero" '[ "$rc" != 0 ]'
check "NOT active detected" 'grep -q "forge-reios NOT active" "$W/out.log"'
check "rolled back" '[ ! -e "$W/live/forge-rei/crash_marker.py" ] && [ "$(cat $W/live/.deployed_sha)" = "$C1" ]'
check "alert sent" 'grep -q "failed its health check" "$W/alerts.log"'

echo "== F: unhealthy with no last-good marker -> alert, exit 1, marker not written"
setup
rm -f "$W/live/.deployed_sha"
commit c8 "echo 'x=1' > 'forge rei/bad_marker.py'" >/dev/null
rc="$(run_deploy)"
check "exit non-zero" '[ "$rc" != 0 ]'
check "no .deployed_sha written" '[ ! -e "$W/live/.deployed_sha" ]'
check "alert: no rollback target" 'grep -q "no other last-good commit" "$W/alerts.log"'

echo "== G: validation failure aborts before touching live (unchanged behavior)"
setup
C1="$(cat "$W/live/.deployed_sha")"
commit c9 "echo 'def (' > 'forge rei/broken.py'" >/dev/null
rc="$(run_deploy)"
check "exit non-zero" '[ "$rc" != 0 ]'
check "no restart, live untouched" '[ "$(restarts)" = 0 ] && [ ! -e "$W/live/forge-rei/broken.py" ] && [ "$(cat $W/live/.deployed_sha)" = "$C1" ]'

echo
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
