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
import logging
import os
import time
from datetime import date, datetime, timezone
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


def _env_key(name: str) -> str:
    key = os.environ.get(name, "")
    if not key:
        try:
            key = daycare_supabase._read_env().get(name, "") or ""
        except Exception:  # noqa: BLE001
            key = ""
    return key.strip()


def _secret_key() -> str:
    return _env_key("STRIPE_SECRET_KEY")


# The QA Sandbox center is the ONLY place Stripe test mode is allowed (billing P0 contract).
QA_LOCATION_ID = "99999999-9999-9999-9999-999999999999"
_TEST_PREFIXES = ("sk_test_", "rk_test_")
_log = logging.getLogger("stripe_io")


def is_test_key(key: str) -> bool:
    return str(key or "").startswith(_TEST_PREFIXES)


def key_for_location(location_id) -> str:
    """The Stripe key for one daycare center. Fail closed: a missing key, a test key in the live
    slot, or a live key in the test slot raises — it never falls back to the other mode."""
    if str(location_id or "").strip().lower() == QA_LOCATION_ID:
        key = _env_key("STRIPE_SECRET_KEY__DAYCARE_TEST")
        if not key:
            raise StripeError(503, "The Stripe test key is not set for the QA Sandbox", "not_configured")
        if not is_test_key(key):
            raise StripeError(503, "The QA Sandbox Stripe key is not a test key, so it was refused", "key_mismatch")
        return key
    key = _secret_key()
    if not key:
        raise StripeError(503, "Stripe is not configured", "not_configured")
    if is_test_key(key):
        raise StripeError(503, "The live Stripe key is a test key, so it was refused", "key_mismatch")
    return key


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


def _req(method: str, path: str, params: dict | None = None,
         key: str | None = None) -> dict:
    # `key` lets another business unit (the agency) reuse this transport with
    # its OWN Stripe account instead of the daycare's. Default is unchanged.
    key = (key or "").strip() or _secret_key()
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


def _find_customer(guardian_id: str, key: str | None = None) -> str | None:
    try:
        result = _req("GET", "/customers/search", {
            "query": f"metadata['daycare_guardian_id']:'{guardian_id}'",
            "limit": 1,
        }, **_kw(key))
    except StripeError:
        return None
    rows = result.get("data") or []
    return rows[0]["id"] if rows else None


def _kw(key: str | None) -> dict:
    """Pass `key=` to _req only when a per-center key was chosen (default callers unchanged)."""
    return {"key": key} if key else {}


def _ensure_customer(guardian_id: str, name: str, email: str | None, key: str | None = None) -> str:
    existing = _find_customer(guardian_id, key)
    if existing:
        return existing
    payload: dict = {"name": name or "Family", "metadata": {"daycare_guardian_id": guardian_id}}
    real = _real_email(email)
    if real:
        payload["email"] = real
    created = _req("POST", "/customers", payload, **_kw(key))
    return created["id"]


