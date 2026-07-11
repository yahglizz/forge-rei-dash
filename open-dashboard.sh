#!/usr/bin/env bash
# open-dashboard.sh — open the 24/7 FORGE REI OS dashboard.
# Box: root@24.199.81.124, connector.py on :7799 (DO cloud firewall blocks it
# publicly), so reach it over an SSH tunnel — no public exposure.
set -euo pipefail

BOX="root@24.199.81.124"
KEY="$HOME/.ssh/forge_droplet"
PORT=7799
URL="http://localhost:${PORT}/"

# Already reachable locally (tunnel or local dev server)? Just open it.
if curl -s -o /dev/null --max-time 3 "$URL"; then
  echo "dashboard already up -> $URL"
else
  echo "starting SSH tunnel to $BOX ..."
  ssh -i "$KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=8 \
      -f -N -L "${PORT}:localhost:${PORT}" "$BOX"
  for _ in $(seq 1 10); do
    curl -s -o /dev/null --max-time 2 "$URL" && break
    sleep 1
  done
fi

open "$URL"
echo "opened $URL"
