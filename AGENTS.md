# FORGE REI OS — Operating Manual (AGENTS.md)

**Read `NORTH_STAR.md` first** — the cross-business constitution (mission, identity,
tone per business, and the authoritative brains/skills/env map). This file is the
day-to-day operating manual underneath it. Note: this file currently lags `CLAUDE.md`
(e.g. it predates the Daycare workspace/Solomon/Nora/Nova) — treat `CLAUDE.md` as the
more current sibling until this file gets its own reconciliation pass.

This file governs how Codex (and the in-app AI agents) work on FORGE REI OS. Read it
before making changes. The **RULES** and **DAILY SELF-IMPROVEMENT** sections are yours
to edit — change them and everything downstream follows.

---

## 1. What this is

A real-estate-wholesaling + AI-agency + daycare control center. Static React UI (React UMD +
in-browser Babel, **no build step**) served by a Python stdlib connector
(`connector.py`, port 7799) that mirrors GoHighLevel and runs the AI agents. Lives 24/7
on a DigitalOcean box. Three workspaces (profile switcher):

- **REI (wholesale):** Dashboard, Leads, Conversations, Pipeline, Agents, Brain, etc.
- **Agency (ClientForge):** Clients, Edit Requests, Agents, Ads, Social, Approvals, Brain.
- **Daycare:** Children, Attendance, Classrooms, Staff, Enrollment, Billing, Meals, Calendar, Reports, Brain.

Folders (siblings under `forge rei dash/`, secrets stay OUTSIDE the web root):
- `forge rei/` — the app (this folder): all `.py` engines + `.jsx` UI + `deploy/`.
- `forge-agency/` — agency config (`config/agency.env`) + agent skills (`skills/`).
- `forge-scout/` — Scout config (`config/scout.env`) + seed skills (`skills/`).
- `~/Desktop/Agentic-OS/vault/` — the Obsidian **brain** (FORGE_VAULT; `/opt/forge/vault` on the box).

---

## 2. RULES (edit me — these are the standing rules I apply)

> Plain-English rules. Edit freely; they are the contract for every change.

1. **Auto-deploy.** After ANY edit, push to the 24/7 box: `./deploy/push.sh root@24.199.81.124`, then SSH-verify (service `active`, endpoints 200, secrets 404). Never leave changes local-only. Validate first — never push a broken state.
2. **Propose → review → execute.** Agents never take irreversible or outward actions on their own. Texting sellers, posting socials, applying GHL tags, moving pipeline, launching ads — all gated behind my one-click approval. The ONLY things agents do autonomously are: score/triage, read the brain, write their own learned playbook to the brain, and post notes on the agent bus.
3. **Marcus owns texting.** Scout ranks + tags + hands off; it never sends SMS. Same spirit for every agent: one agent per outward channel.
4. **Reply to sellers only — never to our own messages.** Agents never draft a reply to OUR outreach/opener/blast (e.g. "we buy houses", "I was calling about…", "just following up"). Only genuine inbound seller messages get a draft. GHL sometimes mis-flags our own text as inbound; the `_is_our_message()` filter in `marcus_engine.py` (`_OUR_OUTREACH_PHRASES`) skips it. Edit that list to match your scripts.
4. **Secrets stay private.** API keys live in `*.env` files OUTSIDE the web-served folder, git-ignored. Never served over HTTP (must 404). Never paste keys in chat. Don't rotate keys unless I say so.
5. **Don't break what works.** Additive edits. Don't remove existing features/code. Validate before deploy.
6. **Decide, don't quiz me.** On design forks, recommend + reason and proceed; don't hand me multiple-choice cards. Ask only when it's genuinely my call (branding, money, live-system policy).
7. **Direct + specific.** Expert advice, real numbers, no fluff.
8. **Keep proposing.** After finishing, propose the next high-leverage build.

*(Add your own rules below this line — they carry the same weight.)*

---

## 3. DAILY SELF-IMPROVEMENT (agents get better every day)

The whole point: the agents improve every day and **never lose what they learned**.

**The loop (already wired):**
1. Agents run against real data (Scout sweeps seller threads; Dyson/Eco work client tasks).
2. They periodically **reflect** — `learn()` asks Codex to look at recent real encounters + the current playbook and **rewrite the playbook** to score/act better.
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

This is a hard operating principle for Codex AND the agents:

- **Capture, don't lose.** When something new or improved is built or learned, turn it
  into a **skill** — either a new skill or an upgrade to an existing one. Don't leave a
  good pattern as a one-off.
- **Two kinds of skill here:**
  1. **Codex skills** (`~/.Codex/skills/<name>/SKILL.md`) — reusable build patterns.
     Canonical example: **`forge-self-improving-agent`** — the recipe for giving any new
     agent its own folder, brain-loaded skills, a self-improvement loop, bus comms, and
     console/deploy wiring. Use it (and keep it current) whenever adding/upgrading an agent.
     Use **`forge-dashboard-workspace`** when adding or upgrading a profile-switcher workspace.
  2. **Agent skills** (the brain playbooks in `vault/Skills/*.md`) — each agent's living
     rubric, rewritten by its `learn()` loop.
