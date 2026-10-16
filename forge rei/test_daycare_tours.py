"""Self-check for tour booking inside Solomon · Replies (daycare_tours + the daycare_replies
hooks): flag off = old behavior byte-for-byte; flag on = real slots offered in the SAME draft
call, the parent's pick becomes a proposal, the owner's tap books + tags + notes + sends once,
two approvals can't book one slot, a failed send undoes the booking, nothing auto-sends.
Fake GHL + fake Google only — no network, no Claude, no real text. Run: python3 test_daycare_tours.py"""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("FORGE_ACTION_LOG", str(Path(tempfile.mkdtemp()) / "actions.jsonl"))

import time  # noqa: E402

import daycare_replies as dr  # noqa: E402
import daycare_tours as dt  # noqa: E402
import google_io as g  # noqa: E402
import review_agent  # noqa: E402
import test_google_io as tg  # noqa: E402 — FakeGoogle + setup()

NOW = time.time()
MIN = 60
LEAD = ["form-type-new-inquiry", "loc-921-n-18th"]


def msg(i, direction, body, ago, source=""):
    return {"id": f"m{i}", "direction": direction, "body": body, "source": source,
            "messageType": "TYPE_SMS", "dateAdded": int((NOW - ago) * 1000)}


FIRST_TOUCH = msg(0, "outbound", "Hi! this is management over at A Touch of Blessings", 60 * MIN, "workflow")


class FakeGHL:
    configured = True
    location_id = "loc"

    def __init__(self):
        self.contacts, self.threads = {}, {}
        self.sms, self.tags, self.notes, self.fail_send = [], [], [], False

    def add(self, cid, tags, msgs, phone=None):
        self.contacts[cid] = {"id": cid, "tags": tags, "firstName": "Ava",
                              **({"phone": phone} if phone else {})}
        self.threads[cid] = msgs

    def _conv(self, cid):
        last = self.threads[cid][-1]
        return {"id": "v" + cid, "contactId": cid, "lastMessageDirection": last["direction"],
                "lastMessageDate": last["dateAdded"]}

    def get(self, ep, params=None):
        params = params or {}
        if ep == "/conversations/search":
            cids = [params["contactId"]] if params.get("contactId") else list(self.threads)
            return {"conversations": [self._conv(c) for c in cids]}
        if ep.startswith("/conversations/v") and ep.endswith("/messages"):
            return {"messages": {"messages": self.threads[ep.split("/")[2][1:]]}}
        if ep.startswith("/contacts/"):
            return {"contact": self.contacts[ep.split("/")[2]]}
        return {}

    def post(self, ep, body):
        if ep == "/conversations/messages":
            if self.fail_send:
                raise RuntimeError("GHL 502 Bad Gateway")
            self.sms.append(body)
            return {"messageId": f"s{len(self.sms)}"}
        if ep.endswith("/tags"):
            self.tags.append((ep.split("/")[2], body["tags"]))
        elif ep.endswith("/notes"):
            self.notes.append((ep.split("/")[2], body["body"]))
        return {}


class Drafter:
    """Fake Claude: records whether tour times reached the prompt; picks a slot on cue."""

    def __init__(self, pick=None, category="tour"):
        self.calls, self.pick, self.category = [], pick, category

    def __call__(self, contact, ev, now, tour=None):
        self.calls.append(tour)
        res = {"action": "draft", "category": self.category, "draft": "we'd love to show you around",
               "why": "parent wants a tour", "unknowns": [], "flags": [], "model": "fake"}
        if tour is not None:
            res["tourPick"] = self.pick(tour) if self.pick else ""
        return res


def fresh(on=True, cfg=tg.CFG):
    dr.STATE = Path(tempfile.mkdtemp()) / "replies.json"
    dr.daycare_leads.in_hours = lambda now: True
    dt.ON, dt._DOWN_UNTIL, dt.ONLY_PHONES = on, 0.0, None
    return tg.setup(cfg=cfg, fake=tg.FakeGoogle())


def row(cid):
    return (dr._load().get("drafts") or {})[cid]


