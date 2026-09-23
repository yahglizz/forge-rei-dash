# Midas — E-com Director (dropship)

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-09-22.
> **Dropship is ARCHIVED by default** (`business_scope.py:37`). Archiving hides Midas in the UI and from Orion, but does **not** stop his routes, Telegram, or loop — see §5.

## 1. Identity

| | |
|---|---|
| Business | Dropship (FORGE store) · hub id `midas` · emoji 🛒 |
| Job | Runs the store: one ranked brief (headline, priorities, winners, money, ops, ads, delegations) + three on-demand lanes — product research, creative & ads, fulfillment & support. |
| Engine | `forge rei/dropship_director.py` → `MidasEngine` (`dropship_director.py:269`), built `connector.py:1063` as `MIDAS` |
| Seed folder | `forge-dropship/` (skills in `forge-dropship/skills/`) |

## 2. Triggers

**Scheduled loop**

| Field | Value |
|---|---|
| Thread | `midas` (`connector.py:5129`) |
| Gate | `FORGE_MARCUS` != `0` **and** `FORGE_DROPSHIP_BRIEF` != `0` — **default `0` (off)** |
| Off | `forge_heartbeat.retire("midas")` (`connector.py:5134`) |
| Tick | 900 s, hardcoded (`dropship_director.py:46`) |
| Brief cadence | `FORGE_DROPSHIP_BRIEF_EVERY_H` 24 · `FORGE_DROPSHIP_BRIEF_TOKENS` 5000 |
| Clock-out | loop tick skipped on `forge_ops.paused()`; HTTP runs ignore it |
| Heartbeat | `midas` |

**Telegram**

| Form | Effect |
|---|---|
| `/midas` · `midas, …` / `midas: …` / `midas — …` | chat → `_tg_agent_chat` → `agents_hub.chat` (`connector.py:2333`) |
| `/task <title>` while active | `agents_hub.send_task("midas", …)` → read off the bus at next brief |

**HTTP** — private network + Host + same-origin POST; no session (`_handle_dropship_get` `connector.py:4515`)

| Method | Route | Calls |
|---|---|---|
| GET | `/api/dropship/director/{status,overview,brief,bus}` · `/api/dropship/agents` · `/api/dropship/ads` (no Claude) · `/api/dropship/{hawk,blaze,otto}/overview` | lane views |
| POST | `/api/dropship/director/run` · `/director/learn` | `run_once` · `learn` |
| POST | `/api/dropship/hawk/run` · `/hawk/watch` · `/research/discover` · `/research/packet` | product research lane |
| POST | `/api/dropship/blaze/run` | `analyze_ads` (creative & ads lane) |
| POST | `/api/dropship/otto/run` | `fulfillment_check` |
| POST | `/api/dropship/{hawk,blaze,otto}/learn` | all alias `learn()` |

(`hawk`/`blaze`/`otto` are retired-agent route names kept as lane aliases.)

**Bus:** `_read_bus_inbox` (`:469`) reads `inbox("midas")` (+ `all`), ≤10, marks read — only inside `build_brief`. No role aliases.

**UI:** Dropship workspace — Agents tab (`dropship_growth.jsx`), Dashboard "Midas brief" card, Watch (`dropship_watch.jsx`), Orders (`dropship_orders.jsx`) · Agent Control Center `midas` (DISABLED while archived or loop off) · Agent Office (Dropship room, hidden while archived).

## 3. Reads / context load order

`build_brief` (`:486`): inline rules → `north_star` → `dropship-context.md` → creed `agent_creed.block("dropship")` → `dropship-evidence-discipline.md` → skills `_load_skills(lane)` → playbook `_playbook_only()` [:4000] (seed `midas-playbook.md` + vault `Skills/midas-playbook.md`) → last 2 vault `Reports/dropship/*.md`. Payload: Shopify snapshot, AutoDS health, connectedSystems, offlineChannels, `assignedToYou` (bus).

| Set | Skills |
|---|---|
| `TOP_SKILLS` (always) | `midas-decision-loop.md`, `midas-craft.md`, `dropship-account-health.md` |
| lane `product research` | + `dropship-adspy-method.md` |
| lane `creative & ads` | + `dropship-four-triggers-ad-writer.md`, `dropship-creative-testing-doctrine.md`, `dropship-account-optimization-doctrine.md`, `dropship-meta-ads-diagnostician.md`, `dropship-ad-launch-sop.md`, `dropship-adspy-method.md` |
| lane `fulfillment & support` | + `dropship-support-macros.md` |
| `ON_DEMAND_SKILLS` (chat only) | `dropship-store-setup.md` |

Brief uses `lane=""` (core only). Enforced by `forge rei/test_dropship_skills.py`.

## 4. Outputs / writes

- `marcus_state/midas.json`.
- Vault `Reports/dropship/brief-<date>.md`, `Skills/midas-playbook.md`.
- Bus: `midas→all` status per brief + one `handoff` per delegation (≤8, can reach Telegram); `note` after a lane run; learn status.

## 5. Autonomy & gates

- Read + propose only: never launches, changes budget, orders from a supplier, edits a listing, messages a customer, or refunds.
- `research_packet` stops before Claude on a kill flag or unknown price/cost; `meta_overview` refuses agency mock data.
- Kill: `FORGE_DROPSHIP_BRIEF=0` (default) stops the loop. **Archive does not gate** routes, Telegram, or the loop.
- Key: `DROPSHIP_ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY` → agency → wholesale.

## 6. Self-improvement

- `_maybe_learn`: `FORGE_DROPSHIP_LEARN_EVERY` (8 briefs) + `FORGE_DROPSHIP_LEARN_GAP_MIN` (45 min) — called only from `run_forever`, so **never fires while the loop is off**.
- Manual: POST `/api/dropship/director/learn` (needs at least one brief). Not in `daily_learn.sh`.

## 7. Chat & tasks

- `/api/hub/chat {agentId:"midas"}` → `_director_chat`: creed → `dropship_context` → latest brief [:3500] → `top_skills_text()` (ALL skills incl. lane + on-demand — deliberately ungated) → `playbook_text(4000)` → `open_tasks_block("midas")` → `caveman.block()`.
- Agent Office tasks run the same chat path.

## 8. Cost

Claude: yes — brief, learn, every lane `analyze()`, chat. Bucket `midas` on the loop; `operator` for HTTP; `telegram` for Telegram chat.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="midas")|{status,archived,lastSuccessAt,lastError}'
curl -s localhost:7799/api/dropship/director/status | jq '{aiReady,topSkills,briefCount,lastBriefAt,lastError}'
curl -s localhost:7799/api/businesses | jq .
```
Heartbeat `midas` reads retired while `FORGE_DROPSHIP_BRIEF=0`.
