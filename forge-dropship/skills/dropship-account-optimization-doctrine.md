---
agent: midas
skill: account-optimization-doctrine
role: How Midas decides whether to act at all, what to touch, and how to scale — the restraint layer
lane: creative & ads
seed: true
priority: top
source: "Field notes distilled from a Meta account-optimization walkthrough by a media buyer managing $5M+ in e-commerce spend (Ole Strand, 2026-07-21, youtu.be/sW7riW434Mg) — paraphrased into operating rules, cross-checked against this account's own evidence rules."
---

# Account Optimization Doctrine — Midas, creative & ads lane

> Division of labor inside this lane, so these don't collide:
> - [[dropship-meta-ads-diagnostician]] — *which metric is the bottleneck* (the 12
>   sliders, the hose bend).
> - [[dropship-creative-testing-doctrine]] — *what to put in the test queue* and why a
>   winner died.
> - **This skill** — *whether to act at all*, what is safe to touch, how the account is
>   structured, and how to scale. It is the **restraint layer**: the diagnostician can
>   name a constraint correctly and the resulting action can still destroy an account
>   that only needed to be left alone.
>
> Rank order unchanged: the creed [[dropship-evidence-discipline]] and
> [[dropship-account-health]] outrank everything here. [[midas-decision-loop]] governs
> HOW to reason; [[midas-craft]] governs triage order. Loads via `_load_skills()`, so
> `learn()` can never rewrite it.
>
> **Everything below is a PROPOSAL.** Midas never pauses, scales, re-budgets, or
> restructures. Rule 2 is not softened by any line in here.

---

## The one-paragraph thesis

Most account damage is self-inflicted, done by an operator reacting to a short window of
bad numbers with a change that resets the algorithm's learning. So the analysis order is:
**pick the window → ask what changed → decide whether the honest answer is "wait" →
only then choose an action.** Skipping to the action is the single most expensive habit
in paid media.

---

## 1. Choose the time window before looking at anything

Reading too short a window is the first mistake, and it contaminates every decision that
follows. Daily results swing by weekday; a 2-day read is mostly noise about which
weekdays you happened to catch.

- **Never conclude anything from under 3 days.**
- **7 days is the decision window** — a full week normalizes weekday effects. Scale
  up/down, kill, restructure: all need 7.
- **3 days is a directional read only** — "is this new concept showing signs of life"
  (CTR, early CPA), never a kill or scale decision. It is far more reliable when you
  already have history for how this account behaves after a launch.

**Then adjust the window to the customer journey.** The window has to be at least as
long as the time from first touch to purchase, or you are grading ads on sales that
haven't happened yet:

- Low-AOV impulse products: journey compresses to 1-2 days; a 7-day read is generous.
- High-ticket products/services: the lead converts one to two weeks later, so a 7-day
  read systematically credits the wrong ads. Zoom out, or you optimize toward whatever
  generates fast cheap leads instead of whatever generates buyers.

Midas states the window and the assumed journey length on every performance claim,
sourced or marked Unknown. "CPA is up" without a window is not evidence.

---

## 2. Ask "what changed?" — and sort it into in-control vs. out-of-control

Before any recommendation, enumerate every variable that moved in the window, then sort:

| Outside our control | Inside our control |
|---|---|
| CPM inflation (seasonal, Q4, auction-wide) | Ad fatigue / frequency climbing |
| A competitor launching a new offer | Creative gone stale, nothing new launched |
| New entrants bidding up the audience | Our offer, price, or page changed |
| Seasonal demand trough for the category | Budget, structure, or targeting we edited |
| Platform-wide delivery shifts | Stock-outs, shipping times, site speed |

This sort determines the entire response. **If the only thing that changed is outside
our control, there is usually no action inside the ad account that helps** — the account
is performing correctly against a worse market. The available moves are then *offer-side*
(convert a higher share of the expensive traffic — which is why brands run promotions in
expensive periods whether they want to or not) or *budget-side* (spend less until the
market improves). Neither is "turn off ads."

If the change is inside our control — fatigue is the common one — then the corresponding
fix is real: fresh concepts for fatigue, a better offer for a conversion-rate drop, and
so on.

---

## 3. "Do nothing" is a course of action, and often the right one

There are only two moves: change something, or wait. Waiting is the harder one to
choose, especially for the person whose money it is, and choosing wrong here is the most
common way accounts get wrecked.

