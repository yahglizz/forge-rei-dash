# Agency workflow audit — client → payment → dashboard

*2026-09-08. Scope: the AGENCY side of FORGE REI OS (`forge rei/agency*.{py,jsx}`,
`stripe_io.py`, `connector.py`). Read-only trace for Phase 1; Phase 2 fixes listed
at the bottom and applied in the working tree.*

**Headline: there is no payment step.** The agency side has a client book, a call
sheet, an offer sheet, a portal, an approval queue and a deploy path. Between
"prospect says yes" and "client is live paying monthly" there is a manual gap that
the software does not model at all: no invoice, no checkout, no subscription, no
paid/unpaid state, and no automated record creation on payment. The one Stripe
module in the repo belongs to the daycare and is not reachable from any agency
code path.

---

## 1. Current State — what actually works

### 1.1 Client record shape (`forge rei/agency_io.py`)

Store: `marcus_state/agency.json`, atomic writes, one process-wide lock.
`_slim()` (`agency_io.py:103-122`) is the full public shape:

| Field | Type | Notes |
|---|---|---|
| `id` | str | `c<seq>_<ms>` |
| `name` / `business` / `site` | str | |
| `plan` | free str | UI offers `Starter/Growth/Pro/Custom` (`agency.jsx:14`) but the call-sheet writes a quoted-offer sentence here instead (see Broken §2.6) |
| `mrr` | float ≥ 0 | `_num()` clamps at 0 |
| `status` | enum | `lead · building · active · paused · churned` (`agency_io.py:18`) |
| `services` | list | whitelisted against `SERVICES` (`agency_io.py:22-24`) — Website, Automations, AI Receptionist, AI Chatbot, Ads Management, SEO, Lead Gen, Social Media, CRM Setup, Hosting |
| `agents` | list | free-form, unvalidated, never rendered |
| `ghlContactId` / `ghlSyncedAt` | str / ms | hand-pasted; nothing creates the contact |
| `notes` | str | |
| `portalToken` | str | `secrets.token_urlsafe(18)`, per-client bearer |
| `workspace` | dict | `repo, branch, liveUrl, stack, brand, assets, accessNotes` (`agency_io.py:38`) — this is what Dyson reads to make real edits |
| `portal` | dict | `welcome, scope, deliverables, contactEmail, contactPhone, startDate` + lifecycle `status(draft/sent/active), sentAt, openedAt` (`agency_io.py:61-63`) |
| `dateAdded` / `dateUpdated` | ms | |

**Answering the brief directly:**
- *What they signed up for* — **yes**, `services[]` (validated) plus a free-text `plan`.
- *Plan/tier* — **yes** but it is a plain string with no server-side vocabulary; the
  UI's four tiers and the call sheet's offer-lines write into the same field.
- *MRR* — **yes**, `mrr` (float). Only counted toward agency MRR when
  `status ∈ {active, paused}` (`agency_io.py:233-234`).
- *Start date* — **only as a free-text label** inside `portal.startDate`
  (`agency.jsx:331-332` placeholder "Mar 3, 2026"). Not a date, not parsed,
  not used for anything. `dateAdded` is the only real timestamp.
- *Status* — **yes**, 5-state. There is **no** `proposal`, `signed`, `invoiced`,
  `past_due` or `paid` state.
- **No** one-time/contract value field at all. A $1,100 website sale is stored only
  as English inside `plan`.

### 1.2 Stripe — what exists today

`forge rei/stripe_io.py` (235 lines) is a **daycare-only** stdlib REST bridge. Its
own docstring says so (`stripe_io.py:2-11`).

