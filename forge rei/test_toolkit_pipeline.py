import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import toolkit_pipeline


class PipelineReminderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_state = toolkit_pipeline.STATE
        toolkit_pipeline.STATE = Path(self._tmp.name) / "pipeline_reminders.json"
        self.now = 1_720_000_000_000
        self.deal = {
            "contactId": "c123",
            "name": "Jane Seller",
            "address": "12 Main, Dover DE",
        }

    def tearDown(self):
        toolkit_pipeline.STATE = self._orig_state
        self._tmp.cleanup()

    def create(self, deal_id="c123", due_at=None, draft="Follow up on the offer"):
        return toolkit_pipeline.create_reminder(
            deal_id, self.deal, due_at or self.now + 86_400_000, draft
        )

    def test_empty_list_is_safe(self):
        self.assertEqual([], toolkit_pipeline.list_reminders())
        self.assertIsNone(toolkit_pipeline.get_reminder("missing"))

    def test_create_reminder_has_locked_shape(self):
        with mock.patch.object(toolkit_pipeline, "_now", return_value=self.now):
            reminder = self.create()
        self.assertEqual("c123", reminder["dealId"])
        self.assertEqual("Jane Seller", reminder["dealName"])
        self.assertEqual("12 Main, Dover DE", reminder["address"])
        self.assertEqual(self.now, reminder["setAt"])
        self.assertEqual(self.now + 86_400_000, reminder["dueAt"])
        self.assertEqual("pending", reminder["status"])
        self.assertIsNone(reminder["sentAt"])
        self.assertIsNone(reminder["snoozedUntil"])
        self.assertEqual("", reminder["note"])

    def test_create_requires_deal_id_and_valid_due_time(self):
        self.assertIn("error", self.create(deal_id=""))
        self.assertIn("error", toolkit_pipeline.create_reminder("c123", self.deal, "nope", "Draft"))

    def test_get_returns_persisted_reminder(self):
        created = self.create()
        self.assertEqual(created, toolkit_pipeline.get_reminder("c123"))

    def test_create_for_same_deal_replaces_in_place(self):
        first = self.create(draft="First")
        second = self.create(due_at=self.now + 172_800_000, draft="Second")
        self.assertEqual("c123", second["dealId"])
        self.assertEqual("Second", toolkit_pipeline.get_reminder("c123")["draftMsg"])
        self.assertEqual(1, len(toolkit_pipeline.list_reminders()))
        self.assertNotEqual(first["dueAt"], second["dueAt"])

    def test_list_is_ordered_by_next_due_time(self):
        self.create(due_at=self.now + 3000)
        toolkit_pipeline.create_reminder("c456", {"name": "Bob"}, self.now + 1000, "Call Bob")
        self.assertEqual(["c456", "c123"], [r["dealId"] for r in toolkit_pipeline.list_reminders()])

    def test_list_filters_by_status(self):
        self.create()
        toolkit_pipeline.create_reminder("c456", {"name": "Bob"}, self.now + 1000, "Call Bob")
        toolkit_pipeline.dismiss_reminder("c456")
        self.assertEqual(["c123"], [r["dealId"] for r in toolkit_pipeline.list_reminders("pending")])
        self.assertEqual(["c456"], [r["dealId"] for r in toolkit_pipeline.list_reminders("dismissed")])
        self.assertEqual([], toolkit_pipeline.list_reminders("not-a-status"))

    def test_snooze_marks_status_and_moves_due_time(self):
        self.create()
        with mock.patch.object(toolkit_pipeline, "_now", return_value=self.now + 10):
            reminder = toolkit_pipeline.snooze_reminder("c123", self.now + 172_800_000)
        self.assertEqual("snoozed", reminder["status"])
        self.assertEqual(self.now + 172_800_000, reminder["snoozedUntil"])
        self.assertEqual(self.now + 172_800_000, reminder["dueAt"])
        self.assertEqual(self.now + 10, reminder["snoozedAt"])

    def test_snooze_requires_existing_reminder_and_valid_time(self):
        self.assertIn("error", toolkit_pipeline.snooze_reminder("missing", self.now + 1000))
        self.create()
        self.assertIn("error", toolkit_pipeline.snooze_reminder("c123", "tomorrow"))

    def test_dismiss_is_persisted_and_reversible_state(self):
        self.create()
        with mock.patch.object(toolkit_pipeline, "_now", return_value=self.now + 10):
            reminder = toolkit_pipeline.dismiss_reminder("c123")
        self.assertEqual("dismissed", reminder["status"])
        self.assertEqual(self.now + 10, reminder["dismissedAt"])
        self.assertEqual("dismissed", toolkit_pipeline.get_reminder("c123")["status"])

    def test_mark_sent_records_operator_handoff_without_transport(self):
        self.create()
        with mock.patch.object(toolkit_pipeline, "_now", return_value=self.now + 10):
            reminder = toolkit_pipeline.mark_sent("c123")
        self.assertEqual("sent", reminder["status"])
        self.assertEqual(self.now + 10, reminder["sentAt"])
        self.assertNotIn("transport", reminder)

    def test_update_allows_draft_and_note_only(self):
        self.create()
        reminder = toolkit_pipeline.update_reminder(
            "c123", draftMsg="Revised draft", note="Call after 5pm", status="sent", unknown="x"
        )
        self.assertEqual("Revised draft", reminder["draftMsg"])
        self.assertEqual("Call after 5pm", reminder["note"])
        self.assertEqual("pending", reminder["status"])
        self.assertNotIn("unknown", reminder)

    def test_update_missing_reminder_errors(self):
        self.assertIn("error", toolkit_pipeline.update_reminder("missing", draftMsg="Nope"))

    def test_days_in_stage_rounds_up_and_handles_missing_dates(self):
        with mock.patch.object(toolkit_pipeline, "_now", return_value=self.now):
            self.assertEqual(0, toolkit_pipeline.days_in_stage({"updatedAt": self.now}))
            self.assertEqual(1, toolkit_pipeline.days_in_stage({"updatedAt": self.now - 1}))
            self.assertEqual(3, toolkit_pipeline.days_in_stage({"updatedAt": self.now - (2 * 86_400_000) - 1}))
            self.assertIsNone(toolkit_pipeline.days_in_stage({}))
            self.assertIsNone(toolkit_pipeline.days_in_stage({"updatedAt": "not-a-date"}))

    def test_store_uses_reminders_envelope_and_atomic_json_shape(self):
        self.create()
        stored = json.loads(toolkit_pipeline.STATE.read_text())
        self.assertEqual({"c123"}, set(stored["reminders"]))
        self.assertEqual("pending", stored["reminders"]["c123"]["status"])


if __name__ == "__main__":
    unittest.main()
