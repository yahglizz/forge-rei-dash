"""Wholesaler Toolkit — operator-approved DocuSign contract state (Phase 4).

All envelope traffic is explicitly limited to the DocuSign demo environment for
v1.  The local JSON record is an approval and lifecycle ledger; it never stores
credentials and no send happens before a named operator approves it.
"""
import base64
import json
import re
import threading
import time
from pathlib import Path

import docusign_io
import forge_atomic


STATE = Path(__file__).resolve().parent / "marcus_state" / "contracts.json"
_LOCK = threading.RLock()
_STATUSES = ("pending", "sent", "signed", "voided", "completed")
_TEMPLATES = {
    "sfr": "Single-family purchase agreement",
    "multi": "Multifamily purchase agreement",
    "land": "Land purchase agreement",
    "assignment": "Assignment of purchase agreement",
}
MAX_CONTRACTS = 1000


def _now():
    return int(time.time() * 1000)


def _load():
    try:
        raw = json.loads(STATE.read_text())
    except Exception:
        raw = {}
    records = raw.get("contracts") if isinstance(raw, dict) else {}
    return {"contracts": records if isinstance(records, dict) else {}}


def _save(data):
    forge_atomic.atomic_write_json(STATE, data)


def _money(value):
    if value in (None, ""):
        return ""
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
        return "$" + format(int(round(number)), ",")
    except (TypeError, ValueError):
        return str(value)


def _template_id(template_type):
    try:
        return (docusign_io.template_map() or {}).get(template_type) or ""
    except Exception:
        return ""


def _record(data, deal_id):
    return data["contracts"].get(str(deal_id or ""))


def _change(deal_id, updater):
    key = str(deal_id or "").strip()
    if not key:
        return {"error": "dealId required"}
    with _LOCK:
        data = _load()
        record = _record(data, key)
        if not isinstance(record, dict):
            return {"error": "contract not found"}
        updater(record)
        record["updatedAt"] = _now()
        data["contracts"][key] = record
        _save(data)
        return dict(record)


def get_contract(deal_id):
    with _LOCK:
        record = _record(_load(), deal_id)
        return dict(record) if isinstance(record, dict) else None


def prefill_from_deal(deal, template_type="sfr"):
    """Derive reviewable DocuSign tabs from the saved local deal record.

    Purchase-agreement types (sfr/multi/land) are seller-signed and never
    include the assignment fee.  The ``assignment`` type is assignee-signed
    (the end buyer) and maps the fee + original-contract reference instead.
    """
    source = deal if isinstance(deal, dict) else {}
    kind = str(template_type or "sfr").strip().lower()
    buyer = (source.get("buyerName") or source.get("assignedBuyerName")
             or source.get("buyer_name") or "")
    signer = source.get("sellerName") or source.get("name") or ""
    price = _money(source.get("purchasePrice") or source.get("purchase_price")
                   or source.get("offer") or source.get("mao"))
    earnest = _money(source.get("earnestMoney") or source.get("earnest_money"))
    property_address = source.get("address") or source.get("propertyAddress") or ""
    terms = {
        "earnestMoney": earnest,
        "closingDate": str(source.get("closingDate") or source.get("closing_date") or ""),
        "titleCompany": str(source.get("titleCompany") or source.get("title_company") or ""),
        "terms": str(source.get("terms") or ""),
    }
    if kind == "assignment":
        fee = _money(source.get("assignmentFee") or source.get("assignment_fee")
                     or source.get("fee"))
        contract_date = str(source.get("contractDate") or source.get("originalContractDate")
                            or source.get("contract_date") or "")
        tabs = {
            "assignor_name": str(source.get("assignorName") or source.get("company") or ""),
            "assignee_name": buyer,
            "property_address": property_address,
            "assignment_fee": fee,
            "original_purchase_price": price,
            "original_contract_date": contract_date,
            "closing_date": terms["closingDate"],
        }
        return {
            "buyerName": buyer,
            "signerName": buyer,
            "signerEmail": str(source.get("buyerEmail") or source.get("assignedBuyerEmail")
                               or source.get("buyer_email") or ""),
            "propertyAddress": property_address,
            "purchasePrice": price,
            "assignmentFee": fee,
            "terms": terms,
            "tabs": tabs,
        }
    tabs = {
        "buyer_name": buyer,
        "seller_name": signer,
        "property_address": property_address,
        "purchase_price": price,
        "earnest_money": earnest,
        "closing_date": terms["closingDate"],
        "title_company": terms["titleCompany"],
    }
    return {
        "buyerName": buyer,
        "signerName": signer,
        "signerEmail": str(source.get("email") or source.get("sellerEmail") or ""),
        "propertyAddress": property_address,
        "purchasePrice": price,
        "terms": terms,
        "tabs": tabs,
    }