The failure mode is specific: results dip for reasons outside your control, the operator
shuts off top-spending ads to "stop the bleeding," and then the market normalizes — only
now the proven ads are off and the algorithm has to redistribute that budget onto
less-proven ones. The dip caused a week of pain; the reaction caused a month of it.

**When the answer is wait, it is never open-ended.** Midas commits, in the proposal, to
all three:

1. **How long** — a specific date/duration ("hold through Sunday, a second full 7-day
   window").
2. **What "recovered" means** — the metric and threshold that ends the wait.
3. **What happens if it doesn't recover** — the exact next action, decided now, while
   nobody is panicking.

That third item is what makes waiting a decision rather than avoidance.

---

## 4. Don't turn off the top spenders

There is little to gain from turning off ads and a great deal to lose.

**Why spend concentration is a signal, not a symptom.** In a CBO optimizing for lowest-
cost conversions, the ads getting most of the budget are getting it because the algorithm
has the most evidence they can convert at volume. A cheaper CPA on a low-spend ad is
mostly an artifact of small volume — push budget into it and its CPA usually degrades
toward or past the top spender's. The top spender looks like the problem precisely
because it carries the volume.

**Why the algorithm outreads you here.** It weighs signals no dashboard exposes — dwell
time, scroll-stop behavior, engagement depth, cross-placement patterns — across far more
events than a human reviewing a table. Modern CBO delivery is genuinely better than
manual reallocation at this specific job. Cutting an ad overrides that with a decision
made on a handful of visible columns.

**The one clean kill condition.** Turn an adset off when it is spending *only* the
forced minimum you imposed (see §6) — that is, the algorithm is not electing to fund it
— **and** it is still missing target CPA over a full 7-day window. Then the spend is
yours, not Meta's, and the data says the concept doesn't work. Absent forced spend,
manual killing is rarely the right move.

An adset slightly outside target that is pulling real volume is not a kill candidate. It
may be carrying the mix.

---

## 5. Split new vs. returning revenue before you touch the ads

"Performance is down" is not a paid-media claim until it's been decomposed. Total revenue
falls for reasons that have nothing to do with acquisition.

Order of operations when revenue drops:

1. **Split the window's revenue into new-customer and returning-customer.**
2. **If new-customer revenue is stable** — acquisition is working. The dip is on the
   retention side, and the correct levers are email, SMS, organic social, and win-back
   incentives, not the ad account. Touching a working paid funnel to fix a retention
   problem is how you end up with two problems.
3. **If returning traffic specifically is down**, the brand has gone quiet: send more
   email/SMS, run list-only or organic-only incentives, put activity back on the
   channels the existing base watches.
4. **If new-customer revenue is what fell**, the problem is in scope for §1-§4.

The margin caveat on incentives: frequent discounting trains the base to wait for the
next promo and erodes both margin and brand perception. List-exclusive or
giveaway-style incentives are the lower-damage version.

For a brand meant to compound, returning revenue trending toward roughly half of monthly
revenue is a healthy target — and low returning revenue is a retention project, not an
ad-budget project.

---

## 6. Structure: one CBO, weekly concept adsets, forced test floors

The structure below is reported to have carried an account from ~$22k to ~$200k+ monthly
revenue inside six months. It is offered as a **pattern with a stated rationale**, not a
mandate — the reasoning is what transfers.

**One CBO doing both testing and scaling.** The textbook split (separate testing campaign
feeding a separate scaling campaign) is defensible, but in this account the two campaigns
overlapped in delivery enough to hurt both. Consolidating everything into one CBO and
raising that campaign's budget over time worked better. If Midas ever proposes a split
structure, he should say what evidence supports the split for *this* account rather than
citing the convention.

**One adset = one concept batch.** Weekly, launch new adsets into the campaign. Within an
adset: identical targeting and setup, and a single concept — one ad style speaking to one
persona or one buying trigger. This matters because **learning happens at the adset
level**: a clean adset teaches the algorithm something legible; a mixed one teaches it
noise.

**Forced spend floors so tests conclude on schedule.** Left alone, a new adset can sit
unfunded for days while the algorithm favors proven ones, and you learn nothing on a
usable timeline. Setting an adset *minimum* daily spend forces conclusive data:

- The reported setting: a floor of roughly **1x AOV per day for 7 days**.
- It is a **floor, not a cap** — the algorithm can and does spend more when the concept
  earns it. That asymmetry is the whole point: fast data on losers, no ceiling on winners.
- The floor is what makes §4's kill condition meaningful. Only spending its floor after
  7 days = the algorithm declined to fund it.

**Then let the CBO allocate.** No manual budget shifting between adsets. The reason to
resist is in §7.

---

## 7. Ads work in harmony — never judge one in isolation

This is the most counterintuitive item here and the one Midas is most likely to get
wrong, because the naive read of the numbers points the wrong way.

**What happens in a mixed campaign.** Video ads tend to do top-of-funnel work — creating
awareness and interest. Statics, without any bottom-funnel targeting being set, drift
into the mid/bottom of the funnel because the algorithm works out that's where they
perform. Statics also have far more available placements than video (feeds, Messenger,
and the rest of the inventory video can't run in), so a warmed-up person sees them more
often.

**The consequence: attribution misallocation.** The static is frequently the last thing
touched before conversion, so it collects the credit for demand the video created. That
produces statics with excellent ROAS, excellent CPA, and high frequency — which look
exactly like your best ads and your most obvious scaling candidates. **They are usually
neither.** They are efficient converters of demand they did not generate, and pushing
budget into them scales the closing step of a funnel whose opening step you just
defunded.

Three rules follow:

- **A high-ROAS, high-frequency static is not automatically a scale candidate.** Check
  the ad mix before recommending anything on the strength of ROAS alone.
- **The algorithm putting most spend into lower-ROAS video is often correct** — that's
  where the heavy lifting happens. Overriding it manually is how the funnel gets
  starved at the top.
- **Read frequency in context.** High frequency on a static-heavy adset serving a warm
  audience is expected and fine. High and climbing frequency on a top-of-funnel video
  adset with a falling CTR is fatigue. Same column, opposite meanings.

**Don't mix top-of-funnel and bottom-of-funnel ads in one adset.** Separate them by
persona and funnel stage into separate adsets and let the algorithm learn each stage's
placement independently. That separation is what makes the allocation trustworthy enough
to leave alone.

---

## 8. Scaling: earn it, then step, then re-earn it

**Scale up** when target CPA or target ROAS has held for a consecutive stretch — not one
good day:

- Raise budget **20-25%**.
- Hold it another week. If the target still holds, raise again.
- Bigger jumps are only justified by *historic evidence* of a genuinely high-demand
  window (a real gift-buying season for this product, with last year's numbers to show
  it). Absent that data, the step stays 20-25%.

**Scale down** when demand is structurally low rather than when performance merely
disappointed. Burning budget through a known trough to "keep momentum" spends money at
the worst available price. Bank it for the window where the same spend converts better.

**Plan the calendar.** Annual demand shape, from real historic data, should drive budget
allocation across the year. Spending in a low window is only defensible with something
specific attached — a launch, a seasonal offer, a promotion — not evergreen ads pushed
harder.

---

## Thresholds — borrowed, not ours

The source's numbers, recorded so Midas can reason about the *shape* of these rules, and
**never quoted as this store's figures**:

- Target CPA ~$22, with roughly $25 as the tolerance edge.
- Adset spend floor $50/day ≈ 1x their AOV, held 7 days.
- Scale step 20-25% per held week.

Ours must be derived from our own AOV, contribution margin, and target CPA — from real
cost inputs, per the creed. The step size (20-25%) and the window (7 days) are the
transferable parts; the dollar amounts are not. If our inputs aren't wired yet, Midas
gives the formula (`floor = 1x AOV`, `kill = floor-only spend + missed target over 7d`)
and says which input is missing.

---

## How Midas uses this

**In the creative & ads lane**, when asked "performance is down, what do we do?",
"should we scale?", or "should I turn this off?":

1. **Window first.** State it, and state the assumed customer-journey length. Refuse to
   conclude from under 3 days — say so plainly rather than answering anyway.
2. **Decompose the revenue.** New vs. returning (§5). If the dip is retention, say so and
   stop recommending ad changes.
3. **Enumerate what changed**, sorted in-control vs. out-of-control (§2), each item
   sourced or marked Unknown.
4. **Answer "act or wait" explicitly** (§3). If wait: duration, recovery threshold, and
   the pre-committed next action, all three.
5. **If acting, check the mix before naming a target** (§7). Is that high-ROAS ad a
   closer riding on someone else's work? Is that top spender actually the problem, or the
   thing holding the account up (§4)?
6. **Ship it as a proposal** with the window, the evidence, and what would falsify the
   read. Never an execution.

**Hard stops, unchanged.** Account health outranks this entire skill. No pause, no budget
change, no structure edit, no launch — the operator taps; Midas thinks.
