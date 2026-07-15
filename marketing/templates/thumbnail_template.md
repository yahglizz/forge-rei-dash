# Thumbnail Template — Master Prompt (parameterized for brand consistency)

> Reusable Higgsfield thumbnail format. The `/generate-marketing` skill fills the
> `{{parameters}}` from the input topic + `/context`, then renders 3 variations that change
> ONLY ONE parameter at a time so the brand stays recognizable.
>
> Renders via the shared Higgsfield **soul** endpoint (`../../forge rei/higgsfield_io.py`,
> `/v1/text2image/soul`, `1536x1536`). Higgsfield reads best from ONE prompt = ONE job, kept
> direct and under ~80 words.

---

## Brand-locked parameters (keep constant across every thumbnail)

| Parameter | Locked value | Notes |
|-----------|-------------|-------|
| `{{brand_badge}}` | **[REFINE — e.g. "FORGE" wordmark / ClientForge logo]** | Same badge, same corner, every time. From `assets/`. |
| `{{accent_color}}` | **[REFINE — pick ONE hex, e.g. electric blue `#2E7BFF`]** | The single pop color. One accent, never two. |
| `{{headshot_pose}}` | **[REFINE — e.g. "confident, half-turn, looking at camera, slight lean-in"]** | Consistent framing. Real headshot from `assets/` when possible. |
| `{{brand_font_vibe}}` | **[REFINE — e.g. "heavy geometric sans, tight tracking"]** | Title styling stays consistent. |
| `{{lighting}}` | Clean studio key + soft rim, dark background | Keeps subject popping the same way each time. |
| `{{aspect}}` | `16:9` (1536x1536 render, crop to 16:9) | [REFINE if primary is Shorts → `9:16`.] |

## Per-video parameters (change per piece — filled from the input topic)

| Parameter | Filled from | Example |
|-----------|-------------|---------|
| `{{title_text}}` | The video title/hook, compressed to ≤ 5 words | "I RUN 3 BUSINESSES WITH AI" |
| `{{ui_evidence}}` | The real screenshot/UI element that proves the claim | "the FORGE dashboard agent queue, approval taps visible" |
| `{{expression}}` | Match the emotional beat of the topic | "focused / mid-explain" |
| `{{prop_or_context}}` | Optional supporting visual | "phone showing a Telegram approval ping" |

---

## MASTER PROMPT (ready to paste / send to Higgsfield `generate_image`)

```
A confident founder, {{headshot_pose}}, {{expression}}, positioned on the right third of
the frame. On the left, clear {{ui_evidence}} shown on a floating screen as real UI
evidence. Bold {{title_text}} in a {{brand_font_vibe}} treatment, {{accent_color}} accent
on one key word. {{brand_badge}} in the top corner. {{lighting}}, dark clean background,
high contrast, crisp product-shot realism, sharp 4K, {{aspect}} composition.
```

**One job:** this is an IMAGE-layout prompt only — no camera motion, no identity edits
(per the Higgsfield "one prompt = one job" rule).

---

## Scale pass — the 3 variations (change ONE parameter each)

The skill generates exactly three, so I can pick the strongest without brand drift:

1. **Variation A — expression/pose swap.** Same layout, change `{{expression}}` /
   `{{headshot_pose}}` (e.g. neutral-authoritative vs. mid-explain vs. surprised-at-result).
2. **Variation B — UI-evidence swap.** Same subject/title, change `{{ui_evidence}}` to a
   different real proof screen (dashboard vs. a metric card vs. the Telegram ping).
3. **Variation C — composition/accent emphasis.** Same everything, flip subject to the left
   / UI to the right, or shift which word carries the `{{accent_color}}`.

> Never change badge, font vibe, and accent color together in one variation — that's a
> different brand, not a variation.

## Pre-render checklist

- [ ] Title ≤ 5 words, passes `voice_guide.md` (no banned words).
- [ ] `{{ui_evidence}}` is REAL (from `assets/` or a real screenshot), not invented.
- [ ] Exactly one accent color, one badge, consistent headshot treatment.
- [ ] If no Higgsfield key is present: output the 3 filled prompts and STOP (don't claim
      an image was made).
