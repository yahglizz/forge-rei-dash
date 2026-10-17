# Client Booking ("Book a call") — design (LOCAL TEST ONLY, not deployed)

Ask (2026-10-17): a Calendly-style booking page for agency outreach prospects, built the same
way as the daycare tour booking, in the FORGE theme. Visual reference: the user's Calendly
screenshot (3 panes: host/event card · month grid · time column).
Note: the URL given (`calendly.com/contact/demo/thank-you`) is Calendly's marketing thank-you
page, not a booking widget — the screenshot is the real reference.

## What gets built
1. **`book.html`** — public, standalone page (no Babel, like `portal.html`), ClientForge brand.
   - Step 1 "Select a Date & Time" (matches the screenshot):
     - Left pane: ClientForge mark, host name, event title, duration, one-line pitch.
     - Middle: month grid (prev/next), available days filled blue, selected day solid.
       Time zone row under it (auto-detected via `Intl`, switchable).
     - Right: selected day heading + "times available" dot + scrolling slot buttons.
       Click a slot → it splits into [time | Next] (Calendly's confirm pattern).
   - Step 2 details: name*, business name*, email*, phone, website, "what do you want help
     with" (chips: Website · Ads · Booking/CRM · Other) + notes. Back link to step 1.
   - Step 3 confirmed: summary card, "Add to calendar" (.ics download, built client-side),
     Google Calendar link. No account, no payment.
   - FORGE theme: `#050B18` bg, `#101827` cards, `#4F7CFF` accent, `#22C55E` availability dot,
     Geist font, 18px radius. Mobile: panes stack (card → grid → times). Keyboard + reduced-motion.
2. **`agency_booking.py`** (stdlib) — reuses `google_io`'s pure slot math (`slots`, `_day_slots`)
   with its own policy file `forge-agency/config/booking.json` (event title, duration 30 min,
   Mon–Fri 10:00–17:00 ET, 15 min buffer, 4 h notice, 21 days ahead, calendar "ClientForge Calls").
   - Busy times = Google free/busy on that calendar **when Google is connected**, plus our own
     bookings in `marcus_state/agency_bookings.json`. Not connected (local test) = local only.
   - `book()` re-checks the slot under a lock (no double booking), writes the booking, and
     inserts the Google event (`sendUpdates=none`, same as tours) when connected.
3. **Routes** — on `PortalHandler` (the ONLY public-safe listener), additive:
   `GET /book` (page) · `POST /api/book/slots` · `POST /api/book/create`. Nothing else is
   reachable from it. Same routes mounted on the private dashboard for local testing.
4. **Dashboard: Agency → "Bookings" tab** (`agency_bookings.jsx`): upcoming calls list
   (who, when, business, need), copy booking link, per-prospect link `/book?ref=<callsheet id>`,
   cancel (frees the slot + deletes the event). Owner Actions gets a CALL row per booking.
5. **Outreach hook:** a booking with `ref` (or a phone match) sets that Call Sheet row to
   `demo_booked` (status already exists). Telegram ping to the agency chat: "📅 call booked".

## Rules it keeps
- Rule 2: the prospect books themselves; WE send nothing outward. No auto SMS/email confirms in
  v1 (the confirm page + .ics is the confirmation). A reminder text would be a later, gated add.
- Public-input hardening: per-IP rate limit (5 bookings/hr), honeypot field, field length caps,
  email/phone format check, max 1 future booking per email, slot must be on-policy and future.
- No secrets/CRM path on the public handler. Booking JSON never served raw.
- Brand: ClientForge only. No invented claims/testimonials on the page.

## Local test only
- Worktree `/Volumes/AgentDrive/client-booking-wt`, branch `client-booking` (off `tours-booking`
  e5db92c, which carries `google_io`). Run `FORGE_MARCUS=0 FORGE_PORT=7812
  FORGE_PORTAL_PORT=7813 python3 connector.py`. No push, no deploy, no Funnel change.
- Rollback = delete worktree + branch.

## Test plan
1. `python3 test_agency_booking.py`: slot math (DST, notice, buffer, closed dates), double-book
   refusal, rate limit, honeypot, validation, ref → callsheet `demo_booked`, cancel frees slot.
2. Regression: `test_google_io.py`, `test_daycare_tours.py`, `test_agency_lens.py`.
3. Browser: `localhost:7813/book` — desktop matches screenshot layout, mobile 375px stacks,
   book → confirm → .ics, slot vanishes after booking, Bookings tab shows it, cancel works.
4. Public surface check: every non-booking path on the portal port still 404s.
5. Read the connector log for errors after the run; fix before reporting done.

## Owner decisions (defaults used until told otherwise)
- Event: "Free 30-min growth call" with Yahjair · ClientForge. Edit in `booking.json`.
- Hours: Mon–Fri 10–5 ET. Edit in `booking.json`.
- Going public later = point the existing Funnel at the portal port (already set up);
  separate approval, not part of this build.

## Hardening as built (2026-10-17) + go-public follow-ups
- Per-IP 5 create attempts/hr (behind Funnel/Serve only the RIGHTMOST X-Forwarded-For entry is
  trusted), 3 bookings/hr per IPv4 /24, global 20/hr + 40/day live bookings (cancelled spam frees
  capacity), one Telegram "booking cap hit" alert per hour.
- `?ref=` is an unguessable per-lead token minted in the Bookings tab
  (`POST /api/agency/bookings/link`); raw Call Sheet ids are ignored. A phone match only
  suggests — the owner confirms (`POST /api/agency/bookings/confirm-lead`).
- **Before going public (separate approval):** add CAPTCHA (e.g. Turnstile) and/or email
  verification on create; confirm Funnel actually appends X-Forwarded-For (unverified locally);
  decide whether the booking link base is the Funnel host (`FORGE_BOOK_BASE`).
