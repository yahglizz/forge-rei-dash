# Daycare Lead Desk — enrollment lead sweep (worker, not a roster agent)

> Code refs are relative to `forge rei/`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Daycare · **not** in `agents_hub.AGENTS` → no hub id, no Agent Control Center row, no chat |
| Job | Every 15 min reads the daycare GHL (GET only), derives each enrollment lead's stage + response time, lists who needs a human, pings the owner. |
| Engine | `forge rei/daycare_leads.py` (module, `run_forever(DAYCARE_GHL)`) |

## 2. Triggers

**Scheduled loop**

| Field | Value |
|---|---|
| Thread | `daycare_leads` (`connector.py:5109`) |
| Gate | `FORGE_MARCUS` != `0` **and** `FORGE_DAYCARE_LEADS` != `0` (default on) |
| Off | `FORGE_DAYCARE_LEADS=0` → `forge_heartbeat.retire("daycare_leads")` (`connector.py:5113`) |
| Interval | `FORGE_DAYCARE_LEADS_INTERVAL`, default 900 s (`daycare_leads.py:52`); first sleep aligned to the last run |
| Clock-out | sweep skipped on `forge_ops.paused()` |
| 429 | aborts the sweep, waits for Retry-After |
| Heartbeat | `daycare_leads` (`daycare_leads.py:636`) |

**Telegram:** outbound only (owner pings). No command, no name trigger.

**HTTP** — daycare router, session-gated

| Method | Route |
|---|---|
| GET | `/api/daycare/leads` → `view()` (state file only, no network) |
| POST | `/api/daycare/leads/stage` → `set_stage` (LOCAL mark, never written to GHL) |

**Bus:** sends `daycare_leads→operator` alerts (contact id + reason codes only). Reads nothing.

**UI:** Lead Desk card on the Daycare Dashboard (`daycare.jsx:221`, `DldLeadDesk`).

**Feeds:** Solomon's brief (`leadDesk`) · Owner Actions · Mission Control daycare tiles · daily brief/recap stats.

## 3. Reads

GHL contacts (6×100), conversations search, ≤50 per-contact lookups, messages, tasks · local stage marks + the contact→child ledger. Stage tags from `daycare_leads.STAGE_TAGS`. No creed, skills or playbook.

## 4. Outputs / writes

- `marcus_state/daycare_leads.json`, `marcus_state/daycare_lead_stages.json`.
- Owner alerts: bus + Telegram (first name only in Telegram, deduped).
- Nothing to GHL, nothing to families.

## 5. Autonomy & gates

- GET-only on GHL; sends nothing to families.
- Alerts only 8am–9pm ET, once per lead+reason episode; first run seeds silently.
- Kill: `FORGE_DAYCARE_LEADS=0` + restart.

## 6. Self-improvement

None.

## 7. Chat & tasks

None. Ask Solomon — the Lead Desk is part of his brief input.

## 8. Cost

Zero Claude calls (imports no `review_agent`). $0.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="daycare_leads")'
curl -s localhost:7799/api/daycare/leads | jq '{lastRunAt,lastOkAt,error,kpis}'   # needs a daycare session
```
