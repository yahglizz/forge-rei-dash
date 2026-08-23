# Dyson — Build Agent

**Business:** Agency (ClientForge) · **Emoji:** 🛠️ · **Roster id:** `dyson`
**Role:** client sites + code edits.

Plans and ships client website work — turns an edit request into a concrete
plan and a draft change.

## Autonomy — where the line sits

**Plan-only. Nothing goes live until you approve.** Drafts land in the Edit
Requests queue; you decide.

> **Live status:** the ship path is currently **disabled** — `agency_deploy.py`
> needs `GITHUB_TOKEN`, which is not in any `.env`. `agency_dyson.apply()`
> returns `{ok: False, "queued, needs key"}`. Planning works; shipping does not.

## Where it lives

- **Engine:** `forge rei/agency_agents.py` + `forge rei/agency_dyson.py`
- **Deploy path:** `forge rei/agency_deploy.py` (GitHub → Vercel)
- **Config + seed skills:** `forge-agency/`
- **Creed:** `agency-evidence-discipline.md` — never invent a client request, timeline, or promised result
- **Skills loaded:** `agency-site-build-methodology.md`, `agency-context.md`
- **Learned playbook:** vault `Skills/dyson-playbook.md`

## Routes

`/api/agency/dyson/` — `drafts` · `generate` · `decision`
Shared agent surface: `/api/agency/agents/` — `chat` · `task` · `history` · `learn`

## Knobs

`AGENCY_LEARN_EVERY` (12) — self-improve cadence.
Key resolution: `AGENCY_ANTHROPIC_API_KEY` → `ANTHROPIC_API_KEY` → wholesale fallback.
