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
import urllib.error


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
FORM_TAG = "family-contact-form"
CF_CHILD_NAME = "XuWMrMVQSx3W1drZR0e0"
CF_CHILD_DOB = "WQctVJsId5tRNHqlhwho"


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
    loc_tag = next((t for t in tags if t.lower().startswith("loc-")), "")
    p_first = (contact.get("firstName") or "").strip()
    p_last = (contact.get("lastName") or "").strip()
    if not p_first and not p_last:
        p_first, p_last = _split_name(contact.get("contactName") or contact.get("name"))
    child_full = cf.get(CF_CHILD_NAME) or ""
    c_first, c_last = _split_name(child_full)
    return {
        "contact_id": contact.get("id"),
        "parent_first": p_first,
        "parent_last": p_last,
        "parent_name": (p_first + " " + p_last).strip(),
        "phone": contact.get("phone") or "",
        "email": (contact.get("email") or "").strip(),
        "child_name": child_full,
        "child_first": c_first,
        "child_last": c_last,
        "child_dob": cf.get(CF_CHILD_DOB) or "",
        "location_tag": loc_tag,
        "created_at": contact.get("dateAdded") or contact.get("createdAt") or "",
    }


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
            if FORM_TAG in tags:
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
