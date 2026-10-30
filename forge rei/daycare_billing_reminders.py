#!/usr/bin/env python3
"""Overdue payment reminders (billing P2 slice, spec: daycare app docs/billing-p2/OVERDUE-SLICE.md).

Computed, not scheduled: each tick asks the database which invoices are owed a reminder today
(`billing_reminders_owed`), texts the parent through the SAME send path as the pay-link
(`daycare_billing_link.deliver_text`: child-named contact -> additive `daycare family` tag -> SMS),
and logs every step through `billing_reminder_*` RPCs. Nothing is pre-queued.

Safety, in order of weight:
- Per-center switch `billing_settings.reminder_mode` (off | dry_run | live). Anything but dry_run/live
  = nothing happens. A read failure counts as off.
- 9:00 AM - 8:00 PM ET only (`in_send_window`); the box loop runs only with FORGE_MARCUS=1.
- dry_run stores the message and sends nothing. A pending payment skips the text that day.
- No pay link on file = no text; the invoice is flagged. A Mother's Touch (1923) is never texted.
- Run-now (`run_now`) is QA Sandbox only; the location check comes before anything else.
- No late-fee wording, no STOP line, parent first name from the app database (never the GHL contact).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import daycare_billing_link as bl
import daycare_ghl
import daycare_supabase

_ET = ZoneInfo("America/New_York")
_log = logging.getLogger("daycare_billing_reminders")

QA_LOCATION_ID = daycare_supabase.QA_SANDBOX_LOCATION_ID
PAY_BASE = "https://www.atouchofblessing.com/pay"
PHONE_ATOB = "(215) 236-5439"
SEND_FROM_HOUR = 9       # 9:00 AM ET, inclusive
SEND_UNTIL_HOUR = 20     # 8:00 PM ET, exclusive
INTERVAL = 3600          # box loop: hourly
MODES_THAT_ACT = ("dry_run", "live")

# The four parent texts, word for word from the spec. {Whose}/{whose} = "Maya's" or, when no single
# child is known, "Your"/"your".
TEMPLATES = {
    "upcoming": ("Hi {parent}, this is {brand}. {Whose} balance of {amount} is due {date}. "
                 "You can pay here: {link} Thank you!"),
    "due_today": ("Hi {parent}, this is {brand}. {Whose} balance of {amount} is due today. "
                  "You can pay here: {link} Thank you!"),
    "overdue_1": ("Hi {parent}, this is {brand}. We don't show {whose} balance of {amount} as paid yet. "
                  "It was due {date}. You can pay here: {link} "
                  "If you already paid, thank you, and you can ignore this."),
    "overdue_3": ("Hi {parent}, this is {brand}. {Whose} balance of {amount} from {date} is still open. "
                  "You can pay here: {link} If you have any questions, please call us at {phone}. Thank you."),
}

_TICK_LOCK = threading.Lock()


def in_send_window(now: datetime) -> bool:
    return SEND_FROM_HOUR <= now.astimezone(_ET).hour < SEND_UNTIL_HOUR


def _is_amt(location_id) -> bool:
    return str(location_id or "").startswith(daycare_ghl.AMT_LOCATION_PREFIX)


def pay_link(token: str) -> str:
    return f"{PAY_BASE}/{token}"


def compose(kind: str, *, parent: str, child: str, brand: str, amount_cents: int, due_on, link: str,
            phone: str = PHONE_ATOB) -> str:
    """The reminder text. Pure. Raises KeyError for an unknown kind."""
    parent = (parent or "").strip()[:30]
    parent = parent if len(parent) > 1 else "there"
    child = (child or "").strip()[:30]
    whose = f"{child}'s" if len(child) > 1 else "your"
    try:
        day = datetime.strptime(str(due_on)[:10], "%Y-%m-%d").date()
        date_text = f"{day:%b} {day.day}"
    except ValueError:
        date_text = "the due date"
    return TEMPLATES[kind].format(
        parent=parent, brand=brand, amount="$" + bl._money(amount_cents), date=date_text, link=link,
        phone=phone, whose=whose, Whose=whose[:1].upper() + whose[1:])


def _bump(bucket: dict, key: str) -> None:
    bucket[key] = bucket.get(key, 0) + 1


def _rpc(session, name, body, *, write=True):
    return daycare_supabase.billing_rpc(session, name, body, write=write)


def _first(result):
    return result[0] if isinstance(result, list) and result else result


def _claim_id(result):
    value = _first(result)
    if isinstance(value, dict):
        value = value.get("billing_reminder_claim") or value.get("id")
    return value or None


def _record(session, rid, status, message_id=None, error=None) -> None:
    try:
        _rpc(session, "billing_reminder_result", {
            "p_id": rid, "p_status": status, "p_ghl_message_id": message_id, "p_error": error})
    except Exception:  # noqa: BLE001 — the text already went out (or was refused); never crash the tick
        _log.exception("billing_reminder_result failed for %s", rid)


def _refresh_delivery(session, rows, ghl) -> None:
    """Best-effort: a reminder GHL reports as undelivered/failed gets the carrier note on its row.
    Status stays 'sent' on purpose — flipping it to 'failed' would let the next tick text a dead
    number again. `rows` were read inside the center switch; the GHL calls happen outside it. Never raises."""
    for row in rows:
        try:
            data = ghl.get(f"/conversations/messages/{row['ghl_message_id']}")
            msg = data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), dict) else data
            state = str((msg or {}).get("status") or "").lower()
            if state in ("undelivered", "failed"):
                _record(session, row["id"], "sent", row["ghl_message_id"],
                        "Carrier reported the text as " + state + ".")
        except Exception:  # noqa: BLE001
            continue


def _flag(session, row, facts, out, bucket: str, note: str) -> None:
    """No text for this invoice: count it, flag it, and keep the reason on a failed reminder row
    (so the Timeline shows why). Best effort; never raises."""
    _bump(out["skipped"], bucket)
    out["flagged"].append(str(row["invoice_id"]))
    try:
        rid = _claim_id(_rpc(session, "billing_reminder_claim", {
            "p_invoice": row["invoice_id"], "p_kind": row["kind"], "p_due_on": row["due_on"],
            "p_today": out["as_of"], "p_amount_cents": facts["balance_cents"],
            "p_message": "(no text sent)", "p_link_send_id": row.get("link_send_id")}))
        if rid:
            _record(session, rid, "failed", None, note[:300])
    except Exception:  # noqa: BLE001
        _log.exception("could not flag invoice %s", row.get("invoice_id"))


def _process_row(session, row, mode, ghl, out, facts, pre) -> None:
    """Phase 2 for one owed row, OUTSIDE the center switch. `facts` / `pre` were read in phase 1
    (an Exception in `facts` means that read failed)."""
    kind = row.get("kind")
    if kind == "staff_review":
        if mode != "live":
            _bump(out["skipped"], "dry_run_staff_review")
            return
        _rpc(session, "billing_reminder_staff_review", {"p_invoice": row["invoice_id"], "p_due_on": row["due_on"]})
        out["reviews"] += 1
        return
    if kind not in TEMPLATES:
        _bump(out["skipped"], "unknown_kind")
        return
    if row.get("has_pending_payment"):
        _bump(out["skipped"], "payment_processing")
        return
    if isinstance(facts, Exception):
        raise facts
    if facts.get("status") in ("void", "paid", "draft") or facts["balance_cents"] <= 0:
        _bump(out["skipped"], "closed")
        return
    if facts.get("has_pending_payment"):
        _bump(out["skipped"], "payment_processing")
        return
    if not (row.get("has_link") and row.get("token")):
        _flag(session, row, facts, out, "no_link", "No pay link on file. Send one from the Billing tab first.")
        return

    brand = daycare_ghl._brand_link(facts["location_id"])[0]
    child = "" if facts.get("child_ambiguous") else (facts.get("child") or {}).get("first_name", "")

    def text_with(link):
        return compose(kind, parent=(facts["guardian"].get("first_name") or ""), child=child, brand=brand,
                       amount_cents=facts["balance_cents"], due_on=row["due_on"], link=link)

    # The text and the Stripe page must show the SAME amount. A partial payment lowers the balance but
    # leaves the old Stripe invoice at the old amount, so a stale link is refreshed (live only) first.
    stale = pre["link_amount"] != facts["balance_cents"]   # unknown amount counts as stale
    link_send_id, message, refreshed = row.get("link_send_id"), None, None
    stale_note = None
    if stale and mode == "dry_run":                        # dry_run never touches Stripe or makes a link
        message = text_with(pay_link(row["token"]))
        stale_note = ("Dry run: the saved pay link is stale (it charges a different amount); "
                      "a live run would refresh it first.")
    elif stale:
        # Everything that can say "no" is checked BEFORE the irreversible Stripe step (it voids the old invoice).
        if not (facts["guardian"].get("phone") or "").strip():
            _flag(session, row, facts, out, "no_phone", "No phone number on file.")
            return
        if pre["family_busy"]:                             # this family already got a billing text today
            _bump(out["skipped"], "already_sent_or_family_cap")
            return
        try:                                               # same guard as the owner's Send (race = two invoices)
            release = bl.reserve_link(session, row["invoice_id"], recent=pre["recent_link"])
        except bl.BillingLinkError:
            _bump(out["skipped"], "link_busy")             # a link was just built/sent; the next tick decides
            return
        try:
            refreshed = bl.create_link(session, facts, text_with(bl.PLACEHOLDER))
        except Exception as error:  # noqa: BLE001 — no text, flag it, keep going with the rest of the tick
            detail = getattr(error, "message", None) or "Stripe or the database refused the request."
            _log.warning("pay-link refresh failed for %s: %s", row.get("invoice_id"), type(error).__name__)
            _flag(session, row, facts, out, "link_refresh_failed",
                  "Could not refresh the pay link, so no text was sent: " + str(detail))
            return
        finally:
            release()
        message, link_send_id = refreshed["final_text"], refreshed["send_id"]
    else:
        message = text_with(pay_link(row["token"]))

    rid = _claim_id(_rpc(session, "billing_reminder_claim", {
        "p_invoice": row["invoice_id"], "p_kind": kind, "p_due_on": row["due_on"], "p_today": out["as_of"],
        "p_amount_cents": facts["balance_cents"], "p_message": message,
        "p_link_send_id": link_send_id}))
    if not rid:                    # already sent, or this family already got a billing text today
        _bump(out["skipped"], "already_sent_or_family_cap")
        if refreshed:
            bl.mark_link(session, refreshed["send_id"], "failed", None, "Reminder not sent (already sent or family cap).")
        return
    if mode == "dry_run":
        _record(session, rid, "dry_run", None, stale_note)
        out["dry_run"] += 1
        return
    if not (facts["guardian"].get("phone") or "").strip():
        _record(session, rid, "failed", None, "No phone number on file.")
        if refreshed:
            bl.mark_link(session, refreshed["send_id"], "failed", None, "No phone number on file.")
        out["failed"] += 1
        return
    try:
        delivered = bl.deliver_text(ghl, facts, message, facts["location_id"])
    except bl.BillingLinkError as error:
        if error.code == "ghl_send_unknown":
            # May have gone out: keep the row 'sent' (with the note) so no later tick can text twice.
            _record(session, rid, "sent", None, error.message[:300])
            out["warnings"].append(error.message)
            if refreshed:
                bl.arm_recent(row["invoice_id"])
        else:
            _record(session, rid, "failed", None, error.message[:300])
        if refreshed:
            bl.mark_link(session, refreshed["send_id"], "failed", None, error.message[:300])
        out["failed"] += 1
        return
    _record(session, rid, "sent", delivered["message_id"], None)
    if refreshed:
        bl.mark_link(session, refreshed["send_id"], "sent", delivered["message_id"], None)
        bl.arm_recent(row["invoice_id"])
    out["sent"] += 1
    if delivered.get("tag_warning"):
        out["warnings"].append(delivered["tag_warning"])


def _plan(session, location_id, as_of: date, mode: str, out: dict) -> dict:
    """PHASE 1 — every read that depends on the session's active center (RLS my_location()):
    the delivery-check candidates and each owed invoice's facts + saved-link amount. Runs inside
    at_location and does no network call to GHL or Stripe, so the center switch (a process-wide lock
    on a profile shared with the dashboard) is held for a few quick reads only."""
    plan = {"unchecked": [], "rows": []}
    if mode == "live":
        try:
            plan["unchecked"] = daycare_supabase.billing_reminder_unchecked(session, location_id)
        except daycare_supabase.DaycareError:
            pass
    owed = _rpc(session, "billing_reminders_owed",
                {"p_location": str(location_id), "p_today": as_of.isoformat()}, write=False)
    for row in (owed if isinstance(owed, list) else []):
        facts, pre = None, {"link_amount": None, "recent_link": False, "family_busy": False}
        needs_facts = (row.get("kind") in TEMPLATES and not row.get("has_pending_payment"))
        if needs_facts:
            try:
                facts = daycare_supabase.billing_invoice_facts(session, row["invoice_id"])
                if row.get("has_link") and row.get("token"):
                    pre["link_amount"] = daycare_supabase.billing_link_amount(session, row.get("link_send_id"))
                    if mode == "live" and pre["link_amount"] != facts["balance_cents"]:
                        # a Stripe refresh is coming: read what must veto it BEFORE any Stripe call
                        pre["recent_link"] = daycare_supabase.billing_recent_send(
                            session, row["invoice_id"], bl.RESEND_WINDOW)
                        pre["family_busy"] = daycare_supabase.billing_reminder_family_busy(
                            session, row.get("guardian_id"), as_of.isoformat())
            except Exception as error:  # noqa: BLE001 — surfaces as that one row's error in phase 2
                facts = error
        plan["rows"].append((row, facts, pre))
    return plan


def run_location(session, location_id, as_of: date, ghl, *, now: datetime | None = None) -> dict:
    """One tick for ONE center. Stands in the center only for the phase-1 reads; Stripe, GHL and the
    claim/result writes (membership-checked RPCs that name the center) run outside the switch."""
    now = now or datetime.now(_ET)
    out = {"ok": True, "location_id": str(location_id), "as_of": as_of.isoformat(), "mode": None,
           "sent": 0, "dry_run": 0, "failed": 0, "reviews": 0, "skipped": {}, "flagged": [], "warnings": []}
    if not in_send_window(now):
        out["skipped_window"] = True
        return out
    if _is_amt(location_id):
        out["mode"] = "off"
        out["note"] = "A Mother's Touch reminders are off."
        return out
    if not _TICK_LOCK.acquire(blocking=False):
        return {**out, "ok": False, "detail": "A reminder run is already in progress."}
    try:
        with daycare_supabase.at_location(session, location_id):
            mode = daycare_supabase.billing_reminder_mode(session, location_id)
            out["mode"] = mode
            if mode not in MODES_THAT_ACT:
                return out            # off / unreadable: no flip, no owed query, nothing
            if mode == "live" and (ghl is None or not getattr(ghl, "configured", False)):
                return {**out, "ok": False, "detail": "GoHighLevel is not connected, so no reminder was sent."}
            # Flip due -> overdue for THIS center as of as_of, before computing what is owed. p_location scopes
            # it (and the database still requires the switch on, never 4444, caller manages), so a QA run-now
            # with a simulated date cannot move another center.
            out["marked_overdue"] = _first(_rpc(session, "billing_mark_overdue", {
                "p_today": as_of.isoformat(), "p_location": str(location_id)}))
            plan = _plan(session, location_id, as_of, mode, out)
        if mode == "live":
            _refresh_delivery(session, plan["unchecked"], ghl)
        for row, facts, pre in plan["rows"]:
            try:
                _process_row(session, row, mode, ghl, out, facts, pre)
            except Exception as error:  # noqa: BLE001 — one bad invoice never stops the rest
                _log.exception("reminder row failed (invoice %s)", row.get("invoice_id"))
                out["failed"] += 1
                _bump(out["skipped"], "row_error")
        return out
    finally:
        _TICK_LOCK.release()


def run_now(session, body, ghl, *, now: datetime | None = None) -> dict:
    """POST /api/daycare/billing/reminders/run {location_id, as_of}. QA Sandbox ONLY.
    The location is checked first, so a real center is refused whatever as_of says."""
    location_id = str((body or {}).get("location_id") or "").strip().lower()
    if location_id != QA_LOCATION_ID:
        raise bl.BillingLinkError(403, "Reminder test runs are limited to the QA Sandbox.", "qa_only")
    now = now or datetime.now(_ET)
    raw = (body or {}).get("as_of")
    if raw in (None, ""):
        as_of = now.astimezone(_ET).date()
    else:
        try:
            as_of = date.fromisoformat(str(raw))
        except ValueError:
            raise bl.BillingLinkError(400, "as_of must be a date like 2026-11-03.", "validation_error") from None
        if abs((as_of - now.astimezone(_ET).date()).days) > 400:
            raise bl.BillingLinkError(400, "as_of is too far from today.", "validation_error")
    return run_location(session, QA_LOCATION_ID, as_of, ghl, now=now)


def run_all(session_fn, ghl, *, now: datetime | None = None) -> dict:
    """The box loop's tick: every center the lane admin can stand in, plus the QA Sandbox.
    Centers whose reminder_mode is off do nothing."""
    now = now or datetime.now(_ET)
    if not in_send_window(now):
        return {"ok": True, "skipped_window": True}
    session = session_fn()
    if session is None:
        return {"ok": False, "error": "no daycare session"}
    ids = [str(row.get("id")) for row in (daycare_supabase.list_locations(session).get("locations") or [])]
    if QA_LOCATION_ID not in ids:
        ids.append(QA_LOCATION_ID)
    today = now.astimezone(_ET).date()
    results, errors = [], 0
    for loc in ids:
        if _is_amt(loc):
            continue
        try:
            results.append(run_location(session, loc, today, ghl, now=now))
        except Exception as error:  # noqa: BLE001 — a center we cannot stand in (or a failure) never stops the others
            errors += 1
            _log.warning("reminder tick skipped %s: %s", loc, type(error).__name__)
    return {"ok": True, "results": results, "errors": errors}


def run_forever(session_fn, ghl, interval: int = INTERVAL):
    """Box loop (thread `daycare_billing_reminders`, FORGE_MARCUS=1 only): hourly, in-window only."""
    import forge_heartbeat
    import forge_ops
    while True:
        err = None
        try:
            if not forge_ops.paused():
                summary = run_all(session_fn, ghl)
                err = summary.get("error") or (f"{summary['errors']} center(s) skipped" if summary.get("errors") else None)
        except Exception as error:  # noqa: BLE001 — one failure never kills the loop
            err = type(error).__name__
        forge_heartbeat.beat("daycare_billing_reminders", interval, "Billing · Overdue reminders", error=err)
        time.sleep(interval)
