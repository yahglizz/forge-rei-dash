"""Self-check for daycare_revive: who gets a revival draft, the template's facts (none),
the shared drafts store + approve gates, and the Replies lane superseding a revive draft.
No network, no Claude. Run: python3 test_daycare_revive.py"""
import os
import tempfile
from pathlib import Path

import daycare_replies as dr
import daycare_revive as rv

NOW = 1_790_000_000.0
DAY = 86400


def ms(ago_days):
    return int((NOW - ago_days * DAY) * 1000)


def lead(cid, last_in=None, last_out=None, **kw):
    return dict({"contactId": cid, "stage": "NEEDS_HUMAN", "optedOut": False, "kind": "form",
                 "parentName": "Tasha", "childName": "Mia", "center": "921 N 18th St",
                 "lastInboundAt": ms(last_in) if last_in is not None else None,
                 "lastOutboundAt": ms(last_out) if last_out is not None else None}, **kw)


def test_pick():
    leads = [
        lead("quiet", last_in=20, last_out=19),                 # we texted last, 19 d quiet
        lead("waiting", last_in=12, last_out=13),               # parent texted last, never answered
        lead("fresh", last_in=3, last_out=2),                   # <7 d, we texted last: not yet
        lead("waiting_fresh", last_in=3, last_out=4),           # <7 d, unanswered
        lead("enrolled", last_in=20, last_out=19, stage="ENROLLED"),
        lead("opted", last_in=20, last_out=19, optedOut=True),
        lead("ancient", last_in=200, last_out=199),
        lead("never_texted"),                                   # no touch either way
    ]
    got = [l["contactId"] for l in rv.pick(leads, {}, {}, NOW)]
    assert got == ["waiting", "quiet"], got                     # unanswered parent first
    # AI circuit open: an unanswered parent text is revived at any age (Replies is paused)
    got = [l["contactId"] for l in rv.pick(leads, {}, {}, NOW, ai_down=True)]
    assert got == ["waiting_fresh", "waiting", "quiet"], got
    # throttles: attempts cap, gap between attempts, open draft, just-handled draft
    st = {"contacts": {"quiet": {"attempts": 2, "lastAt": ms(60)},
                       "waiting": {"attempts": 1, "lastAt": ms(3)}}}
    assert rv.pick(leads, {}, st, NOW) == []
    assert [l["contactId"] for l in rv.pick(leads, {"quiet": {"status": "pending"}}, {}, NOW)] == ["waiting"]
    assert [l["contactId"] for l in rv.pick(leads, {"quiet": {"status": "sent", "closedAt": ms(2)}}, {}, NOW)] == ["waiting"]


def test_template_invents_nothing():
    contact = {"tags": ["loc-1923-cecil-b-moore"], "firstName": "Mia", "lastName": "Hill",
               "customFields": [{"id": rv.daycare_ghl.CF_PARENT_NAME, "value": "Tasha Hill"},
                                {"id": rv.daycare_ghl.CF_CHILD_NAME, "value": "Mia Hill"}]}
    sat = [{"dir": "inbound", "t": NOW - 20 * DAY, "body": "do you have room?", "sms": True, "auto": False}]
    quiet = [{"dir": "outbound", "t": NOW - 20 * DAY, "body": "hi", "sms": True, "auto": True}]
    for ev, tell in ((sat, "dropped the ball"), (quiet, "checking back in")):
        t = rv.template(contact, ev, NOW)
        d = t["draft"]
        assert tell in d and "A Mother's Touch" in d and d.endswith(rv.STOP_LINE), d
        assert dr.flags(d) == [], dr.flags(d)                   # no $, phone, emoji, length
        assert not any(w in d.lower() for w in ("opening", "seat", "spot available", "$", "free")), d


class FakeClient:
    configured = True
    location_id = "loc"

    def __init__(self, msgs, contact=None):
        self.msgs, self.sent, self.contact = msgs, [], contact or {"id": "c1", "tags": ["loc-921-n-18th"]}

    def get(self, ep, params=None):
        if ep == "/conversations/search":
            return {"conversations": [{"id": "v1", "contactId": "c1"}]}
        if ep.endswith("/messages"):
            return {"messages": {"messages": self.msgs}}
        if ep.startswith("/contacts/"):
            return {"contact": self.contact}
        return {}

    def post(self, ep, body):
        self.sent.append(body)
        return {"messageId": "s1"}


