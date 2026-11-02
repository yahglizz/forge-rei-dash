"""Fee links: mint a per-family Stripe payment link + draft, and read paid / unpaid back from Stripe.

All Stripe + GHL traffic is mocked. Nothing is charged, nothing is texted, no real family appears.
Run: python3 test_daycare_fees.py
"""
import time
from unittest import mock

import daycare_fees as fees
import daycare_ghl
import stripe_io

ATOB = "11111111-1111-1111-1111-111111111111"
ATOB2 = "22222222-2222-2222-2222-222222222222"
AMT = "44444444-4444-4444-4444-444444444444"
QA = "99999999-9999-9999-9999-999999999999"
NOW = int(time.time())


class FakeStripe:
    def __init__(self, sessions=(), links=()):
        self.sessions, self.links, self.calls = list(sessions), list(links), []

    def __call__(self, method, path, params=None, key=None):
        self.calls.append((method, path, params, key))
        if method == "GET" and path == "/checkout/sessions":
            return {"data": self.sessions, "has_more": False}
        if method == "GET" and path == "/payment_links":
            return {"data": self.links, "has_more": False}
        if method == "POST" and path == "/payment_links":
            return {"id": "plink_new1", "url": "https://buy.stripe.com/test_NEW"}
        raise AssertionError(f"unexpected Stripe call {method} {path}")


def keyfor(loc):
    return "sk_test_x" if str(loc) == QA else "sk_live_x"


def run(stripe, fn, *a, **k):
    fees._CACHE.clear(); fees._RECENT.clear()
    with mock.patch.object(stripe_io, "_req", stripe), mock.patch.object(stripe_io, "key_for_location", keyfor):
        return fn(*a, **k)


def sess(sid, status, link="plink_a", cents=4900, ago=60, meta=None):
    base = {"family": "Test Parent", "ghl_contact_id": "ABCDEF1234567890", "purpose": "registration-fee",
            "location": "loc-2318-cecil-b-moore"}
    return {"id": sid, "payment_link": link, "payment_status": status, "amount_total": cents,
            "created": NOW - ago, "metadata": base if meta is None else meta}


def q(loc):
    return {"location_id": [loc]}


def test_paid_wins_over_reopened_unpaid_sessions():
    st = FakeStripe([sess("cs_1", "unpaid", ago=10), sess("cs_2", "unpaid", ago=20), sess("cs_3", "paid", ago=300)])
    out = run(st, fees.list_fees, None, q(ATOB2))
    assert out["ok"] and len(out["fees"]) == 1, out
    r = out["fees"][0]
    assert r["status"] == "paid" and r["opens"] == 3 and r["amountCents"] == 4900 and r["paidAt"], r
    assert out["totals"] == {"paidCents": 4900, "paidCount": 1, "unpaidCents": 0, "unpaidCount": 0}
    assert out["testMode"] is False


def test_legacy_tag_maps_to_its_center_and_never_crosses_entities():
    st = FakeStripe([sess("cs_1", "paid")])
    assert len(run(st, fees.list_fees, None, q(ATOB2))["fees"]) == 1        # loc-2318 -> ATOB 2
    assert run(st, fees.list_fees, None, q(ATOB))["fees"] == []              # not the 921 center
    assert run(st, fees.list_fees, None, q(AMT))["fees"] == []               # never A Mother's Touch
    assert daycare_ghl.LOCATION_ID_BY_TAG["loc-2318-cecil-b-moore"] == ATOB2


def test_default_center_is_a_touch_of_blessings():
    st = FakeStripe([sess("cs_1", "paid", meta={"purpose": "deposit", "center_id": ATOB, "family": "Test Parent"})])
    out = run(st, fees.list_fees, None, {})
    assert out["centerId"] == ATOB and len(out["fees"]) == 1


def test_untagged_checkouts_are_ignored_and_unopened_links_show_unpaid():
    st = FakeStripe([sess("cs_x", "paid", link="plink_other", meta={})],
                    [{"id": "plink_u", "url": "https://buy.stripe.com/u", "metadata": {
                        "purpose": "deposit", "family": "Test Two", "center_id": ATOB, "amount_cents": "10000"}}])
    out = run(st, fees.list_fees, None, q(ATOB))
    assert [r["id"] for r in out["fees"]] == ["plink_u"], out
    r = out["fees"][0]
    assert r["status"] == "unpaid" and r["opens"] == 0 and r["amountCents"] == 10000 and r["url"]
    assert out["totals"]["unpaidCents"] == 10000 and out["totals"]["unpaidCount"] == 1


def test_unpaid_sorts_before_paid():
    st = FakeStripe([sess("cs_1", "paid", link="plink_p"), sess("cs_2", "unpaid", link="plink_u")])
    ids = [r["id"] for r in run(st, fees.list_fees, None, q(ATOB2))["fees"]]
    assert ids == ["plink_u", "plink_p"], ids


