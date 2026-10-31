# Dyson — Build Agent

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-10-31 (line cites, Telegram chat path, ads lane, learn gating re-checked).

## 1. Identity

| | |
|---|---|
| Business | Agency (ClientForge) · hub id `dyson` · emoji 🛠️ |
| Job | Plans client website/code edits and drafts the file changes. Nothing ships until approved. Also owns the ads lane (Eco, `agents_hub.LANE_OF`): reads Meta numbers and proposes concepts, see [eco](eco.md). |
| Engine | `forge rei/agency_agents.py` (`_AGENTS`, `agency_agents.py:52`; chat/task/learn) + `forge rei/agency_dyson.py` (drafts, apply) |
| Seed folder | `forge-agency/skills/` |

## 2. Triggers

**Scheduled loop:** none. No thread, no heartbeat, no `FORGE_MARCUS` gate. (`cost_tracker.AGENT_THREADS` lists `dyson`; the only thread with that name is the Telegram partner turn, `telegram_io._partner_turn`.)

**Telegram**

| Form | Effect |
|---|---|
| `/dyson` · `dyson, …` / `dyson: …` / `dyson — …` | chat → `telegram_agent.chat` (tool-using business partner: `api_get` reads, writes become ✅/❌ cards). Fallback if that raises: `_tg_agency_chat` → `agency_agents.chat` (`connector.py:2574`, `telegram_io.py:1196`). Works in the Agency chat; other business chats refuse with a pointer |
| `/task <title>` while Dyson is active | `_tg_agency_task` → `agency_agents.send_task` — Agency board only, **not** the hub task store (`telegram_io.py:1118`) |
| Taps `dysonplan` / `dysongo` / `dysonno` | generate a plan / approve / reject (`connector.py:2436-2440`) |

**HTTP** (private network + Host + same-origin POST; no session)

| Method | Routes |
|---|---|
| GET | `/api/agency/agents` · `/agents/history?agent=` · `/agents/tasks?agent=` · `/api/agency/dyson/drafts` |
| POST | `/api/agency/agents/chat` · `/task` · `/task/update` · `/learn` · `/api/agency/dyson/generate` · `/dyson/decision` |

**Handoffs in:** hub `send_task` mirrors into `agency_agents.send_task` (`agents_hub.py:663`) · Edit Requests "Plan with Dyson" → `/api/agency/dyson/generate` (`agency_requests.jsx:104`).

**Bus:** sends as `dyson` (task queued, playbook updated, `dyson_plan` note → Telegram approve button, apply result). **Reads nothing** — hub `task` bus messages to `dyson` go unconsumed; tasks arrive via `open_tasks_block`.

**UI:** `window.AgencyDyson` (route key `Dyson`, `app.jsx:51`) — reached from the Agents hub Console tab or Edit Requests, not the sidebar · Agency Approvals · Agent Control Center `dyson` · Agent Office (Agency room) · mobile Agents.

## 3. Reads / context load order

Chat / send_task (`agency_agents.py:410`, `_skills_block` :297):
1. agent system prompt
2. LIVE CONTEXT (`_dyson_context`: open requests + draft count)
3. `north_star.context_block()`
4. creed `agent_creed.block("agency")` → `agency-evidence-discipline.md`
5. `agency-marketing-methodology.md` [:5000]
6. `agency-site-build-methodology.md` [:5000]
7. playbook: seed `dyson-playbook.md` + vault `Skills/dyson-playbook.md` [:3000]
8. chat only: `open_tasks_block("dyson")`
9. chat only: ADS LANE block, `_eco_context()` plus the Eco playbook [:3500] (Dyson owns the ads lane)
10. chat and `send_task`: graphify codebase graph (Dyson only)
11. chat only: `caveman.block()`

Draft generator (`agency_dyson._claude_draft_fields`, `agency_dyson.py:261`): request, workspace and repo-file context plus the playbook [:2500] — no creed.

## 4. Outputs / writes

- `marcus_state/agency_agents.json` (history ≤60, tasks, learn counters), `marcus_state/agency_dyson.json` (drafts).
- Vault `Skills/dyson-playbook.md`, `Log/dyson-apply-<id>.md`.
- Approval queue `agency_approvals_io.add("dyson", …)`.
- Coaching broadcast of one insight after learn.

