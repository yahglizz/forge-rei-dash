# FORGE Dropship — End-to-End Setup Checklist

**Goal:** a 24/7 automated Shopify + AutoDS + Meta-ads store where Midas researches products,
watches competitor ads, finds winners, tells you exactly how to run the ads, and you tap to execute.

**Status as of 2026-07-30:** plumbing is real, **store identity is now real, tokens are not.**
`forge-dropship/config/dropship.env` **exists** on the box (chmod 600, 404s over HTTP) carrying
values VERIFIED against the live vendor APIs:

| Fact | Value | How verified |
|------|-------|--------------|
| Shopify store | `pt4x1h-mf.myshopify.com` — "My Store", **Basic**, USD, America/New_York | Shopify Admin API (`shop` query) |
| Storefront launched? | **No — password protection ON** | `onlineStore.passwordProtection.enabled = true` |
| Storefront MCP | `https://pt4x1h-mf.myshopify.com/api/mcp` — seeded, `configured: true`, currently **401** | direct probe; the 401 IS the password wall |
| AutoDS store | id **5654075** ("pt4x1h mf"), site 3 = Shopify, active, linked to the store above, 0 listings | AutoDS API `list_stores_api` |

Still **0 of 7 systems CONNECTED** — every health endpoint returns an honest `configured: false`
because no token is pasted yet. Two blanks are the whole gap: `SHOPIFY_ADMIN_TOKEN` and an AutoDS
credential. `marcus_state/midas.json` does not exist — **Midas has never produced a brief.** The
scheduled loop stays default OFF (`FORGE_DROPSHIP_BRIEF=0`, `/etc/default/forge-reios`).

**AutoDS auth — decided 2026-07-30.** Their OAuth metadata is now confirmed live:
`https://mcp.autods.com/.well-known/oauth-authorization-server` advertises
`grant_types_supported: [authorization_code, refresh_token]`, PKCE `S256`, an open
`registration_endpoint`, and `token_endpoint_auth_methods_supported: ["none"]` (public client).
So the ~1h token expiry is **solvable in code**: register once, one browser PKCE consent, store the
**refresh token** in `dropship.env`, and mint access tokens on the box on demand. Pasting a raw
`AUTODS_MCP_TOKEN` by hand is a 1-hour connection and not worth doing twice.

Rule 2 holds throughout: Midas **proposes**, you tap. Nothing below makes an agent spend money,
launch an ad, order from a supplier, edit a listing, or message a customer on its own.

---

## Phase 0 — Owner decisions (blocks everything downstream)

These five blanks live in `forge-dropship/skills/dropship-context.md` — the FIRST file every
dropship prompt reads. Until they're filled, every rubric that says "never contradict the target
margin / price band / niche" is ungrounded by construction, and "is this a winner?" is unanswerable.

- [ ] **Niche / ICP** — what we sell and who buys it. One paragraph.
- [ ] **Target contribution margin + price bands** — e.g. "≥55% after COGS+ship, sell $39–$89".
- [ ] **COGS + shipping assumptions** — what a unit actually costs landed.
- [ ] **Supplier lead times + promised delivery window** — what we can honestly tell a customer.
- [ ] **Brand voice** — how the store and the support replies sound.

Everything in Phase 1–3 can be done in parallel with this, but no ad-launch or
winner-verdict output is trustworthy until Phase 0 is filled in.

---

## Phase 1 — Accounts to open (your hands, not mine)

| # | Account | Why | Cost | Notes |
|---|---------|-----|------|-------|
| 1 | **Shopify** store | Storefront + the only real source of orders/inventory truth | $39/mo Basic | Custom app → Admin API token (read_orders, read_products, read_inventory) |
| 2 | **Shopify Payments** (or Stripe) | Getting paid | % per txn | See `dropship-account-health.md` for reserve triggers |
| 3 | **AutoDS** | Supplier sourcing + fulfillment | ~$26–66/mo | Need API key + store ID |
| 4 | **Meta Business + Ad Account** | The traffic | ad spend | Need a **System User token** (long-lived), not a user token |
| 5 | **Meta Pixel + Conversions API** | Attribution — without it every ads number is a guess | free | CAPI + event dedup. Non-optional. See `dropship-store-setup.md` |
| 6 | **Apify** | Competitor ad spy (Meta Ad Library) | pay-per-use, ~$0.75/1000 ads | Already connected as an MCP here; the box needs its own `APIFY_TOKEN` |
| 7 | **Domain** | Trust + deliverability | ~$12/yr | |
| 8 | Klaviyo *(later)* | Email/SMS retention — the diagnostician wants LTV:AOV 3:1 | free tier | **No client module exists yet.** Key alone does nothing |
| 9 | PiPiAds *(optional)* | Second ad-spy source | $77/mo | Client exists but its endpoints are unverified guesses. **Skip until Apify proves insufficient** |

**Decision made for you:** ad spy runs on **Apify**, not PiPiAds. Apify is already connected,
costs ~$0.75 per 1000 ads instead of $77/mo flat, and the actor
(`curious_coder/facebook-ads-library-scraper`) has 35k users at a 99.7% success rate. PiPiAds stays
wired as a fallback.

**There is no "Meta MCP."** It doesn't exist in the registry and isn't needed — `agency_ads.py`
already has a real Meta Marketing API client, already env-scoped so dropship can never spend the
agency's token. Meta needs a **token**, not a connector.

