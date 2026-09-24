# review_agent — shared Claude helper + weekly review (worker, not a roster agent)

> Code refs are relative to `forge rei/`. Verified against code 2026-09-22.

## 1. Identity

| | |
|---|---|
| Business | Wholesale playbook (feeds Marcus) + shared infra · not in `agents_hub.AGENTS` |
| Job | (a) `_claude()` / `_api_key()` / `claude_urlopen` — the Claude call most agents use; (b) the review job: 5 analysts + a synthesis that rewrites Marcus's playbook. |
| Engine | `forge rei/review_agent.py` |

## 2. Triggers (review job)

**No in-process loop.** HTTP only:

| Source | Schedule | Call |
|---|---|---|
| Box `forge-review.timer` (`deploy/setup_droplet.sh:135`) | `OnCalendar=Mon *-*-* 08:00:00`, `Persistent=true` — no timezone → box-local | POST `/api/review/run {"days":7}` |
| Box `forge-daily-learn.timer` → `daily_learn.sh` | daily 20:00 America/New_York | POST `/api/review/run {"days":1}` |
| Mac LaunchAgent `com.forge.reios.weekly-review` (`install_review_schedule.sh`) | Mon 08:00 | `{"days":7}` |
| Analytics page "AI Weekly Review" (`analytics.jsx:46`) | manual | POST `/api/review/run` |

**HTTP:** GET `/api/review/latest` · POST `/api/review/run {days}` (default 30). A synthesis failure returns `{hasReview:false, error}`, not a 500.

## 3. Reads

Analytics metrics (`get_metrics`) · `agent_coach.insights_block("marcus","wholesale")` in the synthesis.

## 4. Outputs / writes

Vault `Log/forge-review-<date>.md`, `Skills/marcus-playbook.md` · `marcus_state/review_latest.json`.

## 5. Autonomy & gates

Internal only. No clock-out check.

Shared helper facts: model `FORGE_REVIEW_MODEL` (default `claude-sonnet-5`), `FORGE_HAIKU_MODEL` (default `claude-haiku-4-5-20251001`), `FORGE_DRAFT_MODEL` (Marcus drafts, default = review model); on Sonnet 5 every call sends adaptive thinking + an explicit `effort` (`_claude(..., effort="low"|"medium")`, default low) with thinking headroom added to `max_tokens` (`thinking_params`) and a budget-sized timeout (`call_timeout`); older model ids get neither field; prompt caching when system ≥1200 chars; retries ≤2 (2 s, 5 s) on 429/500/502/503/529 + connection errors, never on timeouts; stamps `forge_heartbeat.ai_ok/ai_fail` and `cost_tracker.record_anthropic`.

## 6. Self-improvement

It IS Marcus's playbook loop. Note the nightly `days=1` run overwrites the Monday 7-day playbook.

## 7. Chat & tasks

None.

## 8. Cost

Claude: 6 calls per run (5 × 900 tok + 2000). Bucket `operator`.

## 9. Verify it's alive

```bash
curl -s localhost:7799/api/review/latest | jq '{hasReview,error}'
ssh box 'systemctl list-timers forge-review.timer forge-daily-learn.timer'
```
