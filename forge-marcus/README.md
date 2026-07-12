# Forge Marcus — lead-screening agent config home (and Marcus's chief-of-ops seat)

This folder is **Marcus's** own home, kept separate from the web app and from the
other agents' key files. It is a sibling of the dashboard (`forge rei/`), so
nothing in here is ever served over HTTP — config and keys live here safely.

**Marcus is the CHIEF of wholesale ops.** He is the wholesale real-estate
lead-**screening** agent (reads a seller's GoHighLevel SMS thread + Scout's
triage, writes a Seller Screening Report + call-prep notes + a lead-stage
recommendation) AND the team lead: `marcus_lead.py` has him survey Scout's
queue, his own screenings, pending proposals, and the day's battle plan, then
issue numbered directives to Scout and the operator. Scout and Atlas both hand
their work to him — nothing goes to a seller except through Marcus. **Marcus is
NOT a closer:** he never negotiates or writes a contract, and never states a
price/offer over text unless the seller already gave one first. He produces
decision support (screening) and direction (lead-agent); the human calls.

## Chain of command

- **Scout** (`scout_triage.py`) finds + ranks + tags. Every call-worthy lead
  (asap/warm) is auto-handed to Marcus the moment it's scored (`connector.py`
  `_auto_screen`, wired to `SCOUT.on_scored`) — posted on `agent_bus` as a
  `"handoff"` message (`scout` → `marcus`), visible in Comms + Telegram
  (🤝 *Handed to Marcus*). Scout never texts a seller.
- **Marcus** (`marcus_screening.py` screens; `marcus_engine.py` drafts/sends)
  is the front door. He's wired directly into Atlas's constructor
  (`DEAL_PREP = deal_prep.DealPrep(SCOUT, SCREENER, ...)`, `connector.py`) so
  Atlas's prep work reads live off Marcus's screening reports.
- **Atlas** (`deal_prep.py`, seed skill lives in *this* folder — see below)
  underwrites every seller Marcus screens as interested and reports each
  finished deal prep back to Marcus on the bus, also kind `"handoff"`
  (`atlas` → `marcus`). Atlas never contacts anyone.
- **The only sends.** Exactly two functions in the whole codebase ever call
  GHL's outbound-message endpoint for a seller: `marcus_engine._send` (fires on
  operator `approve()` of a drafted proposal) and `marcus_screening.
  send_nurture` (the one-click nurture check-back). Both are gated behind the
  single central `sms_guard.guard()` — TCPA hours, DNC, dedupe, price/offer
  scrub. No other agent — not Scout, not Atlas — ever reaches that endpoint.
- **Marcus directs.** `marcus_lead.py` (`skills/marcus-lead-agent.md` below)
  fires after the morning battle-plan build and on demand
  (`POST /api/marcus/directives/run`, Telegram `/directives`): it reads the
  whole ops picture and posts numbered directives — one set to Scout
  (`agent_bus` kind `"directive"`, `to="scout"`), one to the operator
  (`to="all"`) — both land in Comms + Telegram.

```
forge rei dash/
├─ forge rei/                 <- the dashboard (web-served)
├─ marcus-wholesale-agent/    <- WHOLESALE outbound agent (its own keys)
├─ forge-scout/               <- SCOUT triage config
└─ forge-marcus/              <- THIS folder: MARCUS's home — also where ATLAS rides
   ├─ config/
   │  ├─ marcus.env           <- REAL config (private, git-ignored, never served)
   │  └─ marcus.env.example   <- template; copy to marcus.env and edit
   └─ skills/
      ├─ marcus-lead-agent.md          <- Marcus's LEAD AGENT charter (chief-of-ops, directs Scout + operator)
      ├─ marcus-screening-playbook.md  <- the screening rubric + report contract
      ├─ marcus-critical-thinking.md   <- how Marcus reasons about each convo (fact vs inference, path-to-contract logic)
      ├─ marcus-seller-psychology.md   <- seller psychology / motivation / what gets a deal signed
      ├─ marcus-nurture-followup.md    <- the "not right now" lane: comfort + check-back draft (in the operator's voice)
      ├─ wholesale-seller-texter.md    <- Yahjair's exact texting voice/persona, PRICE/READY trigger gate
      ├─ atlas-underwriter.md          <- ATLAS's seed playbook (deal-prep rubric, anchor discipline) — Atlas reports to Marcus, so his seed lives here
      ├─ lead-followup-skill.md        <- GHL lead follow-up audit + send process
      └─ marcus-skills-backlog.md      <- roadmap of future screening capabilities
```

Marcus merges five files into his screening prompt every run (playbook +
critical-thinking + seller-psychology + nurture-followup + the seller-texter
voice skill), alongside any matching brain-vault copies. Atlas merges only its
own (`atlas-underwriter.md`) the same way. For nurture drafts, Marcus also
loads the operator's learned voice (`<vault>/Skills/yahjair-voice.md`).

## What each file does

| File | Purpose |
|------|---------|
| `config/marcus.env` | Marcus's (and Atlas's — Atlas folds this same env in) screening/prep knobs, auto-screen/auto-prep on-off, learn cadence, msgs/thread, optional own Anthropic keys / vault override. **Git-ignored.** |
| `config/marcus.env.example` | Safe-to-commit template of the same keys; copy to `marcus.env`. |
| `skills/marcus-lead-agent.md` | Marcus's charter as LEAD AGENT — head of the whole FORGE REI operation, directs the team. Read by `marcus_lead.py`'s directive loop. |
| `skills/marcus-screening-playbook.md` | Qualification factors, distress signals, 1–10 score bands, lead stages, the strict JSON report contract, and the hard rules (no ARV/MAO/offers/price/contracts/texting). |
| `skills/marcus-critical-thinking.md` | How Marcus separates stated fact from inference, and reasons about path-to-contract. |
| `skills/marcus-seller-psychology.md` | Seller psychology / motivation signals / what actually gets a deal signed. |
| `skills/marcus-nurture-followup.md` | The "not right now" lane — comfort + check-back drafting, in the operator's voice. |
| `skills/wholesale-seller-texter.md` | Yahjair's exact texting voice, fired only on PRICE/READY signals; the hard "always drive to a call, never a price by text" rule. |
| `skills/atlas-underwriter.md` | Atlas's deal-underwriting rubric — anchors ONLY from the seller's own stated ask, MAO math, call-card structure. Self-improves via `DealPrep.learn()` (mirrors Marcus's/Scout's loops). |
| `skills/lead-followup-skill.md` | GHL lead follow-up audit + send process. |
| `skills/marcus-skills-backlog.md` | Brainstormed list of future screening/lead-agent skills. |

## Where Marcus (and Atlas) read their playbooks

Both agents load their rubric from **two** places and merge them, mtime-cached
so edits hot-reload on the next run:

1. **Local (this folder):** the seed files above — the committed floor.
2. **Obsidian brain:** `<FORGE_VAULT>/Skills/<file>.md` — the living, learned
   layer, rewritten by each agent's own `learn()` loop from real encounters
   (default vault `~/Desktop/Agentic-OS/vault`, overridable via `FORGE_VAULT`).

## Secrets

Real config and keys live only in `config/marcus.env`, which is **git-ignored**
(`config/*.env`). Only `*.env.example` is committed. This folder is OUTSIDE the
web-served dir, so nothing here is reachable over HTTP. Do not paste real keys
into the example or any committed file.
