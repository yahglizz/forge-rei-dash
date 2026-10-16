"""Buyer blast transport goes through sms_guard (STOP/DNC, dupes, hours) like every other
send, skips GHL-DND contacts, and fails closed without the guard. GHL is faked; nothing
sends. HOME / vault / guard state point at a temp dir before connector is imported."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp()
os.environ["HOME"] = _TMP
os.environ.setdefault("FORGE_VAULT", os.path.join(_TMP, "vault"))
os.environ.setdefault("FORGE_MARCUS", "0")

import connector  # noqa: E402
import sms_guard  # noqa: E402

RECIP = {"channel": "sms", "phone": "+15555550123", "name": "Cash Buyer Bob",
         "smsDraft": "New deal: 3/1 in Toledo, reply if you want the sheet."}


class FakeGHL:
    def __init__(self, dnd=False):
        self.dnd, self.posts = dnd, []

    def __call__(self, path, body=None, **_kw):
        self.posts.append(path)
        if path == "/contacts/upsert":
            return {"contact": {"id": "buyer1", "dnd": self.dnd}}
        return {}

    def sends(self):
        return [p for p in self.posts if p == "/conversations/messages"]


class BlastGuard(unittest.TestCase):
    def _setup(self, thread=(), dnd=False):
        ghl = FakeGHL(dnd)
        td = Path(tempfile.mkdtemp(dir=_TMP))
        for p in (mock.patch.object(connector, "ghl_post", ghl),
                  mock.patch.object(connector, "_get_or_create_conversation", lambda cid: "conv1"),
                  mock.patch.object(connector.SCOUT, "_thread_transcript",
                                    lambda conv_id, **kw: list(thread)),
                  mock.patch.object(sms_guard, "STATE", td / "sms_guard.json"),
                  mock.patch.object(sms_guard.send_ledger, "STATE", td / "send_ledger.json"),
                  mock.patch.object(sms_guard, "_within_hours", lambda: True)):
            p.start()
            self.addCleanup(p.stop)
        return ghl

    def test_clean_buyer_sends_once_and_is_recorded(self):
        ghl = self._setup()
        r = connector._blast_transport(dict(RECIP), {})
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(ghl.sends()), 1)
        self.assertEqual(sms_guard._load().get("pending"), {})   # reservation committed

    def test_buyer_who_texted_stop_is_blocked(self):
        ghl = self._setup(thread=[{"direction": "inbound", "body": "STOP"}])
        r = connector._blast_transport(dict(RECIP), {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["gate"], "hard_no")
        self.assertEqual(ghl.sends(), [])

    def test_ghl_dnd_contact_is_skipped(self):
        ghl = self._setup(dnd=True)
        r = connector._blast_transport(dict(RECIP), {})
        self.assertTrue(r["skipped"])
        self.assertEqual(ghl.sends(), [])

    def test_pending_duplicate_is_blocked(self):
        ghl = self._setup()
        held = sms_guard.guard("buyer1", RECIP["smsDraft"], conv_id="conv1", kind="buyer_blast")
        self.assertTrue(held["ok"])
        r = connector._blast_transport(dict(RECIP), {})
        self.assertEqual(r["gate"], "pending_dedupe")
        self.assertEqual(ghl.sends(), [])

    def test_quiet_hours_block_before_any_ghl_write(self):
        ghl = self._setup()
        with mock.patch.object(sms_guard, "_within_hours", lambda: False):
            r = connector._blast_transport(dict(RECIP), {})
        self.assertFalse(r["ok"])
        self.assertEqual(ghl.posts, [])

    def test_missing_guard_fails_closed(self):
        ghl = self._setup()
        with mock.patch.object(sms_guard, "guard", None):
            r = connector._blast_transport(dict(RECIP), {})
        self.assertEqual(r["gate"], "sms_guard_missing")
        self.assertEqual(ghl.posts, [])


if __name__ == "__main__":
    unittest.main()
