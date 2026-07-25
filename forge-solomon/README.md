# FORGE Solomon — the daycare's head agent

**Solomon** is the executive director agent for **A Touch of Blessings** (the FORGE
Daycare workspace). Persona: 50 years running childcare centers. He is the daycare's
ONE agent — Nora (roster + family comms) and Nova (ad ops) were merged into him on
2026-07-25, so the center runs on one brief instead of three.

## What he does
- Reads the whole center: live ops metrics + alerts (Supabase), billing, staffing,
  growth channels, connected-systems health (GHL / Stripe / Meta / Metricool), and
  the business brief (`forge-daycare/skills/daycare-context.md`, read FIRST).
- Also reads the **roster + classrooms** and the Family Text Blast log, and the
  **Meta campaign health + competitor read** for the enrollment ads.
- Produces ONE **prioritized operating brief**: Attention Now, Enrollment, Money,
  People, Roster, Follow-ups, Campaign health, Creative direction, Delegations.
- **Owns enrollment.**
- **Delegates** via the shared agent bus only what genuinely needs a human. He
  answers to every bus role he absorbed (solomon · family-comms · enrollment ·
  ads · growth · nora · nova), so an old delegation still lands.
- **Self-improves** his operating playbook (`<vault>/Skills/solomon-playbook.md`,
  git-committed) and reloads it on the next run.

## What he never does
Any outward or irreversible action. No SMS, invoice send, ad launch, or DB write.
He proposes + delegates; a human taps to execute. His only autonomous writes are
his own brain playbook and bus notes.

## Layout
```
forge-solomon/
├─ config/
│  ├─ solomon.env          # real knobs + optional own key (git-ignored)
│  └─ solomon.env.example  # committed template
└─ skills/
   ├─ daycare-evidence-discipline.md  # the CREED (outranks everything)
   ├─ solomon-decision-loop.md        # top skill — how he reasons, and closes the loop
   ├─ solomon-director-craft.md       # top skill — the 50 years of operating judgment
   ├─ solomon-roster-craft.md         # top skill — roster + family-comms lane (was Nora)
   ├─ solomon-adops-craft.md          # top skill — ad-ops lane (was Nova)
   └─ solomon-playbook.md  # seed operating rubric (merged with the vault copy)
```

Engine: `forge rei/daycare_director.py`. Console: the **Solomon · Director** tab in
the Daycare workspace. Routes: `/api/daycare/director/{status,brief,run,learn,bus}`.
Secrets stay in `config/*.env` (git-ignored, outside the web root, 404 over HTTP).
