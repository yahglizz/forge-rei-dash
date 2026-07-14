"""Specs for the daycare family-blast engine.

The two things that must never break: a parent is never texted twice for one blast
(guardian dedupe), and an opted-out family is never texted at all. Run:

    python3 test_daycare_blast.py
"""
import os
import tempfile
from pathlib import Path

import daycare_blast as blast

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("  ok  — %s" % name)
    else:
        FAILURES.append(name)
        print("  FAIL— %s %s" % (name, detail))


def fresh_store():
    tmp = Path(tempfile.mkdtemp()) / "daycare_blast.json"
    blast.STATE = tmp
    blast.register_transport(None)


# A guardian with TWO kids enrolled, one with no phone, one in another room.
CHILDREN = [
    {"id": "c1", "first_name": "Ava", "active": True, "classroom_id": "room-a",
     "guardian": {"id": "g1", "first_name": "Maria", "last_name": "Lopez",
                  "phone": "(555) 201-3344", "auth_email": "maria@example.com"}},
    {"id": "c2", "first_name": "Noah", "active": True, "classroom_id": "room-a",
     "guardian": {"id": "g1", "first_name": "Maria", "last_name": "Lopez",
                  "phone": "555-201-3344", "auth_email": "maria@example.com"}},
    {"id": "c3", "first_name": "Eli", "active": True, "classroom_id": "room-b",
     "guardian": {"id": "g2", "first_name": "Sam", "last_name": "Chen",
                  "phone": "5552019988"}},
    {"id": "c4", "first_name": "Zoe", "active": True, "classroom_id": "room-b",
     "guardian": {"id": "g3", "first_name": "Dana", "last_name": "Reed", "phone": ""}},
    {"id": "c5", "first_name": "Old", "active": False, "classroom_id": "room-a",
     "guardian": {"id": "g4", "first_name": "Past", "last_name": "Family",
                  "phone": "5550000000"}},
]


print("audience")
audience = blast.build_audience(CHILDREN)
people = audience["recipients"]
check("one guardian, two kids → ONE recipient (no double-text)",
      len([p for p in people if p["guardianId"] == "g1"]) == 1,
      "got %d" % len([p for p in people if p["guardianId"] == "g1"]))
check("differently-formatted phones dedupe to one",
      len(people) == 2, "got %d recipients" % len(people))
check("both children collected under the one guardian",
      sorted(next(p for p in people if p["guardianId"] == "g1")["children"]) == ["Ava", "Noah"])
check("no-phone family is surfaced, not silently dropped",
      any(m["guardianName"].startswith("Dana") for m in audience["missingPhone"]))
check("inactive child's family excluded",
      not any(p["guardianId"] == "g4" for p in people))

room_a = blast.build_audience(CHILDREN, classroom_id="room-a")["recipients"]
check("classroom filter narrows the audience",
      len(room_a) == 1 and room_a[0]["guardianId"] == "g1")


print("\nmerge tokens")
maria = next(p for p in people if p["guardianId"] == "g1")
sam = next(p for p in people if p["guardianId"] == "g2")
check("{first_name} fills", blast.render("Hi {first_name}!", maria) == "Hi Maria!")
check("two kids read naturally",
      blast.render("{child}", maria) == "Ava and Noah",
      blast.render("{child}", maria))
check("one kid reads naturally", blast.render("{child}", sam) == "Eli")
check("{center} fills", "A Touch of Blessings" in blast.render("— {center}", maria))
check("unknown token left alone", blast.render("{bogus}", maria) == "{bogus}")


print("\ncreate (queues only — never sends)")
fresh_store()
record = blast.create_blast(title="Snow day", template="Hi {first_name}, {child} stays home.",
                            recipients=people, audience_label="All families")
check("blast is QUEUED, not sent", record["status"] == "queued")
check("every recipient rendered", all(r["text"] for r in record["recipients"]))
check("text is personalized per family",
      record["recipients"][0]["text"] != record["recipients"][1]["text"])
check("empty message rejected",
      "error" in blast.create_blast(title="x", template="  ", recipients=people))
check("over-long message rejected",
      "error" in blast.create_blast(title="x", template="y" * 900, recipients=people))
check("empty audience rejected",
      "error" in blast.create_blast(title="x", template="hi", recipients=[]))

os.environ[blast.CAP_ENV] = "1"
check("recipient cap blocks a fat-finger blast",
      "error" in blast.create_blast(title="big", template="hi", recipients=people))
os.environ.pop(blast.CAP_ENV, None)


