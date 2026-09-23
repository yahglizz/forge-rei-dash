# FORGE AI — Test Plan (2026-09-22)

A feature is complete only when **implemented + tested + connected + observable + has failure
handling** (spec §3). Run tests from `forge rei/`.

## 1. How to run

```bash
cd "forge rei"
T=$(mktemp -d)
for f in test_*.py; do
  case $f in test_mode.py) continue;; esac   # production module, not a test
  FORGE_MARCUS=0 FORGE_VAULT=$T python3 "$f" || echo "FAIL $f"
done
node deploy/valjsx.js *.jsx mobile/*.jsx   # Babel transform + computed-tag scan
python3 deploy/live_smoke.py --json        # GET-only smoke against a running connector
```
Four tests import `connector` and build engines from the **real** `marcus_state/`
(`test_audit_hardening`, `test_audit_regressions`, `test_autopilot_routes`,
`test_daycare_connector_contract`); `MarcusEngine` init can append quarantine rows to the real
`proposals.jsonl`. Run them only against a temp copy of `marcus_state`.

## 2. Baseline (2026-09-22, Mac, offline suite minus the 4 above)

**26 pass / 2 fail** at audit time — both fixed in WP-G. **After wave 1: 32 pass / 0 fail; 33 pass / 0 fail at the wave-2 audit**
(the suite now includes test_ai_health, test_business_scope, test_owner_actions,
test_agent_registry, test_daycare_leads). The two former failures:
- `test_e2e_pipeline.py` — opt-out reason label (`scout_triage._rule_score`).
- `test_marcus_filters.py` — macOS `/var` vs `/private/var` path spelling.

Live box: `/api/health` ok (wholesale GHL), all heartbeats green except **solomon**; Claude
calls fail (credits); secret paths 404; brain `.env` read blocked after the 09-22 fix.

## 3. Spec §21 scenarios → tests

| Spec test | Covered by | Status |
|---|---|---|
| **Agency**: test prospect → queue → mark interested → follow-up task → pipeline → audit log | `agency_callsheet` / `agency_calls` self-checks; `test_agency_messages.py` | partial — no follow-up-task / audit-log assertion (needs P1-8 + P1-9) |
| **Wholesale**: seller → AI conversation → intent → qualify → HOT → owner task → **no duplicate task** | `test_e2e_pipeline.py` (Claude/GHL faked, full pipeline), `test_ace.py`, `test_triage_fix.py`, `test_price_yes.py`, `test_sms_guard.py`, `test_optout_hardening.py` | good; owner-task dedupe asserted by `test_owner_actions.py` (WP-C) |
| **Daycare**: simulated Meta lead → CRM → AI workflow → tour → reminder → pipeline → attribution | website `/api/enroll` (brand-kit repo); `test_daycare_leads.py` (WP-E: stage derivation, needs-human, alert dedupe) | partial — tour/reminder/attribution not built |
| **Agent failure**: break integration → detect → retry → log → DEGRADED → owner/dev task | `test_ai_health.py` (WP-A: credit-400 → hard-down → health ok:false → one alert; recovery), `test_agent_registry.py` (WP-D: status mapping), `test_owner_actions.py` (FIX item) | built (wave 1) |
| **Archive**: archive → hidden → data remains → reactivate → returns | `test_business_scope.py` (WP-B) + manual UI check | built (wave 1) |

## 4. Other suites (existing)

Safety/approval: `test_sms_guard`, `test_autopilot_routes`, `test_telegram_ace`, `test_test_mode_scope`,
`test_price_yes`, `test_reactions`. Daycare: `test_daycare_supabase`, `test_daycare_blast`,
`test_daycare_ads_honesty`. Toolkit: `test_toolkit_{blast,calc,contracts,pipeline}`. Brain/skills:
`test_brain_live` (incl. `.md`-only read guard), `test_skill_forge`, `test_dropship_skills`.
Cost: `test_cost_tracker`, `test_triggers_cost`. Portal: `test_portal_e2e`.

## 5. Post-deploy verification (every merge to `main`)

1. Box HEAD == `origin/main` (`git -C /opt/forge/repo log -1`), `systemctl is-active forge-reios`.
2. `curl 127.0.0.1:7799/api/system/health` → 200; no unexpected red loops; `ai` block present.
3. Secret paths 404: `/config/ghl.env`, `/.env`, `/api/brain/note?path=.env` → `not found`.
4. New routes 200: `/api/businesses`, `/api/owner-actions`, `/api/agents/registry`,
   `/api/daycare/leads` (session-gated → expect `authentication_required` from raw loopback curl).
5. UI loads without white screen: open `https://forge-reios.tail0a2dda.ts.net`, Mission Control
   renders Owner Actions card; switcher shows 3 businesses; Archived page lists Dropship.
6. After Claude credits return: `/api/hub/chat` round-trip for every agent in the registry.

## 6. Security checklist status (spec §22)

| Item | Status |
|---|---|
| API keys server-side / not committed | ✅ (history scan clean) |
| Logs free of credentials | ✅ mostly (raw Meta exception text — LOW) |
| Auth protects dashboard | ⚠️ network-level only (tailnet); no user login |
| Authorization protects data | ⚠️ daycare open mode = admin for tailnet |
| Webhooks validated | N/A (none) |
| Rate limiting | GHL client backoff; SMS caps in `sms_guard`/ACE/autopilot |
| Input validation | POST body caps, JSON parse, path jail, id validation |
| Least privilege | ⚠️ single process, root |
| Destructive actions need approval | ✅ propose → approve |
| Backups | 🔨 WP-F nightly local tarball; off-box = owner decision |
| Rollback | ✅ git revert → autopull; bad commit aborts deploy |
