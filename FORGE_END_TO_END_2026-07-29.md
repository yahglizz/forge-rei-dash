# FORGE — end-to-end verification & fix plan
*2026-07-29 · verified against the live tree on Yahs-MacBook-Air, not against the docs.*

## Verdict

The **machinery** is better than the docs claim. The **wiring** is worse.

- 229/229 tests pass. Python AST clean. Tree clean. Deploy commits landing today.
- The 2026-07-26 audit P0/P1 fixes are **genuinely shipped** — CIDR allowlist, DNS-rebinding host guard, same-origin POST check, `no-store`/`no-referrer`, fragment-based portal token, `auto_send` forced false, GET-writes-child-records removed (commit `73fb928`).
- **No `.env` has ever been committed** — not in any branch, not at any point in history.

What's broken is not the framework. It's that several chains **look** connected and are not, and in two places the system reports fabricated numbers as live.

---

## P0 — fabrication and money. Fix first.

### 1. The daycare Ads tab shows another company's made-up numbers, badged LIVE
`daycare_growth.py:76` → `agency_ads.analytics(client="daycare")`. `daycare.env` has `META_ACCESS_TOKEN` but **no `META_AD_ACCOUNT_MAP`**, so `agency_ads.py:348-368` finds no mapping, falls back to `_ACCOUNTS[0]` = `act_1001`, the Graph call fails, and it silently returns `_mock_analytics` — the hardcoded **Bloom Dental** demo.

You are currently looking at: `$3,370 spend · 117 leads · CPL $28.80 · ROAS 4.99x`, campaigns "New Patient — Search Intent / Whitening Promo / Brand Awareness". None of it is yours.

`agency_ads.connection()` returns `connected:true, source:"live"` on token presence alone, so `daycare_growth.jsx:8` paints the LIVE badge and `:15` suppresses the "add a token" hint.

**Fix:** add `META_AD_ACCOUNT_MAP={"daycare":"act_1175564690150627"}` to `daycare.env`; make `analytics()` return an explicit unconnected payload when a named client isn't mapped, instead of falling back to `_ACCOUNTS[0]`.

### 2. Solomon eats those fake numbers as ground truth
`daycare_director.py:445-458` sets `connected: True` from token presence and passes `analytics` into the brief payload — under a header that literally reads *"TODAY'S LIVE CENTER DATA (ground the brief in these — do not invent numbers)"* (`:564`).

Your daycare creed forbids exactly this. Solomon isn't hallucinating; he's being fed fabrication and told it's verified.

**Fix:** in `_gather_campaign`, drop `analytics`/`accounts` unless `ads["analytics"].get("source") == "live"`, and derive `connected` from that same field.

### 3. Stripe can double-bill a family
Two independent defects:

- `stripe_io.py:134-145,158-167` dedupes via `/v1/customers/search` and `/v1/invoices/search` inside `except StripeError: return None`. A restricted `rk_` key answers **403** (Search needs the read grant) — indistinguishable from "not found". The docstring at `stripe_io.py:11` actively *recommends* the restricted key. Result: `send_invoice` creates a second customer and a second invoice; the family is billed twice.
- `_req` (`:97-104`) retries POSTs on 429/5xx with **no `Idempotency-Key`**. A transient 500 after Stripe committed → duplicate invoice item. The item is also created unattached, so an orphan gets swept into that customer's *next* invoice.

**Fix:** persist Stripe customer + invoice ids at creation and look those up first (search only as fallback); re-raise on 403; add `Idempotency-Key: daycare-inv-<invoice_id>` to both POSTs.

### 4. The price guard leaks bare numbers
`marcus_engine.py:578` `_PRICE_RE` catches `$…`, comma-thousands, `Nk/grand/thousand`, and six offer verbs + digits. It misses plain 4–7 digit numbers. Confirmed leaks:

> `"i was thinking around 40000"` · `"my number is 42500"` · `"im at 55000"` · `"ill give 40000"` · `"the number is 47000.00"` · all spelled-out amounts

