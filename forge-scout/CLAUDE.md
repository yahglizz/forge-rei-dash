# forge-scout/ — Working Notes (read root CLAUDE.md first)

Read `../CLAUDE.md` (the operating manual) and `README.md` in this folder
before editing anything here. This file is the "stuck" anchor for this folder
specifically.

## What lives here

Scout's own home, separate from the web app and from the other agents' keys.
`config/scout.env` is real, git-ignored config (never served over HTTP);
`config/scout.env.example` is the committed template. `skills/scout-playbook.md`
is the seed triage rubric — the **floor**, not the live rubric.

## What Scout is scoped to do (don't let it drift)

Scout **finds + ranks + organizes** — scores motivation, buckets asap/warm/
nurture/dead, tags + pipeline, hands call-worthy leads to Marcus.
**Scout never texts a seller.** If a change would make Scout send an outbound
SMS directly instead of proposing/handing off, that's out of scope — flag it,
don't build it silently. Marcus owns all outbound (`../CLAUDE.md` rule 3).

## Where the live playbook actually is

The seed here is the floor. Scout's `learn()` loop rewrites the LIVE playbook
into the vault (`vault/Skills/scout-playbook.md`), git-committed, mtime-reloaded
every sweep. Read the vault copy to see what Scout currently "knows," not this
folder's seed.

## If stuck

1. `../CLAUDE.md` §5 (agent table) + §2 rule 2's HOT-lead auto-tag exception —
   the ONLY autonomous-without-approval action Scout takes.
2. `README.md` in this folder for the file map + what each file does.
3. `~/.claude/skills/forge-self-improving-agent/SKILL.md` — canonical recipe,
   Scout is the reference implementation it was extracted from.

## Cross-Agent Coaching Network

Scout is a node in the FORGE coaching network (`forge rei/agent_coach.py`). It can **ask
peers** questions and **broadcast a transferable insight** (e.g. a motivation-signal tell)
via `agent_coach.broadcast`; peer insights addressed to Scout fold into its next `learn()`
automatically. **Knowledge only** — never creds, client data, or an outward instruction;
tagging/pipeline/handoff autonomy is unchanged. Details: root `CLAUDE.md` §11.
