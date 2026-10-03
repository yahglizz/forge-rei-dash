# CRM parity and migration status

Audit snapshot: 2026-10-03. This document records the first CRM slice built from the
existing dashboard. GoHighLevel remains the production source of truth.

## Current architecture

- The dashboard is static React UMD + in-browser Babel with no build step.
- `forge rei/connector.py` is the stdlib HTTP server and already owns three isolated
  `GHLClient` instances: wholesale, agency, and daycare.
- Wholesale CRM reads already exist at `/api/contacts`, `/api/conversations`,
  `/api/messages`, `/api/pipeline`, `/api/tasks`, and `/api/dashboard`.
- Existing outbound actions remain behind the current approval/safety gates. This slice
  adds no POST route and no GHL write.
- Daycare enrollment leads are read and derived by `daycare_leads.py`; family messaging
  and Supabase center data remain separate systems with their existing ownership rules.
- Agency has separate GHL read adapters in `agency_ghl.py` and its own client/workflow UI.
- n8n is an existing external workflow path; this CRM slice does not replace or reroute it.

## First vertical slice

`forge rei/crm.jsx` adds a native `CRM` page to the REI workspace. It composes the existing
`/api/dashboard` read model (including the new recent-conversation, pipeline-stage, and open-task
summaries) plus the existing action log into one operator view:

- contacts, unread conversations, open opportunities, follow-up tasks, and appointment
  pipeline signals;
- recent conversations with a jump to the existing inbox;
- pipeline stage activity with a jump to the existing kanban;
- open follow-ups and the existing durable agent/action log;
- an explicit read-only / GHL-reference label.

No new database, sync worker, automation engine, credential, or provider was introduced. Keeping
the page on the shared dashboard aggregation avoids multiplying GHL requests and preserves the
existing connector retry/cache behavior.

## Parity matrix

| Feature | GHL status | FORGE status | Sync/status | Test status | Production status |
|---|---|---|---|---|---|
| Contacts | Live source of truth | Existing `/api/contacts` + Leads UI | Read-through | Existing route/UI checks | No cutover |
| Contact detail/activity | Live | Lead drawer + existing messages read | Read-through | Existing UI path | No cutover |
| Conversations/SMS | Live | Existing inbox/thread reads; sends remain gated | Read-through | Existing SMS safety tests | GHL remains sender |
| Pipelines/opportunities | Live | Existing read-only kanban + CRM summary | Read-through | Existing pipeline tests | No stage migration |
| Tasks/follow-ups | Live per contact | Existing aggregate read + local reminder overlay | Best-effort read | Existing toolkit tests | No task migration |
| Appointments | Live capability not yet mapped | Count only when exposed as a pipeline signal | Not yet mapped | Not yet implemented | GHL unchanged |
| Source/attribution | GHL contact/source fields and daycare tags exist | Visible in existing contact/lead surfaces; not normalized | Not yet normalized | Partial | GHL unchanged |
| Automations | Existing GHL workflows + external n8n | Activity visibility only | No replacement engine | Not yet implemented | GHL/n8n unchanged |
| Agent CRM tools | Existing agent-specific paths | No new unrestricted tool layer | Not unified | Not yet implemented | Existing agents unchanged |

## Safest next step

Add a provider-neutral read model behind the existing GHL adapters, beginning with contact,
conversation, opportunity, task, and raw source metadata. Keep it shadow/read-only until
field mappings and idempotent comparison tests against each GHL location pass. Calendar,
automation execution, controlled writes, and daycare enrollment parity follow that proof.
