"""daycare_calendar — mirrors booked tours + first days to one Google calendar.
Run: python3 test_daycare_calendar.py (no network: fake GHL client + fake Google)."""
import json
import os
import tempfile
import time
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import daycare_calendar as dc
import daycare_ghl
import google_cal_io

ET = dc.ET
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=ET).timestamp()   # a Monday, after the clock change
LIVE, QA = "live@group.calendar.google.com", "qa@group.calendar.google.com"


def contact(cid="c1", tags=("tour-scheduled", "loc-921-n-18th"), day="2026-11-04",
            time_text="Wednesday, November 4 at 10:00 AM ET", where="A Touch of Blessings",
            child="Zuri Davis", parent="Jane Doe", age="2 Years", dob=""):
    fields = [{"id": dc.CF_TOUR_DATE, "value": day}, {"id": dc.CF_TOUR_TIME, "value": time_text},
              {"id": dc.CF_TOUR_LOCATION, "value": where}, {"id": daycare_ghl.CF_CHILD_NAME, "value": child},
              {"id": daycare_ghl.CF_PARENT_NAME, "value": parent}, {"id": dc.CF_CHILD_AGE, "value": age},
              {"id": daycare_ghl.CF_CHILD_DOB, "value": dob}]
    first, _, last = child.partition(" ")
    return {"id": cid, "firstName": first, "lastName": last, "tags": list(tags), "phone": "+12155550100",
            "email": "secret@example.com", "customFields": [f for f in fields if f["value"]]}


class FakeGHL:
    configured = True
    location_id = "LOC"

    def __init__(self, *contacts):
        self.contacts = {c["id"]: c for c in contacts}
        self.fail_reads = False
        self.posts, self.puts, self.deletes = [], [], []

    def post(self, endpoint, body, retries=2):
        if endpoint == "/contacts/search":
            if self.fail_reads:
                raise OSError("ghl down")
            tag = body["filters"][0]["value"]
            hits = [{"id": c["id"], "tags": c["tags"]} for c in self.contacts.values() if tag in c["tags"]]
            return {"contacts": hits, "total": len(hits)}
        self.posts.append((endpoint, body))
        cid = endpoint.split("/")[2]
        self.contacts[cid]["tags"] = self.contacts[cid]["tags"] + list(body.get("tags") or [])
        return {}

    def get(self, endpoint, params=None, retries=3):
        if self.fail_reads:
            raise OSError("ghl down")
        return {"contact": self.contacts[endpoint.split("/")[2]]}

    def put(self, endpoint, body, retries=2):
        self.puts.append((endpoint, body))
        return {}

    def delete(self, endpoint, body=None, retries=2):
        self.deletes.append((endpoint, body))
        cid = endpoint.split("/")[2]
        self.contacts[cid]["tags"] = [t for t in self.contacts[cid]["tags"] if t not in (body or {}).get("tags", [])]
        return {}


class FakeGoogle:
    def __init__(self):
        self.events, self.writes, self.fail = {}, 0, None

    def put_event(self, cal, eid, body):
        if self.fail:
            raise self.fail
        self.writes += 1
        self.events[(cal, eid)] = body
        return "created"

    def remove(self, cal, eid):
        if self.fail:
            raise self.fail
        self.writes += 1
        self.events.pop((cal, eid), None)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.google = FakeGoogle()
        self.starts = {}
        self.env = {"FORGE_DAYCARE_CAL_QA": "0", "GOOGLE_CAL_ID": LIVE, "GOOGLE_CAL_ID_QA": QA}
        for p in (mock.patch.object(dc, "STATE", Path(self.tmp.name) / "cal.json"),
                  mock.patch.object(dc, "gcal", self.google),
                  mock.patch.object(dc, "_pick", lambda n: self.env.get(n, "")),
                  mock.patch.object(dc, "_starts_entries", lambda: self.starts),
                  mock.patch.object(dc, "_notify", lambda text, key: None),
                  mock.patch.object(dc, "_gcal_ready", lambda: True)):
            p.start()
            self.addCleanup(p.stop)

    def events(self):
        return list(self.google.events.values())

    def only(self):
        evs = self.events()
        self.assertEqual(len(evs), 1)
        return evs[0]

    def run_tick(self, ghl, now=NOW):
        return dc.tick(ghl, now=now)


