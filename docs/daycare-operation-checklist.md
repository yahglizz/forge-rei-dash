# FORGE Daycare — Full-Operation Checklist

**Goal:** ads created + published → funnel (website/ad) → GHL lead → agents work + organize
the lead automatically → GHL promotions go out → owner approves outward actions.

**Legend:** ✅ live & verified · ⚠️ needs a key / config / manual verify · ❌ not built yet

*Verify from the Daycare workspace (`open-dashboard.sh` → profile switcher → FORGE DAYCARE).
Every outward action stays owner-approved (CLAUDE.md rule 2).*

---

## Stage 0 — Foundation (the operating layer) — ✅ LIVE

- [x] **Console opens straight in** (loopback auto-admin). Verify: switch to FORGE DAYCARE, no login screen.
- [x] **Supabase live** — center data (children, attendance, billing, incidents). Verify: Dashboard shows real counts.
- [x] **Brain hooked up & self-improving** — 6/6 agents fed; Solomon writes briefs + playbook. Verify: Brain tab → "LIVE · 6/6 agents fed", activity feed shows `solomon`.
- [x] **Solomon (head agent)** — reads center + brief, ranks priorities, delegates. Verify: Solomon · Director → Build operating brief.
- [x] **Stripe invoicing** — `rk_live` key wired. Verify: Billing → Send via Stripe on a test invoice.
- [x] **GHL connected** (daycare sub-account `4JIvZEmkY5EjTsDRnjBN`). Verify: Solomon status chip "GoHighLevel" green.

## Stage 1 — Ad CREATION (ideas) — ✅ LIVE

- [x] **Eco drafts enrollment ad concepts** from the business brief. Verify: Growth → Ideas → "Generate enrollment ideas" → concepts + competitor read appear.
- [x] Ideas read the **learned brain playbook** (Solomon's strategy flows in).

## Stage 2 — Ad PUBLISHING (Meta) — ⚠️ NEEDS KEY

- [ ] **Add `META_ACCESS_TOKEN`** to `forge-daycare/config/daycare.env`, then `push.sh`.
- [ ] Verify: Growth → Ads shows **LIVE** (not "NOT CONNECTED") + real spend/leads.
- [ ] Publish path builds ads **PAUSED** (never auto-spends); you un-pause in Meta. *(agency_ads.create_ad)*
- Gap: blank token = mock mode. No code change needed once keyed.

## Stage 3 — FUNNEL: website / ad → GHL lead — ⚠️ VERIFY

- [ ] Meta **lead form** (or website form) points at the daycare GHL location. *(forms already built per the brief)*
- [ ] Verify end-to-end: submit a **test lead** → confirm the contact lands in GHL.
- Gap: forms exist, but nothing in the dash **ingests/works** a new lead yet (see Stage 4).

## Stage 4 — Agents WORK the lead automatically — ❌ NOT BUILT (daycare)

- [ ] **Daycare Lead Agent** — polls `DAYCARE_GHL`, scores new inquiries, drafts a first-touch reply, hands to family-comms. *(Scout pattern, under Solomon — Solomon already delegates to "Enrollment"/"Family-Comms")*
- Today: Solomon **orchestrates + delegates** but no agent consumes the delegations. Scout works REI seller leads only.
- **This is the core missing piece for "agents work leads automatically."**

## Stage 5 — Keep leads ORGANIZED (tags + pipeline) — ❌ NOT BUILT (daycare)

- [ ] Auto-tag + move GHL pipeline stage on new inquiries (internal + reversible, like Scout's HOT auto-tag).
- Built by the same Stage-4 Lead Agent.

## Stage 6 — GHL PROMOTIONS / blasts from the app — ❌ NOT BUILT (daycare)

- [ ] **Daycare Promo Blast** — segment families/leads, draft the promo, one-tap send via `DAYCARE_GHL`. *(Buyer-Blast pattern)*
- Today: `daycare_ghl` sends **single** family texts (invoice link) via the Text button. No broadcast/promo tool.

---

## What "full operation" still needs (build order)

1. **You:** paste `META_ACCESS_TOKEN` → unlocks Stage 2 (publish) + live ad analytics. *(5 min)*
2. **Build — Daycare Lead Agent** (Stages 4 + 5): the Enrollment/Family-Comms worker. Polls GHL, triages + auto-tags + pipelines new inquiries (reversible), drafts first-touch, hands off — all gated. Reads Solomon's brain, self-improves. *(forge-self-improving-agent recipe)*
3. **Build — Daycare Promo Blast** (Stage 6): segment → draft → one-tap GHL broadcast, gated.
4. **Verify the whole funnel:** test ad → test lead → agent picks it up → tagged + pipelined → promo goes out.

**Status now:** the *brain, ideation, invoicing, and manual family texting* run. The *auto lead-working loop, live ad publishing, and promo blasts* are the gap between today and the hands-free operation you want.

*Kept honest: ✅ = verified this session · ❌ = not written yet, not "coming soon".*
