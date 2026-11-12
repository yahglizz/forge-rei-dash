"""Slack briefs: 8 AM / 6 PM Eastern, once per slot, shared rooms get all-sites briefs only, the main
chat gets one line per site + AMT counts + the no-site-tag warning, nothing while boards are unread.
Run: FORGE_MARCUS=0 python3 -m unittest test_slack_briefs  (no network: slack_io._api faked)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if "slack_io" not in sys.modules:
    os.environ["FORGE_SLACK_CONFIG_DIR"] = tempfile.mkdtemp(prefix="slack_cfg_")

import slack_briefs  # noqa: E402
import slack_io  # noqa: E402
import slack_rooms  # noqa: E402

DAYCARE, TOURS, QUOTES, ALERTS, ENROLLED = "CDAY01", "CTOUR1", "CQUOT1", "CALRT1", "CENRL1"
AM = 1794490200            # 2026-11-12 13:30 UTC = 08:30 Eastern (EST)
PM = AM + 10 * 3600        # 18:30 Eastern
NOON = AM + 4 * 3600       # 12:30 Eastern: no slot open


def c(oid, name):
    return {"opportunityId": oid, "contactId": "c" + oid, "name": name, "createdAt": 1, "updatedAt": 1}


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api = []
        env = {k: v for k, v in os.environ.items() if not k.startswith("SLACK_") and k != "FORGE_CHAT_TRANSPORT"}
        env.update({"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_ALLOWED_USER_IDS": "UOWNER1", "FORGE_CHAT_TRANSPORT": "both"})
        self.sites = {"atob-one": {"New Lead": [c("1", "Ava")], "Tour Scheduled": [c("2", "Ben")],
                                   "Enrolled": [c("3", "Cy"), c("4", "Di")]},
                      "atob-two": {"Application Sent": [c("5", "Eve")]}}
        self.patches = [
            mock.patch.object(slack_io, "STATE", Path(self.tmp.name)),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(slack_io, "_api", self._fake_api),
            mock.patch.object(slack_rooms, "site_cards", lambda site=None: (self.sites, None)),
            mock.patch.object(slack_briefs, "_upcoming_tours", lambda et, proven: {"atob-one": [
                {"date": "2026-11-12", "time": "2026-11-12T10:00:00", "who": "Ben B."}]}),
            mock.patch.object(slack_briefs, "_starts", lambda et, proven: ({}, {"atob-two": 1})),
            mock.patch.object(slack_briefs, "_amt_counts", lambda: {"new lead": 2, "enrolled": 9}),
            mock.patch.object(slack_briefs, "_no_site_count", lambda: 3),
        ]
        for p in self.patches:
            p.start()
        slack_io._SEEN.clear()
        for k, ch in (("daycare", DAYCARE), ("daycare-tours", TOURS), ("daycare-quotes", QUOTES),
                      ("daycare-alerts", ALERTS), ("daycare-enrolled", ENROLLED)):
            slack_io.bind(k, ch)
        self.api.clear()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _fake_api(self, method, token, **params):
        self.api.append((method, params))
        return {"ok": True, "channel": params.get("channel"), "ts": f"1.{len(self.api)}"}

    def posts(self):
        return {p["channel"]: p.get("text") or "" for m, p in self.api if m == "chat.postMessage"}

    def test_slots_are_8am_and_6pm_eastern(self):
        self.assertTrue(slack_briefs.due(AM)[0].endswith("-am"))
        self.assertTrue(slack_briefs.due(PM)[0].endswith("-pm"))
        self.assertIsNone(slack_briefs.due(NOON))

    def test_morning_brief_posts_once_main_overview_and_room_details(self):
        self.assertEqual(slack_briefs.tick(AM), 5)              # main + alerts + tours + quotes + enrolled
        self.assertEqual(slack_briefs.tick(AM + 600), 0)        # same slot: never twice
        p = self.posts()
        main = p[DAYCARE]
        self.assertIn("921", main)
        self.assertIn("2318", main)
        self.assertIn("AMT 1923", main)
        self.assertIn("2 new", main.split("AMT 1923")[1])
        self.assertIn("3 ATOB families have no site tag", main)
        self.assertNotIn("Ava", main)                           # the overview is counts only
        self.assertIn("Ava", p[ALERTS])
        self.assertIn("Ben B.", p[TOURS])
        self.assertIn("Eve", p[QUOTES])
        self.assertIn("2 enrolled", p[ENROLLED])
        self.assertEqual(slack_briefs.tick(NOON), 0)

    def test_evening_brief_counts_what_moved_since_morning(self):
        slack_briefs.tick(AM)
        self.sites["atob-one"]["Enrolled"].append(c("1", "Ava"))
        self.sites["atob-one"]["New Lead"] = []
        self.api.clear()
        slack_briefs.tick(PM)
        p = self.posts()
        self.assertIn("1 moved since last brief", p[DAYCARE])
        self.assertIn("1 new: Ava", p[ENROLLED])
        self.assertNotIn(ALERTS, p)                             # nothing left to say there: skipped

    def test_tours_and_starts_need_a_board_proven_family(self):
        import daycare_calendar
        import daycare_starts
        for p in self.patches[4:6]:
            p.stop()
        self.patches = self.patches[:4] + self.patches[6:]
        up = [{"kind": "tour", "date": "2026-11-12", "time": None, "center": "loc-921-n-18th", "who": "Real R.",
               "contactId": "c2"},
              {"kind": "tour", "date": "2026-11-12", "time": None, "center": "loc-921-n-18th", "who": "Amt A.",
               "contactId": "amtcid"}]
        starts = [{"childName": "Cy", "startDate": "2026-11-14", "status": "proposed", "contactId": "c3"},
                  {"childName": "Amt Kid", "startDate": "2026-11-14", "status": "proposed", "center": "921 N 18th St",
                   "contactId": "amtcid"}]
        with mock.patch.object(daycare_calendar, "view", lambda now=None: {"upcoming": up}), \
                mock.patch.object(daycare_starts, "view", lambda now=None: {"starts": starts}):
            slack_briefs.tick(AM)
        p = self.posts()
        self.assertIn("Real R.", p[TOURS])
        self.assertNotIn("Amt A.", p[TOURS])
        self.assertNotIn("Amt Kid", str(p))

    def test_unread_boards_and_telegram_mode_post_nothing(self):
        with mock.patch.object(slack_rooms, "site_cards", lambda site=None: (None, "unread")):
            self.assertEqual(slack_briefs.tick(AM), 0)
        with mock.patch.dict(os.environ, {"FORGE_CHAT_TRANSPORT": "telegram"}):
            self.assertEqual(slack_briefs.tick(AM), 0)
        self.assertEqual(self.posts(), {})
        self.assertEqual(slack_briefs.tick(AM), 5)              # the slot was not burned


if __name__ == "__main__":
    unittest.main()