class TourEvent(Base):
    def test_booked_tour_makes_one_event_with_tag_age_and_30_minutes(self):
        self.run_tick(FakeGHL(contact()))
        ev = self.only()
        self.assertEqual(ev["summary"], "[921] Tour: Zuri D. (2 Years)")
        self.assertEqual(ev["start"]["dateTime"], "2026-11-04T10:00:00-05:00")
        self.assertEqual(ev["end"]["dateTime"], "2026-11-04T10:30:00-05:00")
        self.assertEqual(ev["start"]["timeZone"], "America/New_York")
        self.assertEqual(ev["location"], "921 N 18th St, Philadelphia, PA 19130")
        self.assertEqual(ev["colorId"], "3")
        self.assertIn("Parent: Jane Doe", ev["description"])
        self.assertIn("/contacts/detail/c1", ev["description"])

    def test_summer_date_gets_the_daylight_offset(self):
        self.run_tick(FakeGHL(contact(day="2027-06-02", time_text="Wednesday, June 2 at 2:30 PM ET")))
        self.assertEqual(self.only()["start"]["dateTime"], "2027-06-02T14:30:00-04:00")

    def test_event_never_carries_private_details(self):
        self.run_tick(FakeGHL(contact()))
        text = json.dumps(self.only())
        for secret in ("secret@example.com", "2155550100", "Davis"):
            self.assertNotIn(secret, text)
        self.assertNotIn("attendees", self.only())

    def test_a_birth_date_beats_the_typed_age(self):
        self.run_tick(FakeGHL(contact(dob="2024-01-15", age="1 Year")))
        self.assertIn("(2 Years)", self.only()["summary"])

    def test_a_baby_shows_months(self):
        self.run_tick(FakeGHL(contact(dob="2026-05-01", age="")))
        self.assertIn("(6 Months)", self.only()["summary"])

    def test_sibling_note_is_dropped_from_the_age(self):
        self.run_tick(FakeGHL(contact(age="2 Years (+1 sibling)")))
        self.assertEqual(self.only()["summary"], "[921] Tour: Zuri D. (2 Years)")

    def test_age_range_and_weeks_are_kept(self):
        for age in ("1-2 Years", "6 Weeks", "8 Months"):
            self.google.events.clear()
            if dc.STATE.exists():
                dc.STATE.unlink()
            self.run_tick(FakeGHL(contact(age=age)))
            self.assertIn(f"({age})", self.only()["summary"])

    def test_bare_number_age_does_not_guess_a_unit(self):
        self.run_tick(FakeGHL(contact(age="3")))
        self.assertIn("(Age 3)", self.only()["summary"])

    def test_odd_age_text_is_left_out(self):
        self.run_tick(FakeGHL(contact(age="<b>three</b>")))
        self.assertEqual(self.only()["summary"], "[921] Tour: Zuri D.")

    def test_no_age_at_all_is_left_out(self):
        self.run_tick(FakeGHL(contact(age="")))
        self.assertEqual(self.only()["summary"], "[921] Tour: Zuri D.")

    def test_one_word_child_name_has_no_initial(self):
        self.run_tick(FakeGHL(contact(child="Zuri")))
        self.assertEqual(self.only()["summary"], "[921] Tour: Zuri (2 Years)")

    def test_unreadable_time_is_an_all_day_flag_never_a_guess(self):
        st = self.run_tick(FakeGHL(contact(time_text="sometime in the morning")))
        ev = self.only()
        self.assertEqual(ev["summary"], "[921] Tour: time not set: Zuri D. (2 Years)")
        self.assertEqual(ev["start"], {"date": "2026-11-04"})
        self.assertEqual(ev["end"], {"date": "2026-11-05"})
        self.assertIn("c1", [h["contactId"] for h in dc.view(NOW)["held"]])

    def test_a_date_from_ghl_as_epoch_ms_reads_the_same(self):
        ms = int(datetime(2026, 11, 4, tzinfo=dc.UTC).timestamp() * 1000)
        self.run_tick(FakeGHL(contact(day=str(ms))))
        self.assertTrue(self.only()["start"]["dateTime"].startswith("2026-11-04T10:00"))


