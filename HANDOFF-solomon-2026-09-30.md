# HANDOFF — Solomon (daycare agent) growth-only rebuild · 2026-09-30

Paste this file's path into a new chat: "read HANDOFF-solomon-2026-09-30.md and continue".
Everything below is **deployed to the box** and pushed to GitHub (auto-sync). Nothing is half-done in the working tree.

## Where things stand (30 seconds)
- **Solomon = the daycare's ONE agent, growth director: enrollment only.** Paperwork, compliance, billing collection, staff admin are NOT his lane (owner decision today; do not re-add).
- **Blocked on the owner:** (1) **Anthropic credits on the box are empty** (since ~Sep 22) — every Claude call fails: Solomon · Replies can't draft, brief can't run. (2) **Auto-send is OFF** and should stay off until credits are back and A2P texting registration is confirmed in GHL (notes said "not approved" as of Sep 23; unverified). (3) Meta token on the box is invalid (ads fall back to mock).
- Active businesses: Wholesale (flagged `maintenance`), Agency, Daycare. Archived: Dropship, Agency Personal lens. One agent per biz: Marcus · Dyson · Solomon · (Midas, archived) · Orion CEO.

## What was built this session
1. **Growth-only skills rewritten** (`forge-solomon/skills/`): creed `daycare-evidence-discipline.md`, `solomon-director-craft.md` (growth craft + triage order), `solomon-roster-craft.md` (seats + retention), `solomon-systems-craft.md`, `solomon-adops-craft.md`, `solomon-decision-loop.md`, `solomon-playbook.md` (floor) + vault `Skills/solomon-playbook.md` (learned; calibrations only).
2. **Brief prompt** (`forge rei/daycare_director.py` `build_brief`): growth triage; exact urgency/area vocab; phone-length caps; robust JSON parse; filters paperwork metrics/alerts; `startsDesk` + per-room `openSeats`/`agesMonths`/`centerLabel` (empty Supabase roster → seats Unknown); bus dedupe; NORTH_STAR trimmed to §1–2+§5; only growth-era brain notes (≥ `GROWTH_SINCE` 2026-09-30) feed back; `learn()` drift guard `_paperwork_drift`; chat Solomon now gets the same skills (`top_skills_text`).
3. **Business brief bug fixed:** `daycare_context.context_block()` was cut at 3,500 chars (dropped offers/Oct-23 expiry/referral). Now 12,000.
4. **Eval loop that converged 6 → 9.5/10 without API credits:** run `capture_solomon_prompt.py` pattern on the box (monkeypatch `review_agent._claude`, `FORGE_VAULT=/opt/forge/vault`, bus read with `mark_read=False`) → stand-in model writes the brief from the captured prompt + live data → growth-expert critic + prompt-coherence critic grade → fix → repeat. (Script was in the session scratchpad; recreate from the `solomon-growth-only` memory if needed.)
5. **Speed-to-lead (Solomon · Replies, `daycare_replies.py`):** sweeps every **60 s**, grace **90 s** (`FORGE_DAYCARE_REPLY_GRACE_SEC`), STL-pending wait 6 min → a parent gets an answer ~90 s–5 min after texting. Reads the GHL automated first text + form facts (child age, desired start) so it never re-asks. Lead-qualifying ladder lives in `forge-daycare/skills/daycare-parent-reply.md` §2b (age → center → start → subsidy → tour).
6. **Telegram hand-off:** `notify_owner()` pings the **daycare** chat when he hits an unknown (`unknowns`) or an escalation topic. All business alerts now route to their own biz chat (`connector._WATCHDOG_BIZ`); **HQ keeps only system alerts** (Anthropic credits/auth, clock, sync, graph) + Orion.
7. **Opt-in AUTO-SEND (default OFF):** `FORGE_DAYCARE_REPLY_AUTO=1` in `/etc/default/forge-reios` + `systemctl restart forge-reios`. Sends only clean, flag-free answers to enrollment **leads** in categories tour/subsidy/availability/enroll/pricing-deflect; `approve()` live re-check, 8am–9pm ET, 30/day, 3/contact, Telegram receipt, action-logged, staff reply in GHL kills it. Documented as a rule-2 exception in `CLAUDE.md` §2.
8. **Website facts merged** (subagent read all 10 pages of atouchofblessing.com) into the fact sheet `daycare-parent-reply.md` §1 (verified 2026-09-30): programs/ages, care types, school pick-up, 24-hr response promise, virtual tours at `atouchofblessing.com/#tours` (921 + 2318 only; 1923 "coming soon"), "no enrollment fee right now", parent-app setup, never quote the $1,400–$1,500 market average as our price.
9. **CCIS wording:** say **"we help families through the CCIS process"** — never "we handle/do the paperwork" (changed in skills + brand-kit docs).
10. **Docs/Codex:** `AGENTS.md` (root, rewritten), `forge-solomon/AGENTS.md`, `forge-daycare/AGENTS.md` (new — Codex reads AGENTS.md, not CLAUDE.md), `agents/README.md`, `agents/daycare/solomon.md`, `CLAUDE.md` §2/§5/§10/§11, `NORTH_STAR.md` §5/§7. Memory: `solomon-growth-only`, `agents-and-active-businesses`.

