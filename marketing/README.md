# /marketing — Claude + Higgsfield Automated Marketing System

Agency-side (ClientForge) marketing engine. One input (a video title/topic) → on-brand
thumbnails + copy, via the **DBS (Design → Build → Scale)** framework. Additive to FORGE;
nothing here edits or removes existing code.

## Structure

```
marketing/
├── claude.md                     # Project instructions (read order, DBS, Higgsfield wiring, rules)
├── context/
│   ├── business_overview.md      # Identity, offer, goals   [has REFINE tags]
│   ├── pov.md                    # Views + contrarian takes [has REFINE tags]
│   └── voice_guide.md            # Anti-AI rules, banned words, style
├── templates/
│   ├── thumbnail_template.md     # Higgsfield master prompt (badge/title/accent/UI/pose params)
│   └── copy_template.md          # Title/hook/description that matches the thumbnail
├── assets/                       # Real logos + headshots + UI screenshots (you add these)
│   └── README.md
└── .claude/
    └── skills/
        └── marketing_gen.md      # /generate-marketing — the DBS automation
```

## Use it

1. Fill the **[REFINE]** blanks in `context/` and drop real files in `assets/`.
2. Run `/generate-marketing <your video title or topic>`.
3. It returns a filled Higgsfield master-prompt + copy + 3 variations. You pick + refine.
   Nothing is published or boosted — that stays your one-tap action.

## Wiring

- **Higgsfield:** renders through the shared account via `../forge rei/higgsfield_io.py`
  (`/v1/text2image/soul`, `1536x1536`). Key `HIGGSFIELD_API_KEY` resolves from
  `../forge-agency/config/agency.env` (or `daycare.env`). No key → it outputs ready-to-paste
  prompts and stops (never fakes an image).
- **Brand + rules:** grounded in `../NORTH_STAR.md`, `../CLAUDE.md` §2, and
  `../forge-agency/skills/agency-context.md`. Same propose→human-executes gate as Eco.

## Make the slash command live in Claude Code (optional)

The skill sits at `marketing/.claude/skills/marketing_gen.md` exactly as the tutorial
specifies. To expose `/generate-marketing` at the repo root in a Claude Code session,
copy or symlink it into the repo-root `.claude/` (e.g. `.claude/commands/generate-marketing.md`)
— left to you so this drop-in stays fully additive and doesn't touch repo-root config.
