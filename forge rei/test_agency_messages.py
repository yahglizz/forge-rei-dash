"""test_agency_messages.py — the operator <-> client message thread.

Runnable spec for agency_messages_io + the portal's send_message scoping. The
security invariant (client B's token can never write to client A's thread, and a
payload cannot spoof clientId or sender) is the reason this file exists.

Run: python3 test_agency_messages.py
"""
import json
import tempfile
import unittest
from pathlib import Path

import agency_io
import agency_messages_io
import agency_portal_io
import agent_bus


class MessagesStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_msgs = agency_messages_io.STATE
        self._orig_clients = agency_io.STATE
        agency_messages_io.STATE = Path(self._tmp.name) / "agency_messages.json"
        agency_io.STATE = Path(self._tmp.name) / "agency.json"
        # send() broadcasts client messages on the bus — keep that off the live store.
        self._orig_bus = agent_bus.STATE
        agent_bus.STATE = Path(self._tmp.name) / "agent_bus.json"

    def tearDown(self):
        agency_messages_io.STATE = self._orig_msgs
        agency_io.STATE = self._orig_clients
        agent_bus.STATE = self._orig_bus
        self._tmp.cleanup()

    # --- store ------------------------------------------------------------
    def test_unknown_client_is_an_empty_thread_not_an_error(self):
        out = agency_messages_io.list_for_client("nobody")
        self.assertEqual([], out["messages"])
        self.assertEqual(0, out["unread"])
        self.assertNotIn("error", out)
        self.assertEqual({"ok": True, "byClient": {}, "total": 0},
                         agency_messages_io.unread_counts())

    def test_both_directions_land_in_order_with_unread_counts(self):
        agency_messages_io.send("c1", "client", "Can you update the hero?", "Bloom")
        agency_messages_io.send("c1", "operator", "On it — shipping tonight.")
        agency_messages_io.send("c1", "client", "Perfect, thank you.", "Bloom")

        out = agency_messages_io.list_for_client("c1")
        self.assertEqual(["client", "operator", "client"],
                         [m["from"] for m in out["messages"]])
        self.assertEqual("Can you update the hero?", out["messages"][0]["text"])
        # Only the client's two messages are unread by the operator.
        self.assertEqual(2, out["unread"])
        self.assertEqual({"ok": True, "byClient": {"c1": 2}, "total": 2},
                         agency_messages_io.unread_counts())

    def test_message_record_shape_and_read_flags(self):
        msg = agency_messages_io.send("c1", "client", "hello")["message"]
        self.assertEqual({"id", "clientId", "from", "text", "ts",
                          "readByOperator", "readByClient"}, set(msg))
        self.assertEqual("c1", msg["clientId"])
        self.assertTrue(msg["readByClient"])
        self.assertFalse(msg["readByOperator"])
        self.assertIsInstance(msg["ts"], int)

        op = agency_messages_io.send("c1", "operator", "hi back")["message"]
        self.assertTrue(op["readByOperator"])
        self.assertFalse(op["readByClient"])

    def test_client_message_hits_the_bus_operator_message_does_not(self):
        """The bus note is what makes Telegram ping — it must fire inbound only."""
        agency_messages_io.send("c1", "operator", "outbound")
        self.assertEqual([], agent_bus.recent()["messages"])
        agency_messages_io.send("c1", "client", "inbound", "Bloom Dental")
        notes = agent_bus.recent()["messages"]
        self.assertEqual(1, len(notes))
        self.assertEqual("portal", notes[0]["from"])
        self.assertIn("Bloom Dental", notes[0]["text"])
        self.assertEqual({"type": "client_message", "clientId": "c1"},
                         notes[0]["data"])

    def test_mark_read_operator_zeroes_the_unread_count(self):
        agency_messages_io.send("c1", "client", "one")
        agency_messages_io.send("c1", "client", "two")
        self.assertEqual(2, agency_messages_io.list_for_client("c1")["unread"])

        marked = agency_messages_io.mark_read("c1", "operator")
        self.assertEqual({"ok": True, "marked": 2}, marked)
        self.assertEqual(0, agency_messages_io.list_for_client("c1")["unread"])
        self.assertEqual({}, agency_messages_io.unread_counts()["byClient"])
        # Idempotent — a second pass marks nothing.
        self.assertEqual(0, agency_messages_io.mark_read("c1", "operator")["marked"])

    def test_cap_drops_the_oldest(self):
        for i in range(agency_messages_io.MAX_PER_THREAD + 5):
            agency_messages_io.send("c1", "client", f"msg {i}")
        msgs = agency_messages_io.list_for_client("c1")["messages"]
        self.assertEqual(agency_messages_io.MAX_PER_THREAD, len(msgs))
        self.assertEqual("msg 5", msgs[0]["text"])
        self.assertEqual(f"msg {agency_messages_io.MAX_PER_THREAD + 4}",
                         msgs[-1]["text"])

    def test_empty_and_whitespace_text_is_rejected(self):
        for bad in ("", "   ", "\n\t ", None):
            self.assertEqual({"error": "message is empty"},
                             agency_messages_io.send("c1", "client", bad))
        self.assertEqual([], agency_messages_io.list_for_client("c1")["messages"])

    def test_bad_sender_and_missing_client_are_rejected(self):
        self.assertEqual({"error": "invalid sender"},
                         agency_messages_io.send("c1", "admin", "sneaky"))
        self.assertEqual({"error": "clientId required"},
                         agency_messages_io.send("", "client", "hi"))
        self.assertEqual([], agency_messages_io.list_for_client("c1")["messages"])

    def test_text_is_capped(self):
        msg = agency_messages_io.send("c1", "client", "x" * 5000)["message"]
        self.assertEqual(agency_messages_io.MAX_TEXT, len(msg["text"]))

    def test_reset_clears_every_thread(self):
        agency_messages_io.send("c1", "client", "a")
        agency_messages_io.send("c2", "operator", "b")
        self.assertEqual({"ok": True, "cleared": 2}, agency_messages_io.reset())
        self.assertEqual([], agency_messages_io.list_for_client("c1")["messages"])


