"""Self-check for the daycare Messages tab (daycare_replies.inbox/thread/send_manual):
inbox mapping + the owner-typed send gates. No network. Run: python3 test_daycare_messages.py"""
import tempfile
from pathlib import Path

import daycare_replies as dr

NOW = 1_790_000_000.0


class Fake:
    configured = True
    location_id = "loc"

    def __init__(self, msgs, contact=None):
        self.msgs, self.contact, self.sent = msgs, contact or {}, []

    def get(self, ep, params=None):
        if ep == "/conversations/search":
            return {"conversations": [{
                "id": "conv1", "contactId": "c1", "fullName": "Tasha Reed", "phone": "+12155550100",
                "tags": ["loc-921-n-18th"], "lastMessageBody": "do you have infant spots?",
                "lastMessageDate": int(NOW * 1000), "lastMessageDirection": "inbound",
                "lastMessageType": "TYPE_SMS", "unreadCount": 2}]}
        if ep.endswith("/messages"):
            return {"messages": {"messages": self.msgs}}
        if ep.startswith("/contacts/"):
            return {"contact": {"id": "c1", "firstName": "Tasha", "tags": ["loc-921-n-18th"], **self.contact}}
        return {}

    def post(self, ep, body):
        self.sent.append(body)
        return {"messageId": "m9"}


def m(direction, body, ago=600):
    return {"id": body[:4], "direction": direction, "body": body, "messageType": "TYPE_SMS",
            "dateAdded": int((NOW - ago) * 1000)}


def main():
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    dr.daycare_leads.in_hours = lambda now: True

    box = dr.inbox(Fake([]))
    row = box["conversations"][0]
    assert row["name"] == "Tasha Reed" and row["center"] == "921 N 18th St"
    assert row["unread"] == 2 and row["type"] == "sms" and row["draft"] is False

    th = dr.thread(Fake([m("outbound", "hi!", 900), m("inbound", "any infant spots?")]), "c1", NOW)
    assert [x["dir"] for x in th["messages"]] == ["outbound", "inbound"] and th["canSend"]

    c = Fake([m("inbound", "any infant spots?")])
    assert dr.send_manual(c, "c1", "Yes! Want to tour Friday?", NOW)["ok"] and len(c.sent) == 1

    assert not dr.send_manual(c, "c1", "   ", NOW)["ok"]
    assert not dr.send_manual(c, "c1", "x" * 700, NOW)["ok"]

    c = Fake([m("inbound", "stop texting me")])
    assert "opted out" in dr.send_manual(c, "c1", "hello", NOW)["error"] and not c.sent

    c = Fake([m("inbound", "hi")], {"dnd": True})
    assert "Do Not Disturb" in dr.send_manual(c, "c1", "hello", NOW)["error"] and not c.sent
    assert dr.thread(c, "c1", NOW)["canSend"] is False

    dr.daycare_leads.in_hours = lambda now: False
    c = Fake([m("inbound", "hi")])
    assert "window" in dr.send_manual(c, "c1", "hello", NOW)["error"] and not c.sent

    # a manual send retires the pending Reply Desk draft so it can't be sent twice
    dr.daycare_leads.in_hours = lambda now: True
    dr._save({"drafts": {"c1": {"contactId": "c1", "status": "pending", "draft": "old"}}})
    assert dr.inbox(Fake([]))["conversations"][0]["draft"] is True
    dr.send_manual(Fake([m("inbound", "hi")]), "c1", "typed by owner", NOW)
    assert dr._load()["drafts"]["c1"]["status"] == "sent"
    print("test_daycare_messages: all passed")


if __name__ == "__main__":
    main()
