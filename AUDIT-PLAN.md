# Plan: End-to-end audit of FORGE REI OS + 24/7 box wiring
_Locked via grill — by Claude + Yahjair (operator). 2026-07-11._

## Goal
Verify the whole app is connected end to end and working live: every UI surface (desktop
JSX, mobile PWA, Telegram) reaches a real connector route, every route reaches a real
engine, every engine's side effects land where they should (marcus_state, GHL mirror,
DocuSign sandbox, Telegram, GitHub mirror), and the 24/7 DO box runs it all without
drift from the repo. Every error found gets debated (Codex vs Claude) and assigned an
owner; fixes ship only after the operator's single sign-off.

## Scope & priority order (weighted full sweep)
1. **Newest surface first (shipped 2026-07-11, least battle-tested):**
   - Quick Send contracts: `toolkit_contracts.py` (save_template/list/delete/quick_send),
     `docusign_io.send_document`, POSTs `/api/toolkit/contracts/template/{upload,delete}`
     + `/quicksend`, GET `/mytemplates`; UIs `mobile/m_more.jsx` (MMSendContractSheet) +
     `toolkit_contracts.jsx` (CTQuickSend).
   - AI ARV finder: `toolkit_calc.find_arv` + `_parse_arv_json`, `review_agent._claude`
     `tools=` web-search param, POST `/api/toolkit/calc/arv`; UIs `mobile/m_calc.jsx` +
     `toolkit_calc.jsx` (TkCalcPanels) + `pages.jsx` onApplyArv wiring.
   - Agents chat history / Telegram sync: `agents_history.py`, `/api/agents/history`,
     recording in `/api/agents/chat` dispatch + `_tg_agent_chat`; UI `mobile/m_agents.jsx`
     (Telegram-style rebuild).
   - Tappable home tiles: `window.mGoTab` bridge in `mobile/m_app.jsx`, MHLeadsSheet in
     `mobile/m_home.jsx`.
2. **End-to-end wiring, whole app:** every fetch/POST in every `.jsx` (desktop + mobile)
   must match a ROUTES entry / POST-allowlist entry / dispatch elif in `connector.py`,
   and vice versa (dead endpoints, orphan handlers, allowlist-without-dispatch,
   dispatch-without-allowlist, NO_CACHE gaps on live data, mobile↔desktop drift,
   `/api/sync` revision bumps after POSTs). Engines: `.py` modules imported but unused,
   state files written by two writers, missing locks/atomic writes.
3. **Safety rails (regression check only — 176 tests + prior audits cover these):**
   secrets 404 over HTTP (`marcus_state/`, `*.env`, contract_templates), operator gates
   (quick_send operatorId, DocuSign `is_sandbox()` gate, FORGE_BLAST_LIVE stub default),
   SMS gates (Marcus approval-gated sends, autopilot caps/window), agents never quote
   price / text sellers autonomously.

## Architecture facts (for the reviewer — you cannot reach the box; trust these)
- Python 3 stdlib `connector.py` (~3000 lines) on port 7799; static React UMD +
  in-browser Babel JSX, no build step. GET via `ROUTES` dict + `NO_CACHE` set; POST via
  allowlist tuple + elif dispatch. JSON stores in `marcus_state/` with threading locks +
  `forge_atomic.atomic_write_json`.
- 24/7 DO box 24.199.81.124 (Tailscale 100.87.232.91), systemd `forge-reios`,
  `FORGE_MARCUS=1` (box runs agent loops; Mac runs UI-only). Deploy = rsync via
  `forge rei/deploy/push.sh` (ast + JSX validation → rsync → setup → health gate →
  **GitHub mirror push**, added 2026-07-11).
- GitHub: repo root mirrors to https://github.com/yahglizz/forge-rei-dash after every
  healthy deploy. LEGACY: box `/opt/forge/forge-rei` has origin `yahglizz/os` (frozen
  since 06-24) + cron `git-sync.sh` pulling every 60s — dormant no-op today, but a
  standing footgun (a push to `os` would fail-or-fight the rsync-managed tree).
- DocuSign: sandbox-only (JWT RS256 via openssl subprocess); creds box-only at
  `/opt/forge/forge-docusign/` (outside web root, never synced by push.sh). Local Mac
  is unconfigured by design. Box verified `configured:true`, sandbox.
