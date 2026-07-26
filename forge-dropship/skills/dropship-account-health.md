---
agent: midas
skill: account-health
role: The survival runbook — the thresholds and the first hour when a processor or ad account is flagged
lane: ops (outranks every lane)
seed: true
priority: sop
---

# Account Health — the runbook for the things that end the store

[[dropship-evidence-discipline]] §5 says account health outranks the analysis.
[[midas-craft]] puts it first in the triage order. **Neither one states a number.** This
file is the numbers, and the response flow for the hour it matters.

The asymmetry that justifies the whole file: a bad ad set costs you a day of budget. A frozen
merchant account or a disabled ad account costs you **the business** — the revenue, the
learning, the pixel history, the customer list access, and often the ability to open a
replacement. There is no scaled winner worth a banned account, and the flags almost always
arrive *after* the behavior that caused them has been running for weeks.

> Midas **raises** these; he never pauses a campaign, issues a refund, files an appeal,
> contacts a processor, or delists a product. He does not need a second pass to raise an
> account-health risk — creed §5 explicitly exempts it. Every remedy below is a proposal
> (rule 2).

---

## 1. Chargeback rate — the hard ceiling

Chargeback (dispute) rate = **disputes ÷ transactions**, measured monthly. The card networks
run monitoring programs on it, and their thresholds are the real ceiling — not Shopify's
opinion, not yours.

| Band | Rate | Status | Action |
|---|---|---|---|
| **Healthy** | **< 0.5%** | Normal. | Monitor monthly. |
| **Watch** | **0.5% – 0.65%** | Approaching the network line. | Root-cause it now: delivery times, WISMO backlog, unclear descriptor, fraud filter off. Do not scale spend into it. |
| **Danger** | **0.65% – 0.9%** | At/over the Visa VDMP-class threshold. Processor review is likely. | **Stop scaling.** Treat as Attention Now in the brief. Fix fulfillment speed and support response before anything else. |
| **Critical** | **> 0.9% – 1.0%+** | Network monitoring program: per-dispute fines, remediation demands, possible termination. | Existential. Every other priority in the brief yields to this. |

The rate is a **lagging** indicator by 30–90 days — a dispute filed today came from an order
placed weeks ago. Two consequences: a rate that just crossed 0.5% reflects a problem that has
already been running, and a fix applied today won't show in the rate for a month. **Act on
the leading indicators instead:** WISMO ticket volume, orders past the promised delivery
window, and orders shipped without tracking uploaded ([[dropship-support-macros]]).

**Also watch absolute count, not just rate.** A store doing 100 orders/month with 1 dispute
is at 1% on a single case; the rate is noisy at low volume. Report both.

## 2. Refund rate

Refund rate = **refunded orders ÷ orders**. This one is yours to control and it is the
earliest honest signal that a product or a promise is wrong.

| Band | Rate | Read |
|---|---|---|
| **Healthy** | **< 5%** | Normal for dropship. |
| **Investigate** | **5% – 10%** | A product-quality, sizing, or expectation-setting problem. Find the pattern before scaling: which product, which reason code, which region. |
| **Stop scaling** | **> 10%** | The product or the delivery promise is broken. Scaling spend here multiplies the disputes 60 days out. |

**A refund is cheaper than a chargeback, always.** Refunding a complaint proactively costs
the order; letting it become a dispute costs the order *plus* a fee *plus* a point on the
metric that can end the store. When the two are close, refund. See the decision tree in
[[dropship-support-macros]].

**"One refund is one customer; two of the same complaint is a product problem"**
([[midas-craft]]). Track reason codes, not just totals — 15% refunds all citing "arrived
late" is a fulfillment fix; 15% all citing "not as described" is a listing or ad-claim
problem, and the ad claim is the more dangerous of the two.

## 3. Shopify Payments reserves

A reserve is the processor withholding a percentage of payouts (rolling reserve) or a fixed
sum, to cover future disputes. It is not a ban, but it is a cash-flow event that can stop a
store that's funding ad spend from revenue. **Triggers:**

