# Scout Skills Backlog — candidate capabilities to add over time

Brainstormed roadmap of skills/capabilities for Scout, the wholesale lead-triage
agent. Each is a candidate to build into the playbook or the scoring/queue
pipeline. Grouped by theme. None of these change the hard rule: Scout proposes,
humans approve, Marcus texts.

## Scoring intelligence
- **Momentum scoring** — Weight recent replies and reply-speed so a seller heating up this week outranks one who went quiet last month.
- **Distress-stacking multiplier** — Boost score nonlinearly when multiple distress triggers co-occur (e.g. foreclosure + vacant + behind on payments).
- **Sentiment & tone read** — Detect frustration, desperation, or relief in seller wording to refine motivation beyond keyword matching.
- **Price-realism check** — Compare the seller's asking number to a likely ARV range and flag "spread likely" vs "needs softening" automatically.
- **Tire-kicker detector** — Pattern-match repeated "I'll think about it" / endless questions with no commitment and quietly downgrade to nurture.

## Outreach timing
- **Best-time-to-call from message timestamps** — Infer a seller's active hours from when they text and recommend the call window most likely to connect.
- **Speed-to-lead SLA timer** — Track minutes since the seller's last message and escalate `asap` leads that are aging past a response threshold.
- **Cadence drift watcher** — Re-bucket warm leads to nurture (and back) as time passes since last contact, so the queue stays honest.
- **Quiet-hours guard** — Flag proposed contacts that would land outside legal/sensible texting hours for the lead's local timezone.

## Data enrichment
- **ARV cross-check via RentCast** — Pull comps/AVM for the property address to validate the price band and spread estimate.
- **Skip-trace gap flag** — Detect leads missing a verified phone/owner match and queue them for skip-trace before Marcus burns a touch.
- **Address & ownership parse** — Extract property address from the thread and confirm the texter is the owner of record.
- **Duplicate / cross-thread merge** — Spot the same seller across multiple GHL conversations or numbers and consolidate the triage.

## Collaboration with other agents
- **Handoff to Marcus with a pre-drafted reply** — Package a hot lead with a ready-to-send first reply (queued, not sent) so Marcus responds in one click.
- **Chief-of-Staff daily triage digest** — Roll up the day's asap/warm/dead counts and top leads into the orchestrator's brief.
- **Eco/Dyson enrichment requests** — Dispatch property or owner lookups to the data agents and fold results back into scoring.
- **Approval-queue annotations** — Attach the "why" and matched signals to each queued tag/move so the human approver decides in seconds.

## Learning
- **Learn from closed deals which signals converted** — Backtest past triage against deals that actually closed and re-weight the rubric toward what wins.
- **False-hot post-mortem loop** — When an `asap` lead dies, capture why and tighten the signals that over-scored it.
- **Vault-synced rubric evolution** — Write learned adjustments into the Obsidian brain (`Skills/scout-playbook.md`) so improvements persist and merge on the next sweep.
- **Per-market calibration** — Track how signals/price bands behave differently by market (e.g. Wilmington DE vs Ohio) and adapt thresholds per region.
