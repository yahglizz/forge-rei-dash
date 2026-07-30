# Everaly — store ↔ dashboard wiring

*Last updated 2026-07-30. Companion to [[dropship-context]]; that file is the business
brief, this one is the plumbing.*

---

## 1. Identity

| | |
|---|---|
| Brand / company | **Everaly** |
| Public domain | **everaly.com** — primary domain, SSL enabled, connected 2026-07-30 |
| Shopify shop name | `Everaly` |
| Admin API domain | `pt4x1h-mf.myshopify.com` |
| Shopify admin | https://admin.shopify.com/store/pt4x1h-mf |
| AutoDS store id | `5654075` |
| Storefront state | **Password protected** — take it off before running traffic |

`SHOPIFY_STORE_DOMAIN` stays the **myshopify** domain even though the public domain is
everaly.com. The Admin API is addressed by the myshopify host; everaly.com is only the
customer-facing name.

## 2. Catalogue

One product. One variant. That is the whole store today.

| | |
|---|---|
| Product | The Sunday Set — `gid://shopify/Product/9284974674146` |
| Handle | `womens-pajamas-long-sleeve-loungewear-casual-button-down-pjs-…-postpartum` |
| Price | $49.78, no compare-at |
| Variants | 1 — `Large / Dark Blue`, 10 units |
| Vendor | `Ekouaer` (supplier brand — correct, not the store brand) |

Full packet, including the eight unverified facts that still gate the page:
[`products/the-sunday-set.md`](products/the-sunday-set.md).

**One variant is the live constraint on paid traffic.** Every buyer who is not a Large
bounces. Import the remaining sizes and colourways from AutoDS before spending.

## 3. Themes

| Theme | Id | Role |
|---|---|---|
| `A Touch of Blessing — Sunday Set (mobile)` | `161462583522` | draft — mobile pass + Everaly brand, **publish this** |
| `A Touch of Blessing — Sunday Set` | `161461960930` | **live** |
| `Helio — Sunday Set (draft)` | `161461108962` | superseded, safe to delete |
| `Helio` | `161409630434` | original stock theme, keep as the rollback |

The custom page is one section, `sections/sunday-set-pdp.liquid`, rendered by both
`templates/index.json` (homepage) and `templates/product.womens-pajamas-long-sleev.json`.
Price, compare-at, colours, sizes, stock, currency and cart count all read from the live
Shopify product — nothing about the offer is hardcoded.

**Theme code lives in Shopify, not in this repo.** It is not covered by the git sync
below. To change it, edit the draft theme through the Admin API or the theme editor and
publish; writes against the live theme are blocked by policy.

## 4. Dashboard connection — what is done, what is not

**Done.** Non-secret config in `config/dropship.env` is correct:

```
SHOPIFY_STORE_DOMAIN=pt4x1h-mf.myshopify.com
SHOPIFY_API_VERSION=2026-07
AUTODS_STORE_ID=5654075
```

**Not done — this is the blocker.** `SHOPIFY_ADMIN_TOKEN` is empty, so every dropship read
in the dashboard still returns the "add key" mock. Until it is filled, Midas cannot see
orders, products or inventory, and the Shopify half of the MER reconciliation in
[[dropship-store-setup]] §8d cannot run. **A brief written over mock data is fabrication.**

### Filling it (operator only — do not hand the token to an agent or paste it in chat)

1. Shopify admin → **Settings → Apps and sales channels → Develop apps → Create an app**.
2. Name it `Forge Dashboard`. Configure **Admin API scopes**, read-only is enough to start:
   `read_products`, `read_inventory`, `read_orders`, `read_fulfillments`,
   `read_customers`, `read_locations`.
3. **Install app**, then reveal the **Admin API access token** once (`shpat_…`).
4. Paste it into `forge-dropship/config/dropship.env` on the workstation:
   `SHOPIFY_ADMIN_TOKEN=shpat_…`
5. Repeat on the box at `/opt/forge/forge-dropship/config/dropship.env`, then
   `systemctl restart forge-reios`.
6. Flip `FORGE_DROPSHIP_BRIEF=1` in `/etc/default/forge-reios` once the read works — the
   daily brief is deliberately off while the store has no data.

**`dropship.env` is gitignored.** It does not travel with `git push`. Filling it here does
not fill it on the box or the Mac; each machine needs its own copy. That is deliberate —
secrets stay off GitHub.

Still empty besides Shopify: `AUTODS_API_KEY`, `AUTODS_MCP_TOKEN`, `META_ACCESS_TOKEN`,
`APIFY_TOKEN`, `WINNINGHUNTER_API_KEY`, `WINNINGHUNTER_MCP_TOKEN`.

## 5. Sync — how this repo reaches GitHub, the box and the Mac

One mechanism: **git**. There is nothing else to run.

```
workstation ──auto-sync commit+push──> GitHub (yahglizz/forge-rei-dash, main)
                                          │
                                          ├── box: autopull.sh, 60s systemd timer,
                                          │   90s debounce, then deploy-pull.sh
                                          │   (validate → sync → restart → health)
                                          │
                                          └── MacBook: same auto-sync daemon pulls
```

- The box is the DigitalOcean droplet `forge-reios`, `24.199.81.124`, Tailscale
  `100.87.232.91`, dashboard at `http://100.87.232.91:7799`.
- **A push is the deploy.** No SSH needed for code. Only the env file needs hands.
- If a commit fails validation, `deploy-pull.sh` aborts and the running version stays up.
- Do not edit files directly on the box; the next pull overwrites them.

## 6. Open items

1. **Fill `SHOPIFY_ADMIN_TOKEN`** on the workstation and the box. Nothing else in the
   dropship lane is real until this is done.
2. **Publish theme `161462583522`** — mobile pass plus the Everaly rename.
3. **Check the page on a real phone.** The mobile layout has not been rendered at phone
   width by anything but code review.
4. **Import the remaining variants** from AutoDS.
5. **Remove the storefront password** before any ad spend.
6. **Fill blocks 2–5 of [[dropship-context]]** — margin, COGS, shipping windows, returns
   window. The eight unknowns in the product packet are mostly the same inputs.
7. Delete the two superseded themes once the mobile one is live.
