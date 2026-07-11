import os
import tempfile
import unittest
from pathlib import Path

import toolkit_blast


class BlastSheetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_state = toolkit_blast.STATE
        self._orig_up = toolkit_blast.UPLOADS
        toolkit_blast.STATE = Path(self._tmp.name) / "toolkit_blast.json"
        toolkit_blast.UPLOADS = Path(self._tmp.name) / "uploads" / "deals"

    def tearDown(self):
        toolkit_blast.STATE = self._orig_state
        toolkit_blast.UPLOADS = self._orig_up
        self._tmp.cleanup()

    def test_build_sheet_hides_fee_uses_buyerprice(self):
        # deal has a saved toolkit snapshot: ARV 200k, buyer pays 110k, repairs 30k
        deal = {"contactId": "c1", "name": "Jane Seller",
                "address": "12 Main St, Dover, DE", "beds": 3, "baths": 2, "sqft": 1400,
                "condition": "needs full rehab", "arv": 200000, "repairs": 30000,
                "toolkitCalc": {"results": {"internal": {"buyerPrice": 110000}}}}
        s = toolkit_blast.build_sheet(deal, photos=["/uploads/deals/c1/1.jpg"])
        self.assertEqual(110000, s["purchase"])
        self.assertEqual(200000, s["arv"])
        self.assertNotIn("fee", s)
        self.assertNotIn("mao", s)
        self.assertEqual(["/uploads/deals/c1/1.jpg"], s["photos"])
        self.assertTrue(s["profit"] > 0)     # buyer_view profit

    def test_build_sheet_derives_purchase_from_mao_plus_fee(self):
        deal = {"contactId": "c2", "name": "Bob", "address": "9 Oak",
                "arv": 150000, "repairs": 20000, "mao": 90000, "assignmentFee": 10000}
        s = toolkit_blast.build_sheet(deal)
        self.assertEqual(100000, s["purchase"])   # mao + fee
        self.assertEqual([], s["photos"])

    def test_build_sheet_no_numbers_is_safe(self):
        s = toolkit_blast.build_sheet({"contactId": "c3", "name": "Al"})
        self.assertEqual("c3", s["dealId"])
        self.assertIsNone(s["purchase"])
        self.assertIsNone(s["profit"])

class BlastPhotoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_up = toolkit_blast.UPLOADS
        toolkit_blast.UPLOADS = Path(self._tmp.name) / "uploads" / "deals"

    def tearDown(self):
        toolkit_blast.UPLOADS = self._orig_up
        self._tmp.cleanup()

    # 1x1 transparent PNG
    _PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
            "AAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC")

    def test_save_and_list_photos(self):
        r = toolkit_blast.save_photos("c1", [self._PNG])
        self.assertTrue(r["ok"])
        self.assertEqual(1, len(r["photos"]))
        self.assertTrue(r["photos"][0].startswith("/uploads/deals/c1/"))
        self.assertTrue(r["photos"][0].endswith(".png"))
        self.assertEqual(r["photos"], toolkit_blast.list_photos("c1"))

    def test_save_rejects_non_image(self):
        r = toolkit_blast.save_photos("c2", ["data:text/plain;base64,aGk="])
        self.assertEqual(0, len(r["photos"]))
        self.assertEqual(1, r["skipped"])

    def test_save_requires_deal_id(self):
        self.assertIn("error", toolkit_blast.save_photos("", [self._PNG]))

    def test_list_photos_empty(self):
        self.assertEqual([], toolkit_blast.list_photos("nope"))

class BlastQueueTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_state = toolkit_blast.STATE
        toolkit_blast.STATE = Path(self._tmp.name) / "toolkit_blast.json"

    def tearDown(self):
        toolkit_blast.STATE = self._orig_state
        self._tmp.cleanup()

    def _deal(self):
        return {"contactId": "c1", "name": "Jane", "address": "12 Main, Dover DE",
                "arv": 200000, "repairs": 30000, "mao": 90000, "assignmentFee": 10000}

    def _matches(self):
        return [
            {"buyerId": "bob-llc", "name": "Bob", "score": 92, "fits": True,
             "buyer": {"phone": "3025551111", "email": "bob@x.com"}},
            {"buyerId": "sue-cap", "name": "Sue", "score": 70, "fits": True,
             "buyer": {"phone": "3025552222", "email": ""}},
        ]

    def test_create_blast_queues_recipients(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["sms"])
        self.assertEqual("queued", b["status"])
        self.assertEqual(2, len(b["recipients"]))
        self.assertTrue(b["id"])
        self.assertEqual("queued", b["recipients"][0]["status"])
        self.assertIn("100,000", b["recipients"][0]["smsDraft"])       # purchase price in the pitch
        self.assertEqual(b, toolkit_blast.get_blast(b["id"]))

    def test_create_blast_filters_by_buyer_ids(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches(),
                                       channels=["sms"], buyer_ids=["sue-cap"])
        self.assertEqual(1, len(b["recipients"]))
        self.assertEqual("sue-cap", b["recipients"][0]["buyerId"])

    def test_email_draft_has_subject_and_numbers(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["email"])
        r0 = b["recipients"][0]
        self.assertTrue(r0["emailSubject"])
        self.assertIn("200,000", r0["emailBody"])   # ARV in the body

    def test_create_blast_requires_matches(self):
        self.assertIn("error", toolkit_blast.create_blast(self._deal(), []))

    def test_list_blasts_newest_first(self):
        b1 = toolkit_blast.create_blast(self._deal(), self._matches())
        b2 = toolkit_blast.create_blast(self._deal(), self._matches())
        ids = [x["id"] for x in toolkit_blast.list_blasts()]
        self.assertEqual(ids[0], b2["id"])

    def test_send_blast_stub_marks_sent_no_real_send(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["sms"])
        r = toolkit_blast.send_blast(b["id"])
        self.assertTrue(r["ok"])
        self.assertEqual(2, r["summary"]["sent"])
        self.assertTrue(all(x["status"] == "stub-sent" for x in r["blast"]["recipients"]))
        self.assertEqual("sent", r["blast"]["status"])
        # persisted
        self.assertEqual("sent", toolkit_blast.get_blast(b["id"])["status"])

    def test_send_skips_recipient_missing_channel_contact(self):
        # Sue has no email -> emailing her is skipped, Bob sends
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["email"])
        toolkit_blast.set_recipient(b["id"], "sue-cap", channel="email")
        r = toolkit_blast.send_blast(b["id"])
        summ = r["summary"]
        self.assertEqual(1, summ["sent"])
        self.assertEqual(1, summ["skipped"])

    def test_record_response(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches())
        toolkit_blast.record_response(b["id"], "bob-llc", "interested")
        r0 = next(x for x in toolkit_blast.get_blast(b["id"])["recipients"]
                  if x["buyerId"] == "bob-llc")
        self.assertEqual("interested", r0["response"])

    def test_record_response_bad_verdict(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches())
        self.assertIn("error", toolkit_blast.record_response(b["id"], "bob-llc", "bogus"))

    def test_set_recipient_edits_draft(self):
        b = toolkit_blast.create_blast(self._deal(), self._matches())
        toolkit_blast.set_recipient(b["id"], "bob-llc", smsDraft="custom pitch")
        r0 = next(x for x in toolkit_blast.get_blast(b["id"])["recipients"]
                  if x["buyerId"] == "bob-llc")
        self.assertEqual("custom pitch", r0["smsDraft"])

    def test_send_missing_blast(self):
        self.assertIn("error", toolkit_blast.send_blast("nope"))


class BlastTransportTest(unittest.TestCase):
    """Live-transport hook (Open Decision #1 = GHL-native, env-gated)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_state = toolkit_blast.STATE
        toolkit_blast.STATE = Path(self._tmp.name) / "toolkit_blast.json"
        self._orig_hook = toolkit_blast._TRANSPORT
        self._orig_env = os.environ.pop(toolkit_blast.LIVE_ENV, None)

    def tearDown(self):
        toolkit_blast.STATE = self._orig_state
        toolkit_blast._TRANSPORT = self._orig_hook
        if self._orig_env is not None:
            os.environ[toolkit_blast.LIVE_ENV] = self._orig_env
        else:
            os.environ.pop(toolkit_blast.LIVE_ENV, None)
        self._tmp.cleanup()

    def _deal(self):
        return {"contactId": "c1", "name": "Jane", "address": "12 Main, Dover DE",
                "arv": 200000, "repairs": 30000, "mao": 90000, "assignmentFee": 10000}

    def _matches(self):
        return [{"buyerId": "bob-llc", "name": "Bob", "score": 92, "fits": True,
                 "buyer": {"phone": "3025551111", "email": "bob@x.com"}}]

    def test_stub_without_env_flag_even_if_hook_registered(self):
        calls = []
        toolkit_blast.register_transport(lambda r, s: calls.append(r) or {"ok": True})
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["sms"])
        r = toolkit_blast.send_blast(b["id"])
        self.assertFalse(r["live"])
        self.assertEqual([], calls)   # hook never fired
        self.assertEqual("stub-sent", r["blast"]["recipients"][0]["status"])

    def test_registered_transport_sends_when_live(self):
        os.environ[toolkit_blast.LIVE_ENV] = "1"
        sent = []
        toolkit_blast.register_transport(
            lambda r, s: sent.append((r["phone"], r["smsDraft"])) or
            {"ok": True, "note": "sent via GHL SMS"})
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["sms"])
        r = toolkit_blast.send_blast(b["id"])
        self.assertTrue(r["live"])
        self.assertEqual(1, len(sent))
        self.assertEqual("3025551111", sent[0][0])
        r0 = r["blast"]["recipients"][0]
        self.assertEqual("sent", r0["status"])         # NOT stub-sent
        self.assertEqual("sent via GHL SMS", r0["note"])

    def test_live_transport_error_marks_failed(self):
        os.environ[toolkit_blast.LIVE_ENV] = "1"

        def boom(recipient, sheet):
            raise RuntimeError("GHL 502")
        toolkit_blast.register_transport(boom)
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["sms"])
        r = toolkit_blast.send_blast(b["id"])
        self.assertEqual(1, r["summary"]["failed"])
        r0 = r["blast"]["recipients"][0]
        self.assertEqual("failed", r0["status"])
        self.assertIn("GHL 502", r0["note"])

    def test_live_flag_without_hook_falls_back_to_stub(self):
        os.environ[toolkit_blast.LIVE_ENV] = "1"
        toolkit_blast._TRANSPORT = None
        b = toolkit_blast.create_blast(self._deal(), self._matches(), channels=["sms"])
        r = toolkit_blast.send_blast(b["id"])
        self.assertEqual("stub-sent", r["blast"]["recipients"][0]["status"])


if __name__ == "__main__":
    unittest.main()
