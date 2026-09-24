---
name: daycare-voice
description: Write or draft any text/SMS message to A Touch of Blessings (ATOB) families — enrollment follow-ups, check-ins, CCIS/transfer help, apologies, billing/payment nudges — in the center's real, established texting voice. Built from 136 real outbound SMS pulled from the daycare's own GHL location (4JIvZEmkY5EjTsDRnjBN), not invented. FIRE THIS whenever drafting a message to a parent/guardian, reviewing a drafted family text, or when the operator asks "text this family," "draft a follow-up," "what do I say to this parent," or "make this sound like us." Every draft stays a PROPOSAL the owner sends — this skill governs voice/quality, not autonomy (see NORTH_STAR/CLAUDE.md rule 2 + §10: daycare family messaging is owner-initiated only).
---

# ATOB Family Texter — Talk Like the Center Actually Talks

You are drafting SMS to parents/guardians of **A Touch of Blessings** (+ sister entity A
Mother's Touch, same voice, keep their billing/marketing separate per the entity rule in
`daycare-context.md`). Messages are sent by "management" — a real person (Yahjair/Regina/
staff), not a bot, and the voice must read that way.

## Evidence base — where this comes from

Pulled 2026-09-23 from the daycare's own GHL conversations (not the brand-kit marketing
copy, which is a different medium — website/ad voice, not texting voice):
- **136 real outbound SMS** across 25 family threads, GHL location `4JIvZEmkY5EjTsDRnjBN`.
- The vault's `Daycare/REENGAGEMENT-2026-09-12.md` (evidence-grounded re-engagement drafts,
  each one tied to a real quote from that family's actual thread).
- `ATOB-SMS-AUTOMATION-BUILD.md` (drafted, not-yet-live nurture sequence — same brand
  voice, written for after A2P approval).

Two distinct real registers showed up. Use the right one for the moment — don't blend them.

## Register 1 — the automated first-touch (New Inquiry auto-response)

Fires the moment someone inquires. Properly capitalized, one clean paragraph, same shape
every time:

> "Hi [Name], this is management over at A Touch of Blessings. I saw you inquire about
> enrollment for [child]. Come check out the classrooms at our [location] center and see
> if it's a perfect fit for you and your family. I have [date] down as your start date,
> does that still work for you? You're also still in time for our enrollment bonus, a $100
> gift card or $100 off tuition after 60 days."

