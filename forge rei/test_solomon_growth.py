"""Solomon is growth-only (2026-09-30). Guards the growth focus + the seat math.

Run: cd "forge rei" && python3 test_solomon_growth.py   (exit 1 on failure)
"""
import inspect

import daycare_director as dd

# Seats: openSeats only from real numbers — None (Unknown), never a fake 0 or vacancy.
assert dd._seat_row({"capacity": 18, "enrolled": 14})["openSeats"] == 4
assert dd._seat_row({"capacity": 10, "enrolled": 12})["openSeats"] == 0
assert dd._seat_row({"capacity": 18, "enrolled": None})["openSeats"] is None
assert dd._seat_row({"capacity": None, "enrolled": 3})["openSeats"] is None

# Chat Solomon runs on the same top skills as the brief (was playbook-only).
skills = dd.top_skills_text()
assert "Growth Craft" in skills, "growth craft missing from Solomon's top skills"
assert "Seats & Retention" in skills, "seats craft missing from Solomon's top skills"
assert "Evidence Discipline" not in skills, "creed leaked into _load_skills — learn() could rewrite it"

# The brief prompt is growth-first: no paperwork lane, no retired role agents.
src = inspect.getsource(dd.SolomonEngine.build_brief)
assert "Paperwork is NOT your lane" in src
assert "Compliance)" not in src and "Billing, Family-Comms" not in src
assert "startsDesk" in src, "Starts lane not fed to the brief"
assert "missingGuardianContact" not in inspect.getsource(dd.SolomonEngine._gather_roster)

# The creed keeps the evidence rails the Reply Desk depends on.
import agent_creed
creed = agent_creed.block("daycare")
for rail in ("An open seat", "A start date", "Tuition, a rate", "What a family said", "Never act outward"):
    assert rail in creed, f"creed lost rail: {rail}"

# Starts desk summary never raises.
assert isinstance(dd.starts_desk_state(), dict)
print("ok — Solomon growth focus holds")

# Age math for seat forecasting (months, day-of-month aware; junk → None).
import datetime
assert dd._age_months("2025-01-15", datetime.date(2026, 9, 30)) == 20
assert dd._age_months("2025-01-31", datetime.date(2026, 9, 30)) == 19
assert dd._age_months(None) is None and dd._age_months("garbage") is None
assert dd._seat_row({"capacity": 8, "enrolled": 6}, [11, 4])["agesMonths"] == [4, 11]
print("ok — seat forecasting data holds")

# learn() drift guard: a rewrite that slides back into paperwork is rejected.
assert dd._paperwork_drift("- Chase overdue invoices weekly\n- Audit staff clearances before tours\n")
assert not dd._paperwork_drift("- Licensing and invoices are not your lane.\n- Call leads in 15 min.\n")
assert not dd._paperwork_drift("- Referral asks at 60 days\n")
assert "output-format" in inspect.getsource(dd.SolomonEngine.learn)
print("ok — learn() drift guard holds")

# Real-data guards (2026-09-30 box capture): an empty Supabase roster is Unknown seats,
# and a watchdog repeating one alert is one bus note.
assert dd._dedupe_bus([{"from": "watchdog", "text": "Replies DOWN (errors x12)"},
                       {"from": "watchdog", "text": "Replies DOWN (errors x13)"}]) == \
    [{"from": "watchdog", "text": "Replies DOWN (errors x12)"}]
assert "r[\"openSeats\"] = r[\"enrolled\"] = None" in inspect.getsource(dd.SolomonEngine._gather_roster)
ns = dd._north_star_block()
assert "## 3. Wholesale" not in ns and ("## 5. Daycare" in ns or not ns)
print("ok — real-data guards hold")

# Leads match seats only through the shared center label.
import daycare_leads
assert set(dd._CENTER_ALIAS.values()) <= set(daycare_leads.CENTER_LABEL.values()), \
    "roster centerLabel no longer matches the Lead Desk's center labels"
print("ok — center labels line up")