## Open items / decisions for the owner
- **Top up Anthropic credits** (box). Then: confirm A2P 10DLC approved in GHL → say "turn on auto-send" and flip the env knob on the box.
- **Website copy still says "we handle the paperwork"** (`website/child-care-works.html` + home why-us) — opposite of the new wording; site is a separate repo (`~/Desktop/A Touch of Blessings — Brand Kit/website`). Also `ATOB-META-CAMPAIGN-BRIEF.md` ad copy. Not edited yet — owner must approve site copy.
- Website issues found: $100 bonus countdown/banner/popup go stale Oct 23; referral has no expiry; 2318 "now open" vs "pre-enroll"; 1923 "Take a Virtual Tour" button leads to "coming soon"; "Refer a Friend" goes to plain enroll form. **Offer successor due by Oct 16.**
- Entity rule: site says A Mother's Touch is "one family" and shows the $100 bonus on the 1923 card; owner's Aug-16 rule keeps it a separate legal entity — Solomon still won't offer ATOB deals to 1923. Confirm that's still wanted.
- Roster data: Supabase shows 0 children at 2318 with Pre-K/School-Age rooms (capacity 32) vs brief's infant/toddler-only 37 slots → seats are "Unknown"; owner/director needs to confirm open seats by age band.
- Lead Desk (real data today): 13 families needing a human (oldest 39 days, nobody owns the queue), 5 of 13 "Center unknown" (form isn't capturing location), 2 proposed starts unconfirmed (Seara Peterson today, Tyeesha Robinson tomorrow).
- Wholesale shows `maintenance: true` in `/api/businesses` — documented as-is, not investigated.
- Dropship chat isn't bound (`/bind dropship`), so its alerts (archived biz) fall back to HQ.
- Suggested next build: surface the Lead Desk queue in Owner Actions sorted by Solomon's call order (proposed starts → 2318 lead → newest → center-unknown).
- Optional: `FORGE_SOLOMON_BRIEF=1` on the box brings the daily growth brief back (~$0.15/day).

## How to verify / work
```bash
cd "/Users/yg4st/forge rei dash/forge rei"
export FORGE_ACTION_LOG=$(mktemp)
python3 test_solomon_growth.py && python3 test_daycare_replies.py && python3 test_agents_docs.py
python3 test_telegram_biz_chats.py && python3 test_daycare_leads.py && python3 test_daycare_starts.py
./deploy/push.sh root@24.199.81.124        # or: git push origin main (box self-deploys ≤60 s)
```
Box: `ssh -i ~/.ssh/forge_droplet root@24.199.81.124`, service `forge-reios`, live prompt/data check via the capture script. Live state: `curl localhost:7799/api/daycare/replies` (shows `auto.on`, `lastSweep`, `error`), `/api/businesses`, `/api/agents/registry`.

## Rules to keep (from `CLAUDE.md`)
Rule 2 propose→approve (only documented opt-in exceptions); additive edits; validate (`ast.parse`, `node deploy/valjsx.js`) before deploy; secrets never in chat/files; caveman answers; audits on Sonnet 5; everything about a business → that business's Telegram chat only.

## Key files
`forge rei/daycare_director.py` (brief) · `daycare_replies.py` (Reply Desk + auto-send + notify_owner) · `daycare_leads.py` · `daycare_starts.py` · `daycare_context.py` · `agents_hub.py` · `connector.py` (`_WATCHDOG_BIZ`) · `forge-solomon/skills/*` · `forge-daycare/skills/{daycare-context,daycare-parent-reply,daycare-voice,enrollment-ad-agent}.md` · tests `test_solomon_growth.py`, `test_daycare_replies.py`.
