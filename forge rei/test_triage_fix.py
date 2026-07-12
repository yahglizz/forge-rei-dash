"""Regression test for the hot-lead false-positive bug:
- a flat 'No' / 'No!!!' must NOT score as a warm/hot lead (RC1)
- our own business autotext must be recognized as ours, not a seller (RC2)
Run: python3 test_triage_fix.py
"""
import marcus_engine as me

# RC1 — whole-message hard-no detection
HARD = ["No", "No!!!", "nope", "Nah", "Not interested", "no thanks", "NO.", "  no  "]
for s in HARD:
    assert me._is_hard_no(s), f"FAIL: should be hard-no: {s!r}"

# ...but NOT a 'no' embedded in an otherwise-warm reply
NOT_HARD = ["No pictures but I want 20k", "Yes sure", "123 Main St, I want 20k",
            "no rush but yes call me", "I don't know the price yet"]
for s in NOT_HARD:
    assert not me._is_hard_no(s), f"FAIL: should NOT be hard-no: {s!r}"

# RC2 — our own autotext is recognized as ours
assert me._is_our_message(
    "Hi this is a touch of blessing 2 & 3, I saw that we just missed your call how can"
), "FAIL: our autotext should be flagged as our message"
# ...but a real seller mentioning a missed call must NOT be filtered out
assert not me._is_our_message("Sorry I missed your call, can you call me back"), \
    "FAIL: seller reply wrongly flagged as our message"

OUTREACH = [
    "Hi Darryl, I wanted to see if you would consider selling your house",
    "Hey Darryl this is Yahjair, I tried calling you about the home",
    "Would you be open to selling the property for cash?",
    "We are looking to purchase your home",
]
for s in OUTREACH:
    assert me._is_our_message(s), f"FAIL: missed our outreach: {s!r}"

SELLER_REPLIES = [
    "yes i am open to selling",
    "i am interested in an offer if the price is right",
    "the property at 123 main is mine",
]
for s in SELLER_REPLIES:
    assert not me._is_our_message(s), f"FAIL: seller reply wrongly flagged: {s!r}"

print("ALL PASS")
