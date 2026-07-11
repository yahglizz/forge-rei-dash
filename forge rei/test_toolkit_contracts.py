import tempfile
import unittest
from pathlib import Path
from unittest import mock

import toolkit_contracts


class ContractTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_state = toolkit_contracts.STATE
        toolkit_contracts.STATE = Path(self._tmp.name) / "contracts.json"
        self.now = 1_720_000_000_000
        self.deal = {
            "contactId": "c123",
            "name": "Jane Seller",
            "email": "jane@example.com",
            "address": "12 Main, Dover DE",
            "assignedBuyerName": "Acme Home Buyers LLC",
            "purchasePrice": 95_000,
            "earnestMoney": 2_500,
            "closingDate": "2026-08-01",
            "dealType": "sfr",
        }

    def tearDown(self):
        toolkit_contracts.STATE = self._orig_state
        self._tmp.cleanup()

    def create(self, deal_id="c123", template_type="sfr", approval_required=True):
        return toolkit_contracts.create_contract(deal_id, self.deal, template_type, approval_required)

    def test_empty_contract_store_is_safe(self):
        self.assertEqual([], toolkit_contracts.list_contracts())
        self.assertIsNone(toolkit_contracts.get_contract("missing"))

    def test_prefill_from_deal_extracts_signer_property_price_and_terms(self):
        prefill = toolkit_contracts.prefill_from_deal(self.deal)
        self.assertEqual("Jane Seller", prefill["signerName"])
        self.assertEqual("jane@example.com", prefill["signerEmail"])
        self.assertEqual("Acme Home Buyers LLC", prefill["buyerName"])
        self.assertEqual("12 Main, Dover DE", prefill["propertyAddress"])
        self.assertEqual("$95,000", prefill["purchasePrice"])
        self.assertEqual("$2,500", prefill["terms"]["earnestMoney"])
        self.assertEqual("2026-08-01", prefill["terms"]["closingDate"])
        self.assertEqual("$95,000", prefill["tabs"]["purchase_price"])

    def test_create_contract_is_pending_and_persisted(self):
        with mock.patch.object(toolkit_contracts, "_now", return_value=self.now), \
                mock.patch.object(toolkit_contracts, "_template_id", return_value="template-sfr"):
            contract = self.create()
        self.assertEqual("c123", contract["dealId"])
        self.assertEqual("pending", contract["status"])
        self.assertTrue(contract["approvalRequired"])
        self.assertEqual("template-sfr", contract["templateId"])
        self.assertEqual("Jane Seller", contract["prefill"]["signerName"])
        self.assertEqual(contract, toolkit_contracts.get_contract("c123"))

    def test_create_requires_deal_and_known_template_type(self):
        self.assertIn("error", self.create(deal_id=""))
        self.assertIn("error", self.create(template_type="condo"))

    def test_list_filters_and_sorts_by_updated_time(self):
        with mock.patch.object(toolkit_contracts, "_now", side_effect=[100, 200]):
            self.create("c123")
            toolkit_contracts.create_contract("c456", {"name": "Bob"}, "land")
        toolkit_contracts.void_contract("c123", "Seller withdrew")
        self.assertEqual(["c456"], [c["dealId"] for c in toolkit_contracts.list_contracts("pending")])
        self.assertEqual(["c123"], [c["dealId"] for c in toolkit_contracts.list_contracts("voided")])

    def test_template_list_uses_sandbox_catalog_and_deal_type_mapping(self):
        with mock.patch.object(toolkit_contracts.docusign_io, "is_sandbox", return_value=True), \
                mock.patch.object(toolkit_contracts.docusign_io, "configured", return_value=True), \
                mock.patch.object(toolkit_contracts.docusign_io, "template_map", return_value={"sfr": "sfr-id", "multi": "", "land": "land-id"}), \
                mock.patch.object(toolkit_contracts.docusign_io, "list_templates", return_value=[{"id": "sfr-id", "name": "Ohio SFR"}]):
            rows = toolkit_contracts.template_list()
        self.assertEqual("sfr-id", next(row for row in rows if row["type"] == "sfr")["id"])
        self.assertEqual("Ohio SFR", next(row for row in rows if row["type"] == "sfr")["name"])
        self.assertFalse(next(row for row in rows if row["type"] == "multi")["configured"])

    def test_send_requires_operator_approval_and_sandbox(self):
        self.create()
        self.assertIn("error", toolkit_contracts.send_contract("c123", ""))
        with mock.patch.object(toolkit_contracts.docusign_io, "is_sandbox", return_value=False):
            result = toolkit_contracts.send_contract("c123", "operator-1")
        self.assertIn("sandbox", result["error"].lower())
        self.assertEqual("pending", toolkit_contracts.get_contract("c123")["status"])

    def test_send_contract_calls_docusign_and_tracks_operator_approval(self):
        with mock.patch.object(toolkit_contracts, "_template_id", return_value="template-sfr"):
            self.create()
        with mock.patch.object(toolkit_contracts, "_now", return_value=self.now), \
                mock.patch.object(toolkit_contracts.docusign_io, "is_sandbox", return_value=True), \
                mock.patch.object(toolkit_contracts.docusign_io, "configured", return_value=True), \
                mock.patch.object(toolkit_contracts.docusign_io, "send_contract", return_value={"ok": True, "envelopeId": "env-123", "status": "sent"}) as send:
            result = toolkit_contracts.send_contract("c123", "operator-1", "Reviewed numbers")
        self.assertTrue(result["ok"])
        send.assert_called_once()
        record = toolkit_contracts.get_contract("c123")
        self.assertEqual("sent", record["status"])
        self.assertEqual("env-123", record["envelopeId"])
        self.assertEqual("operator-1", record["approvedBy"])
        self.assertEqual("Reviewed numbers", record["approvalReason"])

    def test_send_failure_leaves_contract_pending_with_error(self):
        self.create()
        with mock.patch.object(toolkit_contracts.docusign_io, "is_sandbox", return_value=True), \
                mock.patch.object(toolkit_contracts.docusign_io, "configured", return_value=True), \
                mock.patch.object(toolkit_contracts.docusign_io, "send_contract", return_value={"error": "JWT denied"}):
            result = toolkit_contracts.send_contract("c123", "operator-1")
        self.assertIn("error", result)
        record = toolkit_contracts.get_contract("c123")
        self.assertEqual("pending", record["status"])
        self.assertIn("JWT denied", record["sendError"])

    def test_status_tracking_and_void_are_persisted(self):
        self.create("c123")
        self.assertEqual("signed", toolkit_contracts.mark_signed("c123")["status"])
        self.assertEqual("completed", toolkit_contracts.mark_completed("c123")["status"])
        self.create("c456", "land")
        voided = toolkit_contracts.void_contract("c456", "Seller withdrew")
        self.assertEqual("voided", voided["status"])
        self.assertEqual("Seller withdrew", voided["voidReason"])

    def test_assignment_template_in_catalog_and_creatable(self):
        self.assertIn("assignment", toolkit_contracts._TEMPLATES)
        with mock.patch.object(toolkit_contracts.docusign_io, "is_sandbox", return_value=True), \
                mock.patch.object(toolkit_contracts.docusign_io, "configured", return_value=False):
            types = {row["type"] for row in toolkit_contracts.template_list()}
        self.assertIn("assignment", types)
        contract = self.create("c789", "assignment")
        self.assertEqual("assignment", contract["templateType"])
        self.assertEqual("pending", contract["status"])

    def test_assignment_prefill_signs_assignee_and_maps_fee(self):
        deal = dict(self.deal, assignmentFee=12_000,
                    buyerEmail="acme@example.com", contractDate="2026-07-05")
        prefill = toolkit_contracts.prefill_from_deal(deal, template_type="assignment")
        # the ASSIGNEE (end buyer) signs the assignment, not the seller
        self.assertEqual("Acme Home Buyers LLC", prefill["signerName"])
        self.assertEqual("acme@example.com", prefill["signerEmail"])
        tabs = prefill["tabs"]
        self.assertEqual("Acme Home Buyers LLC", tabs["assignee_name"])
        self.assertEqual("$12,000", tabs["assignment_fee"])
        self.assertEqual("$95,000", tabs["original_purchase_price"])
        self.assertEqual("2026-07-05", tabs["original_contract_date"])
        self.assertEqual("12 Main, Dover DE", tabs["property_address"])

    def test_assignment_create_uses_assignment_prefill(self):
        self.deal.update(assignmentFee=12_000, buyerEmail="acme@example.com")
        contract = self.create("c789", "assignment")
        self.assertEqual("acme@example.com", contract["prefill"]["signerEmail"])
        self.assertIn("assignment_fee", contract["prefill"]["tabs"])

    def test_sfr_prefill_never_exposes_assignment_fee(self):
        deal = dict(self.deal, assignmentFee=12_000)
        prefill = toolkit_contracts.prefill_from_deal(deal, template_type="sfr")
        self.assertNotIn("assignment_fee", prefill["tabs"])
        # default (no template_type) stays the seller PA shape too
        default = toolkit_contracts.prefill_from_deal(deal)
        self.assertNotIn("assignment_fee", default["tabs"])
        self.assertEqual("Jane Seller", default["signerName"])