| Capability | State |
|---|---|
| Payment link | **no** |
| Checkout session | **no** |
| Subscription / recurring | **no** (`agency_offers.py:132` asserts "site publishes no recurring offer") |
| Customer create/search | yes, but keyed on `metadata['daycare_guardian_id']` (`stripe_io.py:134-155`) |
| Invoice create/finalize/send | yes, daycare-scoped (`stripe_io.py:184-226`) |
| Invoice status poll | yes (`stripe_io.py:229-235`) |
| **Webhook handler** | **none anywhere in the repo.** No `checkout.session.completed`, no `invoice.paid`, no signature verification, no `/webhook*` route. Payment state is only ever learned by an operator pressing "Sync" on a daycare invoice (`connector.py:3716-3745`) |

**Wiring:** imported once (`connector.py:1012`); reachable only through three
daycare routes — `POST /api/daycare/stripe/send-invoice`,
`POST /api/daycare/stripe/sync-payment` (`connector.py:4112-4116`), and
`GET /api/daycare/stripe/status` (`connector.py:4226`). UI buttons live only in
`daycare_finance.jsx:20-23`.

**Agency exposure to Stripe: zero.** The only agency mentions are cosmetic —
a free-text settings box (`agency_io.py:389`, `agency.jsx:876`), a bullet in an
offer template (`agency_offers.py:31`), and a form placeholder in the Blueprint
Studio (`agency_build.jsx:283`).

**Keys (names only):** `STRIPE_SECRET_KEY`, read from the process env first, else
from `forge-daycare/config/daycare.env` via `daycare_supabase._read_env()`
(`stripe_io.py:42-49`). Restricted key expected (Invoices + Customers write).
`configured()` gates every call, so an unset key returns a clean not-configured
result rather than raising.

### 1.3 The handoff — what exists

The only automated "prospect → client record" path is the call sheet:
`agency_callsheet.escalate()` (`agency_callsheet.py:319-388`). It normalises the
quoted offer through `agency_offers.normalize()`, derives `services` from the
offer, writes a client with `status="lead"`, and back-links `lead.client_id` so a
re-escalate updates rather than duplicates. It is internal and reversible — nothing
is sent outward.

Portal provisioning is manual and works: operator taps **Generate portal link** →
`POST /api/agency/portal/token` → `agency_portal_io.link()` mints/returns
`…/portal#c=<id>&k=<token>` (`agency_portal_io.py:163-177`). The token is a
per-client bearer compared with `secrets.compare_digest`
(`agency_io.py:309-329`). It is kept in the URL **fragment** so it never reaches
the server, a proxy log, or a Referer header; `portal.html` reads it once, clears
it, and POSTs it in a same-origin body. `mark_portal_opened` flips
`portal.status → active` on first open (`agency_io.py:350-369`).

`agency_portal_io.py` **is** the client-facing portal, and it is the well-built
part of this whole surface: four verbs only (bootstrap / submit / send_message /
link), `clientId` and `clientName` always taken from the verified record and never
from the POST body, and a slimmed response that withholds `contactEmail`,
`contactPhone`, `startDate`, lifecycle, token, notes, workspace and MRR
(`agency_portal_io.py:70-107`). It is served by a *separate* listener
(`PortalHandler`, `connector.py:4739-4805`) with a 64 KiB body cap, same-origin
POST enforcement, `no-store` + `no-referrer`, and a hard 404 on every other path.

**How a client authenticates: they don't.** Possession of the link is the whole
auth model. There is no password, no email verification, no session, no expiry,
no revocation beyond the operator hitting Regenerate. That is a defensible design
for an edit-request portal; it is *not* an identity system, and nothing in the
codebase currently promises otherwise except the dead login stub in §2.2.

**After a client pays: nothing happens.** No code path anywhere reacts to a
payment. The operator types the client into the book by hand (or escalates a call
sheet lead), types the MRR by hand, flips the status by hand, and shares the
portal link by hand.

### 1.4 API surface — every agency route

**GET** (registered in `ROUTES`, `connector.py:2674-2704`; handlers at
`connector.py:2424-2576`). ✅ = the frontend calls it.