class Centers(Base):
    def assertHeld(self, ghl):
        self.run_tick(ghl)
        self.assertEqual(self.events(), [])
        self.assertEqual(len(dc.view(NOW)["held"]), 1)

    def test_two_center_tags_are_held(self):
        self.assertHeld(FakeGHL(contact(tags=("tour-scheduled", "loc-921-n-18th", "loc-1923-cecil-b-moore"))))

    def test_no_center_tag_is_held(self):
        self.assertHeld(FakeGHL(contact(tags=("tour-scheduled",))))

    def test_tag_that_disagrees_with_tour_location_is_held(self):
        self.assertHeld(FakeGHL(contact(where="A Touch of Blessings 2 & 3")))

    def test_no_tour_date_is_held(self):
        self.assertHeld(FakeGHL(contact(day="")))

    def test_2318_tag_and_color(self):
        self.run_tick(FakeGHL(contact(tags=("tour-scheduled", "loc-2318-cecil-b-moore"), where="A Touch of Blessings 2 & 3")))
        self.assertTrue(self.only()["summary"].startswith("[2318] "))
        self.assertEqual(self.only()["colorId"], "7")

    def test_a_held_contact_keeps_its_existing_event(self):
        c = contact()
        ghl = FakeGHL(c)
        self.run_tick(ghl)
        c["tags"] = ["tour-scheduled", "loc-921-n-18th", "loc-2318-cecil-b-moore"]
        self.run_tick(ghl)
        self.assertEqual(len(self.events()), 1)


class Lifecycle(Base):
    def test_repeat_ticks_write_nothing(self):
        ghl = FakeGHL(contact())
        self.run_tick(ghl)
        before = self.google.writes
        for _ in range(5):
            self.run_tick(ghl)
        self.assertEqual(self.google.writes, before)

    def test_moved_date_keeps_one_event_id(self):
        c = contact()
        ghl = FakeGHL(c)
        self.run_tick(ghl)
        ids = set(self.google.events)
        c["customFields"][0]["value"] = "2026-11-05"
        self.run_tick(ghl)
        self.assertEqual(set(self.google.events), ids)
        self.assertEqual(self.only()["start"]["dateTime"], "2026-11-05T10:00:00-05:00")

    def test_moved_center_keeps_one_event_id(self):
        c = contact()
        ghl = FakeGHL(c)
        self.run_tick(ghl)
        ids = set(self.google.events)
        c["tags"] = ["tour-scheduled", "loc-2318-cecil-b-moore"]
        c["customFields"][2]["value"] = "A Touch of Blessings 2 & 3"
        self.run_tick(ghl)
        self.assertEqual(set(self.google.events), ids)
        self.assertTrue(self.only()["summary"].startswith("[2318] "))

    def test_canceled_tour_is_removed(self):
        c = contact()
        ghl = FakeGHL(c)
        self.run_tick(ghl)
        c["tags"] = ["tour-canceled", "loc-921-n-18th"]
        self.run_tick(ghl)
        self.assertEqual(self.events(), [])

    def test_failed_ghl_read_removes_nothing(self):
        ghl = FakeGHL(contact())
        self.run_tick(ghl)
        ghl.fail_reads = True
        err = self.run_tick(ghl)
        self.assertEqual(len(self.events()), 1)
        self.assertTrue(err)

    def test_search_miss_with_the_tag_still_on_the_contact_removes_nothing(self):
        c = contact()
        ghl = FakeGHL(c)
        self.run_tick(ghl)
        with mock.patch.object(dc, "_tagged", lambda client, tag: []):
            self.run_tick(ghl)
        self.assertEqual(len(self.events()), 1)

    def test_lost_ledger_writes_to_the_same_event_id(self):
        ghl = FakeGHL(contact())
        self.run_tick(ghl)
        ids = set(self.google.events)
        dc.STATE.unlink()
        self.run_tick(ghl)
        self.assertEqual(set(self.google.events), ids)

    def test_a_past_tour_is_never_created(self):
        self.run_tick(FakeGHL(contact(day="2026-10-20")))
        self.assertEqual(self.events(), [])

    def test_a_past_event_stays_when_its_tag_goes(self):
        c = contact()
        ghl = FakeGHL(c)
        self.run_tick(ghl)
        c["tags"] = ["loc-921-n-18th"]
        self.run_tick(ghl, now=datetime(2026, 11, 6, 9, 0, tzinfo=ET).timestamp())
        self.assertEqual(len(self.events()), 1)

    def test_seven_days_after_the_event_names_are_stripped(self):
        ghl = FakeGHL(contact())
        self.run_tick(ghl)
        self.run_tick(ghl, now=datetime(2026, 11, 11, 9, 0, tzinfo=ET).timestamp())
        ev = self.only()
        self.assertEqual(ev["summary"], "[921] Tour (past)")
        self.assertEqual(ev["description"], "")
        before = self.google.writes
        self.run_tick(ghl, now=datetime(2026, 11, 12, 9, 0, tzinfo=ET).timestamp())
        self.assertEqual(self.google.writes, before)


