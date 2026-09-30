"""send_invoice must pass pending_invoice_items_behavior=include, or Stripe-Version 2024-06-20 makes a $0 invoice."""
import stripe_io

calls = []
def fake(method, path, params=None, key=None):
    calls.append((method, path, params))
    if path == "/invoices" and method == "POST": return {"id": "in_x"}
    if path == "/customers" and method == "POST": return {"id": "cus_x"}
    if path == "/customers/search" or (method == "GET" and "search" in path): return {"data": []}
    return {"id": "in_x", "status": "open", "amount_due": 1500, "currency": "usd"}

stripe_io._req = fake
stripe_io._secret_key = lambda: "rk_live_testkey_testkey_testkey"
stripe_io.find_invoice = lambda _i: None
stripe_io.send_invoice({"invoice_id": "d1", "amount": 15, "guardian": {"id": "g1", "name": "T", "email": "t@example.com"}})
inv = [p for m, path, p in calls if path == "/invoices" and m == "POST"][0]
assert inv["pending_invoice_items_behavior"] == "include", inv
assert [p for m, path, p in calls if path == "/invoiceitems"][0]["amount"] == 1500
print("stripe invoice OK")
