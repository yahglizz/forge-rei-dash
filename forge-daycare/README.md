# Forge Daycare — "A Touch of Blessings" config + Supabase schema

> **Website work moved out (2026-08-11).** The marketing site, family forms, brand kit, and
> web deploy docs now live in `~/Desktop/A Touch of Blessings — Brand Kit/`. Edit the site
> from there. `skills/daycare-context.md` + `skills/enrollment-ad-agent.md` here stay the
> LIVE copies the agents load — the brand-kit `context/` copies are mirrors; sync changes back.

This folder is the Daycare business's own home, a sibling of the dashboard
(`forge rei/`), so nothing in here is ever served over HTTP — config, business
context, and the Supabase schema live here safely.

Unlike Scout/Marcus/Solomon/Midas, this folder holds no agent engine of
its own — the engines (`daycare_supabase.py`, `daycare_growth.py`,
`daycare_blast.py`, `daycare_ghl.py`, `daycare_context.py`, plus Solomon) all
live in `forge rei/`. This folder is what they read from: the
business's own credentials, its brief, and the database schema those engines
talk to.

```
forge rei dash/
├─ forge rei/                 <- the dashboard (web-served; every daycare_*.py engine lives here)
├─ forge-solomon/             <- Solomon (daycare head agent) config + seed playbook
└─ forge-daycare/             <- THIS folder: business config + brief + Supabase schema
   ├─ config/
   │  └─ daycare.env.example  <- template; copy to daycare.env and edit (git-ignored)
   ├─ skills/
   │  ├─ daycare-context.md       <- the business brief every daycare AI task reads FIRST
   │  └─ enrollment-ad-agent.md   <- the real Meta ad account/campaign/creative spec
   └─ supabase/
      ├─ migrations/          <- schema change-control (byte-identical source of truth,
      │                           see supabase/README.md for the verification contract)
      ├─ functions/           <- edge functions (e.g. provision-user)
      └─ snapshots/           <- point-in-time schema/function backups before a hardening pass
```

## What each file does

| File | Purpose |
|---|---|
| `config/daycare.env` | Real runtime config: Supabase project URL/keys, the daycare's own GHL sub-account, Stripe key, Meta/Metricool tokens (blank = mock). **Git-ignored.** |
| `config/daycare.env.example` | Safe-to-commit template of the same keys; copy to `daycare.env`. |
| `skills/daycare-context.md` | The business brief — mission, locations, current status, brand voice, standing job. Read FIRST by every daycare AI path via `daycare_context.py`. |
| `skills/enrollment-ad-agent.md` | The live ad-ops runbook: real Meta account/page/lead-form/campaign IDs, ad copy, image prompts, targeting, the Higgsfield→Pipeboard workflow. |
| `supabase/migrations/` | Schema change-control — kept **byte-identical** to the separate parent/staff app's migrations (see `supabase/README.md`). Not applied automatically; changes are reviewed. |
| `supabase/functions/` | Edge functions (e.g. `provision-user`, used by `daycare_supabase.save_child` to mint a new guardian profile). |

## Where the business brief lives

`daycare_context.py` (`forge rei/`) reads `skills/daycare-context.md` and
`skills/enrollment-ad-agent.md` from this folder, mtime-hot-reloaded — edit
either file directly and the next agent run picks it up, no restart. There is
no vault copy of these two files (unlike agent playbooks); the owner edits
them here, directly, and commits.

## Secrets

Real config and keys live only in `config/daycare.env`, **git-ignored**
(`*.env`, matched by the root `.gitignore`'s global pattern — this folder has
no folder-level `.gitignore` of its own, unlike its sibling agent folders,
since the root pattern already covers it). Only `daycare.env.example` is
committed. This folder is OUTSIDE the web-served dir, so nothing here is
reachable over HTTP. Do not paste real keys into the example or any committed
file.

## Who reads this folder

Solomon (`daycare_director.py`) reads `daycare-context.md` and
`enrollment-ad-agent.md` ahead of his creed and playbook; his role includes the
former roster/family-comms and ad-ops lanes — see
`NORTH_STAR.md` §6 for the full brains-and-skills map across every business.
