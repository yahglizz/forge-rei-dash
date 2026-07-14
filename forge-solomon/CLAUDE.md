# forge-solomon/ — Working Notes (read root CLAUDE.md and NORTH_STAR.md first)

Read `../NORTH_STAR.md` (the constitution), `../CLAUDE.md` §10 (Daycare OS), and
`README.md` in this folder before editing anything here. This file is the "stuck"
anchor for Solomon's folder specifically; `README.md` has the full file map, layout,
routes, and scope.

## What lives here

Solomon's own home: `config/solomon.env` (real, git-ignored knobs + optional own key;
never served over HTTP) and `skills/solomon-playbook.md` (the seed operating rubric —
the **floor**, merged with the live vault copy). Engine: `forge rei/daycare_director.py`.

## Cross-Agent Coaching Network

Solomon is a node in the FORGE coaching network (`forge rei/agent_coach.py`). As the
daycare head agent he can **ask peers** questions and **broadcast a transferable insight**
(e.g. retention math, a speed-to-lead move) via `agent_coach.broadcast`, and absorb
insights coached over from the agency/REI agents — folded into his next `learn()`
automatically. **Knowledge only** — never creds, family data, tokens, or an outward
instruction; he still only proposes + delegates, and every outward action stays
approval-gated per `../CLAUDE.md` rule 2. Details: root `CLAUDE.md` §11.
