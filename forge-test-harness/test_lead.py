#!/usr/bin/env python3
"""test_lead.py — FORGE REI OS live test-lead harness (standalone CLI).

Drive the operator's OWN contact through the wholesale CRM so the whole stack can be
tested end-to-end: reset (delete + recreate) the contact, tag it with the real Scout/Marcus
taxonomy, push it to the pipeline, inspect state, and clean up afterward.

SAFE BY DESIGN:
  • Standalone CLI — NOT a web endpoint. Contact DELETE is never exposed over HTTP.
  • Dry-run by default. Every write/delete needs --confirm, and prints a preview first.
  • Every test contact is stamped with the `forge-test` tag so it's always identifiable.
  • Reads the wholesale GHL creds straight from marcus-wholesale-agent/config/ghl.env.
    The token is never printed.

Usage:
  python3 test_lead.py find     --phone "+1XXXXXXXXXX"
  python3 test_lead.py reset    --phone "+1XXXXXXXXXX" --name "First Last" [--email a@b.com] --confirm
  python3 test_lead.py tag      --phone "+1XXXXXXXXXX" --tags "triage: asap,motivated: high" --confirm
  python3 test_lead.py pipeline --phone "+1XXXXXXXXXX" --stage Hot --confirm
  python3 test_lead.py inbound  --phone "+1XXXXXXXXXX" --text "..." --confirm   # best-effort
  python3 test_lead.py status   --phone "+1XXXXXXXXXX"
  python3 test_lead.py cleanup  --phone "+1XXXXXXXXXX" --confirm
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_CANDIDATES = [
    HERE.parent / "marcus-wholesale-agent" / "config" / "ghl.env",
    Path.home() / "Desktop" / "marcus-wholesale-agent" / "config" / "ghl.env",
]

TEST_TAG = "forge-test"                      # stamps every harness-created contact
BASE_TAGS = [TEST_TAG, "Seller Lead"]
PIPELINE_PREF = "wholesal"                   # mirror scout_triage.PIPELINE_PREF
STAGE_ALIASES = {                            # mirror scout_triage.STAGE_ALIASES
    "hot": "Hot", "warm": "Warm", "follow-up": "Responded", "followup": "Responded",
    "responded": "Responded", "nurture": "Responded", "new": "New Lead",
}
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# ── creds ──────────────────────────────────────────────────────────────────────
def _load_env():
    for p in ENV_CANDIDATES:
        if p.exists():
            cfg = {}
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    cfg[k.strip()] = v.strip()
            return cfg
    sys.exit(f"ERROR: no ghl.env found. Looked in:\n  " +
             "\n  ".join(str(p) for p in ENV_CANDIDATES))


CFG = _load_env()
API_KEY = CFG.get("GHL_API_KEY", "")
LOCATION_ID = CFG.get("GHL_LOCATION_ID", "")
BASE = CFG.get("GHL_BASE_URL", "https://services.leadconnectorhq.com").rstrip("/")
VERSION = CFG.get("GHL_API_VERSION", "2021-07-28")


# ── tiny GHL client (get/post/put/delete) ───────────────────────────────────────
def _req(method, endpoint, params=None, body=None, timeout=30):
    url = f"{BASE}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Version": VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": _UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        raise RuntimeError(f"{method} {endpoint} -> HTTP {e.code}: {detail}") from None


def gget(ep, params=None):
    return _req("GET", ep, params=params)


def gpost(ep, body):
    return _req("POST", ep, body=body)


def gput(ep, body):
    return _req("PUT", ep, body=body)


def gdelete(ep):
    return _req("DELETE", ep)


# ── helpers ──────────────────────────────────────────────────────────────────────
def norm_phone(p):
    """Last 10 digits, for matching."""
    digits = "".join(ch for ch in (p or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def find_contacts(phone):
    """Return contacts whose phone matches (by last-10-digits). Uses /contacts/ query."""
    want = norm_phone(phone)
    out, seen = [], set()
    for q in (phone, want):
        try:
            data = gget("/contacts/", {"locationId": LOCATION_ID, "query": q, "limit": 50})
        except Exception:
            continue
        for c in data.get("contacts", []) or []:
            cid = c.get("id")
            if cid and cid not in seen and norm_phone(c.get("phone")) == want:
                seen.add(cid)
                out.append(c)
    return out


def contact_label(c):
    name = (f"{c.get('firstName') or ''} {c.get('lastName') or ''}").strip() or c.get("contactName") or "(no name)"
    return f"{name} | {c.get('phone')} | id={c.get('id')} | tags={c.get('tags') or []}"


def get_opps(contact_id):
    try:
        d = gget("/opportunities/search", {"location_id": LOCATION_ID, "contact_id": contact_id})
        return d.get("opportunities", []) or []
    except Exception as e:
        print("  (opp lookup failed:", e, ")")
        return []


def resolve_pipeline():
    d = gget("/opportunities/pipelines", {"locationId": LOCATION_ID})
    pls = d.get("pipelines", []) or []
    if not pls:
        raise RuntimeError("no pipelines in GHL")
    pick = next((p for p in pls if PIPELINE_PREF in (p.get("name") or "").lower()), pls[0])
    stages = {(s.get("name") or "").lower(): s.get("id") for s in (pick.get("stages") or [])}
    return pick.get("id"), stages, pick.get("name")


def require_one(phone):
    cs = find_contacts(phone)
    if not cs:
        sys.exit(f"No contact found for {phone}. Run `reset` first.")
    if len(cs) > 1:
        print(f"WARNING: {len(cs)} contacts match {phone}; using the first.")
    return cs[0]


# ── commands ─────────────────────────────────────────────────────────────────────
def cmd_find(a):
    print(f"== GHL location {LOCATION_ID} ({VERSION}) ==")
    # best-effort business SMS number
    try:
        loc = gget(f"/locations/{LOCATION_ID}")
        locobj = loc.get("location") or loc
        num = locobj.get("phone") or "(not exposed via API)"
        print(f"Business number (text sellers from): {num}")
    except Exception:
        print("Business number: (couldn't read /locations — use the number your account texts sellers from)")
    cs = find_contacts(a.phone)
    print(f"\nContacts matching {a.phone}: {len(cs)}")
    for c in cs:
        print("  •", contact_label(c))
        for o in get_opps(c.get("id")):
            print(f"      opp: {o.get('name')} | stage={o.get('pipelineStageId')} | status={o.get('status')}")
        try:
            convs = gget("/conversations/search", {"locationId": LOCATION_ID, "contactId": c.get("id")}).get("conversations", []) or []
            if convs:
                cv = convs[0]
                print(f"      last msg: [{cv.get('lastMessageDirection')}] \"{(cv.get('lastMessageBody') or '')[:80]}\"")
        except Exception:
            pass
    if not cs:
        print("  (none — clean slate)")


def cmd_reset(a):
    cs = find_contacts(a.phone)
    print(f"Found {len(cs)} existing contact(s) for {a.phone}:")
    for c in cs:
        print("  DELETE ->", contact_label(c))
    parts = (a.name or "").split()
    first = parts[0] if parts else "Test"
    last = " ".join(parts[1:]) if len(parts) > 1 else "Lead"
    new_body = {"locationId": LOCATION_ID, "firstName": first, "lastName": last,
                "phone": a.phone, "tags": list(BASE_TAGS), "source": "FORGE test harness"}
    if a.email:
        new_body["email"] = a.email
    print(f"\nCREATE -> {first} {last} | {a.phone} | tags={BASE_TAGS}")
    if not a.confirm:
        print("\n[dry-run] re-run with --confirm to delete the above + create the new contact.")
        return
    for c in cs:
        try:
            gdelete(f"/contacts/{c.get('id')}")
            print("  deleted", c.get("id"))
        except Exception as e:
            print("  DELETE FAILED:", e)
    try:
        res = gpost("/contacts/", new_body)
        cid = (res.get("contact") or res).get("id")
        print("  created contact id:", cid)
    except Exception as e:
        sys.exit(f"CREATE FAILED: {e}")


def cmd_tag(a):
    c = require_one(a.phone)
    tags = [t.strip() for t in (a.tags or "").split(",") if t.strip()]
    if not tags:
        sys.exit("Pass --tags 'tag1,tag2'")
    print(f"Apply to {contact_label(c)}\n  tags -> {tags}")
    if not a.confirm:
        print("[dry-run] add --confirm to write.")
        return
    gpost(f"/contacts/{c.get('id')}/tags", {"tags": tags})
    print("  tags applied.")


def cmd_pipeline(a):
    c = require_one(a.phone)
    pid, stages, pname = resolve_pipeline()
    target = STAGE_ALIASES.get((a.stage or "").lower(), a.stage or "Hot")
    sid = stages.get((target or "").lower())
    if not sid:
        sys.exit(f"stage '{target}' not in pipeline '{pname}'. stages: {list(stages)}")
    print(f"Pipeline '{pname}' -> stage '{target}' for {contact_label(c)}")
    if not a.confirm:
        print("[dry-run] add --confirm to write.")
        return
    opps = get_opps(c.get("id"))
    if opps:
        oid = opps[0].get("id")
        gput(f"/opportunities/{oid}", {"pipelineStageId": sid, "pipelineId": pid})
        print(f"  moved opp {oid} -> {target}")
    else:
        res = gpost("/opportunities/", {"pipelineId": pid, "locationId": LOCATION_ID,
                                        "pipelineStageId": sid, "name": a.name or "FORGE test lead",
                                        "status": "open", "contactId": c.get("id")})
        print("  created opp:", (res.get("opportunity") or res).get("id"))


def cmd_inbound(a):
    """BEST-EFFORT synthetic inbound. GHL usually infers direction from the sender, so this
    may be rejected — if so, just TEXT your GHL number from your phone (the reliable path)."""
    c = require_one(a.phone)
    if not a.confirm:
        print(f"[dry-run] would attempt synthetic inbound for {contact_label(c)}\n  text: {a.text!r}")
        print("  NOTE: best-effort only. Reliable test = text your GHL number from your phone.")
        return
    # ensure a conversation exists
    try:
        convs = gget("/conversations/search", {"locationId": LOCATION_ID, "contactId": c.get("id")}).get("conversations", []) or []
        conv_id = convs[0].get("id") if convs else gpost("/conversations/", {"locationId": LOCATION_ID, "contactId": c.get("id")}).get("conversation", {}).get("id")
    except Exception as e:
        sys.exit(f"conversation lookup/create failed: {e}")
    for body in ({"type": "SMS", "conversationId": conv_id, "message": a.text, "direction": "inbound"},
                 {"type": "SMS", "conversationId": conv_id, "contactId": c.get("id"), "message": a.text}):
        try:
            gpost("/conversations/messages/inbound", body)
            print("  synthetic inbound accepted.")
            return
        except Exception as e:
            print("  attempt failed:", e)
    print("\n>>> Synthetic inbound not supported by this account. TEXT your GHL number from your phone instead.")


def cmd_status(a):
    c = require_one(a.phone)
    print("Contact:", contact_label(c))
    opps = get_opps(c.get("id"))
    for o in opps:
        print("  opp:", o.get("name"), "| stage_id=", o.get("pipelineStageId"), "| status=", o.get("status"))
    if not opps:
        print("  opp: (none)")
    base = a.api_base.rstrip("/")
    print(f"\nLive agent state via {base} (use --api-base http://<box>:7799 for the box):")
    for path, label in (("/api/scout/leads?bucket=asap", "Scout ASAP"),
                        ("/api/marcus/proposals", "Marcus proposals")):
        try:
            with urllib.request.urlopen(f"{base}{path}", timeout=8) as r:
                d = json.loads(r.read().decode())
            items = d.get("leads") or d.get("proposals") or []
            mine = [x for x in items if norm_phone(x.get("phone")) == norm_phone(a.phone)]
            print(f"  {label}: {len(items)} total, {len(mine)} for this contact"
                  + (f" -> {mine[0].get('name')}" if mine else ""))
        except Exception as e:
            print(f"  {label}: (couldn't reach {base} — {e})")


def cmd_cleanup(a):
    cs = find_contacts(a.phone)
    test_cs = [c for c in cs if TEST_TAG in (c.get("tags") or [])]
    print(f"Cleanup {a.phone}: {len(cs)} matched, {len(test_cs)} tagged '{TEST_TAG}':")
    for c in cs:
        mark = "DELETE" if TEST_TAG in (c.get("tags") or []) else "SKIP (not a test contact)"
        print(f"  {mark} ->", contact_label(c))
    if not a.confirm:
        print("\n[dry-run] add --confirm to delete the test contact(s). Only forge-test-tagged are removed.")
        return
    for c in test_cs:
        for o in get_opps(c.get("id")):
            try:
                gdelete(f"/opportunities/{o.get('id')}")
            except Exception as e:
                print("  opp delete failed:", e)
        try:
            gdelete(f"/contacts/{c.get('id')}")
            print("  deleted", c.get("id"))
        except Exception as e:
            print("  delete failed:", e)


def main():
    if not (API_KEY and LOCATION_ID):
        sys.exit("ERROR: GHL_API_KEY / GHL_LOCATION_ID missing from ghl.env")
    ap = argparse.ArgumentParser(description="FORGE REI OS test-lead harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("find", "reset", "tag", "pipeline", "inbound", "status", "cleanup"):
        sp = sub.add_parser(name)
        sp.add_argument("--phone", required=True)
        sp.add_argument("--name", default="")
        sp.add_argument("--email", default="")
        sp.add_argument("--tags", default="")
        sp.add_argument("--stage", default="Hot")
        sp.add_argument("--text", default="")
        sp.add_argument("--api-base", default="http://localhost:7799")
        sp.add_argument("--confirm", action="store_true")
    a = ap.parse_args()
    {"find": cmd_find, "reset": cmd_reset, "tag": cmd_tag, "pipeline": cmd_pipeline,
     "inbound": cmd_inbound, "status": cmd_status, "cleanup": cmd_cleanup}[a.cmd](a)


if __name__ == "__main__":
    main()
