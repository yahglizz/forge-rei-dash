# CODEX TASK — FORGE REI OS: full end-to-end function audit + UI 2.0 pass

**Written for Codex. 2026-09-07. Repo: `/Users/yg4st/forge rei dash` (public GitHub `yahglizz/forge-rei-dash`).**

Two jobs, in this order:

1. **Make every function in this dashboard work end to end** — UI click → connector route →
   engine → real data store / real integration → response → UI renders it. Find what is
   broken, half-wired, or silently failing, and fix it at the root.
2. **Then** raise the UI to its full potential using your image model (referred to below as
   "image 2.0" — see §7 for exactly how it is used) **without changing a single behavior.**

Read this whole file before touching anything. Then read `CLAUDE.md` (operating manual)
and `NORTH_STAR.md` (constitution) in the repo root. Where this file and `CLAUDE.md`
disagree, `CLAUDE.md` wins.

---

## 1. What this system is (so you don't break it by misreading it)

A four-workspace operations console for four real businesses:

| Workspace | Accent | What it runs |
|---|---|---|
| **REI** (wholesale) | `#4F7CFF` | Seller leads from GoHighLevel, triage, screening, underwriting, deal pipeline, contracts, buyer blast |
| **Agency** (ClientForge) | `#8B5CF6` | Client sites, edit requests, Meta ads, social, approvals, call center, client portal |
| **Daycare** | `#2DD4BF` | A real licensed childcare center on Supabase — children, attendance, incidents, billing, staff, enrollment |
| **Dropship** (FORGE Dropship) | `#F97316` | Shopify + AutoDS + Meta store, run by the Midas agent |

**Stack — and this is unusual, respect it:**

- **NO BUILD STEP.** `forge rei/FORGE REI OS.html` loads React UMD + `@babel/standalone`
  from `assets/vendor/` (SRI-pinned) and every `.jsx` is transformed **in the browser at
  load**. There is no webpack, no vite, no npm install, no `node_modules`. Do not
  introduce one. Do not add a bundler "to make the UI work." A syntax error does not fail
  a build — it **white-screens the live dashboard after deploy**.
- **Backend is Python stdlib only.** `forge rei/connector.py` (~4,970 lines) is a
  `http.server` app on port 7799. No Flask, no FastAPI, no requirements.txt to grow. Do
  not add a third-party web framework or an ORM.
- **State is JSON files under `forge rei/marcus_state/`**, thread-locked (`threading.Lock`,
  `_load`/`_save`), plus Supabase for the daycare only.
- **The brain** is an Obsidian vault (`~/Desktop/Agentic-OS/vault`, `/opt/forge/vault` on
  the box) read/written by `brain_io.py` and git-committed.
- Runs 24/7 on a DigitalOcean box (`root@24.199.81.124`), systemd unit `forge-reios`,
  reachable over Tailscale at `https://forge-reios.tail0a2dda.ts.net`. Port 7799 is
  firewalled off the public internet.

---

## 2. HARD RULES — violating any of these is a failed task

These are not style preferences. Each one has already cost a live outage or a real-world
consequence in this repo.

### 2.1 Frontend collision rules (a violation = white screen, not an error)

Every `.jsx` shares **one global scope** after Babel transform. Therefore:

- **Unique hook aliases per file.** Each file destructures React with its own suffix:
  `const { useState: useStateP } = React;` in `pages.jsx`, `useStateAg` in `agency.jsx`,
  `useStateSh` in `shell.jsx`, etc. If you add a file or a hook, pick an unused alias.
- **Unique prefixed top-level names.** No two files may declare the same top-level
  `const`/`function`. Prefix by file (`Ds*` for dropship, `Ag*` for agency, …).
- **NO computed JSX tags.** `<Icons[x] />` parses but white-screens. Always resolve first:
  ```jsx
  const Ico = Icons[key] || Icons.Dashboard;
  return <Ico size={18} />;
  ```
- Components are exported as `window` globals via `Object.assign(window, {...})` at the
  bottom of each file, and the load ORDER in `FORGE REI OS.html` matters — a file must be
  listed after everything it consumes. `agents_hub.jsx` loads after every agent page it
  renders; `mission_control.jsx` after `shell.jsx` + `api.jsx`; `app.jsx` last.

