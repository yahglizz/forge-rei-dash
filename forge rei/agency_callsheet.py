"""agency_callsheet.py — Call Sheet: CRM-style lead tracker (Forge AI Agency).

Owner uploads a PDF (or pastes text) of business leads; it becomes a table of
businesses tracked per-row (new / answered / no_answer / callback / dead, plus the
lifecycle ready / demo_booked / proposal / won / lost / dnc).
Marking answered/no_answer also bumps the existing daily tally in
agency_calls.py (log_call) — internal + reversible, mirrors agency_calls.py's
store idiom (forge_atomic + _LOCK + _load/_save).
"""
import base64
import json
import re
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import forge_atomic

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_callsheet.json"
_LOCK = threading.Lock()

STATUSES = ("new", "answered", "interested", "no_answer", "callback", "dead",
            "bad_number", "ready", "demo_booked", "proposal", "won", "lost", "dnc")
# Out of every call queue for good (until the operator re-marks the row).
TERMINAL = ("dnc", "won", "lost", "dead", "bad_number")
# Rows that are in the queue with no callbackAt set.
QUEUED = ("new", "ready", "callback", "interested")

# Fields the operator can edit inline in the sheet grid. callbackAt is validated ISO.
EDITABLE = {"note": 300, "pain": 200, "nextAction": 200, "category": 60, "callbackAt": 40}
# Lifecycle fields added 2026-09-22 — old rows get these defaults on read.
DEFAULTS = {"callbackAt": "", "attempts": 0, "lastContactAt": "", "nextAction": "",
            "category": ""}

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
_PDF_RE = re.compile(r"^data:application/pdf;base64,(.+)$", re.S)

_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_WEBSITE_RE = re.compile(r"(?:www\.|https?://)\S+")


def _load():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text())
            if isinstance(d, dict) and isinstance(d.get("leads"), list):
                d.setdefault("seq", 0)
                d.setdefault("dnc", [])  # normalized phones that never re-import
                return d
        except Exception:
            pass
    return {"seq": 0, "leads": [], "dnc": []}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _norm_phone(p):
    return re.sub(r"\D", "", str(p or ""))


def _now():
    return datetime.now(timezone.utc)


