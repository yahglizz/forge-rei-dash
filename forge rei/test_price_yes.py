"""Regression test: a stated asking price OR a clear 'yes' must bucket asap (hot),
deterministically — even when Claude is unavailable. A flat 'no' must stay cold.
Mirrors poll_once's stage-1 flow (classify -> hard/soft-no override -> _rule_score).
Run: FORGE_MARCUS=0 python3 test_price_yes.py
"""
import marcus_engine
import scout_triage

S = scout_triage.ScoutEngine(ghl_get=lambda *a, **k: {},
                             ghl_post=lambda *a, **k: {}, location_id="test")


def bucket_for(body, needs_reply=True):
    cls = marcus_engine.classify(body)
    if cls != "DNC" and (cls == "NRN" or marcus_engine._is_soft_no(body)
                         or marcus_engine._is_hard_no(body)):
        cls = "NRN"
    return S._rule_score(cls, body, needs_reply)["bucket"]


# (message, expected bucket) — "NOT-asap" means anything except asap.
CASES = [
    ("40,000 firm", "asap"),
    ("Yes it's for sell as is", "asap"),
    ("Yes I want to sell my house, need to sell fast", "asap"),
    ("123 Main Street and I don't have pictures I want 20k for it", "asap"),
    ("With all respect my price is $ 16,000 thousand as is", "asap"),
    ("35000", "asap"),
    ("i would take 8500 for it", "asap"),
    ("sure", "asap"),
    ("yep", "asap"),
    ("No", "nurture"),
    ("no thanks", "nurture"),
    ("not interested", "nurture"),
    ("stop", "dead"),
    ("123 Main Street", "NOT-asap"),   # bare address -> must NOT be hot
]


def main():
    ok = True
    for body, want in CASES:
        got = bucket_for(body)
        passed = (got != "asap") if want == "NOT-asap" else (got == want)
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] want={want:9} got={got:8} :: {body[:45]}")
    print("ALL PASS" if ok else "SOME FAILED")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
