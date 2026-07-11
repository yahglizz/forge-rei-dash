# Plan Review Log: End-to-end audit of FORGE REI OS + 24/7 box
Act 1 (grill) complete — plan locked with the operator. MAX_ROUNDS=5.
Reviewer: Codex (gpt-5.6-luna, reasoning high, codex-cli 0.144.1), read-only every round.
Plan file: AUDIT-PLAN.md (PLAN.md is the locked toolkit source of truth — untouched).
Grill outcomes: weighted full sweep · live-fire rules set · one-sign-off fix flow with
debated per-finding owner (Codex proposes, Claude arbiters).

## Round 1 — Codex

[SEV:high] scout_triage.py:89 — Scout defaults to autonomous GHL tag and pipeline writes for ASAP leads. [NEEDS-LIVE-CHECK]
  BREAKS: With no override flags, each production sweep calls `_autotag_hot()` and modifies real GHL records without operator approval.
  FIX: Default both flags off and queue tags/pipeline changes for approval.
  OWNER: Claude — live box configuration must be checked and disabled immediately.

[SEV:medium] pages.jsx:643 — Desktop REI agent chat ignores persistent `/api/agents/history`.
  BREAKS: Messages from mobile/Telegram disappear when opening or reloading the desktop Agents tab.
  FIX: Load and render the server history thread.
  OWNER: Codex — self-contained frontend wiring fix.

[SEV:medium] connector.py:1788 — Telegram prefers stale in-memory history over the persistent shared thread.
  BREAKS: After dashboard/mobile messages, an existing Telegram session sends old context to the agent.
  FIX: Always reload or merge the latest `agents_history` before generating Telegram replies.
  OWNER: Codex — deterministic history-selection fix.

[SEV:medium] review_agent.py:64 — `_claude` drops `stop_reason` and never continues paused server-tool turns.
  BREAKS: A web-search ARV request returning `pause_turn` produces no final JSON and the UI reports lookup failure. [Anthropic continuation protocol](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use)
  FIX: Preserve the assistant tool response and continue the request when `stop_reason == "pause_turn"`.
  OWNER: Codex — isolated Anthropic client fix.

[SEV:medium] mobile/m_api.jsx:12 — `useApiM` has no request sequencing or cancellation.
  BREAKS: Switching buckets or contacts while a prior fetch is pending lets the old response overwrite the newly selected view.
  FIX: Add request IDs or `AbortController` handling.
  OWNER: Codex — self-contained mobile data-layer fix.

[SEV:medium] deploy/push.sh:35 — Deploy validation excludes every `mobile/*.jsx` file.
  BREAKS: A mobile Babel or computed-tag regression can deploy successfully and white-screen the PWA.
  FIX: Pass `mobile/*.jsx` to `valjsx.js` during deployment.
  OWNER: Codex — mechanical deploy validation fix.

[SEV:medium] toolkit_contracts.py:469 — Quick Send sends DocuSign before durably recording the ledger row.
  BREAKS: DocuSign succeeds, then a process crash or disk error leaves a live envelope with no local status or void record.
  FIX: Persist a pending outbox record before sending and reconcile the envelope result atomically.
  OWNER: Claude — external envelope recovery requires live-box verification.

[SEV:low] mobile/m_agents.jsx:14 — Mobile agent roster is hard-coded and omits configured Retell agents.
  BREAKS: A Retell agent visible and chat-capable on desktop never appears in mobile Agents.
  FIX: Load `/api/agents/list` and merge dynamic agents into the mobile roster.
  OWNER: Codex — frontend parity fix.

[SEV:low] deploy/push.sh:44 — The rsync-managed box still has a documented legacy git-sync overwrite path. [NEEDS-LIVE-CHECK]
  BREAKS: If the old cron pulls from `yahglizz/os`, it can overwrite the healthy rsynced tree with divergent code after deployment.
  FIX: Disable the legacy cron and remove the obsolete box Git remote.
  OWNER: Claude — only Claude can inspect and retire the live cron safely.

CLEAN: Tappable home tiles and the `mGoTab` bridge are wired correctly.

CLEAN: No dead JSX endpoints, orphan POST allowlist entries, missing dispatch branches, or NO_CACHE omissions were found; successful POST dispatches bump `/api/sync`.

CLEAN: Quick-send operator and sandbox gates, blast stub default, and SMS guard paths are present.

VERDICT: REVISE
### Claude's response (Round 1)
Verified every claim against code before ruling.

- **F1 scout auto-tag/auto-pipe — REJECTED.** Not a defect: CLAUDE.md Rule 2 documents
  both as deliberate, operator-approved exceptions ("internal + reversible", undo button,
  `FORGE_SCOUT_AUTOTAG_HOT=0` / `FORGE_SCOUT_AUTOPIPE_HOT=0` kill switches). The audit
  plan's own safety-rail definition permits "auto-apply internal+reversible tags".
  Reviewer missed the operating manual. No live check needed — behavior matches policy.