def template_list():
    """Return the v1 type picker, enriched from DocuSign only in sandbox."""
    sandbox = bool(docusign_io.is_sandbox())
    configured = bool(docusign_io.configured())
    template_ids = docusign_io.template_map() if sandbox else {}
    catalog = {}
    if sandbox and configured:
        try:
            catalog = {str(row.get("id")): row for row in docusign_io.list_templates()
                       if isinstance(row, dict) and row.get("id")}
        except Exception:
            catalog = {}
    rows = []
    for template_type, default_name in _TEMPLATES.items():
        template_id = template_ids.get(template_type) or ""
        remote = catalog.get(str(template_id)) or {}
        rows.append({
            "type": template_type,
            "id": template_id or None,
            "name": remote.get("name") or default_name,
            "configured": bool(template_id),
            "sandbox": sandbox,
        })
    return rows


def create_contract(deal_id, deal_dict, template_type, approval_required=True):
    """Create a reviewable local draft.  It cannot send an envelope by itself."""
    key = str(deal_id or "").strip()
    kind = str(template_type or "").strip().lower()
    if not key:
        return {"error": "dealId required"}
    if kind not in _TEMPLATES:
        return {"error": "templateType must be one of %s" % (tuple(_TEMPLATES),)}
    now = _now()
    deal = deal_dict if isinstance(deal_dict, dict) else {}
    with _LOCK:
        data = _load()
        existing = _record(data, key)
        if existing and existing.get("status") in ("sent", "signed", "completed"):
            return {"error": "an active contract already exists for this deal"}
        record = {
            "dealId": key,
            "dealName": str(deal.get("name") or deal.get("sellerName") or ""),
            "address": str(deal.get("address") or deal.get("propertyAddress") or ""),
            "templateType": kind,
            "templateName": _TEMPLATES[kind],
            "templateId": _template_id(kind) or None,
            "prefill": prefill_from_deal(deal, kind),
            "approvalRequired": bool(approval_required),
            "status": "pending",
            "createdAt": now,
            "updatedAt": now,
            "approvedAt": None,
            "approvedBy": None,
            "approvalReason": "",
            "sentAt": None,
            "envelopeId": None,
            "signedAt": None,
            "completedAt": None,
            "voidedAt": None,
            "voidReason": "",
            "sendError": "",
        }
        data["contracts"][key] = record
        if len(data["contracts"]) > MAX_CONTRACTS:
            rows = sorted(data["contracts"].values(),
                          key=lambda row: -(row.get("updatedAt") or 0))[:MAX_CONTRACTS]
            data["contracts"] = {row["dealId"]: row for row in rows}
        _save(data)
    return dict(record)


def list_contracts(status=None):
    if status is not None and status not in _STATUSES:
        return []
    with _LOCK:
        rows = [dict(row) for row in _load()["contracts"].values()
                if isinstance(row, dict) and (status is None or row.get("status") == status)]
    rows.sort(key=lambda row: (-(row.get("updatedAt") or 0), -(row.get("createdAt") or 0)))
    return rows


