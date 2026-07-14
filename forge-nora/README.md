# FORGE Nora — roster organizer & family follow-up

**Nora** keeps the daycare's roster organized and follows up on family
communications for **A Touch of Blessings** (the FORGE Daycare workspace). She
reports to Solomon and picks up his "Family-Comms" / "Enrollment" delegations.

## What she does
- Reads the live roster (Supabase `children`/`classrooms`) and flags gaps: missing
  guardian contact info, classroom capacity/ratio issues, new-enrollment setup
  work.
- Reads the Family Text Blast log (`daycare_blast.py`) and surfaces families who
  need a follow-up nudge — no response signal, opted-out/missing phone.
- Consumes Solomon's bus delegations addressed to `family-comms`/`enrollment`.
- **Self-improves** her operating playbook (`<vault>/Skills/nora-playbook.md`,
  git-committed) and reloads it on the next run.

## What she never does
Any outward or irreversible action. No SMS, no record write, no message send. She
proposes; a human taps to execute via the existing Blast/Messages tools.

## Layout
```
forge-nora/
├─ config/
│  ├─ nora.env          # real knobs + optional own key (git-ignored)
│  └─ nora.env.example  # committed template
└─ skills/
   ├─ nora-playbook.md        # seed operating rubric (merged with the vault copy)
   └─ nora-decision-loop.md   # seed — how she ranks roster vs. follow-up work
```

Engine: `forge rei/daycare_family.py`. Console: the **Nora · Family** tab in the
Daycare workspace. Routes: `/api/daycare/family/{status,brief,run,learn,bus}`.
Secrets stay in `config/*.env` (git-ignored, outside the web root, 404 over HTTP).
