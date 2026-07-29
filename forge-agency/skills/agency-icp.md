# ClientForge — ICP & Lead-Gen Spec (Clay / cold call)

**This is the answer to "who do we call."** It defines the territory order, the
niche ranking, the qualify/disqualify rules, and the exact Clay build that
produces a call-ready list. The phone script and pricing live in
`agency-cold-call-playbook.md` — this file is upstream of the call.

*Owner-edited. Last updated: 2026-07-29.*

---

## 0. The one-line ICP

> **Owner-operated local service businesses, 1–30 staff, where one person we can
> reach on the phone decides everything — and their web presence is visibly worse
> than their actual business.**

If we cannot get the owner/manager/shot-caller on the phone, it is not a lead —
no matter how good the business looks. That is the hard filter.

---

## 1. Territory: clear one area, then move

**Model: clear-and-advance, not spray.** We work ONE metro until the good leads
in it are exhausted, then move to the next. Reason: a cleared area gives us local
proof ("we built the site for X down the street"), and repeat names in the same
market compound trust. A national spray gives us neither.

| Phase | Territory | Status |
|---|---|---|
| 1 | **Philadelphia metro** (Philly + Montgomery, Delaware, Bucks, Chester counties + South Jersey) | **ACTIVE** |
| 2 | next metro — chosen when Phase 1 is worked through | not started |
| 3+ | US-wide, one metro at a time | not started |

**"Cleared" means:** every Tier-1 and Tier-2 niche in that metro has been pulled,
scored, and dialed to a decision (won / dead / callback scheduled) — not "we ran
out of energy."

**When we advance,** re-rank the niches for the new metro (§2) — the best niche
in Philly is not automatically the best niche in Atlanta.

---

## 2. Niche order: start with daycare, then rank per area

### Current Philly order

**Tier 1 — start here: daycare & childcare centers.**
Why this one first, ahead of higher-ticket niches:

- **We own one.** A Touch of Blessings Learning Academy is a real licensed center
  in Philly. That is not a case study we bought — it is the operator's own
  business. It opens the call: *"I run a daycare here in Philly, I built our
  site and our enrollment system, and I'm doing it for a few other centers."*
- **We already built the exact thing we're selling them** — site
  (atouchofblessing.com), the enrollment funnel into GoHighLevel, the family
  contact form, the parent/staff app. We can show it live, not describe it.
- **We know their real pain without asking:** enrollment is the only metric that
  matters, leads come from Facebook and word of mouth, they miss calls all day
  because they're with kids, and their site is a template from 2016 that doesn't
  say ages, hours, subsidy, or "book a tour."
- **Owner-reachable by definition** — a single-site center's director IS the
  decision maker, and she picks up her own phone.

Then, in Philly, in order: home services (HVAC/roofing/plumbing/landscaping) →
med spa / dental / chiro / PT → gyms & studios → auto shops & detailers →
restaurants/catering (lowest — thin margins, worst payers).

### How to rank niches in a NEW area (score 1–5 each, add them up)

| Factor | 5 = best |
|---|---|
| **Owner reachable** | Single location, owner-operated, direct line on GBP |
| **Ticket / LTV** | One customer is worth $1k+ to them → a site pays for itself fast |
| **Web pain visible** | Most of the niche has no site, a template, or no mobile |
| **Already buying leads** | Running Meta/Google ads, or paying Angi/Yelp/Thumbtack |
| **We have proof** | We've built for this niche before, or the operator lives in it |

**Work top-scoring niche first, to exhaustion, then the next.** Log the ranking
per metro in this file when a new territory opens, so the next session doesn't
re-derive it.

---

## 3. Qualify / disqualify

### QUALIFIES (all must be true)

1. **Independent + owner-operated.** 1–30 employees, 1–5 locations.
2. **A human decision maker we can reach** — owner, director, GM, or office
   manager who can say yes to $500–1,000 without a committee.
3. **Real business, real revenue** — reviews, photos, hours, activity in the last
   ~6 months. Not a shell listing.
4. **In the active territory** (§1).
5. **At least one buying signal** (§4).

