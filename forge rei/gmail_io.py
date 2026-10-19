#!/usr/bin/env python3
"""gmail_io.py — the daycare's Gmail, READ-ONLY, DAYCARE MAIL ONLY (stdlib urllib, no deps).

Owner 2026-10-18: management@ and yahjair@atouchofblessing.com are both delivered into ONE
Google account (yahjair@). One `gmail.readonly` refresh token lives in the box's
forge-daycare/config/daycare.env: GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_YAHJAIR
(secret — push.sh ships it, never git, 404 over HTTP). There is no `gws` binary on the box: these
routes ARE the box's Gmail path (GET /api/daycare/mail, /api/daycare/mail/thread). Claude Code
sessions on the Mac keep using the `gws` CLI.

  search(query, limit, page_token, known_emails)   metadata-only DAYCARE rows (filtered here)
  thread(thread_id, max_chars, known_emails)       one DAYCARE thread as plaintext, on demand
  daycare_filter(row, known_emails)                bucket | None  (rules only — no Claude)
  mail_view / thread_view                          the routes' payloads: dicts, never raise

Scope gate: a message that fails daycare_filter NEVER leaves this module — it is counted
(`filteredOut`) and dropped. Verizon, Vercel, newsletters, marketing, personal Square payments,
Search Console … are dropped. READ-ONLY: this file makes GET calls to Gmail and one POST to
Google's token endpoint — no send/modify/trash/draft call exists here. Errors are typed and never
carry a token or an upstream body. Kept in memory only: the access token and the known-guardian
email set (10 min). No message body is cached, logged or written anywhere.
Selfcheck (fake transport, no network): python3 gmail_io.py · Tests: python3 test_gmail_io.py
"""
from __future__ import annotations

import base64
import email.utils
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
_UA = "forge-reios/1.0 (+gmail_io)"
_SKEW = 60                    # refresh ~60 s before Google's expiry
_AUTH_DEAD_TTL = 15 * 60      # a rejected refresh token: stop calling for 15 min (pipeboard_io pattern)
_KNOWN_TTL = 10 * 60
MAX_LIMIT = 50
MAX_CHARS = 4000
BUCKETS = ("parent", "lead", "billing", "vendor", "licensing", "system")
_HDRS = ("From", "To", "Subject", "Date")
_ID = re.compile(r"[A-Za-z0-9_-]{6,64}")


class GmailError(RuntimeError):
    """Any Gmail failure. The message is safe to show: no token, no upstream body."""


class GmailAuthError(GmailError):
    """Google refused the refresh/access token — the owner must re-consent."""


_LOCK = threading.Lock()
_TOK = {"access": "", "exp": 0.0}
_DEAD = [0.0]
_KNOWN = {"at": 0.0, "emails": frozenset()}


def _urlopen(req, timeout):       # the one network seam (tests swap it)
    return urllib.request.urlopen(req, timeout=timeout)


def _env():
    import daycare_supabase
    return daycare_supabase._read_env()


def _cfg():
    """Same picker as the daycare modules: process env first, then daycare.env."""
    try:
        values = _env()
    except Exception:  # noqa: BLE001 — config IO never breaks a read
        values = {}
    def pick(n):
        return (os.environ.get(n) or values.get(n) or "").strip()
    return {"client_id": pick("GMAIL_CLIENT_ID"), "client_secret": pick("GMAIL_CLIENT_SECRET"),
            "refresh_token": pick("GMAIL_REFRESH_YAHJAIR")}


def configured():
    return all(_cfg().values())


def auth_dead():
    return time.time() < _DEAD[0]


def _mark_dead():
    _DEAD[0] = time.time() + _AUTH_DEAD_TTL
    _TOK.update(access="", exp=0.0)


