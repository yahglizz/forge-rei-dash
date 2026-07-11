# Forge Marcus — lead-screening agent config home

This folder is **Marcus's** own home, kept separate from the web app and from the
other agents' key files. It is a sibling of the dashboard (`forge rei/`), so
nothing in here is ever served over HTTP — config and keys live here safely.

**Marcus** is the wholesale real-estate lead-**screening** agent. He reads a
seller's GoHighLevel SMS thread + Scout's triage and writes a **Seller Screening
Report** + call-prep notes + a lead-stage recommendation so the operator knows who
to personally **call**. **Marcus is NOT a closer:** he never texts a seller, never
makes an offer, never talks numbers (no ARV / MAO / price unless the seller already
gave one), never writes a contract. He produces decision support; the human calls.

> Scout still owns triage scoring (0–100 motivation), bucketing, tags, and pipeline
> pushes. Marcus consumes Scout's output as input and ADDS the deep qualification
> layer on top. (Marcus also has a dormant SMS engine in `marcus_engine.py`, kept
> off — screening is his front door.)

```
forge rei dash/
├─ forge rei/                 <- the dashboard (web-served)
├─ marcus-wholesale-agent/    <- WHOLESALE outbound agent (its own keys)
├─ forge-scout/               <- SCOUT triage config
└─ forge-marcus/              <- THIS folder: MARCUS screening config
   ├─ config/
   │  ├─ marcus.env           <- REAL config (private, git-ignored, never served)
   │  └─ marcus.env.example   <- template; copy to marcus.env and edit
   └─ skills/
      ├─ marcus-screening-playbook.md   <- the screening rubric + report contract
      ├─ marcus-critical-thinking.md    <- how Marcus reasons about each convo (fact vs inference, path-to-contract logic)
      ├─ marcus-seller-psychology.md    <- seller psychology / motivation / what gets a deal signed
      ├─ marcus-nurture-followup.md     <- the "not right now" lane: comfort + check-back draft (in the operator's voice)
      └─ marcus-skills-backlog.md       <- roadmap of future screening capabilities
```

All four skill files (playbook + critical-thinking + seller-psychology + nurture-followup) are
merged and injected into Marcus's screening prompt every run, alongside any matching brain-vault
copies. For nurture drafts, Marcus also loads the operator's learned voice
(`<vault>/Skills/yahjair-voice.md`) so the check-back message sounds like him.

## What each file does

| File | Purpose |
|------|---------|
| `config/marcus.env` | Marcus's screening knobs (auto-screen on/off, msgs/thread, learn cadence) + optional own Anthropic key / vault override. **Git-ignored.** |
| `config/marcus.env.example` | Safe-to-commit template of the same keys; copy to `marcus.env`. |
| `skills/marcus-screening-playbook.md` | The brain — qualification factors, distress signals, 1–10 score bands, lead stages, the strict JSON report contract, and the hard rules (no ARV/MAO/offers/price/contracts/texting). Injected into Marcus's screening prompt. |
| `skills/marcus-skills-backlog.md` | Brainstormed list of future screening skills. |

## Where Marcus reads his playbook

Marcus loads his screening rubric from **two** places and merges them:

1. **Local:** `forge-marcus/skills/marcus-screening-playbook.md` (this folder — the base).
2. **Obsidian brain:** `<FORGE_VAULT>/Skills/marcus-screening-playbook.md` (learned/edited
   over time; default vault `~/Desktop/Agentic-OS/vault`, overridable via `FORGE_VAULT`).

The vault copy is the living layer his `learn()` loop rewrites from real screenings; the
local copy is the committed floor. Edits hot-reload on the next run (mtime-cached).

## Secrets

Real config and keys live only in `config/marcus.env`, which is **git-ignored**
(`config/*.env`). Only `*.env.example` is committed. This folder is OUTSIDE the
web-served dir, so nothing here is reachable over HTTP. Do not paste real keys
into the example or any committed file.
