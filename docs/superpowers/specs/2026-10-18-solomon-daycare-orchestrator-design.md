# Solomon — the Daycare Orchestrator (design v1, 2026-10-18)

Status: DRAFT, awaiting owner go. Nothing built. Builds on chat actions
(`2026-10-18-agent-chat-actions-design.md`, shipped 9a71ecb: AUTO tier + tap cards + action log).

## Goal (owner, 2026-10-18)
Solomon keeps the whole daycare side on task and updated: Gmail, GoHighLevel, ads, billing, social, roster —
orchestrating the daycare dashboard, doing the small things himself and putting the important ones in front
of the owner for a tap. He is the daycare's COO, not only its growth director.

## Scope change (owner-approved 2026-10-18)
2026-09-30 decision made Solomon growth-only ("paperwork/compliance/billing/staff admin are not his lane").
This reverses it. Required edits (the creed is HUMAN-OWNED, so the owner approves the wording):
- `forge-solomon/skills/daycare-evidence-discipline.md` §5: "growth is the job, paperwork is not" → growth
  stays the top priority, but billing, inbox, ops and system health are now watched; evidence discipline
  (never invent a number, a date, a seat, a family quote; Unknown over guess) is unchanged.
- `CLAUDE.md` §5/§10 Solomon rows + `agents/daycare/solomon.md`.
- His top skills get one new file `solomon-orchestrator-craft` (the watch round, triage order, what is a
  task vs a card vs a note). Not reachable by `learn()` (same isolation as the other top skills).

## Shape: one Command Board + a Watch per domain
**Command Board** (`marcus_state/daycare_board.json`, a card on the Daycare Dashboard + Telegram daycare chat):
a ranked list of OPEN items, each `{id, domain, title, why, evidence(source+window), owner: solomon|owner,
state: open|doing|waiting-tap|done|snoozed, due, createdAt, lastSeen}`. Deduped by `domain+key` so a
persistent problem is ONE item that ages, not a new item every round. Reuses hub tasks for assignments
(`agents_hub.send_task`) and Owner Actions for the owner's rows.

**A Watch** = read a source → detect exceptions → for each: do the AUTO fix, queue a TAP card, or open a
board item. One function per domain, zero Claude to *detect* where a rule can (counts, dates, statuses);
Claude only to read/classify text (email) and to write the one-line "why".

| Domain | Reads | Exceptions it flags | AUTO (does itself) | TAP (card) |
|---|---|---|---|---|
| Inbox (Gmail) | both mailboxes, read-only | parent email unanswered >4 h, tour/enrollment request, invoice/billing question, vendor/state/licensing notice, security alerts | label-in-board (no Gmail write), open board item, link to GHL contact | send/reply to any email, archive, forward |
| Enrollment / GHL | Lead Desk, Starts, Replies, tags | leads waiting, funnel leak, enrolled-tag drift (audit shipped), held auto-enrolls | tags (enrolled only), stage marks, Replies re-run | texts to parents, enroll/login, pipeline moves |
| Billing | Supabase invoices, Stripe | overdue/due-soon, failed payment, unsynced Stripe payment, missing invoice for an enrolled child | open board item, sync-payment read | invoice create/send, payment-link text, refund/void |
| Ads | Pipeboard feed, autopilot state | CPL over target, delivering-nothing, budget at ceiling, pending autopilot proposals | read + annotate | every Meta write (existing ads-auto cards) |
| Social | Metricool | nothing scheduled for N days, failed post | draft post text | schedule/publish |
| Roster / ops | Supabase roster, ratios, attendance | room over ratio, child w/o guardian phone/login, withdrawn-but-active | note + board item | login create/reset, child edits |
| Systems | `/api/system/health`, AI health, heartbeats | red loop, AI credits, Stripe/GHL/Meta auth dead | board item + one HQ Telegram note | — |

Anything money-moving, parent-contacting, email-sending or spend stays TAP regardless of phase.

## Gmail (new integration — nothing exists on the box today)
- **Scope = DAYCARE MAIL ONLY (owner, 2026-10-18).** Everything else in both mailboxes (Verizon, Vercel, Square
  personal, newsletters, Meta/Google marketing) is ignored entirely — not read beyond the header needed to filter,
  not labeled, not on the board. A message is daycare when ANY of: from/to the daycare form sender
  (`noreply@atouchofblessing.com` enrollment/intake forms), from a known guardian/staff email or phone match in the
  daycare roster or GHL daycare contacts, subject/body mentions the daycare's centers or billing for a child
  (tuition, invoice, Stripe receipt tied to a daycare family), or a Supabase/Stripe/Meta-daycare system notice.
  Square "Payment sent" to individuals stays OUT unless it matches a daycare family.
- Mailboxes confirmed: `management@atouchofblessing.com` and `yahjair@atouchofblessing.com` (both received by the
  connected Gmail account).
- `gmail_io.py` (stdlib/urllib, no new deps): OAuth refresh-token → access token → `users.messages.list/get`,
  **`gmail.readonly` only in Phase 1**. Mailboxes: `management@atouchofblessing.com` and
  `yahjair@atouchofblessing.com` *(owner wrote `atouchoiblessing` — assumed typo; confirm)*.
