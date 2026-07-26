# FORGE dashboard audit — 2026-07-26

## Verdict

**Operational readiness: 5/10.** The dashboard loads, the four workspaces switch correctly, the client code compiles, and most automated coverage passes. It is **not fully functional or production-ready** because visible features are incomplete, the full test command is red, documentation conflicts with the product, and write-capable routes lack application-level protection.

This was a read-only audit. No contact, message, pipeline, contract, ad, or database action was executed. Browser testing used a loop-disabled local connector; Daycare was checked only through its sign-in gate.

## What was tested

- **Static UI:** all 59 desktop/mobile JSX files passed the project's Babel and computed-JSX-tag validator.
- **Backend:** all 111 Python files parsed with AST validation; 205 literal UI API paths map to registered backend paths.
- **Automated tests:** `FORGE_MARCUS=0 python3 -m unittest discover -s . -p 'test_*.py' -v` ran 225 tests: **223 passed, 1 failed, 1 discovery error**.
- **Browser smoke test:** Mission Control loaded with zero browser errors; REI, Agency, Daycare, and Dropship profile-switch buttons all worked. REI Properties was clicked and confirmed to be a placeholder.
- **Second opinions:** three independent code/doc audits and one evidence-only Claude review.

## Functional scorecard — 1 through 10

1. **Application load and routing — 8/10**
   - The static app loads and all four workspace shells render: REI, Agency, Daycare, and Dropship.
   - No browser JavaScript errors were recorded in the smoke pass.

2. **Workspace switching and navigation — 7/10**
   - The profile menu switches among all four workspaces correctly.
   - Some visible navigation entries are knowingly not real features; see item 7.

3. **REI operations — 7/10**
   - Dashboard, leads, conversations, pipeline, contracts, calculator, buyers, blasts, analytics, brain, system health, costs, and agent surfaces are implemented.
   - High-risk actions were deliberately not clicked because this connector read real business data and the audit had no authorization to send/change anything.

4. **Agency operations — 6/10**
   - Client, request, workflow, approval, call-center, Meta/social, and planning surfaces are routed and load.
   - This audit did not create clients, approvals, deploys, ads, or external actions. Meta/n8n setup is intentionally unavailable until environment configuration exists.

5. **Daycare operations — 5/10**
   - The management sign-in gate works and the protected workspace navigation is present.
   - Credentialed screens were not tested. A GET endpoint may auto-create child records, which is unsafe for a read request; see P1.

6. **Dropship operations — 5/10**
   - Dashboard and products/watch/orders/inventory/suppliers/ads/customers/analytics/connections routes are present and the dashboard clearly reports unwired systems.
   - Shopify, AutoDS, ad, Klaviyo, TikTok, and AfterShip functionality is unavailable until configured; several are explicitly “not built yet.”

7. **Visible controls and feature completeness — 3/10**
   - Confirmed nonfunctional/incomplete controls: global Search/Command-K, the non-Daycare notification bell, REI Properties/Marketing/Settings, and Daycare Meals/Calendar.
   - REI Properties was browser-tested and displays “Properties is coming online.” Do not present these as live features.

8. **Agent governance and safety — 4/10**
   - The core proposal/approval model has strong tests, including SMS price and safety guards.
   - A persisted Marcus auto-send toggle conflicts with the stated “every outward action needs approval” rule. Lock it behind an explicit, documented exception or remove it.

9. **Security and data integrity — 2/10**
   - The main connector has no application-level authentication, CSRF, or origin protection while exposing write operations (SMS, contracts, pipeline changes, settings, and auto-send control). The private network is its only boundary.
   - The client portal places bearer tokens in URLs without `no-store`/`Referrer-Policy` protection. Generic POST bodies are unbounded and generic errors echo internals.

10. **Quality, tests, and documentation — 4/10**
   - Static validation is clean and 223 automated tests passed.
   - The full suite is not green: a Scout test fake is stale after the `model=` call addition, and `test_daycare_blast.py` exits during import, producing a discovery error despite its internal checks passing.
   - Multiple source-of-truth documents describe the wrong product/agent roster or unsafe behavior.

