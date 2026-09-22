# FORGE — Agents

One card per agent, filed under the business it serves. **Eight agents, four
businesses, plus one cross-business Chief of Staff** — and four engines
with no brain of their own (Follow-up, ACE, Autopilot, the daily brief / recap).

| Business | Agents |
|---|---|
| [Portfolio](portfolio/) (cross-business) | [Orion](portfolio/orion.md) · [Daily brief / recap](portfolio/briefs.md) |
| [Wholesale · REI](wholesale/) | [Scout](wholesale/scout.md) · [Marcus](wholesale/marcus.md) · [Atlas](wholesale/atlas.md) · [Follow-up](wholesale/followup.md) · [ACE](wholesale/ace.md) · [Autopilot](wholesale/autopilot.md) |
| [Agency · ClientForge](agency/) | [Dyson](agency/dyson.md) · [Eco](agency/eco.md) |
| [Daycare](daycare/) | [Solomon](daycare/solomon.md) |
| [Dropship](dropship/) | [Midas](dropship/midas.md) |

## What these files are — and are not

**These are reference cards. They are documentation, not behavior.** Editing a
card changes nothing about how an agent acts. Each card *points at* the files
that are actually loaded at runtime:

| Layer | Lives in | Who rewrites it | Editing it changes behavior? |
|---|---|---|---|
| **Creed** (evidence discipline) | `forge-*/skills/<business>-evidence-discipline.md` | Human only — `learn()` cannot see it | **Yes** |
| **Top skills** | `forge-*/skills/*.md` | Human only (`_playbook_only` shields them) | **Yes** |
| **Playbook** (learned) | vault `Skills/<agent>-playbook.md` | The agent's own `learn()` | **Yes** |
| **This card** | `agents/<business>/<agent>.md` | Human only | **No** |

Rank order inside every prompt: **creed → top skills → learned playbook.** When
the creed and the playbook disagree, the creed wins. See `CLAUDE.md` §4a.

## The one rule that governs all of them

**Propose → review → execute.** No agent takes an outward or irreversible action
on its own. The only autonomous acts are: score/triage, apply internal+reversible
tags, read the brain, rewrite their own playbook, and post on the agent bus.

Each card's **Autonomy** section states exactly where that line sits for that
agent, including the deliberate exceptions.

## Keeping these honest

`CLAUDE.md` §2 (autonomy rules) and §5 (agent table) stay canonical. When an
agent's scope changes, update `CLAUDE.md` first, then its card here.

Roster in code: `forge rei/agents_hub.py` (`AGENTS`; `registry()` for the Control Center). Creed map:
`forge rei/agent_creed.py:28` (`CREED_FILE`).

Follow-up, ACE, Autopilot and the daily brief / recap have no brain of their own;
their roster entry carries `chatVia` (Marcus, or Orion for the briefs), which answers
for them in chat and sees their tasks. Every roster agent shows in the Agent Control
Center (`/api/agents/registry`, `agents_hub.registry()`).
