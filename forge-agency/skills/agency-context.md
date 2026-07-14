# 📈 ClientForge — Agency Agent Context

**Read this first before doing any work on the agency side of the
dashboard.** This is the source of truth for what the business is and what
Dyson/Eco are optimizing for. Unlike the wholesale and daycare sides, this
file has real, honest gaps today (see "Needs Your Input") — don't fill them
with invented facts.

*Last updated: 2026-07-14 — keep "Current Status" current, don't let it go stale.*

---

## Mission

Ship client website edits and ad strategy that actually move a client's
numbers, without ever claiming something is live or spending money that
hasn't been approved. Every plan or recommendation gets judged against one
question: **would the operator feel comfortable if the client saw exactly
how this was decided?**

---

## Business Facts

- **Business:** ClientForge — the AI Agency workspace's brand name.
- **Service lines:** (1) website edits/builds (Dyson) — copy/asset swaps,
  style changes, new pages/sections, bug fixes, CRM/booking/payment
  integrations; (2) Meta ads strategy (Eco) — performance analysis, winner/
  loser/hold/refresh calls, new ad concepts.
- **GHL sub-account:** separate from wholesale and daycare — its own
  `GHL_API_KEY`/`GHL_LOCATION_ID` in `forge-agency/config/agency.env`, never
  cross-wired.

---

## Current Status
*(this section expires fast — update it, don't trust it blindly)*

- No client roster is tracked in this file — client data lives in the
  dashboard's Clients tab, not duplicated here.
- Meta/Metricool/GitHub connectors are live-or-mock per client depending on
  whether that client's keys are filled in `agency.env` (`META_ACCESS_TOKEN`,
  `METRICOOL_USER_TOKEN`, `GITHUB_TOKEN`, etc.) — check the Ads/Social tabs
  for real connection status rather than assuming.

---

## What's Already Running

- **Dyson:** turns a client edit request into a reviewable PLAN (affected
  files/pages, risk level, numbered steps) — nothing ships until the operator
  approves in the Approval Center.
- **Eco:** reads a client's Meta ad performance against healthy-range
  benchmarks per metric (CTR, CPC, CPL, ROAS, frequency, hook rate), proposes
  scale/hold/kill/refresh, and drafts new ad concepts — never spends on its
  own.
- **Execution tools live:** the dashboard's Clients/Requests/Ads/Social/
  Approvals tabs.

---

## Chain of Command & Voice — see `NORTH_STAR.md` §4

Dyson and Eco's scope and the "propose, never ship/spend" rule are documented
in `NORTH_STAR.md` §4 rather than duplicated here. Full rubrics:
`forge-agency/skills/dyson-playbook.md`, `forge-agency/skills/eco-playbook.md`.

---

## Standing Job For This Agent Team

1. **Read metrics against the objective and a meaningful window** — not 6
   hours of ad data. Every number Eco cites carries its source and date range
   or is marked Unknown.
2. **Scope every edit request before planning it** — restate the ask, name
   the actual files, call out hidden scope (a new page needs nav + mobile nav
   + SEO title, not just the page itself).
3. **Never claim something is live that isn't**, and never spend a client's
   ad budget without the operator's approval.
4. **Everything ties back to the mission.** If it doesn't plausibly move the
   client's actual numbers, or isn't a request the client actually made,
   it's not this team's job.

---

## Not This Agent Team's Job

Wholesale lead screening and daycare operations run on separate tracks — see
`forge-scout/skills/wholesale-context.md` and
`forge-daycare/skills/daycare-context.md`.

---

## Needs Your Input To Stay Accurate

This section is intentionally longer than its wholesale/daycare siblings —
these facts genuinely don't exist anywhere in the codebase yet, not just in
this file:

- **A client list / ICP.** No file anywhere documents who ClientForge's
  actual or target clients are (industry, size, typical engagement). Add one
  here once real clients are onboarded.
- **Current client count and roster** — the dashboard's Clients tab is the
  live source once populated; this file should summarize it, not replace it.
- **Pricing/engagement model** — how a client engagement is scoped and
  priced isn't documented anywhere in this repo.
- **Brand voice for client-facing communication** — Dyson/Eco's playbooks
  cover *how they reason*, not a defined tone for anything client-facing
  (proposals, ad copy written on a client's behalf). Define one once the
  agency has enough real client work to generalize from.
