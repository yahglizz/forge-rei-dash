# /marketing — Project Instructions (Claude + Higgsfield Automated Marketing System)

**This is the agency-side (ClientForge) marketing engine.** It turns a single input —
a video title, hook, or topic — into on-brand thumbnails + copy without producing
"AI slop." Read this file, then `/context`, before generating anything.

> Additive by design. Nothing here edits or removes existing FORGE code. It plugs into
> the agency workspace and the SHARED Higgsfield integration (`../forge rei/higgsfield_io.py`).

---

## Read order (never skip — this is what keeps output on-brand)

1. `context/business_overview.md` — who I am, the offer, the goal of the content.
2. `context/pov.md` — my actual views + contrarian takes. Content must carry these.
3. `context/voice_guide.md` — the anti-AI rules, banned words, and how I write.
4. `templates/` — the reusable format for whatever is being produced (thumbnail, copy).
5. THEN generate. Every draft is checked back against `voice_guide.md` before it's shown.

If a fact isn't in `/context` and can't be grounded, mark it **[REFINE]** and move on —
never invent a metric, a claim, or a result. (Same evidence discipline as the FORGE creed:
`../forge-agency/skills/agency-evidence-discipline.md`.)

---

## The DBS framework (Design → Build → Scale)

Every generation runs these three passes. The `/generate-marketing` skill automates them.

- **DESIGN** — read `/context`, lock the ONE angle for this piece (the promise the
  thumbnail/copy makes), pick the template, and fill the master-prompt parameters
  (badge, title, accent color, UI evidence, headshot pose).
- **BUILD** — produce the draft: a ready-to-paste Higgsfield image prompt + the matching
  copy (title/hook/description), grounded in `/context`, checked against the voice guide.
- **SCALE** — generate **3 image variations** off the master prompt (varying only ONE
  parameter at a time so the brand stays consistent), and give repurpose-ready copy for
  the other channels. Nothing is published — these are drafts for me to pick and refine.

---

## Higgsfield wiring (already live in this repo)

The dashboard's ad agents (Eco, Nova) generate images through **one shared Higgsfield
account** via `../forge rei/higgsfield_io.py`:

- Endpoint: `/v1/text2image/soul` (the verified working "soul" text2image path).
- Default size `1536x1536`, quality `1080p`.
- Key: `HIGGSFIELD_API_KEY` (+ `HIGGSFIELD_API_SECRET`), resolved from
  `../forge-agency/config/agency.env` (or `daycare.env` — one paste serves every agent).

Two ways this system can render:
1. **Higgsfield MCP active** (in a Claude session): call `generate_image` directly.
2. **Higgsfield CLI / `higgsfield_io.py`**: same key, same soul endpoint. If no key is
   present, the skill returns the ready-to-paste prompts and stops before rendering
   (never claims an image exists that doesn't — see the voice guide's honesty rule).

---

## Hard rules (inherited from FORGE `../CLAUDE.md` §2)

- **Propose, don't publish.** This system drafts. Posting/boosting/spending stays a
  human one-tap action — same gate as Eco's ad launches.
- **Never invent a number or a claim.** Real proof or **[REFINE]** — never filler.
- **Additive only.** Don't remove or overwrite existing marketing files; version them.
- **Secrets stay in `*.env` outside the web root.** Never paste a key into any file here.
- **Assets are real.** Logos/headshots come from `assets/`, not generated stand-ins,
  unless I explicitly ask for a generated placeholder.
