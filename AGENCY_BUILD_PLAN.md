# AGENCY BUILD PLAN — FORGE REI OS (ClientForge side)

> **Purpose:** Bring the agency side of the dashboard fully to life. Every mock flips to
> real, every dead "Approve" button performs its live action, every empty page gets built.
> **Design principle (non-negotiable):** *key-ready & additive*. Every real path is added
> **behind a credential guard** next to the existing mock — `if token: real() else: mock()`.
> Nothing that works today breaks. The moment the operator drops in a key, that surface
> goes live; with no key it still renders mock so the dashboard never errors.
>
> **This file is the source of truth for the build.** Every agent MUST read it before
> editing and return to it whenever unsure. Stay in your assigned FILE LANE (Section 3).
> Do not edit a file owned by another lane.

Base dir (the app): `/Users/yg4st/forge rei dash/forge rei/`
Agency config: `/Users/yg4st/forge rei dash/forge-agency/config/agency.env`
Date started: 2026-06-15

---

## ✅ BUILD STATUS — 2026-06-15 (SHIPPED & LIVE on the box)

All milestones M0–M6 built, validated (ast.parse + smoke boot), reviewed (5 bugs found +
fixed), deployed to `root@24.199.81.124`, SSH-verified: service `active`, all agency
endpoints `200`, `agency.env` `404` over HTTP, no errors in log.

| Milestone | State | Notes |
|-----------|-------|-------|
| M0 env injection | ✅ | `_inject_env` in connector.py — agency.env keys now reach `os.environ` |
| M1 smart agents | ✅ | Dyson draft-gen + Eco recs/competitor = real Claude, heuristic fallback kept |
| M2 live connectors | ✅ | Meta/n8n/Metricool real fetch behind key-guard, mock fallback keyless |
| M3 execute side | ✅ | Approve dispatches by kind → ship/push/create_ad/publish; idempotency-guarded |
| M4 deploy connector | ✅ | `agency_deploy.py` GitHub→Vercel (PR by default, autoMerge optional) |
| M5 frontend polish | ✅ | Settings/Pipeline/Projects/Revenue built; buttons truthful; client-login scaffold (flag OFF) |
| M6 keys punch list | ⏳ | **OPERATOR ACTION — see §4 M6.** Everything runs on mock until keys added. |

**Built so the ONLY remaining step is dropping in keys.** No key = mock still renders
(nothing breaks). Add a key → that surface goes live on next redeploy. Review fixes applied:
settings GET/SAVE shape + key align, double-exec idempotency guards (Dyson ship + Eco ad),
competitor panel now renders the real Claude output.

---

## 0. Standing rules (from CLAUDE.md — these bind every agent)

1. **Additive only.** Never remove a working feature. Keep mock as the fallback branch.
2. **Validate before done.** Python: `python3 -c "import ast; ast.parse(open('FILE').read())"`.
   JSX: every `.jsx` shares ONE global scope after Babel — use unique hook aliases
   (`useStateAg`, `useStateD`, `useStateEc`, …) and unique prefixed top-level names; **no
   computed JSX tags** (`<Icons[x] />` → resolve to a const first). A collision = white screen.
3. **Propose → review → execute.** Agents never take an outward/irreversible action on
   their own. Every live action (ship code, push n8n, create ad, publish post) stays behind
   the operator's one-click Approval Center decision. The decision handler is where the live
   action fires — never on draft/generate.
4. **Secrets stay private.** Keys live only in `agency.env` (outside web root, git-ignored).
   Never served over HTTP (must 404). Never printed in logs or chat.
5. **Deploy is centralized.** Build agents edit + validate **locally only**. They do NOT run
   `deploy/push.sh`. The orchestrator runs ONE coordinated deploy after all lanes validate
   green, then SSH-verifies (service `active`, endpoints 200, secrets 404).

---

## 1. Current state (from the 3-agent audit, 2026-06-15)

**Real today:** Clients CRUD + GHL tag push (live GHL sub-account ✅), Edit Requests CRUD +
history, Approvals queue (persist), Dyson+Eco **chat/tasks** (real Claude + self-improve
loop → brain + git), Social post queue + real best-time heatmap.

**Mock data (identical output shape to real — swap the body, keep the shape):**
- `agency_ads.py` — all Meta numbers hardcoded (`_DATA` ~L29, `_ACCOUNTS` ~L20).
- `agency_workflows_io.py` — 4 fake workflows (`_MOCK_WORKFLOWS` ~L32).
- `agency_social.py` — analytics all zeros (`_ANALYTICS` ~L62).