def test_qa_sandbox_reads_with_the_test_key_only():
    st = FakeStripe([])
    out = run(st, fees.list_fees, None, q(QA))
    assert out["testMode"] is True and {c[3] for c in st.calls} == {"sk_test_x"}


def test_stripe_failure_is_an_error_not_zero():
    def boom(*a, **k):
        raise stripe_io.StripeError(502, "Stripe is temporarily unavailable", "upstream_unavailable")
    try:
        run(boom, fees.list_fees, None, q(ATOB))
    except fees.FeeError as e:
        assert e.status == 502 and e.payload()["ok"] is False
    else:
        raise AssertionError("a failed Stripe read must raise, never return an empty list")


def mk(**over):
    body = {"family": "Test Parent", "amount": 49, "purpose": "registration-fee",
            "contact_id": "ABCDEF1234567890", "location_id": ATOB}
    body.update(over)
    return body


def test_create_makes_one_tagged_link_and_a_draft_and_sends_nothing():
    st = FakeStripe()
    out = run(st, fees.create, None, mk())
    posts = [c for c in st.calls if c[0] == "POST"]
    assert len(posts) == 1 and posts[0][1] == "/payment_links" and posts[0][3] == "sk_live_x", st.calls
    p = posts[0][2]
    assert p["line_items"][0]["price_data"]["unit_amount"] == 4900
    assert p["line_items"][0]["price_data"]["product_data"]["name"] == "Registration fee - A Touch of Blessings"
    m = p["metadata"]
    assert m["purpose"] == "registration-fee" and m["ghl_contact_id"] == "ABCDEF1234567890"
    assert m["center_id"] == ATOB and m["location"] == "loc-921-n-18th" and m["amount_cents"] == "4900"
    assert out["draft"] == "Here is the link for the $49 registration fee: https://buy.stripe.com/test_NEW Thank you!"
    assert "stop" not in out["draft"].lower()                    # no "Reply STOP" line, ever
    assert out["testMode"] is False and "Nothing was sent" in out["note"]


def test_create_roundtrips_into_the_list():
    st = FakeStripe(links=[{"id": "plink_new1", "url": "https://buy.stripe.com/test_NEW", "metadata": {
        "purpose": "registration-fee", "family": "Test Parent", "center_id": ATOB, "amount_cents": "4900"}}])
    out = run(st, fees.list_fees, None, q(ATOB))
    assert out["fees"][0]["status"] == "unpaid" and out["fees"][0]["amountCents"] == 4900


def test_create_validation_blocks_bad_input_before_stripe():
    import daycare_supabase
    for bad in (mk(family=" "), mk(amount=0), mk(amount=999999), mk(amount="abc"), mk(purpose="gift-card"),
                mk(contact_id="x y"), mk(location_id="not-a-uuid")):
        st = FakeStripe()
        try:
            run(st, fees.create, None, bad)
        except (fees.FeeError, daycare_supabase.DaycareError) as e:
            assert e.status == 400, (bad, e.status)
            assert not [c for c in st.calls if c[0] == "POST"], (bad, st.calls)
        else:
            raise AssertionError(f"accepted bad input {bad}")


def test_double_tap_returns_the_same_link():
    st = FakeStripe()
    fees._CACHE.clear(); fees._RECENT.clear()
    with mock.patch.object(stripe_io, "_req", st), mock.patch.object(stripe_io, "key_for_location", keyfor):
        a = fees.create(None, mk())
        b = fees.create(None, mk())
    assert a["linkId"] == b["linkId"] and b.get("reused") and len([c for c in st.calls if c[0] == "POST"]) == 1


def test_qa_sandbox_create_uses_the_test_key_and_flags_test_mode():
    st = FakeStripe()
    out = run(st, fees.create, None, mk(location_id=QA))
    assert out["testMode"] is True and [c[3] for c in st.calls if c[0] == "POST"] == ["sk_test_x"]


def test_missing_key_fails_closed():
    def nokey(loc):
        raise stripe_io.StripeError(503, "The Stripe test key is not set for the QA Sandbox", "not_configured")
    st = FakeStripe()
    fees._RECENT.clear(); fees._CACHE.clear()
    with mock.patch.object(stripe_io, "_req", st), mock.patch.object(stripe_io, "key_for_location", nokey):
        for fn, arg in ((fees.create, mk(location_id=QA)), (fees.list_fees, q(QA))):
            try:
                fn(None, arg)
            except fees.FeeError as e:
                assert e.status == 503 and e.code == "not_configured"
            else:
                raise AssertionError("must refuse without a key")
    assert st.calls == []


def test_routes_are_wired_and_get_is_read_only():
    import connector
    src = open(connector.__file__).read()
    assert '"/api/daycare/billing/fees": lambda session: daycare_fees.list_fees(session, q)' in src
    assert 'elif path == "/api/daycare/billing/fee-link"' in src and '"/api/daycare/billing/fee-link",' in src


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("OK", name)
    print("all OK")
