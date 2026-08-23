# Atlas — Deal Underwriter

**Business:** Wholesale (REI) · **Emoji:** 📐 · **Roster id:** `atlas`
**Role:** the numbers.

Underwrites every screened-interested seller: pulls facts out of the thread,
derives offer anchors (open / target / walkaway) **from the seller's own stated
ask**, spells out the MAO math and which comps to pull, and writes the
negotiation call card. Auto-preps every 15 minutes.

## Autonomy — where the line sits

**Atlas contacts no one, ever.** It reports to Marcus and writes to the brain.

Its numbers are **internal**. An anchor is a figure for you to hold on a call —
it is never sent to a seller, and the no-price-by-text rule in
[marcus.md](marcus.md) covers anything Atlas produces.

## Where it lives

- **Engine:** `forge rei/deal_prep.py`
- **Config + seed skills:** `forge-marcus/` (shares Marcus's folder)
- **Creed:** `wholesale-evidence-discipline.md` — **no agent ever invents a number**; an anchor traces to the seller's stated ask or it is Unknown
- **Skills loaded:** `atlas-underwriter.md`, `marcus-critical-thinking.md`

## Routes

`/api/prep/` — `list` · `get` · `run` · `status` · `learn`

## Knobs

| Env | Default | Effect |
|---|---|---|
| `FORGE_ATLAS_LEARN_EVERY` | 12 | Self-improve cadence |
| `FORGE_ATLAS_LEARN_GAP_MIN` | — | Rate-limit between reflections |
| `FORGE_PREP_AUTO` / `FORGE_PREP_MSGS` / `FORGE_PREP_SWEEP_CAP` | — | Auto-prep sweep behavior |
