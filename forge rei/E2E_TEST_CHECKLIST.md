# E2E TEST CHECKLIST — fake leads, A to Z

How to prove the whole automated OS works end-to-end without touching a real
seller. Two layers:

1. **Automated** — `test_e2e_pipeline.py` runs fake leads through the REAL
   engines (Scout → auto-screen → Marcus → conversation state → ACE → Atlas →
   Do Today) against an in-memory fake GHL + canned Claude. Every `STATE` file
   is redirected to a tempdir (including `ace.CALL_READY` — it's a second file,
   easy to miss), `brain_io.write_note` is captured, no network. Run:

   ```bash
   cd "forge rei" && FORGE_MARCUS=0 python3 -m unittest test_e2e_pipeline -v
   # full regression: FORGE_MARCUS=0 python3 -m unittest discover -s . -p "test_*.py"
   ```

2. **Live box (read-only)** — after a gated deploy, verify the running 24/7
   dashboard through the tunnel. No fake contacts are created in the real GHL;
   live checks are health/read endpoints only. (Optional live-GHL smoke:
   `forge-test-harness/test_lead.py` with the `forge-test` tag — manual,
   operator-run only.)

---

## Stage checklist (each row = automated assertion → live spot-check)

| # | Stage | Automated (test_e2e_pipeline.py) | Live spot-check (dashboard @ localhost:7799) |
|---|-------|----------------------------------|---------------------------------------------|
| 1 | Scout ingest + filter | `test_our_own_outreach_is_never_scored` — our blast mis-flagged inbound is dropped | Conversations tab shows only genuine seller replies in triage |
| 2 | Scoring + buckets | `test_scout_scores_asap_and_alerts` — price+yes → asap 92, claude source; `test_nurture_bucket_no_handoff_no_alert` — "not right now" → nurture via rule (no Claude spend) | `/api/scout/summary` bucket counts look sane |
| 3 | DNC safety | `test_dnc_goes_dead_and_is_never_entertained` — STOP → dead, no tags, manual screen refuses | a STOP lead shows bucket dead, no motivated tag |
| 4 | Hot alert (bus) | one `hot_lead` bus msg per asap transition, no dupe on re-poll | Command Center comms + Telegram ping on a real hot lead |
| 5 | Auto-tag + auto-pipeline (hot only) | `test_hot_autotag_and_autopipeline_are_idempotent` — tags `triage: asap`+`motivated: high` once, opp lands in Hot stage once, 3rd poll adds nothing | GHL contact shows the two tags; Wholesaling Pipeline Hot stage has the opp |
| 6 | Auto-screen bridge | `test_auto_screen_produces_report_and_call_ready_state` — Scout on_scored → Marcus report score 9 / Hot Lead - Call Now, brain note written | Marcus tab shows the screening marked (auto) |
| 7 | Conversation state | same test — all 5 facts known → CALL_READY | `/api/ace/state` shows the thread's state |
| 8 | Nurture lane | `test_manual_screen_yields_gated_nurture_draft` — not_ready → Follow-Up, checkBackDays 60, voice-scrubbed draft, NOTHING sent | nurture check-back sits as a tap-to-send draft, never auto-sent |
| 9 | ACE off (default) | `test_off_mode_never_touches_marcus`, `test_no_sms_and_no_autonomous_sends_with_ace_off` — decide()="stop: ace off", zero proposals, zero SMS | `/api/ace/status` mode=off on the box — ALWAYS, unless operator flips it |
| 10 | ACE shadow | `test_shadow_drafts_but_never_sends` — one gated proposal (top missing fact), approve never called | (only if operator enables) drafts appear in approval inbox |
| 11 | ACE supervised contract | `test_supervised_autosend_is_flagged_autonomous_and_capped` — proposal `autonomous=True` (LOCKED — full sms_guard stack), sentToday=1, replies counter bumps | (operator-only) Telegram receipt + ⛔ stop button per send |
| 12 | Call-ready escalation | `test_call_ready_escalates_instead_of_texting` — CALL_READY → escalate + call-ready queue, no text drafted | 📞 call-ready ping; ✅ ack → HANDED_OFF |
| 13 | Atlas underwriting | `test_atlas_prep_anchors_from_seller_ask_only` — anchors only from the seller's ask, walkaway = ask, opening<target≤walkaway, cache hit on re-prep | Atlas card on a screened-interested lead shows anchors + MAO note |
| 14 | Do Today | `test_do_today_dedupes_to_one_task_text_back_first` — one row per contact, text-back outranks call; `test_do_today_surfaces_anchored_call_after_we_text_back` — after we reply, the anchored call task surfaces | Do Today card: no duplicate rows for one seller |

## Hard invariants (the suite fails if any break)

- **No SMS ever leaves the harness**: `FakeGHL.sms_posts() == []` in every
  scenario except the explicit supervised test, where the "send" goes through
  the FakeMarcus approve() path — and even there `autonomous=True` is asserted.
- **No production state**: every engine's STATE + `ace.CALL_READY` →& tempdir;
  suite leaves `marcus_state/` untouched (this was a real bug found + fixed —
  see below).
- **No real Claude / GHL / vault**: `review_agent._claude`, `_api_key`, all
  three agent key fns, `agent_context.brain_context`, `brain_io.write_note`
  faked in `setUp`.

## Bugs this harness caught

1. **`ace.CALL_READY` production leak** — ace keeps the call-ready queue in a
   second file next to `ace.STATE`. First harness draft patched only `STATE`,
   and the suite wrote a fake lead (Maria Lopez) into the real
   `marcus_state/call_ready.json`. Fixed: harness patches `ace.CALL_READY`
   too, leaked file removed. Lesson encoded here so no future test repeats it.

## Live-box verification (read-only, after deploy)

```bash
~/"forge rei dash/open-dashboard.sh"        # tunnel + open
curl -s localhost:7799/api/system/health    # service alive
curl -s localhost:7799/api/ace/status       # mode MUST be "off"
curl -s localhost:7799/api/scout/summary    # triage running
curl -s localhost:7799/api/cost/status      # cost tracker counting
curl -s -o /dev/null -w '%{http_code}' localhost:7799/ghl.env   # MUST be 404
```
