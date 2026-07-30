# Wholesale Autopilot Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix and verify every mandatory defect and unfinished wiring item in `CODEX_WHOLESALE_AUTOPILOT_TASK.md` without enabling live ACE or test mode.

**Architecture:** Move seller classification into a tracked pure module, keep Marcus as the integration boundary, and make prompt health explicit through status APIs. Keep ACE's one-pivot state machine intact while gating broad READY signals on three known facts and requiring qualifying drafts to target the selected missing fact. Expose the legacy follow-up autopilot through explicit HTTP controls and keep nurture check-backs approval-only, matching canonical autonomy policy.

**Tech Stack:** Python 3.12 standard library, `unittest`, React JSX globals, existing `connector.py` HTTP router, isolated remote Python harness.

## Global Constraints

- Never state, negotiate, hint at, or invent a price or offer in seller SMS.
- Do not arm ACE or autopilot on the live box; finish with `ace.mode() == "off"` and an empty test whitelist.
- Make additive edits and preserve existing manual/approval paths.
- Do not read, print, commit, or expose secret values.
- Write each regression test first and observe the expected failure before production edits.
- Validate Python with `ast.parse`, JSX with `node deploy/valjsx.js`, and run full test discovery before deploy.

---

### Task 1: Version-Controlled Seller Classifier

**Files:**
- Create: `forge rei/seller_classify.py`
- Create: `forge rei/test_marcus_filters.py`
- Modify: `forge rei/marcus_engine.py`

**Interfaces:**
- Produces: `seller_classify.classify(body: str) -> str`, `seller_classify.draft_reply(first: str, cls: str) -> str`, and `marcus_engine.classifier_source() -> dict`.
- Preserves: optional external `draft_reply` override only; classification always resolves to the tracked module.

- [ ] Add table-driven tests for all 14 `PRICE_ASKS`, word-boundary negatives such as `surprise`, core DNC/HELP/NRN/READY cases, and an assertion that `inspect.getsourcefile(marcus_engine.classify)` is inside `forge rei`.
- [ ] Run `python -m unittest -v test_marcus_filters` and confirm the new cases fail because `seller_classify` and source metadata do not exist.
- [ ] Implement compiled phrase regexes with boundaries for `ballpark`, `range`, `numbers`, `what number`, `your best`, `most you can`, `worth to you`, `what are you offering`, and `what were you thinking`.
- [ ] Import the tracked classifier unconditionally from `marcus_engine.py`, retain the external toolkit only as an optional legacy draft override, log the selected source once, and add classifier metadata to `MarcusEngine.status()`.
- [ ] Re-run `python -m unittest -v test_marcus_filters` and confirm all classifier cases pass.

### Task 2: Identity-Denial Filter

**Files:**
- Modify: `forge rei/test_marcus_filters.py`
- Modify: `forge rei/marcus_engine.py`

**Interfaces:**
- Preserves: `_is_denial(body: str) -> bool`.

- [ ] Add false-positive tests for every `NOT_DENIALS` harness case and true-positive tests for `wrong number`, `im not the owner`, `im not the seller`, `i dont own it`, `never owned it`, `thats not me`, and `thats not my house anymore`.
- [ ] Run the focused denial tests and confirm the seven ordinary seller sentences fail.
- [ ] Replace the catch-all `im not <word>` regex with explicit identity/ownership denial shapes while retaining the existing fixed phrases.
- [ ] Re-run the focused tests and the whole `test_marcus_filters` module.

### Task 3: Prompt Skill Fallback and Health

**Files:**
- Modify: `forge rei/test_marcus_filters.py`
- Modify: `forge rei/marcus_engine.py`
- Modify: `forge rei/ace.py`
- Modify: `forge rei/ace.jsx`

**Interfaces:**
- Produces: `marcus_engine.skill_sources() -> dict` with `path`, `source`, and `bytes` for the reply rubric and playbook components.
- Adds: `ace.status()["promptHealth"]` and `ace.status()["degradedPrompt"]`.

- [ ] Add tests that redirect the vault to a missing directory and assert non-zero seed-loaded rubric/playbook bytes and repo source paths.
- [ ] Run the tests and confirm the current vault-only loaders return empty strings.
- [ ] Resolve seed files from `forge-marcus/skills` first and overlay matching vault files when present; cache on resolved path and mtime.
- [ ] Expose source paths and byte counts through Marcus and ACE status without exposing file contents.
- [ ] Render a compact `DEGRADED PROMPT` status chip in `AcePanel` whenever any required skill has zero bytes.
- [ ] Re-run unit tests and validate `ace.jsx` with `node deploy/valjsx.js "forge rei/ace.jsx"`.

