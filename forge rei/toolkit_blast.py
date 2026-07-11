"""Wholesaler Toolkit — Buyer Blast engine (Phase 2).

Turns a locked/offered deal into a buyer-facing deal sheet, matches it against
the cash-buyer roster (buyers.match), drafts per-buyer SMS/email, and runs an
operator-gated blast. Open Decision #1 resolved GHL-native: the connector
registers a real transport via register_transport(), but it only fires when
FORGE_BLAST_LIVE=1 is set in the environment — otherwise every send stays a
stub and nothing leaves the box.

Stores: marcus_state/toolkit_blast.json (blast records) + uploads/deals/<id>/
(photos). Stays decoupled like buyers.py — the connector assembles the deal
dict + matches and hands them in; this module never imports deals/connector.
Reuses toolkit_calc.buyer_view so the assignment fee is NEVER exposed to buyers.
"""
import base64
import json
import os
import re
import threading
import time
from pathlib import Path

import forge_atomic
import toolkit_calc

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "toolkit_blast.json"
UPLOADS = HERE / "uploads" / "deals"
_LOCK = threading.RLock()
MAX_BLASTS = 500
MAX_PHOTOS = 12
MAX_PHOTO_BYTES = 6 * 1024 * 1024

# Live sends require BOTH: a transport registered by the connector (GHL-native)
# AND FORGE_BLAST_LIVE=1 in the environment. Default is stub — nothing sends.
LIVE_ENV = "FORGE_BLAST_LIVE"
_TRANSPORT = None


def register_transport(fn):
    """Connector injects the real wire-send here (keeps this module decoupled)."""
    global _TRANSPORT
    _TRANSPORT = fn


def live_enabled():
    return os.environ.get(LIVE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _now():
    return int(time.time() * 1000)


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", (s or "").strip()).strip("-")[:60] or "deal"


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def build_sheet(deal, photos=None):
    """Buyer-facing sheet. purchase = what the buyer pays (contract + fee as ONE
    number); the fee itself is never surfaced. Numbers via toolkit_calc.buyer_view."""
    deal = deal or {}
    arv = _num(deal.get("arv"))
    repairs = _num(deal.get("repairs"))
    # what the buyer pays: prefer the saved toolkit snapshot buyerPrice, else mao+fee, else offer
    purchase = None
    snap = ((deal.get("toolkitCalc") or {}).get("results") or {}).get("internal") or {}
    if _num(snap.get("buyerPrice")):
        purchase = _num(snap.get("buyerPrice"))
    elif _num(deal.get("mao")) is not None:
        purchase = _num(deal.get("mao")) + (_num(deal.get("assignmentFee")) or 0)
    elif _num(deal.get("offer")):
        purchase = _num(deal.get("offer"))
    sheet = {
        "dealId": deal.get("contactId"),
        "name": deal.get("name") or "",
        "address": deal.get("address") or "",
        "beds": deal.get("beds"), "baths": deal.get("baths"), "sqft": deal.get("sqft"),
        "condition": deal.get("condition") or deal.get("propertyStatus") or "",
        "arv": arv, "purchase": purchase, "repairs": repairs,
        "profit": None, "roiPct": None,
        "photos": list(photos or []),
    }
    if arv and purchase:
        bv = toolkit_calc.buyer_view(arv, purchase, repairs or 0)
        if not bv.get("error"):
            sheet["profit"] = bv["profit"]
            sheet["roiPct"] = bv["roiPct"]
    return sheet


_IMG_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
            "image/webp": "webp"}
_DATA_RE = re.compile(r"^data:(image/[a-zA-Z]+);base64,(.+)$", re.DOTALL)


def _deal_dir(deal_id):
    return UPLOADS / _slug(deal_id)


def list_photos(deal_id):
    d = _deal_dir(deal_id)
    if not d.is_dir():
        return []
    slug = _slug(deal_id)
    return ["/uploads/deals/%s/%s" % (slug, p.name)
            for p in sorted(d.iterdir()) if p.suffix.lstrip(".").lower()
            in ("png", "jpg", "jpeg", "webp")]


