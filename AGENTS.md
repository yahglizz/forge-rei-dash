# FORGE — The Agents

*The single, current roster of every AI agent in FORGE REI OS: what each one does,
where it lives, who it answers to, and exactly how much it's allowed to do on its
own. One agent per business (three active, one archived) + the CEO, Orion.*

> **Canonical vs. reference.** The enforced autonomy rules live in `CLAUDE.md` §2,
> the full agent table in `CLAUDE.md` §5, and the brains/skills/creed/env map in
> `NORTH_STAR.md` §6. This file is the human-readable directory that ties them
> together — when an agent's scope or autonomy changes, update `CLAUDE.md` first,
> then this. (This replaced an older Codex-era operating-manual copy; the
> operating-manual content is canonical in `CLAUDE.md`, not duplicated here.)

*Last updated: 2026-09-30.*

> **Per-agent cards live in [`agents/`](agents/), one file per agent, filed by
> business.** This file is the single-page overview and is current as of 2026-09-30
> (one agent per business + Orion). `CLAUDE.md` §2 and §5 remain canonical for autonomy.
> Checked by `forge rei/test_agents_docs.py`.

---

## The one rule that governs every agent

**Propose → review → execute.** No agent takes an outward or irreversible action
on its own. Agents autonomously do only: score/triage, **auto-apply internal +
reversible tags** (HOT-lead triage tags), read the brain, write their own learned
playbook back to the brain, and post on the agent bus. Everything outward —
texting a seller, moving pipeline, launching an ad, sending an invoice, posting
social — is gated behind the operator's one-tap approval. Documented exceptions
(HOT-lead auto-tag; opt-in, default-OFF autopilot bumps, ACE, and daycare reply auto-send) are listed in `CLAUDE.md` §2.

**Every agent can self-improve (scheduled self-improvement is OFF since 2026-09-30; manual "Learn" buttons work):** after N real encounters it reflects
(`learn()`), rewrites its own playbook into the brain (git-committed), and reloads
the newest version on its next run. The **creed** (evidence discipline, per
business) sits above the playbook and `learn()` can never rewrite it.

---

## The roster today (2026-09-30): ONE agent per business + the CEO