### 2.2 Backend pattern

- **GET**: add the handler to the `ROUTES` dict (`connector.py:2579`), and add the path to
  `NO_CACHE` if it must not be served from the 45s cache.
- **POST**: add the path to the inline allowlist tuple inside `do_POST`
  (`connector.py:3046`) **and** the `elif` dispatch below it. A POST path missing from the
  allowlist returns 404 even though the handler exists.
- `/api/daycare/*` and `/api/dropship/*` are dispatched by **prefix** to
  `_handle_daycare_post` / `_handle_dropship_post` — they are not in the main allowlist.
- The client portal is a **separate handler** (`PortalHandler`, `connector.py:4790`) with
  exactly 4 routes and no path to the CRM, daycare, or secrets. Keep it that way.
- New JSON stores mirror `agency_io.py`: `threading.Lock`, `_load`/`_save`, file under
  `marcus_state/`.

### 2.3 Agent autonomy — the propose→approve gate (this one is about real people)

Agents **never** take an outward or irreversible action on their own. Texting sellers,
posting socials, moving a GHL pipeline, launching or scaling ads, sending an invoice,
ordering from a supplier, messaging a customer — **all of it is one-tap gated behind the
operator's approval.**

- Do **not** "fix" a page by flipping an approval gate off to make a flow complete.
- Do **not** add an auto-send, auto-post, auto-launch, or auto-charge path.
- The only documented autonomous exceptions already in the code are internal + reversible
  (HOT-lead auto-tag `FORGE_SCOUT_AUTOTAG_HOT`, HOT-lead auto-pipeline
  `FORGE_SCOUT_AUTOPIPE_HOT`, opt-in follow-up bumps behind `autopilot.maybe_send`). Leave
  their gating exactly as-is.
- **No agent ever states a price/offer over text.** `marcus_engine._no_price_over_text`
  enforces it in code. Do not weaken, bypass, or "simplify" that function.

### 2.4 Secrets

- All keys live in `*.env` files **outside** the web-served folder
  (`forge-scout/config/`, `forge-agency/config/`, `forge-daycare/config/daycare.env`,
  `forge-telegram/config/telegram.env`, `forge-dropship/config/`), git-ignored, and must
  **404 over HTTP**. There is a test for this; keep it passing.
- Never print, echo, commit, or move a secret value. Never add one to a JSX file, a route
  response, or a log line. Never rotate a key.
- Box loop knobs live in `/etc/default/forge-reios` — that file holds secrets, so `grep`
  it for a var name, never `cat` it.

### 2.5 Additive only

Do not delete a working feature, page, route, or engine to make an audit pass. If
something looks dead, prove it is unreachable before removing it, and say so in the report
instead of silently deleting.

### 2.6 Never ship a broken state

Validation gates run BEFORE any deploy (§8). A push that fails validation aborts and the
live version keeps running — do not force past it.

---

## 3. Baseline already verified — do not spend time re-proving this

Claude ran these on 2026-09-07 against the current `main` (commit `23cea1b`). All passed.
**Start from behavior, not from syntax.**

| Check | Result |
|---|---|
| `ast.parse` over all 138 `.py` files in `forge rei/` | ✅ all parse |
| `node deploy/valjsx.js` over all 51 `.jsx` files (Babel transform + computed-tag scan) | ✅ all clean |
| Every `/api/...` string referenced in any `.jsx`/`.js` has a matching string in `connector.py` | ✅ no orphans (the only two "misses" are `/api/daycare` and `/api/dropship` prefix constructions, dispatched by prefix) |

Current surface, counted:

- **404 GET routes** registered in the `ROUTES` dict; **136 paths** in the `do_POST`
  allowlist; ~415 unique `/api/*` paths across the whole connector.
- **51 `.jsx`** files, **138 `.py`** files, **33 `test_*.py`** suites in `forge rei/`.
- **74 navigable pages** across the four workspaces (§10 inventory).

So: the code compiles and the wiring map is coherent. **What is unknown is whether each
route returns real, correct, fresh data and whether each UI action actually completes.**
That is your job.

---

## 4. What "end to end works" means here — the definition you will be graded on

