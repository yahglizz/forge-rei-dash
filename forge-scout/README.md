# Forge Scout — lead-triage agent config home

This folder is **Scout's** own home, kept separate from the web app and from the
other agents' key files. It is a sibling of the dashboard (`forge rei/`), so
nothing in here is ever served over HTTP — config and keys live here safely.

**Scout** is the wholesale real-estate lead-triage agent. It reads GoHighLevel
seller text threads, scores how motivated each seller is, ranks who to text back
first (speed-to-lead), filters out stop/not-interested, and **queues** GHL tags +
pipeline pushes for human approval. **Scout never texts a seller — Marcus owns
all outbound. Scout only proposes; a human approves tags and pipeline moves.**

```
forge rei dash/
├─ forge rei/                 <- the dashboard (web-served)
├─ marcus-wholesale-agent/    <- WHOLESALE outbound agent (its own keys)
├─ forge-agency/              <- AGENCY config (its own keys)
└─ forge-scout/               <- THIS folder: SCOUT triage config
   ├─ config/
   │  ├─ scout.env            <- REAL config (private, git-ignored, never served)
   │  └─ scout.env.example    <- template; copy to scout.env and edit
   └─ skills/
      ├─ scout-playbook.md        <- Scout's triage rubric (injected into scoring)
      └─ scout-skills-backlog.md  <- brainstormed roadmap of future capabilities
```

## What each file does

| File                          | Purpose                                                                 |
|-------------------------------|-------------------------------------------------------------------------|
| `config/scout.env`            | Scout's runtime knobs (sweep interval, batch size, pages, pipeline match) and optional own Anthropic key / vault override. **Git-ignored.** |
| `config/scout.env.example`    | Safe-to-commit template of the same keys; copy to `scout.env`.          |
| `skills/scout-playbook.md`    | The brain — motivation rubric (0–100), distress signals, buckets, price bands, next-best-action, pipeline mapping, hard rules. Injected into Scout's Claude scoring prompt. |
| `skills/scout-skills-backlog.md` | Brainstormed list of candidate skills to build into Scout over time. |

## Where Scout reads its playbook

Scout loads its triage rubric from **two** places and merges them:

1. **Local:** `forge-scout/skills/scout-playbook.md` (this folder — the base rubric).
2. **Obsidian brain:** `<FORGE_VAULT>/Skills/scout-playbook.md` (learned/edited
   over time; default vault `~/Desktop/Agentic-OS/vault`, overridable via
   `FORGE_VAULT` in `scout.env`).

The vault copy lets Scout's rubric evolve from real outcomes (which signals
actually converted) without editing code. The local copy is the committed base;
the vault copy is the living, learned layer.

## Config knobs (`scout.env`)

- `FORGE_SCOUT_INTERVAL` — seconds between conversation sweeps (default `180`).
- `FORGE_SCOUT_BATCH` — max conversations Claude-scored per pass (default `15`).
- `FORGE_SCOUT_PAGES` — conversation pages scanned per pass (default `4`).
- `FORGE_SCOUT_PIPELINE` — substring to pick the GHL pipeline (default `wholesal`).
- `SCOUT_ANTHROPIC_API_KEY` — optional; Scout's own Claude key. Falls back to the
  shared wholesale Anthropic key if unset.
- `FORGE_VAULT` — optional override for the Obsidian brain path.

## Secrets

Real config and keys live only in `config/scout.env`, which is **git-ignored**
(`config/*.env`). Only `*.env.example` is committed. This folder is OUTSIDE the
web-served dir, so nothing here is reachable over HTTP. Do not paste real keys
into the example or any committed file.
