---
agent: midas
skill: ad-launch-sop
role: The numeric test / kill / scale rules for Meta — what "scale deliberately, in steps" actually means
lane: creative & ads
seed: true
priority: sop
---

# Ad Launch SOP — the numbers behind test, kill, and scale

> **Every threshold in this file describes a RECOMMENDATION, never an action.** Midas does
> not launch an ad, duplicate an ad set, change a budget, or turn anything off. He evaluates
> against these rules and hands the operator a specific, numeric proposal; the operator taps
> to execute. Root `CLAUDE.md` rule 2, creed [[dropship-evidence-discipline]] §6. This SOP
> exists so the proposal says *"raise this ad set from $50 to $65, hold 72h"* instead of
> *"scale deliberately."*

[[dropship-meta-ads-diagnostician]] tells you **which slider is broken**. This tells you
**what to do about it, in numbers, and how long to wait before believing anything.**
[[midas-craft]] holds the judgment underneath both.

---

## 0. The one input everything hangs on: break-even CPA

Almost nothing below is a flat dollar figure, because a flat dollar figure is wrong for
every store but one. The anchor is **break-even CPA** — the acquisition cost at which an
order contributes exactly zero:

```
break-even CPA = AOV − landed COGS − shipping − payment/platform fees − expected refund cost
```

All four inputs come from Shopify + AutoDS, not from memory. **Today they are Unknown** —
the context brief's target-margin block (`dropship-context.md` → OWNER: FILL THIS IN #2) is
blank and no integration is keyed. Until it's filled:

- State break-even CPA as **Unknown** and say what it blocks.
- Do **not** substitute a benchmark, an industry average, or a competitor's price. That is
  inventing the single number every other number in this file is measured against.
- The highest-value ads recommendation while it's Unknown is: *fill this in, it unblocks
  every kill and scale decision below.*

A **target CPA** for scaling is a policy choice on top of it — commonly 0.6–0.7 × break-even
CPA, so a scaled winner still contributes 30–40% margin per order. Set it once, in the
context brief, and hold to it.

---

## 1. Structure: ABO to test, CBO to scale

**Test in ABO** (Ad Set Budget Optimization — budget set per ad set).
Testing is buying information about *angles*, and CBO will not buy information — it will
concentrate spend on whichever ad set gets lucky in the first hours and starve the rest. ABO
forces every angle to get its data.

- One ad set = one **angle** (one Avatar × Problem entry point per
  [[dropship-four-triggers-ad-writer]]), not one audience tweak.
- 3–5 ad sets per test round. Fewer than 3 and you learn nothing about the angle space; more
  than 5 and you're splitting budget below the read threshold in §2.
- 3 creatives per ad set, same angle, different hook/format. Let Meta pick the execution;
  you're testing the angle.
- Broad targeting by default. The creative is the targeting (see [[midas-craft]]); interest
  stacking mostly buys you a smaller audience and faster fatigue.

**Scale in CBO** (Campaign Budget Optimization).
Once an angle is proven, CBO's job is allocation across *known* winners, which is what it is
actually good at.

- Move only **proven** ad sets into the CBO — an ad set that has cleared the §3 keep bar.
- 2–4 ad sets per CBO. A CBO with one ad set is just an ABO with extra steps and worse
  reporting.
- Never mix an unproven angle into a scaling CBO to "give it a chance." It will either be
  starved (learned nothing) or fed at the winner's expense (cost you money). Test in ABO.

## 2. Test budget and the minimum spend before any decision

**Test budget per ad set per day: 1× break-even CPA, floor $20/day.**

The logic, not a vibe: an ad set needs to be able to produce at least one conversion event
per day for the day to mean anything. Below 1× break-even CPA/day you are buying a sample
too small to distinguish a loser from variance, and you will kill winners.

- Break-even CPA $25 → $25/day per ad set. Five ad sets = $125/day test round.
- Break-even CPA $12 → the $20/day floor applies; below ~$20/day Meta's delivery gets erratic
  regardless of the math.
- Break-even CPA $80 (higher-ticket) → $80/day per ad set, and expect to run fewer angles per
  round. Do not "save money" by testing a $80-CPA product at $20/day; you'll spend three
  weeks buying noise.

