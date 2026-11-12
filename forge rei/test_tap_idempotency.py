"""Second-tap safety for outward tap actions (plan Task 1, refs/02-idempotency.md U1-U3).

Every outward call is stubbed (GHL SMS post, Dyson ship/apply, Meta launch). State paths are
patched to a temp dir, so no live marcus_state file is read or written and nothing hits the network.
Run: cd "forge rei" && FORGE_MARCUS=0 python3 -m unittest test_tap_idempotency
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import action_log  # noqa: E402
import agency_dyson  # noqa: E402
import daycare_ads_autopilot as ap  # noqa: E402
import daycare_ads_tg as tg  # noqa: E402
import marcus_engine  # noqa: E402


class _TmpDir(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

    def patch(self, *a, **kw):
        p = mock.patch.object(*a, **kw)
        m = p.start()
        self.addCleanup(p.stop)
        return m


class MarcusApprove(_TmpDir):
    """U1: the SMS is out, then a later state write fails; a second tap must not re-send."""

    def setUp(self):
        super().setUp()
        for name in ("PROPOSALS_LOG", "HANDLED_LOG", "SEEN_CONTACTS_LOG", "CONFIG_FILE"):
            self.patch(marcus_engine, name, self.td / name.lower())
        self.patch(action_log, "record_result")
        env = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-dummy"})  # never read key files
        env.start()
        self.addCleanup(env.stop)

    def test_approve_second_tap_after_persist_failure_does_not_resend(self):
        sms = []

        def ghl_post(path, body):
            if path == "/conversations/messages":
                sms.append(body)
            return {}

        m = marcus_engine.MarcusEngine(ghl_get=lambda *a, **k: {}, ghl_post=ghl_post,
                                       location_id="loc")
        m.safety_check = lambda *a, **k: {"ok": True, "reservation": "r1"}
        m.safety_release = lambda *a, **k: None
        m.safety_record = lambda *a, **k: None
        m.proposals = {"p1": {
            "id": "p1", "conversationId": "v1", "contactId": "c1", "name": "Lead",
            "classification": "CONTINUE", "inbound": "yes",
            "suggestedReply": "sounds good when can we talk",
        }}
        with mock.patch.object(m, "_persist_proposal", side_effect=OSError("disk full")):
            m.approve("p1")
            second = m.approve("p1")
        self.assertEqual(1, len(sms), "second tap re-sent the seller SMS")
        self.assertIn("error", second)


class DysonDecision(_TmpDir):
    """U2: a Dyson draft that was already decided cannot be decided again."""

    def setUp(self):
        super().setUp()
        self.patch(agency_dyson, "STATE", self.td / "agency_dyson.json")
        agency_dyson._save({"drafts": [{"id": "d1", "status": "draft", "clientName": "C"}],
                            "seq": 1})
        self.apply = self.patch(agency_dyson, "apply", return_value={"ok": True})

    def _status(self):
        return agency_dyson._load()["drafts"][0]["status"]

    def test_dyson_reject_then_approve_refused(self):
        self.assertTrue(agency_dyson.decision("d1", "reject").get("ok"))
        res = agency_dyson.decision("d1", "approve")
        self.assertIn("error", res)
        self.apply.assert_not_called()          # a rejected draft never ships
        self.assertEqual("rejected", self._status())

    def test_dyson_approve_then_reject_refused(self):
        self.assertTrue(agency_dyson.decision("d1", "approve").get("ok"))
        res = agency_dyson.decision("d1", "reject")
        self.assertIn("error", res)
        self.assertEqual(1, self.apply.call_count)
        self.assertEqual("approved", self._status())


class AdsCards(_TmpDir):
    """U3: ads card claims fail closed on a failed write; stale launch cards are refused."""

    def setUp(self):
        super().setUp()
        self.patch(tg, "STORE", self.td / "cards.json")
        self.patch(tg, "_SYNC", True)
        self.patch(tg, "_send", return_value=None)
        self.patch(tg, "_send_undo_receipt", return_value=None)
        self.patch(ap, "get_mode", return_value="on")
        self.patch(ap, "launch_budgets", return_value=[10, 20])
        self.launch = self.patch(ap, "launch", return_value={"ok": True, "noop": True})

    def test_ads_claim_fails_closed_when_save_fails(self):
        card = tg._new("launch", "idea1", title="Ad")
        with mock.patch.object(tg.forge_atomic, "atomic_write_json",
                               side_effect=OSError("disk full")):
            claimed, err = tg._claim(card["id"], ("launch",))
            res = tg.h_launch(f"{card['id']}:10")
        self.assertIsNone(claimed)
        self.assertTrue(err)
        self.assertIn("error", res)
        self.launch.assert_not_called()

    def test_adslaunch_refuses_stale_card(self):
        card = tg._new("launch", "idea1", title="Ad")
        tg._set(card["id"], createdAt=int((time.time() - 7 * 3600) * 1000))
        res = tg.h_launch(f"{card['id']}:10")
        self.assertIn("error", res)
        self.assertIn("too old", res["error"])
        self.launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
