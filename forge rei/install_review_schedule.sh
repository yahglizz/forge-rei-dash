#!/bin/bash
# Install FORGE REI OS weekly AI review as a macOS LaunchAgent so it runs
# every Monday at 8:00 AM (POSTs to the already-running connector).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${FORGE_PORT:-7799}"
LABEL="com.forge.reios.weekly-review"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
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
    <string>http://localhost:$PORT/api/review/run</string>
    <string>-H</string>
    <string>Content-Type: application/json</string>
    <string>-d</string>
    <string>{"days":7}</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>1</integer>
    <key>Hour</key><integer>8</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$DIR/marcus_state/review.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/marcus_state/review.err.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed: $LABEL"
echo "Next run: Mondays 8:00 AM"
echo "Stop:    launchctl unload \"$PLIST\""
echo "Logs:    $DIR/marcus_state/review.*.log"
echo
echo "NOTE: connector must be running (install_service.sh) for the POST to succeed."
