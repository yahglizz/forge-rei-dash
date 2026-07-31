# Wholesale Autopilot Completion Evidence - 2026-07-30

## Executive verdict

**NO-GO for enabling ACE full.**

The deterministic defects and locally verifiable wiring in B1-B6, B8, and B9 are
fixed and reviewed. B7 remains recommendation-only because the task explicitly
requires the operator's decision before implementation. The full post-fix
Claude scenario run remains blocked by Anthropic HTTP 400, credit balance too
low. ACE, wholesale autopilot, and test mode are all off on the live box.

The verified implementation is present through commit `177c82e`; later commits
only refresh this evidence report. The workstation auto-sync pushed the changes
and the box autopull deployed them. No manual seller SMS, live Telegram
callback, pipeline move, or mode-enable action was performed.

## Pre-edit baseline

The production-like isolated harness was run before source edits in this task.
It reproduced the task brief's defects:

```text
CONFIG replyRubricBytes=10640 playbookBytes=15403
PROBE usingProductionClassifier=true
PROBE classifier source=<external toolkit>
PROBE priceMissed=9 priceTotal=14
PROBE denialFalsePositives=7
```

The baseline completed 5 auto-sends, 0 gate blocks, 0 errors, 1 call pivot, and
1 call-ready card. Scenario A pivoted on its opener with zero facts. Scenario B's
turn-4 soft price ask classified `CONTINUE`.

## B1-B9 disposition

| Bug | Disposition and evidence |
|---|---|
| B1 | **Fixed.** The source-of-truth classifier is tracked in `forge rei/seller_classify.py`. `marcus_engine.classifier_source()` reports classifier and optional legacy draft override provenance. Local and isolated-box probes resolve `classify` to the tracked scratch/repo copy. |
| B2 | **Fixed.** The 14 required price asks classify `PRICE`; false-positive regressions cover bare offer/range/numbers statements. The latest box probe reports `priceMissed=0`, `priceTotal=14`. |
| B3 | **Implemented recommendation, operator ratification pending.** Option (b) is in code: `READY_MIN_FACTS = 3`; READY below three facts continues qualification, while explicit PRICE pivots immediately. |
| B4 | **Fixed.** Denial matching is limited to actual identity/ownership denial clauses, with expected-name context. Required motivated-seller non-denials, true denials, seller continuations, and Scout batch-index integrity are covered. The box probe reports 0 false positives. |
| B5 | **Fixed and accepted.** Seed-first/vault-last resolution exposes path, `seed`/`vault`/`missing`, and UTF-8 bytes through `skill_sources()`. ACE status exposes prompt health and `degradedPrompt`; the UI renders `DEGRADED PROMPT`. The actual isolated harness parent/child bootstrap and CONFIG wiring are mutation-tested. |
| B6 | **Fixed deterministically; live model acceptance blocked.** Hints include known facts, drafts get one bounded retry, and fact-adherence rejects missing assigned-fact questions and already-known-fact re-asks without recording a send/fact. Real Claude output cannot be accepted until credits are restored. |
| B7 | **Not implemented, by policy.** Recommendation: keep permanent seller-facing silence after the one call pivot; if a new inbound remains unacknowledged for 2 hours, re-ping only the operator on Telegram with the new inbound quoted. Explicit operator approval is still required. |
| B8 | **Fixed and independently accepted.** A real `MarcusEngine` integration runs two ACE autonomous attempts through production approve/_send, guard, record/release, and a real temporary ledger; the second returns `gate: send_ledger`. A real ACE pivot receipt is selected by `acepivot:<conv>`, and its captured button is dispatched through the production shared callback mapping to durable hold and a subsequent `stop`. |
| B9 | **Fixed/verified.** Protected uncached autopilot status/toggle routes and the separate UI switch are wired. Due nurture check-backs remain proposals/alerts requiring approval; no seller auto-send lane was added. |

Key implementation locations:

- B1/B2: `forge rei/seller_classify.py:20`, `forge rei/marcus_engine.py:106`
- B3: `forge rei/ace.py:32`, `forge rei/ace.py:574`
- B4: `forge rei/marcus_engine.py:353`
- B5: `forge rei/marcus_engine.py:119`, `forge rei/marcus_engine.py:169`,
  `forge rei/ace.jsx:115`