| Path | Handler | Used |
|---|---|---|
| `/api/agency/clients` | `agency_io.list_clients` | ✅ |
| `/api/agency/stats` | `agency_io.stats` | ✅ |
| `/api/agency/health` | `agency_ghl.health` | ❌ dead |
| `/api/agency/ghl/dashboard` | `agency_ghl.dashboard` | ✅ |
| `/api/agency/ghl/contacts` | `agency_ghl.contacts` | ❌ dead |
| `/api/agency/ghl/pipeline` | `agency_ghl.pipeline` | ❌ dead |
| `/api/agency/ghl/tags` | `agency_ghl.list_tags` | ❌ dead (only `/tags/sync` is called) |
| `/api/agency/requests` | `agency_requests_io.list_requests` | ✅ |
| `/api/agency/messages` | `agency_messages_io.list_for_client` | ✅ |
| `/api/agency/messages/unread` | `…unread_counts` | ✅ |
| `/api/agency/portal/links` | `agency_portal_io.links_for_all` | ✅ |
| `/api/portal/bootstrap` | `agency_portal_io.bootstrap` | ✅ (405 on the dashboard listener; POST-only) |
| `/api/agency/dyson/drafts` | `agency_dyson.list_drafts` | ✅ |
| `/api/agency/workflows` | `agency_workflows_io.list_workflows` | ✅ |
| `/api/agency/build/list` | `agency_build_studio.list_blueprints` | ✅ |
| `/api/agency/ads`, `/ads/accounts` | `agency_ads` | ✅ |
| `/api/agency/eco` | `agency_eco.recommendations` | ✅ |
| `/api/agency/approvals` | `agency_approvals_io.list_queue` | ✅ |
| `/api/agency/calls` | `agency_calls.summary` | ✅ |
| `/api/agency/callsheet` | `agency_callsheet.list_leads` | ✅ |
| `/api/agency/offers` | `agency_offers.list_offers` | ✅ |
| `/api/agency/agents` | `agency_agents.status` | ❌ dead |
| `/api/agency/agents/history` | `agency_agents.history` | ✅ (`mobile/m_agents.jsx:158`) |
| `/api/agency/agents/tasks` | `agency_agents.list_tasks` | ❌ dead |
| `/api/agency/social`, `/social/besttime`, `/social/posts`, `/social/analytics` | `agency_social` | ✅ |
| `/api/agency/deploy/status` | `agency_deploy.status` | ❌ dead |
| `/api/agency/settings` | `agency_io.get_settings` | ✅ |

**POST** (allowlist `connector.py:3077-3123`, dispatch `connector.py:3334-3482`):

| Path | Handler | Used |
|---|---|---|
| `/api/agency/client/save` | `agency_io.save_client` | ✅ |
| `/api/agency/client/delete` | `delete_client` + `purge_client` | ✅ |
| `/api/agency/client/login` | `agency_io.client_login` | ⚠️ called but permanently stubbed — §2.2 |
| `/api/agency/client/sync-ghl` | `agency_ghl.ensure/apply` | ✅ |
| `/api/agency/reset` | wipes clients+requests+approvals, needs `{"confirm":true}` | ❌ dead (no UI) |
| `/api/agency/request/save · /delete · /status` | `agency_requests_io` | ✅ |
| `/api/agency/message/send · /read` | `agency_messages_io` | ✅ |
| `/api/agency/portal/sent` | `agency_io.mark_portal_sent` | ✅ |
| `/api/agency/portal/token` | `agency_portal_io.link` (+ rotate) | ✅ |
| `/api/portal/submit · /message · /bootstrap` | `agency_portal_io` | ✅ (portal listener) |
| `/api/agency/dyson/generate · /decision` | `agency_dyson` | ✅ |
| `/api/agency/workflow/save · /decision` | `agency_workflows_io` | ✅ |
| `/api/agency/build/generate · /delete · /status · /handoff` | `agency_build_studio` | ✅ |
| `/api/agency/eco/generate · /competitor` | `agency_eco` | ✅ |
| `/api/agency/eco/decision` | `agency_eco.decision` | ❌ dead (approvals path is used instead) |
| `/api/agency/eco/image` | `agency_eco.generate_concept_image` | ❌ dead — feature has no button |
| `/api/agency/approval/decision` | `agency_approvals_io.decide` | ✅ |
| `/api/agency/calls/log · /undo · /goal` | `agency_calls` | ✅ |
| `/api/agency/callsheet/*` (7 verbs) | `agency_callsheet` | ✅ |
| `/api/agency/agents/chat` | `agency_agents.chat` | ✅ |
| `/api/agency/agents/task · /task/update · /learn` | `agency_agents` | ❌ dead |
| `/api/agency/social/post/save · /status · /delete` | `agency_social` | ✅ |
| `/api/agency/settings/save` | `agency_io.save_settings` | ✅ |
| `/api/agency/ghl/tags/sync` | `agency_ghl.ensure_service_tags` | ✅ |

