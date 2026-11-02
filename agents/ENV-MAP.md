# FORGE agents — env var and MCP map

> Names only. This file never holds a secret value. Code refs are relative to `forge rei/`.
> Written 2026-10-31 from a grep of each agent's engine files plus `~/.agent-keys/STATUS.md`
> (the 2026-10-31 04:00 snapshot). Re-check STATUS.md before relying on a status below.

## Rules that apply to every table

- **Values live only in `~/.agent-keys/master.env`**, rebuilt by `python3 ~/.agent-keys/build_master.py`
  from the per-business source env files. They are never committed to this repo and never pasted into
  a card. To check a key, read `~/.agent-keys/STATUS.md` (names and status only).
- **Two naming schemes.** The engine code reads the *plain* name from its own business env file
  (for example `ANTHROPIC_API_KEY` in `agency.env`). `master.env` keeps same-name keys with different
  values apart by a `__LABEL` suffix (`ANTHROPIC_API_KEY__AGENCY`). The "master.env name" column maps
  one to the other; the mapping comes from the Sources column in STATUS.md, not from code.
- **Never cross accounts.** `__DAYCARE`, `__WHOLESALE` and `__AGENCY` are separate accounts. An agent
  uses only its own label. If its label has no entry, the status is "not listed", and nobody borrows
  another label's value to fill the gap.
- Status words: OK = live call succeeded. FAIL = service rejected it. EMPTY = blank in every source.
  UNTESTED = no safe test exists. CONFIG = non-secret id or setting. Not listed = no entry in STATUS.md.
- **MCPs are suggestions, not read from code.** No engine file calls an MCP. The MCP column says what
  a Claude Code session working on that agent would reach for. Any MCP write (ad change, CRM write,
  send, deploy) still needs the owner's yes (CLAUDE.md section 2).
- `FORGE_*` tuning knobs (intervals, caps, kill switches) are not secrets and are documented on each
  agent's card; they are listed here only so the map is complete.

## Shared by every agent

| Env var | Read by | master.env name | Status |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `telegram_io.py` | same | OK |
| `TELEGRAM_AGENT_BOT_TOKEN` | `telegram_io.py` | same | Unset on the box since 2026-11-02: `@Forgeagentsbot` DMs run through n8n (`FORGE Agent Chat`), and a webhook and box polling can't share a bot. To move the DM back: delete the webhook, restore this line, restart |
| `TELEGRAM_CHAT_ID` | `telegram_io.py` | same | CONFIG |
| `TELEGRAM_ALLOWED_IDS` | `telegram_io.py` | same | EMPTY (not blocking: when empty, only `TELEGRAM_CHAT_ID` is authorized, `telegram_io.py` `_msg_authorized`) |
| `FORGE_SELF_IMPROVE` | `review_agent.py` (`self_improve_on`) | n/a (knob) | knob, default off: gates every automatic `learn()` and `deploy/daily_learn.sh` |
| `FORGE_CHAT_ROUTER` | `review_agent.py` (`chat_models`) | n/a (knob) | knob, default on: tool-loop chat starts on Haiku and restarts on Sonnet; `0` = straight to Sonnet |
| `FORGE_CHAT_LIVE` | `dash_live.py` | n/a (knob) | knob, default on: `0` turns the read-only live-data chat tools off |

## Marcus (wholesale), lanes Scout, Atlas, Follow-up, ACE, Autopilot

Engine files: `forge rei/marcus_screening.py`, `forge rei/marcus_engine.py`, `forge rei/marcus_chat.py`,
`forge rei/scout_triage.py`, `forge rei/followup.py`, `forge rei/ace.py`, `forge rei/autopilot.py`, `forge rei/deal_prep.py`.

