# Daily recap — end-of-day Telegram pulse (no brain)

> Code refs are relative to `forge rei/`. Verified against code 2026-09-22. Roster row is shared with the morning brief: hub id `briefs` — see [briefs](briefs.md).

## 1. Identity

| | |
|---|---|
| Business | System · hub id `briefs` (shared) · `chatVia: "orion"` · `ai: false` |
| Job | Evening "close the loops" message: same sections as the brief + FAILED TODAY + TOMORROW — FIRST 5. |
| Engine | `forge rei/daily_recap.py` + `connector._gather_brief_stats` |

## 2. Triggers

**Scheduled**

| Field | Value |
|---|---|
| Thread | `brief` → `_maybe_daily_recap` (`connector.py:2124`) |
| Gate | `FORGE_MARCUS` != `0`; `config.enabled` (default true) |
| Hour | `hour` default 18 (`daily_recap.py:23`), fixed offset `FORGE_TZ_OFFSET` (−4) |
| Due | enabled + past hour + not yet sent today (`daily_recap.py:84`) |
| Clock-out | skipped on `forge_ops.paused()` |
| Send | `telegram_io.send(dedupe_key="daily_recap:<day>")` |
| Heartbeat | `daily_brief` (shared) |

**Telegram:** outbound only.

**HTTP** (private network + Host + same-origin POST)

| Method | Routes |
|---|---|
| GET | `/api/recap` → config + live preview |
| POST | `/api/recap/send` (forced — skips `due()` + clock-out) · `/api/recap/config` |

**UI:** mobile More → End-of-day recap (`mobile/m_more.jsx:1156`).

## 3. Reads

Same `_gather_brief_stats` sources as the brief.

## 4. Outputs / writes

`marcus_state/daily_recap.json`. One Telegram message.

## 5. Autonomy & gates

Operator's Telegram only. Kill: `/api/recap/config {"enabled":false}` or clock out.

## 6. Self-improvement

None.

## 7. Chat & tasks

Via Orion (`chatVia`), same as the brief.

## 8. Cost

Zero Claude calls.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/recap | jq '{enabled,hour,lastSentDay,localTime}'
```
