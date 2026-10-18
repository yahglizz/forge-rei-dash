#!/usr/bin/env bash
# higgsfield-login-box.sh — log the BOX's Higgsfield CLI into the owner's account. Run FROM THE MAC.
#
#   bash "forge rei/deploy/higgsfield-login-box.sh" [root@24.199.81.124] [--dry-run]
#
# Why a helper: `hf auth login` is a browser OAuth (PKCE) login whose callback lands on
# http://localhost:8765/callback of the machine running the CLI. The box has no browser, so we
# forward the Mac's localhost:8765 to the box over SSH: you open the printed link in your Mac
# browser, approve, and the callback travels the tunnel to the box. The box gets its OWN login
# (never a copy of the Mac's token — two machines sharing one refresh token log each other out).
#
# Steps it runs (nothing else): auth login → workspace list → workspace set <id> → account status.
# It never runs `hf auth token` and never prints a token. --dry-run prints the commands only.
# Env: FORGE_SSH_KEY (default ~/.ssh/forge_droplet) · HF_LOGIN_PORT (8765) · HF_BOX_BIN (/opt/forge/bin/hf)
set -euo pipefail

HOST="root@24.199.81.124"
DRY=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    -*) echo "unknown option: $a" >&2; exit 2 ;;
    *) HOST="$a" ;;
  esac
done
KEY="${FORGE_SSH_KEY:-$HOME/.ssh/forge_droplet}"
PORT="${HF_LOGIN_PORT:-8765}"
BIN="${HF_BOX_BIN:-/opt/forge/bin/hf}"
case "$PORT" in ''|*[!0-9]*) echo "HF_LOGIN_PORT must be a number" >&2; exit 2 ;; esac
# HOME=/root on every remote call = the same place the service reads (HIGGSFIELD_HOME=/root).
R="HOME=/root $BIN"
SSH=(ssh -i "$KEY" -o ServerAliveInterval=30)

run() {   # print, then run unless --dry-run
  printf '  $ %s\n' "$*"
  [ "$DRY" -eq 1 ] || "$@"
}

cat <<EOF
Higgsfield CLI login for the box ($HOST)
 1. A tunnel forwards this Mac's localhost:$PORT to the box, and the box starts 'hf auth login'.
 2. It prints a https://… login link. Open it in THIS Mac's browser and approve.
    (If it says it couldn't open a browser, that's expected — use the link.)
 3. The browser lands on localhost:$PORT/callback → tunnel → box. The login finishes there.
 4. Then you pick the workspace that holds your app credits.
EOF

if [ "$DRY" -eq 0 ] && command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use on this Mac — close that program or set HF_LOGIN_PORT." >&2
  exit 3
fi

echo; echo "Step 1–3: login (tunnel open while it runs)"
run "${SSH[@]}" -t -L "$PORT:localhost:$PORT" "$HOST" "$R auth login --port $PORT"

echo; echo "Step 4: your workspaces"
run "${SSH[@]}" "$HOST" "$R workspace list"

if [ "$DRY" -eq 1 ]; then
  WS="<workspace_id>"
else
  printf 'Paste the workspace id to use: '
  read -r WS
  case "$WS" in ''|*[!A-Za-z0-9_-]*) echo "That doesn't look like a workspace id — stopping." >&2; exit 4 ;; esac
fi
run "${SSH[@]}" "$HOST" "$R workspace set $WS"

echo; echo "Step 5: check (credits + plan; no token is shown)"
run "${SSH[@]}" "$HOST" "$R account status"

cat <<EOF

Done. The dashboard re-checks the engine within a minute (Growth → Ad Studio → Re-check).
Read-only shape check on the box:  cd /opt/forge/forge-rei && HIGGSFIELD_CLI_BIN=$BIN HOME=/root python3 higgsfield_io.py --probe
EOF
