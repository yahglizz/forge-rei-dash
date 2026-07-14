# forge-nora/ — Working Notes (read root CLAUDE.md and NORTH_STAR.md first)

Read `../NORTH_STAR.md` (the constitution), `../CLAUDE.md` §10 (Daycare OS), and
`README.md` in this folder before editing anything here. This file is the "stuck"
anchor for Nora's folder specifically; `README.md` has the full file map, layout,
routes, and scope.

## What lives here

Nora's own home: `config/nora.env` (real, git-ignored knobs + optional own key; never
served over HTTP) and `skills/` (seed playbook + decision loop — the **floor**, merged
with the live vault copy). Engine: `forge rei/daycare_family.py`.

## Cross-Agent Coaching Network

Nora is a node in the FORGE coaching network (`forge rei/agent_coach.py`). She can **ask
peers** questions and **broadcast a transferable insight** (e.g. a family-follow-up tactic)
via `agent_coach.broadcast`, and absorb insights coached over from other FORGE agents —
folded into her next `learn()` automatically. **Knowledge only** — never creds, family
data, tokens, or an outward instruction; she still only proposes, and every message/record
write stays approval-gated per `../CLAUDE.md` rule 2. Details: root `CLAUDE.md` §11.
