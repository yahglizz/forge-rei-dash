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

# --- one key across the dashboard: the agency falls back to the daycare key; opt-out keeps them apart ---
import os, agency_billing
agency_billing.AGENCY_ENV_CANDIDATES = []
os.environ.pop("AGENCY_STRIPE_SECRET_KEY", None)
stripe_io._secret_key = lambda: "rk_live_shared_shared_shared"
assert agency_billing.configured() and agency_billing._secret_key().startswith("rk_live_shared")
assert agency_billing.status()["sharedKey"] is True
os.environ["FORGE_STRIPE_SHARED"] = "0"
assert not agency_billing.configured()
del os.environ["FORGE_STRIPE_SHARED"]
os.environ["AGENCY_STRIPE_SECRET_KEY"] = "rk_live_own_own_own_own"
assert agency_billing._secret_key().startswith("rk_live_own") and agency_billing.status()["sharedKey"] is False
del os.environ["AGENCY_STRIPE_SECRET_KEY"]

# health(): cached, never raises, reports mode + balance
stripe_io._HEALTH.update(at=0.0, val=None)
stripe_io._req = lambda m, p, params=None, key=None: {"available": [{"amount": 1234}], "pending": [{"amount": 50}]}
h = stripe_io.health()
assert h["ok"] and h["mode"] == "live" and h["availableUSD"] == 12.34 and h["pendingUSD"] == 0.5, h
def boom(*a, **k): raise stripe_io.StripeError(403, "nope")
stripe_io._HEALTH.update(at=0.0, val=None); stripe_io._req = boom
assert stripe_io.health()["ok"] is False
print("stripe shared key + health OK")
