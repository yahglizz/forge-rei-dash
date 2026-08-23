# Eco — Ads Agent

**Business:** Agency (ClientForge) · **Emoji:** 📈 · **Roster id:** `eco`
**Role:** ad strategy, Meta performance reads, creative concepts.

Reads campaign performance, diagnoses what is actually leaking, and drafts new
angles and creative. Also generates ad imagery through Higgsfield.

## Autonomy — where the line sits

**Recommends only. Launches on approval.** Spend is never Eco's to commit.

## Where it lives

- **Engine:** `forge rei/agency_agents.py` + `forge rei/agency_eco.py`
- **Meta data:** `forge rei/agency_ads.py` · **Imagery:** `forge rei/higgsfield_io.py`
- **Config + seed skills:** `forge-agency/`
- **Creed:** `agency-evidence-discipline.md` — every CPL/ROAS/spend figure carries its source **and date range**, or is Unknown; mock channels are labeled as mock
- **Skills loaded:** `agency-four-triggers-ad-writer.md`, `agency-marketing-methodology.md`, `agency-icp.md`, `agency-context.md`
- **Learned playbook:** vault `Skills/eco-playbook.md`

## Routes

`/api/agency/eco` · `/api/agency/eco/` — `generate` · `decision` · `image` · `competitor`

Eco's engine is also reused by the daycare under its own credentials (a locked
env-swap in `daycare_growth.py`) to power `/api/daycare/eco/ideas`. Agency output
is unchanged by that reuse — `extra_context` is empty for the agency.

> **Live status:** the agency's Meta and Metricool tabs are **mock**. `agency.env`
> has no `META_ACCESS_TOKEN`, no `META_AD_ACCOUNT_MAP`, and no
> `METRICOOL_USER_TOKEN`, and `connector.py:199` deliberately isolates those
> prefixes so the agency can never inherit another business's token. Three env
> lines turn both tabs real.