- **Always use the newest version.** Agents mtime-reload their playbook every run, so they
  always score with the latest. Codex: before building, check for an existing skill and
  improve it rather than duplicating; after building something reusable, write/update the
  matching skill so the next session starts from the improved version.
- **Improve in place.** Prefer upgrading an existing skill over creating a near-duplicate.
  When a skill is upgraded, the upgrade is the new default immediately.

### 4a. THE CREED — evidence discipline, one per business (outranks every playbook)

Every agent runs on a **creed**: the evidence discipline for the business it works in,
written in that business's own language. **Human-owned, stable, ranked ABOVE the learned
playbook** — when they disagree, **the creed wins**.

**One creed per business** (`agent_creed.py`, `CREED_FILE`):

| Creed | Agents | Home | What it enforces |
|-------|--------|------|------------------|
| **`wholesale-evidence-discipline`** | **Scout, Marcus, Atlas** | `forge-scout/skills/` + `forge-marcus/skills/` | The thread is the only truth — never invent what a seller said, asked, or agreed to; **no agent ever invents a number**, and no price/offer ever goes out by text (Atlas's anchors are internal); Unknowns become the call's missing-info list; reply to sellers only, never to our own outreach. |
| **`agency-evidence-discipline`** | **Dyson, Eco** | `forge-agency/skills/` | Never invent a client's metric — every CPL/ROAS/spend figure carries its source **and date range**, or is Unknown; mock/unconnected channels labeled as such in the output; never invent or stretch a client request, timeline, or promised result; diagnose with ranked alternatives, not "it's the creative." |
| **`daycare-evidence-discipline`** | **Solomon** + role agents | `forge-solomon/skills/` | Never invent capacity, a start date, a rate, a balance, or a ratio; read the brief FIRST; safety/compliance outranks the analysis; look it up, escalate only the decisions. |

**All three share the spine:** *ground it, infer it, or name it **Unknown*** · 3–5 **ranked
falsifiable** hypotheses · **close the loop** — if the next lookup wouldn't change the
recommendation, decide · **two passes max**, Unknowns never block the output · weight care
by cost of being wrong · **propose, never act outward.**

**Why `agent_creed.py` is a module, not another entry in `_load_skills()` — load-bearing.**
Every `learn()` does `current = self._load_skills()` → *"output the FULL UPDATED playbook"*
→ overwrite. **Anything reachable through `_load_skills` is something self-improvement
eventually swallows and rewrites.** The creed is injected straight into each system prompt
(`agent_creed.block(business)`), never through `_load_skills` — `learn()` cannot see it, so
it can never rewrite it. Vault copy wins over seed. ~1.5–1.8k tokens/call, never truncated.

Solomon additionally carries two **top skills** above his playbook (via `_load_skills`,
isolated from `learn()` by `_playbook_only`): **`solomon-decision-loop`** (Frame → Ground →
Hypothesize → Decide → **Close** — the exit condition that kills analysis paralysis) and
**`solomon-director-craft`** (the 50 years: triage order, funnel-leak vs. lead-volume,
speed-to-lead, retention math, discount last).

**Adding an agent:** give it its business's creed — `agent_creed.block("<business>")` into
the system prompt ahead of the playbook — and keep `learn()` on the playbook alone.
Pattern credit: [mattpocock/skills](https://github.com/mattpocock/skills).

---

## 5. The agents

| Agent | Side | Job | Autonomy |
|-------|------|-----|----------|
| **Marcus** (`marcus_engine.py`) | REI | Drafts/sends seller SMS replies | Texts only on approval (NRN canned reply auto-sends). Self-learns daily/weekly. |
| **Scout** (`scout_triage.py`) | REI | Triages seller threads, ranks "text back ASAP", tags + pipeline pushes, hands hot leads to Marcus | Never texts. Tags/pipeline queued for approval. Self-improves autonomously. |
| **Dyson** (`agency_agents.py`) | Agency | Plans/ships client website + code edits | Plan-only; nothing live until approved. Self-improves. |
| **Eco** (`agency_agents.py`) | Agency | Ads strategy / Meta analysis / concepts | Recommends only; launches on approval. Self-improves. |

Shared infra: `review_agent._claude` + `review_agent.MODEL` (Codex calls), `brain_io`
(vault read/write + git), `agent_bus.py` (inter-agent messages), key resolvers fall back
(agent's own key → wholesale `ghl.env` / agency `agency.env`).

**Agent comms + handoff:** one shared bus (`agent_bus.py`, `/api/bus`) carries messages
across BOTH workspaces. Scout → Marcus handoff (`marcus_engine.make_proposal_for`) drops a
hot lead into Marcus's approval inbox. Comms show in the Command Center (REI) and the
Agents → Comms tab (Agency).

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
- Then `./deploy/push.sh root@24.199.81.124` and SSH-verify.

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
- Daycare starter data: browser-local `forge_daycare_v1` until shared backend storage is connected.
- Bus: `/api/bus` · Brain: `/api/brain/{tree,note,search,recent,graph,activity,status}`
- Knobs: `FORGE_SCOUT_*` (scout.env), `AGENCY_LEARN_EVERY`, `FORGE_VAULT`, `FORGE_MARCUS`.
