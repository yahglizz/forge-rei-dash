#!/usr/bin/env python3
"""GoHighLevel bridge for the daycare — outbound family messaging.

Uses the daycare's OWN GHL sub-account (a dedicated ``GHLClient`` built from
``GHL_API_KEY`` / ``GHL_LOCATION_ID`` in ``forge-daycare/config/daycare.env``),
kept fully separate from the wholesale + agency GHL accounts.

Every function takes the client explicitly (no module-level singleton) so tokens
never cross sub-accounts. Outbound SMS is an OWNER-INITIATED action — the console
button click is the approval gate (CLAUDE.md rule 2). Nothing here sends on its own.

Stdlib only (the client is urllib-based).
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
import urllib.error
from pathlib import Path

import forge_atomic

_DISMISSED_STATE = Path(__file__).resolve().parent / "marcus_state" / "daycare_dismissed_contacts.json"
_DISMISSED_LOCK = threading.Lock()


def _load_dismissed() -> set[str]:
    if _DISMISSED_STATE.exists():
        try:
            d = json.loads(_DISMISSED_STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("contact_ids"), list):
                return set(str(c) for c in d["contact_ids"])
        except Exception:  # noqa: BLE001
            pass
    return set()


def is_dismissed(contact_id: str | None) -> bool:
    if not contact_id:
        return False
    with _DISMISSED_LOCK:
        return str(contact_id) in _load_dismissed()


def dismiss(contact_id: str) -> dict:
    """Owner marks a Contact-Form inbox entry as reviewed — internal + reversible
    (undo just removes the id again), so no approval gate needed (CLAUDE.md rule 2)."""
    with _DISMISSED_LOCK:
        ids = _load_dismissed()
        ids.add(str(contact_id))
        forge_atomic.atomic_write_json(_DISMISSED_STATE, {"contact_ids": sorted(ids)})
    return {"ok": True, "contact_id": contact_id}


def undismiss(contact_id: str) -> dict:
    with _DISMISSED_LOCK:
        ids = _load_dismissed()
        ids.discard(str(contact_id))
        forge_atomic.atomic_write_json(_DISMISSED_STATE, {"contact_ids": sorted(ids)})
    return {"ok": True, "contact_id": contact_id}


# Auto-enroll ledger: GHL contact id -> the Supabase child row created for it.
# Lets the inbox auto-create the child ON ARRIVAL (internal + reversible — the row
# can be deleted) while keeping the parent LOGIN behind the owner's button, and lets
# the button UPDATE that same row instead of inserting a duplicate.
_FORM_CHILD_STATE = Path(__file__).resolve().parent / "marcus_state" / "daycare_form_children.json"
_FORM_CHILD_LOCK = threading.Lock()


def _load_form_children() -> dict[str, str]:
    if _FORM_CHILD_STATE.exists():
        try:
            d = json.loads(_FORM_CHILD_STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("children"), dict):
                return {str(k): str(v) for k, v in d["children"].items()}
        except Exception:  # noqa: BLE001
            pass
    return {}


def form_child_id(contact_id: str | None) -> str:
    if not contact_id:
        return ""
    with _FORM_CHILD_LOCK:
        return _load_form_children().get(str(contact_id), "")


def record_form_child(contact_id: str, child_id: str) -> None:
    if not contact_id or not child_id:
        return
    with _FORM_CHILD_LOCK:
        kids = _load_form_children()
        kids[str(contact_id)] = str(child_id)
        forge_atomic.atomic_write_json(_FORM_CHILD_STATE, {"children": kids})


def _digits(phone: str | None) -> str:
    return re.sub(r"[^0-9+]", "", str(phone or ""))


def _duplicate_contact_id(error) -> str | None:
    """Pull the EXISTING contact id out of GHL's duplicate-phone rejection.

    GHL sub-accounts can be set to "no duplicate contacts". When they are, POST /contacts/
    answers 400 "This location does not allow duplicated contacts" AND hands back the id of
    the contact that already holds that phone, in meta.contactId. That id is authoritative
    — more reliable than the search endpoint, which does not consistently match a phone
    written in a different format than it was stored in. Without this, re-saving an
    existing family (or texting them an invoice twice) raises instead of updating them.
    """
    raw = getattr(error, "_body", None)
    if raw is None:
        try:
            raw = error.read()
        except Exception:  # noqa: BLE001
            raw = b""
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = json.loads(text)
    except Exception:  # noqa: BLE001
        return None
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        return None
    return meta.get("contactId") or meta.get("id") or None


def health(client) -> dict:
    """Lightweight connectivity check against the daycare GHL sub-account."""
    if client is None or not client.configured:
        return {"ok": True, "connected": False, "hasKeys": False,
                "detail": "Add GHL_API_KEY + GHL_LOCATION_ID to daycare.env to connect."}
    try:
        client.get("/contacts/", {"locationId": client.location_id, "limit": 1})
        return {"ok": True, "connected": True, "hasKeys": True,
                "locationId": client.location_id}
    except Exception as error:  # noqa: BLE001 — surface a safe message, no token leak
        return {"ok": True, "connected": False, "hasKeys": True,
                "detail": f"GHL not reachable: {type(error).__name__}"}


def find_contact_by_phone(client, phone: str) -> str | None:
    normalized = _digits(phone)
    if not normalized:
        return None
    try:
        data = client.get("/contacts/", {"locationId": client.location_id, "query": normalized})
    except Exception:  # noqa: BLE001
        return None
    contacts = data.get("contacts", []) if isinstance(data, dict) else []
    return contacts[0]["id"] if contacts else None


def ensure_contact(client, *, name: str, phone: str, email: str | None = None) -> str:
    """Return a GHL contact id for the family, creating it only if it truly doesn't exist.

    Idempotent by design — this runs every time a child is saved, so the SECOND save of the
    same family must resolve to the same contact, not explode. Two paths find an existing
    contact: the search endpoint, and (when search misses on a format mismatch) GHL's own
    duplicate rejection, which carries the existing id.
    """
    existing = find_contact_by_phone(client, phone)
    if existing:
        return existing
    body = {"locationId": client.location_id, "name": name or "Family", "phone": _digits(phone)}
    if email and "@" in email and not email.lower().endswith("@login.blessings.app"):
        body["email"] = email
    try:
        created = client.post("/contacts/", body)
    except urllib.error.HTTPError as error:
        if error.code in (400, 409):
            duplicate = _duplicate_contact_id(error)
            if duplicate:
                return duplicate
        raise
    contact = created.get("contact", created) if isinstance(created, dict) else {}
    return contact.get("id") or created.get("id")


def _get_or_create_conversation(client, contact_id: str) -> str | None:
    data = client.get("/conversations/search",
                      {"locationId": client.location_id, "contactId": contact_id})
    convos = (data.get("conversations", []) if isinstance(data, dict) else []) or []
    if convos:
        return convos[0]["id"]
    new = client.post("/conversations/",
                     {"locationId": client.location_id, "contactId": contact_id})
    return (new.get("conversation", {}) or {}).get("id") or new.get("id")


FAMILY_TAG = "daycare family"
LOCATION_PREFIX = "location: "


def location_tag(location_name: str | None) -> str:
    """The tag that keeps centers apart INSIDE GoHighLevel.

    All four centers share ONE GHL sub-account (one API key in daycare.env), so GHL
    itself has no notion of our locations — this tag is the only thing separating them
    over there. Exactly one `location: <center>` tag per contact, always.
    """
    return (LOCATION_PREFIX + (location_name or "").strip().lower())[:64]


def contact_tags(client, contact_id: str) -> list[str]:
    try:
        data = client.get(f"/contacts/{contact_id}")
    except Exception:  # noqa: BLE001 — a tag read must never break an enrollment
        return []
    contact = (data.get("contact") or data) if isinstance(data, dict) else {}
    return [str(tag) for tag in (contact.get("tags") or [])]


def sync_family(client, *, name: str, phone: str, email: str | None = None,
                location_name: str = "", child_name: str = "") -> dict:
    """Mirror ONE daycare family into GHL as a contact, tagged with ITS center.

    Owner-initiated: this runs because the owner clicked "save child" in the console.
    Internal + reversible (writes a contact + a tag, sends NO message), so it needs no
    separate approval — same rationale as the HOT-lead auto-tag in CLAUDE.md rule 2.

    If the family already carries a DIFFERENT `location:` tag (they moved centers, or
    the contact was created under the wrong one), the stale tag is removed — otherwise
    a child who transfers from Blessings 1 to Blessings 2 would show up in BOTH centers'
    GHL segments, which is exactly the leak we're preventing everywhere else.
    """
    if client is None or not client.configured:
        return {"ok": False, "synced": False,
                "detail": "GHL not connected — add GHL_API_KEY + GHL_LOCATION_ID to daycare.env."}
    if not (phone or "").strip():
        return {"ok": True, "synced": False, "detail": "No phone on file — nothing to sync."}

    contact_id = ensure_contact(client, name=name or "Family", phone=phone, email=email)
    if not contact_id:
        return {"ok": False, "synced": False, "detail": "Could not create the GHL contact."}

    wanted = location_tag(location_name)
    existing = contact_tags(client, contact_id)
    stale = [tag for tag in existing
             if tag.lower().startswith(LOCATION_PREFIX) and tag.lower() != wanted]
    if stale:
        try:
            client.delete(f"/contacts/{contact_id}/tags", {"tags": stale})
        except Exception:  # noqa: BLE001 — best-effort; the add below still runs
            pass

    tags = [FAMILY_TAG, wanted]
    if child_name:
        tags.append(("child: " + str(child_name).strip().lower())[:64])
    client.post(f"/contacts/{contact_id}/tags", {"tags": tags})
    return {"ok": True, "synced": True, "contactId": contact_id,
            "tags": tags, "removed": stale}


# --- Family Contact Form intake -> dashboard bridge (read-only) -------------
# The public fillout form (daycare-fillout-form.vercel.app) upserts each existing
# family into GHL tagged `family-contact-form`, with the child's name/DOB in these
# custom fields (ids created 2026-07-19, mirrored in that repo's api/submit.js).
FORM_TAG = "family-contact-form"       # existing-student intake (submit.js)
LEAD_TAG = "website-lead"              # brand-new inquiry from the marketing site (enroll.js)
ENROLLED_TAGS = ("enrolled", "existing-student")  # a family the daycare actually has
# age-band tag (both forms' GROUP_TAG constant) -> the keyword to match against a
# Supabase classroom's name/age_group when auto-assigning on enroll (daycare_supabase
# .find_classroom_id). Keep in sync with GROUP_TAG in submit.js / enroll.js.
GROUP_TAG_LABEL = {
    "group-infants": "Infant",
    "group-toddlers": "Toddler",
    "group-prek": "Pre-K",
    "group-schoolage": "School-Age",
}
CF_CHILD_NAME = "XuWMrMVQSx3W1drZR0e0"
CF_PARENT_NAME = "68zgbWrCHH0e9OIyuRJx"  # added 2026-07-21 — contact identity flipped to
# the child's name (firstName/lastName), parent's name now lives here instead.
CF_CHILD_DOB = "WQctVJsId5tRNHqlhwho"
CF_EMERG_NAME = "pF09l1zZhPh1zOi7CWLc"
CF_EMERG_PHONE = "ZidoyoCzWfoNVak9G494"
CF_EMERG_REL = "eKCWiJmLhRwbHyeO0Rkh"
CF_ENROLL_STATUS = "d7sKOSmyfbxmXnuIOtNr"  # 'Enrolled' (form) vs 'Lead' (inquiry)


def _cf_map(contact: dict) -> dict:
    """Flatten a GHL contact's custom fields to {id: value} (v2 shape varies)."""
    out: dict[str, str] = {}
    for item in (contact.get("customFields") or contact.get("customField") or []):
        if not isinstance(item, dict):
            continue
        key = item.get("id") or item.get("customFieldId")
        val = item.get("value")
        if val is None:
            val = item.get("field_value") or item.get("fieldValue")
        if key and val not in (None, ""):
            out[str(key)] = val
    return out


