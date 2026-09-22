# Daily brief / recap

**Business:** System · **Emoji:** 🗞️ · **Roster id:** `briefs`
**Role:** morning brief + end-of-day recap on Telegram.

Stats-only pulses: the morning brief (default 08:00) and the evening recap
(default 18:00), one send per day each, in the `FORGE_TZ_OFFSET` zone.

## Autonomy — where the line sits

Sends to the **operator's** Telegram only. **No Claude call.** It has no brain of
its own — in chat and tasks, **Orion answers for it** ([orion.md](orion.md)).

## Where it lives

- **Engine:** `forge rei/daily_brief.py` + `forge rei/daily_recap.py`, ticked by the
  connector's brief scheduler (heartbeat `daily_brief`, shared with Orion)
- **State:** `marcus_state/daily_brief.json`, `daily_recap.json`

## Routes

`/api/brief` · `/api/recap` · POST `/api/brief/send|config` · `/api/recap/send|config`
