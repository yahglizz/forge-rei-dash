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

import re


def _digits(phone: str | None) -> str:
    return re.sub(r"[^0-9+]", "", str(phone or ""))


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
    """Return a GHL contact id for the family, creating it if needed."""
    existing = find_contact_by_phone(client, phone)
    if existing:
        return existing
    body = {"locationId": client.location_id, "name": name or "Family", "phone": _digits(phone)}
    if email and "@" in email and not email.lower().endswith("@login.blessings.app"):
        body["email"] = email
    created = client.post("/contacts/", body)
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
