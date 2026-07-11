#!/bin/bash
# FORGE REI OS — end-of-day learning sweep.
# Fires once a day (systemd forge-daily-learn.timer @ 8pm America/New_York) and makes
# EVERY self-improving agent reflect on the day's real activity and rewrite its playbook
# into the brain (vault/Skills/*.md, git-committed). Next run each agent reloads the
# newer playbook (mtime hot-reload) — closed daily improvement loop (CLAUDE.md §3).
#
# Read-only on GHL. No outward action. Each call is one Claude reflection; we space them
# out and keep going if one fails, so a single hiccup never skips the rest.
set -u
PORT="${FORGE_PORT:-7799}"
BASE="http://127.0.0.1:${PORT}"
LOG="/opt/forge/forge-rei/marcus_state/daily-learn.log"
ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

hit() {  # hit <label> <path> <json-body>
  local label="$1" path="$2" body="$3"
  local out
  out=$(curl -s --max-time 180 -X POST "${BASE}${path}" \
        -H "Content-Type: application/json" -d "${body}" 2>&1)
  echo "$(ts) [${label}] ${out:0:300}" >> "$LOG"
}

echo "$(ts) ===== daily learn start =====" >> "$LOG"
hit scout     /api/scout/learn          '{"auto":true}'
sleep 5
hit screening /api/screening/learn      '{"auto":true}'
sleep 5
hit voice     /api/style/run            '{"days":1}'
sleep 5
hit review    /api/review/run           '{"days":1}'
sleep 5
hit dyson     /api/agency/agents/learn  '{"agentId":"dyson"}'
sleep 5
hit eco       /api/agency/agents/learn  '{"agentId":"eco"}'
echo "$(ts) ===== daily learn done =====" >> "$LOG"
