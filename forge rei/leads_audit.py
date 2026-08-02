#!/usr/bin/env python3
"""Standalone, READ-ONLY GHL audit: pull leads for a target state, pull each contact's
full message thread, classify reply status, dump a CSV.

GET requests only. No sends, no tags, no pipeline moves. Safe to re-run.

Run: python3 leads_audit.py
"""
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TARGET_STATE = "OH"  # 2-letter or full name; case-insensitive exact match against contact.state

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "..", "marcus-wholesale-agent", "config", "ghl.env")
OUT_DIR = os.path.join(HERE, "marcus_state", "leads_export")
OUT_CSV = os.path.join(OUT_DIR, "ohio_leads_audit.csv")

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

PAGE_LIMIT = 100
CONV_LIMIT = 20
MSG_LIMIT = 100
RETRY_MAX = 3
RETRY_STATUSES = {429, 500, 502, 503}


# ---------------------------------------------------------------------------
# Env / auth
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


# ---------------------------------------------------------------------------
# Seller-reply classification — ported verbatim from marcus_engine.py:378-507
# ---------------------------------------------------------------------------
_OUR_OUTREACH_PHRASES = [
    "we buy houses", "we buy homes", "we buy property", "we pay cash",
    "cash offer", "close fast", "close quickly", "as-is", "no realtor", "no agents",
    "i was calling about", "i'm calling about", "im calling about",
    "calling about potentially selling", "potentially selling a home",
    "just following up", "just checking in", "circle back", "circling back",
    "reaching out about your", "saw your property", "saw your home",
    "wanted to reach out", "wanted to see if", "wanted to ask if",
    "trying to reach you", "tried calling you", "following up on my call",
    "following up on my text", "following up about the property",
    "would you consider selling", "have you considered selling",
    "interested in selling your", "consider an offer on",
    "cash for your property", "cash for your home",
    "looking to purchase your", "interested in buying your", "buy your property",
    "buy your house", "buy your home", "are you the owner of the property",
    "are you still looking to sell", "still looking to sell", "still interested in selling",
    "this is yahjair", "hey it's yahjair", "this is forge",
    "touch of blessing", "touch of blessings", "we just missed your call",
    "how can we help you today",
]

_OUR_OUTREACH_RE = re.compile(
    r"(?i)^\s*(?:hey|hi|hello)?\s*[a-z'-]{0,30}[, ]*"
    r"(?:this is yahjair|it'?s yahjair|i(?:'m| am) (?:reaching|following|calling|texting)|"
    r"i (?:wanted|was trying|tried) to (?:reach|call|text|see|ask)|"
    r"we(?:'re| are) (?:looking|interested|buying)|would you (?:consider|be open to) selling)\b"
)


def _is_our_message(body):
    b = (body or "").lower()
    return any(p in b for p in _OUR_OUTREACH_PHRASES) or bool(_OUR_OUTREACH_RE.search(body or ""))


_REACT_POS = ("👍", "❤", "♥", "😍", "😎", "😂", "🤣", "🔥", "👏", "🙏", "✅", "💯",
              "😊", "🙂", "👌", "💪", "liked", "loved", "laughed", "emphasized")
_REACT_NEG = ("👎", "disliked")
_REACT_Q = ("❓", "❔", "questioned")
_REACT_LEAD = re.compile(r"^[\s​‌‍⁦-⁩️]+")


def _reaction_kind(body):
    if not body:
        return None
    b = _REACT_LEAD.sub("", body)
    low = b.lower()
    quoted = ('"' in b) or ('“' in b) or (' to ' in low[:8])
    if not quoted:
        return None
    head = low[:16]
    if any(head.startswith(o) for o in _REACT_NEG):
        return "neg"
    if any(head.startswith(o) for o in _REACT_Q):
        return "q"
    if any(head.startswith(o) for o in _REACT_POS):
        return "pos"
    return None


def _is_reaction(body):
    return _reaction_kind(body) is not None


