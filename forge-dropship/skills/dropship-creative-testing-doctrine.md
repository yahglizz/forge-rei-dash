---
agent: midas
skill: creative-testing-doctrine
role: How Midas decides WHAT to test, WHY a winner died, and WHERE the next lift lives
lane: creative & ads
seed: true
priority: top
source: "Field notes distilled from a 1,352-ad / 30-day Meta media-buying teardown (Mark Builds Brands, 2026-07-28, youtu.be/r7E2DSRq9Lo) — paraphrased into operating rules, cross-checked against this account's own evidence rules."
---

# Creative Testing Doctrine — Midas, creative & ads lane

> [[dropship-four-triggers-ad-writer]] teaches Midas how to WRITE an ad.
> This skill teaches him what to **put into the test queue in the first place**, how to
> read a testing program that has stopped paying, and what to do with a winner that
> died. It is a **portfolio-level** rubric, not a copy framework.
>
> Rank order is unchanged: the creed [[dropship-evidence-discipline]] and
> [[dropship-account-health]] outrank everything here. [[midas-decision-loop]] governs
> HOW to reason; [[midas-craft]] governs triage order. When this skill and the learned
> [[midas-playbook]] disagree on testing method, **this wins** — it loads through
> `_load_skills()`, so `learn()` can never rewrite it.
>
> **Everything below is a PROPOSAL.** Midas never launches, pauses, duplicates,
> re-budgets, or edits a live page. Rule 2 is not softened by any line in here.

---

## The one-paragraph thesis

Creative volume buys you a temporary CAC improvement and then stops working. The
program that keeps improving after that point is the one that changes what it is
testing, not how much. Everything in this doctrine follows from that: diversity over
volume, principles over swipes, funnel as the multiplier on creative win-rate, and
"dead" as a conclusion you earn only after exhausting the levers that raise a
creative's spend ceiling.

---

## 1. Diversity is the axis that keeps paying; volume is the one that stops

Plot CAC against creatives tested per week. It falls — real gains, for a while — then
flattens, then rises again while volume keeps climbing. **That inflection point is a
diagnosis, not bad luck.** It arrives for every account; only the number differs (20/wk
for one brand, 500/wk for another). Past it, another 100 near-identical creatives buy
nothing: the proportion that survive testing and graduate into the scaling campaign
falls, so you are paying more test budget for fewer graduates.

**How Midas detects it** — from real data or not at all:
- Test-campaign spend and creatives launched per week, trailing 4-8 weeks
- Blended CAC (or CPA on the test campaign) over the same weeks
- **Graduation rate**: creatives that exited testing into scaling ÷ creatives launched

Rising volume + flat-or-rising CAC + falling graduation rate = saturation of the
*current concept space*. Say that plainly, and say what the trailing window was. If any
of the three series is missing, the honest output is "cannot confirm saturation —
missing graduation rate for weeks X-Y", not a confident diagnosis.

**The response is not more ads.** It is a different axis of variation. Diversity means
the concept, format, and person differ — not the hook line on the same UGC clip:

| Low diversity (looks like volume) | Real diversity |
|---|---|
| 12 hooks on one UGC clip | UGC vs. native static vs. founder-to-camera vs. interview vs. podcast clip |
| Same actor, 6 outfits | Different avatar entirely (see the Four Triggers avatar step) |
| Same claim, 8 headlines | Different mechanism, different problem framing |
| Same format, new music | A format not currently running in the vertical at all |

When Midas proposes a testing slate, he states the diversity axes it spans. A slate
that spans one axis is volume wearing a costume, and he should name it as such.

---

## 2. Source from the feed, not from the ad library

Swiping a competitor's ad caps you at second place, and only if the execution is
flawless — you inherit their angle after their spend has already taught the auction
about it. Winners come from testing broadly, spotting which *variables* recur across
the ones that worked, and combining those variables into something that isn't running.

**The extraction habit that makes this work**: for every winner, write down *why* it
won — the variable, not the ad. "Unpolished phone footage beat studio" is a variable.
"That video with the dog" is not. This is the compounding asset; the creative itself is
disposable.

**Where new formats actually come from.** Native image ads, interview ads, UGC, founder
ads, podcast ads all emerged the same way: someone noticed a content shape people were
already consuming organically and ran it as an ad *before* it read as an ad. The
sourcing loop is therefore:

1. Keep a burner account per market, following what the customer follows.
2. Scroll it deliberately, in the customer's shoes — the **organic posts**, not the ads.
   Ads teach you what advertisers already believe; posts teach you what the market
   actually stops for.
3. **Rule of three**: when the same organic content shape shows up three-plus times, it
   is a validated attention pattern. That is the trigger to build an ad in that shape
   and add it to the queue.
4. Log where it came from. A format proposal with no provenance is a hunch, and the
   creed says hunches get labeled, not laundered.

Midas can't scroll a phone. What he *can* do is treat operator-reported feed
observations as a first-class input, ask for them when the queue is stale, and keep the
running list of observed shapes with dates and counts.

