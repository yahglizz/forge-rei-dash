#!/usr/bin/env python3
"""Billing P0 — owner texts a family a Stripe pay link for the REMAINING balance.

Three calls, all behind the signed-in dashboard session (contract: billing-p0 CONTRACTS §4):
  compose(session, invoice_id)            -> the draft text (facts only from the database)
  send(session, invoice_id, message, ghl) -> Stripe hosted invoice + DB log + GHL text
  timeline(session, invoice_id, ghl)      -> refresh delivery status, then the DB timeline

Propose -> review -> execute: nothing here runs on a loop. `send` is the owner's tap and is the
only thing that texts a parent. No "Reply STOP" line, ever (owner decision 2026-10-07).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, datetime

import daycare_ghl
import daycare_supabase
import stripe_io

_log = logging.getLogger("daycare_billing_link")
PLACEHOLDER = "{{PAY_URL}}"
MAX_MESSAGE = 640
RESEND_WINDOW = 120   # seconds; contract change 1
PENDING_WARNING = "A payment is processing for this invoice."
PENDING_REFUSAL = "A payment is processing for this invoice. Wait for it to clear before sending a link."
TOO_SOON = "A link was just sent for this invoice. Check the Timeline before sending again."
_INFLIGHT: set[str] = set()
_RECENT: dict[str, float] = {}
_LOCK = threading.Lock()
_REFRESHED: dict[str, float] = {}


class BillingLinkError(Exception):
    """Expected refusal with a plain sentence the owner can read."""

    def __init__(self, status: int, detail: str, code: str = "billing_link_error"):
        super().__init__(detail)
        self.status = int(status)
        self.message = detail
        self.code = code

    def payload(self) -> dict:
        return {"ok": False, "detail": self.message, "error": self.message, "code": self.code}


def _money(cents: int) -> str:
    return f"{int(cents) // 100:,}.{int(cents) % 100:02d}"


def _due_phrase(due_on, today: date) -> str:
    try:
        day = datetime.strptime(str(due_on)[:10], "%Y-%m-%d").date()
    except ValueError:
        return ""
    label = f"{day:%b} {day.day}"
    return f", past due since {label}" if day < today else f", due {label}"


def compose_text(facts: dict, today: date | None = None) -> tuple[str, list[str]]:
    """The draft SMS (with one {{PAY_URL}}) + warnings. Pure."""
    today = today or daycare_supabase._today_et()
    brand = daycare_ghl._brand_link(facts.get("location_id"))[0]
    parent = str((facts.get("guardian") or {}).get("first_name") or "").strip()[:30]
    child = str((facts.get("child") or {}).get("first_name") or "").strip()[:30]
    warnings: list[str] = []
    if len(parent) < 2:
        parent = ""
        warnings.append("No parent first name on file; the text says 'Hi there'.")
    if facts.get("child_ambiguous") or len(child) < 2:
        if facts.get("child_ambiguous"):
            warnings.append("This invoice is not tied to one child and the parent has several; "
                            "the text names no child. Edit it if you want a name in.")
        child = ""
    number = str(facts.get("invoice_number") or "your invoice")
    whose = f"{child}'s invoice {number}" if child else f"Invoice {number}"
    greet = f"Hi {parent}" if parent else "Hi there"
    text = (f"{greet}, this is {brand}. {whose} has ${_money(facts['balance_cents'])} left"
            f"{_due_phrase(facts.get('due_on'), today)}. Pay securely here: {PLACEHOLDER}")
    if facts.get("has_pending_payment"):
        warnings.append(PENDING_WARNING)
    if not (facts.get("guardian") or {}).get("phone"):
        warnings.append("No phone number on file for this parent; Send will be refused.")
    return text, warnings


def _facts_or_refuse(session, invoice_id) -> dict:
    facts = daycare_supabase.billing_invoice_facts(session, invoice_id)
    if facts.get("status") in ("void", "paid"):
        raise BillingLinkError(409, f"This invoice is {facts['status']}; there is nothing to collect.", "invoice_closed")
    if facts.get("status") == "draft":
        raise BillingLinkError(409, "This invoice is still a draft. Issue it before texting a pay link.", "invoice_draft")
    if facts["balance_cents"] <= 0:
        raise BillingLinkError(409, "There is no balance left on this invoice.", "no_balance")
    return facts


def compose(session, invoice_id) -> dict:
    facts = _facts_or_refuse(session, invoice_id)
    message, warnings = compose_text(facts)
    return {
        "ok": True,
        "message": message,
        "facts": {
            "parent_first_name": (facts["guardian"].get("first_name") or ""),
            "child_first_name": ("" if facts["child_ambiguous"] else (facts["child"] or {}).get("first_name") or ""),
            "balance": _money(facts["balance_cents"]),
            "balance_cents": facts["balance_cents"],
            "due_on": facts.get("due_on"),
            "invoice_number": facts.get("invoice_number"),
            "brand": daycare_ghl._brand_link(facts.get("location_id"))[0],
            "center_name": facts.get("center_name") or "",
            "livemode": str(facts.get("location_id")).lower() != stripe_io.QA_LOCATION_ID,
        },
        "warnings": warnings,
    }


def validate_message(message) -> str:
    text = str(message or "").strip()
    if not text:
        raise BillingLinkError(400, "The message is empty.", "validation_error")
    if text.count(PLACEHOLDER) != 1:
        raise BillingLinkError(400, f"The message must contain {PLACEHOLDER} exactly once; "
                                    "that is where the pay link goes.", "validation_error")
    if len(text) > MAX_MESSAGE:
        raise BillingLinkError(400, f"The message is {len(text)} characters; the limit is {MAX_MESSAGE}.", "validation_error")
    if re.search(r"reply\s+stop|text\s+stop|\bstop\s+to\s+(opt|unsub)", text, re.I):
        raise BillingLinkError(400, "Remove the opt-out line; this workspace never adds one to texts.", "validation_error")
    return text


def _rpc_row(result):
    return result[0] if isinstance(result, list) and result else (result if isinstance(result, dict) else {})


def send(session, invoice_id, message, ghl) -> dict:
    """Owner's tap. Order: validate everything -> Stripe link -> DB row -> text -> mark sent."""
    text = validate_message(message)
    facts = _facts_or_refuse(session, invoice_id)
    if facts.get("has_pending_payment"):
        raise BillingLinkError(409, PENDING_REFUSAL, "payment_processing")
    phone = (facts["guardian"].get("phone") or "").strip()
    if not phone:
        raise BillingLinkError(400, "This parent has no phone number on file.", "no_phone")
    if ghl is None or not getattr(ghl, "configured", False):
        raise BillingLinkError(503, "GoHighLevel is not connected, so the text cannot be sent.", "ghl_not_configured")

    release = reserve_link(session, facts["invoice_id"])
    try:
        return _send_locked(session, facts, text, ghl)
    finally:
        release()