class Failures(Base):
    def test_google_outage_retries_and_recovers(self):
        ghl = FakeGHL(contact())
        self.google.fail = google_cal_io.CalError("Calendar HTTP 503", 503)
        self.run_tick(ghl)
        self.assertEqual(self.events(), [])
        self.google.fail = None
        self.run_tick(ghl)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(dc.view(NOW)["failed"], 0)

    def test_three_failed_ticks_flag_the_owner_with_counts_only(self):
        ghl = FakeGHL(contact())
        self.google.fail = google_cal_io.CalError("Calendar HTTP 503", 503)
        notes = []
        with mock.patch.object(dc, "_notify", lambda text, key: notes.append(text)):
            for _ in range(3):
                err = self.run_tick(ghl)
        self.assertEqual(dc.view(NOW)["failed"], 1)
        self.assertTrue(err)
        self.assertEqual(len(notes), 1)
        self.assertNotIn("Zuri", notes[0])

    def test_auth_failure_stops_the_tick(self):
        ghl = FakeGHL(contact(), contact(cid="c2"))
        self.google.fail = google_cal_io.CalAuthError("rejected", 401)
        err = self.run_tick(ghl)
        self.assertIn("re-consent", err)

    def test_writes_per_tick_are_capped(self):
        ghl = FakeGHL(*[contact(cid=f"c{i}") for i in range(dc.MAX_WRITES + 3)])
        self.run_tick(ghl)
        self.assertEqual(len(self.events()), dc.MAX_WRITES)
        self.run_tick(ghl)
        self.assertEqual(len(self.events()), dc.MAX_WRITES + 3)


class QaMode(Base):
    def setUp(self):
        super().setUp()
        self.env["FORGE_DAYCARE_CAL_QA"] = "1"

    def test_qa_mode_writes_only_tagged_contacts_to_the_qa_calendar(self):
        self.run_tick(FakeGHL(contact(), contact(cid="qa1", tags=("tour-scheduled", "loc-921-n-18th", "zz-calendar-qa"))))
        self.assertEqual([k[0] for k in self.google.events], [QA])
        self.assertEqual(len(self.events()), 1)

    def test_qa_is_the_default_when_the_switch_is_missing(self):
        del self.env["FORGE_DAYCARE_CAL_QA"]
        self.assertTrue(dc.qa_mode())

    def test_real_mode_skips_qa_contacts(self):
        self.env["FORGE_DAYCARE_CAL_QA"] = "0"
        self.run_tick(FakeGHL(contact(tags=("tour-scheduled", "loc-921-n-18th", "zz-calendar-qa"))))
        self.assertEqual(self.events(), [])

    def test_qa_mode_tap_refuses_a_real_family_and_writes_nothing(self):
        ghl = FakeGHL(contact(tags=("tour-requested",), day="", time_text="", where=""))
        out = dc.confirm_tour(ghl, "c1", "2026-11-04", "10:00", "loc-921-n-18th", now=NOW)
        self.assertFalse(out["ok"])
        self.assertEqual(ghl.puts + ghl.posts, [])
        self.assertFalse(dc.cancel_tour(ghl, "c1")["ok"])
        self.assertEqual(ghl.deletes, [])

    def test_real_mode_skips_zz_children(self):
        self.env["FORGE_DAYCARE_CAL_QA"] = "0"
        self.run_tick(FakeGHL(contact(child="ZZTest Child")))
        self.assertEqual(self.events(), [])


