# PLAN.md — Wholesaler Toolkit (Forge REI OS extension)

> **Single source of truth** for the Wholesaler Toolkit build. The
> `wholesaler-toolkit-build-guard` skill reads this file at the start of every
> coding session. Update the Phase Status and Session Log at the end of every
> work session. Scope changes get logged HERE, not left in chat history.

---

## PHASE STATUS (update every session)

| Phase | Module | Status |
|---|---|---|
| 0 | Audit + plan + skeleton | ✅ SHIPPED (2026-07-09) |
| 1 | Deal Calculator | ✅ SHIPPED (2026-07-09) |
| 2 | Buyer Blast Engine | ✅ SHIPPED (2026-07-10) — sends STUBBED (Open Decision #1) |
| 3 | Deal Pipeline / Organizer | ✅ SHIPPED (2026-07-10) |
| 4 | Contracts | ✅ SHIPPED (2026-07-10) — sandbox-only; production blocked (Open Decision #4) |

**Locked build order: 1 → 2 → 3 → 4. Do not resequence without asking.**

---

## 1. AUDIT FINDINGS (2026-07-09)

### Tech stack
- **Backend:** Python 3 **stdlib only** (`connector.py`, ~2700 lines, port 7799).
  No framework, no pip deps. `http.server.BaseHTTPRequestHandler`.
- **Frontend:** static React 18.3.1 UMD + in-browser Babel — **no build step**.
  Every `.jsx` is a `<script type="text/babel">` tag in `FORGE REI OS.html`,
  loaded in order (icons → data → api → shell → pages → app last).
- **Database:** none. GoHighLevel (GHL) is the live system of record (mirrored,
  45s in-process cache). Local state = JSON stores in `marcus_state/`
  (threading.Lock + `_load`/`_save` + `forge_atomic.atomic_write_json` —
  reference implementation: `agency_io.py:13-51`).
- **Auth:** none at app level. Network-level only: DO firewall blocks :7799
  publicly; access via Tailscale/SSH tunnel (`open-dashboard.sh`). Telegram has
  real 2FA authz (`telegram_io._authorized`).
- **Hosting:** DigitalOcean droplet `24.199.81.124`, systemd `forge-reios`,
  `FORGE_MARCUS=1` on box (loops), `FORGE_MARCUS=0` local (UI-only).
- **Deploy:** `./deploy/push.sh root@24.199.81.124` — validates every .py (ast)
  + .jsx (Babel), rsyncs, restarts, SSH-verifies health + secrets-404.

### Route + store conventions (follow or white-screen)
- GET: add to `ROUTES` dict (`connector.py:1954`); real-time → `NO_CACHE` set.
- POST: add path to `do_POST` allowlist tuple (`connector.py:2275`) + `elif` dispatch.
- New JSON store: copy `agency_io.py` pattern → `marcus_state/<name>.json`.
- New `.jsx`: unique hook aliases (`useStateTk` etc.), unique prefixed top-level
  names, export via `Object.assign(window, {...})`, `<script>` tag before `app.jsx`.
  No computed JSX tags (`<Icons[x]/>` forbidden — resolve to const first).
- Validate before deploy: `python3 -c "import ast; ast.parse(open('F').read())"`
  + `node deploy/valjsx.js F`.

### Existing features that overlap the toolkit
| Feature | Where | State |
|---|---|---|
| MAO calculator | `pages.jsx:812-960` (`DealCalcPage`) | Working: ARV/repairs/fee/adjustable %, GO-NEGOTIATE-PASS verdict, repair presets (Light $10k / Moderate $25k / Heavy $50k / Gut $90k), manual comps, persists via `deals.py` (`/api/deals/save`) |
| Underwriting agent | `deal_prep.py` (Atlas) | Auto-preps every 15 min: offer anchors from seller ask, MAO note, facts, call card. Deliberately does NOT invent ARV/repair dollars |
| Buyer CRM | `buyers.py` + `buyers.jsx` | Local JSON roster (cap 2000): areas, price band, property types, beds, condition, POF, strategy. **Buy-box match scorer 0-100** (`score_buyer`: area 45 hard, price 35 hard, type 12, beds 4, condition 4). Dispo worklist + assign UI |
| Pipeline kanban | `pages.jsx:1231` (`PipelinePage`) | Drag-drop, live GHL mirror (`/api/pipeline`, `/api/pipeline/move` → GHL PUT). Stages come from GHL. Auto-advance on offer/contract/close (`_sync_deal_pipeline`) |
| Contracts / e-sign | `docusign_io.py` + `connector.py:1215-1247` | DocuSign JWT client built (openssl-signed RS256, no deps). Purchase-agreement template send with ~20 prefilled tabs; envelope status poller (`_contract_poll_once`, 10 min) auto-advances GHL to Closed/Won. **INERT: creds file missing, sandbox base, RSA key needs rotation** |
| SMS send | `sms_guard.py` + `connector.py:2091` | Single gated path: DNC/quiet-hours(9a-8p ET)/dedupe/price-quote bans. Per-seller, one-at-a-time. **Not a bulk path** |
| Email send | — | **NONE.** No SMTP/SendGrid/SES anywhere. Digest rides GHL/LeadConnector relay. Greenfield |
| Deal sheet | `connector.py:1044` (`_deal_prefill`) | Assembles deal record from GHL contact + screening (address/beds/baths/sqft/condition + ARV/repairs/MAO/offer) |
| Comps | manual list in DealCalc | No comps API. RentCast flagged as future (`pages.jsx:813`) |
| Photos | — | `uploads/` dir exists, HTTP-blocked, no upload endpoint. Greenfield |

### Integrations already wired
GHL wholesale (`marcus-wholesale-agent/config/ghl.env`) · GHL agency
(`forge-agency/config/agency.env`) · Anthropic Claude (`review_agent._claude`,
model in `review_agent.MODEL`) · Telegram alerts + tap-approve
(`forge-telegram/config/telegram.env`) · Retell voice (read-only) · Meta Ads ·
DocuSign (inert) · n8n · Metricool · GitHub→Vercel. Creds all in git-ignored
`*.env` OUTSIDE web root — never served (must 404).

### Design system
"Dark Luxury SaaS" — `styles.css` tokens: bg `#050B18`, card `#101827`, blue
`#4F7CFF` (REI accent), green/orange/red/violet, text ramp `#F1F5FB→#64748B`,
radii 12/18/22, Geist + Geist Mono. Shared classes `.card .pill .tab .faint
.mono`; layout via inline styles. Icons: `icons.jsx` (`window.Icons` — DealCalc,
Dollar, Doc, Send, Flame, Clipboard all exist). Data hook: `window.useApi(path,
{interval})` + `window.apiPost`. Page = plain function on `window`, registered
in `data.jsx` NAV + `app.jsx` page map.

---

## 2. MODULE MAPPING (build fresh / extend / reuse)

### Module 1 — Deal Calculator → **EXTEND** `DealCalcPage` + new `toolkit_calc.{py,jsx}`
Keep the working MAO calc. Add on top:
- **Repair cost estimator by condition tier:** $/sqft × tier × sqft (tiers seeded
  from existing presets; editable rates persisted in `toolkit_calc.json`).
- **Creative finance calculator:** subject-to (PITI takeover, entry fee, cash
  flow), seller finance (price/down/rate/term amortization), novation (net vs
  wholesale comparison). Pure math — no external deps.
- **Dual-view ROI:** toggle Internal (your spread, fee, MAO logic) vs Buyer view
  (purchase → repairs → ARV → buyer profit/ROI; hides your fee derivation).
  Buyer view is what gets embedded in Buyer Blast deal sheets.
- Comps stay manual for v1 (RentCast = Open Decision #2).
**Why extend:** MAO math + persistence + verdict already exist and work; the
gaps are additive views + math, not a rebuild.

### Module 2 — Buyer Blast Engine → **EXTEND** `buyers.py` + **NET-NEW** `toolkit_blast.{py,jsx}`
Reuse as-is: buyer roster, buy-box fields, 0-100 match scorer, dispo worklist.
Net-new:
- **Deal sheet generator:** assembles from `_deal_prefill` + calc numbers
  (buyer-view ROI) + Atlas facts + photos. Stored per deal; shareable render.
- **Photo upload:** small POST endpoint → `uploads/deals/<dealId>/`; served
  through an allowlisted read route (uploads stay out of generic static serving).
- **Blast queue (propose → approve → execute):** match scores select buyers →
  drafts per-buyer SMS/email → operator one-click approve → send loop with
  throttle + per-buyer ledger. NEVER auto-sends. Reuses Telegram tap-approve.
- **Send transport = pluggable stub** until Open Decision #1 (GHL-native vs
  Twilio/SendGrid). Everything up to the wire-send is built and testable.
- **Response tracking:** per-blast per-buyer status (queued/sent/replied/
  interested/passed), reply capture depends on chosen channel.
**Why:** CRM + matcher = done; sending + sheets = genuinely missing.

### Module 3 — Deal Pipeline / Organizer → **EXTEND** kanban as **local overlay** `toolkit_pipeline.{py,jsx}`
Zero GHL mutations. GHL stays source of truth for stages.
- **Stage-entry timestamps:** poller stamps when an opp changes stage →
  `toolkit_pipeline.json`; computes **days-in-stage** badges on existing kanban.
- **Follow-up reminders per deal:** local reminders (due date + note) surfaced
  on the board + Command Center; optional Telegram ping.
- **Wholesale stage mapping:** config dict maps GHL stages → canonical wholesale
  stages (Lead → Under Contract → Marketing → Buyer Found → Closing → Closed).
  Creating/renaming real GHL stages = Open Decision #3 (live CRM change).
**Why:** kanban + drag-drop + GHL sync already work; missing pieces are
metadata, which local overlay adds without touching live CRM.

### Module 4 — Contracts → **REUSE + FINISH** `docusign_io.py` + new `toolkit_contracts.{py,jsx}`
Already built: JWT auth, purchase-agreement template send with ~20 auto-filled
tabs from deal data, envelope status poller, GHL auto-advance on completion.
To finish:
- **Assignment contract generator:** second DocuSign template (assignor/assignee/
  assignment fee/original contract ref) + tab mapping in `toolkit_contracts.py`.
- **Send-Contract UI:** card on deal sheet / pipeline — pick template, preview
  filled fields, send.
- **Signature status tracker:** tab listing all envelopes (sent/delivered/
  signed/completed/declined) riding the existing poller.
- Blocked on Open Decision #4 (creds + key rotation + sandbox test + prod).
**Why:** 80% of the plumbing exists; do not rebuild it.

---

## 3. FOLDER STRUCTURE

Flat prefixed files — same precedent as the `agency_*` module family. No new
top-level directories (build-guard rule; connector imports flat modules, HTML
loads flat script tags, deploy validators glob flat).

```
forge rei dash/
├── PLAN.md                      ← this file (source of truth)
└── forge rei/
    ├── toolkit_calc.py          # repair-tier estimator, creative finance math, ROI views, store
    ├── toolkit_blast.py         # deal sheet gen, photo store, blast queue, response tracking
    ├── toolkit_pipeline.py      # stage-entry timestamps, days-in-stage, follow-up reminders
    ├── toolkit_contracts.py     # assignment template mapping, contract send helpers, tracker
    ├── toolkit_calc.jsx         # calculator UI (repair tiers, creative finance, dual-view ROI)
    ├── toolkit_blast.jsx        # deal sheet + match/blast/approve + response board UI
    ├── toolkit_pipeline.jsx     # kanban overlay widgets (badges, reminders)
    └── toolkit_contracts.jsx    # send-contract card + signature status tracker
```

- JSON stores: `marcus_state/toolkit_{calc,blast,pipeline,contracts}.json`
- Photos: `uploads/deals/<dealId>/` (HTTP-blocked dir; served via explicit route)
- Hook aliases reserved: `useStateTk/TkB/TkP/TkC` (+ matching useMemo/useEffect/useRef)
- Routes namespace: `/api/toolkit/...`

## 4. PHASED BUILD PLAN

### Phase 1 — Deal Calculator (complexity: LOW-MED) ← NEXT
Build: `toolkit_calc.py` store + math endpoints; `toolkit_calc.jsx` — repair
tier estimator, creative finance (subto/seller-finance/novation), dual-view ROI
toggle; wire into DealCalc tab; save alongside existing `deals.py` records.
Dependencies: **none** (pure math + UI).
Done = operator can price a deal all four ways and flip to buyer view.

### Phase 2 — Buyer Blast Engine (complexity: HIGH)
Build: `toolkit_blast.py` — deal sheet generator, photo upload endpoint, blast
queue store, response tracker; `toolkit_blast.jsx` — sheet preview, matched-buyer
list w/ scores, approve-and-send flow, response board. Transport behind stub.
Dependencies: **Open Decision #1** (channel) before live sends; photos none.
Done = new deal → sheet auto-drafts → matched buyers queued → operator approves
→ (stub) sends logged → responses tracked.

### Phase 3 — Deal Pipeline / Organizer (complexity: LOW-MED)
Build: `toolkit_pipeline.py` poller + reminders store; `toolkit_pipeline.jsx`
badges + reminder UI on existing kanban.
Dependencies: none for overlay. **Open Decision #3** only if real GHL stages wanted.
Done = every card shows days-in-stage; reminders fire on Command Center/Telegram.

### Phase 4 — Contracts (complexity: MED)
Build: `toolkit_contracts.py` assignment mapping; `toolkit_contracts.jsx` send
card + tracker tab; second template in DocuSign account.
Dependencies: **Open Decision #4** — DocuSign creds file on box
(`forge-docusign/config/docusign.env` + .pem), RSA key rotation, sandbox test,
then prod base swap. Ohio PA template exists in sandbox already.
Done = pick deal → send PA or assignment → status visible → GHL auto-advances.

---

## 5. OPEN DECISIONS / COME BACK ⚠️

1. **Blast channel — RESOLVED 2026-07-10: GHL-native (the recommended option).**
   `connector._blast_transport` upserts each buyer into GHL tagged `buyer` and
   sends via the conversations API (SMS only for v1; email recipients are
   skipped, not failed — GHL email needs a configured location mailbox). Live
   sends require BOTH the registered transport AND `FORGE_BLAST_LIVE=1` in the
   box environment — the flag is OFF by default, so sends stay stubbed until
   the operator flips it (add `Environment=FORGE_BLAST_LIVE=1` to the systemd
   unit or its env file, then restart). Every send remains operator-gated in
   the UI, and TCPA 9am-8pm ET quiet hours block buyer texts like seller texts.
2. **Comps/ARV source:** RentCast API (free tier 50 req/mo; paid from ~$74/mo)
   vs manual comps. v1 = manual. **UPDATE 2026-07-11 (operator-ordered):** an
   **AI ARV finder** shipped — `toolkit_calc.find_arv` (Claude + Anthropic
   `web_search` server tool, conservative bias, JSON comps) behind POST
   `/api/toolkit/calc/arv`, surfaced on desktop + mobile Calc. Manual comps
   stay; RentCast remains optional/deferred. ARV numbers are INTERNAL prep
   only (same rule as Atlas — never quoted to a seller).
3. **GHL wholesale stages:** create the 6 canonical stages in the live GHL
   pipeline? Live CRM change — needs explicit operator approval.
4. **DocuSign:** **Option C selected for v1 (2026-07-10): sandbox only.**
   Production sending is blocked in `toolkit_contracts.py`. Before a production
   change: rotate the compromised RSA key, place replacement credentials in the
   box secret store, validate sandbox auth, then explicitly approve the base swap.

## 5b. OPERATOR-APPROVED SCOPE ADDITIONS

- **FORGE Mobile (2026-07-09, explicit operator directive):** PWA at
  `forge rei/mobile/` served by connector (`/m` alias). Operates the dashboard
  from the phone over Tailscale (box stays firewalled; no keys in the app —
  same-origin `/api/*` only; all outward actions stay behind the same gated
  POSTs). Outside the four toolkit modules — fast-tracked by the operator on
  2026-07-09. Tabs: Home (approvals/hot leads/KPIs/ops pill), Convos, Pipeline,
  Calc (incl. Phase 1 toolkit), Agents chat + bus, More (buyers/deals/brain/
  costs/health). Stack identical to desktop: React UMD + in-browser Babel, no
  build step; mobile files use M-prefixed hook aliases in their own page scope.

## 6. OUT OF v1 SCOPE (v2 backlog — do not build without explicit override)

- Driving-for-dollars / on-site property scanning
- Standalone analytics or reporting dashboards
- Multi-user accounts / teams / permission roles
- Anything not in the four modules above

---

## 7. SESSION LOG

- **2026-07-11 — Four operator-ordered features (Quick Send · AI ARV · tappable
  Home · Telegram-synced agents):** all shipped, tested, deployed, box-verified.
  **(1) Send Contract / Quick Send (Module 4 extension):** operator uploads his
  OWN contract file (PDF/DOCX, base64 data-URL — blast-photo wire pattern,
  files in HTTP-denied `marcus_state/contract_templates/`, registry
  `toolkit_templates.json`, 10 MB/20-template caps) then emails it to a seller
  with name/email/address/price via `docusign_io.send_document` (raw-document
  envelope, free-form signing — works for any contract, no tab mapping; price/
  closing ride in the email subject/blurb). `toolkit_contracts.quick_send` keeps
  the v1 gates (named operator + sandbox-only) and records a `custom` row in the
  existing contracts ledger so status/void/tracker flows just work. Routes: GET
  `mytemplates`, POST `template/upload`, `template/delete`, `quicksend`. UI:
  More → "Send Contract" sheet on mobile (upload → 2-field-card → send) +
  CTQuickSend card on the desktop Contracts tab. +5 TDD tests.
  **(2) AI ARV finder (see Open Decision #2 update):** `review_agent._claude`
  grew an additive `tools=` param; `toolkit_calc.find_arv` runs Claude with the
  Anthropic web_search tool (max 4 searches), parses strict JSON ({arv, low,
  high, confidence, comps[≤5], summary}), biases conservative. Cards on mobile
  Calc (top) + desktop TkCalcPanels with one-tap "Apply → ARV" (desktop wired
  via new `onApplyArv` prop from DealCalcPage). Live-verified on the box against
  a real Wilmington DE address (returned $115k ARV w/ 5 real 2025-26 comps,
  low-confidence flagged). +4 tests. MAO/repair math already recomputed live
  client-side — unchanged.
  **(3) Tappable Home stats:** `MApp` exposes a `window.mGoTab` bridge; the 2×2
  stat tiles now navigate — Hot Leads → new full-screen `MHLeadsSheet` (ALL
  Scout leads, bucket chips incl. Dead, handoff buttons; verified 19 leads
  live), Replies → Convos tab, Pipeline/$ + Open Opps → Pipeline tab. Tiles get
  a chevron + press animation (`.m-stat.tappable`).
  **(4) Telegram-synced agent chat:** new `agents_history.py` store
  (`marcus_state/agents_chat_history.json`, 200 turns/agent, atomic+locked) —
  ONE thread per REI agent shared by dashboard, mobile, and the Telegram agent
  bot: the connector's `/api/agents/chat` handler and `_tg_agent_chat` bridge
  both record turns (tagged `via: dash|telegram`) and fall back to stored
  history for context; new GET `/api/agents/history`. Dyson/Eco reuse
  agency_agents' own persistent history (no double-tracking). `m_agents.jsx`
  rebuilt Telegram-style: avatar header w/ online dot + "typing…", date chips
  (Today/Yesterday), asymmetric bubble tails, in-bubble clock + ✓, tiny
  send-icon marker on Telegram-originated turns, pill composer + round send
  button, 12s thread polling so Telegram messages appear without reload.
  Chat-record round-trip verified live on the box.
  All .py ast-validated, all .jsx valjsx-clean, suites green (contracts 19,
  calc 25, blast/pipeline/sms_guard/ace regressions OK). Deployed via push.sh
  (health gate passed); box-verified: new endpoints 200, mobile files 200,
  `agents_chat_history.json` + `toolkit_templates.json` 404 over HTTP, DocuSign
  sandbox configured=true. Browser-verified every flow against the box +
  iOS-Simulator-verified rendering.
- **2026-07-10 — Mobile PWA scroll/layout fix + iOS Simulator test:** FORGE
  Mobile (`/m`) pages were frozen — nothing scrolled in iOS standalone-PWA mode.
  Root cause: body-scroll model (sticky `.m-head` + fixed `.m-tabbar`, page
  content in a `flex:1` `.m-content` with no `overflow` and no `min-height:0`),
  which iOS standalone does not treat as scrollable. Fixed in `mobile.css` by
  converting to a fixed app shell: `html,body{overflow:hidden}`, `.m-app`
  `height:100dvh; overflow:hidden`, header/tabbar `flex:0 0 auto; position:
  relative`, and `.m-content` becomes the single scroller (`flex:1 1 auto;
  min-height:0; overflow-y:auto; -webkit-overflow-scrolling:touch`). Removed the
  86px bottom-padding hack (tab bar is now a real flex sibling, not overlapping).
  `m_agents.jsx` chat area switched from a magic `calc(100dvh - 358px)` height to
  `flex:1 1 auto` so the composer stays pinned inside the bounded scroller.
  Verified via CDP: all 6 tabs render with `overflow-y:auto`, no React errors,
  Home/Convos/Calc scroll (scrollHeight > clientHeight); confirmed by touch-drag
  in the iOS Simulator (content moves, header + tab bar stay pinned). Deployed to
  the box (health gate passed); the box serves the fixed CSS + agents flex change
  and `/m` + all toolkit/dashboard endpoints 200. Installed the PWA on the
  Simulator pointing at the **box** Tailscale IP (`100.87.232.91:7799/m`) so the
  app runs off the 24/7 dashboard with live box data (19 hot / 43 approvals),
  launching fullscreen (no browser chrome) and scrolling correctly.
- **2026-07-10 — Mobile Home redesign (sleeker/organized):** Reworked the Home tab
  (`m_home.jsx` + `mobile.css`) for visual hierarchy. Flat cramped 4-across KPI
  row → **2×2 stat-tile grid** (`.m-stat-grid`/`.m-stat`): each tile has a tinted
  accent icon chip (flame/chat/$/board) + big accent-colored value + uppercase
  label. Added a reusable **section-header** pattern (`.m-section`, MHSection):
  quiet uppercase label + optional count pill + divider — zones the page into
  "Needs you" (approvals, amber count) and "Scout · hot leads". Removed the inner
  MCard titles (section headers carry them); Scout's "N live" count moved inline
  next to the bucket chips. No data/logic changes, no new endpoints, still in v1
  scope (Home polish). valjsx clean; deployed to box; verified in the iOS
  Simulator against box data (2×2 tiles, section headers, scroll all correct).
- **2026-07-10 — Completion pass (post-audit):** Audit of the Codex build found
  one real gap: Phase 4 shipped **without the assignment contract** that §2
  Module 4 specified (Codex built sfr/multi/land only — the deviation traced to
  the handoff prompt itself and was never logged here; logged now). Fixed this
  session (TDD, +4 tests): `assignment` template type in `toolkit_contracts`
  + `docusign_io.template_map` (`DOCUSIGN_TEMPLATE_ASSIGNMENT` env key) —
  assignee-signed (the end buyer), tabs map assignor/assignee/assignment_fee/
  original_purchase_price/original_contract_date; PA prefills still never
  expose the fee. Desktop preview renders assignment-specific fields.
  **Open Decision #1 RESOLVED: GHL-native** — `toolkit_blast` grew a
  `register_transport()` hook (+4 tests); the connector registers
  `_blast_transport` (GHL contact upsert tagged `buyer` → conversation → SMS,
  quiet-hours enforced). Live only when `FORGE_BLAST_LIVE=1` (default OFF —
  currently OFF on the box, so sends remain stubbed); the Blast UI banner,
  send button, confirm dialog, and summary now reflect stub vs LIVE mode.
  Mobile parity: `m_pipeline.jsx` gained the Phase 3 overlay (days-in-stage
  badges mirroring desktop thresholds + reminder chips + set/snooze/dismiss/
  mark-handled bottom sheet); `m_more.jsx` gained a Contracts section (ledger,
  status pills, assignment-aware detail, gated send-approval/status-check/void;
  creation stays desktop-only). **167 tests pass** (159 + 8 new), all touched
  files validated, browser-verified desktop (Contracts/Blast/Pipeline tabs) +
  mobile (More→Contracts, Pipeline badges). Deployed to the box: service
  active, `assignment` in the live template catalog, `live: false` confirmed,
  mobile files 200, secrets 404. Remaining before assignment sends work:
  create the assignment template in the DocuSign sandbox account and set
  `DOCUSIGN_TEMPLATE_ASSIGNMENT` in `forge-docusign/config/docusign.env`
  (it lists as "not configured" until then). Open Decisions #2 (comps), #3
  (GHL stages), #4 (DocuSign prod) remain open — all operator calls.
- **2026-07-10 — Phases 3 & 4 SHIPPED (Codex):** Phase 3 adds the read-only
  Pipeline Hub: every live GHL card shows a correctly thresholded days-in-stage
  badge (green <3d, yellow 3–7d, red >7d) plus a local JSON reminder overlay
  (`pipeline_reminders.json`). Reminders can save, edit, snooze, dismiss, and
  record an operator handoff; they never send a message or mutate GHL. 15 new
  TDD tests pass. Phase 4 adds the Contracts tab + `contracts.json` lifecycle
  ledger: template catalog, deal prefill preview, explicit named-operator
  approval, sandbox JWT send, status refresh, signed/completed tracking, and
  gated voids. 10 new TDD tests pass. Decision #4 is **Option C: sandbox-only**;
  production DocuSign calls are code-blocked pending secure key rotation.
  Generated 10 sRGB raster UI/PWA assets plus a deterministic SVG favicon; every
  asset is responsive, integrated with alt text where rendered, and under 1 MB.
  Full discovery regression: **159 tests passed**. Deployed to the box: service
  active; new APIs and all assets 200; `ghl.env` and state traversal 404.
- **2026-07-09 — Phase 0:** Audit completed, plan approved by operator, PLAN.md
  written, stub skeleton files created (headers only, no logic, not yet wired
  into HTML/connector). Blast-channel decision explicitly deferred by operator.
- **2026-07-09 — Phase 1 SHIPPED:** Deal Calculator complete. `toolkit_calc.py`
  (rates store, repair estimator w/ ceil-to-$500, seller-finance amortization +
  balloon, subject-to, novation-vs-wholesale, internal/buyer dual views,
  evaluate() aggregator, save_snapshot rides deals.py). 21 unit tests green
  (`test_toolkit_calc.py`), zero regressions. Routes: GET
  `/api/toolkit/calc/config`, POST `/api/toolkit/calc/{eval,rates,save}`.
  `toolkit_calc.jsx` (TkCalcPanels) mounted at the bottom of DealCalcPage,
  guarded (`window.TkCalcPanels &&`). Browser-verified locally: estimate →
  Apply → MAO recalc → buyer view hides fee. Implementation plan:
  `docs/superpowers/plans/2026-07-09-phase1-deal-calculator.md`. No deviations
  from plan. Next: Phase 2 Buyer Blast (blocked on Open Decision #1 for live
  sends; everything up to transport can build now).
- **2026-07-10 — Phase 2 SHIPPED (Buyer Blast Engine):** `toolkit_blast.py` —
  deal-sheet generator (reuses `toolkit_calc.buyer_view`, assignment fee NEVER
  exposed), photo store (base64 → `uploads/deals/<id>/`, image-only, caps),
  blast queue (`create_blast` drafts per-buyer SMS+email from `buyers.match`),
  send loop + response tracking. 18 unit tests green (`test_toolkit_blast.py`),
  zero regressions (44 existing pass). **Send transport is a STUB**
  (`TRANSPORT_LIVE=False`, `_transport()` records `stub-sent`, nothing leaves
  the box) — Open Decision #1 (channel) stays OPEN; wiring it later = swap one
  function + flip one flag. Routes: GET `/api/toolkit/blast/{list,get,matches}`,
  POST `/api/toolkit/blast/{create,send,respond,recipient,photos}`. Photos
  served via a narrow static-handler allow (`uploads/deals/<id>/<image>` only;
  traversal + secrets stay 404). UI `toolkit_blast.jsx` (`BlastPage`, subagent-
  built) = new REI "Buyer Blast" tab (nav + Blast icon + page map + script tag):
  deal picker (homeowner search / dispo worklist), deal sheet w/ photo upload,
  channel chips, matched-buyer list w/ scores + checkboxes, create → blast
  detail w/ editable drafts + stub-send + response segmented control, persistent
  amber STUB banner. Browser-verified (search→pick→sheet→create button; all
  tabs render, no regressions). Plan:
  `docs/superpowers/plans/2026-07-10-phase2-buyer-blast.md`. No deviations.
  Next: Phase 3 Pipeline Organizer (days-in-stage + reminders overlay).
- **2026-07-09 — FORGE Mobile SHIPPED (operator-approved scope addition, §5b):**
  Full PWA at `forge rei/mobile/` — foundation (index.html w/ `<base
  href="/mobile/">`, manifest, stdlib-generated icons, mobile.css on the
  desktop token set, m_api/m_shell/m_app) + six tab modules built by parallel
  subagents (m_home approvals/hot-leads/KPIs/ops-pill, m_convos list+thread+
  gated reply via /api/reply/send, m_pipeline snap-column board w/ optimistic
  /api/pipeline/move, m_calc full calculator incl. Phase 1 toolkit eval,
  m_agents Marcus/Scout/Atlas/Dyson/Eco chat + bus feed, m_more buyers/dispo/
  deals/brain/costs/health). Connector: `/m` alias only — no new API surface,
  no keys in the app, all outward actions behind the same gated POSTs. All 9
  jsx pass valjsx; zero cross-file global collisions; browser-verified against
  live GHL data (27 real approvals, live pipeline). DEPLOYED to the box with
  Phase 1 in one push; box verified (/m 200, toolkit config 200, secrets 404).
  Access: Tailscale → http://100.87.232.91:7799/m → Share → Add to Home Screen.
  Gotcha logged: the `/m` alias requires the `<base>` tag — relative script
  srcs otherwise resolve to the web root and Babel silently renders nothing.

### 2026-07-11 (later) — Calc: creative finance removed + accuracy pass; app: Daily Brief
**Calc (toolkit, operator-directed).** Removed the "Creative finance" card
(Sub-To / Seller finance / Novation) from BOTH the mobile calc (`m_calc.jsx`) and
the desktop panels (`toolkit_calc.jsx`) — inputs no longer sent in the eval body.
Backend `toolkit_calc.py` functions (seller_finance/subject_to/novation) + their
tests are LEFT INTACT (reversible; 25 calc tests still green). Verified the
remaining math is accurate: MAO = ARV×pct − repairs − fee (floored 0), repairs
ceil-to-$500, buyer/internal ROI, ARV — all test-covered and consistent
desktop↔mobile↔backend. Calc now: AI ARV finder · MAO · Repair estimator ·
Deal views (internal/buyer) · Send offer.
**Daily Brief (app-level, NOT a toolkit module).** New `daily_brief.py` +
connector wiring: one Telegram digest a day (operator-set hour, box tz) of hot
leads / replies waiting / drafts to approve / pipeline / appointments / spend +
top-3 hot leads — so the operation is legible from anywhere with no app/tunnel.
Endpoints `/api/brief` (GET preview+config), `/api/brief/send` (force),
`/api/brief/config` (hour/enable). Scheduler thread (box-only, FORGE_MARCUS,
quiet while clocked out) + `daily_brief` heartbeat (watchdog-monitored). Mobile
More → "Daily brief" sheet (toggle, hour chips, live preview, send-now). Deployed
+ box scheduler fired a real brief; GitHub-mirrored.