def save_photos(deal_id, data_urls):
    """Decode base64 image data-URLs onto disk under uploads/deals/<slug>/.
    Rejects non-images + oversize; caps total at MAX_PHOTOS."""
    if not deal_id:
        return {"error": "dealId required"}
    with _LOCK:
        d = _deal_dir(deal_id)
        d.mkdir(parents=True, exist_ok=True)
        existing = len(list_photos(deal_id))
        saved, skipped = [], 0
        for url in (data_urls or []):
            if existing + len(saved) >= MAX_PHOTOS:
                skipped += 1
                continue
            m = _DATA_RE.match(url or "")
            if not m or m.group(1) not in _IMG_EXT:
                skipped += 1
                continue
            try:
                raw = base64.b64decode(m.group(2), validate=False)
            except Exception:
                skipped += 1
                continue
            if not raw or len(raw) > MAX_PHOTO_BYTES:
                skipped += 1
                continue
            ext = _IMG_EXT[m.group(1)]
            n = existing + len(saved) + 1
            (d / ("%d.%s" % (n, ext))).write_bytes(raw)
            saved.append(1)
    return {"ok": True, "photos": list_photos(deal_id), "skipped": skipped}


def _money(v):
    n = _num(v)
    return ("$%s" % format(int(round(n)), ",")) if n is not None else "—"


def _draft_sms(sheet):
    addr = sheet.get("address") or "an off-market property"
    bits = ["New off-market deal — %s." % addr]
    if sheet.get("arv"):
        bits.append("ARV %s." % _money(sheet["arv"]))
    if sheet.get("purchase"):
        bits.append("Yours at %s." % _money(sheet["purchase"]))
    if sheet.get("profit"):
        bits.append("Est. spread %s." % _money(sheet["profit"]))
    bits.append("Want the full sheet + pics? Reply YES.")
    return " ".join(bits)


def _draft_email(sheet):
    addr = sheet.get("address") or "Off-market property"
    subject = "Off-market deal: %s" % addr
    lines = ["Off-market wholesale deal — quick numbers:", "",
             "Property: %s" % addr]
    if sheet.get("beds") or sheet.get("baths") or sheet.get("sqft"):
        lines.append("Specs: %s bd / %s ba / %s sqft" % (
            sheet.get("beds") or "?", sheet.get("baths") or "?", sheet.get("sqft") or "?"))
    if sheet.get("condition"):
        lines.append("Condition: %s" % sheet["condition"])
    lines.append("")
    if sheet.get("arv"):
        lines.append("ARV (after repair): %s" % _money(sheet["arv"]))
    if sheet.get("repairs"):
        lines.append("Est. repairs: %s" % _money(sheet["repairs"]))
    if sheet.get("purchase"):
        lines.append("Your price: %s" % _money(sheet["purchase"]))
    if sheet.get("profit"):
        lines.append("Est. buyer spread: %s (%s%% cash-in ROI)" % (
            _money(sheet["profit"]), sheet.get("roiPct")))
    lines += ["", "%d photo(s) available." % len(sheet.get("photos") or []),
              "Reply if you want the full packet + address. Cash / hard-money only.", ""]
    return {"subject": subject, "body": "\n".join(lines)}


def create_blast(deal, matches, channels=None, buyer_ids=None, photos=None):
    """Build a QUEUED blast from a deal + ranked buyer matches. Never sends —
    send_blast() does that, and only through the (stubbed) transport."""
    deal = deal or {}
    matches = matches or []
    if buyer_ids:
        keep = set(buyer_ids)
        matches = [m for m in matches if m.get("buyerId") in keep]
    if not matches:
        return {"error": "no matched buyers"}
    channels = [c for c in (channels or ["sms"]) if c in ("sms", "email")] or ["sms"]
    sheet = build_sheet(deal, photos if photos is not None else list_photos(deal.get("contactId")))
    sms = _draft_sms(sheet)
    email = _draft_email(sheet)
    prim = channels[0]
    recips = []
    for m in matches:
        b = m.get("buyer") or {}
        recips.append({
            "buyerId": m.get("buyerId"), "name": m.get("name") or b.get("name") or "",
            "phone": b.get("phone") or "", "email": b.get("email") or "",
            "score": m.get("score"), "fits": bool(m.get("fits")),
            "channel": prim,
            "smsDraft": sms, "emailSubject": email["subject"], "emailBody": email["body"],
            "status": "queued", "response": "none", "sentAt": None, "note": "",
        })
    with _LOCK:
        d = _load()
        base = "blast-" + _slug(deal.get("name") or deal.get("contactId"))
        bid, n = base, 2
        while bid in d:
            bid = "%s-%d" % (base, n)
            n += 1
        seq = max([x.get("seq", 0) for x in d.values()] or [0]) + 1
        rec = {"id": bid, "seq": seq, "dealId": deal.get("contactId"),
               "dealName": deal.get("name") or "", "address": sheet.get("address") or "",
               "createdAt": _now(), "status": "queued", "channels": channels,
               "sheet": sheet, "recipients": recips}
        d[bid] = rec
        if len(d) > MAX_BLASTS:
            keep = sorted(d.values(), key=lambda x: -(x.get("createdAt") or 0))[:MAX_BLASTS]
            d = {x["id"]: x for x in keep}
        _save(d)
        return rec


