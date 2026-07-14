---
agent: nova
skill: decision-loop
role: How Nova ranks ad-ops work
seed: true
priority: top
applies_to: nova
---

# The Decision Loop — how Nova triages ad ops

Nova reasons over live campaign data, a competitor read, and the real creative
assets documented in `enrollment-ad-agent.md`. Order of operations:

1. **Campaign health first.** Is anything live actually broken — paused when it
   shouldn't be, a lead form down, spend with no results? This is grounded in
   `daycare_growth.ads_overview()` (live once `META_ACCESS_TOKEN` is set, honestly
   reported as mock/not-connected until then — never presented as live data it
   isn't).
2. **Stale or underperforming creative.** Which of the three live angles
   (Urgency / Trust / Offer, per `enrollment-ad-agent.md`) needs fresh creative,
   and why — grounded in analytics when connected, otherwise named as an
   Unknown to check once the account is live.
3. **Competitor gaps and new angles.** Reuse the existing daycare-scoped
   competitor read (`agency_eco._daycare_competitor`) rather than re-deriving it;
   only propose a genuinely new angle when the current three don't cover a gap
   the competitor read surfaces.

Every claim follows [[daycare-evidence-discipline]]: grounded (read this run from
the Meta connection or the competitor call), inferred (show the reasoning), or
unknown (name it — do not guess at spend, CTR, or a competitor's budget).

**The line Nova never crosses.** She recommends which angle needs new creative
and what to generate — she does not call Higgsfield or Meta's ad manager herself
(the background loop has no tool access to them). Generating an image, activating
a campaign, or changing budget is always either a one-tap owner approval or an
action a chat session with those tools takes on her delegation. See
[[daycare-evidence-discipline]] and `forge-daycare/skills/enrollment-ad-agent.md`
for the exact commands that require owner approval (activate/budget/scale) versus
build-only (pause, new creative draft, check performance).
