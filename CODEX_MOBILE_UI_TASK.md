# CODEX TASK — FORGE Mobile UI 2.0: one phone remote for the three businesses

> **Status: BRIEF ONLY. Do not start building until the operator says go.**
> Written 2026-09-22 by Claude (primary builder). Codex builds the UI; Claude reviews
> the diff and deploys. Codex does **not** push to `main` and does **not** deploy.

Read this whole file before touching anything. Then read, in this order:
`CLAUDE.md` (root) §2 RULES, §7 build mechanics, §9 Wave-1/Wave-2 surfaces →
`NORTH_STAR.md` → the 10 files in `forge rei/mobile/` → the desktop consumers listed in §6.

---

## 1. What FORGE Mobile is (the concept)

The operator works a full-time Amazon job. The businesses run on AI agents on a 24/7
DigitalOcean box. The operator's own job shrinks to four verbs: **CALL, CLOSE, APPROVE,
REVIEW.** The phone is where the operator does them, in short gaps: a break, a
parking lot, before a shift.

**FORGE Mobile is that phone remote.** It is not a separate product and not a native app:

- A PWA at `forge rei/mobile/`, served by the same `connector.py` that serves the desktop
  dashboard. URLs `/m`, `/m/`, `/mobile`, `/mobile/` all alias to `/mobile/index.html`
  (`connector.py` ~L4910).
- Reached over Tailscale only: `https://forge-reios.tail0a2dda.ts.net/m`. The box's ports
  are firewalled from the public internet. There is no login screen, so the trust boundary
  is Tailscale device auth.
- Same-origin `/api/*` only. **No keys, tokens or secrets in the app, ever.** The connector
  holds every secret. Mobile calls exactly the same endpoints as desktop.
- Installed to the iOS home screen and run standalone: fullscreen, no browser chrome.
- Live-synced with the desktop. `../live_sync.js` plus `GET /api/sync` means a write on
  either surface refreshes the other (`window.ForgeLiveSync`, already wired into `useApiM`).
- Same stack as desktop: React 18 UMD + in-browser Babel, **no build step**. React,
  ReactDOM and Babel are vendored on the box (`/assets/vendor/*`, SRI-pinned). No CDN.

### Where it is today (the gap this task closes)

Mobile was built on 2026-07-09 as a **wholesale** remote, and it still is one. The
business has changed since then. Three businesses are active: **Agency, Wholesale,
Daycare**. Dropship and the Agency "Personal" lens are archived (`/api/businesses`), and
the desktop's Mission Control now covers all three businesses. Mobile only got the
Owner Actions tab (Wave-2, `m_actions.jsx`). Everything else on it is wholesale-only:

| Mobile has | Mobile is missing |
|---|---|
| Wholesale approvals, hot leads, convos, pipeline, calc, contracts, buyers, deals | **Agency Call Center** (dial tally, call sheet, callbacks due), the thing the operator does after the Amazon shift |
| Owner Actions list (read-only) | **Mission tiles** per business (§15 of the master spec) |
| Agent chat for 5 hard-coded agents | **Agent registry** status (RUNNING / IDLE / WAITING / DEGRADED / FAILED), Solomon, Orion |
| Brief / recap config, brain, costs, health | **Daycare Lead Desk** (new leads, needs-a-human, response time, stage) |
| 7 tabs squeezed into 390px | A tab bar a thumb can hit |

**The job:** turn FORGE Mobile into the **three-business CEO remote**. Opening it answers
"what do I need to do right now, in which business?" in under 10 seconds, and every
CALL / APPROVE / REVIEW is one or two taps away.

---

## 2. Current inventory (read it before you redesign it)

`forge rei/mobile/` currently has 4,042 lines. Load order is set in `index.html`, and
**`m_app.jsx` must stay last**.

