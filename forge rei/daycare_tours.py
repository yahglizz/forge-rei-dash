"""daycare_tours.py — tour booking inside Solomon · Replies, behind FORGE_GOOGLE_CALENDAR (default 0).

Flag off: nothing here runs and daycare_replies behaves exactly as before.
Flag on (and Google connected, and forge-daycare/config/tours.json no longer PLACEHOLDER):
  offer()       before a LEAD's draft (center known): up to 3 real open slots from the "ATOB Tours"
                calendar go into the SAME draft call's prompt — zero extra Claude calls.
  attach()      after the draft: a `tour` draft keeps the slots it offered (so the parent's pick
                can be matched on the next text). If the parent picked one of them, the draft is a
                tour-confirmation proposal (`tourSlot`). Tour drafts are never auto-sent.
  book()        on the owner's approve tap, after approve()'s window / live-thread / opt-out gates:
                claims the draft (a double tap books once), then google_io re-checks free/busy and
                creates the event — or refuses ("slot_taken": nothing sent, Solomon redrafts with
                fresh times on the next sweep).
  after_send()  confirmation sent -> GHL tag `tour-booked` + a GHL note; definitely not sent ->
                event cancelled, draft back to pending.
Never auto-books, never auto-texts: propose -> tap -> execute (CLAUDE.md rule 2).
Rollback: FORGE_GOOGLE_CALENDAR=0 + restart. Stdlib only.
"""
from __future__ import annotations

import os
import re
import time

import daycare_ghl
import daycare_leads
import google_io

ON = os.environ.get("FORGE_GOOGLE_CALENDAR", "0") == "1"
BOOKED_TAG = "tour-booked"          # daycare_leads.STAGE_TAGS maps it to TOUR_BOOKED
OFFER_N = 3
DOWN_SEC = 300                      # after a Google failure, skip offers this long (sweep stays fast)
_DOWN_UNTIL = 0.0


def _phones(raw):
    """FORGE_TOURS_ONLY_PHONES -> set of last-10-digit numbers, or None when unset/empty
    (= every contact). Set but with no usable number -> empty set = nobody (fails closed)."""
    if not (raw or "").strip():
        return None
    return {re.sub(r"\D", "", p)[-10:] for p in raw.split(",") if re.sub(r"\D", "", p)}


# Test-only allowlist: while set, tour times / booking happen ONLY for these phones; everyone
# else (and any contact with no phone) gets exactly the flag-off behavior.
ONLY_PHONES = _phones(os.environ.get("FORGE_TOURS_ONLY_PHONES", ""))


def _allowed(contact, cid=""):
    if ONLY_PHONES is None:
        return True
    d = re.sub(r"\D", "", str((contact or {}).get("phone") or ""))
    if d and d[-10:] in ONLY_PHONES:
        return True
    who = f"phone …{d[-4:]}" if d else "no phone on file"
    print(f"[daycare_tours] {cid or (contact or {}).get('id') or '?'}: {who} not on "
          "FORGE_TOURS_ONLY_PHONES — skipped")
    return False

RULES = ("These exact times override the rubric's \"never offer a specific slot\" rule, for these "
         "times only. If this text is about a tour (category \"tour\"), offer them in plain words "
         "(no list) instead of asking morning or afternoon. Never offer any other day or time. If the "
         "parent asked for a time that is not listed, say that one is taken and offer these. If the "
         "parent clearly picked one of these exact times, confirm it warmly (day, time, center "
         "address) and add \"tour_slot\": \"<its id>\" to the JSON; otherwise leave tour_slot out. "
         "Nothing is booked until the owner approves your text.")


def _set(cid, **kv):
    import daycare_replies as dr     # lazy: daycare_replies imports this module
    with dr._LOCK:
        st = dr._load()
        d = (st.get("drafts") or {}).get(cid)
        if d:
            d.update(kv)
            dr._save(st)
    return d


def _loc(contact):
    """The lead's center tag, or None (enrolled families and unknown centers get no tour times)."""
    tags = {str(t).strip().lower() for t in (contact or {}).get("tags") or []}
    if tags & daycare_leads.FAMILY_TAGS:
        return None
    return next((t for t in sorted(tags) if t.startswith("loc-")), None)


def offer(contact, prev, now):
    """Live tour times for this lead's draft prompt -> {location, slots, prompt}, or None
    (= the old behavior: ask morning or afternoon, staff confirm)."""
    global _DOWN_UNTIL
    loc = _loc(contact)
    cfg = google_io.tours_config()
    if not loc or not cfg or google_io.is_placeholder(cfg) or loc not in cfg["locations"]:
        return None
    if not _allowed(contact):
        return None
    if time.time() < _DOWN_UNTIL:
        return None                     # Google failed recently: don't slow the parent-reply sweep
    res = google_io.free_slots(loc, now=now)
    if not res.get("ok"):
        _DOWN_UNTIL = time.time() + DOWN_SEC
        print(f"[daycare_tours] no tour times for {loc}: {res.get('error')} — retry in {DOWN_SEC // 60} min")
        return None
    free = {s["id"]: s for s in res["data"]}
    keep = [free[s["id"]] for s in (prev or {}).get("tourSlots") or [] if s.get("id") in free]
    picks = {s["id"]: s for s in google_io.spread(res["data"], OFFER_N) + keep}
    slots = sorted(picks.values(), key=lambda s: s["start"])
    if not slots:
        return None
    label = cfg["locations"][loc].get("label") or loc
    prompt = (f"\n\n=== LIVE TOUR TIMES — {label} (ATOB Tours calendar, checked just now: real and open) ===\n"
              + "\n".join(f"- {s['id']} = {s['label']}" for s in slots) + "\n" + RULES)
    return {"location": loc, "slots": slots, "prompt": prompt}


