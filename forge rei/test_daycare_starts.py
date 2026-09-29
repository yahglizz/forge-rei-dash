"""Solomon · Starts — start date from the thread → owner confirm → start-day login text.
Run: python3 test_daycare_starts.py (no network: fake GHL client, fake session/mint/send)."""
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import daycare_ghl
import daycare_starts as ds

ET = ds.ET


def ts(y, m, d, hh=10, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET).timestamp()


def msg(body, when, direction="inbound"):
    return {"body": body, "direction": direction, "messageType": "TYPE_SMS",
            "dateAdded": datetime.fromtimestamp(when, ET).isoformat()}


class FakeGHL:
    configured = True
    location_id = "loc"

    def __init__(self, contacts, threads):
        self.contacts, self.threads = contacts, threads
        self.puts, self.tag_adds, self.tag_drops, self.gets = [], [], [], 0

    def get(self, path, params=None):
        self.gets += 1
        if path == "/conversations/search":
            return {"conversations": [{"id": "conv-" + cid, "contactId": cid,
                                       "lastMessageDate": int(t[-1]["_t"] * 1000)}
                                      for cid, t in self.threads.items()]}
        if path.startswith("/conversations/conv-"):
            cid = path.split("/")[2][5:]
            return {"messages": {"messages": self.threads[cid]}}
        if path.startswith("/contacts/"):
            return {"contact": self.contacts[path.split("/")[2]]}
        raise AssertionError(path)

    def put(self, path, body):
        self.puts.append((path, body))
        return {}

    def post(self, path, body):
        self.tag_adds.append((path, body["tags"]))
        return {}

    def delete(self, path, body):
        self.tag_drops.append((path, body["tags"]))
        return {}


def contact(cid, tags=("website-lead", "loc-921-n-18th"), desired=""):
    cf = [{"id": daycare_ghl.CF_PARENT_NAME, "value": "Ana Lopez"},
          {"id": daycare_ghl.CF_CHILD_NAME, "value": "Mia Lopez"}]
    if desired:
        cf.append({"id": ds.CF_DESIRED, "value": desired})
    return {"id": cid, "tags": list(tags), "firstName": "mia", "lastName": "lopez", "customFields": cf}


def thread(*pairs):
    out = []
    for body, when, *d in pairs:
        m = msg(body, when, *(d or ["inbound"]))
        m["_t"] = when
        out.append(m)
    return out


class StartDateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = mock.patch.object(ds, "STATE", Path(self.tmp.name) / "starts.json")
        self.state.start()
        # telegram/bus pings are best-effort side effects — keep them off the network
        self.ping = mock.patch.object(ds, "_ping_confirm_window", lambda st, now: None)
        self.ping.start()

    def tearDown(self):
        self.ping.stop()
        self.state.stop()
        self.tmp.cleanup()

    # ---------------------------------------------------------------- parser
    def test_parse_date_forms(self):
        ref = date(2026, 9, 26)   # a Saturday
        cases = {
            "Oct 13": date(2026, 10, 13), "October 13th": date(2026, 10, 13),
            "10/13": date(2026, 10, 13), "10/13/26": date(2026, 10, 13),
            "the 13th of October": date(2026, 10, 13), "Sept. 30": date(2026, 9, 30),
            "Monday": date(2026, 9, 28), "next monday": date(2026, 9, 28),
            "tomorrow": date(2026, 9, 27), "the 5th": date(2026, 10, 5),
            "jan 4": date(2027, 1, 4), "9/20": date(2027, 9, 20),
        }
        for text, want in cases.items():
            self.assertEqual(ds.parse_date(text, ref), want, text)
        for text in ("next month", "soon", "13/45", "$10/20", "2/3 days a week"):
            got = ds.parse_date(text, ref)
            self.assertTrue(got is None or text == "2/3 days a week", (text, got))

    def test_extract_newest_start_sentence_wins_and_rejects_noise(self):
        t0 = ts(2026, 9, 22)
        msgs = [msg("Can she start Oct 6?", t0),
                msg("We have a tour Monday at 10", t0 + 60, "outbound"),
                msg("Actually can we do her first day on 10/13 instead", t0 + 3600),
                msg("ok thank you!", t0 + 7200)]
        got = ds.extract(msgs)
        self.assertEqual(got["date"], "2026-10-13")
        self.assertIn("first day", got["evidence"])
        self.assertEqual(got["source"], "messages")
        self.assertIsNone(ds.extract([msg("He started on 9/1 and loves it", t0)]))
        self.assertIsNone(ds.extract([msg("Can we book a tour to start, Monday?", t0)]))
        self.assertIsNone(ds.extract([msg("She can start next month", t0)]))
        self.assertIsNone(ds.extract([msg("START", t0)]))
        # outbound agreement counts too
        got = ds.extract([msg("See you Monday Oct 5 for Mia's first day!", t0, "outbound")])
        self.assertEqual((got["date"], got["dir"]), ("2026-10-05", "outbound"))

    def test_form_fallback_only_when_ahead(self):
        now = ts(2026, 9, 29)
        self.assertEqual(ds.form_date(contact("c", desired="2026-10-20"), now)["date"], "2026-10-20")
        self.assertIsNone(ds.form_date(contact("c", desired="2026-09-01"), now))
        self.assertEqual(ds.form_date(contact("c", desired="10/20/2026"), now)["date"], "2026-10-20")

    # ---------------------------------------------------------------- sweep
    def test_sweep_proposes_writes_ghl_and_skips_non_signups(self):
        now = ts(2026, 9, 29)
        ghl = FakeGHL({"a": contact("a"), "b": contact("b", tags=("daycare family",))},
                      {"a": thread(("Can Mia start Monday 10/5?", now - 3600)),
                       "b": thread(("can he start 10/6", now - 3600))})
        self.assertIsNone(ds.sweep(ghl, now))
        rows = ds.view(now)["starts"]
        self.assertEqual([r["contactId"] for r in rows], ["a"])
        a = rows[0]
        self.assertEqual((a["status"], a["startDate"], a["childFirst"], a["center"]),
                         ("proposed", "2026-10-05", "Mia", "921 N 18th St"))
        self.assertEqual(a["locationId"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(ghl.puts, [("/contacts/a", {"customFields": [{"id": ds.CF_AGREED, "field_value": "2026-10-05"}]})])
        self.assertEqual(ghl.tag_adds, [("/contacts/a/tags", [ds.TAG_PROPOSED])])
        # unchanged threads are not re-read
        gets = ghl.gets
        ds.sweep(ghl, now + 60)
        self.assertEqual(ghl.gets - gets, 1)   # only the conversation list

    def test_confirm_window_and_owner_actions(self):
        now = ts(2026, 10, 1)
        ghl = FakeGHL({"a": contact("a")}, {"a": thread(("first day 10/5?", now - 60))})
        ds.sweep(ghl, now)
        self.assertEqual(ds.confirm_due(now), [])             # 4 days out: listed, not prompted
        row = ds.view(now)["starts"][0]
        self.assertFalse(row["confirmOpen"])
        self.assertEqual(len(ds.confirm_due(ts(2026, 10, 3))), 1)   # 2 days out: prompt
        import owner_actions
        with mock.patch.object(ds, "time") as t:
            t.time.return_value = ts(2026, 10, 3)
            rows = owner_actions._src_daycare_starts({})
        self.assertEqual(rows[0]["kind"], "APPROVE")
        self.assertIn("Mia's start date — 2026-10-05", rows[0]["title"])

    # ---------------------------------------------------------------- confirm + send
    def _confirmed(self, now, start="2026-10-05"):
        ghl = FakeGHL({"a": contact("a")}, {"a": thread((f"can she start {start[5:7]}/{start[8:]}", now - 60))})
        ds.sweep(ghl, now)
        calls = []

        def enroll(entry, day, extras):
            calls.append((entry["contactId"], day, extras))
            return {"ok": True, "childId": "child-1", "locationId": entry["locationId"]}
        res = ds.confirm("a", start, enroll, client=ghl, now=now)
        self.assertTrue(res["ok"], res)
        self.assertEqual(calls, [("a", start, {})])
        return ghl

    def test_confirm_surfaces_needs_and_stays_proposed(self):
        now = ts(2026, 10, 3)
        ghl = FakeGHL({"a": contact("a")}, {"a": thread(("start 10/5", now - 60))})
        ds.sweep(ghl, now)
        res = ds.confirm("a", None, lambda e, d, x: {"ok": False, "needs": ["email"], "error": "missing: email"}, now=now)
        self.assertEqual((res["ok"], res["needs"]), (False, ["email"]))
        self.assertEqual(ds.view(now)["starts"][0]["status"], "proposed")

    def test_start_day_send_only_on_the_day_in_hours_and_never_stores_pin(self):
        now = ts(2026, 10, 3)
        ghl = self._confirmed(now)
        self.assertIn(("/contacts/a/tags", [ds.TAG_CONFIRMED]), ghl.tag_adds)
        sent = []
        mint = lambda session, e: {"login_id": "Ana Lopez", "pin": "482913"}  # noqa: E731
        send = lambda cid, text: sent.append((cid, text)) or {"ok": True}      # noqa: E731
        self.assertEqual(ds.send_due(ghl, lambda: "S", mint, now=now, send_fn=send), [])          # 2 days early
        self.assertEqual(ds.send_due(ghl, lambda: "S", mint, now=ts(2026, 10, 5, 6), send_fn=send), [])  # 6am
        self.assertEqual(ds.view(now)["starts"][0]["status"], "confirmed")
        out = ds.send_due(ghl, lambda: "S", mint, now=ts(2026, 10, 5, 8, 5), send_fn=send)
        self.assertEqual(out, [{"contactId": "a", "ok": True, "error": None}])
        self.assertEqual(len(sent), 1)
        self.assertIn("482913", sent[0][1])
        self.assertIn("atouchofblessing.com/get-app", sent[0][1])
        self.assertEqual(ds.view(now)["starts"][0]["status"], "sent")
        self.assertIn(("/contacts/a/tags", [ds.TAG_SENT]), ghl.tag_adds)
        self.assertNotIn("482913", ds.STATE.read_text())
        # sent is final: never again
        self.assertEqual(ds.send_due(ghl, lambda: "S", mint, now=ts(2026, 10, 5, 9), send_fn=send), [])
        self.assertEqual(len(sent), 1)

    def test_failed_send_retries_then_fix_row(self):
        now = ts(2026, 10, 3)
        ghl = self._confirmed(now)
        mint = lambda session, e: {"login_id": "Ana Lopez", "pin": "1"}   # noqa: E731
        bad = lambda cid, text: {"ok": False, "error": "parent opted out — not sent"}  # noqa: E731
        for i in range(ds.MAX_TRIES):
            out = ds.send_due(ghl, lambda: "S", mint, now=ts(2026, 10, 5, 9, i), send_fn=bad)
            self.assertFalse(out[0]["ok"])
        row = ds.view(now)["starts"][0]
        self.assertEqual((row["status"], row["tries"]), ("failed", ds.MAX_TRIES))
        self.assertEqual(ds.confirm_due(ts(2026, 10, 5, 10))[0]["status"], "failed")

    def test_stale_sending_never_resends(self):
        now = ts(2026, 10, 3)
        ghl = self._confirmed(now)
        ds._patch("a", status="sending", sendingAt=int(ts(2026, 10, 5, 8) * 1000))
        sent = []
        out = ds.send_due(ghl, lambda: "S", lambda s, e: {"pin": "1"}, now=ts(2026, 10, 5, 9),
                          send_fn=lambda c, t: sent.append(c) or {"ok": True})
        self.assertEqual((out, sent), ([], []))
        self.assertEqual(ds.view(now)["starts"][0]["status"], "failed")

    def test_date_moved_in_thread_after_confirm_reopens(self):
        now = ts(2026, 10, 3)
        ghl = self._confirmed(now)
        later = now + 3600
        ghl.threads["a"] = thread(("start 10/5", now - 60), ("sorry can her first day be 10/12 instead", later))
        ds.sweep(ghl, later + 60)
        row = ds.view(later)["starts"][0]
        self.assertEqual((row["status"], row["startDate"], row["reopened"]), ("proposed", "2026-10-12", True))
        self.assertEqual(ds.send_due(ghl, lambda: "S", lambda s, e: {"pin": "1"}, now=ts(2026, 10, 5, 9),
                                     send_fn=lambda c, t: {"ok": True}), [])

    def test_owner_edit_and_dismiss_beat_older_evidence(self):
        now = ts(2026, 10, 1)
        ghl = FakeGHL({"a": contact("a")}, {"a": thread(("start 10/5", now - 60))})
        ds.sweep(ghl, now)
        self.assertTrue(ds.set_date("a", "2026-10-07", now=now + 5)["ok"])
        ghl.threads["a"].append(dict(msg("ok", now + 1), _t=now + 1))   # new msg, old date evidence
        ds.sweep(ghl, now + 10)
        self.assertEqual(ds.view(now)["starts"][0]["startDate"], "2026-10-07")
        self.assertFalse(ds.set_date("a", "2030-01-01", now=now)["ok"])
        self.assertTrue(ds.dismiss("a", now=now + 20)["ok"])
        self.assertEqual(ds.view(now)["starts"], [])

    def test_start_day_text(self):
        t = daycare_ghl.start_day_text("Ana", "Mia", "Ana Lopez", "482913", "11111111-1111")
        self.assertLessEqual(len(t), 480)
        for want in ("Hi Ana!", "Mia's first day", "Sign in with your name: Ana Lopez", "PIN: 482913",
                     "https://atouchofblessing.com/get-app ", "A Touch of Blessings"):
            self.assertIn(want, t)
        amt = daycare_ghl.start_day_text("", "", "BL-1234", "1", "44444444-4444")
        self.assertIn("Hi there!", amt)
        self.assertIn("Login ID: BL-1234", amt)
        self.assertIn("get-app-mothers-touch", amt)
        # login_text unchanged by the brand refactor
        self.assertIn("Get the app: https://atouchofblessing.com/get-app\n",
                      daycare_ghl.login_text("Ana", "Mia", "Ana Lopez", "1", "11111111"))


if __name__ == "__main__":
    unittest.main()