- B6: `forge rei/ace.py:438`, `forge rei/ace.py:452`,
  `forge rei/ace.py:512`, `forge rei/ace.py:669`
- B8: `forge rei/test_ace.py:102`, `forge rei/test_ace.py:236`,
  `forge rei/ace.py:949`, `forge rei/test_telegram_ace.py:140`
- B9: `forge rei/connector.py:567`, `forge rei/connector.py:2559`,
  `forge rei/connector.py:3155`, `forge rei/followup.py:195`

## B3 and B7 recommendations

### B3

Recommend option (b), three known facts:

1. It avoids an empty call card from a bare `yes`/`interested`.
2. Three facts give Marcus enough context without turning SMS into an
   interrogation.
3. PRICE remains unconditional because asking another qualifying question after
   a direct price request is the wrong conversational move.

The five counted facts remain condition, timeline, motivation, occupancy, and
price.

### B7

Recommend an operator-only re-ping after 2 hours when all are true:

1. The one call pivot was already sent.
2. A newer seller inbound exists.
3. The call-ready item remains unacknowledged.

Do not resume seller texting. The Telegram notice should quote the new inbound
and increase urgency. This preserves the one-pivot contract and avoids silently
losing a seller who keeps engaging. It remains unbuilt until explicitly approved.

## Exact B5 and B8 evidence

B5 tests run the tracked harness as a subprocess:

```text
parent _bootstrap -> isolated scratch child -> CONFIG-only exit
```

They assert no `PROBE` or `TURN`, real scratch seed paths, vault precedence,
zero-byte degradation, and a single CONFIG record. Independent mutation review
confirmed both changes are detected:

```text
remove bootstrap seed-copy call       -> test fails
remove shared CONFIG metadata update  -> test fails
```

The latest missing-vault box run reported:

```text
copied seeds=5/5
replyRubric source=seed bytes=10713
playbook sources=seed bytes=16985
degradedPrompt=false
```

B8 exact integration assertions:

```text
ACE attempts                         2
production safety autonomous flags  [true, true]
GHL SMS posts (captured)             1
second gate                          send_ledger
ACE daily-cap charges                1
conversation replies                1
guard sent/pending                   1/0
cost SMS records                     1
```

The receipt test captures exactly `dedupe_key=acepivot:<conversation>`, verifies
`acestop:` and `aceundo:` buttons, dispatches the captured `acestop:` through
`telegram_io._handle_callback` and `ace.telegram_action_handlers(CONVO)`, then
proves `held=true` and the next ACE decision is `stop: operator-held`.

Independent final reviews found no Critical, Important, or Minor findings:

```text
B5 Spec PASS / APPROVED
B8 Spec PASS / APPROVED
```

## Local verification

Environment: Python 3.12.13, `FORGE_MARCUS=0`, `PYTHONUTF8=1`.

```text
python -m unittest discover -s . -p "test_*.py" -q
Ran 310 tests
OK

python test_ace.py
Ran 76 tests
OK

python test_sms_guard.py
Ran 26 tests
OK

python test_dropship_skills.py
dropship skills self-check OK - 14 skills, 0 orphans

tracked Python AST parse
AST OK: 135 tracked Python files

node "forge rei/deploy/valjsx.js" "forge rei/ace.jsx"
OK

git diff --check
clean

git status --short --branch
main...origin/main, clean
```

## Post-fix isolated box harness

Latest production-vault CONFIG and deterministic probe:

```text
classifier=<scratch tracked seller_classify.py>
legacyDraftOverride=true
replyRubric source=vault bytes=10713
playbook source=vault bytes=18822
degradedPrompt=false
priceMissed=0 priceTotal=14
denialFalsePositives=0
```

The scenario chain did not complete. Anthropic returned HTTP 400, credit balance
too low, during screening, drafting, and `legit_check`. Safety failed closed:

```text
SENT_COUNT 0
```

Fresh continuation recheck at 8 PM ET produced the same Anthropic HTTP 400.
Because the run was outside the configured 9 AM-8 PM send window, the final
pivot gate reported `send_hours` before `legit_check`; this is expected
fail-closed behavior and is not scenario acceptance. The deterministic probe
remained `priceMissed=0/14`, `denialFalsePositives=0`, with non-degraded vault
skills.

