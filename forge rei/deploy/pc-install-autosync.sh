#!/usr/bin/env bash
# pc-install-autosync.sh — RUN ONCE on the Windows gaming PC in Git Bash.
# Registers a hidden Task Scheduler job that starts the auto-sync loop at every
# login, so Mac<->PC stay mirrored with zero windows to keep open.
#
#   cd ~/forge-rei-dash && git pull && ./"forge rei/deploy/pc-install-autosync.sh"
#
# Undo:  schtasks //Delete //TN ForgeAutoSync //F
set -euo pipefail

command -v cygpath >/dev/null 2>&1 || { echo "!! not Git Bash / MSYS — run this in Git Bash on Windows"; exit 1; }
command -v schtasks >/dev/null 2>&1 || { echo "!! schtasks not found — are you on Windows?"; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # repo root (POSIX)
SYNC="$REPO/forge rei/deploy/auto-sync.sh"
[ -f "$SYNC" ] || { echo "!! auto-sync.sh missing — run 'git pull' first"; exit 1; }
BASH_WIN="$(cygpath -w "$(which bash)")"

OUT="$HOME/.forge"; mkdir -p "$OUT"
CMD="$OUT/start-autosync.cmd"
VBS="$OUT/start-autosync.vbs"

# .cmd — launch the auto-sync loop (60s) via Git Bash login shell
printf '@"%s" --login -c "cd '\''%s'\'' && '\''%s'\'' 60"\r\n' "$BASH_WIN" "$REPO" "$SYNC" > "$CMD"

# .vbs — run that .cmd fully hidden (window style 0)
CMD_WIN="$(cygpath -w "$CMD")"
printf 'CreateObject("WScript.Shell").Run "cmd /c ""%s""", 0, False\r\n' "$CMD_WIN" > "$VBS"
VBS_WIN="$(cygpath -w "$VBS")"

# Register: run the hidden launcher at every logon
schtasks //Create //TN "ForgeAutoSync" //TR "wscript.exe \"$VBS_WIN\"" //SC ONLOGON //RL LIMITED //F

# Start it now so you don't have to log out/in
wscript.exe "$VBS_WIN" 2>/dev/null || cscript //nologo "$VBS_WIN" 2>/dev/null || true

echo
echo "OK — ForgeAutoSync installed + started (hidden, runs at every login)."
echo "Verify:  schtasks //Query //TN ForgeAutoSync"
echo "Stop:    schtasks //Delete //TN ForgeAutoSync //F   (then it won't restart at login)"
