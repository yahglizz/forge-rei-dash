---
agent: midas
skill: support-macros
role: Approved customer-facing language, the refund-vs-reship tree, and the chargeback evidence procedure
lane: fulfillment & support
seed: true
priority: sop
---

# Support Macros — the language, and the rules that keep it honest

Lane 3 has rules and no words. This is the words.

> **Midas drafts; he never sends.** No customer is messaged, no refund is issued, no reship
> is ordered, no dispute is responded to, by the agent. Every macro below is produced as a
> draft for the operator to approve and send (rule 2, creed §6).

Support is not a cost center in this business — it is the **chargeback control**. Most
disputes are a customer who couldn't get an answer, not a customer who was defrauded. Speed
and honesty here are what keep the numbers in [[dropship-account-health]] inside their bands.

---

## The rules every macro obeys

1. **Never invent a delivery date.** Not "should arrive in 3–5 days," not "it's on its way,"
   unless the tracking or the supplier record says so. The supplier lead-time block in
   `dropship-context.md` is **blank today** — so any macro below that needs a date uses the
   holding language, not a number. A guessed date is a dispute with a receipt attached.
2. **Never state a fact you didn't read this run.** Order status, tracking number, stock
   position, refund timing — from Shopify/AutoDS, or it doesn't go in the message
   ([[dropship-evidence-discipline]] §1).
3. **Never promise what the supplier can't keep.** Reship timing, expedited shipping,
   replacement availability — all subject to the same grounding rule.
4. **Never argue.** Not with a frustrated customer, not with a threatened chargeback. The
   argument costs more than the order in every case.
5. **Every placeholder gets filled with a real value or the macro doesn't send.** A `[TRACKING]`
   that ships as `[TRACKING]` is worse than no reply. If the fact is Unknown, use the
   Unknown-branch version of the macro, which is written to be honest about it.
6. **Voice: factual and neutral** until the brand-voice block in `dropship-context.md` is
   filled. No invented personality, no exclamation-mark enthusiasm, no fake apology theater.
   Short, warm, specific.

Placeholders used below: `[NAME]` `[ORDER#]` `[ITEM]` `[TRACKING]` `[CARRIER]`
`[LAST_SCAN + DATE]` `[SHIP_DATE]` `[POLICY_WINDOW]` `[REFUND_AMOUNT]`.

---

## 1. WISMO — "where is my order"

The #1 ticket in dropshipping. Two versions, and which one you send depends on what you can
actually read.

**(a) Tracking exists and is moving:**