class FirstDays(Base):
    def entry(self, **kw):
        base = {"contactId": "c1", "startDate": "2026-11-09", "status": "confirmed",
                "locationId": daycare_ghl.LOCATION_ID_BY_TAG["loc-921-n-18th"]}
        base.update(kw)
        self.starts["c1"] = base

    def ghl(self, tags=("loc-921-n-18th",)):
        return FakeGHL(contact(tags=tags, day="", time_text="", where=""))

    def test_confirmed_start_is_an_all_day_free_event(self):
        self.entry()
        self.run_tick(self.ghl())
        ev = self.only()
        self.assertEqual(ev["summary"], "[921] First day: Zuri D. (2 Years)")
        self.assertEqual(ev["start"], {"date": "2026-11-09"})
        self.assertEqual(ev["end"], {"date": "2026-11-10"})
        self.assertEqual(ev["transparency"], "transparent")

    def test_proposed_without_the_tap_stays_off_the_calendar(self):
        self.entry(status="proposed")
        self.run_tick(self.ghl())
        self.assertEqual(self.events(), [])

    def test_add_to_calendar_tap_puts_a_proposed_date_on(self):
        self.entry(status="proposed", calendarAt=1)
        self.run_tick(self.ghl())
        self.assertEqual(len(self.events()), 1)

    def test_tap_with_two_center_tags_is_held(self):
        self.entry(status="proposed", calendarAt=1)
        self.run_tick(self.ghl(tags=("loc-921-n-18th", "loc-1923-cecil-b-moore")))
        self.assertEqual(self.events(), [])
        self.assertEqual(len(dc.view(NOW)["held"]), 1)

    def test_confirmed_center_wins_over_messy_tags(self):
        self.entry(locationId=daycare_ghl.LOCATION_ID_BY_TAG["loc-2318-cecil-b-moore"])
        self.run_tick(self.ghl(tags=("loc-921-n-18th", "loc-1923-cecil-b-moore")))
        self.assertTrue(self.only()["summary"].startswith("[2318] "))

    def test_1923_uses_its_own_tag_and_never_the_other_brand(self):
        self.entry(locationId=daycare_ghl.LOCATION_ID_BY_TAG["loc-1923-cecil-b-moore"])
        self.run_tick(self.ghl(tags=("loc-1923-cecil-b-moore",)))
        ev = self.only()
        self.assertTrue(ev["summary"].startswith("[1923 AMT] First day: "))
        self.assertEqual(ev["colorId"], "4")
        self.assertEqual(ev["location"], "1923 Cecil B. Moore Ave, Philadelphia, PA 19121")
        self.assertNotIn("A Touch of Blessings", json.dumps(ev))

    def test_moved_date_moves_the_event(self):
        self.entry()
        ghl = self.ghl()
        self.run_tick(ghl)
        ids = set(self.google.events)
        self.starts["c1"]["startDate"] = "2026-11-16"
        self.run_tick(ghl)
        self.assertEqual(set(self.google.events), ids)
        self.assertEqual(self.only()["start"], {"date": "2026-11-16"})

    def test_reopened_or_dismissed_removes_the_event(self):
        for status in ("proposed", "dismissed"):
            self.entry()
            ghl = self.ghl()
            self.run_tick(ghl)
            self.assertEqual(len(self.events()), 1)
            self.starts["c1"]["status"] = status
            self.run_tick(ghl)
            self.assertEqual(self.events(), [])

    def test_unreadable_starts_state_removes_nothing(self):
        self.entry()
        ghl = self.ghl()
        self.run_tick(ghl)
        with mock.patch.object(dc, "_starts_entries", side_effect=OSError("bad file")):
            self.run_tick(ghl)
        self.assertEqual(len(self.events()), 1)

    def test_unchanged_start_reads_ghl_once(self):
        self.entry()
        ghl = self.ghl()
        reads = []
        real = ghl.get
        ghl.get = lambda e, params=None, retries=3: (reads.append(e), real(e))[1]
        self.run_tick(ghl)
        self.run_tick(ghl)
        self.assertEqual(len(reads), 1)