| Env var | Read by | master.env name | Status |
|---|---|---|---|
| `MARCUS_ANTHROPIC_API_KEY`, then `ANTHROPIC_API_KEY` | `marcus_screening.py` (`marcus.env`) | `ANTHROPIC_API_KEY__WHOLESALE` (plain name: not listed) | OK |
| `ANTHROPIC_API_KEY` | `marcus_engine.py` (also scans `ghl.env`) | `ANTHROPIC_API_KEY__WHOLESALE` | OK |
| `SCOUT_ANTHROPIC_API_KEY`, then `ANTHROPIC_API_KEY` | `scout_triage.py` (`scout.env`) | `ANTHROPIC_API_KEY__WHOLESALE` | OK |
| `GHL_API_KEY` | `connector.py` config (`ghl.env`), used by every wholesale lane | `GHL_API_KEY__WHOLESALE` | OK |
| `GHL_LOCATION_ID` | `connector.py` config | `GHL_LOCATION_ID__WHOLESALE` | CONFIG |
| `GHL_BASE_URL`, `GHL_API_VERSION` | `connector.py` config | same | CONFIG |
| Scout knobs: `FORGE_SCOUT_INTERVAL`, `FORGE_SCOUT_BATCH`, `FORGE_SCOUT_PAGES`, `FORGE_SCOUT_LEARN_EVERY`, `FORGE_SCOUT_LEARN_GAP_MIN`, `FORGE_SCOUT_AUDIT_CANDIDATES`, `FORGE_SCOUT_AUDIT_MSGS`, `FORGE_SCOUT_AUDIT_PAGES`, `FORGE_SCOUT_AUDIT_RETRY_MIN`, `FORGE_SCOUT_AUTOTAG_HOT`, `FORGE_SCOUT_AUTOPIPE_HOT`, `FORGE_SCOUT_PIPELINE`, `FORGE_OFFER_TAG`, `FORGE_STAGE_OFFER`, `FORGE_STAGE_CONTRACT`, `FORGE_STAGE_CLOSED` | `scout_triage.py` | n/a | knobs |
| Marcus knobs: `FORGE_SCREEN_AUTO`, `FORGE_SCREEN_MSGS`, `FORGE_MARCUS_LEARN_EVERY`, `FORGE_MARCUS_LEARN_GAP_MIN`, `FORGE_QUIET_HOURS`, `FORGE_QUIET_START`, `FORGE_QUIET_END`, `FORGE_TZ` | `marcus_screening.py`, `marcus_engine.py` | n/a | knobs |
| Lane knobs: `FORGE_FOLLOWUP_INTERVAL`, `FORGE_FOLLOWUP_PER_SWEEP`, `FORGE_FOLLOWUP_SCAN`, `FORGE_FOLLOWUP_TIERS`, `FORGE_CHECKBACK_MAX`, `FORGE_ACE_CAP_FULL`, `FORGE_ACE_CAP_SUPERVISED`, `FORGE_ACE_MAX_REPLIES`, `FORGE_ACE_PIVOT_RESERVE`, `FORGE_AUTOPILOT_CAP`, `FORGE_PREP_AUTO`, `FORGE_PREP_MSGS`, `FORGE_PREP_SWEEP_CAP`, `FORGE_ATLAS_LEARN_EVERY`, `FORGE_ATLAS_LEARN_GAP_MIN` | `followup.py`, `ace.py`, `autopilot.py`, `deal_prep.py` | n/a | knobs |

Suggested MCPs (not read from code): GoHighLevel (wholesale location only), brain (vault playbooks
and `memory_search`), Claude_Browser (dashboard checks).

## Dyson and Eco (agency)

Engine files: `forge rei/agency_agents.py`, `forge rei/agency_dyson.py`, `forge rei/agency_eco.py`,
`forge rei/agency_ads.py`. Dyson's apply step also reads `forge rei/agency_deploy.py`; Eco's Meta
reads go through `forge rei/pipeboard_io.py`.

| Env var | Read by | master.env name | Status |
|---|---|---|---|
| `AGENCY_ANTHROPIC_API_KEY`, then `ANTHROPIC_API_KEY` in `agency.env`, then the wholesale key | `agency_agents.py` (`_agency_key`; `agency_dyson.py` and `agency_eco.py` delegate to it) | `ANTHROPIC_API_KEY__AGENCY`; fallback `ANTHROPIC_API_KEY__WHOLESALE` | OK / OK |
| `GITHUB_TOKEN` | `agency_deploy.py` (Dyson ship step; missing = "queued, needs GITHUB_TOKEN") | `GITHUB_TOKEN` | OK |
| `GITHUB_DEPLOY_MAP` | `agency_deploy.py` | not listed | Not listed |
| `META_ACCESS_TOKEN` | `agency_ads.py`, `agency_eco.py` (`approve_ad` needs it to build a PAUSED ad) | no agency label. `META_ACCESS_TOKEN__AGENTIC_OS` and `META_ACCESS_TOKEN__DAYCARE` exist but are other accounts | Not listed for agency. Both labelled tokens are FAIL |
| `META_AD_ACCOUNT_MAP` | `agency_ads.py` | `META_AD_ACCOUNT_MAP__DAYCARE`, `__DROPSHIP` exist; none for agency | Not listed for agency |
| `META_PAGE_ID`, `META_DEFAULT_LINK` | `agency_eco.py` (ad spec) | not listed (`META_FB_PAGE_ID` is a different name) | Not listed |
| `PIPEBOARD_API_TOKEN`, `PIPEBOARD_AD_ACCOUNT_ID`, `PIPEBOARD_MCP_URL` | `pipeboard_io.py`, used by `agency_ads.py` | `PIPEBOARD_API_TOKEN__GLOBAL`, `PIPEBOARD_API_TOKEN__DAYCARE`, `PIPEBOARD_AD_ACCOUNT_ID` | OK / OK / CONFIG. The Pipeboard login's only Meta account is the daycare's, so Eco must not report it as agency data (`agency_agents.py` `_eco_context`) |
| `HIGGSFIELD_API_KEY`, `HIGGSFIELD_API_SECRET` | `agency_eco.py` (concept images) | same | UNTESTED / UNTESTED |
| `AGENCY_LEARN_EVERY` | `agency_agents.py` | n/a | knob (12) |