def test_flag_off_is_unchanged():
    gfake = fresh(on=False)
    cl = FakeGHL()
    cl.add("c1", LEAD, [FIRST_TOUCH, msg(1, "inbound", "can we come see the center?", 10 * MIN)])
    seen = []
    old_style = lambda contact, ev, now: seen.append(1) or {      # the pre-tour drafter signature
        "action": "draft", "category": "tour", "draft": "we'd love to show you around", "why": "",
        "unknowns": [], "flags": [], "model": "fake"}
    r = dr.run_once(cl, now=NOW, drafter=old_style)
    assert r["drafted"] == 1 and r["errors"] == 0 and seen == [1], r
    d = row("c1")
    assert not [k for k in d if k.startswith("tour")] and d["autoEligible"] is True
    assert dr.approve(cl, "c1", now=NOW)["ok"] and len(cl.sms) == 1
    assert cl.tags == [] and cl.notes == [] and gfake.calls == []  # no Google, no tag, no note
    # the real drafter's prompt is byte-for-byte the old one; the result keys are the old set
    captured = []
    real = review_agent._claude
    review_agent._claude = lambda key, system, user, **kw: captured.append(user) or (
        '{"action":"draft","category":"tour","draft":"hi","why":"w","unknowns":[],"tour_slot":"x"}')
    try:
        contact = cl.contacts["c1"]
        ev = dr._events(cl.threads["c1"])
        out = dr.draft_reply(contact, ev, NOW, key="test-key")
        assert captured[-1] == dr._prompt(contact, ev, NOW)
        assert set(out) == {"action", "category", "draft", "why", "unknowns", "flags", "model"}
        tour = {"prompt": "\n\nTOUR BLOCK", "slots": [], "location": "loc-921-n-18th"}
        out = dr.draft_reply(contact, ev, NOW, key="test-key", tour=tour)
        assert captured[-1] == dr._prompt(contact, ev, NOW) + "\n\nTOUR BLOCK" and out["tourPick"] == "x"
    finally:
        review_agent._claude = real


def test_offer_pick_approve():
    gfake = fresh()
    cl = FakeGHL()
    cl.add("c1", LEAD, [FIRST_TOUCH, msg(1, "inbound", "can we come see the center?", 10 * MIN)])
    offer = Drafter()
    assert dr.run_once(cl, now=NOW, drafter=offer)["drafted"] == 1
    tour = offer.calls[0]
    assert tour and len(tour["slots"]) == 3 and "LIVE TOUR TIMES" in tour["prompt"]
    assert all(s["id"] in tour["prompt"] and s["label"] in tour["prompt"] for s in tour["slots"])
    assert len({s["id"][:10] for s in tour["slots"]}) == 3          # three different days
    d = row("c1")
    assert d["tourSlots"] == tour["slots"] and "tourSlot" not in d and d["autoEligible"] is False
    assert "tourPick" not in d and d["why"].startswith("Offers tour times — approving books nothing")
    # the offer text goes out on a normal tap — no booking yet
    assert dr.approve(cl, "c1", now=NOW)["ok"] and len(cl.sms) == 1 and gfake.events == {}
    # parent picks the second time offered
    cl.threads["c1"].append(msg(2, "inbound", "the second one works for us", 5 * MIN))
    confirm = Drafter(pick=lambda t: tour["slots"][1]["id"])
    assert dr.run_once(cl, now=NOW, drafter=confirm)["drafted"] == 1
    assert {s["id"] for s in tour["slots"]} <= {s["id"] for s in confirm.calls[0]["slots"]}  # carried forward
    d = row("c1")
    assert d["tourSlot"]["id"] == tour["slots"][1]["id"] and d["why"].startswith("Approve = books")
    # owner's tap: event + SMS + tag + note, once
    out = dr.approve(cl, "c1", now=NOW)
    assert out["ok"] and len(cl.sms) == 2 and len(gfake.events) == 1, out
    (start, _), = gfake.events.values()
    assert start == tour["slots"][1]["start"]
    assert cl.tags == [("c1", ["tour-booked"])] and "tour-booked" in dr.daycare_leads.STAGE_TAGS
    assert cl.notes and cl.notes[0][0] == "c1" and tour["slots"][1]["label"] in cl.notes[0][1]
    d = row("c1")
    assert d["status"] == "sent" and d["tourEventId"] in gfake.events
    assert not dr.approve(cl, "c1", now=NOW)["ok"] and len(cl.sms) == 2 and len(gfake.events) == 1


def test_two_approvals_one_slot():
    gfake = fresh()
    cl = FakeGHL()
    for cid in ("c2", "c3"):
        cl.add(cid, LEAD, [FIRST_TOUCH, msg(1, "inbound", "tuesday 10 please", 10 * MIN)])
    same = Drafter(pick=lambda t: t["slots"][0]["id"])
    assert dr.run_once(cl, now=NOW, drafter=same)["drafted"] == 2
    slot = row("c2")["tourSlot"]
    assert row("c3")["tourSlot"]["id"] == slot["id"]                # both proposals name one slot
    assert dr.approve(cl, "c2", now=NOW)["ok"]
    out = dr.approve(cl, "c3", now=NOW)
    assert not out["ok"] and "just taken" in out["error"], out
    assert len(cl.sms) == 1 and cl.sms[0]["contactId"] == "c2" and len(gfake.events) == 1
    assert row("c3")["status"] == "slot_taken"
    # next sweep redrafts c3 with fresh times that exclude the booked slot
    again = Drafter()
    dr.run_once(cl, now=NOW, drafter=again)
    assert len(again.calls) == 1 and slot["id"] not in {s["id"] for s in again.calls[0]["slots"]}
    assert row("c3")["status"] == "pending"


