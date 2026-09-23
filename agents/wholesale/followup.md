# Follow-up — Cadence Engine (no brain of its own)

> Code refs are relative to `forge rei/`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Wholesale (REI) · hub id `followup` · emoji 🔁 · `chatVia: "marcus"` |
| Job | Every 30 min: drafts no-response re-engage bumps (as Marcus proposals) and flags not-ready sellers whose check-back is due. Sends nothing itself. |
| Engine | `forge rei/followup.py` → `FollowupEngine`, connector global `FOLLOWUP` |

## 2. Triggers

**Scheduled loop**

| Field | Value |
|---|---|
| Thread | `followup` (`connector.py:5091`) |
| Gate | `FORGE_MARCUS` != `0`. No other on/off knob; never retired. |
| Interval | `FORGE_FOLLOWUP_INTERVAL`, default 1800 s (`followup.py:33`); first sweep after `min(120, INTERVAL)` |
| Clock-out | whole sweep skipped on `forge_ops.paused()` (`followup.py:86`) |
| Heartbeat | `followup` (`followup.py:107`) |
| Knobs | `FORGE_FOLLOWUP_TIERS` "24,72,168" h (max bumps = tiers) · `FORGE_CHECKBACK_MAX` 3 · `FORGE_FOLLOWUP_PER_SWEEP` 8 · `FORGE_FOLLOWUP_SCAN` 80 · 18 h quiet via `send_ledger` |

**Telegram:** no `/followup` command and no name trigger. Its bumps arrive as Marcus `proposal` alerts with ✅ `approve:` / 🗑 `mdismiss:` taps. Check-backs are sent with `/checkback name` (confirm button → `send_nurture`, `telegram_ops.py:565`). `/task` can't target it (it can never be the active Telegram agent).

**HTTP:** GET `/api/followup/status` only (`connector.py:2777`). No POST.

**Handoffs out:** `MARCUS.make_proposal_for(hint=…)` per bump → then `autopilot.maybe_send` (see [autopilot](autopilot.md)).

**Bus:** alert `checkback_due` (sent as `marcus`). Reads nothing.

**UI:** no page calls `/api/followup/status`; visible as the Agent Control Center row `followup`. Check-back send button lives on the Screening page.

## 3. Reads

GHL `/conversations/search` · Scout transcripts · `send_ledger.touched_within` · Marcus hard-no/soft-no/DNC checks · `SCREENER.screenings` (`not_ready`, `checkBackDays`, `nurtureDraft`). Acts only when we sent last and there is a genuine seller inbound.

## 4. Outputs / writes

- `marcus_state/followup.json`.
- Marcus proposals flagged `reengage: true` (`marcus_engine.py:1092`).
- Screening flags `checkBackDue` / `checkBackDueSince`.

## 5. Autonomy & gates

- Drafts only; every bump is a proposal you approve — unless Autopilot is on (then routine bumps auto-send behind Autopilot's gates).
- Kill: clock out, or `FORGE_MARCUS=0`.

## 6. Self-improvement

None.

## 7. Chat & tasks

- `/api/hub/chat {agentId:"followup"}` → Marcus's brain (`agents_chat`, commands off) with Follow-up's live state injected (`agents_hub._delegate_context`, `agents_hub.py:363`).
- Tasks filed for `followup` show in Marcus's `open_tasks_block` as "(for Follow-up)".

## 8. Cost

Claude: yes — each bump is a Marcus `_ai_draft`, plus Autopilot's legit verdict. Bucket `followup`.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/agents/registry | jq '.agents[]|select(.id=="followup")|{status,lastRun,pendingApprovals,lastError}'
curl -s localhost:7799/api/followup/status | jq '{lastRun,lastError,tracked,tiersHours}'
```
