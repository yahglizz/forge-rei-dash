# FORGE — The Businesses

*The consolidated business bible for FORGE REI OS. One operator (Yahjair), three
businesses, one standard of care. This is the **human-facing** reference — the
full "what we are and what we're going for" for each business.*

> **Canonical vs. reference.** `NORTH_STAR.md` is the constitution the agents
> actually read (terse, enforced). This file is the richer human bible that sits
> underneath it. Where they overlap, `NORTH_STAR.md` wins on rules; this file
> carries the detail, history, and beginner knowledge. Per-business operational
> truth still lives in each `forge-*/skills/*-context.md` (owner-edited, agent
> hot-reloaded). Keep all four in sync when a business fact changes.

*Last updated: 2026-07-15.*

---

## The through-line (all three)

Build like a young entrepreneur who already made it: **don't reinvent — find the
playbook that already works in the industry and run it better, faster, more
honestly than the shop next door.** AI agents do the employee-work (screening,
drafting, underwriting, ad strategy, roster management); a human keeps a hand on
the wheel for anything that spends money, makes a promise, or goes out the door.

---

## 1. Daycare — A Touch of Blessings Learning Academy

**What it is.** Real, licensed childcare in Philadelphia. The dashboard is the
**owner's management lens**; a separate Next.js app is the parent/staff lens —
both on one Supabase DB.

**The goal.** **Grow enrollment.** That is the one metric the daycare side
exists to move. Every idea, ad, post, or offer is judged against one question:
*does this get another family to book a tour?*

**The model.** Licensed + DHS-compliant childcare, private pay **and**
CCIS / Child Care Works subsidy (a major trust signal — work it into messaging,
don't bury it). Enrollment funnel: ad / referral → lead form (GoHighLevel) →
tour booked → enrolled. Growth is gated by **staffing, not lead volume** — PA
background clearances run 4–8 weeks, so no ad or post promises a start date the
actual open capacity can't support.

**Business facts.**
- **Entity:** A Touch of Blessings 2 & 3 LLC · **Director:** Regina Price
- **Ages:** 6 weeks – 12 years · **Hours:** Mon–Fri, 6:00 AM – 6:00 PM
- **Website:** atouchofblessing.com

**Locations.**

| Location | Address | Phone | Notes |
|---|---|---|---|
| A Touch of Blessings (original) | 921 N 18th St, Philadelphia | 215-236-5439 | |
| A Touch of Blessings 2 & 3 | 2316–2318 Cecil B. Moore Ave, Philadelphia 19121 | 844-708-6824 | Newest. PELICAN Provider ID 4114489120, ELRC Region 18. 37 licensed slots (19 infant / 18 toddler). $3,300/mo rent. |
| A Mother's Touch Inc. | 1923 Cecil B. Moore Ave, Philadelphia | 215-787-0100 | Connected franchise, same ownership, **separate legal entity** — confirm before folding into a shared campaign. |

**What's running.** $100 enrollment bonus; refer-a-friend (both families stay
60 days → $100); ad angle library (urgency / trust / offer) + seasonal variants;
GoHighLevel + Meta Ads Manager (lead forms live).

**Brand voice.** Warm, trustworthy, never corporate — *"your child deserves more
than just childcare,"* not *"enroll now."* Visuals: photorealistic, premium,
warm golden lighting, purple-and-gold, **no children's faces shown**.

**Full context (owner-edited, agent-loaded):**
[`forge-daycare/skills/daycare-context.md`](forge-daycare/skills/daycare-context.md)
· ad runbook: [`forge-daycare/skills/enrollment-ad-agent.md`](forge-daycare/skills/enrollment-ad-agent.md)

---

## 2. Wholesale — A Touch of Blessings Home Buyers

**What it is.** A cash real-estate buying business — **we are a beginner
wholesaler building the muscle**, running the proven wholesaling playbook with
discipline instead of chasing anything novel.

**The goal.** Get a **legitimately motivated seller to a signed contract**
without wasting their time or ours — then assign or close. Judge every lead,
screen, and underwrite against that.

**The model.** Buy for cash, nationwide, as-is. We control a property under
contract at a price that leaves room, then assign that contract to a cash buyer
for a fee (or close it ourselves). Current lead markets seen in the data:
**Ohio** and **Reading / PA (267 area)** — the model stays nationwide, markets
are where the lists are running.