| Business | Status | Main agent | Engine | Lanes (loops that report on the agent's row) |
|---|---|---|---|---|
| **Wholesale (REI)** | active (flagged `maintenance`) | **Marcus** | `marcus_screening.py` + `marcus_engine.py` | Scout (`scout_triage.py`, finds/ranks), Atlas (`deal_prep.py`, underwrites), Follow-up, ACE, Autopilot |
| **Agency (ClientForge)** | active | **Dyson** | `agency_agents.py` | Eco (Meta ads recommendations) |
| **Daycare** | active | **Solomon** | `daycare_director.py` | Replies (`daycare_replies.py`), Leads (`daycare_leads.py`), Starts (`daycare_starts.py`) |
| **Dropship** | **archived** (hidden, data kept; Reactivate in Mission Control) | **Midas** | `dropship_director.py` | product research · creative & ads · fulfillment & support |
| *(Agency · Personal lens)* | archived | — | — | — |
| **Cross-business** | always on | **Orion** (CEO) | `mission_control_agent.py` | oversees + checks in on the four; no scheduled brief |

Source of truth: `forge rei/agents_hub.py` (`AGENTS`, `LANE_OF`) and live `GET /api/businesses`
+ `GET /api/agents/registry`. A lane id (scout, atlas, eco, daycare_replies…) resolves to its
main agent for chat, tasks, the office and the registry. **Scheduled briefs and scheduled
self-improvement are OFF** (owner decision 2026-09-30); Scout's sweep, Follow-up, Atlas and the
daycare lanes are the always-on machinery. Models: small jobs on Haiku 4.5, seller/parent reply
drafts and main-agent chat on Sonnet 5.5; Opus/Fable never (`test_model_policy.py`).

Per-agent cards (triggers, reads, gates, cost, how to verify): [`agents/`](agents/).

### Wholesale — Marcus (only Marcus can ever send a seller SMS; every one is a tap, never a price)
Scout finds/ranks/tags (HOT leads auto-tag: internal + reversible) and hands call-worthy leads to
Marcus; Marcus screens them and drafts replies; Atlas underwrites (numbers internal only).
Opt-in, default OFF: ACE and Autopilot auto-sends (`CLAUDE.md` §2).

### Agency — Dyson (plan/recommend only; nothing ships or spends without approval)
Dyson plans client edits; his Eco lane reads Meta performance and recommends scale/hold/kill.

### Daycare — Solomon (growth director: enrollment only — paperwork/compliance/billing/staff admin are NOT his lane)
Ranked growth brief (families waiting → funnel leak → sellable seats → retention → demand → offer
clock) + speed-to-lead follow-through: Replies texts back a parent ~90 s–5 min after they text
(drafts for the owner's tap, or auto-send for clean enrollment-lead answers when the operator
opts in with `FORGE_DAYCARE_REPLY_AUTO=1`, default OFF), pings the daycare Telegram chat when he
hits a question he can't answer. Codex: read `forge-solomon/AGENTS.md`.

### Dropship — Midas (archived; read + propose only, never launches/spends/orders)

### Telegram routing
Each business has its own chat (`/bind daycare|agency|wholesale|dropship`); everything about a
business — alerts, pings, loop-down/recovered, receipts — goes ONLY to that chat. HQ keeps
system alerts (Anthropic credits/auth, clock, sync, graph builder) and Orion.

---

## How the agents talk to each other

- **Agent bus** (`agent_bus.py`, `/api/bus`) — one shared message bus across all
  four workspaces. Scout → Marcus handoff is automatic; Solomon and Midas post
  their delegations and operating notes here. Surfaced in the Command Center (REI) and Agents → Comms (Agency).
- **Coaching network** (`agent_coach.py`) — every agent can **ask a peer** a
  question and **broadcast a transferable insight** (a converting ad angle, a
  screening tell, a retention move) to a peer / business / all. Peer insights fold
  into the recipient's next `learn()` automatically. **Insights only** — never a
  credential, token, client object, or an outward instruction. Details: `CLAUDE.md` §11.

---

## The layered prompt every agent runs on

Built top-to-bottom, each layer framing everything below it (see `NORTH_STAR.md` §8):

1. **`NORTH_STAR.md`** — mission, identity, tone, cross-business principles.
2. **The creed** (`agent_creed.block(business)`) — evidence discipline in that
   business's own language. *Ground it, infer it, or name it Unknown.* `learn()`
   can never see or rewrite it.
3. **Top skills / decision-loop** (Solomon and Midas) — operating judgment.
4. **The learned playbook** — what `learn()` rewrites, reloaded each run.

Full brains / skills / creed / playbook file map: `NORTH_STAR.md` §6.

---

## Self-improvement, at a glance

- **Triggers:** automatic after N encounters (`FORGE_SCOUT_LEARN_EVERY=25`,
  `AGENCY_LEARN_EVERY=12`, `FORGE_SOLOMON_LEARN_EVERY=8`,
  `FORGE_MARCUS_LEARN_EVERY=15`, `FORGE_ATLAS_LEARN_EVERY=12`), rate-limited; or
  the manual "Learn from brain" button.
- **Where the live playbook is:** the vault (`vault/Skills/<agent>-playbook.md`),
  git-committed. The seed in `forge-*/skills/` is the floor; the vault copy is
  what the agent currently "knows."
- **What can't be rewritten:** `NORTH_STAR.md` and the creed — injected outside
  `_load_skills()`, invisible to `learn()`, by design.

---

## Chat brevity (token discipline)

Operator-facing **agent chat** replies run in a terse, high-signal "caveman" style
to cut Anthropic output tokens (`docs/skills/caveman-brevity.md`). Chat answers
only — it never touches seller-facing SMS drafts (voice + quality critical), the
creed, or evidence discipline.

## Daily notes (Claude + Codex)
Shared handoff log: `~/Desktop/A Touch of Blessings — Brand Kit/docs/daily/`. Read the newest 2 files at session start; append to today's `YYYY-MM-DD.md` at session end and after any deploy/migration/workflow change. Rules in that folder's README.md.
Codex (no hooks): run `bash "$HOME/Desktop/A Touch of Blessings — Brand Kit/scripts/daily-note.sh" start` first and `... stop` last. Claude hooks do this automatically.