- Telegram: box-local `telegram_io.py`/`telegram_ops.py` long-poll with 2FA
  (chat id + allowed user ids). The n8n cloud bot (@Forgeworker23bot) is standalone —
  it CANNOT reach the firewalled box; only the box bot syncs with agents chat.
- Live baseline (verified ~17:00 EDT today after deploy): service active,
  `/api/health` + `/api/system/health` 200, `marcus_state/heartbeats.json` 404,
  `ghl.env` not served, GitHub mirror push OK.

## Key decisions & tradeoffs (settled in the grill — attack these if wrong)
1. **Weighted full sweep** over new-features-only: whole repo in scope, priority order
   above. Old-code findings welcome but must be real breaks, not style.
2. **Live-fire verification allowed** (Claude runs these, not Codex): ARV lookups
   (paid web-search calls, ~2-3), agent chat round-trips, Telegram test ping to the
   operator's own chat, DocuSign sandbox envelope to the operator's own email.
   **Never:** SMS/blasts, GHL tag/pipeline/data writes on real leads, ACE/autopilot
   flips, anything reaching a real seller or buyer.
3. **Fix flow — one sign-off:** every confirmed finding gets a debated owner
   (Codex proposes, Claude counters, disagreement logged, Claude arbiter). Operator
   gives ONE "fix it" after seeing the severity-ranked ledger; then owners fix,
   validate, deploy, SSH-verify. Policy-level changes (behavior, money paths, outward
   actions) stay individually gated even after sign-off.
4. **Reviewer is read-only and box-blind:** claims needing live state get tagged
   `[NEEDS-LIVE-CHECK]` and Claude verifies on the box during the debate.
5. **PLAN.md untouched:** it is the locked Wholesaler Toolkit source of truth; this
   audit lives in AUDIT-PLAN.md + PLAN-REVIEW-LOG.md.

## Risks / open questions
- Repo is PUBLIC on GitHub — operator aware, may flip private later.
- Box git-sync legacy cron (above) — likely audit finding, needs an owner.
- `marcus-wholesale-agent/` (git-ignored, 318MB) is still rsynced to the box by push.sh
  and runs marcus engine paths — in scope for wiring checks, low priority.
- Mobile PWA served from box only via Tailscale; no public exposure expected anywhere.

## Findings ledger (ALL FIXED + deployed + live-verified 2026-07-11)
| # | Sev | Where | Defect | Owner | Why owner |
|---|-----|-------|--------|-------|-----------|
| F2 | med | pages.jsx (REI agents chat) | Desktop never loads `/api/agents/history` — shared thread invisible on desktop | Codex | self-contained JSX fix, Claude reviews + deploys |
| F3 | med | connector.py `_tg_agent_chat` | `history or store` lets Telegram's in-memory last-12 starve the shared store → thread forks | Claude | live Telegram round-trip proof is Claude's lane |
| F4 | med | review_agent.py `_claude` | No `stop_reason`/`pause_turn` continuation for server-tool (web_search) turns → ARV lookups can fail | Codex | isolated API-client fix |
| F6 | med | deploy/push.sh | `valjsx.js *.jsx` skips `mobile/*.jsx` — mobile white-screen can pass the deploy gate | Claude | deploy infra; proof = live deploy |
| F5 | low | mobile/m_api.jsx `useApiM` | Shared `aliveMX` ref lets stale in-flight fetch overwrite a newly selected view | Codex | self-contained data-layer fix |
| F7 | low | toolkit_contracts.py `quick_send` | Envelope sent before ledger row persisted — crash window leaves orphan envelope | Claude | proof = live sandbox envelope |
| F8 | low | mobile/m_agents.jsx | Roster hard-coded (5 agents); desktop uses dynamic `/api/agents/list` | Codex | frontend parity fix |
| F9 | low | box `/opt/forge` | Legacy cron pulls frozen `yahglizz/os` every 60s; token-embedded remote lingers | Claude | box SSH only |

Rejected: F1 (scout HOT auto-tag/auto-pipe defaults) — documented operator policy
(CLAUDE.md Rule 2 exceptions), internal + reversible, kill switches exist.

## Out of scope
- DocuSign RSA key rotation + sandbox→prod promotion (separate operator task).
- FORGE_BLAST_LIVE=1 flip, DocuSign assignment template creation (operator switches).
- New features, refactors, style opinions, Agentic-OS (separate project), vault content.
- Key rotation of any kind; repo visibility change (operator's call).
