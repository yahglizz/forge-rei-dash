# FORGE Dropship — the e-commerce workspace

The **FORGE DROPSHIP** workspace is the operator's control center for the dropshipping /
e-commerce business, run with AI agents + Claude on top of **Shopify** and **AutoDS**
(Meta ads for paid traffic). Fourth workspace in FORGE REI OS, built on the same
self-improving-agent pattern as the daycare's Solomon.

## The crew

| Agent | Job | Autonomy |
|-------|-----|----------|
| **Midas** | Head e-com director. Reads the whole store (Shopify orders/products/inventory, AutoDS sourcing, Meta metrics, connected-systems health, the context brief FIRST) → ranked operating brief (Attention Now / Winners / Money / Ops / Delegations). Owns product strategy, delegates the rest. | Read-only. Proposes + delegates. Self-improves. |
| **Hawk** | Product research — scores product ideas, winner-hunting, trend + margin read. | Proposes only. Self-improves. |
| **Blaze** | Creative & ads — ad concepts + Meta campaign analysis (reuses the agency Meta engine via env-swap). | Recommends only; launches on approval. Self-improves. |
| **Otto** | Fulfillment & support ops — order/inventory/tracking health + drafts customer replies. | Never places supplier orders / messages customers without approval. Self-improves. |

## What the crew never does

Any outward or irreversible action: launching an ad, placing/approving a supplier order,
publishing/editing a Shopify listing, messaging a customer, changing spend/budget. They
propose + delegate; a human taps to execute. Their only autonomous writes are their own
brain playbooks and bus notes. Full autonomy rule: root `CLAUDE.md` rule 2.

## Layout

```
forge-dropship/
├─ config/
│  ├─ dropship.env          # real keys + knobs (git-ignored, 404 over HTTP)
│  └─ dropship.env.example  # committed template
├─ data/                    # local scratch (git-ignored)
└─ skills/
   ├─ dropship-context.md               # business brief — read FIRST (owner-edited)
   ├─ dropship-evidence-discipline.md   # the CREED (outranks the playbook)
   ├─ midas-decision-loop.md            # Midas top skill — how he reasons
   ├─ midas-craft.md                    # Midas top skill — e-com operating judgment
   ├─ midas-playbook.md                 # seed operating rubric (merged with vault copy)
   ├─ hawk-playbook.md                  # seed rubric — product research
   ├─ blaze-playbook.md                 # seed rubric — creative & ads
   └─ otto-playbook.md                  # seed rubric — fulfillment & support
```

Engines: `forge rei/dropship_director.py` (Midas) + `forge rei/dropship_agents.py`
(Hawk / Blaze / Otto). Integration clients: `forge rei/dropship_shopify.py`,
`forge rei/dropship_autods.py`. Console: the **FORGE DROPSHIP** workspace (profile
switcher). Routes: `/api/dropship/*`. Secrets stay in `config/*.env` (git-ignored,
outside the web root, 404 over HTTP).

## Cross-Agent Coaching Network

The dropship crew are nodes in the FORGE coaching network (`forge rei/agent_coach.py`).
They can **ask peers** questions and **broadcast a transferable insight** (a converting
creative angle, a fulfillment tactic) and absorb insights coached over from the agency /
REI / daycare agents — folded into the next `learn()` automatically. **Knowledge only** —
never creds, customer data, tokens, or an outward instruction; every outward action stays
approval-gated. Details: root `CLAUDE.md` §11.
