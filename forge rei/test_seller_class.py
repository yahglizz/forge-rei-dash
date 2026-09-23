#!/usr/bin/env python3
"""Wave-2 item 8: Scout's 5-class seller label is a LABEL ONLY.

Asserts the classification for each message AND that the bucket / reason Scout's
rule scorer produces are exactly what they were before the label existed.
Run: FORGE_MARCUS=0 python3 test_seller_class.py   (exit 1 on any failure)
"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import marcus_engine as me   # noqa: E402
import scout_triage as st    # noqa: E402

# (message, expected class, expected wrongNumber, expected pre-existing bucket)
CASES = [
    ("stop", "DO_NOT_CONTACT", False, "dead"),
    ("STOP texting me", "DO_NOT_CONTACT", False, "dead"),
    ("remove my number and leave me alone", "DO_NOT_CONTACT", False, "dead"),
    # asked to stop wins over wrong number
    ("wrong number, please stop texting me", "DO_NOT_CONTACT", None, "dead"),
    ("not selling", "NOT_INTERESTED", False, "nurture"),
    ("No", "NOT_INTERESTED", False, "nurture"),
    ("wrong number", "NOT_INTERESTED", True, "dead"),
    ("not right now, maybe later", "NURTURE", False, "nurture"),
    ("yes I want to sell, I'd take 85k", "HOT", False, "asap"),
]


def score(body):
    """Replicates poll_once's rule path (cls fold-in + _rule_score) for a live reply."""
    cls = me.classify(body)
    if cls != "DNC" and (cls == "NRN" or me._is_soft_no(body) or me._is_hard_no(body)):
        cls = "NRN"
    return st.ScoutEngine._rule_score(None, cls, body, True, "Pat Seller")


fails = 0
for body, want_cls, want_wrong, want_bucket in CASES:
    base = score(body)
    rec = {"convId": "c1", "name": "Pat Seller", "lastMessage": body, **base}
    before = copy.deepcopy(rec)
    lab = st.seller_class(rec)
    slim = st.ScoutEngine._slim(None, rec)
    checks = [
        (lab["classification"] == want_cls, f"class {lab['classification']} != {want_cls}"),
        (want_wrong is None or lab["wrongNumber"] is want_wrong, f"wrongNumber {lab['wrongNumber']}"),
        (lab["optOut"] is (want_cls == "DO_NOT_CONTACT"), f"optOut {lab['optOut']}"),
        (base["bucket"] == want_bucket, f"bucket {base['bucket']} != {want_bucket} (scoring changed!)"),
        (rec == before, "seller_class mutated the record"),
        (slim["bucket"] == rec["bucket"] and slim["reason"] == rec["reason"], "slim changed bucket/reason"),
        (slim["classification"] == want_cls and lab["classReason"], "slim missing label/classReason"),
    ]
    for ok, msg in checks:
        if not ok:
            fails += 1
            print(f"FAIL {body!r}: {msg}")
    print(f"{'ok ' if all(c[0] for c in checks) else 'BAD'} {body!r:42} -> {lab['classification']:15}"
          f" bucket={base['bucket']:8} reason={base['reason']!r}")

# Backfill-on-read: an old record with no label fields still gets one.
old = {"convId": "old", "bucket": "warm", "reason": "engaged", "lastMessage": "tell me more"}
assert st.seller_class(old)["classification"] == "WARM", "old record not labeled"
# Operator manual override keeps its bucket's class (only opt-out outranks it).
man = {"bucket": "asap", "scoreSource": "manual", "lastMessage": "not interested"}
assert st.seller_class(man)["classification"] == "HOT", "manual override ignored"

if fails:
    print(f"\n{fails} failure(s)")
    sys.exit(1)
print("\nall seller-class checks passed")
