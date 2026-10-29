"""daycare_auto_enroll.py — Family Contact Form -> parent app, once the owner AND the family agree.

A family that completes the Family Contact Form becomes a dashboard card. A card becomes a
real child row + parent login + PIN text only when BOTH are true, in either order (owner
decision 2026-10-29, spec Brand Kit docs/superpowers/specs/2026-10-29-login-click-plus-yes-design.md):
  1. the owner tapped Create login on the card, and
  2. the family replied YES to the Family Contact Form text (tag family-confirmed).
Click after YES: connector enrolls + texts on the spot. Click before YES: approve() records
the click and this loop finishes the job the tick after the YES lands. No click = nothing.
(The 2026-10-07 hands-free enroll is retired: a form alone never makes a login now.)

Guards (review) — still computed so view() can show what looks odd on a card. Anything odd is HELD with a
plain-English reason and shown in view() for a human; nothing odd is ever guessed:
  * not ready (missing email / birth date / parent name / center)
  * birth date implausible (future, or older than 13)
  * test / junk names, non-US phone
  * possible duplicate child (same contact has two cards with the same first name, or the
    same contact's cards sit at different centers, or same child name + birth date on two contacts)
  * parent name too short to greet ("G", "I")

Legacy holds: logins made by the retired hands-free enroll before 2026-10-29 sit in text_hold.
Their PIN text is held. It goes out for every
held login while FORGE_DAYCARE_AUTO_ENROLL_TEXT=1 (default 0), or when the family replies YES
to the Family Contact Form text (tag family-confirmed) while FORGE_DAYCARE_CONFIRM_TEXT=1
(default 0: owner decision 2026-10-29, the owner sends PINs by hand). Held logins are handed to daycare_login_queue the
moment the knob flips on — that queue owns hours (8am–8:30pm ET), fresh PIN minting,
never-two-PINs and opt-out/DND checks. No PIN is ever stored here.

Knobs: FORGE_DAYCARE_AUTO_ENROLL=0 turns the loop off. Stdlib only.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import date
from pathlib import Path

import daycare_ghl
import daycare_login_queue
import forge_atomic
import forge_heartbeat
import forge_ops

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_auto_enroll.json"
INTERVAL = 300
MAX_PER_TICK = 5
MAX_TRIES = 3
DONE_KEEP = 100
_LOCK = threading.Lock()   # guards the state file
_RUN = threading.Lock()    # one run at a time (loop thread vs manual run)
JUNK = ("zz", "test", "example", "larrylop", "russellzep")


def text_enabled() -> bool:
    return os.environ.get("FORGE_DAYCARE_AUTO_ENROLL_TEXT", "0") == "1"


def confirm_text_enabled() -> bool:
    return os.environ.get("FORGE_DAYCARE_CONFIRM_TEXT", "0") == "1"


CONFIRMED_TAG = "family-confirmed"


def _is_confirmed(client, contact_id) -> bool:
    """True when the family replied YES to the confirmation text (daycare_family_confirm tags it).
    A failed read counts as NOT confirmed: no PIN text on a guess."""
    try:
        data = client.get(f"/contacts/{contact_id}")
        tags = (data.get("contact") or data or {}).get("tags") or []
        return CONFIRMED_TAG in {str(t).lower() for t in tags}
    except Exception:  # noqa: BLE001 — unknown = held
        return False


def is_confirmed(client, contact_id) -> bool:
    return _is_confirmed(client, contact_id)


def approve(card_id, contact_id, now: float | None = None) -> dict:
    """The owner tapped Create login before the family's YES: remember the click.
    Internal + reversible (local state only); the loop enrolls once YES lands."""
    with _LOCK:
        st = _load()
        st.setdefault("approved", {})[str(card_id)] = {"contact_id": str(contact_id), "at": now or time.time()}
        _save(st)
    return {"approved": True, "waiting_for_yes": True}


def approved_ids() -> set[str]:
    with _LOCK:
        return set(_load().get("approved") or {})


def clear_approval(card_id) -> None:
    with _LOCK:
        st = _load()
        if (st.get("approved") or {}).pop(str(card_id), None) is not None:
            _save(st)


def release_confirmed(client, st: dict) -> int:
    """Hand a held login to the queue once its family has confirmed by text (YES). The queue
    still owns hours (8am-8:30pm ET), a fresh PIN, never-two-PINs and opt-out/DND. Returns
    how many were released. Runs every tick while the global text knob is off; does nothing
    while FORGE_DAYCARE_CONFIRM_TEXT is off (a YES alone never texts a PIN)."""
    if not confirm_text_enabled():
        return 0
    released = 0
    for pid, hold in list((st.get("text_hold") or {}).items()):
        if _is_confirmed(client, hold.get("contact_id")) \
                and daycare_login_queue.enqueue(hold, reason="family-confirmed").get("ok"):
            st["text_hold"].pop(pid)
            released += 1
    return released


def _load() -> dict:
    import json
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 — missing/corrupt = fresh state
        return {}


def _save(st: dict) -> None:
    forge_atomic.atomic_write_json(STATE, st)


def _norm(value) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").lower())


def _first_token(value) -> str:
    return _norm(re.split(r"[\s-]+", str(value or "").strip())[0] if str(value or "").strip() else "")


def _age(dob_iso: str, today: date) -> int | None:
    try:
        y, m, d = (int(x) for x in dob_iso.split("-"))
        return today.year - y - ((today.month, today.day) < (m, d))
    except (ValueError, AttributeError):
        return None


def _phone_ok(phone) -> bool:
    digits = re.sub(r"\D", "", str(phone or ""))
    return len(digits) == 10 or (len(digits) == 11 and digits.startswith("1"))


def review(cards: list[dict], today: date | None = None) -> tuple[list[dict], list[dict]]:
    """Split enrolled-family cards into (ready, held). Pure — no I/O.
    Held entries carry `reasons`. Cards that are not form-enrolled families (website leads)
    are ignored: they get no login until they enroll."""
    today = today or date.today()
    family_cards = [c for c in cards if c.get("enrolled")]
    by_contact: dict[str, list[dict]] = {}
    for c in family_cards:
        by_contact.setdefault(str(c.get("contact_id")), []).append(c)
    by_child: dict[tuple, list[dict]] = {}
    for c in family_cards:
        key = (_norm(c.get("child_first")), daycare_ghl.iso_date(c.get("child_dob")))
        by_child.setdefault(key, []).append(c)

    ready, held = [], []
    for c in family_cards:
        reasons: list[str] = list(c.get("missing") or [])
        dob = daycare_ghl.iso_date(c.get("child_dob"))
        if str(c.get("child_dob") or "").strip() and not dob:
            reasons.append(f"birth date {c.get('child_dob')} is unreadable or in the future")
        if dob:
            age = _age(dob, today)
            if age is None or age < 0 or age > 13:
                reasons.append(f"birth date {dob} looks wrong")
        names = _norm(f"{c.get('child_first')}{c.get('child_last')}{c.get('parent_first')}")
        if any(names.startswith(j) for j in JUNK) or any(j in _norm(c.get("email")) for j in ("e2e", "zztest")):
            reasons.append("test or junk record")
        for note in c.get("review") or []:
            reasons.append(f"needs a look: {note}")
        if not _phone_ok(c.get("phone")):
            reasons.append("parent phone is not a US number")
        if len(str(c.get("parent_first") or "").strip()) < 2 or len(str(c.get("parent_last") or "").strip()) < 2:
            reasons.append("parent name too short")
        sibs = by_contact.get(str(c.get("contact_id")), [])
        if len(sibs) > 1:
            if sum(1 for s in sibs if _first_token(s.get("child_first")) == _first_token(c.get("child_first"))) > 1:
                reasons.append("possible duplicate child on this parent")
            if len({s.get("location_tag") for s in sibs}) > 1:
                reasons.append("this parent's children are split across centers")
        if len(by_child.get((_norm(c.get("child_first")), dob), [])) > 1 and dob:
            reasons.append("same child + birth date on more than one contact")
        reasons = list(dict.fromkeys(reasons))
        (held if reasons else ready).append({**c, "reasons": reasons} if reasons else c)
    return ready, held


def run_once(client, session_fn, enroll_fn, now: float | None = None, dry_run: bool = False) -> dict:
    """One pass. enroll_fn(session, family, text_login) -> the enroll result dict (raises on failure).
    dry_run lists what WOULD happen and changes nothing."""
    if not _RUN.acquire(blocking=False):
        return {"ok": True, "skipped": "already running"}
    try:
        now = now or time.time()
        cards = [c for c in daycare_ghl.pending_families(client) if not daycare_ghl.is_dismissed(c.get("card_id"))]
        _, held = review(cards)
        with _LOCK:
            approved = dict(_load().get("approved") or {})
        # Owner click + family YES. The click is the owner's judgment on this card, so the review
        # guards (which only ever gated the retired hands-free path) don't block it, same as a
        # click after YES; enroll itself still refuses missing data.
        ready = [c for c in cards if str(c.get("card_id")) in approved and c.get("confirm_state") == "confirmed"]
        summary = {"ok": True, "ready": len(ready), "waiting_for_yes": len(approved) - len(ready), "held": [
            {"child": f"{h.get('child_first')} {h.get('child_last') or ''}".strip(), "card_id": h.get("card_id"),
             "reasons": h["reasons"], "location": h.get("location_tag")}   # center tag (the board's center)
            for h in held], "enrolled": [], "failed": [], "text": text_enabled()}
        if dry_run:
            summary["would_enroll"] = [f"{c.get('child_first')} ({c.get('location_tag')})" for c in ready[:MAX_PER_TICK]]
            return summary
        with _LOCK:
            st = _load()
        tries = st.setdefault("tries", {})
        done_cids: set[str] = set()
        session = session_fn() if ready else None
        if ready and session is None:
            summary["ok"] = False
            summary["error"] = "no daycare session — auto-admin is off"
        for card in (ready[:MAX_PER_TICK] if session is not None else []):
            cid = str(card.get("card_id"))
            if tries.get(cid, 0) >= MAX_TRIES:
                summary["failed"].append({"card_id": cid, "error": "gave up after repeated failures"})
                continue
            family = dict(card)
            family["location_id"] = daycare_ghl.LOCATION_ID_BY_TAG.get(str(card.get("location_tag") or "").lower())
            try:
                result = enroll_fn(session, family, True)
            except Exception as error:  # noqa: BLE001 — type only, never a token
                tries[cid] = tries.get(cid, 0) + 1
                summary["failed"].append({"card_id": cid, "error": f"{type(error).__name__}"})
                continue
            child = (result or {}).get("child") or {}
            prov = (result or {}).get("provision") or {}
            if not child.get("guardian_profile_id"):
                tries[cid] = tries.get(cid, 0) + 1
                summary["failed"].append({"card_id": cid, "error": "no parent login linked"})
                continue
            entry = {"card_id": cid, "child": card.get("child_first"), "location": card.get("location_tag"),
                     "at": now, "login_existed": bool(prov.get("existing")),
                     "texted": bool((prov.get("texted") or {}).get("ok")) or bool((prov.get("texted") or {}).get("queued"))}
            done_cids.add(cid)
            st.setdefault("done", []).append(entry)
            st["done"] = st["done"][-DONE_KEEP:]
            summary["enrolled"].append(entry["child"])
            texted = prov.get("texted") or {}
            if prov.get("pinWithheld") is None and not entry["texted"] and texted.get("error"):
                # Login made, PIN not texted (check failed / GHL refused): the card is gone, so say it
                # loudly — the heartbeat turns this into an alert. Resend login re-issues it.
                summary["failed"].append({"card_id": cid, "error": f"login made, PIN not texted: {texted['error']} — use Resend login"})
        # Text switch flipped on: hand every held login to the queue (it owns hours, PIN, opt-out).
        if text_enabled() and st.get("text_hold"):
            for pid, hold in list(st["text_hold"].items()):
                if daycare_login_queue.enqueue(hold, reason="auto-enroll").get("ok"):
                    st["text_hold"].pop(pid)
        elif st.get("text_hold"):
            summary["released"] = release_confirmed(client, st)
        st["held"] = summary["held"]
        st["last_run"] = now
        with _LOCK:
            # approve()/clear_approval() may have run during this pass: keep their writes,
            # drop only the cards this pass enrolled.
            st["approved"] = {k: v for k, v in (_load().get("approved") or {}).items() if k not in done_cids}
            _save(st)
        return summary
    finally:
        _RUN.release()


def view() -> dict:
    with _LOCK:
        st = _load()
    return {"ok": True, "text_enabled": text_enabled(), "held": st.get("held") or [],
            "waiting_for_text": len(st.get("text_hold") or {}),
            "waiting_for_yes": len(st.get("approved") or {}), "recent": (st.get("done") or [])[-20:],
            "last_run": st.get("last_run")}


def run_forever(client, session_fn, enroll_fn):
    """Background loop (thread `daycare_auto_enroll`)."""
    while True:
        err = None
        try:
            if not forge_ops.paused():
                s = run_once(client, session_fn, enroll_fn)
                err = s.get("error") or (f"{len(s['failed'])} enroll(s) failed" if s.get("failed") else None)
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        forge_heartbeat.beat("daycare_auto_enroll", INTERVAL, "Solomon · Auto-enroll", error=err)
        time.sleep(INTERVAL)
