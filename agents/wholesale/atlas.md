# Atlas — Deal Underwriter

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Wholesale (REI) · hub id `atlas` · emoji 📐 |
| Job | Underwrites every screened-interested seller: facts from the thread, offer anchors (open/target/walkaway) from the seller's own ask, MAO math, negotiation call card. Numbers are INTERNAL. Contacts no one. |
| Engine | `forge rei/deal_prep.py` → `DealPrep` (`deal_prep.py:170`), built `connector.py:1309` as `DEAL_PREP` |
| Seed skill | `atlas-underwriter.md` (in `forge-marcus/skills/`) |

## 2. Triggers

**Scheduled loop**

| Field | Value |
|---|---|
| Thread | `atlas` (`connector.py:5095`) |
| Gate | `FORGE_MARCUS` != `0` |
| Interval | 900 s, **hardcoded — no env knob** (`deal_prep.py:595`) |
| On/off | `FORGE_PREP_AUTO`=1 (`deal_prep.py:72`); heartbeat keeps beating when off |
| Per sweep | ≤ `FORGE_PREP_SWEEP_CAP` (5) preps for screenings with interest `interested` and score ≥ 6 (`deal_prep.py:431`) |
| Clock-out | `auto_prep_interested` returns early on `forge_ops.paused()` (`deal_prep.py:437`) |
| Heartbeat | `atlas` (`deal_prep.py:603`) |

**Telegram**

| Form | Effect |
|---|---|
| `/atlas` · `atlas, …` / `atlas: …` / `atlas — …` | chat |
| `/task <title>` while active | `agents_hub.send_task("atlas", …)` |
| `/prep name` | Atlas deal card (`telegram_ops.py:856`) |

**HTTP** (private network + Host + same-origin POST; no session). There are no `/api/atlas/*` routes.

| Method | Routes |
|---|---|
| GET | `/api/prep/list` · `/api/prep/get?contactId=` · `/api/prep/status` (`connector.py:2781-2783`) |
| POST | `/api/prep/run` (with `contactId` → one prep; without → `auto_prep_interested`) · `/api/prep/learn` |

**Handoffs in:** Screener output (loop keys on `screenedAt`) · ACE `apply(..., deal_prep=DEAL_PREP)` / `call_ready_upsert` (`connector.py:1223`) · Agent Office task.

**Bus:** sends `atlas→marcus` handoff `deal_prep` (Telegram shows "Handed to Marcus") + learn status. **Reads nothing.**

**UI:** `AtlasCallCard` (`atlas_card.jsx`) on interested Screening cards and the Conversations thread · Agent Control Center `atlas` · Agent Office (REI room).

## 3. Reads / context load order

`prep()` (`deal_prep.py:270`): inline JSON contract + anchor rules → `north_star` → creed `agent_creed.block("wholesale")` → `_load_skills()[:7000]` (seed `atlas-underwriter.md` + vault `Skills/atlas-underwriter.md`) → `agent_context.brain_context` → screening JSON + thread (`FORGE_PREP_MSGS` 40).

## 4. Outputs / writes

- `marcus_state/deal_prep.json` (preps ≤100).
- Vault `Skills/atlas-underwriter.md` (its learned playbook).
- No GHL writes.

## 5. Autonomy & gates

- Fully autonomous, internal only.
- Code guard: no seller ask → all anchors null (`deal_prep.py:375`). Never invents a number.
- Anchors are labeled INTERNAL in the UI and never sent to a seller (Marcus's `_no_price_over_text` backs this up).

## 6. Self-improvement

- `_maybe_learn` after each sweep: `FORGE_ATLAS_LEARN_EVERY` (12) **and** `FORGE_ATLAS_LEARN_GAP_MIN` (45 min) (`deal_prep.py:80-81`).
- Manual: POST `/api/prep/learn`. **Not** in the nightly `daily_learn.sh`.
- Writes vault `Skills/atlas-underwriter.md`; adds `agent_coach.insights_block("atlas","wholesale")`.

## 7. Chat & tasks

- `/api/hub/chat {agentId:"atlas"}` → `agents_chat.chat("atlas")` (`agents_chat.py:262`).
- Prompt: prep block + `agent_collab.protocol("marcus")` + `open_tasks_block("atlas")` + `caveman.block()`. No creed.
- Known bug: the prep block always reads "(prep data unavailable)" — see README inconsistencies.
- Tasks reach it only through chat (`open_tasks_block`); the loop never reads tasks or the bus.

## 8. Cost

Claude: yes (Sonnet, 900 tok, ≤2 calls with the JSON retry). Bucket `atlas` on the loop, `operator` from `/api/prep/run`.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="atlas")|{status,lastRun,nextRun,lastError}'
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="atlas")'
curl -s localhost:7799/api/prep/status | jq '{aiPrep,autoPrep,total,lastError}'
```
