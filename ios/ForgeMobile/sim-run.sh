#!/usr/bin/env bash
# Build FORGE Mobile for the iOS Simulator, install, launch.
#   ./sim-run.sh                         # iPhone 17 Pro, live box over Tailscale
#   ./sim-run.sh "iPhone 17e"            # another simulator
#   FORGE_URL=http://localhost:7799/m/ ./sim-run.sh   # via the SSH tunnel instead
set -euo pipefail
cd "$(dirname "$0")"
SIM="${1:-iPhone 17 Pro}"
BUNDLE=com.atouchofblessings.forgemobile
xcodegen generate --quiet
xcodebuild -project ForgeMobile.xcodeproj -scheme ForgeMobile -configuration Debug \
  -sdk iphonesimulator -destination "platform=iOS Simulator,name=$SIM" \
  -derivedDataPath build -quiet build
xcrun simctl boot "$SIM" 2>/dev/null || true
xcrun simctl install "$SIM" build/Build/Products/Debug-iphonesimulator/ForgeMobile.app
xcrun simctl terminate "$SIM" "$BUNDLE" 2>/dev/null || true
if [ -n "${FORGE_URL:-}" ]; then
  xcrun simctl launch "$SIM" "$BUNDLE" -ForgeBaseURL "$FORGE_URL"
else
  xcrun simctl launch "$SIM" "$BUNDLE"
fi
