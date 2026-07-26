---
agent: midas
skill: adspy-method
role: How to read competitor ads and decide whether to enter a market at all
lane: product research
seed: true
priority: sop
---

# Ad-Spy Method — reading the competition without lying to yourself

[[midas-decision-loop]] governs how you reason; [[midas-craft]] holds the operating
judgment. This is the **method for one specific input**: what other advertisers are publicly
running, and what it does and does not tell you.

Ad spy is the cheapest real market signal in this business. It is also the easiest place to
manufacture a confident wrong answer, because a competitor's ad *looks* like proof of profit
and is not. Read it the way the creed demands: it grounds a claim about **what competitors
are running**, never a claim about **our margin, our stock, or what a product will do for
us**.

---

## The data sources

| Source | Module / route | What it grounds | Key field |
|--------|----------------|-----------------|-----------|
| **Meta Ad Library** (via Apify) — primary | `forge rei/dropship_adspy.py` · `GET /api/dropship/adspy/search` | Which ads are live right now, since when, how many variants, which advertisers | **`daysRunning`** — the longevity signal, the single most load-bearing number here |
| **PiPiAds** — secondary | `forge rei/dropship_pipiads.py` · `GET /api/dropship/trending` | Trending products with TikTok + Facebook ad-spy signal and TikTok Shop revenue trend | trend/impression movement |

Both are in the creed's systems-of-record list — cite them by name and date the pull, same
as a Meta or Shopify number. Neither is keyed today; an unkeyed read returns a mock, and a
mock is **not** evidence. If the key is blank, the honest output is Unknown, not a read.

Use the Ad Library as the primary because it is Meta's own disclosure of live ads —
first-party, complete, and free of a vendor's ranking bias. Use PiPiAds to *find candidates*
and to see TikTok-side movement the Ad Library can't show; then verify anything it surfaces
against the Ad Library before it influences a decision.

---

## 1. Longevity is the primary signal

Nobody keeps paying for an ad that loses money. Spend duration is the closest thing to a
public P&L a competitor will ever give you.

| `daysRunning` | Read |
|---------------|------|
| **< 7 days** | Nothing. A test. Could be dead tomorrow. Zero evidence of profitability. |
| **7–20 days** | Survived the first kill window. Weak positive — someone chose not to turn it off. |
| **21+ days** | **The ad is paying for itself.** Three weeks of continuous spend past the learning phase is a rational operator deciding, repeatedly, to keep buying. This is the threshold where longevity becomes real signal. |
| **60+ days** | **Proven winner.** Two months of continuous spend through creative fatigue, CPM swings, and at least one refresh cycle. Whatever this is, it works — for them. |
| **180+ days** | Either a genuine evergreen offer or a brand with a budget line that isn't performance-managed. Check whether the advertiser is a real brand before treating it as a dropship proof point. |

**The three things longevity does not tell you:** their margin, their volume, or their
supplier cost. An ad running 90 days at a 5% net margin is still running. Longevity proves
*viability of the angle*, never *the size of the prize*. Never convert a `daysRunning` number
into a revenue estimate — that is inventing a metric (creed §1).

**Two failure modes to check before trusting the number.** Paused-and-restarted ads can
report a long window with gaps — confirm the ad is *active now*, not just old. And a long run
on a **brand** advertiser (their own product, their own margin structure) is not transferable
to a dropship P&L; check the advertiser page before you copy their math.

## 2. Spotting a scaling advertiser

One long-running ad means the angle works. **Many active variants of the same creative means
they are pushing money through it**, and that is a much stronger signal than any single ad's
age.

What to look for in the Ad Library result set:

- **Variant count.** 10, 20, 50 active ads that are recognizably the same creative with
  different hooks, thumbnails, or copy openings. That is a testing budget in motion. Someone
  spending to find the next 10% on a creative has already found the first 100%.
- **Variant recency spread.** Old variants still running *plus* new ones added this week =
  actively managed and scaling. All variants launched the same day = one batch test, unproven.
- **Placement/format breadth.** The same angle running as static, UGC video, and carousel
  means they've been at it long enough to know the angle survives format changes.
- **Landing-page consistency.** All variants pointing at one product page = a hero product
  carrying the store. Variants pointing at different pages = a catalog play, different game.

Rank a market by *variants × longevity*, not by either alone. One 90-day ad is a niche that
works for someone. Thirty active variants at 45 days is a market with real money in it.

## 3. The saturation curve — and what the shape tells you to do

Plot the advertisers on two axes: **how many** are running this product/angle, and **how old**
their ads are. Four shapes, four different decisions:

| Shape | What it means | Move |
|-------|---------------|------|
| **Few advertisers, all recent** (< 14 days) | Early. Either a product just breaking out, or a dud several people are about to quit on. | **Watch.** Cheapest possible test if the margin math works. Re-pull in 10 days — if the same advertisers are still running, the curve just told you it's real. |
| **Many advertisers, all recent** | A trend cresting *right now*. Everyone found it the same week. CPMs are about to climb and the offer will get commoditized fast. | **Enter only with speed and a differentiated offer**, or skip. Late entry into a crowded recent wave is where beginners lose money — you pay peak CPM to sell the same thing at the same price. |
| **Few advertisers, all old** (60d+) | The best shape in the table. A durable offer that most people never found or couldn't execute — often a sourcing, creative-production, or support barrier. | **Highest-priority candidate.** Find out *why* it's uncrowded before entering; the barrier is the moat and you need to know if you can clear it. |
| **Many advertisers, all old** | Mature and saturated. Real demand, but the easy money is gone and incumbents have creative libraries, reviews, and retargeting pools you don't. | **Differentiate or skip.** Never clone here. A me-too entry against a 6-month incumbent loses on every axis. |