- **Sudden revenue spike** far outside the store's history — the classic dropship trigger. A
  new store going from $500/day to $10k/day looks identical to fraud from the processor's
  side.
- **High or rising dispute rate** (§1).
- **High refund rate** (§2).
- **Long fulfillment lead times** — the processor's exposure is the window between charge and
  delivery. Long transit times mean a long liability tail.
- **Orders shipped without tracking**, or tracking uploaded late.
- **New store, no processing history**, especially in a high-risk category.
- **Business details that don't match** — name, address, or bank details inconsistent with the
  store or the entity.

**Posture that reduces the risk:**
- Upload tracking **immediately** on fulfillment; it is the single most effective reserve and
  dispute control.
- Scale revenue in steps the processor can watch. A step-change looks like fraud; a ramp looks
  like a business.
- Keep the payment descriptor recognizable as the store name — an unrecognized descriptor is
  a direct cause of "I don't recognize this charge" disputes.
- Keep 2–3 weeks of ad spend in cash outside the processor. **A reserve you can survive is an
  inconvenience; a reserve you can't is the end.**

## 4. Meta — policy review, rejection, and restriction

Three distinct states, three different responses. Confusing them is how operators escalate a
rejected ad into a disabled Business Manager.

**(a) Ad rejected.** Routine. Read the **specific policy cited** in the rejection.
- Fix the actual violation and republish. Do **not** resubmit unchanged, and do not appeal by
  reflex — repeated appeals on genuine violations count against the account.
- Most common causes in this business: personal-attribute assertions ("Do you have…"),
  before/after imagery, health/medical claims, unsubstantiated claims, and a landing page
  that doesn't match the ad. [[dropship-four-triggers-ad-writer]] has the compliance rules.

**(b) Ad account restricted / disabled.**
- Go to **Account Quality** in Business Manager. Read the stated reason.
- **File one clear appeal.** State what changed. One appeal, not five.
- **Do NOT create a new ad account, new Business Manager, or new profile to keep spending.**
  Meta links assets by payment method, IP, device, domain, page, and pixel. Evasion converts a
  restricted ad account into a permanently banned Business Manager and takes the page, the
  pixel history, and any connected asset with it. **This is the single most damaging mistake
  available in this section.**
- While restricted: pause nothing you can't afford to lose; export what you can; do not
  churn assets.

**(c) Page or Business Manager restricted.** The serious one — it takes the pixel and the
ad accounts with it. Same rule: one appeal, no evasion, no new asset creation.

**Standing hygiene that prevents most of this:** verified domain, a real page with real
history, a payment method in the business's name, landing pages that say what the ad says,
and no claims the store can't support.

## 5. The first hour after a flag

When a merchant account or ad account is flagged, in this order. Midas produces this as a
checklist for the operator; he executes none of it.

1. **Read the actual notice.** The exact reason, the exact policy or program named, the exact
   deadline. Not the summary email — the notice in Account Quality or the processor dashboard.
   Half of all panic responses are to a misread.
2. **Stop the bleeding, not the business.** If it's a dispute-rate flag, the priority is
   fulfillment and support throughput, not turning off ads. If it's an ad-policy flag on one
   product, pause that product's ads — not the account.
3. **Preserve access to what you'd lose.** Export the customer list, the order history, the
   creative library and ad copy, and the product data. Do it in the first hour, while access
   is certain. A banned asset takes its data with it.
4. **Write the timeline.** What changed in the 30 days before the flag — new product, new
   claim, new supplier, a revenue step-change, a shipping delay. This is both the root cause
   and the substance of any appeal.
5. **One appeal, factual, specific.** What happened, what you changed, what prevents it
   recurring. No boilerplate, no volume.
6. **Switch to the backup posture** (§6) if revenue is actually blocked — do not improvise a
   new account under pressure.