**Mock logic (heuristic, NO Claude):**
- `agency_dyson.py` `generate_draft()` ~L171 — `_PLAYBOOK` template lookup, no LLM.
- `agency_eco.py` `recommendations()`/`generate()` ~L135/140 — `_ANGLE_LIBRARY` fill, no LLM.
- `agency_eco.py` competitor block ~L125 — explicit `status:"placeholder"`.

**Dead execute side (decision() flips status, fires NO live action):**
- `agency_approvals_io.decide` ~L143 (NOTE future ~L156), `agency_dyson.decision` ~L223
  (FUTURE ~L235), `agency_workflows_io.decision` ~L175 (FUTURE ~L187), `agency_eco.decision`
  ~L171 (FUTURE ~L182), `agency_social.set_status` "ready" ~L198 (no publish).

**Empty/partial pages:** Settings (`agency.jsx:424` placeholder), Pipeline (read-only board),
Projects (no detail), Revenue (no charts), ClientView (preview-only, no login).

**Real bug (M0):** `connector.py:137` loads `agency.env` into a dict for `GHLClient` only —
it never injects into `os.environ`. So `os.environ.get("META_ACCESS_TOKEN")` /`N8N_*`/
`METRICOOL_USER_TOKEN`/`GITHUB_TOKEN` are **always empty even if set in `agency.env`**. This
blocks every credential guard. Must fix first.

**No client-site deploy connector exists at all** (Dyson's real job — built in M4).

---

## 2. Target architecture — the credential-guard pattern

Every connector module exposes the SAME function shape it has today. Add a real fetch path
guarded by a key check; mock is the `else`. Example (`agency_ads.py`):

```python
def analytics(account_id, days=30):
    token = os.environ.get("META_ACCESS_TOKEN")
    if token:
        try:
            return _live_analytics(token, account_id, days)   # NEW: real Meta get_insights
        except Exception as e:
            log(f"[ads] live fetch failed, falling back to mock: {e}")
    return _mock_analytics(account_id, days)                   # EXISTING body, renamed
```

`connection()` reports `connected = bool(token)` and a `source: "live"|"mock"` flag so the
frontend badge tells the truth. Same pattern for n8n, social analytics.

**Connection contract every connector returns** (frontend already reads these keys):
`{ connected: bool, source: "live"|"mock", account|brand|baseUrl: str, todo: str|None }`.

---

## 3. FILE-OWNERSHIP LANES (no two agents share a file)

| Lane | Owner agent | Files (write) | Milestones |
|------|-------------|---------------|------------|
| **A — Backbone** | coder-backbone | `connector.py`, `forge-agency/config/agency.env`, `agency.env.example` | M0 + ALL new route registration for M2/M3/M4 |
| **B — Dyson** | coder-dyson | `agency_dyson.py` | M1 (real Claude draft) + M3 (approve→deploy hook) |
| **C — Eco** | coder-eco | `agency_eco.py` | M1 (real Claude recs + competitor) + M3 (approve→Meta ad) |
| **D — Data connectors** | coder-data | `agency_ads.py`, `agency_workflows_io.py`, `agency_social.py` | M2 (live fetch) + M3 (workflow push, social publish) |
| **E — Deploy** | coder-deploy | `agency_deploy.py` (NEW) | M4 (GitHub→Vercel) |
| **F — Frontend** | coder-frontend | all `agency*.jsx`, `agency.jsx` | M5 (empty pages, enable buttons) |
| **R — Review** | reviewer | read-only | validate all lanes |

**Cross-lane contract (so parallel lanes align without runtime coordination):**
- Module functions live in the owner's `.py`. **Lane A is the ONLY writer of `connector.py`**
  and registers every new route, importing the functions B/C/D/E expose. Function names +
  route paths are frozen in Section 4 below — all lanes use these exact names.
- B's approve hook calls `agency_deploy.ship(client, draft)` (E owns the impl). B imports it.
- C's approve hook calls the Meta ad-create function (D exposes `agency_ads.create_ad(...)`).
- D's workflow push calls n8n; social publish calls Metricool REST/MCP shim.

---

## 4. MILESTONES (exact signatures + routes are FROZEN here)

### M0 — Fix env injection (Lane A, prerequisite for all)
In `connector.py`, after `AGENCY = GHLClient(_load_env(AGENCY_ENV_CANDIDATES), "agency")`
(~L137), inject the non-GHL agency keys into `os.environ` without clobbering real shell vars:

```python
def _inject_env(paths):
    for k, v in _load_env(paths).items():
        if v and k not in os.environ:
            os.environ[k] = v
_inject_env(AGENCY_ENV_CANDIDATES)   # makes META_ACCESS_TOKEN / N8N_* / METRICOOL_* / GITHUB_TOKEN visible
```
Add the new key names (commented, empty) to `agency.env` and `agency.env.example`:
`META_ACCESS_TOKEN`, `META_AD_ACCOUNT_MAP` (json `{"clientId":"act_123"}`), `N8N_BASE_URL`,
`N8N_API_KEY`, `METRICOOL_USER_TOKEN`, `GITHUB_TOKEN`, `GITHUB_DEPLOY_MAP` (json
`{"clientId":"owner/repo"}`). **Never fill values — operator does that.**

### M1 — Smart agents (Lanes B, C — no keys needed)
**Dyson** (`agency_dyson.py`): replace `generate_draft()` heuristic body with a real Claude
call via `review_agent._claude(...)` + `review_agent.MODEL` (same infra `agency_agents.py`
uses). Load Dyson's brain playbook (`brain_io` vault `Skills/dyson-playbook.md`, mtime-cached
like `agency_agents._load_skills`). Prompt: request details + playbook → return JSON
`{summary, risk, affectedFiles[], affectedPages[], steps[], estimate}`. Keep `_PLAYBOOK` as
the fallback if the Claude call fails or no key (`_agency_key()` returns None). Persist
identical draft shape.

