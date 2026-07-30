import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_bus
import followup
import marcus_screening


NOW_MS = 2_000_000_000_000
CONTACT_ID = "contact-checkback"
CONVERSATION_ID = "conversation-checkback"
NURTURE_DRAFT = "no worries, is it ok if i check back in a month?"


class FakeMarcus:
    def __init__(self):
        self.approve_calls = []
        self.send_calls = []

    def approve(self, *args, **kwargs):
        self.approve_calls.append((args, kwargs))

    def _send(self, *args, **kwargs):
        self.send_calls.append((args, kwargs))


class FollowupCheckbackTest(unittest.TestCase):
    def test_due_nurture_checkback_stays_approval_only(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            screening_state = tmp / "screenings.json"
            followup_state = tmp / "followup.json"
            bus_state = tmp / "agent_bus.json"
            ghl_posts = []
            marcus = FakeMarcus()

            with (
                mock.patch.object(marcus_screening, "STATE", screening_state),
                mock.patch.object(followup, "STATE", followup_state),
                mock.patch.object(agent_bus, "STATE", bus_state),
                mock.patch.object(agent_bus, "_NOTIFIERS", []),
                mock.patch.object(followup.time, "time", return_value=NOW_MS / 1000),
                mock.patch.object(
                    followup.send_ledger, "touched_within", return_value=False
                ),
                mock.patch.object(followup.autopilot, "maybe_send") as maybe_send,
            ):
                screener = marcus_screening.Screener(
                    lambda *_args, **_kwargs: {},
                    "location-test",
                    ghl_post=lambda path, payload: ghl_posts.append((path, payload)),
                )
                screener.screenings[CONTACT_ID] = {
                    "contactId": CONTACT_ID,
                    "convId": CONVERSATION_ID,
                    "name": "Taylor Seller",
                    "updatedAt": NOW_MS - 31 * followup.DAY_MS,
                    "report": {
                        "interest": "not_ready",
                        "checkBackDays": 30,
                        "nurtureDraft": NURTURE_DRAFT,
                    },
                }

                with mock.patch.object(
                    screener, "send_nurture", wraps=screener.send_nurture
                ) as send_nurture:
                    engine = followup.FollowupEngine(
                        scout=None,
                        screener=screener,
                        marcus=marcus,
                        ghl_get=lambda *_args, **_kwargs: {},
                        location_id="location-test",
                    )
                    engine._scan_due_checkbacks()

                record = screener.screenings[CONTACT_ID]
                self.assertIs(record.get("checkBackDue"), True)
                self.assertEqual(record.get("checkBackDueSince"), NOW_MS)

                persisted = json.loads(screening_state.read_text())
                saved_record = persisted["screenings"][CONTACT_ID]
                self.assertIs(saved_record["checkBackDue"], True)
                self.assertEqual(saved_record["checkBackDueSince"], NOW_MS)
                self.assertTrue(followup_state.exists())

                bus_messages = json.loads(bus_state.read_text())["messages"]
                self.assertEqual(len(bus_messages), 1)
                alert = bus_messages[0]
                self.assertEqual(alert["from"], "marcus")
                self.assertEqual(alert["to"], "all")
                self.assertEqual(alert["kind"], "alert")
                self.assertIn("One tap to send your check-back.", alert["text"])
                self.assertEqual(
                    alert["data"],
                    {
                        "type": "checkback_due",
                        "contactId": CONTACT_ID,
                        "convId": CONVERSATION_ID,
                        "name": "Taylor Seller",
                        "draft": NURTURE_DRAFT,
                    },
                )

                maybe_send.assert_not_called()
                send_nurture.assert_not_called()
                self.assertEqual(marcus.approve_calls, [])
                self.assertEqual(marcus.send_calls, [])
                self.assertEqual(ghl_posts, [])


if __name__ == "__main__":
    unittest.main()