def test_failed_send_undoes_booking():
    gfake = fresh()
    cl = FakeGHL()
    cl.add("c4", LEAD, [FIRST_TOUCH, msg(1, "inbound", "monday works", 10 * MIN)])
    dr.run_once(cl, now=NOW, drafter=Drafter(pick=lambda t: t["slots"][0]["id"]))
    real = dr.daycare_ghl.send_sms
    dr.daycare_ghl.send_sms = lambda client, contact_id, message: {"ok": False, "detail": "not configured"}
    try:
        assert not dr.approve(cl, "c4", now=NOW)["ok"]
    finally:
        dr.daycare_ghl.send_sms = real
    assert gfake.events == {} and row("c4")["status"] == "pending" and cl.tags == []   # undone, retryable
    assert dr.approve(cl, "c4", now=NOW)["ok"] and len(gfake.events) == 1 and len(cl.sms) == 1
    # a send that RAISES (delivery unknown) keeps the event and flags the row
    cl.add("c5", LEAD, [FIRST_TOUCH, msg(1, "inbound", "friday", 10 * MIN)])
    dr.run_once(cl, now=NOW, drafter=Drafter(pick=lambda t: t["slots"][-1]["id"]))
    cl.fail_send = True
    try:
        dr.approve(cl, "c5", now=NOW)
        raise AssertionError("send error should propagate like before")
    except RuntimeError:
        pass
    assert len(gfake.events) == 2 and row("c5")["status"] == "send_error" and row("c5")["tourEventId"]


def test_never_auto_and_flag_rollback():
    fresh()
    cl = FakeGHL()
    cl.add("c6", LEAD, [FIRST_TOUCH, msg(1, "inbound", "wednesday", 10 * MIN)])
    dr.run_once(cl, now=NOW, drafter=Drafter(pick=lambda t: t["slots"][0]["id"]))
    assert row("c6")["autoEligible"] is False
    dr.AUTO = True
    try:
        assert dr.auto_send(cl, NOW)["sent"] == 0 and cl.sms == []
    finally:
        dr.AUTO = False
    assert "never auto" in dt.book("c6", auto=True)["error"] and row("c6")["status"] == "pending"
    dt.ON = False                                                    # rollback with a tour draft pending
    out = dr.approve(cl, "c6", now=NOW)
    assert not out["ok"] and "off" in out["error"] and cl.sms == []


def test_pick_beats_category_label():
    gfake = fresh()
    cl = FakeGHL()
    cl.add("c8", LEAD, [FIRST_TOUCH, msg(1, "inbound", "thursday please", 10 * MIN)])
    mislabeled = Drafter(pick=lambda t: t["slots"][0]["id"], category="enroll")
    dr.run_once(cl, now=NOW, drafter=mislabeled)
    assert row("c8")["tourSlot"]["id"] == mislabeled.calls[0]["slots"][0]["id"]
    assert row("c8")["autoEligible"] is False
    assert dr.approve(cl, "c8", now=NOW)["ok"] and len(gfake.events) == 1
    # a pick that was never offered books nothing
    cl.add("c9", LEAD, [FIRST_TOUCH, msg(1, "inbound", "sunday 3am?", 10 * MIN)])
    dr.run_once(cl, now=NOW, drafter=Drafter(pick=lambda t: "2026-01-04T03:00"))
    assert "tourSlot" not in row("c9")