def send_contract(deal_id, operator_id, reason=""):
    """Operator-gated sandbox send through docusign_io's JWT grant client."""
    operator = str(operator_id or "").strip()
    if not operator:
        return {"error": "operator approval required"}
    if not docusign_io.is_sandbox():
        return {"error": "Contracts v1 is sandbox-only; production sending is disabled"}
    if not docusign_io.configured():
        return {"error": "DocuSign sandbox is not configured"}
    record = get_contract(deal_id)
    if not record:
        return {"error": "contract not found"}
    if record.get("status") != "pending":
        return {"error": "only pending contracts can be sent"}
    prefill = record.get("prefill") or {}
    if not prefill.get("signerEmail"):
        return {"error": "seller email required before approval"}
    result = docusign_io.send_contract(
        prefill.get("signerEmail"), prefill.get("signerName"),
        tabs=prefill.get("tabs") or {}, template_id=record.get("templateId") or None,
    )
    if not isinstance(result, dict) or not result.get("ok"):
        error = (result or {}).get("error") if isinstance(result, dict) else "DocuSign send failed"
        _change(deal_id, lambda row: row.update(sendError=str(error or "DocuSign send failed")))
        return {"error": str(error or "DocuSign send failed")}
    now = _now()
    updated = _change(deal_id, lambda row: row.update(
        status="sent", envelopeId=result.get("envelopeId"), sentAt=now,
        approvedAt=now, approvedBy=operator, approvalReason=str(reason or ""), sendError="",
    ))
    return {"ok": True, "contract": updated, "sandbox": True}


def mark_signed(deal_id):
    """Record a signature event supplied by a webhook or poller."""
    return _change(deal_id, lambda row: row.update(status="signed", signedAt=_now()))


def mark_completed(deal_id):
    """Record a completed DocuSign envelope event supplied by the poller."""
    return _change(deal_id, lambda row: row.update(status="completed", completedAt=_now()))


def refresh_contract_status(deal_id):
    """Read a sandbox envelope lifecycle without sending or altering its terms."""
    record = get_contract(deal_id)
    if not record:
        return {"error": "contract not found"}
    if record.get("status") not in ("sent", "signed") or not record.get("envelopeId"):
        return {"contract": record, "checked": False}
    if not docusign_io.is_sandbox() or not docusign_io.configured():
        return {"error": "DocuSign sandbox is required to refresh envelope status"}
    result = docusign_io.envelope_status(record.get("envelopeId"))
    if not isinstance(result, dict) or result.get("error"):
        error = (result or {}).get("error") if isinstance(result, dict) else "DocuSign status failed"
        _change(deal_id, lambda row: row.update(statusError=str(error or "DocuSign status failed")))
        return {"error": str(error or "DocuSign status failed")}
    remote_status = str(result.get("status") or "").lower()
    if remote_status == "completed":
        updated = mark_completed(deal_id)
    elif remote_status == "signed":
        updated = mark_signed(deal_id)
    elif remote_status in ("voided", "declined"):
        updated = _change(deal_id, lambda row: row.update(
            status="voided", voidedAt=_now(), voidReason="DocuSign " + remote_status,
        ))
    else:
        updated = _change(deal_id, lambda row: row.update(remoteStatus=remote_status))
    return {"ok": True, "checked": True, "contract": updated, "remoteStatus": remote_status}


def void_contract(deal_id, reason=""):
    """Void locally-pending contracts, or an approved sandbox envelope when sent."""
    record = get_contract(deal_id)
    if not record:
        return {"error": "contract not found"}
    if record.get("status") == "voided":
        return record
    if record.get("status") in ("signed", "completed"):
        return {"error": "signed or completed contracts cannot be voided here"}
    if record.get("status") == "sent" and record.get("envelopeId"):
        if not docusign_io.is_sandbox() or not docusign_io.configured():
            return {"error": "DocuSign sandbox is required to void a sent envelope"}
        result = docusign_io.void_envelope(record.get("envelopeId"), reason)
        if not isinstance(result, dict) or not result.get("ok"):
            error = (result or {}).get("error") if isinstance(result, dict) else "DocuSign void failed"
            _change(deal_id, lambda row: row.update(voidError=str(error or "DocuSign void failed")))
            return {"error": str(error or "DocuSign void failed")}
    return _change(deal_id, lambda row: row.update(
        status="voided", voidedAt=_now(), voidReason=str(reason or ""),
    ))


