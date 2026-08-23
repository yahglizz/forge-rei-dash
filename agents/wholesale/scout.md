# Scout — Lead Triage

**Business:** Wholesale (REI) · **Emoji:** 🔍 · **Roster id:** `scout`
**Role:** finds, ranks, organizes every seller reply.

Scores motivation on each inbound seller message, buckets it
(`asap` / `warm` / `nurture` / `dead`), tags and stages it, flags the hot ones,
and hands call-worthy leads to Marcus automatically. Also runs a weekly
missed-leads audit over full threads to surface leads that went cold with real
signal still in them.

## Autonomy — where the line sits

| Does on its own | Needs your tap |
|---|---|
| Score + bucket every reply | Any SMS (Marcus owns texting — Scout never sends) |
| **Auto-tag HOT leads** in GHL (`triage: asap`, `motivated: high`) | Warm/nurture tags |
| **Auto-stage HOT leads** into the Wholesaling Pipeline Hot stage | Any other pipeline move |
| Auto-handoff `asap`/`warm` to Marcus for screening | — |
| Rewrite its own playbook, post on the bus | — |

The two HOT exceptions are deliberate: tags and stage moves are **internal and
reversible** (the "✕ Not hot" button undoes them). Kill either with
`FORGE_SCOUT_AUTOTAG_HOT=0` / `FORGE_SCOUT_AUTOPIPE_HOT=0`.

## Where it lives

- **Engine:** `forge rei/scout_triage.py` → `ScoutEngine`, built at `forge rei/connector.py:1132`
- **Config + seed skills:** `forge-scout/`
- **Creed:** `wholesale-evidence-discipline.md` — the thread is the only truth; never invent what a seller said; never invent a number
- **Skills loaded:** `scout-playbook.md`, `wholesale-context.md`
- **Learned playbook:** vault `Skills/scout-playbook.md` (rewritten by `learn()`)

## Routes

`/api/scout/` — `summary` · `leads` · `overview` · `pipeline` · `run` · `apply` ·
`dismiss` · `remove` · `backfill` · `handoff` · `learn` · `audit` · `audit/run`

## Knobs

| Env | Default | Effect |
|---|---|---|
| `FORGE_SCOUT_INTERVAL` | 180 | Sweep cadence (seconds). The money loop — leave hot. |
| `FORGE_SCOUT_LEARN_EVERY` | 25 | Self-improve after N new encounters |
| `FORGE_SCOUT_AUTOTAG_HOT` | 1 | Auto-tag hot leads in GHL |
| `FORGE_SCOUT_AUTOPIPE_HOT` | 1 | Auto-stage hot leads |
| `FORGE_SCOUT_AUDIT_*` | — | Weekly missed-leads audit depth |

Runs only where `FORGE_MARCUS=1` (the box), so the Mac never double-contacts sellers.
