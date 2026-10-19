"""Solomon: growth first, and since 2026-10-18 the WHOLE daycare side (billing, daycare mail, ops,
system health) — payroll / staff admin stay out. Guards the scope, the board feed, the drift guard and
the seat math.

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
# 2026-10-18: the orchestrator craft is a top skill (chat + brief) and never reachable by learn().
assert "solomon-orchestrator-craft.md" in dd.SolomonEngine.TOP_SKILLS
assert "Orchestrator Craft" in skills, "orchestrator craft missing from Solomon's top skills"
_eng = dd.SolomonEngine.__new__(dd.SolomonEngine)
assert "Orchestrator Craft" not in dd.SolomonEngine._playbook_only(_eng), "learn() must never see a top skill"

# The brief prompt: growth first, the whole daycare side watched (2026-10-18), no retired role agents.
src = inspect.getsource(dd.SolomonEngine.build_brief)
assert "Paperwork is NOT your lane" not in src, "the 2026-09-30 growth-only rule was reversed"
assert "Growth is still job one" in src and "WHOLE daycare side" in src and "Payroll and staff scheduling stay out" in src
assert "never reorder it: safety/ratio → " in src and '"families waiting on us → cash' in src, "the creed's triage order"
assert 'live.update(board_state())' in src and "board (your COMMAND BOARD" in src and "mailDesk" in src
assert "Compliance)" not in src and "Billing, Family-Comms" not in src
assert "startsDesk" in src, "Starts lane not fed to the brief"
bs = dd.board_state()
assert set(bs) == {"board", "mailDesk"}, bs
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

# learn() drift guard (2026-10-18 scope): billing / inbox / ops lines are allowed now; payroll / staff
# admin, a guessed number, or an unsourced $ / % figure are rejected.
assert not dd._paperwork_drift("- Chase overdue invoices weekly\n- Flag unanswered parent email over 4 h\n"
                               "- Licensing notices go to the top of the inbox\n")
assert not dd._paperwork_drift("- Referral asks at 60 days\n- Call leads in 15 min.\n")
assert dd._paperwork_drift("- Run payroll on Fridays\n- Build staff schedules weekly\n"), "staff admin still out"
assert dd._paperwork_drift("- Estimate open seats from licensed capacity\n"), "never guess a number"
assert not dd._paperwork_drift("- Never estimate a seat count — read Supabase\n")
assert dd._paperwork_drift("- Offer a 10% sibling discount\n"), "an unsourced % is an invented offer term"
assert dd._paperwork_drift("- Overdue balances total $4,200\n"), "an unsourced $ is an invented number"
assert not dd._paperwork_drift("- Quote CPL vs the $40 target from the Pipeboard feed, with its window\n")
learn_src = inspect.getsource(dd.SolomonEngine.learn)
assert "output-format" in learn_src and "orchestrator craft" in learn_src
assert "Never add paperwork, compliance, billing-collection" not in learn_src
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

# Old ops/compliance brief notes never feed back in as "recent operating record".
assert 'GROWTH_SINCE' in inspect.getsource(dd.SolomonEngine._recent_brain_context)
assert "brief-2026-08-01"[6:16] < dd.GROWTH_SINCE
print("ok — stale compliance briefs stay out")

# Solomon's loop-down alerts go to the daycare chat, never HQ (source check — connector is heavy).
_src = open("connector.py").read()
assert '"daycare_replies": "daycare"' in _src and '"scout": "wholesale"' in _src and "business=_WATCHDOG_BIZ.get(loop)" in _src
print("ok — Solomon alerts routed to the daycare chat")