def find_invoice(daycare_invoice_id: str, key: str | None = None) -> dict | None:
    """Return the Stripe invoice previously created for a daycare invoice, if any."""
    try:
        result = _req("GET", "/invoices/search", {
            "query": f"metadata['daycare_invoice_id']:'{daycare_invoice_id}'",
            "limit": 1,
        }, **_kw(key))
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
    The key follows ctx.location_id (QA Sandbox -> test key, every other center -> live key).
    """
    location_id = ctx.get("location_id")
    try:
        key = key_for_location(location_id) if location_id else None
    except StripeError as error:
        if error.code != "not_configured":
            raise
        return {"ok": False, "configured": False, "detail": error.message}
    if not key and not configured():
        return {"ok": False, "configured": False,
                "detail": "Add STRIPE_SECRET_KEY to daycare.env to send via Stripe."}
    guardian = ctx.get("guardian") or {}
    amount = round(float(ctx.get("amount") or 0) * 100)
    if amount <= 0:
        raise StripeError(400, "Invoice amount must be positive", "validation_error")

    existing = find_invoice(str(ctx.get("invoice_id")), **_kw(key))
    if existing and existing.get("status") in ("open", "paid"):
        return {"ok": True, "reused": True, **_public(existing)}

    customer_id = _ensure_customer(
        str(guardian.get("id") or ""), guardian.get("name") or "Family", guardian.get("email"), key)

    _req("POST", "/invoiceitems", {
        "customer": customer_id,
        "amount": amount,
        "currency": "usd",
        "description": ctx.get("description") or ctx.get("invoice_number") or "Daycare invoice",
    }, **_kw(key))
    invoice = _req("POST", "/invoices", {
        "customer": customer_id,
        "collection_method": "send_invoice",
        "days_until_due": 7,
        "auto_advance": False,
        # Stripe-Version 2024-06-20 EXCLUDES pending items by default -> a $0 invoice. Verified live 2026-09-30.
        "pending_invoice_items_behavior": "include",
        "description": ctx.get("description") or "",
        "metadata": {
            "daycare_invoice_id": str(ctx.get("invoice_id") or ""),
            "daycare_invoice_number": str(ctx.get("invoice_number") or ""),
            "location_id": str(ctx.get("location_id") or ""),
        },
    }, **_kw(key))
    invoice_id = invoice["id"]
    _req("POST", f"/invoices/{invoice_id}/finalize", {}, **_kw(key))
    sent = _req("POST", f"/invoices/{invoice_id}/send", {}, **_kw(key))
    return {"ok": True, "reused": False, **_public(sent)}


def _due_epoch(due_on) -> int | None:
    """Stripe due_date (unix seconds) for a future YYYY-MM-DD, else None (use days_until_due)."""
    try:
        day = date.fromisoformat(str(due_on)[:10])
    except ValueError:
        return None
    stamp = int(datetime(day.year, day.month, day.day, 23, 0, tzinfo=timezone.utc).timestamp())
    return stamp if stamp > time.time() + 3600 else None


def ensure_hosted_invoice(ctx: dict, location_id) -> dict:
    """Get or create a FINALIZED Stripe invoice for the REMAINING balance. Never calls /send,
    so Stripe never emails the family — only the owner's text carries the link.

    ctx: {invoice_id, invoice_number, balance_cents, paid_cents, due_on, description,
          guardian:{id, name, email}, known_stripe_invoice_ids:[...]}
    Reuses the open Stripe invoice when its amount equals the balance; an open one with a
    different amount is voided and replaced (logged). Returns
    {ok, stripe_invoice_id, hosted_url, livemode, amount_cents, reused, voided:[ids]}.
    """
    key = key_for_location(location_id)
    balance = int(ctx.get("balance_cents") or 0)
    if balance <= 0:
        raise StripeError(400, "There is no balance left to pay on this invoice", "validation_error")
    daycare_id = str(ctx.get("invoice_id") or "")
    guardian = ctx.get("guardian") or {}

    # Candidates: ids this app stored (read-your-write, no search lag) + Stripe's metadata search.
    # ponytail: search lags ~1 min; a first call that died between Stripe and our DB could still
    # double-create on an immediate retry. Upgrade: Idempotency-Key on POST /invoices.
    seen: dict[str, dict] = {}
    for known in ctx.get("known_stripe_invoice_ids") or []:
        try:
            row = _req("GET", f"/invoices/{known}", None, key=key)
        except StripeError:
            continue
        seen[row.get("id")] = row
    found = find_invoice(daycare_id, key)
    if found:
        seen.setdefault(found.get("id"), found)
    mine = [r for r in seen.values()
            if (r.get("metadata") or {}).get("daycare_invoice_id") == daycare_id]

    stripe_paid = sum(int(r.get("amount_paid") or 0) for r in mine if r.get("status") == "paid")
    if stripe_paid > int(ctx.get("paid_cents") or 0):
        raise StripeError(409, "Stripe shows a payment that is not recorded on this invoice yet. "
                               "Sync the payment first.", "payment_not_synced")

    voided: list[str] = []
    for row in mine:
        status = row.get("status")
        if status == "open":
            if int(row.get("amount_due") or 0) == balance and row.get("hosted_invoice_url"):
                return {"ok": True, "reused": True, "voided": voided,
                        "stripe_invoice_id": row["id"], "hosted_url": row["hosted_invoice_url"],
                        "livemode": bool(row.get("livemode", not is_test_key(key))),
                        "amount_cents": balance}
            _req("POST", f"/invoices/{row['id']}/void", {}, key=key)
            voided.append(row["id"])
            _log.info("voided stale Stripe invoice %s for %s (due %s, balance now %s)",
                      row["id"], daycare_id, row.get("amount_due"), balance)
        elif status == "draft":
            _req("DELETE", f"/invoices/{row['id']}", None, key=key)

    customer_id = next((r.get("customer") for r in mine if isinstance(r.get("customer"), str)), None) \
        or _ensure_customer(str(guardian.get("id") or ""), guardian.get("name") or "Family",
                            guardian.get("email"), key)
    number = str(ctx.get("invoice_number") or "Daycare invoice")
    params = {
        "customer": customer_id,
        "collection_method": "send_invoice",
        "auto_advance": False,
        "pending_invoice_items_behavior": "exclude",   # only the item attached below
        "description": str(ctx.get("description") or number)[:300],
        "metadata": {
            "daycare_invoice_id": daycare_id,
            "daycare_invoice_number": number,
            "location_id": str(location_id or ""),
        },
    }
    due = _due_epoch(ctx.get("due_on"))
    if due:
        params["due_date"] = due
    else:
        params["days_until_due"] = 7
    invoice = _req("POST", "/invoices", params, key=key)
    try:
        _req("POST", "/invoiceitems", {
            "customer": customer_id, "invoice": invoice["id"], "amount": balance,
            "currency": "usd", "description": f"{number} balance",
        }, key=key)
        final = _req("POST", f"/invoices/{invoice['id']}/finalize", {}, key=key)
    except StripeError:
        try:
            _req("DELETE", f"/invoices/{invoice['id']}", None, key=key)
        except StripeError:
            pass
        raise
    url = final.get("hosted_invoice_url")
    if not url:
        raise StripeError(502, "Stripe did not return a payment link", "no_hosted_url")
    return {"ok": True, "reused": False, "voided": voided, "stripe_invoice_id": final.get("id") or invoice["id"],
            "hosted_url": url, "livemode": bool(final.get("livemode", not is_test_key(key))),
            "amount_cents": balance}


def invoice_status(daycare_invoice_id: str) -> dict:
    if not configured():
        return {"ok": True, "configured": False}
    invoice = find_invoice(str(daycare_invoice_id))
    if not invoice:
        return {"ok": True, "configured": True, "sent": False}
    return {"ok": True, "configured": True, "sent": True, **_public(invoice)}


_HEALTH: dict = {"at": 0.0, "val": None}


def health(max_age: float = 120.0) -> dict:
    """One cheap, cached read (GET /balance) answering 'does the Stripe key work right now?'.
    Never raises, never writes. Shared by System Health, /api/stripe/status and the agency."""
    key = _secret_key()
    if not key:
        return {"configured": False, "ok": False, "detail": "No STRIPE_SECRET_KEY configured"}
    now = time.time()
    if _HEALTH["val"] and now - _HEALTH["at"] < max_age:
        return _HEALTH["val"]
    kind = "_".join(key.split("_")[:2])
    out = {"configured": True, "keyKind": kind, "mode": "live" if "_live" in kind else "test"}
    try:
        bal = _req("GET", "/balance")
        money = lambda rows: round(sum(r.get("amount", 0) for r in rows or []) / 100, 2)
        out.update(ok=True, availableUSD=money(bal.get("available")), pendingUSD=money(bal.get("pending")))
    except StripeError as e:
        out.update(ok=False, detail=e.message, status=e.status)
    _HEALTH.update(at=now, val=out)
    return out

