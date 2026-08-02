# forge-dropship/ — Working Notes (read root CLAUDE.md and NORTH_STAR.md first)

Read `../NORTH_STAR.md` (the constitution), `../CLAUDE.md` (the operating manual), and
`README.md` in this folder before editing anything here. This file is the "stuck" anchor
for the dropship folder specifically.

## What lives here

Midas's home: `config/dropship.env` (real keys — Shopify, AutoDS, Meta — +
knobs + optional own Claude key; git-ignored, never served over HTTP) and `skills/` (the
seed playbooks + the creed + Midas's top skills — the **floor**, merged with the live
vault copies).

## Where the live playbook actually is

`skills/midas-playbook.md` here is the seed. `learn()` overwrites the LIVE, current
playbook into the Obsidian vault (`vault/Skills/midas-playbook.md`), git-committed there,
and Midas mtime-reloads from the vault on every run. To see what an agent currently "knows,"
read the vault copy, not the seed here.

The **creed** (`dropship-evidence-discipline.md`) and Midas's **top skills** — always-on
(`midas-decision-loop.md`, `midas-craft.md`, `dropship-account-health.md`) plus 7 more
lane-gated SOPs (`MidasEngine.LANE_SKILLS`) and 1 on-demand (`dropship-store-setup.md`,
chat only) — are human-owned and NEVER rewritten by `learn()` — the creed is injected via
`agent_creed.block("dropship")` (invisible to learn), the top/lane/on-demand skills load
via `_load_skills()`/`top_skills_text()` while `_playbook_only()` feeds learn. Self-check:
`cd "forge rei" && python3 test_dropship_skills.py`.

## If stuck

1. `../CLAUDE.md` rule 2 (autonomy) + §5 (agent table) for what Midas is scoped to do.
2. `README.md` in this folder for the file map.
3. `forge rei/daycare_director.py` (`SolomonEngine`) — the sibling engine, same shape
   (one director, several lanes in one brief).

## Hard rule specific to this folder

Dropship keys never share a file with wholesale / agency / daycare. Its GHL sub-account (if
used) stays isolated in `config/dropship.env` only — don't cross-wire.

## Cross-Agent Coaching Network

Midas is a node in the FORGE coaching network
(`forge rei/agent_coach.py`) — knowledge only, never creds/customer-data/tokens or an
outward instruction; ad launches + supplier orders stay approval-gated. Details: root
`CLAUDE.md` §11.