def m(i, direction, body, ago_days):
    return {"id": f"m{i}", "direction": direction, "body": body, "source": "",
            "messageType": "TYPE_SMS", "dateAdded": int((NOW - ago_days * DAY) * 1000)}


def test_run_and_gates():
    tmp = Path(tempfile.mkdtemp())
    dr.STATE, rv.STATE = tmp / "replies.json", tmp / "revive.json"
    rv.daycare_leads.in_hours = lambda now: True
    rv.daycare_leads._load = lambda: {"leads": [lead("c1", last_in=12, last_out=13)]}
    rv.daycare_leads.apply_stages = lambda leads, marks=None, children=None: leads
    rv.review_agent.ai_blocked = lambda *a, **k: True           # credits out: template path
    rv._ping = lambda names, now: None
    cl = FakeClient([m(1, "outbound", "hi", 13), m(2, "inbound", "are you open?", 12)])
    r = rv.run_once(cl, now=NOW)
    assert r["drafted"] == 1, r
    d = dr.view(NOW)["pending"][0]
    assert d["revive"] and d["category"] == "revive" and d["autoEligible"] is False, d
    assert d["model"] == "template" and "dropped the ball" in d["draft"] and d["inboundId"] == "m2"
    # one attempt recorded; the next pass drafts nothing (open draft + gap)
    assert rv._load()["contacts"]["c1"]["attempts"] == 1
    assert rv.run_once(cl, now=NOW)["drafted"] == 0
    # approve rides the Replies gates: a staff reply since -> retired, nothing sent
    cl.msgs.append(m(3, "outbound", "hey sorry about that", 0.01))
    out = dr.approve(cl, "c1", now=NOW)
    assert not out["ok"] and cl.sent == [], out
    # clean thread -> exactly one send, STOP line included
    dr.STATE = tmp / "replies2.json"
    rv.STATE = tmp / "revive2.json"
    cl.msgs = [m(1, "outbound", "hi", 13), m(2, "inbound", "are you open?", 12)]
    assert rv.run_once(cl, now=NOW)["drafted"] == 1
    assert dr.approve(cl, "c1", now=NOW)["ok"] and len(cl.sent) == 1
    assert rv.STOP_LINE in cl.sent[0]["message"], cl.sent[0]
    # a parent who opted out in the thread is never drafted
    dr.STATE, rv.STATE = tmp / "r3.json", tmp / "v3.json"
    cl.msgs = [m(1, "outbound", "hi", 13), m(2, "inbound", "STOP", 12)]
    assert rv.run_once(cl, now=NOW)["drafted"] == 0
    # queue cap: MAX_PENDING revive drafts pending -> nothing new
    dr.STATE, rv.STATE = tmp / "r4.json", tmp / "v4.json"
    full = {f"x{i}": {"revive": True, "status": "pending"} for i in range(rv.MAX_PENDING)}
    dr._save({"drafts": full})
    assert rv.run_once(cl, now=NOW)["skipped"] == "queue_full"


def test_replies_lane_supersedes_revive():
    tmp = Path(tempfile.mkdtemp())
    dr.STATE = tmp / "replies.json"
    dr._save({"drafts": {"c1": {"revive": True, "status": "pending", "inboundId": "m2",
                                "inboundAt": int(NOW * 1000), "draft": "template"}}})
    conv = {"id": "v1", "contactId": "c1", "lastMessageDirection": "inbound",
            "lastMessageDate": int((NOW - 30 * 60) * 1000)}
    cl = FakeClient([m(2, "inbound", "are you open?", 30 / 1440)])
    cl.get = (lambda orig: lambda ep, params=None: {"conversations": [conv]} if ep == "/conversations/search"
              else orig(ep, params))(cl.get)
    fake = lambda contact, ev, now: {"action": "draft", "category": "tour", "draft": "yes come see us",
                                     "why": "", "unknowns": [], "flags": [], "model": "t"}
    rv.review_agent.ai_blocked = lambda *a, **k: False
    assert dr.run_once(cl, now=NOW, drafter=fake)["drafted"] == 1       # AI back: real draft wins
    assert not dr.view(NOW)["pending"][0].get("revive")


if __name__ == "__main__":
    os.environ.setdefault("FORGE_ACTION_LOG", str(Path(tempfile.mkdtemp()) / "a.jsonl"))
    test_pick()
    test_template_invents_nothing()
    test_run_and_gates()
    test_replies_lane_supersedes_revive()
    print("test_daycare_revive: all passed")
