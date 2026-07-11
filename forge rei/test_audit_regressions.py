"""Regression coverage for production audit repairs.

All tests use in-memory or temporary fakes. No GHL, DocuSign, Telegram, or seller
messages are touched.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import connector
import docusign_io
import marcus_engine
import scout_triage


class SellerMessageTests(unittest.TestCase):
    def test_reaction_quoting_outreach_is_still_a_seller_message(self):
        body = '👍 to "Hey Robert, still buying as-is for cash"'
        self.assertTrue(marcus_engine._is_our_message(body))
        self.assertTrue(marcus_engine._is_reaction(body))
        self.assertTrue(marcus_engine._is_seller_message(body))

    def test_plain_outreach_is_not_a_seller_message(self):
        self.assertFalse(marcus_engine._is_seller_message(
            "Hey, just following up about your property"
        ))


class OfferTagRetryTests(unittest.TestCase):
    def test_failed_offer_tag_retries_without_duplicate_offer_count(self):
        calls = []

        def post(endpoint, body):
            calls.append((endpoint, body))
            if len(calls) == 1:
                raise RuntimeError("temporary GHL failure")
            return {"ok": True}

        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "scout.json"
            with mock.patch.object(scout_triage, "STATE", state):
                engine = scout_triage.ScoutEngine(
                    ghl_get=lambda *a, **k: {},
                    ghl_post=post,
                    location_id="test",
                )
                msgs = [{"direction": "outbound",
                         "body": "my cash offer is $25,000",
                         "date": 1}]
                self.assertTrue(engine.scan_thread_offer("c1", "Test", msgs))
                self.assertEqual(1, engine.offers_today())
                self.assertFalse(engine.offers[0]["tagSynced"])

                self.assertFalse(engine.scan_thread_offer("c1", "Test", msgs))
                self.assertEqual(1, engine.offers_today())
                self.assertTrue(engine.offers[0]["tagSynced"])
                self.assertEqual(2, len(calls))


class LifecycleSyncTests(unittest.TestCase):
    def test_terminal_docusign_error_pauses_without_red_health(self):
        class FakeDeals:
            def __init__(self):
                self.row = {
                    "contactId": "c-terminal",
                    "contractStatus": "delivered",
                    "contractEnvelopeId": "missing-envelope",
                }

            def list_deals(self):
                return [dict(self.row)]

            def upsert(self, _contact_id, **fields):
                self.row.update({k: v for k, v in fields.items() if v is not None and v != ""})
                return self.row

            def unset(self, _contact_id, *names):
                for name in names:
                    self.row.pop(name, None)
                return self.row

            def set_contract(self, _contact_id, status, **_kwargs):
                self.row["contractStatus"] = status
                return self.row

        fake_deals = FakeDeals()
        fake_docusign = SimpleNamespace(
            configured=lambda: True,
            envelope_status=lambda _env: {
                "error": "DocuSign API 404: envelope does not exist or you have no rights"
            },
        )
        with mock.patch.object(connector, "deals", fake_deals), \
                mock.patch.object(connector, "docusign_io", fake_docusign):
            first = connector._contract_poll_once()
            second = connector._contract_poll_once()

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertIn("contractPollPausedAt", fake_deals.row)
        self.assertIn("contractPollPausedReason", fake_deals.row)

    def test_completed_contract_pipeline_sync_retries_after_failure(self):
        class FakeDeals:
            def __init__(self):
                self.rows = {"c1": {
                    "contactId": "c1",
                    "name": "Test Seller",
                    "contractStatus": "completed",
                    "assignmentFee": 10000,
                }}

            def list_deals(self):
                return [dict(v) for v in self.rows.values()]

            def get(self, contact_id):
                return self.rows.get(contact_id)

            def upsert(self, contact_id, **fields):
                self.rows.setdefault(contact_id, {"contactId": contact_id}).update(
                    {k: v for k, v in fields.items() if v is not None and v != ""}
                )
                return self.rows[contact_id]

            def unset(self, contact_id, *names):
                for name in names:
                    self.rows[contact_id].pop(name, None)
                return self.rows[contact_id]

            def set_contract(self, contact_id, status, **_kwargs):
                self.rows[contact_id]["contractStatus"] = status
                return self.rows[contact_id]

        class FakeScout:
            def __init__(self):
                self.calls = 0

            def advance_opp(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return {"error": "temporary GHL failure"}
                return {"ok": True, "stage": "Closed / Won", "action": "moved"}

        fake_deals = FakeDeals()
        fake_scout = FakeScout()
        fake_docusign = SimpleNamespace(configured=lambda: True)
        fake_bus = SimpleNamespace(send=lambda *a, **k: None)

        with mock.patch.object(connector, "deals", fake_deals), \
                mock.patch.object(connector, "SCOUT", fake_scout), \
                mock.patch.object(connector, "docusign_io", fake_docusign), \
                mock.patch.object(connector, "agent_bus", fake_bus):
            connector._contract_poll_once()
            self.assertNotIn("closedPipelineSyncedAt", fake_deals.rows["c1"])
            self.assertIn("closedPipelineSyncError", fake_deals.rows["c1"])

            connector._contract_poll_once()
            self.assertIn("closedPipelineSyncedAt", fake_deals.rows["c1"])
            self.assertNotIn("closedPipelineSyncError", fake_deals.rows["c1"])
            self.assertEqual(2, fake_scout.calls)

    def test_pipeline_sync_skip_does_not_retry_ghl(self):
        class FakeDeals:
            def __init__(self):
                self.row = {
                    "contactId": "test-1",
                    "contractStatus": "delivered",
                    "contractEnvelopeId": "env-1",
                    "pipelineSyncSkippedAt": 1,
                }

            def list_deals(self):
                return [dict(self.row)]

            def unset(self, _contact_id, *names):
                for name in names:
                    self.row.pop(name, None)
                return self.row

            def set_contract(self, _contact_id, status, **_kwargs):
                self.row["contractStatus"] = status
                return self.row

        fake_deals = FakeDeals()
        fake_scout = SimpleNamespace(
            advance_opp=mock.Mock(side_effect=AssertionError("must not sync"))
        )
        fake_docusign = SimpleNamespace(
            configured=lambda: True,
            envelope_status=lambda _env: {"status": "delivered"},
        )
        with mock.patch.object(connector, "deals", fake_deals), \
                mock.patch.object(connector, "SCOUT", fake_scout), \
                mock.patch.object(connector, "docusign_io", fake_docusign):
            result = connector._contract_poll_once()
        self.assertTrue(result["ok"])
        fake_scout.advance_opp.assert_not_called()

    def test_buyer_unassignment_clears_both_link_fields(self):
        class FakeDeals:
            def __init__(self):
                self.row = {"contactId": "c1", "assignedBuyerId": "b1",
                            "assignedBuyerName": "Buyer One"}

            def unset(self, _contact_id, *names):
                for name in names:
                    self.row.pop(name, None)
                return self.row

            def get(self, _contact_id):
                return self.row

        fake_deals = FakeDeals()
        with mock.patch.object(connector, "deals", fake_deals):
            result = connector.handle_buyers_assign(
                {"contactId": "c1", "buyerId": ""}
            )
        self.assertTrue(result["ok"])
        self.assertNotIn("assignedBuyerId", result["deal"])
        self.assertNotIn("assignedBuyerName", result["deal"])


class DocuSignTests(unittest.TestCase):
    def test_send_requires_envelope_id_before_reporting_success(self):
        with mock.patch.object(docusign_io, "configured", lambda: True), \
                mock.patch.object(docusign_io, "_api", lambda *a, **k: {"status": "sent"}):
            result = docusign_io.send_contract("seller@example.com", "Seller")
        self.assertIn("error", result)
        self.assertNotIn("ok", result)


class PipelineContactTests(unittest.TestCase):
    def test_invalid_contact_is_rejected_before_opportunity_create(self):
        post = mock.Mock()

        def get(endpoint, _params=None):
            if endpoint == "/opportunities/pipelines":
                return {"pipelines": [{
                    "id": "p1",
                    "name": "Wholesaling Pipeline",
                    "stages": [{"id": "s1", "name": "Under Contract"}],
                }]}
            if endpoint == "/opportunities/search":
                return {"opportunities": []}
            if endpoint == "/contacts/test-1":
                raise RuntimeError("400")
            return {}

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(scout_triage, "STATE", Path(td) / "scout.json"):
            engine = scout_triage.ScoutEngine(
                ghl_get=get,
                ghl_post=post,
                ghl_put=mock.Mock(),
                location_id="test",
            )
            result = engine.advance_opp("test-1", "contract")
        self.assertIn("stale or invalid", result["error"])
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
