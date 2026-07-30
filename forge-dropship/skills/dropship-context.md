# 🛒 FORGE Dropship — Business Context (read this FIRST)

**Read this before doing any work on the dropship side of the dashboard.** This is the
source of truth for what the business is and what **Midas** is optimizing for. It has real,
honest gaps today (see "OWNER: FILL THIS IN") — don't fill them with invented facts.

*Last updated: 2026-07-26 — keep "Current Status" current, don't let it go stale.*

---

## Mission

Build a profitable dropshipping brand: find products people actually want, put them in
front of the right audience with paid traffic, and fulfill fast enough that customers stay
happy and the merchant + ad accounts stay healthy. Every plan gets judged against one
question: **would this survive an honest look at contribution margin after COGS, shipping,
fees, and ad spend?**

---

## Business Facts

- **Store:** **Everaly** — the storefront + system of record for orders, products,
  inventory.
  - Public domain: **everaly.com** (primary domain, SSL on, connected 2026-07-30)
  - Admin API domain: `pt4x1h-mf.myshopify.com` — this is what `SHOPIFY_STORE_DOMAIN`
    holds in `config/dropship.env`, and it stays the myshopify one even though the
    public domain is everaly.com.
  - AutoDS store id: `5654075`
  - Storefront is still **password protected**. Take the password off before running
    traffic; Meta cannot review a gated landing page.
- **Sourcing / fulfillment:** AutoDS — product sourcing, price/stock monitoring, order
  automation. Supplier costs and stock live here, not in a spreadsheet.
- **Paid traffic:** Meta (Facebook / Instagram) ads to start. TikTok is a planned add.
- **Competitor ad research:** Meta Ad Library (via Apify) + PiPiAds — read-only market
  signal, not a system of record for our own store.
- **Model:** test products cheaply, kill losers fast, scale the winners. Thin margins —
  so every decision runs on real cost inputs, never vibes.

---