**Eco** (`agency_eco.py`): replace `recommendations()`/`generate()` heuristic with a real
Claude call grounded on `agency_ads.analytics()` numbers + Eco playbook. Return same set
shape (best/weak analysis + next-3 concepts). Wire **competitor research** to a real path:
use Claude with a web-search tool if available, else a structured Claude prompt; replace
`status:"placeholder"`. Keep template fallback on failure/no-key.

### M2 — Live connectors, key-ready (Lane D)
- `agency_ads.py`: add `_live_analytics(token, account_id, days)` using Meta Graph API
  `GET /{ad_account}/insights` (urllib, same style as `GHLClient._req`). Map fields →
  existing output shape (spend, impressions, reach, clicks, ctr, cpc, leads, cpl,
  conversions, roas, campaigns[], ads[]). `accounts()` reads `META_AD_ACCOUNT_MAP` when token
  present, else mock accounts. Guard + mock fallback. `connection()` → `source` flag.
- `agency_workflows_io.py`: add `_live_workflows()` hitting n8n REST
  (`GET {N8N_BASE_URL}/api/v1/workflows`, header `X-N8N-API-KEY`). Map → existing workflow
  card shape. Guard on `N8N_BASE_URL && N8N_API_KEY`, else `_MOCK_WORKFLOWS`. Merge local
  drafts as today. `_connection()` → real connected state.
- `agency_social.py`: add real `_live_analytics()` via Metricool REST (if
  `METRICOOL_USER_TOKEN`) for follower/engagement; else keep zeros. `connection()` reports
  `autonomous` truthfully. Best-time heatmap stays (real baked data).

### M3 — Execute side: approve → live action (Lanes B, C, D, A)
The Approval Center is the single gate. `agency_approvals_io.decide()` dispatches by
`item["kind"]` to the owning module's executor (all gated by operator approval only):
- `kind:"dyson"` → `agency_dyson.apply(draft)` → calls `agency_deploy.ship(client, draft)` (M4).
- `kind:"workflow"` → `agency_workflows_io.push(draft)` → n8n create/update + publish.
- `kind:"eco"` → `agency_ads.create_ad(spec, paused=True)` → Meta ad created **PAUSED**
  (never auto-spends; operator un-pauses in Meta).
- `kind:"social"` (post marked ready+approved) → `agency_social.publish(post)` → Metricool
  REST if token, else flag for operator MCP (current behavior) + clear receipt.
Each executor: real action behind try/except, write a result note to the brain + agent bus,
return `{ok, detail, url?}`. On no-key/failure → record "queued, needs key" (never silent).
Lane A registers `agency_approvals_io.decide` already routed; ensure dispatch wired.

