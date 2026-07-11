#!/bin/bash
# Install the FORGE REI OS end-of-day learning agent as a macOS LaunchAgent.
# Runs every day at 9:00 PM: POSTs to the running connector, which reads the day's
# texts, learns Yahjair's voice, and writes new skills into the brain.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${FORGE_PORT:-7799}"
LABEL="com.forge.reios.daily-learn"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$DIR/marcus_state"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/curl</string>
    <string>-s</string>
    <string>-X</string>
    <string>POST</string>
    <string>http://localhost:$PORT/api/style/run</string>
    <string>-H</string>
    <string>Content-Type: application/json</string>
    <string>-d</string>
    <string>{"days":1}</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>21</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$DIR/marcus_state/daily-learn.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/marcus_state/daily-learn.err.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed: $LABEL"
echo "Next run: every day 9:00 PM"
echo "Stop:    launchctl unload \"$PLIST\""
echo "Logs:    $DIR/marcus_state/daily-learn.*.log"
echo
echo "NOTE: connector must be running + ANTHROPIC_API_KEY set for learning to work."