**The inverse test.** Take consensus best-practice — the thing every course and every
platform rep recommends right now — and queue a deliberate opposite as one lane of the
program. One consolidated CBO is the consensus; ten campaigns is the inverse. All
enhancements on is the consensus; all off is the inverse. Consensus advice is priced
into the auction because everyone is running it. Two caveats keep this from being
reckless: it is **one lane, not the whole account**, and it never applies to account
health or policy — [[dropship-account-health]] is not a convention to invert.

Old tactics that "don't work anymore" are the same trade. Most were abandoned because
they got crowded, and crowding decays. Cheap to retest, occasionally uncontested.

---

## 3. AI creative is not the moat — the reasoning is

Generation is now effectively unlimited and nearly free, which is exactly why it stopped
being an edge: an input everyone has at zero scarcity can't differentiate anyone. The
scarce input is knowing *why* an ad worked well enough to rebuild the reason on purpose.

Practically, this means Midas never answers "we should test more creatives" as a
strategy. If the account is past the inflection point in §1, more generation is the
thing that already failed. The answer is a stated hypothesis about *why* current
creatives underperform, and a slate designed to test that hypothesis.

---

## 4. Funnels are multipliers on creative win-rate

Picture the funnel as water level and each creative as a boat. A creative is a "winner"
only relative to what the page converts at. Raise conversion rate, AOV, or LTV and the
water rises — **the same creatives that drowned now float.** A 10% win rate on funnel A
can be 30% on funnel B with an identical creative set.

Three consequences Midas should apply:

- **"We can't find winning creatives" is not automatically a creative problem.** Before
  proposing another creative slate, check whether the funnel has been tested at all. If
  every creative has only ever seen one page, the win-rate ceiling is the page's.
- **Funnel testing has creative leverage.** A better page doesn't just lift the ads
  running now; it raises the future graduation rate of everything tested after it. That
  makes funnel work compete directly with creative work for the same slot — rank it as
  such in the brief, don't bolt it on at the end.
- **A single funnel is concentration risk.** Pages die like creatives do. Backups —
  funnels, ad accounts, pages, business managers, stores — are hygiene, and the time to
  build them is while things are working.

---

## 5. Media buying: roughly a fifth of the outcome, and it scales with spend

Rough weighting to reason with, not a law: creative is the largest single share, funnel
next, **media buying about 20%**, product about 10% *once product is proven*. Anyone
claiming media buying is worthless has usually never bought media; anyone claiming it
rescues bad creative is selling something.

The important qualifier: **media-buying lift is spend-dependent.** Under a few hundred
dollars a day, structure fiddling is noise — creative and funnel are the only levers
that move anything measurable. Above roughly $1k/day, structure, grouping, and scaling
method reliably move CAC. Midas should say which regime the account is in before
proposing structure changes, and at low spend should actively *decline* to propose
them in favor of creative and funnel work.

And the standing rule of media buying: **don't touch what's working.** A change to a
performing ad set is a real cost with an uncertain payoff.

---

## 6. Do not split-test the first post-click page

This is the most operationally specific rule here and the easiest to get wrong, so read
it as written.

**The rule:** never run a traffic-splitting test (50/50 software split, Shopify/Funnelish/
Checkout Champ variant routing) on the **first page traffic lands on after the ad
click** — the listicle, advertorial, or PDP the ad points to.

**Why.** Meta re-scans landers after approval. A page that changes post-approval gets
read one of two ways, both bad: as cloaking (getting an ad approved, then swapping in
something non-compliant — a policy problem, not a performance one), or as a soft flag.
The observable symptom is that **the control degrades too**. Not "the variant lost" —
the control, which was working yesterday, drops ~20% while the variant drops more. You
learn nothing about the page and you damage what was already profitable. Lose-lose.

**The right way to test a first page:** duplicate the winning creatives as **new post
IDs** pointed at the new page, in a new ad set or a new campaign. Everything else held
constant. Yes, you land in a slightly different traffic pocket — that is a real and
acceptable cost, because the alternative is contaminating the thing that already pays.

**Why this matters more than it sounds.** In the source case, a listicle tested as a
50/50 split looked like a catastrophic loser (-50% vs. a control that had itself fallen
~20%) and was cut. Retested with new post IDs in a new campaign, that same page beat the
control, replaced it, and absorbed over $400k in spend over the next 60 days. The split
test did not measure the page; it measured the penalty. **A page killed by a first-page
split test has not been evaluated — Midas should treat that verdict as void and flag it
for a clean retest** rather than accepting it as data.

Testing further down the funnel (upsell pages, post-purchase flows, checkout) is not
covered by this rule; the ad-scan mechanism does not apply there.

---

## 7. Why winning ads die — and how the ceiling gets raised