### M4 — Deploy connector (Lane E): `agency_deploy.py` (NEW)
GitHub → Vercel flow (operator chose: commit to GitHub, Vercel auto-deploys via its git
integration). Functions:
- `ship(client, draft) -> {ok, commitUrl, prUrl?, detail}`: resolve repo from
  `GITHUB_DEPLOY_MAP[client.id]`; apply draft changes as a commit (or PR) via GitHub API
  (use `mcp__github__*` tools when available in agent runtime, else GitHub REST with
  `GITHUB_TOKEN`). Commit to a branch + open PR for operator merge (safest), OR direct commit
  to a deploy branch if `draft.autoMerge`. Vercel picks up the push automatically.
- `status(client) -> {connected, repo, lastDeploy}`: report config state.
- Guard on `GITHUB_TOKEN`; no key → `{ok:false, detail:"needs GITHUB_TOKEN"}`. Never throw.
Lane A registers `/api/agency/deploy/status` (GET) + the ship path is invoked via M3 approve.

### M5 — Frontend polish + fill empty pages (Lane F)
- **Settings** (`agency.jsx` `AgencySettings`): build real fields — billing source, default
  plan, default services, team members. Persist via a new `/api/agency/settings` (Lane A
  adds route + `agency_io` get/save). Use existing `agInp` styles + `apiPost`.
- **Pipeline** (`agency.jsx` `AgencyPipeline`): add status-change action on cards (click →
  cycle/select status → `/api/agency/client/save`). Drag-drop optional; a status dropdown
  per card is the floor.
- **Projects** (`agency.jsx` `AgencyProjects`): show per-project detail — linked requests,
  open count, last activity, status. Pull from `/api/agency/requests` filtered by client.
- **Revenue** (`agency.jsx` `AgencyRevenue`): add a simple bar/sparkline (reuse any existing
  chart helper in the codebase; else inline SVG bars) for MRR by client + trend.
- **Enable buttons** the backend now powers: Ads "Connect" (show source/connected truthfully,
  remove "coming soon" when `source==='live'`), Workflows "Approve & Push to n8n" (enable when
  n8n connected), Eco "Run competitor research" (enable — backend now real).
- **Client login portal:** scaffold a minimal login gate for ClientView behind a flag
  (`window.AGENCY_CLIENT_LOGIN`), default OFF (operator tests when ready). Keep preview mode
  as the default path.
- Respect collision rules: unique aliases/prefixes, no computed JSX tags.

### M6 — KEYS PUNCH LIST (what the operator hands over)
Drop these into `agency.env`, then redeploy — each flips its surface to live:

| Key | Unlocks | Where to get it |
|-----|---------|-----------------|
| `META_ACCESS_TOKEN` (+ `META_AD_ACCOUNT_MAP`) | Real Meta Ads numbers + ad creation | Meta Business → System User token, ads_read + ads_management |
| `N8N_BASE_URL` + `N8N_API_KEY` | Real workflows + push-on-approve | n8n instance → Settings → API |
| `GITHUB_TOKEN` (+ `GITHUB_DEPLOY_MAP`) | Dyson ships client sites (→ Vercel) | GitHub → fine-grained PAT, repo contents+PR |
| `METRICOOL_USER_TOKEN` (optional) | Real social analytics + autonomous publish | Metricool paid tier → API |

After keys: `./deploy/push.sh root@24.199.81.124` → SSH-verify service active, endpoints 200,
`agency.env` 404 over HTTP.

---

## 5. Validation gate (every lane, before "done")
- Python lanes: `python3 -c "import ast; ast.parse(open('FILE').read())"` on each edited file.
- JSX lane: Babel transform check + computed-tag scan (orchestrator provides `/tmp/valjsx.js`;
  if absent, manual scan: no `<Var[...] />`, all hooks aliased, all top-level names prefixed).
- Smoke: `FORGE_MARCUS=0 FORGE_PORT=7799 python3 connector.py` boots without ImportError;
  hit each new/changed `/api/agency/*` endpoint → 200 + expected shape (mock when no key).
- Confirm mock still renders with NO keys set (key-ready, non-breaking).

## 6. Deploy (orchestrator only, after all green)
`cd "forge rei" && ./deploy/push.sh root@24.199.81.124` then SSH-verify. Never push a broken
state. Report endpoints + service status back to operator.

## 7. If an agent gets stuck
Re-read this file (esp. your lane in §3 + frozen signatures in §4). Do not invent a different
function name or route — they're frozen so parallel lanes link up. If a frozen signature is
genuinely wrong, STOP and report to the orchestrator; do not silently diverge.