For **every** page in §10 and **every** interactive control on it:

1. **The page renders** with no console error and no white screen, in all four workspaces.
2. **Every read** hits a real route that returns 200 with real data (or an *honest empty
   state* — see §4.1), not a silent `catch {}` that leaves a spinner or a zero forever.
3. **Every button/form does what its label says**, end to end: the POST lands, the store
   or the integration is actually written, the response comes back, and **the UI reflects
   the new state without a manual refresh.**
4. **Every failure is visible.** An error must surface in the UI as a readable message.
   The single most common real defect in this codebase's UI layer is
   `catch (e) {}` — an empty catch that turns a 500 into a permanently blank card. Hunt
   these specifically:
   ```bash
   grep -rn "catch (e) {}\|catch (_) {}\|catch {}" --include="*.jsx" "forge rei/"
   ```
   Each one is either (a) genuinely fine (optional enrichment) or (b) a hidden failure.
   Decide per-site; fix the (b)s by surfacing the error.
5. **Approval gates still gate.** After your fixes, every outward action still requires the
   operator's tap (§2.3).

### 4.1 Honest empty state vs. fake data — do not get this wrong

Several integrations are deliberately **unconfigured** and return a labeled mock:
`agency_ads.py` (Meta, falls back to `"source": "mock"`), `dropship_pipiads.py`,
`dropship_gethookd.py`, `dropship_env.py`, the daycare Growth tab until
`META_ACCESS_TOKEN` / `METRICOOL_USER_TOKEN` are set in `daycare.env`.