**No UI call anywhere targets an unregistered agency path** — there are zero 404s
in the frontend→backend direction. Every POST in the dispatch chain is present in
the allowlist and vice versa.

---

## 2. Broken (with file:line)

### 2.1 The generated client-portal link 403s for every real client — `connector.py:2461`, `:4642`, `:4821`
`PORTAL_BASE` defaults to `https://forge-reios.tail0a2dda.ts.net`
(`connector.py:2462-2463`) — the **tailnet** host, served by the main `Handler`,
whose very first line is `if not self._dashboard_client_allowed(): 403`
(`connector.py:4642`, gate at `:2972-2977`). The public-safe `PortalHandler`
exists and is correct, but only starts when `FORGE_PORTAL_PORT` is set
(`connector.py:4821`), and nothing in the repo sets it — not `.env.example`, not
a service file. `PORTAL_BASE` also carries no port, so even with the second
listener running the copied link still points at the private one.
**Net effect: "Generate portal link" produces a URL the client cannot open.**
This is the single hardest blocker in the onboarding chain.

### 2.2 Client login calls a permanent stub — `agency_io.py:405-413` ← `agency_clientview.jsx:47`
`client_login()` returns `{"ok": False, "detail": "client login not enabled"}`
unconditionally. `CvLoginGate.doLogin` posts to it and renders
"Invalid credentials — check your email and access token."
(`agency_clientview.jsx:47-53`) — a false error message for a feature that does
not exist. Currently unreachable because `CV_LOGIN_FLAG`
(`agency_clientview.jsx:34`) reads `window.AGENCY_CLIENT_LOGIN`, which nothing
sets. It is a loaded gun: flipping that flag hands clients a login screen that
can only ever say their password is wrong.

### 2.3 Revenue page counts leads and churned clients as revenue — `agency.jsx:623-626`, `:633-635`, `:652-656`
`clients` is filtered on `c.mrr > 0` only — status is ignored. The KPIs then read
`st.mrr || totalMrr`. `agency_io.stats()` deliberately counts MRR for
`status ∈ {active, paused}` only (`agency_io.py:233-234`), so when no client is
active `st.mrr` is a legitimate `0`, `||` falls through, and the page reports the
MRR of **leads and churned clients** as live revenue. "Paying Clients"
(`agency.jsx:635`) has the same defect. The Dashboard tile (`agency.jsx:463`)
uses `st.mrr` directly, so the two pages disagree.

### 2.4 The Edit Requests tab is showing three fabricated requests right now — `agency_requests_io.py:31-70`, `:73-80`
`_load()` returns a deep copy of `_SEED` whenever `agency_requests.json` is
missing **or unparseable** — not just on first run. That file does not exist in
this working tree (`marcus_state/` has `agency.json`, `agency_agents.json`,
`agency_messages.json` only), so the operator's live queue currently contains
"Bloom Dental — Swap homepage hero image", "Peak Fitness — Add online class
booking page" and "Bloom Dental — Fix contact form not sending" as if they were
real client work. They are also eligible for Dyson generation and the approval
queue. A corrupt write resurrects them at any time.

