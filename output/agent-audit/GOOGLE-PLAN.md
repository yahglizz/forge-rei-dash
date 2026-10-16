# Google integration plan — all businesses · DRAFT for approval · 2026-10-16

Status today: **zero Google integration in the dashboard code** (one stray mention in connector.py; LeadScraper writes to a Google Sheet from the Mac only). Everything below is new. Nothing here is built; build gate applies.

## One rule (same as every agent): propose -> review -> execute
Reading is free and automatic. Anything outward (an invite to a parent, an email, a Business Profile reply or post, a Sheet write that others rely on) is a draft the owner approves with one tap. No Google call may send, reply, post or invite on its own.

## What each Google piece does, per business

| Piece | Daycare (A Touch of Blessings) | Wholesale (Home Buyers) | Agency (ClientForge) | Orion (CEO) |
|---|---|---|---|---|
| **Calendar** | Tour booking: Solomon offers open slots, parent picks, event is created on the director's calendar and linked to the child's GHL contact; reminder text via GHL. Replaces "tours by text/phone". | Walkthrough / seller appointment slots; Marcus sees free-busy before proposing a call time | Discovery-call slots for prospects | Daily agenda pulled into the morning brief |
| **Gmail** (management@atouchofblessing.com + business inboxes) | Read-only triage of parent/enrollment email into Solomon's queue; reply **drafts** only | Title/attorney/contract email routed to Atlas context (read-only); DocuSign stays separate | Outreach drafts; prospect replies into the call sheet | Unread-that-matters count per business |
| **Sheets** | Waitlist / enrollment export for the director; start-date roster | Lead-list in/out (replaces manual CSV scrub), DNC list | Call Sheet moves from Mac-only LeadScraper to a shared Sheet the box can read | Weekly numbers rollup tab |
| **Business Profile** (3 locations: 921 N 18th, 2318 and 1923 Cecil B. Moore) | Review inbox: Solomon drafts replies in brand voice (owner taps to post); hours/holiday updates; weekly post draft | Only if a profile exists | Client profiles (read-only reporting) | Review score per location in brief |
| **Search Console** (atouchofblessing.com + other sites) | Queries, clicks, indexing errors, enroll-page performance feed Solomon's growth brief | Home-buyers site, same | Client sites, same | One line per site in brief |

Dropship (archived): nothing.

## How it plugs in (smallest design that fits the repo)
- One module `forge rei/google_io.py` in the existing `*_io.py` style (like `stripe_io.py`, `retell_io.py`): token refresh, small typed helpers `calendar_*`, `gmail_*`, `sheets_*`, `gbp_*`, `gsc_*`, each returning `{ok, data|error}`; failures fall back to "not connected" and never break a loop.
- Auth: **OAuth2 refresh token per Google account** (Calendar, Gmail, Business Profile need user consent). Search Console and Sheets can alternatively use a service account added as a user. Secrets live in git-ignored env files and `/etc/default/forge-reios` (names only in docs), covered by the existing `agent_coach` secret-guard. Never in the web root, never in chat.
- Least-privilege scopes: `calendar.events`, `gmail.readonly` + `gmail.compose` (drafts, **no send scope**), `spreadsheets`, `business.manage`, `webmasters.readonly`.
- Feature flags, all default OFF: `FORGE_GOOGLE_CALENDAR`, `_GMAIL`, `_SHEETS`, `_GBP`, `_GSC`. Flip off = instant rollback, no deploy.
- Claude cost: fetching is **zero** Claude. Claude is used only to draft (reply, email, post) — Sonnet 5.5 for parent/customer-facing, Haiku for classification/summaries. Cache results (GSC daily, GBP hourly, Calendar free-busy 5 min) so loops never poll Google into rate limits.
- Surfaces: Solomon / Dyson / Marcus context blocks (`agent_context`), Orion morning brief, Mission Control "approve" cards, Telegram taps.

## Phases (each independently shippable and reversible)
- **P0 — you, outside the code (I can't do these):** create one Google Cloud project; configure OAuth consent (Internal if the domain is Google Workspace); enable Calendar, Gmail, Sheets, Business Profile, Search Console APIs; add the box redirect/consent flow; **submit the Business Profile API access request** (Google reviews it; can take days to weeks); add the service account (if used) as a user in Search Console.
- **P1 — read-only, lowest risk:** Search Console + Calendar free-busy + Sheets read. Feeds Solomon's brief and Orion's brief. No outward effect.
- **P2 — drafts:** Gmail drafts and Business Profile review-reply drafts into the approval queue. Nothing sends.
- **P3 — writes behind a tap:** Calendar tour booking linked to GHL contact; Sheet writes; GBP posts.

## Verification plan (needed before any "ready to build")
Unit tests for `google_io` with a fake transport; per-flag smoke test against a **test Google account/calendar** first; E2E: parent texts "can we tour Thursday?" -> Solomon draft with real open slots -> tap -> event on calendar + GHL note + confirmation text; then read logs for errors and Claude spend before/after (cost tracker byAgent).

## Open questions for you
1. Is atouchofblessing.com on **Google Workspace** (so OAuth can be Internal and Gmail/Calendar are per-user), and which accounts: management@ and yahjair@? Any separate accounts for Home Buyers and ClientForge?
2. Who owns the three Google Business Profiles (which Google account is Owner/Manager)? Do Home Buyers / ClientForge have profiles?
3. Tours: Google Calendar or GHL's built-in calendar as the source of truth? (Plan assumes Google; GHL calendar is the alternative.)
4. Which tour days/hours and how long per slot (not in the brand kit's master info, so I won't guess)?
5. Gmail scope: drafts only (my recommendation) or also allow tap-to-send?
6. Which Sheets matter first: LeadScraper call sheet, waitlist, or lead lists?
7. Search Console: which site properties are verified and under which account?

## Prerequisites missing for the build gate
Approved spec (this plan), Google Cloud project + OAuth credentials (P0), BP API approval, a test calendar/account, env-var names created on the box, clean working tree (repo auto-syncs every few minutes, so build on a branch), rollback = flags off + revert commit, written test plan above.
