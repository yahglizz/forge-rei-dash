#!/usr/bin/env python3
"""Standalone, DRAFT-ONLY reengage-SMS generator for cold/pending Ohio wholesale leads.

Reuses the REAL production drafting engine (marcus_engine.MarcusEngine._ai_draft) so
voice, safety rules, and brain-context injection are byte-for-byte what the live system
would produce. NEVER sends anything and NEVER writes to GHL:
  - `ghl_post` passed into MarcusEngine is a canary that raises if ever called.
  - Only `._recent_thread()` (GET) and `._ai_draft()` (GET-free, just a Claude call) are
    ever invoked on the engine — never `.poll_once()` / `._make_proposal()` / `.ghl_post`.

Input:  marcus_state/leads_export/ohio_leads_audit_deduped.csv
        (filtered to status_category in replied_then_cold / active_pending_us)
Output: marcus_state/leads_export/ohio_reengage_drafts.csv

Run from forge rei/ (or anywhere — paths below are anchored to this file's own dir):
    python3 reengage_draft.py
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # so `import marcus_engine` works regardless of caller's cwd

ENV_PATH = os.path.join(HERE, "..", "marcus-wholesale-agent", "config", "ghl.env")
IN_CSV = os.path.join(HERE, "marcus_state", "leads_export", "ohio_leads_audit_deduped.csv")
OUT_CSV = os.path.join(HERE, "marcus_state", "leads_export", "ohio_reengage_drafts.csv")

TARGET_STATUSES = {"replied_then_cold", "active_pending_us"}

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PAGE_LIMIT_UNUSED = None
RETRY_MAX = 3
RETRY_STATUSES = {429, 500, 502, 503}


# ---------------------------------------------------------------------------
# Env / auth — same pattern as leads_audit.py
# ---------------------------------------------------------------------------
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

api_call_count = 0


def ghl_get(path, params=None):
    """GET only. Retries on 429/500/502/503 or transient network error."""
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


def ghl_post_canary(*args, **kwargs):
    """This script must NEVER write/send. If anything calls ghl_post, blow up loudly."""
    raise RuntimeError(
        f"ghl_post must never be called in reengage_draft.py — called with {args!r} {kwargs!r}")


# ---------------------------------------------------------------------------
# The real production engine — import only, GET+draft calls only (see module docstring)
# ---------------------------------------------------------------------------
import marcus_engine  # noqa: E402


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


def most_recent_conversation_id(contact_id):
    data = ghl_get("/conversations/search", {
        "locationId": LOCATION_ID,
        "contactId": contact_id,
        "limit": 20,
        "sortBy": "last_message_date",
    })
    convs = data.get("conversations") or []
    if not convs:
        return None
    best = max(convs, key=lambda c: _to_ms(c.get("lastMessageDate")) or -1)
    return best.get("id")


def draft_for_row(engine, row):
    """Returns a dict of output-row fields. Never raises — caller wraps in try/except
    for the one-bad-contact-must-not-kill-the-run guarantee, but this stays internal
    too so a partial failure still yields a labeled row."""
    contact_id = row["contact_id"]
    name = row["name"] or ""
    status_category = row["status_category"]

    conv_id = most_recent_conversation_id(contact_id)
    seller_context, history = engine._recent_thread(conv_id, fallback=row["last_inbound_snippet"])
    body = seller_context

    first = name.split()[0] if name.strip() else "there"
    full = name

    cls = marcus_engine.classify(body)
    # Same override logic _make_proposal uses (marcus_engine.py ~997-1000).
    if cls != "DNC" and (cls == "NRN" or marcus_engine._is_soft_no(body)):
        cls = "NRN"
    if marcus_engine._is_denial(body, full):
        cls = "WRONG_NUMBER"

    hint = None
    hint_used = ""
    draft_status = "ok"

    if cls == "WRONG_NUMBER":
        draft_text = marcus_engine.CANNED_WRONG_NUMBER_REPLY
        draft_source = "canned_wrong_number"
    elif cls == "NRN":
        draft_text = marcus_engine.CANNED_NRN_REPLY
        draft_source = "canned_nrn"
    else:
        if status_category == "replied_then_cold":
            hint = (f"Seller said '{body[:200]}' and went quiet after our last message on "
                    f"{row['last_message_date_iso'][:10]}. Reopen naturally, not like a robo-blast.")
        text, source = engine._ai_draft(first, cls, body, history, hint=hint)
        hint_used = hint or ""
        draft_source = source
        if source == "blocked":
            draft_text = ""
            draft_status = "blocked"
        else:
            draft_text = text

    return {
        "contact_id": contact_id,
        "name": name,
        "phone": row["phone"],
        "city": row["city"],
        "state": row["state"],
        "status_category": status_category,
        "classification": cls,
        "draft_source": draft_source,
        "draft_text": draft_text,
        "seller_last_said": body,
        "hint_used": hint_used,
        "draft_status": draft_status,
        "_last_error": engine.last_error if draft_status == "blocked" else "",
    }


OUT_FIELDS = ["contact_id", "name", "phone", "city", "state", "status_category",
              "classification", "draft_source", "draft_text", "seller_last_said",
              "hint_used", "draft_status"]


def main():
    t0 = time.time()
    with open(IN_CSV, newline="") as f:
        all_rows = list(csv.DictReader(f))
    rows = [r for r in all_rows if r["status_category"] in TARGET_STATUSES]
    print(f"[reengage_draft] {len(rows)} rows to draft "
          f"(replied_then_cold + active_pending_us) out of {len(all_rows)} total")

    engine = marcus_engine.MarcusEngine(ghl_get, ghl_post_canary, LOCATION_ID)

    out_rows = []
    ok = blocked = errored = 0
    wrong_number_flags = []
    source_counts = {}

    for i, row in enumerate(rows, 1):
        try:
            result = draft_for_row(engine, row)
            last_error = result.pop("_last_error", "")
            if result["draft_status"] == "blocked":
                blocked += 1
                result["draft_text"] = f"[BLOCKED: {last_error}]"
            else:
                ok += 1
            source_counts[result["draft_source"]] = source_counts.get(result["draft_source"], 0) + 1
            if result["classification"] == "WRONG_NUMBER":
                wrong_number_flags.append((result["contact_id"], result["name"],
                                            result["status_category"]))
            out_rows.append(result)
        except Exception as e:  # noqa: BLE001 — one bad contact must not kill the run
            errored += 1
            out_rows.append({
                "contact_id": row.get("contact_id", ""),
                "name": row.get("name", ""),
                "phone": row.get("phone", ""),
                "city": row.get("city", ""),
                "state": row.get("state", ""),
                "status_category": row.get("status_category", ""),
                "classification": "",
                "draft_source": "",
                "draft_text": str(e),
                "seller_last_said": "",
                "hint_used": "",
                "draft_status": "error",
            })

        if i % 25 == 0:
            print(f"[reengage_draft] {i}/{len(rows)} done "
                  f"(ok={ok} blocked={blocked} error={errored}, {api_call_count} GHL calls)...")

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(out_rows)

    elapsed = time.time() - t0
    print("\n===== SUMMARY =====")
    print(f"Total drafted: {len(out_rows)}  ok={ok} blocked={blocked} error={errored}")
    print("Draft source breakdown:")
    for k, v in sorted(source_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    print(f"WRONG_NUMBER (new information vs original audit): {len(wrong_number_flags)}")
    for cid, name, sc in wrong_number_flags:
        print(f"  {cid} {name!r} ({sc})")
    print(f"GHL API calls: {api_call_count}  Elapsed: {elapsed:.1f}s")
    print(f"Output: {OUT_CSV}")


if __name__ == "__main__":
    main()
