# Autopilot — Re-engage Auto-send (no brain of its own)

> Code refs are relative to `forge rei/`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Wholesale (REI) · hub id `autopilot` · emoji 🛩️ · `chatVia: "marcus"` |
| Job | Opt-in: auto-sends the routine no-response re-engage bumps Follow-up drafts. Nothing else. |
| Engine | `forge rei/autopilot.py` (module functions) |

## 2. Triggers

**Scheduled loop:** none of its own. `autopilot.maybe_send` has one caller — `followup._scan_no_response` right after a bump draft (`followup.py:165-176`) — so it runs on the `followup` thread every 30 min.

**Telegram**

| Form | Effect |
|---|---|
| `/autopilot` | status (`telegram_ops.py:650`) |
| `/autopilot on` / `/autopilot off` | `autopilot.set_enabled` |
| `/report` | includes autopilot status |

No taps, no name trigger, no `/task` target.

**HTTP** (private network + Host + same-origin POST)

| Method | Routes |
|---|---|
| GET | `/api/autopilot/status` |
| POST | `/api/autopilot/toggle {enabled: bool}` (`connector.py:3400`) |

**UI:** "Re-engagement Autopilot" switch inside `AcePanel` (`ace.jsx:145`) · Agent Control Center row `autopilot`.

## 3. Reads

Its state · `forge_ops.paused()` · proposal flags `reengage`, `ace`, `pivot`, `acePivot`, `classification` · `send_ledger` (18 h) · `legit_check.verdict` (cached Claude judgment) · `MarcusEngine._scrub_voice`.

## 4. Outputs / writes

- `marcus_state/autopilot.json` (enabled, sentToday, log).
- Proposal marked `autopilot`+`autonomous` → `marcus.approve` → `sms_guard`.
- Telegram receipt (no buttons, dedupe `autopilot:<pid>`), bus alert `autopilot_send`, `action_log`.

## 5. Autonomy & gates

Default **off** (`autopilot.py:62`). Gate order (`autopilot.py:134-169`):
1. enabled → 2. not clocked out → 3. `reengage is True` → 4. not ACE-owned → 5. class not DNC/PRICE/READY/HELP → 6. 9–20 ET (hardcoded `SEND_START`/`SEND_END`) → 7. `FORGE_AUTOPILOT_CAP` (10/day) → 8. send-ledger dedupe → 9. legit verdict.

Then the full `sms_guard` stack runs again. Kill: `/autopilot off`, the dashboard switch, or clock out. Not limited by Test Mode (see README inconsistencies).

## 6. Self-improvement

None.

## 7. Chat & tasks

`/api/hub/chat {agentId:"autopilot"}` → Marcus's brain with `autopilot.status()` injected, commands off. Tasks show in Marcus's `open_tasks_block`.

## 8. Cost

Claude: the legit verdict only. Bucket `followup`.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/autopilot/status | jq '{enabled,sentToday,cap}'
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="autopilot")|{status,work}'
```
