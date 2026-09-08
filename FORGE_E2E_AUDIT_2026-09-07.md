# FORGE focused audit — 2026-09-07

Scope intentionally narrowed to release-blocking correctness, approval safety, and hidden UI failures. This is not the 74-screen UI sweep; unverified controls remain **Unknown**.

## Baseline

| Check | Result | Evidence |
|---|---|---|
| Python test suites | **31 pass / 2 fail** | `test_e2e_pipeline.py`, `test_marcus_filters.py` fail; the other 31 `test_*.py` suites pass. |
| Local dashboard | **WORKS** | `GET /` → `200`. Started with `FORGE_MARCUS=0`; background contact loops stayed off. |
| Focused GET smoke | **52/53 critical, 21/21 connected warnings, 4/4 secret paths blocked** | `deploy/live_smoke.py --json` against localhost. |
| Approval/autonomy regression checks | **PASS** | `test_autopilot_routes.py`, `test_e2e_pipeline.py` safety cases other than the reason-label assertion, `test_sms_guard.py`, and `test_optout_hardening.py` pass. |
| JSX static validation | **Unknown this pass** | Baseline in the supplied task says it passed; not rerun because no JSX changed. |
| Browser page/control sweep | **Unknown** | Deferred by request for a short, main-issues audit. |

## Fix order

| Priority | Surface | Verdict | Evidence / root cause | Smallest root fix |
|---|---|---|---|---|
| P0 | REI seller opt-out classification | **BROKEN regression** | `test_e2e_pipeline.py:test_explicit_optout_is_dead_grade_even_without_stop_keyword` fails: the deterministic record is correctly `dead`, but `_rule_score()` takes the `cls == "DNC"` branch and emits `"said stop / do not contact"`, which omits the required `opt-out` compliance reason. This makes a removal demand indistinguishable in the audit trail. | In `scout_triage.py:_rule_score`, make the DNC reason include `opt-out` (for example `"opt-out / said stop or do not contact"`). The outcome and approval gates stay unchanged. Re-run that test. |
| P1 | Marcus vault skill-source metadata | **BROKEN on macOS** | `test_marcus_filters.py:test_vault_skill_overrides_matching_repo_seed` compares `/var/...` with `/private/var/...`. `Path.resolve()` returns the physical macOS path while the test's supplied path retains its spelling. The chosen vault override itself works; the report is unstable. | Normalize the metadata path and test expectation through the same canonical representation, preferably the existing `Path.resolve()` boundary. Do not alter vault precedence. Re-run the one test. |
| P1 | REI Daily Non-Negotiables | **HIDDEN-FAIL** | `pages.jsx:1101` and `pages.jsx:1110` use raw `fetch` plus empty catches. A GET failure leaves the card loading forever; a POST failure clears `busy` but shows no error. `api.jsx` already provides `apiGet` / `apiPost`, which reject non-200 and `{error}` responses. | Replace both raw calls with the existing helpers and add one component-local error state/error row. No new abstraction. Verify failed GET and POST render a readable error, then a successful POST updates the counter. |
| P1 | Deal Calculator rates | **HIDDEN-FAIL** | `toolkit_calc.jsx:84` silently drops `/api/toolkit/calc/config` failure. The surrounding evaluator also intentionally leaves panels empty when its POST fails. That makes bad config and unavailable evaluation look like valid blank data. | Keep the existing `apiPost`; surface one visible calculator error/status for config, evaluation, and rate-save failures. Preserve the current calculation behavior and no-data state. |
| P1 | Agency n8n Workflows | **MOCK-UNLABELED / configuration broken** | Local startup logged `n8n 404: ... No workspace here`; `agency_workflows_io.list_workflows()` then supplies `_MOCK_WORKFLOWS`, but retains `connection.connected:true` and `source:"live"`. `agency_workflows.jsx:WfConnectionCard` consequently displays the mock catalog as connected live data. | Correct the n8n base URL/workspace configuration. In the fallback branch, return connection state `connected:false`, `source:"mock"`, plus the sanitized failure detail, so the existing UI marks it honestly. Do not attempt a workflow push during verification. |
| P2 | System Health local smoke | **ENVIRONMENTAL / actionable** | `/api/system/health` returns `200`, `active:false`, no red loops, but `diskOk:false` because the local volume is `98.0%` used with `5,017,817,088` bytes free. Therefore `live_smoke.py` correctly fails this critical probe. | Free local disk space or run the smoke on a volume below the existing `<92%` threshold. Do not weaken the disk alarm merely to make local smoke green. Production status is **Unknown**; it was not contacted. |
| P2 | Agency portal clipboard copy | **ACCEPTED** | `agency.jsx:135` suppresses clipboard permission failures after a portal link is generated. The generated link remains in component state and the explicit Copy action has a prompt fallback. | No change now. Add user feedback only if operators report this as a workflow problem. |

## Do not change

- Approval gates, agent autonomy, or Marcus's no-price-by-text guard.
- Labeled mock/unconfigured integrations.
- Portal-handler isolation and secret-path blocking.
- Disk threshold: it is reporting a real host-capacity condition.

## Verification after the focused fixes

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
python3 test_e2e_pipeline.py
python3 test_marcus_filters.py
node deploy/valjsx.js pages.jsx toolkit_calc.jsx
python3 deploy/live_smoke.py --json
```

The final smoke is expected to remain red until the local disk is below 92%; verify the production box separately, read-only, before any deploy.
