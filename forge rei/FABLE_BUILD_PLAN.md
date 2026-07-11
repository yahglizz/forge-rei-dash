# FABLE BUILD PLAN — FORGE REI OS (audit + cost tracker + skill_forge + ACE P3-5)

**Read first, in order:** `../CLAUDE.md` (root rules), `CLAUDE.md` (this folder — file map +
live state + stay-on-track protocol), `CODEX_REVIEW.md` (architecture). This plan is the
concrete spec; the CLAUDE.md files are the binding rules. When a gate/scope is unclear, grep
the function + read `test_ace.py`/`test_sms_guard.py` — never guess.

**Two operator decisions are LOCKED (do not re-open):**
1. ACE supervised AND full both run the **full gate stack** (`autonomous=True` always for ACE
   auto-sends). The ONLY difference is the daily cap + receipt cadence. A bot never bypasses a
   gate. (`autonomous=False` stays reserved for the operator's own manual taps.)
2. Cost tracker = auto-capture Claude tokens + auto-count GHL SMS + manual flat monthly entries.

**Hard rules (from CLAUDE.md — never violate):** additive only; every outward action gated
except documented exceptions; secrets in `*.env` outside web root, 404 over HTTP, never rotate;
never flip ACE/autopilot to non-off on the live box; never send a real SMS during dev; never let
anything autonomous quote a price; validate every `.py` with `ast.parse` + every `.jsx` with
`node deploy/valjsx.js`; deploy ONLY via gated `./deploy/push.sh` with the operator's go-ahead.
**Do not deploy — stop after validation and report what's ready.**

---

## Audit result (already done — context, not work)

Dashboard is clean: no white-screen/computed-tag/alias collisions, no dead or orphan endpoints,
polling cleanup correct, all 24 `.jsx` loaded in order. So Part 1 is mostly ADD, not fix. Real
gaps: (a) `/api/system/health` is buried in a secondary tab — no at-a-glance health on the main
dashboard; (b) no money view exists; (c) minor: goals fetch has no loading state; redundant
`/api/agency/*` polls (soft-mitigated by the 45s cache).

---

## PART 1 — Dashboard polish (additive)
- **Health dot on the main dashboard.** Add a small green/amber/red fleet indicator to the
  dashboard header/KPI row, fed by `/api/system/health` (handler `api_system_health`,
  connector.py:381). Tap → the existing System Health tab. Don't move/rename the tab (additive).
- **Loading state** on the goals fetch (`pages.jsx:1362-1371`) — show the existing `LoadingRow`
  (exported from `api.jsx:107`) while in flight.
- **Dedupe polls (optional, low priority):** consolidate the repeated `/api/agency/*` 20s polls
  behind one shared hook. Skip if it risks regressions — it's already cache-mitigated.
- Do NOT touch any ACE/autopilot mode switch or any send-path default.

## PART 2 — Cost tracker (new `cost_tracker.py` + `cost.jsx`)
**Store:** copy the `ace.py` shape exactly (threading.Lock + `forge_atomic.atomic_write_json`,
`marcus_state/cost_tracker.json`, ET-day rollover). Reference: `ace.py:16-131`.
- **Auto Claude:** in `review_agent._claude()` (review_agent.py:46-73) the Anthropic response
  carries `usage.input_tokens`/`output_tokens` and is discarded at line 73. Capture it: after the
  response, call `cost_tracker.record_anthropic(model, in_tok, out_tok)`. Hardcode current
  per-model $/Mtok rates in a dict (Sonnet/Opus/Haiku) so it converts tokens→USD. Best-effort,
  never let it break a Claude call (wrap in try/except).
- **Auto SMS:** every successful send already funnels through `sms_guard.record_success()`
  (sms_guard.py:234-259). Add a `cost_tracker.record_sms(1)` call there. Manual $/segment rate in
  the store (operator sets once; default a sane GHL rate).
- **Manual flat:** `POST /api/cost/manual {service, monthlyUSD, note}` → append to a `fixed` map
  (DigitalOcean droplet, Telegram, Retell if used). Mirror the `agency.jsx` form pattern (agInp
  style, apiPost, saving/err states).
- **Endpoints:** `GET /api/cost/status` (ROUTES + NO_CACHE) + `POST /api/cost/manual` (do_POST
  allowlist tuple + elif). Wiring recipe: ROUTES connector.py:1847-1930, NO_CACHE ~1934, allowlist
  ~2164-2228, elif ~2237-2362.
- **UI `cost.jsx`:** `window.CostPage`, unique alias `useStateCt`/`useEffectCt`, no computed tags,
  script tag in `FORGE REI OS.html` BEFORE `app.jsx`. Show: today + month-to-date total, per-
  service breakdown, a small trend, and a spend-cap alert (operator sets a monthly cap; turn the
  card amber/red past it). Surface a compact "spend MTD" number on the main dashboard too.
- **Digest (optional):** append a one-line cost summary to `do_today.py build()` (rides the 9am
  brief, no new loop). Pattern: do_today.py:241-261 + section collectors 95-189.
- Tests: token→USD math, SMS counter increment, manual entry persists, day rollover.

## PART 3 — skill_forge (new `skill_forge.py` + card in Command Center)
**Reuse (do not rebuild):** `brain_io.write_note(rel, content, reason)` auto-git-commits
(brain_io.py:129-145); `agent_bus.register_notifier(fn)` taps every learn() broadcast
(agent_bus.py:34-38); `agent_bus.send(...)` for proposals; Telegram approve buttons via
`telegram_io.set_actions({...})` + `<action>:<arg>` callbacks (telegram_io.py:333-338, 492-551);
`graphify_io.search()/context_for()` for cross-agent pattern lookup.
- **Detect:** register a notifier; accumulate learn()/encounter signals; flag a candidate when a
  pattern recurs across **≥2 agents or ≥N encounters** and is NOT already in an existing playbook
  or `~/.claude/skills/`. Use lightweight stats, not a Claude call per broadcast (Claude only to
  DRAFT once a candidate crosses threshold). Knobs: `FORGE_SKILLFORGE_MIN_AGENTS`,
  `FORGE_SKILLFORGE_MIN_ENCOUNTERS`, `FORGE_SKILLFORGE_INTERVAL_MIN`.
- **Propose, never auto-apply:** draft the skill markdown (match the `SKILL.md` frontmatter of
  `~/.claude/skills/forge-self-improving-agent/SKILL.md`). For a **vault playbook** upgrade, write
  it via `brain_io.write_note("Skills/proposed-<ts>-<name>.md", ...)` (git-committed → reversible).
  For a **`~/.claude/skills/` skill** (outside vault git), write ONLY to a staging proposal and
  require a tap — never write into `~/.claude/skills/` without approval.
- **Approve/dismiss:** `agent_bus.send("skill_forge","all","alert", ..., {"type":"skill_proposal",
  "pid":...})` → Telegram buttons `skillforge_approve:<pid>` / `skilldismiss:<pid>`. On approve:
  move the staged file into place + broadcast adoption. Register handlers in the connector's
  existing `telegram_io.set_actions({...})` block.
- **Self-improves:** log approved-vs-rejected, bias future proposals toward what got adopted.
- **Command Center card:** pending proposals + one-tap approve/dismiss (mirror the Marcus proposal
  card in `marcus.jsx`). New endpoints `GET /api/skillforge/pending`, `POST /api/skillforge/act`.
- Tests: detection threshold, NO write to `~/.claude/skills/` without approval, vault proposal is
  git-reversible.

## PART 3b — Brain/voice context gap (CLAUDE.md §4 fix — makes ACE "sound like me")
**Gap found:** `agent_context` (brain+graphify) is injected into Marcus-screening (372-377),
Atlas (308-313), Dyson/Eco (agency_agents.py:287-340) — but NOT into `marcus_engine._make_proposal`
(the drafter ACE sends through) or Scout. So ACE's autonomous texts currently draft with no brain
context. **Fix:** in `marcus_engine._make_proposal`, inject `agent_context.brain_context(seller_query
(...), header="RELEVANT BRAIN NOTES (voice, closing plays, seller psychology)")` into the draft
system prompt (same 3-line pattern as marcus_screening.py:372-377), best-effort. This fixes Marcus
proposals AND ACE drafts in one place. Confirm the voice-scrub (`_scrub_voice`) still runs after.

## PART 4 — ACE Phases 3-5 (default OFF; reuse the single `sms_guard` gate)
**P3 — supervised/full auto-send (ride the existing bridge, no new loop):**
- Add `ace.apply(conv_id, rec, report, convo, marcus, last_seller_msg)` mirroring `consider()`
  but on a `reply` decision it calls `marcus.approve(pid, draft)` (marcus_engine.py:631 → `_send`
  → `sms_guard.guard`). **Set `autonomous=True` for BOTH supervised and full** (locked decision).
- In `connector._ace_update_from_screening`, when `ace.mode()` is `supervised`/`full` call
  `ace.apply(...)` instead of `consider(...)`; `shadow` keeps `consider`; `off` no-ops.
- Separate cap from autopilot: `FORGE_ACE_CAP_SUPERVISED=3`, `FORGE_ACE_CAP_FULL=10`, tracked in
  `ace.json` under lock via `_bump_sent()` + a cap check before send; share `send_ledger` with
  autopilot so the two can't double-text one thread.
- Telegram receipt per send with inline **Stop this thread** (`acestop:<conv>` → `set_held(conv)`,
  which `decide()` already honors at ace.py:149) + **Undo** (`aceundo:<conv>`). Register in the
  connector's `set_actions`.
- `ace.jsx`: `window.AcePanel`, alias `useStateAce`, segmented off/shadow/supervised/full control
  → `POST /api/ace/mode`, no computed tags, script before `app.jsx`.
- Tests: cap enforced under lock, day rollover, stop-button sets held + decide() stops, undo,
  mode stays off by default, `autonomous=True` on both modes (price-scrub/legit/clock-out all fire).

**P4 — call-ready queue + escalation:**
- On `state==CALL_READY`, build an entry {screening callPrep/pathToContract/redFlags/score/
  askingPrice + `DEAL_PREP.get(contactId).prep.anchors` (deal_prep.py:446) + ACE facts} →
  `marcus_state/call_ready.json` (atomic+locked).
- Telegram "📞 Call-ready: {name}" + **✅ Got it** (`aceack:<conv>` → `set_state(conv,
  "HANDED_OFF")`) + `agent_bus` handoff.
- `do_today.py screenings()` already has a `call` kind + reads anchors (142-170) — add/ensure a
  call task appears for CALL_READY/HANDED_OFF, de-duped by convId.
- `GET /api/ace/callready`, `POST /api/ace/ack`. Dashboard "Call-Ready" card.

**P5 — autonomy observability:**
- `ace.digest(days=1)` summarizes `ace.json.log` (auto-sends, escalations, call-readies, blocks-
  by-reason). Append to `do_today.py build()` (rides the daily brief). `GET /api/ace/digest`.
- Dashboard "Autonomy" card: mode, sentToday/cap, last 10 sends + block reasons, call-ready count,
  and a visible **kill switch** (→ `POST /api/ace/mode {off}`; note `forge_ops.paused()` also halts
  everything instantly).
- **Invariant test (most important):** with `mode=off` OR `forge_ops.paused()`, `decide()` returns
  stop for EVERY other trigger combination (CALL_READY, max-replies, PRICE/READY, all-facts). This
  proves off/clock-out beat all.

---

## Verification (required before reporting done)
- `ast.parse` every `.py` touched; `node deploy/valjsx.js` every `.jsx` touched.
- Full suite green (paste): `test_ace.py`, `test_sms_guard.py`, new cost/skill_forge/ACE tests.
- Confirm post-change default state: ACE `mode="off"`, no cap consumed, no Telegram sends fired,
  skill_forge proposals QUEUED not applied, nothing written to `~/.claude/skills/` without a tap.
- **Do NOT run `./deploy/push.sh`.** Report a single "ready to deploy, pending go-ahead" list.

## Deliverable
Written report: (1) dashboard adds, (2) cost_tracker design + tests, (3) skill_forge design +
the §4 brain-context fix + tests, (4) ACE P3-5 implementation + tests, (5) the ready-to-deploy list.
