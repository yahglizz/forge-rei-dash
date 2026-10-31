# Solomon · Calendar watch: dashboard calendar + tour reminders

**Date:** 2026-10-31. **Status:** APPROVED WITH CHANGES by an independent Opus review 2026-10-31; changes folded into section 7 (binding). **Owner ask:** connect the Google Calendar
concept (tours + first days), add the calendar to the dashboard, and make Solomon watch it and set reminders for
upcoming tours. Source design: Brand Kit `docs/google-calendar/2026-10-30-tour-first-day-calendar-design.md`
(session "Google Calendar concept: tours + first days").

## 1. What already exists (verified 2026-10-31)

| Piece | State |
|---|---|
| Mirror lane `daycare_calendar.py` + `google_cal_io.py` | Live on the box in **QA mode**. Live read: `mode:qa`, `events:0`, `error:null`, ticking every 15 min. |
| Confirm / cancel tour, Add to calendar taps | Built (`daycare.jsx`, `connector.py` routes). |
| Tour email to the owner on booking / move | Live in QA mode. |
| Dashboard | A status card only (`DcsCalendarStatus`): event count, errors, held items. **No calendar view.** |
| Reminders | **None.** The only family reminder is the published GHL Tour Check-in SMS, which stays as is. |
| Solomon wiring | AI ok, keys true, Supabase / GHL / Stripe / Meta connected, Metricool not. `daycare_calendar` is **not** in Solomon's registry heartbeat list (`agents_hub.py` `hb`). |
| Tests | `test_daycare_calendar.py` 88 pass, `test_google_cal_io.py` 11 pass, `test_agents_docs.py` OK. |

## 2. Concept

The calendar lane stays the only writer. Three additions, all inside the existing lane and dashboard. No new thread,
no new Claude call, no new table, no deploy step in this build.