def _when(iso):
    """ISO string → aware datetime (naive = server-local), or None."""
    try:
        dt = datetime.fromisoformat(str(iso or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def is_due(lead, now=None):
    """Is this row in today's call queue? Terminal rows never are; a callbackAt hides the
    row until it comes due; otherwise only new/ready/callback/interested rows queue."""
    if lead.get("status") in TERMINAL:
        return False
    cb = _when(lead.get("callbackAt")) if lead.get("callbackAt") else None
    if cb:
        return cb <= (now or _now())
    return (lead.get("status") or "new") in QUEUED


def call_queue(leads, now=None):
    now = now or _now()
    return [l for l in leads if is_due(l, now)]


def _dupe_key(lead):
    phone = _norm_phone(lead.get("phone"))
    if phone:
        return ("phone", phone)
    return ("name", str(lead.get("name", "")).lower(), str(lead.get("company", "")).lower())


def _add_leads(d, incoming):
    """Internal — lock must already be held. Skips dupes, assigns ids. Returns count added."""
    existing = {_dupe_key(l) for l in d["leads"]}
    blocked = set(d.get("dnc") or []) | {_norm_phone(l.get("phone")) for l in d["leads"]
                                         if l.get("status") == "dnc"}
    blocked.discard("")
    added = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for lead in incoming:
        key = _dupe_key(lead)
        if key in existing or _norm_phone(lead.get("phone")) in blocked:
            continue
        existing.add(key)
        d["seq"] += 1
        d["leads"].append({
            "id": f"L{d['seq']}",
            "name": lead.get("name", ""),
            "company": lead.get("company", ""),
            "phone": lead.get("phone", ""),
            "email": lead.get("email", ""),
            "website": lead.get("website", ""),
            "location": lead.get("location", ""),
            "pain": str(lead.get("pain", "") or "")[:200],
            "status": "new",
            "note": "",
            "added": now,
            "last_called": "",
            **DEFAULTS,
            "category": str(lead.get("category", "") or "")[:60],
        })
        added += 1
    return added


def list_leads():
    with _LOCK:
        d = _load()
        leads = [dict(DEFAULTS, **l) for l in d["leads"]]
    now = _now()
    for l in leads:
        l["due"] = is_due(l, now)
    counts = {s: 0 for s in STATUSES}
    for l in leads:
        counts[l.get("status", "new")] = counts.get(l.get("status", "new"), 0) + 1
    counts["total"] = len(leads)
    counts["due"] = sum(1 for l in leads if l["due"])
    return {"ok": True, "leads": leads, "counts": counts}


def _leads_from_ai(text):
    import review_agent
    key = review_agent._api_key()
    if not key:
        return None
    system = (
        "Extract business leads from raw text. Output ONLY a JSON array of "
        "objects with keys name, company, phone, email, website, location, pain, "
        "category (business type, e.g. dentist) "
        "(empty string when unknown). No commentary, no markdown fences.\n"
        "`pain` is the ONE specific, concrete problem with this business's web "
        "presence that the caller opens with — carry it over verbatim if the "
        "source already states one (a pain/pain_point/pitch/angle/notes column). "
        "If the source does NOT state one, you may only write a pain that the row "
        "itself proves — e.g. the website field says none/no website -> 'No website "
        "at all, just a Facebook page'. NEVER invent or guess a pain: leave it "
        "empty. An empty pain is correct; a made-up one gets said out loud on a "
        "real call."
    )
    reply = review_agent._claude(key, system, text[:12000], max_tokens=4000)
    start = reply.index("[")
    end = reply.rindex("]")
    rows = json.loads(reply[start:end + 1])
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lead = {k: str(row.get(k, "") or "").strip() for k in
                 ("name", "company", "phone", "email", "website", "location", "pain",
                  "category")}
        if lead["name"] or lead["phone"]:
            out.append(lead)
    return out


def _leads_from_regex(text):
    out = []
    for line in text.splitlines():
        m = _PHONE_RE.search(line)
        if not m:
            continue
        phone = m.group(0)
        em = _EMAIL_RE.search(line)
        email = em.group(0) if em else ""
        wm = _WEBSITE_RE.search(line)
        website = wm.group(0) if wm else ""
        name = line.replace(phone, "")
        if email:
            name = name.replace(email, "")
        if website:
            name = name.replace(website, "")
        name = re.sub(r"\s+", " ", name).strip()[:60]
        if not name and not phone:
            continue
        out.append({"name": name, "company": "", "phone": phone, "email": email,
                     "website": website, "location": "", "pain": ""})
    return out


def _leads_from_text(text, use_ai=True):
    if use_ai:
        try:
            rows = _leads_from_ai(text)
            if rows is not None:
                return rows
        except Exception:
            pass
    return _leads_from_regex(text)


def import_text(text, use_ai=True):
    text = str(text or "")
    incoming = _leads_from_text(text, use_ai=use_ai)
    with _LOCK:
        d = _load()
        added = _add_leads(d, incoming)
        _save(d)
    out = list_leads()
    out["added"] = added
    out["skipped"] = len(incoming) - added
    return out


def _extract_pdf_text(blob):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(blob)
        tmp = f.name
    try:
        try:
            import pypdf
            reader = pypdf.PdfReader(tmp)
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except ImportError:
            pass
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(tmp)
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except ImportError:
            pass
        try:
            res = subprocess.run(["pdftotext", tmp, "-"], capture_output=True, timeout=30)
            if res.returncode == 0:
                return res.stdout.decode("utf-8", "ignore")
        except Exception:
            pass
        return None
    finally:
        try:
            Path(tmp).unlink()
        except Exception:
            pass


def import_pdf(data_url, use_ai=True):
    m = _PDF_RE.match(str(data_url or "").strip())
    if not m:
        return {"ok": False, "detail": "Upload a PDF file."}
    try:
        blob = base64.b64decode(m.group(1), validate=True)
    except Exception:
        return {"ok": False, "detail": "That file didn't decode — re-pick it and try again."}
    if not blob:
        return {"ok": False, "detail": "Empty file."}
    if len(blob) > MAX_PDF_BYTES:
        return {"ok": False, "detail": "File too big — keep it under 10 MB."}

    try:
        text = _extract_pdf_text(blob)
    except Exception as e:
        return {"ok": False, "detail": f"Couldn't read that PDF: {e}"}
    if text is None:
        return {"ok": False, "detail": "PDF support missing — run: pip3 install pypdf"}
    if len(text.strip()) < 20:
        return {"ok": False, "detail": "Couldn't read any text in that PDF (is it a scan?)."}

    return import_text(text, use_ai=use_ai)


def set_status(lead_id, status):
    if status not in STATUSES:
        return {"ok": False, "detail": "status must be one of " + ", ".join(STATUSES)}
    tally_outcome = None
    with _LOCK:
        d = _load()
        for lead in d["leads"]:
            if lead["id"] == lead_id:
                prev = lead.get("status")
                lead["status"] = status
                phone = _norm_phone(lead.get("phone"))
                dnc = d.setdefault("dnc", [])
                if status == "dnc" and phone and phone not in dnc:
                    dnc.append(phone)
                elif prev == "dnc" and status != "dnc" and phone in dnc:
                    dnc.remove(phone)  # operator un-marked it — reversible
                if status in ("answered", "interested", "no_answer", "callback",
                              "bad_number"):
                    lead["last_called"] = datetime.now().strftime("%m/%d %H:%M")
                # bad_number stays out of the tally on purpose: a disconnected
                # line is a list-quality problem, not a dial you can improve on.
                if status in ("answered", "interested"):
                    tally_outcome = "answered"
                elif status == "no_answer":
                    tally_outcome = "no_answer"
                if tally_outcome:
                    now = _now()
                    lead["attempts"] = int(lead.get("attempts") or 0) + 1
                    lead["lastContactAt"] = now.isoformat(timespec="seconds")
                    cb = _when(lead.get("callbackAt")) if lead.get("callbackAt") else None
                    if cb and cb <= now:
                        lead["callbackAt"] = ""  # the due callback just got made
                break
        else:
            return {"ok": False, "detail": "Lead not found."}
        _save(d)
    if tally_outcome:
        try:
            import agency_calls
            agency_calls.log_call(tally_outcome)
        except Exception:
            pass
    return list_leads()


def set_note(lead_id, note, field="note"):
    """Inline cell edit. field defaults to "note" so the original call shape still works."""
    field = field if field in EDITABLE else "note"
    value = str(note or "").strip()[:EDITABLE[field]]
    if field == "callbackAt" and value:
        when = _when(value)
        if not when:
            return {"ok": False, "detail": "callbackAt must be an ISO date/time."}
        value = when.astimezone(timezone.utc).isoformat(timespec="seconds")
    with _LOCK:
        d = _load()
        for lead in d["leads"]:
            if lead["id"] == lead_id:
                lead[field] = value
                _save(d)
                return {"ok": True}
    return {"ok": False, "detail": "Lead not found."}


def _escalate_one_time(offer, info):
    """The one-time build/setup charge, as a number.

    A monthly offer carries its build price separately (free today — see
    `agency-offer-sheet.md`). A one-time offer IS the build. Either way this has
    to be a number, because a build stored only as a sentence in `plan` was
    revenue nothing could count.
    """
    if offer:
        if offer.get("monthly"):
            return float(offer.get("buildPrice", 0) or 0)
        return float(offer.get("price", 0) or 0)
    try:
        return max(0.0, float(info.get("oneTime") or 0))
    except (TypeError, ValueError):
        return 0.0


def _escalate_notes(lead, info):
    """Build the client-book note: contact info the client record has no field for,
    plus what they actually said on the call."""
    lines = []
    phone = str(info.get("phone") or lead.get("phone") or "").strip()
    email = str(info.get("email") or lead.get("email") or "").strip()
    if phone:
        lines.append(f"Phone: {phone}")
    if email:
        lines.append(f"Email: {email}")
    loc = str(lead.get("location") or "").strip()
    if loc:
        lines.append(f"Location: {loc}")
    pain = str(info.get("pain") or lead.get("pain") or "").strip()
    if pain:
        lines.append(f"Pain point: {pain}")
    offer = info.get("_offer")
    if offer:
        import agency_offers
        lines.append(f"Offer quoted: {agency_offers.line(offer)}")
        if offer.get("includes"):
            lines.append(f"  includes: {offer['includes']}")
    nxt = str(info.get("next_step") or "").strip()
    if nxt:
        lines.append(f"Next step: {nxt}")
    said = str(info.get("notes") or "").strip()
    if said:
        lines.append(f"Said on the call: {said}")
    lines.append(f"Source: cold call ({datetime.now().strftime('%Y-%m-%d')}), call sheet {lead.get('id')}")
    return "\n".join(lines)[:2000]


def escalate(lead_id, info):
    """Interested → create (or refresh) a Pipeline lead in the agency client book.

    Internal + reversible (delete the client row to undo) — nothing is texted,
    emailed, or published, so this stays inside CLAUDE.md rule 2.
    """
    info = info if isinstance(info, dict) else {}
    with _LOCK:
        d = _load()
        snapshot = next((dict(l) for l in d["leads"] if l["id"] == lead_id), None)
    if snapshot is None:
        return {"ok": False, "detail": "Lead not found."}

    name = str(info.get("name") or snapshot.get("name") or snapshot.get("company") or "").strip()
    if not name:
        return {"ok": False, "detail": "Who did you talk to? A contact name is required."}

    import agency_offers
    offer = agency_offers.normalize(info.get("offer"))
    info = dict(info, _offer=offer)

    services = info.get("services") if isinstance(info.get("services"), list) else []
    if offer and offer.get("service") and offer["service"] not in services:
        services = services + [offer["service"]]

    # A one-time build is NOT recurring revenue — only a monthly offer sets mrr,
    # or the Pipeline/MRR tiles would read a $1,100 site as $1,100/mo forever.
    mrr = info.get("mrr") or 0
    if offer:
        mrr = offer["price"] if offer.get("monthly") else mrr

    client = {
        "name": name,
        "business": str(info.get("business") or snapshot.get("company") or "").strip(),
        "status": "lead",
        # The quote goes in `offer` (structured), never in `plan` — `plan` is a
        # dropdown in the UI, so writing the quote there meant one stray click
        # erased the only record of what was actually sold.
        "offer": offer,
        "site": str(info.get("site") or snapshot.get("website") or "").strip(),
        "mrr": mrr,
        # A free build stores 0 and that is the honest number — it is CAC, not
        # revenue. A paid build stores its price so build revenue is countable.
        "oneTime": _escalate_one_time(offer, info),
        "services": services,
        "notes": _escalate_notes(snapshot, info),
    }
    if snapshot.get("client_id"):
        client["id"] = snapshot["client_id"]  # re-escalate updates, never duplicates

    try:
        import agency_io
        res = agency_io.save_client(client)
    except Exception as e:
        return {"ok": False, "detail": f"Couldn't save to the client book: {e}"}
    if not res.get("ok"):
        return {"ok": False, "detail": res.get("error") or "Client save failed."}

    cid = res["client"]["id"]
    with _LOCK:
        d = _load()
        for lead in d["leads"]:
            if lead["id"] == lead_id:
                lead["client_id"] = cid
                lead["escalated"] = datetime.now().strftime("%m/%d %H:%M")
                lead["offer"] = agency_offers.line(offer)
                said = str(info.get("notes") or "").strip()
                nxt = str(info.get("next_step") or "").strip()
                summary = " · ".join(x for x in (nxt, said) if x)
                if summary:
                    lead["note"] = summary[:300]
                break
        _save(d)

    out = set_status(lead_id, "interested")
    out["client"] = res["client"]
    return out


def delete_lead(lead_id):
    with _LOCK:
        d = _load()
        before = len(d["leads"])
        d["leads"] = [l for l in d["leads"] if l["id"] != lead_id]
        if len(d["leads"]) != before:
            _save(d)
    return list_leads()


def clear_dead():
    with _LOCK:
        d = _load()
        before = len(d["leads"])
        d["leads"] = [l for l in d["leads"] if l.get("status") != "dead"]
        removed = before - len(d["leads"])
        if removed:
            _save(d)
    out = list_leads()
    out["removed"] = removed
    return out


if __name__ == "__main__":
    STATE = Path(tempfile.mktemp(suffix=".json"))  # monkeypatch before any call

    r = import_text("Joe's Pizza (215) 555-1234 joe@pizza.com\n"
                     "Acme Plumbing 215-555-9999 www.acme.com", use_ai=False)
    assert r["ok"] and r["added"] == 2, r
    assert r["counts"]["total"] == 2 and r["counts"]["new"] == 2, r

    r2 = import_text("Joe's Pizza (215) 555-1234 joe@pizza.com\n"
                      "Acme Plumbing 215-555-9999 www.acme.com", use_ai=False)
    assert r2["added"] == 0 and r2["skipped"] == 2, r2

    calls = []
    import agency_calls
    agency_calls.log_call = lambda outcome: calls.append(outcome)  # monkeypatch

    lid = r["leads"][0]["id"]
    r3 = set_status(lid, "answered")
    assert calls == ["answered"], calls
    lead = [l for l in r3["leads"] if l["id"] == lid][0]
    assert lead["last_called"], lead
    assert r3["counts"]["answered"] == 1 and r3["counts"]["new"] == 1, r3

    bad = set_status(lid, "maybe")
    assert bad["ok"] is False, bad

    n = set_note(lid, "  call after 5pm  ")
    assert n["ok"], n
    assert list_leads()["leads"][0]["note"] == "call after 5pm"

    # inline pain-point edit rides the same route via `field`
    assert set_note(lid, " no online ordering ", "pain")["ok"]
    assert list_leads()["leads"][0]["pain"] == "no online ordering"
    set_note(lid, "hack", "status")          # unknown field falls back to note…
    assert list_leads()["leads"][0]["note"] == "hack"          # …never writes status
    assert list_leads()["leads"][0]["status"] == "answered"

    # --- escalate: interested → agency client book (Pipeline "lead" column) ---
    import agency_io
    saved_clients = []

    def _fake_save(c):
        saved_clients.append(c)
        return {"ok": True, "client": dict(c, id=c.get("id") or "c_test1")}

    agency_io.save_client = _fake_save  # monkeypatch

    import agency_offers
    esc = escalate(lid, {"name": "Regina", "business": "Bright Start Daycare",
                          "services": ["Website"], "offer": {"id": "web-growth"},
                          "next_step": "Zoom Thu 10am", "notes": "site has no tour form"})
    assert esc["ok"], esc
    assert saved_clients[0]["status"] == "lead", saved_clients
    # a one-time build must NOT become recurring revenue
    assert saved_clients[0]["mrr"] == 0, saved_clients[0]
    # the quote lives in `offer` (structured), never `plan`
    assert agency_offers.line(saved_clients[0]["offer"]) == "Growth Website — $700", saved_clients[0]
    assert "Offer quoted: Growth Website — $700" in saved_clients[0]["notes"]

    assert "Phone: " in saved_clients[0]["notes"], saved_clients[0]["notes"]
    assert "Zoom Thu 10am" in saved_clients[0]["notes"], saved_clients[0]["notes"]
    lead = [l for l in esc["leads"] if l["id"] == lid][0]
    assert lead["status"] == "interested" and lead["client_id"] == "c_test1", lead
    assert lead["offer"] == "Growth Website — $700", lead
    assert calls == ["answered", "answered"], calls  # interested counts as a dial

    # a custom MONTHLY deal does set mrr, and is labelled off-sheet
    escalate(lid, {"name": "Regina", "offer": {"custom": True, "name": "Starter care",
                                                 "price": 175, "monthly": True}})
    assert saved_clients[-1]["mrr"] == 175, saved_clients[-1]
    assert "CUSTOM" in agency_offers.line(saved_clients[-1]["offer"]), saved_clients[-1]

    # re-escalating updates the SAME client, never creates a second one
    escalate(lid, {"name": "Regina", "mrr": 400})
    assert saved_clients[-1].get("id") == "c_test1", saved_clients[-1]

    assert escalate("nope", {"name": "x"})["ok"] is False
    assert escalate(lid, {"name": "   "})["ok"] is False  # name required

    lid2 = r["leads"][1]["id"]

    # dead line: stamps the row, deliberately NOT a dial
    before = len(calls)
    set_status(lid2, "bad_number")
    assert len(calls) == before, calls
    assert [l for l in list_leads()["leads"] if l["id"] == lid2][0]["last_called"]

    set_status(lid2, "dead")
    cleared = clear_dead()
    assert cleared["removed"] == 1, cleared
    assert cleared["counts"]["total"] == 1, cleared

    dr = delete_lead(lid)
    assert dr["counts"]["total"] == 0, dr

    # --- lifecycle (wave-2 #4) ---------------------------------------------
    import sys
    from datetime import timedelta
    sys.modules["agency_callsheet"] = sys.modules[__name__]  # owner_actions sees temp STATE
    import owner_actions

    # old rows (no lifecycle fields) read back with safe defaults
    with _LOCK:
        d = _load()
        d["leads"].append({"id": "Lold", "name": "Legacy Co", "phone": "215-555-0000",
                           "status": "callback", "note": ""})
        _save(d)
    old = [l for l in list_leads()["leads"] if l["id"] == "Lold"][0]
    assert old["attempts"] == 0 and old["callbackAt"] == "" and old["due"], old

    r = import_text("Bright Dental 215-555-7777\nCorner Cafe 215-555-8888", use_ai=False)
    a, b = [l["id"] for l in r["leads"] if l["id"] != "Lold"]

    # answered / no_answer bump attempts + lastContactAt, tally still bumps
    calls.clear()
    set_status(a, "no_answer")
    r = set_status(a, "answered")
    la = [l for l in r["leads"] if l["id"] == a][0]
    assert la["attempts"] == 2 and la["lastContactAt"], la
    assert calls == ["no_answer", "answered"], calls
    set_status(a, "callback")  # CB is not a dial
    assert [l for l in list_leads()["leads"] if l["id"] == a][0]["attempts"] == 2

    # tomorrow's callback is NOT in today's list; a past one is, with a real age
    tomorrow = (_now() + timedelta(days=1)).isoformat()
    assert set_note(a, tomorrow, "callbackAt")["ok"]
    assert set_note(a, "next tuesday", "callbackAt")["ok"] is False  # junk rejected
    leads = list_leads()["leads"]
    assert a not in [l["id"] for l in call_queue(leads)]
    assert not [l for l in leads if l["id"] == a][0]["due"]
    oa = {i["id"]: i for i in owner_actions._src_agency_callsheet({})}
    assert f"callsheet:{a}" not in oa, oa
    assert oa["callsheet:Lold"]["kind"] == "CALLBACK"   # legacy callback row still shows
    assert oa["callsheet:new"]["title"].startswith("1 prospect"), oa  # b only

    two_h_ago = (_now() - timedelta(hours=2)).isoformat()
    set_note(a, two_h_ago, "callbackAt")
    assert a in [l["id"] for l in call_queue(list_leads()["leads"])]
    it = {i["id"]: i for i in owner_actions._src_agency_callsheet({})}[f"callsheet:{a}"]
    assert it["kind"] == "CALLBACK" and it["priority"] == "revenue", it
    assert 7000 <= it["ageSec"] <= 7300, it
    # making the due call consumes the callback
    set_status(a, "no_answer")
    la = [l for l in list_leads()["leads"] if l["id"] == a][0]
    assert la["callbackAt"] == "" and la["attempts"] == 3, la

    # dnc: out of every queue, and its phone never re-imports — even after delete
    set_status(b, "dnc")
    assert b not in [l["id"] for l in call_queue(list_leads()["leads"])]
    assert "callsheet:new" not in {i["id"] for i in owner_actions._src_agency_callsheet({})}
    delete_lead(b)
    r = import_text("Corner Cafe again (215) 555-8888", use_ai=False)
    assert r["added"] == 0 and r["skipped"] == 1, r
    # un-marking dnc (row still present) lifts the block
    set_status("Lold", "dnc")
    set_status("Lold", "new")
    delete_lead("Lold")
    assert import_text("Legacy Co 215-555-0000", use_ai=False)["added"] == 1

    for st in ("ready", "demo_booked", "proposal", "won", "lost"):
        assert set_status(a, st)["ok"], st
    assert list_leads()["counts"]["lost"] == 1

    print("ok")
