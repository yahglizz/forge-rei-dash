# FORGE Dropship — Plug & Play Setup

Get the product research engine from "honest mock" to "real data" in one sitting.
Do these in order. You already have the EIN, the LLC, a live Shopify store, and a
Higgsfield account, so this is mostly keys and one Shopify gotcha.

Scope: **research only.** Nothing here lets an agent buy, list, advertise, or message.
Rule 2 is untouched — Midas proposes, you tap.

Companion docs: `../DROPSHIP_CHECKLIST.md` (full account list), `README.md` (file map),
`config/dropship.env.example` (every var, commented).

---

## 1. What each key costs and what it unlocks

| Key | Cost | Unlocks | Required? |
|---|---|---|---|
| `WINNINGHUNTER_API_KEY` | **~$49/mo** Basic (40% off yearly) | The evidence half of the decision packet: which ads are running, **how long each creative has been live**, which stores sell it, at what price. Limits 60 req/min, 20,000 credits/calendar month. | **Yes — the only required spend.** |
| `EVERBEE_CLIENT_ID` + `_SECRET` | **$19.99/mo** annual | Etsy keyword volume, competition, `est_mo_sales` / `est_mo_revenue` per listing. Credentials at `dev.everbee.io` → register an app. Limits 10 req/sec, 50,000 per rolling 24h. | Optional — **Etsy track only.** |
| Etsy Plus | **$10/mo** | Marketplace Insights: Etsy's own real search counts. Dashboard-only, **no API**. Its job is to *calibrate* EverBee, not replace it. | Optional, pairs with EverBee. |
| `SHOPIFY_ADMIN_TOKEN` | free (app itself) | Real orders/products/inventory instead of guesses. **See §2 and §3 — this is the part that goes wrong.** | Yes |
| `HIGGSFIELD_API_KEY` / `_SECRET` | already connected | Packet copy plan → an actual generated image. | **Already done.** Usually add nothing. |

**Higgsfield needs no new key.** `higgsfield_io` resolves it os.environ → passed creds →
a scan of `daycare.env` / `agency.env` / `dropship.env`. The paste already in
`forge-daycare/config/daycare.env` is found from here. Add a dropship copy **only** to
bill this workspace separately.

**Two things you must confirm by asking, before paying. Both cost real money if missed:**

1. **WinningHunter — which plan tier unlocks API/MCP access?** Their docs never state it.
   Ask their sales point-blank whether Basic includes API + MCP or whether it's a higher
   tier. A `403` from our client means exactly "this tier has no API access."
