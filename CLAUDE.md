# FORGE REI OS — Operating Manual (CLAUDE.md)

This file governs how Claude (and the in-app AI agents) work on FORGE REI OS. Read it
before making changes. The **RULES** and **DAILY SELF-IMPROVEMENT** sections are yours
to edit — change them and everything downstream follows.

---

## 0. Shortcuts (voice/text triggers)

When the user says any of: **"open dashboard"**, **"open my dashboard"**, **"open the
forge dash"**, **"open forge rei"**, **"pull up the dashboard"** → run:

```bash
~/"forge rei dash/open-dashboard.sh"
```

It ensures an SSH tunnel to the box (`root@24.199.81.124`, connector on `:7799`, blocked
publicly by the DO firewall) and opens `http://localhost:7799/`. Idempotent — safe to
re-run; if already up it just opens the browser. No other action needed.

---

## 1. What this is

A real-estate-wholesaling + AI-agency control center. Static React UI (React UMD +
in-browser Babel, **no build step**) served by a Python stdlib connector
(`connector.py`, port 7799) that mirrors GoHighLevel and runs the AI agents. Lives 24/7
on a DigitalOcean box. Two workspaces (profile switcher):

- **REI (wholesale):** Dashboard, Leads, Conversations, Pipeline, Agents, Brain, etc.
- **Agency (ClientForge):** Clients, Edit Requests, Agents, Ads, Social, Approvals, Brain.

Folders (siblings under `forge rei dash/`, secrets stay OUTSIDE the web root):
- `forge rei/` — the app (this folder): all `.py` engines + `.jsx` UI + `deploy/`.
- `forge-agency/` — agency config (`config/agency.env`) + agent skills (`skills/`).
- `forge-scout/` — Scout config (`config/scout.env`) + seed skills (`skills/`).
- `~/Desktop/Agentic-OS/vault/` — the Obsidian **brain** (FORGE_VAULT; `/opt/forge/vault` on the box).

---

## 2. RULES (edit me — these are the standing rules I apply)

> Plain-English rules. Edit freely; they are the contract for every change.

1. **Auto-deploy.** After ANY edit, push to the 24/7 box: `./deploy/push.sh root@24.199.81.124`, then SSH-verify (service `active`, endpoints 200, secrets 404). Never leave changes local-only. Validate first — never push a broken state.
2. **Propose → review → execute.** Agents never take irreversible or outward actions on their own. Texting sellers, posting socials, moving pipeline, launching ads — all gated behind my one-click approval. The ONLY things agents do autonomously are: score/triage, **auto-apply internal+reversible tags** (offer auto-tag + HOT-lead triage tags — see below), read the brain, write their own learned playbook to the brain, and post notes on the agent bus.
   - **Exception — HOT-lead auto-tag.** `asap` (hot) leads get their triage tags (`triage: asap`, `motivated: high`) pushed to GHL automatically the moment Scout flags them — no approval, because tags are internal + reversible (the "✕ Not hot" remove button undoes them). Warm/nurture tags stay proposals I approve. Outward actions (SMS/pipeline/ads) stay gated. Flip off with `FORGE_SCOUT_AUTOTAG_HOT=0`. Runs every poll (`scout_triage._autotag_hot`), so backlog tags too.
   - **Exception — AUTOPILOT follow-up bumps (operator opt-in, default OFF).** When the operator flips autopilot on (Telegram `/autopilot on`), the routine no-response RE-ENGAGE bumps that followup.py already drafts are auto-sent through `autopilot.maybe_send` — gated by: re-engage drafts only (never first replies, never PRICE/READY/HELP/DNC), legit_check thread verdict, daily cap (FORGE_AUTOPILOT_CAP=10), 9am-8pm ET window, send-ledger dedupe, voice scrub, and a Telegram receipt per send. `/autopilot off` kills it instantly. Everything else stays tap-gated.
