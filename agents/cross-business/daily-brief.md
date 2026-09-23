# Daily brief — morning Telegram pulse (no brain)

> Code refs are relative to `forge rei/`. Verified against code 2026-09-22. Roster row is shared with the recap: hub id `briefs` — see [briefs](briefs.md).

## 1. Identity

| | |
|---|---|
| Business | System · hub id `briefs` (shared) · `chatVia: "orion"` · `ai: false` |
| Job | One stats-only Telegram message each morning: AGENCY / WHOLESALE / DAYCARE / AGENTS / OWNER TASKS. |
| Engine | `forge rei/daily_brief.py` (formatting) + `connector._gather_brief_stats` (`connector.py:1941`, the numbers) |

## 2. Triggers

**Scheduled**

| Field | Value |
|---|---|
| Thread | `brief` → `_brief_scheduler_forever` → `_maybe_daily_brief` (`connector.py:2123`) |
| Gate | `FORGE_MARCUS` != `0`; `config.enabled` (default true) |
| Hour | `hour` default 8 (`daily_brief.py:24`), runtime-editable, fixed offset `FORGE_TZ_OFFSET` (−4) |
| Due | enabled + past hour + not yet sent today (`daily_brief.py:87`) |
| Check tick | `FORGE_BRIEF_CHECK_SEC` 300 |
| Clock-out | skipped on `forge_ops.paused()` |
| Send | `telegram_io.send(dedupe_key="daily_brief:<day>")`; marked sent on success, dedupe skip, or "not configured" |
| Heartbeat | `daily_brief` |

**Telegram:** outbound only. No command.

**HTTP** (private network + Host + same-origin POST)

| Method | Routes |
|---|---|
| GET | `/api/brief` → config + live preview text |
| POST | `/api/brief/send` (`force=True`: skips `due()` and clock-out) · `/api/brief/config` (enabled, hour) |

**UI:** mobile More → Daily brief (`mobile/m_more.jsx:1062`): toggle, hour, preview, send now · Agent Control Center row `briefs`.

## 3. Reads

`_gather_brief_stats`: dashboard stats, Scout summary/leads, Marcus proposals, cost digest, red heartbeats, Owner Actions, agency call sheet + stats, `daycare_leads.view()`, `agents_hub.registry()`. Archived businesses skipped; no dropship section. A failing source drops its line — never a fake 0 (`forge rei/test_brief_sections.py`).

## 4. Outputs / writes

`marcus_state/daily_brief.json` (config + lastSentDay/At). One Telegram message to the operator.

## 5. Autonomy & gates

Operator's Telegram only. Nothing outward to customers. Kill: `/api/brief/config {"enabled":false}` or clock out.

## 6. Self-improvement

None.

## 7. Chat & tasks

`/api/hub/chat {agentId:"briefs"}` → Orion's `_director_chat` with both configs injected. Tasks for `briefs` show in Orion's `open_tasks_block`.

## 8. Cost

Zero Claude calls. $0 (the `brief` thread's paid call is Orion's).

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/brief | jq '{enabled,hour,lastSentDay,localTime}'
curl -s localhost:7799/api/system/health | jq '.loops[]|select(.loop=="daily_brief")'
```
