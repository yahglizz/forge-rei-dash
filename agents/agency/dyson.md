# Dyson — Build Agent

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Agency (ClientForge) · hub id `dyson` · emoji 🛠️ |
| Job | Plans client website/code edits and drafts the file changes. Nothing ships until approved. |
| Engine | `forge rei/agency_agents.py` (`_AGENTS`, `agency_agents.py:52`; chat/task/learn) + `forge rei/agency_dyson.py` (drafts, apply) |
| Seed folder | `forge-agency/skills/` |

## 2. Triggers

**Scheduled loop:** none. No thread, no heartbeat, no `FORGE_MARCUS` gate. (`cost_tracker.AGENT_THREADS` lists `dyson`, but no thread carries that name.)

**Telegram**

| Form | Effect |
|---|---|
| `/dyson` · `dyson, …` / `dyson: …` / `dyson — …` | chat → `_tg_agency_chat` → `agency_agents.chat` (`connector.py:2350`) |
| `/task <title>` while Dyson is active | `_tg_agency_task` → `agency_agents.send_task` — Agency board only, **not** the hub task store (`telegram_io.py:931`) |
| Taps `dysonplan` / `dysongo` / `dysonno` | generate a plan / approve / reject (`connector.py:2219-2223`) |

**HTTP** (private network + Host + same-origin POST; no session)

| Method | Routes |
|---|---|
| GET | `/api/agency/agents` · `/agents/history?agent=` · `/agents/tasks?agent=` · `/api/agency/dyson/drafts` |
| POST | `/api/agency/agents/chat` · `/task` · `/task/update` · `/learn` · `/api/agency/dyson/generate` · `/dyson/decision` |

**Handoffs in:** hub `send_task` mirrors into `agency_agents.send_task` (`agents_hub.py:490`) · Edit Requests "Plan with Dyson" → `/api/agency/dyson/generate` (`agency_requests.jsx:104`).

**Bus:** sends as `dyson` (task queued, playbook updated, `dyson_plan` note → Telegram approve button, apply result). **Reads nothing** — hub `task` bus messages to `dyson` go unconsumed; tasks arrive via `open_tasks_block`.

**UI:** `window.AgencyDyson` (route key `Dyson`, `app.jsx:47`) — reached from the Agents hub Console tab or Edit Requests, not the sidebar · Agency Approvals · Agent Control Center `dyson` · Agent Office (Agency room) · mobile Agents.

## 3. Reads / context load order

Chat / send_task (`agency_agents.py:412`, `_skills_block` :286):
1. agent system prompt
2. LIVE CONTEXT (`_dyson_context`: open requests + draft count)
3. `north_star.context_block()`
4. creed `agent_creed.block("agency")` → `agency-evidence-discipline.md`
5. `agency-marketing-methodology.md` [:5000]
6. `agency-site-build-methodology.md` [:5000]
7. playbook: seed `dyson-playbook.md` + vault `Skills/dyson-playbook.md` [:3000]
8. chat only: `open_tasks_block("dyson")`, graphify codebase graph, `caveman.block()`

Draft generator (`agency_dyson._claude_draft_fields`, `agency_dyson.py:269`): playbook only — no creed.

## 4. Outputs / writes

- `marcus_state/agency_agents.json` (history ≤60, tasks, learn counters), `marcus_state/agency_dyson.json` (drafts).
- Vault `Skills/dyson-playbook.md`, `Log/dyson-apply-<id>.md`.
- Approval queue `agency_approvals_io.add("dyson", …)`.
- Coaching broadcast of one insight after learn.

## 5. Autonomy & gates

| Alone | Needs a tap |
|---|---|
| Chat, plan drafts, playbook rewrite, bus + coaching notes | Ship: `agency_approvals_io.decide` → `agency_dyson.apply` → `agency_deploy.ship` (PR/commit) |

Key: `AGENCY_ANTHROPIC_API_KEY` → agency.env → wholesale key. No agent-specific kill switch.

## 6. Self-improvement

- `_maybe_learn` inside `chat()`/`send_task()`: `AGENCY_LEARN_EVERY` (12 interactions) **and** 45 min hardcoded gap (`agency_agents.py:42-43`).
- Nightly 20:00 ET `daily_learn.sh` → POST `/api/agency/agents/learn {"agentId":"dyson"}`.
- Writes vault `Skills/dyson-playbook.md`; adds `agent_coach.insights_block("dyson","agency")`. Cannot see the creed/methodology floors.

## 7. Chat & tasks

- `/api/hub/chat {agentId:"dyson"}` → `agency_agents.chat` (`agents_hub.py:435`); also `/api/agency/agents/chat`. Reply ≤700 tok.
- Tasks: `/api/hub/task` writes the hub store **and** the agency board; Dyson sees open ones via `open_tasks_block` in chat.

## 8. Cost

Claude: yes — chat, send_task (500), learn (+tip), `generate_draft` (4096). Bucket `operator` (HTTP) or `telegram` (Telegram chat).

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agency/agents | jq '.agents[]|select(.id=="dyson")|{online,openTasks,lastActive,learnCount}'
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="dyson")|{status,pendingApprovals}'
```
No heartbeat — the registry row has `heartbeat: "none"`.
