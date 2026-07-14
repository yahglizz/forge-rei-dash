"""Daycare — Family Blast engine (SMS to parents' phones via GoHighLevel).

The daycare's in-app messaging (``daycare_comms`` → Supabase threads/announcements)
only reaches families who open the parent app. This engine reaches their PHONE:
a one-to-many SMS blast through the daycare's own GHL sub-account (``DAYCARE_GHL``),
fully separate from the wholesale + agency GHL accounts.

Autonomy (CLAUDE.md rule 2): a blast is an OUTWARD action, so it is operator-gated
end-to-end. ``create_blast`` only ever QUEUES — it renders every recipient's exact
final text so the owner previews the real thing. Nothing leaves the box until
``send_blast`` is called, which the console's confirm button is the approval gate for.
Nothing in here runs on a loop or sends on its own.

Decoupled like ``buyers.py`` / ``toolkit_blast.py``: the connector assembles the
audience (it owns the Supabase session) and registers the wire-send transport, so
this module imports neither the connector nor daycare_supabase.

Store: ``marcus_state/daycare_blast.json``. Stdlib only.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

import forge_atomic

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_blast.json"
_LOCK = threading.RLock()

MAX_BLASTS = 200          # rolling history kept on disk
MAX_SMS_CHARS = 480       # ~3 segments; longer gets rejected at create time
CAP_ENV = "FORGE_DAYCARE_BLAST_CAP"
DEFAULT_CAP = 200         # max recipients in a single blast (typo/foot-gun guard)

# The connector injects the real GHL send here. With no transport registered every
# send is a harmless stub that only reports what WOULD have gone out.
_TRANSPORT = None


def register_transport(fn):
    """Connector injects the wire-send: fn(recipient_dict, text) -> {ok|skipped|note}."""
    global _TRANSPORT
    _TRANSPORT = fn


def cap() -> int:
    try:
        return max(1, int(os.environ.get(CAP_ENV, "") or DEFAULT_CAP))
    except (TypeError, ValueError):
        return DEFAULT_CAP


def _now() -> int:
    return int(time.time() * 1000)


def _load() -> dict:
    try:
        import json
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001 — a missing/corrupt store is an empty store
        return {}


def _save(data: dict) -> None:
    forge_atomic.atomic_write_json(STATE, data)


def _digits(phone) -> str:
    """Normalize to a comparable key so one guardian with two kids isn't texted twice."""
    return re.sub(r"[^0-9]", "", str(phone or ""))[-10:]


def _slug(value) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip()).strip("-")[:50] or "blast"


# ---------------------------------------------------------------- audience


def build_audience(children, *, classroom_id=None, active_only=True):
    """Collapse child rows into a de-duplicated guardian list (one text per phone).

    ``children`` is the row shape ``daycare_supabase.get_children`` already returns
    (each child carrying an embedded ``guardian`` profile with ``phone``). A guardian
    with three kids enrolled gets ONE entry, with all three children named — so a
    merge field like {child} still reads correctly.
    """
    out: dict[str, dict] = {}
    no_phone: list[dict] = []
    for child in (children or []):
        if active_only and child.get("active") is False:
            continue
        if classroom_id and str(child.get("classroom_id") or "") != str(classroom_id):
            continue
        guardian = child.get("guardian") or child.get("guardian_profile") or {}
        child_name = (child.get("first_name") or "").strip()
        name = (guardian.get("display_name") or " ".join(
            v for v in (guardian.get("first_name"), guardian.get("last_name")) if v)).strip()
        key = _digits(guardian.get("phone"))
        if not key or len(key) < 10:
            no_phone.append({"guardianName": name or "Family", "childName": child_name})
            continue
        entry = out.setdefault(key, {
            "key": key,
            "guardianId": guardian.get("id"),
            "name": name or "Family",
            "firstName": (guardian.get("first_name") or name.split(" ")[0] or "there").strip(),
            "phone": guardian.get("phone"),
            "email": guardian.get("auth_email"),
            "children": [],
            "classroomIds": [],
        })
        if child_name and child_name not in entry["children"]:
            entry["children"].append(child_name)
        room = child.get("classroom_id")
        if room and room not in entry["classroomIds"]:
            entry["classroomIds"].append(room)
    return {"recipients": sorted(out.values(), key=lambda r: r["name"].lower()),
            "missingPhone": no_phone}


