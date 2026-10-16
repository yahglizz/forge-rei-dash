# Audit — Dyson (agency lead) + Eco lane · tick 2 · 2026-10-16 · PROPOSE-ONLY

Live roster: id=dyson, "Agency Lead — sites, code edits + ads", business=agency, WAITING FOR APPROVAL, 10 tasks done / 0 failed, 3 open tasks, learnCount 4 (last learn 2026-07-29). Sub-lane Eco = "Ads Strategist".
Files read: agents/agency/dyson.md (89), eco.md (87), forge rei/agency_agents.py, agency_dyson.py, agency_eco.py, agency_build_studio.py, box systemd timers + daily_learn.sh.

## Role match: roster, card and engine agree on identity. Role clarity 7/10.
- Title drift in three places: card header "Build Agent", roster "Agency Lead — sites, code edits + ads", agency page "Edit Agent · drafts & ships website/code changes". Pick one and use it everywhere.
- Good: no scheduled loop, so Dyson costs $0 unless you chat with him, give a task, or generate a draft.

## Findings (ranked by $ and risk)
1. **Self-improve is truly off — verified live.** `_maybe_learn` is gated by `self_improve_on()` (agency_agents.py:663). The nightly timer `forge-daily-learn` (8 pm ET) fires every night but `daily_learn.sh` exits immediately: log shows "daily learn skipped: FORGE_SELF_IMPROVE is off" every day through Oct 16. $0. Card §6 still describes both loops as active — update it.
2. **One recurring spend is NOT behind the switch: the weekly review.** `forge-review.timer` POSTs `/api/review/run {"days":7}` every Monday 08:00 UTC, one Claude call over ~400 conversations. Last saved review is 2026-07-30 (the Oct 12 run hit the credit outage). Next run Mon Oct 19 will actually spend. It is useful (it found the 37 pending Marcus replies), so propose: keep, cap input size, pin it to Haiku or Sonnet explicitly, and add it to the Costs tab by name.
3. **Model tiers for Dyson/Eco (all SMART today except learn):**
   | Job | Today | Proposed | Why |
   |---|---|---|---|
   | Dyson chat reply (700 tok) | Sonnet 5.5 | keep | owner reads closely |
   | Dyson task plan (500 tok) | Sonnet 5.5 | Haiku | short plan, owner reviews |
   | Dyson draft site/code edit (4096 tok) | Sonnet 5.5 | keep | client-facing code |
   | Build Studio architect (2600, medium) | Sonnet 5.5 | keep | design judgment, one-off |
   | Eco recommendations (3200) | Sonnet 5.5 | keep | decides scale/hold/kill money |
   | Eco competitor read (2200) | Sonnet 5.5 | Haiku | extraction |
   | Eco ad concept/creative (3200, 2200 x2) | Sonnet 5.5 | keep, manual only | creative |
   | learn() / tip | Haiku (no model arg) | leave off | recurring bill |
   Net saving: small (two jobs to Haiku, ~half price on those). Real money here is in what Eco recommends spending on Meta, not in Claude calls.
4. **Eco shows mock data unlabeled (9/22 doc).** Ad payloads carry `dataSource live|mock|token_rejected` but the Eco page does not label mock — a wrong recommendation based on fake numbers is the highest-impact risk in this agent. Verify now, fix = show the label.
5. **Cost tracker mislabel:** `cost_tracker.AGENT_THREADS` lists `dyson` but no thread has that name, so his spend bills to `operator`. By-agent report undercounts him.

## Integrations for Dyson / Eco
| System | State |
|---|---|
| GHL agency sub-account | connected |
| Vercel (client site deploys) | connected; ships only after approval |
| Meta Marketing API (agency) | **demo-account guard**; token state unverified; Eco page mock unlabeled |
| Metricool (social) | agency token state unverified |
| Higgsfield (creative) | key set |
| n8n | **broken**: base URL returns 404, mock catalog shown as connected·LIVE (9/22) |
| Telegram agency chat | connected |
| LeadScraper -> Google Sheet | **Mac-only**, not on the box |
| Google Sheets (call sheet) | missing, planned (GOOGLE-PLAN P1) |
| Google Calendar (discovery calls) | missing, planned |
| Gmail (outreach drafts) | missing, planned |
| Search Console / Business Profile (client reporting) | missing, planned |
Brand kit: not applicable (ClientForge has its own brand); A Touch of Blessings kit only governs daycare-facing agents.

## Proposed changes (NOT applied)
- Unify Dyson's title; update card §6 (self-improve off) and §8 (add weekly review and cost-bucket gap).
- Move Dyson task-plan and Eco competitor read to Haiku (2 one-line edits).
- Label mock data on the Eco page; relabel n8n mock as "demo".
- Add `dyson` thread alias in cost_tracker.
- Decide weekly review: keep + cap (recommended).