class ConfirmTour(Base):
    def lead(self, tags=("tour-requested",)):
        return FakeGHL(contact(tags=tags, day="", time_text="", where=""))

    def test_tap_writes_fields_then_the_tag(self):
        ghl = self.lead()
        order = []
        real_put, real_post = ghl.put, ghl.post
        ghl.put = lambda e, b, retries=2: (order.append("fields"), real_put(e, b))[1]
        ghl.post = lambda e, b, retries=2: (order.append(tuple(b.get("tags") or ())), real_post(e, b))[1]
        out = dc.confirm_tour(ghl, "c1", "2026-11-04", "14:30", "loc-921-n-18th", now=NOW)
        self.assertTrue(out["ok"])
        self.assertEqual(order[0], "fields")
        self.assertEqual(order[-1], ("tour-scheduled",))
        values = {f["id"]: f["field_value"] for f in ghl.puts[0][1]["customFields"]}
        self.assertEqual(values[dc.CF_TOUR_DATE], "2026-11-04")
        self.assertEqual(values[dc.CF_TOUR_TIME], "Wednesday, November 4 at 2:30 PM ET")
        self.assertEqual(values[dc.CF_TOUR_LOCATION], "A Touch of Blessings")

    def test_tap_clears_an_old_cancel(self):
        ghl = self.lead(tags=("tour-canceled", "loc-921-n-18th"))
        dc.confirm_tour(ghl, "c1", "2026-11-04", "10:00", "loc-921-n-18th", now=NOW)
        self.assertIn("tour-canceled", ghl.deletes[0][1]["tags"])
        self.assertNotIn("tour-canceled", ghl.contacts["c1"]["tags"])

    def test_tap_adds_the_center_tag_when_there_is_none(self):
        ghl = self.lead()
        dc.confirm_tour(ghl, "c1", "2026-11-04", "10:00", "loc-2318-cecil-b-moore", now=NOW)
        self.assertIn("loc-2318-cecil-b-moore", ghl.contacts["c1"]["tags"])
        self.assertIn("entity-atob", ghl.contacts["c1"]["tags"])

    def test_tap_refuses_1923(self):
        ghl = self.lead()
        out = dc.confirm_tour(ghl, "c1", "2026-11-04", "10:00", "loc-1923-cecil-b-moore", now=NOW)
        self.assertFalse(out["ok"])
        self.assertEqual(ghl.puts + ghl.posts, [])

    def test_tap_refuses_a_contact_at_another_center(self):
        ghl = self.lead(tags=("loc-2318-cecil-b-moore",))
        out = dc.confirm_tour(ghl, "c1", "2026-11-04", "10:00", "loc-921-n-18th", now=NOW)
        self.assertFalse(out["ok"])
        self.assertEqual(ghl.puts + ghl.posts, [])

    def test_tap_refuses_a_past_date_a_bad_time_and_a_weekend(self):
        for day, clock in (("2026-10-30", "10:00"), ("2026-11-04", "25:00"), ("2026-11-04", "noon"), ("2026-11-07", "10:00")):
            ghl = self.lead()
            self.assertFalse(dc.confirm_tour(ghl, "c1", day, clock, "loc-921-n-18th", now=NOW)["ok"], (day, clock))
            self.assertEqual(ghl.puts + ghl.posts, [])

    def test_written_time_text_reads_back_as_the_same_time(self):
        ghl = self.lead()
        dc.confirm_tour(ghl, "c1", "2026-11-04", "14:30", "loc-921-n-18th", now=NOW)
        values = {f["id"]: f["field_value"] for f in ghl.puts[0][1]["customFields"]}
        self.assertEqual(dc.parse_clock(values[dc.CF_TOUR_TIME]), (14, 30))

    def test_cancel_swaps_the_tags(self):
        ghl = self.lead(tags=("tour-scheduled", "loc-921-n-18th"))
        self.assertTrue(dc.cancel_tour(ghl, "c1")["ok"])
        self.assertNotIn("tour-scheduled", ghl.contacts["c1"]["tags"])
        self.assertIn("tour-canceled", ghl.contacts["c1"]["tags"])


class View(Base):
    def test_view_before_any_run_says_so(self):
        self.assertIn("has not run", dc.view(NOW)["error"])

    def test_view_names_the_mode_and_holds_no_family_contact_data(self):
        self.run_tick(FakeGHL(contact()))
        v = dc.view(NOW)
        self.assertEqual(v["mode"], "live")
        self.assertEqual(v["events"], 1)
        self.assertNotIn("secret@example.com", dc.STATE.read_text())


if __name__ == "__main__":
    unittest.main()