## Current Status
*(this section expires fast — update it, don't trust it blindly)*

As of **2026-07-30**, honestly:

- **Shopify is keyed. 1 of 7.** `SHOPIFY_ADMIN_TOKEN` was filled and verified on
  2026-07-30 — `shop { name } = "Everaly"` over the Admin API, with all six scopes the
  dashboard reads (`products`, `orders`, `customers`, `locations`, `inventory`,
  `fulfillments`) returning real counts, not mocks. **Shopify reads are now grounded and
  may be cited with a source and window.**
  - Still blank: `AUTODS_API_KEY`, `AUTODS_MCP_TOKEN`, `META_ACCESS_TOKEN`, `APIFY_TOKEN`,
    `WINNINGHUNTER_API_KEY`, `WINNINGHUNTER_MCP_TOKEN`. Those reads still return the "add
    key" mock. **A brief built on mock data is fabrication** — say so rather than
    reasoning over it.
  - **`META_ACCESS_TOKEN` is now the one that unblocks the most.** Without it there is no
    CPA, no ROAS, and no ad half of the §8d reconciliation — so no scale or kill decision
    can be underwritten, however good the Shopify data is.
  - `dropship.env` is **gitignored on purpose**, so it does not travel with a `git push`.
    Filling it on the workstation does **not** fill it on the box — the same
    `SHOPIFY_ADMIN_TOKEN=` line still has to be copied to
    `/opt/forge/forge-dropship/config/dropship.env` and the service restarted, or the box
    keeps serving mock.
- **The store exists but has not sold anything.** Live as of 2026-07-30: Everaly on
  everaly.com with SSL, one product listed (The Sunday Set, $49.78, one variant —
  `Large / Dark Blue`, 10 units), and a custom single-product landing page serving both
  the homepage and the product URL. Still true: **no orders, no ad spend, no winners, no
  testing pipeline, and the storefront is password protected.** There is nothing to scale
  yet, and one variant cannot absorb paid traffic — every non-Large buyer bounces.
- **Midas has never produced a brief.** No `learn()` has run, so there is no vault playbook
  (`Skills/midas-playbook.md` does not exist yet) — the seed
  `forge-dropship/skills/midas-playbook.md` IS the live playbook until his first reflection
  writes the vault copy.
- **The scheduled brief is OFF by default** — `FORGE_DROPSHIP_BRIEF=0` in
  `/etc/default/forge-reios`. Deliberate: a daily Claude call over empty data is a daily bill
  for a fabrication. On-demand runs (chat, `/task`, `/api/dropship/director/run`, all three
  lanes) still work. Flip to `1` when Shopify connects.

**What this means for every dropship agent run right now:** until the blanks below are
filled and at least Shopify is keyed, most operating questions resolve to **Unknown**, and
the highest-value output is naming exactly which input would unblock the most decisions —
not a brief that reads like the store is running.

---

## What's Already Running

**One agent: Midas**, the head e-com director, running three lanes. (Hawk, Blaze and Otto
were retired 2026-07-25 — their rubrics became Midas's top skills, their data reads became
his methods, their routes became lane views onto his brief. Do not address them; they do not
exist.)

| Lane | What Midas does | Autonomy |
|------|-----------------|----------|
| **Daily brief** | Reads the whole store (Shopify, AutoDS, Meta, connected-systems health, this brief FIRST) → one ranked operating brief: Attention Now / Winners / Money / Ops / Ads / Delegations. | Read-only. Proposes. Self-improves. |
| **Product research** (`research`, `watch_score`) | Scores product ideas + the watchlist on margin headroom, demand signal, ad-ability, fulfillment sanity, saturation. Reads competitor ad signal (Meta Ad Library / PiPiAds). | Never sources, lists, or spends. Proposes only. |
| **Creative & ads** (`meta_overview`, `analyze_ads`) | Reads Meta campaign performance → scale / hold / kill / refresh, plus fresh ad concepts. | Never launches, never changes a budget. Recommends + drafts. |
| **Fulfillment & support** (`fulfillment_check`) | Order / inventory / tracking health + drafts customer replies. | Never places a supplier order, never messages a customer. Flags + drafts. |

---

## Standing Job For Midas

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

## Not Midas's Job

Wholesale lead screening, the AI agency, and daycare operations run on separate tracks —
see `forge-scout/skills/`, `forge-agency/skills/`, and `forge-daycare/skills/`.

---

## OWNER: FILL THIS IN

**These five blanks are the single input that unblocks the whole rubric stack.** Every
downstream skill tells Midas to judge products, margins, prices, copy, and delivery promises
against *this file* — so while they're blank, those rubrics have nothing to check against and
the honest answer to most questions is Unknown. Each one is a minute of typing. Replace the
`_______` with the real answer and delete the guidance line; Midas mtime-reloads on his next
run.

**1. Niche / brand + ICP.** ✅ **Filled 2026-07-30.**

> Niche: Women's sleepwear and loungewear. First listing is a two-piece button-down
> pajama set ("The Sunday Set", supplier brand Ekouaer) at $49.78.
> Brand name / positioning: **Everaly** — everaly.com. Quiet, considered loungewear for
> the hours that belong to you; editorial rather than discount-bin. Positioning comes
> through in the page voice, not in claims the supplier sheet cannot back.
> ICP: **working assumption, derived from the first product, not yet confirmed by the
> operator or by any sales data** — women roughly 25–45 who live in loungewear after
> 7pm: work-from-home, pregnant / postpartum / nursing, and shared-house or dorm
> households. They already own pajamas; the ones they own ride up, mark the waist, pill
> after three washes, or have no pockets. What they want is a set they would still be
> wearing when someone knocks on the door.

*Why it matters: the Four-Triggers ad writer opens on the Avatar. Blank = generic copy.*
*Confirm or correct the ICP before it is used to underwrite ad spend — it is inferred,
not given.*

**2. Target margin + price bands.** What are you underwriting to?

> Target contribution margin per order (after COGS + shipping + fees + ad spend): `_______`
> Typical retail price band: `_______`
> Typical landed COGS (product + ship + fees): `_______`
> Break-even CPA you'll accept: `_______`

*Why it matters: "profitable" is undefined without it, and the diagnostician's AOV ≥ 2×
COGS rule has no COGS to check against.*

**3. Current winners + testing pipeline.** Summarize the strategy; the live data is Shopify
+ the Ads tab, not this file.

> Current winners (product + why it wins): `_______`
> Products in test right now: `_______`
> How many new products you want tested per week: `_______`

**4. Brand voice** for customer-facing copy (support replies, ad copy).

> Voice in one line: `_______`
> Words/phrases to always use: `_______`
> Words/phrases to never use: `_______`

*Until this is filled, customer-facing drafts stay factual and neutral — no personality
invented.*

**5. Supplier / shipping realities.** The delivery windows you can actually keep.

> Real AutoDS supplier processing time: `_______`
> Real shipping transit time (by region): `_______`
> Delivery window promised on the store: `_______`
> Return / refund policy window: `_______`

*Why it matters: a support macro or ad that promises a window the supplier can't hit is how
chargebacks start. Midas must never quote a delivery time this block doesn't support — if
it's blank, he says "let me confirm your shipping timeline," never a number.*

---

## Related skills

The creed [[dropship-evidence-discipline]] outranks everything below it. Midas's top skills:
[[midas-decision-loop]], [[midas-craft]], [[dropship-four-triggers-ad-writer]],
[[dropship-meta-ads-diagnostician]], plus the operating SOPs
[[dropship-adspy-method]], [[dropship-ad-launch-sop]], [[dropship-store-setup]],
[[dropship-account-health]], [[dropship-support-macros]].