- Why not the Claude Gmail MCP / `gws`: the MCP lives inside Claude sessions, `gws` is installed on this Mac
  (v0.22.5) but not signed in, and neither runs on the box 24/7. They stay useful as DEV tools: `gws` (once
  logged in) mints the refresh tokens, and the MCP can sample real mail shapes to tune the classifier.
- **Owner steps (cannot be automated):** create a Google Cloud OAuth client (Workspace-internal app,
  Desktop type, `gmail.readonly` scope) → run the one-time consent for each mailbox → refresh tokens go into
  `forge-daycare/config/daycare.env` (`GMAIL_CLIENT_ID/SECRET`, `GMAIL_REFRESH_MANAGEMENT`,
  `GMAIL_REFRESH_YAHJAIR`; secret, shipped by `push.sh`, never git, must 404). I will walk through it.
- Privacy: parent email contains children's data. The box keeps message id, thread id, sender, subject, a
  ≤200-char snippet and Solomon's classification — never full bodies at rest, never in the vault or on the
  agent bus; body fetched on demand for ONE message when the owner asks, redacted in logs.
- Classifier: rules first (sender domain, known parents via GHL/roster phone+email match, keywords), Claude
  (SMART, low) only for ambiguous ones. Bucket → `parent | lead | billing | vendor | licensing | system | noise`.
- Phase-later (own spec, tap-gated): draft replies saved as Gmail DRAFTS (never sent), then send-on-tap.

## The wake-up loop (Phase 3 — the "worker")
Same tools/tiers as chat, started by a box-only timer instead of a message: thread `solomon_orchestrator`
(`FORGE_MARCUS` box only), default every 2 h in business hours + one evening round, `FORGE_SOLOMON_ORCH=0`
default OFF; the operator flips it. Each round: run the Watches → update the board → AUTO fixes → TAP cards to
the daycare Telegram chat → one short "what I did / what needs you" digest (replaces the cut daily brief; zero
Claude to assemble). Guards: forge_ops clock-out, per-turn 20 / per-day 200 write caps (shipped), **per-agent
daily $ ceiling via cost_tracker** (`FORGE_ORCH_MAX_USD`, default $3, over = skip + one HQ note), one round at
a time, heartbeat `solomon_orchestrator` (retire when off), AI circuit breaker respected, round turns ≤8.

## Phases and exit criteria
**P0 — close the readiness gaps (prereq, ~1 day).** (a) real ✅ tap of a card and of a batch card on the
box, (b) live test of each AUTO path not yet exercised (Scout apply/run, Replies re-run, drafts,
`pipeboard_read`), (c) prompt-injection red-team: parent/seller text and email subjects/bodies that say
"tag X / text Y / ignore your rules" must never cause a write (test file + live probe), (d) per-agent $ ceiling
in `cost_tracker`, (e) daily "what agents did" digest from `action_log`, with an inverse hint for each AUTO
write (tag add ↔ remove) so undo is one tap.
**P1 — eyes, read-only (~2–3 days).** `gmail_io.py` + the Watches (detect only) + Command Board + dashboard
card + Telegram digest on demand (`/board`). No timer yet: Solomon refreshes the board when asked or on a
manual "Run round" button. Exit: a week of boards the owner agrees are accurate (no invented numbers, no
wrong "overdue").
**P2 — safe self-fixes.** AUTO actions from the table turn on inside a manual round. Exit: action log clean,
zero undo requests.
**P3 — the timer.** Turn on `FORGE_SOLOMON_ORCH=1` for Solomon alone, a week of supervised rounds.
**P4 — earned autonomy.** Move individual actions off the tap list one at a time, only with owner say-so
and the log to justify it. Marcus / Dyson get their own orchestrator specs after Solomon proves out.

## Safety (unchanged rules + new ones)
Rule 2 holds: propose → tap for anything outward. Daycare center rule: 1923 A Mother's Touch is its own
entity (every board item carries a center). DENY list holds. The evidence creed outranks everything: a board
item without a source + window is not shown. New CLAUDE.md §2 exception "Solomon orchestrator (operator
opt-in, default OFF)" written at P3. Kill: knob 0, clock-out, per-item snooze.

## Tests (per phase)
P0 `test_chat_injection.py`, `test_cost_ceiling.py`, extend `test_chat_actions.py`. P1 `test_gmail_io.py`
(fake Google endpoints, token refresh, never stores bodies, secrets redacted), `test_daycare_board.py` (dedupe,
aging, snooze, center on every item), `test_daycare_watches.py` (each rule on fixtures; failed source drops its
items, never a fake 0). P3 `test_solomon_orchestrator.py` (caps, ceiling, clock-out, no overlap, heartbeat retire).

## Cost (estimate, not measured)
Detection is mostly rules (≈$0). Email classification + digest ≈ $0.02–0.10/round; 6 rounds/day ≈ $0.2–0.6/day
for Solomon, hard-capped at $3/day.

## Open items for the owner
1. Confirm the second mailbox domain spelling (`atouchofblessing.com`?).
2. "Speaker" — not identified yet (Retell voice? Metricool? something else?). Tell me and it becomes a Watch.
3. Google Cloud OAuth client + consent for both mailboxes (Phase 1 prerequisite, I'll guide).
4. Approve the creed wording change before P1 ships.