**These are correct as-is.** The rule (the agents' creed) is: ground it, infer it, or name
it **Unknown** — never invent a number. So:

- ✅ Fix: a mock that is NOT labeled in the UI, so the operator can't tell it's mock.
- ✅ Fix: a card that shows `0` or `—` when the route actually returned an error.
- ❌ Do NOT: replace a mock with invented "realistic" data to make a page look finished.
- ❌ Do NOT: delete a mock fallback — an unkeyed integration must degrade to a labeled
  "add key" state, never to a crash.

`test_research_packet.py` and `test_daycare_ads_honesty.py` already enforce parts of this.
Keep them green.

---

## 5. PHASE 1 — the audit (do this before you change anything)

### 5.1 Run the existing suite and record the baseline

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
for t in test_*.py; do echo "=== $t"; python3 "$t" || echo "FAILED: $t"; done 2>&1 | tee /tmp/forge_test_baseline.txt
```

Some suites need env/keys and will skip or fail for environmental reasons — record which,
and distinguish "fails because the code is broken" from "fails because no key is present."
Do not paper over the second kind by adding a key.

### 5.2 Bring the dashboard up locally, read-only

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
FORGE_MARCUS=0 FORGE_PORT=7799 python3 connector.py
```

`FORGE_MARCUS=0` is **mandatory** locally: it keeps the Scout/Marcus/Atlas/Solomon/Midas
poll loops OFF so the Mac never double-contacts a real seller. Only the box runs
`FORGE_MARCUS=1`. Never start a local instance with it on.

Then open `http://localhost:7799/`. Access is IP-gated (`_dashboard_client_allowed`) —
loopback qualifies.

### 5.3 Sweep every GET route

`forge rei/deploy/live_smoke.py` **already exists** and does exactly this: curls every GET
endpoint, applies a per-endpoint freshness assertion, prints a PASS/FAIL matrix, exits
non-zero if a critical endpoint fails or a security-negative isn't blocked.

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
python3 deploy/live_smoke.py --json > /tmp/forge_smoke_local.json   # local instance
python3 deploy/live_smoke.py --via ssh --host root@24.199.81.124    # the live box
```

**Extend it, don't replace it.** If a route in `ROUTES` has no assertion in `live_smoke.py`,
add one. Target: every one of the 404 GET routes is asserted. It deliberately skips
`/api/goals/today` (has a GHL write side-effect) — keep that skip.

### 5.4 Sweep every POST path

There is no equivalent harness for POST. Build one — `deploy/post_smoke.py`, same shape as
`live_smoke.py`, stdlib only:

- Enumerate the `do_POST` allowlist + the daycare/dropship prefix handlers.
- For each, send a **minimal invalid body** and assert the route responds with a structured
  `{"error": ...}` and a sane status — not a 500 traceback, not a 404 (which would mean the
  path is missing from the allowlist), not a silent 200.
- **Do not fire a POST that sends an SMS, posts a social, launches/scales an ad, sends an
  invoice, orders from a supplier, or writes to GHL/Supabase.** Assert the *shape* of the
  refusal on those, from a body that cannot possibly succeed. If a route cannot be probed
  safely, list it in the report as "manually verified by reading the code" and read it.
- Where you need a live-ish path, use **TEST MODE** (`test_mode.py`, `/api/test-mode`):
  a scoped whitelist where only a whitelisted test phone auto-acts and real sellers stay
  review-gated. Read that module before enabling anything.

### 5.5 Sweep the UI

For each of the 74 pages in §10, with the local instance up:

- Load the page. Capture console errors and failed network requests.
- Exercise every control. Confirm the state change round-trips.
- Record: page → control → route → store/integration → result → verdict.

Use whatever browser automation you have. If you use Playwright, use it against
`http://localhost:7799/`, never against the production Tailscale URL for anything that
writes.

### 5.6 Deliverable of Phase 1

`FORGE_E2E_AUDIT_<date>.md` at repo root — a table, one row per page × control, with
columns: `Workspace | Page | Control | Route | Verdict (WORKS / BROKEN / HIDDEN-FAIL /
MOCK-UNLABELED / UNREACHABLE) | Evidence | Root cause`.

**Evidence, not assertion.** A verdict needs a status code, a console line, a screenshot,
or a quoted response body. Anything you could not verify is **Unknown** — say so; do not
guess and do not pad the table.

---

## 6. PHASE 2 — the fixes

### 6.1 Fix at the root, once

Before editing a function, `grep` every caller. One guard in the shared function beats a
guard in each of six callers, and patching only the path the audit named leaves the
siblings broken. Example: an empty `catch` pattern that appears in 20 JSX files is one
shared helper (`api.jsx` already has `useApi` / `apiPost` — use them), not 20 patches.

### 6.2 Order of work

1. **BROKEN** — a control that does nothing or errors. Highest value.
2. **HIDDEN-FAIL** — the empty-catch class. Make the failure visible, then fix the cause.
3. **MOCK-UNLABELED** — label it as mock/unconfigured in the UI (§4.1). Do not fabricate data.
4. **UNREACHABLE** — a route with no UI or a UI with no route. Wire it or report it; do
   not delete without proof.

### 6.3 Every non-trivial fix leaves a runnable check

This repo's convention: an `assert`-based self-check in `__main__`, or one small
`test_*.py` next to the existing 33. No pytest fixtures, no new frameworks. If you fix a
branch, a parser, a money path, or a gate, leave the smallest thing that fails if it
regresses.

### 6.4 What NOT to "fix"

- The propose→approve gates (§2.3).
- The honest-mock fallbacks (§4.1).
- The daycare open-access trade-off (`FORGE_DAYCARE_OPEN`) — it is a documented, deliberate
  decision with the trust boundary at Tailscale device auth. Read `CLAUDE.md` §10 before
  touching any daycare auth path. Children's records are involved; do not loosen anything.
- The `PortalHandler` isolation (§2.2).
- The skill/creed load paths — `agent_creed.py` is deliberately NOT reachable from
  `_load_skills()` so that `learn()` can never rewrite the constitution. `forge rei/test_dropship_skills.py`
  fails if that leaks. Run it after touching any skill file:
  ```bash
  cd "forge rei" && python3 test_dropship_skills.py
  ```

---

## 7. PHASE 3 — the UI pass ("image 2.0")

**Precondition: Phase 2 is done and the audit table is all WORKS or explicitly-accepted.
Do not restyle a broken dashboard.**

### 7.1 What "image 2.0" means for this task

Use your image/vision capability as the design loop — not as a code generator:

1. **Screenshot every one of the 74 pages** from the running local instance, at desktop
   (1440×900) and mobile (390×844) widths. Save to `docs/ui-audit/before/<workspace>-<page>.png`.
2. **Feed the screenshots to your image model** and have it (a) critique the current
   screen — hierarchy, density, alignment, contrast, dead space, inconsistent components —
   and (b) generate a target reference image for the ones that need it.
3. **Do not paste generated markup.** The reference image is a *target*, not source. You
   implement it by hand in this codebase's own idiom.
4. **Re-screenshot after** into `docs/ui-audit/after/` and diff before/after per page. A
   page whose "after" lost information, lost a control, or changed a number is a
   regression — revert it.

If you do not have an image model available, say so in the report and do the pass from the
screenshots + the constraints below. Do not skip the screenshots either way — they are the
regression evidence.

### 7.2 The surface you may change

**Preferred, in order:**

1. `forge rei/styles.css` (726 lines) — the design-token layer. `:root` already defines
   `--bg`, `--card`, `--border`, `--blue/green/orange/red/violet/pink/cyan`,
   `--workspace-accent`, `--text`/`--text-2`/`--text-3`/`--text-faint`,
   `--radius`/`--radius-lg`/`--radius-sm`, `--shadow`, `--glow-blue`, `--font` (Geist),
   `--mono` (Geist Mono). **Most of the visual lift should happen here.**
2. `className` swaps in JSX, and inline-style objects — as long as the element tree, the
   props, the handlers, and the data bindings are untouched.
3. New shared presentational components in an existing file, following §2.1 naming.

**Do not:**

- Change any `fetch`, `useApi`, `apiPost`, handler, state shape, or conditional that
  decides *what* is displayed.
- Remove a control, a column, a number, a badge, a status, or an error surface to make a
  screen look cleaner. Density is a feature here — this is an operations console, not a
  marketing page.
- Add a CSS/JS framework, a component library, an icon package, or a font beyond the two
  already loaded (Geist / Geist Mono via Google Fonts). Icons come from `icons.jsx`.
- Add a runtime dependency of any kind. There is no build step to tree-shake it.
- Change the four workspace accents (`#4F7CFF` REI, `#8B5CF6` agency, `#2DD4BF` daycare,
  `#F97316` dropship) — the operator navigates by color.

### 7.3 Design direction

Current theme: "Dark Luxury SaaS" — near-black navy ground (`#050B18`), `#101827` cards,
hairline `rgba(255,255,255,0.06)` borders, one accent per workspace, tabular-nums for
figures. **Keep the identity; raise the execution.** What to actually go after:

- **Hierarchy.** Most pages present every card at equal weight. One primary read per
  screen, secondary supporting, tertiary quiet.
- **Vertical rhythm and alignment.** Consistent spacing scale (pick 4/8/12/16/24/32 and
  enforce it). Cards on a page should share edges.
- **Typographic scale.** Fewer sizes, deliberately chosen. Numbers in `--mono` with
  `.tabnum` so columns don't dance.
- **Component consistency.** The same "stat tile", "row", "badge", "empty state",
  "error state", and "loading state" everywhere. Right now they vary per page — unify them
  as shared classes in `styles.css`.
- **Empty and error states.** Every page should have a designed one. An operations console
  that shows a blank card for "no data" and a blank card for "the API 500'd" is lying.
- **Mobile.** The operator uses this from a phone over Tailscale. At 390px the sidebar,
  the tables, and the approval buttons must all remain usable. Test it.
- **Focus and keyboard.** Visible focus rings, `⌘K` search already exists in `shell.jsx` —
  make it discoverable.
- **Motion.** Sparing. No entrance animation on data that updates on a 30s poll.

### 7.4 Verify after every batch

```bash
cd "/Users/yg4st/forge rei dash/forge rei"
node deploy/valjsx.js *.jsx        # must exit 0
```

Then reload the browser and confirm no white screen and no new console error. A white
screen after a CSS-only change means you hit a JSX collision, not a style bug.

---

## 8. PHASE 4 — validate, deploy, report

### 8.1 Validate (non-negotiable, in this order)

```bash
cd "/Users/yg4st/forge rei dash/forge rei"

# 1. Python parses
for f in *.py; do python3 -c "import ast; ast.parse(open('$f').read())" || echo "PARSE FAIL: $f"; done

# 2. JSX transforms + no computed tags
node deploy/valjsx.js *.jsx

# 3. Test suite
for t in test_*.py; do python3 "$t" || echo "FAILED: $t"; done

# 4. Route sweep against the local instance
python3 deploy/live_smoke.py
python3 deploy/post_smoke.py        # the harness you built in 5.4
```

All four clean, or you do not deploy.

### 8.2 Deploy

Three paths, pick by what changed:

| Changed | Command | Notes |
|---|---|---|
| Code only (`.py`/`.jsx`/`.css`/`.html`) | `git push origin main` | The box polls GitHub every 60s (`forge-autopull.timer`) and self-deploys: `git reset --hard origin/main`, validate, rsync into the live tree, restart, health-check. A commit that fails validation aborts the deploy and the live version keeps running. |
| Code only, want it NOW | `./deploy/quick-deploy.sh` | Same, but SSHes the box to run it immediately. Needs `~/.ssh/forge_droplet`. |
| A secret (`*.env`) or the brain vault | `./deploy/push.sh root@24.199.81.124` | Mac-only. Those files are gitignored and never reach GitHub. |

**Do not push a state that fails §8.1.** Commit in reviewable batches (audit → functional
fixes → UI pass), not one 200-file commit. End every commit message with:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

### 8.3 Verify live

```bash
ssh -i ~/.ssh/forge_droplet root@24.199.81.124 'systemctl status forge-reios --no-pager | head -5'
python3 "forge rei/deploy/live_smoke.py" --via ssh --host root@24.199.81.124
```

Service `active`, endpoints 200, secrets 404. Watch the auto-deploy:
`ssh box 'journalctl -u forge-autopull.service -f'`.

### 8.4 Final report — `FORGE_E2E_REPORT_<date>.md`

- The Phase 1 audit table, with a `Fixed / Not fixed / Accepted as-is` column filled in.
- Every fix: file:line, root cause, what the fix does, the check left behind.
- The UI pass: before/after screenshot pairs, what changed per page, what you deliberately
  did **not** change and why.
- **An explicit "still broken / still Unknown" section.** Do not close out with everything
  green if it isn't. A short honest list beats a long clean one.
- Anything you found that needs the operator's decision (money, branding, live-system
  policy) — surface it, don't decide it.

