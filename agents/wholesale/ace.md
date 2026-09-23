# ACE — Conversation Engine (no brain of its own)

> Code refs are relative to `forge rei/`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Wholesale (REI) · hub id `ace` · emoji ♠️ · `chatVia: "marcus"` |
| Job | Per-thread state machine (NEW → ENGAGING → QUALIFYING → CALL_READY → HANDED_OFF / DEAD). Decides reply / call-pivot / escalate / stop; builds the call-ready queue. |
| Engine | `forge rei/ace.py` (controller) + `forge rei/conversation_engine.py` → `ConversationEngine` (global `CONVO`, `connector.py:1194`) |

## 2. Triggers

**Scheduled loop:** none — no thread, no heartbeat.

**Event trigger:** `_ace_update_from_screening(cid)` (`connector.py:1197-1231`), called
- after every Scout auto-screen (unnamed thread, `connector.py:1240`), and
- after a manual POST `/api/screening/run` (HTTP thread — not behind `FORGE_MARCUS`).

It always runs `CONVO.update`, then by mode: `supervised`/`full` → `ace.apply`; `shadow` → `ace.consider` + `call_ready_upsert` when CALL_READY; `off` → nothing more.

**Telegram**

| Form | Effect |
|---|---|
| `/ace` | status: mode + sent today (`telegram_io.py:856`) |
| `/ace off\|shadow\|supervised\|full` | `ace.set_mode` — handled before any other routing |
| Taps `acestop:<conv>` / `aceundo:<conv>` | `hold()` the thread (`ace.py:949`) |
| Tap `aceack:<conv>` | `ack()` a call-ready lead |

No name trigger, no `/task` target.

**HTTP** (private network + Host + same-origin POST — a request with no `Origin` header passes; no per-route operator auth)

| Method | Routes |
|---|---|
| GET | `/api/ace/state` · `/api/ace/status` · `/api/ace/callready` · `/api/ace/digest` |
| POST | `/api/ace/mode` · `/api/ace/ack` · `/api/ace/hold` |

**UI:** `AcePanel` in the Command page (`marcus.jsx:725`) · `AceStrip` on the Dashboard (`dashboard.jsx:734`) · Agent Control Center row `ace`. Hub row is read-only for mode.

## 3. Reads

Screening report → `_derive_facts` (no Claude) · Scout transcript (last inbound) · `marcus_engine.classify` · `test_mode.status()` · Atlas anchors for the call card · Marcus `_ai_draft` (via `make_proposal_for`, `hint=` question / `pivot=True`) · fact-adherence check (≤2 tries) · `sms_guard._quotes_price_or_offer`.

## 4. Outputs / writes

- `marcus_state/ace.json` (mode, sentToday, log), `conversations.json` (per-thread state, `held`), `call_ready.json`.
- Auto-sends: proposal marked `autonomous`+`ace` → `marcus.approve` → `sms_guard.guard`.
- Telegram receipts with ⛔ stop / ↩ undo; 📞 CALL-READY ping + bus `handoff`.
- `action_log` via `approve` / `sms_guard.record_success`.

## 5. Autonomy & gates

| Mode | Behaviour |
|---|---|
| `off` (default, `ace.py:30`) | state tracking only |
| `shadow` | drafts proposals, no auto-send |
| `supervised` | auto-sends qualifying questions + call-pivots, cap `FORGE_ACE_CAP_SUPERVISED` 3/day |
| `full` | same, cap `FORGE_ACE_CAP_FULL` 10/day |

- `FORGE_ACE_PIVOT_RESERVE` 1 → questions actually capped at 2 / 9; `FORGE_ACE_MAX_REPLIES` 5 per thread.
- `decide()` order: mode off → clock-out → Test Mode (non-whitelisted = stop) → terminal state → held → already pivoted.
- `sms_guard` then enforces window `FORGE_SMS_SEND_START`/`_END` (9–20 ET), dedupe, DNC/hard-no, price regex, `legit_check` (fails closed), `FORGE_SMS_DAILY_CAP` 80.
- PRICE and READY (≥3 facts) → call-pivot, never a number.
- Only the operator flips the mode (POST `/api/ace/mode` or `/ace`); no agent code calls `set_mode`.
- Kill: `/ace off`, clock out, per-thread ⛔ hold.

## 6. Self-improvement

None.

## 7. Chat & tasks

`/api/hub/chat {agentId:"ace"}` → Marcus's brain with ACE's live state (mode, sentToday, warning, log) injected, commands off. Tasks for `ace` show in Marcus's `open_tasks_block`.

## 8. Cost

Claude: yes (drafts + legit verdicts). Bucket **`operator`** — its threads are unnamed or HTTP handlers.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/ace/status | jq '{mode,sentToday,warning,testScoped}'
curl -s localhost:7799/api/ace/digest | jq '{mode,sentToday,cap,callReadyWaiting}'
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="ace")|{status,work,lastRun}'
```
