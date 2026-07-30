---
product_gid: gid://shopify/Product/9284974674146
admin_url: https://admin.shopify.com/store/pt4x1h-mf/products/9284974674146
source: AutoDS import
brand: Ekouaer
status: ACTIVE
currency: USD
packet_written: 2026-07-30
rubrics_applied:
  - forge-dropship/skills/dropship-store-setup.md (§2 product page structure, §3 AOV, §6 trust)
  - forge-dropship/skills/dropship-four-triggers-ad-writer.md (Avatar → Problem → Mechanism → Offer)
  - forge-dropship/skills/dropship-evidence-discipline.md (no invented facts)
---

> **Brand: Everaly** (everaly.com). Canonical copy — this file is the synced one.
>
> Store and dashboard wiring: `../EVERALY_STORE.md`.

# Ekouaer Women's Button-Down Pajama Set — product page packet

## 1. Live Shopify data (source of truth, pulled 2026-07-30)

| Field | Value |
|---|---|
| Product ID | `gid://shopify/Product/9284974674146` |
| Original AutoDS title | `Women'S Pajamas Long Sleeve Loungewear Casual Button down Pjs \| Soft Sleepwear,Notch Collar,Elastic Waist Pants with Side Pockets,Adjustable Drawstring,Pajama Party,Maternity,Postpartum` |
| Vendor | My Store (should be `Ekouaer` — supplier brand) |
| Product type | *(empty — set it)* |
| Tags | *(none)* |
| Variants | 1 — `Large / Dark Blue`, SKU `39c5493b-3a4c-40cd-9ccc-1a589b1d8200` |
| Price | $49.78 |
| Compare-at | none |
| Inventory | 10 |
| Images | 5 (Shopify CDN, `files/1/0826/6049/1490/`) |

Featured image: `da46e16d938bcf0f3cf3515999e33076.jpg`

## 2. Verified product facts

Only claims traceable to the supplier listing. Everything here is safe to print on the page.

- Two-piece set: long-sleeve top + long pajama pants
- Top: notch collar, button-front placket, one chest pocket
- Pants: two side pockets, elastic waist with adjustable chiffon drawstring
- Lightweight, soft, described by supplier as loungewear/sleepwear weight
- Positioning: sleep, lounge, pajama parties, dorm, family photos, gifting
- Brand: Ekouaer

## 3. UNKNOWN — do not print until confirmed

These are the gaps that block a fully closed page. Each maps to a blank in
`forge-dropship/skills/dropship-context.md`.

| Unknown | Why it matters | Where to get it |
|---|---|---|
| **Fabric composition** | Supplier blurb says both "premium fabric" and "cashmere" — contradictory and unverifiable. Printing "cashmere" on a $49.78 dropship pajama is a misrepresentation + chargeback risk. | AutoDS supplier listing spec sheet |
| **Size chart numbers** | Supplier ships a size-chart image; no measurements in text. Sizing is the #1 apparel return driver. | AutoDS listing image / supplier |
| **Real processing + transit time** | Store-setup §7: three different delivery promises across a store makes a dispute indefensible. | AutoDS supplier processing + shipping method |
| **Return window** | Must match the Shopify refund policy page verbatim. | Your own policy decision |
| **Landed COGS** | Without it, margin at $49.78 is Unknown and no AOV tier can be underwritten (§3). | AutoDS product cost + shipping |
| **Reviews** | Zero real reviews. Imported/generated reviews are a policy risk (§6). Page ships without a rating block. | Real orders only |
| **Compare-at price** | A fake anchor is a trust + policy problem. Leave empty unless there is a real prior price. | N/A |
| **More sizes/colors** | Only `Large / Dark Blue` exists. Ad traffic sent to a one-size page burns clicks from every other size. | AutoDS — import remaining variants |

## 4. Avatar → Problem → Mechanism → Offer

Framework: `dropship-four-triggers-ad-writer.md`. This drives both the page copy and any ad.

**Avatar** — women 25–45 who live in their loungewear after 7pm: WFH, new moms and
postpartum, dorm/roommate households. Someone who owns pajamas but keeps reaching for
the same beat-up t-shirt and leggings.

**Problem (one layer deep)** — the drawer is full of pajamas that failed for specific
reasons: shorts sets that ride up, tight waistbands that leave a mark, fabric that pills
after three washes, pants with no pockets so the phone gets carried room to room. Surface
problem is "nothing comfortable to sleep in." Real problem is nothing she'd answer the
door in.

