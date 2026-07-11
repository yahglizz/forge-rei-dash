# Forge AI Agency — Dashboard Features

Everything below lives inside the **Agency workspace** of FORGE REI OS (switch via
the profile menu, top-right → *Forge AI Agency*). It is fully separate from the
REI / wholesale side. All data is **mock + locally persisted** for now, with clean
seams to swap in real APIs/DB later.

> Architecture reminder: this dashboard has **no build step**. Each `.jsx` is loaded
> as `<script type="text/babel">` and transformed in the browser. All scripts share
> one global scope, so every agency file uses **unique hook aliases** (`useStateDy`,
> `useStateEc`, …) and **prefixed top-level names** (`Dy*`, `Ec*`, `Ap*`, …) and
> ships its page component on `window`. Never write a computed JSX tag (`<Icons[x]/>`)
> — it white-screens the app.

---

## 1. What was added

| Section | Nav label | Page component | What it does |
|---|---|---|---|
| Client Edit Requests | **Edit Requests** | `AgencyRequests` | Submit/edit client change requests, status flow, history, admin approval, "Send to Dyson" |
| Agents hub | **Agents** | `AgencyAgents` | Roster of operable AI agents (Dyson, Eco). Open one to chat, assign tasks, or operate it. Live, Anthropic-backed |
| Dyson agent | (via Agents) | `AgencyDyson` | Edit agent — drafts a plan (affected files/pages/workflows, risk, steps) per request; waits for approval |
| n8n workflows | **Workflows** | `AgencyWorkflows` | Connection settings, workflow list + detail, draft/edit mode, approval-before-push |
| Client dashboard | **Client View** | `AgencyClientView` | Client-facing view: profile selector, submit request, status tracker, delivered updates, analytics |
| Meta Ads analytics | **Meta Ads** | `AgencyAds` | Connection settings, account selector, 10 metric cards, campaign table, top/weak ad tables |
| Eco agent | **Eco** | `AgencyEco` | Ads strategist — best/weak ads, next 3 ad concepts (hook/headline/copy/CTA/creative), competitor placeholder |
| Approval Center | **Approvals** | `AgencyApprovals` | One queue for Dyson + workflow + Eco items; Approve / Request Revision / Reject |

Plus a **reusable component library** (`window.AgUI`) and **6 backend modules**.

The existing agency pages (Dashboard, Clients, Pipeline, Projects, Revenue,
Settings) and the entire REI side are unchanged.

---

## 2. Folder structure

All files live in the web root `~/forge rei dash/forge rei/`.

```
Frontend (.jsx, browser-transformed)
  agency_ui.jsx           reusable comps  -> window.AgUI.*
  agency_requests.jsx     -> window.AgencyRequests   (also the GOLD template)
  agency_dyson.jsx        -> window.AgencyDyson
  agency_workflows.jsx    -> window.AgencyWorkflows
  agency_clientview.jsx   -> window.AgencyClientView
  agency_ads.jsx          -> window.AgencyAds
  agency_eco.jsx          -> window.AgencyEco
  agency_approvals.jsx    -> window.AgencyApprovals
  agency.jsx              (existing) Dashboard/Clients/Pipeline/Projects/Revenue/Settings

Backend (Python stdlib, in connector.py's process)
  agency_requests_io.py   edit-requests store + admin status flow
  agency_dyson.py         Dyson draft generation (mock heuristics)
  agency_workflows_io.py  n8n workflow mock catalog + draft store
  agency_ads.py           Meta Ads mock analytics (read model)
  agency_eco.py           Eco recommendation engine (mock)
  agency_approvals_io.py  central approval queue

Wiring (edited, additive only)
  connector.py            imports + GET routes + POST dispatch
  data.jsx                AGENCY_NAV (nav entries)
  app.jsx                 AGENCY_PAGES (router)
  icons.jsx               new section icons
  FORGE REI OS.html       <script> tags

Secrets (separate, OUTSIDE web root)
  ../forge-agency/config/agency.env   (agency GHL + Anthropic keys)
```

### Reusable components — `window.AgUI`
`Badge`, `StatusBadge`, `PriorityBadge`, `RiskBadge`, `KindBadge`,
`ClientSelector`, `RequestForm`, `AnalyticsCard`, `ApprovalCard`,
`AgentRecCard`, `WorkflowCard`, plus shared maps (`PRIORITY`, `REQ_STATUS`,
`RISK`, `APPROVAL_STATUS`, `KIND`, `TYPES`, `PRIORITIES`) and helpers
(`inp`, `field`, `fieldLabel`, `money`).

