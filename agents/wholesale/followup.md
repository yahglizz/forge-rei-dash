# Follow-up — Cadence

**Business:** Wholesale (REI) · **Emoji:** 🔁 · **Roster id:** `followup`
**Role:** no-response bumps + check-backs.

Every 30 minutes it scans seller threads that went quiet and drafts re-engage
bumps on the 24h / 72h / 7d tiers, plus any check-back that has come due. Drafts
go through Marcus's drafter and land as **Marcus proposals** you approve.

## Autonomy — where the line sits

**Proposals only.** The one exception is [autopilot.md](autopilot.md): when you
switch Autopilot on, routine re-engage bumps auto-send behind its gates.

It has no brain of its own — in chat and tasks, **Marcus answers for it** with its
live state as context.

## Where it lives

- **Engine:** `forge rei/followup.py` → `FollowupEngine`
- **State:** `marcus_state/followup.json` · heartbeat `followup`

## Routes

`/api/followup/status`

## Knobs

| Env | Default | Effect |
|---|---|---|
| `FORGE_FOLLOWUP_INTERVAL` | 1800 | Seconds between sweeps |
| `FORGE_FOLLOWUP_TIERS` | 24,72,168 | Bump tiers (hours) |
| `FORGE_CHECKBACK_MAX` | 3 | Max check-backs per thread |
