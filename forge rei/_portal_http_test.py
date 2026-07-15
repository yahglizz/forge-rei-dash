import sys, tempfile, pathlib, threading, json, time, urllib.request, urllib.error
sys.path.insert(0, ".")
import connector, agency_io, agency_requests_io
from http.server import ThreadingHTTPServer

td = tempfile.mkdtemp()
agency_io.STATE = pathlib.Path(td) / "agency.json"
agency_requests_io.STATE = pathlib.Path(td) / "requests.json"

# seed one client + token
cid = agency_io.save_client({"name": "Bloom Dental", "business": "Dentistry"})["client"]["id"]
tok = agency_io.ensure_portal_token(cid)["portalToken"]

PORT = 8899
srv = ThreadingHTTPServer(("127.0.0.1", PORT), connector.PortalHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.4)
BASE = f"http://127.0.0.1:{PORT}"

_bad = False
def check(name, cond):
    global _bad
    print(("PASS" if cond else "FAIL"), name)
    if not cond: _bad = True

def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")

def post(path, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")

# portal page serves on / and /portal
s, body = get("/")
check("GET / serves portal page", s == 200 and "ClientForge" in body)
s, body = get("/portal")
check("GET /portal serves page", s == 200 and "Request an Edit" in body)

# bootstrap works with token
s, body = get(f"/api/portal/bootstrap?c={cid}&k={tok}")
d = json.loads(body)
check("bootstrap 200 + ok", s == 200 and d.get("ok") and d["clientName"] == "Bloom Dental")

# bootstrap bad token → error json (still 200 body, error field)
s, body = get(f"/api/portal/bootstrap?c={cid}&k=badtoken")
check("bootstrap bad token → error", "error" in json.loads(body))

# submit works
s, body = post("/api/portal/submit", {"c": cid, "k": tok, "title": "Fix footer", "type": "Bug Fix", "priority": "medium", "detail": "broken link"})
d = json.loads(body)
check("submit 200 + ok + portal source", s == 200 and d.get("ok") and d["request"]["source"] == "portal")

# submit bad token rejected
s, body = post("/api/portal/submit", {"c": cid, "k": "nope", "title": "x"})
check("submit bad token → error", "error" in json.loads(body))

# ── SECURITY BOUNDARY: the portal server must 404 everything else ──
for p in ["/api/agency/requests", "/api/sync", "/api/agency/clients",
          "/api/portal/links", "/FORGE%20REI%20OS.html", "/connector.py",
          "/api/agency/portal/links", "/dashboard", "/config/agency.env"]:
    s, _ = get(p)
    check(f"BLOCKED GET {p} → 404", s == 404)

# POST to anything but submit → 404
s, _ = post("/api/agency/request/save", {"title": "x"})
check("BLOCKED POST /api/agency/request/save → 404", s == 404)

srv.shutdown()
print("\nRESULT:", "ALL GREEN" if not _bad else "HAS FAILURES")
