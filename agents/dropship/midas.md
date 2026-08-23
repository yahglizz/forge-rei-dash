# Midas — E-com Director

**Business:** Dropship (FORGE) · **Emoji:** 🛒 · **Roster id:** `midas`
**Role:** runs the whole store.

Reads it all — Shopify, AutoDS, Meta, and the business brief **first** — and
produces one ranked operating brief: Attention Now / Winners / Money / Ops / Ads /
Delegations. Plus three on-demand lanes: **product research**, **creative & ads**,
**fulfillment & support**.

## Autonomy — where the line sits

**Never acts outward.** No launch, no budget change, no supplier order, no listing
edit, no customer message, no refund. Proposals only.

## Prompt order (highest wins)

1. **Creed** — `dropship-evidence-discipline.md`: never invent a metric, margin, stock status, supplier price, or delivery time; margin only from real cost inputs; **account health outranks the analysis**
2. **Always on** — `midas-decision-loop.md`, `midas-craft.md`, `dropship-account-health.md`
3. **Lane-gated** — loaded only by the lane that consults them:

| Lane | Skills added |
|---|---|
| product research | `dropship-adspy-method` |
| creative & ads | `dropship-four-triggers-ad-writer`, `dropship-creative-testing-doctrine`, `dropship-account-optimization-doctrine`, `dropship-meta-ads-diagnostician`, `dropship-ad-launch-sop`, `dropship-adspy-method` |
| fulfillment & support | `dropship-support-macros` |

4. Learned `midas-playbook.md` — **last**

**Do not un-gate the lane skills.** They are ~13–15KB each; declaring all of them
always-on costs ~24k tokens on *every* call, and the scheduled brief runs
unattended forever. Gated, the brief carries ~12.5k and each lane gets exactly its
own. Operator chat is deliberately **not** gated — a human question is bursty and
can be about any lane.

Enforcement: `forge rei/test_dropship_skills.py` fails if a skill is on disk but
unreachable from every prompt path, if the creed leaks into `_load_skills`, or if
a top skill lands in `learn()`'s budget.

```bash
cd "forge rei" && python3 test_dropship_skills.py
```

## Where it lives

- **Engine:** `forge rei/dropship_director.py` → `MidasEngine`, built at `forge rei/connector.py:1035`
- **Integrations:** `dropship_shopify.py` · `dropship_autods.py` · `dropship_adspy.py` · `dropship_winninghunter.py` · `dropship_pipiads.py`
- **Config + seed skills:** `forge-dropship/`
- **Learned playbook:** vault `Skills/midas-playbook.md` (`PLAYBOOK_MD` at `dropship_director.py:341`)

## Routes

`/api/dropship/director/` — `status` · `overview` · `brief` · `run` · `learn` · `bus`
Also `/api/dropship/` — `agents` · `analytics` · `ads` · `adspy/*` · `autods/*`

## Knobs

| Env | Default | Effect |
|---|---|---|
| `FORGE_DROPSHIP_BRIEF` | **0 (off)** | Scheduled brief. Off while the store is part-wired — a brief over empty data is fabrication *and* a daily bill. On-demand is unaffected. Set `1` when Shopify is connected. |
| `FORGE_DROPSHIP_BRIEF_EVERY_H` | — | Brief cadence when on |
| `FORGE_DROPSHIP_LEARN_EVERY` | — | Self-improve cadence |
| `FORGE_DROPSHIP_BRIEF_TOKENS` | — | Brief token budget |

> Switching a loop off must call `forge_heartbeat.retire("<loop>")` in the else
> branch, or it stops beating, goes red forever, and trips the health card.