# ---------------------------------------------------------------- opt-outs


def _optouts(data) -> dict:
    return data.setdefault("_optouts", {})


def _optout_key(location_id, phone) -> str:
    """Opt-outs are PER CENTER. A family telling A Touch of Blessings to stop texting
    must not silently mute A Mother's Touch — they can be different businesses, and one
    center's consent is not another's. Scoping the key keeps the wall up here too."""
    return "%s|%s" % (str(location_id or ""), _digits(phone))


def list_optouts(location_id=None) -> list[dict]:
    with _LOCK:
        rows = [r for r in _optouts(_load()).values()
                if location_id is None or r.get("locationId") == location_id]
        return sorted(rows, key=lambda r: r.get("at") or 0, reverse=True)


def set_optout(phone, *, location_id=None, opted_out=True, name="") -> dict:
    """Owner marks a family as do-not-text AT THIS CENTER. Skipped by future blasts there."""
    digits = _digits(phone)
    if not digits:
        return {"ok": False, "detail": "A phone number is required."}
    key = _optout_key(location_id, phone)
    with _LOCK:
        data = _load()
        outs = _optouts(data)
        if opted_out:
            outs[key] = {"key": digits, "phone": phone, "name": name,
                         "locationId": location_id, "at": _now()}
        else:
            outs.pop(key, None)
        _save(data)
        return {"ok": True, "optedOut": bool(opted_out)}


# ---------------------------------------------------------------- rendering


_TOKEN_RE = re.compile(r"\{(first_name|name|child|children|center)\}")


def render(template, recipient, center_name="A Touch of Blessings") -> str:
    """Fill merge tokens for ONE recipient. Unknown tokens are left untouched."""
    kids = recipient.get("children") or []
    if len(kids) == 1:
        child = kids[0]
    elif len(kids) == 2:
        child = "%s and %s" % (kids[0], kids[1])
    elif kids:
        child = "%s, and %s" % (", ".join(kids[:-1]), kids[-1])
    else:
        child = "your little one"
    values = {
        "first_name": recipient.get("firstName") or "there",
        "name": recipient.get("name") or "Family",
        "child": child,
        "children": child,
        "center": center_name,
    }
    return _TOKEN_RE.sub(lambda m: values[m.group(1)], str(template or "")).strip()


def preview(template, recipients, center_name="A Touch of Blessings") -> list[dict]:
    """Exactly what each family would receive — rendered, not summarized."""
    return [{"name": r.get("name"), "phone": r.get("phone"),
             "text": render(template, r, center_name)} for r in (recipients or [])]


# ---------------------------------------------------------------- blasts


def create_blast(*, title, template, recipients, audience_label="",
                 center_name="A Touch of Blessings", location_id=None) -> dict:
    """QUEUE a blast for ONE center. Renders every family's final text; sends nothing."""
    body = (template or "").strip()
    if not body:
        return {"error": "Write the message first."}
    if len(body) > MAX_SMS_CHARS:
        return {"error": "Message is %d characters — keep it under %d."
                         % (len(body), MAX_SMS_CHARS)}
    people = list(recipients or [])
    if not people:
        return {"error": "No families with a phone number in this audience."}

    with _LOCK:
        data = _load()
        outs = _optouts(data)
        rows, skipped_optout = [], 0
        for person in people:
            key = _digits(person.get("phone"))
            if _optout_key(location_id, person.get("phone")) in outs:
                skipped_optout += 1
                continue
            rows.append({
                "key": key,
                "guardianId": person.get("guardianId"),
                "name": person.get("name") or "Family",
                "phone": person.get("phone"),
                "email": person.get("email"),
                "children": person.get("children") or [],
                "text": render(body, person, center_name),
                "status": "queued", "sentAt": None, "note": "",
            })
        if not rows:
            return {"error": "Every family in this audience is opted out."}
        if len(rows) > cap():
            return {"error": "%d recipients exceeds the %d-per-blast cap. Narrow the "
                             "audience or raise %s." % (len(rows), cap(), CAP_ENV)}

        base = "dcblast-" + _slug(title)
        bid, n = base, 2
        while bid in data:
            bid = "%s-%d" % (base, n)
            n += 1
        seq = max([r.get("seq", 0) for r in data.values()
                   if isinstance(r, dict) and r.get("seq")] or [0]) + 1
        record = {
            "id": bid, "seq": seq,
            "locationId": location_id,          # which center this blast belongs to
            "centerName": center_name,
            "title": (title or "Family blast").strip(),
            "audience": audience_label or "All families",
            "template": body,
            "createdAt": _now(), "sentAt": None,
            "status": "queued",
            "skippedOptOut": skipped_optout,
            "recipients": rows,
        }
        data[bid] = record
        blasts = [r for r in data.values() if isinstance(r, dict) and r.get("id")]
        if len(blasts) > MAX_BLASTS:
            keep = sorted(blasts, key=lambda r: -(r.get("createdAt") or 0))[:MAX_BLASTS]
            preserved = data.get("_optouts", {})
            data = {r["id"]: r for r in keep}
            data["_optouts"] = preserved
        _save(data)
        return record


