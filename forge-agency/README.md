# Forge AI Agency — private config home

This folder is the **AI Agency's** own home, kept fully **separate from wholesale**.
It is a sibling of the web app folder (`forge rei/`), so nothing in here is ever
served over HTTP — keys live here safely.

```
forge rei dash/
├─ forge rei/                 <- the dashboard (web-served)
├─ marcus-wholesale-agent/    <- WHOLESALE config (its own keys)
└─ forge-agency/              <- THIS folder: AGENCY config (its own keys)
   ├─ config/
   │  ├─ agency.env           <- REAL keys (private, never committed/served)
   │  └─ agency.env.example   <- template; copy values into agency.env
   ├─ scripts/                <- agency-only scripts (empty for now)
   └─ data/                   <- agency-only data files (empty for now)
```

## Where the app reads these keys

| System                | Path it loads                                            |
|-----------------------|---------------------------------------------------------|
| `connector.py`        | `AGENCY_ENV_CANDIDATES[0]` → `../forge-agency/config/agency.env` |
| `deploy/push.sh`      | rsyncs `config/agency.env` → box `/opt/forge/forge-agency/config/` |

The agency uses a **separate GoHighLevel sub-account** from wholesale. The two
never share a key file. Put wholesale keys in `../marcus-wholesale-agent/` only.

## Add or change a key

1. Open `config/agency.env`
2. Add a line: `KEY_NAME=value`
3. Restart the connector (local) or run `deploy/push.sh` (box) so it reloads.

## Current keys in agency.env

- `GHL_API_KEY`, `GHL_LOCATION_ID` — agency GHL sub-account (set ✅)
- `ANTHROPIC_API_KEY` — agency's own Claude key (set ✅)
- `RETELL_API_KEY` — agency voice (blank; add when you launch a caller)