def reserve_link(session, invoice_id, recent: bool | None = None):
    """The one guard in front of anything that builds a pay link for an invoice (owner send AND the
    reminder refresh), so the two can never race into two Stripe invoices or two texts.
    DB guard (survives restarts): a created/sent/delivered row younger than 120 s. In-process guard:
    a concurrent build, and an UNKNOWN GHL outcome (that row is 'failed' in the DB).
    `recent` lets a caller that already read the DB guard inside the right center pass the answer.
    Raises BillingLinkError(409, TOO_SOON); returns a release() to call when the build is done."""
    key = str(invoice_id)
    if recent is None:
        recent = daycare_supabase.billing_recent_send(session, invoice_id, RESEND_WINDOW)
    if recent:
        raise BillingLinkError(409, TOO_SOON, "recent_send")
    with _LOCK:
        if key in _INFLIGHT or time.time() - _RECENT.get(key, 0) < RESEND_WINDOW:
            raise BillingLinkError(409, TOO_SOON, "recent_send")
        _INFLIGHT.add(key)

    def release():
        with _LOCK:
            _INFLIGHT.discard(key)
    return release


def arm_recent(invoice_id) -> None:
    """Block a second link build for this invoice for the resend window (a text just went out)."""
    with _LOCK:
        _RECENT[str(invoice_id)] = time.time()