3. **Marcus owns texting.** Scout ranks + tags + hands off; it never sends SMS. Same spirit for every agent: one agent per outward channel.
4. **Reply to sellers only — never to our own messages.** Agents never draft a reply to OUR outreach/opener/blast (e.g. "we buy houses", "I was calling about…", "just following up"). Only genuine inbound seller messages get a draft. GHL sometimes mis-flags our own text as inbound; the `_is_our_message()` filter in `marcus_engine.py` (`_OUR_OUTREACH_PHRASES`) skips it. Edit that list to match your scripts.
4. **Secrets stay private.** API keys live in `*.env` files OUTSIDE the web-served folder, git-ignored. Never served over HTTP (must 404). Never paste keys in chat. Don't rotate keys unless I say so.
5. **Don't break what works.** Additive edits. Don't remove existing features/code. Validate before deploy.
6. **Decide, don't quiz me.** On design forks, recommend + reason and proceed; don't hand me multiple-choice cards. Ask only when it's genuinely my call (branding, money, live-system policy).
7. **Direct + specific.** Expert advice, real numbers, no fluff.
8. **Keep proposing.** After finishing, propose the next high-leverage build.
9. **Seller auto-replies: adapt, then push to the call — NEVER a price by text.** Before drafting ANY text-back to a seller, Marcus reads the brain skills — `Skills/seller-reply-playbook.md` (the decision rubric: adapt to exactly what the seller said, short/simple/straightforward/powerful, one job = get them on a quick call, stand your ground), `Skills/wholesale-seller-texter.md` (voice), and `Skills/closing-plays.md` — plus the per-lead brain notes. Every reply is tailored to the seller's actual message, not a canned line. **An agent NEVER states, negotiates, hints at, or invents a price/offer/number over text — ever.** The offer is given by a human, on a phone call; the text exists only to get them on that call. If a seller asks for a number, the agent acknowledges it and pivots to a quick call; if they push again, it holds the line a different way. This is enforced in the prompt AND in code (`marcus_engine._no_price_over_text` swaps any drafted figure for a call-pivot before it ever reaches you). **Approval gate stays ON** — every seller reply is still a proposal you approve; this rule governs draft QUALITY + the price boundary, not autonomy. Flip auto-send on only when you decide the drafts are ready.

*(Add your own rules below this line — they carry the same weight.)*

---

## 3. DAILY SELF-IMPROVEMENT (agents get better every day)

The whole point: the agents improve every day and **never lose what they learned**.

**The loop (already wired):**
1. Agents run against real data (Scout sweeps seller threads; Dyson/Eco work client tasks).
2. They periodically **reflect** — `learn()` asks Claude to look at recent real encounters + the current playbook and **rewrite the playbook** to score/act better.
3. The improved playbook is written into the **brain** (`vault/Skills/<agent>-playbook.md`), **git-committed** so there's history.
4. Each agent **reloads its playbook from the brain on the next run** (mtime-cached → newest version wins automatically). So today's lessons are tomorrow's defaults.
5. The agent **broadcasts** the improvement on the agent bus so the others (and I) see it.

**Triggers:** automatic after N new encounters (Scout: `FORGE_SCOUT_LEARN_EVERY=25`;
agency: `AGENCY_LEARN_EVERY=12`; rate-limited ~45 min), or manual via the "Learn from
brain" button in the Command Center / Agents tab. Marcus also self-learns via the daily
`style_agent` (voice) and weekly `review_agent` (playbook) loops.

**Editing what they learn:** open the Brain tab (either workspace) or edit the vault
markdown directly — `Skills/scout-playbook.md`, `Skills/dyson-playbook.md`,
`Skills/eco-playbook.md`, `Skills/marcus-playbook.md`, `Skills/yahjair-voice.md`. Agents
pick up your edits on the next run (mtime hot-reload). Your edits and their self-edits
merge; the seed playbooks in `forge-*/skills/` are the floor.

---

## 4. SKILLS — every improvement becomes a skill, and the newest version is always used

This is a hard operating principle for Claude AND the agents:

- **Capture, don't lose.** When something new or improved is built or learned, turn it
  into a **skill** — either a new skill or an upgrade to an existing one. Don't leave a
  good pattern as a one-off.
