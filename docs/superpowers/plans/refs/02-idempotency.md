# Tap-action idempotency audit (read-only) — "forge rei/connector.py" set_actions table, lines 2384-2414

Date 2026-11-11. Method: read every handler + its callers. Nothing executed. All locks are in-process `threading` locks (single process on the box). Whether the planned Slack bot runs in the same process: Unknown (spec C5 says Socket Mode "on the box", not stated same process).

Dispatch: `telegram_io._handle_callback` (telegram_io.py:673-760). Calls `_ACTIONS[action](arg)` (pgo/pno also get chat_id). No dedupe by callback id there. Keyboard is removed after the tap (editMessageText, ~line 755) so a plain double-click on ONE Telegram message mostly can't repeat. Telegram+Slack mirror = same card live twice = the real risk. Offset is saved before dispatch (telegram_io ~1300-1310) so a poll retry won't redeliver.

## Table

| action | function (file:line) | 2nd call result | VERDICT |
|---|---|---|---|
| approve | marcus_engine.py:1242 `approve` -> `_send` 1181 | pops proposal at :1230 after GHL SMS; 2nd = `{"error":"proposal not found or already handled"}`. Whole thing under `self.lock`. Backstop: sms_guard thread dedupe (sms_guard.py:100-113). | SAFE (one residual gap, see U1) |
| mdismiss | marcus_engine.py:1258 | `proposals.pop` -> 2nd = error "not found" | SAFE |
| handoff | connector.py:2321 `_tg_handoff` | no claim, no lock. 2nd tap spawns a 2nd thread: re-screens (Claude call), `make_proposal_for` (marcus_engine.py:1131) discards `handled` key + pops/rebuilds the proposal. No SMS sent (still needs approve tap). | UNSAFE (low: cost + duplicate draft; not outward) |
| scoutdismiss | scout_triage.py:1768 | sets `dismissed[conv]` again, extra log line | SAFE |
| skillgo | skill_forge.py:261 | under `_LOCK`, requires `status=="pending"`; set to approved after vault write. 2nd = "already handled" | SAFE |
| skillno | skill_forge.py:313 | same status gate | SAFE |
| opsgo | telegram_ops.py:74 `confirm` | token popped + saved under `_LOCK` (:76-80) BEFORE the send. 2nd = "expired — draft it again". TTL 3600s (:34). | SAFE |
| opsno | telegram_ops.py:119 | pop; 2nd = "already gone" | SAFE |
| opspause / opsresume | forge_ops.py:71 `set_paused` | idempotent (shift row only if state changed). Stale tap can flip a newer state (last-writer-wins). | SAFE |
| aceack | ace.py:1038 `ack` | rewrites ackAt, `set_state(HANDED_OFF)` again (conversation_engine.py:226, history row only on change) | SAFE |
| acestop / aceundo | ace.py:937 `hold` | `set_held(True)` again (conversation_engine.py:249). Note: "undo" only holds the thread, it does not recall a sent SMS. | SAFE |
| dysonplan | agency_dyson.py:389 `generate_draft` | no check for an existing draft for this requestId. 2nd tap = 2nd Claude call, 2nd draft, 2nd approvals row, 2nd bus/Telegram card. | UNSAFE (low: cost + duplicate cards; not outward) |
| reqdismiss | agency_requests_io.py:171 `set_status` | idempotent status write, appends a duplicate history row. Stale tap can overwrite a later status (e.g. done -> rejected). | SAFE (cosmetic) |
| dysongo | agency_dyson.py:577 `decision` -> `apply` 476 | `apply` claims `appliedAt` under `_LOCK` (:494-503), 2nd = `{"ok":True,"detail":"already shipped (idempotent)"}`. Claim released only on failure (:565-569). BUT `decision` (:577-595) has no status guard, see U2. | SAFE for double-ship; UNSAFE for approve-after-reject (U2) |
| dysonno | agency_dyson.py:577 `decision(...,"reject")` | unconditional `dr["status"]="rejected"`, even after it shipped (status lies, PR already open) | UNSAFE (low: state corruption, not outward) |
| pgo | telegram_agent.py:222 `confirm` | chat check first (no consume on wrong chat), then pop + save under `_LOCK` (:226-232) BEFORE the POST. 2nd = "expired — ask again". TTL 1800s (:39). | SAFE |
| pno | telegram_agent.py:259 | pop; 2nd = "already gone" | SAFE |
| adsapply | daycare_ads_tg.py:456 `h_apply` | `_claim` pending->working (:97-109), 2nd = "already handled (working/applied)". Then `ap.approve` (daycare_ads_autopilot.py:478) also needs rec.status=="proposed" + fresh guard vs live Meta, under `_RUN_LOCK`. | SAFE (see U3 for persist caveat) |
| adsskip | daycare_ads_tg.py:479 | `_claim` | SAFE |
| adsundo | daycare_ads_tg.py:489 | `_claim`; `ap.undo` (:518) needs status "executed"; undone rec refuses a repeat | SAFE |
| adsbuild | daycare_ads_tg.py:503 | `_claim` concept->working. Also `build_paused` (daycare_ads_studio.py:736) returns noop if idea already built (:742) and `_BUILD_LOCK` non-blocking (:747). Covers dashboard Build button race too. | SAFE (U3 caveat) |
| adsalt | daycare_ads_tg.py:533 | `_claim` to "replaced" | SAFE |
| adsdrop | daycare_ads_tg.py:543 | `_claim`; `studio.discard` (daycare_ads_studio.py:856) idempotent | SAFE |
| adslaunch | daycare_ads_tg.py:583 `h_launch` -> `ap.launch` autopilot.py:577 | `_claim` launch->working (single use, all amount buttons share one card id). `ap.launch` has 3 more layers under `_RUN_LOCK`: live-state check "already live at $X -> noop" (:636), 24h limit via `lastLaunchAt` (:656-659, set :699), daily ceiling. Any failure rolls back to PAUSED. | SAFE (U3 caveat) |
| adsagain | daycare_ads_tg.py:597 `h_again` | `_claim` on launch2 card; amount must equal card usd; same `ap.launch` guards (`second_ok=True` skips only the 24h gate, not the live-noop or ceiling) | SAFE (U3 caveat) |
| adskeep | daycare_ads_tg.py:611 | `_claim` to "kept" | SAFE |