- **F2 desktop agent chat no history — ACCEPTED (medium).** Confirmed: pages.jsx only
  POSTs /api/agents/chat, never GETs /api/agents/history. Breaks the "one thread across
  dash/mobile/Telegram" promise on desktop. Owner: Codex (self-contained JSX fix;
  Claude reviews diff + deploys).
- **F3 Telegram stale history — ACCEPTED (medium).** Confirmed root cause: telegram_io
  `_AGENT_SESS` passes its in-memory last-12 (`list(sess["history"])`), so
  `history or recent_for_context(...)` never consults the shared store after the first
  Telegram exchange → thread forks. Owner: **reassigned Codex→Claude** — fix lands in
  connector.py`_tg_agent_chat` (live Telegram loop) and the proof is a live Telegram
  round-trip, which only Claude may run under the live-fire rules.
- **F4 _claude pause_turn — ACCEPTED (medium).** Confirmed: no stop_reason handling;
  web_search turns that pause would return partial text → ARV parse failure. Owner:
  Codex (isolated client fix; shared infra so Claude reviews carefully).
- **F5 useApiM race — ACCEPTED (low, downgraded from medium).** Confirmed and sharpened:
  the aliveMX useRef is SHARED across effect runs — path-change cleanup sets it false,
  the re-run sets it true, so a stale in-flight fetch passes the guard and overwrites
  the new view. Downgraded: polled views self-heal ≤12s; non-polled sheets stay wrong.
  Owner: Codex.
- **F6 mobile JSX not validated on deploy — ACCEPTED (medium).** Confirmed: push.sh runs
  `valjsx.js *.jsx` from the app root; mobile/*.jsx never validated — and mobile Babel
  failures are documented to white-screen silently. Owner: **reassigned Codex→Claude** —
  push.sh is deploy infrastructure; the only real proof is running a live deploy, which
  is Claude's lane.
- **F7 quick_send ledger-after-send — ACCEPTED (low).** Real durability gap; consequence
  bounded (envelope still visible in DocuSign console). Fix = pending row before send,
  reconcile after. Owner: Claude (verification requires a live sandbox envelope).
- **F8 mobile roster hard-coded — ACCEPTED (low).** Confirmed: desktop pulls
  /api/agents/list (dynamic), mobile hard-codes 5 agents. Owner: Codex.
- **F9 legacy git-sync cron — ACCEPTED (low sev, high hygiene).** Pre-known (flagged in
  AUDIT-PLAN). Fix: remove cron + git-sync.sh + the token-embedded `os` remote on the
  box. Owner: Claude (box SSH only).

Net: 8 accepted (2 medium owners reassigned to Claude), 1 rejected with citation.
Ledger written into AUDIT-PLAN.md; plan revised.

## Round 2 — Codex

F1 rejection stands. `CLAUDE.md:47-49,196-197` documents HOT auto-tag/auto-pipe as deliberate reversible exceptions, and `scout_triage.py:84-90,1280-1303` implements the documented kill switches.

F3 and F6 owner reassignments stand: both require Claude’s live Telegram/deploy verification authority.

CLEAN: All checked POSTs in `mobile/m_more.jsx`, `mobile/m_pipeline.jsx`, `toolkit_blast.jsx`, and the `/api/agency/*` JSX surface match connector allowlist and dispatch branches. No new wiring defect found.

VERDICT: REVISE
### Claude's response (Round 2)
Full concession round: F1 rejection accepted (Codex now cites CLAUDE.md:47-49,196-197 +
scout_triage.py kill switches itself), owner reassignments accepted, priority-2 deep
recheck (m_more/m_pipeline/toolkit_blast/agency surface) clean, no new findings.
REVISE verdict reflects the 8 unfixed defects, not plan disagreement — fixes are gated
on operator sign-off by design. Round 3 asks for a verdict on the PLAN+LEDGER itself.

## Round 3 — Codex

The plan and findings ledger are sound.

- F1 rejection is supported by the documented HOT auto-tag/auto-pipe exceptions and kill switches.
- F2–F8 have accurate defects, severity, fixes, and owners. Claude’s ownership of F3/F6 is appropriate because both require box/live verification.
- F9 is correctly scoped as low severity with a Claude-owned live check and removal fix.
- The recheck of mobile POST paths and `/api/agency/*` found no omitted material wiring issue.

No material gap found.

VERDICT: APPROVED
### Resolution
Converged in 3 rounds. Ledger: 8 accepted findings (Claude: F3,F6,F7,F9 · Codex: F2,F4,F5,F8),
1 rejected (F1, documented operator policy). Awaiting operator one-sign-off to fix.