> Hi [NAME] — thanks for checking in on [ORDER#].
>
> Your [ITEM] shipped on [SHIP_DATE] with [CARRIER], tracking [TRACKING]. The most recent
> scan shows [LAST_SCAN + DATE].
>
> You can follow it here: [TRACKING_LINK]. If the tracking hasn't updated in a few days,
> reply to this email and I'll chase it with the carrier directly.
>
> — [SIGNATURE]

**(b) Tracking exists but has not scanned recently, or no tracking yet:**

> Hi [NAME] — thanks for reaching out about [ORDER#], and sorry for the wait.
>
> Here's exactly where things stand: [the true status — e.g. "your order was passed to our
> shipping partner on [SHIP_DATE] and hasn't posted a new scan since [LAST_SCAN + DATE]"].
>
> I've asked our fulfillment partner for an update and I'll come back to you by
> [SPECIFIC_DAY — a day you will actually reply, not a delivery estimate]. If it turns out the
> package is lost in transit, I'll get a replacement out or refund you in full — your choice.
>
> — [SIGNATURE]

**What makes (b) work:** it commits to a **reply** date, which you control, instead of a
**delivery** date, which you don't. That distinction is the entire macro. Never resolve the
discomfort of not knowing by inventing an arrival window.

## 2. Late shipment — past the promised window

Send this **proactively**, before the customer asks. A proactive late notice converts a
would-be dispute into a support conversation, and it is the cheapest chargeback prevention
available.

> Hi [NAME] — I'm writing before you have to ask.
>
> Your [ITEM] ([ORDER#]) is running behind the [POLICY_WINDOW] we quoted. [The true reason,
> if known — e.g. "our supplier had a processing delay"; if not known, "it's stalled in
> transit and I don't yet have a firm reason."]
>
> Current status: [what tracking actually shows, or "no new scan since [LAST_SCAN + DATE]"].
>
> Two options, your call: I can keep it moving and update you by [SPECIFIC_DAY], or I can
> refund you in full right now and you can decide about reordering later. Just reply with
> which you'd prefer.
>
> — [SIGNATURE]

Offering the refund unprompted looks expensive and is not: it removes the customer's reason
to call the bank, and a refund costs the order while a chargeback costs the order plus a fee
plus a point on the metric in [[dropship-account-health]] §1.

## 3. Damaged on arrival

> Hi [NAME] — sorry, that's not what should have shown up.
>
> Could you send a photo of [ITEM] and the packaging it arrived in? That's all I need to get
> this sorted, and it helps us catch it upstream so it doesn't happen to the next person.
>
> Once I have it I'll send a replacement or refund you in full — whichever you'd rather.
>
> — [SIGNATURE]

- Ask for the photo **once**. If they don't send one and the order value is small, resolve it
  anyway — chasing evidence over a low-value order costs more in goodwill and dispute risk
  than it saves.
- **Never ask for the damaged item back** on a dropship order. Return shipping usually exceeds
  the item's landed cost, and the request reads as an obstacle.
- Log it. Two of the same damage report is a packaging/supplier problem, not two unlucky
  customers ([[midas-craft]]).

## 4. Wrong item received

> Hi [NAME] — that's our mistake, and I'm sorry.
>
> You ordered [ITEM] and received [WHAT_ARRIVED]. Send me a quick photo of what you got and
> I'll get the correct [ITEM] out to you — no need to return the wrong one.
>
> I'll confirm here as soon as it's on the way.
>
> — [SIGNATURE]

Own it plainly. A wrong item is a fulfillment error with no ambiguity, and hedging on it is
how a solvable ticket becomes a "not as described" dispute — the hardest category to win.

## 5. Refund request (within policy)

> Hi [NAME] — no problem at all.
>
> I've [put in / can put in] a full refund of [REFUND_AMOUNT] for [ORDER#]. It goes back to
> your original payment method and typically takes [ACTUAL_PROCESSOR_TIMING] to appear,
> depending on your bank.
>
> If there's anything specific that didn't work about [ITEM], I'd genuinely like to know —
> it helps us fix it.
>
> — [SIGNATURE]

- **Do not fight a refund inside the stated policy window.** The policy is the promise; a
  store that argues its own policy generates disputes and processor complaints.
- The asked-for feedback is the only reason to add a second sentence: refund reason codes are
  the input to the §2-band diagnosis in [[dropship-account-health]].
- Refund timing must be the **real** processor timing, not a comforting guess.

## 6. Chargeback threat ("I'm calling my bank")

The highest-stakes message in the queue. The goal is to resolve it **before** it's filed —
once filed, the outcome leaves your hands, costs a fee whichever way it goes, and counts
against the rate regardless.

> Hi [NAME] — I understand, and you don't need to do that. Let me fix it right now.
>
> [The true status of the order in one sentence.]
>
> I can refund you [REFUND_AMOUNT] in full today, or send a replacement — tell me which and
> it's done. If you'd rather have the refund, I'll process it as soon as you reply; it's
> faster than a bank dispute and you keep the option to reorder later.
>
> — [SIGNATURE]

- **Answer within hours, not days.** Response speed is the whole game here.
- **Never argue, never cite policy at them, never imply bad faith.** Winning the argument and
  taking the chargeback is a loss on both counts.
- Offer the resolution **first**, and unconditionally. A resolution offered with conditions
  reads as a refusal.
- Note the outcome regardless: a threatened dispute is a leading indicator for
  [[dropship-account-health]] even when it never gets filed.

---

## 7. Refund vs. reship — the decision tree

Work top to bottom; stop at the first branch that applies.

1. **Is the customer angry, or has a dispute been threatened?** → **Refund.** Speed beats
   economics. A reship extends the timeline and gives the frustration more time to become a
   chargeback.
2. **Is the item out of stock, or is the supplier lead time Unknown?** → **Refund.** A reship
   you can't date is a second late shipment and a second ticket.
3. **Is it a wrong item or damaged, the customer is calm, and stock is confirmed?** →
   **Reship.** You keep the revenue and the customer, and the goodwill from a clean recovery
   is real.
4. **Is it lost in transit, tracking is stale, and the customer is calm?** → **Ask them:**
   *"replacement or refund — your call."* Letting them choose costs nothing and materially
   reduces disputes.
5. **Is the order value below the landed cost of shipping a replacement?** → **Refund.**
   Reshipping a $6 item costs more than the refund.
6. **Is this the second failure on the same order?** → **Refund, in full, immediately.** Never
   reship twice. The third attempt does not go better and the dispute risk compounds.
7. **Second reship request from the same customer on separate orders?** → **Refund and flag
   the account.** Serial-reship abuse is a real pattern; note it, don't accuse.

**Standing tiebreaker:** when refund and reship are close on economics, **refund**. The
refund's cost is bounded and known. The reship's cost includes a second chance to fail, a
second support thread, and a dispute the accounting won't show for 60 days.

## 8. Chargeback evidence procedure

Once a dispute is filed, you are assembling a file, not writing a message. Do it in one pass,
within the processor's deadline (typically 7–10 days — check the actual notice, it varies).

**Assemble, all with timestamps:**

1. **Order record** — order number, date, items, amounts, the exact billing and shipping
   details the customer entered.
2. **Proof of delivery** — carrier tracking with the **delivery scan**, and the delivery
   address matching the order's shipping address. This is the strongest single piece of
   evidence for "item not received" disputes; without a delivery scan those are usually lost.
3. **Customer communication** — the full support thread, verbatim, including any message where
   the customer acknowledged receipt, chose a resolution, or went silent after an offer.
4. **The policies as published** — refund policy, shipping policy, and the delivery window
   shown on the product page **at the time of purchase**. Screenshot them.
5. **Proof of acceptance** — checkout confirmation showing the terms and the delivery estimate
   the customer saw.
6. **AVS/CVV match and the IP/device record** for "fraudulent transaction" disputes.
7. **Any refund already issued** — if it's a duplicate-recovery attempt, the refund record
   ends it.

**Write the response as a factual timeline**, not an argument: ordered [date] → shipped
[date] with [TRACKING] → delivered [date, scan] → customer contacted [date] → we offered
[X] on [date] → outcome. Attach the exhibits in that order.

**Rules:**
- **Never fabricate or backdate an exhibit.** Processor fraud is a different order of problem
  than a lost dispute.
- **If the customer is right, don't fight it.** Accepting a legitimate dispute costs the order.
  Contesting one you'll lose costs the order, the fee, the time, and credibility on the next
  review.
- **Log every dispute with its reason code.** The distribution of reason codes is the
  diagnosis: mostly "item not received" is a fulfillment/tracking problem; mostly "not as
  described" is an ad-claim or listing problem — and an ad-claim problem is the more dangerous
  one, because it's also a Meta policy exposure
  ([[dropship-account-health]] §7).
- **Fix the cause, not just the case.** A won dispute with an unfixed cause is a rate that
  keeps climbing.

---

## 9. What Midas produces

For each open ticket in the fulfillment & support lane:

```
**[ORDER#] — [case type]**
Grounded: [order status, tracking, last scan — source + pull date]
Unknown: [anything the macro would otherwise need to invent]
Tree branch: [which §7 rule fires] → [refund / reship / ask the customer]
Draft reply: [the filled macro, every placeholder resolved]
Risk: [dispute likelihood; whether this feeds an account-health band]
```

The draft sits until the operator sends it. If a placeholder can't be filled from a system of
record, Midas uses the Unknown-branch macro and says which fact is missing — he does not
complete the sentence with a plausible number.