print("\nopt-out")
fresh_store()
blast.set_optout("555-201-3344", name="Maria Lopez")
guarded = blast.create_blast(title="Reminder", template="hi {first_name}", recipients=people)
check("opted-out family excluded at create time",
      all(r["guardianId"] != "g1" for r in guarded["recipients"]))
check("skip is counted, not hidden", guarded["skippedOptOut"] == 1)
blast.set_optout("555-201-3344", opted_out=False)
check("opt-out is reversible",
      len(blast.create_blast(title="R2", template="hi", recipients=people)["recipients"]) == 2)


print("\nsend (operator-gated)")
fresh_store()
sent_to = []

def transport(recipient, text):
    sent_to.append((recipient["phone"], text))
    return {"ok": True}

queued = blast.create_blast(title="Picture day", template="Hi {first_name}", recipients=people)
check("no transport registered → nothing would leave the box",
      blast._TRANSPORT is None)

blast.register_transport(transport)
result = blast.send_blast(queued["id"], throttle=0)
check("all recipients sent", result["summary"]["sent"] == 2, str(result["summary"]))
check("each phone texted exactly once", len(sent_to) == len(set(p for p, _ in sent_to)))
check("blast marked sent", result["blast"]["status"] == "sent")

sent_to.clear()
again = blast.send_blast(queued["id"], throttle=0)
check("re-sending does NOT double-text (idempotent)",
      not sent_to and again["summary"]["sent"] == 0)


print("\nsend — partial failure")
fresh_store()
def flaky(recipient, text):
    if recipient["guardianId"] == "g2":
        raise RuntimeError("carrier rejected")
    return {"ok": True}

blast.register_transport(flaky)
rec = blast.create_blast(title="Flaky", template="hi", recipients=people)
out = blast.send_blast(rec["id"], throttle=0)
check("one failure does not abort the blast", out["summary"]["sent"] == 1)
check("failure recorded", out["summary"]["failed"] == 1)
check("blast marked partial", out["blast"]["status"] == "partial")

retries = []
blast.register_transport(lambda r, t: (retries.append(r["phone"]), {"ok": True})[1])
out2 = blast.send_blast(rec["id"], throttle=0)
check("retry only picks up the failed one", len(retries) == 1 and out2["summary"]["sent"] == 1)


print("\nlocation isolation (the JSON store has no RLS — the filter IS the wall)")
fresh_store()
LOC1, LOC2 = "loc-blessings-1", "loc-mothers-touch"
b1 = blast.create_blast(title="Snow", template="hi", recipients=people, location_id=LOC1)
b2 = blast.create_blast(title="Party", template="hi", recipients=people, location_id=LOC2)
check("center 1 sees only its own blast",
      [b["id"] for b in blast.list_blasts(LOC1)] == [b1["id"]])
check("center 2 sees only its own blast",
      [b["id"] for b in blast.list_blasts(LOC2)] == [b2["id"]])
check("a blast carries its location", b1["locationId"] == LOC1)

blast.register_transport(lambda r, t: {"ok": True})
check("cannot SEND another center's blast even with its id",
      "error" in blast.send_blast(b2["id"], location_id=LOC1, throttle=0))
check("cannot CANCEL another center's blast",
      "error" in blast.cancel_blast(b2["id"], location_id=LOC1))
check("can send your own center's blast",
      blast.send_blast(b1["id"], location_id=LOC1, throttle=0)["summary"]["sent"] == 2)

blast.set_optout("555-201-3344", location_id=LOC1, name="Maria")
o1 = blast.create_blast(title="A", template="hi", recipients=people, location_id=LOC1)
o2 = blast.create_blast(title="B", template="hi", recipients=people, location_id=LOC2)
check("opt-out applies at the center it was set",
      all(r["guardianId"] != "g1" for r in o1["recipients"]))
check("opt-out does NOT mute a different center (may be a different business)",
      any(r["guardianId"] == "g1" for r in o2["recipients"]))
check("opt-out list is per center",
      len(blast.list_optouts(LOC1)) == 1 and len(blast.list_optouts(LOC2)) == 0)


print("\ncancel")
fresh_store()
blast.register_transport(None)
c = blast.create_blast(title="Oops", template="hi", recipients=people)
check("queued blast can be cancelled", blast.cancel_blast(c["id"])["ok"])
check("cancelled blast will not send", "error" in blast.send_blast(c["id"], throttle=0))


print("\n" + ("ALL PASS" if not FAILURES else "FAILURES: %s" % FAILURES))
raise SystemExit(1 if FAILURES else 0)
