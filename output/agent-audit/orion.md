# Audit — Orion (cross-business CEO) · tick 3 · 2026-10-16 · PROPOSE-ONLY

Live roster: id=orion, "CEO — oversees the main agents", business=cross, IDLE, 6 tasks done / 0 failed.
Files read: agents/cross-business/orion.md (77), agents/portfolio/orion.md (6-line stub), forge-mission/skills/orion-playbook.md (43), forge rei/mission_control_agent.py, connector.py (brief scheduler gate), box mission_brief.json + GET /api/mission-control/brief.

## Role match: identity agrees, title does not. Role clarity 7/10.
- Card header "Chief of Staff (cross-business CEO brief)" vs roster "CEO — oversees the main agents". Pick one. (A CEO decides; this agent only proposes — "Chief of Staff" is the more honest title, but the dashboard UI says CEO.)
- Duplicate card: agents/portfolio/orion.md is a stub kept for old links — fine, but delete once root AGENTS.md links are repointed.
- Card has all 9 standard sections. Gates are correct: proposes only, never acts.

## Findings (ranked)
1. **Mission Control shows a 78-day-old brief as today's greeting.** The CEO brief scheduler is OFF (`FORGE_BRIEFS` defaults 0, connector.py:2178). Last build day on the box: **2026-07-30** (18 briefs ever). `GET /api/mission-control/brief` still serves it: "Good morning, Yahjair... Day 16 daycare zero-staff status is now a DHS license-suspension risk — physical audit TODAY". A stale alarm presented as current is the most harmful thing in this agent. Fix options: (a) show the brief's age and grey it out after 36 h, or (b) re-enable the daily brief. Either is small.
2. **Re-enabling is nearly free.** The daily brief and recap are templated (no Claude). Orion's CEO brief is one Sonnet 5.5 medium call, max 2400 tok (+6144 thinking headroom), once per day, ~ $0.03–0.06/day, ~ $1–2/month. Card §8 says "one scheduled call/day" as if live — wrong while OFF, $0 today.
3. **Model tiers:**
   | Job | Today | Proposed | Why |
   |---|---|---|---|
   | Daily CEO brief | Sonnet 5.5 medium, 2400 | keep | cross-business synthesis the owner reads first thing |
   | Orion chat | Sonnet 5.5 | keep | owner reads closely |
   | learn() playbook rewrite | no model arg -> Haiku, gated off | leave off | recurring bill, FORGE_SELF_IMPROVE=0 |
   | `_gather` (reads all agents) | no Claude | keep | already free |
4. **What Orion does not read yet** (`_gather`): Scout + screener, agency approvals/requests, Solomon status/brief, Midas (if not archived), bus, coaching feed. Missing and worth adding as plain data (no extra Claude calls): cost tracker line (today / month-to-date USD + AI health), Google Calendar agenda, unread-that-matters Gmail count, Search Console one-liner per site, review count/score per location (after Business Profile).
5. **Cost bucket gap:** the scheduled brief bills to `brief`, manual runs to `operator`; no `orion` bucket, so By-agent reports undercount him.
6. **Telegram push** of the brief is off by default (`FORGE_MISSION_BRIEF_TELEGRAM=0`). If you re-enable the brief, turn this on so it reaches your phone, with quiet hours.

## Integrations for Orion
| System | State |
|---|---|
| Agent bus + coaching feed | connected (internal) |
| Telegram (HQ chat) | connected; brief push off |
| GHL, Supabase, Meta, Stripe | indirect, through Marcus / Dyson / Solomon summaries |
| Cost tracker | exists, not fed to Orion |
| Google Calendar / Gmail / Search Console / Sheets | missing; project, APIs, OAuth client and scopes now exist (see GOOGLE-PLAN.md), code not built |
| Google Business Profile | blocked: both profiles unverified |

## Proposed changes (NOT applied)
- Title: align card and roster; update §8 (OFF today, $0) and add FORGE_BRIEFS note.
- Staleness guard in the Mission Control greeting (show "Brief from Jul 30 — stale") — small UI + endpoint change.
- Optional: set `FORGE_BRIEFS=1` and `FORGE_MISSION_BRIEF_TELEGRAM=1` on the box (your call; ~$1–2/month).
- Add `orion` cost bucket alias; add cost + Google lines to `_gather` after P1 of the Google plan.
