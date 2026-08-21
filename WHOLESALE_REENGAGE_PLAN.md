# WHOLESALE RE-ENGAGE — MASTER PLAN

**Owner:** Yahjair · **Head agent:** main Claude session (this file is its contract)
**Started:** 2026-08-21 · **Status:** IN PROGRESS
**Goal:** Recover every still-alive wholesale lead in the GHL wholesale location, produce
one clean DNC-scrubbed CSV, and re-engage them via a GHL bulk SMS campaign.

> This file is the single source of truth. Every subagent reads it BEFORE working and
> writes its result into §7 (Agent Log) when done. The head agent verifies each return
> against that agent's acceptance criteria before unblocking the next stage.

---

## 1. Operator decisions (LOCKED — do not re-litigate)

| # | Decision | Answer |
|---|----------|--------|
| 1 | Send channel | **GHL bulk campaign.** CSV → GHL smart-list → SMS workflow, throttled by GHL. Operator approves copy ONCE per segment. Replies fall back into the normal Scout→Marcus one-tap loop. |
| 2 | Scope | **All 7,363 contacts, every state, INCLUDING blank-state.** The Ohio-only run dropped ~1,836 contacts; blank-state contacts were silently discarded. Both are bugs. |
| 3 | `soft_no` ("not right now", "few months", "later") | **RE-ENGAGE.** Own segment, timing-aware copy. It is NOT a refusal. Currently miscoded as `dead_end` — must be split out. |
| 4 | The 194 Ohio drafts from 2026-08-02 | **Redraft fresh.** Threads are 3 weeks staler; Marcus's voice/playbook skills have improved since. |

## 2. Ground truth (verified 2026-08-21, live GHL reads)

- Wholesale GHL location `8GuqpADet7ivY7wXWTpV` — **7,363 contacts total**.
- Prior Ohio audit (2026-08-02) covered **5,527**:
  `never_replied` 4,802 · `dead_end` 477 · `active_pending_us` 169 ·
  `replied_then_cold` 78 · `no_outbound_yet` 1.
- **194 Ohio re-engage drafts were written on 2026-08-02 and NEVER SENT.** Box
  `send_ledger.json` has 2 entries, last modified Jul 12. This is why the pipeline is dry.
  The leads were never actually contacted.

## 3. Segment definitions (the ONLY buckets that matter)

**KEEP — these are the re-engage list:**

| Segment | Meaning | Copy angle |
|---------|---------|-----------|
| `active_pending_us` | Seller replied, ball is in OUR court, we dropped it | Apologize for the gap, pick the thread back up |
| `replied_then_cold` | Seller replied, conversation died | Reference what they actually said, revive |
| `soft_no_revisit` | Said "not now / few months / later" | Timing-aware — "you mentioned X, is now better?" |
| `never_replied` | We texted, they never responded | Fresh angle, NOT "just following up" |
| `no_outbound_yet` | In CRM, never contacted | Treat as net-new outreach |

**EXCLUDE — never text again:**

| Reason | Why |
|--------|-----|
| `dnc` | Compliance. Permanent. Never expires. |
| `opt_out` | Compliance. Permanent. Never expires. |
| `ghl_dnd` | GHL contact-level DND flag / DNC tag. **NEW — see §4.** |
| `wrong_number` | Not the owner |
| `sold` | Property is gone |
| `hard_no` | Explicitly refused to sell |

## 4. MANDATORY COMPLIANCE GATE (blocks everything downstream)

`leads_audit.py` today derives DNC **only from inbound message text**. It never reads:

- the GHL contact-level `dnd` boolean,
- `dndSettings` (per-channel: SMS/Call/Email),
- contact tags carrying a DNC/opt-out marker.

Carrier-level STOP handling does not always leave an inbound message on the thread. A
genuinely opted-out contact can therefore classify as `never_replied` and land in a
5,000-person blast. That is a TCPA violation and a number-shutdown risk.

**Gate:** no CSV ships and no campaign is proposed until every row has been checked
against contact-level `dnd` / `dndSettings` / DNC tags, and any hit is excluded with
`exclude_reason = ghl_dnd`. Exclusions are logged, counted, and reported — never silently
dropped. When in doubt about a contact, **exclude it**. A missed lead costs one deal; a
missed opt-out costs the number.

## 5. Hard rules for every agent on this job

1. **READ-ONLY on GHL.** GET requests only. No POST, no PUT, no DELETE, no tag writes,
   no pipeline moves, no sends. If a task seems to need a write, STOP and report to the
   head agent instead.
2. **Never invent a lead, a quote, a status, or a number.** Every classification traces to
   actual thread text. Unknown is a valid answer; a guess is not. (wholesale creed)
3. **Never put a price in any draft.** Ever. The draft's only job is a call.
4. **Secrets never leave `../marcus-wholesale-agent/config/ghl.env`.** Never printed,
   never written into a CSV, never pasted into a report.
5. **Exclusion beats inclusion on any tie.** See §4.
6. Report findings as facts with counts. No hedging, no padding.

## 6. Stages & agent assignments

| Stage | Agent | Depends on | Deliverable |
|-------|-------|-----------|-------------|
| A | **Sweep Engineer** | — | `full_leads_audit.py`: all 7,363, every state incl. blank, `soft_no_revisit` split out, §4 DND gate wired in. Verified on a 50-contact slice. |
| B | **Thread Auditor** | — (runs on existing Ohio CSV) | Regex audit of the classifier against real thread text. Find false `dead_end` (leads we wrongly killed) and false-live (opt-outs we missed). Ranked, with quoted evidence. |
| C | **Sweep run** | A + B | Full 7,363 sweep executed → `all_leads_audit.csv` + per-segment CSVs, deduped by address/phone. |
| D | **Copy Writer** | C | Re-engage SMS copy per segment, drafted through the real Marcus voice engine. Draft-only. |
| E | **Campaign Packager** | C + D | GHL-import-ready CSV (correct headers) + per-segment send plan for one-time operator approval. |

### Acceptance criteria

- **A:** runs read-only; on a 50-contact slice produces correct counts; blank-state
  contacts appear in output; `soft_no_revisit` is its own status; every row carries
  `dnd`/`dndSettings`/tag-derived exclusion; script re-runnable without side effects.
- **B:** every claim quotes the actual message text and contact_id. Ranked by cost of
  being wrong — missed opt-outs first, wrongly-killed leads second.
- **C:** total rows accounted for (kept + excluded == pulled). No contact appears in two
  segments. Dedupe collisions resolved compliance-first.
- **D:** no price/number in any draft. Each draft references something the seller
  actually said (except `never_replied`, which gets a fresh angle).
- **E:** headers match GHL import spec. Excluded contacts are absent from every send file.

## 7. Agent Log (agents append here; head agent verifies)

<!-- format: ### [stage] agent-name — YYYY-MM-DD HH:MM — STATUS -->
<!-- what was done / counts / files written / anything the head agent must decide -->

### [plan] head agent — 2026-08-21 — PLAN LOCKED
Operator answered all 4 forks (§1). Ground truth verified against live GHL (§2).
Compliance gap found and made a blocking gate (§4). Stages A and B dispatched in parallel.

## 8. Open questions for the operator

<!-- head agent appends anything that is genuinely the operator's call -->

- (none yet)
