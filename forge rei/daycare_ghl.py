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
    child_cf = cf.get(CF_CHILD_NAME) or ""
    if parent_full:
        c_first = (contact.get("firstName") or "").strip()
        c_last = (contact.get("lastName") or "").strip()
        child_full = (c_first + " " + c_last).strip() or child_cf
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
    return {
        "contact_id": contact.get("id"),
        # website-lead vs family-contact-form — roster dedup only makes sense for a
        # lead who already enrolled elsewhere; an existing-student form submission
        # being in the roster is expected, not a reason to hide it.
        "is_lead": LEAD_TAG in tl,
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


def pending_families(client, *, max_pages: int = 6, page_size: int = 100) -> list[dict]:
    """List families submitted through the Family Contact Form (tagged FORM_TAG).

    Read-only. GHL v2 has no server-side tag filter on the list endpoint, so we
    page the location's contacts and filter client-side.
    ponytail: caps at max_pages*page_size contacts (form intake is small); raise
    the cap or move to POST /contacts/search if the account grows past that.
    """
    if client is None or not client.configured:
        return []
    out: list[dict] = []
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
        for contact in contacts:
            tags = [str(t).lower() for t in (contact.get("tags") or [])]
            # Existing-student form families (get a login) AND brand-new website inquiries
            # (shown marked, no login) — so the inbox tells them apart instead of guessing.
            if FORM_TAG in tags or LEAD_TAG in tags:
                out.append(_family_from_contact(contact))
        meta = (data.get("meta") if isinstance(data, dict) else None) or {}
        nxt_id = meta.get("startAfterId")
        if not nxt_id:
            break
        after = (str(nxt_id), str(meta.get("startAfter") or ""))
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