def deliver_text(ghl, facts: dict, text: str, location_id) -> dict:
    """THE one GHL text path for billing (pay-link send, legacy text, overdue reminders):
    child-named contact by phone -> additive family tag (a tag failure only warns) -> SMS.
    Returns {"message_id", "tag_warning"}; raises BillingLinkError (ghl_contact | ghl_send |
    ghl_send_unknown). Never leaks upstream bodies."""
    child = facts.get("child") or {}
    phone = (facts["guardian"].get("phone") or "").strip()
    try:
        contact_id = daycare_ghl.ensure_family_contact(
            ghl, phone=phone, child_first=child.get("first_name", ""), child_last=child.get("last_name", ""),
            parent_name=facts["guardian"].get("name", ""), email=facts["guardian"].get("email"))
        if not contact_id:
            raise BillingLinkError(502, "Could not find or create the family's GoHighLevel contact.", "ghl_contact")
        tag_warning = daycare_ghl.add_family_tags(ghl, contact_id, location_id)   # before the text; never blocks it
        sent = daycare_ghl.send_sms(ghl, contact_id=contact_id, message=text)
        if not sent.get("ok"):
            raise BillingLinkError(502, sent.get("detail") or "GoHighLevel did not accept the text.", "ghl_send")
    except BillingLinkError:
        raise
    except Exception as error:  # noqa: BLE001
        unknown = type(error).__name__ == "GHLSendUnknown"
        note = ("Unknown whether the text went out. Check the GoHighLevel conversation before sending again."
                if unknown else "GoHighLevel rejected the text (check the contact: opted out, no phone, or Do Not Disturb).")
        raise BillingLinkError(502, note, "ghl_send_unknown" if unknown else "ghl_send") from None
    return {"message_id": sent.get("messageId"), "tag_warning": tag_warning}


def create_link(session, facts: dict, text: str) -> dict:
    """The existing link path: Stripe hosted invoice for the CURRENT balance (ensure_hosted_invoice)
    + a billing_link_sends row (billing_create_link_send; `text` carries {{PAY_URL}}, the RPC fills it).
    Returns {"send_id", "pay_url", "final_text"}. Raises on any failure; texts nothing."""
    hosted = stripe_io.ensure_hosted_invoice({
        "invoice_id": facts["invoice_id"], "invoice_number": facts["invoice_number"],
        "balance_cents": facts["balance_cents"], "paid_cents": facts["paid_cents"],
        "due_on": facts["due_on"], "description": facts.get("description"),
        "guardian": facts["guardian"],
        "known_stripe_invoice_ids": facts.get("known_stripe_invoice_ids") or [],
    }, facts["location_id"])

    row = _rpc_row(daycare_supabase.billing_rpc(session, "billing_create_link_send", {
        "p_invoice": facts["invoice_id"], "p_hosted_url": hosted["hosted_url"],
        "p_stripe_invoice_id": hosted["stripe_invoice_id"], "p_livemode": bool(hosted["livemode"]),
        "p_message": text, "p_amount_cents": facts["balance_cents"],
    }))
    send_id, pay_url, final_text = row.get("id"), row.get("pay_url"), row.get("message")
    if not (send_id and pay_url and final_text) or PLACEHOLDER in final_text:
        raise BillingLinkError(502, "The pay link could not be saved, so nothing was texted.", "rpc_bad_shape")
    return {"send_id": send_id, "pay_url": pay_url, "final_text": final_text}


def mark_link(session, send_id, status, mid=None, err=None) -> bool:
    try:
        daycare_supabase.billing_rpc(session, "billing_mark_link_sent", {
            "p_id": send_id, "p_status": status, "p_ghl_message_id": mid, "p_error": err})
        return True
    except Exception:  # noqa: BLE001 — the text already went out (or failed); never crash the response
        _log.exception("billing_mark_link_sent failed for send %s", send_id)
        return False


def _send_locked(session, facts, text, ghl) -> dict:
    location_id = facts["location_id"]
    created = create_link(session, facts, text)
    send_id, pay_url, final_text = created["send_id"], created["pay_url"], created["final_text"]

    def mark(status, mid=None, err=None):
        return mark_link(session, send_id, status, mid, err)

    try:
        delivered = deliver_text(ghl, facts, final_text, location_id)
    except BillingLinkError as error:
        mark("failed", None, error.message[:300])
        if error.code == "ghl_send_unknown":   # the text may have gone out: block a blind retry for the window
            with _LOCK:
                _RECENT[str(facts["invoice_id"])] = time.time()
        raise
    sent, tag_warning = {"messageId": delivered["message_id"]}, delivered["tag_warning"]

    marked = mark("sent", sent.get("messageId"), None)
    out = {"ok": True, "send_id": send_id, "status": "sent", "pay_url": pay_url, "sent_message": final_text}
    warnings = [w for w in (tag_warning, None if marked else "The text went out, but the send log could not be updated.") if w]
    if warnings:
        out["warning"] = " ".join(warnings)
    with _LOCK:
        _RECENT[str(facts["invoice_id"])] = time.time()
    return out


