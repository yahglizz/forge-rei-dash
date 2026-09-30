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
    assert g([msg(1, "inbound", "hello?", 60)]) == (False, "grace")          # <90 s: wait
    assert g([msg(1, "inbound", "hello?", 2 * MIN)]) == (True, None)         # >90 s: answer — inside 5 min
    # STOP/HELP belong to GHL keyword auto-replies; opt-out is forever
    assert g([msg(1, "inbound", "HELP", 30 * MIN)]) == (False, "keyword")
    assert g([msg(1, "inbound", "STOP", 30 * MIN)])[0] is False
    assert g([msg(1, "inbound", "stop texting me", 60 * MIN),
              msg(2, "inbound", "actually what are your hours", 30 * MIN)]) == (False, "opted_out")
    # not SMS -> Lead Desk handles it
    assert g([msg(1, "inbound", "hi", 30 * MIN, mtype="TYPE_LIVE_CHAT")]) == (False, "not_sms")
    # speed-to-lead owns the first touch
    lead = {"tags": ["form-type-new-inquiry", "speed-to-lead-trigger"],
            "dateAdded": int((NOW - 4 * MIN) * 1000)}
    assert g([msg(1, "inbound", "is this the daycare?", 2 * MIN)], lead) == (False, "stl_pending")
    stale_lead = dict(lead, dateAdded=int((NOW - 9 * MIN) * 1000))            # workflow never fired
    assert g([msg(1, "inbound", "is this the daycare?", 2 * MIN)], stale_lead) == (True, None)
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
    conv["lastMessageDate"] = int((NOW - 10 * MIN) * 1000)
    cl.msgs = parent + [msg(2, "outbound", "feel better!", 20 * MIN),
                        msg(3, "inbound", "thank you, back tomorrow", 10 * MIN)]
    assert dr.run_once(cl, now=NOW, drafter=fake)["drafted"] == 1
    assert dr.approve(cl, "c1", now=NOW)["ok"] and len(cl.sent) == 1
    assert dr.approve(cl, "c1", now=NOW)["ok"] is False          # no double send
    # quiet hours block even the owner
    dr.daycare_leads.in_hours = lambda now: False
    conv["lastMessageDate"] = int((NOW - 5 * MIN) * 1000)
    cl.msgs = parent + [msg(4, "inbound", "one more question", 5 * MIN)]
    dr.run_once(cl, now=NOW, drafter=fake)
    assert "8am" in dr.approve(cl, "c1", now=NOW)["error"]


def test_auto_send():
    # pure eligibility: a clean enrollment-lead answer only
    ok = {"action": "draft", "category": "tour", "draft": "we'd love to show you around", "flags": []}
    assert dr.auto_eligible(ok, "lead")
    assert not dr.auto_eligible(ok, "family")                                  # enrolled family: owner
    assert not dr.auto_eligible(dict(ok, flags=["money"]), "lead")             # flagged: owner
    assert not dr.auto_eligible(dict(ok, category="billing"), "lead")          # off-limits topic
    assert not dr.auto_eligible(dict(ok, action="escalate"), "lead")
    assert not dr.auto_eligible(dict(ok, draft=" "), "lead")
    for bad in ("safety", "custody", "medical", "complaint", "billing", "hiring", "other", "logistics"):
        assert bad not in dr.AUTO_SAFE_CATEGORIES, bad
    # end to end: ON sends once inside hours, respects cap + per-contact limit; OFF sends nothing
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    dr.daycare_leads.in_hours = lambda now: True
    dr._contact = lambda client, cid: {"id": cid, "tags": ["form-type-new-inquiry"]}
    conv = {"id": "v1", "contactId": "c1", "lastMessageDirection": "inbound",
            "lastMessageDate": int((NOW - 3 * MIN) * 1000)}
    parent = [msg(1, "inbound", "do you take ccis?", 3 * MIN)]
    fake = lambda contact, ev, now: {"action": "draft", "category": "subsidy", "flags": [], "why": "",
                                     "draft": "yes we do — how old is your little one?",
                                     "unknowns": [], "model": "t"}
    cl = FakeClient([conv], parent)
    dr.AUTO = False
    r = dr.run_once(cl, now=NOW, drafter=fake)
    assert r["drafted"] == 1 and cl.sent == [] and r["auto"]["sent"] == 0      # default: draft only
    dr.AUTO = True
    assert dr.auto_send(cl, NOW)["sent"] == 1 and len(cl.sent) == 1
    assert dr.view(NOW)["auto"]["sentToday"] == 1
    assert dr.auto_send(cl, NOW)["sent"] == 0 and len(cl.sent) == 1            # no double send
    dr.AUTO = False


def test_ai_down_stops_sweep():
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    convs = [{"id": f"v{i}", "contactId": f"c{i}", "lastMessageDirection": "inbound",
              "lastMessageDate": int((NOW - 30 * MIN) * 1000)} for i in range(3)]
    calls = []

    def broke(contact, ev, now):
        calls.append(1)
        raise RuntimeError("Anthropic API error (400): Your credit balance is too low")
    r = dr.run_once(FakeClient(convs, [msg(1, "inbound", "hi are you open", 30 * MIN)]),
                    now=NOW, drafter=broke)
    assert len(calls) == 1 and "credit" in r["error"] and "credit" in dr.view()["error"], r


if __name__ == "__main__":
    os.environ.setdefault("FORGE_ACTION_LOG", str(Path(tempfile.mkdtemp()) / "a.jsonl"))
    test_gate()
    test_flags()
    test_sweep_and_approve()
    test_auto_send()
    test_ai_down_stops_sweep()
    print("test_daycare_replies: all passed")