## Fix list, ranked

### P0 — fix before any broader access

1. **Protect every dashboard write route with real authentication and CSRF/origin controls.**
   - Evidence: `forge rei/connector.py:2895-3029`, `forge rei/PRODUCTION_CHECKLIST.md:38-43`.
   - Minimum: keep port 7799 private and enforce authenticated reverse-proxy/SSO access before widening reachability. Do not expose this connector directly.

2. **Remove credentials from portal URLs and revoke/rotate any token that may have been exposed.**
   - Evidence: `forge rei/agency_portal_io.py:117-128`, `forge rei/connector.py:4528-4533`.
   - Use a fragment/session exchange, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and rate limiting.

### P1 — correctness and policy

3. **Make the Marcus auto-send toggle obey the approval policy.**
   - Evidence: `forge rei/marcus_engine.py:885-900`, `forge rei/RUNBOOK.md:82-85`.
   - The current persisted toggle can bypass the stated approval gate.

4. **Make daycare pending-family retrieval read-only, or change it to an explicit approved POST.**
   - Evidence: `forge rei/connector.py:3623-3644` writes child records from a GET by default.
   - GET writes can be triggered by refreshes, prefetchers, and crawlers; they also contradict proposal-only expectations.

5. **Repair the test suite so its documented full command is green.**
   - Evidence: `forge rei/test_e2e_pipeline.py:138` fake Claude callback lacks `model`/`**kwargs`; `forge rei/scout_triage.py:456` now passes `model=HAIKU_MODEL`.
   - Convert `forge rei/test_daycare_blast.py` into a proper unittest module (no import-time `SystemExit`).

6. **Update false/contradictory operational docs.**
   - `CONNECT.md` says the API is read-only even though it can write.
   - Root `AGENTS.md`/`DASHBOARD.md` say three businesses/eight agents with Nora/Nova active; the dashboard has four workspaces and Nora/Nova are merged.
   - `forge-marcus/README.md` weakens the unconditional no-price-by-text policy.
   - `forge-daycare/README.md` names retired/nonexistent Nora/Nova code; `NORTH_STAR.md` retains retired key/cadence references.

### P2 — harden and finish what is advertised

7. **Cap and validate generic/dropship JSON requests; never return raw exception strings.**
   - Evidence: `forge rei/connector.py:3024-3029`, `4298-4303`, `3480`, `4439`.

8. **Lock the connector response cache.**
   - Evidence: `forge rei/connector.py:4422-4432` mutates shared cache state under `ThreadingHTTPServer` without a lock.

9. **Either implement or hide/label unfinished visible controls.**
   - Global search/Command-K: `forge rei/shell.jsx:118-122`.
   - Bell is a no-op outside Daycare: `forge rei/shell.jsx:141-144`.
   - REI placeholders: `forge rei/app.jsx:12,23,28` and `forge rei/pages.jsx:2052-2064`.
   - Daycare deferred pages: `forge rei/daycare.jsx:250-257`.

10. **Replace stale fake agent roster/status copy.**
    - Evidence: `forge rei/data.jsx:80-88`, `forge rei/dashboard.jsx:315-339`, `forge rei/agents_hub.jsx:3-5`.
    - The UI shows old “soon” agents rather than the current roster.

## Test limitations

- No live production-server or authenticated Daycare workflow was tested.
- No destructive/outbound control was clicked: approve/send, pipeline move, contract send, payments, ad launch, create/delete, or agent run.
- Passing static checks does not prove integration credentials, vendor APIs, permission policies, or production deployment behavior.

## Suggested repair order

1. P0 access/token fixes.
2. Auto-send and GET-write policy decisions.
3. Repair the two test failures and rerun the full suite.
4. Reconcile docs and hide/label incomplete UI.
5. Run an authenticated staging E2E pass with disposable test accounts and explicit operator approval.
