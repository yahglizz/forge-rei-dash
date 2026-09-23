# Solomon — Executive Director (the daycare's one agent)

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Daycare (A Touch of Blessings) · hub id `solomon` · emoji 🏛️ |
| Job | Reads the whole center and writes ONE ranked operating brief: Attention Now, Enrollment, Money, People, Roster, Follow-ups, Campaign health, Competitor read, Creative, Delegations. Owns enrollment. Absorbed Nora + Nova (2026-07-25). |
| Engine | `forge rei/daycare_director.py` → `SolomonEngine` (`daycare_director.py:172`), connector global `SOLOMON` |
| Seed folder | `forge-solomon/` (skills in `forge-solomon/skills/`) |

## 2. Triggers

**Scheduled loop**

| Field | Value |
|---|---|
| Thread | `solomon` (`connector.py:5101`) |
| Gate | `FORGE_MARCUS` != `0`; no other on/off knob, never retired |
| Tick | 900 s, hardcoded (`daycare_director.py:60`) |
| Brief cadence | `FORGE_SOLOMON_BRIEF_EVERY_H`, default 24 (`:53`) |
| Failure backoff | 15 min doubling to 6 h (`:859`) |
| Clock-out | tick skipped on `forge_ops.paused()` (`:896`) |
| Session | builds under `daycare_supabase.BRIDGE.autoadmin_session("127.0.0.1")` |
| Heartbeat | `solomon` every tick (`:921`) |

**Telegram**

| Form | Effect |
|---|---|
| `/solomon` · `solomon, …` / `solomon: …` / `solomon — …` | chat → `_tg_agent_chat` → `agents_hub.chat` (`connector.py:2333`) |
| `/task <title>` while active | `agents_hub.send_task("solomon", …)` → he also reads it off the bus at the next brief |

**HTTP** — daycare router, every route needs the secure check + a daycare session (cookie or loopback/Serve auto-admin; `connector.py:4497`)

| Method | Routes |
|---|---|
| GET | `/api/daycare/director/{status,overview,brief,bus}` · `/api/daycare/family/{status,overview,brief,bus}` (→ `roster_view()`) · `/api/daycare/adops/{status,overview,brief,bus}` (→ `adops_view()`) · `/api/daycare/eco/ideas` (Claude call on GET) |
| POST | `/api/daycare/director/run` · `/director/learn` · `/family/run` · `/family/learn` · `/adops/run` · `/adops/learn` |

**Bus roles he answers to** — `BUS_ROLES` (`daycare_director.py:49`): `solomon`, `family-comms`, `enrollment`, `ads`, `growth`, `nora`, `nova`. `_read_bus_inbox` (`:357`) pulls unread (≤10 per role, plus `all`), marks them read, feeds the newest 10 into the brief as `busDelegations`.

**Handoffs in:** bus messages to any role above · hub tasks · Daycare Lead Desk feeds `leadDesk` into the brief.

**UI:** `window.DaycareDirector` (route key `Director`, `app.jsx:65`; page title "Solomon") — via the Agents hub Console tab, not the Daycare sidebar · Agent Control Center `solomon` · Agent Office (Daycare room).

## 3. Reads / context load order

`build_brief` (`daycare_director.py:536`):
1. inline role + evidence rule (backstop)
2. `north_star`
3. `daycare-context.md` [:3500] + `enrollment-ad-agent.md` [:4000] (`daycare_context.py`)
4. creed `agent_creed.block("daycare")` → `daycare-evidence-discipline.md`
5. TOP SKILLS (`TOP_SKILLS`, `:228`): `solomon-decision-loop.md`, `solomon-director-craft.md`, `solomon-systems-craft.md`, `solomon-roster-craft.md`, `solomon-adops-craft.md` (+ any other `solomon-*` non-playbook), seed then vault, never truncated
6. PLAYBOOK (`_playbook_only`): seed `solomon-playbook.md` + vault `Skills/solomon-playbook.md` [:4000]
7. last 2 vault `Reports/daycare/*.md` [:1200 each]
8. user JSON: metrics, alerts, roster, blasts, opt-outs, campaign, competitor, busDelegations, connectedSystems (presence only), leadDesk

## 4. Outputs / writes

- `marcus_state/solomon.json`.
- Vault `Reports/daycare/brief-YYYY-MM-DD.md` per brief, `Skills/solomon-playbook.md` on learn.
- Bus: `solomon→all` status per brief · one `handoff` per delegation to `role.lower()` (≤8) · learn status.

## 5. Autonomy & gates

- Read-only, propose + delegate. Never texts a family, invoices, launches ads, or writes the DB.
- Only autonomous writes: brief notes, playbook, bus notes.
- Kill: `FORGE_MARCUS=0`, clock out, or no key. Key: `SOLOMON_ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY` → agency → wholesale.
- Knob `FORGE_SOLOMON_BRIEF_TOKENS` 5000.

## 6. Self-improvement

- `_maybe_learn` every tick: `FORGE_SOLOMON_LEARN_EVERY` (8 briefs) **and** `FORGE_SOLOMON_LEARN_GAP_MIN` (45 min) → about every 8 days at the 24 h cadence.
- Manual: POST `/api/daycare/director/learn` (also `/family/learn`, `/adops/learn`). Not in `daily_learn.sh`.
- Sees only the playbook (`_playbook_only`) — creed and top skills are untouchable.

## 7. Chat & tasks

- `/api/hub/chat {agentId:"solomon"}` → `agents_hub._director_chat` (`agents_hub.py:289`).
- Prompt: role + blurb → creed → `daycare_context.context_block()` → latest brief [:3500] → top skills (**empty** — `daycare_director` has no `top_skills_text`) → `playbook_text(4000)` → `open_tasks_block("solomon")` → `caveman.block()`. ≤700 tok.
- Tasks reach him twice: `open_tasks_block` in chat + the bus `task` message read at brief time.

## 8. Cost

Claude: yes — 2 calls per brief (competitor read + brief) + learn. Bucket `solomon` on the loop; `operator` for manual runs/chat/`eco/ideas`; `telegram` for Telegram chat.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="solomon")|{status,lastSuccessAt,nextRun,lastError}'
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="solomon")'
# needs a daycare session (auto-admin via loopback/Serve):
curl -s localhost:7799/api/daycare/director/status | jq '{aiReady,creedLoaded,topSkills,briefCount,lastBriefAt,nextBriefAt,failStreak}'
```
