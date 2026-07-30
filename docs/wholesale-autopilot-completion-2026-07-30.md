# Wholesale Autopilot Completion Evidence - 2026-07-30

## Scope and safety

This report covers the local implementation and verification for B1-B9. The Task
8 agent did not invoke SSH, `git push`, a deploy command, a service restart, a
live-state write, seller SMS, or a live Telegram action. The workstation
auto-sync and box autopull did deploy the committed changes without a manual
deploy.

Local state read after verification:

```json
{
  "aceMode": "off",
  "autopilot": {"enabled": false, "sentToday": 0},
  "testMode": {"enabled": false, "envPhones": [], "phones": []}
}
```

This is local evidence only. The live box state must be verified separately.

## Baselines

The pre-fix production-like baseline is inherited from the dated task brief; Task
8 did not reproduce it because its scope prohibited SSH/live work. That baseline
reported 5 auto-sends, 0 gate blocks, 0 errors, 1 call pivot, and 1 call-ready
card. It also documented missed price asks, denial false positives, an opener
pivot with zero facts, vault-only prompt loading, and qualifying-draft drift.

Task 8 independently reproduced the known local integration debt before editing:

```text
python -m unittest -v test_e2e_pipeline
Ran 23 tests
FAILED (failures=3)
```

The failures were:

1. Shadow qualification rejected the fake literal `draft for c4` twice.
2. Supervised qualification rejected the same non-adherent fake draft.
3. Call-ready shadow called `FakeMarcus.make_proposal_for(..., pivot=True)`, but
   the fake lacked `pivot=` and the stale test expected direct escalation.

No production check was weakened to resolve these failures.

## B1-B9 disposition

| Bug | Status and evidence |
|---|---|
| B1 | Fixed. The classifier is tracked in `forge rei/seller_classify.py:40`; `marcus_engine.classifier_source()` at line 106 exposes source metadata. The isolated deployed-box harness confirmed the copied `seller_classify.py` as production and reported the legacy draft override separately. |
| B2 | Fixed. All 14 price strings pass locally, and the deployed-box deterministic probe reported `priceMissed=0` of 14. Claude-dependent scenario-B confirmation remains blocked below. |
| B3 | Decision: **option (b), 3 facts**. `forge rei/ace.py:32` sets `READY_MIN_FACTS = 3`, enforced at line 508. READY below three facts keeps qualifying; explicit PRICE pivots immediately. This preserves broad seller intent while avoiding empty call cards. |
| B4 | Fixed. Context-aware denial logic is at `forge rei/marcus_engine.py:335`. All 8 required non-denials return false locally, true ownership/identity denials remain true, and named denials require matching contact context. The deployed-box deterministic probe reported `denialFalsePositives=0`. |
| B5 | Fixed. Seed/vault source metadata is exposed by `forge rei/marcus_engine.py:169`; ACE returns `degradedPrompt`, and `forge rei/ace.jsx:115` renders `DEGRADED PROMPT`. The deployed-box harness loaded a 10,640-byte reply rubric and 18,714-byte playbook. |
| B6 | Fixed. Grounded one-fact hints are built at `forge rei/ace.py:410`; deterministic adherence and known-fact re-ask rejection are at line 446. Drafting retries once, then fails closed without reply/send accounting. |
| B7 | Recommendation only, **not implemented pending operator sign-off**: preserve permanent seller-facing silence after the single call pivot. If a new inbound remains unacknowledged for **2 hours**, send an operator-only Telegram re-ping quoting the inbound and increasing urgency. |
| B8 | Verified locally. `forge rei/test_sms_guard.py:145` uses the real temporary send ledger and proves the second autonomous touch is blocked by `send_ledger`. `forge rei/test_telegram_ace.py:101` exercises callback parsing through durable `ace.hold`; line 107 statically verifies production connector registration. |
| B9 | Verified. Protected uncached autopilot status/toggle routes are wired at `forge rei/connector.py:567`, `:2561`, and `:3157`; the independent fail-closed UI switch is at `forge rei/ace.jsx:66`. Approval-only nurture check-backs persist and post `checkback_due` alerts at `forge rei/followup.py:195`; no seller auto-send was added. B5 health UI is also present. |

## B3 reasoning

Option (b) is the recorded recommendation/decision with three required known
facts:

1. It keeps ordinary acknowledgements such as `yes`, `ok`, and `interested`
   useful without treating them as an immediate empty-card handoff.
2. Three facts provide enough call context while avoiding a long text
   interrogation; the five counted facts remain condition, timeline,
   motivation, occupancy, and price.
3. PRICE remains an unconditional immediate pivot because asking another
   qualifying question after a direct number request is the wrong conversation
   move and risks losing the seller.

## Sixteen-hop audit

`Verified` below means exercised with real local application code and isolated
state. `Partial` names the remaining boundary. Nothing in this table is evidence
of live-box health.

