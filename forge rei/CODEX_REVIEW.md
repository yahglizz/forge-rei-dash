# FORGE REI OS — Codex Debug/Test Brief

You are reviewing a **live, 24/7, money-making** real-estate-wholesaling AI control center.
Treat every safety gate as load-bearing. Goal: **find every bug, wiring gap, and bypassable
gate, then FIX them** (additive diffs only) — this file is what you read first and re-read
whenever you're unsure what "correct" means here. If a decision in this file conflicts with
what you find in the code, the code + its tests are ground truth for CURRENT behavior; this
file is ground truth for INTENDED behavior. Flag the conflict, don't silently pick one.

## What this is
Python stdlib connector (`connector.py`, port 7799, **NO framework**) + static React UI
(in-browser Babel via `@babel/standalone`, **NO build step**, all components are `window`
globals). Runs on one DigitalOcean box under systemd `forge-reios`. State = JSON files in
`marcus_state/` (atomic writes via `forge_atomic.atomic_write_json` + `threading.Lock`). Brain
= an Obsidian vault (git-backed) read/written by `brain_io.py`. Only the box runs the loops
(`FORGE_MARCUS=1`); the Mac runs UI-only (`FORGE_MARCUS=0`).

## CURRENT STATE — everything is BUILT, ALL new autonomy defaults OFF

### The one send gate
`sms_guard.py` — ONE `guard()` in front of every outbound SMS: TCPA 9–8 ET hours, daily cap +
pending reservations, dedupe, our-message filter, DNC/hard/soft-no, **price/offer scrub on
`autonomous=True`**, legit-check. Wired via injected `MARCUS.safety_check/safety_record/
safety_release` + `SCREENER.*` hooks, and directly in `handle_send_post` + `/api/reply/send`.
**Operator-bypass contract:** a MANUAL/operator send (`autonomous=False`) is NOT blocked by the
legit-check verdict, a legit-check outage, a missing Anthropic key (no SPOF), soft-no, or
clock-out — BUT DNC opt-out + 9–8 ET hours apply to EVERYONE. AUTONOMOUS sends
(`autonomous=True`) keep every single gate, no exceptions. Tests: `test_sms_guard.py` (10).

### ACE — Phases 1-5 all shipped, default mode `"off"`
`conversation_engine.py` (state machine NEW→ENGAGING→QUALIFYING→CALL_READY→HANDED_OFF|DEAD,
`next_question()`, `set_held()`) + `ace.py` (`decide()`/`consider()`/`apply()`, modes
off|shadow|supervised|full).
- **shadow**: `consider()` drafts ONE qualifying question into Marcus's approval inbox via
  `make_proposal_for` — no send.
- **supervised/full**: `apply()` auto-sends via `make_proposal_for` → `approve` → sms_guard.
  **LOCKED CONTRACT: `autonomous=True` in BOTH modes** — an ACE send never bypasses a gate; the
  ONLY difference between the two modes is the daily cap (`FORGE_ACE_CAP_SUPERVISED=3`,
  `FORGE_ACE_CAP_FULL=10`). Every auto-send gets a Telegram receipt with ⛔ Stop (`acestop`) /
  ↩ Undo (`aceundo`) — both call `ace.hold()` → `conversation_engine.set_held()`, and `decide()`
  checks the held flag before anything else fires.
- **call-ready queue (P4)**: on `state==CALL_READY`, `ace.call_ready_upsert()` builds a card
  (screening callPrep/pathToContract/redFlags/askingPrice + Atlas `deal_prep` anchors + ACE
  facts) into `marcus_state/call_ready.json`, pings Telegram once (📞 + ✅ ack →
  `ace.ack()` → `conversation_engine.set_state(HANDED_OFF)`), and surfaces a `call` task in
  `do_today.py`. Endpoints `/api/ace/{callready,ack,hold}`.
- **digest (P5)**: `ace.digest(days=1)` rolls the log into `/api/ace/digest`, feeds
  `do_today.py`'s `autonomy` block + the email digest, and `ace.jsx` (`AcePanel` — mode control
  + big kill button in Command Center; `AceStrip` — compact status on the Dashboard, hidden
  when mode is off).
