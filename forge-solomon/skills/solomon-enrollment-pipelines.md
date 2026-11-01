---
agent: solomon
skill: enrollment-pipelines
role: The two GHL enrollment pipelines — what each stage means, who moves it, what proves "enrolled"
seed: true
applies_to: solomon
updated: 2026-11-01 — two boards (A Touch of Blessings + A Mother's Touch), n8n daily stage run
---

# Enrollment pipelines — two businesses, two boards, never mixed

## 1. The two pipelines (daycare GHL location 4JIvZEmkY5EjTsDRnjBN)

| Board key | GHL pipeline | Business | Centers |
|---|---|---|---|
| `enrollment` | "Enrollment" | A Touch of Blessings (ATOB) | 921 N 18th · 2318 Cecil B. Moore |
| `amt` | "A Mother's Touch" | A Mother's Touch (AMT) — a **separate legal entity** | 1923 Cecil B. Moore |

Both have the same six stages, in order: **New Lead → Contacted → Tour Scheduled →
Application Sent → Enrolled → Lost**. Never add the two boards together, never quote one
business's count as the other's, never move or refer a family across them on your own
(cross-referral 921/2318 ↔ 1923 is the owner's call).

## 2. Which business a family belongs to (contact tags)

- **AMT** when the contact has `entity-amt` or `loc-1923-cecil-b-moore`.
- **ATOB** otherwise; `entity-atob`, `loc-921-n-18th`, `loc-2318-cecil-b-moore` name the
  center. No location tag = center Unknown — ask, never assume.
- `enrolled` — mirrors the production roster (see §4). `pipe-propose:<slug>` — a stage
  proposal waiting on the owner (slug: new-lead | contacted | tour-scheduled |
  application-sent | enrolled | lost).

## 3. Who moves a stage

- **The daily n8n run** (workflow R5knymRU7t30uR8x, 9 PM ET) reads each open opportunity's
  full text thread and moves it **forward only**, and only with a quoted evidence line.
  Nothing past Contacted unless the parent replied. Enrolled needs high confidence or the
  `enrolled` tag. It also moves AMT families out of "Enrollment" into "A Mother's Touch".
- **Lost is never automatic** — it arrives as the tag `pipe-propose:lost`; the owner's
  Approve tap on the dashboard moves it (and clears the tag).
- **You never move a stage.** Pipeline moves are a ✅ tap card in chat. You may point at a
  proposal that is waiting ("3 ATOB cards proposed Lost — approve or keep?").

## 4. "Enrolled" — what is true

- **Ground truth = a child row in the production roster** (the daycare app's children).
  The GHL `enrolled` tag mirrors it; the pipeline's Enrolled column is a CRM view of it.
  If they disagree, the roster wins — say "pipeline says X, roster says Y".
- **Family Contact Form** (the emergency-contact PDF, brand-tagged `atob` or `amt`, read
  through `daycare_family_forms.py` / `GET /api/daycare/family-forms`) proves a family
  **finished the paperwork**. It does **not** by itself mean the child is enrolled in the
  app — a login is made only on the owner's Create-login click plus the family's YES.
  Never count a form as an enrollment.

## 5. Reading the boards

Your chat context carries `pipeline` = per-board counts from the dashboard's saved state
(`enrollment` and `amt`, each with total, proposals, byStage, stale, missing). Stale or
missing = say so; `missing: true` = that pipeline is not in GHL yet (Unknown, not zero).
Use the boards for funnel leaks: many in Contacted with no Tour Scheduled = tours aren't
being booked; Application Sent that never reaches Enrolled = paperwork/start-date stall.
Always name the business with the number.