Two more reads worth taking:

- **Advertiser count falling while longevity rises** — the market is consolidating around the
  operators who make it work. Hard to enter, but the ones left are worth studying closely.
- **A wave of new advertisers on a product whose old advertisers all stopped** — a recycled
  trend. Check whether the original wave died from saturation or from a fulfillment/quality
  problem. The second one will kill you too.

## 4. Clone vs. differentiate

The decision the whole exercise exists to answer:

**Clone** (same angle, our own execution) only when *all* hold:
- The market shape is "few advertisers, all recent" or "few, all old" — room exists.
- Our landed COGS + our price supports our target margin **independently** (that's a
  Shopify/AutoDS number, not an Ad Library one — and it's Unknown until the store is keyed).
- We can match or beat the offer, not just the creative. See §6.
- Nothing about the product trips [[dropship-account-health]] — no IP, no health claims.

**Differentiate** (same demand, different angle/offer/avatar) when:
- Many advertisers are already on the obvious angle. The unclaimed angle is worth more than
  the proven one, because the proven one now costs peak CPM.
- The incumbents all speak to the same avatar. A second avatar with the same product is the
  cheapest differentiation there is — and it's exactly what
  [[dropship-four-triggers-ad-writer]] Trigger 1 is for.
- Their offer is weak (flat % discount, no guarantee, no bundle). A better offer beats a
  better creative more often than operators expect.

**Skip** when the market is mature-and-saturated, when the margin math doesn't clear without
optimistic inputs, or when you can't tell — an Unknown you can name is a better output than a
confident entry.

## 5. Extracting the angle and offer

Pull a competitor creative apart into the Four Triggers ([[dropship-four-triggers-ad-writer]])
— that structure is the extraction template, not just the writing template:

1. **Avatar** — who does the first line stop? Not who the product is for; who the *opening
   line* is for. If the hook is "Most guys over 30 notice it in the shower first," the avatar
   is stated in the hook and Meta is targeting on it.
2. **Problem** — which layer are they working? Surface problem, failed solutions, or emotional
   cost? Long-running ads are usually one layer deeper than new ones. That depth is the thing
   worth stealing.
3. **Unique Mechanism** — what do they claim makes it work? Named mechanisms ("dynamic
   tightening straps") outperform feature lists, and a competitor who named theirs has told
   you the category's language.
4. **Offer** — the value stack, the timing reason, the risk-reversal. Write down the *exact*
   structure: B2G1? Free shipping threshold? 30/60/90-day guarantee? Bundle + gift?

Then record what you could **not** see: their landed cost, their AOV, their refund rate,
their true CPA. Those are Unknown and stay Unknown. The extraction gives you the angle; it
never gives you the P&L.

## 6. The trap: copying the creative without copying the offer

This is the single most expensive mistake in ad-spy-driven product research, and it looks
like diligence while you're making it.

You find a 60-day ad, you rebuild the creative faithfully, you launch, and it loses money —
because the ad you copied was selling **Buy 2 Get 1 Free with a 60-day guarantee and free
shipping over $50** at an AOV that supported a $34 CPA, and you launched a single unit at $29
with a 14-day return window. The creative was never the thing that made it work. **The
creative earned the click; the offer earned the profit.**

Rules that follow from it:

- **Never port a creative without porting the offer.** If you can't match the offer at your
  landed cost, you have not found a winner — you have found someone else's winner and your
  own loss. That is a *sourcing* problem to solve first, not a creative brief.
- **Their price is data, not a rule.** A competitor at $49 may be running a different supplier,
  a different shipping method, or a different margin tolerance. Price to *your* margin math
  (Unknown until the context brief's target-margin block is filled), then check whether the
  angle still works at that price.
- **A guarantee is a cost line.** A 60-day guarantee raises conversion and raises refunds.
  Copying it means copying its refund rate into your margin — and refund rate is an account-
  health input ([[dropship-account-health]]), not just a P&L line.
- **If the offer needs volume pricing you can't get, the honest read is: not yet.** Say that,
  name the sourcing gap, and move to the next candidate. A named blocker beats an optimistic
  launch.

## 7. Output shape

When Midas reports an ad-spy read, every claim carries its source and pull date:

```
**Market read — [product/angle]** (Meta Ad Library via Apify, pulled [date])

Longevity: [N] advertisers active; top ad daysRunning = [N]; median = [N]
Scaling signal: [advertiser] running [N] active variants, spread [oldest]–[newest]
Curve shape: [few/many] advertisers, [recent/old] → [entry read]

Angle extracted: Avatar [..] · Problem [..] · Mechanism [..] · Offer [exact stack]
Unknown: our landed COGS, our achievable AOV, their true CPA and refund rate

Call: [clone / differentiate / watch / skip] — because [one sentence]
Falsifier: [what would change this call]
```

Nothing here launches anything. This lane produces a **candidate and a recommendation**; the
operator taps to source, list, or spend (creed §6, root `CLAUDE.md` rule 2).
