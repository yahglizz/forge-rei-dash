# Tour booking — build spec (DRAFT, needs approval) · 2026-10-16

Scope: Solomon's daycare lane only. Not Marcus, not n8n, not Meta (Meta ads are already live through Pipeboard: box /api/daycare/ads reports source=live, dataSource=live).

## Problem (verified in code)
Parents who ask for a tour get a text asking "morning or afternoon, what day works", and staff confirm by hand (`daycare-parent-reply.md` §2b; `daycare_replies.py` category `tour`). No calendar exists, so nothing stops double-booking, nothing reminds staff or the family, and the Lead Desk only reaches TOUR_BOOKED if someone adds a GHL tag by hand (`daycare_leads.py` STAGE_TAGS: `tour-booked` -> TOUR_BOOKED).

## Design (smallest thing that works end to end)
1. **Calendar:** one dedicated Google Calendar, "ATOB Tours" (owner = the account you pick). One event per tour; location is in the title and location field: `Tour — <child first name> — 921 N 18th` etc.
2. **Offer real slots:** in the Replies lane, when a lead is category `tour` and center + child age are known, `google_io.free_slots(location, next 7 days)` returns up to 3 open slots (from your tour policy, minus existing events). The draft text offers those, brand voice, per `daycare-parent-reply.md`.
3. **Parent picks -> tap:** the parent replies with a choice; Solomon drafts the confirmation; you tap approve (same one-tap gate as every outward text). On approve: create the Calendar event, add GHL tag `tour-booked`, add a GHL note with the slot, send the confirmation text.
4. **Reminder:** one text 24 h before (existing speed-to-lead send path, quiet hours respected). Optional, off by default.
5. **Pipeline:** the existing STAGE_TAGS mapping turns `tour-booked` into the TOUR_BOOKED stage with no extra code; after the slot passes, prompt you "Did the tour happen?" and a tap adds `tour-completed`.
6. **Never** auto-books or auto-texts: propose -> tap -> execute. Double-booking is blocked by re-checking free/busy at approval time.

## Pieces
- `forge rei/google_io.py` (new): OAuth refresh-token storage, `free_slots`, `create_tour_event`, `cancel_event`; no Gmail send function exists.
- `forge rei/google_oauth.py` or routes in connector: `GET /api/google/oauth/start` and `/api/google/oauth/callback` (redirect URIs already registered on the client). You click consent once.
- `daycare_replies.py`: slot offer + confirm-on-approve hook, behind `FORGE_GOOGLE_CALENDAR` (default 0).
- Config: `forge-daycare/config/tours.json` (days, hours, slot length, buffer, per-location) — **your tour policy goes here, nothing guessed**.
- Tests: fake-transport unit tests for slot math and no-double-book; E2E on a test calendar.

## Claude cost
Zero extra Claude calls for availability and booking. The two drafts (offer, confirm) are the same Sonnet 5.5 reply drafts Solomon already writes. No new loop.

## Test plan (before any real parent is touched)
1. Unit: slots respect hours/buffer/holidays; two simultaneous approvals cannot book one slot.
2. Test calendar + a test GHL contact (your own phone): text "can we tour Thursday?" -> offer with real slots -> reply -> approve -> event appears, tag `tour-booked`, confirmation arrives, Lead Desk shows TOUR_BOOKED.
3. Read box logs and cost tracker byAgent before/after; confirm no errors and no unexpected Claude calls.
4. Flip `FORGE_GOOGLE_CALENDAR=1` for real leads only after 2 passes.

## Rollback
`FORGE_GOOGLE_CALENDAR=0` (instant, no deploy) and `git revert` of the merge commit. Existing events stay on the calendar; nothing else is touched.

## Prerequisites (build gate)
Have: Google project, Calendar API, OAuth client + scopes, client JSON saved locally at ~/.forge-secrets/forge-rei/keys/google-oauth-client.json.
Missing, from you: (1) tour policy per center (days, hours, slot length, buffer, who leads); (2) which Google account owns "ATOB Tours" and who may see it; (3) OK to copy the client JSON to the box (root-only file, never in git); (4) one consent click after the build; (5) a test phone number and a test GHL contact; (6) build in a separate worktree branch, merged only on your go (the repo auto-syncs and the box auto-pulls, so a save on main is a deploy).
Also open: the daycare app's database on the box points at "QA Sandbox — test data only" (location id 9999..., test mode on). That does not block tours (GHL is separate) but the children/billing side is not on real data.
