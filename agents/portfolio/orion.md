# Orion — Chief of Staff

**Business:** Portfolio (cross-business) · **Emoji:** 🧭 · **Roster id:** `orion`
**Role:** sits *above* the four business directors.

Every morning Orion reads what each business's agents actually produced — their
cached operating briefs, what they broadcast on the agent bus, the cross-agent
coaching insights, new client requests, trending-product signal — and synthesizes
**one ranked "attack today" brief**: the single thing to focus on, a fresh idea to
act on now, and the top priorities across the whole portfolio.

He greets you the moment the dashboard opens. Mission Control reads the **cached**
brief (instant and free); a paid Claude call runs once a day on the box, or when
you tap Refresh.

## Autonomy — where the line sits

**Read-only and propose.** Orion never takes an outward action — he tells you what
to attack. He grounds every recommendation in a signal an agent actually
reported, never a guess.

## ⚠️ Not in the hub roster

Orion is instantiated at `forge rei/connector.py:1039` and serves
`/api/mission-control/brief`, but he is **absent from `agents_hub.AGENTS`**
(`forge rei/agents_hub.py:55`, which lists seven). Consequences:

- he does not appear in the **Agents** hub in any workspace
- he does not appear on the **Agent Office** floor
- `/api/hub/roster` does not return him
- `/task orion …` in Telegram has no roster entry to route to
- `CLAUDE.md` §5 says "Seven agents, on purpose" and does not list him

He still runs and still produces the Mission Control brief. Adding him to the
roster is a behavior change, not a docs change, so it is recorded here rather
than done silently.

## Where it lives

- **Engine:** `forge rei/mission_control_agent.py` → `OrionEngine`
- **Config + seed skills:** `forge-mission/skills/`
- **Creed:** none. `agent_creed.CREED_FILE` covers four *businesses*; Orion is cross-business. His grounding rule lives in his own prompt and docstring: every recommendation traces to a signal an agent actually reported.
- **Learned playbook:** vault `Skills/orion-playbook.md` (`PLAYBOOK_MD` at `mission_control_agent.py:31`)
- **State:** `marcus_state/mission_brief.json`

## Routes

`/api/mission-control` · `/api/mission-control/brief` · `/api/mission-control/brief/overview`
POST: `/api/mission-control/brief/run` · `/api/mission-control/brief/learn`

## Knobs

| Env | Effect |
|---|---|
| `FORGE_MISSION_BRIEF_HOUR` | Hour after which the daily brief builds |
| `FORGE_MISSION_BRIEF_TELEGRAM` | Push "🧭 Orion — today's focus" to Telegram |
| `FORGE_MISSION_LEARN_EVERY` | Self-improve cadence |
| `FORGE_BRIEF_CHECK_SEC` | How often the loop checks whether it is time |