Scout's own `_extract_price` (`scout_triage.py:186`) *does* catch bare `\d{4,7}`. The drafter doesn't. And `sms_guard.py:220`'s last-instant firewall only fires on `protected_draft` (autonomous/nurture/NRN) — so an **operator-approved Marcus draft, the normal path, is never price-checked at the send boundary.**

Failure: Claude drafts "i was thinking around 40000", the guard passes it, you tap ✅ in Telegram, and a price goes out by text. That is your #1 rule, broken in the most common path.

**Fix:** add `|\b\d{4,7}(\.\d+)?\b` to `_PRICE_RE`; call `_no_price_over_text` inside `_send` (`marcus_engine.py:943`) so operator edits are covered too.

---

## P1 — leads and deals you are losing right now

### 5. Scout permanently drops call-worthy leads past 10 per sweep
`scout_triage.py:701` — `for rec in screenable[:10]`. The dropped leads are **already stored with their `convKey`** (`:665`), so the next sweep skips them as "already scored". They are never handed to Marcus, and no error is raised anywhere.

After a blast reply burst, this silently eats real leads.

**Fix:** keep a pending-handoff queue in `scout.json` and drain the remainder on later sweeps instead of slicing and discarding.

### 6. A fresh inbound seller reply never gets an auto-drafted text-back
Scout's auto-handoff (`connector.py:1197` `_auto_screen`) only calls `SCREENER.auto_screen(...)`. The reply draft is created **only** by the manual paths — `/api/scout/handoff` (`:3445`) and the Telegram 🤝 tap (`:2006`). `FORGE_MARCUS_SMS=0` by default; `followup.py:126` only bumps threads where *we* spoke last.

Net: seller texts → screening report appears → **no draft is waiting**, and the Telegram ping has no approve button. Your local state agrees: **27 pending proposals, 3 ever sent.**

Speed-to-lead is the stated edge of the whole system and it is not happening.

**Fix:** in `_auto_screen`'s worker thread, call `MARCUS.make_proposal_for(conv, contact_id=cid)` after `auto_screen` — the same gated path the manual handoff already uses.

### 7. A signed contract closes nothing — and this is now your critical path
You're dropping DocuSign, which makes `mark-signed` your signing path. It is a dead end.

`POST /api/toolkit/contracts/mark-signed` (`connector.py:3528`) → `toolkit_contracts.mark_signed()` (`:273`) flips a JSON row to `status="signed"`. **No** `deals` write, no `advance_opp("closed")`, no GHL stage move, no bus alert, no stats. A wet-signed contract never closes the loop anywhere.

Compounding it: there are **two contract ledgers**. The signature poller iterates `deals.list_deals()` only (`connector.py:1701`); anything sent via `/api/toolkit/contracts/send` lands in `marcus_state/toolkit_contracts.json` and is invisible to it.

**Fix:** make `mark-signed` call `deals.set_contract(cid,"completed")` + `_sync_deal_pipeline(cid,"closed",value=assignmentFee)` — the exact two calls the poller already makes at `connector.py:1745-1754`. This is the single highest-value wholesale fix and it needs no vendor.

### 8. Atlas's math never reaches the contract
`_deal_prefill` (`connector.py:1493`) reads the GHL contact + Marcus's screening and **never touches `DEAL_PREP`**. Atlas emits prose `maoNote`/`repairEstimate` and anchors — there is no numeric ARV, repairs, or MAO field at all (`deal_prep.py:390-406`). You re-key every number by hand.

**Fix:** have Atlas emit numeric `arv`/`repairs`/`mao`; merge `DEAL_PREP.get(cid)["prep"]["anchors"]` into the draft deal.

### 9. Buyer blast: email is offered in the UI and silently no-ops
`_blast_transport` (`connector.py:2737`) returns `{"skipped": True}` for every email recipient, permanently. The UI offers "Email" and "Both" (`toolkit_blast.jsx:453-454`) and lets you compose per-recipient subject/body. `create_blast` also does `prim = channels[0]` (`toolkit_blast.py:220`), so "Both" marks every recipient `sms` and the email drafts are dead data.

