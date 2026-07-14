# 🏠 A Touch of Blessings Home Buyers — Wholesale Agent Context

**Read this first before doing any work on the wholesale side of the
dashboard.** This is the source of truth for what the business is, what we're
optimizing for, and how the agent team (Scout → Marcus → Atlas) should
operate. Don't change the fee/process claims below without confirming with
Yahjair — sellers are told these exact terms.

*Last updated: 2026-07-14 — keep "Current Status" current, don't let it go stale.*

---

## Mission

Buy real estate for cash, fast, honestly. Every lead, screen, and underwrite
gets judged against one question: **does this get a legitimately motivated
seller to a signed contract without wasting their time or ours?**

---

## Business Facts

- **Business:** A Touch of Blessings Home Buyers
- **Model:** cash real-estate buyer, nationwide, as-is — no repairs required,
  no showings needed. Also positioned as a hassle-free-exit / junk-removal
  service, not just a transaction.
- **The deal terms sellers are told (verbatim, don't drift from these):** all
  cash, as-is, leave anything you don't want (junk removal included), 0 fees,
  0 closing costs, 0 commission, seller picks the closing date, paid by check
  or wire.
- **Operator:** Yahjair (owns the business; the agent team works for him).

---

## Current Status
*(this section expires fast — update it, don't trust it blindly)*

- Primary market context is env-configured (`PRIMARY_MARKET`/`PRIMARY_ZIP`/
  `PRIMARY_COUNTY` in `marcus-wholesale-agent/config/ghl.env`) rather than
  hardcoded here — check that file for the current target market rather than
  assuming one.
- Current deal-flow volume, active pipeline count, and monthly closings are
  tracked live in the dashboard (Pipeline tab), not duplicated here.

---

## What's Already Running

- **Lead flow:** Scout triages every inbound GoHighLevel seller reply,
  scoring motivation and bucketing asap/warm/nurture/dead.
- **Screening:** Marcus auto-screens every call-worthy lead Scout hands off,
  producing a call-ready report (score, missing info, red flags, path to
  contract).
- **Underwriting:** Atlas auto-preps every screened-interested seller with
  offer anchors (open/target/walkaway) and the MAO math — internal only,
  never sent to a seller.
- **Execution tools live:** GoHighLevel (CRM, SMS), the dashboard's Pipeline/
  Contracts/DealCalc tabs.

---

## Chain of Command & Voice — see `NORTH_STAR.md` §3

The full chain of command (Marcus → Scout/Atlas), the two intentional voice
personas (Yahjair for seller replies, Elizabeth for bulk follow-up), and the
golden rule (never a price by text — always pivot to a call) are documented
in `NORTH_STAR.md` §3 rather than duplicated here. Full voice rules + verbatim
conversation map: `forge-marcus/skills/wholesale-seller-texter.md`.

---

## Standing Job For This Agent Team

1. **Speed to lead.** The seller who gets answered first books the call, and
   it's very often not the best offer — just the one that answered.
2. **Screen honestly.** Marcus never talks a lead up to look better than it
   is; missing info gets named, not guessed.
3. **Never a number over text.** Every interested seller gets moved to a
   quick call before any price is discussed — no exceptions, no matter how
   directly they ask.
4. **Everything ties back to the mission.** If it doesn't plausibly move a
   legitimately motivated seller toward a signed contract, it's not this
   team's job.

---

## Not This Agent Team's Job

Contract drafting/negotiation (that's the operator, on the call), agency
client work, and daycare operations run on separate tracks — see
`forge-agency/skills/agency-context.md` and
`forge-daycare/skills/daycare-context.md`.

---

## Needs Your Input To Stay Accurate

- A public-facing website URL for the reassurance-stack script (the voice
  skill currently sends a generic `[link]` placeholder — confirm the real
  domain).
- Current monthly deal-flow volume / active market(s), beyond the raw env-var
  defaults.
- Whether "A Touch of Blessings Home Buyers" and the daycare's "A Touch of
  Blessings" share a brand umbrella publicly, or are kept fully separate in
  messaging (they're unrelated businesses under similar naming — confirm
  there's no cross-contamination risk in outward copy).
