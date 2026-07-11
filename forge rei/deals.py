"""Tier 3 — the persistent deal record.

Turns a tagged hot lead into a trackable deal: seller + property + numbers (ARV / repairs /
MAO) + offer + contract status. Without this the Deal Calc's MAO evaporates on refresh and
there's nothing to prefill a contract from.

Keyed by contactId. A pure JSON store (the connector does the prefill assembly from Marcus's
screening + the GHL contact, then calls upsert/save_calc here). Atomic writes so a restart
mid-write can't corrupt it.
"""
import json
import threading
import time
from pathlib import Path

import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "deals.json"
_LOCK = threading.RLock()
MAX = 1000

# Contract lifecycle (mirrors DocuSign envelope status, plus a local "none").
CONTRACT_STATES = ("none", "drafted", "sent", "delivered", "completed", "declined", "voided")


def _now():
    return int(time.time() * 1000)


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def get(contact_id):
    return _load().get(contact_id)


def list_deals():
    rows = list(_load().values())
    rows.sort(key=lambda r: -(r.get("updatedAt") or 0))
    return rows


def upsert(contact_id, **fields):
    """Create or update a deal. Only non-None fields overwrite; everything else is preserved."""
    if not contact_id:
        return {"error": "contactId required"}
    with _LOCK:
        d = _load()
        r = d.get(contact_id) or {"contactId": contact_id, "createdAt": _now(),
                                  "contractStatus": "none", "stage": "Lead"}
        for k, v in fields.items():
            if v is not None and v != "":
                r[k] = v
        r["updatedAt"] = _now()
        d[contact_id] = r
        if len(d) > MAX:
            keep = sorted(d.values(), key=lambda x: -(x.get("updatedAt") or 0))[:MAX]
            d = {x["contactId"]: x for x in keep}
        _save(d)
        return r


def unset(contact_id, *field_names):
    """Remove optional fields from a deal while preserving the rest of the record."""
    if not contact_id:
        return {"error": "contactId required"}
    with _LOCK:
        d = _load()
        r = d.get(contact_id)
        if not r:
            return {"error": "deal not found"}
        for name in field_names:
            r.pop(name, None)
        r["updatedAt"] = _now()
        d[contact_id] = r
        _save(d)
        return r


def save_calc(contact_id, arv=None, repairs=None, fee=None, pct=None, asking=None,
              mao=None, offer=None):
    """Persist the Deal Calc so the MAO stops evaporating on refresh."""
    return upsert(contact_id, arv=_num(arv), repairs=_num(repairs), assignmentFee=_num(fee),
                  maoPct=_num(pct), asking=_num(asking), mao=_num(mao), offer=_num(offer))


def set_contract(contact_id, status, envelope_id=None, sent_at=None, signed_url=None):
    """Update the contract/envelope state from DocuSign."""
    if status and status not in CONTRACT_STATES:
        status = "sent"
    return upsert(contact_id, contractStatus=status, contractEnvelopeId=envelope_id,
                  contractSentAt=sent_at, contractSignedUrl=signed_url)


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None