- **Kill order, checked first in `decide()`, in this order:** mode `"off"` → `forge_ops.
  paused()` (clock-out) → terminal state (`HANDED_OFF`/`DEAD`) → per-thread `held` flag. Verify
  this order can't be reordered/skipped by any code path.
- Driver: `connector._ace_update_from_screening` — routes `shadow`→`consider`,
  `supervised`/`full`→`apply`, rides the existing Scout→Marcus screening bridge, no new loop.
- Tests: `test_ace.py` (30, including `AceKillSwitchInvariantTest` — mode-off/clock-out beats
  every other trigger in every mode).

### cost_tracker.py — new
Auto-captures Claude token spend at the two Anthropic call sites (`review_agent._claude`,
`marcus_engine._ai_draft`), auto-counts SMS at `sms_guard.record_success`, manual flat-monthly
entries (droplet, Telegram, etc.), monthly cap alert (80% warn / over-cap alert). Endpoints
`/api/cost/{status,manual,settings}`. UI: `cost.jsx` (Costs tab) + a 💸 chip on the Dashboard
header. Tests: `test_cost_tracker.py` (9).

### skill_forge.py — new
Registers as an `agent_bus` notifier; cheap keyword-shingle counting per broadcast (NOT a
Claude call per message). When a topic recurs across ≥2 agents or ≥8 mentions (rate-limited,
`FORGE_SKILLFORGE_INTERVAL_MIN`) and isn't already covered by an existing vault playbook or
`~/.claude/skills/` entry, ONE Claude call drafts a skill file → written to vault
`Skills/proposals/<pid>.md` via `brain_io.write_note` (git-committed = reversible). **Never
applied automatically** — `agent_bus` alert + Telegram buttons (`skillgo`/`skillno`) or the
Command Center card gate the adoption; only `skill_forge.approve()` writes the final
`Skills/<slug>.md`. Endpoints `/api/skillforge/{pending,act}`. Tests: `test_skill_forge.py`
(11, including "adopt writes exactly once" + "dismiss writes nothing").