## UNSAFE / UNKNOWN items

U1. approve residual gap (Marcus, outward SMS). marcus_engine.py:1198-1230: GHL SMS is sent, then `p["status"]="sent"` (:1220), `_persist_proposal(p)` (:1222, plain file append, can raise e.g. ENOSPC), and only then `self.proposals.pop` (:1230). If :1222 raises, the `except` (:1231) releases the sms_guard reservation and returns an error, the proposal stays in memory, SMS already went out, 2nd tap re-sends. Severity: low probability (needs disk/IO failure; Mac disk is full but the box is the runtime), sms_guard thread dedupe may still block it (not verified for this exact path). Minimal fix: move `self.proposals.pop(pid, None)` to immediately after the `ghl_post("/conversations/messages"...)` call (before :1220), or wrap :1222 in try/except. VERDICT: SAFE in normal flow, UNSAFE on persist failure.

U2. dysongo/dysonno state machine. agency_dyson.py:577-595 `decision()`: sets status with no check of current status. (a) Tap Reject, then a stale/mirrored Approve: status goes rejected -> approved and `apply()` ships it (outward deploy PR) because `appliedAt` was never set. (b) Approve (shipped), then Reject: status says rejected, PR already open. Minimal fix: in `decision()` inside the `with _LOCK` block, `if dr.get("status") not in ("draft","revision"): return {"error": f"already {dr.get('status')}"}` before assigning (keeps `apply`'s own appliedAt claim). Note: Approvals Center path (`agency_approvals_io.decide`) calls `apply` directly, not `decision`; not audited here.

U3. daycare_ads_tg `_claim` does not fail closed on save failure. daycare_ads_tg.py:62-68 `_save` swallows every exception (`except Exception: pass`); `_claim` (:97-109) then returns the card as claimed though "working" was never persisted. If the store write fails (disk full), a 2nd tap re-claims and re-runs. For adslaunch/adsagain the autopilot guards (live-state noop :636, lastLaunchAt) are the backstop, but those also persist via `_commit`; same swallow pattern not audited there. Minimal fix: make `_save` return bool and have `_claim` return `(None, "could not record the tap — nothing run")` when it is False. Reverse side effect: a crash after claim leaves the card in "working" forever (fail-closed, no retry; the operator must act in Meta). That is by design but means a failed `adsundo` cannot be retried from its card (state "failed").

U4. handoff (low). Fix: in `_tg_handoff` (connector.py:2321) keep a small `{conv_id: ts}` dict under a lock and return `{"error":"already handed to Marcus"}` if tapped within e.g. 10 min; set it before starting the thread.

U5. dysonplan (low). Fix: at agency_dyson.py:~389, under `_LOCK`, return the existing non-rejected draft whose `requestId == request_id` instead of creating another.

U6. Cross-transport (Telegram + Slack mirror, spec C4). Server-side single-use already holds for: approve, mdismiss, skillgo/no, opsgo/no, pgo/pno, all ads* (claim), dysongo (appliedAt). NOT single-use by state: handoff, dysonplan, dysonno/dysongo ordering (U2), opspause/resume (harmless). The "edit the other message" step in the spec is cosmetic only; the fixes above are the real guard. Also pgo/pno are chat-bound (telegram_agent.py:226-227, `str(chat_id) != p.get("chat")`): a Slack tap must pass a chat id equal to the stored one or it always gets "belongs to another chat". Unknown how slack_io will map it (slack_io does not exist yet).

U7. Unknown (not read): `agency_deploy.ship` (called by apply). If it creates a PR/branch and then returns not-ok, the claim is released (agency_dyson.py:565-569) and a retry could create a second PR. Needs a read of agency_deploy.py.

## Token TTL on adslaunch / ads cards (answer)

No TTL on launch cards. Only TTL in daycare_ads_tg.py: `CONCEPT_TTL = 3*86400` (:42), applied by `_expire_old_concepts` (:239-246) to `kind=="concept"` + `state=="pending"` only. It is called only from `send_concept_cards` (:348) i.e. lazily when new concept cards are sent, not by a timer. Launch / launch2 / optimize / undo cards never expire. Bounds on a stale launch tap instead: (1) `ap.launch` re-checks live Meta every tap: ids exist, belong together, not already live, ceiling, health (autopilot.py:611-700); (2) idea must still be status "built" (:597-600 region); (3) 24h gate via `lastLaunchAt` (:656-659); (4) kill switches: `forge_ops.paused()` and autopilot mode "off" checked at tap time. Optimize cards: a new run marks old proposals "superseded" (autopilot.py:446-448) so a stale apply is refused by `ap.approve` (:484). A stale launch tap days later WOULD still launch if all live guards pass. Recommended: add an age check in `h_launch`/`h_again` (card `createdAt` older than e.g. 24h -> error "card too old"). Not implemented; that is a suggestion.

## Races and locks

- Near-simultaneous double tap, same process: serialized for approve (`self.lock`), opsgo (`telegram_ops._LOCK`), pgo (`telegram_agent._LOCK`), skill (`skill_forge._LOCK`), dysongo claim (`agency_dyson._LOCK`), ads (`daycare_ads_tg._LOCK` RLock around load-modify-save; `ap._RUN_LOCK` blocking on approve/launch/undo; build uses non-blocking `_BUILD_LOCK`). No lost-update race found in these.
- Race-prone (no lock/claim): handoff (U4), dysonplan (U5), dysongo-vs-dysonno (U2).
- Several Telegram poll threads (alerts bot, agent bot, groups) can call `_handle_callback` concurrently, so the locks above matter. All are `threading` locks: they do NOT protect against a second OS process writing the same JSON files (Unknown if Slack will be one).