2. **EverBee — is the API a separate paid add-on?** Their API pricing is published
   nowhere. And their guide says data is *"filtered to match that user's subscription"* —
   so a lower tier may return keywords while nulling `est_mo_sales`. Ask whether your tier
   returns the sales/revenue fields. (A null lands as Unknown, which is correct behavior
   either way — but you'd be paying for half a feed.)

Everything below works **before** you pay: unkeyed, every client returns an honest
"add key" mock and never a fabricated row.

---

## 2. Shopify custom app — the 2026 change that breaks every tutorial

**As of 2026-01-01 custom apps can no longer be created in the Shopify admin.** Every
guide that says *Settings → Apps and sales channels → Develop apps* is dead. Two live
paths:

**Option A — Dev Dashboard (no tooling):**
1. Go to **dev.shopify.com** and sign in.
2. Create an app, then install it on your store.
3. Request scopes **`read_products`** and **`read_orders`**. Read-only for now — write
   scopes come with the write path, which does not exist yet.
4. Copy the Admin API access token (`shpat_…`).

**Option B — Shopify CLI:** same result from the terminal if you prefer it.

No app review. No Partner fee. It is a private app on your own store.

---

## 3. The Shopify plan warning — check this before you upgrade anything

Shopify **redacts Level 2 PII** (customer name, address, phone, email) on **Basic and
Starter**. The shipping address a supplier needs to fulfill comes back as **country +
province only**.

- **Research and listing work fine on Basic.**
- **Automated fulfillment does not.** ~$79/mo annual (Grow) is the practical floor for that.

Don't take that on faith — run the check on your own store. Fill in your domain and token:

```bash
curl -s -X POST \
  "https://your-store.myshopify.com/admin/api/2024-10/graphql.json" \
  -H "X-Shopify-Access-Token: shpat_YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ orders(first:1){ edges{ node{ name shippingAddress{ address1 city province country } } } } }"}'
```

- `address1` comes back with a real street → your plan exposes Level 2 PII. Nothing to do.
- `address1` is `null`/absent while `country` and `province` are populated → **redacted.**
  Fulfillment automation is blocked on this plan; research is not.

Fulfillment is out of scope for this engine either way (a separate spec). Run the check
now so the answer is known before a plan decision, not after.

---

## 4. Where keys go, and how they actually ship

```bash
cd "/Users/yg4st/forge rei dash/forge-dropship/config"
cp dropship.env.example dropship.env      # if it doesn't exist yet
chmod 600 dropship.env
# edit dropship.env — paste the real values
```

**This is the #1 way a key silently never reaches production.** Two deploy paths, and
they are not interchangeable:

| What changed | How it ships | Why |
|---|---|---|
| **A key** (`dropship.env`) | `./deploy/push.sh root@24.199.81.124` — **Mac only** | `dropship.env` is git-ignored and **never reaches GitHub**. `git push` does nothing for it. push.sh rsyncs it Mac→box. |
| **Code** (`.py` / `.jsx`) | `git push origin main` (box self-deploys in ≤60s) or `./deploy/quick-deploy.sh` for immediate | Public repo. Never carries secrets. |

Run from the repo root:

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
./deploy/push.sh root@24.199.81.124
```

Box copy lands at `/opt/forge/forge-dropship/config/dropship.env`. push.sh SSH-verifies:
service `active`, endpoints 200, **secrets 404**. If a secret path returns anything but
404, stop and fix that before anything else.

---

## 5. Verify each integration

Local (UI-only run: `FORGE_MARCUS=0 FORGE_PORT=7799 python3 connector.py`), or against
the box through the tunnel:

```bash
for s in winninghunter everbee creative shopify; do
  echo -n "$s: "; curl -s "http://localhost:7799/api/dropship/$s/health"; echo
done
```

Read the response, don't just check for a 200:

- `"configured": false` → the key is not visible to that process.
- `"configured": true, "connected": true` → the key works against the live vendor.
- `"configured": true, "connected": false` → key present, vendor rejected it. See §7.

Then the self-checks — all assert-based, exit 1 on failure:

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
python3 test_research_packet.py     # break-even CVR math, Unknown propagation,
                                    # kill flags, unkeyed→mock, injection guard
python3 dropship_creative.py        # the two hard lines: no asset reuse, no protected brand
python3 test_dropship_skills.py     # every skill file reachable; creed never in learn()
```

Run all three after touching any skill or client. Green here with `configured: false`
everywhere is a valid, expected state before you pay for anything.

---

## 6. Flip the daily brief on — last, not first

`FORGE_DROPSHIP_BRIEF` is **`0`** on purpose. A brief over empty data is fabrication
*and* a daily Claude bill.

The knob lives on the box in `/etc/default/forge-reios`. **That file holds secrets —
`grep` it for a var name, never `cat` it.**

```bash
ssh -i ~/.ssh/forge_droplet root@24.199.81.124
grep FORGE_DROPSHIP_BRIEF /etc/default/forge-reios     # never cat this file
# set FORGE_DROPSHIP_BRIEF=1
systemctl restart forge-reios
systemctl status forge-reios
```

**Only flip it once real data flows** — Shopify keyed and returning orders, WinningHunter
returning rows. Watch the spend after: `/api/cost/status` → `mtd.byAgent`, rendered on the
Costs tab.

If you ever switch it back off, the else branch must call
`forge_heartbeat.retire("midas")` or the loop stops beating, goes red forever, and trips
the health card and watchdog.

Note also: the brief and the packet are only as good as
`skills/dropship-context.md` — niche, target margin, price band, COGS, lead times, brand
voice. Five blanks, read FIRST by every dropship prompt. Unfilled, "is this a winner?" is
unanswerable by construction. See `../DROPSHIP_CHECKLIST.md` Phase 0.

---

## 7. Troubleshooting

| Symptom | What it actually means | Fix |
|---|---|---|
| **`403` from WinningHunter** | Your plan tier does not include API access. Not a bad key. | Ask their sales which tier unlocks API/MCP, then upgrade or revisit the tool choice. |
| **`401` / `403` from EverBee** | Credentials wrong, **or** the app install is not approved, **or** the API is an add-on you don't have. | Re-check `EVERBEE_CLIENT_ID` + `EVERBEE_CLIENT_SECRET` at `dev.everbee.io`, confirm the install is approved, confirm the API is on your plan. |
| **EverBee returns keywords but `est_mo_sales` is null** | Not a bug. Their data is *"filtered to match that user's subscription"* — your tier nulls the sales fields. | Upgrade the tier, or accept it: null lands as Unknown, which is the honest answer. |
| **Higgsfield `"Not enough credits"`** | **Not a key problem.** The key works; the account balance doesn't. | Top up the Higgsfield account. Don't touch the env. |
| **`"configured": false` after keying** | The key never reached the box. | Re-run `./deploy/push.sh root@24.199.81.124` from the Mac. `git push` does not ship `dropship.env`. |
| **WinningHunter `401` right after setting `WINNINGHUNTER_AUTH_PREFIX=Bearer`** | The env loader strips whitespace, so the header became `Bearer<key>` with no space. | Comment the var out — the built-in default is `"Bearer "` and is correct. Set it only for a no-space scheme. |
| **Health 200 but every number is Unknown** | Working as designed — the creed refuses to invent. | Check which input is missing; the packet names it. |
| **Secrets path returns anything but 404** | `dropship.env` is reachable over HTTP. | Stop. Fix the web root before deploying anything else. |
