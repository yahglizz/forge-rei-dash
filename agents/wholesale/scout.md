# Scout — Lead Triage

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Wholesale (REI) · hub id `scout` · emoji 🔍 |
| Job | Sweeps GHL seller replies, scores motivation, buckets `asap`/`warm`/`nurture`/`dead`, tags + stages hot leads, hands call-worthy leads to Marcus, weekly missed-leads audit. Never texts. |
| Engine | `forge rei/scout_triage.py` → `ScoutEngine` (`scout_triage.py:343`), built `connector.py:1160` as `SCOUT` |
| Seed folder | `forge-scout/` |

## 2. Triggers

**Scheduled loop**

| Field | Value |
|---|---|
| Thread | `scout` (`connector.py:5076`) |
| Gate | `FORGE_MARCUS` != `0` (default on, `connector.py:45`). No separate on/off knob. |
| Interval | `FORGE_SCOUT_INTERVAL`, default 180 s (`scout_triage.py:74`) |
| Per tick | `poll_once()` then `_maybe_weekly_audit()` (`scout_triage.py:1854`) |
| Batch knobs | `FORGE_SCOUT_BATCH` 15 leads/sweep to Claude · `FORGE_SCOUT_PAGES` 4 pages (`scout_triage.py:75-76`) |
| Clock-out | `forge_ops.paused()` → `poll_once` stands down (`scout_triage.py:613`) — weekly audit does NOT check it |
| Heartbeat | `scout` (`scout_triage.py:1877`). Never retired. Dead-man: 3 stuck sweeps → bus `agent_down` alert (`scout_triage.py:1861`) |

**Weekly missed-leads audit** (`_maybe_weekly_audit`, `scout_triage.py:1462`): runs `retro_audit(7, auto=True)` when 7 d since last success and ≥ `FORGE_SCOUT_AUDIT_RETRY_MIN` (360) since last attempt. Knobs `FORGE_SCOUT_AUDIT_CANDIDATES` 30 · `FORGE_SCOUT_AUDIT_MSGS` 15 · `FORGE_SCOUT_AUDIT_PAGES` 8.

**Telegram**

| Form | Effect |
|---|---|
| `/scout` or `/scout <text>` | switch active agent to Scout (`telegram_io.py:670`); `/scout <ops command>` runs the ops command (`telegram_ops.py:797`) |
| `scout, …` · `scout: …` · `scout — …` · bare `scout` | name trigger (`telegram_io.py:679`) |
| `/task <title>` while Scout is active | `agents_hub.send_task("scout", …)` + answered in chat (`telegram_io.py:919`) |
| `/hot`, `/sweep` | ops commands reading/running Scout (`telegram_ops.py:837-840`) |
| Tap `handoff:` / `scoutdismiss:` | `_tg_handoff` → Marcus screen + draft / `SCOUT.dismiss` (`connector.py:2203-2204`) |

**HTTP** (all behind private-network + Host allowlist; POST also same-origin — `connector.py:3240`, `4859`; no session)

| Method | Routes |
|---|---|
| GET | `/api/scout/summary` · `/leads?bucket=` · `/pipeline` · `/overview` · `/audit` (`connector.py:2769-2773`) |
| POST | `/api/scout/run` · `/apply` · `/dismiss` · `/remove` · `/pipeline` · `/learn` · `/backfill` · `/handoff` · `/audit/run` (`connector.py:3689-3741`) |

**Handoffs in:** Screener `set_stage` → Scout `apply_tags`/`add_to_pipeline`/`dismiss` (`marcus_screening.py:624`) · deal moves → `SCOUT.advance_opp` (`connector.py:1716`) · `legit_check.audit_tagged` demotes buckets (`connector.py:1340`).

**Bus:** sends `scout→all` alerts `hot_lead`, `missed_sweep`, `agent_down`, status `offer_made` + learn. **Reads nothing** — no `agent_bus.inbox` call.