| # | Hop | Local result |
|---|---|---|
| 1 | Seller SMS to GHL conversation | Partial: FakeGHL returns an inbound conversation row; real GHL receipt/search is remote-unverified. |
| 2 | Scout sweep | Verified: E2E poll scores and buckets inbound rows. |
| 3 | Scout auto-handoff | Partial: E2E exercises the real engines with connector wiring reproduced synchronously; live callback registration/execution is remote-unverified. |
| 4 | Marcus screening | Verified locally with real `Screener` persistence and canned Claude transport; real Claude response is remote-unverified. |
| 5 | Screening to conversation state | Partial: real `ConversationEngine.update` and fact/state derivation run; connector bridge is reproduced in the E2E test. |
| 6 | ACE decision | Verified for reply, pivot, escalate, stop, READY threshold, PRICE priority, and kill switches. |
| 7 | Marcus draft | Partial: production interfaces, hints, skill resolution, and adherence gates are verified; a real Claude/vault draft needs the remote harness. |
| 8 | Price scrub | Verified by focused Marcus/ACE/SMS safety tests, including leaked-price pivot replacement. |
| 9 | Central SMS gate | Verified locally for DNC, hours, clock-out, soft-no, own-message, price/offer, legit, ledger dedupe, and cap behavior. |
| 10 | Send and ledger record | Partial: fake GHL captures `/conversations/messages` and real ledger behavior is tested; live HTTP transport is remote-unverified. |
| 11 | Conversation ledgers | Verified: reply and call-pivot persistence, one-pivot dedupe, and state survival are covered. |
| 12 | Call card | Partial: call-ready JSON persistence, dedupe, and queue behavior are verified; live Telegram delivery is remote-unverified. |
| 13 | Receipt and kill switches | Partial: real callback parser, production action registry, durable hold, and subsequent stop are verified; live Telegram transport/tap is remote-unverified. |
| 14 | Operator acknowledgement | Verified: `ace.ack` transitions to `HANDED_OFF` and clears the waiting queue. Live endpoint exercise is remote-unverified. |
| 15 | Atlas underwriting | Verified in E2E: seller-ask anchors reach the call-ready flow. Real model response remains part of the remote harness. |
| 16 | Digest | Verified: `ace.digest` counts sends/blocks and `/api/ace/digest` is registered uncached. Live HTTP response is remote-unverified. |

Kill-switch tests cover ACE off, clock-out, per-thread hold, and test-mode scope.

## Local verification

Interpreter:
`C:\Users\ymjg0\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`
(Python 3.12.13). Windows `python` is a Microsoft Store alias.

```text
FORGE_MARCUS=0 PYTHONUTF8=1 python -m unittest discover -s . -p "test_*.py" -v
Ran 293 tests in 2.861s
OK

python test_ace.py
Ran 68 tests in 1.083s
OK

python test_sms_guard.py
Ran 26 tests in 0.049s
OK

python test_dropship_skills.py
dropship skills self-check OK - 14 skills, 0 orphans

AST parse
AST OK: 15 changed Python files

node "forge rei/deploy/valjsx.js" "forge rei/ace.jsx"
OK forge rei/ace.jsx

git diff --check
git diff --check 27096b75..HEAD
both exited 0
```

Without `PYTHONUTF8=1`, the first discovery run completed 292 tests with one
environmental error: `test_daycare_blast` printed a Unicode arrow through the
Windows cp1252 console and raised `UnicodeEncodeError`. The UTF-8 rerun is the
authoritative full-suite result; no product assertion failed in the cp1252 run.

Task 8 commits were created and pushed by the workstation auto-sync service:

- `4de19935c90bd4b8a9fd4c7225b08d36d2b06064` - current-contract E2E fixtures.
- `3275862` - tracked-classifier harness probe and regression contract.

Task 8 did not invoke `git push` or any deploy command.

### Review fix round 1

The harness provenance signal is backed by executable resolved-path coverage,
not only a static AST-name check. The pure helper accepts exactly the isolated
repo's `seller_classify.py` (including a normalized equivalent path) and rejects
the external legacy scan module, an outside same-named file, and a missing
source. The probe's helper wiring is checked separately.

```text
focused provenance tests: 2/2 passed
test_marcus_filters + test_e2e_pipeline: 40/40 passed
full discovery: 294/294 passed
```

## Skill-update assessment

No agent seed skill was changed for Task 8. The reusable lessons were test-double
interface parity and path-based harness provenance, both code-specific integration
plumbing rather than Marcus/Scout/Atlas judgment. Updating a learned playbook would
put test mechanics into an agent decision skill and is not warranted.

## Remote evidence

### Post-fix production-like isolated harness

The parent ran the post-fix isolated harness on the deployed box on 2026-07-30.
The deterministic configuration and classifier/filter probes passed:

```text
CONFIG replyRubricBytes=10640 playbookBytes=18714
PROBE classifySource=<isolated forge-rei>/seller_classify.py
PROBE usingProductionClassifier=true
PROBE legacyDraftOverride=true
PROBE priceMissed=0 priceTotal=14
PROBE denialFalsePositives=0
```

The Claude-dependent chain did **not** complete. Anthropic returned HTTP 400
because the API credit balance was too low during screening, drafting, and
`legit_check`. The harness reported:

```text
SENT_COUNT 0
```

Therefore this run is **not** acceptance evidence for:

- Scenario A avoiding the opener pivot and pivoting on the explicit price ask.
- Scenario A facts being populated before the pivot.
- Scenario B pivoting on its price ask.
- Assigned-fact adherence across generated drafts.
- Zero repeated already-known-fact questions.
- Successful gated sends, call pivots, or call-ready cards through the full
  Claude-dependent chain.

Restore Anthropic credits and rerun the complete isolated harness. Do not infer
scenario acceptance from the deterministic probe results.

### Deploy and live health

The workstation auto-sync committed/pushed the changes and the box autopull
deployed them. No manual `git push` or deploy command was used by Task 8.

- Deployed application commits included the Task 8 changes through `91ee41b`
  before this evidence-only report update.
- `forge-reios` service: active.
- HTTP 200:
  - `GET /api/ace/status`
  - `GET /api/ace/digest`
  - `GET /api/ace/callready`
  - `GET /api/autopilot/status`
  - `GET /api/marcus/status`
- HTTP 404:
  - `/.env`
  - `/ALL_KEYS.env`
  - `/forge%20rei/.env`
- Live ACE mode: `off`.
- Live autopilot enabled: `false`.
- Live test mode enabled: `false`.
- Live test phones: empty.
- Blocking external error: Anthropic API HTTP 400, credit balance too low.

## Go/no-go

**NO-GO for flipping ACE to full.** Service health, endpoint protection, live
off-state, tracked classifier provenance, price classification, denial filtering,
and prompt bytes are verified. Anthropic credits must be restored and the full
Claude-dependent isolated harness must then pass every scenario requirement.
After that, start with the existing capped mode and watch first-week price
pivots, fact-adherence rejects/retries, gate blocks by reason, call-ready
acknowledgement latency, duplicate-touch prevention, and unanswered post-pivot
inbound age.

## Final Important-Finding Fix Wave

This local-only review wave addressed the three remaining Important findings.
It did not invoke SSH, deploy, push, restart a service, inspect or change live
state, send SMS, or call live Telegram. The workstation auto-sync service
created commits while the worktree was being edited.

### Fixes

1. `marcus_engine._is_denial` now limits ambiguous confused-recipient phrases
   such as `you called me`, `who is this`, and `what is this` to complete-message
   denial shapes. Explicit ownership denials and expected-name matching are
   unchanged. Continued property/selling context remains active through Scout.
2. `seller_classify._PRICE_RE` no longer treats bare `range`, `numbers`, or
   `offer` as a price ask. Those terms require question/request grammar, while
   every existing string in `PRICE_ASKS` still returns `PRICE` immediately.
3. ACE assigned-fact adherence now requires a fact-targeted interrogative or
   request. A fact statement followed by an unrelated call question is rejected.
   Natural question/request paraphrases for all five facts remain admitted.

### TDD evidence

RED runs against the pre-fix production predicates:

```text
test_marcus_filters: 19 tests, FAILED (failures=7)
AceDraftAdherenceTest: 8 tests, FAILED (failures=10)
valid request regression: 1 test, FAILED (failures=1)
Scout continued-context integration: 1 test, FAILED (failures=3)
```

The failures were the intended behavior gaps, not import or fixture errors.

Fresh GREEN verification after the final source edit:

```text
focused Marcus filters: 19/19
focused Ace adherence: 9/9
focused Scout integration: 1/1
test_ace + test_marcus_filters + test_sms_guard + test_e2e_pipeline: 140/140
FORGE_MARCUS=0 PYTHONUTF8=1 full discovery: 300/300
AST parse: 6/6 changed Python files
git diff --check: clean
```

Auto-sync commits for this wave:

- `ce25666c072ed6ae1a4acffa84bad394bcc9c92e`
- `3b0f73109439181431cad27903fcbea60a515616`
- `3c990a3c1ec17e660eed2add63e33cd31f4fce51`
- `6693302` (comment-only clarification after diff review)

Detailed evidence is in
`.superpowers/sdd/2026-07-30-wholesale-autopilot-fixes/final-fix-report.md`.

### Remaining concern

The go/no-go remains **NO-GO**. This wave did not rerun the remote,
Claude-dependent isolated harness, and the prior low-credit Anthropic HTTP 400
blocker remains unresolved in the available evidence. Restore credit and pass
that harness before enabling ACE.