_GHL_TO_DELIVERY = {"delivered": "delivered", "read": "delivered", "opened": "delivered",
                    "undelivered": "undelivered", "failed": "failed"}


def _refresh_delivery(session, invoice_id, ghl) -> None:
    """Best-effort: ask GHL what happened to texts still 'sent' (or still 'created' with a GHL
    message id, i.e. the mark call was lost). Never raises."""
    if ghl is None or not getattr(ghl, "configured", False):
        return
    try:
        rows = daycare_supabase.billing_send_rows(session, invoice_id, ("created", "sent"))
    except daycare_supabase.DaycareError:
        return
    now = time.time()
    for row in rows:
        mid, sid = row.get("ghl_message_id"), row.get("id")
        if not (mid and sid) or now - _REFRESHED.get(str(sid), 0) < 10:
            continue
        _REFRESHED[str(sid)] = now
        try:
            data = ghl.get(f"/conversations/messages/{mid}")
            msg = data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), dict) else data
            status = _GHL_TO_DELIVERY.get(str((msg or {}).get("status") or "").lower())
            if status:
                daycare_supabase.billing_rpc(session, "billing_set_link_delivery",
                                             {"p_id": sid, "p_status": status})
        except Exception:  # noqa: BLE001 — a status lookup must never break the timeline
            continue


def timeline(session, invoice_id, ghl) -> dict:
    inv_id = daycare_supabase.require_uuid(invoice_id, "invoice_id")
    _refresh_delivery(session, inv_id, ghl)
    result = daycare_supabase.billing_rpc(session, "billing_invoice_timeline",
                                          {"p_invoice": inv_id}, write=False)
    data = result if isinstance(result, dict) else (_rpc_row(result) or {})
    if "billing_invoice_timeline" in data and isinstance(data["billing_invoice_timeline"], dict):
        data = data["billing_invoice_timeline"]      # PostgREST wraps a scalar jsonb return
    if "reminders" not in data:                       # overdue reminders: kind/status/sent_at/amount_cents/error
        data = {**data, "reminders": daycare_supabase.billing_reminder_rows(session, inv_id)}
    return {"ok": True, **data}


def legacy_text(session, body, ghl) -> dict:
    """Old 'Text invoice' button, fixed: right center name, remaining balance (not the full
    amount), child-named GHL contact, and a link only if a Stripe invoice for that exact balance
    is open. Owner-initiated; one text."""
    facts = _facts_or_refuse(session, body.get("invoice_id"))
    phone = (facts["guardian"].get("phone") or "").strip()
    if not phone:
        return {"ok": False, "detail": "This family has no phone number on file."}
    link = ""
    try:
        invoice = stripe_io.find_invoice(str(facts["invoice_id"]), stripe_io.key_for_location(facts["location_id"]))
        if (invoice and invoice.get("status") == "open"
                and int(invoice.get("amount_due") or 0) == facts["balance_cents"]):
            link = invoice.get("hosted_invoice_url") or ""
    except stripe_io.StripeError:
        link = ""   # a missing link must not block the text
    custom = str(body.get("message") or "").strip()
    if custom:
        message = custom + (("\n\nPay here: " + link) if link else "")
    else:
        message, _ = compose_text(facts)
        message = message.replace(" Pay securely here: " + PLACEHOLDER, (" Pay securely here: " + link) if link else "")
    child = facts.get("child") or {}
    contact_id = daycare_ghl.ensure_family_contact(
        ghl, phone=phone, child_first=child.get("first_name", ""), child_last=child.get("last_name", ""),
        parent_name=facts["guardian"].get("name", ""), email=facts["guardian"].get("email"))
    if not contact_id:
        return {"ok": False, "detail": "Could not create a GHL contact for this family."}
    tag_warning = daycare_ghl.add_family_tags(ghl, contact_id, facts["location_id"])
    result = daycare_ghl.send_sms(ghl, contact_id=contact_id, message=message)
    if tag_warning and isinstance(result, dict):
        result["warning"] = tag_warning
    return result