# ---------------------------------------------------------------------------
# Operator-uploaded contract templates + Quick Send (added 2026-07-11).
#
# The operator uploads THEIR OWN contract file (PDF/DOCX, base64 data-URL —
# same wire pattern as blast photos), then fires it to a seller through
# DocuSign with just name/email/address/price. The file becomes the envelope
# document (docusign_io.send_document, free-form signing) — no per-template
# field mapping needed. Files live in marcus_state/ (HTTP-denied dir).
# Same v1 gates as template sends: sandbox-only + named operator.
# ---------------------------------------------------------------------------
TEMPLATES_DIR = Path(__file__).resolve().parent / "marcus_state" / "contract_templates"
TEMPLATES_STATE = Path(__file__).resolve().parent / "marcus_state" / "toolkit_templates.json"
MAX_TEMPLATES = 20
MAX_TEMPLATE_BYTES = 10 * 1024 * 1024  # 10 MB
_DOC_RE = re.compile(
    r"^data:(application/pdf|application/vnd\.openxmlformats-officedocument"
    r"\.wordprocessingml\.document|application/msword);base64,(.+)$", re.S)
_DOC_EXT = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
}


def _templates_load():
    try:
        raw = json.loads(TEMPLATES_STATE.read_text())
    except Exception:
        raw = {}
    rows = raw.get("templates") if isinstance(raw, dict) else {}
    return {"templates": rows if isinstance(rows, dict) else {}}


def _templates_save(data):
    forge_atomic.atomic_write_json(TEMPLATES_STATE, data)


def save_template(name, data_url):
    """Store an operator-uploaded contract file. Returns the registry row."""
    label = str(name or "").strip()[:80]
    m = _DOC_RE.match(str(data_url or "").strip())
    if not m:
        return {"error": "Upload a PDF or Word (.docx) contract file."}
    mime, b64 = m.group(1), m.group(2)
    try:
        blob = base64.b64decode(b64, validate=True)
    except Exception:
        return {"error": "That file didn't decode — re-pick it and try again."}
    if not blob:
        return {"error": "Empty file."}
    if len(blob) > MAX_TEMPLATE_BYTES:
        return {"error": "File too big — keep contract templates under 10 MB."}
    ext = _DOC_EXT[mime]
    with _LOCK:
        data = _templates_load()
        if len(data["templates"]) >= MAX_TEMPLATES:
            return {"error": f"Template limit reached ({MAX_TEMPLATES}) — delete one first."}
        tid = f"t{_now()}"
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        (TEMPLATES_DIR / f"{tid}.{ext}").write_bytes(blob)
        row = {"id": tid, "name": label or f"Contract template {len(data['templates']) + 1}",
               "ext": ext, "size": len(blob), "uploadedAt": _now()}
        data["templates"][tid] = row
        _templates_save(data)
    return {"ok": True, "template": row}


def list_uploaded_templates():
    with _LOCK:
        rows = [dict(r) for r in _templates_load()["templates"].values()]
    rows.sort(key=lambda r: -(r.get("uploadedAt") or 0))
    return {"templates": rows,
            "sandbox": bool(docusign_io.is_sandbox()),
            "configured": bool(docusign_io.configured())}


def delete_template(template_id):
    tid = str(template_id or "").strip()
    with _LOCK:
        data = _templates_load()
        row = data["templates"].pop(tid, None)
        if not row:
            return {"error": "template not found"}
        _templates_save(data)
        try:
            (TEMPLATES_DIR / f"{tid}.{row.get('ext', 'pdf')}").unlink(missing_ok=True)
        except Exception:
            pass
    return {"ok": True, "deleted": tid}


