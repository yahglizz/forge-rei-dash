import sys, tempfile, pathlib
sys.path.insert(0, ".")
import agency_io, agency_requests_io, agency_portal_io

td = tempfile.mkdtemp()
agency_io.STATE = pathlib.Path(td) / "agency.json"
agency_requests_io.STATE = pathlib.Path(td) / "requests.json"

_bad = False
def check(name, cond):
    global _bad
    print(("PASS" if cond else "FAIL"), name)
    if not cond: _bad = True

c1 = agency_io.save_client({"name": "Bloom Dental", "business": "Dentistry", "site": "bloom.com"})
c2 = agency_io.save_client({"name": "Peak Fitness"})
id1, id2 = c1["client"]["id"], c2["client"]["id"]
check("two clients created", c1.get("ok") and c2.get("ok"))

li = agency_portal_io.link(id1, base="https://example.ts.net")
check("link minted", li.get("ok") and "portal?c=" in li["url"] and "&k=" in li["url"])
tok = li["portalToken"]

check("good token verifies", agency_io.verify_portal(id1, tok) is not None)
check("bad token rejected", agency_io.verify_portal(id1, "wrongtoken") is None)
check("empty token rejected", agency_io.verify_portal(id1, "") is None)

b0 = agency_portal_io.bootstrap(id1, tok)
check("bootstrap ok + client name", b0.get("ok") and b0["clientName"] == "Bloom Dental")
check("bootstrap starts empty", b0["requests"] == [])
check("bootstrap bad token errors", "error" in agency_portal_io.bootstrap(id1, "nope"))

s = agency_portal_io.submit(id1, tok, {"title": "Swap hero image", "type": "Website Edit",
                                       "priority": "high", "detail": "New photo + headline"})
check("submit ok", s.get("ok"))
check("submit source=portal", s["request"]["source"] == "portal")
check("submit locked clientId", s["request"]["clientId"] == id1)
check("submit clientName from record", s["request"]["clientName"] == "Bloom Dental")

sp = agency_portal_io.submit(id1, tok, {"title": "Spoof", "clientId": id2, "clientName": "Peak Fitness"})
check("spoof clientId ignored", sp["request"]["clientId"] == id1)

b1 = agency_portal_io.bootstrap(id1, tok)
check("client1 sees own 2 requests", b1["ok"] and len(b1["requests"]) == 2)

li2 = agency_portal_io.link(id2, base="https://example.ts.net")
b2 = agency_portal_io.bootstrap(id2, li2["portalToken"])
check("client2 sees zero (scoped)", b2["ok"] and len(b2["requests"]) == 0)

check("empty title rejected", "error" in agency_portal_io.submit(id1, tok, {"title": "   "}))

allr = agency_requests_io.list_requests()["requests"]
portal_ones = [r for r in allr if r.get("source") == "portal"]
check("admin sees portal requests", len(portal_ones) == 2)

old = tok
agency_io.rotate_portal_token(id1)
check("old token invalid after rotate", agency_io.verify_portal(id1, old) is None)

print("\nRESULT:", "ALL GREEN" if not _bad else "HAS FAILURES")