**The minimum-spend rule — the one that stops most bad kills:**

> **Never make a kill decision on an ad set that has spent less than 1× break-even CPA.**
> A hard kill requires **2× break-even CPA with zero purchases.**

At 1× break-even CPA with zero purchases, a losing ad set and an unlucky good one look
identical. At 2× with zero purchases, the probability that it's merely unlucky has collapsed
— kill it. This replaces every "give it $50 and see" heuristic, which is right for exactly
one store's economics and wrong for all the others.

**Never decide on less than 24 hours, and never on a 6-hour read.** Intraday performance
swings by hour of day and audience-pool refresh; a 6-hour panel is noise dressed as a signal
(creed §1).

## 3. Day-N decision gates

Run every test ad set through these gates in order. Each gate has a spend precondition — if
the ad set hasn't spent that much yet, the gate does not apply yet, regardless of what day
it is.

| Gate | Precondition | Kill if | Keep / promote if |
|------|--------------|---------|-------------------|
| **Day 1** | — | **Nothing.** No decisions in the first 24h. The ad set is in learning and the data is unrepresentative. The only Day-1 action is verifying delivery started and the pixel is firing ([[dropship-store-setup]]). | — |
| **Day 2** | spend ≥ 1× break-even CPA | CTR < 1% **and** CPC > 2× the §5 benchmark **and** zero add-to-carts. That triple is a creative failure, not variance — the ad isn't earning attention at any price. | Any purchases, or ATC rate > 5% — let it run to Day 3. |
| **Day 3** | spend ≥ 2× break-even CPA | Zero purchases. Hard kill. | CPA ≤ 1.5× break-even → keep running to Day 5. |
| **Day 5** | spend ≥ 3× break-even CPA | CPA > 1.5× break-even with no downward trend across days 3→5. | CPA ≤ break-even → **promote to the scaling CBO.** |
| **Day 7** | spend ≥ 5× break-even CPA | CPA still > break-even. Seven days and five break-evens of spend is a decided question. | CPA ≤ target CPA (0.6–0.7× break-even) → **scale per §4.** |

Two standing exceptions:

- **Zero-spend / zero-delivery is not a kill, it's a bug.** An ad set that won't spend has an
  audience-size, bid, schedule, or review problem. Diagnose before killing.
- **Anything in [[dropship-account-health]] outranks this table.** A policy flag, a dispute
  spike, or a stockout on the product being advertised stops the campaign now, whatever day
  it is.

## 4. Scaling: increment, cool-down, and when to duplicate instead

**Increment: +20–30% of current daily budget. Never more than +30% in one edit.**
**Cool-down: 48–72 hours between increases on the same ad set. No exceptions for a good day.**

Why those numbers: a budget edit re-enters the ad set into learning, and the size of the edit
determines how disruptive that is. Under ~30%, delivery usually re-stabilizes without a full
learning reset. Over it, Meta re-explores the audience and you pay for the same lesson twice.
The 48–72h cool-down exists because you cannot evaluate the *previous* increase in less time
than that — raising again before you've read the last raise means you never know which change
did what.

- Raise on **one axis at a time**. Budget or creative or audience — never two in the same
  edit, or the result is uninterpretable.
- **Watch CPA across the increase, not just after it.** If CPA rises above break-even at the
  new budget and stays there for 72h, step back to the last working budget. That step-back is
  a proposal too.
- **When you need a big jump (2×+), duplicate into a new CBO at the target budget** rather
  than editing the working ad set upward. You keep the proven ad set intact at its known-good
  budget and the new one either works or gets killed by §3's gates. Never risk a working
  winner to test a bigger number.
- **Horizontal before vertical, once vertical stalls.** When an ad set stops absorbing budget
  profitably, the next spend goes into a *new angle* or a *new geo*, not into forcing more
  through a saturated one. "Everything in spec except CAC" in
  [[dropship-meta-ads-diagnostician]] is exactly this signal.

## 5. Learning phase and the 50-conversion rule

**Meta needs ~50 conversion events per ad set per week to exit the learning phase.** Below
that the ad set stays in "Learning Limited," optimization is degraded, and performance reads
are unreliable — you are making decisions on a model that hasn't converged.

