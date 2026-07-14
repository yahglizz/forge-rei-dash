# forge-nova/ — Working Notes (read root CLAUDE.md and NORTH_STAR.md first)

Read `../NORTH_STAR.md` (the constitution), `../CLAUDE.md` §10 (Daycare OS), and
`README.md` in this folder before editing anything here. This file is the "stuck"
anchor for Nova's folder specifically; `README.md` has the full file map, layout,
routes, and scope.

## What lives here

Nova's own home: `config/nova.env` (real, git-ignored knobs + optional own key; never
served over HTTP) and `skills/` (seed playbook + decision loop — the **floor**, merged
with the live vault copy). Engine: `forge rei/daycare_adops.py`.

## Cross-Agent Coaching Network

Nova is a node in the FORGE coaching network (`forge rei/agent_coach.py`). She can **ask
peers** questions and **broadcast a transferable insight** via `agent_coach.broadcast`, and
absorb insights coached over from the agency ad agent (Eco) — e.g. a carousel angle beating
single-image, adapted to enrollment ads — folded into her next `learn()` automatically.
**Knowledge only** — never creds, tokens, or an outward instruction; she still only
recommends, and every spend/launch stays a one-tap owner approval per `../CLAUDE.md` rule 2.
Details: root `CLAUDE.md` §11.
