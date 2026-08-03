# FORGE REI OS — Operating Manual (CLAUDE.md)

**Read `NORTH_STAR.md` first** — the cross-business constitution (mission, identity,
tone per business, and the authoritative brains/skills/env map). This file is the
day-to-day operating manual underneath it: HOW to build, not WHY or WHAT tone to use.

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

A real-estate-wholesaling + AI-agency + daycare control center. Static React UI (React
UMD + in-browser Babel, **no build step**) served by a Python stdlib connector
(`connector.py`, port 7799) that mirrors GoHighLevel and runs the AI agents. Lives 24/7
on a DigitalOcean box. Three workspaces (profile switcher):

- **REI (wholesale):** Dashboard, Leads, Conversations, Pipeline, Agents, Brain, etc.
- **Agency (ClientForge):** Clients, Edit Requests, Agents, Ads, Social, Approvals, Brain.
- **Daycare:** Dashboard, Solomon, Children, Billing, Growth, Brain, etc. (§10)
- **Dropship (FORGE Dropship):** Dashboard, Agents (Midas), Products,
  Orders, Inventory, Suppliers, Ads & Creative, Customers, Analytics, Brain, Settings.
  Shopify + AutoDS + Meta store. Folder `forge-dropship/`; engines `dropship_director.py`
  (Midas, all three lanes); integration clients
  `dropship_shopify.py` / `dropship_autods.py`; routes `/api/dropship/*`. Same
  propose→approve discipline — every ad launch, supplier order, listing edit, and
  customer message stays one-tap gated.

Folders (siblings under `forge rei dash/`, secrets stay OUTSIDE the web root):
- `forge rei/` — the app (this folder): all `.py` engines + `.jsx` UI + `deploy/`.
- `forge-agency/`, `forge-scout/`, `forge-marcus/`, `forge-solomon/`,
  `forge-daycare/`, `forge-telegram/`, `forge-dropship/` — each business/agent's own config
  + seed skills, outside the web root. **Full map (every folder, every agent, every env
  var) → `NORTH_STAR.md` §6-7 — that table is the authoritative one now; this list is
  just the orientation.**
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

### 4a. THE CREED — evidence discipline, one per business (outranks every playbook)

Every agent runs on a **creed**: the evidence discipline for the business it works in,
written in that business's own language. The creed is **human-owned, stable, and ranked
ABOVE the learned playbook** — when they disagree, **the creed wins**.

**One creed per business** (`agent_creed.py`, `CREED_FILE`):