def attach(row, tour, res, contact):
    """Fold the offer + the parent's pick into the draft row (in place). A valid pick counts
    even if the model mislabeled the category — the pick, not the label, is the booking."""
    pick_id = row.pop("tourPick", "")
    pick = next((s for s in tour["slots"] if pick_id and s["id"] == pick_id), None)
    if res.get("category") != "tour" and not pick:
        return row
    row["autoEligible"] = False                       # a text with live tour times is always a tap
    row["tourSlots"], row["tourLocation"] = tour["slots"], tour["location"]
    if pick and res.get("action") == "draft":
        fam = daycare_ghl._family_from_contact(contact) if contact else {}
        row["tourSlot"] = {**pick, "location": tour["location"],
                           "childFirst": fam.get("child_first") or "",
                           "parentFirst": fam.get("parent_first") or ""}
        note = f"Approve = books {pick['label']} on ATOB Tours + tags {BOOKED_TAG}. "
    else:   # the owner sees this on the draft: if the text confirms a time anyway, edit it
        note = "Offers tour times — approving books nothing. "
    row["why"] = (note + (row.get("why") or ""))[:300]
    return row


def book(cid, auto=False, client=None):
    """The owner's tap on a tour-confirmation draft: claim it, then create the event.
    -> google_io result ({ok, data:{eventId,…}}) or {ok: False, error} (nothing is sent)."""
    import daycare_replies as dr
    if auto:
        return {"ok": False, "error": "tour bookings are never auto-sent — owner tap only"}
    if not ON:
        return {"ok": False, "error": "tour booking is off (FORGE_GOOGLE_CALENDAR=0) — this draft "
                                      "confirms a tour time; send your own text from the Messages tab"}
    if ONLY_PHONES is not None:         # test allowlist: the LIVE contact's phone decides, fail closed
        try:
            ok = client is not None and _allowed(dr._contact(client, cid), cid)
        except Exception:  # noqa: BLE001 — can't read the phone = not on the list
            ok = False
        if not ok:
            return {"ok": False, "error": "tour booking is limited to FORGE_TOURS_ONLY_PHONES and this "
                                          "contact is not on it — nothing booked or sent"}
    with dr._LOCK:
        st = dr._load()
        d = (st.get("drafts") or {}).get(cid)
        if not d or d.get("status") != "pending" or not d.get("tourSlot"):
            return {"ok": False, "error": "no pending tour draft for that contact"}
        d["status"] = "booking"                   # a second tap now finds nothing pending
        dr._save(st)
    t = d["tourSlot"]
    res = google_io.create_tour_event(t["location"], t["start"], contact_id=cid,
                                      child_first=t.get("childFirst") or "",
                                      parent_first=t.get("parentFirst") or "")
    if res.get("ok"):
        try:
            import action_log
            action_log.record("solomon", "daycare_tour_book", business="daycare", trigger="owner_tap",
                              ref=cid, result="booked", ok=True, approval_required=True)
        except Exception:  # noqa: BLE001 — the log never blocks
            pass
        return {**res, "cleared": True}       # passed every gate above; after_send checks this
    if res.get("error") == "slot_taken":
        # Closed + inbound cleared: the next sweep redrafts this thread with fresh open times.
        _set(cid, status="slot_taken", inboundId="", inboundAt=0)
        return {"ok": False, "error": f"{t['label']} was just taken — not sent. Solomon redrafts with "
                                      "fresh open times within a minute."}
    _set(cid, status="pending", tourError=res.get("error"))
    return {"ok": False, "error": f"calendar booking failed — not sent: {res.get('error')}"}


def after_send(client, cid, booked, res):
    """After approve()'s send. res None = send raised (delivery unknown): keep the event, flag
    the row. Not ok = definitely not sent: cancel the event, draft back to pending.
    Ok = tag `tour-booked` + a GHL note (best effort — the parent is already confirmed).
    Under FORGE_TOURS_ONLY_PHONES it touches nothing that book() did not clear."""
    if ONLY_PHONES is not None and not booked.get("cleared"):
        print(f"[daycare_tours] {cid}: not cleared by book() under FORGE_TOURS_ONLY_PHONES — skipped")
        return
    ev = booked["data"]
    if res is None:
        _set(cid, status="send_error", tourEventId=ev["eventId"])
        print(f"[daycare_tours] {cid}: send raised after booking — event kept, check the thread")
        return
    if not res.get("ok"):
        google_io.cancel_event(ev["eventId"], ev.get("location"))
        _set(cid, status="pending")
        return
    _set(cid, tourEventId=ev["eventId"])
    try:
        client.post(f"/contacts/{cid}/tags", {"tags": [BOOKED_TAG]})
        client.post(f"/contacts/{cid}/notes", {"body": (
            f"Tour booked: {ev['label']} ET at {ev.get('center') or ev.get('location')} "
            f"(Google Calendar \"ATOB Tours\", event {ev['eventId']}). Confirmation text sent on the "
            f"owner's approval (Solomon · Replies).")})
    except Exception as e:  # noqa: BLE001 — never undo a confirmed tour over a tag/note hiccup
        print(f"[daycare_tours] {cid}: tag/note failed: {type(e).__name__}")