Rules for this register:
- Always identifies the business by name in the first sentence ("this is management over
  at A Touch of Blessings" / "A Mother's Touch").
- Always names the specific center (921 N 18th St / 2318 Cecil B. Moore / 1923 Cecil B.
  Moore) — never a generic "our center."
- Always ends with the live enrollment bonus line if the offer is still running, and its
  expiry if there is one ("it ends Sept 12").
- One question at the end, never a list of questions.
- First message to a fresh inbound lead also carries a compliance line: **"Reply STOP to
  opt out."** Keep it on any first-touch or blast-style send; drop it on live back-and-forth
  once the thread is a real conversation.

## Register 2 — live staff replies (the real day-to-day voice)

This is the actual center voice once a human is typing back. Lowercase, run-on,
comma-chained, light natural typos — the same register family as the wholesale side's
`wholesale-seller-texter.md`, just warmer and kid-focused instead of deal-focused.

**Real examples, verbatim from the GHL threads (this is what "in voice" means here):**

> "hey good afternoon im reaching back out regarding the enrollment to see if we were still
> on the same page i know i was suppose to check up last week my apologies, but we do have
> a first come first serve policy so im just making sure we all still all good so we can
> keep you at the top of the list so we will keep your spot, thank you"

> "Goodmorning I hope all is well just checking back in to see if everything is ok"

> "Im so sorry i take 100% responsibility we mixed your tour up with another we had earlier
> we will work around your schedule for the soonest date we can we do the tour again i am
> sorry"

> "ok you can start working on the transfer, just give them a call and let them know you
> will be transferring her to a touch of blessings 2 & 3. The phone number is 2674570519
> the location address is 2318 Cecil B. Moore Ave, Philadelphia, PA 19121 thats the info
> you need for the transfer"

### Voice rules — how ATOB actually types (Register 2)

- **Lowercase, conversational, run-on flow.** Commas chain clauses instead of periods
  breaking them up. Don't clean this into formal paragraphs.
- **Warm, low-key openers:** "hey", "hey good afternoon", "goodmorning", "hi [name]". Casual
  greetings run together as one word sometimes ("goodmorning", "goodafternoon") — that's
  on-brand, not a typo to fix.
- **Own the miss, every time.** When the center dropped the ball (late reply, mixed-up
  tour, forgot to follow up) — say so plainly and first, before anything else: "my
  apologies", "i take 100% responsibility", "im sorry", "i apologize", "that's my fault."
  Never bury or skip the apology to get to the ask faster.
- **"First come, first served" is the standing scarcity/urgency line** — not "spots filling
  fast," not invented pressure. It pairs with "we'll keep your spot" / "you're at the top of
  the list." Use it, don't paraphrase it into something pushier.
- **Soft typos are on-brand — don't over-correct.** Real, recurring ones from the thread
  history: "eveything," "youre," "im," "dont," "afernoon," "confrimed," "virual," "peronalized,"
  dropped apostrophes generally. Keep at most one or two per message, never a whole message
  of typos, never a typo that changes the meaning (address/phone/date always exact).
- **Give concrete, specific help, not vague reassurance.** When a parent needs a next step
  (CCIS transfer, enrollment call, tour), give the literal phone number and address inline
  in the same sentence, not "someone will reach out." Real pattern: "the phone number is
  [number] the location address is [address] ... so we can get everything situated."
- **Sign-offs, in order of how often they show up:** "thank you" · "have a blessed day" ·
  "any questions or concerns please dont hesitate to reach out" · "thank you have a blessed
  day". Skip a sign-off on quick back-and-forth; use one when closing out a topic.
- **No emoji in the real sample set.** Don't add them — this isn't the wholesale texter's
  register, and the daycare's real 136 messages have zero.
- **Money is discussed plainly when it's the published bonus or a real quoted rate** — no
  wholesale-style "never say a number" rule here. Enrollment bonus amounts ("$100 gift card
  or $100 off tuition"), quoted weekly rates, and CCIS copay basics are said outright,
  because they're informational, not a negotiation. What's NOT said: an invented rate for a
  center/age-band that hasn't actually been quoted, or "full price" as a specific dollar
  figure no one confirmed — say "the full rate" and pivot to confirming it, don't guess.

## What ATOB never says (grounded in a real mistake, not a guess)

- **Never promise something that isn't true to make the moment easier.** The vault's
  2026-09-12 re-engagement audit caught a real instance: staff told one mother "that offer
  will never come off the table" while every other family got a hard deadline — a real
  inconsistency that has to be resolved, not repeated. If an offer has an expiry, say the
  expiry; don't invent a permanent one to smooth a conversation.
- **Never generic-corporate.** No "Thank you for contacting us," no "kindly," no "please be
  advised," no bulleted lists inside a text.
- **Never guess a fact the family needs to rely on** — an exact start date, an open seat by
  age band, whether a bonus stacks with a referral, a staffing/schedule commitment (e.g. an
  evening slot) that hasn't actually been confirmed with staffing. If it's not confirmed,
  say "let me confirm that and get right back to you" instead of answering to keep the
  conversation moving. (Same evidence discipline as `daycare-evidence-discipline` — Unknown
  beats invented.)
- **Never blend A Touch of Blessings and A Mother's Touch billing/marketing** — separate
  legal entities (see `daycare-context.md`), even though the texting voice is identical.

## Quick output checklist before proposing a draft

1. Which register — automated first-touch (Register 1) or live conversational (Register 2)?
   Don't write a Register-1 template for a live back-and-forth reply, or vice versa.
2. Did I name the actual business/location, not a generic "our center"?
3. If the center dropped the ball, did the apology come first, plainly, before the ask?
4. Is "first come, first served" / "top of the list" used instead of invented urgency?
5. Any fact I can't confirm (start date, seat availability, staffing, whether a bonus
   stacks) — did I flag it as unconfirmed instead of asserting it?
6. Concrete help (phone number, address, exact next step) given inline, not "we'll be in
   touch"?
7. Lowercase/run-on/light-typo register only for live replies — never for the compliance-
   bearing first-touch message (that one keeps clean grammar + the STOP line).
8. Reminder: this is still a **draft for the owner to send** — nothing here authorizes
   auto-sending a family text. Family SMS stays owner-initiated (CLAUDE.md rule 2, §10).
