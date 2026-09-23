# Daily brief / recap — roster row `briefs`

The Agent Control Center has ONE row for both Telegram pulses: hub id `briefs`,
business `system`, `chatVia: "orion"`, `ai: false`, `daily: true`, heartbeat
`daily_brief` (`forge rei/agents_hub.py`, `AGENTS`).

| Pulse | Card |
|---|---|
| Morning brief (default 08:00) | [daily-brief](daily-brief.md) |
| End-of-day recap (default 18:00) | [daily-recap](daily-recap.md) |

- Registry probe: `enabled` = brief OR recap enabled; `lastSuccessAt` = newer `lastSentAt` of the two.
- Chat `/api/hub/chat {agentId:"briefs"}` → Orion ([orion](orion.md)) with both configs injected.
- Tasks for `briefs` appear in Orion's chat prompt.

This file exists because `forge rei/test_agents_docs.py` requires one card named after every roster id.