| File | Lines | Hook alias | Exports (window) | Endpoints |
|---|---|---|---|---|
| `m_api.jsx` | 73 | `MX` | `useApiM`, `apiPostM`, `fmtMoneyM`, `timeAgoM` | data layer: seq-guarded fetch + live-sync subscribe + optional `interval` |
| `m_shell.jsx` | 130 | `MSH` | `MIcons`, `MHeader`, `MTabBar`, `MCard`, `MBtn`, `MChip`, `MEmpty`, `MSpin`, `M_TABS` | — |
| `m_home.jsx` | 515 | `MH*` | `MHomePage` | `/api/dashboard`, `/api/marcus/proposals`, `/api/marcus/approve`, `/api/marcus/dismiss`, `/api/reply/draft`, `/api/scout/summary`, `/api/scout/leads`, `/api/scout/handoff`, `/api/ops/status`, `/api/ops/set` |
| `m_actions.jsx` | 143 | `MOA*` | `MActionsPage` | `/api/owner-actions` |
| `m_convos.jsx` | 288 | `MC*` | `MConvosPage`, `MCThread`, `MCAvatar` | `/api/conversations`, `/api/messages`, `/api/reply/draft`, `/api/reply/send` |
| `m_pipeline.jsx` | 485 | `MP*` | `MPipelinePage` | `/api/pipeline`, `/api/pipeline/move`, `/api/toolkit/pipeline/reminder{s,/set,/snooze,/dismiss,/send}` |
| `m_calc.jsx` | 495 | `MK*` | `MCalcPage` | `/api/toolkit/calc/{config,eval,arv,save}`, `/api/deals/save`, `/api/contacts`, `/api/send` |
| `m_agents.jsx` | 317 | `MA*` | `MAgentsPage` | `/api/agents/{list,chat,history}`, `/api/agency/agents/{chat,history}`, `/api/bus` |
| `m_more.jsx` | 1303 | `MM*` | `MMorePage` | brief/recap (`/api/brief*`, `/api/recap*`), contracts (`/api/toolkit/contracts/*`), buyers (`/api/buyers/*`), deals, brain (`/api/brain/*`), costs (`/api/cost/status`), health (`/api/system/health`) |
| `m_app.jsx` | 32 | `MAP` | — (root) | tab router, `localStorage.m_tab`, `window.mGoTab(t)` bridge |
| `mobile.css` | 183 | — | — | overrides on `../styles.css` tokens |

Current tabs: Home · Actions · Convos · Pipeline · Calc · Agents · More.
More menu: Daily brief · End-of-day recap · Send Contract · Buyers/Dispo · Deals ·
Contracts · Brain · Costs · System health.

**Every one of those screens and controls must still be reachable when you're done.**
You can move them. You can't delete them.

---

## 3. HARD RULES. Breaking any of these fails the task.

### 3.1 Collision rules (a violation = white screen, not an error)
- Every `.jsx` on the page shares one global scope after Babel. Each file uses **its own
  hook aliases** (`const { useState: useStateMXX } = React;`) and **uniquely prefixed
  top-level names**. Pick a new prefix per new file (e.g. `MT*` Today, `MG*` Agency,
  `MD*` Daycare, `MR*` Registry) and check it with
  `grep -n "^function MT\|^const MT" mobile/*.jsx` before you commit to it.
- Desktop files are **not** loaded on mobile, and mobile files are not loaded on desktop.
  Don't import or reference desktop globals (`window.OwnerActions…`, `useApi`, `apiPost`).
  Mirror their logic in mobile's own files.
- **No computed JSX tags.** `<MIcons[x] />` is banned. Resolve first:
  `const Ico = MIcons[x] || MIcons.More; <Ico/>`.
- Every page component is exported via `Object.assign(window, {...})`, registered in
  `M_PAGES` in `m_app.jsx`, and loaded by a `<script type="text/babel">` in `index.html`
  **before** `m_app.jsx`.

### 3.2 No new dependencies, no new endpoints
- No npm, no framework, no component library, no icon package, no CDN script, no new
  font. Icons are inline SVG in `MIcons` (`m_shell.jsx`); add more there if you need them.
  Fonts are Geist / Geist Mono, already loaded by `../styles.css`.
- **UI only. Do not touch `connector.py` or any `.py` file.** If a screen needs data no
  endpoint returns, build the screen with an honest "not available yet" state and list
  the missing route in your report. Claude adds backend routes.

