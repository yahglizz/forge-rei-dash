# FORGE — Operator Guide (the app you run the businesses from)

Written 2026-09-22 for the wave-1 build. Audience: the owner. Your job in this app is four
verbs — **CALL · CLOSE · APPROVE · REVIEW**. The agents find, score, draft, prep and watch;
nothing leaves the building (texts, ads, invoices, pipeline moves) until you tap it.

## 1. Open it

| Where | How |
|---|---|
| Any device on your tailnet | `https://forge-reios.tail0a2dda.ts.net` |
| Mac shortcut | say "open dashboard" (runs `open-dashboard.sh`) |
| Phone, away from the dashboard | Telegram bot — alerts, tap-to-approve, `/solomon …`, `/task …` |

It runs 24/7 on the box. Your Mac can be closed.

## 2. Home = Mission Control

Top to bottom:

1. **TODAY — N ACTIONS** (Owner Actions). One list across all three businesses, sorted
   URGENT → REVENUE → CUSTOMER → NORMAL, oldest first. Each row is one of:
   - **CALL** — a hot seller (Scout `asap`), a call-ready thread (ACE), a screened interested
     seller (with "Atlas call card ready" when underwriting exists), a daycare family that
     needs a human (Lead Desk), a new daycare inquiry, "N prospects ready to dial" (agency).
   - **CALLBACK** — agency call-sheet callbacks / interested rows.
   - **APPROVE** — Marcus reply drafts, Scout warm/nurture tags, agency approvals, check-back drafts.
   - **REVIEW** — client edit requests, skill proposals.
   - **FIX** — something is broken: AI credits/auth down, a red agent loop, a data source failing.
   Tap a row to jump to the page that handles it. The list is read-only — it never sends anything.
   If it can't refresh you see a red "Refresh failed — list may be stale" row, never a fake "0 actions".
2. **Business cards** — Agency, Wholesale, Daycare (archived businesses don't show).
3. **Orion's CEO brief** — the daily "attack today" read (07:00). Shows its real error if it failed.
4. **Nav strip** — Agents · Automation Health · Costs · Archived.

Switch business with the header switcher (Agency / Wholesale / Daycare).

## 3. The daily loop

| When | Do |
|---|---|
| Morning | Read Orion's brief + the Telegram morning pulse. Work Owner Actions top-down: CALLs first. |
| Between shifts | Telegram pings for hot leads / reply approvals — tap ✅ to send, ✕ to drop. |
| Agency block | Call Center → work the call sheet (tap-to-dial, one-tap Answered / No answer / Call back). |
| Daycare | Daycare → Dashboard → **Lead Desk**: New leads, response time, "needs a human" list with Open-in-GHL. |
| Evening | Telegram end-of-day recap. Clear any APPROVE rows left. |

## 4. Agents — Agent Control Center

Mission Control → **Agents →**. Every agent in one table with its status:

| Status | Means |
|---|---|
| RUNNING | working right now |
| IDLE | healthy, waiting for its next run |
| WAITING FOR APPROVAL | it proposed something — go approve/reject |
| DEGRADED | running but something it depends on is failing (e.g. AI credits) |
| FAILED | its loop is red (stale or repeated errors) |
| DISABLED | switched off by a knob or its business is archived |

Per agent: last run, last success, next run, error count, what it depends on.
**Chat** with any agent and **give it a task** from its row. Engines without their own brain
(Follow-up, ACE, Autopilot, Daily brief) answer through their owner (Marcus / Orion).
A task is an assignment the agent sees in its next prompt — it is never an outward action.

| Agent | Business | Does |
|---|---|---|
| Scout | Wholesale | scores + buckets every seller reply, auto-tags hot leads, hands hot/warm to Marcus |
| Marcus | Wholesale | screens sellers, drafts replies (never a price by text), call-prep report |
| Atlas | Wholesale | offer anchors + MAO math + negotiation call card (internal only) |
| Follow-up | Wholesale | drafts no-response bumps + check-backs every 30 min |
| ACE | Wholesale | per-thread reply-vs-escalate, call-ready queue (default OFF) |
| Autopilot | Wholesale | auto-sends routine bumps behind 7 gates (default OFF, `/autopilot on`) |
| Dyson | Agency | plans client website edits — ships only on approval |
| Eco | Agency | ad strategy + performance reads — launches only on approval |
| Solomon | Daycare | the center's director: one ranked operating brief daily |
| Orion | All | daily CEO brief across businesses |
| Daily brief / recap | All (Agency · Wholesale · Daycare · Agents · Owner tasks) | morning + evening Telegram pulses (no AI cost) |
| Midas | Dropship | archived — reactivate from Archived to use |

Telegram shortcut: start a message with the agent's name — `solomon, what's the ratio situation`
— or `/task <what you need>`.

## 5. Health, costs, archive

- **Automation Health** (`/api/system/health`) — every loop green/amber/red, disk, and the
  **AI** row: if Anthropic credits or a key die, this goes red, Owner Actions shows a FIX row,
  and Telegram alerts once (and once again on recovery).
- **Costs** — Claude spend by agent, month to date + projection.
- **Archived** — Dropship and the Agency "Personal" lens are archived: hidden, data kept.
  **Reactivate** brings a business back everywhere in one tap. **"Open (archived)"** enters it
  without reactivating — but it is **not read-only**: every button on those pages still works
  (an "Archived — actions still work" banner shows). Treat it as live.

## 6. What never happens without you

Texting a seller or a parent · posting social · moving a pipeline stage (except HOT auto-tag/
auto-pipe, which is internal + reversible) · launching or changing ads / budgets · sending an
invoice · enrolling a family (Parent Logins → Enroll is your tap) · switching ACE or Autopilot on.
Kill switch for everything outward: clock out (Command Center or Telegram).

## 7. Things only you can fix

| Symptom | Fix |
|---|---|
| FIX: "Anthropic credit balance exhausted" | top up at console.anthropic.com — every agent's thinking is paused until then |
| Daycare ads show "token rejected — replace it" | put a valid Meta system-user token in `forge-daycare/config/daycare.env`, run `push.sh` |
| FIX: daycare GHL read failing | check the daycare GHL key / location in `daycare.env` |
| Anything else red | see `docs/FORGE_RUNBOOK.md` §5 |

More: `docs/FORGE_RUNBOOK.md` (operations), `docs/FORGE_AGENTS.md` (agent internals),
`docs/FORGE_INTEGRATIONS.md` (what's connected), `agents/README.md` (one card per agent).