Suggested MCPs (not read from code): Dyson: GitHub, Vercel, brain, Claude_Browser. Eco: Meta Ads
(Pipeboard and official Meta), GetHookd, Canva, Higgsfield, Metricool. Any ad write is T2 plus owner approval.

## Solomon (daycare), lanes Replies, Leads, Starts, Calendar

Engine files: `forge rei/daycare_director.py`, `forge rei/daycare_replies.py`, `forge rei/daycare_leads.py`,
`forge rei/daycare_starts.py`, `forge rei/daycare_calendar.py`, `forge rei/google_cal_io.py`. The lanes
import `forge rei/daycare_ghl.py` and `forge rei/daycare_supabase.py` for CRM and database access.

| Env var | Read by | master.env name | Status |
|---|---|---|---|
| `SOLOMON_ANTHROPIC_API_KEY`, then `ANTHROPIC_API_KEY`, then the agency key, then the wholesale key | `daycare_director.py` (`_solomon_key`); `daycare_replies.py` uses the same key | `ANTHROPIC_API_KEY__DAYCARE_AGENT`; fallbacks `__AGENCY`, `__WHOLESALE` | FAIL (HTTP 401) / OK / OK. Note: the chain skips only placeholder values, so a present-but-rejected key does not fall through |
| `GHL_API_KEY` | `daycare_ghl.py` (`daycare.env`), used by Replies, Leads, Starts, Calendar; presence check in `daycare_director.py` | `GHL_API_KEY__DAYCARE` | OK |
| `GHL_LOCATION_ID` | `daycare_ghl.py` | no `__DAYCARE` entry. `GHL_LOCATION_ID__AGENCY` lists `daycare.env` among its sources | CONFIG. Unknown whether that is the daycare location; check before using it |
| `NEXT_PUBLIC_SUPABASE_URL` (also `DAYCARE_SUPABASE_URL`, `SUPABASE_URL`) | `daycare_director.py` presence check; `daycare_supabase.py` | `NEXT_PUBLIC_SUPABASE_URL` | CONFIG |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` (also `DAYCARE_SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_ANON_KEY`) | `daycare_supabase.py` | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | OK |
| `DAYCARE_SUPABASE_LOCATION_ID`, `DAYCARE_SUPABASE_LOGIN_DOMAIN` (also `SUPABASE_LOCATION_ID`, `SUPABASE_LOGIN_DOMAIN`) | `daycare_supabase.py` | same | CONFIG |
| `STRIPE_SECRET_KEY` | `daycare_director.py` presence check only | `STRIPE_SECRET_KEY__DAYCARE` (also `__DAYCARE_TEST`, `__DRAFT`) | OK / UNTESTED / OK |
| `META_ACCESS_TOKEN` | `daycare_director.py` presence check (a token Meta rejected counts as not connected) | `META_ACCESS_TOKEN__DAYCARE` | FAIL |
| `METRICOOL_USER_TOKEN` | `daycare_director.py` presence check | same | EMPTY |
| `GOOGLE_CAL_ID`, `GOOGLE_CAL_ID_QA` | `google_cal_io.py`, `daycare_calendar.py` | same | CONFIG |
| `GOOGLE_CAL_REFRESH_YAHJAIR` | `google_cal_io.py` | same | CONFIG (STATUS.md does not test it) |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` | `google_cal_io.py` (shared Desktop OAuth client) | same | OK / OK |
| `RESEND_API_KEY`, `RESEND_FROM` | `daycare_calendar.py` (owner email when a tour lands) | same | UNTESTED / CONFIG |
| `FORGE_DAYCARE_CAL_QA` | `daycare_calendar.py` | same | CONFIG |
| Knobs: `FORGE_SOLOMON_BRIEF`, `FORGE_SOLOMON_BRIEF_EVERY_H`, `FORGE_SOLOMON_BRIEF_TOKENS`, `FORGE_SOLOMON_LEARN_EVERY`, `FORGE_SOLOMON_LEARN_GAP_MIN`, `FORGE_DAYCARE_REPLIES_INTERVAL`, `FORGE_DAYCARE_REPLY_AUTO`, `FORGE_DAYCARE_AUTO_CAP`, `FORGE_DAYCARE_REPLY_GRACE_SEC`, `FORGE_DAYCARE_REPLY_MAX`, `FORGE_DAYCARE_REPLY_MODEL`, `FORGE_DAYCARE_LEADS_INTERVAL`, `FORGE_DAYCARE_STARTS_INTERVAL`, `FORGE_DAYCARE_CAL_INTERVAL` | the files named on each card | n/a | knobs |

