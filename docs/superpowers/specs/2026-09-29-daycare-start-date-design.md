# Daycare start date → confirm → start-day app login (design)

2026-09-29 · owner-approved flow · lane of Solomon (`daycare_starts.py`)

## Goal
A new family's start date, agreed over text, lands on their GHL contact and the
dashboard automatically. The owner confirms it (prompted 2 days before). On the start
day the parent is automatically texted their app login + how to get the app.

## Flow
1. **Detect** (every 15 min, box only, zero Claude). Read recently-active daycare GHL
   threads for new-signup contacts (tags `website-lead` / `form-type-new-inquiry` /
   `family-contact-form`). A pure regex extractor finds the newest message that pairs a
   start word (start, starting, begin, first day…) with a date ("Oct 13", "10/13",
   "Monday", "the 13th", "tomorrow"), resolved against THAT message's date, future only,
   ≤120 days out. No thread date → the form's `Desired Start Date` field (if future).
   Unparseable/vague ("next month") → nothing (Unknown, never guessed).
2. **Propose.** State `proposed`. GHL contact gets custom field **Agreed Start Date**
   (`KDzh39WHQIlZIIUb7xLR`) + tag `start-date-proposed` (internal + reversible — rule 2
   auto-tag class). The parent's own `Desired Start Date` is never overwritten.
3. **Confirm (owner tap).** Dashboard "Start dates" card lists every proposal with its
   evidence quote; from 2 days before the date it is also an Owner Actions APPROVE row +
   one Telegram ping. Owner can edit the date, confirm, or mark "not a start date".
   Confirm = enroll/update the child in Supabase (`enrollment_date` = start date, guardian
   login created if missing; missing email / DOB → asked inline) with NO text, then state
   `confirmed`, GHL tag `start-date-confirmed`.
4. **Start day send (automatic, the confirm tap is the approval).** First tick on/after
   the start date inside 8am–9pm ET: mint a fresh PIN (`provision-user reset-pin`, never
   stored), text `start_day_text` (login + get-app guide link + 3 steps) through
   `daycare_replies.send_manual` (opt-out / DND / window gates, action-logged). State
   `sent`, GHL tag `app-login-sent`. Failure → retried next tick, 3 tries, then `failed`
   → Owner Actions FIX row.
5. A date change seen in the thread after confirm (before send) drops it back to
   `proposed` with the new date, so nothing goes out on a stale date.

## Not changed
Contact-Form **Enroll** still texts the login immediately (existing families). Nothing
auto-sends without the owner's confirm. No Claude calls (credit-independent).

## Surfaces
`GET /api/daycare/starts` · `POST /api/daycare/starts/{confirm,date,dismiss}` (session-gated);
desktop Daycare Dashboard card; mobile Families tab "Start dates"; Owner Actions rows;
heartbeat `daycare_starts` ("Solomon · Starts"), knob `FORGE_DAYCARE_STARTS=0`.

## Verification
`test_daycare_starts.py` (extractor cases, due/confirm-window logic, sweep/confirm/send
with fake GHL + fake session, text length/content, no-PIN-on-disk), connector contract
routes, independent reviewer + tester agents, live box check (routes 200, loop beating,
GHL field write on a real proposal).
