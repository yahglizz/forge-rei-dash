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

*Last updated: 2026-11-12.*

> **Per-agent cards live in [`agents/`](agents/), one file per agent, filed by
> business.** This file is the single-page overview and is current as of 2026-11-11
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
(HOT-lead auto-tag; #forge-knowledge notes; opt-in, default-OFF autopilot bumps, ACE, and daycare reply auto-send) are listed in `CLAUDE.md` §2.

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
daycare lanes are the always-on machinery. Models: Haiku 5.5 at low effort for scoring, triage,
screening, parsing and lookups; Sonnet 5.5 for seller/parent replies, money, plans and briefs. Chat
starts on Haiku and restarts on Sonnet when it needs judgment, writing or any write
(`FORGE_CHAT_ROUTER=0` goes straight to Sonnet). Opus/Fable can't be reached: hard allowlist in
`review_agent`, enforced in `test_model_policy.py`.

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
hits a question he can't answer. Pipeline lane: two GHL enrollment boards, never mixed —
"Enrollment" (A Touch of Blessings) and "A Mother's Touch" (1923, a separate legal entity); the daily
n8n run moves stages forward on evidence, Lost stays a `pipe-propose:lost` tap; "enrolled" = a child row
in the production roster (a Family Contact Form alone is paperwork, not enrollment). Card:
[`agents/daycare/solomon.md`](agents/daycare/solomon.md) §20. Codex: read `forge-solomon/AGENTS.md`.

### Dropship — Midas (archived; read + propose only, never launches/spends/orders)

### n8n → agents
n8n Cloud (`atob.app.n8n.cloud`) triggers agents through `agent_gateway.py`: each job runs as a child
process from the agent's own folder, loads that folder's files with a recorded hash, and holds one
Anthropic key. Workflows name a fixed task; owner chat has dashboard-chat tools and gates. Details:
`CLAUDE.md` §8a.

### Chat routing (Telegram + Slack)
Each business has its own Telegram chat (`/bind daycare|agency|wholesale|dropship`). When
`FORGE_CHAT_TRANSPORT` is `both` or `slack`, Slack runs beside it: one private, owner-only channel per
business (`#forge-hq`, `#forge-daycare`, `#forge-agency`, `#forge-wholesale`; dropship has none while
archived), bound with `/forge bind <business>`. Everything about a business — alerts, pings,
loop-down/recovered, receipts — goes ONLY to that business's chat or channel. HQ keeps system alerts
(Anthropic credits/auth, clock, sync, graph builder) and Orion. A card can be tapped in either app; the
first tap wins and the other app's buttons are refused. Details: `CLAUDE.md` §5 and
`docs/runbooks/slack-cutover.md`.

**Daycare in Slack is organized by site (2026-11-12).** `#forge-daycare` and the shared rooms
(`#daycare-alerts/-tours/-quotes/-starting/-enrolled`) carry the overview: the 8 AM and 6 PM Eastern
briefs only (`slack_briefs.py`, zero Claude calls). The specifics live per A Touch of Blessings site:
`#daycare-921` / `#daycare-2318` (leads, parent replies) and `#921-` / `#2318-tours`, `-quotes`,
`-enrolled` (`slack_rooms.site_target`). Site comes from the board's location tag, never from text;
A Mother's Touch stays in `#amt-1923`. Solomon's map: `forge-solomon/skills/solomon-slack-channels.md`.

**#forge-knowledge = the agents' Slack brain.** Every agent reads it (`GET /api/knowledge?q=`);
Solomon, Marcus, Dyson and Orion add notes on their own (`POST /api/knowledge/post`, chat AUTO tier,
a ✅ card once their context holds outside text). No names, phones, emails or keys. Exception and
gates: `CLAUDE.md` §2.

**Center tags are automatic (2026-11-12).** A family with no `loc-` tag whose own form fields name exactly
one A Touch of Blessings center gets that tag by itself (`daycare_center_tag.py`), and Solomon can add
one center tag to a provably untagged family without a card. Never Mother's Touch, never a move, never
when two centers are named. Intake and login tags still need your tap. Tap cards are one plain line
("Tag Seara Peterson → 2318 Cecil B. Moore") with ✅ Do it / ❌ Cancel.

---

## The owner's Mac (`mac_run`)

Owner decision 2026-11-01, written risk accepted. In his own chats an agent can run a real shell
command on his Mac while it is awake, through a ✅ card showing the exact command. Only the owner's
tap runs a card. **At launch every command is a tap, for every agent on every surface.**

**`FORGE_MAC_AUTO=1` allows auto-run, default off.** It must stay off until the vault playbook is
hash-pinned, because that playbook is in every gateway prompt. With it on, all of these must hold: Orion, Dyson or Eco; a
gateway chat from the dashboard, phone or box Telegram, not n8n; no lanes, open tasks or
caller-supplied history in the prompt; every replayed history row flagged `clean`; nothing read this
turn but `mac_status` or `/api/cost/status`; the agent not tainted; `FORGE_CHAT_AUTO` on; and the
command misses the risky list. `clean` is earned only on a turn that already met those rules, so one
outside read, one old row or one auto-run keeps that agent's thread on cards until the thread is
reset. Solomon, Marcus, Scout and Atlas always get a card, because their prompts carry lead and seller
text. Workflow jobs, teammate consults and the old Telegram path never get the tool.

A long-running process doesn't survive: `nohup … &` dies with the command's group.

Rules: `CLAUDE.md` section 2 (Mac shell) and section 8a (Mac link). Kill: `FORGE_MAC=0`, clock-out,
`~/.forge-mac/off`, or `launchctl bootout`.

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
