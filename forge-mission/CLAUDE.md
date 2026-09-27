# forge-mission/ — Working Notes (read root CLAUDE.md first)

Read `../CLAUDE.md` (the operating manual) and `../agents/cross-business/orion.md`
(Orion's card — triggers, gates, routes) before editing anything here. This file is
the "stuck" anchor for this folder specifically.

## What lives here

Orion's own home (the cross-business chief of staff). `config/mission.env` is real,
git-ignored config (never served over HTTP); `config/mission.env.example` is the
committed template. `skills/orion-playbook.md` is the seed rubric — the **floor**,
not the live rubric.

Engine: `../forge rei/mission_control_agent.py` (`OrionEngine`, `MISSION_DIR` points
here). State: `marcus_state/mission_brief.json`.

## What Orion is scoped to do (don't let it drift)

Orion **reads** what every other agent produced and writes ONE daily "attack today"
brief on Mission Control (one focus, one idea, ranked priorities). **Read-only +
propose.** He never texts, posts, moves pipeline, spends, or writes another agent's
data. Optional Telegram push of the brief (`FORGE_MISSION_BRIEF_TELEGRAM=1`) is the
only outward thing, and it goes to the operator only.

## When he runs

No thread of his own — runs inside the `brief` thread once a day past
`FORGE_MISSION_BRIEF_HOUR` (default 7, `FORGE_TZ_OFFSET` zone), box only
(`FORGE_MARCUS=1`), skipped on `forge_ops` clock-out. A failed build retries next
tick. Manual: Mission Control → Refresh (`POST /api/mission-control/brief/run`).
Self-improves after `FORGE_MISSION_LEARN_EVERY` (10) briefs.

## Where the live playbook actually is

`learn()` rewrites the LIVE playbook into the vault (`vault/Skills/orion-playbook.md`),
git-committed, mtime-reloaded every run. Vault copy wins over this seed.

## If stuck

1. `../agents/cross-business/orion.md` — the verified card.
2. `../CLAUDE.md` §5 (agent table) + §9 (Mission Control / Owner Actions).
3. `~/.claude/skills/forge-self-improving-agent/SKILL.md` — the agent recipe.