**UI:** Command page → `ScoutConsole` (`marcus.jsx`), Conversations "💎 Missed" tab (`pages.jsx` `ScoutMissed`), Dashboard, mobile Home · Agent Control Center row `scout` · Agent Office (REI room).

## 3. Reads / context load order

Scoring prompt (`_claude_batch`, `scout_triage.py:478`):
1. inline rubric
2. `north_star.context_block()`
3. creed `agent_creed.block("wholesale")` → `wholesale-evidence-discipline.md`
4. `wholesale-context.md` (`agent_context.py:93`)
5. `_load_skills()[:3500]` = seed `scout-playbook.md` + vault `Skills/scout-playbook.md` + vault `Skills/closing-plays.md` (`scout_triage.py:407`)

Retro audit prompt: playbook `[:2500]` + operator query only — no creed.

## 4. Outputs / writes

- State `marcus_state/scout.json` (records ≤300, audits ≤5, offers ≤500).
- Vault `Skills/scout-playbook.md`, `Reports/missed-leads-<date>.md`.
- GHL: contact tags (add/remove), opportunities in pipeline matching `FORGE_SCOUT_PIPELINE` ("wholesal"); stages asap→Hot, warm→Warm, nurture→Responded; `FORGE_OFFER_TAG` (`offer-made`); `FORGE_STAGE_OFFER`/`_CONTRACT`/`_CLOSED`.
- `action_log` rows (agent `scout`).

## 5. Autonomy & gates

| Alone | Needs a tap |
|---|---|
| Score + bucket every reply | Warm/nurture tags (`/api/scout/apply`) |
| HOT auto-tag `triage: asap` + `motivated: high` — `FORGE_SCOUT_AUTOTAG_HOT`=1 (`scout_triage.py:99`, `_autotag_hot` :1478) | Any other pipeline move |
| HOT auto-stage to Hot — `FORGE_SCOUT_AUTOPIPE_HOT`=1 (`:100`, :1498) | — |
| Offer auto-tag · test-mode phones auto tag/pipe | — |
| Auto-handoff asap/warm to Marcus (`on_scored`) | — |

Never: sends SMS. Filters skip our own outreach, DNC, opt-outs, denials; `reconcile_buckets` demotes false positives each poll.

## 6. Self-improvement

- `_maybe_learn` after each poll: `FORGE_SCOUT_LEARN_EVERY` (25 scored) **and** `FORGE_SCOUT_LEARN_GAP_MIN` (45 min) (`scout_triage.py:78-79`).
- Nightly 20:00 ET `deploy/daily_learn.sh` → POST `/api/scout/learn` (bypasses the rate limit).
- Writes vault `Skills/scout-playbook.md`; adds `agent_coach.insights_block("scout","wholesale")`.

## 7. Chat & tasks

- `/api/hub/chat {agentId:"scout"}` → `agents_hub._chat` → `agents_chat.chat` (`agents_hub.py:453`); also `/api/agents/chat`.
- Dashboard chat first tries write commands (`telegram_ops.handle_agent_command`: tags run, stage moves queue a confirm); Telegram chat has commands off.
- Prompt: live triage + playbook `[:1500]` + `agent_collab.protocol` + `open_tasks_block("scout")` + `caveman.block()` (`agents_chat.py:176`). No creed in chat.
- "audit last week"-style asks run `retro_audit` first.
- Tasks: visible only via `open_tasks_block` in chat — Scout's loop never reads tasks or the bus.

## 8. Cost

Claude: yes — scoring (Haiku, 1500 tok), audit, learn (Sonnet). Bucket `scout` on the loop; `operator` from HTTP/learn curls; `telegram` for Telegram chat.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="scout")|{status,lastRun,lastError,pendingApprovals}'
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="scout")'
curl -s localhost:7799/api/scout/summary | jq '{lastRun,lastError,aiScoring,total}'
```