---

## 9. Command cheat sheet

```bash
# Local UI-only run (loops OFF — mandatory on the Mac)
cd "/Users/yg4st/forge rei dash/forge rei" && FORGE_MARCUS=0 FORGE_PORT=7799 python3 connector.py

# Open the live box through the SSH tunnel
~/"forge rei dash/open-dashboard.sh"

# Validate
python3 -c "import ast; ast.parse(open('FILE.py').read())"
node deploy/valjsx.js FILE.jsx

# Route sweeps
python3 deploy/live_smoke.py [--json] [--via ssh --host root@24.199.81.124]

# Skill/creed integrity (run after touching any skill file)
python3 test_dropship_skills.py

# Box
ssh -i ~/.ssh/forge_droplet root@24.199.81.124
systemctl status forge-reios
journalctl -u forge-reios -f
```

**Key env knobs** (box: `/etc/default/forge-reios` — grep it, never cat it):
`FORGE_MARCUS` (loops on/off), `FORGE_SCOUT_INTERVAL` (180s, the money loop),
`FORGE_DROPSHIP_BRIEF` (0 — off until Shopify connects), `FORGE_TODAY_LOOP` (0),
`FORGE_SOLOMON_BRIEF_EVERY_H` (24), `FORGE_SCOUT_LEARN_EVERY` (25),
`FORGE_ATLAS_LEARN_EVERY` (12), `FORGE_CAVEMAN_LEVEL`, `FORGE_VAULT`.
**If you switch a loop OFF you must call `forge_heartbeat.retire("<loop>")` in the else
branch**, or its heartbeat stops and the health card goes red forever.

