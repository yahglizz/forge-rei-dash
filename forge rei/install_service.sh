#!/bin/bash
# Install FORGE REI OS connector as a macOS LaunchAgent (auto-start at login, auto-restart
# if it crashes). UI-only: FORGE_MARCUS=0 — the 24/7 box is the ONLY machine that runs the
# agent loops; a second fleet here would double-text sellers and steal Telegram taps.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3)"
PORT="${FORGE_PORT:-7799}"
LABEL="com.forge.reios.connector"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>$DIR/connector.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>FORGE_PORT</key><string>$PORT</string><key>FORGE_MARCUS</key><string>0</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/marcus_state/connector.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/marcus_state/connector.err.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed + started: $LABEL"
echo "Dashboard: http://localhost:$PORT"
echo "Stop:    launchctl unload \"$PLIST\""
echo "Logs:    $DIR/marcus_state/connector.*.log"
echo
echo "NOTE: 24/7 only holds while this Mac is awake. Prevent sleep:"
echo "  System Settings > Battery/Lock Screen, or run: caffeinate -s"
