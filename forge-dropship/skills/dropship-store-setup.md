---
agent: midas
skill: store-setup
role: Shopify build + CRO + the pixel/CAPI truth layer every ads rubric depends on
lane: creative & ads / ops
seed: true
priority: sop
---

# Store Setup — the build, the offer, and the measurement that makes every other number real

> Everything here is a **recommendation Midas hands the operator**. He does not publish a
> theme, edit a listing, change a price, or install a pixel. Rule 2 / creed §6.

Two things live in this file and the second one matters more than the first.

**The build** (§1–§7) is how a Shopify store converts the traffic paid ads buy — because
[[midas-craft]] is right that the funnel leaks at the seams, and no ad budget fixes a
product page that doesn't close.

**The measurement layer** (§8) is why every other rubric in this folder can be trusted at
all. [[dropship-meta-ads-diagnostician]] scores CVR, ATC-rate, and ROAS.
[[dropship-ad-launch-sop]] kills and scales on CPA. **Every one of those numbers is produced
by the pixel.** A broken or duplicated pixel doesn't make the rubrics slightly wrong — it
makes them confidently wrong, which is worse. Read §8 as the load-bearing section.

---

## 0. Mobile-first is a build requirement, not a polish pass

**Operator standing rule (2026-07-30): every Shopify page is mobile-optimised in the same
build that creates it.** Never ship a desktop-first page intending to fix the phone layout
later — by then real paid traffic has already seen the broken version, and this store sells
almost entirely to mobile paid social.

The phone layout **is** the layout. Desktop is the courtesy view. Before any page is called
done, all of the following must be true:

- **Sticky Add to cart bar on phones**, revealed once the main buy button scrolls out of
  view. On a paid-traffic product page this is the single highest-leverage mobile element.
- **The offer is reachable in about one thumb scroll.** A 100dvh hero that pushes price and
  Add to cart two screens down wastes the click the ad paid for (§2).
- **Tap targets ≥ 44px** — colour swatches especially, which default far smaller.
- **`srcset` + `sizes` on every image.** A phone must never download a desktop-width file;
  page weight is a conversion line item (§1) and mobile bandwidth is the constraint.
- **`env(safe-area-inset-bottom)` respected** so fixed elements clear the iPhone home
  indicator.
- **No horizontal overflow at 390px.**
- **Bottom padding reserved** so a sticky bar never covers footer or policy links.
- **Judged on a real phone**, not a resized desktop window (§5 already says this for
  checkout; it applies to the whole page).

Record the mobile decisions in the project's md files, not just in chat.

## 1. Theme

Pick for speed and trust, not features. A Shopify free theme (**Dawn** or **Refresh**) is the
correct default: officially maintained, fast, mobile-first, and it will not break on the next
Shopify update. Paid conversion themes buy you pre-built sections you can rebuild yourself and
a maintenance dependency you can't.

- **Mobile is the store.** Paid social traffic is overwhelmingly mobile. Design mobile-first
  and judge every page on a phone; the desktop view is a courtesy.
- **Page speed is a conversion line item.** Every app that injects script costs load time and
  therefore conversion. Audit installed apps quarterly and remove anything not earning its
  milliseconds.
- **Above-the-fold on mobile must contain the offer.** If a visitor has to scroll to learn
  what this is and what it costs, the ad's click has already been half wasted.

## 2. Product page structure

The product page is where the ad's promise is either kept or broken. Structure, in order:

**Above the fold (mobile):**
1. Product image — the hero shot, matching the ad creative. **Creative-to-page continuity is
   the highest-leverage CRO fix there is**: if the ad showed a specific angle/colorway and the
   page opens on something else, the visitor thinks they clicked wrong and leaves. That drop
   reads as "low CVR" in the diagnostician and gets misdiagnosed as an offer problem.
2. Product title — plain, benefit-forward, not SEO word salad.
3. Price + compare-at price (only if the compare-at is real; a fake anchor is a policy and
   trust problem).
4. Star rating + review count, linked to the reviews section.
5. 3–5 benefit bullets — outcomes, not specs.
6. Variant selector, then **Add to Cart** — visible without scrolling.
7. Shipping ETA and the guarantee, in text, right under the button. This is the single most
   effective placement for both.

**Below the fold, in this order:**
8. Benefit blocks — image + one claim each, mirroring the ad's Problem → Mechanism structure
   ([[dropship-four-triggers-ad-writer]]).
9. The mechanism explained — *why this works when what they tried didn't*.
10. Comparison table vs. the alternative they already tried.
11. FAQ — pre-handling shipping time, sizing, returns, and the top two support tickets.
12. Reviews with photos.
13. Guarantee restated + a second Add to Cart.

**Every claim on this page must be true and supportable.** Fabricated reviews, invented
statistics, and fake press logos are a merchant-account and ad-account risk, not a growth
tactic (see [[dropship-account-health]]).

## 3. Offer construction and AOV

[[dropship-meta-ads-diagnostician]] slider 10 demands **AOV ≥ 2× landed COGS** and says
nothing about how to get there. This is how.

The mechanism is almost never "raise the price." It is **raise the units or the value per
order** so ad spend is amortized across a bigger basket:

