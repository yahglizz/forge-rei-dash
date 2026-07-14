# forge-daycare/ — Working Notes (read root CLAUDE.md and NORTH_STAR.md first)

Read `../NORTH_STAR.md` (the constitution) and `../CLAUDE.md` (the operating
manual) first, then `README.md` in this folder. This file is the "stuck"
anchor for this folder specifically.

## What lives here

Business config, the business brief, and the Supabase schema for "A Touch of
Blessings Learning Academy" — **not** an agent engine. The engines that read
this folder (`daycare_supabase.py`, `daycare_growth.py`, `daycare_blast.py`,
`daycare_ghl.py`, `daycare_context.py`, and Solomon/Nora/Nova) all live in
`forge rei/`. `config/daycare.env` is real, git-ignored config (never served
over HTTP); `config/daycare.env.example` is the committed template.

## What's scoped here (don't let it drift)

- **The business brief** (`skills/daycare-context.md`,
  `skills/enrollment-ad-agent.md`) — owner-edited directly, no vault copy,
  mtime-hot-reloaded by `daycare_context.py`. If you're updating a business
  fact (a location, an offer, current enrollment), edit it here.
- **The Supabase schema** (`supabase/migrations/`) — kept byte-identical to
  the separate parent/staff app's migrations (see `supabase/README.md` for the
  exact change-control contract). Never applied automatically from this repo.
- **Secrets** — real values only in `config/daycare.env`, never in this
  folder's markdown, never in `NORTH_STAR.md` (which lists env var NAMES only).

## Where the agent playbooks actually are

This folder holds no playbook of its own — Solomon/Nora/Nova's seed skills
live in `forge-solomon/`, `forge-nora/`, `forge-nova/` respectively (each
folder's own `CLAUDE.md`), and their learned playbooks live in the vault. This
folder is what those agents *read from*, not where they *live*.

## If stuck

1. `../NORTH_STAR.md` §5 (Daycare operating section) + §6 (brains & skills map).
2. `../CLAUDE.md` §10 (Daycare OS — the full technical section: Supabase
   project, autoadmin, Stripe, GHL, Solomon).
3. `README.md` in this folder for the file map + secrets policy.

## Cross-Agent Coaching Network

Solomon, Nora, and Nova are nodes in the FORGE coaching network
(`forge rei/agent_coach.py`): they can **ask peers** questions and **broadcast a
transferable insight** — and absorb insights coached over from the agency/REI agents (e.g.
an ad angle from Eco) — folded into each agent's next `learn()` automatically. **Knowledge
only** — never creds, family data, tokens, or an outward instruction; SMS / invoice / ad
launch stay approval-gated per `../CLAUDE.md` rule 2. Details: root `CLAUDE.md` §11.
