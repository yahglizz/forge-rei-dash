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
