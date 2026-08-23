# FORGE — Agents

One card per agent, filed under the business it serves. **Eight agents, four
businesses, plus one cross-business Chief of Staff.**

| Business | Agents |
|---|---|
| [Portfolio](portfolio/) (cross-business) | [Orion](portfolio/orion.md) |
| [Wholesale · REI](wholesale/) | [Scout](wholesale/scout.md) · [Marcus](wholesale/marcus.md) · [Atlas](wholesale/atlas.md) |
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

Roster in code: `forge rei/agents_hub.py:55` (`AGENTS`). Creed map:
`forge rei/agent_creed.py:28` (`CREED_FILE`).

> **Known drift, 2026-08-23:** `agents_hub.AGENTS` lists seven agents — Orion is
> absent from it, though he is instantiated at `forge rei/connector.py:1039` and
> serves `/api/mission-control/brief`. He therefore does not appear in the Agents
> hub, the Agent Office floor, or `/api/hub/roster`. Documented in
> [portfolio/orion.md](portfolio/orion.md); not "fixed" here because adding him
> to the hub roster is a behavior change, not a docs change.