---

## 10. Page inventory — the 74 screens to verify

**REI (16):** Dashboard · Agents · Agent Office · Leads · Conversations · Deal Pipeline ·
Contracts · Deal Calc · Buyers · Buyer Blast · Outbound · Tasks · Analytics · Brain ·
System Health · Costs

**Agency (23)** — two lenses, Personal (`p`) / Business (`b`), toggled in the sidebar;
no lens tag = shows in both:
Dashboard(b) · My Businesses(p) · Daycare·Ads(p) · Daycare·Social(p) · Daycare·Ad Studio(p) ·
Agents · Agent Office · Blueprint Studio(b) · Clients(b) · Client Chat(b) · Client View(b) ·
Edit Requests(b) · Workflows(b) · Meta Ads(b) · Social(b) · Approvals(b) · Call Center(b) ·
Pipeline(b) · Projects(b) · Revenue(b) · Brain · Settings

**Daycare (21):** Dashboard · Agents · Agent Office · Children · Attendance · Daily Logs ·
Incidents · Blessing Coins · Classrooms · Staff & Schedules · Enrollment · Parent Logins ·
Messages · Announcements · Text Blast · Billing · Payroll · Ads & Social · Reports · Brain ·
Settings

**Dropship (14):** Dashboard · Agents · Agent Office · Products · Product Watch · Orders ·
Inventory · AutoDS·Suppliers · Ads & Creative · Customers · Analytics · Connections & MCP ·
Brain · Settings

