#!/usr/bin/env bash
# Self-check for ./forge — runs a stub box on localhost, asserts arg parsing,
# stdin fallback, JSON escaping, and the unknown-agent guards. No network, no box.
#   ./test_forge_cli.sh   (exit 0 = pass)
set -uo pipefail
cd "$(dirname "$0")"

PORT=7811
python3 - "$PORT" <<'PY' &
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

ROSTER = {"agents": [{"id": "scout", "emoji": "S", "businessLabel": "Wholesale",
                      "role": "Lead Triage", "status": {}}]}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        self._send({"/api/hub/roster": ROSTER,
                    "/api/hub/tasks": {"tasks": [{"id": "t1", "agentId": "midas",
                                                  "status": "open", "createdAt": 0,
                                                  "title": "ship it"}]},
                    "/api/hub/bus": {"messages": [{"ts": 0, "from": "scout",
                                                   "to": "marcus", "text": "hot lead"}]}}[p])

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/hub/chat":
            self._send({"reply": "GOT:" + body["message"] + "|AS:" + body["agentId"]})
        else:
            self._send({"task": {"id": "t9", "agentName": "Midas", "title": body["title"]}})

HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY
STUB=$!
trap 'kill $STUB 2>/dev/null' EXIT
export FORGE_URL="http://127.0.0.1:$PORT"

for _ in $(seq 30); do
  curl -fsS -m 1 -o /dev/null "$FORGE_URL/api/hub/roster" 2>/dev/null && break
  sleep 0.2
done

fails=0
check() { # check <name> <expected-substring> <actual>
  case "$3" in *"$2"*) echo "ok   $1" ;;
                    *) echo "FAIL $1: wanted '$2', got '$3'"; fails=$((fails + 1)) ;; esac
}

check roster            "scout"                   "$(./forge agents)"
check chat              "GOT:what is hot|AS:scout" "$(./forge scout what is hot)"
check "chat quoting"    "GOT:it's \"20k\" & up"    "$(./forge scout "it's \"20k\" & up")"
check "chat via stdin"  "GOT:from a pipe|AS:marcus" "$(echo 'from a pipe' | ./forge marcus)"
check task              "filed -> Midas: ship it"  "$(./forge task midas ship it)"
check tasks             "ship it"                  "$(./forge tasks)"
check bus               "hot lead"                 "$(./forge bus)"
check json-passthrough  '"reply"'                  "$(./forge --json scout hi)"

# Guards: an unknown agent must not silently POST somewhere.
out="$(./forge nora hi 2>&1)"; rc=$?
check "unknown agent rc"    "2" "$rc"
check "unknown agent hint"  "unknown 'nora'" "$out"
out="$(./forge task nora hi 2>&1)"; rc=$?
check "unknown task agent"  "2" "$rc"
check "empty message"       "2" "$(./forge scout </dev/null >/dev/null 2>&1; echo $?)"

echo "---"
[ "$fails" -eq 0 ] && { echo "forge cli: all checks passed"; exit 0; }
echo "forge cli: $fails FAILED"; exit 1