def _is_seller_message(body):
    """True for genuine seller text, including reactions that quote our outreach."""
    return bool((body or "").strip()) and (
        not _is_our_message(body) or _is_reaction(body)
    )


# ---------------------------------------------------------------------------
# GHL pulls
# ---------------------------------------------------------------------------
def list_all_contacts():
    """Cursor-paginate /contacts/ for the location. Returns list of raw contact dicts.

    GHL's `dateAdded` on each contact is an ISO string, not the epoch-ms cursor the
    pagination actually wants — the real cursor comes back in the response's `meta`
    block (`meta.startAfter` epoch ms + `meta.startAfterId`). Fall back to the last
    contact's own `startAfter` field (a [epoch_ms, id] pair GHL attaches) if meta is
    ever missing.
    """
    contacts = []
    start_after = None
    start_after_id = None
    while True:
        params = {"locationId": LOCATION_ID, "limit": PAGE_LIMIT}
        if start_after is not None:
            params["startAfter"] = start_after
            params["startAfterId"] = start_after_id
        data = ghl_get("/contacts/", params)
        page = data.get("contacts") or []
        if not page:
            break
        contacts.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        meta = data.get("meta") or {}
        start_after = meta.get("startAfter")
        start_after_id = meta.get("startAfterId")
        if start_after is None or start_after_id is None:
            last = page[-1]
            cursor = last.get("startAfter")
            if isinstance(cursor, list) and len(cursor) == 2:
                start_after, start_after_id = cursor
            else:
                start_after, start_after_id = None, None
        if start_after is None or start_after_id is None:
            break
    return contacts


def list_conversations(contact_id):
    data = ghl_get("/conversations/search", {
        "locationId": LOCATION_ID,
        "contactId": contact_id,
        "limit": CONV_LIMIT,
        "sortBy": "last_message_date",
    })
    return data.get("conversations") or []


def get_messages(conversation_id):
    data = ghl_get(f"/conversations/{conversation_id}/messages", {"limit": MSG_LIMIT})
    msgs = data.get("messages")
    if isinstance(msgs, dict):
        msgs = msgs.get("messages")
    return msgs or []


def full_thread(contact_id):
    """All messages across all conversations for a contact, chronological (oldest first)."""
    all_msgs = []
    for conv in list_conversations(contact_id):
        conv_id = conv.get("id")
        if not conv_id:
            continue
        msgs = get_messages(conv_id)
        all_msgs.extend(msgs)  # GHL returns newest-first per conversation
    # sort by dateAdded ascending (ms epoch); fall back to 0 if missing
    def _key(m):
        d = m.get("dateAdded")
        return d if isinstance(d, (int, float)) else 0
    all_msgs.sort(key=_key)
    return all_msgs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def contact_name(c):
    name = c.get("name")
    if name:
        return name
    parts = [c.get("firstName") or "", c.get("lastName") or ""]
    full = " ".join(p for p in parts if p).strip()
    return full or "(no name)"


def snippet(body, n=120):
    b = (body or "").replace("\n", " ").strip()
    return b[:n]


