# FORGE REI OS — Working Notes for `forge rei/` (read ROOT first)

**Read `../CLAUDE.md` first.** That is the canonical operating manual — rules,
agent table, self-improvement loop, skills doctrine. This file is the **quick
reference + "I'm stuck" anchor** for anyone (Claude, Codex, Fable, a subagent)
actually working inside this folder. It does not restate the root file — it
points at what's true right now and where to verify it.

---

## If you're stuck, about to guess, or losing track of intent

Stop and re-read, in this order, before proceeding on an assumption:

1. `../CLAUDE.md` — hard rules + agent table (source of truth for policy).
2. This file — file map + current live state below.
3. `CODEX_REVIEW.md` (this folder) — most detailed, most current architecture +
   "CURRENT STATE" snapshot of what's actually shipped vs. planned.
4. The tests — `test_ace.py`, `test_sms_guard.py` are executable specs. If you're
   unsure what a gate is supposed to do, the test is the answer, not a guess.
5. The plan file (if one exists in `~/.claude/plans/`) for the phase you're on.

Never silently assume gate behavior, default mode, or approval-vs-autonomous
status — grep the actual function (`sms_guard.guard`, `ace.decide`,
`forge_ops.paused`) rather than inferring from a comment or a stale doc. Docs
drift; code + tests don't.

---

## File map

- `connector.py` — HTTP server. GET via `ROUTES` dict (+`NO_CACHE`); POST via
  `do_POST` allowlist tuple + `elif` dispatch. Boots agent instances + loop
  threads in `main()` (loops only run when `FORGE_MARCUS=1`).
- Agents: `scout_triage.py`, `marcus_screening.py`, `deal_prep.py`,
  `marcus_engine.py`, `agency_agents.py`.
- Autonomy + safety: `sms_guard.py` (the ONE central outbound-SMS gate),
  `conversation_engine.py` + `ace.py` (ACE, default OFF), `autopilot.py`
  (re-engage bumps, default OFF), `legit_check.py`, `send_ledger.py`,
  `forge_ops.py` (master clock-out).
- Infra: `agent_bus.py`, `telegram_io.py`, `brain_io.py` + `agent_context.py`,
  `graphify_io.py`, `forge_heartbeat.py`.
- UI: `FORGE REI OS.html` loads each `.jsx` before `app.jsx`. Every `.jsx` needs
  a unique hook alias + prefixed globals; no computed JSX tags (white screen).
- Tests: `test_ace.py`, `test_sms_guard.py`.
- `CODEX_REVIEW.md` — the living review brief; update it whenever what's "live"
  changes, so it and this file never drift from reality.

## Validate / deploy (non-negotiable)

```bash
python3 -c "import ast; ast.parse(open('FILE').read())"   # every .py you touch
node deploy/valjsx.js FILE.jsx                             # every .jsx you touch
./deploy/push.sh root@24.199.81.124                        # gated deploy + SSH health-verify
```
Local UI-only run: `FORGE_MARCUS=0 FORGE_PORT=7799 python3 connector.py`

## Current live state (verify against CODEX_REVIEW.md before trusting this)

- `sms_guard.guard()` is the single gate in front of every outbound SMS.
  Operator (`autonomous=False`) sends bypass legit-check/outage/soft-no/
  clock-out (no SPOF) but DNC + 9–8 ET hours block everyone.
- ACE (`conversation_engine.py` + `ace.py`) is default `mode="off"`. ALL FIVE
  phases built: state machine, shadow drafting, supervised/full auto-send
  (`ace.apply` — **autonomous=True in BOTH modes**, caps 3/10 per day, Telegram
  receipt + ⛔ stop/↩ undo hold taps), call-ready queue (`call_ready.json`,
  📞 ping + ✅ ack → HANDED_OFF, Do Today call task), autonomy digest
  (`/api/ace/digest`, Do Today + email block, AcePanel/AceStrip UI). Kill:
  Off mode, `forge_ops.paused()`, per-thread held — all checked FIRST.
- `autopilot.py` (re-engage bumps) is operator opt-in, default OFF.
- `cost_tracker.py`: auto Claude tokens (both call sites in `review_agent.
  _claude` + `marcus_engine._ai_draft`) + auto SMS count (`sms_guard.
  record_success`) + manual flat monthly; `/api/cost/*`, Costs tab, dashboard
  💸 chip, cap alert.
- `skill_forge.py`: bus-notifier pattern watcher → Claude-drafted skill
  PROPOSALS (vault `Skills/proposals/`, git-committed); adopt/dismiss via
  Telegram `skillgo/skillno` or the Command Center card. Never auto-applies.
- Marcus's drafter (`marcus_engine._ai_draft`) injects per-lead brain notes
  (`agent_context.brain_context`) — every draft path (taps, Speed-to-Lead,
  ACE) speaks with vault context + the voice scrub.
- **Seller-reply doctrine (all draft paths):** `_ai_draft` loads the decision rubric
  `Skills/seller-reply-playbook.md` in full (`_load_reply_rubric`, mtime-cached, injected
  FIRST so it's never truncated) + the voice playbook, and the system prompt enforces:
  adapt to the seller's actual message, drive to a quick call, **never a price/offer/number
  by text**. Code backstop `_no_price_over_text` (`_PRICE_RE`) runs on every draft (Claude +
  template) and swaps any leaked figure for `_PRICE_FALLBACK` (a call-pivot), logging a
  `price_guard` event. Approval gate unchanged — drafts are still proposals.
- **New-lead flag:** `_mark_seen`/`seen_contacts.jsonl` → first-ever proposal per contact
  sets `newLead:true` + bus `new_lead:true`; the Telegram ping headline gets 🆕.
- **Daily brief + recap:** `daily_brief.py` / `daily_recap.py` — box scheduler
  `_brief_scheduler_forever` ticks both (`_maybe_daily_brief` + `_maybe_daily_recap`),
  `/api/brief*` + `/api/recap*`, mobile More sheets.

## Hard rules (recap — full text in `../CLAUDE.md`)

1. Additive only, never remove a feature. 2. Every outward action gated behind
approval except the documented exceptions. 3. Secrets in `*.env` outside the
web root, must 404 over HTTP, never rotate without being told. 4. Never flip
ACE/autopilot to a non-off mode on the live box without the operator. 5. Never
autonomously quote a price or make an offer. 6. Validate + gated-deploy only —
never push a broken state, never deploy without the operator's go-ahead.
