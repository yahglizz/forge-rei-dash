# 🛒 FORGE Dropship — Business Context (read this FIRST)

**Read this before doing any work on the dropship side of the dashboard.** This is the
source of truth for what the business is and what Midas / Hawk / Blaze / Otto are
optimizing for. It has real, honest gaps today (see "Needs Your Input") — don't fill them
with invented facts.

*Last updated: 2026-07-15 — keep "Current Status" current, don't let it go stale.*

---

## Mission

Build a profitable dropshipping brand: find products people actually want, put them in
front of the right audience with paid traffic, and fulfill fast enough that customers stay
happy and the merchant + ad accounts stay healthy. Every plan gets judged against one
question: **would this survive an honest look at contribution margin after COGS, shipping,
fees, and ad spend?**

---

## Business Facts

- **Store:** (your Shopify store) — the storefront + system of record for orders,
  products, inventory. Fill `SHOPIFY_STORE_DOMAIN` in `config/dropship.env`.
- **Sourcing / fulfillment:** AutoDS — product sourcing, price/stock monitoring, order
  automation. Supplier costs and stock live here, not in a spreadsheet.
- **Paid traffic:** Meta (Facebook / Instagram) ads to start. TikTok is a planned add.
- **Model:** test products cheaply, kill losers fast, scale the winners. Thin margins —
  so every decision runs on real cost inputs, never vibes.

---

## Current Status
*(this section expires fast — update it, don't trust it blindly)*

- Integrations are live-or-mock depending on whether keys are filled in `dropship.env`
  (`SHOPIFY_ADMIN_TOKEN`, `AUTODS_API_KEY`, `META_ACCESS_TOKEN`). Check the Products /
  Orders / Ads tabs for real connection status rather than assuming.
- No product roster or winner list is documented here yet — the live source is Shopify +
  the dashboard tabs once connected.

---

## What's Already Running

- **Midas** reads the whole store and produces a ranked operating brief — nothing outward
  ships without your approval.
- **Hawk** scores product ideas and hunts winners against real ad/sales signal.
- **Blaze** reads Meta ad performance against healthy-range benchmarks and drafts new ad
  concepts — never spends on its own.
- **Otto** watches fulfillment (undelivered orders, stockouts, tracking) and drafts
  customer support replies — never messages a customer or places a supplier order himself.

---

## Standing Job For This Crew

1. **Read metrics against a meaningful window** — not 6 hours of ad data. Every number a
   dropship agent cites carries its source and date range, or is marked Unknown.
2. **Margin is truth, revenue is vanity.** Never call a product a winner, or recommend
   scaling it, without contribution margin computed from real cost inputs.
3. **Protect the accounts.** Fulfillment speed, honest delivery times, and responsive
   support keep chargebacks/refunds down — which keeps the Shopify Payments / Stripe /
   PayPal merchant account and the Meta ad account alive. Treat account health as
   existential.
4. **Never spend, launch, publish, order, or message without the operator's approval.**

---

## Not This Crew's Job

Wholesale lead screening, the AI agency, and daycare operations run on separate tracks —
see `forge-scout/skills/`, `forge-agency/skills/`, and `forge-daycare/skills/`.

---

## Needs Your Input To Stay Accurate

These facts genuinely don't exist anywhere in the codebase yet:

- **Niche / brand.** What does the store sell, and to whom (the ICP)? Fill this in once the
  store's positioning is set.
- **Target margin + price bands.** What contribution margin are you underwriting to, and
  what's the typical product price / COGS / shipping? Hawk and Midas need this to judge
  "profitable."
- **Current winners + testing pipeline** — the live source is Shopify + the Ads tab; this
  file should summarize the strategy, not replace the data.
- **Brand voice** for customer-facing copy (support replies, ad copy). Define one once
  there's enough real work to generalize from — until then Otto stays factual + neutral.
- **Supplier / shipping realities** — real AutoDS supplier lead times and the delivery
  windows you promise on the store. Otto must never quote a delivery time the store and
  supplier don't support.