class PortalScopingTest(unittest.TestCase):
    """The security invariant: a portal token unlocks exactly ONE thread."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_msgs = agency_messages_io.STATE
        self._orig_clients = agency_io.STATE
        agency_messages_io.STATE = Path(self._tmp.name) / "agency_messages.json"
        agency_io.STATE = Path(self._tmp.name) / "agency.json"
        # send() broadcasts client messages on the bus — keep that off the live store.
        self._orig_bus = agent_bus.STATE
        agent_bus.STATE = Path(self._tmp.name) / "agent_bus.json"
        self.a = agency_io.save_client({"name": "Client A"})["client"]
        self.b = agency_io.save_client({"name": "Client B"})["client"]
        self.tok_a = agency_io.ensure_portal_token(self.a["id"])["portalToken"]
        self.tok_b = agency_io.ensure_portal_token(self.b["id"])["portalToken"]

    def tearDown(self):
        agency_messages_io.STATE = self._orig_msgs
        agency_io.STATE = self._orig_clients
        agent_bus.STATE = self._orig_bus
        self._tmp.cleanup()

    def test_wrong_token_writes_nothing(self):
        out = agency_portal_io.send_message(self.a["id"], self.tok_b,
                                            {"text": "let me in"})
        self.assertEqual({"error": "invalid or expired link"}, out)
        self.assertEqual([], agency_messages_io.list_for_client(self.a["id"])["messages"])
        self.assertEqual([], agency_messages_io.list_for_client(self.b["id"])["messages"])
        self.assertEqual(0, agency_messages_io.unread_counts()["total"])

    def test_payload_cannot_spoof_client_or_sender(self):
        out = agency_portal_io.send_message(self.b["id"], self.tok_b, {
            "text": "spoof attempt",
            "clientId": self.a["id"],
            "from": "operator",
            "sender": "operator",
        })
        self.assertTrue(out.get("ok"))
        self.assertEqual(self.b["id"], out["message"]["clientId"])
        self.assertEqual("client", out["message"]["from"])
        self.assertFalse(out["message"]["readByOperator"])
        # Client A's thread was never touched.
        self.assertEqual([], agency_messages_io.list_for_client(self.a["id"])["messages"])
        self.assertEqual({self.b["id"]: 1},
                         agency_messages_io.unread_counts()["byClient"])

    def test_bootstrap_scopes_messages_and_leaks_nothing(self):
        agency_io.save_client({
            "id": self.a["id"], "name": "Client A",
            "notes": "internal only",
            "portal": {"welcome": "Hi!", "scope": "Website + SEO",
                       "deliverables": "5 pages",
                       "contactEmail": "a@example.com",
                       "contactPhone": "555-0100", "startDate": "2026-09-01"},
        })
        agency_messages_io.send(self.a["id"], "operator", "welcome aboard")
        agency_messages_io.send(self.b["id"], "operator", "not for A")

        boot = agency_portal_io.bootstrap(self.a["id"], self.tok_a)
        self.assertTrue(boot.get("ok"))
        self.assertEqual(["welcome aboard"], [m["text"] for m in boot["messages"]])
        self.assertEqual({"welcome": "Hi!", "scope": "Website + SEO",
                          "deliverables": "5 pages"}, boot["portal"])

        blob = json.dumps(boot)
        for secret in ("a@example.com", "555-0100", "2026-09-01",
                       self.tok_a, "internal only", "not for A"):
            self.assertNotIn(secret, blob)

    def test_bootstrap_marks_opened_and_clears_the_client_unread(self):
        agency_messages_io.send(self.a["id"], "operator", "ping")
        self.assertEqual("draft", agency_io.get_client(self.a["id"])["portal"]["status"])

        boot = agency_portal_io.bootstrap(self.a["id"], self.tok_a)
        self.assertTrue(boot.get("ok"))
        portal = agency_io.get_client(self.a["id"])["portal"]
        self.assertEqual("active", portal["status"])
        opened = portal["openedAt"]
        self.assertIsInstance(opened, int)
        # Idempotent: a second open does not re-stamp.
        agency_portal_io.bootstrap(self.a["id"], self.tok_a)
        self.assertEqual(opened, agency_io.get_client(self.a["id"])["portal"]["openedAt"])

    def test_operator_save_does_not_clobber_the_link_lifecycle(self):
        sent = agency_io.mark_portal_sent(self.a["id"])["client"]["portal"]
        self.assertEqual("sent", sent["status"])
        self.assertIsInstance(sent["sentAt"], int)

        after = agency_io.save_client({"id": self.a["id"], "name": "Client A",
                                       "portal": {"welcome": "edited"}})["client"]["portal"]
        self.assertEqual("edited", after["welcome"])
        self.assertEqual("sent", after["status"])
        self.assertEqual(sent["sentAt"], after["sentAt"])


if __name__ == "__main__":
    unittest.main()