### HARD DISQUALIFY — do not import, do not dial

- **Corporate / franchise / chain.** National brands, franchise locations where
  marketing is decided at HQ, anything with a "corporate marketing" contact.
  *Test:* if the website ends in a corporate domain with a store locator, kill it.
- **Anything with "Group," "Holdings," "Enterprises," "Inc." acting as a multi-brand
  parent** — we'd be calling a gatekeeper, not a shot-caller.
- **Franchise-owned locations** even when locally owned, if the brand controls
  the website. (A franchisee who controls their own site *does* qualify — verify,
  don't assume.)
- **50+ employees / multi-state.** They have an in-house marketer or an agency.
- **No phone number**, or a call-center/IVR main line with no path to a person.
- **Already has an obviously good, recently-built site AND runs clean ads** —
  nothing to fix, we'd be a downgrade pitch.
- **On our internal do-not-call list** (§8).
- Adult, gambling, MLM, anything we wouldn't put our name on.

---

## 4. Buying signals — what makes a lead HOT

Score each lead. All four stack; more signals = call sooner.

| Signal | Points | How Clay detects it |
|---|---|---|
| **No website at all** | +3 | GBP has no website field |
| **Bad website** — no SSL, not mobile-responsive, template/Wix-default, copyright year 3+ years stale, no booking/contact form | +3 | HTTP fetch + AI column judging the homepage |
| **Running paid ads** — Meta Ad Library has active ads, or Google Ads transparency shows spend | +3 | Meta Ad Library lookup by page; they already pay for leads → the leak is the site |
| **Review volume** — 25+ Google reviews, and reviews in the last 90 days | +2 | Google Maps / GBP enrichment |
| **Rated well but invisible** — 4.5★+ with 25+ reviews and a bad/no site | +2 | combination column; this is the single best lead type we have |
| **Hiring / expanding** — job post, "now enrolling," second location, new hours | +1 | job-board or site-copy enrichment |
| **Owner name + direct line found** | +2 | required to dial at all; no owner = deprioritize |

**Bands:** 8+ = **HOT, call today.** 5–7 = **WARM, this week.** 3–4 = **cold,
batch it.** <3 = **skip.**

**The money lead:** high reviews + active ads + bad site. They are already proving
demand and already spending money — we're not selling them on marketing, we're
fixing the thing eating what they already spend.

---

## 5. THE PAIN POINT — the one column that matters

**Every lead carries a pain point or it does not get called.** Not a category, not
a score, not "needs a website" — one specific, concrete, checkable sentence about
what is broken for *that business*, written so the owner would hear it and think
*yeah, I know*.

This is the column the whole call opens on. Without it you are a stranger with a
pitch; with it you are someone who looked.

**A real pain point:**

- "Running Facebook ads right now but the site has no way to book a tour."
- "No website at all, just a Facebook page — 61 reviews at 4.8."
- "88 Google reviews at 4.7, busiest center on the block, and invisible online."
- "Second location opened in May, the site still lists only the first."
- "Site doesn't load on a phone, copyright says 2019."
- "No ages, hours, or CCIS subsidy info anywhere on the site."

**Not a pain point:**

- "Outdated website" / "poor online presence" / "needs modernization" — generic,
  says nothing, could be any of the 10,000 businesses on the list.
- "Losing customers to competitors" — we can't see that. It's a guess.
- "Struggling with lead generation" — we don't know their lead flow.
- Anything with a number we didn't actually observe.

### The rule for whoever writes it (Clay AI column, an agent, or Claude)

**Ground it, or leave it empty. Never invent one.** This is the agency creed
(`agency-evidence-discipline`) applied to prospecting: every pain point must be
traceable to something we actually observed — the GBP record, the live homepage,
the Meta Ad Library, the review count, a job post. If the enrichment came back
thin, the pain point is **empty**, and the lead drops to the bottom of the list
or out of it.

**Why this is non-negotiable:** an invented pain gets read out loud to a real
business owner on a real phone call. "Your booking form is broken" to someone
whose form works fine ends the call and burns the number permanently. An empty
pain costs one skipped lead. A wrong one costs the lead, the reputation, and any
referral behind it.

**Bad/no website is observable. Ad spend is observable. Reviews are observable.
Their revenue, their staffing, their frustration, and their intentions are not.**

### Where it lives downstream

The pain point is a first-class column in the dashboard's **Call Sheet**
(`pain` on each lead) — editable inline, shown next to the phone number so it's
under your eyes while it rings. When a lead is marked **Interested**, the pain
point rides into the Pipeline client note automatically, so the mockup gets built
against the actual complaint instead of a guess.

---

## 6. The Clay build (what columns to create)

**Source:** Google Maps / GBP import — search `<niche> in <city>` across the
territory's zip codes. That's the base table.

**Enrichment columns, in order:**

1. `company`, `address`, `city`, `zip`, `phone`, `website`, `rating`,
   `review_count`, `category` — from the Maps import.
2. `is_chain` — AI column: *"Is this an independent local business or a franchise/
   corporate location? Answer INDEPENDENT or CHAIN."* → **filter out CHAIN.**
3. `owner_name` / `owner_title` — people enrichment on the domain, or an AI read
   of the About page. For daycares, the director's name is usually on the site.
4. `direct_phone` — waterfall enrichment; fall back to the GBP number.
5. `email` — waterfall; used for the post-call mockup send, not for the call.
6. `site_status` — HTTP column fetching the homepage, then an AI column scoring:
   `NONE / BAD / OK / GOOD` with a one-line reason.
7. `runs_ads` — Meta Ad Library check on the business's Facebook page → `YES/NO`.
8. `last_review_date` — is the business alive.
9. `score` — formula column implementing §4.
10. **`pain_point` — the §5 column. Required.** AI column fed ONLY the enrichment
    columns above (site_status + its reason, runs_ads, review_count, rating,
    hiring, location count). Prompt it explicitly: *"One sentence naming the
    single specific thing that is broken about this business's web presence,
    using only the fields given. If the fields don't prove a specific problem,
    output an empty string. Never guess."* Then **filter out empty pain points**
    before export, or send them last.

**Output columns to export (must match the Call Sheet's parser):**

```
name, company, phone, email, website, location, pain
```

Put the owner's name in `name`, the business in `company`, and the §5 sentence in
`pain`. Header row is fine — the parser ignores it. Extra columns (score,
runs_ads) survive as loose text and are safe to include; the extractor reads the
paste rather than fixed positions.

**Column order and delimiter don't matter** — pipe, comma, or tab all parse. What
matters is that `pain` is populated, because it is the only column that changes
what you say when they pick up.

---

## 7. Getting the list into the dashboard

**No new tooling needed.** Clay → export/copy the filtered rows → paste into the
dashboard's **Agency → Call Sheet → paste text** box. `agency_callsheet.import_text`
runs a Claude extractor over the paste and produces the rows, deduping on phone.
From there: search, status chips (new / answered / no answer / callback / dead),
tap-to-dial `tel:` links, inline notes, and marking answered/no-answer auto-bumps
the daily dial tally + streak in the Call Center.

**Import discipline:**
- **Import in batches of ~50**, not 500. A wall of untouched rows kills the streak
  mechanic, which is the thing that actually keeps the dialing happening.
- **Filter in Clay, never in the Call Sheet.** Anything that fails §3 should never
  reach the dashboard.
- **Sort the paste by score descending** so the top of the sheet is the hot list.

---

## 8. Internal do-not-call list

If anyone says "don't call me again," mark the row `dead` **and** add the number
to the internal DNC note in the Call Sheet immediately. Before every new import,
the paste gets checked against previously-dead numbers — the dedupe is on phone,
so a re-import of a dead number is skipped automatically. Never re-add a number
that asked out, even from a different list.

---

## 9. What this file is NOT

- Not the phone script — that's `agency-cold-call-playbook.md`.
- Not client data — real clients live in the dashboard's Clients tab.
- Not read by Dyson or Eco. They do client work; this is prospecting. Keeping it
  out of their prompts keeps their token cost flat.
