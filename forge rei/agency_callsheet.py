"""agency_callsheet.py — Call Sheet: CRM-style lead tracker (Forge AI Agency).

Owner uploads a PDF (or pastes text) of business leads; it becomes a table of
businesses tracked per-row (new / answered / no_answer / callback / dead).
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
from datetime import datetime
from pathlib import Path

import forge_atomic

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "agency_callsheet.json"
_LOCK = threading.Lock()

STATUSES = ("new", "answered", "no_answer", "callback", "dead")

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
                return d
        except Exception:
            pass
    return {"seq": 0, "leads": []}


def _save(d):
    forge_atomic.atomic_write_json(STATE, d)


def _norm_phone(p):
    return re.sub(r"\D", "", str(p or ""))


def _dupe_key(lead):
    phone = _norm_phone(lead.get("phone"))
    if phone:
        return ("phone", phone)
    return ("name", str(lead.get("name", "")).lower(), str(lead.get("company", "")).lower())


def _add_leads(d, incoming):
    """Internal — lock must already be held. Skips dupes, assigns ids. Returns count added."""
    existing = {_dupe_key(l) for l in d["leads"]}
    added = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for lead in incoming:
        key = _dupe_key(lead)
        if key in existing:
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
            "status": "new",
            "note": "",
            "added": now,
            "last_called": "",
        })
        added += 1
    return added


def list_leads():
    with _LOCK:
        d = _load()
        leads = list(d["leads"])
    counts = {s: 0 for s in STATUSES}
    for l in leads:
        counts[l.get("status", "new")] = counts.get(l.get("status", "new"), 0) + 1
    counts["total"] = len(leads)
    return {"ok": True, "leads": leads, "counts": counts}


def _leads_from_ai(text):
    import review_agent
    key = review_agent._api_key()
    if not key:
        return None
    system = (
        "Extract business leads from raw text. Output ONLY a JSON array of "
        "objects with keys name, company, phone, email, website, location "
        "(empty string when unknown). No commentary, no markdown fences."
    )
    reply = review_agent._claude(key, system, text[:12000], max_tokens=3000)
    start = reply.index("[")
    end = reply.rindex("]")
    rows = json.loads(reply[start:end + 1])
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lead = {k: str(row.get(k, "") or "").strip() for k in
                 ("name", "company", "phone", "email", "website", "location")}
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
                     "website": website, "location": ""})
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
                lead["status"] = status
                if status in ("answered", "no_answer", "callback"):
                    lead["last_called"] = datetime.now().strftime("%m/%d %H:%M")
                if status in ("answered", "no_answer"):
                    tally_outcome = status
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


def set_note(lead_id, note):
    note = str(note or "").strip()[:300]
    with _LOCK:
        d = _load()
        for lead in d["leads"]:
            if lead["id"] == lead_id:
                lead["note"] = note
                _save(d)
                return {"ok": True}
    return {"ok": False, "detail": "Lead not found."}


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

    lid2 = r["leads"][1]["id"]
    set_status(lid2, "dead")
    cleared = clear_dead()
    assert cleared["removed"] == 1, cleared
    assert cleared["counts"]["total"] == 1, cleared

    dr = delete_lead(lid)
    assert dr["counts"]["total"] == 0, dr

    print("ok")