**The deal terms sellers are told (verbatim — don't drift):** all cash, as-is,
leave anything you don't want (junk removal included), **0 fees, 0 closing
costs, 0 commission**, seller picks the closing date, paid by check or wire.

### Beginner wholesaling knowledge (the floor every agent + operator works from)

*This is the foundational primer — the "what you already know" written down so
the docs teach it, not just assume it.*

- **What wholesaling actually is.** You are not buying with your own money to
  keep. You get a property **under contract** below market, then sell (assign)
  that contract to an end cash buyer. Your profit = the **assignment fee** (the
  spread between your contract price and what the buyer pays). Low capital, high
  skill — the skill is *talking to motivated sellers and reading a deal.*
- **The one number that matters — MAO (Maximum Allowable Offer).** The most you
  can offer and still leave room for your buyer + your fee:
  **`MAO = (ARV × 0.70) − repairs − your assignment fee`.**
  - **ARV** = After-Repair Value (what the house is worth fixed up, from
    comps — recently sold, similar, nearby).
  - **70%** is the classic investor rule of thumb (the buyer's cushion for
    profit + holding + closing). Tighten/loosen by market.
  - **Repairs** = honest rehab estimate. When unknown, it's **Unknown** — never
    invented (that's the creed).
- **Motivation is the whole game.** A house isn't a deal; a **motivated seller**
  is. Signals: inherited/probate, tired landlord, vacant, pre-foreclosure,
  relocation, divorce, major repairs they can't fund, "just want it gone." Scout
  scores exactly this.
- **Speed to lead wins.** The seller who gets answered **first** usually books
  the call — and it's very often *not* the best offer, just the one that
  answered. This is why the whole system optimizes reply speed.
- **Never a number by text — ever.** No price, offer, range, or ARV over SMS.
  The text exists only to get a motivated seller on a **quick call**; the number
  is given by a human, on the phone, after the house is understood. Enforced in
  the prompt *and* in code (`marcus_engine._no_price_over_text`).
- **The funnel.** List / marketing → inbound reply → **Scout** triages +
  ranks → **Marcus** screens + drafts the reply that drives to a call → operator
  calls + gives the offer → contract → **Atlas** has already underwritten the
  numbers internally → assign to a cash buyer → close.
- **Beginner failure modes to avoid:** chasing unmotivated sellers, talking a
  weak lead up to look better, guessing repairs/ARV, lowballing by text and
  killing trust, and being slow to respond. The agents are built to prevent
  exactly these.

**Chain of command & voice.** Marcus (head) → Scout (find/rank) + Atlas
(underwrite). Two deliberate, never-blended voices: **Yahjair** (personal seller
replies — warm, lowercase, faith-flavored, relationship-first) and
**Elizabeth** (bulk GHL follow-up only — casual, max two sentences, never opens
with "I"). Full detail: `NORTH_STAR.md` §3.

**Full context:**
[`forge-scout/skills/wholesale-context.md`](forge-scout/skills/wholesale-context.md)
· voice: [`forge-marcus/skills/wholesale-seller-texter.md`](forge-marcus/skills/wholesale-seller-texter.md)

---

## 3. Agency — ClientForge (brand: "Forge Labs")

**What it is.** The AI-agency workspace — done-for-you **automations, websites,
and ad management** for real clients. Documented in code + constitution as
**ClientForge**; the owner also runs it under the brand **Forge Labs**. (Names
are the owner's call; the agents and code use `ClientForge` today — see
`NORTH_STAR.md` §4.)

**The goal.** Ship work that **actually moves a client's numbers**, without ever
claiming something is live or spending money that isn't approved. Judge every
plan against: *would the operator be comfortable if the client saw exactly how
this was decided?*

**The model.** Sell and deliver:
1. **Automations / AI services** — the growth focus: workflow automation, AI
   agents, lead-gen and follow-up systems, CRM wiring (the same class of build
   this dashboard itself is).
2. **Website edits / builds** (agent: **Dyson**) — copy/asset swaps, style
   changes, new pages, fixes, CRM/booking/payment integrations. Dyson turns a
   request into a reviewable **plan**; nothing ships until approved.
3. **Meta ads strategy** (agent: **Eco**) — reads performance vs. benchmarks
   (CTR/CPC/CPL/ROAS/frequency/hook rate), calls scale/hold/kill/refresh, drafts
   new concepts. Eco never spends on its own.

**Honest gaps (don't invent past them).** No client roster / ICP, pricing model,
or client-facing brand voice is documented yet — the agency-context file flags
these as genuinely-missing, to be filled as real clients onboard, not fabricated.

**Full context:**
[`forge-agency/skills/agency-context.md`](forge-agency/skills/agency-context.md)

---

## Keeping this current

When a business fact changes (a location, an offer, a market, a live client),
edit it in the **same commit** as the change: the per-business
`forge-*/skills/*-context.md` first (that's what the agents read), then this
file and `NORTH_STAR.md` if the change is cross-business. A stale bible tells
every agent something false with full confidence — worse than no bible.