def _access_token():
    # ponytail: one global lock = one refresh at a time; fine for one mailbox, per-account locks if more.
    with _LOCK:
        if auth_dead():
            raise GmailAuthError("Google rejected the Gmail login recently — re-consent needed (retrying in ≤15 min)")
        if _TOK["access"] and time.time() < _TOK["exp"] - _SKEW:
            return _TOK["access"]
        c = _cfg()
        if not all(c.values()):
            raise GmailError("Gmail is not connected (GMAIL_* missing in daycare.env)")
        req = urllib.request.Request(
            TOKEN_URL, data=urllib.parse.urlencode({**c, "grant_type": "refresh_token"}).encode(),
            method="POST", headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": _UA})
        try:
            with _urlopen(req, 30) as r:
                d = json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403):        # invalid_grant / invalid_client / revoked consent
                _mark_dead()
                raise GmailAuthError(f"Google rejected the Gmail refresh token (HTTP {e.code}) — "
                                     "re-consent needed") from None
            raise GmailError(f"Google token endpoint HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise GmailError(f"Google token endpoint unreachable: {type(e).__name__}") from None
        tok = str(d.get("access_token") or "")
        if not tok:
            raise GmailError("Google returned no access token")
        try:
            ttl = float(d.get("expires_in") or 3600)
        except (TypeError, ValueError):
            ttl = 3600.0
        _TOK.update(access=tok, exp=time.time() + ttl)
        return tok


def _get(path, params=None, retry=True):
    """One Gmail API GET (the only verb this module sends to Gmail)."""
    url = API + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    req = urllib.request.Request(url, method="GET", headers={
        "Authorization": f"Bearer {_access_token()}", "Accept": "application/json", "User-Agent": _UA})
    try:
        with _urlopen(req, 30) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        if e.code == 401 and retry:             # access token died early: one fresh refresh
            with _LOCK:
                _TOK.update(access="", exp=0.0)
            return _get(path, params, retry=False)
        if e.code == 401:
            _mark_dead()
            raise GmailAuthError("Gmail refused the access token (HTTP 401) — re-consent needed") from None
        raise GmailError("Gmail: not found" if e.code == 404 else f"Gmail HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise GmailError(f"Gmail unreachable: {type(e).__name__}") from None


# ── text hygiene ─────────────────────────────────────────────────────────────
def _patterns():
    try:  # one list of vendor key shapes (coaching + action log), plus Google's own
        import action_log
        base = list(action_log._PATTERNS)
    except Exception:  # noqa: BLE001
        base = []
    return base + [re.compile(r"\bya29\.[A-Za-z0-9._-]{10,}"),          # Google access token
                   re.compile(r"\b1//[A-Za-z0-9_-]{20,}"),               # Google refresh token
                   re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{10,}"),           # Google client secret
                   re.compile(r"\b[rsp]k_(?:live|test)_[A-Za-z0-9]{8,}")]


_SECRETS = _patterns()


def scrub(s):
    """Secret-shaped strings out of any mail text before it leaves this module."""
    s = str(s or "")
    for p in _SECRETS:
        s = p.sub("[redacted]", s)
    return s


def _clean(s, n):
    s = re.sub(r"\s+", " ", scrub(s)).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


class _Text(HTMLParser):
    _SKIP = {"script", "style", "head", "title"}
    _BREAK = {"br", "p", "div", "li", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self.skip += 1
        elif tag in self._BREAK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self._BREAK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def strip_html(s):
    p = _Text()
    try:
        p.feed(s or "")
        p.close()
    except Exception:  # noqa: BLE001 — malformed markup: crude fallback, never the raw tags
        return html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return "".join(p.out)


def _decode(data):
    try:
        return base64.urlsafe_b64decode(str(data) + "=" * (-len(str(data)) % 4)).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return ""


def _parts(p):
    yield p
    for c in p.get("parts") or []:
        yield from _parts(c)


def _body(payload):
    """Plain text of one message: text/plain parts, else HTML stripped. Attachments skipped."""
    plain, rich = [], []
    for p in _parts(payload or {}):
        data = (p.get("body") or {}).get("data")
        if not data or p.get("filename"):
            continue
        mt = str(p.get("mimeType") or "").lower()
        if mt == "text/plain":
            plain.append(_decode(data))
        elif mt == "text/html":
            rich.append(strip_html(_decode(data)))
    return "\n".join(plain or rich)


def _collapse(s):
    s = re.sub(r"[ \t\r\f\v ]+", " ", s)
    return re.sub(r"\s*\n\s*", "\n", s).strip()


def _headers(payload):
    return {str(h.get("name") or "").lower(): str(h.get("value") or "")
            for h in (payload or {}).get("headers") or []}


def _row(m):
    h = _headers(m.get("payload"))
    labels = [str(x) for x in m.get("labelIds") or []]
    try:
        date = datetime.fromtimestamp(int(m.get("internalDate")) / 1000, timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        date = h.get("date", "")
    return {"id": str(m.get("id") or ""), "threadId": str(m.get("threadId") or ""), "date": date,
            "from": _clean(h.get("from"), 200), "to": _clean(h.get("to"), 300),
            "subject": _clean(h.get("subject"), 200),
            "snippet": _clean(html.unescape(str(m.get("snippet") or "")), 200),
            "labels": labels, "unread": "UNREAD" in labels}


# ── the daycare gate (rules only) ────────────────────────────────────────────
FORM_SENDER = "noreply@atouchofblessing.com"          # enrollment / intake form mails
# Always dropped, whatever they mention (owner: Verizon, Vercel, personal Square, Search Console).
# ponytail: a Square payment TO a daycare family is dropped too — match payee names if that matters.
_NOISE = ("verizon", "vercel", "squareup", "sc-noreply@google.com")
_SYSTEM = ("supabase.io", "supabase.com", "stripe.com", "facebookmail.com", "facebook.com", "meta.com")
_DAYCARE_IDS = ("eqblpbeqothkpyqiafzs", "1175564690150627")   # Supabase project ref, daycare Meta account
_NAME = re.compile(r"touch of blessing|mother[’'`]?s touch", re.I)
_STRONG = re.compile(r"touch of blessing|mother[’'`]?s touch|\btuition\b|\bchild ?care\b|\bday ?care\b"
                     r"|\bccis\b|\bpre-?k\b|\bpre-?school", re.I)
_WEAK = re.compile(r"\btours?\b|\benroll|\bregistration\b|\bwait ?list|\binvoice\b|\bopenings?\b", re.I)
_CHILD = re.compile(r"\b(child|children|kids?|son|daughter|toddler|infant|baby|newborn)\b", re.I)
_BILLING = re.compile(r"tuition|invoice|payment|\bpaid\b|receipt|balance|refund|charge|payout|dispute"
                      r"|\bccis\b|subsidy|co-?pay|\bbill(ing)?\b", re.I)
_LICENSING = re.compile(r"licens|inspection|certificate of compliance|ocdel|keystone stars"
                        r"|department of human services|\bdhs\b|regulat|citation|clearances?", re.I)
_LEAD = re.compile(r"\btours?\b|enroll|wait ?list|availability|openings?|interested|inquir|start date"
                   r"|contact form|registration|looking for", re.I)


def _addrs(s):
    return [a.strip().lower() for _, a in email.utils.getaddresses([s or ""]) if "@" in a]


def daycare_filter(row, known_emails=()):
    """The gate. -> bucket ('parent'|'lead'|'billing'|'vendor'|'licensing'|'system') when the
    message is DAYCARE mail, else None (dropped, only counted). Rules only — no Claude.
    known_emails = lowercased guardian/contact emails (a filter set, never returned)."""
    frm, to = _addrs(row.get("from")), _addrs(row.get("to"))
    sender = frm[0] if frm else ""
    text = f"{row.get('subject') or ''} {row.get('snippet') or ''}"
    if FORM_SENDER in frm or FORM_SENDER in to:
        return "lead"
    if not sender or any(n in sender for n in _NOISE):
        return None
    if sender in known_emails:
        return "billing" if _BILLING.search(text) else "parent"
    domain = sender.rpartition("@")[2]
    if any(domain == d or domain.endswith("." + d) for d in _SYSTEM):    # Supabase/Stripe/Meta notice
        if not (_NAME.search(text) or any(i in text for i in _DAYCARE_IDS)):
            return None                                                   # …only when it's about the daycare
        return "billing" if _BILLING.search(text) else "system"
    if not (_STRONG.search(text) or (_WEAK.search(text) and _CHILD.search(text))):
        return None
    if _LICENSING.search(text) or domain.endswith(".gov"):
        return "licensing"
    if _BILLING.search(text):
        return "billing"
    if _LEAD.search(text) or _CHILD.search(text):
        return "lead"
    return "vendor"


def daycare_query(days=7, q="", known=()):
    """Gmail-side pre-narrow: window, no promotions/social/forums/sent/drafts/chats, AND at least one
    daycare signal (form sender, a daycare word, or a known guardian sender). daycare_filter is the
    gate; this only saves fetches. A guardian with a NEW address and no daycare word is missed by
    the pre-narrow — the known set refreshes from GHL every 10 min."""
    sig = [f"from:{FORM_SENDER}", f"to:{FORM_SENDER}", '"touch of blessings"', '"mother\'s touch"',
           "tuition", "enrollment", "childcare", '"child care"', "daycare", "CCIS"]
    kn = sorted(e for e in (known or ()) if re.fullmatch(r"[\w.+-]+@[\w.-]+", e))[:40]
    if kn:
        sig.append("from:(" + " OR ".join(kn) + ")")
    base = (f"newer_than:{int(days)}d -category:promotions -category:social -category:forums "
            f"-in:sent -in:drafts -in:chats ({' OR '.join(sig)})")
    q = re.sub(r"\s+", " ", str(q or ""))[:200].strip()
    return f"{base} ({q})" if q else base


def _valid_id(v):
    v = str(v or "").strip()
    if not _ID.fullmatch(v):
        raise GmailError("id must be a Gmail thread/message id")
    return v


def search(query, limit=25, page_token=None, known_emails=()):
    """DAYCARE rows for a Gmail query — metadata only, no bodies. A row that fails daycare_filter
    never leaves this module. Pages (≤3 Gmail pages) until `limit` daycare rows are kept.
    -> {rows (each + bucket), filteredOut, nextPage}"""
    limit = max(1, min(int(limit or 25), MAX_LIMIT))
    rows, dropped, token, seen = [], 0, page_token, set()
    for _ in range(3):
        params = {"q": query or "", "maxResults": limit}
        if token:
            params["pageToken"] = str(token)[:300]
        d = _get("/messages", params)
        token = d.get("nextPageToken")
        # ponytail: one metadata GET per message (≤50 sequential); Gmail's batch endpoint if it gets slow.
        for m in d.get("messages") or []:
            mid = str((m or {}).get("id") or "")
            if not _ID.fullmatch(mid) or mid in seen:
                continue
            seen.add(mid)
            r = _row(_get(f"/messages/{mid}", {"format": "metadata", "metadataHeaders": list(_HDRS)}))
            b = daycare_filter(r, known_emails)
            if b is None:
                dropped += 1
                continue
            rows.append(dict(r, bucket=b))
            if len(rows) >= limit:
                return {"rows": rows, "filteredOut": dropped, "nextPage": token}
        if not token:
            break
    return {"rows": rows, "filteredOut": dropped, "nextPage": token}


def thread(thread_id, max_chars=MAX_CHARS, known_emails=(), meta_only=False):
    """One DAYCARE thread as plaintext. Headers first (the gate); the body is fetched only when
    the thread passes, decoded on demand and never stored. Raises GmailError when it is not daycare.
    meta_only=True stops after the gated headers (no body GET) — the board's "answered?" check."""
    tid = _valid_id(thread_id)
    meta = _get(f"/threads/{tid}", {"format": "metadata", "metadataHeaders": list(_HDRS)})
    heads = [_row(m) for m in meta.get("messages") or []]
    ok = {r["id"]: b for r in heads if (b := daycare_filter(r, known_emails))}      # per-MESSAGE gate
    if not ok:
        raise GmailError("not daycare mail — out of scope (this inbox reads daycare mail only)")
    own = "@" + FORM_SENDER.rpartition("@")[2]      # our own replies inside a daycare thread are daycare too
    first = next(iter(ok.values()))
    for r in heads:
        frm = _addrs(r.get("from"))
        if r["id"] not in ok and frm and frm[0].endswith(own):
            ok[r["id"]] = first
    heads = [r for r in heads if r["id"] in ok]
    if meta_only:
        return {"id": tid, "bucket": first, "count": len(heads), "metaOnly": True, "text": "", "truncated": False,
                "messages": [{k: r[k] for k in ("id", "date", "from", "to", "subject", "unread")} for r in heads]}
    full = _get(f"/threads/{tid}", {"format": "full"})
    parts = []
    for m in full.get("messages") or []:
        r = _row(m)
        if r["id"] not in ok:                  # a non-daycare message in the same thread stays out
            continue
        parts.append(f"--- {r['date']} | From: {r['from']} | {r['subject']}\n{_body(m.get('payload'))}")
    text = scrub(_collapse("\n".join(parts)))
    cut = len(text) > max_chars
    return {"id": tid, "bucket": next(iter(ok.values())), "count": len(heads),
            "messages": [{k: r[k] for k in ("id", "date", "from", "to", "subject", "unread")} for r in heads],
            "text": text[:max_chars] + ("…" if cut else ""), "truncated": cut}


def known_emails(client, ttl=_KNOWN_TTL):
    """Guardian/contact emails from the daycare GHL (daycare_ghl.iter_contacts), lowercased, held
    in memory 10 min. A filter set only — never returned to the model, never written. A failed
    read returns the last good set (or empty) and retries on the next call."""
    if _KNOWN["at"] and time.time() - _KNOWN["at"] < ttl:
        return _KNOWN["emails"]
    try:
        import daycare_ghl
        out = set()
        for c in daycare_ghl.iter_contacts(client):
            for e in [c.get("email")] + list(c.get("additionalEmails") or []):
                e = e.get("email") if isinstance(e, dict) else e
                if e and "@" in str(e):
                    out.add(str(e).strip().lower())
    except Exception:  # noqa: BLE001 — GHL down: the other rules still gate
        return _KNOWN["emails"]
    _KNOWN.update(at=time.time(), emails=frozenset(out))
    return _KNOWN["emails"]


# ── route payloads (never raise) ─────────────────────────────────────────────
def _int(v, default, lo, hi):
    try:
        return max(lo, min(int(v), hi))
    except (TypeError, ValueError):
        return default


def _down(e=None):
    """The ok:false payload (HTTP 200, like other integrations), or None when Gmail is usable."""
    base = {"ok": False, "via": "gmail", "fetchedAt": int(time.time() * 1000)}
    if not configured():
        return dict(base, configured=False, error="Gmail is not connected — GMAIL_CLIENT_ID / "
                    "GMAIL_CLIENT_SECRET / GMAIL_REFRESH_YAHJAIR missing in daycare.env. Mail is Unknown.")
    if isinstance(e, GmailAuthError) or (e is None and auth_dead()):
        return dict(base, configured=False, authDead=True,
                    error=str(e or "Google rejected the Gmail login — re-consent needed. Mail is Unknown."))
    return None if e is None else dict(base, configured=True, error=str(e))


def mail_view(days=7, limit=25, q="", bucket="", page_token=None, known=None):
    """GET /api/daycare/mail — daycare-only, read-only list."""
    bad = _down()
    if bad:
        return bad
    days, limit = _int(days, 7, 1, 90), _int(limit, 25, 1, MAX_LIMIT)
    bucket = str(bucket or "").strip().lower()
    if bucket and bucket not in BUCKETS:
        return {"ok": False, "via": "gmail", "error": f"bucket must be one of {', '.join(BUCKETS)}"}
    try:
        kn = known() if callable(known) else (known or ())
        res = search(daycare_query(days, q, kn), limit, page_token, kn)
    except GmailError as e:
        return _down(e)
    rows = [r for r in res["rows"] if not bucket or r["bucket"] == bucket]
    now = datetime.now(timezone.utc)
    return {"ok": True, "via": "gmail", "configured": True, "rows": rows, "count": len(rows),
            "filteredOut": res["filteredOut"], "unreadCount": sum(1 for r in rows if r["unread"]),
            "bucket": bucket or None, "nextPage": res["nextPage"],   # not "…Token": redact() would eat it
            "dateRange": {"days": days, "since": (now - timedelta(days=days)).date().isoformat(),
                          "until": now.date().isoformat(), "label": f"last {days} days (Gmail newer_than:{days}d)"},
            "fetchedAt": int(time.time() * 1000)}


def thread_view(thread_id, known=None, max_chars=MAX_CHARS, meta_only=False):
    """GET /api/daycare/mail/thread — one daycare thread, plaintext ≤ max_chars, read-only.
    ?meta=1 → headers only (who wrote when), no body fetched."""
    bad = _down()
    if bad:
        return bad
    try:
        t = thread(thread_id, max_chars, known() if callable(known) else (known or ()), meta_only=meta_only)
    except GmailError as e:
        out = _down(e)
        if "out of scope" in str(e):
            out["outOfScope"] = True
        return out
    return {"ok": True, "via": "gmail", "configured": True, **t, "fetchedAt": int(time.time() * 1000)}


if __name__ == "__main__":    # selfcheck: fake Google, no network, no real env file read
    import io

    def b64(s):
        return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

    MSGS = {"msg0001": ("Seara <seara@x.com>", "Mia's tuition this week", "Hi, is tuition due Friday?"),
            "msg0002": ("Verizon <alerts@verizon.com>", "Your bill is ready", "Tour your new plan"),
            "msg0003": ("noreply@atouchofblessing.com", "Family Contact Form", "New family form")}
    seen = []

    class R(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout):
        seen.append((req.get_method(), req.full_url))
        if req.full_url == TOKEN_URL:
            return R(json.dumps({"access_token": "ya29.FAKEFAKEFAKEFAKE", "expires_in": 3600}).encode())
        path = urllib.parse.urlparse(req.full_url).path.rsplit("/", 1)[-1]
        if path == "messages":
            return R(json.dumps({"messages": [{"id": k} for k in MSGS]}).encode())
        if path in MSGS:
            f, s, sn = MSGS[path]
            return R(json.dumps({"id": path, "threadId": "t" + path, "labelIds": ["UNREAD"], "snippet": sn,
                                 "internalDate": "1760000000000", "payload": {"headers": [
                                     {"name": "From", "value": f}, {"name": "Subject", "value": s}]}}).encode())
        q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        m = {"id": "msg0001", "internalDate": "1760000000000", "payload": {"headers": [
            {"name": "From", "value": MSGS["msg0001"][0]}, {"name": "Subject", "value": MSGS["msg0001"][1]}],
            "mimeType": "text/html", "body": {"data": b64("<p>Hi&nbsp;team,</p><script>x()</script><b>tuition</b> ok?")}}}
        return R(json.dumps({"messages": [m] if q.get("format") != ["full"] else [m]}).encode())

    _urlopen, _env = fake, (lambda: {})
    os.environ.update(GMAIL_CLIENT_ID="cid", GMAIL_CLIENT_SECRET="GOCSPX-fakefakefake", GMAIL_REFRESH_YAHJAIR="1//fake")
    out = mail_view(7, 10, known={"seara@x.com"})
    assert out["ok"] and [r["id"] for r in out["rows"]] == ["msg0001", "msg0003"] and out["filteredOut"] == 1, out
    assert out["rows"][0]["bucket"] == "billing" and out["rows"][1]["bucket"] == "lead", out["rows"]
    t = thread_view("tmsg0001", known={"seara@x.com"})
    assert t["ok"] and "tuition ok?" in t["text"] and "x()" not in t["text"] and "<p>" not in t["text"], t
    assert all(m == "GET" for m, u in seen if u.startswith(API)) and sum(1 for _, u in seen if u == TOKEN_URL) == 1
    assert "ya29" not in json.dumps([out, t]) and "GOCSPX" not in json.dumps([out, t])
    print("gmail_io selfcheck OK — filter, token cache, HTML strip, GET-only")
