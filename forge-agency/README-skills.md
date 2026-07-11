# Agency Agent Skills — seed playbooks

This folder (`skills/`) holds the **seed playbooks** for the AI Agency's two
agents:

- `skills/dyson-playbook.md` — **Dyson**, the edit/build agent (client website
  edits, new pages, bug fixes, design changes, integrations). Produces a PLAN per
  change; nothing goes live until the operator approves in the Approval Center.
- `skills/eco-playbook.md` — **Eco**, the ads strategist (analyzes Meta ad
  performance, finds winners/losers, proposes new ad concepts). Recommends only;
  campaigns launch after approval.
- `skills/agency-skills-backlog.md` — brainstormed roadmap of future capabilities
  for both agents.

## Seed vs. live (learned) playbooks

These files are the **seed** — a stable, version-controlled starting point. The
**live/learned** versions live in the Obsidian brain vault at:

- `Skills/dyson-playbook.md`
- `Skills/eco-playbook.md`

**How it works each session:**

1. The agent loads its **seed** playbook from this folder.
2. It **merges the brain copy on top** of the seed (vault overrides/extends seed).
3. It works the task using the merged rubric.
4. It **self-improves by rewriting the brain copy** in the vault — capturing
   per-client conventions, what got approved vs rejected, and refined thresholds —
   so improvements persist and compound across sessions.

The seed stays clean and general; the brain copy is where learning accumulates.
If the brain copy is ever lost, the agent still has a solid baseline from the seed.

## Hard rules carried by both agents

- **Propose, don't act.** Dyson plans; Eco recommends. Neither ships or spends.
- **Human-approved.** Everything goes through the operator in the Approval Center.
- **Dyson never claims work is live** until the operator ships it.
- **Eco never moves money** until the operator approves the budget/campaign.
