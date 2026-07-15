# Copy Template — Title / Hook / Description (matches the thumbnail)

> Reusable copy format so every piece ships with thumbnail + copy that make the SAME one
> promise. Filled from the input topic + `/context`, checked against `voice_guide.md`.

---

## Parameters

| Parameter | Filled from | Rule |
|-----------|-------------|------|
| `{{angle}}` | The ONE promise this piece makes | One angle only. |
| `{{proof}}` | The real UI/number that backs the angle | Real or **[REFINE]** — never invented. |
| `{{cta}}` | The offer's next step (`business_overview.md`) | One action, action-first. |

## Output block (the skill fills this)

```
TITLE (≤ 60 chars, one promise, no banned words):
{{title}}

THUMBNAIL TEXT (≤ 5 words, matches the image):
{{thumb_text}}

HOOK (first line works with zero context):
{{hook}}

DESCRIPTION / CAPTION (2–4 short lines, {{proof}} named, ends on {{cta}}):
{{description}}

3 ALT TITLES (for A/B — same angle, different wording):
1. {{alt_1}}
2. {{alt_2}}
3. {{alt_3}}

REPURPOSE (Scale pass — one-line adaptation per secondary channel):
- [REFINE channel]: {{repurpose_line}}
```

## Voice check before showing

- [ ] ONE promise, matches the thumbnail.
- [ ] Every claim real or **[REFINE]**-tagged.
- [ ] Zero banned words (`voice_guide.md`).
- [ ] Sounds like me, not default AI.
