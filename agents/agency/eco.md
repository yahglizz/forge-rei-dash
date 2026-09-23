# Eco — Ads Agent

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Agency (ClientForge) · hub id `eco` · emoji 📈 |
| Job | Reads client Meta performance, proposes ad concepts (hook, headline, primary text, CTA, creative direction). Recommends only; builds PAUSED ads on approval. |
| Engine | `forge rei/agency_agents.py` (chat/task/learn) + `forge rei/agency_eco.py` (recommendations, ad build) |
| Seed folder | `forge-agency/skills/` |

## 2. Triggers

**Scheduled loop:** none. No thread, no heartbeat, no `FORGE_MARCUS` gate.

**Telegram**

| Form | Effect |
|---|---|
| `/eco` · `eco, …` / `eco: …` / `eco — …` | chat → `_tg_agency_chat` → `agency_agents.chat` |
| `/task <title>` while Eco is active | `agency_agents.send_task` — Agency board only, not the hub store |

**HTTP** (private network + Host + same-origin POST; no session)

| Method | Routes |
|---|---|
| GET | `/api/agency/agents` · `/agents/history?agent=` · `/agents/tasks?agent=` · `/api/agency/eco?account=&client=` (template recs, no Claude) |
| POST | `/api/agency/agents/chat` · `/task` · `/task/update` · `/learn` · `/api/agency/eco/generate` · `/eco/decision` · `/eco/image` · `/eco/competitor` |

**Handoffs in:** hub `send_task` mirrors into the agency board (`agents_hub.py:490`).

**Bus:** sends as `eco` (task queued, playbook updated, ad created). Reads nothing.

**UI:** `window.AgencyEco` (route key `Eco`, `app.jsx:51`) — via Agents hub Console tab, not the sidebar · Agency Approvals · Agent Control Center `eco` (shows `dependencyHealth.meta`) · Agent Office (Agency room).

## 3. Reads / context load order

Chat / send_task (`agency_agents.py:412`):
1. agent system prompt
2. LIVE CONTEXT (`_eco_context`: top 3 accounts' 7-day totals)
3. `north_star.context_block()`
4. creed `agent_creed.block("agency")` → `agency-evidence-discipline.md`
5. `agency-marketing-methodology.md` [:5000]
6. `agency-four-triggers-ad-writer.md` [:5000]
7. playbook: seed `eco-playbook.md` + vault `Skills/eco-playbook.md` [:3000]
8. chat only: `open_tasks_block("eco")`, `caveman.block()`

Generate path (`agency_eco._claude_recommendations`, `agency_eco.py:176`): playbook + extra context only — no creed. Ad payloads carry `dataSource` live|mock|token_rejected + `dateRange`.

The daycare reuses Eco's engine with daycare creds (`daycare_growth.py`) — that is Solomon's lane, not this agent.

## 4. Outputs / writes

- `marcus_state/agency_agents.json`, `marcus_state/agency_eco.json` (rec sets).
- Vault `Skills/eco-playbook.md`, `Reports/eco-ad-created-<ts>.md`.
- Approval queue `agency_approvals_io.add("eco", …)`.

## 5. Autonomy & gates

| Alone | Needs a tap |
|---|---|
| Chat, recommendations, playbook rewrite, bus + coaching notes | Approve → `approve_ad` → `agency_ads.create_ad(spec, paused=True)` (`agency_eco.py:560`) — needs `META_ACCESS_TOKEN` |

Never launches, activates, or changes budget. No agent-specific kill switch.

## 6. Self-improvement

- `_maybe_learn` inside `chat()`/`send_task()`: `AGENCY_LEARN_EVERY` (12) **and** 45 min hardcoded gap.
- Nightly `daily_learn.sh` → POST `/api/agency/agents/learn {"agentId":"eco"}`.
- Writes vault `Skills/eco-playbook.md`.

## 7. Chat & tasks

Same as Dyson: `/api/hub/chat {agentId:"eco"}` → `agency_agents.chat`; open tasks via `open_tasks_block`.

## 8. Cost

Claude: yes — chat, send_task, learn, generate (3200), competitor (2200). Bucket `operator` / `telegram`.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agency/agents | jq '.agents[]|select(.id=="eco")|{online,openTasks,lastActive}'
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="eco")|{status,pendingApprovals,dependencyHealth}'
```