The deterministic decision layer did classify both scenario price turns as
`PRICE` and chose `pivot`, but the guard rejected those pivots when `legit_check`
could not run. Therefore this run is not acceptance evidence for:

- successful Claude screening and fact population;
- scenario A's successful seller reply sequence before its price pivot;
- generated-draft assigned-fact adherence and non-reask behavior;
- successful gated sends, call pivot, receipt delivery, or call-ready card
  across the complete live-model chain.

Restore Anthropic credits and rerun the complete isolated harness. Do not infer
full scenario acceptance from deterministic probes.

If that harness passes and the operator later enables a capped rollout, watch
these first-week signals:

- PRICE pivots: correct trigger rate and false-positive rate;
- fact-adherence rejects/retries and any known-fact re-ask;
- central gate blocks grouped by reason, especially ledger dedupe and legitimacy;
- call-ready acknowledgement latency and unanswered post-pivot inbound age;
- duplicate touches, daily-cap usage, holds/undos, and any price-scrub fallback.

## Sixteen-hop audit

| Hop | Result |
|---|---|
| 1. GHL inbound search | Partial: fake GHL seam locally; live search not exercised against a test contact. |
| 2. Scout sweep | Verified locally. |
| 3. Scout handoff | Verified with connector-equivalent callback wiring; live callback execution not exercised. |
| 4. Marcus screening | Verified with deterministic model transport; real Claude blocked by credit. |
| 5. Screening to conversation | Verified locally with real state engine; live bridge not exercised. |
| 6. ACE decision | Verified for reply/pivot/escalate/stop, thresholds, and kill switches. |
| 7. Marcus draft | Deterministic adherence verified; real Claude blocked by credit. |
| 8. Price scrub | Verified; no price/offer can leave by SMS. |
| 9. Central SMS gate | Verified, including exact real-ledger duplicate block. |
| 10. Send and ledger record | Verified with real engine/gates and captured GHL POST; live POST not exercised. |
| 11. Conversation ledgers | Verified. |
| 12. Call card | Persistence/dedupe verified; live Telegram delivery not exercised. |
| 13. Receipt and kill switches | Exact generated receipt/callback/hold path verified without live Telegram transport. |
| 14. Operator acknowledgement | Verified locally; live tap not exercised. |
| 15. Atlas underwriting | Deterministic integration verified; real model output remains blocked. |
| 16. Digest | Verified locally and live endpoint returns 200. |

## Live deployment and safety state

The latest production callback-factory source was present on the box and the
service was active after deployment.

```text
forge-reios                           active
GET /api/ace/status                  200
GET /api/ace/digest                  200
GET /api/ace/callready               200
GET /api/autopilot/status            200
GET /api/marcus/status               200
GET /api/test-mode                   200
GET /.env                            404
GET /ALL_KEYS.env                    404
GET /forge%20rei/.env                404

ace.mode                             off
ace.sentToday                        0
ace.degradedPrompt                   false
autopilot.enabled                    false
autopilot.sentToday                  0
test_mode.enabled                    false
test_mode.phones                     []
test_mode.envPhones                  []
```

## Claude Code consultation

Claude Code was consulted read-only with `Read,Grep,Glob` and plan-only
permissions (Sonnet session `18c1e583-9ff7-45b2-bf01-e49003d55330`). It agreed
that B1-B6/B9 were implemented, identified B3 ratification and B7 as unresolved
policy decisions, and did not accept the live Claude-dependent scenario without
credits. Its review cost was approximately $0.256.

## Definition-of-done gaps

The task is not fully complete until both external decisions are resolved:

1. Operator records approval or rejection of B3 option (b) and the B7
   operator-only 2-hour re-ping recommendation.
2. Anthropic credits are restored and the full isolated scenario harness passes
   every generated-draft, send, pivot, call-ready, and no-reask acceptance.

No reusable agent judgment skill was changed. The reusable lessons here are
code-test patterns (exercise the real production seam and mutation-kill
false-pass paths), not Marcus/Scout/Atlas operating judgment, so they do not
belong in a learned agent playbook.
