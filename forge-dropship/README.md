# FORGE Dropship — the e-commerce workspace

The **FORGE DROPSHIP** workspace is the operator's control center for the dropshipping /
e-commerce business, run with AI agents + Claude on top of **Shopify** and **AutoDS**
(Meta ads for paid traffic). Fourth workspace in FORGE REI OS, built on the same
self-improving-agent pattern as the daycare's Solomon.

## The agent

**Midas** — head e-com director, one agent running three lanes. Hawk, Blaze and Otto were
merged into him on 2026-07-25: for a store this size, three more playbooks and three more
`learn()` loops bought separation of concerns and nothing else.

| Lane | Job | Autonomy |
|------|-----|----------|
| **Daily brief** | Reads the whole store (Shopify orders/products/inventory, AutoDS sourcing, Meta metrics, connected-systems health, the context brief FIRST) → ranked operating brief (Attention Now / Winners / Money / Ops / Ads / Delegations). | Read-only. Proposes. Self-improves. |
| **Product research** (`research`, `watch_score`) | Scores product ideas + the watchlist on margin headroom, demand signal, ad-ability, fulfillment sanity, saturation. 1–10 upside read per watched product. | Never sources/lists/spends. Proposes only. |
| **Creative & ads** (`meta_overview`, `analyze_ads`) | Meta campaign read → scale/hold/kill/refresh + fresh ad concepts. Reuses the agency Meta engine under a locked per-call env-swap. | Never launches or changes budget. Recommends + drafts. |
| **Fulfillment & support** (`fulfillment_check`) | Order/inventory/tracking health + drafts customer replies. | Never places supplier orders / messages customers. Flags + drafts. |

## What Midas never does

Any outward or irreversible action: launching an ad, placing/approving a supplier order,
publishing/editing a Shopify listing, messaging a customer, changing spend/budget.
He proposes; a human taps to execute. His only autonomous writes are his own
brain playbook and bus notes. Full autonomy rule: root `CLAUDE.md` rule 2.

## Layout

```
forge-dropship/
├─ config/
│  ├─ dropship.env          # real keys + knobs (git-ignored, 404 over HTTP)
│  └─ dropship.env.example  # committed template
├─ data/                    # local scratch (git-ignored)
├─ products/
│  └─ the-sunday-set.md     # real product packet (first live listing)
├─ scripts/                 # get-shopify-token.mjs / .py — one-off admin-token helpers
├─ EVERALY_STORE.md         # store/dashboard wiring notes
├─ PLUG_AND_PLAY.md         # setup guide (cross-references DROPSHIP_CHECKLIST.md)
├─ README.md                # this file
└─ skills/                  # 11 skills — always-on (3) + lane-gated (7) + on-demand (1)
   ├─ dropship-context.md               # business brief — read FIRST (owner-edited)
   ├─ dropship-evidence-discipline.md   # the CREED (outranks the playbook)
   ├─ midas-decision-loop.md            # always-on — how he reasons
   ├─ midas-craft.md                    # always-on — e-com operating judgment
   ├─ dropship-account-health.md        # always-on — chargeback/refund bands, ban survival
   ├─ dropship-adspy-method.md          # lane: product research + creative & ads — competitor ad research (Ad Library + PiPiAds)
   ├─ dropship-four-triggers-ad-writer.md    # lane: creative & ads — ad-copy framework (was Blaze's)
   ├─ dropship-meta-ads-diagnostician.md     # lane: creative & ads — the 12 sliders (was Blaze's)
   ├─ dropship-ad-launch-sop.md         # lane: creative & ads — test/scale/kill numbers for Meta
   ├─ dropship-creative-testing-doctrine.md      # lane: creative & ads — what goes in the test queue, why a winner died
   ├─ dropship-account-optimization-doctrine.md  # lane: creative & ads — act-or-wait restraint, account structure/scaling
   ├─ dropship-support-macros.md        # lane: fulfillment & support — approved support language + refund tree
   ├─ dropship-store-setup.md           # on-demand (chat only) — Shopify build, CRO, AOV, pixel/CAPI
   └─ midas-playbook.md                 # seed operating rubric + the three lane sections
                                        #   (absorbed hawk/blaze/otto-playbook.md)
```

The 8 `dropship-*` SOPs (minus the creed + context) are operating references, not top
skills — they load through `_load_skills()` only once declared in
`MidasEngine.TOP_SKILLS`/`LANE_SKILLS`/`ON_DEMAND_SKILLS`
(`forge rei/dropship_director.py`). Self-check that every skill file reaches a prompt and
none are orphaned: `cd "forge rei" && python3 test_dropship_skills.py`.

Engine: `forge rei/dropship_director.py` (Midas — all lanes). Integration clients:
`forge rei/dropship_shopify.py`,
`forge rei/dropship_autods.py`. Console: the **FORGE DROPSHIP** workspace (profile
switcher). Routes: `/api/dropship/*`. Secrets stay in `config/*.env` (git-ignored,
outside the web root, 404 over HTTP).

## Cross-Agent Coaching Network

Midas is a node in the FORGE coaching network (`forge rei/agent_coach.py`).
He can **ask peers** questions and **broadcast a transferable insight** (a converting
creative angle, a fulfillment tactic) and absorb insights coached over from the agency /
REI / daycare agents — folded into the next `learn()` automatically. **Knowledge only** —
never creds, customer data, tokens, or an outward instruction; every outward action stays
approval-gated. Details: root `CLAUDE.md` §11.
