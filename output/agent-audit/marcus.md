# Audit — Marcus (wholesale lead agent)  · tick 1 · 2026-10-16 · PROPOSE-ONLY

Files read: agents/wholesale/marcus.md, forge rei/marcus_screening.py, marcus_engine.py (call sites), review_agent.py (model policy), AGENTS.md.

## Role clarity: strong (8/10)
Card has identity, triggers, context load order, outputs, autonomy gates, self-improve, chat, cost, verify. Hard never-rules are code-enforced. Nothing to restructure.

## Findings (ranked)
1. **Card §8 is wrong about model.** Says screening runs "Sonnet 5 medium effort". Code: `marcus_screening.py:417` calls `review_agent._claude(..., effort="medium")` with NO `model=`, so it uses `MODEL` = FAST = Haiku 4.5 (effort is dropped for non-adaptive models). Same for Atlas `deal_prep.py:360/541`. Real cost is Haiku, lower than the card claims. Fix = doc edit only. Decide: is Haiku good enough for screening reports? Spot-check 5 recent reports; if quality is fine, leave as is (cheapest).
2. **Card §6 is stale.** Says screener learn() fires every 15 screenings and nightly. AGENTS.md says scheduled self-improvement has been OFF since 2026-09-30 (`FORGE_SELF_IMPROVE` default 0). Card verified 2026-09-22. Fix = doc edit.
3. **Drafts are the one place worth Sonnet.** `_ai_draft` = Sonnet 5.5, 300 tok + 2048 thinking headroom, one call per approved seller reply. At seller-reply volume this is cents/day. Keep. Only consider Haiku for re-engage bumps (already FAST via reengage_draft.py:186).
4. **Prompt weight.** Screening loads skills[:9000] chars + voice[:2500] + brain context + 20 thread msgs per screen (~4-5k input tokens on Haiku = ~$0.005). Fine. No change.
5. **Box state:** FORGE_MARCUS=1 on the 247 box; legacy SMS loop FORGE_MARCUS_SMS defaults off. Fine.

## Proposed changes (NOT applied — needs your go)
- Edit agents/wholesale/marcus.md §6 and §8 to match code (model = Haiku for screening, Sonnet for drafts; self-improve off).
- Add a "Model tier" row to the §1 identity table: Screener=FAST, Drafter=SMART, Chat=SMART.
- $ impact: ~$0 (accuracy fix, not a saving).
