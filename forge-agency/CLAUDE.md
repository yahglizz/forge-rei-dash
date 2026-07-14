# forge-agency/ — Working Notes (read root CLAUDE.md first)

Read `../CLAUDE.md` (the operating manual) and `README.md` in this folder
(file map + key resolution) before editing anything here. This file is the
"stuck" anchor for this folder specifically.

## What lives here

Agency (ClientForge) config only — separate GHL sub-account, separate keys from
wholesale. `config/agency.env` is the real, git-ignored secrets file (never
served over HTTP, never rotated without being told); `config/agency.env.example`
is the committed template. `skills/` holds seed playbooks for Dyson/Eco — the
**floor**, not the live rubric.

## Where the live playbook actually is

`skills/*.md` here is the seed. The agents' `learn()` loop overwrites the LIVE,
current playbook into the Obsidian vault (`vault/Skills/dyson-playbook.md`,
`vault/Skills/eco-playbook.md`), git-committed there, and agents mtime-reload
from the vault on every run. If you're trying to see what an agent currently
"knows," read the vault copy, not the seed in this folder.

## If stuck

1. `../CLAUDE.md` §5 (agent table) for what Dyson/Eco are scoped to do.
2. `README.md` in this folder for the exact key-resolution path
   (`AGENCY_ENV_CANDIDATES[0]` in `connector.py`).
3. `~/.claude/skills/forge-self-improving-agent/SKILL.md` — the canonical
   recipe if you're adding/upgrading an agent, not inventing a new shape.

## Hard rule specific to this folder

Agency and wholesale never share a key file. Wholesale keys belong in
`../marcus-wholesale-agent/` only — don't cross-wire them here.

## Cross-Agent Coaching Network

Dyson and Eco are nodes in the FORGE coaching network (`forge rei/agent_coach.py`). They can
**ask peers** questions and **broadcast a transferable insight** — e.g. Eco sees a carousel
angle beating single-image and coaches the daycare ad agent (Nova) — via
`agent_coach.broadcast`; peer insights addressed to them fold into the next `learn()`
automatically. **Knowledge only** — never creds, client data, tokens, or an outward
instruction (the isolation in this folder's hard rule holds); ad launches stay
approval-gated. Details: root `CLAUDE.md` §11.
