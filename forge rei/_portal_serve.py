import sys, tempfile, pathlib, json
sys.path.insert(0, ".")
import connector, agency_io, agency_requests_io
from http.server import ThreadingHTTPServer

td = tempfile.mkdtemp()
agency_io.STATE = pathlib.Path(td) / "agency.json"
agency_requests_io.STATE = pathlib.Path(td) / "requests.json"

cid = agency_io.save_client({"name": "Bloom Dental", "business": "Bloom Family Dentistry", "site": "bloomdental.com"})["client"]["id"]
tok = agency_io.ensure_portal_token(cid)["portalToken"]
# seed a couple of existing requests across statuses so the tracker shows
import agency_portal_io
agency_portal_io.submit(cid, tok, {"title": "Swap homepage hero image", "type": "Website Edit", "priority": "high", "detail": "Use the new photoshoot hero; headline to 'Gentle dentistry for the whole family'."})
r2 = agency_portal_io.submit(cid, tok, {"title": "Fix contact form not sending", "type": "Bug Fix", "priority": "urgent", "detail": "Form submits but no email arrives."})
agency_requests_io.set_status(r2["request"]["id"], "in_progress", "Dyson on it")

print("PORTAL_URL http://localhost:8899/portal?c=%s&k=%s" % (cid, tok), flush=True)
ThreadingHTTPServer(("0.0.0.0", 8899), connector.PortalHandler).serve_forever()