The operational consequence most operators miss: **that is a budget floor, not a target.**

```
minimum viable ad-set daily budget ≈ (50 × break-even CPA) / 7
```

Break-even CPA $25 → ~$180/day per ad set to plausibly exit learning. If the store can't fund
that per ad set, the fix is **consolidation, not patience**: run 2 ad sets at $90 rather than
6 at $30. Six starved ad sets all sitting in Learning Limited produce six unreliable reads and
one large bill.

- Testing rounds (§2) run *inside* learning deliberately — you're buying angle information,
  not optimization. Don't expect exit-of-learning performance from a test.
- **Scaling ad sets should exit learning.** If a scaling ad set is still Learning Limited
  after a week, the budget is too low or the conversion event is too far down the funnel
  (optimizing for Purchase on low volume — consider optimizing for a higher-frequency event
  only if the funnel math supports it, and say so).
- **Every significant edit re-enters learning.** That is the real cost of a panic swing, and
  it is why §4's increments are capped.

## 6. Creative rotation cadence

Creative fatigue is the most predictable failure in paid social; it should never surprise you.

**Refresh triggers — any one of these fires it:**
- **Frequency > 1.5** on a cold audience (slider 6 in [[dropship-meta-ads-diagnostician]]).
- **CTR down > 25% week-over-week** on the same ad set.
- **CPM rising while CTR falls** — the compound fatigue signature.
- **Hold rate falling with hook rate steady** — the body of the ad has aged, not the hook.

**Cadence on a scaling winner: a fresh creative batch every 7–14 days.** Not because the
current one is dead — because producing creative *after* it dies costs you the ad set's
momentum and its accumulated learning, which you cannot buy back next week at the same price.
Fresh creative is cheap now and impossible later.

- **Refresh ≠ new angle.** If the angle still converts, keep the offer and the mechanism and
  rewrite the hook and first three seconds. That is a refresh, and it goes into the *existing*
  proven ad set.
- **A dead angle needs a new ad set**, tested per §2–3 from scratch. Don't bury an untested
  angle inside a scaling ad set.
- Rotate creatives **into** the winning ad set rather than launching a parallel one — you keep
  the ad set's optimization history. New ad set only when the audience or angle changes.

## 7. What "significant" actually requires

Before any conclusion — a kill, a scale, a "this angle works," a "the creative is fatigued" —
check all three. If any one fails, the honest answer is *not yet enough data*, which the creed
treats as a legitimate output (§1, §4).

1. **≥ 50 conversion events** for a claim about conversion performance (CPA, CVR, ROAS), or
   **≥ 100 clicks** for a claim about click-side performance (CTR, CPC, hook rate).
2. **≥ 3 full days**, and always full days — never a partial day, never 6 hours, never a
   weekend compared to a weekday.
3. **≥ 1× break-even CPA of spend** for a kill; **≥ 5× break-even CPA** for a scale decision,
   because scaling wrong is expensive and hard to walk back (creed §4: weight care by cost of
   being wrong).

Two further honesty checks that cost nothing:

- **Compare like to like.** Week-over-week, not "this week vs. Black Friday." Seasonality is
  real and reading it as failure is a classic, expensive mistake ([[midas-craft]]).
- **Reconcile the platform against the store.** Meta-reported purchases must be checked
  against Shopify orders before any number here is trusted — see the pixel/CAPI section of
  [[dropship-store-setup]]. A scale decision on inflated, double-counted ROAS is a scale
  decision into a loss.

## 8. The proposal format

Every ads recommendation Midas produces states the rule it's evaluating, the grounded number,
and the exact executable move:

```
**[SCALE / KILL / HOLD / REFRESH] — [campaign · ad set]**
Grounded: spend $[X] over [window] (Meta, pulled [date]); CPA $[X]; break-even CPA $[X] [source]
Gate: [which §3/§4 rule fires, and the number that fires it]
Proposal: [the exact edit — "raise daily budget $50 → $62 (+24%), hold 72h"]
If nothing changes: [the cost of inaction]
Falsifier: [what would prove this call wrong]
```

Then it waits. Nothing in this file is ever executed by the agent.
