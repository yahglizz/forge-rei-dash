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
| 3 | `soft_no` ("not right now", "few months", "later") | **RE-ENGAGE — as AMENDED 2026-08-21, see below.** Operator intent: exclude only people who said they don't want to sell. |

> **AMENDMENT to decision 3 (head agent, 2026-08-21, evidence-backed).** The literal
> reading — keep everything tagged `soft_no` — is WRONG and would violate the operator's
> own stated intent. `_SOFT_NO_PHRASES` conflates timing with refusal: of the 42 `soft_no`
> rows in the Ohio data, **41 are flat refusals** (`'NOT FOR SALE!!!'`,
> `'Not for sale no matter what the offer would be'`,
> `"I still own it but I'm not interested in selling thank you"`, `'Yes but not selling'`).
> Ruling: `soft_no_refusal` stays `dead_end`; only `soft_no_timing` becomes
> `soft_no_revisit`. Ambiguous → refusal, per §5.5. `SOFT_NO_REFUSAL_IS_KEEP` stays
> **False**. Verified independently by the head agent against the raw CSV.
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

> **CORRECTION (head agent, 2026-08-21).** The stated *mechanism* above was partly wrong:
> in the Ohio data all 205 STOP_KEYWORD contacts had already been caught by the thread
> classifier — carrier-STOP-with-no-thread-message did not occur there. The gate is still
> mandatory, for two different reasons it did catch: **46 TCPA-grade opt-outs** (DNC tag /
> operator-set DND) sitting inside live buckets — `active_pending_us` 32,
> `replied_then_cold` 10, `never_replied` 4 — plus **106 STOP_KEYWORD contacts outside
> Ohio** the previous run never looked at. Verified independently by the head agent
> against live GHL: 7,363 pulled · `dnd` bool 4 · `dndSettings.SMS` not-inactive 2,957 ·
> DNC-ish tag 78. Reason codes: 30005 1371 · 30003 1170 · STOP_KEYWORD 311 ·
> operator-manual 92 · 30006 10 · 21610 2 · "Opted out" 1.

**Two classes of exclusion — do not collapse them.** `dnd_class` distinguishes:
- **`opt_out`** — person-level, permanent, compliance-grade (STOP_KEYWORD, 21610
  blacklist, operator-set DND, DNC tag). Unbeatable dedupe rank. Never text again by any
  number.
- **`undeliverable`** — that *handset* only (Twilio 30003/30005/30006, 2,551 contacts).
  Not a compliance event. Must NOT poison the same seller's second number — thousands of
  contacts carry "ohio 1st/2nd number" tags, so collapsing these to person-level would
  discard reachable leads. Excluded from SMS sends anyway: an undeliverable number wastes
  spend and degrades carrier sender reputation.

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
| B2 | **Classifier Hardener** | B | Implement B's 8 fixes + the `seller_classify` production fix. Local only, NO deploy. Leaves `test_optout_hardening.py`. **Blocks C.** |
| C | **Sweep run** | A + B2 | Full 7,363 sweep executed → `all_leads_audit.csv` + per-segment CSVs, deduped by address/phone. |
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

### [A] Sweep Engineer — 2026-08-21 17:05 — DELIVERED (2 decisions for the head agent)

**File:** `forge rei/full_leads_audit.py` (~370 lines, imports `leads_audit.py` — no
classifier/pagination/auth was copied). Read-only, GET-only, re-runnable.
Knobs: `AUDIT_LIMIT` (slice), `AUDIT_PULL_EXCLUDED_THREADS`, `SOFT_NO_REFUSAL_IS_KEEP`.
Self-check: `python3 full_leads_audit.py --selfcheck` (pure logic, 0 API calls) — PASSES.

**1. All states.** `TARGET_STATE` and the blank-state drop are gone. Raw `state` kept in
the output. Location truth: OH 5,527 · PA 1,137 · DE 690 · FL 3 · NJ 1 · CA 1 · blank 4.
The Ohio run's 1,836 missing contacts were 1,832 non-OH + only 4 blank-state.

