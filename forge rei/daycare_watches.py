"""daycare_watches.py — the Watches: zero-Claude detectors that fill Solomon's Command Board.

One function per domain — inbox · enrollment · billing · ads · social · roster · systems. Each
reads the connector's OWN routes through `get(path, query)` (default: loopback GET via
telegram_agent._http, the same auto-admin path the Telegram partner uses; tests pass fixtures) and
returns (items, status):
  items  = board items, each with evidence {source, window, fetchedAt} and a center
  status = {ok, error?, notWired?, note?, sources?: {key-prefix: ok}}  (sources = which sub-reads
           worked, so one failed read never closes another read's items)
Rules on data only — counts, dates, statuses. No Claude, no write anywhere except the board file,
nothing outward. ZZTest/zztest test families are ignored everywhere. Amounts are exactly what
Supabase / Meta report — never inferred. 1923 A Mother's Touch keeps its own center label.
run_round() runs the seven in parallel (a crashing watch = that domain ok:false), applies the round
to the board in ONE write and records lastRound. One round at a time.
Thresholds: FORGE_BOARD_* (see constants). Test: python3 test_daycare_watches.py
"""
import email.utils
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import daycare_board
import gmail_io


def _num(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return float(default)


ET = ZoneInfo("America/New_York")
MAIL_HOURS = _num("FORGE_BOARD_MAIL_HOURS", 4)               # daycare mail unanswered this long = an item
MAIL_DAYS = int(_num("FORGE_BOARD_MAIL_DAYS", 7))
MAIL_LIMIT = 40                                             # daycare rows per round
MAIL_THREAD_CHECKS = 15                                     # header-only thread reads per round (answered?)
FORM_GRACE_MIN, FORM_MATCH_MIN = 30, 60                     # form email ↔ Lead Desk lead createdAt
RESPONSE_MAX_SEC = int(_num("FORGE_BOARD_RESPONSE_MAX_MIN", 120) * 60)   # median human reply to leads
STALE_SEC = int(_num("FORGE_BOARD_STALE_MIN", 120) * 60)    # Lead Desk older than this = stale (Unknown)
DUE_SOON_DAYS = int(_num("FORGE_BOARD_DUE_SOON_DAYS", 3))
NOINV_DAYS = int(_num("FORGE_BOARD_NOINVOICE_DAYS", 45))
MAX_INV_ITEMS, MAX_DUE_SOON = 10, 5                         # per center; the rest roll into one item
MIN_GAP_SEC = int(_num("FORGE_BOARD_MIN_GAP_SEC", 120))     # rounds closer than this are skipped
OWN_DOMAIN = "@atouchofblessing.com"
ASK_BUCKETS = {"parent": "Parent", "lead": "Lead", "billing": "Billing", "licensing": "Licensing"}
_TEST = re.compile(r"zz\s*test", re.I)
_FAMILY_FORM = re.compile(r"contact form|existing family", re.I)   # → Contact-Form inbox, not the Lead Desk
_LOOPS = ("daycare", "solomon", "telegram")                 # loops the daycare side depends on
_LEAD_SEV = {"URGENT": "urgent", "REVENUE": "high", "CUSTOMER": "high"}


# ── small helpers ─────────────────────────────────────────────────────────────────────────
def _is_test(*texts):
    return any(_TEST.search(str(t or "")) for t in texts)


def _ts(v):
    """ISO-8601 / RFC-2822 / epoch(ms) → epoch seconds, else None."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v / 1000 if v > 1e11 else float(v)
    s = str(v).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        pass
    try:
        return email.utils.parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError, IndexError):
        return None


def _et(sec):
    return datetime.fromtimestamp(sec, ET).strftime("%b %-d %-I:%M %p ET") if sec else "unknown time"


def _today(now):
    return datetime.fromtimestamp(now, ET).date()


def _dur(sec):
    sec = int(sec or 0)
    return f"{max(1, sec // 60)} min" if sec < 3600 else f"{sec / 3600:.1f} h" if sec < 172800 else f"{sec // 86400} d"


def _money(v):
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "amount Unknown"


def _bad(res):
    return not isinstance(res, dict) or res.get("ok") is False or bool(res.get("error"))


def _err(res, what):
    return str((res or {}).get("error") or f"{what} unreadable")[:160] if isinstance(res, dict) else f"{what} unreadable"


def _labels():
    import daycare_leads
    lab = daycare_leads.CENTER_LABEL
    return lab["loc-921-n-18th"], lab["loc-2318-cecil-b-moore"], lab["loc-1923-cecil-b-moore"]


def _center(name):
    """Supabase location name → the Lead Desk's center label (one vocabulary on the board)."""
    try:
        import daycare_director
        return daycare_director._CENTER_ALIAS.get(name) or name or "unknown"
    except Exception:  # noqa: BLE001
        return name or "unknown"


def _norm_center(label):
    label = str(label or "").strip()
    return "unknown" if not label or label.lower() == "center unknown" else label


def _center_from_text(text):
    n921, n2318, amt = _labels()
    if re.search(r"mother[’'`]?s touch|\b1923\b|\bAMT\b", text or "", re.I):
        return amt
    if re.search(r"\b2318\b|touch of blessings? 2\b", text or "", re.I):
        return n2318
    if re.search(r"\b921\b|18th st", text or "", re.I):
        return n921
    return "unknown"


def _addr(row):
    a = gmail_io._addrs((row or {}).get("from"))
    return a[0] if a else ""


def _ours(row):
    """A message we sent (own domain), not the form robot."""
    a = _addr(row)
    return a.endswith(OWN_DOMAIN) and a != gmail_io.FORM_SENDER


def _sender(v):
    name, addr = email.utils.parseaddr(str(v or ""))
    return daycare_board._clip(name or addr or "unknown sender", 40)


def _locations(get):
    r = get("/api/daycare/locations")
    if _bad(r) or not isinstance(r.get("locations"), list):
        return None
    locs = [x for x in r["locations"] if isinstance(x, dict) and x.get("id")]
    return locs or None                     # zero centers readable = a failed read, never "0 problems"


def _leads_fresh(leads, now):
    return (isinstance(leads, dict) and leads.get("ok") is True and leads.get("lastOkAt")
            and now - leads["lastOkAt"] / 1000 <= STALE_SEC)


# ── INBOX ─────────────────────────────────────────────────────────────────────────────────
def watch_inbox(get, now):
    mail = get("/api/daycare/mail", {"days": MAIL_DAYS, "limit": MAIL_LIMIT})
    if not isinstance(mail, dict) or mail.get("ok") is not True:
        m = mail if isinstance(mail, dict) else {}
        wired = m.get("configured") is not False or bool(m.get("authDead"))
        err = ("Gmail not connected" if not wired else "Gmail read failed: " + _err(m, "mail"))
        return [], {"ok": False, "notWired": not wired, "error": err + " — 0 mail items is Unknown, not zero",
                    "mailDesk": {"ok": False, "error": err, "at": int(now * 1000)}}
    rows = [r for r in mail.get("rows") or [] if not _is_test(r.get("from"), r.get("subject"), r.get("snippet"))]
    window = (mail.get("dateRange") or {}).get("label") or f"last {MAIL_DAYS} days"
    ev = {"source": "Gmail — daycare mail only (read-only)", "window": window, "fetchedAt": mail.get("fetchedAt")}
    threads = {}
    for r in rows:
        threads.setdefault(r.get("threadId") or r.get("id"), []).append(r)
    items, urgent, unchecked, checks, forms_unk = [], [], 0, 0, 0
    for tid, rs in threads.items():
        inbound = [r for r in rs if not _ours(r)]
        last = max(inbound, key=lambda r: _ts(r.get("date")) or 0, default=None)
        t_last = _ts((last or {}).get("date"))
        if not last or t_last is None:
            continue
        age, subject = now - t_last, last.get("subject") or "(no subject)"
        center = _center_from_text(f"{subject} {last.get('snippet') or ''}")
        if gmail_io.FORM_SENDER in gmail_io._addrs(last.get("from")):        # a web-form submission
            if age < FORM_GRACE_MIN * 60 or _FAMILY_FORM.search(subject):
                continue
            leads = get("/api/daycare/leads")
            if not _leads_fresh(leads, now):
                forms_unk += 1
                continue
            if any(abs((l.get("createdAt") or 0) / 1000 - t_last) <= FORM_MATCH_MIN * 60
                   for l in leads.get("leads") or []):
                continue
            items.append({"key": f"form:{last.get('id')}", "title": f"Form email with no matching GHL lead — {subject}",
                          "why": f"Form email {_et(t_last)}; the Lead Desk shows no lead created within "
                                 f"{FORM_MATCH_MIN} min of it (a time match — a returning family can trip it). "
                                 "Check it reached GHL.",
                          "severity": "high", "owner": "owner", "center": center,
                          "evidence": dict(ev, source="Gmail form email vs Lead Desk (GHL)"),
                          "link": {"kind": "mail", "ref": tid}})
            continue
        bucket = last.get("bucket")
        if bucket not in ASK_BUCKETS or age < MAIL_HOURS * 3600:
            continue
        unread = any(r.get("unread") for r in inbound)
        if any(_ours(r) and (_ts(r.get("date")) or 0) > t_last for r in rs):
            continue                        # our later reply is already in the list
        answered = None
        if checks < MAIL_THREAD_CHECKS:
            checks += 1
            t = get("/api/daycare/mail/thread", {"id": tid, "meta": 1})
            if isinstance(t, dict) and t.get("ok") is True:
                answered = any(_ours(m) and (_ts(m.get("date")) or 0) > t_last for m in t.get("messages") or [])
        if answered:
            continue
        if answered is None and not unread:
            unchecked += 1                  # read + reply status unknown → Unknown, not an item
            continue
        state = ("unread" if unread else f"read, no reply from {OWN_DOMAIN} after it") + (
            " (reply status not checked)" if answered is None else "")
        sev = "high" if bucket in ("licensing", "lead") or age >= 86400 else "normal"
        items.append({"key": f"mail:{tid}",
                      "title": f"{ASK_BUCKETS[bucket]} email waiting {_dur(age)} — {_sender(last.get('from'))}: {subject}",
                      "why": f"{bucket} mail · their last message {_et(t_last)} · {state}. Replying is your call — "
                             "nothing is ever sent from here.",
                      "severity": sev, "owner": "owner", "center": center, "evidence": ev,
                      "link": {"kind": "mail", "ref": tid}})
        if sev == "high":
            urgent.append({"subject": subject, "bucket": bucket, "threadId": tid})
    counts = {}
    for r in rows:
        counts[r.get("bucket")] = counts.get(r.get("bucket"), 0) + 1
    top = sorted((r for r in rows if r.get("unread")), key=lambda r: _ts(r.get("date")) or 0, reverse=True)[:5]
    desk = {"ok": True, "window": window, "fetchedAt": mail.get("fetchedAt"), "counts": counts,
            "unread": sum(1 for r in rows if r.get("unread")), "needsAnswer": len(items),
            "filteredOut": mail.get("filteredOut"), "urgent": urgent[:5],
            "top": [{"subject": r.get("subject"), "from": _sender(r.get("from")), "bucket": r.get("bucket"),
                     "date": r.get("date")} for r in top]}
    status = {"ok": True, "mailDesk": desk}
    notes = ([f"{unchecked} read thread(s) not checked for a reply (cap {MAIL_THREAD_CHECKS}/round) — Unknown"]
             if unchecked else []) + ([f"{forms_unk} form email(s) not matched — Lead Desk stale"] if forms_unk else [])
    if notes:
        status["note"] = "; ".join(notes)
    return items, status


# ── ENROLLMENT ────────────────────────────────────────────────────────────────────────────
def watch_enrollment(get, now):
    items, src, errs = [], {}, []
    leads = get("/api/daycare/leads")
    ok = bool(_leads_fresh(leads, now))
    src["lead:"] = src["leads:"] = ok
    if ok:
        ev = {"source": "Solomon · Leads (daycare GHL sweep)",
              "window": f"sweep {_et(leads['lastOkAt'] / 1000)} · leads active ≤90 days", "fetchedAt": leads["lastOkAt"]}
        by_cid = {str(l.get("contactId")): l for l in leads.get("leads") or []}
        for n in leads.get("needsHuman") or []:
            cid = str(n.get("contactId") or "")
            lead = by_cid.get(cid) or {}
            if not cid or _is_test(n.get("title"), lead.get("parentName"), lead.get("childName")):
                continue
            items.append({"key": f"lead:{cid}", "title": n.get("title"),
                          "why": f"{n.get('why') or ''} · waiting {_dur(n.get('ageSec'))}",
                          "severity": _LEAD_SEV.get(n.get("priority"), "normal"), "owner": "owner",
                          "center": _norm_center(n.get("center")), "evidence": ev, "link": {"kind": "family", "ref": cid}})
        k = leads.get("kpis") or {}
        med = k.get("medianHumanResponseSec")
        if med is not None and med > RESPONSE_MAX_SEC:
            items.append({"key": "leads:response-time",
                          "title": f"New leads wait {_dur(med)} for a human reply (target ≤ {_dur(RESPONSE_MAX_SEC)})",
                          "why": f"Lead Desk median first HUMAN reply, last 30 days, {k.get('humanSample')} leads. "
                                 "Parents call several centers in one sitting — the first to answer books the tour.",
                          "severity": "high", "owner": "owner", "center": "all",
                          "evidence": dict(ev, window="last 30 days (Lead Desk median)")})
    else:
        errs.append("Lead Desk: " + (_err(leads, "leads") if _bad(leads) else
                                     f"last good sweep older than {STALE_SEC // 60} min (or never)"))
    starts = get("/api/daycare/starts")
    src["start:"] = ok = not _bad(starts) and bool(starts.get("lastRunAt"))
    if ok:
        ev = {"source": "Solomon · Starts (GHL threads + owner confirms)",
              "window": f"sweep {_et(starts['lastRunAt'] / 1000)}", "fetchedAt": starts["lastRunAt"]}
        for r in starts.get("starts") or []:
            cid = str(r.get("contactId") or "")
            who = r.get("childFirst") or r.get("parentName") or "a family"
            if not cid or _is_test(r.get("parentName"), r.get("childName"), r.get("childFirst")):
                continue
            if r.get("status") == "failed":
                items.append({"key": f"start:{cid}", "title": f"Start-day login text failed — {who} ({r.get('startDate')})",
                              "why": f"Solomon · Starts could not send the app login{': ' + str(r['lastError']) if r.get('lastError') else ''}. "
                                     "Resend from Start dates (your tap).",
                              "severity": "urgent", "owner": "owner", "center": _norm_center(r.get("center")),
                              "evidence": ev, "link": {"kind": "family", "ref": cid}})
            elif r.get("confirmOpen"):
                items.append({"key": f"start:{cid}", "title": f"Confirm {who}'s start date — {r.get('startDate')}",
                              "why": f"Agreed in their texts (\"{daycare_board._clip(r.get('evidence'), 80)}\"); starts in "
                                     f"{r.get('daysUntil')} day(s). Confirm enrolls + readies the login (your tap).",
                              "severity": "high", "owner": "owner", "center": _norm_center(r.get("center")),
                              "evidence": ev, "link": {"kind": "family", "ref": cid}})
    else:
        errs.append("Starts: " + _err(starts, "start dates") if _bad(starts) else "Starts: sweep has not run")
    held = get("/api/daycare/auto-enroll")
    src["held:"] = ok = not _bad(held) and bool(held.get("last_run"))
    if ok:
        ev = {"source": "Solomon · Auto-enroll (Contact Form inbox)",
              "window": f"run {_et(held['last_run'])}", "fetchedAt": int(held["last_run"] * 1000)}
        for h in held.get("held") or []:
            reasons = [str(x) for x in h.get("reasons") or []]
            if _is_test(h.get("child")) or "test or junk record" in reasons or not h.get("card_id"):
                continue
            items.append({"key": f"held:{h['card_id']}", "title": f"Auto-enroll held — {h.get('child') or 'a family'}",
                          "why": "; ".join(reasons)[:200] + ". Fix the card, then Enroll (your tap).",
                          "severity": "high", "owner": "owner",
                          "center": _norm_center(_tag_center(h.get("location"))), "evidence": ev,
                          "link": {"kind": "card", "ref": str(h["card_id"])}})
    else:
        errs.append("Auto-enroll: " + (_err(held, "auto-enroll") if _bad(held) else "has not run"))
    audit = get("/api/daycare/ghl/enrolled-audit", {"tag": "enrolled"})
    src["tagdrift:"] = ok = not _bad(audit)
    if ok:
        ev = {"source": "Supabase active roster vs GHL tags (enrolled audit, by guardian phone)",
              "window": "all active children now", "fetchedAt": int(now * 1000)}
        tests = {}
        for m in audit.get("missing") or []:
            if _is_test(m.get("parent"), m.get("child")):
                tests[m.get("center")] = tests.get(m.get("center"), 0) + 1
        for c in audit.get("centers") or []:
            n = int(c.get("missingTag") or 0) - tests.get(c.get("center"), 0)
            if n > 0:
                label = _center(c.get("center"))
                items.append({"key": f"tagdrift:{label}", "title": f"{n} enrolled famil{'y' if n == 1 else 'ies'} "
                                                                  f"missing the `enrolled` GHL tag — {label}",
                              "why": "Matched by guardian phone. Adding `enrolled` is AUTO for Solomon (one batch of "
                                     "/api/daycare/ghl/tag); other tags stay a tap.",
                              "severity": "low", "owner": "solomon", "center": label, "evidence": ev})
    else:
        errs.append("Enrolled audit: " + _err(audit, "enrolled audit"))
    status = {"ok": all(src.values()), "sources": src}
    if errs:
        status["error"] = "; ".join(errs)[:300]
    return items, status


def _tag_center(tag):
    try:
        import daycare_leads
        return daycare_leads.CENTER_LABEL.get(str(tag or "").lower()) or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


# ── BILLING ───────────────────────────────────────────────────────────────────────────────
def _date(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _who(inv):
    return inv.get("guardian_name") or (inv.get("guardian") or {}).get("display_name") or "a family"


def watch_billing(get, now):
    locs = _locations(get)
    if locs is None:
        return [], {"ok": False, "error": "center list unreadable — billing is Unknown, not zero"}
    items, src, errs, today = [], {}, [], _today(now)
    for loc in locs:
        lid, center = loc["id"], _center(loc.get("name"))
        bill = get("/api/daycare/billing", {"location_id": lid})
        kids = get("/api/daycare/children", {"location_id": lid})
        b_ok, k_ok = not _bad(bill), not _bad(kids)
        src[f"inv:{lid}:"] = src[f"invmore:{lid}"] = b_ok
        src[f"noinv:{lid}"] = b_ok and k_ok
        if not b_ok:
            errs.append(f"{center}: {_err(bill, 'invoices')}")
            continue
        ev = {"source": "Supabase invoices (system of record)", "window": f"latest 500 invoices · {center}",
              "fetchedAt": int(now * 1000)}
        overdue, soon = [], []
        for inv in bill.get("invoices") or []:
            if _is_test(_who(inv), (inv.get("children") or {}).get("first_name"), (inv.get("children") or {}).get("last_name")):
                continue
            due, st = _date(inv.get("due_on")), str(inv.get("status") or "")
            if st == "overdue" or (st == "due" and due and due < today):
                overdue.append((due or today, inv))
            elif st == "due" and due and 0 <= (due - today).days <= DUE_SOON_DAYS:
                soon.append((due, inv))
        overdue.sort(key=lambda x: x[0])
        for due, inv in overdue[:MAX_INV_ITEMS]:
            days = (today - due).days
            items.append({"key": f"inv:{lid}:{inv.get('id')}",
                          "title": f"Overdue{f' {days}d' if days > 0 else ''}: invoice {inv.get('invoice_number')} — "
                                   f"{_who(inv)} · {_money(inv.get('amount'))}",
                          "why": f"Supabase: {_money(inv.get('amount'))} invoice amount, due {inv.get('due_on')}, status "
                                 f"'{inv.get('status')}', {len(inv.get('payments') or [])} payment(s) recorded. Sending or "
                                 "texting it is your tap (Billing).",
                          "severity": "high", "owner": "owner", "center": center, "evidence": ev,
                          "due": inv.get("due_on"), "link": {"kind": "invoice", "ref": str(inv.get("id"))}})
        if len(overdue) > MAX_INV_ITEMS:
            items.append({"key": f"invmore:{lid}", "title": f"{len(overdue) - MAX_INV_ITEMS} more overdue invoices — {center}",
                          "why": f"{len(overdue)} overdue in Supabase; the {MAX_INV_ITEMS} oldest are listed. Open Billing.",
                          "severity": "high", "owner": "owner", "center": center, "evidence": ev})
        for due, inv in sorted(soon, key=lambda x: x[0])[:MAX_DUE_SOON]:
            items.append({"key": f"inv:{lid}:{inv.get('id')}",
                          "title": f"Due {due.isoformat()}: invoice {inv.get('invoice_number')} — {_who(inv)} · "
                                   f"{_money(inv.get('amount'))}",
                          "why": f"Supabase invoice due within {DUE_SOON_DAYS} days, status 'due'.",
                          "severity": "low", "owner": "owner", "center": center, "evidence": ev,
                          "due": inv.get("due_on"), "link": {"kind": "invoice", "ref": str(inv.get("id"))}})
        if not k_ok:
            errs.append(f"{center}: {_err(kids, 'children')} (no-invoice check Unknown)")
            continue
        since = today - timedelta(days=NOINV_DAYS)
        recent = [i for i in bill.get("invoices") or [] if (_date(i.get("issued_on")) or date.min) >= since
                  and i.get("status") != "void"]
        billed = {str(v) for i in recent for v in (i.get("child_id"), i.get("guardian_id")) if v}
        active = [c for c in kids.get("children") or [] if c.get("active") and not _is_test(
            c.get("first_name"), c.get("last_name"), c.get("guardian_name"))
            and not ((_date(c.get("withdrawn_on")) or date.max) <= today)
            and (_date(c.get("enrollment_date")) or today) <= today]
        missing = [c for c in active if str(c.get("id")) not in billed
                   and not (c.get("guardian_profile_id") and str(c["guardian_profile_id"]) in billed)]
        ev2 = dict(ev, window=f"invoices issued the last {NOINV_DAYS} days vs active children · {center}")
        if active and not recent:
            items.append({"key": f"noinv:{lid}", "title": f"No invoices in Supabase for {center} in {NOINV_DAYS} days",
                          "why": f"{len(active)} active children, 0 invoices issued since {since.isoformat()} — billing for "
                                 "this center is Unknown here (maybe billed outside Supabase).",
                          "severity": "low", "owner": "owner", "center": center, "evidence": ev2})
        elif missing:
            names = ", ".join(f"{c.get('first_name')} {str(c.get('last_name') or '')[:1]}." for c in missing[:6])
            items.append({"key": f"noinv:{lid}", "title": f"{len(missing)} enrolled children with no invoice in {NOINV_DAYS} days — {center}",
                          "why": f"No invoice by child or guardian since {since.isoformat()}: {names}"
                                 + (" …" if len(missing) > 6 else ""),
                          "severity": "normal", "owner": "owner", "center": center, "evidence": ev2})
    status = {"ok": all(src.values()), "sources": src,
              "note": "failed payments: Unknown — Supabase invoices carry no failed state and Stripe failures are not read"}
    if errs:
        status["error"] = "; ".join(errs)[:300]
    return items, status


# ── ROSTER ────────────────────────────────────────────────────────────────────────────────
def watch_roster(get, now):
    locs = _locations(get)
    if locs is None:
        return [], {"ok": False, "error": "center list unreadable — roster is Unknown, not zero"}
    items, src, errs, today = [], {}, [], _today(now)
    for loc in locs:
        lid, center = loc["id"], _center(loc.get("name"))
        rooms = get("/api/daycare/classrooms", {"location_id": lid})
        kids = get("/api/daycare/children", {"location_id": lid})
        r_ok, k_ok = not _bad(rooms), not _bad(kids)
        src[f"room:{lid}:"] = r_ok
        src[f"withdrawn:{lid}:"] = src[f"nologin:{lid}"] = src[f"nophone:{lid}"] = k_ok
        ev = {"source": "Supabase classrooms + children", "window": f"now · {center}", "fetchedAt": int(now * 1000)}
        if r_ok:
            for r in rooms.get("classrooms") or []:
                cap, enr = r.get("capacity"), r.get("enrolled")
                if r.get("active", True) and isinstance(cap, (int, float)) and isinstance(enr, (int, float)) and enr > cap:
                    items.append({"key": f"room:{lid}:{r.get('id')}",
                                  "title": f"{r.get('name')} over licensed capacity — {enr}/{cap} enrolled · {center}",
                                  "why": "Active children assigned to the room vs its capacity (Supabase). Never market "
                                         "this room; move or hold a start.",
                                  "severity": "urgent", "owner": "owner", "center": center, "evidence": ev})
        else:
            errs.append(f"{center}: {_err(rooms, 'classrooms')}")
        if not k_ok:
            errs.append(f"{center}: {_err(kids, 'children')}")
            continue
        active = [c for c in kids.get("children") or [] if c.get("active") and not _is_test(
            c.get("first_name"), c.get("last_name"), c.get("guardian_name"))]
        gone = set()
        for c in active:
            w = _date(c.get("withdrawn_on"))
            if w and w <= today:
                gone.add(c.get("id"))
                items.append({"key": f"withdrawn:{lid}:{c.get('id')}",
                              "title": f"{c.get('first_name')} {str(c.get('last_name') or '')[:1]}. withdrawn {w.isoformat()} "
                                       f"but still active — {center}",
                              "why": "Supabase withdrawn_on is set but active is still true: seats, counts and billing read "
                                     "this child as enrolled. Deactivate in Children (your tap).",
                              "severity": "normal", "owner": "owner", "center": center, "evidence": ev,
                              "link": {"kind": "child", "ref": str(c.get("id"))}})
        staying = [c for c in active if c.get("id") not in gone]
        nologin = [c for c in staying if not c.get("guardian_profile_id")]
        guardians = list({str(c["guardian_profile_id"]): c["guardian"] for c in staying
                          if c.get("guardian_profile_id") and isinstance(c.get("guardian"), dict)}.values())
        nophone = [g for g in guardians if not g.get("phone")]
        if nologin:
            items.append({"key": f"nologin:{lid}", "title": f"{len(nologin)} active children with no parent login — {center}",
                          "why": ", ".join(f"{c.get('first_name')} {str(c.get('last_name') or '')[:1]}." for c in nologin[:6])
                                 + (" …" if len(nologin) > 6 else "") + ". Logins are your tap (Logins tab).",
                          "severity": "low", "owner": "owner", "center": center, "evidence": ev})
        if nophone and len(nophone) == len(guardians) and len(guardians) >= 3:
            errs.append(f"{center}: no guardian phone came back at all — contact read likely failed (phones Unknown)")
            src[f"nophone:{lid}"] = False
        elif nophone:
            items.append({"key": f"nophone:{lid}", "title": f"{len(nophone)} parent logins with no phone — {center}",
                          "why": "Supabase guardian contact has no phone: no texts, no GHL match.",
                          "severity": "low", "owner": "owner", "center": center, "evidence": ev})
    status = {"ok": all(src.values()), "sources": src,
              "note": "ratio (staff on duty per room) is not read — Unknown; capacity is checked"}
    if errs:
        status["error"] = "; ".join(errs)[:300]
    return items, status


# ── ADS ───────────────────────────────────────────────────────────────────────────────────
def watch_ads(get, now):
    feed = get("/api/daycare/ads/feed", {"fresh": "0"})
    if not isinstance(feed, dict) or feed.get("kind") != "daycare_ads_feed":
        return [], {"ok": False, "error": _err(feed, "ad feed") + " — ad numbers Unknown"}
    if feed.get("configured") is False:
        return [], {"ok": False, "notWired": True, "error": "Pipeboard not connected for the daycare — ad numbers Unknown"}
    items, src = [], {"ap:": True}
    for p in ((feed.get("autopilot") or {}).get("pending") or []):
        if p.get("id"):
            items.append({"key": f"ap:{p['id']}", "title": f"Ads autopilot proposal waiting on you — {p.get('action')}",
                          "why": f"{p.get('reason') or ''} Approve or skip in Growth → Autopilot or the Telegram card.",
                          "severity": "normal", "owner": "owner", "center": "all",
                          "evidence": {"source": "Solomon · Ads autopilot state", "window": "pending now",
                                       "fetchedAt": int(now * 1000)}})
    w7 = next((w for w in feed.get("windows") or [] if w.get("preset") == "last_7d"), None)
    ok7 = bool(w7) and not w7.get("unknown") and not feed.get("unknown") and not w7.get("partial")
    src["cpl:"] = src["nodeliv:"] = ok7
    if ok7:
        ev = {"source": "Meta via Pipeboard", "window": w7.get("window") or "last 7 days",
              "fetchedAt": feed.get("fetchedAt")}
        t = w7.get("totals") or {}
        spend, leads, cpl, tcpl = t.get("spend") or 0, t.get("leads") or 0, t.get("cpl"), t.get("tcpl")
        if tcpl and spend and not leads and spend >= tcpl:
            items.append({"key": "cpl:7d", "title": f"${spend:,.2f} spent in 7 days, 0 leads (target CPL ${tcpl:,.0f})",
                          "why": "Meta account totals. A full target CPL spent with nothing to show — the autopilot's rules "
                                 "decide pauses; you approve.", "severity": "high", "owner": "owner", "center": "all",
                          "evidence": ev})
        elif tcpl and cpl and cpl > tcpl:
            items.append({"key": "cpl:7d", "title": f"CPL ${cpl:,.2f} over target ${tcpl:,.0f} (last 7 days)",
                          "why": f"Meta: ${spend:,.2f} spend → {leads} leads.", "severity": "high" if cpl > 1.5 * tcpl else "normal",
                          "owner": "owner", "center": "all", "evidence": ev})
        for c in w7.get("campaigns") or []:
            if str(c.get("status") or "").lower() == "active" and not c.get("spend"):
                items.append({"key": f"nodeliv:{c.get('id')}", "title": f"Active campaign spent $0 in 7 days — {c.get('name')}",
                              "why": "Campaign is ACTIVE in Meta but delivered nothing this window (ad sets/ads paused, "
                                     "budget or review?).", "severity": "normal", "owner": "owner", "center": "all",
                              "evidence": ev})
    status = {"ok": ok7, "sources": src}
    if not ok7:
        status["error"] = (feed.get("error") or (w7 or {}).get("error") or "7-day window Unknown/partial")[:200] + \
            " — CPL / delivery Unknown"
    return items, status


# ── SOCIAL ────────────────────────────────────────────────────────────────────────────────
def watch_social(get, now):
    s = get("/api/daycare/social")
    if _bad(s):
        return [], {"ok": False, "error": _err(s, "social") + " — social is Unknown"}
    if s.get("configured") is False:
        return [], {"ok": False, "notWired": True,
                    "error": "Metricool not connected for the daycare (METRICOOL_USER_TOKEN missing) — social is Unknown"}
    # ponytail: the daycare social read has no Metricool scheduled-post list (posts are the agency's
    # local store), so "nothing scheduled for N days" can't be judged — add a Metricool read to wire it.
    return [], {"ok": False, "notWired": True,
                "error": "not wired: no daycare Metricool scheduled-post read exists — social is Unknown"}


# ── SYSTEMS ───────────────────────────────────────────────────────────────────────────────
def watch_systems(get, now):
    items, src, errs = [], {}, []
    ev = {"source": "FORGE system health (heartbeats, AI health)", "window": "now", "fetchedAt": int(now * 1000)}
    h = get("/api/system/health")
    src["loop:"] = src["ai"] = ok = isinstance(h, dict) and isinstance(h.get("loops"), list)
    if ok:
        red = set(h.get("redLoops") or [])
        for lp in h["loops"]:
            name = str(lp.get("loop") or "")
            if name in red and name.startswith(_LOOPS):
                items.append({"key": f"loop:{name}", "title": f"{lp.get('label') or name} loop is down",
                              "why": f"Last beat {_dur(lp.get('ageSec'))} ago"
                                     + (f"; last error: {daycare_board._clip(lp.get('lastError'), 120)}" if lp.get("lastError") else ""),
                              "severity": "high", "owner": "owner", "center": "all", "evidence": ev})
        ai = h.get("ai") or {}
        if ai.get("ok") is False:
            items.append({"key": "ai", "title": "Claude is down — the agents' brain is off",
                          "why": daycare_board._clip(ai.get("reason") or ai.get("lastError") or "hard-down", 200),
                          "severity": "high", "owner": "owner", "center": "all", "evidence": ev})
    else:
        errs.append("system health: " + _err(h, "health"))

    def dep(key, res, valid, dead, title, why):
        """valid = the read came back in its own shape (a 401 / loopback error is NOT a clean bill)."""
        src[key] = bool(valid)
        if not valid:
            errs.append(f"{key[4:]}: {_err(res, key[4:])}")
        elif dead:
            items.append({"key": key, "title": title, "why": daycare_board._clip(why, 200), "severity": "high",
                          "owner": "owner", "center": "all", "evidence": ev})
    s = get("/api/stripe/status")
    s = s if isinstance(s, dict) else {}
    dep("dep:stripe", s, "configured" in s, s.get("configured") and s.get("ok") is False,
        "Stripe key is failing", s.get("detail") or "Stripe /balance check failed")
    gh = get("/api/daycare/ghl/health")
    gh = gh if isinstance(gh, dict) else {}
    dep("dep:ghl", gh, "connected" in gh, gh.get("hasKeys") and gh.get("connected") is False,
        "Daycare GoHighLevel unreachable", gh.get("detail") or "GHL contact read failed")
    m = get("/api/daycare/mail", {"days": MAIL_DAYS, "limit": MAIL_LIMIT})
    m = m if isinstance(m, dict) else {}
    dep("dep:gmail", m, m.get("via") == "gmail", m.get("authDead"), "Gmail login rejected — re-consent needed",
        "Google refused the daycare Gmail refresh token; mail is Unknown until the owner re-consents.")
    f = get("/api/daycare/ads/feed", {"fresh": "0"})
    f = f if isinstance(f, dict) else {}
    dep("dep:meta", f, f.get("kind") == "daycare_ads_feed", f.get("authError"),
        "Pipeboard / Meta login rejected — ad numbers Unknown", f.get("error") or "Pipeboard rejected the daycare token")
    status = {"ok": all(src.values()), "sources": src}
    if errs:
        status["error"] = "; ".join(errs)[:300]
    return items, status


# ── the round ─────────────────────────────────────────────────────────────────────────────
WATCHES = (("inbox", watch_inbox), ("enrollment", watch_enrollment), ("billing", watch_billing),
           ("ads", watch_ads), ("social", watch_social), ("roster", watch_roster), ("systems", watch_systems))
_RUN = threading.Lock()


def _loopback(path, query=None):
    import telegram_agent
    return telegram_agent._http("GET", path, query=query, timeout=120)


def _memo(get):
    """One fetch per (path, query) per round — the watches share reads (mail, feed, children)."""
    cache, locks, guard = {}, {}, threading.Lock()

    def g(path, query=None):
        k = (path, tuple(sorted((str(a), str(b)) for a, b in (query or {}).items())))
        with guard:
            lk = locks.setdefault(k, threading.Lock())
        with lk:
            if k not in cache:
                try:
                    cache[k] = get(path, query)
                except Exception as e:  # noqa: BLE001 — a fetch error is a failed read, never a crash
                    cache[k] = {"ok": False, "error": f"read failed: {type(e).__name__}"}
            return cache[k]
    return g


def _one(fn, get, now):
    try:
        return fn(get, now)
    except Exception as e:  # noqa: BLE001 — one crashing watch never sinks the round
        return [], {"ok": False, "error": f"watch crashed: {type(e).__name__}"}


def run_round(get=None, now=None):
    """All seven watches → the board. -> {ok, ranAt, domains, open, new, closed, urgent, newItems, line,
    thirdPartyText} or {ok, skipped} when a round is already running. Zero Claude, nothing outward."""
    if not _RUN.acquire(blocking=False):
        return {"ok": True, "skipped": "a round is already running"}
    try:
        now = now or time.time()
        last = daycare_board.last_round().get("ranAt") or 0
        if 0 <= now * 1000 - last < MIN_GAP_SEC * 1000:   # a chat loop can't hammer GHL / Gmail / Meta
            return {"ok": True, "skipped": f"a round ran {int(now - last / 1000)} s ago — read GET /api/daycare/board",
                    "line": daycare_board.last_round().get("line")}
        g = _memo(get or _loopback)
        with ThreadPoolExecutor(max_workers=len(WATCHES)) as ex:
            futs = [(d, ex.submit(_one, fn, g, now)) for d, fn in WATCHES]
            results = [{"domain": d, "items": f.result()[0], "status": f.result()[1]} for d, f in futs]
        inbox = next(r["status"] for r in results if r["domain"] == "inbox")
        desk = inbox.pop("mailDesk", None) or {"ok": False, "error": inbox.get("error") or "inbox watch failed",
                                                "at": int(now * 1000)}   # never leave old subjects up as current
        out = daycare_board.apply_round(results, now=now, mail_desk=desk)
        shown = (out.get("newItems") or []) + (out.get("urgent") or [])
        return {"ok": True, "ranAt": out["lastRound"]["ranAt"], "domains": out["domains"], "open": out["open"],
                "new": out["new"], "closed": out["closed"], "urgent": out["urgent"], "newItems": out["newItems"],
                "line": out["line"], "thirdPartyText": any(i.get("domain") == "inbox" for i in shown)}
    finally:
        _RUN.release()
