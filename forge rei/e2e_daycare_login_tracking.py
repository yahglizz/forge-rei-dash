#!/usr/bin/env python3
"""Live E2E for spec 2026-10-06: Create login / sibling link / Resend / after-hours queue /
App Tracking. QA center 9999 ONLY, zztest names, fictional 555-01xx phones. Never prints a
PIN or a key. IDs it creates go to $E2E_IDS (JSON) for the morning check + SQL cleanup.

  DASH=http://localhost:7799 python3 e2e_daycare_login_tracking.py run       # any hour
  DASH=http://localhost:7799 python3 e2e_daycare_login_tracking.py morning   # after 8:05 ET
  DASH=http://localhost:7799 python3 e2e_daycare_login_tracking.py orphan    # after the SQL unlink
  DASH=http://localhost:7799 python3 e2e_daycare_login_tracking.py clean-ghl
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

DASH = os.environ.get("DASH", "http://localhost:7799")
IDS = Path(os.environ.get("E2E_IDS", "e2e_login_ids.json"))
QA = "99999999-9999-9999-9999-999999999999"
ENV = {}
for line in (Path.home() / "forge rei dash/forge-daycare/config/daycare.env").read_text().splitlines():
    if re.match(r"^[A-Z_]+=", line):
        k, v = line.split("=", 1)
        ENV[k] = v.strip().strip('"').strip("'")
GHL, LOCID = ENV["GHL_API_KEY"], ENV["GHL_LOCATION_ID"]
SB = ENV.get("DAYCARE_SUPABASE_URL") or ENV.get("SUPABASE_URL") or ENV.get("NEXT_PUBLIC_SUPABASE_URL")
ANON = (ENV.get("DAYCARE_SUPABASE_PUBLISHABLE_KEY") or ENV.get("SUPABASE_ANON_KEY")
        or ENV.get("NEXT_PUBLIC_SUPABASE_ANON_KEY"))
fails = 0
jar = {}


def ok(cond, msg):
    global fails
    print(("PASS  " if cond else "FAIL  ") + msg, flush=True)
    fails += 0 if cond else 1
    return cond


def http(method, url, body=None, headers=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            if r.headers.get("Set-Cookie"):
                jar["c"] = r.headers["Set-Cookie"].split(";")[0]
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else {}
        except ValueError:
            return e.code, {}


def dash(method, path, body=None):
    return http(method, DASH + path, body, {"Origin": DASH, **({"Cookie": jar["c"]} if "c" in jar else {})})


def ghl(method, path, body=None):
    return http(method, "https://services.leadconnectorhq.com" + path, body,
                {"Authorization": f"Bearer {GHL}", "Version": "2021-07-28", "User-Agent": "atob-e2e/1.0"})


def slug(v):
    v = "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", v.lower()))


def signs_in(login_id, pin):
    if not (login_id and pin):
        return False
    s, _ = http("POST", f"{SB}/auth/v1/token?grant_type=password",
                {"email": f"{slug(login_id)}@login.blessings.app", "password": pin}, {"apikey": ANON})
    return s == 200


def login():
    s, _ = dash("POST", "/api/daycare/auth/test-login", {"profile": "admin"})
    return ok(s == 200, "dashboard admin session (tunnel)")


def contact(tag, run, n):
    phone = f"+12155550{120 + (int(run) + n) % 80:03d}"
    s, c = ghl("POST", "/contacts/upsert", {"locationId": LOCID, "firstName": "Zztest", "lastName": f"{tag}{run}",
                                            "phone": phone, "email": f"zztest.{tag.lower()}.{run}@example.com"})
    cid = (c.get("contact") or {}).get("id", "")
    ok(bool(cid), f"GHL test contact {tag} {cid}")
    return cid, phone


def family(cid, phone, run, tag, child):
    return {"contact_id": cid, "card_id": cid, "location_id": QA, "enrolled": True,
            "child_first": "Zztest", "child_last": f"{child}{run}", "child_dob": "2022-04-04",
            "parent_first": "Zzparent", "parent_last": f"{tag}{run}",
            "email": f"zztest.{tag.lower()}.{run}@example.com", "phone": phone}


def outbound_pin_texts(cid, since):
    s, conv = ghl("GET", f"/conversations/search?locationId={LOCID}&contactId={cid}")
    convs = conv.get("conversations") or []
    if not convs:
        return 0
    s, m = ghl("GET", f"/conversations/{convs[0]['id']}/messages")
    msgs = ((m.get("messages") or {}).get("messages")) or []
    return sum(1 for x in msgs if x.get("direction") == "outbound" and "PIN:" in str(x.get("body") or "")
               and time.mktime(time.strptime(str(x.get("dateAdded"))[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone >= since - 120)


def run():
    ids = {"run": str(int(time.time()))[-6:], "contacts": [], "started": time.time()}
    r = ids["run"]
    if not login():
        return
    # 1. Create login, child A (parent P)
    cp, php = contact("Login", r, 0)
    ids["contacts"].append(cp)
    fam = family(cp, php, r, "Login", "Alpha")
    s, a = dash("POST", "/api/daycare/ghl/enroll", {"family": fam})
    pa = a.get("provision") or {}
    ok(s == 200 and bool(pa.get("pin")), f"Create login A: login + PIN returned ({s} {a.get('error', '')})")
    texted = pa.get("texted") or {}
    night = bool(texted.get("queued"))
    ok(texted.get("ok") or night, f"login text sent via GHL or queued for 8am ({ 'queued' if night else texted })")
    ok(signs_in(pa.get("login_id"), pa.get("pin")), "PIN A signs in to the app")
    ids.update({"parent_a": pa.get("profile_id"), "login_a": pa.get("login_id"), "child_a": (a.get("child") or {}).get("id")})
    # 2. Sibling B links, no new PIN
    s, b = dash("POST", "/api/daycare/ghl/enroll", {"family": {**fam, "card_id": cp + "#1", "child_last": f"Bravo{r}"}})
    pb = b.get("provision") or {}
    ok(s == 200 and pb.get("linked") and not pb.get("pin"), f"Create login B: linked to A's login, no new PIN ({pb})")
    ok(signs_in(pa.get("login_id"), pa.get("pin")), "PIN A still signs in after the sibling")
    ids["child_b"] = (b.get("child") or {}).get("id")
    # 3. Resend
    s, rs = dash("POST", "/api/daycare/guardian/resend-login", {"profile_id": pa.get("profile_id"), "location_id": QA})
    pr = rs.get("provision") or {}
    if rs.get("queued"):
        ok(s == 200, "Resend after 9pm → queued for 8am (force entry)")
        ids["resend_queued"] = True
    else:
        ok(s == 200 and bool(pr.get("pin")), f"Resend: fresh PIN ({s} {rs.get('error', '')})")
        ok((pr.get("texted") or {}).get("ok"), f"Resend texted through GHL ({pr.get('texted')})")
        ok(signs_in(pr.get("login_id"), pr.get("pin")) and not signs_in(pa.get("login_id"), pa.get("pin")),
           "new PIN works, old PIN dead")
    # 4. Already-linked child
    s, again = dash("POST", "/api/daycare/ghl/enroll", {"family": fam})
    ok(s == 200 and again.get("already_linked"), f"re-click on a linked child → already_linked ({s})")
    # 5. A never-signed-in family E (the 8am queue's real send path when run at night)
    ce, phe = contact("Queue", r, 7)
    ids["contacts"].append(ce)
    s, e = dash("POST", "/api/daycare/ghl/enroll", {"family": family(ce, phe, r, "Queue", "Echo")})
    pe = e.get("provision") or {}
    ok(s == 200 and bool(pe.get("pin")), "Create login E (never signs in)")
    ids.update({"parent_e": pe.get("profile_id"), "login_e": pe.get("login_id"),
                "child_e": (e.get("child") or {}).get("id"), "contact_e": ce})
    # E's night PIN must be re-checked at 8am (it must die), so it rides in the ids file:
    # scratch only, chmod 600, deleted at cleanup. A QA-center test account, never a family.
    ids["pin_e"] = pe.get("pin")
    # 6. Queue view
    s, v = dash("GET", "/api/daycare/login-queue")
    queued = {q.get("profile_id") for q in v.get("queued", [])}
    if night:
        ok(pe.get("profile_id") in queued, "night: family E is in the 8am queue")
    else:
        ok(pe.get("profile_id") not in queued, "day: nothing queued for E (texted now)")
    # 7. App Tracking
    s, _ = dash("GET", "/api/daycare/app-tracking?center=9999")
    ok(s == 400, "App Tracking refuses the QA center")
    for code in ("921", "2318", "1923"):
        s, t = dash("GET", f"/api/daycare/app-tracking?center={code}")
        ok(s == 200 and "totals" in (t.get("tracking") or {}), f"App Tracking {code} answers")
    IDS.write_text(json.dumps(ids))
    os.chmod(IDS, 0o600)
    print("IDS", json.dumps({k: v for k, v in ids.items() if k != "pin_e"}))


def morning():
    ids = json.loads(IDS.read_text())
    if not login():
        return
    s, v = dash("GET", "/api/daycare/login-queue")
    queued = {q.get("profile_id") for q in v.get("queued", [])}
    ok(ids["parent_e"] not in queued and ids["parent_a"] not in queued, "8am: queue drained for A and E")
    outcomes = {d["profile_id"]: d["outcome"] for d in v.get("done", [])}
    print("INFO  outcomes", json.dumps({k: outcomes.get(ids[k]) for k in ("parent_a", "parent_e")}))
    ok(outcomes.get(ids["parent_e"]) == "sent", "E: fresh PIN texted at 8am")
    ok(not signs_in(ids["login_e"], ids["pin_e"]), "E: the night PIN no longer works (fresh one was minted)")
    ok(outbound_pin_texts(ids["contact_e"], ids["started"]) >= 1, "E: GHL conversation has the PIN text")
    if ids.get("resend_queued"):
        ok(outcomes.get(ids["parent_a"]) == "sent", "A: queued Resend (force) texted at 8am")


def orphan():
    """After SQL unlinked child E from its never-signed-in parent: a link_only re-click must
    re-issue a PIN (the orphan rule), not claim the old one works."""
    ids = json.loads(IDS.read_text())
    if not login():
        return
    r = ids["run"]
    fam = family(ids["contact_e"], "", r, "Queue", "Echo")
    s, o = dash("POST", "/api/daycare/ghl/enroll", {"family": {**fam, "phone": "+12155550199"}})
    po = o.get("provision") or {}
    ok(s == 200 and bool(po.get("pin")) and not po.get("linked"), f"orphan login → PIN re-issued ({s} {sorted(po)})")


def clean_ghl():
    ids = json.loads(IDS.read_text())
    for cid in ids.get("contacts", []):
        s, _ = ghl("DELETE", f"/contacts/{cid}")
        print(f"CLEAN GHL contact {cid} ({s})")


if __name__ == "__main__":
    {"run": run, "morning": morning, "orphan": orphan, "clean-ghl": clean_ghl}[sys.argv[1] if len(sys.argv) > 1 else "run"]()
    print("\nALL PASS" if not fails else f"\n{fails} FAILED")
    raise SystemExit(1 if fails else 0)
