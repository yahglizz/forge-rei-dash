#!/usr/bin/env python3
"""Stage B2 regression suite: opt-out / dead-end classifier hardening.

Every case below is REAL Ohio thread text from the 5,527-contact audit
(marcus_state/leads_export/ohio_leads_audit.csv, 2026-08-21). Contact ids are
quoted so a future change can be argued against the evidence, not a hunch.

Run: python3 test_optout_hardening.py     (exit 1 on any failure)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import seller_classify as SC          # noqa: E402  live send-gate classifier
import leads_audit as LA              # noqa: E402  offline blast scrubber
import full_leads_audit as FLA        # noqa: E402  Stage A wrapper (gate + soft_no split)

FAILURES = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)


def eq(got, want, label):
    if got != want:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")


# ---------------------------------------------------------------------------
# 1. STOPALL family — the non-regression that matters most. 77 of the 270 real
#    Ohio opt-outs used it, and \bstop\b matches NONE of them.
# ---------------------------------------------------------------------------
STOPALL_FAMILY = [
    "STOPALL", "Stopall", "STOPALLCONTACT", "STOPALL contact", "Stopall contact",
    "STOPALL CONTACT", "STOPALL..NOT  DESMOND", "Stop all", "Stop all contact",
    "Stop all Contact !!!", "stopall..not  desmond", "Stopp", "Omg stopppppp",
    "STOPP", "stopallcontact",
]
for t in STOPALL_FAMILY:
    eq(SC.classify(t), "DNC", f"seller_classify STOPALL family {t!r}")
    check(LA._is_dnc(t), f"leads_audit._is_dnc STOPALL family {t!r}")

# plain STOP and its typos (tlN4DNv0miscFy0UgQsb, P9dzgMnZnkMj0ZksAy5h)
for t in ["STOP", "Stop.", "stop", "Stop texting me", "Stop texting this number",
          "STPP TEXTING ME", "Quiting texting me", "Pls stop txtn me. Thank you",
          "Stop messaging me . U got the number.", "unsubscribe", "Please remove me"]:
    eq(SC.classify(t), "DNC", f"seller_classify stop form {t!r}")
    check(LA._is_dnc(t), f"leads_audit._is_dnc stop form {t!r}")

# ---------------------------------------------------------------------------
# 2. "stop" must NOT fire on visiting, or inside a word.
#    IaAAnlDHbkawfRXmMn0J was killed as dnc by the naive substring.
# ---------------------------------------------------------------------------
NOT_STOP = [
    "All business discussions are handled in person. Feel free to stop by",
    "stop by the office",
    "We can stop in at the office next week",
    "Hi Christopher, this is Yahjair with A Touch of Blessings Home Buyers.",
    "I stopped renting it out last year",
    "There is a bus stop on the corner",
]
for t in NOT_STOP:
    check(SC.classify(t) != "DNC", f"seller_classify false DNC on {t!r}")
    check(not LA._is_dnc(t), f"leads_audit false dnc on {t!r}")

# ---------------------------------------------------------------------------
# 3. The extended opt-out set (all real, all previously in KEEP buckets).
# ---------------------------------------------------------------------------
NEW_OPT_OUTS = [
    "FUCK OFF",                                        # daGIgIrL6D95JDb4vFVL
    "Fuck you",                                        # tV1J5PzbQep9JEmZ13J3
    "Go fuck your self",                               # LRdUAp1ju7VWyRzPhn5C
    "Fuck you!! Leave me the fuck alone!",             # Q7BA5gix5Hn05ARKUDNi
    "Leave me alone",
    "Stfu I'm not Richard so stop texting me you cunty bitch",   # GlQ6N66vGoxVDxDM6yFN
    "No and please don't text me",                     # QlqPnCesBROotqwWTd4B
    "Please don't text or call me anymore respect my wishes",    # e58D2VcFStHAmc9AUXFx
    "Don't bother me you have the wrong number",       # ke4zpb2PYeVbijAtAmMS
    "I'm suing you for harassment",                    # uIIO2uYLQmIVrfrR8Ig9
    "Scam I'm reporting you",                          # Cy6xTeigRwBHfjtrs78j
    "Hello I have already been put on a do not contact list",    # jAdApc7RJC3oIv4z9VvQ
    "Lose my number",                                  # fNieYfNqg5gqrASAw4g2
    "Good Morning not John, please loose my number ty",# O85GxcRXJ2oszsjNmwMW
    "Number blocked",                                  # 8mCSEo25pp0SUb60PKi3
    "Absolutely NOT  Please take me off your list",
    "\U0001F44E",                                      # bare thumbs-down
    "No \U0001F44E",                                   # Wi0bfQ85Arl6vMCJD7nI
    "\U0001F6D1",                                      # TgVTyWW8y1jppMNWfSNz
    "\U0001F92C",                                      # Is62uAj55dJ5UPcUguzy
    "\U0001F449\U0001F449\U0001F44E\U0001F44E\U0001F44E",       # 8iw35sx9t3KnxKhQsuwl
]
for t in NEW_OPT_OUTS:
    eq(SC.classify(t), "DNC", f"seller_classify new opt-out {t!r}")
    check(LA._dead_end_reason(t) in ("dnc", "opt_out"),
          f"leads_audit dead-end reason for {t!r} -> {LA._dead_end_reason(t)!r}")

# ...and what must survive it. A motivated seller swears about the HOUSE, and a
# probate seller has an attorney; neither is an opt-out.
NOT_OPT_OUT = [
    "this place is fucked up, tenants trashed it",
    "The roof is shot \U0001F44E but I might sell",
    "My attorney handles the estate, call him",
    "I quite like the idea",
    "How much are you offering",
    "yes im interested",
    "There is a stop sign out front",
]
for t in NOT_OPT_OUT:
    check(SC.classify(t) != "DNC", f"seller_classify false DNC {t!r}")
    check(LA._dead_end_reason(t) not in ("dnc", "opt_out"),
          f"leads_audit false compliance dead-end {t!r}")

# Our own outreach footer says "reply STOPALL contact". A tapback quoting it back
# at us is a POSITIVE signal, not the seller opting out.
TAPBACK = ("​\U0001F44D​ to “ Hey Ronald, following up on my note about 645 "
           "Ashwood Ave. Still buying as-is for cash, can close in 2 weeks or on your "
           "timeline.\nIf you'd rather not receive messages reply STOPALL contact, have a "
           "blessed day\nThanks, yahjair ”")
check(SC.classify(TAPBACK) != "DNC", "positive tapback quoting our STOPALL footer -> DNC")
# but a real STOP outside the quote still counts
eq(SC.classify('Stop. “we buy houses” I dont want your texts anymore'), "DNC",
   "stop outside a quoted span")
# ...and a thumbs-up on a CARRIER opt-out confirmation is not a resurrected lead
# (45GAWv1ODCSmlXh4VxJo). The confirmation is matched before the quote is stripped.
CARRIER_CONFIRM = ("\u200b\U0001F44D\u200b to \u201cYou have successfully been unsubscribed. "
                   "You will not receive any more messages\u201d")
eq(SC.classify(CARRIER_CONFIRM), "DNC", "tapback on a carrier unsubscribe confirmation")
check(LA._dead_end_reason(CARRIER_CONFIRM) in ("dnc", "opt_out"),
      "leads_audit must keep a carrier unsubscribe confirmation excluded")

# ---------------------------------------------------------------------------
# 4. Thread-wide compliance scan. An opt-out ANYWHERE is permanent.
#    Is62uAj55dJ5UPcUguzy: "Please stop damn texting me" ... last line "\U0001F92C".
# ---------------------------------------------------------------------------
def _thread(*pairs):
    return [{"direction": d, "body": b, "dateAdded": "2026-08-01T00:00:00Z"}
            for d, b in pairs]


t = _thread(("outbound", "Hi, this is Yahjair with A Touch of Blessings Home Buyers."),
            ("inbound", "Please stop damn texting me"),
            ("outbound", "Understood, sorry about that."),
            ("inbound", "sure whatever"))
eq(LA.classify(t)[0], "dead_end", "earlier opt-out must win over a benign last line")
eq(LA.classify(t)[7], "dnc", "earlier opt-out reason")

# a seller CAN change their mind about selling: an early "not interested" followed
# by a real reply must stay live.
t2 = _thread(("outbound", "Hi, this is Yahjair with A Touch of Blessings Home Buyers."),
             ("inbound", "not interested"),
             ("outbound", "No problem, I'll check back."),
             ("inbound", "actually what were you thinking for it"))
eq(LA.classify(t2)[0], "active_pending_us", "non-compliance dead end keys off the LAST reply")

# ---------------------------------------------------------------------------
# 5. De-anchored wrong_number / sold / hard_no (search-anywhere).
# ---------------------------------------------------------------------------
WRONG_NUMBER = [
    "Look man you got the wrong number. Good luck.",   # l0zYbfsVRwQVdXeV7y8O
    "WRING NUMBER",                                    # pLM0ClCdIF39kfLxIYQB
    "Wrong person man",                                # QyDUi7ITaXUmwFWT85W9
    "You have the wrong number. Noone here owns 161 Rita St",
    "By the way that is not my name",                  # DWaVWadh7AkYLhQWmWCn
    "You texting the wrong person/ number",            # DSpDI6TgEdhQV1577Lix
    "You've got the wrong number my friend!! Hope you find Jennifer :)",
]
for txt in WRONG_NUMBER:
    check(LA._is_denial(txt), f"_is_denial missed {txt!r}")

# task 6: "who is this"/"who are you" is the most normal reply to a cold text.
# D3ugTFgL48MGaf4M1icx had SIX inbound messages and was killed by it.
for txt in ["Who is this?", "who are you", "Who dis", "Who is this"]:
    check(not LA._is_denial(txt), f"_is_denial must not kill {txt!r}")
    check(SC.classify(txt) != "DNC", f"seller_classify must not call {txt!r} DNC")
for txt in ["Who is this?", "who are you"]:
    eq(SC.classify(txt), "HELP", f"seller_classify calls {txt!r} HELP (production behavior)")

SOLD = [
    "No it's been sold",                               # QYblreF89KDK216tsPHH
    "It's sold please forget about it",                # tUGT0mly876czROQGtlz
    "Sold them all sorry",                             # 0xQiyTWvUZ4maB4DsP3T
    "Carbon has been sold",                            # WJ1IrTHRH2ISkb0Fmqfv
    "sold",
    "the house is sold",
]
for txt in SOLD:
    check(LA._is_sold(txt), f"_is_sold missed {txt!r}")

# _is_sold had ZERO false positives across 5,527 rows. Do not regress that.
NOT_SOLD = [
    "sold my other house",
    "I sold my other house last year",
    "not sold yet",
    "it has not been sold",
    "thinking of getting it sold",
    "I want to get it sold this year",
    "if it gets sold I'll let you know",
    "trying to get it sold",
    "It is not for sale",
    "would you buy it before it is sold",
]
for txt in NOT_SOLD:
    check(not LA._is_sold(txt), f"_is_sold FALSE POSITIVE on {txt!r}")

for txt in ["Nfs", "No sale.", "Not intrested", "not interested", "No", "nope",
            "Its NFS", "not for sale, sorry"]:
    check(LA._dead_end_reason(txt) in ("hard_no", "soft_no"),
          f"refusal {txt!r} -> {LA._dead_end_reason(txt)!r}")
for txt in ["no rush", "no problem", "I have no idea", "no worries what do you offer"]:
    check(LA._dead_end_reason(txt) != "hard_no", f"hard_no FALSE POSITIVE on {txt!r}")

# ---------------------------------------------------------------------------
# 6. soft_no split + widened timing (Stage A's SOFT_NO_REFUSAL_IS_KEEP stays False).
# ---------------------------------------------------------------------------
check(FLA.SOFT_NO_REFUSAL_IS_KEEP is False, "SOFT_NO_REFUSAL_IS_KEEP must stay False")
for txt in ["not for sale", "NOT FOR SALE!!!", "Not for sale no matter what the offer would be",
            "I still own it but I'm not interested in selling thank you", "Yes but not selling"]:
    eq(FLA.soft_no_kind(txt), "refusal", f"soft_no_kind {txt!r}")
for txt in ["No not at this time", "not right now", "maybe later",
            "give me 2 weeks", "call me in a few months", "check back in the spring",
            "try me in a couple months", "ask me again next year"]:
    eq(FLA.soft_no_kind(txt), "timing", f"soft_no_kind {txt!r}")
eq(FLA.soft_no_kind("not selling right now"), "refusal", "ambiguous -> refusal")

for txt in ["give me 2 weeks", "call me back in a few months", "check back in the spring",
            "hit me up next spring", "ask me again later"]:
    check(LA._is_timing(txt), f"_is_timing missed {txt!r}")
# the timing re-label can only move a row BETWEEN keep segments, never out of them
check("soft_no_revisit" in FLA.KEEP_SEGMENTS,
      "soft_no_revisit must be a KEEP segment or the timing re-label deletes leads")

# ---------------------------------------------------------------------------
# 7. merge_rank: every dead-end reason is unbeatable EXCEPT the handset-scoped one.
# ---------------------------------------------------------------------------
def _row(status, reason="", dnd_class=""):
    return {"status_category": status, "dead_end_reason": reason,
            "dnd_class": dnd_class}


for reason in ("dnc", "opt_out", "hard_no", "sold", "soft_no_refusal"):
    check(FLA.merge_rank(_row("dead_end", reason)) > FLA.merge_rank(_row("active_pending_us")),
          f"dead_end/{reason} must beat a live duplicate")
check(FLA.merge_rank(_row("dead_end", "wrong_number")) < FLA.merge_rank(_row("never_replied")),
      "wrong_number is handset-scoped and must lose to a live sibling")
check(FLA.merge_rank(_row("excluded", dnd_class="opt_out")) > FLA.merge_rank(_row("active_pending_us")),
      "GHL opt_out must beat everything")
check(FLA.merge_rank(_row("excluded", dnd_class="undeliverable")) < FLA.merge_rank(_row("never_replied")),
      "undeliverable handset must lose to a live sibling")

# ---------------------------------------------------------------------------
# 8. _is_our_message must stop eating short seller replies, without un-filtering
#    the 130 real "Still buying as-is for cash" follow-ups it protects us from.
# ---------------------------------------------------------------------------
import marcus_engine as ME            # noqa: E402  (loads config; imported last)

OUR_PITCHES = [
    "Hey Clive, following up on my note about 419 E 6th St. Still buying as-is for cash, "
    "can close in 2 weeks or on your timeline. Open to a conversation ? if not its 100% ok",
    "Hi Jose, this is elizabeth with A Touch of Blessings Home Buyers. I'm reaching out "
    "about your property at 12 Main St do you still own it?",
    "Elizabeth with a touch of blessings home buyers",
    "Ok great we was wondering would you consider a cash offer on the property, we are "
    "actively buying in the area",
]
for txt in OUR_PITCHES:
    for mod in (ME, LA):
        check(mod._is_our_message(txt),
              f"{mod.__name__}: our own pitch leaked through as a seller reply: {txt[:60]!r}")

SELLER_ECHOES = [
    "Touch of Blessings?",              # MY1qNVo5dCGgbJASuyWV — engaged question
    "as-is?",
    "cash offer?",
    "whats a cash offer",
]
for txt in SELLER_ECHOES:
    for mod in (ME, LA):
        check(not mod._is_our_message(txt),
              f"{mod.__name__}: ate a real seller reply: {txt!r}")

# ---------------------------------------------------------------------------
# 9. The GHL compliance gate (plan section 4) is wired and still fires.
# ---------------------------------------------------------------------------
eq(FLA.compliance_check({"dndSettings": {"SMS": {"status": "permanent",
                                                 "message": "STOP_KEYWORD"}}})[3:],
   ("ghl_dnd", "opt_out"), "STOP_KEYWORD -> opt_out")
eq(FLA.compliance_check({"dndSettings": {"SMS": {"status": "active",
                                                 "message": "TWILIO_ERROR_CODE: 30005"}}})[3:],
   ("ghl_dnd", "undeliverable"), "Twilio 30005 -> undeliverable")
eq(FLA.compliance_check({"tags": ["wholesale lead", "DNC"]})[3:],
   ("ghl_dnd", "opt_out"), "DNC tag -> opt_out")
eq(FLA.compliance_check({"dnd": True})[3:], ("ghl_dnd", "opt_out"), "dnd flag -> opt_out")
eq(FLA.compliance_check({"dndSettings": {"SMS": {"status": "inactive", "message": ""}},
                         "tags": ["sms blasted", "ohio 1 st number"]}),
   (False, "", "", "", ""), "clean contact must not be excluded")

# ---------------------------------------------------------------------------
if FAILURES:
    print(f"\n{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("test_optout_hardening: ALL PASS")
