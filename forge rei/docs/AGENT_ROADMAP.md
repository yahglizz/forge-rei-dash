# FORGE REI OS — Agent Roadmap (24/7 wholesale agency)

Synthesized 2026-06-08 from a 4-agent parallel audit (lead-capture, follow-up,
reliability, deal-economics). Each item: `severity | gap | fix | file`.

## DONE 2026-06-08
- HOT-lead auto-tag (`_autotag_hot`, runs every poll incl. backlog).
- Price/YES deterministic fast-path to asap (`_has_price_signal`/`_is_affirmative` in `_rule_score`).
- `_extract_price` bare-integer branch ("35000", "i want 8500").
- Regression test `test_price_yes.py`.

## DONE 2026-06-09 — REACTION-DROP LEAK (live miss fixed)
Live audit (raw GHL vs scout records) found Scout caught 11/12 inbound — the miss was a
seller **tapback/emoji reaction** to our text. GHL delivers '👍 to "…our msg…"' as inbound;
the quoted body contains our outreach ("as-is"/"cash") so `_is_our_message()` fired and Scout
**silently dropped the lead** (real case: Robert Ewing 👍'd our follow-up, never scored).
- `marcus_engine._reaction_kind`/`_is_reaction` — classify pos/neg/q reactions (tapback words
  + emoji, must quote our text so a normal reply w/ an emoji isn't mistaken).
- `poll_once` skip guard now `is_our AND NOT reaction`; `reconcile_buckets` same (won't demote
  a reaction record to dead).
- `scout_triage._reaction_score`: 👍→warm (motiv 62, auto-handed to Marcus + Telegram), ❓→warm,
  👎→nurture. NOT auto-hot (soft yes, not a stated price).
- Regression `test_reactions.py` (14 cases incl. Robert's exact body). Verified on box: Robert
  now warm; live diff INBOUND-not-in-records 0 (was 1).
- Confirmed 24/7 infra solid: systemd `enabled` (boot) + `Restart=always`/3s + 0 crashes;
  poll every 180s sweeps ~400 newest convos; followup loop + Telegram live; health green.

---

## TIER 1 — keep it alive 24/7 — ✅ DONE 2026-06-08 (deployed + verified on box)
(retry widen, atomic writes ×7 stores via `forge_atomic.py`, dead-man's-switch in `run_forever`,
RLock + locked `_active`, `PYTHONUNBUFFERED` drop-in, enriched `/api/health` liveness.)

### Tier 1 detail (shipped)
- **P0 GHL retry is too narrow.** `_req` retries only HTTPError 429/5xx; a network blip / read-timeout / DNS flap raises and aborts the whole sweep. Fix: also catch `urllib.error.URLError, TimeoutError, ConnectionError` with the same backoff. `connector.py:97-107`
- **P1 Non-atomic JSON writes corrupt state on restart-mid-write.** Every store except telegram does truncate-in-place; a kill mid-write empties scout.json → re-tags + re-alerts the whole backlog. Fix: shared `atomic_write_json` (tmp + `os.replace`, telegram already does this). `scout_triage.py:282, agent_bus.py:53, daily_goals.py:50, +others`
- **P1 No dead-man's-switch.** Loop/Claude failures only set `last_error`; agent can die silently. Fix: consecutive-failure counter in `run_forever` → after 3, one Telegram alert via the bus notifier. `scout_triage.py:~1425`
- **P1 Records race.** `_active()`/summary/leads iterate `self.records` with no lock while the poll loop mutates it → `dictionary changed size` 500s. Fix: snapshot under lock. `scout_triage.py:626`
- **P1 Logs block-buffered.** No `PYTHONUNBUFFERED` → post-mortem blind. Fix: one line in the systemd unit. `deploy/setup_droplet.sh`
- **P2 Real health probe.** `/api/health` returns ok even if loop died hours ago. Fix: include `last_run` age + `last_error`, 503 when stale. `connector.py:236`
- **P2 POST shared-secret.** Mutations rely only on firewall. Fix: `X-Forge-Token` header check as defense-in-depth. `connector.py:do_POST`

## TIER 2 — work leads 24/7 — ✅ CORE DONE 2026-06-08 (deployed + verified)
Shipped: `followup.py` (FollowupEngine, 30-min loop) + `send_ledger.py`.
- ✅ **No-response bumps** — 24h/72h/7d, max 3, gated `make_proposal_for` drafts grounded on the seller's last words.
- ✅ **Due check-back scheduler** — flags `checkBackDue` + bus/Telegram alert; up to 3 touches; operator one-taps the existing gated nurture send.
- ✅ **Send-ledger** — `_send` + `send_nurture` record every touch; loops skip threads touched within 18h (no double-text).
- ⏳ **Cold re-engage auto-queue** (retro_audit → proposals) — partly covered by no-response bumps for recent leads; the older-than-window audit-queue is the remaining add.
- ⏳ **Nurture-bucket → Marcus enroll** — deferred (lowest value / highest Claude cost).

### Tier 2 detail
- **P0 No check-back / nurture scheduler.** `checkBackDays` + `nurtureDraft` are computed but nothing scans them on a schedule — a "not ready" seller is touched once (maybe) then abandoned forever. Fix: `_maybe_run_cadence()` in `run_forever` (mirror `_maybe_weekly_audit`): find due check-backs → queue a gated proposal; add `checkBackCount`/`nextCheckBackAt` for a multi-touch cadence. `marcus_screening.py:397-411,582-611`
- **P0 No no-response follow-up.** Nothing detects "we replied, seller went quiet N hours." Fix: scan threads where last msg is outbound + age > 24h/72h/7d (tiered) → `MARCUS.make_proposal_for(hint='gentle bump')` gated. `marcus_engine.py:458`
- **P1 Cold-lead re-engage is read-only.** Weekly audit finds cold leads but creates no proposals. Fix: auto-queue gated re-engage drafts for the top K. `scout_triage.py:827+`
- **P1 Nurture bucket never reaches Marcus.** Only asap/warm auto-screen. Fix: enroll nurture into a light drip. `scout_triage.py:536-537`
- **P1 No appointment booking / Retell is read-only.** No call-time proposal, no outbound voice call, no booking link. Fix: gated "book call" action (Google Calendar/GHL slots) or enable Retell create-phone-call gated. `retell_io.py`
- **P2 Shared send-ledger (double-text guard).** The moment Tier-2 loops land, 4 paths can text one seller. Fix: `_can_contact(conv_id)` ledger every send path must pass. `marcus_engine.py:500`

## FULL-DASHBOARD AUDIT + DEAL-LOOP CLOSE — ✅ 2026-06-08 (4-agent audit, deployed+verified)
4 parallel auditors (lifecycle, frontend, reliability, gating). Frontend clean (22 jsx pass, zero dead
buttons, no white-screen). Two auditor claims were live-disproven (schedules DO run on box via systemd
timers; Marcus does NOT re-screen unchanged threads — `screenable` is gated to new-message leads). Fixed:
- **Deal loop closed (start→finish):** `scout_triage.advance_opp(contactId, kind)` + `DEAL_STAGE` (offer→Appointment Set, contract→Under Contract, closed→Closed/Won, env-overridable). Offer send (`handle_send_post`) → deal saved + offer-tag + opp→Appointment Set. Contract send → opp→Under Contract. New **contract poller** (`_contract_poll_forever`, every 600s) → DocuSign "completed" → mark opp **Won** (value=assignment fee) → Closed/Won → `deal_stats` counts it. `sendOffer` now persists the calc (`/api/deals/save`).
- **Gating fix:** `auto_send_nrn` default→False (the one un-gated outward text). **Contract idempotency** guard (no duplicate envelope on re-click, `force:true` to override).
- **Durability:** 7 agency stores → `forge_atomic` atomic writes. **Health probe** now covers Follow-up + Telegram. **Nav:** Dyson + Eco wired into the agency sidebar (were orphaned).
- Verified on box: stages resolve to real GHL IDs, idempotency blocks, deal-save persists, poller clean, all loops live.
- ⏳ Remaining P2: operator double-click ledger guard; `autoSendNrn` UI toggle; Telegram self-start on late creds; put the systemd timers into `setup_droplet.sh` (rebuild-safety).

## TIER 3 — actually close deals + earn fees — 🟡 IN PROGRESS 2026-06-08
Shipped backend: `deals.py` (persistent deal record — MAO stops evaporating) + `docusign_io.py`
(DocuSign eSignature, JWT-via-openssl, send-from-template, status — INERT until creds set) +
endpoints `/api/deals/{list,get,save,upsert}` + `/api/contract/{config,send,status}` + box config
scaffold `forge-docusign/config/docusign.env.example`.
- ✅ **DocuSign LIVE (sandbox)** 2026-06-08 — JWT auth working, account `96869f27…`, template `a6c2eb02…` (Ohio PA, anchored seller_name/property_address/purchase_price + seller signHere/date). Test envelope sent + fields verified on the doc. `/api/contract/config` → configured.
  - ⏳ Rotate RSA keypair (private key was pasted in chat) + promote sandbox→production when ready.
  - ✅ **Full fillable agreement UI** 2026-06-08 — template `f9e563e8` (HTML token-anchored, 22 fields). Deal Calc → pick homeowner → "prepare contract" → 19-field form (Parties/Property, Money/Closing, Title, Buyer) → gated send. `handle_contract_send` maps form→tabLabels; `deals.py` persists. Verified end-to-end on box.
  - ⏳ Rotate RSA key + sandbox→prod still pending.
- ⏳ UI: deal panel + "Send Contract" button + contract-status badge (next).
- ⏳ Auto-advance pipeline Hot→Under Contract on envelope `completed`; webhook or status poll.
- ✅ **Buyers/dispo module** 2026-06-08 (deployed+verified) — `buyers.py` (atomic `buyers.json` store +
  buy-box matcher) + `/api/buyers/{list,match,dispo,upsert,remove,assign}` + `buyers.jsx` **Buyers** page
  (REI nav). Roster CRUD (areas/maxPrice/types/minBeds/condition/POF, pause/activate) + dispo worklist:
  every deal with an offer/contract shows ranked cash buyers (area+price = hard filters → `fits`, score
  0-100 + reasons) with one-tap **Assign** (reversible link onto the deal record, no outward action).
  Box: list/dispo/jsx 200, `buyers.json` 404. **The deal loop now has a dispo endpoint — the missing half is in.**

### Tier 3 detail (remaining)
- **P0 Persist the deal.** MAO from the Deal Calc evaporates on refresh; screening data is prose only. Fix: `marcus_state/deals.json` keyed by contactId (address/beds/baths/sqft/condition/repairs/asking/MAO/offer/buyer/status), prefilled from screening + GHL, written back to the opp value. `pages.jsx:840-858, marcus_screening.py:325`
- ✅ ~~**P0 Buyers / dispo module — entirely missing.**~~ DONE 2026-06-08 — `buyers.py` + `/api/buyers/*` + Buyers page (see Tier 3 above). Remaining dispo polish: blast-to-buyers (email/SMS the deal to all `fits` buyers, gated), `dealsBought` increment on assign→closed, buyer activity log.
- **P0 Contract gen / e-sign — total gap.** Offer SMS promises a contract that doesn't exist. Fix: PA + assignment templates auto-filled from the deal sheet + DocuSign/PandaDoc/Dropbox-Sign (or generated PDF + e-sign link). `MISSING`
- **P1 Pipeline stops at "Hot."** No Offer Made / Under Contract / Assigned / Closed mapping. Fix: extend `STAGE_BY_BUCKET`/aliases; auto-advance to Offer Made on offer-tag, gated past. `scout_triage.py:109`
- **P2 Comps/ARV is manual.** Fix: RentCast/ATTOM `/api/comps?address=` → auto-fill ARV. `pages.jsx:928`
- **P1 KPIs coarse.** Missing lead→contract %, contract→close %, speed-to-contract, avg fee, cost/lead. Fix: funnel from offers[] + stage timestamps. `deal_stats.py:130`
- **P2 JV fee-blind / fellThrough conflated.** JV books full value as yours; fellThrough mixes title-fallout with early ghosts. Fix: `jvSplit` field; only count post-offer losses as fellThrough. `deal_stats.py:47,156`

---

### Recommended build order
1. **Tier 1 reliability** (1 session) — cheap, stops silent failure. Non-negotiable for unattended.
2. **Tier 2 cadence + follow-up** (1-2 sessions) — turns the reactive tagger into a 24/7 worker. Highest business leverage on the lead side.
3. **Tier 3 closing spine** (2-3 sessions) — deal record → buyers → contract. Turns it into a business that collects fees.