def _split_name(full: str) -> tuple[str, str]:
    parts = [p for p in str(full or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _family_from_contact(contact: dict) -> dict:
    cf = _cf_map(contact)
    tags = [str(t) for t in (contact.get("tags") or [])]
    tl = {t.lower() for t in tags}
    loc_tag = next((t for t in tags if t.lower().startswith("loc-")), "")
    # Enrolled vs brand-new inquiry: only an actually-enrolled family (existing-student
    # form) ever gets a parent app login. A website-lead is a prospect — no login until
    # they enroll. Tags are the truth; the enrollStatus custom field is the fallback.
    enrolled = any(t in tl for t in ENROLLED_TAGS)
    enroll_status = (cf.get(CF_ENROLL_STATUS) or "").strip() or (
        "Enrolled" if enrolled else ("Lead" if LEAD_TAG in tl else ""))
    if not enrolled and enroll_status.lower() == "enrolled":
        enrolled = True
    # Contact identity flipped 2026-07-21: submit.js / enroll.js now write firstName/
    # lastName from the CHILD's name, with the parent's name in CF_PARENT_NAME. Contacts
    # created before that fix have it the other way (firstName/lastName = parent,
    # CF_CHILD_NAME = child). CF_PARENT_NAME's presence tells us which regime applies.
    parent_full = cf.get(CF_PARENT_NAME) or ""
    # A multi-child inquiry stores "Maria Lopez, Juan Lopez" — the card is the first child.
    child_cf = str(cf.get(CF_CHILD_NAME) or "").split(",")[0].strip()
    if parent_full:
        # GET /contacts/ (iter_contacts) returns firstName/lastName LOWERCASED, so a
        # child saved from them lands in the roster as "maria lopez". The child-name
        # field keeps exactly what the parent typed, so it wins.
        child_full = child_cf or " ".join(
            p for p in ((contact.get("firstName") or "").strip(),
                        (contact.get("lastName") or "").strip()) if p)
        c_first, c_last = _split_name(child_full)
        p_first, p_last = _split_name(parent_full)
    else:
        p_first = (contact.get("firstName") or "").strip()
        p_last = (contact.get("lastName") or "").strip()
        if not p_first and not p_last:
            p_first, p_last = _split_name(contact.get("contactName") or contact.get("name"))
        child_full = child_cf
        c_first, c_last = _split_name(child_full)
    emerg_name = (cf.get(CF_EMERG_NAME) or "").strip()
    emerg_phone = (cf.get(CF_EMERG_PHONE) or "").strip()
    emerg_rel = (cf.get(CF_EMERG_REL) or "").strip()
    pickup_lines = []
    if emerg_name:
        rel = f" ({emerg_rel})" if emerg_rel else ""
        ph = f" — {emerg_phone}" if emerg_phone else ""
        pickup_lines.append(f"Emergency contact: {emerg_name}{rel}{ph}")
    classroom_label = next((label for tag, label in GROUP_TAG_LABEL.items() if tag in tl), "")
    return {
        "contact_id": contact.get("id"),
        # website-lead vs family-contact-form — roster dedup only makes sense for a
        # lead who already enrolled elsewhere; an existing-student form submission
        # being in the roster is expected, not a reason to hide it. Forms ADD tags, so a
        # former lead who later filled the Contact Form carries both — enrolled wins.
        "is_lead": LEAD_TAG in tl and not enrolled,
        # age-band keyword ("Infant"/"Toddler"/"Pre-K"/"School-Age") for auto-matching
        # a Supabase classroom on one-click enroll — "" when the form had no age tag.
        "classroom_label": classroom_label,
        "parent_first": p_first,
        "parent_last": p_last,
        "parent_name": (p_first + " " + p_last).strip(),
        "phone": contact.get("phone") or "",
        "email": (contact.get("email") or "").strip(),
        "child_name": child_full,
        "child_first": c_first,
        "child_last": c_last,
        "child_dob": cf.get(CF_CHILD_DOB) or "",
        "emergency_name": emerg_name,
        "emergency_phone": emerg_phone,
        "emergency_relationship": emerg_rel,
        # Seed the child's pickup_notes with the emergency contact (from custom fields);
        # pending_families() appends the authorized-pickup people + freeform note it reads
        # from the GHL Note body, and fills medical_notes.
        "pickup_notes": "\n".join(pickup_lines),
        "medical_notes": "",
        "allergies": "",
        "location_tag": loc_tag,
        # kind drives the inbox: "enrolled" families can be given a login; "inquiry"
        # (brand-new, not in the daycare yet) are shown marked, with NO login.
        "enrolled": enrolled,
        "enroll_status": enroll_status,
        "kind": "enrolled" if enrolled else "inquiry",
        "created_at": contact.get("dateAdded") or contact.get("createdAt") or "",
    }


def _parse_intake_note(body: str) -> tuple[list[str], str]:
    """Pull the authorized-pickup people + the freeform NOTES section out of the Family
    Contact Form intake note (format from the fillout form's summaryText). Returns
    (people_lines, freeform_notes). Section headers are ALL-CAPS lines; items under them
    are indented. Best-effort — an unrecognized note yields ([], "")."""
    people: list[str] = []
    notes_lines: list[str] = []
    section = None
    for raw in str(body or "").splitlines():
        stripped = raw.strip()
        upper = stripped.upper()
        if upper in ("OTHER AUTHORIZED PEOPLE", "NOTES", "CHILD", "PARENT / GUARDIAN",
                     "EMERGENCY CONTACT", "FAMILY CONTACT FORM — STUDENT INTAKE"):
            section = upper
            continue
        if not stripped:
            continue
        if section == "OTHER AUTHORIZED PEOPLE":
            people.append(stripped)
        elif section == "NOTES":
            notes_lines.append(stripped)
    return people, " ".join(notes_lines).strip()


def _contact_note_body(client, contact_id: str) -> str:
    """Newest Family-Contact-Form intake note body for a contact (read-only, best-effort)."""
    if not contact_id:
        return ""
    try:
        data = client.get(f"/contacts/{contact_id}/notes")
    except Exception:  # noqa: BLE001 — a note read must never break the inbox
        return ""
    notes = data.get("notes") if isinstance(data, dict) else None
    for note in (notes or []):
        body = note.get("body") or ""
        if "STUDENT INTAKE" in body or "EMERGENCY CONTACT" in body:
            return body
    return (notes[0].get("body") or "") if notes else ""


def family_intake(client, contact_id: str) -> dict:
    """Read a family's GHL intake note → the authorized-pickup people + freeform notes
    (the parts the form keeps only in the Note, not custom fields). Read-only, best-effort;
    used to fill the child's pickup_notes / medical_notes when provisioning from the inbox."""
    people, freeform = _parse_intake_note(_contact_note_body(client, contact_id))
    return {"authorized_pickup": people, "notes": freeform}


def iter_contacts(client, *, max_pages: int = 6, page_size: int = 100):
    """Yield every raw contact in the daycare location (read-only paging).

    GHL v2 has no server-side tag filter on the list endpoint, so callers page the
    location's contacts and filter client-side.
    ponytail: caps at max_pages*page_size contacts (the location is small); raise
    the cap or move to POST /contacts/search if the account grows past that.
    """
    after: tuple[str, str] | None = None
    for _ in range(max_pages):
        params = {"locationId": client.location_id, "limit": page_size}
        if after:
            params["startAfterId"] = after[0]
            if after[1]:
                params["startAfter"] = after[1]
        data = client.get("/contacts/", params)
        contacts = (data.get("contacts") if isinstance(data, dict) else None) or []
        if not contacts:
            break
        yield from contacts
        meta = (data.get("meta") if isinstance(data, dict) else None) or {}
        nxt_id = meta.get("startAfterId")
        if not nxt_id:
            break
        after = (str(nxt_id), str(meta.get("startAfter") or ""))


# --- Family-form confirmation + multi-child (spec 2026-10-05-family-form-automation) ---
# forms/api/submit.js keeps one entry per child in children_json; child 0 is the contact's
# identity. Each child is its own inbox card keyed card_id = contact_id (child 0) or
# "contact_id#i" — the key dismiss() and the form-child ledger use, so enrolling or
# dismissing one sibling never touches another.
CF_CHILDREN_JSON = "e7YOKwZiHYM5lUnehTGE"
CF_SHIRT = "YlJ22B5f89vAQBFWBkW5"
CF_PANTS = "HnSCMs702Efn0eNPEEfi"
CF_CONFIRM_SENT = "D1HjF1rkDPhTQsNoPCoc"
CF_CONFIRMED_AT = "T4h8YJeha9uvQE5MgBNf"
CONFIRM_PENDING_TAG = "family-confirm-pending"
CONFIRMED_TAG = "family-confirmed"
# Tags forms/api/submit.js (or the backfill) sets when a human must look before trusting
# the data. Shown on the card as a warning; they do not block Create login.
REVIEW_TAGS = {"child-age-review": "age — DOB and typed age disagree, check the classroom",
               "child-name-review": "child name — a submission was not added as a new child",
               "contact-match-review": "contact — matched by email under a different phone"}
GROUP_TAG_BY_LABEL = {"Infants": "group-infants", "Toddlers": "group-toddlers",
                      "Pre-K": "group-prek", "School-Age": "group-schoolage"}


def card_contact_id(card_id: str | None) -> str:
    """'abc#1' -> 'abc' (the GHL contact a sibling card belongs to)."""
    return str(card_id or "").split("#", 1)[0]


def _children_entries(contact: dict) -> list[dict]:
    raw = _cf_map(contact).get(CF_CHILDREN_JSON)
    if not raw:
        return []
    try:
        arr = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [c for c in arr if isinstance(c, dict) and str(c.get("name") or "").strip()] \
        if isinstance(arr, list) else []


def _confirm_state(contact: dict, tags: set[str], now: float) -> str:
    """'confirmed' | 'pending' | 'no_reply' | '' (never texted)."""
    if CONFIRMED_TAG in tags:
        return "confirmed"
    if CONFIRM_PENDING_TAG not in tags:
        return ""
    sent = str(_cf_map(contact).get(CF_CONFIRM_SENT) or "")
    try:
        from datetime import datetime
        at = datetime.fromisoformat(sent.replace("Z", "+00:00")).timestamp()
        if now - at > 48 * 3600:
            return "no_reply"
    except ValueError:
        pass
    return "pending"


def _readiness(card: dict) -> list[str]:
    """What Create login still needs. Empty = ready. Mirrors _daycare_enroll_family:
    a login needs an email, a child DOB, and the parent's first + last name; a child row
    needs a first name, a surname (child's or parent's), and a known center."""
    missing = []
    if not card.get("enrolled"):
        missing.append("not enrolled")
    if not str(card.get("child_first") or "").strip():
        missing.append("child name")
    if not str(card.get("child_last") or card.get("parent_last") or "").strip():
        missing.append("last name")
    if not LOCATION_ID_BY_TAG.get(str(card.get("location_tag") or "").lower()):
        missing.append("location")
    if not str(card.get("email") or "").strip():
        missing.append("parent email")
    if not str(card.get("phone") or "").strip():
        missing.append("parent phone")
    if not iso_date(card.get("child_dob")):
        missing.append("child birth date")
    if not str(card.get("parent_first") or "").strip():
        missing.append("parent first name")
    if not str(card.get("parent_last") or "").strip():
        missing.append("parent last name")
    return missing


def family_cards(contact: dict, now: float | None = None) -> list[dict]:
    """One inbox card per child on the contact (a contact with no children_json = one card,
    exactly the pre-2026-10-05 behaviour)."""
    import time as _time
    now = now or _time.time()
    base = _family_from_contact(contact)
    tags = {str(t).lower() for t in (contact.get("tags") or [])}
    cf = _cf_map(contact)
    cid = str(base.get("contact_id") or "")
    base.update({"card_id": cid, "child_index": 0, "children_count": 1,
                 "shirt_size": cf.get(CF_SHIRT) or "", "pants_size": cf.get(CF_PANTS) or "",
                 "confirm_state": _confirm_state(contact, tags, now),
                 "confirmed_at": cf.get(CF_CONFIRMED_AT) or "",
                 "review": [msg for tag, msg in REVIEW_TAGS.items() if tag in tags]})
    kids = _children_entries(contact)
    cards = []
    for i, kid in enumerate(kids or [None]):
        card = dict(base)
        if kid is not None:
            first, last = _split_name(kid.get("name"))
            card.update({
                "card_id": cid if i == 0 else f"{cid}#{i}", "child_index": i,
                "children_count": len(kids),
                "child_name": str(kid.get("name") or "").strip(),
                "child_first": first, "child_last": last,
                "child_dob": kid.get("dob") or (base["child_dob"] if i == 0 else ""),
                "shirt_size": kid.get("shirt") or "", "pants_size": kid.get("pants") or "",
            })
            if kid.get("loc"):
                card["location_tag"] = kid["loc"]
            if kid.get("group") in GROUP_TAG_BY_LABEL:
                card["classroom_label"] = GROUP_TAG_LABEL[GROUP_TAG_BY_LABEL[kid["group"]]]
        card["missing"] = _readiness(card)
        card["ready"] = not card["missing"]
        cards.append(card)
    return cards


def pending_families(client, *, max_pages: int = 6, page_size: int = 100) -> list[dict]:
    """List families submitted through the Family Contact Form (tagged FORM_TAG) —
    one card per child.

    Read-only. Pages the location's contacts (iter_contacts) and filters client-side.
    """
    if client is None or not client.configured:
        return []
    out: list[dict] = []
    for contact in iter_contacts(client, max_pages=max_pages, page_size=page_size):
        tags = [str(t).lower() for t in (contact.get("tags") or [])]
        # Existing-student form families (get a login) AND brand-new website inquiries
        # (shown marked, no login) — so the inbox tells them apart instead of guessing.
        if FORM_TAG in tags or LEAD_TAG in tags:
            out.extend(family_cards(contact))
    return out


def send_sms(client, *, contact_id: str, message: str) -> dict:
    """Send one SMS to a family contact. Owner-initiated; not autonomous."""
    if client is None or not client.configured:
        return {"ok": False, "connected": False,
                "detail": "Add GHL_API_KEY + GHL_LOCATION_ID to daycare.env to text families."}
    text = (message or "").strip()
    if not contact_id or not text:
        return {"ok": False, "detail": "contact and message are required"}
    conv_id = _get_or_create_conversation(client, contact_id)
    payload = {"type": "SMS", "contactId": contact_id, "message": text}
    if conv_id:
        payload["conversationId"] = conv_id
    result = client.post("/conversations/messages", payload)
    return {"ok": True, "sent": True, "conversationId": conv_id,
            "messageId": result.get("messageId") or result.get("id")}


AMT_LOCATION_PREFIX = "44444444"  # A Mother's Touch (1923 Cecil B. Moore) — its own brand + app link


# Family Contact Form / lead GHL location tag -> Supabase center id (stable business ids,
# not secrets). connector.DAYCARE_FORM_LOCATION_BY_TAG points at this same dict.
LOCATION_ID_BY_TAG = {
    "loc-921-n-18th": "11111111-1111-1111-1111-111111111111",       # A Touch of Blessings
    "loc-2318-cecil-b-moore": "22222222-2222-2222-2222-222222222222",  # A Touch of Blessings 2
    "loc-1923-cecil-b-moore": "44444444-4444-4444-4444-444444444444",  # A Mother's Touch
}

# App Tracking page tabs -> center. QA 9999 is deliberately absent.
APP_TRACKING_CENTERS = {
    "921": LOCATION_ID_BY_TAG["loc-921-n-18th"],
    "2318": LOCATION_ID_BY_TAG["loc-2318-cecil-b-moore"],
    "1923": LOCATION_ID_BY_TAG["loc-1923-cecil-b-moore"],
}


def iso_date(value) -> str:
    """GHL's Child DOB is free text ("03/14/2023" or "2023-03-14") → YYYY-MM-DD, else ""."""
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m.%d.%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y"):
        try:
            got = datetime.strptime(raw[:10] if fmt == "%Y-%m-%d" else raw, fmt).date()
        except ValueError:
            continue
        return got.isoformat() if got <= datetime.now().date() else ""   # a future DOB is a typo
    return ""


def _brand_link(location_id):
    if str(location_id or "").startswith(AMT_LOCATION_PREFIX):
        return "A Mother's Touch", "https://atouchofblessing.com/get-app-mothers-touch"
    return "A Touch of Blessings", "https://atouchofblessing.com/get-app"


def start_day_text(parent_first, child_first, login_id, pin, location_id) -> str:
    """The first-day SMS (daycare_starts): welcome + app login + how to get the app, in the
    get-app page's own steps. Pure — no I/O. Same name/label rules as login_text."""
    parent = str(parent_first or "").strip()[:30]
    child = str(child_first or "").strip()[:30]
    login_id = str(login_id or "")[:60]
    brand, link = _brand_link(location_id)
    greet = parent if len(parent) > 1 else "there"
    whose = f"{child}'s" if len(child) > 1 else "your child's"
    bl = str(login_id or "").startswith("BL-")
    label = "Login ID" if bl else "Sign in with your name"
    how = "your Login ID" if bl else "your first + last name"
    if not pin:     # the parent already has a login: welcome + guide, never a PIN reset
        return (f"Hi {greet}! Welcome to {brand} - today is {whose} first day!\n"
                f"Your family app: open {link} and tap Open the app, then sign in the way you "
                "already do (your name or Login ID + your PIN). Forgot your PIN? Just ask a staff member.\n"
                "iPhone: Share > Add to Home Screen keeps it one tap away.")
    return (f"Hi {greet}! Welcome to {brand} - today is {whose} first day!\n"
            f"Your family app login:\n{label}: {login_id}\nPIN: {pin}\n"
            f"Get the app: open {link} and tap Open the app, then sign in with {how} + PIN. "
            "iPhone: Share > Add to Home Screen keeps it one tap away.\n"
            "Keep your PIN private. Questions? Just ask a staff member.")


def login_text(parent_first, child_first, login_id, pin, location_id) -> str:
    """The SMS a parent gets when the owner clicks Create login. Pure — no I/O.
    A name under 2 characters (a GHL field typed "I") counts as missing."""
    parent = str(parent_first or "").strip()
    child = str(child_first or "").strip()
    brand, link = _brand_link(location_id)
    greet = parent if len(parent) > 1 else "there"
    whose = f"{child}'s" if len(child) > 1 else "Your child's"
    # Legacy accounts / non-Latin names fall back to a BL- Login ID (same rule as the modal).
    label = "Login ID" if str(login_id or "").startswith("BL-") else "Sign in with your name"
    return (f"Hi {greet}! {whose} {brand} family app is ready.\n"
            f"{label}: {login_id}\n"
            f"PIN: {pin}\n"
            f"Get the app: {link}\n"
            "Keep your PIN private. Questions? Just ask a staff member.")
