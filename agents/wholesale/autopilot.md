# Autopilot — Re-engage Auto-send

**Business:** Wholesale (REI) · **Emoji:** 🛩️ · **Roster id:** `autopilot`
**Role:** opt-in auto-send of routine re-engage bumps.

When the operator switches it on, the re-engage bumps [followup.md](followup.md)
drafts are auto-sent — re-engage drafts only, legit-check verdict, daily cap,
9am–8pm ET, send-ledger dedupe, voice scrub, a Telegram receipt per send.

## Autonomy — where the line sits

**Off by default** (`CLAUDE.md` §2 exception). The Agent Control Center shows it
read-only and never toggles it.

It has no brain of its own — in chat and tasks, **Marcus answers for it**.

## Where it lives

- **Engine:** `forge rei/autopilot.py`
- **State:** `marcus_state/autopilot.json`

## Routes

`/api/autopilot/status` · POST `/api/autopilot/toggle`

## Knobs

| Env | Default | Effect |
|---|---|---|
| `FORGE_AUTOPILOT_CAP` | 10 | Max auto-sends per day |