### 2.5 The client picker offers two fake clients — `agency_ui.jsx:49-51`, `:87`
`UiClientSelector` falls back to `UI_DEMO_CLIENTS` (`demo-bloom`, `demo-peak`)
whenever the live book is empty — which it is (`marcus_state/agency.json` holds
`clients: []`). `UiRequestForm.submit` (`agency_ui.jsx:113-122`) will happily
persist `clientId: "demo-bloom"` into the **real** request store, and
`agency_eco.jsx:205` will strategise against a client that does not exist
(`agency_io.get_workspace("demo-bloom")` → `None`).

### 2.6 `plan` is two different things — `agency_callsheet.py:353-354` vs `agency.jsx:14`, `:248-250`
Escalating an interested lead writes `client["plan"] = agency_offers.line(offer)`
— e.g. `"Website + App Combo — $1,100"`. The client form renders `plan` in a
`<select>` whose options are `Starter/Growth/Pro/Custom`. A controlled select with
an unlisted value renders as blank/first-option, so the operator sees a plan tier
that does not match the stored string, and one touch of the dropdown silently
destroys the quoted-offer record. Nothing else stores the quote.

### 2.7 One-time deal value is never stored as a number — `agency_callsheet.py:344-349`
`mrr` is set from the offer **only when `offer["monthly"]` is true**, and none of
the three published offers is monthly (`agency_offers.py:132` asserts it). A
closed $350 / $600 / $1,100 sale therefore contributes `mrr = 0` and lands
nowhere countable. The Revenue page can only ever show recurring revenue that no
current offer produces.

### 2.8 Settings that nothing reads — `agency.jsx:880-897` vs `agency.jsx:217`
Settings promises "Default plan for new clients" and, under Default services,
"Pre-selected when adding a new client." `AgClientForm`'s `blank`
(`agency.jsx:217`) hardcodes `plan: "Growth"`, `services: []` and never reads
`/api/agency/settings`. Both settings save correctly and are then ignored.
(`billingSource` is likewise stored and never used by any code path.)

### 2.9 Unguarded `int()` on live query strings — `connector.py:2442`, `:2505`
`api_agency_ghl_contacts` and `api_agency_ads` parse `limit` / `days` with a bare
`int()`. `/api/agency/ads?days=abc` raises `ValueError` → the generic 500 handler
(`connector.py:4681-4683`). `connector.py:625` already ships `_qint()` for exactly
this; these two handlers just don't use it.

### 2.10 `sentAt` written as an ISO string where every other writer uses epoch ms — `agency.jsx:121`
The optimistic fallback in `markSent` sets `sentAt: new Date().toISOString()`,
while `agency_io.mark_portal_sent` (`agency_io.py:340-343`) and `window.timeAgo`
both use integer ms. Only fires when the POST returns no `client`, so it is a
latent "Sent NaN ago", not a crash.

### 2.11 Smaller notes
- `agency_eco.generate_concept_image` is dispatched at `connector.py:3411` and
  has no caller in any `.jsx` — a built, unreachable feature.
- `agency_agents.send_task / update_task / learn` (`connector.py:3441-3448`) and
  `list_tasks` (`:2546`) form a complete task subsystem with no UI at all.
- `agency_deploy.status` (`connector.py:2569`) is dead; the deploy path is only
  ever exercised through `agency_approvals_io._dispatch_approve`
  (`agency_approvals_io.py:170-179`) → `agency_dyson.apply`.
- `agency_io.get_settings` (`:396-402`) merges stored over defaults, so the stale
  `"team": []` key already present in `marcus_state/agency.json` is echoed
  forever alongside `teamMembers`. Harmless, but it never gets cleaned.
- `agency_ghl.apply_contact_tags` (`:119-132`) no-ops without a hand-pasted
  `ghlContactId`. Nothing creates the GHL contact, so CRM sync is copy-paste.
