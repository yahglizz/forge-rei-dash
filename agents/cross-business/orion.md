# Orion — Chief of Staff (cross-business CEO brief)

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Cross-business · hub id `orion` · emoji 🧭 · roster business `cross` |
| Job | Reads what every agent produced and writes the daily "attack today" brief: one focus, one idea, ranked priorities. Proposes only. Also answers chat for the daily brief / recap ([briefs](briefs.md)). |
| Engine | `forge rei/mission_control_agent.py` → `OrionEngine` (`mission_control_agent.py:72`), built `connector.py:1067` as `ORION` |
| Seed folder | `forge-mission/skills/` (`orion-playbook.md`) |

## 2. Triggers

**Scheduled** — no thread of its own. Runs inside the `brief` thread.

| Field | Value |
|---|---|
| Thread | `brief` (`connector.py:5177`) → `_brief_scheduler_forever` (`:2112`) → `_maybe_ceo_brief` (`:2088`) → `ORION.maybe_daily()` |
| Gate | `FORGE_MARCUS` != `0` (scheduler returns immediately otherwise); never retired |
| Hour | `FORGE_MISSION_BRIEF_HOUR`, default 7, in fixed offset `FORGE_TZ_OFFSET` (default −4) |
| Check tick | `FORGE_BRIEF_CHECK_SEC` 300 (min 60), 90 s startup delay |
| Clock-out | whole scheduler tick skipped on `forge_ops.paused()` |
| Once/day | `last_build_day` set only on success — a failure retries next tick |
| Telegram push | `FORGE_MISSION_BRIEF_TELEGRAM=1` (default 0), dedupe `ceo_brief:<date>` |
| Heartbeat | `daily_brief` (shared with the briefs) |

**Telegram:** **no `/orion` command and no name trigger** (`telegram_io.py:670-683`). Orion can never be the active Telegram agent, so `/task` cannot reach him from Telegram.

**HTTP** (private network + Host + same-origin POST)

| Method | Routes |
|---|---|
| GET | `/api/mission-control` · `/api/mission-control/brief` (cached, free) · `/api/mission-control/brief/overview` |
| POST | `/api/mission-control/brief/run` (paid rebuild) · `/api/mission-control/brief/learn` |

**Bus:** no inbox; reads `agent_bus.recent(30)` (last 20) as input.

**UI:** Mission Control greeting card (`mission_control.jsx:343`), Refresh = `brief/run` · Agent Control Center `orion` · not on the Agent Office floor.

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

- `/api/hub/chat {agentId:"orion"}` (dashboard/Agent Control Center only) → `_director_chat` with `_DIRECTOR["cross"]` (`agents_hub.py:284`): NORTH_STAR as brief → latest brief → `eng._playbook()[:4000]` → `open_tasks_block("orion")` (includes tasks filed for `briefs`) → `caveman.block()`.
- Tasks: `/api/hub/task {agentId:"orion"}`; visible only in chat — the scheduled brief does not read tasks.

## 8. Cost

Claude: yes — one scheduled call/day (2400 tok) + learn, manual runs, chat. Scheduled call bills to **`brief`** (no `orion` bucket); HTTP → `operator`.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/mission-control/brief | jq '{generatedAt,briefCount,error}'
curl -s localhost:7799/api/mission-control/brief/overview | jq 'keys'
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="orion")|{status,lastSuccessAt,lastError}'
```
