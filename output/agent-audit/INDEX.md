# Agent audit index (propose-only loop)

| Agent | Audited | Role clarity | Model today | Verdict |
|---|---|---|---|---|
| Marcus | 2026-10-16 | 8/10 | screen=Haiku, drafts=Sonnet 5.5, chat=Sonnet 5.5 | doc drift only (§6, §8) — marcus.md |
| Solomon | 2026-10-16 | 8/10 | replies=Sonnet 5.5, brief=Sonnet 5.5, ads judge=Haiku | no daily draft cap; 3 stale card spots — solomon.md |
| Dyson (+Eco) | 2026-10-16 | 7/10 | all Sonnet 5.5 except learn=Haiku | title drift x3; weekly review ungated spend; Eco mock unlabeled — dyson.md |
| Orion | pending | | | |
| Midas (archived) | pending | | | |
| Marcus re-check | pending | | | |

## Cross-cutting findings so far
- spend_tracker.json fixed costs (Claude sub, ChatGPT, DigitalOcean, GHL x3) are all $0 — never filled in, so the Costs tab undercounts.
- cost_tracker.json on the box has no rows Aug 2 - Oct 11; history before July does not exist there.

## Open questions for the user
1. Console login (platform.claude.com) so I can pull month-by-month usage and balance.
2. Monthly Claude API budget target ($)?
3. Fixed monthly costs to enter (DO droplet, GHL x3, subs)?
4. Is Dropship staying archived?
5. Which agents are customer-facing (so brand kit voice applies)?


## Update 2026-10-16 (loop restarted, scope = 5 main agents + integrations)
- Claude was DOWN (credits) Aug 1 -> Oct 12 17:24 UTC; 4,862 of 4,869 recorded calls failed; recovered. Circuit breaker (9/30) now stops hammering.
- Google is not integrated anywhere in the code. Plan: GOOGLE-PLAN.md.
- Open: Meta daycare token state, Supabase migrations behind, n8n page mock-as-live, spend_tracker fixed costs all $0.
- Nightly learn timer fires daily but is a verified no-op (FORGE_SELF_IMPROVE off). Weekly review timer (Mon 08:00 UTC) is NOT gated and will spend on Oct 19.
