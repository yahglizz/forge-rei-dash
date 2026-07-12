# forge-marcus/ — Working Notes (read root CLAUDE.md first)

Read `../CLAUDE.md` (the operating manual) and `README.md` in this folder
before editing anything here. This file is the "stuck" anchor for this folder
specifically.

## What lives here

Marcus's own home, separate from the web app and from the other agents' keys —
AND the home of Atlas's seed skill (`skills/atlas-underwriter.md`). Atlas
(`deal_prep.py`) has no folder of its own by design: "Atlas reports to Marcus"
is literal, not just a phrase, so his skill rides on Marcus's team folder.
`config/marcus.env` is real, git-ignored config shared by Marcus and Atlas
(never served over HTTP); `config/marcus.env.example` is the committed
template. Every `skills/*.md` file here is a seed — the **floor**, not the
live rubric.

## What Marcus is scoped to do (don't let this drift)

Marcus is the **chief**: the only agent that ever sends a seller SMS
(`marcus_engine._send` / `marcus_screening.send_nurture`, both gated behind
`sms_guard.guard`), the screening front door Scout hands every call-worthy
lead to, and — via `marcus_lead.py` — the one who surveys the whole operation
and directs Scout + the operator. **If a change would let Scout or Atlas call
GHL's outbound-message endpoint directly, or bypass `sms_guard`, that's out of
scope — flag it, don't build it silently.** Marcus owns all outbound
(`../CLAUDE.md` rule 3). Marcus is not a closer: never negotiates, never
writes a contract, never states a price/offer over text unless the seller
already gave one first.

## Where the live playbooks actually are

The seeds here are the floor. Each agent's `learn()` loop rewrites its own
LIVE playbook into the vault, git-committed, mtime-reloaded on the next run —
read the vault copy to see what an agent currently "knows," not this folder's
seed:

- Marcus screening → `vault/Skills/marcus-screening-playbook.md`
- Marcus texting voice/behavior → `vault/Skills/marcus-playbook.md` (written
  by the daily `style_agent.py`/weekly `review_agent.py` loops, not this
  folder's seed set)
- Atlas underwriting → `vault/Skills/atlas-underwriter.md` (`DealPrep.learn()`
  in `deal_prep.py`, same pattern as Scout/Marcus)

## If stuck

1. `../CLAUDE.md` §5 (agent table) — Marcus's and Atlas's autonomy boundaries.
2. `README.md` in this folder for the full file map, the chain-of-command
   section, and what each skill file does.
3. `~/.claude/skills/forge-self-improving-agent/SKILL.md` — canonical recipe
   (extracted from Scout); Marcus and Atlas both follow the same shape.