Every creative has a **profitable spend ceiling**. Think of a tier list: most creatives
can't spend past break-even at all; some carry a few hundred; fewer carry $1k, then
$10k, then $100k, then seven figures. Statics tend to cluster lower — they are cheap to
produce and cheap to exhaust — while the top tiers are usually video, simply because
video sustains more consumption before fatigue. The offsetting truth is that you get far
more static winners, so the two roughly even out. Neither format is "better"; they have
different ceiling distributions and different production economics.

An ad "dies" when it reaches its ceiling: CAC drifts past KPI, drags the account, gets
cut. **That is a ceiling event, not a verdict on the creative** — and the ceiling is
movable. Before Midas ever calls a creative dead, these must be exhausted:

1. **Media buying.** New campaign structure. Different scaling method (duplication-based
   scaling, staged duplicates). Narrowing. New audiences. And the underrated one:
   **creative grouping** — a creative sometimes performs materially better beside a
   specific set of other ads, even when those ads take almost no spend themselves.
2. **New funnels.** Was that winner ever run against a different page? Per §4, the same
   creative has a different ceiling on a different funnel.
3. **Unit economics.** The ceiling is denominated in what you can afford to pay for a
   customer. Move break-even from $50 to $70 — lower COGS, better shipping rates, higher
   price, higher AOV, better back-end — and **every creative in the account gets more
   headroom at once.** This is the only lever that lifts the whole tier list.
4. **Iterations.** Variations of the winner are the obvious move and worth naming, but
   they are a new creative with a new ceiling, not a raised one.

Only after those come back empty is "dead" the honest word. Written as a proposal:
*"Creative X hit its ceiling at $Ns spend, CAC $A vs. target $B (source, window).
Untried levers: new campaign structure, funnel B, grouping with the current top 5.
Recommend attempting 1 and 2 before retiring."*

---

## 8. Take bigger swings — especially when spend is low

Test size has to be readable against the noise floor. At $100k/day, a headline swap
worth a few cents of EPC is a real, measurable win. At $500-1,000/day the same test
returns nothing you can distinguish from variance, and you have spent a week learning
it. Small tests are a luxury purchased with spend volume.

So: at low spend, propose **structural** swings — a different funnel architecture, a
format nobody in the vertical is running, an entirely different avatar or mechanism, a
new page rather than a new headline. Above the fold (headline, subhead, first image) is
correctly the highest-leverage part of a page to change, but "change the headline" and
"change what the page fundamentally is" are different sizes of swing, and only one of
them is legible at small budgets.

The evidence discipline still applies: a big swing is still a stated hypothesis with a
pre-declared kill threshold. Bigger swing, not sloppier test.

---

## 9. Spend is the scoreboard — with the LTV caveat

Operators who talk only in ROAS are usually optimizing a small account. The largest
brands run unremarkable ROAS and win on LTV and total spend, because volume of
profitable acquisition — not efficiency ratio — is what compounds.

This does **not** license spending into losses, and it does not override
[[dropship-account-health]] or the margin rules in [[midas-craft]]. Read it as a framing
correction: when a proposal trades a little ROAS for a lot more profitable volume, and
the contribution margin and cash cycle survive it, that is usually the right trade —
and Midas should show the LTV or repeat-rate evidence that makes it right, or label it
Unknown and say what data would settle it.

---

## Thresholds — borrowed, not ours

The source operates at a scale FORGE Dropship does not. These are his gates, recorded so
Midas can reason about the *shape* of a testing gate, and **never quoted as if they were
this store's numbers**:

- Kill a test creative at 1x break-even, or ~2x target CPA, with no sale.
- Treat ~$500 of profitable spend as the first real "this works" tier.

Our equivalents must be derived from our own break-even, target CPA, and daily budget —
from real cost inputs, per the creed. If those inputs aren't wired yet, Midas says so
and proposes the gate as a formula (`kill at 1x break-even = COGS + shipping + fees +
target margin`), not as a number he made up.

---

## How Midas uses this

**In the creative & ads lane**, when asked what to test, why testing stopped working, or
whether a creative is finished:

1. **Ground it.** Volume, CAC, graduation rate, spend regime, funnel count, and the
   creative's own spend/CAC history — each with source and window, or marked Unknown.
   Missing data narrows the claim; it never blocks the recommendation.
2. **Locate the account.** Which of these is it? Pre-inflection (volume still paying) ·
   post-inflection (needs diversity) · funnel-capped (win rate is the page's fault) ·
   sub-$1k/day (media buying is noise) · ceiling event (a specific winner died).
3. **Rank falsifiable hypotheses**, 3-5, cheapest-to-disprove first. Do not anchor on
   "we need more creatives" — §1 and §3 exist precisely because that is the reflex.
4. **Close the loop.** If the next lookup wouldn't change the recommendation, recommend.
5. **Ship it as a proposal** with a stated diversity axis, a kill threshold, and the
   evidence each claim rests on. Never an execution.

**Hard stops, unchanged.** Account health outranks this entire skill — a merchant or ad
account under review gets stabilized before anything here is proposed. No launch, no
budget change, no pause, no page edit, no supplier order, no customer message. The
operator taps; Midas thinks.
