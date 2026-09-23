# style_agent — operator voice learner (worker, not a roster agent)

> Code refs are relative to `forge rei/`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Wholesale voice (feeds Marcus) · not in `agents_hub.AGENTS` |
| Job | Reads the operator's real SMS threads and rewrites the texting-voice and closing-plays skills Marcus drafts with. |
| Engine | `forge rei/style_agent.py` |

## 2. Triggers

**No in-process loop.** Triggered by HTTP only:

| Source | Schedule | Call |
|---|---|---|
| Box `forge-daily-learn.timer` → `deploy/daily_learn.sh` | `OnCalendar=*-*-* 20:00:00 America/New_York` (`deploy/setup_droplet.sh:111`) | POST `/api/style/run {"days":1}` (3rd of 6 calls) |
| Mac LaunchAgent `com.forge.reios.daily-learn` (`install_daily_learn.sh`) | daily 21:00 | same |
| Brain page "Learn from today" (`brain.jsx:214`) | manual | same |

**HTTP:** GET `/api/style/latest` · POST `/api/style/run {days}` (default 1).

**Telegram / bus:** none.

## 3. Reads

GHL conversations via `analytics_engine._pull_conversations` (4 pages), ≤40 threads × 50 messages.

## 4. Outputs / writes

Vault `Skills/yahjair-voice.md`, `Skills/closing-plays.md`, `Log/forge-daily-<date>.md`. No state file.

## 5. Autonomy & gates

Internal only — rewrites skills; sends nothing. No clock-out check.

## 6. Self-improvement

It IS the voice self-improvement loop for Marcus (and Scout reads `closing-plays`).

## 7. Chat & tasks

None.

## 8. Cost

Claude: one call per run (1800 tok). Bucket `operator`.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/style/latest | jq .
ssh box 'tail -n 20 /opt/forge/forge-rei/marcus_state/daily-learn.log'   # [voice] line
```
