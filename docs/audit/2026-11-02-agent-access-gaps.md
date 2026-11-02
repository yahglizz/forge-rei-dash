# Agent access gaps (2026-11-02)

What FORGE agents can reach from chat, what they cannot, and what the owner has to do. Read-only
everywhere; no secrets in this file. "Unknown" means not checked from the repo.

| System | What agents read now | What is missing | Owner action |
|---|---|---|---|
| Stripe | `GET /api/stripe/status` (key works, test or live mode, available and pending balance, agency link-maker state) and `GET /api/stripe/offers` (agency offers). Added this task: both were GETs under no agent scope. Scope is the two exact paths, so `POST /api/stripe/link` stays a tap card and out of agent reach. | No customer, charge, invoice or subscription reads. Whether the box holds a Stripe key: Unknown (not read). | None to use what exists. To let agents see payments, decide which Stripe objects (a read-only restricted key is enough) and ask for a route. |
| Google Calendar | `GET /api/daycare/calendar`: the daycare lane's own mirror (tours and first days in the next 14 days, no network on the request). | `google_cal_io.py` has one Google identity and refuses any calendar except the daycare live and QA ones, and it only writes. No second account is configured in code, so no new route was added. No wholesale, agency or personal calendar. | If wanted: say which calendar and account. It needs its own read-only refresh token and calendar id, never the daycare token reused. |
| Gmail | `GET /api/daycare/mail` and `/api/daycare/mail/thread`: one identity, filtered to the daycare. | `gmail_io.py` has one identity (the daycare's). No wholesale or agency inbox is configured, so nothing added. The `__DAYCARE` and `__WHOLESALE` accounts are never crossed. | If wanted: a separate `__WHOLESALE` (or agency) read-only Gmail token and a route that uses only that account. Needs a go from the owner. |
| Vercel | `GET /api/agency/deploy/status`. It reports the GitHub deploy token, not Vercel. | No Vercel token is referenced anywhere in the repo's Python, so no route was added. Whether the box has one: Unknown (env not read). | If wanted: a team-scoped read-only Vercel token on the box, then a deployments and runtime-errors route. |
| n8n | New `GET /api/system/n8n`: runs this month, failures this month, last 10 runs, last 10 failures (workflow name, status, times only; no error text, no key, no host). Under the existing no-taint `/api/system` prefix. One try per request, 15 s total (then `partial: true`), cached 60 s. | The box has no `N8N_BASE_URL` or `N8N_API_KEY`, so it answers exactly `{"connected": false}`. | Create an n8n API key (n8n Settings, API). Put `N8N_BASE_URL` and `N8N_API_KEY` in `/etc/default/forge-reios` and restart. Takes about 5 minutes. |
| Brain | `/api/brain/search`, `/api/brain/recent`, `/api/brain/note` were already readable in every chat. Added this task: both are now on the scheduled, non-parent task `solomon.pipeline_review`. | Parent-triggered (`solomon.tour_followup`) and lead-triggered (`dyson.lead_review`) tasks stay narrow on purpose. | None. |
| Owner's Mac | `mac_status`, `mac_run` (Task 4), gated. | Agents were never told in the prompt blurb; now named. | None. |

## Also changed

- `escalate` tool text and one routing line on the cheap-model turn: planning, recommendations, writing for anyone, money decisions and multi-step work go to Sonnet.
- Agents are told about Stripe, the daycare Calendar, n8n runs, the brain and (when offered) the Mac in the "what can you do" line and the HQ route hints.
- No `DENY` entry changed. No write route added. `MAC_CLEAN_PREFIXES` unchanged: none of the new reads is Mac-clean.