| Creed | Agents | Home | What it enforces |
|-------|--------|------|------------------|
| **`wholesale-evidence-discipline`** | **Scout, Marcus, Atlas** | `forge-scout/skills/` + `forge-marcus/skills/` | The thread is the only truth — never invent what a seller said, asked, or agreed to; **no agent ever invents a number**, and no price/offer ever goes out by text (Atlas's anchors are internal); Unknowns become the call's missing-info list; reply to sellers only, never to our own outreach. |
| **`agency-evidence-discipline`** | **Dyson, Eco** | `forge-agency/skills/` | Never invent a client's metric — every CPL/ROAS/spend figure carries its source **and date range**, or is Unknown; mock/unconnected channels are labeled as such in the output; never invent or stretch a client request, timeline, or promised result; diagnose with ranked alternatives, not "it's the creative." |
| **`daycare-evidence-discipline`** | **Solomon** + role agents (Enrollment, Billing, Family-Comms, Staffing, Compliance) | `forge-solomon/skills/` | Never invent capacity, a start date, a rate, a balance, or a ratio; read the brief FIRST; safety/compliance outranks the analysis; look it up, escalate only the decisions. |
| **`dropship-evidence-discipline`** | **Midas** (all three lanes) | `forge-dropship/skills/` | Never invent a metric, a margin, a stock status, a supplier price, or a delivery time — every number carries its source **and window**, or is Unknown; margin only from real cost inputs (revenue is not profit); a "winner" needs real sales + ad signal, never a hunch; **account health (merchant + ad account) outranks the analysis**; propose, never launch/spend/order/message. |

**All four share the spine:** *ground it, infer it, or name it **Unknown*** · 3–5 **ranked
falsifiable** hypotheses (never anchor on the first story) · **close the loop** — if the
next lookup wouldn't change the recommendation, decide · **two passes max**, Unknowns never
block the output · weight care by cost of being wrong · **propose, never act outward.**

**Why `agent_creed.py` is a module and not another entry in `_load_skills()` — this is
load-bearing.** Every agent's `learn()` does `current = self._load_skills()` → *"output the
FULL UPDATED playbook"* → overwrite. **Anything reachable through `_load_skills` is
something self-improvement will eventually swallow and rewrite.** So the creed is injected
straight into each system prompt (`agent_creed.block(business)`), never through
`_load_skills` — `learn()` cannot see it, so it can never rewrite it. A self-rewriting
constitution is no constitution. Vault copy wins over seed (edit it in Obsidian, agents
mtime-reload next run). ~1.5–1.8k tokens per call, never truncated — deliberate.

Solomon additionally carries two **top skills** above his playbook (loaded by
`_load_skills`, isolated from `learn()` via `_playbook_only`):

| Top skill | What it enforces |
|-----------|------------------|
| **`solomon-decision-loop`** | Frame → Ground → Hypothesize → Decide → **Close**. The exit condition that kills analysis paralysis. |
| **`solomon-director-craft`** | The 50 years: triage order (safety/ratio → compliance → cash → enrollment), funnel-leak vs. lead-volume, speed-to-lead, vacancy as a spoiled good, retention math, discount last. |

Midas carries eleven skills above his playbook, all isolated from `learn()` via
`_playbook_only`. Unlike Solomon's flat set, Midas's are **lane-gated** — see below.

**Always on** (`MidasEngine.TOP_SKILLS`, in every prompt including the scheduled brief):

| Top skill | What it enforces |
|-----------|------------------|
| **`midas-decision-loop`** | How he reasons — ground every claim, rank falsifiable hypotheses, **close the loop** while the ad account is still spending. |
| **`midas-craft`** | The operating judgment: triage order (account health → fulfillment → margin → winners → testing), the funnel leaks at the seams not the source, creative IS the targeting, a stockout on a winner is a spoiled good, discount last. |
| **`dropship-account-health`** | Chargeback/refund danger bands, reserve triggers, the Meta restriction runbook, hard-stop categories. Always on because the creed ranks account health above the analysis. |

**Lane-gated** (`MidasEngine.LANE_SKILLS`, loaded only by the lane that consults them —
`_load_skills(lane)`, where `lane` is the string `analyze()` already carries):

| Lane | Skills added |
|------|--------------|
| `product research` | `dropship-adspy-method` |
| `creative & ads` | `dropship-four-triggers-ad-writer`, `dropship-creative-testing-doctrine`, `dropship-account-optimization-doctrine`, `dropship-meta-ads-diagnostician`, `dropship-ad-launch-sop`, `dropship-adspy-method` |
| `fulfillment & support` | `dropship-support-macros` |

**On demand** (`ON_DEMAND_SKILLS`): `dropship-store-setup` — one-time build guidance
(theme, offer/AOV, **pixel + CAPI**), reachable to the operator in chat, never worth a
scheduled tick.

**Why gated, and don't undo it.** These SOPs are ~13–15KB each. Declaring all eleven as
always-on costs **~24k tokens on every call**; the daily brief runs unattended forever, so
that is a recurring bill for pages that call never reads. Gated, the brief carries ~12.5k
and each lane gets exactly its own. **Operator chat is deliberately NOT gated** —
`top_skills_text()` loads all nine, because a human question is bursty, cache-warm, and
can be about any lane.

**Enforcement:** `forge rei/test_dropship_skills.py` fails if any skill file is on disk but
unreachable from every prompt path, if the creed leaks into `_load_skills`, or if a top
skill lands in `learn()`'s budget. Run it after touching any skill:
`cd "forge rei" && python3 test_dropship_skills.py` (exit 1 on failure).

**Adding an agent:** give it the creed for its business — `agent_creed.block("<business>")`
into its system prompt ahead of the playbook — and keep `learn()` pointed at the playbook
alone. A new business gets a new creed file + a `CREED_FILE` entry.
Pattern credit: [mattpocock/skills](https://github.com/mattpocock/skills) — evidence before
hypothesis, ranked falsifiable hypotheses, checkable completion criteria.

---

## 5. The agents

**Seven agents, on purpose.** 2026-07-25 audit: the daycare ran a director + two role
agents that were ~85% the same class re-reading the same tables on separate loops, and
dropship ran a director + three specialists for a store that isn't live. Nora, Nova, Hawk,
Blaze and Otto were retired — their skills merged into Solomon's and Midas's top skills +
playbooks, their data reads became director methods, their routes became lane views onto
the director's brief. **Before adding an agent, ask whether a section of an existing
agent's brief does the job.** A new agent is a new playbook to drift, a new loop to run,
and a new Claude call per cycle.

| Agent | Side | Job | Autonomy |
|-------|------|-----|----------|
| **Scout** (`scout_triage.py`) | REI | **FINDS + RANKS + ORGANIZES** every seller reply: scores motivation, buckets (asap/warm/nurture/dead), tags + pipeline, flags hot, weekly missed-leads audit. **Auto-hands call-worthy leads (asap/warm) to Marcus.** | Never texts. Tags/pipeline queued for approval. Self-improves. |
| **Marcus** (`marcus_screening.py`) | REI | **SCREENS** each interested / "not ready" seller → call-ready report (score, missing-info, red flags, call-prep, path-to-contract) + for not-ready a comfort/check-back draft in your voice. **Auto-screens what Scout flags.** Also the **seller text-back drafter** (`marcus_engine._ai_draft`): reads `Skills/seller-reply-playbook.md` + voice skills, tailors every reply to the seller's actual message, and **never puts a price/offer in a text — always pivots to a call** (code-enforced via `_no_price_over_text`). | Never closes/negotiates/quotes price by text. Every reply is a PROPOSAL you approve (gate stays on). You call; you one-tap send. Self-improves. Legacy SMS auto-responder OFF by default — `FORGE_MARCUS_SMS=1` to re-enable. |
| **Atlas** (`deal_prep.py`) | REI | **UNDERWRITES** every screened-interested seller: extracts facts from the thread, derives offer anchors (open/target/walkaway) from the SELLER'S stated ask, spells out the MAO math + what comps to pull, writes the negotiation call card. Auto-preps every 15 min. | Never contacts anyone. Prep numbers are INTERNAL — never sent to a seller. Reports to Marcus. |
| **Dyson** (`agency_agents.py`) | Agency | Plans/ships client website + code edits | Plan-only; nothing live until approved. Self-improves. |
| **Eco** (`agency_agents.py`) | Agency | Ads strategy / Meta analysis / concepts | Recommends only; launches on approval. Self-improves. |
| **Solomon** (`daycare_director.py`) | Daycare | **Runs the whole center.** One ranked operating brief: ops, enrollment, money, people, **roster + family follow-ups** (was Nora), **campaign health + competitor read + creative direction** (was Nova). Owns enrollment. See §10. | Never texts/invoices/launches ads/writes the DB. Proposes only. Self-improves. |
| **Midas** (`dropship_director.py`) | Dropship | **HEAD e-com director — runs the whole store.** Reads it all (Shopify + AutoDS + Meta + the brief FIRST) → ranked operating brief (Attention Now / Winners / Money / Ops / Ads / Delegations), plus three on-demand lanes: **product research** (`research`, `watch_score`), **creative & ads** (`meta_overview`, `analyze_ads` — agency Meta engine via a locked env-swap), **fulfillment & support** (`fulfillment_check`). | Never acts outward — no launch, budget change, supplier order, listing edit, customer message, or refund. Proposes only. Self-improves. |

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
- Agency Call Center (`agency_calls.py` + `agency_callcenter.jsx`): tap-to-log dial tracker — Answered/No-Answer buttons, daily log, editable dial goal, streak (consecutive days ≥ goal; in-progress today never breaks it). `/api/agency/calls{,/log,/undo,/goal}`, state `marcus_state/agency_calls.json`. Internal tally only — no approval gate.
- Agency Call Sheet (`agency_callsheet.py`, same tab): upload a PDF of biz leads (or paste text) → Claude parses to rows (`review_agent._claude`; regex fallback, pypdf/PyPDF2/pdftotext extraction chain — box has pypdf) → CRM-style table with search + status chips; per-row quick-marks New/Answered/No answer/Call back/Move on, tap-to-dial `tel:` links, inline notes, phone-dedupe on import. Marking answered/no_answer auto-bumps the daily tally. `/api/agency/callsheet{,/import-pdf,/import-text,/status,/note,/delete,/clear-dead}`, state `marcus_state/agency_callsheet.json`.
- Bus: `/api/bus` · Brain: `/api/brain/{tree,note,search,recent,graph,activity,status}`
- **`./forge` — call any agent from any shell (the 4th surface, next to dashboard /
  Telegram / Agent Office).** One bash script at the repo root; no new backend — it POSTs
  the same `/api/hub/{chat,task}` the dashboard uses, so the conversation thread, the hub
  task queue, and the agent bus stay shared across every surface. Install once:
  `ln -sf "$HOME/forge rei dash/forge" ~/.local/bin/forge`. Then from Mac, the PC, an SSH
  session, a cron job, or a Claude Code Bash call:

  | Command | What it does |
  |---------|--------------|
  | `forge scout what's hot today` | ask that agent (`marcus scout atlas dyson eco solomon midas`) |
  | `forge task midas check inventory` | file a REAL job — hub task + bus message the agent reads |
  | `forge agents` / `forge tasks [agent]` / `forge bus [agent]` | roster+status · task queue · bus feed |
  | `echo "..." \| forge marcus` | message from stdin (long text, files, pipes) |
  | `forge --json <cmd>` | raw JSON, for scripting |

  Box URL resolves `$FORGE_URL` → tailnet (`https://forge-reios.tail0a2dda.ts.net`) →
  `localhost:7799`. No API token because the network IS the perimeter (DO firewall blocks
  public; tailnet or SSH tunnel only) — **do not expose 7799 publicly without adding auth
  first.** Phone without Telegram: an iOS Shortcut doing
  `POST $TAILNET/api/hub/chat {"agentId":"scout","message":"..."}` over Tailscale is the
  same call. Rule 2 holds — chat is thinking, `task` is an assignment, neither acts outward.
  Self-check: `./test_forge_cli.sh` (stub box on 127.0.0.1, 12 assertions, exit 1 on failure).
- **Agent Office** (`pixel_office.py` + `pixel_office.jsx`, nav "Agent Office" in all four
  workspaces): the visual floor — four department rooms, twelve agents as pixel characters,
  animated from REAL signals only (live job → agent_bus → open hub tasks → engine status;
  an agent we can't reach reads "unknown", never "idle"). Clicking a character opens its
  status + live step log + a task box. Sending a task files it via `agents_hub.send_task`
  AND runs that agent's real brain in a background thread (`agents_hub.chat` for the eight
  hub agents; `analyze`/`build_brief` for the dropship four), then posts the result on the
  bus and closes the task. Rule 2 holds — the run is THINKING, never an outward action.
  Routes `/api/office/{state,job,jobs}` (GET) + `/api/office/task` (POST). Self-check:
  `python3 pixel_office.py`. Idea borrowed from github.com/pixel-agents-hq/pixel-agents;
  rebuilt on this stack (their Vite/React-19/Fastify/VS-Code build can't drop into a
  buildless UMD dashboard) with procedurally drawn characters, so no third-party sprite
  art ships in this public repo.

- Telegram alerts + tap-to-approve (`telegram_io.py`): pings on hot lead / Marcus reply
  needing approval (warm+ only) / weekly missed sweep / handoffs+agency; inline buttons
  reuse Marcus's gated send + Scout handoff/dismiss. Tap **two-factor auth**: right chat AND
  allowed user id (`TELEGRAM_ALLOWED_IDS` — REQUIRED for a team group). Long-poll getUpdates
  (box-only, `FORGE_MARCUS` gate; no public port). Creds in git-ignored
  `forge-telegram/config/telegram.env`. API: `/api/notify/{settings,test}`. Bus tap =
  `agent_bus.register_notifier`. Settings card in the Command Center.
- **Trigger words + real task dispatch (Telegram).** Say an agent's NAME as the first word
  followed by `,` `:` or a spaced dash — "solomon, what's the ratio situation" / "midas:
  which product is winning" — and the message routes to that agent (same as `/solomon`,
  `/midas`, `/scout`, …; all 7 now have slash commands + a `/` menu slot). A bare name with
  no separator ("I told marcus to call") stays plain chat, so ordinary sentences don't
  hijack the session. `/task <what you need>` no longer just chats: it files a REAL job via
  `agents_hub.send_task` → hub task store + `agent_bus` message to that agent, and the
  agent SEES it — every chat prompt now injects `agents_hub.open_tasks_block(agent_id)`
  (`agents_chat._tasks`, `marcus_chat._hub_tasks`, `agency_agents`, `_director_chat`), and
  Midas reads his bus inbox into the brief (`_read_bus_inbox`, same as Solomon). Filing a
  task is an ASSIGNMENT, never an outward action — rule 2 unchanged. Self-check:
  `python3 test_triggers_cost.py`.
- **Per-agent API cost.** `cost_tracker` buckets every Claude call by
  `threading.current_thread().name`; `connector` names each loop thread (`scout`, `marcus`,
  `atlas`, `followup`, `solomon`, `midas`, `do_today`, `telegram`, `brief`, `graphify`), so
  attribution needed zero changes at the 47 `_claude()` call sites. Anything on an HTTP
  handler thread (chat, a brief button, the UI) buckets under `operator`.
  `/api/cost/status` → `mtd.byAgent` = `[{agent, usd, calls, projMonthUSD}]`, biggest first.
- **New-lead speed ping:** the first time Marcus ever proposes for a contact (tracked in
  `marcus_state/seen_contacts.jsonl`) the Telegram ping leads with **🆕 NEW LEAD — reply fast**
  so a fresh seller entering the funnel stands out from an ongoing thread. Re-engages never flag.
- **Daily brief + end-of-day recap** (run-from-anywhere Telegram pulses, box-scheduled):
  `daily_brief.py` (morning, `/api/brief{,/send,/config}`) and `daily_recap.py` (evening
  close-the-loops, `/api/recap{,/send,/config}`). Both gated by `forge_ops.paused()`, one send
  per day past the set hour (`FORGE_TZ_OFFSET` zone), heartbeat-monitored under `daily_brief`.
  Mobile control: More → Daily brief / End-of-day recap (toggle, hour, live preview, send-now).
- Knobs: `FORGE_SCOUT_*` (scout.env), `AGENCY_LEARN_EVERY`, `FORGE_VAULT`, `FORGE_MARCUS`.
- **Loop switchboard (2026-07-26) — tune spend without a deploy.** Box loop knobs live in
  `/etc/default/forge-reios` (box-only, holds secrets — `grep` it for a var name, never
  `cat` it). Edit + `systemctl restart forge-reios`; no push, no code edit.

  | Knob | Default | What it does |
  |------|---------|--------------|
  | `FORGE_DROPSHIP_BRIEF` | **0 (off)** | Midas's scheduled brief. Off while the store has 0/7 systems wired — a brief over empty data is fabrication AND a daily bill. On-demand (chat, `/task`, `/api/dropship/director/run`, all 3 lanes) is unaffected. Set `1` when Shopify connects. |
  | `FORGE_TODAY_LOOP` | **0 (off)** | DoToday's scheduled rebuild + 9 AM email. Paused by operator request. Costs $0 either way (DoToday makes no Claude call); `view()` self-rebuilds so `/today` + `/done` still work. |
  | `FORGE_SCOUT_INTERVAL` | 180 | Wholesale sweep. The money loop — leave hot. |
  | `FORGE_SOLOMON_BRIEF_EVERY_H` | 24 | Daycare brief. Raise to 48 if enrollment goes quiet. |
  | `FORGE_SCOUT_LEARN_EVERY` / `FORGE_ATLAS_LEARN_EVERY` | 25 / 12 | Self-improve cadence — the other real Claude cost. |

  **Switching a loop OFF must call `forge_heartbeat.retire("<loop>")`** in the else branch,
  or it stops beating, goes red forever, and trips the health card + watchdog. Which agents
  actually cost money: `daily_brief`, `daily_recap`, `do_today`, `followup` make **zero**
  Claude calls — pausing them saves nothing. Spend is Scout, Marcus, Atlas, Solomon, Midas,
  `skill_forge`, `style_agent`, and your chats. Per-agent truth: `/api/cost/status` →
  `mtd.byAgent`, rendered on the Costs tab ("Spend by agent").
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
- **Contact-Form auto-enroll.** Every enrolled Contact-Form submission is auto-enrolled
  into the Supabase roster the moment the Parent Logins inbox loads it
  (`connector._daycare_pending_families` → `_daycare_family_child_body` →
  `daycare_supabase.save_child`, no guardian block = no login). Internal + reversible
  (a deletable child row), same rule-2 class as HOT-lead auto-tag. Idempotent via a
  contact→child ledger `marcus_state/daycare_form_children.json`
  (`daycare_ghl.form_child_id`/`record_form_child`); name-based dedupe
  (`daycare_supabase.find_child_id`) adopts an already-enrolled kid instead of
  duplicating, first-name-only submissions fall back to the family surname. The parent
  **login** stays button-gated — owner's Create-login (`/api/daycare/ghl/enroll`) now
  passes the ledgered child id so `save_child` UPDATES the row and provisions the
  guardian (Login ID + one-time PIN) on that update path. Kill switch
  `FORGE_DAYCARE_AUTOENROLL=0` (default on).
- **Secrets + flags** all live in `forge-daycare/config/daycare.env` (git-ignored, 404 over
  HTTP, chmod 600, shipped by `push.sh`). Design spec:
  `docs/superpowers/specs/2026-07-13-daycare-os-design.md`.
- **Solomon — the daycare's ONE agent (executive director).** `daycare_director.py`
  (`SolomonEngine`) is a **50-year** childcare director who runs the whole center. He reads
  it all (Supabase ops metrics + alerts, roster/classrooms, the blast log, Meta campaign
  health + competitor read, billing, staffing, connected-systems health, the
  `daycare-context.md` brief FIRST) and produces ONE ranked **operating brief** (Attention
  Now / Enrollment / Money / People / **Roster** / **Follow-ups** / **Campaign health** /
  **Creative** / Delegations). He **owns enrollment** and **delegates** via `agent_bus`
  only what genuinely needs a human. Nora (roster/family-comms) and Nova (ad ops) were
  merged into him on 2026-07-25 — their rubrics are his `solomon-roster-craft` /
  `solomon-adops-craft` top skills, their routes (`/api/daycare/{family,adops}/*`) now
  narrow his brief via `roster_view()`/`adops_view()`. One brief, one Claude call, one
  auto-admin session instead of three of each. Same self-improving-agent pattern as Scout: own env folder
  `forge-solomon/` (config + seed `skills/`), key fallback (own →
  shared agency/wholesale), mtime-cached brain skills, `learn()` self-improvement into
  `<vault>/Skills/solomon-playbook.md`, background loop gated by `FORGE_MARCUS` (box only,
  brief every `FORGE_SOLOMON_BRIEF_EVERY_H`h + auto self-improve). Read-only + propose/
  delegate — he never texts, invoices, launches ads, or writes the DB; his only autonomous
  writes are his playbook + bus notes. Console: the **Solomon · Director** tab (daycare
  workspace). Routes `/api/daycare/director/{status,overview,brief,run,learn,bus}`. His
  "access to the env files" = reading which systems are **wired** (presence only, never
  the secret value) via `connected_systems()`. He answers to every bus role he absorbed
  (`BUS_ROLES` = solomon · family-comms · enrollment · ads · growth · nora · nova), so a
  delegation addressed to any of them still lands. **Before adding a role agent under him,
  ask whether a new brief section would do the job** — that is what the 2026-07-25
  consolidation concluded for the last two.
  - **His skills (see §4a — creed + top skills outrank the playbook).** Prompt order:
    `daycare-evidence-discipline` (the **creed**, via `agent_creed.block("daycare")` —
    never guess capacity/start date/rate/ratio; ground/infer/**Unknown**) →
    `solomon-decision-loop` (ranked falsifiable hypotheses; **close the loop** and decide —
    unknowns never block the brief) → `solomon-director-craft` (the 50 years: triage order,
    funnel-leak vs. lead-volume, speed-to-lead, retention math, discount last) →
    `solomon-roster-craft` (ratio/safety gaps before follow-ups; ground every family
    follow-up in the blast log) → `solomon-adops-craft` (account mismatch is a hard stop;
    refresh before new angles; PAUSED always) → the learned `solomon-playbook` last. The creed comes from `agent_creed` (invisible to
    `learn()`); the top skills come from `_load_skills()` while `_playbook_only()` feeds
    `learn()` — so self-improvement can rewrite the playbook and nothing above it. The
    brief prompt also carries the evidence rule inline as a backstop, so it holds even if
    every skill file fails to load.
- **Autonomy rule holds:** every outward daycare action (SMS, invoice send, ad launch,
  social post) stays approval-gated per rule 2. Auto-admin is loopback-only convenience.

---

## 11. Cross-Agent Coaching Network (all 7 agents coach each other, across all four businesses)

Every agent is a node in a **coaching network**: they can **ASK peers questions**,
**LEARN from answers**, and **BROADCAST a transferable insight** (a creative angle that's
converting, a screening tactic, a pricing-conversation move) to a peer, a business, or
`"all"`. Peer insights addressed to an agent are **automatically folded into its next
`learn()` self-improvement cycle** — so a lesson discovered in one business becomes a
default in another. Coaching flows both ways and across all four businesses.

*Example:* Eco (agency ads) sees a carousel angle beating single-image for a client and
coaches Solomon (who owns the daycare's ads); he adapts it to enrollment ads. Scout's
screening tell can sharpen Marcus; Solomon's retention math can inform how Midas frames
an offer.

- **Module:** `forge rei/agent_coach.py` — stdlib, connector-free. `broadcast()`,
  `insights_for()`, `insights_block()`, `ask()`, `feed()`.
- **Wired into every agent's `learn()`:** each reflection prompt appends
  `agent_coach.insights_block("<agent>", "<business>")` (guarded by try/except, returns
  `""` when nothing is addressed → zero behavior change when the feed is empty).
- **Source of truth:** vault `Coaching/feed.md` (human-readable, git-committed via
  `brain_io`), mirrored on the agent bus (`kind=="coach"`). Surface + manual coaching:
  the **Agent Network** tab; routes `/api/coach/{feed,ask,broadcast}`.
- **The one invariant:** coaching moves **INSIGHTS ONLY** — plain text. It **never** moves
  a credential, token, GHL client object, or location id (the 3 GHL sub-accounts stay
  byte-for-byte isolated), and it **never** carries an instruction to take an outward
  action. A secret-guard in `broadcast()` drops anything that looks like a live key.
- **Autonomy:** insight-sharing + absorption is **autonomous, internal, reversible, and
  git-committed** — the same class as the existing `learn()` self-improve loop, so it's
  **rule-2 compliant**. Every outward action (texts, ad launches, invoices, spend, posts)
  stays tap-gated exactly as before.

---

## 12. CAVEMAN — the house answer style (default ON, every response)

**Caveman is the standing communication mode for this whole system** — Claude's replies AND
the in-app agents' operator-facing text. Skill: **https://github.com/JuliusBrussee/caveman**
(installed; skill files under `forge rei/.agents/skills/caveman*`). Terse "smart caveman":
cut filler ~65%, keep 100% of the substance.

**The rule (applies to EVERY response + output):** lead with the answer, no preamble / no
"great question" / no restating the ask / no sign-off. Terse bullet fragments over full
sentences. Drop articles + filler. One line when one line does it. Keep every fact, name,
number, and the reasoning that changes the decision — **short, never wrong.**

**Commands (Claude Code, my sessions):**
- `/caveman [lite|full|ultra]` — set intensity (default **full**). `/caveman-stats` — token
  savings. `/caveman-commit` — terse commit msg. `/caveman-review` — one-line PR notes.
  `/caveman-compress <file>` — shrink a memory/context file permanently. Say **"stop caveman"**
  / **"normal mode"** to revert.

**BOUNDARIES — write NORMAL (clear, full) prose, caveman OFF, for:**
- Security warnings, irreversible-action confirmations, and any multi-step sequence where
  dropping words risks misread (the skill's own Auto-Clarity rule — obey it).
- **Code, commits, PRs, commands, API names, exact error strings** — verbatim, never abbreviated.
- Real caveats and Unknowns — evidence discipline / the creed outrank brevity. Be short, not wrong.

**Agent side (already wired — `forge rei/caveman.py`):** `caveman.block(level)` is appended
to operator-facing chat prompts ONLY — Scout/Atlas (`agents_chat`), Solomon
(`agents_hub`), Dyson/Eco (`agency_agents`), Marcus screening chat (`marcus_chat`). It is
**NEVER** on seller-facing SMS drafts (`marcus_engine._ai_draft` — voice-critical), internal
scoring/underwriting, briefs, or the creed. Intensity: `FORGE_CAVEMAN_LEVEL=lite|full|ultra`;
kill switch: `FORGE_CAVEMAN=0`. When adding any new operator-facing AI chat surface, append
`caveman.block()` LAST (after the creed/context) — never on an outward-message or structured
(JSON) generator.
