#!/usr/bin/env python3
"""Standalone, READ-ONLY prep for Ohio reengagement drafting. Pulls FRESH full thread
text per lead (not the 120-char CSV snippet), classifies via the real seller_classify
logic (no LLM, no API key needed), and dumps a JSON file the main session then drafts
against directly (no Anthropic API key — this session's own model does the writing).

GET requests only. No sends, no tags, no drafts written here.
Run: python3 ohio_reengage_prep.py
"""
import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import marcus_engine  # safe: no import-time side effects (verified), pure functions only

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "..", "marcus-wholesale-agent", "config", "ghl.env")
IN_CSV = os.path.join(HERE, "marcus_state", "leads_export", "ohio_leads_audit_deduped.csv")
OUT_JSON = os.path.join(HERE, "marcus_state", "leads_export", "ohio_reengage_prep.json")

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def load_env(path):
    cfg = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


ENV = load_env(ENV_PATH)
API_KEY = ENV["GHL_API_KEY"]
LOCATION_ID = ENV["GHL_LOCATION_ID"]
BASE_URL = ENV.get("GHL_BASE_URL", "https://services.leadconnectorhq.com")
API_VERSION = ENV.get("GHL_API_VERSION", "2021-07-28")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Version": API_VERSION,
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
}

RETRY_MAX = 3
RETRY_STATUSES = {429, 500, 502, 503}
REAL_MESSAGE_TYPES = {"TYPE_SMS"}
api_call_count = 0


def ghl_get(path, params=None):
    global api_call_count
    url = f"{BASE_URL}{path}"
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{qs}"
    last_err = None
    for attempt in range(1, RETRY_MAX + 1):
        api_call_count += 1
        req = urllib.request.Request(url, headers=HEADERS, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < RETRY_MAX:
                time.sleep(0.6 * attempt)
                last_err = e
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < RETRY_MAX:
                time.sleep(0.6 * attempt)
                last_err = e
                continue
            raise
    raise last_err or RuntimeError("ghl_get failed with no response")


def _to_ms(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def full_thread(contact_id):
    convs = ghl_get("/conversations/search", {
        "locationId": LOCATION_ID, "contactId": contact_id, "limit": 20,
        "sortBy": "last_message_date",
    }).get("conversations") or []
    all_msgs = []
    for conv in convs:
        conv_id = conv.get("id")
        if not conv_id:
            continue
        data = ghl_get(f"/conversations/{conv_id}/messages", {"limit": 100})
        msgs = data.get("messages")
        if isinstance(msgs, dict):
            msgs = msgs.get("messages")
        all_msgs.extend(m for m in (msgs or []) if m.get("messageType") in REAL_MESSAGE_TYPES)
    all_msgs.sort(key=lambda m: _to_ms(m.get("dateAdded")) or 0)
    return all_msgs


def main():
    t0 = time.time()
    with open(IN_CSV) as f:
        rows = [r for r in csv.DictReader(f)
                if r["status_category"] in ("replied_then_cold", "active_pending_us")]
    print(f"[prep] {len(rows)} leads to prep (replied_then_cold + active_pending_us)")

    out = []
    errors = []
    for i, row in enumerate(rows, 1):
        cid = row["contact_id"]
        name = row["name"]
        first = (name.split() or ["there"])[0]
        try:
            messages = full_thread(cid)
            inbound = [m for m in messages if m.get("direction") == "inbound"
                       and marcus_engine._is_seller_message(m.get("body"))]
            outbound = [m for m in messages if m.get("direction") == "outbound"]
            last_inbound = inbound[-1] if inbound else None
            body = (last_inbound.get("body") if last_inbound else row["last_inbound_snippet"]) or ""

            cls = marcus_engine.classify(body)
            if cls != "DNC" and (cls == "NRN" or marcus_engine._is_soft_no(body)):
                cls = "NRN"
            if marcus_engine._is_denial(body, name):
                cls = "WRONG_NUMBER"

            history = []
            for m in messages[-8:]:
                b = (m.get("body") or "").strip()
                if b:
                    who = "Seller" if m.get("direction") == "inbound" else "You"
                    history.append(f"{who}: {b[:500]}")

            canned = None
            if cls == "WRONG_NUMBER":
                canned = marcus_engine.CANNED_WRONG_NUMBER_REPLY
            elif cls == "NRN":
                canned = marcus_engine.CANNED_NRN_REPLY

            hint = None
            if row["status_category"] == "replied_then_cold":
                hint = (f"Seller said '{body[:200]}' and went quiet after our last message "
                        f"on {row['last_message_date_iso'][:10]}. Reopen naturally, not like "
                        f"a robo-blast.")

            out.append({
                "contact_id": cid, "name": name, "first_name": first,
                "phone": row["phone"], "city": row["city"], "state": row["state"],
                "status_category": row["status_category"],
                "classification": cls,
                "canned_text": canned,
                "seller_last_message": body,
                "recent_history": history,
                "hint": hint,
                "total_inbound": len(inbound), "total_outbound": len(outbound),
            })
        except Exception as e:
            errors.append((cid, name, str(e)))
            continue

        if i % 25 == 0:
            print(f"[prep] {i}/{len(rows)} ({api_call_count} api calls)...")

    with open(OUT_JSON, "w") as f:
        json.dump({"leads": out, "errors": errors}, f, indent=2)

    from collections import Counter
    cls_counts = Counter(x["classification"] for x in out)
    print("\n===== PREP SUMMARY =====")
    print(f"Prepped: {len(out)}  Errors: {len(errors)}")
    print("Classification breakdown:", dict(cls_counts))
    needs_real_draft = sum(1 for x in out if x["canned_text"] is None)
    print(f"Needs a real drafted reply (not canned NRN/wrong-number): {needs_real_draft}")
    print(f"API calls: {api_call_count}  Elapsed: {time.time()-t0:.1f}s")
    print(f"Written: {OUT_JSON}")


if __name__ == "__main__":
    main()