In LIVE mode with Email selected: zero buyers contacted, no error.

Also: when live, `_blast_transport` checks only `sms_guard._within_hours()` — **no `sms_guard.guard()`**, so no daily cap, no dedupe reservation, no DNC/opt-out check, no ledger record.

**Fix:** hide Email/Both until a transport exists; route `_blast_transport` through `sms_guard.guard(..., kind="buyer_blast", autonomous=False)`.

### 10. Meta lead-form leads never reach the dashboard
`daycare_ghl.pending_families` accepts a contact only if tagged `family-contact-form` or `website-lead` (`:262-263`) — tags written by the two Vercel forms. A submission to lead form `979521464497096` / `2119191855676444` carries neither, and there is no leadgen webhook or Meta lead reader anywhere in the tree.

So even once you unpause the ads, **the leads do not arrive.**

**Fix:** tag inbound lead-ad contacts (e.g. `meta-lead`) in the GHL Meta integration and add that tag to the accepted set.

---

## P2 — correctness, honesty, and guard rails

| # | Finding | Evidence | Fix |
|---|---|---|---|
| 11 | Agency Approve fires a **live GitHub PR / real Meta ad** with no `confirm()` at all — while the wholesale side confirms even a single SMS | `agency_approvals.jsx:53-62`, `agency_dyson.jsx:40-45` vs `pages.jsx:162,874,917` | add `window.confirm()` naming the concrete effect |
| 12 | Eco approve is an M3 stub — flips to "approved", creates nothing, no error | `agency_eco.py:522-534` | delegate to `agency_approvals_io.decide` like `agency_workflows_io.decision` does |
| 13 | Eco's ad spec uses `account_id`; `create_ad` reads `ad_account_id` → 100% failure the day the token lands. Also missing `page_id`, `creative.*`, `objective`, `budget_daily` | `agency_eco.py:593` vs `agency_ads.py:391` | rename key + nest creative + add `META_PAGE_ID` |
| 14 | The agency **creed never reaches Dyson or Eco** — only the chat surface. The generators whose output gets shipped have no evidence discipline | only `agency_agents.py:304` | prepend `agent_creed.block("agency")` at `agency_dyson.py:281` + Eco prompts |
| 15 | `agency-context.md` says "read this first" and is loaded by **nothing** | no `agency_context.py` exists | 20-line module mirroring `daycare_context.py` |
| 16 | Two agency skills orphaned on disk: `agency-cold-call-playbook.md` (12.4KB), `agency-icp.md` (13.2KB) | reachable from zero prompt paths | port `test_dropship_skills.py` to the agency set |
| 17 | Ad runbook truncated at 4000 chars of 8871 — **all ad copy, image prompts, targeting, and the "start PAUSED" rule are cut before Solomon sees them** | `daycare_context.py:116` | `limit=9000` (and `context_block` → `6000`) |
| 18 | `agency_social.connection()` hardcodes `connected: True`; daycare Social shows the **agency's** Metricool brand (`forgelabsx`) as live | `agency_social.py:162,37-39` | `"connected": token` |
| 19 | No retry, no dead-letter, anywhere in approve→act. Failed items are **hidden by default** (`status` filter defaults to `pending`) and fire no alert | `agency_approvals_io.py:154-221,279-283`; `agency_approvals.jsx:43` | Telegram alert on `ok:False` with `dedupe_key` |
| 20 | GHL POST retries on timeout with **no ledger record until success** → a timed-out send can text a seller **twice** | `connector.py:150-163`, `marcus_engine.py:993-999` | `retries=0` on `/conversations/messages` |
| 21 | Four loops missing `forge_heartbeat.retire()` in their else branch — `marcus_sms`, `contract`, `telegram_agent`, `graphify` — each goes permanently red and trips the watchdog | `connector.py:4780,4832,4846,4865` | add `retire()`, matching `:4817`/`:4830` |
| 22 | Telegram `_msg_authorized` has **no chat binding** — an allowed user can pull leads/screenings into any group the bot joined | `telegram_io.py:752-760`, selected at `:587` | add `TELEGRAM_AGENT_CHAT_IDS` allowlist |
| 23 | Contract poller only starts if DocuSign was configured **at boot** | `connector.py:4832` | always start; let `_contract_poll_once` short-circuit |
| 24 | Docs still authorize a price by text: `forge-marcus/CLAUDE.md` + `README.md` say "unless the seller already gave one first". Code says never. Root `CLAUDE.md` §2 says never | — | delete the clause from both files |
| 25 | Two flags gate the whole daycare workspace and are in **no template** — `FORGE_DAYCARE_LIVE`, `FORGE_DAYCARE_WRITES`, both default `"0"` | `daycare_supabase.py:157-158,412-422` | add commented to `daycare.env.example` |
| 26 | Stale docs: `FORGE_DAYCARE_AUTOENROLL` documented in `CLAUDE.md:451` exists in **no code file**; `daycare-context.md` + `daycare_logins.jsx:45` still tell agents and you that form kids auto-enroll | — | correct three strings; add a contract test |
| 27 | Contact-Form inbox caps at 600 contacts, client-side filtered — past that, real families silently stop appearing | `daycare_ghl.py:433-462` | `POST /contacts/search` with tag filter |