---

## 3. Mock data locations

Each backend module ships a `_SEED` / `_MOCK_*` block and persists runtime
changes to a JSON file under `marcus_state/` (gitignored, excluded from deploy,
so the box always starts from seeds):

| Data | Seed in | Persists to |
|---|---|---|
| Clients | `agency_io.py` (existing) | `marcus_state/agency.json` |
| Edit requests | `agency_requests_io.py` `_SEED` | `marcus_state/agency_requests.json` |
| Dyson drafts | generated at runtime | `marcus_state/agency_dyson.json` |
| n8n workflows | `agency_workflows_io.py` `_MOCK_WORKFLOWS` | `marcus_state/agency_workflows.json` (drafts only) |
| Meta Ads | `agency_ads.py` `_DATA` (pure read model) | — none — |
| Eco rec sets | generated at runtime | `marcus_state/agency_eco.json` |
| Approval queue | `agency_approvals_io.py` `_SEED` | `marcus_state/agency_approvals.json` |

To reset to clean seeds: delete the relevant `marcus_state/agency_*.json` file.

---

## 4. API endpoints

GET: `/api/agency/requests`, `/api/agency/dyson/drafts`,
`/api/agency/workflows`, `/api/agency/ads` (`?account=`),
`/api/agency/ads/accounts`, `/api/agency/eco` (`?client=`),
`/api/agency/approvals` (`?status=`)

POST: `/api/agency/request/save`, `/api/agency/request/delete`,
`/api/agency/request/status`, `/api/agency/dyson/generate`,
`/api/agency/dyson/decision`, `/api/agency/workflow/save`,
`/api/agency/workflow/decision`, `/api/agency/eco/generate`,
`/api/agency/eco/decision`, `/api/agency/approval/decision`

---

## 4b. The Agents tab (live, Anthropic-backed)

The **Agents** tab is the hub for your AI team. Dyson and Eco live here as
operable agents (the standalone Dyson/Eco nav entries were folded in here; their
operate panels are embedded, nothing removed).

- **Roster** — a card per agent with status (ONLINE when the Anthropic key is
  present), open-task count, and message count.
- **Open an agent** → a console with three tabs:
  - **Chat** — talk to the agent. Real Claude (`claude-sonnet-4-5`) via the
    agency key, grounded with live context (Dyson sees open edit requests; Eco
    sees client ad metrics). History **syncs** server-side.
  - **Tasks** — assign a task; the agent drafts a plan (Claude) and queues it.
    Mark Start / Done / Cancel. Tasks persist.
  - **Operate** — the agent's full operating panel embedded (`AgencyDyson` /
    `AgencyEco`).

