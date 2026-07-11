# FORGE REI OS — Live GoHighLevel Connection

The dashboard mirrors your GoHighLevel account in real time. No new database,
no new service — it reuses the GHL credentials already configured for Marcus.

## Run it

```bash
cd "forge rei dash/forge rei"
./start.sh          # serves UI + GHL data on http://localhost:7799
```

Or: `python3 connector.py` then open <http://localhost:7799>.

The connector **must stay running** — it holds the GHL token server-side
(never exposed to the browser) and proxies read-only calls to GoHighLevel.

## What's wired

| Source of truth | GoHighLevel (location `8GuqpADet7ivY7wXWTpV`) |
|---|---|
| Credentials | `../marcus-wholesale-agent/config/ghl.env` (reused, not duplicated) |
| API | `services.leadconnectorhq.com` v2021-07-28 |

### Pages
- **Dashboard** — Total Leads, Active Conversations, Open Opportunities,
  Pipeline Value, Appointments, Tasks Due Today (+ latest leads, open tasks,
  live conversations, pipeline overview). Auto-refresh 30s.
- **Leads** — contacts pull, server-side search, tag filter, detail drawer.
- **Conversations** — all conversations, latest message, unread badges,
  10s auto-refresh.
- **Pipeline** — all opportunities by stage with deal values; switch between
  Marketing and Wholesaling pipelines.
- **Tasks** — aggregated from contacts (GHL has no global task endpoint, so the
  connector scans recent contacts for tasks).

## API endpoints (read-only)
`/api/health` · `/api/dashboard` · `/api/contacts?limit=&query=` ·
`/api/conversations?limit=` · `/api/pipeline` · `/api/tasks?scan=`

Responses cache 45s; 429/5xx retried with backoff to stay under GHL rate limits.

## Notes / limits
- **Read-only by design.** Nothing writes back to GHL yet.
- **Appointments** derive from the "Appointment Set" pipeline stage — no GHL
  calendars are configured on this location.
- **Tasks** require scanning contacts; the dashboard scans 30, the Tasks page 60.
  Raise `scan=` if you keep tasks on older contacts.
- Port override: `FORGE_PORT=8080 ./start.sh`.
