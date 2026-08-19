"""test_portal_e2e.py — end-to-end check of the client-portal setup + connection stage.

Drives the REAL modules (no HTTP, no network): operator creates a client with portal
onboarding fields -> mints a link -> marks it sent -> the client bootstraps with that
token -> both sides exchange messages -> unread counts + read receipts behave.

Also pins the security invariants that matter most, because this is the one surface in
the whole system that faces the public internet:
  * client B's token cannot read or write client A's thread
  * a client cannot forge `from` / `clientId` in the payload
  * bootstrap never leaks contactEmail / contactPhone / portalToken / notes

Run: cd "forge rei" && python3 test_portal_e2e.py
"""
import tempfile
import unittest
from pathlib import Path

import agent_bus
import agency_io
import agency_messages_io
import agency_portal_io


class PortalEndToEndTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._orig_clients = agency_io.STATE
        self._orig_msgs = agency_messages_io.STATE
        # Redirect the bus too, or a test run prunes the operator's REAL bus history
        # (agent_bus keeps only the newest 200 notes).
        self._orig_bus = agent_bus.STATE
        agency_io.STATE = root / "agency.json"
        agency_messages_io.STATE = root / "agency_messages.json"
        agent_bus.STATE = root / "agent_bus.json"

    def tearDown(self):
        agency_io.STATE = self._orig_clients
        agency_messages_io.STATE = self._orig_msgs
        agent_bus.STATE = self._orig_bus
        self._tmp.cleanup()

    def _client(self, name, **portal):
        saved = agency_io.save_client({
            "name": name,
            "business": name + " LLC",
            "portal": {"welcome": "", "scope": "", "deliverables": "",
                       "contactEmail": "", "contactPhone": "", "startDate": "", **portal},
        })
        self.assertTrue(saved.get("ok"), saved)
        return saved["client"]

    # ---- the happy path the operator actually walks -------------------------
    def test_setup_to_conversation(self):
        c = self._client(
            "Dana Reyes",
            welcome="Hey Dana - this is your private line to me.",
            scope="5-page site + booking",
            deliverables="Homepage\nBooking form\nMonthly SEO",
            contactEmail="dana@example.com",
            contactPhone="555-0100",
        )
        cid = c["id"]

        # operator generates the shareable link
        li = agency_portal_io.link(cid, base="https://example.test:8443")
        self.assertTrue(li.get("ok"), li)
        self.assertIn("/portal#c=" + cid + "&k=", li["url"])
        token = li["portalToken"]

        # not sent yet
        self.assertEqual(agency_io.get_client(cid)["portal"]["status"], "draft")
        self.assertTrue(agency_io.mark_portal_sent(cid).get("ok"))
        sent = agency_io.get_client(cid)["portal"]
        self.assertEqual(sent["status"], "sent")
        self.assertTrue(sent["sentAt"])

        # client opens the link
        boot = agency_portal_io.bootstrap(cid, token)
        self.assertTrue(boot.get("ok"), boot)
        self.assertEqual(boot["clientName"], "Dana Reyes")
        self.assertEqual(boot["portal"]["welcome"], "Hey Dana - this is your private line to me.")
        self.assertEqual(boot["portal"]["scope"], "5-page site + booking")
        self.assertEqual(boot["messages"], [])

        # opening flips status to active and stamps openedAt exactly once
        after = agency_io.get_client(cid)["portal"]
        self.assertEqual(after["status"], "active")
        first_open = after["openedAt"]
        self.assertTrue(first_open)
        agency_portal_io.bootstrap(cid, token)
        self.assertEqual(agency_io.get_client(cid)["portal"]["openedAt"], first_open)

        # client talks, operator sees it unread
        sent_msg = agency_portal_io.send_message(cid, token, {"text": "Can we swap the hero photo?"})
        self.assertTrue(sent_msg.get("ok"), sent_msg)
        self.assertEqual(sent_msg["message"]["from"], "client")
        self.assertEqual(agency_messages_io.unread_counts()["byClient"].get(cid), 1)

        # operator replies, thread reads in order
        rep = agency_messages_io.send(cid, "operator", "On it - sending two options today.")
        self.assertTrue(rep.get("ok"), rep)
        thread = agency_messages_io.list_for_client(cid)["messages"]
        self.assertEqual([m["from"] for m in thread], ["client", "operator"])

        # operator reads -> badge clears
        agency_messages_io.mark_read(cid, "operator")
        self.assertEqual(agency_messages_io.unread_counts()["total"], 0)

        # the client sees the reply on their next poll
        self.assertEqual(len(agency_portal_io.bootstrap(cid, token)["messages"]), 2)

    # ---- security invariants ------------------------------------------------
    def test_cross_client_token_is_refused(self):
        a = self._client("Client A")
        b = self._client("Client B")
        tok_b = agency_portal_io.link(b["id"])["portalToken"]

        self.assertIn("error", agency_portal_io.bootstrap(a["id"], tok_b))
        self.assertIn("error", agency_portal_io.send_message(a["id"], tok_b, {"text": "hi"}))
        self.assertEqual(agency_messages_io.list_for_client(a["id"])["messages"], [])

    def test_client_cannot_forge_sender_or_owner(self):
        a = self._client("Client A")
        b = self._client("Client B")
        tok_a = agency_portal_io.link(a["id"])["portalToken"]

        res = agency_portal_io.send_message(a["id"], tok_a, {
            "text": "sneaky", "from": "operator", "sender": "operator", "clientId": b["id"],
        })
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res["message"]["from"], "client")
        self.assertEqual(res["message"]["clientId"], a["id"])
        self.assertEqual(agency_messages_io.list_for_client(b["id"])["messages"], [])

    def test_bootstrap_leaks_nothing_internal(self):
        c = self._client("Leak Check", contactEmail="private@example.com",
                         contactPhone="555-0199")
        agency_io.save_client({"id": c["id"], "name": "Leak Check",
                               "notes": "INTERNAL ONLY", "mrr": 4200})
        tok = agency_portal_io.link(c["id"])["portalToken"]
        boot = agency_portal_io.bootstrap(c["id"], tok)

        blob = repr(boot)
        for leak in ("private@example.com", "555-0199", tok, "INTERNAL ONLY", "4200"):
            self.assertNotIn(leak, blob, "portal bootstrap leaked: " + leak)
        self.assertEqual(set(boot["portal"]), {"welcome", "scope", "deliverables"})

    def test_deleting_a_client_deletes_their_conversation(self):
        """An orphaned thread keeps an unread badge alive for a client that no longer
        exists — the operator can never open it to clear it — and retains a deleted
        client's messages on disk. Deleting the client must delete the conversation."""
        c = self._client("Goodbye")
        tok = agency_portal_io.link(c["id"])["portalToken"]
        agency_portal_io.send_message(c["id"], tok, {"text": "hello"})
        self.assertEqual(agency_messages_io.unread_counts()["total"], 1)

        agency_io.delete_client(c["id"])
        agency_messages_io.purge_client(c["id"])

        self.assertEqual(agency_messages_io.unread_counts()["total"], 0)
        self.assertEqual(agency_messages_io.list_for_client(c["id"])["messages"], [])

    def test_empty_message_is_refused(self):
        c = self._client("Blank")
        tok = agency_portal_io.link(c["id"])["portalToken"]
        self.assertIn("error", agency_portal_io.send_message(c["id"], tok, {"text": "   "}))
        self.assertEqual(agency_messages_io.list_for_client(c["id"])["messages"], [])


if __name__ == "__main__":
    unittest.main()