class UploadedTemplateTest(unittest.TestCase):
    """Operator-uploaded templates + quick send (2026-07-11)."""

    PDF_URL = ("data:application/pdf;base64,"
               + __import__("base64").b64encode(b"%PDF-1.4 test\n%%EOF").decode())

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = (toolkit_contracts.STATE, toolkit_contracts.TEMPLATES_STATE,
                      toolkit_contracts.TEMPLATES_DIR)
        toolkit_contracts.STATE = Path(self._tmp.name) / "contracts.json"
        toolkit_contracts.TEMPLATES_STATE = Path(self._tmp.name) / "toolkit_templates.json"
        toolkit_contracts.TEMPLATES_DIR = Path(self._tmp.name) / "contract_templates"

    def tearDown(self):
        (toolkit_contracts.STATE, toolkit_contracts.TEMPLATES_STATE,
         toolkit_contracts.TEMPLATES_DIR) = self._orig
        self._tmp.cleanup()

    def test_save_list_delete_roundtrip(self):
        saved = toolkit_contracts.save_template("Ohio PA", self.PDF_URL)
        self.assertTrue(saved.get("ok"), saved)
        tid = saved["template"]["id"]
        self.assertEqual("pdf", saved["template"]["ext"])
        rows = toolkit_contracts.list_uploaded_templates()["templates"]
        self.assertTrue(any(r["id"] == tid for r in rows))
        self.assertTrue((toolkit_contracts.TEMPLATES_DIR / f"{tid}.pdf").exists())
        self.assertTrue(toolkit_contracts.delete_template(tid).get("ok"))
        self.assertFalse((toolkit_contracts.TEMPLATES_DIR / f"{tid}.pdf").exists())

    def test_rejects_non_document_uploads(self):
        bad = toolkit_contracts.save_template("x", "data:image/png;base64,AAAA")
        self.assertIn("error", bad)
        bad2 = toolkit_contracts.save_template("x", "not a data url")
        self.assertIn("error", bad2)

    def test_quick_send_requires_operator(self):
        out = toolkit_contracts.quick_send({"templateId": "t1",
                                            "sellerEmail": "a@b.com"})
        self.assertEqual("operator approval required", out["error"])

    def test_quick_send_is_sandbox_gated(self):
        saved = toolkit_contracts.save_template("PA", self.PDF_URL)
        with mock.patch.object(toolkit_contracts.docusign_io, "is_sandbox",
                               return_value=False):
            out = toolkit_contracts.quick_send({
                "templateId": saved["template"]["id"], "operatorId": "Y",
                "sellerEmail": "a@b.com", "sellerName": "A"})
        self.assertIn("sandbox-only", out["error"])

    def test_quick_send_records_ledger_row(self):
        saved = toolkit_contracts.save_template("PA", self.PDF_URL)
        with mock.patch.object(toolkit_contracts.docusign_io, "is_sandbox",
                               return_value=True), \
             mock.patch.object(toolkit_contracts.docusign_io, "configured",
                               return_value=True), \
             mock.patch.object(toolkit_contracts.docusign_io, "send_document",
                               return_value={"ok": True, "envelopeId": "env-9"}) as sd:
            out = toolkit_contracts.quick_send({
                "templateId": saved["template"]["id"], "operatorId": "Yahjair",
                "sellerName": "Jane Seller", "sellerEmail": "jane@example.com",
                "address": "12 Main, Dover DE", "price": 95000,
                "closingDate": "2026-08-01"})
        self.assertTrue(out.get("ok"), out)
        self.assertEqual("env-9", out["envelopeId"])
        # the email carries the deal terms
        kwargs = sd.call_args.kwargs
        self.assertIn("12 Main, Dover DE", kwargs["email_subject"])
        self.assertIn("$95,000", kwargs["email_blurb"])
        # ledger row is trackable by the existing list/status flows
        row = toolkit_contracts.list_contracts()[0]
        self.assertEqual("sent", row["status"])
        self.assertEqual("custom", row["templateType"])
        self.assertEqual("env-9", row["envelopeId"])
        self.assertEqual("Yahjair", row["approvedBy"])

    def test_quick_send_failure_keeps_pending_row_with_error(self):
        """Audit F7: the ledger row is persisted BEFORE the DocuSign call, so a
        failed (or crashed) send still leaves a trackable pending record."""
        saved = toolkit_contracts.save_template("PA", self.PDF_URL)
        with mock.patch.object(toolkit_contracts.docusign_io, "is_sandbox",
                               return_value=True), \
             mock.patch.object(toolkit_contracts.docusign_io, "configured",
                               return_value=True), \
             mock.patch.object(toolkit_contracts.docusign_io, "send_document",
                               return_value={"error": "boom"}):
            out = toolkit_contracts.quick_send({
                "templateId": saved["template"]["id"], "operatorId": "Yahjair",
                "sellerName": "Jane Seller", "sellerEmail": "jane@example.com",
                "address": "12 Main, Dover DE", "price": 95000})
        self.assertEqual("boom", out["error"])
        row = toolkit_contracts.list_contracts()[0]
        self.assertEqual("pending", row["status"])
        self.assertEqual("boom", row["sendError"])
        self.assertIsNone(row["envelopeId"])


if __name__ == "__main__":
    unittest.main()
