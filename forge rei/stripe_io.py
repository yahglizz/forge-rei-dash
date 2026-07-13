#!/usr/bin/env python3
"""Stripe REST bridge for daycare invoicing — stdlib only (no pip on the box).

Sends a daycare invoice through Stripe so families get a real hosted invoice /
payment page, then lets the daycare sync the payment back into the Supabase ledger
via the existing ``record_invoice_payment`` RPC (``provider='stripe'``).

The Stripe secret key lives in ``forge-daycare/config/daycare.env`` as
``STRIPE_SECRET_KEY`` (use a RESTRICTED key with Invoices + Customers write). When
it is blank the module reports ``configured() == False`` and every call returns a
clean "not configured" result — nothing is charged, no rebuild needed to go live.

Design mirrors ``GHLClient`` (connector.py): urllib + retry, but Stripe wants
form-encoded bodies, so nested params use ``metadata[key]=value`` bracket syntax.
No secret is ever returned to the browser.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import daycare_supabase  # reuse the same daycare.env loader

_API_BASE = "https://api.stripe.com/v1"
_TIMEOUT = 30
_RETRIES = 2


class StripeError(Exception):
    def __init__(self, status: int, message: str, code: str = "stripe_error"):
        super().__init__(message)
        self.status = int(status)
        self.message = message
        self.code = code


def _secret_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        try:
            key = daycare_supabase._read_env().get("STRIPE_SECRET_KEY", "") or ""
        except Exception:  # noqa: BLE001
            key = ""
    return key.strip()


def configured() -> bool:
    return bool(_secret_key())


def _encode(params: dict) -> bytes:
    """Form-encode with Stripe's bracket syntax for nested dicts."""
    flat: list[tuple[str, str]] = []

    def add(prefix: str, value) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for k, v in value.items():
                add(f"{prefix}[{k}]", v)
        elif isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                add(f"{prefix}[{i}]", v)
        elif isinstance(value, bool):
            flat.append((prefix, "true" if value else "false"))
        else:
            flat.append((prefix, str(value)))

    for key, value in params.items():
        add(key, value)
    return urllib.parse.urlencode(flat).encode("utf-8")


def _req(method: str, path: str, params: dict | None = None) -> dict:
    key = _secret_key()
    if not key:
        raise StripeError(503, "Stripe is not configured", "not_configured")
    url = f"{_API_BASE}{path}"
    data = _encode(params or {}) if method in ("POST",) else None
    if method == "GET" and params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Stripe-Version": "2024-06-20",
    }
    last_error: Exception | None = None
    for attempt in range(_RETRIES + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except urllib.error.HTTPError as error:
            body = b""
            try:
                body = error.read()
            except Exception:  # noqa: BLE001
                pass
            if error.code in (429, 500, 502, 503, 504) and attempt < _RETRIES:
                time.sleep(0.5 * (attempt + 1))
                last_error = error
                continue
            detail = "Stripe request failed"
            try:
                payload = json.loads(body.decode("utf-8"))
                detail = payload.get("error", {}).get("message", detail)
            except Exception:  # noqa: BLE001
                pass
            raise StripeError(error.code, detail, "stripe_http_error") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
            if attempt < _RETRIES:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise StripeError(502, "Stripe is temporarily unavailable", "upstream_unavailable") from None
    raise StripeError(502, "Stripe is temporarily unavailable", "upstream_unavailable") from last_error


def _real_email(email: str | None) -> str | None:
    """Only pass a genuine deliverable email to Stripe (skip synthetic login emails)."""
    if not email or "@" not in email:
        return None
    if email.lower().endswith("@login.blessings.app"):
        return None
    return email


def _find_customer(guardian_id: str) -> str | None:
    try:
        result = _req("GET", "/customers/search", {
            "query": f"metadata['daycare_guardian_id']:'{guardian_id}'",
            "limit": 1,
        })
    except StripeError:
        return None
    rows = result.get("data") or []
    return rows[0]["id"] if rows else None


def _ensure_customer(guardian_id: str, name: str, email: str | None) -> str:
    existing = _find_customer(guardian_id)
    if existing:
        return existing
    payload: dict = {"name": name or "Family", "metadata": {"daycare_guardian_id": guardian_id}}
    real = _real_email(email)
    if real:
        payload["email"] = real
    created = _req("POST", "/customers", payload)
    return created["id"]


def find_invoice(daycare_invoice_id: str) -> dict | None:
    """Return the Stripe invoice previously created for a daycare invoice, if any."""
    try:
        result = _req("GET", "/invoices/search", {
            "query": f"metadata['daycare_invoice_id']:'{daycare_invoice_id}'",
            "limit": 1,
        })
    except StripeError:
        return None
    rows = result.get("data") or []
    return rows[0] if rows else None


def _public(invoice: dict) -> dict:
    return {
        "stripeInvoiceId": invoice.get("id"),
        "status": invoice.get("status"),
        "hostedInvoiceUrl": invoice.get("hosted_invoice_url"),
        "invoicePdf": invoice.get("invoice_pdf"),
        "amountDue": (invoice.get("amount_due") or 0) / 100.0,
        "amountPaid": (invoice.get("amount_paid") or 0) / 100.0,
        "paid": bool(invoice.get("paid")),
        "number": invoice.get("number"),
    }


def send_invoice(ctx: dict) -> dict:
    """Create (idempotently) + finalize + send a Stripe invoice for a daycare invoice.

    ctx: {invoice_id, invoice_number, amount, description, due_on, location_id,
          guardian:{id, name, email}}
    """
    if not configured():
        return {"ok": False, "configured": False,
                "detail": "Add STRIPE_SECRET_KEY to daycare.env to send via Stripe."}
    guardian = ctx.get("guardian") or {}
    amount = round(float(ctx.get("amount") or 0) * 100)
    if amount <= 0:
        raise StripeError(400, "Invoice amount must be positive", "validation_error")

    existing = find_invoice(str(ctx.get("invoice_id")))
    if existing and existing.get("status") in ("open", "paid"):
        return {"ok": True, "reused": True, **_public(existing)}

    customer_id = _ensure_customer(
        str(guardian.get("id") or ""), guardian.get("name") or "Family", guardian.get("email"))

    _req("POST", "/invoiceitems", {
        "customer": customer_id,
        "amount": amount,
        "currency": "usd",
        "description": ctx.get("description") or ctx.get("invoice_number") or "Daycare invoice",
    })
    invoice = _req("POST", "/invoices", {
        "customer": customer_id,
        "collection_method": "send_invoice",
        "days_until_due": 7,
        "auto_advance": False,
        "description": ctx.get("description") or "",
        "metadata": {
            "daycare_invoice_id": str(ctx.get("invoice_id") or ""),
            "daycare_invoice_number": str(ctx.get("invoice_number") or ""),
            "location_id": str(ctx.get("location_id") or ""),
        },
    })
    invoice_id = invoice["id"]
    _req("POST", f"/invoices/{invoice_id}/finalize", {})
    sent = _req("POST", f"/invoices/{invoice_id}/send", {})
    return {"ok": True, "reused": False, **_public(sent)}


def invoice_status(daycare_invoice_id: str) -> dict:
    if not configured():
        return {"ok": True, "configured": False}
    invoice = find_invoice(str(daycare_invoice_id))
    if not invoice:
        return {"ok": True, "configured": True, "sent": False}
    return {"ok": True, "configured": True, "sent": True, **_public(invoice)}