Suggested MCPs (not read from code): Supabase (project `eqblpbeqothkpyqiafzs`), GoHighLevel (daycare
location only), Google Calendar, Gmail (drafts only), Stripe (read), Meta Ads / Pipeboard (read), Vercel, brain.

## Midas (dropship) — ARCHIVED, kept ready for reactivation

Engine file: `forge rei/dropship_director.py`, plus the `forge rei/dropship_*.py` modules it calls
(`dropship_shopify.py`, `dropship_autods.py`, `dropship_gethookd.py`, `dropship_winninghunter.py`,
`dropship_pipiads.py`, `dropship_adspy.py`). Reactivate from Mission Control; the loop stays off until
`FORGE_DROPSHIP_BRIEF=1`.

| Env var | Read by | master.env name | Status |
|---|---|---|---|
| `DROPSHIP_ANTHROPIC_API_KEY`, then `ANTHROPIC_API_KEY`, then the agency key, then the wholesale key | `dropship_director.py` (`_midas_key`) | no dropship label; fallbacks `ANTHROPIC_API_KEY__AGENCY`, `__WHOLESALE` | Not listed / OK / OK |
| `SHOPIFY_ADMIN_TOKEN` | `dropship_director.py`, `dropship_shopify.py` | same | FAIL (HTTP 401) |
| `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_API_VERSION` | `dropship_shopify.py` (domain also in `dropship_io.py`) | same | CONFIG |
| `AUTODS_API_KEY`, `AUTODS_STORE_ID` | `dropship_autods.py` | same | UNTESTED / CONFIG |
| `AUTODS_MCP_URL`, `AUTODS_MCP_TOKEN`, `SHOPIFY_STOREFRONT_MCP_URL` | `dropship_io.py` | not listed | Not listed |
| `GETHOOKED_API_KEY` | `dropship_gethookd.py` | same | UNTESTED |
| `WINNINGHUNTER_API_KEY` | `dropship_winninghunter.py` | `WINNINGHUNTER_API_KEY` | EMPTY |
| `WINNINGHUNTER_MCP_URL`, `WINNINGHUNTER_MCP_TOKEN` | `dropship_io.py` | not listed | Not listed |
| `EVERBEE_CLIENT_ID` | `dropship_director.py` | same | EMPTY (`EVERBEE_CLIENT_SECRET` also EMPTY) |
| `PIPIADS_API_KEY` | `dropship_pipiads.py` | not listed | Not listed |
| `APIFY_TOKEN`, `DROPSHIP_ADSPY_ACTOR` | `dropship_adspy.py` | same | OK / CONFIG |
| `HIGGSFIELD_API_KEY` | `dropship_director.py` | same | UNTESTED |
| `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_MAP` | `dropship_director.py` (read from `dropship.env`, scoped per call so they do not leak into other workspaces) | `META_AD_ACCOUNT_MAP__DROPSHIP`. No dropship-labelled token; `META_ACCESS_TOKEN__AGENTIC_OS` and `__DAYCARE` are other accounts | CONFIG / Not listed for dropship. Both labelled tokens are FAIL |
| `KLAVIYO_API_KEY`, `TIKTOK_ACCESS_TOKEN`, `AFTERSHIP_API_KEY` | `dropship_director.py` (no client module; presence only) | not listed | Not listed |
| Knobs: `FORGE_DROPSHIP_BRIEF`, `FORGE_DROPSHIP_BRIEF_EVERY_H`, `FORGE_DROPSHIP_BRIEF_TOKENS`, `FORGE_DROPSHIP_LEARN_EVERY`, `FORGE_DROPSHIP_LEARN_GAP_MIN` | `dropship_director.py`, `agents_hub.py` | n/a | knobs |

