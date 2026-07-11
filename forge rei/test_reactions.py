"""Regression: seller emoji/tapback REACTIONS to our texts must NOT be dropped as
our-own-outreach. A '👍 to "...our msg..."' is a warm buy-signal, not silence.

Root cause (2026-06-09): GHL delivers a reaction as an inbound message whose body quotes
our outreach (which contains "as-is"/"cash"/etc.), so _is_our_message() fired and Scout
skipped it. Real miss found live: Robert Ewing 👍'd our follow-up and never got scored.

Run: python3 test_reactions.py
"""
import marcus_engine as M
import scout_triage as S

# (body, expected _reaction_kind)
REACTIONS = [
    # Robert Ewing's real message (zero-width spaces + thin spaces, quotes our as-is/cash text)
    ('​\U0001f44d​ to “ Hey Robert, following up on my note about '
     '1938 W Sylvania Ave. Still buying as-is for cash, can close in 2 weeks ”', "pos"),
    ('\U0001f44d to "are you still looking to sell?"', "pos"),
    ('Liked "we buy houses cash"', "pos"),
    ('Loved "I was calling about your property"', "pos"),
    ('Emphasized "close fast, no realtor"', "pos"),
    ('\U0001f44e to "cash offer of 40k"', "neg"),
    ('Disliked "just following up"', "neg"),
    ('❓ to "we can close fast"', "q"),
    ('Questioned "saw your home on zillow"', "q"),
]
# Must NOT be flagged as reactions (normal replies / our own outreach / flat no/yes)
NON_REACTIONS = [
    "I want to sell, 45000 \U0001f44d",   # emoji but no quoted-our-text
    "we buy houses cash offer",            # our outreach, not a reaction
    "No thanks",
    "Yes I want to sell my house",
    "Can you do 60k?",
]


def main():
    fails = 0
    for body, exp in REACTIONS:
        got = M._reaction_kind(body)
        if got != exp:
            fails += 1
            print("FAIL kind", repr(got), "!=", repr(exp), "|", body[:50])
        # and the kept-buy-signal must score into a live (non-dead) bucket
        sc = S._reaction_score(got) if got else None
        if got == "pos" and (not sc or sc["bucket"] != "warm"):
            fails += 1
            print("FAIL score: pos reaction did not bucket warm:", sc)
    for body in NON_REACTIONS:
        if M._is_reaction(body):
            fails += 1
            print("FAIL false-positive reaction on:", repr(body))
    # The crux: a reaction quoting our text is our-message=True but reaction=True, so the
    # AND-guard in poll_once keeps it.
    robert = REACTIONS[0][0]
    assert M._is_our_message(robert) is True, "expected _is_our_message True for reaction body"
    assert M._is_reaction(robert) is True, "expected _is_reaction True for reaction body"
    skip_old = M._is_our_message(robert)
    skip_new = M._is_our_message(robert) and not M._is_reaction(robert)
    if not (skip_old and not skip_new):
        fails += 1
        print("FAIL guard: old should skip, new should keep")

    print(("ALL %d REACTION CASES PASS" % (len(REACTIONS) + len(NON_REACTIONS)))
          if not fails else ("%d FAILURES" % fails))
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