**Mechanism** — the classic button-down cut done with the two details that make a set
livable: an adjustable drawstring over elastic waist (fits a body that changes — bloat,
pregnancy, postpartum, weight shifts) and real side pockets on the pants. Button front
means it opens flat — the reason nursing and postpartum wearers pick button-downs over
pullovers.

**Offer** — no discount code. Per store-setup §3, discounts come last on thin margins.
Recommended, **pending landed COGS**:
- 2-set volume tier (second set at a lower unit price) — needs COGS to price
- Free-shipping threshold set ~1.2–1.3× current AOV
- Guarantee tied to the actual problem: fit/comfort return window — needs the real window

Do not launch a tier or a guarantee number until §3 unknowns are filled.

## 4b. The Sunday Set landing page (theme build, 2026-07-30)

The design in `~/Downloads/Shopify product website design/Sunday Set.dc.html` is now a real
Shopify product template.

| Thing | Value |
|---|---|
| Draft theme | `Helio — Sunday Set (draft)` — `gid://shopify/OnlineStoreTheme/161461108962` |
| Section | `sections/sunday-set-pdp.liquid` |
| Template | `templates/product.womens-pajamas-long-sleev.json` (the suffix the product already pointed at) |
| Live theme | `Helio` (161409630434) — **untouched** |
| Images | `sunday-set-front.png`, `sunday-set-lifestyle.png`, `sunday-set-back.png` uploaded to Shopify Files |

Nothing about the offer is hardcoded. The section reads price, compare-at, colour values,
size values, per-variant stock, currency and cart count from the Shopify product, so
importing more AutoDS variants makes swatches and sizes appear with no code change.
Sold-out sizes strike through and disable themselves. Add to bag posts to
`/cart/add` over fetch and falls back to a normal form post without JS.

**Changed from the design, and why:**

| Design said | Shipped as | Why |
|---|---|---|
| `★★★★★ 214 reviews` | removed | Zero real reviews. Fake review markup is a manual-action and merchant-account risk. |
| `Free shipping over $75 · 30-day returns · Ships in 1–2 business days` | links to Shipping Policy and Returns | None of those three numbers is confirmed (§3). |
| `92% brushed viscose / 8% spandex` | "composition is on the garment label" | Supplier blurb says both "premium fabric" and "cashmere". Unverifiable. |
| `30" inseam`, mother-of-pearl buttons | removed | Not in the supplier spec. |
| Price $48, compare-at $64 | live variant price, compare-at hidden | Real price is $49.78 and there is no real compare-at. A fake anchor is a policy problem. |
| Two colorways: Heather Navy + Midnight Black | one swatch, from Shopify | **No black variant exists.** The three `-black` images in the design folder are AI recolors (`ChatGPT Image ...png` in `uploads/`). The three navy images are the real supplier photos and are the ones uploaded. |
| Six sizes XS–2X | Large only, from Shopify | Only `Large / Dark Blue` exists. |
| Remote webfont from `db.onlinewebfonts.com` | system Helvetica stack | Third-party font blocks render; page speed is a conversion line item. |
| — | added JSON-LD Product | SEO. No `aggregateRating`, for the reason above. |

Colour naming: the swatch prints Shopify's real option value, `Dark Blue`. If you want the
brand name on the page, rename the option value to `Heather Navy` in the product — then the
page, cart and order confirmation all agree. The section already maps both names to
`#4a5670`.

**Verified in the theme editor:** template resolves, section renders, schema settings load,
hero matches the design, theme header/footer hidden, CTA reads `SHOP THE SET — $49.78` from
live data.

**Not yet verified:** everything below the hero (buy block, story, details, closing) and a
real add-to-cart. The storefront is password-protected and the theme editor blocks
programmatic scrolling in its preview iframe, so this needs a human scroll.

## 4c. Mobile optimisation (2026-07-30)

**Standing rule from the operator: every Shopify page here is mobile-optimised in the same
build that creates it, never as a follow-up.** This store sells almost entirely to mobile
paid social, so the phone layout is the real layout and desktop is the courtesy view. The
rule is also written into `forge-dropship/skills/dropship-store-setup.md` §0.

What the section does on phones (`@media (max-width:900px)`):

