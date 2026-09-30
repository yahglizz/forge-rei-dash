"""stripe_links: recurring + pay-in-full links for any business; reuse; caps. No network."""
import stripe_io, stripe_links

store = {"links": [], "products": []}
def fake(method, path, params=None, key=None):
    if path == "/products" and method == "GET": return {"data": store["products"]}
    if path == "/products":
        p = {"id": "prod_%d" % (len(store["products"]) + 1), "name": params["name"], "metadata": params["metadata"]}; store["products"].append(p); return p
    if path == "/payment_links" and method == "GET": return {"data": store["links"]}
    if path == "/payment_links":
        l = {"id": "plink_%d" % (len(store["links"]) + 1), "url": "https://buy.stripe.com/x%d" % len(store["links"]), "metadata": params["metadata"], "_p": params}
        store["links"].append(l); return l
    raise AssertionError(path)
stripe_io._req = fake
stripe_io._secret_key = lambda: "sk_live_test_test_test_test"

r = stripe_links.create({"offerId": "care-plan", "reference": "cli_1", "email": "a@b.com"})
assert r["ok"] and r["mode"] == "recurring" and r["display"].startswith("$129.00/mo"), r
assert "client_reference_id=cli_1" in r["url"] and "prefilled_email=a%40b.com" in r["url"], r["url"]
items = store["links"][0]["_p"]["line_items"]; assert items[0]["price_data"]["recurring"] == {"interval": "month"} and len(items) == 1

r2 = stripe_links.create({"offerId": "care-plan", "reference": "cli_2"})            # same link, new client tag
assert r2["reused"] and len(store["links"]) == 1 and "cli_2" in r2["url"]

r3 = stripe_links.create({"business": "agency", "name": "Website build", "amountUSD": 774, "mode": "one_time"})
assert r3["ok"] and r3["display"] == "$774.00 pay in full" and store["links"][1]["_p"]["invoice_creation"] == {"enabled": "true"}
assert "recurring" not in store["links"][1]["_p"]["line_items"][0]["price_data"]

r4 = stripe_links.create({"business": "daycare", "name": "Tuition", "amountUSD": 200, "mode": "recurring", "interval": "week", "upfrontUSD": 50})
assert r4["display"] == "$200.00/wk + $50.00 upfront" and len(store["links"][2]["_p"]["line_items"]) == 2

for bad in ({"name": "x", "amountUSD": 0}, {"name": "x", "amountUSD": 99999}, {"amountUSD": 5}, {"name": "x", "amountUSD": 5, "business": "nope"}, {"offerId": "zzz"}):
    assert not stripe_links.create(bad)["ok"], bad
assert stripe_links.offers()["offers"][0]["id"] == "care-plan"
print("stripe links OK")

# --- onboarding send: link built, GHL contact upserted, email (+sms) sent, billing recorded ---
import tempfile, pathlib, agency_io, agency_billing
agency_io.STATE = pathlib.Path(tempfile.mkdtemp()) / "agency.json"
cid = agency_io.save_client({"name": "Dana Smith", "business": "Bloom Dental", "email": "dana@bloom.test", "phone": "(215) 555-0134"})["client"]["id"]
class FakeGHL:
    configured, location_id = True, "loc1"
    def __init__(self): self.calls = []
    def post(self, ep, body):
        self.calls.append((ep, body))
        return {"contact": {"id": "ghl_c1"}} if ep == "/contacts/upsert" else {"messageId": "m1"}
g = FakeGHL()
r = agency_billing.send_to_client(g, cid, {"mode": "one_time", "name": "Website build", "amountUSD": 774}, ["email", "sms"])
assert r["ok"] and r["sent"] == {"email": True, "sms": True}, r
assert [c[0] for c in g.calls] == ["/contacts/upsert", "/conversations/messages", "/conversations/messages"]
assert g.calls[1][1]["type"] == "Email" and r["url"] in g.calls[1][1]["html"] and g.calls[2][1]["type"] == "SMS"
assert "client_reference_id=" + cid in r["url"] and "prefilled_email=dana%40bloom.test" in r["url"]
saved = agency_io.get_client(cid)
assert saved["ghlContactId"] == "ghl_c1" and saved["billing"]["display"] == "$774.00 pay in full" and saved["email"] == "dana@bloom.test"
g2 = FakeGHL(); r2 = agency_billing.send_to_client(g2, cid, {}, ["email"])       # default = care plan, reuses contact
assert r2["ok"] and r2["display"].startswith("$129.00/mo") and g2.calls[0][0] == "/conversations/messages"
agency_io.save_client({"id": cid, "name": "Dana Smith", "email": "", "phone": ""})
assert not agency_billing.send_to_client(FakeGHL(), cid, {}, ["email"])["ok"]       # no email -> refuse
assert not agency_billing.send_to_client(FakeGHL(), "nope", {}, ["email"])["ok"]
print("agency onboarding send OK")
