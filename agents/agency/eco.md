# Eco — Ads Agent

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-10-31 (line cites, Telegram chat path, learn gating re-checked).

## 1. Identity

| | |
|---|---|
| Business | Agency (ClientForge) · hub id `eco` · emoji 📈 |
| Job | Reads client Meta performance, proposes ad concepts (hook, headline, primary text, CTA, creative direction). Recommends only; builds PAUSED ads on approval. Runs as Dyson's ads lane (`agents_hub.LANE_OF`: eco → dyson), see [dyson](dyson.md). |
| Engine | `forge rei/agency_agents.py` (chat/task/learn) + `forge rei/agency_eco.py` (recommendations, ad build) |
| Seed folder | `forge-agency/skills/` |

## 2. Triggers

**Scheduled loop:** none. No thread, no heartbeat, no `FORGE_MARCUS` gate.

**Telegram**

| Form | Effect |
|---|---|
| `/eco` · `eco, …` / `eco: …` / `eco — …` | chat → `telegram_agent.chat` (tool-using business partner). Fallback if that raises: `_tg_agency_chat` → `agency_agents.chat` (`connector.py:2574`, `telegram_io.py:1196`) |
| `/task <title>` while Eco is active | `agency_agents.send_task` — Agency board only, not the hub store (`telegram_io.py:1118`) |

**HTTP** (private network + Host + same-origin POST; no session)

| Method | Routes |
|---|---|
| GET | `/api/agency/agents` · `/agents/history?agent=` · `/agents/tasks?agent=` · `/api/agency/eco?account=&client=` (template recs, no Claude) |
| POST | `/api/agency/agents/chat` · `/task` · `/task/update` · `/learn` · `/api/agency/eco/generate` · `/eco/decision` · `/eco/image` · `/eco/competitor` |

**Handoffs in:** hub `send_task` mirrors into the agency board (`agents_hub.py:663`).

**Bus:** sends as `eco` (task queued, playbook updated, ad created). Reads nothing.

**UI:** `window.AgencyEco` (route key `Eco`, `app.jsx:55`) — via Agents hub Console tab, not the sidebar · Agency Approvals · Agent Control Center `eco` (shows `dependencyHealth.meta`) · Agent Office (Agency room).

## 3. Reads / context load order

Chat / send_task (`agency_agents.py:410`, `_skills_block` :297):
1. agent system prompt
2. LIVE CONTEXT (`_eco_context`: top 3 accounts' 7-day totals)
3. `north_star.context_block()`
4. creed `agent_creed.block("agency")` → `agency-evidence-discipline.md`
5. `agency-marketing-methodology.md` [:5000]
6. `agency-four-triggers-ad-writer.md` [:5000]
7. playbook: seed `eco-playbook.md` + vault `Skills/eco-playbook.md` [:3000]
8. chat only: `open_tasks_block("eco")`, `caveman.block()`

Generate path (`agency_eco._claude_recommendations`, `agency_eco.py:164`): playbook [:2500] + extra context only — no creed. Competitor path (`agency_eco.py:238`) uses playbook [:1500]. `_eco_context` leaves out the daycare's Meta account (`agency_agents.py:152`). Ad payloads carry `dataSource` live|mock|token_rejected + `dateRange`.

The daycare reuses Eco's engine with daycare creds (`daycare_growth.py`) — that is Solomon's lane, not this agent.

## 4. Outputs / writes

- `marcus_state/agency_agents.json`, `marcus_state/agency_eco.json` (rec sets).
- Vault `Skills/eco-playbook.md`, `Reports/eco-ad-created-<ts>.md`.
- Approval queue `agency_approvals_io.add("eco", …)`.

## 5. Autonomy & gates

| Alone | Needs a tap |
|---|---|
| Chat, recommendations, playbook rewrite, bus + coaching notes | Approve → `approve_ad` (`agency_eco.py:569`) → `agency_ads.create_ad(spec, paused=True)` (`agency_eco.py:648`) — needs `META_ACCESS_TOKEN`, else "queued, needs META_ACCESS_TOKEN" |

Never launches, activates, or changes budget. No agent-specific kill switch.

## 6. Self-improvement

- `_maybe_learn` inside `chat()`/`send_task()` runs only when `review_agent.self_improve_on()` is true (`FORGE_SELF_IMPROVE`, **default off**). Then: `AGENCY_LEARN_EVERY` (12) **and** 45 min hardcoded gap.
- Nightly `daily_learn.sh` → POST `/api/agency/agents/learn {"agentId":"eco"}`, but the script exits at once unless `FORGE_SELF_IMPROVE=1`. The manual Learn button always works.
- Writes vault `Skills/eco-playbook.md`.

## 7. Chat & tasks

Same as Dyson: `/api/hub/chat {agentId:"eco"}` → `agency_agents.chat`; open tasks via `open_tasks_block`.

## 8. Cost

Claude: yes — chat, send_task, learn, generate (3200), competitor (2200). Bucket `operator` (HTTP) / `eco` (Telegram partner turns run on a thread named for the agent).

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agency/agents | jq '.agents[]|select(.id=="eco")|{online,openTasks,lastActive}'
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="eco")|{status,pendingApprovals,dependencyHealth}'
```

## 10. Keys, MCPs and task file

This card is the agent's canonical task file; runtime prompts still load skills from `forge-agency/skills/` — doc pointer only.

Full table with statuses: [ENV-MAP, Dyson and Eco](../ENV-MAP.md). Names only, values live in `~/.agent-keys/master.env`.

| Env var (name only) | master.env status |
|---|---|
| `AGENCY_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY` (agency.env) | `ANTHROPIC_API_KEY__AGENCY` OK; wholesale fallback `ANTHROPIC_API_KEY__WHOLESALE` OK |
| `META_ACCESS_TOKEN` (`approve_ad`, `agency_ads.py`) | no agency label; `META_ACCESS_TOKEN__AGENTIC_OS` and `__DAYCARE` are other accounts and both FAIL. Eco cannot build a PAUSED ad until an agency token exists |
| `META_AD_ACCOUNT_MAP`, `META_PAGE_ID`, `META_DEFAULT_LINK` | not listed for agency |
| `PIPEBOARD_API_TOKEN`, `PIPEBOARD_AD_ACCOUNT_ID` | `PIPEBOARD_API_TOKEN__GLOBAL` and `__DAYCARE` OK; the account behind them is the daycare's, so never report it as agency data |
| `HIGGSFIELD_API_KEY`, `HIGGSFIELD_API_SECRET` (concept images) | UNTESTED |
| `AGENCY_LEARN_EVERY`, `FORGE_SELF_IMPROVE` | knobs |

Suggested MCPs (not read from code): Meta Ads (Pipeboard / official), GetHookd, Canva, Higgsfield, Metricool. Any ad write is T2 plus the owner's yes.