def get_blast(blast_id):
    record = _load().get(blast_id)
    return record if isinstance(record, dict) and record.get("id") else None


def list_blasts() -> list[dict]:
    rows = [r for r in _load().values() if isinstance(r, dict) and r.get("id")]
    rows.sort(key=lambda r: (-(r.get("createdAt") or 0), -(r.get("seq") or 0)))
    return rows


def cancel_blast(blast_id) -> dict:
    with _LOCK:
        data = _load()
        record = data.get(blast_id)
        if not isinstance(record, dict) or not record.get("id"):
            return {"error": "blast not found"}
        if record.get("status") in ("sent", "partial"):
            return {"error": "This blast already went out — it can't be cancelled."}
        record["status"] = "cancelled"
        _save(data)
        return {"ok": True, "blast": record}


def _send_one(recipient) -> dict:
    if not (recipient.get("phone") or "").strip():
        return {"ok": False, "skipped": True, "note": "no phone on file"}
    if _TRANSPORT is None:
        return {"ok": True, "stub": True,
                "note": "stub: would text %s" % recipient.get("phone")}
    try:
        result = _TRANSPORT(recipient, recipient.get("text") or "")
    except Exception as error:  # noqa: BLE001 — one bad number must not kill the blast
        return {"ok": False, "note": str(error) or "send failed"}
    return result if isinstance(result, dict) else {"ok": False, "note": "bad transport result"}


def send_blast(blast_id, *, throttle=0.25) -> dict:
    """OPERATOR-GATED. The console's confirm button is the approval gate (rule 2).

    Walks recipients one at a time (throttled so GHL doesn't rate-limit), and is
    re-entrant: anyone already 'sent' is never texted twice, so a retry after a
    partial failure only picks up the stragglers.
    """
    with _LOCK:
        data = _load()
        record = data.get(blast_id)
        if not isinstance(record, dict) or not record.get("id"):
            return {"error": "blast not found"}
        if record.get("status") == "cancelled":
            return {"error": "This blast was cancelled."}

        outs = _optouts(data)
        sent = skipped = failed = 0
        for recipient in record.get("recipients", []):
            if recipient.get("status") in ("sent", "stub-sent"):
                continue
            if recipient.get("key") in outs:
                recipient["status"] = "skipped"
                recipient["note"] = "opted out"
                skipped += 1
                continue
            result = _send_one(recipient)
            if result.get("ok"):
                recipient["status"] = "stub-sent" if result.get("stub") else "sent"
                recipient["sentAt"] = _now()
                recipient["note"] = result.get("note") or ""
                sent += 1
            elif result.get("skipped"):
                recipient["status"] = "skipped"
                recipient["note"] = result.get("note") or ""
                skipped += 1
            else:
                recipient["status"] = "failed"
                recipient["note"] = result.get("note") or "send failed"
                failed += 1
            if throttle:
                time.sleep(throttle)

        if failed and not sent:
            record["status"] = "failed"
        elif failed or skipped:
            record["status"] = "partial" if sent else record.get("status")
        if sent and not failed:
            record["status"] = "sent"
        record["sentAt"] = _now()
        _save(data)
        return {"ok": True, "blast": record,
                "summary": {"sent": sent, "skipped": skipped, "failed": failed},
                "live": _TRANSPORT is not None}