### Brain-context fix
`marcus_engine._ai_draft` (the ONE drafter every reply path uses — taps, Speed-to-Lead,
autopilot, AND ace.apply's proposals) now injects `agent_context.brain_context()` per lead,
same pattern as `marcus_screening.py`/`deal_prep.py`. Verify this didn't silently break the
existing voice-scrub (`_scrub_voice`) ordering — scrub must still run AFTER the Claude call,
on the final text, unconditionally.

### Everything from before (still load-bearing, still in scope)
Heartbeat/watchdog (`forge_heartbeat.py`, `_watchdog_forever`, `/api/system/health`,
`system_health.jsx`, now also surfaced as a health dot on the Dashboard header), Do Today
strict + Went-Ghost + suppression (`legit_check.verdict` urgency, `send_ledger.
last_reply_msg_date`), Speed-to-Lead (`/api/reply/{draft,send}`, `mark_texted`),
brain/graphify per-lead injection (`agent_context.py` into `marcus_screening`, `deal_prep`,
`agency_agents` Dyson/Eco, and now `marcus_engine`).

## Architecture (read these first)
- `connector.py` — HTTP server. **GET** via the `ROUTES` dict (+ the `NO_CACHE` set); **POST**
  via the `do_POST` allowlist tuple + an `elif` dispatch chain. Boots agent instances (SCOUT,
  SCREENER, MARCUS, FOLLOWUP, DEAL_PREP) + background loop threads in `main()`.
- Agents: `scout_triage.py` (triage/tag/pipeline, auto), `marcus_screening.py` (call-ready
  screening reports, auto on hot lead), `deal_prep.py` (Atlas underwriting, auto),
  `marcus_engine.py` (SMS draft/classify/voice — the single drafter every path uses; legacy
  auto-responder OFF by default), `agency_agents.py` (Dyson/Eco).
- Autonomy + safety: `ace.py` + `conversation_engine.py` (see above, default OFF),
  `autopilot.py` (auto-sends re-engage bumps only, 8 gates, **OFF by default** — shares
  `send_ledger` with ACE so the two tiers can't double-text one thread), `legit_check.py`
  (Claude verdict `{legit, urgency, reason}`, reads the thread), `send_ledger.py` (anti-double-
  text + text-back suppression), `forge_ops.py` (master clock-out kill switch), `followup.py`
  (cadence bumps), `sms_guard.py` (the one send gate, see above).
- New this round: `cost_tracker.py`, `skill_forge.py` (see above).
- Infra: `agent_bus.py` (inter-agent messages, `register_notifier` — skill_forge taps this),
  `telegram_io.py` (alerts + tap-to-approve, two-factor auth, `set_actions` callback registry),
  `brain_io.py` + `agent_context.py` (vault read/search injected per-lead), `graphify_io.py`,
  `forge_heartbeat.py` (per-loop heartbeats) + `_watchdog_forever` in `connector.py`
  (silent-death Telegram alerting).
- UI: `FORGE REI OS.html` loads each `.jsx` before `app.jsx`. **Each `.jsx` MUST use unique
  hook aliases + uniquely-prefixed globals; NO computed JSX tags** (`<Icons[x] />`) — a
  violation is a white screen. `deploy/valjsx.js` catches both. New tabs this round: `cost.jsx`
  (Costs), `ace.jsx` (AcePanel in Command Center + AceStrip on Dashboard).

## Hard rules (must hold — flag ANY violation as a top-severity bug)
1. **Additive only** — don't remove features.
2. Every outward action (SMS/pipeline/ads) is gated behind operator approval EXCEPT the
   documented autonomous exceptions: Scout tags/pipeline (HOT-lead auto-tag/pipeline),
   autopilot re-engage bumps (operator opt-in), and ACE per its mode (never above `full`'s cap,
   never bypasses a gate — see the locked `autonomous=True` contract above).
3. Secrets live in `*.env` **outside** the web root and MUST 404 over HTTP.
4. `_is_our_message` filter: never reply to our own outreach (unless a deliberate ACE/re-engage
   `hint` is present, by design).
5. ACE + autopilot default OFF; `forge_ops.paused()` stops ALL autonomy instantly, in every mode.
6. Nothing autonomous ever quotes a price or makes an offer — enforced by `sms_guard`'s
   price/offer scrub on `autonomous=True`, the single central point, not a per-agent scrub.
7. `skill_forge` never writes into `~/.claude/skills/` or a final `vault/Skills/<name>.md`
   without an explicit operator tap (`approve()`); a proposal sitting in `Skills/proposals/`
   is inert.
8. `cost_tracker` telemetry must NEVER be able to break a Claude call or an SMS send — every
   tap site wraps it in try/except.

## Review + fix scope
1. **Wiring completeness**: every endpoint registered in ALL required places (`ROUTES`,
   `NO_CACHE`, and for POST the `do_POST` allowlist + an `elif` branch — including the NEW
   `/api/cost/*`, `/api/skillforge/*`, `/api/ace/{callready,ack,hold,digest}` endpoints). Every
   background loop started in `main()` and heartbeat-instrumented. `skill_forge.on_bus_message`
   registered via `agent_bus.register_notifier`. No import cycles. No UI `fetch`/`apiPost` call
   to an endpoint the backend doesn't serve, and no orphan backend endpoint the UI never calls.
2. **Safety-gate integrity**: map EVERY outbound SMS path — `/api/send`, `/api/reply/send`,
   `MARCUS.approve`/`_send`, `autopilot.maybe_send`, and **`ace.apply`** — and prove the full
   gate stack (legit, 9–8 ET hours, daily cap, `send_ledger` dedupe, `_is_our_message`,
   DNC/hard-no/soft-no, price/offer scrub, clock-out) cannot be bypassed on any of them. Prove
   `ace.apply` sets `autonomous=True` unconditionally in both supervised and full (grep for any
   path where it might not). Prove ACE never calls `ghl_post` directly.
3. **ACE correctness**: the kill-order in `decide()` (mode-off → clock-out → terminal/held →
   escalation triggers → reply); `apply()`'s cap check happens BEFORE drafting (not after a
   wasted Claude call); day-rollover math; the call-ready queue only pings Telegram ONCE per
   thread (not on every screening re-run); `ack()` actually flips state to `HANDED_OFF`.
4. **cost_tracker correctness**: token→USD math against the `PRICES` table (verify it's not
   stale vs actual Anthropic pricing — flag if so, don't silently "fix" pricing without
   verifying current rates), day-key rollover, cap-alert thresholds, manual entry validation
   (rejects non-numeric, `<=0` removes).
5. **skill_forge correctness**: detection never fires on skill_forge's own broadcasts (avoid a
   feedback loop); rate-limiting actually prevents proposal spam; `approve()`/`dismiss()` are
   idempotent (a second tap on an already-decided pid errors cleanly); the vault write path is
   git-committed (verify with `git log` in the vault after a test approve).