---

## What genuinely works (don't touch)

- **Scout** score → bucket → auto-tag → auto-pipeline. Idempotent, backlog-covering, reversible, flag-killable.
- **Atlas** 15-min underwriting sweep with call cards, reported on the bus.
- **The outbound SMS choke point is real** — exactly two seller-send functions, both through `sms_guard.guard()`. DNC and 9am–8pm ET block everyone including you. No agent path reaches GHL messages directly.
- **Approvals survive restart** — `proposals.jsonl` append-only, last-write-wins, unsafe legacy drafts quarantined on load.
- **Autonomy defaults are honest** — ACE off, autopilot off, `MARCUS.toggle` refuses auto-send, blast stubbed, dropship/today off with `retire()` called correctly.
- **Loopback-only daycare auto-admin holds.** Tailscale Serve always adds `X-Forwarded-*`, so tailnet clients are refused and fall to real login. Session cookie `Secure; HttpOnly; SameSite=Strict`.
- **Daycare Supabase console** — route allowlist, no generic table proxy, RLS per center.
- **`record_invoice_payment` RPC** — transaction-safe, idempotent, replay-proof.
- **Family Blast** — genuinely live, opt-outs, per-location scoping, capped, re-entrant retry that never double-texts.
- **The deals-path DocuSign poller** is well built — idempotent, distinguishes terminal vs transient, operator retry. It just can't see toolkit-sent contracts.
- **Dyson's ship path is real** — `agency_dyson.apply` → `agency_deploy.ship()` → real GitHub branch + commit + PR. Not a proposal record.

---

## Recommended order

**Batch A — stop fabricating (1 session, no vendor needed)**
1, 2, 17, 18 — kill the Bloom Dental data, stop Solomon ingesting it, untruncate the runbook, fix the social badge.

**Batch B — stop losing leads and deals (1 session)**
7, 6, 5, 4 — make `mark-signed` actually close; auto-draft on inbound; stop dropping leads past 10; close the price-guard hole.

**Batch C — stop the double-bill (1 session)**
3 — Stripe idempotency keys + persisted ids + re-raise on 403.

**Batch D — guard rails**
11, 12, 13, 14, 19, 20, 21 — agency confirms, Eco stub, creed injection, retry alerts, heartbeat retires.

**Batch E — docs and templates**
24, 25, 26, 15, 16 — the price-rule clause, env templates, stale auto-enroll strings, agency context loader, skill-reachability test.

---

## Open items needing your answer

1. **What signing method replaces DocuSign?** Fix #7 works regardless, but the send side needs a target.
2. **Repo → private.** I can't reach the GitHub API from the sandbox. Direct link: `https://github.com/yahglizz/forge-rei-dash/settings` → Danger Zone → Change visibility.
3. **`META_PAGE_ID`** is required for any Meta ad creation and is missing from the M6 plan entirely.