### Task 4: ACE READY Policy and Fact-Adherent Drafting

**Files:**
- Modify: `forge rei/test_ace.py`
- Modify: `forge rei/ace.py`

**Interfaces:**
- READY policy: pivot only after at least three known facts; PRICE pivots immediately.
- Drafting contract: every qualifying hint names the assigned fact and includes all already-known fact values as explicit do-not-reask context.

- [ ] Add decision tests proving a READY opener with fewer than three facts replies, READY at three facts pivots, and PRICE with zero facts pivots.
- [ ] Add execution tests proving the drafting hint carries known values and the assigned fact.
- [ ] Run the focused tests and observe policy/context failures.
- [ ] Add a named `READY_MIN_FACTS = 3` threshold and apply it only to READY.
- [ ] Build the hint from the selected missing fact plus report/conversation known values; do not mark a reply successful if the draft fails the assigned-fact check.
- [ ] Re-run focused and full `test_ace` tests.

### Task 5: Send-Ledger and Telegram Kill-Switch Integration

**Files:**
- Modify: `forge rei/test_ace.py`
- Modify: `forge rei/test_sms_guard.py`
- Create or modify: `forge rei/test_telegram_ace.py`

**Interfaces:**
- Verifies: two guarded autonomous sends inside the dedupe window block the second with `gate == "send_ledger"`.
- Verifies: `acestop:` and `aceundo:` callback payloads dispatch to `ace.hold()` and make the thread stop.

- [ ] Add a real temporary-ledger two-send test without mocking `touched_within`.
- [ ] Run it and confirm the existing mocked coverage does not satisfy the integration case.
- [ ] Add callback-dispatch tests using the real action parser with injected action handlers and a temporary conversation store.
- [ ] Make only minimal production changes if the integration tests expose a wiring defect.
- [ ] Re-run all gate and callback tests.

### Task 6: Legacy Autopilot HTTP and UI Wiring

**Files:**
- Modify: `forge rei/connector.py`
- Modify: `forge rei/ace.jsx`
- Create: `forge rei/test_autopilot_routes.py`

**Interfaces:**
- Adds: `GET /api/autopilot/status`.
- Adds: `POST /api/autopilot/toggle` with `{enabled: bool}`.

- [ ] Add route-table and handler tests proving status delegates to `autopilot.status()` and toggle delegates to `autopilot.set_enabled()`.
- [ ] Run the tests and confirm both HTTP routes are absent.
- [ ] Add the GET route, POST allowlist entry, and POST handler with the existing same-origin/private-dashboard protections.
- [ ] Add a labeled toggle in `AcePanel` that displays enabled/off state independently from ACE mode.
- [ ] Re-run route tests and validate JSX.

### Task 7: Nurture Check-Back Policy Verification

**Files:**
- Create: `forge rei/test_followup_checkbacks.py`
- Modify only if needed: `forge rei/followup.py`

**Interfaces:**
- Preserves canonical behavior: due nurture check-backs create an approval-required alert and never call `autopilot.maybe_send`.

- [ ] Add a due-check-back test that asserts the record is flagged, the bus alert is posted, and no autonomous send function is invoked.
- [ ] Run the test; if current behavior passes, record B9 as verified rather than changing policy.
- [ ] If it fails, make the minimal change needed to restore approval-only behavior and re-run.

### Task 8: Integration, Harness, Deploy, and Live Safety Audit

**Files:**
- Update: `CODEX_WHOLESALE_AUTOPILOT_TASK.md` or a dated completion report with evidence and B7 recommendation.
- Update: the appropriate wholesale skill only if a reusable pattern was learned.

**Interfaces:**
- Post-fix harness must report 14/14 PRICE, zero denial false positives, non-zero skill bytes, scenario-A price pivot, and no repeated known-fact question.

- [ ] Review every subagent diff against the hard rules and inspect for overlapping edits.
- [ ] Run targeted modules, then `FORGE_MARCUS=0 python -m unittest discover -s . -p "test_*.py" -v`.
- [ ] Run the task brief's three explicit acceptance scripts.
- [ ] Run `ast.parse` on every changed Python file and `node deploy/valjsx.js "forge rei/ace.jsx"`.
- [ ] Copy the harness to `/tmp`, run the production-like isolated post-fix harness, and save its structured output as completion evidence.
- [ ] Record B7 recommendation: keep seller silence, send an operator-only Telegram re-ping after new inbound remains unacknowledged for two hours; do not implement until the operator approves the interval.
- [ ] Commit and push only after all verification is green; wait for autopull, then verify service active, required endpoints return 200, env URLs return 404, ACE mode is off, and test whitelist is empty.
