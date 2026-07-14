# FORGE Nova — ad ops

**Nova** runs point on the daycare's ad ops for **A Touch of Blessings** (the
FORGE Daycare workspace): campaign health, competitor intel, and creative
direction, grounded in the real Meta account documented in
`forge-daycare/skills/enrollment-ad-agent.md`. She reports to Solomon and picks
up his "Ads" / "Enrollment" delegations.

## What she does
- Reads campaign health via `daycare_growth.ads_overview()` (live once
  `META_ACCESS_TOKEN` is set, honestly mock/not-connected until then).
- Reuses the existing daycare-scoped competitor research
  (`agency_eco._daycare_competitor`).
- Recommends which of the three live creative angles (Urgency/Trust/Offer) needs
  fresh creative and what to generate, grounded in `enrollment-ad-agent.md`'s
  real asset IDs, copy, and image-gen rules.
- Consumes Solomon's bus delegations addressed to `ads`/`enrollment`.
- **Self-improves** her operating playbook (`<vault>/Skills/nova-playbook.md`,
  git-committed) and reloads it on the next run.

## What she never does
Launch or activate a campaign, change budget, or generate a Higgsfield image
herself — the background loop has no tool access to Meta Ads Manager or
Higgsfield. She recommends; the owner (or a chat session with those tools) acts
on her delegation. Every spend action stays a one-tap owner approval.

## Layout
```
forge-nova/
├─ config/
│  ├─ nova.env          # real knobs + optional own key (git-ignored)
│  └─ nova.env.example  # committed template
└─ skills/
   ├─ nova-playbook.md        # seed operating rubric (merged with the vault copy)
   └─ nova-decision-loop.md   # seed — how she ranks ad-ops work
```

Engine: `forge rei/daycare_adops.py`. Console: the **Nova · Ad Ops** tab in the
Daycare workspace. Routes: `/api/daycare/adops/{status,brief,run,learn,bus}`.
Secrets stay in `config/*.env` (git-ignored, outside the web root, 404 over HTTP).