---

## Phase 2 — Keys into `forge-dropship/config/dropship.env`

**Created 2026-07-30** — on the box at `/opt/forge/forge-dropship/config/dropship.env`, chmod 600,
verified 404 over HTTP (rule 4). Secrets never go through git; ship it with `scp` + a
`systemctl restart forge-reios` (from the gaming PC: `~/.ssh/forge_droplet`), or `./deploy/push.sh`
from the Mac.

Required to make anything real:

- [x] `SHOPIFY_STORE_DOMAIN` — `pt4x1h-mf.myshopify.com`, `SHOPIFY_API_VERSION` — `2026-07`
- [ ] `SHOPIFY_ADMIN_TOKEN` — **the one blocking blank.** dev.shopify.com → Dev Dashboard (the old
      admin "Develop apps" path was removed 2026-01-01) → custom app on this store → Admin API
      access token `shpat_...`, scopes `read_orders, read_products, read_inventory`
- [x] `AUTODS_STORE_ID` — `5654075`
- [ ] AutoDS auth — **not** `AUTODS_API_KEY` (REST rejected: unpublished activation fee, docs gated
      behind payment). Wire the MCP OAuth refresh companion instead — see the status table above
- [ ] `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_MAP`
- [ ] `APIFY_TOKEN` *(new — competitor ad spy)*
- [ ] `DROPSHIP_ANTHROPIC_API_KEY` *(optional; falls back to the shared key)*

Verify each with the health endpoints before trusting anything:

```bash
for s in shopify autods pipiads adspy; do curl -s "http://localhost:7799/api/dropship/$s/health"; echo; done
```

**Known trap (now fixed):** four cadence knobs were read before the env file loaded, so setting
`FORGE_DROPSHIP_BRIEF_EVERY_H` / `_LEARN_EVERY` / `_LEARN_GAP_MIN` / `_BRIEF_TOKENS` in
`dropship.env` was silently ignored.

---

## Phase 3 — Turn the 24/7 loops on

Box loop knobs live in `/etc/default/forge-reios` (secrets — `grep` it, never `cat` it).
Edit + `systemctl restart forge-reios`. No deploy needed.

- [ ] `FORGE_DROPSHIP_BRIEF=1` — **only after Shopify is keyed.** A brief over empty data is
      fabrication *and* a daily Claude bill. Thread `midas`, cadence `FORGE_DROPSHIP_BRIEF_EVERY_H` (24).
- [ ] `FORGE_DROPSHIP_BRIEF_EVERY_H` — start at 24. Drop to 12 only once there's real order volume.
- [ ] `FORGE_DROPSHIP_LEARN_EVERY=8` / `_LEARN_GAP_MIN=45` — self-improvement cadence.

**Switching a loop back OFF must call `forge_heartbeat.retire("midas")`** or it stops beating,
goes red forever, and trips the health card + watchdog.

Watch the spend at `/api/cost/status` → `mtd.byAgent` (Costs tab, "Spend by agent").

**Ad spy is manual-pull only, deliberately.** Every pull costs real money, so it never auto-polls.
If you later want a nightly competitor sweep, that's a separate opt-in knob with its own cap —
say so and I'll wire it.

---

## Phase 4 — What is built vs. still missing

### Built and real
- Shopify read bridge (orders / products / inventory / snapshot) — retry + backoff, honest mock when unkeyed
- AutoDS client (products / marketplace / orders) — endpoints unverified against live docs
- MCP client (`dropship_mcp.py`) — full JSON-RPC + SSE, probe + call + receipts, **operator-gated** (agents cannot reach it)
- Local watchlist funnel (idea → researching → testing → winner → killed), atomic writes
- Midas: daily brief, `learn()` self-improvement, 3 lanes (research / ads / fulfillment)
- Creed + 4 top skills + learned playbook, with `learn()` structurally unable to rewrite the creed
- **Competitor ad spy** (`dropship_adspy.py`) — Meta Ad Library via Apify, longevity scoring *(new)*
- Ad-launch numeric SOP, store-setup/CRO, account-health runbook, support macros *(new skills)*

### Still missing — flag if you want these
- [ ] **Shopify write path** — there is no publish/fulfill code at all, gated or otherwise. Listing edits are manual today.
- [ ] **Klaviyo / TikTok / AfterShip / GA4** — env placeholders only, **no client modules exist**. (They used to light a false "connected" dot; that's now reported honestly.)
- [ ] **Route auth** — all 44 `/api/dropship/*` routes are unauthenticated. Fine on loopback/tailnet, but `/director/run`, `/director/learn` and `/mcp/call` each spend money or act, and `/mcp/call`'s only gate is a browser confirm dialog.
- [ ] **Nightly competitor sweep** — deliberately not built; costs money per run.
- [ ] **Higgsfield ad-creative generation** — the MCP is connected here but not wired into dropship.

---

## The honest bottom line

Nothing about this is blocked on code. It's blocked on **Phase 0 (five sentences from you)** and
**Phase 1–2 (accounts + keys)**. Every engine below that already runs, degrades honestly when
unkeyed, and refuses to invent a number.

The first real milestone: key Shopify + Apify → pull competitor ads on a keyword → get a
grounded product verdict out of Midas. That's the first output in this system that isn't a
model prior.