7. **Tell the customers before they tell the bank.** If fulfillment or refunds are affected,
   proactive factual contact prevents the dispute wave that turns a flag into a termination
   ([[dropship-support-macros]]).

**What not to do, in the first hour or ever:** create an evasion account, dispute the flag
publicly, mass-refund in panic (a refund spike is itself a processor trigger), or delete the
evidence of what happened.

## 6. Backup posture — set up before you need it

All of this is legitimate redundancy, not evasion. The distinction is that these are
**disclosed, real, separate** — not duplicates created to circumvent an enforcement action.

- **A second payment processor**, live and tested, on the same legal entity — PayPal alongside
  Shopify Payments, or a second gateway. A store with one processor is one review away from
  zero revenue.
- **A second ad account inside the same Business Manager**, created in good standing, with its
  own payment method. Legitimate; a *new Business Manager after a ban* is not.
- **Cash reserve** — 2–3 weeks of ad spend outside the processor, so a rolling reserve doesn't
  stop the campaigns.
- **Owned assets:** the customer email/SMS list exported on a schedule, the domain in your own
  registrar account, and the creative library + winning ad copy stored in the brain vault. A
  platform can take your account; it cannot take your list, your domain, or your creatives.
- **Documentation ready in advance:** supplier invoices, fulfillment records, business
  registration. Processor reviews ask for these on a deadline, and assembling them under a
  72-hour clock is how stores fail reviews they'd otherwise pass.

## 7. The categories and claims that get merchants killed

Screen every product candidate against this list **before** the margin math, not after — a
product that fails here is not a product, whatever its margin ([[dropship-adspy-method]] §4).

**Hard stops:**
- **IP infringement** — branded goods, character/franchise merchandise, team logos, dupes and
  "inspired by" versions of a designer product. This is the most common cause of a dropship
  store's death: it triggers takedowns, processor termination, *and* actual legal liability,
  and one complaint is enough.
- **Counterfeits** of any kind.
- **Weapons, weapon accessories, tactical items** that trip Meta's prohibited list.
- **Adult products.** Whatever the margin.
- **Anything requiring a license we don't hold** — pharmaceuticals, regulated devices,
  nicotine/CBD, financial products.

**Claim traps — the product may be fine and the claim kills the account:**
- **Health / medical claims.** "Cures," "treats," "eliminates," "clinically proven." Benefits
  must be framed as supportive, never curative.
- **Weight-loss claims and before/after imagery.** Meta's personal-health policies restrict
  both; before/after body imagery is a reliable rejection and a repeated-violation risk.
- **Personal-attribute assertions** — "Do YOU have hair loss?" Situation-first phrasing
  instead ([[dropship-four-triggers-ad-writer]] Trigger 1).
- **Fabricated proof** — invented statistics, fake clinical studies, fake press logos, fake
  scarcity ("only 3 left" when untrue), generated reviews. All of it is an account risk and
  none of it is worth the lift.
- **Subscription / negative-option billing** without unmistakable disclosure. Auto-renew
  surprises are a top dispute driver and a processor red flag.

**The screening rule:** if a product needs a claim from this list to sell, the *angle* is
wrong or the *product* is wrong. Say so, and say which. There is always another product;
there is not always another merchant account.

---

## 8. What Midas reports

Account health leads the brief whenever any band above is breached — ahead of winners, ahead
of a scale-up, on the first pass, without a second look:

```
**⚠ ACCOUNT HEALTH — [merchant / ad account]**
Grounded: [metric] = [value] over [window] ([source], pulled [date]) — band: [Watch/Danger/Critical]
Leading indicators: [WISMO volume / orders past promised window / untracked shipments]
Likely cause (ranked, falsifiable): 1) [..] → proved wrong by [..]  2) [..]  3) [..]
Proposal: [the specific remedy, and what it costs]
If nothing changes: [the concrete consequence and its rough timing]
```

If a figure isn't reachable — as today, with no processor or store integration keyed — it is
**Unknown**, and finding it out is itself a top-priority item. An unmeasured dispute rate is
not a healthy one.
