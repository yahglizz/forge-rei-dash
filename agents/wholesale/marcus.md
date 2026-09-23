# Marcus — Lead Agent (screener + text-back drafter)

> Code refs are relative to `forge rei/` unless they start with `forge-`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Wholesale (REI) · hub id `marcus` · emoji 🎯 |
| Job | Screens interested / not-ready sellers into a call-ready report, drafts every seller text-back as a proposal, never quotes a price by text. |
| Engines | **Screener** `forge rei/marcus_screening.py` → `Screener` (`marcus_screening.py:150`), `SCREENER` at `connector.py:1165` · **Drafter** `forge rei/marcus_engine.py` → `MarcusEngine` (`marcus_engine.py:537`), `MARCUS` at `connector.py:877` · **Chat** `forge rei/marcus_chat.py` |
| Seed folder | `forge-marcus/` (skills in `forge-marcus/skills/`) |

## 2. Triggers

**Scheduled loop** — none for the screener (event-driven, `connector.py:565`).

| Loop | Thread | Gate | Interval | Heartbeat |
|---|---|---|---|---|
| Legacy SMS responder | `marcus` (`connector.py:5085`) | `FORGE_MARCUS` + `FORGE_MARCUS_SMS` != `0` — **default `0` (off)** | 60 s, hardcoded (`marcus_engine.py:549`) | `marcus_sms` (`marcus_engine.py:1312`) — not retired when off |

**Handoffs in (the real triggers)**

| From | Path |
|---|---|
| Scout sweep | `SCOUT.on_scored = _auto_screen` (`connector.py:1254`): up to 10 asap/warm per sweep → unnamed thread → `SCREENER.auto_screen` → `_ace_update_from_screening` + bus `scout→marcus` handoff. Gate `FORGE_SCREEN_AUTO`=1 (`marcus_screening.py:73`) |
| Scout "Hand to Marcus" | POST `/api/scout/handoff` · Telegram tap `handoff:` → `_tg_handoff` (`connector.py:2138`): screen + `make_proposal_for` |
| Follow-up | `followup.py:152` → `MARCUS.make_proposal_for(hint=…)` (re-engage bumps) |
| ACE | `ace.py` → `make_proposal_for` (questions/pivots) and `marcus.approve` (auto-send in supervised/full) |
| Autopilot | `autopilot.py:180` → `marcus.approve` |

**Telegram**

| Form | Effect |
|---|---|
| `/marcus` (default active agent) · `marcus, …` / `marcus: …` / `marcus — …` | chat (`telegram_io.py:670`, `:679`) |
| `/task <title>` while active | `agents_hub.send_task("marcus", …)` |
| `/screen name` · `/text name: msg` · `/checkback name` · `/proposals` · `/directives` | ops commands (`telegram_ops.py:742`) — every send returns a ✅/❌ confirm |
| Tap `approve:` / `mdismiss:` | send / drop a pending proposal (`telegram_io.py:401`) |

**HTTP** (private network + Host + same-origin POST; no session)

| Method | Routes |
|---|---|
| GET | `/api/screening/queue` · `/report?contactId=` · `/status` · `/api/marcus/status` · `/proposals` · `/directives` |
| POST | `/api/screening/run` · `/note` · `/stage` · `/send` · `/audit-not-ready` · `/learn` · `/api/marcus/approve` · `/dismiss` · `/toggle` (refuses autoSend) · `/poll` · `/chat` · `/directives/run` · `/api/reply/draft` · `/api/reply/send` |

**Bus:** sends `marcus→all` alert `proposal` (not NRN/DNC; Telegram pings warm+ only), `checkback_due`, learn status; `marcus_lead` sends `directive` to `scout`/`all`. **Reads nothing.**

**UI:** Screening page (`screening.jsx`, embeds Atlas call card) · Command page `MarcusConsole` (`marcus.jsx`) · Dashboard · mobile Home + Actions · Agent Control Center `marcus` · Agent Office (REI room).

## 3. Reads / context load order

**Screening** (`screen()`, `marcus_screening.py:335`): inline JSON contract → `north_star` → creed `agent_creed.block("wholesale")` → `wholesale-context.md` → `_load_skills()[:9000]` (`marcus-lead-agent.md`, `marcus-screening-playbook.md`, `marcus-critical-thinking.md`, `marcus-seller-psychology.md`, `marcus-nurture-followup.md`, `wholesale-seller-texter.md` — seed + vault each) → voice `[:2500]` (vault `Skills/yahjair-voice.md` + `Skills/marcus-playbook.md`) → `agent_context.brain_context` → thread (`FORGE_SCREEN_MSGS` 20).