Suggested MCPs (not read from code): Shopify, GetHookd, Apify, Higgsfield, Meta Ads (read), n8n.

## Orion (head agent, cross-business)

Engine file: `forge rei/mission_control_agent.py` (built as `ORION` in `forge rei/connector.py`).

| Env var | Read by | master.env name | Status |
|---|---|---|---|
| `MISSION_ANTHROPIC_API_KEY`, then `ANTHROPIC_API_KEY`, then the agency key, then the Midas key, then the review (wholesale) key | `mission_control_agent.py` (`_ceo_key`) | no mission label; fallbacks `ANTHROPIC_API_KEY__AGENCY`, `__WHOLESALE` | Not listed / OK / OK |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (HQ chat is Orion's default) | `telegram_io.py` | same | OK / CONFIG |
| Knobs: `FORGE_MISSION_BRIEF_HOUR`, `FORGE_MISSION_LEARN_EVERY`, `FORGE_TZ_OFFSET`, `FORGE_MISSION_BRIEF_TELEGRAM`, `FORGE_BRIEFS`, `FORGE_BRIEF_CHECK_SEC` | `mission_control_agent.py`, `connector.py` | n/a | knobs. The scheduled brief runs only when `FORGE_BRIEFS=1` (default off) |

Orion reads other agents' state through the dashboard API, so it needs no business keys of its own.
Suggested MCPs (not read from code): brain, scheduled-tasks, Vercel (runtime logs).

## Agent gateway (n8n → box)

| Var | Where | Purpose |
|---|---|---|
| `FORGE_GATEWAY_PORT` | `/etc/default/forge-reios` | Starts the listener on 127.0.0.1. Unset = off |
| `FORGE_GATEWAY_WORKFLOW_KEY_SHA256` | same | Hash of the key n8n workflows send |
| `FORGE_GATEWAY_OWNER_KEY_SHA256` | same | Hash of the key `FORGE Agent Chat` sends |
| `FORGE_GATEWAY_OWNER_IDS` | same | Telegram user ids allowed in owner chat |

Plain keys live only in n8n credentials and `~/.agent-keys/forge-gateway.env`. Each job's child gets
exactly one Anthropic key plus a per-job token.

## Broken or empty keys that block an agent (STATUS.md, 2026-10-31)

| Agent | Key | Status | What it blocks |
|---|---|---|---|
| Solomon | `ANTHROPIC_API_KEY__DAYCARE_AGENT` | FAIL (401) | Solomon's own Claude key, if his env resolves to it. Unknown which value his box env holds; a rejected value does not fall back to the agency or wholesale key |
| Solomon | `META_ACCESS_TOKEN__DAYCARE` | FAIL (401) | Meta shows "not connected" in his connected-systems read; the Pipeboard path (`PIPEBOARD_API_TOKEN__DAYCARE`, OK) is separate |
| Solomon | `METRICOOL_USER_TOKEN` | EMPTY | Social is not connected |
| Solomon | `RESEND_API_KEY` | UNTESTED | Owner email on a new tour: unconfirmed |
| Eco / Dyson | `META_ACCESS_TOKEN` (agency) | Not listed; both labelled tokens FAIL | Eco cannot build a PAUSED ad ("queued, needs META_ACCESS_TOKEN") |
| Eco | `HIGGSFIELD_API_KEY`, `HIGGSFIELD_API_SECRET` | UNTESTED | Concept images: unconfirmed |
| Midas | `SHOPIFY_ADMIN_TOKEN` | FAIL (401) | Store snapshot, orders, listings |
| Midas | `WINNINGHUNTER_API_KEY`, `EVERBEE_CLIENT_ID`, `EVERBEE_CLIENT_SECRET` | EMPTY | Product research sources |
| Midas | `META_ACCESS_TOKEN` (dropship) | Not listed; both labelled tokens FAIL | Ad performance reads |
| Marcus | none | n/a | No broken key on his path |
| Orion | none | n/a | `TELEGRAM_ALLOWED_IDS` is EMPTY but only means no extra users |
