---
name: generate-marketing
description: Turn one input (a video title, hook, or topic) into on-brand ClientForge marketing — a filled Higgsfield thumbnail master-prompt + matching copy + 3 image variations — using the DBS (Design, Build, Scale) framework, grounded in /context and /templates. Never invents proof; renders via the shared Higgsfield soul endpoint when a key is present, otherwise outputs ready-to-paste prompts.
---

# /generate-marketing — DBS marketing generator (Claude + Higgsfield)

**Trigger:** `/generate-marketing <topic-or-title>`
(e.g. `/generate-marketing How I run 3 businesses with self-improving AI agents`)

**Input:** ONE string — a video title, hook, or topic. That's it.

This skill lives in the agency-side `/marketing` engine. It automates the DBS framework
and produces a **ready-to-refine draft** — it never publishes, boosts, or spends (same
propose→human-executes gate as Eco). Follow every step in order.

---

## Step 0 — Load context (mandatory, before any generation)

Read, in this order (do NOT skip — this is what prevents AI slop):
1. `marketing/claude.md`
2. `marketing/context/business_overview.md`
3. `marketing/context/pov.md`
4. `marketing/context/voice_guide.md`
5. `marketing/templates/thumbnail_template.md` and `marketing/templates/copy_template.md`

If a needed fact is missing from `/context`, tag it **[REFINE]** in the output — never
invent a metric, result, or claim.

---

## Step 1 — DESIGN (lock the angle)

From the input topic + `/context`:
- State the **ONE promise** this piece makes (one angle only — reject a second one).
- Pick which **POV / contrarian take** from `pov.md` it carries.
- Choose the real **UI evidence** that proves it (name the screenshot/asset from
  `assets/`; if none exists, tag **[REFINE — capture this screenshot]**).
- Fill the thumbnail master-prompt parameters from `thumbnail_template.md`:
  `{{title_text}}` (≤5 words), `{{ui_evidence}}`, `{{expression}}`, plus the brand-locked
  `{{brand_badge}}` / `{{accent_color}}` / `{{headshot_pose}}` (constant every time).

Output a short **DESIGN** block: the angle, the POV, the evidence, the filled parameters.

---

## Step 2 — BUILD (the draft)

- Assemble the **master prompt** from `thumbnail_template.md` (ready to paste — one job,
  image layout only, ≤80 words).
- Fill `copy_template.md`: title, thumbnail text (must match the image), hook, description
  ending on the real CTA, and 3 A/B alt titles.
- **Run the voice check** from `voice_guide.md` on all copy — strip banned words, kill
  hedging, confirm one promise, confirm every claim is real or **[REFINE]**-tagged.

Output a **BUILD** block: the master prompt + the filled copy block.

---

## Step 3 — SCALE (3 variations + repurpose)

**Higgsfield integration — check availability first:**
- If the **Higgsfield MCP** is active in this session → call `generate_image` with the
  master prompt at `1536x1536` (soul model), then twice more for the variations.
- Else if `HIGGSFIELD_API_KEY` is resolvable (via `../../../forge rei/higgsfield_io.py`;
  `agency.env` → `daycare.env`) → note it renders through the `soul` endpoint the same way.
- Else (no key) → **do not fabricate images.** Output the 3 filled prompts, ready to paste,
  and say the render step is pending a Higgsfield key (per the honesty rule).

Generate exactly **3 variations**, each changing **ONE** parameter (per
`thumbnail_template.md`'s Scale pass): A = expression/pose, B = UI-evidence, C =
composition/accent emphasis. Never change badge + font + accent together.

Then add the **repurpose** lines from `copy_template.md` — one adaptation per secondary
channel listed in `business_overview.md`.

Output a **SCALE** block: the 3 variation prompts (+ image URLs if rendered) and the
repurpose lines.

---

## Final output shape

```
DESIGN  — angle, POV carried, UI evidence, filled parameters
BUILD   — master prompt + copy block (voice-checked)
SCALE   — 3 variation prompts (+ images if key present) + repurpose lines
NEXT    — what I (the operator) should refine, and the one-tap action to publish
```

End by telling me exactly which **[REFINE]** items to finalize and which asset (if any) to
capture. Nothing is posted or boosted — I approve the final pick myself.

## Guardrails (inherited from FORGE `../../CLAUDE.md` §2)

- Propose, never publish/spend. This skill drafts only.
- Never invent proof, a metric, or a result. Real or **[REFINE]**.
- One promise per asset. One accent color, one badge, consistent headshot.
- Additive: write drafts as new files under `marketing/` (e.g. `marketing/drafts/`); never
  overwrite an existing draft — version it.