- **Two kinds of skill here:**
  1. **Claude skills** (`~/.claude/skills/<name>/SKILL.md`) — reusable build patterns.
     Canonical example: **`forge-self-improving-agent`** — the recipe for giving any new
     agent its own folder, brain-loaded skills, a self-improvement loop, bus comms, and
     console/deploy wiring. Use it (and keep it current) whenever adding/upgrading an agent.
  2. **Agent skills** (the brain playbooks in `vault/Skills/*.md`) — each agent's living
     rubric, rewritten by its `learn()` loop.
- **Always use the newest version.** Agents mtime-reload their playbook every run, so they
  always score with the latest. Claude: before building, check for an existing skill and
  improve it rather than duplicating; after building something reusable, write/update the
  matching skill so the next session starts from the improved version.
- **Improve in place.** Prefer upgrading an existing skill over creating a near-duplicate.
  When a skill is upgraded, the upgrade is the new default immediately.

### 4a. TOP SKILLS — the constitution (outranks every playbook)

Some skills are **constitutional**: human-owned, stable, and ranked ABOVE the learned
playbooks. When a top skill and a playbook disagree, **the top skill wins**. They are
loaded FIRST and are never truncated; the `learn()` self-improvement loop can neither see
nor rewrite them (that isolation is the point — a self-rewriting constitution is no
constitution).