def test_phone_allowlist():
    import contextlib
    import io
    variants = ("+1 267-555-0166", "(267) 555 0166", "2675550166")
    assert dt._phones("") is None and dt._phones("  ") is None                      # empty = everyone
    assert dt._phones(",".join(variants)) == {"2675550166"}
    assert dt._phones("not a number") == set()                                      # set but junk = nobody
    for listed in variants:                                                         # every format matches
        for on_file in variants + ("+12675550166",):
            fresh()
            dt.ONLY_PHONES = dt._phones(listed)
            assert dt.offer({"tags": LEAD, "phone": on_file}, None, NOW), (listed, on_file)
    # unlisted phone and NO phone: no slots, no Google call, logged without the full number
    fake = fresh()
    dt.ONLY_PHONES = dt._phones("+1 267-555-0166")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert dt.offer({"id": "cX", "tags": LEAD, "phone": "+1 (215) 555-0123"}, None, NOW) is None
        assert dt.offer({"id": "cY", "tags": LEAD}, None, NOW) is None
        assert dt.offer({"id": "cZ", "tags": LEAD, "phone": ""}, None, NOW) is None
    log = out.getvalue()
    assert fake.calls == [] and "…0123" in log and "2155550123" not in log and "555-0123" not in log
    assert log.count("no phone on file") == 2
    # unlisted: the sweep's draft row is byte-identical to flag-off
    def sweep(on, allow):
        fresh(on=on)
        dt.ONLY_PHONES = dt._phones(allow)
        cl = FakeGHL()
        cl.add("c1", LEAD, [FIRST_TOUCH, msg(1, "inbound", "can we tour?", 10 * MIN)], phone="+12155550123")
        d = Drafter()
        dr.run_once(cl, now=NOW, drafter=d)
        return d.calls, row("c1")
    off_calls, off_row = sweep(False, "")
    on_calls, on_row = sweep(True, "2675550166")
    assert off_calls == on_calls == [None] and on_row == off_row
    # listed phone: offered; empty var: everyone (the unlisted phone gets slots too)
    assert sweep(True, "2675550166 , +1 215 555 0123")[0][0] is not None
    assert sweep(True, "")[0][0] is not None
    # book(): a tour draft made before the allowlist was set -> refused, nothing booked or sent
    gfake = fresh()
    cl = FakeGHL()
    cl.add("c2", LEAD, [FIRST_TOUCH, msg(1, "inbound", "thursday", 10 * MIN)], phone="+12155550123")
    cl.add("c3", LEAD, [FIRST_TOUCH, msg(1, "inbound", "friday", 10 * MIN)])            # no phone on file
    cl.add("c4", LEAD, [FIRST_TOUCH, msg(1, "inbound", "monday", 10 * MIN)], phone="(267) 555-0166")
    dr.run_once(cl, now=NOW, drafter=Drafter(pick=lambda t: t["slots"][0]["id"]))
    dt.ONLY_PHONES = dt._phones("2675550166")
    for cid in ("c2", "c3"):
        r = dr.approve(cl, cid, now=NOW)
        assert not r["ok"] and "FORGE_TOURS_ONLY_PHONES" in r["error"] and row(cid)["status"] == "pending"
    assert gfake.events == {} and cl.sms == [] and cl.tags == [] and cl.notes == []
    assert dr.approve(cl, "c4", now=NOW)["ok"]                                       # listed: books
    assert len(gfake.events) == 1 and len(cl.sms) == 1 and cl.tags == [("c4", ["tour-booked"])]
    # after_send never writes for a booking book() did not clear
    dt.after_send(cl, "c2", {"ok": True, "data": {"eventId": "x", "label": "l"}}, {"ok": True})
    assert cl.tags == [("c4", ["tour-booked"])] and len(cl.notes) == 1


def test_offer_refuses_when_not_ready():
    fake = fresh(cfg=dict(tg.CFG, _note="PLACEHOLDER tour policy - owner must replace"))
    assert dt.offer({"tags": LEAD}, None, NOW) is None and fake.calls == []        # placeholder
    fresh(cfg=None)
    assert dt.offer({"tags": LEAD}, None, NOW) is None                              # no config
    fake = fresh()
    assert dt.offer({"tags": LEAD + ["daycare family"]}, None, NOW) is None         # enrolled family
    assert dt.offer({"tags": ["form-type-new-inquiry"]}, None, NOW) is None         # center unknown
    assert dt.offer({"tags": ["loc-2318-cecil-b-moore"]}, None, NOW) is None        # center not in policy
    assert fake.calls == []
    g.TOKEN_FILE.unlink()                                                           # Google disconnected
    g._ACCESS.update(token=None, exp=0)
    assert dt.offer({"tags": LEAD}, None, NOW) is None
    g.TOKEN_FILE.write_text('{"refresh_token": "r"}')                               # back, but backing off:
    n = len(fake.calls)
    assert dt.offer({"tags": LEAD}, None, NOW) is None and len(fake.calls) == n     # no Google call for 5 min
    dt._DOWN_UNTIL = 0.0
    assert dt.offer({"tags": LEAD}, None, NOW) is not None
    dt._DOWN_UNTIL = time.time() + 300
    cl = FakeGHL()                                    # and the sweep still drafts the old way
    cl.add("c7", LEAD, [FIRST_TOUCH, msg(1, "inbound", "can we tour", 10 * MIN)])
    d = Drafter()
    assert dr.run_once(cl, now=NOW, drafter=d)["drafted"] == 1 and d.calls == [None]


if __name__ == "__main__":
    test_flag_off_is_unchanged()
    test_offer_pick_approve()
    test_two_approvals_one_slot()
    test_failed_send_undoes_booking()
    test_never_auto_and_flag_rollback()
    test_pick_beats_category_label()
    test_phone_allowlist()
    test_offer_refuses_when_not_ready()
    print("test_daycare_tours: all passed")
