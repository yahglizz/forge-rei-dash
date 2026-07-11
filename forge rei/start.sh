#!/bin/bash
# FORGE REI OS — launch the live dashboard (connector serves UI + GHL data).
cd "$(dirname "$0")"
PORT="${FORGE_PORT:-7799}"
echo "Starting FORGE REI OS on http://localhost:$PORT"
# Open the browser once the server is up.
( sleep 1; command -v open >/dev/null && open "http://localhost:$PORT" ) &
exec python3 connector.py