- **Volume tiers — the workhorse.** Buy 2 save 10%, Buy 3 save 20%. On a $30 product with $10
  landed COGS, a 2-unit order at $54 turns a 3× COGS-to-AOV ratio into a 2.7× on a much
  bigger absolute margin. Present tiers as a *selected default on the middle tier* — most
  buyers take the pre-selected option.
- **BOGO / B2G1** — reads as a bigger discount than it costs when COGS is a small fraction of
  price, and it's the structure competitor ad-spy most often reveals
  ([[dropship-adspy-method]] §6).
- **Bundles** — the hero product plus a genuinely complementary item. Bundle margin should be
  computed on the *bundle's* landed COGS, not the hero's.
- **Free-shipping threshold set just above current AOV** (~1.2–1.3×). It moves the basket
  without a discount and it removes the #1 cause of the ATC-to-Purchase drop (slider 9).
- **Discount codes last, always.** On thin margins a code turns a profitable order into a
  loss faster than any other lever ([[midas-craft]]). Fill carts with a better offer before
  you fill them with price.

**None of this can be evaluated today** — landed COGS and target margin are Unknown until the
context brief's block #2 is filled. State the structure, mark the math Unknown, and say what
input unblocks it.

## 4. Upsells

- **Pre-purchase (on the product page):** volume tiers, as above. Highest ROI, zero extra
  app friction.
- **In-cart:** a low-price complementary add-on. One, not a carousel.
- **Post-purchase one-click (after payment, before the thank-you page):** the best AOV lever
  in Shopify, because it cannot damage the primary conversion. The buyer has already paid;
  the offer either lands or it doesn't. Use a real complement at a real discount.
- **Do not put an upsell between the cart and the payment step.** Anything inserted there
  reads as a checkout obstacle and shows up as an ATC-to-Purchase drop.
- **Subscriptions / negative-option billing:** avoid entirely unless the operator explicitly
  wants it and understands the dispute exposure. Auto-renew surprises are a top chargeback
  cause.

## 5. Checkout configuration

Slider 9 (ATC → Purchase > 30%) is almost always a checkout or a surprise-cost problem, and
almost all of it is configuration:

- **Guest checkout on. Never force account creation.** This is the most common self-inflicted
  checkout kill.
- **Express payments enabled** — Shop Pay, Apple Pay, Google Pay, PayPal. On mobile paid
  traffic these carry a large share of conversions.
- **No surprise costs at step 3.** Shipping cost and any taxes must be knowable from the
  product page. A shipping charge that first appears at checkout is the classic ATC-to-Purchase
  killer.
- **Address autocomplete on**, phone field optional (a required phone field measurably drops
  mobile completion).
- **Abandoned-checkout recovery on** — first message ~1h, second ~24h. Factual, no invented
  scarcity.
- **Fraud filters reviewed, not ignored.** High-risk orders shipped are chargebacks in
  waiting ([[dropship-account-health]]).
- **Test the full checkout on a real phone, on cellular, with a real card**, and re-test after
  every theme or app change. Most "the ads stopped working" incidents are a checkout that
  broke and nobody checked.

## 6. Trust and social proof

- **Reviews must be real.** Imported supplier reviews that don't match the product, or
  generated reviews, are a policy risk and they read as fake to buyers. Photo reviews from
  actual customers outperform volume of text reviews.
- **A real contact route** — an email address that is monitored and a contact page. Meta and
  the payment processors both look for it, and so do buyers.
- **A real business address and business name** on the site, matching what's on the payment
  processor account. Mismatches are a review trigger.
- **Trust badges near the Add to Cart** — payment logos, guarantee, shipping ETA. Badges that
  make specific false claims ("FDA approved," fake certification marks) are worse than none.
- **Honest delivery windows everywhere.** This is a conversion element and a chargeback
  control at the same time ([[dropship-support-macros]]).

## 7. Required policy pages and domain

**Policy pages — required by Shopify Payments, by Meta's commerce policies, and by the
consumer-protection rules the processors enforce.** A missing or boilerplate-contradictory
policy page is a common cause of both an ad rejection and a payment-processor review:

- Refund / Return Policy — with the **actual** window and the **actual** process.
- Shipping Policy — with the **actual** processing time and transit windows, by region.
- Privacy Policy.
- Terms of Service.
- Contact page — monitored email, business name, address.

The refund and shipping policies must match what the product page, the ads, and the support
macros say. **Three different delivery promises across a store is how a dispute becomes
indefensible** — the customer just quotes whichever one you missed.

**Domain:** a custom domain, purchased and connected before running a dollar of traffic.
Never advertise a `myshopify.com` URL — it depresses trust and looks disposable to review
systems. Match the domain to the brand name in the context brief. **Verify the domain in Meta
Business Manager** — domain verification is required for aggregated event measurement and
gives you control of your own link previews.

---

## 8. Pixel and Conversions API — the section that makes every other number real

> Every CPA, ROAS, CVR, and ATC-rate in [[dropship-meta-ads-diagnostician]] and every kill or
> scale gate in [[dropship-ad-launch-sop]] is produced by this layer. **Those rubrics assume
> clean attribution and nothing in them says to check it.** This section is that check.

