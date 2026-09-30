# forge-solomon/ — instructions for Codex (and any non-Claude agent)

Codex reads `AGENTS.md`, not `CLAUDE.md`. The canonical rules are in `../CLAUDE.md` (§2 rule 2,
§10 Daycare OS) and `../NORTH_STAR.md`; this file is the short contract for Solomon's folder.

## What Solomon is
The daycare's ONE agent — a **growth director**: more families touring, starting, staying.
Paperwork, compliance, billing collection, staff admin are **not** his lane (owner decision
2026-09-30). Do not add that guidance back to his skills, brief prompt or playbooks;
`daycare_director._paperwork_drift` rejects a `learn()` rewrite that does.

## Files
- `skills/` — seed skills: `daycare-evidence-discipline.md` (creed, injected by
  `agent_creed`, never reachable by `learn()`), `solomon-decision-loop.md`,
  `solomon-director-craft.md` (growth craft), `solomon-systems-craft.md`,
  `solomon-roster-craft.md` (seats + retention), `solomon-adops-craft.md`, `solomon-playbook.md`
  (floor; the learned copy is the vault `Skills/solomon-playbook.md`).
- `../forge-daycare/skills/daycare-context.md` (business facts, read FIRST),
  `daycare-parent-reply.md` (verified fact sheet + §2b lead-qualifying ladder),
  `daycare-voice.md` — what the Replies lane texts parents.
- Engines: `../forge rei/daycare_director.py` (brief), `daycare_replies.py`,
  `daycare_leads.py`, `daycare_starts.py`. Card: `../agents/daycare/solomon.md`.

## Autonomy (do not loosen)
Propose → owner taps. Only exception: `FORGE_DAYCARE_REPLY_AUTO=1` (default OFF, operator
flips it) auto-sends a clean, flag-free answer to an enrollment **lead** in safe categories.
Never a price/rate/seat/start-date promise, never safety/billing/custody/medical. Unknown
question or escalation → Telegram ping to the owner (`notify_owner`).
Wording rule: CCIS = "we help families through the **process**" — never "we handle/do the paperwork".

## Validate (run from `../forge rei`)
```bash
python3 test_solomon_growth.py && python3 test_daycare_replies.py && python3 test_agents_docs.py
python3 -c "import ast; ast.parse(open('daycare_replies.py').read())"
./deploy/push.sh root@24.199.81.124     # or: git push origin main (box self-deploys in ≤60 s)
```
No Anthropic credits? Eval the prompt without spending: monkeypatch `review_agent._claude` to
capture (system, user) on the box, then judge the brief by hand — see the `solomon-growth-only` memory.
