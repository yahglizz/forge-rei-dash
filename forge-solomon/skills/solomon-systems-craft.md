---
agent: solomon
skill: systems-craft
role: The lead machine — what is wired, what is verified, what leaks
seed: true
priority: top
updated: 2026-09-30 — chain refreshed (speed-to-lead SMS + Lead/Reply/Starts desks); legal section scoped to marketing guardrails
---

# Systems Craft — the lead machine, and how much of it you may trust

`daycare-context.md` holds the business. This holds the **machine that turns a stranger
into an enrolled family**: ad → pixel → website → CRM → first text → a human → tour →
start. Every enrollment claim rests on this chain working. **A form existing is not a lead
captured.** Verified = someone submitted a real record end to end and watched it land.

## The chain, link by link

| # | Link | State | Source |
|---|---|---|---|
| 1 | Meta ad → click | **Not live** unless the live Meta data this run shows an active campaign | Meta connection |
| 2 | Meta Pixel `1361417309440327` fires | Verified Aug 16 (PageView, ViewContent, Lead, Contact → HTTP 200) | manual test |
| 3 | Website enrollment form → `/success` | Verified Aug 14 | manual test |
| 4 | → GHL contact (location `4JIvZEmkY5EjTsDRnjBN`, tags applied) | Verified Aug 14 | manual test |
| 5 | → Opportunity in the Enrollment pipeline | Verified Aug 14 | manual test |
| 6 | → Email to management@ / yahjair@ | Verified Aug 14 | manual test |
| 7 | → **Speed to Lead SMS** to the parent (~3 min; overnight forms queue to 8am) | Built in GHL (per `daycare-parent-reply.md`, 2026-09-23) — trust the **Lead Desk's measured first-response time**, not this row | `leadDesk.kpis.medianResponseSec` |
| 8 | → A human replies / calls | **The live leak to watch.** `leadDesk.needsHuman` + `kpis.medianHumanResponseSec`; `replyDesk.pending` drafts waiting on the owner | Lead + Reply Desks |
| 9 | → Tour booked / attended | Manual — tracked only via GHL tags or local stage marks (`leadDesk.kpis.pipeline`; null = untracked, never 0) | Lead Desk stages |
| 10 | → Start day + app login | Solomon · Starts: start date → owner Confirm → login text on day one | `startsDesk` |

**Capture (3–6) is solid. The money leaks at 8–9: how fast a human follows up and whether
tours get booked and attended.** Triage there first.

The New Inquiry **nurture sequence** (4 texts) is **OFF until A2P approves**. Never assume
unreplied leads are being followed up automatically.

## The CRM, precisely

**Contact identity is the CHILD's name.** `{{contact.first_name}}` = the child;
`{{contact.parent_name}}` = the parent. Any template greeting `first_name` addresses a
mother by her toddler's name — check every template you propose.

| Tag | Meaning |
|---|---|
| `form-type-new-inquiry` + `website-lead` | Brand-new lead — growth |
| `form-type-existing-family` | Current family updating info — not a lead |
| `group-infants` / `group-toddlers` / `group-prek` / `group-schoolage` | Age band → match to open seats |

Pipelines: **Enrollment** (6 stages) is the real one; "Marketing Pipeline" is a leftover.

## Known defects that distort growth numbers — never brief around them silently

1. **GHL timezone is `America/Cancun`** — any scheduled send or reminder fires off
   Philadelphia time. Flag it before proposing a scheduled send.
2. **GHL location record is an unbranded template** (wrong name/website/email/ZIP) — merge
   fields can leak the wrong brand into automated messages.
3. **Website deploy is manual** (`vercel --prod`) — never assume a site change is live.
4. **Form spam** — bot submissions with foreign numbers reach the CRM. Discount obvious
   fakes from any lead count you report.
5. **A GHL read returning "no contacts"** may be a permissions artifact — say so, never
   report zero.

## Advertising facts

- Ad account `1175564690150627`, Page `939494549239823`. History: $46.30 spent, 4 Instant
  Form leads at $11.58 (March 2026) — those leads expired uncontacted.
- **Never benchmark website-conversion ads against $11.58.** Project $18–28 CPL; judge on
  **cost per tour booked**.
- Optimize on `Lead` (fires on `/success`). Page has ~1 follower, no posts, Instagram not
  linked — thin social proof suppresses ads; flag it before proposing spend.
- **Learning-phase math:** ~50 conversions per ad set per week to stabilize. At $25/day
  split three ways, no ad set exits learning — consolidate or fund it.

## Marketing guardrails (legal — these bind every growth proposal)

- **SMS consent stays optional** — never a condition of enrollment (TCPA: $500–$1,500 per
  message). Never propose making it required.
- `/privacy-policy` and `/sms-terms` must stay live (A2P depends on them).
- **No child's photo in marketing** without a signed release; ad imagery shows no children.
- **Entity wall:** A Mother's Touch (1923) is a separate legal entity — no shared campaign,
  offer, or legal page across entities without the owner confirming with counsel.

## How you use this file

- Before claiming a lead was captured or answered, name the link and its source.
- Report speed-to-lead from the Lead Desk's measured numbers, never from this table.
- When a defect is fixed, say so in the brief — a human strikes it here (`learn()` never
  rewrites this file).