| Top skill | Applies to | What it enforces |
|-----------|-----------|------------------|
| **`agent-evidence-discipline`** | **ALL agents** (Solomon, Scout, Marcus, Atlas, Dyson, Eco) | **Ground it, infer it, or name it Unknown** — every number/status carries its source or is written Unknown; never invent what a human said, owes, or promised; 3–5 ranked falsifiable hypotheses (never anchor on the first story); **close the loop** (if the next lookup wouldn't change the recommendation, decide); two passes max; propose, never act outward. |
| **`solomon-decision-loop`** | Solomon | How he reasons: Frame → Ground → Hypothesize → Decide → **Close**. The exit condition that kills analysis paralysis; unknowns never block the brief. |
| **`solomon-director-craft`** | Solomon | 50 years of operating judgment: triage order (safety/ratio → compliance → cash → enrollment), funnel-leak vs. lead-volume, speed-to-lead, vacancy as a spoiled good, retention math, seasonality, discounting last. |

Live in `forge-solomon/skills/` (seed) + `vault/Skills/` (brain). Loaded by
`daycare_director.SolomonEngine._load_skills` (constitution, whole) vs. `_playbook_only`
(learned rubric, own budget). Constitution ≈5.1k tokens/brief — that cost is deliberate.
**Adding a top skill for another agent:** drop the `.md` in the agent's `forge-*/skills/`
+ vault, load it ahead of the playbook, and keep `learn()` pointed at the playbook alone.
Pattern credit: [mattpocock/skills](https://github.com/mattpocock/skills) — evidence
before hypothesis, ranked falsifiable hypotheses, checkable completion criteria.

---

## 5. The agents

| Agent | Side | Job | Autonomy |
|-------|------|-----|----------|
| **Scout** (`scout_triage.py`) | REI | **FINDS + RANKS + ORGANIZES** every seller reply: scores motivation, buckets (asap/warm/nurture/dead), tags + pipeline, flags hot, weekly missed-leads audit. **Auto-hands call-worthy leads (asap/warm) to Marcus.** | Never texts. Tags/pipeline queued for approval. Self-improves. |
| **Marcus** (`marcus_screening.py`) | REI | **SCREENS** each interested / "not ready" seller → call-ready report (score, missing-info, red flags, call-prep, path-to-contract) + for not-ready a comfort/check-back draft in your voice. **Auto-screens what Scout flags.** Also the **seller text-back drafter** (`marcus_engine._ai_draft`): reads `Skills/seller-reply-playbook.md` + voice skills, tailors every reply to the seller's actual message, and **never puts a price/offer in a text — always pivots to a call** (code-enforced via `_no_price_over_text`). | Never closes/negotiates/quotes price by text. Every reply is a PROPOSAL you approve (gate stays on). You call; you one-tap send. Self-improves. Legacy SMS auto-responder OFF by default — `FORGE_MARCUS_SMS=1` to re-enable. |
| **Atlas** (`deal_prep.py`) | REI | **UNDERWRITES** every screened-interested seller: extracts facts from the thread, derives offer anchors (open/target/walkaway) from the SELLER'S stated ask, spells out the MAO math + what comps to pull, writes the negotiation call card. Auto-preps every 15 min. | Never contacts anyone. Prep numbers are INTERNAL — never sent to a seller. Reports to Marcus. |
| **Dyson** (`agency_agents.py`) | Agency | Plans/ships client website + code edits | Plan-only; nothing live until approved. Self-improves. |
| **Eco** (`agency_agents.py`) | Agency | Ads strategy / Meta analysis / concepts | Recommends only; launches on approval. Self-improves. |

Shared infra: `review_agent._claude` + `review_agent.MODEL` (Claude calls), `brain_io`
(vault read/write + git), `agent_bus.py` (inter-agent messages), key resolvers fall back
(agent's own key → wholesale `ghl.env` / agency `agency.env`).

**Agent comms + handoff:** one shared bus (`agent_bus.py`, `/api/bus`) carries messages
across BOTH workspaces. Scout → Marcus is now automatic: `SCOUT.on_scored` fires for every
call-worthy lead (asap/warm) → `SCREENER.screen` produces a screening report hands-free
(also the manual "Hand to Marcus" button + Telegram handoff now screen). Comms show in the
Command Center (REI) and the Agents → Comms tab (Agency).

---

## 6. The brain (Obsidian vault) — connected, synced, live across the whole dashboard

- One vault, both workspaces: **Brain tab** in REI and Agency (`window.BrainPage`).
- `brain_io.py` reads/writes the markdown directly; writes are **git-committed** (history +
  undo). `/api/brain/{tree,note,search,recent,graph,activity,status}`.
- Agents read their skills from it and write their learned playbooks back to it.
- Synced to the box by `deploy/push.sh` (rsync vault). Box vault: `/opt/forge/vault`.

---

## 7. Build / validate / deploy (non-negotiable mechanics)

**Static React, no build.** Components are `window` globals via `Object.assign(window,{...})`,
loaded as `<script type="text/babel" src="X.jsx">` in `FORGE REI OS.html` before `app.jsx`.

**Collision rules (a violation = white screen):**
- Every `.jsx` shares one global scope after Babel. Each file MUST use **unique hook
  aliases** (`useStateP`, `useStateAg`, `useStateAgt`, `useStateM`, `useStateD`, …) and
  **unique prefixed top-level names**.
- **No computed JSX tags** (`<Icons[x] />`). Resolve first: `const Ico = Icons[x] || Icons.Bot;` then `<Ico/>`.

**Backend pattern:** GET via `ROUTES` dict (+`NO_CACHE`); POST via the `do_POST` allowlist
tuple + `elif` dispatch. JSON stores mirror `agency_io.py` (threading.Lock, `_load`/`_save`,
state in `marcus_state/`).

**Validate before every deploy:**
- Python: `python3 -c "import ast; ast.parse(open('FILE').read())"`
- JSX: `node /tmp/valjsx.js FILE` (Babel transform + computed-tag scan)
- Then deploy (two paths, both validate + SSH-verify):

**Three deploy paths — same box, pick by what changed:**
1. **`git push origin main` (everyday, ANY machine — Mac or the gaming PC).** The box polls
   GitHub every 60s (`forge-autopull.timer` → `autopull.sh` → `deploy-pull.sh`) and
   self-deploys any new commit: `git reset --hard origin/main`, validate (py ast + jsx),
   rsync CODE into the live tree, restart, health-check. **Client needs only git** — no SSH
   key, no secrets, no rsync. This is what makes Mac + PC co-equal workspaces (repo is public
   `yahglizz/forge-rei-dash`). A commit that fails validation aborts the deploy (set -e) and
   the live version keeps running; the next good push recovers. Box clone: `/opt/forge/repo`;
   never touches secrets (`config/*.env`), vault, `marcus_state`, `uploads`. Watch it:
   `ssh box 'journalctl -u forge-autopull.service -f'`.
2. **`./deploy/quick-deploy.sh` (instant, needs `~/.ssh/forge_droplet`).** Same as above but
   SSHes the box to run `deploy-pull.sh` immediately instead of waiting ≤60s. Use when you
   want the deploy NOW.
3. **`./deploy/push.sh root@24.199.81.124` (Mac-only, full).** Use when a SECRET (`*.env`) or
   the brain VAULT changed — it rsyncs those Mac→box (they're gitignored, never in GitHub).
   Also mirrors code to GitHub. The original full-fat deploy.

Shared workspace discipline: edits sync via GIT, not magic. Edit on one machine →
quick-deploy (or `git push`); on the other machine `git pull` before you start. View live on
either at `https://forge-reios.tail0a2dda.ts.net` (Tailscale — no tunnel, bypasses DO
firewall).

**Box:** systemd `forge-reios`, `FORGE_MARCUS=1` (only the box runs the poll/triage loops —
the Mac runs `FORGE_MARCUS=0`, UI-only, so sellers aren't double-contacted).

---

## 8. Add or upgrade an agent — use the skill

Invoke the **`forge-self-improving-agent`** skill and follow its recipe (folder + key
resolver + mtime-cached brain skill load + `learn()` self-improvement + auto-trigger +
`agent_bus` + handoff + connector/console wiring + `deploy/push.sh`). After building,
update that skill if you improved the pattern.

---

## 9. Quick reference

- Local run (UI-only): `FORGE_MARCUS=0 FORGE_PORT=7799 python3 connector.py`
- Box: `ssh -i ~/.ssh/forge_droplet root@24.199.81.124` · `systemctl status forge-reios`
- Scout: `/api/scout/{summary,leads,overview,pipeline,run,apply,dismiss,pipeline,learn,handoff,audit,audit/run}`
- Missed-leads deep-audit (`scout_triage.retro_audit`): scans the last N days of FULL seller
  threads, surfaces leads with real signal we let go cold. Manual: "💎 Missed" tab in
  Conversations, "Weekly Sweep" card in the Command Center, or ask Scout in chat ("audit my
  messages from last week"). Auto: runs **once a week** on the box (`_maybe_weekly_audit` in
  Scout's loop) → brain note `Reports/missed-leads-<date>.md` + agent-bus alert. Read-only on
  GHL. Knobs: `FORGE_SCOUT_AUDIT_CANDIDATES`, `FORGE_SCOUT_AUDIT_PAGES`, `FORGE_SCOUT_AUDIT_MSGS`.
- Agency agents: `/api/agency/agents{,/history,/tasks,/chat,/task,/task/update,/learn}`
- Bus: `/api/bus` · Brain: `/api/brain/{tree,note,search,recent,graph,activity,status}`
- Telegram alerts + tap-to-approve (`telegram_io.py`): pings on hot lead / Marcus reply
  needing approval (warm+ only) / weekly missed sweep / handoffs+agency; inline buttons
  reuse Marcus's gated send + Scout handoff/dismiss. Tap **two-factor auth**: right chat AND
  allowed user id (`TELEGRAM_ALLOWED_IDS` — REQUIRED for a team group). Long-poll getUpdates
  (box-only, `FORGE_MARCUS` gate; no public port). Creds in git-ignored
  `forge-telegram/config/telegram.env`. API: `/api/notify/{settings,test}`. Bus tap =
  `agent_bus.register_notifier`. Settings card in the Command Center.
- **New-lead speed ping:** the first time Marcus ever proposes for a contact (tracked in
  `marcus_state/seen_contacts.jsonl`) the Telegram ping leads with **🆕 NEW LEAD — reply fast**
  so a fresh seller entering the funnel stands out from an ongoing thread. Re-engages never flag.
- **Daily brief + end-of-day recap** (run-from-anywhere Telegram pulses, box-scheduled):
  `daily_brief.py` (morning, `/api/brief{,/send,/config}`) and `daily_recap.py` (evening
  close-the-loops, `/api/recap{,/send,/config}`). Both gated by `forge_ops.paused()`, one send
  per day past the set hour (`FORGE_TZ_OFFSET` zone), heartbeat-monitored under `daily_brief`.
  Mobile control: More → Daily brief / End-of-day recap (toggle, hour, live preview, send-now).
- Knobs: `FORGE_SCOUT_*` (scout.env), `AGENCY_LEARN_EVERY`, `FORGE_VAULT`, `FORGE_MARCUS`.
- HOT-lead auto-pipeline: `FORGE_SCOUT_AUTOPIPE_HOT=1` (default on) — asap leads auto-land in the Wholesaling Pipeline Hot stage each poll (internal + reversible, same rationale as auto-tags).
- HOT-lead auto-tag: `FORGE_SCOUT_AUTOTAG_HOT=1` (default on). Scout pushes `triage: asap`+`motivated: high` to GHL for every `asap` lead each poll (`_autotag_hot`, runs even with no new leads → backlog covered). Set `=0` to revert to approval-gated tagging.

---

## 10. Daycare OS (the third workspace — full daycare operating system)

The **Daycare** workspace is the owner's management OS for "A Touch of Blessings"
(Supabase project `eqblpbeqothkpyqiafzs`). It is the **management lens**; the separate
Next.js app at `~/Desktop/the main daycare app` is the parent/staff lens. **Both are two
front-ends on ONE Supabase DB + schema** — the merge is at the data layer, not the code
(one compiles, one runs in-browser Babel). The Supabase migrations in
`forge-daycare/supabase/migrations/` and the app's `supabase/migrations/` are kept
**byte-identical = single source of truth** (verified against the live DB).

- **Opens straight in (no login).** On the box, a loopback (SSH-tunnel) request auto-mints
  an admin session so the console opens with no login screen. Gated by
  `FORGE_DAYCARE_AUTOADMIN=1` + `FORGE_DAYCARE_ALLOW_HTTP=1`, both **loopback-only** —
  tailnet/public clients still require real HTTPS + Login-ID/PIN. See
  `daycare_supabase.request_is_secure` / `autoadmin_session` and
  `connector._daycare_resolve_session`.
- **Ads + Social + Ideas (Growth tab).** `daycare_growth.py` reuses the agency
  `agency_ads`/`agency_social`/`agency_eco` engines with the daycare's OWN creds (locked
  env-swap; agency code untouched). Mock until `META_ACCESS_TOKEN` / `METRICOOL_USER_TOKEN`
  are added to `daycare.env`. Routes `/api/daycare/{ads,social,eco,eco/ideas}`.
- **Daycare agent context brief — READ FIRST.** Every daycare AI task loads
  `forge-daycare/skills/daycare-context.md` (business facts, mission = grow enrollment,
  current status, brand voice, standing job) BEFORE reasoning, via `daycare_context.py`
  (mtime hot-reload; `context_block()` injected into the Eco prompt ahead of the playbook).
- **Enrollment Ad Agent spec.** `forge-daycare/skills/enrollment-ad-agent.md` is the ad-ops
  runbook — the daycare's REAL Meta account (`act_1175564690150627`, page/lead-form IDs),
  the 3 live PAUSED angles (Urgency/Trust/Offer) with campaign+creative+image IDs, ad copy,
  Higgsfield image prompts + model table, targeting, and the Higgsfield→Pipeboard workflow.
  Loaded via `daycare_context.load_skill()` / `ad_agent_block()` and injected into the
  enrollment engine (`eco_ideas`) so ideas build on the actual running assets. **FORGE gate
  overrides its "execute immediately" line:** image/creative/paused-campaign builds run;
  activating campaigns, budget changes, and `scale winner` are one-tap owner approvals
  (spend). IDs there are business identifiers, not secrets — tokens stay in `daycare.env`.
  The "Ideas" tab (`daycare_growth.eco_ideas` → `/api/daycare/eco/ideas`) is the daycare's
  Eco agent: it reads the brief, drafts new enrollment angles + a competitor read, and
  returns PROPOSALS (launching an ad stays approval-gated). Eco's `extra_context` param is
  ""/no-op for the agency, so agency output is unchanged. Owner keeps the brief current by
  editing that markdown — agents pick it up on the next run. When adding any new daycare AI
  surface, inject `daycare_context.context_block()` FIRST.
- **Stripe invoicing.** `stripe_io.py` (stdlib) sends hosted invoices + syncs payments back
  via the `record_invoice_payment` RPC (`provider='stripe'`). Needs a secret-class
  `STRIPE_SECRET_KEY` in `daycare.env` — `sk_live_…`/`sk_test_…` (full) or `rk_live_…`
  (restricted, needs Customers + Invoices write). A `pk_…` publishable key is rejected by
  Stripe. Blank = "add key" hint, nothing charged. Routes
  `/api/daycare/stripe/{send-invoice,sync-payment,status}`. Billing UI: "Send via Stripe" /
  "Sync".
- **GHL family messaging.** `DAYCARE_GHL` = own `GHLClient` from `daycare.env`
  (`GHL_API_KEY`/`GHL_LOCATION_ID`, separate from wholesale+agency). `daycare_ghl.py`
  texts families their payment link. **Owner-initiated only** (the "Text" button IS the
  approval gate — never autonomous). Routes `/api/daycare/ghl/{health,text-invoice}`.
- **Secrets + flags** all live in `forge-daycare/config/daycare.env` (git-ignored, 404 over
  HTTP, chmod 600, shipped by `push.sh`). Design spec:
  `docs/superpowers/specs/2026-07-13-daycare-os-design.md`.
- **Solomon — the daycare HEAD agent (executive director).** `daycare_director.py`
  (`SolomonEngine`) is the first daycare agent and the head of all daycare agents: a
  **50-year** childcare director. He reads the whole center (Supabase ops metrics + alerts,
  billing, staffing, connected-systems health, the `daycare-context.md` brief FIRST),
  produces a ranked **operating brief** (Attention Now / Enrollment / Money / People /
  Delegations), **owns enrollment**, and **delegates** to role sub-agents via `agent_bus`
  (hand-off per role). Same self-improving-agent pattern as Scout: own env folder
  `forge-solomon/` (config + seed `skills/`), key fallback (own →
  shared agency/wholesale), mtime-cached brain skills, `learn()` self-improvement into
  `<vault>/Skills/solomon-playbook.md`, background loop gated by `FORGE_MARCUS` (box only,
  brief every `FORGE_SOLOMON_BRIEF_EVERY_H`h + auto self-improve). Read-only + propose/
  delegate — he never texts, invoices, launches ads, or writes the DB; his only autonomous
  writes are his playbook + bus notes. Console: the **Solomon · Director** tab (daycare
  workspace). Routes `/api/daycare/director/{status,overview,brief,run,learn,bus}`. His
  "access to the env files" = reading which systems are **wired** (presence only, never
  the secret value) via `connected_systems()`. Add role agents under him with the same
  `forge-self-improving-agent` recipe; they consume his bus delegations.
  - **His skills (see §4a — top skills outrank the playbook).** Constitution:
    `agent-evidence-discipline` (house rule, all agents) → `solomon-decision-loop` (never
    guess; ground/infer/**Unknown**; ranked falsifiable hypotheses; **close the loop** and
    decide — unknowns never block the brief) → `solomon-director-craft` (the 50 years:
    triage order, funnel-leak vs. lead-volume, speed-to-lead, retention math, discount
    last). Then the learned `solomon-playbook`. `_load_skills()` loads the constitution
    whole and FIRST; `_playbook_only()` feeds `learn()` so self-improvement can never
    rewrite the constitution. The brief prompt carries the same evidence rule inline as a
    backstop, so it holds even if the skill files fail to load.
- **Autonomy rule holds:** every outward daycare action (SMS, invoice send, ad launch,
  social post) stays approval-gated per rule 2. Auto-admin is loopback-only convenience.