### 3.3 The approval gate. This one is about real people.
- **Nothing outward happens without an explicit operator tap on that specific item.**
  Outward means texting a seller or a family, sending a contract, moving the GHL pipeline,
  launching or pausing an ad, or anything else that leaves the box. No auto-send. No
  "approve all". No send fired from a `useEffect`, a timer, or a swipe that can misfire.
  Destructive or outward buttons get a confirm step unless the existing screen already
  runs without one (keep existing behavior; don't loosen it).
- Use the **existing gated POSTs only** (`/api/marcus/approve`, `/api/reply/send`,
  `/api/toolkit/contracts/*`, …). Never call a GHL/Meta/Stripe/DocuSign URL directly.
- **No price by text.** Atlas's offer anchors and any MAO/ARV figure are **INTERNAL**.
  They may be shown on a call card labeled INTERNAL. They must never be pre-filled into,
  or suggested inside, any message composer (`CLAUDE.md` rule 9, code-enforced
  server-side too).
- ACE mode, autopilot, and clock-in/out (`/api/ops/set`) are operator switches. They stay
  where the operator can see them, and they never flip as a side effect of anything else.
- Daycare records are children's records. `/api/daycare/leads` is session-gated. If it
  returns 401/403, show "Daycare needs a session — open the desktop Daycare tab once". Do
  **not** add a PIN or login flow, and do **not** touch daycare auth.

### 3.4 Honest data (the creed, applied to UI)
- **A failed source is never a 0.** If an endpoint errors, drop that tile or card and
  show one warn line ("Agency calls unavailable — retry"). Don't render `0`, `—`
  pretending to be data, or a stale number without saying it's stale. Desktop does
  exactly this (`test_mission_tiles.py`). Mirror it.
- Mock or non-live ad data carries a visible **MOCK** / **TOKEN REJECTED** badge. Read
  `dataSource` (`live|mock|token_rejected`) and `dateRange` from the payload.
- Empty ("nothing to do") and error ("couldn't load") are **different designed states**.
- Respect archiving: read `/api/businesses` and **hide archived businesses**. Don't
  hard-code "three". If the operator reactivates Dropship tomorrow, it should appear.

### 3.5 Additive, never broken
- Don't remove a feature, control, number, badge, status or error surface. Move it,
  regroup it, restyle it.
- Don't change `useApiM` / `apiPostM` semantics. If you extend them, keep the existing
  call signatures working.
- Every commit leaves the app loadable. After each batch, run
  `node deploy/valjsx.js mobile/*.jsx`, reload, and check for no white screen and no new
  console error.

---

## 4. iOS standalone-PWA rules (learned the hard way; don't regress them)

- **Fixed app shell.** `html, body { overflow: hidden }`. `.m-app` is `height: 100dvh`.
  The header and tab bar are flex siblings (`flex: 0 0 auto`). **`.m-content` is the ONE
  scroller** (`flex: 1 1 auto; min-height: 0; overflow-y: auto`). Body scroll plus a
  sticky header plus a fixed tab bar freezes the page in iOS standalone. That bug has
  already shipped once (2026-07-10).
- Full-screen sheets and chats size with flex (`flex: 1 1 auto`), never with
  `calc(100dvh - Npx)`.
- Safe areas: `env(safe-area-inset-top/bottom)` on the header, the tab bar and every
  bottom sheet.
- Inputs use `font-size: 16px` minimum, or iOS zooms on focus.
- Tap targets are **44px minimum**, with at least 8px between adjacent destructive and
  confirm buttons.
- `-webkit-tap-highlight-color: transparent`. Use `:active` feedback instead of hover.
- `tel:` links for every phone number (agency call sheet, sellers). `sms:` is **not**
  allowed; texting goes through the gated app flow.
- Test at **390×844** (iPhone 14/15), **375×667** (SE) and **430×932** (Pro Max), in
  standalone display mode.

---

## 5. Design direction

Keep the identity and raise the execution. The theme is **Dark Luxury**. The tokens
live in `forge rei/styles.css` `:root`: `--bg #050B18`, `--card #101827`, `--card-2`,
`--border rgba(255,255,255,.06)`, `--text / --text-2 / --text-3 / --text-faint`,
`--radius 18 / -lg 22 / -sm 12`, `--font` Geist, `--mono` Geist Mono. Use the tokens.
Don't invent new hex values except for status colors that already exist in mobile
(`#EF4444` urgent/hot, `#F59E0B` warm/revenue-warn, `#22C55E` ok/revenue, `#64748B`
quiet).

**Workspace accents are navigation. Don't change them:** Wholesale `#4F7CFF`, Agency
`#8B5CF6`, Daycare `#2DD4BF`, Dropship `#F97316` (archived). A business's screens, tiles
and chips carry its accent, so the operator knows which business they're in at a glance.

What to actually go after:
- **One primary read per screen.** On Today, that's the owner-actions count and the
  top 3 actions. Everything else is secondary.
- **Spacing scale 4 / 8 / 12 / 16 / 24.** Cards share edges. There's one card radius.
- **Numbers** use `var(--mono)` + `font-variant-numeric: tabular-nums`, so polled figures
  don't jitter.
- **One component set.** Stat tile, list row, badge/pill, section header (`MHSection`
  already exists; promote it to `m_shell.jsx`), bottom sheet, empty state, error state,
  skeleton loader. Put them in `m_shell.jsx` + `mobile.css` and use them everywhere.
  Today each file rolls its own (`MMPill`, `MMErr`, `MHStat` …). Unify them, but only by
  adding shared atoms and switching call sites. Don't break the old names in the same
  batch.
- **Loading** uses skeleton rows, not a lone spinner on a blank screen. **Motion** stays
  sparing: no entrance animation on data that re-renders on a poll or live-sync.
- **Thumb zone.** Primary actions (Call, Approve) sit in the bottom half of the screen or
  in the row itself, never only in the header.
- **Dark only.** There's no light theme on mobile; don't add one.

If you have an image model: screenshot every current screen at 390×844 into
`docs/ui-audit/mobile/before/`, critique the screenshots, and generate target references.
**Implement the references by hand in this codebase's idiom. Never paste generated
markup.** Then screenshot again into `docs/ui-audit/mobile/after/`. Any "after" screen
that lost a number, a control or an error surface is a regression, and you revert it.

---

## 6. Target information architecture (recommended; justify any deviation in the report)

**Tab bar: 5 tabs, max.** Seven labels at 390px leaves about 55px each, which is too
tight for a thumb. Recommended layout:

| Tab | Accent | What it is |
|---|---|---|
| **Today** | neutral | The CEO home. It replaces Home + Actions as the landing tab. |
| **Wholesale** | `#4F7CFF` | Today's wholesale Home, with a segmented control: **Approvals · Hot · Convos · Pipeline · Calc** |
| **Agency** | `#8B5CF6` | New: the Call Center |
| **Daycare** | `#2DD4BF` | New: the Lead Desk + Solomon's brief |
| **More** | neutral | Everything else from today's More menu, plus Agents |

A **bot button in the header** (on every tab) opens the Agents sheet, so chat is one tap
from anywhere without spending a tab slot on it. Business tabs are **generated from
`/api/businesses`** (active only). With Dropship reactivated, the bar would grow to 6. If
that happens, move Daycare/Dropship into a business switcher rather than exceeding 6.

Keep `window.mGoTab(tab)` working, and add `window.mGoTab(tab, segment)` for deep links
(e.g. Owner Action → Wholesale › Convos › thread). Migrate `localStorage.m_tab`: stored
`home`, `actions`, `convos`, `pipeline` or `calc` values must map to the new tabs instead
of falling through to a blank screen.

### 6.1 Today
- **Owner Actions** (primary): count plus a sorted list, URGENT → REVENUE → CUSTOMER →
  NORMAL. Kind chips are CALL / CALLBACK / APPROVE / REVIEW / FIX, and each row carries
  its business accent. Source is `GET /api/owner-actions`, and the logic is ported from
  `m_actions.jsx` (which already handles the stale-row collapse and the "list may be
  stale" error state). Row tap opens the deep link: wholesale thread, agency call-sheet
  row, daycare lead. A CALL row with a phone number gets an inline **Call** (`tel:`)
  button.
- **Business cards**, one per active business, carrying the §15 tiles. Source is
  `GET /api/mission-control`. Mirror `forge rei/mission_control.jsx` for the payload shape
  and the per-tile failure behavior:
  - Agency: calls ready · callbacks · interested · clients · MRR
  - Wholesale: owner calls · contracts · deals (plus hot leads from `/api/scout/summary`)
  - Daycare: new leads · needs human · response time
  - A failed source drops its tiles and shows one warn line. Tapping a card jumps to that
    business tab.
- **Agents strip**: healthy / running / waiting approval / failed counts from
  `GET /api/agents/registry` (mirror `forge rei/agent_center.jsx`). Tap opens the
  Agents sheet.
- **Ops pill**: clock-in / clock-out (`/api/ops/status`, `/api/ops/set`). Keep its
  current confirm behavior.

### 6.2 Wholesale
Reuse the existing pages as segments; don't rewrite their logic. Home's approvals + hot
leads become the **Approvals** and **Hot** segments. Convos, Pipeline and Calc keep
their current components. Restyling them to the shared atoms is in scope. Changing their
data flow is not.

### 6.3 Agency — Call Center (new file, e.g. `m_agency.jsx`)
Mirror `forge rei/agency_callcenter.jsx`. This is the after-shift dialing screen and
should feel like a dialer, not a report.
- Tally header: today's dials vs goal, answered / no-answer, streak.
  `GET /api/agency/calls`. Big **Answered** / **No answer** tap buttons →
  `POST /api/agency/calls/log`. **Undo** → `/api/agency/calls/undo`. Goal edit →
  `/api/agency/calls/goal`. These are internal tallies, so no approval gate, but Undo
  must stay visible.
- Call sheet: `GET /api/agency/callsheet`, with a **📞 Due now** filter first, then
  search + status chips. Each row gets a `tel:` Call button, status quick-marks
  (`POST /api/agency/callsheet/status`) and an inline note (`/note`). Marking a row
  answered / no_answer bumps the tally server-side, so don't double-log it
  client-side. Callback rows show their `callbackAt`.
- Import (PDF/text) stays **desktop-only**. Show a one-line hint and don't build an
  upload flow.
- Link to Dyson / Eco chat through the Agents sheet.

### 6.4 Daycare — Lead Desk (new file, e.g. `m_daycare.jsx`)
Mirror the Lead Desk card in `forge rei/daycare.jsx` (~L221, "WP-E").
- `GET /api/daycare/leads` gives stages, response time and the needs-a-human list. The
  needs-a-human list comes first, and each row gets a `tel:` button.
- Stage mark: `POST /api/daycare/leads/stage` (local, never written to GHL). It needs an
  explicit tap plus a confirm sheet. Stage tiles show "—" when a stage is untracked;
  that's honest, not zero.
- Solomon's brief (read-only) is `GET /api/daycare/director/brief` (or `/overview`). It
  renders as readable sections, not as a raw markdown dump.
- The 401/403 session state follows §3.3.
- **No children's names or records beyond what the Lead Desk endpoint already returns.**
  No roster, attendance or billing screens on mobile in this task.

### 6.5 Agents sheet (rework `m_agents.jsx`)
- The roster comes from `GET /api/agents/registry` (status, last run, next run, errors,
  dependency health), **not** from the hard-coded `MA_AGENTS` list (audit finding F8).
  Keep `MA_AGENTS` only as a color/role fallback. Hide agents that belong to archived
  businesses.
- Chat: keep the Telegram-style thread UI and the shared history (`/api/agents/history`
  for REI and `/api/agency/agents/history` for Dyson/Eco. The thread is shared with the
  desktop and Telegram; **don't fork it**). Agents without a dedicated chat route go
  through `POST /api/hub/chat` (Solomon, Orion …). Mirror `agent_center.jsx` for the
  routing.
- The bus feed (`/api/bus`) stays.

### 6.6 More
Everything from today's `MM_MENU`, grouped under section headers:
**Pulses** (Daily brief, End-of-day recap) · **Wholesale tools** (Send Contract,
Contracts, Deals, Buyers/Dispo) · **System** (Brain, Costs, System health). Add
**Agents** as a row here too.

---

## 7. Local run, test, validate

```bash
cd "/Users/yg4st/forge rei dash/forge rei"

# UI-only local run. Loops OFF. MANDATORY on the Mac, or sellers get double-contacted.
FORGE_MARCUS=0 FORGE_PORT=7799 python3 connector.py
# open http://localhost:7799/m   (Chrome devtools device mode, 390x844, then SE + Pro Max)

# Validate every batch
node deploy/valjsx.js mobile/*.jsx          # must exit 0 (Babel transform + computed-tag scan)
node deploy/valjsx.js *.jsx                  # desktop untouched, but prove it

# Collision check for your new prefixes
grep -hoE "^(function|const) [A-Za-z_]+" mobile/*.jsx | sort | uniq -d   # must print nothing
```

Local data may be thin (the Mac has no live loops), and that's fine. It's a good test of
your empty and error states. If you need to view live data, use the SSH tunnel
(`~/"forge rei dash/open-dashboard.sh"`) **read-only**. **Never tap Approve, Send, Move,
Log, Stage or Clock on the live box to "test" it.** Every one of those is a real action
against real sellers, prospects and families.

Tests: this task is UI-only, so there's no new Python test. If you add non-trivial pure
logic (sorting, tab migration, deep-link parsing), put it in plain functions and add an
`assert`-style self-check block (a `?selftest=1` path that logs pass/fail to the console
is fine). Don't add a JS test framework.

---

## 8. Definition of done

1. Five-tab (or justified) IA shipped. Today is the landing tab, and Agency + Daycare
   screens are live against real endpoints.
2. Every pre-existing screen and control is still reachable (list each old path → new
   path in the report).
3. Old `localStorage.m_tab` values migrate. There's no blank landing screen.
4. Archived businesses are hidden, driven by `/api/businesses`.
5. Every screen has a designed loading, empty and error state. No failed source renders
   as 0.
6. No outward action fires without an explicit tap on that item, and every gate listed
   in §3.3 holds.
7. `valjsx` passes on `mobile/*.jsx` and `*.jsx`, and the duplicate-global check prints
   nothing.
8. No white screen and no console errors at 390×844, 375×667 and 430×932. Scrolling works
   on every tab and sheet (§4).
9. Before/after screenshots are saved in `docs/ui-audit/mobile/`.
10. The report is written (below).

## 9. Hand-back (Codex → Claude)

- **Don't push, merge or deploy.** Work on a branch named `codex/mobile-ui-2`. Commit in
  small batches, one screen or concern each, so Claude can review and revert per batch.
- Write `docs/ui-audit/MOBILE_UI_2_REPORT.md` covering: what changed per file, old → new
  navigation map, any missing backend routes you stubbed (§3.2), deviations from §6 with
  reasons, screenshots index, and known issues. Be terse and specific; no marketing.
- Claude reviews and runs the deploy gate (`git push origin main`, after which the box
  autopulls, validates and health-checks), then verifies on the phone over Tailscale.

## 10. Out of scope. Don't build these.

- Any backend / `.py` change, new route, or auth change.
- The desktop dashboard (`forge rei/*.jsx` outside `mobile/`).
- The daycare **parent/staff** app (`~/Desktop/the main daycare app`). It's a different
  product.
- A native iOS/Android wrapper, push notifications (Telegram already handles immediate
  alerts), offline mode or a service worker.
- Dropship screens (archived; they only appear if reactivated, via §3.4).
- Daycare roster, attendance, billing, or anything showing children's records beyond the
  Lead Desk payload.
- Call-sheet PDF import, contract template upload redesign, and ad launching. Those stay
  desktop.