### 8a. Pixel install

- **One pixel per store**, installed via the official **Meta sales channel app** in Shopify —
  not hand-pasted into `theme.liquid`, which breaks on theme updates and misses checkout
  events.
- Required events: `PageView`, `ViewContent`, `AddToCart`, `InitiateCheckout`, `Purchase`.
- **`Purchase` must carry `value`, `currency`, and `content_ids`.** A Purchase event without a
  value makes ROAS meaningless — Meta optimizes toward conversions it cannot price, and every
  ROAS-based decision downstream is built on nothing.
- **Aggregated Event Measurement:** with the domain verified, configure the 8 prioritized
  events with `Purchase` at the top. iOS opt-out traffic is measured only through this
  configuration.

### 8b. Conversions API (CAPI) — not optional

Browser-only pixel loses a large and *unpredictable* share of events to iOS ATT opt-outs, ad
blockers, ITP cookie limits, and network failures. The loss is not random noise — it is
skewed toward exactly the mobile-app traffic paid social buys. Server-side CAPI recovers a
material share of it.

- Enable CAPI through the **Meta sales channel** in Shopify (simplest correct path) or a CAPI
  gateway. Both send purchase events server-side, where the browser can't drop them.
- Send **customer information parameters** (hashed email, phone, name, city, IP, user agent)
  with server events. These drive **Event Match Quality** — the score that determines whether
  Meta can attribute a server event to a person at all. A CAPI feed with poor match quality
  is CAPI in name only.
- **Target Event Match Quality: 6.0+** in Events Manager. Below ~5 the server events are
  attaching to far fewer people than you think and your recovered conversions aren't recovered.

### 8c. Deduplication — the trap

With both browser pixel and CAPI live, the **same purchase fires twice** — once from the
browser, once from the server. Without deduplication Meta counts both.

- Browser and server events for the same action **must share the same `event_id` and
  `event_name`**. That pair is the entire dedup mechanism.
- The Meta sales channel handles this automatically. **Any custom or app-based CAPI setup must
  be verified**, and a mixed setup (sales channel + a third-party CAPI app both firing) is the
  most common way stores end up double-counting.
- **Verify in Events Manager, don't assume:** the event should show both browser and server as
  sources with a *deduplicated* indicator, and there should be **no "duplicate events"
  diagnostic warning**. Check after every app install and every theme change.

**What double-counting does to the rest of this folder:** it roughly doubles reported
purchases, halves reported CPA, and doubles ROAS. Every gate in [[dropship-ad-launch-sop]]
then fires wrong — losers pass the Day-3 kill gate, and the scale gate green-lights raising
budget on an ad set that is losing money at twice the rate you think. **A dedup error is not
a reporting nuisance; it is a mechanism for scaling a loss.**

### 8d. Meta-reported ROAS ≠ Shopify revenue. Reconcile daily.

They will never match, and the *direction* of the gap tells you which problem you have:

| Observation | Likely cause | What to do |
|---|---|---|
| **Meta purchases > Shopify orders** | Dedup broken (§8c), or attribution overclaim — Meta counting purchases that would have happened without the ad (view-through, or click-attributed brand/repeat buyers). | Check dedup diagnostics first. If dedup is clean, it's attribution overclaim — stop underwriting scale on platform ROAS. |
| **Meta purchases < Shopify orders** | Tracking loss — CAPI missing or poor Event Match Quality, or the attribution window is shorter than the real consideration cycle. | Fix the tracking. Under-attribution makes you kill winners at the §3 gates. |
| **Meta ROAS healthy, bank account shrinking** | Platform ROAS ignores COGS, shipping, fees, and refunds entirely. | Use the blended number below. This one bankrupts stores that "scaled a 2.5 ROAS." |

**The reconciliation, run daily, in the brief:**

```
Meta reported purchases [window] : [N]   (Meta Ads Manager, pulled [date])
Shopify orders          [window] : [N]   (Shopify, same window)
Gap                              : [N] ([%])
```

**And the number that actually governs scale decisions — blended, not platform-reported:**

```
MER (blended ROAS) = total Shopify revenue [window] / total ad spend across all platforms [window]
contribution margin = Shopify revenue − landed COGS − shipping − fees − refunds − ad spend
```

MER cannot be gamed by attribution settings because it never asks which ad gets credit. It
is the number to underwrite a scale-up against. **Platform ROAS is a within-platform
optimization signal; blended MER and contribution margin are the truth**
([[dropship-evidence-discipline]]: revenue is not profit, and a metric without a source and a
window is a vibe).

### 8e. Standing rule for every ads read

Before Midas cites any CPA, ROAS, or CVR in a brief, he states the attribution setting and
window it came from (e.g. *7-day click / 1-day view*), and flags when Meta-reported purchases
and Shopify orders disagree by more than ~10%. **An unreconciled platform number is Unknown
wearing a number's clothes.** If the reconciliation can't be run — Shopify unkeyed, as it is
today — say so, and treat every platform figure as unverified rather than grounded.
