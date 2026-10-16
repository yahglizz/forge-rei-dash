# Audit — Solomon (daycare Executive/Growth Director) · tick 1 of restart · 2026-10-16 · PROPOSE-ONLY

Live roster: id=solomon, role "Growth Director — enrollment", business=daycare, status WAITING FOR APPROVAL, tasksCompleted 6, tasksFailed 0, errorCount **2904** (all from the Claude outage Aug 1 – Oct 12; AI is OK again, lastOk 2026-10-16).
Files read: agents/daycare/solomon.md (269 lines, main + 5 lanes), forge rei/daycare_director.py, daycare_replies.py, daycare_ads_autopilot.py, daycare_ads_studio.py, forge-daycare/skills/*, forge-solomon/skills/*, brand kit BRAND-KIT-FOR-AGENTS.md.

## Role match: roster, card and engine agree (name, role, business). Role clarity 8/10.
Card has all 9 standard sections plus lanes Replies / Leads / Starts / Ads / Revive. Title drift: card header says "Executive Director", roster says "Growth Director". Pick one.

## Findings (ranked by $ and risk)
1. **Replies lane = the only always-on Claude spender in daycare.** 60 s loop, up to 8 Sonnet 5.5 drafts per sweep (`FORGE_DAYCARE_REPLY_MAX`), gated by `gate()`. Worst case 8 x 1440 = 11,520 calls/day if the gate misfires. During the outage it logged 2,904 errors. Proposal: add a per-day draft cap (e.g. 60) and a per-contact cooldown; no quality loss. Model stays Sonnet 5.5: parent replies are customer-facing.
2. **Card is stale in 3 places.** (a) §7 says top skills are empty ("daycare_director has no top_skills_text"); code now has `top_skills_text()` at daycare_director.py:275 and the craft skills are described as loaded. (b) Replies model listed as `claude-sonnet-5`; code default is `review_agent.SMART_MODEL` = claude-sonnet-5-5. (c) Replies card says "5-min sweep"; code interval is 60 s (`FORGE_DAYCARE_REPLIES_INTERVAL`). Doc-only fixes.
3. **Model tiers per Solomon job (proposed table, matches code except where noted):**
   | Job | Today | Proposed | Why |
   |---|---|---|---|
   | Parent reply draft | Sonnet 5.5 low | keep | customer-facing, brand voice |
   | Owner chat with Solomon | Sonnet 5.5 | keep | owner reads closely |
   | Growth brief (2 calls, manual only) | Sonnet 5.5 medium, 5000 tok | keep, but 2nd call (competitor read) -> Haiku | extraction, not judgment |
   | Ads optimizer judge | Haiku | keep | already cheap |
   | Ad creative copy (Nova) | Sonnet 5.5, 3000 tok | keep, cap to manual trigger | creative |
   | learn() playbook rewrite | no model arg -> Haiku | leave off (FORGE_SELF_IMPROVE=0) | recurring bill |
   | Leads, Starts lanes | zero Claude | keep rules-only | already $0 |
4. **Brand-kit alignment.** daycare-voice.md references the kit (1 hit) and uses "center" (never "facility") — good. daycare-parent-reply.md has 0 references to the brand kit but 7 "unknown / ask Yahjair / never invent" guards — good on facts, add one line pointing to BRAND-KIT-FOR-AGENTS.md rules 9–10 (voice, never invent a business fact, child's name is the GHL contact identity). Code-level `flags()` already blocks unverified phone, dollar figures, emoji.
5. **Integrations for Solomon** (live-verified where noted):
   | System | State |
   |---|---|
   | GHL daycare sub-account | connected (loops green, `daycare_replies` age 56 s) |
   | Supabase (app, RLS) | connected (`FORGE_DAYCARE_LIVE=1`); doc says 9 migrations behind — verify |
   | Website + /api/enroll -> GHL | connected (per 9/22 doc) |
   | Telegram daycare chat | connected |
   | Meta ads (daycare) | **unverified**: 9/22 doc says token invalid (OAuth 190); ads loop is green but may be reading mock data — check `/api/daycare/ads` mode |
   | Stripe | key set, owner-initiated only |
   | **Google Calendar (tour booking)** | **missing** — tours arranged by text/phone, GHL pipeline only uses "New Lead" |
   | **Gmail (management@)** | **missing** |
   | **Business Profile (3 locations: reviews/hours/posts)** | **missing** |
   | **Search Console (atouchofblessing.com)** | **missing** |
   | Sheets | missing (no need today) |

## Proposed changes (NOT applied)
- Edit solomon.md: fix header title, §7, Replies model + interval, add Model-tier table (item 3).
- Add one-line brand-kit pointer to daycare-parent-reply.md.
- Add daily draft cap + cooldown in daycare_replies.py (needs build gate).
- Wire Google per output/agent-audit/GOOGLE-PLAN.md.
- $ impact: cap prevents runaway (worst case ~$20+/day at 8 Sonnet calls x 1440 sweeps); normal-day savings ~cents.