**Draft** (`_ai_draft`, `marcus_engine.py:826`): inline voice + hard rules → `north_star` → creed → `seller-reply-playbook.md` (full) → `_load_playbook()[:1500]` (`marcus-playbook.md`, `yahjair-voice.md`, `wholesale-seller-texter.md`, `closing-plays.md`; vault copy overrides seed) → `brain_context` → RE-ENGAGE block (hint) → PIVOT block (last).

## 4. Outputs / writes

- `marcus_state/screenings.json`, `proposals.jsonl`, `handled.jsonl`, `seen_contacts.jsonl` (drives 🆕 NEW LEAD ping), `config.json`.
- Vault `Reports/screening-<name>.md`, `Skills/marcus-screening-playbook.md`.
- GHL: `POST /conversations/messages` only on an approved send / `send_nurture`; DNC tag on suppress; stage writes go through Scout.
- `action_log` `approve_send`.

## 5. Autonomy & gates

| Alone | Needs a tap |
|---|---|
| Screen + write the report | Every seller SMS (`/api/marcus/approve`, Telegram ✅) |
| Draft proposals | `send_nurture` (operator-only, `autonomous=False`, fails closed without `sms_guard`) |

Hard never-rules (code-enforced):
- `_no_price_over_text` (`marcus_engine.py:781`) swaps any figure for a call-pivot.
- `_is_our_message` + `_OUR_OUTREACH_PHRASES` (`marcus_engine.py:378-439`) — never reply to our own outreach.
- `_draft_safety_reason` (meta text, placeholders, persona name, price confirm).
- `toggle()` refuses auto-send; `_load_config` forces it off. Only test-mode phones auto-send in `poll_once`.
- Quiet hours `FORGE_QUIET_START` 8 / `FORGE_QUIET_END` 21. Legacy loop kill: `FORGE_MARCUS_SMS=0` (default).
- Outward sends from ACE/Autopilot pass `sms_guard` (window, dedupe, DNC, price regex, legit check, daily cap).

## 6. Self-improvement

| Loop | Trigger | Writes |
|---|---|---|
| Screener `learn()` | after each screen: `FORGE_MARCUS_LEARN_EVERY` 15 + `FORGE_MARCUS_LEARN_GAP_MIN` 45 min; nightly `/api/screening/learn` | vault `Skills/marcus-screening-playbook.md` |
| Voice (`style_agent`) | nightly `/api/style/run` — see [style-agent](../cross-business/style-agent.md) | `Skills/yahjair-voice.md`, `Skills/closing-plays.md` |
| Playbook (`review_agent`) | Mon 08:00 + nightly `days=1` — see [review-agent](../cross-business/review-agent.md) | `Skills/marcus-playbook.md` |

## 7. Chat & tasks

- `/api/hub/chat {agentId:"marcus"}` → `agents_chat.chat` → `marcus_chat.chat` (`agents_chat.py:170`); also `/api/marcus/chat`, `/api/agents/chat`.
- Searches 4 pages of GHL threads, ranks by keyword. Prompt: LEAD AGENT text + `agent_collab.protocol("scout")` + `_hub_tasks("marcus")` (= `open_tasks_block`, which also lists Follow-up/ACE/Autopilot tasks) + `caveman.block()`. No creed in chat.
- Marcus also answers chat for Follow-up, ACE, Autopilot (`chatVia`, `agents_hub.py:421`) with commands disabled.

## 8. Cost

Claude: yes. Screening (Sonnet, 1400 tok) runs on the unnamed auto-screen thread → bucket **`operator`**. Drafts (Haiku, 300 tok) bill to the caller's thread (`followup`, `telegram`, `operator`). `marcus` bucket only on the legacy SMS loop.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="marcus")|{status,lastRun,pendingApprovals,lastError}'
curl -s localhost:7799/api/screening/status | jq '{aiScreening,autoScreen,total,lastError}'
curl -s localhost:7799/api/marcus/status | jq '{pending,hasAI,lastError,promptHealth}'
```
