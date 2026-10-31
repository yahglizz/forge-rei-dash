# Agency Instagram: the tools you have (stable floor, not learned)

You (Dyson, Eco) can use these for the AGENCY's Instagram only. Facts here are verified; anything marked Unknown is not a fact.

## Whose account

- Instagram: **`@forgelabsphiladelphia`** (id `17841464279234508`, "Forge Labs | Graphic & Software Designer"). Agency ad account: **`act_2344043939684594`**.
- The daycare (A Touch of Blessings / A Mother's Touch) is a **different business** with a different Instagram, Page and ad account. Never use, mention or borrow its ids, its Page `939494549239823`, or its Instagram. Pass the exact `account_id` on every Meta/Pipeboard call; never rely on a default. Full table: `docs/META_ACCOUNTS.md`.
- Agency Facebook Page: **Unknown, none exists yet.** Say so; do not substitute the daycare's.
- Metricool brand `forgelabsx` is the agency's posting tool. As of 2026-10-31 it shows TikTok only, so Instagram is **not yet linked there** and `METRICOOL_USER_TOKEN` is empty. Until both are fixed, nothing can be published from the dashboard and analytics are mock. Check `GET /api/agency/instagram` (`metricool.instagramLinked`, `metricool.source`) instead of assuming.

## What you can run (stdlib tools, no network, nothing leaves the box)

`POST /api/agency/instagram/tool` with `{"tool": <name>, "text": <input>}`. It is read-only: no network, no writes.

| tool | input | gives you |
|---|---|---|
| `hook` | hooks, one per line | each hook scored on 5 properties + dealbreakers (greeting, "stop scrolling") |
| `beats` | a Reel script (+ `wpm`, `target` seconds) | timed beat sheet; flags a slow hook, long beats, no loop |
| `caption` | a caption (+ `keywords`) | what the feed shows before "... more" (first 125 chars), lint |
| `humanize` | a draft | the draft with em dashes, slop words and invisible watermark characters stripped, plus a report |
| `detect` | a draft | how machine-written it reads (burstiness, specificity, slop, fingerprint, voice) |
| `swipe` | TSV with header `account followers median views hook` | reels ranked by multiple over each account's own baseline, with the hook formula named |

`POST /api/agency/instagram/draft` with `{"text", "keywords"}`: humanizes, lints, scores, then saves an Instagram **draft** in the Social queue. It never marks anything Ready or posted.

## The skills behind them (`forge-agency/instagram/skills/`)

`/ig-reel` (Reel from one idea, 26 hook formulas), `/ig-viral` (what is working in a niche), `/ig-caption`, `/ig-carousel`, `/ig-story`, `/ig-profile` (score out of 100), `/ig-plan` (the week), `/ig-human`, `/ig-comment`, `/ig-reply`, `/ig-dm`, `/ig-repurpose`, `/ig-audit`. Voice: `forge-agency/instagram/voice.md` (many answers still Unknown). Runtime notes (swipe file, log, plan): `forge-agency/data/instagram/`.

## Rules

1. **Nothing posts without the owner.** Write a draft, say it is a draft, and stop. Ready -> Approval Center -> Metricool is the owner's tap (CLAUDE.md rule 2). No DMs, comments or replies are sent by these tools either.
2. **Run `humanize` on every caption, hook and script before showing it.** Show the owner the humanized text.
3. **Never invent proof.** The agency has no clients, results or testimonials yet; leave `{{your number}}` where proof would go. Price is only what `agency-offer-sheet.md` says.
4. If a tool errors, show the error and say it failed. Do not reconstruct its output from memory.
5. Say Unknown for the voice answers the owner has not given (`voice.md`); do not guess a voice.

Source and licence of the tools: `forge-agency/instagram/VENDOR.md` (MIT).