- No `console.log`, no `TODO`/`FIXME`, no un-awaited `apiPost`, and no empty
  `except:` that hides a real failure were found in the agency files. The
  swallowed exceptions that do exist (`agency_io.py:367`,
  `agency_portal_io.py:62-68`, `agency_messages_io.py:74`) are deliberate,
  documented best-effort side-effects on a page-load path.

---

## 3. Missing — the onboarding gap list

Concretely, between *"prospect says yes on a cold call"* and *"client is live in
the dashboard paying monthly"*:

1. **A proposal / signed state.** `STATUSES` jumps `lead → building`. There is no
   `proposal_sent`, no `signed`, no `awaiting_payment`. The quoted offer survives
   only as English inside `plan`.
2. **Any contract or signature step.** `toolkit_contracts.py` exists for the
   wholesale side and is not wired to the agency at all.
3. **A way to ask for money.** No payment link, no checkout session, no invoice,
   no deposit. Nothing on the agency side calls Stripe. The operator sends money
   requests entirely outside the system.
4. **A subscription object.** Retainer/MRR is a number an operator types. Nothing
   knows whether it was billed, collected, is late, or stopped.
5. **A payment webhook.** Nothing in the repo listens for `checkout.session.completed`
   or `invoice.paid`, so the system can never learn that a client paid — even the
   daycare only learns via a manual "Sync" button.
6. **Automatic record creation on payment.** The client record is always typed or
   escalated by hand. There is no "payment → create client → mint portal token →
   send welcome" chain.
7. **A reachable portal.** §2.1 — the link the operator copies 403s for the client.
8. **A welcome delivery.** `mark_portal_sent` is a manual "I sent it" checkbox
   (`agency.jsx:115-124`); no email or SMS is composed or sent.
9. **A GHL contact.** `ghlContactId` must be pasted by hand before tags apply.
10. **A one-time revenue number.** §2.7 — build fees are invisible to reporting.
11. **A real start date.** `portal.startDate` is a free-text label; nothing
    computes a billing anniversary, a term, or a renewal.
12. **Client identity.** Link-possession only. No account, no per-user audit, no
    second contact at the client, no revocation short of rotating the token.

---

## 4. Fix Plan — ordered, smallest diff first

**Applied in Phase 2 (this pass):**

1. `connector.py:2442, 2505` — use the existing `_qint()` helper. 2 lines.
2. `agency.jsx:121` — `Date.now()` instead of `toISOString()`. 1 token.
3. `agency.jsx:623` — filter the Revenue client list to `status ∈ {active, paused}`
   so it matches `agency_io.stats()` and the Dashboard tile. 1 line.
4. `agency_ui.jsx:49-51, 87` — delete the demo-client fallback so a fabricated
   `clientId` can never be persisted. Net deletion.
5. `agency_requests_io.py:31-80` — stop seeding the live request store with mock
   Bloom Dental / Peak Fitness records. Net deletion; the module's own docstring
   asks for this once the portal is wired, and it is.
6. `agency.jsx` — read `/api/agency/settings` in `AgencyClients` and apply
   `defaultPlan` / `defaultServices` to a *new* client form, making the existing
   Settings copy true.

**Deliberately not touched (needs an operator decision, see §5 of the report):**

7. Set `FORGE_PORTAL_PORT` + `FORGE_PORTAL_BASE` and put a Tailscale Funnel in
   front of the portal listener. Code is already correct; this is config on the
   live box, so it is the operator's call, not an edit.
8. Decide whether client login exists. Either delete `client_login` +
   `CvLoginGate`, or implement it. Leaving a stub behind a flag is the worst of
   the three.
9. Split `plan` (tier) from the quoted offer — add a `quote` field, or make the
   client form a free input. Either is a schema decision.
10. Add `oneTimeValue` (or a `deals[]` list) so build fees are countable.
11. Add a `signed` / `awaiting_payment` status and a Stripe payment-link
    generator + `invoice.paid` webhook. This is the actual product gap and is a
    build, not a fix.
