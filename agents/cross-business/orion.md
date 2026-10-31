# Orion — Chief of Staff (cross-business CEO brief)

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-09-22; Telegram routing, scheduled-brief gate and the `connector.py` cites re-checked 2026-10-31 (other line cites not re-checked).

## 1. Identity

| | |
|---|---|
| Business | Cross-business · hub id `orion` · emoji 🧭 · roster business `cross` |
| Job | Reads what every agent produced and writes the daily "attack today" brief: one focus, one idea, ranked priorities. Proposes only. Also answers chat for the daily brief / recap ([briefs](briefs.md)). |
| Engine | `forge rei/mission_control_agent.py` → `OrionEngine` (`mission_control_agent.py:72`), built `connector.py:1144` as `ORION` |
| Seed folder | `forge-mission/skills/` (`orion-playbook.md`) |

## 2. Triggers

**Scheduled** — no thread of its own. Runs inside the `brief` thread.

| Field | Value |
|---|---|
| Thread | `brief` (`connector.py:6116`) → `_brief_scheduler_forever` (`:2301`) → `_maybe_ceo_brief` (`:2271`) → `ORION.maybe_daily()` |
| Gate | `FORGE_MARCUS` != `0` (scheduler returns immediately otherwise) **and** `FORGE_BRIEFS=1` (`BRIEFS_ON`, `connector.py:2298`, **default off** since the 2026-09-30 cut); the thread itself stays up for the git-sync watchdog |
| Hour | `FORGE_MISSION_BRIEF_HOUR`, default 7, in fixed offset `FORGE_TZ_OFFSET` (default −4) |
| Check tick | `FORGE_BRIEF_CHECK_SEC` 300 (min 60), 90 s startup delay |
| Clock-out | whole scheduler tick skipped on `forge_ops.paused()` |
| Once/day | `last_build_day` set only on success — a failure retries next tick |
| Telegram push | `FORGE_MISSION_BRIEF_TELEGRAM=1` (default 0), dedupe `ceo_brief:<date>` |
| Heartbeat | `daily_brief` (shared with the briefs; reads "briefs off · sync watchdog" while `FORGE_BRIEFS` is off) |

**Telegram:** `/orion` and the trigger word (`orion, …` / `orion: …` / `orion — …`) switch the chat to Orion (`_AGENT_ALIASES` `telegram_io.py:778`, `_AGENT_TRIGGER` `:787`). He is the default agent of the HQ chat (`_default_agent`, `telegram_io.py:1226`) and works only there: in a bound business chat the switch is refused with a pointer to HQ (`telegram_io.py:1087`). Chat runs through `telegram_agent.chat` (HQ scope: health, API cost, what's down). `/task <title>` while Orion is active files it with `agents_hub.send_task("orion", …)` (`telegram_io.py:1118`); the scheduled brief still does not read tasks.

**HTTP** (private network + Host + same-origin POST)

| Method | Routes |
|---|---|
| GET | `/api/mission-control` · `/api/mission-control/brief` (cached, free) · `/api/mission-control/brief/overview` |
| POST | `/api/mission-control/brief/run` (paid rebuild) · `/api/mission-control/brief/learn` |

**Bus:** no inbox; reads `agent_bus.recent(30)` (last 20) as input.

**UI:** Mission Control greeting card (`mission_control.jsx:343`), Refresh = `brief/run` · Agent Control Center `orion` · Agent Office: Meshy 3D character with idle/walk/talk animations, typed chat and browser voice controls. `/api/office/plan` proposes validated assignments; the owner taps Approve & assign before `/api/office/task` starts each agent’s real analytical job. Orion→agent assignment and agent→Orion completion receipts animate the floor.

## 3. Reads / context load order

`_gather` (`mission_control_agent.py:140`, no Claude): Scout summary + screener queue · `agency_agents.status()`, fresh client requests, pending agency approvals · Solomon status + brief headline · Midas + dropship stats (only if not archived) · bus · `agent_coach.feed`. Archived businesses are dropped and listed under `archived`.

System prompt: inline rules → `north_star.context_block()` → playbook [:3500] (seed `orion-playbook.md` + vault `Skills/orion-playbook.md`). **No creed** (`BUSINESS["cross"]["creed"] = ""`), no top skills.

## 4. Outputs / writes

- `marcus_state/mission_brief.json`.
- Vault `Reports/ceo-brief-<day>.md`, `Skills/orion-playbook.md`.
- Bus note `orion→all`. Optional Telegram "🧭 Orion — today's focus".

## 5. Autonomy & gates

Read-only, propose only; every recommendation must trace to a signal an agent reported. Key: `MISSION_ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY` → agency → Midas key → review key.

## 6. Self-improvement

`_maybe_learn` after every `build_brief` (scheduled or manual): `FORGE_MISSION_LEARN_EVERY` (10 briefs), no time gap. Writes vault `Skills/orion-playbook.md`. Manual: POST `/api/mission-control/brief/learn`.

## 7. Chat & tasks

- `/api/hub/chat {agentId:"orion"}` (dashboard and Agent Control Center; the HQ Telegram chat uses `telegram_agent.chat` instead) → `_director_chat` with `_DIRECTOR["cross"]` (`agents_hub.py:284`): NORTH_STAR as brief → latest brief → `eng._playbook()[:4000]` → `open_tasks_block("orion")` (includes tasks filed for `briefs`) → `caveman.block()`.
- Tasks: `/api/hub/task {agentId:"orion"}` or Telegram `/task` in the HQ chat; visible only in chat — the scheduled brief does not read tasks.
- **Live data (2026-10-18):** `_director_chat` runs `dash_live.ask` — read-only `api_get`/`route_help` over the HQ scope **plus all four business scopes** (`dash_live.businesses`), ≤4 tool turns, no writes. Placement: cross-business surfaces (Mission Control, Agent Control Center) + every workspace's Agent Office floor, where his check-in/plan/chat cover that floor's agent only; a workspace hub/mobile portal or a bound Telegram business chat refuses him with a pointer to HQ. Knob `FORGE_CHAT_LIVE=0`.

## 8. Cost

Claude: yes — one scheduled call/day (2400 tok) + learn, manual runs, chat. Scheduled call bills to **`brief`** (no `orion` bucket); HTTP → `operator`.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/mission-control/brief | jq '{generatedAt,briefCount,error}'
curl -s localhost:7799/api/mission-control/brief/overview | jq 'keys'
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="orion")|{status,lastSuccessAt,lastError}'
```

## 10. Keys, MCPs and task file

This card is the agent's canonical task file; runtime prompts still load skills from `forge-mission/skills/` — doc pointer only.

Head agent over Marcus, Dyson, Solomon and Midas: reads their state, proposes assignments, cannot send or spend. Table: [ENV-MAP, Orion](../ENV-MAP.md#orion-head-agent-cross-business).

- Key chain: `MISSION_ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY` → agency → Midas → review (wholesale) key. master.env: no mission label; fallbacks `ANTHROPIC_API_KEY__AGENCY` and `__WHOLESALE` are OK.
- Other names: `TELEGRAM_BOT_TOKEN` (OK), `TELEGRAM_CHAT_ID` (CONFIG), `TELEGRAM_ALLOWED_IDS` (EMPTY, not blocking). Knobs: `FORGE_MISSION_BRIEF_HOUR`, `FORGE_MISSION_LEARN_EVERY`, `FORGE_TZ_OFFSET`, `FORGE_MISSION_BRIEF_TELEGRAM`, `FORGE_BRIEFS`.
- Suggested MCPs (not read from code): brain, scheduled-tasks, Vercel (runtime logs).