**Login + sync:**
- *Login* = the Anthropic key. `agency_agents._agency_key()` resolves it in order:
  `AGENCY_ANTHROPIC_API_KEY` env → `ANTHROPIC_API_KEY` in
  `forge-agency/config/agency.env` (the agency's own key) → wholesale key fallback.
  The status banner shows connected state + which key source is in use.
- *Sync* = chat history (last 60 turns/agent) + all tasks persist to
  `marcus_state/agency_agents.json`, so they survive reloads/restarts.

Backend: `agency_agents.py` (reuses `review_agent._claude` + `review_agent.MODEL`).
Endpoints — GET `/api/agency/agents`, `/api/agency/agents/history?agent=`,
`/api/agency/agents/tasks?agent=`; POST `/api/agency/agents/chat`,
`/api/agency/agents/task`, `/api/agency/agents/task/update`.

To add a third agent: add an entry to `_AGENTS` in `agency_agents.py` (id, name,
role, system prompt, and a `page` for its operate panel) — the roster, chat, and
tasks all pick it up automatically.

---

## 5. How Dyson works

Dyson is the **edit agent**. Flow:

1. A client edit request exists (Edit Requests tab, or Client View).
2. You hit **Send to Dyson** (Requests) or pick a request in the Dyson tab and
   click **Ask Dyson to draft**.
3. `agency_dyson.generate_draft(requestId)` builds a plan:
   - **affected** files / pages / workflows
   - **risk** level (low/medium/high) + reason — bumped a notch for high/urgent
     requests
   - **implementation steps**
   It uses a per-request-type heuristic playbook (`_PLAYBOOK`). This is the mock
   "intelligence".
4. The draft is pushed to the **Approval Center** (`agency_approvals_io.add`).
5. **Nothing is applied until you approve.** Approve / Request Revision / Reject
   from the Dyson tab or the Approval Center.

**To make Dyson real:** replace the heuristic block in `generate_draft()` with a
Claude call (the agency's `ANTHROPIC_API_KEY` is already wired) that reads the
request **and the actual client codebase**, returning the same shape. On
*approve*, add the code that applies the edit + flips the request to
`in_progress` / `completed` (see the `FUTURE:` note in `decision()`).

---

## 6. How Eco works

Eco is the **ads strategist**. Flow:

1. Pick a client (Eco tab → *Strategize for*).
2. `agency_eco.recommendations(client)` reads that client's (mock) Meta Ads
   analytics from `agency_ads.py` and returns:
   - **best** ads to scale (ranked by ROAS, then leads)
   - **weak** ads to pause/rework
   - **next 3 ad concepts** — each with angle, hook, headline, primary text, CTA,
     creative direction (drawn from `_ANGLE_LIBRARY`, biased toward winning hooks)
   - a **competitor research placeholder**
3. **Send recommendations to Approval Center** persists a rec set and queues it.
4. Approve / revise / reject from the Approval Center.

**To make Eco real:** replace `_build()` with a Claude call over real
`get_insights` data; wire the competitor placeholder to the Meta Ad Library
(`ads_library_search`). On *approve*, create the ads via the Meta Ads MCP in
**paused** state for final human review.

---

## 7. Future — auth notes

There is **no application-level auth** anywhere yet (REI or Agency). Today the
whole dashboard is protected only by being private (Tailscale / local). Before
exposing publicly **or** giving real clients access to **Client View**:

- Put nginx Basic Auth / an SSO proxy in front of port 7799 (see
  `DEPLOY_DIGITALOCEAN.md`).
- Add a per-client login + scope so a client only sees their own
  `clientId` in Client View / Requests. The data layer already keys requests by
  `clientId`, so this is an access-filter, not a schema change.
- Gate the admin actions (status changes, approvals, decisions) behind an
  "agency staff" role.

---

## 8. Future — database notes

The stores are flat JSON behind a tiny, swappable API (`list_*`, `save_*`,
`set_status`, `delete_*`, `decide`, `add`). To move to a real DB:

- Replace each module's `_load()` / `_save()` with DB reads/writes (SQLite →
  Postgres). Keep the public function signatures identical so no UI changes.
- Add a `clientId` foreign key everywhere (already present on requests).
- Consider one `agency.db` instead of several JSON files; the `_LOCK` per module
  becomes a transaction.

---

## 9. Future — n8n MCP integration notes

`agency_workflows_io.py` currently serves `_MOCK_WORKFLOWS`. The real n8n MCP is
already available to the agent runtime (`mcp__claude_ai_n8n__*`:
`search_workflows`, `get_workflow_details`, `update_workflow`,
`create_workflow_from_code`, `publish_workflow`, …).

To go live:
1. Set `N8N_BASE_URL` + `N8N_API_KEY` as env vars (placeholders only — never
   hardcode). `_connection()` already reports `connected` off these.
2. Replace `list_workflows()` body with an n8n MCP `search_workflows` /
   `get_workflow_details` call.
3. On approval (`decision(..., 'approve')`), call `update_workflow` /
   `publish_workflow` to push the draft. That is the "approval-before-push" gate.

---

## 10. Future — Meta Ads API notes

`agency_ads.py` returns deterministic mock data. Real Meta tooling is available
(`mcp__claude_ai_Pipeboard_Meta_Ads__*` and `mcp__claude_ai_meta_ads__*`:
`get_campaigns`, `get_insights`, `get_ads`, `ads_library_search`, …).

To go live:
1. Set `META_ACCESS_TOKEN` as an env var (placeholder only). `connection()`
   reports `connected` off it.
2. Replace `analytics(account, ...)` body with `get_insights` over the account
   for the last `days`. Keep the output shape identical so `AgencyAds` is
   unchanged.
3. Map each agency client to its real ad account id in `_ACCOUNTS`.

---

## Rules honored in this build

- Existing dashboard **not broken**, **no code removed** (additive wiring only).
- **No auth built** yet (structured so it can be added).
- **No real API keys hardcoded** — env-var placeholders only
  (`N8N_*`, `META_ACCESS_TOKEN`); GHL/Anthropic keys stay in
  `../forge-agency/config/agency.env`, outside the web root.
- Every agent draft is **human-gated** through the Approval Center before
  anything goes live.
