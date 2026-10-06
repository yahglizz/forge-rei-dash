"""daycare_family_confirm.py — reads parents' replies to the Family Contact Form
confirmation text and marks the family confirmed.

Flow (spec: A Touch of Blessings — Brand Kit/docs/superpowers/specs/2026-10-05-family-form-automation-design.md):
  forms/api/submit.js arms the GHL workflow "Family Form Confirmation SMS", which texts
  "...reply YES to confirm". The contact carries `family-confirm-pending` and the ISO send
  time in the `family_confirm_sent` custom field. Every INTERVAL this loop reads each pending
  family's thread; an affirmative inbound reply AFTER the send swaps the tag to
  `family-confirmed` and stamps `family_confirmed_at` + a Note.

Internal + reversible (tags/fields/notes only — CLAUDE.md rule 2), never sends a text.
A reply that isn't a clean YES (questions, corrections, "yes but…") is left pending and
surfaced on the Parent Logins card for a human. STOP is the carrier/GHL's job.
Knob: FORGE_DAYCARE_FAMILY_CONFIRM=0 turns the loop off. Stdlib only.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import daycare_ghl
import daycare_leads
import forge_atomic
import forge_heartbeat
import forge_ops
import seller_classify

HERE = Path(__file__).resolve().parent
STATE = HERE / "marcus_state" / "daycare_family_confirm.json"
_LOCK = threading.Lock()
INTERVAL = int(os.environ.get("FORGE_DAYCARE_FAMILY_CONFIRM_INTERVAL", "120"))

PENDING_TAG = "family-confirm-pending"
CONFIRMED_TAG = "family-confirmed"
CF_CONFIRM_SENT = "D1HjF1rkDPhTQsNoPCoc"
CF_CONFIRMED_AT = "T4h8YJeha9uvQE5MgBNf"
NO_REPLY_SEC = 48 * 3600

_YES_RE = re.compile(r"^(y|ya|yes+|yea+h?|yep|yup|confirm(ed)?|correct|ok(ay)?|all good|looks good|"
                     r"that'?s right|right)\b")
_HEDGE_RE = re.compile(r"\b(no|not|wrong|incorrect|change|update|but|except|fix|mistake)\b")


def classify(body: str) -> str:
    """Pure: 'yes' | 'opt_out' | 'other'. Hedged yeses ('yes but the phone is wrong') are 'other'."""
    text = str(body or "").strip()
    if seller_classify.is_opt_out(text):
        return "opt_out"
    low = re.sub(r"\s+", " ", text.lower())
    if low.startswith(("👍", "✅")) and not _HEDGE_RE.search(low):
        return "yes"
    words = re.sub(r"[^a-z' ]", " ", low).strip()
    if _YES_RE.match(words) and not _HEDGE_RE.search(words):
        return "yes"
    return "other"


def _iso_sec(v) -> float | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def decide(contact: dict, messages: list, now: float) -> dict:
    """Pure: given a pending family's contact + thread, what happened? Returns
    {"state": confirmed|opted_out|replied|no_reply|waiting, "reply": text|None, "at": sec|None}."""
    cf = daycare_ghl._cf_map(contact)
    sent = _iso_sec(cf.get(CF_CONFIRM_SENT))
    inbound = []
    for m in messages or []:
        t = daycare_leads._sec(m.get("dateAdded") or m.get("date"))
        mtype = str(m.get("messageType") or m.get("type") or "").upper()
        if t is None or m.get("direction") != "inbound" or "ACTIVITY" in mtype:
            continue
        # Only replies to OUR text count; a message from before it can't be a YES to it.
        if sent is not None and t < sent - 5:
            continue
        inbound.append((t, str(m.get("body") or "")))
    inbound.sort()
    for t, body in reversed(inbound):           # newest decisive reply wins
        verdict = classify(body)
        if verdict == "yes":
            return {"state": "confirmed", "reply": body, "at": t}
        if verdict == "opt_out":
            return {"state": "opted_out", "reply": body, "at": t}
    if inbound:
        t, body = inbound[-1]
        return {"state": "replied", "reply": body, "at": t}
    if sent is not None and now - sent > NO_REPLY_SEC:
        return {"state": "no_reply", "reply": None, "at": None}
    return {"state": "waiting", "reply": None, "at": None}


def _load() -> dict:
    try:
        import json
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 — missing/corrupt = fresh
        return {}


def status(contact_id: str | None) -> dict:
    """Last verdict for one family (read by the Parent Logins card). {} when unknown."""
    if not contact_id:
        return {}
    with _LOCK:
        return (_load().get("families") or {}).get(str(contact_id)) or {}


def _confirm(client, cid: str, reply: str, at: float) -> None:
    when = datetime.fromtimestamp(at, tz=timezone.utc).isoformat()
    client.post(f"/contacts/{cid}/tags", {"tags": [CONFIRMED_TAG]})
    client.delete(f"/contacts/{cid}/tags", {"tags": [PENDING_TAG]})
    client.put(f"/contacts/{cid}", {"customFields": [{"id": CF_CONFIRMED_AT, "value": when}]})
    client.post(f"/contacts/{cid}/notes", {"body": f"Family confirmed their info by text ({when}): \"{reply[:200]}\""})


def run_once(client, now: float | None = None) -> dict:
    """One sweep. Never sends. Returns a summary; `unresolved` > 0 means some reads failed
    and the summary is partial (never report a partial run as complete)."""
    now = now or time.time()
    if client is None or not getattr(client, "configured", False):
        return {"ok": False, "error": "Daycare GHL not configured"}
    with _LOCK:
        state = _load()
    fams = state.get("families") or {}
    summary = {"ok": True, "checked": 0, "confirmed": 0, "unresolved": 0}
    for contact in daycare_ghl.iter_contacts(client):
        tags = {str(t).lower() for t in contact.get("tags") or []}
        cid = str(contact.get("id") or "")
        if PENDING_TAG not in tags or CONFIRMED_TAG in tags or not cid:
            continue
        summary["checked"] += 1
        try:
            conv = daycare_leads._conversation(client, cid)
            verdict = decide(contact, daycare_leads._messages(client, conv), now)
            if verdict["state"] == "confirmed":
                _confirm(client, cid, verdict["reply"], verdict["at"])
                summary["confirmed"] += 1
            fams[cid] = {**verdict, "checkedAt": now}
        except Exception as e:  # noqa: BLE001 — one family never blocks the rest
            summary["unresolved"] += 1
            print(f"[family_confirm] {cid}: {type(e).__name__}: {str(e)[:120]}")
        time.sleep(0.3)                          # gentle on GHL's rate limit
    with _LOCK:
        forge_atomic.atomic_write_json(STATE, {"lastRunAt": int(now * 1000), "families": fams,
                                               "last": summary})
    return summary


def run_forever(client):
    """Background loop (thread `daycare_family_confirm`)."""
    while True:
        err = None
        try:
            if not forge_ops.paused():
                s = run_once(client)
                err = s.get("error") or (f"{s['unresolved']} unresolved" if s.get("unresolved") else None)
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        forge_heartbeat.beat("daycare_family_confirm", INTERVAL, "Solomon · Family confirm", error=err)
        time.sleep(INTERVAL)