def get_blast(blast_id):
    return _load().get(blast_id)


def list_blasts():
    rows = list(_load().values())
    rows.sort(key=lambda r: (-(r.get("createdAt") or 0), -(r.get("seq") or 0)))
    return rows


_VERDICTS = ("none", "interested", "passed", "noreply")


def _transport(recipient, sheet):
    """Wire-send one recipient. Live only when the connector registered a
    transport AND FORGE_BLAST_LIVE=1; every other combination is a harmless
    stub that just reports what WOULD go out."""
    ch = recipient.get("channel")
    dest = recipient.get("email") if ch == "email" else recipient.get("phone")
    if not dest:
        return {"ok": False, "skipped": True, "note": "no %s on file" % ch}
    if live_enabled() and _TRANSPORT is not None:
        try:
            res = _TRANSPORT(recipient, sheet)
        except Exception as e:  # noqa: BLE001 - a transport crash must not kill the loop
            return {"ok": False, "note": str(e) or "transport error"}
        return res if isinstance(res, dict) else {"ok": False, "note": "bad transport result"}
    return {"ok": True, "stub": True,
            "note": "stub: would %s %s" % (ch, dest)}


def _find(rec, buyer_id):
    return next((x for x in rec.get("recipients", []) if x.get("buyerId") == buyer_id), None)


def set_recipient(blast_id, buyer_id, **fields):
    allowed = {"channel", "smsDraft", "emailSubject", "emailBody", "status", "note"}
    with _LOCK:
        d = _load()
        rec = d.get(blast_id)
        if not rec:
            return {"error": "blast not found"}
        r = _find(rec, buyer_id)
        if not r:
            return {"error": "recipient not found"}
        for k, v in fields.items():
            if k in allowed and v is not None:
                r[k] = v
        _save(d)
        return rec


def send_blast(blast_id):
    """Operator-gated. Fires the (stubbed) transport for every queued recipient."""
    with _LOCK:
        d = _load()
        rec = d.get(blast_id)
        if not rec:
            return {"error": "blast not found"}
        sent = skipped = failed = 0
        for r in rec["recipients"]:
            if r["status"] in ("stub-sent", "sent"):
                continue
            res = _transport(r, rec.get("sheet") or {})
            if res.get("ok"):
                r["status"] = "stub-sent" if res.get("stub") else "sent"
                r["sentAt"] = _now()
                r["note"] = res.get("note") or ""
                sent += 1
            elif res.get("skipped"):
                r["status"] = "skipped"
                r["note"] = res.get("note") or ""
                skipped += 1
            else:
                r["status"] = "failed"
                r["note"] = res.get("note") or "send failed"
                failed += 1
        rec["status"] = "sent" if sent else ("partial" if (skipped or failed) else rec["status"])
        rec["sentAt"] = _now()
        _save(d)
        return {"ok": True, "blast": rec,
                "summary": {"sent": sent, "skipped": skipped, "failed": failed},
                "live": live_enabled()}


def record_response(blast_id, buyer_id, verdict):
    if verdict not in _VERDICTS:
        return {"error": "verdict must be one of %s" % (_VERDICTS,)}
    with _LOCK:
        d = _load()
        rec = d.get(blast_id)
        if not rec:
            return {"error": "blast not found"}
        r = _find(rec, buyer_id)
        if not r:
            return {"error": "recipient not found"}
        r["response"] = verdict
        _save(d)
        return rec
