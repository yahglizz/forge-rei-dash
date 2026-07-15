# FORGE — The Agents

*The single, current roster of every AI agent in FORGE REI OS: what each one does,
where it lives, who it answers to, and exactly how much it's allowed to do on its
own. One file, all eight agents, three businesses.*

> **Canonical vs. reference.** The enforced autonomy rules live in `CLAUDE.md` §2,
> the full agent table in `CLAUDE.md` §5, and the brains/skills/creed/env map in
> `NORTH_STAR.md` §6. This file is the human-readable directory that ties them
> together — when an agent's scope or autonomy changes, update `CLAUDE.md` first,
> then this. (This replaced an older Codex-era operating-manual copy; the
> operating-manual content is canonical in `CLAUDE.md`, not duplicated here.)

*Last updated: 2026-07-15.*

---

## The one rule that governs every agent

**Propose → review → execute.** No agent takes an outward or irreversible action
on its own. Agents autonomously do only: score/triage, **auto-apply internal +
reversible tags** (HOT-lead triage tags), read the brain, write their own learned
playbook back to the brain, and post on the agent bus. Everything outward —
texting a seller, moving pipeline, launching an ad, sending an invoice, posting
social — is gated behind the operator's one-tap approval. Documented exceptions
(HOT-lead auto-tag, opt-in autopilot bumps) are internal + reversible by design.

**Every agent also self-improves:** after N real encounters it reflects
(`learn()`), rewrites its own playbook into the brain (git-committed), and reloads
the newest version on its next run. The **creed** (evidence discipline, per
business) sits above the playbook and `learn()` can never rewrite it.

---

## Wholesale — A Touch of Blessings Home Buyers

Chain of command: **Marcus** (head) → **Scout** (finds/ranks) + **Atlas**
(underwrites). Only Marcus can ever send an outbound SMS.

| Agent | Engine | Job | Autonomy |
|---|---|---|---|
| **Scout** | `scout_triage.py` | Finds, ranks, organizes every inbound seller reply — scores motivation, buckets asap/warm/nurture/dead, tags + pipeline, flags hot, weekly missed-lead audit. Auto-hands call-worthy leads to Marcus. | Never texts. Tags/pipeline queued for approval (except HOT-lead auto-tag: internal + reversible). Self-improves. |
| **Marcus** | `marcus_screening.py` + `marcus_engine.py` | Screens each interested seller → call-ready report (score, missing info, red flags, path to contract). Also the **seller text-back drafter** — tailors every reply to what the seller said, drives to a call, **never a price by text** (code-enforced). | Never closes/negotiates/quotes by text. Every reply is a proposal the operator approves. Self-improves. |
| **Atlas** | `deal_prep.py` | Underwrites every screened-interested seller — extracts facts, derives offer anchors (open/target/walkaway) from the seller's stated ask, the MAO math, the negotiation call card. | Never contacts anyone. Numbers are **internal only**, never sent. Reports to Marcus. Self-improves. |

---

## Agency — ClientForge (brand: "Forge Labs")

Two agents, both plan/recommend only — nothing ships or spends without approval.

| Agent | Engine | Job | Autonomy |
|---|---|---|---|
| **Dyson** | `agency_agents.py` (`"dyson"`) | Turns a client edit/build/automation request into a reviewable **plan** — affected files, risk level, numbered steps. Reads the code-graph (Graphify) for context. | Plan-only; never says "done" for anything not actually deployed. Self-improves. |
| **Eco** | `agency_agents.py` (`"eco"`) | Reads a client's Meta ad performance vs. benchmarks, calls scale/hold/kill/refresh, drafts new ad concepts. | Recommends only; never spends a client's budget on its own. Self-improves. |

---

## Daycare — A Touch of Blessings Learning Academy

Chain of command: **Solomon** (head / executive director) → **Nora** (roster/
family comms) + **Nova** (ad ops). All propose/delegate; none writes outward.

| Agent | Engine | Job | Autonomy |
|---|---|---|---|
| **Solomon** | `daycare_director.py` | Head of all daycare agents — a 50-year childcare-director persona. Reads the whole center, produces the ranked operating brief (Attention Now / Enrollment / Money / People / Delegations), owns enrollment, delegates the rest via the bus. | Never texts/invoices/launches ads/writes the DB. Proposes + delegates. Self-improves. Carries two top skills (decision-loop, director-craft) above his playbook. |
| **Nora** | `daycare_family.py` | Keeps the roster organized (new enrollments, data gaps, capacity/ratio) + follows up on family comms after a Text Blast. | Never texts/writes records. Proposes only. Reports to Solomon. Self-improves. |
| **Nova** | `daycare_adops.py` | Campaign health, competitor intel, creative direction for the daycare's Meta ads. | Never launches/spends/generates creative herself. Recommends only. Reports to Solomon. Self-improves. |

---

## How the agents talk to each other

- **Agent bus** (`agent_bus.py`, `/api/bus`) — one shared message bus across all
  three workspaces. Scout → Marcus handoff is automatic; Solomon delegates to
  Nora/Nova over it. Surfaced in the Command Center (REI) and Agents → Comms (Agency).
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
3. **Top skills / decision-loop** (Solomon/Nora/Nova) — operating judgment.
4. **The learned playbook** — what `learn()` rewrites, reloaded each run.

Full brains / skills / creed / playbook file map: `NORTH_STAR.md` §6.

---

## Self-improvement, at a glance

- **Triggers:** automatic after N encounters (`FORGE_SCOUT_LEARN_EVERY=25`,
  `AGENCY_LEARN_EVERY=12`, `FORGE_{SOLOMON,NORA,NOVA}_LEARN_EVERY=8`,
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
