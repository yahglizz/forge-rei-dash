# FORGE AI — Integrations (audit 2026-09-22)

Env var **names** only — values live in git-ignored `*.env` files outside the web root
(`forge-*/config/*.env`, `marcus-wholesale-agent/config/ghl.env`, box `/etc/default/forge-reios`).
Status = what was observed on the box on 2026-09-22, not what the code claims.

| Integration | Business | Module(s) | Env names | Status | Failure behavior |
|---|---|---|---|---|---|
| **Anthropic (Claude)** | all agents | `review_agent._claude` (shared), `marcus_engine` direct call | `ANTHROPIC_API_KEY` (box default + `ghl.env` + `agency.env`), `AGENCY_ANTHROPIC_API_KEY` | 🔴 **DOWN since 2026-08-01 — credit balance too low (all 3 keys, one account)** | per-caller fallback / error; was invisible to health (fix: WP-A) |
| **GoHighLevel — wholesale** | Wholesale | `connector.GHLClient` (`WHOLESALE`), scout, marcus, followup, ace | `GHL_API_KEY`, `GHL_LOCATION_ID`, `GHL_USER_EMAIL` (in `marcus-wholesale-agent/config/ghl.env`) | 🟢 `/api/health` ok, Scout sweeping every 180 s | `_req` retries 429/5xx/network |
| **GoHighLevel — agency** | Agency | `connector.AGENCY` | `GHL_*` in `agency.env` | 🟢 configured | same client |
| **GoHighLevel — daycare** | Daycare | `daycare_ghl.py` (`DAYCARE_GHL`) | `GHL_*` in `daycare.env` | 🟢 configured (session-gated routes) | family texts owner-initiated only |
| Sub-account isolation | — | three separate client instances; `agent_coach` secret-guard never moves location ids | — | ✅ by design | — |
| **Supabase** | Daycare | `daycare_supabase.py` (RLS, server sessions) | `NEXT_PUBLIC_SUPABASE_*`, `DAYCARE_*` | 🟢 live (`FORGE_DAYCARE_LIVE=1`, `_WRITES=1`, `_TEST_MODE=1` ← confirm) | dashboard migrations 9 behind the app |
| **Meta Marketing API — daycare** | Daycare | `daycare_growth` → `agency_ads` (locked env-swap), `daycare_ads_studio` | `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_MAP` (`daycare.env`) | 🔴 token invalid (32 chars, OAuth 190) → spend/CPL/CTR unreadable | falls back to labeled mock; Solomon retried every 15 min (fix: WP-A) |
| Meta — agency / dropship | Agency / (archive) | `agency_ads`, `agency_eco`, dropship | `META_*` | agency: demo-account guard; dropship: blank | mock labeled on Ads page, **unlabeled on Eco page** |
| Pipeboard (Meta MCP) | dev-time | Claude Code MCP only | `PIPEBOARD_API_TOKEN` (`~/.agents.env`) | dev only | — |
| **Telegram** | all | `telegram_io.py`, `telegram_ops.py` | `TELEGRAM_BOT_TOKEN`, `_CHAT_ID`, `_ALLOWED_IDS` (blank → operator-DM-only fallback, default-deny), `_AGENT_BOT_TOKEN` | 🟢 both bots polling | alerts dedupe + quiet hours |
| **n8n** | Agency | `agency_workflows_io.py` | `N8N_BASE_URL`, `N8N_API_KEY`, `N8N_WORKFLOW_ID` | 🔴 base URL → "No workspace here" (404); **mock catalog shown as connected·LIVE** (fix: WP-G) | falls back to `_MOCK_WORKFLOWS` |
| **Retell (voice)** | Wholesale | `retell_io.py`, Outbound page | `RETELL_API_KEY` | key set; usage unverified | route-driven |
| Twilio | Wholesale (legacy) | legacy scripts | `TWILIO_*` | key set; not on the live send path (GHL sends SMS) | — |
| **Stripe** | Daycare | `stripe_io.py` | `STRIPE_SECRET_KEY` | key set; owner-initiated invoices only | "add key" hint when blank |
| **DocuSign** | Wholesale | `docusign_io.py`, contract poller | `forge-docusign/config/docusign.env` | 🟢 poller running (600 s) | terminal-error pause |
| Metricool | Agency / Daycare social | `agency_social.py` | `METRICOOL_USER_TOKEN` | daycare blank → mock | labeled |
| Higgsfield | Daycare ads studio / agency | `higgsfield_io.py` | `HIGGSFIELD_API_KEY`, `_SECRET` | key set | — |
| Shopify / AutoDS / WinningHunter / EverBee / GetHookd / Apify | Dropship (**archive**) | `dropship_*.py` | `SHOPIFY_*`, `AUTODS_*`, … | mostly blank; loop off | health pings still run from Mission Control → filter (WP-B) |
| Obsidian vault + git | all | `brain_io.py` | `FORGE_VAULT` | 🟢 box vault `/opt/forge/vault` (no git remote on box) | read now `.md`-only |
| Tailscale Serve / Funnel | infra | box | — | 🟢 Serve → :7799 (tailnet), Funnel :8443 → portal :10000 (public) | — |
| Vercel sites | Daycare website + forms, ClientForge site | private brand-kit repos | Vercel env | 🟢 `/api/enroll` → GHL + speed-to-lead workflow live | — |
| Web3Forms / Resend | ClientForge site / daycare intake email | site repos | — | 🟢 | — |
| LeadScraper (Apify → Google Sheet) | Agency prospecting | `~/Desktop/LeadScraper` | `APIFY_TOKEN` (Mac) | **Mac-only** — not on the box | — |
| GitHub | deploy | autopull (box pulls public repo), auto-sync (Mac pushes) | `GITHUB_TOKEN` (box default) | 🟢 | bad commit aborts deploy |

## Inbound webhooks

None. Telegram uses long-poll. GHL workflows, Vercel functions and Meta forms deliver into GHL,
not into the box. (Spec §22 "webhooks validated": N/A today; any future receiver must validate
signatures.)

## Gaps vs the spec

| Spec need | Have | Missing / next |
|---|---|---|
| Daycare Meta spend/leads/CPL/CTR | `agency_ads` toolchain + demo guard | valid token (owner), CAPI, tour/enrollment attribution join |
| Daycare lead pipeline NEW→ENROLLED | GHL `Enrollment` pipeline (only "New Lead" used) + tags from `/api/enroll` | stage derivation on the box (WP-E Lead Desk), tour stage/calendar |
| Tour booking | none (tours arranged by text/phone) | GHL calendar decision (owner) |
| Wholesale AI conversations + DNC/opt-out | Scout + Marcus + ACE + `sms_guard` (DNC + 9–8 ET for everyone) | Claude credits |
| Agency prospect research → call queue | Call Sheet (PDF/text import, statuses, tally) + Mac LeadScraper | prospect engine on the box (P1-8) |
| n8n | client code | a real workspace URL or retire the page |
