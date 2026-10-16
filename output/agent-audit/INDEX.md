# Agent audit index (propose-only loop)

| Agent | Audited | Role clarity | Model today | Verdict |
|---|---|---|---|---|
| Marcus | 2026-10-16 | 8/10 | screen=Haiku, drafts=Sonnet 5.5, chat=Sonnet 5.5 | doc drift only (§6, §8) — marcus.md |
| Scout | pending | | | |
| Atlas | pending | | Haiku (no model= arg) | |
| Solomon | pending | | | |
| Dyson / Eco | pending | | | |
| Midas | pending (archived) | | | |
| Orion | pending | | | |

## Cross-cutting findings so far
- spend_tracker.json fixed costs (Claude sub, ChatGPT, DigitalOcean, GHL x3) are all $0 — never filled in, so the Costs tab undercounts.
- cost_tracker.json on the box has no rows Aug 2 - Oct 11; history before July does not exist there.

## Open questions for the user
1. Console login (platform.claude.com) so I can pull month-by-month usage and balance.
2. Monthly Claude API budget target ($)?
3. Fixed monthly costs to enter (DO droplet, GHL x3, subs)?
4. Is Dropship staying archived?
5. Which agents are customer-facing (so brand kit voice applies)?