def iso(ms):
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def classify(messages):
    """messages: chronological list of dicts with 'direction' + 'body'.
    Returns (status_category, last_inbound, last_outbound, total_inbound, total_outbound,
             last_msg_direction, last_msg_date_ms).
    """
    inbound_seller_msgs = [m for m in messages if m.get("direction") == "inbound"
                            and _is_seller_message(m.get("body"))]
    outbound_msgs = [m for m in messages if m.get("direction") == "outbound"]
    total_inbound = len(inbound_seller_msgs)
    total_outbound = len(outbound_msgs)

    last_inbound = inbound_seller_msgs[-1] if inbound_seller_msgs else None
    last_outbound = outbound_msgs[-1] if outbound_msgs else None

    if not messages:
        return ("no_outbound_yet", last_inbound, last_outbound, total_inbound,
                 total_outbound, "", None)

    if total_outbound == 0:
        # never messaged them at all (edge case)
        return ("no_outbound_yet", last_inbound, last_outbound, total_inbound,
                 total_outbound, messages[-1].get("direction", ""), messages[-1].get("dateAdded"))

    if total_inbound == 0:
        return ("never_replied", last_inbound, last_outbound, total_inbound,
                 total_outbound, messages[-1].get("direction", ""), messages[-1].get("dateAdded"))

    # We have both outbound + at least one genuine seller reply somewhere.
    last_msg = messages[-1]
    last_is_seller_reply = (last_msg.get("direction") == "inbound"
                             and _is_seller_message(last_msg.get("body")))
    if last_is_seller_reply:
        status = "active_pending_us"
    else:
        status = "replied_then_cold"

    return (status, last_inbound, last_outbound, total_inbound, total_outbound,
            last_msg.get("direction", ""), last_msg.get("dateAdded"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"[leads_audit] pulling all contacts for location {LOCATION_ID} ...")
    all_contacts = list_all_contacts()
    print(f"[leads_audit] total contacts pulled: {len(all_contacts)}")

    target_contacts = []
    unknown_state_count = 0
    for c in all_contacts:
        state = (c.get("state") or "").strip()
        if not state:
            unknown_state_count += 1
            continue
        norm = state.strip().upper()
        if norm == TARGET_STATE.upper() or norm == "OHIO":
            target_contacts.append(c)

    print(f"[leads_audit] {TARGET_STATE} contacts: {len(target_contacts)} "
          f"(unknown-state skipped: {unknown_state_count})")

    rows = []
    errors = []
    status_counts = {}

    for i, c in enumerate(target_contacts, 1):
        cid = c.get("id")
        try:
            messages = full_thread(cid)
            (status, last_in, last_out, n_in, n_out,
             last_dir, last_date_ms) = classify(messages)

            status_counts[status] = status_counts.get(status, 0) + 1

            rows.append({
                "contact_id": cid,
                "name": contact_name(c),
                "phone": c.get("phone") or "",
                "email": c.get("email") or "",
                "city": c.get("city") or "",
                "state": c.get("state") or "",
                "current_tags": ";".join(c.get("tags") or []),
                "last_message_date_iso": iso(last_date_ms),
                "last_message_direction": last_dir,
                "status_category": status,
                "last_inbound_snippet": snippet(last_in.get("body")) if last_in else "",
                "last_outbound_snippet": snippet(last_out.get("body")) if last_out else "",
                "total_inbound_count": n_in,
                "total_outbound_count": n_out,
            })
        except Exception as e:
            errors.append((cid, contact_name(c), str(e)))
            continue

        if i % 25 == 0:
            print(f"[leads_audit] processed {i}/{len(target_contacts)} contacts "
                  f"({api_call_count} api calls so far)...")

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "contact_id", "name", "phone", "email", "city", "state", "current_tags",
            "last_message_date_iso", "last_message_direction", "status_category",
            "last_inbound_snippet", "last_outbound_snippet",
            "total_inbound_count", "total_outbound_count",
        ])
        w.writeheader()
        w.writerows(rows)

    elapsed = time.time() - t0
    print("\n===== SUMMARY =====")
    print(f"Total GHL contacts (all states): {len(all_contacts)}")
    print(f"{TARGET_STATE} contacts found: {len(target_contacts)}")
    print(f"Unknown-state contacts skipped: {unknown_state_count}")
    print("Status breakdown:")
    for k, v in sorted(status_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    print(f"Errored contacts: {len(errors)}")
    for cid, name, err in errors[:50]:
        print(f"  ERROR contact={cid} name={name!r}: {err}")
    print(f"API calls made: {api_call_count}")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"CSV written: {OUT_CSV}")

    return {
        "total_contacts": len(all_contacts),
        "target_contacts": len(target_contacts),
        "unknown_state": unknown_state_count,
        "status_counts": status_counts,
        "errors": errors,
        "api_calls": api_call_count,
        "elapsed": elapsed,
    }


if __name__ == "__main__":
    main()