Plus the cross-business front door: **Mission Control** (`mission_control.jsx`) and the
**Agent Office** floor (`pixel_office.jsx`, present in all four workspaces).

Source of truth: `forge rei/data.jsx` (`NAV`, `AGENCY_NAV`, `DAYCARE_NAV`, `DROPSHIP_NAV`).
The renderer map is `forge rei/app.jsx` — keys must match.

---

## 11. The seven agents (context — do not restructure them)

| Agent | Side | Job | Autonomy |
|---|---|---|---|
| **Scout** `scout_triage.py` | REI | Finds/ranks/organizes seller replies; auto-hands call-worthy leads to Marcus | Never texts. Tags/pipeline queued for approval (HOT-lead tag/pipe are the documented internal exceptions) |
| **Marcus** `marcus_screening.py` + `marcus_engine.py` | REI | Screens interested sellers → call-ready report; drafts seller text-backs | Every reply is a PROPOSAL. Never a price by text (code-enforced) |
| **Atlas** `deal_prep.py` | REI | Underwrites screened sellers, offer anchors, MAO math, call card | Never contacts anyone. Numbers are internal only |
| **Dyson** `agency_agents.py` | Agency | Client website/code edit PLANS | Plan-only until approved |
| **Eco** `agency_agents.py` | Agency | Ads strategy / Meta analysis / concepts | Recommends only |
| **Solomon** `daycare_director.py` | Daycare | One ranked operating brief for the whole center; owns enrollment | Never texts/invoices/launches ads/writes the DB |
| **Midas** `dropship_director.py` | Dropship | Head e-com director; brief + 3 lanes (research / creative & ads / fulfillment) | Never launches, spends, orders, or messages |

Shared infra you will see referenced: `review_agent._claude` (Claude calls),
`brain_io` (vault read/write + git), `agent_bus.py` (inter-agent messages),
`agent_coach.py` (cross-agent insight sharing), `agent_creed.py` (the per-business evidence
discipline, injected into prompts, invisible to `learn()`), `cost_tracker` (per-agent API
cost by thread name), `agents_hub.py` (task filing), `telegram_io.py` (alerts + tap-to-approve).

**Before adding an agent: don't.** A 2026-07-25 audit retired five agents (Nora, Nova,
Hawk, Blaze, Otto) because they were re-reading the same tables on separate loops. A new
agent is a new playbook to drift, a new loop to run, and a new Claude call per cycle. If
the answer is "a new section in an existing agent's brief," write that instead.

---

## 12. Communication style for your report

Terse. Lead with the answer, no preamble, no restating the ask, no sign-off. Bullet
fragments over full sentences. Keep every fact, name, number, file path, and the reasoning
that changes a decision — **short, never wrong.**

Write **normal, full prose** for: security warnings, irreversible-action confirmations,
multi-step sequences where dropping words risks a misread, and any real caveat or Unknown.
Code, commits, commands, API names, and error strings are verbatim, never abbreviated.

Evidence discipline outranks brevity: ground it, infer it with the reasoning shown, or name
it **Unknown**.
