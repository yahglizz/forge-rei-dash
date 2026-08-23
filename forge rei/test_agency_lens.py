#!/usr/bin/env python3
"""Self-check for the agency Personal/Business lens split (data.jsx + app.jsx).

The lens lives in the buildless UI, so there is no Python to import — this
parses the real nav table and asserts the invariants that would silently break
it: a client tab leaking into Personal, a personal tab leaking into Business, a
nav key with no page behind it, or the daycare ad account falling back to a demo
account (which is what put a dentist's spend on a daycare tab once before).

    python3 test_agency_lens.py     # exit 1 on failure
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DAYCARE_ENV = os.path.join(HERE, "..", "forge-daycare", "config", "daycare.env")


def _nav():
    src = open(os.path.join(HERE, "data.jsx"), encoding="utf-8").read()
    block = src.split("const AGENCY_NAV = [", 1)[1].split("\n];", 1)[0]
    tuples = re.findall(r'\["([A-Za-z]+)",\s*"([^"]+)"(?:,\s*"([pb])")?\]', block)
    assert tuples, "AGENCY_NAV did not parse"
    return tuples


def _pages():
    src = open(os.path.join(HERE, "app.jsx"), encoding="utf-8").read()
    block = src.split("const AGENCY_PAGES = {", 1)[1].split("\n};", 1)[0]
    return set(re.findall(r"^\s{2}([A-Za-z]+):\s*\(\) =>", block, re.M))


def test_lenses_do_not_leak():
    tuples = _nav()
    personal = [t[0] for t in tuples if not t[2] or t[2] == "p"]
    business = [t[0] for t in tuples if not t[2] or t[2] == "b"]

    assert personal[0] == "MyBiz", f"Personal lands on {personal[0]}"
    assert business[0] == "Dashboard", f"Business lands on {business[0]}"

    # Client work must never show up under Personal.
    for client_tab in ("Clients", "Messages", "ClientView", "Requests", "Revenue"):
        assert client_tab in business, f"{client_tab} vanished from Business"
        assert client_tab not in personal, f"{client_tab} leaked into Personal"

    # My own businesses must never show up under Business.
    for mine in ("MyBiz", "MyAds", "MySocial", "MyStudio"):
        assert mine in personal, f"{mine} vanished from Personal"
        assert mine not in business, f"{mine} leaked into Business"

    # Shared infra shows on both sides.
    for shared in ("Agents", "Office", "Brain", "Settings"):
        assert shared in personal and shared in business, f"{shared} is not shared"

    return personal, business


def test_every_nav_key_has_a_page():
    tuples = _nav()
    pages = _pages()
    missing = sorted(t[0] for t in tuples if t[0] not in pages)
    assert not missing, f"nav keys with no AGENCY_PAGES entry: {missing}"


def test_daycare_ad_account_is_real():
    """The Personal > Daycare Ads tab must resolve the daycare's own account.

    Without META_AD_ACCOUNT_MAP, agency_ads.analytics falls back to _ACCOUNTS[0]
    (a demo account), which is how another business's spend once rendered under
    a daycare badge. daycare_growth guards against it; this asserts the fix.
    """
    if not os.path.exists(DAYCARE_ENV):
        print("SKIP daycare ad account — daycare.env not on this machine")
        return
    raw = [l.split("=", 1)[1].strip()
           for l in open(DAYCARE_ENV, encoding="utf-8").read().splitlines()
           if l.startswith("META_AD_ACCOUNT_MAP=")]
    assert len(raw) == 1, f"expected 1 META_AD_ACCOUNT_MAP line, found {len(raw)}"
    acct = json.loads(raw[0]).get("daycare")
    assert acct and acct.startswith("act_"), f"bad daycare ad account: {acct!r}"

    sys.path.insert(0, HERE)
    import agency_ads
    demo = [a["id"] for a in agency_ads._ACCOUNTS]
    assert acct not in demo, f"daycare resolves to demo account {acct}"


if __name__ == "__main__":
    personal, business = test_lenses_do_not_leak()
    test_every_nav_key_has_a_page()
    test_daycare_ad_account_is_real()
    print(f"OK — Personal {len(personal)} tabs: {personal}")
    print(f"OK — Business {len(business)} tabs")
    print("OK — agency lens split intact")