**2. soft_no split.** `LA._SOFT_NO_PHRASES` mixes 13 refusals with 6 timing phrases.
Against the 5,527-row Ohio CSV the 42 `soft_no` rows split **41 refusal / 1 timing**
("Not for sale", "NOT FOR SALE!!!", "I'm not interested in selling thank you" vs "No not
at this time..."). Shipping all 42 as KEEP would blast 41 people who refused. So:
`soft_no_timing` → `soft_no_revisit` (KEEP), `soft_no_refusal` → stays `dead_end`.
Ambiguous ("not selling right now") → refusal, per §5.5.

**3. Compliance gate (§4) — wired, and it fires.** `dndSettings` IS on the list endpoint,
so **0 extra API calls**. Live shape: `{"SMS":{"status":"permanent","message":"STOP_KEYWORD"}}`.
Location-wide: `dnd` boolean True on only **4** of 7,363 (useless alone) · `dndSettings.SMS`
not-inactive on **2,957** · `dnc` tag on **78** (34 of them with NO dnd flag) · `wrong-number`
tag on 1. **Union excluded pre-thread: 2,992.**
SMS DND breaks down as STOP_KEYWORD 311 · Twilio 21610 (blacklist) 2 · operator-manual ~92
· Twilio 30003/30005/30006 (dead handset) 2,551. Split into `dnd_class`: **opt_out**
(person-level, unbeatable dedupe rank 100) vs **undeliverable** (that phone only — it must
NOT poison the seller's second number, and 2,790/2,738 contacts carry "ohio 1st/2nd number"
tags, so collapsing them person-level would have killed thousands of reachable leads).
Columns emitted: `dnd_flag`, `dnd_sms` (raw `status:message`), `dnd_class`, `dnc_tags`,
`exclude_reason`.
**Measured against the 2026-08-02 Ohio run: of 5,050 rows it called LIVE, the gate now
excludes 2,103 — 2,057 undeliverable + 46 TCPA-grade opt-outs** (22 `dnc` tag, ~21
operator-set DND, 3 mixed) that were sitting in `active_pending_us` (32),
`replied_then_cold` (10), `never_replied` (4).
*Correction to §4's stated mechanism:* all 205 Ohio STOP_KEYWORD contacts were already
caught by the thread classifier — carrier-STOP-with-no-message did not occur in that data.
The gate still earns its place via DNC tags + operator DND (the 46), and 106 STOP_KEYWORD
contacts live outside Ohio where the old run never looked.

**4. Reconciliation.** `pulled == kept + excluded + errored`, printed and written to
`*_summary.json` with per-status, per-exclude_reason, and per-state counts. Nothing dropped.

**50-contact slice (verified, real run):** 50 processed → 31 kept / 19 excluded / 0 errored
— **BALANCED**. never_replied 24 · excluded 18 · no_outbound_yet 6 · dead_end 1 ·
active_pending_us 1. Exclude reasons: ghl_dnd/undeliverable 17 · ghl_dnd/opt_out 1 · dnc 1.
States present incl. **1 blank**, FL 3, NJ 1, DE 1. `dnd_sms` populated with real values
(`permanent:STOP_KEYWORD`, `active:TWILIO_ERROR_CODE: 30003/30005/30006`). Dedupe: 33
unique leads from 50 rows. 138 API calls, 53s. Output `slice50_*` — `ohio_*.csv` untouched.
0 `soft_no` rows landed in the slice (42 in 5,527 ≈ 0.8%, so ~0 expected in 50); the split
was validated offline against the Ohio CSV instead (see 2).

**Full-run projection (Stage C):** 2,992 pre-excluded → 4,371 thread pulls →
**~8,816 API calls, ~73 min** sequential at the measured ~1.0 s/contact and ~2 req/s.
Without the skip-excluded optimization: ~14,800 calls, ~123 min.

**DECISIONS FOR THE HEAD AGENT**
1. `soft_no_revisit` will be **~1–5 leads location-wide**, not a real segment — the phrase
   list only recognises 6 timing expressions and Ohio hit 1. Real "call me in a few months"
   language is being classified as `active_pending_us`/`replied_then_cold` instead. Stage B
   should widen the timing regex; until it does, segment D copy for `soft_no_revisit` is
   near-pointless. (Flip `SOFT_NO_REFUSAL_IS_KEEP=True` for the literal §1-decision-3
   reading — but that adds 41 refusals per 5,527 to the blast. Recommend leaving it False.)
2. Full run is ~73 min sequential. A 4-way thread pool would cut it to ~20 min but risks
   GHL burst 429s. Not built — say the word if the wall clock matters.
3. Minor: 1 contact carries a `wrong-number` tag with no DND. Currently excluded as
   `ghl_dnd` with `dnc_tags=wrong-number` (exclusion beats inclusion). Reclassify if you
   want `exclude_reason` semantics kept strictly to opt-out.

### [B] thread-auditor — 2026-08-21 — DONE · VERDICT: NOT SAFE TO BLAST

Audited `leads_audit.py` against the 5,527-row Ohio CSV + `ohio_reengage_prep.json`
(232 threads w/ history) + `batches/*.json`. Read-only; no GHL calls; no repo files added.

**Headline: 118 of the 247 KEEP-bucket rows that have any inbound text (48%) contain a
refusal the classifier missed.** 47 of those are compliance-grade.

P1 — missed opt-outs now sitting in KEEP buckets (TCPA exposure):
- 42 by thread text: profanity-stop 22 (`daGIgIrL6D95JDb4vFVL` "FUCK OFF"), contraction/typo
  stop 8 (`QlqPnCesBROotqwWTd4B` "No and please don't text me"; `tlN4DNv0miscFy0UgQsb`
  "STPP TEXTING ME"; `e58D2VcFStHAmc9AUXFx` "Please don't text or call me anymore respect my
  wishes"), legal/spam threat 4 (`uIIO2uYLQmIVrfrR8Ig9` "I'm suing you for harassment"),
  lose-my-number 2, list-removal 2, blocked 1, 👎/🛑/🤬 reactions 6.
- 7 carry a GHL `dnc` TAG but classify KEEP (3 of them `never_replied`, 0 inbound —
  exactly the carrier-STOP case §4 describes). Union = **47 distinct**.
- `_is_dnc`/`_is_opt_out` only ever read the LAST inbound. 11 of 232 threads have an
  earlier seller opt-out with a benign last line — incl. `Is62uAj55dJ5UPcUguzy` ("Please
  stop damn texting me" → last msg "🤬" → active_pending_us) and `TdPj3xPGmGOUWqowna50`
  ("Stop texting me nigga", also dnc-tagged → active_pending_us). recent_history caps at 8
  lines, so 11 is a floor.
- **`seller_classify.classify("STOPALL") == "CONTINUE"`.** 77 Ohio contacts opted out with
  the STOPALL family. They are excluded in the CSV only because `leads_audit._is_dnc` uses
  a naive substring. `\bstop\b` does NOT match STOPALL — Stage A must not "tighten" that
  substring without adding `stopall|stopallcontact|stopp+`.
- 3 leads the PRODUCTION classifier calls DNC are in leads_audit KEEP buckets.

P2 — wrongly killed / wrongly kept:
- False `dead_end` is small: 7 total. 5 killed as `wrong_number` by
  `_STANDALONE_DENIAL_RE` on "Who is this?"/"Who are you?" (`D3ugTFgL48MGaf4M1icx` had 6
  inbound msgs); 1 killed as `dnc` by the "stop" substring inside
  `IaAAnlDHbkawfRXmMn0J` "All business discussions are handled in person. Feel free to stop
  by"; 1 positive 👍 reaction → `dnc` (`cNOkLSniTFInPccoIXqE`, trigger not visible in the
  120-char snippet — Stage A should re-check on the full body).
- The real P2 is inverted — 72 KEEP rows should be excluded, not re-engaged: 55 wrong-number
  (`_is_denial` is fully `^…$`-anchored, so any extra clause defeats it — `pLM0ClCdIF39kfLxIYQB`
  "WRING NUMBER", `l0zYbfsVRwQVdXeV7y8O` "Look man you got the wrong number. Good luck."),
  7 already-sold (`tUGT0mly876czROQGtlz` "It's sold please forget about it" — `_is_sold` is
  anchored and fired ONCE in 5,527 rows), 10 explicit refusals (`Ha982mQBkRMw3sCp2Bwk` "Nfs",
  `FMJs4kSjyCU5Ymw5T788` "Not intrested").
- `_is_hard_no` and `_is_sold` have ZERO false positives in this data (both effectively
  fullmatch). Their problem is recall, not precision.

**BLOCKS §1 decision 3:** 41 of the 42 `soft_no` rows are PERMANENT refusals
("Not for sale" ×20, `59CwUHtz3musSW37YluN` "Not for sale no matter what the offer would
be", `BgQgjltEjZdhBXyVzCMw` "NOT FOR SALE!!!"). Exactly ONE is a timing objection
(`2rRTndTiHdofAjbCyapd`). Shipping all 42 as `soft_no_revisit` texts 41 people who flatly
refused. `_SOFT_NO_PHRASES` conflates timing with refusal and contains no "later"/"few
months" at all — genuine timing leads never land in soft_no. Split required.

P3 — internal contradictions: 2 `never_replied` rows whose last message is INBOUND
(`2yLVup4rPde9E55Wl1Z0`, `xsXQnERl2lAg0pXW9l2d`) — `_is_our_message` ate a real seller
reply; the filter also eats "Touch of Blessings?" (`MY1qNVo5dCGgbJASuyWV`, an engaged
question) and any seller line containing "as-is"/"cash offer". 1 carrier bounce classified
as a live pending lead (`dtuuGU2W7BWmTroJQlGR` "The number you are sending an SMS to,
currently has no SMS capabilities."). Dedupe: `merge_rank` treats only dnc/opt_out as
unbeatable, so 7 KEEP survivors swallowed a `dead_end` duplicate (`VFfQJHM5bR9fiALwHSZK`
kept over `j9NaCdLdNqjBgNOz2lXN` "No") — same person, one number said no.

**Must change before any send:** (1) read GHL `dnd`/`dndSettings`/`dnc` tag — §4 gate;
(2) scan EVERY inbound in the thread for dnc/opt-out, not just the last; (3) add the
STOPALL family + contraction/typo stop forms + profanity + legal/spam threats + 👎🛑 to the
opt-out set; (4) de-anchor `_is_denial`/`_is_sold`/`_is_hard_no` to search-anywhere;
(5) split soft_no into timing vs. refusal, keep only timing; (6) drop "who is this"/"who
are you" from the denial rule; (7) make ALL dead-end reasons unbeatable in `merge_rank`;
(8) drop "as-is"/"cash offer"/"close fast" from `_OUR_OUTREACH_PHRASES` for inbound.
Also fix `seller_classify._DNC_RE` (misses STOPALL, fires on "stop by").

### [B2] classifier-hardener — 2026-08-21 — DONE · all 8 fixes shipped + 3 the audit could not see

Files changed (local only — see the DEPLOY WARNING at the end):
- `forge rei/seller_classify.py` — LIVE. New `is_opt_out()` is now the single source
  of compliance truth (`classify()` calls it; `leads_audit` imports it), so the send
  gate and the blast scrubber cannot drift.
- `forge rei/leads_audit.py` — thread-wide compliance scan, de-anchored
  denial/sold/hard_no, who-is-this removed, timing regex, merge_rank.
- `forge rei/full_leads_audit.py` — merge_rank mirrored, widened timing wired into
  `soft_no_kind`, timing re-label for KEEP rows, selfcheck extended.
- `forge rei/marcus_engine.py` — LIVE. `_is_our_message` echoable-phrase exemption.
- `forge rei/test_optout_hardening.py` — NEW, stdlib asserts, exit 1 on failure.
  `python3 test_optout_hardening.py` → `test_optout_hardening: ALL PASS`.

**STOPALL NON-REGRESSION (the thing that could have gone silently wrong).** 80 Ohio
rows contain the STOPALL/STOPP family. OLD naive substring caught 80/80. NEW explicit
`_STOP_KEYWORD_RE` catches **80/80. Zero lost.** Across all 5,527 rows only 2 old-dnc
rows are released, both verified false positives: `IaAAnlDHbkawfRXmMn0J` ("Feel free
to stop by") and `cNOkLSniTFInPccoIXqE` (a 👍 whose only "stop" was inside
"Chri-STOP-her").

**Before/after — 5,527 Ohio rows, identical text through old vs new rules**

| bucket | before | after | delta |
|---|---|---|---|
| never_replied | 4802 | 4802 | 0 |
| active_pending_us | 174 | 118 | **-56** |
| replied_then_cold | 76 | 65 | -11 |
| soft_no_revisit | 0 | 2 | +2 |
| no_outbound_yet | 1 | 1 | 0 |
| dead_end | 474 | 539 | **+65** |
| **TOTAL KEEP** | **5053** | **4988** | **-65** |

**KEEP → EXCLUDE: 72** (the audit predicted 72). **EXCLUDE → KEEP: 7** — 5 killed by
"who is this", 1 by "stop by", 1 tapback. Reasons after: dnc 313 · hard_no 110 ·
wrong_number 102 · soft_no_refusal 9 · sold 5 · soft_no_timing 2 (was: dnc 268 ·
hard_no 76 · wrong_number 75 · soft_no 42 · opt_out 12 · sold 1).

**232 threads with real multi-message history:** KEEP → EXCLUDE **74**, EXCLUDE → KEEP
0. **4 of those are caught ONLY by scanning every inbound** (fix 2) — an explicit
opt-out earlier with a benign last line, incl. `Is62uAj55dJ5UPcUguzy` and
`TdPj3xPGmGOUWqowna50`. 32% of threads with real history were unsafe to blast.

**Dedupe (3,582 address groups):** 3 groups where a KEEP survivor now yields to a
dead_end duplicate; 51 groups where a live sibling now beats a wrong_number duplicate.
Deduped keep-list 3,072 → **3,120 (+48)**.

**3 things the audit did not see, found in the data while implementing:**
1. **Our own outreach footer reads "reply STOPALL contact".** Every tapback/quote-reply
   therefore contained "STOPALL" and classified DNC — in production that blocks the
   OPERATOR from answering a 👍. Fixed by matching opt-out patterns only on the words
   OUTSIDE a quoted span (`_seller_words`).
2. …but a **carrier opt-out CONFIRMATION** ("You have successfully been unsubscribed")
   also gets quoted back by a tapback, and stripping it resurrected `45GAWv1ODCSmlXh4VxJo`
   as a live lead. `_OPTOUT_CONFIRM_RE` now matches on the FULL body, before the strip.
3. **Removing "as-is"/"cash offer"/"close fast" from `_OUR_OUTREACH_PHRASES` as fix 8
   literally specifies would have un-filtered 130 real outbound messages** ("Still
   buying as-is for cash…", our standard follow-up #2 — measured on 690 real outbound).
   Implemented as intended instead: those phrases stop condemning a message ONLY when
   it is short (≤32 chars) and hits nothing else. Measured basis: shortest of our own
   messages with echoable-only hits = 47 chars; the only seller reply eaten = 19 chars
   ("Touch of Blessings?", `MY1qNVo5dCGgbJASuyWV`). Our outbound classification is
   **unchanged on all 690 messages**; the eaten seller replies drop 4 → 3 (the rest are
   "Removed 👍 from…" un-likes and a hostile rant).

**ONE DECISION FOR THE HEAD AGENT.** Fix 7 says make ALL dead-end reasons unbeatable in
`merge_rank`. I made every reason unbeatable **except `wrong_number`**, which is
handset-scoped exactly like §4's Twilio `undeliverable`: "you have the wrong number"
is about THAT PHONE, and thousands of contacts carry "ohio 1st/2nd number" tags, so
letting it poison the address deletes the seller's good number with the bad one. That
single choice is the **+48** on the deduped keep-list (51 recovered, 3 given up). Flip
`HANDSET_SCOPED` (leads_audit) / `HANDSET_SCOPED_DEAD_END` (full_leads_audit) to an
empty set for the strict literal reading; it costs ~51 leads location-wide.

**Not fixed, deliberately:**
- `marcus_engine._is_denial` (LIVE) still contains "who is this"/"who are you". I only
  removed it from the audit copy. Changing the live one alters what Marcus skips
  drafting for — a separate, operator-visible behavior change. Recommend doing it, but
  not as a side effect of a blast-list job.
- `dtuuGU2W7BWmTroJQlGR` — carrier bounce ("The number you are sending an SMS to
  currently has no SMS capabilities") still classifies as a live pending lead. One line
  in `_is_seller_message` if you want it; out of scope for the 8.
- A 👎 tapback that quotes our message is not an opt-out (the quote strip leaves only
  "👎 to"). It was not one before either — an unrealized gain, not a regression.

**Verification:** `python3 test_optout_hardening.py` (ALL PASS) ·
`python3 full_leads_audit.py --selfcheck` (OK) · `test_triage_fix.py`,
`test_reactions.py` PASS · `test_marcus_filters + test_audit_regressions +
test_sms_guard + test_ace` = 133 tests, 1 failure that is **pre-existing and
unrelated** (`test_vault_skill_overrides_matching_repo_seed`, a macOS
`/var` vs `/private/var` tempdir-symlink comparison; file last changed 2026-07-30).
Zero GHL calls made — every number above comes from the CSVs and JSON on disk.

> **⚠️ DEPLOY WARNING — NOT MY DOING, NEEDS THE OPERATOR.** I made no commit and no
> push. A pre-existing launchd agent, `~/Library/LaunchAgents/com.forge.autosync.plist`
> → `deploy/auto-sync.sh`, runs **every 60 seconds** and auto-committed + pushed each
> of these edits to `origin/main` as `auto-sync: Mac 2026-08-21 17:2x`. `HEAD ==
> origin/main`. The box's `forge-autopull.timer` polls GitHub every 60s and
> self-deploys, so **the hardened classifier is almost certainly live on the box
> already**. Every change is fail-safe (strictly more conservative on sends, minus the
> 2 verified false positives it releases) and all validation passes, but the "local
> edits only" instruction was defeated by that daemon. Decide whether to leave it, and
> whether to pause `com.forge.autosync` for the rest of this job.

## 8. Open questions for the operator

<!-- head agent appends anything that is genuinely the operator's call -->

### Q1 — LIVE PRODUCTION BUG, open right now (needs an operator call on the hotfix)

`seller_classify.py` governs how Marcus classifies **live inbound seller replies on the
box**. Two verified defects, reproduced by the head agent 2026-08-21:

```
seller_classify.classify('STOPALL')            -> 'CONTINUE'   # must be DNC
seller_classify.classify('stop by the office') -> 'DNC'        # must not be
```

77 Ohio contacts opted out using the STOPALL form. Production treats them as live
conversations to reply to. This is a TCPA hole open in the running system **today**,
independent of this re-engage job — and it is the exact path every reply from this campaign
will flow through. Stage B2 is fixing it locally. **It is not deployed.** Operator decides
when it ships (CLAUDE.md rule 1 wants auto-deploy; this touches live seller handling, so it
waits for a yes).

### Q2 — A2P/10DLC registration status (blocks the whole channel decision)

Decision §1.1 is a GHL bulk SMS campaign to ~4,000+ contacts. That requires the wholesale
sending number to be A2P/10DLC registered and in good standing. If it is not, a blast this
size gets carrier-filtered or the number gets shut down, and the send channel has to change.
Operator to confirm in GHL → Settings → Phone Numbers → Trust Center. Unanswered as of
2026-08-21.

### Q3 — Send volume / ramp (needed before Stage E)

Even with 10DLC in good standing, blasting ~4,000 messages in one burst from a number with
a months-long quiet period is a spam-filter trigger. Stage E should propose a daily ramp
rather than one send. Operator sets the ceiling.

---

### [head agent] verification of Stage A + Stage B — 2026-08-21 — BOTH ACCEPTED

**Stage A — verified, accepted.** Independently re-pulled all 7,363 contacts from live GHL.
Numbers match Stage A's exactly: `dnd` bool 4 · `dndSettings.SMS` not-inactive 2,957 ·
DNC-ish tag 78 · reason codes 30005 1371 / 30003 1170 / STOP_KEYWORD 311 / operator-manual
92 / 30006 10 / 21610 2 / "Opted out" 1. `full_leads_audit.py` confirmed read-only (no
POST/PUT/DELETE verbs present), `--selfcheck` passes, `ohio_*.csv` mtimes still Aug 2 —
nothing clobbered.
Rulings on Stage A's three questions:
1. **`soft_no_revisit` stays a bucket but gets no dedicated copy track** if it lands at
   ~1–5 leads. Stage B2 is widening timing detection; final call after its delta report.
2. **Sequential run, no thread pool.** 73 min is acceptable for a background job; a 4-way
   pool risking 429 bursts against the *live* location could rate-limit Marcus's production
   loops on the box. Not worth 50 minutes.
3. **Reclassify the `wrong-number`-tagged contact** to `exclude_reason=wrong_number`.
   Keeps `ghl_dnd` semantics strictly compliance-grade. Still excluded either way.

**Stage B — verified, accepted; it changes the critical path.** Spot-checked its highest-cost
claims against live code: `_is_dnc` confirmed False on "STPP TEXTING ME" / "Lose my number" /
"FUCK OFF"; `seller_classify` STOPALL and `stop by` defects reproduced exactly as reported.
Headline stands: **47 compliance-grade opt-outs sitting in KEEP buckets, and 72 further KEEP
rows that should be excluded** (55 wrong-number, 7 sold, 10 refusal).
One sub-claim corrected: Stage B wrote that `_SOFT_NO_PHRASES` contains no "later"/"few
months" at all — `'maybe later'` is in fact present. The list is exactly 13 refusals + 6
timing, as Stage A described. Stage B's practical conclusion is unaffected: bare "call me in
a few months" is absent, so genuine timing leads land in other buckets. Both agents converge
on the same fix; the §1.3 amendment stands unchanged.

**Consequence:** Stage C is BLOCKED behind a new Stage B2. Running the sweep on the current
classifier would produce a list with 47 known opt-outs in it.

### [B2] Classifier Hardener — DISPATCHED 2026-08-21
Implementing Stage B's 8 fixes + the `seller_classify` production fix. Local edits only,
explicitly **no deploy**. Must leave a runnable `test_optout_hardening.py` and prove the
STOPALL count does not regress.

---

### [head agent] verification of Stage B2 — 2026-08-21 — ACCEPTED

Ran B2's suite myself: `test_optout_hardening.py` → **ALL PASS (exit 0)**;
`full_leads_audit.py --selfcheck` → OK. Spot-checked the live rules directly:

```
STOPALL / Stopall / STOP ALL -> DNC      STPP TEXTING ME -> DNC    FUCK OFF -> DNC
stop by the office           -> CONTINUE  Lose my number  -> DNC    Who is this? -> HELP
yes im interested -> READY                how much can you offer -> PRICE
```
De-anchored audit rules: `"Look man you got the wrong number. Good luck."` → denial ✓ ·
`"No it's been sold"` → sold ✓ · non-regression holds — `"sold my other house"` and
`"not sold yet"` still do NOT fire. Real buying intent still classifies (READY/PRICE), so
the hardening did not over-block.

**Ruling on B2's open decision:** `wrong_number` **stays handset-scoped**
(`HANDSET_SCOPED_DEAD_END = {"wrong_number"}`). It is a property of the handset, not the
person — identical logic to §4's `undeliverable` class. A seller whose 1st number reaches a
stranger is still reachable on their 2nd. Worth +48 leads on the deduped keep-list. NOT
flipped to the strict literal reading of fix 7.

Accepted B2's three judgment calls as made — each was better than the instruction it was
given, and each is evidenced:
- our own outreach footer says "reply STOPALL contact", so every tapback quoting our text
  was classifying DNC and blocking the operator from answering a 👍 — fixed by matching
  only outside quoted spans, while still catching carrier opt-out confirmations on the
  full body first;
- fix 8 as literally written would have un-filtered **130 real outbound messages**
  ("Still buying as-is for cash…" — our standard follow-up #2). Implemented as a
  short-message (≤32 char) exemption instead. Measured margin: shortest of our own
  messages with echoable-only hits = 47 chars; the seller reply being eaten = 19 chars.

### ⚠️ DEPLOY INCIDENT — 2026-08-21 (no fault of the agent; disclosed to operator)

B2 was instructed "local edits only, NO deploy" and made no commit and no push. It was
deployed anyway: `~/Library/LaunchAgents/com.forge.autosync.plist` → `deploy/auto-sync.sh`
auto-commits and pushes to `origin/main` **every 60 seconds**, and the box's
`forge-autopull.timer` polls GitHub every 60s and self-deploys. Daemon predates this job
(installed Jul 14).

**Verified live state on the box:** `seller_classify.classify('STOPALL')` → **DNC**,
`'stop by the office'` → **CONTINUE**, `systemctl is-active forge-reios` → **active**.
The production TCPA hole is closed. Every shipped change is fail-safe (strictly more
conservative on sends, minus 2 verified false positives it releases).

**Privacy check performed because that repo (`yahglizz/forge-rei-dash`) is PUBLIC:**
`marcus_state/` is gitignored, **0 tracked files** — no seller names, phones, or addresses
have been pushed. Only code. Confirmed clean.
*Unrelated pre-existing item for the operator:* `forge rei/screenshots/leads.png` IS tracked
in the public repo — worth checking whether it shows real seller data.

**Open for the operator:** pause `com.forge.autosync` for the rest of this job? Downstream
stages produce lead CSVs; they are gitignored today, but the daemon means no local-only
guarantee exists on this machine.

### [C] Sweep run — STARTED 2026-08-21
`python3 full_leads_audit.py` over all 7,363, sequential, log at
`marcus_state/leads_export/full_sweep.log`. Settings as ruled: `AUDIT_LIMIT=0`,
`SKIP_THREADS_FOR_EXCLUDED=1`, `SOFT_NO_REFUSAL_IS_KEEP=False`,
`HANDSET_SCOPED_DEAD_END={"wrong_number"}`. ETA ~73 min.

### [C] Sweep run — 2026-08-21 18:12 — COMPLETE, verified

7,363 processed · 0 errored · **reconciliation BALANCED** (4,057 kept + 3,306 excluded).
8,808 API calls, 2,123s (~35 min — faster than the 73-min projection).

| status | raw | deduped |
|---|---|---|
| never_replied | 3,837 | 2,823 |
| active_pending_us | 116 | 109 |
| replied_then_cold | 88 | 80 |
| no_outbound_yet | 16 | 11 |
| dead_end | 314 | 253 |
| excluded (GHL gate) | 2,992 | 1,550 |

**Deduped keep-list: 3,023 leads** (4,826 unique contacts from 7,363 rows).
Exclude reasons: `ghl_dnd/undeliverable` 2,548 · `ghl_dnd/opt_out` 444 · `hard_no` 119 ·
`wrong_number` 96 · `dnc` 82 · `soft_no_refusal` 12 · `sold` 5.
States: OH 5,527 · PA 1,137 · DE 690 · blank 4 · FL 3 · NJ 1 · CA 1.

**`soft_no_revisit` came back EMPTY (0 leads)** even with B2's widened timing regex —
confirming Stage A's prediction. Genuine "call me in a few months" language lives in
`active_pending_us` / `replied_then_cold`, which get re-engaged anyway. **Ruling: the
segment is retired; no dedicated copy track. §3's row stays for schema stability only.**

**Head-agent compliance verification of the output (all PASS):**
```
contact_id in BOTH keep and excluded  : 0
contact in >1 keep segment            : 0
keep rows carrying dnd/dnc/exclude mark: 0
dnd_sms on keep rows                  : blank on all 3,023
keep rows with no phone               : 1
```

**Deliverable:** `marcus_state/leads_export/all_leads_CLEAN_3023.csv` — all four keep
segments merged, sorted warmest-first. Delivered to the operator.

### [D] Copy Writer + [E] Campaign Packager — DISPATCHED 2026-08-21
D: 3 bulk template variants × 2 cold segments + 189 individually-grounded warm drafts
through the real `marcus_engine._ai_draft` harness. E: GHL-import spec + non-duplicating
path, send ramp, reply-handling readiness, pre-flight checklist. Both propose-only.

---

### [E] Campaign Packager — 2026-08-21 — DELIVERED (propose-only; nothing touched in GHL)

Zero GHL calls of any verb. Zero deploys, zero commits by me. Every number below comes from
the Stage C CSVs on disk or from read-only inspection of the box.

**Files written**
- `forge rei/campaign_package.py` — pure-local packager (stdlib, no network). Re-runnable.
- `marcus_state/leads_export/GHL_IMPORT_active_pending_us.csv` — **109**
- `…/GHL_IMPORT_replied_then_cold.csv` — **80**
- `…/GHL_IMPORT_no_outbound_yet.csv` — **10**
- `…/GHL_IMPORT_never_replied.csv` — **2,823**
- `…/GHL_IMPORT_verification.json` — the leak-check evidence
- `…/CAMPAIGN_SEND_PLAN.md` — import path, ramp, copy slots, GO/NO-GO, kill switch
- `…/CAMPAIGN_PREFLIGHT.md` — the checklist

**3,022 sendable** (3,023 − 1). The one removed row is `KehwKm3V4Nj6Yan11Wx8`
`yahjair (operator)` — the operator's own CRM record, the only blank phone in the keep-list.

**1. GHL header spec — found, not guessed.** `~/Desktop/marcus-wholesale-agent/skills/
wholesale-list-cleaner/SKILL.md` §"Output Format (GHL-Ready)", corroborated by all three of
its scripts (`clean_list.py` `GHL_COLUMNS`, `clean_multiphone.py:33`,
`clean_batchdata_list.py:24`):
`First Name | Last Name | Phone | Email | Address1 | City | State | Postal Code`, phone in
E164. Emitted in that order, then `Tags`, `Contact Id`, `Segment`. All 3,022 phones were
already E164 in Stage C output. Names title-cased on split; LLC/Trust suffixes ride with the
last name.

**2. Non-duplicating import path — RECOMMEND: do not import at all.** These contacts already
exist in GHL. Tag by `contact_id` via `POST /contacts/{id}/tags {"tags":[…]}` — the exact
call production already makes (`scout_triage.py:1467-1475` / `:1447-1459`, v2
`services.leadconnectorhq.com`, `2021-07-28`). Additive, cannot create a contact, cannot
overwrite a field, reversible with the matching DELETE. Then every smart list is a tag
filter forever after. 3,022 POSTs ≈ 25 min at the measured ~2 req/s. It is a WRITE, so it
needs the operator's yes and a runner script — **deliberately not built** (§5.1).
If the operator prefers the wizard: update-mode, **dedupe on Phone, never Email** —
**1,215 of 3,022 rows (40%) have no email**, so an email-keyed import creates 1,215 duplicate
seller records. Leave `Contact Id`/`Segment` unmapped.
**"Just filter in GHL" does NOT work here** and is worth killing now: the four segments come
from full-thread direction analysis through the B2-hardened classifier, and GHL has no native
filter for "last message direction across the whole thread". The hybrid is the lazy correct
answer — tag once, filter forever.

**3. Ramp — 12 send days + 1 hold, warm first.**
D1 `active_pending_us` 109 → D2 `replied_then_cold` 80 + `no_outbound_yet` 10 = 90 (cum 199)
→ **D3 HOLD 0, GO/NO-GO** → D4 50 · D5 100 · D6 200 · D7 300 · D8-D12 400 each · D13 173.
Cold = 650 + 2,000 + 173 = 2,823. Total 199 + 2,823 = **3,022** ✓. **13 business days ≈ 17
calendar days ≈ 3 weeks.** Intra-day: 50 per batch every 30 min, 10:00–17:00 ET (every
contact is in an ET state: OH 2,181 · PA 490 · DE 346 · FL 2 · NJ 1; the 2 blank-state rows
go 11:00–16:00 ET, safe in every US timezone; the location's single CA contact was already
excluded by the Stage C gate).

**Where 400/day comes from — and what is still Unknown.** The **carrier daily cap is
UNKNOWN** (Q2, unread Trust Center). 400 is **not** carrier-approved and must not be
presented as such; if the brand is low-tier the ramp gets re-cut. 400 is derived from
**measured reply-handling capacity**: Scout scores 15/sweep at 180 s = 300/hr
(`scout_triage.py:74-76`), hands off 10/sweep = 200/hr (`:707`) — neither is binding; the
operator is, at ~15–20 calls/day, and 400 × 4% reply ≈ 16 replies/day. Warm-up shape (50 →
100 → 200 → 300 → 400) is practice, not a limit: the number has been quiet ~40 days (box
`send_ledger.json` = 2 entries, last write Jul 12). Scout's 400-conversation window only
breaks above ~130 msgs/min; the ramp peaks at ~1.7/min.

**4. Reply readiness (read-only box inspection — nothing changed, nothing deployed).**
GOOD: `forge-reios` **active**; `FORGE_MARCUS=1` is in the systemd unit itself so loops run;
`/api/health` → `loopsEnabled: true`, `ops.paused: false`, Scout last ran **61 s ago**;
interval is the default 180 s (no override) — sane for a spike; gate ON (`autoSend: false`,
`autoSendNrn: false`); autopilot off; `send_ledger` = 2 entries (nothing ever sent).

**⚠️ THE ONE THAT MATTERS — inbound replies do NOT auto-produce a one-tap SMS draft.** Both
drafting switches are off: `FORGE_MARCUS_SMS` is set **nowhere** on the box → defaults to
`"0"` → `MARCUS.run_forever` never starts (`connector.py:4854-4857`; that is why
`/api/marcus/status` shows `"lastPoll": null`), **and** `ace.mode()` is `"off"` (box
`ace.json`) while `_ace_update_from_screening` only calls ACE when mode ≠ `"off"`
(`connector.py:1185`). On a reply the operator DOES get: Scout score + bucket + hot auto-tag
+ auto-pipeline + Telegram ping + a Marcus **screening report**. What is missing is the
reply draft — the operator must press "Hand to Marcus" per lead (`connector.py:3516`).
Invisible at 5 replies/day; a bottleneck on day 1's 109 warm leads. **Operator's call before
send #1** — it is a live-seller behavior change, not a list-job side effect.

Also to fix before send #1: **38 proposals already pending** unactioned
(CONTINUE 22 · WRONG_NUMBER 10 · READY 5 · PRICE 1) — day-1 replies would queue behind them;
**Telegram quiet hours are DISABLED** with `hot_lead` + `proposal` pings on, and days 1–2 put
189 warm leads into that pipe with no night guard; **Scout's lead list prunes at
`MAX_RECORDS = 300`** (`scout_triage.py:77`) so over 13 days the oldest fall off the Scout tab
— tags/pipeline/GHL threads are unaffected (display limit, not data loss), but the GHL smart
list must be the system of record, not the Scout tab.
Machine capacity is fine for 189 simultaneous conversations (300 scored/hr, 200 handoffs/hr).
The human is the constraint — which is exactly why warm rides alone on D1–D2 with a D3 hold.

**5. Leak check — proven, not asserted.** `python3 campaign_package.py` → exit 0:
```
block list: 2577 contact_ids / 1803 phones (638 person-level)
active_pending_us   109 in ->   109 out
replied_then_cold    80 in ->    80 out
no_outbound_yet      11 in ->    10 out
never_replied      2823 in ->  2823 out
TOTAL SENDABLE     3022
DROPPED  no_outbound_yet/KehwKm3V4Nj6Yan11Wx8: internal_contact
LEAK CHECK: 0 excluded/dead_end contacts in any send file.  PASS
```
Blocks on every `contact_id` in `all_leads_excluded.csv` (1,550) + `all_leads_dead_end.csv`
(253) **including every dedupe-collapsed sibling id from `duplicate_contact_ids`**, on every
phone in those files, and separately on 638 person-level (`opt_out`/`dnc`/`hard_no`/`sold`/
`soft_no_refusal`) phones. Plus cross-segment id and phone collision checks: **0**. Evidence
in `GHL_IMPORT_verification.json`.

**Note on the autosync daemon.** `com.forge.autosync` is still loaded and pushing every ~60 s
(commits `bcb6fca`/`6b7f797`/`86f0d99` at 18:21/18:23/18:25 today); it auto-pushed
`campaign_package.py`. That is code with no secrets — same class as `full_leads_audit.py`.
**No seller data leaked:** `marcus_state/` is gitignored (`forge rei/.gitignore:12`) with
**0 tracked files**, re-verified. Every CSV above lives there.

**FOR THE HEAD AGENT**
1. Merge Stage D's copy into the four `[[STAGE D COPY — …]]` slots in `CAMPAIGN_SEND_PLAN.md` §4.
2. Decide the drafting switch (`FORGE_MARCUS_SMS=1` vs. `ace` mode vs. leave manual) before D1.
3. Q2 (A2P/10DLC) is still the gate on the whole ramp — 400/day is a capacity number, not a
   carrier number.
