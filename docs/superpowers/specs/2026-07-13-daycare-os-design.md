# FORGE Daycare OS — Design Spec

**Date:** 2026-07-13
**Status:** Approved — executing phase-by-phase
**Owner:** Yahjair

## Context

The FORGE dashboard already has a **Daycare** workspace (`forge rei/daycare*.jsx` +
`daycare_supabase.py`) that is a management-only front-end on the same Supabase project
(`eqblpbeqothkpyqiafzs`) as the separate Next.js family/staff app
(`~/Desktop/the main daycare app`). Today the daycare side shows a login / "Choose your
test profile" screen and, when reached over the SSH tunnel (`http://localhost:7799`),
fails writes with **"Daycare writes require HTTPS."**

The owner wants the daycare side of the dashboard to become the **full daycare operating
system**: opens straight into management (no login), oversees staff/parents/company,
runs business ads + watches social media, sends invoices through Stripe, and reaches
families over GoHighLevel — while the Next.js app remains the parent/staff front-end.
The two stay two lenses on one Supabase DB, cross-linked (no literal code merge — one is
a Next.js compile target, the other is in-browser Babel served by a Python stdlib
connector).

## Decisions (from brainstorming)

- **Merge meaning:** keep both apps separate, one shared DB as source-of-truth, add
  cross-links. Folder relocation is optional/cosmetic, deferred.
- **Access model:** auto-open as admin. The box auto-establishes an admin daycare session
  on loopback; the outer DO firewall + SSH tunnel / Tailscale is the real security gate.
- **Keys available now:** GHL (daycare) + Stripe. Meta Ads + Metricool get env slots only
  (blank until the owner fills them).
- **Autonomy:** every outward action (SMS, invoice send, ad launch, social post) stays
  approval-gated per CLAUDE.md rule 2. Auto-admin is loopback-only.

## Architecture principles

- Secrets only in `forge-daycare/config/daycare.env` (git-ignored, 404 over HTTP,
  chmod 600, shipped separately by `deploy/push.sh`).
- Reuse existing engines: `GHLClient` (`connector.py:105-168`), `agency_ads.py`,
  `agency_social.py`, `agency_eco.py`, the `record_invoice_payment` RPC seam
  (already accepts `provider='stripe'`).
- New daycare JSX files use unique hook aliases (e.g. `useStateDca`) and no computed JSX
  tags; loaded before `app.jsx` in `FORGE REI OS.html`.
- New daycare routes slot into `_handle_daycare_get`/`_handle_daycare_post`
  (`connector.py:3087-3188`) so they inherit the HTTPS + Origin + session gate.
- Validate before every deploy: `ast.parse` each `.py`, `deploy/valjsx.js` each `.jsx`,
  then `deploy/push.sh root@24.199.81.124` + SSH-verify.

## Phases

### Phase 0 — Foundation / secrets hygiene
- Move `GHL_API_KEY` + `GHL_LOCATION_ID` from the loose
  `forge-daycare/keys for daycare/keys for daycare.env.rtf` into `daycare.env`; delete the
  `.rtf` (push.sh would otherwise rsync it to the box unprotected).
- Add key slots to `daycare.env` + `daycare.env.example`: `STRIPE_SECRET_KEY`,
  `GHL_API_KEY`, `GHL_LOCATION_ID`, `META_ACCESS_TOKEN`, `METRICOOL_USER_TOKEN`
  (last two blank).

### Phase 1 — Kill the login wall (auto-open as admin)
- **Loopback HTTP fix:** narrow `request_is_secure` (`daycare_supabase.py:340`) so an
  allow-http flag is honored only when `client_ip in {127.0.0.1, ::1}`. SSH-tunnel path
  works; tailnet/public still require real HTTPS. Box enforcement intact.
- **Auto-admin:** new `FORGE_DAYCARE_AUTOADMIN=1` (box only). A loopback request with no
  valid session auto-mints an admin session from `daycare.env` admin creds; the client
  (`DaycareWorkspace`, `daycare.jsx:158`) sees `authenticated` and renders the console.
  No login screen, writes work, RLS enforced under the admin identity.

### Phase 2 — OS framing / command center
- Daycare Dashboard surfaces present-count, staff-on-duty, ratio, invoices due, unread,
  alerts (data already available via `get_overview`). Add an "Open family app" cross-link.

### Phase 3 — Ads + social (env-ready, mock until keys)
- New daycare tab(s) (`useStateDca`) + thin `/api/daycare/{ads,social,eco}` routes calling
  the existing `agency_ads` / `agency_social` / `agency_eco` functions with daycare creds.
  Graceful mock when `META_ACCESS_TOKEN` / `METRICOOL_USER_TOKEN` unset; goes live when the
  owner pastes keys — no rebuild. Metricool MCP also available for build/testing.

### Phase 4 — Stripe invoicing
- New `stripe_io.py` (stdlib urllib, form-encoded): customer → invoiceitem → invoice →
  send; optional payment link. `/api/daycare/stripe/*` routes. Wire `daycare_finance.jsx`
  with a "Send via Stripe" action on an invoice → creates + emails a hosted Stripe invoice,
  stores the Stripe id. Payment confirmation feeds the existing `record_invoice_payment`
  RPC with `provider='stripe'`, `provider_reference=<stripe id>`, an idempotency key. Use
  the Stripe MCP during build to test. Runtime uses `STRIPE_SECRET_KEY` (restricted key
  recommended).

### Phase 5 — GHL wiring (family SMS)
- Add `DAYCARE_GHL = GHLClient(_load_env(DAYCARE_ENV_CANDIDATES), "daycare")` beside the
  wholesale/agency instances. New `daycare_ghl.py` wrapping contacts/tags/pipeline + a
  `send_sms`. `/api/daycare/ghl/*` routes. Wire family SMS into comms + optional billing
  reminders. Outward sends stay approval-gated.

### Phase 6 — Merge / connect + docs
- Reconcile the Supabase migrations so one tree is the single source of truth (the dash
  side currently has an extra migration the app lacks). Add app↔dash cross-links. Document
  the daycare OS in CLAUDE.md.

## Verification

- **P0:** `daycare.env` holds the GHL keys; `.rtf` gone; `check-ignore` clean; new slots
  present in example.
- **P1:** `open-dashboard.sh` → daycare loads straight into console, no login; a test write
  (e.g. save announcement) succeeds over the tunnel; **box still returns 403 for daycare
  writes over tailnet HTTP** (enforcement not weakened); `/api/daycare/auth/status` shows an
  admin session.
- **P3:** ads/social tabs render with mock data and no errors when keys are blank.
- **P4:** Stripe MCP creates a test invoice; "Send via Stripe" produces a real hosted
  invoice; a recorded payment reflects via the RPC with `provider='stripe'`.
- **P5:** a test SMS draft is produced and gated for approval; approved send reaches GHL.
- **Every phase:** `ast.parse` all `.py`, `valjsx.js` all `.jsx`, deploy, SSH-verify
  (service active, endpoints 200, `daycare.env` 404 over HTTP).

## Out of scope

- Physically fusing the two source trees.
- Deploying the Next.js app (stays undeployed unless the owner requests it).
- Removing the Login-ID/PIN screen for non-loopback access (kept for real HTTPS clients).
