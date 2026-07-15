"""spend_tracker.py — the operator's OWN monthly subscriptions & recurring bills,
organized per business. This is NOT cost_tracker.py: that one meters what the OS itself
spends (Claude tokens, SMS, droplet). THIS one is the human's personal/business spend —
"my Claude subscription, my GoHighLevel, my Shopify" — the things YOU pay for, bucketed
by which business they belong to, so the main dashboard shows a clean monthly-spend
picture you keep current by editing the numbers.

Store mirrors cost_tracker: one small locked JSON (`marcus_state/spend_tracker.json`),
atomic writes, best-effort everywhere — a spend-ledger hiccup must never break a page load.
Every write is manual + operator-initiated; nothing here is autonomous or outward.
"""
import json
import threading
import time
import uuid
from pathlib import Path

import forge_atomic

STATE = Path(__file__).resolve().parent / "marcus_state" / "spend_tracker.json"
_LOCK = threading.Lock()

# The buckets a line item can belong to. Order = display order on the dashboard.
# Ids match the workspace ids where one exists (rei/agency/daycare/dropship) plus a
# "personal" catch-all for you + any shared tool that isn't owned by one business.
BUSINESSES = (
    ("personal", "Personal / Shared", "#4F7CFF"),
    ("rei",      "Wholesale (REI)",   "#4F7CFF"),
    ("agency",   "AI Agency",         "#8B5CF6"),
    ("daycare",  "Daycare",           "#2DD4BF"),
    ("dropship", "Dropship",          "#F97316"),
)
_BIZ_IDS = {b[0] for b in BUSINESSES}
_DEFAULT_BIZ = "personal"

CADENCES = ("monthly", "yearly")
_DEFAULT_CADENCE = "monthly"

# First-run scaffold: an organized starting set at $0 so the dashboard opens already
# grouped the way you asked — you just fill in (or edit/delete) the amounts. Seeded once;
# if you clear the list it does NOT come back (the "seeded" flag guards re-seeding).
_SEED = [
    ("personal", "Claude subscription"),
    ("personal", "ChatGPT"),
    ("personal", "DigitalOcean server"),
    ("rei",      "GoHighLevel (wholesale)"),
    ("agency",   "GoHighLevel (agency)"),
    ("daycare",  "GoHighLevel (daycare)"),
    ("dropship", "Shopify"),
]


def _load():
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _ensure_seed(d):
    """One-time scaffold so the section is organized before any price is entered."""
    if d.get("seeded"):
        return d
    items = d.setdefault("items", {})
    if not items:
        for biz, name in _SEED:
            iid = uuid.uuid4().hex[:8]
            items[iid] = {"id": iid, "name": name, "amount": 0.0,
                          "cadence": _DEFAULT_CADENCE, "business": biz,
                          "note": "", "updatedAt": int(time.time() * 1000)}
    d["seeded"] = True
    return d


def _monthly_equiv(item):
    try:
        amt = float(item.get("amount") or 0.0)
    except Exception:
        return 0.0
    return amt / 12.0 if item.get("cadence") == "yearly" else amt


def _clean_biz(biz):
    biz = (biz or "").strip().lower()
    return biz if biz in _BIZ_IDS else _DEFAULT_BIZ


# -- writes (all manual, operator-initiated) ----------------------------------------------

def save_item(item_id=None, name=None, amount=None, cadence=None, business=None, note=None):
    """Add a new line item, or update an existing one when item_id is given."""
    name = (name or "").strip()
    if not name and not item_id:
        return {"error": "name required"}
    try:
        amt = round(float(amount), 2) if amount not in (None, "") else 0.0
    except Exception:
        return {"error": "amount must be a number"}
    if amt < 0:
        return {"error": "amount must be 0 or more"}
    cad = (cadence or "").strip().lower()
    cad = cad if cad in CADENCES else _DEFAULT_CADENCE
    with _LOCK:
        d = _ensure_seed(_load())
        items = d.setdefault("items", {})
        if item_id and item_id in items:
            row = items[item_id]
            if name:
                row["name"] = name[:80]
            row["amount"] = amt
            row["cadence"] = cad
            if business is not None:
                row["business"] = _clean_biz(business)
            if note is not None:
                row["note"] = str(note)[:120]
            row["updatedAt"] = int(time.time() * 1000)
        else:
            iid = uuid.uuid4().hex[:8]
            items[iid] = {"id": iid, "name": name[:80], "amount": amt,
                          "cadence": cad, "business": _clean_biz(business),
                          "note": str(note or "")[:120],
                          "updatedAt": int(time.time() * 1000)}
        _save(d)
    return status()


def delete_item(item_id):
    item_id = (item_id or "").strip()
    if not item_id:
        return {"error": "id required"}
    with _LOCK:
        d = _ensure_seed(_load())
        d.setdefault("items", {}).pop(item_id, None)
        _save(d)
    return status()


# -- read API ------------------------------------------------------------------------------

def status():
    """Everything the Monthly Spend card needs: items grouped by business + totals."""
    try:
        with _LOCK:
            d = _ensure_seed(_load())
            _save(d)  # persist a first-run seed
        items = list((d.get("items") or {}).values())

        groups = []
        grand_monthly = 0.0
        for bid, label, color in BUSINESSES:
            rows = [i for i in items if (i.get("business") or _DEFAULT_BIZ) == bid]
            rows.sort(key=lambda r: (r.get("name") or "").lower())
            sub_monthly = round(sum(_monthly_equiv(r) for r in rows), 2)
            grand_monthly += sub_monthly
            groups.append({
                "id": bid, "label": label, "color": color,
                "monthlyUSD": sub_monthly,
                "yearlyUSD": round(sub_monthly * 12, 2),
                "items": [{
                    "id": r.get("id"), "name": r.get("name") or "",
                    "amount": round(float(r.get("amount") or 0.0), 2),
                    "cadence": r.get("cadence") or _DEFAULT_CADENCE,
                    "monthlyUSD": round(_monthly_equiv(r), 2),
                    "note": r.get("note") or "",
                } for r in rows],
            })
        grand_monthly = round(grand_monthly, 2)
        return {
            "ok": True,
            "groups": groups,
            "businesses": [{"id": b[0], "label": b[1]} for b in BUSINESSES],
            "cadences": list(CADENCES),
            "monthlyUSD": grand_monthly,
            "yearlyUSD": round(grand_monthly * 12, 2),
            "itemCount": len(items),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "groups": [], "monthlyUSD": 0.0}


def digest_line():
    """One-line personal-spend summary for the daily brief. Never raises."""
    try:
        s = status()
        return f"Your subscriptions ${s.get('monthlyUSD', 0):.2f}/mo (${s.get('yearlyUSD', 0):.2f}/yr)"
    except Exception:
        return ""
