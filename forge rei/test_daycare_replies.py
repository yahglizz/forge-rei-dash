"""Self-check for daycare_replies: the GHL-automation yield rules, draft flags, and the
approve path's live re-check. No network, no Claude. Run: python3 test_daycare_replies.py"""
import os
import tempfile
from pathlib import Path

import daycare_replies as dr

NOW = 1_790_000_000.0          # a fixed epoch; hours checks are stubbed where needed
MIN = 60


def msg(i, direction, body, ago, source="", mtype="TYPE_SMS"):
    return {"id": f"m{i}", "direction": direction, "body": body, "source": source,
            "messageType": mtype, "dateAdded": int((NOW - ago) * 1000)}


def g(msgs, contact=None):
    return dr.gate(contact or {}, msgs, NOW)


def test_gate():
    parent = [msg(1, "inbound", "hi do you have infant openings?", 30 * MIN)]
    assert g(parent) == (True, None)
    # a person or workflow already answered
    assert g(parent + [msg(2, "outbound", "hey yes let me check", 10 * MIN)]) == (False, "answered")
    # grace window: GHL stop-on-response / live staff go first
    assert g([msg(1, "inbound", "hello?", 2 * MIN)]) == (False, "grace")
    # STOP/HELP belong to GHL keyword auto-replies; opt-out is forever
    assert g([msg(1, "inbound", "HELP", 30 * MIN)]) == (False, "keyword")
    assert g([msg(1, "inbound", "STOP", 30 * MIN)])[0] is False
    assert g([msg(1, "inbound", "stop texting me", 60 * MIN),
              msg(2, "inbound", "actually what are your hours", 30 * MIN)]) == (False, "opted_out")
    # not SMS -> Lead Desk handles it
    assert g([msg(1, "inbound", "hi", 30 * MIN, mtype="TYPE_LIVE_CHAT")]) == (False, "not_sms")
    # speed-to-lead owns the first touch
    lead = {"tags": ["form-type-new-inquiry", "speed-to-lead-trigger"],
            "dateAdded": int((NOW - 8 * MIN) * 1000)}
    assert g([msg(1, "inbound", "is this the daycare?", 6 * MIN)], lead) == (False, "stl_pending")
    queued = {"tags": ["form-type-new-inquiry", "speed-to-lead-queued"]}
    assert g([msg(1, "inbound", "hi", 30 * MIN)], queued) == (False, "stl_queued")
    # workflow sent the first touch, parent replied -> ours
    assert g([msg(1, "outbound", "Hi Tasha, this is management over at A Touch of Blessings",
                  60 * MIN, source="workflow"),
              msg(2, "inbound", "yes can we tour friday", 30 * MIN)], lead) == (True, None)
    assert g(parent, {"dnd": True}) == (False, "dnd")
    assert g([msg(1, "inbound", "hi", 9 * 86400)]) == (False, "stale")
    assert g([]) == (False, "no_thread")


def test_flags():
    assert dr.flags("call us at (215) 236-5439 or 215-787-0100") == []
    assert dr.flags("ELRC is 1-888-461-KIDS") == []
    assert dr.flags("call 267-457-0519") == ["unverified_phone"]
    assert dr.flags("its $250 a week") == ["money"]
    assert "long" in dr.flags("x" * 500)


class FakeClient:
    configured = True
    location_id = "loc"

    def __init__(self, convs, msgs):
        self.convs, self.msgs, self.sent = convs, msgs, []

    def get(self, ep, params=None):
        if ep == "/conversations/search":
            return {"conversations": self.convs}
        if ep.endswith("/messages"):
            return {"messages": {"messages": self.msgs}}
        if ep.startswith("/contacts/"):
            return {"contact": {"id": "c1", "tags": ["loc-921-n-18th", "daycare family"]}}
        return {}

    def post(self, ep, body):
        self.sent.append(body)
        return {"messageId": "sent1"}


def test_sweep_and_approve():
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    conv = {"id": "v1", "contactId": "c1", "lastMessageDirection": "inbound",
            "lastMessageDate": int((NOW - 30 * MIN) * 1000)}
    parent = [msg(1, "inbound", "she's sick today she won't be in", 30 * MIN)]
    fake = lambda contact, ev, now: {"action": "draft", "category": "logistics",
                                     "draft": "ok thank you for letting us know", "why": "",
                                     "unknowns": [], "flags": [], "model": "test"}
    cl = FakeClient([conv], parent)
    r = dr.run_once(cl, now=NOW, drafter=fake)
    assert r["drafted"] == 1, r
    assert dr.view()["pending"][0]["center"] == "921 N 18th St"
    # same inbound -> no second Claude call
    assert dr.run_once(cl, now=NOW, drafter=fake)["drafted"] == 0
    # approve: staff answered in GHL meanwhile -> refuse, retire, send nothing
    dr.daycare_leads.in_hours = lambda now: True
    cl.msgs = parent + [msg(2, "outbound", "feel better!", 5 * MIN)]
    out = dr.approve(cl, "c1", now=NOW)
    assert not out["ok"] and "already replied" in out["error"] and cl.sent == []
    # fresh draft, clean thread -> exactly one send
    cl.msgs = parent + [msg(2, "outbound", "feel better!", 20 * MIN),
                        msg(3, "inbound", "thank you, back tomorrow", 10 * MIN)]
    assert dr.run_once(cl, now=NOW, drafter=fake)["drafted"] == 1
    assert dr.approve(cl, "c1", now=NOW)["ok"] and len(cl.sent) == 1
    assert dr.approve(cl, "c1", now=NOW)["ok"] is False          # no double send
    # quiet hours block even the owner
    dr.daycare_leads.in_hours = lambda now: False
    cl.msgs = parent + [msg(4, "inbound", "one more question", 10 * MIN)]
    dr.run_once(cl, now=NOW, drafter=fake)
    assert "8am" in dr.approve(cl, "c1", now=NOW)["error"]


if __name__ == "__main__":
    os.environ.setdefault("FORGE_ACTION_LOG", str(Path(tempfile.mkdtemp()) / "a.jsonl"))
    test_gate()
    test_flags()
    test_sweep_and_approve()
    print("test_daycare_replies: all passed")