1. **Dashboard calendar.** Replace the status card with a Calendar panel: next 14 days grouped by day, each row with a
   center color dot, tour or first-day chip, time, child first name + initial (from this tick's memory, never disk),
   an Open link to the Google event, and a "reminder sent" mark. Empty state says nothing is booked. Status line
   (QA mode, last update, errors, held items) stays.
2. **Reminders, two layers, both to the owner only.**
   - *Google-native:* timed tour events get popup reminders 1 day and 1 hour before; first-day all-day events get a
     popup at 9:00 AM the day before. No attendees, so no family is ever emailed.
   - *Solomon watch:* each tick, for every tour really on the calendar (ledger hash matches this tick's plan, event in
     the future), send one Telegram note to the **daycare chat** at the nearest of 24 h / 2 h before. Text carries
     center, time, countdown and the event link, **no name** (same rule as the lane's other Telegram notes). Quiet
     hours 9 PM to 6 AM ET: held until the next tick after 6:00, skipped if the tour has started. Deduped per tour per
     stage in the ledger row (`reminded`). A moved tour resets its stages. QA mode prefixes `[QA]`.
3. **Solomon sees it.** Add `daycare_calendar` to Solomon's `hb` list (only when `FORGE_DAYCARE_CALENDAR != 0`, same
   pattern as the other lanes) so the registry row, status and Agent Control Center fold the lane in. Add the next 7
   days of tours and first days (counts + dates + center, no names) to Solomon's live chat context.

Not in scope: texting families (the GHL check-in text already does that and any new outward text needs its own
approval), staff texts / "Send to staff" (design section 17, waiting on the owner), real-mode switch
(`FORGE_DAYCARE_CAL_QA=0` stays the owner's call), the 1923 tour option.

## 3. Build steps (TDD, one failing test first each)

| # | Change | Files |
|---|---|---|
| 1 | `_reminders()` Google popups added to `_tour_event` / `_first_day_event` bodies. Payload hash changes, so each existing event patches once (QA calendar holds 0 today). | `daycare_calendar.py`, `test_daycare_calendar.py` |
| 2 | `_remind()` Telegram stage logic: stage pick, quiet hours, dedupe, reset on move, QA prefix, kill switch `FORGE_DAYCARE_CAL_REMIND=0`, never a name. Called from `_tick` after `_tour_emails`. | same |
| 3 | `view()` gains `upcoming` (next 14 days, from ledger rows: `kind`, `when`, `shell.start`, `center`, `link`, `reminded`) plus first name from an in-memory map filled by the tick. Still no network on the request path. | same |
| 4 | Dashboard `DcsCalendar` panel replacing `DcsCalendarStatus`, same slot. | `daycare.jsx` |
| 5 | Solomon wiring: `hb` entry, live-context block. | `agents_hub.py` (+ context file found by grep) |
| 6 | Update `test_agent_registry.py:239` (asserts Solomon's exact `hb` list). No new wiring test file. | `test_agent_registry.py` |
| 7 | Docs: Solomon card and CLAUDE.md note the Reminders and Calendar panel. Audit docs are already committed (`1ec0bd8`). | `agents/daycare/solomon.md`, `CLAUDE.md` |

## 4. Verification

- Unit: `test_daycare_calendar.py`, `test_google_cal_io.py`, `test_agent_registry.py`, `test_agent_placement.py`,
  `test_agents_docs.py`, new `test_solomon_wiring.py`. Then the full suite; known unrelated failure
  `test_optout_hardening.py` (needs a wholesale env).
- UI: local dash copy with loops off, ledger seeded with ZZ QA rows, screenshot the panel (light, dark, phone width).
- Privacy greps: no phone / email / last name in any event or Telegram text; no name on disk.
- **Not done in this build:** box deploy, live Telegram send, real-mode switch. Each needs the owner's separate yes
  (deploy via `deploy/push.sh`).

## 5. Risks

| Risk | Handling |
|---|---|
| Reminder reaches the wrong chat | `send_biz` falls back to the HQ chat when daycare is unbound (`telegram_io.py:142-144`). `_remind` must skip when `telegram_io._biz_chats().get("daycare")` is empty. Whether daycare is bound on the box is Unknown. |
| Duplicate reminders after restart | Dedupe lives in the ledger on disk, not memory. |
| Payload hash change | Tours re-put once, then settle (`test_repeat_ticks_write_nothing`). First days skip the hash check when `source` is unchanged, so add `|r1` to `source` or accept new/changed first days only. Calendar holds 0 events today. |
| Name on disk | First name held in memory only; lost on restart, refilled by the next tick (up to 15 min). |
| `hb` change breaks registry tests | Run both registry tests before and after; the lane is excluded when its kill switch is on. |
| Solomon's own health problems | Out of scope, tracked separately: errorCount 2904 with unknown cause, last brief success 2026-08-01, Metricool not connected. |

## 6. Rollback

`git revert` the build commits. Runtime kill switches: `FORGE_DAYCARE_CAL_REMIND=0` stops Telegram reminders,
`FORGE_DAYCARE_CALENDAR=0` stops the whole lane. No schema, no migration.

## 7. Approver changes (binding, from the independent review)

Build order: 1, 2, 3, 5, 4, 7. Audit docs already committed, so the tree is clean for step 7.

1. **Chat guard.** `_remind` sends only when the daycare chat is bound (`telegram_io._biz_chats().get("daycare")`). Unbound = skip, no HQ fallback. Test it.
2. **Mark sent only on success.** `telegram_io.send` returns `{error}` and never raises, and `_notify` swallows it. `_remind` calls `send_biz` itself and writes `reminded` only when the result is ok (a `skipped:dedupe` counts as ok). `dedupe_key=f"cal-remind:{key}:{stage}:{start}"`.
3. **All-day tours.** `_remind` skips any tour whose `start` has no `dateTime` ("Tour: time not set"). All-day tours get no Google popup either, and the panel shows them as "time not set".
4. **Google body.** `reminders` is `{"useDefault": False, "overrides": [...]}`; overrides without `useDefault:false` return 400. First day = popup 900 minutes (9 AM the day before, in the calendar's own zone). Read the zone of both calendars (America/New_York expected) before relying on it; report if different.
5. **First days.** Add `|r1` to `source` so existing first days patch once and gain the popup.
6. **Registry.** Update `test_agent_registry.py:239`. A reminder or Telegram failure must never enter `_tick`'s `errors` (three bad ticks turn Solomon's row FAILED, `agents_hub.py:743-747`).
7. **Context.** Solomon's block goes in `agents_hub._delegate_context("solomon")` (line ~466; also feeds `telegram_agent.py:561`). Cut at 2500 chars, ~1800 used. Calendar block under 300 chars, before `adGenerator`, no names.
8. **Panel dates.** `DcxDate("2026-11-09")` shows Nov 8 in ET. Format date-only strings from their parts; format times with `timeZone:"America/New_York"`. Validate JSX with `forge rei/deploy/valjsx.js`. Center dot colors need hex that works in light and dark. 1923 rows show `[1923 AMT]` only.
9. **`view().upcoming`** uses only rows with `hash`, not `scrubbed`, `cal` equal to the current mode's calendar, and `when >= today`. Empty state is shown in live mode too (the old card returned null).

Owner decisions taken as defaults, all reversible, to be shown in the report: keep both reminder layers (popups + Telegram); skip when the daycare chat is unbound; panel shows all 3 centers; QA tours may fire popups on the owner's phone.
