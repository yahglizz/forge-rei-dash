#!/bin/zsh
# Installs the Mac worker to ~/.forge-mac (not AgentDrive, so it survives an unmounted drive) and starts
# it under launchd. Safe to rerun: an existing key is kept. Prints the key's SHA-256 only, never the key.
# The box takes that hash as FORGE_MAC_KEY_SHA256 and rejects the worker until it is set.
set -eu
here=${0:A:h}
dest=$HOME/.forge-mac
plist=$HOME/Library/LaunchAgents/com.forge.mac-worker.plist
mkdir -p "$dest" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
chmod 700 "$dest"
cp "$here/mac_worker.py" "$dest/mac_worker.py"
hash=$(/usr/bin/python3 - "$dest/key" <<'PY'
import hashlib, os, secrets, sys
path = sys.argv[1]
if not os.path.exists(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secrets.token_urlsafe(48))
os.chmod(path, 0o600)
print(hashlib.sha256(open(path).read().strip().encode()).hexdigest())
PY
)
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.forge.mac-worker</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>$dest/mac_worker.py</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/forge-mac-worker.launchd.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/forge-mac-worker.launchd.log</string>
</dict>
</plist>
PLIST
launchctl bootout "gui/$(id -u)/com.forge.mac-worker" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "FORGE_MAC_KEY_SHA256=$hash"
