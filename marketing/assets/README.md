# /assets — Brand assets (real, not generated)

Drop the real brand assets here so every generation uses consistent, authentic visuals
instead of AI stand-ins. The `/generate-marketing` skill pulls from this folder.

## What goes here

- **Logos / badges** — the FORGE / ClientForge wordmark used as `{{brand_badge}}` in the
  thumbnail template. Same badge every time = brand recognition.
  - Suggested: `logo-primary.png` (transparent), `logo-mark.png` (icon only), `badge.png`.
- **Headshots** — your real headshot(s) for `{{headshot_pose}}`. Consistent framing/pose.
  - Suggested: `headshot-primary.png`, plus a couple of expression variants
    (`headshot-neutral.png`, `headshot-explain.png`) for the Scale-pass variations.
- **Brand color chip** — a note or swatch of the single `{{accent_color}}` hex.
- **UI evidence screenshots** *(optional but powerful)* — real dashboard/agent screenshots
  used as `{{ui_evidence}}`. A `ui/` subfolder keeps them tidy.

## Rules

- **Real assets only.** Per the voice guide's honesty rule, don't substitute a generated
  headshot/logo for the real one unless you explicitly ask for a placeholder.
- Keep filenames stable — templates and the skill reference them.
- Large binaries: check `../.gitignore` / repo policy before committing heavy files.

*(No secrets in this folder — keys live in `../../forge-agency/config/agency.env`, never here.)*