## 5. Autonomy & gates

| Alone | Needs a tap |
|---|---|
| Chat, plan drafts, playbook rewrite, bus + coaching notes | Ship: `agency_approvals_io.decide` → `agency_dyson.apply` → `agency_deploy.ship` (PR/commit) |

Key: `AGENCY_ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY` in agency.env → wholesale key (`agency_agents._agency_key`; `agency_dyson` delegates to it). Shipping needs `GITHUB_TOKEN`; without it `apply` returns "queued, needs GITHUB_TOKEN". No agent-specific kill switch.

## 6. Self-improvement

- `_maybe_learn` inside `chat()`/`send_task()` runs only when `review_agent.self_improve_on()` is true (`FORGE_SELF_IMPROVE`, **default off**). Then: `AGENCY_LEARN_EVERY` (12 interactions) **and** 45 min hardcoded gap (`agency_agents.py:42-43`).
- Nightly 20:00 ET `daily_learn.sh` → POST `/api/agency/agents/learn {"agentId":"dyson"}`, but the script exits at once unless `FORGE_SELF_IMPROVE=1`. The manual Learn button always works.
- Writes vault `Skills/dyson-playbook.md`; adds `agent_coach.insights_block("dyson","agency")`. Cannot see the creed/methodology floors.

## 7. Chat & tasks

- `/api/hub/chat {agentId:"dyson"}` → `agency_agents.chat` (`agents_hub.py:604`); also `/api/agency/agents/chat`. Reply ≤700 tok.
- Tasks: `/api/hub/task` writes the hub store **and** the agency board; Dyson sees open ones via `open_tasks_block` in chat.
- **Live data (2026-10-18):** `agency_agents.chat` runs `dash_live.ask` — read-only `api_get`/`route_help` over `/api/agency/*` + `/api/coach/*` + brain/owner-actions, ≤4 tool turns. Daycare/wholesale routes refuse with 'that is Solomon's/Marcus's lane', so he points the owner there instead of guessing. The shared Pipeboard account is the daycare's: `agency_ads` labels it `accountOwner:'daycare'` and `_eco_context` reports "agency: no ad account connected yet" instead of its numbers. Workspace: Agency only (cross-workspace `/api/hub/chat {business}` refused). Knob `FORGE_CHAT_LIVE=0`.

## 8. Cost

Claude: yes — chat, send_task (500), learn (+tip), `generate_draft` (4096). Bucket `operator` (HTTP) or `dyson` (Telegram partner turns run on a thread named for the agent).

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agency/agents | jq '.agents[]|select(.id=="dyson")|{online,openTasks,lastActive,learnCount}'
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="dyson")|{status,pendingApprovals}'
```
No heartbeat — the registry row has `heartbeat: "none"`.

## 10. Keys, MCPs and task file

This card is the agent's canonical task file; runtime prompts still load skills from `forge-agency/skills/` — doc pointer only.

Full table with statuses: [ENV-MAP, Dyson and Eco](../ENV-MAP.md). Names only, values live in `~/.agent-keys/master.env`.

| Env var (name only) | master.env status |
|---|---|
| `AGENCY_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY` (agency.env) | `ANTHROPIC_API_KEY__AGENCY` OK; wholesale fallback `ANTHROPIC_API_KEY__WHOLESALE` OK |
| `GITHUB_TOKEN`, `GITHUB_DEPLOY_MAP` (`agency_deploy.py`, ship step) | `GITHUB_TOKEN` OK; map not listed |
| `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_MAP`, `META_PAGE_ID`, `META_DEFAULT_LINK` (ads lane) | no agency label; the two labelled Meta tokens are FAIL and belong to other accounts |
| `PIPEBOARD_API_TOKEN` (ads reads) | `__GLOBAL` and `__DAYCARE` OK; that Meta account is the daycare's |
| `AGENCY_LEARN_EVERY`, `FORGE_SELF_IMPROVE` | knobs |

Suggested MCPs (not read from code): GitHub, Vercel, brain, Claude_Browser; for the ads lane Meta Ads (Pipeboard / official). Any write needs the owner's yes.
