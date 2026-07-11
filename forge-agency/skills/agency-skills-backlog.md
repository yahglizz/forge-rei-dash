# Agency Skills Backlog — candidate capabilities to add over time

Brainstormed roadmap of skills/capabilities for the AI Agency's two agents —
**Dyson** (edit/build) and **Eco** (ads strategy). Each is a candidate to build
into a playbook or the agents' tooling. Grouped by theme. None of these change
the hard rule: **the agents propose, the operator approves** — Dyson never ships
on its own and Eco never spends on its own.

## Dyson capabilities (edit / build)
- **Auto-draft the edit diff from the request** — Turn an approved PLAN into a ready-to-review code diff (before/after) so the operator approves the actual change, not just a description.
- **Visual before/after preview** — Render a screenshot of the page as-is vs the proposed change so the operator approves on sight, not on imagination.
- **Risk auto-classifier** — Read the affected files/paths and auto-assign low/med/high risk with a reason, flagging anything that touches forms, payments, redirects, or DNS as high.
- **Regression spotter** — Detect when a change touches a shared component/nav/footer and auto-list every other page that needs re-checking before approval.
- **Per-client style memory** — Learn each client's brand tokens (colors, fonts, spacing, tone, stack, file layout) so new plans come out on-brand and faster.
- **Reusable mini-templates for repeat requests** — Convert common asks (add FAQ item, swap hero image, add a testimonial, add a CTA section) into one-step templates.
- **Accessibility + performance pre-flight** — Auto-run alt-text, contrast, heading-order, and image-weight checks and fold the results into the plan's QA section.

## Eco capabilities (ads strategy)
- **Creative fatigue detector from frequency** — Watch frequency + CTR trend per ad and auto-flag "refresh now" before CPA climbs, with the proven angle to reuse.
- **Winner/loser auto-triage** — Pull the account on a schedule, classify every ad as scale/hold/kill/refresh against the client's targets, and queue the proposals.
- **Concept generator from the winning angle** — Given the current winner, auto-write 2–3 fresh hooks/headlines/primary-text variants that keep the angle and change the execution.
- **Budget reallocation proposer** — Compute how much to move from losers to winners (in steps, never overnight 2x) and queue it as a single approve-once proposal.
- **Spend-pacing watchdog** — Track actual vs planned spend daily and alert when a client is pacing >20% over/under or about to hit an end-of-month cliff.
- **Competitor/ad-library scan** — Pull active ads in the client's niche to surface angles and formats worth testing (inspiration brief, not copy-paste).
- **Per-client benchmark builder** — Maintain each client's real CTR/CPC/CPL/CPA/ROAS baselines so thresholds are calibrated, not generic.

## Cross-agent collaboration
- **Eco → Dyson handoff: ad needs a landing-page change** — When CTR is good but CPL/CPA is bad, Eco auto-drafts a Dyson edit request (message-match, faster page, shorter form) tied to the metric that justifies it.
- **Dyson → Eco handoff: page changed, re-test the ad** — When Dyson ships a landing-page edit, notify Eco to re-baseline the ad's conversion metrics and judge the lift.
- **Pixel/tracking integrity loop** — Eco flags a misfiring pixel/event; Dyson plans the fix; neither makes optimization calls until tracking is verified clean.
- **Unified client brief for the operator** — Roll up Dyson's pending plans + Eco's pending recommendations per client into one Approval-Center digest the operator clears in one pass.

## Learning & self-improvement
- **Learn from approved-vs-rejected plans which patterns get approved** — Backtest Dyson's plans against operator decisions and bias future plans (scope, risk framing, step granularity) toward what gets approved fast.
- **Learn from approved-vs-rejected ad concepts** — Track which Eco concepts the operator shipped vs cut, per client/niche, and steer future copy toward winning patterns.
- **Spend-to-outcome attribution** — Tie ad spend to leads/closed business where possible and re-weight Eco's angle/audience preferences toward what produced revenue, not just clicks.
- **Vault-synced playbook evolution** — Write learned adjustments into the Obsidian brain (`Skills/dyson-playbook.md`, `Skills/eco-playbook.md`) so improvements persist and merge on the next session.
- **Post-mortem loops** — When a shipped change breaks (Dyson) or a scaled ad craters (Eco), capture why and tighten the rubric so the same mistake doesn't repeat.
