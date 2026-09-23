"""test_eco_datasource.py — creed honesty: Eco never passes mock/rejected numbers as live.

Run: cd "forge rei" && python3 test_eco_datasource.py   (exit 1 on failure). No network.
"""
import os

os.environ.pop("META_ACCESS_TOKEN", None)
os.environ.pop("META_AD_ACCOUNT_MAP", None)

import agency_ads
import agency_eco

# 1. No token -> mock, with a window.
a = agency_ads.analytics()
assert a["dataSource"] == "mock", a["dataSource"]
assert a["dateRange"]["days"] == 7 and a["dateRange"]["since"] < a["dateRange"]["until"], a["dateRange"]

# 2. The field survives into the Eco payload (read view, no Claude).
eco = agency_eco.recommendations()
assert eco["dataSource"] == "mock", eco.get("dataSource")
assert eco["dateRange"] == a["dateRange"], eco.get("dateRange")
assert "DATA SOURCE: MOCK" in agency_eco._format_analytics_block(a)

# 3. Meta rejects the token -> "token_rejected", not "mock" and never "live".
os.environ["META_ACCESS_TOKEN"] = "fake-test-token"
_real = agency_ads._live_analytics
agency_ads._live_analytics = lambda *a_, **k: (_ for _ in ()).throw(
    RuntimeError("Meta 400: Invalid OAuth access token (#190)"))
try:
    r = agency_ads.analytics()
    assert r["dataSource"] == "token_rejected", r["dataSource"]
    assert agency_eco.recommendations()["dataSource"] == "token_rejected"
finally:
    agency_ads._live_analytics = _real
    agency_ads._AUTH_DEAD.clear()
    os.environ.pop("META_ACCESS_TOKEN", None)

print("test_eco_datasource: OK")
