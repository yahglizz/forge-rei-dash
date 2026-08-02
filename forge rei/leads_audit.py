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
# Dead-end classifiers — ported verbatim from marcus_engine.py (DNC keywords:
# _fallback_classify lines 76; soft_no: 238-250; hard_no: 257-267; opt_out: 328-371;
# denial: 272-363). A "STOP"/"not interested"/"sold"/wrong-number reply is a genuine
# seller message but must NEVER be treated as a re-engage-worthy or pending-response
# lead — re-texting these is a compliance risk (DNC) or just wasted/annoying outreach.
# ---------------------------------------------------------------------------
_DNC_PHRASES = ["stop", "unsubscribe", "remove me", "do not text"]

_SOFT_NO_PHRASES = [
    "not for sale", "not selling", "not interested", "no longer selling",
    "not looking to sell", "not gonna sell", "not going to sell", "won't sell",
    "wont sell", "not right now", "not at this time",
    "not at the moment", "maybe later", "not the right time",
    "not ready to sell", "decided not to sell", "changed my mind",
    "keeping the house", "keeping the property",
]

_HARD_NO_RE = re.compile(
    r"^\s*(no+|nope|nah+|no\s*thanks?|no\s*thank\s*you|not\s*interested"
    r"|no\s*i'?m?\s*good|no\s*sorry|sorry\s*no|not\s*for\s*me|no\s*thx)"
    r"[\s.!?,'\"\-]*$",
    re.IGNORECASE,
)

_OPT_OUT_PHRASES = [
    "remove my number", "take me off", "off your list", "off your website",
    "leave me alone", "stop bothering", "stop contacting", "stop messaging",
    "stop texting me", "quit texting", "quit calling", "quit contacting",
    "harassing me", "this is harassment",
]

_DENIAL_CLAUSE = (
    r"(?:"
    r"i\s+(?:do\s+not|don'?t)\s+know\s+you"
    r"|(?:(?:(?:i\s+(?:think|believe)\s+)?you\s+(?:have|got)"
    r"|you(?:'ve|ve)\s+got|this\s+is|it(?:'?s|\s+is))\s+)?"
    r"(?:the\s+)?wrong\s+"
    r"(?:number|person|contact|recipient|owner|seller)"
    r"|(?:i(?:'?m|\s+am)\s+)?not\s+who\s+you\s+think(?:\s+i\s+am)?"
    r"|(?:i(?:'?m|\s+am)\s+)?not\s+(?:the\s+person\s+)?"
    r"who\s+you(?:'?re|\s+are)\s+looking\s+for"
    r")"
)
_DENIAL_MESSAGE_RE = re.compile(
    rf"^\s*(?:sorry(?:\s*[,;:-]\s*(?:but\s+)?|\s+but\s+|\s+))?"
    rf"{_DENIAL_CLAUSE}"
    rf"(?:\s*[,;.!-]+\s*{_DENIAL_CLAUSE})*\s*[.!?]*\s*$",
    re.IGNORECASE,
)
_STANDALONE_DENIAL_RE = re.compile(
    r"^\s*(?:"
    r"did\s+i\s+call\s+you|did\s+you\s+call\s+me|you\s+called\s+me|"
    r"i\s+(?:did\s+not|didn'?t)\s+call\s+you|"
    r"(?:i\s+)?never\s+(?:called|talked\s+to|spoke\s+to)\s+you|"
    r"who\s+dis|who(?:'?s|\s+is)\s+this|who\s+are\s+you|what\s+is\s+this"
    r")\s*[?.!,]*(?:\s*(?:no+|nope|nah+))?\s*[?.!,]*$",
    re.IGNORECASE,
)
_IDENTITY_DENIAL_RE = re.compile(
    r"^\s*(?:"
    r"(?:i\s*am|i'?m)\s+not\s+(?:the\s+)?(?:owner|seller)(?:\s+anymore)?"
    r"|i\s+(?:do\s+not|don'?t)\s+own\s+"
    r"(?:it|this|that|the\s+(?:house|home|property))(?:\s+anymore)?"
    r"|(?:i(?:'ve|\s+have)?\s+)?never\s+owned\s+"
    r"(?:it|this|that|the\s+(?:house|home|property))"
    r"|(?:this|that)(?:\s+is\s+not|\s+isn'?t|'?s\s+not)\s+"
    r"(?:me|my\s+(?:house|home|property))(?:\s+anymore)?"
    r")(?=\s*(?:[.!?]+(?:\s|$)|$))",
    re.IGNORECASE,
)


def _is_dnc(body):
    b = (body or "").lower()
    return any(p in b for p in _DNC_PHRASES)


def _is_opt_out(body):
    b = (body or "").lower()
    return any(p in b for p in _OPT_OUT_PHRASES)


def _is_soft_no(body):
    b = (body or "").lower()
    return any(p in b for p in _SOFT_NO_PHRASES)


def _is_hard_no(body):
    return bool(_HARD_NO_RE.match(body or ""))


def _is_denial(body):
    if _DENIAL_MESSAGE_RE.match(body or ""):
        return True
    if _STANDALONE_DENIAL_RE.match(body or ""):
        return True
    if _IDENTITY_DENIAL_RE.search(body or ""):
        return True
    return False