6. **Concurrency/atomicity**: every `marcus_state/*.json` store (including the two NEW ones —
   `cost_tracker.json`, `skill_forge.json`, `call_ready.json`) uses `forge_atomic` + a lock; no
   partial-write or lost-update races between loop threads and HTTP handler threads.
7. **Failure modes**: no agent loop can raise out; brain/graphify/telegram/cost-telemetry are
   all best-effort (wrapped, never break their caller); no API key → gates degrade safely.
8. **Dead code / half-wired features**: anything referenced but unreachable, or built but not
   loaded (a `.jsx` not in the HTML script list, an endpoint not in `ROUTES`/allowlist, a
   Telegram action not in `set_actions`).
9. **Voice consistency**: confirm `agent_context.brain_context` injection in `marcus_engine.
   _ai_draft` didn't break `_scrub_voice` — the scrub must run on every returned draft
   regardless of source (Claude or template fallback).

## How to run / validate / test
- Local UI-only: `FORGE_MARCUS=0 FORGE_PORT=7799 python3 connector.py` → http://localhost:7799
- Validate every file you touch: `python3 -c "import ast; ast.parse(open('FILE').read())"` per
  `.py`; `node deploy/valjsx.js FILE.jsx` per `.jsx` (real Babel transform + computed-tag scan).
- Run the full suite: `python3 -m unittest test_ace test_sms_guard test_cost_tracker
  test_skill_forge` — currently 62/62 green. Any regression is a top-severity finding.
- Deploy (gated, DO NOT run this yourself — see below): `./deploy/push.sh
  root@24.199.81.124` — validates every `.py`/`.jsx`, rsyncs, restarts, then SSH-verifies
  service active + `/api/health` + `/api/system/health` 200 + `marcus_state/heartbeats.json`
  404 + `ghl.env` not served.
- Health: `GET /api/system/health`. New reads: `GET /api/ace/status`, `/api/ace/digest`,
  `/api/ace/callready`, `/api/cost/status`, `/api/skillforge/pending` — all should be reachable
  and return `mode:"off"` / empty / zeroed defaults on a clean checkout.
- Box: `ssh -i ~/.ssh/forge_droplet root@24.199.81.124`, `systemctl status forge-reios`, logs
  `/opt/forge/connector.err.log`.

## Deliverables
1. A written, severity-ranked review: bugs, wiring gaps, any gate that can be bypassed, race
   conditions, dead code. Cite exact `file:line`.
2. **Fix everything you find** as additive diffs — no feature removal, no weakening of an
   approval path, no loosening of the `autonomous=True` ACE contract, no relaxing the
   skill_forge approval gate.
3. A test checklist run against every safety gate (DNC stop, 9–8 hours, daily cap, clock-out,
   `_is_our_message`, price/offer scrub, ACE kill-order, skill_forge no-write-without-approval)
   with actual results, not assumptions.
4. Confirmation every new/edited file passes `ast.parse` + `valjsx`, and the full test suite
   (62 baseline + anything you add) is green. Paste the run output.
5. Confirm the post-fix defaults are unchanged: ACE mode `"off"`, no cap consumed, no Telegram
   sends fired, no skill_forge proposal auto-applied, cost_tracker untouched by your test run
   (or reset it if your testing incremented counters).

**Do NOT** flip any autonomy mode on, send a real SMS, rotate keys, or push to the box —
`./deploy/push.sh` requires the operator's explicit go-ahead. Stop after validation and report
what's ready to deploy.