def quick_send(body):
    """Send an uploaded template to a seller through DocuSign in one shot.

    body: {templateId, sellerName, sellerEmail, address, price, closingDate,
           notes, operatorId}. Sandbox-only + operator-named, like every send.
    Records a 'custom' contract in the ledger so the tracker/poller sees it.
    """
    body = body or {}
    operator = str(body.get("operatorId") or "").strip()
    if not operator:
        return {"error": "operator approval required"}
    if not docusign_io.is_sandbox():
        return {"error": "Contracts v1 is sandbox-only; production sending is disabled"}
    if not docusign_io.configured():
        return {"error": "DocuSign sandbox is not configured"}
    seller_email = str(body.get("sellerEmail") or "").strip()
    seller_name = str(body.get("sellerName") or "").strip()
    if "@" not in seller_email:
        return {"error": "seller email required (DocuSign delivers by email)"}
    tid = str(body.get("templateId") or "").strip()
    with _LOCK:
        row = _templates_load()["templates"].get(tid)
    if not row:
        return {"error": "pick an uploaded contract template first"}
    path = TEMPLATES_DIR / f"{tid}.{row.get('ext', 'pdf')}"
    try:
        doc_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        return {"error": "template file missing on disk — re-upload it"}

    address = str(body.get("address") or "").strip()
    price = _money(body.get("price"))
    closing = str(body.get("closingDate") or "").strip()
    notes = str(body.get("notes") or "").strip()
    subject = ("Purchase agreement — " + address) if address else "Purchase agreement to sign"
    blurb_bits = []
    if price:
        blurb_bits.append(f"Purchase price: {price}.")
    if closing:
        blurb_bits.append(f"Target closing: {closing}.")
    blurb_bits.append("Review the attached agreement and sign where indicated. "
                      "Reply to this email with any questions.")
    if notes:
        blurb_bits.append(notes)

    # Durability: persist the ledger row BEFORE the DocuSign call so a crash
    # mid-send can never leave a live envelope with no local record. Mirrors the
    # main flow's convention: failures stay status="pending" with sendError set;
    # the status poller only touches sent/signed rows that have an envelopeId.
    now = _now()
    deal_key = str(body.get("dealId") or f"quick-{now}")
    record = {
        "dealId": deal_key,
        "dealName": seller_name or seller_email,
        "address": address,
        "templateType": "custom",
        "templateName": row.get("name") or "Uploaded contract",
        "templateId": tid,
        "prefill": {"signerName": seller_name, "signerEmail": seller_email,
                    "propertyAddress": address, "purchasePrice": price,
                    "terms": {"closingDate": closing, "notes": notes}},
        "approvalRequired": True,
        "status": "pending",
        "createdAt": now, "updatedAt": now,
        "approvedAt": now, "approvedBy": operator, "approvalReason": "quick send",
        "sentAt": None, "envelopeId": None,
        "signedAt": None, "completedAt": None, "voidedAt": None,
        "voidReason": "", "sendError": "",
    }
    with _LOCK:
        data = _load()
        data["contracts"][deal_key] = record
        _save(data)

    result = docusign_io.send_document(
        seller_email, seller_name, doc_b64, row.get("name") or "Contract",
        ext=row.get("ext", "pdf"), email_subject=subject,
        email_blurb=" ".join(blurb_bits))
    if not isinstance(result, dict) or not result.get("ok"):
        error = (result or {}).get("error") if isinstance(result, dict) else "DocuSign send failed"
        with _LOCK:
            data = _load()
            failed = data["contracts"].get(deal_key)
            if isinstance(failed, dict):
                failed.update(sendError=str(error or "DocuSign send failed"),
                              updatedAt=_now())
                _save(data)
        return {"error": str(error or "DocuSign send failed"), "dealId": deal_key}

    sent_at = _now()
    with _LOCK:
        data = _load()
        record = data["contracts"].get(deal_key) or record
        record.update(status="sent", sentAt=sent_at, updatedAt=sent_at,
                      envelopeId=result.get("envelopeId"), sendError="")
        data["contracts"][deal_key] = record
        _save(data)
    return {"ok": True, "contract": record, "sandbox": True,
            "envelopeId": result.get("envelopeId")}