# NOT ported from existing code — no "already sold" classifier exists anywhere in
# marcus_engine.py/scout_triage.py today (verified by grep). Added here for this audit
# only, narrow standalone-message match so it can't misfire inside a longer reply. Flag
# to the operator: worth backporting into marcus_engine.py's real dead-end detection.
_SOLD_RE = re.compile(
    r"^\s*(?:(?:it'?s|its|already|house\s+is|home\s+is|property\s+is)\s+)?sold[\s.!?]*$",
    re.IGNORECASE,
)


def _is_sold(body):
    return bool(_SOLD_RE.match((body or "").strip()))


def _dead_end_reason(body):
    """Priority order: compliance-grade first (DNC/opt-out never expire), then
    content-based dead ends. None means the message is a live, actionable seller reply."""
    if body is None:
        return None
    if _is_dnc(body):
        return "dnc"
    if _is_opt_out(body):
        return "opt_out"
    if _is_denial(body):
        return "wrong_number"
    if _is_sold(body):
        return "sold"
    if _is_hard_no(body):
        return "hard_no"
    if _is_soft_no(body):
        return "soft_no"
    return None


def _to_ms(v):
    """Normalize a GHL timestamp (epoch int/str OR ISO-8601 string) to epoch ms, or None.
    Ported from scout_triage.py:_to_ms — GHL is inconsistent: conversation
    lastMessageDate is epoch-ms, but message dateAdded (what /messages actually
    returns) is an ISO-8601 string. Ignoring this would silently sort/format wrong."""
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


REAL_MESSAGE_TYPES = {"TYPE_SMS"}  # GHL also returns TYPE_ACTIVITY_CONTACT etc. (system
# log lines like "DnD enabled by customer" / "Opportunity created" / "Tag added") mixed
# into /messages with real direction+body fields — those are NOT texts and must be
# dropped before classification, confirmed via live sample pull 2026-08-01.


def full_thread(contact_id):
    """All real SMS messages across all conversations for a contact, chronological
    (oldest first). Non-SMS system activity-log entries are filtered out."""
    all_msgs = []
    for conv in list_conversations(contact_id):
        conv_id = conv.get("id")
        if not conv_id:
            continue
        msgs = get_messages(conv_id)
        all_msgs.extend(m for m in msgs if m.get("messageType") in REAL_MESSAGE_TYPES)
    all_msgs.sort(key=lambda m: _to_ms(m.get("dateAdded")) or 0)
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


def iso(v):
    ms = _to_ms(v)
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
                "address1": c.get("address1") or "",
                "city": c.get("city") or "",
                "state": c.get("state") or "",
                "postal_code": c.get("postalCode") or "",
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
            "contact_id", "name", "phone", "email", "address1", "city", "state",
            "postal_code", "current_tags",
            "last_message_date_iso", "last_message_direction", "status_category",
            "last_inbound_snippet", "last_outbound_snippet",
            "total_inbound_count", "total_outbound_count",
        ])
        w.writeheader()
        w.writerows(rows)

    # ---- Dedup pass: same property/seller often has 2 GHL contacts (2 phone numbers
    # imported separately, e.g. "ohio 1 st number" / "ohio second number" tags). Group by
    # normalized property address (falls back to name when address is blank) and collapse
    # to ONE row per real-world lead, keeping the strongest signal across duplicates.
    STATUS_RANK = {"active_pending_us": 3, "replied_then_cold": 2, "never_replied": 1,
                   "no_outbound_yet": 0}

    def dedup_key(row):
        addr = (row["address1"] or "").strip().lower()
        if addr:
            return f"addr:{addr}|{row['postal_code']}"
        return f"name:{row['name'].strip().lower()}"

    groups = {}
    for row in rows:
        groups.setdefault(dedup_key(row), []).append(row)

    deduped = []
    for key, group in groups.items():
        best = max(group, key=lambda r: STATUS_RANK.get(r["status_category"], -1))
        merged = dict(best)
        merged["duplicate_contact_ids"] = ";".join(
            r["contact_id"] for r in group if r["contact_id"] != best["contact_id"])
        merged["duplicate_count"] = len(group) - 1
        deduped.append(merged)

    dedup_csv = os.path.join(OUT_DIR, "ohio_leads_audit_deduped.csv")
    with open(dedup_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "contact_id", "name", "phone", "email", "address1", "city", "state",
            "postal_code", "current_tags",
            "last_message_date_iso", "last_message_direction", "status_category",
            "last_inbound_snippet", "last_outbound_snippet",
            "total_inbound_count", "total_outbound_count",
            "duplicate_contact_ids", "duplicate_count",
        ])
        w.writeheader()
        w.writerows(deduped)

    dedup_status_counts = {}
    for row in deduped:
        dedup_status_counts[row["status_category"]] = (
            dedup_status_counts.get(row["status_category"], 0) + 1)

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
    print(f"Raw CSV written: {OUT_CSV}")
    print()
    print(f"===== DEDUPED (by property address, name fallback) =====")
    print(f"Unique leads after collapsing duplicate contacts: {len(deduped)} "
          f"(raw rows: {len(rows)}, {len(rows) - len(deduped)} were duplicates)")
    for k, v in sorted(dedup_status_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    print(f"Deduped CSV written: {dedup_csv}")

    return {
        "total_contacts": len(all_contacts),
        "target_contacts": len(target_contacts),
        "unknown_state": unknown_state_count,
        "status_counts": status_counts,
        "dedup_status_counts": dedup_status_counts,
        "dedup_total": len(deduped),
        "errors": errors,
        "api_calls": api_call_count,
        "elapsed": elapsed,
    }


if __name__ == "__main__":
    main()