| Area | Mobile behaviour |
|---|---|
| **Sticky buy bar** | Fixed bottom bar with title, live price and Add to bag. Revealed by an IntersectionObserver once the main Add to bag scrolls out of view. Submits the same form via the `form=` attribute, so there is one cart path, not two. |
| **Hero** | Height auto instead of `100dvh`; nav collapses to one wrapped row; marquee 16vw; product shot 44vh; CTA full width. Price and Add to bag land about one thumb scroll in instead of two screens down. |
| **Tap targets** | Swatches 34px → 44px, size buttons 48px min-height, qty buttons and both Add to bag buttons 52px. |
| **Images** | `srcset` at 400/800/1200 with `sizes="(max-width:900px) 100vw, …"` on hero, gallery, story, back view and size chart. Phones stop pulling desktop-width files. |
| **Safe area** | Sticky bar padding uses `env(safe-area-inset-bottom)` for the iPhone home indicator. |
| **Overflow** | `overflow-x:hidden` on the root; the marquee is the only intentionally wide element and it sits in a clipped wrapper. |
| **Footer clearance** | Closing section gets 104px bottom padding so the sticky bar never covers the policy links. |
| **Toast** | Repositioned above the sticky bar instead of behind it. |
| **Misc** | `touch-action:manipulation` and transparent tap highlight on every control; `prefers-reduced-motion` already stops the marquee. |

**Verified:** desktop, on the live storefront — hero, buy block, story, details, closing,
real `$49.78`, Large-only, working Add to bag (cart reached 1 item).

**Not verified:** the phone rendering itself. Chrome's window resize did not change the
rendered viewport through the automation bridge, and the storefront password blocks loading
the page in the in-app browser. **Open it on an actual phone and check the sticky bar
appears, the hero is not too tall, and nothing scrolls sideways.**

## 5. Page structure shipped to Shopify

Order follows `dropship-store-setup.md` §2. Above-the-fold items 1–7 (image, title, price,
variant selector, Add to Cart) are rendered by the **theme**, not the description — the
description body starts at the benefit block.

1. Hero image — matches ad creative *(theme)*
2. Plain benefit-forward title *(updated)*
3. Price, no fake compare-at *(theme)*
4. ~~Star rating~~ — **omitted, no real reviews**
5. Benefit bullets — in description
6. Variant + Add to Cart *(theme)*
7. Shipping ETA + guarantee under the button — **blocked on unknowns; add via theme block once confirmed**
8. Benefit blocks mirroring Problem → Mechanism ✅
9. Mechanism explained ✅
10. Comparison vs. the pajamas she already owns ✅
11. FAQ — sizing, fit, care, shipping (shipping answer points to policy page, no invented number) ✅
12. ~~Photo reviews~~ — omitted, none real
13. Guarantee restated — **points to policy page, no invented window**

## 6. Recommended title

Old (AutoDS keyword salad, 200+ chars):
> Women'S Pajamas Long Sleeve Loungewear Casual Button down Pjs | Soft Sleepwear,Notch Collar,...

New:
> Ekouaer Women's Button-Down Pajama Set — Long Sleeve Top + Pants with Pockets

Keywords that got dropped from the title (maternity, postpartum, pajama party, notch
collar, drawstring) are all preserved in the body copy and tags, where they belong.

## 7. Tags to apply

`pajama set`, `womens sleepwear`, `loungewear`, `button down pajamas`, `long sleeve pajamas`,
`pajamas with pockets`, `maternity`, `postpartum`, `nursing friendly`, `gift`, `ekouaer`

## 8. SEO

- **Title:** Ekouaer Women's Button-Down Pajama Set | Long Sleeve Loungewear
- **Description:** Soft two-piece button-down pajama set — long sleeve notch-collar top with chest pocket, elastic drawstring waist pants with real side pockets. Maternity and postpartum friendly.

## 9. Open actions for the operator

1. Fill the eight unknowns in §3 (fabric + shipping window are the two that gate the page closing).
2. Import remaining sizes/colors from AutoDS — one variant kills paid traffic economics.
3. Change vendor `My Store` → `Ekouaer`, set product type `Pajama Sets`.
4. Add shipping ETA + guarantee as a theme block directly under Add to Cart (§2 item 7).
5. Compute landed COGS, then set the volume tier and free-shipping threshold.
6. Do not import supplier reviews.
